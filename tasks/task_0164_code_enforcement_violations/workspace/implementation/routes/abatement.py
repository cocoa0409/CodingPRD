"""AbatementOrder endpoints (PRD §3.11)."""

from flask import Blueprint

from db import db, common_fields, touch
from errors import err
from middleware import require_roles
from response import success, list_success
from services import domain, serialize
from services.helpers import (
    get_body,
    lookup,
    pagination_params,
    paginate,
    require_enum,
    require_int,
    resolve_ref,
    sort_by_created,
)

bp = Blueprint("abatement", __name__)

ACTION_KINDS = {"BOARD_UP", "DEMOLITION"}


@bp.post("/abatement-orders")
@require_roles("CodeOfficer")
def order_abatement():
    body = get_body()
    if "case_id" not in body or body["case_id"] is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: case_id")
    require_enum(body, "action_kind", ACTION_KINDS)
    estimated = require_int(body, "estimated_cost_cents")
    case = resolve_ref(db.cases, body["case_id"])

    if body["action_kind"] == "DEMOLITION":
        # Requires VACANT occupancy and a HAZARD-class notice in {OVERDUE, UPHELD}.
        prop = db.properties.get(case["property_id"])
        vacant = prop is not None and prop["occupancy"] == "VACANT"
        has_hazard = False
        for n in domain.notices_for_case(case["id"]):
            domain.evaluate_notice(n)
            if n["violation_class"] == "HAZARD" and n["status"] in ("OVERDUE", "UPHELD"):
                has_hazard = True
                break
        if not (vacant and has_hazard):
            raise err("ERR_DEMOLITION_NOT_PERMITTED", "demolition prerequisites not met")

    record = common_fields()
    record.update({
        "case_id": case["id"],
        "action_kind": body["action_kind"],
        "estimated_cost_cents": estimated,
        "actual_cost_cents": None,
        "status": "ORDERED",
    })
    db.abatement_orders[record["id"]] = record

    domain.recompute_case(case)  # -> ABATEMENT
    return success(serialize.abatement_out(record), status=201)


@bp.get("/abatement-orders/<aid>")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk")
def get_abatement(aid):
    record = lookup(db.abatement_orders, aid)
    return success(serialize.abatement_out(record), status=200)


@bp.get("/cases/<cid>/abatement-orders")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk")
def list_case_abatement(cid):
    lookup(db.cases, cid)
    limit, offset = pagination_params()
    items = [a for a in db.abatement_orders.values() if a["case_id"] == cid]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize.abatement_out(a) for a in page], limit, offset, total)


@bp.post("/abatement-orders/<aid>/start")
@require_roles("CodeOfficer")
def start_abatement(aid):
    order = lookup(db.abatement_orders, aid)
    if order["status"] != "ORDERED":
        raise err("ERR_INVALID_STATE", "order is not ORDERED")
    case = db.cases.get(order["case_id"])
    if case is not None:
        domain.refresh_case_for_read(case)
        if case["posture"] not in ("ABATEMENT", "ACTIVE"):
            raise err("ERR_INVALID_STATE", "case posture does not permit starting")
    order["status"] = "IN_PROGRESS"
    touch(order)
    if case is not None:
        domain.recompute_case(case)
    return success(serialize.abatement_out(order), status=200)


@bp.post("/abatement-orders/<aid>/complete")
@require_roles("CodeOfficer")
def complete_abatement(aid):
    order = lookup(db.abatement_orders, aid)
    body = get_body()
    if order["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "order is not IN_PROGRESS")
    if "actual_cost_cents" not in body or body["actual_cost_cents"] is None:
        raise err("ERR_MISSING_ACTUAL_COST", "actual_cost_cents is required")
    actual = require_int(body, "actual_cost_cents")

    order["status"] = "COMPLETED"
    order["actual_cost_cents"] = actual
    touch(order)

    case = db.cases.get(order["case_id"])
    if case is not None:
        # Attach ABATEMENT_COST Fine to the case's most recent UPHELD/OVERDUE notice.
        target = _most_recent_uph_or_overdue(case["id"])
        if target is not None:
            fine = common_fields()
            fine.update({
                "notice_id": target["id"],
                "source_kind": "ABATEMENT_COST",
                "assessed_cents": actual,
                "settlement_status": "OPEN",
            })
            db.fines[fine["id"]] = fine
        domain.recompute_case(case)

    return success(serialize.abatement_out(order), status=200)


@bp.post("/abatement-orders/<aid>/cancel")
@require_roles("CodeOfficer")
def cancel_abatement(aid):
    order = lookup(db.abatement_orders, aid)
    if order["status"] != "ORDERED":
        raise err("ERR_INVALID_STATE", "order is not ORDERED")
    order["status"] = "CANCELLED"
    touch(order)
    case = db.cases.get(order["case_id"])
    if case is not None:
        domain.recompute_case(case)
    return success(serialize.abatement_out(order), status=200)


def _most_recent_uph_or_overdue(case_id):
    """The case's most recently created notice in UPHELD or OVERDUE (PRD §3.11)."""
    candidates = []
    for n in domain.notices_for_case(case_id):
        domain.evaluate_notice(n)
        if n["status"] in ("UPHELD", "OVERDUE"):
            candidates.append(n)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    return candidates[-1]
