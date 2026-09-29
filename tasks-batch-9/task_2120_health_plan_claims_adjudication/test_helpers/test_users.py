"""Pre-built role headers for every role the PRD declares."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#
# Six of the seven roles carry an opaque X-User-ID that the server never compares
# against any row's id, so a shared constant is the canonical form for them.
# ProviderRep is different: its X-User-ID is the id of the acting Provider, so the
# shared constant below is only safe for calls that never reach an ownership check.
TEST_USERS = {
    "plan_admin_headers": build_user_headers("u-plan-admin-1", "PlanAdmin"),
    "network_manager_headers": build_user_headers("u-network-manager-1", "NetworkManager"),
    "claims_intake_headers": build_user_headers("u-claims-intake-1", "ClaimsIntake"),
    "claims_examiner_headers": build_user_headers("u-claims-examiner-1", "ClaimsExaminer"),
    "utilization_reviewer_headers": build_user_headers(
        "u-utilization-reviewer-1", "UtilizationReviewer"
    ),
    "medical_director_headers": build_user_headers("u-medical-director-1", "MedicalDirector"),
    "provider_rep_headers": build_user_headers("u-provider-rep-1", "ProviderRep"),
}


# ─── Per-instance builders ────────────────────────────────────────────────────

def make_provider_rep_headers(provider_id: str) -> dict:
    """For ProviderRep, whose X-User-ID is the id of the acting Provider.

    Every ownership-gated claim call MUST pass the real Provider id here.
    """
    return build_user_headers(provider_id, "ProviderRep")


def make_plan_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlanAdmin")


def make_network_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "NetworkManager")


def make_claims_intake_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsIntake")


def make_claims_examiner_headers(user_id: str) -> dict:
    """The examiner's X-User-ID is written to a claim's last_adjudicated_by_user_id,
    which the segregation-of-duties check compares the overriding director against."""
    return build_user_headers(user_id, "ClaimsExaminer")


def make_utilization_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "UtilizationReviewer")


def make_medical_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MedicalDirector")


def make_headers(user_id: str, role: str) -> dict:
    """Escape hatch for role values outside the seven declared roles."""
    return build_user_headers(user_id, role)
