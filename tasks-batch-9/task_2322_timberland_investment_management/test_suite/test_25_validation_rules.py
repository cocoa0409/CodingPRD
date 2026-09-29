"""Input rules: required methodology inputs, per-stand plot numbering, coverage caps and guard ordering."""

from test_helpers import (
    ApiErrorId,
    assert_bps,
    assert_fund_cash,
    assert_money,
    assert_pagination_meta,
    assert_stand_partition,
    assert_tons,
    assert_tons_per_acre,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    cruise_plot_payload,
    harvest_block_payload,
    income_appraisal_submit_payload,
    recreational_lease_payload,
)
from test_helpers.fixtures import (
    activate_lease,
    create_lease,
    create_stand,
    cruised_stand,
    open_cruise_stand,
    owned_tract,
    read_block,
    read_fund,
    read_lease,
    read_property,
    read_stand,
    reserve_block,
    stand_version,
)
from test_helpers.test_users import (
    make_appraiser_headers,
    make_forest_manager_headers,
    make_fund_admin_headers,
)

SECOND_STAND = {"stand_code": "PC-02", "acres": 90.00}
SHARED_TERM = {"term_start_date": "2027-01-01", "term_end_date": "2028-01-01"}
FIRST_CLUB = dict(
    SHARED_TERM,
    lessee_name="Piney Creek Hunt Club",
    leased_acres=400.00,
    rent_per_acre_usd=22.50,
)
SECOND_CLUB = dict(
    SHARED_TERM,
    lessee_name="Bear Hollow Sportsmen",
    leased_acres=400.00,
    rent_per_acre_usd=22.50,
)
THIRD_CLUB = dict(
    SHARED_TERM,
    lessee_name="Longleaf Bow Hunters",
    leased_acres=200.00,
    rent_per_acre_usd=22.50,
)
OVERSIZED_LATER_BLOCK = {
    "planned_start_date": "2032-06-01",
    "planned_end_date": "2032-09-30",
    "planned_tons": 9000.00,
    "product_mix": "MIXED",
    "expected_stumpage_price_usd_per_ton": 58.00,
    "price_index_factor": 1.05,
    "expected_haul_distance_miles": 140,
}


class TestIncomeAppraisalsNeedBothInputs:
    """Direct capitalisation cannot run without a capitalisation rate."""

    def test_an_income_submission_without_a_cap_rate_is_incomplete(self, api):
        """Supplying the rate on the retry produces the capitalised value.

        PRD: "Under `INCOME`, the required inputs are `stabilized_noi_usd` and `cap_rate_bps`, and `appraised_value_usd` is `stabilized_noi_usd` divided by the quantity `cap_rate_bps` divided by 10,000 — direct capitalisation — rounded half-up to two decimals."

        Design: Corner/validations/income_appraisal_without_a_cap_rate_is_incomplete
        """
        ctx = cruised_stand(api)
        before = read_property(api, ctx.property_id)

        response = api.appraisal_action(
            ctx.property_id,
            {
                "action": "SUBMIT",
                "appraisal_methodology": "INCOME",
                "stabilized_noi_usd": 210000.00,
            },
            make_appraiser_headers("appraiser-1"),
        )

        validate_error(response, ApiErrorId.APPRAISAL_INPUTS_INCOMPLETE.value, 422)
        refused = read_property(api, ctx.property_id)
        assert refused["appraisal_status"] == "NONE"
        assert refused["appraisal_methodology"] is None
        assert refused["version"] == before["version"]

        submitted = validate_success(
            api.appraisal_action(
                ctx.property_id,
                income_appraisal_submit_payload(),
                make_appraiser_headers("appraiser-1"),
            ),
            200,
        )

        assert submitted["appraisal_status"] == "SUBMITTED"
        assert_money(
            submitted["appraised_value_usd"], 3652173.91, "appraised_value_usd"
        )
        assert submitted["appraisal_submitted_by_user_id"] == "appraiser-1"


class TestPlotNumbersAreScopedToTheirStand:
    """Uniqueness is per stand, so every cruise starts again at plot one."""

    def test_plot_number_one_is_accepted_on_each_stand_independently(self, api):
        """Two stands each carry a plot one, and the numbering only clashes within a stand.

        PRD: "A duplicate `plot_number` on the same stand is refused with `ERR_DUPLICATE_PLOT_NUMBER`, and any attempt to add a plot to a stand that has left `CRUISE_OPEN` is refused with `ERR_CRUISE_ALREADY_CLOSED`."

        Design: Corner/validations/plot_number_one_is_allowed_on_each_stand
        """
        ctx = open_cruise_stand(api)
        second = create_stand(api, ctx.property_id, **SECOND_STAND)
        assert read_stand(api, ctx.stand_id)["status"] == "CRUISE_OPEN"
        assert second["status"] == "CRUISE_OPEN"

        first_plot = validate_success(
            api.create_cruise_plot(
                cruise_plot_payload(ctx.stand_id, plot_number=1, tons_per_acre=41.37, defect_pct=6.5),
                make_forest_manager_headers(),
            ),
            201,
        )
        mirrored_plot = validate_success(
            api.create_cruise_plot(
                cruise_plot_payload(second["id"], plot_number=1, tons_per_acre=41.37, defect_pct=6.5),
                make_forest_manager_headers(),
            ),
            201,
        )
        extra_plot = validate_success(
            api.create_cruise_plot(
                cruise_plot_payload(second["id"], plot_number=2, tons_per_acre=38.94, defect_pct=4.25),
                make_forest_manager_headers(),
            ),
            201,
        )

        assert_tons_per_acre(
            first_plot["net_tons_per_acre"], 38.681, "net_tons_per_acre"
        )
        assert_tons_per_acre(
            mirrored_plot["net_tons_per_acre"], 38.681, "net_tons_per_acre"
        )
        assert len({first_plot["id"], mirrored_plot["id"], extra_plot["id"]}) == 3
        parent = read_stand(api, ctx.stand_id)
        sibling = read_stand(api, second["id"])
        assert parent["plot_count"] == 1
        assert sibling["plot_count"] == 2
        assert parent["status"] == "CRUISE_OPEN"
        assert sibling["status"] == "CRUISE_OPEN"
        assert_tons(parent["net_merch_tons"], 0.00, "net_merch_tons")
        assert_tons(sibling["net_merch_tons"], 0.00, "net_merch_tons")
        assert parent["version"] == 1

    def test_a_repeated_plot_number_on_one_stand_is_refused(self, api):
        """The clash is reported only when the number repeats on the same stand.

        PRD: "Each plot cites its `stand_id`, an integer `plot_number` of at least 1 that must be unique within that stand, the gross measured `tons_per_acre` (strictly positive, two decimals), the observed `defect_pct` from 0 through 100 at two decimals, and the field `measured_at` instant in ISO 8601 UTC."

        Design: Corner/validations/plot_number_one_is_allowed_on_each_stand
        """
        ctx = open_cruise_stand(api)
        validate_success(
            api.create_cruise_plot(
                cruise_plot_payload(ctx.stand_id, plot_number=1),
                make_forest_manager_headers(),
            ),
            201,
        )

        response = api.create_cruise_plot(
            cruise_plot_payload(ctx.stand_id, plot_number=1, tons_per_acre=39.00),
            make_forest_manager_headers(),
        )

        validate_error(response, ApiErrorId.DUPLICATE_PLOT_NUMBER.value, 409)
        assert read_stand(api, ctx.stand_id)["plot_count"] == 1
        _plots, meta = validate_paginated(
            api.list_stand_cruise_plots(ctx.stand_id, make_forest_manager_headers())
        )
        assert_pagination_meta(meta, total_count=1)


class TestCoverageCapCountsEveryOverlappingLease:
    """Three concurrent clubs breach four fifths of the tract in aggregate."""

    def test_the_third_overlapping_lease_breaches_the_capacity_in_aggregate(self, api):
        """Eight hundred acres activate; the next two hundred cross the 960-acre cap.

        PRD: "The sum of those overlapping leases' `leased_acres` plus the candidate's own `leased_acres`, rounded half-up to two decimals, must be less than or equal to capacity; equality is allowed and only a strictly greater total is refused, with `ERR_LEASE_ACREAGE_EXCEEDED`."

        Design: Corner/validations/three_overlapping_leases_breach_the_coverage_cap_in_aggregate
        """
        ctx = owned_tract(api)
        first = create_lease(api, ctx.property_id, **FIRST_CLUB)
        second = create_lease(api, ctx.property_id, **SECOND_CLUB)
        # A PENDING lease already occupies acreage against the cap, so the two
        # four-hundred-acre clubs are activated before the third is offered.
        for lease in (first, second):
            activated = activate_lease(api, lease["id"])
            assert activated["status"] == "ACTIVE"
            assert_money(activated["annual_rent_usd"], 9000.00, "annual_rent_usd")
            assert_money(
                activated["first_year_prorated_rent_usd"],
                9000.00,
                "first_year_prorated_rent_usd",
            )
        third = validate_success(
            api.create_recreational_lease(
                recreational_lease_payload(ctx.property_id, **THIRD_CLUB),
                make_fund_admin_headers(),
            ),
            201,
        )

        response = api.activate_recreational_lease(
            third["id"], None, make_fund_admin_headers()
        )

        validate_error(response, ApiErrorId.LEASE_ACREAGE_EXCEEDED.value, 422)
        refused = read_lease(api, third["id"])
        assert refused["status"] == "PENDING"
        assert refused["first_year_prorated_rent_usd"] is None
        assert_money(refused["annual_rent_usd"], 4500.00, "annual_rent_usd")
        fund = read_fund(api, ctx.fund_id)
        assert_fund_cash(
            fund, cash_balance_usd=318000.00, net_operating_cash_usd=18000.00
        )
        assert_bps(fund["cash_yield_bps"], 360, "cash_yield_bps")


class TestTheVersionGuardOutranksTheTonnageCheck:
    """A stale stand version is reported before the headroom is even weighed."""

    def test_the_stale_version_is_reported_ahead_of_the_tonnage_ceiling(self, api):
        """The same oversized reservation yields 412 when stale and 422 when fresh.

        PRD: "If it does not equal the stand's current `version`, the reservation is rejected with `ERR_STALE_STAND_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_stand_version_outranks_the_tonnage_capacity_check
        """
        ctx = cruised_stand(api)
        stale = stand_version(api, ctx.stand_id)
        first = reserve_block(api, ctx.stand_id, planned_tons=1000.00)
        fresh = stand_version(api, ctx.stand_id)
        assert fresh == stale + 1
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            reserved_tons=1000.00,
            available_tons=3647.12,
        )

        stale_attempt = api.create_harvest_block(
            harvest_block_payload(ctx.stand_id, stale, **OVERSIZED_LATER_BLOCK),
            make_forest_manager_headers(),
        )
        validate_error(stale_attempt, ApiErrorId.STALE_STAND_VERSION.value, 412)

        fresh_attempt = api.create_harvest_block(
            harvest_block_payload(ctx.stand_id, fresh, **OVERSIZED_LATER_BLOCK),
            make_forest_manager_headers(),
        )
        validate_error(fresh_attempt, ApiErrorId.INSUFFICIENT_AVAILABLE_TONS.value, 422)

        after = read_stand(api, ctx.stand_id)
        assert after["version"] == fresh
        assert_stand_partition(
            after, reserved_tons=1000.00, available_tons=3647.12
        )
        assert read_block(api, first["id"])["status"] == "RESERVED"
        blocks, meta = validate_paginated(
            api.list_stand_harvest_blocks(ctx.stand_id, make_forest_manager_headers())
        )
        assert len(blocks) == 1, "neither refused reservation created a block"
        assert_pagination_meta(meta, total_count=1)
