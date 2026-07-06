"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_estate(data: dict):
    _assert_common(data)
    assert isinstance(data["decedent_name"], str) and data["decedent_name"]
    assert data["estate_type"] in ("TESTATE", "INTESTATE")
    assert data["status"] in (
        "DRAFT", "OPEN", "INVENTORIED", "ACCOUNTING", "DISTRIBUTING", "CLOSED"
    )
    assert data["supervision_level"] in ("FULL", "LIMITED", "INDEPENDENT")
    assert isinstance(data["gross_estate_value_cents"], int)
    for f in (
        "inventory_total_cents", "marshaled_cash_cents",
        "allowed_claims_total_cents", "residue_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_petition(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "GRANTED", "DENIED")
    assert isinstance(data["will_lodged"], bool)


def assert_representative(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "NOMINATED", "APPOINTED", "SUSPENDED", "DISCHARGED", "REMOVED"
    )
    assert isinstance(data["bond_required"], bool)


def assert_bond(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "APPROVED", "EXONERATED", "FORFEITED")
    assert isinstance(data["penal_amount_cents"], int)
    assert isinstance(data["required_amount_cents"], int)


def assert_beneficiary(data: dict):
    _assert_common(data)
    assert data["relationship"] in (
        "SPOUSE", "CHILD", "HEIR", "DEVISEE", "CREDITOR_RESIDUAL"
    )
    assert isinstance(data["share_bps"], int)
    assert isinstance(data["distributed_cents"], int)


def assert_claim(data: dict):
    _assert_common(data)
    assert data["claim_class"] in ("SECURED", "FUNERAL", "ADMIN", "TAX", "GENERAL")
    assert data["status"] in ("FILED", "ALLOWED", "REJECTED", "BARRED", "PAID")
    assert isinstance(data["claimed_amount_cents"], int)


def assert_asset(data: dict):
    _assert_common(data)
    assert data["asset_class"] in (
        "REAL_PROPERTY", "CASH", "SECURITY", "PERSONAL_PROPERTY"
    )
    assert data["status"] in (
        "LISTED", "APPRAISED", "MARSHALED", "LIQUIDATED", "DISTRIBUTED"
    )
    assert isinstance(data["declared_value_cents"], int)


def assert_distribution(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "APPROVED", "PAID", "RETURNED")
    assert isinstance(data["proposed_amount_cents"], int)


def assert_accounting(data: dict):
    _assert_common(data)
    assert data["report_type"] in ("INVENTORY", "INTERIM", "FINAL")
    assert data["status"] in ("DRAFT", "FILED", "APPROVED", "REJECTED")


def assert_hearing(data: dict):
    _assert_common(data)
    assert data["hearing_type"] in ("PETITION", "ACCOUNTING", "REMOVAL")
    assert data["status"] in ("SCHEDULED", "HELD", "VACATED")
