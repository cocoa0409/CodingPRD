"""Clock, members, practitioners, pharmacies and physical stock (PRD 3.1)."""

from flask import Blueprint

import calculations as calc
import envelope
import errors
import serializers
import services
import validation as v
from auth import ANY_ROLE, guard
from errors import ApiError
from store import new_record, ordered, parse_iso, store, touch

bp = Blueprint("directory", __name__)

COMORBIDITY_CODES = ("TYPE_2_DIABETES", "HYPERTENSION", "DYSLIPIDEMIA", "OSA", "CVD")
PAYMENT_MODES = ("INSURANCE", "CASH")
PROVIDER_TYPES = ("CLINICIAN", "COACH")
PROVIDER_STATUSES = ("ACTIVE", "SUSPENDED")
DISPENSE_TYPES = ("COMPOUNDED", "BRANDED")
PHARMACY_STATUSES = ("ACTIVE", "SUSPENDED")
LOT_STATUSES = ("RELEASED", "QUARANTINED")


# --- logical clock (PRD 2.4) ----------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    guard(["PlatformAdmin"])
    body = v.body()
    raw = v.datetime_field(body, "to_iso8601", required=True)
    store.set_clock(raw, parse_iso(raw))
    return envelope.success({"current_utc": store.clock_raw}, 200)


# --- members ---------------------------------------------------------------
@bp.post("/patients")
def create_patient():
    guard(["PlatformAdmin"])
    body = v.body()

    email = v.string_field(body, "email", required=True)
    if "@" not in email:
        raise ApiError(errors.ERR_VALIDATION, "email must contain '@'.")
    for existing in store.patients.values():
        if existing["email"] == email:
            raise ApiError(errors.ERR_VALIDATION, "email is already enrolled.")

    full_name = v.string_field(body, "full_name", required=True)
    state_code = v.state_code_field(body, "state_code", required=True)
    height_cm = v.number_field(body, "height_cm", required=True, exclusive_minimum=0)
    weight_kg = v.number_field(body, "weight_kg", required=True, exclusive_minimum=0)
    payment_mode = v.enum_field(body, "payment_mode", PAYMENT_MODES, required=True)
    comorbidity_codes = v.enum_list(body, "comorbidity_codes", COMORBIDITY_CODES,
                                    required=False, default=[])

    patient = new_record(store.patients, {
        "email": email,
        "full_name": full_name,
        "state_code": state_code,
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "comorbidity_codes": comorbidity_codes,
        "payment_mode": payment_mode,
        "current_bmi": calc.bmi_float(weight_kg, height_cm),
        "eligibility_status": "NOT_SCREENED",
        "lifetime_charged_cents": 0,
        "lifetime_credited_cents": 0,
    })
    return envelope.success(serializers.dump("patient", patient), 201)


@bp.get("/patients/<patient_id>")
def read_patient(patient_id):
    guard(ANY_ROLE)
    patient = services.get_patient(patient_id)
    return envelope.success(serializers.dump("patient", patient), 200)


@bp.patch("/patients/<patient_id>/vitals")
def update_vitals(patient_id):
    guard(["Patient", "Provider"])
    patient = services.get_patient(patient_id)
    body = v.body()
    weight_kg = v.number_field(body, "weight_kg", required=True, exclusive_minimum=0)

    patient["weight_kg"] = weight_kg
    patient["current_bmi"] = calc.bmi_float(weight_kg, patient["height_cm"])
    touch(patient)
    return envelope.success(serializers.dump("patient", patient), 200)


# --- practitioners ---------------------------------------------------------
@bp.post("/providers")
def create_provider():
    guard(["PlatformAdmin"])
    body = v.body()

    full_name = v.string_field(body, "full_name", required=True)
    provider_type = v.enum_field(body, "provider_type", PROVIDER_TYPES, required=True)
    licensed_state_codes = v.state_code_list(body, "licensed_state_codes",
                                             required=False, default=[])
    npi = v.string_field(body, "npi", required=False, default=None)
    if provider_type == "CLINICIAN" and npi is None:
        raise ApiError(errors.ERR_VALIDATION, "npi is required for a CLINICIAN.")
    if provider_type == "COACH":
        npi = None
    status = v.enum_field(body, "status", PROVIDER_STATUSES, required=False,
                          default="ACTIVE")

    provider = new_record(store.providers, {
        "full_name": full_name,
        "provider_type": provider_type,
        "npi": npi,
        "licensed_state_codes": licensed_state_codes,
        "status": status,
    })
    return envelope.success(serializers.dump("provider", provider), 201)


# --- pharmacies ------------------------------------------------------------
@bp.post("/pharmacies")
def create_pharmacy():
    guard(["PlatformAdmin"])
    body = v.body()

    name = v.string_field(body, "name", required=True)
    dispense_type = v.enum_field(body, "dispense_type", DISPENSE_TYPES, required=True)
    served_state_codes = v.state_code_list(body, "served_state_codes",
                                           required=False, default=[])
    status = v.enum_field(body, "status", PHARMACY_STATUSES, required=False,
                          default="ACTIVE")

    pharmacy = new_record(store.pharmacies, {
        "name": name,
        "dispense_type": dispense_type,
        "served_state_codes": served_state_codes,
        "status": status,
    })
    return envelope.success(serializers.dump("pharmacy", pharmacy), 201)


# --- supply lots -----------------------------------------------------------
@bp.post("/supply-lots")
def create_supply_lot():
    guard(["PlatformAdmin"])
    body = v.body()

    pharmacy_id = v.string_field(body, "pharmacy_id", required=True)
    lot_code = v.string_field(body, "lot_code", required=True)
    strength_mg = v.number_field(body, "strength_mg", required=True, exclusive_minimum=0)
    total_units = v.int_field(body, "total_units", required=True, minimum=0)
    window_capacity_units = v.int_field(body, "window_capacity_units", required=True,
                                        minimum=0)
    expires_at = v.datetime_field(body, "expires_at", required=True)
    status = v.enum_field(body, "status", LOT_STATUSES, required=False,
                          default="RELEASED")

    services.get_pharmacy(pharmacy_id)

    lot = new_record(store.supply_lots, {
        "pharmacy_id": pharmacy_id,
        "lot_code": lot_code,
        "strength_mg": strength_mg,
        "total_units": total_units,
        "window_capacity_units": window_capacity_units,
        "available_units": total_units,
        "reserved_units": 0,
        "dispensed_units": 0,
        "expires_at": expires_at,
        "status": status,
    })
    return envelope.success(serializers.dump("supply_lot", lot), 201)


@bp.get("/supply-lots/<supply_lot_id>")
def read_supply_lot(supply_lot_id):
    guard(ANY_ROLE)
    lot = services.get_supply_lot(supply_lot_id)
    return envelope.success(serializers.dump("supply_lot", lot), 200)


@bp.get("/supply-lots")
def list_supply_lots():
    guard(ANY_ROLE)
    limit, offset = v.pagination()
    filters = v.query_filters("pharmacy_id", "status")
    records = v.apply_filters(ordered(list(store.supply_lots.values())), filters)
    page, total = v.paginate(records, limit, offset)
    return envelope.collection(serializers.dump_many("supply_lot", page),
                               limit, offset, total)
