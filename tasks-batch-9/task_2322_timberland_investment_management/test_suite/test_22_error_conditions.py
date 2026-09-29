"""Refusal conditions: each guarded operation names its own error and leaves the books untouched."""

from test_helpers import (
    ApiErrorId,
    assert_acres,
    assert_bps,
    assert_fund_cash,
    assert_money,
    assert_pagination_meta,
    assert_property_dimensions,
    assert_stand_partition,
    assert_tons,
    assert_tons_per_acre,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    CANONICAL_CRUISE_PLOTS,
    carbon_project_payload,
    cruise_plot_payload,
    harvest_block_payload,
    hbu_parcel_payload,
    market_appraisal_submit_payload,
    recreational_lease_payload,
    underwriting_case_payload,
)
from test_helpers.fixtures import (
    advance_carbon_project,
    approved_case,
    close_cruise,
    commit_block,
    create_carbon_project,
    create_property,
    create_stand,
    cruised_stand,
    dedicate,
    fund_version,
    identify_parcel,
    invalidate_appraisal,
    open_cruise_stand,
    owned_tract,
    property_version,
    read_block,
    read_carbon_project,
    read_case,
    read_dedication,
    read_fund,
    read_hazard_event,
    read_parcel,
    read_property,
    read_stand,
    record_cruise_plot,
    registered_carbon_project,
    report_hazard,
    reserve_block,
    settle_hazard,
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

BEAR_HOLLOW = {"name": "Bear Hollow Tract"}
BEAR_HOLLOW_STAND = {"stand_code": "BH-01"}
OUTSIDE_BLACKOUT_LEASE = {
    "lessee_name": "Big Piney Hunt Club",
    "leased_acres": 400.00,
    "term_start_date": "2027-01-01",
    "term_end_date": "2028-01-01",
    "blackout_start_date": "2027-11-01",
    "blackout_end_date": "2028-02-01",
}


def _cruise_a_second_tract(api, fund_id):
    """A second cruise-closed tract in the same fund, appraised and approved for bid."""
    tract = create_property(api, fund_id, **BEAR_HOLLOW)
    stand = create_stand(api, tract["id"], **BEAR_HOLLOW_STAND)
    for plot in CANONICAL_CRUISE_PLOTS:
        record_cruise_plot(api, stand["id"], **plot)
    close_cruise(api, stand["id"])
    signed_appraisal(api, tract["id"])
    case = approved_case(api, tract["id"])
    return tract, stand, case


def _reported_wildfire(api):
    """A cruise-closed stand carrying one reported thousand-ton wildfire loss."""
    ctx = cruised_stand(api)
    event = report_hazard(api, ctx.stand_id, damaged_tons=1000.00)
    assert_tons(event["salvageable_tons"], 350.00, "salvageable_tons")
    assert_money(event["insurance_claim_usd"], 13500.00, "insurance_claim_usd")
    assert_tons(
        event["inventory_shortfall_tons"], 0.00, "inventory_shortfall_tons"
    )
    return ctx, event


class TestOwnershipGatesTheCarbonProgram:
    """Carbon can only be pledged on ground the fund already holds."""

    def test_a_prospect_tract_cannot_open_a_carbon_project(self, api):
        """An unowned tract is refused before any project row exists.

        PRD: "The property must be `OWNED` or `HBU_MARKETED`, or the request is refused with `ERR_PROPERTY_NOT_OWNED`."

        Design: Corner/errors/property_not_owned_blocks_carbon_project_creation
        """
        ctx = cruised_stand(api)
        before = property_version(api, ctx.property_id)

        response = api.create_carbon_project(
            carbon_project_payload(ctx.property_id), make_carbon_developer_headers()
        )

        validate_error(response, ApiErrorId.PROPERTY_NOT_OWNED.value, 409)
        assert_property_dimensions(
            read_property(api, ctx.property_id), status="PROSPECT"
        )
        assert read_property(api, ctx.property_id)["version"] == before
        projects, meta = validate_paginated(
            api.list_property_carbon_projects(
                ctx.property_id, make_carbon_developer_headers()
            )
        )
        assert projects == [], "the refusal left no carbon project behind"
        assert_pagination_meta(meta, total_count=0)
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            dedicated_tons=0.00,
            available_tons=4647.12,
        )


class TestHbuListingRequiresASignedValuation:
    """Land is not marketed without an independent valuation standing behind it."""

    def test_a_staled_appraisal_blocks_the_listing_and_a_fresh_one_unblocks_it(self, api):
        """The listing is refused while the appraisal is stale and succeeds once re-signed.

        PRD: "Listing moves the parcel from `IDENTIFIED` to `LISTED` and requires the property to be `OWNED` or `HBU_MARKETED` — otherwise `ERR_PROPERTY_NOT_OWNED` — and its `appraisal_status` to be `SIGNED`, since land is not marketed without an independent valuation behind it; an unsigned appraisal is refused with `ERR_APPRAISAL_NOT_SIGNED`."

        Design: Corner/errors/a_stale_appraisal_blocks_the_hbu_listing
        """
        ctx = owned_tract(api)
        parcel = identify_parcel(api, ctx.stand_id, acres=40.00)
        assert parcel["status"] == "IDENTIFIED"
        staled = invalidate_appraisal(api, ctx.property_id)
        assert staled["appraisal_status"] == "STALE"

        response = api.advance_hbu_parcel(
            parcel["id"], {"action": "LIST"}, make_fund_admin_headers()
        )

        validate_error(response, ApiErrorId.APPRAISAL_NOT_SIGNED.value, 409)
        assert read_parcel(api, parcel["id"])["status"] == "IDENTIFIED"
        assert_property_dimensions(read_property(api, ctx.property_id), status="OWNED")

        submit_appraisal(api, ctx.property_id, market_appraisal_submit_payload())
        sign_appraisal(api, ctx.property_id)
        listed = validate_success(
            api.advance_hbu_parcel(
                parcel["id"], {"action": "LIST"}, make_fund_admin_headers()
            ),
            200,
        )

        assert listed["status"] == "LISTED"
        assert_property_dimensions(
            read_property(api, ctx.property_id),
            status="HBU_MARKETED",
            appraisal_status="SIGNED",
        )
        assert_stand_partition(
            read_stand(api, ctx.stand_id), hbu_withdrawn_tons=0.00
        )


class TestRegisteredProjectsAreClosedToNewPledges:
    """Once registered, a project no longer accepts inventory."""

    def test_a_registered_project_refuses_a_further_dedication(self, api):
        """The pledge is refused on project state, not on the version guard.

        PRD: "The project must still be in `DRAFT` or `VALIDATION`, or the dedication is refused with `ERR_CARBON_PROJECT_NOT_OPEN_FOR_DEDICATION`."

        Design: Corner/errors/dedication_after_registration_is_not_open
        """
        ctx = owned_tract(api)
        carbon = registered_carbon_project(api, ctx.property_id, ctx.stand_id)
        assert carbon.project["status"] == "REGISTERED"
        assert_tons(carbon.project["buffer_pool_tons"], 90.00, "buffer_pool_tons")

        response = api.create_carbon_dedication(
            {
                "carbon_project_id": carbon.project_id,
                "stand_id": ctx.stand_id,
                "dedicated_tons": 100.00,
                "expected_stand_version": stand_version(api, ctx.stand_id),
            },
            make_carbon_developer_headers(),
        )

        validate_error(
            response,
            ApiErrorId.CARBON_PROJECT_NOT_OPEN_FOR_DEDICATION.value,
            409,
        )
        unchanged = read_carbon_project(api, carbon.project_id)
        assert_tons(unchanged["dedicated_tons_total"], 500.00, "dedicated_tons_total")
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            dedicated_tons=500.00,
            available_tons=4147.12,
        )
        active = read_dedication(api, carbon.dedication_id)
        assert active["status"] == "ACTIVE"
        assert active["permanence_end_date"] == "2056-08-01"


class TestPlotNumbersAreUniquePerStand:
    """A repeated plot number on the same stand is refused and changes nothing."""

    def test_a_repeated_plot_number_is_refused_and_the_sample_stands(self, api):
        """The third plot keeps its recorded figure and the sample stays at three.

        PRD: "A duplicate `plot_number` on the same stand is refused with `ERR_DUPLICATE_PLOT_NUMBER`, and any attempt to add a plot to a stand that has left `CRUISE_OPEN` is refused with `ERR_CRUISE_ALREADY_CLOSED`."

        Design: Corner/errors/duplicate_plot_number_on_the_same_stand_is_rejected
        """
        ctx = open_cruise_stand(api)
        for plot in CANONICAL_CRUISE_PLOTS[:3]:
            record_cruise_plot(api, ctx.stand_id, **plot)

        response = api.create_cruise_plot(
            cruise_plot_payload(
                ctx.stand_id,
                plot_number=3,
                tons_per_acre=51.00,
                defect_pct=0.0,
                measured_at="2026-07-20T00:00:00Z",
            ),
            make_forest_manager_headers(),
        )

        validate_error(response, ApiErrorId.DUPLICATE_PLOT_NUMBER.value, 409)
        stand = read_stand(api, ctx.stand_id)
        assert stand["status"] == "CRUISE_OPEN"
        assert stand["plot_count"] == 3
        plots, meta = validate_paginated(
            api.list_stand_cruise_plots(ctx.stand_id, make_forest_manager_headers())
        )
        assert_pagination_meta(meta, total_count=3)
        assert [row["plot_number"] for row in plots] == [1, 2, 3]
        assert_tons_per_acre(
            plots[2]["net_tons_per_acre"], 39.764, "net_tons_per_acre"
        )


class TestHarvestWindowShape:
    """The operating window is closed at both ends, so a single day is a legal window."""

    def test_a_window_that_ends_before_it_starts_is_refused(self, api):
        """A reversed window is refused and a same-day window is accepted.

        PRD: "The window must be coherent: `planned_end_date` must be on or after `planned_start_date`, since the window is closed at both ends, and a window that ends before it starts yields `ERR_HARVEST_WINDOW_INVALID`."

        Design: Corner/errors/harvest_window_end_before_start_is_rejected
        """
        ctx = cruised_stand(api)
        version = stand_version(api, ctx.stand_id)

        response = api.create_harvest_block(
            harvest_block_payload(
                ctx.stand_id,
                version,
                planned_start_date="2027-09-30",
                planned_end_date="2027-06-01",
                planned_tons=500.00,
            ),
            make_forest_manager_headers(),
        )

        validate_error(response, ApiErrorId.HARVEST_WINDOW_INVALID.value, 422)
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            reserved_tons=0.00,
            available_tons=4647.12,
        )
        assert read_stand(api, ctx.stand_id)["version"] == version

        accepted = reserve_block(
            api,
            ctx.stand_id,
            planned_start_date="2027-06-01",
            planned_end_date="2027-06-01",
            planned_tons=500.00,
        )

        assert accepted["status"] == "RESERVED"
        assert accepted["years_to_start"] == 0
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            reserved_tons=500.00,
            available_tons=4147.12,
        )


class TestLeaseTermShape:
    """The blackout must sit entirely inside the term it belongs to."""

    def test_a_blackout_running_past_the_term_is_refused(self, api):
        """A blackout ending after the term is refused; pulling it back inside is accepted.

        PRD: "The term must be non-empty — `term_end_date` strictly after `term_start_date` — and the blackout must be non-empty and must sit entirely inside the term; a term or blackout that violates any of those conditions is refused with `ERR_LEASE_TERM_INVALID`."

        Design: Corner/errors/lease_blackout_outside_the_term_is_rejected
        """
        ctx = owned_tract(api)

        response = api.create_recreational_lease(
            recreational_lease_payload(ctx.property_id, **OUTSIDE_BLACKOUT_LEASE),
            make_fund_admin_headers(),
        )

        validate_error(response, ApiErrorId.LEASE_TERM_INVALID.value, 422)
        leases, meta = validate_paginated(
            api.list_property_recreational_leases(
                ctx.property_id, make_fund_admin_headers()
            )
        )
        assert leases == [], "the refusal left no lease behind"
        assert_pagination_meta(meta, total_count=0)

        accepted = validate_success(
            api.create_recreational_lease(
                recreational_lease_payload(
                    ctx.property_id,
                    **{**OUTSIDE_BLACKOUT_LEASE, "blackout_end_date": "2027-12-15"},
                ),
                make_fund_admin_headers(),
            ),
            201,
        )

        assert accepted["status"] == "PENDING"
        assert accepted["term_days"] == 365
        assert_money(accepted["annual_rent_usd"], 9000.00, "annual_rent_usd")
        assert accepted["first_year_prorated_rent_usd"] is None
        assert_fund_cash(read_fund(api, ctx.fund_id), cash_balance_usd=300000.00)


class TestHbuCarveOutLeavesARetainedFloor:
    """Five acres must stay behind on the parent stand."""

    def test_a_parcel_leaving_under_five_acres_is_refused_at_the_boundary(self, api):
        """One hundred sixteen acres of one hundred twenty is refused; one hundred fifteen is not.

        PRD: "and the carve-out must leave at least five acres behind on the parent stand: `acres` must be no greater than the stand's `acres` less five, and a parcel that would leave less is refused with `ERR_HBU_ACRES_EXCEED_STAND`."

        Design: Corner/errors/hbu_parcel_leaving_under_five_acres_is_rejected
        """
        ctx = owned_tract(api)

        response = api.create_hbu_parcel(
            hbu_parcel_payload(
                ctx.stand_id,
                parcel_code="HBU-TOO-BIG",
                acres=116.00,
                ask_price_usd=754000.00,
            ),
            make_fund_admin_headers(),
        )

        validate_error(response, ApiErrorId.HBU_ACRES_EXCEED_STAND.value, 422)

        accepted = validate_success(
            api.create_hbu_parcel(
                hbu_parcel_payload(
                    ctx.stand_id,
                    parcel_code="HBU-MAX",
                    acres=115.00,
                    ask_price_usd=747500.00,
                ),
                make_fund_admin_headers(),
            ),
            201,
        )

        assert accepted["status"] == "IDENTIFIED"
        assert_acres(accepted["acres"], 115.00, "acres")
        assert_tons(accepted["withdrawn_tons"], 0.00, "withdrawn_tons")
        assert_acres(read_stand(api, ctx.stand_id)["acres"], 120.00, "parent acres")
        assert_property_dimensions(read_property(api, ctx.property_id), status="OWNED")


class TestAcquisitionCitesItsOwnCase:
    """A case authored against another tract cannot close this one."""

    def test_a_case_from_another_tract_is_refused_and_the_matched_pair_closes(self, api):
        """The mismatched closing is refused, then the correctly paired one succeeds.

        PRD: "the case's `property_id` must equal the property named in the path, or the closing is refused with `ERR_CASE_PROPERTY_MISMATCH`"

        Design: Corner/errors/acquire_with_another_property_case_is_rejected
        """
        first = cruised_stand(api)
        signed_appraisal(api, first.property_id)
        first_case = approved_case(api, first.property_id)
        _, _, second_case = _cruise_a_second_tract(api, first.fund_id)

        response = api.acquire_property(
            first.property_id,
            {
                "underwriting_case_id": second_case["id"],
                "expected_fund_version": fund_version(api, first.fund_id),
            },
            make_fund_admin_headers(),
        )

        validate_error(response, ApiErrorId.CASE_PROPERTY_MISMATCH.value, 422)
        assert_fund_cash(read_fund(api, first.fund_id), cash_balance_usd=400000.00)
        assert_property_dimensions(
            read_property(api, first.property_id), status="APPROVED_FOR_BID"
        )

        closed = validate_success(
            api.acquire_property(
                first.property_id,
                {
                    "underwriting_case_id": first_case["id"],
                    "expected_fund_version": fund_version(api, first.fund_id),
                },
                make_fund_admin_headers(),
            ),
            200,
        )

        assert closed["status"] == "OWNED"
        assert_money(
            closed["acquisition_price_usd"], 100000.00, "acquisition_price_usd"
        )
        assert_fund_cash(
            read_fund(api, first.fund_id),
            cash_balance_usd=300000.00,
            net_operating_cash_usd=0.00,
        )

    def test_the_neighbouring_tract_is_left_approved_for_bid(self, api):
        """Lending its case to another closing leaves the second tract untouched.

        PRD: "The cited case must be `APPROVED`, or the closing is refused with `ERR_UNDERWRITING_NOT_APPROVED`"

        Design: Corner/errors/acquire_with_another_property_case_is_rejected
        """
        first = cruised_stand(api)
        signed_appraisal(api, first.property_id)
        approved_case(api, first.property_id)
        second_tract, _, second_case = _cruise_a_second_tract(api, first.fund_id)

        api.acquire_property(
            first.property_id,
            {
                "underwriting_case_id": second_case["id"],
                "expected_fund_version": fund_version(api, first.fund_id),
            },
            make_fund_admin_headers(),
        )

        assert_property_dimensions(
            read_property(api, second_tract["id"]), status="APPROVED_FOR_BID"
        )
        assert read_case(api, second_case["id"])["status"] == "APPROVED"


class TestCompletionCannotOutrunThePlan:
    """Realised tonnage is capped by the block's own plan."""

    def test_actual_tons_one_hundredth_above_the_plan_are_refused(self, api):
        """A hundredth of a ton over the plan is refused; the plan itself completes.

        PRD: "`actual_tons` must be no greater than the block's current `planned_tons`, or the close is refused with `ERR_ACTUAL_TONS_EXCEED_PLANNED`, and the property's `certification_posture` must not be `SUSPENDED`, or it is refused with `ERR_CERTIFICATION_SUSPENDED`."

        Design: Corner/errors/actual_tons_above_planned_at_complete_is_rejected
        """
        ctx = cruised_stand(api)
        block = reserve_block(api, ctx.stand_id, planned_tons=1000.00)
        commit_block(api, block["id"])

        response = api.close_harvest_block(
            block["id"],
            {
                "action": "COMPLETE",
                "actual_tons": 1000.01,
                "realized_price_index_factor": 1.05,
            },
            make_forest_manager_headers(),
        )

        validate_error(response, ApiErrorId.ACTUAL_TONS_EXCEED_PLANNED.value, 422)
        refused = read_block(api, block["id"])
        assert refused["status"] == "COMMITTED"
        assert refused["actual_tons"] is None
        assert refused["final_net_revenue_usd"] is None
        assert_fund_cash(read_fund(api, ctx.fund_id), cash_balance_usd=400000.00)

        completed = validate_success(
            api.close_harvest_block(
                block["id"],
                {
                    "action": "COMPLETE",
                    "actual_tons": 1000.00,
                    "realized_price_index_factor": 1.05,
                },
                make_forest_manager_headers(),
            ),
            200,
        )

        assert completed["status"] == "COMPLETED"
        assert_money(
            completed["final_net_revenue_usd"], 22889.55, "final_net_revenue_usd"
        )
        assert_fund_cash(
            read_fund(api, ctx.fund_id),
            cash_balance_usd=422889.55,
            net_operating_cash_usd=22889.55,
        )
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            net_merch_tons=3647.12,
            committed_tons=0.00,
        )


class TestAcquisitionIsBoundedByFundCash:
    """The treasury is checked before the bid is posted."""

    def test_a_bid_above_the_treasury_is_refused_and_moves_nothing(self, api):
        """A 100000.00 bid against 50000.00 of cash is refused on the cash guard.

        PRD: "and the fund's `cash_balance_usd` must be at least the case's `bid_price_usd`, or the closing is refused with `ERR_FUND_CASH_INSUFFICIENT`."

        Design: Corner/errors/acquisition_beyond_fund_cash_is_rejected
        """
        ctx = cruised_stand(api, fund_overrides={"opening_cash_usd": 50000.00})
        signed_appraisal(api, ctx.property_id)
        case = approved_case(api, ctx.property_id)
        assert_money(
            case["underwritten_value_usd"], 191966.99, "underwritten_value_usd"
        )
        before = fund_version(api, ctx.fund_id)

        response = api.acquire_property(
            ctx.property_id,
            {
                "underwriting_case_id": case["id"],
                "expected_fund_version": before,
            },
            make_fund_admin_headers(),
        )

        validate_error(response, ApiErrorId.FUND_CASH_INSUFFICIENT.value, 422)
        fund = read_fund(api, ctx.fund_id)
        assert_fund_cash(fund, cash_balance_usd=50000.00, nav_usd=50000.00)
        assert fund["version"] == before
        assert fund["valuation_basis_stale_count"] == 0
        tract = read_property(api, ctx.property_id)
        assert_property_dimensions(tract, status="APPROVED_FOR_BID")
        assert tract["acquisition_price_usd"] is None
        assert read_case(api, case["id"])["status"] == "APPROVED"


class TestSubmissionIsBoundedByUnderwrittenValue:
    """The committee is never asked to approve a bid above the model."""

    def test_a_bid_above_the_underwritten_value_is_refused_at_submission(self, api):
        """A 250000.00 bid against a 191966.99 model is refused and the case stays in draft.

        PRD: "requires — after the valuation stack has been recomputed against current inventory — that `bid_price_usd` be no greater than `underwritten_value_usd`; a bid above the underwritten value is refused with `ERR_BID_EXCEEDS_UNDERWRITTEN_VALUE`."

        Design: Corner/errors/bid_above_underwritten_value_is_rejected_at_submit
        """
        ctx = cruised_stand(api)
        case = validate_success(
            api.create_underwriting_case(
                underwriting_case_payload(
                    ctx.property_id,
                    property_version(api, ctx.property_id),
                    bid_price_usd=250000.00,
                ),
                make_analyst_headers(),
            ),
            201,
        )
        assert_money(
            case["underwritten_value_usd"], 191966.99, "underwritten_value_usd"
        )

        response = api.submit_underwriting_case(
            case["id"], None, make_analyst_headers()
        )

        validate_error(response, ApiErrorId.BID_EXCEEDS_UNDERWRITTEN_VALUE.value, 422)
        refused = read_case(api, case["id"])
        assert refused["status"] == "DRAFT"
        assert refused["revision_count"] == 0
        assert refused["decided_by_user_id"] is None
        assert_property_dimensions(
            read_property(api, ctx.property_id), status="PROSPECT"
        )


class TestSettlementIsBoundedByTheComputedFigures:
    """The claim ceiling and the salvage ceiling are checked independently."""

    def test_a_claim_one_cent_above_the_indemnity_is_refused(self, api):
        """A cent over the 13500.00 ceiling is refused; the ceiling itself settles.

        PRD: "The settlement may not exceed the event's computed `insurance_claim_usd`, or it is refused with `ERR_CLAIM_EXCEEDS_INDEMNITY`, and the sold volume may not exceed the event's computed `salvageable_tons`, or it is refused with `ERR_SALVAGE_EXCEEDS_RECOVERABLE`."

        Design: Corner/errors/settled_claim_above_computed_indemnity_is_rejected
        """
        ctx, event = _reported_wildfire(api)

        response = api.settle_hazard_event(
            event["id"],
            {"settled_claim_usd": 13500.01, "salvage_sold_tons": 350.00},
            make_fund_admin_headers(),
        )

        validate_error(response, ApiErrorId.CLAIM_EXCEEDS_INDEMNITY.value, 422)
        refused = read_hazard_event(api, event["id"])
        assert refused["status"] == "REPORTED"
        assert refused["settled_claim_usd"] is None
        assert_fund_cash(read_fund(api, ctx.fund_id), cash_balance_usd=400000.00)

        settled = settle_hazard(api, event["id"], 13500.00, 350.00)

        assert settled["status"] == "SETTLED"
        fund = read_fund(api, ctx.fund_id)
        assert_fund_cash(
            fund, cash_balance_usd=413500.00, net_operating_cash_usd=13500.00
        )
        assert_bps(fund["cash_yield_bps"], 270, "cash_yield_bps")
        stand = read_stand(api, ctx.stand_id)
        assert stand["status"] == "INVENTORIED"
        assert_tons(stand["net_merch_tons"], 3647.12, "net_merch_tons")

    def test_salvage_above_the_recoverable_volume_is_refused_on_its_own_ceiling(self, api):
        """A hundredth of a ton over the 350.00 recoverable volume names the salvage error.

        PRD: "On success the event moves from `REPORTED` to the terminal `SETTLED`, the stand moves back from `SALVAGE_PENDING` to `INVENTORIED`, `settled_claim_usd` is credited to both the fund's `cash_balance_usd` and its `net_operating_cash_usd`, and `cash_yield_bps` and `harvest_acceleration_required` are recomputed."

        Design: Corner/errors/salvage_tons_above_recoverable_is_rejected
        """
        ctx, event = _reported_wildfire(api)

        response = api.settle_hazard_event(
            event["id"],
            {"settled_claim_usd": 12000.00, "salvage_sold_tons": 350.01},
            make_fund_admin_headers(),
        )

        validate_error(response, ApiErrorId.SALVAGE_EXCEEDS_RECOVERABLE.value, 422)
        assert read_hazard_event(api, event["id"])["status"] == "REPORTED"
        assert read_stand(api, ctx.stand_id)["status"] == "SALVAGE_PENDING"

        settled = settle_hazard(api, event["id"], 12000.00, 350.00)

        assert settled["status"] == "SETTLED"
        fund = read_fund(api, ctx.fund_id)
        assert_fund_cash(fund, cash_balance_usd=412000.00)
        assert_bps(fund["cash_yield_bps"], 240, "cash_yield_bps")


class TestValidationRequiresSomethingPledged:
    """An empty project cannot be sent to a registry."""

    def test_a_project_with_nothing_pledged_cannot_be_validated(self, api):
        """The empty project is refused, and one dedication later validation succeeds.

        PRD: "Submitting for validation moves the project from `DRAFT` to `VALIDATION` and freezes `dedicated_tons_total`; it requires at least one dedication in `PENDING`, and a project with nothing pledged is refused with `ERR_CARBON_NO_DEDICATIONS`."

        Design: Corner/errors/validation_submission_without_dedications_is_rejected
        """
        ctx = owned_tract(api)
        project = create_carbon_project(api, ctx.property_id)

        response = api.advance_carbon_project(
            project["id"], {"action": "SUBMIT_VALIDATION"}, make_carbon_developer_headers()
        )

        validate_error(response, ApiErrorId.CARBON_NO_DEDICATIONS.value, 422)
        empty = read_carbon_project(api, project["id"])
        assert empty["status"] == "DRAFT"
        assert_tons(empty["dedicated_tons_total"], 0.00, "dedicated_tons_total")
        assert_tons(empty["buffer_pool_tons"], 0.00, "buffer_pool_tons")

        dedication = dedicate(api, project["id"], ctx.stand_id, dedicated_tons=500.00)
        validated = advance_carbon_project(api, project["id"], "SUBMIT_VALIDATION")

        assert validated["status"] == "VALIDATION"
        assert_tons(validated["dedicated_tons_total"], 500.00, "dedicated_tons_total")
        pledged = read_dedication(api, dedication["id"])
        assert pledged["status"] == "PENDING"
        assert pledged["permanence_end_date"] is None
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            dedicated_tons=500.00,
            available_tons=4147.12,
        )


class TestBufferCureMustCoverTheDeficit:
    """A reversal cannot be cured for less than the deficit it created."""

    def test_a_cure_below_the_deficit_is_refused_and_the_exact_deficit_clears_it(self, api):
        """Forty tons will not cover a 45.52-ton deficit; the deficit itself does.

        PRD: "Curing the buffer moves it back: a cure supplies `cure_tons`, which must be at least the project's current `buffer_deficit_tons`, or the cure is refused with `ERR_BUFFER_CURE_INSUFFICIENT`."

        Design: Corner/errors/buffer_cure_below_the_deficit_is_rejected
        """
        ctx = owned_tract(api)
        carbon = registered_carbon_project(api, ctx.property_id, ctx.stand_id)
        report_hazard(
            api,
            ctx.stand_id,
            event_type="INSECT",
            occurred_at="2026-07-25T00:00:00Z",
            damaged_tons=4400.00,
        )
        reversed_dedication = read_dedication(api, carbon.dedication_id)
        assert reversed_dedication["status"] == "REDUCED"
        assert_tons(reversed_dedication["reduced_tons"], 252.88, "reduced_tons")
        pending = read_carbon_project(api, carbon.project_id)
        assert pending["status"] == "REVERSAL_PENDING"
        assert_tons(pending["buffer_deficit_tons"], 45.52, "buffer_deficit_tons")

        response = api.advance_carbon_project(
            carbon.project_id,
            {"action": "CURE_BUFFER", "cure_tons": 40.00},
            make_carbon_developer_headers(),
        )

        validate_error(response, ApiErrorId.BUFFER_CURE_INSUFFICIENT.value, 422)
        still_pending = read_carbon_project(api, carbon.project_id)
        assert still_pending["status"] == "REVERSAL_PENDING"
        assert_tons(still_pending["buffer_pool_tons"], 90.00, "buffer_pool_tons")
        assert_tons(
            still_pending["buffer_deficit_tons"], 45.52, "buffer_deficit_tons"
        )
        assert_fund_cash(read_fund(api, ctx.fund_id), cash_balance_usd=300000.00)

        cured = advance_carbon_project(
            api, carbon.project_id, "CURE_BUFFER", cure_tons=45.52
        )

        assert cured["status"] == "REGISTERED"
        assert_tons(cured["buffer_pool_tons"], 135.52, "buffer_pool_tons")
        assert_tons(cured["buffer_deficit_tons"], 0.00, "buffer_deficit_tons")
        assert_fund_cash(read_fund(api, ctx.fund_id), cash_balance_usd=299362.72)
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            net_merch_tons=247.12,
            available_tons=0.00,
        )
