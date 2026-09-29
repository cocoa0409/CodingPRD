"""Authentication and the family-membership codes of §2.5.

Resolving a reference is not the same as it belonging where the payload claims
it belongs, and each of the four families reports its own code.
"""

from test_helpers import (
    ApiErrorId,
    assert_score,
    make_headers,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _row_count(response):
    _, meta = validate_paginated(response)
    return meta["total_count"]


class TestAuthentication:
    """Both headers are mandatory on every request, writes included."""

    def test_a_request_with_an_empty_user_header_is_unauthenticated(self, api):
        """PRD §2.1: "Every request to the API — reads included — must carry two
        headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the
        capacity in which they act. If either header is absent or empty, the request is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/request_without_a_user_header_unauthenticated
        """
        response = api.create_project(
            f.project_payload(), make_headers("", "Developer")
        )
        validate_error(response, ApiErrorId.UNAUTHENTICATED, expected_status=401)

        assert _row_count(api.list_projects(fx.DEVELOPER_HEADERS)) == 0, (
            "An unauthenticated request never reaches the domain, so no project exists"
        )


class TestCommentFamilyMembership:
    """A comment's segment must sit on the route the same payload names."""

    def test_a_comment_naming_a_segment_of_another_route_is_refused(self, api):
        """PRD §2.5: "a comment's segment must belong to the route named in the same
        payload and an application's route must belong to the named project
        (`ERR_ROUTE_PROJECT_MISMATCH`, which guards both comment intake and application
        filing)."

        Design: Corner/errors/comment_naming_a_segment_of_another_route_rejected
        """
        ctx = {}
        fx.create_project(api, ctx)
        fx.build_route_a(api, ctx)
        fx.build_route_b(api, ctx, nominate=False)
        fx.publish_route_a(api, ctx)

        response = api.create_public_comment(
            f.public_comment_payload(
                ctx["routeA"], commenter_kind="PUBLIC", commenter_name="Nell Ford",
                body="Wrong-route segment cited", materiality="MATERIAL",
                segment_id=ctx["segB1"],
            ),
            fx.ROUTE_ANALYST_HEADERS,
        )
        validate_error(
            response, ApiErrorId.ROUTE_PROJECT_MISMATCH, expected_status=422
        )

        assert fx.read_segment(api, ctx["segB1"])["material_comment_count"] == 0, (
            "The alternate corridor's segment is untouched"
        )
        assert fx.read_segment(api, ctx["seg1"])["material_comment_count"] == 0, (
            "No segment of the published corridor was credited either"
        )
        assert _row_count(
            api.list_public_comments(
                fx.COMMISSION_STAFF_HEADERS, {"route_id": ctx["routeA"]}
            )
        ) == 0, "No comment row survives the membership check"


class TestApplicationFamilyMembership:
    """The study and the route must both belong to the project being filed on."""

    def test_an_application_citing_another_projects_study_is_refused(self, api):
        """PRD §2.5: "an application's study and proposed route must both belong to its
        project (`ERR_STUDY_PROJECT_MISMATCH`)." PRD §3.5 runs the route-belonging check
        before this one, so the corridor named here is one of the filed project's own.

        Design: Corner/errors/application_citing_another_projects_study_rejected
        """
        ctx = fx.setup_nominated_routes(api)
        fx.setup_second_project_nominated_route(api, ctx)

        response = api.create_application(
            f.application_payload(
                ctx["proj_other"], ctx["study"], ctx["routeO"],
                docket_number="EL-2026-0555", filing_fee_cents=2_500_000,
            ),
            fx.DEVELOPER_FILER_HEADERS,
        )
        validate_error(response, ApiErrorId.STUDY_PROJECT_MISMATCH, expected_status=422)

        assert _row_count(
            api.list_applications(
                fx.COMMISSION_STAFF_HEADERS, {"project_id": ctx["proj_other"]}
            )
        ) == 0, "The refused filing writes no application row"
        assert fx.read_project(api, ctx, key="proj_other")["stage"] == "PLANNING", (
            "The second project has no certified study of its own, so it stays PLANNING"
        )
        assert fx.read_project(api, ctx)["stage"] == "ROUTING", (
            "The first project keeps its own corridors and its own stage"
        )
        assert fx.read_route(api, ctx["routeO"])["status"] == "NOMINATED", (
            "The second project's corridor is still nominated and still filable"
        )


class TestActivityFamilyMembership:
    """An activity's segment must sit on the certificate's certified route."""

    def test_an_activity_on_a_segment_off_the_certified_route_is_refused(self, api):
        """PRD §2.5: "a construction activity's segment must sit on the certificate's
        certified route (`ERR_SEGMENT_ROUTE_MISMATCH`)."

        Design: Corner/errors/activity_on_a_segment_off_the_certified_route_rejected
        """
        ctx = fx.setup_issued_certificate(api)

        response = api.create_construction_activity(
            f.construction_activity_payload(
                ctx["cert"], ctx["segB1"], activity_kind="CLEARING", crew_count=4,
                window_start_at="2027-09-01T00:00:00Z",
                window_end_at="2027-09-10T00:00:00Z",
            ),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.SEGMENT_ROUTE_MISMATCH, expected_status=422)

        assert fx.read_route(api, ctx["routeB"])["status"] == "REJECTED", (
            "The order rejected the alternate corridor, which is why its segments are "
            "off the certified route"
        )
        assert fx.read_segment(api, ctx["segB1"])["committed_crew_count"] == 0, (
            "No crew was committed on the rejected corridor"
        )
        assert _row_count(
            api.list_construction_activities(
                fx.DEVELOPER_HEADERS, {"certificate_id": ctx["cert"]}
            )
        ) == 0, "No activity row survives the membership check"


class TestFindingFamilyMembership:
    """A finding's condition must belong to the certificate it is filed against."""

    def test_a_finding_against_another_certificates_condition_is_refused(self, api):
        """PRD §2.5: "and a nonconformance's condition — and its activity, when one is
        named — must belong to the certificate it is filed against
        (`ERR_CONDITION_CERTIFICATE_MISMATCH`)."

        Design: Corner/errors/finding_against_another_certificates_condition_rejected
        """
        ctx = fx.setup_issued_certificate(api)
        fx.setup_second_certificate(api, ctx)

        response = api.create_nonconformance(
            f.nonconformance_payload(
                ctx["cert"], ctx["cond2_1"], severity="MINOR",
                observation="Cultural monitor absent for one shift",
            ),
            fx.COMPLIANCE_MONITOR_HEADERS,
        )
        validate_error(
            response, ApiErrorId.CONDITION_CERTIFICATE_MISMATCH, expected_status=422
        )

        assert fx.read_condition(api, ctx["cond2_1"])["status"] == "ACTIVE", (
            "The other docket's condition was never moved to VIOLATED"
        )
        assert_score(
            fx.read_certificate(api, ctx["cert"])["compliance_index_rolling"],
            100.00, "compliance_index_rolling",
        )
        assert_score(
            fx.read_certificate(api, ctx["cert2"])["compliance_index_rolling"],
            100.00, "compliance_index_rolling",
        )
        assert _row_count(api.list_nonconformances(fx.COMPLIANCE_MONITOR_HEADERS)) == 0, (
            "No finding row survives the membership check"
        )
