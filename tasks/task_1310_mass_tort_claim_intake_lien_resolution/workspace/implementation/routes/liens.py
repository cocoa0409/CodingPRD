"""Lien CRUD + state machine."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_CLAIM_INVALID_STATE,
    ERR_LIEN_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_HOLDER_WINDOW_OPEN,
    ERR_FINAL_EXCEEDS_ASSERTED,
    ERR_UNRESOLVED_LIENS_EXIST,
    ERR_OPEN_APPEAL_BLOCKS_FINALIZE,
)
from middleware import require_role
from response import success_envelope
from routes.helpers import (
    bump,
    get_json_body,
    get_pagination,
    new_common_fields,
    paginate,
    require_fields,
    resolve_claim,
    resolve_lien,
    sort_by_created_at,
)
from services.calculations import (
    provisional_lien_demand,
    recompute_claim_totals,
)

bp = Blueprint("liens", __name__)

LIEN_READ_ROLES = (
    "ProgramAdministrator",
    "LienAnalyst",
    "DisbursementApprover",
    "ClaimantRole",
)

VALID_LIEN_TYPES = {"MEDICARE", "MEDICAID", "PRIVATE_INSURER", "MEDICAL_PROVIDER", "VA_TRICARE"}


def _parse_iso(s):
    """Parse an ISO 8601 datetime string, handling both Z and +00:00."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _format_iso(dt):
    """Format a datetime as ISO 8601 UTC with Z suffix.

    The program logical clock reads e.g. exactly ``2026-08-01T00:00:00Z``
    (PRD §2.5), so stamps derived from it (holder_response_due_at = clock +
    30 days, PRD §3.5) keep the same fractional-less shape unless the clock
    itself carries sub-second precision.
    """
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@bp.route("/settlement-programs/<pid>/claims/<cid>/liens", methods=["POST"])
def create_lien(pid, cid):
    user_id, role = require_role("LienAnalyst")
    prog, claim = resolve_claim(pid, cid)

    # PRD §3.5: identification targets a TIER_ASSIGNED claim; the first
    # identification moves the claim to LIENS_PENDING and "later
    # identifications leave the claim status alone" — i.e. they are permitted
    # while the claim is LIENS_PENDING.
    if claim["status"] not in ("TIER_ASSIGNED", "LIENS_PENDING"):
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Claim must be TIER_ASSIGNED or LIENS_PENDING to identify a lien", 409)

    body = get_json_body()
    require_fields(body, ["lien_type", "holder_name", "asserted_amount_cents"])

    lt = body["lien_type"]
    if lt not in VALID_LIEN_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, "lien_type must be one of MEDICARE, MEDICAID, PRIVATE_INSURER, MEDICAL_PROVIDER, VA_TRICARE", 400)

    if not isinstance(body["asserted_amount_cents"], int) or body["asserted_amount_cents"] < 0:
        raise ApiError(ERR_INVALID_REQUEST, "asserted_amount_cents must be a non-negative integer", 400)

    lien = {
        "claim_id": cid,
        "lien_type": lt,
        "holder_name": body["holder_name"],
        "asserted_amount_cents": body["asserted_amount_cents"],
        "provisional_demand_cents": None,
        "final_demand_cents": None,
        "holder_response_due_at": None,
        "resolution_notes": None,
        "state": "IDENTIFIED",
    }
    lien.update(new_common_fields())
    db.liens[lien["id"]] = lien

    # Cascade: first lien on TIER_ASSIGNED claim advances it to LIENS_PENDING
    if claim["status"] == "TIER_ASSIGNED":
        claim["status"] = "LIENS_PENDING"
        bump(claim)

    return success_envelope(lien, 201, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/liens", methods=["GET"])
def list_liens(pid, cid):
    user_id, role = require_role(*LIEN_READ_ROLES)
    prog, claim = resolve_claim(pid, cid)
    limit, offset = get_pagination()

    items = [l for l in db.liens.values() if l["claim_id"] == cid]

    state_filter = request.args.get("state")
    if state_filter:
        items = [l for l in items if l["state"] == state_filter]

    type_filter = request.args.get("lien_type")
    if type_filter:
        items = [l for l in items if l["lien_type"] == type_filter]

    claim_filter = request.args.get("claim_id")
    if claim_filter:
        items = [l for l in items if l["claim_id"] == claim_filter]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)


@bp.route("/settlement-programs/<pid>/claims/<cid>/liens/<lid>", methods=["GET"])
def get_lien(pid, cid, lid):
    user_id, role = require_role(*LIEN_READ_ROLES)
    prog, claim, lien = resolve_lien(pid, cid, lid)
    return success_envelope(lien, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/liens/<lid>/notify", methods=["POST"])
def notify_lien(pid, cid, lid):
    user_id, role = require_role("LienAnalyst")
    prog, claim, lien = resolve_lien(pid, cid, lid)

    if lien["state"] != "IDENTIFIED":
        raise ApiError(ERR_LIEN_INVALID_STATE, "Lien must be IDENTIFIED to notify", 409)

    if claim["status"] != "LIENS_PENDING":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Claim must be LIENS_PENDING", 409)

    # Compute provisional demand
    lien["provisional_demand_cents"] = provisional_lien_demand(lien, claim)

    # Set holder response deadline: current_utc + 30 days
    current = _parse_iso(prog["current_utc"])
    due = current + timedelta(days=30)
    lien["holder_response_due_at"] = _format_iso(due)

    lien["state"] = "NOTIFIED"
    bump(lien)
    return success_envelope(lien, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/liens/<lid>/begin-negotiation", methods=["POST"])
def begin_negotiation(pid, cid, lid):
    user_id, role = require_role("LienAnalyst")
    prog, claim, lien = resolve_lien(pid, cid, lid)

    if lien["state"] not in ("NOTIFIED", "DISPUTED"):
        raise ApiError(ERR_LIEN_INVALID_STATE, "Lien must be NOTIFIED or DISPUTED to begin negotiation", 409)

    lien["state"] = "IN_NEGOTIATION"
    bump(lien)
    return success_envelope(lien, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/liens/<lid>/dispute", methods=["POST"])
def dispute_lien(pid, cid, lid):
    user_id, role = require_role("ClaimantRole")
    prog, claim, lien = resolve_lien(pid, cid, lid)

    # ClaimantRole ownership check
    if user_id != claim["claimant_id"]:
        raise ApiError(ERR_NOT_FOUND, "Lien not found", 404)

    if lien["state"] != "IN_NEGOTIATION":
        raise ApiError(ERR_LIEN_INVALID_STATE, "Lien must be IN_NEGOTIATION to dispute", 409)

    lien["state"] = "DISPUTED"
    bump(lien)
    return success_envelope(lien, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/liens/<lid>/resolve", methods=["POST"])
def resolve_lien_endpoint(pid, cid, lid):
    user_id, role = require_role("LienAnalyst")
    prog, claim, lien = resolve_lien(pid, cid, lid)

    body = get_json_body()
    require_fields(body, ["expected_claim_version"])

    # OCC check BEFORE any state validation
    expected = body["expected_claim_version"]
    if expected != claim["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_claim_version does not match claim.version", 412)

    if lien["state"] == "NOTIFIED":
        # Silent-holder path
        due = _parse_iso(lien["holder_response_due_at"])
        current = _parse_iso(prog["current_utc"])
        if current <= due:
            raise ApiError(ERR_HOLDER_WINDOW_OPEN, "Holder response window has not yet closed", 422)
        lien["final_demand_cents"] = lien["asserted_amount_cents"]
        if "resolution_notes" in body and body["resolution_notes"] is not None:
            lien["resolution_notes"] = body["resolution_notes"]
    elif lien["state"] == "IN_NEGOTIATION":
        # Negotiated path
        require_fields(body, ["final_demand_cents"])
        final = body["final_demand_cents"]
        if not isinstance(final, int):
            raise ApiError(ERR_INVALID_REQUEST, "final_demand_cents must be an integer", 400)
        if final < 0:
            raise ApiError(ERR_INVALID_REQUEST, "final_demand_cents must be >= 0", 400)
        if final > lien["asserted_amount_cents"]:
            raise ApiError(ERR_FINAL_EXCEEDS_ASSERTED, "final_demand_cents exceeds asserted_amount_cents", 422)
        lien["final_demand_cents"] = final
        if "resolution_notes" in body and body["resolution_notes"] is not None:
            lien["resolution_notes"] = body["resolution_notes"]
    else:
        raise ApiError(ERR_LIEN_INVALID_STATE, "Lien must be NOTIFIED or IN_NEGOTIATION to resolve", 409)

    lien["state"] = "RESOLVED"
    bump(lien)

    # Recompute claim totals and bump claim version
    recompute_claim_totals(claim)
    bump(claim)

    return success_envelope(lien, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/liens/<lid>/waive", methods=["POST"])
def waive_lien(pid, cid, lid):
    user_id, role = require_role("LienAnalyst")
    prog, claim, lien = resolve_lien(pid, cid, lid)

    if lien["state"] not in ("IDENTIFIED", "NOTIFIED", "IN_NEGOTIATION"):
        raise ApiError(ERR_LIEN_INVALID_STATE, "Lien must be IDENTIFIED, NOTIFIED, or IN_NEGOTIATION to waive", 409)

    body = get_json_body()
    require_fields(body, ["resolution_notes"])
    notes = body["resolution_notes"]
    if not isinstance(notes, str) or len(notes.strip()) == 0:
        raise ApiError(ERR_INVALID_REQUEST, "resolution_notes must be non-empty", 400)

    lien["state"] = "WAIVED"
    lien["final_demand_cents"] = 0
    lien["resolution_notes"] = notes
    bump(lien)

    # Recompute claim totals
    recompute_claim_totals(claim)
    bump(claim)

    return success_envelope(lien, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/finalize-liens", methods=["POST"])
def finalize_liens(pid, cid):
    user_id, role = require_role("LienAnalyst")
    prog, claim = resolve_claim(pid, cid)

    if claim["status"] != "LIENS_PENDING":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Claim must be LIENS_PENDING to finalize liens", 409)

    # Check all liens are RESOLVED or WAIVED
    for lien in db.liens.values():
        if lien["claim_id"] == cid and lien["state"] in ("IDENTIFIED", "NOTIFIED", "IN_NEGOTIATION", "DISPUTED"):
            raise ApiError(ERR_UNRESOLVED_LIENS_EXIST, "One or more liens are still unresolved", 409)

    # Check no open appeal
    if claim["active_appeal_id"] is not None:
        raise ApiError(ERR_OPEN_APPEAL_BLOCKS_FINALIZE, "An open appeal blocks lien finalization", 409)

    claim["status"] = "LIENS_RESOLVED"
    claim["lien_posture"] = "ALL_RESOLVED"
    recompute_claim_totals(claim)
    bump(claim)
    return success_envelope(claim, 200, "object")
