"""Rent determination: the provisional quote at signing versus the final rent.

Also covers the ladder ordering between the lease's state gate and the fiscal
rate-row gate, which is the pair a caller is most likely to trip together.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as asserts
from test_helpers import constants as const
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS

# A family whose orders land in 2025 but who arrive in 2026: the control date
# and the start date therefore sit in different rate years.
PROVISIONAL_CLOCK = "2025-11-01T00:00:00Z"
PCS_ORDERS_DATE = "2025-11-15"
ARRIVAL_DATE = "2026-01-05"
MOVE_IN_CLOCK = "2026-01-05T09:00:00Z"


def _two_rate_years(api):
    """Installation carrying both a 2025 and a 2026 E5 rate row, plus a family.

    Returns the tenancy dict with the lease still in PENDING_MOVE_IN, priced
    under the provisional variant against the 2025 row.
    """
    base = fx.setup_installation_with_unit(api, clock=PROVISIONAL_CLOCK)
    base["bah_rate_2025"] = fx.create_bah_rate(
        api,
        base["installation"]["id"],
        effective_year=2025,
        monthly_rate_cents=const.TEST_DEFAULTS["E5_2025_MONTHLY_RATE_CENTS"],
        utility_allowance_cents=const.TEST_DEFAULTS["E5_2025_UTILITY_ALLOWANCE_CENTS"],
    )
    sponsor, dependents = fx.setup_sponsor_family(api)
    application = fx.submit_application(
        api,
        base["installation"]["id"],
        sponsor,
        pcs_orders_date=PCS_ORDERS_DATE,
        expected_arrival_date=ARRIVAL_DATE,
    )
    fx.run_offer_run(api, base["installation"]["id"])
    application = fx.accept_offer(api, application["id"], sponsor)
    lease = fx.write_lease(
        api, application["id"], base["unit"]["id"], start_date=ARRIVAL_DATE
    )
    base.update(
        {
            "sponsor": sponsor,
            "dependents": dependents,
            "application": application,
            "lease": lease,
        }
    )
    return base


def test_lease_creation_quotes_the_control_date_year_rate(api):
    """Signing prices the lease off the 2025 row the control date points at.

    PRD: "The **`OFFER_PROVISIONAL`** variant runs at lease creation and produces the rent quoted at signing, before the family arrives: its year source is the calendar year of the application's `effective_control_date`, and its dependent-count source is the application's `dependent_count_at_application` snapshot."

    Design: Difficulty/dual_variant_calc/lease_gross_rent_provisional_vs_final_divergence
    """
    state = _two_rate_years(api)
    lease = state["lease"]

    asserts.assert_lease(lease)
    assert state["application"]["effective_control_date"] == PCS_ORDERS_DATE
    assert lease["rent_basis"] == "OFFER_PROVISIONAL"
    assert lease["rent_effective_year"] == 2025
    assert lease["gross_rent_cents"] == const.PROVISIONAL_2025_GROSS_RENT_CENTS
    assert (
        lease["utility_allowance_cents"]
        == const.PROVISIONAL_2025_UTILITY_ALLOWANCE_CENTS
    )
    assert lease["net_rent_cents"] == const.PROVISIONAL_2025_NET_RENT_CENTS
    assert lease["daily_rent_cents"] == const.PROVISIONAL_2025_DAILY_RENT_CENTS
    asserts.assert_lease_money_invariants(lease)


def test_move_in_reprices_the_lease_off_the_start_date_year_rate(api):
    """Arrival re-reads the 2026 row, so every rent figure moves.

    PRD: "The divergence is real and intended: for a control date in 2025 and a start date in 2026 the two variants read different rate rows and produce different `gross_rent_cents` for identical lease inputs."

    Design: Difficulty/dual_variant_calc/lease_gross_rent_provisional_vs_final_divergence
    """
    state = _two_rate_years(api)
    inspection = fx.schedule_inspection(
        api, state["lease"]["id"], scheduled_date="2026-01-04"
    )
    sponsor = state["sponsor"]
    fx.acknowledge_inspection(
        api,
        inspection["id"],
        sponsor,
        f"{sponsor['first_name']} {sponsor['last_name']}",
        state["installation"]["bill_of_rights_version"],
    )
    fx.set_clock(api, MOVE_IN_CLOCK)

    occupied = fx.move_in(api, state["lease"]["id"])

    assert occupied["rent_basis"] == "MOVE_IN_FINAL"
    assert occupied["rent_effective_year"] == 2026
    assert occupied["gross_rent_cents"] == const.BASE_GROSS_RENT_CENTS
    assert occupied["utility_allowance_cents"] == const.BASE_UTILITY_ALLOWANCE_CENTS
    assert occupied["net_rent_cents"] == const.BASE_NET_RENT_CENTS
    assert occupied["daily_rent_cents"] == const.BASE_DAILY_RENT_CENTS
    # The same lease inputs, two rate rows: the quote and the collected rent differ.
    assert (
        occupied["gross_rent_cents"] - const.PROVISIONAL_2025_GROSS_RENT_CENTS == 13580
    )
    assert occupied["net_rent_cents"] - const.PROVISIONAL_2025_NET_RENT_CENTS == 12080
    asserts.assert_lease_money_invariants(occupied)


def test_each_variant_rounds_the_daily_rent_exactly_once(api):
    """Both variants derive the per-day rent from their own net rent, once.

    PRD: "The stored `daily_rent_cents` is `net_rent_cents` multiplied by 12 and divided by 365, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/lease_gross_rent_provisional_vs_final_divergence
    """
    state = _two_rate_years(api)
    provisional = state["lease"]
    assert provisional["daily_rent_cents"] == 6775
    assert provisional["daily_rent_cents"] * 365 != provisional["net_rent_cents"] * 12

    inspection = fx.schedule_inspection(
        api, provisional["id"], scheduled_date="2026-01-04"
    )
    sponsor = state["sponsor"]
    fx.acknowledge_inspection(
        api,
        inspection["id"],
        sponsor,
        f"{sponsor['first_name']} {sponsor['last_name']}",
        state["installation"]["bill_of_rights_version"],
    )
    fx.set_clock(api, MOVE_IN_CLOCK)
    occupied = fx.move_in(api, provisional["id"])

    assert occupied["daily_rent_cents"] == 7172
    assert occupied["daily_rent_cents"] - provisional["daily_rent_cents"] == 397
    assert occupied["version"] > provisional["version"]


def _offered_application_and_no_rate_row(api):
    """An installation with inventory and an offered family but no BAH table.

    Lease creation against this state violates two rungs at once: the
    application is only OFFERED, and no rate row can be selected.
    """
    fx.set_clock(api, fx.CLOCK_BEFORE_ARRIVAL)
    installation = fx.create_installation(api)
    unit = fx.create_housing_unit(api, installation["id"])
    sponsor, dependents = fx.setup_sponsor_family(api)
    application = fx.submit_application(api, installation["id"], sponsor)
    fx.run_offer_run(api, installation["id"])
    return {
        "installation": fx.read_installation(api, installation["id"]),
        "unit": fx.read_housing_unit(api, unit["id"]),
        "sponsor": sponsor,
        "dependents": dependents,
        "application": fx.read_application(api, application["id"]),
    }


def test_unaccepted_application_is_reported_before_the_missing_rate_row(api):
    """The 409 state gate answers first even though the fiscal gate also fails.

    PRD: "The ladder is walked in ascending priority order and **the first violated rung determines the response**; the remaining rungs are not evaluated."

    Design: Difficulty/priority_pair_validation_conflict/lease_state_gate_outranks_bah_rate_fiscal_gate
    """
    state = _offered_application_and_no_rate_row(api)
    assert state["application"]["status"] == "OFFERED"

    response = api.create_lease(
        f.create_lease_payload(state["application"]["id"], state["unit"]["id"]),
        TEST_USERS["property_manager_headers"],
    )

    validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_ACCEPTED, 409)


def test_rejected_lease_creation_leaves_the_offer_and_inventory_untouched(api):
    """Nothing is written when the state gate refuses the lease.

    PRD: "Rung 22 requires, on lease creation, that the referenced application's `status` be `ACCEPTED`, failing with `ERR_APPLICATION_NOT_ACCEPTED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/lease_state_gate_outranks_bah_rate_fiscal_gate
    """
    state = _offered_application_and_no_rate_row(api)

    response = api.create_lease(
        f.create_lease_payload(state["application"]["id"], state["unit"]["id"]),
        TEST_USERS["property_manager_headers"],
    )
    validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_ACCEPTED, 409)

    leases = validate_success(api.list_leases(TEST_USERS["property_manager_headers"]))
    assert leases == []
    application = fx.read_application(api, state["application"]["id"])
    assert application["status"] == "OFFERED"
    assert application["offer_count"] == 1
    assert application["offered_unit_id"] == state["unit"]["id"]
    unit = fx.read_housing_unit(api, state["unit"]["id"])
    assert unit["status"] == "ASSIGNED"
    installation = fx.read_installation(api, state["installation"]["id"])
    assert installation["assigned_unit_count"] == 1
    assert installation["available_unit_count"] == 0
    asserts.assert_installation_counter_conservation(installation)


def test_filing_the_missing_rate_row_does_not_change_the_reported_gate(api):
    """Curing the fiscal gate leaves the state gate as the answer.

    PRD: "No later rung may pre-empt an earlier one, so when a request violates two rules the caller always sees the lower-numbered one."

    Design: Difficulty/priority_pair_validation_conflict/lease_state_gate_outranks_bah_rate_fiscal_gate
    """
    state = _offered_application_and_no_rate_row(api)
    fx.create_bah_rate(api, state["installation"]["id"])

    response = api.create_lease(
        f.create_lease_payload(state["application"]["id"], state["unit"]["id"]),
        TEST_USERS["property_manager_headers"],
    )
    validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_ACCEPTED, 409)

    # Accepting the offer clears the state gate, and the lease now prices cleanly.
    application = fx.accept_offer(api, state["application"]["id"], state["sponsor"])
    assert application["status"] == "ACCEPTED"
    lease = fx.write_lease(api, application["id"], state["unit"]["id"])
    assert lease["gross_rent_cents"] == const.BASE_GROSS_RENT_CENTS
    assert lease["occupancy_status"] == "PENDING_MOVE_IN"
