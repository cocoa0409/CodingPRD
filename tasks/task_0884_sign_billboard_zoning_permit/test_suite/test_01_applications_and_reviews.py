"""Parcels, sign-application intake, and the two parallel dimensional/overlay reviews."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID, ApiErrorId,
    create_parcel_payload, create_application_payload,
    make_planner_headers, make_applicant_headers, make_anonymous_headers,
    assert_parcel, assert_application,
    create_parcel, create_applicant, create_application, create_submitted_application,
    review_application,
)


# ── Parcel creation & defaults ───────────────────────────────────────────────
def test_create_parcel_initializes_slot_ledger(api):
    """PRD §3.1: "On creation, the parcel's `active_permit_count` is 0 and its
    `available_sign_slots` equals `max_signs`."

    Design: Corner/entities/create_parcel_returns_201_envelope_and_slot_ledger
    """
    resp = api.create_parcel(create_parcel_payload(max_signs=5), make_planner_headers())
    data = validate_success(resp, expected_status=201)
    assert_parcel(data)
    assert data["available_sign_slots"] == 5
    assert data["active_permit_count"] == 0


def test_create_parcel_response_type_object(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/create_parcel_returns_201_envelope_and_slot_ledger
    """
    resp = api.create_parcel(create_parcel_payload(max_signs=5), make_planner_headers())
    validate_success(resp, expected_status=201)
    body = resp.json()
    assert body["response_type"] == "object"


def test_parcel_overlay_flags_default_false(api):
    """PRD §3.1: "two optional overlay flags, `historic_overlay` and `corridor_overlay`,
    each defaulting to false when omitted"

    Design: Corner/entities/parcel_default_historic_overlay_false
    """
    payload = create_parcel_payload()
    payload.pop("historic_overlay", None)
    payload.pop("corridor_overlay", None)
    resp = api.create_parcel(payload, make_planner_headers())
    data = validate_success(resp, expected_status=201)
    assert data["historic_overlay"] is False
    assert data["corridor_overlay"] is False


# ── Application system fields & input validation ─────────────────────────────
def test_application_created_draft_pending_version_one(api):
    """PRD §3.2: "An applicant opens a `SignApplication` in `DRAFT` status".
    PRD §3.2: "At creation both review axes begin at `PENDING`."
    PRD §2.4: "The `version` begins at 1 on creation and increments by one on every
    mutation that changes the resource".

    Design: Corner/entities/application_system_fields_generated
    """
    parcel = create_parcel(api)
    applicant = create_applicant(api)
    resp = api.create_application(
        create_application_payload(parcel["id"], applicant["id"]),
        make_applicant_headers(applicant["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert_application(data)
    assert data["version"] == 1
    assert data["status"] == "DRAFT"
    assert data["dimensional_review"] == "PENDING"
    assert data["overlay_review"] == "PENDING"


def test_application_missing_required_field_rejected(api):
    """PRD §2.8: "on every write, required fields must be present and correctly typed,
    numeric quantities must be non-negative, and enum values must be members of their
    allowed set; failures yield `ERR_VALIDATION`".

    Design: Corner/entities/application_missing_required_field_returns_validation
    """
    parcel = create_parcel(api)
    applicant = create_applicant(api)
    payload = create_application_payload(parcel["id"], applicant["id"])
    payload.pop("requested_area_sqft")
    resp = api.create_application(payload, make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_application_invalid_sign_type_enum_rejected(api):
    """PRD §2.8: "enum values must be members of their allowed set; failures yield
    `ERR_VALIDATION`, or `ERR_INVALID_ENUM` for a bad enum value".

    Design: Corner/entities/application_invalid_enum_sign_type_rejected
    """
    parcel = create_parcel(api)
    applicant = create_applicant(api)
    payload = create_application_payload(parcel["id"], applicant["id"], sign_type="NEON")
    resp = api.create_application(payload, make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


def test_get_unknown_application_not_found(api):
    """PRD §2.8: "for endpoints keyed on a typed root, a missing root yields the specific
    code `ERR_APPLICATION_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, or
    `ERR_BILLBOARD_NOT_FOUND`."

    Design: Corner/entities/get_application_not_found
    """
    resp = api.get_application(NON_EXISTENT_UUID, make_planner_headers())
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND)


# ── State legality on submit / decide ────────────────────────────────────────
def test_submit_already_submitted_rejected(api):
    """PRD §3.2: "Submitting a draft advances the application from `DRAFT` to `SUBMITTED`,
    provided all requested dimension fields are present."
    PRD §2.8: "the target resource must be in a state from which the requested transition
    is legal, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/submit_already_submitted_application_invalid_state
    """
    parcel, applicant, app = create_submitted_application(api)
    resp = api.submit_application(app["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_decide_denied_application_is_terminal(api):
    """PRD §3.2: "A denial advances `SUBMITTED → DENIED` unconditionally. Both `DENIED`
    and `PERMITTED` are terminal for an application."
    PRD §2.8: "the target resource must be in a state from which the requested transition
    is legal, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/decide_denied_application_terminal_lockdown
    """
    parcel, applicant, app = create_submitted_application(api)
    denied = validate_success(
        api.decide_application(app["id"], {"decision": "DENY"}, make_planner_headers())
    )
    assert denied["status"] == "DENIED"
    resp = api.decide_application(app["id"], {"decision": "APPROVE"}, make_planner_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ── Parallel review axes (Difficulty) ────────────────────────────────────────
def test_dimensional_pass_leaves_overlay_pending(api):
    """PRD §3.2: "From this point the application carries **two independent review axes**
    that evolve separately from one another and from the application's own `status`."

    Design: Difficulty/non_linear_state_machine/application_parallel_review_axes_independent
    """
    parcel, applicant, app = create_submitted_application(api)
    updated = review_application(api, app["id"], "DIMENSIONAL", "PASS")
    assert updated["dimensional_review"] == "PASS"
    assert updated["overlay_review"] == "PENDING"


def test_overlay_cleared_leaves_dimensional_pending(api):
    """PRD §3.2: "From this point the application carries **two independent review axes**
    that evolve separately from one another and from the application's own `status`."

    Design: Difficulty/non_linear_state_machine/application_parallel_review_axes_independent
    """
    parcel, applicant, app = create_submitted_application(api)
    updated = review_application(api, app["id"], "OVERLAY", "CLEARED")
    assert updated["overlay_review"] == "CLEARED"
    assert updated["dimensional_review"] == "PENDING"


# ── Dimensional boundary: area == max is inclusive (Difficulty) ──────────────
def test_area_exactly_at_max_passes_dimensional(api):
    """PRD §3.2: "a `PASS` requires that this effective area be at most the parcel's
    `max_sign_area_sqft` (the ceiling is inclusive — equality passes), else
    `ERR_SIGN_AREA_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/area_equals_max_is_allowed_inclusive
    """
    parcel = create_parcel(api, max_sign_area_sqft=100)
    applicant = create_applicant(api)
    parcel, applicant, app = create_submitted_application(
        api, parcel, applicant, requested_area_sqft=100)
    updated = review_application(api, app["id"], "DIMENSIONAL", "PASS")
    assert updated["dimensional_review"] == "PASS"


def test_area_just_below_max_passes_dimensional(api):
    """PRD §3.2: "a `PASS` requires that this effective area be at most the parcel's
    `max_sign_area_sqft` (the ceiling is inclusive — equality passes), else
    `ERR_SIGN_AREA_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/area_equals_max_is_allowed_inclusive
    """
    parcel = create_parcel(api, max_sign_area_sqft=100)
    applicant = create_applicant(api)
    parcel, applicant, app = create_submitted_application(
        api, parcel, applicant, requested_area_sqft=99)
    updated = review_application(api, app["id"], "DIMENSIONAL", "PASS")
    assert updated["dimensional_review"] == "PASS"


# ── Dimensional / overlay constraint violations (Corner) ─────────────────────
def test_area_above_max_rejected(api):
    """PRD §3.2: "a `PASS` requires that this effective area be at most the parcel's
    `max_sign_area_sqft` (the ceiling is inclusive — equality passes), else
    `ERR_SIGN_AREA_EXCEEDED`."

    Design: Corner/validations/dimensional_area_exceeds_max_rejected
    """
    parcel = create_parcel(api, max_sign_area_sqft=100)
    applicant = create_applicant(api)
    parcel, applicant, app = create_submitted_application(
        api, parcel, applicant, requested_area_sqft=100.5)
    resp = api.review_application(
        app["id"], {"review_type": "DIMENSIONAL", "outcome": "PASS"}, make_planner_headers())
    validate_error(resp, ApiErrorId.ERR_SIGN_AREA_EXCEEDED)


def test_height_above_max_rejected(api):
    """PRD §3.2: "Likewise the effective height must be at most `max_height_ft`, else
    `ERR_SIGN_HEIGHT_EXCEEDED`; the `requested_setback_ft` must be at least the parcel's
    `min_setback_ft`, else `ERR_SETBACK_INSUFFICIENT`; and the requested illumination
    class must not outrank what the parcel allows, else `ERR_ILLUMINATION_NOT_ALLOWED`."

    Design: Corner/validations/dimensional_height_exceeds_max_rejected
    """
    parcel = create_parcel(api, max_height_ft=50)
    applicant = create_applicant(api)
    parcel, applicant, app = create_submitted_application(
        api, parcel, applicant, sign_type="MONUMENT", requested_height_ft=60)
    resp = api.review_application(
        app["id"], {"review_type": "DIMENSIONAL", "outcome": "PASS"}, make_planner_headers())
    validate_error(resp, ApiErrorId.ERR_SIGN_HEIGHT_EXCEEDED)


def test_setback_below_min_rejected(api):
    """PRD §3.2: "Likewise the effective height must be at most `max_height_ft`, else
    `ERR_SIGN_HEIGHT_EXCEEDED`; the `requested_setback_ft` must be at least the parcel's
    `min_setback_ft`, else `ERR_SETBACK_INSUFFICIENT`; and the requested illumination
    class must not outrank what the parcel allows, else `ERR_ILLUMINATION_NOT_ALLOWED`."

    Design: Corner/validations/dimensional_setback_below_min_rejected
    """
    parcel = create_parcel(api, min_setback_ft=10)
    applicant = create_applicant(api)
    parcel, applicant, app = create_submitted_application(
        api, parcel, applicant, requested_setback_ft=5)
    resp = api.review_application(
        app["id"], {"review_type": "DIMENSIONAL", "outcome": "PASS"}, make_planner_headers())
    validate_error(resp, ApiErrorId.ERR_SETBACK_INSUFFICIENT)


def test_illumination_above_allowed_rejected(api):
    """PRD §3.2: "the check passes when the rank of `requested_illumination` is at most
    the rank of the parcel's `allowed_illumination`, unless an `ILLUMINATION` variance
    has been granted for the application, which lifts the ceiling."

    Design: Corner/calculations/illumination_rank_exceeds_allowed_rejected
    """
    parcel = create_parcel(api, allowed_illumination="NONE")
    applicant = create_applicant(api)
    parcel, applicant, app = create_submitted_application(
        api, parcel, applicant, requested_illumination="DIGITAL_DISPLAY")
    resp = api.review_application(
        app["id"], {"review_type": "DIMENSIONAL", "outcome": "PASS"}, make_planner_headers())
    validate_error(resp, ApiErrorId.ERR_ILLUMINATION_NOT_ALLOWED)


def test_overlay_cleared_on_historic_parcel_requires_variance(api):
    """PRD §3.2: "clearing a historic-overlay parcel without that granted variance is
    rejected with `ERR_HISTORIC_OVERLAY_REVIEW_REQUIRED`."

    Design: Corner/validations/overlay_cleared_on_historic_parcel_requires_variance
    """
    parcel = create_parcel(api, historic_overlay=True)
    applicant = create_applicant(api)
    parcel, applicant, app = create_submitted_application(api, parcel, applicant)
    resp = api.review_application(
        app["id"], {"review_type": "OVERLAY", "outcome": "CLEARED"}, make_planner_headers())
    validate_error(resp, ApiErrorId.ERR_HISTORIC_OVERLAY_REVIEW_REQUIRED)


# ── RBAC gates ───────────────────────────────────────────────────────────────
def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_missing_headers_returns_401
    """
    resp = api.create_parcel(create_parcel_payload(), make_anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_applicant_cannot_create_parcel(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership-scoped role acts on a resource it
    does not own — the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/applicant_cannot_create_parcel_unauthorized
    """
    applicant = create_applicant(api)
    resp = api.create_parcel(create_parcel_payload(), make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
