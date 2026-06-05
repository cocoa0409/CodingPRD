"""CRUD basics, defaults, type and reference validation, and conditional /
state preconditions on writes.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    make_provider_headers,
    TEST_USERS, NON_EXISTENT_UUID,
    create_provider,
    create_patient,
    create_cpt_code,
    create_visit,
    create_visit_in_progress,
)

FD = TEST_USERS["frontdesk_headers"]
BILLER = TEST_USERS["biller_headers"]


# ─── Queue B: entities / create_patient_returns_201_with_defaults ───

def test_create_patient_returns_201_with_defaults(api):
    """PRD §3.2: "A new patient is created `ACTIVE` with `pcp_id` null and all derived
    counters at zero."

    Design: Corner/entities/create_patient_returns_201_with_defaults
    """
    res = api.create_patient(
        {"first_name": "New", "last_name": "Patient", "date_of_birth": "1990-04-04", "sex": "F"}, FD
    )
    patient = validate_success(res, 201)
    assert patient["status"] == "ACTIVE"
    assert patient["pcp_id"] is None
    assert patient["lifetime_charges_cents"] == 0
    assert patient["version"] == 1


# ─── Queue B: entities / get_patient_not_found_returns_404 ───

def test_get_patient_not_found(api):
    """PRD §2.6: "the first identifier that does not resolve to an existing resource
    causes the request to be rejected with `ERR_NOT_FOUND` before any deeper validation
    runs."

    Design: Corner/entities/get_patient_not_found_returns_404
    """
    res = api.get_patient(NON_EXISTENT_UUID, FD)
    validate_error(res, "ERR_NOT_FOUND")


# ─── Queue B: entities / create_patient_missing_required_field_returns_422 ───

def test_create_patient_missing_date_of_birth(api):
    """PRD §3.2: "A `FrontDesk` operator registers a patient with a `first_name`, a
    `last_name`, a `date_of_birth`, and an administrative `sex`."

    Design: Corner/entities/create_patient_missing_required_field_returns_422
    """
    res = api.create_patient({"first_name": "No", "last_name": "Dob", "sex": "M"}, FD)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── Queue B: entities / create_provider_default_specialty_applied ───

def test_create_provider_applies_defaults(api):
    """PRD §3.1: "The `specialty`, when supplied, is one of `FAMILY_MEDICINE`,
    `INTERNAL_MEDICINE`, or `PEDIATRICS`, and defaults to `FAMILY_MEDICINE` when
    omitted. The `dea_number`, when supplied, must be exactly 9 characters... and
    defaults to null... The `epcs_enrolled` flag... defaults to false. The
    `panel_capacity`... defaults to 2000."

    Design: Corner/entities/create_provider_default_specialty_applied
    """
    res = api.create_provider({"npi": "2000000001", "full_name": "Default Doc"}, FD)
    provider = validate_success(res, 201)
    assert provider["specialty"] == "FAMILY_MEDICINE"
    assert provider["epcs_enrolled"] is False
    assert provider["panel_capacity"] == 2000
    assert provider["status"] == "ACTIVE"


# ─── Queue B: entities / cpt_code_immutable_no_version_field ───

def test_cpt_code_has_no_version_field(api):
    """PRD §2.4: "A `CptCode` has neither `updated_at` nor `version`, and the system
    does not expose those fields for it."

    Design: Corner/entities/cpt_code_immutable_no_version_field
    """
    cpt = create_cpt_code(category="PROCEDURE", base_fee_cents=3000)
    res = api.get_cpt_code(cpt["id"], BILLER)
    fetched = validate_success(res, 200)
    assert "version" not in fetched, "CptCode must not expose a version field"
    assert "updated_at" not in fetched, "CptCode must not expose an updated_at field"
    assert fetched["code"] == cpt["code"]
    assert "created_at" in fetched


# ─── Queue B: entities / create_provider_invalid_specialty_enum_returns_422 ───

def test_create_provider_invalid_specialty(api):
    """PRD §3.1: "The `specialty`, when supplied, is one of `FAMILY_MEDICINE`,
    `INTERNAL_MEDICINE`, or `PEDIATRICS`."

    Design: Corner/entities/create_provider_invalid_specialty_enum_returns_422
    """
    res = api.create_provider(
        {"npi": "2000000003", "full_name": "Bad Spec", "specialty": "SURGERY"}, FD
    )
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── Queue B: entities / create_visit_unknown_patient_fk_returns_404 ───

def test_create_visit_unknown_patient_fk(api):
    """PRD §2.6: "When a write carries a reference such as `patient_id`, `provider_id`,
    `visit_id`, or `cpt_code` and that reference does not resolve to an existing row, the
    request is rejected with `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/create_visit_unknown_patient_fk_returns_404
    """
    provider = create_provider()
    res = api.create_visit({
        "patient_id": NON_EXISTENT_UUID, "provider_id": provider["id"],
        "visit_type": "CONSULTATION",
        "scheduled_start": "2026-06-01T09:00:00Z", "scheduled_end": "2026-06-01T09:30:00Z",
    }, FD)
    validate_error(res, "ERR_REFERENCE_NOT_FOUND")


# ─── Queue B: validations / vaccination_visit_missing_vaccine_code_returns_422 ───

def test_vaccination_visit_missing_vaccine_code(api):
    """PRD §3.4: "The `vaccine_code` is the immunization product code, such as `FLU` or
    `MMR`; it is required when `visit_type` is `VACCINATION` and is otherwise null."

    Design: Corner/validations/vaccination_visit_missing_vaccine_code_returns_422
    """
    provider = create_provider(specialty="PEDIATRICS")
    patient = create_patient(date_of_birth="2020-01-01", sex="M")
    res = api.create_visit({
        "patient_id": patient["id"], "provider_id": provider["id"],
        "visit_type": "VACCINATION",
        "scheduled_start": "2026-06-01T09:00:00Z", "scheduled_end": "2026-06-01T09:15:00Z",
    }, FD)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── Queue B: validations / code_visit_without_charge_lines_invalid_state ───

def test_code_visit_without_charge_lines(api):
    """PRD §3.4: "Coding the visit advances it from `IN_PROGRESS` to `CODED` and
    requires that the visit have at least one charge line."

    Design: Corner/validations/code_visit_without_charge_lines_invalid_state
    """
    provider, patient, visit = create_visit_in_progress()
    prov_hdr = make_provider_headers(provider["id"])
    res = api.code_visit(visit["id"], prov_hdr)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Queue B: validations / deactivate_patient_with_open_visit_returns_409 ───

def test_deactivate_patient_with_open_visit(api):
    """PRD §3.2: "An attempt to deactivate a patient who still has such an open visit is
    rejected with `ERR_PATIENT_HAS_OPEN_VISITS`."

    Design: Corner/validations/deactivate_patient_with_open_visit_returns_409
    """
    provider = create_provider()
    patient = create_patient()
    create_visit(patient["id"], provider["id"])  # SCHEDULED, non-terminal
    res = api.deactivate_patient(patient["id"], FD)
    validate_error(res, "ERR_PATIENT_HAS_OPEN_VISITS")
