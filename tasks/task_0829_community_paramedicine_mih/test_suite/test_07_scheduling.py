"""Encounter scheduling safeguards: provider half-open overlap for home visits, patient
buffer for telehealth, provider-type gating, and the safety-before-temporal precedence."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    bootstrap, enroll_patient, create_active_care_plan, create_care_plan,
    setup_enrollment_with_active_plan, setup_enrollment_with_draft_plan,
    schedule_home_visit, schedule_telehealth,
    create_home_visit_payload, create_telehealth_payload,
)


def test_overlapping_home_visit_for_provider_rejected(api):
    """PRD 3.5: "no other SCHEDULED home visit for the same provider may overlap the visit's
    half-open window [scheduled_start, scheduled_end) ... any true overlap is rejected with
    ERR_SCHEDULE_CONFLICT."
    A second visit 10:30-11:30 overlapping an existing 10:00-11:00 booking is rejected.

    Design: Difficulty/resource_temporal_overlap/home_visit_provider_halfopen_overlap
    """
    ctx = setup_enrollment_with_active_plan(api)
    org, enr_id, cp_id = ctx["org"], ctx["enrollment_id"], ctx["care_plan_id"]
    schedule_home_visit(api, org, enr_id, cp_id,
                        "2026-03-16T10:00:00Z", "2026-03-16T11:00:00Z")
    payload = create_home_visit_payload(enr_id, cp_id, org["para_id"],
                                        "2026-03-16T10:30:00Z", "2026-03-16T11:30:00Z")
    resp = api.create_home_visit(payload, org["coord_headers"])
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT)


def test_back_to_back_home_visit_for_provider_allowed(api):
    """PRD 3.5: "Two visits that merely touch end-to-start do not overlap and are allowed".
    A second visit 11:00-12:00 immediately after a 10:00-11:00 booking is accepted.

    Design: Difficulty/resource_temporal_overlap/home_visit_provider_halfopen_overlap
    """
    ctx = setup_enrollment_with_active_plan(api)
    org, enr_id, cp_id = ctx["org"], ctx["enrollment_id"], ctx["care_plan_id"]
    schedule_home_visit(api, org, enr_id, cp_id,
                        "2026-03-16T10:00:00Z", "2026-03-16T11:00:00Z")
    payload = create_home_visit_payload(enr_id, cp_id, org["para_id"],
                                        "2026-03-16T11:00:00Z", "2026-03-16T12:00:00Z")
    resp = api.create_home_visit(payload, org["coord_headers"])
    validate_success(resp, 201)


def test_telehealth_within_patient_buffer_rejected(api):
    """PRD 3.5: "no other SCHEDULED telehealth session for the same patient may fall within
    15 minutes of this session's window. If another session lies inside that buffered window,
    the request is rejected with ERR_TELEHEALTH_BUFFER_CONFLICT."
    A 10:40-11:00 session only 10 minutes after a 10:00-10:30 session is rejected.

    Design: Difficulty/resource_temporal_overlap/telehealth_patient_buffer_overlap
    """
    org = bootstrap(api)
    enr = enroll_patient(api, org)
    schedule_telehealth(api, org, enr["enrollment_id"], enr["patient_id"],
                        "2026-03-17T10:00:00Z", "2026-03-17T10:30:00Z")
    payload = create_telehealth_payload(enr["enrollment_id"], enr["patient_id"], org["clin_id"],
                                        "2026-03-17T10:40:00Z", "2026-03-17T11:00:00Z")
    resp = api.create_telehealth_session(payload, org["coord_headers"])
    validate_error(resp, ApiErrorId.ERR_TELEHEALTH_BUFFER_CONFLICT)


def test_telehealth_outside_patient_buffer_allowed(api):
    """PRD 3.5: "no other SCHEDULED telehealth session for the same patient may fall within
    15 minutes of this session's window."
    A 11:00-11:30 session a full 30 minutes after a 10:00-10:30 session lies outside the
    15-minute buffer and is accepted.

    Design: Difficulty/resource_temporal_overlap/telehealth_patient_buffer_overlap
    """
    org = bootstrap(api)
    enr = enroll_patient(api, org)
    schedule_telehealth(api, org, enr["enrollment_id"], enr["patient_id"],
                        "2026-03-17T10:00:00Z", "2026-03-17T10:30:00Z")
    payload = create_telehealth_payload(enr["enrollment_id"], enr["patient_id"], org["clin_id"],
                                        "2026-03-17T11:00:00Z", "2026-03-17T11:30:00Z")
    resp = api.create_telehealth_session(payload, org["coord_headers"])
    validate_success(resp, 201)


def test_draft_plan_conflict_returns_care_plan_not_active(api):
    """PRD 2.6: "Operational status of related resources. A care plan that is not ACTIVE under
    a scheduled home visit yields ERR_CARE_PLAN_NOT_ACTIVE" (item 7) is checked before
    "Temporal conflicts ... ERR_SCHEDULE_CONFLICT" (item 8). A visit under a DRAFT plan that
    also collides with the paramedic's booked slot returns the safety error.

    Design: Difficulty/priority_pair_validation_conflict/schedule_safety_beats_temporal
    """
    org = bootstrap(api)
    enr1 = enroll_patient(api, org, {"full_name": "Pat One"})
    cp1 = create_active_care_plan(api, org, enr1["enrollment_id"], enr1["enrollment_version"])
    schedule_home_visit(api, org, enr1["enrollment_id"], cp1["id"],
                        "2026-03-12T10:00:00Z", "2026-03-12T11:00:00Z")
    enr2 = enroll_patient(api, org, {"full_name": "Pat Two"})
    cp2 = create_care_plan(api, org, enr2["enrollment_id"], enr2["enrollment_version"])  # DRAFT
    payload = create_home_visit_payload(enr2["enrollment_id"], cp2["id"], org["para_id"],
                                        "2026-03-12T10:30:00Z", "2026-03-12T11:30:00Z")
    resp = api.create_home_visit(payload, org["coord_headers"])
    validate_error(resp, ApiErrorId.ERR_CARE_PLAN_NOT_ACTIVE)


def test_safety_check_preempts_schedule_conflict(api):
    """PRD 2.6: "Lower-numbered checks always take precedence". The operational-status check
    (item 7, ERR_CARE_PLAN_NOT_ACTIVE) outranks the temporal check (item 8,
    ERR_SCHEDULE_CONFLICT), so a DRAFT-plan visit that also double-books the paramedic never
    surfaces the temporal error.

    Design: Difficulty/priority_pair_validation_conflict/schedule_safety_beats_temporal
    """
    org = bootstrap(api)
    enr1 = enroll_patient(api, org, {"full_name": "Pat One"})
    cp1 = create_active_care_plan(api, org, enr1["enrollment_id"], enr1["enrollment_version"])
    schedule_home_visit(api, org, enr1["enrollment_id"], cp1["id"],
                        "2026-03-12T10:00:00Z", "2026-03-12T11:00:00Z")
    enr2 = enroll_patient(api, org, {"full_name": "Pat Two"})
    cp2 = create_care_plan(api, org, enr2["enrollment_id"], enr2["enrollment_version"])
    payload = create_home_visit_payload(enr2["enrollment_id"], cp2["id"], org["para_id"],
                                        "2026-03-12T10:30:00Z", "2026-03-12T11:30:00Z")
    resp = api.create_home_visit(payload, org["coord_headers"])
    error = validate_error(resp, ApiErrorId.ERR_CARE_PLAN_NOT_ACTIVE)
    assert error["error_id"] != ApiErrorId.ERR_SCHEDULE_CONFLICT.value


def test_schedule_home_visit_under_draft_plan_rejected(api):
    """PRD 3.5: "The referenced care plan must be ACTIVE at schedule time, otherwise
    ERR_CARE_PLAN_NOT_ACTIVE; the enrollment must be ACTIVE, otherwise
    ERR_ENROLLMENT_NOT_ACTIVE; and the assigned provider must be of type PARAMEDIC, otherwise
    ERR_PROVIDER_TYPE_MISMATCH."

    Design: Difficulty/cross_entity_state_dependency/visit_requires_care_plan_active
    """
    ctx = setup_enrollment_with_draft_plan(api)
    org = ctx["org"]
    payload = create_home_visit_payload(ctx["enrollment_id"], ctx["care_plan_id"], org["para_id"],
                                        "2026-03-14T10:00:00Z", "2026-03-14T11:00:00Z")
    resp = api.create_home_visit(payload, org["coord_headers"])
    validate_error(resp, ApiErrorId.ERR_CARE_PLAN_NOT_ACTIVE)


def test_schedule_home_visit_under_active_plan_succeeds(api):
    """PRD 3.5: "The referenced care plan must be ACTIVE at schedule time, otherwise
    ERR_CARE_PLAN_NOT_ACTIVE; the enrollment must be ACTIVE, otherwise
    ERR_ENROLLMENT_NOT_ACTIVE; and the assigned provider must be of type PARAMEDIC, otherwise
    ERR_PROVIDER_TYPE_MISMATCH." Once the same plan is ACTIVE, the identical schedule request
    is accepted, confirming the DRAFT status was the gate.

    Design: Difficulty/cross_entity_state_dependency/visit_requires_care_plan_active
    """
    ctx = setup_enrollment_with_draft_plan(api)
    org = ctx["org"]
    api.activate_care_plan(ctx["care_plan_id"], org["clin_headers"])
    payload = create_home_visit_payload(ctx["enrollment_id"], ctx["care_plan_id"], org["para_id"],
                                        "2026-03-14T10:00:00Z", "2026-03-14T11:00:00Z")
    resp = api.create_home_visit(payload, org["coord_headers"])
    validate_success(resp, 201)


def test_home_visit_with_non_paramedic_provider_rejected(api):
    """PRD 3.5: "the assigned provider must be of type PARAMEDIC, otherwise
    ERR_PROVIDER_TYPE_MISMATCH."
    Scheduling a home visit with a CLINICIAN provider is rejected.

    Design: Corner/validations/home_visit_wrong_provider_type_returns_mismatch
    """
    ctx = setup_enrollment_with_active_plan(api)
    org = ctx["org"]
    payload = create_home_visit_payload(ctx["enrollment_id"], ctx["care_plan_id"], org["clin_id"],
                                        "2026-03-21T10:00:00Z", "2026-03-21T11:00:00Z")
    resp = api.create_home_visit(payload, org["coord_headers"])
    validate_error(resp, ApiErrorId.ERR_PROVIDER_TYPE_MISMATCH)
