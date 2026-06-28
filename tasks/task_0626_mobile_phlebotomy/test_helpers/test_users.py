"""Pre-built role headers for every role in the Mobile Phlebotomy PRD (§2.1).

Four roles (OrderingProvider, Dispatcher, LabOps, BillingAgent) are opaque operator
identities not tied to any persisted entity, so a shared constant is the canonical form.
Phlebotomist is the one entity-backed role: X-User-ID must equal the acting Phlebotomist
entity's id for ownership-gated actions (arrival). Use make_phlebotomist_headers(phleb_id)
with the real Phlebotomist.id whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles; the Phlebotomist entry is a fallback
# for tests that do NOT exercise phlebotomist ownership.
TEST_USERS = {
    "ordering_provider_headers": build_user_headers("op-user-1", "OrderingProvider"),
    "dispatcher_headers": build_user_headers("dispatcher-user-1", "Dispatcher"),
    "lab_ops_headers": build_user_headers("labops-user-1", "LabOps"),
    "billing_agent_headers": build_user_headers("billing-user-1", "BillingAgent"),
    "phlebotomist_headers": build_user_headers("phleb-user-1", "Phlebotomist"),
}


def make_phlebotomist_headers(user_id: str) -> dict:
    """For Phlebotomist (entity_backed:Phlebotomist). Pass the actual Phlebotomist.id as
    user_id whenever the call is ownership-gated (e.g., arrive, collect, complete-draw,
    add-specimen performed by the assigned phlebotomist)."""
    return build_user_headers(user_id, "Phlebotomist")
