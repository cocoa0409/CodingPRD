"""Financial statements and reporting packages: due-date derivation, lateness,
duplicate triples, and closed-interval period windows (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_borrower,
    create_facility,
    create_package,
    create_package_payload,
    create_statement,
    create_statement_payload,
    make_agent_headers,
    make_borrower_headers,
    set_clock,
    validate_error,
    validate_success,
)

AGENT = make_agent_headers()


class TestFinancialStatements:
    def test_statement_receive_after_due_marks_late_received(self):
        """PRD §3.8: "the system copies `borrower_id` from the facility and
        derives the `due_date` — forty-five days after the period end for a
        quarterly statement, ninety days for an annual audited one."
        PRD §3.8: "When the agent marks receipt, the statement moves `EXPECTED` →
        `RECEIVED` if the current clock date is on or before the `due_date`, and
        `EXPECTED` → `LATE_RECEIVED` if it is after".

        Design: Corner/state_machines/statement_receive_after_due_marks_late_received
        """
        borrower = create_borrower(legal_name="Stmt B")
        facility = create_facility(borrower["id"], total_commitment_cents=5_000_000)
        statement = create_statement(
            facility["id"], borrower["id"],
            statement_type="QUARTERLY", period_end_date="2026-06-30",
            document_ref="s3://docs/q2.pdf",
        )
        assert statement["due_date"] == "2026-08-14"  # period_end + 45 days
        assert statement["status"] == "EXPECTED"
        assert statement["borrower_id"] == borrower["id"]

        set_clock("2026-08-20T00:00:00Z")
        received = validate_success(api_client.receive_financial_statement(statement["id"], AGENT))
        assert received["status"] == "LATE_RECEIVED"
        assert received["received_at"] is not None

    def test_duplicate_statement_rejected(self):
        """PRD §3.8: "One non-waived statement may exist per facility, type, and
        period end: a duplicate triple fails with `ERR_DUPLICATE_STATEMENT`."

        Design: Corner/validations/duplicate_statement_rejected
        """
        borrower = create_borrower(legal_name="DS B")
        facility = create_facility(borrower["id"], total_commitment_cents=5_000_000)
        create_statement(
            facility["id"], borrower["id"],
            statement_type="QUARTERLY", period_end_date="2026-06-30",
            document_ref="s3://a.pdf",
        )
        resp = api_client.create_financial_statement(
            create_statement_payload(
                facility["id"], statement_type="QUARTERLY",
                period_end_date="2026-06-30", document_ref="s3://b.pdf",
            ),
            make_borrower_headers(borrower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STATEMENT, expected_status=409)


class TestPackageWindows:
    def test_package_windows_closed_interval_adjacency_collides(self):
        """PRD §3.8: "Period windows on the same facility are closed intervals
        and must not overlap at all: unlike draws, adjacency collides here, so a
        package whose start equals a sibling's end is an overlap, rejected with
        `ERR_PACKAGE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/package_windows_closed_interval_adjacency_collides
        """
        borrower = create_borrower(legal_name="Pkg B")
        facility = create_facility(borrower["id"], total_commitment_cents=10_000_000)
        pkg1 = create_package(
            facility["id"], period_label="2026-06",
            period_start_date="2026-06-01", period_end_date="2026-06-30",
            due_date="2026-08-15",
        )
        assert pkg1["status"] == "OPEN"

        # Closed-interval adjacency: start == prior end collides.
        resp = api_client.create_reporting_package(
            create_package_payload(
                facility["id"], period_label="2026-07",
                period_start_date="2026-06-30", period_end_date="2026-07-31",
                due_date="2026-09-15",
            ),
            AGENT,
        )
        validate_error(resp, ApiErrorId.ERR_PACKAGE_WINDOW_OVERLAP, expected_status=409)

        # One day later is strictly outside the closed interval: accepted.
        pkg3 = validate_success(
            api_client.create_reporting_package(
                create_package_payload(
                    facility["id"], period_label="2026-07b",
                    period_start_date="2026-07-01", period_end_date="2026-07-31",
                    due_date="2026-09-15",
                ),
                AGENT,
            ),
            expected_status=201,
        )
        assert pkg3["status"] == "OPEN"

    def test_package_inverted_range_rejected_and_single_day_allowed(self):
        """PRD §3.8: "a closed period interval from `period_start_date` to
        `period_end_date` — the end must be on or after the start, failing
        `ERR_INVALID_REQUEST`".

        Design: Difficulty/resource_temporal_overlap/package_windows_closed_interval_adjacency_collides
        """
        borrower = create_borrower(legal_name="Pkg2 B")
        facility = create_facility(borrower["id"], total_commitment_cents=10_000_000)

        resp = api_client.create_reporting_package(
            create_package_payload(
                facility["id"], period_label="bad",
                period_start_date="2026-05-02", period_end_date="2026-05-01",
                due_date="2026-08-15",
            ),
            AGENT,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        # "on or after": a single-day closed interval (start == end) is valid.
        pkg = validate_success(
            api_client.create_reporting_package(
                create_package_payload(
                    facility["id"], period_label="single",
                    period_start_date="2026-05-01", period_end_date="2026-05-01",
                    due_date="2026-08-15",
                ),
                AGENT,
            ),
            expected_status=201,
        )
        assert pkg["status"] == "OPEN"
