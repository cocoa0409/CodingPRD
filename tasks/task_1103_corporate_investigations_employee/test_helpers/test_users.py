"""Pre-built role headers for every role in the PRD.

Every role's ``X-User-ID`` is opaque per the PRD — no entity-backed identity.
Shared constants below are therefore safe for every call. Tests that need a
*specific* user id (e.g. so that a SOD check can be exercised) should build
per-instance headers via ``build_user_headers(user_id, role)`` directly or via
the convenience builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "intake_coordinator_headers": build_user_headers("ic-1", "IntakeCoordinator"),
    "investigator_headers": build_user_headers("inv-1", "Investigator"),
    "manager_headers": build_user_headers("mgr-1", "InvestigationsManager"),
    "hr_headers": build_user_headers("hr-1", "HRBusinessPartner"),
    "gc_headers": build_user_headers("gc-1", "GeneralCounsel"),
    "clo_headers": build_user_headers("clo-1", "ChiefLegalOfficer"),
    "auditor_headers": build_user_headers("aud-1", "ComplianceAuditor"),
    "admin_headers": build_user_headers("sys-1", "SystemAdmin"),
}


def make_intake_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_investigator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Investigator")


def make_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InvestigationsManager")


def make_hr_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HRBusinessPartner")


def make_gc_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GeneralCounsel")


def make_clo_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ChiefLegalOfficer")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceAuditor")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")
