"""Validation rules: shape, FK resolution, business constraints (PRD §2.10, §3)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_ctr_in_draft,
    create_filed_ctr,
    get_single_ctr_for_customer,
    get_success_data,
    make_admin_headers,
    make_analyst_headers,
    make_examiner_headers,
    make_officer_headers,
    make_teller_headers,
    post_cash_txn,
    post_instrument_sale,
    request_exemption,
    set_clock,
    setup_branch_and_customer,
    api_client,
    validate_error,
    validate_success,
)


class TestShapeValidation:
    def test_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.10 step 3: "Request shape: the body is a JSON object, all
        required input fields are present, types and enum values are valid ...
        any failure yields `ERR_INVALID_REQUEST`."

        Design: Corner/validations/missing_required_field_returns_invalid_request
        """
        branch, customer = setup_branch_and_customer()
        resp = api_client.create_cash_transaction(
            {
                "customer_id": customer["id"], "branch_id": branch["id"],
                "direction": "CASH_IN", "occurred_at": "2026-08-01T08:00:00Z",
            },
            headers=make_teller_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_invalid_request_shape_variants(self, api):
        """PRD §2.10 step 3: "Request shape: the body is a JSON object, all
        required input fields are present, types and enum values are valid, an
        examination scope satisfies `scope_start_date` strictly earlier than
        `scope_end_date`, and a manually opened alert window has its start on or
        before its end with a span of at most 31 days—any failure yields
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/invalid_request_shape_variants
        """
        branch, customer = setup_branch_and_customer()
        r1 = api_client.create_cash_transaction(
            {
                "customer_id": customer["id"], "branch_id": branch["id"],
                "direction": "SIDEWAYS", "amount_cents": 100,
                "occurred_at": "2026-08-01T08:00:00Z",
            },
            headers=make_teller_headers(),
        )
        validate_error(r1, ApiErrorId.ERR_INVALID_REQUEST)
        r2 = api_client.create_exemption_designation(
            customer["id"], {"phase": "PHASE_III"}, headers=make_officer_headers("officer-a"),
        )
        validate_error(r2, ApiErrorId.ERR_INVALID_REQUEST)
        r3 = api_client.create_structuring_alert(
            {
                "customer_id": customer["id"],
                "window_start_date": "2026-01-01",
                "window_end_date": "2026-03-01",
                "note": "too wide",
            },
            headers=make_officer_headers("officer-a"),
        )
        validate_error(r3, ApiErrorId.ERR_INVALID_REQUEST)
        r4 = api_client.create_examination_case(
            {
                "regulator": "FDIC", "case_number": "CASE-400",
                "scope_start_date": "2025-06-30", "scope_end_date": "2025-01-01",
            },
            headers=make_examiner_headers(),
        )
        validate_error(r4, ApiErrorId.ERR_INVALID_REQUEST)


class TestTemporalValidation:
    def test_occurred_at_in_future_rejected(self, api):
        """PRD §3.2: "`occurred_at` must not be later than the current logical
        clock, otherwise the posting is rejected with
        `ERR_OCCURRED_AT_IN_FUTURE`."

        Design: Corner/validations/occurred_at_in_future_rejected
        """
        branch, customer = setup_branch_and_customer()  # clock 2026-08-01T09:00:00Z
        resp = api_client.create_cash_transaction(
            {
                "customer_id": customer["id"], "branch_id": branch["id"],
                "direction": "CASH_IN", "amount_cents": 100,
                "occurred_at": "2026-08-01T10:00:00Z",
            },
            headers=make_teller_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_OCCURRED_AT_IN_FUTURE)
        # occurred_at == clock is allowed
        ok = post_cash_txn(customer["id"], branch["id"], amount_cents=100,
                           occurred_at="2026-08-01T09:00:00Z")
        assert ok["id"]

    def test_void_window_expired_after_business_date_rolls(self, api):
        """PRD §3.2: "Voiding is a same-day correction mechanism only: the
        transaction's `business_date` must equal the current logical clock date,
        otherwise the request is rejected with `ERR_VOID_WINDOW_EXPIRED`."

        Design: Corner/validations/void_window_expired_after_business_date_rolls
        """
        branch, customer = setup_branch_and_customer()
        txn = post_cash_txn(customer["id"], branch["id"], amount_cents=500_000,
                            occurred_at="2026-08-01T08:00:00Z")
        set_clock("2026-08-02T00:00:00Z")
        resp = api_client.void_cash_transaction(
            txn["id"], {"void_reason": "too late"}, headers=make_teller_headers("teller-1"),
        )
        validate_error(resp, ApiErrorId.ERR_VOID_WINDOW_EXPIRED)
        after = get_success_data(api_client.get_cash_transaction(
            txn["id"], headers=make_teller_headers(),
        ))
        assert after["status"] == "POSTED"

    def test_amendment_window_expired_for_filed_ctr(self, api):
        """PRD §3.5: "Amendment is permitted only from `FILED`, `ACKNOWLEDGED`,
        or `AMENDMENT_REQUIRED`—any other status is rejected with
        `ERR_CTR_NOT_AMENDABLE`—and only while the current logical date is on
        or before the business date plus 45 days, otherwise the request is
        rejected with `ERR_AMENDMENT_WINDOW_EXPIRED`."

        Design: Corner/validations/amendment_window_expired_for_filed_ctr
        """
        branch, customer = setup_branch_and_customer()
        filed = create_filed_ctr(customer["id"], branch["id"])
        # business_date 2026-08-01 + 45 days = 2026-09-15; advance past it
        set_clock("2026-09-20T00:00:00Z")
        fresh = get_success_data(api_client.get_ctr(filed["id"], headers=make_officer_headers()))
        resp = api_client.amend_ctr(
            filed["id"],
            {"amendment_reason": "late fix", "expected_ctr_version": fresh["version"]},
            headers=make_officer_headers("officer-y"),
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_WINDOW_EXPIRED)


class TestAmendStateBeatsTemporal:
    def test_amend_state_error_beats_temporal_error(self, api):
        """PRD §2.10 step 6: "State and status checks: the requested action is a
        valid transition from the record's current status (else
        `ERR_INVALID_STATE_TRANSITION`); the receiving branch is `ACTIVE` when
        posting to it (else `ERR_BRANCH_INACTIVE`); the subject customer is
        `ACTIVE` when posting a transaction, sale, or exemption designation for
        them (else `ERR_CUSTOMER_NOT_ACTIVE`, with the customer checked before
        the branch); a cash transaction void target is not already `VOIDED`
        (else `ERR_TRANSACTION_ALREADY_VOIDED`); a CTR amendment target is in
        `FILED`, `ACKNOWLEDGED`, or `AMENDMENT_REQUIRED` (else
        `ERR_CTR_NOT_AMENDABLE`)".
        PRD §2.10 step 9: "Business temporal rules: `occurred_at` not later
        than the current logical clock (else `ERR_OCCURRED_AT_IN_FUTURE`),
        same-day void windows (else `ERR_VOID_WINDOW_EXPIRED`), the 45-day
        amendment window (else `ERR_AMENDMENT_WINDOW_EXPIRED`)".
        PRD §2.10: "Every endpoint applies the same fixed priority order when
        multiple checks could fail on one request, so the surfaced error is
        deterministic."

        Design: Difficulty/priority_pair_validation_conflict/amend_state_error_beats_temporal_error
        """
        set_clock("2026-08-01T12:00:00Z")
        from test_helpers import create_branch, create_customer
        br1 = create_branch(name="Main", branch_code="BR1")
        c1 = create_customer(legal_name="Prio One", tin="12-1212121")
        post_cash_txn(c1["id"], br1["id"], amount_cents=1_100_000,
                      occurred_at="2026-08-01T10:00:00Z")
        ctr = get_single_ctr_for_customer(c1["id"])
        get_success_data(api_client.validate_ctr(ctr["id"], headers=make_analyst_headers("analyst-x")))
        get_success_data(api_client.file_ctr(
            ctr["id"], {"filing_channel": "EFILE"}, headers=make_officer_headers("officer-y"),
        ))
        ctr_now = get_success_data(api_client.get_ctr(ctr["id"], headers=make_officer_headers()))
        # First amendment succeeds -> original SUPERSEDED
        get_success_data(api_client.amend_ctr(
            ctr["id"],
            {"amendment_reason": "amount correction", "expected_ctr_version": ctr_now["version"]},
            headers=make_officer_headers("officer-y"),
        ))
        # Advance past the 45-day amendment window
        set_clock("2026-09-20T00:00:00Z")
        ctr_fresh = get_success_data(api_client.get_ctr(ctr["id"], headers=make_officer_headers()))
        assert ctr_fresh["status"] == "SUPERSEDED"
        # Both state (SUPERSEDED) and temporal (window expired) fail; state wins
        resp = api_client.amend_ctr(
            ctr["id"],
            {"amendment_reason": "second attempt", "expected_ctr_version": ctr_fresh["version"]},
            headers=make_officer_headers("officer-y"),
        )
        validate_error(resp, ApiErrorId.ERR_CTR_NOT_AMENDABLE)

    def test_amend_rejected_on_validated_ctr(self, api):
        """PRD §3.5: "Amendment is permitted only from `FILED`, `ACKNOWLEDGED`,
        or `AMENDMENT_REQUIRED`—any other status is rejected with
        `ERR_CTR_NOT_AMENDABLE`".

        Independent confirmation on a VALIDATED (non-amendable) target.

        Design: Difficulty/priority_pair_validation_conflict/amend_state_error_beats_temporal_error
        """
        branch, customer = setup_branch_and_customer()
        ctr = create_ctr_in_draft(customer["id"], branch["id"])
        validated = get_success_data(api_client.validate_ctr(
            ctr["id"], headers=make_analyst_headers("analyst-x"),
        ))
        resp = api_client.amend_ctr(
            ctr["id"],
            {"amendment_reason": "too early", "expected_ctr_version": validated["version"]},
            headers=make_officer_headers("officer-y"),
        )
        validate_error(resp, ApiErrorId.ERR_CTR_NOT_AMENDABLE)


class TestBusinessConstraints:
    def test_amount_not_positive_rejected(self, api):
        """PRD §3.2: "The amount must be greater than zero—otherwise the posting
        is rejected with `ERR_AMOUNT_NOT_POSITIVE`".

        Design: Corner/validations/amount_not_positive_rejected
        """
        branch, customer = setup_branch_and_customer()
        resp = api_client.create_cash_transaction(
            {
                "customer_id": customer["id"], "branch_id": branch["id"],
                "direction": "CASH_IN", "amount_cents": 0,
                "occurred_at": "2026-08-01T08:00:00Z",
            },
            headers=make_teller_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_AMOUNT_NOT_POSITIVE)

    def test_money_order_limit_boundary(self, api):
        """PRD §3.3: "money orders carry a per-instrument cap: a `MONEY_ORDER`
        with an amount greater than 100000 cents is rejected with
        `ERR_INSTRUMENT_LIMIT_EXCEEDED`."

        Design: Corner/validations/money_order_limit_boundary
        """
        branch, customer = setup_branch_and_customer()
        # Inclusive cap at 100000
        ok = post_instrument_sale(customer["id"], branch["id"],
                                  instrument_type="MONEY_ORDER", amount_cents=100_000,
                                  occurred_at="2026-08-01T08:00:00Z")
        assert ok["id"]
        resp = api_client.create_instrument_sale(
            {
                "customer_id": customer["id"], "branch_id": branch["id"],
                "instrument_type": "MONEY_ORDER", "amount_cents": 100_001,
                "occurred_at": "2026-08-01T08:05:00Z",
            },
            headers=make_teller_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INSTRUMENT_LIMIT_EXCEEDED)
        # Cap is money-order-specific: CASHIERS_CHECK at 100001 succeeds
        ok2 = post_instrument_sale(customer["id"], branch["id"],
                                   instrument_type="CASHIERS_CHECK", amount_cents=100_001,
                                   occurred_at="2026-08-01T08:10:00Z")
        assert ok2["id"]

    def test_duplicate_case_number_rejected(self, api):
        """PRD §3.8: "a `case_number` unique across all examination cases (a
        duplicate is rejected with `ERR_DUPLICATE_CASE_NUMBER`)".

        Design: Corner/validations/duplicate_case_number_rejected
        """
        from test_helpers import create_exam_case
        create_exam_case(regulator="FINCEN", case_number="CASE-500",
                         scope_start_date="2025-01-01", scope_end_date="2025-06-30")
        resp = api_client.create_examination_case(
            {
                "regulator": "OCC", "case_number": "CASE-500",
                "scope_start_date": "2026-01-01", "scope_end_date": "2026-06-30",
            },
            headers=make_examiner_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CASE_NUMBER)

    def test_ctr_incomplete_missing_tin_fixed_by_patch(self, api):
        """PRD §3.5: "Two completeness conditions are enforced at validation,
        and a failure of either is rejected with `ERR_CTR_INCOMPLETE`: the
        customer's `tin` must be non-null, and the frozen-or-live snapshot must
        exceed the reporting threshold on at least one side".
        PRD §3.1: "A `BranchManager` may update a customer's `legal_name` or
        `tin` through a profile patch that increments the customer's `version`
        by one".

        Design: Corner/validations/ctr_incomplete_missing_tin_fixed_by_patch
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_branch, create_customer, make_manager_headers
        br1 = create_branch(name="Main", branch_code="BR1")
        c1 = create_customer(legal_name="No Tin Nina", tin=None)  # explicit null tin
        post_cash_txn(c1["id"], br1["id"], amount_cents=1_100_000,
                      occurred_at="2026-08-01T08:00:00Z")
        ctr = get_single_ctr_for_customer(c1["id"])
        resp = api_client.validate_ctr(ctr["id"], headers=make_analyst_headers("analyst-x"))
        validate_error(resp, ApiErrorId.ERR_CTR_INCOMPLETE)
        # Patch tin; OCC on customer.version (initially 1)
        cust = get_success_data(api_client.get_customer(c1["id"], headers=make_officer_headers()))
        assert cust["version"] == 1
        patched = get_success_data(api_client.patch_customer(
            c1["id"], {"tin": "33-3333330", "expected_customer_version": cust["version"]},
            headers=make_manager_headers(),
        ))
        assert patched["version"] == 2
        validated = get_success_data(api_client.validate_ctr(
            ctr["id"], headers=make_analyst_headers("analyst-x"),
        ))
        assert validated["status"] == "VALIDATED"

    def test_double_void_rejected_already_voided(self, api):
        """PRD §3.2: "a void attempted on an already-`VOIDED` transaction is
        rejected with `ERR_TRANSACTION_ALREADY_VOIDED`."

        Design: Corner/validations/double_void_rejected_already_voided
        """
        branch, customer = setup_branch_and_customer()
        txn = post_cash_txn(customer["id"], branch["id"], amount_cents=500_000,
                            occurred_at="2026-08-01T08:00:00Z")
        get_success_data(api_client.void_cash_transaction(
            txn["id"], {"void_reason": "first"}, headers=make_teller_headers("teller-1"),
        ))
        resp = api_client.void_cash_transaction(
            txn["id"], {"void_reason": "second"}, headers=make_teller_headers("teller-1"),
        )
        validate_error(resp, ApiErrorId.ERR_TRANSACTION_ALREADY_VOIDED)
        from test_helpers import get_aggregation_for
        agg = get_aggregation_for(customer["id"], "2026-08-01")
        assert agg["total_cash_in_cents"] == 0

    def test_missing_auth_headers_return_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting an
        `X-User-Role` value that is not one of the declared roles, is rejected
        with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_headers_return_unauthenticated
        """
        resp = api_client.list_customers(headers=None, params={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestSegregationOfDuties:
    def test_sod_ctr_file_same_operator_rejected(self, api):
        """PRD §3.5: "Segregation of duties is enforced mechanically: the
        filer's `X-User-ID` must differ from the recorded `validated_by_id`,
        otherwise the filing is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sod_ctr_file_same_operator_rejected
        """
        branch, customer = setup_branch_and_customer()
        ctr = create_ctr_in_draft(customer["id"], branch["id"])
        # Validator and filer are the same operator id (different roles)
        get_success_data(api_client.validate_ctr(ctr["id"], headers=make_analyst_headers("shared-op")))
        resp = api_client.file_ctr(
            ctr["id"], {"filing_channel": "EFILE"}, headers=make_officer_headers("shared-op"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        # A different officer can file
        filed = get_success_data(api_client.file_ctr(
            ctr["id"], {"filing_channel": "EFILE"}, headers=make_officer_headers("officer-y"),
        ))
        assert filed["status"] == "FILED"

    def test_sod_exemption_approve_same_requester_rejected(self, api):
        """PRD §3.6: "Approval is performed by a `BSAOfficer` other than the
        requester—segregation of duties compares the approver's `X-User-ID`
        against `requested_by_id` and rejects a match with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sod_exemption_approve_same_requester_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        from test_helpers import create_customer
        c1 = create_customer(legal_name="SoD City", customer_type="GOVERNMENT_AGENCY",
                             account_opened_date="2020-01-01T00:00:00Z")
        ex = request_exemption(c1["id"], phase="PHASE_I", requester_id="officer-a")
        resp = api_client.approve_exemption(ex["id"], headers=make_officer_headers("officer-a"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        approved = get_success_data(api_client.approve_exemption(
            ex["id"], headers=make_officer_headers("officer-b"),
        ))
        assert approved["status"] == "ACTIVE"

    def test_sod_exemption_review_same_designator_rejected(self, api):
        """PRD §3.6: "The reviewer must differ from the officer recorded as
        `designated_by_officer_id`, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sod_exemption_review_same_designator_rejected
        """
        set_clock("2026-01-02T09:00:00Z")
        from test_helpers import create_customer, create_active_phase_i_exemption
        c1 = create_customer(legal_name="SoD Review City", customer_type="GOVERNMENT_AGENCY",
                             account_opened_date="2020-01-01T00:00:00Z")
        ex = create_active_phase_i_exemption(c1["id"], requester_id="officer-a",
                                             approver_id="officer-b")
        set_clock("2027-01-03T00:00:00Z")
        current = get_success_data(api_client.get_exemption_designation(ex["id"], headers=make_officer_headers()))
        assert current["status"] == "REVIEW_DUE"
        resp = api_client.complete_review_exemption(
            ex["id"],
            {"outcome": "PASS", "expected_exemption_version": current["version"]},
            headers=make_officer_headers("officer-b"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        passed = get_success_data(api_client.complete_review_exemption(
            ex["id"],
            {"outcome": "PASS", "expected_exemption_version": current["version"]},
            headers=make_officer_headers("officer-c"),
        ))
        assert passed["status"] == "ACTIVE"
