"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_taxpayer(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["entity_type"] in ["SOLE_PROP", "LLC", "CORP", "PARTNERSHIP"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["filing_frequency"] in ["MONTHLY", "QUARTERLY", "ANNUAL"]
    assert data["account_status"] in ["PENDING", "ACTIVE", "SUSPENDED"]
    assert data["nexus_status"] in ["NONE", "ESTABLISHED"]
    assert isinstance(data["account_balance_cents"], int)


def assert_jurisdiction(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str)
    assert isinstance(data["rate_bps"], int) and data["rate_bps"] >= 0
    assert isinstance(data["active"], bool)


def assert_return(data: dict):
    _assert_common(data)
    assert isinstance(data["taxpayer_id"], str)
    assert isinstance(data["period_key"], str)
    assert data["status"] in ["DRAFT", "FILED", "AMENDING", "ASSESSED"]
    assert isinstance(data["lines"], list)


def assert_certificate(data: dict):
    _assert_common(data)
    assert isinstance(data["taxpayer_id"], str)
    assert data["exemption_type"] in ["RESALE", "GOVERNMENT", "NONPROFIT", "MANUFACTURING"]
    assert isinstance(data["certificate_number"], str)


def assert_remittance(data: dict):
    _assert_common(data)
    assert isinstance(data["taxpayer_id"], str)
    assert data["remittance_type"] in ["PAYMENT", "PREPAYMENT"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["applied_amount_cents"], int)
    assert isinstance(data["unapplied_amount_cents"], int)
    assert_remittance_partition(data)


def assert_remittance_partition(data: dict):
    """Conservation invariant: applied + unapplied == amount, always (PRD §3.4)."""
    assert data["applied_amount_cents"] + data["unapplied_amount_cents"] == data["amount_cents"], (
        f"partition broken: {data['applied_amount_cents']} + "
        f"{data['unapplied_amount_cents']} != {data['amount_cents']}"
    )


def assert_audit(data: dict):
    _assert_common(data)
    assert isinstance(data["taxpayer_id"], str)
    assert data["audit_type"] in ["FIELD_AUDIT", "NEXUS_DISCOVERY"]
    assert data["status"] in ["OPEN", "CLOSED_ASSESSED", "CLOSED_NO_CHANGE"]


def assert_assessment(data: dict):
    _assert_common(data)
    assert isinstance(data["taxpayer_id"], str)
    assert data["assessment_type"] in ["AUDIT_DEFICIENCY", "LATE_FILING"]
    assert isinstance(data["tax_deficiency_cents"], int) and data["tax_deficiency_cents"] > 0
    assert isinstance(data["penalty_cents"], int)
    assert isinstance(data["interest_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert data["status"] in ["ISSUED", "ABATED", "AFFIRMED"]
    assert_assessment_total(data)


def assert_assessment_total(data: dict):
    """total_due_cents == tax_deficiency + penalty + interest (PRD §3.5)."""
    assert data["total_due_cents"] == (
        data["tax_deficiency_cents"] + data["penalty_cents"] + data["interest_cents"]
    ), "total_due_cents must equal base + penalty + interest"


def assert_appeal(data: dict):
    _assert_common(data)
    assert isinstance(data["assessment_id"], str)
    assert data["status"] in ["SUBMITTED", "INFO_REQUESTED", "ALLOWED", "DENIED"]


def assert_refund_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["taxpayer_id"], str)
    assert isinstance(data["return_id"], str)
    assert isinstance(data["claim_amount_cents"], int) and data["claim_amount_cents"] > 0
    assert data["reason"] in ["TAXPAYER_ERROR", "AUDIT_ADJUSTMENT"]
    assert data["status"] in ["OPEN", "APPROVED", "DENIED", "VOIDED", "SUPERSEDED"]
