"""Plan registration, patient enrolment, prescription recording, logical clock."""

from flask import Blueprint

import calc
import clock
import db
import enums
import middleware
import response
import store
import validators

bp = Blueprint("setup", __name__)


@bp.post("/insurance-plans")
def create_insurance_plan():
    middleware.authenticate(("PlatformAdmin",))
    body = validators.json_body()
    plan = store.create(
        db.insurance_plans,
        {
            "payer_name": validators.string(body, "payer_name"),
            "bin_number": validators.string(body, "bin_number"),
            "refill_too_soon_threshold_pct": validators.integer(
                body, "refill_too_soon_threshold_pct", required=False, default=75,
                minimum=0, maximum=100,
            ),
            "max_day_supply_days": validators.integer(
                body, "max_day_supply_days", required=False, default=90,
                minimum=1, maximum=365,
            ),
            "vacation_overrides_per_year": validators.integer(
                body, "vacation_overrides_per_year", required=False, default=1,
                minimum=0, maximum=12,
            ),
            "generic_copay_cents_per_day": validators.integer(
                body, "generic_copay_cents_per_day", minimum=0
            ),
            "brand_copay_cents_per_day": validators.integer(
                body, "brand_copay_cents_per_day", minimum=0
            ),
            "specialty_copay_cents_per_day": validators.integer(
                body, "specialty_copay_cents_per_day", minimum=0
            ),
            "coinsurance_pct": validators.integer(
                body, "coinsurance_pct", required=False, default=20,
                minimum=0, maximum=100,
            ),
            "allows_payer_vacation_override": validators.boolean(
                body, "allows_payer_vacation_override", required=False, default=False
            ),
        },
    )
    return response.object_response(store.serialize(plan), 201)


@bp.post("/patients")
def create_patient():
    middleware.authenticate(("PlatformAdmin", "PharmacyOperations"))
    body = validators.json_body()
    full_name = validators.string(body, "full_name")
    date_of_birth = validators.date_field(body, "date_of_birth")
    email = validators.string(body, "email")
    state_code = validators.string(body, "state_code")
    plan_id = validators.string(body, "insurance_plan_id")
    middleware.lookup("insurance_plan", plan_id)

    patient = store.create(
        db.patients,
        {
            "full_name": full_name,
            "date_of_birth": store.fmt_date(date_of_birth),
            "email": email,
            "state_code": state_code,
            "insurance_plan_id": plan_id,
            "anchor_fill_day": None,
            "sync_mode": None,
            "sync_status": "UNSYNCED",
            "next_cycle_start_date": None,
            "autoship_status": "ACTIVE",
            "pause_reason": None,
            "adherence_score_pct": 100,
            "consecutive_missed_pickups": 0,
            "credit_balance_cents": 0,
            "vacation_exceptions_used_this_year": 0,
        },
    )
    return response.object_response(store.serialize(patient), 201)


@bp.post("/prescriptions")
def create_prescription():
    middleware.authenticate(("Prescriber", "PharmacyOperations"))
    body = validators.json_body()
    patient_id = validators.string(body, "patient_id")
    prescriber_npi = validators.string(body, "prescriber_npi")
    drug_name = validators.string(body, "drug_name")
    ndc = validators.string(body, "ndc")
    strength = validators.string(body, "strength")
    form = validators.enum(body, "form", enums.FORMS)
    copay_tier = validators.enum(body, "copay_tier", enums.COPAY_TIERS)
    refrigerated = validators.boolean(body, "refrigerated", required=False, default=False)
    is_controlled = validators.boolean(body, "is_controlled", required=False, default=False)
    dose_times = validators.string_array(
        body, "dose_times", non_empty=True, distinct=True, allowed=enums.DOSE_SLOTS
    )
    quantity_per_dose = validators.integer(body, "quantity_per_dose", minimum=1)
    days_supply_written = validators.integer(
        body, "days_supply_written", minimum=1, maximum=90
    )
    refills_authorized = validators.integer(body, "refills_authorized", minimum=0)
    written_date = validators.date_field(body, "written_date")
    expiration_date = validators.date_field(body, "expiration_date")
    last_dispensed_date = validators.date_field(
        body, "last_dispensed_date", required=False, default=None
    )
    last_dispensed_days_supply = validators.integer(
        body, "last_dispensed_days_supply", required=False, default=0, minimum=0
    )

    middleware.lookup("patient", patient_id)

    prescription = store.create(
        db.prescriptions,
        {
            "patient_id": patient_id,
            "prescriber_npi": prescriber_npi,
            "drug_name": drug_name,
            "ndc": ndc,
            "strength": strength,
            "form": form,
            "copay_tier": copay_tier,
            "refrigerated": refrigerated,
            "is_controlled": is_controlled,
            "packable": calc.is_packable(form, refrigerated),
            "dose_times": list(dose_times),
            "quantity_per_dose": quantity_per_dose,
            "days_supply_written": days_supply_written,
            "refills_authorized": refills_authorized,
            "refills_remaining": refills_authorized,
            "refills_consumed": 0,
            "written_date": store.fmt_date(written_date),
            "expiration_date": store.fmt_date(expiration_date),
            "status": "ACTIVE",
            "supersedes_rx_id": None,
            "last_dispensed_date": (
                store.fmt_date(last_dispensed_date) if last_dispensed_date else None
            ),
            "last_dispensed_days_supply": last_dispensed_days_supply,
            "prior_last_dispensed_date": None,
            "prior_last_dispensed_days_supply": 0,
            "days_dispensed_total": 0,
            "sync_bridge_days": 0,
            "sync_trim_days": 0,
        },
    )
    return response.object_response(store.serialize(prescription), 201)


@bp.post("/_clock/set_current_utc")
def set_clock():
    body = validators.json_body()
    current_utc = validators.instant_field(body, "current_utc")
    clock.set_now(current_utc)
    return response.object_response({"current_utc": clock.now_iso()})
