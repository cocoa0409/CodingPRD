"""The independent appraisal dimension and the acquisition closing gate."""

from test_helpers import (
    ApiErrorId,
    assert_bps,
    assert_fund_cash,
    assert_money,
    assert_property_dimensions,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    acquire,
    approved_case,
    create_case,
    cruised_stand,
    decide_case,
    fund_version,
    invalidate_appraisal,
    read_case,
    read_fund,
    read_property,
    signed_appraisal,
    submit_case,
)
from test_helpers.test_users import make_fund_admin_headers


class TestPropertyDimensionsAdvanceIndependently:
    """Driving the appraisal dimension leaves the other three coordinates where they were."""

    def test_invalidating_a_signed_appraisal_leaves_the_acquisition_dimension_pinned(self, api):
        """A third appraiser stales the valuation while the tract stays approved for bid.

        PRD: "Invalidating a `SIGNED` appraisal instead moves `appraisal_status` to `STALE`, which does not erase `appraised_value_usd` but subjects the property's contribution to fund net asset value to a twelve percent haircut, and recomputes `valuation_basis_stale_count`."

        Design: Difficulty/non_linear_state_machine/property_acquisition_and_appraisal_dimensions_advance_independently
        """
        ctx = cruised_stand(api)
        signed_appraisal(api, ctx.property_id)
        case = approved_case(api, ctx.property_id)
        assert_property_dimensions(
            read_property(api, ctx.property_id),
            status="APPROVED_FOR_BID",
            appraisal_status="SIGNED",
        )

        invalidate_appraisal(api, ctx.property_id, actor="appraiser-3")

        tract = read_property(api, ctx.property_id)
        assert_property_dimensions(
            tract, status="APPROVED_FOR_BID", appraisal_status="STALE"
        )
        assert_money(tract["appraised_value_usd"], 3900000.00, "appraised_value_usd")
        assert read_case(api, case["id"])["status"] == "APPROVED"

    def test_the_certification_and_planning_dimensions_are_not_reset_by_the_appraisal(self, api):
        """The posture and the plan flag advance on disjoint triggers of their own.

        PRD: "Neither `status` nor `appraisal_status` gates the other's transitions; they advance on disjoint triggers."

        Design: Difficulty/non_linear_state_machine/property_acquisition_and_appraisal_dimensions_advance_independently
        """
        ctx = cruised_stand(api)
        signed_appraisal(api, ctx.property_id)
        approved_case(api, ctx.property_id)

        invalidate_appraisal(api, ctx.property_id, actor="appraiser-3")

        assert_property_dimensions(
            read_property(api, ctx.property_id),
            status="APPROVED_FOR_BID",
            appraisal_status="STALE",
            certification_posture="CERTIFIED",
            harvest_plan_status="ALIGNED",
        )

    def test_a_tract_not_yet_owned_carries_no_value_and_no_stale_basis(self, api):
        """A tract approved for bid contributes nothing to net asset value or the stale counter.

        PRD: "Only properties whose `status` is `OWNED` or `HBU_MARKETED` carry value; those in `PROSPECT`, `UNDER_UNDERWRITING`, `APPROVED_FOR_BID` and `PASSED` contribute 0.00."

        Design: Difficulty/non_linear_state_machine/property_acquisition_and_appraisal_dimensions_advance_independently
        """
        ctx = cruised_stand(api)
        signed_appraisal(api, ctx.property_id)
        approved_case(api, ctx.property_id)

        invalidate_appraisal(api, ctx.property_id, actor="appraiser-3")

        fund = read_fund(api, ctx.fund_id)
        assert fund["valuation_basis_stale_count"] == 0
        assert_fund_cash(fund, cash_balance_usd=400000.00, nav_usd=400000.00)


class TestAcquisitionGatedByCaseStatus:
    """The closing reads the cited case's status before it touches the fund."""

    def test_a_draft_case_cannot_close_the_acquisition(self, api):
        """A case left in DRAFT is refused, and the fund is not debited.

        PRD: "The cited case must be `APPROVED`, or the closing is refused with `ERR_UNDERWRITING_NOT_APPROVED`"

        Design: Difficulty/cross_entity_state_dependency/property_acquisition_gated_by_underwriting_case_status
        """
        ctx = cruised_stand(api)
        signed_appraisal(api, ctx.property_id)
        case = create_case(api, ctx.property_id)
        assert case["status"] == "DRAFT"
        version_before = fund_version(api, ctx.fund_id)

        response = api.acquire_property(
            ctx.property_id,
            {
                "underwriting_case_id": case["id"],
                "expected_fund_version": version_before,
            },
            make_fund_admin_headers(),
        )
        validate_error(response, ApiErrorId.UNDERWRITING_NOT_APPROVED.value, 409)

        fund = read_fund(api, ctx.fund_id)
        assert_fund_cash(fund, cash_balance_usd=400000.00)
        assert fund["version"] == version_before
        assert_property_dimensions(
            read_property(api, ctx.property_id),
            status="PROSPECT",
            appraisal_status="SIGNED",
        )

    def test_the_captured_fund_version_still_closes_once_the_committee_approves(self, api):
        """The refused attempt left the fund untouched, so the same token remains current.

        PRD: "On success the property moves from `APPROVED_FOR_BID` to `OWNED`, its `acquisition_price_usd` is set to the case's `bid_price_usd`, the same amount is debited from the fund's `cash_balance_usd`, the fund's `nav_usd` is recomputed, and the fund's `version` is incremented."

        Design: Difficulty/cross_entity_state_dependency/property_acquisition_gated_by_underwriting_case_status
        """
        ctx = cruised_stand(api)
        signed_appraisal(api, ctx.property_id)
        case = create_case(api, ctx.property_id)
        version_before = fund_version(api, ctx.fund_id)

        api.acquire_property(
            ctx.property_id,
            {
                "underwriting_case_id": case["id"],
                "expected_fund_version": version_before,
            },
            make_fund_admin_headers(),
        )

        submit_case(api, case["id"])
        decided = decide_case(api, case["id"], "APPROVE", decision_note="Bid cleared by committee.")
        assert decided["status"] == "APPROVED"
        assert_property_dimensions(
            read_property(api, ctx.property_id), status="APPROVED_FOR_BID"
        )

        response = api.acquire_property(
            ctx.property_id,
            {
                "underwriting_case_id": case["id"],
                "expected_fund_version": version_before,
            },
            make_fund_admin_headers(),
        )
        tract = validate_success(response, 200)

        assert tract["status"] == "OWNED"
        assert_money(tract["acquisition_price_usd"], 100000.00, "acquisition_price_usd")

    def test_the_closing_debits_the_bid_without_touching_operating_cash(self, api):
        """The bid is a capital call, so the yield figures stay at zero after the closing.

        PRD: "the bid is a capital call, not operating cash, and including it would understate the fund's yield against its mandate for the life of the fund"

        Design: Difficulty/cross_entity_state_dependency/property_acquisition_gated_by_underwriting_case_status
        """
        ctx = cruised_stand(api)
        signed_appraisal(api, ctx.property_id)
        case = approved_case(api, ctx.property_id)

        acquire(api, ctx.property_id, case["id"], ctx.fund_id)

        fund = read_fund(api, ctx.fund_id)
        assert_fund_cash(
            fund,
            cash_balance_usd=300000.00,
            net_operating_cash_usd=0.00,
            nav_usd=4200000.00,
        )
        assert_bps(fund["cash_yield_bps"], 0, "cash_yield_bps")
        assert_money(
            read_property(api, ctx.property_id)["appraised_value_usd"],
            3900000.00,
            "appraised_value_usd",
        )
