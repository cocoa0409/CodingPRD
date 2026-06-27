"""Second, distinct test per difficulty-design instance.

Each test below attacks the same PRD rule as its sibling in test_01..test_03 but
from a different concrete angle (the other boundary side, a different tier/branch,
a different conserved amount, or the positive control), so every non-skipped
difficulty instance carries >= 2 tests.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    setup_active_rental_contract,
    setup_active_system,
    setup_account_with_accepted_test,
    setup_triaged_claim,
    setup_planned_route_with_active_system,
    set_clock,
    create_system_payload,
    create_route_payload,
    create_route_stop_payload,
)

BILLING = TEST_USERS["billing_clerk_headers"]
SM = TEST_USERS["service_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# dual_variant_calc / proration_full_cycle_vs_daily — different window
# ===========================================================================
def test_proration_full_vs_daily_diverge_on_15_day_window(api):
    """PRD §3.10: "For a `RENTAL_CYCLE` invoice the amount is the flat
    `monthly_rate_cents` for a whole month, regardless of partial occupancy."
    PRD §3.10: "For a `PRORATION` invoice the amount is a daily rate times the
    billable days, where the daily rate is the `monthly_rate_cents` divided by 30
    days per billing month, rounded half up to whole cents first, and only then
    multiplied by the billable-day count — the rounding happens before the
    multiplication, never after."

    Design: Difficulty/dual_variant_calc/proration_full_cycle_vs_daily_on_rental_contract
    """
    ctx = setup_active_rental_contract(monthly_rate_cents=4500, term_months=12,
                                       start_date="2026-06-01T00:00:00Z")
    set_clock("2026-07-05T00:00:00Z", BILLING)
    full = validate_success(api.create_invoice({
        "account_id": ctx["account"]["id"], "contract_id": ctx["contract"]["id"],
        "invoice_kind": "RENTAL_CYCLE",
        "period_start": "2026-06-01T00:00:00Z", "period_end": "2026-06-16T00:00:00Z"}, BILLING), 201)
    pro = validate_success(api.create_invoice({
        "account_id": ctx["account"]["id"], "contract_id": ctx["contract"]["id"],
        "invoice_kind": "PRORATION",
        "period_start": "2026-06-01T00:00:00Z", "period_end": "2026-06-16T00:00:00Z"}, BILLING), 201)
    assert full["amount_cents"] == 4500
    assert pro["amount_cents"] == 2250, f"15 days * 150c/day = 2250, got {pro['amount_cents']}"
    assert full["amount_cents"] != pro["amount_cents"]


# ===========================================================================
# dual_variant_calc / claim_settlement — different defect-class pair
# ===========================================================================
def test_claim_settlement_covered_leak_vs_oow_uv_ballast(api):
    """PRD §3.9: "when the claim is covered the settlement is 0 regardless of defect
    class; when it is not covered the customer pays the parts-plus-labor cost reduced
    by an age-based goodwill discount."
    PRD §3.9: "The goodwill discount grows with system age: it is 5 percent for each
    full 365 days between the system's `install_date` and now, capped at 30 percent."

    Design: Difficulty/dual_variant_calc/claim_settlement_covered_vs_out_of_warranty_on_warrantyclaim
    """
    # Covered LEAK (window 1825) on a fresh system.
    covered = setup_triaged_claim(defect_class="LEAK", install_at="2026-01-01T00:00:00Z",
                                  reported_at="2026-06-01T00:00:00Z", triage_at="2026-06-01T00:00:00Z")
    assert covered["claim"]["covered"] is True
    cov = validate_success(api.resolve_warranty_claim(covered["claim"]["id"], {"resolution": "REPAIR"}, SM), 200)
    assert cov["settlement_cents"] == 0

    # Out-of-warranty UV_BALLAST (window 365) on a 2-year-old system.
    # age 882d -> floor(882/365)=2 steps -> 10% goodwill; (9000+9000)*0.9 = 16200.
    oow = setup_triaged_claim(defect_class="UV_BALLAST", install_at="2024-01-01T00:00:00Z",
                              reported_at="2026-06-01T00:00:00Z", triage_at="2026-06-01T00:00:00Z")
    assert oow["claim"]["covered"] is False
    oow_r = validate_success(api.resolve_warranty_claim(oow["claim"]["id"], {"resolution": "REPAIR"}, SM), 200)
    assert oow_r["settlement_cents"] == 16200, f"(9000+9000)*0.9=16200, got {oow_r['settlement_cents']}"


# ===========================================================================
# combinatorial_formula / proration mode_b — different rate exposes rounding
# ===========================================================================
def test_proration_rounds_first_with_fractional_daily_rate(api):
    """PRD §3.10: "the daily rate is the `monthly_rate_cents` divided by 30 days per
    billing month, rounded half up to whole cents first, and only then multiplied by
    the billable-day count — the rounding happens before the multiplication, never
    after."

    Design: Difficulty/combinatorial_formula/proration_round_then_multiply_order_mode_b
    """
    ctx = setup_active_rental_contract(monthly_rate_cents=3001, term_months=12,
                                       start_date="2026-06-13T00:00:00Z")
    set_clock("2026-07-05T00:00:00Z", BILLING)
    pro = validate_success(api.create_invoice({
        "account_id": ctx["account"]["id"], "contract_id": ctx["contract"]["id"],
        "invoice_kind": "PRORATION",
        "period_start": "2026-06-13T00:00:00Z", "period_end": "2026-07-01T00:00:00Z"}, BILLING), 201)
    # round_half_up(3001/30)=100; 100*18=1800 (multiply-then-round 3001/30*18=1800.6 -> 1801).
    assert pro["amount_cents"] == 1800, f"round-first -> 1800, got {pro['amount_cents']}"


# ===========================================================================
# combinatorial_formula / ETF tiered — tier2 rate 0.6
# ===========================================================================
def test_early_termination_fee_tier2_rate(api):
    """PRD §3.8: "if they are more than 3 but 6 or fewer the rate is 0.6 ... The raw
    fee is the months remaining multiplied by `monthly_rate_cents` multiplied by that
    rate; the stored `early_termination_fee_cents` is that raw amount rounded half up
    to whole cents and then capped at 50000 cents, with the cap applied after
    rounding."

    Design: Difficulty/combinatorial_formula/early_termination_fee_tiered_rate_with_cap_mode_a
    """
    ctx = setup_active_rental_contract(monthly_rate_cents=4500, term_months=12,
                                       start_date="2026-01-01T00:00:00Z")
    set_clock("2026-07-01T00:00:00Z", BILLING)  # 181 days -> 6 elapsed -> 6 remaining
    rc_v = get_success_data(api.get_rental_contract(ctx["contract"]["id"], BILLING))["version"]
    result = validate_success(api.terminate_rental_contract(
        ctx["contract"]["id"], {"expected_rentalcontract_version": rc_v}, BILLING), 200)
    # 6 remaining (>3 and <=6 -> tier2 0.6): 6*4500*0.6 = 16200.
    assert result["early_termination_fee_cents"] == 16200, \
        f"6*4500*0.6=16200, got {result['early_termination_fee_cents']}"


# ===========================================================================
# non_linear_state_machine / cyclic contract — single toggle returns to ACTIVE
# ===========================================================================
def test_rental_contract_single_suspend_resume_returns_active(api):
    """PRD §3.8: "A `BillingClerk` may resume a `SUSPENDED` contract back to
    `ACTIVE`, but only when the account's `standing` is `GOOD`; resumption restores
    accrual. This active-suspended cycle may repeat any number of times. Each suspend
    and each resume bumps the contract's `version`."

    Design: Difficulty/non_linear_state_machine/rental_contract_cyclic_active_suspended
    """
    ctx = setup_active_rental_contract()
    rc_id = ctx["contract"]["id"]
    get_success_data(api.suspend_rental_contract(rc_id, BILLING))
    resumed = validate_success(api.resume_rental_contract(rc_id, BILLING), 200)
    assert resumed["status"] == "ACTIVE"
    assert resumed["version"] == 3, f"v1 + suspend + resume -> v3, got {resumed['version']}"


# ===========================================================================
# non_linear_state_machine / fork-join — REPAIR branch reaches CLOSED
# ===========================================================================
def test_warranty_claim_repair_branch_reaches_closed(api):
    """PRD §3.9: "Resolving to `REPAIR` moves a `TRIAGED` claim to `REPAIR`."
    PRD §3.9: "Closing a claim moves it from either `REPAIR` or `REPLACE` to
    `CLOSED`."

    Design: Difficulty/non_linear_state_machine/warranty_claim_branching_fork_join
    """
    ctx = setup_triaged_claim(defect_class="RESIN_FOULING", install_at="2026-01-01T00:00:00Z",
                              reported_at="2026-06-01T00:00:00Z", triage_at="2026-06-01T00:00:00Z")
    assert ctx["claim"]["covered"] is True
    resolved = validate_success(api.resolve_warranty_claim(ctx["claim"]["id"], {"resolution": "REPAIR"}, SM), 200)
    assert resolved["status"] == "REPAIR"
    closed = validate_success(api.close_warranty_claim(ctx["claim"]["id"], SM), 200)
    assert closed["status"] == "CLOSED"
    assert closed["settlement_cents"] == 0


# ===========================================================================
# transitive_cascade / terminate depth-3 — credit exceeds fee
# ===========================================================================
def test_terminate_fee_debits_only_up_to_fee_when_credit_exceeds(api):
    """PRD §3.8: "When the computed fee is greater than 0, termination creates a
    termination invoice for that amount, and that invoice debits the account's
    `credit_balance_cents` ledger — termination to fee invoice to ledger debit is a
    three-level cascade."
    PRD §3.10: "The amount applied is the smaller of the invoice's `amount_cents` and
    the account's `credit_balance_cents` before the debit; the ledger is reduced by
    that applied amount."

    Design: Difficulty/transitive_cascade/terminate_to_fee_invoice_to_ledger_debit_depth3
    """
    ctx = setup_active_rental_contract(monthly_rate_cents=4500, term_months=12,
                                       start_date="2026-01-01T00:00:00Z")
    get_success_data(api.credit_account(ctx["account"]["id"], {"amount_cents": 20000}, BILLING))
    set_clock("2026-03-02T00:00:00Z", BILLING)  # 10 remaining -> fee 18000
    rc_v = get_success_data(api.get_rental_contract(ctx["contract"]["id"], BILLING))["version"]
    result = validate_success(api.terminate_rental_contract(
        ctx["contract"]["id"], {"expected_rentalcontract_version": rc_v}, BILLING), 200)
    assert result["early_termination_fee_cents"] == 18000
    acct = validate_success(api.get_account(ctx["account"]["id"], SM), 200)
    assert acct["credit_balance_cents"] == 2000, "20000 - applied 18000 = 2000"


# ===========================================================================
# transitive_cascade / route complete skips depth-2 — two straggler stops
# ===========================================================================
def test_route_complete_skips_multiple_scheduled_stops(api):
    """PRD §3.4: "Completing a route advances it from `DISPATCHED` to `COMPLETED` and
    force-skips any straggler stops: every `RouteStop` still in `SCHEDULED`
    transitions to `SKIPPED` as a cascade, and a skipped stop fires no service side
    effects."

    Design: Difficulty/transitive_cascade/route_complete_skips_scheduled_stops_depth2
    """
    # Plan a route with two SCHEDULED stops (two different systems to avoid the
    # 24h same-system service gap), dispatch, then complete and confirm BOTH skip.
    ctx = setup_planned_route_with_active_system(capacity_stops=4)
    route_id = ctx["route"]["id"]
    stop1 = get_success_data(api.add_route_stop(route_id, create_route_stop_payload(
        ctx["system"]["id"], stop_type="INSPECTION",
        window_start="2026-06-01T09:00:00Z", window_end="2026-06-01T10:00:00Z"), DISPATCHER))
    sys2 = _second_active_system_same_account(api, ctx)
    stop2 = get_success_data(api.add_route_stop(route_id, create_route_stop_payload(
        sys2["id"], stop_type="INSPECTION",
        window_start="2026-06-01T11:00:00Z", window_end="2026-06-01T12:00:00Z"), DISPATCHER))
    get_success_data(api.dispatch_route(route_id, DISPATCHER))

    completed = validate_success(api.complete_route(route_id, ctx["tech_headers"]), 200)
    assert completed["status"] == "COMPLETED"
    assert validate_success(api.get_route_stop(stop1["id"], SM), 200)["status"] == "SKIPPED"
    assert validate_success(api.get_route_stop(stop2["id"], SM), 200)["status"] == "SKIPPED"


# ===========================================================================
# priority_pair / install state beats capacity — INSTALLED re-install
# ===========================================================================
def test_reinstall_installed_system_returns_invalid_state(api):
    """PRD §2.6: "then — for state-changing operations — whether the target resource
    is in a legal state for the transition (`ERR_INVALID_STATE`), and only then the
    domain-specific business rules described throughout Section 3."
    PRD §3.3: "Installing the system advances `lifecycle_status` from `ORDERED` to
    `INSTALLED`."

    Design: Difficulty/priority_pair_validation_conflict/install_state_beats_capacity_mismatch
    """
    base = setup_account_with_accepted_test(hardness_gpg=15)  # recommends 32000
    sys = get_success_data(api.create_system(
        create_system_payload(base["account"]["id"], base["water_test"]["id"],
                              acquisition_mode="PURCHASE", grain_capacity=32000), SM))
    get_success_data(api.install_system(sys["id"], base["tech_headers"]))  # now INSTALLED
    # Re-install from INSTALLED: capacity matches, but the transition is undefined.
    resp = api.install_system(sys["id"], base["tech_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# boundary_precision / regen — OVERDUE grace boundary
# ===========================================================================
def test_regen_overdue_at_grace_boundary(api):
    """PRD §3.3: "if `gallons_since_regen` is at least the cycle capacity multiplied
    by the grace factor of 1.25, the health becomes `OVERDUE` ... Each boundary is
    inclusive — reaching the threshold exactly counts as having crossed it."

    Design: Difficulty/boundary_precision_check/regen_due_exactly_at_capacity_gallons_meter_reading
    """
    ctx = setup_active_system(grain_capacity=32000, hardness_gpg=15)  # capacity_gallons 2133
    sys_id, th = ctx["system"]["id"], ctx["tech_headers"]
    # grace threshold = 2133 * 1.25 = 2666.25; 2666 < threshold stays DUE, 2667 >= -> OVERDUE.
    below = validate_success(api.meter_reading(sys_id, {"gallons_since_regen": 2666}, th), 200)
    assert below["regen_health"] == "DUE", "2666 < 2666.25 stays DUE"
    at = validate_success(api.meter_reading(sys_id, {"gallons_since_regen": 2667}, th), 200)
    assert at["regen_health"] == "OVERDUE", "2667 >= 2666.25 flips OVERDUE"


# ===========================================================================
# boundary_precision / coverage — just past the window is NOT covered
# ===========================================================================
def test_warranty_not_covered_one_day_past_window(api):
    """PRD §3.9: "the claim's `covered` flag is set true when that age at report is
    at most the window for its defect class, and false otherwise. The boundary is
    inclusive — an age exactly equal to the window is still covered."
    PRD §3.9: "a UV ballast for 365 days."

    Design: Difficulty/boundary_precision_check/warranty_coverage_inclusive_window_boundary_on_triage
    """
    # install 2026-01-01, report 2027-01-02 = 366 days > 365 window.
    ctx = setup_triaged_claim(defect_class="UV_BALLAST", install_at="2026-01-01T00:00:00Z",
                              reported_at="2027-01-02T00:00:00Z", triage_at="2027-01-02T00:00:00Z",
                              acquisition_mode="PURCHASE")
    assert ctx["claim"]["status"] == "TRIAGED"
    assert ctx["claim"]["covered"] is False


# ===========================================================================
# resource_temporal_overlap / half-open — adjacency does NOT overlap
# ===========================================================================
def test_route_stop_adjacent_windows_do_not_overlap(api):
    """PRD §3.4: "`window_end` must be strictly after `window_start`, and the new
    window must not overlap any existing `SCHEDULED` stop already on the same route
    (the overlap check is buffer-aware)."

    Design: Difficulty/resource_temporal_overlap/route_stop_window_half_open_overlap_same_route
    """
    # Use two DIFFERENT systems so the 24h same-system service gap does not fire;
    # adjacency [09:00,10:00) + [10:00,11:00) must be accepted.
    ctx = setup_planned_route_with_active_system(capacity_stops=4)
    route_id = ctx["route"]["id"]
    get_success_data(api.add_route_stop(route_id, create_route_stop_payload(
        ctx["system"]["id"], stop_type="INSPECTION",
        window_start="2026-06-01T09:00:00Z", window_end="2026-06-01T10:00:00Z"), DISPATCHER))

    sys2 = _second_active_system_same_account(api, ctx)
    second = validate_success(api.add_route_stop(route_id, create_route_stop_payload(
        sys2["id"], stop_type="INSPECTION",
        window_start="2026-06-01T10:00:00Z", window_end="2026-06-01T11:00:00Z"), DISPATCHER), 201)
    assert second["status"] == "SCHEDULED"
    route = validate_success(api.get_route(route_id, SM), 200)
    assert route["stop_count"] == 2


# ===========================================================================
# resource_temporal_overlap / service gap — >=24h apart is allowed
# ===========================================================================
def test_same_system_stops_24h_apart_allowed(api):
    """PRD §3.4: "The same system may not be serviced twice in close succession: if
    any two stops servicing the same system — across any route, not just this one —
    would fall within 24 hours of each other, the add is rejected with
    `ERR_SERVICE_GAP_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/same_system_min_service_gap_across_routes
    """
    ctx = setup_planned_route_with_active_system(capacity_stops=4)
    sys_id, tech_id = ctx["system"]["id"], ctx["tech"]["id"]
    get_success_data(api.add_route_stop(ctx["route"]["id"], create_route_stop_payload(
        sys_id, stop_type="INSPECTION",
        window_start="2026-06-01T09:00:00Z", window_end="2026-06-01T10:00:00Z"), DISPATCHER))
    route2 = get_success_data(api.create_route(
        create_route_payload(tech_id, service_zone="Z-NORTH", capacity_stops=4), DISPATCHER))
    # 25 hours after the first stop's window -> outside the 24h gap.
    second = validate_success(api.add_route_stop(route2["id"], create_route_stop_payload(
        sys_id, stop_type="INSPECTION",
        window_start="2026-06-02T11:00:00Z", window_end="2026-06-02T12:00:00Z"), DISPATCHER), 201)
    assert second["status"] == "SCHEDULED"


# ===========================================================================
# compensating_invariant / credit conservation — full applied amount
# ===========================================================================
def test_visit_confirm_void_conserves_credit_full_apply(api):
    """PRD §3.6: "If the visit's `billable_cents` is greater than 0, confirmation
    creates a service-repair invoice that debits the account ledger as a cascade."
    PRD §3.6: "voiding the visit voids that invoice and credits the account ledger
    back, compensating the confirm cascade so the account's credit balance nets back
    to its pre-confirm value."

    Design: Difficulty/compensating_invariant/visit_confirm_void_conserves_account_credit_balance
    """
    ctx = setup_active_system()
    get_success_data(api.credit_account(ctx["account"]["id"], {"amount_cents": 20000}, BILLING))
    visit = get_success_data(api.create_service_visit({
        "system_id": ctx["system"]["id"], "visit_type": "REPAIR",
        "gallons_treated_reading": 0, "billable_cents": 9000}, ctx["tech_headers"]))
    get_success_data(api.confirm_service_visit(visit["id"], ctx["tech_headers"]))
    after_confirm = validate_success(api.get_account(ctx["account"]["id"], SM), 200)
    assert after_confirm["credit_balance_cents"] == 11000, "applied=min(9000,20000)=9000 -> 11000"
    get_success_data(api.void_service_visit(visit["id"], SM))
    after_void = validate_success(api.get_account(ctx["account"]["id"], SM), 200)
    assert after_void["credit_balance_cents"] == 20000, "void credits back exactly 9000"


# ===========================================================================
# compensating_invariant / months_billed conservation — two issues, one void
# ===========================================================================
def test_two_rental_cycles_one_void_leaves_months_billed_one(api):
    """PRD §3.10: "For a `RENTAL_CYCLE` invoice, issuing also increments the
    contract's `months_billed` by 1."
    PRD §3.10: "If the voided invoice was a `RENTAL_CYCLE` invoice, the void also
    decrements the contract's `months_billed` by 1."

    Design: Difficulty/compensating_invariant/rental_invoice_issue_void_conserves_months_billed
    """
    ctx = setup_active_rental_contract(monthly_rate_cents=4500, term_months=12,
                                       start_date="2026-01-01T00:00:00Z")
    acct_id, rc_id = ctx["account"]["id"], ctx["contract"]["id"]
    inv1 = get_success_data(api.create_invoice({
        "account_id": acct_id, "contract_id": rc_id, "invoice_kind": "RENTAL_CYCLE",
        "period_start": "2026-01-01T00:00:00Z", "period_end": "2026-02-01T00:00:00Z"}, BILLING))
    get_success_data(api.create_invoice({
        "account_id": acct_id, "contract_id": rc_id, "invoice_kind": "RENTAL_CYCLE",
        "period_start": "2026-02-01T00:00:00Z", "period_end": "2026-03-01T00:00:00Z"}, BILLING))
    after_two = validate_success(api.get_rental_contract(rc_id, BILLING), 200)
    assert after_two["months_billed"] == 2
    get_success_data(api.void_invoice(inv1["id"], BILLING))
    after_void = validate_success(api.get_rental_contract(rc_id, BILLING), 200)
    assert after_void["months_billed"] == 1


# ===========================================================================
# cross_entity_state_dependency / install requires accepted — positive control
# ===========================================================================
def test_install_succeeds_when_source_test_accepted(api):
    """PRD §3.3: "the source water test must be in `ACCEPTED` status ... On a
    successful install the system's `lifecycle_status` becomes `INSTALLED`, its
    `install_date` is stamped with the current logical-clock instant."

    Design: Difficulty/cross_entity_state_dependency/system_install_requires_accepted_water_test
    """
    base = setup_account_with_accepted_test(hardness_gpg=15)  # test ACCEPTED, recommends 32000
    sys = get_success_data(api.create_system(
        create_system_payload(base["account"]["id"], base["water_test"]["id"],
                              acquisition_mode="PURCHASE", grain_capacity=32000), SM))
    installed = validate_success(api.install_system(sys["id"], base["tech_headers"]), 200)
    assert installed["lifecycle_status"] == "INSTALLED"
    assert installed["install_date"] is not None


# ===========================================================================
# cross_entity_state_dependency / resume requires GOOD — positive control
# ===========================================================================
def test_resume_succeeds_after_paying_past_due_invoice(api):
    """PRD §3.8: "A `BillingClerk` may resume a `SUSPENDED` contract back to
    `ACTIVE`, but only when the account's `standing` is `GOOD`."
    PRD §3.10: "Paying an invoice is permitted from `OPEN` or `PAST_DUE` ... and if
    the account then has no other open or past-due invoice beyond its due window, the
    account's `standing` is restored to `GOOD`."

    Design: Difficulty/cross_entity_state_dependency/contract_resume_requires_account_good_standing
    """
    ctx = setup_active_rental_contract(start_date="2026-01-01T00:00:00Z")
    rc_id, acct_id = ctx["contract"]["id"], ctx["account"]["id"]
    get_success_data(api.suspend_rental_contract(rc_id, BILLING))
    inv = get_success_data(api.create_invoice({
        "account_id": acct_id, "contract_id": rc_id, "invoice_kind": "RENTAL_CYCLE",
        "period_start": "2026-01-01T00:00:00Z", "period_end": "2026-02-01T00:00:00Z",
        "due_offset_days": 30}, BILLING))
    set_clock("2026-03-05T00:00:00Z", BILLING)
    get_success_data(api.evaluate_invoice(inv["id"], BILLING))
    delinquent = validate_success(api.get_account(acct_id, SM), 200)
    assert delinquent["standing"] == "DELINQUENT"

    get_success_data(api.pay_invoice(inv["id"], BILLING))
    good = validate_success(api.get_account(acct_id, SM), 200)
    assert good["standing"] == "GOOD"
    resumed = validate_success(api.resume_rental_contract(rc_id, BILLING), 200)
    assert resumed["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _second_active_system_same_account(api, ctx):
    """Order+install+activate a second system on the same account (same zone)."""
    sys = get_success_data(api.create_system(
        create_system_payload(ctx["account"]["id"], ctx["water_test"]["id"],
                              acquisition_mode="PURCHASE", grain_capacity=32000), SM))
    get_success_data(api.install_system(sys["id"], ctx["tech_headers"]))
    return get_success_data(api.activate_system(sys["id"], ctx["tech_headers"]))
