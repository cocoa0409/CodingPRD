"""Claim endpoints: create, get, list, submit, apply-extension, close,
plus the /_ledger test hook for setting balance."""
from datetime import date

from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_role
from response import object_response, array_response
from validate import (
    as_int, as_string, check_occ, get_json_body, paginate, serialize,
    validate_iso_date,
)
from services import claim_logic

bp = Blueprint("claims", __name__)

DRAFT = "DRAFT"
MONETARY_PENDING = "MONETARY_PENDING"
MONETARILY_ELIGIBLE = "MONETARILY_ELIGIBLE"
MONETARILY_INELIGIBLE = "MONETARILY_INELIGIBLE"
EXHAUSTED = "EXHAUSTED"
CLOSED = "CLOSED"


def _new_claim(claimant_id, filed_date):
    rec = {
        "claimant_id": claimant_id,
        "filed_date": filed_date,
        "base_period_method": None,
        "status": DRAFT,
        "weekly_benefit_amount_cents": 0,
        "maximum_benefit_amount_cents": 0,
        "remaining_balance_cents": 0,
        "emergency_extension_id": None,
        "extension_weeks_granted": 0,
    }
    db.stamp_create(rec)
    return rec


@bp.route("/ui/claims", methods=["POST"])
def create_claim():
    p = authenticate()
    require_role(p, {"Claimant", "ProgramAdmin"})
    body = get_json_body()
    claimant_id = as_string(body, "claimant_id")
    if claimant_id not in db.claimants:
        raise err("ERR_NOT_FOUND", "claimant_id not found.")
    filed_date = as_string(body, "filed_date")
    validate_iso_date(filed_date, "filed_date")
    rec = _new_claim(claimant_id, filed_date)
    db.claims[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/ui/claims/<cid>", methods=["GET"])
def get_claim(cid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Claimant"})
    rec = db.claims.get(cid)
    if not rec:
        raise err("ERR_NOT_FOUND", "Claim not found.")
    return object_response(serialize(rec))


@bp.route("/ui/claims", methods=["GET"])
def list_claims():
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator"})
    items = list(db.claims.values())
    claimant_id = request.args.get("claimant_id")
    ext_id = request.args.get("emergency_extension_id")
    if claimant_id is not None:
        items = [c for c in items if c["claimant_id"] == claimant_id]
    if ext_id is not None:
        items = [c for c in items if c.get("emergency_extension_id") == ext_id]
    page, limit, offset, total = paginate(items)
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/ui/claims/<cid>/submit", methods=["POST"])
def submit_claim(cid):
    p = authenticate()
    require_role(p, {"Claimant", "ProgramAdmin"})
    claim = db.claims.get(cid)
    if not claim:
        raise err("ERR_NOT_FOUND", "Claim not found.")
    body = get_json_body()
    # state check (priority 7) before business rule (no-qualifying-wages)
    if claim["status"] != DRAFT:
        raise err("ERR_INVALID_STATE", "Claim is not in DRAFT.")
    # OCC (optional) is last per §2.10; but no-qualifying-wages is a business
    # rule (priority before OCC). Validate OCC after business check.
    # Business rule: at least one non-disputed WageRecord for the claimant.
    has_wages = any(
        w["claimant_id"] == claim["claimant_id"] and not w.get("is_disputed")
        for w in db.wage_records.values()
    )
    if not has_wages:
        raise err("ERR_NO_QUALIFYING_WAGES",
                  "No non-disputed wage records exist for the claimant.")
    check_occ(body, "expected_claim_version", claim, "ERR_STALE_VERSION")
    claim["status"] = MONETARY_PENDING
    db.touch(claim)
    return object_response(serialize(claim))


@bp.route("/ui/claims/<cid>/apply-extension", methods=["POST"])
def apply_extension(cid):
    p = authenticate()
    require_role(p, {"Adjudicator"})
    claim = db.claims.get(cid)
    if not claim:
        raise err("ERR_NOT_FOUND", "Claim not found.")
    body = get_json_body()
    program_id = as_string(body, "program_id")
    # expected_claim_version is REQUIRED on this op (§2.6)
    if "expected_claim_version" not in body or body["expected_claim_version"] is None:
        raise err("ERR_INVALID_REQUEST", "expected_claim_version is required.")
    program = db.extension_programs.get(program_id)
    if not program:
        raise err("ERR_NOT_FOUND", "program_id not found.")

    # state check (priority 7): apply-extension defined only from EXHAUSTED
    if claim["status"] != EXHAUSTED:
        raise err("ERR_INVALID_STATE", "Claim is not EXHAUSTED.")
    # already-applied (409) — treat as a state/uniqueness business rule
    if claim.get("emergency_extension_id") is not None:
        raise err("ERR_EXTENSION_ALREADY_APPLIED",
                  "Claim already has an emergency extension applied.")
    # extension window / active (422)
    filed = date.fromisoformat(claim["filed_date"])
    start = date.fromisoformat(program["trigger_start_date"])
    end = date.fromisoformat(program["trigger_end_date"])
    if not program.get("is_active"):
        raise err("ERR_EXTENSION_WINDOW", "Program is not active.")
    if not (start <= filed <= end):
        raise err("ERR_EXTENSION_WINDOW",
                  "Claim filed_date is outside the program window.")
    # OCC (specific code) last
    check_occ(body, "expected_claim_version", claim,
              "ERR_STALE_CLAIM_VERSION", required=True)

    # Apply
    extra_weeks = program["extra_weeks"]
    claim["emergency_extension_id"] = program_id
    claim["extension_weeks_granted"] = extra_weeks
    # recompute MBA = base_mba + extra_weeks * wba
    results = claim_logic.run_monetary(claim)
    base_mba = results["base_mba"]
    claim["maximum_benefit_amount_cents"] = base_mba + extra_weeks * claim["weekly_benefit_amount_cents"]
    # recompute remaining balance = MBA - sum(payable of PAID/OFFSET weeks)
    claim["remaining_balance_cents"] = _consumed_balance_recompute(claim)
    claim["status"] = MONETARILY_ELIGIBLE
    db.touch(claim)
    return object_response(serialize(claim))


def _consumed_balance_recompute(claim):
    """remaining = MBA - sum(payable_amount_cents of PAID/OFFSET weeks)."""
    consumed = 0
    for wc in db.weekly_certifications.values():
        if wc["claim_id"] == claim["id"] and wc["payment_status"] in ("PAID", "OFFSET"):
            consumed += wc["payable_amount_cents"]
    return claim["maximum_benefit_amount_cents"] - consumed


@bp.route("/ui/claims/<cid>/close", methods=["POST"])
def close_claim(cid):
    p = authenticate()
    require_role(p, {"Adjudicator"})
    claim = db.claims.get(cid)
    if not claim:
        raise err("ERR_NOT_FOUND", "Claim not found.")
    body = get_json_body()
    if claim["status"] not in (MONETARILY_ELIGIBLE, EXHAUSTED):
        raise err("ERR_INVALID_STATE", "Claim cannot be closed from its state.")
    # Blocked by any HELD week
    held = any(
        wc["claim_id"] == claim["id"] and wc["adjudication_status"] == "HELD"
        for wc in db.weekly_certifications.values()
    )
    if held:
        raise err("ERR_INVALID_STATE", "A held weekly certification blocks closure.")
    check_occ(body, "expected_claim_version", claim, "ERR_STALE_VERSION")
    claim["status"] = CLOSED
    db.touch(claim)
    return object_response(serialize(claim))


# ---------------------------------------------------------------------------
# Test hooks (PRD §3.10)
# ---------------------------------------------------------------------------
@bp.route("/_ledger/set_claim_balance", methods=["POST"])
def set_claim_balance():
    p = authenticate()
    require_role(p, {"ProgramAdmin"})
    body = get_json_body()
    claim_id = as_string(body, "claim_id")
    claim = db.claims.get(claim_id)
    if not claim:
        raise err("ERR_NOT_FOUND", "claim_id not found.")
    target = as_int(body, "remaining_balance_cents", minimum=0)
    if claim["status"] != MONETARILY_ELIGIBLE:
        raise err("ERR_INVALID_STATE", "Claim is not MONETARILY_ELIGIBLE.")
    if target > claim["maximum_benefit_amount_cents"]:
        raise err("ERR_INVALID_REQUEST",
                  "remaining_balance_cents exceeds maximum_benefit_amount_cents.")
    claim["remaining_balance_cents"] = target
    db.touch(claim)
    return object_response(serialize(claim))
