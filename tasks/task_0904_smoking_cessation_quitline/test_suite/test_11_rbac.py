"""Role-based access control and entity-backed participant ownership."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS, NO_AUTH_HEADERS,
    make_participant_headers, create_participant, create_enrollment,
)

PA = TEST_USERS["program_admin_headers"]
CM = TEST_USERS["case_manager_headers"]


def test_program_admin_cannot_create_enrollment(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or a participant attempts to act on a resource
    it does not own — the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/program_admin_cannot_create_enrollment
    """
    part = create_participant(api, cpd=10)
    resp = api.create_enrollment(part["id"], {}, PA)  # enrollment creation is CaseManager-only
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_participant_cannot_read_other_participants_enrollment(api):
    """PRD §2.1: "A participant may read only its own participant record, its own
    enrollments, and the child resources of those enrollments, and may submit only
    readiness assessments and quit attempts on enrollments it owns. Any attempt to
    reach another participant's data is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/participant_cannot_read_other_participants_enrollment
    """
    part_a = create_participant(api, cpd=10, full_name="A", email="a@x.com")
    enr_a = create_enrollment(api, part_a["id"])
    part_b = create_participant(api, cpd=10, full_name="B", email="b@x.com")
    resp = api.get_enrollment(enr_a["id"], make_participant_headers(part_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_participant_reads_own_enrollment(api):
    """PRD §2.1: "A participant may read only its own participant record, its own
    enrollments, and the child resources of those enrollments, and may submit only
    readiness assessments and quit attempts on enrollments it owns."

    Design: Corner/rbac/participant_reads_own_enrollment_ok
    """
    part_a = create_participant(api, cpd=10, full_name="A", email="a@x.com")
    enr_a = create_enrollment(api, part_a["id"])
    data = validate_success(api.get_enrollment(enr_a["id"], make_participant_headers(part_a["id"])))
    assert data["status"] == "PENDING_ASSESSMENT"


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    part = create_participant(api, cpd=10)
    enr = create_enrollment(api, part["id"])
    resp = api.get_enrollment(enr["id"], NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
