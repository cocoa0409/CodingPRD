"""Order/audit branching, the cap-conversion and recoupment cascades, the
13-month cap boundary, cycle-period overlap, the ledger-conservation invariant,
and the broad order/delivery/cycle state-machine transitions.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    assert_ledger_identity,
    fixtures,
    factories as f,
)
from test_helpers.test_users import make_supplier_headers, TEST_USERS

PHYSICIAN = TEST_USERS["physician_headers"]
PAYER = TEST_USERS["payer_headers"]


# ─── Difficulty: non_linear_state_machine ─────────────
def test_order_close_branch_from_active_without_cap(api):
    """PRD §3.8: "a SupplierUser closes it, moving it from ACTIVE to the terminal
    CLOSED status. Closing requires the order to be ACTIVE."

    Design: Difficulty/non_linear_state_machine/dme_order_branch_convert_vs_close
    """
    order, supplier, item, cycles = fixtures.setup_rental_with_cycles(
        2, monthly_rental_cents=10000, modifier="KX",
    )
    sup_headers = make_supplier_headers(supplier["id"])
    resp = api.close_order(order["id"], sup_headers)
    data = validate_success(resp, 200)
    assert data["status"] == "CLOSED"
    assert data["cap_reached"] is False


def test_order_convert_branch_from_active_at_cap(api):
    """PRD §3.7: "When the cycle that posts pushes rental_months_billed to 13 on a
    CAPPED_RENTAL order, a cascade fires: the cycle posts in BILLED status, the
    order's rental_months_billed becomes 13 and cap_reached becomes true, and the
    order advances from ACTIVE to the terminal CONVERTED_TO_PURCHASE status."

    Design: Difficulty/non_linear_state_machine/dme_order_branch_convert_vs_close
    """
    starts = fixtures.distinct_month_starts(13)
    order, supplier, item, cycles = fixtures.setup_rental_with_cycles(
        13, monthly_rental_cents=10000, modifier="KX", with_period_starts=starts,
    )
    sup_headers = make_supplier_headers(supplier["id"])
    order = get_success_data(api.get_order(order["id"], sup_headers))
    assert order["status"] == "CONVERTED_TO_PURCHASE"
    assert order["cap_reached"] is True


def test_audit_dismiss_branch_has_no_ledger_effect(api):
    """PRD §3.11: "Dismissing moves the audit to the terminal DISMISSED status with
    no ledger effect."

    Design: Difficulty/non_linear_state_machine/audit_branch_uphold_vs_dismiss
    """
    order, supplier, item, cycles, audit = fixtures.setup_audit_ready(
        2, reason_code="NO_VALID_CMN", monthly_rental_cents=10000, modifier="KX",
    )
    resp = api.dismiss_audit(audit["id"], PAYER)
    data = validate_success(resp, 200)
    assert data["status"] == "DISMISSED"
    assert data["recouped_total_cents"] == 0

    sup_headers = make_supplier_headers(supplier["id"])
    order = get_success_data(api.get_order(order["id"], sup_headers))
    assert order["total_allowed_cents"] == 20000


def test_audit_uphold_branch_runs_recoupment(api):
    """PRD §3.11: "Upholding an audit runs the recoupment cascade and moves the
    audit to the terminal UPHELD status."

    Design: Difficulty/non_linear_state_machine/audit_branch_uphold_vs_dismiss
    """
    order, supplier, item, cycles, audit = fixtures.setup_audit_ready(
        2, reason_code="OVERBILLED_PAST_CAP", monthly_rental_cents=10000, modifier="KX",
    )
    resp = api.uphold_audit(audit["id"], PAYER)
    data = validate_success(resp, 200)
    assert data["status"] == "UPHELD"
    assert data["recouped_total_cents"] == 20000


# ─── Difficulty: transitive_cascade ───────────────────
def test_audit_uphold_recoupment_cascade_recoups_and_voids(api):
    """PRD §3.11: "For each such cycle, the cycle moves to RECOUPED; one
    system-created claim line of type RECOUPMENT is created whose allowed_amount_cents
    is the negation of that cycle's already-rounded billed_amount_cents and whose
    audit_id is the upholding audit's id; and the cycle's original linked claim line
    moves to VOID."

    Design: Difficulty/transitive_cascade/audit_uphold_recoupment_cascade_depth3
    """
    order, supplier, item, cycles, audit = fixtures.setup_audit_ready(
        2, reason_code="OVERBILLED_PAST_CAP", monthly_rental_cents=10000, modifier="KX",
    )
    upheld = validate_success(api.uphold_audit(audit["id"], PAYER), 200)
    assert upheld["recouped_total_cents"] == 20000

    cyc1 = get_success_data(api.get_rental_cycle(cycles[0]["id"], PAYER))
    assert cyc1["status"] == "RECOUPED"


def test_audit_uphold_cascade_recomputes_order_total(api):
    """PRD §3.11: "After all cycles are processed, the order's total_allowed_cents
    is recomputed."
    PRD §3.9: "recoupment lines are system-created and carry negative
    allowed_amount_cents. ... Lines in VOID status drop out of the order's
    total_allowed_cents."

    Design: Difficulty/transitive_cascade/audit_uphold_recoupment_cascade_depth3
    """
    order, supplier, item, cycles, audit = fixtures.setup_audit_ready(
        2, reason_code="OVERBILLED_PAST_CAP", monthly_rental_cents=10000, modifier="KX",
    )
    get_success_data(api.uphold_audit(audit["id"], PAYER))
    sup_headers = make_supplier_headers(supplier["id"])
    order = get_success_data(api.get_order(order["id"], sup_headers))
    # 2 originals VOID + 2 RECOUPMENT lines of -10000 each => -20000.
    assert order["total_allowed_cents"] == -20000


def test_cap_conversion_cascade_sets_flags_and_status(api):
    """PRD §3.7: "the cycle posts in BILLED status, the order's rental_months_billed
    becomes 13 and cap_reached becomes true, and the order advances from ACTIVE to
    the terminal CONVERTED_TO_PURCHASE status."

    Design: Difficulty/transitive_cascade/cap_conversion_cascade_depth2
    """
    starts = fixtures.distinct_month_starts(12)
    order, supplier, item, cycles = fixtures.setup_rental_with_cycles(
        12, monthly_rental_cents=10000, modifier="KX", with_period_starts=starts,
    )
    sup_headers = make_supplier_headers(supplier["id"])
    # Post the 13th cycle — triggers the cascade.
    get_success_data(
        api.post_rental_cycle(order["id"], sup_headers, {"period_start_utc": "2027-01-01T00:00:00Z"})
    )
    order = get_success_data(api.get_order(order["id"], sup_headers))
    assert order["rental_months_billed"] == 13
    assert order["cap_reached"] is True
    assert order["status"] == "CONVERTED_TO_PURCHASE"


def test_cap_not_reached_at_twelfth_cycle(api):
    """PRD §3.7: "posting the 12th cycle leaves the cap not reached, while posting
    the 13th cycle reaches it."

    Design: Difficulty/transitive_cascade/cap_conversion_cascade_depth2
    """
    starts = fixtures.distinct_month_starts(12)
    order, supplier, item, cycles = fixtures.setup_rental_with_cycles(
        12, monthly_rental_cents=10000, modifier="KX", with_period_starts=starts,
    )
    sup_headers = make_supplier_headers(supplier["id"])
    order = get_success_data(api.get_order(order["id"], sup_headers))
    assert order["rental_months_billed"] == 12
    assert order["cap_reached"] is False
    assert order["status"] == "ACTIVE"


# ─── Difficulty: boundary_precision_check (rental cap) ─
def test_rental_cap_boundary_at_twelve(api):
    """PRD §3.7: "an order is considered to have reached the cap when its
    billing_category is CAPPED_RENTAL and its rental_months_billed is at least 13.
    Concretely, posting the 12th cycle leaves the cap not reached."

    Design: Difficulty/boundary_precision_check/rental_cap_13_boundary
    """
    starts = fixtures.distinct_month_starts(12)
    order, supplier, item, cycles = fixtures.setup_rental_with_cycles(
        12, monthly_rental_cents=10000, modifier="KX", with_period_starts=starts,
    )
    sup_headers = make_supplier_headers(supplier["id"])
    order = get_success_data(api.get_order(order["id"], sup_headers))
    assert order["rental_months_billed"] == 12
    assert order["cap_reached"] is False
    assert order["status"] == "ACTIVE"


def test_rental_cap_boundary_at_thirteen(api):
    """PRD §3.7: "while posting the 13th cycle reaches it. ... the order's
    rental_months_billed becomes 13 and cap_reached becomes true, and the order
    advances from ACTIVE to the terminal CONVERTED_TO_PURCHASE status."

    Design: Difficulty/boundary_precision_check/rental_cap_13_boundary
    """
    starts = fixtures.distinct_month_starts(13)
    order, supplier, item, cycles = fixtures.setup_rental_with_cycles(
        13, monthly_rental_cents=10000, modifier="KX", with_period_starts=starts,
    )
    sup_headers = make_supplier_headers(supplier["id"])
    order = get_success_data(api.get_order(order["id"], sup_headers))
    assert order["rental_months_billed"] == 13
    assert order["cap_reached"] is True
    assert order["status"] == "CONVERTED_TO_PURCHASE"


# ─── Difficulty: resource_temporal_overlap (cycle) ────
def test_cycle_period_overlap_rejected(api):
    """PRD §3.7: "the new cycle's period must not overlap any existing cycle on the
    order; the period is half-open, so a new period whose start equals a prior
    period's end is allowed, but any true overlap is rejected with ERR_CYCLE_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/rental_cycle_period_overlap_halfopen
    """
    order, supplier, item, cycles = fixtures.setup_rental_with_cycles(
        1, monthly_rental_cents=10000, modifier="KX",
        with_period_starts=["2026-01-01T00:00:00Z"],
    )
    sup_headers = make_supplier_headers(supplier["id"])
    # 2026-01-15 falls strictly inside [2026-01-01, 2026-02-01).
    resp = api.post_rental_cycle(
        order["id"], sup_headers, {"period_start_utc": "2026-01-15T00:00:00Z"}
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_OVERLAP.value)


def test_cycle_adjacent_boundary_allowed(api):
    """PRD §3.7: "the period is half-open, so a new period whose start equals a
    prior period's end is allowed."

    Design: Difficulty/resource_temporal_overlap/rental_cycle_period_overlap_halfopen
    """
    order, supplier, item, cycles = fixtures.setup_rental_with_cycles(
        1, monthly_rental_cents=10000, modifier="KX",
        with_period_starts=["2026-01-01T00:00:00Z"],
    )
    sup_headers = make_supplier_headers(supplier["id"])
    # 2026-02-01 == prior period_end, an allowed adjacent boundary.
    resp = api.post_rental_cycle(
        order["id"], sup_headers, {"period_start_utc": "2026-02-01T00:00:00Z"}
    )
    data = validate_success(resp, 201)
    assert data["status"] == "BILLED"


# ─── Difficulty: compensating_invariant (ledger) ──────
def test_recoupment_ledger_total_is_negative_sum(api):
    """PRD §2.7: "Its total_allowed_cents is always the sum of allowed_amount_cents
    across all of the order's claim lines whose status is not VOID; recoupment lines
    participate in this sum as negative amounts."

    Design: Difficulty/compensating_invariant/recoupment_ledger_cents_conserved
    """
    order, supplier, item, cycles, audit = fixtures.setup_audit_ready(
        2, reason_code="OVERBILLED_PAST_CAP", monthly_rental_cents=10000, modifier="KX",
    )
    get_success_data(api.uphold_audit(audit["id"], PAYER))
    sup_headers = make_supplier_headers(supplier["id"])
    order = get_success_data(api.get_order(order["id"], sup_headers))
    assert order["total_allowed_cents"] == -20000


def test_recoupment_ledger_identity_holds_no_drift(api):
    """PRD §2.7: "after any such event — including the full audit recoupment cascade
    — the order's total_allowed_cents equals the sum of allowed_amount_cents over its
    non-VOID claim lines, with no drift."

    Design: Difficulty/compensating_invariant/recoupment_ledger_cents_conserved
    """
    order, supplier, item, cycles, audit = fixtures.setup_audit_ready(
        2, reason_code="OVERBILLED_PAST_CAP", monthly_rental_cents=10000, modifier="KX",
    )
    get_success_data(api.uphold_audit(audit["id"], PAYER))
    sup_headers = make_supplier_headers(supplier["id"])
    order = get_success_data(api.get_order(order["id"], sup_headers))
    claim_lines, _ = api_list_claim_lines(api, order["id"])
    assert_ledger_identity(order, claim_lines)
    live_sum = sum(cl["allowed_amount_cents"] for cl in claim_lines if cl["status"] != "VOID")
    assert live_sum == -20000


def api_list_claim_lines(api, order_id):
    from test_helpers import validate_paginated
    resp = api.list_claim_lines(PAYER, params={"order_id": order_id, "limit": 100})
    return validate_paginated(resp)


# ─── Corner: §state_machines ──────────────────────────
def test_confirm_already_confirmed_delivery_invalid_state(api):
    """PRD §3.5: "From SCHEDULED, a delivery may be confirmed, failed, or cancelled;
    each of these requires that the delivery currently be SCHEDULED, otherwise
    ERR_INVALID_STATE applies."

    Design: Corner/state_machines/confirm_already_confirmed_delivery_invalid_state
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL"},
    )
    _, delivery = fixtures.drive_order_to_delivered(order, supplier, pod_signature_name="IC1")
    sup_headers = make_supplier_headers(supplier["id"])
    resp = api.confirm_delivery(delivery["id"], "IC1", sup_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_non_draft_order_invalid_state(api):
    """PRD §3.2: "Cancelling is available only while the order is still in DRAFT; a
    cancel request against an order in any other status is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_non_draft_order_invalid_state
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL"},
    )
    fixtures.drive_order_to_ready(order, supplier)
    sup_headers = make_supplier_headers(supplier["id"])
    resp = api.cancel_order(order["id"], sup_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_draft_order_revokes_cmn_and_cancels_delivery(api):
    """PRD §3.2: "every certificate for that order that is in DRAFT or ACTIVE status
    is moved to REVOKED, and every delivery for that order that is in SCHEDULED status
    is moved to CANCELLED."

    Design: Corner/state_machines/cancel_draft_order_revokes_cmn_and_cancels_delivery
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_cmn": True},
    )
    cmn, _ = fixtures.activate_cmn_for_order(order, supplier, signed_date="2025-12-20")
    sup_headers = make_supplier_headers(supplier["id"])
    delivery = get_success_data(
        api.create_delivery(f.create_delivery_payload(order["id"]), sup_headers)
    )
    cancelled = validate_success(api.cancel_order(order["id"], sup_headers), 200)
    assert cancelled["status"] == "CANCELLED"

    cmn_after = get_success_data(api.get_cmn(cmn["id"], PHYSICIAN))
    assert cmn_after["status"] == "REVOKED"
    del_after = get_success_data(api.get_delivery(delivery["id"], sup_headers))
    assert del_after["status"] == "CANCELLED"


def test_deny_prior_auth_branch_captures_reason(api):
    """PRD §3.4: "denial moves it from PENDING to DENIED ... The reviewer may attach
    a decision_reason on either decision, and whatever reason is supplied is captured
    onto the authorization."

    Design: Corner/state_machines/deny_prior_auth_branch
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL", "requires_prior_auth": True},
    )
    sup_headers = make_supplier_headers(supplier["id"])
    pa = get_success_data(
        api.create_prior_auth(f.create_prior_auth_payload(order["id"]), sup_headers)
    )
    resp = api.deny_prior_auth(pa["id"], PAYER, {"decision_reason": "Insufficient documentation"})
    data = validate_success(resp, 200)
    assert data["status"] == "DENIED"
    assert data["decision_reason"] == "Insufficient documentation"


def test_mark_paid_already_paid_cycle_invalid_state(api):
    """PRD §3.7: "A PayerReviewer marks a BILLED cycle as paid, which requires the
    cycle to be in BILLED status (ERR_INVALID_STATE otherwise)."

    Design: Corner/state_machines/mark_paid_already_paid_cycle_invalid_state
    """
    order, supplier, item, cycles = fixtures.setup_rental_with_cycles(
        1, monthly_rental_cents=10000, modifier="KX",
    )
    cyc = cycles[0]
    get_success_data(api.mark_paid(cyc["id"], PAYER))
    resp = api.mark_paid(cyc["id"], PAYER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_mark_paid_settles_claim_line(api):
    """PRD §3.7: "moves the cycle to PAID, and moves its linked claim line from
    POSTED to SETTLED."

    Design: Corner/state_machines/mark_paid_settles_claim_line
    """
    from test_helpers import validate_paginated
    order, supplier, item, cycles = fixtures.setup_rental_with_cycles(
        1, monthly_rental_cents=10000, modifier="KX",
    )
    cyc = cycles[0]
    paid = validate_success(api.mark_paid(cyc["id"], PAYER), 200)
    assert paid["status"] == "PAID"

    lines, _ = validate_paginated(
        api.list_claim_lines(PAYER, params={"rental_cycle_id": cyc["id"], "limit": 100})
    )
    assert len(lines) == 1
    assert lines[0]["status"] == "SETTLED"


def test_terminal_order_cancelled_lockdown(api):
    """PRD §3.6: "Moving an order from DRAFT to READY_FOR_DELIVERY ... requires the
    order to be in DRAFT status (ERR_INVALID_STATE otherwise)."
    PRD §3.2: "the order moves to the terminal CANCELLED status."

    Design: Corner/state_machines/terminal_order_cancelled_lockdown
    """
    order, supplier, item, _ = fixtures.create_order(
        item_overrides={"billing_category": "CAPPED_RENTAL"},
    )
    sup_headers = make_supplier_headers(supplier["id"])
    get_success_data(api.cancel_order(order["id"], sup_headers))
    resp = api.mark_ready(order["id"], sup_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
