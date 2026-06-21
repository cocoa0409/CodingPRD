"""Payload factories — one per entity, input fields only.

Only fields the client supplies (source: input) are included. System and
computed fields (status, premiums, result, cash values, version, timestamps)
are never sent.
"""

DEFAULTS = {
    "PRODUCT_BASE_RATE": 250,
    "PRODUCT_MAX_FACE": 100_000_000,
    "PRODUCT_ACCRUAL_BPS": 300,
    "FACE_AMOUNT": 50_000_000,
    "STANDARD_PREMIUM": 125000,
}

_product_seq = [0]
_email_seq = [0]
_license_seq = [0]


def unique_code(prefix="PROD") -> str:
    _product_seq[0] += 1
    return f"{prefix}-{_product_seq[0]}"


def unique_email(prefix="person") -> str:
    _email_seq[0] += 1
    return f"{prefix}{_email_seq[0]}@example.com"


def unique_license(prefix="LIC") -> str:
    _license_seq[0] += 1
    return f"{prefix}-{_license_seq[0]}"


def create_product_payload(**overrides) -> dict:
    """Product: code, base_annual_rate_per_thousand_cents, max_face_amount_cents,
    cash_value_accrual_rate_bps, and optional contestability_months / grace_period_days /
    max_loan_to_cash_value_pct / exam_validity_days."""
    defaults = {
        "code": unique_code(),
        "base_annual_rate_per_thousand_cents": DEFAULTS["PRODUCT_BASE_RATE"],
        "max_face_amount_cents": DEFAULTS["PRODUCT_MAX_FACE"],
        "cash_value_accrual_rate_bps": DEFAULTS["PRODUCT_ACCRUAL_BPS"],
        "contestability_months": 24,
        "grace_period_days": 31,
        "max_loan_to_cash_value_pct": 90,
        "exam_validity_days": 180,
    }
    defaults.update(overrides)
    return defaults


def create_underwriter_payload(**overrides) -> dict:
    """Underwriter: name, license_id."""
    defaults = {
        "name": "Test Underwriter",
        "license_id": unique_license(),
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    """Applicant: full_name, date_of_birth, sex, tobacco_use, email."""
    defaults = {
        "full_name": "Test Applicant",
        "date_of_birth": "1986-06-06",
        "sex": "MALE",
        "tobacco_use": False,
        "email": unique_email(),
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id, product_id, **overrides) -> dict:
    """Application: applicant_id, product_id, requested_face_amount_cents."""
    defaults = {
        "applicant_id": applicant_id,
        "product_id": product_id,
        "requested_face_amount_cents": DEFAULTS["FACE_AMOUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_paramed_exam_payload(**overrides) -> dict:
    """ParamedExam: height_inches, weight_pounds, systolic_bp, exam_date."""
    defaults = {
        "height_inches": 70,
        "weight_pounds": 160,
        "systolic_bp": 120,
        "exam_date": "2026-05-01",
    }
    defaults.update(overrides)
    return defaults


def create_mib_check_payload(**overrides) -> dict:
    """MIBCheck: mib_hit, rx_flag_count."""
    defaults = {
        "mib_hit": False,
        "rx_flag_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_beneficiary_payload(**overrides) -> dict:
    """Beneficiary: full_name, designation, share_pct."""
    defaults = {
        "full_name": "Test Beneficiary",
        "designation": "PRIMARY",
        "share_pct": 100,
    }
    defaults.update(overrides)
    return defaults


def create_premium_payment_payload(amount_cents, **overrides) -> dict:
    """PremiumPayment: amount_cents, optional coverage_period_start."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_policy_loan_payload(principal_cents, expected_policy_version, **overrides) -> dict:
    """PolicyLoan: principal_cents, expected_policy_version (OCC guard)."""
    defaults = {
        "principal_cents": principal_cents,
        "expected_policy_version": expected_policy_version,
    }
    defaults.update(overrides)
    return defaults
