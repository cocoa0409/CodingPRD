"""Work-order completion, RepairRecord, and parts-cost calculation."""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    assert_repair_record,
    assert_work_order,
    BULK_DISCOUNT_FACTOR,
    BULK_QTY_THRESHOLD,
    accept_work_order,
    complete_payload,
    complete_work_order,
    create_requisition,
    create_spare_part,
    find_part_replaced,
    issue_requisition,
    make_site_manager_headers,
    make_technician_headers,
    return_requisition,
    setup_for_parts_cost_pinned_rounding,
    setup_pending_workorder,
    setup_started_workorder,
    start_work_order,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# 3.6 + 3.8 — parts_cost calculation: pinned per-line-then-sum order
# ---------------------------------------------------------------------------
def test_parts_cost_per_line_then_sum_pinned_order(api):
    """PRD §3.8: 'Per-line, before any summation: if the used quantity is
    at least 10, the line cost is replaced by the floor of itself
    multiplied by 0.90 (a 10% bulk discount, rounded down to the nearest
    cent). The work order's parts_cost_cents is the sum of every line cost
    obtained this way. The pinned variant of the calculation applies
    discount and floor on each line and only then sums; the alternative
    ordering — first sum all lines, then apply discount retroactively to
    lines whose used quantity was at least 10 — is not the canonical order
    and produces a different cents value on mixed-bulk requisitions; only
    the per-line-then-sum order is correct.'

    Case: two ISSUED requisitions, qty=11 each, unit_cost_cents=191.
    PINNED  = floor(11*191*0.9) + floor(11*191*0.9) = 1890 + 1890 = 3780
    REJECTED = floor((11*191 + 11*191) * 0.9) = floor(3781.8) = 3781
    Asserted value 3780 distinguishes the two orderings.
    # difficulty: combinatorial_formula/parts_cost_mode_b_pinned_rounding_order
    """
    bag = setup_for_parts_cost_pinned_rounding()
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    tech_id = bag["technician"]["id"]
    res = api.complete_work_order(
        site_id, wo_id, complete_payload(),
        make_technician_headers(tech_id),
    )
    wo_completed = validate_success(res, expected_status=200)
    assert wo_completed["status"] == "COMPLETED"
    assert wo_completed["parts_cost_cents"] == 3780, (
        "PRD §3.8 pinned order: floor(11*191*0.9) + floor(11*191*0.9) "
        "== 1890 + 1890 == 3780. The rejected sum-then-discount order "
        "would yield 3781."
    )


def test_parts_cost_pinned_order_distinguishable_from_alternative(api):
    """PRD §3.8: 'the alternative ordering — first sum all lines, then
    apply discount retroactively to lines whose used quantity was at
    least 10 — is not the canonical order and produces a different cents
    value on mixed-bulk requisitions; only the per-line-then-sum order is
    correct.'

    A second case proving the rounding order is observable on a different
    cost configuration. Two ISSUED requisitions, qty=11 each,
    unit_cost_cents=137.
    PINNED  = floor(11*137*0.9) + floor(11*137*0.9) = 1356 + 1356 = 2712
    REJECTED = floor((11*137 + 11*137) * 0.9) = floor(3014 * 0.9) =
               floor(2712.6) = 2712 — wait, this collides. Use 191 again
               for safety; we use a single bulk + non-bulk mix where the
               two orders diverge.

    Three-line mix: qty=11 (bulk), qty=11 (bulk), qty=9 (non-bulk),
    unit_cost=191 each.
    PINNED   = floor(11*191*0.9) + floor(11*191*0.9) + (9*191) = 1890+1890+1719 = 5499
    REJECTED would discount the qty=9 line retroactively differently;
    in either case the asserted PINNED 5499 fixes the answer.
    # difficulty: combinatorial_formula/parts_cost_mode_b_pinned_rounding_order
    """
    bag = setup_started_workorder()
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    tech_id = bag["technician"]["id"]
    p1 = create_spare_part(
        site_id, unit_cost_cents=191, stock_on_hand=20, reorder_point=0,
    )
    p2 = create_spare_part(
        site_id, unit_cost_cents=191, stock_on_hand=20, reorder_point=0,
    )
    p3 = create_spare_part(
        site_id, unit_cost_cents=191, stock_on_hand=20, reorder_point=0,
    )
    r1 = create_requisition(site_id, wo_id, p1["id"], 11)
    r2 = create_requisition(site_id, wo_id, p2["id"], 11)
    r3 = create_requisition(site_id, wo_id, p3["id"], 9)
    issue_requisition(site_id, wo_id, r1["id"])
    issue_requisition(site_id, wo_id, r2["id"])
    issue_requisition(site_id, wo_id, r3["id"])
    res = api.complete_work_order(
        site_id, wo_id, complete_payload(),
        make_technician_headers(tech_id),
    )
    completed = validate_success(res, expected_status=200)
    # 1890 + 1890 + 1719 = 5499
    assert completed["parts_cost_cents"] == 5499


def test_parts_cost_excludes_cancelled_requisitions(api, storekeeper_headers):
    """PRD §3.8: 'It walks every Requisition linked to the work order whose
    status is ISSUED ... cancelled rows are excluded'.
    """
    from test_helpers import cancel_requisition
    bag = setup_started_workorder()
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    tech_id = bag["technician"]["id"]
    spare1 = create_spare_part(
        site_id, unit_cost_cents=300, stock_on_hand=20, reorder_point=0,
    )
    spare2 = create_spare_part(
        site_id, unit_cost_cents=200, stock_on_hand=20, reorder_point=0,
    )
    # Pause the WO so we can create requisitions; create+issue req1, then
    # create+CANCEL req2 before completion.
    req1 = create_requisition(site_id, wo_id, spare1["id"], 2)
    issue_requisition(site_id, wo_id, req1["id"])
    req2 = create_requisition(site_id, wo_id, spare2["id"], 5)
    cancel_requisition(site_id, wo_id, req2["id"])  # req2 → CANCELLED
    res = api.complete_work_order(
        site_id, wo_id, complete_payload(), make_technician_headers(tech_id),
    )
    completed = validate_success(res, expected_status=200)
    # qty_used_R1 = 2 (no return); 2 < 10 → no bulk discount.
    # parts_cost = 2 * 300 = 600. CANCELLED row is excluded.
    assert completed["parts_cost_cents"] == 600


def test_parts_cost_no_bulk_discount_below_threshold(api, storekeeper_headers):
    """PRD §3.8: 'if the used quantity is at least 10, the line cost is
    replaced by the floor of itself multiplied by 0.90'. Below threshold,
    no discount.
    """
    bag = setup_started_workorder()
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    tech_id = bag["technician"]["id"]
    spare = create_spare_part(
        site_id, unit_cost_cents=500, stock_on_hand=20, reorder_point=0,
    )
    req = create_requisition(site_id, wo_id, spare["id"], 9)  # < 10
    issue_requisition(site_id, wo_id, req["id"])
    res = api.complete_work_order(
        site_id, wo_id, complete_payload(), make_technician_headers(tech_id),
    )
    completed = validate_success(res, expected_status=200)
    # Used=9 < 10 → no discount: line_cost = 9 * 500 = 4500
    assert completed["parts_cost_cents"] == 4500


# ---------------------------------------------------------------------------
# 3.6 — RepairRecord shape and parts_replaced snapshot
# ---------------------------------------------------------------------------
def test_repair_record_parts_replaced_snapshot(api, storekeeper_headers):
    """PRD §3.6: 'a new RepairRecord is created with the body fields, and
    its parts_replaced array is built as a snapshot of every ISSUED
    requisition with qty_used equal to qty − returned_qty (plus the
    underlying requisition_id, part_id, qty_used, and unit_cost_cents)'.
    """
    bag = setup_started_workorder()
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    tech_id = bag["technician"]["id"]
    spare = create_spare_part(
        site_id, unit_cost_cents=250, stock_on_hand=20, reorder_point=0,
    )
    req = create_requisition(site_id, wo_id, spare["id"], 5)
    issue_requisition(site_id, wo_id, req["id"])
    return_requisition(site_id, wo_id, req["id"], 2)  # qty_used = 5-2 = 3
    res = api.complete_work_order(
        site_id, wo_id, complete_payload(), make_technician_headers(tech_id),
    )
    completed = validate_success(res, expected_status=200)
    # parts_cost = 3 * 250 = 750 (3 < 10 so no discount)
    assert completed["parts_cost_cents"] == 750

    rr = validate_success(
        api.get_repair_record(
            site_id, wo_id, make_technician_headers(tech_id),
        ),
        expected_status=200,
    )
    assert_repair_record(rr)
    row = find_part_replaced(rr["parts_replaced"], req["id"])
    assert row is not None, "PRD §3.6: parts_replaced has one row per ISSUED req"
    assert row["part_id"] == spare["id"]
    assert row["qty_used"] == 3
    assert row["unit_cost_cents"] == 250


def test_post_completion_return_does_not_recompute_parts_cost(
        api, storekeeper_headers):
    """PRD §3.8: 'If the work order is already COMPLETED, the snapshot of
    RepairRecord.parts_replaced and WorkOrder.parts_cost_cents taken at
    completion is final — neither is recomputed by a post-completion
    return.'
    """
    bag = setup_started_workorder()
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    tech_id = bag["technician"]["id"]
    spare = create_spare_part(
        site_id, unit_cost_cents=400, stock_on_hand=20, reorder_point=0,
    )
    req = create_requisition(site_id, wo_id, spare["id"], 5)
    issue_requisition(site_id, wo_id, req["id"])
    res = api.complete_work_order(
        site_id, wo_id, complete_payload(), make_technician_headers(tech_id),
    )
    completed = validate_success(res, expected_status=200)
    cost_at_completion = completed["parts_cost_cents"]
    assert cost_at_completion == 5 * 400  # 2000

    # Post-completion partial return: should NOT recompute parts_cost_cents
    return_requisition(site_id, wo_id, req["id"], 2)
    wo_after_return = validate_success(
        api.get_work_order(site_id, wo_id, make_technician_headers(tech_id)),
        expected_status=200,
    )
    assert wo_after_return["parts_cost_cents"] == cost_at_completion, \
        "PRD §3.8: post-completion return must not recompute parts_cost_cents"


# ---------------------------------------------------------------------------
# 3.6 — acceptance: evidence presence
# ---------------------------------------------------------------------------
def test_accept_rejects_when_evidence_missing(api):
    """PRD §3.6: 'The associated RepairRecord must already exist and must
    carry both a non-empty before_evidence_url and a non-empty
    after_evidence_url; if either is missing or empty, the acceptance is
    rejected with ERR_EVIDENCE_MISSING.'
    """
    responsible_user_id = "owner-evidence-missing"
    bag = setup_started_workorder(responsible_user_id=responsible_user_id)
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    tech_id = bag["technician"]["id"]
    # Complete with empty before_evidence_url
    payload = complete_payload(before_evidence_url="")
    api.complete_work_order(
        site_id, wo_id, payload, make_technician_headers(tech_id),
    )
    res = api.accept_work_order(
        site_id, wo_id, make_site_manager_headers(responsible_user_id),
    )
    validate_error(res, "ERR_EVIDENCE_MISSING", expected_status=422)


def test_accept_writes_acceptance_user_and_at(api):
    """PRD §3.6: 'On a successful acceptance, RepairRecord.acceptance_user_id
    is set to X-User-ID, RepairRecord.acceptance_at is set to the current
    site clock'.
    """
    responsible_user_id = "owner-accept-001"
    bag = setup_started_workorder(responsible_user_id=responsible_user_id)
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    tech_id = bag["technician"]["id"]
    complete_work_order(site_id, wo_id, tech_id)
    accept_work_order(site_id, wo_id, responsible_user_id)
    rr = validate_success(
        api.get_repair_record(
            site_id, wo_id, make_site_manager_headers(responsible_user_id),
        ),
        expected_status=200,
    )
    assert rr["acceptance_user_id"] == responsible_user_id
    assert rr["acceptance_at"] is not None
