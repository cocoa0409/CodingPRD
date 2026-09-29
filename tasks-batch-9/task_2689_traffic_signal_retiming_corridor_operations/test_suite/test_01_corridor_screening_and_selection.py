"""Corridor screening, the two average-age variants, and the selection decision."""
from test_helpers import ApiErrorId, api_client, validate_error, validate_paginated
from test_helpers.fixtures import (
    ADMIN,
    ENGINEER,
    create_corridor,
    create_intersection,
    create_requester,
    decide_corridor,
    enrol_member,
    file_complaint,
    open_project,
    patch_intersection,
    read_corridor,
    screen_corridor,
    setup_canonical_implemented_project,
    setup_corridor_with_members,
)


def _one_ready_and_one_blocked_member():
    """An ARTERIAL corridor holding a freshly retimed member and a dark member.

    The first member has just had a plan deployed, so its `timing_plan_age_days`
    is 0; the second has `detection_status` `FAILED`, so its posture is `BLOCKED`
    and it has never been retimed, so its age is the synthetic 3650 days.
    """
    base = setup_canonical_implemented_project()
    retimed = base["intersections"][0]
    dark = create_intersection(detection_status="FAILED")
    corridor = create_corridor(jurisdiction_class="ARTERIAL", annual_volume_change_pct=12.0)
    enrol_member(corridor["id"], retimed["id"], 1)
    enrol_member(corridor["id"], dark["id"], 2, distance_from_prev_ft=2640)
    requester = create_requester()
    for _ in range(3):
        file_complaint(requester["id"], corridor["id"])
    return {"corridor": read_corridor(corridor["id"]), "retimed": retimed, "dark": dark}


def test_screening_variant_drops_the_blocked_member_from_the_average():
    """Screening averages only the READY/RESTRICTED members, so the dark member is gone.

    PRD §3.2: "Under the **screening variant** the included set is the members
    whose intersection posture is `READY` or `RESTRICTED`, so `BLOCKED` members
    are dropped from both the numerator and the denominator". With one 0-day
    member included the mean is 0.00, so the age component contributes nothing
    and the score is (0.45*0 + 0.35*(12.0/25.0) + 0.20*(3/20)) * 1.25 * 100.0 =
    24.75.

    Design: Difficulty/dual_variant_calc/corridor_priority_score_screening_vs_programming_variant_divergence
    """
    ctx = _one_ready_and_one_blocked_member()
    screened = screen_corridor(ctx["corridor"]["id"])

    assert screened["selection_status"] == "SCREENED"
    assert screened["member_count"] == 2
    assert screened["complaint_count_12mo"] == 3
    assert float(screened["avg_plan_age_days"]) == 0.00
    assert float(screened["priority_score"]) == 24.75
    assert screened["priority_score_variant"] == "SCREENING"


def test_programming_variant_admits_the_blocked_member_and_lifts_the_score():
    """The selection decision re-runs the average over every member, posture ignored.

    PRD §3.2: "Under the **programming variant** every member is included
    regardless of posture, because once money is being committed the corridor
    must be judged as it actually stands, `BLOCKED` intersections and all." and
    "Both decisions recompute `complaint_count_12mo`, `avg_plan_age_days` and
    `priority_score` under the **programming variant** before anything else is
    decided, set `priority_score_variant` to `PROGRAMMING`". The mean becomes
    (0 + 3650) / 2 = 1825.00, saturating the age component, so the score is
    (0.45 + 0.35*0.48 + 0.20*0.15) * 1.25 * 100.0 = 81.00.

    Design: Difficulty/dual_variant_calc/corridor_priority_score_screening_vs_programming_variant_divergence
    """
    ctx = _one_ready_and_one_blocked_member()
    screened = screen_corridor(ctx["corridor"]["id"])
    decided = decide_corridor(ctx["corridor"]["id"], "SELECT",
                              rationale="Dark member drags the programming average up")

    assert decided["selection_status"] == "SELECTED"
    assert float(decided["avg_plan_age_days"]) == 1825.00
    assert float(decided["priority_score"]) == 81.00
    assert decided["priority_score_variant"] == "PROGRAMMING"
    # The same four static inputs, two different averages, one 56.25 point gap.
    assert float(decided["priority_score"]) - float(screened["priority_score"]) == 56.25
    assert decided["version"] == screened["version"] + 1


def _collector_corridor_scoring(complaint_count):
    """A COLLECTOR corridor with zero volume change and one never-retimed member.

    The age component saturates at 1, the volume component is 0, so the score is
    (0.45 + 0.20 * complaint_count/20) * 1.00 * 100.0.
    """
    intersection = create_intersection()
    corridor = create_corridor(jurisdiction_class="COLLECTOR", annual_volume_change_pct=0.0)
    enrol_member(corridor["id"], intersection["id"], 1)
    requester = create_requester()
    for _ in range(complaint_count):
        file_complaint(requester["id"], corridor["id"])
    return screen_corridor(corridor["id"])


def test_selection_accepts_a_programming_score_of_exactly_the_threshold():
    """Five complaints put the score on 50.00 exactly, and exactly 50.00 selects.

    PRD §3.2: "the freshly recomputed programming-variant score must be at least
    the select threshold of 50.00 — exactly 50.00 is accepted, 49.99 is not —
    failing which the decision is refused with
    `ERR_SCORE_BELOW_SELECT_THRESHOLD`".

    Design: Difficulty/boundary_precision_check/selection_decision_at_exactly_the_fifty_point_zero_score_threshold
    """
    screened = _collector_corridor_scoring(5)
    assert float(screened["priority_score"]) == 50.00
    assert screened["complaint_count_12mo"] == 5

    decided = decide_corridor(screened["id"], "SELECT", rationale="Right on the threshold")
    assert decided["selection_status"] == "SELECTED"
    assert float(decided["priority_score"]) == 50.00
    assert decided["priority_score_variant"] == "PROGRAMMING"


def test_selection_one_point_below_the_threshold_writes_nothing_at_all():
    """Four complaints leave the score on 49.00, and the refused SELECT is a no-op.

    PRD §3.2: "A refused `SELECT` writes **nothing at all**: the corridor keeps
    its screening-variant `priority_score`, its `priority_score_variant` of
    `SCREENING`, its `selection_status` of `SCREENED` and its previous `version`,
    exactly as if the request had never been made."

    Design: Difficulty/boundary_precision_check/selection_decision_at_exactly_the_fifty_point_zero_score_threshold
    """
    screened = _collector_corridor_scoring(4)
    assert float(screened["priority_score"]) == 49.00

    validate_error(
        api_client.corridor_selection_decision(
            screened["id"], {"decision": "SELECT", "rationale": "One point short"}, ADMIN
        ),
        ApiErrorId.ERR_SCORE_BELOW_SELECT_THRESHOLD.value,
        409,
    )

    after = read_corridor(screened["id"])
    assert after["selection_status"] == "SCREENED"
    assert float(after["priority_score"]) == 49.00
    assert after["priority_score_variant"] == "SCREENING"
    assert after["version"] == screened["version"]


def test_screening_a_corridor_with_no_members_is_refused():
    """A member-less corridor cannot be screened, and the screen leaves no trace.

    PRD §3.2: "the corridor must have at least one member, and at least one of
    those members' intersections must have an `operational_posture` of `READY`
    or `RESTRICTED`, failing which the screen is refused with
    `ERR_NO_ELIGIBLE_MEMBERS` — a corridor with zero members and a corridor
    whose every member is `BLOCKED` both fail on exactly this code."

    Design: Difficulty/boundary_precision_check/screen_zero_cardinality_eligible_member_set_rejected
    """
    corridor = create_corridor()
    assert corridor["member_count"] == 0

    validate_error(
        api_client.screen_corridor(corridor["id"], ADMIN),
        ApiErrorId.ERR_NO_ELIGIBLE_MEMBERS.value,
        409,
    )

    after = read_corridor(corridor["id"])
    assert after["selection_status"] == "UNSCREENED"
    assert after["screened_at"] is None
    assert after["priority_score_variant"] is None
    assert after["version"] == corridor["version"]


def test_screening_an_all_blocked_corridor_is_refused_until_one_member_recovers():
    """The same code covers an all-BLOCKED corridor, and a repair makes it screenable.

    PRD §3.2: "at least one of those members' intersections must have an
    `operational_posture` of `READY` or `RESTRICTED`, failing which the screen is
    refused with `ERR_NO_ELIGIBLE_MEMBERS`". PRD §2.10: "Otherwise, if
    communication is `INTERMITTENT`, or detection is `PARTIAL` or `NONE`, the
    posture is `RESTRICTED`." A single `RESTRICTED` member is eligible, and its
    never-retimed 3650-day age saturates the age component, so the COLLECTOR
    corridor scores 0.45 * 1.00 * 100.0 = 45.00.

    Design: Difficulty/boundary_precision_check/screen_zero_cardinality_eligible_member_set_rejected
    """
    ctx = setup_corridor_with_members(
        intersections=[{"detection_status": "FAILED"}],
        jurisdiction_class="COLLECTOR",
        annual_volume_change_pct=0.0,
    )
    corridor_id = ctx["corridor"]["id"]
    assert ctx["corridor"]["member_count"] == 1

    validate_error(
        api_client.screen_corridor(corridor_id, ADMIN),
        ApiErrorId.ERR_NO_ELIGIBLE_MEMBERS.value,
        409,
    )
    assert read_corridor(corridor_id)["selection_status"] == "UNSCREENED"

    repaired = patch_intersection(ctx["intersections"][0]["id"], detection_status="PARTIAL")
    assert repaired["operational_posture"] == "RESTRICTED"

    screened = screen_corridor(corridor_id)
    assert screened["selection_status"] == "SCREENED"
    assert float(screened["avg_plan_age_days"]) == 3650.00
    assert float(screened["priority_score"]) == 45.00


def test_project_creation_is_refused_from_every_non_selected_status():
    """UNSCREENED, SCREENED and DEFERRED all refuse to carry a retiming project.

    PRD §3.4: "The corridor must be in `SELECTED`; any other selection status is
    refused with `ERR_CORRIDOR_NOT_SELECTED`."

    Design: Difficulty/cross_entity_state_dependency/project_creation_depends_on_corridor_selection_status
    """
    ctx = setup_corridor_with_members()
    corridor_id = ctx["corridor"]["id"]

    def refused():
        validate_error(
            api_client.create_retiming_project(
                {
                    "corridor_id": corridor_id,
                    "study_window_start_at": "2026-07-01T00:00:00Z",
                    "study_window_days": 180,
                    "lead_engineer_user_id": "timing-eng-1",
                },
                ENGINEER,
            ),
            ApiErrorId.ERR_CORRIDOR_NOT_SELECTED.value,
            409,
        )

    assert read_corridor(corridor_id)["selection_status"] == "UNSCREENED"
    refused()

    assert screen_corridor(corridor_id)["selection_status"] == "SCREENED"
    refused()

    assert decide_corridor(corridor_id, "DEFER")["selection_status"] == "DEFERRED"
    refused()


def test_project_creation_succeeds_once_the_corridor_reaches_selected():
    """Selecting the very same corridor opens the gate and pins eligible_member_count.

    PRD §3.4: "The corridor must be in `SELECTED`; any other selection status is
    refused with `ERR_CORRIDOR_NOT_SELECTED`." and "A new project starts in
    `DATA_COLLECTION` with `tuning_round` 0 and `last_tuning_completed_at` null,
    and its `eligible_member_count` is computed as the number of the corridor's
    members whose intersection posture is `READY` or `RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/project_creation_depends_on_corridor_selection_status
    """
    ctx = setup_corridor_with_members(
        intersections=[{}, {"detection_status": "FAILED"}], distances=[0, 1320]
    )
    corridor_id = ctx["corridor"]["id"]
    screen_corridor(corridor_id)
    assert decide_corridor(corridor_id, "SELECT")["selection_status"] == "SELECTED"

    project = open_project(corridor_id)
    assert project["corridor_id"] == corridor_id
    assert project["status"] == "DATA_COLLECTION"
    assert project["tuning_round"] == 0
    assert project["last_tuning_completed_at"] is None
    # Two members, but the BLOCKED one is not eligible.
    assert project["eligible_member_count"] == 1


def test_a_second_live_project_on_the_same_corridor_is_refused():
    """One live project per corridor, so the second create is refused outright.

    PRD §3.4: "The corridor must also not already carry a project whose status is
    anything other than `CLOSED` or `ABANDONED`, a second live project being
    refused with `ERR_CORRIDOR_PROJECT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/project_creation_depends_on_corridor_selection_status
    """
    ctx = setup_corridor_with_members()
    corridor_id = ctx["corridor"]["id"]
    screen_corridor(corridor_id)
    decide_corridor(corridor_id, "SELECT")
    first = open_project(corridor_id)
    assert first["status"] == "DATA_COLLECTION"

    validate_error(
        api_client.create_retiming_project(
            {
                "corridor_id": corridor_id,
                "study_window_start_at": "2026-07-01T00:00:00Z",
                "lead_engineer_user_id": "timing-eng-2",
            },
            ENGINEER,
        ),
        ApiErrorId.ERR_CORRIDOR_PROJECT_ACTIVE.value,
        409,
    )

    projects, _meta = validate_paginated(
        api_client.list_corridor_retiming_projects(corridor_id, ADMIN)
    )
    assert len(projects) == 1
