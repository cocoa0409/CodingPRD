"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the ten opaque-identity roles — safe for any call whose
# success does not depend on the caller owning the subject resource.
TEST_USERS = {
    "payer_admin_headers": build_user_headers("test-payer-admin-1", "PayerAdmin"),
    "contract_manager_headers": build_user_headers("test-contract-manager-1", "ContractManager"),
    "attribution_analyst_headers": build_user_headers("test-attribution-analyst-1", "AttributionAnalyst"),
    "actuary_analyst_headers": build_user_headers("test-actuary-analyst-1", "ActuaryAnalyst"),
    "quality_analyst_headers": build_user_headers("test-quality-analyst-1", "QualityAnalyst"),
    "claims_processor_headers": build_user_headers("test-claims-processor-1", "ClaimsProcessor"),
    "settlement_officer_headers": build_user_headers("test-settlement-officer-1", "SettlementOfficer"),
    "dispute_adjudicator_headers": build_user_headers("test-dispute-adjudicator-1", "DisputeAdjudicator"),
    "payment_ops_headers": build_user_headers("test-payment-ops-1", "PaymentOps"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # PracticeGroupRep is entity-backed (X-User-ID must equal a PracticeGroup id);
    # this shared constant is a fallback for non-ownership tests only.
    "practice_group_rep_headers": build_user_headers("test-group-rep-1", "PracticeGroupRep"),
}


def make_practice_group_rep_headers(group_id: str) -> dict:
    """PracticeGroupRep is entity-backed: X-User-ID must equal the acting
    PracticeGroup's id for ownership-gated calls (settlement/dispute reads,
    dispute create/withdraw)."""
    return build_user_headers(group_id, "PracticeGroupRep")


def make_settlement_officer_headers(user_id: str) -> dict:
    """SettlementOfficer with a specific X-User-ID (finalized_by_user_id anchor
    for the segregation-of-duties rule)."""
    return build_user_headers(user_id, "SettlementOfficer")


def make_dispute_adjudicator_headers(user_id: str) -> dict:
    """DisputeAdjudicator with a specific X-User-ID (checked against the
    settlement's finalized_by_user_id at dispute resolve)."""
    return build_user_headers(user_id, "DisputeAdjudicator")
