"""GrievanceCase endpoints."""

from flask import Blueprint, request

import db
from calculations import (
    jurisdiction_tax_cents, phw_contribution_cents,
    recompute_engagement_accrued_adjustment,
)
from errors import (
    ApiError, ERR_RESOURCE_INVALID_STATE, ERR_NO_OPEN_BATCH, ERR_VALIDATION,
)
from helpers import (
    new_id, now_timestamp, require_enum, require_int, require_string,
    optional_string, err_validation,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, list_response
from serializers import serialize, get_or_404, bump_version

bp = Blueprint("grievance_cases", __name__)

CATEGORIES = {"UNDERPAYMENT", "PENALTY_OMITTED", "RESIDUAL_MISCALC", "PHW_SHORTAGE"}


@bp.post("/payroll/grievance-cases")
def create_grievance_case():
    user_id, _role = require_roles({"UnionAuditor"})
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object")

    engagement_id = require_string(body, "engagement_id")
    pay_line_id = optional_string(body, "pay_line_id")
    category = require_enum(body, "category", CATEGORIES)
    claimed_amount_cents = require_int(body, "claimed_amount_cents", minimum=0)
    description = require_string(body, "description")

    # FK existence (priority 3), left to right
    get_or_404(db.engagements, engagement_id, "Engagement")
    if pay_line_id is not None:
        get_or_404(db.pay_lines, pay_line_id, "PayLine")

    now = now_timestamp()
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "engagement_id": engagement_id,
        "pay_line_id": pay_line_id,
        "filed_by_user_id": user_id,
        "category": category,
        "claimed_amount_cents": claimed_amount_cents,
        "awarded_amount_cents": 0,
        "description": description,
        "status": "FILED",
    }
    db.grievance_cases[record["id"]] = record
    return success_object(serialize(record), 201)


@bp.get("/payroll/grievance-cases")
def list_grievance_cases():
    require_roles(ALL_ROLES)
    items = list(db.grievance_cases.values())
    engagement_id = request.args.get("engagement_id")
    if engagement_id is not None:
        items = [g for g in items if g["engagement_id"] == engagement_id]
    pay_line_id = request.args.get("pay_line_id")
    if pay_line_id is not None:
        items = [g for g in items if g["pay_line_id"] == pay_line_id]
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    return list_response([serialize(g) for g in items], request.args)


@bp.get("/payroll/grievance-cases/<case_id>")
def get_grievance_case(case_id):
    require_roles(ALL_ROLES)
    case = get_or_404(db.grievance_cases, case_id, "GrievanceCase")
    return success_object(serialize(case), 200)


@bp.post("/payroll/grievance-cases/<case_id>/respond")
def respond_grievance_case(case_id):
    require_roles({"PayrollClerk"})
    case = get_or_404(db.grievance_cases, case_id, "GrievanceCase")

    if case["status"] != "FILED":
        raise ApiError(
            ERR_RESOURCE_INVALID_STATE,
            "Respond requires status FILED",
            409,
        )

    body = request.get_json(silent=True)
    response_note = None
    if isinstance(body, dict):
        response_note = body.get("response_note")
    if not isinstance(response_note, str) or response_note == "":
        raise ApiError(ERR_VALIDATION, "response_note is required", 400)

    case["status"] = "UNDER_REVIEW"
    bump_version(case)
    return success_object(serialize(case), 200)


@bp.post("/payroll/grievance-cases/<case_id>/escalate")
def escalate_grievance_case(case_id):
    require_roles({"UnionAuditor"})
    case = get_or_404(db.grievance_cases, case_id, "GrievanceCase")

    if case["status"] != "UNDER_REVIEW":
        raise ApiError(
            ERR_RESOURCE_INVALID_STATE,
            "Escalate requires status UNDER_REVIEW",
            409,
        )

    case["status"] = "ESCALATED"
    bump_version(case)
    return success_object(serialize(case), 200)


@bp.post("/payroll/grievance-cases/<case_id>/resolve")
def resolve_grievance_case(case_id):
    require_roles({"PayrollSupervisor"})
    case = get_or_404(db.grievance_cases, case_id, "GrievanceCase")

    if case["status"] not in {"UNDER_REVIEW", "ESCALATED"}:
        raise ApiError(
            ERR_RESOURCE_INVALID_STATE,
            "Resolve requires status UNDER_REVIEW or ESCALATED",
            409,
        )

    body = request.get_json(silent=True)
    awarded = None
    if isinstance(body, dict):
        awarded = body.get("awarded_amount_cents")
    if awarded is None:
        raise ApiError(ERR_VALIDATION, "awarded_amount_cents is required", 400)
    if isinstance(awarded, bool) or not isinstance(awarded, int) or awarded < 0:
        raise ApiError(ERR_VALIDATION, "awarded_amount_cents must be an integer >= 0", 400)

    # Positive award requires exactly one OPEN batch
    open_batches = [b for b in db.pay_batches.values() if b["status"] == "OPEN"]
    if awarded > 0 and len(open_batches) != 1:
        raise ApiError(
            ERR_NO_OPEN_BATCH,
            "Grievance resolve with a positive award requires exactly one OPEN pay batch",
            422,
        )

    case["awarded_amount_cents"] = awarded
    case["status"] = "RESOLVED"
    bump_version(case)

    if awarded > 0:
        batch = open_batches[0]
        engagement = get_or_404(db.engagements, case["engagement_id"], "Engagement")
        agreement = get_or_404(
            db.union_agreements, engagement["union_agreement_id"], "UnionAgreement"
        )
        production = get_or_404(db.productions, engagement["production_id"], "Production")
        performer = get_or_404(db.performers, engagement["performer_id"], "Performer")

        gross = awarded
        tax = jurisdiction_tax_cents(
            gross, engagement, production, performer, "GRIEVANCE_ADJUSTMENT"
        )
        phw = phw_contribution_cents(gross, agreement)
        # GRIEVANCE_ADJUSTMENT lines are garnishment-exempt regardless of payee type
        garnished = 0
        net = gross - tax - garnished

        now = now_timestamp()
        line = {
            "id": new_id(),
            "created_at": now,
            "pay_batch_id": batch["id"],
            "engagement_id": engagement["id"],
            "source_type": "GRIEVANCE_ADJUSTMENT",
            "source_id": case["id"],
            "gross_cents": gross,
            "jurisdiction_code": performer["tax_residency_state"],
            "tax_cents": tax,
            "garnished_cents": garnished,
            "phw_cents": phw,
            "net_cents": net,
            "status": "UNPAID",
            "_sort_date": case["created_at"][:10],
            "_performer_id": performer["id"],
            "_exempt": True,
        }
        db.pay_lines[line["id"]] = line

        recompute_engagement_accrued_adjustment(engagement)

    return success_object(serialize(case), 200)
