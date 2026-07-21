"""Rental reservation, checkout, return, late fees, and overlap protection.

Difficulty: dual_variant_calc (estimated vs final), boundary_precision_check (on-time
return), cross_entity_state_dependency (checkout gated by item), resource_temporal_overlap
(buffered intervals). Corner: state_machines.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
    setup_reserved_rental, setup_checked_out_rental, set_clock,
    make_sale, sale_line, create_rental_payload,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── Difficulty: rental estimated vs final diverges on late return ────────
def test_rental_estimated_charge_pinned_at_checkout(api):
    """PRD §3.7: "a clerk moves the rental RESERVED → CHECKED_OUT, transitions the item
    AVAILABLE → RENTED, and pins the estimated_charge_cents as daily_rate_cents multiplied
    by planned_days. This estimate assumes an on-time return and excludes any late fee."

    Design: Difficulty/dual_variant_calc/rental_estimated_vs_final_diverges_on_late_return
    """
    member, product, item, rental = setup_checked_out_rental(
        daily_rental_rate_cents=500, start_at="2026-07-02T00:00:00Z",
        due_at="2026-07-05T00:00:00Z")
    assert rental["estimated_charge_cents"] == 1500


def test_rental_final_charge_diverges_on_late_return(api):
    """PRD §3.7: "the late fee is that number of late days multiplied by 500 cents per
    late day. Finally, final_charge_cents is pinned as estimated_charge_cents plus
    late_fee_cents; it diverges from the estimate exactly when returned_at is after
    due_at."

    Design: Difficulty/dual_variant_calc/rental_estimated_vs_final_diverges_on_late_return
    """
    member, product, item, rental = setup_checked_out_rental(
        daily_rental_rate_cents=500, start_at="2026-07-02T00:00:00Z",
        due_at="2026-07-05T00:00:00Z")
    set_clock("2026-07-06T00:00:00Z")
    returned = validate_success(api.return_rental(rental["id"], CLERK), 200)
    assert returned["late_fee_cents"] == 500
    assert returned["final_charge_cents"] == 2000
    assert returned["final_charge_cents"] != returned["estimated_charge_cents"]


# ─── Difficulty: return exactly at due → zero late fee ────────────────────
def test_return_exactly_at_due_has_zero_late_fee(api):
    """PRD §3.7: "if returned_at is at or before due_at, the late fee is zero (the
    boundary is inclusive, so a return exactly on time incurs nothing)."

    Design: Difficulty/boundary_precision_check/rental_returned_exactly_at_due_has_zero_late_fee
    """
    member, product, item, rental = setup_checked_out_rental(
        daily_rental_rate_cents=500, start_at="2026-07-02T00:00:00Z",
        due_at="2026-07-05T00:00:00Z")
    set_clock("2026-07-05T00:00:00Z")
    returned = validate_success(api.return_rental(rental["id"], CLERK), 200)
    assert returned["late_fee_cents"] == 0


def test_return_exactly_at_due_final_equals_estimated(api):
    """PRD §3.7: "Finally, final_charge_cents is pinned as estimated_charge_cents plus
    late_fee_cents."
    PRD §3.7: "A clerk returns a CHECKED_OUT rental, moving it CHECKED_OUT → RETURNED."

    Design: Difficulty/boundary_precision_check/rental_returned_exactly_at_due_has_zero_late_fee
    """
    member, product, item, rental = setup_checked_out_rental(
        daily_rental_rate_cents=500, start_at="2026-07-02T00:00:00Z",
        due_at="2026-07-05T00:00:00Z")
    set_clock("2026-07-05T00:00:00Z")
    returned = validate_success(api.return_rental(rental["id"], CLERK), 200)
    assert returned["final_charge_cents"] == 1500
    assert returned["status"] == "RETURNED"


# ─── Difficulty: checkout gated by inventory item status ──────────────────
def test_checkout_rejected_when_item_sold(api):
    """PRD §3.7: "At checkout — allowed only while the rental is RESERVED and the item is
    AVAILABLE ... If the item is not AVAILABLE at checkout time, the checkout is rejected
    with ERR_ITEM_NOT_AVAILABLE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/rental_checkout_gated_by_inventory_item_status
    """
    member, product, item, rental = setup_reserved_rental(
        daily_rental_rate_cents=400, start_at="2026-07-10T00:00:00Z",
        due_at="2026-07-12T00:00:00Z")
    sale_res = make_sale(member["id"], [sale_line(item["id"], 12000, 1)])
    validate_success(sale_res, 201)

    res = api.checkout_rental(rental["id"], CLERK)
    validate_error(res, "ERR_ITEM_NOT_AVAILABLE", expected_status=409)


def test_sale_marks_item_sold_blocking_checkout(api):
    """PRD §3.8: "On a successful sale each line's inventory item transitions
    AVAILABLE → SOLD."
    PRD §3.1: "An inventory item's status starts at AVAILABLE and is one of AVAILABLE,
    RENTED, or SOLD."

    Design: Difficulty/cross_entity_state_dependency/rental_checkout_gated_by_inventory_item_status
    """
    member, product, item, rental = setup_reserved_rental(
        daily_rental_rate_cents=400, start_at="2026-07-10T00:00:00Z",
        due_at="2026-07-12T00:00:00Z")
    make_sale(member["id"], [sale_line(item["id"], 12000, 1)])
    fetched = validate_success(api.get_inventory_item(item["id"], CLERK), 200)
    assert fetched["status"] == "SOLD"


# ─── Difficulty: rental interval with buffer rejects overlap ──────────────
def test_rental_within_buffer_rejected(api):
    """PRD §3.7: "The new reservation conflicts with an existing one when the new start_at
    is earlier than the other rental's due_at plus 24 hours, and simultaneously the other
    rental's start_at is earlier than the new due_at plus 24 hours. ... A conflict is
    rejected with ERR_RENTAL_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rental_interval_with_buffer_rejects_overlap
    """
    member, product, item, rental = setup_reserved_rental(
        daily_rental_rate_cents=300, start_at="2026-07-02T00:00:00Z",
        due_at="2026-07-05T00:00:00Z")
    payload = create_rental_payload(
        member["id"], item["id"], "2026-07-05T12:00:00Z", "2026-07-08T00:00:00Z")
    res = api.create_rental(payload, CLERK)
    validate_error(res, "ERR_RENTAL_OVERLAP", expected_status=409)


def test_rental_exactly_buffer_apart_accepted(api):
    """PRD §3.7: "Two rentals that are exactly the buffer apart do not conflict and are
    accepted."

    Design: Difficulty/resource_temporal_overlap/rental_interval_with_buffer_rejects_overlap
    """
    member, product, item, rental = setup_reserved_rental(
        daily_rental_rate_cents=300, start_at="2026-07-02T00:00:00Z",
        due_at="2026-07-05T00:00:00Z")
    payload = create_rental_payload(
        member["id"], item["id"], "2026-07-06T00:00:00Z", "2026-07-09T00:00:00Z")
    res = api.create_rental(payload, CLERK)
    accepted = validate_success(res, 201)
    assert accepted["status"] == "RESERVED"


# ─── Corner: state_machines / return an already-returned rental ───────────
def test_return_already_returned_rental_rejected(api):
    """PRD §3.7: "A clerk returns a CHECKED_OUT rental, moving it CHECKED_OUT → RETURNED."
    PRD §2.11: "then the target resource being in a legal state for the requested
    transition (ERR_INVALID_STATE, 409)."

    Design: Corner/state_machines/return_already_returned_rental_rejected
    """
    member, product, item, rental = setup_checked_out_rental(
        daily_rental_rate_cents=200, start_at="2026-07-02T00:00:00Z",
        due_at="2026-07-04T00:00:00Z")
    validate_success(api.return_rental(rental["id"], CLERK), 200)
    res = api.return_rental(rental["id"], CLERK)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
