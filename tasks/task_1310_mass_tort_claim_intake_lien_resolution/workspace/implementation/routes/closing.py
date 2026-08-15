"""Closing statement endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CLAIM_INVALID_STATE,
    ERR_NOT_FOUND,
)
from middleware import require_role
from response import success_envelope
from routes.helpers import (
    bump,
    get_pagination,
    new_id,
    paginate,
    resolve_claim,
    sort_by_created_at,
    utc_now_iso,
)

bp = Blueprint("closing", __name__)

CLOSING_READ_ROLES = (
    "ProgramAdministrator",
    "DisbursementApprover",
    "ClaimantRole",
)


@bp.route("/settlement-programs/<pid>/claims/<cid>/close", methods=["POST"])
def close_claim(pid, cid):
    user_id, role = require_role("ProgramAdministrator")
    prog, claim = resolve_claim(pid, cid)

    if claim["status"] != "DISBURSED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Claim must be DISBURSED to close", 409)

    claim["status"] = "CLOSED"
    bump(claim)

    # Create ClosingStatement snapshot (append-only, no updated_at/version)
    statement = {
        "id": new_id(),
        "created_at": utc_now_iso(),
        "claim_id": cid,
        "gross_award_cents": claim["gross_award_cents"],
        "total_lien_cents": claim["total_lien_cents"],
        "attorney_fee_cents": claim["attorney_fee_cents"],
        "net_award_cents": claim["net_award_cents"],
        "statement_body": _render_statement_body(claim, prog),
        "sealed_at": prog["current_utc"],
    }
    db.closing_statements[statement["id"]] = statement

    return success_envelope(claim, 200, "object")


def _render_statement_body(claim, prog):
    """Render the audit text for the closing statement."""
    return (
        "CLOSING STATEMENT\n"
        "Program: %s\n"
        "Claim: %s\n"
        "Gross Award: %d cents\n"
        "Total Liens: %d cents\n"
        "Attorney Fee: %d cents\n"
        "Net Award: %d cents\n"
        "Sealed at: %s\n"
        % (
            prog.get("tort_name", ""),
            claim.get("claim_number", ""),
            claim["gross_award_cents"],
            claim["total_lien_cents"],
            claim["attorney_fee_cents"],
            claim["net_award_cents"],
            prog["current_utc"],
        )
    )


@bp.route("/settlement-programs/<pid>/claims/<cid>/closing-statements", methods=["GET"])
def list_closing_statements(pid, cid):
    user_id, role = require_role(*CLOSING_READ_ROLES)
    prog, claim = resolve_claim(pid, cid)
    limit, offset = get_pagination()

    items = [s for s in db.closing_statements.values() if s["claim_id"] == cid]

    claim_filter = request.args.get("claim_id")
    if claim_filter:
        items = [s for s in items if s["claim_id"] == claim_filter]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)
