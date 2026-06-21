"""CourtOrder endpoints + branching state machine + final-judgment cascade
(PRD §3.7)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SUPPORT_ORDER_NOT_CALCULATED,
    ERR_DISCLOSURES_NOT_VERIFIED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_CASE_VERSION,
)
from middleware import (
    require_auth,
    get_json_body,
    paginate_params,
    slice_page,
    current_user_id,
)
from response import ok_object, ok_array
from services.common import (
    serialize,
    serialize_list,
    sorted_by_creation,
    get_case,
    assert_case_not_terminal,
    recompute_active_support_total,
    require,
)

bp = Blueprint("court_orders", __name__)

READ_ROLES = ["Clerk", "Judge", "Mediator", "Petitioner", "Respondent"]


@bp.post("/api/court-orders")
def create_court_order():
    require_auth(["Clerk", "Judge"])()
    body = get_json_body()

    # Existence (404) left-to-right.
    case_id = body.get("case_id")
    case = get_case(case_id)

    order_kind = body.get("order_kind")
    if order_kind not in ("TEMPORARY", "FINAL_JUDGMENT"):
        raise APIError(ERR_INVALID_REQUEST, 422, "order_kind must be TEMPORARY or FINAL_JUDGMENT")

    support_order_ids = body.get("support_order_ids")
    if not isinstance(support_order_ids, list) or len(support_order_ids) == 0:
        raise APIError(ERR_INVALID_REQUEST, 422, "support_order_ids must be a non-empty array")

    # Each referenced support order must EXIST and belong to the same case
    # (status NOT checked here — enforced at ENTER time).
    for soid in support_order_ids:
        so = require(db.support_orders, soid, "SupportOrder")
        if so["case_id"] != case_id:
            raise APIError(ERR_INVALID_REQUEST, 422, "support order not on this case")

    parenting_plan_id = body.get("parenting_plan_id")
    if order_kind == "FINAL_JUDGMENT" and parenting_plan_id is None:
        raise APIError(ERR_INVALID_REQUEST, 422, "parenting_plan_id required for FINAL_JUDGMENT")
    if parenting_plan_id is not None:
        plan = require(db.parenting_plans, parenting_plan_id, "ParentingPlan")
        if plan["case_id"] != case_id:
            raise APIError(ERR_INVALID_REQUEST, 422, "parenting plan not on this case")

    supersedes_order_id = body.get("supersedes_order_id")
    if supersedes_order_id is not None:
        sup = require(db.court_orders, supersedes_order_id, "CourtOrder")
        if sup["case_id"] != case_id:
            raise APIError(ERR_INVALID_REQUEST, 422, "superseded order not on this case")

    assert_case_not_terminal(case)

    order = {
        "case_id": case_id,
        "order_kind": order_kind,
        "support_order_ids": list(support_order_ids),
        "parenting_plan_id": parenting_plan_id,
        "supersedes_order_id": supersedes_order_id,
        "status": "DRAFT",
        "entered_at": None,
    }
    db.stamp_common(order)
    db.court_orders[order["id"]] = order
    return ok_object(serialize(order), 201)


@bp.get("/api/court-orders/<rid>")
def get_court_order(rid):
    require_auth(READ_ROLES)()
    o = require(db.court_orders, rid, "CourtOrder")
    return ok_object(serialize(o), 200)


@bp.get("/api/court-orders")
def list_court_orders():
    require_auth(READ_ROLES)()
    limit, offset = paginate_params(request.args)
    items = sorted_by_creation(list(db.court_orders.values()))
    case_id = request.args.get("case_id")
    plan_id = request.args.get("parenting_plan_id")
    supersedes = request.args.get("supersedes_order_id")
    if case_id is not None:
        items = [o for o in items if o["case_id"] == case_id]
    if plan_id is not None:
        items = [o for o in items if o["parenting_plan_id"] == plan_id]
    if supersedes is not None:
        items = [o for o in items if o["supersedes_order_id"] == supersedes]
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


def _had_default(case):
    # No ANSWER pleading exists -> the case proceeded on the default path.
    for p in db.pleadings.values():
        if p["case_id"] == case["id"] and p["pleading_type"] == "ANSWER":
            return False
    return True


@bp.post("/api/court-orders/<rid>/enter")
def enter_court_order(rid):
    require_auth(["Judge"])()
    order = require(db.court_orders, rid, "CourtOrder")
    case = get_case(order["case_id"])
    body = get_json_body()

    # State gate (ERR_INVALID_STATE): order must be DRAFT.
    if order["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Only a DRAFT order can be entered")

    # Case-status precondition per order kind (ERR_INVALID_STATE).
    if order["order_kind"] == "TEMPORARY":
        if case["status"] not in ("DISCOVERY", "MEDIATION", "DEFAULT_PENDING"):
            raise APIError(ERR_INVALID_STATE, 409, "TEMPORARY requires DISCOVERY/MEDIATION/DEFAULT_PENDING")
    else:  # FINAL_JUDGMENT
        if case["status"] != "AWAITING_JUDGMENT":
            raise APIError(ERR_INVALID_STATE, 409, "FINAL_JUDGMENT requires AWAITING_JUDGMENT")

    # Referential: every referenced support order must be CALCULATED.
    referenced = []
    for soid in order["support_order_ids"]:
        so = db.support_orders.get(soid)
        if so is None or so["status"] != "CALCULATED":
            raise APIError(ERR_SUPPORT_ORDER_NOT_CALCULATED, 409, "Referenced support order not CALCULATED")
        referenced.append(so)

    if order["order_kind"] == "FINAL_JUDGMENT":
        # Disclosures verified: both parties, or petitioner only on default path.
        pet_ok = case.get("petitioner_disclosure_verified", False)
        resp_ok = case.get("respondent_disclosure_verified", False)
        if not (pet_ok and resp_ok):
            if not (pet_ok and _had_default(case)):
                raise APIError(ERR_DISCLOSURES_NOT_VERIFIED, 409, "Disclosures not verified")

        # Segregation of duties: acting judge != case mediator.
        if case.get("mediator_user_id") is not None and \
                current_user_id() == case["mediator_user_id"]:
            raise APIError(ERR_SEGREGATION_OF_DUTIES, 403, "Judge mediated this case")

        # OCC: expected_case_version must match Case.version.
        expected = body.get("expected_case_version")
        if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
            raise APIError(ERR_INVALID_REQUEST, 422, "expected_case_version is required (integer)")
        if expected != case["version"]:
            raise APIError(ERR_STALE_CASE_VERSION, 412, "Stale case version")

    # --- commit: enter the order ---------------------------------------------
    order["entered_at"] = db.now_iso()
    order["status"] = "ENTERED"
    db.bump(order)

    # All referenced support orders -> ACTIVE; recompute case ledger.
    for so in referenced:
        so["status"] = "ACTIVE"
        db.bump(so)
    recompute_active_support_total(case)
    case_mutated = True

    if order["order_kind"] == "FINAL_JUDGMENT":
        # Cascade link A: supersede the prior TEMPORARY order if named.
        sup_id = order.get("supersedes_order_id")
        if sup_id is not None:
            sup = db.court_orders.get(sup_id)
            if sup is not None and sup["order_kind"] == "TEMPORARY" and sup["status"] == "ENTERED":
                sup["status"] = "SUPERSEDED"
                db.bump(sup)
                # Cascade link B: support orders referenced by the superseded
                # order but NOT by this final judgment -> VACATED.
                final_set = set(order["support_order_ids"])
                for soid in sup["support_order_ids"]:
                    if soid in final_set:
                        continue
                    so = db.support_orders.get(soid)
                    if so is not None and so["status"] != "VACATED":
                        so["status"] = "VACATED"
                        db.bump(so)
                recompute_active_support_total(case)

        # Record judge, advance case to terminal JUDGMENT_ENTERED.
        case["judge_user_id"] = current_user_id()
        case["status"] = "JUDGMENT_ENTERED"

    if case_mutated:
        db.bump(case)

    return ok_object(serialize(order), 200)
