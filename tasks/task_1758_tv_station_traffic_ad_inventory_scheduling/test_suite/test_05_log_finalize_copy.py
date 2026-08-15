"""Log finalization and copy rotation: the finalize cascade, copy clearance
preconditions, rotation scoring, and withdrawal locks."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_order_line,
    approve_order,
    create_advertiser,
    create_avail_unit,
    create_avail_week,
    create_copy,
    create_log_day,
    create_order,
    create_program,
    create_received_copy,
    finalize_log_day,
    get_avail_unit,
    get_avail_week,
    get_log_day,
    get_spot,
    get_success_data,
    list_line_spots,
    place_spot_fresh,
    place_spot_payload,
    setup_scheduled_scenario,
    submit_order,
    validate_error,
    validate_success,
)

SALESREP = TEST_USERS["salesrep_headers"]
TRAFFIC = TEST_USERS["trafficmanager_headers"]
COPYDESK = TEST_USERS["copycoordinator_headers"]


class TestFinalizeCascade:
    def test_finalize_assigns_copy_locks_week_gates_placement(self, api):
        """PRD §3.7: "The lowest score wins, ties break toward the candidate with the earliest `created_at`, and scores are compared exactly as rational numbers by cross-multiplication, never as rounded floats."
        PRD §3.7: "Finalizing a log day also locks its owning week: the week's status moves from `OPEN` to `LOCKED`, freezing new placements into the week per §3.5"

        Design: Difficulty/transitive_cascade/finalize_cascade_spot_copy_week_lock
        """
        ctx = setup_scheduled_scenario(
            spots_per_week=2, place_count=1, num_copies=2,
            gross_rate_cents=8000, log_date="2026-08-03",
        )
        log = ctx["log"]
        placed_spot = ctx["placed"][0]
        copy_a, copy_b = ctx["copies"]  # copy_a created first

        finalized = validate_success(api.finalize_log_day(log["id"], TRAFFIC))
        assert finalized["status"] == "FINALIZED"  # hop 1

        spot_after = get_spot(placed_spot["id"])
        assert spot_after["copy_instruction_id"] == copy_a["id"], (
            "both copies score 0; the tie breaks to the earliest created_at"
        )  # hop 2

        assert get_avail_week(ctx["week"]["id"])["status"] == "LOCKED"  # hop 3

        # The locked week now gates the sibling spot's placement.
        pending_spot = ctx["spots"][1]
        unit = ctx["units"][0]
        resp = api.place_spot(
            pending_spot["id"],
            place_spot_payload(unit["id"], get_avail_unit(unit["id"])["version"]),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_finalize_run_assigns_same_winner_to_all_spots(self, api):
        """PRD §3.7: "Each candidate's score is its times-used count divided by its `rotation_weight`, where times-used counts every spot — of any status — whose `copy_instruction_id` references that copy and that was created before the current finalize run began."

        Design: Difficulty/transitive_cascade/finalize_cascade_spot_copy_week_lock
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=1, air_date="2026-08-03", num_units=2,
            spots_per_week=2, place_count=2, num_copies=2, log_date="2026-08-03",
        )
        copy_a, _ = ctx["copies"]
        finalize_log_day(ctx["log"]["id"])
        first = get_spot(ctx["placed"][0]["id"])
        second = get_spot(ctx["placed"][1]["id"])
        assert first["copy_instruction_id"] == copy_a["id"]
        assert second["copy_instruction_id"] == copy_a["id"], (
            "both spots finalize in the same run; times-used counts only "
            "assignments made before the run began, so both see score 0 for "
            "every copy and the earliest-created copy wins both"
        )


class TestCopyRotation:
    def test_least_used_copy_wins_next_finalize_run(self, api):
        """PRD §3.7: "Each candidate's score is its times-used count divided by its `rotation_weight`, where times-used counts every spot — of any status — whose `copy_instruction_id` references that copy and that was created before the current finalize run began. The lowest score wins, ties break toward the candidate with the earliest `created_at`, and scores are compared exactly as rational numbers by cross-multiplication, never as rounded floats."

        Design: Corner/calculations/copy_rotation_weighted_least_used_wins
        """
        advertiser = create_advertiser(name="Rot")
        program = create_program(
            title="Mon Rot", daypart_code="DAYTIME", airs_weekday=1, rating_estimate=2.0
        )
        week1 = create_avail_week("2026-08-03")
        unit1 = create_avail_unit(week1["id"], program["id"], "2026-08-03", total_seconds=120)
        week2 = create_avail_week("2026-08-10")
        unit2 = create_avail_unit(week2["id"], program["id"], "2026-08-10", total_seconds=120)
        copy_a = create_received_copy(advertiser["id"], 30)
        copy_b = create_received_copy(advertiser["id"], 30)
        order = create_order(advertiser["id"], "2026-08-03", "2026-08-16")
        line = add_order_line(
            order["id"], program["id"], weeks_requested=2, spots_per_week=1,
            gross_rate_cents=5000,
        )
        submit_order(order["id"])
        approve_order(order["id"])
        spots = list_line_spots(line["id"])
        spot_w1 = place_spot_fresh(spots[0]["id"], unit1["id"])
        spot_w2 = place_spot_fresh(spots[1]["id"], unit2["id"])

        log1 = create_log_day(week1["id"], "2026-08-03")
        finalize_log_day(log1["id"])
        assert get_spot(spot_w1["id"])["copy_instruction_id"] == copy_a["id"], (
            "week1: both copies at score 0, tie broken to earliest created_at"
        )

        log2 = create_log_day(week2["id"], "2026-08-10")
        finalize_log_day(log2["id"])
        assert get_spot(spot_w2["id"])["copy_instruction_id"] == copy_b["id"], (
            "week2: score(copy_a) = 1/1 > score(copy_b) = 0/1 — least-used wins"
        )


class TestFinalizePreconditions:
    def test_finalize_blocked_without_received_copy(self, api):
        """PRD §3.7: "Every spot scheduled on that date must also have resolvable copy: for each such spot, at least one of its advertiser's copy instructions must be in `RECEIVED` status with a `length_seconds` equal to the spot's line length. When no eligible copy exists for a scheduled spot, finalization fails with `ERR_COPY_NOT_RECEIVED`"

        Design: Corner/validations/finalize_without_received_copy_rejected
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=3, air_date="2026-08-05", copy_received=False,
            log_date="2026-08-05",
        )
        # Copy exists but stays PENDING — never cleared for air.
        create_copy(ctx["advertiser"]["id"], 30)
        resp = api.finalize_log_day(ctx["log"]["id"], TRAFFIC)
        validate_error(resp, ApiErrorId.ERR_COPY_NOT_RECEIVED)
        assert get_log_day(ctx["log"]["id"])["status"] == "DRAFT"

    def test_finalize_past_log_rejected_by_clock(self, api):
        """PRD §3.7: "A `TrafficManager` finalizes a `DRAFT` log day only while its `log_date` is today or in the future relative to the logical clock — finalizing a past log is rejected with `ERR_DATE_WINDOW`."
        PRD §2.5: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and before any clock-setting call it continues to read exactly that instant."

        Design: Corner/state_machines/logday_finalize_past_date_rejected
        """
        week = create_avail_week("2026-07-27")
        log = create_log_day(week["id"], "2026-07-30")
        resp = api.finalize_log_day(log["id"], TRAFFIC)
        validate_error(resp, ApiErrorId.ERR_DATE_WINDOW)
        assert get_log_day(log["id"])["status"] == "DRAFT"


class TestCopyWithdrawalLock:
    def test_expire_blocked_while_finalized_log_depends_on_copy(self, api):
        """PRD §3.3: "Specifically, expiring `RECEIVED` copy is rejected with `ERR_INVALID_STATE` while any `FINALIZED` log day references that copy through a spot still in `SCHEDULED` status."

        Design: Corner/state_machines/copy_expire_from_received_blocked_when_referenced_by_finalized_log
        """
        ctx = setup_scheduled_scenario(log_date="2026-08-03", finalize=True)
        copy = ctx["copies"][0]
        assert get_spot(ctx["placed"][0]["id"])["copy_instruction_id"] == copy["id"]
        resp = api.expire_copy(copy["id"], COPYDESK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        kept = get_success_data(api.get_copy_instruction(copy["id"], COPYDESK))
        assert kept["status"] == "RECEIVED"
