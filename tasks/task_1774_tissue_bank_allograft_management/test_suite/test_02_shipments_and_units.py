"""Shipments and tissue units: minting, inspection outcomes, release gates,
holds, discards, recall and fiscal gates on movement."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_tissue_unit,
    create_recall,
    create_shipment,
    get_success_data,
    make_manifest_item,
    setup_accepted_units,
    setup_available_units,
    setup_received_shipment,
    setup_supplier_and_freezer,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
QM = TEST_USERS["quality_headers"]
CO = TEST_USERS["compliance_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestShipmentMinting:
    def test_tissue_unit_system_fields_ignore_manifest_input(self, api):
        """PRD §3.2: "One `TissueUnit` is minted per line, each starting in
        `QUARANTINED` with `hold_reason` `NONE`, carrying its line's attributes
        plus its `shipment_id`, the denormalized `supplier_id`, and the storage
        `freezer_id`."
        PRD §2.5: "`id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/tissue_unit_system_fields_ignore_manifest_input
        """
        supplier, freezer = setup_supplier_and_freezer()
        smuggled_id = "00000000-0000-0000-0000-0000000000aa"
        shipment = validate_success(
            api.create_shipment(
                {
                    "supplier_id": supplier["id"],
                    "freezer_id": freezer["id"],
                    "items": [
                        {
                            "id": smuggled_id,
                            "status": "AVAILABLE",
                            "tissue_type": "BONE",
                            "lot_number": "L1",
                            "serial_number": "U-001",
                            "unit_cost_cents": 5000,
                            "expiration_at": "2027-01-01T00:00:00Z",
                            "criticality_tier": "STANDARD",
                        }
                    ],
                },
                COORD,
            ),
            201,
        )
        assert shipment["unit_count"] == 1
        assert shipment["total_declared_value_cents"] == 5000
        units = get_success_data(
            api.list_tissue_units(QM, params={"shipment_id": shipment["id"]})
        )
        assert len(units) == 1
        assert_tissue_unit(units[0])
        assert units[0]["status"] == "QUARANTINED"
        assert units[0]["hold_reason"] == "NONE"
        assert units[0]["id"] != smuggled_id

    def test_invalid_enum_in_manifest_rejected(self, api):
        """PRD §3.2: "each line declares a `tissue_type` (`BONE`,
        `SOFT_TISSUE`, `CARDIOVASCULAR`, `SKIN`, or `CORNEA`)"
        PRD §2.8: "4. **Request shape** — required fields present, types
        correct, enum members valid, strings at or above their minimum lengths,
        arrays non-empty where required, and window or range sanity:
        `ERR_INVALID_REQUEST`, `ERR_INVALID_WINDOW`, and
        `ERR_INVALID_TEMP_RANGE` (all 400)."

        Design: Corner/entities/invalid_enum_in_manifest_returns_invalid_request
        """
        supplier, freezer = setup_supplier_and_freezer()
        resp = api.create_shipment(
            {
                "supplier_id": supplier["id"],
                "freezer_id": freezer["id"],
                "items": [
                    make_manifest_item(tissue_type="MARROW")
                ],
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestShipmentInspection:
    def test_shipment_reject_creates_return_dispositions(self, api):
        """PRD §3.2: "Rejection by a `TissueBankCoordinator` requires a
        `rejection_reason` of at least ten characters (anything shorter fails
        with `ERR_INVALID_REQUEST`) and moves the shipment to `REJECTED`; every
        minted unit, still `QUARANTINED`, is moved to `RETURNED_TO_SUPPLIER`
        with `hold_reason` cleared to `NONE`, one `DRAFT` disposition record of
        type `RETURNED_TO_SUPPLIER` is created per unit under the coordinator's
        `recorded_by_user_id`, and the freezer's `occupied_count` is
        decremented per unit."

        Design: Corner/state_machines/shipment_reject_creates_return_dispositions
        """
        supplier, freezer, shipment, units = setup_received_shipment(
            items=[
                make_manifest_item(serial_number="U-001", unit_cost_cents=5000),
                make_manifest_item(serial_number="U-002", unit_cost_cents=6000),
            ]
        )
        rejected = validate_success(
            api.reject_shipment(
                shipment["id"], {"rejection_reason": "Cold chain broken in transit"}, COORD
            )
        )
        assert rejected["status"] == "REJECTED"
        after = get_success_data(
            api.list_tissue_units(QM, params={"shipment_id": shipment["id"]})
        )
        assert {u["status"] for u in after} == {"RETURNED_TO_SUPPLIER"}
        assert {u["hold_reason"] for u in after} == {"NONE"}
        for unit in after:
            records = get_success_data(api.list_unit_disposition_records(unit["id"], CO))
            assert len(records) == 1
            assert records[0]["disposition_type"] == "RETURNED_TO_SUPPLIER"
            assert records[0]["status"] == "DRAFT"
            assert records[0]["recorded_by_user_id"] == "tbc-1"
        freezer_after = validate_success(api.get_freezer(freezer["id"], ADMIN))
        assert freezer_after["occupied_count"] == 0

    def test_shipment_accept_twice_rejected(self, api):
        """PRD §3.2: "Both acceptance and rejection are defined only from
        `RECEIVED`; acting on a decided shipment fails with
        `ERR_SHIPMENT_NOT_RECEIVED`."

        Design: Corner/state_machines/shipment_accept_twice_rejected
        """
        _, _, shipment, _ = setup_accepted_units()
        resp = api.accept_shipment(shipment["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_RECEIVED)


class TestUnitStateGates:
    def test_unit_release_from_available_rejected(self, api):
        """PRD §3.4: "the unit must actually be `QUARANTINED`
        (`ERR_UNIT_NOT_QUARANTINED`)"

        Design: Corner/state_machines/unit_release_from_available_rejected
        """
        _, _, _, units = setup_available_units()
        assert units[0]["status"] == "AVAILABLE"
        resp = api.release_unit(units[0]["id"], QM)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_QUARANTINED)

    def test_unit_release_before_shipment_accept_blocked(self, api):
        """PRD §3.4: "its shipment must be `ACCEPTED`
        (`ERR_SHIPMENT_NOT_ACCEPTED`)"

        Design: Corner/state_machines/unit_release_before_shipment_accept_blocked
        """
        _, _, shipment, units = setup_received_shipment()
        assert shipment["status"] == "RECEIVED"
        assert units[0]["status"] == "QUARANTINED"
        resp = api.release_unit(units[0]["id"], QM)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_ACCEPTED)
        unit_after = validate_success(api.get_tissue_unit(units[0]["id"], QM))
        assert unit_after["status"] == "QUARANTINED"

    def test_unit_discard_from_available_rejected(self, api):
        """PRD §3.4: "Discarding takes a free-text `reason`, requires the unit
        to be `QUARANTINED` or `EXPIRED` (`ERR_UNIT_NOT_DISCARDABLE`)"

        Design: Corner/state_machines/unit_discard_from_available_rejected
        """
        _, _, _, units = setup_available_units()
        resp = api.discard_unit(
            units[0]["id"], {"reason": "Packaging damaged during handling"}, QM
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_DISCARDABLE)

    def test_unit_hold_from_quarantined_rejected(self, api):
        """PRD §3.4: "A `QualityManager` can manually quarantine an `AVAILABLE`
        unit — attempting it on any other status fails with
        `ERR_UNIT_NOT_HOLDABLE` — which records `hold_reason` `MANUAL`."

        Design: Corner/state_machines/unit_hold_from_quarantined_rejected
        """
        _, _, _, units = setup_received_shipment()
        assert units[0]["status"] == "QUARANTINED"
        resp = api.hold_unit(units[0]["id"], QM)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_HOLDABLE)


class TestRecallAndFiscalGates:
    def test_release_blocked_by_active_recall(self, api):
        """PRD §3.4: "no `ACTIVE` recall may match the unit
        (`ERR_UNIT_UNDER_ACTIVE_RECALL` — matching means the recall names the
        unit's supplier, the unit's `lot_number` appears among the recall's
        `lot_numbers`, and the unit's `received_at` falls inside the recall's
        received window inclusive at both ends)."

        Design: Corner/errors/error_release_blocked_by_active_recall
        """
        supplier, _, _, units = setup_available_units()
        recall = create_recall(supplier["id"], lot_numbers=["L1"],
                               reason="Lot L1 under recall")
        get_success_data(api.activate_recall(recall["id"], QM))
        held = validate_success(api.get_tissue_unit(units[0]["id"], QM))
        assert held["status"] == "QUARANTINED"
        assert held["hold_reason"] == "RECALL"
        resp = api.release_unit(units[0]["id"], QM)
        validate_error(resp, ApiErrorId.ERR_UNIT_UNDER_ACTIVE_RECALL)

    def test_inventory_value_cap_isolated(self, api):
        """PRD §3.2: "On top of compliance sits the fiscal cap of §3.9: for
        every tissue type in the shipment that has an `ACTIVE` par-level
        policy, acceptance is refused with `ERR_INVENTORY_VALUE_CAP_EXCEEDED`
        (HTTP 402) if the projected weighted-average valuation including the
        incoming units would exceed the policy's
        `max_inventory_value_cents`."

        Design: Corner/errors/error_inventory_value_cap_isolated
        """
        supplier, freezer = setup_supplier_and_freezer()
        get_success_data(
            api.create_par_policy(
                {
                    "tissue_type": "BONE",
                    "par_quantity": 5,
                    "max_inventory_value_cents": 25000,
                },
                ADMIN,
            )
        )
        shipment = create_shipment(
            supplier["id"],
            freezer["id"],
            [
                make_manifest_item(serial_number="U-001", unit_cost_cents=10001),
                make_manifest_item(serial_number="U-002", unit_cost_cents=10001),
                make_manifest_item(serial_number="U-003", unit_cost_cents=10001),
            ],
        )
        resp = api.accept_shipment(shipment["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVENTORY_VALUE_CAP_EXCEEDED)
        after = validate_success(api.get_shipment(shipment["id"], COORD))
        assert after["status"] == "RECEIVED"

    def test_valuation_empty_population_after_reject(self, api):
        """PRD §3.9: "Both methods share a population definition: every unit of
        the named tissue type whose shipment reached `ACCEPTED`, in any unit
        status including terminal ones, with the on-hand subset being those
        population units in `QUARANTINED`, `AVAILABLE`, `RESERVED`, or
        `ISSUED`; `on_hand_count` is the size of that subset."
        PRD §3.9: "`total_value` is the sum of those per-lot line values."

        Design: Corner/calculations/valuation_empty_population_after_reject
        """
        supplier, freezer, shipment, _ = setup_received_shipment()
        get_success_data(
            api.reject_shipment(
                shipment["id"], {"rejection_reason": "Cold chain broken in transit"}, COORD
            )
        )
        fifo = validate_success(api.get_inventory_valuation("BONE", "FIFO", ADMIN))
        assert fifo["on_hand_count"] == 0
        assert fifo["total_value"] == pytest.approx(0.0, abs=0.005)
        wa = validate_success(
            api.get_inventory_valuation("BONE", "WEIGHTED_AVERAGE", ADMIN)
        )
        assert wa["on_hand_count"] == 0
        assert wa["total_value"] == pytest.approx(0.0, abs=0.005)


class TestAcceptSupplierQualificationGate:
    def test_accept_blocked_while_supplier_suspended(self, api):
        """PRD §3.2: "Acceptance re-verifies the compliance envelope at
        decision time rather than trusting receipt-time checks: the supplier
        must still be `QUALIFIED` (`ERR_SUPPLIER_NOT_QUALIFIED`)"

        Design: Difficulty/cross_entity_state_dependency/shipment_accept_blocked_by_supplier_suspension
        """
        supplier, freezer, shipment, _ = setup_received_shipment()
        get_success_data(api.suspend_supplier(supplier["id"], CO))
        resp = api.accept_shipment(shipment["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED)
        after = validate_success(api.get_shipment(shipment["id"], COORD))
        assert after["status"] == "RECEIVED"

    def test_accept_succeeds_after_supplier_reinstated(self, api):
        """PRD §3.2: "Acceptance re-verifies the compliance envelope at
        decision time rather than trusting receipt-time checks: the supplier
        must still be `QUALIFIED` (`ERR_SUPPLIER_NOT_QUALIFIED`)"
        PRD §3.1: "From `SUSPENDED`, reinstatement by a `ComplianceOfficer`
        re-applies the same documentary coverage check as approval
        (`ERR_REQUIRED_DOCUMENTS_NOT_VERIFIED` on lapse) and additionally
        demands a `qualification_score_provisional` of at least 60; a weaker
        score is rejected with `ERR_SUPPLIER_SCORE_BELOW_THRESHOLD`."

        Design: Difficulty/cross_entity_state_dependency/shipment_accept_blocked_by_supplier_suspension
        """
        supplier, freezer, shipment, _ = setup_received_shipment()
        get_success_data(api.suspend_supplier(supplier["id"], CO))
        reinstated = validate_success(api.reinstate_supplier(supplier["id"], CO))
        assert reinstated["status"] == "QUALIFIED"
        accepted = validate_success(api.accept_shipment(shipment["id"], COORD))
        assert accepted["status"] == "ACCEPTED"
        supplier_after = validate_success(api.get_supplier(supplier["id"], CO))
        assert supplier_after["status"] == "QUALIFIED"


class TestAcceptPrioritySafetyOverFiscal:
    def test_accept_suspended_supplier_reports_safety_not_fiscal(self, api):
        """PRD §2.8: "When a request violates several rules, the platform
        reports exactly one failure: the one from the earliest rung of a pinned
        priority ladder."
        PRD §2.8: "11. **Fiscal caps** — the inventory value ceiling at
        shipment acceptance (`ERR_INVENTORY_VALUE_CAP_EXCEEDED`, 402),
        evaluated last."

        Design: Difficulty/priority_pair_validation_conflict/accept_suspended_supplier_over_cap_safety_wins
        """
        supplier, freezer = setup_supplier_and_freezer()
        get_success_data(
            api.create_par_policy(
                {
                    "tissue_type": "BONE",
                    "par_quantity": 5,
                    "max_inventory_value_cents": 25000,
                },
                ADMIN,
            )
        )
        shipment = create_shipment(
            supplier["id"],
            freezer["id"],
            [
                make_manifest_item(serial_number="U-001", unit_cost_cents=10001),
                make_manifest_item(serial_number="U-002", unit_cost_cents=10001),
                make_manifest_item(serial_number="U-003", unit_cost_cents=10001),
            ],
        )
        get_success_data(api.suspend_supplier(supplier["id"], CO))
        resp = api.accept_shipment(shipment["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED)

    def test_accept_suspended_supplier_leaves_shipment_untouched(self, api):
        """PRD §2.8: "7. **Compliance gates** — supplier qualification and
        document verification, unit expiry at movement time, active-recall
        matches, freezer excursion lockout, and high-severity destroy mandates:
        `ERR_SUPPLIER_NOT_QUALIFIED`, `ERR_REQUIRED_DOCUMENTS_NOT_VERIFIED`,
        `ERR_UNIT_EXPIRED`, `ERR_UNIT_UNDER_ACTIVE_RECALL`,
        `ERR_FREEZER_IN_EXCURSION`, and `ERR_SEVERITY_REQUIRES_DESTROY`
        (all 403)."
        PRD §3.2: "Both acceptance and rejection are defined only from
        `RECEIVED`; acting on a decided shipment fails with
        `ERR_SHIPMENT_NOT_RECEIVED`."

        Design: Difficulty/priority_pair_validation_conflict/accept_suspended_supplier_over_cap_safety_wins
        """
        supplier, freezer = setup_supplier_and_freezer()
        get_success_data(
            api.create_par_policy(
                {
                    "tissue_type": "BONE",
                    "par_quantity": 5,
                    "max_inventory_value_cents": 25000,
                },
                ADMIN,
            )
        )
        shipment = create_shipment(
            supplier["id"],
            freezer["id"],
            [
                make_manifest_item(serial_number="U-001", unit_cost_cents=10001),
                make_manifest_item(serial_number="U-002", unit_cost_cents=10001),
                make_manifest_item(serial_number="U-003", unit_cost_cents=10001),
            ],
        )
        get_success_data(api.suspend_supplier(supplier["id"], CO))
        resp = api.accept_shipment(shipment["id"], COORD)
        err = validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED)
        assert err["error_id"] != "ERR_INVENTORY_VALUE_CAP_EXCEEDED"
        after = validate_success(api.get_shipment(shipment["id"], COORD))
        assert after["status"] == "RECEIVED"
