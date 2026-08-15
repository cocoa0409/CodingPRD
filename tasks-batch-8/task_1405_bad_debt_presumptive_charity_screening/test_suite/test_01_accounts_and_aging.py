"""Self-pay account registration, retrieval, listing, envelope, auth context,
and aging-bucket boundary derivation."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_account_invariants,
    assert_self_pay_account,
    create_account,
    create_account_payload,
    post_recovery,
    read_account,
    validate_error,
    validate_paginated,
    validate_success,
)

COLLECTOR = TEST_USERS["collector_headers"]


class TestAccountCreation:
    def test_account_creation_initializes_computed_fields(self, api):
        """PRD §3.1: "On creation the account's `current_balance_cents` is
        initialized to the full `original_balance_cents`, its `status` begins at
        `OPEN`, its `credit_reporting_status` begins at `NOT_REPORTED`, and all
        running totals start at zero."
        PRD §3.1: "Fewer than 30 days outstanding places the account in
        `CURRENT`"

        Design: Corner/entities/account_creation_sets_computed_defaults
        """
        resp = api.create_account(create_account_payload(
            patient_mrn="MRN-K1", patient_name="K1",
            original_balance_cents=50000, guarantor_liability_date="2026-07-15",
        ), COLLECTOR)
        account = validate_success(resp, 201)
        assert_self_pay_account(account)
        assert account["current_balance_cents"] == 50000
        assert account["status"] == "OPEN"
        assert account["statements_sent_count"] == 0
        assert account["charity_writeoff_total_cents"] == 0
        assert account["bad_debt_writeoff_total_cents"] == 0
        assert account["recovery_total_cents"] == 0
        assert account["credit_reporting_status"] == "NOT_REPORTED"
        # 2026-07-15 -> 2026-08-01 boot clock is 17 days outstanding.
        assert account["aging_bucket"] == "CURRENT"
        assert_account_invariants(account)

    @pytest.mark.parametrize("missing_field", [
        "patient_mrn", "patient_name", "original_balance_cents",
        "guarantor_liability_date",
    ])
    def test_account_creation_missing_required_field(self, api, missing_field):
        """PRD §2.9: "Required fields must be present, types correct, enum
        values within their declared sets, and numeric ranges honored (for
        example `amount_cents` greater than zero, or `installment_count` within
        its allowed range), else `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/account_creation_missing_required_field_returns_invalid_request
        """
        payload = create_account_payload(
            patient_mrn="MRN-K1B", patient_name="NoField",
            original_balance_cents=50000, guarantor_liability_date="2026-07-15",
        )
        del payload[missing_field]
        resp = api.create_account(payload, COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_account_retrieval_returns_persisted_input_fields(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/entities/account_retrieval_by_id_returns_persisted_fields
        """
        created = create_account(
            balance_cents=75000, guarantor_liability_date="2026-06-01",
            patient_mrn="MRN-K2", patient_name="K2 Name")
        fetched = validate_success(api.get_account(created["id"], COLLECTOR), 200)
        assert_self_pay_account(fetched)
        assert fetched["id"] == created["id"]
        assert fetched["patient_mrn"] == "MRN-K2"
        assert fetched["patient_name"] == "K2 Name"
        assert fetched["original_balance_cents"] == 75000

    def test_get_account_not_found(self, api):
        """PRD §2.9: "Any unresolved reference yields `ERR_NOT_FOUND` (HTTP
        404); the specific missing resource is identified in the human-readable
        `message`."

        Design: Corner/entities/account_not_found_returns_404
        """
        resp = api.get_account(NON_EXISTENT_UUID, COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAccountListing:
    def test_list_accounts_envelope_and_pagination(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.3: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/list_accounts_pagination_envelope
        """
        for mrn in ("MRN-P1", "MRN-P2", "MRN-P3"):
            create_account(balance_cents=10000,
                           guarantor_liability_date="2026-07-01",
                           patient_mrn=mrn, patient_name=mrn)

        resp = api.list_accounts(COLLECTOR)
        data, meta = validate_paginated(resp)
        body = resp.json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        assert len(data) == 3
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta

    def test_list_accounts_filter_by_status(self, api):
        """PRD §3.1: "The account list endpoint can be filtered by `status`,
        `aging_bucket`, and `credit_reporting_status`, in addition to the
        standard `limit` and `offset` pagination parameters."

        Design: Corner/endpoints/list_accounts_filter_by_status
        """
        open_acct = create_account(
            balance_cents=50000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-P-OPEN", patient_name="P Open")
        closed_acct = create_account(
            balance_cents=20000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-P-CLOSED", patient_name="P Closed")
        post_recovery(closed_acct["id"], payment_kind="LUMP_SUM", amount_cents=20000)
        assert read_account(closed_acct["id"])["status"] == "CLOSED_PAID"

        data, meta = validate_paginated(
            api.list_accounts(COLLECTOR, params={"status": "OPEN"}))
        ids = [a["id"] for a in data]
        assert all(a["status"] == "OPEN" for a in data)
        assert open_acct["id"] in ids
        assert closed_acct["id"] not in ids


class TestAuthContext:
    def test_missing_user_context_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed
        header, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/errors/missing_user_context_header
        """
        resp = api.list_accounts({})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestAgingBucketBoundaries:
    def test_aging_bucket_day30_and_day120_inclusive(self, api):
        """PRD §3.1: "Boundaries include their lower edge: day 30 is already
        `BUCKET_30`, day 60 is `BUCKET_60`, day 90 is `BUCKET_90`, and day 120
        is `BUCKET_120_PLUS`."

        At the boot clock 2026-08-01: liability date 2026-07-02 is exactly 30
        days outstanding; 2026-04-03 is exactly 120 days outstanding.

        Design: Difficulty/combinatorial_formula/aging_bucket_derivation_uses_inclusive_lower_bound
        """
        acct_30 = create_account(
            balance_cents=100000, guarantor_liability_date="2026-07-02",
            patient_mrn="MRN-C2", patient_name="C2")
        acct_120 = create_account(
            balance_cents=100000, guarantor_liability_date="2026-04-03",
            patient_mrn="MRN-C3", patient_name="C3")
        assert read_account(acct_30["id"])["aging_bucket"] == "BUCKET_30"
        assert read_account(acct_120["id"])["aging_bucket"] == "BUCKET_120_PLUS"

    @pytest.mark.parametrize("liability_date,days,expected_bucket", [
        ("2026-07-03", 29, "CURRENT"),
        ("2026-06-02", 60, "BUCKET_60"),
        ("2026-05-03", 90, "BUCKET_90"),
        ("2026-04-04", 119, "BUCKET_90"),
    ])
    def test_aging_bucket_remaining_boundaries(self, api, liability_date, days,
                                               expected_bucket):
        """PRD §3.1: "Fewer than 30 days outstanding places the account in
        `CURRENT`; at least 30 but fewer than 60 in `BUCKET_30`; at least 60 but
        fewer than 90 in `BUCKET_60`; at least 90 but fewer than 120 in
        `BUCKET_90`; and 120 days or more in `BUCKET_120_PLUS`."

        Each liability date is the stated number of whole days before the boot
        clock 2026-08-01.

        Design: Difficulty/combinatorial_formula/aging_bucket_derivation_uses_inclusive_lower_bound
        """
        account = create_account(
            balance_cents=100000, guarantor_liability_date=liability_date,
            patient_mrn=f"MRN-AGE-{days}", patient_name=f"Age {days}")
        fetched = read_account(account["id"])
        assert fetched["aging_bucket"] == expected_bucket, (
            f"{days} days outstanding should be {expected_bucket}, "
            f"got {fetched['aging_bucket']}")
