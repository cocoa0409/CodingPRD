"""Victim claims, the evidence cycle and the four-hop reissue cascade
(PRD 3.9)."""
from datetime import timedelta

import clock
from flask import Blueprint

import db as dbm
import response
import validate
from db import db
from errors import fail
from routes.common import (READ_ROLES, authenticate, filter_by, listing_response,
                           require_alert, require_card, require_claim)
from services import cards as card_svc
from services import claims as claim_svc
from services import liability as liability_svc
from services.claims import CLAIM_STATES, DECISIONS, EVIDENCE_KINDS

bp = Blueprint("claims", __name__)


@bp.post("/victim-claims")
def file_claim():
    caller = authenticate(["PosAssociate", "FraudAnalyst"])
    body = validate.body()
    card_id = validate.string(body, "card_id", min_len=1)
    claimant_name = validate.string(body, "claimant_name", min_len=1, max_len=120)
    claimant_contact = validate.string(body, "claimant_contact", min_len=1,
                                       max_len=160)
    disputed = validate.integer(body, "disputed_amount_cents", minimum=1)
    purchased_at = validate.datetime_field(body, "purchased_at")
    alert_id = validate.string(body, "alert_id", required=False, min_len=1)
    receipt_ref = validate.string(body, "purchase_receipt_ref", required=False,
                                  min_len=None)
    packaging_ref = validate.string(body, "packaging_photo_ref", required=False,
                                    min_len=None)
    require_card(card_id)
    if alert_id is not None:
        require_alert(alert_id)

    policy = dbm.policy()
    # Inclusive boundary: exactly claim_window_days after purchase is accepted.
    if clock.now() - purchased_at > timedelta(days=policy["claim_window_days"]):
        fail("ERR_CLAIM_WINDOW_EXPIRED")

    rec = dbm.record({
        "card_id": card_id,
        "alert_id": alert_id,
        "reissued_card_id": None,
        "claimant_name": claimant_name,
        "claimant_contact": claimant_contact,
        "purchase_receipt_ref": receipt_ref,
        "packaging_photo_ref": packaging_ref,
        "disputed_amount_cents": disputed,
        "purchased_at": purchased_at,
        "state": "SUBMITTED",
        "evidence_round": 0,
        "missing_evidence_kinds": [],
        "unauthorized_line_count": 0,
        "gross_reissue_cents": None,
        "reissue_amount_cents": None,
        "residual_transfer_cents": None,
        "intake_user_id": caller.user_id,
        "decided_by_user_id": None,
        "decision_note": None,
        "rescind_reason": None,
    })
    db.claims[rec["id"]] = rec
    return response.created(rec)


@bp.get("/victim-claims")
def list_claims():
    authenticate(READ_ROLES)
    card_id = validate.query_str("card_id")
    alert_id = validate.query_str("alert_id")
    reissued_card_id = validate.query_str("reissued_card_id")
    state = validate.query_enum("state", CLAIM_STATES)
    rows = list(db.claims.values())
    rows = filter_by(rows, "card_id", card_id)
    rows = filter_by(rows, "alert_id", alert_id)
    rows = filter_by(rows, "reissued_card_id", reissued_card_id)
    rows = filter_by(rows, "state", state)
    return listing_response(rows)


@bp.get("/victim-claims/<claim_id>")
def get_claim(claim_id):
    authenticate(READ_ROLES)
    return response.ok(require_claim(claim_id))


@bp.post("/victim-claims/<claim_id>/request-evidence")
def request_evidence(claim_id):
    authenticate(["FraudAnalyst"])
    body = validate.body()
    kinds = validate.string_list(body, "missing_evidence_kinds",
                                 allowed=EVIDENCE_KINDS)
    claim = require_claim(claim_id)
    if claim["state"] != "SUBMITTED":
        fail("ERR_INVALID_CLAIM_STATE")
    policy = dbm.policy()
    if claim["evidence_round"] >= policy["claim_evidence_round_limit"]:
        fail("ERR_EVIDENCE_ROUND_LIMIT_EXCEEDED")
    claim["state"] = "EVIDENCE_REQUESTED"
    claim["evidence_round"] = claim["evidence_round"] + 1
    claim["missing_evidence_kinds"] = kinds
    dbm.touch(claim)
    return response.ok(claim)


@bp.post("/victim-claims/<claim_id>/resubmit-evidence")
def resubmit_evidence(claim_id):
    authenticate(["PosAssociate", "FraudAnalyst"])
    body = validate.body()
    receipt_ref = validate.string(body, "purchase_receipt_ref", required=False,
                                  min_len=None)
    packaging_ref = validate.string(body, "packaging_photo_ref", required=False,
                                    min_len=None)
    claim = require_claim(claim_id)
    if claim["state"] != "EVIDENCE_REQUESTED":
        fail("ERR_INVALID_CLAIM_STATE")
    # Only the references actually supplied are overwritten.
    if receipt_ref is not None:
        claim["purchase_receipt_ref"] = receipt_ref
    if packaging_ref is not None:
        claim["packaging_photo_ref"] = packaging_ref
    claim["state"] = "SUBMITTED"
    # evidence_round is deliberately NOT reset.
    dbm.touch(claim)
    return response.ok(claim)


@bp.post("/victim-claims/<claim_id>/decide")
def decide_claim(claim_id):
    caller = authenticate(["RiskManager"])
    body = validate.body()
    decision = validate.enum(body, "decision", DECISIONS)
    note = validate.string(body, "decision_note", required=False, min_len=None)
    claim = require_claim(claim_id)
    if claim["state"] != "SUBMITTED":
        fail("ERR_INVALID_CLAIM_STATE")
    if claim["intake_user_id"] == caller.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")

    policy = dbm.policy()
    card = db.cards.get(claim["card_id"])

    if decision == "DENY":
        claim["state"] = "DENIED"
        claim["decided_by_user_id"] = caller.user_id
        claim["decision_note"] = note
        dbm.touch(claim)
        return response.ok(claim)

    # Evidence gate: a receipt is always mandatory, a packaging photo only for
    # a PHYSICAL card.
    if not claim.get("purchase_receipt_ref"):
        fail("ERR_EVIDENCE_INCOMPLETE")
    if card is not None and card["channel"] == "PHYSICAL" \
            and not claim.get("packaging_photo_ref"):
        fail("ERR_EVIDENCE_INCOMPLETE")

    card_svc.recompute(card)
    line_count, gross, reissue, residual = claim_svc.reissue_figures(
        claim, card, policy)
    # The cap is tested before any other clamping, and nothing is written when
    # it bites.
    if gross > policy["reissue_cap_cents"]:
        fail("ERR_REISSUE_LIMIT_EXCEEDED")

    # HOP 1 - freeze the arithmetic onto the claim.
    claim["state"] = "APPROVED"
    claim["unauthorized_line_count"] = line_count
    claim["gross_reissue_cents"] = gross
    claim["reissue_amount_cents"] = reissue
    claim["residual_transfer_cents"] = residual
    claim["decided_by_user_id"] = caller.user_id
    claim["decision_note"] = note

    # HOP 2 - mint the replacement card directly in ACTIVE and credit it.
    replacement = card_svc.new_card(
        card["channel"], store_id=card.get("store_id"), rack_id=None,
        reissued_from_card_id=card["id"], activation_state="ACTIVE",
    )
    replacement["activated_at"] = clock.now()
    card_svc.append_event(replacement, "REISSUE_CREDIT", reissue + residual,
                          caller.user_id)
    card_svc.recompute(replacement)
    dbm.touch(replacement)
    claim["reissued_card_id"] = replacement["id"]

    # HOP 3 - close the original, moving the residual across.
    if residual > 0:
        card_svc.append_event(card, "REISSUE_DEBIT", residual, caller.user_id)
    card["activation_state"] = "CLOSED"
    card["closed_at"] = clock.now()
    card_svc.recompute(card)
    dbm.touch(card)

    # HOP 4 - charge the write-off to the OPEN period covering the logical now.
    period = liability_svc.open_period_containing_now()
    if period is not None:
        period["unauthorized_writeoff_cents"] = \
            period["unauthorized_writeoff_cents"] + reissue
        dbm.touch(period)

    dbm.touch(claim)
    return response.ok(claim)


def _find_event(card_id, event_type):
    for event in card_svc.card_events(card_id):
        if event["type"] == event_type:
            return event
    return None


@bp.post("/victim-claims/<claim_id>/rescind")
def rescind_claim(claim_id):
    caller = authenticate(["RiskManager", "LiabilityAccountant"])
    body = validate.body()
    reason = validate.string(body, "rescind_reason", min_len=None)
    claim = require_claim(claim_id)
    if claim["state"] != "APPROVED":
        fail("ERR_INVALID_CLAIM_STATE")

    reissue = claim["reissue_amount_cents"] or 0
    residual = claim["residual_transfer_cents"] or 0
    replacement = db.cards.get(claim["reissued_card_id"])
    original = db.cards.get(claim["card_id"])

    # Unwind HOP 2: void and quarantine the replacement.
    if replacement is not None:
        credit = _find_event(replacement["id"], "REISSUE_CREDIT")
        card_svc.append_event(
            replacement, "REISSUE_CREDIT_REVERSAL", reissue + residual,
            caller.user_id,
            reverses_event_id=credit["id"] if credit is not None else None,
        )
        replacement["activation_state"] = "VOIDED"
        replacement["risk_posture"] = "FROZEN"
        replacement["closed_at"] = clock.now()
        card_svc.recompute(replacement)
        dbm.touch(replacement)

    # Unwind HOP 3: reopen the original and hand the residual back.
    if original is not None:
        if residual > 0:
            debit = _find_event(original["id"], "REISSUE_DEBIT")
            card_svc.append_event(
                original, "REISSUE_DEBIT_REVERSAL", residual, caller.user_id,
                reverses_event_id=debit["id"] if debit is not None else None,
            )
        original["activation_state"] = "ACTIVE"
        original["closed_at"] = None
        card_svc.recompute(original)
        dbm.touch(original)

    # Unwind HOP 4.
    period = liability_svc.open_period_containing_now()
    if period is not None:
        period["unauthorized_writeoff_cents"] = \
            period["unauthorized_writeoff_cents"] - reissue
        dbm.touch(period)

    claim["state"] = "RESCINDED"
    claim["rescind_reason"] = reason
    # reissue_amount_cents, residual_transfer_cents and reissued_card_id are
    # RETAINED for audit.
    dbm.touch(claim)
    return response.ok(claim)
