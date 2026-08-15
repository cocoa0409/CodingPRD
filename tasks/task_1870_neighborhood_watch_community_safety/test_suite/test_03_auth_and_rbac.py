"""Authentication, authorization matrix, and validation priority ordering."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_member,
    create_active_agreement,
    create_certification_review_payload,
    create_officer,
    file_incident,
    make_member_headers,
    make_officer_headers,
    move_report_to_under_review,
    open_certification_review,
    set_clock,
    setup_group_with_member,
    setup_group_with_registered_block,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request whose headers are missing or malformed, or whose
        declared role is not one of these four, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_headers
        """
        resp = api.list_watch_groups({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorizationMatrix:
    def test_member_cannot_create_watch_group(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted to
        invoke the endpoint per the authorization matrix in §4 is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /watch/watch-groups is authorized for ProgramCoordinator only.

        Design: Corner/rbac/member_cannot_create_watch_group
        """
        resp = api.create_watch_group(
            {"name": "RBAC Watch", "precinct_code": "R01"},
            make_member_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_coordinator_cannot_corroborate_incident(self, api):
        """PRD §4: POST /watch/incident-reports/{id}/corroborate is authorized
        for LiaisonOfficer only.
        PRD §2.6: "second, role authorization against the endpoint
        (`ERR_UNAUTHORIZED`)" — the role check precedes every business rule.

        Design: Corner/rbac/coordinator_cannot_corroborate_incident
        """
        set_clock("2026-08-02T00:00:00Z")
        group, block, member = setup_group_with_member("RBAC2 Watch", "R02")
        officer = create_officer("BR02", "Officer RB", "R02")
        create_active_agreement(group["id"], officer, scope="FULL")
        report = file_incident(block["id"], member, category="OTHER",
                               occurred_at="2026-08-01T09:00:00Z")
        move_report_to_under_review(report["id"])

        # Even with every business precondition satisfied, the role check fires.
        resp = api.corroborate_incident(report["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

        after = validate_success(api.get_incident_report(report["id"], COORD))
        assert after["review_status"] == "UNDER_REVIEW"

    def test_officer_cannot_decide_review_assigned_to_another_officer(self, api):
        """PRD §3.8: "Decision is the reviewing officer's act — the acting
        officer must equal `reviewing_officer_id`"
        PRD §2.1: "ownership checks on any resource that references a
        `LiaisonOfficer` compare the resource's foreign-key field —
        `liaison_officer_id`, `trainer_officer_id`, or `reviewing_officer_id` —
        to `X-User-ID`."

        Design: Corner/rbac/officer_cannot_decide_review_assigned_to_another_officer
        """
        group, _block = setup_group_with_registered_block(
            "RBAC3 Watch", "R03", "3-3 Rbac St", 4,
        )
        officer_a = create_officer("BR03A", "Officer A3", "R03")
        officer_b = create_officer("BR03B", "Officer B3", "R03")
        review = open_certification_review(group["id"], officer_a)

        resp = api.decide_certification_review(
            review["id"], {"decision": "REJECTED"},
            make_officer_headers(officer_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

        after = validate_success(api.get_certification_review(review["id"], COORD))
        assert after["review_status"] == "PENDING"


class TestValidationPriority:
    def test_existence_checked_before_state(self, api):
        """PRD §2.6: "third, existence of the resources named in the path
        (`ERR_NOT_FOUND`); fourth, whether the target resource is in a state from
        which the requested transition exists (`ERR_INVALID_STATE`)"

        Design: Corner/validations/priority_order_existence_before_state
        """
        resp = api.begin_review_incident(NON_EXISTENT_UUID, COORD)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
