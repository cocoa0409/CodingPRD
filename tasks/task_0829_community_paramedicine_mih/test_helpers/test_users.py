"""Pre-built role headers for every role in the PRD.

Role identities (PRD 2.1):
  - ProgramAdmin  : opaque operator id, never compared against any entity.
  - CareCoordinator/Paramedic/Clinician/BillingSpecialist : X-User-ID is the acting Provider.id.
  - PayerReviewer : X-User-ID is the acting Payer.id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque ProgramAdmin role and for tests that do not
# exercise provider/payer ownership.
TEST_USERS = {
    "program_admin_headers": build_user_headers("op-admin-1", "ProgramAdmin"),
    # Fallbacks for entity_backed roles — use ONLY for non-ownership tests.
    "care_coordinator_headers": build_user_headers("op-coord-1", "CareCoordinator"),
    "paramedic_headers": build_user_headers("op-para-1", "Paramedic"),
    "clinician_headers": build_user_headers("op-clin-1", "Clinician"),
    "billing_specialist_headers": build_user_headers("op-biller-1", "BillingSpecialist"),
    "payer_reviewer_headers": build_user_headers("op-payer-1", "PayerReviewer"),
}


# Per-instance builders — required for every entity_backed role. Pass the real
# Provider.id (or Payer.id for PayerReviewer) whenever the call is ownership-gated.
def make_program_admin_headers(user_id: str = "op-admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_care_coordinator_headers(provider_id: str) -> dict:
    return build_user_headers(provider_id, "CareCoordinator")


def make_paramedic_headers(provider_id: str) -> dict:
    return build_user_headers(provider_id, "Paramedic")


def make_clinician_headers(provider_id: str) -> dict:
    return build_user_headers(provider_id, "Clinician")


def make_billing_specialist_headers(provider_id: str) -> dict:
    return build_user_headers(provider_id, "BillingSpecialist")


def make_payer_reviewer_headers(payer_id: str) -> dict:
    return build_user_headers(payer_id, "PayerReviewer")
