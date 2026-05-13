"""Commission settlement — provisional, return-adjusted final, sweep, payout.

PRD §3.8 — commission settlement; §3.10 — sweep semantics. Covers
difficulty-design dual_variant_calc/commission_provisional_vs_final and
combinatorial_formula/commission_circular_dependency.
"""

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from test_helpers import (
    validate_success,
    validate_error,
    ADMIN_HEADERS,
    make_streamer_headers,
    set_clock,
    DEFAULT_BASE_TIME,
    setup_active_streamer,
    setup_gold_streamer_for_commission,
    fetch_settlement,
    fetch_application,
    fetch_streamer,
    emit_event_payload,
    close_return_window,
    emit_return,
    go_live,
    end_live,
    iso,
    ERR_INVALID_STATE,
)
from test_helpers.fixtures import _parse_iso


def round_half_up(x) -> int:
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class TestProvisionalCommission:
    """PRD §3.8: 'The provisional variant runs at end-live and reads only
    gross_sales_cents (returns have not yet been collected).'
    """

    def test_provisional_payout_gold_with_bonus(self, api):
        """# difficulty: dual_variant_calc/commission_provisional_vs_final_on_settlement
        PRD §3.8: "The gross commission is gross_sales_cents multiplied by the
        rate divided by 10,000, rounded half-up to integer cents."
        PRD §3.8: "The tier bonus is 0 unless pinned_streamer_tier is GOLD or
        PLATINUM and gross_sales_cents is at least 5,000,000 cents, in which
        case the bonus is half a percent of gross_sales_cents (i.e.,
        gross_sales_cents multiplied by 0.005), rounded half-up to integer
        cents..."

        Per recipe: GOLD streamer, gross_sales_cents = 6,000,000.
        gross_commission = round_half_up(6_000_000 * 1800 / 10000) = 1_080_000
        tier_bonus = round_half_up(6_000_000 * 0.005) = 30_000
        provisional_payout = 1_110_000
        """
        bundle = setup_gold_streamer_for_commission()
        streamer = bundle["streamer"]
        app = bundle["application"]
        starts = bundle["starts_at"]
        ends = bundle["ends_at"]
        # Go live, emit 6_000_000 GMV, end live
        app = go_live(streamer, app, clock_at=starts)
        payload = emit_event_payload(
            source="ECOMMERCE", kind="BROADCAST_GMV",
            occurred_at=starts + timedelta(minutes=30),
            application_id=app["id"], amount_cents=6_000_000,
        )
        from prd_bench_local_runner.testing import get_success_data
        get_success_data(api.emit_event(payload, ADMIN_HEADERS))
        app = end_live(streamer, app, clock_at=ends)
        settlement = fetch_settlement(app["id"])
        assert settlement["commission_rate_bp"] == 1800
        assert settlement["gross_sales_cents"] == 6_000_000
        assert settlement["provisional_payout_cents"] == 1_110_000


class TestFinalCommissionAfterReturns:
    """PRD §3.8: 'The final variant runs when the periodic sweep observes a
    settlement whose return_window_ends_at has reached or passed the logical
    clock.'
    """

    def test_final_payout_with_returns_reverses_and_taxes(self, api):
        """# difficulty: dual_variant_calc/commission_provisional_vs_final_on_settlement
        PRD §3.8: "Effective sales are computed as gross_sales_cents minus
        returned_sales_cents. The commission to be reversed is
        returned_sales_cents multiplied by the pinned rate divided by 10,000,
        rounded half-up; the adjusted gross commission is the previously
        rounded gross commission minus this reversed amount."
        PRD §3.8: "When that base is strictly positive, tax is withheld at 10%
        of the base, rounded half-up, written to tax_withholding_cents..."

        Per recipe: GOLD, gross=6_000_000, return=1_000_000.
        gross_commission = round_half_up(6_000_000 * 0.18) = 1_080_000
        reversed = round_half_up(1_000_000 * 0.18) = 180_000
        adjusted_gross = 900_000
        effective_sales = 5_000_000 -> bonus eligible (GOLD, >=5_000_000)
        adjusted_bonus = round_half_up(5_000_000 * 0.005) = 25_000
        pre_tax = 925_000
        tax = round_half_up(92500.0) = 92_500
        final_payout = 832_500
        """
        bundle = setup_gold_streamer_for_commission()
        streamer = bundle["streamer"]
        app = bundle["application"]
        starts = bundle["starts_at"]
        ends = bundle["ends_at"]
        app = go_live(streamer, app, clock_at=starts)
        payload = emit_event_payload(
            source="ECOMMERCE", kind="BROADCAST_GMV",
            occurred_at=starts + timedelta(minutes=30),
            application_id=app["id"], amount_cents=6_000_000,
        )
        from prd_bench_local_runner.testing import get_success_data
        get_success_data(api.emit_event(payload, ADMIN_HEADERS))
        app = end_live(streamer, app, clock_at=ends)
        # Emit return within window
        emit_return(app["id"], 1_000_000, ends + timedelta(days=1))
        # Close the window, sweep
        close_return_window(ends)
        settlement = fetch_settlement(app["id"])
        assert settlement["status"] == "READY_FOR_PAYOUT"
        assert settlement["final_payout_cents"] == 832_500, \
            f"final_payout must be 832_500, got {settlement['final_payout_cents']}"


class TestCommissionCircularBonusThreshold:
    """Difficulty-design Rule 2 instance: commission_circular_dependency_mode_c."""

    def test_one_cent_return_drops_tier_bonus_below_threshold(self, api):
        """# difficulty: combinatorial_formula/commission_circular_dependency_mode_c
        PRD §3.8: "The adjusted tier bonus is recomputed against effective
        sales, not gross sales: if pinned_streamer_tier is GOLD or PLATINUM
        and effective sales are at least 5,000,000 cents, the adjusted bonus
        is half a percent of effective sales rounded half-up; otherwise 0."

        Per recipe: GOLD, gross=5_000_000 (bonus eligible at provisional),
        return=1 (effective_sales = 4_999_999 < 5_000_000 -> bonus drops to 0).
        provisional_payout = round_half_up(5_000_000 * 0.18) + round_half_up(5_000_000 * 0.005)
                           = 900_000 + 25_000 = 925_000
        After sweep:
            reversed_commission = round_half_up(1 * 0.18) = 0
            adjusted_gross = 900_000 - 0 = 900_000
            adjusted_bonus = 0 (effective_sales = 4_999_999 below threshold)
            pre_tax = 900_000
            tax = round_half_up(90_000.0) = 90_000
            final_payout = 810_000
        """
        bundle = setup_gold_streamer_for_commission()
        streamer = bundle["streamer"]
        app = bundle["application"]
        starts = bundle["starts_at"]
        ends = bundle["ends_at"]
        app = go_live(streamer, app, clock_at=starts)
        payload = emit_event_payload(
            source="ECOMMERCE", kind="BROADCAST_GMV",
            occurred_at=starts + timedelta(minutes=30),
            application_id=app["id"], amount_cents=5_000_000,
        )
        from prd_bench_local_runner.testing import get_success_data
        get_success_data(api.emit_event(payload, ADMIN_HEADERS))
        app = end_live(streamer, app, clock_at=ends)
        settlement = fetch_settlement(app["id"])
        assert settlement["provisional_payout_cents"] == 925_000
        # Emit 1-cent return
        emit_return(app["id"], 1, ends + timedelta(days=1))
        close_return_window(ends)
        settlement = fetch_settlement(app["id"])
        assert settlement["status"] == "READY_FOR_PAYOUT"
        assert settlement["final_payout_cents"] == 810_000


class TestReturnWindowGating:
    """PRD §3.8: 'provided the event's occurred_at is at or before the
    settlement's return_window_ends_at; events whose occurred_at falls after
    the window are ignored for settlement purposes.'
    """

    def test_late_return_event_ignored(self, api):
        """PRD §3.8: "events whose occurred_at falls after the window are
        ignored for settlement purposes."
        """
        bundle = setup_gold_streamer_for_commission()
        streamer = bundle["streamer"]
        app = bundle["application"]
        starts = bundle["starts_at"]
        ends = bundle["ends_at"]
        app = go_live(streamer, app, clock_at=starts)
        from prd_bench_local_runner.testing import get_success_data
        # Push 6_000_000 GMV in-window
        get_success_data(api.emit_event(
            emit_event_payload(
                source="ECOMMERCE", kind="BROADCAST_GMV",
                occurred_at=starts + timedelta(minutes=30),
                application_id=app["id"], amount_cents=6_000_000,
            ), ADMIN_HEADERS
        ))
        app = end_live(streamer, app, clock_at=ends)
        # Emit a return whose occurred_at is AFTER the return window
        rwe = _parse_iso(fetch_settlement(app["id"])["return_window_ends_at"])
        late_return_at = rwe + timedelta(hours=1)
        # We have to advance clock to be able to emit the event
        set_clock(late_return_at)
        emit_return(app["id"], 1_000_000, late_return_at)
        # Now run sweep
        close_return_window(ends)
        settlement = fetch_settlement(app["id"])
        # PRD says the late return must NOT have updated returned_sales_cents
        assert settlement["returned_sales_cents"] == 0, (
            f"late-window return must be ignored; got {settlement['returned_sales_cents']}"
        )


class TestPayoutSettlement:
    """PRD §3.8: 'A PlatformAdmin then pays out a READY_FOR_PAYOUT settlement;
    the payout transitions status to PAID...'
    """

    def test_payout_transitions_to_paid_and_updates_gmv(self, api):
        """PRD §3.8: "A PlatformAdmin then pays out a READY_FOR_PAYOUT
        settlement; the payout transitions status to PAID and adds the
        effective sales (gross_sales_cents minus returned_sales_cents) to the
        streamer's lifetime_gmv_cents..."
        """
        bundle = setup_gold_streamer_for_commission()
        streamer_before = bundle["streamer"]
        app = bundle["application"]
        starts = bundle["starts_at"]
        ends = bundle["ends_at"]
        app = go_live(streamer_before, app, clock_at=starts)
        from prd_bench_local_runner.testing import get_success_data
        get_success_data(api.emit_event(
            emit_event_payload(
                source="ECOMMERCE", kind="BROADCAST_GMV",
                occurred_at=starts + timedelta(minutes=30),
                application_id=app["id"], amount_cents=6_000_000,
            ), ADMIN_HEADERS
        ))
        app = end_live(streamer_before, app, clock_at=ends)
        close_return_window(ends)
        settlement = fetch_settlement(app["id"])
        # Pay out
        get_success_data(api.payout_settlement(settlement["id"], ADMIN_HEADERS))
        settlement2 = fetch_settlement(app["id"])
        assert settlement2["status"] == "PAID"
        s = fetch_streamer(streamer_before["id"])
        # lifetime_gmv_cents must have increased by 6_000_000 (no returns)
        assert s["lifetime_gmv_cents"] >= streamer_before["lifetime_gmv_cents"] + 6_000_000

    def test_payout_from_non_ready_state_rejected(self, api):
        """PRD §3.8: "A PlatformAdmin then pays out a READY_FOR_PAYOUT
        settlement..." — implicit converse: paying out a non-ready settlement
        is an invalid state.
        """
        bundle = setup_gold_streamer_for_commission()
        streamer = bundle["streamer"]
        app = bundle["application"]
        starts = bundle["starts_at"]
        ends = bundle["ends_at"]
        app = go_live(streamer, app, clock_at=starts)
        app = end_live(streamer, app, clock_at=ends)
        settlement = fetch_settlement(app["id"])  # status WINDOW_OPEN
        resp = api.payout_settlement(settlement["id"], ADMIN_HEADERS)
        validate_error(resp, ERR_INVALID_STATE, expected_status=409)
