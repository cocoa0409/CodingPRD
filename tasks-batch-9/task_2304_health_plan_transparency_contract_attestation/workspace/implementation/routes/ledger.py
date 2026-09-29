"""PenaltyLedgerEntry endpoints (PRD 3.9). The ledger is append-only."""

from flask import Blueprint

import db
import domain
import guards
import response

bp = Blueprint("ledger", __name__)

READ_ROLES = ("PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor")


@bp.route("/compliance/penalty-ledger-entries/<row_id>", methods=["GET"])
def get_entry(row_id):
    guards.authorize(*READ_ROLES)
    return response.object_response(
        response.public(guards.fetch("ledger_entry", row_id))
    )


@bp.route("/compliance/penalty-ledger-entries", methods=["GET"])
def list_entries():
    guards.authorize(*READ_ROLES)
    limit, offset = guards.pagination()
    guards.filter_fk("plan_year", "plan_year_id")
    guards.filter_fk("ledger_entry", "reverses_entry_id")
    guards.filter_fk("remediation_plan", "remediation_plan_id")
    rows = guards.apply_filters(db.ordered(db.ledger_entries), [
        ("plan_year_id", "plan_year_id", None),
        ("entry_type", "entry_type", None),
        ("deficiency_type", "deficiency_type", None),
        ("reverses_entry_id", "reverses_entry_id", None),
        ("remediation_plan_id", "remediation_plan_id", None),
    ])
    page, total = guards.paginate(rows, limit, offset)
    return response.array_response(
        [response.public(r) for r in page], limit, offset, total
    )


@bp.route("/compliance/penalty-ledger-entries/<row_id>/reverse", methods=["POST"])
def reverse_entry(row_id):
    user_id, _role = guards.authorize("ExternalAuditor")
    entry = guards.fetch("ledger_entry", row_id)
    body = guards.read_body()
    reason = guards.field(body, "reason", "string")
    plan_year = db.plan_years.get(entry["plan_year_id"])
    # Reversal is one of the five operations permitted while frozen (PRD 2.8).
    # Ladder step 34 — only a plain accrual is reversible.
    guards.require(
        entry["entry_type"] == "ACCRUAL" and entry.get("reverses_entry_id") is None,
        "ERR_NOT_REVERSIBLE_ENTRY",
        "Only an ACCRUAL entry that is not itself a reversal may be reversed.",
    )
    # Ladder step 35 — at most one reversal per accrual.
    guards.require(
        not domain.is_reversed(entry["id"]),
        "ERR_ENTRY_ALREADY_REVERSED",
        "This accrual has already been reversed.",
    )
    reversal = domain.append_entry(
        plan_year,
        "ABATEMENT",
        entry["deficiency_type"],
        -entry["signed_amount_cents"],
        0,
        0,
        1.0,
        None,
        reason,
        posted_by_user_id=user_id,
        reverses_entry_id=entry["id"],
    )
    if plan_year is not None:
        with db.txn(plan_year):
            domain.recompute_exposure(plan_year)
    # An action on an existing resource answers 200 (PRD 4).
    return response.object_response(response.public(reversal))
