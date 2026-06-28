"""Resource creation, defaults, care-plan activation guards, structural validation
ordering, and role-based access control.

Covers corner sections: entities, the care-plan state-machine instances,
validations (existence ordering, duplicate mrn), errors (reference not found), and
rbac (forbidden ops, unauthenticated).
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID, set_clock,
    create_payer, create_patient, create_care_plan, activate_care_plan,
    create_billing_period, create_consent,
)

CC = TEST_USERS["care_coordinator_headers"]
PHYS = TEST_USERS["physician_headers"]
CLIN = TEST_USERS["clinician_headers"]
BILL = TEST_USERS["billing_specialist_headers"]


# ---- entities ----
def test_create_patient_returns_201_with_system_defaults(api):
    """PRD §3.1: "Every new patient begins life with `enrollment_status` of
    `PENDING_CONSENT` and `monitoring_status` of `INACTIVE`, and its `care_plan_id`
    back-pointer — a convenience reference to the patient's current active plan — begins
    null."
    PRD §2.4: "`version` — an integer that begins at its initial value and increments by
    one on every mutation."

    Design: Corner/entities/create_patient_returns_201_with_system_defaults
    """
    payer = create_payer(name="P-EC1", payer_type="COMMERCIAL",
                         rate_99453_cents=2000, rate_99454_cents=4000, rate_99457_cents=5000)
    patient = validate_success(api.create_patient(
        {"payer_id": payer["id"], "mrn": "M-EC1-1", "full_name": "Edge Create"}, CC), 201)
    assert patient["enrollment_status"] == "PENDING_CONSENT"
    assert patient["monitoring_status"] == "INACTIVE"
    assert patient["version"] == 1
    assert patient["care_plan_id"] is None


def test_get_patient_not_found_returns_404(api):
    """PRD §2.5: "The server validates the identifiers in a path strictly left-to-right
    and rejects the request at the first identifier that does not resolve, returning
    `ERR_NOT_FOUND`."

    Design: Corner/entities/get_patient_not_found_returns_404
    """
    resp = api.get_patient(NON_EXISTENT_UUID, CC)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_patient_missing_mrn_returns_422(api):
    """PRD §2.5: "the system check that all required body fields are present and of the
    declared type or enum domain, rejecting violations with `ERR_INVALID_REQUEST`."
    PRD §3.1: "The `mrn` must be non-empty and unique across all patients whose
    `enrollment_status` is one of `PENDING_CONSENT`, `ENROLLED`, or `SUSPENDED`."

    Design: Corner/entities/create_patient_missing_required_field_returns_422
    """
    payer = create_payer(name="P-EC2", payer_type="COMMERCIAL",
                         rate_99453_cents=2000, rate_99454_cents=4000, rate_99457_cents=5000)
    resp = api.create_patient({"payer_id": payer["id"], "full_name": "No MRN"}, CC)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_patient_invalid_payer_reference_returns_404(api):
    """PRD §3.1: "The referenced payer must exist or the create fails with
    `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/create_patient_invalid_payer_reference_returns_404
    """
    resp = api.create_patient(
        {"payer_id": NON_EXISTENT_UUID, "mrn": "M-EC3-1", "full_name": "Bad Payer"}, CC)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


def test_device_invalid_enum_device_type_returns_422(api):
    """PRD §2.5: "the system check that all required body fields are present and of the
    declared type or enum domain, rejecting violations with `ERR_INVALID_REQUEST`."
    PRD §3.4: "A `CareCoordinator` enrolls a device for a patient by supplying its
    `device_type` — one of `BP_CUFF`, `GLUCOMETER`, `PULSE_OX`, or `WEIGHT_SCALE`."

    Design: Corner/entities/device_invalid_enum_device_type_returns_422
    """
    payer = create_payer(name="P-EC4", payer_type="COMMERCIAL",
                         rate_99453_cents=2000, rate_99454_cents=4000, rate_99457_cents=5000)
    patient = create_patient(payer["id"], mrn="M-EC4-1")
    resp = api.create_device(
        patient["id"], {"device_type": "THERMOMETER", "serial_number": "SN-EC4-1"}, CC)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_care_plan_required_minutes_default_applied(api):
    """PRD §3.2: "an optional `required_care_minutes` — the monthly care-minute target the
    plan commits to, which defaults to 20 and must be at least 20."
    PRD §3.2: "A freshly drafted plan has `status` of `DRAFT`."

    Design: Corner/entities/care_plan_required_minutes_default_applied
    """
    payer = create_payer(name="P-EC5", payer_type="COMMERCIAL",
                         rate_99453_cents=2000, rate_99454_cents=4000, rate_99457_cents=5000)
    patient = create_patient(payer["id"], mrn="M-EC5-1")
    plan = validate_success(api.create_care_plan(
        patient["id"], {"diagnosis_code": "I10", "goal_text": "BP"}, PHYS), 201)
    assert plan["required_care_minutes"] == 20
    assert plan["status"] == "DRAFT"


def test_list_patients_paginated_envelope(api):
    """PRD §2.3: "Each list response carries four pagination fields in the `meta` object
    of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_patients_paginated_envelope
    """
    payer = create_payer(name="P-EC7", payer_type="COMMERCIAL",
                         rate_99453_cents=2000, rate_99454_cents=4000, rate_99457_cents=5000)
    create_patient(payer["id"], mrn="M-EC7-1", full_name="List A")
    create_patient(payer["id"], mrn="M-EC7-2", full_name="List B")
    resp = api.list_patients(CC, params={"payer_id": payer["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ---- care-plan state machine ----
def test_care_plan_initial_state_is_draft(api):
    """PRD §3.2: "A freshly drafted plan has `status` of `DRAFT`."

    Design: Corner/state_machines/care_plan_initial_state_is_draft
    """
    payer = create_payer(name="P-SM4", payer_type="COMMERCIAL",
                         rate_99453_cents=2000, rate_99454_cents=4000, rate_99457_cents=5000)
    patient = create_patient(payer["id"], mrn="M-SM4-1")
    plan = validate_success(api.create_care_plan(
        patient["id"], {"diagnosis_code": "I10", "goal_text": "BP", "required_care_minutes": 25},
        PHYS), 201)
    assert plan["status"] == "DRAFT"


def test_activate_second_care_plan_without_supersede_rejected(api):
    """PRD §3.2: "Activating a draft plan advances it from `DRAFT` to `ACTIVE`, but only
    if no other care plan for that patient is already `ACTIVE`; attempting to activate a
    second concurrent active plan without the supersede flag is refused with
    `ERR_ACTIVE_PLAN_EXISTS`."

    Design: Corner/state_machines/activate_second_care_plan_without_supersede_rejected
    """
    payer = create_payer(name="P-SM5")
    patient = create_patient(payer["id"], mrn="M-SM5-1")
    plan1 = create_care_plan(patient["id"])
    activate_care_plan(patient["id"], plan1["id"])
    plan2 = create_care_plan(patient["id"], diagnosis_code="E11.9", goal_text="glucose")
    resp = api.activate_care_plan(patient["id"], plan2["id"], {}, PHYS)
    validate_error(resp, ApiErrorId.ERR_ACTIVE_PLAN_EXISTS.value)
    still_active = get_success_data(api.get_care_plan(plan1["id"], PHYS))
    assert still_active["status"] == "ACTIVE"


def test_care_plan_supersede_revises_prior_active(api):
    """PRD §3.2: "When supersede is set, the activation is treated as a revision: the
    patient's prior `ACTIVE` plan transitions `ACTIVE → REVISED`, its
    `superseded_by_plan_id` is set to the newly activated plan's `id`, and that prior
    plan's version is bumped."
    PRD §3.2: "On activation the plan's `status` becomes `ACTIVE` and the patient's
    `care_plan_id` is set to the activated plan's `id`."

    Design: Corner/state_machines/care_plan_supersede_revises_prior_active
    """
    payer = create_payer(name="P-SM6")
    patient = create_patient(payer["id"], mrn="M-SM6-1")
    plan1 = create_care_plan(patient["id"])
    activate_care_plan(patient["id"], plan1["id"])
    plan2 = create_care_plan(patient["id"], goal_text="BP tighter", required_care_minutes=30)
    plan2_active = validate_success(
        api.activate_care_plan(patient["id"], plan2["id"], {"supersede": True}, PHYS), 200)
    assert plan2_active["status"] == "ACTIVE"
    prior = get_success_data(api.get_care_plan(plan1["id"], PHYS))
    assert prior["status"] == "REVISED"
    assert prior["superseded_by_plan_id"] == plan2["id"]
    patient_after = get_success_data(api.get_patient(patient["id"], CC))
    assert patient_after["care_plan_id"] == plan2["id"]


# ---- validations: structural ordering, duplicate mrn ----
def test_device_activate_on_missing_patient_resolves_path_first(api):
    """PRD §2.5: "A request for a device under a non-existent patient fails on the patient
    before the device is ever consulted."
    PRD §2.5: "The server validates the identifiers in a path strictly left-to-right and
    rejects the request at the first identifier that does not resolve, returning
    `ERR_NOT_FOUND`."

    Design: Corner/validations/existence_left_to_right_path_validation
    """
    resp = api.activate_device(NON_EXISTENT_UUID, NON_EXISTENT_UUID, CC)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_duplicate_mrn_among_active_patients_rejected(api):
    """PRD §3.1: "The `mrn` must be non-empty and unique across all patients whose
    `enrollment_status` is one of `PENDING_CONSENT`, `ENROLLED`, or `SUSPENDED`; a
    collision against an active patient is refused with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/error_duplicate_mrn_already_implied
    """
    payer = create_payer(name="P-V7", payer_type="COMMERCIAL",
                         rate_99453_cents=2000, rate_99454_cents=4000, rate_99457_cents=5000)
    create_patient(payer["id"], mrn="M-DUP-1", full_name="Dup A")
    resp = api.create_patient(
        {"payer_id": payer["id"], "mrn": "M-DUP-1", "full_name": "Dup B"}, CC)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


# ---- errors: body FK resolution ----
def test_care_activity_bad_billing_period_reference_returns_404(api):
    """PRD §2.5: "the system confirms that every foreign key carried in the request body
    resolves to an existing entity — `payer_id`, `billing_period_id`, `device_id`,
    `vitals_reading_id`, and `threshold_alert_id` are all subject to this — failing with
    `ERR_REFERENCE_NOT_FOUND` when a referenced row is absent."

    Design: Corner/errors/error_reference_not_found_on_care_activity_bad_period
    """
    payer = create_payer(name="P-ER1")
    patient = create_patient(payer["id"], mrn="M-ER1-1")
    create_consent(patient["id"], consent_type="BOTH")
    plan = create_care_plan(patient["id"])
    activate_care_plan(patient["id"], plan["id"])
    get_success_data(api.enroll_patient(patient["id"], CC))
    set_clock("2026-06-10T00:00:00Z", BILL)
    resp = api.create_care_activity(
        patient["id"],
        {"billing_period_id": NON_EXISTENT_UUID, "clinician_user_id": "clin-12",
         "activity_type": "REVIEW", "minutes": 10, "performed_at": "2026-06-10T10:00:00Z"},
        CLIN)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ---- rbac ----
def test_physician_cannot_create_patient(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §4: the `POST /patients` row authorizes only `CareCoordinator`.

    Design: Corner/rbac/physician_cannot_create_patient
    """
    payer = create_payer(name="P-RB1", payer_type="COMMERCIAL",
                         rate_99453_cents=2000, rate_99454_cents=4000, rate_99457_cents=5000)
    resp = api.create_patient(
        {"payer_id": payer["id"], "mrn": "M-RB1-1", "full_name": "Rbac One"}, PHYS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_clinician_cannot_finalize_billing_period(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §4: the `POST /billing-periods/{id}/finalize` row authorizes only
    `BillingSpecialist`.

    Design: Corner/rbac/clinician_cannot_finalize_billing_period
    """
    payer = create_payer(name="P-RB2")
    patient = create_patient(payer["id"], mrn="M-RB2-1")
    period = create_billing_period(patient["id"], 2026, 6)
    set_clock("2026-07-01T00:00:00Z", BILL)
    bp = get_success_data(api.get_billing_period(period["id"], BILL))
    resp = api.finalize_billing_period(
        period["id"], {"expected_billing_period_version": bp["version"]}, CLIN)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    resp = api.list_patients({})  # no X-User-ID / X-User-Role
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
