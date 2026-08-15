"""Pre-built role headers for every role in the PRD (§2.1).

All ten roles use an opaque operator identifier for X-User-ID: it is never
compared against any persisted entity's id. It IS compared against other
operator identifiers for segregation of duties (wire initiator vs approvers),
so builders accepting an explicit user_id are provided for each role and are
used whenever the test cares about a specific actor identity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical operator identities used across tests.
TEST_USERS = {
    "wire_ops_admin_headers": build_user_headers("admin-1", "WireOpsAdmin"),
    "wire_operator_headers": build_user_headers("op-1", "WireOperator"),
    "wire_approver_headers": build_user_headers("ap-1", "WireApprover"),
    "wire_approver_2_headers": build_user_headers("ap-2", "WireApprover"),
    "sanctions_screener_headers": build_user_headers("ss-1", "SanctionsScreener"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "fraud_analyst_headers": build_user_headers("fa-1", "FraudAnalyst"),
    "repair_specialist_headers": build_user_headers("rs-1", "RepairSpecialist"),
    "wire_investigator_headers": build_user_headers("inv-1", "WireInvestigator"),
    "beneficiary_bank_headers": build_user_headers("benebank-1", "BeneficiaryBank"),
    "auditor_headers": build_user_headers("aud-1", "Auditor"),
}


def make_wire_ops_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "WireOpsAdmin")


def make_wire_operator_headers(user_id: str = "op-1") -> dict:
    return build_user_headers(user_id, "WireOperator")


def make_wire_approver_headers(user_id: str = "ap-1") -> dict:
    return build_user_headers(user_id, "WireApprover")


def make_sanctions_screener_headers(user_id: str = "ss-1") -> dict:
    return build_user_headers(user_id, "SanctionsScreener")


def make_compliance_officer_headers(user_id: str = "co-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_fraud_analyst_headers(user_id: str = "fa-1") -> dict:
    return build_user_headers(user_id, "FraudAnalyst")


def make_repair_specialist_headers(user_id: str = "rs-1") -> dict:
    return build_user_headers(user_id, "RepairSpecialist")


def make_wire_investigator_headers(user_id: str = "inv-1") -> dict:
    return build_user_headers(user_id, "WireInvestigator")


def make_beneficiary_bank_headers(user_id: str = "benebank-1") -> dict:
    return build_user_headers(user_id, "BeneficiaryBank")


def make_auditor_headers(user_id: str = "aud-1") -> dict:
    return build_user_headers(user_id, "Auditor")
