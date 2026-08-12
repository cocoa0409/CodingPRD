"""Deposits, bonds, ledger: post gates, resource cascade, bond coverage
boundary, window conflict, utilization floor, ledger append-only, derived
field reconciliation, clock-driven lapse/expiry."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId, make_admin_headers, make_financial_officer_headers,
    make_case_manager_headers,
    create_client, create_active_client, create_client_with_verified_entitlement,
    create_account, create_active_bond, create_and_post_deposit,
    create_budget_plan_for_client, create_approved_budget_plan,
    create_disbursement, create_approved_disbursement,
    create_released_disbursement, set_clock,
    create_deposit_payload, create_surety_bond_payload,
    create_entitlement_payload, create_granted_court_order,
    setup_funded_release_ready,
)
from test_helpers.api_client import api_client as api

ADMIN = make_admin_headers()
FO = make_financial_officer_headers()
CM = make_case_manager_headers()


class TestDepositPostGates:
    def test_deposit_post_to_frozen_account_rejected(self, api):
        """PRD §3.3: "Posting requires the destination account to be `OPEN` —
        posting into a frozen or closed account fails with
        `ERR_ACCOUNT_NOT_OPEN` — and it respects bond coverage: if an `ACTIVE`
        surety bond exists, the organization-wide funds under management after
        the post must not exceed that bond's `coverage_amount_cents`, or the
        post fails with `ERR_BOND_COVERAGE_EXCEEDED`; when no `ACTIVE` bond
        exists, posts are unbounded."

        Design: Corner/validations/deposit_post_to_frozen_account_rejected
        """
        client, _ = create_active_client()
        acct = create_account(client["id"])
        dep = get_success_data(api.create_deposit(
            create_deposit_payload(account_id=acct["id"], amount_cents=10000), FO
        ))
        get_success_data(api.suspend_client(client["id"], ADMIN))
        resp = api.post_deposit(dep["id"], FO)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_OPEN)

    def test_deposit_entitlement_client_mismatch(self, api):
        """PRD §3.3: "When the source is an SSA benefit, the optional
        `entitlement_id` links the deposit to the award; when present, the
        entitlement must belong to the same client as the destination account,
        a coherence enforced both at recording and again at posting, with
        violations rejected as `ERR_ENTITLEMENT_ACCOUNT_MISMATCH`."

        Design: Corner/validations/deposit_entitlement_client_mismatch
        """
        client_a = create_client(legal_name="Mismatch A")
        client_b = create_client(legal_name="Mismatch B")
        acct_a = create_account(client_a["id"])
        ent_b = get_success_data(api.create_entitlement(
            create_entitlement_payload(client_id=client_b["id"]), ADMIN
        ))
        resp = api.create_deposit(
            {
                "account_id": acct_a["id"], "source": "SSA_BENEFIT",
                "amount_cents": 80000, "received_date": "2026-06-02",
                "entitlement_id": ent_b["id"],
            },
            FO,
        )
        validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_ACCOUNT_MISMATCH)


class TestBondCoverage:
    def test_bond_coverage_exact_boundary(self, api):
        """PRD §3.3: "if an `ACTIVE` surety bond exists, the organization-wide
        funds under management after the post must not exceed that bond's
        `coverage_amount_cents`, or the post fails with
        `ERR_BOND_COVERAGE_EXCEEDED`; when no `ACTIVE` bond exists, posts are
        unbounded."

        Design: Difficulty/boundary_precision_check/bond_coverage_exact_boundary
        """
        set_clock("2026-06-05T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"])
        bond = create_active_bond(coverage_amount_cents=300000)
        create_and_post_deposit(acct["id"], 200000, received_date="2026-06-02")
        db = get_success_data(api.create_deposit(
            create_deposit_payload(account_id=acct["id"], amount_cents=100000,
                                   received_date="2026-06-03"), FO
        ))
        dc = get_success_data(api.create_deposit(
            create_deposit_payload(account_id=acct["id"], amount_cents=1,
                                   received_date="2026-06-04"), FO
        ))
        # Landing exactly at coverage succeeds (<= semantics).
        db_after = get_success_data(api.post_deposit(db["id"], FO))
        assert db_after["status"] == "POSTED"
        # One cent over is rejected.
        resp = api.post_deposit(dc["id"], FO)
        validate_error(resp, ApiErrorId.ERR_BOND_COVERAGE_EXCEEDED)
        bond_after = get_success_data(api.get_surety_bond(bond["id"], ADMIN))
        assert bond_after["funds_under_management_cents"] == 300000
        assert bond_after["utilization_bps"] == 10000

    def test_bond_coverage_one_cent_under_boundary(self, api):
        """PRD §3.3: "if an `ACTIVE` surety bond exists, the organization-wide
        funds under management after the post must not exceed that bond's
        `coverage_amount_cents`, or the post fails with
        `ERR_BOND_COVERAGE_EXCEEDED`; when no `ACTIVE` bond exists, posts are
        unbounded."

        Design: Difficulty/boundary_precision_check/bond_coverage_exact_boundary
        """
        set_clock("2026-06-05T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"])
        bond = create_active_bond(coverage_amount_cents=300000)
        create_and_post_deposit(acct["id"], 200000, received_date="2026-06-02")
        # 99999 lands at 299999 (one cent under coverage) and succeeds.
        under = create_and_post_deposit(acct["id"], 99999, received_date="2026-06-03")
        assert under["status"] == "POSTED"
        bond_after = get_success_data(api.get_surety_bond(bond["id"], ADMIN))
        assert bond_after["funds_under_management_cents"] == 299999
        # 2 more cents would exceed the 300000 coverage: rejected.
        over = get_success_data(api.create_deposit(
            create_deposit_payload(account_id=acct["id"], amount_cents=2,
                                   received_date="2026-06-04"), FO
        ))
        resp = api.post_deposit(over["id"], FO)
        validate_error(resp, ApiErrorId.ERR_BOND_COVERAGE_EXCEEDED)

    def test_bond_window_conflict_and_adjacency(self, api):
        """PRD §3.7: "Activation moves it `PENDING` → `ACTIVE` and enforces
        single coverage: the activating bond's half-open window must not
        overlap the window of any other `ACTIVE` bond — adjacency is allowed,
        and `PENDING` bonds never block activation — with conflicts rejected as
        `ERR_BOND_WINDOW_CONFLICT`."

        Design: Corner/validations/bond_window_conflict_and_adjacency
        """
        b1 = get_success_data(api.create_surety_bond(
            create_surety_bond_payload(
                coverage_amount_cents=1000000,
                coverage_start_date="2026-01-01", coverage_end_date="2026-07-01",
                premium_paid_through_date="2026-06-30",
            ), ADMIN))
        get_success_data(api.activate_surety_bond(b1["id"], ADMIN))
        b2 = get_success_data(api.create_surety_bond(
            create_surety_bond_payload(
                coverage_amount_cents=1000000,
                coverage_start_date="2026-06-01", coverage_end_date="2026-12-01",
                premium_paid_through_date="2026-12-01",
            ), ADMIN))
        b3 = get_success_data(api.create_surety_bond(
            create_surety_bond_payload(
                coverage_amount_cents=1000000,
                coverage_start_date="2026-07-01", coverage_end_date="2027-01-01",
                premium_paid_through_date="2026-12-31",
            ), ADMIN))
        resp = api.activate_surety_bond(b2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_BOND_WINDOW_CONFLICT)
        b3_after = get_success_data(api.activate_surety_bond(b3["id"], ADMIN))
        assert b3_after["status"] == "ACTIVE"

    def test_bond_utilization_bps_floor(self, api):
        """PRD §3.7: "Two figures are always derivable on a bond:
        `funds_under_management_cents`, the sum of `balance_cents` over every
        trust account organization-wide in `OPEN` or `FROZEN` status (`CLOSED`
        accounts are excluded), recomputed on every balance-affecting mutation;
        and `utilization_bps`, the floor of `funds_under_management_cents`
        multiplied by ten thousand and divided by `coverage_amount_cents`,
        where ten thousand basis points marks full utilization."

        Design: Corner/calculations/bond_utilization_bps_floor
        """
        set_clock("2026-06-05T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"])
        bond = create_active_bond(coverage_amount_cents=400000)
        create_and_post_deposit(acct["id"], 150000, received_date="2026-06-02")
        bond_after = get_success_data(api.get_surety_bond(bond["id"], ADMIN))
        assert bond_after["funds_under_management_cents"] == 150000
        assert bond_after["utilization_bps"] == 3750


class TestResourceCascade:
    def test_deposit_post_triggers_resource_cascade(self, api):
        """PRD §3.3: "The recompute chain has a third, conditional link. When
        the client is Medicaid-enrolled and the refreshed
        `countable_resources_cents` has crossed strictly above
        `medicaid_resource_limit_cents`, and no spend-down plan in `DRAFT` or
        `ACTIVE` already exists for that client for the current logical-clock
        month, the system auto-creates a spend-down plan: status `DRAFT`,
        `auto_created` set true, an empty `entries` list, `target_month` set to
        the current clock month, and `provisional_excess_cents` computed by the
        provisional formula of §3.9."

        Design: Difficulty/transitive_cascade/deposit_post_triggers_resource_cascade
        """
        set_clock("2026-06-05T00:00:00Z")
        client, ent = create_active_client(medicaid_enrolled=True)
        acct = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(acct["id"], 150000, received_date="2026-06-02")
        plans_before, _ = validate_paginated(
            api.list_spend_down_plans(CM, params={"client_id": client["id"]})
        )
        assert plans_before == []
        create_and_post_deposit(acct["id"], 80000, source="SSA_BENEFIT",
                                received_date="2026-06-05", entitlement_id=ent["id"])
        acct_after = get_success_data(api.get_trust_account(acct["id"], FO))
        assert acct_after["balance_cents"] == 230000
        client_after = get_success_data(api.get_client(client["id"], ADMIN))
        assert client_after["countable_resources_cents"] == 230000
        assert client_after["medicaid_at_risk"] is True
        plans_after, _ = validate_paginated(
            api.list_spend_down_plans(CM, params={"client_id": client["id"]})
        )
        assert len(plans_after) == 1
        auto = plans_after[0]
        assert auto["auto_created"] is True
        assert auto["status"] == "DRAFT"
        assert auto["target_month"] == "2026-06"
        assert auto["provisional_excess_cents"] == 110000

    def test_deposit_post_below_threshold_does_not_auto_create(self, api):
        """PRD §3.3: "The recompute chain has a third, conditional link. When
        the client is Medicaid-enrolled and the refreshed
        `countable_resources_cents` has crossed strictly above
        `medicaid_resource_limit_cents`, and no spend-down plan in `DRAFT` or
        `ACTIVE` already exists for that client for the current logical-clock
        month, the system auto-creates a spend-down plan: status `DRAFT`,
        `auto_created` set true, an empty `entries` list, `target_month` set to
        the current clock month, and `provisional_excess_cents` computed by the
        provisional formula of §3.9."

        Design: Difficulty/transitive_cascade/deposit_post_triggers_resource_cascade
        """
        set_clock("2026-06-05T00:00:00Z")
        client, ent = create_active_client(medicaid_enrolled=True)
        acct = create_account(client["id"])
        create_active_bond()
        # 150000 <= 200000: no auto-create on this post.
        create_and_post_deposit(acct["id"], 150000, received_date="2026-06-02")
        plans, _ = validate_paginated(
            api.list_spend_down_plans(CM, params={"client_id": client["id"]})
        )
        assert plans == []
        client_after = get_success_data(api.get_client(client["id"], ADMIN))
        assert client_after["countable_resources_cents"] == 150000
        assert client_after["medicaid_at_risk"] is False

    def test_derived_fields_reconcile_on_release_and_return(self, api):
        """PRD §2.6: "Because balances are derived, every balance-affecting
        mutation also refreshes the client-level rollups (`total_funds_cents`,
        `countable_resources_cents`) and the organization-wide bond rollup
        (`funds_under_management_cents`), as detailed in the workflows of §3."

        Design: Corner/cross_cutting_layers/derived_fields_reconcile_on_release_and_return
        """
        set_clock("2026-06-10T00:00:00Z")
        env = setup_funded_release_ready(deposit_amount=50000, disbursement_amount=20000)
        client = env["client"]; bond = env["bond"]; d = env["disbursement"]
        get_success_data(api.release_disbursement(d["id"], FO))
        client_mid = get_success_data(api.get_client(client["id"], ADMIN))
        bond_mid = get_success_data(api.get_surety_bond(bond["id"], ADMIN))
        assert client_mid["total_funds_cents"] == 30000
        assert client_mid["countable_resources_cents"] == 30000
        assert bond_mid["funds_under_management_cents"] == 30000
        get_success_data(api.return_disbursement(d["id"], FO))
        client_end = get_success_data(api.get_client(client["id"], ADMIN))
        bond_end = get_success_data(api.get_surety_bond(bond["id"], ADMIN))
        assert client_end["total_funds_cents"] == 50000
        assert client_end["countable_resources_cents"] == 50000
        assert bond_end["funds_under_management_cents"] == 50000

    def test_dedicated_account_excluded_from_countable_resources(self, api):
        """PRD §3.1: "Three figures are always derivable on read:
        `total_funds_cents`, the sum of `balance_cents` over all of the
        client's accounts in `OPEN` or `FROZEN` status regardless of account
        type; `countable_resources_cents`, the same sum restricted to
        `OPERATING` and `RESTRICTED` accounts — `DEDICATED` accounts are
        excluded per SSA countable-resource rules; and `medicaid_at_risk`,
        which is true exactly when the client is Medicaid-enrolled and
        `countable_resources_cents` is strictly greater than
        `medicaid_resource_limit_cents` — equality with the ceiling is not at
        risk."

        Design: Corner/entities/dedicated_account_excluded_from_countable_resources
        """
        set_clock("2026-06-05T00:00:00Z")
        client, ent = create_active_client(medicaid_enrolled=True)
        acct_op = create_account(client["id"], account_type="OPERATING")
        acct_ded = create_account(client["id"], account_type="DEDICATED")
        create_active_bond()
        create_and_post_deposit(acct_op["id"], 150000, received_date="2026-06-02")
        create_and_post_deposit(acct_ded["id"], 80000, source="SSA_BENEFIT",
                                received_date="2026-06-02", entitlement_id=ent["id"])
        client_after = get_success_data(api.get_client(client["id"], ADMIN))
        assert client_after["total_funds_cents"] == 230000
        assert client_after["countable_resources_cents"] == 150000
        assert client_after["medicaid_at_risk"] is False


class TestLedgerImmutability:
    def test_ledger_entry_immutability_and_append_only(self, api):
        """PRD §2.5: "The one exception is the ledger entry: ledger entries
        carry only `id` and `created_at` — they are immutable once written, so
        both `updated_at` and `version` are absent from them."
        PRD §2.6: "Entries are append-only, are strictly serialized per account
        in request order, and each records the running `balance_after_cents` of
        its account immediately after itself in chronological replay order."
        PRD §3.2: "Operators read an account's ledger chronologically, oldest
        entry first, optionally narrowed by `entry_type`."

        Design: Corner/entities/ledger_entry_immutability_and_append_only
        """
        set_clock("2026-06-05T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(acct["id"], 40000, received_date="2026-06-02")
        create_and_post_deposit(acct["id"], 10000, received_date="2026-06-03")
        rows, _ = validate_paginated(api.get_account_ledger(acct["id"], FO))
        assert len(rows) == 2
        assert rows[0]["entry_type"] == "DEPOSIT_POSTED"
        assert rows[0]["balance_after_cents"] == 40000
        assert rows[1]["entry_type"] == "DEPOSIT_POSTED"
        assert rows[1]["balance_after_cents"] == 50000
        for row in rows:
            assert "updated_at" not in row
            assert "version" not in row
            assert "id" in row and "created_at" in row


class TestClockDrivenLapse:
    def test_court_order_auto_expiry_via_clock(self, api):
        """PRD §3.7: "Advancing the logical clock past an order's `expiry_date`
        moves it to `EXPIRED` whether it is still `PETITIONED` or already
        `GRANTED`."
        PRD §3.6: "First, for a `RESTRICTED` source account, the named court
        order must be grantable: the `court_order_id` must be present, the
        order must be `GRANTED`, it must belong to the disbursement's client,
        its `order_type` must be `RESTRICTED_WITHDRAWAL`, and the logical clock
        date must be on or before its `expiry_date` — any failure is
        `ERR_COURT_ORDER_NOT_GRANTABLE`."

        Design: Corner/cross_cutting_layers/court_order_auto_expiry_via_clock
        """
        set_clock("2026-06-25T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"], account_type="RESTRICTED")
        create_active_bond()
        create_and_post_deposit(acct["id"], 100000, received_date="2026-06-20")
        plan = create_approved_budget_plan(client["id"], source_benefit_cents=100000)
        order = create_granted_court_order(client["id"], amount_limit_cents=50000,
                                           expiry_date="2026-06-30")
        d = create_approved_disbursement(
            client["id"], acct["id"], plan["id"], amount_cents=20000,
            payee_name="Expiry Payee", court_order_id=order["id"],
            scheduled_release_date="2026-06-28",
        )
        set_clock("2026-07-01T00:00:00Z")
        order_after = get_success_data(api.get_court_order(order["id"], ADMIN))
        assert order_after["status"] == "EXPIRED"
        resp = api.release_disbursement(d["id"], FO)
        validate_error(resp, ApiErrorId.ERR_COURT_ORDER_NOT_GRANTABLE)

    def test_bond_auto_lapse_via_clock(self, api):
        """PRD §3.7: "Bonds lapse by the clock: advancing the logical clock to
        a date on or after `coverage_end_date`, or to any date after
        `premium_paid_through_date`, moves an `ACTIVE` bond to `LAPSED`."
        PRD §3.6: "Last, an `ACTIVE` surety bond must exist, failing with
        `ERR_NO_ACTIVE_BOND`."

        Design: Corner/cross_cutting_layers/bond_auto_lapse_via_clock
        """
        set_clock("2026-06-25T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"])
        bond = create_active_bond(
            coverage_amount_cents=1000000,
            coverage_start_date="2026-01-01", coverage_end_date="2026-07-01",
            premium_paid_through_date="2026-12-31",
        )
        create_and_post_deposit(acct["id"], 50000, received_date="2026-06-20")
        plan = create_approved_budget_plan(client["id"], period_month="2026-07",
                                           source_benefit_cents=100000)
        d = create_approved_disbursement(
            client["id"], acct["id"], plan["id"], amount_cents=10000,
            payee_name="Lapse Payee", scheduled_release_date="2026-07-02",
        )
        set_clock("2026-07-01T00:00:00Z")
        bond_after = get_success_data(api.get_surety_bond(bond["id"], ADMIN))
        assert bond_after["status"] == "LAPSED"
        resp = api.release_disbursement(d["id"], FO)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_BOND)
