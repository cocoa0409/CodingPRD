"""Upstream supply: supply-contract lifecycle and the rail-shipment conveyor."""
from test_helpers import (
    SUPPLY_ADMIN,
    ApiErrorId,
    activate_supply_contract,
    advance_shipment,
    api_client,
    assert_rail_shipment,
    assert_supply_contract,
    create_supply_contract,
    create_terminal,
    get_success_data,
    tender_shipment,
    validate_error,
)


class TestRailConveyorLegality:

    def test_shipment_invalid_jump_tendered_to_unloaded(self):
        """PRD section 3.2: "Rail shipments advance along a strict conveyor:
        from `TENDERED` to `IN_TRANSIT`, from `IN_TRANSIT` to `ARRIVED`, and
        from `ARRIVED` to `UNLOADED`, each step requested by the `SupplyAdmin`
        naming a `to_state`. Any jump outside the legal edges is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/shipment_invalid_jump_tendered_to_unloaded
        """
        term = create_terminal(name="T-M4")
        contract = create_supply_contract(term["id"])
        activate_supply_contract(contract["id"])
        ship = tender_shipment(contract["id"], volume_gal=200_000,
                               railcar_count=10)

        resp = api_client.transition_rail_shipment(
            ship["id"], {"to_state": "UNLOADED"}, SUPPLY_ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(api_client.get_rail_shipment(ship["id"],
                                                              SUPPLY_ADMIN))
        assert after["status"] == "TENDERED", \
            "a rejected jump leaves the shipment in its from-state"
        term_after = get_success_data(api_client.get_terminal(term["id"],
                                                              SUPPLY_ADMIN))
        assert term_after["on_hand_gal"] == 0, \
            "no inventory may be posted by a rejected unload"

    def test_shipment_outside_receipt_window_rejected(self):
        """PRD section 3.2: "Against a contract, the `SupplyAdmin` tenders rail
        shipments with a `supply_contract_id`, a strictly positive manifest
        `volume_gal`, a strictly positive `railcar_count`, and a
        `scheduled_arrival_date` that must fall inside the contract's receipt
        window — an arrival date outside it is rejected with
        `ERR_SHIPMENT_WINDOW_VIOLATION`."

        Design: Corner/validations/shipment_outside_receipt_window_rejected
        """
        term = create_terminal(name="T-V6")
        contract = create_supply_contract(term["id"])
        activate_supply_contract(contract["id"])

        resp = api_client.create_rail_shipment(
            {"supply_contract_id": contract["id"], "volume_gal": 100_000,
             "railcar_count": 5, "scheduled_arrival_date": "2026-10-05"},
            SUPPLY_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_WINDOW_VIOLATION)


class TestUnloadGateAndCompletion:

    def _setup_arrived_then_cancel(self):
        """Shipment ARRIVED under an ACTIVE contract, then contract cancelled.

        Cancellation leaves ARRIVED shipments in place (PRD 3.2: "shipments
        already `ARRIVED` or `UNLOADED` are unaffected").
        """
        term = create_terminal(name="T-X2")
        contract = create_supply_contract(term["id"])
        activate_supply_contract(contract["id"])
        ship = tender_shipment(contract["id"], volume_gal=200_000,
                               railcar_count=10)
        advance_shipment(ship["id"], "IN_TRANSIT")
        advance_shipment(ship["id"], "ARRIVED")
        api_client.cancel_supply_contract(contract["id"], SUPPLY_ADMIN)
        return term, contract, ship

    def test_shipment_unload_requires_contract_active_rejected(self):
        """PRD section 3.2: "Unloading requires the contract to be `ACTIVE` —
        otherwise the transition is rejected with `ERR_CONTRACT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/shipment_unload_requires_contract_active
        """
        term, contract, ship = self._setup_arrived_then_cancel()
        cancelled = get_success_data(
            api_client.get_supply_contract(contract["id"], SUPPLY_ADMIN))
        assert cancelled["status"] == "CANCELLED", (
            "setup check: the contract must be CANCELLED before the unload "
            f"attempt, got {cancelled['status']}")

        resp = api_client.transition_rail_shipment(
            ship["id"], {"to_state": "UNLOADED"}, SUPPLY_ADMIN)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    def test_shipment_unload_rejection_leaves_state_untouched(self):
        """PRD section 3.2: "Unloading requires the contract to be `ACTIVE` —
        otherwise the transition is rejected with `ERR_CONTRACT_NOT_ACTIVE`."
        PRD section 3.2: "On unload, the terminal's `on_hand_gal` increases by
        the shipment's `volume_gal` (bumping `Terminal.version`), the
        contract's `delivered_volume_gal` increases by the same amount, and
        `unloaded_at` is stamped with the current instant." — a rejected
        unload performs none of these.

        Design: Difficulty/cross_entity_state_dependency/shipment_unload_requires_contract_active
        """
        term, contract, ship = self._setup_arrived_then_cancel()
        api_client.transition_rail_shipment(ship["id"], {"to_state": "UNLOADED"},
                                            SUPPLY_ADMIN)

        after = get_success_data(api_client.get_rail_shipment(ship["id"],
                                                              SUPPLY_ADMIN))
        assert_rail_shipment(after)
        assert after["status"] == "ARRIVED"
        assert after["unloaded_at"] is None

        term_after = get_success_data(api_client.get_terminal(term["id"],
                                                              SUPPLY_ADMIN))
        assert term_after["on_hand_gal"] == 0, \
            "the rejected unload must not post inventory"

        contract_after = get_success_data(
            api_client.get_supply_contract(contract["id"], SUPPLY_ADMIN))
        assert contract_after["delivered_volume_gal"] == 0

    def test_supply_contract_completes_on_full_delivery(self):
        """PRD section 3.2: "On unload, the terminal's `on_hand_gal` increases
        by the shipment's `volume_gal` (bumping `Terminal.version`), the
        contract's `delivered_volume_gal` increases by the same amount, and
        `unloaded_at` is stamped with the current instant. If the delivered
        volume has now reached or exceeded the `contracted_volume_gal`, the
        contract transitions to `COMPLETED`, and no further rail shipments may
        be created or advanced under it."

        Design: Corner/state_machines/supply_contract_completes_on_full_delivery
        """
        term = create_terminal(name="T-M11")
        contract = create_supply_contract(term["id"],
                                          contracted_volume_gal=200_000)
        activate_supply_contract(contract["id"])
        ship = tender_shipment(contract["id"], volume_gal=200_000,
                               railcar_count=10)
        advance_shipment(ship["id"], "IN_TRANSIT")
        advance_shipment(ship["id"], "ARRIVED")
        unloaded = advance_shipment(ship["id"], "UNLOADED")
        assert_rail_shipment(unloaded)
        assert unloaded["status"] == "UNLOADED"
        assert unloaded["unloaded_at"] is not None

        contract_after = get_success_data(
            api_client.get_supply_contract(contract["id"], SUPPLY_ADMIN))
        assert_supply_contract(contract_after)
        assert contract_after["status"] == "COMPLETED", (
            "delivered 200000 reached contracted 200000; got "
            f"{contract_after['status']}")
        assert contract_after["delivered_volume_gal"] == 200_000

        term_after = get_success_data(api_client.get_terminal(term["id"],
                                                              SUPPLY_ADMIN))
        assert term_after["on_hand_gal"] == 200_000
