"""Recognition tiers, auto-awards, revocation compensation, manual grants."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_recognition_award_payload,
    create_volunteer_applied,
    get_success_data,
    get_volunteer,
    list_awards_for,
    log_and_verify_hours,
    log_hours,
    setup_volunteer_with_confirmed_placement,
    validate_error,
    validate_paginated,
    validate_success,
    verify_entry,
)

DC = TEST_USERS["coordinator_headers"]
CA = TEST_USERS["campus_admin_headers"]

WEEK = {"starts_at": "2026-08-03T08:00:00Z", "ends_at": "2026-08-07T20:00:00Z"}


def _week_scenario(name, email):
    return setup_volunteer_with_confirmed_placement(
        full_name=name, email=email, opp_overrides=dict(WEEK, capacity=2))


class TestTierBoundaries:
    def test_exactly_fifty_verified_hours_yields_silver(self, api):
        """PRD: "The recognition ladder has three rungs above `NONE`: `BRONZE`
        at twenty verified hours, `SILVER` at fifty, and `GOLD` at one hundred.
        Boundaries are inclusive — a volunteer at exactly 50.0 verified hours
        holds `SILVER` — and the comparison runs against the two-decimal
        `total_verified_hours`."
        PRD: "Whenever a recompute raises the tier, the system automatically
        creates a RecognitionAward with `source` `AUTO` for the new tier,
        unless one already exists for that volunteer and tier; tier decreases
        create nothing."

        Design: Difficulty/boundary_precision_check/tier_boundary_exactly_fifty_hours
        """
        scenario = _week_scenario("Boundary Bea", "bea@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]

        for day in ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"):
            log_and_verify_hours(placement["id"], vid, worked_date=day,
                                 hours=12.0)
        mid = get_volunteer(vid)
        assert mid["total_verified_hours"] == pytest.approx(48.0)
        assert mid["recognition_tier"] == "BRONZE"

        pending = log_hours(placement["id"], vid, worked_date="2026-08-07",
                            hours=2.0)
        verify_entry(pending["id"])

        after = get_volunteer(vid)
        assert after["total_verified_hours"] == pytest.approx(50.0)
        assert after["recognition_tier"] == "SILVER", (
            "The fifty-hour boundary is inclusive")

        awards, meta = list_awards_for(vid)
        assert meta["total_count"] == 2
        assert {a["tier"] for a in awards} == {"BRONZE", "SILVER"}
        assert all(a["source"] == "AUTO" for a in awards)

    def test_exactly_twenty_verified_hours_yields_bronze(self, api):
        """PRD: "The recognition ladder has three rungs above `NONE`: `BRONZE`
        at twenty verified hours, `SILVER` at fifty, and `GOLD` at one hundred.
        Boundaries are inclusive — a volunteer at exactly 50.0 verified hours
        holds `SILVER` — and the comparison runs against the two-decimal
        `total_verified_hours`."

        Design: Difficulty/boundary_precision_check/tier_boundary_exactly_fifty_hours
        """
        scenario = _week_scenario("Twenty Tim", "tim@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]

        log_and_verify_hours(placement["id"], vid, worked_date="2026-08-03",
                             hours=10.0)
        log_and_verify_hours(placement["id"], vid, worked_date="2026-08-04",
                             hours=10.0)

        after = get_volunteer(vid)
        assert after["total_verified_hours"] == pytest.approx(20.0)
        assert after["recognition_tier"] == "BRONZE", (
            "The twenty-hour boundary is inclusive")

        awards, meta = list_awards_for(vid)
        assert meta["total_count"] == 1
        assert awards[0]["tier"] == "BRONZE"
        assert awards[0]["source"] == "AUTO"


class TestVerifyTierAwardCascade:
    def test_verify_crossing_bronze_auto_awards(self, api):
        """PRD: "Verification recomputes both hour totals, recomputes the
        volunteer's `recognition_points` as the exact sum of the per-entry
        `points` over all `VERIFIED` entries, and re-evaluates the
        `recognition_tier`."
        PRD: "Whenever a recompute raises the tier, the system automatically
        creates a RecognitionAward with `source` `AUTO` for the new tier,
        unless one already exists for that volunteer and tier; tier decreases
        create nothing."

        Design: Difficulty/transitive_cascade/hour_verify_tier_award_cascade
        """
        scenario = _week_scenario("Cascade Carl", "carl@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]

        log_and_verify_hours(placement["id"], vid, worked_date="2026-08-03",
                             hours=10.0)
        log_and_verify_hours(placement["id"], vid, worked_date="2026-08-04",
                             hours=8.0)
        pending = log_hours(placement["id"], vid, worked_date="2026-08-05",
                            hours=2.0)
        assert get_volunteer(vid)["recognition_tier"] == "NONE"

        verify_entry(pending["id"])

        after = get_volunteer(vid)
        assert after["total_verified_hours"] == pytest.approx(20.0)
        assert after["recognition_tier"] == "BRONZE"

        awards, meta = list_awards_for(vid)
        assert meta["total_count"] == 1
        assert awards[0]["tier"] == "BRONZE"
        assert awards[0]["source"] == "AUTO"

    def test_verify_recomputes_totals_points_tier(self, api):
        """PRD: "Verification recomputes both hour totals, recomputes the
        volunteer's `recognition_points` as the exact sum of the per-entry
        `points` over all `VERIFIED` entries, and re-evaluates the
        `recognition_tier`."
        PRD: "The recognition ladder has three rungs above `NONE`: `BRONZE` at
        twenty verified hours, `SILVER` at fifty, and `GOLD` at one hundred."

        Design: Difficulty/transitive_cascade/hour_verify_tier_award_cascade
        """
        scenario = _week_scenario("Stepwise Sue", "step.sue@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]

        e1 = log_hours(placement["id"], vid, worked_date="2026-08-03",
                       hours=10.0, activity_category="STANDARD")
        verify_entry(e1["id"])
        step1 = get_volunteer(vid)
        assert step1["total_verified_hours"] == pytest.approx(10.0)
        assert step1["recognition_points"] == pytest.approx(10.0)
        assert step1["recognition_tier"] == "NONE"

        e2 = log_hours(placement["id"], vid, worked_date="2026-08-04",
                       hours=8.0, activity_category="TUTORING")
        verify_entry(e2["id"])
        step2 = get_volunteer(vid)
        assert step2["total_verified_hours"] == pytest.approx(18.0)
        assert step2["recognition_points"] == pytest.approx(22.0)
        assert step2["recognition_tier"] == "NONE"

        e3 = log_hours(placement["id"], vid, worked_date="2026-08-05",
                       hours=2.0, activity_category="MENTORING")
        verify_entry(e3["id"])
        step3 = get_volunteer(vid)
        assert step3["total_verified_hours"] == pytest.approx(20.0)
        assert step3["recognition_points"] == pytest.approx(26.0)
        assert step3["recognition_tier"] == "BRONZE"


class TestRevocationCompensation:
    def test_verify_then_revoke_nets_totals_to_zero_drift(self, api):
        """PRD: "Revocation is a district-office exclusive: a
        `DistrictCoordinator` moves a `VERIFIED` entry to the terminal
        `REVOKED` status, recomputing both totals and the recognition points in
        compensation, and the tier may downgrade as a result."
        PRD: "Entries in `REJECTED` or `REVOKED` count toward neither."

        Design: Difficulty/compensating_invariant/hours_points_conservation_verify_then_revoke
        """
        scenario = _week_scenario("Revoke Rena", "rena@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]

        e1 = log_and_verify_hours(placement["id"], vid,
                                  worked_date="2026-08-03", hours=4.0,
                                  activity_category="TUTORING")
        log_and_verify_hours(placement["id"], vid, worked_date="2026-08-04",
                             hours=3.0, activity_category="STANDARD")
        peak = get_volunteer(vid)
        assert peak["total_verified_hours"] == pytest.approx(7.0)
        assert peak["recognition_points"] == pytest.approx(9.0)

        revoked = validate_success(api.revoke_hour_entry(e1["id"], DC), 200)
        assert revoked["status"] == "REVOKED"

        after = get_volunteer(vid)
        # Verifying 4.0 then revoking 4.0 nets back to the remaining 3.0.
        assert after["total_verified_hours"] == pytest.approx(3.0)
        assert after["total_provisional_hours"] == pytest.approx(3.0)
        assert after["recognition_points"] == pytest.approx(3.0)
        assert after["recognition_tier"] == "NONE"

        # The revoked entry keeps its historical per-entry points but feeds
        # no aggregate.
        stale = get_success_data(api.get_hour_entry(e1["id"], DC))
        assert stale["status"] == "REVOKED"
        assert stale["points"] == pytest.approx(6.0, abs=1e-6)

    def test_revoked_entry_excluded_from_aggregates_but_keeps_points(self, api):
        """PRD: "Entries in `REJECTED` or `REVOKED` count toward neither."
        PRD: "Revocation is a district-office exclusive: a
        `DistrictCoordinator` moves a `VERIFIED` entry to the terminal
        `REVOKED` status, recomputing both totals and the recognition points in
        compensation, and the tier may downgrade as a result. Awards already
        granted are never retracted, whatever happens to the tier afterwards."

        Design: Difficulty/compensating_invariant/hours_points_conservation_verify_then_revoke
        """
        scenario = _week_scenario("Single Sol", "sol@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]

        entry = log_and_verify_hours(placement["id"], vid,
                                     worked_date="2026-08-03", hours=4.0,
                                     activity_category="TUTORING")
        peak = get_volunteer(vid)
        assert peak["total_verified_hours"] == pytest.approx(4.0)
        assert peak["recognition_points"] == pytest.approx(6.0)

        validate_success(api.revoke_hour_entry(entry["id"], DC), 200)

        after = get_volunteer(vid)
        assert after["total_verified_hours"] == pytest.approx(0.0)
        assert after["total_provisional_hours"] == pytest.approx(0.0)
        assert after["recognition_points"] == pytest.approx(0.0)

        stale = get_success_data(api.get_hour_entry(entry["id"], DC))
        assert stale["status"] == "REVOKED"
        assert stale["points"] == pytest.approx(6.0, abs=1e-6)


class TestManualAwards:
    def test_duplicate_award_tier_rejected(self, api):
        """PRD: "Manual grants are refused for volunteers in the terminal
        `DENIED` or `REMOVED` statuses (`ERR_VOLUNTEER_INVALID_STATE`), and at
        most one award per tier may ever exist for a volunteer, automatic or
        manual; a second grant of the same tier is rejected with
        `ERR_DUPLICATE_AWARD`."
        PRD: "A manually created award records `source` `MANUAL`, and because
        the award attaches to the volunteer aggregate, its creation increments
        the volunteer's `version` by one."

        Design: Corner/endpoints/duplicate_award_tier_rejected
        """
        volunteer = create_volunteer_applied("Award Amy", "amy@x.com",
                                             "SUPERVISED")

        first = validate_success(api.create_recognition_award(
            create_recognition_award_payload(volunteer["id"], "BRONZE",
                                             volunteer["version"],
                                             note="First"), DC), 201)
        assert first["source"] == "MANUAL"
        assert first["tier"] == "BRONZE"

        current = get_volunteer(volunteer["id"])

        duplicate = api.create_recognition_award(
            create_recognition_award_payload(volunteer["id"], "BRONZE",
                                             current["version"],
                                             note="Again"), DC)
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_AWARD)

        # A different tier succeeds; the failed duplicate consumed nothing.
        second = validate_success(api.create_recognition_award(
            create_recognition_award_payload(volunteer["id"], "SILVER",
                                             current["version"],
                                             note="Different tier"), DC), 201)
        assert second["tier"] == "SILVER"

        _, meta = validate_paginated(api.list_recognition_awards(
            DC, params={"volunteer_id": volunteer["id"]}))
        assert meta["total_count"] == 2

    def test_occ_manual_award_success_and_stale_rejected(self, api):
        """PRD: "The request must carry `expected_volunteer_version` matching
        the volunteer's current `version`. If the volunteer's version has
        advanced since the client last read it — for example, an automated tier
        award or an hour verification has just changed the volunteer's
        recognition posture — the grant is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD: "A manually created award records `source` `MANUAL`, and because
        the award attaches to the volunteer aggregate, its creation increments
        the volunteer's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_manual_award_success_and_stale_rejected
        """
        volunteer = create_volunteer_applied("Award Ollie", "ao@x.com",
                                             "SUPERVISED")
        observed_version = volunteer["version"]

        first = validate_success(api.create_recognition_award(
            create_recognition_award_payload(volunteer["id"], "BRONZE",
                                             observed_version,
                                             note="Manual kudos"), DC), 201)
        assert first["source"] == "MANUAL"
        assert first["tier"] == "BRONZE"

        # The first grant advanced the volunteer's version: replaying the
        # observed version is stale.
        replay = api.create_recognition_award(
            create_recognition_award_payload(volunteer["id"], "SILVER",
                                             observed_version,
                                             note="Stale replay"), DC)
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

        _, meta = validate_paginated(api.list_recognition_awards(
            DC, params={"volunteer_id": volunteer["id"]}))
        assert meta["total_count"] == 1
