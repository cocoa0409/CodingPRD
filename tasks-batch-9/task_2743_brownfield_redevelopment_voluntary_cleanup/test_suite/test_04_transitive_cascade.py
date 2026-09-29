"""
Cascades that run several aggregates deep inside one request.

Two of them start from opposite ends of the file. A single exceeding laboratory result
impairs the control it verifies, restricts the parcel, revokes the closure letter a
lender has relied on and rescinds every grant. A single lapsed defence-critical duty
forfeits the purchaser defence, freezes the parcel and does the same to the letter and
the money — but for the reason that can never be cured.
"""

from test_helpers import (
    REVIEWER_GAMMA,
    accept_letter,
    add_event,
    add_letter,
    assert_fields,
    assert_funding_conservation,
    assert_number,
    assert_sweep_counters,
    file_result,
    impose_obligation,
    issue_letter,
    request_completion,
    run_sweep,
    schedule_attainment_events,
    set_clock,
    stage_approved,
    stage_bind,
    stage_control_operating,
    stage_quote,
    stage_two_awards_granted,
)

FUNDING_NEED_CENTS = 118043177
GRANT_ALLOCATION_CENTS = 23842210
TAX_CREDIT_ALLOCATION_CENTS = 22636409

RESTRICTED_RESULTS = (240.0, 250.0, 245.0, 200.0)
UNRESTRICTED_RESULTS = (160.0, 166.67, 150.0, 100.0)

LAPSING_DUTIES = (
    ("REASONABLE_STEPS", "Maintain fencing, signage and stormwater controls.", "2027-06-30"),
    (
        "LAND_USE_RESTRICTION_COMPLIANCE",
        "Comply with the recorded environmental covenant.",
        "2027-06-30",
    ),
    (
        "INSTITUTIONAL_CONTROL_MAINTENANCE",
        "Inspect and maintain the sub-slab depressurisation system.",
        "2027-02-05",
    ),
    ("ACCESS_AND_COOPERATION", "Provide agency access on 48 hours notice.", "2027-02-05"),
    ("NOTIFICATION", "Report newly discovered releases within 10 days.", "2027-02-05"),
)


def _attain_both_goals(world, clock="2027-06-01T00:00:00Z"):
    """Four compliant results on each goal, the restricted one landing on its target."""
    restricted_events = schedule_attainment_events(world, world.goal_restricted, prefix="G1-")
    unrestricted_events = schedule_attainment_events(
        world, world.goal_unrestricted, prefix="G2-"
    )
    set_clock(world.api, clock)
    for event, value in zip(restricted_events, RESTRICTED_RESULTS):
        file_result(world, event, value)
    for event, value in zip(unrestricted_events, UNRESTRICTED_RESULTS):
        file_result(world, event, value)


def _staged_cascade(api):
    """
    The deepest reachable state: closed enrollment, relied-on letter, two awards.

    The cap is bound, so the parcel's funding need carries the premium and the waterfall
    has the pinned figure to allocate against.
    """
    world = stage_approved(api)
    stage_quote(world)
    stage_bind(world)
    stage_control_operating(world)
    _attain_both_goals(world)
    world.enrollment = request_completion(world)
    world.letter = add_letter(world)
    world.letter = issue_letter(world, headers=REVIEWER_GAMMA)
    world.letter = accept_letter(world, lender_reference="LN-2743-77")
    stage_two_awards_granted(world)
    return world


def _trigger_exceedance(world):
    """File one result far above the credited goal against the operating control."""
    set_clock(world.api, "2027-08-06T00:00:00Z")
    event = add_event(
        world,
        cleanup_goal_id=world.goal_restricted["id"],
        site_control_id=world.control["id"],
        monitoring_period_code="2027-M08",
        sample_date="2027-08-05",
        window_start="2027-08-01T00:00:00Z",
        window_end="2027-08-15T00:00:00Z",
    )
    return file_result(world, event, 900.0)


# ─── monitoring_exceedance_impairs_control_revokes_letter_rescinds_awards ───────


def test_the_exceedance_replays_the_goal_and_impairs_the_named_control(api):
    """
    Level two: the streak is rebuilt from scratch and the control leaves service.

    "At the second, the goal's streak and attainment are replayed as above, and the named
    control moves `OPERATING → IMPAIRED`, setting `impaired_since` and incrementing its
    `impairment_count` by 1."

    Design: Difficulty/transitive_cascade/monitoring_exceedance_impairs_control_revokes_letter_rescinds_awards
    """
    world = _staged_cascade(api)

    reported = _trigger_exceedance(world)
    assert_fields(reported, status="REPORTED", result_status="EXCEEDANCE")
    assert_number(reported["result_value_ugl"], 900.0, "result_value_ugl")

    assert_fields(
        world.read_goal(world.goal_restricted),
        compliant_streak=0,
        attainment_status="NOT_ATTAINED",
    )
    assert_fields(
        world.read_goal(world.goal_unrestricted),
        compliant_streak=4,
        attainment_status="ATTAINED",
    )
    assert_fields(
        world.read_control(),
        status="IMPAIRED",
        impaired_since="2027-08-06",
        impairment_count=1,
    )


def test_the_impairment_restricts_the_parcel(api):
    """
    Level three: the derived posture follows the impaired count up.

    "At the third, the parcel's `impaired_control_count` increments and its
    `cleanup_posture` becomes `RESTRICTED` unless it is already `FROZEN`."

    Design: Difficulty/transitive_cascade/monitoring_exceedance_impairs_control_revokes_letter_rescinds_awards
    """
    world = _staged_cascade(api)
    assert_fields(world.read_site(), impaired_control_count=0, cleanup_posture="OPEN")

    _trigger_exceedance(world)

    assert_fields(world.read_site(), impaired_control_count=1, cleanup_posture="RESTRICTED")
    assert_fields(world.read_enrollment(), status="CLOSED", reverted_completion_count=0)


def test_the_impairment_revokes_the_letter_but_keeps_the_lender_on_the_record(api):
    """
    Level four: closure is withdrawn while the reliance history survives it.

    "Where the letter had been accepted, `accepted_by_lender_user_id` and
    `lender_reference` are **preserved as history** rather than cleared — the record of
    who relied on the letter survives its revocation."

    Design: Difficulty/transitive_cascade/monitoring_exceedance_impairs_control_revokes_letter_rescinds_awards
    """
    world = _staged_cascade(api)
    assert_fields(
        world.read_letter(),
        status="ACCEPTED_BY_LENDER",
        accepted_by_lender_user_id="lender-1",
        lender_reference="LN-2743-77",
        revocation_reason=None,
        reissue_count=0,
    )

    _trigger_exceedance(world)

    assert_fields(
        world.read_letter(),
        status="REVOKED",
        revocation_reason="CONTROL_FAILURE",
        accepted_by_lender_user_id="lender-1",
        lender_reference="LN-2743-77",
        reissue_count=0,
    )


def test_the_revocation_rescinds_every_award_and_reopens_the_whole_gap(api):
    """
    The last level empties the assembly and the conserved total still holds.

    "In either case the letter moves to `REVOKED`, its `version` increments by 1, and
    every funding award on the parcel whose `status` is `AWARDED` becomes `RESCINDED`
    with its `allocated_cents` set to zero, which re-derives the parcel's assembly and
    raises `unfunded_gap_cents` accordingly."

    Design: Difficulty/transitive_cascade/monitoring_exceedance_impairs_control_revokes_letter_rescinds_awards
    """
    world = _staged_cascade(api)

    before = world.read_funding_assembly()
    assert_fields(
        before,
        total_funding_need_cents=FUNDING_NEED_CENTS,
        unfunded_gap_cents=71564558,
        local_match_required_cents=4768442,
    )
    assert [row["allocated_cents"] for row in before["allocations"]] == [
        GRANT_ALLOCATION_CENTS,
        TAX_CREDIT_ALLOCATION_CENTS,
    ]
    assert_funding_conservation(before)

    _trigger_exceedance(world)

    for award in world.awards:
        assert_fields(world.read_award(award), status="RESCINDED", allocated_cents=0)

    after = world.read_funding_assembly()
    assert_fields(
        after,
        total_funding_need_cents=FUNDING_NEED_CENTS,
        unfunded_gap_cents=FUNDING_NEED_CENTS,
        local_match_required_cents=0,
    )
    assert after["allocations"] == [], "a rescinded award leaves no allocation behind"
    assert_funding_conservation(after)


# ─── lapsed_reasonable_steps_forfeits_defence_and_freezes_site ──────────────────


def _staged_cascade_with_duties(api):
    """The same closed file, plus five imposed duties whose periods have run out."""
    world = _staged_cascade(api)
    for category, description, due_date in LAPSING_DUTIES:
        world.obligations[category] = impose_obligation(
            world,
            obligation_category=category,
            description=description,
            due_date=due_date,
            recurrence_days=90,
        )
    return world


def test_the_sweep_lapses_the_overdue_duties_and_forfeits_the_defence(api):
    """
    Every duty is past its deadline, and two of them are defence-critical.

    "A duty in either `CURRENT` or `AT_RISK` whose `due_date` is strictly earlier than the
    `as_of_date` moves to the terminal `LAPSED`; both edges behave identically."

    Design: Difficulty/transitive_cascade/lapsed_reasonable_steps_forfeits_defence_and_freezes_site
    """
    world = _staged_cascade_with_duties(api)
    assert_fields(world.read_protection(), obligation_state="CURRENT", bfpp_status="ESTABLISHED")

    result = run_sweep(world, "2027-07-01")
    assert_sweep_counters(
        result,
        swept_obligation_count=5,
        lapsed_count=5,
        at_risk_count=0,
        stale_inquiry_count=0,
        forfeited_protection_count=1,
        frozen_site_count=1,
    )

    protection = world.read_protection()
    assert_fields(
        protection,
        obligation_state="LAPSED",
        bfpp_status="FORFEITED",
        obligations_total_weight=20,
        current_weight=0,
        satisfied_weight=0,
        at_risk_weight=0,
        lapsed_weight=20,
    )
    assert_number(protection["compliance_pct"], "0.0000", "compliance_pct")
    for category, _description, _due in LAPSING_DUTIES:
        assert_fields(world.read_obligation(world.obligations[category]), status="LAPSED")


def test_the_forfeiture_freezes_the_parcel_and_revokes_the_letter_uncurably(api):
    """
    Forfeiture dominates the posture and stamps the letter with the incurable reason.

    "Where a lapsed duty's `obligation_category` is defence-critical, the cascade
    continues: the protection's `obligation_state` becomes `LAPSED`, its `bfpp_status`
    becomes `FORFEITED`, the parcel's `cleanup_posture` becomes `FROZEN`, every closure
    letter on the parcel in `ISSUED` or `ACCEPTED_BY_LENDER` becomes `REVOKED` with
    `revocation_reason` `BFPP_FORFEITED`, and every funding award on the parcel in
    `AWARDED` becomes `RESCINDED`."

    Design: Difficulty/transitive_cascade/lapsed_reasonable_steps_forfeits_defence_and_freezes_site
    """
    world = _staged_cascade_with_duties(api)

    run_sweep(world, "2027-07-01")

    assert_fields(world.read_site(), cleanup_posture="FROZEN", impaired_control_count=0)
    assert_fields(
        world.read_letter(),
        status="REVOKED",
        revocation_reason="BFPP_FORFEITED",
        accepted_by_lender_user_id="lender-1",
        lender_reference="LN-2743-77",
    )


def test_the_forfeiture_rescinds_the_awards_and_leaves_the_need_unfunded(api):
    """
    The money unwinds with the letter and the conserved total still balances.

    "Second, in the funding assembly, the sum of every awarded application's
    `allocated_cents` plus the residual `unfunded_gap_cents` always equals the approved
    plan's `total_funding_need_cents`."

    Design: Difficulty/transitive_cascade/lapsed_reasonable_steps_forfeits_defence_and_freezes_site
    """
    world = _staged_cascade_with_duties(api)

    run_sweep(world, "2027-07-01")

    for award in world.awards:
        assert_fields(world.read_award(award), status="RESCINDED", allocated_cents=0)

    assembly = world.read_funding_assembly()
    assert_fields(
        assembly,
        total_funding_need_cents=FUNDING_NEED_CENTS,
        unfunded_gap_cents=FUNDING_NEED_CENTS,
        local_match_required_cents=0,
    )
    assert assembly["allocations"] == [], "no awarded application remains to allocate to"
    assert_funding_conservation(assembly)
    assert_fields(world.read_enrollment(), status="CLOSED")
