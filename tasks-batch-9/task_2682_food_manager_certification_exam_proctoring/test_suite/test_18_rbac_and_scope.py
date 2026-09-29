"""The three-layer access model: authentication (401), role membership (403),
ownership scope (403), plus the per-user segregation-of-duties bar."""
from test_helpers import (
    TEST_USERS,
    add_candidate,
    add_jurisdiction,
    add_proctor,
    add_provider,
    assign_code,
    build_user_headers,
    factories as f,
    file_incident,
    get_success_data,
    make_candidate_headers,
    make_health_officer_headers,
    make_proctor_headers,
    purchase_batch,
    schedule_session,
    set_clock,
    setup_landscape,
    setup_sitting,
    validate_error,
    validate_paginated,
)

_SCORING_ADMIN = TEST_USERS["scoring_admin_headers"]
_SECURITY_ADMIN = TEST_USERS["security_admin_headers"]

_GHOST_SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_GHOST_CODE = "88888888-8888-4888-8888-888888888888"
_GHOST_REPORT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_GHOST_REGISTRATION = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


def test_no_role_inherits_another_roles_exclusive_operation(api):
    """Eight cross-role attempts, including a PlatformAdmin booking a sitting, are
    all 403s decided before any id in the request is resolved.

    PRD: "If the headers are well-formed but the acting role is not among the roles listed
    for the target endpoint in §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP
    403)."

    PRD: "2. Role membership in the target endpoint's role list — `ERR_UNAUTHORIZED`."

    PRD: "`PlatformAdmin` is accrediting-body operations staff: it publishes jurisdictions,
    exam forms and testing sites, adjudicates proctor registrations and audits, reviews
    accommodation requests, finalizes and releases scores, issues certificates, resolves
    security incidents, triggers compliance runs and pins the logical clock."

    PRD: "| POST | `/exam-sessions` | schedule an accredited sitting for a candidate
    against an assigned access code, in person or by remote proctoring | `ProviderAdmin` |"

    PRD: "| GET | `/exam-forms/{id}` | read one exam form | `PlatformAdmin`,
    `ProviderAdmin`, `Proctor` |"

    Design: Corner/rbac/each_role_is_denied_every_other_roles_exclusive_operation
    """
    env = setup_landscape(with_site=False)
    admin, provider_headers = env["admin_headers"], env["provider_headers"]
    candidate = add_candidate(env)
    proctor = add_proctor(env)
    candidate_headers = make_candidate_headers(candidate["id"])
    proctor_headers = make_proctor_headers(proctor["id"])
    booking = f.create_exam_session_payload(
        candidate["id"], env["exam_form"]["id"], _GHOST_CODE,
        "2026-09-12T09:00:00Z", delivery_mode="REMOTE")

    validate_error(api.create_jurisdiction(
        f.create_jurisdiction_payload(name="Rogue County",
                                      jurisdiction_code="XX-ROGUE"),
        provider_headers), "ERR_UNAUTHORIZED", 403)
    validate_error(api.create_exam_session(booking, admin), "ERR_UNAUTHORIZED", 403)
    validate_error(api.create_exam_session(booking, candidate_headers),
                   "ERR_UNAUTHORIZED", 403)
    validate_error(api.create_certificate(
        f.create_certificate_payload(_GHOST_REPORT), proctor_headers),
        "ERR_UNAUTHORIZED", 403)
    validate_error(api.create_security_incident(
        f.create_security_incident_payload(
            _GHOST_SESSION, proctor["id"], severity="MINOR",
            narrative="Filed by the wrong role"), provider_headers),
        "ERR_UNAUTHORIZED", 403)
    validate_error(api.verify_local_registration(
        _GHOST_REGISTRATION, f.create_verification_payload("VERIFY"),
        proctor_headers), "ERR_UNAUTHORIZED", 403)
    validate_error(api.confirm_posting(
        _GHOST_REGISTRATION, f.create_posting_confirmation_payload(
            posting_location="Wrong role"), env["officer_headers"]),
        "ERR_UNAUTHORIZED", 403)
    validate_error(api.open_proctor_audit(
        proctor["id"], f.create_audit_open_payload(
            audit_reason="Self-audit attempt"), proctor_headers),
        "ERR_UNAUTHORIZED", 403)

    _, meta = validate_paginated(api.list_exam_sessions(
        admin, params={"candidate_id": candidate["id"]}))
    assert meta["total_count"] == 0

    shared_form = get_success_data(api.get_exam_form(
        env["exam_form"]["id"], proctor_headers))
    assert shared_form["id"] == env["exam_form"]["id"]
    own_row = get_success_data(api.get_candidate(candidate["id"], candidate_headers))
    assert own_row["id"] == candidate["id"]


def test_unusable_identity_headers_answer_401_before_any_role_check(api):
    """An empty X-User-ID and an undeclared role are both 401s; the same read with a
    declared-but-wrong role is a 403 and with the right one a 200.

    PRD: "If either header is missing or empty, or if `X-User-Role` is not one of the five
    role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD: "1. Header presence and role recognition — `ERR_UNAUTHENTICATED`."

    PRD: "The five roles are `PlatformAdmin`, `ProviderAdmin`, `Proctor`, `Candidate` and
    `HealthOfficer`, spelled exactly that way."

    PRD: "| GET | `/training-providers` | list providers, optionally filtered by home
    jurisdiction | `PlatformAdmin` |"

    Design: Corner/rbac/missing_or_unknown_identity_headers_are_rejected_before_authorization
    """
    env = setup_landscape(prepay_cents=0, with_site=False)
    provider_id = env["provider"]["id"]
    provider_headers = env["provider_headers"]

    nameless = api.get_training_provider(
        provider_id, build_user_headers("", "ProviderAdmin"))
    validate_error(nameless, "ERR_UNAUTHENTICATED", 401)

    undeclared = api.get_training_provider(
        provider_id, build_user_headers(provider_id, "Auditor"))
    validate_error(undeclared, "ERR_UNAUTHENTICATED", 401)

    wrong_role = api.list_training_providers(provider_headers)
    validate_error(wrong_role, "ERR_UNAUTHORIZED", 403)

    own_row = get_success_data(api.get_training_provider(provider_id, provider_headers))
    assert own_row["id"] == provider_id
    assert own_row["credit_balance_cents"] == 0


def test_the_finalizer_may_open_the_review_but_never_resolve_it(api):
    """The segregation bar is per user and per step: admin-scoring-1 opens the review
    and is then refused the resolution that admin-security-1 performs unchanged.

    PRD: "The incident's `status` must be `UNDER_REVIEW`, and the resolving operator must
    clear the segregation-of-duties comparison of §2.11: their `X-User-ID` must differ from
    the `finalized_by_user_id` recorded on that sitting's score report, or the request is
    refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD: "Both outcomes record `resolved_by_user_id` from the acting `X-User-ID` and store
    the supplied `resolution_note`."

    PRD: "Dismissal is a full unwind. The incident moves `UNDER_REVIEW → DISMISSED` and the
    sitting's `proctoring_status` moves `INCIDENT_UNDER_REVIEW → CLEARED`."

    Design: Corner/rbac/the_admin_who_finalized_the_score_cannot_resolve_that_sittings_incident
    """
    env = setup_sitting(stage="CLOSED", start_at="2026-09-12T09:00:00Z",
                        scoring_admin_headers=_SCORING_ADMIN)
    admin, session = env["admin_headers"], env["session"]
    assert env["score_report"]["finalized_by_user_id"] == "admin-scoring-1"

    incident = file_incident(env, session, env["proctor"], severity="MINOR",
                            category="PROHIBITED_MATERIAL")
    opened = get_success_data(api.open_incident_review(incident["id"], _SCORING_ADMIN))
    assert opened["status"] == "UNDER_REVIEW"
    assert opened["resolved_by_user_id"] is None

    verdict = f.create_incident_resolution_payload(
        "DISMISS", resolution_note="Bag was outside the exam room")
    refused = api.resolve_security_incident(incident["id"], verdict, _SCORING_ADMIN)
    validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 403)
    pending = get_success_data(api.get_security_incident(incident["id"], admin))
    assert pending["status"] == "UNDER_REVIEW"
    assert pending["resolved_by_user_id"] is None

    dismissed = get_success_data(api.resolve_security_incident(
        incident["id"], verdict, _SECURITY_ADMIN))
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["resolved_by_user_id"] == "admin-security-1"

    cleared = get_success_data(api.get_exam_session(session["id"], admin))
    assert cleared["proctoring_status"] == "CLEARED"
    assert cleared["session_status"] == "CLOSED"
    untouched = get_success_data(api.get_proctor(env["proctor"]["id"], admin))
    assert untouched["substantiated_incident_weight_total"] == 0
    assert float(untouched["risk_score"]) == 0.0


def test_every_entity_backed_caller_is_confined_to_its_own_rows(api):
    """Five in-role calls reach outside their own scope and are refused, each paired
    with the in-scope call that proves the row and the role were both fine.

    PRD: "When `X-User-Role` is `ProviderAdmin`, `X-User-ID` is the `id` of the acting
    `TrainingProvider`; ownership checks on any resource that references a
    `TrainingProvider` compare the resource's provider foreign key — directly, or through
    the candidate, proctor or access-code batch the resource hangs off — to `X-User-ID`."

    PRD: "Any entity-backed caller addressing a resource outside its own scope is rejected
    with `ERR_FORBIDDEN_RESOURCE_SCOPE` (HTTP 403) — a provider touching another provider's
    batch, candidate or proctor; a candidate reading another candidate's sitting, code,
    accommodation, score report or certificate; a proctor acting on a sitting it is not
    assigned to; a health officer verifying a registration outside its own jurisdiction."

    PRD: "3. Ownership scope for entity-backed callers — `ERR_FORBIDDEN_RESOURCE_SCOPE`."

    Design: Corner/rbac/entity_backed_callers_cannot_reach_outside_their_own_scope
    """
    env = setup_landscape()
    admin, first_provider_headers = env["admin_headers"], env["provider_headers"]
    other_jurisdiction = add_jurisdiction(env, jurisdiction_code="TX-BEXAR",
                                          name="Bexar County Health District")
    other_provider = add_provider(env, prepay_cents=500000)
    own_candidate = add_candidate(env)
    other_candidate = add_candidate(env, provider=other_provider)
    own_proctor = add_proctor(env)
    other_proctor = add_proctor(env, provider=other_provider)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}])
    code, batch = assign_code(env, batch, own_candidate)
    session = schedule_session(env, own_candidate, code, "2026-09-12T09:00:00Z",
                               proctor=own_proctor)
    set_clock("2026-09-12T08:45:00Z", admin)
    identity = f.create_check_in_payload(id_document_expires_on="2030-01-31")

    poaching = api.create_access_code_batch(
        f.create_access_code_batch_payload(
            other_provider["id"], env["exam_form"]["id"],
            expires_at="2027-06-30T00:00:00Z",
            line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}]),
        first_provider_headers)
    validate_error(poaching, "ERR_FORBIDDEN_RESOURCE_SCOPE", 403)
    assert get_success_data(api.get_training_provider(
        other_provider["id"], admin))["credit_balance_cents"] == 500000

    enrolling = api.create_candidate(
        f.create_candidate_payload(
            other_provider["id"], env["jurisdiction"]["id"],
            full_name="Ghost Enrollee", email="ghost@x.test"),
        first_provider_headers)
    validate_error(enrolling, "ERR_FORBIDDEN_RESOURCE_SCOPE", 403)
    _, meta = validate_paginated(api.list_candidates(
        admin, params={"training_provider_id": other_provider["id"]}))
    assert meta["total_count"] == 1

    intruding = api.check_in_exam_session(
        session["id"], identity, make_proctor_headers(other_proctor["id"]))
    validate_error(intruding, "ERR_FORBIDDEN_RESOURCE_SCOPE", 403)
    assert get_success_data(api.get_exam_session(
        session["id"], admin))["session_status"] == "SCHEDULED"

    peeking = api.get_exam_session(
        session["id"], make_candidate_headers(other_candidate["id"]))
    validate_error(peeking, "ERR_FORBIDDEN_RESOURCE_SCOPE", 403)

    outside_officer = api.get_compliance_summary(
        own_candidate["id"], make_health_officer_headers(other_jurisdiction["id"]))
    validate_error(outside_officer, "ERR_FORBIDDEN_RESOURCE_SCOPE", 403)

    own_read = get_success_data(api.get_exam_session(
        session["id"], make_candidate_headers(own_candidate["id"])))
    assert own_read["id"] == session["id"]
    summary = get_success_data(api.get_compliance_summary(
        own_candidate["id"], env["officer_headers"]))
    assert summary["compliance_status"] == "NOT_CERTIFIED"
    checked_in = get_success_data(api.check_in_exam_session(
        session["id"], identity, make_proctor_headers(own_proctor["id"])))
    assert checked_in["session_status"] == "CHECKED_IN"
