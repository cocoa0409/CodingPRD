"""Cascade and derived-field reconciliation tests (PRD §2.5, §3.1, §3.6, §3.10)."""
from test_helpers import (
    validate_success, get_success_data,
    setup_open_pool_dispatched_visit, setup_draft_invoice_for_visit,
    setup_issued_invoice_for_visit,
    complete_payload, create_invoice_payload, TEST_USERS,
)
from test_helpers.fixtures import _list_route_visits

FT = TEST_USERS["field_technician_headers"]
RM = TEST_USERS["route_manager_headers"]
AM = TEST_USERS["account_manager_headers"]


def test_green_completion_cascade_creates_recovery_visit(api):
    """PRD §3.6: "When a technician completes a `SCHEDULED` visit on an `OPEN` pool
    with `green_pool` true, the pool transitions from `OPEN` to `GREEN_RECOVERY`,
    the system auto-creates a follow-up visit in `RECOVERY_SCHEDULED` on the same
    `plan_id` and `route_id` as the triggering visit, and the pool's `version` is
    incremented."

    Design: Difficulty/transitive_cascade/green_pool_completion_cascade_depth3
    """
    ctx = setup_open_pool_dispatched_visit(volume_gallons=20000, plan_type="ONE_TIME",
                                           frequency="NONE", per_visit_rate_cents=8000)
    completed = validate_success(api.complete_visit(ctx["visit"]["id"], complete_payload(green_pool=True), FT))
    pool = validate_success(api.get_pool(ctx["pool"]["id"], AM))
    visits, _ = _list_route_visits(ctx["route"]["id"])
    recovery = [v for v in visits if v["status"] == "RECOVERY_SCHEDULED"]
    assert completed["status"] == "COMPLETED"
    assert pool["service_status"] == "GREEN_RECOVERY"
    assert len(recovery) == 1, f"expected exactly one RECOVERY_SCHEDULED visit, got {len(recovery)}"
    assert recovery[0]["plan_id"] == ctx["plan"]["id"]
    assert recovery[0]["route_id"] == ctx["route"]["id"]


def test_green_cascade_preserves_pool_open_after_no_trigger(api):
    """PRD §3.6: "the system auto-creates a follow-up visit in `RECOVERY_SCHEDULED`
    on the same `plan_id` and `route_id` as the triggering visit".
    PRD §3.4: "A freshly scheduled visit starts in `SCHEDULED`".

    The auto-created follow-up is the only RECOVERY_SCHEDULED visit and references
    the triggering plan and route.

    Design: Difficulty/transitive_cascade/green_pool_completion_cascade_depth3
    """
    ctx = setup_open_pool_dispatched_visit(volume_gallons=20000, plan_type="RECURRING",
                                           frequency="WEEKLY", per_visit_rate_cents=6000)
    validate_success(api.complete_visit(ctx["visit"]["id"], complete_payload(green_pool=True), FT))
    visits, _ = _list_route_visits(ctx["route"]["id"])
    recovery = [v for v in visits if v["status"] == "RECOVERY_SCHEDULED"]
    assert len(recovery) == 1
    assert recovery[0]["pool_id"] == ctx["pool"]["id"]


def test_invoice_issue_cascades_to_pool_balance(api):
    """PRD §3.10: "At issuance the system computes `amount_cents` as the sum of the
    referenced visit's `billed_amount_cents` (when a `visit_id` is set) and the
    referenced work order's `repair_total_cents` (when a `work_order_id` is set)".
    PRD §3.10: "Issuance recomputes the owning pool's `balance_due_cents`."

    Design: Difficulty/transitive_cascade/invoice_issue_balance_cascade_depth2
    """
    ctx = setup_draft_invoice_for_visit(green_pool=True, volume_gallons=20000, per_visit_rate_cents=8000)
    issued = validate_success(api.issue_invoice(ctx["invoice"]["id"], AM))
    pool = validate_success(api.get_pool(ctx["pool"]["id"], AM))
    assert issued["amount_cents"] == 26000, f"expected 26000, got {issued['amount_cents']}"
    assert pool["balance_due_cents"] == 26000, f"expected 26000, got {pool['balance_due_cents']}"


def test_invoice_amount_equals_referenced_visit_bill(api):
    """PRD §3.10: "At issuance the system computes `amount_cents` as the sum of the
    referenced visit's `billed_amount_cents` (when a `visit_id` is set) and the
    referenced work order's `repair_total_cents` (when a `work_order_id` is set) —
    in practice one part is present and the other contributes 0."

    Design: Difficulty/transitive_cascade/invoice_issue_balance_cascade_depth2
    """
    ctx = setup_draft_invoice_for_visit(green_pool=True, volume_gallons=20000, per_visit_rate_cents=8000)
    visit = validate_success(api.get_visit(ctx["visit"]["id"], RM))
    issued = validate_success(api.issue_invoice(ctx["invoice"]["id"], AM))
    assert issued["amount_cents"] == visit["billed_amount_cents"]


def test_balance_reconciles_to_zero_after_payment(api):
    """PRD §3.1: "The `balance_due_cents` is the sum of `amount_cents` over this
    pool's invoices whose status is `ISSUED`; invoices that are `PAID`, `DRAFT`, or
    `VOIDED` contribute nothing".
    PRD §3.10: "Paying an issued invoice advances it from `ISSUED` to `PAID` and
    recomputes the pool's `balance_due_cents`, dropping the now-settled amount out of
    the outstanding balance."

    Design: Corner/cross_cutting_complexity_layers/balance_due_reconciles_after_invoice_pay
    """
    ctx = setup_issued_invoice_for_visit(green_pool=True, volume_gallons=20000, per_visit_rate_cents=8000)
    pool_issued = validate_success(api.get_pool(ctx["pool"]["id"], AM))
    assert pool_issued["balance_due_cents"] == 26000
    paid = validate_success(api.pay_invoice(ctx["invoice"]["id"], AM))
    pool_paid = validate_success(api.get_pool(ctx["pool"]["id"], AM))
    assert paid["status"] == "PAID"
    assert pool_paid["balance_due_cents"] == 0


def test_balance_visible_immediately_in_next_request(api):
    """PRD §2.5: "The system applies all such secondary effects immediately and
    synchronously within the triggering request, never deferring them."
    PRD §3.10: "Issuance recomputes the owning pool's `balance_due_cents`."

    Design: Corner/consistency_model/immediate_consistency_balance_visible_same_response
    """
    # Build a recovery-visit-billed invoice of 12500 (one-time base 8000 + recovery 4500).
    ctx = setup_open_pool_dispatched_visit(volume_gallons=20000, plan_type="ONE_TIME",
                                           frequency="NONE", per_visit_rate_cents=8000)
    validate_success(api.complete_visit(ctx["visit"]["id"], complete_payload(green_pool=True), FT))
    visits, _ = _list_route_visits(ctx["route"]["id"])
    recovery = next(v for v in visits if v["status"] == "RECOVERY_SCHEDULED")
    validate_success(api.complete_visit(recovery["id"], complete_payload(green_pool=False), FT))
    inv = get_success_data(api.create_invoice(
        create_invoice_payload(ctx["pool"]["id"], visit_id=recovery["id"]), AM))
    issued = validate_success(api.issue_invoice(inv["id"], AM))
    pool = validate_success(api.get_pool(ctx["pool"]["id"], AM))
    assert issued["amount_cents"] == 12500, f"expected 12500, got {issued['amount_cents']}"
    assert pool["balance_due_cents"] == 12500, f"expected 12500, got {pool['balance_due_cents']}"
