"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_distillery(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["dsp_permit_number"], str)
    assert isinstance(data["state_code"], str)
    assert data["cbma_rate_tier"] in ("REDUCED", "STANDARD")
    assert isinstance(data["club_release_active"], bool)


def assert_conservation_identity(data: dict):
    """PRD 2.7: total_gauged_pg == production + storage + processing + removed
    + angel_share_losses + bottling_losses + destroyed_losses."""
    lhs = data["total_gauged_pg"]
    rhs = (
        data["production_account_pg"]
        + data["storage_account_pg"]
        + data["processing_account_pg"]
        + data["removed_pg"]
        + data["angel_share_losses_pg"]
        + data["bottling_losses_pg"]
        + data["destroyed_losses_pg"]
    )
    assert abs(lhs - rhs) < 0.05, (
        f"conservation identity violated: total_gauged_pg={lhs}, sum-of-accounts={rhs}"
    )


def assert_bonded_total(data: dict):
    """PRD 2.7: bonded_total_pg == production + storage + processing."""
    expected = (
        data["production_account_pg"]
        + data["storage_account_pg"]
        + data["processing_account_pg"]
    )
    assert abs(data["bonded_total_pg"] - expected) < 0.05, (
        f"bonded_total_pg={data['bonded_total_pg']} != prod+storage+processing={expected}"
    )


def assert_mash_batch(data: dict):
    _common(data)
    assert data["status"] in ("FERMENTING", "DISTILLED", "ARCHIVED", "DUMPED")


def assert_distillation_run(data: dict):
    _common(data)
    assert data["status"] in ("DISTILLING", "GAUGED", "CLOSED")


def assert_barrel(data: dict):
    _common(data)
    assert data["status"] in ("AGING", "EMPTIED", "DESTROYED")


def assert_label_application(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "NEEDS_CORRECTION", "APPROVED")


def assert_bottling_run(data: dict):
    _common(data)
    assert data["status"] in ("SCHEDULED", "BOTTLING", "COMPLETED", "CANCELLED")
    assert data["tax_status"] in ("IN_BOND", "TAX_DETERMINED")
    assert data["inventory_status"] in ("IN_STOCK", "SOLD_OUT")


def assert_case_conservation(data: dict):
    """PRD 3.5/3.6/3.8: available + reserved + shipped + removed == cases_bottled."""
    total = (
        data["cases_available"]
        + data["cases_reserved"]
        + data["cases_shipped"]
        + data["cases_removed"]
    )
    assert total == data["cases_bottled"], (
        f"case conservation violated: {total} != cases_bottled {data['cases_bottled']}"
    )


def assert_tax_removal(data: dict):
    _common(data)
    assert data["status"] == "DETERMINED"
    assert data["removal_reason"] in ("TAXPAID", "TRANSFER_IN_BOND", "EXPORT")


def assert_customer(data: dict):
    _common(data)
    assert data["club_tier"] in ("NONE", "SILVER", "GOLD", "RESERVE")
    assert isinstance(data["age_verified"], bool)


def assert_sales_order(data: dict):
    _common(data)
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["fulfillment_status"] in ("PENDING", "ALLOCATED", "SHIPPED", "CANCELLED")


def assert_tour_booking(data: dict):
    _common(data)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "CANCELLED")
