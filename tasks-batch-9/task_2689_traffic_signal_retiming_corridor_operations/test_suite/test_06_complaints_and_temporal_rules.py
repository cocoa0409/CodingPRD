"""Advance gate ordering, complaint linkage across entities, run spacing, and abandonment."""
from test_helpers import ApiErrorId, api_client, assert_instant_equals, validate_error
from test_helpers.fixtures import (
    ENGINEER,
    LIAISON,
    TECHNICIAN,
    close_project,
    create_requester,
    file_complaint,
    link_complaint,
    open_project,
    project_counts,
    project_runs,
    read_complaint,
    read_corridor,
    read_project,
    read_requester,
    record_count,
    record_run,
    setup_project_in_plan_development,
    setup_selected_corridor,
    triage_complaint,
)

# A window that opened on new year's day and closed thirty days later, so the
# 2026-08-01 logical clock is months past the deadline.
EXPIRED_WINDOW = {
    "study_window_start_at": "2026-01-01T00:00:00Z",
    "study_window_days": 30,
}


def _project_past_its_study_deadline():
    """A DATA_COLLECTION project holding no counts and no runs, whose window has closed."""
    ctx = setup_selected_corridor()
    ctx["project"] = open_project(ctx["corridor"]["id"], **EXPIRED_WINDOW)
    return ctx


def test_the_completeness_gate_is_reported_before_the_expired_window():
    """Both advance gates are violated and the data-completeness one is what surfaces.

    PRD §3.4: "Every one of the corridor's members whose intersection posture is
    `READY` or `RESTRICTED` must have at least one `BEFORE` turning movement
    count recorded for this project, and the project must hold at least one
    `BEFORE` travel time run; either shortfall is refused with
    `ERR_BEFORE_STUDY_INCOMPLETE`. And the study data must still be fresh: the
    logical clock's current value must be strictly earlier than
    `study_window_start_at` advanced by `study_window_days` whole days."

    Design: Difficulty/priority_pair_validation_conflict/advance_before_study_priority_60_beats_study_window_priority_65_rejected
    """
    ctx = _project_past_its_study_deadline()
    project_id = ctx["project"]["id"]
    assert ctx["project"]["status"] == "DATA_COLLECTION"

    validate_error(
        api_client.advance_project(project_id, ENGINEER),
        ApiErrorId.ERR_BEFORE_STUDY_INCOMPLETE.value,
        409,
    )
    assert read_project(project_id)["status"] == "DATA_COLLECTION"


def test_supplying_the_missing_study_data_exposes_the_expired_window():
    """With the study complete the same advance reports the deadline instead.

    PRD §3.4: "The deadline instant itself already counts as expired — at exactly
    that instant the advance is refused with `ERR_STUDY_WINDOW_EXPIRED`, while
    one second earlier it is accepted." PRD §3.4 also pins the listings that prove
    the data really landed: "A project exposes six reverse-reachability listings:
    its turning movement counts filterable by `study_role`, its travel time runs
    filterable by `study_role` and `direction`".

    Design: Difficulty/priority_pair_validation_conflict/advance_before_study_priority_60_beats_study_window_priority_65_rejected
    """
    ctx = _project_past_its_study_deadline()
    project_id = ctx["project"]["id"]

    record_count(ctx["intersections"][0]["id"], project_id,
                 count_date="2026-01-15T00:00:00Z")
    record_run(project_id, started_at="2026-01-15T09:00:00Z")

    validate_error(
        api_client.advance_project(project_id, ENGINEER),
        ApiErrorId.ERR_STUDY_WINDOW_EXPIRED.value,
        409,
    )

    assert read_project(project_id)["status"] == "DATA_COLLECTION"
    counts = project_counts(project_id, study_role="BEFORE")
    assert len(counts) == 1
    assert counts[0]["study_role"] == "BEFORE"
    runs = project_runs(project_id, study_role="BEFORE")
    assert len(runs) == 1
    assert runs[0]["study_role"] == "BEFORE"


def _two_corridors_each_with_a_triaged_complaint():
    """Symmetric corridors A and B, each SELECTED with its own DATA_COLLECTION project."""
    built = {}
    requester = create_requester()
    for key in ("a", "b"):
        ctx = setup_selected_corridor()
        project = open_project(ctx["corridor"]["id"])
        complaint = file_complaint(requester["id"], ctx["corridor"]["id"])
        triage_complaint(complaint["id"], "TRIAGE", note="Queued")
        built[key] = {"corridor": ctx["corridor"], "project": project,
                      "complaint": complaint}
    built["requester"] = requester
    return built


def test_linking_to_a_project_on_another_corridor_is_a_referential_failure():
    """The project is perfectly healthy; only its corridor is the wrong one.

    PRD §3.3: "The liaison supplies the `project_id` of a retiming project, which
    must belong to the very corridor the complaint names — a project on a
    different corridor is refused with `ERR_COMPLAINT_PROJECT_MISMATCH`".

    Design: Difficulty/cross_entity_state_dependency/complaint_link_depends_on_project_corridor_identity_and_terminality
    """
    built = _two_corridors_each_with_a_triaged_complaint()
    complaint = built["a"]["complaint"]
    foreign_project = built["b"]["project"]
    assert foreign_project["status"] == "DATA_COLLECTION"

    validate_error(
        api_client.link_complaint(
            complaint["id"], {"project_id": foreign_project["id"]}, LIAISON
        ),
        ApiErrorId.ERR_COMPLAINT_PROJECT_MISMATCH.value,
        422,
    )

    unchanged = read_complaint(built["a"]["corridor"]["id"], complaint["id"])
    assert unchanged["status"] == "TRIAGED"
    assert unchanged["linked_project_id"] is None


def test_linking_to_an_abandoned_project_is_a_state_failure():
    """Right corridor, terminal project: a different code and a different status.

    PRD §3.3: "and which must not already be `CLOSED` or `ABANDONED`, a terminal
    project being refused with `ERR_PROJECT_TERMINAL`. A successful link moves
    the complaint `TRIAGED → LINKED`, writes `linked_project_id`, moves one unit
    from `complaint_open_count` to `complaint_linked_count`, and increments the
    complaint's `version`. The requester's `open_complaint_count` does not move,
    because `LINKED` is still one of the three statuses that count as open from
    the citizen's point of view."

    Design: Difficulty/cross_entity_state_dependency/complaint_link_depends_on_project_corridor_identity_and_terminality
    """
    built = _two_corridors_each_with_a_triaged_complaint()
    b_project = built["b"]["project"]

    abandoned = close_project(b_project["id"], "ABANDONED", note="Funding pulled")
    assert abandoned["status"] == "ABANDONED"

    validate_error(
        api_client.link_complaint(
            built["b"]["complaint"]["id"], {"project_id": b_project["id"]}, LIAISON
        ),
        ApiErrorId.ERR_PROJECT_TERMINAL.value,
        409,
    )
    refused = read_complaint(built["b"]["corridor"]["id"], built["b"]["complaint"]["id"])
    assert refused["status"] == "TRIAGED"
    assert refused["linked_project_id"] is None

    # The healthy pairing on corridor A goes through.
    linked = link_complaint(built["a"]["complaint"]["id"], built["a"]["project"]["id"])
    assert linked["status"] == "LINKED"
    assert linked["linked_project_id"] == built["a"]["project"]["id"]

    corridor_a = read_corridor(built["a"]["corridor"]["id"])
    assert corridor_a["complaint_open_count"] == 0
    assert corridor_a["complaint_linked_count"] == 1
    corridor_b = read_corridor(built["b"]["corridor"]["id"])
    assert corridor_b["complaint_open_count"] == 1
    assert corridor_b["complaint_linked_count"] == 0
    # LINKED still counts as open for the citizen, so both complaints do.
    assert read_requester(built["requester"]["id"])["open_complaint_count"] == 2


# The stored run occupies the closed interval [09:00:00, 09:05:20] northbound.
STORED_RUN = {
    "study_role": "BEFORE", "direction": "NB",
    "started_at": "2026-07-15T09:00:00Z", "duration_sec": 320,
    "stops_count": 5, "arrivals_on_green_count": 4, "total_arrivals": 12,
}


def _run_payload(**overrides):
    payload = {
        "study_role": "BEFORE", "direction": "NB", "duration_sec": 300,
        "stops_count": 4, "arrivals_on_green_count": 5, "total_arrivals": 12,
    }
    payload.update(overrides)
    return payload


def _project_with_one_stored_run():
    """A DATA_COLLECTION project holding exactly one northbound before run."""
    ctx = setup_selected_corridor()
    ctx["project"] = open_project(ctx["corridor"]["id"])
    ctx["run"] = record_run(ctx["project"]["id"], **STORED_RUN)
    return ctx


def test_closed_intervals_reject_overlap_touching_and_a_gap_one_second_short():
    """Four geometries all inside the buffer, all refused on the same code.

    PRD §3.4: "Treat each run as occupying the **closed** interval from its
    `started_at` to its `started_at` plus its `duration_sec`. A new run is
    accepted only when the gap between its interval and every stored run's
    interval, measured on whichever side the new run falls, is at least 120
    seconds: a gap of exactly 120 seconds is accepted, a gap of 119 seconds is
    refused, and overlapping intervals or intervals that merely touch at an
    endpoint — a gap of zero — are refused. The rejection is
    `ERR_RUN_SPACING_VIOLATION`." PRD §3.4: "The server stamps `recorded_at` with
    the logical clock's current value; that stamp, not `started_at`, is what the
    certified performance variant later filters on."

    Design: Difficulty/resource_temporal_overlap/travel_time_run_intervals_closed_with_120_second_buffer_per_project_direction
    """
    ctx = _project_with_one_stored_run()
    project_id = ctx["project"]["id"]
    assert_instant_equals(ctx["run"]["recorded_at"], "2026-08-01T00:00:00Z", "recorded_at")

    for started_at, duration in (
        ("2026-07-15T09:03:00Z", 300),   # starts inside the stored interval
        ("2026-07-15T09:05:20Z", 300),   # touches the stored end exactly, gap 0
        ("2026-07-15T09:07:19Z", 300),   # gap of 119 seconds on the later side
        ("2026-07-15T08:54:00Z", 320),   # ends 08:59:20, only 40 seconds early
    ):
        validate_error(
            api_client.create_travel_time_run(
                project_id, _run_payload(started_at=started_at, duration_sec=duration),
                TECHNICIAN,
            ),
            ApiErrorId.ERR_RUN_SPACING_VIOLATION.value,
            409,
        )

    # Four refusals wrote nothing at all.
    assert len(project_runs(project_id)) == 1


def test_the_buffer_is_satisfied_at_exactly_120_seconds_and_direction_keys_the_resource():
    """A southbound pass may overlap outright, and 120 seconds of gap is enough.

    PRD §3.4: "Runs in different directions, or with different study roles, or on
    different projects, never constrain each other." and "a gap of exactly 120
    seconds is accepted". The stored northbound interval ends at 09:05:20, so a
    run starting at 09:07:20 sits exactly 120 seconds clear of it.

    Design: Difficulty/resource_temporal_overlap/travel_time_run_intervals_closed_with_120_second_buffer_per_project_direction
    """
    ctx = _project_with_one_stored_run()
    project_id = ctx["project"]["id"]

    southbound = record_run(project_id, **_run_payload(
        direction="SB", started_at="2026-07-15T09:03:00Z",
        stops_count=7, arrivals_on_green_count=3, total_arrivals=18,
    ))
    assert southbound["direction"] == "SB"
    assert_instant_equals(southbound["started_at"], "2026-07-15T09:03:00Z", "started_at")

    exactly_clear = record_run(project_id, **_run_payload(
        started_at="2026-07-15T09:07:20Z"
    ))
    assert_instant_equals(exactly_clear["started_at"], "2026-07-15T09:07:20Z", "started_at")

    northbound = project_runs(project_id, study_role="BEFORE", direction="NB")
    assert len(northbound) == 2
    for actual, expected in zip(
        sorted(r["started_at"] for r in northbound),
        ("2026-07-15T09:00:00Z", "2026-07-15T09:07:20Z"),
    ):
        assert_instant_equals(actual, expected, "started_at")


def _corridor_with_a_triaged_and_a_closed_complaint():
    """One PLAN_DEVELOPMENT project, one TRIAGED complaint and one terminal complaint."""
    ctx = setup_project_in_plan_development()
    requester = create_requester()
    corridor_id = ctx["corridor"]["id"]
    triaged = file_complaint(requester["id"], corridor_id, category="COORDINATION",
                             narrative="Progression breaks down northbound after 9am.")
    closed = file_complaint(requester["id"], corridor_id, category="DETECTION",
                            narrative="Loop at the side street never calls.")
    triage_complaint(triaged["id"], "TRIAGE", note="Queued for the coordination program")
    triage_complaint(closed["id"], "NO_ACTION", note="Duplicate of a maintenance ticket")
    ctx["requester"] = requester
    ctx["triaged"] = triaged
    ctx["closed"] = closed
    return ctx


def _partition(corridor):
    return (
        corridor["complaint_open_count"],
        corridor["complaint_linked_count"],
        corridor["complaint_terminal_count"],
        corridor["complaint_total_count"],
    )


def test_linking_moves_one_unit_between_two_buckets_and_leaves_the_citizen_alone():
    """Before and after the link the three buckets still sum to the total.

    PRD §2.12: "The **complaint partition**: every complaint of a corridor sits
    in exactly one of three buckets — `complaint_open_count`,
    `complaint_linked_count` and `complaint_terminal_count` — and those three
    always sum to `complaint_total_count`. Any transition that moves a complaint
    between buckets decrements one and increments another in the same operation,
    so the partition is never briefly wrong." PRD §3.3: "A successful
    link moves the complaint `TRIAGED → LINKED` ... moves one unit from
    `complaint_open_count` to `complaint_linked_count` ... The requester's
    `open_complaint_count` does not move".

    Design: Difficulty/compensating_invariant/project_abandonment_conserves_the_corridor_complaint_partition
    """
    ctx = _corridor_with_a_triaged_and_a_closed_complaint()
    corridor_id = ctx["corridor"]["id"]
    requester_id = ctx["requester"]["id"]
    assert ctx["project"]["status"] == "PLAN_DEVELOPMENT"

    before = read_corridor(corridor_id)
    assert _partition(before) == (1, 0, 1, 2)
    # The no-action closure already left the citizen's open bucket at one.
    assert read_requester(requester_id)["open_complaint_count"] == 1

    linked = link_complaint(ctx["triaged"]["id"], ctx["project"]["id"])
    assert linked["status"] == "LINKED"
    assert linked["linked_project_id"] == ctx["project"]["id"]

    after = read_corridor(corridor_id)
    assert _partition(after) == (0, 1, 1, 2)
    assert read_requester(requester_id)["open_complaint_count"] == 1


def test_abandonment_restores_the_partition_and_leaves_only_a_reopen_count():
    """The compensation lands the corridor back on its pre-link counts exactly.

    PRD §3.10: "every complaint whose `linked_project_id` is this project and
    whose status is `LINKED` moves `LINKED → OPEN` with `linked_project_id`
    cleared to null and `reopen_count` incremented by 1. That complaint cascade
    is the exact compensation of the link operation — one unit moves from the
    corridor's `complaint_linked_count` back to its `complaint_open_count`,
    restoring the partition to its pre-link values — while the requester's
    `open_complaint_count` is left unchanged, because `LINKED` was already
    counted in that requester's open bucket." and "Abandonment applies to
    complaints of every `category`".

    Design: Difficulty/compensating_invariant/project_abandonment_conserves_the_corridor_complaint_partition
    """
    ctx = _corridor_with_a_triaged_and_a_closed_complaint()
    corridor_id = ctx["corridor"]["id"]
    requester_id = ctx["requester"]["id"]
    baseline = _partition(read_corridor(corridor_id))

    link_complaint(ctx["triaged"]["id"], ctx["project"]["id"])
    assert _partition(read_corridor(corridor_id)) == (0, 1, 1, 2)

    abandoned = close_project(ctx["project"]["id"], "ABANDONED",
                              note="Corridor deferred to next fiscal year")
    assert abandoned["status"] == "ABANDONED"

    restored = read_corridor(corridor_id)
    assert _partition(restored) == baseline == (1, 0, 1, 2)
    assert read_requester(requester_id)["open_complaint_count"] == 1

    reopened = read_complaint(corridor_id, ctx["triaged"]["id"])
    assert reopened["status"] == "OPEN"
    assert reopened["linked_project_id"] is None
    # The round trip's only lasting trace.
    assert reopened["reopen_count"] == 1

    untouched = read_complaint(corridor_id, ctx["closed"]["id"])
    assert untouched["status"] == "CLOSED_NO_ACTION"
    assert untouched["reopen_count"] == 0
