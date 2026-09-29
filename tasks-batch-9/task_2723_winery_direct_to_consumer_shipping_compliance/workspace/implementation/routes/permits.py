"""Destination-state permits: filing, activation, the renewal cycle, revocation."""
from flask import Blueprint

import clock
import response
import validate
from errors import ApiError
from middleware import require, own_winery
from routes import common
from services import permits, serialize
from store import db, base_row, touch

bp = Blueprint("permits", __name__)

PERMIT_TYPES = ("DIRECT_SHIPPER", "WINE_SHIPPER", "COMMON_CARRIER_ENDORSEMENT")
PERMIT_STATUSES = ("PENDING", "ACTIVE", "RENEWAL_FILED", "EXPIRED", "REVOKED")


@bp.route("/dtc/state-permits", methods=["POST"])
def create_state_permit():
    require("ComplianceOfficer")
    b = validate.body()
    winery_id = validate.field_str(b, "winery_id")
    code = validate.state_code(b, "state_code")
    number = validate.field_str(b, "permit_number")
    permit_type = validate.field_enum(b, "permit_type", PERMIT_TYPES)
    eff_raw, eff = validate.field_date(b, "effective_date")
    exp_raw, exp = validate.field_date(b, "expiration_date")

    common.winery(winery_id)
    common.rule_for_state(code)

    for existing in permits.permits_for(winery_id, code):
        if existing["status"] == "REVOKED":
            continue
        if permits.overlaps(eff, exp, existing):
            raise ApiError(
                "ERR_PERMIT_PERIOD_OVERLAP",
                "The requested period overlaps a non-revoked permit for %s." % code)

    row = base_row()
    row.update({
        "winery_id": winery_id,
        "state_code": code,
        "permit_number": number,
        "permit_type": permit_type,
        "effective_date": eff_raw,
        "expiration_date": exp_raw,
        "status": "PENDING",
        "renewal_reference": None,
        "renewal_filed_at": None,
        "revocation_reason": None,
        "renewal_cycle_count": 0,
    })
    db.state_permits[row["id"]] = row
    return response.obj(serialize.state_permit(row), 201)


@bp.route("/dtc/state-permits/<pid>", methods=["GET"])
def read_state_permit(pid):
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator")
    permit = common.state_permit(pid)
    own_winery(uid, role, permit["winery_id"])
    return response.obj(serialize.state_permit(permit))


@bp.route("/dtc/state-permits", methods=["GET"])
def list_state_permits():
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator")
    winery_id = common.scope_winery(common.arg("winery_id"), uid, role)
    code = common.arg("state_code")
    status = validate.query_enum("status", PERMIT_STATUSES)
    rows = [p for p in db.state_permits.values()
            if (winery_id is None or p["winery_id"] == winery_id)
            and (code is None or p["state_code"] == code)
            and (status is None or p["status"] == status)]
    return common.listing(rows, serialize.state_permit)


@bp.route("/dtc/state-permits/<pid>/activate", methods=["POST"])
def activate_state_permit(pid):
    require("ComplianceOfficer")
    permit = common.state_permit(pid)
    if permit["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a PENDING permit may be activated.")
    effective = clock.parse_date(permit["effective_date"])
    if effective is not None and effective > clock.today():
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The permit's effective_date has not arrived yet.")
    permit["status"] = "ACTIVE"
    touch(permit)
    return response.obj(serialize.state_permit(permit))


@bp.route("/dtc/state-permits/<pid>/file-renewal", methods=["POST"])
def file_renewal(pid):
    uid, role = require("ComplianceOfficer", "WineryOperator")
    permit = common.state_permit(pid)
    own_winery(uid, role, permit["winery_id"])
    b = validate.body()
    reference = validate.field_str(b, "renewal_reference")

    status = permit["status"]
    if status == "ACTIVE":
        rule = common.rule_for_state(permit["state_code"])
        expires = clock.parse_date(permit["expiration_date"])
        if expires is not None:
            window_open = clock.plus_days(expires, -int(rule["renewal_lead_days"]))
            if clock.today() < window_open:
                raise ApiError("ERR_INVALID_STATE_TRANSITION",
                               "The renewal window has not opened yet.")
    elif status != "EXPIRED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A renewal may only be filed from ACTIVE or EXPIRED.")

    winery = db.wineries.get(permit["winery_id"])
    if winery is not None and winery["status"] == "SUSPENDED":
        raise ApiError("ERR_WINERY_SUSPENDED",
                       "The winery is suspended; this operation is blocked.")

    permit["status"] = "RENEWAL_FILED"
    permit["renewal_reference"] = reference
    permit["renewal_filed_at"] = clock.now_iso()
    touch(permit)
    return response.obj(serialize.state_permit(permit))


@bp.route("/dtc/state-permits/<pid>/approve-renewal", methods=["POST"])
def approve_renewal(pid):
    require("ComplianceOfficer")
    permit = common.state_permit(pid)
    b = validate.body()
    if validate.present(b, "expiration_date") or not validate.present(b, "new_expiration_date"):
        new_raw, new_date = validate.field_date(b, "expiration_date")
    else:
        new_raw, new_date = validate.field_date(b, "new_expiration_date")
    if permit["status"] != "RENEWAL_FILED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a RENEWAL_FILED permit may have its renewal approved.")
    current = clock.parse_date(permit["expiration_date"])
    if current is not None and new_date is not None and new_date <= current:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The new expiration_date must be strictly later than the current one.")
    permit["expiration_date"] = new_raw
    permit["status"] = "ACTIVE"
    permit["renewal_cycle_count"] = int(permit["renewal_cycle_count"]) + 1
    permit["renewal_reference"] = None
    permit["renewal_filed_at"] = None
    touch(permit)
    return response.obj(serialize.state_permit(permit))


@bp.route("/dtc/state-permits/<pid>/revoke", methods=["POST"])
def revoke_state_permit(pid):
    require("ComplianceOfficer")
    permit = common.state_permit(pid)
    b = validate.body()
    reason = validate.field_str(b, "revocation_reason")
    if permit["status"] not in permits.NON_REVOKED:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A REVOKED permit can never move again.")
    permit["status"] = "REVOKED"
    permit["revocation_reason"] = reason
    touch(permit)
    permits.revoke_cascade(permit)
    return response.obj(serialize.state_permit(permit))
