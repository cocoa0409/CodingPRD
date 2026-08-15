"""Opt-in election lifecycle (PRD §3.2): the cyclic revoke/reinstate machine,
disclosure-version gating, and the one-election-per-account rule."""
from test_helpers import (
    ApiErrorId,
    authorize,
    get_account,
    get_election,
    get_transaction,
    make_account,
    make_account_holder_headers,
    make_election,
    make_opted_in_account,
    make_program,
    open_batch,
    seal_batch,
    validate_error,
    validate_success,
)


class TestOptInElectionRevokeReinstateCycle:
    def _setup(self):
        program = make_program(name="OD-E")
        account = make_account(program["id"], holder_name="Holder E")
        election = make_election(account["id"], channel="ONLINE")
        batch = open_batch(program["id"], "2026-08-03")
        # Authorize a would-be-overdraft one-time debit (500 from ledger 0).
        txn = authorize(account["id"], "DEBIT_ONE_TIME", 500)
        return program, account, election, batch, txn

    def test_cycle_flips_status_and_version_on_one_record(self, api):
        """PRD §3.2: "The election is cyclic and may flip without bound.
        Revoking moves `OPTED_IN` to `REVOKED` and refreshes `last_changed_at`
        from the clock".
        PRD §2.5: "A system-managed integer that increments by one on every
        mutation of the resource and serves as the basis for optimistic
        concurrency control."

        Design: Difficulty/non_linear_state_machine/opt_in_election_revoke_reinstate_cycle
        """
        _, account, election, _, _ = self._setup()
        holder = make_account_holder_headers(account["id"])
        assert election["status"] == "OPTED_IN"
        assert election["version"] == 1

        revoked = validate_success(
            api.revoke_opt_in_election(election["id"], holder))
        assert revoked["status"] == "REVOKED"
        assert revoked["version"] == 2

        reinstated = validate_success(api.reinstate_opt_in_election(
            election["id"], {"disclosure_version": "D1"}, holder))
        assert reinstated["status"] == "OPTED_IN"
        assert reinstated["version"] == 3

        revoked_again = validate_success(
            api.revoke_opt_in_election(election["id"], holder))
        assert revoked_again["status"] == "REVOKED"
        assert revoked_again["version"] == 4

    def test_revoked_election_returns_one_time_debit_nsf(self, api):
        """PRD §3.4: "If the projection is negative, the item is payable unless
        it is a `DEBIT_ONE_TIME` and the account has no `OPTED_IN` election; a
        non-payable one-time debit is moved to `RETURNED_NSF` with its
        `batch_id`, `posting_sequence`, and `posted_date` assigned, the balance
        left unchanged, and no fee of any kind created."

        Design: Difficulty/non_linear_state_machine/opt_in_election_revoke_reinstate_cycle
        """
        _, account, election, batch, txn = self._setup()
        holder = make_account_holder_headers(account["id"])
        validate_success(api.revoke_opt_in_election(election["id"], holder))
        validate_success(api.reinstate_opt_in_election(
            election["id"], {"disclosure_version": "D1"}, holder))
        validate_success(api.revoke_opt_in_election(election["id"], holder))

        seal = seal_batch(batch["id"])
        assert seal["items_returned_count"] == 1
        assert seal["fees_assessed_count"] == 0
        assert get_transaction(txn["id"])["status"] == "RETURNED_NSF"
        assert get_account(account["id"])["ledger_balance_cents"] == 0


class TestDoubleRevokeElectionRejected:
    def test_second_revoke_is_invalid_transition(self, api):
        """PRD §3.2: "Revoking moves `OPTED_IN` to `REVOKED`".
        PRD §2.10: "seventh, state-machine validity of the requested transition
        and waivability of listed fees (`ERR_INVALID_STATE_TRANSITION`,
        `ERR_FEE_NOT_WAIVABLE`)".

        Design: Corner/state_machines/double_revoke_election_returns_invalid_state
        """
        program = make_program(name="OD-SM3")
        account, election = make_opted_in_account(program["id"],
                                                  holder_name="H SM3")
        holder = make_account_holder_headers(account["id"])
        validate_success(api.revoke_opt_in_election(election["id"], holder))

        resp = api.revoke_opt_in_election(election["id"], holder)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = get_election(election["id"])
        assert after["status"] == "REVOKED"
        assert after["version"] == 2


class TestOptInStaleDisclosureVersion:
    def test_create_and_reinstate_require_current_disclosure_version(self, api):
        """PRD §3.2: "An `AccountHolder` (for their own account) or a `Teller`
        creates the election with a `channel` of `BRANCH`, `ONLINE`, `PHONE`,
        or `MAIL` documenting how consent was captured, and a
        `disclosure_version` that must exactly equal the program's
        `current_disclosure_version` at that moment; a stale or mismatched
        version is rejected with `ERR_STALE_DISCLOSURE_VERSION`."
        PRD §3.2: "the payload's `disclosure_version` must again equal the
        program's `current_disclosure_version`, else
        `ERR_STALE_DISCLOSURE_VERSION`."

        Design: Corner/validations/opt_in_stale_disclosure_version_rejected
        """
        program = make_program(name="OD-V2")
        account = make_account(program["id"], holder_name="H V2")
        holder = make_account_holder_headers(account["id"])

        bad_create = api.create_opt_in_election(
            account["id"],
            {"channel": "BRANCH", "disclosure_version": "D0"}, holder)
        validate_error(bad_create, ApiErrorId.ERR_STALE_DISCLOSURE_VERSION)

        election = validate_success(api.create_opt_in_election(
            account["id"],
            {"channel": "BRANCH", "disclosure_version": "D1"}, holder), 201)
        assert election["status"] == "OPTED_IN"

        validate_success(api.revoke_opt_in_election(election["id"], holder))
        bad_reinstate = api.reinstate_opt_in_election(
            election["id"], {"disclosure_version": "D0"}, holder)
        validate_error(bad_reinstate, ApiErrorId.ERR_STALE_DISCLOSURE_VERSION)


class TestSecondElectionForAccountRejected:
    def test_at_most_one_election_per_account_ever(self, api):
        """PRD §3.2: "An account has at most one election, ever — a second
        creation attempt is rejected with `ERR_ELECTION_ALREADY_EXISTS` — and
        an account with no election at all is simply not opted in."

        Design: Corner/validations/second_election_for_account_rejected
        """
        program = make_program(name="OD-V3")
        account, _ = make_opted_in_account(program["id"], holder_name="H V3",
                                           channel="ONLINE")
        holder = make_account_holder_headers(account["id"])
        resp = api.create_opt_in_election(
            account["id"],
            {"channel": "MAIL", "disclosure_version": "D1"}, holder)
        validate_error(resp, ApiErrorId.ERR_ELECTION_ALREADY_EXISTS)
