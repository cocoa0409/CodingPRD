"""Claim lifecycle state machine and transaction-ledger invariants
(PRD §3.2): the OPEN -> CLOSED -> REOPENED -> CLOSED cycle, invalid
transitions, the zero-outstanding close gate, and the payment/reversal
conservation of reported incurred.
"""
from test_helpers import (
    ApiErrorId,
    assert_claim,
    case_reserve_set_payload,
    create_claim,
    create_segment,
    payment_reversal_payload,
    post_payment,
    transition_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


def _cycle_segment_and_claim():
    segment = create_segment(name="Cycle Book", line_of_business="PROPERTY")
    claim = create_claim(
        segment["id"],
        claim_number="C-N",
        accident_date="2025-01-15",
        report_date="2025-01-20",
    )
    return segment, claim


class TestClaimOpenClosedReopenedCycle:
    def test_claim_open_closed_reopened_cycle(self, api, claims_examiner_headers):
        """PRD §3.2: "Closing requires the claim to be `OPEN` or `REOPENED` and
        its `case_outstanding_cents` to be exactly zero; a claim still carrying
        case reserves cannot close, and the attempt is refused with
        `ERR_CLAIM_NOT_CLOSEABLE`."
        PRD §3.2: "A `CLOSED` claim may be reopened without preconditions,
        after which its adequacy ratios resume being computed on read; a
        `REOPENED` claim closes again under the same zero-outstanding rule."

        Design: Difficulty/non_linear_state_machine/claim_open_closed_reopened_cycle
        """
        _, claim = _cycle_segment_and_claim()

        data = validate_success(
            api.set_claim_status(
                claim["id"], {"target_status": "CLOSED"}, claims_examiner_headers
            ),
            200,
        )
        assert data["status"] == "CLOSED", "OPEN -> CLOSED must succeed at zero case outstanding"

        data = validate_success(
            api.set_claim_status(
                claim["id"], {"target_status": "REOPENED"}, claims_examiner_headers
            ),
            200,
        )
        assert data["status"] == "REOPENED", "CLOSED -> REOPENED is a declared cycle edge"

        data = validate_success(
            api.set_claim_status(
                claim["id"], {"target_status": "CLOSED"}, claims_examiner_headers
            ),
            200,
        )
        assert data["status"] == "CLOSED", "REOPENED -> CLOSED must succeed at zero case outstanding"

    def test_claim_cycle_increments_version_each_transition(
        self, api, claims_examiner_headers
    ):
        """PRD §3.2: "Both transitions are requested by supplying a
        `target_status` of `CLOSED` or `REOPENED`, and each increments the
        claim's `version`."
        PRD §2.4: "`version` (integer): a system-managed integer that
        increments with every modification to the resource"

        Design: Difficulty/non_linear_state_machine/claim_open_closed_reopened_cycle
        """
        _, claim = _cycle_segment_and_claim()
        previous_version = claim["version"]

        for target in ("CLOSED", "REOPENED", "CLOSED"):
            data = validate_success(
                api.set_claim_status(
                    claim["id"], {"target_status": target}, claims_examiner_headers
                ),
                200,
            )
            assert data["version"] == previous_version + 1, (
                f"each transition increments the claim's version by one: "
                f"expected {previous_version + 1}, got {data['version']}"
            )
            previous_version = data["version"]


class TestClaimInvalidTransitions:
    def test_claim_close_from_closed_returns_invalid_state(
        self, api, claims_examiner_headers
    ):
        """PRD §3.2: "Closing a claim that is already `CLOSED`, or reopening
        one that is not `CLOSED`, is refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/claim_close_from_closed_returns_invalid_state
        """
        _, claim = _cycle_segment_and_claim()
        closed = transition_claim(claim["id"], "CLOSED")

        resp = api.set_claim_status(
            claim["id"], {"target_status": "CLOSED"}, claims_examiner_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        data = validate_success(api.get_claim(claim["id"], claims_examiner_headers))
        assert data["status"] == "CLOSED"
        assert data["version"] == closed["version"], (
            "a rejected transition must not modify the claim"
        )

    def test_claim_reopen_from_open_returns_invalid_state(
        self, api, claims_examiner_headers
    ):
        """PRD §3.2: "Closing a claim that is already `CLOSED`, or reopening
        one that is not `CLOSED`, is refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/claim_reopen_from_open_returns_invalid_state
        """
        _, claim = _cycle_segment_and_claim()
        assert claim["status"] == "OPEN"
        resp = api.set_claim_status(
            claim["id"], {"target_status": "REOPENED"}, claims_examiner_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestClaimCloseGateAndLedgerGuards:
    def test_claim_close_with_open_case_rejected(self, api, claims_examiner_headers):
        """PRD §3.2: "Closing requires the claim to be `OPEN` or `REOPENED` and
        its `case_outstanding_cents` to be exactly zero; a claim still carrying
        case reserves cannot close, and the attempt is refused with
        `ERR_CLAIM_NOT_CLOSEABLE`."

        Design: Corner/validations/claim_close_with_open_case_rejected
        """
        segment = create_segment(name="F Book", line_of_business="PROPERTY")
        claim = create_claim(
            segment["id"],
            claim_number="C-F",
            accident_date="2025-01-15",
            report_date="2025-01-20",
        )
        resp = api.post_claim_transaction(
            claim["id"],
            case_reserve_set_payload(
                transaction_date="2025-02-01T00:00:00Z", case_value_cents=50000
            ),
            claims_examiner_headers,
        )
        validate_success(resp, 201)

        resp = api.set_claim_status(
            claim["id"], {"target_status": "CLOSED"}, claims_examiner_headers
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_CLOSEABLE)

        data = validate_success(api.get_claim(claim["id"], claims_examiner_headers))
        assert data["status"] == "OPEN"

    def test_case_reserve_set_negative_rejected(self, api, claims_examiner_headers):
        """PRD §3.2: "A `CASE_RESERVE_SET` requires a `case_value_cents` of
        zero or more — a negative value is refused with
        `ERR_CASE_OUTSTANDING_NEGATIVE` — and replaces the case outstanding
        with that absolute value rather than adjusting it."

        Design: Corner/validations/case_reserve_set_negative_rejected
        """
        segment = create_segment(name="F Book", line_of_business="PROPERTY")
        claim = create_claim(
            segment["id"],
            claim_number="C-F",
            accident_date="2025-01-15",
            report_date="2025-01-20",
        )
        resp = api.post_claim_transaction(
            claim["id"],
            case_reserve_set_payload(
                transaction_date="2025-02-01T00:00:00Z", case_value_cents=-100
            ),
            claims_examiner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_OUTSTANDING_NEGATIVE)

    def test_payment_reversal_exceeding_paid_rejected(self, api, claims_examiner_headers):
        """PRD §3.2: "A `PAYMENT_REVERSAL` requires a positive `amount_cents`
        no greater than the claim's current `paid_to_date_cents` — a larger
        reversal is refused with `ERR_PAYMENT_REVERSAL_EXCEEDS_PAID` — and
        subtracts the amount."

        Design: Corner/validations/payment_reversal_exceeding_paid_rejected
        """
        segment = create_segment(name="F Book", line_of_business="PROPERTY")
        claim = create_claim(
            segment["id"],
            claim_number="C-F",
            accident_date="2025-01-15",
            report_date="2025-01-20",
        )
        post_payment(claim["id"], "2025-02-01T00:00:00Z", 100000)

        resp = api.post_claim_transaction(
            claim["id"],
            payment_reversal_payload(
                transaction_date="2025-02-10T00:00:00Z", amount_cents=150000
            ),
            claims_examiner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_REVERSAL_EXCEEDS_PAID)

        data = validate_success(api.get_claim(claim["id"], claims_examiner_headers))
        assert data["paid_to_date_cents"] == 100000, (
            "a rejected reversal must leave paid_to_date_cents unchanged"
        )


class TestPaymentReversalConservation:
    def test_payment_and_reversal_conserve_reported_incurred(
        self, api, claims_examiner_headers
    ):
        """PRD §3.2: "A `PAYMENT` requires a positive `amount_cents` and adds
        that amount to paid-to-date. A `PAYMENT_REVERSAL` requires a positive
        `amount_cents` no greater than the claim's current `paid_to_date_cents`
        — a larger reversal is refused with `ERR_PAYMENT_REVERSAL_EXCEEDS_PAID`
        — and subtracts the amount."
        PRD §3.2: "`reported_incurred_cents` — which is always, by invariant,
        the sum of those two — likewise starts at zero."

        Design: Difficulty/compensating_invariant/payment_and_reversal_conserve_reported_incurred
        """
        segment = create_segment(name="Inv Book", line_of_business="GENERAL_LIABILITY")
        claim = create_claim(
            segment["id"],
            claim_number="M-1",
            accident_date="2025-01-15",
            report_date="2025-01-20",
        )
        post_payment(claim["id"], "2025-02-01T00:00:00Z", 300000)

        post_payment(claim["id"], "2025-03-01T00:00:00Z", 40000)
        resp = api.post_claim_transaction(
            claim["id"],
            payment_reversal_payload(
                transaction_date="2025-03-05T00:00:00Z", amount_cents=40000
            ),
            claims_examiner_headers,
        )
        validate_success(resp, 201)

        data = validate_success(api.get_claim(claim["id"], claims_examiner_headers))
        assert data["paid_to_date_cents"] == 300000, (
            "the forward+compensating pair must return paid_to_date_cents to 300000"
        )
        assert data["case_outstanding_cents"] == 0
        assert data["reported_incurred_cents"] == 300000

    def test_payment_reversal_pair_preserves_incurred_invariant_and_log_order(
        self, api, claims_examiner_headers
    ):
        """PRD §3.2: "A new claim starts `OPEN` with zero financials:
        `paid_to_date_cents` and `case_outstanding_cents` both begin at zero,
        and `reported_incurred_cents` — which is always, by invariant, the sum
        of those two — likewise starts at zero."
        PRD §3.2: "Each posting refreshes the claim's derived figures and bumps
        the claim's `version`, and the claim's transaction log can be listed in
        creation order."

        Design: Difficulty/compensating_invariant/payment_and_reversal_conserve_reported_incurred
        """
        segment = create_segment(name="Inv Book", line_of_business="GENERAL_LIABILITY")
        claim = create_claim(
            segment["id"],
            claim_number="M-1",
            accident_date="2025-01-15",
            report_date="2025-01-20",
        )
        post_payment(claim["id"], "2025-02-01T00:00:00Z", 300000)
        post_payment(claim["id"], "2025-03-01T00:00:00Z", 40000)
        resp = api.post_claim_transaction(
            claim["id"],
            payment_reversal_payload(
                transaction_date="2025-03-05T00:00:00Z", amount_cents=40000
            ),
            claims_examiner_headers,
        )
        validate_success(resp, 201)

        data = validate_success(api.get_claim(claim["id"], claims_examiner_headers))
        assert_claim(data)
        assert data["reported_incurred_cents"] == (
            data["paid_to_date_cents"] + data["case_outstanding_cents"]
        ), "reported incurred must remain the sum of paid-to-date and case outstanding"

        log, _ = validate_paginated(
            api.list_claim_transactions(claim["id"], claims_examiner_headers)
        )
        assert [entry["type"] for entry in log] == [
            "PAYMENT",
            "PAYMENT",
            "PAYMENT_REVERSAL",
        ], "the ledger must list entries in creation order"
