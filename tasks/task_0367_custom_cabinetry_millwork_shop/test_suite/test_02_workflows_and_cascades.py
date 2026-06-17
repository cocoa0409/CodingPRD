"""State-machine loops, transitive cascades, and compensating invariants.

Covers the non_linear_state_machine, transitive_cascade, and
compensating_invariant difficulty instances.
"""
from test_helpers import (
    get_success_data,
    validate_success,
    TEST_USERS,
    make_customer_headers,
    setup_in_production_project,
    setup_submitted_change_order,
    setup_committed_reservation,
    setup_base_shop,
    create_project,
    add_spec,
)

MANAGER = TEST_USERS["shop_manager_headers"]
DESIGNER = TEST_USERS["designer_headers"]


# ===========================================================================
# Difficulty / non_linear_state_machine
# ===========================================================================
def test_project_change_order_cyclic_loop(api):
    """PRD §3.7: "Submission computes `delta_cents` using the change-order delta
    calculation against the project's current margin policy and active finish,
    drives the project from `IN_PRODUCTION` to `CHANGE_PENDING`, and increments
    the project's `version` by one."
    PRD §3.7: "Approval freezes `delta_cents` and drives the project from
    `CHANGE_PENDING` back to `IN_PRODUCTION` with a ledger fold"

    Design: Difficulty/non_linear_state_machine/project_change_order_cyclic_loop
    """
    ctx = setup_submitted_change_order(spec_price_delta_cents=50000)
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    co_id = ctx["change_order"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])

    # After submit the project is at CHANGE_PENDING.
    pending = get_success_data(api.get_project(shop_id, proj_id, MANAGER))
    assert pending["status"] == "CHANGE_PENDING", f"after submit expected CHANGE_PENDING, got {pending['status']}"

    # Approve returns the project to IN_PRODUCTION (closing the cycle).
    validate_success(api.approve_change_order(shop_id, proj_id, co_id, {"expected_project_version": pending["version"]}, cust))
    after = get_success_data(api.get_project(shop_id, proj_id, MANAGER))
    assert after["status"] == "IN_PRODUCTION", f"after approve expected IN_PRODUCTION again, got {after['status']}"


def test_change_order_submitted_revising_cycle(api):
    """PRD §3.7: "A manager then resubmits a revising change order, which
    increments `revision_round` by one and recomputes `delta_cents`, returning it
    to `SUBMITTED`; a change order may bounce between `SUBMITTED` and `REVISING`
    over multiple rounds."

    Design: Difficulty/non_linear_state_machine/change_order_submitted_revising_cycle
    """
    ctx = setup_submitted_change_order(spec_price_delta_cents=30000)
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    co_id = ctx["change_order"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])

    # Submitted change order begins at revision_round 1.
    co = get_success_data(api.get_change_order(shop_id, proj_id, co_id, MANAGER))
    assert co["revision_round"] == 1, f"submitted change order expected revision_round 1, got {co['revision_round']}"

    # Customer requests revision -> REVISING; manager resubmits -> SUBMITTED round 2.
    get_success_data(api.request_revision_change_order(shop_id, proj_id, co_id, cust))
    resubmitted = validate_success(api.resubmit_change_order(shop_id, proj_id, co_id, MANAGER))
    assert resubmitted["status"] == "SUBMITTED", f"after resubmit expected SUBMITTED, got {resubmitted['status']}"
    assert resubmitted["revision_round"] == 2, f"after resubmit expected revision_round 2, got {resubmitted['revision_round']}"


# ===========================================================================
# Difficulty / transitive_cascade
# ===========================================================================
def test_change_order_approve_folds_ledger_creates_progress_draw(api):
    """PRD §3.7: "It takes the signed `spec_price_delta_cents`, multiplies it by
    the project's margin-policy `BULK` multiplier (12500 basis points under
    `STANDARD`, 15000 under `PREMIUM`), divides by 10000, and rounds half up to a
    margined figure that preserves the sign."
    PRD §3.7: "Approval freezes `delta_cents` and drives the project from
    `CHANGE_PENDING` back to `IN_PRODUCTION` with a ledger fold: the project's
    `contract_total_cents` is increased by `delta_cents`, `deposit_required_cents`
    is recomputed, a `PROGRESS` adjustment draw in `PENDING` status is created for
    the larger of zero and `delta_cents`, and the project's `version` is
    incremented by one."

    Design: Difficulty/transitive_cascade/change_order_approve_folds_ledger_creates_progress_draw_depth3
    """
    # tax800, STANDARD, qty4, PAINT -> contract_total 628992; spec_delta 50000 -> delta 75600.
    ctx = setup_submitted_change_order(
        spec_price_delta_cents=50000,
        shop_overrides={"tax_rate_bps": 800, "deposit_pct_bps": 3000},
        specs=[{"quantity": 4}],
        finish_code="PAINT",
    )
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    co_id = ctx["change_order"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])

    # Hop A: submit froze delta_cents on the change order.
    co_submitted = get_success_data(api.get_change_order(shop_id, proj_id, co_id, MANAGER))
    assert co_submitted["delta_cents"] == 75600, f"change-order delta expected 75600, got {co_submitted['delta_cents']}"

    pending = get_success_data(api.get_project(shop_id, proj_id, MANAGER))
    approved = validate_success(api.approve_change_order(shop_id, proj_id, co_id, {"expected_project_version": pending["version"]}, cust))
    assert approved["delta_cents"] == 75600, "frozen delta_cents must survive approval"

    # Hop B: contract_total folds in the delta (628992 + 75600 == 704592).
    project = get_success_data(api.get_project(shop_id, proj_id, MANAGER))
    assert project["contract_total_cents"] == 704592, (
        f"contract_total after fold expected 704592, got {project['contract_total_cents']}"
    )

    # Hop C: a PROGRESS draw in PENDING for max(0, delta) == 75600 now exists.
    draws = api.list_draws(shop_id, proj_id, MANAGER).json()["data"]
    progress = [d for d in draws if d["draw_type"] == "PROGRESS" and d["status"] == "PENDING" and d["amount_cents"] == 75600]
    assert len(progress) == 1, (
        f"expected exactly one PENDING PROGRESS draw of 75600 from the fold, got {[(d['draw_type'], d['status'], d['amount_cents']) for d in draws]}"
    )


def test_build_complete_consumes_reservation_decrements_stock(api):
    """PRD §3.6: "Completing an in-progress job moves it to `COMPLETE` and
    triggers a consumption cascade: every `COMMITTED` reservation on the project
    transitions to `CONSUMED`, and for each, the material's `on_hand_sheets` is
    decremented by the reservation's `sheets` and its `reserved_sheets` drops
    correspondingly"

    Design: Difficulty/transitive_cascade/build_complete_consumes_reservation_decrements_stock_depth3
    """
    # Material on_hand=8; one COMMITTED reservation of 5; started build job.
    ctx = setup_committed_reservation(reservation_sheets=5, restock=8)
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]

    # Hop A: complete the started build job.
    completed = validate_success(api.complete_build_job(shop_id, proj_id, ctx["build_job"]["id"], MANAGER))
    assert completed["status"] == "COMPLETE"

    # Hop B: the COMMITTED reservation flips to CONSUMED.
    res = get_success_data(api.get_reservation(shop_id, proj_id, ctx["reservation"]["id"], MANAGER))
    assert res["status"] == "CONSUMED", f"reservation expected CONSUMED after build complete, got {res['status']}"

    # Hop C: on_hand drops by the reservation's sheets (8-5==3); reserved drops to 0.
    mat = get_success_data(api.get_material(shop_id, ctx["material"]["id"], MANAGER))
    assert mat["on_hand_sheets"] == 3, f"on_hand expected 3 (8-5), got {mat['on_hand_sheets']}"
    assert mat["reserved_sheets"] == 0, f"reserved expected 0 after consume, got {mat['reserved_sheets']}"


# ===========================================================================
# Difficulty / compensating_invariant
# ===========================================================================
def test_draw_issue_void_conserves_billed_to_date(api):
    """PRD §3.8: "on success the draw moves to `ISSUED` and its `amount_cents` is
    added to the project's `billed_to_date_cents`."
    PRD §3.8: "voiding an issued draw additionally subtracts its `amount_cents`
    back out of the project's `billed_to_date_cents`, leaving that ledger at its
    pre-issue value so that billing stays conserved under the issue-then-void
    pair."

    Design: Difficulty/compensating_invariant/draw_issue_void_conserves_billed_to_date
    """
    # tax0 STAIN qty2 -> deposit draw 87480. billed 0 -> issue 87480 -> void back to 0.
    from test_helpers import setup_contracted_project
    ctx = setup_contracted_project(specs=[{"quantity": 2}], finish_code="STAIN")
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    dep_id = ctx["deposit_draw"]["id"]

    before = get_success_data(api.get_project(shop_id, proj_id, MANAGER))
    assert before["billed_to_date_cents"] == 0, "billed_to_date starts at 0"

    get_success_data(api.issue_draw(shop_id, proj_id, dep_id, MANAGER))
    issued_proj = get_success_data(api.get_project(shop_id, proj_id, MANAGER))
    assert issued_proj["billed_to_date_cents"] == 87480, (
        f"billed_to_date after issue expected 87480, got {issued_proj['billed_to_date_cents']}"
    )

    voided = validate_success(api.void_draw(shop_id, proj_id, dep_id, MANAGER))
    assert voided["status"] == "VOIDED"
    assert voided["amount_cents"] == 87480, "the voided draw's amount_cents is immutable"

    after = get_success_data(api.get_project(shop_id, proj_id, MANAGER))
    assert after["billed_to_date_cents"] == 0, (
        f"billed_to_date must return to its pre-issue value 0 after void, got {after['billed_to_date_cents']}"
    )


def test_reservation_hold_release_conserves_on_hand_sheets(api):
    """PRD §3.6: "Reservation is forward-looking and provisional: the requested
    `sheets` are added to the material's `reserved_sheets` up front, which lowers
    `available_sheets`, even though the eventual build may consume fewer sheets."
    PRD §3.6: "A held reservation can be released, returning its `sheets` to the
    available quota, which restores the material's availability to its pre-hold
    value."

    Design: Difficulty/compensating_invariant/reservation_hold_release_conserves_material_on_hand_sheets
    """
    # Material on_hand=10; hold 4 (available 10->6); release (reserved 0, available 10); on_hand 10 throughout.
    from test_helpers import setup_contracted_project
    ctx = setup_contracted_project(specs=[{"quantity": 2}], finish_code="STAIN", restock=10)
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    mat_id = ctx["material"]["id"]
    dep_id = ctx["deposit_draw"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])
    # Pay the deposit so the project can advance (not strictly required for a HELD
    # reservation, but mirrors the design instance which is IN_PRODUCTION-bound).
    get_success_data(api.issue_draw(shop_id, proj_id, dep_id, MANAGER))
    get_success_data(api.pay_draw(shop_id, proj_id, dep_id, cust))

    r = get_success_data(api.create_reservation(shop_id, proj_id, {"material_id": mat_id, "sheets": 4}, MANAGER))
    held_mat = get_success_data(api.get_material(shop_id, mat_id, MANAGER))
    assert held_mat["on_hand_sheets"] == 10, "on_hand unchanged by a hold"
    assert held_mat["reserved_sheets"] == 4
    assert held_mat["available_sheets"] == 6, f"available expected 6 (10-4) while held, got {held_mat['available_sheets']}"

    released = validate_success(api.release_reservation(shop_id, proj_id, r["id"], MANAGER))
    assert released["status"] == "RELEASED"

    after = get_success_data(api.get_material(shop_id, mat_id, MANAGER))
    assert after["on_hand_sheets"] == 10, f"on_hand unchanged throughout, got {after['on_hand_sheets']}"
    assert after["reserved_sheets"] == 0, f"reserved restored to 0 after release, got {after['reserved_sheets']}"
    assert after["available_sheets"] == 10, f"available restored to pre-hold 10, got {after['available_sheets']}"
