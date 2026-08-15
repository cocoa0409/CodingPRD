"""Receipt lot creation, acceptance gates (verification, histamine, abuse,
freeze, open CAs), quarantine loop, and species verification flows."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_lot,
    assert_lot_mass_balance,
    create_accepted_lot,
    create_approved_supplier,
    create_entry,
    create_lot,
    create_receipt_lot_payload,
    create_released_entry,
    create_species_verification_payload,
    get_success_data,
    make_compliance_manager_headers,
    make_qa_tech_headers,
    make_receiving_inspector_headers,
    record_histamine_pass,
    release_entry,
    validate_error,
    validate_paginated,
    validate_success,
    verify_species,
)

CM = TEST_USERS["compliance_manager_headers"]
IC = TEST_USERS["import_coordinator_headers"]
RI = TEST_USERS["receiving_inspector_headers"]
QA = TEST_USERS["qa_tech_headers"]


class TestReceiptCreation:
    def test_receipt_requires_released_entry(self, api):
        """PRD: "Receipt creation requires the import entry to be `RELEASED`;
        any other status is rejected with `ERR_ENTRY_NOT_RELEASED` (HTTP 409)."

        Design: Corner/validations/receipt_requires_released_entry
        """
        supplier = create_approved_supplier(frn="FRN-V09")
        entry = create_entry(supplier["id"], entry_number="E-V09")
        get_success_data(api.file_prior_notice(entry["id"], IC))
        get_success_data(api.file_entry(entry["id"], IC))
        # ENTRY_FILED, not RELEASED.
        resp = api.create_receipt_lot(
            create_receipt_lot_payload(import_entry_id=entry["id"],
                                       species_declared="COD"),
            RI)
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_RELEASED)

    def test_lot_computed_fields_and_ice_deduction(self, api):
        """PRD: "The system computes `quantity_accepted_kg` as the received
        quantity multiplied by one minus the ice deduction percentage divided
        by 100, rounded half-up to 3 decimal places. `remaining_kg` starts
        equal to `quantity_accepted_kg`; `consumed_kg` starts at 0.
        `cumulative_abuse_minutes` starts at 0, `freeze_compliant` starts at
        `false`, and `mislabel_flag` starts at `false`."
        PRD: "The invariant is that the sum of `allocated_cost_cents` across
        all eligible lots must equal `allocatable_total_cents`."

        Design: Corner/entities/lot_computed_fields_and_ice_deduction
        """
        supplier = create_approved_supplier(frn="FRN-C04")
        entry = create_released_entry(
            supplier["id"], entry_number="E-C04", species="TUNA",
            transport_mode="VESSEL", goods_value_cents=1000000,
            freight_cost_cents=50000, duty_rate_pct=0.03, total_weight_kg=100)

        lot = validate_success(api.create_receipt_lot(
            create_receipt_lot_payload(
                import_entry_id=entry["id"], species_declared="TUNA",
                quantity_received_kg=100, ice_deduction_pct=2.5,
                harvest_country_code="US", catch_area_code="FAO77",
                vessel_name="FV Pacific", receiving_temp_c=2.0),
            RI), 201)
        # round(100 * (1 - 2.5/100), 3) == 97.500
        assert lot["quantity_accepted_kg"] == pytest.approx(97.500, abs=1e-6)
        assert lot["remaining_kg"] == pytest.approx(97.500, abs=1e-6)
        assert lot["consumed_kg"] == 0
        assert lot["mislabel_flag"] is False
        assert lot["cumulative_abuse_minutes"] == 0
        assert lot["allocated_cost_cents"] == 0

        # On accept, the sole ACCEPTED lot absorbs the full allocatable total:
        # goods 1000000 + freight 50000 + duty round(1000000*0.03)=30000.
        verify_species(lot["id"], "TUNA", test_method="DNA_BARCODING")
        record_histamine_pass(lot["id"])
        accepted = validate_success(api.accept_receipt_lot(lot["id"], RI))
        assert accepted["allocated_cost_cents"] == 1080000


class TestAcceptanceGates:
    def test_histamine_gate_on_accept(self, api):
        """PRD: "If the lot's `species_declared` is among the
        histamine-susceptible species (TUNA, MAHI_MAHI, MACKEREL, SARDINE,
        ANCHOVY, BLUEFISH), a HaccpMonitoringRecord with `hazard_type`
        `HISTAMINE` for this lot with `verdict` `PASS` must exist. Absence is
        rejected with `ERR_HISTAMINE_CRITICAL_LIMIT` (HTTP 422)."

        Design: Corner/validations/histamine_gate_on_accept
        """
        supplier = create_approved_supplier(name="Meridian Marine",
                                            country="EC", frn="FRN-V11")
        entry = create_released_entry(supplier["id"], entry_number="E-V11",
                                      species="TUNA", transport_mode="VESSEL")
        lot = create_lot(entry["id"], species="TUNA", quantity_received_kg=80,
                         harvest_country_code="EC", catch_area_code="FAO87",
                         vessel_name="FV Meridiano", receiving_temp_c=2.0)
        verify_species(lot["id"], "TUNA", test_method="DNA_BARCODING")
        # No histamine PASS record exists.
        resp = api.accept_receipt_lot(lot["id"], RI)
        validate_error(resp, ApiErrorId.ERR_HISTAMINE_CRITICAL_LIMIT)
        after = validate_success(api.get_receipt_lot(lot["id"], RI))
        assert after["status"] == "UNDER_INSPECTION"

    def test_freeze_gate_on_accept(self, api):
        """PRD: "If the lot's `freeze_protocol` is not `NONE`,
        `freeze_compliant` must be `true`. Otherwise rejected with
        `ERR_FREEZE_PROTOCOL_NOT_MET` (HTTP 422)."

        Design: Corner/validations/freeze_gate_on_accept
        """
        supplier = create_approved_supplier(name="Nordic Fish Co", country="NO",
                                            frn="FRN-V12")
        entry = create_released_entry(supplier["id"], entry_number="E-V12",
                                      species="SALMON", transport_mode="AIR",
                                      goods_value_cents=800000,
                                      freight_cost_cents=90000,
                                      total_weight_kg=120)
        lot = create_lot(entry["id"], species="SALMON",
                         quantity_received_kg=120, harvest_country_code="NO",
                         catch_area_code="FAO27", production_method="FARMED",
                         freeze_protocol="STANDARD", vessel_name="FV Nord",
                         receiving_temp_c=0.0)
        verify_species(lot["id"], "SALMON")
        # No temperature logs: freeze_compliant is false.
        resp = api.accept_receipt_lot(lot["id"], RI)
        validate_error(resp, ApiErrorId.ERR_FREEZE_PROTOCOL_NOT_MET)

    def test_state_beats_safety_on_accept(self, api):
        """PRD: "Field-level validation (required fields, types, enum
        membership, numeric ranges) comes next, followed by state-machine
        checks (target resource in a valid from-state), then domain-specific
        business rules in ascending priority order."
        A QUARANTINED lot is not in accept's from-state, so the state check
        (ERR_INVALID_STATE, 409) runs before the histamine safety gate even
        though both would fail.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_accept
        """
        supplier = create_approved_supplier(name="Delta Seafood", country="VN",
                                            frn="FRN-6001")
        entry = create_released_entry(supplier["id"], entry_number="E-6001",
                                      species="TUNA", transport_mode="VESSEL",
                                      goods_value_cents=200000,
                                      freight_cost_cents=8000,
                                      duty_rate_pct=0.03, total_weight_kg=40)
        lot = create_lot(entry["id"], species="TUNA", grade="B",
                         quantity_received_kg=40, harvest_country_code="VN",
                         catch_area_code="FAO71", production_method="FARMED",
                         vessel_name="FV Delta", receiving_temp_c=2.0)
        # Manually quarantined WITHOUT any histamine record: both the state
        # rule and the safety rule would fail; state must win.
        get_success_data(api.quarantine_receipt_lot(lot["id"],
                                                    "document hold", QA))
        resp = api.accept_receipt_lot(lot["id"], RI)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_receipt_lot(lot["id"], QA))
        assert after["status"] == "QUARANTINED"

    def test_state_beats_safety_preserves_quarantine_state(self, api):
        """PRD: "A `QualityAssuranceTech` may place a hold on a lot in
        `UNDER_INSPECTION` or `ACCEPTED` by providing a `reason`, transitioning
        it to `QUARANTINED`." The failed accept (state error wins over the
        safety gate) is not a modification: "**`version`** (integer): A
        system-managed integer that increments with every modification to the
        resource." The lot's version after create(1) -> quarantine(2) stays 2.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_accept
        """
        supplier = create_approved_supplier(name="Delta Seafood", country="VN",
                                            frn="FRN-6001")
        entry = create_released_entry(supplier["id"], entry_number="E-6001",
                                      species="TUNA", transport_mode="VESSEL",
                                      goods_value_cents=200000,
                                      freight_cost_cents=8000,
                                      duty_rate_pct=0.03, total_weight_kg=40)
        lot = create_lot(entry["id"], species="TUNA", grade="B",
                         quantity_received_kg=40, harvest_country_code="VN",
                         catch_area_code="FAO71", production_method="FARMED",
                         vessel_name="FV Delta", receiving_temp_c=2.0)
        quarantined = get_success_data(
            api.quarantine_receipt_lot(lot["id"], "document hold", QA))
        assert quarantined["version"] == 2

        resp = api.accept_receipt_lot(lot["id"], RI)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_receipt_lot(lot["id"], QA))
        assert after["status"] == "QUARANTINED"
        assert after["version"] == 2

    def test_accept_rejected_lot_returns_invalid_state(self, api):
        """PRD: "A lot in `UNDER_INSPECTION` may be rejected outright by a
        `ReceivingInspector` providing a `reason`. This transitions to
        `REJECTED` (terminal)." Accept is gated on `UNDER_INSPECTION`, so
        accepting a REJECTED lot yields ERR_INVALID_STATE (HTTP 409).

        Design: Corner/state_machines/accept_rejected_lot_returns_invalid_state
        """
        supplier = create_approved_supplier(frn="FRN-S03")
        entry = create_released_entry(supplier["id"], entry_number="E-S03",
                                      species="COD")
        lot = create_lot(entry["id"], species="COD", quantity_received_kg=30)
        get_success_data(api.reject_receipt_lot(lot["id"],
                                                "falsified catch documents",
                                                RI))
        resp = api.accept_receipt_lot(lot["id"], RI)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_receipt_lot(lot["id"], RI))
        assert after["status"] == "REJECTED"


class TestQuarantineAcceptLoop:
    def test_quarantine_release_cycle_twice(self, api):
        """PRD: "A `QualityAssuranceTech` may place a hold on a lot in
        `UNDER_INSPECTION` or `ACCEPTED` by providing a `reason`, transitioning
        it to `QUARANTINED`."
        PRD: "On release, the lot returns to `ACCEPTED` and cost allocation
        re-runs with the lot re-included."

        Design: Difficulty/non_linear_state_machine/lot_quarantine_accept_loop
        """
        supplier = create_approved_supplier(name="Atlantic Whitefish",
                                            country="IS", frn="FRN-4002")
        entry = create_released_entry(supplier["id"], entry_number="E-4002",
                                      species="COD", transport_mode="VESSEL",
                                      port_code="USSEA",
                                      goods_value_cents=400000,
                                      freight_cost_cents=15000)
        lot = create_lot(entry["id"], species="COD", quantity_received_kg=100,
                         harvest_country_code="IS", catch_area_code="FAO27",
                         vessel_name="FV Ice")
        verify_species(lot["id"], "COD")
        accept_lot(lot["id"])

        # Traverse ACCEPTED -> QUARANTINED -> ACCEPTED twice.
        get_success_data(api.quarantine_receipt_lot(lot["id"],
                                                    "late document audit", QA))
        first = get_success_data(
            api.quarantine_release_receipt_lot(lot["id"], CM))
        assert first["status"] == "ACCEPTED"
        get_success_data(api.quarantine_receipt_lot(lot["id"], "second hold",
                                                    QA))
        second = get_success_data(
            api.quarantine_release_receipt_lot(lot["id"], CM))
        assert second["status"] == "ACCEPTED"

    def test_quarantine_release_requires_no_open_ca_and_version_progression(self, api):
        """PRD: "**`version`** (integer): A system-managed integer that
        increments with every modification to the resource. Starts at 1 on
        creation."
        PRD: "If they match, the verification enters `CONFIRMED` status, and
        the lot's `species_verified` is set to the verified species (bumping
        the lot's version)."
        create(1) -> verify(2) -> accept(3) -> quarantine(4) -> release(5)
        -> quarantine(6) -> release(7): the lot ends at version 7.

        Design: Difficulty/non_linear_state_machine/lot_quarantine_accept_loop
        """
        supplier = create_approved_supplier(name="Atlantic Whitefish",
                                            country="IS", frn="FRN-4002")
        entry = create_released_entry(supplier["id"], entry_number="E-4002",
                                      species="COD", transport_mode="VESSEL",
                                      port_code="USSEA",
                                      goods_value_cents=400000,
                                      freight_cost_cents=15000)
        lot = create_lot(entry["id"], species="COD", quantity_received_kg=100,
                         harvest_country_code="IS", catch_area_code="FAO27",
                         vessel_name="FV Ice")
        assert lot["version"] == 1
        verify_species(lot["id"], "COD")
        accept_lot(lot["id"])
        get_success_data(api.quarantine_receipt_lot(lot["id"], "hold-1", QA))
        get_success_data(api.quarantine_release_receipt_lot(lot["id"], CM))
        get_success_data(api.quarantine_receipt_lot(lot["id"], "hold-2", QA))
        get_success_data(api.quarantine_release_receipt_lot(lot["id"], CM))

        final = validate_success(api.get_receipt_lot(lot["id"], CM))
        assert final["status"] == "ACCEPTED"
        assert final["version"] == 7
        # Manual quarantine created no corrective action for this lot.
        cas, meta = validate_paginated(api.list_corrective_actions(
            CM, params={"receipt_lot_id": lot["id"]}))
        assert meta["total_count"] == 0


class TestAcceptResponseConsistency:
    def test_accept_response_immediate_consistency(self, api):
        """PRD: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD: "On acceptance, the lot transitions to `ACCEPTED` and the entry
        cost allocation runs over the entry's `ACCEPTED` lots — the newly
        accepted lot is now included."

        Design: Corner/endpoints/accept_response_immediate_consistency
        """
        supplier = create_approved_supplier(frn="FRN-P02")
        entry = create_released_entry(
            supplier["id"], entry_number="E-P02", species="TUNA",
            transport_mode="VESSEL", goods_value_cents=1000000,
            freight_cost_cents=50000, duty_rate_pct=0.0, total_weight_kg=100)
        lot = create_lot(entry["id"], species="TUNA", quantity_received_kg=100,
                         vessel_name="FV Pacific", catch_area_code="FAO77",
                         receiving_temp_c=2.0)
        verify_species(lot["id"], "TUNA", test_method="DNA_BARCODING")
        record_histamine_pass(lot["id"])
        accepted = validate_success(api.accept_receipt_lot(lot["id"], RI))
        # duty at rate 0.0 is 0 -> allocatable 1000000 + 50000 + 0 = 1050000.
        assert accepted["status"] == "ACCEPTED"
        assert accepted["allocated_cost_cents"] == 1050000


class TestReceiptLotPagination:
    def test_receipt_lots_list_pagination(self, api):
        """PRD: "The `limit` parameter specifies the maximum number of items to
        return. If not provided, it defaults to 10, with a minimum of 1 and a
        maximum of 100. The `offset` parameter specifies the number of items to
        skip and defaults to 0."
        PRD: "Paginated list-based responses include the following fields in
        the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/receipt_lots_list_pagination
        """
        supplier = create_approved_supplier(frn="FRN-C07")
        entry = create_released_entry(supplier["id"], entry_number="E-C07",
                                      species="COD", goods_value_cents=100000,
                                      freight_cost_cents=5000,
                                      total_weight_kg=60)
        lot1 = create_lot(entry["id"], species="COD", quantity_received_kg=30,
                          vessel_name="FV A")
        lot2 = create_lot(entry["id"], species="COD", grade="B",
                          quantity_received_kg=30, vessel_name="FV B")

        page1, meta1 = validate_paginated(api.list_receipt_lots(
            RI, params={"import_entry_id": entry["id"], "limit": 1,
                        "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_receipt_lots(
            RI, params={"import_entry_id": entry["id"], "limit": 1,
                        "offset": 1}))
        assert len(page2) == 1
        assert meta2["has_more"] is False

        ids = {page1[0]["id"], page2[0]["id"]}
        assert ids == {lot1["id"], lot2["id"]}
