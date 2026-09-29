"""Line-level invoice construction, the offer selector's ranking key and the retry clamp.

Each of these is a place where the arithmetic must be read exactly as written: lines are
rounded then summed in a pinned order, the selector ranks on priority before profit, and
the retry schedule is bounded by the grace window rather than by the backoff list.
"""

import pytest

from test_helpers import (
    assert_dunning_attempt,
    assert_instant,
    assert_line_items_pinned_order,
    assert_lines_sum_to_amount,
    assert_margin_exception_consistency,
    create_attempt,
    new_template,
    read_invoice,
    read_session,
    read_subscription,
    present_offers,
    set_clock,
    settle_attempt,
    setup_active_subscription,
    setup_dunning_chain,
    setup_reason_captured_session,
    signup_invoice,
)


class TestInvoiceLineConstruction:

    def test_the_signup_invoice_records_a_plan_line_then_the_addon_line(self):
        """4999 plus 1299 is billed as two rounded lines summing to 6298 against 2620 of cogs.

        PRD §3.4: "`line_items` records the breakdown in a pinned order — the plan line
        first, then one line per addon ordered by `code` ascending — and each entry carries
        a `kind`, a `code`, a `unit_price_cents`, a `qty` and a `line_cents`."

        Design: Corner/calculations/signup_invoice_amount_and_cogs_match_the_pinned_line_construction
        """
        world = setup_active_subscription(
            clock="2026-01-10",
            subscriber_overrides={"acquisition_channel": "SEARCH"},
            addons=[{"code": "MUG", "qty": 1}])

        invoice = signup_invoice(world["subscription"]["id"])
        assert invoice["amount_cents"] == 6298
        assert invoice["cogs_cents"] == 2620
        assert invoice["proration_factor"] == pytest.approx(1.0000, abs=5e-5)

        lines = invoice["line_items"]
        assert len(lines) == 2
        assert_line_items_pinned_order(invoice)
        assert_lines_sum_to_amount(invoice)

        assert lines[0]["kind"] == "PLAN"
        assert lines[0]["code"] == world["plan"]["code"]
        assert lines[0]["unit_price_cents"] == 4999
        assert lines[0]["line_cents"] == 4999

        assert lines[1]["kind"] == "ADDON"
        assert lines[1]["code"] == "MUG"
        assert lines[1]["unit_price_cents"] == 1299
        assert lines[1]["qty"] == 1
        assert lines[1]["line_cents"] == 1299


class TestSelectorRanking:

    def test_the_lower_ranked_template_wins_even_though_it_earns_less(self):
        """Rank 5 at a 0.4877 blended margin beats rank 60 at 0.5691.

        PRD §3.6: "Candidates are ordered by `priority_rank` ascending; where those tie, by
        `blended_term_margin_pct` descending; and where both tie, by `created_at`
        ascending."

        Design: Corner/calculations/selector_priority_rank_dominates_a_richer_blended_margin
        """
        deep_but_prioritised = new_template(
            code="T_R5", offer_type="DISCOUNT", discount_pct=0.4500, discount_cycles=2,
            priority_rank=5, eligible_reason_codes=["PRICE"])
        shallow_but_deprioritised = new_template(
            code="T_R60", offer_type="DISCOUNT", discount_pct=0.1000, discount_cycles=1,
            priority_rank=60, eligible_reason_codes=["PRICE"])

        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        session = setup_reason_captured_session(world, reason_code="PRICE")

        grant = present_offers(session["id"], as_user_id="rs_1")
        assert grant["save_offer_template_id"] == deep_but_prioritised["id"]
        assert grant["save_offer_template_id"] != shallow_but_deprioritised["id"]

        # Two offer cycles at 2749 plus three post-offer cycles at 4999 against 2100 of
        # cogs each: 9995 of margin on 20495 of revenue.
        assert grant["per_cycle_margin_pct"] == pytest.approx(0.2361, abs=5e-5)
        assert grant["blended_term_margin_pct"] == pytest.approx(0.4877, abs=5e-5)
        assert grant["retention_value_cents"] == 9995
        assert grant["margin_exception_required"] is False
        assert grant["margin_exception_state"] == "NOT_REQUIRED"
        assert_margin_exception_consistency(grant)
        assert_instant(grant["expires_at"], "2026-01-12T00:00:00Z", "expires_at")

        presented = read_session(session["id"])
        assert presented["state"] == "OFFERS_PRESENTED"
        assert presented["presented_by_user_id"] == "rs_1"


class TestRetryScheduleClamp:

    def test_the_third_attempt_is_pulled_back_to_grace_end_and_marked_final(self):
        """Attempt two lands inside the window at its raw date; attempt three is clamped.

        PRD §3.7: "Fifth, `scheduled_at` is the **earlier** of the raw schedule instant and
        the subscription's `grace_end_at`. Sixth, `grace_clamped` is true exactly when the
        raw schedule instant fell **strictly after** `grace_end_at`, and `is_final` is set
        to the same value: a clamped attempt is the last one this invoice will get."

        Design: Corner/calculations/retry_schedule_clamps_to_grace_end_and_marks_the_attempt_final
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        first_attempt = setup_dunning_chain(world, ["INSUFFICIENT_FUNDS"])[0]

        subscription = read_subscription(world["subscription"]["id"])
        assert_instant(subscription["first_failed_at"], "2026-01-10T00:00:00Z", "first_failed_at")
        # A brand-new subscriber sits in M0_1, so the bare allowance is three days.
        assert_instant(subscription["grace_end_at"], "2026-01-13T00:00:00Z", "grace_end_at")

        second_attempt = create_attempt(world["invoice"]["id"])
        assert_dunning_attempt(second_attempt)
        assert second_attempt["attempt_number"] == 2
        assert second_attempt["previous_attempt_id"] == first_attempt["id"]
        assert second_attempt["backoff_days_applied"] == 1
        assert_instant(second_attempt["scheduled_at"], "2026-01-11T00:00:00Z", "scheduled_at")
        assert second_attempt["grace_clamped"] is False
        assert second_attempt["is_final"] is False

        set_clock("2026-01-11")
        settle_attempt(world["invoice"]["id"], "SOFT_DECLINE", "INSUFFICIENT_FUNDS")

        third_attempt = create_attempt(world["invoice"]["id"])
        assert third_attempt["attempt_number"] == 3
        # Attempt three reads the second position of the INSUFFICIENT_FUNDS list, so its
        # raw date 2026-01-14 falls strictly after the window and is pulled back.
        assert third_attempt["backoff_days_applied"] == 3
        assert_instant(third_attempt["scheduled_at"], "2026-01-13T00:00:00Z", "scheduled_at")
        assert third_attempt["grace_clamped"] is True
        assert third_attempt["is_final"] is True

        assert read_invoice(world["invoice"]["id"])["attempt_count"] == 3
        assert read_subscription(world["subscription"]["id"])["consecutive_failed_attempts"] == 2
