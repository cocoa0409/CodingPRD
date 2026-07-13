"""Invoice payment, fees & commissions, refund cascades, revenue variants, cycles."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error,
    make_creator_headers, make_student_headers,
    fixtures as fx,
)


def _get_creator(api, creator_id):
    return validate_success(api.get_creator(creator_id, make_creator_headers(creator_id)))


def _get_course(api, course_id, creator_id):
    return validate_success(api.get_course(course_id, make_creator_headers(creator_id)))


def _get_affiliate(api, affiliate_id, creator_id):
    return validate_success(api.get_affiliate(affiliate_id, make_creator_headers(creator_id)))


# --------------------------------------------------------------------------
# Difficulty: gross (provisional) vs net_settled (final) revenue on one PAID invoice.
# --------------------------------------------------------------------------

def test_course_gross_revenue_counts_in_window_invoice(api):
    """PRD §3.5: "A course reports `gross_revenue_cents` as the provisional variant — the
    sum of `amount_cents` over all `PAID` invoices belonging to its enrollments, counting
    every paid invoice including those still inside their refund window — and
    `net_settled_revenue_cents` as the final variant — the sum of `creator_net_cents` over
    its `PAID` invoices that have passed their refund window (current clock strictly after
    `paid_at` plus `refund_window_days`)."

    Design: Difficulty/dual_variant_calc/course_revenue_gross_vs_net_settled
    """
    ctx = fx.setup_paid_enrollment(amount_cents=20000, refund_window_days=14)
    course = _get_course(api, ctx["course"]["id"], ctx["creator"]["id"])
    assert course["gross_revenue_cents"] == 20000


def test_course_net_settled_excludes_in_window_invoice(api):
    """PRD §3.5: "A course reports `gross_revenue_cents` as the provisional variant — the
    sum of `amount_cents` over all `PAID` invoices belonging to its enrollments, counting
    every paid invoice including those still inside their refund window — and
    `net_settled_revenue_cents` as the final variant — the sum of `creator_net_cents` over
    its `PAID` invoices that have passed their refund window (current clock strictly after
    `paid_at` plus `refund_window_days`)."

    Design: Difficulty/dual_variant_calc/course_revenue_gross_vs_net_settled
    """
    ctx = fx.setup_paid_enrollment(amount_cents=20000, refund_window_days=14)
    course = _get_course(api, ctx["course"]["id"], ctx["creator"]["id"])
    assert course["net_settled_revenue_cents"] == 0


# --------------------------------------------------------------------------
# Difficulty: creator net-earnings ledger conserved across pay(+net)/refund(-net).
# --------------------------------------------------------------------------

def test_creator_net_returns_to_zero_after_refund(api):
    """PRD §2.7: "`lifetime_creator_net_cents` always equals the running sum of
    `creator_net_cents` across the creator's `PAID` invoices, so that a payment followed by
    a full refund of the same invoice returns the figure exactly to its pre-payment value
    with zero drift."

    Design: Difficulty/compensating_invariant/creator_net_ledger_conservation_on_refund
    """
    ctx = fx.setup_paid_enrollment(amount_cents=20000, refund_window_days=14)
    before = _get_creator(api, ctx["creator"]["id"])
    assert before["lifetime_creator_net_cents"] == 18000
    fx.refund_invoice_as_creator(ctx["invoice"]["id"], ctx["creator"]["id"])
    after = _get_creator(api, ctx["creator"]["id"])
    assert after["lifetime_creator_net_cents"] == 0


def test_refund_adds_amount_to_lifetime_refunded(api):
    """PRD §3.7: "because the invoice is no longer `PAID`, its `creator_net_cents` drops out
    of `lifetime_creator_net_cents`, and its `amount_cents` is added to
    `lifetime_refunded_cents`."

    Design: Difficulty/compensating_invariant/creator_net_ledger_conservation_on_refund
    """
    ctx = fx.setup_paid_enrollment(amount_cents=20000, refund_window_days=14)
    fx.refund_invoice_as_creator(ctx["invoice"]["id"], ctx["creator"]["id"])
    after = _get_creator(api, ctx["creator"]["id"])
    assert after["lifetime_refunded_cents"] == 20000


# --------------------------------------------------------------------------
# Difficulty: refunding an INITIAL invoice cascades across four entities.
# --------------------------------------------------------------------------

def test_refund_initial_invoice_revokes_enrollment(api):
    """PRD §3.7: "Refunding the `INITIAL` invoice cascades to the whole enrollment. The
    enrollment's `access_status` moves to `REVOKED` and its `billing_status` moves to
    `REFUNDED`."

    Design: Difficulty/transitive_cascade/refund_initial_invoice_depth3_cascade
    """
    ctx = fx.setup_paid_enrollment(amount_cents=20000, refund_window_days=14,
                                   affiliate_pct=20, affiliate_code="AF20")
    invoice = fx.refund_invoice_as_creator(ctx["invoice"]["id"], ctx["creator"]["id"])
    assert invoice["status"] == "REFUNDED"
    enr = validate_success(
        api.get_enrollment(ctx["enrollment"]["id"], make_student_headers(ctx["student"]["id"])))
    assert enr["access_status"] == "REVOKED"
    assert enr["billing_status"] == "REFUNDED"


def test_refund_initial_invoice_reverses_ledger_and_claws_back_commission(api):
    """PRD §3.7: "The affiliate commission is clawed back: the invoice's
    `affiliate_commission_cents` moves out of the affiliate's `commission_pending_cents` and
    into its `commission_clawed_back_cents` (the running sum of commission on the affiliate's
    attributed `REFUNDED` invoices)."

    Design: Difficulty/transitive_cascade/refund_initial_invoice_depth3_cascade
    """
    ctx = fx.setup_paid_enrollment(amount_cents=20000, refund_window_days=14,
                                   affiliate_pct=20, affiliate_code="AF20")
    fx.refund_invoice_as_creator(ctx["invoice"]["id"], ctx["creator"]["id"])
    creator = _get_creator(api, ctx["creator"]["id"])
    assert creator["lifetime_creator_net_cents"] == 0
    affiliate = _get_affiliate(api, ctx["affiliate"]["id"], ctx["creator"]["id"])
    assert affiliate["commission_pending_cents"] == 0
    assert affiliate["commission_clawed_back_cents"] == 4000


# --------------------------------------------------------------------------
# Difficulty: state check (priority 6) masks the temporal window check (priority 9).
# --------------------------------------------------------------------------

def test_re_refund_after_window_close_reports_state_error(api):
    """PRD §3.7: "The invoice must actually be in `PAID` status, else
    `ERR_INVOICE_NOT_REFUNDABLE`, and the refund must fall inside the window — the current
    clock must be at or before `paid_at` plus the course's `refund_window_days`; a later
    refund is rejected with `ERR_REFUND_WINDOW_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/refund_state_beats_temporal
    """
    ctx = fx.setup_paid_enrollment(amount_cents=20000, refund_window_days=14)
    fx.set_clock("2026-03-05T00:00:00Z")
    fx.refund_invoice_as_creator(ctx["invoice"]["id"], ctx["creator"]["id"])
    fx.set_clock("2026-04-01T00:00:00Z")  # window (03-15) is now closed
    resp = api.refund_invoice(ctx["invoice"]["id"], {}, make_creator_headers(ctx["creator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_REFUNDABLE.value)


def test_re_refund_within_window_reports_state_error(api):
    """PRD §3.7: "The invoice must actually be in `PAID` status, else
    `ERR_INVOICE_NOT_REFUNDABLE`, and the refund must fall inside the window — the current
    clock must be at or before `paid_at` plus the course's `refund_window_days`; a later
    refund is rejected with `ERR_REFUND_WINDOW_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/refund_state_beats_temporal
    """
    ctx = fx.setup_paid_enrollment(amount_cents=20000, refund_window_days=14)
    # Clock is still the paid instant (2026-03-01), well inside the window.
    fx.refund_invoice_as_creator(ctx["invoice"]["id"], ctx["creator"]["id"])
    resp = api.refund_invoice(ctx["invoice"]["id"], {}, make_creator_headers(ctx["creator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_REFUNDABLE.value)


# --------------------------------------------------------------------------
# Difficulty: refund-window inclusive boundary (deadline succeeds, +1 day fails).
# --------------------------------------------------------------------------

def test_refund_at_exact_deadline_succeeds(api):
    """PRD §2.5: "An invoice remains refundable while the current clock time is at or before
    its `paid_at` plus the course's `refund_window_days` (measured in whole days) — the final
    instant of that window is still eligible."

    Design: Difficulty/boundary_precision_check/refund_window_inclusive_boundary
    """
    ctx = fx.setup_paid_enrollment(amount_cents=20000, refund_window_days=14)
    fx.set_clock("2026-03-15T00:00:00Z")  # paid_at 2026-03-01 + 14 days
    invoice = fx.refund_invoice_as_creator(ctx["invoice"]["id"], ctx["creator"]["id"])
    assert invoice["status"] == "REFUNDED"


def test_refund_one_day_past_deadline_rejected(api):
    """PRD §3.7: "the refund must fall inside the window — the current clock must be at or
    before `paid_at` plus the course's `refund_window_days`; a later refund is rejected with
    `ERR_REFUND_WINDOW_EXPIRED`."

    Design: Difficulty/boundary_precision_check/refund_window_inclusive_boundary
    """
    ctx = fx.setup_paid_enrollment(amount_cents=20000, refund_window_days=14)
    fx.set_clock("2026-03-16T00:00:00Z")  # one day past the 2026-03-15 deadline
    resp = api.refund_invoice(ctx["invoice"]["id"], {}, make_creator_headers(ctx["creator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_REFUND_WINDOW_EXPIRED.value)


# --------------------------------------------------------------------------
# Difficulty: affiliate commission is floored per-invoice then summed (not sum-then-floor).
# --------------------------------------------------------------------------

def test_affiliate_commission_sum_of_per_invoice_floors(api):
    """PRD §3.5: "Commission is deliberately computed and floored per invoice and then
    summed across invoices — the affiliate's `commission_pending_cents` is the sum of those
    per-invoice floored commissions over the affiliate's attributed `PAID` invoices, which
    is not the same as flooring one commission on the summed amount."

    Design: Difficulty/combinatorial_formula/affiliate_commission_per_invoice_sum_mode_b
    """
    ctx = fx.setup_enrollment(plan_type="PAYMENT_PLAN", amount_cents=10000,
                              num_installments=3, affiliate_pct=15, affiliate_code="AF15")
    for inv in ctx["invoices"]:
        fx.pay_invoice_as_student(inv["id"], ctx["student"]["id"])
    affiliate = _get_affiliate(api, ctx["affiliate"]["id"], ctx["creator"]["id"])
    assert affiliate["commission_pending_cents"] == 1499


def test_affiliate_per_invoice_commissions_are_floored(api):
    """PRD §3.5: "The `affiliate_commission_cents` is, when the enrollment has an attributed
    affiliate whose status is `ACTIVE`, the invoice's `amount_cents` multiplied by that
    affiliate's `commission_pct` divided by 100 and rounded down, and is zero otherwise."

    Design: Difficulty/combinatorial_formula/affiliate_commission_per_invoice_sum_mode_b
    """
    ctx = fx.setup_enrollment(plan_type="PAYMENT_PLAN", amount_cents=10000,
                              num_installments=3, affiliate_pct=15, affiliate_code="AF15")
    commissions = []
    for inv in ctx["invoices"]:
        paid = fx.pay_invoice_as_student(inv["id"], ctx["student"]["id"])
        commissions.append(paid["affiliate_commission_cents"])
    # installments 3334, 3334, 3332 * 15% floored -> 500, 500, 499
    assert sorted(commissions) == [499, 500, 500]


# --------------------------------------------------------------------------
# Corner: invoice state guards.
# --------------------------------------------------------------------------

def test_pay_already_paid_invoice_rejected(api):
    """PRD §3.5: "Payment is only possible while the invoice is `PENDING`, else
    `ERR_INVOICE_NOT_PAYABLE`, and the parent enrollment's course must not be `ARCHIVED`."

    Design: Corner/state_machines/pay_already_paid_invoice_returns_409
    """
    ctx = fx.setup_paid_enrollment(amount_cents=20000)
    resp = api.pay_invoice(ctx["invoice"]["id"], {}, make_student_headers(ctx["student"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE.value)


def test_refund_unpaid_invoice_rejected(api):
    """PRD §3.7: "The invoice must actually be in `PAID` status, else
    `ERR_INVOICE_NOT_REFUNDABLE`"

    Design: Corner/state_machines/refund_unpaid_invoice_returns_409
    """
    ctx = fx.setup_enrollment(amount_cents=20000)
    invoice = ctx["invoices"][0]
    resp = api.refund_invoice(invoice["id"], {}, make_creator_headers(ctx["creator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_REFUNDABLE.value)


def test_cancel_after_payment_rejected(api):
    """PRD §3.7: "Cancellation is permitted only while no invoice for the enrollment is in
    `PAID` status — it is a pre-payment escape hatch — and a cancel attempted after payment
    is rejected with `ERR_ENROLLMENT_INVALID_STATE`."

    Design: Corner/state_machines/cancel_enrollment_after_payment_returns_409
    """
    ctx = fx.setup_paid_enrollment(amount_cents=20000)
    resp = api.cancel_enrollment(
        ctx["enrollment"]["id"], {}, make_student_headers(ctx["student"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_INVALID_STATE.value)


# --------------------------------------------------------------------------
# Difficulty: subscription CYCLE invoices use HALF-OPEN intervals.
# --------------------------------------------------------------------------

def test_cycle_invoice_genuine_overlap_rejected(api):
    """PRD §3.5: "the coverage intervals are half-open, so back-to-back cycles that merely
    touch at an endpoint are allowed, but a genuine overlap with an existing non-refunded
    cycle invoice is rejected with `ERR_CYCLE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/subscription_cycle_overlap_half_open_intervals
    """
    ctx = fx.setup_paid_enrollment(plan_type="SUBSCRIPTION", amount_cents=5000,
                                   billing_interval_days=30)
    cid, crid = ctx["enrollment"]["id"], ctx["creator"]["id"]
    fx.create_cycle_invoice(cid, crid, "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z")
    fx.create_cycle_invoice(cid, crid, "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z")
    resp = api.create_cycle_invoice(
        cid, {"cycle_start": "2026-04-15T00:00:00Z", "cycle_end": "2026-05-15T00:00:00Z"},
        make_creator_headers(crid))
    validate_error(resp, ApiErrorId.ERR_CYCLE_OVERLAP.value)


def test_cycle_invoice_adjacent_touch_allowed(api):
    """PRD §3.5: "the coverage intervals are half-open, so back-to-back cycles that merely
    touch at an endpoint are allowed, but a genuine overlap with an existing non-refunded
    cycle invoice is rejected with `ERR_CYCLE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/subscription_cycle_overlap_half_open_intervals
    """
    ctx = fx.setup_paid_enrollment(plan_type="SUBSCRIPTION", amount_cents=5000,
                                   billing_interval_days=30)
    cid, crid = ctx["enrollment"]["id"], ctx["creator"]["id"]
    fx.create_cycle_invoice(cid, crid, "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z")
    # Touches the prior end at 2026-05-01 but does not overlap (half-open): accepted.
    resp = api.create_cycle_invoice(
        cid, {"cycle_start": "2026-05-01T00:00:00Z", "cycle_end": "2026-06-01T00:00:00Z"},
        make_creator_headers(crid))
    data = validate_success(resp, expected_status=201)
    assert data["kind"] == "CYCLE"
    assert data["status"] == "PENDING"
