"""Entity creation defaults, not-found / required-field / enum errors, patient-flag
workflow, listing envelope, agreement/plan open-child guards, and RBAC.

Queue B: entities, endpoints, errors, rbac sections.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    make_prescriber_headers,
    make_compliance_officer_headers,
    setup_active_medication_patient,
    setup_active_procedure_patient,
    setup_scheduled_procedure,
    create_clinic,
    create_prescriber,
    register_patient,
    create_active_agreement,
    create_draft_agreement,
    create_pdmp_check,
    create_approved_prescription_pa,
    propose_prescription,
    activate_prescription,
    create_active_below_threshold_rx,
    get_prescription,
    set_clock,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
PA_CLERK = TEST_USERS["prior_auth_clerk_headers"]


# --- entities section ---

def test_create_clinic_returns_defaults(api):
    """PRD 3.1: "The first, `med_review_threshold_mg`, ... defaults to 90 when omitted. The
    second, `pill_count_tolerance`, ... defaults to 2 when omitted."
    PRD 2.5: "On server startup the clock reads exactly `2026-05-01T00:00:00Z`."

    Design: Corner/entities/create_clinic_returns_defaults
    """
    data = validate_success(api.create_clinic({"name": "Clinic X", "state_code": "NY"}, ADMIN), 201)
    assert data["med_review_threshold_mg"] == 90
    assert data["pill_count_tolerance"] == 2
    assert data["current_utc"].startswith("2026-05-01T00:00:00")
    assert data["version"] == 1


def test_create_clinic_overrides_defaults(api):
    """PRD 3.1: "may optionally set two policy thresholds. The first, `med_review_threshold_mg`,
    is the daily MED at or above which a prescription is treated as a high-scrutiny controlled
    prescription ... The second, `pill_count_tolerance`, is the absolute pill-count discrepancy
    in whole pills at or below which an audit is judged consistent."

    Design: Corner/entities/create_clinic_overrides_defaults
    """
    data = validate_success(
        api.create_clinic(
            {"name": "Clinic Y", "state_code": "TX", "med_review_threshold_mg": 50, "pill_count_tolerance": 5}, ADMIN
        ), 201,
    )
    assert data["med_review_threshold_mg"] == 50
    assert data["pill_count_tolerance"] == 5


def test_get_patient_not_found(api):
    """PRD 2.7: "rejects the request at the first identifier that does not resolve, returning
    the not-found error for that specific resource type — `ERR_CLINIC_NOT_FOUND`, then
    `ERR_PATIENT_NOT_FOUND`, and so on down the path."

    Design: Corner/entities/get_patient_not_found
    """
    clinic = create_clinic()
    resp = api.get_patient(clinic["id"], NON_EXISTENT_UUID, INTAKE)
    validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_FOUND.value, expected_status=404)


def test_create_patient_missing_required_field(api):
    """PRD 3.2: "Registration supplies the patient's `full_name` and `referral_source`."

    Design: Corner/entities/create_patient_missing_required_field
    """
    clinic = create_clinic()
    resp = api.create_patient(clinic["id"], {"full_name": "No Source"}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_provider_invalid_role_kind_enum(api):
    """PRD 3.1: "a `role_kind`, which must be either `PRESCRIBER` ... or `COMPLIANCE_OFFICER`.
    ... Any other `role_kind` value is rejected as an invalid enum value."

    Design: Corner/entities/create_provider_invalid_role_kind_enum
    """
    clinic = create_clinic()
    resp = api.create_provider(
        clinic["id"], {"full_name": "Dr Wrong", "dea_number": "BX0000000", "role_kind": "SURGEON"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM_VALUE.value)


def test_pdmp_check_queried_utc_system_stamped(api):
    """PRD 3.4: "The system stamps `queried_utc` with the clinic's `current_utc` at query time."
    PRD 2.5: "On server startup the clock reads exactly `2026-05-01T00:00:00Z`."

    Design: Corner/entities/pdmp_check_system_fields_ignored
    """
    clinic = create_clinic()  # default clock 2026-05-01
    prescriber = create_prescriber(clinic["id"])
    patient = register_patient(clinic["id"])
    pres_h = make_prescriber_headers(prescriber["id"])
    data = validate_success(
        api.create_pdmp_check(
            clinic["id"],
            {"patient_id": patient["id"], "queried_by_provider_id": prescriber["id"], "outcome": "CLEAR"},
            pres_h,
        ), 201,
    )
    assert data["queried_utc"].startswith("2026-05-01T00:00:00")


# --- endpoints section: patient flag workflow + listing ---

def _flag_patient_via_pill_count(api, ctx):
    """Drive a patient to FLAGGED through an inconsistent pill-count audit, returning
    the first (below-threshold) prescription id."""
    clinic_id, patient_id, prescriber_id, co_id = (
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"], ctx["compliance_officer"]["id"],
    )
    rx1 = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        drug_name="tramadol", dose_mg=5, units_per_day=1.5, conversion_factor=0.1,
        day_supply=40, pills_dispensed=60,
    )
    activate_prescription(clinic_id, patient_id, prescriber_id, rx1["id"])
    set_clock(clinic_id, "2026-06-21T00:00:00Z")
    co_h = make_compliance_officer_headers(co_id)
    validate_success(
        api.create_pill_count_audit(
            clinic_id, patient_id,
            {"prescription_id": rx1["id"], "audit_utc": "2026-06-21T00:00:00Z", "counted_pills": 15}, co_h,
        ), 201,
    )
    return rx1["id"]


def test_flagged_patient_blocks_new_activation(api):
    """PRD 3.5: "Independently of the MED threshold, activating an opioid prescription for a
    patient whose `compliance_flag` is `FLAGGED` is refused with `ERR_PATIENT_FLAGGED`; such a
    patient must be cleared first."

    Design: Corner/endpoints/patient_flagged_blocks_activation
    """
    ctx = setup_active_medication_patient(clock_utc="2026-06-01T00:00:00Z", intake_utc="2026-06-01T00:00:00Z")
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    _flag_patient_via_pill_count(api, ctx)

    pres_h = make_prescriber_headers(prescriber_id)
    patient = validate_success(api.get_patient(clinic_id, patient_id, pres_h), 200)
    assert patient["compliance_flag"] == "FLAGGED"

    rx2 = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        drug_name="codeine", dose_mg=15, units_per_day=2, conversion_factor=1.0,
        day_supply=30, pills_dispensed=60,
    )
    resp = api.activate_prescription(clinic_id, patient_id, rx2["id"], pres_h)
    validate_error(resp, ApiErrorId.ERR_PATIENT_FLAGGED.value)
    after = get_prescription(clinic_id, patient_id, prescriber_id, rx2["id"])
    assert after["status"] == "PROPOSED"


def test_clear_flag_then_activation_succeeds(api):
    """PRD 3.10: "Clearing sets the patient's `compliance_flag` to `CLEARED`, which re-opens
    the patient to opioid activation that the `FLAGGED` state had blocked."

    Design: Corner/endpoints/clear_flag_then_activate_succeeds
    """
    ctx = setup_active_medication_patient(clock_utc="2026-06-01T00:00:00Z", intake_utc="2026-06-01T00:00:00Z")
    clinic_id, patient_id, prescriber_id, co_id = (
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"], ctx["compliance_officer"]["id"],
    )
    _flag_patient_via_pill_count(api, ctx)

    pres_h = make_prescriber_headers(prescriber_id)
    rx2 = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        drug_name="codeine", dose_mg=15, units_per_day=2, conversion_factor=1.0,
        day_supply=30, pills_dispensed=60,
    )
    co_h = make_compliance_officer_headers(co_id)
    cleared = validate_success(api.clear_flag(clinic_id, patient_id, co_h), 200)
    assert cleared["compliance_flag"] == "CLEARED"

    data = validate_success(api.activate_prescription(clinic_id, patient_id, rx2["id"], pres_h), 200)
    assert data["status"] == "ACTIVE"


def test_list_prescriptions_pagination_envelope(api):
    """PRD 2.3: "Paginated list responses include the following fields in the `meta` object of
    the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_prescriptions_pagination_envelope
    """
    clinic = create_clinic()
    prescriber = create_prescriber(clinic["id"])
    patient = register_patient(clinic["id"])
    pres_h = make_prescriber_headers(prescriber["id"])
    propose_prescription(
        clinic["id"], patient["id"], prescriber["id"],
        drug_name="tramadol", dose_mg=5, units_per_day=4, conversion_factor=1.0,
        day_supply=30, pills_dispensed=120,
    )
    resp = api.list_prescriptions(clinic["id"], patient["id"], pres_h)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(data) == 1


# --- errors section ---

def test_counter_sign_by_wrong_prescriber_rejected(api):
    """PRD 3.4: "the acting prescriber's own `Provider.id` (that is, `X-User-ID`) must equal
    the agreement's `prescriber_id` (otherwise `ERR_NOT_AGREEMENT_PRESCRIBER`)."

    Design: Corner/errors/counter_sign_by_wrong_prescriber_rejected
    """
    clinic = create_clinic()
    dr_a = create_prescriber(clinic["id"], full_name="Dr A", dea_number="BX1111111")
    dr_b = create_prescriber(clinic["id"], full_name="Dr B", dea_number="BX2222222")
    patient = register_patient(clinic["id"])
    ag = create_draft_agreement(clinic["id"], patient["id"], dr_a["id"])

    resp = api.counter_sign_agreement(clinic["id"], ag["id"], make_prescriber_headers(dr_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_AGREEMENT_PRESCRIBER.value)

    ags = validate_success(api.list_opioid_agreements(clinic["id"], make_prescriber_headers(dr_a["id"])), 200)
    assert [a for a in ags if a["id"] == ag["id"]][0]["status"] == "DRAFT"


def test_complete_plan_with_open_procedure_rejected(api):
    """PRD 3.3: "Completing a procedure-path plan moves it from `PROCEDURE_PATH` to
    `COMPLETED`, but only if every procedure referencing that plan is already `COMPLETED` or
    `CANCELLED` (otherwise `ERR_OPEN_PROCEDURES_EXIST`)."

    Design: Corner/errors/complete_plan_with_open_procedure_rejected
    """
    ctx = setup_scheduled_procedure()
    clinic_id, patient_id, prescriber_id, plan_id = (
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"], ctx["plan"]["id"],
    )
    pres_h = make_prescriber_headers(prescriber_id)
    resp = api.complete_treatment_plan(clinic_id, patient_id, plan_id, pres_h)
    validate_error(resp, ApiErrorId.ERR_OPEN_PROCEDURES_EXIST.value)

    plans = validate_success(api.list_treatment_plans(clinic_id, patient_id, pres_h), 200)
    assert [p for p in plans if p["id"] == plan_id][0]["status"] == "PROCEDURE_PATH"


def test_uds_collect_before_due_rejected(api):
    """PRD 3.8: "collects a scheduled screen ... requires the clinic's `current_utc` to have
    reached or passed the screen's `due_utc` (otherwise `ERR_UDS_NOT_DUE`)."

    Design: Corner/errors/uds_collect_before_due_rejected
    """
    clinic = create_clinic()  # default clock 2026-05-01
    co = create_prescriber(clinic["id"], full_name="CO One", dea_number="AC7654321", role_kind="COMPLIANCE_OFFICER")
    patient = register_patient(clinic["id"])
    co_h = make_compliance_officer_headers(co["id"])
    uds = validate_success(
        api.create_urine_drug_screen(
            clinic["id"], patient["id"], {"due_utc": "2026-06-01T00:00:00Z", "expected_substances": ["oxycodone"]}, co_h
        ), 201,
    )
    resp = api.collect_urine_drug_screen(clinic["id"], patient["id"], uds["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_UDS_NOT_DUE.value)
    scr = validate_success(api.list_urine_drug_screens(clinic["id"], patient["id"], co_h), 200)
    assert [s for s in scr if s["id"] == uds["id"]][0]["status"] == "SCHEDULED"


# --- rbac section ---

def test_intake_coordinator_cannot_write_prescription(api):
    """PRD 2.1: "When the headers are valid but the declared role is not permitted to perform
    the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/intake_coordinator_cannot_write_prescription
    """
    clinic = create_clinic()
    prescriber = create_prescriber(clinic["id"])
    patient = register_patient(clinic["id"])
    resp = api.create_prescription(
        clinic["id"], patient["id"],
        {
            "prescriber_id": prescriber["id"], "drug_name": "tramadol", "dose_mg": 5,
            "units_per_day": 4, "conversion_factor": 1.0, "day_supply": 30, "pills_dispensed": 120,
        },
        INTAKE,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_prescriber_cannot_revoke_agreement(api):
    """PRD 4 (endpoint table): revoke an active agreement is authorized for ComplianceOfficer.
    PRD 2.1: "When the headers are valid but the declared role is not permitted to perform the
    requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/prescriber_cannot_revoke_agreement_sod
    """
    clinic = create_clinic()
    prescriber = create_prescriber(clinic["id"])
    patient = register_patient(clinic["id"])
    ag = create_active_agreement(clinic["id"], patient["id"], prescriber["id"])

    resp = api.revoke_agreement(clinic["id"], ag["id"], make_prescriber_headers(prescriber["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    ags = validate_success(api.list_opioid_agreements(clinic["id"], make_prescriber_headers(prescriber["id"])), 200)
    assert [a for a in ags if a["id"] == ag["id"]][0]["status"] == "ACTIVE"


def test_missing_user_context_header_rejected(api):
    """PRD 2.1: "If either header is missing or carries an unrecognized value, the request is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    clinic = create_clinic()
    resp = api.get_clinic(clinic["id"], {})  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value, expected_status=400)
