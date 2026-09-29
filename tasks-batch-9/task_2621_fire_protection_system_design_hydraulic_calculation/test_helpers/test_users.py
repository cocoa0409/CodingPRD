"""Pre-built role headers for the five roles named in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the two opaque roles (FirmAdmin, Contractor) and for
# tests that never exercise an ownership check.
TEST_USERS = {
    "firm_admin_headers": build_user_headers("ops-admin-1", "FirmAdmin"),
    "contractor_headers": build_user_headers("sprinkler-contractor-1", "Contractor"),
    "design_engineer_headers": build_user_headers("engineer-placeholder-1", "DesignEngineer"),
    "qc_reviewer_headers": build_user_headers("engineer-placeholder-2", "QcReviewer"),
    "ahj_reviewer_headers": build_user_headers("reviewer-placeholder-1", "AhjReviewer"),
}


def make_firm_admin_headers(user_id: str = "ops-admin-1") -> dict:
    """FirmAdmin identities are opaque operator identifiers."""
    return build_user_headers(user_id, "FirmAdmin")


def make_contractor_headers(user_id: str = "sprinkler-contractor-1") -> dict:
    """Contractor identities are opaque operator identifiers."""
    return build_user_headers(user_id, "Contractor")


def make_design_engineer_headers(engineer_id: str) -> dict:
    """Pass the acting Engineer row's id; every design write compares it to the
    project's lead_engineer_id."""
    return build_user_headers(engineer_id, "DesignEngineer")


def make_qc_reviewer_headers(engineer_id: str) -> dict:
    """Pass the reviewing Engineer row's id; it must differ from the calculation's
    authored_by_engineer_id."""
    return build_user_headers(engineer_id, "QcReviewer")


def make_ahj_reviewer_headers(reviewer_id: str) -> dict:
    """Pass the acting AhjReviewer row's id; every authority write compares it to
    the project's ahj_reviewer_id."""
    return build_user_headers(reviewer_id, "AhjReviewer")


def make_clock_headers(role: str = "FirmAdmin") -> dict:
    """The logical-clock endpoint requires only X-User-Role."""
    return {"X-User-Role": role}
