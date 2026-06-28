"""TreatmentPlan + Deposit routes (PRD §3.3)."""
from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import ApiError
from middleware import require_roles
from helpers import (get_json_body, require_string, require_enum, require_int,
                     paginate)
from response import success_object, success_array
import domain

bp = Blueprint("plans", __name__)

PRODUCTS = {"BOTOX", "DYSPORT", "JUVEDERM", "RESTYLANE"}


def _base_common():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


# --------------------------------------------------------------------------
# TreatmentPlan
# --------------------------------------------------------------------------
@bp.route("/aesthetics/treatment-plans", methods=["POST"])
@require_roles("Provider")
def create_plan():
    body = get_json_body()
    patient_id = require_string(body, "patient_id")
    consultation_id = require_string(body, "consultation_id")
    product = require_enum(body, "product", PRODUCTS)
    planned_sessions = require_int(body, "planned_sessions", minimum=1)
    planned_units_per_session = require_int(body, "planned_units_per_session", positive=True)
    list_price_per_unit_cents = require_int(body, "list_price_per_unit_cents", positive=True)
    required_deposit_cents = require_int(body, "required_deposit_cents", minimum=0)

    if patient_id not in db.patients:
        raise ApiError("ERR_PATIENT_NOT_FOUND", "Patient not found")
    if consultation_id not in db.consultations:
        raise ApiError("ERR_CONSULTATION_NOT_FOUND", "Consultation not found")

    plan = _base_common()
    plan.update({
        "patient_id": patient_id,
        "consultation_id": consultation_id,
        "product": product,
        "planned_sessions": planned_sessions,
        "planned_units_per_session": planned_units_per_session,
        "list_price_per_unit_cents": list_price_per_unit_cents,
        "required_deposit_cents": required_deposit_cents,
        "deposit_paid_cents": 0,
        "provisional_series_cost_cents": 0,
        "finalized_series_cost_cents": 0,
        "sessions_committed": 0,
        "status": "PROPOSED",
    })
    domain.recompute_plan_provisional(plan)
    db.treatment_plans[plan["id"]] = plan
    return success_object(domain.serialize(plan, "TreatmentPlan"), 201)


@bp.route("/aesthetics/treatment-plans", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def list_plans():
    patient_id = request.args.get("patient_id")
    consultation_id = request.args.get("consultation_id")
    status = request.args.get("status")
    records = list(db.treatment_plans.values())
    if patient_id is not None:
        records = [r for r in records if r["patient_id"] == patient_id]
    if consultation_id is not None:
        records = [r for r in records if r["consultation_id"] == consultation_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return success_array([domain.serialize(r, "TreatmentPlan") for r in page],
                         limit, offset, total)


@bp.route("/aesthetics/treatment-plans/<pid>", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def get_plan(pid):
    plan = db.treatment_plans.get(pid)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "Treatment plan not found")
    return success_object(domain.serialize(plan, "TreatmentPlan"))


def _check_plan_occ(plan, body):
    expected = require_int(body, "expected_treatment_plan_version")
    if expected != plan["version"]:
        raise ApiError("ERR_STALE_PLAN_VERSION", "Stale plan version")


@bp.route("/aesthetics/treatment-plans/<pid>/activate", methods=["POST"])
@require_roles("Provider")
def activate_plan(pid):
    plan = db.treatment_plans.get(pid)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "Treatment plan not found")
    body = get_json_body()
    # priority 6 OCC, priority 7 state — but PRD §3.3 lists state (PROPOSED) first
    # then OCC. PRD §2.8 fixes precedence: OCC (6) before source-state (7).
    if plan["status"] != "PROPOSED":
        raise ApiError("ERR_PLAN_NOT_PROPOSED", "Plan not PROPOSED")
    _check_plan_occ(plan, body)
    consultation = db.consultations.get(plan["consultation_id"])
    if consultation is None or consultation["status"] != "EXAM_COMPLETE":
        raise ApiError("ERR_NO_GOOD_FAITH_EXAM", "Referenced consultation not EXAM_COMPLETE")
    if plan["deposit_paid_cents"] < plan["required_deposit_cents"]:
        raise ApiError("ERR_DEPOSIT_REQUIRED", "Deposit not satisfied")

    plan["status"] = "ACTIVE"
    domain.recompute_plan_provisional(plan)
    domain.touch(plan)
    return success_object(domain.serialize(plan, "TreatmentPlan"))


@bp.route("/aesthetics/treatment-plans/<pid>/complete", methods=["POST"])
@require_roles("Provider")
def complete_plan(pid):
    plan = db.treatment_plans.get(pid)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "Treatment plan not found")
    body = get_json_body()
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", "Plan not ACTIVE")
    _check_plan_occ(plan, body)
    open_session = any(
        s["treatment_plan_id"] == pid and s["status"] in ("BOOKED", "COMMITTED", "COMPLICATION_OPEN")
        for s in db.treatment_sessions.values()
    )
    if open_session:
        raise ApiError("ERR_OPEN_SESSIONS_EXIST", "Plan has open sessions")

    plan["status"] = "COMPLETED"
    plan["provisional_series_cost_cents"] = 0
    domain.touch(plan)
    return success_object(domain.serialize(plan, "TreatmentPlan"))


@bp.route("/aesthetics/treatment-plans/<pid>/cancel", methods=["POST"])
@require_roles("ClinicAdmin")
def cancel_plan(pid):
    plan = db.treatment_plans.get(pid)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "Treatment plan not found")
    body = get_json_body()
    if plan["status"] not in ("PROPOSED", "ACTIVE"):
        raise ApiError("ERR_PLAN_NOT_CANCELLABLE", "Plan not cancellable")
    _check_plan_occ(plan, body)
    if plan["sessions_committed"] != 0:
        raise ApiError("ERR_PLAN_HAS_COMMITTED_SESSIONS", "Plan has committed sessions")

    # Cascade compensation: refund POSTED deposits, cancel BOOKED sessions.
    for dep in db.deposits.values():
        if dep["treatment_plan_id"] == pid and dep["status"] == "POSTED":
            dep["status"] = "REFUNDED"
            domain.touch(dep)
    domain.recompute_plan_deposit_paid(plan)

    for sess in db.treatment_sessions.values():
        if sess["treatment_plan_id"] == pid and sess["status"] == "BOOKED":
            _release_session_reservations(sess)
            sess["status"] = "CANCELLED"
            domain.touch(sess)

    plan["status"] = "CANCELLED"
    domain.recompute_plan_provisional(plan)
    domain.touch(plan)
    return success_object(domain.serialize(plan, "TreatmentPlan"))


def _release_session_reservations(session):
    """Release all reserved units this session holds back to its lots."""
    for lot_id, qty in session.get("_reservations", {}).items():
        lot = db.injectable_lots.get(lot_id)
        if lot is None or qty <= 0:
            continue
        lot["reserved_units"] -= qty
        domain.recompute_lot_remaining(lot)
        domain.touch(lot)
    session["_reservations"] = {}


# --------------------------------------------------------------------------
# Deposit
# --------------------------------------------------------------------------
@bp.route("/aesthetics/deposits", methods=["POST"])
@require_roles("ClinicAdmin")
def create_deposit():
    body = get_json_body()
    treatment_plan_id = require_string(body, "treatment_plan_id")
    amount_cents = require_int(body, "amount_cents", positive=True)

    plan = db.treatment_plans.get(treatment_plan_id)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "Treatment plan not found")
    _check_plan_occ(plan, body)

    deposit = _base_common()
    deposit.update({
        "treatment_plan_id": treatment_plan_id,
        "amount_cents": amount_cents,
        "status": "POSTED",
    })
    db.deposits[deposit["id"]] = deposit

    domain.recompute_plan_deposit_paid(plan)
    domain.touch(plan)
    return success_object(domain.serialize(deposit, "Deposit"), 201)


@bp.route("/aesthetics/deposits", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def list_deposits():
    treatment_plan_id = request.args.get("treatment_plan_id")
    status = request.args.get("status")
    records = list(db.deposits.values())
    if treatment_plan_id is not None:
        records = [r for r in records if r["treatment_plan_id"] == treatment_plan_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return success_array([domain.serialize(r, "Deposit") for r in page],
                         limit, offset, total)


@bp.route("/aesthetics/deposits/<did>", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def get_deposit(did):
    deposit = db.deposits.get(did)
    if deposit is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "Deposit not found")
    return success_object(domain.serialize(deposit, "Deposit"))
