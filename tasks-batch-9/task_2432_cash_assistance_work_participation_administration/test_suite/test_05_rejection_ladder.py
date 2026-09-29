"""Requests that violate two rules at once and must report the higher one."""
from test_helpers import SUPERVISOR_ID, supervisor_headers, work_specialist_headers
from test_helpers import api_errors as errs
from test_helpers import assertions as asrt
from test_helpers import factories, fixtures as fx

STANDARD_INCOMES = (
    {
        "source_type": "EARNED",
        "gross_monthly_cents": 40000,
        "is_recurring": True,
        "verification_status": "VERIFIED",
    },
)


def _exhausted_transportation_cap_and_a_proposed_activity(api):
    """Transportation headroom fully committed, with a request on a PROPOSED activity."""
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Priority Pair One Household"},
        incomes=STANDARD_INCOMES,
    )
    running = fx.create_active_assignment(
        api,
        context.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=20,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    proposed = fx.create_assignment(
        api,
        context.case_id,
        activity_category="WORK_EXPERIENCE",
        scheduled_weekly_hours=20,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    committed = fx.build_authorized_service(
        api,
        context.case_id,
        running["id"],
        service_type="TRANSPORTATION",
        requested_amount_cents=60000,
    )
    blocked = fx.request_authorization(
        api,
        context.case_id,
        proposed["id"],
        service_type="TRANSPORTATION",
        requested_amount_cents=10000,
        period_start="2026-09-01",
        period_end="2026-09-30",
    )
    return context, committed["id"], blocked["id"]


def test_inactive_activity_is_reported_before_the_exhausted_cap(api):
    """PRD §3.8: "The authorization must be `REQUESTED`, or the request is refused
    with `ERR_INVALID_AUTHORIZATION_STATE`, and the owning work assignment must by
    then be `ACTIVE`, or the request is refused with `ERR_ASSIGNMENT_NOT_ACTIVE`."
    PRD §2.8: "When a request violates several rules at once, exactly one error is
    returned and it is always the violation with the lowest ladder position below."

    Design: Difficulty/priority_pair_validation_conflict/assignment_state_outranks_supportive_cap_exhaustion_on_authorize
    """
    _context, _committed_id, blocked_id = _exhausted_transportation_cap_and_a_proposed_activity(
        api
    )

    response = api.authorize_supportive(blocked_id, work_specialist_headers())

    asrt.assert_rejected(response, errs.ERR_ASSIGNMENT_NOT_ACTIVE)


def test_the_rejected_authorize_consumes_no_supportive_headroom(api):
    """PRD §3.8: "Only a waterfall result of exactly zero is a failure: it is
    refused with `ERR_SUPPORTIVE_CAP_EXHAUSTED`, the authorization stays
    `REQUESTED`, and no cap is consumed."
    PRD §3.8: "The per-service-type caps are 60000 cents for transportation, 240000
    cents for child care and 30000 cents for work expenses."

    Design: Difficulty/priority_pair_validation_conflict/assignment_state_outranks_supportive_cap_exhaustion_on_authorize
    """
    context, committed_id, blocked_id = _exhausted_transportation_cap_and_a_proposed_activity(
        api
    )

    api.authorize_supportive(blocked_id, work_specialist_headers())

    asrt.assert_authorization(
        fx.read_authorization(api, blocked_id),
        status="REQUESTED",
        authorized_amount_cents=0,
    )
    asrt.assert_authorization(
        fx.read_authorization(api, committed_id),
        status="AUTHORIZED",
        authorized_amount_cents=60000,
    )
    case = fx.read_case(api, context.case_id)
    asrt.assert_money(
        case["supportive_fy_authorized_cents"], 60000, "supportive fiscal-year total"
    )


def _application_over_both_the_clock_and_the_resource_limit(api):
    """A determined application whose household is out of state months and over-resourced."""
    household = fx.create_household(
        api, head_of_household_name="Priority Pair Two Household"
    )
    fx.record_prior_assistance(
        api, household["id"], state_clock_months=24, federal_clock_months=24
    )
    application = fx.create_application(api, household["id"])
    fx.add_income_source(
        api,
        application["id"],
        verification_status="VERIFIED",
        source_type="EARNED",
        gross_monthly_cents=40000,
    )
    fx.add_income_source(
        api,
        application["id"],
        verification_status="VERIFIED",
        source_type="UNEARNED_CHILD_SUPPORT",
        gross_monthly_cents=20000,
    )
    fx.add_resource_item(
        api, application["id"], item_type="LIQUID_ASSET", gross_value_cents=250000
    )
    fx.determine(api, application["id"])
    return household["id"], application["id"]


def test_time_limit_exhaustion_is_reported_before_the_resource_limit(api):
    """PRD §3.3: "The household's `state_clock_months_used` must be below the
    24-month state limit, unless a `GRANTED` hardship extension on any case of that
    household covers the supplied `certification_start_month`; failing both, the
    request is refused with `ERR_TIME_LIMIT_EXHAUSTED`."
    PRD §2.8: "**Program safety rules** — in this relative order:
    `ERR_TIME_LIMIT_EXHAUSTED`, then `ERR_CONCILIATION_NOT_COMPLETE`, then
    `ERR_GOOD_CAUSE_ACTIVE`, then `ERR_EXTENSION_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/time_limit_exhaustion_outranks_resource_limit_on_approve
    """
    _household_id, application_id = _application_over_both_the_clock_and_the_resource_limit(api)

    response = api.approve_application(
        application_id, factories.approve_payload("2026-08"), supervisor_headers()
    )

    asrt.assert_rejected(response, errs.ERR_TIME_LIMIT_EXHAUSTED)


def test_the_refused_approval_mints_no_case_and_leaves_the_application_determined(api):
    """PRD §3.3: "The application's `countable_resources_cents` must not exceed the
    program resource limit of 200000 cents — exactly at the limit is eligible, and
    strictly above it is refused with `ERR_RESOURCE_LIMIT_EXCEEDED`."
    PRD §3.3: "When all five hold, approval advances the application
    `DETERMINED → APPROVED`, records the acting user in `decided_by_user_id`, and
    mints a new **assistance case**, which is the response body of the approval."

    Design: Difficulty/priority_pair_validation_conflict/time_limit_exhaustion_outranks_resource_limit_on_approve
    """
    _household_id, application_id = _application_over_both_the_clock_and_the_resource_limit(api)

    api.approve_application(
        application_id, factories.approve_payload("2026-08"), supervisor_headers()
    )

    application = fx.read_application(api, application_id)
    assert application["status"] == "DETERMINED"
    asrt.assert_money(
        application["countable_resources_cents"], 250000, "countable resources"
    )
    asrt.assert_money(
        application["determined_benefit_cents"], 17000, "determined benefit"
    )
    assert fx.search_cases(api, application_id=application_id) == []


def _two_cases_one_holding_an_august_transportation_request(api):
    """Case A already covers all of August; case B has its own running activity."""
    case_a = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Case A Household"},
        incomes=STANDARD_INCOMES,
    )
    assignment_a = fx.create_active_assignment(
        api,
        case_a.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=20,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    existing = fx.request_authorization(
        api,
        case_a.case_id,
        assignment_a["id"],
        service_type="TRANSPORTATION",
        requested_amount_cents=20000,
        period_start="2026-08-01",
        period_end="2026-08-31",
    )
    case_b = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Case B Household"},
        incomes=STANDARD_INCOMES,
    )
    assignment_b = fx.create_active_assignment(
        api,
        case_b.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=20,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    return case_a, existing["id"], assignment_b["id"]


def _crossed_authorization_payload(api, case_a, foreign_assignment_id):
    return factories.supportive_authorization_payload(
        case_a.case_id,
        foreign_assignment_id,
        fx.case_version(api, case_a.case_id),
        service_type="TRANSPORTATION",
        requested_amount_cents=15000,
        period_start="2026-08-15",
        period_end="2026-08-20",
    )


def test_period_overlap_is_reported_before_the_assignment_case_mismatch(api):
    """PRD §3.8: "At create time the candidate period must not overlap any other
    authorization of the same case with the same `service_type` whose status is
    `REQUESTED`, `HELD` or `AUTHORIZED`; an overlap is refused with
    `ERR_SERVICE_PERIOD_OVERLAP`."
    PRD §2.8: "**Temporal and uniqueness rules** — in this relative order:
    `ERR_DIVERSION_INELIGIBILITY_ACTIVE`, then `ERR_SERVICE_PERIOD_OVERLAP`, then
    `ERR_DUPLICATE_ISSUANCE_MONTH`, then `ERR_DUPLICATE_REPORT_MONTH`, then
    `ERR_REPORT_MONTH_OUTSIDE_ASSIGNMENT`."

    Design: Difficulty/priority_pair_validation_conflict/service_period_overlap_outranks_assignment_case_mismatch_on_create
    """
    case_a, _existing_id, foreign_assignment_id = _two_cases_one_holding_an_august_transportation_request(
        api
    )
    payload = _crossed_authorization_payload(api, case_a, foreign_assignment_id)

    response = api.create_supportive_authorization(payload, work_specialist_headers())

    asrt.assert_rejected(response, errs.ERR_SERVICE_PERIOD_OVERLAP)


def test_the_refused_creation_adds_no_authorization_and_bumps_no_case_version(api):
    """PRD §3.8: "The referenced assignment must belong to the referenced case; a
    mismatch between the assignment's own case and the `case_id` supplied is refused
    with `ERR_WORK_ASSIGNMENT_CASE_MISMATCH`."
    PRD §2.8: "This ordering is part of the contract: a test that supplies both an
    unknown role and a nonexistent path identifier expects the role error, not the
    not-found error."

    Design: Difficulty/priority_pair_validation_conflict/service_period_overlap_outranks_assignment_case_mismatch_on_create
    """
    case_a, existing_id, foreign_assignment_id = _two_cases_one_holding_an_august_transportation_request(
        api
    )
    version_before = fx.case_version(api, case_a.case_id)
    payload = _crossed_authorization_payload(api, case_a, foreign_assignment_id)

    api.create_supportive_authorization(payload, work_specialist_headers())

    rows = fx.search_authorizations(api, case_id=case_a.case_id)
    assert [row["id"] for row in rows] == [existing_id], (
        f"expected only the pre-existing authorization, got {[row['id'] for row in rows]}"
    )
    assert fx.case_version(api, case_a.case_id) == version_before


def _application_determined_by_its_would_be_approver(api):
    """A determined, over-resourced application whose determiner will also approve."""
    household = fx.create_household(
        api, head_of_household_name="Priority Pair Four Household"
    )
    application = fx.create_application(api, household["id"])
    fx.add_income_source(
        api,
        application["id"],
        verification_status="VERIFIED",
        source_type="EARNED",
        gross_monthly_cents=40000,
    )
    fx.add_resource_item(
        api, application["id"], item_type="LIQUID_ASSET", gross_value_cents=250000
    )
    fx.determine(api, application["id"], determiner=SUPERVISOR_ID)
    return application["id"]


def test_segregation_of_duties_is_reported_before_the_resource_limit(api):
    """PRD §3.3: "The acting user must differ from the recorded
    `determined_by_user_id`, or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.8: "**Fiscal rules**, evaluated last and in this relative order:
    `ERR_RESOURCE_LIMIT_EXCEEDED`, then `ERR_INELIGIBLE_ZERO_BENEFIT`, then
    `ERR_SUPPORTIVE_CAP_EXHAUSTED`, then `ERR_RECOVERY_EXCEEDS_BALANCE`, then
    `ERR_REVERSAL_EXCEEDS_RECOVERED`, then `ERR_DIVERSION_REQUIRES_BENEFIT`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_resource_limit_on_approve
    """
    application_id = _application_determined_by_its_would_be_approver(api)

    response = api.approve_application(
        application_id,
        factories.approve_payload("2026-08"),
        supervisor_headers(SUPERVISOR_ID),
    )

    asrt.assert_rejected(response, errs.ERR_SEGREGATION_OF_DUTIES)


def test_the_same_actor_refusal_records_no_decision_on_the_application(api):
    """PRD §2.8: "**Segregation of duties** — the different-actor checks described
    in §2.1; `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.2: "On success the determination freezes the household's current
    `family_type` into the application's `snapshot_family_type`, computes
    `countable_income_cents`, computes `countable_resources_cents`, computes
    `determined_benefit_cents` with the sanction fraction held at 0.00, and records
    the acting user in `determined_by_user_id`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_resource_limit_on_approve
    """
    application_id = _application_determined_by_its_would_be_approver(api)

    api.approve_application(
        application_id,
        factories.approve_payload("2026-08"),
        supervisor_headers(SUPERVISOR_ID),
    )

    application = fx.read_application(api, application_id)
    assert application["status"] == "DETERMINED"
    assert application["determined_by_user_id"] == SUPERVISOR_ID
    assert application["decided_by_user_id"] is None
