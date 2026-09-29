"""Transitions whose legality lives on a different entity: the sitting on its
proctor's registration, the filing on its certificate, check-in on its code."""
from test_helpers import (
    TEST_USERS,
    add_candidate,
    add_proctor,
    assign_code,
    factories as f,
    file_local_registration,
    get_success_data,
    purchase_batch,
    run_compliance,
    set_clock,
    setup_landscape,
    setup_sitting,
    shift_iso,
    sign_off_course,
    validate_error,
    validate_paginated,
    validate_success,
)

_SLOT = "2026-09-10T09:00:00Z"


def _pending_proctor_env(api):
    env = setup_landscape()
    candidate = add_candidate(env)
    proctor = add_proctor(env, registered=False, languages_certified=["EN"],
                          remote_certified=False)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}])
    code, batch = assign_code(env, batch, candidate)
    env.update({"candidate": candidate, "proctor": proctor, "access_code": code,
                "batch": batch})
    return env


def _session_payload(env):
    return f.create_exam_session_payload(
        env["candidate"]["id"], env["exam_form"]["id"], env["access_code"]["id"],
        _SLOT, delivery_mode="IN_PERSON",
        testing_site_id=env["testing_site"]["id"],
        proctor_id=env["proctor"]["id"])


def test_scheduling_is_refused_until_the_proctors_registration_is_approved(api):
    """The identical create fails while the proctor is PENDING and succeeds the
    moment the accrediting body approves the registration.

    PRD: "The form must still be `ACTIVE`; the candidate's `security_hold` must be
    false; a supplied proctor must be `REGISTERED`; the redeemed code's `status`
    must be `ASSIGNED`, and anything else answers
    `ERR_ACCESS_CODE_STATE_INVALID`."

    PRD: "20. The proctor being relied on is `REGISTERED` —
    `ERR_PROCTOR_NOT_REGISTERED`."

    PRD: "`APPROVE` advances `PENDING → REGISTERED` and resets `risk_score` to
    0.00 with `risk_variant_applied` `ROLLING_WINDOW`."

    Design: Difficulty/cross_entity_state_dependency/session_scheduling_depends_on_proctor_registration_state
    """
    env = _pending_proctor_env(api)
    assert env["proctor"]["registration_status"] == "PENDING"

    refused = api.create_exam_session(_session_payload(env), env["provider_headers"])
    validate_error(refused, "ERR_PROCTOR_NOT_REGISTERED", 409)
    assert get_success_data(api.get_access_code(
        env["access_code"]["id"], env["provider_headers"]))["status"] == "ASSIGNED"

    validate_success(api.decide_proctor_registration(
        env["proctor"]["id"], f.create_registration_decision_payload("APPROVE"),
        env["admin_headers"]))

    session = get_success_data(api.create_exam_session(
        _session_payload(env), env["provider_headers"]), 201)
    assert session["session_status"] == "SCHEDULED"
    assert session["proctoring_status"] == "ASSIGNED"
    assert session["allowed_minutes"] == 120
    assert session["scheduled_end_at"] == "2026-09-10T11:00:00Z"
    assert get_success_data(api.get_proctor(
        env["proctor"]["id"], env["admin_headers"]))["reserved_minutes"] == 120


def test_the_sitting_follows_its_proctor_out_of_the_registered_state(api):
    """A suspension pushes the still-SCHEDULED sitting into PENDING_REPROCTOR and
    hands the held minutes back, without touching session_status.

    PRD: "Every one of that proctor's sittings whose `session_status` is
    `SCHEDULED` and whose `proctoring_status` is `ASSIGNED` moves `ASSIGNED →
    PENDING_REPROCTOR`, has its `proctor_id` cleared to null, and decrements that
    proctor's `reserved_minutes` by the sitting's own `allowed_minutes`."

    Design: Difficulty/cross_entity_state_dependency/session_scheduling_depends_on_proctor_registration_state
    """
    env = setup_sitting(stage="SCHEDULED")
    admin = env["admin_headers"]
    proctor_id = env["proctor"]["id"]
    assert get_success_data(api.get_proctor(proctor_id, admin))["reserved_minutes"] == 120

    validate_success(api.open_proctor_audit(
        proctor_id, f.create_audit_open_payload(
            audit_reason="Complaint about roster handling"), admin))
    suspended = get_success_data(api.close_proctor_audit(
        proctor_id, f.create_audit_close_payload(
            outcome="SUSPEND", audit_note="Roster paperwork missing"), admin))

    assert suspended["registration_status"] == "SUSPENDED"
    assert suspended["suspended_reason"] == "AUDIT_FAILURE"
    assert float(suspended["risk_score"]) == 0.00
    assert suspended["reserved_minutes"] == 0

    session = get_success_data(api.get_exam_session(env["session"]["id"], admin))
    assert session["proctoring_status"] == "PENDING_REPROCTOR"
    assert session["session_status"] == "SCHEDULED"
    assert session["proctor_id"] is None


def test_filing_a_registration_requires_a_live_certificate(api):
    """A filing lands while the certificate is ISSUED, and the very same body is
    refused once the compliance run has expired that certificate.

    PRD: "The certificate's `status` must be `ISSUED`; filing against a `REVOKED`
    or `SUPERSEDED` certificate answers `ERR_CERTIFICATE_STATE_INVALID`."

    PRD: "On success the registration opens with `status` `FILED`, `filed_at` set
    to the logical clock, `refile_count` at zero, and `posting_deadline_at`
    computed as `filed_at` advanced by the jurisdiction's `posting_deadline_days`
    days"

    Design: Difficulty/cross_entity_state_dependency/local_registration_filing_depends_on_certificate_state
    """
    env = setup_sitting(stage="CERTIFIED", scored_correct_count=60,
                        scoring_admin_headers=TEST_USERS["scoring_admin_headers"])
    admin = env["admin_headers"]
    certificate = env["certificate"]
    assert certificate["status"] == "ISSUED"

    registration = file_local_registration(env, certificate)
    assert registration["status"] == "FILED"
    assert registration["refile_count"] == 0
    assert registration["jurisdiction_id"] == env["jurisdiction"]["id"]
    assert registration["posting_deadline_at"] == shift_iso(
        registration["filed_at"], days=30)

    set_clock(certificate["expires_at"], admin)
    summary = run_compliance(env)
    assert summary["certificates_expired_count"] == 1
    assert get_success_data(api.get_certificate(
        certificate["id"], admin))["status"] == "EXPIRED"

    refused = api.create_local_registration(
        f.create_local_registration_payload(
            certificate["id"], establishment_name="Blue Cafe Second Location",
            establishment_address="7 Lamar Blvd"),
        env["provider_headers"])
    validate_error(refused, "ERR_CERTIFICATE_STATE_INVALID", 409)


def test_the_expiry_run_withdraws_the_filing_it_can_no_longer_support(api):
    """The same certificate/registration pair is coupled in the other direction:
    expiry withdraws the filing instead of marking it delinquent.

    PRD: "Every local registration whose `status` is `FILED`, whose `posted_at` is
    still null, and whose `posting_deadline_at` falls strictly before `run_epoch`
    moves `FILED → DELINQUENT`."

    PRD: "its holder's `compliance_status` drops to `LAPSED`, and its local
    registrations in `FILED`, `POSTED`, `VERIFIED` or `DELINQUENT` move to
    `WITHDRAWN`"

    Design: Difficulty/cross_entity_state_dependency/local_registration_filing_depends_on_certificate_state
    """
    env = setup_sitting(stage="FILED", scored_correct_count=60,
                        scoring_admin_headers=TEST_USERS["scoring_admin_headers"])
    admin = env["admin_headers"]
    registration = env["local_registration"]
    assert registration["status"] == "FILED"

    set_clock(env["certificate"]["expires_at"], admin)
    summary = run_compliance(env)

    assert summary["registrations_delinquent_count"] == 0
    assert get_success_data(api.get_local_registration(
        registration["id"], admin))["status"] == "WITHDRAWN"
    assert get_success_data(api.get_candidate(
        env["candidate"]["id"], admin))["compliance_status"] == "LAPSED"

    _, meta = validate_paginated(api.list_local_registrations(
        admin, params={"certificate_id": env["certificate"]["id"]}))
    assert meta["total_count"] == 1


def test_check_in_on_a_bundled_code_is_refused_before_the_course_is_signed_off(api):
    """The code's bundle_type, not any field of the sitting, gates check-in.

    PRD: "the redeemed code must either carry `bundle_type` `EXAM_ONLY` or have a
    non-null `course_completed_at`, and a candidate arriving on a
    `COURSE_PLUS_EXAM` code whose course was never signed off is turned away with
    `ERR_COURSE_NOT_COMPLETED` (HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/checkin_depends_on_bundled_access_code_course_completion_state
    """
    env = setup_sitting(stage="SCHEDULED", bundle_type="COURSE_PLUS_EXAM",
                        auto_sign_off=False)
    admin = env["admin_headers"]
    assert env["access_code"]["bundle_type"] == "COURSE_PLUS_EXAM"
    assert env["access_code"]["course_completed_at"] is None
    assert env["batch"]["total_price_cents"] == 9301
    assert env["batch"]["quantity_purchased"] == 1

    set_clock("2026-09-10T08:45:00Z", admin)
    refused = api.check_in_exam_session(
        env["session"]["id"], f.create_check_in_payload(),
        env["proctor_headers"])
    validate_error(refused, "ERR_COURSE_NOT_COMPLETED", 409)

    session = get_success_data(api.get_exam_session(env["session"]["id"], admin))
    assert session["session_status"] == "SCHEDULED"
    assert session["checked_in_at"] is None
    assert session["identity_verified_at"] is None


def test_the_instructors_sign_off_unblocks_the_same_check_in(api):
    """Signing the course off stamps the code and the retried check-in passes,
    while the code itself is still only ASSIGNED.

    PRD: "Sign-off is only permitted while the code's `status` is `AVAILABLE` or
    `ASSIGNED`; the code stays in whichever of those two states it was in, and
    only `course_completed_at` — set to the logical clock — and
    `course_instructor_proctor_id` change."

    PRD: "It stays `ASSIGNED` right up to submission, which is what lets a
    cancellation from `CHECKED_IN` return the code to the batch intact."

    Design: Difficulty/cross_entity_state_dependency/checkin_depends_on_bundled_access_code_course_completion_state
    """
    env = setup_sitting(stage="SCHEDULED", bundle_type="COURSE_PLUS_EXAM",
                        auto_sign_off=False)
    admin = env["admin_headers"]
    set_clock("2026-09-10T08:45:00Z", admin)

    signed = sign_off_course(env, env["access_code"], env["proctor"])
    assert signed["course_completed_at"] == "2026-09-10T08:45:00Z"
    assert signed["course_instructor_proctor_id"] == env["proctor"]["id"]
    assert signed["status"] == "ASSIGNED"

    checked_in = get_success_data(api.check_in_exam_session(
        env["session"]["id"], f.create_check_in_payload(), env["proctor_headers"]))
    assert checked_in["session_status"] == "CHECKED_IN"
    assert checked_in["identity_verified_at"] == "2026-09-10T08:45:00Z"
    assert checked_in["proctoring_status"] == "ASSIGNED"

    code = get_success_data(api.get_access_code(
        env["access_code"]["id"], env["provider_headers"]))
    assert code["status"] == "ASSIGNED"
    assert get_success_data(api.get_access_code_batch(
        env["batch"]["id"], env["provider_headers"]))["consumed_count"] == 0
