"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_procedure(data: dict):
    _assert_common(data)
    assert data["code_system"] in ("CPT", "HCPCS", "DRG")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["setting"] in ("INPATIENT", "OUTPATIENT")
    assert isinstance(data["is_shoppable"], bool)
    assert isinstance(data["requires_prior_auth"], bool)
    assert isinstance(data["gross_charge_cents"], int) and data["gross_charge_cents"] >= 0


def assert_payer_contract(data: dict):
    _assert_common(data)
    assert data["payer_type"] in ("COMMERCIAL", "MEDICARE", "MEDICAID")
    assert data["methodology"] in ("FEE_SCHEDULE", "PERCENT_OF_CHARGE", "CASE_RATE")
    assert data["status"] in ("DRAFT", "ACTIVE")


def assert_negotiated_rate(data: dict):
    _assert_common(data)
    assert data["rate_type"] in ("FLAT", "PERCENT")
    assert isinstance(data["superseded"], bool)


def assert_benefit_plan(data: dict):
    _assert_common(data)
    assert data["individual_oop_max_cents"] >= data["individual_deductible_cents"]
    assert 0 <= data["coinsurance_rate"] <= 1


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["deductible_met_cents"], int)
    assert isinstance(data["oop_met_cents"], int)
    assert data["deductible_met_cents"] >= 0
    assert data["oop_met_cents"] >= 0


def assert_estimate(data: dict):
    _assert_common(data)
    assert data["estimate_type"] in ("GFE_INSURED", "GFE_SELFPAY")
    assert data["status"] in ("DRAFT", "ISSUED", "ACCEPTED", "DISPUTED", "SETTLED", "VOID")


def assert_estimate_priced(data: dict):
    """Invariant: a priced estimate conserves the allowed amount across the
    patient/plan split (allowed == patient_responsibility + plan_paid)."""
    assert_estimate(data)
    allowed = data["allowed_amount_cents"]
    pr = data["patient_responsibility_cents"]
    pp = data["plan_paid_cents"]
    assert allowed is not None and pr is not None and pp is not None
    assert allowed == pr + pp, \
        f"allowed {allowed} must equal patient_responsibility {pr} + plan_paid {pp}"
    assert pr >= 0 and pp >= 0


def assert_prior_authorization(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "CONSUMED")


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "RESOLVED_UPHELD", "RESOLVED_ADJUSTED")
