"""Queue A (depth) — non-linear state machines: the spec brand-review revision
cycle and the purchase order's two parallel axes with their cross-axis guard.
"""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    create_procurement_project, create_spec, submit_spec, brand_review,
    run_pipeline, advance_po_to_ready_to_ship,
    TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]


# ── rule: non_linear_state_machine (spec revision cycle) ───

def _rejected_spec():
    base = create_procurement_project(
        name="P-NL1", brand_program="INDIE_SOFT",
        total_budget_cents=5_000_000, budgeted_cents=4_000_000,
    )
    spec = create_spec(
        base["project"]["id"],
        category="FURNITURE", description="Headboard",
        brand_standard_ref="IS-HB", quantity_per_room=1, room_count=30,
        unit_budget_cents=90000,
    )
    submit_spec(spec["id"])
    brand_review(spec["id"], "REJECT", notes="fabric off-standard")
    return base, spec["id"]


def test_resubmit_from_brand_rejected_closes_revision_loop(api):
    """PRD §3.2: "Submission moves a spec from `DRAFT` to `SUBMITTED`; the same
    action resubmits a spec from `BRAND_REJECTED` back to `SUBMITTED`, closing the
    revision loop, and the loop is unbounded. From any other state the attempt
    fails with `ERR_SPEC_NOT_SUBMITTABLE`."
    After a REJECT decision the spec is BRAND_REJECTED, and submit moves it back
    to SUBMITTED.

    Design: Difficulty/non_linear_state_machine/spec_brand_review_revision_cycle
    """
    _base, spec_id = _rejected_spec()

    rejected = validate_success(api_client.get_spec_item(spec_id, PA))
    assert rejected["status"] == "BRAND_REJECTED"

    resubmitted = validate_success(api_client.submit_spec_item(spec_id, PA), 200)
    assert resubmitted["status"] == "SUBMITTED", (
        "submit from BRAND_REJECTED must succeed and return the spec to SUBMITTED"
    )


def test_revision_loop_terminates_in_brand_approved(api):
    """PRD §3.2: "The `BrandApprover` then records a brand-standard `decision` of
    `APPROVE` or `REJECT`, with optional `notes`, on a spec currently `SUBMITTED`
    — otherwise `ERR_SPEC_NOT_IN_REVIEW` — moving it to `BRAND_APPROVED` or
    `BRAND_REJECTED` respectively."
    After the resubmission leg of the cycle, a second brand review APPROVE moves
    the spec to BRAND_APPROVED.

    Design: Difficulty/non_linear_state_machine/spec_brand_review_revision_cycle
    """
    _base, spec_id = _rejected_spec()

    resubmitted = validate_success(api_client.submit_spec_item(spec_id, PA), 200)
    assert resubmitted["status"] == "SUBMITTED"

    approved = validate_success(
        api_client.brand_review_spec_item(spec_id, {"decision": "APPROVE"},
                                          TEST_USERS["brand_approver_headers"]),
        200,
    )
    assert approved["status"] == "BRAND_APPROVED"

    final = validate_success(api_client.get_spec_item(spec_id, PA))
    assert final["status"] == "BRAND_APPROVED"


# ── rule: non_linear_state_machine (PO parallel axes) ──────

def _po_ready_to_ship_with_line():
    scenario = run_pipeline(
        name="P-NL2", brand_program="MARQUEE_LUXE",
        total_budget_cents=5_000_000, budgeted_cents=4_000_000,
        line_specs=[{
            "description": "Sofa", "brand_standard_ref": "ML-SF",
            "quantity_per_room": 1, "room_count": 10,
            "unit_budget_cents": 10000, "unit_price_cents": 10000,
            "lead_time_days": 5,
            "quantity_ordered": 10, "declared_cube_m3": 5,
        }],
        attach=False, seal=False, depart=False,
    )
    advance_po_to_ready_to_ship(scenario["po"]["id"])
    return scenario


def test_invoice_axis_advances_independently_of_fulfillment(api):
    """PRD §3.4: "The invoice axis, walked with an `axis` of `INVOICE` and
    belonging to the `PurchasingAgent`, runs `UNBILLED` to `PARTIALLY_INVOICED` to
    `INVOICED` to `PAID`, with a direct hop from `UNBILLED` to `INVOICED` also
    legal."
    PRD §3.4: "Otherwise the axes are genuinely independent — an order may be
    `INVOICED` while fulfillment is still `ISSUED`, or `ACKNOWLEDGED` while the
    invoice is `UNBILLED`; only `PAID` and `CLOSED` look across."
    The direct hop UNBILLED -> INVOICED lands while fulfillment stays
    READY_TO_SHIP.

    Design: Difficulty/non_linear_state_machine/po_parallel_fulfillment_invoice_axes
    """
    scenario = _po_ready_to_ship_with_line()
    po_id = scenario["po"]["id"]

    updated = validate_success(
        api_client.transition_purchase_order(
            po_id, {"axis": "INVOICE", "to_status": "INVOICED"}, PA
        ),
        200,
    )
    assert updated["invoice_status"] == "INVOICED"
    assert updated["fulfillment_status"] == "READY_TO_SHIP", (
        "the fulfillment axis must not move when the invoice axis advances"
    )


def test_invoice_paid_blocked_until_fulfillment_delivered(api):
    """PRD §3.4: "The single cross-axis guard sits at payment: `INVOICED` to
    `PAID` requires fulfillment to be `DELIVERED` or `CLOSED`, else
    `ERR_INVOICE_BEFORE_DELIVERY`."
    While fulfillment is READY_TO_SHIP the PAID transition is rejected and the
    invoice axis stays INVOICED.

    Design: Difficulty/non_linear_state_machine/po_parallel_fulfillment_invoice_axes
    """
    scenario = _po_ready_to_ship_with_line()
    po_id = scenario["po"]["id"]

    validate_success(
        api_client.transition_purchase_order(
            po_id, {"axis": "INVOICE", "to_status": "INVOICED"}, PA
        ),
        200,
    )
    res = api_client.transition_purchase_order(
        po_id, {"axis": "INVOICE", "to_status": "PAID"}, PA
    )
    validate_error(res, ApiErrorId.ERR_INVOICE_BEFORE_DELIVERY, expected_status=409)

    po = validate_success(api_client.get_purchase_order(po_id, PA))
    assert po["invoice_status"] == "INVOICED", (
        "a rejected PAID attempt must leave the invoice axis at INVOICED"
    )
    assert po["fulfillment_status"] == "READY_TO_SHIP"
