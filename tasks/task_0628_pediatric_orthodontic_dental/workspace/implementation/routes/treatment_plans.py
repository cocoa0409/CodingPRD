"""TreatmentPlan and TreatmentPhase endpoints + plan lifecycle (PRD §3.3-§3.5)."""

from flask import Blueprint, request

import errors
from db import db, lock
from helpers import (
    get_json_body, require_str, require_enum, require_int, stamp_new,
    parse_pagination, sort_and_paginate, touch,
)
from lookups import get_or_404, fk_or_404, require_guardian_owns_plan
from middleware import require_roles
from response import success, list_success
from serializers import public, public_list
from clock import clock
from services.domain import (
    pin_plan_fees, recompute_family_discount, contract_for_plan,
)

bp = Blueprint("treatment_plans", __name__)


def _provider_owns(plan_or_none):
    """Orthodontist ownership: X-User-ID == provider_user_id of a Provider.

    Plans/phases/growth records do not carry a provider FK in this scaffold, so
    Orthodontist actions are role-gated only (any Orthodontist may act). This
    helper is a placeholder kept for symmetry; no plan-level provider ownership
    is defined by the PRD."""
    return True


# -----------------------------------------------------------------------------
# TreatmentPlan CRUD
# -----------------------------------------------------------------------------

@bp.post("/treatment-plans")
@require_roles("Orthodontist", "ClinicAdmin")
def create_treatment_plan():
    body = get_json_body()
    patient_id = require_str(body, "patient_id")
    modality = require_enum(body, "modality", {"BRACES", "INVISALIGN"})
    policy_id = body.get("policy_id")
    if policy_id is not None and not isinstance(policy_id, str):
        raise errors.invalid_request("policy_id must be a string")
    interval = body.get("planned_visit_interval_weeks")
    if interval is None:
        interval = 6
    else:
        interval = require_int(body, "planned_visit_interval_weeks", minimum=1)
    with lock:
        fk_or_404(db.patients, patient_id)
        if policy_id is not None:
            fk_or_404(db.insurance_policies, policy_id)
        rec = {
            "patient_id": patient_id,
            "policy_id": policy_id,
            "modality": modality,
            "planned_visit_interval_weeks": interval,
            "gross_fee_cents": None,
            "discount_pct_applied": None,
            "net_fee_cents": None,
            "estimated_insurance_benefit_cents": None,
            "estimated_patient_responsibility_cents": None,
            "status": "DRAFT",
        }
        stamp_new(rec)
        db.treatment_plans[rec["id"]] = rec
        return success(public(rec), 201)


@bp.get("/treatment-plans/<plan_id>")
@require_roles("Orthodontist", "ClinicAdmin", "BillingSpecialist", "Guardian")
def get_treatment_plan(plan_id):
    with lock:
        rec = get_or_404(db.treatment_plans, plan_id)
        require_guardian_owns_plan(rec)
        return success(public(rec), 200)


@bp.get("/treatment-plans")
@require_roles("Orthodontist", "ClinicAdmin", "BillingSpecialist", "Guardian")
def list_treatment_plans():
    from flask import g
    from lookups import family_of_patient, guardian_owns_family
    with lock:
        limit, offset = parse_pagination()
        patient_id = request.args.get("patient_id")
        policy_id = request.args.get("policy_id")
        records = list(db.treatment_plans.values())
        if patient_id is not None:
            records = [r for r in records if r["patient_id"] == patient_id]
        if policy_id is not None:
            records = [r for r in records if r.get("policy_id") == policy_id]
        if g.user_role == "Guardian":
            records = [
                r for r in records
                if guardian_owns_family(family_of_patient(db.patients.get(r["patient_id"])))
            ]
        page, total = sort_and_paginate(records, limit, offset)
        return list_success(public_list(page), limit, offset, total, 200)


# -----------------------------------------------------------------------------
# Plan lifecycle transitions
# -----------------------------------------------------------------------------

@bp.post("/treatment-plans/<plan_id>/propose")
@require_roles("Orthodontist")
def propose_plan(plan_id):
    with lock:
        plan = get_or_404(db.treatment_plans, plan_id)
        if plan["status"] != "DRAFT":
            raise errors.invalid_state()
        has_phase = any(p["plan_id"] == plan_id for p in db.treatment_phases.values())
        if not has_phase:
            raise errors.no_phases()
        plan["status"] = "PROPOSED"
        touch(plan)
        return success(public(plan), 200)


@bp.post("/treatment-plans/<plan_id>/revise")
@require_roles("Orthodontist")
def revise_plan(plan_id):
    with lock:
        plan = get_or_404(db.treatment_plans, plan_id)
        if plan["status"] != "PROPOSED":
            raise errors.invalid_state()
        plan["status"] = "DRAFT"
        touch(plan)
        return success(public(plan), 200)


@bp.post("/treatment-plans/<plan_id>/activate")
@require_roles("Guardian")
def activate_plan(plan_id):
    with lock:
        plan = get_or_404(db.treatment_plans, plan_id)
        require_guardian_owns_plan(plan)
        if plan["status"] != "PROPOSED":
            raise errors.invalid_state()
        pat = db.patients.get(plan["patient_id"])
        if not pat or not pat.get("records_complete"):
            raise errors.records_incomplete()
        # Pin computed fees (order fixed inside pin_plan_fees), counting this
        # plan as in-treatment for the discount tier.
        plan["status"] = "ACTIVE"
        pin_plan_fees(plan)
        touch(plan)
        recompute_family_discount(pat["family_account_id"])
        return success(public(plan), 200)


@bp.post("/treatment-plans/<plan_id>/debond")
@require_roles("Orthodontist")
def debond_plan(plan_id):
    body = get_json_body()
    retainer_type = body.get("retainer_type")
    with lock:
        plan = get_or_404(db.treatment_plans, plan_id)
        if plan["status"] != "ACTIVE":
            raise errors.invalid_state()
        # Requires a completed DEBOND appointment OR an inline retainer_type.
        has_debond_appt = any(
            a.get("plan_id") == plan_id
            and a["visit_type"] == "DEBOND"
            and a["status"] == "COMPLETED"
            for a in db.appointments.values()
        )
        if not has_debond_appt and retainer_type is None:
            raise errors.invalid_request(
                "debond requires a completed DEBOND appointment or a retainer_type")
        if retainer_type is None:
            retainer_type = "HAWLEY"
        elif retainer_type not in {"HAWLEY", "CLEAR", "FIXED"}:
            raise errors.invalid_request("retainer_type must be HAWLEY|CLEAR|FIXED")
        plan["status"] = "RETENTION"
        # Issue a Retainer (ISSUED) with issued_at = clock-now.
        from clock import format_iso8601_ms
        retainer = {
            "plan_id": plan_id,
            "retainer_type": retainer_type,
            "issued_at": format_iso8601_ms(clock.now()),
            "status": "ISSUED",
        }
        stamp_new(retainer)
        db.retainers[retainer["id"]] = retainer
        touch(plan)
        pat = db.patients.get(plan["patient_id"])
        if pat:
            recompute_family_discount(pat["family_account_id"])
        return success(public(plan), 200)


@bp.post("/treatment-plans/<plan_id>/complete")
@require_roles("Orthodontist")
def complete_plan(plan_id):
    with lock:
        plan = get_or_404(db.treatment_plans, plan_id)
        if plan["status"] != "RETENTION":
            raise errors.invalid_state()
        plan["status"] = "COMPLETED"
        touch(plan)
        # Close the owning contract (lifecycle axis 2).
        contract = contract_for_plan(plan_id)
        if contract is not None and contract["lifecycle_status"] != "CLOSED":
            contract["lifecycle_status"] = "CLOSED"
            touch(contract)
        pat = db.patients.get(plan["patient_id"])
        if pat:
            recompute_family_discount(pat["family_account_id"])
        return success(public(plan), 200)


@bp.post("/treatment-plans/<plan_id>/cancel")
@require_roles("Orthodontist")
def cancel_plan(plan_id):
    with lock:
        plan = get_or_404(db.treatment_plans, plan_id)
        if plan["status"] not in ("DRAFT", "PROPOSED"):
            raise errors.invalid_state()
        plan["status"] = "CANCELLED"
        touch(plan)
        return success(public(plan), 200)


# -----------------------------------------------------------------------------
# TreatmentPhase
# -----------------------------------------------------------------------------

@bp.post("/treatment-phases")
@require_roles("Orthodontist", "ClinicAdmin")
def create_treatment_phase():
    body = get_json_body()
    plan_id = require_str(body, "plan_id")
    sequence_no = require_int(body, "sequence_no", minimum=1)
    label = require_str(body, "label")
    phase_fee_cents = require_int(body, "phase_fee_cents", non_negative=True)
    with lock:
        fk_or_404(db.treatment_plans, plan_id)
        rec = {
            "plan_id": plan_id,
            "sequence_no": sequence_no,
            "label": label,
            "phase_fee_cents": phase_fee_cents,
        }
        stamp_new(rec)
        db.treatment_phases[rec["id"]] = rec
        return success(public(rec), 201)


@bp.get("/treatment-phases/<phase_id>")
@require_roles("Orthodontist", "ClinicAdmin", "BillingSpecialist")
def get_treatment_phase(phase_id):
    with lock:
        rec = get_or_404(db.treatment_phases, phase_id)
        return success(public(rec), 200)


@bp.get("/treatment-phases")
@require_roles("Orthodontist", "ClinicAdmin", "BillingSpecialist")
def list_treatment_phases():
    with lock:
        limit, offset = parse_pagination()
        plan_id = request.args.get("plan_id")
        records = list(db.treatment_phases.values())
        if plan_id is not None:
            records = [r for r in records if r["plan_id"] == plan_id]
        page, total = sort_and_paginate(records, limit, offset)
        return list_success(public_list(page), limit, offset, total, 200)
