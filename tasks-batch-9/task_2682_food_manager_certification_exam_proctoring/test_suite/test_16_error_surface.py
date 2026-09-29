"""Entity-specific 404s, pagination bounds, and the batch, accommodation, incident
and scheduling rejection families."""
from test_helpers import (
    TEST_USERS,
    add_candidate,
    add_exam_form,
    add_proctor,
    add_testing_site,
    assign_code,
    factories as f,
    file_incident,
    get_success_data,
    purchase_batch,
    read_batch,
    set_clock,
    setup_landscape,
    setup_sitting,
    take_incident_into_review,
    validate_error,
    validate_paginated,
)

_ALT_ADMIN = TEST_USERS["platform_admin_alt_headers"]
_SECURITY_ADMIN = TEST_USERS["security_admin_headers"]

_GHOST = {
    "jurisdiction": "11111111-1111-4111-8111-111111111111",
    "provider": "22222222-2222-4222-8222-222222222222",
    "form": "33333333-3333-4333-8333-333333333333",
    "site": "44444444-4444-4444-8444-444444444444",
    "candidate": "55555555-5555-4555-8555-555555555555",
    "proctor": "66666666-6666-4666-8666-666666666666",
    "batch": "77777777-7777-4777-8777-777777777777",
    "code": "88888888-8888-4888-8888-888888888888",
    "accommodation": "99999999-9999-4999-8999-999999999999",
    "session": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "report": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "incident": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    "registration": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
}


def test_every_unresolvable_id_names_the_entity_that_failed_to_resolve(api):
    """Thirteen bogus path ids answer thirteen distinct 404s, and a body carrying
    three bad foreign keys reports the leftmost one.

    PRD: "The not-found identifier reported at priorities 6 and 7 is the one matching
    the entity that failed to resolve, and there is one per entity type:
    `ERR_JURISDICTION_NOT_FOUND`, `ERR_TRAINING_PROVIDER_NOT_FOUND`,
    `ERR_EXAM_FORM_NOT_FOUND`, `ERR_TESTING_SITE_NOT_FOUND`,
    `ERR_CANDIDATE_NOT_FOUND`, `ERR_PROCTOR_NOT_FOUND` (covering `proctor_id`,
    `reported_by_proctor_id` and `course_instructor_proctor_id` alike),
    `ERR_ACCESS_CODE_BATCH_NOT_FOUND`, `ERR_ACCESS_CODE_NOT_FOUND`,
    `ERR_ACCOMMODATION_REQUEST_NOT_FOUND`, `ERR_EXAM_SESSION_NOT_FOUND`,
    `ERR_SCORE_REPORT_NOT_FOUND`, `ERR_SECURITY_INCIDENT_NOT_FOUND`,
    `ERR_CERTIFICATE_NOT_FOUND` and `ERR_LOCAL_REGISTRATION_NOT_FOUND`."

    PRD: "Body foreign keys resolve, validated in the order the fields appear in that
    endpoint's input list — the matching `ERR_..._NOT_FOUND`."

    Design: Corner/errors/every_bogus_path_id_and_body_fk_returns_its_entity_specific_not_found
    """
    env = setup_landscape(with_site=False)
    admin, provider_headers = env["admin_headers"], env["provider_headers"]
    candidate = add_candidate(env)

    probes = [
        (api.get_jurisdiction, "jurisdiction", "ERR_JURISDICTION_NOT_FOUND"),
        (api.get_training_provider, "provider", "ERR_TRAINING_PROVIDER_NOT_FOUND"),
        (api.get_exam_form, "form", "ERR_EXAM_FORM_NOT_FOUND"),
        (api.get_testing_site, "site", "ERR_TESTING_SITE_NOT_FOUND"),
        (api.get_candidate, "candidate", "ERR_CANDIDATE_NOT_FOUND"),
        (api.get_proctor, "proctor", "ERR_PROCTOR_NOT_FOUND"),
        (api.get_access_code_batch, "batch", "ERR_ACCESS_CODE_BATCH_NOT_FOUND"),
        (api.get_access_code, "code", "ERR_ACCESS_CODE_NOT_FOUND"),
        (api.get_accommodation_request, "accommodation",
         "ERR_ACCOMMODATION_REQUEST_NOT_FOUND"),
        (api.get_exam_session, "session", "ERR_EXAM_SESSION_NOT_FOUND"),
        (api.get_score_report, "report", "ERR_SCORE_REPORT_NOT_FOUND"),
        (api.get_security_incident, "incident", "ERR_SECURITY_INCIDENT_NOT_FOUND"),
        (api.get_local_registration, "registration",
         "ERR_LOCAL_REGISTRATION_NOT_FOUND"),
    ]
    for getter, key, error_id in probes:
        response = getter(_GHOST[key], admin)
        validate_error(response, error_id, 404)
        body = response.json()
        assert body["response_type"] == "error"
        assert set(body["data"].keys()) == {"error_id", "message"}
        assert body["data"]["message"]

    all_bogus = api.create_exam_session(
        f.create_exam_session_payload(
            _GHOST["candidate"], _GHOST["form"], _GHOST["code"],
            "2026-09-12T09:00:00Z", delivery_mode="REMOTE"),
        provider_headers)
    validate_error(all_bogus, "ERR_CANDIDATE_NOT_FOUND", 404)

    candidate_fixed = api.create_exam_session(
        f.create_exam_session_payload(
            candidate["id"], _GHOST["form"], _GHOST["code"],
            "2026-09-12T09:00:00Z", delivery_mode="REMOTE"),
        provider_headers)
    validate_error(candidate_fixed, "ERR_EXAM_FORM_NOT_FOUND", 404)

    _, meta = validate_paginated(api.list_exam_sessions(
        admin, params={"candidate_id": candidate["id"]}))
    assert meta["total_count"] == 0


def test_pagination_bounds_are_refused_rather_than_clamped(api):
    """limit is a closed [1, 100] range and offset must not be negative; illegal
    windows are 400s, and the legal windows report matches rather than page size.

    PRD: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100."

    PRD: "A `limit` outside the inclusive range 1 through 100, or a negative `offset`,
    is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/errors/list_pagination_outside_bounds_is_rejected_before_any_row_is_read
    """
    env = setup_landscape(with_site=False)
    admin = env["admin_headers"]
    add_exam_form(env, form_code="FM-EN-02", version_label="2026.2")

    validate_error(api.list_exam_forms(admin, params={"limit": 0}),
                   "ERR_INVALID_PAGINATION", 400)
    validate_error(api.list_exam_forms(admin, params={"limit": 101}),
                   "ERR_INVALID_PAGINATION", 400)
    validate_error(api.list_exam_forms(admin, params={"offset": -1}),
                   "ERR_INVALID_PAGINATION", 400)
    validate_error(api.list_candidates(admin, params={"limit": 0, "offset": -1}),
                   "ERR_INVALID_PAGINATION", 400)

    rows, meta = validate_paginated(api.list_exam_forms(
        admin, params={"limit": 100, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(rows) == 2

    page, page_meta = validate_paginated(api.list_exam_forms(
        admin, params={"limit": 1, "offset": 1}))
    assert page_meta["total_count"] == 2
    assert page_meta["has_more"] is False
    assert len(page) == 1


def test_a_batch_can_be_depleted_expired_or_voided_and_each_says_so(api):
    """One mixed batch and one clock-expired batch produce three different batch
    rejections, and the void of an expired-but-ACTIVE batch still succeeds.

    PRD: "The code actually handed out is chosen deterministically: among the batch's
    codes that are still `AVAILABLE` and carry the requested `bundle_type`, the one with
    the earliest `created_at` wins, and when no such code exists the request is rejected
    with `ERR_BATCH_DEPLETED` even if the batch holds available codes of the other
    bundle type."

    PRD: "A clock past `expires_at`, or a batch already `EXPIRED`, is rejected with
    `ERR_BATCH_EXPIRED` (HTTP 409); an exhausted batch with `ERR_BATCH_DEPLETED` (HTTP
    409); a batch that is `VOIDED` with `ERR_BATCH_STATE_INVALID` (HTTP 409); a
    candidate on hold with `ERR_CANDIDATE_SECURITY_HOLD` (HTTP 409)."

    PRD: "The request supplies a free-text `reason` and `expected_batch_version`, and
    requires the batch `status` to be `ACTIVE` with an `available_count` of at least 1 —
    voiding a `VOIDED` or `EXPIRED` batch answers `ERR_BATCH_STATE_INVALID`, and voiding
    a batch with nothing left available answers `ERR_BATCH_DEPLETED`."

    Design: Corner/errors/batch_assignment_rejections_bundle_depleted_then_batch_state_then_batch_expired
    """
    env = setup_landscape(with_site=False)
    admin, provider_headers = env["admin_headers"], env["provider_headers"]
    candidate_a = add_candidate(env)
    candidate_b = add_candidate(env)
    expires_at = "2026-08-15T00:00:00Z"
    mixed = purchase_batch(env, expires_at=expires_at, line_items=[
        {"bundle_type": "EXAM_ONLY", "quantity": 1},
        {"bundle_type": "COURSE_PLUS_EXAM", "quantity": 1}])
    _, mixed = assign_code(env, mixed, candidate_a)
    assert (mixed["status"], mixed["available_count"], mixed["assigned_count"]) == (
        "ACTIVE", 1, 1)
    spare = purchase_batch(env, expires_at=expires_at,
                           line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}])

    held_version = mixed["version"]
    wrong_bundle = api.assign_access_code(
        mixed["id"],
        f.create_assignment_payload(candidate_b["id"], held_version, "EXAM_ONLY"),
        provider_headers)
    validate_error(wrong_bundle, "ERR_BATCH_DEPLETED", 409)

    # The refused request left the version untouched: the same guard still matches.
    bundled = get_success_data(api.assign_access_code(
        mixed["id"],
        f.create_assignment_payload(candidate_b["id"], held_version,
                                    "COURSE_PLUS_EXAM"),
        provider_headers), 201)
    assert bundled["bundle_type"] == "COURSE_PLUS_EXAM"
    emptied = read_batch(env, mixed["id"])
    assert (emptied["status"], emptied["available_count"],
            emptied["assigned_count"]) == ("DEPLETED", 0, 2)

    set_clock("2026-08-16T00:00:00Z", admin)
    too_late = api.assign_access_code(
        spare["id"],
        f.create_assignment_payload(candidate_a["id"], spare["version"], "EXAM_ONLY"),
        provider_headers)
    validate_error(too_late, "ERR_BATCH_EXPIRED", 409)
    assert read_batch(env, spare["id"])["status"] == "ACTIVE"

    voided = get_success_data(api.void_access_code_batch(
        spare["id"], f.create_void_payload(spare["version"], reason="Course cancelled"),
        provider_headers))
    assert voided["status"] == "VOIDED"
    assert (voided["voided_count"], voided["available_count"]) == (1, 0)
    assert voided["void_gross_credit_cents"] == 3762
    assert voided["void_restock_fee_cents"] == 564
    assert voided["void_net_credit_cents"] == 3198

    again = api.void_access_code_batch(
        spare["id"], f.create_void_payload(voided["version"],
                                           reason="Course cancelled again"),
        provider_headers)
    validate_error(again, "ERR_BATCH_STATE_INVALID", 409)


def test_the_accommodation_guards_fire_from_both_directions_and_per_candidate(api):
    """review-open wants REQUESTED and review wants UNDER_REVIEW, the duplicate guard
    counts the candidate rather than the type, and it guards APPROVE only.

    PRD: "Taking a request into review moves `REQUESTED → UNDER_REVIEW` and records the
    reviewing operator's `X-User-ID` in `reviewed_by_user_id`; attempting it on a request
    that is not `REQUESTED` answers `ERR_ACCOMMODATION_STATE_INVALID` (HTTP 409), and the
    same code answers a decision on a request that is not `UNDER_REVIEW`."

    PRD: "No other accommodation request belonging to the same candidate may already be
    `APPROVED`, and a second approval is rejected with
    `ERR_DUPLICATE_APPROVED_ACCOMMODATION` (HTTP 409)."

    PRD: "Three referential rules bind the sitting to the objects it names: the code's
    `candidate_id` must equal the sitting's `candidate_id` or the request answers
    `ERR_ACCESS_CODE_CANDIDATE_MISMATCH` (HTTP 409); the exam form purchased for the
    code's batch must equal the sitting's `exam_form_id` or the request answers
    `ERR_ACCESS_CODE_FORM_MISMATCH` (HTTP 409); and a linked accommodation must belong to
    the same candidate with a `status` of either `UNDER_REVIEW` or `APPROVED`, failing
    which the request answers `ERR_ACCOMMODATION_CANDIDATE_MISMATCH` (HTTP 409)."

    PRD: "On the denial branch the request moves `UNDER_REVIEW → DENIED`,
    `decision_reason` records the reviewer's note, and `approved_multiplier` stays null."

    Design: Corner/errors/accommodation_rejections_state_duplicate_approval_and_candidate_mismatch
    """
    env = setup_landscape()
    admin, provider_headers = env["admin_headers"], env["provider_headers"]
    candidate_a = add_candidate(env)
    candidate_b = add_candidate(env)
    proctor = add_proctor(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 2}])
    code_b, batch = assign_code(env, batch, candidate_b)

    first = get_success_data(api.create_accommodation_request(
        f.create_accommodation_request_payload(
            candidate_a["id"], accommodation_type="EXTRA_TIME",
            requested_multiplier=1.5, documentation_ref="DOC-EXTRA-1"),
        provider_headers), 201)
    get_success_data(api.open_accommodation_review(first["id"], _ALT_ADMIN))
    first = get_success_data(api.review_accommodation(
        first["id"], f.create_accommodation_review_payload("APPROVE"), _ALT_ADMIN))
    assert first["status"] == "APPROVED"

    second = get_success_data(api.create_accommodation_request(
        f.create_accommodation_request_payload(
            candidate_a["id"], accommodation_type="SEPARATE_ROOM",
            requested_multiplier=1.0, documentation_ref="DOC-ROOM-2"),
        provider_headers), 201)
    assert second["status"] == "REQUESTED"

    reopened = api.open_accommodation_review(first["id"], _ALT_ADMIN)
    validate_error(reopened, "ERR_ACCOMMODATION_STATE_INVALID", 409)
    still_approved = get_success_data(api.get_accommodation_request(first["id"], admin))
    assert still_approved["status"] == "APPROVED"
    assert float(still_approved["approved_multiplier"]) == 1.5

    too_early = api.review_accommodation(
        second["id"], f.create_accommodation_review_payload("APPROVE"), _ALT_ADMIN)
    validate_error(too_early, "ERR_ACCOMMODATION_STATE_INVALID", 409)

    opened = get_success_data(api.open_accommodation_review(second["id"], _ALT_ADMIN))
    assert opened["status"] == "UNDER_REVIEW"
    assert opened["reviewed_by_user_id"] == "admin-ops-2"

    duplicate = api.review_accommodation(
        second["id"], f.create_accommodation_review_payload("APPROVE"), _ALT_ADMIN)
    validate_error(duplicate, "ERR_DUPLICATE_APPROVED_ACCOMMODATION", 409)
    held = get_success_data(api.get_accommodation_request(second["id"], admin))
    assert held["status"] == "UNDER_REVIEW"
    assert held["approved_multiplier"] is None

    borrowed = api.create_exam_session(
        f.create_exam_session_payload(
            candidate_b["id"], env["exam_form"]["id"], code_b["id"],
            "2026-09-12T09:00:00Z", delivery_mode="IN_PERSON",
            testing_site_id=env["testing_site"]["id"], proctor_id=proctor["id"],
            accommodation_request_id=second["id"]),
        provider_headers)
    validate_error(borrowed, "ERR_ACCOMMODATION_CANDIDATE_MISMATCH", 409)
    _, meta = validate_paginated(api.list_exam_sessions(
        admin, params={"candidate_id": candidate_b["id"]}))
    assert meta["total_count"] == 0

    denied = get_success_data(api.review_accommodation(
        second["id"], f.create_accommodation_review_payload(
            "DENY", decision_reason="Duplicate of DOC-EXTRA-1"), _ALT_ADMIN))
    assert denied["status"] == "DENIED"
    assert denied["approved_multiplier"] is None


def test_the_incident_pipeline_refuses_both_orderings_and_closes_at_72_hours(api):
    """Resolution before review and review twice are the same state error, and the
    filing window measured from submitted_at includes its own last instant.

    PRD: "The incident's `status` must be `UNDER_REVIEW`, and the resolving operator must
    clear the segregation-of-duties comparison of §2.11: their `X-User-ID` must differ
    from the `finalized_by_user_id` recorded on that sitting's score report, or the
    request is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD: "15. Incident state permits it — `ERR_INCIDENT_STATE_INVALID`."

    PRD: "The incident's `status` must be `OPEN`, or the request answers
    `ERR_INCIDENT_STATE_INVALID` (HTTP 409), and the sitting's `proctoring_status` must be
    either `ATTESTED` or `CLEARED`."

    PRD: "On success the incident moves `OPEN → UNDER_REVIEW` and the sitting's
    `proctoring_status` moves `ATTESTED → INCIDENT_UNDER_REVIEW` or `CLEARED →
    INCIDENT_UNDER_REVIEW`."

    PRD: "Reporting is also time-boxed: the logical clock must be at or before the
    sitting's `submitted_at` plus 72 hours — three days — and a later report is rejected
    with `ERR_INCIDENT_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/errors/incident_rejections_state_invalid_both_ways_and_filing_window_at_exactly_72_hours
    """
    env = setup_sitting(stage="SUBMITTED", start_at="2026-09-12T09:00:00Z",
                        scored_correct_count=60)
    admin, session = env["admin_headers"], env["session"]
    assert session["submitted_at"] == "2026-09-12T09:00:00Z"
    assert session["proctoring_status"] == "ATTESTED"

    incident = file_incident(env, session, env["proctor"], severity="MINOR",
                             category="PROHIBITED_MATERIAL")
    assert incident["status"] == "OPEN"
    assert incident["severity_weight"] == 1

    too_early = api.resolve_security_incident(
        incident["id"], f.create_incident_resolution_payload(
            "DISMISS", resolution_note="Too early to resolve"), _SECURITY_ADMIN)
    validate_error(too_early, "ERR_INCIDENT_STATE_INVALID", 409)
    unresolved = get_success_data(api.get_security_incident(incident["id"], admin))
    assert unresolved["status"] == "OPEN"
    assert unresolved["resolved_by_user_id"] is None

    opened = take_incident_into_review(env, incident, admin_headers=_SECURITY_ADMIN)
    assert opened["status"] == "UNDER_REVIEW"
    reviewed_session = get_success_data(api.get_exam_session(session["id"], admin))
    assert reviewed_session["proctoring_status"] == "INCIDENT_UNDER_REVIEW"
    assert reviewed_session["session_status"] == "SUBMITTED"

    reopened = api.open_incident_review(incident["id"], _SECURITY_ADMIN)
    validate_error(reopened, "ERR_INCIDENT_STATE_INVALID", 409)
    assert get_success_data(api.get_security_incident(
        incident["id"], admin))["status"] == "UNDER_REVIEW"

    set_clock("2026-09-15T09:00:00Z", admin)
    on_the_bound = get_success_data(api.create_security_incident(
        f.create_security_incident_payload(
            session["id"], env["proctor"]["id"], severity="MAJOR",
            category="CONTENT_DISCLOSURE",
            narrative="Screenshot of two items surfaced in a study group chat"),
        env["proctor_headers"]), 201)
    assert on_the_bound["status"] == "OPEN"
    assert on_the_bound["severity_weight"] == 3

    set_clock("2026-09-15T09:01:00Z", admin)
    one_minute_late = api.create_security_incident(
        f.create_security_incident_payload(
            session["id"], env["proctor"]["id"], severity="MINOR",
            category="ROOM_SCAN_REFUSAL",
            narrative="Late recollection of a refused room scan"),
        env["proctor_headers"])
    validate_error(one_minute_late, "ERR_INCIDENT_WINDOW_CLOSED", 409)

    _, meta = validate_paginated(api.list_security_incidents(
        admin, params={"exam_session_id": session["id"]}))
    assert meta["total_count"] == 2


def _matrix_env():
    """One candidate holding three codes against three forms, plus two sites and
    three proctors, so each eligibility rule can be broken one at a time."""
    env = setup_landscape(
        jurisdiction={"accepted_accreditation_bodies": ["ANAB_CFP"],
                      "accepted_languages": ["EN"],
                      "accepts_remote_proctoring": True},
        testing_site={"languages_supported": ["EN"]})
    env["site_es"] = add_testing_site(env, name="Sur Testing Annex",
                                      languages_supported=["ES"])
    env["form_es"] = add_exam_form(env, form_code="FM-ES-01", language="ES")
    env["form_legacy"] = add_exam_form(env, form_code="FM-LG-01",
                                       accreditation_body="ANSI_LEGACY")
    env["proctor_en"] = add_proctor(env, languages_certified=["EN"],
                                    remote_certified=False)
    env["proctor_es"] = add_proctor(env, languages_certified=["ES"],
                                    remote_certified=False)
    env["proctor_rc"] = add_proctor(env, languages_certified=["EN"],
                                    remote_certified=True)
    candidate = add_candidate(env)
    env["candidate"] = candidate
    for key, form in (("code_en", env["exam_form"]), ("code_es", env["form_es"]),
                      ("code_legacy", env["form_legacy"])):
        batch = purchase_batch(env, exam_form_id=form["id"],
                               line_items=[{"bundle_type": "EXAM_ONLY",
                                            "quantity": 1}])
        code, _ = assign_code(env, batch, candidate)
        env[key] = code
    return env


def test_each_eligibility_rule_names_its_own_rejection(api):
    """Seven bookings break one eligibility rule each and answer seven distinct
    errors; the eighth, well-formed booking proves the fixture was otherwise sound.

    PRD: "Three acceptance rules read the **candidate's own** jurisdiction, never the
    testing site's: the form's `accreditation_body` must appear in that jurisdiction's
    `accepted_accreditation_bodies` or the request answers
    `ERR_ACCREDITATION_NOT_ACCEPTED` (HTTP 422); the form's `language` must appear in its
    `accepted_languages` or the request answers `ERR_LANGUAGE_NOT_ACCEPTED` (HTTP 422);
    and a `REMOTE` sitting requires that jurisdiction's `accepts_remote_proctoring` to be
    true or the request answers `ERR_REMOTE_PROCTORING_NOT_ACCEPTED` (HTTP 422)."

    PRD: "Three capability rules bind the delivery channel: the proctor's
    `languages_certified` must contain the form's `language` or the request answers
    `ERR_PROCTOR_LANGUAGE_NOT_CERTIFIED` (HTTP 422); a `REMOTE` sitting requires the
    proctor's `remote_certified` to be true or the request answers
    `ERR_PROCTOR_NOT_REMOTE_CERTIFIED` (HTTP 422); and for an in-person sitting the chosen
    site's `languages_supported` must contain the form's `language` or the request answers
    `ERR_SITE_LANGUAGE_UNSUPPORTED` (HTTP 422)."

    PRD: "Getting the site-versus-mode pairing wrong in either direction — an in-person
    sitting with no `testing_site_id`, or a remote sitting that supplies one — is rejected
    with `ERR_SITE_REQUIRED_FOR_IN_PERSON` (HTTP 422)."

    Design: Corner/errors/scheduling_eligibility_matrix_rejections_by_jurisdiction_proctor_and_site
    """
    env = _matrix_env()
    admin, provider_headers = env["admin_headers"], env["provider_headers"]
    candidate, form_en = env["candidate"], env["exam_form"]
    site_en, site_es = env["testing_site"], env["site_es"]
    slot = "2026-09-12T09:00:00Z"

    def book(form, code, proctor, mode="IN_PERSON", site=None):
        payload = f.create_exam_session_payload(
            candidate["id"], form["id"], code["id"], slot, delivery_mode=mode,
            proctor_id=proctor["id"])
        if site is not None:
            payload["testing_site_id"] = site["id"]
        return api.create_exam_session(payload, provider_headers)

    validate_error(book(env["form_legacy"], env["code_legacy"], env["proctor_en"],
                        site=site_en),
                   "ERR_ACCREDITATION_NOT_ACCEPTED", 422)
    validate_error(book(env["form_es"], env["code_es"], env["proctor_es"],
                        site=site_es),
                   "ERR_LANGUAGE_NOT_ACCEPTED", 422)
    validate_error(book(form_en, env["code_en"], env["proctor_en"], mode="REMOTE"),
                   "ERR_PROCTOR_NOT_REMOTE_CERTIFIED", 422)
    validate_error(book(form_en, env["code_en"], env["proctor_es"], site=site_en),
                   "ERR_PROCTOR_LANGUAGE_NOT_CERTIFIED", 422)
    validate_error(book(form_en, env["code_en"], env["proctor_en"], site=site_es),
                   "ERR_SITE_LANGUAGE_UNSUPPORTED", 422)
    validate_error(book(form_en, env["code_en"], env["proctor_en"]),
                   "ERR_SITE_REQUIRED_FOR_IN_PERSON", 422)
    validate_error(book(form_en, env["code_en"], env["proctor_rc"], mode="REMOTE",
                        site=site_en),
                   "ERR_SITE_REQUIRED_FOR_IN_PERSON", 422)

    _, meta = validate_paginated(api.list_exam_sessions(
        admin, params={"candidate_id": candidate["id"]}))
    assert meta["total_count"] == 0
    assert get_success_data(api.get_access_code(
        env["code_en"]["id"], provider_headers))["status"] == "ASSIGNED"

    booked = get_success_data(
        book(form_en, env["code_en"], env["proctor_en"], site=site_en), 201)
    assert booked["session_status"] == "SCHEDULED"
    assert booked["proctoring_status"] == "ASSIGNED"
    assert booked["allowed_minutes"] == 120
