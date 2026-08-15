"""Filing and acknowledgment: submit side effects, the Carmack deadline and
acknowledgment clocks, counter conservation under submit/withdraw, and the
validation priority between claim state and the filing deadline."""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    ApiErrorId,
    assert_claim,
    get_carrier,
    get_claim,
    get_lane,
    get_shipment,
    set_clock,
    setup_claim_draft,
    setup_claim_submitted,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestSubmitSideEffects:
    def test_submit_stamps_filing_times_and_deadlines(self, api):
        """PRD §3.3: "A successful submission stamps `filing_received_at` with the current logical time, computes `filing_deadline_at` as the shipment's `ship_date` plus the carrier's `carmack_filing_days`, and computes `acknowledgment_due_at` as the filing receipt time plus the carrier's `carmack_acknowledgment_days`."
        PRD §3.3: "It then ripples outward: the carrier's `claims_filed_count` increases by one and its `claim_ratio_bp` is recomputed; the lane's `claims_count` increases by one and `lane_claim_ratio_bp` is recomputed; the shipment moves from `DELIVERED` to `CLAIMED`; a `FILED` event is appended to the claim's log; and the claim's `version` increments."

        Design: Corner/state_machines/claim_submit_side_effects_full_chain
        """
        ctx = setup_claim_submitted(submit_clock="2026-06-10T12:00:00Z")
        claim = ctx["claim"]
        assert_claim(claim)
        assert claim["filing_status"] == "SUBMITTED"

        received = _parse_ts(claim["filing_received_at"])
        assert received == datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
        ship_date = _parse_ts(ctx["shipment"]["ship_date"])
        assert _parse_ts(claim["filing_deadline_at"]) == ship_date + timedelta(
            days=270
        )
        assert _parse_ts(claim["acknowledgment_due_at"]) == received + timedelta(
            days=30
        )

        assert get_shipment(ctx["shipment"]["id"])["status"] == "CLAIMED"
        assert get_carrier(ctx["carrier"]["id"])["claims_filed_count"] == 1
        assert get_lane(ctx["lane"]["id"])["claims_count"] == 1

    def test_submit_is_immediately_visible_on_counters(self, api):
        """PRD §3.3: "It then ripples outward: the carrier's `claims_filed_count` increases by one and its `claim_ratio_bp` is recomputed; the lane's `claims_count` increases by one and `lane_claim_ratio_bp` is recomputed; the shipment moves from `DELIVERED` to `CLAIMED`; a `FILED` event is appended to the claim's log; and the claim's `version` increments."

        Design: Corner/consistency_model/submit_response_immediately_reflects_counters
        """
        ctx = setup_claim_submitted()
        # The submit response body itself carries the new state.
        assert ctx["claim"]["filing_status"] == "SUBMITTED"
        assert ctx["claim"]["filing_received_at"] is not None
        # And the carrier counter is visible on an immediate read.
        carrier = get_carrier(ctx["carrier"]["id"])
        assert carrier["claims_filed_count"] == 1

    def test_resubmit_of_submitted_claim_rejected(self, api):
        """PRD §3.3: "Submitting a claim is the act that starts every statutory clock, and a `ClaimsClerk` may submit only a `DRAFT` claim (anything else is `ERR_CLAIM_INVALID_STATE`)."

        Design: Corner/state_machines/claim_submit_from_submitted_rejected
        """
        ctx = setup_claim_submitted()
        resp = api.submit_claim(ctx["claim"]["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE)


class TestSubmitValidationPriority:
    def test_resubmit_after_deadline_reports_state_error(self, api):
        """PRD §2.9: "When several validations could apply to the same request, they are evaluated in a fixed priority order, and the earliest failure is the one reported."
        PRD §2.9: "The order is: (1) header presence and well-formedness, producing `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role authorization, producing `ERR_INSUFFICIENT_PERMISSIONS`; (3) left-to-right existence of every path identifier, producing the resource-specific 404 of §2.8; (4) whether the parent claim's state admits the requested child operation at all, producing `ERR_CLAIM_INVALID_STATE` (HTTP 409); (5) optimistic concurrency, producing `ERR_STALE_VERSION`; (6) segregation of duties, producing `ERR_SEGREGATION_OF_DUTIES_VIOLATION`; (7) business temporal rules — the filing deadline at submit, a salvage execution time in the future at scheduling, and a delivery date no earlier than the ship date at shipment registration — producing `ERR_FILING_DEADLINE_PASSED` (HTTP 422); (8) required-document presence at submit, producing `ERR_REQUIRED_DOCUMENT_MISSING` (HTTP 422); (9) document verification completeness at assessment, producing `ERR_DOCUMENTS_NOT_VERIFIED` (HTTP 422); (10) fiscal amount checks, producing `ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED_VALUE` (HTTP 422); (11) reserve coverage at settlement acceptance, producing `ERR_RESERVE_INSUFFICIENT` (HTTP 402); (12) settlement authority tier, producing `ERR_AUTHORITY_TIER_INSUFFICIENT` (HTTP 403); (13) appeal-round eligibility, producing `ERR_APPEAL_ROUND_EXHAUSTED` (HTTP 409); (14) claim-opening referential gating, producing `ERR_SHIPMENT_NOT_DELIVERED` (HTTP 409); (15) uniqueness of natural keys, producing `ERR_DUPLICATE_KEY` (HTTP 409); (16) the indemnity-first gate on subrogation, producing `ERR_CLAIM_NOT_PAID` (HTTP 409); and (17) the open-exposure gate on carrier and lane lifecycle actions, producing `ERR_OPEN_EXPOSURE_EXISTS` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_submit
        """
        # Claim already SUBMITTED; then the clock advances past the filing
        # deadline (ship_date 2026-06-01 + carmack_filing_days 270 -> 2027-02-26),
        # so both the state check (4) and the temporal check (7) would fail —
        # (4) wins. (The 270-day window is the statutory floor of PRD §3.1,
        # which a contract may lengthen but never shorten, so the deadline is
        # reached by advancing the clock rather than shrinking the window.)
        ctx = setup_claim_submitted(submit_clock="2026-06-10T00:00:00Z")
        set_clock("2027-03-01T00:00:00Z")
        resp = api.submit_claim(ctx["claim"]["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE)

    def test_submit_after_filing_deadline_rejected(self, api):
        """PRD §3.3: "The logical time at submission must be no later than the claim's `filing_deadline_at`, else `ERR_FILING_DEADLINE_PASSED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_submit
        """
        # Isolated temporal failure: claim still DRAFT, documents attached,
        # amount within declared value — only the deadline has passed
        # (ship_date 2026-06-01 + carmack_filing_days 270 -> 2027-02-26; the
        # 270-day statutory floor of PRD §3.1 may not be shortened, so the
        # deadline is passed by advancing the clock).
        ctx = setup_claim_draft()
        claim_id = ctx["claim"]["id"]
        from test_helpers import create_document_payload, get_success_data

        get_success_data(
            api.attach_document(
                claim_id, create_document_payload(document_kind="BOL"), CLERK
            )
        )
        get_success_data(
            api.attach_document(
                claim_id,
                create_document_payload(document_kind="COMMERCIAL_INVOICE"),
                CLERK,
            )
        )
        set_clock("2027-03-01T00:00:00Z")
        resp = api.submit_claim(claim_id, CLERK)
        validate_error(resp, ApiErrorId.ERR_FILING_DEADLINE_PASSED)


class TestAcknowledgmentLatenessBoundary:
    def test_acknowledge_exactly_at_due_instant_is_on_time(self, api):
        """PRD §3.3: "Lateness is judged by a strict comparison: an acknowledgment recorded later than `acknowledgment_due_at` sets `acknowledgment_late` to true and appends an `ACK_LATE_FLAGGED` event, while one landing exactly at the due instant is on time."

        Design: Difficulty/boundary_precision_check/acknowledgment_late_strictly_greater_than
        """
        # Submitted at 2026-06-10T00:00:00Z with a 30-day acknowledgment window,
        # so acknowledgment_due_at is 2026-07-10T00:00:00Z exactly.
        ctx = setup_claim_submitted(submit_clock="2026-06-10T00:00:00Z")
        set_clock("2026-07-10T00:00:00Z")
        resp = api.acknowledge_claim(ctx["claim"]["id"], ADJUSTER)
        claim = validate_success(resp, 200)
        assert _parse_ts(claim["acknowledged_at"]) == datetime(
            2026, 7, 10, 0, 0, tzinfo=timezone.utc
        )
        assert _parse_ts(claim["acknowledged_at"]) == _parse_ts(
            claim["acknowledgment_due_at"]
        )
        assert claim["acknowledgment_late"] is False

    def test_acknowledge_after_due_instant_flagged_late(self, api):
        """PRD §3.3: "Lateness is judged by a strict comparison: an acknowledgment recorded later than `acknowledgment_due_at` sets `acknowledgment_late` to true and appends an `ACK_LATE_FLAGGED` event, while one landing exactly at the due instant is on time."

        Design: Difficulty/boundary_precision_check/acknowledgment_late_strictly_greater_than
        """
        ctx = setup_claim_submitted(submit_clock="2026-06-10T00:00:00Z")
        set_clock("2026-07-10T00:00:01Z")  # one second past the due instant
        resp = api.acknowledge_claim(ctx["claim"]["id"], ADJUSTER)
        claim = validate_success(resp, 200)
        assert claim["acknowledgment_late"] is True
        events, _meta = validate_paginated(
            api.list_claim_events(
                ctx["claim"]["id"], CLERK, params={"event_kind": "ACK_LATE_FLAGGED"}
            )
        )
        assert len(events) >= 1, "ACK_LATE_FLAGGED event must be appended"


class TestFiledCountConservation:
    def test_submit_increments_carrier_and_lane_counters(self, api):
        """PRD §3.3: "It then ripples outward: the carrier's `claims_filed_count` increases by one and its `claim_ratio_bp` is recomputed; the lane's `claims_count` increases by one and `lane_claim_ratio_bp` is recomputed; the shipment moves from `DELIVERED` to `CLAIMED`; a `FILED` event is appended to the claim's log; and the claim's `version` increments."

        Design: Difficulty/compensating_invariant/claim_filed_count_conserved_under_submit_withdraw
        """
        ctx = setup_claim_submitted()
        assert get_carrier(ctx["carrier"]["id"])["claims_filed_count"] == 1
        assert get_lane(ctx["lane"]["id"])["claims_count"] == 1

    def test_withdraw_submitted_claim_restores_counters(self, api):
        """PRD §3.3: "Withdrawing a claim that had been submitted or acknowledged decrements the carrier's `claims_filed_count` and the lane's `claims_count` and recomputes both ratios; withdrawal from `DRAFT` touches no counters, since they were never incremented."
        PRD §3.3: "In every case the shipment reverts from `CLAIMED` to `DELIVERED`, provided no other claim on the same shipment remains in a non-terminal state; the claim's `version` increments and a `WITHDRAWN` event is recorded."

        Design: Difficulty/compensating_invariant/claim_filed_count_conserved_under_submit_withdraw
        """
        ctx = setup_claim_submitted()
        resp = api.withdraw_claim(ctx["claim"]["id"], CLERK)
        claim = validate_success(resp, 200)
        assert claim["filing_status"] == "WITHDRAWN"
        # Compensation: both counters return to their pre-submit values.
        assert get_carrier(ctx["carrier"]["id"])["claims_filed_count"] == 0
        assert get_lane(ctx["lane"]["id"])["claims_count"] == 0
        assert get_shipment(ctx["shipment"]["id"])["status"] == "DELIVERED"
