"""Validation pipeline order on seasonal creation: temporal sanity (tier 6)
precedes schedule conflict (tier 7); season span boundary (PRD §2.9, §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    make_renter_headers,
    make_site, make_facility, make_policy, make_renter, make_insurance,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

DIRECTOR = TEST_USERS["director_headers"]
ADMIN = TEST_USERS["admin_headers"]

NP_ATH_POLICY = {
    "policy_code": "NP-ATH", "rate_class": "NONPROFIT", "facility_tier": "ATHLETIC",
    "hourly_rate_cents": 9000, "deposit_basis_points": 2000,
    "custodial_hourly_cents": 4500, "effective_from": "2026-01-01T00:00:00Z",
    "deposit_floor_cents": 15000,
}


def _soccer_env(api):
    site = make_site("FHS", display_name="Fairview High")
    facility = make_facility(site["id"], facility_code="FIELD",
                             facility_tier="ATHLETIC", capacity=1000)
    make_policy(**NP_ATH_POLICY)
    org = make_renter("City Soccer League")
    make_insurance(org["id"], per_occurrence_limit_cents=200000000,
                   aggregate_limit_cents=400000000,
                   effective_to="2027-06-01T00:00:00Z")
    return site, facility, org


class TestTemporalVsConstraintOnSeasonalCreate:
    def test_overspan_season_with_conflicting_occurrence_reports_temporal_error(self, api):
        """PRD §2.9: "the server evaluates them in a fixed priority order and
        surfaces the first failure; a failure at an earlier tier masks every later
        tier."
        PRD §3.9: "the end must be at or after the start and the whole span may not
        exceed 120 days — a longer season is rejected with `ERR_INVALID_TIME_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_seasonal_create
        """
        site, facility, org = _soccer_env(api)
        # Existing SCHEDULED tier-0 event overlapping the first occurrence
        # (constraint violation at tier 7)...
        validate_success(api.create_calendar_event(
            site["id"],
            {"facility_id": facility["id"], "title": "Varsity Match",
             "starts_at": "2026-09-05T18:00:00Z", "ends_at": "2026-09-05T22:00:00Z",
             "event_priority_tier": 0},
            ADMIN), 201)
        # ...AND a 207-day season span (temporal violation at tier 6).
        res = api.create_seasonal_permit(
            {"renter_org_id": org["id"], "facility_id": facility["id"],
             "series_name": "Fall Soccer", "recurrence_rule": "WEEKLY:SAT:18:00-21:00",
             "season_start": "2026-09-05T00:00:00Z", "season_end": "2027-03-31T00:00:00Z"},
            make_renter_headers(org["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_TIME_WINDOW)

        series = validate_success(api.list_seasonal_permits(DIRECTOR))
        assert series == [], "no SeasonalPermit row created"

    def test_season_span_boundary_120_accepted_121_rejected(self, api):
        """PRD §3.9: "the end must be at or after the start and the whole span may
        not exceed 120 days — a longer season is rejected with
        `ERR_INVALID_TIME_WINDOW`."
        PRD §2.4: "every day-count threshold in this document is inclusive of its
        lower bound."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_seasonal_create
        """
        site, facility, org = _soccer_env(api)
        # 2026-09-05 .. 2027-01-03 spans exactly 120 days -> accepted.
        ok = api.create_seasonal_permit(
            {"renter_org_id": org["id"], "facility_id": facility["id"],
             "series_name": "Boundary Season", "recurrence_rule": "WEEKLY:SAT:18:00-21:00",
             "season_start": "2026-09-05T00:00:00Z", "season_end": "2027-01-03T00:00:00Z"},
            make_renter_headers(org["id"]))
        assert ok.status_code == 201, f"120-day span must be accepted: {ok.text}"

        # 2026-09-05 .. 2027-01-04 spans 121 days -> rejected on the temporal tier.
        res = api.create_seasonal_permit(
            {"renter_org_id": org["id"], "facility_id": facility["id"],
             "series_name": "Overlong Season", "recurrence_rule": "WEEKLY:SAT:18:00-21:00",
             "season_start": "2026-09-05T00:00:00Z", "season_end": "2027-01-04T00:00:00Z"},
            make_renter_headers(org["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_TIME_WINDOW)
