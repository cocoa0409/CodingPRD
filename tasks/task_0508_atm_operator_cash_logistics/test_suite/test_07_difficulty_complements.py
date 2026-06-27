"""Second, complementary assertions for each high-complexity workflow.

Each test here exercises the same workflow as its counterpart in test_02..test_06, but pins a
different observable (a complementary side, the unchanged-state side of a rejection, or the X+1
side of a boundary), so every high-complexity behavior is covered by more than one assertion.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, TECH_T1,
    make_field_tech_headers,
    provision_network, provision_armed_atm, create_atm, create_cassette,
    approve_fee_disclosure_for_atm, draft_fee_disclosure,
    schedule_order, schedule_and_dispatch_order, confirm_load_order,
    seed_monthly_wd_count, set_clock, post_withdrawal, post_balance_inquiry,
    post_n_withdrawals, create_settlement_run, settle_run,
    get_commission_statement_for_run, settle_atm_window,
    setup_armed_atm_with_withdrawals, setup_resolved_ticket,
    open_ticket, acknowledge_ticket_as,
    read_vault, read_atm, read_order, assert_vault_conservation,
)

VAULT = TEST_USERS["vault_controller_headers"]
TECH = TEST_USERS["field_tech_headers"]
SETTLE = TEST_USERS["settlement_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _dispatch(api, order_id, version):
    return api.dispatch_order(order_id, {"expected_vault_version": version}, headers=VAULT)


# ---- dual_variant_calc: forecast ----

def test_forecast_variants_report_their_basis_and_avg(api):
    """PRD §3.3: "The response reports the rounded `forecast_cents`, the `avg_daily_dispense_cents`
    the variant computed, and the `basis` that was used."

    Design: Difficulty/dual_variant_calc/forecast_forward_vs_chronological_diverge
    """
    net = provision_armed_atm(surcharge_cents=100, jurisdiction_code="CA", note_denomination_cents=2000)
    atm_id = net["atm"]["id"]
    create_cassette(atm_id, position="C1")
    set_clock("2026-01-02T00:00:00Z")
    post_withdrawal(atm_id, amount_cents=1_070_000)
    post_withdrawal(atm_id, amount_cents=1_070_000)
    order = schedule_order(atm_id, net["route"]["id"], order_amount_cents=4_000_000,
                           service_window_start="2026-01-12T08:00:00Z",
                           service_window_end="2026-01-12T10:00:00Z")
    set_clock("2026-01-12T00:00:00Z")
    v = read_vault(net["vault"]["id"])
    validate_success(_dispatch(api, order["id"], v["version"]))
    confirm_load_order(order["id"])
    post_withdrawal(atm_id, amount_cents=660_000)
    set_clock("2026-01-15T00:00:00Z")

    fwd = validate_success(api.get_forecast(
        atm_id, headers=VAULT, params={"basis": "FORWARD", "days_until_next_visit": 7}))
    chrono = validate_success(api.get_forecast(
        atm_id, headers=VAULT, params={"basis": "CHRONOLOGICAL", "days_until_next_visit": 7}))
    assert fwd["basis"] == "FORWARD"
    assert fwd["avg_daily_dispense_cents"] == 200_000
    assert chrono["basis"] == "CHRONOLOGICAL"
    assert chrono["avg_daily_dispense_cents"] == 220_000


# ---- dual_variant_calc: commission basis ----

def test_commission_basis_runs_share_net_revenue(api):
    """PRD §3.10: "The `net_operator_revenue_cents` is therefore the `surcharge_revenue_cents` plus
    the `interchange_revenue_cents` minus the `network_fee_cents`."

    Design: Difficulty/dual_variant_calc/commission_greater_of_vs_pct_only_diverge
    """
    common = {"commission_pct_bps": 1500, "commission_flat_per_wd_cents": 120,
              "commission_monthly_ceiling_cents": 50_000}
    net_g = setup_armed_atm_with_withdrawals(
        surcharge_cents=295, jurisdiction_code="CA", seed_count=498, num_withdrawals=5,
        clock="2026-01-10T00:00:00Z",
        merchant_overrides={**common, "commission_basis": "GREATER_OF"})
    net_p = setup_armed_atm_with_withdrawals(
        surcharge_cents=295, jurisdiction_code="CA", seed_count=498, num_withdrawals=5,
        merchant_overrides={**common, "commission_basis": "PCT_ONLY"})
    settled_g, _ = settle_atm_window(net_g["atm"]["id"])
    settled_p, _ = settle_atm_window(net_p["atm"]["id"])
    assert settled_g["net_operator_revenue_cents"] == 1631
    assert settled_p["net_operator_revenue_cents"] == 1631


# ---- combinatorial_formula: settlement revenue terms ----

def test_settlement_surcharge_and_network_fee_terms(api):
    """PRD §3.10: "The `surcharge_revenue_cents` is the sum of each swept withdrawal's snapshotted
    `surcharge_cents`."
    PRD §3.10: "The `network_fee_cents` is a flat network charge of 8 cents per swept withdrawal —
    that is, 8 cents multiplied by the `withdrawal_count` — and it is subtracted from revenue."

    Design: Difficulty/combinatorial_formula/settlement_tiered_interchange_with_kind_branch
    """
    net = setup_armed_atm_with_withdrawals(
        surcharge_cents=295, jurisdiction_code="CA", seed_count=498, num_withdrawals=5,
        num_balance_inquiries=2, clock="2026-01-10T00:00:00Z")
    settled = settle_run(create_settlement_run(net["atm"]["id"])["id"])
    assert settled["surcharge_revenue_cents"] == 1475   # 5 * 295
    assert settled["network_fee_cents"] == 40           # 8 * 5


# ---- combinatorial_formula: commission eval order (first statement) ----

def test_commission_eval_order_first_statement_under_ceiling(api):
    """PRD §3.11: "The percentage candidate, `pct_amount_cents`, is the `net_operator_revenue_cents`
    multiplied by the merchant's `commission_pct_bps`, divided by 10000, with the fractional part
    discarded (floored)."

    Design: Difficulty/combinatorial_formula/commission_eval_order_pct_then_ceiling
    """
    net = provision_armed_atm(
        surcharge_cents=295, jurisdiction_code="CA",
        merchant_overrides={"commission_pct_bps": 5000, "commission_flat_per_wd_cents": 0,
                            "commission_monthly_ceiling_cents": 200, "commission_basis": "PCT_ONLY"})
    set_clock("2026-01-10T00:00:00Z")
    post_balance_inquiry(net["atm"]["id"])
    post_withdrawal(net["atm"]["id"], amount_cents=2000)
    run1 = create_settlement_run(net["atm"]["id"])
    settle_run(run1["id"])
    stmt1 = get_commission_statement_for_run(run1["id"])
    # net = 295 + 35 - 8 = 322; pct = floor(322 * 0.5) = 161; under ceiling 200.
    assert stmt1["pct_amount_cents"] == 161
    assert stmt1["commission_cents"] == 161


# ---- non_linear_state_machine: reopen cycle (ATM re-fault) ----

def test_service_ticket_reopen_refaults_atm(api):
    """PRD §3.8: "a `RESOLVED` ticket can be **reopened** back to `OPEN`, which increments its
    `reopen_count` by one and re-faults the machine — to `FAULTED` for a minor ticket or
    `OUT_OF_SERVICE` for a major one."

    Design: Difficulty/non_linear_state_machine/service_ticket_reopen_cycle
    """
    atm_id = provision_network(jurisdiction_code="TX")["atm"]["id"]
    atm_id, ticket = setup_resolved_ticket(atm_id=atm_id, fault_kind="CASH_JAM",
                                           severity="MINOR", tech_id=TECH_T1)
    # Before reopen the ATM is back IN_SERVICE.
    assert read_atm(atm_id)["operational_status"] == "IN_SERVICE"
    validate_success(api.reopen_ticket(ticket["id"], headers=make_field_tech_headers(TECH_T1)))
    assert read_atm(atm_id)["operational_status"] == "FAULTED"


# ---- non_linear_state_machine: parallel dimensions (fault survives load) ----

def test_atm_load_does_not_clear_fault(api):
    """PRD §2.5: "a fault never changes the cash dimension nor vice versa."
    PRD §3.6: "Notably, a `FAULTED` machine can still be loaded — only `OUT_OF_SERVICE` blocks it."

    Design: Difficulty/non_linear_state_machine/atm_parallel_dimensions_independent
    """
    net = provision_network(provisioned_cents=100_000_000)
    create_cassette(net["atm"]["id"], position="C1")
    order = schedule_and_dispatch_order(net["atm"]["id"], net["route"]["id"], net["vault"]["id"],
                                        order_amount_cents=200_000)
    open_ticket(net["atm"]["id"], fault_kind="CARD_READER", severity="MINOR")
    validate_success(api.confirm_load(order["id"], headers=TECH))
    atm = read_atm(net["atm"]["id"])
    # The load advanced cash_status but left operational_status FAULTED untouched.
    assert atm["cash_status"] == "LOADED"
    assert atm["operational_status"] == "FAULTED"


# ---- transitive_cascade: close-out (vault leg) ----

def test_closeout_cascade_decrements_vault_in_machine(api):
    """PRD §3.6: "cascades to the cash supply chain: the machine's currently `LOADED` replenishment
    order moves to its terminal `SETTLED` status, and the vault's `in_machine_cents` is reduced by
    that order's `order_amount_cents`."

    Design: Difficulty/transitive_cascade/closeout_cascade_depth3_atm_order_vault
    """
    net = provision_network(provisioned_cents=100_000_000)
    create_cassette(net["atm"]["id"], position="C1")
    order = schedule_and_dispatch_order(net["atm"]["id"], net["route"]["id"], net["vault"]["id"],
                                        order_amount_cents=200_000)
    order = confirm_load_order(order["id"])
    cc = validate_success(api.create_cash_count(net["atm"]["id"], {"counted_cents": 200_000},
                                                headers=TECH), expected_status=201)
    validate_success(api.close_out_cash_count(net["atm"]["id"], cc["id"], headers=TECH))
    vault = read_vault(net["vault"]["id"])
    assert vault["in_machine_cents"] == 0
    # PRD §2.7: balance_cents = provisioned_cents - in_transit_cents - in_machine_cents,
    # and the sum equals provisioned_cents at all times ("conserved forever", "two buckets
    # in equal and opposite amounts"). Close-out empties in_machine, so that cash returns to
    # on-hand balance, restoring it to the full provisioned baseline.
    assert vault["balance_cents"] == 100_000_000
    assert_vault_conservation(vault)


# ---- transitive_cascade: settle (commission cascade) ----

def test_settle_generates_single_accrued_commission_statement(api):
    """PRD §3.11: "Settling a run does not stop at the operator's books — it cascades to generate a
    **commission statement** for the host merchant, born `ACCRUED`."

    Design: Difficulty/transitive_cascade/settle_cascade_depth2_txn_commission
    """
    net = setup_armed_atm_with_withdrawals(
        surcharge_cents=295, jurisdiction_code="CA", seed_count=498, num_withdrawals=5,
        clock="2026-01-10T00:00:00Z")
    run = create_settlement_run(net["atm"]["id"])
    settle_run(run["id"])
    statements = validate_success(api.list_commission_statements(
        headers=SETTLE, params={"settlement_run_id": run["id"]}))
    assert len(statements) == 1
    assert statements[0]["status"] == "ACCRUED"
    assert statements[0]["site_merchant_id"] == net["merchant"]["id"]


# ---- priority_pair: route paused (order unchanged) ----

def test_dispatch_route_paused_leaves_order_scheduled(api):
    """PRD §3.4: "the fulfilling route must be `ACTIVE`, or the dispatch is rejected with
    `ERR_ROUTE_PAUSED`"
    PRD §3.4: "The pivotal action is **dispatch**, performed by a `VaultController`, which advances
    the order from `SCHEDULED` to `DISPATCHED`."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_route_paused_beats_vault_insufficient
    """
    net = provision_network(provisioned_cents=100)
    order = schedule_order(net["atm"]["id"], net["route"]["id"], order_amount_cents=500_000)
    validate_success(api.pause_route(net["route"]["id"], headers=VAULT))
    resp = _dispatch(api, order["id"], net["vault"]["version"])
    validate_error(resp, ApiErrorId.ERR_ROUTE_PAUSED, expected_status=409)
    assert read_order(order["id"])["status"] == "SCHEDULED"  # rejected dispatch did not advance


# ---- priority_pair: invalid state (order stays DISPATCHED) ----

def test_redispatch_leaves_order_dispatched(api):
    """PRD §2.6: "Among those, any attempt to drive an entity through a transition that is not
    defined from its current state — settling a run that is already `SETTLED`, acknowledging a
    ticket that is not `OPEN`, approving a disclosure that is not `DRAFT`, and the like — is
    rejected with `ERR_INVALID_STATE`, the generic guard that backs every state machine
    described below."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_invalid_state_beats_vault_insufficient
    """
    net = provision_network(provisioned_cents=250_000)
    order = schedule_order(net["atm"]["id"], net["route"]["id"], order_amount_cents=200_000)
    validate_success(_dispatch(api, order["id"], net["vault"]["version"]))
    resp = _dispatch(api, order["id"], net["vault"]["version"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert read_order(order["id"])["status"] == "DISPATCHED"


# ---- boundary: interchange tier net revenue ----

def test_interchange_tier_boundary_net_revenue(api):
    """PRD §3.10: "The `net_operator_revenue_cents` is therefore the `surcharge_revenue_cents` plus
    the `interchange_revenue_cents` minus the `network_fee_cents`."

    Design: Difficulty/boundary_precision_check/interchange_tier_boundary_seq_500_vs_501
    """
    net = setup_armed_atm_with_withdrawals(
        surcharge_cents=100, jurisdiction_code="CA", seed_count=499, num_withdrawals=2,
        clock="2026-01-10T00:00:00Z")
    settled = settle_run(create_settlement_run(net["atm"]["id"])["id"])
    # surcharge 2*100=200, interchange 77, network 2*8=16 -> 261.
    assert settled["net_operator_revenue_cents"] == 261


# ---- boundary: cash-count variance one beyond tolerance -> SHORT ----

def test_cash_count_variance_one_beyond_tolerance_is_short(api):
    """PRD §3.6: "`SHORT` when it is strictly less than zero and beyond tolerance."
    PRD §3.6: "the `variance_cents` as the `counted_cents` minus that expected remaining."

    Design: Difficulty/boundary_precision_check/cash_count_variance_at_tolerance_boundary
    """
    net = provision_armed_atm(surcharge_cents=100, jurisdiction_code="CA", note_denomination_cents=2000)
    create_cassette(net["atm"]["id"], position="C1")
    order = schedule_and_dispatch_order(net["atm"]["id"], net["route"]["id"], net["vault"]["id"],
                                        order_amount_cents=100_000)
    confirm_load_order(order["id"])
    post_withdrawal(net["atm"]["id"], amount_cents=40_000)  # expected_remaining 60000
    # counted 59499 -> variance -501, |−501| > 500 -> SHORT (one cent past the inclusive boundary).
    cc = validate_success(api.create_cash_count(
        net["atm"]["id"], {"counted_cents": 59_499, "tolerance_cents": 500}, headers=TECH),
        expected_status=201)
    assert cc["variance_cents"] == -501
    assert cc["outcome"] == "SHORT"


# ---- cross_entity_state_dependency: confirm-load OOS (order unchanged) ----

def test_confirm_load_oos_leaves_order_dispatched(api):
    """PRD §3.6: "an attempt to load an out-of-service machine is rejected with
    `ERR_ATM_OUT_OF_SERVICE`."
    PRD §3.6: "Once an order is dispatched and the truck arrives, a `FieldTech` performs
    **confirm-load**, advancing the order from `DISPATCHED` to `LOADED`."

    Design: Difficulty/cross_entity_state_dependency/confirm_load_blocked_by_atm_out_of_service
    """
    net = provision_network(provisioned_cents=100_000_000)
    create_cassette(net["atm"]["id"], position="C1")
    order = schedule_and_dispatch_order(net["atm"]["id"], net["route"]["id"], net["vault"]["id"],
                                        order_amount_cents=200_000)
    open_ticket(net["atm"]["id"], fault_kind="DISPENSER", severity="MAJOR")
    validate_error(api.confirm_load(order["id"], headers=TECH),
                   ApiErrorId.ERR_ATM_OUT_OF_SERVICE, expected_status=409)
    assert read_order(order["id"])["status"] == "DISPATCHED"


# ---- cross_entity_state_dependency: settle gate (approved disclosure succeeds) ----

def test_settle_succeeds_once_disclosure_approved(api):
    """PRD §3.10: "Settlement is gated by two preconditions: the machine must have an approved fee
    disclosure, or settlement is rejected with `ERR_NO_FEE_DISCLOSURE`"
    PRD §3.10: "The officer then **settles** it, moving it from `DRAFT` to its terminal, immutable
    `SETTLED` status."

    Design: Difficulty/cross_entity_state_dependency/settle_blocked_without_approved_fee_disclosure
    """
    net = provision_network(jurisdiction_code="CA", surcharge_cents=100, note_denomination_cents=2000)
    # Approve a matching disclosure -> machine armed; settle now passes the gate.
    approve_fee_disclosure_for_atm(net["atm"]["id"], 100)
    run = create_settlement_run(net["atm"]["id"])
    settled = validate_success(api.settle_run(run["id"], headers=SETTLE))
    assert settled["status"] == "SETTLED"


# ---- resource_temporal_overlap: route window (adjacent allowed) ----

def test_route_window_adjacent_endpoints_allowed(api):
    """PRD §3.5: "Intervals that merely touch — where one order's start equals another's end — do
    not overlap and are permitted; there is no buffer on the route."

    Design: Difficulty/resource_temporal_overlap/route_window_halfopen_overlap_rejected_adjacent_allowed
    """
    net = provision_network(provisioned_cents=100_000_000)
    route_id = net["route"]["id"]
    atm_a = net["atm"]
    atm_c = create_atm(net["location"]["id"], serial_no="SN-ADJ-OK", surcharge_cents=100)
    ro_a = schedule_order(atm_a["id"], route_id, order_amount_cents=200_000,
                          service_window_start="2026-01-05T09:00:00Z",
                          service_window_end="2026-01-05T10:00:00Z")
    validate_success(_dispatch(api, ro_a["id"], read_vault(net["vault"]["id"])["version"]))
    # Adjacent [10:00,11:00) touches ro_a's end exactly -> permitted on the route.
    ro_c = schedule_order(atm_c["id"], route_id, order_amount_cents=200_000,
                          service_window_start="2026-01-05T10:00:00Z",
                          service_window_end="2026-01-05T11:00:00Z")
    data = validate_success(_dispatch(api, ro_c["id"], read_vault(net["vault"]["id"])["version"]))
    assert data["status"] == "DISPATCHED"


# ---- resource_temporal_overlap: ATM lockout (>30min gap allowed) ----

def test_atm_lockout_gap_beyond_buffer_allowed(api):
    """PRD §3.5: "Because of the thirty-minute buffer on each side, two orders whose windows merely
    touch end-to-start do collide, and only a gap strictly greater than thirty minutes between them
    is allowed."

    Design: Difficulty/resource_temporal_overlap/atm_lockout_closed_buffer_overlap_rejected
    """
    net = provision_network(provisioned_cents=100_000_000)
    atm_id = net["atm"]["id"]
    route_id = net["route"]["id"]
    ro_1 = schedule_order(atm_id, route_id, order_amount_cents=200_000,
                          service_window_start="2026-01-05T09:00:00Z",
                          service_window_end="2026-01-05T10:00:00Z")
    validate_success(_dispatch(api, ro_1["id"], net["vault"]["version"]))
    # [10:31,11:00) leaves a 31-minute gap (> 30) on the same ATM -> allowed.
    ro_2 = schedule_order(atm_id, route_id, order_amount_cents=200_000,
                          service_window_start="2026-01-05T10:31:00Z",
                          service_window_end="2026-01-05T11:00:00Z")
    data = validate_success(_dispatch(api, ro_2["id"], read_vault(net["vault"]["id"])["version"]))
    assert data["status"] == "DISPATCHED"


# ---- compensating_invariant: vault recall (order terminal RECALLED) ----

def test_vault_recall_lands_order_in_recalled(api):
    """PRD §3.7: "The machine's `cash_status` reverts from `AWAITING_LOAD` back to `EMPTY` or `LOW`,
    and the order lands in `RECALLED`."

    Design: Difficulty/compensating_invariant/vault_conservation_dispatch_then_recall
    """
    net = provision_network(provisioned_cents=10_000_000)
    order = schedule_and_dispatch_order(net["atm"]["id"], net["route"]["id"], net["vault"]["id"],
                                        order_amount_cents=200_000)
    recalled = validate_success(api.recall_order(order["id"], headers=VAULT))
    assert recalled["status"] == "RECALLED"
    vault = read_vault(net["vault"]["id"])
    assert vault["in_transit_cents"] == 0
    assert_vault_conservation(vault)


# ---- compensating_invariant: ceiling headroom (run1 voided) ----

def test_void_marks_statement_voided(api):
    """PRD §3.11: "Alternatively the officer **voids** an `ACCRUED` statement, moving it to its
    terminal `VOIDED` status"

    Design: Difficulty/compensating_invariant/commission_ceiling_headroom_accrue_then_void
    """
    net = provision_armed_atm(
        surcharge_cents=295, jurisdiction_code="CA",
        merchant_overrides={"commission_pct_bps": 5000, "commission_flat_per_wd_cents": 0,
                            "commission_monthly_ceiling_cents": 200, "commission_basis": "PCT_ONLY"})
    set_clock("2026-01-10T00:00:00Z")
    post_withdrawal(net["atm"]["id"], amount_cents=2000)
    run1 = create_settlement_run(net["atm"]["id"])
    settle_run(run1["id"])
    stmt1 = get_commission_statement_for_run(run1["id"])
    assert stmt1["status"] == "ACCRUED"
    voided = validate_success(api.void_commission_statement(stmt1["id"], headers=SETTLE))
    assert voided["status"] == "VOIDED"
