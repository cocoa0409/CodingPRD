"""Claim endpoints (PRD 3.7): first notice of loss, assignment, withdrawal,
submit-for-review, and reads."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_LOSS_DATE_OUT_OF_COVERAGE, ERR_LATE_NOTICE_OVER_30D,
    ERR_CLAIM_NOT_IN_REPORTED, ERR_ADJUSTER_NOT_ACTIVE,
    ERR_ADJUSTER_COUNTY_MISMATCH, ERR_ADJUSTER_SPECIES_MISMATCH,
    ERR_ADJUSTER_CAPACITY_FULL, ERR_POLICY_RESTRICTED,
    ERR_CLAIM_NOT_WITHDRAWABLE, ERR_CLAIM_NOT_IN_INSPECTED,
    ERR_NOT_ASSIGNED_ADJUSTER,
)
from middleware import require_roles
from response import success_object, success_list
from routes.common import (
    resolve_carrier, resolve_policy, resolve_unit, resolve_claim,
)
from serializers import claim_view
from services import core
from util import (
    get_json_body, reject_unknown_fields, require_string, require_int,
    require_datetime, optional_int, parse_pagination, paginate, sort_created,
    query_arg, dt,
)

bp = Blueprint("claims", __name__)

ALL_ROLES = ("PlatformAdmin", "Underwriter", "Policyholder", "Adjuster", "ClaimsApprover")

CREATE_FIELDS = {
    "coverage_unit_id", "loss_date", "percent_damage_estimate_pct",
    "appraisal_value_cents", "deceased_head_count",
}
ASSIGN_FIELDS = {"adjuster_id"}


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims", methods=["POST"])
@require_roles("Policyholder")
def create_claim(carrierId: str, policyId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    coverage_unit_id = require_string(body, "coverage_unit_id")
    loss_date = require_datetime(body, "loss_date")

    # Body reference: the coverage unit must exist beneath this policy.
    unit = db.coverage_units.get(coverage_unit_id)
    if unit is None or unit["policy_id"] != policy["id"]:
        raise_err(ERR_NOT_FOUND, f"CoverageUnit not found: {coverage_unit_id}")

    if policy["policy_kind"] == "CROP_HAIL":
        percent_damage = require_int(
            body, "percent_damage_estimate_pct", minimum=1, maximum=100)
        appraisal_value = None
        deceased_head_count = None
        claim_kind = "HAIL_DAMAGE"
    else:
        appraisal_value = require_int(body, "appraisal_value_cents", minimum=0)
        deceased_head_count = require_int(
            body, "deceased_head_count", minimum=1,
            maximum=unit["declared_head_count"])
        percent_damage = None
        claim_kind = "LIVESTOCK_MORTALITY"

    # State: the unit must currently be REPORTED.
    if unit["status"] != "REPORTED":
        raise_err(ERR_INVALID_STATE,
                  "A claim can only be opened against a unit in REPORTED status")

    # Temporal checks in fixed order (PRD 3.7).
    now = carrier["current_utc"]
    now_dt = dt(now)
    loss_dt = dt(loss_date)
    if not (dt(policy["effective_date"]) <= loss_dt < dt(policy["expiration_date"])):
        raise_err(ERR_LOSS_DATE_OUT_OF_COVERAGE,
                  "loss_date must fall within [effective_date, expiration_date)")
    if (now_dt - loss_dt) > timedelta(days=30):
        raise_err(ERR_LATE_NOTICE_OVER_30D,
                  "Notice of loss more than 30 days after the loss is non-payable")

    within_window, penalty = core.late_notice(claim_kind, now_dt, loss_dt)

    claim = db.stamp_new({
        "policy_id": policy["id"],
        "coverage_unit_id": unit["id"],
        "claim_kind": claim_kind,
        "loss_date": loss_date,
        "reported_at": now,
        "reported_within_window": within_window,
        "late_notification_penalty_pct": penalty,
        "percent_damage_estimate_pct": percent_damage,
        "appraisal_value_cents": appraisal_value,
        "deceased_head_count": deceased_head_count,
        "adjuster_id": None,
        "provisional_indemnity_cents": 0,
        "final_indemnity_cents": 0,
        "claim_state": "REPORTED",
        "doc_posture": "DOCS_PENDING",
    }, now)
    db.claims[claim["id"]] = claim

    unit["status"] = "UNDER_CLAIM"
    db.touch(unit, now)
    return success_object(claim_view(claim), 201)


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_claims(carrierId: str, policyId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    items = core.claims_of_policy(policy["id"])
    claim_state = query_arg("claim_state")
    if claim_state is not None:
        items = [c for c in items if c["claim_state"] == claim_state]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([claim_view(c) for c in page], limit, offset, total)


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims/<claimId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_claim(carrierId: str, policyId: str, claimId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    claim = resolve_claim(policy["id"], claimId)
    return success_object(claim_view(claim))


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims/<claimId>/assign-adjuster",
          methods=["POST"])
@require_roles("ClaimsApprover")
def assign_adjuster(carrierId: str, policyId: str, claimId: str,
                    _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    claim = resolve_claim(policy["id"], claimId)
    body = get_json_body()
    reject_unknown_fields(body, ASSIGN_FIELDS)
    adjuster_id = require_string(body, "adjuster_id")

    # Body reference: adjuster must exist under this carrier.
    adjuster = db.adjusters.get(adjuster_id)
    if adjuster is None or adjuster["carrier_id"] != carrier["id"]:
        raise_err(ERR_NOT_FOUND, f"Adjuster not found: {adjuster_id}")

    unit = db.coverage_units.get(claim["coverage_unit_id"])

    # Fixed check order (PRD 3.7).
    if claim["claim_state"] != "REPORTED":
        raise_err(ERR_CLAIM_NOT_IN_REPORTED,
                  "assign-adjuster requires claim_state REPORTED")
    if adjuster["status"] != "ACTIVE":
        raise_err(ERR_ADJUSTER_NOT_ACTIVE, "Adjuster.status != ACTIVE")
    if claim["claim_kind"] == "HAIL_DAMAGE":
        if unit is None or unit["county_code"] not in adjuster["county_codes"]:
            raise_err(ERR_ADJUSTER_COUNTY_MISMATCH,
                      "Adjuster is not licensed for the coverage unit's county")
    else:
        if unit is None or unit["species"] not in adjuster["species_qualified"]:
            raise_err(ERR_ADJUSTER_SPECIES_MISMATCH,
                      "Adjuster is not qualified for the coverage unit's species")
    if core.adjuster_open_claims(adjuster["id"]) >= adjuster["capacity_max_open_claims"]:
        raise_err(ERR_ADJUSTER_CAPACITY_FULL,
                  "Adjuster has reached capacity_max_open_claims")
    if core.derive_claims_posture(policy) != "OPEN":
        raise_err(ERR_POLICY_RESTRICTED,
                  "Policy claims_posture is RESTRICTED")

    now = carrier["current_utc"]
    claim["adjuster_id"] = adjuster["id"]
    claim["claim_state"] = "INSPECTION_SCHEDULED"
    db.touch(claim, now)
    return success_object(claim_view(claim))


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims/<claimId>/withdraw",
          methods=["POST"])
@require_roles("Policyholder")
def withdraw_claim(carrierId: str, policyId: str, claimId: str,
                   _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    claim = resolve_claim(policy["id"], claimId)
    body = get_json_body()
    reject_unknown_fields(body, set())

    if claim["claim_state"] not in ("REPORTED", "INSPECTION_SCHEDULED"):
        raise_err(ERR_CLAIM_NOT_WITHDRAWABLE,
                  "withdraw requires claim_state REPORTED or INSPECTION_SCHEDULED")

    now = carrier["current_utc"]
    claim["claim_state"] = "WITHDRAWN"
    db.touch(claim, now)
    core.release_unit(claim, now)
    return success_object(claim_view(claim))


@bp.route("/carriers/<carrierId>/policies/<policyId>/claims/<claimId>/submit-for-review",
          methods=["POST"])
@require_roles("Adjuster")
def submit_for_review(carrierId: str, policyId: str, claimId: str,
                      _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    claim = resolve_claim(policy["id"], claimId)
    body = get_json_body()
    reject_unknown_fields(body, set())

    if claim["claim_state"] != "INSPECTED":
        raise_err(ERR_CLAIM_NOT_IN_INSPECTED,
                  "submit-for-review requires claim_state INSPECTED")
    if _user_id != claim["adjuster_id"]:
        raise_err(ERR_NOT_ASSIGNED_ADJUSTER,
                  "Caller is not the claim's assigned adjuster")

    claim["claim_state"] = "UNDER_REVIEW"
    db.touch(claim, carrier["current_utc"])
    return success_object(claim_view(claim))
