"""Compensating-invariant tests: forward effect + compensating reversal restores
a conserved quantity (PRD §3.1, §3.4, §3.6, §3.10)."""
from test_helpers import (
    validate_success,
    setup_issued_invoice_for_visit, setup_green_recovery_pool, TEST_USERS,
)
from test_helpers.fixtures import _list_route_visits

FT = TEST_USERS["field_technician_headers"]
RM = TEST_USERS["route_manager_headers"]
AM = TEST_USERS["account_manager_headers"]


def test_issued_invoice_void_restores_zero_balance(api):
    """PRD §3.10: "an `ISSUED` invoice voids to `VOIDED` and recomputes the pool's
    `balance_due_cents` to remove the reversed amount."
    PRD §3.1: "The `balance_due_cents` is the sum of `amount_cents` over this pool's
    invoices whose status is `ISSUED`; invoices that are `PAID`, `DRAFT`, or
    `VOIDED` contribute nothing".

    Design: Difficulty/compensating_invariant/invoice_issue_then_void_balance_conserved
    """
    ctx = setup_issued_invoice_for_visit(green_pool=True, volume_gallons=20000, per_visit_rate_cents=8000)
    pool_issued = validate_success(api.get_pool(ctx["pool"]["id"], AM))
    assert pool_issued["balance_due_cents"] == 26000
    voided = validate_success(api.void_invoice(ctx["invoice"]["id"], AM))
    pool_voided = validate_success(api.get_pool(ctx["pool"]["id"], AM))
    assert voided["status"] == "VOIDED"
    assert pool_voided["balance_due_cents"] == 0


def test_invoice_balance_conserved_invoice_status_voided(api):
    """PRD §3.10: "An invoice may also be voided: a `DRAFT` invoice voids to
    `VOIDED` with no balance effect, while an `ISSUED` invoice voids to `VOIDED` and
    recomputes the pool's `balance_due_cents` to remove the reversed amount."

    After issue then void, the invoice rests in VOIDED and contributes nothing to
    the balance — the conserved balance returns to its pre-issue value of 0.

    Design: Difficulty/compensating_invariant/invoice_issue_then_void_balance_conserved
    """
    ctx = setup_issued_invoice_for_visit(green_pool=True, volume_gallons=20000, per_visit_rate_cents=8000)
    validate_success(api.void_invoice(ctx["invoice"]["id"], AM))
    invoice = validate_success(api.get_invoice(ctx["invoice"]["id"], AM))
    pool = validate_success(api.get_pool(ctx["pool"]["id"], AM))
    assert invoice["status"] == "VOIDED"
    assert pool["balance_due_cents"] == 0


def test_recovery_cancel_reverts_pool_and_clears_recovery(api):
    """PRD §3.6: "Recovery can also unwind by cancellation rather than completion: if
    the lone outstanding `RECOVERY_SCHEDULED` visit is cancelled and no other
    `RECOVERY_SCHEDULED` visit remains on the pool, the pool is reverted from
    `GREEN_RECOVERY` to `OPEN` as a cascade of that cancellation."

    Design: Difficulty/compensating_invariant/green_recovery_create_then_cancel_recovery_count_conserved
    """
    ctx = setup_green_recovery_pool(volume_gallons=20000, plan_type="RECURRING",
                                    frequency="WEEKLY", per_visit_rate_cents=6000)
    cancelled = validate_success(api.cancel_visit(ctx["recovery_visit"]["id"], RM))
    pool = validate_success(api.get_pool(ctx["pool"]["id"], AM))
    assert cancelled["status"] == "CANCELLED"
    assert pool["service_status"] == "OPEN"


def test_recovery_cancel_leaves_zero_open_recovery_visits(api):
    """PRD §3.4: "a recovery visit may likewise be cancelled from
    `RECOVERY_SCHEDULED` to `CANCELLED`, and when that cancellation leaves no other
    `RECOVERY_SCHEDULED` visit on the pool, it reverts the pool out of recovery".

    After cancelling the sole recovery visit, no RECOVERY_SCHEDULED visit remains on
    the route and the pool posture is restored to OPEN — count and posture conserved.

    Design: Difficulty/compensating_invariant/green_recovery_create_then_cancel_recovery_count_conserved
    """
    ctx = setup_green_recovery_pool(volume_gallons=20000, plan_type="RECURRING",
                                    frequency="WEEKLY", per_visit_rate_cents=6000)
    validate_success(api.cancel_visit(ctx["recovery_visit"]["id"], RM))
    visits, _ = _list_route_visits(ctx["route"]["id"])
    remaining_recovery = [v for v in visits if v["status"] == "RECOVERY_SCHEDULED"]
    pool = validate_success(api.get_pool(ctx["pool"]["id"], AM))
    assert remaining_recovery == [], "no RECOVERY_SCHEDULED visit should remain"
    assert pool["service_status"] == "OPEN"
