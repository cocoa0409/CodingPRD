"""Restitution ledger and recovery payment endpoints (PRD §3.7)."""

from __future__ import annotations

from flask import Blueprint

import db
from constants import CASE_TERMINAL, PAYMENT_METHODS
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_CASE_NOT_IN_REQUIRED_STATE,
    ERR_RECOVERY_EXCEEDS_OUTSTANDING,
    ERR_RESTITUTION_TARGET_INVALID,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import pub_ledger, pub_payment
from services.cascade import recompute_ledger
from util import (
    apply_filters,
    child_or_404,
    get_json_body,
    page_of,
    parse_pagination,
    path_or_404,
    require_enum,
    require_int,
    require_string,
    require_ts,
    require_version,
    sort_created,
)

bp = Blueprint("restitution", __name__)

MGR = ("SIUManager",)
LEDGER_READERS = ("SIUManager", "SIUComplianceOfficer")
CASE_LIST_READERS = ("SIUManager", "SIUInvestigator", "SIUComplianceOfficer")


def _resolve_ledger(ledgerId: str, paymentId: str = None):
    ledger = path_or_404(db.ledgers, ledgerId, "RestitutionLedger")
    payment = None
    if paymentId is not None:
        payment = child_or_404(db.payments, paymentId, "ledger_id", ledger["id"], "RecoveryPayment")
    return ledger, payment


@bp.post("/siu/cases/<caseId>/restitution-ledgers")
@require_roles("SIUManager")
def create_ledger(caseId: str, _user_id: str, _role: str):
    body = get_json_body()
    target = require_int(body, "target_amount_cents")
    case = path_or_404(db.cases, caseId, "SIUCase")
    claim = db.claims.get(case.get("claim_id")) or {}
    if target <= 0 or target > int(claim.get("claimed_amount_cents", 0)):
        raise_err(
            ERR_RESTITUTION_TARGET_INVALID,
            "target_amount_cents must be > 0 and <= the claim's claimed_amount_cents",
        )
    ledger = {
        "case_id": case["id"],
        "target_amount_cents": target,
        "recovered_amount_cents": 0,
        "outstanding_amount_cents": target,
        "status": "OPEN",
    }
    db.stamp_new(ledger)
    db.ledgers[ledger["id"]] = ledger
    return success_object(pub_ledger(ledger), 201)


@bp.get("/siu/cases/<caseId>/restitution-ledgers")
@require_roles(*CASE_LIST_READERS)
def list_case_ledgers(caseId: str, _user_id: str, _role: str):
    case = path_or_404(db.cases, caseId, "SIUCase")
    limit, offset = parse_pagination()
    items = sort_created([l for l in db.ledgers.values() if l.get("case_id") == case["id"]])
    page, total = page_of(items, limit, offset)
    return success_list([pub_ledger(l) for l in page], limit, offset, total)


@bp.get("/siu/ledgers")
@require_roles(*CASE_LIST_READERS)
def list_ledgers(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = apply_filters(list(db.ledgers.values()), ["case_id", "status"])
    items = sort_created(items)
    page, total = page_of(items, limit, offset)
    return success_list([pub_ledger(l) for l in page], limit, offset, total)


@bp.get("/siu/ledgers/<ledgerId>")
@require_roles(*LEDGER_READERS)
def get_ledger(ledgerId: str, _user_id: str, _role: str):
    ledger, _ = _resolve_ledger(ledgerId)
    return success_object(pub_ledger(ledger))


@bp.get("/siu/ledgers/<ledgerId>/payments")
@require_roles(*LEDGER_READERS)
def list_ledger_payments(ledgerId: str, _user_id: str, _role: str):
    ledger, _ = _resolve_ledger(ledgerId)
    limit, offset = parse_pagination()
    items = sort_created([p for p in db.payments.values() if p.get("ledger_id") == ledger["id"]])
    page, total = page_of(items, limit, offset)
    return success_list([pub_payment(p) for p in page], limit, offset, total)


@bp.get("/siu/recovery-payments")
@require_roles(*LEDGER_READERS)
def list_all_payments(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = apply_filters(list(db.payments.values()), ["ledger_id", "status", "method"])
    items = sort_created(items)
    page, total = page_of(items, limit, offset)
    return success_list([pub_payment(p) for p in page], limit, offset, total)


@bp.get("/siu/recovery-payments/<paymentId>")
@require_roles(*LEDGER_READERS)
def get_payment(paymentId: str, _user_id: str, _role: str):
    payment = path_or_404(db.payments, paymentId, "RecoveryPayment")
    return success_object(pub_payment(payment))


@bp.post("/siu/ledgers/<ledgerId>/payments")
@require_roles("SIUManager")
def create_payment(ledgerId: str, _user_id: str, _role: str):
    body = get_json_body()
    amount_cents = require_int(body, "amount_cents", minimum=1)
    received_at = require_ts(body, "received_at")
    method = require_enum(body, "method", PAYMENT_METHODS)
    ledger, _ = _resolve_ledger(ledgerId)
    payment = {
        "ledger_id": ledger["id"],
        "amount_cents": amount_cents,
        "received_at": received_at,
        "method": method,
        "status": "PENDING",
        "reversed_at": None,
    }
    db.stamp_new(payment)
    db.payments[payment["id"]] = payment
    return success_object(pub_payment(payment), 201)


@bp.post("/siu/ledgers/<ledgerId>/payments/<paymentId>/clear")
@require_roles("SIUManager")
def clear_payment(ledgerId: str, paymentId: str, _user_id: str, _role: str):
    body = get_json_body()
    expected_ledger_version = require_version(body, "expected_ledger_version")
    ledger, payment = _resolve_ledger(ledgerId, paymentId)
    # Rung 5: the payment must be PENDING.
    if payment.get("status") != "PENDING":
        raise_err(ERR_INVALID_STATE, "Payment must be PENDING to be cleared")
    # Rung 7 (priority 17): the amount must not exceed the outstanding balance.
    if int(payment.get("amount_cents", 0)) > int(ledger.get("outstanding_amount_cents", 0)):
        raise_err(ERR_RECOVERY_EXCEEDS_OUTSTANDING, "Clearing would drive recovered above the target")
    # Rung 8: optimistic concurrency on the ledger.
    if expected_ledger_version != int(ledger.get("version", 0)):
        raise_err(ERR_STALE_VERSION, "expected_ledger_version does not match the ledger version")
    payment["status"] = "CLEARED"
    db.touch(payment)
    recompute_ledger(ledger)
    return success_object(pub_payment(payment))


@bp.post("/siu/ledgers/<ledgerId>/payments/<paymentId>/return")
@require_roles("SIUManager")
def return_payment(ledgerId: str, paymentId: str, _user_id: str, _role: str):
    body = get_json_body()
    require_string(body, "reason")
    _, payment = _resolve_ledger(ledgerId, paymentId)
    if payment.get("status") != "PENDING":
        raise_err(ERR_INVALID_STATE, "Payment must be PENDING to be returned")
    payment["status"] = "RETURNED"
    db.touch(payment)
    return success_object(pub_payment(payment))


@bp.post("/siu/ledgers/<ledgerId>/payments/<paymentId>/reverse")
@require_roles("SIUManager")
def reverse_payment(ledgerId: str, paymentId: str, _user_id: str, _role: str):
    body = get_json_body()
    require_string(body, "reason")
    ledger, payment = _resolve_ledger(ledgerId, paymentId)
    if payment.get("status") != "CLEARED":
        raise_err(ERR_INVALID_STATE, "Payment must be CLEARED to be reversed")
    payment["status"] = "REVERSED"
    payment["reversed_at"] = db.clock.now_string()
    db.touch(payment)
    recompute_ledger(ledger)
    return success_object(pub_payment(payment))


@bp.post("/siu/cases/<caseId>/restitution-ledgers/<ledgerId>/write-off")
@require_roles("SIUManager")
def write_off_ledger(caseId: str, ledgerId: str, _user_id: str, _role: str):
    body = get_json_body()
    require_string(body, "reason")
    case = path_or_404(db.cases, caseId, "SIUCase")
    ledger = child_or_404(db.ledgers, ledgerId, "case_id", case["id"], "RestitutionLedger")
    # Rung 5: write-off runs from OPEN or PARTIALLY_RECOVERED; from OPEN the
    # outstanding balance must be positive.
    if ledger.get("status") not in ("OPEN", "PARTIALLY_RECOVERED"):
        raise_err(ERR_INVALID_STATE, "Ledger must be OPEN or PARTIALLY_RECOVERED to write off")
    if ledger.get("status") == "OPEN" and int(ledger.get("outstanding_amount_cents", 0)) <= 0:
        raise_err(ERR_INVALID_STATE, "OPEN ledger with no outstanding balance cannot be written off")
    # Rung 6: the case must be in a terminal status.
    if case.get("status") not in CASE_TERMINAL:
        raise_err(ERR_CASE_NOT_IN_REQUIRED_STATE, "Case must be in a terminal status to write off")
    ledger["status"] = "WRITTEN_OFF"
    db.touch(ledger)
    return success_object(pub_ledger(ledger))
