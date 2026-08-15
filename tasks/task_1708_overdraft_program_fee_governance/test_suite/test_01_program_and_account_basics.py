"""Program and account creation basics (PRD §3.1, §3.2) and the shared
response envelope (PRD §2.2)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_deposit_account,
    assert_overdraft_program,
    create_program_payload,
    get_account,
    get_program,
    make_account,
    make_program,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, TELLER


class TestProgramCreateAppliesDefaults:
    def test_create_returns_active_version_one_with_echoed_inputs(self, api):
        """PRD §3.1: "A new program is born `ACTIVE` with `version` equal to 1."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/entities/program_create_applies_defaults
        """
        payload = create_program_payload(
            name="OD-STD", posting_order_policy="HIGH_TO_LOW")
        resp = api.create_program(payload, ADMIN)
        program = validate_success(resp, 201)
        assert_overdraft_program(program)
        assert program["status"] == "ACTIVE"
        assert program["version"] == 1
        assert program["fee_amount_cents"] == 3500
        assert program["posting_order_policy"] == "HIGH_TO_LOW"

        fetched = get_program(program["id"])
        assert fetched["fee_amount_cents"] == 3500
        assert fetched["status"] == "ACTIVE"


class TestAccountCreateInitializesComputedFields:
    def test_new_account_is_active_with_zeroed_counters(self, api):
        """PRD §3.2: "The account begins `ACTIVE` with `ledger_balance_cents`
        at zero and every counter at zero."
        PRD §2.5: "A system-managed integer that increments by one on every
        mutation of the resource and serves as the basis for optimistic
        concurrency control."

        Design: Corner/entities/account_create_initializes_computed_fields
        """
        program = make_program()
        resp = api.create_account(
            {"program_id": program["id"], "holder_name": "New Holder"}, TELLER)
        account = validate_success(resp, 201)
        assert_deposit_account(account)
        assert account["status"] == "ACTIVE"
        assert account["ledger_balance_cents"] == 0
        assert account["consecutive_negative_business_days"] == 0
        assert account["restricted_business_days"] == 0
        assert account["lifetime_fees_assessed_cents"] == 0
        assert account["lifetime_fees_waived_cents"] == 0
        assert account["charged_off_cents"] == 0
        assert account["recovered_cents"] == 0
        assert account["charge_off_original_cents"] == 0
        assert account["version"] == 1


class TestAccountCreateMissingProgramId:
    def test_missing_program_id_returns_invalid_request(self, api):
        """PRD §2.10: "third, body well-formedness — required fields present,
        enum values valid, amounts positive, date strings parseable, and
        kind-specific fields supplied (`ERR_INVALID_REQUEST`)".

        Design: Corner/entities/account_create_missing_required_program_id_returns_invalid_request
        """
        resp = api.create_account({"holder_name": "No Program"}, TELLER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestProgramCreateInvalidEnum:
    def test_unknown_posting_order_policy_returns_invalid_request(self, api):
        """PRD §2.10: "third, body well-formedness — required fields present,
        enum values valid, amounts positive, date strings parseable, and
        kind-specific fields supplied (`ERR_INVALID_REQUEST`)".
        PRD §3.1: "`posting_order_policy` selects how debits are ordered
        inside a batch seal: `HIGH_TO_LOW` or `CHRONOLOGICAL`."

        Design: Corner/entities/program_create_invalid_enum_returns_invalid_request
        """
        payload = create_program_payload(
            name="OD-BAD", posting_order_policy="SIDEWAYS")
        resp = api.create_program(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestGetFeeNotFound:
    def test_unknown_fee_id_returns_404_not_found(self, api):
        """PRD §2.10: "the first identifier that does not correspond to an
        existing resource yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_fee_not_found_returns_404
        """
        resp = api.get_fee(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAccountCreateOnSuspendedProgram:
    def test_opening_under_suspended_program_rejected_then_resume(self, api):
        """PRD §3.2: "A `Teller` or `ProgramAdmin` opens a **DepositAccount**
        by supplying the `program_id` of the governing program and the
        customer's `holder_name`; opening under a `SUSPENDED` program is
        rejected with `ERR_PROGRAM_SUSPENDED`."
        PRD §3.1: "A `ProgramAdmin` may suspend a program, moving its `status`
        from `ACTIVE` to `SUSPENDED`, and later resume it, returning from
        `SUSPENDED` to `ACTIVE`; both transitions increment the program's
        `version`."

        Design: Corner/validations/account_create_on_suspended_program_rejected
        """
        program = make_program()
        resp = api.suspend_program(program["id"], ADMIN)
        assert validate_success(resp)["status"] == "SUSPENDED"

        err = api.create_account(
            {"program_id": program["id"], "holder_name": "H V4"}, TELLER)
        validate_error(err, ApiErrorId.ERR_PROGRAM_SUSPENDED)

        resumed = validate_success(api.resume_program(program["id"], ADMIN))
        assert resumed["status"] == "ACTIVE"
        account = make_account(program["id"], holder_name="H V4")
        assert account["status"] == "ACTIVE"
        assert get_account(account["id"])["status"] == "ACTIVE"
