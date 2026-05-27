"""Corner (entities) — basic CRUD + system-minted field shapes."""
import re

import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_applicant,
    create_applicant_payload,
    set_clock,
    register_applicant,
    create_draft_case,
    publish_visa_bulletin,
    file_case,
    make_applicant_headers,
    RECEIPT_NUMBER_PATTERN,
    TEST_USERS,
)


_RECEIPT_RE = re.compile(RECEIPT_NUMBER_PATTERN)


class TestApplicantCrud:

    def test_create_applicant_returns_201_with_system_fields(self, api, anonymous_headers):
        """PRD §2.12: "Operations that create a brand-new resource (e.g., creating a draft
        case, scheduling a fresh biometrics appointment, issuing a new RFE,
        scheduling an interview, publishing a visa bulletin entry, registering
        an applicant or attorney) return `201 Created`."
        PRD §2.4: "`version` (integer): a monotonically increasing counter that starts at 1
        on creation and increments by exactly one on every mutation."

        Design: Corner/entities/create_applicant_minimal_required_fields_returns_201_with_system_fields
        """
        payload = create_applicant_payload(
            alien_number="A100100100",
            full_name="Alice A",
            date_of_birth="1990-04-15",
            country_of_chargeability="WORLDWIDE",
            email="alice-corner@example.com",
        )
        res = api.register_applicant(payload, anonymous_headers)
        body = validate_success(res, 201)
        assert_applicant(body)
        assert body["alien_number"] == "A100100100"
        assert body["full_name"] == "Alice A"
        assert body["version"] == 1

    def test_get_applicant_by_unknown_id_returns_not_found(self, api):
        """PRD §2.8: "the server validates them in left-to-right order and returns
        `ERR_NOT_FOUND` (HTTP 404) for the first identifier that does not resolve."

        Design: Corner/entities/get_applicant_by_unknown_id_returns_not_found
        """
        # Register one applicant so we have an authenticated identity for the call.
        applicant = register_applicant()
        headers = make_applicant_headers(applicant["id"])
        res = api.get_applicant("00000000-0000-0000-0000-000000000999", headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_create_applicant_missing_alien_number_returns_invalid_request(
        self, api, anonymous_headers
    ):
        """PRD §3.1: "An applicant is created via the self-registration endpoint, which
        accepts the applicant's `alien_number`, `full_name`, `date_of_birth`,
        `country_of_chargeability`, and `email`."
        PRD §2.11: "the request shape (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/create_applicant_missing_alien_number_invalid_request
        """
        payload = create_applicant_payload()
        del payload["alien_number"]
        res = api.register_applicant(payload, anonymous_headers)
        validate_error(res, "ERR_INVALID_REQUEST")


class TestCaseSystemFieldsAtFile:

    def test_filing_stamps_receipt_number_matching_prd_pattern(self, api):
        """PRD §2.6: "every minted `receipt_number` matches the regular expression
        `^(NBC|MSC|SRC|EAC|WAC|LIN|YSC|NSC|VSC|TSC)\\d{10}$`."
        PRD §3.2: "It stamps `file_date` to the calendar-date portion of `ClockState.current_utc`
        (the first ten characters of the ISO 8601 timestamp). It stamps `priority_date`
        equal to `file_date`"

        Design: Corner/entities/receipt_number_system_minted_matches_pattern
        """
        set_clock("2026-06-15T00:00:00Z")
        applicant = register_applicant()
        case = create_draft_case(applicant, case_type="I-130",
                                 preference_category="IR")
        filed = file_case(case, applicant)
        assert _RECEIPT_RE.match(filed["receipt_number"]), (
            f"receipt_number {filed['receipt_number']!r} must match the PRD §2.6 pattern"
        )
        assert filed["file_date"] == "2026-06-15"
        assert filed["priority_date"] == "2026-06-15"


class TestCaseTypeEnumConstraint:

    def test_invalid_case_type_enum_rejected(self, api):
        """PRD §3.1: "the `case_type` — one of `I-130`, `I-485`, `I-765`, or `I-131`"
        PRD §2.11: "the request shape (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/invalid_case_type_enum_rejected
        """
        applicant = register_applicant()
        headers = make_applicant_headers(applicant["id"])
        res = api.create_case({
            "applicant_id": applicant["id"],
            "case_type": "I-999",
        }, headers)
        validate_error(res, "ERR_INVALID_REQUEST")


class TestVisaBulletinPagination:

    def test_visa_bulletin_listing_supports_limit_and_offset(self, api):
        """PRD §2.3: "List endpoints accept two query parameters. The `limit` parameter caps
        the number of items returned: it defaults to 10, with a minimum of 1 and
        a maximum of 100. The `offset` parameter is the number of leading items
        to skip and defaults to 0."
        PRD §2.3: "The `meta` envelope of every list response carries the resolved `limit`
        and `offset` values, the `total_count` of items matching the filter, and
        the `has_more` boolean."

        Design: Corner/entities/list_visa_bulletin_supports_pagination
        """
        set_clock("2026-06-15T00:00:00Z")
        admin = TEST_USERS["field_office_admin_headers"]
        publish_visa_bulletin("2026-06", "F1", "WORLDWIDE",
                              "FINAL_ACTION", "2024-01-01")
        publish_visa_bulletin("2026-06", "F2A", "WORLDWIDE",
                              "FINAL_ACTION", "2024-02-01")

        res = api.list_visa_bulletin(admin, params={"bulletin_month": "2026-06",
                                                     "limit": 1, "offset": 0})
        data, meta = validate_paginated(res)
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert len(data) == 1
