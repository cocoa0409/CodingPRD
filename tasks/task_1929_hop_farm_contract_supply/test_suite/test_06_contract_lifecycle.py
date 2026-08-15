"""Contracts: initial state, suspend/reinstate loop, OCC-guarded amendments,
and term completion at crop-year rollover."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_contract_payload, create_amendment_payload,
    create_active_contract, run_allocation, find_allocation, set_clock,
    assert_contract,
)


class TestContractInitialState:
    def test_contract_created_in_draft(self, api, contract_manager_headers):
        """PRD §3.5: "A new contract opens in `DRAFT` with its
        `consecutive_shortfall_years` counter at 0." PRD §2.4: "`version`, an
        integer that starts at its initial value on creation and increments by
        exactly 1 on every mutation of that resource."

        Design: Corner/state_machines/contract_created_in_draft_initial_state
        """
        res = api.create_contract(create_contract_payload(), contract_manager_headers)
        contract = validate_success(res, 201)
        assert_contract(contract)
        assert contract["status"] == "DRAFT"
        assert contract["consecutive_shortfall_years"] == 0
        assert contract["version"] == 1
        fetched = validate_success(
            api.get_contract(contract["id"], contract_manager_headers), 200)
        assert fetched["status"] == "DRAFT", "immediate read agrees with create"


class TestSuspendReinstateLoop:
    def test_suspend_reinstate_cycle(self, api, contract_manager_headers):
        """PRD §3.5: "Activation moves a contract from `DRAFT` to `ACTIVE`.
        Suspension moves an `ACTIVE` contract to `SUSPENDED` ... Reinstatement
        moves `SUSPENDED` back to `ACTIVE`, and the suspend–reinstate loop may
        repeat as often as negotiations require." PRD §2.4: "every state
        transition ... moves the counter by one."

        Design: Corner/state_machines/contract_suspend_reinstate_cycle
        """
        contract = validate_success(api.create_contract(
            create_contract_payload(), contract_manager_headers), 201)
        activated = validate_success(
            api.activate_contract(contract["id"], contract_manager_headers), 200)
        assert activated["status"] == "ACTIVE"
        suspended = validate_success(
            api.suspend_contract(contract["id"], contract_manager_headers), 200)
        assert suspended["status"] == "SUSPENDED"
        reinstated = validate_success(
            api.reinstate_contract(contract["id"], contract_manager_headers), 200)
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["version"] == 4, (
            "create plus three transitions move the counter to 4")


class TestOccGuardedAmendment:
    def test_stale_amendment_rejected_then_fresh_succeeds(
            self, api, contract_manager_headers):
        """PRD §2.6: "If the contract's current `version` has advanced beyond
        that observed value — a contract may legitimately be amended repeatedly
        during volume and price renegotiation, and a writer working from a stale
        read would silently clobber an intervening amendment — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412), reducing the conflict to a
        deterministic stale-version rejection. A successful amendment applies the
        supplied changes and increments the contract's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected_then_fresh_succeeds
        """
        contract = validate_success(api.create_contract(
            create_contract_payload(), contract_manager_headers), 201)
        validate_success(api.activate_contract(contract["id"], contract_manager_headers), 200)
        current = validate_success(
            api.get_contract(contract["id"], contract_manager_headers), 200)
        live_version = current["version"]

        stale = api.amend_contract(
            contract["id"],
            create_amendment_payload(live_version - 1, annual_volume_lbs=1500),
            contract_manager_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api.amend_contract(
            contract["id"],
            create_amendment_payload(live_version, annual_volume_lbs=1500),
            contract_manager_headers), 200)
        assert fresh["annual_volume_lbs"] == 1500, "the supplied change is applied"
        assert fresh["version"] == live_version + 1, (
            "a successful amendment increments the contract's version by 1")


class TestRolloverCompletesExpiredContracts:
    def test_rollover_completes_expired_contract_and_cancels_projection(
            self, api, farm_manager_headers, contract_manager_headers):
        """PRD §3.9: "Every `ACTIVE` contract whose `term_end_year` is before the
        clock's year transitions to `COMPLETED`; its allocations in `PROJECTED`
        or `CONFIRMED` are cancelled, and each such confirmed allocation releases
        its reserved pellet lots from `RESERVED` back to `AVAILABLE`." The ops
        run returns "the `carried_over_lot_ids` and the `completed_contract_ids`
        it touched."

        Design: Corner/endpoints/rollover_completes_expired_contracts
        """
        contract = create_active_contract(term_start_year=2026, term_end_year=2026)
        run_allocation(crop_year=2026, variety="CASCADE")
        allocation = find_allocation(contract_id=contract["id"], crop_year=2026)
        assert allocation["status"] == "PROJECTED"

        set_clock("2027-01-15T00:00:00Z")
        rollover = validate_success(api.crop_year_rollover(farm_manager_headers), 200)
        assert contract["id"] in rollover["completed_contract_ids"]

        contract_after = validate_success(
            api.get_contract(contract["id"], contract_manager_headers), 200)
        assert contract_after["status"] == "COMPLETED"
        allocation_after = validate_success(
            api.get_allocation(allocation["id"], contract_manager_headers), 200)
        assert allocation_after["status"] == "CANCELLED"
