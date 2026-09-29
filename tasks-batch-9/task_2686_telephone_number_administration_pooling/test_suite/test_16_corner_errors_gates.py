"""Errors: the eligibility, jurisdiction and fiscal gates, and which one of them reports."""
from test_helpers import (
    ADMIN_HEADERS,
    APPROVER_HEADERS,
    CLOCK_PLUS_180,
    ApiErrorId,
    api_client,
    assert_pct,
    create_allocation_request_payload,
    create_eligible_carrier,
    create_submitted_filing,
    file_allocation_request,
    load_block,
    load_held_blocks,
    load_pool_blocks,
    make_carrier_representative_headers,
    pooling_transition,
    put_carrier_on_probation,
    read_block,
    read_carrier,
    read_npa,
    read_rate_center,
    read_request,
    set_clock,
    setup_npa_with_rate_center,
    validate_error,
    validate_paginated,
)

LICENCE_EXPIRY = "2026-09-01T00:00:00Z"
NEW_ENTRANT_CLLI = "CLMBOH04DS0"

# 1300 assigned over two blocks: 65.00 on both variants, clear of the 60.00 floor.
SIXTY_FIVE_SLOW_FORECAST = dict(
    numbers_assigned=1300,
    numbers_intermediate=0,
    numbers_reserved=0,
    numbers_aging=0,
    numbers_administrative=0,
    blocks_held_at_period_end=2,
    forecast_quarters=[600, 600, 600, 600],
)
SIXTY_FIVE_FAST_FORECAST = dict(SIXTY_FIVE_SLOW_FORECAST, forecast_quarters=[3000, 3000, 0, 0])


def _attempt_request(carrier, rate_center, **overrides):
    """File a request as the named carrier and hand back the raw response."""
    payload = create_allocation_request_payload(
        carrier["id"], rate_center["id"],
        read_rate_center(rate_center["id"])["version"], **overrides
    )
    return api_client.create_allocation_request(
        payload, make_carrier_representative_headers(carrier["id"])
    )


def _attempt_approval(request, **payload):
    """Send an approving review and hand back the raw response."""
    return api_client.create_review(
        request["id"], dict({"action": "APPROVE"}, **payload), APPROVER_HEADERS
    )


class TestALapsedLicenceIsCaughtBelowEligibility:
    """The carrier still reads eligible, and the dedicated expiry check stops it anyway."""

    def test_the_expiry_instant_itself_refuses_the_request(self):
        """The clock sits exactly on the expiry instant, so the licence is no longer strictly
        in the future, and the applicant holds no filing at all yet never reaches that gate.

        its `license_expires_on` must be strictly after the logical clock, otherwise `ERR_LICENSE_EXPIRED`

        A carrier whose licence is granted but whose `license_expires_on` has already passed still reads `ELIGIBLE` here, and is caught one step later by the dedicated expiry check that returns `ERR_LICENSE_EXPIRED`.

        a carrier whose licence is granted but expired must surface as `ERR_LICENSE_EXPIRED` rather than being masked by the broader eligibility check

        Design: Corner/errors/expired_licence_blocks_a_new_allocation_request
        """
        set_clock()
        carrier = create_eligible_carrier("A", license_expires_on=LICENCE_EXPIRY)
        _npa, rate_center = setup_npa_with_rate_center()
        set_clock(LICENCE_EXPIRY)

        error = validate_error(
            _attempt_request(
                carrier, rate_center, request_type="GROWTH", requested_block_count=1,
                justification="growth filed one day too late",
            ),
            ApiErrorId.ERR_LICENSE_EXPIRED,
            422,
        )
        assert error["error_id"] != ApiErrorId.ERR_CARRIER_NOT_ELIGIBLE.value
        assert error["error_id"] != ApiErrorId.ERR_UTILIZATION_FILING_REQUIRED.value

        unchanged = read_carrier(carrier["id"])
        assert unchanged["license_status"] == "GRANTED"
        assert unchanged["license_expires_on"] == LICENCE_EXPIRY
        assert unchanged["eligibility_status"] == "ELIGIBLE"

        _rows, meta = validate_paginated(
            api_client.list_allocation_requests(ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0


class TestProbationStopsTheApprovalWithoutDenyingTheRequest:
    """Filing tolerates probation; approval does not, and the refusal is not a denial."""

    def test_the_audit_penalty_refuses_the_approval_and_leaves_the_request_pending(self):
        """A five-point overstatement earns the penalty, the request is filed after the
        penalty lands so it is still queued, and the refused approval changes nothing.

        unlike filing, approval does not tolerate `PROBATION`, and an applicant whose `probation_until` is strictly after the logical clock is refused with `ERR_CARRIER_ON_PROBATION`

        a carrier on probation must surface as `ERR_CARRIER_ON_PROBATION` rather than as either of the two before it

        A difference of 20.00 points or more yields `RECLAMATION_REFERRAL`, a difference of 5.00 points or more yields `PROBATION`, and anything smaller yields `NONE`.

        In both penalty cases `probation_until` is stamped 180 days after the current logical clock, which makes the carrier's computed `eligibility_status` read `PROBATION`

        Design: Corner/errors/carrier_on_probation_cannot_have_a_request_approved
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        load_pool_blocks(npa, rate_center, 5, nxx_code="554")
        filing = put_carrier_on_probation(carrier, rate_center)
        request = file_allocation_request(
            carrier, rate_center, request_type="GROWTH", requested_block_count=1,
            justification="growth while the audit penalty is live",
        )
        assert request["status"] == "PENDING_REVIEW"

        error = validate_error(
            _attempt_approval(request), ApiErrorId.ERR_CARRIER_ON_PROBATION, 422
        )
        assert error["error_id"] != ApiErrorId.ERR_CARRIER_NOT_ELIGIBLE.value

        penalised = read_carrier(carrier["id"])
        assert penalised["eligibility_status"] == "PROBATION"
        assert penalised["probation_until"] == CLOCK_PLUS_180
        assert penalised["reclamation_strike_count"] == 0

        assert filing["status"] == "REJECTED"
        assert_pct(filing["audited_utilization_pct"], 75.00, "audited_utilization_pct")
        assert_pct(filing["claimed_utilization_pct"], 80.00, "claimed_utilization_pct")

        still_queued = read_request(request["id"])
        assert still_queued["status"] == "PENDING_REVIEW"
        assert still_queued["granted_block_count"] == 0
        assert still_queued["reviewer_user_id"] is None


class TestPoolingAloneClosesARateCenterToInitialDemand:
    """The area code is healthy, so the refusal can only come from the transition."""

    def test_a_transitional_rate_center_refuses_the_new_entrants_first_block(self):
        """The rate center holds no blocks at all, so the area code is active and unflagged,
        and the closed door is the pooling transition rather than exhaust posture.

        which it is not while `jeopardy_flag` is set or `pooling_status` is `TRANSITIONAL`; a request against a rate center that is closed to initial demand is refused with `ERR_RATE_CENTER_NOT_ACCEPTING_INITIAL`

        A rate center's `accepts_initial_requests` is false whenever its `jeopardy_flag` is true or its `pooling_status` is `TRANSITIONAL`, and true otherwise.

        Design: Corner/errors/initial_request_into_a_transitional_rate_center_is_refused
        """
        set_clock()
        entrant = create_eligible_carrier(
            "A", switch_clli=NEW_ENTRANT_CLLI, ocn="3456",
            legal_name="Olentangy Wireless LLC", carrier_type="WIRELESS",
            months_in_operation=3,
        )
        npa, rate_center = setup_npa_with_rate_center()
        transitional = pooling_transition(rate_center, "BEGIN_POOLING")
        assert transitional["pooling_status"] == "TRANSITIONAL"

        validate_error(
            _attempt_request(
                entrant, rate_center, request_type="INITIAL", requested_block_count=1,
                justification="first block for a new entrant",
            ),
            ApiErrorId.ERR_RATE_CENTER_NOT_ACCEPTING_INITIAL,
            409,
        )

        closed = read_rate_center(rate_center["id"])
        assert closed["pooling_status"] == "TRANSITIONAL"
        assert closed["accepts_initial_requests"] is False
        assert closed["jeopardy_flag"] is False
        assert closed["pending_request_count"] == 0
        assert read_npa(npa["id"])["status"] == "ACTIVE"


class TestAWellStockedRateCenterIsTooFarFromExhaust:
    """Clearing the utilization floor is not enough when the pool will last two years."""

    def test_a_twenty_five_month_horizon_refuses_the_approval(self):
        """Five blocks against a two-hundred-a-month forecast is twenty-five months of
        inventory, so the gate that fires is the horizon and not the floor.

        The rate center's projected months to exhaust must also be at most 6 months under whichever variant applies to the applicant's effective filing, and a longer horizon is refused with `ERR_EXHAUST_HORIZON_TOO_LONG`

        That months-to-exhaust projection is computed by taking the rate center's `available_block_count`, multiplying by the one thousand numbers in a block to get the available number inventory, and dividing by a monthly demand figure.

        At review time the gate uses whichever variant the applicant's effective filing actually supports: the forward-looking variant when that filing carries `forecast_quarters` values

        the four fiscal gates on an approving review run in the order utilization threshold (30), exhaust horizon (31), safety-valve ceiling (32), empty pool (33), grant ceiling (34), so a request that fails several of them reports the earliest

        Design: Corner/errors/exhaust_horizon_of_twenty_five_months_refuses_the_approval
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        load_pool_blocks(npa, rate_center, 5, nxx_code="555")
        create_submitted_filing(carrier, rate_center, **SIXTY_FIVE_SLOW_FORECAST)
        request = file_allocation_request(
            carrier, rate_center, request_type="GROWTH", requested_block_count=1,
            justification="growth against a well-stocked rate center",
        )
        assert_pct(
            request["months_to_exhaust_at_submission"], 25.00,
            "months_to_exhaust_at_submission",
        )

        error = validate_error(
            _attempt_approval(request), ApiErrorId.ERR_EXHAUST_HORIZON_TOO_LONG, 422
        )
        assert error["error_id"] != ApiErrorId.ERR_UTILIZATION_THRESHOLD_NOT_MET.value

        still_queued = read_request(request["id"])
        assert still_queued["status"] == "PENDING_REVIEW"
        assert_pct(
            still_queued["utilization_pct_at_submission"], 65.00,
            "utilization_pct_at_submission",
        )

        untouched = read_rate_center(rate_center["id"])
        assert untouched["available_block_count"] == 5
        assert untouched["assigned_block_count"] == 0


class TestAnExplicitGrantIsMeasuredAgainstTheEntitlement:
    """The forecast and the pool would carry three blocks; the tier cap would not."""

    def test_naming_three_blocks_against_an_entitlement_of_one_is_refused(self):
        """Sixty-five percent buys a tier cap of one block, and that single ceiling is what
        the reviewer's own figure is measured against.

        The reviewer may grant less than the entitlement by supplying `granted_block_count`, and that figure must not exceed the entitlement, otherwise `ERR_GRANT_EXCEEDS_ENTITLEMENT`.

        The entitlement itself is the smallest of four independent ceilings, none of which predicts the answer on its own.

        Design: Corner/errors/explicit_granted_block_count_above_the_entitlement_is_refused
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        pool = load_pool_blocks(npa, rate_center, 5, nxx_code="555")
        create_submitted_filing(carrier, rate_center, **SIXTY_FIVE_FAST_FORECAST)
        request = file_allocation_request(
            carrier, rate_center, request_type="GROWTH", requested_block_count=3,
            justification="three growth blocks for a 6000-number forecast",
        )
        assert_pct(
            request["months_to_exhaust_at_submission"], 5.00,
            "months_to_exhaust_at_submission",
        )

        validate_error(
            _attempt_approval(request, granted_block_count=3),
            ApiErrorId.ERR_GRANT_EXCEEDS_ENTITLEMENT,
            422,
        )

        still_queued = read_request(request["id"])
        assert still_queued["status"] == "PENDING_REVIEW"
        assert still_queued["requested_block_count"] == 3
        assert still_queued["granted_block_count"] == 0
        assert still_queued["assigned_block_ids"] == []

        assert read_block(pool[0]["id"])["allocation_status"] == "POOL_AVAILABLE"
        assert read_rate_center(rate_center["id"])["available_block_count"] == 5


class TestAStockedButUnusablePoolIsNotAnEmptyPool:
    """Two blocks sit in the pool and neither of them may be handed out."""

    def test_both_contaminated_candidates_report_the_contamination_code(self):
        """One block is inside the contamination ceiling and the other is not, and a rate
        center outside pooling can use neither, so the earlier of the two pool errors fires.

        if the rate center does hold at least one `POOL_AVAILABLE` block whose `routing_status` is `UNROUTED` or `ROUTING_WITHDRAWN` but every such block fails the eligibility test, the refusal is `ERR_BLOCK_NOT_POOLING_ELIGIBLE`

        Contamination (28) precedes the empty-pool check (33) so that a rate center whose pool is stocked but entirely unusable reports `ERR_BLOCK_NOT_POOLING_ELIGIBLE` rather than the misleading `ERR_POOL_INSUFFICIENT_BLOCKS`.

        a rate center that is not `POOLED` can only ever hand out pristine blocks

        A block's `is_pooling_eligible` is true when its `contaminated_count` is at most 100

        Design: Corner/errors/contamination_blocked_pool_refuses_the_approval
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        lightly_dirty = load_block(
            npa, rate_center, nxx_code="556", thousands_digit=0, contaminated_count=40
        )
        heavily_dirty = load_block(
            npa, rate_center, nxx_code="556", thousands_digit=1, contaminated_count=250
        )
        create_submitted_filing(carrier, rate_center, **SIXTY_FIVE_FAST_FORECAST)
        request = file_allocation_request(
            carrier, rate_center, request_type="GROWTH", requested_block_count=1,
            justification="growth against a contaminated pool",
        )

        error = validate_error(
            _attempt_approval(request), ApiErrorId.ERR_BLOCK_NOT_POOLING_ELIGIBLE, 422
        )
        assert error["error_id"] != ApiErrorId.ERR_POOL_INSUFFICIENT_BLOCKS.value

        inside_ceiling = read_block(lightly_dirty["id"])
        assert inside_ceiling["allocation_status"] == "POOL_AVAILABLE"
        assert inside_ceiling["routing_status"] == "UNROUTED"
        assert inside_ceiling["is_pooling_eligible"] is True
        assert read_block(heavily_dirty["id"])["is_pooling_eligible"] is False

        assert read_request(request["id"])["status"] == "PENDING_REVIEW"
        stocked = read_rate_center(rate_center["id"])
        assert stocked["available_block_count"] == 2
        assert stocked["assigned_block_count"] == 0


class TestAGenuinelyEmptyPoolReportsInsufficientBlocks:
    """Every block on the code is already held by the applicant itself."""

    def test_the_approval_is_refused_although_the_horizon_reads_zero(self):
        """With nothing available the projection is zero months, which clears the horizon
        gate and leaves the empty pool as the only thing left to fail.

        if the rate center holds no unrouted `POOL_AVAILABLE` block at all, the refusal is `ERR_POOL_INSUFFICIENT_BLOCKS`. The contamination-blocked case is tested first, so the empty-pool error only ever appears for a genuinely empty pool.

        If the monthly demand figure is zero or negative, the projection is the sentinel 999.00 and no division is attempted; otherwise the quotient is rounded half up to two decimal places.

        Design: Corner/errors/empty_pool_refuses_the_approval_with_insufficient_blocks
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        held = load_held_blocks(
            npa, rate_center, carrier, 2, nxx_code="557", mark_activated=True
        )
        create_submitted_filing(carrier, rate_center, **SIXTY_FIVE_FAST_FORECAST)
        request = file_allocation_request(
            carrier, rate_center, request_type="GROWTH", requested_block_count=1,
            justification="growth with nothing left in the pool",
        )
        assert_pct(
            request["months_to_exhaust_at_submission"], 0.00,
            "months_to_exhaust_at_submission",
        )

        error = validate_error(
            _attempt_approval(request), ApiErrorId.ERR_POOL_INSUFFICIENT_BLOCKS, 409
        )
        assert error["error_id"] != ApiErrorId.ERR_BLOCK_NOT_POOLING_ELIGIBLE.value

        assert read_request(request["id"])["status"] == "PENDING_REVIEW"
        for block in held:
            still_held = read_block(block["id"])
            assert still_held["allocation_status"] == "ASSIGNED"
            assert still_held["holder_carrier_id"] == carrier["id"]

        exhausted = read_rate_center(rate_center["id"])
        assert exhausted["available_block_count"] == 0
        assert exhausted["assigned_block_count"] == 2
