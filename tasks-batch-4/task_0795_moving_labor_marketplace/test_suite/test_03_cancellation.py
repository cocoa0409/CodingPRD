"""Cancellation pricing by notice, and the release cascade / slot-count invariant on
cancelling a booked job."""
import pytest

from test_helpers import (
    validate_success,
    create_config, create_booked_job, create_approved_helper, assign_helper,
    set_clock, make_customer_headers, ADMIN, api_client,
)


def _booked_job_window_0310(api):
    """A crew-1, 3.0h weekday job (window 2026-03-10T09:00Z) booked at the default clock.
    Its estimated_total_cents is 20700."""
    rate_card, policy, customer = create_config(api)
    booked, _quote = create_booked_job(
        api, rate_card["id"], policy["id"], customer["id"],
        crew_size=1, estimated_hours=3.0,
        window_start="2026-03-10T09:00:00Z", window_end="2026-03-10T12:00:00Z",
    )
    return customer, booked


def test_cancel_booked_job_with_short_notice_charges_fee(api):
    """PRD §3.4: "otherwise it is the job's `estimated_total_cents` multiplied by 20%,
    rounded half up to cents. Either way `final_total_cents` is set equal to
    `cancellation_fee_cents`."

    Cancelling the 20700 booked job 9 hours before window_start (<24h) charges
    round_half_up(20700*0.20) = 4140.

    Design: Corner/calculations/cancellation_fee_late_charge
    """
    customer, booked = _booked_job_window_0310(api)
    set_clock(api, "2026-03-10T00:00:00Z")  # 9h before the 09:00 window
    cancelled = validate_success(api.cancel_job(booked["id"], make_customer_headers(customer["id"])))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 4140
    assert cancelled["final_total_cents"] == 4140


def test_cancel_booked_job_with_long_notice_is_free(api):
    """PRD §3.4: "If that notice is at least 24 hours — the boundary of exactly 24 hours
    before `window_start` is treated as free — then `cancellation_fee_cents` is 0".

    Cancelling while the clock is still 2026-03-01 (>=24h before the 2026-03-10 window) is
    free.

    Design: Corner/calculations/cancellation_free_early_window
    """
    customer, booked = _booked_job_window_0310(api)
    cancelled = validate_success(api.cancel_job(booked["id"], make_customer_headers(customer["id"])))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 0


class TestSlotCountConservedOnCancel:
    """Design: Difficulty/compensating_invariant/assignment_slots_conserved_on_cancel"""

    def _assigned_then_cancelled(self, api):
        rate_card, policy, customer = create_config(api)
        helper = create_approved_helper(api, email="hb@x.com")
        booked, _quote = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=1, estimated_hours=3.0,
            window_start="2026-03-11T09:00:00Z", window_end="2026-03-11T12:00:00Z",
        )
        assignment = assign_helper(api, booked["id"], helper["id"])
        validate_success(api.cancel_job(booked["id"], make_customer_headers(customer["id"])))
        return helper, assignment

    def test_cancel_releases_the_assignment(self, api):
        """PRD §3.4: "Cancelling a booked job also releases the crew and truck: every
        assignment of the job in status `ASSIGNED` or `CHECKED_IN` transitions to
        `RELEASED`".

        Design: Difficulty/compensating_invariant/assignment_slots_conserved_on_cancel
        """
        _helper, assignment = self._assigned_then_cancelled(api)
        released = validate_success(api.get_assignment(assignment["id"], ADMIN))
        assert released["status"] == "RELEASED"

    def test_cancel_restores_helper_active_assignment_count(self, api):
        """PRD §3.4: "each such release decrementing the corresponding helper's
        `active_assignment_count`". PRD §3.2: "which is recomputed as the number of the
        helper's assignments whose status is `ASSIGNED`, `CHECKED_IN`, or `CHECKED_OUT`."

        Releasing the sole assignment returns the count to 0.

        Design: Difficulty/compensating_invariant/assignment_slots_conserved_on_cancel
        """
        helper, _assignment = self._assigned_then_cancelled(api)
        refreshed = validate_success(api.get_helper(helper["id"], ADMIN))
        assert refreshed["active_assignment_count"] == 0
