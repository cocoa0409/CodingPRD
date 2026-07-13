"""Helper vetting cycle and the rating-driven auto-suspension cascade."""
import pytest

from test_helpers import (
    validate_success,
    create_config, create_approved_helper, vet_helper,
    create_booked_job, assign_helper, setup_completed_ratable_job,
    create_rating_payload, make_customer_headers, ADMIN, api_client,
)


class TestSuspendReinstateCycle:
    """Design: Difficulty/non_linear_state_machine/helper_suspend_reinstate_cycle"""

    def test_reinstate_returns_suspended_helper_to_approved(self, api):
        """PRD §3.2: "An `APPROVED` helper may be moved to `SUSPENDED` with a `SUSPEND`
        decision, and a `SUSPENDED` helper may be returned to `APPROVED` with a `REINSTATE`
        decision."

        Design: Difficulty/non_linear_state_machine/helper_suspend_reinstate_cycle
        """
        helper = create_approved_helper(api)
        vet_helper(api, helper["id"], "SUSPEND")
        reinstated = validate_success(api.vet_helper(helper["id"], {"decision": "REINSTATE"}, ADMIN))
        assert reinstated["vetting_status"] == "APPROVED"

    def test_suspend_then_reinstate_traverses_both_states(self, api):
        """PRD §3.2: "An `APPROVED` helper may be moved to `SUSPENDED` with a `SUSPEND`
        decision, and a `SUSPENDED` helper may be returned to `APPROVED` with a `REINSTATE`
        decision."

        The vetting machine cycles APPROVED -> SUSPENDED -> APPROVED.

        Design: Difficulty/non_linear_state_machine/helper_suspend_reinstate_cycle
        """
        helper = create_approved_helper(api)
        suspended = validate_success(api.vet_helper(helper["id"], {"decision": "SUSPEND"}, ADMIN))
        assert suspended["vetting_status"] == "SUSPENDED"
        reinstated = validate_success(api.vet_helper(helper["id"], {"decision": "REINSTATE"}, ADMIN))
        assert reinstated["vetting_status"] == "APPROVED"


class TestRatingCascade:
    """Design: Difficulty/transitive_cascade/rating_suspends_helper_releases_assignment"""

    def _rate_one_star_after_setup(self, api):
        rate_card, policy, customer = create_config(api)
        helper = create_approved_helper(api, email="ha@x.com")
        jc1, asg1 = setup_completed_ratable_job(
            api, helper, rate_card, policy, customer,
            window_start="2026-03-10T09:00:00Z", window_end="2026-03-10T12:00:00Z",
            estimated_hours=3.0, actual_hours=3.0,
        )
        jc2, _q = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=1, estimated_hours=3.0,
            window_start="2026-03-20T09:00:00Z", window_end="2026-03-20T12:00:00Z",
        )
        asg2 = assign_helper(api, jc2["id"], helper["id"], role="LEAD")
        validate_success(api.create_rating(
            create_rating_payload(jc1["id"], helper["id"], 1, comment="bad"),
            make_customer_headers(customer["id"]),
        ), 201)
        return helper, asg1, asg2

    def test_low_rating_auto_suspends_helper(self, api):
        """PRD §3.9: "the helper's `rating_avg` becomes the mean of the `stars` across those
        ratings, rounded half up to two decimal places". PRD §3.9: "if, after the new rating,
        the helper's `rating_avg` is below 2.0 and the helper is currently `APPROVED`, the
        helper is automatically transitioned `APPROVED → SUSPENDED`".

        Design: Difficulty/transitive_cascade/rating_suspends_helper_releases_assignment
        """
        helper, _asg1, _asg2 = self._rate_one_star_after_setup(api)
        refreshed = validate_success(api.get_helper(helper["id"], ADMIN))
        assert refreshed["rating_avg"] == 1.0
        assert refreshed["vetting_status"] == "SUSPENDED"

    def test_auto_suspension_releases_assigned_assignment(self, api):
        """PRD §3.2: "every one of that helper's assignments currently in status `ASSIGNED`
        is transitioned `ASSIGNED → RELEASED`, and each such release decrements that helper's
        `active_assignment_count`, which is recomputed as the number of the helper's
        assignments whose status is `ASSIGNED`, `CHECKED_IN`, or `CHECKED_OUT`."

        The still-ASSIGNED future assignment is released; the CHECKED_OUT one is untouched,
        leaving the count at 1.

        Design: Difficulty/transitive_cascade/rating_suspends_helper_releases_assignment
        """
        helper, asg1, asg2 = self._rate_one_star_after_setup(api)
        released = validate_success(api.get_assignment(asg2["id"], ADMIN))
        kept = validate_success(api.get_assignment(asg1["id"], ADMIN))
        assert released["status"] == "RELEASED"
        assert kept["status"] == "CHECKED_OUT"
        refreshed = validate_success(api.get_helper(helper["id"], ADMIN))
        assert refreshed["active_assignment_count"] == 1
