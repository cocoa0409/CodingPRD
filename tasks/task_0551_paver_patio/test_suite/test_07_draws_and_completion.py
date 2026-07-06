"""The draw ledger's money conservation, OCC on draws, and completion accounting."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_client_headers,
    assert_balance_consistent, retention_amount_cents, warranty_claim_payload,
    draw_payload,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["project_manager_headers"]


def test_refund_restores_amount_paid_to_deposit_only(api):
    """PRD §3.7: "Refunding advances a `PAID` draw to `REFUNDED`, subtracts its `amount_cents` back
    out of `amount_paid_cents`, recomputes the balance the same way, and again increments the
    version. At all times, `amount_paid_cents` equals the sum of `amount_cents` over the project's
    draws that are `PAID`."

    Design: Difficulty/compensating_invariant/money_conservation_draw_then_refund
    """
    ctx = fx.setup_progress_paid_then_ready_to_refund(api)
    draw = validate_success(api.refund_draw(ctx["progress_draw_id"], PM))
    assert draw["status"] == "REFUNDED", f"expected REFUNDED, got {draw['status']}"
    project = validate_success(api.get_project(ctx["project_id"], PM))
    # Only the 15000 deposit remains PAID after the 20000 progress draw is refunded.
    assert project["amount_paid_cents"] == 15000, \
        f"expected amount_paid back at the 15000 deposit, got {project['amount_paid_cents']}"


def test_balance_due_recomputed_after_refund(api):
    """PRD §3.7: "Recording a payment advances a draw from `PENDING` to `PAID`, adds its
    `amount_cents` to the project's `amount_paid_cents`, recomputes `balance_due_cents` as
    `contract_value_cents` minus `amount_paid_cents`, and increments the project version."

    Design: Difficulty/compensating_invariant/money_conservation_draw_then_refund
    """
    ctx = fx.setup_progress_paid_then_ready_to_refund(api)
    validate_success(api.refund_draw(ctx["progress_draw_id"], PM))
    project = validate_success(api.get_project(ctx["project_id"], PM))
    assert project["amount_paid_cents"] == 15000, \
        f"expected amount_paid back at the 15000 deposit, got {project['amount_paid_cents']}"
    assert_balance_consistent(project)


def test_stale_draw_version_conflict(api):
    """PRD §2.7: "If the project's current `version` has advanced past that value — because another
    change order, draw, payment, or refund has since touched the ledger — the create is rejected with
    `ERR_STALE_VERSION` (412), and no resource is created."

    Design: Corner/cross_cutting/stale_draw_version_returns_conflict
    """
    ctx = fx.setup_stale_draw(api)
    resp = api.create_draw(
        draw_payload(ctx["project_id"], "DEPOSIT", 5000, ctx["stale_version"]), PM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_final_phase_completion_bubbles_project_to_completed(api):
    """PRD §3.9: "When the final work phase completes, the project bubbles from `IN_PRODUCTION` to
    `COMPLETED`, and the completion accounting runs."
    PRD §3.9: "Third, `warranty_start_date` is set to the current logical-clock instant and
    `warranty_end_date` to 365 days after it."

    Design: Difficulty/transitive_cascade/final_phase_completion_bubbles_project_and_creates_retention
    """
    ctx = fx.setup_final_phase_in_progress(api)
    validate_success(api.complete_work_phase(
        ctx["phase_id"], {"installed_quantities": {ctx["line_id"]: 100}}, PM))
    project = validate_success(api.get_project(ctx["project_id"], PM))
    assert project["status"] == "COMPLETED", f"expected COMPLETED, got {project['status']}"
    assert project["warranty_start_date"] is not None, "completion must stamp warranty_start_date"
    assert project["warranty_end_date"] is not None, "completion must stamp warranty_end_date"


def test_completion_creates_pending_retention_release_draw(api):
    """PRD §3.9: "Second, the system creates a `RETENTION_RELEASE` progress draw in `PENDING` status
    whose `amount_cents` is five percent of `contract_value_cents`, rounded half up to whole cents."

    Design: Difficulty/transitive_cascade/final_phase_completion_bubbles_project_and_creates_retention
    """
    ctx = fx.setup_final_phase_in_progress(api)
    validate_success(api.complete_work_phase(
        ctx["phase_id"], {"installed_quantities": {ctx["line_id"]: 100}}, PM))
    project = validate_success(api.get_project(ctx["project_id"], PM))
    draws, _meta = validate_paginated(api.list_project_draws(ctx["project_id"], PM))
    retention = [d for d in draws if d["draw_type"] == "RETENTION_RELEASE"]
    assert len(retention) == 1, f"completion must create exactly one RETENTION_RELEASE draw; got {len(retention)}"
    draw = retention[0]
    assert draw["status"] == "PENDING", f"retention draw must be PENDING, got {draw['status']}"
    expected = retention_amount_cents(project["contract_value_cents"])
    assert draw["amount_cents"] == expected, (
        f"retention amount must be 5% of contract {project['contract_value_cents']} "
        f"(= {expected}), got {draw['amount_cents']}"
    )


def test_file_warranty_on_non_completed_project(api):
    """PRD §3.9: "The project must be `COMPLETED`, or the claim is rejected with `ERR_NOT_COMPLETED`
    (409); and the clock must not have passed the project's `warranty_end_date`, or filing is
    rejected with `ERR_WARRANTY_WINDOW_CLOSED` (409)."

    Design: Corner/validations/file_warranty_on_non_completed_returns_error
    """
    ctx = fx.setup_contracted_owned(api, email="own@example.com")
    resp = api.create_warranty_claim(
        warranty_claim_payload(ctx["project_id"], claim_category="WORKMANSHIP", description="early claim"),
        make_client_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_COMPLETED)
