"""Partial updates, computed reads, bulk actions, reverse lookups and read-your-writes."""
from test_helpers import (
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_START, NEVER_RETIMED_AGE_DAYS
from test_helpers.fixtures import (
    ENGINEER,
    INDEPENDENT_REVIEWER,
    REVIEWER,
    REVIEWER_ID,
    add_splits,
    coordinate_project,
    corridor_complaints,
    create_corridor,
    create_intersection,
    create_requester,
    decide_corridor,
    draft_plan,
    enrol_member,
    file_complaint,
    link_complaint,
    open_project,
    patch_intersection,
    project_complaints,
    project_plans,
    project_version,
    read_corridor,
    read_plan,
    read_ped_checks,
    read_requester,
    requester_complaints,
    screen_corridor,
    setup_draft_plan,
    setup_project_in_plan_development,
    submit_plan,
    triage_complaint,
    waive_check,
)
from test_helpers.test_users import make_public_requester_headers

# Phase 2 carries the greatest min_green, so it absorbs the rescale residual and
# operates at 34 seconds against a drafted 30.
PED_PASS_SPLITS = [
    {"phase_number": 1, "split_sec": 21, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 2, "split_sec": 30, "min_green_sec": 15,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0, "is_pedestrian_phase": True,
     "walk_sec": 7.0, "ped_clear_sec": 20.0, "crosswalk_length_ft": 62},
    {"phase_number": 4, "split_sec": 22, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 6, "split_sec": 22, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
]

# The same plan with a second crossing whose pedestrian change interval is short.
PED_MIXED_SPLITS = PED_PASS_SPLITS[:2] + [
    {"phase_number": 4, "split_sec": 22, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0, "is_pedestrian_phase": True,
     "walk_sec": 7.0, "ped_clear_sec": 10.0, "crosswalk_length_ft": 62},
    PED_PASS_SPLITS[3],
]

TWO_PHASE_SPLITS = [
    {"phase_number": 1, "split_sec": 20, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 2, "split_sec": 20, "min_green_sec": 12,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
]

PED_INTERSECTION = {
    "aps_installed": False,
    "walking_speed_standard": "STD_3_5_FPS",
    "max_cycle_length_sec": 150,
}


def test_patching_one_field_leaves_the_other_five_and_the_identity_alone():
    """A single-field PATCH is partial, still re-derives posture, and never rewrites created_at.

    PRD §2.9: "Updating an intersection is how detection and communication health,
    and the pedestrian configuration, stay current: an administrator may revise
    `detection_status`, `comm_status`, `aps_installed`, `walking_speed_standard`,
    `pedestrian_recall` and `max_cycle_length_sec`, each independently optional."
    ... "Every accepted update re-derives `operational_posture` from the new health
    values and increments the intersection's `version`." PRD §2.4: "Every resource
    also carries `created_at`, an ISO 8601 UTC timestamp with three fractional
    digits recording the instant the row was first stored." PRD §2.9: "while
    `last_retimed_at` is still null — meaning no timing plan for this intersection
    has ever reached `DEPLOYED` — the age reads exactly 3650 days"

    Design: Corner/endpoints/patch_intersection_is_a_partial_update_over_its_six_declared_inputs
    """
    intersection = create_intersection(
        location_name="Main St @ 1st Ave",
        controller_type="TS2_CABINET",
        detection_status="FULL",
        comm_status="ONLINE",
        aps_installed=False,
        walking_speed_standard="STD_3_5_FPS",
        pedestrian_recall=True,
        max_cycle_length_sec=150,
    )
    intersection_id = intersection["id"]
    assert intersection["version"] == 1
    created_at = intersection["created_at"]

    single = patch_intersection(intersection_id, max_cycle_length_sec=120)
    assert single["max_cycle_length_sec"] == 120
    # The five inputs the body omitted, plus the two PATCH does not accept at all.
    assert single["location_name"] == "Main St @ 1st Ave"
    assert single["controller_type"] == "TS2_CABINET"
    assert single["detection_status"] == "FULL"
    assert single["comm_status"] == "ONLINE"
    assert single["aps_installed"] is False
    assert single["walking_speed_standard"] == "STD_3_5_FPS"
    assert single["pedestrian_recall"] is True
    assert single["operational_posture"] == "READY"
    assert single["version"] == 2

    paired = patch_intersection(intersection_id, detection_status="PARTIAL",
                                pedestrian_recall=False)
    assert paired["detection_status"] == "PARTIAL"
    assert paired["pedestrian_recall"] is False
    # Carried over from the earlier PATCH rather than reset to the create value.
    assert paired["max_cycle_length_sec"] == 120
    assert paired["operational_posture"] == "RESTRICTED"
    assert paired["version"] == 3

    fetched = validate_success(api_client.get_intersection(intersection_id, ENGINEER))
    assert fetched["location_name"] == "Main St @ 1st Ave"
    assert fetched["detection_status"] == "PARTIAL"
    assert fetched["max_cycle_length_sec"] == 120
    assert fetched["pedestrian_recall"] is False
    assert fetched["version"] == 3
    assert fetched["last_retimed_at"] is None
    assert fetched["timing_plan_age_days"] == NEVER_RETIMED_AGE_DAYS
    assert fetched["created_at"] == created_at


def test_pedestrian_checks_only_exist_once_the_pipeline_has_written_them():
    """The listing is empty before coordination and afterwards records both sides of all three sub-checks.

    PRD §3.7: "The coordination pipeline creates one **pedestrian compliance
    check** for every phase split of every plan whose `is_pedestrian_phase` is
    true, in `phase_number` ascending order, and each check records both what was
    required and what the plan actually provides." PRD §3.7: "`walking_speed_fps`
    is the walking speed applied: 3.5 feet per second when the intersection's
    `walking_speed_standard` is `STD_3_5_FPS`" ... "`required_ped_clear_sec` is the
    crossing distance `crosswalk_length_ft` divided by that walking speed, raised
    **up** to the next tenth of a second" ... "`required_walk_sec` is the minimum
    WALK interval and depends on the accessible-signal equipment: 7.0 seconds
    where `aps_installed` is true, and 4.0 seconds where it is not" ...
    "`required_phase_length_sec` is the total the phase must accommodate: the
    required WALK interval plus the required pedestrian change interval plus the
    phase's `yellow_sec` plus its `red_clearance_sec`." PRD §3.7: "`provided_walk_sec`
    snapshots its `walk_sec`, and `provided_phase_length_sec` snapshots its
    `effective_split_sec` — the **post-rescale** operating split, never the drafted
    one." PRD §3.7: "If none of the three falls short, the `result` is `PASS` and
    `failure_reason` is null."

    Design: Corner/endpoints/pedestrian_checks_are_a_computed_read_produced_by_the_pipeline
    """
    ctx = setup_draft_plan(intersections=[dict(PED_INTERSECTION)],
                           plan_overrides={"cycle_length_sec": 90},
                           splits=PED_PASS_SPLITS)
    plan_id = ctx["plan"]["id"]

    empty, empty_meta = validate_paginated(
        api_client.list_pedestrian_checks(plan_id, ENGINEER))
    assert empty == []
    assert empty_meta["total_count"] == 0

    coordinate_project(ctx["project"]["id"])

    rows, meta = validate_paginated(api_client.list_pedestrian_checks(plan_id, REVIEWER))
    assert meta["total_count"] == 1
    check = rows[0]
    assert check["timing_plan_id"] == plan_id
    assert check["phase_number"] == 2
    assert float(check["walking_speed_fps"]) == 3.5
    # 62 / 3.5 == 17.7142..., raised up to the next tenth.
    assert float(check["required_ped_clear_sec"]) == 17.8
    assert float(check["provided_ped_clear_sec"]) == 20.0
    assert float(check["required_walk_sec"]) == 4.0
    assert float(check["provided_walk_sec"]) == 7.0
    assert float(check["required_phase_length_sec"]) == 25.8
    # 30 * 105 / 95 == 33.16 rounds to 33, and phase 2 takes the +1 residual.
    assert check["provided_phase_length_sec"] == 34
    assert check["result"] == "PASS"
    assert check["failure_reason"] is None

    failing, failing_meta = validate_paginated(
        api_client.list_pedestrian_checks(plan_id, REVIEWER, {"result": "FAIL"}))
    assert failing_meta["total_count"] == 0
    assert failing == []

    plan = read_plan(plan_id)
    assert plan["ped_compliance_state"] == "COMPLIANT"

    # Reading the computed row again persists nothing.
    assert read_ped_checks(plan_id)[0]["version"] == check["version"]
    assert read_plan(plan_id)["version"] == plan["version"]


def test_coordination_either_moves_every_draft_plan_or_none_of_them():
    """A local ceiling on the second intersection rolls the whole bulk action back.

    PRD §3.6: "one request by the project's `TimingEngineer` takes every `DRAFT`
    plan of the project `DRAFT → COORDINATED`" ... "That candidate is then tested
    against the hard ceiling, which is the **smallest** `max_cycle_length_sec`
    among the participants: a coordinated cycle above that ceiling cannot be
    served by every intersection on the corridor, so the whole request is refused
    with `ERR_CYCLE_EXCEEDS_LOCAL_MAX` and nothing is written." PRD §3.6: "Finally
    each plan's `status` becomes `COORDINATED`, each touched plan's `version` is
    incremented by 1, and the project's `version` is incremented by 1."

    Design: Corner/endpoints/coordinate_is_an_all_or_nothing_bulk_action_over_every_plan
    """
    ctx = setup_project_in_plan_development(
        intersections=[{"max_cycle_length_sec": 150}, {"max_cycle_length_sec": 90}],
        distances=[0, 2640],
    )
    project_id = ctx["project"]["id"]
    first_id, second_id = (i["id"] for i in ctx["intersections"])

    plan_ids = []
    for intersection_id in (first_id, second_id):
        plan = draft_plan(project_id, intersection_id, cycle_length_sec=90,
                          coordination_ref="MASTER")
        add_splits(plan["id"], TWO_PHASE_SPLITS)
        plan_ids.append(plan["id"])

    before_versions = {pid: read_plan(pid)["version"] for pid in plan_ids}
    before_project = project_version(project_id)

    # The corridor wants 105 seconds; the second intersection can only serve 90.
    validate_error(
        api_client.coordinate_project(project_id, ENGINEER),
        ApiErrorId.ERR_CYCLE_EXCEEDS_LOCAL_MAX.value,
        422,
    )
    rolled_back = project_plans(project_id)
    assert len(rolled_back) == 2
    for plan in rolled_back:
        assert plan["status"] == "DRAFT"
        assert plan["cycle_length_sec"] == 90
        assert plan["offset_sec"] == 0
        assert plan["version"] == before_versions[plan["id"]]
    assert project_version(project_id) == before_project

    assert patch_intersection(second_id, max_cycle_length_sec=150)["max_cycle_length_sec"] == 150

    coordinated = coordinate_project(project_id)
    assert coordinated["version"] == before_project + 1

    plans = {p["id"]: p for p in project_plans(project_id)}
    for pid in plan_ids:
        assert plans[pid]["status"] == "COORDINATED"
        assert plans[pid]["cycle_length_sec"] == 105
        assert plans[pid]["version"] == before_versions[pid] + 1
    # 2640 ft at 44.0 ft/s is 60 seconds of progression behind the first member.
    assert plans[plan_ids[0]]["offset_sec"] == 0
    assert plans[plan_ids[1]]["offset_sec"] == 60


def test_one_complaint_is_reachable_from_all_three_of_its_parents():
    """The requester and corridor lookups see it at once; the project lookup only after the link.

    PRD §3.3: "A requester's own row and their complaint list, the latter
    filterable by `status`, are readable by a `CitizenLiaison` for anybody and by a
    `PublicRequester` only for themselves." PRD §3.2: "Alongside its own read, a
    corridor exposes three reverse-reachability listings: its membership rows in
    sequence order, the retiming projects on it filterable by `status`, and the
    complaints filed against it filterable by `status` and `category`." PRD §3.4:
    "A project exposes six reverse-reachability listings: its turning movement
    counts filterable by `study_role`, its travel time runs filterable by
    `study_role` and `direction`, its timing plans filterable by `status`, its
    field observations filterable by `resolution_status`, the complaints linked to
    it filterable by `status`, and its performance evaluations filterable by
    `status`." PRD §3.3: "A successful link moves the complaint `TRIAGED → LINKED`,
    writes `linked_project_id`, moves one unit from `complaint_open_count` to
    `complaint_linked_count`, and increments the complaint's `version`."

    Design: Corner/endpoints/one_complaint_is_reachable_from_every_declared_cross_reference
    """
    corridor = create_corridor(jurisdiction_class="ARTERIAL",
                               annual_volume_change_pct=20.0)
    intersection = create_intersection(location_name="Reachable @ 1st Ave")
    enrol_member(corridor["id"], intersection["id"], 1, distance_from_prev_ft=0)
    screen_corridor(corridor["id"])
    decide_corridor(corridor["id"], "SELECT", rationale="Programme this corridor")
    project = open_project(corridor["id"], study_window_start_at="2026-08-01T00:00:00Z",
                           study_window_days=90)
    project_id = project["id"]

    requester = create_requester(display_name="Ada Citizen", email="ada@example.org")
    coordination = file_complaint(requester["id"], corridor["id"], category="COORDINATION",
                                 narrative="Progression is broken northbound.")
    pedestrian = file_complaint(requester["id"], corridor["id"], category="PEDESTRIAN",
                                narrative="Not enough crossing time.")

    assert len(requester_complaints(requester["id"])) == 2
    # The category filter exists on the corridor lookup and on no other.
    by_category = corridor_complaints(corridor["id"], category="PEDESTRIAN")
    assert [row["id"] for row in by_category] == [pedestrian["id"]]

    # The project lookup keys on linked_project_id, which is still null.
    assert project_complaints(project_id) == []

    assert triage_complaint(coordination["id"], "TRIAGE",
                            note="Valid coordination complaint.")["status"] == "TRIAGED"
    linked = link_complaint(coordination["id"], project_id)
    assert linked["status"] == "LINKED"
    assert linked["linked_project_id"] == project_id

    assert [row["id"] for row in project_complaints(project_id)] == [coordination["id"]]

    # The status filter partitions the two complaints the same way on both lookups.
    by_status = corridor_complaints(corridor["id"], status="LINKED")
    assert [row["id"] for row in by_status] == [coordination["id"]]
    still_open = requester_complaints(requester["id"], status="OPEN")
    assert [row["id"] for row in still_open] == [pedestrian["id"]]


def test_a_waiver_is_admissible_only_against_the_row_that_actually_failed():
    """Waiving the passing check is refused; waiving the failing one unblocks the submit.

    PRD §3.7: "Three guards apply: the check must currently be `FAIL`, and one
    already passing or already waived is refused with `ERR_PED_CHECK_NOT_FAILING`"
    ... "A `CertifyingEngineer` may **waive** a check, moving its `result` `FAIL →
    WAIVED`, and must supply a `waiver_justification` in writing; the server
    records that text and stamps `waived_by_user_id` with the acting `X-User-ID`."
    PRD §3.7: "After a waiver is applied, if the plan no longer holds any check
    whose `result` is `FAIL`, the plan's `ped_compliance_state` becomes `WAIVED`
    and the plan's own `version` is incremented." PRD §3.8: "Its
    `ped_compliance_state` must be `COMPLIANT` or `WAIVED`; a plan still `PENDING`
    or still `NON_COMPLIANT` is refused with `ERR_PED_CLEARANCE_INSUFFICIENT`."
    PRD §3.7: "If the provided pedestrian change interval is less than the required
    one, the `result` is `FAIL` with `failure_reason` `PED_CLEAR_SHORT`."

    Design: Corner/endpoints/waive_is_a_conditional_action_gated_on_the_checks_own_result
    """
    ctx = setup_draft_plan(intersections=[dict(PED_INTERSECTION)],
                           plan_overrides={"cycle_length_sec": 90},
                           splits=PED_MIXED_SPLITS)
    plan_id = ctx["plan"]["id"]
    coordinate_project(ctx["project"]["id"])

    checks = read_ped_checks(plan_id)
    assert [c["phase_number"] for c in checks] == [2, 4]
    passing, failing = checks
    assert passing["result"] == "PASS"
    assert failing["result"] == "FAIL"
    # 10.0 provided against 17.8 required decides before the other two sub-checks.
    assert failing["failure_reason"] == "PED_CLEAR_SHORT"
    assert read_plan(plan_id)["ped_compliance_state"] == "NON_COMPLIANT"

    validate_error(
        api_client.submit_timing_plan(plan_id, ENGINEER),
        ApiErrorId.ERR_PED_CLEARANCE_INSUFFICIENT.value,
        422,
    )
    validate_error(
        api_client.waive_pedestrian_check(
            passing["id"], {"waiver_justification": "Trying to waive a passing check."},
            INDEPENDENT_REVIEWER),
        ApiErrorId.ERR_PED_CHECK_NOT_FAILING.value,
        409,
    )

    justification = "Crosswalk closed for construction through the retiming period."
    waived = waive_check(failing["id"], justification=justification)
    assert waived["result"] == "WAIVED"
    assert waived["waived_by_user_id"] == REVIEWER_ID
    assert waived["waiver_justification"] == justification

    plan = read_plan(plan_id)
    assert plan["ped_compliance_state"] == "WAIVED"
    assert plan["status"] == "COORDINATED"

    # The identical submit now passes, so the waiver was the only thing in its way.
    assert submit_plan(plan_id)["status"] == "SUBMITTED"


def test_every_denormalised_counter_is_already_correct_on_the_very_next_read():
    """Buckets, the requester counter and both score variants keep up with each write.

    PRD §2.11: "When they do, the whole set of effects is applied within the
    triggering request, in the order this document pins, and every touched row has
    its `updated_at` refreshed and its `version` incremented by 1 — including rows
    the caller never named." PRD §3.3: "The server stamps `received_at` with the
    logical clock's current value ... sets `status` to `OPEN`, leaves
    `linked_project_id` null and `reopen_count` at 0, refreshes the corridor's
    `complaint_total_count` and `complaint_open_count`, and increments the
    requester's `open_complaint_count` by 1." PRD §3.3: "`TRIAGED` and `OPEN` both
    live in the open bucket, so a triage leaves `complaint_open_count` and the
    requester's `open_complaint_count` numerically unchanged, whereas
    `CLOSED_NO_ACTION` lives in the terminal bucket, so a no-action closure moves
    one unit from `complaint_open_count` to `complaint_terminal_count` and
    decrements the requester's `open_complaint_count` by 1." PRD §3.2: "Complaints
    in `CLOSED_NO_ACTION` are excluded from this window count" ... "Then
    `avg_plan_age_days` and `priority_score` are recomputed under the screening
    variant, `priority_score_variant` is set to `SCREENING`, `screened_at` is
    stamped with the logical clock's current value, and the corridor's `version` is
    incremented." PRD §3.2: "Both decisions recompute `complaint_count_12mo`,
    `avg_plan_age_days` and `priority_score` under the **programming variant**
    before anything else is decided, set `priority_score_variant` to `PROGRAMMING`,
    and increment the corridor's `version`."

    Design: Corner/consistency_model/immediate_visibility_of_every_denormalised_counter_and_computed_score
    """
    intersection = create_intersection(location_name="Immediate @ 1st Ave",
                                       max_cycle_length_sec=150)
    corridor = create_corridor(jurisdiction_class="ARTERIAL",
                               annual_volume_change_pct=20.0)
    assert corridor["complaint_total_count"] == 0
    assert float(corridor["priority_score"]) == 0.00
    assert corridor["priority_score_variant"] is None
    corridor_id = corridor["id"]

    member = enrol_member(corridor_id, intersection["id"], 1, distance_from_prev_ft=0)
    assert member["sequence_index"] == 1

    requester = create_requester(display_name="Dana Reyes", email="dana@example.org")
    assert requester["open_complaint_count"] == 0
    requester_id = requester["id"]
    public = make_public_requester_headers(requester_id)

    first = file_complaint(
        requester_id, corridor_id, headers=public, category="COORDINATION",
        narrative="Northbound platoon stops at every signal in the morning.")
    assert first["status"] == "OPEN"
    assert first["received_at"].startswith(CLOCK_START[:-1])

    fresh = read_corridor(corridor_id)
    assert fresh["complaint_total_count"] == 1
    assert fresh["complaint_open_count"] == 1
    assert fresh["complaint_linked_count"] == 0
    assert fresh["complaint_terminal_count"] == 0
    assert read_requester(requester_id, headers=public)["open_complaint_count"] == 1

    assert triage_complaint(first["id"], "TRIAGE",
                            note="Already on the shortlist.")["status"] == "TRIAGED"
    triaged = read_corridor(corridor_id)
    assert triaged["complaint_total_count"] == 1
    assert triaged["complaint_open_count"] == 1
    assert triaged["complaint_terminal_count"] == 0

    screened = screen_corridor(corridor_id)
    assert screened["selection_status"] == "SCREENED"
    assert screened["member_count"] == 1
    assert float(screened["avg_plan_age_days"]) == float(NEVER_RETIMED_AGE_DAYS)
    assert screened["complaint_count_12mo"] == 1
    # (0.45 * 1.0 + 0.35 * 0.8 + 0.20 * 0.05) * 1.25 * 100.0
    assert float(screened["priority_score"]) == 92.50
    assert screened["priority_score_variant"] == "SCREENING"
    assert screened["screened_at"].startswith(CLOCK_START[:-1])

    second = file_complaint(requester_id, corridor_id, category="TIMING_OTHER",
                            narrative="Unrelated question about the side street.")
    assert second["status"] == "OPEN"
    assert triage_complaint(second["id"], "NO_ACTION",
                            note="Not a timing matter.")["status"] == "CLOSED_NO_ACTION"

    closed = read_corridor(corridor_id)
    assert closed["complaint_total_count"] == 2
    assert closed["complaint_open_count"] == 1
    assert closed["complaint_terminal_count"] == 1
    assert read_requester(requester_id, headers=public)["open_complaint_count"] == 1

    selected = decide_corridor(corridor_id, "SELECT",
                               rationale="Score clears the programming threshold.")
    assert selected["selection_status"] == "SELECTED"
    # The no-action complaint raised the total but stayed out of the window count.
    assert selected["complaint_count_12mo"] == 1
    assert float(selected["priority_score"]) == 92.50
    assert selected["priority_score_variant"] == "PROGRAMMING"
