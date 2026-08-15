"""PenaltyAssessment routes: assess, waive, settle, list, get."""

from flask import Blueprint, request as flask_request

import db
from errors import raise_err
from middleware import get_auth, require_role, get_body
from response import success_object, success_list, parse_pagination
from services import core

bp = Blueprint("penalties", __name__)


def _get_penalty_or_404(penalty_id):
    p = db.penalties.get(penalty_id)
    if p is None:
        raise_err("ERR_PENALTY_NOT_FOUND", "Penalty not found")
    return p


@bp.get("/penalties")
def list_penalties():
    get_auth()
    request_id = flask_request.args.get("request_id")
    check_in_id = flask_request.args.get("check_in_id")
    status = flask_request.args.get("status")
    items = sorted(db.penalties.values(), key=lambda p: p["_seq"])
    if request_id:
        items = [p for p in items if p["request_id"] == request_id]
    if check_in_id:
        items = [p for p in items if p["check_in_id"] == check_in_id]
    if status:
        items = [p for p in items if p["status"] == status]
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(p) for p in page], limit, offset, total)


@bp.get("/penalties/<id>")
def get_penalty(id):
    get_auth()
    penalty = _get_penalty_or_404(id)
    return success_object(core.serialize(penalty))


@bp.post("/penalties/<id>/assess")
def assess_penalty(id):
    _, role = get_auth()
    get_body()
    require_role(role, ["VendorCoordinator"])
    penalty = _get_penalty_or_404(id)

    if penalty["status"] != "ACCRUING":
        raise_err("ERR_PENALTY_INVALID_STATE", "Only an ACCRUING penalty can be assessed")

    request = db.requests.get(penalty["request_id"])
    case = db.cases.get(request["case_id"]) if request else None
    if case is None or case["status"] != "COMPLETED":
        raise_err("ERR_CASE_INVALID_STATE", "The penalty's case must be COMPLETED before assessment")

    vendor = db.vendors.get(request["vendor_id"]) if request else None
    vendor_delay_final = case["vendor_delay_minutes_final"] or 0
    surcharge = 0
    if vendor is not None:
        surcharge = min(
            vendor["late_penalty_cap_cents"],
            vendor_delay_final * vendor["delay_surcharge_per_minute_cents"],
        )
    penalty["delay_surcharge_cents"] = surcharge
    penalty["assessed_cents"] = penalty["time_charge_cents"] + surcharge
    penalty["outstanding_cents"] = penalty["assessed_cents"] - penalty["waived_cents"] - penalty["settled_cents"]
    penalty["status"] = "ASSESSED"
    core.touch(penalty)

    if request is not None:
        core.recompute_request_penalty_exposure(request["id"])
        core.recompute_vendor_rollups(request["vendor_id"])

    return success_object(core.serialize(penalty))


@bp.post("/penalties/<id>/waive")
def waive_penalty(id):
    user_id, role = get_auth()
    body = get_body(required=True)

    waive_amount_cents = body.get("waive_amount_cents")
    if waive_amount_cents is None or isinstance(waive_amount_cents, bool) or not isinstance(waive_amount_cents, int):
        raise_err("ERR_VALIDATION", "waive_amount_cents is required and must be an integer")
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise_err("ERR_VALIDATION", "reason is required")

    require_role(role, ["VendorCoordinator"])
    penalty = _get_penalty_or_404(id)

    if penalty["status"] != "ASSESSED":
        raise_err("ERR_PENALTY_INVALID_STATE", "Only an ASSESSED penalty can be waived")

    # SoD: the waiving coordinator must differ from the verifying coordinator
    # of the penalty's check-in.
    checkin = db.check_ins.get(penalty["check_in_id"])
    if checkin is not None and checkin.get("verified_by_user_id") == user_id:
        raise_err(
            "ERR_SEGREGATION_OF_DUTIES",
            "The verifying coordinator may not waive this penalty",
        )

    if waive_amount_cents > penalty["outstanding_cents"]:
        raise_err("ERR_WAIVER_EXCEEDS_OUTSTANDING", "Waiver exceeds the outstanding amount")

    penalty["waived_cents"] += waive_amount_cents
    penalty["outstanding_cents"] = penalty["assessed_cents"] - penalty["waived_cents"] - penalty["settled_cents"]
    if penalty["outstanding_cents"] == 0:
        penalty["status"] = "WAIVED_CLOSED"
    core.touch(penalty)

    request = db.requests.get(penalty["request_id"])
    if request is not None:
        core.recompute_request_penalty_exposure(request["id"])
        core.recompute_vendor_rollups(request["vendor_id"])

    return success_object(core.serialize(penalty))


@bp.post("/penalties/<id>/settle")
def settle_penalty(id):
    _, role = get_auth()
    body = get_body(required=True)

    settle_amount_cents = body.get("settle_amount_cents")
    if settle_amount_cents is None or isinstance(settle_amount_cents, bool) or not isinstance(settle_amount_cents, int):
        raise_err("ERR_VALIDATION", "settle_amount_cents is required and must be an integer")

    require_role(role, ["VendorCoordinator"])
    penalty = _get_penalty_or_404(id)

    if penalty["status"] != "ASSESSED":
        raise_err("ERR_PENALTY_INVALID_STATE", "Only an ASSESSED penalty can be settled")

    if settle_amount_cents != penalty["outstanding_cents"]:
        raise_err("ERR_SETTLE_AMOUNT_MISMATCH", "Settle amount must equal the outstanding amount exactly")

    penalty["settled_cents"] += settle_amount_cents
    penalty["outstanding_cents"] = 0
    penalty["status"] = "SETTLED"
    core.touch(penalty)

    request = db.requests.get(penalty["request_id"])
    if request is not None:
        core.recompute_request_penalty_exposure(request["id"])
        core.recompute_vendor_rollups(request["vendor_id"])

    return success_object(core.serialize(penalty))
