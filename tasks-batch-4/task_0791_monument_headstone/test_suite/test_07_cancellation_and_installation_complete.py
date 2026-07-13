"""Cancellation cascade + refund conservation, capacity release, and the installation-complete
transition that opens the warranty window."""
import test_helpers as th


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / order_cancel_installation_permit_crew_chain
# ---------------------------------------------------------------------------
def test_cancel_cascades_to_installation_and_permit(api):
    """PRD §3.7: "Any `SCHEDULED` installation for the order is moved to `CANCELLED`, and its
    `duration_minutes` is released from its crew's `booked_minutes`. Any `PENDING` or `ISSUED`
    permit for the order is moved to `REVOKED`."

    Design: Difficulty/transitive_cascade/order_cancel_installation_permit_crew_chain
    """
    ctx = th.setup_scheduled_installation(
        inst_start="2026-03-25T09:00:00Z", inst_end="2026-03-25T11:00:00Z", permit_number="P-100",
    )
    order = th.validate_success(api.cancel_order(ctx["order"]["id"], ctx["customer_headers"]))
    assert order["production_status"] == "CANCELLED", order
    inst = th.validate_success(api.get_installation(ctx["installation"]["id"], th.TEST_USERS["field_ops_headers"]))
    assert inst["status"] == "CANCELLED", inst
    permit = th.validate_success(api.get_permit(ctx["permit"]["id"], th.TEST_USERS["field_ops_headers"]))
    assert permit["status"] == "REVOKED", permit


def test_cancel_releases_crew_capacity(api):
    """PRD §2.7: "a crew's `booked_minutes` is the sum of `duration_minutes` across its
    `SCHEDULED` installations." PRD §2.7: "These figures move up as slots are booked and back
    down as slots complete or are cancelled, and they must never drift away from that defining
    sum."

    Design: Difficulty/transitive_cascade/order_cancel_installation_permit_crew_chain
    """
    ctx = th.setup_scheduled_installation(
        inst_start="2026-03-25T09:00:00Z", inst_end="2026-03-25T11:00:00Z", permit_number="P-100",
    )
    th.validate_success(api.cancel_order(ctx["order"]["id"], ctx["customer_headers"]))
    data, _meta = th.validate_paginated(
        api.list_installations(th.TEST_USERS["field_ops_headers"], params={"crew_id": ctx["crew"]["id"]})
    )
    scheduled = [i for i in data if i["status"] == "SCHEDULED"]
    assert sum(i["duration_minutes"] for i in scheduled) == 0, data


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / installation_complete_marks_order_installed
# ---------------------------------------------------------------------------
def test_installation_complete_marks_order_installed(api):
    """PRD §3.6: "Completion stamps the installation's `completed_at` from the logical clock,
    moves it from `SCHEDULED` to `COMPLETED`, releases the crew slot by decreasing the crew's
    `booked_minutes` by the installation's `duration_minutes`, advances the order from
    `READY_TO_INSTALL` to `INSTALLED`, and opens the warranty window by setting
    `warranty_expires_at`."

    Design: Difficulty/transitive_cascade/installation_complete_marks_order_installed
    """
    ctx = th.setup_scheduled_installation(
        inst_start="2026-03-25T09:00:00Z", inst_end="2026-03-25T11:00:00Z", permit_number="P-101",
        pay_balance=True, balance_cents=53371,
    )
    th.set_clock("2026-03-25T12:00:00Z")
    inst = th.validate_success(api.complete_installation(ctx["installation"]["id"], th.TEST_USERS["field_ops_headers"]))
    assert inst["status"] == "COMPLETED", inst
    order = th.validate_success(api.get_order(ctx["order"]["id"], ctx["customer_headers"]))
    assert order["production_status"] == "INSTALLED", order


def test_installation_complete_opens_human_warranty_window(api):
    """PRD §3.6: "The warranty length depends on the subject: a `HUMAN` marker carries a ten-year
    warranty (120 months) and a `PET` marker a five-year warranty (60 months), each measured
    forward in calendar months from the installation's `completed_at`."

    Design: Difficulty/transitive_cascade/installation_complete_marks_order_installed
    """
    ctx = th.setup_scheduled_installation(
        inst_start="2026-03-25T09:00:00Z", inst_end="2026-03-25T11:00:00Z", permit_number="P-101",
        pay_balance=True, balance_cents=53371,
    )
    th.set_clock("2026-03-25T12:00:00Z")
    th.validate_success(api.complete_installation(ctx["installation"]["id"], th.TEST_USERS["field_ops_headers"]))
    order = th.validate_success(api.get_order(ctx["order"]["id"], ctx["customer_headers"]))
    th.assert_instant_equals(order["warranty_expires_at"], "2036-03-25T12:00:00Z", "warranty_expires_at")


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / cancel_refund_money_conservation
# ---------------------------------------------------------------------------
def test_cancel_refunds_paid_deposit_to_zero(api):
    """PRD §3.7: "If the order's `amount_paid_cents` is greater than zero at cancellation, the
    system creates a `REFUND` payment for the negative of the paid amount, so that recomputing
    `amount_paid_cents` over the captured ledger returns it to zero, and the order's
    `payment_status` moves to `REFUNDED`."

    Design: Difficulty/compensating_invariant/cancel_refund_money_conservation
    """
    ctx = th.setup_deposit_paid_order(
        deposit_cents=33880, cemetery_over={"requires_permit": True, "permit_fee_cents": 12000},
    )
    order = th.validate_success(api.cancel_order(ctx["order"]["id"], ctx["customer_headers"]))
    assert order["amount_paid_cents"] == 0, order
    assert order["payment_status"] == "REFUNDED", order
    assert order["production_status"] == "CANCELLED", order


def test_cancel_refund_ledger_signed_sum_is_zero(api):
    """PRD §3.4: "The order's `amount_paid_cents` is always exactly the sum of `signed_amount_cents`
    over that order's `CAPTURED` payments".

    Design: Difficulty/compensating_invariant/cancel_refund_money_conservation
    """
    ctx = th.setup_deposit_paid_order(
        deposit_cents=33880, cemetery_over={"requires_permit": True, "permit_fee_cents": 12000},
    )
    th.validate_success(api.cancel_order(ctx["order"]["id"], ctx["customer_headers"]))
    data, _meta = th.validate_paginated(
        api.list_order_payments(ctx["order"]["id"], ctx["customer_headers"])
    )
    captured = [p for p in data if p["status"] == "CAPTURED"]
    assert sum(p["signed_amount_cents"] for p in captured) == 0, captured


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / cancel_release_workshop_capacity_conservation
# ---------------------------------------------------------------------------
def test_cancel_cancels_scheduled_fabrication_job(api):
    """PRD §3.7: "Any `SCHEDULED` fabrication job for the order is moved to `CANCELLED`, and that
    job's `duration_minutes` is released from its workshop's `booked_minutes`."

    Design: Difficulty/compensating_invariant/cancel_release_workshop_capacity_conservation
    """
    ctx = th.setup_in_fabrication(
        proof_lines=[21, 31], cemetery_over={"requires_permit": False, "permit_fee_cents": 0},
    )
    order = th.validate_success(api.cancel_order(ctx["order"]["id"], ctx["customer_headers"]))
    assert order["production_status"] == "CANCELLED", order
    fab = th.validate_success(api.get_fabrication_job(ctx["fabrication_job"]["id"], th.TEST_USERS["shop_manager_headers"]))
    assert fab["status"] == "CANCELLED", fab


def test_cancel_releases_workshop_capacity(api):
    """PRD §2.7: "A workshop's `booked_minutes` is always exactly the sum of `duration_minutes`
    across its `SCHEDULED` fabrication jobs and its `ASSESSED` restoration jobs".

    Design: Difficulty/compensating_invariant/cancel_release_workshop_capacity_conservation
    """
    ctx = th.setup_in_fabrication(
        proof_lines=[21, 31], cemetery_over={"requires_permit": False, "permit_fee_cents": 0},
    )
    th.validate_success(api.cancel_order(ctx["order"]["id"], ctx["customer_headers"]))
    data, _meta = th.validate_paginated(
        api.list_fabrication_jobs(th.TEST_USERS["shop_manager_headers"], params={"workshop_id": ctx["workshop"]["id"]})
    )
    scheduled = [j for j in data if j["status"] == "SCHEDULED"]
    assert sum(j["duration_minutes"] for j in scheduled) == 0, data


# ---------------------------------------------------------------------------
# Corner: state_machines / cancel_terminal_order_returns_already_terminal
# ---------------------------------------------------------------------------
def test_cancel_already_cancelled_order_returns_already_terminal(api):
    """PRD §3.7: "A cancel attempted on an order already `INSTALLED` or `CANCELLED` is rejected
    with `ERR_ORDER_ALREADY_TERMINAL`."

    Design: Corner/state_machines/cancel_terminal_order_returns_already_terminal
    """
    ctx = th.setup_drafting_order(cemetery_over={"requires_permit": False, "permit_fee_cents": 0})
    th.validate_success(api.cancel_order(ctx["order"]["id"], ctx["customer_headers"]))
    resp = api.cancel_order(ctx["order"]["id"], ctx["customer_headers"])
    th.validate_error(resp, th.ApiErrorId.ERR_ORDER_ALREADY_TERMINAL.value)
