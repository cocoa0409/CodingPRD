"""Entity assertions and domain invariant checkers for the Glass & Mirror Shop API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_contractor_account(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert data["tier"] in ("WALK_IN", "BRONZE", "SILVER", "GOLD")
    assert data["status"] in ("ACTIVE", "ON_HOLD", "SUSPENDED")
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["credit_used_cents"], int)
    assert data["credit_used_cents"] >= 0, "credit_used_cents must be non-negative"
    assert data["available_credit_cents"] == data["credit_limit_cents"] - data["credit_used_cents"], \
        "available_credit_cents must equal credit_limit_cents - credit_used_cents"


def assert_quote(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contractor_account_id"])
    assert data["status"] in ("DRAFT", "SENT", "ORDERED")
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1


def assert_line_item(data: dict):
    _assert_common(data)
    assert data["product_type"] in ("SHOWER_ENCLOSURE", "STOREFRONT", "CUSTOM_MIRROR", "TABLETOP")
    assert data["glass_type"] in ("ANNEALED", "TEMPERED", "LAMINATED", "INSULATED")
    assert data["thickness_mm"] in (6, 10, 12)
    assert data["quantity"] >= 1
    assert data["edge_work"] in ("NONE", "POLISHED", "BEVELED")
    assert data["status"] in ("SPEC", "FABRICATING", "FABRICATED", "INSTALLED", "BROKEN")
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert data["line_total_cents"] == data["unit_price_cents"] * data["quantity"], \
        "line_total_cents must equal unit_price_cents * quantity"


def assert_job(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["quote_id"])
    assert is_valid_uuid(data["contractor_account_id"])
    assert data["status"] in ("ACTIVE", "CLOSED", "CANCELLED")
    assert data["fabrication_status"] in ("PENDING", "IN_FABRICATION", "COMPLETE", "REOPENED")
    assert data["install_status"] in ("NOT_READY", "READY", "SCHEDULED", "INSTALLED", "ON_HOLD")


def assert_furnace(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["max_batch_sqft"] > 0
    assert data["reserved_sqft"] >= 0


def assert_tempering_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["furnace_id"])
    assert is_valid_uuid(data["job_id"])
    assert data["status"] in ("SCHEDULED", "DONE", "CANCELLED")
    assert data["total_sqft"] >= 0


def assert_install_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["certified_products"], list)


def assert_install_appointment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["crew_id"])
    assert is_valid_uuid(data["job_id"])
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_claim_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["job_id"])
    assert is_valid_uuid(data["line_item_id"])
    assert data["claim_type"] in ("BREAKAGE", "WARRANTY_DEFECT")
    assert data["status"] in ("FILED", "APPROVED", "REJECTED")


def assert_remake_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["claim_report_id"])
    assert is_valid_uuid(data["job_id"])
    assert is_valid_uuid(data["line_item_id"])
    assert data["status"] in ("PENDING", "COMPLETE")
    assert isinstance(data["remake_cost_cents"], int)
