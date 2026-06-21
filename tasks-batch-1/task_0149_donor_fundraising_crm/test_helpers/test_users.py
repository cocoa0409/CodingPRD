"""Pre-built role headers for every role in the PRD.

All three roles are operator roles whose X-User-ID is opaque and never matched
against any persisted entity id (PRD Section 2.1). Therefore the shared-constant
form is the canonical form for every role; no per-instance ownership builders are
required because there are no entity_backed roles in this contract.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "gift_admin_headers": build_user_headers("op-gift-admin-1", "GiftAdmin"),
    "campaign_manager_headers": build_user_headers("op-campaign-manager-1", "CampaignManager"),
    "donor_relations_headers": build_user_headers("op-donor-relations-1", "DonorRelations"),
}
