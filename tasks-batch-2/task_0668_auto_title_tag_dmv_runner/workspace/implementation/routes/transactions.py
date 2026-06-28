"""Transaction endpoints and lifecycle transitions (PRD §3.2-§3.9; scaffold §1.5)."""

from flask import Blueprint, g, request

import calculations
import errors
import repo
from clock import clock, add_hours, format_iso8601_ms
from db import db
from domain import (active_schedule_for_state, recompute_account_balance,
                    checklist_outcome, lien_in_play, active_quote_for_transaction,
                    settled_quote_for_transaction, REQUIRED_CHECKLIST,
                    quotes_for_transaction, documents_for_transaction,
                    submissions_for_transaction, lien_packets_for_transaction)
from helpers import (get_json_body, require_str, require_int, require_enum,
                     opt_int, opt_bool, parse_pagination, paginate)
from middleware import require_roles
from response import success, list_success
from serializers import (transaction_out, fee_quote_out, submission_out,
                         document_item_out, lien_packet_out)

bp = Blueprint("transactions", __name__)

MAX_REJECTION_ROUNDS = 3
EXPEDITE_SLA_HOURS = 48


def _get_txn_or_404(tid):
    txn = db.transactions.get(tid)
    if txn is None:
        raise errors.not_found("transaction not found")
    return txn


# ----------------------------------------------------------------------------
# List & create & fetch
# ----------------------------------------------------------------------------

@bp.route("/dmv/transactions", methods=["GET"])
@require_roles("PlatformAdmin", "FeeAnalyst", "IntakeClerk", "AccountHolder")
def list_transactions():
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    lifecycle_status = request.args.get("lifecycle_status")
    document_status = request.args.get("document_status")
    items = list(db.transactions.values())
    if account_id is not None:
        items = [t for t in items if t["account_id"] == account_id]
    if lifecycle_status is not None:
        items = [t for t in items if t["lifecycle_status"] == lifecycle_status]
    if document_status is not None:
        items = [t for t in items if t["document_status"] == document_status]
    if g.user_role == "AccountHolder":
        items = [t for t in items if t["account_id"] == g.user_id]
    page, total = paginate(items, limit, offset)
    return list_success([transaction_out(t) for t in page], limit, offset, total)


@bp.route("/dmv/transactions", methods=["POST"])
@require_roles("IntakeClerk")
def create_transaction():
    body = get_json_body()
    account_id = require_str(body, "account_id")
    transaction_type = require_enum(
        body, "transaction_type", {"TITLE", "REGISTRATION", "TRANSFER", "LIEN"}
    )
    vin = require_str(body, "vin")
    declared_price_cents = opt_int(body, "declared_price_cents", 0)
    trade_in_allowance_cents = opt_int(body, "trade_in_allowance_cents", 0)
    expedite = opt_bool(body, "expedite", False)

    # Existence of body FK (priority 3).
    acct = db.accounts.get(account_id)
    if acct is None:
        raise errors.not_found("account not found")

    # Field validation (priority 9): VIN length 17; declared price consistent
    # with type; trade-in <= declared price.
    if len(vin) != 17:
        raise errors.invalid_transaction_fields("vin must be exactly 17 characters")
    if transaction_type in ("TITLE", "TRANSFER"):
        if declared_price_cents <= 0:
            raise errors.invalid_transaction_fields(
                "declared_price_cents must be > 0 for TITLE/TRANSFER"
            )
    else:  # REGISTRATION, LIEN
        if declared_price_cents != 0:
            raise errors.invalid_transaction_fields(
                "declared_price_cents must be 0 for REGISTRATION/LIEN"
            )
    if trade_in_allowance_cents > declared_price_cents:
        raise errors.invalid_transaction_fields(
            "trade_in_allowance_cents may not exceed declared_price_cents"
        )
    if trade_in_allowance_cents < 0:
        raise errors.validation("trade_in_allowance_cents must be >= 0")

    rec = repo.make_transaction(account_id, transaction_type, vin,
                                declared_price_cents, trade_in_allowance_cents,
                                expedite)
    return success(transaction_out(rec), 201)


@bp.route("/dmv/transactions/<tid>", methods=["GET"])
@require_roles("PlatformAdmin", "FeeAnalyst", "IntakeClerk", "AccountHolder",
               "RunnerDispatcher", "LienOfficer")
def get_transaction(tid):
    txn = _get_txn_or_404(tid)
    if g.user_role == "AccountHolder" and txn["account_id"] != g.user_id:
        raise errors.not_resource_owner("AccountHolder may only read own transactions")
    return success(transaction_out(txn), 200)


# ----------------------------------------------------------------------------
# Quote (DRAFT->QUOTED / QUOTED->QUOTED) — OCC-guarded
# ----------------------------------------------------------------------------

@bp.route("/dmv/transactions/<tid>/quote", methods=["POST"])
@require_roles("FeeAnalyst")
def quote_transaction(tid):
    body = get_json_body()
    txn = _get_txn_or_404(tid)

    # State eligibility (priority 5): DRAFT (first estimate), QUOTED (recompute),
    # or REJECTED (PRD §3.4: rework requires "a re-run quote reflecting the current
    # rejection_round surcharge exists" while lifecycle_status is REJECTED).
    if txn["lifecycle_status"] not in ("DRAFT", "QUOTED", "REJECTED"):
        raise errors.invalid_state("transaction must be DRAFT, QUOTED, or REJECTED to quote")

    # OCC guard (priority 17): expected_transaction_version required and must
    # match the current version.
    expected = body.get("expected_transaction_version")
    if expected is None:
        raise errors.invalid_request("expected_transaction_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_transaction_version must be an integer")
    if expected != txn["version"]:
        raise errors.stale_version("expected_transaction_version is stale")

    acct = db.accounts.get(txn["account_id"])
    # An ACTIVE FeeSchedule must exist for the account's state_code.
    sched = active_schedule_for_state(acct["state_code"])
    if sched is None:
        raise errors.invalid_state("no ACTIVE fee schedule for the account's state")

    components = calculations.compute_quote_components(
        txn, acct, sched, acct["ytd_completed_count"], lien_in_play(txn)
    )

    # Supersede prior ACTIVE quote, create the new ESTIMATE quote.
    prior = active_quote_for_transaction(tid)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        repo.bump(prior)

    quote = repo.make_fee_quote(tid, "ESTIMATE", sched["id"], components, "ACTIVE")
    txn["active_quote_id"] = quote["id"]
    if txn["lifecycle_status"] == "DRAFT":
        txn["lifecycle_status"] = "QUOTED"
    repo.bump(txn)
    return success(fee_quote_out(quote), 200)


# ----------------------------------------------------------------------------
# Verify documents (document_status dimension)
# ----------------------------------------------------------------------------

@bp.route("/dmv/transactions/<tid>/verify-documents", methods=["POST"])
@require_roles("IntakeClerk")
def verify_documents(tid):
    txn = _get_txn_or_404(tid)
    # The document-dimension transitions originate from COLLECTING or INCOMPLETE.
    # A VERIFIED dimension is only knocked back by a DMV rejection (system), not
    # by this endpoint; re-evaluating from VERIFIED is not a declared transition.
    if txn["document_status"] not in ("COLLECTING", "INCOMPLETE"):
        raise errors.invalid_state(
            "document_status must be COLLECTING or INCOMPLETE to evaluate"
        )
    outcome = checklist_outcome(txn)
    txn["document_status"] = outcome
    repo.bump(txn)
    return success(transaction_out(txn), 200)


# ----------------------------------------------------------------------------
# Submit / rework-resubmit (QUOTED->SUBMITTED, REJECTED->SUBMITTED)
# ----------------------------------------------------------------------------

@bp.route("/dmv/transactions/<tid>/submit", methods=["POST"])
@require_roles("IntakeClerk")
def submit_transaction(tid):
    txn = _get_txn_or_404(tid)
    lifecycle = txn["lifecycle_status"]

    # State eligibility (priority 5): only QUOTED (first submit) or REJECTED (rework).
    if lifecycle not in ("QUOTED", "REJECTED"):
        raise errors.invalid_state("transaction must be QUOTED or REJECTED to submit")

    # Documents must be VERIFIED (priority 8).
    if txn["document_status"] != "VERIFIED":
        raise errors.documents_incomplete("documents are not fully verified")

    # active_quote must be present.
    if txn["active_quote_id"] is None:
        raise errors.documents_incomplete("no active quote to submit against")

    if lifecycle == "REJECTED":
        # Rework cap (priority 13): rejection_round < MAX.
        if txn["rejection_round"] >= MAX_REJECTION_ROUNDS:
            raise errors.rework_limit_reached("rework limit reached")

    # owning Account must be ACTIVE.
    acct = db.accounts.get(txn["account_id"])
    if acct is None:
        raise errors.not_found("owning account not found")
    if acct["status"] != "ACTIVE":
        raise errors.invalid_state("owning account is not ACTIVE")

    # Rework: supersede the prior (current) submission.
    if lifecycle == "REJECTED":
        for s in submissions_for_transaction(tid):
            if s["submission_status"] not in ("SUPERSEDED",):
                # Supersede the live (non-superseded, non-terminal current) submission.
                if s["submission_status"] in ("QUEUED", "ASSIGNED", "DMV_REJECTED", "ACCEPTED"):
                    s["submission_status"] = "SUPERSEDED"
                    repo.bump(s)

    # Derive priority_class and SLA deadline.
    if txn["expedite"]:
        priority_class = "EXPEDITE"
        sla_deadline_at = format_iso8601_ms(add_hours(clock.now(), EXPEDITE_SLA_HOURS))
    else:
        priority_class = "STANDARD"
        sla_deadline_at = None

    submission = repo.make_submission(tid, priority_class, sla_deadline_at)

    # Stamp submitting user and advance lifecycle.
    txn["submitted_by_user_id"] = g.user_id
    txn["lifecycle_status"] = "SUBMITTED"
    repo.bump(txn)
    return success(submission_out(submission), 201)


# ----------------------------------------------------------------------------
# Complete (APPROVED->COMPLETED) — settle FINAL quote, reconcile account
# ----------------------------------------------------------------------------

@bp.route("/dmv/transactions/<tid>/complete", methods=["POST"])
@require_roles("FeeAnalyst")
def complete_transaction(tid):
    txn = _get_txn_or_404(tid)

    # State eligibility (priority 5): only APPROVED.
    if txn["lifecycle_status"] != "APPROVED":
        raise errors.invalid_state("transaction must be APPROVED to complete")

    # LIEN transactions require a PERFECTED lien packet.
    if txn["transaction_type"] == "LIEN":
        packets = lien_packets_for_transaction(tid)
        if not any(p["packet_status"] == "PERFECTED" for p in packets):
            raise errors.invalid_state("LIEN transaction requires a PERFECTED lien packet")

    acct = db.accounts.get(txn["account_id"])
    sched = active_schedule_for_state(acct["state_code"])
    if sched is None:
        raise errors.invalid_state("no ACTIVE fee schedule for the account's state")

    # FINAL fleet tier uses the PRE-increment count.
    components = calculations.compute_quote_components(
        txn, acct, sched, acct["ytd_completed_count"], lien_in_play(txn)
    )

    # Credit-limit pre-check for postpaid accounts (priority 16): a completion
    # that would push outstanding over the limit is rejected.
    if acct["credit_terms"]:
        completed_txn_ids = {
            t["id"] for t in db.transactions.values()
            if t["account_id"] == acct["id"] and t["lifecycle_status"] == "COMPLETED"
        }
        settled_existing = sum(
            q["total_cents"] for q in db.fee_quotes.values()
            if q["status"] == "SETTLED" and q["transaction_id"] in completed_txn_ids
        )
        charges = sum(
            p["amount_cents"] for p in db.payments.values()
            if p["account_id"] == acct["id"] and p["kind"] == "CHARGE"
        )
        refunds = sum(
            p["amount_cents"] for p in db.payments.values()
            if p["account_id"] == acct["id"] and p["kind"] == "REFUND"
        )
        projected = max(0, settled_existing + components["total_cents"] - charges + refunds)
        if projected > acct["credit_limit_cents"]:
            raise errors.credit_limit_exceeded(
                "completion would exceed the account credit limit"
            )

    # Settle: supersede ACTIVE estimate, create FINAL SETTLED quote.
    prior = active_quote_for_transaction(tid)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        repo.bump(prior)

    final_quote = repo.make_fee_quote(tid, "FINAL", sched["id"], components, "SETTLED")
    txn["active_quote_id"] = final_quote["id"]

    # Increment completed count, advance lifecycle, then reconcile balance.
    acct["ytd_completed_count"] = acct["ytd_completed_count"] + 1
    txn["lifecycle_status"] = "COMPLETED"
    repo.bump(txn)

    recompute_account_balance(acct)
    if acct["outstanding_balance_cents"] > acct["credit_limit_cents"]:
        acct["status"] = "SUSPENDED"
    repo.bump(acct)

    return success(transaction_out(txn), 200)


# ----------------------------------------------------------------------------
# Cancel (DRAFT/QUOTED/REJECTED -> CANCELLED; COMPLETED -> CANCELLED reversal)
# ----------------------------------------------------------------------------

@bp.route("/dmv/transactions/<tid>/cancel", methods=["POST"])
@require_roles("AccountHolder")
def cancel_transaction(tid):
    txn = _get_txn_or_404(tid)

    # Ownership (priority 4) before state.
    if g.user_id != txn["account_id"]:
        raise errors.not_resource_owner("AccountHolder must own the transaction")

    lifecycle = txn["lifecycle_status"]

    if lifecycle in ("DRAFT", "QUOTED", "REJECTED"):
        # Supersede ACTIVE quote; void DRAFT lien packets.
        aq = active_quote_for_transaction(tid)
        if aq is not None:
            aq["status"] = "SUPERSEDED"
            repo.bump(aq)
        for p in lien_packets_for_transaction(tid):
            if p["packet_status"] == "DRAFT":
                p["packet_status"] = "VOIDED"
                repo.bump(p)
        txn["lifecycle_status"] = "CANCELLED"
        repo.bump(txn)
        return success(transaction_out(txn), 200)

    if lifecycle == "COMPLETED":
        # Post-completion reversal requires a CHARGE payment to compensate
        # (priority 6).
        charge = None
        for p in db.payments.values():
            if p["transaction_id"] == tid and p["kind"] == "CHARGE":
                charge = p
                break
        if charge is None:
            raise errors.no_charge_to_refund("no CHARGE payment exists to compensate")

        acct = db.accounts.get(txn["account_id"])
        settled = settled_quote_for_transaction(tid)
        refund_amount = settled["total_cents"] if settled is not None else charge["amount_cents"]

        repo.make_payment(acct["id"], tid, refund_amount, "REFUND")

        # Decrement completed count, void PERFECTED lien packets, advance lifecycle.
        acct["ytd_completed_count"] = max(0, acct["ytd_completed_count"] - 1)
        for p in lien_packets_for_transaction(tid):
            if p["packet_status"] == "PERFECTED":
                p["packet_status"] = "VOIDED"
                repo.bump(p)
        txn["lifecycle_status"] = "CANCELLED"
        repo.bump(txn)

        recompute_account_balance(acct)
        repo.bump(acct)
        return success(transaction_out(txn), 200)

    # Any other lifecycle state is not cancellable.
    raise errors.invalid_state("transaction cannot be cancelled from its current state")


# ----------------------------------------------------------------------------
# Sub-collection list endpoints
# ----------------------------------------------------------------------------

@bp.route("/dmv/transactions/<tid>/fee-quotes", methods=["GET"])
@require_roles("PlatformAdmin", "FeeAnalyst", "AccountHolder")
def list_txn_quotes(tid):
    txn = _get_txn_or_404(tid)
    if g.user_role == "AccountHolder" and txn["account_id"] != g.user_id:
        raise errors.not_resource_owner("AccountHolder may only read own transactions")
    limit, offset = parse_pagination()
    items = quotes_for_transaction(tid)
    page, total = paginate(items, limit, offset)
    return list_success([fee_quote_out(q) for q in page], limit, offset, total)


@bp.route("/dmv/transactions/<tid>/documents", methods=["GET"])
@require_roles("PlatformAdmin", "FeeAnalyst", "IntakeClerk", "AccountHolder")
def list_txn_documents(tid):
    txn = _get_txn_or_404(tid)
    if g.user_role == "AccountHolder" and txn["account_id"] != g.user_id:
        raise errors.not_resource_owner("AccountHolder may only read own transactions")
    limit, offset = parse_pagination()
    items = documents_for_transaction(tid)
    page, total = paginate(items, limit, offset)
    return list_success([document_item_out(d) for d in page], limit, offset, total)


@bp.route("/dmv/transactions/<tid>/submissions", methods=["GET"])
@require_roles("PlatformAdmin", "FeeAnalyst", "IntakeClerk", "RunnerDispatcher")
def list_txn_submissions(tid):
    _get_txn_or_404(tid)
    limit, offset = parse_pagination()
    items = submissions_for_transaction(tid)
    page, total = paginate(items, limit, offset)
    return list_success([submission_out(s) for s in page], limit, offset, total)


@bp.route("/dmv/transactions/<tid>/lien-packets", methods=["GET"])
@require_roles("PlatformAdmin", "FeeAnalyst", "LienOfficer", "AccountHolder")
def list_txn_lien_packets(tid):
    txn = _get_txn_or_404(tid)
    if g.user_role == "AccountHolder" and txn["account_id"] != g.user_id:
        raise errors.not_resource_owner("AccountHolder may only read own transactions")
    limit, offset = parse_pagination()
    items = lien_packets_for_transaction(tid)
    page, total = paginate(items, limit, offset)
    return list_success([lien_packet_out(p) for p in page], limit, offset, total)
