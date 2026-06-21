"""Pre-built role headers for every role declared in PRD §2.1.

Two roles (Applicant, Cardholder) are entity-backed against Household.id;
ownership-gated calls MUST use the per-instance builders that thread the
actual Household.id as X-User-ID. The shared TEST_USERS constants are
fallbacks safe only for tests that do not exercise ownership (bad-payload,
not-found, unauth, RBAC tests where the call should be rejected regardless
of identity).
"""
from prd_bench_local_runner.testing import build_user_headers


# ─── Shared constants ──────────────────────────────────────────────────

TEST_USERS = {
    # Opaque operator roles — shared constant is the canonical form.
    "caseworker_headers": build_user_headers("cw_001", "Caseworker"),
    "benefit_issuer_headers": build_user_headers("bi_001", "BenefitIssuer"),
    "fraud_investigator_headers": build_user_headers("inv_001", "FraudInvestigator"),
    "fraud_investigator_b_headers": build_user_headers("inv_002", "FraudInvestigator"),
    "merchant_headers": build_user_headers("mer_001", "Merchant"),
    "policy_admin_headers": build_user_headers("pa_001", "PolicyAdmin"),
    # entity_backed roles — fallback ONLY for non-ownership tests.
    "applicant_headers": build_user_headers("applicant-fallback", "Applicant"),
    "cardholder_headers": build_user_headers("cardholder-fallback", "Cardholder"),
}


# ─── Per-instance builders for entity_backed roles ─────────────────────

def make_applicant_headers(household_id: str) -> dict:
    """For Applicant (entity_backed:Household per PRD §2.1).
    Pass the actual Household.id as user_id for ownership-gated calls."""
    return build_user_headers(household_id, "Applicant")


def make_cardholder_headers(household_id: str) -> dict:
    """For Cardholder (entity_backed:Household per PRD §2.1).
    Pass the actual Household.id as user_id; ownership-gated calls compare
    X-User-ID to the card's household_id."""
    return build_user_headers(household_id, "Cardholder")
