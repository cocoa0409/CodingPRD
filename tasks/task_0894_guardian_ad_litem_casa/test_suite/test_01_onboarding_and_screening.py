"""Volunteer onboarding: registration, screening, background clearance, training,
and swearing-in gates.

Queue B (Corner) translations for the entities / state_machines / validations /
errors sections.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    assert_volunteer,
    ApiErrorId,
    TEST_USERS,
    NIL_UUID,
    create_volunteer_in_training,
    register_volunteer,
    set_clock,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_register_volunteer_applies_defaults(api):
    """PRD 3.1: "An optional max_caseload sets how many simultaneous active
    appointments the volunteer may hold; when omitted it defaults to 2."
    PRD 3.1: "A newly registered volunteer starts in PROSPECT status, with
    active_case_count at 0, background_status at NONE, sworn_in_at and
    deactivation_reason and background_expiry_date null, and training_hours_total
    at 0."

    Design: Corner/entities/create_volunteer_returns_201_with_defaults
    """
    resp = api.create_volunteer(
        {"full_name": "Val One", "email": "v1@casa.org", "home_zip": "94601"}, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_volunteer(data)
    assert data["max_caseload"] == 2, "max_caseload must default to 2"
    assert data["status"] == "PROSPECT"
    assert data["active_case_count"] == 0
    assert data["background_status"] == "NONE"


def test_get_unknown_volunteer_returns_not_found(api):
    """PRD 2.9: "the system validates identifiers left to right and rejects on the
    first identifier that does not resolve, using the not-found error for that
    resource: ERR_VOLUNTEER_NOT_FOUND, ERR_SUPERVISOR_NOT_FOUND, ..."

    Design: Corner/entities/get_volunteer_not_found_returns_404
    """
    resp = api.get_volunteer(NIL_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_FOUND.value)


def test_training_record_is_immutable_audit_entry(api):
    """PRD 2.4: "Two resources are immutable audit entries and therefore carry
    only id and created_at — they have neither updated_at nor version."

    Design: Corner/entities/training_record_is_immutable_no_version
    """
    vol = register_volunteer(api, email="v1@casa.org")
    resp = api.create_training_record(
        vol["id"], {"module_name": "CORE", "hours": 15, "completed_at": "2026-05-10T00:00:00Z"}, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert "id" in data and data["id"]
    assert "created_at" in data and data["created_at"]
    assert "version" not in data, "TrainingRecord must not carry a version field"
    assert "updated_at" not in data, "TrainingRecord must not carry an updated_at field"


def test_swear_in_prospect_rejected_invalid_state(api):
    """PRD 3.1: "The volunteer must currently be in `TRAINING`, else
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/swear_in_from_prospect_returns_invalid_state
    """
    vol = register_volunteer(api, email="v1@casa.org")
    resp = api.swear_in(vol["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    # Status is unchanged.
    after = get_success_data(api.get_volunteer(vol["id"], ADMIN))
    assert after["status"] == "PROSPECT"


def test_double_clear_background_check_rejected(api):
    """PRD 3.2: "Clearing or flagging a check that is not `PENDING` fails with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/double_clear_background_returns_invalid_state
    """
    vol = register_volunteer(api, email="v1@casa.org")
    get_success_data(api.start_screening(vol["id"], ADMIN))
    bg = get_success_data(api.create_background_check(vol["id"], {"check_type": "STATE_ONLY"}, ADMIN))
    get_success_data(api.clear_background_check(bg["id"], ADMIN))
    resp = api.clear_background_check(bg["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_clearing_newest_check_auto_advances_to_training(api):
    """PRD 3.2: "If the owning volunteer is in SCREENING and this is that
    volunteer's newest check, clearing also drives the automatic SCREENING →
    TRAINING transition and recomputes the volunteer's background_status to
    CLEARED along with background_expiry_date."

    Design: Corner/state_machines/background_clear_auto_advances_volunteer_to_training
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    vol = register_volunteer(api, email="v1@casa.org")
    get_success_data(api.start_screening(vol["id"], ADMIN))
    bg = get_success_data(api.create_background_check(vol["id"], {"check_type": "STATE_AND_FEDERAL"}, ADMIN))
    get_success_data(api.clear_background_check(bg["id"], ADMIN))
    after = get_success_data(api.get_volunteer(vol["id"], ADMIN))
    assert after["status"] == "TRAINING"
    assert after["background_status"] == "CLEARED"


def test_swear_in_training_incomplete_rejected_422(api):
    """PRD 3.1: "Finally, training_hours_total must be at least 30 hours, else
    ERR_TRAINING_INCOMPLETE — the boundary is inclusive, so exactly 30 hours
    passes while 29 fails."

    Design: Corner/validations/swear_in_training_incomplete_returns_422
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    vol = create_volunteer_in_training(api, email="v1@casa.org", training_hours=20)
    assert vol["status"] == "TRAINING"
    resp = api.swear_in(vol["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_TRAINING_INCOMPLETE.value)


def test_swear_in_background_expired_rejected_422(api):
    """PRD 3.1: "The volunteer's `background_status` must be `CLEARED` with the
    logical clock strictly before `background_expiry_date`, else
    `ERR_BACKGROUND_EXPIRED`."
    PRD 3.2: "its read-only `expiry_date` is computed as `cleared_at` plus 365 days."

    Design: Corner/errors/swear_in_background_expired_returns_422
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    vol = create_volunteer_in_training(api, email="v1@casa.org", training_hours=30)
    # Advance past the 365-day clearance validity window.
    set_clock(api, "2027-07-06T00:00:00Z")
    resp = api.swear_in(vol["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_BACKGROUND_EXPIRED.value)
