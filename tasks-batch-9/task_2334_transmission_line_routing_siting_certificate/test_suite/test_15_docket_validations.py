"""Rules that guard the filing, the hearing record and the commission's order.

The two status dimensions of an application move on separate tracks, so each
refusal here is checked against both.
"""

from test_helpers import (
    ApiErrorId,
    make_commission_staff_headers,
    make_hearing_examiner_headers,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


DUAL_ROLE_USER = "dual-dana"


def _application_count(api, project_id):
    _, meta = validate_paginated(
        api.list_applications(fx.COMMISSION_STAFF_HEADERS, {"project_id": project_id})
    )
    return meta["total_count"]


def _certificate_count(api, application_id):
    _, meta = validate_paginated(
        api.list_certificates(
            fx.COMMISSION_STAFF_HEADERS, {"application_id": application_id}
        )
    )
    return meta["total_count"]


class TestFilingGates:
    """Two of the filing's ordered checks, isolated one at a time."""

    def test_a_second_open_application_on_the_project_is_refused(self, api):
        """PRD §3.5: "the project must not already carry an application whose
        `review_status` is neither `GRANTED` nor `DENIED`
        (`ERR_DUPLICATE_APPLICATION`, HTTP 409)."

        Design: Corner/validations/duplicate_open_application_on_the_project_rejected
        """
        ctx = fx.setup_accepted_application(api)

        response = api.create_application(
            f.application_payload(
                ctx["proj"], ctx["study"], ctx["routeA"],
                docket_number="EL-2026-0999", filing_fee_cents=2_500_000,
            ),
            fx.DEVELOPER_FILER_HEADERS,
        )
        validate_error(response, ApiErrorId.DUPLICATE_APPLICATION, expected_status=409)

        assert _application_count(api, ctx["proj"]) == 1, (
            "The project still carries exactly the one open application"
        )
        application = fx.read_application(api, ctx["app"])
        assert application["review_status"] == "ACCEPTED", (
            f"The standing application is untouched, got "
            f"{application['review_status']}"
        )
        assert application["docket_number"] == "EL-2026-0334", (
            f"The refused second docket number was never recorded, got "
            f"{application['docket_number']!r}"
        )

    def test_filing_with_no_nominated_alternate_corridor_is_refused(self, api):
        """PRD §3.5: "and last of all, the project must offer at least one nominated
        alternate corridor to snapshot, or the filing is refused with
        `ERR_NO_ALTERNATE_ROUTE` (HTTP 422)."

        Design: Corner/validations/application_without_a_nominated_alternate_route_rejected
        """
        ctx = fx.build_certified_study(api)
        fx.build_route_a(api, ctx)
        fx.publish_route_a(api, ctx)
        fx.record_two_open_houses(api, ctx)
        fx.set_clock(api, "2026-08-31T00:00:00Z")
        fx.nominate_route(api, ctx, "routeA")

        response = api.create_application(
            f.application_payload(ctx["proj"], ctx["study"], ctx["routeA"]),
            fx.DEVELOPER_FILER_HEADERS,
        )
        validate_error(response, ApiErrorId.NO_ALTERNATE_ROUTE, expected_status=422)

        assert _application_count(api, ctx["proj"]) == 0, (
            "There is nothing to snapshot, so no application row is written"
        )
        assert fx.read_project(api, ctx)["stage"] == "ROUTING", (
            "The project stays in ROUTING because the filing never landed"
        )
        assert fx.read_route(api, ctx["routeA"])["status"] == "NOMINATED", (
            "The proposed corridor is still nominated and still filable"
        )


class TestHearingRecordGates:
    """When a session may be held, and what must be finished before closure."""

    def test_a_session_cannot_be_held_before_its_window_opens(self, api):
        """PRD §3.6: "A session may not be held before the logical clock reaches its
        `window_start_at`; earlier attempts are refused with
        `ERR_SESSION_NOT_STARTED` (HTTP 409)."

        Design: Corner/validations/holding_a_session_before_its_window_opens_rejected
        """
        ctx = fx.setup_accepted_application(api)
        fx.schedule_session(api, ctx)

        response = api.hold_hearing_session(
            ctx["sess1"], f.holding_payload(exhibits_admitted_count=12),
            fx.HEARING_EXAMINER_HEADERS,
        )
        validate_error(response, ApiErrorId.SESSION_NOT_STARTED, expected_status=409)

        session = fx.read_session(api, ctx["sess1"])
        assert session["status"] == "SCHEDULED", (
            f"The session is still waiting for its window, got {session['status']}"
        )
        assert session["exhibits_admitted_count"] == 0, (
            f"No exhibits were admitted, got {session['exhibits_admitted_count']}"
        )
        assert fx.read_application(api, ctx["app"])["record_status"] == "SCHEDULING", (
            "The record dimension is still at SCHEDULING"
        )

    def test_closure_is_refused_while_a_session_is_still_scheduled(self, api):
        """PRD §3.6: "Two prerequisites guard it, in this order: no session on the
        application may still be at `SCHEDULED` (`ERR_HEARING_STILL_SCHEDULED`, HTTP
        409), and every intervention petition on the application must have been ruled
        either `GRANTED` or `DENIED` (`ERR_INTERVENTION_UNRULED`, HTTP 409)."

        Design: Corner/validations/record_closure_with_a_session_still_scheduled_rejected
        """
        ctx = fx.setup_accepted_application(api)
        fx.schedule_session(api, ctx)
        fx.set_clock(api, "2026-10-05T09:00:00Z", fx.HEARING_EXAMINER_HEADERS)
        fx.hold_session(api, ctx)
        fx.schedule_session(
            api, ctx, key="sess2", kind="PUBLIC_TESTIMONY",
            window_start_at="2026-10-06T09:00:00Z",
            window_end_at="2026-10-06T12:00:00Z",
        )

        response = api.close_record(
            ctx["app"], f.record_closure_payload(), fx.HEARING_EXAMINER_HEADERS
        )
        validate_error(response, ApiErrorId.HEARING_STILL_SCHEDULED, expected_status=409)

        assert fx.read_session(api, ctx["sess2"])["status"] == "SCHEDULED", (
            "The public testimony session is still on the calendar"
        )
        assert fx.read_application(api, ctx["app"])["record_status"] == "RECORD_OPEN", (
            "The record stays open until every session has been held"
        )

    def test_closure_is_refused_while_a_petition_is_unruled(self, api):
        """PRD §3.6: "and every intervention petition on the application must have
        been ruled either `GRANTED` or `DENIED` (`ERR_INTERVENTION_UNRULED`, HTTP
        409)."

        Design: Corner/validations/record_closure_with_an_unruled_petition_rejected
        """
        ctx = fx.setup_accepted_application(api)
        fx.create_landowner(api, ctx, "lo1")
        fx.petition_to_intervene(api, ctx, "int1", landowner_key="lo1")
        fx.schedule_session(api, ctx)
        fx.set_clock(api, "2026-10-05T09:00:00Z", fx.HEARING_EXAMINER_HEADERS)
        fx.hold_session(api, ctx)

        response = api.close_record(
            ctx["app"], f.record_closure_payload(), fx.HEARING_EXAMINER_HEADERS
        )
        validate_error(response, ApiErrorId.INTERVENTION_UNRULED, expected_status=409)

        assert fx.read_intervention(api, ctx["int1"])["status"] == "PETITIONED", (
            "The petition is still awaiting a ruling"
        )
        assert fx.read_application(api, ctx["app"])["record_status"] == "RECORD_OPEN", (
            "The record cannot close over an unruled petition"
        )


class TestDecisionGates:
    """The record must be closed, and the decider must not have presided."""

    def test_a_decision_before_the_record_closes_is_refused(self, api):
        """PRD §3.7: "Either outcome requires the application to be sitting at
        `ACCEPTED` on the review dimension and at `RECORD_CLOSED` on the record
        dimension; a decision attempted before the record closes is refused with
        `ERR_RECORD_NOT_CLOSED` (HTTP 409)."

        Design: Corner/validations/decision_before_the_record_is_closed_rejected
        """
        ctx = fx.setup_accepted_application(api)
        fx.schedule_session(api, ctx)
        fx.set_clock(api, "2026-10-05T09:00:00Z", fx.HEARING_EXAMINER_HEADERS)
        fx.hold_session(api, ctx)

        response = api.record_decision(
            ctx["app"],
            f.decision_payload(outcome="GRANT", certified_route_id=ctx["routeA"]),
            fx.COMMISSION_STAFF_HEADERS,
        )
        validate_error(response, ApiErrorId.RECORD_NOT_CLOSED, expected_status=409)

        application = fx.read_application(api, ctx["app"])
        assert application["review_status"] == "ACCEPTED", (
            f"The merits dimension is untouched, got {application['review_status']}"
        )
        assert application["record_status"] == "RECORD_OPEN", (
            f"The record dimension is untouched, got {application['record_status']}"
        )
        assert _certificate_count(api, ctx["app"]) == 0, (
            "No certificate is minted by a refused decision"
        )
        assert fx.read_route(api, ctx["routeA"])["status"] == "NOMINATED", (
            "The corridor is neither certified nor rejected"
        )

    def test_the_examiner_who_presided_may_not_decide_the_docket(self, api):
        """PRD §2.10: "the staff user who records the decision must not have presided
        over the hearing: if the acting `X-User-ID` matches the `presiding_user_id` of
        any hearing session on that application whose status is `HELD`, the decision
        is refused with `ERR_DECIDER_PRESIDED`."

        Design: Corner/validations/decision_by_the_presiding_examiner_rejected
        """
        ctx = fx.setup_accepted_application(api)
        examiner_headers = make_hearing_examiner_headers(DUAL_ROLE_USER)
        fx.schedule_session(api, ctx, key="sessd", headers=examiner_headers)
        fx.set_clock(api, "2026-10-05T09:00:00Z", examiner_headers)
        fx.hold_session(api, ctx, key="sessd", headers=examiner_headers)
        fx.close_record(api, ctx, headers=examiner_headers)

        response = api.record_decision(
            ctx["app"],
            f.decision_payload(outcome="GRANT", certified_route_id=ctx["routeA"]),
            make_commission_staff_headers(DUAL_ROLE_USER),
        )
        validate_error(response, ApiErrorId.DECIDER_PRESIDED, expected_status=403)

        session = fx.read_session(api, ctx["sessd"])
        assert session["presiding_user_id"] == DUAL_ROLE_USER, (
            f"The held session records the dual-role user as presiding, got "
            f"{session['presiding_user_id']!r}"
        )
        assert session["status"] == "HELD", (
            f"Only a HELD session disqualifies a decider, got {session['status']}"
        )
        application = fx.read_application(api, ctx["app"])
        assert application["record_status"] == "RECORD_CLOSED", (
            f"The record did close, so the state gates are all satisfied, got "
            f"{application['record_status']}"
        )
        assert application["review_status"] == "ACCEPTED", (
            f"The refusal leaves the merits dimension at ACCEPTED, got "
            f"{application['review_status']}"
        )
        assert _certificate_count(api, ctx["app"]) == 0, (
            "No certificate is minted by a refused decision"
        )
