"""Cyclic state machines, transitive ledger cascades, and compensating invariants.

Difficulty queue: non_linear_state_machine, transitive_cascade, compensating_invariant.
Corner queue: state_machines transitions, consistency-model supersede, standing generate.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    setup_membership,
    setup_confirmed_engagement,
    setup_reconciled_expense,
    setup_time_logged,
    intake_request,
    accept_request,
    fulfill_request,
    log_time,
    create_active_member,
    create_plan,
    create_membership_payload,
    api_client,
)

AM = TEST_USERS["account_manager_headers"]
AGENT = TEST_USERS["concierge_agent_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]


# ─── Difficulty/non_linear_state_machine/service_request_hold_resume_cycle ──
def test_request_hold_then_resume_reenters_in_progress(api):
    """PRD §3.4: "Once in progress, the agent may put the request `ON_HOLD` and later
    resume it back to `IN_PROGRESS`, forming a client-input revision loop, and may
    ultimately fulfill it, moving `IN_PROGRESS` to the terminal `FULFILLED` status."

    Design: Difficulty/non_linear_state_machine/service_request_hold_resume_cycle
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    sr = intake_request(ctx, category="ERRAND", title="task")
    accept_request(sr["id"], "2026-03-02T09:00:00Z", "2026-03-02T10:00:00Z")
    held = validate_success(api.hold_service_request(sr["id"], AGENT))
    assert held["status"] == "ON_HOLD", f"expected ON_HOLD, got {held['status']}"
    resumed = validate_success(api.resume_service_request(sr["id"], AGENT))
    assert resumed["status"] == "IN_PROGRESS", f"expected IN_PROGRESS, got {resumed['status']}"


def test_request_second_hold_after_resume(api):
    """PRD §3.4: "Once in progress, the agent may put the request `ON_HOLD` and later
    resume it back to `IN_PROGRESS`, forming a client-input revision loop, and may
    ultimately fulfill it, moving `IN_PROGRESS` to the terminal `FULFILLED` status."

    Design: Difficulty/non_linear_state_machine/service_request_hold_resume_cycle
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    sr = intake_request(ctx, category="ERRAND", title="task")
    accept_request(sr["id"], "2026-03-02T09:00:00Z", "2026-03-02T10:00:00Z")
    api.hold_service_request(sr["id"], AGENT)
    api.resume_service_request(sr["id"], AGENT)
    held_again = validate_success(api.hold_service_request(sr["id"], AGENT))
    assert held_again["status"] == "ON_HOLD", f"expected ON_HOLD after second hold, got {held_again['status']}"


# ─── Difficulty/non_linear_state_machine/expense_dispute_resolve_cycle ──────
def test_expense_dispute_then_resolve_reenters_reconciled(api):
    """PRD §3.7: "A `FinanceOps` operator may dispute a reconciled expense, moving it from
    `RECONCILED` to `DISPUTED`, and later resolve it back from `DISPUTED` to `RECONCILED`;
    these two transitions form the expense reconciliation loop."

    Design: Difficulty/non_linear_state_machine/expense_dispute_resolve_cycle
    """
    s = setup_reconciled_expense(estimated_cost_lines=[1000], actual_cost_lines=[1000])
    exp_id = s["expense"]["id"]
    disputed = validate_success(api.dispute_expense(exp_id, FINANCE))
    assert disputed["status"] == "DISPUTED", f"expected DISPUTED, got {disputed['status']}"
    resolved = validate_success(api.resolve_expense(exp_id, FINANCE))
    assert resolved["status"] == "RECONCILED", f"expected RECONCILED, got {resolved['status']}"


def test_expense_second_dispute_after_resolve(api):
    """PRD §3.7: "A `FinanceOps` operator may dispute a reconciled expense, moving it from
    `RECONCILED` to `DISPUTED`, and later resolve it back from `DISPUTED` to `RECONCILED`;
    these two transitions form the expense reconciliation loop."

    Design: Difficulty/non_linear_state_machine/expense_dispute_resolve_cycle
    """
    s = setup_reconciled_expense(estimated_cost_lines=[1000], actual_cost_lines=[1000])
    exp_id = s["expense"]["id"]
    api.dispute_expense(exp_id, FINANCE)
    api.resolve_expense(exp_id, FINANCE)
    disputed_again = validate_success(api.dispute_expense(exp_id, FINANCE))
    assert disputed_again["status"] == "DISPUTED", f"expected DISPUTED, got {disputed_again['status']}"


# ─── Difficulty/transitive_cascade/time_entry_debit_ledger_cascade ──────────
def test_time_entry_cascades_cycle_and_membership(api):
    """PRD §2.6: "Logging or reversing time recomputes the cycle's `consumed_minutes`,
    `overage_minutes`, and `overage_charge_cents`; that in turn refreshes the membership's
    `hour_bank_remaining_minutes` and `outstanding_balance_cents`; and that finally
    refreshes the member's `lifetime_billed_cents`."

    Design: Difficulty/transitive_cascade/time_entry_debit_ledger_cascade
    """
    s = setup_time_logged(vip_tier="GOLD", plan_kind="GOLD", minutes=700)
    cycle = validate_success(api.get_billing_cycle(s["cycle_id"], AM))
    assert cycle["consumed_minutes"] == 700, f"expected 700, got {cycle['consumed_minutes']}"
    ms = validate_success(api.get_membership(s["ctx"]["ms_id"], AM))
    assert ms["outstanding_balance_cents"] == 12000, f"expected 12000, got {ms['outstanding_balance_cents']}"


def test_time_entry_cascades_to_member_lifetime(api):
    """PRD §2.6: "A member's `lifetime_billed_cents` is defined as the sum of
    `outstanding_balance_cents` across all of that member's memberships and is recomputed
    on any downstream ledger change."

    Design: Difficulty/transitive_cascade/time_entry_debit_ledger_cascade
    """
    s = setup_time_logged(vip_tier="GOLD", plan_kind="GOLD", minutes=700)
    member = validate_success(api.get_member(s["ctx"]["member_id"], AM))
    assert member["lifetime_billed_cents"] == 12000, f"expected 12000, got {member['lifetime_billed_cents']}"


# ─── Difficulty/transitive_cascade/engagement_reconcile_expense_cascade ─────
def test_reconcile_creates_expense_with_final_and_provisional(api):
    """PRD §3.7: "The expense snapshots the prior provisional charge as `estimated_cents`
    and the final charge as `actual_cents`, and records their difference as
    `variance_cents`, defined as the actual amount minus the estimated amount."

    Design: Difficulty/transitive_cascade/engagement_reconcile_expense_cascade
    """
    s = setup_reconciled_expense(estimated_cost_lines=[1000], actual_cost_lines=[2000], markup_pct=0.10)
    exp = s["expense"]
    assert exp["actual_cents"] == 2200, f"expected actual 2200, got {exp['actual_cents']}"
    assert exp["estimated_cents"] == 1100, f"expected estimated 1100, got {exp['estimated_cents']}"


def test_reconcile_cascades_delta_to_outstanding(api):
    """PRD §3.6: "The membership's `outstanding_balance_cents` is then recomputed to apply
    the delta between the final and prior provisional charge, and the member's
    `lifetime_billed_cents` follows."

    Design: Difficulty/transitive_cascade/engagement_reconcile_expense_cascade
    """
    s = setup_reconciled_expense(estimated_cost_lines=[1000], actual_cost_lines=[2000], markup_pct=0.10)
    ms = validate_success(api.get_membership(s["ctx"]["ms_id"], AM))
    assert ms["outstanding_balance_cents"] == 2200, f"expected 2200, got {ms['outstanding_balance_cents']}"


# ─── Difficulty/compensating_invariant/time_entry_reverse_conserves_minutes ─
def test_reverse_time_entry_restores_cycle(api):
    """PRD §3.5: "Reversal removes the entry's minutes from consideration and reruns the
    same cascade: the cycle's `consumed_minutes`, `overage_minutes`, and
    `overage_charge_cents` are recomputed with the reversed entry excluded, the membership
    rollups are refreshed, and the member's `lifetime_billed_cents` is recomputed."

    Design: Difficulty/compensating_invariant/time_entry_reverse_conserves_minutes
    """
    s = setup_time_logged(vip_tier="GOLD", plan_kind="GOLD", minutes=700)
    api.reverse_time_entry(s["time_entry"]["id"], AGENT)
    cycle = validate_success(api.get_billing_cycle(s["cycle_id"], AM))
    assert cycle["consumed_minutes"] == 0, f"expected 0, got {cycle['consumed_minutes']}"
    assert cycle["overage_minutes"] == 0, f"expected 0, got {cycle['overage_minutes']}"
    assert cycle["overage_charge_cents"] == 0, f"expected 0, got {cycle['overage_charge_cents']}"


def test_reverse_time_entry_restores_membership_rollups(api):
    """PRD §3.2: "The membership's `hour_bank_remaining_minutes` reflects the current
    `OPEN` cycle: it is the cycle's `included_minutes` minus its `consumed_minutes`, never
    below zero."
    PRD §3.6: "The membership's `outstanding_balance_cents` is the sum of two components:
    the total of `overage_charge_cents` across all of the membership's billing cycles, both
    `OPEN` and `CLOSED`, plus the total of `client_charge_cents` across the membership's
    engagements that are in `CONFIRMED` or `RECONCILED` status."

    Design: Difficulty/compensating_invariant/time_entry_reverse_conserves_minutes
    """
    s = setup_time_logged(vip_tier="GOLD", plan_kind="GOLD", minutes=700)
    api.reverse_time_entry(s["time_entry"]["id"], AGENT)
    ms = validate_success(api.get_membership(s["ctx"]["ms_id"], AM))
    assert ms["hour_bank_remaining_minutes"] == 600, f"expected 600, got {ms['hour_bank_remaining_minutes']}"
    assert ms["outstanding_balance_cents"] == 0, f"expected 0, got {ms['outstanding_balance_cents']}"


# ─── Difficulty/compensating_invariant/engagement_void_conserves_cents ──────
def test_void_confirmed_engagement_reverses_outstanding(api):
    """PRD §3.6: "Voiding a confirmed engagement reverses its provisional charge: the
    membership's `outstanding_balance_cents` is recomputed to remove it, and the member's
    `lifetime_billed_cents` follows."

    Design: Difficulty/compensating_invariant/engagement_void_conserves_cents
    """
    s = setup_confirmed_engagement(vip_tier="STANDARD", plan_kind="STD",
                                   markup_pct=0.10, estimated_cost_lines=[1000])
    voided = validate_success(api.void_engagement(s["engagement"]["id"], AGENT))
    assert voided["status"] == "VOID", f"expected VOID, got {voided['status']}"
    ms = validate_success(api.get_membership(s["ctx"]["ms_id"], AM))
    assert ms["outstanding_balance_cents"] == 0, f"expected 0, got {ms['outstanding_balance_cents']}"


def test_void_confirmed_engagement_reverses_member_lifetime(api):
    """PRD §3.6: "Voiding a confirmed engagement reverses its provisional charge: the
    membership's `outstanding_balance_cents` is recomputed to remove it, and the member's
    `lifetime_billed_cents` follows."

    Design: Difficulty/compensating_invariant/engagement_void_conserves_cents
    """
    s = setup_confirmed_engagement(vip_tier="STANDARD", plan_kind="STD",
                                   markup_pct=0.10, estimated_cost_lines=[1000])
    api.void_engagement(s["engagement"]["id"], AGENT)
    member = validate_success(api.get_member(s["ctx"]["member_id"], AM))
    assert member["lifetime_billed_cents"] == 0, f"expected 0, got {member['lifetime_billed_cents']}"


# ─── Corner/state_machines/accept_from_fulfilled_returns_invalid_state ──────
def test_accept_fulfilled_request_rejected(api):
    """PRD §3.4: "Any transition requested from a state in which it is not defined is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/accept_from_fulfilled_returns_invalid_state
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    sr = intake_request(ctx, category="ERRAND", title="t")
    accept_request(sr["id"], "2026-03-02T09:00:00Z", "2026-03-02T10:00:00Z")
    fulfill_request(sr["id"])
    resp = api.accept_service_request(
        sr["id"], {"scheduled_start": "2026-03-03T09:00:00Z", "scheduled_end": "2026-03-03T10:00:00Z"}, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Corner/state_machines/fulfill_from_submitted_returns_invalid_state ─────
def test_fulfill_submitted_request_rejected(api):
    """PRD §3.4: "Any transition requested from a state in which it is not defined is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/fulfill_from_submitted_returns_invalid_state
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    sr = intake_request(ctx, category="ERRAND", title="t")
    resp = api.fulfill_service_request(sr["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Corner/state_machines/reconcile_from_proposed_returns_invalid_state ────
def test_reconcile_proposed_engagement_rejected(api):
    """PRD §3.4: "Any transition requested from a state in which it is not defined is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/reconcile_from_proposed_returns_invalid_state
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    from test_helpers import create_vendor, intake_request as _ir, propose_engagement
    vendor = create_vendor(name="Bk", category="BOOKING")
    sr = _ir(ctx, category="BOOKING", title="r")
    eng = propose_engagement(sr["id"], vendor["id"], "MARKUP", [1000],
                             "2026-03-06T10:00:00Z", "2026-03-06T11:00:00Z", markup_pct=0.10)
    resp = api.reconcile_engagement(eng["id"], {"actual_cost_lines": [1000]}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Corner/state_machines/time_entry_double_reverse_returns_invalid_state ──
def test_double_reverse_time_entry_rejected(api):
    """PRD §3.4: "Any transition requested from a state in which it is not defined is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/time_entry_double_reverse_returns_invalid_state
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    sr = intake_request(ctx, category="ERRAND", title="t")
    te = log_time(sr["id"], 30)
    api.reverse_time_entry(te["id"], AGENT)
    resp = api.reverse_time_entry(te["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Corner/state_machines/membership_cancel_blocked_by_active_request ──────
def test_cancel_membership_with_active_request_rejected(api):
    """PRD §3.2: "An `AccountManager` may also cancel a membership from either `ACTIVE` or
    `PAUSED`, moving it to the terminal `CANCELLED` status, provided the membership has no
    `ServiceRequest` in `SUBMITTED`, `IN_PROGRESS`, or `ON_HOLD`; if any such active
    request exists the cancellation is rejected with `ERR_CYCLE_HAS_ACTIVE_REQUESTS`
    (HTTP 409)."

    Design: Corner/state_machines/membership_cancel_blocked_by_active_request
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    intake_request(ctx, category="ERRAND", title="t")  # leaves a SUBMITTED request
    resp = api.cancel_membership(ctx["ms_id"], AM)
    validate_error(resp, ApiErrorId.ERR_CYCLE_HAS_ACTIVE_REQUESTS.value)


# ─── Corner/consistency model/membership_supersede_immediate_visibility ─────
def test_supersede_cancels_prior_membership_immediately(api):
    """PRD §3.2: "If the member already held an `ACTIVE` membership, that prior membership
    is superseded — the `System` actor transitions it from `ACTIVE` to `CANCELLED` and
    sets its `OPEN` cycle to `CLOSED` — and the member's `version` is incremented."

    Design: Corner/consistency model/membership_supersede_immediate_visibility
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    ms1_id = ctx["ms_id"]
    # Read the member's current version, then create a superseding membership.
    member = validate_success(api.get_member(ctx["member_id"], AM))
    resp = api.create_membership(
        ctx["member_id"],
        create_membership_payload(ctx["plan_id"], expected_member_version=member["version"], vip_tier="GOLD"),
        AM,
    )
    ms2 = validate_success(resp, expected_status=201)
    ms1 = validate_success(api.get_membership(ms1_id, AM))
    assert ms1["status"] == "CANCELLED", f"expected prior CANCELLED, got {ms1['status']}"
    assert ms2["status"] == "ACTIVE", f"expected new ACTIVE, got {ms2['status']}"


# ─── Corner/endpoints/standing_request_generate_creates_occurrence ──────────
def test_generate_standing_request_creates_occurrence(api):
    """PRD §3.4: "The owning `Member` generates an occurrence, which creates a new
    `ServiceRequest` in `SUBMITTED` status whose `recurrence_parent_id` points back to the
    template and which copies the template's `category`, `rush`, and `estimated_minutes`;
    the caller may override the `title`."

    Design: Corner/endpoints/standing_request_generate_creates_occurrence
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    tpl = intake_request(ctx, category="ERRAND", title="weekly groceries",
                         is_standing=True, cadence="WEEKLY")
    resp = api.generate_service_request(tpl["id"], {}, ctx["member_headers"])
    occ = validate_success(resp, expected_status=201)
    assert occ["recurrence_parent_id"] == tpl["id"], f"expected parent {tpl['id']}, got {occ['recurrence_parent_id']}"
    assert occ["status"] == "SUBMITTED", f"expected SUBMITTED, got {occ['status']}"
    assert occ["category"] == "ERRAND", f"expected ERRAND, got {occ['category']}"
