"""WorkOrder release: cross-entity gates, OCC, validation precedence.

Translates queue A cross_entity_state_dependency (release requires quote
approved), priority_pair_validation_conflict (state vs referential on release),
and queue B validations (qty_started, material_not_allocated) plus
cross_cutting_complexity_layers OCC instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_approved_quote, create_priced_quote, receive_lot,
    create_planned_work_order, create_allocated_work_order,
    TEST_USERS,
)

ADMIN = TEST_USERS["shop_admin_headers"]
EST = TEST_USERS["estimator_headers"]
MAT = TEST_USERS["material_controller_headers"]


def test_workorder_release_requires_quote_approved(api):
    """PRD §3.3: "Release additionally enforces three cross-cutting
    preconditions: the owning quote must be APPROVED, failing with
    ERR_QUOTE_NOT_APPROVED".

    The WO is PLANNED with material allocated, but its quote is only PRICED.

    Design: Difficulty/cross_entity_state_dependency/workorder_release_requires_quote_approved
    """
    rfq, pl, priced, ops = create_priced_quote(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 5.0, "setup_fee_cents": 2000}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 2},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="CUST-13",
    )
    receive_lot("AL_6061", 2, 1000, "2026-06-01T00:00:00Z", heat_number="H-XA")
    wo = create_planned_work_order(priced["id"], pl["id"], qty_ordered=2, qty_started=2)
    wo = validate_success(api.allocate_material(wo["id"], MAT), 200)
    res = api.release_work_order(wo["id"], {"expected_work_order_version": wo["version"]}, ADMIN)
    validate_error(res, "ERR_QUOTE_NOT_APPROVED")


def test_release_planned_wo_with_priced_quote_state_is_valid_block_is_referential(api):
    """PRD §2.9: "Cross-entity referential preconditions — for example, releasing
    a work order requires its quote to be approved ... these yield
    ERR_QUOTE_NOT_APPROVED".

    The WO's own state is the valid PLANNED start state for release; the only
    block is the referenced quote being unapproved.

    Design: Difficulty/cross_entity_state_dependency/workorder_release_requires_quote_approved
    """
    rfq, pl, priced, ops = create_priced_quote(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 5.0, "setup_fee_cents": 2000}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 2},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="CUST-13b",
    )
    receive_lot("AL_6061", 2, 1000, "2026-06-01T00:00:00Z", heat_number="H-XA2")
    wo = create_planned_work_order(priced["id"], pl["id"], qty_ordered=2, qty_started=2)
    assert wo["status"] == "PLANNED"
    wo = validate_success(api.allocate_material(wo["id"], MAT), 200)
    res = api.release_work_order(wo["id"], {"expected_work_order_version": wo["version"]}, ADMIN)
    validate_error(res, "ERR_QUOTE_NOT_APPROVED")


def test_state_precedes_referential_release_on_cancelled_wo(api):
    """PRD §2.9: "When several validations could fire on a single request, they
    are evaluated in a fixed order, and the first to fail determines the
    response." with state legality (#5) ahead of cross-entity referential (#7).
    PRD §2.9: "a request that violates several rules at once always reports the
    failure highest in this list."

    A CANCELLED WO (whose quote is APPROVED — referential would pass — but is
    irrelevant) released must report ERR_INVALID_STATE, not the referential check.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_referential_release_invalid_state_wins
    """
    rfq, pl, quote, ops = create_approved_quote(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 5.0, "setup_fee_cents": 2000}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 2},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="CUST-9",
    )
    wo = create_planned_work_order(quote["id"], pl["id"], qty_ordered=2, qty_started=2)
    wo_version = wo["version"]
    validate_success(api.cancel_work_order(wo["id"], ADMIN), 200)
    res = api.release_work_order(wo["id"], {"expected_work_order_version": wo_version}, ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


def test_terminal_cancelled_wo_release_not_referential_error(api):
    """PRD §2.9: "the target resource must currently be in a state from which the
    requested transition is defined; otherwise ERR_INVALID_STATE (409)."
    PRD §3.3: "Both CLOSED and CANCELLED are terminal work-order states."

    A second illustration: a PLANNED->CANCELLED WO offers no defined release
    transition, so the state check (#5) fires ahead of the quote-approval
    referential check (#7).

    Design: Difficulty/priority_pair_validation_conflict/state_vs_referential_release_invalid_state_wins
    """
    rfq, pl, quote, ops = create_approved_quote(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 5.0, "setup_fee_cents": 2000}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 2},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="CUST-9b",
    )
    wo = create_planned_work_order(quote["id"], pl["id"], qty_ordered=2, qty_started=2)
    stale_version = wo["version"]
    api.cancel_work_order(wo["id"], ADMIN)
    res = api.release_work_order(wo["id"], {"expected_work_order_version": stale_version}, ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


def test_release_with_qty_started_below_ordered_rejected(api):
    """PRD §3.3: "qty_started must be at least qty_ordered (started quantity may
    exceed ordered quantity to cover scrap, but must never be lower), failing
    with ERR_INVALID_QTY_STARTED."

    Design: Corner/validations/release_with_qty_started_below_ordered_rejected
    """
    rfq, pl, quote, ops = create_approved_quote(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 4.0, "setup_fee_cents": 1000}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 5},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="C-25",
    )
    receive_lot("AL_6061", 5, 1000, "2026-06-01T00:00:00Z", heat_number="H-QtyB")
    wo = create_planned_work_order(quote["id"], pl["id"], qty_ordered=5, qty_started=2)
    wo = validate_success(api.allocate_material(wo["id"], MAT), 200)
    res = api.release_work_order(wo["id"], {"expected_work_order_version": wo["version"]}, ADMIN)
    validate_error(res, "ERR_INVALID_QTY_STARTED")


def test_release_without_material_allocated_rejected(api):
    """PRD §3.3: "the work order's material must already be allocated
    (material_allocated true), failing with ERR_MATERIAL_NOT_ALLOCATED".

    Design: Corner/validations/release_without_material_allocated_rejected
    """
    rfq, pl, quote, ops = create_approved_quote(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 4.0, "setup_fee_cents": 1000}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 3},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="C-26",
    )
    wo = create_planned_work_order(quote["id"], pl["id"], qty_ordered=3, qty_started=3)
    res = api.release_work_order(wo["id"], {"expected_work_order_version": wo["version"]}, ADMIN)
    validate_error(res, "ERR_MATERIAL_NOT_ALLOCATED")


def test_occ_quote_approve_stale_version_rejected(api):
    """PRD §3.2: "this is one of the two optimistic-concurrency-guarded
    operations, so the request must carry expected_quote_version matching the
    quote's current version, failing with ERR_STALE_VERSION otherwise."

    Design: Corner/cross_cutting_complexity_layers/occ_quote_approve_stale_version_rejected
    """
    rfq, pl, priced, ops = create_priced_quote(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 4.0, "setup_fee_cents": 1000}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 3},
        quote_overrides={"material_unit_cost_cents": 800, "scrap_allowance_pct": 0},
        customer_id="C-37",
    )
    res = api.approve_quote(
        priced["id"], {"expected_quote_version": priced["version"] - 1}, EST)
    validate_error(res, "ERR_STALE_VERSION")


def test_occ_wo_release_stale_version_rejected(api):
    """PRD §2.8: "Material allocation, machine-slot booking that schedules the
    work order's operations, and routing-operation completion all advance a work
    order's version between its creation and its release; if the
    expected_work_order_version supplied on release does not equal the work
    order's current version, the release is rejected with ERR_STALE_VERSION".

    The pre-allocation version is captured, allocation bumps the version, and the
    stale release is refused.

    Design: Corner/cross_cutting_complexity_layers/occ_wo_release_stale_version_rejected
    """
    rfq, pl, quote, ops = create_approved_quote(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 4.0, "setup_fee_cents": 1000}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 3},
        quote_overrides={"material_unit_cost_cents": 800, "scrap_allowance_pct": 0},
        customer_id="C-38",
    )
    receive_lot("AL_6061", 3, 800, "2026-06-01T00:00:00Z", heat_number="H-OccW")
    wo = create_planned_work_order(quote["id"], pl["id"], qty_ordered=3, qty_started=3)
    stale_version = wo["version"]
    validate_success(api.allocate_material(wo["id"], MAT), 200)  # bumps version
    res = api.release_work_order(wo["id"], {"expected_work_order_version": stale_version}, ADMIN)
    validate_error(res, "ERR_STALE_VERSION")
