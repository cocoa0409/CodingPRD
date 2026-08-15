"""Segment setup and claim intake: creation defaults, request-shape
validation, existence, the append-only ledger contract, and claim listing
with pagination and filters (PRD §2.3, §2.4, §2.8, §3.1, §3.2).
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_claim_transaction,
    assert_segment,
    create_claim,
    create_claim_payload,
    create_segment,
    create_segment_payload,
    payment_payload,
    transition_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSegmentCreation:
    def test_segment_creation_applies_defaults(self, api, appointed_actuary_headers):
        """PRD §3.1: "Every segment carries a computed `last_closed_quarter`:
        the maximum valuation quarter across the segment's `APPROVED` studies,
        or null when no study has been approved yet."

        Design: Corner/entities/segment_creation_applies_defaults
        """
        payload = create_segment_payload(
            name="New Book",
            line_of_business="PROPERTY",
            large_loss_threshold_cents=250000,
            max_range_width_pct=0.8,
            benchmark_open_severity_cents=30000,
        )
        resp = api.create_segment(payload, appointed_actuary_headers)
        data = validate_success(resp, 201)
        assert_segment(data)
        assert data["last_closed_quarter"] is None, (
            "no study has been approved, so the quarter-close checkpoint must be null"
        )
        assert data["name"] == "New Book"
        assert data["line_of_business"] == "PROPERTY"
        assert data["large_loss_threshold_cents"] == 250000
        assert data["max_range_width_pct"] == pytest.approx(0.8)
        assert data["benchmark_open_severity_cents"] == 30000


class TestClaimIntakeValidation:
    def test_claim_create_missing_required_field_returns_400(
        self, api, claims_examiner_headers
    ):
        """PRD §2.8: "**Request shape** — required fields are present, types
        are valid, enum values are within their declared domains, quarter
        labels match the `YYYY-Qn` form, dates are ISO dates, payment and
        reversal amounts are positive, a case value is present on reserve-set
        transactions, Bornhuetter-Ferguson runs carry both the exposure and the
        a-priori ratio, report dates are not earlier than accident dates, and
        bodies are free of server-managed fields — `id`, `created_at`,
        `updated_at`, `version`, or any computed field. Violations are
        `ERR_INVALID_REQUEST` (400)."
        PRD §3.2: "A `ClaimsExaminer` registers a claim with its `segment_id`,
        a business `claim_number`, an `accident_date`, and a `report_date` that
        must not be earlier than the accident date."

        Design: Corner/entities/claim_create_missing_required_field_returns_400
        """
        segment = create_segment(
            name="Req Book",
            line_of_business="PROPERTY",
            large_loss_threshold_cents=250000,
            max_range_width_pct=0.8,
            benchmark_open_severity_cents=30000,
        )
        payload = {
            "segment_id": segment["id"],
            "claim_number": "C-X",
            "report_date": "2025-01-20",
        }
        resp = api.create_claim(payload, claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_claim_create_with_server_managed_field_returns_400(
        self, api, claims_examiner_headers
    ):
        """PRD §2.8: "**Request shape** — required fields are present, types
        are valid, enum values are within their declared domains, quarter
        labels match the `YYYY-Qn` form, dates are ISO dates, payment and
        reversal amounts are positive, a case value is present on reserve-set
        transactions, Bornhuetter-Ferguson runs carry both the exposure and the
        a-priori ratio, report dates are not earlier than accident dates, and
        bodies are free of server-managed fields — `id`, `created_at`,
        `updated_at`, `version`, or any computed field. Violations are
        `ERR_INVALID_REQUEST` (400)."
        PRD §3.2: "A new claim starts `OPEN` with zero financials:
        `paid_to_date_cents` and `case_outstanding_cents` both begin at zero"

        Design: Corner/entities/claim_create_with_server_managed_field_returns_400
        """
        segment = create_segment(
            name="Req Book",
            line_of_business="PROPERTY",
            large_loss_threshold_cents=250000,
            max_range_width_pct=0.8,
            benchmark_open_severity_cents=30000,
        )
        payload = create_claim_payload(
            segment["id"],
            claim_number="C-X",
            accident_date="2025-01-15",
            report_date="2025-01-20",
        )
        payload["paid_to_date_cents"] = 999999
        resp = api.create_claim(payload, claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_claim_get_nonexistent_id_returns_404(self, api, actuarial_analyst_headers):
        """PRD §2.8: "Requests that address nested resources validate path
        identifiers in a strict left-to-right order: the first path identifier
        that does not correspond to an existing resource determines the
        `ERR_NOT_FOUND` response, before any deeper identifier or body rule is
        examined."

        Design: Corner/entities/claim_get_nonexistent_id_returns_404
        """
        resp = api.get_claim(NON_EXISTENT_UUID, actuarial_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestClaimTransactionLedger:
    def test_claim_transaction_is_append_only_event(
        self, api, claims_examiner_headers
    ):
        """PRD §2.4: "A claim transaction is an append-only event-log entry: it
        carries only `id` and `created_at` as system-managed properties —
        `updated_at` and `version` are absent — and entries are never modified
        after being posted."
        PRD §3.2: "Posting a transaction names a `type` and a
        `transaction_date`; the server derives the entry's `effective_quarter`
        as the quarter label of the transaction date and takes the entry's
        `claim_id` from the claim being addressed."

        Design: Corner/entities/claim_transaction_is_append_only_event
        """
        segment = create_segment(
            name="Evt Book",
            line_of_business="PROPERTY",
            large_loss_threshold_cents=250000,
            max_range_width_pct=0.8,
            benchmark_open_severity_cents=30000,
        )
        claim = create_claim(
            segment["id"],
            claim_number="C-E",
            accident_date="2025-01-15",
            report_date="2025-01-20",
        )
        resp = api.post_claim_transaction(
            claim["id"],
            payment_payload(
                transaction_date="2025-02-01T00:00:00Z", amount_cents=100000
            ),
            claims_examiner_headers,
        )
        data = validate_success(resp, 201)
        assert_claim_transaction(data)
        assert data["effective_quarter"] == "2025-Q1", (
            "2025-02-01 falls in quarter 2025-Q1"
        )
        assert data["claim_id"] == claim["id"]


class TestClaimListing:
    def test_claims_list_pagination_and_status_filter(
        self, api, actuarial_analyst_headers
    ):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return; if not provided it defaults to 10, with a minimum of 1
        and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §3.2: "Claims can be read individually — the response carries the
        computed financials, both segregation flags, and both adequacy ratios —
        or listed with optional `segment_id`, `catastrophe_event_id`, and
        `status` filters; a claim's `status` is one of `OPEN`, `CLOSED`, or
        `REOPENED`."

        Design: Corner/entities/claims_list_pagination_and_status_filter
        """
        segment = create_segment(
            name="Page Book",
            line_of_business="PROPERTY",
            large_loss_threshold_cents=250000,
            max_range_width_pct=0.8,
            benchmark_open_severity_cents=30000,
        )
        claim_p1 = create_claim(
            segment["id"],
            claim_number="C-P1",
            accident_date="2025-01-15",
            report_date="2025-01-20",
        )
        create_claim(
            segment["id"],
            claim_number="C-P2",
            accident_date="2025-02-15",
            report_date="2025-02-20",
        )
        create_claim(
            segment["id"],
            claim_number="C-P3",
            accident_date="2025-03-15",
            report_date="2025-03-20",
        )
        transition_claim(claim_p1["id"], "CLOSED")

        # Page 1 of 3 with limit 2.
        data, meta = validate_paginated(
            api.list_claims(
                actuarial_analyst_headers,
                params={"segment_id": segment["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(data) == 2, f"limit 2 must return exactly 2 claims, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

        # Status filter returns exactly the closed claim.
        data, meta = validate_paginated(
            api.list_claims(
                actuarial_analyst_headers,
                params={"segment_id": segment["id"], "status": "CLOSED"},
            )
        )
        assert len(data) == 1, f"status=CLOSED must return exactly 1 claim, got {len(data)}"
        assert data[0]["id"] == claim_p1["id"]
