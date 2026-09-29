"""Conditional rules: gates read from the candidate's jurisdiction, the two
identity branches of check-in, third-entity authorization and the lead-time floor."""
from test_helpers import (
    add_candidate,
    add_provider,
    add_proctor,
    assign_code,
    factories as f,
    get_success_data,
    make_proctor_headers,
    purchase_batch,
    schedule_session,
    set_clock,
    setup_landscape,
    setup_sitting,
    validate_error,
    validate_paginated,
)


def _booking(env, candidate, code, proctor, delivery_mode, with_site):
    payload = f.create_exam_session_payload(
        candidate["id"], env["exam_form"]["id"], code["id"],
        "2026-09-10T09:00:00Z", delivery_mode=delivery_mode,
        proctor_id=proctor["id"])
    if with_site:
        payload["testing_site_id"] = env["testing_site"]["id"]
    return payload


def test_a_remote_booking_is_refused_by_the_candidates_own_jurisdiction(api):
    """The remote gate is read from the candidate's jurisdiction, so the identical
    booking is refused as REMOTE and accepted as IN_PERSON.

    PRD: "Three acceptance rules read the **candidate's own** jurisdiction, never the
    testing site's: the form's `accreditation_body` must appear in that jurisdiction's
    `accepted_accreditation_bodies` or the request answers
    `ERR_ACCREDITATION_NOT_ACCEPTED` (HTTP 422); the form's `language` must appear in
    its `accepted_languages` or the request answers `ERR_LANGUAGE_NOT_ACCEPTED` (HTTP
    422); and a `REMOTE` sitting requires that jurisdiction's
    `accepts_remote_proctoring` to be true or the request answers
    `ERR_REMOTE_PROCTORING_NOT_ACCEPTED` (HTTP 422)."

    Design: Corner/validations/remote_sitting_in_a_jurisdiction_that_refuses_remote_is_rejected
    """
    env = setup_landscape(jurisdiction={"accepts_remote_proctoring": False})
    admin, provider_headers = env["admin_headers"], env["provider_headers"]
    assert env["jurisdiction"]["accepts_remote_proctoring"] is False
    candidate = add_candidate(env)
    proctor = add_proctor(env, languages_certified=["EN"], remote_certified=True)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 2}])
    code, batch = assign_code(env, batch, candidate)

    refused = api.create_exam_session(
        _booking(env, candidate, code, proctor, "REMOTE", with_site=False),
        provider_headers)
    validate_error(refused, "ERR_REMOTE_PROCTORING_NOT_ACCEPTED", 422)
    assert get_success_data(api.get_access_code(
        code["id"], provider_headers))["status"] == "ASSIGNED"

    accepted = get_success_data(api.create_exam_session(
        _booking(env, candidate, code, proctor, "IN_PERSON", with_site=True),
        provider_headers), 201)

    assert accepted["delivery_mode"] == "IN_PERSON"
    assert accepted["allowed_minutes"] == 120
    assert accepted["testing_site_id"] == env["testing_site"]["id"]
    _, meta = validate_paginated(api.list_exam_sessions(
        admin, params={"candidate_id": candidate["id"]}))
    assert meta["total_count"] == 1
    assert get_success_data(api.get_proctor(
        proctor["id"], admin))["reserved_minutes"] == 120


def test_an_in_person_attestation_stands_in_for_the_biometric_score(api):
    """With no biometric_match_score at all, the proctor's own attestation carries
    the in-person identity check and the score is recorded as null.

    PRD: "An `IN_PERSON` sitting passes when either `proctor_attestation` is true or a
    supplied `biometric_match_score` is at least 85; a `proctor_attestation` of false
    paired with a score below 85 is likewise `ERR_IDENTITY_VERIFICATION_FAILED`."

    PRD: "On success the sitting moves `SCHEDULED → CHECKED_IN`, both
    `identity_verified_at` and `checked_in_at` are set to the logical clock, and the
    presented `id_document_type`, `id_document_expires_on` and
    `biometric_match_score` are recorded on the sitting."

    Design: Corner/validations/in_person_attestation_substitutes_for_the_biometric_score
    """
    env = setup_sitting(stage="SCHEDULED")
    set_clock("2026-09-10T08:45:00Z", env["admin_headers"])

    checked_in = get_success_data(api.check_in_exam_session(
        env["session"]["id"],
        f.create_check_in_payload(id_document_type="GOVT_PHOTO_ID",
                                  id_document_expires_on="2028-03-31"),
        env["proctor_headers"]))

    assert checked_in["session_status"] == "CHECKED_IN"
    assert checked_in["checked_in_at"] == "2026-09-10T08:45:00Z"
    assert checked_in["identity_verified_at"] == "2026-09-10T08:45:00Z"
    assert checked_in["biometric_match_score"] is None
    assert checked_in["proctor_attestation"] is True
    assert checked_in["id_document_type"] == "GOVT_PHOTO_ID"
    assert checked_in["id_document_expires_on"] == "2028-03-31"
    assert checked_in["proctoring_status"] == "ASSIGNED"


def test_an_expired_document_outranks_the_failing_biometric_score(api):
    """Both identity rules are broken at once; priority 21 must answer, and the same
    call with a live document proves priority 23 was live all along.

    PRD: "The proctor supplies the `id_document_type` presented — `GOVT_PHOTO_ID`,
    `PASSPORT` or `MILITARY_ID` — and the `id_document_expires_on` date in
    `YYYY-MM-DD` form, which must be on or after the logical clock's own date; a
    document expiring on or before that date is rejected with
    `ERR_ID_DOCUMENT_EXPIRED` (HTTP 422)."

    PRD: "21. The presented identity document has not expired —
    `ERR_ID_DOCUMENT_EXPIRED`."

    PRD: "23. The supplied biometric score clears the minimum —
    `ERR_IDENTITY_VERIFICATION_FAILED`."

    Design: Corner/validations/expired_id_outranks_a_failing_biometric_score
    """
    env = setup_sitting(stage="SCHEDULED")
    admin = env["admin_headers"]
    set_clock("2026-09-10T08:45:00Z", admin)

    both_broken = api.check_in_exam_session(
        env["session"]["id"],
        f.create_check_in_payload(id_document_expires_on="2026-08-31",
                                  biometric_match_score=40,
                                  proctor_attestation=False),
        env["proctor_headers"])
    validate_error(both_broken, "ERR_ID_DOCUMENT_EXPIRED", 422)

    score_only = api.check_in_exam_session(
        env["session"]["id"],
        f.create_check_in_payload(id_document_expires_on="2030-01-31",
                                  biometric_match_score=40,
                                  proctor_attestation=False),
        env["proctor_headers"])
    validate_error(score_only, "ERR_IDENTITY_VERIFICATION_FAILED", 422)

    session = get_success_data(api.get_exam_session(env["session"]["id"], admin))
    assert session["session_status"] == "SCHEDULED"
    assert session["checked_in_at"] is None
    assert session["identity_verified_at"] is None
    assert session["id_document_type"] is None
    assert session["biometric_match_score"] is None


def test_only_the_owning_providers_instructor_may_sign_the_course_off(api):
    """Authorization is read off a third entity: an equally REGISTERED instructor at
    another provider is refused, and the owning provider's instructor succeeds.

    PRD: "The sign-off names the `course_instructor_proctor_id` of the person
    attesting, and three things must be true of that person: `INSTRUCTOR` appears in
    their `roles_held`, their `registration_status` is `REGISTERED`, and their
    `training_provider_id` matches the provider that bought the code's batch."

    PRD: "A failure of the role or provider condition is rejected with
    `ERR_INSTRUCTOR_NOT_AUTHORIZED` (HTTP 422), and a signer who is not `REGISTERED`
    is rejected with `ERR_PROCTOR_NOT_REGISTERED` (HTTP 409)."

    Design: Corner/validations/course_signoff_by_another_providers_instructor_is_rejected
    """
    env = setup_landscape()
    admin, provider_a_headers = env["admin_headers"], env["provider_headers"]
    provider_b = add_provider(env, prepay_cents=500000)
    instructor_a = add_proctor(env)
    instructor_b = add_proctor(env, provider=provider_b)
    assert "INSTRUCTOR" in instructor_b["roles_held"]
    assert instructor_b["registration_status"] == "REGISTERED"
    candidate = add_candidate(env)
    batch = purchase_batch(
        env, line_items=[{"bundle_type": "COURSE_PLUS_EXAM", "quantity": 1}])
    assert batch["total_price_cents"] == 9301
    assert get_success_data(api.get_training_provider(
        env["provider"]["id"], admin))["credit_balance_cents"] == 490699
    code, batch = assign_code(env, batch, candidate, bundle_type="COURSE_PLUS_EXAM")

    refused = api.complete_course(
        code["id"], f.create_course_completion_payload(instructor_b["id"]),
        provider_a_headers)
    validate_error(refused, "ERR_INSTRUCTOR_NOT_AUTHORIZED", 422)
    untouched = get_success_data(api.get_access_code(code["id"], provider_a_headers))
    assert untouched["course_completed_at"] is None
    assert untouched["course_instructor_proctor_id"] is None

    signed = get_success_data(api.complete_course(
        code["id"], f.create_course_completion_payload(instructor_a["id"]),
        provider_a_headers))

    assert signed["course_completed_at"] == "2026-08-01T00:00:00Z"
    assert signed["course_instructor_proctor_id"] == instructor_a["id"]
    assert signed["status"] == "ASSIGNED"


def test_the_lead_time_floor_is_re_applied_on_every_reschedule(api):
    """A move to 18 hours out is refused without bumping the version, and a move a
    day later than the original slot succeeds and counts the reschedule.

    PRD: "The sitting's `session_status` must still be `SCHEDULED` — re-timing a
    `CANCELLED` or `INVALIDATED` sitting answers `ERR_SESSION_STATE_INVALID` (HTTP
    409) — the candidate must not be on `security_hold`, the new start must again
    clear the 24-hour lead-time floor, the jurisdiction must still accept the delivery
    mode, and the proctor, site and mode-pairing capability rules all apply again with
    the same error codes as at creation."

    PRD: "On success `scheduled_start_at` is replaced, `allowed_minutes` and
    `scheduled_end_at` are recomputed by the rule above, `reschedule_count` grows by
    one, the released interval is deducted from the site's `reserved_seat_minutes` and
    the proctor's `reserved_minutes` before the new interval is reserved, a supplied
    `proctor_id` moves `proctoring_status` `PENDING_REPROCTOR → ASSIGNED`, and the
    sitting's `version` increments by one."

    Design: Corner/validations/reschedule_inside_the_lead_time_window_is_rejected
    """
    env = setup_sitting(stage="SCHEDULED")
    admin, site_id = env["admin_headers"], env["testing_site"]["id"]
    session = env["session"]
    first_version = session["version"]

    refused = api.reschedule_exam_session(
        session["id"],
        f.create_reschedule_payload("2026-08-01T18:00:00Z", first_version),
        env["provider_headers"])
    validate_error(refused, "ERR_SCHEDULE_LEAD_TIME_TOO_SHORT", 422)

    unchanged = get_success_data(api.get_exam_session(session["id"], admin))
    assert unchanged["scheduled_start_at"] == "2026-09-10T09:00:00Z"
    assert unchanged["reschedule_count"] == 0
    assert unchanged["version"] == first_version
    assert get_success_data(api.get_testing_site(
        site_id, admin))["reserved_seat_minutes"] == 120
    assert get_success_data(api.get_proctor(
        env["proctor"]["id"], admin))["reserved_minutes"] == 120

    moved = get_success_data(api.reschedule_exam_session(
        session["id"],
        f.create_reschedule_payload("2026-09-11T09:00:00Z", first_version),
        env["provider_headers"]))

    assert moved["scheduled_start_at"] == "2026-09-11T09:00:00Z"
    assert moved["scheduled_end_at"] == "2026-09-11T11:00:00Z"
    assert moved["allowed_minutes"] == 120
    assert moved["reschedule_count"] == 1
    assert moved["version"] == first_version + 1
    assert get_success_data(api.get_testing_site(
        site_id, admin))["reserved_seat_minutes"] == 120
    assert get_success_data(api.get_proctor(
        env["proctor"]["id"], admin))["reserved_minutes"] == 120


def test_the_biometric_score_is_demanded_only_by_the_remote_sitting(api):
    """One check-in body, two sittings: it passes in person and is refused remotely
    until the score is supplied.

    PRD: "A `REMOTE` sitting **must** carry a `biometric_match_score` — omitting it is
    rejected with `ERR_BIOMETRIC_REQUIRED_FOR_REMOTE` (HTTP 422) — and that score must
    be at least 85, with anything below rejected as `ERR_IDENTITY_VERIFICATION_FAILED`
    (HTTP 422)."

    PRD: "The delivery allowance is 10 minutes of remote setup time for a `REMOTE`
    sitting and zero for an `IN_PERSON` one."

    Design: Corner/validations/biometric_score_is_required_only_when_the_sitting_is_remote
    """
    env = setup_landscape()
    admin = env["admin_headers"]
    proctor = add_proctor(env, languages_certified=["EN"], remote_certified=True)
    proctor_headers = make_proctor_headers(proctor["id"])
    first_candidate = add_candidate(env)
    second_candidate = add_candidate(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 2}])
    first_code, batch = assign_code(env, batch, first_candidate)
    second_code, batch = assign_code(env, batch, second_candidate)

    in_person = schedule_session(env, first_candidate, first_code,
                                 "2026-09-10T09:00:00Z", proctor=proctor)
    remote = schedule_session(env, second_candidate, second_code,
                              "2026-09-10T14:00:00Z", proctor=proctor,
                              delivery_mode="REMOTE", testing_site=None)
    assert in_person["allowed_minutes"] == 120
    assert remote["allowed_minutes"] == 130
    assert remote["scheduled_end_at"] == "2026-09-10T16:10:00Z"
    assert get_success_data(api.get_proctor(
        proctor["id"], admin))["reserved_minutes"] == 250

    body = f.create_check_in_payload(id_document_expires_on="2030-01-31")
    set_clock("2026-09-10T08:45:00Z", admin)
    assert get_success_data(api.check_in_exam_session(
        in_person["id"], dict(body), proctor_headers))["session_status"] == "CHECKED_IN"

    set_clock("2026-09-10T13:45:00Z", admin)
    refused = api.check_in_exam_session(remote["id"], dict(body), proctor_headers)
    validate_error(refused, "ERR_BIOMETRIC_REQUIRED_FOR_REMOTE", 422)
    assert get_success_data(api.get_exam_session(
        remote["id"], admin))["session_status"] == "SCHEDULED"

    with_score = dict(body, biometric_match_score=91)
    verified = get_success_data(api.check_in_exam_session(
        remote["id"], with_score, proctor_headers))

    assert verified["session_status"] == "CHECKED_IN"
    assert verified["biometric_match_score"] == 91
    assert verified["checked_in_at"] == "2026-09-10T13:45:00Z"
