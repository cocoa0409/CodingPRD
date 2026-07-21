"""Marketing selection, policy binding/activation, coverage overlap, commission math."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_policy_payload,
)
from test_helpers import fixtures as fx

CONSULTANT = TEST_USERS["consultant_headers"]
CARRIER = TEST_USERS["carrier_headers"]


# ===========================================================================
# Corner / state_machines — quote selection cascade
# ===========================================================================
def test_quote_select_cascade_closes_campaign_declines_siblings(api):
    """PRD §3.2: "Selection cascades: the parent campaign advances from OPEN to CLOSED, and
    every sibling quote for that same campaign still in SUBMITTED is moved to DECLINED."

    Design: Corner/state_machines/quote_select_cascade_closes_campaign_declines_siblings
    """
    client = fx.create_client(legal_name="Cascade Co")
    camp = validate_success(api.create_campaign(
        {"client_id": client["id"], "coverage_line": "VISION",
         "target_effective_date": "2026-01-01"}, CONSULTANT), 201)
    validate_success(api.open_campaign(camp["id"], CONSULTANT))
    q1 = validate_success(api.create_quote(
        {"campaign_id": camp["id"], "carrier_name": "Vision A",
         "monthly_premium_cents": 200_000, "commission_rate_pct": 0.03}, CARRIER), 201)
    q2 = validate_success(api.create_quote(
        {"campaign_id": camp["id"], "carrier_name": "Vision B",
         "monthly_premium_cents": 210_000, "commission_rate_pct": 0.03}, CARRIER), 201)
    validate_success(api.select_quote(q1["id"], CONSULTANT))
    assert validate_success(api.get_quote(q1["id"], CONSULTANT))["status"] == "SELECTED"
    assert validate_success(api.get_quote(q2["id"], CONSULTANT))["status"] == "DECLINED"
    assert validate_success(api.get_campaign(camp["id"], CONSULTANT))["status"] == "CLOSED"


# ===========================================================================
# Corner / validations — policy bind
# ===========================================================================
def test_bind_policy_expiration_before_effective_rejected(api):
    """PRD §2.7: "a policy's expiration_date must be strictly after its effective_date".
    PRD §3.3: "an expiration_date (coverage end, inclusive, which must be strictly later
    than the effective date)."

    Design: Corner/validations/bind_policy_expiration_before_effective_rejected
    """
    client = fx.create_client(legal_name="BadDate Co")
    quote = fx.create_selected_quote(client["id"])
    resp = api.create_policy(
        create_policy_payload(client["id"], quote["id"],
                              effective_date="2026-12-31", expiration_date="2026-01-01"),
        CONSULTANT)
    validate_error(resp, ApiErrorId.ERR_INVALID_FIELD.value)


def test_bind_policy_unselected_quote_rejected(api):
    """PRD §3.3: "The bind is rejected with ERR_QUOTE_NOT_SELECTED unless the referenced
    quote is in SELECTED status and belongs to a campaign of the same client."

    Design: Corner/validations/bind_policy_quote_not_selected_rejected
    """
    client = fx.create_client(legal_name="Unsel Co")
    camp = validate_success(api.create_campaign(
        {"client_id": client["id"], "coverage_line": "MEDICAL",
         "target_effective_date": "2026-01-01"}, CONSULTANT), 201)
    validate_success(api.open_campaign(camp["id"], CONSULTANT))
    quote = validate_success(api.create_quote(
        {"campaign_id": camp["id"], "carrier_name": "Acme Health",
         "monthly_premium_cents": 500_000, "commission_rate_pct": 0.04}, CARRIER), 201)
    resp = api.create_policy(
        create_policy_payload(client["id"], quote["id"]), CONSULTANT)
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_SELECTED.value)


# ===========================================================================
# Corner / state_machines — terminate a BOUND policy
# ===========================================================================
def test_terminate_bound_policy_invalid_state(api):
    """PRD §3.3: "Terminating an active policy advances its lifecycle_status from ACTIVE to
    TERMINATED and subtracts that policy's monthly_premium_cents from the client's
    active_premium_total_cents."
    PRD §2.7: "State — the target resource is in a state from which the requested transition
    is defined; otherwise ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/terminate_bound_policy_invalid_state_rejected
    """
    client = fx.create_client(legal_name="Bound Co")
    policy = fx.bind_policy(client["id"])
    resp = api.terminate_policy(policy["id"], CONSULTANT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner / consistency_model — activation ledger update
# ===========================================================================
def test_activate_policy_updates_client_ledger_immediately(api):
    """PRD §3.3: "On successful activation the policy's monthly_premium_cents is added to
    the client's active_premium_total_cents."

    Design: Corner/consistency_model/policy_activate_updates_client_ledger_same_response_cycle
    """
    client = fx.create_client(legal_name="Immediate Co")
    policy = fx.bind_policy(client["id"], monthly_premium_cents=750_000)
    activated = validate_success(api.activate_policy(policy["id"], CONSULTANT))
    assert activated["lifecycle_status"] == "ACTIVE"
    fresh = validate_success(api.get_client(client["id"], CONSULTANT))
    assert fresh["active_premium_total_cents"] == 750_000


# ===========================================================================
# Difficulty / dual_variant_calc — estimated vs finalized commission
# ===========================================================================
def _finalized_medical_policy(api):
    """MEDICAL policy premium 1000000, rate 0.04, effective 2026-01-01, ACTIVE, then
    finalize at default clock 2026-07-01 (6 months elapsed)."""
    client = fx.create_client(legal_name="Alpha Co")
    policy = fx.activate_policy(client["id"], coverage_line="MEDICAL",
                               monthly_premium_cents=1_000_000, commission_rate_pct=0.04,
                               effective_date="2026-01-01", expiration_date="2026-12-31")
    finalized = validate_success(api.finalize_commission(policy["id"], CONSULTANT))
    return finalized


def test_commission_estimated_annualized_with_volume_tier(api):
    """PRD §3.3: "The estimated commission is the base multiplied by the volume multiplier
    and then by the line multiplier, rounded half-up to whole cents."
    PRD §3.3: "A volume multiplier is then chosen by tier: it is 1.10 when the annualized
    premium is at least 12,000,000 cents ($120,000), otherwise 1.05 when the annualized
    premium is at least 6,000,000 cents ($60,000), otherwise 1.00."

    Design: Difficulty/dual_variant_calc/commission_estimated_vs_finalized_on_policy
    """
    finalized = _finalized_medical_policy(api)
    assert finalized["estimated_commission_cents"] == 528_000
    assert finalized["commission_status"] == "FINALIZED"


def test_commission_finalized_chronological_no_volume_tier(api):
    """PRD §3.5: "The finalized_commission_cents is then the policy's current
    monthly_premium_cents multiplied by its commission_rate_pct, multiplied by that
    months-elapsed count, multiplied by the coverage-line multiplier (1.00 for MEDICAL,
    0.90 for DENTAL, 0.85 for VISION, 0.95 for LIFE), rounded half-up to whole cents."
    PRD §3.5: "Unlike the estimate, the finalized figure applies no volume-tier multiplier,
    so the two figures diverge for the same policy."

    Design: Difficulty/dual_variant_calc/commission_estimated_vs_finalized_on_policy
    """
    finalized = _finalized_medical_policy(api)
    assert finalized["finalized_commission_cents"] == 240_000
    assert finalized["estimated_commission_cents"] != finalized["finalized_commission_cents"]


# ===========================================================================
# Difficulty / combinatorial_formula — tiered non-linear estimation
# ===========================================================================
def test_commission_estimation_tier1_dental_multiplicative(api):
    """PRD §3.3: "The estimated commission is the base multiplied by the volume multiplier
    and then by the line multiplier, rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/commission_estimation_tiered_nonlinear_mode_a
    """
    client = fx.create_client(legal_name="Gamma Co", industry="OTHER")
    quote = fx.create_selected_quote(client["id"], coverage_line="DENTAL",
                                    monthly_premium_cents=700_000, commission_rate_pct=0.05)
    policy = validate_success(api.create_policy(
        create_policy_payload(client["id"], quote["id"]), CONSULTANT), 201)
    assert policy["estimated_commission_cents"] == 396_900


def test_commission_estimation_tier1_dental_persisted_on_read(api):
    """PRD §3.3: "A line multiplier is chosen by coverage line: 1.00 for MEDICAL, 0.90 for
    DENTAL, 0.85 for VISION, and 0.95 for LIFE."

    Design: Difficulty/combinatorial_formula/commission_estimation_tiered_nonlinear_mode_a
    """
    client = fx.create_client(legal_name="Gamma Co", industry="OTHER")
    quote = fx.create_selected_quote(client["id"], coverage_line="DENTAL",
                                    monthly_premium_cents=700_000, commission_rate_pct=0.05)
    policy = validate_success(api.create_policy(
        create_policy_payload(client["id"], quote["id"]), CONSULTANT), 201)
    fresh = validate_success(api.get_policy(policy["id"], CONSULTANT))
    assert fresh["estimated_commission_cents"] == 396_900


# ===========================================================================
# Difficulty / resource_temporal_overlap — coverage overlap (closed interval)
# ===========================================================================
def test_coverage_overlap_touching_endpoints_conflict(api):
    """PRD §3.3: "Activation is refused with ERR_COVERAGE_OVERLAP if it would create a
    closed-interval [effective_date, expiration_date] overlap with another ACTIVE policy for
    the same client and the same coverage line; endpoints that merely touch (one policy's
    expiration equal to another's effective date) do conflict."

    Design: Difficulty/resource_temporal_overlap/policy_coverage_overlap_closed_touching
    """
    client = fx.create_client(legal_name="Pi Co")
    fx.activate_policy(client["id"], coverage_line="MEDICAL", monthly_premium_cents=500_000,
                       effective_date="2026-01-01", expiration_date="2026-06-30")
    p2 = fx.bind_policy(client["id"], coverage_line="MEDICAL", monthly_premium_cents=500_000,
                        effective_date="2026-06-30", expiration_date="2026-12-31")
    resp = api.activate_policy(p2["id"], CONSULTANT)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_OVERLAP.value)


def test_coverage_disjoint_intervals_activate_ok(api):
    """PRD §3.3: "Activation is refused with ERR_COVERAGE_OVERLAP if it would create a
    closed-interval [effective_date, expiration_date] overlap with another ACTIVE policy for
    the same client and the same coverage line; endpoints that merely touch (one policy's
    expiration equal to another's effective date) do conflict."

    Design: Difficulty/resource_temporal_overlap/policy_coverage_overlap_closed_touching
    """
    client = fx.create_client(legal_name="Pi Co")
    fx.activate_policy(client["id"], coverage_line="MEDICAL", monthly_premium_cents=500_000,
                       effective_date="2026-01-01", expiration_date="2026-06-29")
    p2 = fx.bind_policy(client["id"], coverage_line="MEDICAL", monthly_premium_cents=500_000,
                        effective_date="2026-06-30", expiration_date="2026-12-31")
    activated = validate_success(api.activate_policy(p2["id"], CONSULTANT))
    assert activated["lifecycle_status"] == "ACTIVE"


# ===========================================================================
# Difficulty / compensating_invariant — active premium ledger conserved
# ===========================================================================
def test_active_premium_total_conserved_after_activate_then_terminate(api):
    """PRD §3.3: "On successful activation the policy's monthly_premium_cents is added to
    the client's active_premium_total_cents. Terminating an active policy advances its
    lifecycle_status from ACTIVE to TERMINATED and subtracts that policy's
    monthly_premium_cents from the client's active_premium_total_cents."

    Design: Difficulty/compensating_invariant/active_premium_total_conserved_activate_then_terminate
    """
    client = fx.create_client(legal_name="Sigma Co")
    policy = fx.activate_policy(client["id"], monthly_premium_cents=800_000)
    terminated = validate_success(api.terminate_policy(policy["id"], CONSULTANT))
    assert terminated["lifecycle_status"] == "TERMINATED"
    fresh = validate_success(api.get_client(client["id"], CONSULTANT))
    assert fresh["active_premium_total_cents"] == 0


def test_active_premium_total_reflects_forward_activation(api):
    """PRD §2.8: "active_premium_total_cents — the sum of monthly_premium_cents over the
    client's policies whose lifecycle_status is ACTIVE. Activating a policy adds that
    policy's monthly_premium_cents to the total; terminating an active policy subtracts it".

    Design: Difficulty/compensating_invariant/active_premium_total_conserved_activate_then_terminate
    """
    client = fx.create_client(legal_name="Sigma Co")
    fx.activate_policy(client["id"], monthly_premium_cents=800_000)
    fresh = validate_success(api.get_client(client["id"], CONSULTANT))
    assert fresh["active_premium_total_cents"] == 800_000
