"""Patient registration, payments, ledger, and insurance policies."""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, authorize, get_json_body, paginate
from models import new_record, touch, serialize, serialize_list
from lookups import get_patient_or_404, leaf_or_404, ref_or_404
from response import ok, created
from services.ledger import add_entry
import validators as V

bp = Blueprint("patients", __name__)

PAYER_MODES = {"INSURANCE", "CASH", "WELLNESS"}
READ_PATIENT = ["FrontDesk", "PracticeAdmin", "Provider", "BillingClerk"]


@bp.route("/patients", methods=["POST"])
def register_patient():
    _, role = authenticate()
    authorize(role, ["FrontDesk", "PracticeAdmin"])
    body = get_json_body()
    full_name = V.require_str(body, "full_name")
    dob = V.require_str(body, "date_of_birth")
    payer_mode = V.optional_enum(body, "payer_mode", PAYER_MODES, default="CASH")
    wellness_plan_id = body.get("wellness_plan_id")

    # FK existence for wellness_plan_id (priority 5) before coherence check.
    if wellness_plan_id is not None:
        ref_or_404(db.wellness_plans, wellness_plan_id)

    # Payer-mode coherence (priority 10): WELLNESS requires wellness_plan_id;
    # CASH/INSURANCE forbid it.
    if payer_mode == "WELLNESS" and not wellness_plan_id:
        raise err("ERR_PAYER_MODE_MISMATCH", "WELLNESS patient requires a wellness_plan_id")
    if payer_mode in ("CASH", "INSURANCE") and wellness_plan_id:
        raise err("ERR_PAYER_MODE_MISMATCH", "wellness_plan_id forbidden for CASH/INSURANCE patient")

    rec = new_record({
        "full_name": full_name,
        "date_of_birth": dob,
        "payer_mode": payer_mode,
        "wellness_plan_id": wellness_plan_id,
        "no_show_strike_count": 0,
        "ledger_balance_cents": 0,
        "is_dismissed": False,
        "status": "ACTIVE",
    })
    db.patients[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/patients", methods=["GET"])
def list_patients():
    _, role = authenticate()
    authorize(role, READ_PATIENT)
    items = list(db.patients.values())
    status = request.args.get("status")
    payer_mode = request.args.get("payer_mode")
    wellness_plan_id = request.args.get("wellness_plan_id")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if payer_mode is not None:
        items = [p for p in items if p["payer_mode"] == payer_mode]
    if wellness_plan_id is not None:
        items = [p for p in items if p.get("wellness_plan_id") == wellness_plan_id]
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/patients/<patient_id>", methods=["GET"])
def get_patient(patient_id):
    _, role = authenticate()
    authorize(role, READ_PATIENT)
    rec = get_patient_or_404(patient_id)
    return ok(serialize(rec))


@bp.route("/patients/<patient_id>/payments", methods=["POST"])
def post_payment(patient_id):
    _, role = authenticate()
    authorize(role, ["FrontDesk", "BillingClerk"])
    patient = get_patient_or_404(patient_id)
    body = get_json_body()
    amount = V.require_int(body, "amount_cents")
    if amount <= 0:
        raise err("ERR_VALIDATION", "amount_cents must be positive")
    entry = add_entry(patient, "PATIENT_PAYMENT", -amount, memo="Patient payment")
    return created(serialize(entry))


@bp.route("/patients/<patient_id>/ledger-entries", methods=["GET"])
def list_patient_ledger(patient_id):
    _, role = authenticate()
    authorize(role, ["FrontDesk", "PracticeAdmin", "BillingClerk"])
    get_patient_or_404(patient_id)
    items = [e for e in db.ledger_entries.values() if e["patient_id"] == patient_id]
    entry_type = request.args.get("entry_type")
    appointment_id = request.args.get("appointment_id")
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    if appointment_id is not None:
        items = [e for e in items if e.get("appointment_id") == appointment_id]
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


# ---- Insurance policies ----
@bp.route("/patients/<patient_id>/insurance-policies", methods=["POST"])
def add_policy(patient_id):
    _, role = authenticate()
    authorize(role, ["FrontDesk", "BillingClerk", "PracticeAdmin"])
    patient = get_patient_or_404(patient_id)
    body = get_json_body()
    cap = V.require_int(body, "annual_visit_cap")
    deductible = V.require_int(body, "deductible_total_cents")
    coins = V.require_number(body, "coinsurance_pct")
    allowed = V.require_int(body, "allowed_amount_cents")
    if cap < 0 or deductible < 0 or allowed < 0:
        raise err("ERR_INVALID_REQUEST", "Amounts must be >= 0")
    if not (0.0 <= coins <= 1.0):
        raise err("ERR_INVALID_REQUEST", "coinsurance_pct must be between 0.0 and 1.0")
    rec = new_record({
        "patient_id": patient["id"],
        "carrier_name": V.require_str(body, "carrier_name"),
        "annual_visit_cap": cap,
        "visits_reserved": 0,
        "visits_committed": 0,
        "deductible_total_cents": deductible,
        "deductible_met_cents": 0,
        "coinsurance_pct": coins,
        "allowed_amount_cents": allowed,
        "status": "ACTIVE",
    })
    db.insurance_policies[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/patients/<patient_id>/insurance-policies", methods=["GET"])
def list_policies(patient_id):
    _, role = authenticate()
    authorize(role, ["FrontDesk", "BillingClerk", "PracticeAdmin", "Provider"])
    get_patient_or_404(patient_id)
    items = [p for p in db.insurance_policies.values() if p["patient_id"] == patient_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/patients/<patient_id>/insurance-policies/<policy_id>/terminate", methods=["POST"])
def terminate_policy(patient_id, policy_id):
    _, role = authenticate()
    authorize(role, ["BillingClerk", "PracticeAdmin"])
    get_patient_or_404(patient_id)
    policy = leaf_or_404(db.insurance_policies, policy_id, patient_id, "patient_id")
    if policy["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Policy is not ACTIVE")
    policy["status"] = "TERMINATED"
    touch(policy)
    return ok(serialize(policy))
