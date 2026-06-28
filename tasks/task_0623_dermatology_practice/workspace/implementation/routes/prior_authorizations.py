"""PriorAuthorization + StepTherapyTrial (cyclic step therapy) (PRD 3.9)."""
from flask import Blueprint, request

import db
import errors
import helpers
import response
import services
from middleware import require

bp = Blueprint("prior_authorizations", __name__)

OUTCOMES = {"FAILED", "EFFECTIVE", "NOT_TRIED"}
DECISIONS = {"APPROVE", "DENY"}


@bp.post("/prior-authorizations")
@require("BillingSpecialist")
def create_pa():
    data = helpers.body()
    patient_id = helpers.require_str(data, "patient_id")
    drug_name = helpers.require_str(data, "drug_name")
    required_step_count = helpers.require_int(data, "required_step_count")
    list_price_cents = helpers.require_int(data, "list_price_cents")
    if required_step_count < 0:
        raise errors.invalid_request("required_step_count must be >= 0")
    helpers.get_or_404(db.patients, patient_id, "patient")
    row = {
        "patient_id": patient_id,
        "drug_name": drug_name,
        "required_step_count": required_step_count,
        "list_price_cents": list_price_cents,
        "status": "DRAFT",
        "satisfied_step_count": 0,
        "submission_round": 0,
    }
    db.stamp_new(row)
    db.prior_authorizations[row["id"]] = row
    return response.created(row)


@bp.get("/prior-authorizations/<paid>")
@require("BillingSpecialist", "PracticeAdmin", "Provider")
def get_pa(paid):
    row = helpers.get_or_404(db.prior_authorizations, paid, "prior_auth")
    return response.ok(row)


@bp.get("/prior-authorizations")
@require("BillingSpecialist", "PracticeAdmin", "Provider")
def list_pa():
    rows = list(db.prior_authorizations.values())
    pid = request.args.get("patient_id")
    if pid is not None:
        rows = [p for p in rows if p["patient_id"] == pid]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)


@bp.post("/prior-authorizations/<paid>/step-therapy-trials")
@require("BillingSpecialist")
def create_trial(paid):
    pa = helpers.get_or_404(db.prior_authorizations, paid, "prior_auth")
    data = helpers.body()
    drug_name = helpers.require_str(data, "drug_name")
    outcome = helpers.require_enum(data, "outcome", OUTCOMES)
    row = {
        "prior_auth_id": paid,
        "drug_name": drug_name,
        "outcome": outcome,
    }
    db.stamp_new(row)
    db.step_therapy_trials[row["id"]] = row
    # Recompute satisfied_step_count and bump PA version (PRD 3.9).
    services.recompute_satisfied_steps(pa)
    db.touch(pa)
    return response.created(row)


@bp.get("/prior-authorizations/<paid>/step-therapy-trials")
@require("BillingSpecialist", "PracticeAdmin", "Provider")
def list_trials(paid):
    helpers.get_or_404(db.prior_authorizations, paid, "prior_auth")
    rows = [t for t in db.step_therapy_trials.values() if t["prior_auth_id"] == paid]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)


@bp.post("/prior-authorizations/<paid>/submit")
@require("BillingSpecialist")
def submit_pa(paid):
    pa = helpers.get_or_404(db.prior_authorizations, paid, "prior_auth")
    if pa["status"] not in ("DRAFT", "DENIED"):
        raise errors.bad_state("ERR_PA_BAD_STATE")
    if pa["satisfied_step_count"] < pa["required_step_count"]:
        raise errors.step_therapy_not_met()
    pa["status"] = "SUBMITTED"
    pa["submission_round"] += 1
    db.touch(pa)
    return response.ok(pa)


@bp.post("/prior-authorizations/<paid>/adjudicate")
@require("BillingSpecialist")
def adjudicate_pa(paid):
    pa = helpers.get_or_404(db.prior_authorizations, paid, "prior_auth")
    data = helpers.body()
    decision = helpers.require_enum(data, "decision", DECISIONS)
    if pa["status"] != "SUBMITTED":
        raise errors.bad_state("ERR_PA_BAD_STATE")
    pa["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    db.touch(pa)
    return response.ok(pa)
