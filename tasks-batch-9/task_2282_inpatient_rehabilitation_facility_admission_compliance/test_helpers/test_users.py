"""Role headers for every role in the PRD (§2.1).

`ComplianceOfficer` identities are opaque operator identifiers, so the shared
constants below are the canonical form for that role. The other four roles are
backed by a `Clinician` record: `X-User-ID` must be the acting clinician's `id`,
so ownership-, credential- and duty-gated calls MUST use the per-instance
builders (`make_nurse_headers`, ...) with the real clinician id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque ComplianceOfficer operator identifiers (PRD §2.1, §2.9).
OFFICER_ONE_USER_ID = "officer-1"
OFFICER_TWO_USER_ID = "officer-2"


TEST_USERS = {
    # Opaque role — shared constants are the canonical form.
    "compliance_officer_headers": build_user_headers(
        OFFICER_ONE_USER_ID, "ComplianceOfficer"
    ),
    "second_compliance_officer_headers": build_user_headers(
        OFFICER_TWO_USER_ID, "ComplianceOfficer"
    ),
    # Clinician-backed roles — these shared constants are only safe for tests
    # that do not depend on the caller resolving to a real clinician record
    # (for example role-authorisation rejections evaluated before any lookup).
    "nurse_case_manager_headers": build_user_headers(
        "test-nurse-case-manager-1", "NurseCaseManager"
    ),
    "rehab_physician_headers": build_user_headers(
        "test-rehab-physician-1", "RehabPhysician"
    ),
    "therapy_lead_headers": build_user_headers("test-therapy-lead-1", "TherapyLead"),
    "him_coder_headers": build_user_headers("test-him-coder-1", "HimCoder"),
}


# Headers that omit `X-User-Role` entirely (PRD §2.1 header presence rule).
HEADERS_WITHOUT_ROLE = {
    "X-User-ID": OFFICER_ONE_USER_ID,
    "Content-Type": "application/json",
}

# Headers that omit `X-User-ID` entirely (PRD §2.1 header presence rule).
HEADERS_WITHOUT_USER_ID = {
    "X-User-Role": "ComplianceOfficer",
    "Content-Type": "application/json",
}


def make_officer_headers(user_id: str) -> dict:
    """Headers for a ComplianceOfficer with an explicit opaque operator id."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_nurse_headers(clinician_id: str) -> dict:
    """Headers for NurseCaseManager. Pass the acting Clinician's own `id`."""
    return build_user_headers(clinician_id, "NurseCaseManager")


def make_physician_headers(clinician_id: str) -> dict:
    """Headers for RehabPhysician. Pass the acting Clinician's own `id`."""
    return build_user_headers(clinician_id, "RehabPhysician")


def make_therapy_lead_headers(clinician_id: str) -> dict:
    """Headers for TherapyLead. Pass the acting Clinician's own `id`."""
    return build_user_headers(clinician_id, "TherapyLead")


def make_coder_headers(clinician_id: str) -> dict:
    """Headers for HimCoder. Pass the acting Clinician's own `id`."""
    return build_user_headers(clinician_id, "HimCoder")
