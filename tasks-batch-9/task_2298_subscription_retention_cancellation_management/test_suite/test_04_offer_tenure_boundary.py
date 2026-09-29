"""The inclusive tenure boundary on the only eligible save-offer template.

The single candidate template demands 60 days of tenure.  One day short the offer
round is refused and the session is left untouched; on the day tenure reads exactly
60 the same round mints the grant.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    make_retention_specialist_headers,
    new_core_plan,
    new_template,
    read_session,
    read_subscriber,
    set_clock,
    setup_active_subscription,
    setup_reason_captured_session,
    validate_error,
    validate_success,
)

TENURE_GATED_TEMPLATE = {
    "offer_type": "DISCOUNT",
    "discount_pct": 0.3500,
    "discount_cycles": 2,
    "priority_rank": 30,
    "min_tenure_days": 60,
    "eligible_reason_codes": ["PRICE"],
}


def _session_one_day_short_of_the_tenure_floor():
    """Sign up 2026-01-10 and stop the clock on 2026-03-10, where tenure reads 59."""
    plan = new_core_plan()
    template = new_template(**TENURE_GATED_TEMPLATE)
    world = setup_active_subscription(clock="2026-01-10", plan=plan)
    set_clock("2026-03-10")
    world["template"] = template
    world["session"] = setup_reason_captured_session(world, reason_code="PRICE")
    return world


class TestOfferTenureBoundary:

    def test_tenure_one_day_short_refuses_the_round_and_leaves_the_session_alone(self):
        """Tenure 59 against min_tenure_days 60 is a tenure rejection, not an empty pool.

        PRD §3.6: "First, if every `ACTIVE` template whose `eligible_reason_codes`
        contains the session's `reason_code` was excluded *solely* because the
        subscriber's `tenure_days` fell below `min_tenure_days`, the round is
        rejected with `ERR_TENURE_REQUIREMENT_NOT_MET` (422) — and in that case the
        empty-pool rejection below does not fire." and "All three rejections leave
        the session exactly as it was: `state` stays `REASON_CAPTURED`, and
        `offers_presented_count` and `step_count` are unchanged, so the subscriber
        can still complete within the simple-cancellation budget."

        Design: Difficulty/boundary_precision_check/min_tenure_days_inclusive_boundary_59_versus_60
        """
        world = _session_one_day_short_of_the_tenure_floor()

        assert read_subscriber(world["subscriber"]["id"])["tenure_days"] == 59

        response = api_client.present_offers(
            world["session"]["id"], make_retention_specialist_headers("rs_4"))
        validate_error(response, ApiErrorId.ERR_TENURE_REQUIREMENT_NOT_MET, 422)

        session = read_session(world["session"]["id"])
        assert session["state"] == "REASON_CAPTURED"
        assert session["step_count"] == 2
        assert session["offers_presented_count"] == 0
        assert session["presented_by_user_id"] is None

    def test_tenure_exactly_at_the_floor_qualifies_and_mints_the_grant(self):
        """One day later tenure reads 60 and the same template becomes a candidate.

        PRD §3.1: "`min_tenure_days` is the minimum subscriber tenure in days, with
        an inclusive boundary — a subscriber whose tenure exactly equals it
        qualifies — and it defaults to 0."

        Design: Difficulty/boundary_precision_check/min_tenure_days_inclusive_boundary_59_versus_60
        """
        world = _session_one_day_short_of_the_tenure_floor()

        set_clock("2026-03-11")
        assert read_subscriber(world["subscriber"]["id"])["tenure_days"] == 60

        response = api_client.present_offers(
            world["session"]["id"], make_retention_specialist_headers("rs_4"))
        grant = validate_success(response, 201)

        assert grant["save_offer_template_id"] == world["template"]["id"]
        assert grant["state"] == "PRESENTED"
        assert grant["blended_term_margin_pct"] == pytest.approx(0.5115, abs=5e-5)

        session = read_session(world["session"]["id"])
        assert session["state"] == "OFFERS_PRESENTED"
        assert session["step_count"] == 3
        assert session["offers_presented_count"] == 1
