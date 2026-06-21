"""Transfer endpoints: create, fund, screen, dispatch (PRD §3.4-§3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import err
from response import success
from middleware import get_user_context, require_role
from services.common import (stamp_create, touch, public, get_json,
                             paginate, require_fields)
from services.clock import expire_quotes, parse_iso
from services import calculations
from services.serializers import transfer_view
from services.ledger import write_entry, sender_debit_entry

bp = Blueprint("transfers", __name__)

ALL_ROLES = {"PlatformAdmin", "RemittanceAgent", "ComplianceOfficer", "PayoutOperator"}


# ---------------------------------------------------------------------------
# Create a transfer by consuming a LOCKED quote (PRD §3.4, OCC §2.10).
# ---------------------------------------------------------------------------
@bp.route("/transfers", methods=["POST"])
def create_transfer():
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent"})
    expire_quotes()
    body = get_json()
    require_fields(body, ["quote_id", "recipient_id", "expected_quote_version"])
    # Existence left-to-right: quote then recipient (PRD §2.6).
    quote = db.quotes.get(body["quote_id"])
    if quote is None:
        raise err("ERR_NOT_FOUND", "Quote not found")
    recipient = db.recipients.get(body["recipient_id"])
    if recipient is None:
        raise err("ERR_NOT_FOUND", "Recipient not found")

    expected_version = body["expected_quote_version"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise err("ERR_INVALID_REQUEST", "expected_quote_version must be an integer")

    # OCC (priority 5 analog for transfer-create): stale quote version -> 412.
    # NOTE: existence/body checks precede OCC; OCC precedes state checks.
    if quote["version"] != expected_version:
        raise err("ERR_STALE_VERSION", "Quote version has advanced; re-read before consuming")

    # State: an auto-expired quote surfaces as ERR_QUOTE_EXPIRED (PRD §3.4); any
    # other non-LOCKED status (DRAFT, CONSUMED) is an invalid transition.
    if quote["status"] == "EXPIRED":
        raise err("ERR_QUOTE_EXPIRED", "Quote rate-lock has expired")
    if quote["status"] != "LOCKED":
        raise err("ERR_INVALID_STATE", "Only a LOCKED quote can be consumed")

    sender = db.senders[quote["sender_id"]]
    # Blocked sender (priority 8).
    if sender["status"] == "BLOCKED":
        raise err("ERR_SENDER_BLOCKED", "Sender is blocked by a confirmed sanctions match")

    # Quote must be unexpired (priority 12). expires_at strictly after clock.
    # (Defensive: a LOCKED quote whose window elapsed without a clock tick.)
    if not quote.get("expires_at") or parse_iso(quote["expires_at"]) <= db.get_clock():
        raise err("ERR_QUOTE_EXPIRED", "Quote rate-lock has expired")

    transfer = {
        "quote_id": quote["id"],
        "corridor_id": quote["corridor_id"],
        "sender_id": quote["sender_id"],
        "recipient_id": recipient["id"],
        "send_principal_minor": quote["send_principal_minor"],
        "fee_minor": quote["fee_minor"],
        "recipient_amount_minor": quote["recipient_amount_minor"],
        "locked_rate_micro": quote["locked_rate_micro"],
        "funding_status": "UNFUNDED",
        "compliance_status": "SCREENING",
        "delivery_status": "PENDING",
        "sanctions_score": None,
    }
    stamp_create(transfer)
    db.transfers[transfer["id"]] = transfer

    # Consume the quote (LOCKED -> CONSUMED, bump version).
    quote["status"] = "CONSUMED"
    touch(quote)

    return success(transfer_view(transfer), 201)


@bp.route("/transfers/<transfer_id>", methods=["GET"])
def get_transfer(transfer_id):
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent", "ComplianceOfficer", "PayoutOperator"})
    transfer = db.transfers.get(transfer_id)
    if transfer is None:
        raise err("ERR_NOT_FOUND", "Transfer not found")
    return success(transfer_view(transfer), 200)


@bp.route("/transfers", methods=["GET"])
def list_transfers():
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent", "ComplianceOfficer", "PayoutOperator"})
    items = list(db.transfers.values())
    for key in ("quote_id", "sender_id", "recipient_id", "corridor_id",
                "compliance_status", "delivery_status"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t.get(key) == val]
    page, meta = paginate(items)
    return success([transfer_view(t) for t in page], 200, pagination=meta)


# ---------------------------------------------------------------------------
# Fund (UNFUNDED -> FUNDED): the send-limit choke point (PRD §3.4).
# ---------------------------------------------------------------------------
@bp.route("/transfers/<transfer_id>/fund", methods=["POST"])
def fund_transfer(transfer_id):
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent"})
    transfer = db.transfers.get(transfer_id)
    if transfer is None:
        raise err("ERR_NOT_FOUND", "Transfer not found")

    # State precondition: must be UNFUNDED, and compliance not REJECTED.
    if transfer["funding_status"] != "UNFUNDED":
        raise err("ERR_INVALID_STATE", "Transfer is already funded")
    if transfer["compliance_status"] == "REJECTED":
        raise err("ERR_INVALID_STATE", "A rejected transfer cannot be funded")

    corridor = db.corridors[transfer["corridor_id"]]
    sender = db.senders[transfer["sender_id"]]
    principal = transfer["send_principal_minor"]

    # Three inclusive ceilings in priority order (13, 14, 15).
    if principal > corridor["per_transfer_max_minor"]:
        raise err("ERR_PER_TRANSFER_LIMIT", "Exceeds per-transfer maximum")
    if principal > calculations.kyc_ceiling(sender["kyc_tier"]):
        raise err("ERR_KYC_TIER_LIMIT", "Exceeds the sender's KYC-tier ceiling")

    # Rolling-window cumulative funded send for this sender on this corridor.
    window_start = db.get_clock() - timedelta(hours=corridor["rolling_window_hours"])
    prior = 0
    for t in db.transfers.values():
        if t["id"] == transfer["id"]:
            continue
        if t["corridor_id"] != corridor["id"] or t["sender_id"] != sender["id"]:
            continue
        if t["funding_status"] != "FUNDED":
            continue
        debit = sender_debit_entry(t["id"])
        if debit is None:
            continue
        # Exclusive lower bound: created_at strictly after window_start.
        if parse_iso(debit["created_at"]) > window_start:
            prior += t["send_principal_minor"]
    projected = prior + principal
    if projected > corridor["rolling_window_cap_minor"]:
        raise err("ERR_ROLLING_WINDOW_LIMIT", "Exceeds the rolling-window cap")

    # Commit: FUNDED, reserve, write SENDER_DEBIT + FEE_REVENUE.
    transfer["funding_status"] = "FUNDED"
    corridor["reserved_minor"] += principal
    write_entry(transfer["id"], "SENDER_DEBIT",
                -(principal + transfer["fee_minor"]), "Sender pay-in (principal + fee)")
    write_entry(transfer["id"], "FEE_REVENUE", transfer["fee_minor"],
                "Disclosed fee revenue")
    touch(transfer)
    return success(transfer_view(transfer), 200)


# ---------------------------------------------------------------------------
# Screen (compliance SCREENING -> CLEARED|HELD) (PRD §3.5).
# ---------------------------------------------------------------------------
@bp.route("/transfers/<transfer_id>/screen", methods=["POST"])
def screen_transfer(transfer_id):
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer"})
    user_id, _ = get_user_context()
    transfer = db.transfers.get(transfer_id)
    if transfer is None:
        raise err("ERR_NOT_FOUND", "Transfer not found")
    if transfer["compliance_status"] != "SCREENING":
        raise err("ERR_INVALID_STATE", "Transfer is not awaiting screening")

    sender = db.senders[transfer["sender_id"]]
    recipient = db.recipients[transfer["recipient_id"]]
    entries = list(db.sanctions_list.values())
    subjects = [
        ("SENDER", sender["id"], sender["full_name"], sender["country"]),
        ("RECIPIENT", recipient["id"], recipient["full_name"], recipient["country"]),
    ]
    best, hits = calculations.screen_subjects(subjects, entries)
    transfer["sanctions_score"] = best

    if best < calculations.SANCTIONS_CLEAR_THRESHOLD:
        transfer["compliance_status"] = "CLEARED"
        touch(transfer)
        return success(transfer_view(transfer), 200)

    # HELD: write a SanctionsHit per qualifying (subject, entry) pair, open a case.
    transfer["compliance_status"] = "HELD"
    top_hit_id = None
    for (kind, sid, entry, score) in hits:
        hit = {
            "transfer_id": transfer["id"],
            "list_entry_id": entry["id"],
            "subject_kind": kind,
            "subject_id": sid,
            "score": score,
        }
        stamp_create(hit, versioned=False)
        db.sanctions_hits[hit["id"]] = hit
        if top_hit_id is None:
            top_hit_id = hit["id"]  # hits already sorted: first is top-scoring

    case = {
        "transfer_id": transfer["id"],
        "sanctions_hit_id": top_hit_id,
        "opened_reason": "SANCTIONS_SCORE",
        "assigned_officer_id": user_id,
        "info_request_count": 0,
        "status": "OPEN",
    }
    stamp_create(case)
    db.compliance_cases[case["id"]] = case

    touch(transfer)
    return success(transfer_view(transfer), 200)


# ---------------------------------------------------------------------------
# Dispatch (delivery PENDING|FAILED -> IN_TRANSIT) (PRD §3.6).
# ---------------------------------------------------------------------------
@bp.route("/transfers/<transfer_id>/dispatch", methods=["POST"])
def dispatch_transfer(transfer_id):
    _, role = get_user_context()
    require_role(role, {"PayoutOperator"})
    transfer = db.transfers.get(transfer_id)
    if transfer is None:
        raise err("ERR_NOT_FOUND", "Transfer not found")

    delivery = transfer["delivery_status"]
    # State precondition (priority 6): only PENDING or FAILED can dispatch.
    if delivery not in ("PENDING", "FAILED"):
        raise err("ERR_INVALID_STATE", "Transfer cannot be dispatched from its delivery state")

    # Retry guard from FAILED (priority via state machine): below MAX attempts.
    if delivery == "FAILED":
        failed_count = sum(1 for a in db.payout_attempts.values()
                           if a["transfer_id"] == transfer["id"]
                           and a["outcome"] == "FAILED")
        if failed_count >= calculations.MAX_PAYOUT_ATTEMPTS:
            raise err("ERR_MAX_ATTEMPTS_REACHED", "Maximum payout attempts reached")

    # Funded (priority via business safety), compliance cleared, recipient verified.
    if transfer["funding_status"] != "FUNDED":
        raise err("ERR_TRANSFER_NOT_FUNDED", "Transfer must be funded before dispatch")
    if transfer["compliance_status"] != "CLEARED":
        raise err("ERR_COMPLIANCE_HOLD", "Transfer is under a compliance hold")
    recipient = db.recipients[transfer["recipient_id"]]
    if recipient["kyc_status"] != "VERIFIED":
        raise err("ERR_RECIPIENT_NOT_VERIFIED", "Recipient is not verified")

    prior_attempts = sum(1 for a in db.payout_attempts.values()
                         if a["transfer_id"] == transfer["id"])
    attempt = {
        "transfer_id": transfer["id"],
        "payout_method": recipient["payout_method"],
        "attempt_index": prior_attempts + 1,
        "outcome": "PENDING",
        "failure_reason": None,
    }
    stamp_create(attempt)
    db.payout_attempts[attempt["id"]] = attempt

    transfer["delivery_status"] = "IN_TRANSIT"
    touch(transfer)
    return success(transfer_view(transfer), 200)
