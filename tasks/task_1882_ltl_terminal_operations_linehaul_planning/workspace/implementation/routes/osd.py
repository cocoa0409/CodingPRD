"""OS&D case endpoints (PRD section 3.8)."""
from flask import Blueprint, request

import db
from errors import err_invalid_request, err_invalid_state
from middleware import require_roles
from response import success, success_list
from routes.common import (as_enum, as_int, body_json, get_path, new_record,
                           paginate, refresh_osd_hold, resolve_fk, ser_case,
                           touch)
from services.calculations import CASE_KINDS, osd_liability

bp = Blueprint("osd", __name__)

_READ_ROLES = ("TerminalAdmin", "RatingClerk", "OsdClerk")


@bp.route("/ltl/osd-cases", methods=["POST"])
@require_roles("OsdClerk")
def create_case():
    body = body_json()
    shipment = resolve_fk("shipments", body.get("shipment_id"), "shipment_id")
    case_kind = as_enum(body, "case_kind", CASE_KINDS)
    claimed = as_int(body, "claimed_amount_cents", minimum=0)
    items = body.get("item_amounts_cents")
    if not isinstance(items, list) or not items or any(
            not isinstance(x, int) or isinstance(x, bool) or x < 0 for x in items):
        raise err_invalid_request(
            "item_amounts_cents must be a non-empty list of integers >= 0")
    rec = new_record({
        "shipment_id": shipment["id"], "case_kind": case_kind,
        "claimed_amount_cents": claimed,
        "item_amounts_cents": [int(x) for x in items],
        "awarded_amount_cents": 0,
        "status": "OPEN",
    })
    db.store["osd_cases"][rec["id"]] = rec
    # Opening a case sets the hold immediately.
    refresh_osd_hold(shipment)
    return success(ser_case(rec), 201)


@bp.route("/ltl/osd-cases", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_cases():
    items = list(db.store["osd_cases"].values())
    for param in ("shipment_id", "case_kind", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c.get(param) == value]
    page, total, limit, offset = paginate(items)
    return success_list([ser_case(c) for c in page], total, limit, offset)


@bp.route("/ltl/osd-cases/<caseId>", methods=["GET"])
@require_roles(*_READ_ROLES)
def get_case(caseId):
    return success(ser_case(get_path("osd_cases", caseId)))


@bp.route("/ltl/osd-cases/<caseId>/review", methods=["POST"])
@require_roles("OsdClerk")
def review_case(caseId):
    case = get_path("osd_cases", caseId)
    if case["status"] != "OPEN":
        raise err_invalid_state("Only an OPEN case can move to UNDER_REVIEW")
    case["status"] = "UNDER_REVIEW"
    touch(case)
    return success(ser_case(case))


@bp.route("/ltl/osd-cases/<caseId>/resolve", methods=["POST"])
@require_roles("OsdClerk")
def resolve_case(caseId):
    case = get_path("osd_cases", caseId)
    if case["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Only an UNDER_REVIEW case can be resolved")
    shipment = db.store["shipments"][case["shipment_id"]]
    case["awarded_amount_cents"] = osd_liability(
        case["claimed_amount_cents"], case["item_amounts_cents"],
        shipment["actual_weight_lbs"], shipment["nmfc_class"],
        shipment["rated_amount_cents"])
    case["status"] = "RESOLVED"
    touch(case)
    # Billed-then-resolved: offset the award against billed revenue.
    if shipment["rating_status"] == "BILLED":
        shipment["billed_amount_cents"] -= case["awarded_amount_cents"]
        touch(shipment)
    refresh_osd_hold(shipment)
    return success(ser_case(case))


@bp.route("/ltl/osd-cases/<caseId>/deny", methods=["POST"])
@require_roles("OsdClerk")
def deny_case(caseId):
    case = get_path("osd_cases", caseId)
    if case["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Only an UNDER_REVIEW case can be denied")
    case["awarded_amount_cents"] = 0
    case["status"] = "DENIED"
    touch(case)
    shipment = db.store["shipments"][case["shipment_id"]]
    refresh_osd_hold(shipment)
    return success(ser_case(case))
