"""Boundary precision: floors, clamps and thresholds probed one cent — or one slot —
either side of the value the contract names."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_scoped_request,
    agreement_payload,
    api_client,
    create_vetted_volunteer,
    current_engagement_version,
    deliverable_scores_payload,
    drive_review_to_outcome,
    get_success_data,
    handoff_payload,
    make_volunteer_headers,
    milestone_payload,
    read_cycle,
    read_engagement,
    read_volunteer,
    scope_change_request_payload,
    set_clock,
    setup_held_milestone_engagement,
    setup_roster,
    setup_submitted_engagement,
    setup_world,
    time_log_payload,
    validate_error,
    validate_success,
    valuation_payload,
)

SINGLE_DELIVERABLE = [
    {
        "title": "Compliance memo",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 40.00,
        "acceptance_criteria": "Memo accepted by the board",
    }
]

TWELVE_DELIVERY_HOURS = [
    {"work_date": "2026-08-12T00:00:00Z", "hours": 12.00, "activity_class": "DELIVERY"},
]

FORTY_FIVE_POINT_NINE_NINE = [
    {"work_date": "2026-08-12T00:00:00Z", "hours": 12.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-13T00:00:00Z", "hours": 12.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-14T00:00:00Z", "hours": 12.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-15T00:00:00Z", "hours": 9.99, "activity_class": "DELIVERY"},
]


# ===========================================================================
# The reliability floor: strict at 0.4000
# ===========================================================================
def _reinstate(world):
    """Lift the volunteer back to `ACTIVE` whenever the reliability floor has paused her,
    so the next engagement in the history can be accepted and worked."""
    if read_volunteer(world)["status"] == "PAUSED":
        get_success_data(
            api_client.patch_volunteer_status(
                world["volunteer"]["id"], {"to_status": "ACTIVE"}, world["pm_headers"]
            )
        )


def _live_engagement(world, title):
    """Scope one more request on the roster's partner, match it to the roster's single
    volunteer, execute the agreement and start the work."""
    _reinstate(world)
    extra = add_scoped_request(world, title=title, deliverables=SINGLE_DELIVERABLE)
    offer = get_success_data(
        api_client.match_project_request(extra["request"]["id"], world["spec_headers"])
    )
    engagement = get_success_data(
        api_client.accept_match_offer(offer["id"], world["volunteer_headers"])
    )
    agreement = get_success_data(
        api_client.create_agreement(
            engagement["id"],
            agreement_payload(engagement["version"]),
            world["pm_headers"],
        )
    )
    get_success_data(api_client.send_agreement(agreement["id"], world["pm_headers"]))
    get_success_data(
        api_client.execute_agreement(agreement["id"], world["volunteer_headers"])
    )
    get_success_data(
        api_client.execute_agreement(agreement["id"], world["partner_headers"])
    )
    engagement = get_success_data(
        api_client.start_engagement(engagement["id"], world["volunteer_headers"])
    )
    return {
        "request": extra["request"],
        "deliverables": extra["deliverables"],
        "engagement": engagement,
    }


def _checkin(world, engagement_id, due_at, *, missed, hold_clock, sweep_clock,
             reported=0.00):
    """Schedule one check-in and either hold it inside the grace band or leave it for the
    operations checkpoint to mark missed."""
    milestone = get_success_data(
        api_client.create_milestone(
            engagement_id, milestone_payload(due_at=due_at), world["pm_headers"]
        )
    )
    if not missed:
        set_clock(hold_clock, world["pm_headers"])
        get_success_data(
            api_client.hold_milestone(
                milestone["id"],
                {"reported_cumulative_hours": reported},
                world["pm_headers"],
            )
        )
    set_clock(sweep_clock, world["pm_headers"])
    get_success_data(
        api_client.recalculate_program_cycle(world["cycle"]["id"], world["pm_headers"])
    )
    return milestone


def _terminal_history(*, h4_missed, h3_missed):
    """Four terminal engagements for one volunteer, built oldest first so the decay ranks
    read the `SCOPE_BREACH`, the conditional handoff, the voided agreement and the oldest
    `SCOPE_BREACH` from the most recent backwards."""
    world = setup_roster()
    pm = world["pm_headers"]

    fourth = _live_engagement(world, "Grant compliance review")
    _checkin(
        world,
        fourth["engagement"]["id"],
        "2026-08-05T00:00:00Z",
        missed=h4_missed,
        hold_clock="2026-08-04T00:00:00Z",
        sweep_clock="2026-08-07T00:00:00Z",
    )
    get_success_data(
        api_client.terminate_engagement(
            fourth["engagement"]["id"], pm, {"termination_reason": "SCOPE_BREACH"}
        )
    )

    third = _live_engagement(world, "Bylaw modernisation")
    _checkin(
        world,
        third["engagement"]["id"],
        "2026-08-12T00:00:00Z",
        missed=h3_missed,
        hold_clock="2026-08-11T00:00:00Z",
        sweep_clock="2026-08-14T00:00:00Z",
    )
    get_success_data(
        api_client.terminate_engagement(
            third["engagement"]["id"], pm, {"termination_reason": "AGREEMENT_VOIDED"}
        )
    )

    second = _live_engagement(world, "Employee policy refresh")
    _checkin(
        world,
        second["engagement"]["id"],
        "2026-08-19T00:00:00Z",
        missed=True,
        hold_clock="2026-08-18T00:00:00Z",
        sweep_clock="2026-08-21T00:00:00Z",
    )
    _reinstate(world)
    get_success_data(
        api_client.create_time_log(
            second["engagement"]["id"],
            time_log_payload(work_date="2026-08-20T00:00:00Z", hours=12.00),
            world["volunteer_headers"],
        )
    )
    _checkin(
        world,
        second["engagement"]["id"],
        "2026-08-26T00:00:00Z",
        missed=False,
        hold_clock="2026-08-25T00:00:00Z",
        sweep_clock="2026-08-26T00:00:00Z",
        reported=12.00,
    )
    _reinstate(world)
    get_success_data(
        api_client.submit_engagement(
            second["engagement"]["id"], world["volunteer_headers"]
        )
    )
    review = get_success_data(
        api_client.create_quality_review(
            second["engagement"]["id"], world["reviewer_headers"]
        )
    )
    get_success_data(
        api_client.score_quality_review(
            review["id"],
            deliverable_scores_payload({d["id"]: 3 for d in second["deliverables"]}),
            world["reviewer_headers"],
        )
    )
    get_success_data(
        api_client.decide_quality_review(
            review["id"], world["reviewer_headers"], {"request_rework": False}
        )
    )
    get_success_data(
        api_client.handoff_engagement(
            second["engagement"]["id"], handoff_payload(), pm
        )
    )

    first = _live_engagement(world, "Endowment policy audit")
    _checkin(
        world,
        first["engagement"]["id"],
        "2026-09-02T00:00:00Z",
        missed=False,
        hold_clock="2026-09-01T00:00:00Z",
        sweep_clock="2026-09-04T00:00:00Z",
    )
    get_success_data(
        api_client.terminate_engagement(
            first["engagement"]["id"], pm, {"termination_reason": "SCOPE_BREACH"}
        )
    )
    return world


def test_01_a_decay_weighted_score_of_exactly_the_floor_pauses_nobody(api):
    """PRD §3.2: "The comparison is strict — a score of exactly 0.4000 does not pause
    anyone."
    PRD §3.2: "The gating figure, `reliability_score`, uses the decay-weighted variant: it
    takes only the eight most recent terminal engagements in that order (or all of them
    when the volunteer has fewer), gives the engagement at rank zero a weight of 1, the
    next a weight of 0.85, the next 0.85 multiplied by itself, and so on — each rank's
    weight is 0.85 raised to that zero-based rank and rounded to six decimals — then
    divides the weighted sum of point values by the sum of the weights actually used and
    rounds to four decimals."

    Design: Difficulty/boundary_precision/reliability_floor_strict_at_0_4000
    """
    world = _terminal_history(h4_missed=False, h3_missed=True)

    volunteer = read_volunteer(world)
    assert volunteer["reliability_score"] == pytest.approx(0.4000, abs=1e-4), (
        f"Expected reliability_score exactly 0.4000, got "
        f"{volunteer['reliability_score']}"
    )
    assert volunteer["status"] == "ACTIVE", (
        f"Expected the volunteer to survive the floor as ACTIVE, got "
        f"{volunteer['status']}"
    )
    assert volunteer["pause_reason"] is None, (
        f"Expected a null pause_reason, got {volunteer['pause_reason']}"
    )


def test_02_the_lifetime_average_ignores_the_decay_weights(api):
    """PRD §3.2: "The reporting figure, `reliability_score_lifetime`, uses the unweighted
    lifetime variant: it averages the point values of every terminal engagement ever,
    however many there are, and rounds to four decimals."
    PRD §3.9: "And because the engagement has now reached a terminal `work_status`, the
    volunteer's `terminal_engagement_count` rises by one and both reliability variants
    rerun — which may itself pause the volunteer and withdraw her open offers."

    Design: Difficulty/boundary_precision/reliability_floor_strict_at_0_4000
    """
    world = _terminal_history(h4_missed=False, h3_missed=True)

    volunteer = read_volunteer(world)
    assert volunteer["terminal_engagement_count"] == 4, (
        f"Expected four terminal engagements, got "
        f"{volunteer['terminal_engagement_count']}"
    )
    assert volunteer["reliability_score_lifetime"] == pytest.approx(0.4000, abs=1e-4), (
        f"Expected reliability_score_lifetime 0.4000, got "
        f"{volunteer['reliability_score_lifetime']}"
    )


def test_03_one_more_missed_checkin_drops_below_the_floor_and_pauses(api):
    """PRD §3.2: "One threshold consequence hangs off the decay-weighted figure alone: if
    `reliability_score` falls strictly below 0.4000 while the volunteer's `status` is
    `ACTIVE`, the volunteer moves to `PAUSED` with `pause_reason` `RELIABILITY_FLOOR`,
    dragging the offer-withdrawal cascade above with it."
    PRD §3.2: "From that value the program subtracts one tenth for each missed check-in the
    engagement recorded — the engagement's `missed_checkin_count` multiplied by 0.10 —
    rounds the result to four decimals, and floors it at zero so no single engagement can
    contribute a negative amount."

    Design: Difficulty/boundary_precision/reliability_floor_strict_at_0_4000
    """
    world = _terminal_history(h4_missed=True, h3_missed=True)

    volunteer = read_volunteer(world)
    assert volunteer["reliability_score"] == pytest.approx(0.3808, abs=1e-4), (
        f"Expected reliability_score 0.3808, got {volunteer['reliability_score']}"
    )
    assert volunteer["reliability_score_lifetime"] == pytest.approx(0.3750, abs=1e-4), (
        f"Expected reliability_score_lifetime 0.3750, got "
        f"{volunteer['reliability_score_lifetime']}"
    )
    assert volunteer["status"] == "PAUSED", (
        f"Expected the volunteer PAUSED below the floor, got {volunteer['status']}"
    )
    assert volunteer["pause_reason"] == "RELIABILITY_FLOOR", (
        f"Expected pause_reason RELIABILITY_FLOOR, got {volunteer['pause_reason']}"
    )


def test_04_a_held_checkin_on_the_voided_engagement_keeps_her_above_the_floor(api):
    """PRD §3.2: "Each terminal engagement earns a point value before penalties: 1.00 when
    it was `HANDED_OFF` with a `quality_gate` of `PASSED`; 0.70 when it was `HANDED_OFF`
    with a `quality_gate` of `CONDITIONAL`; 0.00 when it was `TERMINATED` for
    `QUALITY_FAILURE`; 0.25 when it was `TERMINATED` for `SCOPE_BREACH` or `ADMIN`; and
    0.60 when it was `TERMINATED` for `AGREEMENT_VOIDED` or `PARTNER_SUSPENDED`."
    PRD §3.2: "Engagements are ordered most-recent-first by the instant they went terminal,
    which is the engagement's `handoff_at` when present and otherwise its `terminated_at`,
    with the engagement's own `created_at` descending as the tie-break; row identifiers
    never participate in the ordering."

    Design: Difficulty/boundary_precision/reliability_floor_strict_at_0_4000
    """
    world = _terminal_history(h4_missed=False, h3_missed=False)

    volunteer = read_volunteer(world)
    assert volunteer["reliability_score"] == pytest.approx(0.4227, abs=1e-4), (
        f"Expected reliability_score 0.4227, got {volunteer['reliability_score']}"
    )
    assert volunteer["reliability_score_lifetime"] == pytest.approx(0.4250, abs=1e-4), (
        f"Expected reliability_score_lifetime 0.4250, got "
        f"{volunteer['reliability_score_lifetime']}"
    )
    assert volunteer["status"] == "ACTIVE", (
        f"Expected the volunteer ACTIVE above the floor, got {volunteer['status']}"
    )


# ===========================================================================
# The creep ladder: three inclusive floors on one rising quantity
# ===========================================================================
CREEP_RUNGS = ["A1", "A2", "B1", "B2", "C1", "C2"]

CREEP_LADDER = [
    (
        "A2",
        [{"work_date": "2026-08-19T00:00:00Z", "hours": 0.01, "activity_class": "ADMIN"}],
        "2026-08-23T00:00:00Z",
        "2026-08-22T00:00:00Z",
        46.00,
    ),
    (
        "B1",
        [{"work_date": "2026-08-22T00:00:00Z", "hours": 5.99,
          "activity_class": "DELIVERY"}],
        "2026-08-26T00:00:00Z",
        "2026-08-25T00:00:00Z",
        51.99,
    ),
    (
        "B2",
        [{"work_date": "2026-08-25T00:00:00Z", "hours": 0.01, "activity_class": "ADMIN"}],
        "2026-08-29T00:00:00Z",
        "2026-08-28T00:00:00Z",
        52.00,
    ),
    (
        "C1",
        [{"work_date": "2026-08-28T00:00:00Z", "hours": 7.99,
          "activity_class": "DELIVERY"}],
        "2026-09-01T00:00:00Z",
        "2026-08-31T00:00:00Z",
        59.99,
    ),
    (
        "C2",
        [{"work_date": "2026-08-31T00:00:00Z", "hours": 0.01, "activity_class": "ADMIN"}],
        "2026-09-05T00:00:00Z",
        "2026-09-04T00:00:00Z",
        60.00,
    ),
]


def _creep_ladder(stop_after="A1"):
    """Walk the approved-hours ladder from 45.99 hours upwards, one check-in per rung, and
    return the world together with the hold that closed the requested rung."""
    world = setup_held_milestone_engagement(
        deliverables=SINGLE_DELIVERABLE,
        time_logs=FORTY_FIVE_POINT_NINE_NINE,
        reported_cumulative_hours=45.99,
        title="Lease portfolio review",
    )
    held = world["milestone"]
    if stop_after == "A1":
        return world, held
    for rung, logs, due_at, hold_clock, reported in CREEP_LADDER:
        for row in logs:
            get_success_data(
                api_client.create_time_log(
                    world["engagement"]["id"],
                    time_log_payload(**row),
                    world["volunteer_headers"],
                )
            )
        milestone = get_success_data(
            api_client.create_milestone(
                world["engagement"]["id"],
                milestone_payload(due_at=due_at),
                world["pm_headers"],
            )
        )
        set_clock(hold_clock, world["pm_headers"])
        held = get_success_data(
            api_client.hold_milestone(
                milestone["id"],
                {"reported_cumulative_hours": reported},
                world["pm_headers"],
            )
        )
        if rung == stop_after:
            break
    world["milestone"] = held
    return world, held


def test_05_one_cent_of_an_hour_below_the_watch_floor_stays_unescalated(api):
    """PRD §3.7: "Subtract the baseline from that total, divide by the baseline, and round
    to four decimals."
    PRD §3.7: "The result drives `creep_escalation_level`: `NONE` below 0.1500, `WATCH`
    from 0.1500 up to but not including 0.3000, `ESCALATED` from 0.3000 up to but not
    including 0.5000, and `BREACH` at 0.5000 and above."

    Design: Difficulty/boundary_precision/creep_band_floors_inclusive_ladder
    """
    world, held = _creep_ladder("A1")

    assert held["checkin_status"] == "HELD", (
        f"Expected the check-in HELD, got {held['checkin_status']}"
    )
    assert held["variance_hours"] == pytest.approx(0.00, abs=0.01), (
        f"Expected variance_hours 0.00, got {held['variance_hours']}"
    )
    assert held["escalation_raised"] is False, (
        f"Expected escalation_raised false below the watch floor, got "
        f"{held['escalation_raised']}"
    )
    engagement = read_engagement(world)
    assert engagement["approved_hours"] == pytest.approx(45.99, abs=0.01), (
        f"Expected approved_hours 45.99, got {engagement['approved_hours']}"
    )
    assert engagement["scope_creep_pct"] == pytest.approx(0.1498, abs=1e-4), (
        f"Expected scope_creep_pct 0.1498, got {engagement['scope_creep_pct']}"
    )
    assert engagement["creep_escalation_level"] == "NONE", (
        f"Expected creep_escalation_level NONE, got "
        f"{engagement['creep_escalation_level']}"
    )


def test_06_exactly_the_watch_floor_escalates_without_raising_the_flag(api):
    """PRD §3.7: "The band floors are inclusive, so exactly 0.1500 is `WATCH`, exactly
    0.3000 is `ESCALATED` and exactly 0.5000 is `BREACH`; the ratio may legitimately be
    negative when a generous scope change has raised the baseline above the hours actually
    burned."
    PRD §3.7: "The hold moves the milestone `SCHEDULED → HELD` with `held_at` stamped, and
    then, in this order: every child time log of the engagement that is still unapproved
    and whose `work_date` is at or before the milestone's `due_at` flips `approved` to true
    with `approved_at` stamped and its `milestone_id` set to this milestone; the
    engagement's `approved_hours` is recomputed; the creep calculation reruns and may move
    `creep_escalation_level`; `variance_hours` is computed as the reported cumulative hours
    less the engagement's `approved_hours` *measured after those approvals*, which is why
    an early hold can show a negative variance; and `escalation_raised` is set to true when
    the recomputed `creep_escalation_level` is `ESCALATED` or `BREACH`."

    Design: Difficulty/boundary_precision/creep_band_floors_inclusive_ladder
    """
    world, held = _creep_ladder("A2")

    assert held["escalation_raised"] is False, (
        f"WATCH must not raise the escalation flag, got {held['escalation_raised']}"
    )
    engagement = read_engagement(world)
    assert engagement["approved_hours"] == pytest.approx(46.00, abs=0.01), (
        f"Expected approved_hours 46.00, got {engagement['approved_hours']}"
    )
    assert engagement["scope_creep_pct"] == pytest.approx(0.1500, abs=1e-4), (
        f"Expected scope_creep_pct exactly 0.1500, got {engagement['scope_creep_pct']}"
    )
    assert engagement["creep_escalation_level"] == "WATCH", (
        f"Expected creep_escalation_level WATCH on the inclusive floor, got "
        f"{engagement['creep_escalation_level']}"
    )


def test_07_one_cent_of_an_hour_below_the_escalated_floor_stays_on_watch(api):
    """PRD §3.7: "The result drives `creep_escalation_level`: `NONE` below 0.1500, `WATCH`
    from 0.1500 up to but not including 0.3000, `ESCALATED` from 0.3000 up to but not
    including 0.5000, and `BREACH` at 0.5000 and above."

    Design: Difficulty/boundary_precision/creep_band_floors_inclusive_ladder
    """
    world, held = _creep_ladder("B1")

    assert held["escalation_raised"] is False, (
        f"A ratio of 0.2998 must not raise the escalation flag, got "
        f"{held['escalation_raised']}"
    )
    engagement = read_engagement(world)
    assert engagement["approved_hours"] == pytest.approx(51.99, abs=0.01), (
        f"Expected approved_hours 51.99, got {engagement['approved_hours']}"
    )
    assert engagement["scope_creep_pct"] == pytest.approx(0.2998, abs=1e-4), (
        f"Expected scope_creep_pct 0.2998, got {engagement['scope_creep_pct']}"
    )
    assert engagement["creep_escalation_level"] == "WATCH", (
        f"Expected creep_escalation_level WATCH, got "
        f"{engagement['creep_escalation_level']}"
    )


def test_08_exactly_the_escalated_floor_raises_the_escalation_flag(api):
    """PRD §3.7: "The band floors are inclusive, so exactly 0.1500 is `WATCH`, exactly
    0.3000 is `ESCALATED` and exactly 0.5000 is `BREACH`; the ratio may legitimately be
    negative when a generous scope change has raised the baseline above the hours actually
    burned."

    Design: Difficulty/boundary_precision/creep_band_floors_inclusive_ladder
    """
    world, held = _creep_ladder("B2")

    assert held["escalation_raised"] is True, (
        f"ESCALATED must raise the escalation flag, got {held['escalation_raised']}"
    )
    engagement = read_engagement(world)
    assert engagement["approved_hours"] == pytest.approx(52.00, abs=0.01), (
        f"Expected approved_hours 52.00, got {engagement['approved_hours']}"
    )
    assert engagement["scope_creep_pct"] == pytest.approx(0.3000, abs=1e-4), (
        f"Expected scope_creep_pct exactly 0.3000, got {engagement['scope_creep_pct']}"
    )
    assert engagement["creep_escalation_level"] == "ESCALATED", (
        f"Expected creep_escalation_level ESCALATED on the inclusive floor, got "
        f"{engagement['creep_escalation_level']}"
    )
    assert engagement["work_status"] == "IN_PROGRESS", (
        f"An escalated engagement survives, got {engagement['work_status']}"
    )


def test_09_one_cent_of_an_hour_below_the_breach_floor_survives(api):
    """PRD §3.7: "The result drives `creep_escalation_level`: `NONE` below 0.1500, `WATCH`
    from 0.1500 up to but not including 0.3000, `ESCALATED` from 0.3000 up to but not
    including 0.5000, and `BREACH` at 0.5000 and above."

    Design: Difficulty/boundary_precision/creep_band_floors_inclusive_ladder
    """
    world, _held = _creep_ladder("C1")

    engagement = read_engagement(world)
    assert engagement["approved_hours"] == pytest.approx(59.99, abs=0.01), (
        f"Expected approved_hours 59.99, got {engagement['approved_hours']}"
    )
    assert engagement["scope_creep_pct"] == pytest.approx(0.4998, abs=1e-4), (
        f"Expected scope_creep_pct 0.4998, got {engagement['scope_creep_pct']}"
    )
    assert engagement["creep_escalation_level"] == "ESCALATED", (
        f"Expected creep_escalation_level ESCALATED, got "
        f"{engagement['creep_escalation_level']}"
    )
    assert engagement["work_status"] == "IN_PROGRESS", (
        f"One cent short of the breach floor the work continues, got "
        f"{engagement['work_status']}"
    )


def test_10_exactly_the_breach_floor_terminates_from_inside_a_successful_hold(api):
    """PRD §3.7: "If the recomputed level is `BREACH`, the hold does not merely flag the
    problem — the engagement is terminated with `termination_reason` `SCOPE_BREACH` and the
    parent request moves `IN_DELIVERY → RESCOPING`."

    Design: Difficulty/boundary_precision/creep_band_floors_inclusive_ladder
    """
    world, held = _creep_ladder("C2")

    assert held["checkin_status"] == "HELD", (
        f"The breaching hold itself succeeds, got {held['checkin_status']}"
    )
    assert held["escalation_raised"] is True, (
        f"BREACH must raise the escalation flag, got {held['escalation_raised']}"
    )
    engagement = read_engagement(world)
    assert engagement["approved_hours"] == pytest.approx(60.00, abs=0.01), (
        f"Expected approved_hours 60.00, got {engagement['approved_hours']}"
    )
    assert engagement["scope_creep_pct"] == pytest.approx(0.5000, abs=1e-4), (
        f"Expected scope_creep_pct exactly 0.5000, got {engagement['scope_creep_pct']}"
    )
    assert engagement["creep_escalation_level"] == "BREACH", (
        f"Expected creep_escalation_level BREACH on the inclusive floor, got "
        f"{engagement['creep_escalation_level']}"
    )
    assert engagement["work_status"] == "TERMINATED", (
        f"Expected work_status TERMINATED, got {engagement['work_status']}"
    )
    assert engagement["termination_reason"] == "SCOPE_BREACH", (
        f"Expected termination_reason SCOPE_BREACH, got "
        f"{engagement['termination_reason']}"
    )
    request = get_success_data(
        api_client.get_project_request(
            engagement["project_request_id"], world["pm_headers"]
        )
    )
    assert request["status"] == "RESCOPING", (
        f"Expected the parent request RESCOPING, got {request['status']}"
    )


def test_11_a_terminal_work_status_answers_before_the_breach_guard(api):
    """PRD §2.12: "The engagement's `work_status` is in the from-set of the requested
    transition — start requires `NOT_STARTED`, submit requires `IN_PROGRESS`, time logging
    and scope-change creation require `IN_PROGRESS`, opening a quality review requires
    `SUBMITTED`, handoff requires `ACCEPTED`, and terminate requires a non-terminal value —
    on `POST /engagements/{id}/start`, `POST /engagements/{id}/submit`,
    `POST /engagements/{id}/time-logs`, `POST /engagements/{id}/scope-change-requests`,
    `POST /engagements/{id}/quality-reviews`, `POST /engagements/{id}/handoff`,
    `POST /engagements/{id}/terminate`, `POST /engagements/{id}/satisfaction-surveys` and
    `POST /milestones/{id}/hold`, otherwise `ERR_INVALID_WORK_STATE` (409)."

    Design: Difficulty/boundary_precision/creep_band_floors_inclusive_ladder
    """
    world, _held = _creep_ladder("C2")

    response = api_client.create_time_log(
        world["engagement"]["id"],
        time_log_payload(work_date="2026-09-04T00:00:00Z", hours=1.00),
        world["volunteer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INVALID_WORK_STATE)
    body = response.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_SCOPE_BREACH_THRESHOLD.value, (
        "The terminal work state is checked before the breached creep level"
    )


def test_12_pending_change_hours_raise_creep_and_bar_further_logging(api):
    """PRD §3.7: "A `MANAGER_REVIEW` change is stored in `PENDING` with a null
    `decided_by_user_id` and a null `decided_at`, and its pending hours immediately raise
    the engagement's `scope_creep_pct` even though no work has been done against them."
    PRD §2.12: "The engagement's `creep_escalation_level` is not `BREACH` and no child
    scope change request sits in `PENDING` or `ESCALATED` — on
    `POST /engagements/{id}/time-logs` and `POST /engagements/{id}/submit` — otherwise
    `ERR_SCOPE_BREACH_THRESHOLD` (409)."

    Design: Difficulty/boundary_precision/creep_band_floors_inclusive_ladder
    """
    world, _held = _creep_ladder("A2")

    change = validate_success(
        api_client.create_scope_change_request(
            world["engagement"]["id"],
            scope_change_request_payload(
                additional_hours=10.00,
                additional_deliverable_count=0,
                justification="Two extra leases surfaced in diligence",
            ),
            world["partner_headers"],
        ),
        201,
    )
    assert change["projected_creep_pct"] == pytest.approx(0.4000, abs=1e-4), (
        f"Expected projected_creep_pct 0.4000, got {change['projected_creep_pct']}"
    )
    assert change["decision_tier"] == "MANAGER_REVIEW", (
        f"Expected decision_tier MANAGER_REVIEW, got {change['decision_tier']}"
    )
    assert change["status"] == "PENDING", (
        f"Expected the change stored PENDING, got {change['status']}"
    )

    engagement = read_engagement(world)
    assert engagement["scope_creep_pct"] == pytest.approx(0.4000, abs=1e-4), (
        f"Expected the pending hours to lift scope_creep_pct to 0.4000, got "
        f"{engagement['scope_creep_pct']}"
    )
    assert engagement["creep_escalation_level"] == "ESCALATED", (
        f"Expected creep_escalation_level ESCALATED, got "
        f"{engagement['creep_escalation_level']}"
    )

    refused = api_client.create_time_log(
        world["engagement"]["id"],
        time_log_payload(work_date="2026-08-22T00:00:00Z", hours=1.00),
        world["volunteer_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_SCOPE_BREACH_THRESHOLD)


# ===========================================================================
# Cycle posture on an integer slot lattice
# ===========================================================================
def _cycle_at_capacity(live_engagements):
    """A five-slot cycle carrying `live_engagements` slot-holding engagements. The first is
    driven all the way to `ACCEPTED` so it can be handed off; the rest stop at
    `NOT_STARTED`, which still occupies a committed slot."""
    world = setup_world(
        "accepted",
        cycle_slots=5,
        deliverables=SINGLE_DELIVERABLE,
        time_logs=TWELVE_DELIVERY_HOURS,
        reported_cumulative_hours=12.00,
        title="Founding clinic",
    )
    headers_by_volunteer = {world["volunteer"]["id"]: world["volunteer_headers"]}
    for _ in range(3):
        extra_volunteer, _skill, _window = create_vetted_volunteer()
        headers_by_volunteer[extra_volunteer["id"]] = make_volunteer_headers(
            extra_volunteer["id"]
        )
    world["engagements"] = [world["engagement"]]
    for index in range(live_engagements - 1):
        extra = add_scoped_request(
            world,
            title=f"Parallel clinic {index + 1}",
            deliverables=SINGLE_DELIVERABLE,
        )
        offer = get_success_data(
            api_client.match_project_request(
                extra["request"]["id"], world["spec_headers"]
            )
        )
        world["engagements"].append(
            get_success_data(
                api_client.accept_match_offer(
                    offer["id"], headers_by_volunteer[offer["volunteer_id"]]
                )
            )
        )
    return world


def test_13_utilization_below_the_restricted_floor_leaves_the_cycle_open(api):
    """PRD §3.1: "The cycle then maintains five derived figures continuously:
    `slots_committed`, `slots_reserved` and `slots_available` as defined in §2.8, a
    `utilization_ratio` equal to the sum of committed and reserved slots divided by
    `capacity_slot_total` and rounded to four decimals, and a `posture` that gates every
    child operation."
    PRD §3.1: "The posture calculation reruns whenever a match offer is created, whenever
    an offer leaves `OFFERED`, whenever an engagement enters or leaves the four live
    `work_status` values, and on every operations checkpoint."

    Design: Difficulty/boundary_precision/cycle_posture_floors_on_integer_slot_lattice
    """
    world = _cycle_at_capacity(3)

    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 3, (
        f"Expected slots_committed 3, got {cycle['slots_committed']}"
    )
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved 0, got {cycle['slots_reserved']}"
    )
    assert cycle["slots_available"] == 2, (
        f"Expected slots_available 2, got {cycle['slots_available']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.6000, abs=1e-4), (
        f"Expected utilization_ratio 0.6000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN, got {cycle['posture']}"
    )

    probe = add_scoped_request(
        world,
        title="Routine bylaw check",
        urgency="ROUTINE",
        deliverables=SINGLE_DELIVERABLE,
    )
    validate_success(
        api_client.match_project_request(probe["request"]["id"], world["spec_headers"]),
        201,
    )

    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 1, (
        f"Expected the new offer to reserve one slot, got {cycle['slots_reserved']}"
    )
    assert cycle["slots_available"] == 1, (
        f"Expected slots_available 1, got {cycle['slots_available']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.8000, abs=1e-4), (
        f"Expected utilization_ratio 0.8000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "RESTRICTED", (
        f"A legal routine match is what pushes the cycle onto the floor, got "
        f"{cycle['posture']}"
    )


def test_14_exactly_the_restricted_floor_refuses_a_routine_request(api):
    """PRD §3.1: "`posture` is `OPEN` while utilization is below 0.8000, `RESTRICTED` from
    0.8000 up to but not including 1.0000, and `FROZEN` at 1.0000 and above; both band
    floors are inclusive, so a utilization of exactly 0.8000 is `RESTRICTED` and exactly
    1.0000 is `FROZEN`."
    PRD §2.12: "When the cycle's `posture` is `RESTRICTED`, the request's `urgency` is
    `ELEVATED` or `CRITICAL` — on `POST /project-requests/{id}/match` — otherwise
    `ERR_CYCLE_RESTRICTED_URGENCY` (409)."

    Design: Difficulty/boundary_precision/cycle_posture_floors_on_integer_slot_lattice
    """
    world = _cycle_at_capacity(4)

    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 4, (
        f"Expected slots_committed 4, got {cycle['slots_committed']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.8000, abs=1e-4), (
        f"Expected utilization_ratio exactly 0.8000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "RESTRICTED", (
        f"Expected posture RESTRICTED on the inclusive floor, got {cycle['posture']}"
    )
    assert cycle["slots_available"] == 1, (
        f"A restricted cycle still shows headroom, got {cycle['slots_available']}"
    )

    probe = add_scoped_request(
        world,
        title="Routine bylaw check",
        urgency="ROUTINE",
        deliverables=SINGLE_DELIVERABLE,
    )
    response = api_client.match_project_request(
        probe["request"]["id"], world["spec_headers"]
    )

    validate_error(response, ApiErrorId.ERR_CYCLE_RESTRICTED_URGENCY)
    refused = get_success_data(
        api_client.get_project_request(probe["request"]["id"], world["pm_headers"])
    )
    assert refused["status"] == "SCOPED", (
        f"A refused match leaves the request SCOPED, got {refused['status']}"
    )


def test_15_an_elevated_request_still_matches_under_a_restricted_posture(api):
    """PRD §3.1: "`RESTRICTED` narrows the gate rather than shutting it: only requests of
    `ELEVATED` or `CRITICAL` urgency may take a slot, while a `ROUTINE` request attempting
    to match is refused with `ERR_CYCLE_RESTRICTED_URGENCY`."

    Design: Difficulty/boundary_precision/cycle_posture_floors_on_integer_slot_lattice
    """
    world = _cycle_at_capacity(4)
    assert read_cycle(world)["posture"] == "RESTRICTED", (
        "Setup expected a cycle sitting exactly on the restricted floor"
    )

    probe = add_scoped_request(
        world,
        title="Elevated diligence",
        urgency="ELEVATED",
        deliverables=SINGLE_DELIVERABLE,
    )
    offer = validate_success(
        api_client.match_project_request(probe["request"]["id"], world["spec_headers"]),
        201,
    )

    assert offer["volunteer_id"], (
        f"An elevated match must still name a winning volunteer, got {offer}"
    )
    assert offer["round_no"] == 1, (
        f"Expected the first offer on the request to be round 1, got {offer['round_no']}"
    )


def test_16_full_utilization_freezes_the_cycle_and_a_handoff_thaws_it(api):
    """PRD §2.12: "The cycle's `posture` is not `FROZEN` — on
    `POST /project-requests/{id}/match` and `POST /match-offers/{id}/accept` — otherwise
    `ERR_CYCLE_CAPACITY_FROZEN` (409)."
    PRD §3.1: "`posture` is `OPEN` while utilization is below 0.8000, `RESTRICTED` from
    0.8000 up to but not including 1.0000, and `FROZEN` at 1.0000 and above; both band
    floors are inclusive, so a utilization of exactly 0.8000 is `RESTRICTED` and exactly
    1.0000 is `FROZEN`."

    Design: Difficulty/boundary_precision/cycle_posture_floors_on_integer_slot_lattice
    """
    world = _cycle_at_capacity(4)
    parked = add_scoped_request(
        world,
        title="Elevated diligence",
        urgency="ELEVATED",
        deliverables=SINGLE_DELIVERABLE,
    )
    get_success_data(
        api_client.match_project_request(parked["request"]["id"], world["spec_headers"])
    )

    cycle = read_cycle(world)
    assert cycle["utilization_ratio"] == pytest.approx(1.0000, abs=1e-4), (
        f"Expected utilization_ratio exactly 1.0000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "FROZEN", (
        f"Expected posture FROZEN on the inclusive floor, got {cycle['posture']}"
    )
    assert cycle["slots_available"] == 0, (
        f"Expected slots_available 0, got {cycle['slots_available']}"
    )

    critical = add_scoped_request(
        world,
        title="Critical injunction support",
        urgency="CRITICAL",
        deliverables=SINGLE_DELIVERABLE,
    )
    frozen_response = api_client.match_project_request(
        critical["request"]["id"], world["spec_headers"]
    )
    validate_error(frozen_response, ApiErrorId.ERR_CYCLE_CAPACITY_FROZEN)
    body = frozen_response.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_CYCLE_RESTRICTED_URGENCY.value, (
        "A frozen cycle offers no urgency escape hatch"
    )

    validate_success(
        api_client.handoff_engagement(
            world["engagement"]["id"], handoff_payload(), world["pm_headers"]
        )
    )
    get_success_data(
        api_client.recalculate_program_cycle(world["cycle"]["id"], world["pm_headers"])
    )

    cycle = read_cycle(world)
    assert cycle["utilization_ratio"] == pytest.approx(0.8000, abs=1e-4), (
        f"A released slot drops utilization to 0.8000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "RESTRICTED", (
        f"Expected the thawed posture RESTRICTED, got {cycle['posture']}"
    )
    validate_success(
        api_client.match_project_request(
            critical["request"]["id"], world["spec_headers"]
        ),
        201,
    )


# ===========================================================================
# Quality gate thresholds and the pinned rounding order
# ===========================================================================
def _weighted_deliverables(*specs):
    """Turn (weight_pct, hours_estimate) pairs into a deliverable set in pinned order."""
    return [
        {
            "title": f"Deliverable {index + 1}",
            "sequence_no": index + 1,
            "weight_pct": weight,
            "hours_estimate": hours,
            "acceptance_criteria": "Signed off by the partner",
        }
        for index, (weight, hours) in enumerate(specs)
    ]


def _scored_review(specs, scores, title):
    """A submitted engagement whose deliverable set carries `specs`, reviewed once with
    `scores` in pinned order. Returns the world and the SCORED review."""
    world = setup_submitted_engagement(
        deliverables=_weighted_deliverables(*specs),
        time_logs=TWELVE_DELIVERY_HOURS,
        reported_cumulative_hours=12.00,
        title=title,
    )
    review = drive_review_to_outcome(
        world,
        {
            deliverable["id"]: score
            for deliverable, score in zip(world["deliverables"], scores)
        },
    )
    return world, review


def test_17_a_weighted_score_of_exactly_seventy_eight_passes(api):
    """PRD §3.8: "The `outcome` follows from the score: `PASS` at 78.00 and above,
    `CONDITIONAL` from 60.00 up to but not including 78.00, and `FAIL` below 60.00."
    PRD §3.8: "Scoring also recomputes `scored_deliverable_count`, the number of
    non-`WAIVED` deliverables on the pinned revision now carrying a non-null
    `review_score`, and moves the review `OPEN → SCORED`."

    Design: Difficulty/boundary_precision/quality_gate_thresholds_78_and_60_with_pinned_rounding
    """
    world, review = _scored_review(
        [(90.00, 36.00), (10.00, 4.00)], (4, 3), "Charter overhaul"
    )

    assert review["weighted_score"] == pytest.approx(78.00, abs=0.01), (
        f"Expected weighted_score exactly 78.00, got {review['weighted_score']}"
    )
    assert review["outcome"] == "PASS", (
        f"Expected outcome PASS on the inclusive floor, got {review['outcome']}"
    )
    assert review["status"] == "SCORED", (
        f"Expected the review SCORED, got {review['status']}"
    )
    assert review["scored_deliverable_count"] == 2, (
        f"Expected scored_deliverable_count 2, got {review['scored_deliverable_count']}"
    )

    validate_success(
        api_client.decide_quality_review(
            review["id"], world["reviewer_headers"], {"request_rework": False}
        )
    )
    engagement = read_engagement(world)
    assert engagement["quality_gate"] == "PASSED", (
        f"Expected quality_gate PASSED, got {engagement['quality_gate']}"
    )
    assert engagement["work_status"] == "ACCEPTED", (
        f"Expected work_status ACCEPTED, got {engagement['work_status']}"
    )


def test_18_one_cent_below_the_pass_floor_falls_to_conditional(api):
    """PRD §3.8: "A decision on a `PASS` or `CONDITIONAL` outcome without rework moves the
    review `SCORED → DECIDED` with `decided_at` stamped, sets the engagement's
    `quality_gate` to `PASSED` when the outcome was `PASS` and to `CONDITIONAL` when it was
    `CONDITIONAL`, moves the engagement `SUBMITTED → ACCEPTED`, and settles each
    deliverable: every non-`WAIVED` deliverable whose `review_score` is 3 or higher moves
    to `review_status` `ACCEPTED`, and every remaining one moves to `REJECTED`."

    Design: Difficulty/boundary_precision/quality_gate_thresholds_78_and_60_with_pinned_rounding
    """
    world, review = _scored_review(
        [(89.95, 36.00), (10.05, 4.00)], (4, 3), "Charter overhaul"
    )

    assert review["weighted_score"] == pytest.approx(77.99, abs=0.01), (
        f"Expected weighted_score 77.99, got {review['weighted_score']}"
    )
    assert review["outcome"] == "CONDITIONAL", (
        f"One cent short of 78.00 is CONDITIONAL, got {review['outcome']}"
    )

    validate_success(
        api_client.decide_quality_review(
            review["id"], world["reviewer_headers"], {"request_rework": False}
        )
    )
    engagement = read_engagement(world)
    assert engagement["quality_gate"] == "CONDITIONAL", (
        f"Expected quality_gate CONDITIONAL, got {engagement['quality_gate']}"
    )
    assert engagement["work_status"] == "ACCEPTED", (
        f"Expected work_status ACCEPTED, got {engagement['work_status']}"
    )


def test_19_one_cent_above_the_pass_floor_still_passes(api):
    """PRD §3.8: "The `outcome` follows from the score: `PASS` at 78.00 and above,
    `CONDITIONAL` from 60.00 up to but not including 78.00, and `FAIL` below 60.00."

    Design: Difficulty/boundary_precision/quality_gate_thresholds_78_and_60_with_pinned_rounding
    """
    _world, review = _scored_review(
        [(90.05, 36.00), (9.95, 4.00)], (4, 3), "Charter overhaul"
    )

    assert review["weighted_score"] == pytest.approx(78.01, abs=0.01), (
        f"Expected weighted_score 78.01, got {review['weighted_score']}"
    )
    assert review["outcome"] == "PASS", (
        f"Expected outcome PASS, got {review['outcome']}"
    )


def test_20_a_weighted_score_of_exactly_sixty_is_conditional_not_failed(api):
    """PRD §3.8: "For each deliverable in the pinned order, divide its `weight_pct` by that
    active total and round to six decimals, then multiply that normalised weight by the
    deliverable's `review_score` and by a scale factor of 20, rounding each deliverable's
    contribution to two decimals *before* summing."

    Design: Difficulty/boundary_precision/quality_gate_thresholds_78_and_60_with_pinned_rounding
    """
    _world, review = _scored_review(
        [(50.00, 20.00), (50.00, 20.00)], (3, 3), "Volunteer handbook"
    )

    assert review["weighted_score"] == pytest.approx(60.00, abs=0.01), (
        f"Expected weighted_score exactly 60.00, got {review['weighted_score']}"
    )
    assert review["outcome"] == "CONDITIONAL", (
        f"Expected outcome CONDITIONAL on the inclusive floor, got {review['outcome']}"
    )


def test_21_one_cent_below_the_conditional_floor_fails_and_ends_the_work(api):
    """PRD §3.8: "A decision on a `FAIL` outcome ends the engagement, and it does so
    through a four-step cascade whose steps each follow from the previous one."
    PRD §3.8: "The `outcome` follows from the score: `PASS` at 78.00 and above,
    `CONDITIONAL` from 60.00 up to but not including 78.00, and `FAIL` below 60.00."

    Design: Difficulty/boundary_precision/quality_gate_thresholds_78_and_60_with_pinned_rounding
    """
    world, review = _scored_review(
        [(99.95, 39.00), (0.05, 1.00)], (3, 2), "Trust deed rewrite"
    )

    assert review["weighted_score"] == pytest.approx(59.99, abs=0.01), (
        f"Expected weighted_score 59.99, got {review['weighted_score']}"
    )
    assert review["outcome"] == "FAIL", (
        f"One cent short of 60.00 is FAIL, got {review['outcome']}"
    )

    validate_success(
        api_client.decide_quality_review(
            review["id"], world["reviewer_headers"], {"request_rework": False}
        )
    )
    engagement = read_engagement(world)
    assert engagement["quality_gate"] == "FAILED", (
        f"Expected quality_gate FAILED, got {engagement['quality_gate']}"
    )
    assert engagement["work_status"] == "TERMINATED", (
        f"Expected work_status TERMINATED, got {engagement['work_status']}"
    )
    assert engagement["termination_reason"] == "QUALITY_FAILURE", (
        f"Expected termination_reason QUALITY_FAILURE, got "
        f"{engagement['termination_reason']}"
    )


def test_22_one_cent_above_the_conditional_floor_is_conditional(api):
    """PRD §3.8: "The `outcome` follows from the score: `PASS` at 78.00 and above,
    `CONDITIONAL` from 60.00 up to but not including 78.00, and `FAIL` below 60.00."

    Design: Difficulty/boundary_precision/quality_gate_thresholds_78_and_60_with_pinned_rounding
    """
    _world, review = _scored_review(
        [(99.95, 39.00), (0.05, 1.00)], (3, 4), "Trust deed rewrite"
    )

    assert review["weighted_score"] == pytest.approx(60.01, abs=0.01), (
        f"Expected weighted_score 60.01, got {review['weighted_score']}"
    )
    assert review["outcome"] == "CONDITIONAL", (
        f"Expected outcome CONDITIONAL, got {review['outcome']}"
    )


def test_23_contributions_are_rounded_per_deliverable_before_they_are_summed(api):
    """PRD §3.8: "The review's `weighted_score` is the sum of those per-deliverable
    contributions, rounded to two decimals; summing normalised weights first and rounding
    once at the end is not equivalent and is not permitted."

    Design: Difficulty/boundary_precision/quality_gate_thresholds_78_and_60_with_pinned_rounding
    """
    _world, review = _scored_review(
        [(16.62, 10.00), (60.17, 20.00), (23.21, 10.00)],
        (2, 4, 5),
        "Merger diligence pack",
    )

    assert review["weighted_score"] == pytest.approx(78.00, abs=0.01), (
        f"Rounding each contribution before summing gives 78.00, got "
        f"{review['weighted_score']}"
    )
    assert review["weighted_score"] != pytest.approx(77.99, abs=0.001), (
        "77.99 is the value produced by summing unrounded contributions"
    )
    assert review["outcome"] == "PASS", (
        f"Expected outcome PASS, got {review['outcome']}"
    )


# ===========================================================================
# The admin overhead minimum charge, clamped at 45.00
# ===========================================================================
def _valuation(logs, method="MARKET_RATE", title="Valuation boundary"):
    """A live engagement whose only approved hours are `logs`, then one posted valuation."""
    world = setup_held_milestone_engagement(
        deliverables=SINGLE_DELIVERABLE,
        time_logs=logs,
        reported_cumulative_hours=round(sum(row["hours"] for row in logs), 2),
        title=title,
    )
    response = api_client.create_valuation(
        world["engagement"]["id"],
        valuation_payload(current_engagement_version(world), method=method),
        world["pm_headers"],
    )
    return world, response


def test_24_a_base_below_the_overhead_floor_is_lifted_to_the_minimum_charge(api):
    """PRD §3.9: "Third, `admin_overhead_usd` is the greater of a 45.00-dollar floor and
    the base multiplied by that tier rate rounded to two decimals — so even a base of 0.00
    still carries 45.00 of overhead."
    PRD §3.9: "Fourth, `total_amount_usd` is the base plus the overhead, rounded to two
    decimals."

    Design: Difficulty/boundary_precision/admin_overhead_minimum_charge_clamp_at_45
    """
    world, response = _valuation(
        [
            {"work_date": "2026-08-12T00:00:00Z", "hours": 2.49,
             "activity_class": "DELIVERY"},
            {"work_date": "2026-08-12T00:00:00Z", "hours": 0.01,
             "activity_class": "ADMIN"},
        ]
    )

    record = validate_success(response, 201)
    assert record["hours_included"] == pytest.approx(2.50, abs=0.01), (
        f"Expected hours_included 2.50, got {record['hours_included']}"
    )
    assert record["rate_applied_usd"] == pytest.approx(150.00, abs=0.01), (
        f"Expected rate_applied_usd 150.00, got {record['rate_applied_usd']}"
    )
    assert record["base_amount_usd"] == pytest.approx(374.25, abs=0.01), (
        f"Expected base_amount_usd 374.25, got {record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(45.00, abs=0.01), (
        f"The 44.91 tier charge must be lifted to the 45.00 floor, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(419.25, abs=0.01), (
        f"Expected total_amount_usd 419.25, got {record['total_amount_usd']}"
    )
    assert read_engagement(world)["valuation_status"] == "PROVISIONAL", (
        f"Expected valuation_status PROVISIONAL, got "
        f"{read_engagement(world)['valuation_status']}"
    )


def test_25_a_base_exactly_on_the_overhead_floor_returns_the_tie(api):
    """PRD §3.9: "For each admitted log it multiplies the log's `hours` by the lesser of
    that log's `rate_basis_usd` and the seniority ceiling, then by a class factor of 1.00
    for `DELIVERY` and 0.50 for `ADMIN` — travel's factor is 0.00, which is why excluding
    it changes nothing about the money but does change the hours — and rounds that line to
    two decimals."

    Design: Difficulty/boundary_precision/admin_overhead_minimum_charge_clamp_at_45
    """
    _world, response = _valuation(
        [
            {"work_date": "2026-08-12T00:00:00Z", "hours": 2.50,
             "activity_class": "DELIVERY"},
        ]
    )

    record = validate_success(response, 201)
    assert record["hours_included"] == pytest.approx(2.50, abs=0.01), (
        f"Expected hours_included 2.50, got {record['hours_included']}"
    )
    assert record["base_amount_usd"] == pytest.approx(375.00, abs=0.01), (
        f"Expected base_amount_usd 375.00, got {record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(45.00, abs=0.01), (
        f"Expected admin_overhead_usd 45.00 exactly on the floor, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(420.00, abs=0.01), (
        f"Expected total_amount_usd 420.00, got {record['total_amount_usd']}"
    )


def test_26_one_cent_of_admin_time_above_the_floor_leaves_the_clamp_inert(api):
    """PRD §3.9: "`hours_included` is the sum of `hours` over the admitted logs, rounded to
    two decimals, and `rate_applied_usd` is the lesser of the volunteer's
    `professional_rate_usd_per_hour` and the seniority ceiling."

    Design: Difficulty/boundary_precision/admin_overhead_minimum_charge_clamp_at_45
    """
    _world, response = _valuation(
        [
            {"work_date": "2026-08-12T00:00:00Z", "hours": 2.50,
             "activity_class": "DELIVERY"},
            {"work_date": "2026-08-12T00:00:00Z", "hours": 0.01,
             "activity_class": "ADMIN"},
        ]
    )

    record = validate_success(response, 201)
    assert record["hours_included"] == pytest.approx(2.51, abs=0.01), (
        f"Expected hours_included 2.51, got {record['hours_included']}"
    )
    assert record["base_amount_usd"] == pytest.approx(375.75, abs=0.01), (
        f"Expected base_amount_usd 375.75, got {record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(45.09, abs=0.01), (
        f"Above the floor the tier charge stands unclamped at 45.09, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(420.84, abs=0.01), (
        f"Expected total_amount_usd 420.84, got {record['total_amount_usd']}"
    )


def test_27_a_travel_only_engagement_is_valued_entirely_as_overhead(api):
    """PRD §3.9: "It admits only logs whose `activity_class` is `DELIVERY` or `ADMIN`,
    dropping every `TRAVEL` log from both the hours and the money."
    PRD §3.9: "Third, `admin_overhead_usd` is the greater of a 45.00-dollar floor and the
    base multiplied by that tier rate rounded to two decimals — so even a base of 0.00
    still carries 45.00 of overhead."

    Design: Difficulty/boundary_precision/admin_overhead_minimum_charge_clamp_at_45
    """
    _world, response = _valuation(
        [
            {"work_date": "2026-08-12T00:00:00Z", "hours": 3.00,
             "activity_class": "TRAVEL"},
        ]
    )

    record = validate_success(response, 201)
    assert record["hours_included"] == pytest.approx(0.00, abs=0.01), (
        f"Travel hours are dropped from the market-rate figure, got "
        f"{record['hours_included']}"
    )
    assert record["base_amount_usd"] == pytest.approx(0.00, abs=0.01), (
        f"Expected base_amount_usd 0.00, got {record['base_amount_usd']}"
    )
    assert record["rate_applied_usd"] == pytest.approx(150.00, abs=0.01), (
        f"Expected rate_applied_usd 150.00, got {record['rate_applied_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(45.00, abs=0.01), (
        f"Expected admin_overhead_usd 45.00, got {record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(45.00, abs=0.01), (
        f"Expected total_amount_usd 45.00, got {record['total_amount_usd']}"
    )


def test_28_the_national_rate_admits_travel_and_still_takes_the_floor(api):
    """PRD §3.9: "It admits every approved log regardless of class — `DELIVERY`, `ADMIN`
    and `TRAVEL` alike — sets `hours_included` to the sum of their `hours` rounded to two
    decimals, sets `rate_applied_usd` to the flat national rate of 34.79 dollars an hour,
    and sets `base_amount_usd` to those hours multiplied by that rate, rounded once at the
    end."

    Design: Difficulty/boundary_precision/admin_overhead_minimum_charge_clamp_at_45
    """
    _world, response = _valuation(
        [
            {"work_date": "2026-08-12T00:00:00Z", "hours": 3.00,
             "activity_class": "TRAVEL"},
        ],
        method="INDEPENDENT_SECTOR",
    )

    record = validate_success(response, 201)
    assert record["hours_included"] == pytest.approx(3.00, abs=0.01), (
        f"Expected hours_included 3.00, got {record['hours_included']}"
    )
    assert record["rate_applied_usd"] == pytest.approx(34.79, abs=0.01), (
        f"Expected rate_applied_usd 34.79, got {record['rate_applied_usd']}"
    )
    assert record["base_amount_usd"] == pytest.approx(104.37, abs=0.01), (
        f"Expected base_amount_usd 104.37, got {record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(45.00, abs=0.01), (
        f"The 12.52 tier charge must be lifted to the 45.00 floor, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(149.37, abs=0.01), (
        f"Expected total_amount_usd 149.37, got {record['total_amount_usd']}"
    )


def test_29_a_base_one_notch_below_the_tier_floor_takes_the_higher_rate(api):
    """PRD §3.9: "Second, the overhead tier is selected from `base_amount_usd` and never
    from the total: a base below 2500.00 takes a rate of 0.12, a base from 2500.00 up to
    but not including 10000.00 takes 0.09, and a base of 10000.00 or more takes 0.06."

    Design: Difficulty/boundary_precision/admin_overhead_minimum_charge_clamp_at_45
    """
    _world, response = _valuation(
        [
            {"work_date": "2026-08-12T00:00:00Z", "hours": 12.00,
             "activity_class": "DELIVERY"},
            {"work_date": "2026-08-13T00:00:00Z", "hours": 4.66,
             "activity_class": "DELIVERY"},
            {"work_date": "2026-08-13T00:00:00Z", "hours": 0.01,
             "activity_class": "ADMIN"},
        ]
    )

    record = validate_success(response, 201)
    assert record["base_amount_usd"] == pytest.approx(2499.75, abs=0.01), (
        f"Expected base_amount_usd 2499.75, got {record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(299.97, abs=0.01), (
        f"A base below 2500.00 takes the 0.12 rate, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(2799.72, abs=0.01), (
        f"Expected total_amount_usd 2799.72, got {record['total_amount_usd']}"
    )


def test_30_a_base_one_notch_above_the_tier_floor_takes_the_lower_rate(api):
    """PRD §3.9: "Second, the overhead tier is selected from `base_amount_usd` and never
    from the total: a base below 2500.00 takes a rate of 0.12, a base from 2500.00 up to
    but not including 10000.00 takes 0.09, and a base of 10000.00 or more takes 0.06."

    Design: Difficulty/boundary_precision/admin_overhead_minimum_charge_clamp_at_45
    """
    _world, response = _valuation(
        [
            {"work_date": "2026-08-12T00:00:00Z", "hours": 12.00,
             "activity_class": "DELIVERY"},
            {"work_date": "2026-08-13T00:00:00Z", "hours": 4.67,
             "activity_class": "DELIVERY"},
        ]
    )

    record = validate_success(response, 201)
    assert record["base_amount_usd"] == pytest.approx(2500.50, abs=0.01), (
        f"Expected base_amount_usd 2500.50, got {record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(225.05, abs=0.01), (
        f"A base at or above 2500.00 takes the 0.09 rate, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(2725.55, abs=0.01), (
        f"Expected total_amount_usd 2725.55, got {record['total_amount_usd']}"
    )


def test_31_a_total_inside_the_lower_band_still_takes_the_tier_of_its_base(api):
    """PRD §3.9: "A base of 2380.00 therefore takes the 0.12 rate, yielding 285.60 of
    overhead and a total of 2665.60, even though the resulting total sits inside the 0.09
    band."

    Design: Difficulty/boundary_precision/admin_overhead_minimum_charge_clamp_at_45
    """
    _world, response = _valuation(
        [
            {"work_date": "2026-08-12T00:00:00Z", "hours": 12.00,
             "activity_class": "DELIVERY"},
            {"work_date": "2026-08-13T00:00:00Z", "hours": 3.87,
             "activity_class": "DELIVERY"},
        ]
    )

    record = validate_success(response, 201)
    assert record["base_amount_usd"] == pytest.approx(2380.50, abs=0.01), (
        f"Expected base_amount_usd 2380.50, got {record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(285.66, abs=0.01), (
        f"Expected admin_overhead_usd 285.66 from the 0.12 tier, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(2666.16, abs=0.01), (
        f"Expected total_amount_usd 2666.16 even though it lands in the 0.09 band, got "
        f"{record['total_amount_usd']}"
    )
