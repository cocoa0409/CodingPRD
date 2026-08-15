"""Payload factories — one per creatable entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_seq = itertools.count(1)


def _next(prefix: str) -> str:
    return f"{prefix}-{next(_seq):04d}"


def create_insured_person_payload(**overrides) -> dict:
    defaults = {
        "full_name": TEST_DEFAULTS["FULL_NAME"],
        "date_of_birth": TEST_DEFAULTS["DATE_OF_BIRTH"],
        "tobacco_user": False,
        "gender": TEST_DEFAULTS["GENDER"],
    }
    defaults.update(overrides)
    return defaults


def create_product_template_payload(**overrides) -> dict:
    defaults = {
        "product_code": _next("WL-NP"),
        "product_type": "WHOLE_LIFE_NON_PARTICIPATING",
        "participating": False,
        "allows_policy_loans": True,
        "min_face_amount_cents": TEST_DEFAULTS["MIN_FACE_CENTS"],
        "max_face_amount_cents": TEST_DEFAULTS["MAX_FACE_CENTS"],
        "base_monthly_premium_rate_per_thousand_cents":
            TEST_DEFAULTS["BASE_RATE_PER_THOUSAND_CENTS"],
        "coi_rate_table": [],
        "surrender_charge_schedule": [],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(insured_person_id, product_template_id, **overrides) -> dict:
    defaults = {
        "insured_person_id": insured_person_id,
        "product_template_id": product_template_id,
        "requested_face_amount_cents": TEST_DEFAULTS["FACE_AMOUNT_CENTS"],
        "premium_mode": TEST_DEFAULTS["PREMIUM_MODE"],
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(requested_amount_cents=1_000_000, **overrides) -> dict:
    defaults = {"requested_amount_cents": requested_amount_cents}
    defaults.update(overrides)
    return defaults


def create_rider_payload(rider_type="ACCIDENTAL_DEATH_BENEFIT",
                         rider_face_amount_cents=1_000_000, **overrides) -> dict:
    defaults = {
        "rider_type": rider_type,
        "rider_face_amount_cents": rider_face_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_conversion_request_payload(target_product_template_id,
                                      requested_face_amount_cents=5_000_000,
                                      **overrides) -> dict:
    defaults = {
        "target_product_template_id": target_product_template_id,
        "requested_face_amount_cents": requested_face_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_dividend_declaration_payload(policy_year=1, declared_amount_cents=100_000,
                                        **overrides) -> dict:
    defaults = {
        "policy_year": policy_year,
        "declared_amount_cents": declared_amount_cents,
    }
    defaults.update(overrides)
    return defaults
