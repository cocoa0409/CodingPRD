"""Transitions that are legal on their own row and blocked by another entity."""
from test_helpers import (
    ANALYST_ALT_ID,
    ANALYST_ID,
    analyst_headers,
    work_specialist_headers,
)
from test_helpers import api_errors as errs
from test_helpers import assertions as asrt
from test_helpers import fixtures as fx

EARNED_ONLY = (
    {
        "source_type": "EARNED",
        "gross_monthly_cents": 40000,
        "is_recurring": True,
        "verification_status": "VERIFIED",
    },
)


def _approved_case_with_a_proposed_activity(api):
    """A case still awaiting its first issuance, with an activity lined up."""
    context = fx.build_approved_case(
        api,
        household_overrides={"head_of_household_name": "Cross Entity One Household"},
        incomes=EARNED_ONLY,
    )
    assignment = fx.create_assignment(
        api,
        context.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=20,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    return context, assignment["id"]


def test_activation_is_blocked_while_the_case_awaits_its_first_issuance(api):
    """PRD §3.5: "The owning case's `benefit_status` must be `ACTIVE`, and a case
    sitting in `PENDING_ISSUANCE`, `SUSPENDED` or `CLOSED` is refused with
    `ERR_CASE_NOT_ACTIVE`."
    PRD §3.5: "Activation moves an assignment `PROPOSED → ACTIVE` and is where the
    case's two dimensions both gate the operation."

    Design: Difficulty/cross_entity_state_dependency/assignment_activation_blocked_by_case_benefit_status_pending_issuance
    """
    context, assignment_id = _approved_case_with_a_proposed_activity(api)

    response = api.activate_work_assignment(assignment_id, work_specialist_headers())

    asrt.assert_rejected(response, errs.ERR_CASE_NOT_ACTIVE)
    assert fx.read_assignment(api, assignment_id)["status"] == "PROPOSED"
    asrt.assert_case_state(
        fx.read_case(api, context.case_id), benefit_status="PENDING_ISSUANCE"
    )


def test_the_same_activation_succeeds_once_a_month_has_been_issued(api):
    """PRD §3.4: "The first successful issuance advances the case
    `PENDING_ISSUANCE → ACTIVE`; every subsequent issuance leaves it `ACTIVE`."
    PRD §3.5: "The assignment must be `PROPOSED`, or the request is refused with
    `ERR_INVALID_ASSIGNMENT_STATE`."

    Design: Difficulty/cross_entity_state_dependency/assignment_activation_blocked_by_case_benefit_status_pending_issuance
    """
    context, assignment_id = _approved_case_with_a_proposed_activity(api)
    api.activate_work_assignment(assignment_id, work_specialist_headers())

    fx.issue_month(api, context.case_id, "2026-08")
    asrt.assert_case_state(fx.read_case(api, context.case_id), benefit_status="ACTIVE")

    fx.activate_assignment(api, assignment_id)

    assert fx.read_assignment(api, assignment_id)["status"] == "ACTIVE"


def _calculated_quarter_with_one_submitted_report_inside_it(api):
    """FY2027 Q1 calculated, with an unverified November report still open."""
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Cross Entity Two Household"},
        incomes=EARNED_ONLY,
    )
    assignment = fx.create_active_assignment(
        api,
        context.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=30,
        start_date="2026-08-01",
        end_date="2027-02-01",
    )
    report = fx.file_report(
        api,
        assignment["id"],
        report_month="2026-11",
        reported_hours=120,
        verification_source="TIMESHEET",
    )
    fx.set_clock(api, "2027-01-05T00:00:00Z")
    period = fx.open_period(
        api,
        fiscal_year=2027,
        quarter=1,
        prior_year_caseload=1.00,
        eligibility_change_caseload_effect=0.00,
    )
    fx.calculate_period(api, period["id"])
    return period["id"], report["id"]


def test_certification_is_blocked_by_an_unverified_report_inside_the_quarter(api):
    """PRD §3.10: "And no participation report may still be sitting in `SUBMITTED`
    with a `report_month` inside the period's three months, because an unverified
    report could still change the numerator; such a period is refused with
    `ERR_UNVERIFIED_REPORTS_IN_QUARTER`."
    PRD §3.10: "Each run records the acting analyst in `calculated_by_user_id`."

    Design: Difficulty/cross_entity_state_dependency/reporting_period_certification_blocked_by_a_submitted_report_in_another_entity
    """
    period_id, _report_id = _calculated_quarter_with_one_submitted_report_inside_it(api)

    response = api.certify_reporting_period(period_id, analyst_headers(ANALYST_ALT_ID))

    asrt.assert_rejected(response, errs.ERR_UNVERIFIED_REPORTS_IN_QUARTER)
    period = fx.read_period(api, period_id)
    assert period["status"] == "CALCULATED"
    assert period["certified_by_user_id"] is None
    assert period["calculated_by_user_id"] == ANALYST_ID


def test_verifying_that_report_unblocks_the_identical_certification(api):
    """PRD §3.10: "It advances the period `CALCULATED → CERTIFIED`; a period still
    `OPEN` or already `CERTIFIED` is refused with `ERR_INVALID_PERIOD_STATE`."
    PRD §3.10: "On success the acting analyst is recorded in `certified_by_user_id`,
    and the period's figures are frozen."

    Design: Difficulty/cross_entity_state_dependency/reporting_period_certification_blocked_by_a_submitted_report_in_another_entity
    """
    period_id, report_id = _calculated_quarter_with_one_submitted_report_inside_it(api)
    api.certify_reporting_period(period_id, analyst_headers(ANALYST_ALT_ID))

    fx.verify_report(api, report_id, 120)
    fx.certify_period(api, period_id, ANALYST_ALT_ID)

    period = fx.read_period(api, period_id)
    assert period["status"] == "CERTIFIED"
    assert period["certified_by_user_id"] == ANALYST_ALT_ID


def _held_authorization_on_a_conciliating_case(api):
    """A shortfall cascade has held the service money and opened an episode."""
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Cross Entity Three Household"},
        incomes=EARNED_ONLY,
    )
    assignment = fx.create_active_assignment(
        api,
        context.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=20,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    authorization = fx.request_authorization(
        api,
        context.case_id,
        assignment["id"],
        service_type="TRANSPORTATION",
        requested_amount_cents=20000,
    )
    fx.credit_hours(api, assignment["id"], "2026-08", 40)
    episodes = fx.search_episodes(api, case_id=context.case_id)
    assert len(episodes) == 1, f"expected one system episode, got {len(episodes)}"
    fx.start_conciliation(api, episodes[0]["id"])
    return context, assignment["id"], authorization["id"], episodes[0]["id"]


def test_hold_release_is_blocked_by_the_case_compliance_status(api):
    """PRD §3.8: "A `WorkProgramSpecialist` releases one by moving it
    `HELD → REQUESTED`, which is permitted only once the case's `compliance_status`
    has returned to `ASSIGNED`, `EXEMPT` or `NOT_REQUIRED`; a case still in
    `CONCILIATION_PENDING`, `SANCTIONED` or `CURE_PENDING` is refused with
    `ERR_ASSIGNMENT_NOT_ACTIVE`, and a row that is not `HELD` is refused with
    `ERR_INVALID_AUTHORIZATION_STATE`."

    Design: Difficulty/cross_entity_state_dependency/hold_release_blocked_by_case_compliance_status_on_a_different_entity
    """
    context, assignment_id, authorization_id, _episode_id = _held_authorization_on_a_conciliating_case(
        api
    )

    response = api.release_supportive_hold(authorization_id, work_specialist_headers())

    asrt.assert_rejected(response, errs.ERR_ASSIGNMENT_NOT_ACTIVE)
    asrt.assert_authorization(fx.read_authorization(api, authorization_id), status="HELD")
    assert fx.read_assignment(api, assignment_id)["status"] == "ACTIVE"
    asrt.assert_case_state(
        fx.read_case(api, context.case_id), compliance_status="CONCILIATION_PENDING"
    )


def test_good_cause_on_the_episode_lets_the_same_release_through(api):
    """PRD §3.7: "The episode moves `CONCILIATION → GOOD_CAUSE_GRANTED`, its own
    `sanction_level` returns to 0 and its `sanction_pct` to 0.00, the case's
    `compliance_status` becomes `EXEMPT`, and the case's sanction rollup and
    `benefit_amount_cents` are recomputed."
    PRD §3.8: "The pair `REQUESTED → HELD → REQUESTED` is therefore a genuine cycle,
    and a released row can go on to be authorized normally."

    Design: Difficulty/cross_entity_state_dependency/hold_release_blocked_by_case_compliance_status_on_a_different_entity
    """
    context, _assignment_id, authorization_id, episode_id = _held_authorization_on_a_conciliating_case(
        api
    )
    api.release_supportive_hold(authorization_id, work_specialist_headers())

    fx.grant_good_cause(api, episode_id, good_cause_reason="NO_CHILD_CARE_AVAILABLE")
    assert fx.read_episode(api, episode_id)["status"] == "GOOD_CAUSE_GRANTED"
    asrt.assert_case_state(fx.read_case(api, context.case_id), compliance_status="EXEMPT")

    fx.release_hold(api, authorization_id)

    asrt.assert_authorization(
        fx.read_authorization(api, authorization_id),
        status="REQUESTED",
        authorized_amount_cents=0,
    )
