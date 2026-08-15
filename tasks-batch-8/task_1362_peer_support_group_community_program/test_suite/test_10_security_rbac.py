"""Authentication, authorization, and ownership checks (PRD §2.1)."""
from test_helpers import (
    ApiErrorId,
    create_program_payload,
    make_facilitator,
    make_facilitator_headers,
    make_participant,
    make_participant_headers,
    reset_clock,
    validate_error,
)


class TestAuthentication:
    def test_missing_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming their
        operational role. A request missing either header, or carrying a
        malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_headers
        """
        resp = api.list_programs({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_participant_cannot_create_program(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "`Participant` manages their own agreements, enrollments,
        check-ins, check-outs, and surveys."

        Design: Corner/errors/error_forbidden_participant_cannot_create_program
        """
        reset_clock()
        participant = make_participant(full_name="P")
        resp = api.create_program(
            create_program_payload(name="Bad"),
            make_participant_headers(participant["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_facilitator_cannot_create_program(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "In broad strokes: `ProgramAdmin` is the operational
        administrator and may perform all write operations, including creating
        programs, rooms, training courses, groups, facilitators, and
        participants"

        Design: Corner/rbac/facilitator_cannot_create_program_admin_only
        """
        reset_clock()
        facilitator = make_facilitator(full_name="F")
        resp = api.create_program(
            create_program_payload(name="Bad"),
            make_facilitator_headers(facilitator["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestOwnership:
    def test_facilitator_viewing_other_profile_rejected(self, api):
        """PRD §2.1: "When `X-User-Role` is `Facilitator`, `X-User-ID` is the
        `id` of the acting Facilitator entity; ownership checks on any resource
        that references a Facilitator compare the resource's foreign-key field
        to `X-User-ID` — for example, a facilitator may view their own
        profile"
        PRD §2.1: "A request whose entity-backed `X-User-ID` does not match an
        existing entity of the backing type, or — where the endpoint declares
        ownership — does not match the resource owner, is rejected with
        `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/facilitator_viewing_other_facilitator_profile_ownership_mismatch
        """
        reset_clock()
        f1 = make_facilitator(full_name="F1")
        f2 = make_facilitator(full_name="F2")
        resp = api.get_facilitator(f2["id"], make_facilitator_headers(f1["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
