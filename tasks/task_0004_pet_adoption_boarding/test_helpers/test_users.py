"""Pre-built role headers from scaffold Table 7.

Role strings are PRD-exact: ShelterManager | CaseWorker | Veterinarian.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # ShelterManager (approval, refund/void, settlements, shelter lifecycle)
    "manager_headers": build_user_headers("test-manager-1", "ShelterManager"),
    "manager_headers_2": build_user_headers("test-manager-2", "ShelterManager"),
    "manager_headers_3": build_user_headers("test-manager-3", "ShelterManager"),

    # CaseWorker (intake, review, home visits, payments, boarding check-in/out)
    "case_worker_headers": build_user_headers("test-caseworker-1", "CaseWorker"),
    "case_worker_headers_2": build_user_headers("test-caseworker-2", "CaseWorker"),
    "case_worker_headers_3": build_user_headers("test-caseworker-3", "CaseWorker"),

    # Veterinarian (vaccination records, compliance holds)
    "vet_headers": build_user_headers("test-vet-1", "Veterinarian"),
    "vet_headers_2": build_user_headers("test-vet-2", "Veterinarian"),
}


def user_id_from_headers(headers: dict) -> str:
    """Extract the X-User-ID from a headers dict built by build_user_headers."""
    # build_user_headers returns a dict with 'X-User-ID' and 'X-User-Role' keys
    return headers.get("X-User-ID") or headers.get("x-user-id") or ""
