"""Wineries, state rules, prohibited ZIPs, carrier programs and the clock."""
from flask import Blueprint

import clock
import response
import validate
from errors import ApiError
from middleware import require, own_winery
from routes import common
from services import serialize
from store import db, base_row, touch

bp = Blueprint("reference", __name__)

STATUSES = ("ACTIVE", "SUSPENDED")
PERIODS = ("ROLLING_12_MONTHS", "CALENDAR_YEAR", "ROLLING_30_DAYS")
FREQUENCIES = ("MONTHLY", "ANNUAL")
ZIP_REASONS = ("DRY_COUNTY", "PROHIBITED_MUNICIPALITY", "PO_BOX_ONLY", "CARRIER_UNSERVED")
CARRIER_CODES = ("UPS", "FEDEX", "GSO")


# ---- wineries -------------------------------------------------------------
@bp.route("/dtc/wineries", methods=["POST"])
def create_winery():
    require("PlatformAdmin")
    b = validate.body()
    name = validate.field_str(b, "name")
    ttb = validate.field_str(b, "ttb_permit_number")
    home = validate.state_code(b, "home_state_code")
    gallons = validate.field_int(b, "annual_production_gallons", minimum=0)
    for row in db.wineries.values():
        if row["ttb_permit_number"] == ttb:
            validate.bad("ttb_permit_number must be unique across wineries.")
    row = base_row()
    row.update({
        "name": name,
        "ttb_permit_number": ttb,
        "home_state_code": home,
        "annual_production_gallons": gallons,
        "status": "ACTIVE",
        "suspension_reason": None,
    })
    db.wineries[row["id"]] = row
    return response.obj(serialize.winery(row), 201)


@bp.route("/dtc/wineries/<wid>", methods=["GET"])
def read_winery(wid):
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator")
    own_winery(uid, role, wid)
    return response.obj(serialize.winery(common.winery(wid)))


@bp.route("/dtc/wineries", methods=["GET"])
def list_wineries():
    require("PlatformAdmin", "ComplianceOfficer")
    home = common.arg("home_state_code")
    status = validate.query_enum("status", STATUSES)
    rows = [w for w in db.wineries.values()
            if (home is None or w["home_state_code"] == home)
            and (status is None or w["status"] == status)]
    return common.listing(rows, serialize.winery)


@bp.route("/dtc/wineries/<wid>/status", methods=["POST"])
def winery_status(wid):
    require("PlatformAdmin")
    winery = common.winery(wid)
    b = validate.body()
    target = validate.field_enum(b, "status", STATUSES)
    reason = validate.field_str(b, "suspension_reason", required=False, allow_empty=True)
    if winery["status"] == target:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The winery is already %s." % target)
    winery["status"] = target
    winery["suspension_reason"] = reason if target == "SUSPENDED" else None
    touch(winery)
    return response.obj(serialize.winery(winery))


# ---- state rules ----------------------------------------------------------
@bp.route("/dtc/state-rules", methods=["POST"])
def create_state_rule():
    require("PlatformAdmin")
    b = validate.body()
    code = validate.state_code(b, "state_code")
    row = base_row()
    row.update({
        "state_code": code,
        "allows_dtc": validate.field_bool(b, "allows_dtc"),
        "per_consumer_limit_liters": validate.field_num(
            b, "per_consumer_limit_liters", exclusive_min=0),
        "per_consumer_period": validate.field_enum(b, "per_consumer_period", PERIODS),
        "per_winery_annual_limit_liters": validate.field_num(
            b, "per_winery_annual_limit_liters", exclusive_min=0),
        "excise_rate_per_liter_cents": validate.field_int(
            b, "excise_rate_per_liter_cents", minimum=0),
        "large_format_surcharge_cents_per_liter": validate.field_int(
            b, "large_format_surcharge_cents_per_liter", minimum=0),
        "excise_cap_cents_per_shipment": validate.field_int(
            b, "excise_cap_cents_per_shipment", minimum=1),
        "sales_tax_rate_bps": validate.field_int(
            b, "sales_tax_rate_bps", minimum=0, maximum=2000),
        "tax_on_shipping": validate.field_bool(b, "tax_on_shipping"),
        "excise_in_tax_base": validate.field_bool(b, "excise_in_tax_base"),
        "adult_signature_required": validate.field_bool(b, "adult_signature_required"),
        "requires_carrier_program": validate.field_bool(b, "requires_carrier_program"),
        "reporting_frequency": validate.field_enum(b, "reporting_frequency", FREQUENCIES),
        "zero_filing_required": validate.field_bool(b, "zero_filing_required"),
        "min_purchaser_age": validate.field_int(
            b, "min_purchaser_age", required=False, default=21, minimum=0),
        "renewal_lead_days": validate.field_int(
            b, "renewal_lead_days", required=False, default=60, minimum=0),
    })
    for existing in db.state_rules.values():
        if existing["state_code"] == code:
            validate.bad("state_code must be unique across state rules.")
    db.state_rules[row["id"]] = row
    return response.obj(serialize.state_rule(row), 201)


@bp.route("/dtc/state-rules/<rid>", methods=["GET"])
def read_state_rule(rid):
    require("PlatformAdmin", "ComplianceOfficer", "WineryOperator", "Consumer")
    return response.obj(serialize.state_rule(common.state_rule(rid)))


@bp.route("/dtc/state-rules", methods=["GET"])
def list_state_rules():
    require("PlatformAdmin", "ComplianceOfficer", "WineryOperator")
    code = common.arg("state_code")
    allows = validate.query_bool("allows_dtc")
    rows = [r for r in db.state_rules.values()
            if (code is None or r["state_code"] == code)
            and (allows is None or r["allows_dtc"] == allows)]
    return common.listing(rows, serialize.state_rule)


# ---- prohibited ZIPs ------------------------------------------------------
@bp.route("/dtc/state-rules/<rid>/prohibited-zips", methods=["POST"])
def create_prohibited_zip(rid):
    require("PlatformAdmin", "ComplianceOfficer")
    rule = common.state_rule(rid)
    b = validate.body()
    zip_value = validate.zip_code(b, "zip_code")
    reason = validate.field_enum(b, "reason", ZIP_REASONS)
    effective_raw, _effective = validate.field_date(b, "effective_from")
    for existing in db.prohibited_zips.values():
        if existing["state_rule_id"] == rule["id"] and existing["zip_code"] == zip_value:
            raise ApiError("ERR_DUPLICATE_PROHIBITED_ZIP",
                           "This ZIP is already declared for the state rule.")
    row = base_row(versioned=False)
    row.update({
        "state_rule_id": rule["id"],
        "zip_code": zip_value,
        "reason": reason,
        "effective_from": effective_raw,
    })
    db.prohibited_zips[row["id"]] = row
    return response.obj(serialize.prohibited_zip(row), 201)


@bp.route("/dtc/state-rules/<rid>/prohibited-zips", methods=["GET"])
def list_prohibited_zips(rid):
    require("PlatformAdmin", "ComplianceOfficer", "WineryOperator")
    rule = common.state_rule(rid)
    reason = validate.query_enum("reason", ZIP_REASONS)
    rows = [z for z in db.prohibited_zips.values()
            if z["state_rule_id"] == rule["id"]
            and (reason is None or z["reason"] == reason)]
    return common.listing(rows, serialize.prohibited_zip)


# ---- carrier programs ----------------------------------------------------
@bp.route("/dtc/carrier-programs", methods=["POST"])
def create_carrier_program():
    require("PlatformAdmin")
    b = validate.body()
    code = validate.field_enum(b, "carrier_code", CARRIER_CODES)
    name = validate.field_str(b, "program_name")
    served = b.get("states_served")
    if not isinstance(served, list) or not served:
        validate.bad("Field 'states_served' must be a non-empty array of state codes.")
    for item in served:
        if not isinstance(item, str) or len(item) != 2 or not item.isalpha() \
                or item != item.upper():
            validate.bad("Field 'states_served' must hold two-letter uppercase codes.")
    requires = validate.field_bool(b, "requires_enrollment")
    service_code = validate.field_str(b, "adult_signature_service_code",
                                     required=False, default=None)
    row = base_row()
    row.update({
        "carrier_code": code,
        "program_name": name,
        "states_served": list(served),
        "requires_enrollment": requires,
        "adult_signature_service_code": service_code,
    })
    db.carrier_programs[row["id"]] = row
    return response.obj(serialize.carrier_program(row), 201)


@bp.route("/dtc/carrier-programs/<pid>", methods=["GET"])
def read_carrier_program(pid):
    require("PlatformAdmin", "ComplianceOfficer", "WineryOperator", "CarrierAgent")
    return response.obj(serialize.carrier_program(common.carrier_program(pid)))


@bp.route("/dtc/carrier-programs", methods=["GET"])
def list_carrier_programs():
    require("PlatformAdmin", "ComplianceOfficer", "WineryOperator", "CarrierAgent")
    code = validate.query_enum("carrier_code", CARRIER_CODES)
    rows = [p for p in db.carrier_programs.values()
            if code is None or p["carrier_code"] == code]
    return common.listing(rows, serialize.carrier_program)


# ---- logical clock -------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require("PlatformAdmin")
    b = validate.body()
    raw, parsed = validate.field_instant(b, "current_utc")
    clock.set_now(parsed)
    return response.obj({"current_utc": clock.now_iso()})
