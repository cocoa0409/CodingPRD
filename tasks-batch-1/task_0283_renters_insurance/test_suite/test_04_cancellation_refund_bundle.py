"""Cancellation refunds (pro-rata vs short-rate), bundle discount, dissolution."""
from test_helpers import (
    add_full_coverage,
    create_bundle,
    create_policyholder,
    create_quoted_policy,
    get_first_invoice,
    issue_policy,
    make_policyholder_headers,
    set_clock,
    setup_active_policy,
    validate_error,
    validate_success,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]


def _issue_paid_policy(api, ph_id, amount=33350, **policy_overrides):
    """Create + fully-cover + issue + fully-pay a policy. Returns the policy."""
    policy = create_quoted_policy(ph_id, **policy_overrides)
    add_full_coverage(policy["id"])
    policy = issue_policy(policy["id"])
    invoice = get_first_invoice(policy["id"])
    validate_success(
        api.record_payment(invoice["id"], {"amount_cents": amount, "method": "CARD"},
                           make_policyholder_headers(ph_id)),
        201,
    )
    return policy


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc — pro-rata vs short-rate refund diverge
# ---------------------------------------------------------------------------
def test_cancellation_refund_pro_rata(api):
    """PRD §3.5: "The pro-rata refund is the paid premium multiplied by the
    unused days and divided by the term days, rounded half up to a whole cent.
    If the requested `refund_method` is `PRO_RATA`, the `refund_amount_cents` is
    exactly that pro-rata refund."

    Design: Difficulty/dual_variant_calc/cancellation_refund_pro_rata_vs_short_rate_diverge
    """
    set_clock("2026-01-01T00:00:00Z")
    ph = create_policyholder(email="ref@x.com")
    policy = _issue_paid_policy(api, ph["id"], insured_address="11 P St")
    set_clock("2026-03-15T00:00:00Z")  # 73 days elapsed
    out = validate_success(
        api.cancel_policy(policy["id"], {"refund_method": "PRO_RATA"}, UW), 200
    )
    assert out["refund_amount_cents"] == 26680, out["refund_amount_cents"]
    assert out["status"] == "CANCELLED", out["status"]


def test_cancellation_refund_short_rate_strictly_less(api):
    """PRD §3.5: "If the requested method is `SHORT_RATE`, a penalty equal to
    the paid premium multiplied by the short-rate penalty of ten percent
    (rounded half up to a whole cent) is subtracted from the pro-rata refund,
    and `refund_amount_cents` is the larger of zero and that difference — so for
    the same inputs a short-rate refund is strictly less than a pro-rata refund."

    Design: Difficulty/dual_variant_calc/cancellation_refund_pro_rata_vs_short_rate_diverge
    """
    set_clock("2026-01-01T00:00:00Z")
    ph = create_policyholder(email="ref2@x.com")
    policy = _issue_paid_policy(api, ph["id"], insured_address="12 Q St")
    set_clock("2026-03-15T00:00:00Z")  # identical 73 days elapsed, same paid premium
    out = validate_success(
        api.cancel_policy(policy["id"], {"refund_method": "SHORT_RATE"}, UW), 200
    )
    assert out["refund_amount_cents"] == 23345, out["refund_amount_cents"]


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency — payment requires billable policy
# ---------------------------------------------------------------------------
def test_payment_on_cancelled_policy_invoice_rejected(api):
    """PRD §3.4: "A payment may be recorded only while the owning policy's
    status is `ACTIVE` or `LAPSED`; against a policy in any other status the
    payment is rejected with `ERR_POLICY_NOT_BILLABLE`."

    Design: Difficulty/cross_entity_state_dependency/payment_requires_policy_billable
    """
    set_clock("2026-01-01T00:00:00Z")
    ph = create_policyholder(email="cx2@x.com")
    policy = create_quoted_policy(ph["id"])
    add_full_coverage(policy["id"])
    policy = issue_policy(policy["id"])
    invoice = get_first_invoice(policy["id"])
    validate_success(api.cancel_policy(policy["id"], {"refund_method": "PRO_RATA"}, UW), 200)
    resp = api.record_payment(
        invoice["id"], {"amount_cents": 33350, "method": "CARD"},
        make_policyholder_headers(ph["id"]),
    )
    validate_error(resp, "ERR_POLICY_NOT_BILLABLE", 409)


def test_payment_after_short_rate_cancel_rejected(api):
    """PRD §3.4: "A payment may be recorded only while the owning policy's
    status is `ACTIVE` or `LAPSED`; against a policy in any other status the
    payment is rejected with `ERR_POLICY_NOT_BILLABLE`."

    A policy cancelled (here via SHORT_RATE) is terminal-CANCELLED, so any later
    payment against its invoice is rejected by the same cross-entity guard.

    Design: Difficulty/cross_entity_state_dependency/payment_requires_policy_billable
    """
    set_clock("2026-01-01T00:00:00Z")
    ph = create_policyholder(email="cx2b@x.com")
    policy = create_quoted_policy(ph["id"])
    add_full_coverage(policy["id"])
    policy = issue_policy(policy["id"])
    invoice = get_first_invoice(policy["id"])
    # cancel from ACTIVE -> CANCELLED, then attempt a payment again
    validate_success(api.cancel_policy(policy["id"], {"refund_method": "SHORT_RATE"}, UW), 200)
    resp = api.record_payment(
        invoice["id"], {"amount_cents": 100, "method": "ACH"},
        make_policyholder_headers(ph["id"]),
    )
    validate_error(resp, "ERR_POLICY_NOT_BILLABLE", 409)


# ---------------------------------------------------------------------------
# Queue B: cancel blocked by open claim
# ---------------------------------------------------------------------------
def test_cancel_blocked_by_open_claim(api):
    """PRD §3.5: "From `ACTIVE`, cancellation is blocked while any claim is in
    `FILED`, `UNDER_REVIEW`, or `APPROVED`, and such an attempt is rejected with
    `ERR_OPEN_CLAIM_BLOCKS_CANCEL`."

    Design: Corner/state_machines/cancel_blocked_by_open_claim
    """
    _ph, policy, _lines, _inv = setup_active_policy(email="s7@x.com")
    ph_id = _ph["id"]
    validate_success(
        api.file_claim(policy["id"], {"loss_type": "PERSONAL_PROPERTY",
                                      "loss_date": "2026-03-01T00:00:00Z"},
                       make_policyholder_headers(ph_id)),
        201,
    )
    validate_error(
        api.cancel_policy(policy["id"], {"refund_method": "PRO_RATA"}, UW),
        "ERR_OPEN_CLAIM_BLOCKS_CANCEL", 409,
    )


# ---------------------------------------------------------------------------
# Queue B: bundle discount activation + dissolution cascade
# ---------------------------------------------------------------------------
def test_bundle_discount_recomputes_member_premiums(api):
    """PRD §3.1: "the moment its `active_member_count` reaches the two-member
    minimum — through a policy issue or attach that bubbles the count up — the
    bundle transitions `FORMING → ACTIVE`, sets `discount_active` to `true`, and
    as a cascade re-runs the premium calculation on every member policy".
    PRD §3.2: "The bundle factor is 0.90 when the policy's bundle has
    `discount_active` true".

    Design: Corner/calculations/bundle_discount_recomputes_member_premiums
    """
    ph = create_policyholder(email="cc3@x.com")
    bnd = create_bundle(ph["id"])
    # member 1 issued (no discount yet)
    p1 = create_quoted_policy(ph["id"], bundle_id=bnd["id"], insured_address="47 St")
    add_full_coverage(p1["id"])
    issue_policy(p1["id"])
    # member 2 quoted, non-overlapping term
    p2 = create_quoted_policy(
        ph["id"], bundle_id=bnd["id"], insured_address="48 St",
        effective_date="2026-02-01T00:00:00Z", expiry_date="2027-02-01T00:00:00Z",
    )
    add_full_coverage(p2["id"])
    issue_policy(p2["id"])
    bundle = validate_success(api.get_bundle(bnd["id"], UW), 200)
    assert bundle["active_member_count"] == 2, bundle["active_member_count"]
    assert bundle["discount_active"] is True, bundle["discount_active"]
    p1_after = validate_success(api.get_policy(p1["id"], UW), 200)
    assert p1_after["annual_premium_cents"] == 30015, p1_after["annual_premium_cents"]


def test_bundle_dissolution_recomputes_premium_on_cancel(api):
    """PRD §3.1: "while a bundle is `ACTIVE`, if its `active_member_count` drops
    below the two-member minimum — through a cancellation or detach that bubbles
    the count down — the bundle transitions `ACTIVE → DISSOLVED`, sets
    `discount_active` to `false`, and as a cascade re-runs the premium
    calculation on every remaining member policy, each of which now loses the
    discount multiplier."

    Design: Corner/cross_cutting_complexity_layers/bundle_dissolution_recomputes_premium_on_cancel
    """
    set_clock("2026-01-01T00:00:00Z")
    ph = create_policyholder(email="bd@x.com")
    bnd = create_bundle(ph["id"])
    p1 = create_quoted_policy(ph["id"], bundle_id=bnd["id"], insured_address="63 St")
    add_full_coverage(p1["id"])
    issue_policy(p1["id"])
    # Member 2 carries a non-overlapping term for the same policyholder so the
    # issue is not blocked by the half-open term-overlap rule (PRD §3.3); the
    # asserted behavior here is the bundle dissolution + premium recompute.
    p2 = create_quoted_policy(
        ph["id"], bundle_id=bnd["id"], insured_address="64 St",
        effective_date="2027-01-01T00:00:00Z", expiry_date="2028-01-01T00:00:00Z",
    )
    add_full_coverage(p2["id"])
    issue_policy(p2["id"])
    # both active, discount on; cancel one to drop below 2
    validate_success(api.cancel_policy(p2["id"], {"refund_method": "PRO_RATA"}, UW), 200)
    bundle = validate_success(api.get_bundle(bnd["id"], UW), 200)
    assert bundle["status"] == "DISSOLVED", bundle["status"]
    assert bundle["discount_active"] is False, bundle["discount_active"]
    p1_after = validate_success(api.get_policy(p1["id"], UW), 200)
    assert p1_after["annual_premium_cents"] == 33350, p1_after["annual_premium_cents"]
