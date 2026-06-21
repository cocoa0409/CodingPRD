"""Role-based access control, segregation of duties, optimistic concurrency on
the trial version, the response envelope, and immediate-consistency reads
(PRD §2.1, §2.2, §2.6, §3.2, §3.5)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_trial_payload, create_irb_review_payload, decide_irb_review_payload,
    review_adverse_event_payload,
    set_clock, get_trial_version,
    create_trial, open_irb_review,
    setup_open_trial, create_consent_document, approve_protocol, approve_consent,
    setup_randomized_enrollment, report_adverse_event,
    create_eligible_screened_enrollment,
    activate_consent_payload,
    build_user_headers,
    TEST_USERS, make_sponsor_headers, make_irb_reviewer_headers,
    make_safety_officer_headers,
)


# ─── Corner: rbac ───────────────────────────────────────────────────


def test_coordinator_cannot_open_irb_review(api):
    """PRD §2.1: "When a request carries valid headers but the role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_coordinator_cannot_open_irb_review
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=5)

    res = api.create_irb_review(
        trial["id"], create_irb_review_payload(scope="PROTOCOL"), TEST_USERS["coordinator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one
    of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/rbac_missing_headers_unauthenticated
    """
    res = api.create_trial(
        create_trial_payload(title="NoAuth", target_enrollment=5, randomization_method="SIMPLE"),
        {"Content-Type": "application/json"},  # no X-User-ID / X-User-Role
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_sponsor_cannot_decide_own_review(api):
    """PRD §3.2: "the deciding reviewer's `X-User-ID` must not equal the trial's
    `sponsor_user_id` — a sponsor deciding their own trial's review is a
    segregation-of-duties violation rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."

    Design: Corner/rbac/rbac_sponsor_cannot_decide_own_review_segregation
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(sponsor_user_id="sponsor-1", target_enrollment=5)
    review = open_irb_review(trial["id"], scope="PROTOCOL")

    # IRBReviewer whose X-User-ID equals the trial's sponsor_user_id.
    res = api.decide_irb_review(
        trial["id"], review["id"], decide_irb_review_payload("APPROVE"),
        make_irb_reviewer_headers("sponsor-1"),
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    reviews = validate_success(api.list_irb_reviews(trial["id"], TEST_USERS["sponsor_headers"]), 200)
    target = next(r for r in reviews if r["id"] == review["id"])
    assert target["decision"] == "PENDING", "the review stays PENDING"


def test_reporter_cannot_triage_own_adverse_event(api):
    """PRD §3.5: "A `SafetyOfficer` — never the investigator who reported it —
    reviews the event. The reviewing officer's `X-User-ID` must not equal the
    event's `reporter_user_id`; otherwise the review is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/rbac_reporter_cannot_triage_own_ae_segregation
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_randomized_enrollment()
    ae = report_adverse_event(ctx["enrollment_id"], severity="MODERATE",
                              occurred_at="2026-06-01T09:00:00Z", reporter_user_id="inv-1")

    # SafetyOfficer whose X-User-ID equals the event's reporter_user_id.
    res = api.review_adverse_event(
        ae["id"], review_adverse_event_payload("TRIAGE"), make_safety_officer_headers("inv-1"),
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    events = validate_success(api.list_adverse_events(ctx["enrollment_id"], TEST_USERS["safety_officer_headers"]), 200)
    target = next(e for e in events if e["id"] == ae["id"])
    assert target["report_status"] == "REPORTED", "the event stays REPORTED"


# ─── Corner: cross_cutting / optimistic concurrency ─────────────────


def test_stale_trial_version_on_second_activate_rejected(api):
    """PRD §2.6: "Activating an IRB-approved consent document supersedes
    whichever consent document was previously `ACTIVE` for the trial and
    recomputes the trial's `posture`. The activation request must carry
    `expected_trial_version` equal to the trial's current `version`. If the
    trial's `version` has advanced since the client last read it ... the
    client's view is stale and the activation is rejected with
    `ERR_STALE_TRIAL_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_trial_version_on_second_activate
    """
    set_clock("2026-06-01T08:00:00Z")
    # A trial with TWO IRB_APPROVED consent versions, neither yet activated.
    trial = create_trial(target_enrollment=5)
    from test_helpers import add_arm
    add_arm(trial["id"], name="TREATMENT")
    doc_v1 = create_consent_document(trial["id"], body_hash="v1")
    approve_protocol(trial["id"])
    approve_consent(trial["id"], doc_v1["id"])     # v1 -> IRB_APPROVED
    doc_v2 = create_consent_document(trial["id"], body_hash="v2")
    approve_consent(trial["id"], doc_v2["id"])     # v2 -> IRB_APPROVED

    # Capture the version, then activate v1 (which advances Trial.version).
    stale_version = get_trial_version(trial["id"])
    validate_success(api.activate_consent_document(
        trial["id"], doc_v1["id"], activate_consent_payload(stale_version),
        TEST_USERS["sponsor_headers"],
    ), 200)

    # Activating the still-IRB_APPROVED v2 with the now-stale version is 412.
    res = api.activate_consent_document(
        trial["id"], doc_v2["id"], activate_consent_payload(stale_version),
        TEST_USERS["sponsor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_STALE_TRIAL_VERSION.value, 412)


# ─── Corner: endpoints ──────────────────────────────────────────────


def test_trial_create_response_envelope_shape(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body"
    PRD §2.4: "Every resource in this system carries a `id` that is a
    server-minted UUID with no type prefix"

    Design: Corner/endpoints/response_envelope_shape_on_trial_create
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_trial(
        create_trial_payload(title="Envelope", target_enrollment=5, randomization_method="SIMPLE"),
        make_sponsor_headers("sponsor-1"),
    )
    assert res.status_code == 201
    body = res.json()
    assert "meta" in body and "api_request_id" in body["meta"], "meta.api_request_id present"
    assert "api_request_timestamp" in body["meta"], "meta.api_request_timestamp present"
    assert body["response_type"] == "object", "single resource => response_type object"
    # validate_success cross-checks the envelope and asserts the UUID id shape.
    data = validate_success(res, 201)
    from test_helpers import is_valid_uuid
    assert is_valid_uuid(data["id"]), "data.id is a UUID with no type prefix"


def test_enrollment_list_returns_enrollment_with_pagination_fields(api):
    """PRD §2.3: "The list-returning endpoints that accept these parameters —
    the screenings and enrollments collections — include the four pagination
    fields `limit`, `offset`, `total_count`, and `has_more` in the `meta`
    object of the response envelope."

    Design: Corner/endpoints/enrollment_filtered_list_by_trial
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=5)
    enr_ctx = create_eligible_screened_enrollment(trial["id"])

    res = api.list_enrollments(TEST_USERS["coordinator_headers"])
    data, meta = validate_success(res, 200), res.json()["meta"]
    ids = [e["id"] for e in data]
    assert enr_ctx["enrollment_id"] in ids, "the created enrollment appears in the listing"
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"the enrollments listing meta carries {field}"


# ─── Corner: consistency_model ──────────────────────────────────────


def test_posture_open_visible_immediately_after_activate(api):
    """PRD §2.5: "It becomes `OPEN` once the protocol review has been approved
    (`irb_status` is `APPROVED`), the trial has at least one randomization arm,
    an `ACTIVE` consent document exists, and there are no active safety holds."
    PRD §2.5: "Posture is recomputed every time an IRB decision lands, a consent
    document is activated, an enrollment is randomized or withdrawn, a safety
    hold is placed, or a safety hold is lifted."

    Design: Corner/consistency_model/immediate_visibility_of_posture_after_activate
    """
    set_clock("2026-06-01T08:00:00Z")
    trial = create_trial(target_enrollment=5)
    from test_helpers import add_arm
    add_arm(trial["id"], name="TREATMENT")
    doc = create_consent_document(trial["id"], body_hash="h1")
    approve_protocol(trial["id"])
    approve_consent(trial["id"], doc["id"])
    tv = get_trial_version(trial["id"])

    activate_res = api.activate_consent_document(
        trial["id"], doc["id"], activate_consent_payload(tv), TEST_USERS["sponsor_headers"],
    )
    validate_success(activate_res, 200)

    # The immediately-following GET reflects the recomputed posture with no lag.
    trial_after = validate_success(api.get_trial(trial["id"], TEST_USERS["sponsor_headers"]), 200)
    assert trial_after["posture"] == "OPEN", "posture is OPEN on the next GET, immediately"
