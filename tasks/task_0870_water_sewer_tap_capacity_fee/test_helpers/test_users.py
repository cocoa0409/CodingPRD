"""Pre-built role headers for every role in the PRD (§2.1).

Four roles are opaque (Applicant, Developer, UtilityReviewer, UtilityAdmin): their
X-User-ID is a free-form operator id and the shared constants below are canonical.
Ownership on applications/projects/agreements is checked by comparing the *stored*
owner id (applicant_user_id / developer_user_id / availability_reviewer_id) against
the caller's X-User-ID, so use distinct ids where a scenario needs distinct actors.

FieldInspector is entity-backed: its X-User-ID must be the acting Inspector's id when
the call is ownership-gated (starting an inspection requires the acting inspector to be
the assigned inspector_id). Use make_field_inspector_headers(inspector_id) in that case.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "applicant_headers": build_user_headers("appl-1", "Applicant"),
    "applicant2_headers": build_user_headers("appl-2", "Applicant"),
    "applicant3_headers": build_user_headers("appl-3", "Applicant"),
    "developer_headers": build_user_headers("dev-1", "Developer"),
    "reviewer_headers": build_user_headers("rev-1", "UtilityReviewer"),
    "reviewer2_headers": build_user_headers("rev-2", "UtilityReviewer"),
    "admin_headers": build_user_headers("admin-1", "UtilityAdmin"),
    # Generic FieldInspector header for meter-set field work that is not gated on a
    # specific inspector identity.
    "field_inspector_headers": build_user_headers("insp-generic", "FieldInspector"),
}


def make_applicant_headers(user_id: str) -> dict:
    """For Applicant (opaque). Pass an applicant_user_id to control ownership."""
    return build_user_headers(user_id, "Applicant")


def make_developer_headers(user_id: str) -> dict:
    """For Developer (opaque). Pass the stored developer_user_id for owner-gated calls."""
    return build_user_headers(user_id, "Developer")


def make_reviewer_headers(user_id: str) -> dict:
    """For UtilityReviewer (opaque). Pass a distinct id to satisfy separation of duties."""
    return build_user_headers(user_id, "UtilityReviewer")


def make_field_inspector_headers(inspector_id: str) -> dict:
    """For FieldInspector (entity_backed:Inspector). Pass the actual Inspector.id
    whenever the call is ownership-gated (schedule/start/pass/fail an inspection)."""
    return build_user_headers(inspector_id, "FieldInspector")
