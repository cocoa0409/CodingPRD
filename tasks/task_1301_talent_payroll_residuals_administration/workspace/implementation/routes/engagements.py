"""Engagement endpoints: create (with amendment OCC), submit/approve/reject."""

from flask import Blueprint, request

import db
from calculations import find_tier
from errors import (
    ApiError, ERR_ENGAGEMENT_INVALID_STATE, ERR_AGREEMENT_NOT_RATIFIED,
    ERR_PERFORMER_DOUBLE_BOOKED, ERR_TIER_NOT_FOUND, ERR_LOAN_OUT_FIELDS,
    ERR_STALE_VERSION, ERR_VALIDATION,
)
from helpers import (
    new_id, now_timestamp, parse_date, require_enum, require_int,
    require_string, optional_string, err_validation, temporal_error,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, list_response
from serializers import serialize, get_or_404, bump_version

bp = Blueprint("engagements", __name__)

PAYEE_TYPES = {"DIRECT", "LOAN_OUT"}


@bp.post("/payroll/engagements")
def create_engagement():
    require_roles({"ProductionAccountant"})
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object")

    production_id = require_string(body, "production_id")
    union_agreement_id = require_string(body, "union_agreement_id")
    performer_id = require_string(body, "performer_id")
    tier_code = require_string(body, "tier_code")
    payee_type = require_enum(body, "payee_type", PAYEE_TYPES)
    loan_out_legal_name = optional_string(body, "loan_out_legal_name")
    loan_out_tax_id = optional_string(body, "loan_out_tax_id")
    weekly_guarantee_cents = require_int(body, "weekly_guarantee_cents", minimum=0)
    guaranteed_days = require_int(body, "guaranteed_days", minimum=0)
    start_date_raw = require_string(body, "start_date")
    end_date_raw = require_string(body, "end_date")
    supersedes_engagement_id = optional_string(body, "supersedes_engagement_id")

    # ---- priority 3: FK existence, left to right ----
    get_or_404(db.productions, production_id, "Production")
    agreement = get_or_404(db.union_agreements, union_agreement_id, "UnionAgreement")
    get_or_404(db.performers, performer_id, "Performer")
    supersede_target = None
    if supersedes_engagement_id is not None:
        supersede_target = get_or_404(
            db.engagements, supersedes_engagement_id, "Engagement"
        )

    # ---- priority 6 (temporal): end_date >= start_date ----
    start_date = parse_date(start_date_raw, "start_date")
    end_date = parse_date(end_date_raw, "end_date")
    if end_date < start_date:
        raise temporal_error("end_date must be on or after start_date")

    # ---- priority 8 (business-referential): tier lookup ----
    if find_tier(agreement, tier_code) is None:
        raise ApiError(
            ERR_TIER_NOT_FOUND,
            f"tier_code '{tier_code}' absent from the agreement's rate_tiers",
            422,
        )

    # ---- priority 8: loan-out conditional fields ----
    if payee_type == "LOAN_OUT":
        if loan_out_legal_name is None or loan_out_tax_id is None:
            raise ApiError(
                ERR_LOAN_OUT_FIELDS,
                "payee_type LOAN_OUT requires loan_out_legal_name and loan_out_tax_id",
                422,
            )
    else:  # DIRECT
        if loan_out_legal_name is not None or loan_out_tax_id is not None:
            raise ApiError(
                ERR_LOAN_OUT_FIELDS,
                "payee_type DIRECT forbids loan_out_legal_name and loan_out_tax_id",
                422,
            )

    # ---- amendment handling: target must be ACTIVE; OCC check ----
    if supersede_target is not None:
        if "expected_engagement_version" not in body or body["expected_engagement_version"] is None:
            raise ApiError(
                ERR_VALIDATION,
                "expected_engagement_version is required when supersedes_engagement_id is set",
                400,
            )
        expected = body["expected_engagement_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err_validation("expected_engagement_version must be an integer")
        # Target must currently be ACTIVE for amendment. No catalogued
        # state-gate error covers the create path, so this falls under the
        # generic request-shape rule (ERR_VALIDATION, priority 28), which
        # still fires before the OCC check (priority 29).
        if supersede_target["status"] != "ACTIVE":
            raise ApiError(
                ERR_VALIDATION,
                "Supersede target engagement is not ACTIVE",
                400,
            )
        # OCC (priority 12 in PRD ordering; only the amendment path carries it).
        if expected != supersede_target["version"]:
            raise ApiError(
                ERR_STALE_VERSION,
                "expected_engagement_version does not match the target's current version",
                412,
            )

    now = now_timestamp()
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "production_id": production_id,
        "union_agreement_id": union_agreement_id,
        "performer_id": performer_id,
        "tier_code": tier_code,
        "payee_type": payee_type,
        "loan_out_legal_name": loan_out_legal_name,
        "loan_out_tax_id": loan_out_tax_id,
        "weekly_guarantee_cents": weekly_guarantee_cents,
        "guaranteed_days": guaranteed_days,
        "start_date": start_date_raw,
        "end_date": end_date_raw,
        "supersedes_engagement_id": supersedes_engagement_id,
        "accrued_penalty_cents": 0,
        "accrued_adjustment_cents": 0,
        "ytd_paid_cents": 0,
        "status": "DRAFT",
    }
    db.engagements[record["id"]] = record

    # Create-time side effect: amendment target ACTIVE -> AMENDMENT_PENDING, version bump.
    if supersede_target is not None:
        supersede_target["status"] = "AMENDMENT_PENDING"
        bump_version(supersede_target)

    return success_object(serialize(record), 201)


@bp.get("/payroll/engagements")
def list_engagements():
    require_roles(ALL_ROLES)
    items = list(db.engagements.values())
    production_id = request.args.get("production_id")
    if production_id is not None:
        items = [e for e in items if e["production_id"] == production_id]
    performer_id = request.args.get("performer_id")
    if performer_id is not None:
        items = [e for e in items if e["performer_id"] == performer_id]
    union_agreement_id = request.args.get("union_agreement_id")
    if union_agreement_id is not None:
        items = [e for e in items if e["union_agreement_id"] == union_agreement_id]
    supersedes_engagement_id = request.args.get("supersedes_engagement_id")
    if supersedes_engagement_id is not None:
        items = [e for e in items if e["supersedes_engagement_id"] == supersedes_engagement_id]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return list_response([serialize(e) for e in items], request.args)


@bp.get("/payroll/engagements/<engagement_id>")
def get_engagement(engagement_id):
    require_roles(ALL_ROLES)
    engagement = get_or_404(db.engagements, engagement_id, "Engagement")
    return success_object(serialize(engagement), 200)


@bp.post("/payroll/engagements/<engagement_id>/submit")
def submit_engagement(engagement_id):
    require_roles({"ProductionAccountant"})
    engagement = get_or_404(db.engagements, engagement_id, "Engagement")

    if engagement["status"] != "DRAFT":
        raise ApiError(
            ERR_ENGAGEMENT_INVALID_STATE,
            "Submit requires DRAFT status",
            409,
        )

    agreement = get_or_404(
        db.union_agreements, engagement["union_agreement_id"], "UnionAgreement"
    )
    if agreement["status"] != "RATIFIED":
        raise ApiError(
            ERR_AGREEMENT_NOT_RATIFIED,
            "Engagement submit requires the referenced UnionAgreement to be RATIFIED",
            409,
        )

    # Performer double-booking: closed-interval overlap against engagements in
    # {PENDING_APPROVAL, ACTIVE, AMENDMENT_PENDING}, excluding the supersede target.
    this_start = parse_date(engagement["start_date"], "start_date")
    this_end = parse_date(engagement["end_date"], "end_date")
    for other in db.engagements.values():
        if other["id"] == engagement_id:
            continue
        if other["performer_id"] != engagement["performer_id"]:
            continue
        if other["status"] not in {"PENDING_APPROVAL", "ACTIVE", "AMENDMENT_PENDING"}:
            continue
        if engagement["supersedes_engagement_id"] is not None and other["id"] == engagement["supersedes_engagement_id"]:
            continue
        other_start = parse_date(other["start_date"], "start_date")
        other_end = parse_date(other["end_date"], "end_date")
        if other_start <= this_end and this_start <= other_end:
            raise ApiError(
                ERR_PERFORMER_DOUBLE_BOOKED,
                "Performer already engaged on an overlapping engagement",
                409,
            )

    engagement["status"] = "PENDING_APPROVAL"
    bump_version(engagement)
    return success_object(serialize(engagement), 200)


@bp.post("/payroll/engagements/<engagement_id>/approve")
def approve_engagement(engagement_id):
    require_roles({"PayrollSupervisor"})
    engagement = get_or_404(db.engagements, engagement_id, "Engagement")

    if engagement["status"] != "PENDING_APPROVAL":
        raise ApiError(
            ERR_ENGAGEMENT_INVALID_STATE,
            "Approve requires PENDING_APPROVAL status",
            409,
        )

    production = get_or_404(db.productions, engagement["production_id"], "Production")
    if production["status"] not in {"PRE_PRODUCTION", "SHOOTING"}:
        raise ApiError(
            ERR_ENGAGEMENT_INVALID_STATE,
            "Engagement cannot be approved into a wrapped or archived production",
            409,
        )

    engagement["status"] = "ACTIVE"
    bump_version(engagement)

    # Amendment approval supersedes the target: AMENDMENT_PENDING -> SUPERSEDED.
    if engagement["supersedes_engagement_id"] is not None:
        target = db.engagements.get(engagement["supersedes_engagement_id"])
        if target is not None:
            target["status"] = "SUPERSEDED"
            bump_version(target)

    return success_object(serialize(engagement), 200)


@bp.post("/payroll/engagements/<engagement_id>/reject")
def reject_engagement(engagement_id):
    require_roles({"PayrollSupervisor"})
    engagement = get_or_404(db.engagements, engagement_id, "Engagement")

    if engagement["status"] != "PENDING_APPROVAL":
        raise ApiError(
            ERR_ENGAGEMENT_INVALID_STATE,
            "Reject requires PENDING_APPROVAL status",
            409,
        )

    engagement["status"] = "DRAFT"
    bump_version(engagement)

    # Rejected amendment restores target: AMENDMENT_PENDING -> ACTIVE.
    if engagement["supersedes_engagement_id"] is not None:
        target = db.engagements.get(engagement["supersedes_engagement_id"])
        if target is not None:
            target["status"] = "ACTIVE"
            bump_version(target)

    return success_object(serialize(engagement), 200)
