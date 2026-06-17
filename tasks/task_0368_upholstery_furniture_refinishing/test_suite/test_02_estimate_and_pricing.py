"""Per-piece pricing, estimate authoring, the revision loop, turnaround, deposit gate.

Per-piece subtotal rounding, the tiered rush surcharge, the cyclic revision loop and
its supersede cascade, optimistic-concurrency on estimate authoring, turnaround bands,
the deposit gate, and immediate balance reconciliation.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_line_item_payload,
    register_customer, register_fabric_sku, register_foam_spec,
    open_intake_work_order, create_estimating_work_order, create_awaiting_approval_order,
    author_estimate, current_version, get_work_order, reupholstery_line_item,
    make_customer_headers, factories,
    TEST_USERS,
)

CLERK = TEST_USERS["intake_clerk_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
MANAGER = TEST_USERS["shop_manager_headers"]


# ---------------------------------------------------------------------------
# Per-piece subtotal — round-each-term-then-sum (mode b)
# ---------------------------------------------------------------------------
def test_per_piece_subtotal_rounds_each_term_then_sums(api):
    """PRD §2.6: "each individual cost term is rounded to the nearest whole cent using the
    round-half-up convention *before* terms are summed; the system rounds per term and then
    adds, never the reverse."
    PRD §3.2: "Each of these three components is rounded individually before they are added,
    and the `piece_subtotal_cents` is their sum."

    Design: Difficulty/combinatorial_formula/per_piece_subtotal_round_per_term_then_sum_mode_b
    """
    fab = register_fabric_sku(price_cents_per_yard=1799)
    foam = register_foam_spec(price_cents_per_board_foot=333)
    _, wo = open_intake_work_order(service_type="REUPHOLSTERY")
    li = validate_success(api.create_line_item(
        wo["id"],
        reupholstery_line_item(fab["id"], yardage_required=6.5, labor_hours=3.5,
                               foam_spec_id=foam["id"], board_feet_required=7.5,
                               piece_label="Loveseat"),
        CLERK,
    ), 201)
    # labor 3.5*6500=22750 ; fabric 6.5*1799=11693.5->11694 ; foam 7.5*333=2497.5->2498
    assert li["piece_subtotal_cents"] == 36942


def test_per_piece_subtotal_round_per_term_then_sum_mode_b_dup(api):
    """PRD §2.6: "Wherever a calculation multiplies a quantity by a per-unit price, each
    individual cost term is rounded to the nearest whole cent using the round-half-up
    convention *before* terms are summed; the system rounds per term and then adds, never
    the reverse. This per-term rounding applies to labor cost, fabric cost, and foam cost
    alike."

    Design: Difficulty/combinatorial_formula/per_piece_subtotal_round_per_term_then_sum_mode_b
    """
    fab = register_fabric_sku(price_cents_per_yard=1799)
    foam = register_foam_spec(price_cents_per_board_foot=333)
    _, wo = open_intake_work_order(service_type="REUPHOLSTERY")
    li = validate_success(api.create_line_item(
        wo["id"],
        reupholstery_line_item(fab["id"], yardage_required=6.5, labor_hours=3.5,
                               foam_spec_id=foam["id"], board_feet_required=7.5,
                               piece_label="Loveseat2"),
        CLERK,
    ), 201)
    assert li["piece_subtotal_cents"] == 36942


# ---------------------------------------------------------------------------
# Rush surcharge — tiered non-linear (mode a)
# ---------------------------------------------------------------------------
def test_rush_surcharge_tiered_above_tier1(api):
    """PRD §3.3: "If `labor_total_cents` exceeds 50000 cents, the surcharge is the sum of two
    rounded terms: 15 percent of the first 50000 cents, plus 30 percent of the portion of
    `labor_total_cents` above 50000 cents — each of the two terms rounded to whole cents
    before they are added."

    Design: Difficulty/combinatorial_formula/rush_surcharge_tiered_nonlinear_mode_a
    """
    fab = register_fabric_sku(price_cents_per_yard=2000)
    _, wo, est, _ = create_awaiting_approval_order(
        service_type="REUPHOLSTERY", rush_requested=True,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=4, labor_hours=10,
                                            piece_label="Sectional")],
    )
    # labor 10*6500=65000 ; rush round(50000*.15)+round(15000*.30)=7500+4500=12000
    # materials 4*2000=8000 ; total 65000+8000+12000=85000
    assert est["labor_total_cents"] == 65000
    assert est["materials_total_cents"] == 8000
    assert est["rush_surcharge_cents"] == 12000
    assert est["total_cents"] == 85000


def test_rush_surcharge_total_mirrored_onto_work_order(api):
    """PRD §3.3: "The estimate's `total_cents` is the base plus `rush_surcharge_cents`, and
    it is mirrored onto the work order's `estimate_total_cents`."

    Design: Difficulty/combinatorial_formula/rush_surcharge_tiered_nonlinear_mode_a
    """
    fab = register_fabric_sku(price_cents_per_yard=2000)
    _, wo, est, _ = create_awaiting_approval_order(
        service_type="REUPHOLSTERY", rush_requested=True,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=4, labor_hours=10,
                                            piece_label="Sectional2")],
    )
    assert est["rush_surcharge_cents"] == 12000
    assert wo["estimate_total_cents"] == 85000


# ---------------------------------------------------------------------------
# Cyclic revision loop and the supersede cascade
# ---------------------------------------------------------------------------
def test_revision_loop_authors_v2_and_supersedes_v1(api):
    """PRD §3.3: "Authoring creates a new `Estimate` carrying the `work_order_id`, a
    server-assigned `version_no` equal to the prior maximum plus one, and a `status` of
    `ACTIVE`; any previously `ACTIVE` estimate on the order is moved to `SUPERSEDED`, so at
    most one estimate per order is ever `ACTIVE` or `APPROVED` at a time."
    PRD §3.3: "Requesting a revision is permitted only while the order is `AWAITING_APPROVAL`
    and only by the owning customer; it moves the order to `REVISION_REQUESTED` while leaving
    the current estimate `ACTIVE` until a new version supersedes it."

    Design: Difficulty/non_linear_state_machine/workorder_cyclic_revision_loop
    """
    fab = register_fabric_sku(price_cents_per_yard=1500)
    cust, wo, est_v1, _ = create_awaiting_approval_order(
        service_type="REUPHOLSTERY",
        line_items=[reupholstery_line_item(fab["id"], yardage_required=2, labor_hours=2,
                                            piece_label="Ottoman")],
    )
    validate_success(api.request_revision(wo["id"], make_customer_headers(cust["id"])), 200)
    est_v2 = author_estimate(wo["id"], supersedes_estimate_id=est_v1["id"])

    assert est_v2["version_no"] == 2
    assert est_v2["status"] == "ACTIVE"
    v1_after = validate_success(api.get_estimate(est_v1["id"], ESTIMATOR), 200)
    assert v1_after["status"] == "SUPERSEDED"
    wo_after = get_work_order(wo["id"])
    assert wo_after["status"] == "AWAITING_APPROVAL"
    assert wo_after["active_estimate_id"] == est_v2["id"]


def test_revision_loop_repeats_and_increments_version_no(api):
    """PRD §3.3: "From `REVISION_REQUESTED`, the estimator authors a fresh version exactly
    as above, returning the order to `AWAITING_APPROVAL` — and this `AWAITING_APPROVAL →
    REVISION_REQUESTED → AWAITING_APPROVAL` loop may repeat any number of times."

    Design: Difficulty/non_linear_state_machine/workorder_cyclic_revision_loop
    """
    fab = register_fabric_sku(price_cents_per_yard=1500)
    cust, wo, est_v1, _ = create_awaiting_approval_order(
        service_type="REUPHOLSTERY",
        line_items=[reupholstery_line_item(fab["id"], yardage_required=2, labor_hours=2,
                                            piece_label="Ottoman-loop")],
    )
    headers = make_customer_headers(cust["id"])
    # loop once
    validate_success(api.request_revision(wo["id"], headers), 200)
    est_v2 = author_estimate(wo["id"], supersedes_estimate_id=est_v1["id"])
    assert get_work_order(wo["id"])["status"] == "AWAITING_APPROVAL"
    # loop again
    validate_success(api.request_revision(wo["id"], headers), 200)
    est_v3 = author_estimate(wo["id"], supersedes_estimate_id=est_v2["id"])
    assert est_v3["version_no"] == 3
    assert est_v3["status"] == "ACTIVE"
    assert get_work_order(wo["id"])["status"] == "AWAITING_APPROVAL"


def test_revision_supersede_reconciles_work_order_totals(api):
    """PRD §3.3: "The order's `active_estimate_id` is repointed to the new estimate, its
    `estimate_total_cents` is set to the new estimate's `total_cents`, its `balance_due_cents`
    is reconciled, the work order's `version` increments by one, and the order moves to
    `AWAITING_APPROVAL`."
    PRD §3.7: "While the order has no final invoice yet (its `final_invoice_cents` is still 0),
    `balance_due_cents` equals `estimate_total_cents` minus `amount_paid_cents`."

    Design: Difficulty/transitive_cascade/estimate_author_cascade_supersede_then_workorder_reconcile_depth2
    """
    cust, wo, est_v1, _ = create_awaiting_approval_order(
        service_type="REPAIR",
        line_items=[
            create_line_item_payload(piece_label="Frame glue", yardage_required=0, labor_hours=2),
            create_line_item_payload(piece_label="Re-screw legs", yardage_required=0, labor_hours=4),
        ],
    )
    assert est_v1["total_cents"] == 39000  # (2+4)h * 6500
    validate_success(api.request_revision(wo["id"], make_customer_headers(cust["id"])), 200)
    est_v2 = author_estimate(wo["id"], supersedes_estimate_id=est_v1["id"])

    v1_after = validate_success(api.get_estimate(est_v1["id"], ESTIMATOR), 200)
    assert v1_after["status"] == "SUPERSEDED"
    assert est_v2["total_cents"] == 39000  # recomputed from the same line items
    wo_after = get_work_order(wo["id"])
    assert wo_after["estimate_total_cents"] == 39000
    assert wo_after["balance_due_cents"] == 39000


def test_revision_supersede_repoints_active_estimate(api):
    """PRD §3.3: "any previously `ACTIVE` estimate on the order is moved to `SUPERSEDED`, so
    at most one estimate per order is ever `ACTIVE` or `APPROVED` at a time. The order's
    `active_estimate_id` is repointed to the new estimate, its `estimate_total_cents` is set
    to the new estimate's `total_cents`, its `balance_due_cents` is reconciled, the work
    order's `version` increments by one, and the order moves to `AWAITING_APPROVAL`."

    Design: Difficulty/transitive_cascade/estimate_author_cascade_supersede_then_workorder_reconcile_depth2
    """
    cust, wo, est_v1, _ = create_awaiting_approval_order(
        service_type="REPAIR",
        line_items=[
            create_line_item_payload(piece_label="Frame glue", yardage_required=0, labor_hours=2),
            create_line_item_payload(piece_label="Re-screw legs", yardage_required=0, labor_hours=4),
        ],
    )
    validate_success(api.request_revision(wo["id"], make_customer_headers(cust["id"])), 200)
    est_v2 = author_estimate(wo["id"], supersedes_estimate_id=est_v1["id"])
    wo_after = get_work_order(wo["id"])
    assert wo_after["active_estimate_id"] == est_v2["id"]
    v1_after = validate_success(api.get_estimate(est_v1["id"], ESTIMATOR), 200)
    assert v1_after["status"] == "SUPERSEDED"


# ---------------------------------------------------------------------------
# OCC on estimate authoring
# ---------------------------------------------------------------------------
def test_estimate_author_stale_version_rejected(api):
    """PRD §2.5: "Authoring an estimate version, approving an order, and cancelling an order
    each require the caller to submit `expected_work_order_version` in the request body,
    carrying the `version` of the work order the client last observed. If that value does
    not equal the work order's current `version` at the moment the server processes the
    request, the operation is rejected with `ERR_STALE_WORK_ORDER_VERSION` and HTTP status
    412, and no state changes."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_work_order_version_on_estimate_author
    """
    cust, wo, items = create_estimating_work_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="P", yardage_required=0, labor_hours=2)],
    )
    stale_v = current_version(wo["id"])
    est1 = author_estimate(wo["id"])  # bumps version
    validate_success(api.request_revision(wo["id"], make_customer_headers(cust["id"])), 200)
    res = api.create_estimate(
        wo["id"],
        {"expected_work_order_version": stale_v, "supersedes_estimate_id": est1["id"]},
        ESTIMATOR,
    )
    validate_error(res, "ERR_STALE_WORK_ORDER_VERSION", expected_status=412)


def test_estimate_author_correct_version_succeeds(api):
    """PRD §3.3: "From `REVISION_REQUESTED`, the estimator authors a fresh version exactly
    as above, returning the order to `AWAITING_APPROVAL`."
    PRD §2.5: "If that value does not equal the work order's current `version` at the moment
    the server processes the request, the operation is rejected with
    `ERR_STALE_WORK_ORDER_VERSION` and HTTP status 412, and no state changes."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_work_order_version_on_estimate_succeeds
    """
    cust, wo, items = create_estimating_work_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="P", yardage_required=0, labor_hours=2)],
    )
    est1 = author_estimate(wo["id"])
    validate_success(api.request_revision(wo["id"], make_customer_headers(cust["id"])), 200)
    v2 = current_version(wo["id"])
    res = api.create_estimate(
        wo["id"],
        {"expected_work_order_version": v2, "supersedes_estimate_id": est1["id"]},
        ESTIMATOR,
    )
    est2 = validate_success(res, 201)
    assert est2["version_no"] == 2
    assert get_work_order(wo["id"])["status"] == "AWAITING_APPROVAL"


# ---------------------------------------------------------------------------
# Line-item driven state advance
# ---------------------------------------------------------------------------
def test_first_line_item_advances_intake_to_estimating(api):
    """PRD §3.2: "Adding the very first line item to an order is what advances it from
    `INTAKE` to `ESTIMATING`, and that advance requires three conditions to hold: the order
    is still in `INTAKE`, at least one condition photo already exists for the order, and the
    line item satisfies the service-type field rules below."

    Design: Corner/state_machines/line_item_initial_state_advances_intake_to_estimating
    """
    _, wo = open_intake_work_order(service_type="REPAIR")
    validate_success(api.create_line_item(
        wo["id"], create_line_item_payload(piece_label="Q", yardage_required=0, labor_hours=2),
        CLERK), 201)
    assert get_work_order(wo["id"])["status"] == "ESTIMATING"


def test_line_item_without_condition_photo_rejected_invalid_state(api):
    """PRD §3.2: "Adding the very first line item to an order is what advances it from
    `INTAKE` to `ESTIMATING`, and that advance requires three conditions to hold: the order
    is still in `INTAKE`, at least one condition photo already exists for the order, and the
    line item satisfies the service-type field rules below."

    Design: Corner/state_machines/line_item_without_condition_photo_rejected_invalid_state
    """
    cust = register_customer()
    wo = validate_success(api.create_work_order(
        factories.create_work_order_payload(cust["id"], service_type="REPAIR"), CLERK), 201)
    res = api.create_line_item(
        wo["id"], create_line_item_payload(piece_label="R", yardage_required=0, labor_hours=2),
        CLERK)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ---------------------------------------------------------------------------
# Turnaround bands
# ---------------------------------------------------------------------------
def test_turnaround_standard_band_no_rush(api):
    """PRD §3.4: "The standard band is 3 base days plus the total labor hours divided by 8
    hours per day and rounded up to the next whole day. If the order is not a rush,
    `promised_turnaround_days` is that standard band."

    Design: Corner/calculations/turnaround_standard_band_no_rush
    """
    cust, wo, est, _ = create_awaiting_approval_order(
        service_type="REFINISH",
        line_items=[create_line_item_payload(piece_label="Table refinish", yardage_required=0, labor_hours=5)],
    )
    v = current_version(wo["id"])
    res = api.approve_work_order(
        wo["id"], factories.approve_payload(v, 10000), make_customer_headers(cust["id"]))
    approved = validate_success(res, 200)
    assert approved["promised_turnaround_days"] == 4  # 3 + ceil(5/8) = 4


def test_turnaround_rush_compressed_to_floor(api):
    """PRD §3.4: "If the order is a rush, the standard band is compressed: take the standard
    band, multiply by one half, round up to the next whole day, and then take the larger of
    that compressed figure and the rush floor of 2 days — so a rush order is never promised
    fewer than 2 days."

    Design: Corner/calculations/turnaround_rush_compressed_floor
    """
    fab = register_fabric_sku(price_cents_per_yard=2000)
    cust, wo, est, _ = create_awaiting_approval_order(
        service_type="REUPHOLSTERY", rush_requested=True,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=4, labor_hours=10,
                                            piece_label="Big sofa")],
    )
    v = current_version(wo["id"])
    res = api.approve_work_order(
        wo["id"], factories.approve_payload(v, 25500), make_customer_headers(cust["id"]))
    approved = validate_success(res, 200)
    # base 3+ceil(10/8)=5 ; rush max(2, ceil(5*0.5))=3
    assert approved["promised_turnaround_days"] == 3


# ---------------------------------------------------------------------------
# Deposit gate + immediate balance reconciliation
# ---------------------------------------------------------------------------
def test_approve_deposit_too_low_returns_deposit_error(api):
    """PRD §3.4: "The deposit gate requires that `deposit_amount_cents` be at least the
    required deposit, which is 30 percent of the order's `estimate_total_cents` rounded *up*
    to the next whole cent. A deposit below that floor is rejected with
    `ERR_DEPOSIT_TOO_LOW`."

    Design: Corner/validations/approve_deposit_too_low_returns_deposit_error
    """
    fab = register_fabric_sku(price_cents_per_yard=1500)
    cust, wo, est, _ = create_awaiting_approval_order(
        service_type="REUPHOLSTERY",
        line_items=[reupholstery_line_item(fab["id"], yardage_required=2, labor_hours=2,
                                            piece_label="Ottoman")],
    )
    assert wo["estimate_total_cents"] == 16000  # 2h*6500 + 2yd*1500 = 13000+3000
    v = current_version(wo["id"])
    res = api.approve_work_order(
        wo["id"], factories.approve_payload(v, 4000), make_customer_headers(cust["id"]))
    validate_error(res, "ERR_DEPOSIT_TOO_LOW", expected_status=422)
    assert get_work_order(wo["id"])["status"] == "AWAITING_APPROVAL"


def test_balance_due_visible_immediately_after_deposit(api):
    """PRD §3.7: "While the order has no final invoice yet (its `final_invoice_cents` is
    still 0), `balance_due_cents` equals `estimate_total_cents` minus `amount_paid_cents`."
    PRD §3.4: "A `DEPOSIT` payment is recorded for the submitted `deposit_amount_cents`, the
    order's `amount_paid_cents` increases by that amount, and `balance_due_cents` is
    reconciled."

    Design: Corner/consistency_model/balance_due_visible_immediately_after_deposit
    """
    fab = register_fabric_sku(price_cents_per_yard=1500)
    cust, wo, est, _ = create_awaiting_approval_order(
        service_type="REUPHOLSTERY",
        line_items=[reupholstery_line_item(fab["id"], yardage_required=2, labor_hours=2,
                                            piece_label="Ottoman")],
    )
    v = current_version(wo["id"])
    res = api.approve_work_order(
        wo["id"], factories.approve_payload(v, 12090), make_customer_headers(cust["id"]))
    approved = validate_success(res, 200)
    assert approved["amount_paid_cents"] == 12090
    assert approved["balance_due_cents"] == 3910  # 16000 - 12090
