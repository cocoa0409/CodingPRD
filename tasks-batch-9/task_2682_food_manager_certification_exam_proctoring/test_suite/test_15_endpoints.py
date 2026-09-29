"""Full endpoint round-trips: the site trio, the narrow effect of retirement, the
filing chain, the derived compliance summary and the recertification gate."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_candidate,
    add_jurisdiction,
    add_proctor,
    assign_code,
    check_in_session,
    factories as f,
    file_incident,
    file_local_registration,
    finalize_report,
    get_success_data,
    issue_certificate,
    make_candidate_headers,
    purchase_batch,
    schedule_session,
    set_clock,
    setup_landscape,
    start_session,
    submit_session,
    validate_error,
    validate_paginated,
)

_SCORING_ADMIN = TEST_USERS["scoring_admin_headers"]
_ALT_ADMIN = TEST_USERS["platform_admin_alt_headers"]


def _certified_at_1030(api, jurisdiction=None):
    """Walk one sitting so its certificate is issued at 2026-09-12T10:30:00Z."""
    env = setup_landscape(jurisdiction=jurisdiction)
    admin = env["admin_headers"]
    candidate = add_candidate(env)
    proctor = add_proctor(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}])
    code, batch = assign_code(env, batch, candidate)
    session = schedule_session(env, candidate, code, "2026-09-12T09:00:00Z",
                               proctor=proctor)
    session = check_in_session(env, session, proctor, at_clock="2026-09-12T08:45:00Z")
    set_clock("2026-09-12T09:00:00Z", admin)
    session = start_session(env, session, proctor)
    set_clock("2026-09-12T10:30:00Z", admin)
    report = submit_session(env, session, proctor, scored_correct_count=60)
    report = finalize_report(env, report, admin_headers=_SCORING_ADMIN)
    env.update({"candidate": candidate, "proctor": proctor, "session": session,
                "score_report": report})
    env["certificate"] = issue_certificate(env, report, admin_headers=admin)
    return env


def test_a_testing_site_round_trips_and_the_jurisdiction_filter_narrows_the_list(api):
    """Create, read and list one site per jurisdiction: the array and integer inputs
    survive intact, occupancy is minted at zero and the filter is what narrows.

    PRD: "Registering an in-person testing site records its `name`, the
    `jurisdiction_id` it sits in, an `address_line`, a `seat_count` between 1 and 50
    describing how many proctored seats can be occupied at once, and
    `languages_supported` — the non-empty set of exam languages this centre can
    actually deliver in person."

    PRD: "A new site opens with `reserved_seat_minutes` at zero, and that figure
    thereafter tracks the site's committed testing time as described in §2.9."

    PRD: "`total_count` is the number of rows matching the filters before the window
    is applied, and `has_more` is true when rows remain beyond the current window."

    Design: Corner/endpoints/testing_site_create_read_and_filtered_list_round_trip
    """
    env = setup_landscape(with_site=False)
    admin = env["admin_headers"]
    other = add_jurisdiction(env, jurisdiction_code="TX-BEXAR",
                             name="Bexar County Health Department")

    created = get_success_data(api.create_testing_site(
        f.create_testing_site_payload(
            env["jurisdiction"]["id"], name="Austin Exam Center", seat_count=3,
            address_line="100 Congress Ave", languages_supported=["EN", "ES"]),
        admin), 201)
    elsewhere = get_success_data(api.create_testing_site(
        f.create_testing_site_payload(
            other["id"], name="San Antonio Exam Center", seat_count=1,
            address_line="12 Alamo Plaza", languages_supported=["EN"]),
        admin), 201)

    assert created["name"] == "Austin Exam Center"
    assert created["seat_count"] == 3
    assert created["languages_supported"] == ["EN", "ES"]
    assert created["address_line"] == "100 Congress Ave"
    assert created["jurisdiction_id"] == env["jurisdiction"]["id"]
    assert created["reserved_seat_minutes"] == 0
    assert created["version"] == 1

    read_back = get_success_data(api.get_testing_site(created["id"], admin))
    assert read_back["id"] == created["id"]
    assert read_back["name"] == created["name"]
    assert read_back["seat_count"] == created["seat_count"]
    assert read_back["created_at"] == created["created_at"]

    filtered, filtered_meta = validate_paginated(api.list_testing_sites(
        admin, params={"jurisdiction_id": env["jurisdiction"]["id"],
                       "limit": 10, "offset": 0}))
    assert filtered_meta["total_count"] == 1
    assert filtered_meta["has_more"] is False
    assert [row["id"] for row in filtered] == [created["id"]]

    _, all_meta = validate_paginated(api.list_testing_sites(
        admin, params={"limit": 10, "offset": 0}))
    assert all_meta["total_count"] == 2
    assert elsewhere["seat_count"] == 1


def test_retirement_blocks_new_business_but_leaves_a_booked_sitting_alone(api):
    """After retirement a purchase, a booking and a second retire all answer
    ERR_EXAM_FORM_RETIRED, while the sitting already on the books is untouched.

    PRD: "Retiring a form moves its `status` from `ACTIVE` to `RETIRED` and is
    deliberately narrow in effect: sittings already scheduled against the form are
    untouched and proceed to completion, but no new code batch may be purchased
    against it and no new sitting may be scheduled on it."

    PRD: "Attempting either — or attempting to retire a form that is already
    `RETIRED` — is rejected with `ERR_EXAM_FORM_RETIRED` (HTTP 409)."

    Design: Corner/endpoints/retiring_a_form_blocks_new_purchases_but_leaves_booked_sittings_alone
    """
    env = setup_landscape()
    admin, provider_headers = env["admin_headers"], env["provider_headers"]
    form_id, site_id = env["exam_form"]["id"], env["testing_site"]["id"]
    assert env["exam_form"]["status"] == "ACTIVE"
    first = add_candidate(env)
    second = add_candidate(env)
    proctor = add_proctor(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 2}])
    first_code, batch = assign_code(env, batch, first)
    second_code, batch = assign_code(env, batch, second)
    booked = schedule_session(env, first, first_code, "2026-09-10T09:00:00Z",
                              proctor=proctor)
    assert get_success_data(api.get_training_provider(
        env["provider"]["id"], admin))["credit_balance_cents"] == 492476

    retired = get_success_data(api.retire_exam_form(form_id, admin))
    assert retired["status"] == "RETIRED"

    no_purchase = api.create_access_code_batch(
        f.create_access_code_batch_payload(
            env["provider"]["id"], form_id,
            line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}],
            expires_at="2027-06-30T00:00:00Z"),
        provider_headers)
    validate_error(no_purchase, "ERR_EXAM_FORM_RETIRED", 409)
    assert get_success_data(api.get_training_provider(
        env["provider"]["id"], admin))["credit_balance_cents"] == 492476

    no_booking = api.create_exam_session(
        f.create_exam_session_payload(
            second["id"], form_id, second_code["id"], "2026-09-11T09:00:00Z",
            delivery_mode="IN_PERSON", testing_site_id=site_id,
            proctor_id=proctor["id"]),
        provider_headers)
    validate_error(no_booking, "ERR_EXAM_FORM_RETIRED", 409)
    assert get_success_data(api.get_access_code(
        second_code["id"], provider_headers))["status"] == "ASSIGNED"

    validate_error(api.retire_exam_form(form_id, admin), "ERR_EXAM_FORM_RETIRED", 409)

    survivor = get_success_data(api.get_exam_session(booked["id"], admin))
    assert survivor["session_status"] == "SCHEDULED"
    assert survivor["allowed_minutes"] == 120
    assert get_success_data(api.get_testing_site(
        site_id, admin))["reserved_seat_minutes"] == 120
    assert get_success_data(api.get_proctor(
        proctor["id"], admin))["reserved_minutes"] == 120


def test_a_filing_walks_from_the_certificate_to_a_verified_posting(api):
    """The filing copies its jurisdiction from the certificate, derives the deadline
    from that jurisdiction's policy, and then posts and verifies.

    PRD: "Body foreign keys resolve, validated in the order the fields appear in that
    endpoint's input list — the matching `ERR_..._NOT_FOUND`."

    PRD: "The filing's `jurisdiction_id` is copied from the certificate rather than
    supplied, and that jurisdiction must actually require local registration — filing
    into a jurisdiction whose `requires_local_registration` is false is rejected with
    `ERR_LOCAL_REGISTRATION_NOT_REQUIRED` (HTTP 409)."

    PRD: "On success the registration opens with `status` `FILED`, `filed_at` set to
    the logical clock, `refile_count` at zero, and `posting_deadline_at` computed as
    `filed_at` advanced by the jurisdiction's `posting_deadline_days` days;
    `posting_location`, `posted_at`, `rejection_reason` and `verified_by_user_id` are
    all null."

    PRD: "The registration moves `FILED → POSTED` or `DELINQUENT → POSTED`,
    `posted_at` is set to the logical clock and `posting_location` is recorded."

    PRD: "On `VERIFY` the registration moves `POSTED → VERIFIED` and
    `verified_by_user_id` records the officer's `X-User-ID`; the owning certificate
    must still be `ISSUED`."

    Design: Corner/endpoints/local_registration_links_certificate_to_establishment_then_posts_and_verifies
    """
    env = _certified_at_1030(api)
    admin, provider_headers = env["admin_headers"], env["provider_headers"]
    jurisdiction_id = env["jurisdiction"]["id"]
    certificate = env["certificate"]
    assert env["jurisdiction"]["requires_local_registration"] is True
    assert env["jurisdiction"]["posting_deadline_days"] == 30

    ghost = api.create_local_registration(
        f.create_local_registration_payload(
            NON_EXISTENT_UUID, establishment_name="Ghost Kitchen",
            establishment_address="1 Nowhere Rd"),
        provider_headers)
    validate_error(ghost, "ERR_CERTIFICATE_NOT_FOUND", 404)
    _, empty = validate_paginated(api.list_local_registrations(admin))
    assert empty["total_count"] == 0

    registration = file_local_registration(
        env, certificate, establishment_name="Barton Springs Cafe",
        establishment_address="2200 Barton Springs Rd")

    assert registration["status"] == "FILED"
    assert registration["filed_at"] == "2026-09-12T10:30:00Z"
    assert registration["posting_deadline_at"] == "2026-10-12T10:30:00Z"
    assert registration["jurisdiction_id"] == jurisdiction_id
    assert registration["posted_at"] is None
    assert registration["refile_count"] == 0
    assert registration["rejection_reason"] is None
    assert registration["verified_by_user_id"] is None
    assert registration["posting_location"] is None

    posted = get_success_data(api.confirm_posting(
        registration["id"],
        f.create_posting_confirmation_payload(
            posting_location="Behind the host stand, at eye level"),
        provider_headers))
    assert posted["status"] == "POSTED"
    assert posted["posted_at"] == "2026-09-12T10:30:00Z"
    assert posted["posting_location"] == "Behind the host stand, at eye level"

    verified = get_success_data(api.verify_local_registration(
        registration["id"], f.create_verification_payload("VERIFY"),
        env["officer_headers"]))
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == jurisdiction_id

    rows, meta = validate_paginated(api.list_local_registrations(
        admin, params={"certificate_id": certificate["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "VERIFIED"


def test_the_compliance_summary_joins_three_entities_in_one_read(api):
    """One derived read reports the certificate window, the filing state and the open
    incident count, and the candidate sees exactly what the officer sees.

    PRD: "A dedicated computed read exposes the whole posture in one object for
    regulators and providers alike: it returns `candidate_id`, the current
    `compliance_status`, the `active_certificate_id`, that certificate's
    `certificate_expires_at` and `recert_window_opens_at`, the
    `local_registration_status` of its filing, the `reminder_tiers_sent` already
    dispatched against it, and an `open_incident_count`."

    PRD: "A `HealthOfficer` may read this summary for candidates in its own
    jurisdiction, which is how a health inspector learns that a posted certificate has
    been revoked."

    Design: Corner/endpoints/compliance_summary_reads_the_whole_certification_posture_in_one_call
    """
    env = _certified_at_1030(api)
    candidate, certificate = env["candidate"], env["certificate"]
    file_local_registration(env, certificate)
    incident = file_incident(env, env["session"], env["proctor"], severity="MINOR",
                             category="PROHIBITED_MATERIAL")
    assert incident["status"] == "OPEN"

    summary = get_success_data(api.get_compliance_summary(
        candidate["id"], env["officer_headers"]))

    assert summary["candidate_id"] == candidate["id"]
    assert summary["compliance_status"] == "CERTIFIED"
    assert summary["active_certificate_id"] == certificate["id"]
    assert summary["certificate_expires_at"] == "2031-09-12T10:30:00Z"
    assert summary["recert_window_opens_at"] == "2031-03-16T10:30:00Z"
    assert summary["local_registration_status"] == "FILED"
    assert summary["reminder_tiers_sent"] == []
    assert summary["open_incident_count"] == 1

    own_read = get_success_data(api.get_compliance_summary(
        candidate["id"], make_candidate_headers(candidate["id"])))
    assert own_read == summary


def test_recertification_is_refused_a_day_early_and_granted_on_the_instant(api):
    """The window bound is inclusive: one day short answers
    ERR_RECERT_WINDOW_NOT_OPEN, and the exact instant stamps the authorization.

    PRD: "Once the logical clock has reached `recert_window_opens_at` — the comparison
    is inclusive, so a clock sitting exactly on that instant qualifies — a
    `PlatformAdmin` authorizes the holder to sit again; a clock strictly before it is
    rejected with `ERR_RECERT_WINDOW_NOT_OPEN` (HTTP 409)."

    PRD: "Authorization takes no body and does only one thing: it sets
    `recert_authorized_at` to the logical clock."

    PRD: "The certificate is not renewed, not extended and does not change `status`;
    it merely becomes the certificate that a successor is permitted to replace."

    Design: Corner/endpoints/recert_authorization_is_refused_before_the_window_and_accepted_at_its_first_instant
    """
    env = _certified_at_1030(api, jurisdiction={"requires_local_registration": False})
    admin = env["admin_headers"]
    certificate = env["certificate"]
    assert certificate["recert_window_opens_at"] == "2031-03-16T10:30:00Z"

    set_clock("2031-03-15T10:30:00Z", admin)
    early = api.authorize_recertification(certificate["id"], _ALT_ADMIN)
    validate_error(early, "ERR_RECERT_WINDOW_NOT_OPEN", 409)
    assert get_success_data(api.get_certificate(
        certificate["id"], admin))["recert_authorized_at"] is None

    set_clock("2031-03-16T10:30:00Z", admin)
    authorized = get_success_data(api.authorize_recertification(
        certificate["id"], _ALT_ADMIN))

    assert authorized["recert_authorized_at"] == "2031-03-16T10:30:00Z"
    assert authorized["status"] == "ISSUED"
    assert authorized["expires_at"] == "2031-09-12T10:30:00Z"
    assert authorized["reminder_tiers_sent"] == []
    assert authorized["superseded_by_certificate_id"] is None
