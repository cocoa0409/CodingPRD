"""Reference data: clinics, contracts, mobile units, equipment, technicians,
specialists (PRD 3.1)."""

from flask import Blueprint

from core import clock, db
from core.auth import READ_ROLES, authenticate, authorize
from core.constants import (
    CLINIC_STATUS_ENUM,
    CONTRACT_KIND_ENUM,
    DEFAULT_BUSINESS_CLOSE_MINUTE,
    DEFAULT_BUSINESS_DAYS,
    DEFAULT_BUSINESS_OPEN_MINUTE,
    MINUTES_PER_DAY,
    MODALITY_ENUM,
    ROUTE_MAX_SHIFT_MINUTES_DEFAULT,
    ROUTE_MAX_STOPS_DEFAULT,
    SPECIALIST_STATUS_ENUM,
    SPECIES_ENUM,
    TECHNICIAN_STATUS_ENUM,
    UNIT_SERVICE_STATUS_ENUM,
    CALIBRATION_VALIDITY_DAYS,
    BILLING_HOLD_ENUM,
)
from core.errors import ApiError
from core.validate import (
    body,
    enum_members,
    enum_value,
    fail,
    opt_bool,
    opt_id,
    opt_int,
    opt_str,
    req_id,
    req_int,
    req_list,
    req_str,
)
from routes.common import apply_derived_filter, apply_filters, listing, need, one
from services import derive

bp = Blueprint("reference", __name__)


# ==========================================================================
# Clinic
# ==========================================================================

@bp.post("/clinics")
def create_clinic():
    authenticate()
    authorize("PlatformAdmin")
    data = body()
    name = req_str(data, "name")
    zone = req_str(data, "address_zone")
    status = opt_str(data, "status", "ACTIVE")
    open_min = opt_int(data, "business_open_minute", DEFAULT_BUSINESS_OPEN_MINUTE,
                       minimum=0, maximum=MINUTES_PER_DAY)
    close_min = opt_int(data, "business_close_minute", DEFAULT_BUSINESS_CLOSE_MINUTE,
                        minimum=0, maximum=MINUTES_PER_DAY)
    days = data.get("business_days")
    if days is None:
        days = list(DEFAULT_BUSINESS_DAYS)
    else:
        if not isinstance(days, list) or not days:
            fail("Field 'business_days' must be a non-empty array.")
        for d in days:
            if isinstance(d, bool) or not isinstance(d, int) or d < 0 or d > 6:
                fail("Every member of 'business_days' must be an integer in 0..6.")
        if len(set(days)) != len(days):
            fail("Members of 'business_days' must be distinct.")
    if open_min >= close_min:
        fail("business_open_minute must be strictly less than business_close_minute.")
    enum_value(status, CLINIC_STATUS_ENUM, "status")

    rec = db.new_record()
    rec.update(
        {
            "name": name,
            "address_zone": zone,
            "status": status,
            "billing_hold_status": "CLEAR",
            "business_open_minute": open_min,
            "business_close_minute": close_min,
            "business_days": list(days),
        }
    )
    db.insert("clinics", rec)
    return one("clinics", rec, 201)


@bp.get("/clinics/<clinic_id>")
def get_clinic(clinic_id):
    authenticate()
    authorize(*READ_ROLES)
    return one("clinics", need("clinics", clinic_id, "ERR_CLINIC_NOT_FOUND"))


@bp.post("/clinics/<clinic_id>/billing-hold")
def set_billing_hold(clinic_id):
    authenticate()
    authorize("BillingAdmin")
    clinic = need("clinics", clinic_id, "ERR_CLINIC_NOT_FOUND")
    data = body()
    value = req_str(data, "billing_hold_status")
    enum_value(value, BILLING_HOLD_ENUM, "billing_hold_status")
    # Adjudication of an additional ambiguity (beyond the 9): PRD 3.1 states
    # "placing a hold requires the clinic to be CLEAR, lifting one requires it to
    # be HOLD", but the error catalogue nominates NO code for a violation and no
    # ladder rung covers a Clinic state precondition.  Reachability decides:
    # inventing a code (ERR_VALIDATION, say) would emit an identifier §5 never
    # licenses for this endpoint, while treating the write as idempotent strands
    # nothing at all — the pair may still "be cycled any number of times", which
    # is the only behaviour the paragraph actually declares.
    clinic["billing_hold_status"] = value
    db.touch(clinic)
    return one("clinics", clinic)


# ==========================================================================
# ClinicContract
# ==========================================================================

@bp.post("/contracts")
def create_contract():
    authenticate()
    authorize("BillingAdmin")
    data = body()
    clinic_id = req_id(data, "clinic_id")
    kind = req_str(data, "kind")
    valid_from_raw = req_str(data, "valid_from")
    valid_until_raw = req_str(data, "valid_until")
    purchased = opt_int(data, "block_purchased_studies", 0, minimum=0)
    suspended = opt_bool(data, "suspended", False)

    need("clinics", clinic_id, "ERR_CLINIC_NOT_FOUND")
    enum_value(kind, CONTRACT_KIND_ENUM, "kind")

    valid_from = clock.parse_instant(valid_from_raw)
    valid_until = clock.parse_instant(valid_until_raw)
    if valid_from is None:
        fail("Field 'valid_from' must be an ISO 8601 instant.")
    if valid_until is None:
        fail("Field 'valid_until' must be an ISO 8601 instant.")

    rec = db.new_record()
    rec.update(
        {
            "clinic_id": clinic_id,
            "kind": kind,
            "block_purchased_studies": purchased,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "suspended": suspended,
        }
    )
    db.insert("contracts", rec)
    return one("contracts", rec, 201)


@bp.get("/contracts/<contract_id>")
def get_contract(contract_id):
    authenticate()
    authorize(*READ_ROLES)
    return one("contracts", need("contracts", contract_id, "ERR_CONTRACT_NOT_FOUND"))


@bp.get("/contracts")
def list_contracts():
    authenticate()
    authorize(*READ_ROLES)
    rows = db.all_rows("contracts")
    rows = apply_filters(rows, {"clinic_id": "clinic_id"})
    rows = apply_derived_filter(rows, "status", derive.contract_status)
    return listing("contracts", rows)


@bp.post("/contracts/<contract_id>/block-purchase")
def block_purchase(contract_id):
    authenticate()
    authorize("BillingAdmin")
    contract = need("contracts", contract_id, "ERR_CONTRACT_NOT_FOUND")
    data = body()
    additional = req_int(data, "additional_studies", minimum=1)
    expected = req_int(data, "expected_contract_version")
    # rung 7 — optimistic concurrency
    if expected != contract["version"]:
        raise ApiError("ERR_STALE_VERSION")
    # rung 16 — contract is active.
    # Adjudication of friction 7: rung 16 is applied AS PHRASED, as a property of
    # the CLINIC ("the clinic must have exactly one ClinicContract whose computed
    # status is ACTIVE"), not of the contract being topped up.  Chosen in
    # reachability terms: the clinic-scoped reading admits every top-up target a
    # clinic with one live contract can name (including a lapsed contract the
    # operator is restocking), so no declared top-up behaviour is stranded, while
    # ERR_CONTRACT_NOT_ACTIVE stays fully reachable (zero active contracts, or two).
    # The contract-scoped reading would additionally strand top-ups of any
    # non-ACTIVE contract, reaching strictly fewer declared behaviours.
    if len(derive.active_contracts_for_clinic(contract["clinic_id"])) != 1:
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")

    contract["block_purchased_studies"] += additional
    db.touch(contract)
    return one("contracts", contract)


# ==========================================================================
# MobileUnit
# ==========================================================================

@bp.post("/mobile-units")
def create_mobile_unit():
    authenticate()
    authorize("PlatformAdmin")
    data = body()
    name = req_str(data, "name")
    service_status = opt_str(data, "service_status", "IN_SERVICE")
    max_stops = opt_int(data, "max_stops", ROUTE_MAX_STOPS_DEFAULT, minimum=1)
    max_shift = opt_int(data, "max_shift_minutes", ROUTE_MAX_SHIFT_MINUTES_DEFAULT,
                        minimum=60)
    enum_value(service_status, UNIT_SERVICE_STATUS_ENUM, "service_status")
    rec = db.new_record()
    rec.update(
        {
            "name": name,
            "service_status": service_status,
            "max_stops": max_stops,
            "max_shift_minutes": max_shift,
        }
    )
    db.insert("mobile_units", rec)
    return one("mobile_units", rec, 201)


@bp.get("/mobile-units/<unit_id>")
def get_mobile_unit(unit_id):
    authenticate()
    authorize(*READ_ROLES)
    return one("mobile_units", need("mobile_units", unit_id, "ERR_RECORD_NOT_FOUND"))


@bp.post("/mobile-units/<unit_id>/service-status")
def set_service_status(unit_id):
    authenticate()
    authorize("PlatformAdmin")
    unit = need("mobile_units", unit_id, "ERR_RECORD_NOT_FOUND")
    data = body()
    value = req_str(data, "service_status")
    enum_value(value, UNIT_SERVICE_STATUS_ENUM, "service_status")
    unit["service_status"] = value
    db.touch(unit)
    return one("mobile_units", unit)


# ==========================================================================
# Equipment
# ==========================================================================

@bp.post("/equipment")
def create_equipment():
    authenticate()
    authorize("PlatformAdmin")
    data = body()
    modality = req_str(data, "modality")
    serial_label = req_str(data, "serial_label")
    assigned_unit_id = opt_id(data, "assigned_unit_id")
    enum_value(modality, MODALITY_ENUM, "modality")
    if assigned_unit_id is not None:
        need("mobile_units", assigned_unit_id, "ERR_RECORD_NOT_FOUND")
    rec = db.new_record()
    rec.update(
        {
            "assigned_unit_id": assigned_unit_id,
            "modality": modality,
            "serial_label": serial_label,
            "calibration_valid_from": None,
            "calibration_valid_until": None,
            "usage_count_since_qc": 0,
            "last_passing_qc_at": None,
            "quarantined_at": None,
        }
    )
    db.insert("equipment", rec)
    return one("equipment", rec, 201)


@bp.get("/equipment/<equipment_id>")
def get_equipment(equipment_id):
    authenticate()
    authorize(*READ_ROLES)
    return one("equipment", need("equipment", equipment_id, "ERR_EQUIPMENT_NOT_FOUND"))


@bp.get("/equipment")
def list_equipment():
    authenticate()
    authorize(*READ_ROLES)
    rows = db.all_rows("equipment")
    rows = apply_filters(rows, {"assigned_unit_id": "assigned_unit_id",
                                "modality": "modality"})
    rows = apply_derived_filter(rows, "calibration_status", derive.calibration_status)
    return listing("equipment", rows)


@bp.post("/equipment/<equipment_id>/assign")
def assign_equipment(equipment_id):
    authenticate()
    authorize("PlatformAdmin")
    equipment = need("equipment", equipment_id, "ERR_EQUIPMENT_NOT_FOUND")
    data = body()
    if "assigned_unit_id" not in data:
        fail("Field 'assigned_unit_id' is required.")
    unit_id = data.get("assigned_unit_id")
    if unit_id is not None:
        if not isinstance(unit_id, str):
            fail("Field 'assigned_unit_id' must be a string identifier or null.")
        need("mobile_units", unit_id, "ERR_RECORD_NOT_FOUND")
    equipment["assigned_unit_id"] = unit_id
    db.touch(equipment)
    return one("equipment", equipment)


@bp.post("/equipment/<equipment_id>/calibrate")
def calibrate_equipment(equipment_id):
    authenticate()
    authorize("PlatformAdmin")
    equipment = need("equipment", equipment_id, "ERR_EQUIPMENT_NOT_FOUND")
    data = body()
    from_raw = req_str(data, "calibration_valid_from")
    until_raw = req_str(data, "calibration_valid_until")
    valid_from = clock.parse_instant(from_raw)
    valid_until = clock.parse_instant(until_raw)
    if valid_from is None:
        fail("Field 'calibration_valid_from' must be an ISO 8601 instant.")
    if valid_until is None:
        fail("Field 'calibration_valid_until' must be an ISO 8601 instant.")
    if valid_until <= valid_from:
        fail("calibration_valid_until must be strictly after calibration_valid_from.")
    if (valid_until - valid_from).total_seconds() > CALIBRATION_VALIDITY_DAYS * 86400:
        fail("A calibration window may span at most 30 days.")

    # The supplied window need not contain the logical clock (PRD 3.1).
    equipment["calibration_valid_from"] = valid_from
    equipment["calibration_valid_until"] = valid_until
    equipment["quarantined_at"] = None
    equipment["usage_count_since_qc"] = 0
    db.touch(equipment)
    return one("equipment", equipment)


# ==========================================================================
# Technician
# ==========================================================================

@bp.post("/technicians")
def create_technician():
    authenticate()
    authorize("PlatformAdmin")
    data = body()
    full_name = req_str(data, "full_name")
    modalities = req_list(data, "certified_modalities")
    status = opt_str(data, "status", "ACTIVE")
    enum_members(modalities, MODALITY_ENUM, "certified_modalities")
    enum_value(status, TECHNICIAN_STATUS_ENUM, "status")
    rec = db.new_record()
    rec.update(
        {
            "full_name": full_name,
            "certified_modalities": list(modalities),
            "status": status,
        }
    )
    db.insert("technicians", rec)
    return one("technicians", rec, 201)


@bp.get("/technicians/<technician_id>")
def get_technician(technician_id):
    authenticate()
    authorize(*READ_ROLES)
    return one("technicians", need("technicians", technician_id, "ERR_RECORD_NOT_FOUND"))


# ==========================================================================
# Specialist
# ==========================================================================

@bp.post("/specialists")
def create_specialist():
    authenticate()
    authorize("PlatformAdmin")
    data = body()
    full_name = req_str(data, "full_name")
    modality_privileges = req_list(data, "modality_privileges")
    species_privileges = req_list(data, "species_privileges")
    stat_eligible = opt_bool(data, "stat_eligible", False)
    status = opt_str(data, "status", "ACTIVE")
    enum_members(modality_privileges, MODALITY_ENUM, "modality_privileges")
    enum_members(species_privileges, SPECIES_ENUM, "species_privileges")
    enum_value(status, SPECIALIST_STATUS_ENUM, "status")
    rec = db.new_record()
    rec.update(
        {
            "full_name": full_name,
            "modality_privileges": list(modality_privileges),
            "species_privileges": list(species_privileges),
            "stat_eligible": stat_eligible,
            "status": status,
        }
    )
    db.insert("specialists", rec)
    return one("specialists", rec, 201)


@bp.get("/specialists/<specialist_id>")
def get_specialist(specialist_id):
    authenticate()
    authorize(*READ_ROLES)
    return one("specialists", need("specialists", specialist_id, "ERR_SPECIALIST_NOT_FOUND"))
