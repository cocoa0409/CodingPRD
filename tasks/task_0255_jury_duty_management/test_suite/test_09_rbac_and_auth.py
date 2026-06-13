"""Role-based access control and authentication.

Translates corner-design instances from §1.9 sections `endpoints` and `rbac`
(queue B).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    draw_payload, qualification_payload, create_trial_payload, seat_payload,
    TEST_USERS, make_juror_headers,
    setup_open_term_with_qualified_jurors, get_term, draw, get_summons,
    create_term, add_juror, admin_qualify, open_term,
    submit_qualifying_questionnaire, check_in, create_ready_trial, create_panel,
    set_clock,
)

_ADMIN = TEST_USERS["jury_administrator_headers"]
_CLERK = TEST_USERS["court_clerk_headers"]
_JUDGE = TEST_USERS["judge_headers"]


def test_juror_cannot_draw(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §4 endpoint table: "POST `/service-terms/{id}/draw` ... JuryAdministrator."

    Design: Corner/endpoints/rbac_juror_cannot_draw
    """
    term, jurors, open_v = setup_open_term_with_qualified_jurors(
        num_jurors=1, term_overrides={"name": "E1"}
    )
    resp = api.draw(term["id"], draw_payload(1, open_v), make_juror_headers(jurors[0]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    assert get_term(term["id"])["summoned_count"] == 0, "no summons may be created by a forbidden role"


def test_courtclerk_cannot_seat_panel(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §4 endpoint table: "POST `/panels/{id}/seat` ... Judge."

    Design: Corner/endpoints/rbac_courtclerk_cannot_seat_panel
    """
    set_clock("2026-07-20T08:00:00Z")
    term, jurors, open_v = setup_open_term_with_qualified_jurors(
        num_jurors=1, term_overrides={"name": "E2", "report_date": "2026-07-01T00:00:00Z"}
    )
    summons = draw(term["id"], open_v, count=1)[0]
    submit_qualifying_questionnaire(summons["id"], jurors[0]["id"])
    check_in(summons["id"], "2026-07-20T00:00:00Z", 8.0)
    trial = create_ready_trial(term["id"], required_jurors=1, caption="State v. E2")
    panel = create_panel(trial["id"], target_size=1)
    # A CourtClerk attempts a Judge-exclusive seat.
    resp = api.seat(panel["id"], seat_payload(summons["id"], panel["version"]), _CLERK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_juror_cannot_qualify_others_summons(api):
    """PRD §2.1: "a juror submitting a qualification questionnaire or requesting a
    disposition on a summons must own that summons, meaning the summons's `juror_id`
    must equal `X-User-ID`; otherwise the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/endpoints/juror_cannot_qualify_others_summons
    """
    term, jurors, open_v = setup_open_term_with_qualified_jurors(
        num_jurors=2, term_overrides={"name": "E3"}
    )
    summonses = draw(term["id"], open_v, count=2)
    # Find juror B's summons and have juror A act on it.
    jA, jB = jurors[0], jurors[1]
    sB = next(x for x in summonses if x["juror_id"] == jB["id"])
    resp = api.submit_qualification(sB["id"], qualification_payload(), make_juror_headers(jA["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    assert get_summons(sB["id"])["status"] == "SUMMONED", "the un-owned summons must stay SUMMONED"


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request to the API carries two mandatory HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role` ... If either header
    is absent, or if `X-User-Role` is not one of these four declared roles, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/endpoints/missing_auth_headers_unauthenticated
    """
    resp = api.list_service_terms(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_create_trial_shared_by_admin_and_judge_denied_to_clerk(api):
    """PRD §3.7: "A trial is created under a term by either a `JuryAdministrator` or
    a `Judge`, supplying a `caption` and the number of `required_jurors`."
    PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/rbac_term_create_shared_trial_both_roles
    """
    term = create_term(name="RB1")
    validate_success(api.create_trial(term["id"], create_trial_payload(caption="By Judge", required_jurors=1), _JUDGE), 201)
    validate_success(api.create_trial(term["id"], create_trial_payload(caption="By Admin", required_jurors=1), _ADMIN), 201)
    resp = api.create_trial(term["id"], create_trial_payload(caption="By Clerk", required_jurors=1), _CLERK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
