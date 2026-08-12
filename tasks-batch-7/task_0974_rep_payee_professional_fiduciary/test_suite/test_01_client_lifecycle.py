"""Client lifecycle: intake defaults, activation gating, suspend/reactivate,
terminal lockdown, initial states, not-found variants."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, make_admin_headers, make_financial_officer_headers,
    make_case_manager_headers, make_auditor_headers,
    create_client, create_active_client, create_client_with_verified_entitlement,
    create_account, create_active_bond, create_budget_plan_for_client,
    create_disbursement, create_spend_down_plan, create_conservator,
    create_audit_with_findings, set_clock,
    create_client_payload, create_entitlement_payload,
    create_surety_bond_payload, create_court_order_payload,
    create_audit_case_payload, create_accounting_report_payload,
    create_deposit_payload,
)
from test_helpers.api_client import api_client as api

ADMIN = make_admin_headers()
FO = make_financial_officer_headers()
CM = make_case_manager_headers()
AUD = make_auditor_headers()


class TestClientDefaultsAndCreate:
    def test_client_create_defaults_applied(self, api):
        """PRD §3.1: "When the client is Medicaid-enrolled,
        `medicaid_resource_limit_cents` sets the countable-resource ceiling; it
        defaults to 200,000 cents ($2,000.00) and must be positive when
        supplied. A new client begins in `INTAKE_REVIEW`."

        Design: Corner/entities/client_create_defaults_applied
        """
        resp = api.create_client(
            {
                "legal_name": "Default Dan",
                "date_of_birth": "1988-08-08",
                "ssn_last4": "4455",
                "county_of_residence": "TRV",
                "medicaid_enrolled": True,
            },
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert data["medicaid_resource_limit_cents"] == 200000
        assert data["status"] == "INTAKE_REVIEW"
        assert data["version"] == 1

    def test_client_create_missing_required_returns_invalid_request(self, api):
        """PRD §2.9: "missing required fields, invalid enum values, violated
        integer constraints (amounts that must be positive, counts that must be
        non-negative), an `ssn_last4` that is not exactly four digits, budget
        line percents that do not sum to exactly 100 or repeat a category, and
        malformed date strings all produce `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/client_create_missing_required_returns_invalid_request
        """
        resp = api.create_client(
            {
                "date_of_birth": "1988-08-08",
                "ssn_last4": "4455",
                "county_of_residence": "TRV",
                "medicaid_enrolled": True,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)



class TestActivationGating:
    def test_client_activation_blocked_without_verified_entitlement(self, api):
        """PRD §3.1: "It requires at least one `VERIFIED` entitlement on the
        client — without one the request fails with
        `ERR_NO_VERIFIED_ENTITLEMENT` — and as it completes, every `FROZEN`
        account of the client reopens to `OPEN` and the client's `version`
        advances."

        Design: Difficulty/cross_entity_state_dependency/client_activation_requires_verified_entitlement
        """
        client = create_client()
        ent = get_success_data(api.create_entitlement(
            create_entitlement_payload(client_id=client["id"]), ADMIN
        ))
        # Entitlement still PENDING_VERIFICATION: activation must fail.
        resp = api.activate_client(client["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_VERIFIED_ENTITLEMENT)
        # Verify the entitlement, then activation succeeds.
        get_success_data(api.verify_entitlement(ent["id"], ADMIN))
        resp2 = api.activate_client(client["id"], ADMIN)
        data = validate_success(resp2, expected_status=200)
        assert data["status"] == "ACTIVE"

    def test_client_activation_succeeds_after_entitlement_verified(self, api):
        """PRD §3.1: "It requires at least one `VERIFIED` entitlement on the
        client — without one the request fails with
        `ERR_NO_VERIFIED_ENTITLEMENT` — and as it completes, every `FROZEN`
        account of the client reopens to `OPEN` and the client's `version`
        advances."

        Design: Difficulty/cross_entity_state_dependency/client_activation_requires_verified_entitlement
        """
        client, ent = create_client_with_verified_entitlement()
        resp = api.activate_client(client["id"], ADMIN)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "ACTIVE"


class TestSuspendReactivateCycle:
    def test_client_suspend_reactivate_cycle_restores_accounts(self, api):
        """PRD §3.1: "Activation moves a client `INTAKE_REVIEW` → `ACTIVE` or
        `SUSPENDED` → `ACTIVE`. It requires at least one `VERIFIED` entitlement
        on the client — without one the request fails with
        `ERR_NO_VERIFIED_ENTITLEMENT` — and as it completes, every `FROZEN`
        account of the client reopens to `OPEN` and the client's `version`
        advances. Suspension moves a client `ACTIVE` → `SUSPENDED` and freezes
        every `OPEN` account to `FROZEN`, which in turn rejects that account's
        pending disbursements through the freeze cascade; suspension is also
        how the misuse cascade of §3.9 manifests on the client."

        Design: Difficulty/non_linear_state_machine/client_suspend_reactivate_cycle_restores_accounts
        """
        client, ent = create_client_with_verified_entitlement()
        account = create_account(client["id"])
        activated = get_success_data(api.activate_client(client["id"], ADMIN))
        assert activated["version"] == 2

        suspended = get_success_data(api.suspend_client(client["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"
        assert suspended["version"] == 3
        acct_after_suspend = get_success_data(api.get_trust_account(account["id"], ADMIN))
        assert acct_after_suspend["status"] == "FROZEN"

        reactivated = get_success_data(api.activate_client(client["id"], ADMIN))
        assert reactivated["status"] == "ACTIVE"
        assert reactivated["version"] == 4
        acct_after_reactivate = get_success_data(api.get_trust_account(account["id"], ADMIN))
        assert acct_after_reactivate["status"] == "OPEN"

    def test_client_suspend_freeze_rejects_pending_disbursements(self, api):
        """PRD §3.1: "Suspension moves a client `ACTIVE` → `SUSPENDED` and
        freezes every `OPEN` account to `FROZEN`, which in turn rejects that
        account's pending disbursements through the freeze cascade; suspension
        is also how the misuse cascade of §3.9 manifests on the client."

        Design: Difficulty/non_linear_state_machine/client_suspend_reactivate_cycle_restores_accounts
        """
        set_clock("2026-06-05T00:00:00Z")
        client, ent = create_active_client()
        account = create_account(client["id"])
        create_active_bond()
        plan = create_budget_plan_for_client(client["id"])
        d = create_disbursement(client["id"], account["id"], plan["id"],
                                amount_cents=5000)
        # Suspend: account freeze cascade rejects the REQUESTED disbursement.
        get_success_data(api.suspend_client(client["id"], ADMIN))
        d_after = get_success_data(api.get_disbursement(d["id"], FO))
        assert d_after["status"] == "REJECTED"
        acct_after = get_success_data(api.get_trust_account(account["id"], ADMIN))
        assert acct_after["status"] == "FROZEN"


class TestTerminalLockdown:
    def test_activate_terminated_client_returns_already_terminal(self, api):
        """PRD §2.9: "Stage six is the terminal-state guard: an entity already
        in a terminal state — a `TERMINATED` client or entitlement, a `CLOSED`
        account, a `SUPERSEDED` plan, a `REJECTED` or `RETURNED` disbursement,
        an `ACCEPTED` or `REJECTED` report, a `MET` or `LAPSED` spend-down
        plan, a `DISCHARGED` conservator, an `EXECUTED` or `EXPIRED` court
        order, a `LAPSED` bond, a `CLOSED_NO_ACTION` or `MISUSE_CONFIRMED`
        audit — rejects any further action with `ERR_ALREADY_TERMINAL` (HTTP
        409)."

        Design: Corner/state_machines/activate_terminated_client_returns_already_terminal
        """
        client, ent = create_active_client()
        get_success_data(api.terminate_client(client["id"], ADMIN))
        resp = api.activate_client(client["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestInitialStates:
    def test_initial_states_on_create(self, api):
        """PRD §3.1: "A new client begins in `INTAKE_REVIEW`."
        PRD §3.1: "A new entitlement sits in `PENDING_VERIFICATION` until an
        administrator verifies it, which stamps `verified_at` with the current
        logical clock; an entitlement whose owning client has reached
        `TERMINATED` cannot be verified."
        PRD §3.2: "Accounts open in `OPEN` status and move `OPEN` → `FROZEN` →
        `OPEN` only through the client lifecycle cascades of §3.1; there is no
        operator endpoint that freezes an account directly."
        PRD §3.5: "A created disbursement records `requested_by_user_id` from
        the requester and sits in `REQUESTED`, with `fee_cents` at zero until
        release."
        PRD §3.3: "A recorded deposit sits in `RECEIVED`."
        PRD §3.7: "A petitioned order sits in `PETITIONED` until an
        administrator grants it, moving it `PETITIONED` → `GRANTED` and
        stamping `granted_date` with the logical clock date."
        PRD §3.7: "a new bond is `PENDING`."
        PRD §3.8: "A drafted report sits in `DRAFTING` with its four totals
        still null."
        PRD §3.9: "Plans live in `DRAFT`."
        PRD §3.9: "The case opens in `OPENED`; issuing findings moves it
        `OPENED` → `FINDINGS_ISSUED` and records the declared
        `misuse_amount_cents` (zero for clean findings, never negative) and
        `findings_count` (never negative)."
        PRD §3.5: "A conservator is `ACTIVE` from registration; an
        administrator may suspend one (`ACTIVE` → `SUSPENDED`) or discharge one
        (`ACTIVE` → `DISCHARGED` or `SUSPENDED` → `DISCHARGED`)."

        Design: Corner/state_machines/initial_states_on_create
        """
        set_clock("2026-06-05T00:00:00Z")
        # Client starts INTAKE_REVIEW
        client = create_client(medicaid_enrolled=True)
        assert client["status"] == "INTAKE_REVIEW"
        # Entitlement starts PENDING_VERIFICATION
        ent = get_success_data(api.create_entitlement(
            create_entitlement_payload(client_id=client["id"]), ADMIN
        ))
        assert ent["status"] == "PENDING_VERIFICATION"
        # Account starts OPEN
        account = create_account(client["id"])
        assert account["status"] == "OPEN"
        # Bond starts PENDING
        bond = get_success_data(api.create_surety_bond(create_surety_bond_payload(), ADMIN))
        assert bond["status"] == "PENDING"
        # Court order starts PETITIONED
        order = get_success_data(api.create_court_order(
            create_court_order_payload(client_id=client["id"]), ADMIN
        ))
        assert order["status"] == "PETITIONED"
        # Conservator starts ACTIVE
        cons = create_conservator(client["id"], authority_scope="ADVISORY")
        assert cons["status"] == "ACTIVE"
        # Audit case starts OPENED
        audit = get_success_data(api.create_audit_case(
            create_audit_case_payload(client_id=client["id"]), AUD,
        ))
        assert audit["status"] == "OPENED"
        # Report starts DRAFTING
        report = get_success_data(api.create_accounting_report(
            create_accounting_report_payload(client_id=client["id"],
                                             period_start_date="2025-06-01",
                                             period_end_date="2026-05-31"),
            CM,
        ))
        assert report["status"] == "DRAFTING"
        # Spend-down plan starts DRAFT
        get_success_data(api.verify_entitlement(ent["id"], ADMIN))
        get_success_data(api.activate_client(client["id"], ADMIN))
        sp = create_spend_down_plan(client["id"])
        assert sp["status"] == "DRAFT"
        # Budget plan starts DRAFT
        plan = create_budget_plan_for_client(client["id"])
        assert plan["status"] == "DRAFT"
        # Disbursement starts REQUESTED
        d = create_disbursement(client["id"], account["id"], plan["id"],
                                amount_cents=5000)
        assert d["status"] == "REQUESTED"
        # Deposit starts RECEIVED
        dep = get_success_data(api.create_deposit(
            create_deposit_payload(account_id=account["id"], amount_cents=5000),
            FO,
        ))
        assert dep["status"] == "RECEIVED"
