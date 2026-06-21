"""Order and distribution-event lifecycle: the AgencyOrder recall revision loop,
the DistributionEvent pack/void branch, the finalize cascade (lot -> order ->
agency ledger), the clock-expiry cascade (lot -> cold storage), and the
poundage-conservation invariants on cancel and void.

Covers Difficulty queue rules non_linear_state_machine, transitive_cascade,
and compensating_invariant.
"""
from prd_bench_local_runner.testing import validate_success, validate_paginated
from test_helpers import (
    api_client, TEST_USERS, fixtures, make_agency_coordinator_headers,
)

MGR = TEST_USERS["allocation_manager_headers"]
OP = TEST_USERS["food_bank_operator_headers"]


# ---------------------------------------------------------------------------
# non_linear_state_machine
# ---------------------------------------------------------------------------

def test_recall_cycles_approved_order_back_to_submitted(api):
    """PRD §3.6: "An AllocationManager may recall an APPROVED order back to
    SUBMITTED for revision, provided no DistributionEvent for that order has
    reached PACKED or FINALIZED."
    PRD §3.6: "the order's approved_lbs resets to 0 and its version is bumped."

    Design: Difficulty/non_linear_state_machine/agency_order_recall_cycle_back_to_submitted
    """
    ctx = fixtures.setup_approved_order(requested_lbs=200, intake_lbs=500)
    recalled = validate_success(api.recall_agency_order(ctx["order"]["id"], MGR))
    assert recalled["status"] == "SUBMITTED", \
        f"recall returns order to SUBMITTED, got {recalled['status']}"
    assert recalled["approved_lbs"] == 0.00, \
        f"approved_lbs resets to 0 on recall, got {recalled['approved_lbs']}"


def test_recall_restores_lot_remaining_lbs(api):
    """PRD §3.6: "The recall releases every line's reservation: each reserved
    InventoryLot moves from RESERVED back to AVAILABLE with its remaining_lbs
    restored by exactly the released amount"

    Design: Difficulty/non_linear_state_machine/agency_order_recall_cycle_back_to_submitted
    """
    ctx = fixtures.setup_approved_order(requested_lbs=200, intake_lbs=500)
    api.recall_agency_order(ctx["order"]["id"], MGR)
    lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], OP))
    assert lot["remaining_lbs"] == 500.00, \
        f"lot remaining_lbs restored to full 500, got {lot['remaining_lbs']}"
    assert lot["disposition"] == "AVAILABLE", \
        f"lot returns to AVAILABLE, got {lot['disposition']}"


def test_void_planned_event_leaves_lines_reserved(api):
    """PRD §3.7: "A PLANNED event may be voided with nothing moved — the order's
    lines remain RESERVED."
    PRD §3.7: "Either void moves the event to VOIDED and bumps its version."

    Design: Difficulty/non_linear_state_machine/distribution_event_branch_pack_vs_void
    """
    ctx = fixtures.setup_planned_event(requested_lbs=200, intake_lbs=500, certify=True)
    agency_id = ctx["agency"]["id"]
    voided = validate_success(api.void_distribution_event(
        ctx["event"]["id"], make_agency_coordinator_headers(agency_id)))
    assert voided["status"] == "VOIDED", f"event should be VOIDED, got {voided['status']}"
    assert voided["planned_lbs"] == 0.00, \
        f"void of a PLANNED event computes no planned poundage, got {voided['planned_lbs']}"
    lines, _ = validate_paginated(api.list_order_lines(ctx["order"]["id"], MGR))
    assert lines[0]["line_status"] == "RESERVED", \
        f"order line untouched by void, should be RESERVED, got {lines[0]['line_status']}"


def test_pack_branch_marks_lines_packed_and_sets_planned(api):
    """PRD §3.7: "On a valid pack the event moves from PLANNED to PACKED, its
    planned_lbs is set to the forward-looking planned poundage"
    PRD §3.7: "The order's RESERVED lines are marked PACKED, and the event's
    version is bumped."

    Design: Difficulty/non_linear_state_machine/distribution_event_branch_pack_vs_void
    """
    ctx = fixtures.setup_planned_event(requested_lbs=200, intake_lbs=500, certify=True)
    agency_id = ctx["agency"]["id"]
    packed = validate_success(api.pack_distribution_event(
        ctx["event"]["id"], make_agency_coordinator_headers(agency_id)))
    assert packed["status"] == "PACKED"
    assert packed["planned_lbs"] == 200.00, \
        f"pack sets planned_lbs to reserved 200, got {packed['planned_lbs']}"
    lines, _ = validate_paginated(api.list_order_lines(ctx["order"]["id"], MGR))
    assert lines[0]["line_status"] == "PACKED", \
        f"pack marks RESERVED lines PACKED, got {lines[0]['line_status']}"


# ---------------------------------------------------------------------------
# transitive_cascade
# ---------------------------------------------------------------------------

def test_finalize_cascade_depletes_lot_fulfills_order_bumps_agency_ledger(api):
    """PRD §3.7: "transitions the reserved lots backing the order's PACKED lines
    from RESERVED to DEPLETED (marking that poundage permanently consumed and
    bumping each lot's version), advances the linked AgencyOrder from APPROVED to
    FULFILLED, increases the receiving agency's lifetime_distributed_lbs by the
    actual_distributed_lbs, and bumps the event's version."

    Design: Difficulty/transitive_cascade/finalize_depth3_lot_order_agency_ledger
    """
    ctx = fixtures.setup_packed_event(requested_lbs=200, intake_lbs=200)
    agency_id = ctx["agency"]["id"]
    finalized = validate_success(api.finalize_distribution_event(
        ctx["event"]["id"], {"actual_distributed_lbs": 200},
        make_agency_coordinator_headers(agency_id)))
    assert finalized["status"] == "FINALIZED"

    lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], OP))
    assert lot["disposition"] == "DEPLETED", \
        f"reserved lot should deplete on finalize, got {lot['disposition']}"

    order = validate_success(api.get_agency_order(ctx["order"]["id"], MGR))
    assert order["status"] == "FULFILLED", \
        f"order should be FULFILLED on finalize, got {order['status']}"

    agency = validate_success(api.get_agency(agency_id, MGR))
    assert agency["lifetime_distributed_lbs"] == 200.00, \
        f"agency ledger should add 200, got {agency['lifetime_distributed_lbs']}"


def test_finalize_cascade_event_reaches_finalized_and_depletes_holding_unit_occupancy(api):
    """PRD §3.7: "This is the cascade origin of the system: a single finalize
    depletes lots, fulfills the order, advances the agency's lifetime ledger, and
    feeds the cycle's poundage report."
    PRD §2.5: "Lots that have become DEPLETED, EXPIRED, or DISPOSED leave the
    occupancy count entirely."

    Design: Difficulty/transitive_cascade/finalize_depth3_lot_order_agency_ledger
    """
    ctx = fixtures.setup_packed_event(requested_lbs=200, intake_lbs=200)
    agency_id = ctx["agency"]["id"]
    finalized = validate_success(api.finalize_distribution_event(
        ctx["event"]["id"], {"actual_distributed_lbs": 200},
        make_agency_coordinator_headers(agency_id)))
    assert finalized["status"] == "FINALIZED"
    # The depleted lot has left the holding unit's occupancy as a downstream effect.
    unit = validate_success(api.get_cold_storage_unit(ctx["unit"]["id"], OP))
    assert unit["stored_lbs"] == 0.00, \
        f"depleted lot leaves occupancy after the finalize cascade, got {unit['stored_lbs']}"


def test_clock_expiry_cascade_expires_lot_and_drops_cold_storage_occupancy(api):
    """PRD §2.9: "Advancing the clock runs a shelf-life sweep: every AVAILABLE lot
    whose expiration_date is at or before the new current time transitions to
    EXPIRED, its holding unit's occupancy is recomputed, and its version is
    bumped."
    PRD §2.5: "Lots that have become DEPLETED, EXPIRED, or DISPOSED leave the
    occupancy count entirely."
    PRD §2.5: "it reads FULL when stored_lbs equals capacity_lbs, and AVAILABLE
    whenever stored_lbs is below capacity_lbs."

    Design: Difficulty/transitive_cascade/clock_expiry_depth2_lot_then_coldstorage
    """
    api.set_clock("2026-06-01T00:00:00.000Z", OP)
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    lot = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                        intake_lbs=300,
                                        expiration_date="2026-06-15T00:00:00.000Z")
    api.set_clock("2026-06-20T00:00:00.000Z", OP)

    refetched_lot = validate_success(api.get_inventory_lot(lot["id"], OP))
    assert refetched_lot["disposition"] == "EXPIRED", \
        f"lot should expire past its date, got {refetched_lot['disposition']}"

    refetched_unit = validate_success(api.get_cold_storage_unit(unit["id"], OP))
    assert refetched_unit["stored_lbs"] == 0.00, \
        f"expired lot leaves occupancy, stored_lbs should be 0, got {refetched_unit['stored_lbs']}"
    assert refetched_unit["status"] == "AVAILABLE", \
        f"unit below capacity should be AVAILABLE, got {refetched_unit['status']}"


def test_clock_expiry_only_fires_for_lots_at_or_past_expiration(api):
    """PRD §3.1: "this fires only for lots whose disposition is AVAILABLE and whose
    expiration_date is at or before the new current time"
    PRD §2.9: "every AVAILABLE lot whose expiration_date is at or before the new
    current time transitions to EXPIRED, its holding unit's occupancy is
    recomputed, and its version is bumped."

    Design: Difficulty/transitive_cascade/clock_expiry_depth2_lot_then_coldstorage
    """
    api.set_clock("2026-06-01T00:00:00.000Z", OP)
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    # Lot expires 2026-06-15; advancing only to 2026-06-10 must NOT expire it.
    lot = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                        intake_lbs=300,
                                        expiration_date="2026-06-15T00:00:00.000Z")
    api.set_clock("2026-06-10T00:00:00.000Z", OP)
    still_available = validate_success(api.get_inventory_lot(lot["id"], OP))
    assert still_available["disposition"] == "AVAILABLE", \
        f"lot before its expiration stays AVAILABLE, got {still_available['disposition']}"
    unit_before = validate_success(api.get_cold_storage_unit(unit["id"], OP))
    assert unit_before["stored_lbs"] == 300.00, \
        f"occupancy still counts the live lot at 300, got {unit_before['stored_lbs']}"
    # Now advance past expiration: lot expires and leaves occupancy.
    api.set_clock("2026-06-20T00:00:00.000Z", OP)
    expired = validate_success(api.get_inventory_lot(lot["id"], OP))
    assert expired["disposition"] == "EXPIRED"
    unit_after = validate_success(api.get_cold_storage_unit(unit["id"], OP))
    assert unit_after["stored_lbs"] == 0.00, \
        f"expired lot leaves occupancy, got {unit_after['stored_lbs']}"


# ---------------------------------------------------------------------------
# compensating_invariant
# ---------------------------------------------------------------------------

def test_cancel_approved_order_conserves_lot_poundage(api):
    """PRD §3.6: "cancelling it releases all reservations exactly as recall does —
    reserved lots return from RESERVED to AVAILABLE, remaining_lbs is restored,
    lines reset to PENDING with reserved_lbs 0 and reserved_lot_id null — and the
    order moves to CANCELLED with its version bumped."
    PRD §3.6: "poundage released equals poundage reserved, so no pound is ever
    created or destroyed by an unwind."

    Design: Difficulty/compensating_invariant/order_cancel_conserves_lot_poundage
    """
    ctx = fixtures.setup_approved_order(requested_lbs=200, intake_lbs=300)
    agency_id = ctx["agency"]["id"]
    cancelled = validate_success(api.cancel_agency_order(
        ctx["order"]["id"], make_agency_coordinator_headers(agency_id)))
    assert cancelled["status"] == "CANCELLED", f"order should be CANCELLED, got {cancelled['status']}"

    lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], OP))
    assert lot["remaining_lbs"] == 300.00, \
        f"released poundage equals reserved; remaining_lbs back to 300, got {lot['remaining_lbs']}"
    assert lot["disposition"] == "AVAILABLE", \
        f"lot returns to AVAILABLE, got {lot['disposition']}"


def test_cancel_approved_order_resets_lines_to_pending(api):
    """PRD §3.6: "reserved lots return from RESERVED to AVAILABLE, remaining_lbs is
    restored, lines reset to PENDING with reserved_lbs 0 and reserved_lot_id null"
    PRD §3.6: "Whenever a reservation is released through recall or cancel, the
    affected lot's holding unit has its stored_lbs recomputed and the lot's version
    bumped."

    Design: Difficulty/compensating_invariant/order_cancel_conserves_lot_poundage
    """
    ctx = fixtures.setup_approved_order(requested_lbs=200, intake_lbs=300)
    agency_id = ctx["agency"]["id"]
    api.cancel_agency_order(ctx["order"]["id"], make_agency_coordinator_headers(agency_id))
    lines, _ = validate_paginated(api.list_order_lines(ctx["order"]["id"], MGR))
    assert lines[0]["line_status"] == "PENDING", \
        f"line resets to PENDING on cancel, got {lines[0]['line_status']}"
    assert lines[0]["reserved_lbs"] == 0.00, \
        f"reserved_lbs resets to 0 on cancel, got {lines[0]['reserved_lbs']}"
    assert lines[0]["reserved_lot_id"] is None, \
        f"reserved_lot_id resets to null on cancel, got {lines[0]['reserved_lot_id']}"
    # Holding unit occupancy restored to the full released poundage.
    unit = validate_success(api.get_cold_storage_unit(ctx["unit"]["id"], OP))
    assert unit["stored_lbs"] == 300.00, \
        f"occupancy recomputed to full 300 after release, got {unit['stored_lbs']}"


def test_void_packed_event_conserves_line_reserved_poundage(api):
    """PRD §3.7: "A PACKED event may also be voided, which reverts its packing: the
    order's PACKED lines return to line_status RESERVED and the event's planned_lbs
    resets to 0, conserving poundage without consuming any."
    PRD §3.7: "A void leaves no poundage permanently consumed."

    Design: Difficulty/compensating_invariant/event_void_conserves_line_packed_poundage
    """
    ctx = fixtures.setup_packed_event(requested_lbs=200, intake_lbs=300)
    agency_id = ctx["agency"]["id"]
    voided = validate_success(api.void_distribution_event(
        ctx["event"]["id"], make_agency_coordinator_headers(agency_id)))
    assert voided["status"] == "VOIDED", f"event should be VOIDED, got {voided['status']}"
    assert voided["planned_lbs"] == 0.00, \
        f"void of PACKED event resets planned_lbs to 0, got {voided['planned_lbs']}"

    lines, _ = validate_paginated(api.list_order_lines(ctx["order"]["id"], MGR))
    assert lines[0]["line_status"] == "RESERVED", \
        f"PACKED line reverts to RESERVED on void, got {lines[0]['line_status']}"
    assert lines[0]["reserved_lbs"] == 200.00, \
        f"reserved_lbs unchanged at 200, got {lines[0]['reserved_lbs']}"


def test_void_packed_event_leaves_lot_reserved_not_consumed(api):
    """PRD §3.7: "A void leaves no poundage permanently consumed."
    PRD §3.7: "the order's PACKED lines return to line_status RESERVED and the
    event's planned_lbs resets to 0, conserving poundage without consuming any."

    Design: Difficulty/compensating_invariant/event_void_conserves_line_packed_poundage
    """
    ctx = fixtures.setup_packed_event(requested_lbs=200, intake_lbs=300)
    agency_id = ctx["agency"]["id"]
    api.void_distribution_event(ctx["event"]["id"], make_agency_coordinator_headers(agency_id))
    # The backing lot's reservation is conserved: still RESERVED, not depleted,
    # and the unreserved remainder (300-200=100) is unchanged.
    lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], OP))
    assert lot["disposition"] == "RESERVED", \
        f"backing lot stays RESERVED after void (no consumption), got {lot['disposition']}"
    assert lot["remaining_lbs"] == 100.00, \
        f"lot remaining_lbs unchanged at 300-200=100, got {lot['remaining_lbs']}"
