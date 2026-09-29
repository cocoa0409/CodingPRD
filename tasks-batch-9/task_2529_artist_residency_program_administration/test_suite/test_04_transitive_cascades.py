"""Chains that run four and five links deep from a single request."""

from test_helpers import (
    ERR_PANEL_REVIEW_INCOMPLETE,
    ERR_PANELIST_RECUSED,
    assert_money_equals,
    assign_panelist,
    assignments_for,
    check_in,
    complete_all_trainings,
    create_applicant,
    create_chair,
    create_panelist,
    create_residency,
    declare_conflict,
    disbursements_for,
    generate_stipend_schedule,
    make_panel_assignment_payload,
    read_application,
    read_cycle,
    read_panel_assignment,
    read_panelist,
    refresh_residency,
    schedule_residency,
    score_assignment,
    set_clock,
    setup_open_cycle,
    setup_panel_review_cycle,
    terminate_residency,
    validate_error,
    ADMIN_HEADERS,
)

HAZMAT_SCULPT = {"requires_hazmat_review": True}


def _residency_mid_session(api):
    """An eight-week residency, checked in, with a full disbursement calendar."""
    cycle = setup_open_cycle(api, discipline_overrides=HAZMAT_SCULPT)
    applicant = create_applicant(api)
    residency = create_residency(api, cycle, applicant)
    schedule_residency(api, residency, "2026-11-02", 8)
    generate_stipend_schedule(api, residency)
    complete_all_trainings(api, residency)
    set_clock(api, "2026-11-02T09:00:00Z")
    check_in(api, residency)
    return cycle, residency


def test_termination_voids_every_scheduled_disbursement(api):
    """Settling the week count sweeps the unpaid calendar to nothing.

    PRD: "Caused by link 1, every stipend disbursement of the residency still in
    status `SCHEDULED` moves `SCHEDULED → VOIDED`, each with its
    `withholding_cents` and `net_cents` set to 0 and its `version` advanced by
    1."

    Design: Difficulty/transitive_cascade/terminate_residency_repricing_chain_reaches_the_cycle_ledger
    """
    _cycle, residency = _residency_mid_session(api)
    before = disbursements_for(api, residency.residency_id)
    assert len(before) == 4
    assert all(row["status"] == "SCHEDULED" for row in before)
    assert all(row["gross_cents"] == 140000 for row in before)

    set_clock(api, "2026-11-20T15:00:00Z")
    settled = terminate_residency(
        api, residency, "resident withdrew from the shop after a safety incident"
    )
    assert settled["actual_weeks_in_residence"] == 3

    after = disbursements_for(api, residency.residency_id)
    assert [row["status"] for row in after] == ["VOIDED"] * 4
    for row in after:
        assert row["withholding_cents"] == 0
        assert row["net_cents"] == 0


def test_the_void_sweep_releases_the_over_commitment_to_the_cycle(api):
    """The re-price is passed on, so the cycle stops holding money it lost.

    PRD: "Caused by link 3, the cycle's `stipend_committed_cents` is reduced by
    the difference between the old award and the new one, and
    `stipend_uncommitted_cents` is recomputed, releasing the unspent balance
    back to the funding pool."

    Design: Difficulty/transitive_cascade/terminate_residency_repricing_chain_reaches_the_cycle_ledger
    """
    cycle, residency = _residency_mid_session(api)
    committed = read_cycle(api, cycle.cycle_id)
    assert_money_equals(committed["stipend_committed_cents"], 560000, "committed")
    assert_money_equals(committed["stipend_uncommitted_cents"], 19440000, "uncommitted")

    set_clock(api, "2026-11-20T15:00:00Z")
    settled = terminate_residency(api, residency)
    assert settled["stipend_basis"] == "FINAL_SETTLED"
    assert_money_equals(settled["stipend_total_cents"], 210000, "settled award")

    released = read_cycle(api, cycle.cycle_id)
    assert_money_equals(released["stipend_committed_cents"], 210000, "committed")
    assert_money_equals(released["stipend_uncommitted_cents"], 19790000, "uncommitted")
    assert (
        committed["stipend_committed_cents"] - released["stipend_committed_cents"]
        == 350000
    )


def test_the_money_cascade_leaves_the_slot_ledger_where_it_was(api):
    """A terminated residency keeps its place in the cohort it filled.

    PRD: "Residencies in `WITHDRAWN` leave both ledgers entirely — money and
    slot alike — whereas residencies in `TERMINATED` remain in both, but with
    their award already reduced to the settled figure."

    Design: Difficulty/transitive_cascade/terminate_residency_repricing_chain_reaches_the_cycle_ledger
    """
    cycle, residency = _residency_mid_session(api)
    occupied = read_cycle(api, cycle.cycle_id)
    assert occupied["slots_filled_count"] == 1
    assert occupied["slots_open_count"] == 9

    set_clock(api, "2026-11-20T15:00:00Z")
    terminate_residency(api, residency)

    unchanged = read_cycle(api, cycle.cycle_id)
    assert unchanged["slots_filled_count"] == 1
    assert unchanged["slots_open_count"] == 9
    assert refresh_residency(api, residency)["status"] == "TERMINATED"


def _scored_two_application_panel(api):
    """Two scored applications sharing one reviewer, so a recusal spans both."""
    cycle, apps = setup_panel_review_cycle(api, applicant_count=2, panel_quorum=2)
    app_one, app_two = apps
    shared = create_panelist(api)
    only_one = create_panelist(api)
    only_two = create_panelist(api)

    shared_on_one = assign_panelist(api, app_one, shared)
    solo_on_one = assign_panelist(api, app_one, only_one)
    shared_on_two = assign_panelist(api, app_two, shared)
    solo_on_two = assign_panelist(api, app_two, only_two)

    score_assignment(api, shared_on_one["id"], shared, 8, 8, 8, 8)
    score_assignment(api, solo_on_one["id"], only_one, 6, 6, 6, 6)
    score_assignment(api, shared_on_two["id"], shared, 8, 8, 8, 8)
    score_assignment(api, solo_on_two["id"], only_two, 7, 7, 7, 7)

    return {
        "cycle": cycle,
        "app_one": app_one,
        "app_two": app_two,
        "shared": shared,
        "shared_on_one": shared_on_one,
        "shared_on_two": shared_on_two,
        "solo_on_one": solo_on_one,
    }


def test_a_severe_conflict_clears_the_declaring_row_and_freezes_the_reviewer(api):
    """Links one and two: the row is emptied and the reviewer is recused.

    PRD: "Only when the declared `conflict_type` is `FAMILIAL` or `FINANCIAL` —
    the two the organization treats as severe — the reviewer auto-recuses: the
    panelist's `status` becomes `RECUSED_FOR_CYCLE` and `recused_cycle_id` is
    set to the `cycle_id` of the application under review."

    Design: Difficulty/transitive_cascade/severe_conflict_recusal_chain_unwinds_the_whole_cycle_panel
    """
    world = _scored_two_application_panel(api)
    assert read_application(api, world["app_one"].application_id)["status"] == "SCORED"

    declared = declare_conflict(
        api,
        world["shared_on_one"]["id"],
        world["shared"],
        "FAMILIAL",
        "the applicant is my sibling-in-law",
    )

    assert declared["status"] == "CONFLICT_DECLARED"
    assert declared["conflict_type"] == "FAMILIAL"
    assert declared["panelist_total_100"] is None
    assert declared["scored_at"] is None
    for field in (
        "score_artistic_merit",
        "score_feasibility",
        "score_community_fit",
        "score_technical_readiness",
    ):
        assert declared[field] is None

    frozen = read_panelist(api, world["shared"].panelist_id)
    assert frozen["status"] == "RECUSED_FOR_CYCLE"
    assert frozen["recused_cycle_id"] == world["cycle"].cycle_id


def test_the_recusal_vacates_the_reviewer_s_other_rows_in_the_same_cycle(api):
    """Link three reaches an application that was never named in the request.

    PRD: "Caused by the recusal, every **other** panel assignment held by that
    reviewer whose application belongs to the same cycle and whose status is
    `ASSIGNED` or `SCORED` is moved to `VACATED`."

    Design: Difficulty/transitive_cascade/severe_conflict_recusal_chain_unwinds_the_whole_cycle_panel
    """
    world = _scored_two_application_panel(api)

    declare_conflict(api, world["shared_on_one"]["id"], world["shared"], "FAMILIAL")

    vacated = read_panel_assignment(api, world["shared_on_two"]["id"])
    assert vacated["status"] == "VACATED"
    assert vacated["panelist_total_100"] is None
    assert vacated["scored_at"] is None

    # The vacate is scoped to the recused reviewer's own rows.
    untouched = read_panel_assignment(api, world["solo_on_one"]["id"])
    assert untouched["status"] == "SCORED"
    assert untouched["panelist_total_100"] == 60.00


def test_both_applications_fall_back_below_quorum(api):
    """Link four demotes every application whose contributing count collapsed.

    PRD: "An application in status `SCORED` whose contributing count has now
    fallen below the cycle's `panel_quorum` is demoted along the reverse edge
    `SCORED → PANEL_REVIEW`, with `final_panel_score` and `rank_in_discipline`
    both set to null."

    Design: Difficulty/transitive_cascade/severe_conflict_recusal_chain_unwinds_the_whole_cycle_panel
    """
    world = _scored_two_application_panel(api)

    declare_conflict(api, world["shared_on_one"]["id"], world["shared"], "FAMILIAL")

    named = read_application(api, world["app_one"].application_id)
    assert named["status"] == "PANEL_REVIEW"
    assert named["scored_panelist_count"] == 1
    assert named["final_panel_score"] is None
    assert named["rank_in_discipline"] is None
    assert named["provisional_screening_score"] == 60.00

    sibling = read_application(api, world["app_two"].application_id)
    assert sibling["status"] == "PANEL_REVIEW"
    assert sibling["scored_panelist_count"] == 1
    assert sibling["final_panel_score"] is None
    assert sibling["provisional_screening_score"] == 70.00


def test_the_cycle_loses_its_readiness_and_cannot_be_locked(api):
    """Link five reaches the cycle and closes the slate lock behind it.

    PRD: "And `panel_review_complete` is true precisely when
    `slate_ready_count` is at least 1 **and** no application of the cycle
    remains in status `PANEL_REVIEW`."

    Design: Difficulty/transitive_cascade/severe_conflict_recusal_chain_unwinds_the_whole_cycle_panel
    """
    world = _scored_two_application_panel(api)
    ready = read_cycle(api, world["cycle"].cycle_id)
    assert ready["slate_ready_count"] == 2
    assert ready["panel_review_complete"] is True

    declare_conflict(api, world["shared_on_one"]["id"], world["shared"], "FAMILIAL")

    unwound = read_cycle(api, world["cycle"].cycle_id)
    assert unwound["slate_ready_count"] == 0
    assert unwound["panel_review_complete"] is False

    chair = create_chair(api)
    validate_error(
        api.lock_slate(world["cycle"].cycle_id, chair.chair_headers),
        ERR_PANEL_REVIEW_INCOMPLETE,
    )


def test_a_recused_reviewer_takes_no_further_work_in_that_cycle(api):
    """The frozen reviewer can no longer be seated on anything in the cycle.

    PRD: "the reviewer's `status` must be `ACTIVE`, because a panelist frozen as
    `RECUSED_FOR_CYCLE` takes no further work in that cycle and the refusal is
    `ERR_PANELIST_RECUSED` (HTTP 409)".

    Design: Difficulty/transitive_cascade/severe_conflict_recusal_chain_unwinds_the_whole_cycle_panel
    """
    world = _scored_two_application_panel(api)

    declare_conflict(api, world["shared_on_one"]["id"], world["shared"], "FAMILIAL")

    validate_error(
        api.create_panel_assignment(
            make_panel_assignment_payload(
                world["app_two"].application_id, world["shared"].panelist_id
            ),
            ADMIN_HEADERS,
        ),
        ERR_PANELIST_RECUSED,
    )

    rows = assignments_for(api, panelist_id=world["shared"].panelist_id)
    assert sorted(row["status"] for row in rows) == ["CONFLICT_DECLARED", "VACATED"]
