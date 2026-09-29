"""The precedence ladder, aggregate gates, boundary instants and paired-field rules."""
from test_helpers import (
    ApiErrorId,
    api_client,
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    AUTHOR,
    ENGINEER,
    TECHNICIAN,
    advance_project,
    coordinate_project,
    corridor_members,
    create_corridor,
    create_intersection,
    decide_corridor,
    enrol_member,
    open_project,
    patch_intersection,
    project_version,
    read_corridor,
    read_intersection,
    read_plan,
    read_project,
    read_split,
    record_count,
    record_run,
    return_plan,
    screen_corridor,
    set_clock,
    setup_coordinated_plan,
    setup_project_in_data_collection,
    submit_plan,
)
from test_helpers.factories import (
    corridor_member_payload,
    intersection_payload,
    retiming_project_payload,
)

# No X-User-ID and no X-User-Role at all.
NO_AUTH = {"Content-Type": "application/json"}
# A role name outside the six the contract declares.
UNKNOWN_ROLE = build_user_headers("intern-1", "TrafficIntern")

UNKNOWN_ID = "11111111-1111-4111-8111-111111111111"

# Phase 1 carries a 20-second minimum green, which is both the largest on the
# plan (so the rescale residual lands there) and exactly satisfied by the
# resulting 24-second effective split.
MIN_GREEN_SPLITS = [
    {"phase_number": 1, "split_sec": 21, "min_green_sec": 20,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 2, "split_sec": 30, "min_green_sec": 15,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 4, "split_sec": 22, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 6, "split_sec": 22, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
]

MODERATE_VOLUMES = {"1": 350, "2": 500, "4": 250, "6": 180}


def test_each_doubly_broken_request_reports_the_earliest_gate_it_trips():
    """Auth, role, path resolution and body shape each pre-empt the pagination gate.

    PRD §2.7: "Checks are evaluated in the fixed order below, and **the first
    failure wins** — a later check never masks an earlier one" ... "Both headers
    present and non-blank — `ERR_UNAUTHENTICATED`." ... "`X-User-Role` is one of
    the six declared roles — `ERR_UNKNOWN_ROLE`." ... "The acting role is
    authorised for the target endpoint — `ERR_ROLE_NOT_PERMITTED`." ... "Path
    identifiers resolve, left to right — the eleven 404 codes of §2.6." ...
    "Request-body shape: required fields present, declared types honoured,
    numeric ranges respected, enum values inside their declared sets —
    `ERR_INVALID_REQUEST`." ... "Pagination parameters in range, on list
    endpoints — `ERR_INVALID_PAGINATION`." PRD §2.3: "`limit` defaults to 10 when
    omitted, may be no smaller than 1 and no larger than 100. `offset` defaults
    to 0 and may be no smaller than 0; there is no upper bound on `offset`. A
    `limit` below 1 or above 100, or an `offset` below 0, or either parameter
    supplied as something other than an integer, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 422)."

    Design: Corner/validations/gate_ladder_from_auth_to_pagination_rejected_in_priority_order
    """
    corridor = create_corridor(jurisdiction_class="ARTERIAL",
                               annual_volume_change_pct=20.0)

    validate_error(api_client.list_corridors(NO_AUTH, {"limit": 0}),
                   ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    validate_error(api_client.list_corridors(UNKNOWN_ROLE, {"limit": 0}),
                   ApiErrorId.ERR_UNKNOWN_ROLE.value, 401)

    # A forbidden role carrying a body that is malformed twice over.
    validate_error(
        api_client.create_corridor(
            {"name": "Second St", "annual_volume_change_pct": "not-a-number"},
            TECHNICIAN,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )

    validate_error(
        api_client.list_corridor_members(UNKNOWN_ID, ADMIN, {"limit": 0}),
        ApiErrorId.ERR_CORRIDOR_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.create_corridor_member(UNKNOWN_ID, {"sequence_index": "one"}, ADMIN),
        ApiErrorId.ERR_CORRIDOR_NOT_FOUND.value,
        404,
    )

    validate_error(
        api_client.create_corridor(
            {"name": "Third St", "jurisdiction_class": "BOULEVARD",
             "annual_volume_change_pct": 5.0},
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    validate_error(api_client.list_corridors(ADMIN, {"limit": 101}),
                   ApiErrorId.ERR_INVALID_PAGINATION.value, 422)
    validate_error(api_client.list_corridors(ADMIN, {"offset": -1}),
                   ApiErrorId.ERR_INVALID_PAGINATION.value, 422)

    # Both values sit exactly on the legal edge of the pagination contract.
    rows, meta = validate_paginated(
        api_client.list_corridors(ADMIN, {"limit": 100, "offset": 0}))
    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [corridor["id"]]


def test_the_min_green_gate_passes_on_equality_and_fails_after_half_a_second():
    """24 seconds clears a 24.0 requirement and misses a 24.5 one on the same splits.

    PRD §3.8: "Every one of the plan's phase splits must satisfy the
    minimum-green obligation — the phase's `effective_split_sec` must be at least
    the sum of its `min_green_sec`, its `yellow_sec` and its `red_clearance_sec`,
    with equality acceptable — and any phase falling short is refused with
    `ERR_MIN_GREEN_VIOLATION`." PRD §3.5: "Every accepted adjustment re-mirrors
    `effective_split_sec` onto the new `split_sec`, recomputes both of the plan's
    split totals, and increments the plan's `version`."

    Design: Corner/validations/min_green_gate_passes_at_exact_equality_then_fails_after_a_half_second_patch
    """
    ctx = setup_coordinated_plan(plan_overrides={"cycle_length_sec": 90},
                                 splits=MIN_GREEN_SPLITS)
    project_id = ctx["project"]["id"]
    plan_id = ctx["plan"]["id"]

    phase_one = read_split(plan_id, 1)
    # 21 * 105 / 95 == 23.2105 rounds to 23; the +1 residual lands on phase 1.
    assert phase_one["effective_split_sec"] == 24

    submitted = submit_plan(plan_id)
    assert submitted["status"] == "SUBMITTED"
    # No pedestrian phase means an empty check set, which is compliant.
    assert submitted["ped_compliance_state"] == "COMPLIANT"

    returned = return_plan(plan_id, reason="Nudge the phase 1 yellow interval.")
    assert returned["status"] == "DRAFT"
    assert returned["cycle_length_sec"] == 90
    assert returned["return_count"] == 1

    patched = validate_success(
        api_client.update_phase_split(phase_one["id"], {"yellow_sec": 3.5}, AUTHOR))
    assert float(patched["yellow_sec"]) == 3.5
    # The adjustment re-mirrors the effective split onto the drafted split.
    assert patched["effective_split_sec"] == 21

    coordinate_project(project_id)
    assert read_split(plan_id, 1)["effective_split_sec"] == 24

    validate_error(
        api_client.submit_timing_plan(plan_id, ENGINEER),
        ApiErrorId.ERR_MIN_GREEN_VIOLATION.value,
        422,
    )
    # A rejected submit writes nothing, so the plan does not advance.
    assert read_plan(plan_id)["status"] == "COORDINATED"


def test_before_study_completeness_quantifies_over_every_eligible_member():
    """One count and an AFTER run are not a study; the gate wants all members and a BEFORE run.

    PRD §3.4: "Every one of the corridor's members whose intersection posture is
    `READY` or `RESTRICTED` must have at least one `BEFORE` turning movement
    count recorded for this project, and the project must hold at least one
    `BEFORE` travel time run; either shortfall is refused with
    `ERR_BEFORE_STUDY_INCOMPLETE`." PRD §3.4: "A successful advance recomputes
    `eligible_member_count` and increments the project's `version`."

    Design: Corner/validations/before_study_completeness_is_an_aggregate_over_every_eligible_member
    """
    ctx = setup_project_in_data_collection(
        intersections=[{"max_cycle_length_sec": 150}, {"max_cycle_length_sec": 150}],
        distances=[0, 2640],
    )
    project_id = ctx["project"]["id"]
    first_id = ctx["intersections"][0]["id"]
    second_id = ctx["intersections"][1]["id"]

    assert read_corridor(ctx["corridor"]["id"])["member_count"] == 2
    assert ctx["project"]["status"] == "DATA_COLLECTION"
    assert ctx["project"]["eligible_member_count"] == 2

    validate_error(api_client.advance_project(project_id, ENGINEER),
                   ApiErrorId.ERR_BEFORE_STUDY_INCOMPLETE.value, 409)

    record_count(first_id, project_id, count_date="2026-07-15T00:00:00Z",
                 phase_volumes=MODERATE_VOLUMES)
    record_run(project_id, study_role="AFTER", started_at="2026-07-15T09:00:00Z",
               duration_sec=300, stops_count=3, arrivals_on_green_count=8,
               total_arrivals=12)
    # The second member still has no BEFORE count.
    validate_error(api_client.advance_project(project_id, ENGINEER),
                   ApiErrorId.ERR_BEFORE_STUDY_INCOMPLETE.value, 409)

    record_count(second_id, project_id, count_date="2026-07-16T00:00:00Z",
                 phase_volumes=MODERATE_VOLUMES)
    # Both members are covered now, but the only run carries study_role AFTER.
    validate_error(api_client.advance_project(project_id, ENGINEER),
                   ApiErrorId.ERR_BEFORE_STUDY_INCOMPLETE.value, 409)
    assert read_project(project_id)["status"] == "DATA_COLLECTION"

    record_run(project_id, study_role="BEFORE", started_at="2026-07-16T09:00:00Z")
    before_advance = project_version(project_id)

    advanced = advance_project(project_id)
    assert advanced["status"] == "PLAN_DEVELOPMENT"
    assert advanced["eligible_member_count"] == 2
    assert advanced["version"] == before_advance + 1


def test_the_study_window_is_already_expired_at_the_boundary_instant():
    """One second before the deadline the advance lands; at the deadline it is refused.

    PRD §3.4: "And the study data must still be fresh: the logical clock's
    current value must be strictly earlier than `study_window_start_at` advanced
    by `study_window_days` whole days. The deadline instant itself already counts
    as expired — at exactly that instant the advance is refused with
    `ERR_STUDY_WINDOW_EXPIRED`, while one second earlier it is accepted." PRD
    §2.5: "The clock is monotonic: a target instant strictly earlier than the
    clock's current value is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422)."

    Design: Corner/validations/study_window_expiry_is_inclusive_at_the_boundary_instant
    """
    shared = create_intersection(location_name="Shared Junction @ Main",
                                 max_cycle_length_sec=150)
    window = {"study_window_start_at": "2026-08-01T00:00:00Z", "study_window_days": 30}

    projects = {}
    for key in ("a", "b"):
        corridor = create_corridor(jurisdiction_class="ARTERIAL",
                                   annual_volume_change_pct=20.0)
        enrol_member(corridor["id"], shared["id"], 1, distance_from_prev_ft=0)
        screen_corridor(corridor["id"])
        decide_corridor(corridor["id"], "SELECT", rationale="Programme this corridor")
        project = open_project(corridor["id"], **window)
        record_count(shared["id"], project["id"], count_date="2026-08-02T00:00:00Z",
                     phase_volumes=MODERATE_VOLUMES)
        record_run(project["id"], started_at="2026-08-02T09:00:00Z")
        projects[key] = project

    set_clock("2026-08-30T23:59:59Z")
    # One second before the boundary the window is still open.
    assert advance_project(projects["b"]["id"])["status"] == "PLAN_DEVELOPMENT"

    set_clock("2026-08-31T00:00:00Z")
    stale_id = projects["a"]["id"]
    before_refusal = project_version(stale_id)
    validate_error(api_client.advance_project(stale_id, ENGINEER),
                   ApiErrorId.ERR_STUDY_WINDOW_EXPIRED.value, 409)

    untouched = read_project(stale_id)
    assert untouched["status"] == "DATA_COLLECTION"
    assert untouched["version"] == before_refusal

    # The window cannot be reopened by winding the logical clock back.
    validate_error(
        api_client.set_clock("2026-08-30T23:59:59Z", ADMIN),
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
        422,
    )


def test_project_creation_reads_the_selection_status_and_then_the_project_register():
    """UNSCREENED and DEFERRED both fail the selection gate; SELECTED fails the active-project one.

    PRD §3.2: "A new corridor starts at `selection_status` `UNSCREENED` with
    `member_count` 0, every complaint counter 0, `priority_score` 0,
    `priority_score_variant` null and `screened_at` null." PRD §3.2: "Either
    decision requires the corridor to be in `SCREENED`; from any other selection
    status the request is refused with `ERR_CORRIDOR_NOT_SCREENED`." PRD §3.4:
    "The corridor must be in `SELECTED`; any other selection status is refused
    with `ERR_CORRIDOR_NOT_SELECTED`. The corridor must also not already carry a
    project whose status is anything other than `CLOSED` or `ABANDONED`, a second
    live project being refused with `ERR_CORRIDOR_PROJECT_ACTIVE`."

    Design: Corner/validations/project_creation_gates_on_corridor_status_and_on_any_active_project
    """
    shared = create_intersection(location_name="Register Junction @ Main",
                                 max_cycle_length_sec=150)

    def corridor_with(jurisdiction_class):
        corridor = create_corridor(jurisdiction_class=jurisdiction_class,
                                   annual_volume_change_pct=20.0)
        enrol_member(corridor["id"], shared["id"], 1, distance_from_prev_ft=0)
        return corridor

    selected = corridor_with("ARTERIAL")
    screened = screen_corridor(selected["id"])
    assert float(screened["priority_score"]) == 91.25
    assert decide_corridor(selected["id"], "SELECT")["selection_status"] == "SELECTED"
    live = open_project(selected["id"], study_window_start_at="2026-08-01T00:00:00Z",
                        study_window_days=90)
    assert live["status"] == "DATA_COLLECTION"

    deferred = corridor_with("LOCAL")
    assert float(screen_corridor(deferred["id"])["priority_score"]) == 58.40
    assert decide_corridor(deferred["id"], "DEFER")["selection_status"] == "DEFERRED"

    fresh = corridor_with("ARTERIAL")
    assert read_corridor(fresh["id"])["selection_status"] == "UNSCREENED"
    validate_error(
        api_client.corridor_selection_decision(fresh["id"], {"decision": "SELECT"}, ADMIN),
        ApiErrorId.ERR_CORRIDOR_NOT_SCREENED.value,
        409,
    )

    window = {"study_window_start_at": "2026-08-01T00:00:00Z", "study_window_days": 90}
    for barred in (fresh["id"], deferred["id"]):
        validate_error(
            api_client.create_retiming_project(
                retiming_project_payload(barred, **window), ENGINEER),
            ApiErrorId.ERR_CORRIDOR_NOT_SELECTED.value,
            409,
        )

    # The selected corridor clears the selection gate and trips the register gate.
    validate_error(
        api_client.create_retiming_project(
            retiming_project_payload(selected["id"], **window), ENGINEER),
        ApiErrorId.ERR_CORRIDOR_PROJECT_ACTIVE.value,
        409,
    )

    rows, meta = validate_paginated(
        api_client.list_corridor_retiming_projects(selected["id"], ENGINEER))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [live["id"]]


def test_the_accessible_signal_pair_is_refused_unless_both_fields_move_together():
    """Either field alone is a mismatch in both directions; only the paired change lands.

    PRD §2.9: "The accessible-signal rule binds the first two together: an
    intersection with `aps_installed` true must carry `walking_speed_standard`
    `EXTENDED_3_0_FPS`, and a registration that pairs `aps_installed` true with
    `STD_3_5_FPS` is rejected with `ERR_APS_STANDARD_MISMATCH`." PRD §2.9: "The
    accessible-signal rule is re-evaluated against the *resulting* pair, and it is
    enforced in both directions on an update. Turning `aps_installed` on while
    `walking_speed_standard` would remain `STD_3_5_FPS` is
    `ERR_APS_STANDARD_MISMATCH`; so is clearing `aps_installed` while
    `walking_speed_standard` would remain `EXTENDED_3_0_FPS`. The two fields must
    move in the same request. Every accepted update re-derives
    `operational_posture` from the new health values and increments the
    intersection's `version`."

    Design: Corner/validations/aps_flag_and_walking_speed_standard_must_move_together
    """
    validate_error(
        api_client.create_intersection(
            intersection_payload(aps_installed=True,
                                 walking_speed_standard="STD_3_5_FPS"),
            ADMIN,
        ),
        ApiErrorId.ERR_APS_STANDARD_MISMATCH.value,
        422,
    )

    intersection = create_intersection()
    intersection_id = intersection["id"]
    assert intersection["aps_installed"] is False
    assert intersection["walking_speed_standard"] == "STD_3_5_FPS"
    assert intersection["version"] == 1

    # Half of the pair, in each of the two possible halves.
    validate_error(
        api_client.update_intersection(intersection_id, {"aps_installed": True}, ADMIN),
        ApiErrorId.ERR_APS_STANDARD_MISMATCH.value,
        422,
    )
    validate_error(
        api_client.update_intersection(
            intersection_id, {"walking_speed_standard": "EXTENDED_3_0_FPS"}, ADMIN),
        ApiErrorId.ERR_APS_STANDARD_MISMATCH.value,
        422,
    )
    assert read_intersection(intersection_id)["version"] == 1

    equipped = patch_intersection(intersection_id, aps_installed=True,
                                  walking_speed_standard="EXTENDED_3_0_FPS")
    assert equipped["aps_installed"] is True
    assert equipped["walking_speed_standard"] == "EXTENDED_3_0_FPS"
    assert equipped["version"] == 2

    # Coming back down is symmetric: neither field may be moved on its own.
    validate_error(
        api_client.update_intersection(intersection_id, {"aps_installed": False}, ADMIN),
        ApiErrorId.ERR_APS_STANDARD_MISMATCH.value,
        422,
    )
    validate_error(
        api_client.update_intersection(
            intersection_id, {"walking_speed_standard": "STD_3_5_FPS"}, ADMIN),
        ApiErrorId.ERR_APS_STANDARD_MISMATCH.value,
        422,
    )
    assert read_intersection(intersection_id)["version"] == 2

    stripped = patch_intersection(intersection_id, aps_installed=False,
                                  walking_speed_standard="STD_3_5_FPS")
    assert stripped["aps_installed"] is False
    assert stripped["walking_speed_standard"] == "STD_3_5_FPS"
    assert stripped["version"] == 3


def test_enrolment_wants_exactly_the_next_index_and_reports_duplicates_first():
    """A gap is refused at both ends, and a re-enrolment at a gapped index is a duplicate.

    PRD §3.2: "Sequencing is kept gap-free by construction: the supplied
    `sequence_index` must equal the corridor's current `member_count` plus 1, and
    anything else is refused with `ERR_SEQUENCE_INDEX_GAP`. An intersection
    already enrolled in that corridor is refused with
    `ERR_DUPLICATE_CORRIDOR_MEMBER`; the uniqueness is on the pairing of corridor
    and intersection, so the same intersection may legitimately belong to several
    corridors. The first member of a corridor has nothing before it, so a
    `distance_from_prev_ft` other than exactly 0 at `sequence_index` 1 is an
    invalid request. Each accepted enrolment recomputes `member_count` as the
    number of membership rows pointing at the corridor and increments the
    corridor's `version`." PRD §2.7: "Corridor-membership uniqueness and gap-free
    sequencing — `ERR_DUPLICATE_CORRIDOR_MEMBER`, then `ERR_SEQUENCE_INDEX_GAP`."

    Design: Corner/validations/member_sequence_index_must_be_exactly_member_count_plus_one
    """
    corridor = create_corridor()
    corridor_id = corridor["id"]
    first = create_intersection(location_name="Gapless @ First")
    second = create_intersection(location_name="Gapless @ Second")
    assert corridor["member_count"] == 0
    assert corridor["version"] == 1

    # An empty corridor wants index 1, not index 3.
    validate_error(
        api_client.create_corridor_member(
            corridor_id, corridor_member_payload(first["id"], 3), ADMIN),
        ApiErrorId.ERR_SEQUENCE_INDEX_GAP.value,
        422,
    )
    # The body-shape gate outranks the sequencing gate.
    validate_error(
        api_client.create_corridor_member(
            corridor_id,
            corridor_member_payload(first["id"], 1, distance_from_prev_ft=100),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    assert read_corridor(corridor_id)["member_count"] == 0

    enrolled = enrol_member(corridor_id, first["id"], 1, distance_from_prev_ft=0)
    assert enrolled["sequence_index"] == 1
    assert read_corridor(corridor_id)["member_count"] == 1

    # Index 1 is now behind the corridor, so a second member there is a gap.
    validate_error(
        api_client.create_corridor_member(
            corridor_id, corridor_member_payload(second["id"], 1,
                                                 distance_from_prev_ft=0), ADMIN),
        ApiErrorId.ERR_SEQUENCE_INDEX_GAP.value,
        422,
    )
    # This request breaks uniqueness and sequencing at once; uniqueness reports first.
    validate_error(
        api_client.create_corridor_member(
            corridor_id, corridor_member_payload(first["id"], 5), ADMIN),
        ApiErrorId.ERR_DUPLICATE_CORRIDOR_MEMBER.value,
        409,
    )

    enrol_member(corridor_id, second["id"], 2, distance_from_prev_ft=1320)
    settled = read_corridor(corridor_id)
    assert settled["member_count"] == 2
    assert settled["version"] == 3
    assert [m["sequence_index"] for m in corridor_members(corridor_id)] == [1, 2]

    # Uniqueness is scoped to the pairing, so another corridor may take the same one.
    other = create_corridor()
    assert enrol_member(other["id"], first["id"], 1,
                        distance_from_prev_ft=0)["sequence_index"] == 1
