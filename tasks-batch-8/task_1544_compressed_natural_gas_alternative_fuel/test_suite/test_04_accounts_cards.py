"""Fleet account and card lifecycle: cycles, terminal lockdown, balance gating
on close, uniqueness, and version increments (PRD §2.4, §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    authorize_session,
    create_fleet_account,
    create_fleet_card,
    get_account,
    make_fleet_account_manager_headers,
    setup_fueling_ready,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAccountSuspendResumeCycle:
    """Difficulty instance: account_suspend_resume_cycle_gates_fueling (two tests)."""

    def _setup_with_session(self):
        env = setup_fueling_ready(station_name="Golf", station_code="ST-GOLF")
        session = validate_success(
            authorize_session(
                env["card"]["id"], env["dispenser"]["id"], "CR-A1", 20.0
            ),
            201,
        )
        return env, session

    def test_suspended_account_blocks_authorize(self, api, network_operator_headers):
        """PRD §3.4: "The card must be ACTIVE (`ERR_CARD_NOT_ACTIVE`, HTTP 409)
        and its account ACTIVE (`ERR_ACCOUNT_NOT_ACTIVE`); the dispenser must
        be IN_SERVICE (`ERR_DISPENSER_NOT_IN_SERVICE`, HTTP 409); the station
        must be ACTIVE (`ERR_STATION_NOT_ACTIVE`); the station's posture must
        not be OUTAGE (`ERR_STATION_OUTAGE`); and the station's `access_mode`
        must serve the requested access type — PUBLIC stations serve public
        sessions, PRIVATE stations private sessions, DUAL stations both — else
        `ERR_ACCESS_MODE_MISMATCH` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/account_suspend_resume_cycle_gates_fueling
        """
        env, _session = self._setup_with_session()
        account_id = env["account"]["id"]
        suspended = validate_success(
            api.suspend_fleet_account(account_id, network_operator_headers), 200
        )
        assert suspended["status"] == "SUSPENDED"
        resp = authorize_session(env["card"]["id"], env["dispenser"]["id"], "CR-A2", 20.0)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, 409)

    def test_resumed_account_authorizes_with_balance_intact(
        self, api, network_operator_headers
    ):
        """PRD §3.3: "Accounts may be suspended and later resumed by a
        `NetworkOperator`. Suspension requires the account to be ACTIVE, else
        `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409); resumption requires it to be
        SUSPENDED, else `ERR_ACCOUNT_NOT_SUSPENDED` (HTTP 409)."
        PRD §3.4: "The hold, `hold_amount_cents`, is `estimated_gge` multiplied
        by the resolved unit price, rounded half-up to a whole cent."

        Design: Difficulty/non_linear_state_machine/account_suspend_resume_cycle_gates_fueling
        """
        env, session = self._setup_with_session()
        account_id = env["account"]["id"]
        validate_success(api.suspend_fleet_account(account_id, network_operator_headers), 200)
        resumed = validate_success(
            api.resume_fleet_account(account_id, network_operator_headers), 200
        )
        assert resumed["status"] == "ACTIVE"
        # First session's 5780-cent hold (20.0 x 289) survived the round trip.
        assert get_account(account_id)["outstanding_balance_cents"] == 5780
        session3 = validate_success(
            authorize_session(env["card"]["id"], env["dispenser"]["id"], "CR-A3", 20.0),
            201,
        )
        assert session3["status"] == "AUTHORIZED"
        assert session3["hold_amount_cents"] == 5780


class TestCardRevokedLockdown:
    def test_card_revoked_terminal_lockdown(self, api):
        """PRD §3.3: "Any attempt to change the status of an already REVOKED
        card is rejected with `ERR_CARD_ALREADY_REVOKED` (HTTP 409), and
        resuming a SUSPENDED card additionally requires its owning account to
        be ACTIVE, else `ERR_ACCOUNT_NOT_ACTIVE`."

        Design: Corner/state_machines/card_revoked_terminal_lockdown
        """
        account = create_fleet_account(account_name="CardLock", credit_limit_cents=100000)
        fam = make_fleet_account_manager_headers(account["id"])
        card = create_fleet_card(account["id"], daily_gge_limit=100.0)
        validate_success(
            api.set_fleet_card_status(card["id"], {"to_status": "REVOKED"}, fam), 200
        )
        resp = api.set_fleet_card_status(card["id"], {"to_status": "ACTIVE"}, fam)
        validate_error(resp, ApiErrorId.ERR_CARD_ALREADY_REVOKED, 409)
        fetched = validate_success(api.get_fleet_card(card["id"], fam), 200)
        assert fetched["status"] == "REVOKED"


class TestAccountClose:
    def test_account_close_blocked_by_balance_then_succeeds(
        self, api, network_operator_headers, station_manager_headers
    ):
        """PRD §3.3: "Closing an account is stronger: it requires ACTIVE status
        and an `outstanding_balance_cents` of exactly zero, else
        `ERR_OUTSTANDING_BALANCE_NONZERO` (HTTP 409), and on success the
        account becomes CLOSED — terminal — while every non-REVOKED card on the
        account cascades to REVOKED, each card's `version` incrementing by
        one."

        Design: Corner/validations/account_close_blocked_by_balance_then_succeeds
        """
        env = setup_fueling_ready(
            station_name="Close", station_code="ST-CLOSE", credit_limit_cents=100000,
            daily_gge_limit=100.0,
        )
        account_id = env["account"]["id"]
        card_id = env["card"]["id"]
        session = validate_success(
            authorize_session(card_id, env["dispenser"]["id"], "CR-CL1", 20.0), 201
        )

        resp = api.close_fleet_account(account_id, network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_OUTSTANDING_BALANCE_NONZERO, 409)

        validate_success(
            api.void_session(session["id"], {"reason": "MANAGER_VOID"}, station_manager_headers),
            200,
        )
        closed = validate_success(
            api.close_fleet_account(account_id, network_operator_headers), 200
        )
        assert closed["status"] == "CLOSED"
        card = validate_success(api.get_fleet_card(card_id, network_operator_headers), 200)
        assert card["status"] == "REVOKED", "close cascades to non-REVOKED cards"


class TestCardUniqueness:
    def test_duplicate_card_number_rejected(self, api):
        """PRD §3.3: "Issuance requires the account to be ACTIVE (else
        `ERR_ACCOUNT_NOT_ACTIVE`), a `card_number` unique across all cards (a
        duplicate is `ERR_CARD_NUMBER_EXISTS`, HTTP 409), a `vehicle_plate`
        binding the card to a vehicle, and a positive `daily_gge_limit` capping
        per-card daily volume."

        Design: Corner/validations/duplicate_card_number_rejected
        """
        a = create_fleet_account(account_name="Dup A", credit_limit_cents=100000)
        create_fleet_card(a["id"], card_number="FC-DUP1", daily_gge_limit=100.0)
        b = create_fleet_account(account_name="Dup B", credit_limit_cents=100000)
        resp = api.create_fleet_card(
            {
                "fleet_account_id": b["id"],
                "card_number": "FC-DUP1",
                "vehicle_plate": "1RRR018",
                "daily_gge_limit": 100.0,
            },
            make_fleet_account_manager_headers(b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CARD_NUMBER_EXISTS, 409)


class TestAccountResumeValidation:
    def test_account_resume_when_active_rejected(self, api, network_operator_headers):
        """PRD §3.3: "Accounts may be suspended and later resumed by a
        `NetworkOperator`. Suspension requires the account to be ACTIVE, else
        `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409); resumption requires it to be
        SUSPENDED, else `ERR_ACCOUNT_NOT_SUSPENDED` (HTTP 409)."

        Design: Corner/validations/account_resume_when_active_rejected
        """
        account = create_fleet_account(account_name="ResB", credit_limit_cents=100000)
        resp = api.resume_fleet_account(account["id"], network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_SUSPENDED, 409)


class TestVersionIncrements:
    def test_version_increments_on_every_mutation(self, api, network_operator_headers):
        """PRD §2.4: "Every persisted resource carries an `id` that is a
        server-minted UUID with no type prefix. Alongside it, resources carry
        `created_at` and `updated_at` timestamps formatted as ISO 8601 UTC with
        three fractional digits, and a `version` integer that starts at 1 when
        the resource is created and increments by exactly one on every
        mutation, including system-driven mutations such as clock sweeps and
        cascades."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        account = create_fleet_account(account_name="Ver Co", credit_limit_cents=100000)
        assert account["version"] == 1
        suspended = validate_success(
            api.suspend_fleet_account(account["id"], network_operator_headers), 200
        )
        assert suspended["version"] == 2
        resumed = validate_success(
            api.resume_fleet_account(account["id"], network_operator_headers), 200
        )
        assert resumed["version"] == 3


class TestAccountManagerScoping:
    def test_fleet_account_manager_list_scoped_to_own_account(self, api):
        """PRD §2.10: "`FleetAccountManager` views are auto-scoped to the
        account identified by their `X-User-ID`: account lists and details,
        fleet cards, fueling sessions, supply contracts, and monthly
        settlements are all filtered to that account."

        Design: Corner/rbac/fleet_account_manager_list_scoped_to_own_account
        """
        a = create_fleet_account(account_name="Scope A", credit_limit_cents=100000)
        create_fleet_account(account_name="Scope B", credit_limit_cents=100000)
        rows, meta = validate_paginated(
            api.list_fleet_accounts(make_fleet_account_manager_headers(a["id"]))
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == a["id"]
