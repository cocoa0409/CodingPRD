"""Pre-built role headers from scaffold Table 7."""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # ShelterManager users
    "manager_headers": build_user_headers("test-manager-1", "ShelterManager"),
    "manager2_headers": build_user_headers("test-manager-2", "ShelterManager"),

    # CaseWorker users
    "caseworker_headers": build_user_headers("test-caseworker-1", "CaseWorker"),
    "caseworker2_headers": build_user_headers("test-caseworker-2", "CaseWorker"),

    # Veterinarian users
    "vet_headers": build_user_headers("test-vet-1", "Veterinarian"),
    "vet2_headers": build_user_headers("test-vet-2", "Veterinarian"),
}
