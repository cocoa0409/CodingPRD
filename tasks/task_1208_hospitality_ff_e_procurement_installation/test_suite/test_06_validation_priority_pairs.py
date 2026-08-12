"""Queue A (depth) — pinned validation order when two failure categories are
simultaneously tripped: state over fiscal at change-order apply, and
referential over fiscal at PO-line creation.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_procurement_project, create_approved_spec, create_bid,
    sample_decide, award, create_po, propose_change_order,
    get_budget_line, get_project, current_project_version,
    make_purchasing_agent_headers, make_owner_rep_headers, TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]
PA_1 = make_purchasing_agent_headers("pa-1")
OWNER_1 = make_owner_rep_headers("owner-1")
OWNER_2 = make_owner_rep_headers("owner-2")


# ── rule: priority_pair_validation_conflict (state/fiscal) ─

def _rejected_unfunded_change_order():
    """Project (total 10000000c, unallocated 100000c) in PROCUREMENT with a
    FURNITURE line of 9000000c; a +500000c draw proposed by pa-1 (unfunded: the
    draw plus its fee exceeds the 100000c contingency) and already REJECTED."""
    base = create_procurement_project(
        name="P-PP1", total_budget_cents=10_000_000,
        unallocated_contingency_cents=100_000, budgeted_cents=9_000_000,
    )
    project, budget_line = base["project"], base["budget_line"]
    change_order = propose_change_order(
        project["id"],
        [{"budget_line_id": budget_line["id"], "delta_cents": 500000}],
        title="CO1 unfunded draw", proposer_headers=PA_1,
    )
    validate_success(api_client.reject_change_order(change_order["id"], OWNER_1))
    return project, budget_line, change_order


def test_apply_of_rejected_change_order_reports_state_not_fiscal(api):
    """PRD §2.8: "Every write request passes through a fixed, prioritized
    validation cascade; a failure at an earlier stage masks all later stages."
    PRD §3.9: "The order must still be `PROPOSED` — this guard covers both
    re-applying an already `APPLIED` order and deciding an already `REJECTED` one
    — else `ERR_CO_NOT_PROPOSED`."
    The draw is also unfunded (500000c plus fee against 100000c contingency, a
    stage-11 fiscal failure), but the stage-5 state failure is what surfaces.

    Design: Difficulty/priority_pair_validation_conflict/co_approve_state_before_fiscal
    """
    project, _budget_line, change_order = _rejected_unfunded_change_order()
    version = current_project_version(project["id"])

    res = api_client.apply_change_order(
        change_order["id"], {"expected_project_version": version}, OWNER_2
    )
    validate_error(res, ApiErrorId.ERR_CO_NOT_PROPOSED, expected_status=409)


def test_rejected_change_order_apply_mutates_nothing(api):
    """PRD §3.9: "Rejection, by contrast, moves the order from `PROPOSED` to
    `REJECTED` with the same segregation-of-duties bar, bumps the order's
    `version`, and touches no budget figures."
    After the rejected apply attempt, the change order stays REJECTED and neither
    the budget line nor the contingency moves.

    Design: Difficulty/priority_pair_validation_conflict/co_approve_state_before_fiscal
    """
    project, budget_line, change_order = _rejected_unfunded_change_order()
    version = current_project_version(project["id"])

    api_client.apply_change_order(
        change_order["id"], {"expected_project_version": version}, OWNER_2
    )

    co_after = validate_success(api_client.get_change_order(change_order["id"], PA))
    assert co_after["status"] == "REJECTED"
    assert co_after["fee_cents"] is None

    bl_after = get_budget_line(budget_line["id"])
    assert bl_after["budgeted_cents"] == 9_000_000
    project_after = get_project(project["id"])
    assert project_after["unallocated_contingency_cents"] == 100000
    assert project_after["sunk_fees_cents"] == 0


# ── rule: priority_pair_validation_conflict (referential/fiscal) ──

def _po_for_other_vendor():
    """Project in PROCUREMENT; FURNITURE budget line of only 1000c; spec
    approved and awarded to VENDA at 15000c unit; PO created for OTHERV."""
    base = create_procurement_project(
        name="P-PP2", total_budget_cents=10_000_000, budgeted_cents=1000,
    )
    project, budget_line = base["project"], base["budget_line"]
    spec = create_approved_spec(
        project["id"], category="FURNITURE", description="Guest chair",
        brand_standard_ref="MS-GR-01", quantity_per_room=2, room_count=20,
        unit_budget_cents=15000,
    )
    bid = create_bid(
        spec["id"], vendor_name="VENDA", unit_price_cents=15000,
        freight_estimate_cents=0, lead_time_days=14,
    )
    sample_decide(bid["id"], "APPROVED")
    award(bid["id"])
    po = create_po(project["id"], vendor_name="OTHERV")
    return project, budget_line, spec, po


def test_line_add_reports_missing_awarded_bid_before_fiscal(api):
    """PRD §3.4: "A bid in `AWARDED` or `ORDERED` status must exist pairing that
    spec with the PO's `vendor_name`, else `ERR_NO_AWARDED_BID`."
    PRD §2.8: "Every write request passes through a fixed, prioritized validation
    cascade; a failure at an earlier stage masks all later stages."
    The OTHERV purchase order has no awarded bid for the spec (stage-8
    referential failure), and the line's 600000c extended would also breach the
    1000c budget line (stage-11 fiscal failure); the referential error surfaces.

    Design: Difficulty/priority_pair_validation_conflict/line_add_referential_before_fiscal
    """
    _project, _budget_line, spec, po = _po_for_other_vendor()

    res = api_client.add_purchase_order_line(
        po["id"],
        {"spec_item_id": spec["id"], "quantity_ordered": 40,
         "declared_cube_m3": 10},
        PA,
    )
    validate_error(res, ApiErrorId.ERR_NO_AWARDED_BID, expected_status=409)


def test_rejected_referential_line_add_creates_no_po_line(api):
    """PRD §3.4: "A bid in `AWARDED` or `ORDERED` status must exist pairing that
    spec with the PO's `vendor_name`, else `ERR_NO_AWARDED_BID`."
    The rejected add persists nothing: the spec's PO-line listing is empty.

    Design: Difficulty/priority_pair_validation_conflict/line_add_referential_before_fiscal
    """
    _project, _budget_line, spec, po = _po_for_other_vendor()

    res = api_client.add_purchase_order_line(
        po["id"],
        {"spec_item_id": spec["id"], "quantity_ordered": 40,
         "declared_cube_m3": 10},
        PA,
    )
    validate_error(res, ApiErrorId.ERR_NO_AWARDED_BID, expected_status=409)

    lines, meta = validate_paginated(
        api_client.list_spec_item_po_lines(spec["id"], PA)
    )
    assert lines == [] and meta["total_count"] == 0, (
        "a rejected line add must not persist a PO line"
    )

    po_lines, po_meta = validate_paginated(
        api_client.list_purchase_order_lines(po["id"], PA)
    )
    assert po_lines == [] and po_meta["total_count"] == 0
