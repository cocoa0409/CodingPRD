"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_full_common(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive int"


def assert_property(data: dict):
    _assert_full_common(data)
    assert isinstance(data["landlord_name"], str) and data["landlord_name"]
    assert isinstance(data["unit_label"], str)
    assert isinstance(data["full_rent_cents"], int) and data["full_rent_cents"] > 0
    assert 1 <= data["rent_due_day"] <= 28
    assert data["integration_status"] in ("PENDING", "ACTIVE", "SUSPENDED")
    assert data["status"] == data["integration_status"], \
        "status must mirror integration_status"


def assert_renter(data: dict):
    _assert_full_common(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["portion_rent_cents"], int) and data["portion_rent_cents"] > 0
    assert data["status"] in ("PROSPECT", "UNDERWRITING", "ENROLLED", "SUSPENDED")
    assert data["risk_band"] in ("LOW", "MEDIUM", "HIGH", None)
    assert isinstance(data["approved_limit_cents"], int)
    assert isinstance(data["autopay_enabled"], bool)


def assert_application(data: dict):
    _assert_full_common(data)
    assert isinstance(data["renter_id"], str)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DECLINED", "WITHDRAWN")
    assert isinstance(data["risk_score"], int) and 0 <= data["risk_score"] <= 100
    assert data["risk_band"] in ("LOW", "MEDIUM", "HIGH")


def assert_billing_cycle(data: dict):
    _assert_full_common(data)
    assert isinstance(data["renter_id"], str)
    assert data["mode"] in ("SPLIT", "DEFER")
    assert data["status"] in ("SCHEDULED", "REMITTED", "SETTLED", "DELINQUENT",
                              "WRITTEN_OFF", "CANCELLED")
    assert isinstance(data["portion_cents"], int)
    assert isinstance(data["full_rent_cents"], int)
    assert isinstance(data["repaid_amount_cents"], int)
    assert isinstance(data["net_remitted_cents"], int)
    assert isinstance(data["outstanding_cents"], int)


def assert_installment(data: dict):
    _assert_full_common(data)
    assert isinstance(data["cycle_id"], str)
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["amount_cents"], int)
    assert data["kind"] in ("IMMEDIATE", "SPLIT", "DEFERRED")
    assert data["status"] in ("SCHEDULED", "PAID", "FAILED", "WAIVED", "CANCELLED")
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_remittance(data: dict):
    _assert_full_common(data)
    assert isinstance(data["cycle_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("SENT", "REVERSED")


def assert_autopay_mandate(data: dict):
    _assert_full_common(data)
    assert isinstance(data["renter_id"], str)
    assert data["status"] in ("PAUSED", "ACTIVE", "REVOKED")


def assert_delinquency_case(data: dict):
    _assert_full_common(data)
    assert isinstance(data["cycle_id"], str)
    assert data["status"] in ("OPEN", "IN_OUTREACH", "PROMISE_TO_PAY",
                              "BROKEN_PROMISE", "RESOLVED", "CHARGED_OFF")
    assert isinstance(data["accrued_late_fee_cents"], int)
    assert isinstance(data["principal_outstanding_cents"], int)


def assert_append_only(data: dict):
    """Append-only records carry only id + created_at (no version/updated_at)."""
    _assert_common(data)
    assert "version" not in data, "append-only record must not carry version"
    assert "updated_at" not in data, "append-only record must not carry updated_at"


def find_ledger_entry(entries: list, entry_type: str, amount_cents=None):
    """Return the first ledger entry of entry_type (and optional amount), else None."""
    for e in entries:
        if e.get("entry_type") == entry_type:
            if amount_cents is None or e.get("amount_cents") == amount_cents:
                return e
    return None
