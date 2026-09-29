"""Aggregate eligibility, recertified snapshots and the two fiscal rungs."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as asserts
from test_helpers import constants as const
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_service_member_headers

BEFORE_ARRIVAL_CLOCK = fx.CLOCK_BEFORE_ARRIVAL
ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["property_manager_headers"]
HOUSING_OFFICE = TEST_USERS["installation_housing_office_headers"]
SPECIALIST = TEST_USERS["environmental_specialist_headers"]

UNACCOMPANIED_SPONSOR = {"dodid": "1000000001", "last_name": "Reyes", "first_name": "Ana"}
SECOND_SPONSOR = {"dodid": "1000000002", "last_name": "Okafor", "first_name": "Dele"}
PART_TIME_DAUGHTER = {
    "relationship": "CHILD",
    "date_of_birth": "2019-11-02",
    "gender": "FEMALE",
    "is_full_time_custody": False,
}
FULL_TIME_SPOUSE = {
    "relationship": "SPOUSE",
    "date_of_birth": "1992-03-04",
    "gender": "MALE",
    "is_full_time_custody": True,
}
LATER_ARRIVAL = {"expected_arrival_date": "2026-09-15"}
EARLIER_ORDERS = {
    "pcs_orders_date": "2026-08-20",
    "expected_arrival_date": "2026-09-10",
}


def test_family_housing_eligibility_counts_custody_and_forbids_a_second_application(api):
    """A part-time child is not a qualifying dependent, and one list is one seat.

    PRD: "Rung 35 requires the sponsor to have at least one full-time-custody dependent, because unaccompanied members are not eligible for family housing; it guards waitlist application creation, failing with `ERR_NOT_ELIGIBLE_FAMILY_HOUSING` (422)."

    Design: Corner/validations/family_housing_eligibility_counts_custody_and_forbids_a_second_application
    """
    fx.set_clock(api, BEFORE_ARRIVAL_CLOCK)
    installation = fx.create_installation(api)
    unaccompanied = fx.create_service_member(api, **UNACCOMPANIED_SPONSOR)
    unaccompanied_headers = make_service_member_headers(unaccompanied["id"])
    housed_family, _ = fx.setup_sponsor_family(api, **SECOND_SPONSOR)
    fx.submit_application(api, installation["id"], housed_family)
    payload = f.create_waitlist_application_payload(
        installation["id"], unaccompanied["id"], **LATER_ARRIVAL
    )

    validate_error(
        api.create_waitlist_application(payload, unaccompanied_headers),
        ApiErrorId.ERR_NOT_ELIGIBLE_FAMILY_HOUSING,
        422,
    )

    fx.create_dependent(api, unaccompanied["id"], **PART_TIME_DAUGHTER)

    # The part-time row exists and still does not qualify the sponsor.
    validate_error(
        api.create_waitlist_application(payload, unaccompanied_headers),
        ApiErrorId.ERR_NOT_ELIGIBLE_FAMILY_HOUSING,
        422,
    )
    validate_error(
        api.create_waitlist_application(
            f.create_waitlist_application_payload(
                installation["id"], housed_family["id"], **EARLIER_ORDERS
            ),
            make_service_member_headers(housed_family["id"]),
        ),
        ApiErrorId.ERR_DUPLICATE_ACTIVE_APPLICATION,
        422,
    )

    fx.create_dependent(api, unaccompanied["id"], **FULL_TIME_SPOUSE)
    admitted = validate_success(
        api.create_waitlist_application(payload, unaccompanied_headers), 201
    )

    assert admitted["status"] == "PENDING"
    assert admitted["dependent_count_at_application"] == 1
    # One qualifying dependent, and the floor of one bedroom applies.
    assert admitted["bedroom_eligibility"] == const.MIN_BEDROOMS
    installation_after = fx.read_installation(api, installation["id"])
    assert installation_after["pending_application_count"] == 2


TWIN_UNITS = ({"unit_code": "A-101"}, {"unit_code": "A-102"})
ELDER_SON = {
    "relationship": "CHILD",
    "date_of_birth": "2014-05-01",
    "gender": "MALE",
    "is_full_time_custody": True,
}
PROMOTION = {"pay_grade": "E7"}


def test_bedroom_and_rank_gates_read_the_recertified_snapshot_not_the_offer(api):
    """Each lease is refused against the very unit its own offer reserved.

    PRD: "Rung 37 requires the unit's `bedroom_count` to equal the application's `bedroom_eligibility`; it guards lease creation, failing with `ERR_BEDROOM_MISMATCH` (422)."

    Design: Corner/validations/bedroom_and_rank_gates_read_the_recertified_snapshot_not_the_offer
    """
    fx.set_clock(api, BEFORE_ARRIVAL_CLOCK)
    installation = fx.create_installation(api)
    fx.create_bah_rate(api, installation["id"])
    grown_family_unit, promoted_unit = [
        fx.create_housing_unit(api, installation["id"], **spec) for spec in TWIN_UNITS
    ]
    grown_sponsor, _ = fx.setup_sponsor_family(api)
    grown_application = fx.submit_application(
        api, installation["id"], grown_sponsor, **EARLIER_ORDERS
    )
    promoted_sponsor, _ = fx.setup_sponsor_family(api, **SECOND_SPONSOR)
    promoted_application = fx.submit_application(
        api, installation["id"], promoted_sponsor
    )
    fx.run_offer_run(api, installation["id"])
    grown_accepted = fx.accept_offer(api, grown_application["id"], grown_sponsor)
    promoted_accepted = fx.accept_offer(api, promoted_application["id"], promoted_sponsor)
    # Each application really does hold the offer on the unit it is now refused.
    assert grown_accepted["offered_unit_id"] == grown_family_unit["id"]
    assert promoted_accepted["offered_unit_id"] == promoted_unit["id"]

    fx.create_dependent(api, grown_sponsor["id"], **ELDER_SON)
    recertified_family = validate_success(
        api.recertify_waitlist_application(
            grown_application["id"],
            f.recertify_payload(grown_accepted["version"]),
            HOUSING_OFFICE,
        )
    )
    assert recertified_family["bedroom_eligibility"] == 3
    assert recertified_family["rank_category"] == "JUNIOR_ENLISTED"

    promoted = validate_success(
        api.record_orders(
            promoted_sponsor["id"], f.record_orders_payload(**PROMOTION), HOUSING_OFFICE
        )
    )
    assert promoted["rank_category"] == "SENIOR_ENLISTED"
    recertified_rank = validate_success(
        api.recertify_waitlist_application(
            promoted_application["id"],
            f.recertify_payload(promoted_accepted["version"]),
            HOUSING_OFFICE,
        )
    )
    assert recertified_rank["rank_category"] == "SENIOR_ENLISTED"
    assert recertified_rank["bedroom_eligibility"] == 2

    # Unit bedroom_count 2 against an entitlement of 3.
    validate_error(
        api.create_lease(
            f.create_lease_payload(grown_application["id"], grown_family_unit["id"]),
            MANAGER,
        ),
        ApiErrorId.ERR_BEDROOM_MISMATCH,
        422,
    )
    # The rank rung answers before the fiscal rung that would also fail for
    # want of an E7 rate row.
    validate_error(
        api.create_lease(
            f.create_lease_payload(promoted_application["id"], promoted_unit["id"]),
            MANAGER,
        ),
        ApiErrorId.ERR_RANK_CATEGORY_MISMATCH,
        422,
    )


LEAD_WATER_REPORT = {
    "hazard_type": "LEAD_WATER",
    "reported_symptoms": "Tap water tested high for lead at the kitchen sink",
}
LEAD_WATER_MEASUREMENT = {"lead_level_ppm": 15}
AUTHORISED_OCCUPANTS = 5
OVER_CAP_OCCUPANTS = 6
LODGING_WINDOW = {
    "start_date": "2026-09-02",
    "end_date": "2026-09-09",
    "nightly_rate_cents": 31000,
}


def test_lodging_occupants_may_not_exceed_two_plus_the_custody_count(api):
    """Six is one over the cap for a three-dependent family; five is exact.

    PRD: "Rung 39 requires the lodging's `occupants_count` not to exceed two plus the sponsor's full-time-custody dependent count; it guards lodging authorisation, failing with `ERR_OCCUPANTS_EXCEED_AUTHORIZED` (422)."

    Design: Corner/validations/lodging_occupants_may_not_exceed_two_plus_the_custody_count
    """
    state = fx.setup_assessed_hazard(
        api,
        report_overrides=LEAD_WATER_REPORT,
        assess_overrides=LEAD_WATER_MEASUREMENT,
    )
    hazard = state["hazard_case"]
    assert hazard["assessment_severity"] == "SEVERITY_3"
    assert hazard["displacement_required"] is True
    assert hazard["status"] == "DISPLACEMENT_ACTIVE"
    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "HAZARD_HOLD"
    assert fx.read_lease(api, state["lease"]["id"])["allotment_status"] == "SUSPENDED"

    validate_error(
        api.create_displacement_lodging(
            f.create_displacement_lodging_payload(
                hazard["id"],
                state["lease"]["id"],
                occupants_count=OVER_CAP_OCCUPANTS,
                **LODGING_WINDOW,
            ),
            MANAGER,
        ),
        ApiErrorId.ERR_OCCUPANTS_EXCEED_AUTHORIZED,
        422,
    )

    lodging = validate_success(
        api.create_displacement_lodging(
            f.create_displacement_lodging_payload(
                hazard["id"],
                state["lease"]["id"],
                occupants_count=AUTHORISED_OCCUPANTS,
                **LODGING_WINDOW,
            ),
            MANAGER,
        ),
        201,
    )

    assert lodging["status"] == "AUTHORIZED"
    assert lodging["occupants_count"] == AUTHORISED_OCCUPANTS
    assert lodging["actual_end_date"] is None
    # Every figure waits for the closure that computes it.
    assert lodging["nights_displaced"] == 0
    assert lodging["per_night_authorized_cents"] == 0
    assert lodging["lodging_authorized_cents"] == 0
    assert lodging["rent_abatement_cents"] == 0
    asserts.assert_displacement_lodging(lodging)


THIN_ACCOUNT = {
    "opening_balance_cents": 300000,
    "occupancy_basis": "MONTH_END_SNAPSHOT",
}
WHOLE_BALANCE_CENTS = 300000
ONE_CENT_OVERDRAW_CENTS = 300001
ONE_CENT = 1


def test_an_expenditure_may_not_overdraw_the_reinvestment_account(api):
    """One cent over is refused, the whole balance is allowed, then nothing is left.

    PRD: "Rung 46 requires the requested expenditure not to exceed the account's `closing_balance_cents`; it guards operator-initiated expenditure authorisation only and is never applied to the expenditure that the lodging-closure cascade writes, failing with `ERR_REINVESTMENT_BALANCE_INSUFFICIENT` (422)."

    Design: Corner/validations/an_expenditure_may_not_overdraw_the_reinvestment_account
    """
    fx.set_clock(api, BEFORE_ARRIVAL_CLOCK)
    installation = fx.create_installation(api)
    account = fx.create_reinvestment_account(api, installation["id"], **THIN_ACCOUNT)
    assert account["closing_balance_cents"] == WHOLE_BALANCE_CENTS
    assert account["expenditures_cents"] == 0

    validate_error(
        api.authorize_expenditure(
            account["id"],
            f.expenditure_payload(account["version"], ONE_CENT_OVERDRAW_CENTS),
            MANAGER,
        ),
        ApiErrorId.ERR_REINVESTMENT_BALANCE_INSUFFICIENT,
        422,
    )
    # The refusal left the token and the balance exactly as they were.
    assert fx.read_account(api, account["id"])["version"] == account["version"]

    drained = validate_success(
        api.authorize_expenditure(
            account["id"],
            f.expenditure_payload(account["version"], WHOLE_BALANCE_CENTS),
            MANAGER,
        )
    )

    assert drained["expenditures_cents"] == WHOLE_BALANCE_CENTS
    assert drained["closing_balance_cents"] == 0
    assert drained["version"] == account["version"] + 1
    asserts.assert_reinvestment_account(drained)

    # An empty account refuses even a single cent.
    validate_error(
        api.authorize_expenditure(
            account["id"], f.expenditure_payload(drained["version"], ONE_CENT), MANAGER
        ),
        ApiErrorId.ERR_REINVESTMENT_BALANCE_INSUFFICIENT,
        422,
    )


SEPTEMBER = "2026-09"
OCTOBER = "2026-10"
NOVEMBER = "2026-11"
ALLOTMENT_RUN_CLOCK = "2026-09-30T00:00:00Z"
FIRST_METRICS_CLOCK = "2026-10-01T00:00:00Z"
SECOND_METRICS_CLOCK = "2026-11-01T00:00:00Z"
FULL_OCCUPANCY_PCT = 100.00
NO_ESCALATION_PENALTY_PCT = 0.00
CLEAN_INCENTIVE_FEE_CENTS = 8181
SEPTEMBER_CONTRIBUTION_CENTS = 21815
CLOSING_AFTER_SEPTEMBER_CENTS = 5021815


def test_a_metrics_period_may_be_run_once_and_never_ahead_of_the_clock(api):
    """The same code covers the replayed period and the period that has not happened.

    PRD: "Rung 44 requires that no metrics run has already been recorded for this reinvestment account and `period_month`, and that the requested period is not in the future relative to the logical clock; it guards the metrics run, failing with `ERR_PERIOD_ALREADY_POSTED` (409)."

    Design: Corner/validations/a_metrics_period_may_be_run_once_and_never_ahead_of_the_clock
    """
    state = fx.setup_account(api, occupied_state=fx.setup_occupied_lease(api))
    account = state["account"]
    fx.set_clock(api, ALLOTMENT_RUN_CLOCK)
    fx.run_allotment_run(api, state["installation"]["id"], SEPTEMBER)
    fx.set_clock(api, FIRST_METRICS_CLOCK)

    first = validate_success(
        api.run_metrics_run(account["id"], f.metrics_run_payload(SEPTEMBER), MANAGER)
    )
    assert first["metrics_run_epoch"] == 1
    assert first["occupancy_rate_pct"] == FULL_OCCUPANCY_PCT
    assert first["net_collected_cents"] == const.BASE_NET_RENT_CENTS
    assert first["habitability_penalty_pct"] == NO_ESCALATION_PENALTY_PCT
    # round_half_up(218150 * 0.03) = 6545, then round_half_up(6545 * 1.25).
    assert first["performance_incentive_fee_cents"] == CLEAN_INCENTIVE_FEE_CENTS
    assert first["contributions_cents"] == SEPTEMBER_CONTRIBUTION_CENTS
    assert first["closing_balance_cents"] == CLOSING_AFTER_SEPTEMBER_CENTS

    # September is spent for this account.
    validate_error(
        api.run_metrics_run(account["id"], f.metrics_run_payload(SEPTEMBER), MANAGER),
        ApiErrorId.ERR_PERIOD_ALREADY_POSTED,
        409,
    )
    # November has not happened yet at a clock of 2026-10-01.
    validate_error(
        api.run_metrics_run(account["id"], f.metrics_run_payload(NOVEMBER), ADMIN),
        ApiErrorId.ERR_PERIOD_ALREADY_POSTED,
        409,
    )
    assert fx.read_account(api, account["id"])["metrics_run_epoch"] == 1

    fx.set_clock(api, SECOND_METRICS_CLOCK)
    second = validate_success(
        api.run_metrics_run(account["id"], f.metrics_run_payload(OCTOBER), ADMIN)
    )

    assert second["metrics_run_epoch"] == 2
    asserts.assert_instant_equals(second["last_metrics_run_at"], SECOND_METRICS_CLOCK)
    assert second["occupancy_rate_pct"] == FULL_OCCUPANCY_PCT
    # No allotment run posted an October row, so October collected nothing.
    assert second["net_collected_cents"] == 0
    assert second["performance_incentive_fee_cents"] == 0
    assert second["contributions_cents"] == SEPTEMBER_CONTRIBUTION_CENTS
    assert second["closing_balance_cents"] == CLOSING_AFTER_SEPTEMBER_CENTS


WRONG_YEAR_RATE = {"effective_year": 2025}
WRONG_DEPENDENTS_RATE = {"with_dependents": False}


def test_the_rate_row_must_match_all_four_parts_of_its_key(api):
    """A row for the wrong year and a row for the wrong household both miss.

    PRD: "Rung 45 requires that a `BahRate` row exist for the combination of `installation_id`, `pay_grade`, `with_dependents` and `effective_year` that the active rent variant selects; it guards lease creation, move-in and rent redetermination, failing with `ERR_BAH_RATE_NOT_ON_FILE` (422)."

    Design: Corner/validations/the_rate_row_must_match_all_four_parts_of_its_key
    """
    fx.set_clock(api, BEFORE_ARRIVAL_CLOCK)
    installation = fx.create_installation(api)
    unit = fx.create_housing_unit(api, installation["id"])
    sponsor, _ = fx.setup_sponsor_family(api)
    application = fx.submit_application(api, installation["id"], sponsor)
    fx.run_offer_run(api, installation["id"])
    accepted = fx.accept_offer(api, application["id"], sponsor)
    lease_payload = f.create_lease_payload(application["id"], unit["id"])
    # The provisional variant reads the control date's year and the snapshot count.
    assert accepted["effective_control_date"] == "2026-08-25"
    assert accepted["dependent_count_at_application"] == 3

    validate_error(
        api.create_lease(lease_payload, MANAGER),
        ApiErrorId.ERR_BAH_RATE_NOT_ON_FILE,
        422,
    )

    fx.create_bah_rate(api, installation["id"], **WRONG_YEAR_RATE)
    validate_error(
        api.create_lease(lease_payload, MANAGER),
        ApiErrorId.ERR_BAH_RATE_NOT_ON_FILE,
        422,
    )

    fx.create_bah_rate(api, installation["id"], **WRONG_DEPENDENTS_RATE)
    validate_error(
        api.create_lease(lease_payload, MANAGER),
        ApiErrorId.ERR_BAH_RATE_NOT_ON_FILE,
        422,
    )

    fx.create_bah_rate(api, installation["id"])
    lease = validate_success(api.create_lease(lease_payload, MANAGER), 201)

    assert lease["gross_rent_cents"] == const.BASE_GROSS_RENT_CENTS
    assert lease["utility_allowance_cents"] == const.BASE_UTILITY_ALLOWANCE_CENTS
    assert lease["net_rent_cents"] == const.BASE_NET_RENT_CENTS
    assert lease["rent_effective_year"] == 2026
    assert lease["rent_basis"] == "OFFER_PROVISIONAL"
