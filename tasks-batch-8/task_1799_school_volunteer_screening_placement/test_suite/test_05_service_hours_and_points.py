"""Hour logging, dual hour totals, and per-entry recognition points."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_volunteer,
    log_hours,
    make_volunteer_headers,
    setup_volunteer_with_confirmed_placement,
    validate_error,
    validate_paginated,
    validate_success,
    verify_entry,
)

DC = TEST_USERS["coordinator_headers"]
CA = TEST_USERS["campus_admin_headers"]


class TestDualHourTotals:
    def test_volunteer_hours_verified_and_provisional_variants(self, api):
        """PRD: "The official figure, `total_verified_hours`, sums the `hours`
        of entries in `VERIFIED` status only and feeds tier evaluation and
        reporting. The pipeline figure, `total_provisional_hours`, sums entries
        in `PENDING` or `VERIFIED`, giving an optimistic view that sits
        strictly above the verified total whenever unverified entries are
        outstanding. Entries in `REJECTED` or `REVOKED` count toward neither."

        Design: Difficulty/dual_variant_calc/volunteer_hours_provisional_vs_verified
        """
        scenario = setup_volunteer_with_confirmed_placement(
            full_name="Ann Hours", email="ann.hours@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]

        verified_entry = log_hours(placement["id"], vid,
                                   worked_date="2026-08-10", hours=3.0,
                                   activity_category="STANDARD")
        verify_entry(verified_entry["id"])
        # 2.0 TUTORING stays PENDING: inside the provisional set only.
        log_hours(placement["id"], vid, worked_date="2026-08-10", hours=2.0,
                  activity_category="TUTORING")

        volunteer = get_volunteer(vid)
        assert volunteer["total_verified_hours"] == pytest.approx(3.0)
        assert volunteer["total_provisional_hours"] == pytest.approx(5.0)
        # Only the VERIFIED 3.0 STANDARD entry feeds points so far.
        assert volunteer["recognition_points"] == pytest.approx(3.0)
        assert volunteer["recognition_tier"] == "NONE"

    def test_pending_entry_counts_only_toward_provisional(self, api):
        """PRD: "The pipeline figure, `total_provisional_hours`, sums entries
        in `PENDING` or `VERIFIED`, giving an optimistic view that sits
        strictly above the verified total whenever unverified entries are
        outstanding."
        PRD: "Verification recomputes both hour totals, recomputes the
        volunteer's `recognition_points` as the exact sum of the per-entry
        `points` over all `VERIFIED` entries, and re-evaluates the
        `recognition_tier`."

        Design: Difficulty/dual_variant_calc/volunteer_hours_provisional_vs_verified
        """
        scenario = setup_volunteer_with_confirmed_placement(
            full_name="Pending Penny", email="penny@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]

        entry = log_hours(placement["id"], vid, worked_date="2026-08-10",
                          hours=2.0, activity_category="TUTORING")
        mid = get_volunteer(vid)
        assert mid["total_verified_hours"] == pytest.approx(0.0)
        assert mid["total_provisional_hours"] == pytest.approx(2.0)
        assert mid["recognition_points"] == pytest.approx(0.0)

        verify_entry(entry["id"])
        after = get_volunteer(vid)
        assert after["total_verified_hours"] == pytest.approx(2.0)
        assert after["total_provisional_hours"] == pytest.approx(2.0)
        # 2.0 hours x 1.5 multiplier = 3.0 points once VERIFIED.
        assert after["recognition_points"] == pytest.approx(3.0)


class TestPointsRoundingOrder:
    def test_recognition_points_round_per_entry_then_sum(self, api):
        """PRD: "Recognition points are rounded per entry, not per aggregate:
        each hour entry's `points` value is rounded half up to one decimal
        place at creation, and the volunteer's `recognition_points` aggregate
        is the exact sum of those already-rounded per-entry values. Summing raw
        products first and rounding once at the end is not permitted — the two
        orders produce different results."
        PRD: "Consider a 2.5-hour `TUTORING` entry and a 1.25-hour `STANDARD`
        entry: they contribute 3.8 and 1.3 points respectively, raising the
        aggregate by 5.1, whereas summing the raw products and rounding once
        would wrongly yield 5.0."

        Design: Difficulty/combinatorial_formula/recognition_points_per_entry_round_then_sum
        """
        scenario = setup_volunteer_with_confirmed_placement(
            full_name="Point Pam", email="pam@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]

        e1 = log_hours(placement["id"], vid, worked_date="2026-08-10",
                       hours=2.5, activity_category="TUTORING")
        e2 = log_hours(placement["id"], vid, worked_date="2026-08-10",
                       hours=1.25, activity_category="STANDARD")
        verify_entry(e1["id"])
        verify_entry(e2["id"])

        volunteer = get_volunteer(vid)
        # Per-entry round-then-sum: 3.8 + 1.3 = 5.1 (never 5.0).
        assert volunteer["recognition_points"] == pytest.approx(5.1, abs=1e-6)
        assert volunteer["total_verified_hours"] == pytest.approx(3.75)

    def test_per_entry_points_rounded_half_up_at_creation(self, api):
        """PRD: "At creation the entry's `volunteer_id` is copied from the
        placement, its status starts at `PENDING`, and its `points` are
        computed immediately: the `hours` multiplied by the category multiplier
        — one for `STANDARD`, one and a half for `TUTORING`, two for
        `MENTORING` — rounded half up to one decimal place."
        PRD: "Consider a 2.5-hour `TUTORING` entry and a 1.25-hour `STANDARD`
        entry: they contribute 3.8 and 1.3 points respectively"

        Design: Difficulty/combinatorial_formula/recognition_points_per_entry_round_then_sum
        """
        scenario = setup_volunteer_with_confirmed_placement(
            full_name="Round Rita", email="round.rita@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]

        e1 = log_hours(placement["id"], vid, worked_date="2026-08-10",
                       hours=2.5, activity_category="TUTORING")
        e2 = log_hours(placement["id"], vid, worked_date="2026-08-10",
                       hours=1.25, activity_category="STANDARD")
        # Points exist at creation, ahead of any verification.
        assert e1["points"] == pytest.approx(3.8, abs=1e-6)
        assert e2["points"] == pytest.approx(1.3, abs=1e-6)
        assert e1["status"] == "PENDING"
        assert e2["status"] == "PENDING"


class TestRejection:
    def test_rejected_entry_excluded_from_totals(self, api):
        """PRD: "The pipeline figure, `total_provisional_hours`, sums entries
        in `PENDING` or `VERIFIED`, giving an optimistic view that sits
        strictly above the verified total whenever unverified entries are
        outstanding. Entries in `REJECTED` or `REVOKED` count toward neither."
        PRD: "Rejection, available to the same two roles, moves a `PENDING`
        entry to the terminal `REJECTED` status; the entry leaves the
        provisional set, `total_provisional_hours` is recomputed, and both the
        entry's and the volunteer's `version` increment by one"

        Design: Corner/calculations/rejected_entry_excluded_from_totals
        """
        scenario = setup_volunteer_with_confirmed_placement(
            full_name="Filter Flo", email="flo@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]

        entry = log_hours(placement["id"], vid, worked_date="2026-08-10",
                          hours=5.0, activity_category="STANDARD")
        before = get_volunteer(vid)
        assert before["total_provisional_hours"] == pytest.approx(5.0)
        assert before["total_verified_hours"] == pytest.approx(0.0)

        rejected = validate_success(api.reject_hour_entry(entry["id"], CA), 200)
        assert rejected["status"] == "REJECTED"

        after = get_volunteer(vid)
        assert after["total_provisional_hours"] == pytest.approx(0.0)
        assert after["total_verified_hours"] == pytest.approx(0.0)

    def test_verify_rejected_entry_rejected(self, api):
        """PRD: "A `CampusAdmin` or `DistrictCoordinator` verifies an entry
        that is still `PENDING` — any other status yields
        `ERR_HOUR_ENTRY_INVALID_STATE` — moving it to `VERIFIED`."

        Design: Corner/state_machines/verify_rejected_entry_rejected
        """
        scenario = setup_volunteer_with_confirmed_placement(
            full_name="Reject Rita", email="rita@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]

        entry = log_hours(placement["id"], vid, worked_date="2026-08-10",
                          hours=2.0, activity_category="STANDARD")
        validate_success(api.reject_hour_entry(entry["id"], CA), 200)

        verify = api.verify_hour_entry(entry["id"], CA)
        validate_error(verify, ApiErrorId.ERR_HOUR_ENTRY_INVALID_STATE)

        volunteer = get_volunteer(vid)
        assert volunteer["total_verified_hours"] == pytest.approx(0.0)
        assert volunteer["total_provisional_hours"] == pytest.approx(0.0)


class TestHourEntryGates:
    def test_hour_entry_rule_violations_rejected(self, api):
        """PRD: "A single entry may declare at most twelve hours — anything
        above twelve is rejected with `ERR_HOURS_EXCEED_LIMIT` — and must
        declare a positive amount with no more than two decimal places
        (otherwise `ERR_INVALID_REQUEST`)."
        PRD: "The referenced placement must be `CONFIRMED` or `COMPLETED`
        (otherwise `ERR_PLACEMENT_INVALID_STATE`), and the `worked_date` must
        fall on or between the calendar date of the opportunity's `starts_at`
        and the calendar date of its `ends_at` (otherwise
        `ERR_HOURS_OUTSIDE_PLACEMENT_WINDOW`)."

        Design: Corner/validations/hour_entry_rule_violations_rejected
        """
        scenario = setup_volunteer_with_confirmed_placement(
            full_name="Rules Rudy", email="rudy@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]

        too_many = api.create_hour_entry(
            {"placement_id": placement["id"], "worked_date": "2026-08-10",
             "hours": 13.0, "activity_category": "STANDARD"},
            make_volunteer_headers(vid))
        validate_error(too_many, ApiErrorId.ERR_HOURS_EXCEED_LIMIT)

        outside = api.create_hour_entry(
            {"placement_id": placement["id"], "worked_date": "2026-08-20",
             "hours": 2.0, "activity_category": "STANDARD"},
            make_volunteer_headers(vid))
        validate_error(outside, ApiErrorId.ERR_HOURS_OUTSIDE_PLACEMENT_WINDOW)

        _, meta = validate_paginated(api.list_hour_entries(
            DC, params={"placement_id": placement["id"]}))
        assert meta["total_count"] == 0
