"""Settlement lifecycle: state guards, dispute/reissue loop, provisional vs
final maintenance basis, issue gating on lease state, creation guards."""
from test_helpers import (
    validate_success, validate_error, api_client, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, make_driver_headers,
    create_active_lease, set_clock, create_settlement, create_and_issue_settlement,
    create_service_bay, create_work_order, complete_work_order,
    assert_settlement_funds_conservation,
    create_settlement_payload, create_lease_payload,
)

ADMIN = TEST_USERS["lease_admin_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


# ─── Queue B: corner/state_machines + corner/validations ──

def test_settlement_finalize_from_draft_rejected(api):
    """PRD section 3.4: "A `SettlementClerk` finalizes an `ISSUED` statement
    (wrong state: `ERR_SETTLEMENT_NOT_FINALIZABLE`; lease not
    `ACTIVE`/`DEFAULTED`: `ERR_LEASE_NOT_ACTIVE`)."

    Design: Corner/state_machines/settlement_finalize_from_draft_rejected
    """
    scenario = create_active_lease()
    set_clock("2026-08-12T00:00:00Z")
    st = create_settlement(scenario["lease"]["id"], "2026-08-03")
    assert st["status"] == "DRAFT"

    res = api.finalize_settlement(st["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_SETTLEMENT_NOT_FINALIZABLE.value)

    after = validate_success(api.get_settlement(st["id"], CLERK), 200)
    assert after["status"] == "DRAFT", "rejected finalize leaves the DRAFT unchanged"


def test_settlement_dispute_from_draft_rejected(api):
    """PRD section 3.4: "a `Driver` whose identity matches the lease's operator
    may dispute an `ISSUED` statement, moving `ISSUED` → `DISPUTED` (wrong state:
    `ERR_SETTLEMENT_NOT_ISSUED`; wrong operator: `ERR_RESOURCE_NOT_OWNED`)."

    Design: Corner/state_machines/settlement_dispute_from_draft_rejected
    """
    scenario = create_active_lease()
    set_clock("2026-08-12T00:00:00Z")
    st = create_settlement(scenario["lease"]["id"], "2026-08-03")

    res = api.dispute_settlement(
        st["id"], make_driver_headers(scenario["operator"]["id"]))
    validate_error(res, ApiErrorId.ERR_SETTLEMENT_NOT_ISSUED.value)

    after = validate_success(api.get_settlement(st["id"], CLERK), 200)
    assert after["status"] == "DRAFT"


def test_settlement_and_lease_residual_state_guards(api):
    """PRD section 3.4: "From `DRAFT`, a `SettlementClerk` issues the statement —
    `DRAFT` → `ISSUED` — provided the lease is `ACTIVE` or `DEFAULTED` (issuing a
    non-draft fails with `ERR_SETTLEMENT_NOT_DRAFT`; a wrong lease state fails
    with `ERR_LEASE_NOT_ACTIVE`)." PRD section 3.4:
    "(reissuing anything not `DISPUTED` fails with `ERR_SETTLEMENT_NOT_DISPUTED`)".
    PRD section 3.3: "the truck must be `AVAILABLE` with no other non-terminal
    lease attached, or the create fails with `ERR_TRUCK_NOT_AVAILABLE`."

    Design: Corner/state_machines/settlement_and_lease_residual_state_guards
    """
    scenario = create_active_lease()
    set_clock("2026-08-12T00:00:00Z")
    st = create_and_issue_settlement(scenario["lease"]["id"], "2026-08-03")
    assert st["status"] == "ISSUED"

    res1 = api.issue_settlement(st["id"], CLERK)
    validate_error(res1, ApiErrorId.ERR_SETTLEMENT_NOT_DRAFT.value)

    res2 = api.reissue_settlement(
        st["id"], {"maintenance_deduction_override_cents": 10000, "reason": "premature"}, CLERK)
    validate_error(res2, ApiErrorId.ERR_SETTLEMENT_NOT_DISPUTED.value)

    res3 = api.create_lease_agreement(
        create_lease_payload(scenario["operator"]["id"], scenario["truck"]["id"]), ADMIN)
    validate_error(res3, ApiErrorId.ERR_TRUCK_NOT_AVAILABLE.value)

    after = validate_success(api.get_settlement(st["id"], CLERK), 200)
    assert after["status"] == "ISSUED", "both rejected actions leave the statement ISSUED"


def test_settlement_week_temporal_guards(api):
    """PRD section 3.4: "the week must lie inside the lease term — from
    `start_date` up to but not including the term-end instant — or the create
    fails with `ERR_WEEK_OUT_OF_TERM`; and the week must be closed, meaning the
    current logical clock has reached `week_start_date` plus seven days, failing
    with `ERR_SETTLEMENT_WEEK_NOT_CLOSED` otherwise."

    Design: Corner/validations/settlement_week_temporal_guards
    """
    scenario = create_active_lease(doc_expires_on="2028-08-01")
    lease_id = scenario["lease"]["id"]
    set_clock("2026-08-19T00:00:00Z")

    # Week 2026-08-24 closes 2026-08-31, after the clock: not yet closed.
    res1 = api.create_settlement(
        create_settlement_payload(lease_id, "2026-08-24", gross_revenue_cents=100000,
                                  fuel_gallons=0, insurance_weekly_cents=0,
                                  miles_driven=0, load_declined_flag=False), CLERK)
    validate_error(res1, ApiErrorId.ERR_SETTLEMENT_WEEK_NOT_CLOSED.value)

    # Week 2027-08-10 is closed but past the term end 2027-08-02.
    set_clock("2027-08-17T00:00:00Z")
    res2 = api.create_settlement(
        create_settlement_payload(lease_id, "2027-08-10", gross_revenue_cents=100000,
                                  fuel_gallons=0, insurance_weekly_cents=0,
                                  miles_driven=0, load_declined_flag=False), CLERK)
    validate_error(res2, ApiErrorId.ERR_WEEK_OUT_OF_TERM.value)


def test_duplicate_week_settlement_returns_409(api):
    """PRD section 3.4: "One settlement may exist per lease per week: a second
    create for the same `(lease_id, week_start_date)` pair is rejected with
    `ERR_DUPLICATE_WEEK_SETTLEMENT`."

    Design: Corner/validations/duplicate_week_settlement_returns_409
    """
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]
    set_clock("2026-08-12T00:00:00Z")
    create_settlement(lease_id, "2026-08-03", gross_revenue_cents=100000,
                      fuel_gallons=0, insurance_weekly_cents=0,
                      miles_driven=0, load_declined_flag=False)

    res = api.create_settlement(
        create_settlement_payload(lease_id, "2026-08-03", gross_revenue_cents=200000,
                                  fuel_gallons=0, insurance_weekly_cents=0,
                                  miles_driven=0, load_declined_flag=False), CLERK)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_WEEK_SETTLEMENT.value)


def test_settlement_create_nonexistent_lease_returns_404(api):
    """PRD section 2.8: "Third, existence of path identifiers and body
    foreign-key references, validated left-to-right — path first, then body —
    yielding the appropriate `ERR_{RESOURCE}_NOT_FOUND`."

    Design: Corner/validations/settlement_create_nonexistent_lease_returns_404
    """
    res = api.create_settlement(
        create_settlement_payload(NON_EXISTENT_UUID, "2026-08-03",
                                  gross_revenue_cents=100000, fuel_gallons=0,
                                  insurance_weekly_cents=0, miles_driven=0,
                                  load_declined_flag=False), CLERK)
    validate_error(res, ApiErrorId.ERR_LEASE_NOT_FOUND.value)


# ─── Queue A: difficulty/non_linear_state_machine ────

def _issued_w1_settlement(scenario):
    set_clock("2026-08-12T00:00:00Z")
    return create_and_issue_settlement(scenario["lease"]["id"], "2026-08-03")


def test_settlement_dispute_reissue_cycle_applies_override(api):
    """PRD section 3.4: "reissuing a `DISPUTED` statement accepts a
    `maintenance_deduction_override_cents` value and an optional `reason`,
    substitutes the override for the maintenance line, recomputes the waterfall
    (escrow, lease payment, net pay, short flag) on the provisional basis with
    that override, and returns the statement to `ISSUED`".

    Design: Difficulty/non_linear_state_machine/settlement_dispute_reissue_cycle
    """
    scenario = create_active_lease()
    st = _issued_w1_settlement(scenario)
    assert st["maintenance_deduction_cents"] == 31250

    disputed = validate_success(api.dispute_settlement(
        st["id"], make_driver_headers(scenario["operator"]["id"])), 200)
    assert disputed["status"] == "DISPUTED"

    reissued = validate_success(api.reissue_settlement(
        st["id"], {"maintenance_deduction_override_cents": 25000, "reason": "shop credit"},
        CLERK), 200)
    assert reissued["status"] == "ISSUED", "dispute loop closes back at ISSUED"
    assert reissued["maintenance_deduction_cents"] == 25000, "clerk override substituted"
    # 250000 - 70000 fuel - 22000 insurance - 25000 maint - 20000 escrow - 65000 lease
    assert reissued["net_pay_cents"] == 48000


def test_settlement_finalize_after_reissue_uses_final_basis(api):
    """PRD section 3.4: "At finalize, `maintenance_deduction_cents` is recomputed
    on the final basis: the sum of `actual_cost_cents` across this lease's work
    orders that are `COMPLETED`, billed to the operator, and whose `completed_at`
    falls within the half-open week from `week_start_date` to `week_start_date`
    plus seven days. For identical inputs the two bases generally differ — a
    reserve accrual versus actual billed work."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_reissue_cycle
    """
    scenario = create_active_lease()
    st = _issued_w1_settlement(scenario)
    validate_success(api.dispute_settlement(
        st["id"], make_driver_headers(scenario["operator"]["id"])), 200)
    validate_success(api.reissue_settlement(
        st["id"], {"maintenance_deduction_override_cents": 25000, "reason": "shop credit"},
        CLERK), 200)

    finalized = validate_success(api.finalize_settlement(st["id"], CLERK), 200)
    assert finalized["maintenance_deduction_cents"] == 0, (
        "final basis: no COMPLETED operator-billed work orders in the week")
    # 250000 - 70000 - 22000 - 0 - 20000 - 65000
    assert finalized["net_pay_cents"] == 73000
    assert finalized["status"] == "FINALIZED"


# ─── Queue A: difficulty/compensating_invariant ──────

def test_settlement_funds_conservation_on_issue(api):
    """PRD section 3.4: "The waterfall then allocates the settlement's funds —
    gross revenue plus any guarantee top-up — through five ordered steps, each
    capped by what remains". PRD section 3.4: "Whatever survives step five is the
    operator's `net_pay_cents`, never below zero."

    Design: Difficulty/compensating_invariant/settlement_funds_conservation_across_reissue
    """
    scenario = create_active_lease()
    st = _issued_w1_settlement(scenario)
    assert st["maintenance_deduction_cents"] == 31250
    assert st["net_pay_cents"] == 41750
    # 250000 + 0 == 41750 + 70000 + 22000 + 31250 + 20000 + 65000
    assert_settlement_funds_conservation(st)


def test_settlement_funds_conservation_across_reissue(api):
    """PRD section 3.4: "reissuing a `DISPUTED` statement accepts a
    `maintenance_deduction_override_cents` value and an optional `reason`,
    substitutes the override for the maintenance line, recomputes the waterfall
    (escrow, lease payment, net pay, short flag) on the provisional basis with
    that override, and returns the statement to `ISSUED`".

    Design: Difficulty/compensating_invariant/settlement_funds_conservation_across_reissue
    """
    scenario = create_active_lease()
    st = _issued_w1_settlement(scenario)
    validate_success(api.dispute_settlement(
        st["id"], make_driver_headers(scenario["operator"]["id"])), 200)
    reissued = validate_success(api.reissue_settlement(
        st["id"], {"maintenance_deduction_override_cents": 10000, "reason": "warranty credit"},
        CLERK), 200)

    assert reissued["maintenance_deduction_cents"] == 10000
    assert reissued["net_pay_cents"] == 63000
    # 250000 + 0 == 63000 + 70000 + 22000 + 10000 + 20000 + 65000 (no drift)
    assert_settlement_funds_conservation(reissued)
    assert reissued["gross_revenue_cents"] == 250000, "compensation never rewrites gross"


# ─── Queue A: difficulty/dual_variant_calc ───────────

def _scenario_with_operator_billed_work_order():
    """ACTIVE lease with one REPAIR work order completed inside W1
    (2026-08-05) at actual cost 45000; odometer past the warranty mileage
    limit, so the work bills to the operator."""
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]
    bay = create_service_bay()
    wo = create_work_order(
        lease_id, bay["id"], category="REPAIR", description="Turbo actuator",
        scheduled_start="2026-08-04T08:00:00Z", scheduled_end="2026-08-04T10:00:00Z",
        estimated_cost_cents=40000)
    set_clock("2026-08-05T09:00:00Z")
    complete_work_order(wo["id"], actual_cost_cents=45000, odometer_at_service=120000)
    set_clock("2026-08-12T00:00:00Z")
    return scenario


def test_settlement_provisional_maintenance_basis(api):
    """PRD section 3.4: "`maintenance_deduction_cents` on the provisional basis
    is a reserve accrual: `miles_driven` multiplied by 12.5 cents per mile,
    rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/settlement_maintenance_provisional_vs_final
    """
    scenario = _scenario_with_operator_billed_work_order()
    st = create_and_issue_settlement(scenario["lease"]["id"], "2026-08-03")
    assert st["maintenance_deduction_cents"] == 31250, (
        "provisional basis: round_half_up(2500 * 12.5)")
    # 250000 - 70000 - 22000 - 31250 - 20000 - 65000
    assert st["net_pay_cents"] == 41750


def test_settlement_final_maintenance_basis_differs(api):
    """PRD section 3.4: "At finalize, `maintenance_deduction_cents` is recomputed
    on the final basis: the sum of `actual_cost_cents` across this lease's work
    orders that are `COMPLETED`, billed to the operator, and whose `completed_at`
    falls within the half-open week from `week_start_date` to `week_start_date`
    plus seven days. For identical inputs the two bases generally differ — a
    reserve accrual versus actual billed work."

    Design: Difficulty/dual_variant_calc/settlement_maintenance_provisional_vs_final
    """
    scenario = _scenario_with_operator_billed_work_order()
    st = create_and_issue_settlement(scenario["lease"]["id"], "2026-08-03")
    provisional_maint = st["maintenance_deduction_cents"]

    finalized = validate_success(api.finalize_settlement(st["id"], CLERK), 200)
    assert finalized["maintenance_deduction_cents"] == 45000, (
        "final basis: the week's COMPLETED operator-billed work order")
    assert finalized["maintenance_deduction_cents"] != provisional_maint, (
        "the two bases diverge for identical inputs")
    # 250000 - 70000 - 22000 - 45000 - 20000 - 65000
    assert finalized["net_pay_cents"] == 28000
    assert finalized["escrow_contribution_cents"] == 20000
    assert finalized["status"] == "FINALIZED"


# ─── Queue A: difficulty/cross_entity_state_dependency ──

def _scenario_with_draft_settlement_then_completed_lease():
    """ACTIVE lease with a W1 settlement left in DRAFT; clock then advanced past
    the term end and the lease completed."""
    scenario = create_active_lease(doc_expires_on="2028-08-01")
    set_clock("2026-08-12T00:00:00Z")
    st = create_settlement(scenario["lease"]["id"], "2026-08-03")
    set_clock("2027-08-03T00:00:00Z")
    validate_success(api_client.complete_lease(scenario["lease"]["id"], ADMIN), 200)
    return scenario, st


def test_issue_rejected_after_lease_completed(api):
    """PRD section 3.4: "From `DRAFT`, a `SettlementClerk` issues the statement —
    `DRAFT` → `ISSUED` — provided the lease is `ACTIVE` or `DEFAULTED` (issuing a
    non-draft fails with `ERR_SETTLEMENT_NOT_DRAFT`; a wrong lease state fails
    with `ERR_LEASE_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/issue_requires_lease_active_or_defaulted
    """
    scenario, st = _scenario_with_draft_settlement_then_completed_lease()
    res = api.issue_settlement(st["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_LEASE_NOT_ACTIVE.value)


def test_draft_settlement_survives_lease_completion(api):
    """PRD section 3.4: "Settlement end-states are `FINALIZED` and `CANCELLED`;
    the latter arrives only through lease termination, which sweeps every
    `DRAFT`, `ISSUED`, or `DISPUTED` statement of the lease into `CANCELLED`."

    Design: Difficulty/cross_entity_state_dependency/issue_requires_lease_active_or_defaulted
    """
    scenario, st = _scenario_with_draft_settlement_then_completed_lease()
    lease = validate_success(api.get_lease_agreement(scenario["lease"]["id"], ADMIN), 200)
    assert lease["status"] == "COMPLETED"

    after = validate_success(api.get_settlement(st["id"], CLERK), 200)
    assert after["status"] == "DRAFT", "completion does not cancel drafts; only termination does"
