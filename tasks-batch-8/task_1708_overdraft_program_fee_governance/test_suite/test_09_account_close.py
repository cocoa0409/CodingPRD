"""Voluntary account closure (PRD §3.2): the negative-balance and open-items
guards, and the cross-entity dependency on pending waiver requests."""
from test_helpers import (
    ApiErrorId,
    get_account,
    list_fees,
    make_opted_in_account,
    make_program,
    make_restricted_scenario,
    run_posting_day,
    submit_waiver,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import TELLER
from test_helpers.test_users import make_supervisor_headers


class TestAccountCloseBlockedByPendingWaiver:
    def _setup(self):
        """Account funded 100 (Mon), overdrawn by a 2000 debit (Tue, fee 3500
        POSTED, ledger -5400), cured by a 10000 credit (Wed, ledger 4600,
        status ACTIVE); a FULL waiver request by the holder sits
        PENDING_SUPERVISOR."""
        program = make_program(name="OD-K")
        account, _ = make_opted_in_account(program["id"], holder_name="Holder K",
                                           channel="ONLINE")
        run_posting_day(program["id"], "2026-08-03", account["id"],
                        [("CREDIT_DEPOSIT", 100)], settle=True)
        run_posting_day(program["id"], "2026-08-04", account["id"],
                        [("DEBIT_ONE_TIME", 2000)], settle=True)
        run_posting_day(program["id"], "2026-08-05", account["id"],
                        [("CREDIT_DEPOSIT", 10000)], settle=True)
        fee = list_fees(account_id=account["id"])[0]
        request = submit_waiver(account["id"], [fee["id"]], kind="FULL",
                                reason_code="FIRST_TIME", as_holder=True)
        return account, request

    def test_pending_waiver_blocks_close(self, api):
        """PRD §3.2: "Closing with open items — any fee still `ASSESSED`, any
        waiver request in `PENDING_SUPERVISOR`, `PENDING_MANAGER`, or
        `PENDING_COMPLIANCE`, or any education offer still `OFFERED` — is
        rejected with `ERR_OPEN_ITEMS_BLOCK_CLOSE`."
        PRD §3.6: "An `AccountHolder`-created request never auto-approves; even
        a one-dollar holder request routes to `PENDING_SUPERVISOR` at minimum."

        Design: Difficulty/cross_entity_state_dependency/account_close_blocked_by_pending_waiver
        """
        account, request = self._setup()
        # Holder-created: never auto-approved, even within the teller cap.
        assert request["status"] == "PENDING_SUPERVISOR"
        # Balance 4600 >= 0, so the only blocker is the pending request.
        assert get_account(account["id"])["ledger_balance_cents"] == 4600

        resp = api.close_account(account["id"], TELLER)
        validate_error(resp, ApiErrorId.ERR_OPEN_ITEMS_BLOCK_CLOSE)

    def test_close_succeeds_after_pending_request_is_denied(self, api):
        """PRD §3.2: "A clean close moves the account to `CLOSED_VOLUNTARY` and
        increments its `version`."
        PRD §3.6: "Denying a `PENDING_SUPERVISOR` request — available to
        `Supervisor`, `Manager`, or `ComplianceOfficer` — moves it to `DENIED`
        with `denied_band` set to `SUPERVISOR`".

        Design: Difficulty/cross_entity_state_dependency/account_close_blocked_by_pending_waiver
        """
        account, request = self._setup()
        validate_success(api.deny_fee_waiver_request(
            request["id"], make_supervisor_headers("sup-1")))
        closed = validate_success(api.close_account(account["id"], TELLER))
        assert closed["status"] == "CLOSED_VOLUNTARY"


class TestCloseRestrictedAccountRejected:
    def test_close_only_valid_from_active(self, api):
        """PRD §3.2: "Voluntary closure is available to a `Teller` or
        `ProgramAdmin`, but only for an `ACTIVE` account — attempting it from
        any other status is an invalid state transition".
        PRD §2.10: "seventh, state-machine validity of the requested transition
        and waivability of listed fees (`ERR_INVALID_STATE_TRANSITION`,
        `ERR_FEE_NOT_WAIVABLE`)" and "eleventh, close economics".

        Design: Corner/state_machines/close_restricted_account_returns_invalid_state
        """
        ctx = make_restricted_scenario()
        account = get_account(ctx["account"]["id"])
        assert account["status"] == "RESTRICTED"

        resp = api.close_account(account["id"], TELLER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_account(account["id"])["status"] == "RESTRICTED"


class TestCloseNegativeBalanceRejected:
    def test_active_account_with_negative_ledger_cannot_close(self, api):
        """PRD §3.2: "Closing with a negative `ledger_balance_cents` is
        rejected with `ERR_CLOSE_NEGATIVE_BALANCE`."

        Design: Corner/validations/close_negative_balance_rejected
        """
        program = make_program(name="OD-V16")
        account, _ = make_opted_in_account(program["id"], holder_name="H V16")
        run_posting_day(program["id"], "2026-08-03", account["id"],
                        [("CREDIT_DEPOSIT", 100)], settle=True)
        run_posting_day(program["id"], "2026-08-04", account["id"],
                        [("DEBIT_ONE_TIME", 2000)], settle=True)
        # Ledger 100 - 2000 - 3500 = -5400; fee POSTED, no pending items.
        assert get_account(account["id"])["ledger_balance_cents"] == -5400

        resp = api.close_account(account["id"], TELLER)
        validate_error(resp, ApiErrorId.ERR_CLOSE_NEGATIVE_BALANCE)
