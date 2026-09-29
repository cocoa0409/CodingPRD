"""Two shared resources with deliberately opposite interval semantics."""

from test_helpers import (
    ERR_ASSET_CAPACITY_EXCEEDED,
    ERR_TEAM_WINDOW_CONFLICT,
    accepted_organ,
    assert_team_ledger,
    book_operation,
    create_asset,
    create_team,
    cross_clamp,
    dispatch_transport,
    read_organ,
    read_team,
    recovery_operation_payload,
    transport_payload,
    validate_error,
    validate_success,
)

TEAM_CLOCK = "2026-08-25T07:00:00Z"
ASSET_CLOCK = "2026-08-26T05:00:00Z"


# ---------------------------------------------------------------------------
# RecoveryTeam: strict comparisons on a symmetric turnaround buffer
# ---------------------------------------------------------------------------
def _team_holding_one_booked_window(env):
    """One abdominal team booked 08:00-12:00 for case one, with case two waiting."""
    team = create_team(
        env, specialty="ABDOMINAL", turnaround_buffer_minutes=90
    )
    first = accepted_organ(
        env, "LIVER", TEAM_CLOCK, candidate_count=1, primary_offer_slots=1
    )
    first.team = team
    first.operation = book_operation(
        env,
        first.case_id,
        team["id"],
        "2026-08-25T08:00:00Z",
        "2026-08-25T12:00:00Z",
    )
    second = accepted_organ(
        env, "KIDNEY_RIGHT", TEAM_CLOCK, candidate_count=1, primary_offer_slots=1
    )
    second.team = team
    return first, second


def test_the_first_booking_writes_its_minutes_onto_the_team_ledger(env):
    """A four-hour window books 240 minutes against the team.

    PRD 3.7: "its `or_minutes` computed as the whole minutes from `or_start_at`
    to `or_end_at`, and its `organ_types_covered` pinned to the `organ_type`
    values of the case's accepted organs as they stand at scheduling time".
    PRD 3.7: "The team's `booked_or_minutes` increases by that `or_minutes` and
    its `scheduled_operation_count` by one."

    Design: Difficulty/resource_temporal_overlap/recovery_team_half_open_window_with_symmetric_turnaround_buffer
    """
    first, _second = _team_holding_one_booked_window(env)

    assert first.operation["or_minutes"] == 240
    assert first.operation["status"] == "SCHEDULED"
    assert first.operation["organ_types_covered"] == ["LIVER"]
    assert_team_ledger(read_team(env, first.team["id"]), 240, 1)


def test_a_window_one_minute_inside_the_buffer_is_refused(env):
    """13:29 falls strictly before 12:00 plus the ninety-minute buffer.

    PRD 3.7: "The requested window conflicts with an existing operation of the
    same team, whose status is `SCHEDULED` or `COMPLETED`, when the new start
    falls strictly before that operation's end plus the buffer **and** that
    operation's start falls strictly before the new end plus the buffer."
    PRD 3.7: "a `turnaround_buffer_minutes` from 0 through 480 that defaults to
    90 and is applied symmetrically around every booked window when availability
    is tested".

    Design: Difficulty/resource_temporal_overlap/recovery_team_half_open_window_with_symmetric_turnaround_buffer
    """
    _first, second = _team_holding_one_booked_window(env)

    refused = env.api.create_recovery_operation(
        second.case_id,
        recovery_operation_payload(
            second.team["id"], "2026-08-25T13:29:00Z", "2026-08-25T16:29:00Z"
        ),
        env.logistics,
    )
    validate_error(refused, ERR_TEAM_WINDOW_CONFLICT)

    assert_team_ledger(read_team(env, second.team["id"]), 240, 1)


def test_a_window_starting_exactly_at_the_buffer_boundary_is_accepted(env):
    """13:30 is exactly 12:00 plus the buffer, so the strict test lets it through.

    PRD 3.7: "Both comparisons are strict, so a window beginning exactly the
    buffer's worth of minutes after an existing window ends is accepted."
    PRD 2.11: "for each recovery team, `booked_or_minutes` is always exactly the
    sum of `or_minutes` over that team's operations whose status is `SCHEDULED`
    or `COMPLETED`".

    Design: Difficulty/resource_temporal_overlap/recovery_team_half_open_window_with_symmetric_turnaround_buffer
    """
    _first, second = _team_holding_one_booked_window(env)

    created = env.api.create_recovery_operation(
        second.case_id,
        recovery_operation_payload(
            second.team["id"], "2026-08-25T13:30:00Z", "2026-08-25T16:30:00Z"
        ),
        env.logistics,
    )
    operation = validate_success(created, 201)

    assert operation["or_minutes"] == 180
    assert operation["status"] == "SCHEDULED"
    assert operation["organ_types_covered"] == ["KIDNEY_RIGHT"]
    assert_team_ledger(read_team(env, second.team["id"]), 420, 2)


# ---------------------------------------------------------------------------
# TransportAsset: closed intervals, so touching endpoints collide
# ---------------------------------------------------------------------------
def _asset_carrying_one_leg_to_nine_o_clock(env):
    """One van at capacity one, already carrying a kidney leg from 08:00 to 09:00."""
    asset = create_asset(env, mode="GROUND", concurrent_leg_capacity=1)

    first = accepted_organ(
        env, "KIDNEY_LEFT", ASSET_CLOCK, candidate_count=1, primary_offer_slots=1
    )
    first.team = create_team(
        env, specialty="ABDOMINAL", turnaround_buffer_minutes=30
    )
    first.operation = book_operation(
        env,
        first.case_id,
        first.team["id"],
        "2026-08-26T05:30:00Z",
        "2026-08-26T07:00:00Z",
    )

    second = accepted_organ(
        env, "KIDNEY_RIGHT", ASSET_CLOCK, candidate_count=1, primary_offer_slots=1
    )
    second.team = create_team(
        env, specialty="ABDOMINAL", turnaround_buffer_minutes=30
    )
    second.operation = book_operation(
        env,
        second.case_id,
        second.team["id"],
        "2026-08-26T05:30:00Z",
        "2026-08-26T07:00:00Z",
    )

    env.set_clock("2026-08-26T06:00:00Z")
    cross_clamp(env, first.operation["id"])
    cross_clamp(env, second.operation["id"])

    first.asset = asset
    second.asset = asset
    first.organs["KIDNEY_LEFT"] = dispatch_transport(
        env,
        first.only_organ_id,
        asset["id"],
        "2026-08-26T08:00:00Z",
        "2026-08-26T09:00:00Z",
    )
    return first, second


def test_the_first_leg_projects_well_inside_the_kidney_ceiling(env):
    """Two hours of cold time plus an hour of transit still selects standard prep.

    PRD 3.7: "a margin of at least 120 minutes selects standard prep at 45
    minutes, otherwise a margin of at least 60 minutes selects expedited prep at
    30 minutes, otherwise crash prep at 20 minutes".
    PRD 3.5: "and eighteen hours each for `KIDNEY_LEFT` and `KIDNEY_RIGHT`, all
    expressed internally in whole minutes".

    Design: Difficulty/resource_temporal_overlap/transport_asset_closed_interval_legs_touch_at_endpoint
    """
    first, _second = _asset_carrying_one_leg_to_nine_o_clock(env)
    organ = first.organ("KIDNEY_LEFT")

    assert organ["cit_limit_minutes"] == 1080
    assert organ["transit_minutes"] == 60
    assert organ["implant_prep_minutes"] == 45
    assert organ["projected_cold_ischemic_minutes"] == 225
    assert organ["projected_cit_margin_minutes"] == 855
    assert organ["status"] == "RECOVERED"


def test_a_leg_departing_exactly_when_the_other_arrives_collides(env):
    """The closed-interval test makes a touching endpoint an overlap.

    PRD 3.7: "the system counts the organs already assigned to the named asset
    whose status is `RECOVERED` or `TRANSPLANTED` and whose leg overlaps the
    requested leg on **closed** intervals — that is, where the new departure is
    at or before the existing arrival and the existing departure is at or before
    the new arrival, so legs that merely touch at an endpoint do collide."
    PRD 3.7: "When that count has already reached the asset's
    `concurrent_leg_capacity`, the dispatch is rejected with
    `ERR_ASSET_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/transport_asset_closed_interval_legs_touch_at_endpoint
    """
    _first, second = _asset_carrying_one_leg_to_nine_o_clock(env)

    refused = env.api.dispatch_transport(
        second.only_organ_id,
        transport_payload(
            second.asset["id"], "2026-08-26T09:00:00Z", "2026-08-26T10:00:00Z"
        ),
        env.logistics,
    )
    validate_error(refused, ERR_ASSET_CAPACITY_EXCEEDED)

    organ = read_organ(env, second.only_organ_id)
    assert organ["transport_asset_id"] is None
    assert organ["projected_cold_ischemic_minutes"] is None
    assert organ["status"] == "RECOVERED"


def test_shifting_the_departure_by_one_minute_clears_the_conflict(env):
    """A 09:01 departure no longer touches the 09:00 arrival and is dispatched.

    PRD 3.7: "The gate then rejects the dispatch only when
    `projected_cold_ischemic_minutes` **strictly exceeds** `cit_limit_minutes`".
    PRD 3.7: "Fourth, `projected_cit_margin_minutes` is the organ's
    `cit_limit_minutes` less `projected_cold_ischemic_minutes`."

    Design: Difficulty/resource_temporal_overlap/transport_asset_closed_interval_legs_touch_at_endpoint
    """
    _first, second = _asset_carrying_one_leg_to_nine_o_clock(env)

    # The longer accepted leg projects 345 minutes, more than the refused leg's
    # 285, so cold ischemia was never what stopped the 09:00 departure.
    dispatched = validate_success(
        env.api.dispatch_transport(
            second.only_organ_id,
            transport_payload(
                second.asset["id"], "2026-08-26T09:01:00Z", "2026-08-26T11:00:00Z"
            ),
            env.logistics,
        ),
        200,
    )

    assert dispatched["projected_cold_ischemic_minutes"] == 345
    assert dispatched["projected_cit_margin_minutes"] == 735
    assert dispatched["transport_asset_id"] == second.asset["id"]
    assert dispatched["status"] == "RECOVERED"
