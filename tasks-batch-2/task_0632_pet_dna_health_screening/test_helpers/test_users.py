"""Pre-built role headers for every role in the PRD.

The Account role is entity_backed: ownership checks compare X-User-ID to the
account's id. So every ownership-gated call must use make_account_headers(account_id)
with the real account id — never the shared TEST_USERS constant. The shared
Account constant is only a fallback for non-ownership tests (e.g. 401/403/404).
PlatformAdmin, LabTechnician, Veterinarian, and Anonymous are opaque.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "lab_technician_headers": build_user_headers("lab-1", "LabTechnician"),
    "veterinarian_headers": build_user_headers("vet-1", "Veterinarian"),
    # entity_backed Account: shared constant is a fallback for non-ownership tests only.
    "account_headers": build_user_headers("account-fallback-1", "Account"),
}


def make_account_headers(account_id: str) -> dict:
    """For the Account role (entity_backed:Account). Pass the actual Account.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(account_id, "Account")


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_lab_technician_headers(user_id: str = "lab-1") -> dict:
    return build_user_headers(user_id, "LabTechnician")


def make_veterinarian_headers(user_id: str = "vet-1") -> dict:
    return build_user_headers(user_id, "Veterinarian")
