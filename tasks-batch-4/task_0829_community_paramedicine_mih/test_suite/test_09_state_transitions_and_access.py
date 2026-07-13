"""Illegal-transition guards, access control, existence/validation checks, and list
pagination for the enrollment collection."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, NON_EXISTENT_UUID,
    bootstrap, create_patient, create_screened_referral, enroll_patient,
    setup_enrollment_with_active_plan, setup_med_rec_drafted,
    add_completed_home_visit, create_program_payload, create_referral_payload,
)


def test_screen_already_screened_referral_rejected(api):
    """PRD 3.3: "Screening advances the referral SUBMITTED -> SCREENED", and per PRD 2.6 "A
    generic illegal transition yields ERR_INVALID_STATE". Screening a referral already in
    SCREENED is a generic illegal transition.

    Design: Corner/state_machines/screen_referral_twice_rejected
    """
    org = bootstrap(api)
    sr = create_screened_referral(api, org)
    resp = api.screen_referral(sr["referral_id"], org["coord_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_complete_already_completed_home_visit_rejected(api):
    """PRD 3.5: "A paramedic completes a visit by moving it SCHEDULED -> COMPLETED", and per
    PRD 2.6 "A generic illegal transition yields ERR_INVALID_STATE". Completing an
    already-COMPLETED visit is rejected.

    Design: Corner/state_machines/complete_home_visit_twice_rejected
    """
    ctx = setup_enrollment_with_active_plan(api)
    org = ctx["org"]
    hv = add_completed_home_visit(api, org, ctx["enrollment_id"], ctx["care_plan_id"],
                                  "2026-03-20T10:00:00Z", "2026-03-20T11:00:00Z")
    resp = api.complete_home_visit(hv["id"],
                                   {"systolic_bp": 200, "diastolic_bp": 120, "heart_rate": 150},
                                   org["para_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_review_med_rec_not_pending_rejected(api):
    """PRD 3.6: "review is only permitted while the record is PENDING_REVIEW, otherwise
    ERR_MED_REC_NOT_PENDING." Reviewing a still-DRAFTED reconciliation is rejected.

    Design: Corner/validations/review_med_rec_not_pending_returns_error
    """
    ctx = setup_med_rec_drafted(api)
    org = ctx["org"]
    resp = api.review_med_reconciliation(ctx["med_reconciliation_id"],
                                         {"review_outcome": "RECONCILED"}, org["clin_headers"])
    validate_error(resp, ApiErrorId.ERR_MED_REC_NOT_PENDING)


def test_paramedic_cannot_create_referral(api):
    """PRD 2.1: "When the headers are valid but the declared role is not permitted to perform
    the requested operation, the request is rejected with ERR_UNAUTHORIZED." Creating a
    referral is a CareCoordinator-only operation, so a Paramedic caller is rejected.

    Design: Corner/rbac/paramedic_cannot_create_referral_returns_unauthorized
    """
    org = bootstrap(api)
    patient = create_patient(api, org, full_name="Pat RB")
    payload = create_referral_payload(patient["id"], org["program_id"])
    resp = api.create_referral(payload, org["para_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_create_program_without_auth_headers_rejected(api):
    """PRD 2.1: "If either header is missing or its value is not recognized, the request is
    rejected with ERR_UNAUTHENTICATED." A program create carrying no authentication headers
    is rejected.

    Design: Corner/rbac/create_program_missing_auth_returns_401
    """
    org = bootstrap(api)
    payload = create_program_payload(org["payer_id"], name="NoAuth")
    resp = api.create_program(payload, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_get_unknown_patient_returns_not_found(api):
    """PRD 2.6: "Existence. Every id in the path and every foreign key in the body is resolved
    left-to-right; the first that does not correspond to an existing resource yields
    ERR_NOT_FOUND." A GET on a non-existent patient id is rejected.

    Design: Corner/entities/get_patient_unknown_id_returns_not_found
    """
    org = bootstrap(api)
    resp = api.get_patient(NON_EXISTENT_UUID, org["coord_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_referral_missing_program_id_returns_validation(api):
    """PRD 2.6: "Body validation. Missing required fields, wrong types, invalid enum members,
    or a scheduled_end that is not strictly after scheduled_start yield ERR_VALIDATION." A
    referral create omitting the required program_id is rejected.

    Design: Corner/entities/create_referral_missing_required_program_returns_400
    """
    org = bootstrap(api)
    patient = create_patient(api, org, full_name="Pat X")
    payload = {"patient_id": patient["id"], "referring_source": "ED"}
    resp = api.create_referral(payload, org["coord_headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_list_enrollments_pagination_envelope(api):
    """PRD 2.3: "Every list response includes limit, offset, total_count, and has_more in the
    meta object of the envelope." With two enrollments under one program and limit=1, the
    listing returns one item, total_count 2, and has_more true.

    Design: Corner/endpoints/list_enrollments_pagination_envelope
    """
    org = bootstrap(api)
    enroll_patient(api, org, {"full_name": "Pat A1"})
    enroll_patient(api, org, {"full_name": "Pat A2"})
    resp = api.list_enrollments(org["coord_headers"],
                                params={"program_id": org["program_id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"expected 1 item on the page, got {len(data)}"
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "expected has_more true with 2 items and limit 1"
