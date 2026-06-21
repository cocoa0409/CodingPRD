"""The draw cycle, release gates, sequence enforcement, project completion +
warranty issuance, the money-conservation invariant, and cancel cascades.

Translates Difficulty/transitive_cascade (final draw pay arm),
Difficulty/compensating_invariant (money conservation), and
Corner/validations + Corner/state_machines draw/cancel instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_accepted_estimate, setup_scheduled_project, setup_completed_project,
    FENCE_100_PLAIN, FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20,
    find_draw_by_milestone,
)

PM = TEST_USERS["project_manager_headers"]


def _draw(api, pid, milestone):
    draws = get_success_data(api.list_draws(pid, PM))
    return find_draw_by_milestone(draws, milestone)


# ===========================================================================
# Corner/validations: draw gate not met (DELIVERY before delivered)
# ===========================================================================
def test_invoice_delivery_draw_before_delivered_rejected(api):
    """PRD §3.8: "A `ProjectManager` invoices a `SCHEDULED` draw, but only once that milestone's release gate is met, or the request is rejected with `ERR_DRAW_GATE_NOT_MET`."
    PRD §3.8: "`DELIVERY` requires a `DELIVERED` material order on the project".

    Design: Corner/validations/error_draw_gate_not_met_delivery_before_delivered
    """
    ctx = setup_accepted_estimate(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pid = ctx["project"]["id"]
    delivery = _draw(api, pid, "DELIVERY")
    resp = api.invoice_draw(pid, delivery["id"], PM)
    validate_error(resp, ApiErrorId.ERR_DRAW_GATE_NOT_MET.value)


# ===========================================================================
# NOTE: test_pay_final_draw_before_prior_paid_rejected was DELETED.
# STEP 1b ERROR-PRECEDENCE / UNREACHABLE-BRANCH collapse: PRD §3.8 line 178
# makes FINAL's *invoice* gate require "every prior non-voided draw to be
# PAID". Since paying a draw requires it to be INVOICED (§3.8 line 180), and
# FINAL can only become INVOICED after all prior non-voided draws are already
# PAID, the pay-time ERR_DRAW_SEQUENCE_VIOLATION branch is unreachable under
# any PRD-faithful implementation. The test's own setup cannot construct the
# precondition (invoicing FINAL with DELIVERY unpaid) without correctly
# tripping ERR_DRAW_GATE_NOT_MET at the invoice step.
# ===========================================================================


# ===========================================================================
# transitive_cascade instance 2: final draw pay -> COMPLETED -> warranty
# ===========================================================================
def test_final_draw_pay_completes_project_and_issues_warranty(api):
    """PRD §3.8: "Paying the `FINAL` draw bubbles the project from `IN_PROGRESS` to `COMPLETED`, but only if every non-final, non-voided draw is already `PAID`."
    PRD §3.8: "On a successful final payment the balance due must reach 0.00, and a `Warranty` in `ISSUED` status is created for the project."

    Design: Difficulty/transitive_cascade/final_draw_pay_cascades_project_completed_warranty_depth2
    """
    ctx = setup_scheduled_project(line_specs=[FENCE_100_PLAIN], dock_id="DOCK_FIN",
                                  crew_id="CREW_FIN", deliver=True)
    pid = ctx["project"]["id"]
    deposit = _draw(api, pid, "DEPOSIT")
    get_success_data(api.invoice_draw(pid, deposit["id"], PM))
    get_success_data(api.pay_draw(pid, deposit["id"], PM))
    get_success_data(api.pay_draw(pid, _draw(api, pid, "DELIVERY")["id"], PM))
    framing = _draw(api, pid, "FRAMING")
    get_success_data(api.invoice_draw(pid, framing["id"], PM))
    get_success_data(api.pay_draw(pid, framing["id"], PM))
    final = _draw(api, pid, "FINAL")
    get_success_data(api.invoice_draw(pid, final["id"], PM))
    resp = api.pay_draw(pid, final["id"], PM)
    final_paid = validate_success(resp, expected_status=200)
    assert final_paid["status"] == "PAID"
    proj = get_success_data(api.get_project(pid, PM))
    assert proj["status"] == "COMPLETED"
    assert proj["balance_due"] == 0.00


def test_completed_project_has_exactly_one_issued_warranty(api):
    """PRD §3.9: "When a project completes, the system issues a `Warranty` owned by the project, starting in `ISSUED`."
    PRD §3.8: "a `Warranty` in `ISSUED` status is created for the project."

    Design: Difficulty/transitive_cascade/final_draw_pay_cascades_project_completed_warranty_depth2
    """
    ctx = setup_completed_project(line_specs=[FENCE_100_PLAIN])
    pid = ctx["project"]["id"]
    warranties = get_success_data(api.list_warranties(pid, PM))
    issued = [w for w in warranties if w["status"] == "ISSUED"]
    assert len(issued) == 1, f"expected exactly one ISSUED warranty, got {len(warranties)}"


# ===========================================================================
# compensating_invariant instance 1: paid + due == contract
# ===========================================================================
def test_deposit_pay_conserves_contract_dollars(api):
    """PRD §3.8: "Payment moves the draw to `PAID` and recomputes the project's `draws_paid_total` (the sum of `amount` over all `PAID` draws) and its `balance_due` (the `contract_total` minus `draws_paid_total`)."
    After paying the DEPOSIT draw (4321.01) on a 21605.04 contract,
    draws_paid_total 4321.01 + balance_due 17284.03 == 21605.04.

    Design: Difficulty/compensating_invariant/draw_money_conservation_paid_plus_due_equals_contract
    """
    ctx = setup_scheduled_project(
        line_specs=[FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20],
        dock_id="DOCK_INVCON", crew_id="CREW_INVCON", deliver=True)
    pid = ctx["project"]["id"]
    deposit = _draw(api, pid, "DEPOSIT")
    get_success_data(api.invoice_draw(pid, deposit["id"], PM))
    resp = api.pay_draw(pid, deposit["id"], PM)
    validate_success(resp, expected_status=200)
    proj = get_success_data(api.get_project(pid, PM))
    assert proj["draws_paid_total"] == 4321.01
    assert proj["balance_due"] == 17284.03
    assert round(proj["draws_paid_total"] + proj["balance_due"], 2) == 21605.04


def test_deposit_pay_advances_project_to_in_progress(api):
    """PRD §3.8: "Paying the `DEPOSIT` draw — which must itself be `INVOICED` — bubbles the project from `SCHEDULED` to `IN_PROGRESS`."

    Design: Difficulty/compensating_invariant/draw_money_conservation_paid_plus_due_equals_contract
    """
    ctx = setup_scheduled_project(
        line_specs=[FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20],
        dock_id="DOCK_INPROG", crew_id="CREW_INPROG", deliver=True)
    pid = ctx["project"]["id"]
    deposit = _draw(api, pid, "DEPOSIT")
    get_success_data(api.invoice_draw(pid, deposit["id"], PM))
    get_success_data(api.pay_draw(pid, deposit["id"], PM))
    proj = get_success_data(api.get_project(pid, PM))
    assert proj["status"] == "IN_PROGRESS"


# ===========================================================================
# Corner/state_machines: cancel an ESTIMATED project voids draws
# ===========================================================================
def test_cancel_estimated_project_voids_all_draws(api):
    """PRD §2.5: "cancelling a project cascades downward: every non-terminal crew booking is driven to `CANCELLED`, every draw still in `SCHEDULED` or `INVOICED` is driven to `VOIDED`, and — when cancellation occurs from the `APPROVED` stage — any material order still in `PLACED` or `CONFIRMED` is driven to `CANCELLED`."
    PRD §3.1: "A `ProjectManager` may cancel a project while it is in `DRAFT`, `ESTIMATED`, or `APPROVED`."

    Design: Corner/state_machines/cancel_project_cascades_void_draws_cancel_bookings
    """
    ctx = setup_accepted_estimate(line_specs=[FENCE_100_PLAIN], job_type="FENCE")
    pid = ctx["project"]["id"]
    resp = api.cancel_project(pid, PM)
    proj = validate_success(resp, expected_status=200)
    assert proj["status"] == "CANCELLED"
    draws = get_success_data(api.list_draws(pid, PM))
    assert len(draws) == 4
    assert all(d["status"] == "VOIDED" for d in draws), \
        f"all draws should be VOIDED, got {[d['status'] for d in draws]}"


# ===========================================================================
# Corner/state_machines: cancel terminal COMPLETED project rejected
# ===========================================================================
def test_cancel_completed_project_returns_invalid_state(api):
    """PRD §2.5: "The terminal project states are `COMPLETED` and `CANCELLED`."
    PRD §2.9: "the system evaluate state-machine legality, yielding `ERR_INVALID_STATE` (HTTP 409) when the target resource is not in a state from which the requested transition is defined". A COMPLETED project has no defined
    cancel transition.

    Design: Corner/state_machines/cancel_terminal_completed_project_returns_invalid_state
    """
    ctx = setup_completed_project(line_specs=[FENCE_100_PLAIN])
    pid = ctx["project"]["id"]
    resp = api.cancel_project(pid, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    proj = get_success_data(api.get_project(pid, PM))
    assert proj["status"] == "COMPLETED"
