"""Entry cost allocation waterfall: remainder distribution, tie-breaking, and
the money-conservation invariant across quarantine/release."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_lot,
    assert_allocation_conserves_total,
    create_approved_supplier,
    create_lot,
    create_released_entry,
    get_success_data,
    validate_success,
    verify_species,
)

CM = TEST_USERS["compliance_manager_headers"]
QA = TEST_USERS["qa_tech_headers"]


def _setup_two_cod_lots(api):
    """Entry with allocatable_total_cents == 1080001 and two 50 kg ACCEPTED
    COD lots (A created first, B second)."""
    supplier = create_approved_supplier(name="Harbor Fresh", country="US",
                                        frn="FRN-1002B")
    entry = create_released_entry(
        supplier["id"], entry_number="E-1002B", species="COD",
        transport_mode="ROAD", goods_value_cents=1000001,
        freight_cost_cents=50000, duty_rate_pct=0.03, total_weight_kg=100)
    lot_a = create_lot(entry["id"], species="COD", quantity_received_kg=50)
    verify_species(lot_a["id"], "COD")
    accept_lot(lot_a["id"])
    lot_b = create_lot(entry["id"], species="COD", quantity_received_kg=50)
    verify_species(lot_b["id"], "COD")
    accept_lot(lot_b["id"])
    return supplier, entry, lot_a, lot_b


class TestEntryCostAllocation:
    def test_duty_and_allocatable_total_computed_on_release(self, api):
        """PRD: "`RELEASED` computes `duty_cents` as the goods value in cents
        multiplied by the duty rate, rounded half-up to integer cents, and
        `allocatable_total_cents` as the sum of goods value, freight cost, and
        duty."
        round(1000001 * 0.03, 0) = 30000 (half-up: 30000.03 -> 30000);
        allocatable = 1000001 + 50000 + 30000 = 1080001.

        Design: Difficulty/compensating_invariant/quarantine_release_conserves_allocated_cost
        """
        supplier = create_approved_supplier(name="Harbor Fresh", country="US",
                                            frn="FRN-1002B")
        entry = create_released_entry(
            supplier["id"], entry_number="E-1002B", species="COD",
            transport_mode="ROAD", goods_value_cents=1000001,
            freight_cost_cents=50000, duty_rate_pct=0.03, total_weight_kg=100)
        assert entry["duty_cents"] == 30000
        assert entry["allocatable_total_cents"] == 1080001

    def test_quarantine_release_conserves_allocated_cost(self, api):
        """PRD: "The remainder — the allocatable total minus the sum of all
        floor values — is distributed one cent at a time to lots ordered by:
        share descending, then `quantity_accepted_kg` descending, then
        `created_at` ascending."
        PRD: "The invariant is that the sum of `allocated_cost_cents` across
        all eligible lots must equal `allocatable_total_cents`."
        PRD: "Each re-run fully recomputes from scratch; the eligible set
        changing re-allocates the same total over the new set."

        Design: Difficulty/compensating_invariant/quarantine_release_conserves_allocated_cost
        """
        supplier, entry, lot_a, lot_b = _setup_two_cod_lots(api)

        a0 = validate_success(api.get_receipt_lot(lot_a["id"], CM))
        b0 = validate_success(api.get_receipt_lot(lot_b["id"], CM))
        # Both shares are 0.5: floor(1080001 * 0.5) = 540000 each, remainder 1.
        # Tie on share and quantity -> created_at ascending: lot A gets +1.
        assert a0["allocated_cost_cents"] == 540001
        assert b0["allocated_cost_cents"] == 540000
        assert_allocation_conserves_total([a0, b0], 1080001)

        # Quarantine B: the eligible set collapses to A, which absorbs all.
        get_success_data(api.quarantine_receipt_lot(lot_b["id"], "audit hold",
                                                    QA))
        a1 = validate_success(api.get_receipt_lot(lot_a["id"], CM))
        b1 = validate_success(api.get_receipt_lot(lot_b["id"], CM))
        assert a1["allocated_cost_cents"] == 1080001
        assert b1["allocated_cost_cents"] == 0
        assert_allocation_conserves_total([a1], 1080001)

        # Release B: the compensating pair restores the original split exactly.
        get_success_data(api.quarantine_release_receipt_lot(lot_b["id"], CM))
        a2 = validate_success(api.get_receipt_lot(lot_a["id"], CM))
        b2 = validate_success(api.get_receipt_lot(lot_b["id"], CM))
        assert a2["allocated_cost_cents"] == 540001
        assert b2["allocated_cost_cents"] == 540000
        assert_allocation_conserves_total([a2, b2], 1080001)
