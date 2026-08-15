"""Program creation, program-code uniqueness, BIN range constraints, program
posture lifecycle, and soft-delete retrieval."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_bin_range,
    assert_card_program,
    create_account_payload,
    create_bin_range_payload,
    create_program_payload,
    get_success_data,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]


class TestProgramCreation:
    def test_program_creation_returns_201_with_defaults(self, api):
        """PRD §3.1: "A new program starts in `DRAFT` posture with
        `authorization_rules_locked` false and `open_card_count` zero".

        Design: Corner/entities/program_creation_returns_201_with_defaults
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", TEST_USERS["platform_admin_headers"]))
        resp = api.create_program(
            create_program_payload(
                program_code="P-INIT-1",
                product_class="DEBIT_CONSUMER",
                network="VISA",
                currency_code="USD",
                daily_spend_cap_cents=500000,
            ),
            PM,
        )
        data = validate_success(resp, expected_status=201)
        assert_card_program(data)
        assert data["posture"] == "DRAFT", f"posture must start DRAFT, got {data['posture']}"
        assert data["authorization_rules_locked"] is False
        assert data["open_card_count"] == 0
        assert isinstance(data["version"], int) and data["version"] >= 1

    def test_program_code_unique_globally(self, api):
        """PRD §3.1: "The creation payload carries a `program_code` that must be
        unique across all programs — including programs that have since been
        `TERMINATED`, so a retired code is never recycled".

        Design: Corner/entities/program_code_unique_globally
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", TEST_USERS["platform_admin_headers"]))
        first = api.create_program(
            create_program_payload(program_code="P-UNIQ"), PM,
        )
        validate_success(first, expected_status=201)
        # Reusing the same program_code must be rejected (PRD names no specific
        # error_id for uniqueness — assert a 4xx error envelope).
        resp = api.create_program(
            create_program_payload(
                program_code="P-UNIQ",
                product_class="CONSUMER_PREPAID",
                network="MASTERCARD",
            ),
            PM,
        )
        assert 400 <= resp.status_code < 500, (
            f"Duplicate program_code must be rejected with 4xx, got {resp.status_code}"
        )
        body = resp.json()
        assert body.get("response_type") == "error"
        assert isinstance(body["data"].get("error_id"), str)

    def test_card_account_requires_valid_program_fk(self, api):
        """PRD §2.9: "any foreign key supplied in a request body — a program,
        account, BIN range, vendor, mandate, or target program reference — must
        resolve to an existing row, or the request is rejected with
        `ERR_INVALID_REFERENCE` (HTTP 422)."

        Design: Corner/entities/card_account_requires_valid_program_fk
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", TEST_USERS["platform_admin_headers"]))
        resp = api.create_account(
            create_account_payload(
                "00000000-0000-0000-0000-000000000000",
                "A-X",
                account_class="INDIVIDUAL",
                daily_spend_cap_cents=1000,
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE.value)

    def test_bin_range_range_size_must_be_power_of_10_in_range(self, api):
        """PRD §3.1: "a `range_size` that must be a power of ten no smaller than
        one thousand and no larger than ten million".

        Design: Corner/entities/bin_range_range_size_must_be_power_of_10_in_range
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", TEST_USERS["platform_admin_headers"]))
        prog = get_success_data(
            api.create_program(create_program_payload(program_code="P-BIN-SZ"), PM),
        )
        # 500 is not a power of ten → rejected (PRD names no specific error_id).
        resp = api.create_bin_range(
            prog["id"],
            create_bin_range_payload(
                bin_prefix="499999",
                range_size=500,
                effective_from="2026-08-01T00:00:00Z",
                effective_until="2027-01-01T00:00:00Z",
            ),
            PM,
        )
        assert 400 <= resp.status_code < 500, (
            f"Non-power-of-ten range_size must be rejected with 4xx, got {resp.status_code}"
        )
        assert resp.json().get("response_type") == "error"

    def test_bin_range_effective_from_must_precede_until(self, api):
        """PRD §3.1: "an effective window delimited by `effective_from` and
        `effective_until`, where `effective_until` must be strictly later than
        `effective_from` — a violation is rejected with `ERR_BIN_NOT_IN_WINDOW`."

        Design: Corner/entities/bin_range_effective_from_must_precede_until
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", TEST_USERS["platform_admin_headers"]))
        prog = get_success_data(
            api.create_program(create_program_payload(program_code="P-BIN-WIN"), PM),
        )
        resp = api.create_bin_range(
            prog["id"],
            create_bin_range_payload(
                bin_prefix="499999",
                range_size=1000,
                effective_from="2027-01-01T00:00:00Z",
                effective_until="2026-08-01T00:00:00Z",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_BIN_NOT_IN_WINDOW.value)

    def test_card_account_credit_limit_zero_for_non_commercial(self, api):
        """PRD §3.4: "`credit_limit_cents` is meaningful only for accounts under
        a `COMMERCIAL_CREDIT` program; under any other product class it must
        equal zero."

        Design: Corner/entities/card_account_credit_limit_zero_for_non_commercial
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", TEST_USERS["platform_admin_headers"]))
        from test_helpers import create_program_with_bin_and_publish
        prog, _bin = create_program_with_bin_and_publish("P-NC", product_class="DEBIT_CONSUMER")
        resp = api.create_account(
            create_account_payload(
                prog["id"],
                "A-NC",
                account_class="INDIVIDUAL",
                credit_limit_cents=1000,
                daily_spend_cap_cents=5000,
            ),
            PM,
        )
        assert 400 <= resp.status_code < 500, (
            f"Non-zero credit_limit_cents under DEBIT_CONSUMER must be rejected, "
            f"got {resp.status_code}"
        )
        assert resp.json().get("response_type") == "error"

    def test_card_expiry_year_must_not_be_in_past(self, api):
        """PRD §3.4: "an `expiry_year` that must be later than the current clock
        year — or equal to it, in which case `expiry_month` must be at least the
        current month".

        Design: Corner/entities/card_expiry_year_must_not_be_in_past
        """
        from test_helpers import create_open_account, create_program_with_bin_and_publish
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", TEST_USERS["platform_admin_headers"]))
        prog, _bin = create_program_with_bin_and_publish("P-EXP")
        acct = create_open_account(prog["id"], "A-EXP", daily_spend_cap_cents=10000)
        # Clock year is 2026; expiry_year=2025 is in the past → rejected.
        resp = api.issue_card(
            acct["id"],
            {"expiry_month": 1, "expiry_year": 2025, "form_factor": "PHYSICAL"},
            PM,
        )
        assert 400 <= resp.status_code < 500, (
            f"Past expiry must be rejected with 4xx, got {resp.status_code}"
        )
        assert resp.json().get("response_type") == "error"

    def test_get_nonexistent_program_returns_404(self, api):
        """PRD §2.7: "every id in a path template (program, bin range, vendor,
        batch, account, card, activation token, authorization event, settlement,
        rule, mandate, acknowledgement, campaign, conversion job) must resolve
        to an existing row, and nested paths validate parents left to right
        (`ERR_NOT_FOUND`)."

        Design: Corner/entities/get_nonexistent_program_returns_404
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", TEST_USERS["platform_admin_headers"]))
        resp = api.get_program("00000000-0000-0000-0000-000000000000", PM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestProgramPostureTransitions:
    def test_publish_program_with_no_active_bin_rejected(self, api):
        """PRD §3.2: "at least one of the program's BIN ranges must be `ACTIVE`
        (otherwise `ERR_PROGRAM_NO_ACTIVE_BIN`)".

        Design: Corner/state_machines/publish_program_with_no_active_bin_rejected
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", TEST_USERS["platform_admin_headers"]))
        prog = get_success_data(
            api.create_program(create_program_payload(program_code="P-NOBIN"), PM),
        )
        resp = api.publish_program(prog["id"], PM)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NO_ACTIVE_BIN.value)

    def test_sunset_program_with_in_flight_batch_rejected(self, api):
        """PRD §3.2: "the `LIVE` → `SUNSETTING` transition is refused with
        `ERR_PROGRAM_BATCH_IN_FLIGHT` while any production batch under the
        program sits in `SUBMITTED` or `IN_PRODUCTION`."

        Design: Corner/state_machines/sunset_program_with_in_flight_batch_rejected
        """
        from test_helpers import (
            create_program_with_bin_and_publish,
            create_submitted_batch,
            create_vendor,
        )
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", TEST_USERS["platform_admin_headers"]))
        prog, _bin = create_program_with_bin_and_publish("P-INF")
        vendor = create_vendor("V-INF", daily_capacity_cards=100)
        create_submitted_batch(
            prog["id"], vendor["id"],
            scheduled_for_utc_date="2026-08-15",
            requested_card_count=10,
            unit_cost_cents=100,
        )
        resp = api.sunset_program(prog["id"], PM)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_BATCH_IN_FLIGHT.value)

    def test_terminate_program_with_open_accounts_rejected(self, api):
        """PRD §3.2: "for the other two reasons, every card account under the
        program must already be `CLOSED` or `CONVERTED_OUT`, or the request
        fails with `ERR_PROGRAM_HAS_OPEN_ACCOUNTS`."

        Design: Corner/state_machines/terminate_program_with_open_accounts_rejected
        """
        from test_helpers import create_open_account, create_program_with_bin_and_publish
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", TEST_USERS["platform_admin_headers"]))
        prog, _bin = create_program_with_bin_and_publish("P-TOA")
        create_open_account(prog["id"], "A-TOA", daily_spend_cap_cents=10000)
        get_success_data(api.sunset_program(prog["id"], PM))
        resp = api.terminate_program(prog["id"], "VOLUNTARY", PM)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_HAS_OPEN_ACCOUNTS.value)

    def test_invalid_transition_rejected(self, api):
        """PRD §3.2: "Termination is final and moves `SUNSETTING` → `TERMINATED`."
        PRD §2.7: "State validity — the target resource must be in a state that
        permits the requested transition (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/invalid_transition_rejected
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", TEST_USERS["platform_admin_headers"]))
        prog = get_success_data(
            api.create_program(create_program_payload(program_code="P-IT"), PM),
        )
        # terminate from DRAFT (not SUNSETTING) is an invalid transition.
        resp = api.terminate_program(prog["id"], "VOLUNTARY", PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_terminal_state_lockdown(self, api):
        """PRD §3.2: "Termination is final and moves `SUNSETTING` → `TERMINATED`."
        PRD §2.7: "State validity — the target resource must be in a state that
        permits the requested transition (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/terminal_state_lockdown
        """
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", TEST_USERS["platform_admin_headers"]))
        from test_helpers import create_program_with_bin_and_publish
        prog, _bin = create_program_with_bin_and_publish("P-TL")
        get_success_data(api.sunset_program(prog["id"], PM))
        term = api.terminate_program(prog["id"], "VOLUNTARY", PM)
        validate_success(term, expected_status=200)
        # From TERMINATED, sunset is no longer a valid transition.
        resp = api.sunset_program(prog["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_bin_range_retire_with_allocated_pans_rejected(self, api):
        """PRD §3.2: "if `pans_allocated` is above zero the retirement is
        rejected with `ERR_BIN_HAS_ALLOCATED_PANS`".

        Design: Corner/state_machines/bin_range_retire_with_allocated_pans_rejected
        """
        from test_helpers import (
            create_open_account,
            create_program_with_bin_and_publish,
            issue_card_for_account,
        )
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", TEST_USERS["platform_admin_headers"]))
        prog, bin_range = create_program_with_bin_and_publish("P-BRA")
        acct = create_open_account(prog["id"], "A-BRA", daily_spend_cap_cents=10000)
        issue_card_for_account(acct["id"], bin_range_id=bin_range["id"])
        resp = api.retire_bin_range(bin_range["id"], PM)
        validate_error(resp, ApiErrorId.ERR_BIN_HAS_ALLOCATED_PANS.value)
