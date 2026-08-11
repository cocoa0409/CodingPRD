"""Onboarding, loan accounts, case register: creation rules, defaults,
envelope shape, pagination/filtering, reverse lookups, and the logical
clock's fixed epoch."""
from test_helpers import (
    DEFAULT_CLOCK_ISO,
    RM_OPERATOR_ID,
    UNKNOWN_UUID,
    ApiErrorId,
    create_borrower,
    create_loan,
    create_loan_account_payload,
    issue_cure_notice,
    make_borrower_headers,
    open_case,
    parse_instant,
    rm_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBorrowerCreation:
    def test_borrower_missing_required_email_returns_invalid_request(self, api):
        """PRD §3.1: "A `RecoveryManager` begins by registering the borrower with
        a `full_name`, a `state_code` capturing the two-letter US state of the
        borrower's residence, and a contact `email`."
        PRD §2.7: "every identifier in the path resolves to an existing resource
        and the request body is well-formed — required fields present, types
        correct, enum values valid, unknown fields rejected, amount fields
        positive integers — with path identifiers validated left to right
        (`ERR_NOT_FOUND`, `ERR_INVALID_REQUEST`)"

        Design: Corner/entities/borrower_missing_required_email_returns_invalid_request
        """
        resp = api.create_borrower(
            {"full_name": "No Email", "state_code": "CA"}, rm_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestLoanAccountCreation:
    def test_loan_optional_defaults_applied(self, api):
        """PRD §3.1: "Three arrears fields — `missed_installments`,
        `accrued_interest_cents`, and `late_fees_cents` — may be supplied at
        creation and each defaults to 0 when omitted"
        PRD §3.1: "A freshly created loan stands in `CURRENT` status with
        `paid_to_date_cents` at 0."
        PRD §3.1: "From these inputs the system derives `total_outstanding_cents`
        — the principal balance plus the accrued interest plus the late fees,
        minus the payments to date"

        Design: Corner/entities/loan_optional_defaults_applied
        """
        borrower = create_borrower(full_name="Def", email="def@x.com")
        resp = api.create_loan_account(
            {
                "borrower_id": borrower["id"],
                "vin": "VIN00000000000041",
                "governing_state_code": "CA",
                "principal_balance_cents": 800_000,
                "apr_bps": 1100,
                "monthly_payment_cents": 25_000,
            },
            rm_headers(),
        )
        loan = validate_success(resp, expected_status=201)
        assert loan["missed_installments"] == 0
        assert loan["accrued_interest_cents"] == 0
        assert loan["late_fees_cents"] == 0
        assert loan["paid_to_date_cents"] == 0
        assert loan["status"] == "CURRENT"
        assert loan["total_outstanding_cents"] == 800_000

    def test_loan_computed_field_input_rejected(self, api):
        """PRD §3.1: "A freshly created loan stands in `CURRENT` status with
        `paid_to_date_cents` at 0." (the manager supplies only the inputs listed
        in §3.1; the running payment total is system-derived)
        PRD §2.7: "the request body is well-formed — required fields present,
        types correct, enum values valid, unknown fields rejected, amount fields
        positive integers"

        Design: Corner/entities/loan_computed_field_input_rejected
        """
        borrower = create_borrower(full_name="CF", email="cf@x.com")
        payload = create_loan_account_payload(
            borrower["id"], vin="VIN00000000000042", principal_balance_cents=800_000,
            apr_bps=1100, monthly_payment_cents=25_000)
        payload["paid_to_date_cents"] = 5
        resp = api.create_loan_account(payload, rm_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCaseRegister:
    def test_get_case_returns_not_found_with_error_envelope(self, api):
        """PRD §2.7: "every identifier in the path resolves to an existing
        resource ... (`ERR_NOT_FOUND`, `ERR_INVALID_REQUEST`)"
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/get_case_returns_not_found_with_error_envelope
        """
        resp = api.get_recovery_case(UNKNOWN_UUID, rm_headers())
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert error_data.get("message"), "error envelope must carry a human-readable message"
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"], "meta.api_request_id must be present"

    def test_case_starts_opened(self, api):
        """PRD §3.1: "A successful opening moves the loan from `CURRENT` to
        `IN_DEFAULT` (incrementing the loan's `version`), stamps the case
        `OPENED`, and records the caller in `opened_by_user_id`"

        Design: Corner/state_machines/case_starts_opened
        """
        borrower = create_borrower(full_name="IS", email="is@x.com")
        loan = create_loan(borrower["id"], vin="VIN00000000000046",
                           principal_balance_cents=500_000, apr_bps=900,
                           monthly_payment_cents=20_000, missed_installments=2,
                           accrued_interest_cents=8_000, late_fees_cents=3_000)
        resp = api.create_recovery_case(
            {"loan_account_id": loan["id"], "default_reason": "delinquent"}, rm_headers())
        case = validate_success(resp, expected_status=201)
        assert case["status"] == "OPENED"
        assert case["opened_by_user_id"] == RM_OPERATOR_ID
        loan_after = validate_success(api.get_loan_account(loan["id"], rm_headers()))
        assert loan_after["status"] == "IN_DEFAULT"

    def test_duplicate_open_case_rejected_then_allowed_after_close(self, api):
        """PRD §3.1: "At most one case per loan may be non-`CLOSED` at any time;
        opening a second while another is still live is rejected with
        `ERR_DUPLICATE_OPEN_CASE` (HTTP 409)."
        PRD §3.9: "Once a case is `CLOSED`, the loan is again eligible under the
        one-open-case rule of §3.1 should a future default occur."

        Design: Corner/validations/duplicate_open_case_rejected
        """
        borrower = create_borrower(full_name="DP", email="dp@x.com")
        loan = create_loan(borrower["id"], vin="VIN00000000000059",
                           principal_balance_cents=500_000, apr_bps=900,
                           monthly_payment_cents=20_000, missed_installments=2,
                           accrued_interest_cents=8_000, late_fees_cents=3_000)
        case1 = open_case(loan["id"], default_reason="first")
        issue_cure_notice(case1["id"])
        set_clock("2026-05-02T00:00:00Z")
        # Cure amount = 2 x 20,000 + 3,000 = 43,000c; cure it in-window.
        pay = api.create_cure_payment(
            case1["id"], {"amount_cents": 43_000},
            make_borrower_headers(borrower["id"]))
        validate_success(pay, expected_status=201)
        assert validate_success(api.get_recovery_case(case1["id"], rm_headers()))["status"] == "CURED"

        # Second open while the first is live (CURED is not CLOSED) is rejected.
        rejected = api.create_recovery_case(
            {"loan_account_id": loan["id"], "default_reason": "second too early"},
            rm_headers())
        validate_error(rejected, ApiErrorId.ERR_DUPLICATE_OPEN_CASE)

        # After closing the first case the loan is eligible again.
        closed = api.close_recovery_case(case1["id"], rm_headers())
        validate_success(closed)
        reopened = api.create_recovery_case(
            {"loan_account_id": loan["id"], "default_reason": "second after close"},
            rm_headers())
        case2 = validate_success(reopened, expected_status=201)
        assert case2["status"] == "OPENED"
        loan_after = validate_success(api.get_loan_account(loan["id"], rm_headers()))
        assert loan_after["status"] == "IN_DEFAULT"

    def test_closed_case_rejects_all_transitions(self, api):
        """PRD §3.9: "`CLOSED` is the case's only terminal state"
        PRD §3.2: "Two guards apply in cascade order: the case must stand in
        `CURE_PENDING` (a state-tier rejection with `ERR_INVALID_CASE_STATE`),
        and only then is sufficiency judged"

        Design: Corner/state_machines/closed_case_rejects_all_transitions
        """
        borrower = create_borrower(full_name="TL", email="tl@x.com")
        loan = create_loan(borrower["id"], vin="VIN00000000000047",
                           principal_balance_cents=500_000, apr_bps=900,
                           monthly_payment_cents=20_000, missed_installments=2,
                           accrued_interest_cents=8_000, late_fees_cents=3_000)
        case = open_case(loan["id"])
        issue_cure_notice(case["id"])
        set_clock("2026-05-02T00:00:00Z")
        # Cure amount is 43,000c; an overpay of 51,000c is at least the amount.
        paid = api.create_cure_payment(
            case["id"], {"amount_cents": 51_000}, make_borrower_headers(borrower["id"]))
        validate_success(paid, expected_status=201)
        validate_success(api.close_recovery_case(case["id"], rm_headers()))

        resp = api.create_cure_payment(
            case["id"], {"amount_cents": 51_000}, make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE)
        entries = validate_success(api.list_ledger_entries(case["id"], rm_headers()))
        assert len(entries) == 1
        assert entries[0]["kind"] == "PAYMENT"
        assert entries[0]["amount_cents"] == 51_000

    def test_fk_reverse_lists_are_reachable(self, api):
        """PRD §3.1: "every case-scoped collection (notices, assignments, items,
        quotes, consignments, deficiency notices, complaints, ledger entries) can
        be listed through its own reverse-lookup endpoint."
        PRD §4: "GET `/borrowers/{id}/loan-accounts` List a borrower's loan
        accounts"

        Design: Corner/endpoints/fk_reverse_lists_are_reachable
        """
        borrower = create_borrower(full_name="FK", email="fk@x.com")
        loan = create_loan(borrower["id"], vin="VIN00000000000067",
                           principal_balance_cents=500_000, apr_bps=900,
                           monthly_payment_cents=20_000, missed_installments=2,
                           accrued_interest_cents=8_000, late_fees_cents=3_000)
        case = open_case(loan["id"], default_reason="fk")
        loans = validate_success(api.list_borrower_loan_accounts(borrower["id"], rm_headers()))
        assert [l["id"] for l in loans] == [loan["id"]]
        cases = validate_success(api.list_loan_recovery_cases(loan["id"], rm_headers()))
        assert [c["id"] for c in cases] == [case["id"]]

    def test_list_pagination_defaults_and_status_filter(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter specifies how many items to skip and defaults to 0."
        PRD §3.1: "The case register can be listed with optional `status` and
        `loan_account_id` filters alongside the standard `limit` and `offset`
        pagination parameters"

        Design: Corner/endpoints/list_pagination_defaults_and_status_filter
        """
        borrower1 = create_borrower(full_name="PG1", email="pg1@x.com")
        loan1 = create_loan(borrower1["id"], vin="VIN00000000000065",
                            principal_balance_cents=500_000, apr_bps=900,
                            monthly_payment_cents=20_000, missed_installments=2,
                            accrued_interest_cents=8_000, late_fees_cents=3_000)
        case1 = open_case(loan1["id"], default_reason="one")
        issue_cure_notice(case1["id"])  # case1 -> CURE_PENDING
        borrower2 = create_borrower(full_name="PG2", email="pg2@x.com")
        loan2 = create_loan(borrower2["id"], vin="VIN00000000000066",
                            principal_balance_cents=500_000, apr_bps=900,
                            monthly_payment_cents=20_000, missed_installments=2,
                            accrued_interest_cents=8_000, late_fees_cents=3_000)
        case2 = open_case(loan2["id"], default_reason="two")  # stays OPENED

        data, meta = validate_paginated(api.list_recovery_cases(rm_headers(), params={"limit": 1}))
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True

        data, meta = validate_paginated(api.list_recovery_cases(rm_headers(), params={"status": "OPENED"}))
        assert [c["id"] for c in data] == [case2["id"]]
        assert meta["total_count"] == 1

        data, meta = validate_paginated(api.list_recovery_cases(rm_headers()))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False
        assert len(data) == 2

    def test_logical_clock_default_is_fixed_epoch(self, api):
        """PRD §2.5: "Before any operator intervention the logical clock starts
        at exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock
        time."

        Design: Corner/complexity_layers/logical_clock_default_is_fixed_epoch
        """
        borrower = create_borrower(full_name="CLK", email="clk@x.com")
        assert parse_instant(borrower["created_at"]) == parse_instant(DEFAULT_CLOCK_ISO)

    def test_immediate_visibility_after_mutation(self, api):
        """PRD §3.2: "Issuing that first notice moves the case from `OPENED` to
        `CURE_PENDING`, repoints the case's `current_cure_notice_id` to the live
        notice, and increments the case's `version`."
        PRD §2.2: "operations that create or modify a resource will return the
        created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        borrower = create_borrower(full_name="IC", email="ic@x.com")
        loan = create_loan(borrower["id"], vin="VIN00000000000077",
                           principal_balance_cents=500_000, apr_bps=900,
                           monthly_payment_cents=20_000, missed_installments=2,
                           accrued_interest_cents=8_000, late_fees_cents=3_000)
        case = open_case(loan["id"])
        case_version = case["version"]
        resp = api.create_cure_notice(
            case["id"], {"expected_recovery_case_version": case_version}, rm_headers())
        notice = validate_success(resp, expected_status=201)
        assert notice["status"] == "SENT"
        # cure amount = 2 x 20,000 + 3,000 late fees + 0 costs = 43,000c
        assert notice["cure_amount_cents"] == 43_000
        case_after = validate_success(api.get_recovery_case(case["id"], rm_headers()))
        assert case_after["status"] == "CURE_PENDING"
        # Notice sent at the 2026-05-01 epoch; deadline is sent_at + 14 days.
        assert parse_instant(case_after["cure_deadline"]) == parse_instant("2026-05-15T00:00:00Z")
        assert case_after["version"] == case_version + 1
        assert case_after["current_cure_notice_id"] == notice["id"]
