"""RBAC, authentication, and ownership enforcement (PRD §2.1, §2.11)."""
from test_helpers import (
    ApiErrorId,
    create_event,
    create_group,
    create_group_payload,
    create_segment_payload,
    make_coordinator_headers,
    make_group_leader_headers,
    setup_active_agreement,
    setup_agreement_with_waiver,
    validate_error,
)

COORD = make_coordinator_headers()


class TestAuthentication:
    def test_request_without_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Failure to provide both headers, a blank value, or a role
        string that is not one of the two declared roles results in an
        `ERR_UNAUTHENTICATED` error."

        Design: Corner/validations/request_without_auth_headers_returns_unauthenticated
        """
        group = create_group()
        resp = api.get_group(group["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_undeclared_role_returns_unauthenticated(self, api):
        """PRD §2.1: "Failure to provide both headers, a blank value, or a role
        string that is not one of the two declared roles results in an
        `ERR_UNAUTHENTICATED` error."

        Design: Corner/validations/request_without_auth_headers_returns_unauthenticated
        """
        group = create_group()
        resp = api.get_group(
            group["id"],
            headers={"X-User-ID": "someone", "X-User-Role": "SuperAdmin"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_group_leader_cannot_create_segment_returns_unauthorized(self, api):
        """PRD §2.1: "A well-formed identity whose role is simply not permitted
        on the target operation is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: POST /program/segments authorized role is "ProgramCoordinator".

        Design: Corner/rbac/group_leader_cannot_create_segment_returns_unauthorized
        """
        group = create_group()
        gl = make_group_leader_headers(group["id"])
        resp = api.create_segment(
            create_segment_payload(route_name="Sneak Rd",
                                   mile_marker_start=1.0, mile_marker_end=2.0,
                                   segment_type="ROADWAY", water_adjacent=False),
            gl)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_group_leader_cannot_review_agreement(self, api):
        """PRD §4: POST /program/agreements/{id}/review-decision authorized
        role is "ProgramCoordinator".
        PRD §2.1: "A well-formed identity whose role is simply not permitted
        on the target operation is rejected with `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/group_leader_cannot_create_segment_returns_unauthorized
        """
        from test_helpers import create_agreement, create_segment
        group = create_group()
        segment = create_segment()
        agreement = create_agreement(group, segment)
        gl = make_group_leader_headers(group["id"])
        resp = api.review_decision(agreement["id"], {"decision": "APPROVE"}, gl)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_coordinator_cannot_brief_event_returns_unauthorized(self, api):
        """PRD §4: POST /program/events/{id}/briefing authorized role is
        "GroupLeader".
        PRD §2.1: "A well-formed identity whose role is simply not permitted
        on the target operation is rejected with `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/coordinator_cannot_brief_event_returns_unauthorized
        """
        group, segment, agreement, waiver = setup_agreement_with_waiver()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        resp = api.record_briefing(
            event["id"], {"attendee_waiver_ids": [waiver["id"]]}, COORD)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_coordinator_cannot_create_event(self, api):
        """PRD §4: POST /program/events authorized role is "GroupLeader".
        PRD §2.1: "A well-formed identity whose role is simply not permitted
        on the target operation is rejected with `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/coordinator_cannot_brief_event_returns_unauthorized
        """
        group, segment, agreement = setup_active_agreement()
        resp = api.create_event(
            {"agreement_id": agreement["id"], "scheduled_date": "2026-09-10",
             "expected_volunteers": 2}, COORD)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestOwnership:
    def test_foreign_group_cannot_brief_event_returns_forbidden(self, api):
        """PRD §2.1: "A `GroupLeader` touching a resource whose chain belongs
        to another group is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/validations/foreign_group_cannot_brief_event_returns_forbidden
        """
        ga, sa, aga = setup_active_agreement(
            group_name="Group A", contact_email="a@a.org",
            route_name="Alpha Rd", segment_type="ROADWAY", water_adjacent=False,
        )
        from test_helpers import create_adult_waiver
        wa = create_adult_waiver(aga["id"], ga["id"])
        ea = create_event(aga["id"], ga["id"], scheduled_date="2026-09-10")

        gb = create_group(name="Group B", org_type="SCHOOL",
                          contact_email="b@b.org")
        foreign = make_group_leader_headers(gb["id"])
        resp = api.record_briefing(
            ea["id"], {"attendee_waiver_ids": [wa["id"]]}, foreign)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

    def test_foreign_group_cannot_postpone_others_event(self, api):
        """PRD §2.1: "Ownership checks on any resource compare the
        `AdopterGroup` at the root of the resource's chain to `X-User-ID`"

        Design: Corner/validations/foreign_group_cannot_brief_event_returns_forbidden
        """
        ga, sa, aga = setup_active_agreement(
            group_name="Group A", contact_email="a@a.org",
            route_name="Alpha Rd", segment_type="ROADWAY", water_adjacent=False,
        )
        ea = create_event(aga["id"], ga["id"], scheduled_date="2026-09-10")
        gb = create_group(name="Group B", org_type="SCHOOL",
                          contact_email="b@b.org")
        foreign = make_group_leader_headers(gb["id"])
        resp = api.postpone_event(ea["id"], {"reason": "x"}, foreign)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
