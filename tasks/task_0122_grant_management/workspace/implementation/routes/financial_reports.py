"""FinancialReport endpoints (PRD §3.6)."""
from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success
from services import common as c
from services.award import recompute_federal_approved_expenditures
from services.financial_report import (
    DIRECT_COST_CATEGORIES,
    approved_direct_total,
    compute_indirect_cost,
    compute_reimbursable,
)

bp = Blueprint("financial_reports", __name__)

REPORT_BASES = {"INTERIM", "FINAL"}
READ_ROLES = ("FinanceOfficer", "AgencyOfficer", "Auditor")


def _serialize(rep):
    return c.serialize(rep)


def _load(rep_id):
    rep = db.financial_reports.get(rep_id)
    if rep is None:
        raise errors.not_found("Financial report not found.")
    return rep


def _validate_direct_cost_lines(body):
    lines = c.require_present(body, "direct_cost_lines")
    if not isinstance(lines, list):
        raise errors.invalid_request("direct_cost_lines must be an array.")
    normalized = []
    for entry in lines:
        if not isinstance(entry, dict):
            raise errors.invalid_request("Each direct_cost_lines entry must be an object.")
        category = entry.get("category")
        amt = entry.get("amount_cents")
        if not isinstance(category, str) or category not in DIRECT_COST_CATEGORIES:
            raise errors.invalid_request(
                "direct_cost_lines category must be one of %s." % sorted(DIRECT_COST_CATEGORIES)
            )
        if isinstance(amt, bool) or not isinstance(amt, int) or amt < 0:
            raise errors.invalid_request("direct_cost_lines amount_cents must be a non-negative integer.")
        normalized.append({"category": category, "amount_cents": amt})
    return normalized


@bp.route("/financial-reports", methods=["POST"])
@require_roles("FinanceOfficer")
def create_report(user_id, role):
    body = c.get_body()

    award_id = body.get("award_id")
    if award_id is None or not isinstance(award_id, str) or award_id == "":
        raise errors.invalid_request("award_id is required.")
    with db.LOCK:
        if award_id not in db.awards:
            raise errors.not_found("Award not found.")

        period_label = c.require_nonempty_string(body, "period_label")
        report_basis = c.require_enum(body, "report_basis", REPORT_BASES)
        direct_cost_lines = _validate_direct_cost_lines(body)
        disallowed_cents = c.optional_int(body, "disallowed_cents", 0, minimum=0)

        # priority 15: period_label unique per award among non-REJECTED reports.
        for r in db.financial_reports.values():
            if (r["award_id"] == award_id and r["status"] != "REJECTED"
                    and r["period_label"] == period_label):
                raise errors.duplicate("period_label already used for this award.")

        record = {
            "award_id": award_id,
            "period_label": period_label,
            "report_basis": report_basis,
            "direct_cost_lines": direct_cost_lines,
            "disallowed_cents": disallowed_cents,
            "approved_direct_cents": 0,
            "indirect_cost_cents": 0,
            "reimbursable_cents": 0,
            "certified_by_user_id": None,
            "status": "DRAFT",
        }
        db.stamp_create(record)
        db.financial_reports[record["id"]] = record
        return success(_serialize(record), status=201)


@bp.route("/financial-reports", methods=["GET"])
@require_roles(*READ_ROLES)
def list_reports(user_id, role):
    limit, offset = c.parse_pagination()
    award_id = request.args.get("award_id")
    status = request.args.get("status")
    with db.LOCK:
        records = list(db.financial_reports.values())
    if award_id is not None:
        records = [r for r in records if r["award_id"] == award_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pagination = c.paginate(records, limit, offset)
    return success([_serialize(r) for r in page], status=200, pagination=pagination)


@bp.route("/financial-reports/<rep_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_report(rep_id, user_id, role):
    with db.LOCK:
        return success(_serialize(_load(rep_id)), status=200)


@bp.route("/financial-reports/<rep_id>/certify", methods=["POST"])
@require_roles("FinanceOfficer")
def certify_report(rep_id, user_id, role):
    with db.LOCK:
        rep = _load(rep_id)
        # priority 4: report must be DRAFT.
        if rep["status"] != "DRAFT":
            raise errors.invalid_state("Only a DRAFT report may be certified.")
        award = db.awards.get(rep["award_id"])
        # Parent award must be ACTIVE or PENDING_CLOSEOUT (PRD §3.6 state precond).
        if award is None or award["status"] not in ("ACTIVE", "PENDING_CLOSEOUT"):
            raise errors.invalid_state("Parent award must be ACTIVE or PENDING_CLOSEOUT.")
        # priority 7: segregation of duties — certifier must not be any drawdown
        # initiator on this award.
        for dd in db.drawdowns.values():
            if dd["award_id"] == rep["award_id"] and dd["initiated_by_user_id"] == user_id:
                raise errors.segregation_of_duties()
        rep["status"] = "SUBMITTED"
        rep["certified_by_user_id"] = user_id
        db.touch(rep)
        return success(_serialize(rep), status=200)


@bp.route("/financial-reports/<rep_id>/accept", methods=["POST"])
@require_roles("AgencyOfficer")
def accept_report(rep_id, user_id, role):
    with db.LOCK:
        rep = _load(rep_id)
        if rep["status"] != "SUBMITTED":
            raise errors.invalid_state("Only a SUBMITTED report may be accepted.")
        award = db.awards.get(rep["award_id"])

        # Compute the three derived figures (PRD §3.6).
        approved = approved_direct_total(rep)
        rep["status"] = "ACCEPTED"
        rep["approved_direct_cents"] = approved
        rep["indirect_cost_cents"] = compute_indirect_cost(rep, award)
        rep["reimbursable_cents"] = compute_reimbursable(rep, award, approved)
        db.touch(rep)

        # Recompute the award's cumulative approved-expenditure ledger and bump
        # the award's version (PRD §3.6).
        recompute_federal_approved_expenditures(award)
        db.touch(award)

        return success(_serialize(rep), status=200)


@bp.route("/financial-reports/<rep_id>/reject", methods=["POST"])
@require_roles("AgencyOfficer")
def reject_report(rep_id, user_id, role):
    with db.LOCK:
        rep = _load(rep_id)
        if rep["status"] != "SUBMITTED":
            raise errors.invalid_state("Only a SUBMITTED report may be rejected.")
        rep["status"] = "REJECTED"
        db.touch(rep)
        return success(_serialize(rep), status=200)


@bp.route("/financial-reports/<rep_id>/revise", methods=["POST"])
@require_roles("FinanceOfficer")
def revise_report(rep_id, user_id, role):
    with db.LOCK:
        rep = _load(rep_id)
        if rep["status"] != "REJECTED":
            raise errors.invalid_state("Only a REJECTED report may be revised.")
        rep["status"] = "DRAFT"
        db.touch(rep)
        return success(_serialize(rep), status=200)
