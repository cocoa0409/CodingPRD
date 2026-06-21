"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD §3:
- Applicant: full_name, birth_date, declared_state_code required; bonus_points optional (default 0).
- ResidencyVerification: applicant_id, proof_type, proof_state_code, continuous_months required.
- EducationCertificate: applicant_id, course_code, completion_date required.
- LicenseProduct: sku, product_kind, base_fee_cents required; species_season_id, requires_education,
  residency_restriction, min_age_years optional.
- SpeciesSeason: species, season_open, season_close, bag_limit required; draw_required optional.
- DrawPool: species_season_id, license_product_id, quota, entry_deadline required; scoring_model optional.
- DrawApplication: draw_pool_id, applicant_id required.
- License: applicant_id, license_product_id required.
- HarvestReport: license_id, harvest_datetime, quantity required.
- Replacement: original_license_id, reason required.
"""


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Applicant",
        "birth_date": "1980-01-01",
        "declared_state_code": "MT",
    }
    defaults.update(overrides)
    return defaults


def create_residency_verification_payload(applicant_id: str, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "proof_type": "DRIVERS_LICENSE",
        "proof_state_code": "MT",
        "continuous_months": 24,
    }
    defaults.update(overrides)
    return defaults


def create_education_certificate_payload(applicant_id: str, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "course_code": "HE-101",
        "completion_date": "2025-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_license_product_payload(**overrides) -> dict:
    defaults = {
        "sku": "PROD-1",
        "product_kind": "STAMP",
        "base_fee_cents": 4500,
        "residency_restriction": "ANY",
    }
    defaults.update(overrides)
    return defaults


def create_species_season_payload(**overrides) -> dict:
    defaults = {
        "species": "ELK",
        "season_open": "2026-09-01T00:00:00Z",
        "season_close": "2026-10-01T00:00:00Z",
        "bag_limit": 1,
    }
    defaults.update(overrides)
    return defaults


def create_draw_pool_payload(species_season_id: str, license_product_id: str, **overrides) -> dict:
    defaults = {
        "species_season_id": species_season_id,
        "license_product_id": license_product_id,
        "quota": 1,
        "entry_deadline": "2026-03-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_draw_application_payload(draw_pool_id: str, applicant_id: str, **overrides) -> dict:
    defaults = {
        "draw_pool_id": draw_pool_id,
        "applicant_id": applicant_id,
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(applicant_id: str, license_product_id: str, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "license_product_id": license_product_id,
    }
    defaults.update(overrides)
    return defaults


def create_harvest_report_payload(license_id: str, **overrides) -> dict:
    defaults = {
        "license_id": license_id,
        "harvest_datetime": "2026-09-15T08:00:00Z",
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_replacement_payload(original_license_id: str, **overrides) -> dict:
    defaults = {
        "original_license_id": original_license_id,
        "reason": "LOST",
    }
    defaults.update(overrides)
    return defaults
