"""InsurancePolicy endpoints (PRD §3.6)."""

from flask import Blueprint, request

import errors
from db import db, lock
from helpers import (
    get_json_body, require_str, require_bool, require_int, require_number,
    stamp_new, parse_pagination, sort_and_paginate, touch,
)
from lookups import get_or_404, fk_or_404
from middleware import require_roles
from response import success, list_success
from serializers import public, public_list

bp = Blueprint("insurance_policies", __name__)


@bp.post("/insurance-policies")
@require_roles("BillingSpecialist", "ClinicAdmin")
def create_insurance_policy():
    body = get_json_body()
    patient_id = require_str(body, "patient_id")
    carrier_name = require_str(body, "carrier_name")
    ortho_rider = require_bool(body, "ortho_rider")
    coverage_pct = require_number(body, "ortho_coverage_pct")
    lifetime_max = require_int(body, "lifetime_max_cents", non_negative=True)
    # Shape passes; semantic range check (PRD §2.5): coverage_pct in [0, 1].
    if coverage_pct < 0 or coverage_pct > 1:
        raise errors.validation("ortho_coverage_pct must be within [0, 1]")
    with lock:
        fk_or_404(db.patients, patient_id)
        rec = {
            "patient_id": patient_id,
            "carrier_name": carrier_name,
            "ortho_rider": ortho_rider,
            "ortho_coverage_pct": coverage_pct,
            "lifetime_max_cents": lifetime_max,
            "remaining_max_cents": lifetime_max,
            "status": "ACTIVE",
        }
        stamp_new(rec)
        db.insurance_policies[rec["id"]] = rec
        return success(public(rec), 201)


@bp.get("/insurance-policies/<policy_id>")
@require_roles("BillingSpecialist", "ClinicAdmin")
def get_insurance_policy(policy_id):
    with lock:
        rec = get_or_404(db.insurance_policies, policy_id)
        return success(public(rec), 200)


@bp.get("/insurance-policies")
@require_roles("BillingSpecialist", "ClinicAdmin")
def list_insurance_policies():
    with lock:
        limit, offset = parse_pagination()
        patient_id = request.args.get("patient_id")
        records = list(db.insurance_policies.values())
        if patient_id is not None:
            records = [r for r in records if r["patient_id"] == patient_id]
        page, total = sort_and_paginate(records, limit, offset)
        return list_success(public_list(page), limit, offset, total, 200)


@bp.post("/insurance-policies/<policy_id>/terminate")
@require_roles("BillingSpecialist")
def terminate_insurance_policy(policy_id):
    with lock:
        rec = get_or_404(db.insurance_policies, policy_id)
        if rec["status"] != "ACTIVE":
            raise errors.invalid_state()
        # Refused while any claim on this policy is APPROVED (PRD §3.6).
        has_approved = any(
            c["status"] == "APPROVED" for c in db.insurance_claims.values()
            if c["policy_id"] == policy_id
        )
        if has_approved:
            raise errors.policy_has_open_claims()
        rec["status"] = "TERMINATED"
        touch(rec)
        return success(public(rec), 200)
