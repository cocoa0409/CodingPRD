"""Patient registration, referral intake, path/body resolution and access control."""

from test_helpers import (
    ApiErrorId,
    assert_patient,
    assert_referral,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import (
    create_eligibility_assessment_payload,
    create_patient_payload,
    create_referral_payload,
)
from test_helpers.test_users import (
    ADMITTING_PHYSICIAN,
    FIELD_NURSE,
    NO_AUTH_HEADERS,
    PROGRAM_ADMIN,
    make_patient_headers,
)


def test_patient_registration_applies_declared_defaults(api):
    """PRD §3.1: "Three further attributes are optional at registration and take
    documented defaults if omitted: `diet_restriction` defaults to `NONE`,
    `broadband_verified` defaults to `false`, and `caregiver_present` defaults to
    `false`."
    PRD §3.1: "The new record's `status` is initialized by the system to
    `REGISTERED`; callers never supply it."
    PRD §2.4: "`version` is an integer that begins at 1 when the row is created
    and increases by exactly 1 on every mutation of that row"

    Design: Corner/entities/patient_create_applies_declared_defaults_and_system_fields
    """
    payload = create_patient_payload(
        mrn="MRN-DEF",
        full_name="Dee Fault",
        home_distance_km=5.0,
        primary_diagnosis_code="CHF_EXAC",
    )
    data = validate_success(api.create_patient(payload, PROGRAM_ADMIN), 201)

    assert_patient(data)
    assert data["diet_restriction"] == "NONE", (
        f"omitted diet_restriction must default to NONE, got {data['diet_restriction']}"
    )
    assert data["broadband_verified"] is False, (
        "omitted broadband_verified must default to false"
    )
    assert data["caregiver_present"] is False, (
        "omitted caregiver_present must default to false"
    )
    assert data["status"] == "REGISTERED", (
        f"a new patient opens in REGISTERED, got {data['status']}"
    )
    assert data["version"] == 1, f"version begins at 1, got {data['version']}"


def test_patient_registration_without_mrn_is_rejected(api):
    """PRD §2.5: "(4a) Every field the endpoint declares required is present and
    not null — violation `ERR_VALIDATION` (400), applying to every POST, PUT and
    PATCH endpoint."
    PRD §3.1: "Registering a patient captures the medical record number `mrn`,
    which must be non-empty and unique across all patients, together with the
    patient's legal `full_name` and `home_distance_km` — the road distance in
    kilometres from the program hub to the front door, which must be at least 0
    and is the number the service-radius rule later interrogates."

    Design: Corner/entities/patient_create_missing_required_mrn_returns_validation
    """
    response = api.create_patient(
        {
            "full_name": "No Mrn",
            "home_distance_km": 5.0,
            "primary_diagnosis_code": "CHF_EXAC",
        },
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)


def test_referral_with_unknown_origin_value_is_rejected_as_invalid_enum(api):
    """PRD §2.10: "Every enumerated value below is matched exactly,
    case-sensitively; anything outside the declared set is rejected at rung 4
    with `ERR_INVALID_ENUM`."
    PRD §2.10: "A referral's `origin` is `ED`, `INPATIENT_WARD`, `CLINIC` or
    `SNF`; its `acuity`, and the episode `acuity` copied from it, is `STANDARD`
    or `HIGH`; and its `status` runs `SUBMITTED`, `SCREENING`, `ELIGIBLE`,
    `ADMITTED`, `CLOSED`."

    Design: Corner/entities/referral_create_invalid_enum_origin_returns_invalid_enum
    """
    patient = fx.register_patient(mrn="MRN-EN", full_name="Ena Enum")

    response = api.create_referral(
        create_referral_payload(patient["id"], origin="HOSPICE"), ADMITTING_PHYSICIAN
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value)

    rows, meta = validate_paginated(
        api.list_patient_referrals(patient["id"], PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 0, "the rejected referral must not be persisted"
    assert rows == []


def test_unknown_episode_id_in_path_returns_episode_not_found(api):
    """PRD §2.4: "The error identifier chosen at this step depends on the
    resource type of the segment that failed: a patient segment yields
    `ERR_PATIENT_NOT_FOUND`, a referral segment yields `ERR_REFERRAL_NOT_FOUND`,
    an episode segment yields `ERR_EPISODE_NOT_FOUND`, and every other resource
    type — visit, compliance day, device kit, device component, delivery order,
    meal plan, escalation event, inpatient unit, bed reservation, billing claim —
    yields `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/episode_get_with_unknown_id_returns_episode_not_found
    """
    response = api.get_episode(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMITTING_PHYSICIAN
    )
    validate_error(response, ApiErrorId.ERR_EPISODE_NOT_FOUND.value)


def test_unknown_device_kit_id_in_path_returns_generic_resource_not_found(api):
    """PRD §2.4: "The error identifier chosen at this step depends on the
    resource type of the segment that failed: a patient segment yields
    `ERR_PATIENT_NOT_FOUND`, a referral segment yields `ERR_REFERRAL_NOT_FOUND`,
    an episode segment yields `ERR_EPISODE_NOT_FOUND`, and every other resource
    type — visit, compliance day, device kit, device component, delivery order,
    meal plan, escalation event, inpatient unit, bed reservation, billing claim —
    yields `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/device_kit_get_with_unknown_id_returns_generic_resource_not_found
    """
    response = api.get_device_kit(
        "11111111-2222-4333-8444-555555555555", PROGRAM_ADMIN
    )
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


def test_referral_body_with_unknown_patient_id_returns_patient_not_found(api):
    """PRD §2.5: "**Rung 5 — Body foreign-key existence.** Every foreign key
    supplied in a request body resolves: `patient_id` yields
    `ERR_PATIENT_NOT_FOUND`, `referral_id` yields `ERR_REFERRAL_NOT_FOUND`,
    `episode_id` yields `ERR_EPISODE_NOT_FOUND`, and `unit_id` or `kit_id` yields
    `ERR_RESOURCE_NOT_FOUND`; all at HTTP 404."

    Design: Corner/entities/referral_create_with_unknown_patient_returns_patient_not_found
    """
    response = api.create_referral(
        create_referral_payload("99999999-8888-4777-8666-555555555555"),
        ADMITTING_PHYSICIAN,
    )
    validate_error(response, ApiErrorId.ERR_PATIENT_NOT_FOUND.value)


def test_assessment_body_with_unknown_referral_id_returns_referral_not_found(api):
    """PRD §2.5: "**Rung 5 — Body foreign-key existence.** Every foreign key
    supplied in a request body resolves: `patient_id` yields
    `ERR_PATIENT_NOT_FOUND`, `referral_id` yields `ERR_REFERRAL_NOT_FOUND`,
    `episode_id` yields `ERR_EPISODE_NOT_FOUND`, and `unit_id` or `kit_id` yields
    `ERR_RESOURCE_NOT_FOUND`; all at HTTP 404."

    Design: Corner/entities/eligibility_assessment_with_unknown_referral_returns_referral_not_found
    """
    payload = create_eligibility_assessment_payload(
        "77777777-6666-4555-8444-333333333333", "2026-06-01T06:00:00Z"
    )
    response = api.create_eligibility_assessment(payload, ADMITTING_PHYSICIAN)
    validate_error(response, ApiErrorId.ERR_REFERRAL_NOT_FOUND.value)


def test_patient_referral_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "`limit` controls page size: its default is 10, its minimum
    accepted value is 1, and its maximum accepted value is 100; a supplied value
    below 1 or above 100 is a bound violation rejected with `ERR_VALIDATION`
    (HTTP 400)."
    PRD §2.3: "Both are echoed back in the `meta` object of the response
    alongside `total_count` — the number of rows matching the filters before the
    page window is applied — and `has_more`, which is true exactly when rows
    remain beyond the current window."

    Design: Corner/entities/patient_referrals_subresource_paginates_with_total_count_and_has_more
    """
    patient = fx.register_patient(mrn="MRN-PG", full_name="Peg Paging")
    fx.file_referral(patient["id"], origin="ED", qualifying_condition_code="CHF_EXAC")
    fx.file_referral(
        patient["id"], origin="INPATIENT_WARD", qualifying_condition_code="COPD_EXAC"
    )
    fx.file_referral(
        patient["id"], origin="CLINIC", qualifying_condition_code="OTHER"
    )

    first_page, first_meta = validate_paginated(
        api.list_patient_referrals(
            patient["id"], PROGRAM_ADMIN, params={"limit": 2, "offset": 0}
        )
    )
    assert first_meta["total_count"] == 3, (
        f"total_count must count all three referrals, got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, "rows remain beyond the first page of 2"
    assert len(first_page) == 2, f"expected 2 rows on the first page, got {len(first_page)}"
    for row in first_page:
        assert_referral(row)

    second_page, second_meta = validate_paginated(
        api.list_patient_referrals(
            patient["id"], PROGRAM_ADMIN, params={"limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1, (
        f"expected 1 row on the second page, got {len(second_page)}"
    )
    assert second_meta["has_more"] is False, "no rows remain beyond the second page"
    assert second_meta["total_count"] == 3


def test_request_without_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request to this API — without exception, including reads
    — must carry two headers: `X-User-ID`, identifying the acting principal, and
    `X-User-Role`, naming the role that principal is acting in. If either header
    is absent, or if `X-User-Role` carries a string that is not one of the eight
    declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401) before any other evaluation takes place."

    Design: Corner/rbac/request_missing_auth_headers_returns_unauthenticated
    """
    response = api.create_patient({"full_name": "Anon Ymous"}, NO_AUTH_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_field_nurse_cannot_admit_an_episode(api):
    """PRD §2.1: "When both headers are well formed but the named role is not
    among the roles authorized for the target endpoint (see the Authorized
    Role(s) column of the table in §4), the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "**`AdmittingPhysician`** is the attending clinician. This role
    alone files referrals, marks a referral eligible, admits a patient to the
    program, signs medication reconciliation, begins and completes discharge,
    readmits a returned episode, holds an inpatient bed, and converts an
    escalation into a bed return."

    Design: Corner/rbac/field_nurse_cannot_admit_an_episode_and_gets_forbidden_role
    """
    parts = fx.setup_eligible_referral(mrn="MRN-RB", full_name="Rob Rbac")
    patient, referral = parts["patient"], parts["referral"]

    response = api.create_episode(
        {
            "patient_id": patient["id"],
            "referral_id": referral["id"],
            "program_track": "CMS_WAIVER",
        },
        FIELD_NURSE,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    still_eligible = validate_success(
        api.get_referral(referral["id"], ADMITTING_PHYSICIAN)
    )
    assert still_eligible["status"] == "ELIGIBLE", (
        "the rejected admission must not consume the referral"
    )

    rows, meta = validate_paginated(
        api.list_episodes(PROGRAM_ADMIN, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0, "no episode may exist after a forbidden admission"
    assert rows == []


def test_patient_reads_own_record_through_entity_backed_identity(api):
    """PRD §2.1: "The eighth role is different: when `X-User-Role` is `Patient`,
    `X-User-ID` is the `id` of the acting `Patient` record, and ownership checks
    on any resource that references a patient compare that resource's patient
    foreign key to `X-User-ID`."

    Design: Corner/rbac/patient_role_reads_its_own_record_through_entity_backed_identity
    """
    payload = create_patient_payload(
        mrn="MRN-PT",
        full_name="Pia Patient",
        home_distance_km=5.0,
        primary_diagnosis_code="CHF_EXAC",
        diet_restriction="LOW_SODIUM",
    )
    created = validate_success(api.create_patient(payload, PROGRAM_ADMIN), 201)

    own = validate_success(
        api.get_patient(created["id"], make_patient_headers(created["id"]))
    )
    assert own["id"] == created["id"], "the patient must read back their own row"
    assert own["diet_restriction"] == "LOW_SODIUM"
    assert own["status"] == "REGISTERED"
