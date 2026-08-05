"""Activation cascade, rental proration and renewal overlap, shot-clock deadline
boundary, and the appeal lifecycle.

Difficulty: dual_variant_calc, transitive_cascade,
priority_pair_validation_conflict, resource_temporal_overlap,
boundary_precision_check.
Corner: validations, state_machines.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    renew_payload, appeal_payload, appeal_decision_payload, design_review_payload,
    register_applicant, create_structure, create_segment, set_clock,
    open_application, add_node, submit, record_completeness, record_design_review,
    decide, pay_full, fetch_node, fetch_structure, structure_version,
    setup_under_review_single, setup_submitted_single,
    setup_granted_single_collocation, setup_activated_single_collocation,
    setup_denied_single_collocation,
    make_applicant_headers, make_inspector_headers, make_approver_headers, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


# ─── Difficulty: rental_estimate_vs_actual_proration ──────────────────────
def test_rental_estimate_prorates_from_decided_at(api):
    """PRD §3.7: "The estimate variant uses the application's `decided_at` as the
    reference (or, for a rental created when an appeal is overturned, the current clock)."

    Design: Difficulty/dual_variant_calc/rental_estimate_vs_actual_proration
    """
    ctx = setup_activated_single_collocation(
        decision_clock="2026-07-15T00:00:00Z", activation_clock="2026-08-20T00:00:00Z"
    )
    assert ctx["rental"]["estimated_amount_cents"] == 12575


def test_rental_actual_prorates_from_activation_clock(api):
    """PRD §3.7: "The actual variant, computed at activation, uses the activation
    clock as the reference; because activation happens on or after the decision,
    fewer days remain and the actual amount is never greater than the estimate."

    Design: Difficulty/dual_variant_calc/rental_estimate_vs_actual_proration
    """
    ctx = setup_activated_single_collocation(
        decision_clock="2026-07-15T00:00:00Z", activation_clock="2026-08-20T00:00:00Z"
    )
    assert ctx["rental"]["actual_amount_cents"] == 9912
    assert ctx["rental"]["status"] == "ACTIVE"
    assert ctx["rental"]["actual_amount_cents"] <= ctx["rental"]["estimated_amount_cents"]


# ─── Difficulty: activate_cascades_rental_finalization ────────────────────
def test_activate_moves_node_to_activated_and_shifts_slot(api):
    """PRD §3.8: "On activation the node advances from `PERMITTED` to `ACTIVATED`
    and its version advances." "The structure accounting also shifts:
    `reserved_collocations` is decremented by one and `active_collocations` is
    incremented by one, converting the held reservation into an active occupancy."

    Design: Difficulty/transitive_cascade/activate_cascades_rental_finalization
    """
    ctx = setup_activated_single_collocation()
    assert ctx["node"]["status"] == "ACTIVATED"
    assert ctx["structure"]["active_collocations"] == 1
    assert ctx["structure"]["reserved_collocations"] == 0


def test_activate_finalizes_pending_rental_to_active(api):
    """PRD §3.8: "Its `PENDING` rental moves to `ACTIVE` with `actual_amount_cents`
    computed against the activation clock, `period_start` set to the current clock,
    `period_end` set to January 1 of the following year, and `billing_year` set to
    the current calendar year."

    Design: Difficulty/transitive_cascade/activate_cascades_rental_finalization
    """
    ctx = setup_activated_single_collocation(activation_clock="2026-08-20T00:00:00Z")
    rental = ctx["rental"]
    assert rental["status"] == "ACTIVE"
    assert rental["actual_amount_cents"] == 9912
    assert rental["billing_year"] == 2026


# ─── Difficulty: activate_state_beats_invoice_unpaid ──────────────────────
def _approved_but_undecided_unpaid():
    """Single node design-PASSed to APPROVED; application NOT decided (node not
    PERMITTED); invoice unpaid."""
    ctx = setup_under_review_single()
    record_design_review(ctx["node"]["id"], ctx["structure"]["id"], outcome="PASS")
    ctx["node"] = fetch_node(ctx["node"]["id"])
    return ctx


def test_activate_on_approved_node_returns_invalid_state(api):
    """PRD §2.10: "then whether the target resource is in a legal from-state for the
    requested transition (`ERR_INVALID_STATE`). Only after those universal gates do
    endpoint-specific business rules run."

    Design: Difficulty/priority_pair_validation_conflict/activate_state_beats_invoice_unpaid
    """
    ctx = _approved_but_undecided_unpaid()
    assert ctx["node"]["status"] == "APPROVED"
    res = api.activate_node(ctx["node"]["id"], INSPECTOR)
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_activate_state_check_preempts_invoice_unpaid(api):
    """PRD §3.8: "Activation is the terminal step that brings a node into service,
    performed by an `Inspector`. It is admissible only when the node is `PERMITTED`,
    its latest inspection outcome is `PASS` (otherwise `ERR_INSPECTION_NOT_PASSED`),
    and the application's fee invoice is fully paid with an `outstanding_amount_cents`
    of zero (otherwise `ERR_INVOICE_UNPAID`)."

    Design: Difficulty/priority_pair_validation_conflict/activate_state_beats_invoice_unpaid
    """
    ctx = _approved_but_undecided_unpaid()
    res = api.activate_node(ctx["node"]["id"], INSPECTOR)
    body = res.json()["data"]
    assert body["error_id"] == "ERR_INVALID_STATE"
    assert body["error_id"] != "ERR_INVOICE_UNPAID"


# ─── Difficulty: rental_period_overlap_half_open_adjacency ────────────────
def test_overlapping_renewal_rejected(api):
    """PRD §3.7: "The requested half-open interval must not overlap any non-`VOID`
    rental of the same node, though intervals that merely touch at an endpoint are
    allowed; an overlap is rejected with `ERR_RENTAL_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rental_period_overlap_half_open_adjacency
    """
    ctx = setup_activated_single_collocation(activation_clock="2026-08-20T00:00:00Z")
    rental = ctx["rental"]  # ACTIVE over [2026-08-20, 2027-01-01)
    res = api.renew_rental(
        rental["id"],
        renew_payload("2026-12-15T00:00:00Z", "2027-06-01T00:00:00Z"),
        ADMIN,
    )
    validate_error(res, "ERR_RENTAL_PERIOD_OVERLAP", 409)


def test_adjacent_renewal_at_prior_period_end_succeeds(api):
    """PRD §3.7: "though intervals that merely touch at an endpoint are allowed" "On
    renewal the current rental moves to `EXPIRED` and a new `ACTIVE` rental is created
    for the requested period."

    Design: Difficulty/resource_temporal_overlap/rental_period_overlap_half_open_adjacency
    """
    ctx = setup_activated_single_collocation(activation_clock="2026-08-20T00:00:00Z")
    rental = ctx["rental"]  # period_end 2027-01-01
    res = api.renew_rental(
        rental["id"],
        renew_payload("2027-01-01T00:00:00Z", "2028-01-01T00:00:00Z"),
        ADMIN,
    )
    new_rental = validate_success(res, 201)
    assert new_rental["status"] == "ACTIVE"


# ─── Difficulty: shot_clock_deadline_exact_vs_after ───────────────────────
def test_evaluate_at_exact_deadline_refused(api):
    """PRD §3.6: "The deemed grant only fires when the current clock is strictly past
    the `shot_clock_deadline`; at a clock exactly equal to the deadline the request is
    refused with `ERR_SHOT_CLOCK_NOT_EXPIRED`."

    Design: Difficulty/boundary_precision_check/shot_clock_deadline_exact_vs_after
    """
    ctx = setup_submitted_single()  # deadline 2026-07-31T00:00:00.000Z
    set_clock("2026-07-31T00:00:00Z")
    res = api.evaluate_deadline(ctx["app"]["id"], ADMIN)
    validate_error(res, "ERR_SHOT_CLOCK_NOT_EXPIRED", 409)


def test_evaluate_one_second_past_deadline_deems_granted(api):
    """PRD §3.6: "When the clock has strictly passed the deadline, the application
    moves to `DEEMED_GRANTED`: `decided_at` is set to the current clock, every node
    that is not already `REJECTED`, `DENIED`, or `WITHDRAWN` advances to `PERMITTED`,"

    Design: Difficulty/boundary_precision_check/shot_clock_deadline_exact_vs_after
    """
    ctx = setup_submitted_single()
    set_clock("2026-07-31T00:00:01Z")
    res = api.evaluate_deadline(ctx["app"]["id"], ADMIN)
    updated = validate_success(res, 200)
    assert updated["status"] == "DEEMED_GRANTED"


# ─── Corner: activate_without_passing_inspection_rejected ─────────────────
def test_activate_without_passing_inspection_rejected(api):
    """PRD §3.8: "It is admissible only when the node is `PERMITTED`, its latest
    inspection outcome is `PASS` (otherwise `ERR_INSPECTION_NOT_PASSED`), and the
    application's fee invoice is fully paid with an `outstanding_amount_cents` of zero
    (otherwise `ERR_INVOICE_UNPAID`)."

    Design: Corner/validations/activate_without_passing_inspection_rejected
    """
    ctx = setup_granted_single_collocation(pay=True, inspect=True, inspection_outcome="FAIL")
    res = api.activate_node(ctx["node"]["id"], INSPECTOR)
    validate_error(res, "ERR_INSPECTION_NOT_PASSED", 409)


# ─── Corner: terminal_deemed_granted_blocks_further_evaluate ──────────────
def test_second_evaluate_on_deemed_granted_rejected(api):
    """PRD §3.9: "The states `GRANTED`, `DEEMED_GRANTED`, `WITHDRAWN`,
    `APPEAL_GRANTED`, and `APPEAL_DENIED` are terminal for an application."
    PRD §2.10: "then whether the target resource is in a legal from-state for the
    requested transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/terminal_deemed_granted_blocks_further_evaluate
    """
    ctx = setup_submitted_single()
    set_clock("2026-09-01T00:00:00Z")
    validate_success(api.evaluate_deadline(ctx["app"]["id"], ADMIN), 200)
    res = api.evaluate_deadline(ctx["app"]["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", 409)


# ─── Corner: appeal_from_granted_application_rejected ─────────────────────
def test_appeal_from_granted_application_rejected(api):
    """PRD §3.9: "When an application is `DENIED` or `PARTIALLY_GRANTED`, its owner
    may appeal it, supplying the `grounds` for the appeal; filing moves the
    application to `UNDER_APPEAL` and creates an appeal in `FILED` status. Appealing
    an application in any other state is rejected with `ERR_APPEAL_NOT_ALLOWED`."

    Design: Corner/state_machines/appeal_from_granted_application_rejected
    """
    ctx = setup_granted_single_collocation(pay=False)
    app_now = api.get_application(ctx["app"]["id"], ADMIN).json()["data"]
    assert app_now["status"] == "GRANTED"
    res = api.create_appeal(
        ctx["app"]["id"], appeal_payload(grounds="disagree"),
        make_applicant_headers(ctx["applicant"]["id"]),
    )
    validate_error(res, "ERR_APPEAL_NOT_ALLOWED", 409)


# ─── Corner: appeal_overturn_repermits_denied_nodes ───────────────────────
def test_appeal_overturn_repermits_denied_nodes(api):
    """PRD §3.9: "Deciding not to uphold overturns the denial: the appeal moves to
    `OVERTURNED` with its `decided_by_user_id` set from `X-User-ID`, the application
    moves from `UNDER_APPEAL` to `APPEAL_GRANTED`, each previously `DENIED` node
    advances to `PERMITTED` and receives a new `PENDING` recurring rental estimated
    against the current clock,"

    Design: Corner/state_machines/appeal_overturn_repermits_denied_nodes
    """
    ctx = setup_denied_single_collocation(pay=False)
    appeal = validate_success(
        api.create_appeal(
            ctx["app"]["id"], appeal_payload(grounds="reconsider"),
            make_applicant_headers(ctx["applicant"]["id"]),
        ),
        201,
    )
    decided = validate_success(
        api.decide_appeal(appeal["id"], appeal_decision_payload(uphold=False), make_approver_headers("approver-1")),
        200,
    )
    assert decided["status"] == "OVERTURNED"
    app_after = api.get_application(ctx["app"]["id"], ADMIN).json()["data"]
    assert app_after["status"] == "APPEAL_GRANTED"
    assert fetch_node(ctx["node"]["id"])["status"] == "PERMITTED"
