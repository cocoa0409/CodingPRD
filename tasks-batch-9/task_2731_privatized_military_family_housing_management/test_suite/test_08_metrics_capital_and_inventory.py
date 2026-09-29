"""The metrics run's two occupancy bases, the capital pool, and the counters."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as asserts
from test_helpers import constants as const
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

SEPTEMBER = "2026-09"
LATE_ARRIVAL_DATE = "2026-09-07"
LATE_INSPECTION_DATE = "2026-09-06"
LATE_MOVE_IN_CLOCK = "2026-09-07T09:00:00Z"
ALLOTMENT_CLOCK = "2026-09-30T12:00:00Z"
METRICS_CLOCK = "2026-10-01T00:00:00Z"

OPENING_BALANCE_CENTS = const.TEST_DEFAULTS["OPENING_BALANCE_CENTS"]
# September's two charges: 218150 for the townhome, 248000 for the SFH.
NET_COLLECTED_CENTS = 466150
# Thirty occupied unit-days plus twenty-four, over two units times thirty days.
UNIT_DAY_RATE_PCT = 90.00
MONTH_END_RATE_PCT = 100.00
DIVERGENCE_PCT = 10.00
# Three percent of collections is 13985 after rounding half up, then the band
# multiplier: 0.50 under the unit-day basis, 1.25 under the snapshot.
UNIT_DAY_FEE_CENTS = 6993
MONTH_END_FEE_CENTS = 17481
CONTRIBUTIONS_CENTS = 46615
CLOSING_AFTER_CONTRIBUTION_CENTS = 5046615


def _rate(account):
    """Read the stored occupancy percentage as a number."""
    return float(account["occupancy_rate_pct"])


def _one_full_month_and_one_late_arrival(api):
    """Two tenancies at one installation, the second arriving on 2026-09-07.

    Both units are occupied when September closes, but only one was occupied
    for the whole of it, which is exactly what the two bases disagree about.
    """
    fx.set_clock(api, fx.CLOCK_BEFORE_ARRIVAL)
    installation = fx.create_installation(api)
    inst_id = installation["id"]
    fx.create_bah_rate(api, inst_id)
    fx.create_bah_rate(api, inst_id, **fx.SENIOR_ENLISTED_RATE)
    units = [
        fx.create_housing_unit(api, inst_id),
        fx.create_housing_unit(api, inst_id, **fx.SENIOR_ENLISTED_UNIT),
    ]
    junior, _ = fx.setup_sponsor_family(api)
    senior, _ = fx.setup_sponsor_family(
        api, dependents=fx.SENIOR_ENLISTED_DEPENDENTS, **fx.SENIOR_ENLISTED_SPONSOR
    )
    applications = [
        fx.submit_application(api, inst_id, junior),
        fx.submit_application(
            api, inst_id, senior, expected_arrival_date=LATE_ARRIVAL_DATE
        ),
    ]
    fx.run_offer_run(api, inst_id)
    applications = [
        fx.accept_offer(api, applications[0]["id"], junior),
        fx.accept_offer(api, applications[1]["id"], senior),
    ]
    leases = [
        fx.write_lease(api, applications[0]["id"], units[0]["id"]),
        fx.write_lease(
            api,
            applications[1]["id"],
            units[1]["id"],
            start_date=LATE_ARRIVAL_DATE,
        ),
    ]
    for lease, sponsor, scheduled in (
        (leases[0], junior, None),
        (leases[1], senior, LATE_INSPECTION_DATE),
    ):
        overrides = {} if scheduled is None else {"scheduled_date": scheduled}
        inspection = fx.schedule_inspection(api, lease["id"], **overrides)
        fx.acknowledge_inspection(
            api,
            inspection["id"],
            sponsor,
            f"{sponsor['first_name']} {sponsor['last_name']}",
            installation["bill_of_rights_version"],
        )
    fx.set_clock(api, fx.CLOCK_AT_MOVE_IN)
    leases[0] = fx.move_in(api, leases[0]["id"])
    fx.set_clock(api, LATE_MOVE_IN_CLOCK)
    leases[1] = fx.move_in(api, leases[1]["id"])
    assert leases[0]["net_rent_cents"] == const.BASE_NET_RENT_CENTS
    assert leases[1]["net_rent_cents"] == const.E7_NET_RENT_CENTS
    fx.set_clock(api, ALLOTMENT_CLOCK)
    fx.run_allotment_run(api, inst_id, SEPTEMBER)
    accounts = [
        fx.create_reinvestment_account(api, inst_id),
        fx.create_reinvestment_account(
            api, inst_id, occupancy_basis="MONTH_END_SNAPSHOT"
        ),
    ]
    assert accounts[0]["occupancy_basis"] == "UNIT_DAY_WEIGHTED"
    assert accounts[1]["occupancy_basis"] == "MONTH_END_SNAPSHOT"
    fx.set_clock(api, METRICS_CLOCK)
    return {
        "installation": installation,
        "units": units,
        "leases": leases,
        "unit_day_account": accounts[0],
        "month_end_account": accounts[1],
    }


def test_the_unit_day_basis_counts_only_the_tail_of_a_late_arrival(api):
    """Fifty-four occupied unit-days out of sixty score ninety points.

    PRD: "Under the `UNIT_DAY_WEIGHTED` basis, the numerator is the sum, over all of the installation's units, of the number of days in the period on which that unit had a lease whose `occupancy_status` was `OCCUPIED` or `NOTICE_GIVEN`, where a lease counts from its `start_date` through the earlier of its `termination_effective_date` and the period's last day, inclusive at both ends; the denominator is the unit count multiplied by the month's day count."

    Design: Difficulty/dual_variant_calc/occupancy_rate_unit_day_vs_month_end_divergence
    """
    state = _one_full_month_and_one_late_arrival(api)

    account = fx.run_metrics_run(
        api, state["unit_day_account"]["id"], SEPTEMBER
    )

    asserts.assert_reinvestment_account(account)
    assert _rate(account) == UNIT_DAY_RATE_PCT
    assert account["net_collected_cents"] == NET_COLLECTED_CENTS
    assert account["habitability_penalty_pct"] == 0
    assert account["performance_incentive_fee_cents"] == UNIT_DAY_FEE_CENTS
    assert account["contributions_cents"] == CONTRIBUTIONS_CENTS
    assert account["closing_balance_cents"] == CLOSING_AFTER_CONTRIBUTION_CENTS
    assert account["expenditures_cents"] == 0
    assert account["metrics_run_epoch"] == 1
    asserts.assert_instant_equals(account["last_metrics_run_at"], METRICS_CLOCK)


def test_the_month_end_snapshot_counts_the_late_arrival_in_full(api):
    """Both units are occupied on the thirtieth, so the snapshot reads full.

    PRD: "Under the `MONTH_END_SNAPSHOT` basis, the numerator is the count of units whose `status` is `OCCUPIED` on the period's last day and the denominator is simply the unit count, so any unit occupied on the final day counts fully no matter when the family arrived."

    Design: Difficulty/dual_variant_calc/occupancy_rate_unit_day_vs_month_end_divergence
    """
    state = _one_full_month_and_one_late_arrival(api)

    account = fx.run_metrics_run(
        api, state["month_end_account"]["id"], SEPTEMBER
    )

    asserts.assert_reinvestment_account(account)
    assert _rate(account) == MONTH_END_RATE_PCT
    assert account["net_collected_cents"] == NET_COLLECTED_CENTS
    assert account["performance_incentive_fee_cents"] == MONTH_END_FEE_CENTS
    assert account["contributions_cents"] == CONTRIBUTIONS_CENTS
    assert account["closing_balance_cents"] == CLOSING_AFTER_CONTRIBUTION_CENTS
    assert account["metrics_run_epoch"] == 1


def test_the_two_bases_land_the_same_period_in_different_bands(api):
    """Ten points apart on identical collections, and the fee follows the band.

    PRD: "The divergence is material: for two units where one was occupied all 30 days of 2026-09 and the other from 2026-09-07 onward, which is 24 days, the unit-day basis yields 90.00 while the month-end snapshot yields 100.00 — ten full points apart, which lands the installation in different incentive multiplier bands."

    Design: Difficulty/dual_variant_calc/occupancy_rate_unit_day_vs_month_end_divergence
    """
    state = _one_full_month_and_one_late_arrival(api)

    unit_day = fx.run_metrics_run(api, state["unit_day_account"]["id"], SEPTEMBER)
    month_end = fx.run_metrics_run(api, state["month_end_account"]["id"], SEPTEMBER)

    assert _rate(month_end) - _rate(unit_day) == DIVERGENCE_PCT
    assert unit_day["net_collected_cents"] == month_end["net_collected_cents"]
    assert (
        unit_day["performance_incentive_fee_cents"]
        != month_end["performance_incentive_fee_cents"]
    )
    assert unit_day["performance_incentive_fee_cents"] == UNIT_DAY_FEE_CENTS
    assert month_end["performance_incentive_fee_cents"] == MONTH_END_FEE_CENTS
    # The basis is pinned at creation, so neither run adopted the other's.
    assert unit_day["occupancy_basis"] == "UNIT_DAY_WEIGHTED"
    assert month_end["occupancy_basis"] == "MONTH_END_SNAPSHOT"
    assert unit_day["contributions_cents"] == month_end["contributions_cents"]


HAZARD_CLOCK = "2026-09-20T10:00:00Z"
COMPLETION_CLOCK = "2026-09-27T15:00:00Z"
CLOSE_DATE = "2026-09-27"
CONTRACT_RATE_CENTS = 22000
AUTHORIZED_OCCUPANTS = 4
# The 22000 room rate plus four meal allowances of 6900.
PER_NIGHT_AUTHORIZED_CENTS = 49600
SEVEN_NIGHTS = 7
SEVEN_NIGHT_AUTHORIZED_CENTS = 347200
SEVEN_NIGHT_RENT_ABATEMENT_CENTS = 50204
ACCOUNT_AFTER_THE_CLOSURE_CENTS = 4652800
# Eleven inclusive days of September credited when the allotment was suspended.
ABATEMENT_CENTS = 78892
BALANCE_AFTER_ABATEMENT_CENTS = 139258


def _displaced_family_lodged_with_the_repair_under_way(api):
    """A displaced household in lodging, its remediation order IN_PROGRESS."""
    state = fx.setup_charged_lease(api)
    fx.setup_account(api, occupied_state=state)
    fx.setup_displaced_household(
        api,
        occupied_state=state,
        hazard_clock=HAZARD_CLOCK,
        report_overrides={
            "lease_id": state["lease"]["id"],
            "reported_symptoms": "Extensive growth across master bedroom wall",
        },
        assess_overrides={"child_under_six_present": True},
    )
    assert state["hazard_case"]["status"] == "DISPLACEMENT_ACTIVE"
    state["lodging"] = fx.authorize_lodging(
        api,
        state["hazard_case"]["id"],
        state["lease"]["id"],
        nightly_rate_cents=CONTRACT_RATE_CENTS,
        occupants_count=AUTHORIZED_OCCUPANTS,
    )
    order = fx.find_remediation_work_order(api, state["hazard_case"])
    fx.assign_work_order(api, order["id"])
    state["work_order"] = fx.start_work_order(api, order["id"])
    fx.set_clock(api, COMPLETION_CLOCK)
    return state


def test_completing_the_repair_carries_the_case_to_clearance_pending(api):
    """Hops one and two: one completion request moves the case as well.

    PRD: "If instead the order is the one a hazard case is tracking as its remediation order, the case advances out of `REMEDIATION_IN_PROGRESS` or `DISPLACEMENT_ACTIVE` into `CLEARANCE_PENDING` as a second hop; and when the case had been in `DISPLACEMENT_ACTIVE`, every `AUTHORIZED` lodging on it is closed with `actual_end_date` set to the logical clock's date, computing `nights_displaced`, `per_night_authorized_cents`, `lodging_authorized_cents` and `rent_abatement_cents` as a third hop, after which the reinvestment account for that installation and the calendar year of the close date has its `expenditures_cents` raised by the sum of those closed lodgings' `lodging_authorized_cents` as a fourth hop, and its `closing_balance_cents` recomputed with its `version` incremented by 1 as a fifth hop."

    Design: Difficulty/transitive_cascade/remediation_completion_cascades_lodging_close_to_account_balance
    """
    state = _displaced_family_lodged_with_the_repair_under_way(api)

    completed = fx.complete_work_order(api, state["work_order"]["id"])

    assert completed["status"] == "COMPLETED"
    asserts.assert_instant_equals(completed["completed_at"], COMPLETION_CLOCK)
    case = fx.read_hazard_case(api, state["hazard_case"]["id"])
    asserts.assert_hazard_case(case)
    assert case["status"] == "CLEARANCE_PENDING"
    assert case["remediation_work_order_id"] == state["work_order"]["id"]


def test_the_closure_prices_the_stay_at_the_clock_date(api):
    """Hop three: seven nights, priced per night and against the daily rent.

    PRD: "`nights_displaced` is the number of whole days from `start_date` inclusive to `actual_end_date` exclusive, so a lodging closed on its own start date yields 0 nights."

    Design: Difficulty/transitive_cascade/remediation_completion_cascades_lodging_close_to_account_balance
    """
    state = _displaced_family_lodged_with_the_repair_under_way(api)

    fx.complete_work_order(api, state["work_order"]["id"])

    lodging = fx.read_lodging(api, state["lodging"]["id"])
    asserts.assert_displacement_lodging(lodging)
    assert lodging["status"] == "CLOSED"
    assert lodging["actual_end_date"] == CLOSE_DATE
    assert lodging["nights_displaced"] == SEVEN_NIGHTS
    assert lodging["per_night_authorized_cents"] == PER_NIGHT_AUTHORIZED_CENTS
    assert lodging["lodging_authorized_cents"] == SEVEN_NIGHT_AUTHORIZED_CENTS
    assert lodging["rent_abatement_cents"] == SEVEN_NIGHT_RENT_ABATEMENT_CENTS


def test_the_lodging_spend_lands_on_the_capital_account_not_the_ledger(api):
    """Hops four and five: the account pays, and the ledger does not move.

    PRD: "No `AllotmentTransaction` row is posted for the lodging at all: the ledger abatement was already posted when the allotment was suspended, and `rent_abatement_cents` is the reconciliation figure the installation compares against it."

    Design: Difficulty/transitive_cascade/remediation_completion_cascades_lodging_close_to_account_balance
    """
    state = _displaced_family_lodged_with_the_repair_under_way(api)
    opened_version = state["account"]["version"]

    fx.complete_work_order(api, state["work_order"]["id"])

    account = fx.read_account(api, state["account"]["id"])
    asserts.assert_reinvestment_account(account)
    assert account["expenditures_cents"] == SEVEN_NIGHT_AUTHORIZED_CENTS
    assert account["closing_balance_cents"] == ACCOUNT_AFTER_THE_CLOSURE_CENTS
    assert account["contributions_cents"] == 0
    assert account["version"] == opened_version + 1
    lease = fx.read_lease(api, state["lease"]["id"])
    assert lease["allotment_balance_cents"] == BALANCE_AFTER_ABATEMENT_CENTS
    assert lease["abatement_total_cents"] == ABATEMENT_CENTS
    ledger = fx.read_ledger(api, state["lease"]["id"])
    assert [row["type"] for row in ledger] == ["CHARGE", "ABATEMENT"]
    asserts.assert_ledger_conservation(ledger, lease)


THIRD_UNIT = {
    "unit_code": "C-300",
    "bedroom_count": 2,
    "unit_type": "APARTMENT",
    "designated_rank_category": "JUNIOR_ENLISTED",
    "historic_flag": False,
}
INVENTORY_CLOCK = "2026-09-10T09:00:00Z"
STAIRWELL_HOLD_REASON = "Lead paint survey pending in the stairwell"


def _one_occupied_unit_and_two_spare_ones(api):
    """Three units at one installation: one occupied, two sitting available."""
    state = fx.setup_occupied_lease(api)
    inst_id = state["installation"]["id"]
    fx.create_bah_rate(api, inst_id, **fx.SENIOR_ENLISTED_RATE)
    state["spare_units"] = [
        fx.create_housing_unit(api, inst_id, **fx.SENIOR_ENLISTED_UNIT),
        fx.create_housing_unit(api, inst_id, **THIRD_UNIT),
    ]
    fx.set_clock(api, INVENTORY_CLOCK)
    installation = fx.read_installation(api, inst_id)
    assert installation["total_unit_count"] == 3
    assert installation["available_unit_count"] == 2
    assert installation["occupied_unit_count"] == 1
    state["installation"] = installation
    return state


def _set_status(api, housing_unit_id, status, **overrides):
    return validate_success(
        api.set_housing_unit_status(
            housing_unit_id,
            f.housing_unit_status_payload(status, **overrides),
            TEST_USERS["property_manager_headers"],
        )
    )


def _counters(api, installation_id):
    installation = fx.read_installation(api, installation_id)
    asserts.assert_installation_counter_conservation(installation)
    return installation


def test_two_status_writes_move_counts_between_buckets_only(api):
    """A hold and a takedown redistribute the inventory without growing it.

    PRD: "After every request that creates a unit or changes a unit's `status`, the five per-status counters must each equal the live count of the installation's units in the matching status, and `total_unit_count` must equal their sum across all five tracked statuses."

    Design: Difficulty/compensating_invariant/unit_status_counters_conserve_installation_inventory
    """
    state = _one_occupied_unit_and_two_spare_ones(api)
    inst_id = state["installation"]["id"]
    senior_unit, apartment = state["spare_units"]

    held = _set_status(
        api, apartment["id"], "HAZARD_HOLD", hazard_hold_reason=STAIRWELL_HOLD_REASON
    )

    assert held["status"] == "HAZARD_HOLD"
    assert held["hazard_hold_reason"] == STAIRWELL_HOLD_REASON
    after_hold = _counters(api, inst_id)
    assert after_hold["available_unit_count"] == 1
    assert after_hold["hazard_hold_unit_count"] == 1
    assert after_hold["offline_unit_count"] == 0
    assert after_hold["occupied_unit_count"] == 1
    assert after_hold["assigned_unit_count"] == 0
    assert after_hold["total_unit_count"] == 3

    offline = _set_status(api, senior_unit["id"], "OFFLINE_MAINTENANCE")

    assert offline["status"] == "OFFLINE_MAINTENANCE"
    after_takedown = _counters(api, inst_id)
    assert after_takedown["available_unit_count"] == 0
    assert after_takedown["offline_unit_count"] == 1
    assert after_takedown["hazard_hold_unit_count"] == 1
    assert after_takedown["occupied_unit_count"] == 1
    assert after_takedown["assigned_unit_count"] == 0
    assert after_takedown["total_unit_count"] == 3


def test_releasing_the_operator_hold_clears_the_reason_it_stamped(api):
    """The compensating edge hands the count back and wipes the reason.

    PRD: "Releasing an operator-placed hold is the compensating edge: `HAZARD_HOLD → AVAILABLE` clears `hazard_hold_reason`, recomputes `hazard_hold_unit_count` and `available_unit_count` with the five-counter sum unchanged, and raises the unit's `version` by 1."

    Design: Difficulty/compensating_invariant/unit_status_counters_conserve_installation_inventory
    """
    state = _one_occupied_unit_and_two_spare_ones(api)
    inst_id = state["installation"]["id"]
    apartment = state["spare_units"][1]
    held = _set_status(
        api, apartment["id"], "HAZARD_HOLD", hazard_hold_reason=STAIRWELL_HOLD_REASON
    )

    released = _set_status(api, apartment["id"], "AVAILABLE")

    asserts.assert_housing_unit(released)
    assert released["status"] == "AVAILABLE"
    assert released["hazard_hold_reason"] is None
    assert released["version"] == held["version"] + 1
    after_release = _counters(api, inst_id)
    assert after_release["available_unit_count"] == 2
    assert after_release["hazard_hold_unit_count"] == 0
    assert after_release["offline_unit_count"] == 0
    assert after_release["occupied_unit_count"] == 1
    assert after_release["total_unit_count"] == 3


def test_the_inventory_returns_to_its_starting_distribution(api):
    """Four writes later the counters are exactly where they began.

    PRD: "`AVAILABLE → OFFLINE_MAINTENANCE` takes a unit out of the offer pool for planned work, and `OFFLINE_MAINTENANCE → AVAILABLE` puts it back; each edge recomputes `available_unit_count` and `offline_unit_count` and raises the unit's `version` by 1."

    Design: Difficulty/compensating_invariant/unit_status_counters_conserve_installation_inventory
    """
    state = _one_occupied_unit_and_two_spare_ones(api)
    inst_id = state["installation"]["id"]
    senior_unit, apartment = state["spare_units"]
    start = _counters(api, inst_id)

    _set_status(
        api, apartment["id"], "HAZARD_HOLD", hazard_hold_reason=STAIRWELL_HOLD_REASON
    )
    _set_status(api, senior_unit["id"], "OFFLINE_MAINTENANCE")
    _set_status(api, apartment["id"], "AVAILABLE")
    back_online = _set_status(api, senior_unit["id"], "AVAILABLE")

    assert back_online["status"] == "AVAILABLE"
    end = _counters(api, inst_id)
    for counter in (
        "available_unit_count",
        "assigned_unit_count",
        "occupied_unit_count",
        "offline_unit_count",
        "hazard_hold_unit_count",
        "total_unit_count",
    ):
        assert end[counter] == start[counter], counter
    # The occupied tenancy never entered the story at all.
    assert fx.read_housing_unit(api, state["unit"]["id"])["status"] == "OCCUPIED"
    lease = fx.read_lease(api, state["lease"]["id"])
    assert lease["occupancy_status"] == "OCCUPIED"
    assert lease["allotment_status"] == "ACTIVE"
