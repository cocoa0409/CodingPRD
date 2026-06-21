"""Difficulty Rule 5 — priority_pair_validation_conflict.

A single request that violates two distinct categories of validation. The
PRD's strict pipeline (§2.7) names the order in which categories surface,
so only category pairs whose ordering is explicitly named by PRD prose are
testable.

Skipped: `business_safety_beats_business_referential_on_award_insurance_and_contract_stale`
— PRD §2.7 orders categories only up to ERR_STALE_VERSION; for the
final "domain-specific business rules" bucket the PRD does not pin the
relative ordering between ERR_INSURANCE_EXPIRED and ERR_CONTRACT_RATE_STALE.
Two PRD-only readers could ship different orderings without violating PRD
prose, so this instance fails unique-derivability and is not translated.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    clock_advance,
    create_qualified_carrier,
    create_quote,
    create_shipper,
    get_success_data,
    set_clock,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.factories import award_quote_payload


class TestStateBeatsBusinessSafetyOnAwardExpiredQuoteAndSmartwayViolation:
    def test_award_against_expired_quote_with_smartway_violation_returns_invalid_state(self, api):
        """PRD §2.7: "a request that violates several rules surfaces the rule
        with the lowest priority number, not the most domain-specific one.
        The pipeline is, in order: authentication header presence
        (`ERR_UNAUTHENTICATED`); role authorization for the targeted
        endpoint (`ERR_UNAUTHORIZED`); existence of every path-parameter
        resource resolved strictly left-to-right (`ERR_RESOURCE_NOT_FOUND`);
        existence of every foreign-key reference present in the request body
        (`ERR_FK_NOT_FOUND`); state-machine admissibility of the requested
        transition (`ERR_INVALID_STATE`); optimistic-concurrency
        parent-version match for the two OCC-guarded endpoints
        (`ERR_STALE_VERSION`); and finally the domain-specific business
        rules detailed throughout §3 and listed in §5."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_award_expired_quote_and_smartway_violation
        """
        set_clock("2026-06-01T00:00:00Z")
        shipper = create_shipper(credit_limit_cents=100_000_000)
        # SmartWay-violating carrier: tier=NONE but the quote will require SmartWay.
        carrier = create_qualified_carrier(
            smartway_tier="NONE",
            insurance_expiry_utc="2027-01-01T00:00:00Z",
            safety_score=30.0,
        )
        quote = create_quote(
            shipper["id"], lane_origin="10001", lane_destination="30303",
            distance_miles=400,
            pickup_window_start_utc="2026-06-05T08:00:00Z",
            pickup_window_end_utc="2026-06-05T18:00:00Z",
            requested_equipment="DRY_VAN",
            requires_smartway=True,
        )
        # Advance the clock past the quote's expires_at_utc and run the sweep.
        set_clock("2026-06-10T00:00:00Z")
        clock_advance()

        # Now the quote is EXPIRED (state-machine inadmissible AWARD); the
        # carrier still violates SmartWay (business safety). PRD §2.7 says
        # state wins.
        res = api.award_quote(
            quote["id"],
            award_quote_payload(carrier["id"], quote["version"]),
            TEST_USERS["broker_ops_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")

        quote_after = get_success_data(
            api_client.get_quote_request(quote["id"], TEST_USERS["broker_ops_headers"])
        )
        # The quote is EXPIRED — and no Load was created.
        assert quote_after["status"] == "EXPIRED"

    def test_state_error_blocks_award_before_smartway_check_runs(self, api):
        """PRD §2.7: "The pipeline is, in order: authentication header
        presence (`ERR_UNAUTHENTICATED`); role authorization for the
        targeted endpoint (`ERR_UNAUTHORIZED`); existence of every
        path-parameter resource resolved strictly left-to-right
        (`ERR_RESOURCE_NOT_FOUND`); existence of every foreign-key
        reference present in the request body (`ERR_FK_NOT_FOUND`);
        state-machine admissibility of the requested transition
        (`ERR_INVALID_STATE`); optimistic-concurrency parent-version
        match for the two OCC-guarded endpoints (`ERR_STALE_VERSION`);
        and finally the domain-specific business rules detailed
        throughout §3 and listed in §5."

        Confirming the ordering directionally: even though the smartway
        precondition would also fail in isolation, the response surfaces the
        state error (which sits above the business-rules bucket) and the
        QuoteRequest stays at EXPIRED.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_award_expired_quote_and_smartway_violation
        """
        set_clock("2026-06-01T00:00:00Z")
        shipper = create_shipper(credit_limit_cents=100_000_000)
        carrier = create_qualified_carrier(
            smartway_tier="NONE",
            insurance_expiry_utc="2027-01-01T00:00:00Z",
            safety_score=30.0,
        )
        quote = create_quote(
            shipper["id"], lane_origin="10001", lane_destination="30303",
            distance_miles=400,
            pickup_window_start_utc="2026-06-05T08:00:00Z",
            pickup_window_end_utc="2026-06-05T18:00:00Z",
            requested_equipment="DRY_VAN",
            requires_smartway=True,
        )
        set_clock("2026-06-10T00:00:00Z")
        clock_advance()

        res = api.award_quote(
            quote["id"],
            award_quote_payload(carrier["id"], quote["version"]),
            TEST_USERS["broker_ops_headers"],
        )
        body = validate_error(res, "ERR_INVALID_STATE")
        # The error body carries the ERR_INVALID_STATE id, not ERR_SMARTWAY_INELIGIBLE.
        assert body["error_id"] == "ERR_INVALID_STATE"
