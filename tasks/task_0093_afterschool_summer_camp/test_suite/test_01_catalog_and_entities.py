"""Catalog construction, entity CRUD basics, and program/session/form lifecycle.

Covers corner-design instances from the entities, state_machines, calculations, and
errors sections, plus the cross_entity_state_dependency difficulty instance that gates
session opening on program publication.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    assert_guardian,
    assert_child,
    assert_authorization_form,
    create_guardian_payload,
    create_child_payload,
    create_program_payload,
    create_session_payload,
    create_authorization_form_payload,
    make_guardian_headers,
    # fixtures
    create_guardian,
    create_child,
    setup_eligible_child,
)

DIRECTOR = TEST_USERS["program_director_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
def test_register_guardian_returns_201_with_system_fields(api):
    """PRD §3.3: "A prospective family begins as a Guardian, registered by an anonymous
    caller with an email (the login identity, which must be unique among guardians when
    compared case-insensitively and must be non-empty), a full_name, a phone, and a
    home_zip of exactly five digits".
    PRD §2.4: "version — a system-managed integer that starts at creation and increments
    by one on every mutation of the resource."

    Design: Corner/entities/create_guardian_returns_201_with_fields
    """
    resp = api.create_guardian(create_guardian_payload(full_name="New G"), ANON)
    data = validate_success(resp, 201)
    assert_guardian(data)
    assert data["version"] == 1, f"fresh guardian version must be 1, got {data['version']}"
    assert data["full_name"] == "New G"


def test_get_nonexistent_child_returns_not_found(api):
    """PRD §2.6: "when an identifier in the path or body refers to something that does not
    exist, the request is rejected with ERR_NOT_FOUND."

    Design: Corner/entities/get_child_not_found_returns_404
    """
    guardian = create_guardian()
    resp = api.get_child(NON_EXISTENT_UUID, make_guardian_headers(guardian["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_child_missing_first_name_rejected(api):
    """PRD §2.10: "the structural well-formedness of the request body (ERR_INVALID_REQUEST:
    a required field is missing, an enum value is outside its declared set, or a numeric
    field is out of its declared bounds)."

    Design: Corner/entities/create_child_missing_required_first_name_returns_invalid_request
    """
    guardian = create_guardian()
    gh = make_guardian_headers(guardian["id"])
    payload = create_child_payload(guardian["id"])
    payload.pop("first_name")
    resp = api.create_child(payload, gh)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_child_defaults_household_size_to_one(api):
    """PRD §3.3: "an optional household_size — the number of people in the household, which
    feeds scholarship income-tier eligibility, defaults to 1, and must be at least 1."

    Design: Corner/entities/create_child_default_household_size_applied
    """
    guardian = create_guardian()
    gh = make_guardian_headers(guardian["id"])
    payload = create_child_payload(guardian["id"], first_name="Def")
    # household_size intentionally omitted.
    resp = api.create_child(payload, gh)
    data = validate_success(resp, 201)
    assert data["household_size"] == 1, f"omitted household_size must default to 1, got {data['household_size']}"


def test_child_age_computed_against_session_reference_date(api):
    """PRD §3.4: "Take the reference year minus the birth year; then, if the reference
    date's month-and-day falls before the child's birth month-and-day, subtract one year
    because the birthday has not yet been reached on the reference date."
    PRD §3.3: "A child's age_years is never supplied; it is computed on demand against a
    session's reference date as described in §3.4."

    Design: Corner/entities/child_age_computed_field_ignores_client_input
    """
    guardian = create_guardian()
    gh = make_guardian_headers(guardian["id"])
    # Born 2016-03-01; ref 2026-06-01 -> birthday already reached -> age 10.
    child = create_child(guardian["id"], first_name="Comp", birth_date="2016-03-01")
    program = api_client.create_program(
        create_program_payload(name="Age Camp", program_type="AFTERSCHOOL", min_age=5, max_age=12),
        DIRECTOR,
    ).json()["data"]
    session = api_client.create_session(
        create_session_payload(program["id"], title="Age", age_group_min=8, age_group_max=12,
                               age_as_of_date="2026-06-01", base_weekly_tuition_cents=15000),
        DIRECTOR,
    ).json()["data"]
    resp = api.get_child_age_eligibility(child["id"], gh, params={"session_id": session["id"]})
    data = validate_success(resp, 200)
    assert data["age_years"] == 10, f"expected computed age 10, got {data['age_years']}"


def test_session_group_outside_program_band_rejected(api):
    """PRD §3.1: "The session's age group must sit within the program's band: age_group_min
    must be at least the program's min_age, and age_group_max must be at most the program's
    max_age and not below age_group_min. A session group that falls outside its program's
    range is rejected with ERR_INVALID_AGE_RANGE."

    Design: Corner/entities/invalid_age_range_session_group_outside_program
    """
    program = api_client.create_program(
        create_program_payload(name="Range Camp", program_type="CAMP", min_age=5, max_age=10),
        DIRECTOR,
    ).json()["data"]
    resp = api.create_session(
        create_session_payload(program["id"], title="Bad", age_group_min=8, age_group_max=14),
        DIRECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_AGE_RANGE.value)


def test_create_program_bad_program_type_enum_rejected(api):
    """PRD §2.10: "ERR_INVALID_REQUEST: a required field is missing, an enum value is
    outside its declared set, or a numeric field is out of its declared bounds."
    PRD §3.1: "A program's type is one of AFTERSCHOOL or CAMP".

    Design: Corner/errors/invalid_request_bad_enum_program_type
    """
    resp = api.create_program(
        create_program_payload(name="Bad Enum", program_type="SUMMER", min_age=5, max_age=12),
        DIRECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# State machines — program/session lifecycle
# ---------------------------------------------------------------------------
def test_publish_already_published_program_rejected(api):
    """PRD §3.1: "Attempting either transition from a state that does not permit it yields
    ERR_INVALID_STATE."

    Design: Corner/state_machines/publish_already_published_program_returns_invalid_state
    """
    program = api_client.create_program(create_program_payload(name="Dbl Pub"), DIRECTOR).json()["data"]
    api_client.create_session(create_session_payload(program["id"], title="Dp"), DIRECTOR)
    validate_success(api_client.publish_program(program["id"], DIRECTOR), 200)
    resp = api.publish_program(program["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_publish_program_with_no_session_rejected(api):
    """PRD §3.1: "A program moves from DRAFT to PUBLISHED only when it holds at least one
    session in SCHEDULED or OPEN; a publish attempt against a program with no such session
    is rejected with ERR_NO_SESSION_FOR_PUBLISH".

    Design: Corner/state_machines/publish_program_with_no_session_rejected
    """
    program = api_client.create_program(create_program_payload(name="No Sess"), DIRECTOR).json()["data"]
    resp = api.publish_program(program["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_NO_SESSION_FOR_PUBLISH.value)


def test_cancel_already_cancelled_session_rejected(api):
    """PRD §3.2: "A cancel requested from any state other than SCHEDULED or OPEN is
    rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_terminal_session_returns_invalid_state
    """
    program = api_client.create_program(create_program_payload(name="Term Camp"), DIRECTOR).json()["data"]
    session = api_client.create_session(create_session_payload(program["id"], title="Tm"), DIRECTOR).json()["data"]
    validate_success(api_client.cancel_session(session["id"], DIRECTOR), 200)
    resp = api.cancel_session(session["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# State machines — authorization form lifecycle
# ---------------------------------------------------------------------------
def test_approved_form_can_be_revoked_by_owning_guardian(api):
    """PRD §3.3: "The owning guardian may revoke a form, moving it to the terminal REVOKED
    state from either SUBMITTED or APPROVED".

    Design: Corner/state_machines/auth_form_approve_then_revoke_compensation
    """
    guardian = create_guardian()
    gh = make_guardian_headers(guardian["id"])
    child = create_child(guardian["id"], first_name="Ar")
    form = validate_success(
        api_client.create_authorization_form(
            create_authorization_form_payload(child["id"], "MEDICAL", medication_notes="epipen"), gh
        ),
        201,
    )
    validate_success(api_client.approve_authorization_form(form["id"], DIRECTOR), 200)
    resp = api.revoke_authorization_form(form["id"], gh)
    data = validate_success(resp, 200)
    assert_authorization_form(data)
    assert data["status"] == "REVOKED", f"revoked form must be REVOKED, got {data['status']}"


# ---------------------------------------------------------------------------
# Cross-entity state dependency (difficulty): session open requires program published
# ---------------------------------------------------------------------------
def test_open_session_under_draft_program_rejected(api):
    """PRD §3.2: "Opening is gated on two conditions: the parent program must already be
    PUBLISHED — an attempt to open under an unpublished program is rejected with
    ERR_PROGRAM_NOT_PUBLISHED".

    Design: Difficulty/cross_entity_state_dependency/session_open_requires_program_published
    """
    program = api_client.create_program(create_program_payload(name="Draft Camp"), DIRECTOR).json()["data"]
    session = api_client.create_session(create_session_payload(program["id"], title="Dr7"), DIRECTOR).json()["data"]
    api_client.create_weekly_offering({"session_id": session["id"], "week_start": "2026-06-08"}, DIRECTOR)
    # Program never published.
    resp = api.open_session(session["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_PUBLISHED.value)


def test_open_session_under_published_program_succeeds(api):
    """PRD §3.2: "Before families can enroll, a director opens a session, advancing it
    SCHEDULED -> OPEN. Opening is gated on two conditions: the parent program must already
    be PUBLISHED ... and the session must already have at least one weekly offering laid
    out beneath it."

    Design: Difficulty/cross_entity_state_dependency/session_open_requires_program_published
    """
    program = api_client.create_program(create_program_payload(name="Pub OK Camp"), DIRECTOR).json()["data"]
    session = api_client.create_session(create_session_payload(program["id"], title="Ok7"), DIRECTOR).json()["data"]
    api_client.create_weekly_offering({"session_id": session["id"], "week_start": "2026-06-08"}, DIRECTOR)
    validate_success(api_client.publish_program(program["id"], DIRECTOR), 200)
    resp = api.open_session(session["id"], DIRECTOR)
    data = validate_success(resp, 200)
    assert data["status"] == "OPEN", f"session must be OPEN after open, got {data['status']}"
