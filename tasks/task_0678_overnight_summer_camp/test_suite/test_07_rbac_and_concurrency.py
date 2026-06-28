"""Role-based access control, ownership, authentication, and optimistic-concurrency
(OCC) supersede races.

Corner queue: rbac section + cross_cutting_complexity_layers OCC instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_director_headers, make_nurse_headers, make_guardian_headers,
    ApiErrorId,
    setup_enrolling_session, setup_submitted_application, setup_deposit_paid_application,
    register_guardian, make_camper, make_health_form, submit_health_form,
    request_aid, make_camp, make_session, make_cabin,
    api_client,
)


# ===========================================================================
# Corner / rbac
# ===========================================================================
def test_guardian_cannot_enroll_application():
    """PRD §2.1: "When a well-authenticated caller invokes an operation their role is
    not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: enrolling a deposit-paid application is a CampDirector operation
    (`POST /applications/{id}/enroll` — CampDirector).

    Design: Corner/rbac/guardian_cannot_enroll_application
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    gc = setup_deposit_paid_application(env, deposit_cents=25_000, email="fr1@x.com")
    g_headers = make_guardian_headers(gc["guardian"]["id"])
    resp = api_client.enroll_application(gc["application"]["id"], g_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_nurse_cannot_open_enrollment_peer_role_denied():
    """PRD §2.1: "When a well-authenticated caller invokes an operation their role is
    not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: opening enrollment is a CampDirector operation
    (`POST /sessions/{id}/open-enrollment` — CampDirector).

    Design: Corner/rbac/nurse_cannot_clear_other_camps_aside_is_peer_role_denied_on_enroll
    """
    camp = make_camp()
    director = make_director_headers()
    sess = make_session(camp["id"])
    make_cabin(sess["id"])
    nurse = make_nurse_headers()
    resp = api_client.open_enrollment(sess["id"], {"expected_session_version": sess["version"]}, nurse)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_guardian_cannot_act_on_other_guardians_application():
    """PRD §2.1: "A `Guardian` may act only within their own ownership chain; an
    attempt to act on a camper, application, health form, or payment they do not own
    is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/guardian_cannot_act_on_other_guardians_application
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    # Guardian-1 owns an OFFERED application.
    gc1 = setup_submitted_application(env, email="own1@x.com")
    # Guardian-2 is a different registered guardian.
    g2 = register_guardian(email="own2@x.com")
    resp = api_client.pay_deposit(
        gc1["application"]["id"], {"amount_cents": 25_000}, make_guardian_headers(g2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_auth_headers_returns_unauthenticated():
    """PRD §2.1: "A request missing or malformed in either header — on any endpoint
    that requires authentication — is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    director = make_director_headers()
    get_success_data(api_client.set_clock("2026-04-01T00:00:00Z", director))
    # POST /campers with no auth headers
    resp = api_client._request("POST", "/campers",
                               {"full_name": "Kid", "age": 10, "gender": "BOY"},
                               headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Corner / cross_cutting_complexity_layers — OCC
# ===========================================================================
def test_bunk_assign_stale_cabin_version_rejected():
    """PRD §2.8: "If another assignment has consumed a bunk and advanced the cabin's
    `version` since the client read it, the client's view of the remaining bunk
    capacity is out of date; the request is therefore rejected with
    `ERR_STALE_VERSION` and HTTP 412".

    Design: Corner/cross_cutting_complexity_layers/occ_bunk_assign_stale_cabin_version_returns_412
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    director = make_director_headers()
    cabin_id = env["cabin"]["id"]
    gc_a = setup_deposit_paid_application(env, deposit_cents=25_000, email="oa1@x.com")
    gc_b = setup_deposit_paid_application(env, deposit_cents=25_000, email="ob1@x.com")

    # observe cabin version BEFORE any assignment
    cab_pre = get_success_data(api_client.get_cabin(cabin_id, director))["version"]
    # first assignment consumes a bunk and advances version
    get_success_data(api_client.assign_bunk(
        cabin_id, {"application_id": gc_a["application"]["id"], "expected_cabin_version": cab_pre},
        director))
    # second assignment with the stale pre-assignment version -> rejected
    resp = api_client.assign_bunk(
        cabin_id, {"application_id": gc_b["application"]["id"], "expected_cabin_version": cab_pre},
        director)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_aid_approve_stale_application_version_rejected():
    """PRD §2.8: "If another award was approved in the interim, the application's
    `version` has advanced and the approver's snapshot of remaining tuition headroom
    is stale; the approval is rejected with `ERR_STALE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_aid_approve_stale_application_version_returns_412
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    gc = setup_submitted_application(env, email="oc1@x.com")  # list_tuition 370000
    g_id = gc["guardian"]["id"]
    app_id = gc["application"]["id"]
    aid1 = request_aid(g_id, app_id, 100_000, kind="NEED_GRANT")
    aid2 = request_aid(g_id, app_id, 100_000, kind="MERIT_SCHOLARSHIP")
    director = make_director_headers()

    app_pre = get_success_data(api_client.get_application(app_id, director))["version"]
    # approve aid1 -> advances application version
    get_success_data(api_client.approve_aid(
        aid1["id"], {"expected_application_version": app_pre}, director))
    # approve aid2 with the stale pre-approval version -> rejected
    resp = api_client.approve_aid(aid2["id"], {"expected_application_version": app_pre}, director)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
