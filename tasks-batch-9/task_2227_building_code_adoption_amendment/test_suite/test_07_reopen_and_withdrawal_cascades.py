"""The two deep cascades: reopening an approval, and withdrawing a published order."""
from test_helpers import (
    ADMIN_PUBLISHER_ID,
    STAFF_SECOND_ANALYST_ID,
    fixtures,
    get_success_data,
    make_council_admin_headers,
    make_technical_staff_headers,
    validate_success,
)
from test_helpers.factories import ballot

MECHANICAL_PROPOSAL = {
    "code_section": "M403.3.1",
    "discipline": "MECHANICAL",
    "title": "Ventilation rate table cleanup",
    "proposed_text": (
        "Restate the outdoor air rate table without changing required rates."
    ),
    "stringency_direction": "NEUTRAL",
    "proposer_sector": "DESIGN_PROFESSIONAL",
}

MECHANICAL_COST_BENEFIT = {
    "incremental_cost_by_occupancy": {"R3": 10000, "R2": 12000, "B": 15000, "A2": 18000},
    "affected_permit_count": 700,
    "annual_cost_savings_cents": 900000,
    "measure_life_years": 20,
}

SECOND_HEARING = {
    "scheduled_start": "2026-10-06T09:00:00Z",
    "scheduled_end": "2026-10-06T12:00:00Z",
}


def _two_approvals_with_draft_rule(api):
    """Two approvals in one cycle — the ENERGY amendment and a MECHANICAL one —
    with a DRAFT rulemaking order whose schedule was computed from the combined
    backlog of 3,110 permits."""
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.add_mechanical_committee(api, world)

    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_OPEN")
    fixtures.submit_proposal(api, world)

    mech = dict(world)
    mech["committee_id"] = world["mechanical_committee_id"]
    mech["members"] = world["mechanical_members"]
    fixtures.submit_proposal(api, mech, **MECHANICAL_PROPOSAL)

    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_CLOSED")

    fixtures.screen_proposal(api, world)
    fixtures.file_cost_benefit_analysis(api, world)
    fixtures.review_analysis(api, world["cost_benefit_id"])
    fixtures.file_energy_impact_analysis(api, world)
    fixtures.review_analysis(api, world["energy_impact_id"])

    fixtures.screen_proposal(api, mech)
    fixtures.file_cost_benefit_analysis(
        api,
        mech,
        headers=make_technical_staff_headers(STAFF_SECOND_ANALYST_ID),
        **MECHANICAL_COST_BENEFIT,
    )
    fixtures.review_analysis(api, mech["cost_benefit_id"])

    fixtures.set_cycle_status(api, world["cycle_id"], "DELIBERATION")
    fixtures.open_comment_window(api, world)
    fixtures.open_comment_window(api, mech)
    fixtures.set_logical_clock(api, fixtures.CLOCK_MID_COMMENT)
    fixtures.submit_golden_comments(api, world)
    fixtures.set_logical_clock(api, fixtures.CLOCK_COMMENT_CLOSES)
    fixtures.act_on_comment_window(api, world, "CLOSE")
    fixtures.act_on_comment_window(api, mech, "CLOSE")

    fixtures.add_scheduled_hearing(api, world)
    fixtures.fill_agenda(api, world)
    fixtures.add_scheduled_hearing(api, mech, **SECOND_HEARING)
    fixtures.fill_agenda(api, mech)

    fixtures.set_logical_clock(api, fixtures.CLOCK_HEARING_START)
    fixtures.convene_hearing(api, world)
    get_success_data(fixtures.record_vote(api, world), 201)

    fixtures.set_logical_clock(api, fixtures.CLOCK_SECOND_HEARING_START)
    fixtures.convene_hearing(api, mech)
    mech_ballots = [
        ballot(mech["members"]["chair"]["id"], "YES"),
        ballot(mech["members"]["fire"]["id"], "YES"),
        ballot(mech["members"]["local"]["id"], "YES"),
    ]
    get_success_data(fixtures.record_vote(api, mech, ballots=mech_ballots), 201)

    fixtures.set_cycle_status(api, world["cycle_id"], "RULEMAKING")
    fixtures.create_adoption_rule(api, world)
    mech["rule_id"] = world["rule_id"]
    return world, mech


def test_01_reopening_one_approval_compensates_the_ledger_and_supersedes_its_analysis(
    api,
):
    """"At the first level, the proposal moves to `RETURNED_FOR_REVISION`,
    `revision_round` increments by one, and the analysis dimension moves
    `COMPLETE` → `STALE`. At the second level ... every child analysis of that
    proposal whose `status` is `ACCEPTED` moves `ACCEPTED` → `SUPERSEDED`" and "at
    the third level ... `statewide_incremental_cost_cents`, `affected_permit_count`,
    `preliminary_benefit_cost_ratio` and `final_benefit_cost_ratio` are all
    cleared back to null." At the fourth level "the cleared
    `statewide_incremental_cost_cents` is subtracted from the cycle's
    `approved_incremental_cost_cents`", leaving only the surviving approval's
    143,002,800 cents over 2,410 permits.

    Design: Difficulty/transitive_cascade/reopen_approved_proposal_cascade_depth_six_reschedules_draft_rule
    """
    world, mech = _two_approvals_with_draft_rule(api)

    validate_success(
        fixtures.reopen_proposal(
            api,
            mech,
            reason=(
                "Ventilation table restatement conflicts with the mechanical "
                "appendix."
            ),
        )
    )

    reopened = fixtures.read_proposal(api, mech["proposal_id"])
    assert reopened["review_status"] == "RETURNED_FOR_REVISION"
    assert reopened["analysis_status"] == "STALE"
    assert reopened["revision_round"] == 1
    assert reopened["statewide_incremental_cost_cents"] is None
    assert reopened["affected_permit_count"] is None
    assert reopened["final_benefit_cost_ratio"] is None

    analysis = get_success_data(
        api.get_impact_analysis(mech["cost_benefit_id"], make_council_admin_headers())
    )
    assert analysis["status"] == "SUPERSEDED"

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["approved_incremental_cost_cents"] == 143002800
    assert cycle["approved_permit_backlog_count"] == 2410
    assert cycle["approved_proposal_count"] == 1

    survivor = fixtures.read_proposal(api, world["proposal_id"])
    assert survivor["review_status"] == "APPROVED"


def test_02_the_draft_order_reschedules_itself_and_the_cycle_reverts(api):
    """"At the fifth level, because the cycle's approved backlog has changed,
    every rulemaking order of that cycle still in `DRAFT` recomputes its whole
    schedule — `projected_permit_backlog`, `transition_grace_days`,
    `notice_days`, `effective_date`, `transition_cutoff_date` and
    `prior_code_expiry_date` — while its `base_date` stays exactly where it was.
    At the sixth level ... the cycle reverts `RULEMAKING` → `DELIBERATION`." The
    backlog falls from 3,110 to 2,410, so the projection falls from 511 to 396,
    the grace tier from 180 to 90 days and the notice period to its 120-day
    floor, re-dating the order from the unchanged 2026-10-06 anchor.

    Design: Difficulty/transitive_cascade/reopen_approved_proposal_cascade_depth_six_reschedules_draft_rule
    """
    world, mech = _two_approvals_with_draft_rule(api)
    assert world["rule"]["projected_permit_backlog"] == 511
    assert world["rule"]["notice_days"] == 180

    fixtures.reopen_proposal(
        api,
        mech,
        reason="Ventilation table restatement conflicts with the mechanical appendix.",
    )

    rule = get_success_data(
        api.get_adoption_rule(world["rule_id"], make_council_admin_headers())
    )
    assert rule["base_date"] == "2026-10-06T00:00:00Z"
    assert rule["projected_permit_backlog"] == 396
    assert rule["transition_grace_days"] == 90
    assert rule["notice_days"] == 120
    assert rule["effective_date"] == "2027-02-03T00:00:00Z"
    assert rule["prior_code_expiry_date"] == "2028-02-03T00:00:00Z"

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["status"] == "DELIBERATION"


def _delivered_training_and_local_filing_world(api):
    """A published order carrying all of Riverbend's and Harborview's training,
    plus one accepted Riverbend local amendment."""
    world = fixtures.setup_published_adoption_rule(api)
    fixtures.add_riverbend(api, world)
    fixtures.add_harborview(api, world)
    # The local filing is accepted while the clock is still inside the 90-day
    # window that runs from the order's `published_at`.
    fixtures.setup_accepted_local_amendment(api, world=world)
    fixtures.setup_delivered_session_two_jurisdictions(api, world=world)
    return world


def _withdraw(api, world):
    return fixtures.advance_rule(
        api,
        world,
        "WITHDRAWN",
        make_council_admin_headers(ADMIN_PUBLISHER_ID),
        withdrawal_reason="Statutory defect found in the notice filing.",
    )


def test_03_withdrawal_cancels_delivered_training_and_restores_the_seat_ledger(api):
    """"At level two, every training session whose `adoption_rule_id` is this
    order and whose `status` is `SCHEDULED`, `ENROLLMENT_OPEN`,
    `ENROLLMENT_CLOSED` or `DELIVERED` moves to `CANCELLED` — note that even a
    `DELIVERED` session is cancelled ... At level three ... every enrollment on
    them whose `status` is `ENROLLED`, `ATTENDED` or `NO_SHOW` moves to
    `CANCELLED`, each session's `seats_available` returns to its full
    `seat_capacity`, and `enrolled_count`, `attended_count` and `no_show_count`
    all return to 0."

    Design: Difficulty/transitive_cascade/withdraw_published_rule_cascade_depth_five_unreadies_jurisdictions
    """
    world = _delivered_training_and_local_filing_world(api)

    validate_success(_withdraw(api, world))

    rule = get_success_data(
        api.get_adoption_rule(world["rule_id"], make_council_admin_headers())
    )
    assert rule["status"] == "WITHDRAWN"

    session = get_success_data(
        api.get_training_session(world["session_id"], make_council_admin_headers())
    )
    assert session["status"] == "CANCELLED"
    assert session["seats_available"] == 60
    assert session["enrolled_count"] == 0
    assert session["attended_count"] == 0
    assert session["no_show_count"] == 0

    for key in ("riverbend_1", "riverbend_5", "harborview_4"):
        enrollment = get_success_data(
            api.get_training_enrollment(
                world["enrollments"][key]["id"], make_council_admin_headers()
            )
        )
        assert enrollment["status"] == "CANCELLED"


def test_04_withdrawal_unreadies_both_jurisdictions_and_voids_the_local_filing(api):
    """"At level four ... every jurisdiction that had an affected enrollment
    recomputes both `compliance_pct_enrollment_basis` and
    `compliance_pct_attendance_basis` — both falling to 0.00 when the withdrawn
    order carried all of that jurisdiction's training. At level five ... that
    jurisdiction's `enforcement_readiness` moves to `NOT_READY`." Alongside that
    chain, "every local amendment whose `adoption_rule_id` is this order and whose
    `status` is ... `FILED_EFFECTIVE` moves to `VOIDED`, and each affected
    jurisdiction's `effective_local_amendment_count` is recomputed", while the
    cycle itself is untouched.

    Design: Difficulty/transitive_cascade/withdraw_published_rule_cascade_depth_five_unreadies_jurisdictions
    """
    world = _delivered_training_and_local_filing_world(api)

    _withdraw(api, world)

    riverbend = fixtures.read_jurisdiction(api, world["riverbend_id"])
    assert riverbend["compliance_pct_enrollment_basis"] == 0.00
    assert riverbend["compliance_pct_attendance_basis"] == 0.00
    assert riverbend["enforcement_readiness"] == "NOT_READY"
    assert riverbend["effective_local_amendment_count"] == 0

    harborview = fixtures.read_jurisdiction(api, world["harborview_id"])
    assert harborview["compliance_pct_attendance_basis"] == 0.00
    assert harborview["enforcement_readiness"] == "NOT_READY"

    amendment = get_success_data(
        api.get_local_amendment(
            world["local_amendment_id"], make_council_admin_headers()
        )
    )
    assert amendment["status"] == "VOIDED"

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["status"] == "RULEMAKING"
