"""Dual-variant calculations and combinatorial formulas (queue A: Difficulty).

Covers the charge-responsibility estimate/adjudicated split, the provider
primary-vs-coverage load divergence, the risk-tier branch ladder, and the pinned
payment-plan waterfall rounding order.
"""
from test_helpers import (
    api_client, TEST_USERS, validate_success, get_success_data,
    fixtures,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["center_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
MIDWIFE = TEST_USERS["midwife_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ===========================================================================
# dual_variant_calc / dvc_charge_estimate_vs_adjudicated
# ===========================================================================
def test_global_fee_estimate_responsibility_at_create(api):
    """PRD §3.6: "In the estimate variant ... the client responsibility is the gross
    global fee multiplied by the self-pay estimate fraction of 0.20 (that is, twenty
    percent), with the product rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/dvc_charge_estimate_vs_adjudicated
    """
    ctx = fixtures.setup_episode_with_submitted_claim(global_fee_cents=800000)
    ep_id = ctx["episode"]["id"]
    charge = fixtures.get_global_fee_charge(ep_id)
    assert charge["client_responsibility_cents"] == 160000, \
        f"estimate variant = 20% of 800000 = 160000, got {charge['client_responsibility_cents']}"


def test_global_fee_adjudicated_responsibility_after_claim(api):
    """PRD §3.6: "In the adjudicated variant — used once the claim is ADJUDICATED — the
    client responsibility is the claim's allowed_amount_cents minus its paid_amount_cents."
    PRD §3.6: "Adjudication cascades into billing: the episode's global-fee charge's
    client_responsibility_cents is recomputed by the adjudicated variant (the allowed
    amount minus the paid amount), which re-derives the episode's balance_due_cents"

    Design: Difficulty/dual_variant_calc/dvc_charge_estimate_vs_adjudicated
    """
    ctx = fixtures.setup_episode_with_submitted_claim(global_fee_cents=800000)
    ep_id = ctx["episode"]["id"]
    claim_id = ctx["claim"]["id"]

    # Before adjudication: estimate variant.
    charge_before = fixtures.get_global_fee_charge(ep_id)
    assert charge_before["client_responsibility_cents"] == 160000

    validate_success(
        api.adjudicate_claim(claim_id, f.adjudicate_payload(600000, 540000), BILLING)
    )

    charge_after = fixtures.get_global_fee_charge(ep_id)
    assert charge_after["client_responsibility_cents"] == 60000, \
        f"adjudicated = allowed 600000 - paid 540000 = 60000, got {charge_after['client_responsibility_cents']}"

    ep = validate_success(api.get_episode(ep_id, BILLING))
    assert ep["balance_due_cents"] == 60000, \
        f"balance re-derives to 60000, got {ep['balance_due_cents']}"


# ===========================================================================
# dual_variant_calc / dvc_provider_primary_vs_coverage_load
# ===========================================================================
def test_backup_assigned_excluded_from_primary_load(api):
    """PRD §3.4: "A BACKUP row still sitting in ASSIGNED does not count toward primary
    load." PRD §3.4: "Only the primary load is persisted in active_assignment_count and
    only the primary load gates the capacity check."

    Design: Difficulty/dual_variant_calc/dvc_provider_primary_vs_coverage_load
    """
    ctx = fixtures.setup_primary_with_backup(max_active_episodes=2)
    bak_id = ctx["backup_provider"]["id"]
    backup_assignment = ctx["backup_assignment"]

    assert backup_assignment["coverage_role"] == "BACKUP"
    assert backup_assignment["status"] == "ASSIGNED"

    bak = validate_success(api.get_provider(bak_id, ADMIN))
    assert bak["active_assignment_count"] == 0, \
        f"primary load excludes a BACKUP/ASSIGNED row, expected 0, got {bak['active_assignment_count']}"


def test_primary_assigned_counts_toward_primary_load(api):
    """PRD §3.4: "It counts every assignment for the provider that is either a PRIMARY
    row in ASSIGNED or ON_DUTY, or a BACKUP row that has been promoted to PROMOTED"

    Design: Difficulty/dual_variant_calc/dvc_provider_primary_vs_coverage_load
    """
    ctx = fixtures.setup_primary_with_backup(max_active_episodes=2)
    pri_id = ctx["provider"]["id"]

    pri = validate_success(api.get_provider(pri_id, ADMIN))
    assert pri["active_assignment_count"] == 1, \
        f"the PRIMARY/ASSIGNED row counts under primary load, expected 1, got {pri['active_assignment_count']}"


# ===========================================================================
# combinatorial_formula / cf_risk_tier_branching_inputs
# ===========================================================================
def test_single_watch_visit_yields_elevated(api):
    """PRD §3.7: "otherwise if the worst flag is WATCH, the tier is ELEVATED"

    Design: Difficulty/combinatorial_formula/cf_risk_tier_branching_inputs
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    v1 = fixtures.schedule_visit(ep_id, scheduled_at="2026-04-01T10:00:00Z")
    fixtures.complete_visit(v1["id"], risk_flag="WATCH", blood_pressure_systolic=120)

    ep = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert ep["risk_tier"] == "ELEVATED", f"one WATCH (bp 120) -> ELEVATED, got {ep['risk_tier']}"


def test_two_watch_visits_escalate_to_transfer_required(api):
    """PRD §3.7: "otherwise if the worst flag is WATCH and the number of watch-flagged
    visits is at least 2, the tier is TRANSFER_REQUIRED"

    Design: Difficulty/combinatorial_formula/cf_risk_tier_branching_inputs
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    v1 = fixtures.schedule_visit(ep_id, scheduled_at="2026-04-01T10:00:00Z")
    v2 = fixtures.schedule_visit(ep_id, scheduled_at="2026-04-15T10:00:00Z")
    fixtures.complete_visit(v1["id"], risk_flag="WATCH", blood_pressure_systolic=120)
    fixtures.complete_visit(v2["id"], risk_flag="WATCH", blood_pressure_systolic=125)

    ep = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert ep["risk_tier"] == "TRANSFER_REQUIRED", \
        f"two WATCH visits (watch_count==2) -> TRANSFER_REQUIRED, got {ep['risk_tier']}"


# ===========================================================================
# combinatorial_formula / cf_payment_waterfall_rounding_order
# ===========================================================================
def _setup_plan_100003_three_installments(api):
    """Build an episode whose balance is exactly 100003, plan with 3 installments."""
    ctx = fixtures.setup_episode_with_submitted_claim(global_fee_cents=800000)
    ep_id = ctx["episode"]["id"]
    claim_id = ctx["claim"]["id"]
    # Adjudicate the global fee to 100000 (allowed 100000 - paid 0).
    validate_success(api.adjudicate_claim(claim_id, f.adjudicate_payload(100000, 0), BILLING))
    # Add an EXTRA_VISIT of 3 -> balance 100003.
    validate_success(api.create_charge(f.create_charge_payload(ep_id, "EXTRA_VISIT", 3), BILLING),
                     expected_status=201)
    ep = validate_success(api.get_episode(ep_id, BILLING))
    plan = validate_success(
        api.create_payment_plan(f.create_payment_plan_payload(ep_id, 3, ep["version"]), BILLING),
        expected_status=201,
    )
    return ep_id, plan


def test_waterfall_balance_and_plan_total_100003(api):
    """PRD §3.10: "On success the plan opens in OPEN status with its total_cents
    snapshotted from the episode's balance_due_cents"

    Design: Difficulty/combinatorial_formula/cf_payment_waterfall_rounding_order
    """
    ep_id, plan = _setup_plan_100003_three_installments(api)
    ep = validate_success(api.get_episode(ep_id, BILLING))
    assert ep["balance_due_cents"] == 100003, \
        f"after the EXTRA_VISIT charge balance == 100003, got {ep['balance_due_cents']}"
    assert plan["total_cents"] == 100003, f"plan total == 100003, got {plan['total_cents']}"


def test_waterfall_first_installment_covered_by_earliest_remainder(api):
    """PRD §3.10: "the remainder is distributed to the earliest installments first: the
    first however-many installments equal to the remainder each get the base plus one
    cent, and every installment after that gets the base."
    PRD §3.10: "After a payment, the plan's paid_cents increases by the amount applied
    and its remaining_cents becomes total_cents minus paid_cents."

    Design: Difficulty/combinatorial_formula/cf_payment_waterfall_rounding_order
    """
    ep_id, plan = _setup_plan_100003_three_installments(api)
    # Schedule for total 100003 over 3: base=33334, remainder=1 -> [33335, 33334, 33334].
    after = validate_success(
        api.apply_payment(plan["id"], f.payment_payload(33335), BILLING)
    )
    assert after["paid_cents"] == 33335, f"paid_cents == 33335, got {after['paid_cents']}"
    assert after["remaining_cents"] == 66668, \
        f"remaining == 100003 - 33335 == 66668 (remainder on earliest slot), got {after['remaining_cents']}"
    assert after["status"] == "OPEN", f"plan still OPEN, got {after['status']}"
