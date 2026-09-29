"""Transitive cascades: one event reaching through two or three further resources."""

from test_helpers import (
    ASSIGN_ASSIGNED,
    ASSIGN_DEFERRED,
    ASSIGN_RECLEAN_REQUIRED,
    CLEAN_DIRTY,
    CLEAN_RECLEAN_REQUIRED,
    COMPLIANCE_AT_LIMIT,
    COMPLIANCE_BREACH_BLOCKED,
    CYCLE_LATE_ESCALATED,
    DIRECTOR_HEADERS,
    INSPECTION_FAIL,
    ORDINANCE_NONE,
    SERVICE_CHECKOUT,
    SERVICE_DEEP_CLEAN,
    SHORTAGE_ESCALATED,
    ApiErrorId,
    assert_coverage_ratio,
    assert_credits,
    assert_linen_buckets,
    assert_roster_totals,
    assert_score_pct,
    assert_whole_minutes,
    build_scenario,
    dispatch_cycle,
    patch_attendant,
    read_assignment,
    read_attendant,
    read_day,
    read_linen_item,
    read_room,
    read_roster,
    return_cycle,
    start_payload,
    validate_error,
    validate_paginated,
)


def _reclean_of(api, assignment_id):
    """Re-clean rows are discovered only by filtering on `supersedes_assignment_id`."""
    rows, _ = validate_paginated(
        api.list_room_assignments(
            {"supersedes_assignment_id": assignment_id}, DIRECTOR_HEADERS
        )
    )
    assert len(rows) == 1, (
        f"exactly one re-clean should supersede {assignment_id}, got {len(rows)}"
    )
    return rows[0]


# --------------------------------------------------------------------------
# A late laundry return reaching the day ledger
# --------------------------------------------------------------------------


def _dispatched_batch_with_a_planned_deep_clean(api):
    """A checkout and a deep clean allocated, with eight sets away at the plant."""
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": "DUE_OUT"}, "103"],
        linen={"total_owned_sets": 20, "initial_soiled_sets": 8},
        clocked_in=False,
    )
    checkout = scenario.assign("101", SERVICE_CHECKOUT)
    deep = scenario.assign("103", SERVICE_DEEP_CLEAN)
    cycle = dispatch_cycle(
        api,
        scenario.linen_id,
        8,
        "2026-08-03T08:00:00.000Z",
        "2026-08-03T12:00:00.000Z",
        scenario.linen["version"],
    )
    return scenario, checkout, deep, cycle


def test_late_return_forces_the_linen_line_to_escalated_despite_a_full_shelf(api):
    """A 390-minute turnaround breaches the SLA and the shortage ladder is overridden.

    PRD 3.8: "Hop two returns the sets to `on_hand_clean` and, because a late
    cycle now exists on this line, forces the line's `shortage_status` to
    `ESCALATED` regardless of `coverage_ratio`."

    Design: Difficulty/transitive_cascade/late_laundry_return_cascades_to_deferred_deep_clean_and_day_ledger
    """
    scenario, _, _, cycle = _dispatched_batch_with_a_planned_deep_clean(api)

    returned = return_cycle(api, cycle["id"], "2026-08-03T14:30:00.000Z")

    assert_whole_minutes(returned["turnaround_minutes"], 390, "turnaround_minutes")
    assert returned["sla_breach"] is True
    assert returned["status"] == CYCLE_LATE_ESCALATED
    linen = read_linen_item(api, scenario.linen_id)
    assert_linen_buckets(linen, 20, 0, 0)
    assert_coverage_ratio(linen["coverage_ratio"], 5.0000)
    assert linen["shortage_status"] == SHORTAGE_ESCALATED, (
        "a full clean shelf must not clear the late-cycle escalation"
    )


def test_late_return_defers_the_deep_clean_and_restores_the_day_ledger(api):
    """The escalation sweeps the deep clean off the roster and the day total follows.

    PRD 3.8: "Hop three, because the line is now `ESCALATED`, sweeps deep cleans
    off the floor: every room assignment whose `service_type` is `DEEP_CLEAN` and
    whose `status` is `ASSIGNED`, sitting on a roster whose forecast day belongs
    to the same property and is still `PUBLISHED`, advances `ASSIGNED →
    DEFERRED`, processed in ascending `created_at` order."

    Design: Difficulty/transitive_cascade/late_laundry_return_cascades_to_deferred_deep_clean_and_day_ledger
    """
    scenario, checkout, deep, cycle = _dispatched_batch_with_a_planned_deep_clean(api)
    day_before = read_day(api, scenario.day_id)
    assert_credits(day_before["allocated_credits_total"], 3.00, "allocated_credits_total")

    return_cycle(api, cycle["id"], "2026-08-03T14:30:00.000Z")

    assert read_assignment(api, deep["id"])["status"] == ASSIGN_DEFERRED
    assert read_assignment(api, checkout["id"])["status"] == ASSIGN_ASSIGNED, (
        "only deep cleans are swept; the departure clean is untouched"
    )
    assert_roster_totals(read_roster(api, scenario.roster_id), 1.00, 420)
    assert_credits(
        read_day(api, scenario.day_id)["allocated_credits_total"],
        1.00,
        "allocated_credits_total",
    )


# --------------------------------------------------------------------------
# A failed inspection reaching probation and the sampling obligation
# --------------------------------------------------------------------------


def _four_rooms_cleaned(api):
    """Four departure cleans finished by one attendant, rest buffer respected."""
    scenario = build_scenario(
        api,
        rooms=[
            {"number": "101", "occupancy_state": "DUE_OUT"},
            {"number": "102", "occupancy_state": "DUE_OUT"},
            {"number": "103", "occupancy_state": "DUE_OUT"},
            {"number": "104", "occupancy_state": "DUE_OUT"},
        ],
        linen={"total_owned_sets": 20},
    )
    windows = [
        ("101", "2026-08-03T10:00:00.000Z", "2026-08-03T10:30:00.000Z"),
        ("102", "2026-08-03T10:50:00.000Z", "2026-08-03T11:20:00.000Z"),
        ("103", "2026-08-03T11:40:00.000Z", "2026-08-03T12:10:00.000Z"),
        ("104", "2026-08-03T12:30:00.000Z", "2026-08-03T13:00:00.000Z"),
    ]
    cleaned = [
        scenario.clean(number, SERVICE_CHECKOUT, started, finished)
        for number, started, finished in windows
    ]
    return scenario, cleaned


def test_failed_inspection_condemns_the_clean_and_inserts_the_reclean_row(api):
    """A bathroom score of 5 condemns an 78.0 clean and generates a 0.50-credit re-clean.

    PRD 3.6: "Separately, `critical_fail` is true when either the bathroom score
    or the linen score is 6 or lower — those two items are the ones a guest
    notices first, and a poor mark on either condemns the clean whatever the
    total says."

    Design: Difficulty/transitive_cascade/failed_inspection_cascades_reclean_probation_and_sampling_obligation
    """
    scenario, cleaned = _four_rooms_cleaned(api)

    inspection = scenario.inspect(
        cleaned[0]["id"],
        bathroom_points=5,
        linen_points=9,
        dust_points=9,
        amenity_points=9,
        floor_points=9,
    )

    assert_score_pct(inspection["score_pct"], 78.0)
    assert inspection["critical_fail"] is True
    assert inspection["result"] == INSPECTION_FAIL
    assert read_assignment(api, cleaned[0]["id"])["status"] == ASSIGN_RECLEAN_REQUIRED
    assert read_room(api, scenario.room_id("101"))["cleanliness_status"] == (
        CLEAN_RECLEAN_REQUIRED
    )
    reclean = _reclean_of(api, cleaned[0]["id"])
    assert reclean["id"] == inspection["generated_reclean_assignment_id"]
    assert reclean["reclean_generation"] == 1
    assert reclean["status"] == ASSIGN_ASSIGNED
    assert_credits(reclean["credits"], 0.50, "re-clean credits")


def test_failed_inspection_raises_probation_sampling_and_the_roster_totals(api):
    """Probation doubles the sampling obligation while the re-clean grows both totals.

    PRD 3.6: "Because the sampling rate is keyed on `quality_probation`, that
    single flag raises `required_inspection_samples` on the roster immediately —
    under the defaults, from one clean in five to one in two — and on every later
    roster of that attendant."

    Design: Difficulty/transitive_cascade/failed_inspection_cascades_reclean_probation_and_sampling_obligation
    """
    scenario, cleaned = _four_rooms_cleaned(api)

    scenario.inspect(
        cleaned[0]["id"],
        bathroom_points=5,
        linen_points=9,
        dust_points=9,
        amenity_points=9,
        floor_points=9,
    )

    attendant = read_attendant(api, scenario.worker_id)
    assert attendant["quality_probation"] is True
    assert attendant["lifetime_fail_count"] == 1
    roster = read_roster(api, scenario.roster_id)
    assert roster["required_inspection_samples"] == 2, (
        "four performed cleans at the probation rate of 0.50 owe two samples, "
        f"got {roster['required_inspection_samples']}"
    )
    assert roster["inspections_completed"] == 1
    assert_roster_totals(roster, 4.50, 2100)


# --------------------------------------------------------------------------
# A restricted-duty patch reaching a work blockade
# --------------------------------------------------------------------------


def _roster_at_the_ceiling_then_restricted(api):
    """Two deep cleans exactly on a 4.00 ceiling, then the ceiling is cut to 3.00."""
    scenario = build_scenario(
        api,
        property_overrides={
            "ordinance_profile": ORDINANCE_NONE,
            "max_daily_credits": 4.00,
        },
        rooms=["103", "104"],
        linen={"total_owned_sets": 20},
    )
    first = scenario.assign("103", SERVICE_DEEP_CLEAN)
    scenario.assign("104", SERVICE_DEEP_CLEAN)
    return scenario, first


def test_restricted_duty_patch_shrinks_the_cap_underneath_allocated_work(api):
    """Turning restricted duty on cuts the ceiling to 3.00 and blocks a 4.00 roster.

    PRD 3.1: "This is not a bookkeeping edit: flipping `restricted_duty`
    re-derives `effective_credit_cap` and `compliance_state` on every one of that
    attendant's rosters whose `status` is not `CLOSED`, and re-derives
    `required_inspection_samples` on those same rosters."

    Design: Difficulty/transitive_cascade/restricted_duty_patch_cascades_cap_reduction_into_work_blockade
    """
    scenario, _ = _roster_at_the_ceiling_then_restricted(api)
    before = read_roster(api, scenario.roster_id)
    assert before["compliance_state"] == COMPLIANCE_AT_LIMIT

    patched = patch_attendant(api, scenario.worker_id, restricted_duty=True)

    assert patched["restricted_duty"] is True
    roster = read_roster(api, scenario.roster_id)
    assert_credits(roster["effective_credit_cap"], 3.00, "effective_credit_cap")
    assert_credits(roster["assigned_credits"], 4.00, "assigned_credits")
    assert roster["compliance_state"] == COMPLIANCE_BREACH_BLOCKED


def test_blockaded_roster_refuses_the_start_and_leaves_the_room_dirty(api):
    """A breached roster accepts no start, and the room stays at the head of the loop.

    PRD 2.8: "A roster in `BREACH_BLOCKED` accepts no further work of any kind."

    Design: Difficulty/transitive_cascade/restricted_duty_patch_cascades_cap_reduction_into_work_blockade
    """
    scenario, first = _roster_at_the_ceiling_then_restricted(api)
    patch_attendant(api, scenario.worker_id, restricted_duty=True)

    response = api.start_assignment(
        first["id"],
        start_payload("2026-08-03T09:00:00.000Z"),
        scenario.attendant_headers(),
    )

    validate_error(response, ApiErrorId.ROSTER_WORKLOAD_BREACH)
    assert read_assignment(api, first["id"])["status"] == ASSIGN_ASSIGNED
    assert read_room(api, scenario.room_id("103"))["cleanliness_status"] == CLEAN_DIRTY
