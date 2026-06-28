"""Validation/error paths: deposit mismatch, enrollment closed, no eligible cabin,
gender mismatch, referential mismatch, pagination, activity full, swim test, offer
expired, aid exceeds tuition, staff not cleared.

Corner queue: validations, endpoints, errors sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_director_headers, make_guardian_headers,
    ApiErrorId,
    setup_enrolling_session, setup_submitted_application, setup_deposit_paid_application,
    register_guardian, make_camper, make_health_form, submit_health_form,
    make_activity, book_activity, request_aid, make_camp, make_session, make_cabin,
    api_client,
)


# ===========================================================================
# Corner / validations
# ===========================================================================
def test_pay_deposit_amount_mismatch_rejected():
    """PRD §3.6: "it requires that the current clock be at or before `offer_expires_at`
    (otherwise `ERR_OFFER_EXPIRED`) and that the submitted `amount_cents` exactly equal
    the camp's `deposit_cents` (otherwise `ERR_DEPOSIT_AMOUNT_MISMATCH`)."

    Design: Corner/validations/deposit_amount_mismatch_returns_error
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    gc = setup_submitted_application(env, email="dm1@x.com")
    g_headers = make_guardian_headers(gc["guardian"]["id"])
    resp = api_client.pay_deposit(gc["application"]["id"], {"amount_cents": 20_000}, g_headers)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_AMOUNT_MISMATCH.value)


def test_submit_into_planning_session_rejected_enrollment_closed():
    """PRD §3.4: "the session must be in `ENROLLING` status with `enrollment_open`
    true (otherwise `ERR_ENROLLMENT_CLOSED`)".

    Design: Corner/validations/submit_into_planning_session_returns_enrollment_closed
    """
    # Build a PLANNING session (never opened) with a cabin and a submitted health form.
    camp = make_camp(deposit_cents=25_000)
    session = make_session(camp["id"])
    make_cabin(session["id"])
    guardian = register_guardian(email="ec1@x.com")
    g_id = guardian["id"]
    camper = make_camper(g_id, full_name="Kid", age=10, gender="BOY")
    hf = make_health_form(g_id, camper["id"])
    submit_health_form(g_id, hf["id"])
    app = get_success_data(api_client.create_application(
        {"camper_id": camper["id"], "session_id": session["id"]}, make_guardian_headers(g_id)))
    resp = api_client.submit_application(app["id"], make_guardian_headers(g_id))
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_CLOSED.value)


def test_submit_no_eligible_cabin_for_gender_rejected():
    """PRD §3.4: "the session must contain at least one cabin whose `gender_band`
    admits the camper's gender and whose inclusive age band from `min_age` to
    `max_age` contains the camper's age (otherwise `ERR_NO_ELIGIBLE_CABIN`)."

    Design: Corner/validations/submit_no_eligible_cabin_for_gender_returns_error
    """
    # only a GIRLS cabin; a BOY camper applies
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000},
                                  cabin_overrides={"name": "Rose", "gender_band": "GIRLS"})
    guardian = register_guardian(email="ne1@x.com")
    g_id = guardian["id"]
    camper = make_camper(g_id, full_name="Boy Kid", age=10, gender="BOY")
    hf = make_health_form(g_id, camper["id"])
    submit_health_form(g_id, hf["id"])
    app = get_success_data(api_client.create_application(
        {"camper_id": camper["id"], "session_id": env["session"]["id"]}, make_guardian_headers(g_id)))
    resp = api_client.submit_application(app["id"], make_guardian_headers(g_id))
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CABIN.value)


# ===========================================================================
# Corner / endpoints
# ===========================================================================
def test_assign_bunk_gender_mismatch_rejected():
    """PRD §3.6: "the cabin's `gender_band` must admit the camper's gender (otherwise
    `ERR_CABIN_GENDER_MISMATCH`)".

    Design: Corner/endpoints/assign_bunk_gender_mismatch_returns_error
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    director = make_director_headers()
    # add a GIRLS cabin to the same session; the BOYS cabin (env["cabin"]) made the camper eligible
    girls = make_cabin(env["session"]["id"], name="Rose", gender_band="GIRLS")
    gc = setup_deposit_paid_application(env, deposit_cents=25_000, email="gm1@x.com")
    girls_cabin = get_success_data(api_client.get_cabin(girls["id"], director))
    resp = api_client.assign_bunk(
        girls["id"],
        {"application_id": gc["application"]["id"], "expected_cabin_version": girls_cabin["version"]},
        director)
    validate_error(resp, ApiErrorId.ERR_CABIN_GENDER_MISMATCH.value)
    after = validate_success(api_client.get_cabin(girls["id"], director))
    assert after["occupied_bunks"] == 0, after["occupied_bunks"]


def test_assign_bunk_cabin_in_other_session_rejected_referential_mismatch():
    """PRD §3.6: "The cabin must belong to the same session as the application
    (otherwise `ERR_REFERENTIAL_MISMATCH`)".

    Design: Corner/endpoints/assign_bunk_cabin_in_other_session_returns_referential_mismatch
    """
    camp = make_camp(deposit_cents=25_000)
    director = make_director_headers()
    # session 1 (open) with a BOYS cabin; session 2 with another BOYS cabin
    sess1 = make_session(camp["id"], name="S1")
    make_cabin(sess1["id"])
    sess2 = make_session(camp["id"], name="S2", starts_on="2026-07-15T00:00:00Z",
                         ends_on="2026-07-28T00:00:00Z", visiting_day_on="2026-07-21T00:00:00Z")
    cab2 = make_cabin(sess2["id"], name="Oak")
    sess1 = get_success_data(api_client.open_enrollment(
        sess1["id"], {"expected_session_version": sess1["version"]}, director))
    env1 = {"camp": camp, "session": sess1, "cabin": None}
    gc = setup_deposit_paid_application(env1, deposit_cents=25_000, email="rm1@x.com")
    cab2_cur = get_success_data(api_client.get_cabin(cab2["id"], director))
    resp = api_client.assign_bunk(
        cab2["id"],
        {"application_id": gc["application"]["id"], "expected_cabin_version": cab2_cur["version"]},
        director)
    validate_error(resp, ApiErrorId.ERR_REFERENTIAL_MISMATCH.value)


def test_list_sessions_pagination_envelope():
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."
    PRD §2.3: "The `limit` parameter specifies the maximum number of items to return".

    Design: Corner/endpoints/list_sessions_pagination_envelope
    """
    camp = make_camp()
    director = make_director_headers()
    make_session(camp["id"], name="S1")
    make_session(camp["id"], name="S2", starts_on="2026-07-15T00:00:00Z",
                 ends_on="2026-07-28T00:00:00Z", visiting_day_on="2026-07-21T00:00:00Z")
    resp = api_client.list_sessions(camp["id"], director, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is True, meta["has_more"]
    assert len(data) == 1, len(data)


# ===========================================================================
# Corner / errors
# ===========================================================================
def test_activity_full_rejected():
    """PRD §3.8: "The booking must not push `seats_taken` beyond `seat_capacity`
    (otherwise `ERR_ACTIVITY_FULL`)."

    Design: Corner/errors/activity_full_returns_error
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    offering = make_activity(env["session"]["id"], name="Sailing", slot_day=1,
                             starts_minute=540, ends_minute=600, seat_capacity=1)
    gc_a = setup_submitted_application(env, email="fa1@x.com")
    book_activity(gc_a["guardian"]["id"], offering["id"], gc_a["application"]["id"])
    gc_b = setup_submitted_application(env, email="fb1@x.com")
    resp = api_client.create_activity_enrollment(
        {"offering_id": offering["id"], "application_id": gc_b["application"]["id"]},
        make_guardian_headers(gc_b["guardian"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ACTIVITY_FULL.value)


def test_swim_test_required_for_waterfront_offering_rejected():
    """PRD §3.8: "If the offering's `requires_swim_test` flag is true, the camper's
    `health_status` must be `CLEARED`, the waterfront gate (otherwise
    `ERR_SWIM_TEST_REQUIRED`)."

    Design: Corner/errors/swim_test_required_for_waterfront_offering
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    offering = make_activity(env["session"]["id"], name="Waterfront", slot_day=1,
                             starts_minute=540, ends_minute=600, seat_capacity=10,
                             requires_swim_test=True)
    # camper health PENDING (submitted, not cleared)
    gc = setup_submitted_application(env, email="sw1@x.com", clear_health=False)
    resp = api_client.create_activity_enrollment(
        {"offering_id": offering["id"], "application_id": gc["application"]["id"]},
        make_guardian_headers(gc["guardian"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SWIM_TEST_REQUIRED.value)


def test_offer_expired_pay_deposit_rejected():
    """PRD §3.6: "it requires that the current clock be at or before `offer_expires_at`
    (otherwise `ERR_OFFER_EXPIRED`)".
    PRD §3.4: "the system sets `offer_expires_at` to the current clock plus the camp's
    `deposit_grace_days`".

    Design: Corner/errors/offer_expired_pay_deposit_returns_error
    """
    # offer made at 2026-04-01, grace 7 days -> expires 2026-04-08; advance clock to 2026-04-10
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000, "deposit_grace_days": 7})
    gc = setup_submitted_application(env, email="oe1@x.com")
    director = make_director_headers()
    get_success_data(api_client.set_clock("2026-04-10T00:00:00Z", director))
    resp = api_client.pay_deposit(
        gc["application"]["id"], {"amount_cents": 25_000}, make_guardian_headers(gc["guardian"]["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED.value)


def test_aid_exceeds_tuition_rejected():
    """PRD §3.7: "that the requested `amount_cents` plus the aid already approved on
    the application not exceed the application's `list_tuition_cents` (otherwise
    `ERR_AID_EXCEEDS_TUITION`)".

    Design: Corner/errors/aid_exceeds_tuition_returns_error
    """
    env = setup_enrolling_session(camp_overrides={"deposit_cents": 25_000})
    gc = setup_submitted_application(env, email="ax1@x.com")  # list_tuition 370000 (early tier)
    g_id = gc["guardian"]["id"]
    app_id = gc["application"]["id"]
    aid = request_aid(g_id, app_id, 400_001, kind="MERIT_SCHOLARSHIP")
    director = make_director_headers()
    app_v = get_success_data(api_client.get_application(app_id, director))["version"]
    resp = api_client.approve_aid(aid["id"], {"expected_application_version": app_v}, director)
    validate_error(resp, ApiErrorId.ERR_AID_EXCEEDS_TUITION.value)


def test_staff_not_cleared_assignment_rejected():
    """PRD §3.2: "Assigning a staff member whose `is_background_cleared` is false is
    refused with `ERR_STAFF_NOT_CLEARED` — only background-cleared staff may be placed
    in a cabin."

    Design: Corner/errors/staff_not_cleared_assignment_returns_error
    """
    camp = make_camp()
    director = make_director_headers()
    sess = make_session(camp["id"])
    cab = make_cabin(sess["id"])
    staff = get_success_data(api_client.create_staff(
        camp["id"], {"full_name": "Uncleared", "role_kind": "COUNSELOR",
                     "is_background_cleared": False}, director))
    resp = api_client.create_cabin_assignment(
        {"cabin_id": cab["id"], "staff_member_id": staff["id"]}, director)
    validate_error(resp, ApiErrorId.ERR_STAFF_NOT_CLEARED.value)
