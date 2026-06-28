"""Claim variant selection, reconciliation, risk input filtering, and the estimate
balance at create (queue B: Corner / calculations).
"""
from test_helpers import (
    api_client, TEST_USERS, validate_success, get_success_data, fixtures,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["center_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
MIDWIFE = TEST_USERS["midwife_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ---- denied_claim_full_responsibility ----
def test_denied_claim_full_responsibility(api):
    """PRD §3.6: "Denying a claim moves it from SUBMITTED to DENIED and cascades the denied
    variant: the global-fee charge's client_responsibility_cents becomes the full
    amount_cents, the episode's balance_due_cents is re-derived"

    Design: Corner/calculations/denied_claim_full_responsibility
    """
    ctx = fixtures.setup_episode_with_submitted_claim(global_fee_cents=800000)
    ep_id = ctx["episode"]["id"]
    claim_id = ctx["claim"]["id"]

    claim = validate_success(api.deny_claim(claim_id, BILLING))
    assert claim["status"] == "DENIED"

    ep = validate_success(api.get_episode(ep_id, BILLING))
    assert ep["balance_due_cents"] == 800000, \
        f"DENIED -> full global fee 800000, got {ep['balance_due_cents']}"


# ---- void_claim_reverts_to_estimate ----
def test_void_denied_claim_reverts_to_estimate(api):
    """PRD §3.6: "Voiding reverts the global-fee charge's client_responsibility_cents to
    the estimate variant (the gross global fee times 0.20, rounded half up), re-derives
    the episode's balance_due_cents"

    Design: Corner/calculations/void_claim_reverts_to_estimate
    """
    ctx = fixtures.setup_episode_with_submitted_claim(global_fee_cents=800000)
    ep_id = ctx["episode"]["id"]
    claim_id = ctx["claim"]["id"]
    validate_success(api.deny_claim(claim_id, BILLING))

    claim = validate_success(api.void_claim(claim_id, BILLING))
    assert claim["status"] == "VOID"

    ep = validate_success(api.get_episode(ep_id, BILLING))
    assert ep["balance_due_cents"] == 160000, \
        f"void reverts to 20% estimate 160000, got {ep['balance_due_cents']}"


# ---- risk_tier_zero_completed_visits_low ----
def test_risk_tier_low_with_only_scheduled_visit(api):
    """PRD §3.7: "It is re-derived every time a visit is completed, and it considers only
    the episode's visits in COMPLETED status; SCHEDULED, NO_SHOW, and CANCELLED visits are
    ignored. With no completed visits, the tier is LOW."

    Design: Corner/calculations/risk_tier_zero_completed_visits_low
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    fixtures.schedule_visit(ep_id, scheduled_at="2026-04-01T10:00:00Z")  # never completed

    ep = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert ep["risk_tier"] == "LOW", f"no COMPLETED visits -> LOW, got {ep['risk_tier']}"


# ---- balance_estimate_at_create ----
def test_balance_estimate_at_create(api):
    """PRD §3.6: "the client responsibility is the gross global fee multiplied by the
    self-pay estimate fraction of 0.20 (that is, twenty percent), with the product rounded
    half up to a whole cent."

    Design: Corner/calculations/balance_estimate_at_create
    """
    kit, package = fixtures.create_catalog(global_fee_cents=800000)
    client = fixtures.create_client()
    episode = validate_success(api.create_episode(
        f.create_episode_payload(client["id"], package_code=package["code"], edd="2026-08-01"), INTAKE),
        expected_status=201)
    assert episode["balance_due_cents"] == 160000, \
        f"20% of 800000 == 160000, got {episode['balance_due_cents']}"
