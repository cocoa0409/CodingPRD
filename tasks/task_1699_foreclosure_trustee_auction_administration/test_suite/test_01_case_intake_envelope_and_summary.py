"""Referral intake, request-schema rules, pagination envelope, and summary read."""
from test_helpers import (
    CM,
    ApiErrorId,
    assert_date_equals,
    create_beneficiary,
    create_case,
    create_case_payload,
    setup_case_with_nod,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCaseIntakeSchema:
    def test_case_create_missing_required_field_returns_400(self, api):
        """PRD §2.8: "Request-body schema and clock consistency — required fields present, no unknown fields, valid enum values, positive integer cents where required, well-formed datetimes, uniqueness of `loan_reference` and `reference_code`, and the clock-consistency rules of Section 2.5 (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/case_create_missing_required_field_returns_400
        """
        ben = create_beneficiary("BEN-T2")
        payload = create_case_payload(ben["id"], loan_reference="LN-T2")
        del payload["unpaid_principal_balance_cents"]
        resp = api.create_case(payload, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_case_create_invalid_enum_returns_400(self, api):
        """PRD §3.1: "`distribution_method`, which selects the surplus waterfall variant — `STATUTORY_PRIORITY` or `PRO_RATA` — and is immutable once the case is created."
        PRD §2.8: "Request-body schema and clock consistency — required fields present, no unknown fields, valid enum values, positive integer cents where required, well-formed datetimes, uniqueness of `loan_reference` and `reference_code`, and the clock-consistency rules of Section 2.5 (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/case_create_invalid_enum_returns_400
        """
        ben = create_beneficiary("BEN-T3")
        resp = api.create_case(
            create_case_payload(
                ben["id"], loan_reference="LN-T3", distribution_method="WEEKLY"
            ),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_case_create_duplicate_loan_reference_rejected(self, api):
        """PRD §3.1: "The intake payload identifies the owning beneficiary through `beneficiary_id` and captures the loan as referred: `loan_reference` (unique across all cases), `borrower_name`, `property_address`, and `county_code` for the recording jurisdiction."
        PRD §2.8: "Request-body schema and clock consistency — required fields present, no unknown fields, valid enum values, positive integer cents where required, well-formed datetimes, uniqueness of `loan_reference` and `reference_code`, and the clock-consistency rules of Section 2.5 (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/case_create_duplicate_loan_reference_rejected
        """
        ben = create_beneficiary("BEN-T4")
        create_case(ben["id"], loan_reference="LN-T4")
        resp = api.create_case(
            create_case_payload(
                ben["id"],
                loan_reference="LN-T4",
                borrower_name="Borrower T4b",
                distribution_method="PRO_RATA",
            ),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_unknown_input_field_rejected(self, api):
        """PRD §2.4: "The `id` is a server-minted UUID with no type prefix."
        PRD §2.8: "Request-body schema and clock consistency — required fields present, no unknown fields, valid enum values, positive integer cents where required, well-formed datetimes, uniqueness of `loan_reference` and `reference_code`, and the clock-consistency rules of Section 2.5 (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/unknown_input_field_rejected
        """
        ben = create_beneficiary("BEN-T9")
        payload = create_case_payload(ben["id"], loan_reference="LN-T9")
        payload["id"] = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
        resp = api.create_case(payload, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestCaseReadAndListing:
    def test_get_case_not_found_returns_404(self, api):
        """PRD §2.9: "A path naming a case and then a child collection, or a child resource and then its own child, first confirms the leftmost identifier and proceeds rightward only while each identifier resolves; the first identifier that does not resolve aborts the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404), and no business validation runs against a resource whose ancestor did not resolve."

        Design: Corner/entities/get_case_not_found_returns_404
        """
        resp = api.get_case("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", CM)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND, 404)

    def test_case_list_pagination_envelope(self, api):
        """PRD §2.3: "List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD §3.1: "Cases may be listed with optional `beneficiary_id` and `lifecycle_status` filters plus the standard pagination parameters."

        Design: Corner/entities/case_list_pagination_envelope
        """
        ben = create_beneficiary("BEN-T7")
        create_case(ben["id"], loan_reference="LN-T7A")
        create_case(
            ben["id"], loan_reference="LN-T7B", distribution_method="PRO_RATA"
        )

        page1, meta1 = validate_paginated(
            api.list_cases(CM, params={"beneficiary_id": ben["id"],
                                       "limit": 1, "offset": 0})
        )
        page2, meta2 = validate_paginated(
            api.list_cases(CM, params={"beneficiary_id": ben["id"],
                                       "limit": 1, "offset": 1})
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"], (
            "the two pages must window distinct cases"
        )


class TestCaseSummary:
    def test_summary_computed_read(self, api):
        """PRD §3.1: "A computed summary read of a case returns its current posture and statutory aggregates: `lifecycle_status`, `hold_status`, `active_stay_count`, `reinstatement_deadline_date`, `reinstatement_cutoff_date`, `claims_deadline_date`, `undistributed_surplus_cents`, and `total_approved_costs_cents` (the sum of `amount_cents` over the case's `APPROVED` cost advances)."
        PRD §3.2: "On success the system creates a `NoticeOfDefault` in `RECORDED` status with `rescinded_at` still null, advances the case to `NOD_RECORDED`, sets the case's `reinstatement_deadline_date` to ninety days after the recording date, and increments the case's `version`."

        Design: Corner/entities/summary_computed_read
        """
        ctx = setup_case_with_nod("BEN-T8", loan_reference="LN-T8")
        data = validate_success(api.get_case_summary(ctx["case"]["id"], CM), 200)
        assert data["hold_status"] == "CLEAR"
        assert data["active_stay_count"] == 0
        assert data["lifecycle_status"] == "NOD_RECORDED"
        assert_date_equals(
            data["reinstatement_deadline_date"], "2026-10-30",
            label="reinstatement_deadline_date",
        )
