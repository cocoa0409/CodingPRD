"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque roles (PRD §2.1: X-User-ID is not tied to any
# persisted entity for these roles) — the canonical form for those roles.
# For the entity-backed roles (Physician, MentorPhysician) the shared constant is
# a fallback only for tests that do not exercise an ownership check.
TEST_USERS = {
    "recruiter_headers": build_user_headers("test-recruiter-1", "Recruiter"),
    "contract_admin_headers": build_user_headers("test-contract-admin-1", "ContractAdministrator"),
    "credentialing_specialist_headers": build_user_headers("cs-1", "CredentialingSpecialist"),
    "credentialing_specialist_2_headers": build_user_headers("cs-2", "CredentialingSpecialist"),
    "practice_manager_headers": build_user_headers("test-practice-manager-1", "PracticeManager"),
    "finance_analyst_headers": build_user_headers("test-finance-analyst-1", "FinanceAnalyst"),
    "onboarding_director_headers": build_user_headers("test-onboarding-director-1", "OnboardingDirector"),
    "system_operator_headers": build_user_headers("test-system-operator-1", "SystemOperator"),
    # Fallbacks for non-ownership calls only (e.g. GET reads).
    "physician_headers": build_user_headers("test-physician-1", "Physician"),
    "mentor_headers": build_user_headers("test-mentor-1", "MentorPhysician"),
}


def make_physician_headers(user_id: str) -> dict:
    """Physician is entity-backed (PRD §2.1): X-User-ID must be the acting
    Physician's id whenever the call is ownership-gated (offer counter/accept/
    decline, training-module completion)."""
    return build_user_headers(user_id, "Physician")


def make_mentor_headers(user_id: str) -> dict:
    """MentorPhysician is entity-backed (PRD §2.1): X-User-ID must equal the
    assignment's mentor_physician_id for check-in recording."""
    return build_user_headers(user_id, "MentorPhysician")


def make_specialist_headers(user_id: str) -> dict:
    """CredentialingSpecialist with a caller-chosen opaque id; used to anchor
    segregation of duties (submitter vs verifier must differ, PRD §3.3)."""
    return build_user_headers(user_id, "CredentialingSpecialist")
