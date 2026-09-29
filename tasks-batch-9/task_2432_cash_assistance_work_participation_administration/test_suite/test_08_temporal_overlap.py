"""Date ranges whose endpoint conventions decide whether two rows collide."""
from test_helpers import caseworker_headers, work_specialist_headers
from test_helpers import api_errors as errs
from test_helpers import assertions as asrt
from test_helpers import factories, fixtures as fx

EARNED_ONLY = (
    {
        "source_type": "EARNED",
        "gross_monthly_cents": 40000,
        "is_recurring": True,
        "verification_status": "VERIFIED",
    },
)


def _case_holding_an_august_transportation_period(api):
    """One REQUESTED transportation period covering the whole of August."""
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Temporal One Household"},
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
    august = fx.request_authorization(
        api,
        context.case_id,
        assignment["id"],
        service_type="TRANSPORTATION",
        requested_amount_cents=20000,
        period_start="2026-08-01",
        period_end="2026-08-31",
    )
    return context, assignment["id"], august["id"]


def test_a_shared_endpoint_day_collides_but_the_following_day_does_not(api):
    """PRD §3.8: "Unlike work assignment intervals, service periods are **closed and
    inclusive** at both ends."
    PRD §3.8: "A period starting 2026-10-01 therefore belongs to fiscal year 2027,
    while one starting 2026-09-30 belongs to fiscal year 2026."

    Design: Difficulty/resource_temporal_overlap/supportive_service_periods_are_closed_inclusive_so_shared_endpoints_collide
    """
    context, assignment_id, _august_id = _case_holding_an_august_transportation_period(api)
    version = fx.case_version(api, context.case_id)

    response = api.create_supportive_authorization(
        factories.supportive_authorization_payload(
            context.case_id,
            assignment_id,
            version,
            service_type="TRANSPORTATION",
            requested_amount_cents=10000,
            period_start="2026-08-31",
            period_end="2026-09-15",
        ),
        work_specialist_headers(),
    )

    asrt.assert_rejected(response, errs.ERR_SERVICE_PERIOD_OVERLAP)

    september = fx.request_authorization(
        api,
        context.case_id,
        assignment_id,
        service_type="TRANSPORTATION",
        requested_amount_cents=10000,
        period_start="2026-09-01",
        period_end="2026-09-30",
    )

    stored = fx.read_authorization(api, september["id"])
    assert stored["period_start"] == "2026-09-01"
    asrt.assert_authorization(stored, status="REQUESTED", fiscal_year=2026)


def test_the_period_collision_is_scoped_to_a_single_service_type(api):
    """PRD §3.8: "At create time the candidate period must not overlap any other
    authorization of the same case with the same `service_type` whose status is
    `REQUESTED`, `HELD` or `AUTHORIZED`; an overlap is refused with
    `ERR_SERVICE_PERIOD_OVERLAP`."
    PRD §3.8: "A new authorization opens in `status` `REQUESTED` with
    `authorized_amount_cents` at 0 and `void_reason` null."

    Design: Difficulty/resource_temporal_overlap/supportive_service_periods_are_closed_inclusive_so_shared_endpoints_collide
    """
    context, assignment_id, august_id = _case_holding_an_august_transportation_period(api)
    fx.request_authorization(
        api,
        context.case_id,
        assignment_id,
        service_type="TRANSPORTATION",
        requested_amount_cents=10000,
        period_start="2026-09-01",
        period_end="2026-09-30",
    )

    child_care = fx.request_authorization(
        api,
        context.case_id,
        assignment_id,
        service_type="CHILD_CARE",
        requested_amount_cents=30000,
        period_start="2026-08-10",
        period_end="2026-08-20",
    )

    stored = fx.read_authorization(api, child_care["id"])
    assert stored["service_type"] == "CHILD_CARE"
    asrt.assert_authorization(stored, status="REQUESTED", authorized_amount_cents=0)
    transportation = fx.search_authorizations(
        api, case_id=context.case_id, service_type="TRANSPORTATION"
    )
    assert len(transportation) == 2, (
        f"expected two transportation periods, got "
        f"{[(row['period_start'], row['period_end']) for row in transportation]}"
    )
    assert len(fx.search_authorizations(api, case_id=context.case_id)) == 3
    asrt.assert_authorization(fx.read_authorization(api, august_id), status="REQUESTED")


def _case_with_two_adjacent_assignments(api, name):
    """A 35-hour activity ending the same day a 20-hour activity begins."""
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": name},
        incomes=EARNED_ONLY,
    )
    first = fx.create_assignment(
        api,
        context.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=35,
        start_date="2026-08-01",
        end_date="2026-10-01",
    )
    second = fx.create_assignment(
        api,
        context.case_id,
        activity_category="WORK_EXPERIENCE",
        scheduled_weekly_hours=20,
        start_date="2026-10-01",
        end_date="2026-12-01",
    )
    return context, first["id"], second["id"]


def test_adjacent_half_open_ranges_do_not_share_scheduling_capacity(api):
    """PRD §3.5: "Assignment date ranges are **half-open**: the interval runs from the
    `start_date` inclusive up to but not including the `end_date`."
    PRD §3.5: "The practical consequence is that an assignment ending on 2026-10-01
    and another starting on 2026-10-01 do *not* overlap, and both may carry a full
    schedule."

    Design: Difficulty/resource_temporal_overlap/work_assignment_ranges_are_half_open_and_capacity_sums_only_the_overlapping_set
    """
    context, first_id, second_id = _case_with_two_adjacent_assignments(
        api, "Temporal Two A Household"
    )
    assert fx.read_assignment(api, first_id)["is_core"] is True
    assert fx.read_assignment(api, second_id)["status"] == "PROPOSED"

    third = fx.create_assignment(
        api,
        context.case_id,
        activity_category="SECONDARY_SCHOOL",
        scheduled_weekly_hours=25,
        start_date="2026-10-01",
        end_date="2026-11-01",
    )

    assert fx.read_assignment(api, third["id"])["is_core"] is False
    assert len(fx.list_assignments(api, context.case_id)) == 3


def test_capacity_admits_exactly_sixty_overlapping_hours_and_refuses_one_more(api):
    """PRD §3.5: "For the candidate assignment, the system totals the candidate's own
    `scheduled_weekly_hours` with the `scheduled_weekly_hours` of every *other* work
    assignment of the same case that is in `PROPOSED` or `ACTIVE` status and that
    overlaps the candidate's interval."
    PRD §3.5: "If that total exceeds 60 hours per week the operation is refused with
    `ERR_SCHEDULED_HOURS_CAPACITY_EXCEEDED`; a total of exactly 60 is allowed."

    Design: Difficulty/resource_temporal_overlap/work_assignment_ranges_are_half_open_and_capacity_sums_only_the_overlapping_set
    """
    context, _first_id, _second_id = _case_with_two_adjacent_assignments(
        api, "Temporal Two B Household"
    )

    at_the_limit = fx.create_assignment(
        api,
        context.case_id,
        activity_category="JOB_SEARCH_READINESS",
        scheduled_weekly_hours=25,
        start_date="2026-09-01",
        end_date="2026-09-15",
    )
    assert fx.read_assignment(api, at_the_limit["id"])["scheduled_weekly_hours"] == 25

    response = api.create_work_assignment(
        context.case_id,
        factories.work_assignment_payload(
            activity_category="VOCATIONAL_EDUCATION",
            scheduled_weekly_hours=1,
            start_date="2026-09-05",
            end_date="2026-09-10",
        ),
        work_specialist_headers(),
    )

    asrt.assert_rejected(response, errs.ERR_SCHEDULED_HOURS_CAPACITY_EXCEEDED)
    assert len(fx.list_assignments(api, context.case_id)) == 3


DIVERSION_INCOMES = (
    {
        "source_type": "EARNED",
        "gross_monthly_cents": 40000,
        "is_recurring": True,
        "verification_status": "VERIFIED",
    },
    {
        "source_type": "UNEARNED_CHILD_SUPPORT",
        "gross_monthly_cents": 20000,
        "is_recurring": True,
        "verification_status": "VERIFIED",
    },
)


def _household_inside_an_accepted_diversion_window(api, name):
    """A three-month ineligibility window running through 2026-10."""
    built = fx.build_determined_application(
        api,
        household_overrides={"head_of_household_name": name},
        application_overrides={"requested_program": "DIVERSION_CONSIDERED"},
        incomes=DIVERSION_INCOMES,
    )
    household_id = built["household"]["id"]
    application_id = built["application"]["id"]
    grant = fx.offer_diversion(api, application_id)
    fx.accept_diversion(api, grant["id"], household_id)
    return household_id, application_id, grant["id"]


def test_diversion_lump_sum_sizes_an_inclusive_three_month_window(api):
    """PRD §3.3: "The `lump_sum_cents` is three times the basis, capped at 200000
    cents, taking whichever is smaller."
    PRD §3.3: "The `ineligibility_end_month` is the application's `application_month`
    advanced by one month fewer than the ineligibility month count, so a one-month
    window ends in the application month itself and the recorded end month is
    inclusive."
    PRD §3.3: "Accepting it moves the grant `OFFERED → ACCEPTED` and the application
    `DIVERSION_OFFERED → DIVERTED`, and writes the grant's `ineligibility_end_month`
    onto the household as `diversion_ineligible_through_month`."

    Design: Difficulty/resource_temporal_overlap/diversion_ineligibility_window_blocks_the_last_covered_month_but_not_the_next
    """
    household_id, application_id, grant_id = _household_inside_an_accepted_diversion_window(
        api, "Temporal Three Household"
    )

    grant = fx.read_diversion_grant(api, application_id, grant_id)

    asrt.assert_money(grant["monthly_benefit_basis_cents"], 17000, "basis")
    asrt.assert_money(grant["lump_sum_cents"], 51000, "lump sum")
    assert grant["ineligibility_months"] == 3
    assert grant["ineligibility_end_month"] == "2026-10"
    assert grant["status"] == "ACCEPTED"
    household = fx.read_household(api, household_id)
    assert household["diversion_ineligible_through_month"] == "2026-10"


def test_the_window_blocks_its_end_month_and_releases_the_month_after(api):
    """PRD §3.2: "It is refused from any other status with
    `ERR_INVALID_APPLICATION_STATE`, and it is refused with
    `ERR_DIVERSION_INELIGIBILITY_ACTIVE` when the household is inside a diversion
    ineligibility window — that is, when `diversion_ineligible_through_month` is set
    and the application's `application_month` is not strictly later than it; the first
    month after the window passes."
    PRD §3.3: "No assistance case is created, no time-limit month is consumed, and the
    household is barred from a further determination for any month at or before that
    recorded end month — a determination for a month inside the window is refused with
    `ERR_DIVERSION_INELIGIBILITY_ACTIVE`, while the first month strictly after it
    proceeds normally."

    Design: Difficulty/resource_temporal_overlap/diversion_ineligibility_window_blocks_the_last_covered_month_but_not_the_next
    """
    household_id, _application_id, _grant_id = _household_inside_an_accepted_diversion_window(
        api, "Temporal Three Later Household"
    )
    october = fx.create_application(api, household_id, application_month="2026-10")
    november = fx.create_application(api, household_id, application_month="2026-11")
    for income in DIVERSION_INCOMES:
        fx.add_income_source(api, november["id"], **income)

    response = api.determine_application(october["id"], caseworker_headers())

    asrt.assert_rejected(response, errs.ERR_DIVERSION_INELIGIBILITY_ACTIVE)
    assert fx.read_application(api, october["id"])["status"] == "RECEIVED"

    fx.determine(api, november["id"])

    determined = fx.read_application(api, november["id"])
    assert determined["status"] == "DETERMINED"
    asrt.assert_money(
        determined["determined_benefit_cents"], 17000, "determined benefit"
    )
