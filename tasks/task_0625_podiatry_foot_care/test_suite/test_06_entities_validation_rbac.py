"""Entity creation, defaults, computed risk category, FK/required/enum
validation, RBAC denials, recall cadence, the logical clock default, and list
filtering.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error, validate_paginated,
    assert_practice, assert_provider, assert_patient, assert_recall,
    ApiErrorId, TEST_USERS, make_podiatrist_headers, NONEXISTENT_UUID,
    setup_practice_provider_patient, create_encounter, complete_exam, set_clock,
)
from test_helpers import (
    create_provider_payload, create_patient_payload, create_encounter_payload,
    create_recall_payload, create_practice_payload,
)

ADMIN = TEST_USERS["practice_admin_headers"]
FRONTDESK = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
PODIATRIST = TEST_USERS["podiatrist_headers"]
PAYER = TEST_USERS["payer_agent_headers"]


def _practice():
    return get_success_data(api_client.create_practice(create_practice_payload(), ADMIN))


# ─── entities / create_practice_returns_201_with_defaults ──────────────────
def test_create_practice_applies_defaults(api):
    """PRD §3.1: "`routine_care_min_interval_days`, the minimum number of days
    that must elapse between covered routine foot-care procedures, which defaults
    to 61; and `fee_split_medicare_pct`, the fraction of an allowed amount the
    payer covers on a covered line, which defaults to 0.80 with the patient owing
    the rest."
    PRD §2.4: "an integer `version` that begins at its initial value and
    increments by one on every mutation."

    Design: Corner/entities/create_practice_returns_201_with_defaults
    """
    res = api.create_practice(create_practice_payload(name="Foot Clinic", npi="1234567890"), ADMIN)
    practice = validate_success(res, 201)
    assert_practice(practice)
    assert practice["routine_care_min_interval_days"] == 61
    assert practice["fee_split_medicare_pct"] == 0.80
    assert practice["version"] == 1


# ─── entities / create_provider_missing_required_full_name_rejected ────────
def test_create_provider_missing_full_name_rejected(api):
    """PRD §2.7: "Every required field must be present and well-typed ... Any
    violation of these structural rules is rejected with `ERR_INVALID_REQUEST`
    (HTTP 422)."

    Design: Corner/entities/create_provider_missing_required_full_name_rejected
    """
    practice = _practice()
    payload = create_provider_payload(practice["id"])
    del payload["full_name"]
    res = api.create_provider(payload, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── entities / create_provider_invalid_enum_role_type_rejected ────────────
def test_create_provider_invalid_role_type_rejected(api):
    """PRD §2.7: "every enum-valued field must hold one of its allowed values ...
    Any violation of these structural rules is rejected with
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_provider_invalid_enum_role_type_rejected
    """
    practice = _practice()
    res = api.create_provider(
        create_provider_payload(practice["id"], full_name="Dr X", role_type="SURGEON"), ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── entities / provider_is_active_default_true ────────────────────────────
def test_provider_is_active_defaults_true(api):
    """PRD §3.1: "an optional `is_active` flag (defaulting to true) records
    whether the provider accepts new encounters."

    Design: Corner/entities/provider_is_active_default_true
    """
    practice = _practice()
    res = api.create_provider(
        create_provider_payload(practice["id"], full_name="Dr Default"), ADMIN)
    provider = validate_success(res, 201)
    assert provider["is_active"] is True


# ─── entities / patient_risk_category_computed_cat2_lops_pad ───────────────
def test_patient_risk_category_cat2_lops_and_pad(api):
    """PRD §3.2: "if the patient has loss of protective sensation and
    additionally has either peripheral arterial disease or a foot deformity, the
    category is 2."

    Design: Corner/entities/patient_risk_category_computed_cat2_lops_pad
    """
    practice = _practice()
    res = api.create_patient(
        create_patient_payload(practice["id"], full_name="Pat R2",
                               date_of_birth="1955-01-01", has_diabetes_mellitus=True,
                               has_loss_protective_sensation=True,
                               has_peripheral_arterial_disease=True),
        FRONTDESK)
    patient = validate_success(res, 201)
    assert patient["diabetic_foot_risk_category"] == 2


# ─── entities / patient_risk_category_cat3_prior_ulcer_overrides ───────────
def test_patient_risk_category_cat3_prior_ulcer(api):
    """PRD §3.2: "under a fixed precedence in which the highest applicable
    category wins. If the patient has a prior ulcer or amputation, the category
    is 3."

    Design: Corner/entities/patient_risk_category_cat3_prior_ulcer_overrides
    """
    practice = _practice()
    res = api.create_patient(
        create_patient_payload(practice["id"], full_name="Pat R3",
                               date_of_birth="1950-01-01", has_diabetes_mellitus=True,
                               has_prior_ulcer_or_amputation=True),
        FRONTDESK)
    patient = validate_success(res, 201)
    assert patient["diabetic_foot_risk_category"] == 3


# ─── entities / patch_risk_factors_recomputes_category ─────────────────────
def test_patch_risk_factors_recomputes_category_and_bumps_version(api):
    """PRD §3.2: "When risk factors are updated, the `diabetic_foot_risk_category`
    is recomputed by the same precedence rule and the patient's `version` is
    incremented."
    PRD §3.2: "Otherwise, if the patient has loss of protective sensation, the
    category is 1."

    Design: Corner/entities/patch_risk_factors_recomputes_category
    """
    practice, provider, patient = setup_practice_provider_patient(
        patient_overrides={"full_name": "Pat R0", "date_of_birth": "1960-01-01",
                           "has_diabetes_mellitus": True})
    assert patient["diabetic_foot_risk_category"] == 0
    res = api.update_patient_risk_factors(
        patient["id"], {"has_loss_protective_sensation": True},
        make_podiatrist_headers(provider["id"]))
    updated = validate_success(res, 200)
    assert updated["diabetic_foot_risk_category"] == 1
    assert updated["version"] == 2


# ─── entities / system_fields_input_ignored_on_patient_create ──────────────
def test_client_supplied_risk_category_ignored(api):
    """PRD §3.2: "The patient's `diabetic_foot_risk_category` is a derived
    integer from 0 to 3 computed from four of the risk booleans ... Otherwise
    the category is 0."

    Design: Corner/entities/system_fields_input_ignored_on_patient_create
    """
    practice = _practice()
    payload = create_patient_payload(practice["id"], full_name="Pat Sys",
                                     date_of_birth="1970-01-01", has_diabetes_mellitus=False)
    payload["diabetic_foot_risk_category"] = 3  # client attempt — must be ignored
    res = api.create_patient(payload, FRONTDESK)
    patient = validate_success(res, 201)
    assert patient["diabetic_foot_risk_category"] == 0


# ─── entities / get_patient_nonexistent_returns_not_found ──────────────────
def test_get_nonexistent_patient_not_found(api):
    """PRD §2.6: "a path identifier that names no existing row is rejected with
    `ERR_NOT_FOUND` (HTTP 404)"

    Design: Corner/entities/get_patient_nonexistent_returns_not_found
    """
    res = api.get_patient(NONEXISTENT_UUID, FRONTDESK)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ─── entities / create_encounter_unknown_provider_fk_not_found ─────────────
def test_create_encounter_unknown_provider_fk_not_found(api):
    """PRD §2.6: "Whenever a write supplies a foreign key — `practice_id`,
    `patient_id`, `provider_id`, `modality_id`, `encounter_id`,
    `prior_authorization_id`, or `orthotic_rx_id` — the referenced row must
    exist; a dangling reference is rejected with `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/create_encounter_unknown_provider_fk_not_found
    """
    practice = _practice()
    patient = get_success_data(api.create_patient(
        create_patient_payload(practice["id"], full_name="Pat FK",
                               date_of_birth="1971-01-01"), FRONTDESK))
    res = api.create_encounter(
        create_encounter_payload(patient["id"], NONEXISTENT_UUID), FRONTDESK)
    validate_error(res, ApiErrorId.ERR_FK_NOT_FOUND.value)


# ─── entities / encounter_invalid_interval_end_before_start_rejected ───────
def test_encounter_end_before_start_rejected(api):
    """PRD §2.7: "every scheduled interval must have its end strictly after its
    start (an encounter's `scheduled_end` must be after its `scheduled_start` ...
    Any violation of these structural rules is rejected with
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/encounter_invalid_interval_end_before_start_rejected
    """
    practice, provider, patient = setup_practice_provider_patient()
    res = api.create_encounter(
        create_encounter_payload(patient["id"], provider["id"],
                                 scheduled_start="2026-06-01T10:30:00Z",
                                 scheduled_end="2026-06-01T10:00:00Z"),
        FRONTDESK)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── calculations / recall_due_date_cat0_plus_365 ──────────────────────────
def test_recall_cat0_interval_365(api):
    """PRD §3.10: "category 0 yields 365 days, category 1 yields 180 days,
    category 2 yields 90 days, and category 3 yields 30 days — and the `due_date`
    is the `anchor_date` advanced by `interval_days` whole calendar days."

    Design: Corner/calculations/recall_due_date_cat0_plus_365
    """
    practice = _practice()
    patient = get_success_data(api.create_patient(
        create_patient_payload(practice["id"], full_name="Pat C0",
                               date_of_birth="1990-01-01"), FRONTDESK))
    res = api.create_recall(create_recall_payload(patient["id"], anchor_date="2026-06-01"),
                            FRONTDESK)
    recall = validate_success(res, 201)
    assert_recall(recall)
    assert recall["interval_days"] == 365
    assert recall["due_date"] == "2027-06-01"


# ─── calculations / recall_due_date_cat3_plus_30 ───────────────────────────
def test_recall_cat3_interval_30(api):
    """PRD §3.10: "category 3 yields 30 days — and the `due_date` is the
    `anchor_date` advanced by `interval_days` whole calendar days."

    Design: Corner/calculations/recall_due_date_cat3_plus_30
    """
    practice = _practice()
    patient = get_success_data(api.create_patient(
        create_patient_payload(practice["id"], full_name="Pat C3",
                               date_of_birth="1948-01-01", has_diabetes_mellitus=True,
                               has_prior_ulcer_or_amputation=True), FRONTDESK))
    res = api.create_recall(create_recall_payload(patient["id"], anchor_date="2026-06-01"),
                            FRONTDESK)
    recall = validate_success(res, 201)
    assert recall["interval_days"] == 30
    assert recall["due_date"] == "2026-07-01"


# ─── calculations / recall_snapshot_not_re_derived_after_risk_change ───────
def test_recall_interval_snapshot_not_re_derived(api):
    """PRD §3.10: "The recall's `interval_days` is derived from the patient's
    `diabetic_foot_risk_category` as snapshotted at creation time"
    PRD §3.10: "This snapshot is deliberate: a recall is not re-derived if the
    patient's risk category later changes."

    Design: Corner/calculations/recall_snapshot_not_re_derived_after_risk_change
    """
    practice, provider, patient = setup_practice_provider_patient(
        patient_overrides={"full_name": "Pat Snap", "date_of_birth": "1962-01-01",
                           "has_diabetes_mellitus": True})
    recall = get_success_data(api.create_recall(
        create_recall_payload(patient["id"], anchor_date="2026-06-01"), FRONTDESK))
    assert recall["interval_days"] == 365  # category 0 at create
    # Raise the patient to category 1.
    api.update_patient_risk_factors(patient["id"], {"has_loss_protective_sensation": True},
                                    make_podiatrist_headers(provider["id"]))
    recall_after = get_success_data(api.get_recall(recall["id"], FRONTDESK))
    assert recall_after["interval_days"] == 365


# ─── state_machines / recall_complete_then_cancel_rejected_terminal ────────
def test_cancel_completed_recall_rejected(api):
    """PRD §3.10: "completing or cancelling a recall not in `PENDING` is rejected
    with `ERR_RECALL_BAD_STATE`."

    Design: Corner/state_machines/recall_complete_then_cancel_rejected_terminal
    """
    practice = _practice()
    patient = get_success_data(api.create_patient(
        create_patient_payload(practice["id"], full_name="Pat Rec",
                               date_of_birth="1981-01-01"), FRONTDESK))
    recall = get_success_data(api.create_recall(
        create_recall_payload(patient["id"], anchor_date="2026-06-01"), FRONTDESK))
    get_success_data(api.complete_recall(recall["id"], FRONTDESK))
    res = api.cancel_recall(recall["id"], FRONTDESK)
    validate_error(res, ApiErrorId.ERR_RECALL_BAD_STATE.value)


# ─── errors / error_missing_user_context_header ────────────────────────────
def test_missing_user_role_header_rejected(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of
    these five declared roles, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401)."

    Design: Corner/errors/error_missing_user_context_header
    """
    practice = _practice()
    res = api.get_practice(practice["id"], headers={"Content-Type": "application/json"})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT.value)


# ─── rbac / rbac_frontdesk_cannot_code_encounter ───────────────────────────
def test_frontdesk_cannot_code_encounter(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "A `BillingSpecialist` runs the revenue cycle: requesting prior
    authorizations, coding, recoding, submitting and voiding encounters, and
    creating, shipping, or cancelling lab orders."

    Design: Corner/rbac/rbac_frontdesk_cannot_code_encounter
    """
    set_clock("2026-06-01T09:00:00Z")
    practice, provider, patient = setup_practice_provider_patient()
    enc = create_encounter(patient["id"], provider["id"])
    complete_exam(enc["id"], provider["id"])
    res = api.code_encounter(enc["id"], FRONTDESK)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── rbac / rbac_podiatrist_cannot_create_practice ─────────────────────────
def test_podiatrist_cannot_create_practice(api):
    """PRD §2.1: "A `PracticeAdmin` is an operational identity that provisions
    the static backbone of the practice — practices, providers, and imaging
    modalities — and controls the logical clock."

    Design: Corner/rbac/rbac_podiatrist_cannot_create_practice
    """
    res = api.create_practice(create_practice_payload(name="Rogue", npi="9999999999"),
                              make_podiatrist_headers(NONEXISTENT_UUID))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── rbac / rbac_non_rendering_provider_denied_complete_exam ───────────────
def test_non_rendering_provider_denied_complete_exam(api):
    """PRD §3.3: "but only the rendering provider may do so: the acting
    podiatrist's `X-User-ID` must equal the encounter's `provider_id`, failing
    which the request is rejected with `ERR_NOT_RENDERING_PROVIDER`"

    Design: Corner/rbac/rbac_non_rendering_provider_denied_complete_exam
    """
    set_clock("2026-06-01T09:00:00Z")
    practice, provider1, patient = setup_practice_provider_patient(
        provider_overrides={"full_name": "Dr One"})
    provider2 = get_success_data(api.create_provider(
        create_provider_payload(practice["id"], full_name="Dr Two"), ADMIN))
    enc = create_encounter(patient["id"], provider1["id"])
    res = api.complete_exam(enc["id"], make_podiatrist_headers(provider2["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_RENDERING_PROVIDER.value)


# ─── endpoints / list_encounters_filtered_by_provider_id ───────────────────
def test_list_encounters_filtered_by_provider(api):
    """PRD §2.6: "list endpoints accept optional filter query parameters that
    mirror the foreign keys ... encounters by `patient_id` and/or `provider_id`"

    Design: Corner/endpoints/list_encounters_filtered_by_provider_id
    """
    set_clock("2026-06-01T08:00:00Z")
    practice, provider1, patient = setup_practice_provider_patient(
        provider_overrides={"full_name": "Dr One"})
    provider2 = get_success_data(api.create_provider(
        create_provider_payload(practice["id"], full_name="Dr Two"), ADMIN))
    enc1 = create_encounter(patient["id"], provider1["id"],
                            scheduled_start="2026-06-01T09:00:00Z",
                            scheduled_end="2026-06-01T09:30:00Z")
    create_encounter(patient["id"], provider2["id"],
                     scheduled_start="2026-06-01T10:00:00Z",
                     scheduled_end="2026-06-01T10:30:00Z")
    res = api.list_encounters(FRONTDESK, params={"provider_id": provider1["id"]})
    data, meta = validate_paginated(res)
    assert len(data) >= 1
    assert all(e["provider_id"] == provider1["id"] for e in data)
    assert enc1["id"] in [e["id"] for e in data]


# ─── endpoints / list_practices_pagination_envelope_fields ─────────────────
def test_list_providers_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_practices_pagination_envelope_fields
    """
    practice = _practice()
    get_success_data(api.create_provider(
        create_provider_payload(practice["id"], full_name="Dr A", role_type="PODIATRIST"), ADMIN))
    get_success_data(api.create_provider(
        create_provider_payload(practice["id"], full_name="Dr B", role_type="NP_PA"), ADMIN))
    res = api.list_providers(ADMIN, params={"practice_id": practice["id"],
                                            "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
