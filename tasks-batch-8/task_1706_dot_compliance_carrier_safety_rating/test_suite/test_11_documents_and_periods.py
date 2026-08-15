"""Document retention and purging, plus the annual random testing program:
retention calendars, purge gating, quota ceilings, and close verdicts."""
from test_helpers import (
    ApiErrorId,
    create_document_payload,
    create_period_payload,
    create_test_payload,
    get_document,
    get_period,
    make_carrier,
    make_document,
    make_manager_headers,
    make_mro_headers,
    make_period,
    make_driver,
    run_cycle,
    make_audit_case,
    set_clock,
    validate_error,
    validate_success,
)


class TestDocumentRetention:
    def test_document_retention_computed_by_type(self, api, manager_headers):
        """PRD §3.10: "Retention is derived from the document type:
        `retention_months` is 12 for `INSPECTION_REPORT`; 36 for `DQ_FILE`,
        `ACCIDENT_REGISTER_ENTRY`, and `TRAINING_CERTIFICATE`; and 60 for
        `DRUG_TEST_RECORD` and `ALCOHOL_TEST_RECORD`. The `retention_until`
        deadline is `filed_at` advanced by that many calendar months".

        Design: Corner/entities/document_retention_computed_by_type
        """
        carrier = make_carrier(dot_number="DOT-2004")
        inspection_report = validate_success(
            api.create_document(
                create_document_payload(
                    carrier["id"], document_type="INSPECTION_REPORT",
                    filed_at="2026-01-15T00:00:00Z",
                ),
                manager_headers,
            ),
            201,
        )
        assert inspection_report["retention_months"] == 12
        assert str(inspection_report["retention_until"]).startswith("2027-01-15")
        assert inspection_report["status"] == "RETAINED"

        drug_record = validate_success(
            api.create_document(
                create_document_payload(
                    carrier["id"], document_type="DRUG_TEST_RECORD",
                    filed_at="2026-01-15T00:00:00Z",
                ),
                manager_headers,
            ),
            201,
        )
        assert drug_record["retention_months"] == 60
        assert str(drug_record["retention_until"]).startswith("2031-01-15")

    def test_retention_leap_day_clamp(self, api, manager_headers):
        """PRD §3.10: "The `retention_until` deadline is `filed_at` advanced by
        that many calendar months, with the day-of-month clamped to the target
        month's last day when it does not exist — 2024-02-29 plus twelve months
        yields 2025-02-28, while 2026-01-31 plus twelve months yields
        2027-01-31."

        Design: Corner/calculations/retention_leap_day_clamp
        """
        carrier = make_carrier(dot_number="DOT-2206")
        dq_file = validate_success(
            api.create_document(
                create_document_payload(
                    carrier["id"], document_type="DQ_FILE",
                    filed_at="2024-02-29T00:00:00Z",
                ),
                manager_headers,
            ),
            201,
        )
        # 2024-02-29 + 36 months: 2027 has no Feb 29, so the day clamps.
        assert str(dq_file["retention_until"]).startswith("2027-02-28")

        inspection_report = validate_success(
            api.create_document(
                create_document_payload(
                    carrier["id"], document_type="INSPECTION_REPORT",
                    filed_at="2024-02-29T00:00:00Z",
                ),
                manager_headers,
            ),
            201,
        )
        assert str(inspection_report["retention_until"]).startswith("2025-02-28")


class TestDocumentPurge:
    def test_purge_blocked_by_open_audit(self, api, manager_headers, admin_headers):
        """PRD §3.10: "Purge is additionally blocked while any audit case of the
        carrier is open — in `SCHEDULED`, `FIELD_WORK`, `FINDINGS_ISSUED`, or
        `CORRECTIVE_ACTION_PHASE` — surfacing as `ERR_AUDIT_HOLD_ACTIVE`."
        PRD §3.10: "Once the logical clock reaches a document's
        `retention_until` — equality is eligible — the next measurement cycle
        marks the document `PURGE_ELIGIBLE`."

        Design: Corner/validations/purge_blocked_by_open_audit
        """
        carrier = make_carrier(dot_number="DOT-2315")
        document = make_document(
            carrier["id"], document_type="INSPECTION_REPORT",
            filed_at="2025-06-01T00:00:00Z",
        )
        cycle = run_cycle(carrier["id"])
        assert cycle["documents_marked_purge_eligible"] == 1
        assert get_document(document["id"])["status"] == "PURGE_ELIGIBLE"

        make_audit_case(
            carrier["id"], audit_type="COMPLIANCE_REVIEW",
            scheduled_date="2026-09-01T00:00:00Z", field_work_duration_days=7,
        )
        resp = api.purge_document(document["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_AUDIT_HOLD_ACTIVE)
        assert get_document(document["id"])["status"] == "PURGE_ELIGIBLE"

    def test_purge_state_errors_and_terminal_lockdown(self, api, manager_headers):
        """PRD §3.10: "A `SafetyManager` may then purge it to terminal
        `PURGED`. Purging a document still `RETAINED` is rejected with
        `ERR_RETENTION_NOT_EXPIRED`, and purging one already `PURGED` with
        `ERR_DOCUMENT_ALREADY_PURGED`."

        Design: Corner/validations/purge_state_errors_and_terminal_lockdown
        """
        carrier = make_carrier(dot_number="DOT-2316")
        document = make_document(
            carrier["id"], document_type="INSPECTION_REPORT",
            filed_at="2025-06-01T00:00:00Z",
        )
        # Still RETAINED at the default clock until a cycle sweeps it.
        early = api.purge_document(document["id"], manager_headers)
        validate_error(early, ApiErrorId.ERR_RETENTION_NOT_EXPIRED)

        run_cycle(carrier["id"])
        purged = validate_success(api.purge_document(document["id"], manager_headers), 200)
        assert purged["status"] == "PURGED"

        again = api.purge_document(document["id"], manager_headers)
        validate_error(again, ApiErrorId.ERR_DOCUMENT_ALREADY_PURGED)


class TestRandomTestingQuotas:
    def test_random_quota_exact_multiple_no_roundup(self, api, manager_headers):
        """PRD §3.6: "The required counts are computed at creation:
        `required_drug_tests` is one quarter of `avg_driver_count` rounded up to
        a whole number, and `required_alcohol_tests` is one tenth of it rounded
        up the same way; exact multiples do not round up, so eight drivers
        require exactly two drug tests."

        Design: Difficulty/boundary_precision_check/random_quota_exact_multiple_no_roundup
        """
        carrier = make_carrier(dot_number="DOT-1012A", fleet_size=8)
        period = validate_success(
            api.create_period(
                create_period_payload(carrier["id"], program_year=2026, avg_driver_count=8),
                manager_headers,
            ),
            201,
        )
        assert period["required_drug_tests"] == 2, "ceil(8 x 0.25) = ceil(2.0) = 2"
        assert period["required_alcohol_tests"] == 1, "ceil(8 x 0.10) = ceil(0.8) = 1"

    def test_random_quota_fractional_product_rounds_up(self, api, manager_headers):
        """PRD §3.6: "`required_drug_tests` is one quarter of `avg_driver_count`
        rounded up to a whole number, and `required_alcohol_tests` is one tenth
        of it rounded up the same way" — a fractional product rounds up: nine
        drivers require three drug tests.

        Design: Difficulty/boundary_precision_check/random_quota_exact_multiple_no_roundup
        """
        carrier = make_carrier(dot_number="DOT-1012B", fleet_size=9)
        period = validate_success(
            api.create_period(
                create_period_payload(carrier["id"], program_year=2026, avg_driver_count=9),
                manager_headers,
            ),
            201,
        )
        assert period["required_drug_tests"] == 3, "ceil(9 x 0.25) = ceil(2.25) = 3"
        assert period["required_alcohol_tests"] == 1, "ceil(9 x 0.10) = ceil(0.9) = 1"


class TestPeriodClose:
    def test_period_close_before_year_end_rejected(self, api, manager_headers):
        """PRD §3.6: "A period in `OPEN` may be closed by a `SafetyManager` once
        the clock has reached midnight UTC on January 1 of the year following
        `program_year`; closing earlier is rejected with
        `ERR_PERIOD_NOT_ENDED`".

        Design: Corner/validations/period_close_before_year_end_rejected
        """
        carrier = make_carrier(dot_number="DOT-2334", fleet_size=4)
        period = make_period(carrier["id"], program_year=2026, avg_driver_count=4)

        resp = api.close_period(period["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_ENDED)
        assert get_period(period["id"])["status"] == "OPEN"

    def test_period_close_twice_terminal_lockdown(self, api, manager_headers):
        """PRD §3.6: "closing earlier is rejected with `ERR_PERIOD_NOT_ENDED`,
        and closing a period that is not `OPEN` is rejected with
        `ERR_PERIOD_NOT_OPEN`. The close verdict is automatic: when both
        completed counters meet or exceed their required counts — equality is
        compliant — the period closes `CLOSED_COMPLIANT`; any shortfall in
        either counter closes it `CLOSED_DEFICIENT`. Both closed states are
        terminal."

        Design: Corner/state_machines/period_close_twice_terminal_lockdown
        """
        carrier = make_carrier(dot_number="DOT-2340", fleet_size=4)
        period = make_period(carrier["id"], program_year=2025, avg_driver_count=4)
        # Default clock 2026-08-01 is past (2025+1)-01-01, so closing is allowed.
        closed = validate_success(api.close_period(period["id"], manager_headers), 200)
        assert closed["status"] == "CLOSED_DEFICIENT", "0 completed < 1 required drug"

        again = api.close_period(period["id"], manager_headers)
        validate_error(again, ApiErrorId.ERR_PERIOD_NOT_OPEN)

    def test_random_period_close_equality_compliant_and_deficient(
        self, api, manager_headers
    ):
        """PRD §3.6: "The close verdict is automatic: when both completed
        counters meet or exceed their required counts — equality is compliant —
        the period closes `CLOSED_COMPLIANT`; any shortfall in either counter
        closes it `CLOSED_DEFICIENT`."
        PRD §3.6: "The `completed_drug_tests` and `completed_alcohol_tests`
        counters are computed live on read rather than stored: each counts tests
        of the carrier's drivers whose `substance` matches the counter, whose
        `test_type` is `RANDOM`, whose status is `MRO_VERIFIED` with
        `mro_verdict` one of `VERIFIED_NEGATIVE`, `VERIFIED_POSITIVE`, or
        `VERIFIED_REFUSAL`, and whose `collected_at` falls within the program
        year".

        Design: Corner/calculations/random_period_close_equality_compliant_and_deficient
        """
        carrier_a = make_carrier(dot_number="DOT-2207A", fleet_size=8)
        carrier_b = make_carrier(dot_number="DOT-2207B", fleet_size=8)
        driver = make_driver(carrier_a["id"], hire_date="2024-01-01T00:00:00Z")
        period_a = make_period(carrier_a["id"], program_year=2026, avg_driver_count=8)
        period_b = make_period(carrier_b["id"], program_year=2026, avg_driver_count=8)

        # Exactly the required counts: 2 verified RANDOM/DRUG + 1 RANDOM/ALCOHOL.
        for substance, day in (("DRUG", "01"), ("DRUG", "02"), ("ALCOHOL", "03")):
            test = validate_success(
                api.create_test(
                    create_test_payload(
                        driver["id"], test_type="RANDOM", substance=substance,
                        collected_at=f"2026-03-{day}T00:00:00Z",
                    ),
                    make_manager_headers("sm-1"),
                ),
                201,
            )
            validate_success(
                api.report_lab_result(test["id"], {"lab_result": "NEGATIVE"}, manager_headers),
                200,
            )
            validate_success(
                api.verify_test(
                    test["id"], {"verdict": "VERIFIED_NEGATIVE"}, make_mro_headers("mro-1")
                ),
                200,
            )

        # Closing is allowed the instant the following year begins.
        set_clock("2027-01-01T00:00:00Z")
        before = get_period(period_a["id"])
        assert before["completed_drug_tests"] == 2
        assert before["completed_alcohol_tests"] == 1

        closed_a = validate_success(api.close_period(period_a["id"], manager_headers), 200)
        assert closed_a["status"] == "CLOSED_COMPLIANT", "2 >= 2 and 1 >= 1"

        closed_b = validate_success(api.close_period(period_b["id"], manager_headers), 200)
        assert closed_b["status"] == "CLOSED_DEFICIENT", "0 < 2"
