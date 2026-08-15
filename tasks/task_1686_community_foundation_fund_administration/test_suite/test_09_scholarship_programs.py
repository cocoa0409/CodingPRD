"""Scholarship programs: committee quorum, scoring, the application window,
winner selection, and award responses."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_active_fund,
    create_scholarship_program,
    setup_open_program,
    setup_scoring_program,
    setup_awarded_program,
    submit_application,
    score_application,
    set_logical_clock,
    make_applicant_headers,
    make_committee_member_headers,
    create_member_payload,
    create_score_payload,
    assert_money_eq,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["foundation_admin_headers"]
PROGRAM = TEST_USERS["program_officer_headers"]


def test_close_applications_moves_program_to_scoring(api):
    """PRD §3.7: "The program moves from `OPEN` to `SCORING`, and every
    `SUBMITTED` application cascades to `UNDER_SCORING`."

    Design: Difficulty/transitive_cascade/program_close_applications_scoring_cascade
    """
    env = setup_scoring_program(num_applications=2)
    assert env["program"]["status"] == "SCORING"


def test_close_applications_cascades_applications_to_under_scoring(api):
    """PRD §3.7: "The program moves from `OPEN` to `SCORING`, and every
    `SUBMITTED` application cascades to `UNDER_SCORING`."

    Design: Difficulty/transitive_cascade/program_close_applications_scoring_cascade
    """
    env = setup_scoring_program(num_applications=2)
    for application in env["applications"]:
        refreshed = validate_success(api.get_application(application["id"], PROGRAM))
        assert refreshed["status"] == "UNDER_SCORING"


def _setup_two_apps_one_quorum_met(api):
    """SCORING program (3 members, quorum 2) with two applications: app_scored
    has two entries (final_score set), app_thin has exactly one (null)."""
    env = setup_scoring_program(num_applications=2)
    app_scored = env["applications"][0]
    app_thin = env["applications"][1]
    members = env["members"]
    score_application(app_scored["id"], members[0]["id"])
    score_application(app_scored["id"], members[1]["id"])
    score_application(app_thin["id"], members[0]["id"])
    return env, app_scored, app_thin


def test_unscored_winner_rejected_until_quorum(api):
    """PRD §3.7: "Its checks run in order: at least one application must carry a
    non-null `final_score` — quorum met somewhere — failing with
    `ERR_QUORUM_NOT_MET` (HTTP 422); the slate's length must not exceed
    `max_awards`, failing with `ERR_TOO_MANY_WINNERS` (HTTP 422); every named
    winner must itself carry a `final_score`, failing with `ERR_UNSCORED_WINNER`
    (HTTP 422); and every named winner must belong to this program, failing with
    `ERR_CROSS_REFERENCE_MISMATCH`."
    PRD §3.7: "The application's `final_score` is then maintained continuously:
    once the number of score entries whose member held `SEATED` status at the
    time of scoring reaches the program's `quorum_threshold`, `final_score`
    becomes the mean of those entries' `weighted_score` values, rounded half-up
    to two decimal places; before quorum it remains null."

    Design: Difficulty/boundary_precision_check/quorum_threshold_boundary_on_select_winners
    """
    env, app_scored, app_thin = _setup_two_apps_one_quorum_met(api)
    # Quorum (2 of 3) is met program-wide via app_scored, but the named winner
    # has only one score — one below quorum — so its final_score is null.
    thin = validate_success(api.get_application(app_thin["id"], PROGRAM))
    assert thin["final_score"] is None
    resp = api.select_winners(
        env["program"]["id"], {"winner_application_ids": [app_thin["id"]]}, PROGRAM
    )
    validate_error(resp, ApiErrorId.ERR_UNSCORED_WINNER)


def test_selection_succeeds_once_quorum_met(api):
    """PRD §3.7: "Selection moves each winner to `SELECTED` and every other
    `UNDER_SCORING` application to `NOT_SELECTED`, creates one scholarship award
    per winner in `OFFERED` status with its `amount` copied from the program's
    `award_amount` and its `program_id` and `fund_id` denormalized from the
    application and program, answers with the created `award_ids` and a
    `selected_count`, and moves the program to `AWARDED`."
    PRD §3.7: "Each entry's `weighted_score` is forty percent of `academic`,
    thirty percent of `financial_need`, twenty percent of `essay`, and ten
    percent of `interview`, summed and rounded half-up to two decimal places."

    Design: Difficulty/boundary_precision_check/quorum_threshold_boundary_on_select_winners
    """
    env, app_scored, app_thin = _setup_two_apps_one_quorum_met(api)
    # The second score reaches quorum (2 of 3) for the thin application.
    entry = score_application(app_thin["id"], env["members"][1]["id"])
    assert_money_eq(entry["weighted_score"], 80.00, "weighted score")
    thin = validate_success(api.get_application(app_thin["id"], PROGRAM))
    assert_money_eq(thin["final_score"], 80.00, "final score at quorum")

    result = validate_success(
        api.select_winners(
            env["program"]["id"], {"winner_application_ids": [app_thin["id"]]}, PROGRAM
        ),
        200,
    )
    assert result["selected_count"] == 1
    assert len(result["award_ids"]) == 1
    program = validate_success(api.get_program(env["program"]["id"], PROGRAM))
    assert program["status"] == "AWARDED"


def test_application_at_exact_window_open_accepted(api):
    """PRD §3.7: "An `Applicant` submits with `applicant_name` and
    `applicant_email`, unique per program, and the submission is accepted only
    inside the window — the logical clock at or after `application_open` and
    strictly before `application_close` — failing with `ERR_OUTSIDE_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/scholarship_application_window_membership
    """
    env = setup_open_program()  # clock sits exactly at application_open
    application = submit_application(env["program"]["id"])
    assert application["status"] == "SUBMITTED"


def test_application_at_exact_window_close_rejected(api):
    """PRD §3.7: "An `Applicant` submits with `applicant_name` and
    `applicant_email`, unique per program, and the submission is accepted only
    inside the window — the logical clock at or after `application_open` and
    strictly before `application_close` — failing with `ERR_OUTSIDE_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/scholarship_application_window_membership
    """
    env = setup_open_program()
    # Exactly at application_close the half-open window has ended.
    set_logical_clock("2026-03-01T00:00:00Z")
    resp = api.submit_application(
        env["program"]["id"],
        {"applicant_name": "Late Exact", "applicant_email": "late@example.org"},
        TEST_USERS["applicant_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_WINDOW)


def test_award_accept_cascades_to_application(api):
    """PRD §3.7: "Acceptance moves the award from `OFFERED` to `ACCEPTED` and
    cascades the application to `ACCEPTED_AWARD`; declination moves the award to
    `DECLINED` and the application to `DECLINED_AWARD`."

    Design: Corner/state_machines/award_accept_cascades_application
    """
    env = setup_awarded_program()
    application = env["applications"][0]
    awards, _ = validate_paginated(
        api.list_program_awards(env["program"]["id"], PROGRAM)
    )
    assert len(awards) == 1
    award = awards[0]
    assert award["status"] == "OFFERED"
    accepted = validate_success(
        api.accept_award(award["id"], make_applicant_headers(application["id"])), 200
    )
    assert accepted["status"] == "ACCEPTED"
    app_after = validate_success(api.get_application(application["id"], PROGRAM))
    assert app_after["status"] == "ACCEPTED_AWARD"


def test_open_requires_three_member_committee(api):
    """PRD §3.7: "Opening the program enforces three checks in order: the
    committee must number at least 3 seated members, failing with
    `ERR_COMMITTEE_TOO_SMALL` (HTTP 422); the application window must be
    well-formed, with `application_close` after `application_open`; and the
    current logical clock must not yet have reached `application_close`, failing
    with `ERR_OUTSIDE_WINDOW`."

    Design: Corner/errors/err_committee_too_small_triggerable
    """
    set_logical_clock("2026-01-15T00:00:00Z")
    bundle = create_active_fund(fund_type="SCHOLARSHIP", seed_amount=100000.00)
    built = create_scholarship_program(
        fund_id=bundle["fund"]["id"], member_count=2
    )
    resp = api.open_program(built["program"]["id"], PROGRAM)
    validate_error(resp, ApiErrorId.ERR_COMMITTEE_TOO_SMALL)
    # Seating a third member satisfies the minimum.
    validate_success(
        api.seat_committee_member(
            built["program"]["id"], create_member_payload(), PROGRAM
        ),
        201,
    )
    opened = validate_success(api.open_program(built["program"]["id"], PROGRAM), 200)
    assert opened["status"] == "OPEN"


def test_duplicate_score_rejected(api):
    """PRD §3.7: "The scoring member must be seated on the program that owns the
    application; a member of a different program's committee is rejected with
    `ERR_CROSS_REFERENCE_MISMATCH` (HTTP 422), and a second score from the same
    member on the same application is rejected with `ERR_DUPLICATE_SCORE`
    (HTTP 409)."

    Design: Corner/errors/err_duplicate_score_triggerable
    """
    env = setup_scoring_program(num_applications=1)
    application = env["applications"][0]
    member = env["members"][0]
    score_application(
        application["id"], member["id"],
        academic=70, financial_need=70, essay=70, interview=70,
    )
    resp = api.create_score(
        application["id"],
        create_score_payload(
            member_id=member["id"], academic=99, financial_need=99, essay=99, interview=99
        ),
        make_committee_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCORE)


def test_score_component_range(api):
    """PRD §3.7: "A `CommitteeMember` scores an application by submitting their
    own `member_id` together with four integer components — `academic`,
    `financial_need`, `essay`, and `interview` — each between 0 and 100
    inclusive, failing which the entry is rejected with `ERR_FIELD_CONSTRAINT`."

    Design: Corner/validations/score_component_range_enforced
    """
    env = setup_scoring_program(num_applications=1)
    application = env["applications"][0]
    member = env["members"][0]
    resp = api.create_score(
        application["id"],
        create_score_payload(
            member_id=member["id"], academic=101, financial_need=50, essay=50, interview=50
        ),
        make_committee_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FIELD_CONSTRAINT)
    # Bounds are inclusive: 100 and 0 are both legal components.
    entry = score_application(
        application["id"], member["id"],
        academic=100, financial_need=0, essay=50, interview=50,
    )
    # 0.40*100 + 0.30*0 + 0.20*50 + 0.10*50 = 55.00
    assert_money_eq(entry["weighted_score"], 55.00, "weighted score at range bounds")


def test_weighted_score_computation(api):
    """PRD §3.7: "Each entry's `weighted_score` is forty percent of `academic`,
    thirty percent of `financial_need`, twenty percent of `essay`, and ten
    percent of `interview`, summed and rounded half-up to two decimal places."
    PRD §3.7: "The application's `final_score` is then maintained continuously:
    once the number of score entries whose member held `SEATED` status at the
    time of scoring reaches the program's `quorum_threshold`, `final_score`
    becomes the mean of those entries' `weighted_score` values, rounded half-up
    to two decimal places; before quorum it remains null."

    Design: Corner/calculations/weighted_score_rounding_and_constants
    """
    env = setup_scoring_program(num_applications=1)
    application = env["applications"][0]
    member = env["members"][0]
    entry = score_application(
        application["id"], member["id"],
        academic=88, financial_need=90, essay=80, interview=85,
    )
    # 0.40*88 + 0.30*90 + 0.20*80 + 0.10*85 = 35.2 + 27 + 16 + 8.5 = 86.70
    assert_money_eq(entry["weighted_score"], 86.70, "weighted score")
    # One entry is below the quorum threshold of 2, so final_score stays null.
    app_after = validate_success(api.get_application(application["id"], PROGRAM))
    assert app_after["final_score"] is None
