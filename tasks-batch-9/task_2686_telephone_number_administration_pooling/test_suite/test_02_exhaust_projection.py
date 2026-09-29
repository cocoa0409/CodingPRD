"""The two months-to-exhaust variants and where each one is used."""
from test_helpers import (
    APPROVER_HEADERS,
    ApiErrorId,
    TEST_DEFAULTS,
    api_client,
    assert_pct,
    create_eligible_carrier,
    create_submitted_filing,
    file_allocation_request,
    load_block,
    load_pool_blocks,
    read_rate_center,
    read_request,
    set_clock,
    setup_npa_with_rate_center,
    validate_error,
)


def _carrier_with_two_filings():
    """Carrier B holding one activated block, two pool blocks, two filings on file."""
    set_clock()
    carrier = create_eligible_carrier("B")
    npa, rate_center = setup_npa_with_rate_center()
    load_pool_blocks(npa, rate_center, 2, nxx_code="557")
    load_block(
        npa,
        rate_center,
        nxx_code="556",
        thousands_digit=0,
        contaminated_count=0,
        holder_carrier_id=carrier["id"],
        mark_activated=True,
    )
    create_submitted_filing(
        carrier,
        rate_center,
        reporting_period=TEST_DEFAULTS["PRIOR_REPORTING_PERIOD"],
        numbers_assigned=1500,
        numbers_intermediate=0,
        numbers_reserved=0,
        numbers_aging=0,
        numbers_administrative=0,
        blocks_held_at_period_end=3,
        forecast_quarters=[0, 0, 0, 0],
    )
    create_submitted_filing(
        carrier,
        rate_center,
        reporting_period=TEST_DEFAULTS["REPORTING_PERIOD"],
        numbers_assigned=2400,
        numbers_intermediate=0,
        numbers_reserved=0,
        numbers_aging=0,
        numbers_administrative=0,
        blocks_held_at_period_end=3,
        forecast_quarters=[1800, 1200, 900, 600],
    )
    return carrier, npa, rate_center


def _submit_zero_forecast_filing(carrier, rate_center):
    """A newer filing whose forecast is all zeroes, so the forward variant is empty."""
    return create_submitted_filing(
        carrier,
        rate_center,
        reporting_period=TEST_DEFAULTS["NEXT_REPORTING_PERIOD"],
        numbers_assigned=3300,
        numbers_intermediate=0,
        numbers_reserved=0,
        numbers_aging=0,
        numbers_administrative=0,
        blocks_held_at_period_end=3,
        forecast_quarters=[0, 0, 0, 0],
    )


class TestForwardLookingSnapshot:
    """A growth filing snapshots the forecast-driven projection."""

    def test_growth_request_snapshots_the_forward_looking_projection(self):
        """Two pool blocks against a 1800 plus 1200 forecast project 4.00 months.

        A forecast of 1800 for the nearest quarter and 1200 for the one after
        totals 3000, which over six months is a monthly demand of 500 and a
        projection of 4.00 months.

        Design: Difficulty/dual_variant_calc/rate_center_exhaust_forward_vs_chronological_divergence
        """
        carrier, _npa, rate_center = _carrier_with_two_filings()

        assert read_rate_center(rate_center["id"])["available_block_count"] == 2

        request = file_allocation_request(
            carrier,
            rate_center,
            request_type="GROWTH",
            requested_block_count=1,
            justification="forward-looking demand",
        )

        assert_pct(
            request["months_to_exhaust_at_submission"],
            4.00,
            "months_to_exhaust_at_submission",
        )
        assert_pct(
            request["utilization_pct_at_submission"], 80.00, "utilization_pct_at_submission"
        )
        assert read_rate_center(rate_center["id"])["available_block_count"] == 2

    def test_a_zero_forecast_filing_snapshots_the_sentinel_and_supersedes_the_first_request(self):
        """The snapshot variant never consults history, so an all-zero forecast leaves
        no measurable demand and the newer request displaces the older one.

        At filing time the snapshot uses the forward-looking variant for `INITIAL`,
        `GROWTH` and `POOL_REPLENISH` requests and the chronological variant for a
        `SAFETY_VALVE` request.

        Design: Difficulty/dual_variant_calc/rate_center_exhaust_forward_vs_chronological_divergence
        """
        carrier, _npa, rate_center = _carrier_with_two_filings()
        first = file_allocation_request(
            carrier,
            rate_center,
            request_type="GROWTH",
            requested_block_count=1,
            justification="forward-looking demand",
        )

        _submit_zero_forecast_filing(carrier, rate_center)
        second = file_allocation_request(
            carrier,
            rate_center,
            request_type="GROWTH",
            requested_block_count=1,
            justification="history-based demand",
        )

        assert_pct(
            second["months_to_exhaust_at_submission"],
            999.00,
            "months_to_exhaust_at_submission",
        )

        displaced = read_request(first["id"])
        assert displaced["status"] == "SUPERSEDED"
        assert displaced["superseded_by_request_id"] == second["id"]
        assert displaced["decided_at"] is not None
        assert read_rate_center(rate_center["id"])["available_block_count"] == 2


class TestChronologicalGateAtReview:
    """The review gate follows the filing the applicant actually has."""

    def test_chronological_variant_at_review_refuses_the_thirteen_month_horizon(self):
        """History of 3300 against 2400 is 900 over six months, or 150 a month, so
        2000 available numbers project 13.33 months and fail the six-month gate.

        The rate center's projected months to exhaust must also be at most 6 months
        under whichever variant applies to the applicant's effective filing, and a
        longer horizon is refused with `ERR_EXHAUST_HORIZON_TOO_LONG`.

        Design: Difficulty/dual_variant_calc/rate_center_exhaust_forward_vs_chronological_divergence
        """
        carrier, _npa, rate_center = _carrier_with_two_filings()
        _submit_zero_forecast_filing(carrier, rate_center)
        request = file_allocation_request(
            carrier,
            rate_center,
            request_type="GROWTH",
            requested_block_count=1,
            justification="history-based demand",
        )

        validate_error(
            api_client.create_review(request["id"], {"action": "APPROVE"}, APPROVER_HEADERS),
            ApiErrorId.ERR_EXHAUST_HORIZON_TOO_LONG,
            422,
        )
        assert read_request(request["id"])["status"] == "PENDING_REVIEW"
        assert read_rate_center(rate_center["id"])["available_block_count"] == 2

    def test_forward_variant_at_review_clears_the_same_six_month_gate(self):
        """With a forecast on the effective filing the gate reads 4.00 months, and the
        very same inventory qualifies.

        the chronological variant when `forecast_quarters` is absent or every one of
        its four entries is zero

        Design: Difficulty/dual_variant_calc/rate_center_exhaust_forward_vs_chronological_divergence
        """
        carrier, _npa, rate_center = _carrier_with_two_filings()
        request = file_allocation_request(
            carrier,
            rate_center,
            request_type="GROWTH",
            requested_block_count=1,
            justification="forward-looking demand",
        )

        approved = api_client.create_review(
            request["id"], {"action": "APPROVE"}, APPROVER_HEADERS
        )
        assert approved.status_code == 200, approved.text
        decided = read_request(request["id"])
        assert decided["status"] == "APPROVED"
        assert decided["granted_block_count"] == 1
