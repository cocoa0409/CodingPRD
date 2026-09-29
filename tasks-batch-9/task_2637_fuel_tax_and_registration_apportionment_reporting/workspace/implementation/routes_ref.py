"""Clock control, reference data, carriers, drivers and vehicles."""

from flask import Blueprint, g

import calc
import serializers as S
from common import (
    API_PREFIX,
    ALL_ROLES,
    ApiError,
    DB,
    JCODE_RE,
    LIGHT,
    VERSIONED,
    ZERO,
    authenticate,
    bad_request,
    carrier_scope_guard,
    collection,
    fail,
    find_or_404,
    fmt_instant,
    gallons,
    miles,
    money,
    new_row,
    need_bool,
    need_enum,
    need_int,
    need_num,
    need_str,
    ok,
    parse_instant,
    q_bool,
    q_int,
    q_str,
    raw_body,
    ratio,
    reject_unknown,
    touch,
)

bp = Blueprint("ref", __name__)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/_clock/set_current_utc")
def set_clock():
    authenticate(["ComplianceOfficer"])
    body = raw_body()
    reject_unknown(body, {"to_iso8601"})
    raw = need_str(body, "to_iso8601")
    instant = parse_instant(raw)
    if instant is None:
        raise bad_request("Field 'to_iso8601' must be an ISO 8601 instant.")
    DB.clock.set(instant)
    return ok({"current_utc": fmt_instant(instant)})


# --------------------------------------------------------------------------
# Jurisdictions
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/jurisdictions")
def create_jurisdiction():
    authenticate(["ComplianceOfficer"])
    body = raw_body()
    reject_unknown(body, {
        "jurisdiction_code", "name", "fuel_tax_rate_per_gallon",
        "surcharge_rate_per_gallon", "is_surcharge_jurisdiction",
    })
    code = need_str(body, "jurisdiction_code")
    if not JCODE_RE.match(code):
        raise bad_request("Field 'jurisdiction_code' must be exactly two uppercase letters.")
    name = need_str(body, "name")
    rate = need_num(body, "fuel_tax_rate_per_gallon", minimum=0)
    surcharge = need_num(body, "surcharge_rate_per_gallon", required=False,
                         default=ZERO, minimum=0)
    need_bool(body, "is_surcharge_jurisdiction", required=False, default=None)

    if calc.jurisdiction_by_code(code) is not None:
        raise fail("ERR_DUPLICATE_JURISDICTION",
                   "Jurisdiction %s is already declared." % code)

    row = new_row(LIGHT)
    row.update({
        "jurisdiction_code": code,
        "name": name,
        "fuel_tax_rate_per_gallon": ratio(rate),
        "surcharge_rate_per_gallon": ratio(surcharge),
        "is_surcharge_jurisdiction": ratio(surcharge) > 0,
    })
    DB.jurisdictions[row["id"]] = row
    return ok(S.jurisdiction_out(row), 201)


@bp.get(API_PREFIX + "/jurisdictions/<row_id>")
def get_jurisdiction(row_id):
    authenticate(ALL_ROLES)
    row = DB.jurisdictions.get(row_id)
    if row is None:
        # The catalogue declares no jurisdiction-not-found id; a read of an
        # unknown id is still a 404.
        raise ApiError("ERR_JURISDICTION_NOT_FOUND", 404,
                       "No such jurisdiction: %s." % row_id)
    return ok(S.jurisdiction_out(row))


@bp.get(API_PREFIX + "/jurisdictions")
def list_jurisdictions():
    authenticate(ALL_ROLES)
    filters = {"is_surcharge_jurisdiction": q_bool("is_surcharge_jurisdiction")}
    return collection(DB.jurisdictions.values(), filters,
                      ["jurisdiction_code"], S.jurisdiction_out)


# --------------------------------------------------------------------------
# Weight group fee chart
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/weight-group-fees")
def create_weight_group_fee():
    authenticate(["ComplianceOfficer"])
    body = raw_body()
    reject_unknown(body, {
        "jurisdiction_code", "weight_group_code", "declared_weight_lbs",
        "annual_fee_amount",
    })
    code = need_str(body, "jurisdiction_code")
    group = need_str(body, "weight_group_code")
    weight = need_int(body, "declared_weight_lbs", minimum=1)
    fee = need_num(body, "annual_fee_amount", minimum_exclusive=0)

    if calc.jurisdiction_by_code(code) is None:
        raise fail("ERR_JURISDICTION_NOT_DECLARED",
                   "Jurisdiction %s is not declared." % code)
    if calc.weight_group_fee(code, group) is not None:
        raise fail("ERR_DUPLICATE_WEIGHT_GROUP_FEE",
                   "A fee cell already exists for (%s, %s)." % (code, group))

    row = new_row(LIGHT)
    row.update({
        "jurisdiction_code": code,
        "weight_group_code": group,
        "declared_weight_lbs": weight,
        "annual_fee_amount": money(fee),
    })
    DB.weight_group_fees[row["id"]] = row
    return ok(S.weight_group_fee_out(row), 201)


@bp.get(API_PREFIX + "/weight-group-fees/<row_id>")
def get_weight_group_fee(row_id):
    authenticate(ALL_ROLES)
    row = DB.weight_group_fees.get(row_id)
    if row is None:
        raise ApiError("ERR_WEIGHT_GROUP_FEE_NOT_FOUND", 404,
                       "No such weight group fee: %s." % row_id)
    return ok(S.weight_group_fee_out(row))


@bp.get(API_PREFIX + "/weight-group-fees")
def list_weight_group_fees():
    authenticate(ALL_ROLES)
    filters = {
        "jurisdiction_code": q_str("jurisdiction_code"),
        "weight_group_code": q_str("weight_group_code"),
    }
    return collection(DB.weight_group_fees.values(), filters,
                      ["jurisdiction_code", "weight_group_code"],
                      S.weight_group_fee_out)


# --------------------------------------------------------------------------
# Carriers
# --------------------------------------------------------------------------


def get_carrier_or_404(carrier_id):
    return find_or_404(DB.carriers, carrier_id, "ERR_CARRIER_NOT_FOUND")


@bp.post(API_PREFIX + "/carriers")
def create_carrier():
    authenticate(["ComplianceOfficer"])
    body = raw_body()
    reject_unknown(body, {
        "legal_name", "usdot_number", "base_jurisdiction_code",
        "bond_ceiling_amount",
    })
    legal_name = need_str(body, "legal_name")
    usdot = need_str(body, "usdot_number")
    base_code = need_str(body, "base_jurisdiction_code")
    bond = need_num(body, "bond_ceiling_amount", required=False,
                    default=money("5000.00"), minimum=0)

    for existing in DB.carriers.values():
        if existing["usdot_number"] == usdot:
            raise fail("ERR_DUPLICATE_USDOT_NUMBER",
                       "USDOT number %s is already on file." % usdot)

    row = new_row(VERSIONED)
    row.update({
        "legal_name": legal_name,
        "usdot_number": usdot,
        "base_jurisdiction_code": base_code,
        "bond_ceiling_amount": money(bond),
        "ifta_license_status": "ACTIVE",
        "irp_account_status": "ACTIVE",
        "tax_paid_gallons_ytd": gallons(ZERO),
        "unsubstantiated_mileage_ratio": ratio(ZERO),
        "audit_flag": False,
        "latest_prepared_fleet_mpg": None,
        "suspension_count": 0,
    })
    DB.carriers[row["id"]] = row
    return ok(S.carrier_out(row), 201)


@bp.get(API_PREFIX + "/carriers/<row_id>")
def get_carrier(row_id):
    authenticate(ALL_ROLES)
    return ok(S.carrier_out(get_carrier_or_404(row_id)))


@bp.get(API_PREFIX + "/carriers")
def list_carriers():
    authenticate(ALL_ROLES)
    filters = {
        "base_jurisdiction_code": q_str("base_jurisdiction_code"),
        "ifta_license_status": q_str("ifta_license_status"),
        "audit_flag": q_bool("audit_flag"),
    }
    return collection(DB.carriers.values(), filters, [], S.carrier_out)


@bp.get(API_PREFIX + "/carriers/<row_id>/drivers")
def list_carrier_drivers(row_id):
    authenticate(ALL_ROLES)
    carrier = get_carrier_or_404(row_id)
    rows = [d for d in DB.drivers.values() if d["carrier_id"] == carrier["id"]]
    filters = {"driver_status": q_str("driver_status")}
    return collection(rows, filters, [], S.driver_out)


@bp.get(API_PREFIX + "/carriers/<row_id>/audit-selections")
def list_carrier_audit_selections(row_id):
    authenticate(ALL_ROLES)
    carrier = get_carrier_or_404(row_id)
    rows = [
        a for a in DB.audit_selections.values()
        if a["carrier_id"] == carrier["id"]
    ]
    filters = {
        "selection_year": q_int("selection_year"),
        "selection_status": q_str("selection_status"),
    }
    return collection(rows, filters, ["selection_year", "selection_quarter"],
                      S.audit_selection_out)


# --------------------------------------------------------------------------
# Drivers
# --------------------------------------------------------------------------


@bp.post(API_PREFIX + "/drivers")
def create_driver():
    authenticate(["CarrierAdmin", "ComplianceOfficer"])
    body = raw_body()
    reject_unknown(body, {"carrier_id", "full_name", "cdl_number"})

    carrier_id = body.get("carrier_id")
    if isinstance(carrier_id, str):
        get_carrier_or_404(carrier_id)

    need_str(body, "carrier_id")
    full_name = need_str(body, "full_name")
    cdl = need_str(body, "cdl_number")
    carrier = get_carrier_or_404(body["carrier_id"])

    carrier_scope_guard(carrier["id"])

    row = new_row(VERSIONED)
    row.update({
        "carrier_id": carrier["id"],
        "full_name": full_name,
        "cdl_number": cdl,
        "driver_status": "ACTIVE",
    })
    DB.drivers[row["id"]] = row
    return ok(S.driver_out(row), 201)


# --------------------------------------------------------------------------
# Vehicles
# --------------------------------------------------------------------------


def get_vehicle_or_404(vehicle_id):
    return find_or_404(DB.vehicles, vehicle_id, "ERR_VEHICLE_NOT_FOUND")


@bp.post(API_PREFIX + "/vehicles")
def create_vehicle():
    authenticate(["CarrierAdmin", "ComplianceOfficer"])
    body = raw_body()
    reject_unknown(body, {
        "carrier_id", "unit_number", "vin", "weight_group_code",
        "factory_price_amount", "registration_year",
    })

    carrier_id = body.get("carrier_id")
    if isinstance(carrier_id, str):
        get_carrier_or_404(carrier_id)

    need_str(body, "carrier_id")
    unit_number = need_str(body, "unit_number")
    vin = need_str(body, "vin")
    weight_group_code = need_str(body, "weight_group_code")
    factory_price = need_num(body, "factory_price_amount", minimum=0)
    registration_year = need_int(body, "registration_year", minimum=1)
    carrier = get_carrier_or_404(body["carrier_id"])

    carrier_scope_guard(carrier["id"])

    for existing in DB.vehicles.values():
        if (existing["carrier_id"] == carrier["id"]
                and existing["unit_number"] == unit_number
                and existing["registration_year"] == registration_year):
            raise fail("ERR_DUPLICATE_UNIT_NUMBER",
                       "Unit %s already exists for this carrier and year." % unit_number)

    row = new_row(VERSIONED)
    row.update({
        "carrier_id": carrier["id"],
        "unit_number": unit_number,
        "vin": vin,
        "weight_group_code": weight_group_code,
        "factory_price_amount": money(factory_price),
        "registration_year": registration_year,
        "vehicle_status": "PENDING",
        "credential_status": "NONE",
        "replaced_vehicle_id": None,
        "activated_on_date": None,
    })
    DB.vehicles[row["id"]] = row
    return ok(S.vehicle_out(row), 201)


@bp.get(API_PREFIX + "/vehicles/<row_id>")
def get_vehicle(row_id):
    authenticate(ALL_ROLES)
    return ok(S.vehicle_out(get_vehicle_or_404(row_id)))


@bp.get(API_PREFIX + "/vehicles")
def list_vehicles():
    authenticate(ALL_ROLES)
    filters = {
        "carrier_id": q_str("carrier_id"),
        "replaced_vehicle_id": q_str("replaced_vehicle_id"),
        "vehicle_status": q_str("vehicle_status"),
        "credential_status": q_str("credential_status"),
        "registration_year": q_int("registration_year"),
    }
    return collection(DB.vehicles.values(), filters, [], S.vehicle_out)
