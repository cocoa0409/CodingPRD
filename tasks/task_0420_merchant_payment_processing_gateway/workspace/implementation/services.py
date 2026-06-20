"""Business logic, state transitions, calculations.

Every behavior here traces to a verbatim PRD sentence (§3) and the scaffold
state-machine / calculation / validation tables.
"""
from decimal import Decimal

from db import store
from errors import err
import constants as C
from common import (
    base_record, touch, serialize,
    require_int, optional_int, require_str, optional_str, require_enum,
    validate_enum, is_four_digits,
    parse_iso8601, clock_now, clock_date, parse_date, add_days_to_date,
    post_ledger, recompute_balances, bps,
)


# ---------------------------------------------------------------------------
# Fee plans (PRD §3.1)
# ---------------------------------------------------------------------------
def create_fee_plan(body):
    name = require_str(body, "name")
    pricing_model = require_enum(body, "pricing_model")  # FLAT | INTERCHANGE_PLUS

    # Completeness check (ERR_FEE_PLAN_INCOMPLETE, 422). Judged on presence of
    # the fields the chosen model needs, not whether a value happens to be zero.
    if pricing_model == "FLAT":
        if "flat_pct_bps" not in body or body.get("flat_pct_bps") is None or \
           "flat_fixed_cents" not in body or body.get("flat_fixed_cents") is None:
            raise err("ERR_FEE_PLAN_INCOMPLETE",
                      "FLAT plan must provide flat_pct_bps and flat_fixed_cents")
    elif pricing_model == "INTERCHANGE_PLUS":
        if "markup_pct_bps" not in body or body.get("markup_pct_bps") is None or \
           "markup_fixed_cents" not in body or body.get("markup_fixed_cents") is None:
            raise err("ERR_FEE_PLAN_INCOMPLETE",
                      "INTERCHANGE_PLUS plan must provide markup_pct_bps and markup_fixed_cents")

    rec = base_record(common_fields=True)
    rec["name"] = name
    rec["pricing_model"] = pricing_model
    rec["flat_pct_bps"] = optional_int(body, "flat_pct_bps", 0)
    rec["flat_fixed_cents"] = optional_int(body, "flat_fixed_cents", 0)
    rec["markup_pct_bps"] = optional_int(body, "markup_pct_bps", 0)
    rec["markup_fixed_cents"] = optional_int(body, "markup_fixed_cents", 0)
    rec["volume_tier_threshold_cents"] = optional_int(body, "volume_tier_threshold_cents", 0)
    rec["discounted_markup_pct_bps"] = optional_int(body, "discounted_markup_pct_bps", 0)
    rec["chargeback_fee_cents"] = optional_int(body, "chargeback_fee_cents", 1500)
    store.fee_plans[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Merchant onboarding (PRD §3.2)
# ---------------------------------------------------------------------------
def register_merchant(body):
    legal_name = require_str(body, "legal_name")
    mcc = require_str(body, "mcc")
    if not is_four_digits(mcc):
        raise err("ERR_VALIDATION", "mcc must be exactly 4 ASCII digits")
    fee_plan_id = require_str(body, "fee_plan_id")
    requested = require_int(body, "requested_monthly_volume_cents", minimum=0)
    payout_method = require_enum(body, "payout_method", default="BANK_ACCOUNT")

    # FK existence: fee_plan_id must reference an existing fee plan (ERR_FK_NOT_FOUND).
    if fee_plan_id not in store.fee_plans:
        raise err("ERR_FK_NOT_FOUND", "fee_plan_id does not reference an existing fee plan")

    rec = base_record(common_fields=True)
    rec["legal_name"] = legal_name
    rec["mcc"] = mcc
    rec["fee_plan_id"] = fee_plan_id
    rec["onboarding_status"] = "PENDING_REVIEW"
    rec["risk_band"] = None
    rec["requested_monthly_volume_cents"] = requested
    rec["reserve_rate_bps"] = 0
    rec["funding_delay_days"] = 2
    rec["available_balance_cents"] = 0
    rec["reserved_balance_cents"] = 0
    rec["payout_method"] = payout_method
    store.merchants[rec["id"]] = rec

    # Side effect: open an OPEN RiskReview for the merchant.
    rr = base_record(common_fields=True)
    rr["merchant_id"] = rec["id"]
    rr["decision"] = "OPEN"
    rr["assigned_risk_band"] = None
    rr["notes"] = ""
    store.risk_reviews[rr["id"]] = rr
    return rec


def _open_review_exists(merchant_id):
    for rr in store.risk_reviews.values():
        if rr["merchant_id"] == merchant_id and rr["decision"] == "OPEN":
            return True
    return False


def approve_review(merchant, review, body):
    # Validation: assigned_risk_band required + enum-valid.
    assigned = require_enum(body, "assigned_risk_band")
    notes = optional_str(body, "notes", "")

    # State: merchant must be PENDING_REVIEW and an OPEN review must exist.
    if merchant["onboarding_status"] != "PENDING_REVIEW" or not _open_review_exists(merchant["id"]):
        raise err("ERR_INVALID_STATE", "Merchant is not in PENDING_REVIEW with an OPEN review")

    # Risk-band policy guard (fires only on approve).
    if merchant["mcc"] in C.HIGH_RISK_MCC_SET and assigned != "HIGH":
        raise err("ERR_RISK_BAND_POLICY_VIOLATION",
                  "High-risk MCC merchant must be assigned the HIGH risk band")

    merchant["onboarding_status"] = "APPROVED"
    merchant["risk_band"] = assigned
    merchant["reserve_rate_bps"] = C.RISK_BAND_RESERVE_BPS[assigned]
    merchant["funding_delay_days"] = C.RISK_BAND_FUNDING_DELAY[assigned]
    touch(merchant)  # increments Merchant.version by 1

    review["decision"] = "APPROVED"
    review["assigned_risk_band"] = assigned
    if notes:
        review["notes"] = notes
    touch(review)
    return merchant


def reject_review(merchant, review, body):
    notes = optional_str(body, "notes", "")
    if merchant["onboarding_status"] != "PENDING_REVIEW" or not _open_review_exists(merchant["id"]):
        raise err("ERR_INVALID_STATE", "Merchant is not in PENDING_REVIEW with an OPEN review")
    merchant["onboarding_status"] = "REJECTED"
    touch(merchant)
    review["decision"] = "REJECTED"
    if notes:
        review["notes"] = notes
    touch(review)
    return merchant


def suspend_merchant(merchant):
    if merchant["onboarding_status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Merchant must be APPROVED to suspend")
    merchant["onboarding_status"] = "SUSPENDED"
    touch(merchant)
    return merchant


def reinstate_merchant(merchant):
    if merchant["onboarding_status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Merchant must be SUSPENDED to reinstate")
    merchant["onboarding_status"] = "APPROVED"
    touch(merchant)
    return merchant


# ---------------------------------------------------------------------------
# Charges: authorize / capture / void (PRD §3.3, §3.4)
# ---------------------------------------------------------------------------
def authorize_charge(merchant, body):
    auth_amount = require_int(body, "auth_amount_cents", minimum=1)
    card_last4 = require_str(body, "card_last4")
    if not is_four_digits(card_last4):
        raise err("ERR_VALIDATION", "card_last4 must be exactly 4 ASCII digits")

    # Merchant must be APPROVED to authorize (ERR_MERCHANT_NOT_APPROVED, 409).
    if merchant["onboarding_status"] != "APPROVED":
        raise err("ERR_MERCHANT_NOT_APPROVED", "Merchant is not APPROVED")

    rec = base_record(common_fields=True)
    rec["merchant_id"] = merchant["id"]
    rec["auth_amount_cents"] = auth_amount
    rec["captured_amount_cents"] = 0
    rec["refunded_amount_cents"] = 0
    rec["processing_fee_cents"] = 0
    rec["auth_status"] = "AUTHORIZED"
    rec["settlement_status"] = "PENDING"
    rec["settlement_batch_id"] = None
    rec["card_last4"] = card_last4
    # internal: settle posting clock (set when this charge becomes SETTLED)
    rec["_settle_clock"] = None
    store.charges[rec["id"]] = rec
    return rec


def _compute_processing_fee(merchant, fee_plan, capture_amount):
    """processing_fee calc (PRD §3.4). Round-then-sum into whole cents."""
    base = capture_amount
    if fee_plan["pricing_model"] == "FLAT":
        pct = bps(base, fee_plan["flat_pct_bps"])
        return pct + fee_plan["flat_fixed_cents"]
    # INTERCHANGE_PLUS
    ic = bps(base, C.INTERCHANGE_BPS) + C.INTERCHANGE_FIXED_CENTS
    prior = _prior_month_settled(merchant, exclude_charge=None)
    if prior > fee_plan["volume_tier_threshold_cents"]:
        eff_markup_bps = fee_plan["discounted_markup_pct_bps"]
    else:
        eff_markup_bps = fee_plan["markup_pct_bps"]
    markup = bps(base, eff_markup_bps) + fee_plan["markup_fixed_cents"]
    return ic + markup


def _prior_month_settled(merchant, exclude_charge):
    """Sum captured_amount_cents over this merchant's SETTLED charges whose settle
    posting fell in the CURRENT calendar month, excluding the charge being
    captured. The charge being captured is not yet SETTLED so exclusion is moot,
    but kept explicit per PRD §3.4."""
    now = clock_now()
    cur_year, cur_month = now.year, now.month
    total = 0
    for c in store.charges.values():
        if c["merchant_id"] != merchant["id"]:
            continue
        if exclude_charge is not None and c["id"] == exclude_charge["id"]:
            continue
        if c["settlement_status"] != "SETTLED":
            continue
        sc = c.get("_settle_clock")
        if sc is None:
            continue
        if sc.year == cur_year and sc.month == cur_month:
            total += c["captured_amount_cents"]
    return total


def capture_charge(charge, body):
    amount = require_int(body, "amount_cents")
    merchant = store.merchants[charge["merchant_id"]]

    # State: auth_status must be AUTHORIZED (ERR_INVALID_STATE).
    if charge["auth_status"] != "AUTHORIZED":
        raise err("ERR_INVALID_STATE", "Charge is not AUTHORIZED")

    # Merchant must be APPROVED (ERR_MERCHANT_NOT_APPROVED, 409). [priority 7]
    if merchant["onboarding_status"] != "APPROVED":
        raise err("ERR_MERCHANT_NOT_APPROVED", "Merchant is not APPROVED")

    # Capture amount must be 1..auth_amount_cents (ERR_CAPTURE_EXCEEDS_AUTH, 422).
    if amount < 1 or amount > charge["auth_amount_cents"]:
        raise err("ERR_CAPTURE_EXCEEDS_AUTH",
                  "Capture amount must be between 1 and the authorized amount")

    fee_plan = store.fee_plans[merchant["fee_plan_id"]]
    charge["captured_amount_cents"] = amount
    charge["processing_fee_cents"] = _compute_processing_fee(merchant, fee_plan, amount)
    charge["auth_status"] = "CAPTURED"
    # settlement_status stays PENDING; NO ledger posting at capture.
    touch(charge)
    return charge


def void_charge(charge):
    if charge["auth_status"] != "AUTHORIZED":
        raise err("ERR_INVALID_STATE", "Charge is not AUTHORIZED")
    charge["auth_status"] = "VOIDED"
    touch(charge)
    return charge


# ---------------------------------------------------------------------------
# Refunds (PRD §3.5)
# ---------------------------------------------------------------------------
def _has_nonterminal_dispute(charge_id):
    nonterminal = {"OPEN", "UNDER_REVIEW", "REPRESENTED"}
    for d in store.disputes.values():
        if d["charge_id"] == charge_id and d["dispute_status"] in nonterminal:
            return True
    return False


def create_refund(charge, body):
    amount = require_int(body, "amount_cents", minimum=1)
    reason = require_enum(body, "reason", default="REQUESTED_BY_CUSTOMER")

    # State: charge must be CAPTURED (ERR_INVALID_STATE).
    if charge["auth_status"] != "CAPTURED":
        raise err("ERR_INVALID_STATE", "Charge is not CAPTURED")

    # Business referential: blocked by a live dispute (ERR_REFUND_BLOCKED_BY_DISPUTE, 409). [priority 12]
    if _has_nonterminal_dispute(charge["id"]):
        raise err("ERR_REFUND_BLOCKED_BY_DISPUTE",
                  "A non-terminal dispute exists on the charge")

    # Business fiscal: cumulative refunds must not exceed captured (ERR_REFUND_EXCEEDS_CAPTURED, 422). [priority 16]
    if charge["refunded_amount_cents"] + amount > charge["captured_amount_cents"]:
        raise err("ERR_REFUND_EXCEEDS_CAPTURED",
                  "Cumulative refunded amount would exceed captured amount")

    rec = base_record(common_fields=True)
    rec["charge_id"] = charge["id"]
    rec["amount_cents"] = amount
    rec["refund_status"] = "PENDING"
    rec["reason"] = reason
    rec["_settle_date"] = None  # internal: clock date at settle
    store.refunds[rec["id"]] = rec

    charge["refunded_amount_cents"] += amount
    touch(charge)
    return rec


def settle_refund(refund):
    if refund["refund_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Refund is not PENDING")
    charge = store.charges[refund["charge_id"]]
    merchant = store.merchants[charge["merchant_id"]]
    refund["refund_status"] = "SETTLED"
    refund["_settle_date"] = clock_date().isoformat()
    touch(refund)
    post_ledger(merchant["id"], "AVAILABLE", -refund["amount_cents"],
                "REFUND", "REFUND", refund["id"])
    recompute_balances(merchant)
    return refund


def fail_refund(refund):
    if refund["refund_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Refund is not PENDING")
    charge = store.charges[refund["charge_id"]]
    refund["refund_status"] = "FAILED"
    touch(refund)
    # compensation: restore refundable headroom
    charge["refunded_amount_cents"] -= refund["amount_cents"]
    touch(charge)
    return refund


# ---------------------------------------------------------------------------
# Disputes (PRD §3.6)
# ---------------------------------------------------------------------------
def open_dispute(charge, body):
    disputed = require_int(body, "disputed_amount_cents", minimum=1)
    merchant = store.merchants[charge["merchant_id"]]

    # State: charge CAPTURED + SETTLED, and no non-terminal dispute (ERR_INVALID_STATE).
    if charge["auth_status"] != "CAPTURED" or charge["settlement_status"] != "SETTLED":
        raise err("ERR_INVALID_STATE", "Charge is not CAPTURED/SETTLED")
    if _has_nonterminal_dispute(charge["id"]):
        raise err("ERR_INVALID_STATE", "A non-terminal dispute already exists on the charge")

    # Business referential: disputed amount must equal net captured (ERR_DISPUTE_AMOUNT_MISMATCH, 422). [priority 13]
    net_captured = charge["captured_amount_cents"] - charge["refunded_amount_cents"]
    if disputed != net_captured:
        raise err("ERR_DISPUTE_AMOUNT_MISMATCH",
                  "disputed_amount_cents must equal net captured amount")

    fee_plan = store.fee_plans[merchant["fee_plan_id"]]
    rec = base_record(common_fields=True)
    rec["charge_id"] = charge["id"]
    rec["disputed_amount_cents"] = disputed
    rec["dispute_status"] = "OPEN"
    rec["representment_round"] = 0
    rec["evidence_due_at"] = _due_at_from_now()
    rec["chargeback_fee_cents"] = fee_plan["chargeback_fee_cents"]
    store.disputes[rec["id"]] = rec

    # Ledger debits: CHARGEBACK (-disputed) and FEE (-chargeback_fee), both DISPUTE.
    post_ledger(merchant["id"], "AVAILABLE", -disputed,
                "CHARGEBACK", "DISPUTE", rec["id"])
    post_ledger(merchant["id"], "AVAILABLE", -rec["chargeback_fee_cents"],
                "FEE", "DISPUTE", rec["id"])

    # Full net disputed => charge settlement_status SETTLED -> REVERSED.
    charge["settlement_status"] = "REVERSED"
    touch(charge)

    recompute_balances(merchant)
    return rec


def _due_at_from_now():
    from datetime import timedelta
    due = clock_now() + timedelta(days=C.EVIDENCE_WINDOW_DAYS)
    return due.strftime("%Y-%m-%dT%H:%M:%S.") + f"{due.microsecond // 1000:03d}Z"


def acknowledge_dispute(dispute):
    if dispute["dispute_status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Dispute is not OPEN")
    dispute["dispute_status"] = "UNDER_REVIEW"
    touch(dispute)
    return dispute


def represent_dispute(dispute):
    # State: must be UNDER_REVIEW (ERR_INVALID_STATE).
    if dispute["dispute_status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Dispute is not UNDER_REVIEW")
    # Evidence window check precedes round-limit check (PRD §3.6).
    due = parse_iso8601(dispute["evidence_due_at"])
    if clock_now() > due:
        raise err("ERR_EVIDENCE_WINDOW_CLOSED", "Evidence window has closed")
    if dispute["representment_round"] >= C.MAX_REPRESENTMENT_ROUNDS:
        raise err("ERR_REPRESENTMENT_LIMIT_REACHED", "Representment limit reached")
    dispute["representment_round"] += 1
    dispute["dispute_status"] = "REPRESENTED"
    touch(dispute)
    return dispute


def reopen_dispute(dispute):
    if dispute["dispute_status"] != "REPRESENTED":
        raise err("ERR_INVALID_STATE", "Dispute is not REPRESENTED")
    if dispute["representment_round"] >= C.MAX_REPRESENTMENT_ROUNDS:
        raise err("ERR_INVALID_STATE", "Representment round limit reached")
    dispute["dispute_status"] = "UNDER_REVIEW"
    # extend evidence_due_at by another EVIDENCE_WINDOW_DAYS
    from datetime import timedelta
    cur = parse_iso8601(dispute["evidence_due_at"]) + timedelta(days=C.EVIDENCE_WINDOW_DAYS)
    dispute["evidence_due_at"] = cur.strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{cur.microsecond // 1000:03d}Z"
    touch(dispute)
    return dispute


def resolve_dispute(dispute, body):
    outcome = require_str(body, "outcome")
    if outcome not in ("WON", "LOST"):
        raise err("ERR_RESOLVE_OUTCOME_INVALID", "outcome must be WON or LOST")
    if dispute["dispute_status"] != "REPRESENTED":
        raise err("ERR_INVALID_STATE", "Dispute is not REPRESENTED")

    charge = store.charges[dispute["charge_id"]]
    merchant = store.merchants[charge["merchant_id"]]

    if outcome == "WON":
        dispute["dispute_status"] = "WON"
        touch(dispute)
        # credit back ONLY the disputed amount; fee retained.
        post_ledger(merchant["id"], "AVAILABLE", dispute["disputed_amount_cents"],
                    "CHARGEBACK_REVERSAL", "DISPUTE", dispute["id"])
        if charge["settlement_status"] == "REVERSED":
            charge["settlement_status"] = "SETTLED"
            touch(charge)
        recompute_balances(merchant)
    else:  # LOST
        dispute["dispute_status"] = "LOST"
        touch(dispute)
        # no further ledger postings; chargeback debit retained.
    return dispute


def accept_dispute(dispute):
    if dispute["dispute_status"] not in ("OPEN", "UNDER_REVIEW"):
        raise err("ERR_INVALID_STATE", "Dispute is not OPEN or UNDER_REVIEW")
    dispute["dispute_status"] = "ACCEPTED"
    touch(dispute)
    return dispute


# ---------------------------------------------------------------------------
# Settlement batches (PRD §3.7, §3.8)
# ---------------------------------------------------------------------------
def open_batch(merchant, body):
    business_date = require_str(body, "business_date")
    parse_date(business_date, "business_date")  # validate format

    # State: merchant APPROVED or SUSPENDED.
    if merchant["onboarding_status"] not in ("APPROVED", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Merchant must be APPROVED or SUSPENDED")

    eligible = [c for c in store.charges.values()
                if c["merchant_id"] == merchant["id"]
                and c["auth_status"] == "CAPTURED"
                and c["settlement_status"] == "PENDING"]
    if not eligible:
        raise err("ERR_NO_ELIGIBLE_CHARGES",
                  "No CAPTURED/PENDING charges eligible for this batch")

    rec = base_record(common_fields=True)
    rec["merchant_id"] = merchant["id"]
    rec["business_date"] = business_date
    rec["batch_status"] = "OPEN"
    rec["gross_captured_cents"] = 0
    rec["total_fees_cents"] = 0
    rec["total_refunds_cents"] = 0
    rec["reserve_held_cents"] = 0
    rec["net_funding_cents"] = 0
    store.settlement_batches[rec["id"]] = rec

    # Sweep eligible charges: PENDING -> BATCHED, set settlement_batch_id.
    for c in sorted(eligible, key=lambda x: x["_seq"]):
        c["settlement_status"] = "BATCHED"
        c["settlement_batch_id"] = rec["id"]
        touch(c)
    return rec


def settle_batch(batch, body):
    expected = require_int(body, "expected_merchant_version")
    merchant = store.merchants[batch["merchant_id"]]

    # State: batch must be OPEN (ERR_INVALID_STATE).
    if batch["batch_status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Batch is not OPEN")

    # OCC: expected_merchant_version must equal current version (ERR_STALE_MERCHANT_VERSION, 412). [priority 18]
    if expected != merchant["version"]:
        raise err("ERR_STALE_MERCHANT_VERSION",
                  "expected_merchant_version does not match current merchant version")

    # Cascade hop 1: batched charges BATCHED -> SETTLED.
    batched = [c for c in store.charges.values()
               if c["settlement_batch_id"] == batch["id"]
               and c["settlement_status"] == "BATCHED"]
    settle_clock = clock_now()
    for c in sorted(batched, key=lambda x: x["_seq"]):
        c["settlement_status"] = "SETTLED"
        c["_settle_clock"] = settle_clock
        touch(c)

    # Pin aggregates (settlement_summary calc).
    batch_charges = [c for c in store.charges.values()
                     if c["settlement_batch_id"] == batch["id"]]
    gross = sum(c["captured_amount_cents"] for c in batch_charges)
    fees = sum(c["processing_fee_cents"] for c in batch_charges)

    # Refunds: SETTLED, on charges in this batch, settle_date <= business_date;
    # accumulated in ascending created_at order for determinism.
    bdate = parse_date(batch["business_date"], "business_date")
    refunds_in = []
    batch_charge_ids = {c["id"] for c in batch_charges}
    for r in store.refunds.values():
        if r["refund_status"] != "SETTLED":
            continue
        if r["charge_id"] not in batch_charge_ids:
            continue
        if r.get("_settle_date") is None:
            continue
        if parse_date(r["_settle_date"], "_settle_date") <= bdate:
            refunds_in.append(r)
    refunds_in.sort(key=lambda x: x["_seq"])
    total_refunds = sum(r["amount_cents"] for r in refunds_in)

    # Reserve: sum-then-round once on the aggregate.
    reserve_held = bps(gross, merchant["reserve_rate_bps"])
    net_funding = gross - fees - total_refunds - reserve_held

    batch["gross_captured_cents"] = gross
    batch["total_fees_cents"] = fees
    batch["total_refunds_cents"] = total_refunds
    batch["reserve_held_cents"] = reserve_held
    batch["net_funding_cents"] = net_funding
    batch["batch_status"] = "SETTLED"
    touch(batch)

    # Cascade hop 2: create ReserveEntry HELD.
    release_date = add_days_to_date(bdate, C.RESERVE_HOLD_DAYS).isoformat()
    re = base_record(common_fields=True)
    re["merchant_id"] = merchant["id"]
    re["settlement_batch_id"] = batch["id"]
    re["amount_cents"] = reserve_held
    re["release_date"] = release_date
    re["reserve_status"] = "HELD"
    store.reserve_entries[re["id"]] = re

    # Cascade hop 3: post RESERVE_HOLD ledger entry (RESERVE account, +reserve).
    post_ledger(merchant["id"], "RESERVE", reserve_held,
                "RESERVE_HOLD", "RESERVE_ENTRY", re["id"])

    # increments Merchant.version by 1 (settle action). recompute_balances also
    # bumps version; the settle pins reserve terms and bumps version per §2.10.
    touch(merchant)
    recompute_balances(merchant)
    return batch


def fund_batch(batch):
    merchant = store.merchants[batch["merchant_id"]]
    # State: batch must be SETTLED (ERR_INVALID_STATE).
    if batch["batch_status"] != "SETTLED":
        raise err("ERR_INVALID_STATE", "Batch is not SETTLED")
    # Temporal: clock date >= business_date + funding_delay_days (ERR_FUNDING_DATE_NOT_REACHED, 409). [priority 14]
    bdate = parse_date(batch["business_date"], "business_date")
    maturity = add_days_to_date(bdate, merchant["funding_delay_days"])
    if clock_date() < maturity:
        raise err("ERR_FUNDING_DATE_NOT_REACHED", "Funding maturity not yet reached")

    batch["batch_status"] = "FUNDED"
    touch(batch)
    post_ledger(merchant["id"], "AVAILABLE", batch["net_funding_cents"],
                "FUNDING", "SETTLEMENT_BATCH", batch["id"])
    recompute_balances(merchant)
    return batch


# ---------------------------------------------------------------------------
# Reserve release sweep (PRD §3.9)
# ---------------------------------------------------------------------------
def reserve_release_sweep(merchant):
    today = clock_date()
    eligible = [r for r in store.reserve_entries.values()
                if r["merchant_id"] == merchant["id"]
                and r["reserve_status"] == "HELD"
                and parse_date(r["release_date"], "release_date") <= today]
    released = []
    for re in sorted(eligible, key=lambda x: x["_seq"]):
        re["reserve_status"] = "RELEASED"
        touch(re)
        post_ledger(merchant["id"], "RESERVE", -re["amount_cents"],
                    "RESERVE_RELEASE", "RESERVE_ENTRY", re["id"])
        post_ledger(merchant["id"], "AVAILABLE", re["amount_cents"],
                    "ADJUSTMENT", "RESERVE_ENTRY", re["id"])
        released.append(re)
    if released:
        recompute_balances(merchant)
    return released


# ---------------------------------------------------------------------------
# Payouts (PRD §3.10)
# ---------------------------------------------------------------------------
def request_payout(merchant, body):
    amount = require_int(body, "amount_cents", minimum=1)
    scheduled_for = require_str(body, "scheduled_for")
    parse_date(scheduled_for, "scheduled_for")

    # State: merchant must be APPROVED (ERR_MERCHANT_NOT_APPROVED, 409). [priority 7]
    if merchant["onboarding_status"] != "APPROVED":
        raise err("ERR_MERCHANT_NOT_APPROVED", "Merchant is not APPROVED")

    # Business fiscal: amount must not exceed available balance (ERR_INSUFFICIENT_BALANCE, 422). [priority 17]
    if amount > merchant["available_balance_cents"]:
        raise err("ERR_INSUFFICIENT_BALANCE", "Payout amount exceeds available balance")

    rec = base_record(common_fields=True)
    rec["merchant_id"] = merchant["id"]
    rec["amount_cents"] = amount
    rec["payout_status"] = "REQUESTED"
    rec["scheduled_for"] = scheduled_for
    store.payouts[rec["id"]] = rec

    post_ledger(merchant["id"], "AVAILABLE", -amount, "PAYOUT", "PAYOUT", rec["id"])
    recompute_balances(merchant)
    return rec


def mark_payout_paid(payout):
    if payout["payout_status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Payout is not REQUESTED")
    sched = parse_date(payout["scheduled_for"], "scheduled_for")
    if clock_date() < sched:
        raise err("ERR_PAYOUT_DATE_NOT_REACHED", "Payout scheduled date not yet reached")
    payout["payout_status"] = "PAID"
    touch(payout)
    return payout


def return_payout(payout):
    if payout["payout_status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Payout is not REQUESTED")
    merchant = store.merchants[payout["merchant_id"]]
    payout["payout_status"] = "RETURNED"
    touch(payout)
    post_ledger(merchant["id"], "AVAILABLE", payout["amount_cents"],
                "PAYOUT_RETURN", "PAYOUT", payout["id"])
    recompute_balances(merchant)
    return payout


# ---------------------------------------------------------------------------
# Tax 1099-K (PRD §3.11)
# ---------------------------------------------------------------------------
def generate_tax(merchant, body):
    tax_year = require_int(body, "tax_year")
    included = []
    for c in store.charges.values():
        if c["merchant_id"] != merchant["id"]:
            continue
        if c["settlement_status"] != "SETTLED":
            continue
        sc = c.get("_settle_clock")
        if sc is None:
            continue
        if sc.year == tax_year:
            included.append(c)
    gross = sum(c["captured_amount_cents"] for c in included)
    count = len(included)
    reportable = gross > C.REPORTING_THRESHOLD_CENTS

    rec = base_record(common_fields=True)
    rec["merchant_id"] = merchant["id"]
    rec["tax_year"] = tax_year
    rec["gross_amount_cents"] = gross
    rec["transaction_count"] = count
    rec["reportable"] = reportable
    store.tax_1099k[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Webhooks (PRD §3.11)
# ---------------------------------------------------------------------------
def emit_webhook(merchant, body):
    event_type = require_enum(body, "event_type")
    source_id = require_str(body, "source_id")
    idempotency_key = require_str(body, "idempotency_key")

    # Idempotent on key, scoped to this merchant.
    for e in store.webhook_events.values():
        if e["merchant_id"] == merchant["id"] and e["idempotency_key"] == idempotency_key:
            return e, False

    rec = base_record(common_fields=False)
    rec["merchant_id"] = merchant["id"]
    rec["event_type"] = event_type
    rec["source_id"] = source_id
    rec["idempotency_key"] = idempotency_key
    store.webhook_events[rec["id"]] = rec
    return rec, True


# ---------------------------------------------------------------------------
# Logical clock (PRD §3.12)
# ---------------------------------------------------------------------------
def clock_set(body):
    to = require_str(body, "to_iso8601")
    store.clock = parse_iso8601(to)


def clock_advance(body):
    to = require_str(body, "to_iso8601")
    store.clock = parse_iso8601(to)
    _auth_expiry_sweep()


def _auth_expiry_sweep():
    """Move AUTHORIZED charges older than AUTH_HOLD_DAYS to EXPIRED."""
    today = clock_date()
    for c in store.charges.values():
        if c["auth_status"] != "AUTHORIZED":
            continue
        created = parse_iso8601(c["created_at"]).date()
        if today >= add_days_to_date(created, C.AUTH_HOLD_DAYS):
            c["auth_status"] = "EXPIRED"
            touch(c)
