"""Registry surface: logical clock, payers, patients, providers, network
contracts and transport vehicles (PRD 3.1)."""

from flask import Blueprint

import derive
from envelope import created, filter_eq, list_response, ok
from errors import ApiError
from store import base_row, db, ordered, parse_dt, touch
from validate import (PROVIDER_STATUSES, PROVIDER_TYPES, VEHICLE_TYPES, actor,
                      body, opt_bool, opt_int, present, req_bool, req_date,
                      req_enum, req_int, req_num, req_str, req_str_array,
                      require_roles)

bp = Blueprint("registry", __name__)


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    b = body()
    raw = req_str(b, "to_iso8601")
    parsed = parse_dt(raw)
    if parsed is None:
        raise ApiError("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 instant")
    db.set_clock(parsed, raw)
    return ok({"current_utc": db.now_raw()})


# --------------------------------------------------------------------------
# payers
# --------------------------------------------------------------------------
@bp.post("/payers")
def create_payer():
    require_roles("PlatformAdmin")
    b = body()
    name = req_str(b, "name")
    coinsurance = req_num(b, "coinsurance_pct", minimum=0.0, maximum=0.5)
    snf = opt_bool(b, "snf_auth_required", True)
    hh = opt_bool(b, "hh_auth_required", True)
    expiry_days = opt_int(b, "auth_expiry_days", minimum=1, default=30)
    row = base_row()
    row.update({
        "name": name,
        "snf_auth_required": snf,
        "hh_auth_required": hh,
        "coinsurance_pct": coinsurance,
        "auth_expiry_days": expiry_days,
    })
    db.payers[row["id"]] = row
    return created(derive.ser_payer(row))


@bp.get("/payers/<pid>")
def read_payer(pid):
    require_roles("PlatformAdmin", "CaseManager", "UtilizationReviewNurse",
                  "PayerRepresentative")
    return ok(derive.ser_payer(derive.get_payer(pid)))


# --------------------------------------------------------------------------
# patients
# --------------------------------------------------------------------------
@bp.post("/patients")
def create_patient():
    require_roles("PlatformAdmin", "CaseManager")
    b = body()
    mrn = req_str(b, "mrn")
    full_name = req_str(b, "full_name")
    dob = req_date(b, "date_of_birth")
    payer_id = req_str(b, "primary_payer_id")
    prior = req_int(b, "prior_admissions_180d", minimum=0)
    lives_alone = req_bool(b, "lives_alone")
    has_pcp = req_bool(b, "has_pcp")
    derive.get_payer(payer_id)
    for existing in db.patients.values():
        if existing["mrn"] == mrn:
            raise ApiError("ERR_DUPLICATE_MRN", "mrn %s already exists" % mrn)
    row = base_row()
    row.update({
        "mrn": mrn,
        "full_name": full_name,
        "date_of_birth": dob,
        "primary_payer_id": payer_id,
        "prior_admissions_180d": prior,
        "lives_alone": lives_alone,
        "has_pcp": has_pcp,
    })
    db.patients[row["id"]] = row
    return created(derive.ser_patient(row))


@bp.get("/patients/<pid>")
def read_patient(pid):
    require_roles("PlatformAdmin", "CaseManager", "UtilizationReviewNurse")
    return ok(derive.ser_patient(derive.get_patient(pid)))


@bp.get("/patients")
def list_patients():
    require_roles("PlatformAdmin", "CaseManager", "UtilizationReviewNurse")
    rows = ordered(db.patients.values())
    rows = filter_eq(rows, "primary_payer_id", "primary_payer_id")
    rows = filter_eq(rows, "mrn", "mrn")
    return list_response(rows, derive.ser_patient)


# --------------------------------------------------------------------------
# providers
# --------------------------------------------------------------------------
@bp.post("/providers")
def create_provider():
    require_roles("PlatformAdmin")
    b = body()
    name = req_str(b, "name")
    provider_type = req_enum(b, "provider_type", PROVIDER_TYPES)
    stars = req_int(b, "quality_star_rating", minimum=1, maximum=5)
    distance = req_int(b, "distance_miles_from_hospital", minimum=0)
    bed_units = req_str_array(b, "bed_unit_codes")
    row = base_row()
    row.update({
        "name": name,
        "provider_type": provider_type,
        "quality_star_rating": stars,
        "distance_miles_from_hospital": distance,
        "bed_unit_codes": bed_units,
        "status": "ACTIVE",
        "offers_received_count": 0,
    })
    db.providers[row["id"]] = row
    return created(derive.ser_provider(row))


@bp.get("/providers/<pid>")
def read_provider(pid):
    require_roles("PlatformAdmin", "CaseManager", "UtilizationReviewNurse",
                  "PostAcuteLiaison", "DischargeCoordinator")
    provider = derive.get_provider(pid)
    derive.sweep_provider(provider)
    return ok(derive.ser_provider(provider))


@bp.get("/providers")
def list_providers():
    require_roles("PlatformAdmin", "CaseManager", "UtilizationReviewNurse")
    rows = ordered(db.providers.values())
    for row in rows:
        derive.sweep_provider(row)
    rows = filter_eq(rows, "provider_type", "provider_type")
    rows = filter_eq(rows, "status", "status")
    return list_response(rows, derive.ser_provider)


@bp.post("/providers/<pid>/suspend")
def suspend_provider(pid):
    require_roles("PlatformAdmin")
    provider = derive.get_provider(pid)
    provider["status"] = "SUSPENDED"
    touch(provider)
    return ok(derive.ser_provider(provider))


# --------------------------------------------------------------------------
# network contracts
# --------------------------------------------------------------------------
@bp.post("/network-contracts")
def create_contract():
    require_roles("PlatformAdmin")
    b = body()
    payer_id = req_str(b, "payer_id")
    provider_id = req_str(b, "provider_id")
    in_network = req_bool(b, "in_network")
    rate = req_int(b, "negotiated_daily_rate_cents", minimum=1)
    derive.get_payer(payer_id)
    derive.get_provider(provider_id)
    if derive.contract_for(payer_id, provider_id) is not None:
        raise ApiError("ERR_DUPLICATE_NETWORK_CONTRACT",
                       "a contract already exists for this payer and provider")
    row = base_row()
    row.update({
        "payer_id": payer_id,
        "provider_id": provider_id,
        "in_network": in_network,
        "negotiated_daily_rate_cents": rate,
    })
    db.contracts[row["id"]] = row
    return created(derive.ser_contract(row))


@bp.get("/network-contracts/<cid>")
def read_contract(cid):
    require_roles("PlatformAdmin", "CaseManager", "PayerRepresentative")
    return ok(derive.ser_contract(derive.get_contract(cid)))


@bp.get("/network-contracts")
def list_contracts():
    require_roles("PlatformAdmin", "CaseManager", "PayerRepresentative")
    rows = ordered(db.contracts.values())
    rows = filter_eq(rows, "payer_id", "payer_id")
    rows = filter_eq(rows, "provider_id", "provider_id")
    return list_response(rows, derive.ser_contract)


# --------------------------------------------------------------------------
# transport vehicles
# --------------------------------------------------------------------------
@bp.post("/vehicles")
def create_vehicle():
    require_roles("PlatformAdmin")
    b = body()
    operator_name = req_str(b, "operator_name")
    vehicle_type = req_enum(b, "vehicle_type", VEHICLE_TYPES)
    base_rate = req_int(b, "base_rate_cents", minimum=1)
    per_mile = req_int(b, "per_mile_cents", minimum=0)
    row = base_row()
    row.update({
        "operator_name": operator_name,
        "vehicle_type": vehicle_type,
        "base_rate_cents": base_rate,
        "per_mile_cents": per_mile,
        "status": "ACTIVE",
    })
    db.vehicles[row["id"]] = row
    return created(derive.ser_vehicle(row))


@bp.get("/vehicles/<vid>")
def read_vehicle(vid):
    require_roles("PlatformAdmin", "DischargeCoordinator", "CaseManager")
    return ok(derive.ser_vehicle(derive.get_vehicle(vid)))


@bp.post("/vehicles/<vid>/out-of-service")
def vehicle_out_of_service(vid):
    require_roles("PlatformAdmin")
    vehicle = derive.get_vehicle(vid)
    vehicle["status"] = "OUT_OF_SERVICE"
    touch(vehicle)
    return ok(derive.ser_vehicle(vehicle))
