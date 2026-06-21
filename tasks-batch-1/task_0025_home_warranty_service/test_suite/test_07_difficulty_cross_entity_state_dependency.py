"""Difficulty Rule 7 — cross_entity_state_dependency.

POST /claims depends on the parent Contract's status (∈ ACTIVE / EXPIRING_SOON);
POST /contracts/{id}/cancel from ACTIVE depends on no child ClaimTicket being in
{SUBMITTED, ASSESSED, DISPATCHED}.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    set_clock,
    setup_expired_contract_with_item,
    setup_active_contract_with_dispatched_claim,
    make_customer_headers,
    create_claim_payload,
)


class TestClaimCreationBlockedByExpiredContract:
    """POST /claims against an EXPIRED contract → ERR_OUT_OF_COVERAGE. PRD §3.4."""

    def test_claim_on_expired_contract_rejected_out_of_coverage(self, api):
        """PRD §3.4: "The coverage-window guard is enforced at filing time: the
        request is rejected with `ERR_OUT_OF_COVERAGE` unless the server clock is
        in the half-open interval from `coverage_start_utc` (inclusive) to
        `coverage_end_utc` (exclusive) and the contract's `status` is one of
        `ACTIVE` or `EXPIRING_SOON`."

        Design: Difficulty/cross_entity_state_dependency/claim_creation_blocked_by_expired_contract
        """
        package, customer, expired_contract, item = setup_expired_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
            tick_at="2027-02-01T00:00:00Z",
            category="OVEN",
        )
        assert expired_contract["status"] == "EXPIRED"
        cust_h = make_customer_headers(customer["id"])
        res = api.create_claim(
            create_claim_payload(expired_contract["id"], item["id"],
                                  issue_summary="Belated"),
            cust_h,
        )
        validate_error(res, "ERR_OUT_OF_COVERAGE")

    def test_claim_on_active_contract_outside_window_rejected(self, api):
        """PRD §3.4: "The coverage-window guard is enforced at filing time: the
        request is rejected with `ERR_OUT_OF_COVERAGE` unless the server clock is
        in the half-open interval from `coverage_start_utc` (inclusive) to
        `coverage_end_utc` (exclusive) and the contract's `status` is one of
        `ACTIVE` or `EXPIRING_SOON`."

        Design: Difficulty/cross_entity_state_dependency/claim_creation_blocked_by_expired_contract
        """
        # PRD §3.4 binds both conjuncts: (clock ∈ window) AND (status ∈ {ACTIVE, EXPIRING_SOON}).
        # An EXPIRED contract violates both.
        package, customer, expired, item = setup_expired_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
            tick_at="2027-06-15T00:00:00Z",
            category="HVAC",
        )
        cust_h = make_customer_headers(customer["id"])
        res = api.create_claim(
            create_claim_payload(expired["id"], item["id"], issue_summary="Outside window"),
            cust_h,
        )
        validate_error(res, "ERR_OUT_OF_COVERAGE")


class TestContractCancelBlockedByOpenClaim:
    """POST /contracts/{id}/cancel from ACTIVE with an in-flight ClaimTicket in
    {SUBMITTED, ASSESSED, DISPATCHED} → ERR_OPEN_CLAIMS_BLOCK_CANCEL. PRD §3.2."""

    def test_cancel_with_dispatched_claim_returns_open_claims_block_cancel(self, api):
        """PRD §3.2: "Cancellation from `ACTIVE` is also permitted, but only when
        no `ClaimTicket` on the contract is in `SUBMITTED`, `ASSESSED`, or
        `DISPATCHED` — that is, no open claim is in flight. If any such open claim
        exists, the cancellation is rejected with `ERR_OPEN_CLAIMS_BLOCK_CANCEL`."

        Design: Difficulty/cross_entity_state_dependency/contract_cancel_blocked_by_open_claim
        """
        package, customer, contract, item, claim, dispatch = setup_active_contract_with_dispatched_claim(
            activate_at="2026-01-01T00:00:00Z",
            schedule_at="2026-02-01T08:00:00Z",
            scheduled_utc="2026-02-01T09:00:00Z",
            technician_id="tech-A",
            repair_cost_cents=10_000,
        )
        assert claim["status"] == "DISPATCHED"
        cust_h = make_customer_headers(customer["id"])
        res = api.cancel_contract(contract["id"], cust_h)
        validate_error(res, "ERR_OPEN_CLAIMS_BLOCK_CANCEL")

    def test_cancel_blocked_when_only_a_submitted_claim_exists(self, api):
        """PRD §3.2: "Cancellation from `ACTIVE` is also permitted, but only when
        no `ClaimTicket` on the contract is in `SUBMITTED`, `ASSESSED`, or
        `DISPATCHED` — that is, no open claim is in flight."

        Design: Difficulty/cross_entity_state_dependency/contract_cancel_blocked_by_open_claim
        """
        # SUBMITTED is one of the open statuses.
        from test_helpers import (
            setup_active_contract_with_item, file_claim, make_customer_headers,
        )
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
        )
        claim = file_claim(contract, customer, item, issue="Just filed")
        assert claim["status"] == "SUBMITTED"
        cust_h = make_customer_headers(customer["id"])
        res = api.cancel_contract(contract["id"], cust_h)
        validate_error(res, "ERR_OPEN_CLAIMS_BLOCK_CANCEL")
