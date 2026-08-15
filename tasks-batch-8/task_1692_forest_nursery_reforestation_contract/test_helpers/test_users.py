"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — the four operator roles are opaque (X-User-ID is never
# compared to an entity id), so a fixed identifier is canonical for them.
# The Landowner role is entity-backed: the shared constant is a fallback for
# non-ownership tests only; ownership-gated calls MUST use
# make_landowner_headers(<landowner id>).
TEST_USERS = {
    "nursery_manager_headers": build_user_headers("test-nursery-manager-1", "NurseryManager"),
    "contract_officer_headers": build_user_headers("test-contract-officer-1", "ContractOfficer"),
    "field_auditor_headers": build_user_headers("test-field-auditor-1", "FieldAuditor"),
    "program_administrator_headers": build_user_headers(
        "test-program-administrator-1", "ProgramAdministrator"
    ),
    # Fallback only — this id resolves to no Landowner record, so it is usable
    # solely where authentication itself is expected to fail or ownership is
    # irrelevant.
    "landowner_headers": build_user_headers("test-landowner-1", "Landowner"),
}


def make_landowner_headers(user_id: str) -> dict:
    """Headers for the entity-backed Landowner role (PRD §2.1).

    Pass the actual Landowner record's id as user_id whenever the call is
    ownership-gated: creating/amending/cancelling an order, creating or
    submitting an enrollment, or reading a landowner-owned resource.
    """
    return build_user_headers(user_id, "Landowner")
