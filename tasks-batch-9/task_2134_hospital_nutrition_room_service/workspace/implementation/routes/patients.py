"""Patient admission, the bedside clinical profile and discharge (PRD section 3.1)."""

from decimal import Decimal

from flask import Blueprint

import api
import domain
import serialize
import store
from calcs import LIQUID_LEVELS, TEXTURE_LEVELS
from errors import ApiError

bp = Blueprint("patients", __name__, url_prefix="/nutrition/patients")

PATIENT_STATUSES = ("ADMITTED", "DISCHARGED")
NPO_STATUSES = ("NONE", "NPO_STRICT", "NPO_CLEAR_LIQUIDS")


@bp.post("")
@api.require("DietClerk", "NutritionManager")
def admit_patient():
    body = api.body()
    ward_id = api.req_id(body, "ward_id")
    mrn = api.req_str(body, "mrn")
    full_name = api.req_str(body, "full_name")
    age_years = api.req_int(body, "age_years", lo=0, hi=120)
    allergens = api.opt_str_list(body, "allergen_codes", [])
    texture = api.opt_enum(body, "texture_level", TEXTURE_LEVELS, "REGULAR")
    liquid = api.opt_enum(body, "liquid_level", LIQUID_LEVELS, "THIN")

    store.get_ward(ward_id)

    if any(p["mrn"] == mrn for p in store.patients.values()):
        raise ApiError("ERR_DUPLICATE_MRN",
                       "A patient with mrn '%s' already exists." % mrn)

    patient = {
        "ward_id": ward_id,
        "mrn": mrn,
        "full_name": full_name,
        "age_years": age_years,
        "allergen_codes": allergens,
        "texture_level": texture,
        "liquid_level": liquid,
        "status": "ADMITTED",
        "npo_status": "NONE",
        "missed_meal_count": 0,
        "protein_deficit_g": Decimal("0.0"),
        "daily_supplement_cost_cents": 0,
        "survey_count": 0,
        "satisfaction_score_avg": None,
    }
    store.stamp_new(patient)
    store.patients[patient["id"]] = patient
    return api.created(serialize.patient(patient))


@bp.get("")
@api.require(*api.ALL_ROLES)
def list_patients():
    ward_id = api.q_str("ward_id")
    status = api.q_enum("status", PATIENT_STATUSES)
    npo_status = api.q_enum("npo_status", NPO_STATUSES)
    rows = api.filtered(list(store.patients.values()),
                        [(ward_id, "ward_id"), (status, "status"),
                         (npo_status, "npo_status")])
    return api.paged(rows, serialize.patient)


@bp.get("/<patient_id>")
@api.require(*api.ALL_ROLES)
def read_patient(patient_id):
    return api.ok(serialize.patient(store.get_patient(patient_id)))


@bp.patch("/<patient_id>")
@api.require("DietClerk", "Dietitian")
def update_patient(patient_id):
    patient = store.get_patient(patient_id)
    body = api.body()
    allergens = api.opt_str_list(body, "allergen_codes", None) if "allergen_codes" in body else None
    texture = api.opt_enum(body, "texture_level", TEXTURE_LEVELS)
    liquid = api.opt_enum(body, "liquid_level", LIQUID_LEVELS)

    if allergens is not None:
        patient["allergen_codes"] = allergens
    if texture is not None:
        patient["texture_level"] = texture
    if liquid is not None:
        patient["liquid_level"] = liquid
    store.touch(patient)
    return api.ok(serialize.patient(patient))


@bp.post("/<patient_id>/discharge")
@api.require("DietClerk", "NutritionManager")
def discharge_patient(patient_id):
    patient = store.get_patient(patient_id)
    if patient["status"] != "ADMITTED":
        raise ApiError("ERR_INVALID_STATE", "The patient is not ADMITTED.")

    # Cascade level 1 -- cancel every open tray for this patient.
    touched_periods = []
    trays = store.sort_rows([o for o in store.meal_orders.values()
                             if o["patient_id"] == patient_id
                             and o["fulfillment_status"] in domain.OPEN_TRAY_STATES])
    for tray in trays:
        was_committed = tray["fulfillment_status"] in domain.COMMITTED_STATES
        tray["fulfillment_status"] = "CANCELLED"
        store.touch(tray)
        if was_committed:
            touched_periods.append(tray["meal_period_id"])

    # Cascade levels 2 and 3 -- re-ledger and re-forecast the affected periods.
    domain.reledger_periods(touched_periods)

    # Every SCHEDULED procedure hold for this patient is cancelled.
    for hold in store.sort_rows([h for h in store.procedure_holds.values()
                                 if h["patient_id"] == patient_id
                                 and h["status"] == "SCHEDULED"]):
        hold["status"] = "CANCELLED"
        store.touch(hold)

    # The ACTIVE diet order, if any, is discontinued.
    active_order = store.active_diet_order_of(patient_id)
    if active_order is not None:
        active_order["status"] = "DISCONTINUED"
        store.touch(active_order)

    patient["status"] = "DISCHARGED"
    store.touch(patient)
    return api.ok(serialize.patient(patient))
