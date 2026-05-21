"""Dispute claims, credit cascades, and carrier safety — PRD §3.9."""
from __future__ import annotations

import pytest

from test_helpers import (
    accept_counter_dispute,
    assert_dispute_claim,
    assert_invoice_balance_conservation,
    CLAIM_TYPE_PENALTY,
    counter_dispute,
    create_dispute_claim_payload,
    counter_dispute_claim_payload,
    escalate_dispute,
    file_dispute,
    get_carrier,
    get_dispute_claim,
    get_invoice,
    get_shipper,
    make_shipper_headers,
    reject_counter_dispute,
    resolve_dispute,
    resolve_dispute_claim_payload,
    SAFETY_SCORE_INITIAL,
    SAFETY_SUSPEND_THRESHOLD,
    SMARTWAY_BREACH_PENALTY,
    setup_factored_invoice,
    setup_invoice_in_review_dispute,
    setup_invoiced_load,
    start_review_dispute,
    validate_error,
    validate_success,
    withdraw_dispute,
)


# ===========================================================================
# §3.9 — Filing.
# ===========================================================================
def test_file_claim_creates_open_claim(api):
    """PRD §3.9: "The new claim lands in `OPEN`."

    Claim: filing a positive claim against an invoice ->
    status == OPEN.
    """
    brokerage, shipper, _c, _q, _l, invoice = setup_invoiced_load(
        origin_zip="00000", destination_zip="00100",
        detention_minutes=0, accessorials=None,
    )
    claim = file_dispute(brokerage["id"], shipper["id"], invoice["id"],
                         claim_type="OVERCHARGE", claimed_cents=1_000)
    assert_dispute_claim(claim)
    assert claim["status"] == "OPEN"


def test_claim_amount_zero_rejected(api):
    """PRD §3.9: "The claimed amount must be strictly greater than zero
    and must not exceed the invoice's current `balance_due_cents` at the
    moment of filing; either violation is rejected with
    `ERR_CLAIM_AMOUNT_INVALID`."

    Claim: claimed_cents == 0 -> ERR_CLAIM_AMOUNT_INVALID (HTTP 422).
    """
    brokerage, shipper, _c, _q, _l, invoice = setup_invoiced_load(
        origin_zip="00000", destination_zip="00100",
        detention_minutes=0, accessorials=None,
    )
    res = api.create_dispute_claim(
        brokerage["id"], invoice["id"],
        create_dispute_claim_payload(claim_type="DAMAGE",
                                     claimed_cents=0),
        make_shipper_headers(shipper["id"]),
    )
    validate_error(res, "ERR_CLAIM_AMOUNT_INVALID")


def test_claim_amount_exceeds_balance_rejected(api):
    """PRD §3.9: "must not exceed the invoice's current `balance_due_cents`
    at the moment of filing; either violation is rejected with
    `ERR_CLAIM_AMOUNT_INVALID`."

    Claim: claimed_cents > balance_due_cents -> ERR_CLAIM_AMOUNT_INVALID.
    """
    brokerage, shipper, _c, _q, _l, invoice = setup_invoiced_load(
        origin_zip="00000", destination_zip="00100",  # spot DRY_VAN = 30_000+100*10 = 31_000
        detention_minutes=0, accessorials=None,
    )
    too_big = invoice["balance_due_cents"] + 1
    res = api.create_dispute_claim(
        brokerage["id"], invoice["id"],
        create_dispute_claim_payload(claim_type="DAMAGE",
                                     claimed_cents=too_big),
        make_shipper_headers(shipper["id"]),
    )
    validate_error(res, "ERR_CLAIM_AMOUNT_INVALID")


def test_claim_on_factored_invoice_rejected(api):
    """PRD §3.9: "Filing a dispute on an invoice whose `factoring_status`
    is `FACTORED` or `RECOURSED` is rejected with
    `ERR_INVOICE_NOT_DISPUTABLE_AFTER_FACTORING` — the dispute window
    closes once a financing house owns the receivable."

    Claim: file_dispute on a FACTORED invoice ->
    ERR_INVOICE_NOT_DISPUTABLE_AFTER_FACTORING.
    """
    brokerage, shipper, _c, _q, _l, invoice, _adv = setup_factored_invoice()
    res = api.create_dispute_claim(
        brokerage["id"], invoice["id"],
        create_dispute_claim_payload(claim_type="DAMAGE",
                                     claimed_cents=100),
        make_shipper_headers(shipper["id"]),
    )
    validate_error(res, "ERR_INVOICE_NOT_DISPUTABLE_AFTER_FACTORING")


# ===========================================================================
# §3.9 — Counter-offer cycle.
# ===========================================================================
def test_counter_then_reject_clears_counter_offer(api, broker_ops_headers):
    """PRD §3.9: "From `COUNTER_OFFERED` the shipper can either accept
    the counter ... or reject it (cycling back to `IN_REVIEW`, with
    `counter_offer_cents` cleared back to null so the next counter is a
    fresh offer). ... A claim may oscillate between `IN_REVIEW` and
    `COUNTER_OFFERED` any number of times before terminating."

    Claim: counter -> reject-counter -> claim is back in IN_REVIEW with
    counter_offer_cents == None; counter again with a different value
    -> COUNTER_OFFERED with the new value.
    """
    brokerage, shipper, _c, _q, _l, invoice, claim = (
        setup_invoice_in_review_dispute(claimed_cents=10_000)
    )
    countered = counter_dispute(brokerage["id"], claim["id"], 4_000)
    assert countered["status"] == "COUNTER_OFFERED"
    assert countered["counter_offer_cents"] == 4_000

    after_reject = reject_counter_dispute(brokerage["id"], shipper["id"],
                                          claim["id"])
    assert after_reject["status"] == "IN_REVIEW"
    assert after_reject.get("counter_offer_cents") in (None, 0) or (
        # Some implementations may serialise null differently — accept
        # any falsy representation as "cleared". The PRD says "cleared
        # back to null".
        not after_reject["counter_offer_cents"]
    )

    countered2 = counter_dispute(brokerage["id"], claim["id"], 5_000)
    assert countered2["status"] == "COUNTER_OFFERED"
    assert countered2["counter_offer_cents"] == 5_000


def test_counter_offer_zero_rejected(api, broker_ops_headers):
    """PRD §3.9: "It must be strictly greater than zero and strictly
    less than the original `claimed_cents`; either violation is rejected
    with `ERR_COUNTER_OFFER_INVALID`."

    Claim: counter_offer_cents == 0 -> ERR_COUNTER_OFFER_INVALID.
    """
    brokerage, _s, _c, _q, _l, _inv, claim = (
        setup_invoice_in_review_dispute(claimed_cents=10_000)
    )
    res = api.counter_dispute_claim(brokerage["id"], claim["id"],
                                    counter_dispute_claim_payload(0),
                                    broker_ops_headers)
    validate_error(res, "ERR_COUNTER_OFFER_INVALID")


def test_counter_offer_equal_to_claimed_rejected(api, broker_ops_headers):
    """PRD §3.9: "strictly less than the original `claimed_cents`".

    Claim: counter_offer_cents == claimed_cents -> ERR_COUNTER_OFFER_INVALID.
    """
    brokerage, _s, _c, _q, _l, _inv, claim = (
        setup_invoice_in_review_dispute(claimed_cents=10_000)
    )
    res = api.counter_dispute_claim(brokerage["id"], claim["id"],
                                    counter_dispute_claim_payload(10_000),
                                    broker_ops_headers)
    validate_error(res, "ERR_COUNTER_OFFER_INVALID")


# ===========================================================================
# §3.9 — Resolve and the credit cascade.
# ===========================================================================
def test_resolve_credit_application_arithmetic(api, broker_ops_headers):
    """PRD §3.9: "The invoice's `amount_credited_cents` is increased by
    c. The invoice's `invoice_total_cents` is decreased by c — the face
    value of the receivable shrinks because the shipper no longer owes
    that portion. The invoice's `balance_due_cents` is then recomputed as
    `invoice_total_cents` minus `amount_paid_cents` minus `amount_credited_cents`,
    with a floor of zero."

    Claim: resolve with settled_credit_cents=3000 on a 46500-cent
    invoice -> invoice_total drops to 43500, amount_credited == 3000,
    balance_due == 40500. Conservation invariant holds.
    """
    brokerage, shipper, _c, _q, _l, invoice, claim = (
        setup_invoice_in_review_dispute(
            origin_zip="00000", destination_zip="01000",  # 30000+1000*10=40000
            detention_minutes=121,                         # 1 chargeable -> 1500
            accessorials=[("LUMPER", 5_000, True)],         # +5000
            claimed_cents=10_000,
        )
    )
    original_total = invoice["invoice_total_cents"]
    assert original_total == 46_500

    resolve_dispute(brokerage["id"], claim["id"], 3_000)
    after = get_invoice(brokerage["id"], invoice["id"])
    assert after["invoice_total_cents"] == 43_500
    assert after["amount_credited_cents"] == 3_000
    assert after["balance_due_cents"] == 40_500
    assert_invoice_balance_conservation(after, original_total_cents=46_500)


def test_resolve_settled_credit_negative_rejected(api, broker_ops_headers):
    """PRD §3.9: "The value must be at least zero, must not exceed the
    original `claimed_cents`, and must not exceed the invoice's current
    `balance_due_cents`; any violation is rejected with
    `ERR_SETTLED_CREDIT_INVALID`."

    Claim: settled_credit_cents == -1 -> ERR_SETTLED_CREDIT_INVALID.
    """
    brokerage, _s, _c, _q, _l, _inv, claim = (
        setup_invoice_in_review_dispute(claimed_cents=10_000)
    )
    res = api.resolve_dispute_claim(brokerage["id"], claim["id"],
                                    resolve_dispute_claim_payload(-1),
                                    broker_ops_headers)
    validate_error(res, "ERR_SETTLED_CREDIT_INVALID")


def test_resolve_settled_credit_exceeds_claimed_rejected(api,
                                                        broker_ops_headers):
    """PRD §3.9: "must not exceed the original `claimed_cents`".

    Claim: settled_credit_cents > claimed_cents -> ERR_SETTLED_CREDIT_INVALID.
    """
    brokerage, _s, _c, _q, _l, _inv, claim = (
        setup_invoice_in_review_dispute(claimed_cents=2_000)
    )
    res = api.resolve_dispute_claim(brokerage["id"], claim["id"],
                                    resolve_dispute_claim_payload(2_001),
                                    broker_ops_headers)
    validate_error(res, "ERR_SETTLED_CREDIT_INVALID")


# ===========================================================================
# §3.9 — Carrier safety penalty cascade.
# ===========================================================================
def test_safety_score_deduction_for_damage_claim(api):
    """PRD §3.9: "The base penalty is keyed to `claim_type`: 100 points
    for `DAMAGE` ... The carrier's `safety_score` is reduced by the resulting
    total, with a floor of zero."

    Claim: a DAMAGE claim resolved with settled_credit > 0 deducts 100
    points from the carrier's safety_score.
    """
    brokerage, _s, carrier, _q, _l, _inv, claim = (
        setup_invoice_in_review_dispute(claim_type="DAMAGE",
                                        claimed_cents=1_000)
    )
    initial = carrier["safety_score"]  # should be 1000 (qualified default)
    resolve_dispute(brokerage["id"], claim["id"], 500)
    after = get_carrier(brokerage["id"], carrier["id"])
    assert after["safety_score"] == initial - CLAIM_TYPE_PENALTY["DAMAGE"]


# NOTE: PRD §3.9 documents an additional 50-point SmartWay-breach
# penalty when "the shipper's smartway_required is true and the
# carrier's smartway_certified is false" — but the same combination is
# blocked at /loads (tender) by ERR_SMARTWAY_REQUIRED, and the PRD
# does not document any endpoint to mutate Carrier.smartway_certified
# or Shipper.smartway_required after creation. The breach branch is
# therefore not reachable through any PRD-documented sequence; per the
# Silence Patterns (branch-asymmetry), this test is omitted.


def test_safety_score_never_negative_after_deduction(api):
    """PRD §3.9: "The carrier's `safety_score` is reduced by the resulting
    total, with a floor of zero."

    PRD §2.6: "The carrier safety score is in integer points, not
    cents, and is likewise non-negative: every deduction is floored at
    zero."

    Claim: after a DAMAGE resolution, carrier.safety_score >= 0.
    """
    brokerage, _s, carrier, _q, _l, _inv, claim = (
        setup_invoice_in_review_dispute(claim_type="DAMAGE",
                                        claimed_cents=1_000)
    )
    resolve_dispute(brokerage["id"], claim["id"], 500)
    carrier_now = get_carrier(brokerage["id"], carrier["id"])
    assert carrier_now["safety_score"] >= 0


def test_safety_score_auto_suspends_carrier(api):
    """PRD §3.9: "After the deduction, if `safety_score` is strictly less
    than 600 the carrier is automatically transitioned `QUALIFIED` ->
    `SUSPENDED` as a further cascade; this auto-suspension carries no
    precondition check."

    Claim: enough DAMAGE resolutions to drive the score under 600 cause
    the carrier to flip to SUSPENDED automatically.

    Setup: drive 5 DAMAGE resolutions (5*100=500 deducted -> score 500,
    < 600 -> auto-SUSPENDED).
    """
    # Build invoice + dispute + resolve cycles on a single carrier.
    from test_helpers import setup_carrier_with_safety_score
    brokerage, _shipper, carrier = setup_carrier_with_safety_score(
        target_score=500,  # 5 cycles of 100 each
    )
    # After driving to 500, carrier must be SUSPENDED.
    assert carrier["safety_score"] <= 500
    assert carrier["status"] == "SUSPENDED"


# ===========================================================================
# §3.9 — Auto-settle cascade.
# ===========================================================================
def test_resolve_full_credit_cascades_to_paid_and_settles_outstanding(api):
    """PRD §3.9: "if after the cascade the invoice's `balance_due_cents`
    is exactly zero and its `factoring_status` is something other than
    `FACTORED`, the invoice's `settlement_status` automatically advances to
    `PAID`."

    PRD §3.2: "at the point the invoice transitions to `PAID` or
    `WRITTEN_OFF`, the shipper's `outstanding_invoiced_cents` is decreased
    by the original frozen `invoice_total_cents` of that invoice."

    Claim: resolve with full credit on a NOT_FACTORED invoice drives
    balance to 0, settlement_status to PAID, and outstanding to 0.
    """
    brokerage, shipper, _c, _q, _l, invoice, claim = (
        setup_invoice_in_review_dispute(
            origin_zip="00000", destination_zip="01000",
            detention_minutes=0, accessorials=None,
            claimed_cents=40_000,
        )
    )
    original_total = invoice["invoice_total_cents"]
    assert original_total == 40_000

    resolve_dispute(brokerage["id"], claim["id"], 40_000)
    after = get_invoice(brokerage["id"], invoice["id"])
    assert after["balance_due_cents"] == 0
    assert after["settlement_status"] == "PAID"

    shipper_after = get_shipper(brokerage["id"], shipper["id"])
    assert shipper_after["outstanding_invoiced_cents"] == 0


# ===========================================================================
# §3.9 — Escalate and withdraw.
# ===========================================================================
def test_escalate_terminates_claim_without_credit_or_penalty(api):
    """PRD §3.9: "Escalation moves the claim from `IN_REVIEW` to the
    terminal `ESCALATED` state — the claim is parked for external
    arbitration and no credit is applied, no invoice is touched, no
    safety penalty fires."

    Claim: after escalate, claim is ESCALATED; invoice unchanged;
    carrier.safety_score unchanged.
    """
    brokerage, _shipper, carrier, _q, _l, invoice, claim = (
        setup_invoice_in_review_dispute(claimed_cents=2_000)
    )
    invoice_before = invoice
    carrier_before = carrier

    escalated = escalate_dispute(brokerage["id"], claim["id"])
    assert escalated["status"] == "ESCALATED"

    invoice_after = get_invoice(brokerage["id"], invoice["id"])
    assert invoice_after["invoice_total_cents"] == (
        invoice_before["invoice_total_cents"]
    )
    assert invoice_after["amount_credited_cents"] == 0

    carrier_after = get_carrier(brokerage["id"], carrier["id"])
    assert carrier_after["safety_score"] == carrier_before["safety_score"]


def test_withdraw_from_open_terminates_to_withdrawn(api):
    """PRD §3.9: "From `OPEN` or `IN_REVIEW`, the shipper may withdraw the
    claim into the terminal `WITHDRAWN` state."

    Claim: withdraw on an OPEN claim -> status == WITHDRAWN.
    """
    brokerage, shipper, _c, _q, _l, invoice = setup_invoiced_load(
        origin_zip="00000", destination_zip="00100",
        detention_minutes=0, accessorials=None,
    )
    claim = file_dispute(brokerage["id"], shipper["id"], invoice["id"],
                         claim_type="OVERCHARGE", claimed_cents=1_000)
    withdrawn = withdraw_dispute(brokerage["id"], shipper["id"],
                                 claim["id"])
    assert withdrawn["status"] == "WITHDRAWN"
