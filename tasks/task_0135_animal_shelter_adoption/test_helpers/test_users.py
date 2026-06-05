"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — the five operational roles are opaque identities (PRD §2.1):
# their X-User-ID is an opaque operator identifier the server never compares to
# any entity's id. The Adopter shared constant is a fallback for non-ownership
# tests only (e.g., 403/404 paths); ownership-gated Adopter calls MUST use the
# per-instance builder below threaded with the real AdopterAccount.id.
TEST_USERS = {
    "shelter_admin_headers": build_user_headers("admin-1", "ShelterAdmin"),
    "intake_officer_headers": build_user_headers("intake-1", "IntakeOfficer"),
    "veterinarian_headers": build_user_headers("vet-1", "Veterinarian"),
    "adoption_counselor_headers": build_user_headers("counselor-1", "AdoptionCounselor"),
    "foster_coordinator_headers": build_user_headers("foster-1", "FosterCoordinator"),
    "adopter_headers": build_user_headers("adopter-fallback", "Adopter"),
}


# ─── Opaque-role builders (distinct operator IDs for segregation-of-duties tests) ───
def make_shelter_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "ShelterAdmin")


def make_intake_officer_headers(user_id: str = "intake-1") -> dict:
    return build_user_headers(user_id, "IntakeOfficer")


def make_veterinarian_headers(user_id: str = "vet-1") -> dict:
    """Veterinarian is opaque, but euthanasia records the X-User-ID; tests pass
    distinct ids (e.g. 'vet-1' vs 'vet-2') to exercise segregation of duties."""
    return build_user_headers(user_id, "Veterinarian")


def make_adoption_counselor_headers(user_id: str = "counselor-1") -> dict:
    return build_user_headers(user_id, "AdoptionCounselor")


def make_foster_coordinator_headers(user_id: str = "foster-1") -> dict:
    return build_user_headers(user_id, "FosterCoordinator")


# ─── Entity-backed builder (mandatory for Adopter) ───
def make_adopter_headers(adopter_account_id: str) -> dict:
    """For Adopter (entity_backed:AdopterAccount). Pass the actual AdopterAccount.id
    as X-User-ID whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(adopter_account_id, "Adopter")
