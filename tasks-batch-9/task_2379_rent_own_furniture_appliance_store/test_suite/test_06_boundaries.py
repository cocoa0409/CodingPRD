"""Two boundaries that decide opposite outcomes one unit apart.

A single day-close sweeps two agreements whose due dates are one day apart, so the
same sweep must charge one of them and leave the other alone. Two payoff quotes with
identical expiries are accepted one second apart, so one is live and the other is not.
"""

from __future__ import annotations

from test_helpers import (
    DAY_02,
    DAY_08,
    DAY_08_PLUS_ONE_SECOND,
    DAY_12,
    TX_LATE_FEE_CENTS,
    TX_REINSTATEMENT_FEE_CENTS,
    W52_MONTHLY_EQUIVALENT_CENTS,
    W52_RENEWAL_RATE_CENTS,
    AccountFlag,
    CollectionsStage,
    ErrorId,
    EntryType,
    LoyaltyTier,
    PaymentStatus,
    PossessionStatus,
    QuoteStatus,
    UnitStatus,
    WindowStatus,
    assert_fields,
    assert_paid_pct,
    build_tx_floor,
    deliver_on,
    factories,
    failure,
    sign_on,
)
from test_helpers.test_users import MANAGER

SECOND_DELIVERY_START = "2026-08-02T09:00:00Z"
SECOND_DELIVERY_END = "2026-08-02T11:00:00Z"
LATE_AFTERNOON_START = "2026-08-01T14:00:00Z"
LATE_AFTERNOON_END = "2026-08-01T16:00:00Z"
PAYOFF_AFTER_ONE_PERIOD_CENTS = 145160
EQUITY_THRESHOLD_CENTS = 2 * W52_MONTHLY_EQUIVALENT_CENTS  # two months' rent, in cents


def _two_agreements_due_a_day_apart(world):
    """One sofa delivered on the first and another on the second, then a single sweep."""
    scenario = build_tx_floor(world, serials=("SN-TX-0001", "SN-TX-0002"))
    deliver_on(sign_on(scenario, unit_index=0))

    world.set_clock(DAY_02)
    second = world.sign(scenario.customer_id, scenario.units[1]["id"])
    world.deliver(
        second["id"], scenario.crew_id, SECOND_DELIVERY_START, SECOND_DELIVERY_END
    )

    world.set_clock(DAY_12)
    report = world.day_close(scenario.store_id)
    return scenario, second, report


def test_exactly_three_days_past_a_three_day_grace_period_is_still_current(world):
    """The grace comparison is strict, so the third day carries no fee and no transition.

    PRD: When `days_late` is at or below the jurisdiction's `late_fee_grace_days` there is no fee **and no transition at all** — the comparison is strict, so an agreement one day past a three-day grace period is still current and only a fourth day makes it delinquent.

    Design: Difficulty/boundary_precision_check/late_fee_grace_day_boundary_three_versus_four_in_one_day_close
    """
    scenario, second, report = _two_agreements_due_a_day_apart(world)

    assert_fields(
        report,
        store_id=scenario.store_id,
        agreements_scanned=2,
        late_fees_assessed=1,
        late_fee_total_cents=TX_LATE_FEE_CENTS,
        windows_opened=1,
        windows_expired=0,
        agreements_defaulted=0,
    )

    untouched = world.get_agreement(second["id"])
    assert_fields(
        untouched,
        current_period_due_at="2026-08-09T00:00:00Z",
        late_fee_assessed_cents=0,
        late_fee_balance_cents=0,
        late_fee_period_index_last=0,
        reinstatement_fee_balance_cents=0,
        payment_status=PaymentStatus.CURRENT,
        collections_stage=CollectionsStage.NONE,
    )
    assert world.windows(second["id"]) == [], (
        "an agreement inside its grace period opens no reinstatement window"
    )


def test_the_fourth_day_assesses_the_fee_and_opens_the_short_window(world):
    """One day further past due, the same sweep charges the fee and starts the clock.

    PRD: Otherwise the fee is the smaller of `late_fee_max_cents` and `renewal_rate_cents` multiplied by `late_fee_pct`, rounded half up.

    Design: Difficulty/boundary_precision_check/late_fee_grace_day_boundary_three_versus_four_in_one_day_close
    """
    scenario, _second, report = _two_agreements_due_a_day_apart(world)
    assert report["agreements_marked_adverse"] == 1, (
        "exactly one of the two swept agreements crossed into delinquency"
    )

    charged = scenario.read_agreement()
    assert_fields(
        charged,
        current_period_due_at="2026-08-08T00:00:00Z",
        late_fee_assessed_cents=TX_LATE_FEE_CENTS,
        late_fee_balance_cents=TX_LATE_FEE_CENTS,
        late_fee_period_index_last=1,
        reinstatement_fee_balance_cents=TX_REINSTATEMENT_FEE_CENTS,
        payment_status=PaymentStatus.DELINQUENT,
        collections_stage=CollectionsStage.ADVERSE,
    )
    assert charged["late_fee_assessed_cents"] < W52_RENEWAL_RATE_CENTS, (
        "the fee is a tenth of the period rate, well under the statutory cap"
    )

    windows = world.windows(scenario.agreement_id)
    assert len(windows) == 1, f"expected exactly one window, got {len(windows)}"
    assert_fields(
        windows[0],
        status=WindowStatus.OPEN,
        window_days=5,
        reinstatement_fee_cents=TX_REINSTATEMENT_FEE_CENTS,
        expires_at="2026-08-17T00:00:00Z",
    )
    assert charged["rent_applied_cents"] < EQUITY_THRESHOLD_CENTS, (
        "no rent has been applied, so the short window length is the one that applies"
    )

    assert_fields(
        scenario.read_customer(),
        lifetime_delinquency_count=1,
        adverse_agreement_count=1,
        account_flag=AccountFlag.ADVERSE,
    )


def _two_live_quotes(world):
    """Two agreements, each one period in, each carrying an open quote that expires together."""
    scenario = build_tx_floor(world, serials=("SN-TX-0001", "SN-TX-0002"))
    deliver_on(sign_on(scenario, unit_index=0))

    second = world.sign(scenario.customer_id, scenario.units[1]["id"])
    world.deliver(
        second["id"], scenario.crew_id, LATE_AFTERNOON_START, LATE_AFTERNOON_END
    )

    world.pay(scenario.agreement_id, W52_RENEWAL_RATE_CENTS)
    world.pay(second["id"], W52_RENEWAL_RATE_CENTS)

    first_quote = world.issue_quote(scenario.agreement_id)
    second_quote = world.issue_quote(second["id"])
    return scenario, second, first_quote, second_quote


def test_a_payoff_accepted_at_the_expiry_instant_is_still_live(world):
    """The expiry comparison is inclusive, so the last second of validity still works.

    PRD: The quote moves `OPEN` → `ACCEPTED`; the agreement records `early_purchase_paid_cents` equal to the payoff, clears `late_fee_balance_cents` and `reinstatement_fee_balance_cents`, sets `paid_pct` to 1.0000, and moves `payment_status` `CURRENT` → `CLOSED` and `possession_status` `DELIVERED` → `OWNED`.

    Design: Difficulty/boundary_precision_check/payoff_quote_expiry_is_inclusive_to_the_second
    """
    scenario, _second, first_quote, second_quote = _two_live_quotes(world)
    for quote in (first_quote, second_quote):
        assert_fields(
            quote,
            loyalty_tier_snapshot=LoyaltyTier.STANDARD,
            loyalty_discount_cents=0,
            late_fee_component_cents=0,
            pre_discount_cents=PAYOFF_AFTER_ONE_PERIOD_CENTS,
            payoff_amount_cents=PAYOFF_AFTER_ONE_PERIOD_CENTS,
            status=QuoteStatus.OPEN,
            expires_at=DAY_08,
        )

    world.set_clock(DAY_08)
    accepted = world.accept_quote(first_quote["id"], PAYOFF_AFTER_ONE_PERIOD_CENTS)
    assert accepted["status"] == QuoteStatus.ACCEPTED

    agreement = scenario.read_agreement()
    assert_fields(
        agreement,
        early_purchase_paid_cents=PAYOFF_AFTER_ONE_PERIOD_CENTS,
        payment_status=PaymentStatus.CLOSED,
        possession_status=PossessionStatus.OWNED,
        late_fee_balance_cents=0,
        reinstatement_fee_balance_cents=0,
    )
    assert_paid_pct(agreement, 1.0000)
    assert scenario.read_unit(0)["status"] == UnitStatus.SOLD

    entries = world.ledger(customer_id=scenario.customer_id)
    bonus = [e for e in entries if e["entry_type"] == EntryType.EARLY_PAYOFF_BONUS]
    assert len(bonus) == 1, f"expected exactly one payoff bonus, got {len(bonus)}"
    assert bonus[0]["delta_points"] == 500
    assert_fields(
        scenario.read_customer(),
        loyalty_points_lifetime=650,
        loyalty_tier=LoyaltyTier.GOLD,
    )


def test_a_payoff_accepted_one_second_later_is_refused_as_expired(world):
    """One second past the expiry the identical acceptance is refused and changes nothing.

    PRD: The logical clock is at or before the quote's `expires_at` — otherwise `ERR_QUOTE_EXPIRED` (409).

    Design: Difficulty/boundary_precision_check/payoff_quote_expiry_is_inclusive_to_the_second
    """
    scenario, second, first_quote, second_quote = _two_live_quotes(world)

    world.set_clock(DAY_08)
    world.accept_quote(first_quote["id"], PAYOFF_AFTER_ONE_PERIOD_CENTS)

    world.set_clock(DAY_08_PLUS_ONE_SECOND)
    response = scenario.api.accept_early_purchase_quote(
        second_quote["id"],
        factories.accept_quote_payload(PAYOFF_AFTER_ONE_PERIOD_CENTS),
        MANAGER,
    )
    failure(response, ErrorId.QUOTE_EXPIRED)

    still_open = world.quotes(second["id"])
    assert len(still_open) == 1, f"expected one quote on the second agreement, got {len(still_open)}"
    assert still_open[0]["status"] == QuoteStatus.OPEN

    untouched = world.get_agreement(second["id"])
    assert_fields(
        untouched,
        early_purchase_paid_cents=0,
        payment_status=PaymentStatus.CURRENT,
        possession_status=PossessionStatus.DELIVERED,
    )
    assert scenario.read_unit(1)["status"] == UnitStatus.ON_RENT
    assert scenario.read_store()["units_on_rent_count"] == 1
