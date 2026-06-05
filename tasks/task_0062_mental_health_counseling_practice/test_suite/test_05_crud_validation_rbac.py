"""CRUD, input validation, RBAC, and listing/endpoint corner cases.

Queue B (Corner): entities, validations, rbac, endpoints.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_associate_therapist, create_patient, schedule_appointment,
    create_payer_contract, create_policy, set_clock,
    create_crisis_assessment_payload, make_therapist_headers,
    TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
)

CD = TEST_USERS["clinical_director_headers"]
FD = TEST_USERS["front_desk_headers"]
BILLER = TEST_USERS["biller_headers"]


def test_create_patient_returns_201_with_computed_sliding_fields():
    """PRD §3.4: "Registration immediately computes the patient's fpl_percent and
    sliding_fee_multiplier per the sliding-fee bands."
    PRD §2.10: "above 250 and at or below 300 yields 0.80"

    Design: Corner/entities/create_patient_returns_201_with_computed_sliding_fields
    """
    # income 40000 / FPL 15060 (household 1) = 265.60% -> 0.80 band
    resp = api_client.create_patient(
        {"full_name": "New Pt", "location_state_code": "CA",
         "annual_household_income": 40000, "household_size": 1}, FD)
    data = validate_success(resp, 201)
    assert data["fpl_percent"] == 265.60
    assert data["sliding_fee_multiplier"] == 0.80
    assert data["status"] == "ACTIVE"


def test_get_nonexistent_therapist_returns_not_found():
    """PRD §2.5: "The first identifier that does not resolve to an existing resource
    causes the request to be rejected with ERR_NOT_FOUND before any business rule is
    evaluated."

    Design: Corner/entities/get_nonexistent_therapist_returns_not_found
    """
    resp = api_client.get_therapist("00000000-0000-4000-8000-000000000000", CD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_patient_missing_household_size_returns_invalid_request():
    """PRD §3.4: "Front-desk staff or a director register a patient with their
    full_name, their location_state_code ..., their annual_household_income in whole
    dollars (which must be zero or greater), and their household_size (which must be at
    least one)."

    Design: Corner/entities/create_patient_missing_required_field_returns_invalid_request
    """
    resp = api_client.create_patient(
        {"full_name": "X", "location_state_code": "CA",
         "annual_household_income": 40000}, FD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_crisis_assessment_score_out_of_range_returns_invalid_request():
    """PRD §3.8: "four severity factors each in the range 0 through 3: ideation_score,
    plan_score, means_access_score, and prior_attempts_score."

    Design: Corner/entities/crisis_assessment_score_out_of_range_returns_invalid_request
    """
    therapist = create_associate_therapist(full_name="Dr Q")
    patient = create_patient(full_name="Pt Q")
    resp = api_client.create_crisis_assessment(
        create_crisis_assessment_payload(patient["id"], therapist["id"],
                                         ideation_score=4),
        make_therapist_headers(therapist["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_state_license_default_telehealth_authorized_true():
    """PRD §3.1: "an optional telehealth_authorized flag that defaults to true. A new
    license is born ACTIVE."

    Design: Corner/entities/state_license_default_telehealth_authorized_true
    """
    therapist = create_associate_therapist(full_name="Dr D")
    resp = api_client.create_state_license(
        {"therapist_id": therapist["id"], "state_code": "CA", "license_number": "LD",
         "expires_on": "2030-01-01T00:00:00Z"}, CD)
    data = validate_success(resp, 201)
    assert data["telehealth_authorized"] is True
    assert data["status"] == "ACTIVE"


def test_system_fields_minted_on_therapist_create():
    """PRD §2.4: "carries a system-managed id that is a UUID with no type prefix ... an
    integer version that begins at its initial value and increments by one with each
    modification."
    PRD §3.1: "Every new clinician begins life in ASSOCIATE standing and requiring
    supervision"

    Design: Corner/entities/system_fields_minted_on_therapist_create
    """
    resp = api_client.create_therapist({"full_name": "Dr Sys"}, CD)
    data = validate_success(resp, 201)
    assert data["version"] == 1
    assert data["credential_status"] == "ASSOCIATE"
    assert data["requires_supervision"] is True


def test_list_patients_pagination_envelope():
    """PRD §2.3: "Every list response includes limit, offset, total_count, and has_more
    in the meta object of the envelope."

    Design: Corner/entities/list_patients_pagination_envelope
    """
    create_patient(full_name="Pt 1", state_code="CA")
    create_patient(full_name="Pt 2", state_code="NY")
    resp = api_client.list_patients(FD)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_appointment_cpt_duration_mismatch_rejected():
    """PRD §3.5: "The session length must match the procedure code — a 90791 must be
    exactly 60 minutes and a 90834 exactly 45 minutes — or the request is rejected with
    ERR_CPT_DURATION_MISMATCH."

    Design: Corner/validations/appointment_cpt_duration_mismatch_rejected
    """
    therapist = create_associate_therapist(full_name="Dr Dur")
    patient = create_patient(full_name="Pt Dur")
    resp = api_client.create_appointment(
        {"therapist_id": therapist["id"], "patient_id": patient["id"],
         "cpt_code": "90834", "modality": "IN_PERSON",
         "start_at": "2026-07-08T08:00:00Z", "duration_minutes": 60,
         "payment_path": "SELF_PAY"}, FD)
    validate_error(resp, ApiErrorId.ERR_CPT_DURATION_MISMATCH.value)


def test_self_pay_with_insurance_policy_rejected():
    """PRD §3.5: "an INSURANCE session requires a non-null insurance_policy_id whose own
    patient matches the appointment's patient, while a SELF_PAY session requires the
    policy reference to be absent; a violation is rejected with ERR_PAYMENT_PATH_INVALID."

    Design: Corner/validations/self_pay_with_insurance_policy_rejected
    """
    therapist = create_associate_therapist(full_name="Dr PP")
    contract = create_payer_contract(in_network=False, rate_90791=0, rate_90834=0)
    patient = create_patient(full_name="Pt PP")
    policy = create_policy(patient["id"], contract["id"], cost_share_model="COPAY",
                           copay_cents=2500, deductible_total_cents=0)
    resp = api_client.create_appointment(
        {"therapist_id": therapist["id"], "patient_id": patient["id"],
         "cpt_code": "90834", "modality": "IN_PERSON",
         "start_at": "2026-07-08T09:00:00Z", "duration_minutes": 45,
         "payment_path": "SELF_PAY", "insurance_policy_id": policy["id"]}, FD)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_PATH_INVALID.value)


def test_frontdesk_cannot_promote_therapist():
    """PRD §2.1: "A request whose role is not permitted to invoke the targeted endpoint
    is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/frontdesk_cannot_promote_therapist
    """
    therapist = create_associate_therapist(full_name="Dr RB")
    resp = api_client.promote_therapist(
        therapist["id"], {"expected_therapist_version": therapist["version"]}, FD)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_biller_cannot_render_appointment():
    """PRD §2.1: "A request whose role is not permitted to invoke the targeted endpoint
    is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/biller_cannot_render_appointment
    """
    set_clock("2026-07-12T12:00:00Z")
    therapist = create_associate_therapist(full_name="Dr RB2")
    get_success_data(api_client.create_state_license(
        {"therapist_id": therapist["id"], "state_code": "CA", "license_number": "LRb",
         "expires_on": "2030-01-01T00:00:00Z"}, CD))
    patient = create_patient(full_name="Pt RB")
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-07-12T08:00:00Z", payment_path="SELF_PAY")
    resp = api_client.render_appointment(appt["id"], BILLER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_therapist_cannot_render_other_therapists_appointment():
    """PRD §2.1: "when a clinician acts to render or complete an appointment, or to sign
    or co-sign a clinical note, X-User-ID must equal the rendering clinician of the
    linked appointment (or, for co-signing, that clinician's supervisor), failing which
    the request is rejected with ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/therapist_cannot_render_other_therapists_appointment
    """
    set_clock("2026-07-13T12:00:00Z")
    ta = create_associate_therapist(full_name="Dr A")
    tb = create_associate_therapist(full_name="Dr B")
    get_success_data(api_client.create_state_license(
        {"therapist_id": ta["id"], "state_code": "CA", "license_number": "LA9",
         "expires_on": "2030-01-01T00:00:00Z"}, CD))
    patient = create_patient(full_name="Pt OW")
    appt = schedule_appointment(
        ta["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-07-13T08:00:00Z", payment_path="SELF_PAY")
    resp = api_client.render_appointment(appt["id"], make_therapist_headers(tb["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_auth_headers_returns_unauthenticated():
    """PRD §2.1: "A request missing either header is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api_client.list_patients({})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_list_state_licenses_filtered_by_therapist_id():
    """PRD §3.1: "Licenses are retrievable individually and as a filtered list — by
    therapist_id or by state_code — so that a clinician's full jurisdictional footprint
    can be enumerated."

    Design: Corner/endpoints/list_state_licenses_filtered_by_therapist_id
    """
    therapist = create_associate_therapist(full_name="Dr ML")
    get_success_data(api_client.create_state_license(
        {"therapist_id": therapist["id"], "state_code": "CA", "license_number": "M1",
         "expires_on": "2030-01-01T00:00:00Z"}, CD))
    get_success_data(api_client.create_state_license(
        {"therapist_id": therapist["id"], "state_code": "NY", "license_number": "M2",
         "expires_on": "2030-01-01T00:00:00Z"}, CD))
    resp = api_client.list_state_licenses(CD, params={"therapist_id": therapist["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2


def test_get_appointment_returns_stored_entity():
    """PRD §3.5: "Appointments are retrievable individually and as a list filtered by
    therapist_id, patient_id, insurance_policy_id, or status."
    PRD §3.6: "Until a session is rendered its patient_charge_cents is 0."

    Design: Corner/endpoints/get_appointment_returns_stored_entity
    """
    therapist = create_associate_therapist(full_name="Dr GA")
    patient = create_patient(full_name="Pt GA")
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90791", duration_minutes=60,
        start_at="2026-07-14T08:00:00Z", payment_path="SELF_PAY")
    data = validate_success(api_client.get_appointment(appt["id"], FD), 200)
    assert data["status"] == "SCHEDULED"
    assert data["cpt_code"] == "90791"
    assert data["patient_charge_cents"] == 0
