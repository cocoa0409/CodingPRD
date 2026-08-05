"""Intake CRUD, referral assessment fork, access control, and resolution errors.

Queue B (corner): entities, referral state_machines, errors, RBAC.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, ApiErrorId, TEST_USERS, make_therapist_headers, make_role_headers,
    create_insurance_client_payload, create_self_pay_client_payload,
    create_therapist_payload, assess_payload,
)
from test_helpers import fixtures as fx


# --------------------------------------------------------------------- entities
def test_create_client_returns_201_with_system_fields(api):
    """PRD §2.4: "an integer `version` that begins at 1 on creation and increments
    by exactly 1 on every mutation of that resource."
    PRD §3.1: "A newly created client starts in `INTAKE` status with
    `insurance_visits_used` at 0 and `insurance_visits_remaining` equal to
    `insurance_visits_authorized`".

    Design: Corner/entities/create_client_returns_201_with_system_fields
    """
    resp = api.create_client(
        create_self_pay_client_payload(full_name="New Client",
                                       household_income_cents=4_000_000, household_size=3),
        TEST_USERS["intake_headers"])
    data = validate_success(resp, expected_status=201)
    assert is_valid_uuid(data["id"]), "id must be a non-empty UUID"
    assert data["status"] == "INTAKE"
    assert data["version"] == 1
    assert data.get("created_at"), "created_at must be present"


def test_create_client_missing_payer_type_returns_422(api):
    """PRD §2.7: "Field validation — required fields present, types correct, enum
    members valid, numeric ranges satisfied, and `end_utc` strictly later than
    `start_utc` (`ERR_VALIDATION`, 422)."

    Design: Corner/entities/create_client_missing_payer_type_returns_422
    """
    resp = api.create_client({"full_name": "No Payer", "dob": "2015-01-01"},
                             TEST_USERS["intake_headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_get_client_nonexistent_returns_404(api):
    """PRD §2.6: "the first identifier that does not resolve produces that entity's
    specific not-found error (for example `ERR_CLIENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_SESSION_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_SUPERBILL_NOT_FOUND`)."

    Design: Corner/entities/get_client_nonexistent_returns_404
    """
    resp = api.get_client("00000000-0000-0000-0000-000000000000", TEST_USERS["intake_headers"])
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_FOUND.value)


def test_create_therapist_invalid_discipline_returns_422(api):
    """PRD §3.1: "An `IntakeCoordinator` registers a `Therapist` by supplying a
    `full_name`, a `discipline` of either `MUSIC` or `ART`, and a `credential`".
    PRD §2.7: "Field validation — required fields present, types correct, enum
    members valid, numeric ranges satisfied, and `end_utc` strictly later than
    `start_utc` (`ERR_VALIDATION`, 422)."

    Design: Corner/entities/create_therapist_invalid_discipline_returns_422
    """
    resp = api.create_therapist(create_therapist_payload(discipline="DANCE", credential="X"),
                                TEST_USERS["intake_headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_computed_visits_remaining_on_client_create(api):
    """PRD §3.1: "`insurance_visits_remaining` is always the authorized count minus
    the used count."

    Design: Corner/entities/computed_visits_remaining_on_client_create
    """
    resp = api.create_client(
        create_insurance_client_payload(full_name="Ins C", insurance_visits_authorized=7,
                                        insurance_contracted_rate_cents=12503),
        TEST_USERS["intake_headers"])
    data = validate_success(resp, expected_status=201)
    assert data["insurance_visits_used"] == 0
    assert data["insurance_visits_remaining"] == 7


def test_list_sessions_pagination_returns_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_sessions_pagination_returns_envelope
    """
    resp = api.list_sessions(TEST_USERS["intake_headers"], params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    assert "total_count" in meta and "has_more" in meta


# ------------------------------------------------------------ referral fork
def test_referral_decline_branch_sets_declined(api):
    """PRD §3.1: "a recommendation of `NOT_APPROPRIATE` instead routes it
    `RECEIVED → DECLINED`, a terminal outcome." PRD §3.1: "On assessment the referral
    records `assessed_by_therapist_id` as the acting therapist's identity and stores
    the recommendation and baseline."

    Design: Corner/state_machines/referral_decline_branch_sets_declined
    """
    ther = fx.new_therapist(api)
    client = fx.new_self_pay_client(api)
    ref = fx.new_referral(api, client["id"])
    resp = api.assess_referral(ref["id"], assess_payload(recommendation="NOT_APPROPRIATE",
                                                          baseline_score=12),
                               make_therapist_headers(ther["id"]))
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "DECLINED"
    assert data["assessed_by_therapist_id"] == ther["id"]


def test_assess_declined_referral_rejected(api):
    """PRD §3.1: "Assessment is only permitted while the referral is `RECEIVED`;
    otherwise the transition is rejected with `ERR_REFERRAL_INVALID_STATE`."

    Design: Corner/state_machines/assess_declined_referral_rejected
    """
    ther = fx.new_therapist(api)
    client = fx.new_self_pay_client(api)
    ref = fx.new_referral(api, client["id"])
    fx.assess(api, ref["id"], ther["id"], recommendation="NOT_APPROPRIATE", baseline_score=10)
    resp = api.assess_referral(ref["id"], assess_payload(baseline_score=40),
                               make_therapist_headers(ther["id"]))
    validate_error(resp, ApiErrorId.ERR_REFERRAL_INVALID_STATE.value)


# ------------------------------------------------------------ resolution errors
def test_session_create_therapist_not_found(api):
    """PRD §2.6: "Body foreign keys are checked after the path, each mapping to its
    own not-found error: a missing `therapist_id` yields `ERR_THERAPIST_NOT_FOUND`".

    Design: Corner/errors/session_create_therapist_not_found
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    bogus = "00000000-0000-0000-0000-0000000000aa"
    resp = api.create_session(
        {"therapist_id": bogus, "room_id": ctx["room_id"], "plan_id": ctx["plan_id"],
         "goal_id": ctx["goal_id"], "modality": "INDIVIDUAL",
         "start_utc": "2026-06-01T09:00:00Z", "end_utc": "2026-06-01T10:00:00Z", "capacity": 1},
        make_role_headers(bogus, "Therapist"))
    validate_error(resp, ApiErrorId.ERR_THERAPIST_NOT_FOUND.value)


def test_superbill_create_session_not_found(api):
    """PRD §2.6: "When a request references resources — through path identifiers or
    through foreign-key fields in the body — the server validates their existence
    before applying any business rule."

    Design: Corner/errors/superbill_create_session_not_found
    """
    client = fx.new_insurance_client(api, insurance_visits_authorized=3)
    resp = api.create_superbill(
        {"session_id": "00000000-0000-0000-0000-0000000000bb", "client_id": client["id"]},
        TEST_USERS["billing_headers"])
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_FOUND.value)


def test_progress_note_enrollment_not_found(api):
    """PRD §2.6: "Path identifiers are checked left to right; the first identifier
    that does not resolve produces that entity's specific not-found error (for
    example `ERR_CLIENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`,
    `ERR_ENROLLMENT_NOT_FOUND`, `ERR_SUPERBILL_NOT_FOUND`)."

    Design: Corner/errors/progress_note_enrollment_not_found
    """
    ther = fx.new_therapist(api)
    resp = api.create_progress_note(
        "00000000-0000-0000-0000-0000000000cc",
        {"narrative": "n", "rubric_score": 50, "outcome_rating": "MAINTAINED"},
        make_therapist_headers(ther["id"]))
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND.value)


def test_void_superbill_not_found(api):
    """PRD §2.6: "Path identifiers are checked left to right; the first identifier
    that does not resolve produces that entity's specific not-found error (for
    example `ERR_CLIENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`,
    `ERR_ENROLLMENT_NOT_FOUND`, `ERR_SUPERBILL_NOT_FOUND`)."

    Design: Corner/errors/void_superbill_not_found
    """
    resp = api.void_superbill("00000000-0000-0000-0000-0000000000dd", TEST_USERS["billing_headers"])
    validate_error(resp, ApiErrorId.ERR_SUPERBILL_NOT_FOUND.value)


# ------------------------------------------------------------ access control
def test_therapist_cannot_create_treatment_plan(api):
    """PRD §2.1: "When the role is recognized but is not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "Each write operation is otherwise restricted to the single role named
    in its endpoint definition (§4)."

    Design: Corner/RBAC/therapist_cannot_create_treatment_plan
    """
    ther = fx.new_therapist(api)
    client = fx.new_self_pay_client(api)
    ref = fx.new_referral(api, client["id"])
    fx.assess(api, ref["id"], ther["id"])
    resp = api.create_treatment_plan(
        client["id"],
        {"referral_id": ref["id"], "discipline": "MUSIC", "weekly_frequency": 1,
         "expected_client_version": client["version"]},
        make_therapist_headers(ther["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_billing_specialist_cannot_schedule_session(api):
    """PRD §2.1: "When the role is recognized but is not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "Each write operation is otherwise restricted to the single role named
    in its endpoint definition (§4)."

    Design: Corner/RBAC/billing_specialist_cannot_schedule_session
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    resp = api.create_session(
        {"therapist_id": ctx["ther_id"], "room_id": ctx["room_id"], "plan_id": ctx["plan_id"],
         "goal_id": ctx["goal_id"], "modality": "INDIVIDUAL",
         "start_utc": "2026-06-01T09:00:00Z", "end_utc": "2026-06-01T10:00:00Z", "capacity": 1},
        TEST_USERS["billing_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_non_owner_therapist_cannot_complete_session(api):
    """PRD §2.1: "any write against a session (scheduling, completing, cancelling,
    enrolling a client, or writing a progress note under one of its enrollments)
    requires that the session's `therapist_id` equal the acting `X-User-ID`,
    otherwise the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/RBAC/non_owner_therapist_cannot_complete_session
    """
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    other = fx.new_therapist(api, full_name="T2")
    session = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"])
    fx.enroll(api, session["id"], ctx["client_id"], ctx["ther_id"])
    fx.set_clock(api, "2026-06-01T09:30:00Z")
    resp = api.complete_session(session["id"], {"attended_client_ids": [ctx["client_id"]]},
                                make_therapist_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_unauthenticated_missing_role_rejected(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/RBAC/unauthenticated_missing_role_rejected
    """
    resp = api.get_client("00000000-0000-0000-0000-000000000000",
                          make_role_headers("guest-1", "Guest"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
