"""Union eligibility rolling counter: the >=3 flip threshold and the inclusive
365-day window's input filtering (PRD section 3.9).

Engagement dates are chosen so each booking's engagement_start lies inside the
inclusive window [clock - 365 days, clock] at the moment it is confirmed.
"""
from test_helpers import (
    book_talent_on_new_role,
    create_production,
    create_talent,
    set_clock,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]


def _union_production():
    return create_production(title="UP", production_type="TV_SERIES", union_signatory=True)


class TestUnionThresholdFlip:
    def test_third_union_engagement_flips_status(self, api):
        """PRD section 3.9: "When a `NON_UNION` talent's count reaches at least
        three — the third qualifying engagement is the flip point — the talent's
        `union_status` becomes `ELIGIBLE_PENDING`."
        PRD section 3.9: "The count is recomputed on the booking-creation path, on
        confirmation (the increment path), and on cancellation from `CONFIRMED`
        (the decrement path)."

        Design: Difficulty/boundary_precision_check/union_threshold_exactly_three_flips
        """
        set_clock("2026-08-03T00:00:00Z")
        production = _union_production()
        talent = create_talent(union_status="NON_UNION")
        book_talent_on_new_role(
            production["id"], talent, "UR1", "2026-08-01", "2026-08-02", session_date="2026-08-04"
        )
        book_talent_on_new_role(
            production["id"], talent, "UR2", "2026-08-03", "2026-08-04", session_date="2026-08-05"
        )
        third = book_talent_on_new_role(
            production["id"], talent, "UR3", "2026-08-05", "2026-08-06", session_date="2026-08-06", confirm=False
        )
        pre = validate_success(api.get_talent(talent["id"], DIRECTOR))
        assert pre["union_engagement_count_365d"] == 2, "two in-window CONFIRMED union-covered bookings before the trigger"
        assert pre["union_status"] == "NON_UNION", "count 2 is below the threshold"
        validate_success(api.confirm_booking(third["booking"]["id"], TEST_USERS["coordinator_headers"]))
        post = validate_success(api.get_talent(talent["id"], DIRECTOR))
        assert post["union_engagement_count_365d"] == 3, "the third confirmed engagement is counted"
        assert post["union_status"] == "ELIGIBLE_PENDING", "count == 3 meets the >= threshold exactly"

    def test_two_engagements_stay_below_threshold(self, api):
        """PRD section 3.9: "When a `NON_UNION` talent's count reaches at least
        three — the third qualifying engagement is the flip point — the talent's
        `union_status` becomes `ELIGIBLE_PENDING`."

        Design: Difficulty/boundary_precision_check/union_threshold_exactly_three_flips
        """
        set_clock("2026-08-03T00:00:00Z")
        production = _union_production()
        talent = create_talent(union_status="NON_UNION")
        book_talent_on_new_role(
            production["id"], talent, "UR1", "2026-08-01", "2026-08-02", session_date="2026-08-04"
        )
        book_talent_on_new_role(
            production["id"], talent, "UR2", "2026-08-03", "2026-08-04", session_date="2026-08-05"
        )
        post = validate_success(api.get_talent(talent["id"], DIRECTOR))
        assert post["union_engagement_count_365d"] == 2
        assert post["union_status"] == "NON_UNION", "two engagements do not reach the three-engagement threshold"


class TestUnionWindowFiltering:
    def test_engagement_outside_window_excluded_from_count(self, api):
        """PRD section 3.9: "A talent's `union_engagement_count_365d` counts their
        `CONFIRMED` bookings — `PENDING` and `CANCELLED` excluded — on roles with
        `is_union_covered`, where the backing memo's `engagement_start` falls
        inside the inclusive window from 365 days before the current logical clock
        through the clock itself, both ends included."

        Design: Corner/calculations/tafthartley_eligibility_window_excludes_outside
        """
        set_clock("2026-08-03T00:00:00Z")
        production = _union_production()
        talent = create_talent(union_status="NON_UNION")
        # In-window engagement: engagement_start 2026-08-03 <= clock at confirm.
        book_talent_on_new_role(
            production["id"], talent, "IN", "2026-08-03", "2026-08-04", session_date="2026-08-04"
        )
        # Out-of-window engagement: engagement_start 2026-08-20 lies AFTER the
        # clock at confirm time (2026-08-05), outside the window's inclusive end.
        book_talent_on_new_role(
            production["id"], talent, "OUT", "2026-08-20", "2026-08-21", session_date="2026-08-05"
        )
        post = validate_success(api.get_talent(talent["id"], DIRECTOR))
        assert post["union_engagement_count_365d"] == 1, (
            "only the in-window confirmed union-covered engagement is counted"
        )
        assert post["union_status"] == "NON_UNION", "count 1 < threshold 3, no flip"
