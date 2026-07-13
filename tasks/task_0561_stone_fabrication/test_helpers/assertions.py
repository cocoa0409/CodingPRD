"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_snapshot(data: dict):
    """Immutable snapshot entities carry only id + created_at (no updated_at / version)."""
    _assert_common(data)
    assert "updated_at" not in data, "snapshot entity must not expose updated_at"
    assert "version" not in data, "snapshot entity must not expose version"


def assert_project(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"INTAKE", "IN_PRODUCTION", "ON_HOLD", "INSTALLED", "CLOSED"}
    assert data["payment_status"] in {"UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL"}
    assert isinstance(data["amount_paid_cents"], int)


def assert_quote(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"ACTIVE", "SUPERSEDED"}
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["quote_total_cents"], int)


def assert_template(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"DRAFT", "MEASURED", "APPROVED", "SUPERSEDED"}


def assert_slab(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"IN_STOCK", "RESERVED", "CONSUMED"}


def assert_fabrication_order(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"SCHEDULED", "CUTTING", "RECUTTING", "QC_PASSED", "COMPLETE", "CANCELLED"}


def assert_install_job(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"SCHEDULED", "IN_PROGRESS", "DONE"}


def assert_payment(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"CAPTURED", "REFUNDED"}


def assert_change_order(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"DRAFT", "APPLIED"}


def assert_warranty_claim(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"SUBMITTED", "RESOLVED", "REJECTED"}


def assert_cutout(data: dict):
    _assert_snapshot(data)


def assert_remnant(data: dict):
    _assert_snapshot(data)


def assert_slab_area_conserved(slab: dict, tolerance: float = 0.005):
    """Invariant (PRD §2.7): reserved_sqft + remaining_sqft always equals nominal_sqft."""
    total = slab["reserved_sqft"] + slab["remaining_sqft"]
    assert abs(total - slab["nominal_sqft"]) <= tolerance, (
        f"reserved+remaining ({total}) must equal nominal ({slab['nominal_sqft']})"
    )
