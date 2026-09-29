"""Review-cycle behaviour: the information ceiling and the gates re-run at review."""
from test_helpers import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    APPROVER_HEADERS,
    ApiErrorId,
    api_client,
    approve_request,
    assert_pct,
    attest_readiness,
    create_eligible_carrier,
    create_submitted_filing,
    fail_readiness,
    file_allocation_request,
    license_action,
    load_pool_blocks,
    read_carrier,
    read_request,
    request_info,
    resubmit_request,
    set_clock,
    setup_npa_with_rate_center,
    validate_error,
    verify_readiness,
)


def _request_under_review(requested_block_count=2):
    """Carrier A at 68.89 with a PENDING_REVIEW growth request over a one-block pool."""
    set_clock()
    carrier = create_eligible_carrier("A")
    npa, rate_center = setup_npa_with_rate_center()
    pool_blocks = load_pool_blocks(npa, rate_center, 1, nxx_code="556")
    create_submitted_filing(
        carrier, rate_center,
        numbers_assigned=2500, numbers_intermediate=400, numbers_reserved=200,
        numbers_aging=200, numbers_administrative=300,
        blocks_held_at_period_end=5, forecast_quarters=[1800, 1200, 900, 600],
    )
    request = file_allocation_request(
        carrier, rate_center, request_type="GROWTH",
        requested_block_count=requested_block_count,
        justification="two blocks for Q3 growth",
    )
    return carrier, rate_center, pool_blocks, request


class TestInformationCycleCeiling:
    """Two rounds of questions are allowed; the third is turned away."""

    def test_two_cycles_are_accepted_and_the_third_request_for_information_is_refused(self):
        """The counter climbs to two across two full round trips and then stops.

        It is accepted only from `PENDING_REVIEW`, it requires `info_note` to be present, and
        it requires `info_request_count` to be strictly below the two-cycle ceiling; a third
        information request is refused with `ERR_INFO_CYCLE_LIMIT_REACHED`.

        Design: Difficulty/non_linear_state_machine/allocation_request_info_request_cycle_twice_then_third_refused
        """
        carrier, _rate_center, _pool_blocks, request = _request_under_review()

        first = request_info(request, info_note="cycle one: itemise the reserved numbers")
        assert first["status"] == "INFO_REQUESTED"
        assert first["info_request_count"] == 1

        resubmit_request(
            request, carrier, revised_requested_block_count=2,
            response_note="reserved numbers itemised",
        )
        assert read_request(request["id"])["status"] == "PENDING_REVIEW"

        second = request_info(request, info_note="cycle two: confirm the intermediate numbers")
        assert second["status"] == "INFO_REQUESTED"
        assert second["info_request_count"] == 2

        resubmit_request(
            request, carrier, revised_requested_block_count=2,
            response_note="intermediate numbers confirmed",
        )

        validate_error(
            api_client.create_review(
                request["id"],
                {"action": "REQUEST_INFO", "info_note": "cycle three: one more question"},
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_INFO_CYCLE_LIMIT_REACHED,
            409,
        )

    def test_the_refusal_leaves_the_counter_and_the_reviewer_untouched_and_approval_follows(self):
        """A refused third cycle is inert: the request stays in the queue at two cycles
        with the same recorded reviewer, and the approval that follows still works.

        The transition moves `status` to `INFO_REQUESTED`, increments `info_request_count`
        by 1, records the acting `X-User-ID` in `reviewer_user_id` if that field is still
        null, and increments the request's `version` by 1.

        Design: Difficulty/non_linear_state_machine/allocation_request_info_request_cycle_twice_then_third_refused
        """
        carrier, _rate_center, pool_blocks, request = _request_under_review()

        request_info(request, info_note="cycle one: itemise the reserved numbers")
        resubmit_request(
            request, carrier, revised_requested_block_count=2,
            response_note="reserved numbers itemised",
        )
        request_info(request, info_note="cycle two: confirm the intermediate numbers")
        resubmit_request(
            request, carrier, revised_requested_block_count=2,
            response_note="intermediate numbers confirmed",
        )
        api_client.create_review(
            request["id"],
            {"action": "REQUEST_INFO", "info_note": "cycle three: one more question"},
            ADMIN_HEADERS,
        )

        after_refusal = read_request(request["id"])
        assert after_refusal["info_request_count"] == 2
        assert after_refusal["status"] == "PENDING_REVIEW"
        assert after_refusal["reviewer_user_id"] == ADMIN_USER_ID

        approve_request(request)

        decided = read_request(request["id"])
        assert decided["status"] == "APPROVED"
        assert decided["granted_block_count"] == 1
        assert decided["assigned_block_ids"] == [pool_blocks[0]["id"]]
        assert decided["info_request_count"] == 2


def _suspended_applicant_below_the_threshold():
    """Carrier A filed while eligible at 40.00, then had its licence suspended."""
    set_clock()
    carrier = create_eligible_carrier("A")
    npa, rate_center = setup_npa_with_rate_center()
    pool_blocks = load_pool_blocks(npa, rate_center, 1, nxx_code="556")
    filing = create_submitted_filing(
        carrier, rate_center,
        numbers_assigned=2000, numbers_intermediate=0, numbers_reserved=0,
        numbers_aging=0, numbers_administrative=0,
        blocks_held_at_period_end=5, forecast_quarters=[1200, 800, 600, 400],
    )
    request = file_allocation_request(
        carrier, rate_center, request_type="GROWTH", requested_block_count=1,
        justification="one growth block",
    )
    license_action(carrier, "SUSPEND")
    return carrier, filing, pool_blocks, request


class TestEligibilityOutranksTheUtilizationThreshold:
    """A suspended applicant hears about its licence, not about its arithmetic."""

    def test_a_suspended_applicant_is_refused_on_eligibility_not_on_utilization(self):
        """Both grounds are present at once and only the earlier one is reported.

        A `SUSPEND` action from `GRANTED` sets `license_status` to `SUSPENDED`, which
        recomputes `eligibility_status` to `SUSPENDED`

        An action that requires eligibility rejects a carrier reading `INELIGIBLE` or
        `SUSPENDED` with `ERR_CARRIER_NOT_ELIGIBLE`

        Design: Difficulty/priority_pair_validation_conflict/carrier_eligibility_beats_utilization_threshold_on_approval
        """
        carrier, filing, _pool_blocks, request = _suspended_applicant_below_the_threshold()

        assert_pct(filing["claimed_utilization_pct"], 40.00, "claimed_utilization_pct")
        assert read_carrier(carrier["id"])["eligibility_status"] == "SUSPENDED"

        error = validate_error(
            api_client.create_review(request["id"], {"action": "APPROVE"}, APPROVER_HEADERS),
            ApiErrorId.ERR_CARRIER_NOT_ELIGIBLE,
            422,
        )
        assert error["error_id"] != ApiErrorId.ERR_UTILIZATION_THRESHOLD_NOT_MET.value

        undecided = read_request(request["id"])
        assert undecided["status"] == "PENDING_REVIEW"
        assert undecided["approver_user_id"] is None
        assert undecided["granted_block_count"] == 0

    def test_reinstating_the_licence_reveals_the_utilization_refusal_underneath(self):
        """With the licence back the same approval is refused on the arithmetic instead,
        which proves the first refusal was masking a second live ground.

        A `REINSTATE` action returns a carrier from `SUSPENDED` to `GRANTED`, but only when
        its stored `license_expires_on` is still strictly after the logical clock

        A tier cap of zero — an effective utilization below 60.00 on a `GROWTH` or
        `POOL_REPLENISH` request — is refused with `ERR_UTILIZATION_THRESHOLD_NOT_MET`

        Design: Difficulty/priority_pair_validation_conflict/carrier_eligibility_beats_utilization_threshold_on_approval
        """
        carrier, _filing, pool_blocks, request = _suspended_applicant_below_the_threshold()
        validate_error(
            api_client.create_review(request["id"], {"action": "APPROVE"}, APPROVER_HEADERS),
            ApiErrorId.ERR_CARRIER_NOT_ELIGIBLE,
            422,
        )

        license_action(carrier, "REINSTATE")
        restored = read_carrier(carrier["id"])
        assert restored["license_status"] == "GRANTED"
        assert restored["eligibility_status"] == "ELIGIBLE"

        validate_error(
            api_client.create_review(request["id"], {"action": "APPROVE"}, APPROVER_HEADERS),
            ApiErrorId.ERR_UTILIZATION_THRESHOLD_NOT_MET,
            422,
        )

        still_open = read_request(request["id"])
        assert still_open["status"] == "PENDING_REVIEW"
        assert_pct(
            still_open["utilization_pct_at_submission"], 40.00, "utilization_pct_at_submission"
        )
        assert still_open["assigned_block_ids"] == []
        assert read_request(request["id"])["granted_block_count"] == 0
        assert pool_blocks[0]["allocation_status"] == "POOL_AVAILABLE"


def _applicant_whose_readiness_lapsed_after_filing():
    """Carrier A filed at 93.33 while verified, then failed its re-inspection."""
    set_clock()
    carrier = create_eligible_carrier("A")
    npa, rate_center = setup_npa_with_rate_center()
    pool_blocks = load_pool_blocks(npa, rate_center, 1, nxx_code="556")
    create_submitted_filing(
        carrier, rate_center,
        numbers_assigned=2800, numbers_intermediate=0, numbers_reserved=0,
        numbers_aging=0, numbers_administrative=0,
        blocks_held_at_period_end=3, forecast_quarters=[1200, 800, 600, 400],
    )
    request = file_allocation_request(
        carrier, rate_center, request_type="GROWTH", requested_block_count=1,
        justification="one growth block",
    )
    fail_readiness(carrier)
    return carrier, pool_blocks, request


class TestReadinessIsRecheckedAtReviewTime:
    """The facilities axis is read again when the approver acts, not at filing."""

    def test_a_failed_re_inspection_between_filing_and_review_blocks_the_approval(self):
        """The request was filed by an eligible carrier, yet the approval consults the
        carrier as it stands now and refuses it.

        The applicant's `eligibility_status` is re-evaluated at review time rather than
        inherited from the snapshot, and here it must read exactly `ELIGIBLE`

        `FAIL` from `VERIFIED` does exactly the same thing — a failed re-inspection revokes
        verified readiness, setting `facilities_readiness_status` to `FAILED`

        Design: Difficulty/cross_entity_state_dependency/allocation_approval_rechecks_carrier_readiness_at_review_time
        """
        carrier, pool_blocks, request = _applicant_whose_readiness_lapsed_after_filing()

        lapsed = read_carrier(carrier["id"])
        assert lapsed["facilities_readiness_status"] == "FAILED"
        assert lapsed["eligibility_status"] == "INELIGIBLE"
        assert lapsed["license_status"] == "GRANTED"

        validate_error(
            api_client.create_review(request["id"], {"action": "APPROVE"}, APPROVER_HEADERS),
            ApiErrorId.ERR_CARRIER_NOT_ELIGIBLE,
            422,
        )

        refused = read_request(request["id"])
        assert refused["status"] == "PENDING_REVIEW"
        assert refused["approver_user_id"] is None
        assert refused["assigned_block_ids"] == []
        assert pool_blocks[0]["allocation_status"] == "POOL_AVAILABLE"

    def test_re_attesting_and_verifying_restores_the_approval_without_touching_the_licence(self):
        """Walking the facilities axis back up to verified is enough on its own; the
        licensing axis never moved and the same approval now lands.

        The facilities axis is cyclic too: a carrier at `FAILED` may re-attest, which moves
        `FAILED → ATTESTED` with the resubmitted `switch_clli`

        `VERIFY` moves `ATTESTED → VERIFIED`, and is accepted only when
        `interconnection_ready` reads true

        Design: Difficulty/cross_entity_state_dependency/allocation_approval_rechecks_carrier_readiness_at_review_time
        """
        carrier, pool_blocks, request = _applicant_whose_readiness_lapsed_after_filing()
        validate_error(
            api_client.create_review(request["id"], {"action": "APPROVE"}, APPROVER_HEADERS),
            ApiErrorId.ERR_CARRIER_NOT_ELIGIBLE,
            422,
        )

        reattested = attest_readiness(carrier)
        assert reattested["facilities_readiness_status"] == "ATTESTED"
        verified = verify_readiness(carrier)
        assert verified["facilities_readiness_status"] == "VERIFIED"
        assert verified["eligibility_status"] == "ELIGIBLE"
        assert verified["license_status"] == "GRANTED"

        approve_request(request)

        decided = read_request(request["id"])
        assert decided["status"] == "APPROVED"
        assert decided["granted_block_count"] == 1
        assert decided["assigned_block_ids"] == [pool_blocks[0]["id"]]
