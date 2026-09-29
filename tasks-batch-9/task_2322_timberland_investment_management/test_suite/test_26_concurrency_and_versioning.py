"""Version guards and read-after-write: stale writers lose, and a closing is visible immediately."""

from test_helpers import (
    ApiErrorId,
    assert_bps,
    assert_fund_cash,
    assert_money,
    assert_pagination_meta,
    assert_stand_partition,
    assert_tons,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    carbon_dedication_payload,
    harvest_block_payload,
    market_appraisal_submit_payload,
    risk_review_payload,
    underwriting_case_payload,
)
from test_helpers.fixtures import (
    approved_case,
    create_carbon_project,
    cruised_stand,
    dedicate,
    fund_version,
    invalidate_appraisal,
    owned_tract,
    property_version,
    read_block,
    read_carbon_project,
    read_dedication,
    read_fund,
    read_investor_report,
    read_property,
    read_stand,
    record_risk_review,
    reserve_block,
    sign_appraisal,
    signed_appraisal,
    stand_version,
    submit_appraisal,
)
from test_helpers.test_users import (
    make_analyst_headers,
    make_carbon_developer_headers,
    make_forest_manager_headers,
    make_fund_admin_headers,
)

FIRST_WINDOW = {
    "planned_start_date": "2027-06-01",
    "planned_end_date": "2027-09-30",
    "planned_tons": 1000.00,
}
SECOND_WINDOW = {
    "planned_start_date": "2032-06-01",
    "planned_end_date": "2032-09-30",
    "planned_tons": 800.00,
    "product_mix": "MIXED",
    "expected_stumpage_price_usd_per_ton": 58.00,
    "price_index_factor": 1.05,
    "expected_haul_distance_miles": 140,
}


class TestTwoWritersReserveTheSameStand:
    """The second writer's view of the stand is one reservation out of date."""

    def test_the_stale_writer_loses_its_block_and_the_retry_succeeds(self, api):
        """The refused reservation leaves no row, and the refreshed one allocates cleanly.

        PRD: "Reserving harvest tonnage requires `expected_stand_version`, carrying the client's last observed `version` of the target stand."

        Design: Corner/cross_cutting_complexity_layers/two_writers_reserving_the_same_stand_lose_one_block_to_the_version_guard
        """
        ctx = cruised_stand(api)
        stale = stand_version(api, ctx.stand_id)
        first = reserve_block(api, ctx.stand_id, **FIRST_WINDOW)
        fresh = stand_version(api, ctx.stand_id)
        assert fresh == stale + 1

        refused = api.create_harvest_block(
            harvest_block_payload(ctx.stand_id, stale, **SECOND_WINDOW),
            make_forest_manager_headers(),
        )

        validate_error(refused, ApiErrorId.STALE_STAND_VERSION.value, 412)
        blocked = read_stand(api, ctx.stand_id)
        assert blocked["version"] == fresh
        assert_stand_partition(
            blocked, reserved_tons=1000.00, available_tons=3647.12
        )
        _blocks, meta = validate_paginated(
            api.list_stand_harvest_blocks(ctx.stand_id, make_forest_manager_headers())
        )
        assert_pagination_meta(meta, total_count=1)

        second = validate_success(
            api.create_harvest_block(
                harvest_block_payload(ctx.stand_id, fresh, **SECOND_WINDOW),
                make_forest_manager_headers(),
            ),
            201,
        )

        assert second["status"] == "RESERVED"
        assert read_block(api, first["id"])["status"] == "RESERVED"
        after = read_stand(api, ctx.stand_id)
        assert after["version"] == fresh + 1
        assert_stand_partition(
            after, reserved_tons=1800.00, available_tons=2847.12
        )


class TestDedicationsShareTheStandVersionGuard:
    """A pledge written against a stale stand would break the partition."""

    def test_a_dedication_on_a_stale_stand_version_is_refused_then_retried(self, api):
        """Both pledges land only once the second one quotes the current version.

        PRD: "Creating a carbon dedication requires the same field, `expected_stand_version`, against the same stand `version`, and a mismatch is likewise rejected with `ERR_STALE_STAND_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/a_dedication_on_a_stale_stand_version_is_refused
        """
        ctx = owned_tract(api)
        project = create_carbon_project(api, ctx.property_id)
        stale = stand_version(api, ctx.stand_id)
        first = dedicate(api, project["id"], ctx.stand_id, dedicated_tons=500.00)
        fresh = stand_version(api, ctx.stand_id)
        assert fresh == stale + 1

        refused = api.create_carbon_dedication(
            carbon_dedication_payload(
                project["id"], ctx.stand_id, stale, dedicated_tons=300.00
            ),
            make_carbon_developer_headers(),
        )

        validate_error(refused, ApiErrorId.STALE_STAND_VERSION.value, 412)
        assert_tons(
            read_carbon_project(api, project["id"])["dedicated_tons_total"],
            500.00,
            "dedicated_tons_total",
        )

        second = validate_success(
            api.create_carbon_dedication(
                carbon_dedication_payload(
                    project["id"], ctx.stand_id, fresh, dedicated_tons=300.00
                ),
                make_carbon_developer_headers(),
            ),
            201,
        )

        assert second["status"] == "PENDING"
        after_stand = read_stand(api, ctx.stand_id)
        assert after_stand["version"] == fresh + 1
        assert_stand_partition(
            after_stand, dedicated_tons=800.00, available_tons=3847.12
        )
        assert_tons(
            read_carbon_project(api, project["id"])["dedicated_tons_total"],
            800.00,
            "dedicated_tons_total",
        )
        for dedication in (first, second):
            row = read_dedication(api, dedication["id"])
            assert row["status"] == "PENDING"
            assert_tons(row["reduced_tons"], 0.00, "reduced_tons")
            assert row["permanence_end_date"] is None


class TestCasesAreOpenedAgainstAFreshProperty:
    """An appraisal cycle moves the property underneath a slow analyst."""

    def test_a_case_authored_against_a_stale_property_version_is_refused(self, api):
        """The refused case leaves no row and the refreshed one values the tract.

        PRD: "Opening an underwriting case requires `expected_property_version`, carrying the client's last observed `version` of the property being underwritten. A mismatch with the property's current `version` is rejected with `ERR_STALE_PROPERTY_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/a_case_authored_against_a_stale_property_version_is_refused
        """
        ctx = cruised_stand(api)
        stale = property_version(api, ctx.property_id)
        submit_appraisal(
            api,
            ctx.property_id,
            market_appraisal_submit_payload(),
            submitter="appraiser-1",
        )
        sign_appraisal(api, ctx.property_id, signer="appraiser-2")
        fresh = property_version(api, ctx.property_id)
        assert fresh == stale + 2

        refused = api.create_underwriting_case(
            underwriting_case_payload(ctx.property_id, stale),
            make_analyst_headers("analyst-1"),
        )

        validate_error(refused, ApiErrorId.STALE_PROPERTY_VERSION.value, 412)
        _cases, meta = validate_paginated(
            api.list_property_underwriting_cases(
                ctx.property_id, make_analyst_headers("analyst-1")
            )
        )
        assert_pagination_meta(meta, total_count=0)

        case = validate_success(
            api.create_underwriting_case(
                underwriting_case_payload(ctx.property_id, fresh),
                make_analyst_headers("analyst-1"),
            ),
            201,
        )

        assert case["status"] == "DRAFT"
        assert case["authored_by_user_id"] == "analyst-1"
        assert case["revision_count"] == 0
        assert_money(
            case["underwritten_value_usd"], 191966.99, "underwritten_value_usd"
        )
        assert read_property(api, ctx.property_id)["version"] == fresh + 1


class TestAcquisitionsAreClosedAgainstAFreshFund:
    """A premium debit moves the fund between the analyst's read and the closing."""

    def test_an_acquisition_on_a_stale_fund_version_is_refused_then_closes(self, api):
        """The stale closing is refused on the version guard, not on cash.

        PRD: "Closing an acquisition requires `expected_fund_version`, carrying the client's last observed `version` of the owning fund. A mismatch with the fund's current `version` is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/an_acquisition_on_a_stale_fund_version_is_refused
        """
        ctx = cruised_stand(api)
        signed_appraisal(api, ctx.property_id, market_appraisal_submit_payload())
        case = approved_case(api, ctx.property_id)
        stale = fund_version(api, ctx.fund_id)

        reviewed = record_risk_review(api, ctx.property_id, risk_review_payload())
        assert_money(reviewed["composite_risk_score"], 66.48, "composite_risk_score")
        assert_money(
            reviewed["insurance_premium_usd"], 26570.21, "insurance_premium_usd"
        )
        fresh = fund_version(api, ctx.fund_id)
        assert fresh == stale + 1
        assert_fund_cash(
            read_fund(api, ctx.fund_id), cash_balance_usd=373429.79
        )

        refused = api.acquire_property(
            ctx.property_id,
            {"underwriting_case_id": case["id"], "expected_fund_version": stale},
            make_fund_admin_headers(),
        )

        validate_error(refused, ApiErrorId.STALE_FUND_VERSION.value, 412)
        assert read_property(api, ctx.property_id)["status"] == "APPROVED_FOR_BID"

        closed = validate_success(
            api.acquire_property(
                ctx.property_id,
                {"underwriting_case_id": case["id"], "expected_fund_version": fresh},
                make_fund_admin_headers(),
            ),
            200,
        )

        assert closed["status"] == "OWNED"
        fund = read_fund(api, ctx.fund_id)
        assert_fund_cash(
            fund,
            cash_balance_usd=273429.79,
            net_operating_cash_usd=-26570.21,
            nav_usd=4173429.79,
        )


class TestTheStaleValuationCounterIsRederived:
    """Every appraisal write re-derives the fund's exposure counter."""

    def test_the_counter_tracks_each_appraisal_write_in_turn(self, api):
        """Invalidation raises the count, resubmission holds it, countersignature clears it.

        PRD: "`valuation_basis_stale_count` is the number of the fund's properties whose `status` is `OWNED` or `HBU_MARKETED` and whose `appraisal_status` is anything other than `SIGNED`."

        Design: Corner/cross_cutting_complexity_layers/the_stale_valuation_counter_is_re_derived_on_every_appraisal_write
        """
        ctx = owned_tract(api)
        opening = read_fund(api, ctx.fund_id)
        assert opening["valuation_basis_stale_count"] == 0
        assert_money(opening["nav_usd"], 4200000.00, "nav_usd")

        invalidate_appraisal(api, ctx.property_id, actor="appraiser-1")
        staled = read_fund(api, ctx.fund_id)
        assert staled["valuation_basis_stale_count"] == 1
        assert_money(staled["nav_usd"], 3732000.00, "nav_usd")

        submit_appraisal(
            api,
            ctx.property_id,
            market_appraisal_submit_payload(),
            submitter="appraiser-1",
        )
        resubmitted = read_fund(api, ctx.fund_id)
        assert resubmitted["valuation_basis_stale_count"] == 1
        assert_money(resubmitted["nav_usd"], 400000.00, "nav_usd")

        signed = sign_appraisal(api, ctx.property_id, signer="appraiser-2")

        assert signed["appraisal_status"] == "SIGNED"
        assert signed["appraisal_signed_by_user_id"] == "appraiser-2"
        restored = read_fund(api, ctx.fund_id)
        assert restored["valuation_basis_stale_count"] == 0
        assert_money(restored["nav_usd"], 4200000.00, "nav_usd")
        assert_fund_cash(restored, cash_balance_usd=300000.00)

    def test_the_investor_report_agrees_with_the_fund_on_the_counter(self, api):
        """A staled valuation shows up on the reporting pack at the haircut.

        PRD: "Both are recomputed whenever the fund or the investor report is read, and both are also maintained incrementally by the transitions that cause them to move."

        Design: Corner/cross_cutting_complexity_layers/the_stale_valuation_counter_is_re_derived_on_every_appraisal_write
        """
        ctx = owned_tract(api)
        invalidate_appraisal(api, ctx.property_id, actor="appraiser-1")

        report = read_investor_report(api, ctx.fund_id)

        assert report["valuation_basis_stale_count"] == 1
        assert report["owned_property_count"] == 1
        assert_money(
            report["appraised_value_total_usd"], 3432000.00, "appraised_value_total_usd"
        )
        assert_money(report["nav_usd"], 3732000.00, "nav_usd")
        assert_tons(
            report["standing_inventory_tons"], 4647.12, "standing_inventory_tons"
        )


class TestTheClosingIsVisibleImmediately:
    """The closing response and the next reads describe the same position."""

    def test_the_acquire_response_already_shows_the_closed_position(self, api):
        """Ownership, price and the market-access grading are all in the response body.

        PRD: "On success the property moves from `APPROVED_FOR_BID` to `OWNED`, its `acquisition_price_usd` is set to the case's `bid_price_usd`, the same amount is debited from the fund's `cash_balance_usd`, the fund's `nav_usd` is recomputed, and the fund's `version` is incremented."

        Design: Corner/consistency_model/the_acquire_response_already_shows_the_closed_position
        """
        ctx = cruised_stand(api)
        signed_appraisal(api, ctx.property_id, market_appraisal_submit_payload())
        case = approved_case(api, ctx.property_id)
        before = fund_version(api, ctx.fund_id)

        closed = validate_success(
            api.acquire_property(
                ctx.property_id,
                {"underwriting_case_id": case["id"], "expected_fund_version": before},
                make_fund_admin_headers(),
            ),
            200,
        )

        assert closed["status"] == "OWNED"
        assert_money(
            closed["acquisition_price_usd"], 100000.00, "acquisition_price_usd"
        )
        assert closed["market_access_tier"] == "TIER_B"
        assert_money(
            closed["market_access_discount_pct"], 4.5, "market_access_discount_pct"
        )

        fund = read_fund(api, ctx.fund_id)
        assert fund["version"] == before + 1
        assert_fund_cash(
            fund,
            cash_balance_usd=300000.00,
            net_operating_cash_usd=0.00,
            nav_usd=4200000.00,
        )
        assert_bps(fund["cash_yield_bps"], 0, "cash_yield_bps")

        reread = validate_success(
            api.get_property(ctx.property_id, make_analyst_headers("analyst-1")), 200
        )
        assert reread["status"] == "OWNED"
        assert reread["appraisal_status"] == "SIGNED"
        assert_money(reread["appraised_value_usd"], 3900000.00, "appraised_value_usd")

