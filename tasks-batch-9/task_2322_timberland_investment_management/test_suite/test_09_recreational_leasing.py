"""Recreational leasing: coverage capacity, the half-open blackout and the termination refund."""

from test_helpers import (
    ApiErrorId,
    assert_acres,
    assert_bps,
    assert_fund_cash,
    assert_money,
    assert_stand_partition,
    validate_error,
    validate_success,
)
from test_helpers.factories import CANONICAL_CRUISE_PLOTS
from test_helpers.fixtures import (
    activate_lease,
    close_cruise,
    create_lease,
    create_stand,
    owned_tract,
    read_block,
    read_fund,
    read_lease,
    read_stand,
    record_cruise_plot,
    reserve_block,
    terminate_lease,
)
from test_helpers.test_users import make_forest_manager_headers, make_fund_admin_headers

LEASE_ONE = {
    "leased_acres": 600.00,
    "term_start_date": "2027-01-01",
    "term_end_date": "2028-01-01",
    "blackout_start_date": "2027-06-01",
    "blackout_end_date": "2027-12-01",
}
LEASE_TWO = {
    "lessee_name": "Cypress Bend Sportsmen",
    "leased_acres": 400.00,
    "term_start_date": "2027-03-01",
    "term_end_date": "2027-09-01",
    "blackout_start_date": "2027-04-01",
    "blackout_end_date": "2027-05-01",
}
LEASE_THREE = {
    "lessee_name": "Longleaf Bowhunters",
    "leased_acres": 360.00,
    "term_start_date": "2027-09-01",
    "term_end_date": "2027-12-01",
    "blackout_start_date": "2027-10-01",
    "blackout_end_date": "2027-11-01",
}
LEASE_FOUR = {
    "lessee_name": "Piney Creek Hunt Club",
    "leased_acres": 600.00,
    "term_start_date": "2028-01-01",
    "term_end_date": "2029-01-01",
    "blackout_start_date": "2028-06-01",
    "blackout_end_date": "2028-07-01",
}
SHORT_LEASE = {
    "leased_acres": 600.00,
    "term_start_date": "2026-08-01",
    "term_end_date": "2027-02-01",
    "blackout_start_date": "2026-10-01",
    "blackout_end_date": "2026-11-01",
}


def _cruise_second_stand(api, property_id, stand_code="PC-02"):
    stand = create_stand(api, property_id, stand_code=stand_code)
    for plot in CANONICAL_CRUISE_PLOTS:
        record_cruise_plot(api, stand["id"], **plot)
    return close_cruise(api, stand["id"])


class TestLeaseCoverageCapacity:
    """Only leases whose half-open terms genuinely intersect count against the cap."""

    def test_a_full_year_term_pays_its_whole_annual_rent(self, api):
        """A term of exactly 365 days is billed the full annual rent at activation.

        PRD: "At creation the system computes `annual_rent_usd` as `leased_acres` multiplied by `rent_per_acre_usd`, rounded half-up to two decimals, and `term_days` as the whole number of days from `term_start_date` to `term_end_date` under half-open counting, which excludes the end date."

        Design: Difficulty/resource_temporal_overlap/lease_coverage_capacity_counts_only_intersecting_terms
        """
        ctx = owned_tract(api)
        lease = create_lease(api, ctx.property_id, **LEASE_ONE)
        assert_money(lease["annual_rent_usd"], 13500.00, "annual_rent_usd")
        assert lease["status"] == "PENDING"

        activated = activate_lease(api, lease["id"])

        assert activated["status"] == "ACTIVE"
        assert activated["term_days"] == 365
        assert_money(
            activated["first_year_prorated_rent_usd"],
            13500.00,
            "first_year_prorated_rent_usd",
        )

    def test_an_overlapping_lease_beyond_the_cap_is_refused_and_stays_pending(self, api):
        """Six hundred plus four hundred acres exceeds the 960.00-acre capacity.

        PRD: "must be less than or equal to capacity; equality is allowed and only a strictly greater total is refused, with `ERR_LEASE_ACREAGE_EXCEEDED`"

        Design: Difficulty/resource_temporal_overlap/lease_coverage_capacity_counts_only_intersecting_terms
        """
        ctx = owned_tract(api)
        first = create_lease(api, ctx.property_id, **LEASE_ONE)
        activate_lease(api, first["id"])
        second = create_lease(api, ctx.property_id, **LEASE_TWO)

        response = api.activate_recreational_lease(
            second["id"], None, make_fund_admin_headers()
        )
        validate_error(response, ApiErrorId.LEASE_ACREAGE_EXCEEDED.value, 422)

        refused = read_lease(api, second["id"])
        assert refused["status"] == "PENDING"
        assert refused["first_year_prorated_rent_usd"] is None

    def test_a_term_touching_only_at_an_endpoint_does_not_count_against_capacity(self, api):
        """The third lease activates at exactly the 960.00-acre capacity.

        PRD: "The set that counts against that capacity is the property's leases in `PENDING` or `ACTIVE` whose half-open term intersects the candidate's half-open term; terms that merely touch at an endpoint do not intersect and do not count."

        Design: Difficulty/resource_temporal_overlap/lease_coverage_capacity_counts_only_intersecting_terms
        """
        ctx = owned_tract(api)
        first = create_lease(api, ctx.property_id, **LEASE_ONE)
        activate_lease(api, first["id"])
        second = create_lease(api, ctx.property_id, **LEASE_TWO)
        api.activate_recreational_lease(second["id"], None, make_fund_admin_headers())
        third = create_lease(api, ctx.property_id, **LEASE_THREE)

        activated = activate_lease(api, third["id"])

        assert activated["status"] == "ACTIVE"
        assert_acres(activated["leased_acres"], 360.00, "leased_acres")
        assert_money(
            activated["first_year_prorated_rent_usd"],
            2019.45,
            "first_year_prorated_rent_usd",
        )

    def test_a_leap_year_term_is_clamped_to_three_hundred_sixty_five_days(self, api):
        """A 366-day term still pays one full year up front, not 13536.99.

        PRD: "On activation the lessee is billed `first_year_prorated_rent_usd`, computed as `annual_rent_usd` multiplied by the lesser of `term_days` and 365, divided by 365, rounded half-up to two decimals"

        Design: Difficulty/resource_temporal_overlap/lease_coverage_capacity_counts_only_intersecting_terms
        """
        ctx = owned_tract(api)
        first = create_lease(api, ctx.property_id, **LEASE_ONE)
        activate_lease(api, first["id"])
        fourth = create_lease(api, ctx.property_id, **LEASE_FOUR)

        activated = activate_lease(api, fourth["id"])

        assert activated["term_days"] == 366
        assert_money(
            activated["first_year_prorated_rent_usd"],
            13500.00,
            "first_year_prorated_rent_usd",
        )
        assert abs(float(activated["first_year_prorated_rent_usd"]) - 13536.99) > 0.01, (
            "the leap-year term must not have been billed 366 days of rent"
        )

    def test_every_activation_rent_reaches_the_fund_treasury(self, api):
        """Only the two admitted leases move money, so cash rises to 329019.45.

        PRD: "That amount is credited to both the fund's `cash_balance_usd` and its `net_operating_cash_usd`, and `cash_yield_bps` and `harvest_acceleration_required` are recomputed."

        Design: Difficulty/resource_temporal_overlap/lease_coverage_capacity_counts_only_intersecting_terms
        """
        ctx = owned_tract(api)
        first = create_lease(api, ctx.property_id, **LEASE_ONE)
        activate_lease(api, first["id"])
        second = create_lease(api, ctx.property_id, **LEASE_TWO)
        api.activate_recreational_lease(second["id"], None, make_fund_admin_headers())
        third = create_lease(api, ctx.property_id, **LEASE_THREE)
        activate_lease(api, third["id"])
        fourth = create_lease(api, ctx.property_id, **LEASE_FOUR)
        activate_lease(api, fourth["id"])

        assert_fund_cash(
            read_fund(api, ctx.fund_id),
            cash_balance_usd=329019.45,
            net_operating_cash_usd=29019.45,
        )


class TestClosedHarvestWindowAgainstHalfOpenBlackout:
    """The harvest window includes both its endpoints; the blackout excludes its end."""

    def test_a_window_starting_on_the_excluded_blackout_end_commits(self, api):
        """A window opening on 2027-12-01 clears a blackout that ends there exclusively.

        PRD: "Commitment moves `planned_tons` out of the stand's `reserved_tons` and into its `committed_tons`, leaving `available_tons` unchanged, and increments the stand's `version`."

        Design: Difficulty/resource_temporal_overlap/closed_harvest_window_versus_half_open_lease_blackout
        """
        ctx = owned_tract(api)
        lease = create_lease(api, ctx.property_id, **LEASE_ONE)
        activate_lease(api, lease["id"])
        block = reserve_block(
            api,
            ctx.stand_id,
            planned_start_date="2027-12-01",
            planned_end_date="2027-12-31",
            planned_tons=500.00,
        )

        response = api.commit_harvest_block(
            block["id"], None, make_forest_manager_headers()
        )
        committed = validate_success(response, 200)

        assert committed["status"] == "COMMITTED"
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            committed_tons=500.00,
            reserved_tons=0.00,
            available_tons=4147.12,
        )

    def test_a_window_ending_on_the_included_blackout_start_is_refused(self, api):
        """A window closing on 2027-06-01 intersects a blackout that starts there inclusively.

        PRD: "the block's closed window must not intersect the half-open hunting blackout of any `ACTIVE` recreational lease on the property, or the commit is refused with `ERR_LEASE_BLACKOUT_CONFLICT`"

        Design: Difficulty/resource_temporal_overlap/closed_harvest_window_versus_half_open_lease_blackout
        """
        ctx = owned_tract(api)
        lease = create_lease(api, ctx.property_id, **LEASE_ONE)
        activate_lease(api, lease["id"])
        second_stand = _cruise_second_stand(api, ctx.property_id)
        block = reserve_block(
            api,
            second_stand["id"],
            planned_start_date="2027-03-01",
            planned_end_date="2027-06-01",
            planned_tons=500.00,
        )

        response = api.commit_harvest_block(
            block["id"], None, make_forest_manager_headers()
        )
        validate_error(response, ApiErrorId.LEASE_BLACKOUT_CONFLICT.value, 409)

        assert read_block(api, block["id"])["status"] == "RESERVED"
        assert_stand_partition(
            read_stand(api, second_stand["id"]),
            committed_tons=0.00,
            reserved_tons=500.00,
            available_tons=4147.12,
        )
        assert read_lease(api, lease["id"])["status"] == "ACTIVE"


class TestTerminationRefundsTheProratedRent:
    """Terminating on the first day of the term earns nothing and refunds everything."""

    def test_activation_charges_the_prorated_rent_for_a_short_term(self, api):
        """A 184-day term pays 6805.48 of a 13500.00 annual rent.

        PRD: "a term shorter than a year pays pro rata, and a term longer than a year pays one full year up front"

        Design: Difficulty/compensating_invariant/lease_termination_at_term_start_refunds_the_whole_prorated_rent
        """
        ctx = owned_tract(api)
        lease = create_lease(api, ctx.property_id, **SHORT_LEASE)

        activated = activate_lease(api, lease["id"])

        assert activated["term_days"] == 184
        assert_money(activated["annual_rent_usd"], 13500.00, "annual_rent_usd")
        assert_money(
            activated["first_year_prorated_rent_usd"],
            6805.48,
            "first_year_prorated_rent_usd",
        )
        assert_fund_cash(read_fund(api, ctx.fund_id), cash_balance_usd=306805.48)

    def test_terminating_on_the_first_day_refunds_the_whole_prorated_rent(self, api):
        """Earned rent measured to an exclusive first day is zero, so the whole charge comes back.

        PRD: "Earned rent is measured to that date exclusive: `earned_rent_usd` is `annual_rent_usd` multiplied by the whole number of days from `term_start_date` to `termination_effective_date`, divided by 365, rounded half-up to two decimals, and `refunded_rent_usd` is `first_year_prorated_rent_usd` less `earned_rent_usd`, rounded half-up to two decimals."

        Design: Difficulty/compensating_invariant/lease_termination_at_term_start_refunds_the_whole_prorated_rent
        """
        ctx = owned_tract(api)
        lease = create_lease(api, ctx.property_id, **SHORT_LEASE)
        activate_lease(api, lease["id"])

        terminated = terminate_lease(api, lease["id"], "2026-08-01")

        assert terminated["status"] == "TERMINATED"
        assert_money(terminated["refunded_rent_usd"], 6805.48, "refunded_rent_usd")
        assert_money(terminated["earned_rent_usd"], 0.00, "earned_rent_usd")

    def test_the_refund_returns_the_fund_to_its_pre_lease_position(self, api):
        """Cash and operating cash both come back to where the acquisition left them.

        PRD: "The refund is debited from both the fund's `cash_balance_usd` and its `net_operating_cash_usd`, subject to the cash guard of §2.11, and the leased acreage is released from the coverage cap along with the blackout from the commit gate."

        Design: Difficulty/compensating_invariant/lease_termination_at_term_start_refunds_the_whole_prorated_rent
        """
        ctx = owned_tract(api)
        lease = create_lease(api, ctx.property_id, **SHORT_LEASE)
        activate_lease(api, lease["id"])

        terminate_lease(api, lease["id"], "2026-08-01")

        fund = read_fund(api, ctx.fund_id)
        assert_fund_cash(
            fund, cash_balance_usd=300000.00, net_operating_cash_usd=0.00
        )
        assert_bps(fund["cash_yield_bps"], 0, "cash_yield_bps")
        assert read_lease(api, lease["id"])["status"] == "TERMINATED"
