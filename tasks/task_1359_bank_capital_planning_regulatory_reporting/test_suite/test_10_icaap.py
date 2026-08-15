"""ICAAP documents: governing-plan finality gate, section completeness,
segregation of duties, and the full attest-then-file lifecycle."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_bank,
    create_period,
    create_icaap_document_payload,
    setup_plan_approved,
    setup_plan_submitted,
    set_clock,
    make_capital_analyst_headers,
    make_board_approver_headers,
)


def _create_icaap(api, analyst_headers, bank_id, plan_id, **overrides):
    return validate_success(
        api.create_icaap_document(
            bank_id, create_icaap_document_payload(plan_id, **overrides), analyst_headers
        ),
        201,  # PRD §4: creation operations return 201 Created
    )


class TestIcaapPlanFinality(object):
    def test_icaap_submit_depends_on_plan_final_submitted_plan_rejected(
        self, api, system_operator_headers, capital_analyst_headers
    ):
        """PRD §3.8: "Submission for review also requires the governing plan
        to have reached APPROVED or EFFECTIVE; otherwise the rejection is
        ERR_PLAN_NOT_FINAL (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/icaap_submit_depends_on_plan_effective
        """
        bank, period, report, scenario, plan = setup_plan_submitted(
            "CH-XD2-001", 10_000_000_000, 100_000_000_000, scenario_code="BASE-XD2"
        )
        assert plan["status"] == "SUBMITTED"
        doc = _create_icaap(api, capital_analyst_headers, bank["id"], plan["id"], document_year=2027)
        res = api.submit_icaap_review(bank["id"], doc["id"], capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_FINAL)
        doc_now = validate_success(api.get_icaap_document(bank["id"], doc["id"], capital_analyst_headers))
        assert doc_now["status"] == "DRAFT"

    def test_icaap_submit_review_succeeds_when_plan_approved(self, api, system_operator_headers,
                                                             capital_analyst_headers):
        """PRD §3.8: "Submission for review also requires the governing plan
        to have reached APPROVED or EFFECTIVE" and "A clean submission moves
        the document DRAFT → REVIEW."

        Design: Difficulty/cross_entity_state_dependency/icaap_submit_depends_on_plan_effective
        """
        bank, period, report, scenario, plan = setup_plan_approved(
            "CH-XD2-002", 10_000_000_000, 100_000_000_000, scenario_code="BASE-XD2B"
        )
        assert plan["status"] == "APPROVED"
        doc = _create_icaap(api, capital_analyst_headers, bank["id"], plan["id"], document_year=2027)
        reviewed = validate_success(api.submit_icaap_review(bank["id"], doc["id"], capital_analyst_headers))
        assert reviewed["status"] == "REVIEW"


class TestIcaapSectionCompleteness(object):
    def test_icaap_missing_section_rejected(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.8: "Five sections are required — GOVERNANCE, RISK_APPETITE,
        CAPITAL_ADEQUACY, STRESS_TESTING, and DISTRIBUTION_POLICY — and
        submitting the document for review checks them all: a missing section
        is rejected with ERR_SECTION_MISSING (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/icaap_submit_depends_on_plan_effective
        """
        bank, period, report, scenario, plan = setup_plan_approved(
            "CH-XD2-003", 10_000_000_000, 100_000_000_000, scenario_code="BASE-XD2C"
        )
        doc = _create_icaap(
            api, capital_analyst_headers, bank["id"], plan["id"], document_year=2027,
            sections=[
                {"section_code": "GOVERNANCE", "content": "x"},
                {"section_code": "RISK_APPETITE", "content": "x"},
                {"section_code": "CAPITAL_ADEQUACY", "content": "x"},
                {"section_code": "STRESS_TESTING", "content": "x"},
            ],
        )
        res = api.submit_icaap_review(bank["id"], doc["id"], capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_SECTION_MISSING)


class TestIcaapLifecycle(object):
    def test_attest_is_segregation_of_duties_checkpoint(self, api, system_operator_headers,
                                                        capital_analyst_headers):
        """PRD §3.8: "A BoardApprover attests a document in REVIEW, and the
        attester's X-User-ID must differ from the document's
        prepared_by_user_id, failing which the attestation is rejected with
        ERR_SEGREGATION_OF_DUTIES_VIOLATION."

        Design: Difficulty/cross_entity_state_dependency/icaap_submit_depends_on_plan_effective
        """
        bank, period, report, scenario, plan = setup_plan_approved(
            "CH-ICA-001", 10_000_000_000, 100_000_000_000, scenario_code="BASE-ICA"
        )
        preparer = make_capital_analyst_headers("analyst-icaap-prep-1")
        doc = _create_icaap(api, preparer, bank["id"], plan["id"], document_year=2027)
        validate_success(api.submit_icaap_review(bank["id"], doc["id"], preparer))
        # The attester id collides with the preparer id.
        res = api.attest_icaap(bank["id"], doc["id"], make_board_approver_headers("analyst-icaap-prep-1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

    def test_full_lifecycle_attest_then_file_when_plan_effective(self, api, system_operator_headers,
                                                                 capital_analyst_headers):
        """PRD §3.8: "The governing plan must be EFFECTIVE at filing time —
        an APPROVED-but-not-yet-effective plan is no longer sufficient" and
        "A successful filing moves the document ATTESTED → FILED"

        Design: Difficulty/cross_entity_state_dependency/icaap_submit_depends_on_plan_effective
        """
        bank, period, report, scenario, plan = setup_plan_approved(
            "CH-ICA-002", 10_000_000_000, 100_000_000_000, scenario_code="BASE-ICA2"
        )
        # Filing while the plan is APPROVED (not yet EFFECTIVE) is refused;
        # walk the document to ATTESTED first.
        preparer = make_capital_analyst_headers("analyst-icaap-prep-2")
        doc = _create_icaap(api, preparer, bank["id"], plan["id"], document_year=2027)
        validate_success(api.submit_icaap_review(bank["id"], doc["id"], preparer))
        attested = validate_success(
            api.attest_icaap(bank["id"], doc["id"], make_board_approver_headers("board-1"))
        )
        assert attested["status"] == "ATTESTED"
        bank_now = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        premature = api.file_icaap(
            bank["id"], doc["id"], {"expected_bank_version": bank_now["version"]}, preparer
        )
        validate_error(premature, ApiErrorId.ERR_PLAN_NOT_FINAL)
        # Cross into the plan year: the plan auto-activates to EFFECTIVE.
        set_clock("2027-01-01T00:00:01Z")
        plan_now = validate_success(api.get_capital_plan(bank["id"], plan["id"], capital_analyst_headers))
        assert plan_now["status"] == "EFFECTIVE"
        bank_now = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        filed = validate_success(
            api.file_icaap(
                bank["id"], doc["id"], {"expected_bank_version": bank_now["version"]}, preparer
            )
        )
        assert filed["status"] == "FILED"
