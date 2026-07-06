"""Booking cancellation: notice-window refund tiers, deposit conservation, the
three-hop financing-void cascade, and the quote balance identity after void."""
from test_helpers import (
    validate_success, get_success_data,
    assert_deposit_conservation, assert_quote_balance_identity,
    TEST_USERS, PROC_A, PROC_B,
    create_procedure, create_scheduled_booking, set_clock,
)

FRONT = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_cancellation_exactly_14_days_half_refund(api):
    """PRD §3.7: "if it is at least 14 days but fewer than 30, the refund fraction is
    0.50 ... The deposit_refunded_cents is the quote's current deposit_paid_cents
    multiplied by the refund fraction, rounded half up to whole cents, and the
    deposit_forfeited_cents is the remainder — the recorded deposit minus the refunded
    portion."

    Design: Difficulty/boundary_precision_check/boundary_cancellation_notice_14_days_half_refund
    """
    procA = create_procedure(**PROC_A)
    procB = create_procedure(**PROC_B)
    booking, _q, _p, _l, _f = create_scheduled_booking(
        [procA["id"], procB["id"]], deposit_cents=266000)
    set_clock("2026-07-18T00:00:00Z")  # exactly 14 days before 2026-08-01
    resp = api.cancel_surgery_booking(booking["id"], BILLING)
    data = validate_success(resp, 200)
    assert data["deposit_refunded_cents"] == 133000   # round_half_up(266000 * 0.5)
    assert data["deposit_forfeited_cents"] == 133000


def test_cancellation_14_day_boundary_conserves_deposit(api):
    """PRD §3.7: "so that the forfeited and refunded amounts always sum exactly to the
    deposit that was paid, with no drift."

    Design: Difficulty/boundary_precision_check/boundary_cancellation_notice_14_days_half_refund
    """
    procA = create_procedure(**PROC_A)
    procB = create_procedure(**PROC_B)
    booking, _q, _p, _l, _f = create_scheduled_booking(
        [procA["id"], procB["id"]], deposit_cents=266000)
    set_clock("2026-07-18T00:00:00Z")
    data = get_success_data(api.cancel_surgery_booking(booking["id"], BILLING))
    assert_deposit_conservation(data, 266000)


def test_cancellation_full_refund_over_30_days(api):
    """PRD §3.7: "If that notice is at least 30 days, the refund fraction is the full
    1.00 ... The deposit_refunded_cents is the quote's current deposit_paid_cents
    multiplied by the refund fraction, rounded half up to whole cents, and the
    deposit_forfeited_cents is the remainder."

    Design: Corner/calculations/cancellation_full_refund_over_30_days
    """
    procA = create_procedure(**PROC_A)
    booking, _q, _p, _l, _f = create_scheduled_booking([procA["id"]], deposit_cents=170000)
    set_clock("2026-06-01T00:00:00Z")  # 61 days notice
    data = get_success_data(api.cancel_surgery_booking(booking["id"], BILLING))
    assert data["deposit_refunded_cents"] == 170000
    assert data["deposit_forfeited_cents"] == 0


def test_cancellation_zero_refund_under_14_days(api):
    """PRD §3.7: "and if it is fewer than 14 days, the refund fraction is 0.00 ... the
    deposit_forfeited_cents is the remainder — the recorded deposit minus the refunded
    portion."

    Design: Corner/calculations/cancellation_zero_refund_under_14_days
    """
    procA = create_procedure(**PROC_A)
    booking, _q, _p, _l, _f = create_scheduled_booking([procA["id"]], deposit_cents=170000)
    set_clock("2026-07-19T00:00:00Z")  # 13 days notice
    data = get_success_data(api.cancel_surgery_booking(booking["id"], BILLING))
    assert data["deposit_refunded_cents"] == 0
    assert data["deposit_forfeited_cents"] == 170000


def test_deposit_conservation_on_cancel_20_day_split(api):
    """PRD §3.7: "the deposit_forfeited_cents is the remainder — the recorded deposit
    minus the refunded portion — so that the forfeited and refunded amounts always sum
    exactly to the deposit that was paid, with no drift."

    Design: Difficulty/compensating_invariant/invariant_deposit_conservation_on_cancel
    """
    procA = create_procedure(**PROC_A)
    procB = create_procedure(**PROC_B)
    booking, _q, _p, _l, _f = create_scheduled_booking(
        [procA["id"], procB["id"]], deposit_cents=266000)
    set_clock("2026-07-12T00:00:00Z")  # 20 days -> 50% tier
    data = get_success_data(api.cancel_surgery_booking(booking["id"], BILLING))
    assert data["deposit_forfeited_cents"] == 133000
    assert data["deposit_refunded_cents"] == 133000
    assert_deposit_conservation(data, 266000)


def test_deposit_conservation_holds_at_full_refund(api):
    """PRD §3.7: "so that the forfeited and refunded amounts always sum exactly to the
    deposit that was paid, with no drift."

    Design: Difficulty/compensating_invariant/invariant_deposit_conservation_on_cancel
    """
    procA = create_procedure(**PROC_A)
    procB = create_procedure(**PROC_B)
    booking, _q, _p, _l, _f = create_scheduled_booking(
        [procA["id"], procB["id"]], deposit_cents=266000)
    set_clock("2026-06-01T00:00:00Z")  # 61 days -> 100% refund
    data = get_success_data(api.cancel_surgery_booking(booking["id"], BILLING))
    assert_deposit_conservation(data, 266000)
    assert data["deposit_refunded_cents"] == 266000
    assert data["deposit_forfeited_cents"] == 0


def test_cancel_voids_approved_financing_and_reconciles_balance(api):
    """PRD §3.7: "each FinancingApplication on the quote that is APPROVED or SUBMITTED is
    transitioned to VOIDED; and every application that had been APPROVED runs its own
    reversal, reducing the quote's financed_cents by that application's
    approved_amount_cents. In the third hop, driven by the change to financed_cents, the
    quote's balance_due_cents is recomputed as total_cents minus deposit_paid_cents minus
    financed_cents."

    Design: Difficulty/transitive_cascade/cascade_booking_cancel_voids_financing_reconciles_balance
    """
    procA = create_procedure(**PROC_A)
    procB = create_procedure(**PROC_B)
    booking, _q, _p, _l, fin = create_scheduled_booking(
        [procA["id"], procB["id"]], deposit_cents=266000,
        financing={"lender": "CARECREDIT", "requested_amount_cents": 500000})
    # clock 2026-06-01 -> 61 days notice -> 100% refund
    set_clock("2026-06-01T00:00:00Z")
    cancelled = validate_success(api.cancel_surgery_booking(booking["id"], BILLING), 200)
    assert cancelled["deposit_refunded_cents"] == 266000
    assert cancelled["deposit_forfeited_cents"] == 0
    fin_after = get_success_data(api.get_financing(fin["id"], FRONT))
    assert fin_after["status"] == "VOIDED"
    quote_after = get_success_data(api.get_quote_package(_q["id"], FRONT))
    assert quote_after["financed_cents"] == 0
    assert quote_after["deposit_paid_cents"] == 0
    assert quote_after["balance_due_cents"] == 1330000  # 1330000 - 0 - 0


def test_cancel_cascade_full_chain_end_state(api):
    """PRD §3.7: "In the first hop, the refunded portion leaves the quote ledger: the
    quote's deposit_paid_cents is reduced by deposit_refunded_cents. In the second hop,
    each FinancingApplication on the quote that is APPROVED or SUBMITTED is transitioned
    to VOIDED."

    Design: Difficulty/transitive_cascade/cascade_booking_cancel_voids_financing_reconciles_balance
    """
    procA = create_procedure(**PROC_A)
    procB = create_procedure(**PROC_B)
    booking, quote, _p, _l, fin = create_scheduled_booking(
        [procA["id"], procB["id"]], deposit_cents=266000,
        financing={"lender": "CARECREDIT", "requested_amount_cents": 500000})
    set_clock("2026-06-01T00:00:00Z")
    get_success_data(api.cancel_surgery_booking(booking["id"], BILLING))
    quote_after = get_success_data(api.get_quote_package(quote["id"], FRONT))
    # hop 1: deposit_paid reduced by the full refunded 266000 -> 0
    assert quote_after["deposit_paid_cents"] == 0
    # hop 2: approved financing voided, financed_cents back to 0
    assert quote_after["financed_cents"] == 0
    fin_after = get_success_data(api.get_financing(fin["id"], FRONT))
    assert fin_after["status"] == "VOIDED"


def test_quote_balance_identity_after_financing_void(api):
    """PRD §2.6: "Its balance_due_cents is always the quote's total_cents minus its
    deposit_paid_cents minus its financed_cents, and this derived field must be
    recomputed and kept consistent every time any of its three inputs changes."

    Design: Difficulty/compensating_invariant/invariant_quote_balance_identity_after_financing_void
    """
    procA = create_procedure(**PROC_A)
    procB = create_procedure(**PROC_B)
    booking, quote, _p, _l, _fin = create_scheduled_booking(
        [procA["id"], procB["id"]], deposit_cents=266000,
        financing={"lender": "CARECREDIT", "requested_amount_cents": 500000})
    set_clock("2026-06-01T00:00:00Z")
    get_success_data(api.cancel_surgery_booking(booking["id"], BILLING))
    quote_after = get_success_data(api.get_quote_package(quote["id"], FRONT))
    assert quote_after["financed_cents"] == 0
    assert quote_after["deposit_paid_cents"] == 0
    assert quote_after["balance_due_cents"] == 1330000
    assert_quote_balance_identity(quote_after)


def test_financing_void_leaves_no_financed_drift(api):
    """PRD §3.8: "When a voided application had previously been APPROVED, its void
    reverses the quote ledger by reducing financed_cents by its approved_amount_cents and
    recomputing balance_due_cents."

    Design: Difficulty/compensating_invariant/invariant_quote_balance_identity_after_financing_void
    """
    procA = create_procedure(**PROC_A)
    procB = create_procedure(**PROC_B)
    booking, quote, _p, _l, _fin = create_scheduled_booking(
        [procA["id"], procB["id"]], deposit_cents=266000,
        financing={"lender": "CARECREDIT", "requested_amount_cents": 500000})
    set_clock("2026-06-01T00:00:00Z")
    get_success_data(api.cancel_surgery_booking(booking["id"], BILLING))
    quote_after = get_success_data(api.get_quote_package(quote["id"], FRONT))
    assert_quote_balance_identity(quote_after)
    assert quote_after["financed_cents"] == 0
