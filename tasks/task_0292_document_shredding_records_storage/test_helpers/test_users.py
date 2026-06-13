"""Pre-built role headers for every role in the PRD.

Every role in this PRD uses an opaque X-User-ID that the server never compares
to any entity's id for ownership (PRD Section 2.1). The single place a captured
identifier is compared is the segregation-of-duties check at destruction, where
the witnessing operator's X-User-ID must differ from the order's recorded
assigned_tech_id. For that reason, several flows pin a specific X-User-ID; the
make_*_headers builders below let a test or fixture set the exact operator id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles; safe everywhere an explicit operator id is
# not required by a workflow capture.
TEST_USERS = {
    "compliance_officer_headers": build_user_headers("compliance-officer-1", "ComplianceOfficer"),
    "account_manager_headers": build_user_headers("account-manager-1", "AccountManager"),
    "field_technician_headers": build_user_headers("field-technician-1", "FieldTechnician"),
    "plant_operator_headers": build_user_headers("plant-operator-1", "PlantOperator"),
    "destruction_witness_headers": build_user_headers("destruction-witness-1", "DestructionWitness"),
}


# Per-operator builders — use these whenever a workflow records the acting
# operator's X-User-ID (assigned_tech_id pinning, witnessed_by, SoD checks).
def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_account_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AccountManager")


def make_field_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FieldTechnician")


def make_plant_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantOperator")


def make_destruction_witness_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DestructionWitness")
