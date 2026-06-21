"""FeeWaiver endpoints (PRD 3.7)."""
from flask import Blueprint, g, request

from db import store
from errors import ApiError
from middleware import require_roles
from response import success, success_list
from util import new_common, serialize, touch
from services.common import (
    get_body, require_fields, require_int, lookup,
    parse_pagination, sort_by_created,
)
from services import calculations as calc

bp = Blueprint("fee_waivers", __name__)


@bp.route("/fee-waivers", methods=["POST"])
@require_roles("Clerk", "Applicant")
def create_waiver():
    body = get_body()
    require_fields(body, "applicant_id", "declared_monthly_income_cents", "household_size")
    require_int(body["declared_monthly_income_cents"], "declared_monthly_income_cents", minimum=0)
    require_int(body["household_size"], "household_size", minimum=1)
    lookup("applicant", body["applicant_id"])

    ent = new_common("fee_waiver")
    ent.update({
        "applicant_id": body["applicant_id"],
        "declared_monthly_income_cents": body["declared_monthly_income_cents"],
        "household_size": body["household_size"],
        "status": "REQUESTED",
        "max_waivable_cents": 0,
        "consumed_cents": 0,
        "adjudicated_by_user_id": None,
    })
    store.fee_waivers[ent["id"]] = ent
    return success(serialize(ent), status=201)


@bp.route("/fee-waivers/<waiver_id>", methods=["GET"])
@require_roles("Clerk", "Registrar", "Applicant", "WaiverOfficer")
def get_waiver(waiver_id):
    ent = lookup("fee_waiver", waiver_id)
    return success(serialize(ent), status=200)


@bp.route("/fee-waivers", methods=["GET"])
@require_roles("Clerk", "Registrar", "WaiverOfficer")
def list_waivers():
    limit, offset = parse_pagination()
    applicant_filter = request.args.get("applicant_id")
    items = list(store.fee_waivers.values())
    if applicant_filter is not None:
        items = [w for w in items if w["applicant_id"] == applicant_filter]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(w) for w in page], limit, offset, total)


@bp.route("/fee-waivers/<waiver_id>/decide", methods=["POST"])
@require_roles("WaiverOfficer")
def decide_waiver(waiver_id):
    waiver = lookup("fee_waiver", waiver_id)
    body = get_body()
    require_fields(body, "decision")
    from services.common import require_enum
    require_enum(body["decision"], {"GRANT", "DENY"}, "decision")
    decision = body["decision"]

    if waiver["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Waiver is not REQUESTED")

    if decision == "DENY":
        waiver["status"] = "DENIED"
        waiver["adjudicated_by_user_id"] = g.user_id
        touch(waiver)
        return success(serialize(waiver), status=200)

    # GRANT — means test.
    threshold = calc.poverty_threshold_for(waiver["household_size"])
    if waiver["declared_monthly_income_cents"] > threshold:
        raise ApiError("ERR_INCOME_ABOVE_THRESHOLD", "Declared income exceeds the poverty threshold")
    waiver["status"] = "GRANTED"
    waiver["adjudicated_by_user_id"] = g.user_id
    waiver["max_waivable_cents"] = calc.waiver_cap(
        waiver["declared_monthly_income_cents"], waiver["household_size"]
    )
    touch(waiver)
    return success(serialize(waiver), status=200)
