"""Pre-built role headers for every role in the PRD.

The Inventor role is entity-backed: its X-User-ID must be the id of the acting
Inventor record whenever a call is ownership-gated (confirming one's own
roster entry, raising a dispute, submitting a disclosure). For those calls,
use make_inventor_headers(inventor["id"]) — never the shared constant.

Opaque roles (all others) use server-recorded operator identifiers. Fixtures
that exercise segregation of duties use the distinct named users below so the
preparer and the approver/certifier are never the same X-User-ID.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed:Inventor — fallback for non-ownership reads only.
    "inventor_headers": build_user_headers("test-inventor-1", "Inventor"),
    # opaque roles — shared constants are the canonical form.
    "tto_headers": build_user_headers("tto_1", "TechTransferOfficer"),
    "licensing_manager_headers": build_user_headers("lm_1", "LicensingManager"),
    "compliance_officer_headers": build_user_headers("comp_officer_1",
                                                     "ComplianceOfficer"),
    "compliance_officer_2_headers": build_user_headers("comp_officer_2",
                                                       "ComplianceOfficer"),
    "compliance_director_headers": build_user_headers("comp_director_1",
                                                      "ComplianceDirector"),
    "finance_officer_headers": build_user_headers("fin_officer_1",
                                                  "FinanceOfficer"),
    "finance_officer_2_headers": build_user_headers("fin_officer_2",
                                                    "FinanceOfficer"),
    "finance_director_headers": build_user_headers("fin_director_1",
                                                   "FinanceDirector"),
    "system_admin_headers": build_user_headers("sysadmin_1", "SystemAdmin"),
}

# User ids used by segregation-of-duties scenarios.
FIN_OFFICER_1_ID = "fin_officer_1"
FIN_DIRECTOR_1_ID = "fin_director_1"
COMP_OFFICER_1_ID = "comp_officer_1"
COMP_DIRECTOR_1_ID = "comp_director_1"


def make_inventor_headers(user_id: str) -> dict:
    """For Inventor (entity_backed:Inventor). Pass the actual Inventor.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Inventor")


def make_tto_headers(user_id: str = "tto_1") -> dict:
    return build_user_headers(user_id, "TechTransferOfficer")


def make_licensing_manager_headers(user_id: str = "lm_1") -> dict:
    return build_user_headers(user_id, "LicensingManager")


def make_compliance_officer_headers(user_id: str = COMP_OFFICER_1_ID) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_compliance_director_headers(user_id: str = COMP_DIRECTOR_1_ID) -> dict:
    return build_user_headers(user_id, "ComplianceDirector")


def make_finance_officer_headers(user_id: str = FIN_OFFICER_1_ID) -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


def make_finance_director_headers(user_id: str = FIN_DIRECTOR_1_ID) -> dict:
    return build_user_headers(user_id, "FinanceDirector")


def make_system_admin_headers(user_id: str = "sysadmin_1") -> dict:
    return build_user_headers(user_id, "SystemAdmin")
