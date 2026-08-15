"""Provider education score bands: boundary precision and zero-floor invariant."""
import pytest

from test_helpers import (
    assert_provider_education_invariants,
    drive_education_score,
    setup_sent_query,
    validate_success,
)


class TestScoreBandBoundary85:
    def test_score_85_is_none(self, api, cdi_manager_headers):
        """PRD §3.8: "The flag bands are exact: a score of 85 or higher yields
        `NONE`; 70 through 84 yields `WATCH`"
        PRD §3.8: "The boundary behavior matters: 85 is `NONE` while 84 is
        `WATCH`"

        Design: Difficulty/boundary_precision_check/education_score_threshold_85_is_none_84_is_watch
        """
        scenario = setup_sent_query()
        provider_id = scenario["provider"]["id"]
        drive_education_score(provider_id, scenario["query"]["id"], 15)
        provider = validate_success(api.get_provider(provider_id, cdi_manager_headers))
        assert provider["education_score"] == 85
        assert provider["education_flag"] == "NONE"
        assert_provider_education_invariants(provider)

    def test_score_84_is_watch(self, api, cdi_manager_headers):
        """PRD §3.8: "The boundary behavior matters: 85 is `NONE` while 84 is
        `WATCH`; 70 is `WATCH` while 69 is `COACHING`; 50 is `COACHING` while 49
        is `INTENSIVE_REVIEW`."

        Design: Difficulty/boundary_precision_check/education_score_threshold_85_is_none_84_is_watch
        """
        scenario = setup_sent_query()
        provider_id = scenario["provider"]["id"]
        drive_education_score(provider_id, scenario["query"]["id"], 15)
        drive_education_score(provider_id, scenario["query"]["id"], 1)
        provider = validate_success(api.get_provider(provider_id, cdi_manager_headers))
        assert provider["education_score"] == 84
        assert provider["education_flag"] == "WATCH"
        assert_provider_education_invariants(provider)


class TestZeroFloorInvariant:
    def test_score_floors_at_zero(self, api, cdi_manager_headers):
        """PRD §3.8: "The score is 100 minus the total points deducted across all
        of the provider's education events regardless of age, floored at zero."
        PRD §3.8: "below 50 yields `INTENSIVE_REVIEW`"

        Design: Difficulty/compensating_invariant/education_score_compensating_events_conserve_at_zero_floor
        """
        scenario = setup_sent_query()
        provider_id = scenario["provider"]["id"]
        # Five 25-point events = 125 points total, more than the initial 100.
        for tag in ("LEADING_LANGUAGE", "LEADING_LANGUAGE", "NO_RESPONSE_PATTERN",
                    "CLINICALLY_UNSUPPORTED_PATTERN", "OVERDUE_PATTERN"):
            drive_education_score(provider_id, scenario["query"]["id"], 25, pattern_tag=tag)
        provider = validate_success(api.get_provider(provider_id, cdi_manager_headers))
        assert provider["education_score"] == 0
        assert provider["education_flag"] == "INTENSIVE_REVIEW"
        assert_provider_education_invariants(provider)

    def test_score_at_exactly_100_minus_points(self, api, cdi_manager_headers):
        """PRD §3.8: "Each event subtracts its `points_deducted` from the
        provider's `education_score` (which never falls below 0), increments
        `pattern_tally_json` for that `pattern_tag` by 1"
        PRD §3.8: "50 through 69 yields `COACHING`"

        Design: Difficulty/compensating_invariant/education_score_compensating_events_conserve_at_zero_floor
        """
        scenario = setup_sent_query()
        provider_id = scenario["provider"]["id"]
        drive_education_score(provider_id, scenario["query"]["id"], 40)
        provider = validate_success(api.get_provider(provider_id, cdi_manager_headers))
        assert provider["education_score"] == 60
        assert provider["education_flag"] == "COACHING"
        assert provider["pattern_tally_json"]["LEADING_LANGUAGE"] == 2
        assert_provider_education_invariants(provider)
