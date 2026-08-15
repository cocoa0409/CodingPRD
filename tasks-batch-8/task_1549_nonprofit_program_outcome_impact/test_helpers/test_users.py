"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed per PRD section 2.1: `FunderViewer` (X-User-ID is
the id of the acting Funder) and `VendorAnalyst` (X-User-ID is the id of the
acting VendorEngagement). Ownership- or scope-gated calls MUST use the
per-instance builders below with the real row id. The other five roles are
opaque and the shared constants are the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    COLLECTOR_USER, DIRECTOR_USER, LEAD_USER, PRIVACY_USER, STEWARD_USER,
)

TEST_USERS = {
    # Opaque roles -- the shared constant is the canonical form.
    "program_director_headers": build_user_headers(DIRECTOR_USER, "ProgramDirector"),
    "evaluation_lead_headers": build_user_headers(LEAD_USER, "EvaluationLead"),
    "field_collector_headers": build_user_headers(COLLECTOR_USER, "FieldCollector"),
    "data_steward_headers": build_user_headers(STEWARD_USER, "DataSteward"),
    "privacy_officer_headers": build_user_headers(PRIVACY_USER, "PrivacyOfficer"),
    # Entity-backed roles -- fallback for non-ownership tests only (for
    # example role-gate probes where the entity id never matters).
    "funder_viewer_headers": build_user_headers("funder-fallback-1", "FunderViewer"),
    "vendor_analyst_headers": build_user_headers("engagement-fallback-1", "VendorAnalyst"),
}

DIRECTOR = TEST_USERS["program_director_headers"]
LEAD = TEST_USERS["evaluation_lead_headers"]
COLLECTOR = TEST_USERS["field_collector_headers"]
STEWARD = TEST_USERS["data_steward_headers"]
PRIVACY = TEST_USERS["privacy_officer_headers"]


def make_program_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramDirector")


def make_evaluation_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EvaluationLead")


def make_field_collector_headers(user_id: str) -> dict:
    """FieldCollector is opaque, but observation recording and segregation-of-
    duties checks compare X-User-ID to certification.staff_user_id and to
    observation.collected_by_id; callers must pin a specific user id."""
    return build_user_headers(user_id, "FieldCollector")


def make_data_steward_headers(user_id: str) -> dict:
    """DataSteward is opaque, but segregation-of-duties checks compare the
    steward's X-User-ID to observation.collected_by_id; pin a specific id."""
    return build_user_headers(user_id, "DataSteward")


def make_privacy_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PrivacyOfficer")


def make_funder_viewer_headers(funder_id: str) -> dict:
    """Headers for a FunderViewer acting as the Funder whose id is
    `funder_id`. Required for every ownership-gated report read/accept/return
    and every list scoped to the caller's own funder."""
    return build_user_headers(funder_id, "FunderViewer")


def make_vendor_analyst_headers(engagement_id: str) -> dict:
    """Headers for a VendorAnalyst acting as the VendorEngagement whose id is
    `engagement_id`. Required for every scope-gated read/submit."""
    return build_user_headers(engagement_id, "VendorAnalyst")


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder used by role-matrix style tests."""
    return build_user_headers(user_id, role)


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
