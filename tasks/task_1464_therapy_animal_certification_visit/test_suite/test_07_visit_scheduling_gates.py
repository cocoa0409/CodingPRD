"""Visit scheduling gate chain: duration caps, workload ceiling, overlap
semantics (team vs facility), daily/weekly caps, species, past-dated, OCC."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_visit_payload,
    get_animal,
    get_team_version,
    schedule_visit_ok,
    set_clock,
    setup_active_facility,
    setup_certified_team,
    setup_certified_team_at_facility,
    setup_visit_ready_team,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]


def _attempt_visit(ctx, start, end):
    """POST /v1/visits with the team's current version; returns raw response."""
    return api_client.create_visit(
        create_visit_payload(
            ctx["team"]["id"], ctx["facility"]["id"], start, end,
            get_team_version(ctx["team"]["id"]),
        ),
        ADMIN,
    )


class TestDurationCapBoundary:
    def test_duration_equal_to_effective_cap_passes_and_over_fails(self):
        """PRD §3.7: "Constraints: the scheduled duration must run at least thirty minutes (`ERR_VISIT_DURATION_INVALID`) and at most the effective cap — the smallest of the facility's `max_visit_minutes`, the covering agreement's `agreed_max_visit_minutes`, and the program ceiling of one hundred twenty minutes, with a duration exactly equal to the cap allowed and anything longer failing `ERR_VISIT_DURATION_EXCEEDS_CAP`; the resulting count of visits at the facility whose scheduled intervals overlap at any instant must not exceed `max_overlapping_teams` (`ERR_FACILITY_CAPACITY_EXCEEDED`); and the facility's count of visits in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` within the ISO week — Monday through Sunday — must stand below `visits_per_week_cap`, a booking made while the count already equals the cap failing `ERR_FACILITY_WEEKLY_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/duration_cap_equality_boundary
        """
        # Effective cap = min(facility 60, agreement 90, program 120) = 60.
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H B1", "team_name": "TB1"},
            facility_kwargs={"name": "School M", "max_visit_minutes": 60,
                             "agreed_max_visit_minutes": 90},
        )
        ok = _attempt_visit(ctx, "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        assert validate_success(ok, 201)["lifecycle_status"] == "SCHEDULED", (
            "duration 60 == cap 60 must pass (<= semantics)"
        )
        over = _attempt_visit(ctx, "2026-08-04T10:00:00Z", "2026-08-04T11:01:00Z")
        validate_error(over, ApiErrorId.ERR_VISIT_DURATION_EXCEEDS_CAP)

    def test_program_ceiling_binds_when_facility_and_agreement_are_higher(self):
        """PRD §3.7: "Constraints: the scheduled duration must run at least thirty minutes (`ERR_VISIT_DURATION_INVALID`) and at most the effective cap — the smallest of the facility's `max_visit_minutes`, the covering agreement's `agreed_max_visit_minutes`, and the program ceiling of one hundred twenty minutes, with a duration exactly equal to the cap allowed and anything longer failing `ERR_VISIT_DURATION_EXCEEDS_CAP`; the resulting count of visits at the facility whose scheduled intervals overlap at any instant must not exceed `max_overlapping_teams` (`ERR_FACILITY_CAPACITY_EXCEEDED`); and the facility's count of visits in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` within the ISO week — Monday through Sunday — must stand below `visits_per_week_cap`, a booking made while the count already equals the cap failing `ERR_FACILITY_WEEKLY_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/duration_cap_equality_boundary
        """
        # Effective cap = min(facility 150, agreement 150, program 120) = 120.
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H B1p", "team_name": "TB1p"},
            facility_kwargs={"name": "School Mp", "max_visit_minutes": 150,
                             "agreed_max_visit_minutes": 150},
        )
        # The over-cap attempt goes first so it cannot contaminate later gates.
        over = _attempt_visit(ctx, "2026-08-03T10:00:00Z", "2026-08-03T12:01:00Z")
        validate_error(over, ApiErrorId.ERR_VISIT_DURATION_EXCEEDS_CAP)
        ok = _attempt_visit(ctx, "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z")
        assert validate_success(ok, 201)["lifecycle_status"] == "SCHEDULED", (
            "duration 120 == program ceiling 120 must pass (<= semantics)"
        )


class TestTeamOverlapSemantics:
    def test_bare_adjacency_allowed_for_team(self):
        """PRD §3.7: "Temporal: `scheduled_start` must lie in the future (`ERR_VISIT_IN_PAST`), and the new interval — start inclusive, end exclusive — must not overlap any other `SCHEDULED` or `IN_PROGRESS` visit of the same team, with bare adjacency allowed (`ERR_TEAM_SCHEDULING_CONFLICT`)."

        Design: Difficulty/resource_temporal_overlap/team_half_open_adjacency
        """
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H O1", "team_name": "TO1"},
            facility_kwargs={"name": "School P"},
        )
        first = _attempt_visit(ctx, "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        assert validate_success(first, 201)["lifecycle_status"] == "SCHEDULED"
        # Half-open [start, end): prior end 11:00 == new start 11:00 is allowed.
        adjacent = _attempt_visit(ctx, "2026-08-03T11:00:00Z", "2026-08-03T12:00:00Z")
        assert validate_success(adjacent, 201)["lifecycle_status"] == "SCHEDULED"

    def test_interior_overlap_rejected_for_team(self):
        """PRD §3.7: "Temporal: `scheduled_start` must lie in the future (`ERR_VISIT_IN_PAST`), and the new interval — start inclusive, end exclusive — must not overlap any other `SCHEDULED` or `IN_PROGRESS` visit of the same team, with bare adjacency allowed (`ERR_TEAM_SCHEDULING_CONFLICT`)."

        Design: Difficulty/resource_temporal_overlap/team_half_open_adjacency
        """
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H O1b", "team_name": "TO1b"},
            facility_kwargs={"name": "School Pb"},
        )
        first = _attempt_visit(ctx, "2026-08-04T10:00:00Z", "2026-08-04T11:00:00Z")
        assert validate_success(first, 201)["lifecycle_status"] == "SCHEDULED"
        # [10:30, 11:30) strictly overlaps the existing [10:00, 11:00).
        overlap = _attempt_visit(ctx, "2026-08-04T10:30:00Z", "2026-08-04T11:30:00Z")
        validate_error(overlap, ApiErrorId.ERR_TEAM_SCHEDULING_CONFLICT)


class TestFacilityAggregateCapacity:
    def _setup_three_teams(self):
        fac_ctx = setup_active_facility(
            name="School Q", max_overlapping_teams=2, visits_per_week_cap=10,
        )
        teams = [
            setup_visit_ready_team(
                setup_certified_team(handler_name=f"H F{i}", team_name=f"TF{i}",
                                     animal_name=f"D{i}",
                                     # Each team's chain advances the clock to the
                                     # end of its evaluation slot; stagger slots so
                                     # later evaluations are never in the past.
                                     eval_start=f"2026-08-02T{7 + 2 * i:02d}:00:00Z",
                                     eval_end=f"2026-08-02T{8 + 2 * i:02d}:00:00Z"),
                fac_ctx,
            )
            for i in (1, 2, 3)
        ]
        return fac_ctx, teams

    def test_overlapping_visits_up_to_capacity_pass(self):
        """PRD §3.7: "Constraints: the scheduled duration must run at least thirty minutes (`ERR_VISIT_DURATION_INVALID`) and at most the effective cap — the smallest of the facility's `max_visit_minutes`, the covering agreement's `agreed_max_visit_minutes`, and the program ceiling of one hundred twenty minutes, with a duration exactly equal to the cap allowed and anything longer failing `ERR_VISIT_DURATION_EXCEEDS_CAP`; the resulting count of visits at the facility whose scheduled intervals overlap at any instant must not exceed `max_overlapping_teams` (`ERR_FACILITY_CAPACITY_EXCEEDED`); and the facility's count of visits in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` within the ISO week — Monday through Sunday — must stand below `visits_per_week_cap`, a booking made while the count already equals the cap failing `ERR_FACILITY_WEEKLY_CAP_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/facility_aggregate_capacity_overlap
        """
        fac_ctx, (t1, t2, _t3) = self._setup_three_teams()
        v1 = schedule_visit_ok(t1["team"]["id"], fac_ctx["facility"]["id"],
                               "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        assert v1["lifecycle_status"] == "SCHEDULED"
        # Fully overlapping second visit: instantaneous count 2 == cap 2 (allowed).
        v2 = schedule_visit_ok(t2["team"]["id"], fac_ctx["facility"]["id"],
                               "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        assert v2["lifecycle_status"] == "SCHEDULED"

    def test_overlap_beyond_capacity_rejected(self):
        """PRD §3.7: "Constraints: the scheduled duration must run at least thirty minutes (`ERR_VISIT_DURATION_INVALID`) and at most the effective cap — the smallest of the facility's `max_visit_minutes`, the covering agreement's `agreed_max_visit_minutes`, and the program ceiling of one hundred twenty minutes, with a duration exactly equal to the cap allowed and anything longer failing `ERR_VISIT_DURATION_EXCEEDS_CAP`; the resulting count of visits at the facility whose scheduled intervals overlap at any instant must not exceed `max_overlapping_teams` (`ERR_FACILITY_CAPACITY_EXCEEDED`); and the facility's count of visits in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` within the ISO week — Monday through Sunday — must stand below `visits_per_week_cap`, a booking made while the count already equals the cap failing `ERR_FACILITY_WEEKLY_CAP_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/facility_aggregate_capacity_overlap
        """
        fac_ctx, (t1, t2, t3) = self._setup_three_teams()
        schedule_visit_ok(t1["team"]["id"], fac_ctx["facility"]["id"],
                          "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        schedule_visit_ok(t2["team"]["id"], fac_ctx["facility"]["id"],
                          "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        # Partially overlapping third visit: instantaneous count would reach 3 > 2.
        third = api_client.create_visit(
            create_visit_payload(
                t3["team"]["id"], fac_ctx["facility"]["id"],
                "2026-08-03T10:30:00Z", "2026-08-03T11:00:00Z",
                get_team_version(t3["team"]["id"]),
            ),
            ADMIN,
        )
        validate_error(third, ApiErrorId.ERR_FACILITY_CAPACITY_EXCEEDED)


class TestWorkloadCapBoundary:
    def test_workload_cap_equality_boundary(self):
        """PRD §3.7: "Safety: the animal must not stand in `WELFARE_HOLD` (`ERR_ANIMAL_WELFARE_HOLD`); the animal's rest block must be satisfied — `scheduled_start` at or after `welfare_blocked_until`, with an earlier start failing `ERR_ANIMAL_REST_PERIOD`; the forward workload gate must hold — the animal's existing forward-looking workload plus the new visit's scheduled minutes may not exceed two hundred forty minutes, with a total of exactly two hundred forty allowed and anything beyond rejected `ERR_WORKLOAD_LIMIT_EXCEEDED`; the daily limit must hold — an animal already standing on two visits in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` on that UTC calendar day rejects a third with `ERR_DAILY_VISIT_LIMIT_EXCEEDED`; the animal's `species` must appear in the facility's `allowed_species` (`ERR_SPECIES_NOT_PERMITTED`); and a valid rabies vaccination must cover the scheduled date (`ERR_VACCINATION_MISSING` / `ERR_VACCINATION_EXPIRED`)."

        Design: Corner/calculations/workload_cap_equality_boundary
        """
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H WL", "team_name": "TWL"},
            facility_kwargs={"name": "School Y", "visits_per_week_cap": 6},
        )
        for start, end in (
            ("2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z"),
            ("2026-08-03T12:00:00Z", "2026-08-03T13:00:00Z"),
            ("2026-08-04T10:00:00Z", "2026-08-04T11:00:00Z"),
            ("2026-08-04T12:00:00Z", "2026-08-04T13:00:00Z"),
        ):
            visit = _attempt_visit(ctx, start, end)
            assert validate_success(visit, 201)["lifecycle_status"] == "SCHEDULED"
        animal = get_animal(ctx["animal"]["id"])
        assert animal["forward_workload_minutes"] == 240, (
            f"Four 60-minute visits must land exactly on the 240 cap, got {animal['forward_workload_minutes']}"
        )
        # 240 + 30 = 270 > 240 -> rejected.
        over = _attempt_visit(ctx, "2026-08-05T10:00:00Z", "2026-08-05T10:30:00Z")
        validate_error(over, ApiErrorId.ERR_WORKLOAD_LIMIT_EXCEEDED)


class TestVisitGateViolations:
    def test_visit_scheduled_in_past_rejected(self):
        """PRD §3.7: "Temporal: `scheduled_start` must lie in the future (`ERR_VISIT_IN_PAST`), and the new interval — start inclusive, end exclusive — must not overlap any other `SCHEDULED` or `IN_PROGRESS` visit of the same team, with bare adjacency allowed (`ERR_TEAM_SCHEDULING_CONFLICT`)."

        Design: Corner/errors/visit_scheduled_in_past_rejected
        """
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H VP", "team_name": "TVP"},
            facility_kwargs={"name": "Fac VP"},
        )
        set_clock("2026-08-02T12:00:00Z")
        resp = _attempt_visit(ctx, "2026-08-02T11:00:00Z", "2026-08-02T11:30:00Z")
        validate_error(resp, ApiErrorId.ERR_VISIT_IN_PAST)

    def test_species_not_permitted_at_facility(self):
        """PRD §3.7: "Safety: the animal must not stand in `WELFARE_HOLD` (`ERR_ANIMAL_WELFARE_HOLD`); the animal's rest block must be satisfied — `scheduled_start` at or after `welfare_blocked_until`, with an earlier start failing `ERR_ANIMAL_REST_PERIOD`; the forward workload gate must hold — the animal's existing forward-looking workload plus the new visit's scheduled minutes may not exceed two hundred forty minutes, with a total of exactly two hundred forty allowed and anything beyond rejected `ERR_WORKLOAD_LIMIT_EXCEEDED`; the daily limit must hold — an animal already standing on two visits in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` on that UTC calendar day rejects a third with `ERR_DAILY_VISIT_LIMIT_EXCEEDED`; the animal's `species` must appear in the facility's `allowed_species` (`ERR_SPECIES_NOT_PERMITTED`); and a valid rabies vaccination must cover the scheduled date (`ERR_VACCINATION_MISSING` / `ERR_VACCINATION_EXPIRED`)."

        Design: Corner/errors/species_not_permitted_at_facility
        """
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H SP", "team_name": "TSP", "species": "CAT",
                         "animal_name": "C", "breed": "Ragdoll"},
            facility_kwargs={"name": "Fac SP", "allowed_species": ["DOG"]},
        )
        resp = _attempt_visit(ctx, "2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z")
        validate_error(resp, ApiErrorId.ERR_SPECIES_NOT_PERMITTED)

    def test_daily_visit_limit_third_visit_rejected(self):
        """PRD §3.7: "Safety: the animal must not stand in `WELFARE_HOLD` (`ERR_ANIMAL_WELFARE_HOLD`); the animal's rest block must be satisfied — `scheduled_start` at or after `welfare_blocked_until`, with an earlier start failing `ERR_ANIMAL_REST_PERIOD`; the forward workload gate must hold — the animal's existing forward-looking workload plus the new visit's scheduled minutes may not exceed two hundred forty minutes, with a total of exactly two hundred forty allowed and anything beyond rejected `ERR_WORKLOAD_LIMIT_EXCEEDED`; the daily limit must hold — an animal already standing on two visits in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` on that UTC calendar day rejects a third with `ERR_DAILY_VISIT_LIMIT_EXCEEDED`; the animal's `species` must appear in the facility's `allowed_species` (`ERR_SPECIES_NOT_PERMITTED`); and a valid rabies vaccination must cover the scheduled date (`ERR_VACCINATION_MISSING` / `ERR_VACCINATION_EXPIRED`)."

        Design: Corner/errors/daily_visit_limit_third_visit_rejected
        """
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H DL", "team_name": "TDL"},
            facility_kwargs={"name": "Fac DL"},
        )
        schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                          "2026-08-03T09:00:00Z", "2026-08-03T09:30:00Z")
        schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                          "2026-08-03T11:00:00Z", "2026-08-03T11:30:00Z")
        # The animal already holds two visits on 2026-08-03 (UTC).
        resp = _attempt_visit(ctx, "2026-08-03T14:00:00Z", "2026-08-03T14:30:00Z")
        validate_error(resp, ApiErrorId.ERR_DAILY_VISIT_LIMIT_EXCEEDED)

    def test_weekly_cap_third_week_visit_rejected(self):
        """PRD §3.7: "Constraints: the scheduled duration must run at least thirty minutes (`ERR_VISIT_DURATION_INVALID`) and at most the effective cap — the smallest of the facility's `max_visit_minutes`, the covering agreement's `agreed_max_visit_minutes`, and the program ceiling of one hundred twenty minutes, with a duration exactly equal to the cap allowed and anything longer failing `ERR_VISIT_DURATION_EXCEEDS_CAP`; the resulting count of visits at the facility whose scheduled intervals overlap at any instant must not exceed `max_overlapping_teams` (`ERR_FACILITY_CAPACITY_EXCEEDED`); and the facility's count of visits in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` within the ISO week — Monday through Sunday — must stand below `visits_per_week_cap`, a booking made while the count already equals the cap failing `ERR_FACILITY_WEEKLY_CAP_EXCEEDED`."

        Design: Corner/errors/weekly_cap_third_week_visit_rejected
        """
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H WC", "team_name": "TWC"},
            facility_kwargs={"name": "Fac WC", "visits_per_week_cap": 2},
        )
        # 2026-08-03 (Mon) and 2026-08-04 (Tue) are both in ISO week 2026-W32.
        schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                          "2026-08-03T09:00:00Z", "2026-08-03T09:30:00Z")
        schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                          "2026-08-04T09:00:00Z", "2026-08-04T09:30:00Z")
        # The weekly count already equals the cap of 2; a third booking in the
        # same ISO week fails even though it lands on a different day.
        resp = _attempt_visit(ctx, "2026-08-05T09:00:00Z", "2026-08-05T09:30:00Z")
        validate_error(resp, ApiErrorId.ERR_FACILITY_WEEKLY_CAP_EXCEEDED)


class TestVisitCreateOcc:
    def test_occ_stale_version_on_visit_create(self):
        """PRD §2.6: "Directly scheduling a visit requires `expected_team_version` carrying the client's last observed `version` of the team. If the team's current `version` does not match — because another booking has legitimately mutated the team's workload bookkeeping since the client last read it — the scheduling call is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.7: "A visit that clears the chain starts `SCHEDULED` and `UNVERIFIED`, increments the team's `version` by one, and raises the animal's `forward_workload_minutes` by the scheduled minutes."

        Design: Corner/cross_cutting/occ_stale_version_on_visit_create
        """
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H OC2", "team_name": "TOC2"},
            facility_kwargs={"name": "Fac OC2"},
        )
        observed = get_team_version(ctx["team"]["id"])
        first = api_client.create_visit(
            create_visit_payload(ctx["team"]["id"], ctx["facility"]["id"],
                                 "2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z",
                                 observed),
            ADMIN,
        )
        assert validate_success(first, 201)["lifecycle_status"] == "SCHEDULED"
        # The first create advanced Team.version; replaying the stale value fails.
        stale = api_client.create_visit(
            create_visit_payload(ctx["team"]["id"], ctx["facility"]["id"],
                                 "2026-08-04T10:00:00Z", "2026-08-04T10:30:00Z",
                                 observed),
            ADMIN,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
