"""Inventory receipt, rollup reconciliation, lot lifecycle, and compliance gates.

Covers queue-B corner instances and queue-A difficulty instances on inventory
receiving, derived-quantity reconciliation, the quarantine conservation invariant,
optimistic concurrency on receive-lot, and the RoHS / conflict-minerals gates.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
import test_helpers.fixtures as fx
import test_helpers.factories as f

PE = TEST_USERS["process_engineer_headers"]
PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]


# ---------------------------------------------------------------------------
# Derived-field reconciliation after receipt
# ---------------------------------------------------------------------------

def test_available_qty_reconciled_after_receive(api):
    """PRD §3.2: "A successfully received lot is created with `remaining_qty` equal
    to its `received_qty` and `status` `AVAILABLE`, and the owning part's
    `total_on_hand_qty` and `available_qty` are recomputed".
    PRD §2.9: "`available_qty` is the sum of `remaining_qty` across the part's
    `AVAILABLE` lots only, minus the quantity currently reserved by open kit
    requirements".

    Design: Corner/cross_cutting_complexity_layers/derived_available_qty_reconciled_after_receive
    """
    part = fx.create_part()
    avl = fx.create_approved_avl(part["id"])
    fx.receive_one_lot(avl["id"], avl["version"], received_qty=25, unit_cost_cents=10)
    fetched = validate_success(api.get_part(part["id"], PP))
    assert fetched["available_qty"] == 25, fetched
    assert fetched["total_on_hand_qty"] == 25, fetched


# ---------------------------------------------------------------------------
# Receive-lot gating: revoked approval / OCC
# ---------------------------------------------------------------------------

def test_receive_lot_against_revoked_avl_rejected(api):
    """PRD §3.2: "A lot may be received only when the approval record's `status` is
    `APPROVED` and the backing vendor's `status` is `ACTIVE`; a receipt against a
    revoked approval or a suspended vendor is rejected with `ERR_AVL_NOT_APPROVED`
    (HTTP 422)."

    Design: Corner/validations/receive_lot_against_revoked_avl_rejected
    """
    part = fx.create_part()
    avl = fx.create_approved_avl(part["id"])
    revoked = get_success_data(api.revoke_avl_entry(avl["id"], PE))
    payload = f.receive_lot_payload(revoked["version"], lot_code="CL-REVK",
                                    received_qty=10, unit_cost_cents=10)
    validate_error(api.receive_lot(avl["id"], payload, PP),
                   ApiErrorId.ERR_AVL_NOT_APPROVED.value)


def test_receive_lot_stale_avl_version_rejected(api):
    """PRD §2.6: "Receiving an inventory lot against an approved-vendor record
    requires the request to carry `expected_avl_entry_version`, which must equal that
    approval record's current `version`. If another writer has advanced the approval
    record's version since the client last read it ... the receive request is rejected
    with `ERR_STALE_AVL_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_receive_lot_stale_avl_version
    """
    part = fx.create_part()
    avl = fx.create_approved_avl(part["id"])
    # First receipt advances the AvlEntry version.
    lot1 = fx.receive_one_lot(avl["id"], avl["version"], lot_code="CL-OCC-1",
                              received_qty=10, unit_cost_cents=10)
    # Re-fetch the entry to learn the advanced version, then submit one behind it.
    current = validate_success(api.get_avl_entry(avl["id"], PP))
    stale_version = current["version"] - 1
    payload = f.receive_lot_payload(stale_version, lot_code="CL-OCC-2",
                                    received_qty=5, unit_cost_cents=10,
                                    received_at="2026-01-03T00:00:00.000Z")
    validate_error(api.receive_lot(avl["id"], payload, PP),
                   ApiErrorId.ERR_STALE_AVL_VERSION.value)
    assert lot1["remaining_qty"] == 10


# ---------------------------------------------------------------------------
# Quarantine conservation invariant (queue A: compensating_invariant)
# ---------------------------------------------------------------------------

def test_quarantine_conserves_total_on_hand_removes_available(api):
    """PRD §2.9: "A quality engineer may quarantine an `AVAILABLE` lot, moving it to
    `QUARANTINED`; its `remaining_qty` then leaves the available pool but remains
    counted in on-hand stock, so quarantine recomputes the owning part's
    `available_qty` accordingly."

    Design: Difficulty/compensating_invariant/revoke_lot_receipt_balance_invariant
    """
    part = fx.create_part()
    avl = fx.create_approved_avl(part["id"])
    lot = fx.receive_one_lot(avl["id"], avl["version"], received_qty=30, unit_cost_cents=20)
    get_success_data(api.quarantine_lot(lot["id"], QE))
    fetched = validate_success(api.get_part(part["id"], PP))
    assert fetched["total_on_hand_qty"] == 30, fetched
    assert fetched["available_qty"] == 0, fetched


def test_quarantined_lot_status_is_quarantined(api):
    """PRD §2.9: "A quality engineer may quarantine an `AVAILABLE` lot, moving it to
    `QUARANTINED`; its `remaining_qty` then leaves the available pool but remains
    counted in on-hand stock, so quarantine recomputes the owning part's
    `available_qty` accordingly."

    Design: Difficulty/compensating_invariant/revoke_lot_receipt_balance_invariant
    """
    part = fx.create_part()
    avl = fx.create_approved_avl(part["id"])
    lot = fx.receive_one_lot(avl["id"], avl["version"], received_qty=30, unit_cost_cents=20)
    quarantined = validate_success(api.quarantine_lot(lot["id"], QE))
    assert quarantined["status"] == "QUARANTINED", quarantined


# ---------------------------------------------------------------------------
# Lot-code uniqueness within a part (queue A: resource_temporal_overlap)
# ---------------------------------------------------------------------------

def test_duplicate_lot_code_within_part_rejected(api):
    """PRD §3.2: "The request supplies a `lot_code` (the vendor lot or date code,
    which must be unique within the part)".
    PRD §2.7: "a generic business-rule violation not covered by a more specific code
    (such as a non-positive received quantity) yields `ERR_VALIDATION` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/lot_code_uniqueness_within_part_collision
    """
    part = fx.create_part()
    avl = fx.create_approved_avl(part["id"])
    lot1 = fx.receive_one_lot(avl["id"], avl["version"], lot_code="LOT-DUP",
                              received_qty=10, unit_cost_cents=20)
    current = validate_success(api.get_avl_entry(avl["id"], PP))
    payload = f.receive_lot_payload(current["version"], lot_code="LOT-DUP",
                                    received_qty=5, unit_cost_cents=20,
                                    received_at="2026-01-03T00:00:00.000Z")
    validate_error(api.receive_lot(avl["id"], payload, PP),
                   ApiErrorId.ERR_VALIDATION.value)
    assert lot1["lot_code"] == "LOT-DUP"


def test_same_lot_code_distinct_parts_allowed(api):
    """PRD §3.2: "The request supplies a `lot_code` (the vendor lot or date code,
    which must be unique within the part)".

    Uniqueness is scoped per part, so the same lot_code under a different part is
    accepted — pinning the scope of the constraint asserted above.

    Design: Difficulty/resource_temporal_overlap/lot_code_uniqueness_within_part_collision
    """
    part_a = fx.create_part()
    avl_a = fx.create_approved_avl(part_a["id"])
    fx.receive_one_lot(avl_a["id"], avl_a["version"], lot_code="SHARED-CODE",
                       received_qty=10, unit_cost_cents=20)

    part_b = fx.create_part()
    avl_b = fx.create_approved_avl(part_b["id"])
    payload = f.receive_lot_payload(avl_b["version"], lot_code="SHARED-CODE",
                                    received_qty=7, unit_cost_cents=20)
    created = validate_success(api.receive_lot(avl_b["id"], payload, PP), expected_status=201)
    assert created["lot_code"] == "SHARED-CODE"
    assert created["part_id"] == part_b["id"]


# ---------------------------------------------------------------------------
# Conflict-minerals gate at start
# ---------------------------------------------------------------------------

def test_cmrt_missing_on_start_rejected(api):
    """PRD §2.8: "A part whose `contains_conflict_minerals` flag is set may only
    consume lots that carry a conflict-minerals reporting template, signalled by the
    lot's `has_cmrt` flag; consuming a lot that lacks the template fails with
    `ERR_CMRT_MISSING` (HTTP 422). The conflict-minerals gate applies at two
    consumption points: when a run is started and when a rework order is closed."

    Design: Corner/validations/cmrt_missing_on_start_rejected
    """
    part = fx.create_part(contains_conflict_minerals=True, standard_cost_cents=30,
                          package_type="0805")
    avl = fx.create_approved_avl(part["id"])
    fx.receive_one_lot(avl["id"], avl["version"], received_qty=10, unit_cost_cents=30,
                       is_rohs_compliant=True, has_cmrt=False)
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=1,
                                             ref_designators=["C1"])
    program = fx.create_verified_program(bom["id"])
    wo = fx.create_kitted_work_order(part["id"], bom["id"], planned_qty=1)
    get_success_data(api.setup_work_order(wo["id"], f.setup_payload(program["id"]), PP))

    validate_error(api.start_work_order(wo["id"], PP), ApiErrorId.ERR_CMRT_MISSING.value)
    fetched = validate_success(api.get_work_order(wo["id"], PP))
    assert fetched["status"] == "SETUP", fetched
