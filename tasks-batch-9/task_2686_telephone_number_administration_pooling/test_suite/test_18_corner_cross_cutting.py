"""Cross-cutting layers: the two concurrency guards, a refused cascade, and a lapsed window."""
from test_helpers import (
    ADMIN_HEADERS,
    APPROVER_HEADERS,
    APPROVER_USER_ID,
    CLOCK_PLUS_180,
    DEFAULT_CLOCK,
    ApiErrorId,
    api_client,
    assert_pct,
    create_allocation_request_payload,
    create_eligible_carrier,
    create_routing_record_payload,
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
    validate_success,
)

FIRST_LRN = "6145540000"
SECOND_LRN = "6145540001"

# 1300 assigned over two blocks is 65.00, and 6000 forecast over two quarters is
# a monthly demand of 1000, which keeps the exhaust horizon short.
SIXTY_FIVE_FAST_FORECAST = dict(
    numbers_assigned=1300,
    numbers_intermediate=0,
    numbers_reserved=0,
    numbers_aging=0,
    numbers_administrative=0,
    blocks_held_at_period_end=2,
    forecast_quarters=[3000, 3000, 0, 0],
)


def _attempt_request(carrier, rate_center_id, version, justification):
    """File a growth request against a pinned version and hand back the raw response."""
    payload = create_allocation_request_payload(
        carrier["id"], rate_center_id, version, request_type="GROWTH",
        requested_block_count=1, justification=justification,
    )
    return api_client.create_allocation_request(
        payload, make_carrier_representative_headers(carrier["id"])
    )


class TestAnUnrelatedTransitionStalesTheCapturedVersion:
    """The version moved through a pooling transition, not through a competing request."""

    def test_the_stale_version_is_reported_ahead_of_the_missing_filing(self):
        """The applicant has filed no utilization report for this rate center at all, so the
        growth prerequisite is genuinely unmet, and the concurrency guard still answers first.

        Filing an allocation request must carry `expected_rate_center_version`, holding the `version` of the target rate center as the client last read it.

        If the supplied value does not equal the rate center's current `version`, the request is rejected with `ERR_STALE_RATE_CENTER_VERSION` (HTTP 412) and the client must re-read the rate center before filing again.

        `BEGIN_POOLING` moves it to `TRANSITIONAL` and increments its `version` by 1

        the supplied `expected_rate_center_version` or `expected_block_version` equals the parent's current `version`, else `ERR_STALE_RATE_CENTER_VERSION` or `ERR_STALE_BLOCK_VERSION`

        Design: Corner/cross-cutting complexity layers/stale_rate_center_version_on_allocation_request_returns_412
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        _npa, rate_center = setup_npa_with_rate_center()
        captured = read_rate_center(rate_center["id"])["version"]

        transitional = pooling_transition(rate_center, "BEGIN_POOLING")
        assert transitional["pooling_status"] == "TRANSITIONAL"
        assert transitional["version"] == captured + 1

        error = validate_error(
            _attempt_request(
                carrier, rate_center["id"], captured,
                "growth on a rate center that moved under us",
            ),
            ApiErrorId.ERR_STALE_RATE_CENTER_VERSION,
            412,
        )
        assert error["error_id"] != ApiErrorId.ERR_UTILIZATION_FILING_REQUIRED.value

        assert read_rate_center(rate_center["id"])["pending_request_count"] == 0
        _rows, meta = validate_paginated(
            api_client.list_allocation_requests(ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0


class TestTheAcceptedRequestInvalidatesItsOwnVersion:
    """One version number is good for exactly one write, and this proves both halves."""

    def test_the_first_filing_is_accepted_and_the_replay_of_the_same_version_is_not(self):
        """Nothing else touches the rate center between the two calls, so the only thing that
        moved the version is the request that was just accepted.

        Every accepted filing advances the rate center's `version` (its pending-request counter changes)

        so a writer holding an older version number is working from a stale view of the rate center's pool and pending demand

        A newly filed request opens at `status` `PENDING_REVIEW` with `info_request_count` at 0, `granted_block_count` at 0, an empty `assigned_block_ids` array, and `reviewer_user_id`, `approver_user_id`, `decided_at`, `denial_reason` and `superseded_by_request_id` all null.

        Effective utilization is defined once and used everywhere in this document: it is the effective filing's `audited_utilization_pct` when that field is non-null, otherwise that filing's `claimed_utilization_pct`

        Design: Corner/cross-cutting complexity layers/fresh_rate_center_version_is_accepted_then_immediately_goes_stale
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        load_pool_blocks(npa, rate_center, 2, nxx_code="554")
        create_submitted_filing(carrier, rate_center, **SIXTY_FIVE_FAST_FORECAST)
        captured = read_rate_center(rate_center["id"])["version"]

        filed = validate_success(
            _attempt_request(
                carrier, rate_center["id"], captured,
                "first growth request with a fresh version",
            ),
            201,
        )
        assert filed["status"] == "PENDING_REVIEW"
        assert filed["info_request_count"] == 0
        assert_pct(
            filed["utilization_pct_at_submission"], 65.00,
            "utilization_pct_at_submission",
        )

        validate_error(
            _attempt_request(
                carrier, rate_center["id"], captured,
                "replay of the now-stale version",
            ),
            ApiErrorId.ERR_STALE_RATE_CENTER_VERSION,
            412,
        )

        assert read_rate_center(rate_center["id"])["pending_request_count"] == 1
        live = read_request(filed["id"])
        assert live["status"] == "PENDING_REVIEW"
        assert live["superseded_by_request_id"] is None


class TestTheSecondConcurrencyGuardLivesOnTheBlock:
    """A different parent, a different version field and a different refusal code."""

    def test_the_republish_of_a_consumed_block_version_is_refused(self):
        """The publish that succeeded is what moved the block's version, so the naive repeat of
        the same body carries a number the platform has already spent.

        Publishing routing data for a number block must carry `expected_block_version`, holding the `version` of the target block as the client last read it.

        If the supplied value does not equal the block's current `version`, the publish is rejected with `ERR_STALE_BLOCK_VERSION` (HTTP 412).

        From `UNROUTED`, an `effective_at` at or before the logical clock moves it to `LERG_PUBLISHED` with `current_lrn` set from the record

        `npac_db_version` on the record captures the block's `npac_db_version` immediately after the record was written, so the ledger carries its own portability-database watermark.

        `record_status` reads `PUBLISHED` for that open row, `SUPERSEDED` once a later record starts

        Design: Corner/cross-cutting complexity layers/stale_block_version_on_routing_record_publish_returns_412
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        block = load_block(
            npa, rate_center, nxx_code="554", thousands_digit=0,
            holder_carrier_id=carrier["id"], mark_activated=True,
        )
        assert block["routing_status"] == "UNROUTED"
        captured = read_block(block["id"])["version"]

        published = validate_success(
            api_client.create_routing_record(
                block["id"],
                create_routing_record_payload(
                    captured, lrn=FIRST_LRN, effective_at=DEFAULT_CLOCK
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert published["record_status"] == "PUBLISHED"
        assert published["npac_db_version"] == 1
        assert published["end_at"] is None

        routed = read_block(block["id"])
        assert routed["routing_status"] == "LERG_PUBLISHED"
        assert routed["current_lrn"] == FIRST_LRN
        assert routed["npac_db_version"] == 1

        error = validate_error(
            api_client.create_routing_record(
                block["id"],
                create_routing_record_payload(
                    captured, lrn=SECOND_LRN, effective_at=DEFAULT_CLOCK
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_STALE_BLOCK_VERSION,
            412,
        )
        assert error["error_id"] != ApiErrorId.ERR_ROUTING_INTERVAL_OVERLAP.value

        rows, meta = validate_paginated(
            api_client.list_block_routing_records(block["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 1
        assert rows[0]["lrn"] == FIRST_LRN
        assert read_block(block["id"])["npac_db_version"] == 1


class TestARefusedCompletionDonatesNothingAtAll:
    """The widest cascade in the domain is refused before any of it is applied."""

    def test_the_open_queue_refuses_completion_and_both_blocks_stay_held(self):
        """One request is sitting in the queue, so the completion's cross-entity precondition
        fails while the transition itself is perfectly legal from `TRANSITIONAL`.

        Completion requires that no allocation request for the rate center is sitting in `PENDING_REVIEW` or `INFO_REQUESTED`, which is exactly the condition that `pending_request_count` is zero; an administrator who tries to complete pooling over an open queue is refused with `ERR_INVALID_STATE_TRANSITION`.

        the requested transition exists from the current state and every cross-entity precondition of that transition holds, else `ERR_INVALID_STATE_TRANSITION`

        Each donated block moves from `RESERVED` or `ASSIGNED` to `POOL_AVAILABLE` with `holder_carrier_id`, `assigned_at`, `activation_due_at` and `activated_at` all cleared to null.

        `last_donation_block_count` accumulates the blocks actually donated and `donation_shortfall_count` accumulates the difference between what each carrier owed and what it could deliver

        A new rate center opens at `pooling_status` `NON_POOLED` with `pooling_effective_at` null, `available_block_count` and `assigned_block_count` at 0, `pending_request_count` at 0, `last_donation_block_count` and `donation_shortfall_count` at 0

        Design: Corner/cross-cutting complexity layers/pooling_completion_refused_leaves_no_partial_donation
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        held = load_held_blocks(
            npa, rate_center, carrier, 2, nxx_code="554", mark_activated=True
        )
        create_submitted_filing(carrier, rate_center, **SIXTY_FIVE_FAST_FORECAST)
        pooling_transition(rate_center, "BEGIN_POOLING")
        request = file_allocation_request(
            carrier, rate_center, request_type="GROWTH", requested_block_count=1,
            justification="growth filed while the rate center transitions",
        )
        assert request["status"] == "PENDING_REVIEW"
        posture_before = read_npa(npa["id"])["status"]

        validate_error(
            api_client.create_pooling_transition(
                rate_center["id"],
                {"action": "COMPLETE_POOLING", "pooling_effective_at": DEFAULT_CLOCK},
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

        refused = read_rate_center(rate_center["id"])
        assert refused["pooling_status"] == "TRANSITIONAL"
        assert refused["pooling_effective_at"] is None
        assert refused["available_block_count"] == 0
        assert refused["assigned_block_count"] == 2
        assert refused["pending_request_count"] == 1
        assert refused["last_donation_block_count"] == 0
        assert refused["donation_shortfall_count"] == 0

        for block in held:
            still_held = read_block(block["id"])
            assert still_held["allocation_status"] == "ASSIGNED"
            assert still_held["holder_carrier_id"] == carrier["id"]
            assert still_held["activated_at"] is not None

        assert read_carrier(carrier["id"])["blocks_held_count"] == 2
        untouched = read_npa(npa["id"])
        assert untouched["available_block_count"] == 0
        assert untouched["status"] == posture_before


class TestThePenaltyWindowIsOutrunRatherThanCleared:
    """The stored timestamp never changes; only the clock catching up changes the answer."""

    def test_the_approval_that_probation_refused_succeeds_at_the_inclusive_instant(self):
        """The clock sits exactly on `probation_until`, which is not strictly after it, so the
        carrier reads eligible again on a stored field nobody has touched.

        It is `ELIGIBLE` when `license_status` is `GRANTED` and `facilities_readiness_status` is `VERIFIED` and `reclamation_strike_count` is below 2 and `probation_until` is either null or at or before the logical clock.

        an applicant whose `probation_until` is strictly after the logical clock is refused with `ERR_CARRIER_ON_PROBATION`

        Step one closes the request: `status` becomes `APPROVED`, `granted_block_count` and `assigned_block_ids` are stamped, `approver_user_id` records the acting `RegulatoryApprover`, `decided_at` is stamped at the logical clock, and the rate center's `pending_request_count` is decremented by 1.

        Step two moves each drawn block from `POOL_AVAILABLE` to `RESERVED`, setting its `holder_carrier_id` to the request's `carrier_id`

        The first is the carrier's own ask, `requested_block_count`.

        A code with at most four available blocks becomes `JEOPARDY` — the comparison is inclusive, so exactly four available blocks is `JEOPARDY` while five is not.

        Design: Corner/cross-cutting complexity layers/probation_window_lapse_lets_the_same_approval_through
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        load_pool_blocks(npa, rate_center, 5, nxx_code="554")
        filing = put_carrier_on_probation(
            carrier, rate_center, numbers_assigned=1600,
            adjusted_numbers_assigned=1500, blocks_held_at_period_end=2,
            forecast_quarters=[3000, 3000, 0, 0],
        )
        assert_pct(filing["audited_utilization_pct"], 75.00, "audited_utilization_pct")
        request = file_allocation_request(
            carrier, rate_center, request_type="GROWTH", requested_block_count=1,
            justification="growth once the penalty window has run",
        )
        assert request["status"] == "PENDING_REVIEW"

        penalised = read_carrier(carrier["id"])
        assert penalised["eligibility_status"] == "PROBATION"
        assert penalised["probation_until"] == CLOCK_PLUS_180

        set_clock(CLOCK_PLUS_180)
        approved = validate_success(
            api_client.create_review(
                request["id"], {"action": "APPROVE"}, APPROVER_HEADERS
            ),
            200,
        )

        assert approved["status"] == "APPROVED"
        assert approved["granted_block_count"] == 1
        assert approved["approver_user_id"] == APPROVER_USER_ID
        assert approved["reviewer_user_id"] is None
        assert approved["decided_at"] == CLOCK_PLUS_180

        recovered = read_carrier(carrier["id"])
        assert recovered["eligibility_status"] == "ELIGIBLE"
        assert recovered["probation_until"] == CLOCK_PLUS_180
        assert recovered["reclamation_strike_count"] == 0

        rows, meta = validate_paginated(
            api_client.list_blocks(
                ADMIN_HEADERS,
                params={"rate_center_id": rate_center["id"],
                        "allocation_status": "RESERVED"},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["holder_carrier_id"] == carrier["id"]

        settled = read_rate_center(rate_center["id"])
        assert settled["available_block_count"] == 4
        assert settled["assigned_block_count"] == 1
        assert settled["pending_request_count"] == 0
        assert read_npa(npa["id"])["status"] == "JEOPARDY"
