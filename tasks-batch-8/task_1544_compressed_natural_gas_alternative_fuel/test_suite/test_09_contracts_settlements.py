"""Supply contracts and monthly shortfall settlements: activation gates,
tiered penalties, settlement uniqueness/temporal guards, immutability, and
delivered-volume conservation (PRD §2.4, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    authorize_and_complete,
    create_active_contract,
    create_active_station,
    create_contract,
    create_fleet_account,
    create_fleet_card,
    get_account,
    make_fleet_driver_headers,
    set_clock,
    setup_fueling_ready,
    validate_error,
    validate_paginated,
    validate_success,
    void_session_ok,
)


class TestContractActivationDependencies:
    """Difficulty instance: contract_activate_requires_account_and_station_active
    (two tests)."""

    def _setup(self, api, network_operator_headers):
        env = create_active_station(
            station_name="Oscar", station_code="ST-OSCAR", access_mode="PRIVATE"
        )
        account = create_fleet_account(account_name="Oscar Logistics")
        contract = create_contract(
            account["id"], env["station"]["id"], committed_monthly_gge=100.0
        )
        return env, account, contract

    def test_suspended_account_blocks_activation(self, api, network_operator_headers):
        """PRD §3.8: "It requires the contract still be DRAFT, else
        `ERR_CONTRACT_NOT_DRAFT` (HTTP 409); the account ACTIVE, else
        `ERR_ACCOUNT_NOT_ACTIVE`; the station ACTIVE, else
        `ERR_STATION_NOT_ACTIVE`; and no other ACTIVE contract already covering
        the same account-station pair, else `ERR_CONTRACT_ALREADY_ACTIVE`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/contract_activate_requires_account_and_station_active
        """
        _env, account, contract = self._setup(api, network_operator_headers)
        validate_success(api.suspend_fleet_account(account["id"], network_operator_headers), 200)
        resp = api.activate_supply_contract(contract["id"], network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, 409)

    def test_suspended_station_blocks_then_both_active_succeed(
        self, api, network_operator_headers
    ):
        """PRD §3.8: "It requires the contract still be DRAFT, else
        `ERR_CONTRACT_NOT_DRAFT` (HTTP 409); the account ACTIVE, else
        `ERR_ACCOUNT_NOT_ACTIVE`; the station ACTIVE, else
        `ERR_STATION_NOT_ACTIVE`; and no other ACTIVE contract already covering
        the same account-station pair, else `ERR_CONTRACT_ALREADY_ACTIVE`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/contract_activate_requires_account_and_station_active
        """
        env, account, contract = self._setup(api, network_operator_headers)
        validate_success(api.suspend_station(env["station"]["id"], network_operator_headers), 200)
        resp = api.activate_supply_contract(contract["id"], network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_STATION_NOT_ACTIVE, 409)
        validate_success(api.resume_station(env["station"]["id"], network_operator_headers), 200)
        activated = validate_success(
            api.activate_supply_contract(contract["id"], network_operator_headers), 200
        )
        assert activated["status"] == "ACTIVE", (
            "both dependencies ACTIVE -> activation succeeds"
        )


class TestContractActivationGuards:
    def test_contract_activate_twice_rejected(self, api, network_operator_headers):
        """PRD §3.8: "It requires the contract still be DRAFT, else
        `ERR_CONTRACT_NOT_DRAFT` (HTTP 409); the account ACTIVE, else
        `ERR_ACCOUNT_NOT_ACTIVE`; the station ACTIVE, else
        `ERR_STATION_NOT_ACTIVE`; and no other ACTIVE contract already covering
        the same account-station pair, else `ERR_CONTRACT_ALREADY_ACTIVE`
        (HTTP 409)."

        Design: Corner/validations/contract_activate_twice_rejected
        """
        env = create_active_station(
            station_name="CTw", station_code="ST-CTW", access_mode="PRIVATE"
        )
        account = create_fleet_account(account_name="CTw Co", credit_limit_cents=100000)
        contract = create_contract(
            account["id"], env["station"]["id"], committed_monthly_gge=50.0,
            start_month="2026-08", end_month="2026-12",
        )
        validate_success(
            api.activate_supply_contract(contract["id"], network_operator_headers), 200
        )
        resp = api.activate_supply_contract(contract["id"], network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_DRAFT, 409)

    def test_second_active_contract_same_pair_rejected(self, api, network_operator_headers):
        """PRD §3.8: "It requires the contract still be DRAFT, else
        `ERR_CONTRACT_NOT_DRAFT` (HTTP 409); the account ACTIVE, else
        `ERR_ACCOUNT_NOT_ACTIVE`; the station ACTIVE, else
        `ERR_STATION_NOT_ACTIVE`; and no other ACTIVE contract already covering
        the same account-station pair, else `ERR_CONTRACT_ALREADY_ACTIVE`
        (HTTP 409)."

        Design: Corner/validations/second_active_contract_same_pair_rejected
        """
        env = create_active_station(
            station_name="C2nd", station_code="ST-C2ND", access_mode="PRIVATE"
        )
        account = create_fleet_account(account_name="C2nd Co", credit_limit_cents=100000)
        c1 = create_contract(
            account["id"], env["station"]["id"], committed_monthly_gge=50.0,
            start_month="2026-08", end_month="2026-12",
        )
        validate_success(api.activate_supply_contract(c1["id"], network_operator_headers), 200)
        c2 = create_contract(
            account["id"], env["station"]["id"], committed_monthly_gge=80.0,
            contract_price_per_gge_cents=265, shortfall_tier1_rate_cents=25,
            shortfall_tier2_rate_cents=50, start_month="2026-08", end_month="2026-12",
        )
        resp = api.activate_supply_contract(c2["id"], network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_ALREADY_ACTIVE, 409)
        after = validate_success(
            api.get_supply_contract(c2["id"], network_operator_headers), 200
        )
        assert after["status"] == "DRAFT"


class TestShortfallTieredPenalty:
    """Difficulty instance: shortfall_tiered_penalty_straddling_tier_cap
    (two tests)."""

    def _setup_and_settle(self, api, network_operator_headers):
        env = setup_fueling_ready(
            station_name="Gamma", station_code="ST-GAMMA", access_mode="PRIVATE"
        )
        contract = create_active_contract(
            env["account"]["id"],
            env["station"]["id"],
            committed_monthly_gge=100.0,
            contract_price_per_gge_cents=275,
            shortfall_tier1_rate_cents=30,
            shortfall_tier2_rate_cents=55,
            start_month="2026-07",
            end_month="2026-12",
        )
        set_clock("2026-08-05T12:00:00Z")
        # Contract price 275 applies to both sessions (contract overrides).
        # 112.948 kg / 2.567 = 43.9999... -> 44.000 GGE settled each.
        authorize_and_complete(
            env["card"]["id"], env["dispenser"]["id"], "CR-S1", 112.948, 50.0
        )
        authorize_and_complete(
            env["card"]["id"], env["dispenser"]["id"], "CR-S2", 112.948, 50.0
        )
        set_clock("2026-09-01T00:00:00Z")
        settlement = validate_success(
            api.settle_month(contract["id"], {"month": "2026-08"}, network_operator_headers),
            201,
        )
        return env, contract, settlement

    def test_shortfall_straddling_tier_cap_penalty(self, api, network_operator_headers):
        """PRD §3.8: "Settlement then computes, for the settled month:
        `delivered_gge`, the sum of `settled_gge` over the contract account's
        non-voided private sessions at the contract station in COMPLETED or
        SETTLED status whose `completed_at` falls from midnight UTC on the
        first day of that month inclusive to midnight UTC on the first day of
        the following month exclusive; `shortfall_gge`, the committed volume
        minus the delivered volume, floored at zero; and a two-tier penalty.
        The tier cap is one-tenth of `committed_monthly_gge`; the portion of
        the shortfall up to that cap is charged at `shortfall_tier1_rate_cents`
        per GGE, and any remaining shortfall beyond the cap is charged at
        `shortfall_tier2_rate_cents` per GGE; the sum is rounded half-up to a
        whole cent and stored as `penalty_cents`."

        Design: Difficulty/combinatorial_formula/shortfall_tiered_penalty_straddling_tier_cap
        """
        _env, _contract, settlement = self._setup_and_settle(api, network_operator_headers)
        assert settlement["delivered_gge"] == pytest.approx(88.000, abs=1e-9)
        assert settlement["shortfall_gge"] == pytest.approx(12.000, abs=1e-9)
        # min(12,10)*30 + max(0,12-10)*55 = 300 + 110
        assert settlement["penalty_cents"] == 410

    def test_penalty_posts_to_account_balance(self, api, network_operator_headers):
        """PRD §3.8: "The penalty posts to the fleet account:
        `outstanding_balance_cents` rises by `penalty_cents` and the account's
        `version` increments by one."
        PRD §3.4: "First, for a private session only: if an ACTIVE supply
        contract covers the session's account and station and the current
        calendar month falls between the contract's `start_month` and
        `end_month` inclusive, the price is the contract's
        `contract_price_per_gge_cents` and resolution stops — a contract
        overrides all policy pricing."

        Design: Difficulty/combinatorial_formula/shortfall_tiered_penalty_straddling_tier_cap
        """
        env, _contract, _settlement = self._setup_and_settle(api, network_operator_headers)
        # Two session totals at contract price 275: 2 x (44.000 x 275) = 24200,
        # plus the 410 penalty.
        assert get_account(env["account"]["id"])["outstanding_balance_cents"] == 24610


class TestDeliveredVolumeConservation:
    """Difficulty instance: complete_void_delivered_volume_conservation
    (two tests)."""

    def _setup_and_settle(self, api, network_operator_headers, station_manager_headers):
        env = setup_fueling_ready(
            station_name="Sierra", station_code="ST-SIERRA", access_mode="PRIVATE"
        )
        contract = create_active_contract(
            env["account"]["id"],
            env["station"]["id"],
            committed_monthly_gge=1000.0,
            contract_price_per_gge_cents=275,
            shortfall_tier1_rate_cents=30,
            shortfall_tier2_rate_cents=55,
            start_month="2026-07",
            end_month="2026-12",
        )
        set_clock("2026-08-05T12:00:00Z")
        completed = authorize_and_complete(
            env["card"]["id"], env["dispenser"]["id"], "CR-W1", 20.536, 20.0
        )
        assert completed["settled_gge"] == pytest.approx(8.000, abs=1e-9), (
            "the session did complete before the void"
        )
        voided = void_session_ok(completed["id"], station_manager_headers, "MANAGER_VOID")
        assert voided["status"] == "VOIDED"
        set_clock("2026-09-01T00:00:00Z")
        settlement = validate_success(
            api.settle_month(contract["id"], {"month": "2026-08"}, network_operator_headers),
            201,
        )
        return env, settlement

    def test_voided_completion_contributes_no_delivered_volume(
        self, api, network_operator_headers, station_manager_headers
    ):
        """PRD §3.8: "Settlement then computes, for the settled month:
        `delivered_gge`, the sum of `settled_gge` over the contract account's
        non-voided private sessions at the contract station in COMPLETED or
        SETTLED status whose `completed_at` falls from midnight UTC on the
        first day of that month inclusive to midnight UTC on the first day of
        the following month exclusive; `shortfall_gge`, the committed volume
        minus the delivered volume, floored at zero; and a two-tier penalty."

        Design: Difficulty/compensating_invariant/complete_void_delivered_volume_conservation
        """
        _env, settlement = self._setup_and_settle(
            api, network_operator_headers, station_manager_headers
        )
        assert settlement["delivered_gge"] == pytest.approx(0.000, abs=1e-9), (
            "void compensation reached the settlement aggregate"
        )
        assert settlement["shortfall_gge"] == pytest.approx(1000.000, abs=1e-9)
        # min(1000,100)*30 + max(0,1000-100)*55 = 3000 + 49500
        assert settlement["penalty_cents"] == 52500

    def test_penalty_posts_to_balance_after_void_refund(
        self, api, network_operator_headers, station_manager_headers
    ):
        """PRD §3.8: "The penalty posts to the fleet account:
        `outstanding_balance_cents` rises by `penalty_cents` and the account's
        `version` increments by one."
        PRD §3.4: "Voiding a COMPLETED private session refunds it: the balance
        falls by `total_amount_cents` — the hold having already been netted out
        at completion — the account `version` increments, and the card's
        `current_day_gge` falls by `settled_gge`, never below zero."

        Design: Difficulty/compensating_invariant/complete_void_delivered_volume_conservation
        """
        env, _settlement = self._setup_and_settle(
            api, network_operator_headers, station_manager_headers
        )
        # Balance conserved at 0 by the void, then +52500 penalty.
        assert get_account(env["account"]["id"])["outstanding_balance_cents"] == 52500


class TestSettleMonthGuards:
    def test_settle_current_month_rejected(self, api, network_operator_headers):
        """PRD §3.8: "The month must be strictly before the current logical
        month, else `ERR_MONTH_NOT_CLOSED` (HTTP 409); it must lie within the
        contract's span from `start_month` through `end_month` inclusive, else
        `ERR_MONTH_OUT_OF_CONTRACT` (HTTP 409); and no settlement may already
        exist for that contract and month, else `ERR_MONTH_ALREADY_SETTLED`
        (HTTP 409)."

        Design: Corner/validations/settle_current_month_rejected
        """
        set_clock("2026-08-15T00:00:00Z")
        env = create_active_station(
            station_name="Arrears", station_code="ST-ARR", access_mode="PRIVATE"
        )
        account = create_fleet_account(account_name="Arr Co", credit_limit_cents=100000)
        contract = create_active_contract(
            account["id"], env["station"]["id"], committed_monthly_gge=50.0
        )
        resp = api.settle_month(contract["id"], {"month": "2026-08"}, network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_MONTH_NOT_CLOSED, 409)

    def test_settle_month_twice_rejected(self, api, network_operator_headers):
        """PRD §3.8: "The month must be strictly before the current logical
        month, else `ERR_MONTH_NOT_CLOSED` (HTTP 409); it must lie within the
        contract's span from `start_month` through `end_month` inclusive, else
        `ERR_MONTH_OUT_OF_CONTRACT` (HTTP 409); and no settlement may already
        exist for that contract and month, else `ERR_MONTH_ALREADY_SETTLED`
        (HTTP 409)."

        Design: Corner/validations/settle_month_twice_rejected
        """
        env = create_active_station(
            station_name="Twice", station_code="ST-TWICE", access_mode="PRIVATE"
        )
        account = create_fleet_account(account_name="Twice Co", credit_limit_cents=100000)
        contract = create_active_contract(
            account["id"], env["station"]["id"], committed_monthly_gge=100.0,
            start_month="2026-06", end_month="2026-12",
        )
        settlement = validate_success(
            api.settle_month(contract["id"], {"month": "2026-07"}, network_operator_headers),
            201,
        )
        # delivered 0, shortfall 100.000, penalty 10x30 + 90x55 = 5250.
        assert settlement["penalty_cents"] == 5250
        resp = api.settle_month(contract["id"], {"month": "2026-07"}, network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_MONTH_ALREADY_SETTLED, 409)

    def test_settle_month_outside_contract_span_rejected(self, api, network_operator_headers):
        """PRD §3.8: "The month must be strictly before the current logical
        month, else `ERR_MONTH_NOT_CLOSED` (HTTP 409); it must lie within the
        contract's span from `start_month` through `end_month` inclusive, else
        `ERR_MONTH_OUT_OF_CONTRACT` (HTTP 409); and no settlement may already
        exist for that contract and month, else `ERR_MONTH_ALREADY_SETTLED`
        (HTTP 409)."

        Design: Corner/validations/settle_month_outside_contract_span_rejected
        """
        env = create_active_station(
            station_name="OSpan", station_code="ST-OSPAN", access_mode="PRIVATE"
        )
        account = create_fleet_account(account_name="OSpan Co", credit_limit_cents=100000)
        contract = create_active_contract(
            account["id"], env["station"]["id"], committed_monthly_gge=50.0,
            start_month="2026-06", end_month="2026-12",
        )
        # Default clock 2026-08-01: January 2026 is closed but outside the span.
        resp = api.settle_month(contract["id"], {"month": "2026-01"}, network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_MONTH_OUT_OF_CONTRACT, 409)


class TestSettlementImmutability:
    def test_monthly_settlement_immutable_no_version_field(self, api, network_operator_headers):
        """PRD §2.4: "Two resource types are deliberately thinner: a
        calibration record and a monthly settlement are immutable once created,
        so each carries only `id` and `created_at` — both `updated_at` and
        `version` are absent from them."
        PRD §3.8: "The result is persisted as an immutable MonthlySettlement
        carrying `supply_contract_id`, `month`, `delivered_gge`,
        `shortfall_gge`, `penalty_cents`, and a `settled_at` timestamp — and,
        being immutable, only `id` and `created_at` among the common fields."

        Design: Corner/entities/monthly_settlement_immutable_no_version_field
        """
        env = create_active_station(
            station_name="Setl", station_code="ST-SETL", access_mode="PRIVATE"
        )
        account = create_fleet_account(account_name="Settle Co", credit_limit_cents=100000)
        contract = create_active_contract(
            account["id"], env["station"]["id"], committed_monthly_gge=100.0,
            start_month="2026-06", end_month="2026-12",
        )
        settlement = validate_success(
            api.settle_month(contract["id"], {"month": "2026-07"}, network_operator_headers),
            201,
        )
        fetched = validate_success(
            api.get_monthly_settlement(settlement["id"], network_operator_headers), 200
        )
        assert fetched["supply_contract_id"] == contract["id"]
        assert fetched["month"] == "2026-07"
        assert fetched["delivered_gge"] == pytest.approx(0.000, abs=1e-9)
        assert fetched["shortfall_gge"] == pytest.approx(100.000, abs=1e-9)
        assert fetched["penalty_cents"] == 5250
        assert "version" not in fetched
        assert "updated_at" not in fetched


class TestSettlementReverseLookup:
    def test_settlement_reverse_lookup_by_contract(self, api, network_operator_headers):
        """PRD §3.8: "Settlements list with optional `supply_contract_id` and
        `month` filters, and contracts list with `fleet_account_id`,
        `station_id`, and `status` filters."

        Design: Corner/endpoints/settlement_reverse_lookup_by_contract
        """
        env = create_active_station(
            station_name="Rev", station_code="ST-REV", access_mode="PRIVATE"
        )
        account = create_fleet_account(account_name="Rev Co", credit_limit_cents=100000)
        contract = create_active_contract(
            account["id"], env["station"]["id"], committed_monthly_gge=100.0,
            start_month="2026-06", end_month="2026-12",
        )
        settlement = validate_success(
            api.settle_month(contract["id"], {"month": "2026-07"}, network_operator_headers),
            201,
        )
        rows, meta = validate_paginated(
            api.list_monthly_settlements(
                network_operator_headers, params={"supply_contract_id": contract["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == settlement["id"]
