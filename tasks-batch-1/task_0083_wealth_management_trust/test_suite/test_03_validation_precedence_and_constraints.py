"""Validation precedence, cross-entity state gating, and temporal-overlap constraints.

Covers Difficulty queue rules priority_pair_validation_conflict, cross_entity_state_dependency,
and resource_temporal_overlap, plus the matching state-machine and validation corner instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    setup_active_trust, setup_closed_account_with_draft_filing,
    propose_distribution, create_approved_distribution,
    allocate_gst_exemption, make_grantor_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["trust_admin_headers"]


# ─────────────────────────────────────────────────────────────
# Rule priority_pair_validation_conflict — state beats fiscal on pay
# ─────────────────────────────────────────────────────────────

def test_state_check_precedes_corpus_check_on_pay(api):
    """PRD §2.10: "then whether the target is in a state that admits the transition
    (ERR_INVALID_STATE). Business-specific rules are evaluated only after those five gates
    pass." (ERR_INSUFFICIENT_CORPUS is among the business rules.)

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pay
    """
    ctx = setup_active_trust(contribution_cents=1, num_trustees=1)
    g_id = ctx["grantor"]["id"]
    t1 = ctx["trustees"][0]["id"]
    ben_a = get_success_data(api.create_beneficiary(
        {"full_name": "Ben A", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    # PROPOSED (never approved) distribution whose amount also exceeds corpus.
    dist = propose_distribution(ctx["account"]["id"], ben_a["id"], 999999, t1, "MANDATORY")
    from test_helpers import make_trustee_headers
    res = api.pay_distribution(dist["id"], make_trustee_headers(t1))
    validate_error(res, "ERR_INVALID_STATE")


def test_pay_proposed_distribution_returns_invalid_state(api):
    """PRD §3.5: "It is permitted only while the distribution is APPROVED, the owning period
    is OPEN, and the owning trust is in ACTIVE or TERMINATING status — a TERMINATED or
    REVOKED trust can never pay."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pay
    """
    ctx = setup_active_trust(contribution_cents=5_000_000, num_trustees=1)
    g_id = ctx["grantor"]["id"]
    t1 = ctx["trustees"][0]["id"]
    ben_a = get_success_data(api.create_beneficiary(
        {"full_name": "Ben A", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    dist = propose_distribution(ctx["account"]["id"], ben_a["id"], 1000, t1, "MANDATORY")
    from test_helpers import make_trustee_headers
    res = api.pay_distribution(dist["id"], make_trustee_headers(t1))
    validate_error(res, "ERR_INVALID_STATE")


# ─────────────────────────────────────────────────────────────
# Rule priority_pair_validation_conflict — referential beats fiscal on GST
# ─────────────────────────────────────────────────────────────

def test_grantor_mismatch_precedes_exemption_exceeded(api):
    """PRD §2.10: "Among the business rules themselves the ordering, from earliest to
    latest, is: the irrevocable-trust bar (ERR_TRUST_IRREVOCABLE), segregation of duties
    (ERR_SEGREGATION_OF_DUTIES), accounting-period overlap (ERR_ACCOUNT_PERIOD_OVERLAP),
    trustee-term conflict (ERR_TRUSTEE_TERM_CONFLICT), the frozen-period bar
    (ERR_PERIOD_FROZEN), amount validity (ERR_INVALID_AMOUNT), grantor consistency
    (ERR_GRANTOR_MISMATCH), corpus sufficiency (ERR_INSUFFICIENT_CORPUS), exemption-pool
    sufficiency (ERR_GST_EXEMPTION_EXCEEDED), and finally the GST-allocation stale-version
    check (ERR_STALE_TRUST_VERSION)."

    Design: Difficulty/priority_pair_validation_conflict/irrevocable_safety_beats_temporal_overlap_is_moot_use_referential_vs_fiscal_on_gst
    """
    ctx = setup_active_trust(contribution_cents=5_000_000, num_trustees=1)
    trust_id = ctx["trust"]["id"]
    # A second grantor with a tiny exemption pool; naming it both mismatches the trust's
    # grantor AND requests more than the pool.
    g2 = get_success_data(api.create_grantor(
        {"full_name": "G2 Other", "generation_level": 0, "gst_exemption_total_cents": 100}, ADMIN))
    res = api.create_gst_exemption_allocation(
        trust_id,
        {"grantor_id": g2["id"], "amount_cents": 200000,
         "expected_trust_version": ctx["trust"]["version"]},
        ADMIN)
    validate_error(res, "ERR_GRANTOR_MISMATCH")


def test_grantor_mismatch_on_consistent_pool_still_fires(api):
    """PRD §3.8: "The funding grantor must be consistent with the trust — the allocation is
    trust-scoped, and a grantor inconsistent with the trust is rejected with
    ERR_GRANTOR_MISMATCH."

    Design: Difficulty/priority_pair_validation_conflict/irrevocable_safety_beats_temporal_overlap_is_moot_use_referential_vs_fiscal_on_gst
    """
    ctx = setup_active_trust(contribution_cents=5_000_000, num_trustees=1)
    trust_id = ctx["trust"]["id"]
    # Stranger grantor with a large pool: only the referential mismatch can fire.
    g2 = get_success_data(api.create_grantor(
        {"full_name": "G2 Wealthy", "generation_level": 0,
         "gst_exemption_total_cents": 5_000_000_000}, ADMIN))
    res = api.create_gst_exemption_allocation(
        trust_id,
        {"grantor_id": g2["id"], "amount_cents": 200000,
         "expected_trust_version": ctx["trust"]["version"]},
        ADMIN)
    validate_error(res, "ERR_GRANTOR_MISMATCH")


# ─────────────────────────────────────────────────────────────
# Rule cross_entity_state_dependency — pay blocked when trust revoked
# ─────────────────────────────────────────────────────────────

def test_pay_blocked_after_trust_revoked(api):
    """PRD §3.5: "It is permitted only while the distribution is APPROVED, the owning period
    is OPEN, and the owning trust is in ACTIVE or TERMINATING status — a TERMINATED or
    REVOKED trust can never pay."

    Design: Difficulty/cross_entity_state_dependency/distribution_pay_blocked_when_trust_revoked
    """
    ctx = setup_active_trust(trust_type="REVOCABLE", contribution_cents=5_000_000,
                             num_trustees=2)
    g_id = ctx["grantor"]["id"]
    trust_id = ctx["trust"]["id"]
    t_prop, t_appr = ctx["trustees"][0]["id"], ctx["trustees"][1]["id"]
    ben_a = get_success_data(api.create_beneficiary(
        {"full_name": "Ben A", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    dist = create_approved_distribution(ctx["account"]["id"], ben_a["id"], 10000,
                                        t_prop, t_appr, "MANDATORY")
    validate_success(api.revoke_trust(trust_id, make_grantor_headers(g_id)), 200)
    from test_helpers import make_trustee_headers
    res = api.pay_distribution(dist["id"], make_trustee_headers(t_prop))
    validate_error(res, "ERR_INVALID_STATE")


def test_revoke_closes_open_accounts(api):
    """PRD §3.9: "Revocation, also a grantor action confined to revocable trusts, moves a
    trust from ACTIVE to the terminal REVOKED state; it is permitted only while the trust is
    ACTIVE, an attempt to revoke an IRREVOCABLE trust is rejected with ERR_TRUST_IRREVOCABLE,
    and it transitions every OPEN period on the trust to CLOSED and increments the trust's
    version."

    Design: Difficulty/cross_entity_state_dependency/distribution_pay_blocked_when_trust_revoked
    """
    ctx = setup_active_trust(trust_type="REVOCABLE", contribution_cents=5_000_000,
                             num_trustees=1)
    g_id = ctx["grantor"]["id"]
    trust_id = ctx["trust"]["id"]
    validate_success(api.revoke_trust(trust_id, make_grantor_headers(g_id)), 200)
    acct = validate_success(api.get_account(ctx["account"]["id"], ADMIN), 200)
    assert acct["status"] == "CLOSED"


# ─────────────────────────────────────────────────────────────
# Rule resource_temporal_overlap — account period half-open
# ─────────────────────────────────────────────────────────────

def test_overlapping_account_period_rejected(api):
    """PRD §3.3: "A new period must not overlap any existing period on the same trust under
    half-open semantics, which means two periods that merely abut — where one period's
    period_end equals the next period's period_start — are allowed, while any true overlap
    is rejected with ERR_ACCOUNT_PERIOD_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/account_period_half_open_overlap_rejected_abutting_allowed
    """
    g = get_success_data(api.create_grantor({"full_name": "G B8a", "generation_level": 0}, ADMIN))
    trust = get_success_data(api.create_trust(
        {"name": "B8a Trust", "grantor_id": g["id"], "trust_type": "IRREVOCABLE"}, ADMIN))
    validate_success(api.create_account(trust["id"], {
        "tax_year": 2025, "period_start": "2025-01-01T00:00:00.000Z",
        "period_end": "2026-01-01T00:00:00.000Z"}, ADMIN), 201)
    res = api.create_account(trust["id"], {
        "tax_year": 2025, "period_start": "2025-06-01T00:00:00.000Z",
        "period_end": "2026-06-01T00:00:00.000Z"}, ADMIN)
    validate_error(res, "ERR_ACCOUNT_PERIOD_OVERLAP")


def test_abutting_account_period_allowed(api):
    """PRD §3.3: "two periods that merely abut — where one period's period_end equals the
    next period's period_start — are allowed".

    Design: Difficulty/resource_temporal_overlap/account_period_half_open_overlap_rejected_abutting_allowed
    """
    g = get_success_data(api.create_grantor({"full_name": "G B8a", "generation_level": 0}, ADMIN))
    trust = get_success_data(api.create_trust(
        {"name": "B8a Trust", "grantor_id": g["id"], "trust_type": "IRREVOCABLE"}, ADMIN))
    validate_success(api.create_account(trust["id"], {
        "tax_year": 2025, "period_start": "2025-01-01T00:00:00.000Z",
        "period_end": "2026-01-01T00:00:00.000Z"}, ADMIN), 201)
    abut = validate_success(api.create_account(trust["id"], {
        "tax_year": 2026, "period_start": "2026-01-01T00:00:00.000Z",
        "period_end": "2027-01-01T00:00:00.000Z"}, ADMIN), 201)
    assert abut["status"] == "OPEN"


# ─────────────────────────────────────────────────────────────
# Rule resource_temporal_overlap — trustee term closed interval + buffer
# ─────────────────────────────────────────────────────────────

def test_trustee_term_within_buffer_gap_rejected(api):
    """PRD §3.2: "the requested closed term interval [term_start, term_end] may neither
    overlap nor sit within 30 days of an existing active term for that same
    (trust_id, trustee_id) pair, the buffer being a mandatory gap between successive terms
    of one trustee on one trust. A conflict is rejected with ERR_TRUSTEE_TERM_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/trustee_term_closed_interval_buffer_gap_conflict
    """
    g = get_success_data(api.create_grantor({"full_name": "G B8b", "generation_level": 0}, ADMIN))
    t1 = get_success_data(api.create_trustee({"full_name": "Seat T1"}, ADMIN))
    trust = get_success_data(api.create_trust(
        {"name": "B8b Trust", "grantor_id": g["id"], "trust_type": "IRREVOCABLE"}, ADMIN))
    validate_success(api.create_trustee_appointment(trust["id"], {
        "trustee_id": t1["id"], "term_start": "2025-01-01T00:00:00.000Z",
        "term_end": "2030-01-01T00:00:00.000Z"}, ADMIN), 201)
    # 2030-01-15 is 14 days after prior term_end 2030-01-01, inside the 30-day buffer.
    res = api.create_trustee_appointment(trust["id"], {
        "trustee_id": t1["id"], "term_start": "2030-01-15T00:00:00.000Z",
        "term_end": "2035-01-01T00:00:00.000Z"}, ADMIN)
    validate_error(res, "ERR_TRUSTEE_TERM_CONFLICT")


def test_distinct_co_trustees_serve_concurrently(api):
    """PRD §3.2: "Distinct trustees may serve the same trust at the same time as
    co-trustees; the conflict is strictly per seat."

    Design: Difficulty/resource_temporal_overlap/trustee_term_closed_interval_buffer_gap_conflict
    """
    g = get_success_data(api.create_grantor({"full_name": "G B8b", "generation_level": 0}, ADMIN))
    t1 = get_success_data(api.create_trustee({"full_name": "Seat T1"}, ADMIN))
    t2 = get_success_data(api.create_trustee({"full_name": "Seat T2"}, ADMIN))
    trust = get_success_data(api.create_trust(
        {"name": "B8b Trust", "grantor_id": g["id"], "trust_type": "IRREVOCABLE"}, ADMIN))
    validate_success(api.create_trustee_appointment(trust["id"], {
        "trustee_id": t1["id"], "term_start": "2025-01-01T00:00:00.000Z",
        "term_end": "2030-01-01T00:00:00.000Z"}, ADMIN), 201)
    # Distinct trustee, fully overlapping term — allowed (different seat).
    app2 = validate_success(api.create_trustee_appointment(trust["id"], {
        "trustee_id": t2["id"], "term_start": "2025-01-01T00:00:00.000Z",
        "term_end": "2030-01-01T00:00:00.000Z"}, ADMIN), 201)
    assert app2["status"] == "ACTIVE"


# ─────────────────────────────────────────────────────────────
# Corner / validations
# ─────────────────────────────────────────────────────────────

def test_insufficient_corpus_on_pay(api):
    """PRD §3.5: "The payment must be funded from available corpus: the amount_cents must
    be no greater than the trust's principal_balance_cents plus its income_balance_cents,
    or the payment is rejected with ERR_INSUFFICIENT_CORPUS."

    Design: Corner/validations/insufficient_corpus_on_pay_returns_error
    """
    ctx = setup_active_trust(contribution_cents=100, num_trustees=2)
    g_id = ctx["grantor"]["id"]
    t_prop, t_appr = ctx["trustees"][0]["id"], ctx["trustees"][1]["id"]
    ben_a = get_success_data(api.create_beneficiary(
        {"full_name": "Ben A", "grantor_id": g_id, "generation_level": 1}, ADMIN))
    dist = create_approved_distribution(ctx["account"]["id"], ben_a["id"], 200,
                                        t_prop, t_appr, "MANDATORY")
    from test_helpers import make_trustee_headers
    res = api.pay_distribution(dist["id"], make_trustee_headers(t_prop))
    validate_error(res, "ERR_INSUFFICIENT_CORPUS")


def test_gst_exemption_exceeds_pool(api):
    """PRD §3.8: "The requested amount_cents must not exceed the grantor's
    gst_exemption_remaining_cents, or the pool would go negative and the request is
    rejected with ERR_GST_EXEMPTION_EXCEEDED."

    Design: Corner/validations/gst_exemption_exceeds_pool_returns_error
    """
    ctx = setup_active_trust(contribution_cents=5_000_000, num_trustees=1,
                             grantor_total_cents=100000)
    res = api.create_gst_exemption_allocation(
        ctx["trust"]["id"],
        {"grantor_id": ctx["grantor"]["id"], "amount_cents": 200000,
         "expected_trust_version": ctx["trust"]["version"]},
        ADMIN)
    validate_error(res, "ERR_GST_EXEMPTION_EXCEEDED")
