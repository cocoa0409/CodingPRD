"""Creation, defaults, system fields, immutability, boundary rejection, listing,
error-envelope, and RBAC tests. Pinned to PRD §2.1, §2.2, §2.3, §2.4, §2.9,
§2.10, §3.1, §3.2, §3.3, §3.8.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    fixtures, factories, ApiErrorId, NON_EXISTENT_UUID,
    build_user_headers,
    make_wound_clinician_headers, make_hyperbaric_tech_headers,
)


# =============================================================================
# Corner: entities section
# =============================================================================

def test_create_patient_returns_201_all_fields(api):
    """PRD §3.2: "A patient enters the system when an IntakeCoordinator creates a
    Patient under a center_id with an mrn, a full_name, and the payer_policy_id
    linking the patient to their coverage. A patient begins in INTAKE status".
    PRD §3.2: "A patient carries a latest_wound_area_cm2 that starts at zero".

    Design: Corner/entities/create_patient_returns_201_all_fields
    """
    center = fixtures.create_center()
    policy = fixtures.create_payer_policy(center["id"])
    resp = api.create_patient(
        factories.create_patient_payload(center["id"], policy["id"],
                                         mrn="MRN-1", full_name="Ann"),
        fixtures.INTAKE)
    data = validate_success(resp, 201)
    assert data["status"] == "INTAKE"
    assert data["latest_wound_area_cm2"] == 0


def test_get_patient_not_found_returns_404(api):
    """PRD §2.9: "existence of every path- and body-referenced resource, failing
    with the applicable not-found code (the generic ERR_NOT_FOUND or a
    resource-specific code such as ... ERR_PATIENT_NOT_FOUND ...)".
    GET on an unknown patient UUID returns ERR_PATIENT_NOT_FOUND (404).

    Design: Corner/entities/get_patient_not_found_returns_404
    """
    resp = api.get_patient(NON_EXISTENT_UUID, fixtures.INTAKE)
    validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_FOUND.value)


def test_create_assessment_missing_required_field_returns_400(api):
    """PRD §2.10: "Creation requests are subject to structural validation, failing
    with ERR_INVALID_REQUEST when violated." PRD §3.3: "A WoundClinician records a
    WoundAssessment for a patient by patient_id, supplying the stage, the
    length_cm, the width_cm, the tissue_type, and an optional infected flag".
    Omitting the required stage returns ERR_INVALID_REQUEST (400).

    Design: Corner/entities/create_assessment_missing_required_field_returns_400
    """
    base = fixtures.setup_center_staff_patient(mrn="Mreq")
    payload = {
        "patient_id": base["patient_id"],
        "length_cm": 2, "width_cm": 2, "tissue_type": "GRANULATION",
    }
    resp = api.create_wound_assessment(payload, make_wound_clinician_headers(base["wc_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_assessment_bad_enum_stage_returns_400(api):
    """PRD §2.10: "Enumerated fields must carry legal values: a wound assessment's
    stage must be one of STAGE_1, STAGE_2, STAGE_3, STAGE_4, or UNSTAGEABLE".
    A stage of STAGE_9 returns ERR_INVALID_REQUEST (400).

    Design: Corner/entities/create_assessment_bad_enum_stage_returns_400
    """
    base = fixtures.setup_center_staff_patient(mrn="Menum")
    resp = api.create_wound_assessment(
        factories.create_wound_assessment_payload(base["patient_id"], stage="STAGE_9"),
        make_wound_clinician_headers(base["wc_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_hbo_session_window_end_before_start_returns_400(api):
    """PRD §2.10: "For any scheduled interval, window_end must be strictly greater
    than window_start."
    An HBO session with window_end <= window_start returns ERR_INVALID_REQUEST
    (400).

    Design: Corner/entities/create_hbo_session_window_end_before_start_returns_400
    """
    base = fixtures.setup_active_covered_plan_with_chamber(mrn="Mwin")
    ht_headers = make_hyperbaric_tech_headers(base["ht_id"])
    version = fixtures.get_plan_version(base["plan_id"], ht_headers)
    resp = api.create_hbo_session(
        factories.create_hbo_session_payload(
            base["plan_id"], base["chamber_id"], version,
            window_start="2026-05-02T10:00:00Z", window_end="2026-05-02T09:00:00Z"),
        ht_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_system_fields_generated_on_create_input_ignored(api):
    """PRD §3.1: "A newly registered chamber begins with an occupied_slot_count of
    zero — a conserved count of that chamber's sessions currently in SCHEDULED
    status."
    occupied_slot_count is 0 on create; the client-supplied turnover_buffer is
    honored (15).

    Design: Corner/entities/system_fields_generated_on_create_input_ignored
    """
    center = fixtures.create_center()
    resp = api.create_chamber(
        factories.create_chamber_payload(center["id"], turnover_buffer_minutes=15),
        fixtures.INTAKE)
    data = validate_success(resp, 201)
    assert data["occupied_slot_count"] == 0
    assert data["turnover_buffer_minutes"] == 15


def test_chamber_buffer_default_applied(api):
    """PRD §3.1: "Chambers are registered against the center by center_id with a
    label and an optional turnover_buffer_minutes that defaults to 30 minutes".
    Omitting turnover_buffer_minutes applies the default 30.

    Design: Corner/entities/chamber_buffer_default_applied
    """
    center = fixtures.create_center()
    resp = api.create_chamber(
        factories.create_chamber_payload(center["id"]), fixtures.INTAKE)
    data = validate_success(resp, 201)
    assert data["turnover_buffer_minutes"] == 30


def test_assessment_immutable_no_version_field(api):
    """PRD §2.4: "Two entities are append-only clinical records and therefore
    carry only id and created_at — they have no updated_at and no version field:
    the WoundAssessment and the PhotoDocument."
    A WoundAssessment GET exposes no version field; its severity_score for a
    STAGE_1 1x1 EPITHELIAL wound is clamped to the floor of 1.

    Design: Corner/entities/assessment_immutable_no_version_field
    """
    base = fixtures.setup_center_staff_patient(mrn="Mimm")
    asm = fixtures.record_assessment(base["patient_id"], base["wc_id"], stage="STAGE_1",
                                     length_cm=1, width_cm=1, tissue_type="EPITHELIAL")
    resp = api.get_wound_assessment(asm["id"], make_wound_clinician_headers(base["wc_id"]))
    data = validate_success(resp)
    assert data["severity_score"] == 1
    assert "version" not in data, "append-only WoundAssessment must not carry a version field"


# =============================================================================
# boundary_precision_check — empty dive log (queue A)
# =============================================================================

def test_empty_dive_log_blocks_session_complete(api):
    """PRD §3.8: "Completing a session is permitted only when the session is in
    SCHEDULED (otherwise ERR_SESSION_NOT_SCHEDULED), the plan is ACTIVE (otherwise
    ERR_PLAN_NOT_ACTIVE), and the request supplies a non-empty dive_log_entries
    list — each entry a record of a minute, an spo2, and an hr vitals reading —
    without which completion fails with ERR_EMPTY_DIVE_LOG."
    An empty dive_log_entries list is rejected; the session stays SCHEDULED.

    Design: Difficulty/boundary_precision_check/empty_dive_log_blocks_session_complete
    """
    base = fixtures.setup_active_covered_plan_with_chamber(mrn="M12")
    ht_id = base["ht_id"]
    sess = fixtures.schedule_hbo_session(base["plan_id"], base["chamber_id"], ht_id)
    resp = api.complete_hbo_session(
        sess["id"], {"dive_log_entries": []}, make_hyperbaric_tech_headers(ht_id))
    validate_error(resp, ApiErrorId.ERR_EMPTY_DIVE_LOG.value)
    session = validate_success(api.get_hbo_session(sess["id"], fixtures.INTAKE))
    assert session["status"] == "SCHEDULED"


def test_nonempty_dive_log_allows_session_complete(api):
    """PRD §3.8: "Completion persists the supplied dive_log_entries, moves the
    session to COMPLETED, decrements the chamber's occupied_slot_count by one".
    A one-entry dive log succeeds: session -> COMPLETED.

    Design: Difficulty/boundary_precision_check/empty_dive_log_blocks_session_complete
    """
    base = fixtures.setup_active_covered_plan_with_chamber(mrn="M12b")
    ht_id = base["ht_id"]
    sess = fixtures.schedule_hbo_session(base["plan_id"], base["chamber_id"], ht_id)
    resp = api.complete_hbo_session(
        sess["id"], {"dive_log_entries": [{"minute": 0, "spo2": 98, "hr": 72}]},
        make_hyperbaric_tech_headers(ht_id))
    data = validate_success(resp)
    assert data["status"] == "COMPLETED"


# =============================================================================
# Corner: endpoints section
# =============================================================================

def test_list_hbo_sessions_by_chamber_filter(api):
    """PRD §1 (Introduction): "every collection exposes a filtered list endpoint
    so that any reference can be traced back to its owner." Endpoint table: "GET
    /wound-care/hbo-sessions — List HBO sessions, optionally by plan or chamber".
    Filtering by chamber_id returns the session scheduled on that chamber.

    Design: Corner/endpoints/list_hbo_sessions_by_chamber_filter
    """
    base = fixtures.setup_active_covered_plan_with_chamber(mrn="Mlist")
    ht_id = base["ht_id"]
    sess = fixtures.schedule_hbo_session(base["plan_id"], base["chamber_id"], ht_id)
    resp = api.list_hbo_sessions(fixtures.INTAKE, params={"chamber_id": base["chamber_id"]})
    data, meta = validate_paginated(resp)
    ids = [s["id"] for s in data]
    assert sess["id"] in ids, f"expected session {sess['id']} in filtered list"
    assert all(s["chamber_id"] == base["chamber_id"] for s in data)


# =============================================================================
# Corner: errors section
# =============================================================================

def test_error_envelope_shape_on_not_found(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format: ... response_type: error ... data: { error_id: ... }". PRD
    §2.9: not-found existence failures use a resource-specific code such as
    ERR_CENTER_NOT_FOUND.
    GET on a non-existent center returns response_type 'error' with data.error_id
    ERR_CENTER_NOT_FOUND.

    Design: Corner/errors/error_envelope_shape_on_not_found
    """
    resp = api.get_center(NON_EXISTENT_UUID, fixtures.INTAKE)
    error_data = validate_error(resp, ApiErrorId.ERR_CENTER_NOT_FOUND.value)
    assert isinstance(error_data.get("message"), str) and len(error_data["message"]) > 0
    body = resp.json()
    assert body["response_type"] == "error"


# =============================================================================
# Corner: rbac section
# =============================================================================

def test_intake_coordinator_cannot_record_assessment(api):
    """PRD §2.1: "When the headers are present and valid but the declared role is
    not permitted to perform the requested operation, the request is rejected
    with ERR_INSUFFICIENT_PERMISSIONS." PRD §2.1: "WoundClinician owns clinical
    assessment and treatment: recording wound assessments and photos".
    An IntakeCoordinator recording a wound assessment returns
    ERR_INSUFFICIENT_PERMISSIONS (403).

    Design: Corner/rbac/intake_coordinator_cannot_record_assessment
    """
    base = fixtures.setup_center_staff_patient(mrn="Mrbac1")
    resp = api.create_wound_assessment(
        factories.create_wound_assessment_payload(base["patient_id"]),
        fixtures.INTAKE)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_hyperbarictech_cannot_approve_prior_auth(api):
    """PRD §2.1: "PayerLiaison owns the payer relationship: payer policies, prior
    authorizations, and supply-order approvals and rejections." PRD §2.1: role
    not permitted -> ERR_INSUFFICIENT_PERMISSIONS.
    A HyperbaricTech approving a prior authorization returns
    ERR_INSUFFICIENT_PERMISSIONS (403).

    Design: Corner/rbac/hyperbarictech_cannot_approve_prior_auth
    """
    base = fixtures.setup_draft_plan(budget_cents=100000, mrn="Mrbac2", accept_into_care=False)
    ht = fixtures.create_clinician(base["center_id"], role_kind="HYPERBARIC", name="Tech H")
    auth = validate_success(api.create_prior_authorization(
        factories.create_prior_authorization_payload(
            base["plan_id"], requested_hbo_sessions=2), fixtures.PAYER), 201)
    resp = api.approve_prior_authorization(auth["id"], make_hyperbaric_tech_headers(ht["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_missing_user_context_header_returns_400(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: X-User-ID,
    identifying the acting user, and X-User-Role, declaring the operational
    capacity under which the request is made. If either header is missing or
    invalid, the request is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."
    A create-center request with no user context returns
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400).

    Design: Corner/rbac/missing_user_context_header_returns_400
    """
    resp = api.create_center(factories.create_center_payload(name="C"), headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)
