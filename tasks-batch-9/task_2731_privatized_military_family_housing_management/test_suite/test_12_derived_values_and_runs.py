"""Derived categories, filtered input sets, run waterfalls and rounding."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as asserts
from test_helpers import constants as const
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

STARTUP_CLOCK = const.CLOCK_STARTUP_DEFAULT
BEFORE_ARRIVAL_CLOCK = fx.CLOCK_BEFORE_ARRIVAL
ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["property_manager_headers"]
HOUSING_OFFICE = TEST_USERS["installation_housing_office_headers"]
SPECIALIST = TEST_USERS["environmental_specialist_headers"]

GRADE_TO_CATEGORY = (
    ("2000000006", "Ibarra", "Luz", "ARMY", "E6", "JUNIOR_ENLISTED"),
    ("2000000007", "Nakamura", "Ken", "ARMY", "E7", "SENIOR_ENLISTED"),
    ("2000000002", "Boone", "Rae", "ARMY", "W2", "WARRANT_OFFICER"),
    ("2000000003", "Duarte", "Iva", "NAVY", "O3", "JUNIOR_OFFICER"),
    ("2000000004", "Ellison", "Cy", "NAVY", "O4", "SENIOR_OFFICER"),
)


def test_the_rank_category_is_derived_at_both_seniority_floors(api):
    """E6 against E7 and O3 against O4, with every W grade skipping the floors.

    PRD: "For a grade beginning with `E`, the category is `JUNIOR_ENLISTED` when that integer is at most 6, and `SENIOR_ENLISTED` from 7 upward — so `E6` is junior enlisted and `E7` is senior enlisted."

    Design: Corner/calculations/rank_category_is_derived_at_both_seniority_floors
    """
    fx.set_clock(api, STARTUP_CLOCK)
    fx.create_installation(api)

    last = None
    for dodid, last_name, first_name, branch, pay_grade, expected in GRADE_TO_CATEGORY:
        headers = HOUSING_OFFICE if pay_grade.startswith("W") else ADMIN
        sponsor = validate_success(
            api.create_service_member(
                f.create_service_member_payload(
                    dodid=dodid,
                    last_name=last_name,
                    first_name=first_name,
                    branch=branch,
                    pay_grade=pay_grade,
                ),
                headers,
            ),
            201,
        )
        assert sponsor["rank_category"] == expected, pay_grade
        assert sponsor["dependent_count"] == 0
        assert sponsor["deployment_status"] == "NOT_DEPLOYED"
        assert sponsor["pcs_orders_ref"] is None
        assert sponsor["deployment_orders_ref"] is None
        last = sponsor

    # The category is stored on the row, not recomputed on each read.
    reread = validate_success(api.get_service_member(last["id"], MANAGER))
    assert reread["rank_category"] == "SENIOR_OFFICER"


FULL_CUSTODY_FAMILY = (
    {
        "relationship": "SPOUSE",
        "date_of_birth": "1992-03-04",
        "gender": "FEMALE",
        "is_full_time_custody": True,
    },
    {
        "relationship": "CHILD",
        "date_of_birth": "2014-05-01",
        "gender": "MALE",
        "is_full_time_custody": True,
    },
    {
        "relationship": "CHILD",
        "date_of_birth": "2018-04-10",
        "gender": "MALE",
        "is_full_time_custody": True,
    },
)
PART_CUSTODY_FAMILY = (
    {
        "relationship": "SPOUSE",
        "date_of_birth": "1990-06-06",
        "gender": "MALE",
        "is_full_time_custody": True,
    },
    {
        "relationship": "CHILD",
        "date_of_birth": "2018-04-10",
        "gender": "MALE",
        "is_full_time_custody": True,
    },
    {
        "relationship": "CHILD",
        "date_of_birth": "2022-03-15",
        "gender": "MALE",
        "is_full_time_custody": True,
    },
    {
        "relationship": "CHILD",
        "date_of_birth": "2019-11-02",
        "gender": "FEMALE",
        "is_full_time_custody": False,
    },
)
CONTROL_DATE = "2026-08-25"
LATER_ARRIVAL = {"expected_arrival_date": "2026-09-15"}


def test_bedroom_eligibility_counts_only_full_time_custody_dependents(api):
    """A twelve-year-old buys a private room; a part-time daughter buys nothing.

    PRD: "Consider only the sponsor's dependents whose `is_full_time_custody` is true; part-time-custody dependents are excluded from the calculation entirely, and so are dependents added after the snapshot was taken unless a recertification re-runs the rule."

    Design: Corner/calculations/bedroom_eligibility_counts_only_full_time_custody_dependents
    """
    fx.set_clock(api, BEFORE_ARRIVAL_CLOCK)
    installation = fx.create_installation(api)
    sponsor_a, _ = fx.setup_sponsor_family(api, dependents=FULL_CUSTODY_FAMILY)
    sponsor_b, _ = fx.setup_sponsor_family(
        api,
        dependents=PART_CUSTODY_FAMILY,
        dodid="1000000002",
        last_name="Okafor",
        first_name="Dele",
    )

    application_a = fx.submit_application(
        api, installation["id"], sponsor_a, **LATER_ARRIVAL
    )
    application_b = fx.submit_application(
        api, installation["id"], sponsor_b, **LATER_ARRIVAL
    )

    # Base one, a private bedroom for the twelve-year-old, one shared bedroom.
    assert application_a["bedroom_eligibility"] == 3
    assert application_a["dependent_count_at_application"] == 3
    assert application_a["effective_control_date"] == CONTROL_DATE
    assert application_a["rank_category"] == "JUNIOR_ENLISTED"
    # Base one plus one shared bedroom for the two boys under ten.
    assert application_b["bedroom_eligibility"] == 2
    assert application_b["dependent_count_at_application"] == 3
    assert validate_success(api.get_service_member(sponsor_b["id"], MANAGER))[
        "dependent_count"
    ] == 3
    # The fourth row exists and was filtered by the rule, not missing.
    _, dependents_meta = validate_paginated(
        api.list_service_member_dependents(sponsor_b["id"], MANAGER)
    )
    assert dependents_meta["total_count"] == 4


WATERFALL_INVENTORY = (
    {
        "unit_code": "B-200",
        "bedroom_count": 3,
        "unit_type": "SFH",
        "designated_rank_category": "SENIOR_ENLISTED",
        "historic_flag": False,
    },
    {
        "unit_code": "A-101",
        "bedroom_count": 2,
        "unit_type": "TOWNHOME",
        "designated_rank_category": "JUNIOR_ENLISTED",
        "historic_flag": False,
    },
)
THREE_BEDROOM_FAMILY = (
    {"relationship": "SPOUSE", "date_of_birth": "1988-01-09", "gender": "MALE"},
    {"relationship": "CHILD", "date_of_birth": "2014-05-01", "gender": "MALE"},
    {"relationship": "CHILD", "date_of_birth": "2018-04-10", "gender": "MALE"},
)
LATEST_CONTROL_DATE = {
    "pcs_orders_date": "2026-08-25",
    "expected_arrival_date": "2026-09-15",
}
EARLIEST_CONTROL_DATE = {
    "pcs_orders_date": "2026-08-20",
    "expected_arrival_date": "2026-09-10",
}
MIDDLE_CONTROL_DATE = {
    "pcs_orders_date": "2026-08-22",
    "expected_arrival_date": "2026-09-12",
}
SECOND_SPONSOR = {"dodid": "1000000002", "last_name": "Okafor", "first_name": "Dele"}
SENIOR_SPONSOR = {
    "dodid": "1000000003",
    "last_name": "Vance",
    "first_name": "Mia",
    "pay_grade": "E7",
}
OFFER_EXPIRES_AT = "2026-08-28T00:00:00Z"


def test_the_offer_run_walks_units_smallest_first_and_offers_each_its_own_winner(api):
    """The two-bedroom unit is served first although it was created second.

    PRD: "The run considers only that installation's units whose `status` is `AVAILABLE`, and it visits them ordered by `bedroom_count` ascending, breaking ties by `created_at` ascending."

    Design: Corner/calculations/offer_run_walks_units_smallest_first_and_offers_each_to_its_own_winner
    """
    state = fx.setup_multi_unit_installation(
        api, WATERFALL_INVENTORY, clock=BEFORE_ARRIVAL_CLOCK
    )
    installation_id = state["installation"]["id"]
    three_bedroom_unit, two_bedroom_unit = state["units"]

    sponsor_one, _ = fx.setup_sponsor_family(api)
    application_one = fx.submit_application(
        api, installation_id, sponsor_one, **LATEST_CONTROL_DATE
    )
    sponsor_two, _ = fx.setup_sponsor_family(api, **SECOND_SPONSOR)
    application_two = fx.submit_application(
        api, installation_id, sponsor_two, **EARLIEST_CONTROL_DATE
    )
    sponsor_three, _ = fx.setup_sponsor_family(
        api, dependents=THREE_BEDROOM_FAMILY, **SENIOR_SPONSOR
    )
    application_three = fx.submit_application(
        api, installation_id, sponsor_three, **MIDDLE_CONTROL_DATE
    )
    assert application_three["bedroom_eligibility"] == 3
    assert application_three["rank_category"] == "SENIOR_ENLISTED"

    first_run = fx.run_offer_run(api, installation_id)

    assert first_run["offer_run_epoch"] == 1
    asserts.assert_instant_equals(
        first_run["last_offer_run_at"], BEFORE_ARRIVAL_CLOCK
    )
    assert first_run["available_unit_count"] == 0
    assert first_run["assigned_unit_count"] == 2
    assert first_run["pending_application_count"] == 1

    # The earliest control date took the townhome, not the first applicant.
    winner = fx.read_application(api, application_two["id"])
    assert winner["status"] == "OFFERED"
    assert winner["offered_unit_id"] == two_bedroom_unit["id"]
    asserts.assert_instant_equals(winner["offer_expires_at"], OFFER_EXPIRES_AT)
    assert winner["offer_count"] == 1

    # The only three-bedroom senior-enlisted match took the SFH.
    senior = fx.read_application(api, application_three["id"])
    assert senior["status"] == "OFFERED"
    assert senior["offered_unit_id"] == three_bedroom_unit["id"]

    # Matched the two-bedroom pool, lost the ranking, no second unit that size.
    loser = fx.read_application(api, application_one["id"])
    assert loser["status"] == "PENDING"
    assert loser["offered_unit_id"] is None
    assert loser["offer_count"] == 0

    second_run = validate_success(
        api.run_waitlist_offer_run(installation_id, HOUSING_OFFICE)
    )

    # A walk over zero AVAILABLE units is a success, not an error.
    assert second_run["offer_run_epoch"] == 2
    assert second_run["available_unit_count"] == 0
    assert second_run["assigned_unit_count"] == 2
    still_pending = fx.read_application(api, application_one["id"])
    assert still_pending["status"] == "PENDING"
    assert still_pending["offer_count"] == 0


MOVE_IN_CLOCK = fx.CLOCK_AT_MOVE_IN
SECOND_UNIT = {"unit_code": "A-102"}
SECOND_TENANCY_SPONSOR = {
    "dodid": "1000000002",
    "last_name": "Okafor",
    "first_name": "Dele",
}
SECOND_LEASE_START = {"start_date": "2026-09-05"}
SEPTEMBER = "2026-09"
OCTOBER = "2026-10"
TWO_MONTH_BALANCE_CENTS = 436300


def _one_active_lease_and_one_not_started(api):
    """An occupied tenancy plus a written-but-unoccupied lease on a second unit."""
    state = fx.setup_occupied_lease(api)
    installation_id = state["installation"]["id"]
    second_unit = fx.create_housing_unit(api, installation_id, **SECOND_UNIT)
    sponsor, _ = fx.setup_sponsor_family(api, **SECOND_TENANCY_SPONSOR)
    application = fx.submit_application(api, installation_id, sponsor)
    fx.run_offer_run(api, installation_id)
    accepted = fx.accept_offer(api, application["id"], sponsor)
    assert accepted["offered_unit_id"] == second_unit["id"]
    state["second_lease"] = fx.write_lease(
        api, application["id"], second_unit["id"], **SECOND_LEASE_START
    )
    return state


def test_the_allotment_run_charges_only_active_leases_once_per_period(api):
    """A lease that has not moved in is outside the input set; a replay is a no-op.

    PRD: "For each eligible lease, if a `CHARGE` row already exists for that lease and that `period_month` the lease is skipped, which makes a repeat run for the same period a no-op and guarantees at most one charge row per lease per period."

    Design: Corner/calculations/allotment_run_charges_only_active_leases_and_is_idempotent_per_period
    """
    state = _one_active_lease_and_one_not_started(api)
    installation_id = state["installation"]["id"]
    lease_id = state["lease"]["id"]
    second_lease_id = state["second_lease"]["id"]
    assert state["second_lease"]["occupancy_status"] == "PENDING_MOVE_IN"
    assert state["second_lease"]["allotment_status"] == "NOT_STARTED"

    fx.run_allotment_run(api, installation_id, SEPTEMBER)

    charged = fx.read_lease(api, lease_id)
    assert charged["allotment_status"] == "ACTIVE"
    assert charged["allotment_balance_cents"] == const.BASE_NET_RENT_CENTS
    skipped = fx.read_lease(api, second_lease_id)
    assert skipped["allotment_status"] == "NOT_STARTED"
    assert skipped["allotment_balance_cents"] == 0
    _, skipped_meta = validate_paginated(
        api.list_lease_allotment_transactions(second_lease_id, MANAGER)
    )
    assert skipped_meta["total_count"] == 0

    fx.run_allotment_run(api, installation_id, SEPTEMBER, headers=ADMIN)

    september_rows, september_meta = validate_paginated(
        api.list_lease_allotment_transactions(
            lease_id, MANAGER, params={"period_month": SEPTEMBER}
        )
    )
    assert september_meta["total_count"] == 1
    assert september_rows[0]["running_balance_cents"] == const.BASE_NET_RENT_CENTS

    fx.run_allotment_run(api, installation_id, OCTOBER)

    ledger, ledger_meta = validate_paginated(
        api.list_lease_allotment_transactions(lease_id, MANAGER)
    )
    assert ledger_meta["total_count"] == 2
    october_row = ledger[1]
    assert october_row["period_month"] == OCTOBER
    assert october_row["amount_cents"] == const.BASE_NET_RENT_CENTS
    assert october_row["running_balance_cents"] == TWO_MONTH_BALANCE_CENTS
    final = fx.read_lease(api, lease_id)
    assert final["allotment_balance_cents"] == TWO_MONTH_BALANCE_CENTS
    assert fx.read_lease(api, second_lease_id)["allotment_balance_cents"] == 0
    asserts.assert_ledger_conservation(ledger, final)


TWO_ADJUSTED_UNIT_TYPES = (
    {"unit_code": "A-201", "unit_type": "APARTMENT"},
    {"unit_code": "A-301", "unit_type": "DUPLEX"},
)
APARTMENT_GROSS_CENTS = 232750
APARTMENT_NET_CENTS = 213250
APARTMENT_DAILY_CENTS = 7011
DUPLEX_GROSS_CENTS = 240100
DUPLEX_NET_CENTS = 220600
DUPLEX_DAILY_CENTS = 7253


def test_the_daily_rent_rate_rounds_half_up_on_two_unit_types(api):
    """Both leases land on a fraction that truncation would round the wrong way.

    PRD: "The stored `daily_rent_cents` is `net_rent_cents` multiplied by 12 and divided by 365, rounded half up to whole cents."

    Design: Corner/calculations/daily_rent_rate_rounds_half_up_on_two_unit_types
    """
    fx.set_clock(api, BEFORE_ARRIVAL_CLOCK)
    installation = fx.create_installation(api)
    fx.create_bah_rate(api, installation["id"])
    apartment, duplex = [
        fx.create_housing_unit(api, installation["id"], **spec)
        for spec in TWO_ADJUSTED_UNIT_TYPES
    ]

    sponsor_one, _ = fx.setup_sponsor_family(api)
    application_one = fx.submit_application(
        api, installation["id"], sponsor_one, **EARLIEST_CONTROL_DATE
    )
    sponsor_two, _ = fx.setup_sponsor_family(api, **SECOND_SPONSOR)
    application_two = fx.submit_application(
        api, installation["id"], sponsor_two, **LATEST_CONTROL_DATE
    )
    fx.run_offer_run(api, installation["id"])
    assert fx.accept_offer(api, application_one["id"], sponsor_one)[
        "offered_unit_id"
    ] == apartment["id"]
    assert fx.accept_offer(api, application_two["id"], sponsor_two)[
        "offered_unit_id"
    ] == duplex["id"]

    apartment_lease = fx.write_lease(api, application_one["id"], apartment["id"])
    duplex_lease = fx.write_lease(api, application_two["id"], duplex["id"])

    # 245000 reduced by the APARTMENT adjustment of five percent.
    assert apartment_lease["gross_rent_cents"] == APARTMENT_GROSS_CENTS
    assert apartment_lease["utility_allowance_cents"] == const.BASE_UTILITY_ALLOWANCE_CENTS
    assert apartment_lease["net_rent_cents"] == APARTMENT_NET_CENTS
    # round_half_up(7010.96): truncation would store 7010.
    assert apartment_lease["daily_rent_cents"] == APARTMENT_DAILY_CENTS
    # 245000 reduced by the DUPLEX adjustment of two percent.
    assert duplex_lease["gross_rent_cents"] == DUPLEX_GROSS_CENTS
    assert duplex_lease["net_rent_cents"] == DUPLEX_NET_CENTS
    # round_half_up(7252.60): truncation would store 7252.
    assert duplex_lease["daily_rent_cents"] == DUPLEX_DAILY_CENTS

    # Both rates are stored, not recomputed on each read.
    assert fx.read_lease(api, apartment_lease["id"])["daily_rent_cents"] == (
        APARTMENT_DAILY_CENTS
    )
    assert fx.read_lease(api, duplex_lease["id"])["daily_rent_cents"] == (
        DUPLEX_DAILY_CENTS
    )


NO_HEAT_CLOCK = "2026-09-05T00:00:00Z"
ESCALATION_CLOCK = "2026-09-06T00:00:00Z"
COLLECTION_CLOCK = "2026-09-30T00:00:00Z"
METRICS_CLOCK = "2026-10-01T00:00:00Z"
FURNACE_DESCRIPTION = "Furnace will not ignite"
FULL_MONTH_OCCUPANCY_PCT = 100.00
ONE_ESCALATION_PENALTY_PCT = 0.05
INCENTIVE_FEE_CENTS = 7772
CONTRIBUTION_CENTS = 21815
CLOSING_BALANCE_CENTS = 5021815


def test_the_metrics_run_applies_the_incentive_band_and_the_escalation_penalty(api):
    """A full house at the top band, docked one step for one escalated order.

    PRD: "The stored `performance_incentive_fee_cents` is the base fee multiplied by the occupancy multiplier and then by one minus the habitability penalty fraction, rounded half up to whole cents — so a project with an occupancy rate below 85 earns nothing regardless of collections, and a project with ten escalated orders in the period loses half of what it would otherwise earn."

    Design: Corner/calculations/metrics_run_applies_the_incentive_band_and_the_escalation_penalty
    """
    state = fx.setup_occupied_lease(api)
    installation_id = state["installation"]["id"]
    account = fx.create_reinvestment_account(api, installation_id)

    fx.set_clock(api, NO_HEAT_CLOCK)
    order = fx.submit_work_order(
        api,
        state["unit"]["id"],
        headers=MANAGER,
        lease_id=state["lease"]["id"],
        category="NO_HEAT",
        description=FURNACE_DESCRIPTION,
        habitability_impact=True,
    )
    fx.set_clock(api, ESCALATION_CLOCK)
    assert fx.escalate_work_order(api, order["id"])["escalation_level"] == 1

    fx.set_clock(api, COLLECTION_CLOCK)
    fx.run_allotment_run(api, installation_id, SEPTEMBER)
    fx.set_clock(api, METRICS_CLOCK)

    metrics = validate_success(
        api.run_metrics_run(account["id"], f.metrics_run_payload(SEPTEMBER), MANAGER)
    )

    # Thirty occupied unit-days over one unit times thirty days.
    assert metrics["occupancy_rate_pct"] == FULL_MONTH_OCCUPANCY_PCT
    # The one CHARGE row of the period, with no abatement to net against.
    assert metrics["net_collected_cents"] == const.BASE_NET_RENT_CENTS
    assert metrics["habitability_penalty_pct"] == ONE_ESCALATION_PENALTY_PCT
    # round_half_up(218150 * 0.03) = 6545, then round_half_up(6545 * 1.25 * 0.95).
    assert metrics["performance_incentive_fee_cents"] == INCENTIVE_FEE_CENTS
    assert metrics["contributions_cents"] == CONTRIBUTION_CENTS
    assert metrics["expenditures_cents"] == 0
    assert metrics["closing_balance_cents"] == CLOSING_BALANCE_CENTS
    assert metrics["metrics_run_epoch"] == 1
    asserts.assert_instant_equals(metrics["last_metrics_run_at"], METRICS_CLOCK)

    stored = validate_success(
        api.get_reinvestment_account(account["id"], HOUSING_OFFICE)
    )
    asserts.assert_reinvestment_account(stored)
    assert stored["performance_incentive_fee_cents"] == INCENTIVE_FEE_CENTS
    assert stored["closing_balance_cents"] == CLOSING_BALANCE_CENTS


# One school-age child, so no dependent on file is under six at assessment.
NO_YOUNG_CHILDREN = (
    {"relationship": "SPOUSE", "date_of_birth": "1992-03-04", "gender": "FEMALE"},
    {"relationship": "CHILD", "date_of_birth": "2014-05-01", "gender": "MALE"},
)
MOLD_AT_THE_FIRST_CEILING = {
    "affected_area_sqft": 10,
    "lead_level_ppm": 14,
    "child_under_six_present": False,
}
MOLD_AT_THE_SECOND_CEILING = {"affected_area_sqft": 30, "child_under_six_present": False}
PAINT_AT_THE_SECOND_FLOOR = {"lead_level_ppm": 5000, "child_under_six_present": False}
WATER_BELOW_THE_FIRST_FLOOR = {"lead_level_ppm": 9, "child_under_six_present": False}
WATER_AT_THE_THIRD_FLOOR = {"lead_level_ppm": 15, "child_under_six_present": False}


def test_hazard_severity_grades_each_type_on_its_own_thresholds(api):
    """Five assessments, five boundary values, three different ladders.

    PRD: "For `MOLD`, an affected area of at most 10 square feet is `SEVERITY_1`, an area greater than 10 but at most 30 square feet is `SEVERITY_2`, and anything greater than 30 square feet is `SEVERITY_3`; the mold bounds are inclusive upper bounds, so exactly 10 square feet is `SEVERITY_1` and exactly 30 square feet is `SEVERITY_2`."

    Design: Corner/calculations/hazard_severity_grades_each_type_on_its_own_declared_thresholds
    """
    state = fx.setup_occupied_lease(api, dependents=NO_YOUNG_CHILDREN)
    unit_id = state["unit"]["id"]
    lease_id = state["lease"]["id"]
    reports = (
        ("MOLD", "Spotting on the bathroom ceiling", MANAGER),
        ("MOLD", "Growth behind the laundry wall", MANAGER),
        ("LEAD_PAINT", "Chipping paint on the window sills", SPECIALIST),
        ("LEAD_WATER", "Tap sample requested by the family", SPECIALIST),
        ("LEAD_WATER", "Second tap sample from the kitchen", SPECIALIST),
    )
    cases = [
        fx.report_hazard(
            api,
            unit_id,
            headers=headers,
            lease_id=lease_id,
            hazard_type=hazard_type,
            reported_symptoms=symptoms,
        )
        for hazard_type, symptoms, headers in reports
    ]

    # Ten square feet sits on the inclusive edge of the first mold band, and the
    # lead reading handed in alongside it is ignored because the type is MOLD.
    first = fx.assess_hazard(api, cases[0]["id"], **MOLD_AT_THE_FIRST_CEILING)
    assert first["assessment_severity"] == "SEVERITY_1"
    assert first["displacement_required"] is False
    assert first["status"] == "REMEDIATION_IN_PROGRESS"
    assert first["lead_level_ppm"] is None
    assert first["affected_area_sqft"] == 10
    assert first["remediation_work_order_id"] is not None
    asserts.assert_instant_equals(first["assessed_at"], MOVE_IN_CLOCK)

    # Thirty square feet is the inclusive top of the second band, not the third.
    second = fx.assess_hazard(api, cases[1]["id"], **MOLD_AT_THE_SECOND_CEILING)
    assert second["assessment_severity"] == "SEVERITY_2"
    assert second["displacement_required"] is False
    assert second["status"] == "REMEDIATION_IN_PROGRESS"

    # 5000 ppm has already left the paint ladder's first band.
    third = fx.assess_hazard(api, cases[2]["id"], **PAINT_AT_THE_SECOND_FLOOR)
    assert third["assessment_severity"] == "SEVERITY_2"
    assert third["displacement_required"] is False
    assert third["affected_area_sqft"] is None

    # Nine is below the water ladder's first floor of ten.
    fourth = fx.assess_hazard(api, cases[3]["id"], **WATER_BELOW_THE_FIRST_FLOOR)
    assert fourth["assessment_severity"] == "SEVERITY_1"
    assert fourth["displacement_required"] is False

    # Fifteen has reached the water top band, proving it is not the paint ladder.
    fifth = fx.assess_hazard(api, cases[4]["id"], **WATER_AT_THE_THIRD_FLOOR)
    assert fifth["assessment_severity"] == "SEVERITY_3"
    assert fifth["displacement_required"] is True
    assert fifth["status"] == "DISPLACEMENT_ACTIVE"
    assert fifth["child_under_six_present"] is False
