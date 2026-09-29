"""Ledgers that must return to their exact pre-operation value."""

from test_helpers import (
    ADMIN,
    assert_entitlement_counters,
    assert_membership_axes,
    assert_reservation_state,
    create_open_park,
    create_president_tier,
    make_payment_payload,
    make_payment_reversal_payload,
    make_reservation_payload,
    read_invoice,
    read_membership,
    read_reservation,
    reset_clock,
    sell_membership_to_new_member,
    set_clock,
    validate_success,
)


def _six_night_stay_on_a_clean_ledger(api):
    """One PRESIDENT contract, a clean ledger, and a CONFIRMED six-night stay."""
    reset_clock(api)
    tier = create_president_tier(api)
    park = create_open_park(
        api,
        name="Silver Pine RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Cyrus Adeyemi", "email": "cyrus@example.com"},
        upfront_paid_cents=1850000,
    )
    assert_entitlement_counters(holder["membership"], class_b=0, annual=0)

    reservation = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], holder["membership_id"], "2026-09-05", "2026-09-11"
            ),
            holder["headers"],
        ),
        201,
    )
    assert_reservation_state(reservation, "CONFIRMED", entitlement_nights_charged=6)
    assert reservation["nights"] == 6
    assert_entitlement_counters(
        read_membership(api, holder["membership_id"]), class_b=6, annual=6
    )
    return holder, park, reservation


def test_cancellation_credits_the_night_ledger_back_to_zero(api):
    """The credit is exact: the ledger reads its pre-booking value with no residue.

    PRD §3.6: "Cancelling a `CONFIRMED` member stay runs the full compensating action —
    `entitlement_nights_charged` is credited back to the membership's class bucket and to
    `annual_nights_used` and then reset to 0, `affiliate_nights_charged` is credited back to
    the agreement's `nights_consumed_ytd` with `settlement_owed_cents` recomputed and then
    reset to 0, `pool_charged` returns to `NONE` releasing the seat on every night of the
    stay, and the membership's `version` increments by 1. The entitlement invariant is left
    exactly as it stood before the booking."

    Design: Difficulty/compensating_invariant/entitlement_night_ledger_returns_to_zero_after_cancellation_and_rebooking_does_not_double_debit
    """
    holder, _park, reservation = _six_night_stay_on_a_clean_ledger(api)

    cancelled = validate_success(
        api.cancel_reservation(reservation["id"], holder["headers"]), 200
    )
    assert_reservation_state(
        cancelled, "CANCELLED", pool_charged="NONE", entitlement_nights_charged=0
    )
    assert cancelled["cancellation_reason"] == "MEMBER_REQUEST"

    assert_entitlement_counters(
        read_membership(api, holder["membership_id"]), class_b=0, annual=0
    )


def test_rebooking_after_a_cancellation_debits_only_the_new_stay(api):
    """A cancelled stay is no longer a prior stay, and its nights are not re-debited.

    PRD §3.3: "The counters against which headroom is judged reflect only the current
    entitlement year: they are derived from the membership's reservations in status
    `CONFIRMED`, `CHECKED_IN`, `EXTENSION_REVIEW` or `COMPLETED` whose `arrival_date` is on or
    after `entitlement_year_start` and strictly before `entitlement_year_start` advanced by
    the entitlement-year length of 365 days. Rows in `WAITLISTED`, `PENDING`, `CANCELLED` or
    `EXPIRED` are excluded and debit nothing."

    Design: Difficulty/compensating_invariant/entitlement_night_ledger_returns_to_zero_after_cancellation_and_rebooking_does_not_double_debit
    """
    holder, park, reservation = _six_night_stay_on_a_clean_ledger(api)
    validate_success(api.cancel_reservation(reservation["id"], holder["headers"]), 200)

    rebooked = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], holder["membership_id"], "2026-09-05", "2026-09-09"
            ),
            holder["headers"],
        ),
        201,
    )
    assert_reservation_state(
        rebooked, "CONFIRMED", pool_charged="MEMBER_POOL", entitlement_nights_charged=4
    )
    assert rebooked["nights"] == 4

    membership = read_membership(api, holder["membership_id"])
    assert_entitlement_counters(membership, class_b=4, annual=4)
    assert membership["nights_used_class_b"] != 10, "the cancelled six nights are not re-debited"
    assert membership["nights_used_class_b"] != 2, "nor is the credit taken twice"

    assert read_reservation(api, reservation["id"])["status"] == "CANCELLED"


def _paid_invoice_carrying_a_fifteen_day_late_fee(api):
    """A PRESIDENT invoice swept at 15 days past due, then settled in full."""
    reset_clock(api)
    tier = create_president_tier(api)
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Wren Tanaka", "email": "wren@example.com"},
        upfront_paid_cents=1850000,
    )
    invoice_id = holder["invoice_id"]

    set_clock(api, "2026-09-15")
    validate_success(api.run_dues_delinquency(ADMIN), 200)

    aged = read_invoice(api, invoice_id)
    assert aged["amount_cents"] == 59508
    assert aged["days_past_due"] == 15
    # 59508 * 1.5% * ceil(15/30) = 892.62, with a single half-up rounding.
    assert aged["late_fee_cents"] == 893
    assert aged["status"] == "PAST_DUE"

    before = read_membership(api, holder["membership_id"])
    assert before["dues_balance_cents"] == 60401, "59508 of dues plus the 893 late fee"
    assert_membership_axes(before, "ACTIVE", "GRACE")

    paid = validate_success(
        api.pay_dues_invoice(invoice_id, make_payment_payload(60401), holder["headers"]), 200
    )
    assert paid["status"] == "PAID"
    assert paid["paid_amount_cents"] == 60401
    assert paid["paid_at"] is not None
    return holder, invoice_id


def test_reversal_restores_the_balance_including_the_accrued_late_fee(api):
    """The reversal returns exactly 60401 cents: the fee is neither dropped nor re-charged.

    PRD §3.7: "The reversal is a genuine compensating action: `paid_amount_cents` is reset to
    0, `paid_at` is cleared to null, `dues_paid_through` is rolled back to the value it held
    before the payment, `dues_balance_cents` is restored to exactly its pre-payment figure,
    and the membership's `version` increments by 1."

    Design: Difficulty/compensating_invariant/dues_balance_in_cents_is_restored_exactly_by_a_payment_reversal_including_the_accrued_late_fee
    """
    holder, invoice_id = _paid_invoice_carrying_a_fifteen_day_late_fee(api)
    settled = read_membership(api, holder["membership_id"])
    assert settled["dues_balance_cents"] == 0, "a settling payment leaves nothing outstanding"

    reversed_invoice = validate_success(
        api.reverse_dues_payment(invoice_id, make_payment_reversal_payload(), ADMIN), 200
    )
    assert reversed_invoice["status"] == "PAST_DUE", (
        "2026-09-15 is after the 2026-08-31 due date, so the invoice is PAST_DUE and not OPEN"
    )
    assert reversed_invoice["paid_amount_cents"] == 0
    assert reversed_invoice["paid_at"] is None
    assert reversed_invoice["amount_cents"] == 59508, "the dues figure is untouched"
    assert reversed_invoice["late_fee_cents"] == 893, "the accrued fee is neither dropped nor doubled"

    assert read_membership(api, holder["membership_id"])["dues_balance_cents"] == 60401, (
        "the conserved cents figure is restored exactly"
    )


def test_reversal_rewinds_the_dues_axis_to_grace_and_not_to_delinquent(api):
    """The reversal re-derives the billing axis from the invoice rather than advancing it.

    PRD §3.7: "A membership with an `OPEN` or `PAST_DUE` invoice whose
    `days_past_due` is at least 1 and below 30 moves from `CURRENT` to `GRACE`."

    Design: Difficulty/compensating_invariant/dues_balance_in_cents_is_restored_exactly_by_a_payment_reversal_including_the_accrued_late_fee
    """
    holder, invoice_id = _paid_invoice_carrying_a_fifteen_day_late_fee(api)
    assert_membership_axes(read_membership(api, holder["membership_id"]), "ACTIVE", "CURRENT")

    validate_success(
        api.reverse_dues_payment(invoice_id, make_payment_reversal_payload(), ADMIN), 200
    )

    membership = read_membership(api, holder["membership_id"])
    assert_membership_axes(membership, "ACTIVE", "GRACE")
    assert membership["dues_status"] != "DELINQUENT", (
        "fifteen days past due is inside the grace band, so the axis does not overshoot"
    )
