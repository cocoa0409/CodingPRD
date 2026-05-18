"""Case creation, draft state, and filing transition — PRD §3.2 / §3.3.

Coverage:
- Case is born in DRAFT with default null fields.
- Body FK existence: petitioner_id, beneficiary_id, linked_i130_case_id.
- DRAFT -> FILED transition mints receipt_number and pins filing_date.
- I-485 filing requires APPROVED I-130 unless beneficiary is IR
  (ERR_I485_MISSING_APPROVED_I130).
- Receipt number is exactly 13 chars with the prefix from
  CaseTypeConfig.
- I-130 filing pins priority_date = today (UTC date portion).
- I-485 filing inherits the linked I-130's priority_date.
- I-765 / I-131 filings leave priority_date null.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    RECEIPT_NUMBER_LENGTH,
    TEST_DEFAULTS,
    advance_clock_to,
    api_client,
    assert_case,
    assert_receipt_number_format,
    create_case,
    create_case_payload,
    create_petitioner,
    file_case,
    iso_instant_utc,
    make_petitioner_headers,
    parse_iso,
    seed_all_case_type_configs,
    setup_filed_case,
    setup_petitioner_and_beneficiary,
    validate_error,
    validate_success,
)


# ===========================================================================
# Case creation — DRAFT initial state
# ===========================================================================
class TestCaseCreate:

    def test_create_case_born_in_draft(self, api, officer_headers):
        """PRD §3.2: "The new case is born in DRAFT status, with
        priority_date null, priority_date_status set to NOT_APPLICABLE,
        rfe_deadline null, decision_at null, and denial_reason null."

        Claim: a freshly created case has status=DRAFT, priority_date
        null, priority_date_status=NOT_APPLICABLE, rfe_deadline null,
        decision_at null, denial_reason null.
        """
        seed_all_case_type_configs()
        p, b = setup_petitioner_and_beneficiary()
        payload = create_case_payload(
            petitioner_id=p["id"], beneficiary_id=b["id"],
            case_type="I-130",
        )
        resp = api_client.create_case(payload, officer_headers)
        data = validate_success(resp, expected_status=201)
        assert_case(data)
        assert data["status"] == "DRAFT"
        assert data.get("priority_date") is None
        assert data["priority_date_status"] == "NOT_APPLICABLE"
        assert data.get("rfe_deadline") is None
        assert data.get("decision_at") is None
        assert data.get("denial_reason") is None

    def test_referenced_petitioner_must_exist(
        self, api, officer_headers,
    ):
        """PRD §3.2: "If any of the body-referenced foreign keys
        (petitioner_id, beneficiary_id, linked_i130_case_id) cannot be
        resolved at creation time, the request is rejected with
        ERR_REFERENCED_RESOURCE_NOT_FOUND."

        Claim: unknown petitioner_id in body ->
        ERR_REFERENCED_RESOURCE_NOT_FOUND.
        """
        seed_all_case_type_configs()
        _, b = setup_petitioner_and_beneficiary()
        payload = create_case_payload(
            petitioner_id=NON_EXISTENT_UUID,
            beneficiary_id=b["id"],
            case_type="I-130",
        )
        resp = api_client.create_case(payload, officer_headers)
        validate_error(
            resp, ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND.value,
        )

    def test_referenced_beneficiary_must_exist(
        self, api, officer_headers,
    ):
        """PRD §3.2: "If any of the body-referenced foreign keys
        (petitioner_id, beneficiary_id, linked_i130_case_id) cannot be
        resolved at creation time, the request is rejected with
        ERR_REFERENCED_RESOURCE_NOT_FOUND."

        Claim: unknown beneficiary_id in body ->
        ERR_REFERENCED_RESOURCE_NOT_FOUND.
        """
        seed_all_case_type_configs()
        p = create_petitioner()
        payload = create_case_payload(
            petitioner_id=p["id"],
            beneficiary_id=NON_EXISTENT_UUID,
            case_type="I-130",
        )
        resp = api_client.create_case(payload, officer_headers)
        validate_error(
            resp, ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND.value,
        )

    def test_invalid_case_type_rejected(self, api, officer_headers):
        """PRD §3.2: "case_type chosen from I-130, I-485, I-765, or
        I-131".

        Claim: unknown case_type -> ERR_VALIDATION.
        """
        seed_all_case_type_configs()
        p, b = setup_petitioner_and_beneficiary()
        payload = create_case_payload(
            petitioner_id=p["id"], beneficiary_id=b["id"],
            case_type="I-999",
        )
        resp = api_client.create_case(payload, officer_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Filing — DRAFT -> FILED
# ===========================================================================
class TestCaseFiling:

    def test_i130_file_transitions_to_filed(self, api):
        """PRD §3.2: "Filing pins the filing_date to the current UTC
        instant, mints the receipt_number according to the
        deterministic 13-character algorithm in §2.7 ... and pins
        priority_date according to case type: an I-130 filing sets
        priority_date to today's UTC date (the date portion of
        filing_date)".

        Claim: filing an I-130 yields status=FILED with non-null
        receipt_number, filing_date, and priority_date.
        """
        bundle = setup_filed_case(case_type="I-130")
        case = bundle["case"]
        assert case["status"] == "FILED"
        assert case.get("receipt_number") is not None
        assert case.get("filing_date") is not None
        assert case.get("priority_date") is not None
        # PRD: priority_date is the date portion of filing_date.
        assert case["priority_date"] == case["filing_date"][:10], (
            f"I-130 priority_date should equal date portion of "
            f"filing_date; got priority_date={case['priority_date']!r} "
            f"filing_date={case['filing_date']!r}"
        )

    def test_receipt_number_length_and_prefix(self, api):
        """PRD §2.7: "Receipt Numbers are exactly 13 characters long".
        PRD §2.7: "first, the three-letter prefix is read from the
        matching CaseTypeConfig.receipt_prefix".

        Claim: minted receipt_number has the CaseTypeConfig prefix and
        13 chars total.
        """
        bundle = setup_filed_case(case_type="I-130", receipt_prefix="MSC")
        rn = bundle["case"]["receipt_number"]
        assert len(rn) == RECEIPT_NUMBER_LENGTH
        assert_receipt_number_format(rn, expected_prefix="MSC")

    def test_i485_file_inherits_priority_date_from_linked_i130(self, api):
        """PRD §3.2: "an I-485 filing whose linked_i130_case_id is set
        copies that linked I-130's priority_date onto this case".

        Claim: I-485 filed with linked APPROVED I-130 inherits the
        I-130's priority_date.
        """
        bundle = setup_filed_case(
            case_type="I-485", preference_category="F2A",
        )
        i130 = bundle["i130"]
        i485 = bundle["case"]
        assert i485["priority_date"] == i130["priority_date"], (
            f"I-485 priority_date should inherit from I-130; got "
            f"i485={i485['priority_date']!r} i130={i130['priority_date']!r}"
        )

    @pytest.mark.parametrize("case_type", ["I-765", "I-131"])
    def test_i765_i131_filing_leaves_priority_date_null(
        self, api, case_type,
    ):
        """PRD §3.2: "I-765 and I-131 filings leave priority_date null."

        Claim: an I-765 or I-131 filing has priority_date == null.
        """
        bundle = setup_filed_case(case_type=case_type)
        case = bundle["case"]
        assert case["status"] == "FILED"
        assert case.get("priority_date") is None, (
            f"{case_type} filing should leave priority_date null; got "
            f"{case.get('priority_date')!r}"
        )

    def test_i485_filing_without_approved_i130_rejected(self, api):
        """PRD §3.2: "For an I-485 filing where the beneficiary's
        preference_category is anything other than IR, the case's
        linked_i130_case_id must point to an existing I-130 whose own
        status is APPROVED; otherwise the filing is rejected with
        ERR_I485_MISSING_APPROVED_I130."

        Claim: filing an I-485 (non-IR) with no linked I-130 ->
        ERR_I485_MISSING_APPROVED_I130.
        """
        seed_all_case_type_configs()
        p, b = setup_petitioner_and_beneficiary(
            preference_category="F2A",
        )
        case = create_case(p, b, case_type="I-485")
        resp = api_client.file_case(
            case["id"], make_petitioner_headers(p["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_I485_MISSING_APPROVED_I130.value,
        )

    def test_i485_filing_with_unapproved_i130_rejected(self, api):
        """PRD §3.2: "the case's linked_i130_case_id must point to an
        existing I-130 whose own status is APPROVED; otherwise the
        filing is rejected with ERR_I485_MISSING_APPROVED_I130."

        Claim: filing an I-485 linked to a FILED-but-not-APPROVED I-130
        -> ERR_I485_MISSING_APPROVED_I130.
        """
        seed_all_case_type_configs()
        p, b = setup_petitioner_and_beneficiary(
            preference_category="F2A",
        )
        # I-130 is FILED but not approved.
        i130 = create_case(p, b, case_type="I-130")
        i130 = file_case(i130, p)
        assert i130["status"] == "FILED"
        i485 = create_case(
            p, b, case_type="I-485", linked_i130_case_id=i130["id"],
        )
        resp = api_client.file_case(
            i485["id"], make_petitioner_headers(p["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_I485_MISSING_APPROVED_I130.value,
        )

    def test_double_file_rejected_invalid_state(self, api):
        """PRD §2.4: "State precondition — the target resource must be
        in a state from which the requested transition is permitted,
        otherwise ERR_INVALID_STATE is returned."

        Claim: filing an already-FILED case -> ERR_INVALID_STATE.
        """
        bundle = setup_filed_case(case_type="I-130")
        p = bundle["petitioner"]
        case = bundle["case"]
        # Second file attempt on an already-FILED case.
        resp = api_client.file_case(
            case["id"], make_petitioner_headers(p["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_petitioner_cannot_file_other_petitioners_case(self, api):
        """PRD §2.1: "Petitioners may read and act only on cases whose
        petitioner_id matches their own X-User-ID."

        Claim: a Petitioner attempting to file another petitioner's
        case -> ERR_FORBIDDEN.
        """
        seed_all_case_type_configs()
        p_a, b_a = setup_petitioner_and_beneficiary()
        p_b = create_petitioner()
        case_a = create_case(p_a, b_a, case_type="I-130")
        # Act as petitioner B trying to file petitioner A's case.
        resp = api_client.file_case(
            case_a["id"], make_petitioner_headers(p_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
