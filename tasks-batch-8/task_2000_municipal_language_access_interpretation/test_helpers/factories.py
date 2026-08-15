"""Payload factories — one per entity, input fields only (PRD §3/§4)."""

DEFAULTS = {
    "DEPARTMENT_NAME": "Test Department",
    "SERVICE_AREA_CODE": "SA-1",
    "ANNUAL_BUDGET_CENTS": 1_000_000,
    "LANGUAGE_CODE": "es",
    "PLAN_YEAR": 2026,
    "PERIOD_START": "2026-01-01T00:00:00Z",
    "PERIOD_END": "2026-07-01T00:00:00Z",
    "LEP_SPEAKER_COUNT": 100,
    "SERVICE_AREA_POPULATION": 10_000,
    "ENCOUNTER_COUNT": 50,
    "TOTAL_ENCOUNTERS": 10_000,
    "DOCUMENT_TITLE": "Test Document",
    "DOCUMENT_TYPE": "FORM",
    "VENDOR_NAME": "Test Vendor",
    "CEILING_CENTS": 500_000,
    "PHONE_PER_MINUTE_CENTS": 50,
    "VIDEO_PER_MINUTE_CENTS": 75,
    "IN_PERSON_PER_MINUTE_CENTS": 100,
    "TRANSLATION_PER_WORD_CENTS": 20,
    "IN_PERSON_TRAVEL_FLAT_CENTS": 2500,
    "TARGET_LANGUAGE_CODE": "es",
    "WORD_COUNT": 100,
    "INTERPRETER_NAME": "Test Interpreter",
    "TIER": "REGISTERED",
    "MODALITY": "PHONE",
    "ENCOUNTER_SETTING": "GENERAL",
    "SCHEDULED_DURATION_MINUTES": 30,
    "COMPLAINT_CATEGORY": "OTHER",
    "COMPLAINT_DESCRIPTION": "test complaint",
}


def create_department_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["DEPARTMENT_NAME"],
        "service_area_code": DEFAULTS["SERVICE_AREA_CODE"],
        "annual_budget_cents": DEFAULTS["ANNUAL_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(department_id, **overrides) -> dict:
    defaults = {
        "department_id": department_id,
        "language_code": DEFAULTS["LANGUAGE_CODE"],
        "plan_year": DEFAULTS["PLAN_YEAR"],
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
        "lep_speaker_count": DEFAULTS["LEP_SPEAKER_COUNT"],
        "service_area_population": DEFAULTS["SERVICE_AREA_POPULATION"],
        "encounter_count": DEFAULTS["ENCOUNTER_COUNT"],
        "total_encounters": DEFAULTS["TOTAL_ENCOUNTERS"],
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(department_id, **overrides) -> dict:
    defaults = {
        "department_id": department_id,
        "title": DEFAULTS["DOCUMENT_TITLE"],
        "document_type": DEFAULTS["DOCUMENT_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_translation_job_payload(document_id, vendor_contract_id, **overrides) -> dict:
    defaults = {
        "document_id": document_id,
        "vendor_contract_id": vendor_contract_id,
        "target_language_code": DEFAULTS["TARGET_LANGUAGE_CODE"],
        "word_count": DEFAULTS["WORD_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_interpreter_payload(vendor_contract_id, **overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["INTERPRETER_NAME"],
        "language_codes": [DEFAULTS["LANGUAGE_CODE"]],
        "modalities": [DEFAULTS["MODALITY"]],
        "tier": DEFAULTS["TIER"],
        "vendor_contract_id": vendor_contract_id,
    }
    defaults.update(overrides)
    return defaults


def create_request_payload(department_id, **overrides) -> dict:
    defaults = {
        "department_id": department_id,
        "language_code": DEFAULTS["LANGUAGE_CODE"],
        "modality": DEFAULTS["MODALITY"],
        "encounter_setting": DEFAULTS["ENCOUNTER_SETTING"],
        "scheduled_duration_minutes": DEFAULTS["SCHEDULED_DURATION_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(department_id, **overrides) -> dict:
    defaults = {
        "department_id": department_id,
        "category": DEFAULTS["COMPLAINT_CATEGORY"],
        "description": DEFAULTS["COMPLAINT_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_contract_payload(**overrides) -> dict:
    defaults = {
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "ceiling_cents": DEFAULTS["CEILING_CENTS"],
        "phone_per_minute_cents": DEFAULTS["PHONE_PER_MINUTE_CENTS"],
        "video_per_minute_cents": DEFAULTS["VIDEO_PER_MINUTE_CENTS"],
        "in_person_per_minute_cents": DEFAULTS["IN_PERSON_PER_MINUTE_CENTS"],
        "translation_per_word_cents": DEFAULTS["TRANSLATION_PER_WORD_CENTS"],
        "in_person_travel_flat_cents": DEFAULTS["IN_PERSON_TRAVEL_FLAT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(**overrides) -> dict:
    defaults = {"plan_year": DEFAULTS["PLAN_YEAR"]}
    defaults.update(overrides)
    return defaults
