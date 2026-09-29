"""Initial states, terminal states, refused transitions and cycles."""
from test_helpers import SUPERVISOR_ALT_ID, caseworker_headers, supervisor_headers
from test_helpers import api_errors as errs
from test_helpers import assertions as asrt
from test_helpers import factories, fixtures as fx


def test_a_new_application_starts_undetermined(api):
    """PRD §3.1: "A new application lands in `status` `RECEIVED`; the full lifecycle
    domain is `RECEIVED`, `DETERMINED`, `DIVERSION_OFFERED`, `APPROVED`, `DENIED`,
    `DIVERTED` and `WITHDRAWN`, of which the last four are terminal."
    PRD §3.1: "Before the determination runs, `snapshot_family_type`,
    `countable_income_cents`, `countable_resources_cents`, `determined_benefit_cents`,
    `determined_by_user_id` and `decided_by_user_id` are all null, `denial_reason` is
    `NONE`, and `withdrawal_reason` is null."

    Design: Corner/state_machines/newly_created_application_starts_in_received
    """
    household = fx.create_household(
        api, head_of_household_name="Corner Initial State Household"
    )

    response = api.file_application(
        factories.application_payload(
            household["id"], budgeting_method="RETROSPECTIVE"
        ),
        caseworker_headers(),
    )

    application = asrt.assert_accepted(response, expected_status=201)
    assert application["status"] == "RECEIVED"
    assert application["budgeting_method"] == "RETROSPECTIVE"
    assert application["countable_income_cents"] is None
    assert application["determined_benefit_cents"] is None
    assert application["determined_by_user_id"] is None
    assert application["denial_reason"] == "NONE"


def test_a_withdrawn_application_can_no_longer_be_determined(api):
    """PRD §3.3: "Withdrawal is available to the applicant itself and to a
    `Caseworker`, and is the only disposition reachable from more than one status: an
    application may be withdrawn while it is `RECEIVED`, `DETERMINED` or
    `DIVERSION_OFFERED`, and any other status is refused with
    `ERR_INVALID_APPLICATION_STATE`."
    PRD §3.2: "Running the **determination** is a `Caseworker` action that advances the
    application `RECEIVED → DETERMINED`."

    Design: Corner/state_machines/withdrawn_application_cannot_be_determined
    """
    household = fx.create_household(
        api, head_of_household_name="Corner Withdrawn Household"
    )
    application = fx.create_application(api, household["id"])
    asrt.assert_accepted(
        api.withdraw_application(
            application["id"],
            factories.withdraw_payload("MOVED_OUT_OF_STATE"),
            caseworker_headers(),
        )
    )

    response = api.determine_application(application["id"], caseworker_headers())

    asrt.assert_rejected(response, errs.ERR_INVALID_APPLICATION_STATE)
    stored = fx.read_application(api, application["id"])
    assert stored["status"] == "WITHDRAWN"
    assert stored["countable_income_cents"] is None


def test_a_denied_application_is_terminal_and_mints_no_case(api):
    """PRD §3.3: "A supervisor different from the determiner moves the application
    `DETERMINED → DENIED` and supplies a `denial_reason`, which is one of `NONE`,
    `RESOURCES_OVER_LIMIT`, `ZERO_BENEFIT`, `TIME_LIMIT`, `FAILURE_TO_COOPERATE` or
    `OTHER`."
    PRD §3.3: "Nothing else changes and no case is created."

    Design: Corner/state_machines/denied_application_is_terminal_and_rejects_approve
    """
    built = fx.build_determined_application(
        api,
        household_overrides={"head_of_household_name": "Corner Denied Household"},
        incomes=(),
    )
    application_id = built["application"]["id"]
    asrt.assert_accepted(
        api.deny_application(
            application_id,
            factories.deny_payload("FAILURE_TO_COOPERATE"),
            supervisor_headers(),
        )
    )

    response = api.approve_application(
        application_id,
        factories.approve_payload("2026-08"),
        supervisor_headers(SUPERVISOR_ALT_ID),
    )

    asrt.assert_rejected(response, errs.ERR_INVALID_APPLICATION_STATE)
    stored = fx.read_application(api, application_id)
    assert stored["status"] == "DENIED"
    assert stored["denial_reason"] == "FAILURE_TO_COOPERATE"
    assert fx.search_cases(api, application_id=application_id) == []


def test_a_second_issuance_of_the_same_month_is_refused_and_double_counts_nothing(api):
    """PRD §3.4: "A second issuance for a benefit month the case has already issued is
    refused with `ERR_DUPLICATE_ISSUANCE_MONTH` — the pair of case and benefit month is
    unique."
    PRD §3.4: "The first successful issuance advances the case
    `PENDING_ISSUANCE → ACTIVE`; every subsequent issuance leaves it `ACTIVE`."

    Design: Corner/state_machines/duplicate_issuance_for_the_same_benefit_month_is_refused
    """
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Corner Duplicate Issuance Household"},
        incomes=(),
    )

    response = api.issue_month(
        context.case_id, factories.issuance_payload("2026-08"), caseworker_headers()
    )

    asrt.assert_rejected(response, errs.ERR_DUPLICATE_ISSUANCE_MONTH)
    rows = fx.list_time_limit_months(api, context.case_id)
    assert len(rows) == 1
    asrt.assert_time_limit_month(rows[0], benefit_month="2026-08", assistance_issued=True)
    asrt.assert_household_clocks(
        fx.read_household(api, context.household_id),
        state_clock_months_used=1,
        federal_clock_months_used=1,
        issued_countable_months=1,
    )
    asrt.assert_case_state(fx.read_case(api, context.case_id), benefit_status="ACTIVE")


def test_good_cause_is_refused_before_conciliation_has_started(api):
    """PRD §3.7: "A new episode opens in `status` `ALLEGED` with
    `conciliation_start_date` and `conciliation_deadline_date` null, `sanction_level` 0,
    `sanction_pct` 0.00, `sanction_imposed_month` null, `good_cause_reason` `NONE` and
    `cure_plan_note` null."
    PRD §3.7: "The episode moves `CONCILIATION → GOOD_CAUSE_GRANTED`, its own
    `sanction_level` returns to 0 and its `sanction_pct` to 0.00, the case's
    `compliance_status` becomes `EXEMPT`, and the case's sanction rollup and
    `benefit_amount_cents` are recomputed."
    PRD §3.7: "A successful referral puts the case's `compliance_status` into
    `CONCILIATION_PENDING` and increments the case's `version` by one."

    Design: Corner/state_machines/good_cause_grant_before_conciliation_starts_is_refused
    """
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Corner Good Cause Household"},
        incomes=(),
    )
    episode = fx.open_episode(
        api, context.case_id, allegation_reason="REFUSED_ASSIGNMENT"
    )

    response = api.grant_good_cause(
        episode["id"], factories.good_cause_payload("ILLNESS"), supervisor_headers()
    )

    asrt.assert_rejected(response, errs.ERR_INVALID_EPISODE_STATE)
    stored = fx.read_episode(api, episode["id"])
    assert stored["status"] == "ALLEGED"
    assert stored["origin"] == "CASEWORKER_REFERRAL"
    assert stored["good_cause_reason"] == "NONE"
    assert stored["sanction_level"] == 0
    asrt.assert_case_state(
        fx.read_case(api, context.case_id), compliance_status="CONCILIATION_PENDING"
    )


def test_rejecting_a_report_credits_nothing_and_opens_no_episode(api):
    """PRD §3.6: "A `WorkProgramSpecialist` moves a `SUBMITTED` report to `REJECTED`
    with a free-text `rejection_reason`, and the report's `verified_hours`,
    `core_hours_credited` and `non_core_hours_credited` are all set to 0."
    PRD §3.6: "A rejected report never enters the participation predicate and never
    enters the federal rate numerator."

    Design: Corner/state_machines/rejecting_a_participation_report_leaves_cumulative_hours_unchanged
    """
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Corner Reject Report Household"},
        incomes=(),
    )
    assignment = fx.create_active_assignment(
        api,
        context.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=20,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    report = fx.file_report(
        api,
        assignment["id"],
        report_month="2026-08",
        reported_hours=100,
        verification_source="SELF_REPORT",
    )

    fx.reject_report(api, report["id"], rejection_reason="DOCUMENTATION_ILLEGIBLE")

    asrt.assert_report_credits(
        fx.read_report(api, assignment["id"], report["id"]),
        status="REJECTED",
        verified_hours=0,
        core_hours_credited=0,
        non_core_hours_credited=0,
    )
    stored = fx.read_assignment(api, assignment["id"])
    assert stored["cumulative_verified_hours"] == 0
    assert stored["compliance_flag"] == "NONE"
    asrt.assert_case_state(fx.read_case(api, context.case_id), compliance_status="ASSIGNED")
    assert fx.search_episodes(api, case_id=context.case_id) == []


def test_declining_an_offer_returns_the_application_to_determined(api):
    """PRD §3.3: "Declining instead moves the grant `OFFERED → DECLINED`, stores the
    supplied free-text `decline_reason`, and cycles the application
    `DIVERSION_OFFERED → DETERMINED` so that ongoing assistance can still be approved
    from the same determination; no ineligibility window is created by a decline."
    PRD §3.3: "The `ineligibility_months` count is the lump sum divided by the basis and
    rounded up to a whole month, capped at 12 months, again taking whichever is
    smaller."

    Design: Corner/state_machines/declining_a_diversion_offer_cycles_the_application_back_to_determined
    """
    built = fx.build_determined_application(
        api,
        household_overrides={"head_of_household_name": "Corner Decline Diversion Household"},
        application_overrides={"requested_program": "DIVERSION_CONSIDERED"},
        incomes=(),
    )
    household_id = built["household"]["id"]
    application_id = built["application"]["id"]
    grant = fx.offer_diversion(api, application_id)

    fx.decline_diversion(
        api, grant["id"], household_id, decline_reason="PREFERS_ONGOING_ASSISTANCE"
    )

    stored = fx.read_diversion_grant(api, application_id, grant["id"])
    assert stored["status"] == "DECLINED"
    asrt.assert_money(stored["lump_sum_cents"], 124950, "lump sum")
    assert stored["ineligibility_months"] == 3
    assert fx.read_application(api, application_id)["status"] == "DETERMINED"
    household = fx.read_household(api, household_id)
    assert household["diversion_ineligible_through_month"] is None

    case = fx.approve(api, application_id)

    asrt.assert_case_state(case, benefit_amount_cents=41650)
    assert fx.read_application(api, application_id)["status"] == "APPROVED"
