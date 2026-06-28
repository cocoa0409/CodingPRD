"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response shape against the PRD contract using
the framework's generic format checkers. Money is integer cents; areas carry
two decimals (PRD §2.5).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_VARIANTS = ["STANDARD", "PET", "PLAYGROUND", "PUTTING_GREEN"]


def _common_full(data: dict):
    """id + created_at + updated_at + version present (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def _common_min(data: dict):
    """id + created_at only — for TurfProduct, InfillProduct, Payment (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only entity must not carry updated_at"
    assert "version" not in data, "append-only entity must not carry version"


def assert_project(data: dict):
    _common_full(data)
    assert data["workflow_status"] in [
        "DRAFT", "MEASURED", "DESIGNED", "QUOTED", "DEPOSIT_PAID",
        "SCHEDULED", "INSTALLED", "CLOSED", "CANCELLED",
    ]
    assert data["finance_status"] in [
        "UNBILLED", "DEPOSIT_DUE", "DEPOSIT_SETTLED",
        "BALANCE_DUE", "PAID_IN_FULL", "REFUNDED",
    ]
    assert isinstance(data["customer_id"], str) and data["customer_id"]
    assert isinstance(data["site_address"], str)
    assert data["variant"] is None or data["variant"] in _VARIANTS
    assert isinstance(data["billable_area_sqft"], (int, float))
    for f in (
        "contract_total_cents", "deposit_paid_cents", "balance_paid_cents",
        "amount_refunded_cents", "outstanding_balance_cents", "open_callback_count",
    ):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["outstanding_balance_cents"] >= 0, "display outstanding is floored at 0"
    assert data["open_callback_count"] >= 0


def assert_customer(data: dict):
    _common_full(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]


def assert_site_measure(data: dict):
    _common_full(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert data["gross_area_sqft"] > 0
    assert data["obstruction_area_sqft"] >= 0
    assert data["longest_run_ft"] > 0
    assert data["slope_pct"] >= 0
    assert isinstance(data["soil_drains_freely"], bool)
    assert data["status"] in ["RECORDED", "SUPERSEDED"]


def assert_turf_product(data: dict):
    _common_min(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str)
    assert data["pile_height_mm"] > 0
    assert data["price_per_sqft_cents"] > 0
    assert data["roll_width_ft"] > 0
    for flag in ("pet_approved", "playground_rated", "putting_rated", "active"):
        assert isinstance(data[flag], bool)


def assert_infill_product(data: dict):
    _common_min(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["material"] in ["SILICA", "ACRYLIC_COATED", "ZEOLITE", "RUBBER", "CORK"]
    assert data["price_per_sqft_cents"] > 0
    assert data["coverage_lbs_per_sqft"] > 0
    for flag in ("antimicrobial", "nonabrasive", "active"):
        assert isinstance(data[flag], bool)


def assert_design_layout(data: dict):
    _common_full(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert data["variant"] in _VARIANTS
    assert data["status"] in ["DRAFT", "ACCEPTED", "REJECTED"]
    assert isinstance(data["waste_factor_pct"], (int, float))
    assert isinstance(data["net_area_sqft"], (int, float))
    assert data["net_area_sqft"] > 0


def assert_base_prep_scope(data: dict):
    _common_full(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert data["drainage_tier"] in ["NONE", "FRENCH_DRAIN", "DRAINAGE_PANEL"]
    assert isinstance(data["excavation_cost_cents"], int)
    assert isinstance(data["drainage_cost_cents"], int)
    assert data["status"] in ["DRAFT", "FINALIZED"]
    assert data["base_depth_in"] > 0


def assert_quote(data: dict):
    _common_full(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert data["status"] in ["DRAFT", "SENT", "ACCEPTED", "REVISED", "EXPIRED", "VOID"]
    for f in (
        "material_subtotal_cents", "base_prep_subtotal_cents", "variant_surcharge_cents",
        "discount_cents", "subtotal_cents", "total_cents", "deposit_amount_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["variant_kind"] in _VARIANTS


def assert_crew(data: dict):
    _common_full(data)
    assert isinstance(data["name"], str)
    assert data["daily_capacity_sqft"] > 0
    for flag in ("certified_putting", "certified_playground", "active"):
        assert isinstance(data[flag], bool)


def assert_install_job(data: dict):
    _common_full(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["crew_id"], str) and data["crew_id"]
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED"]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])


def assert_warranty_plan(data: dict):
    _common_full(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert data["tier"] in ["BASIC", "PLUS", "PREMIUM"]
    assert isinstance(data["coverage_months"], int)
    assert isinstance(data["maintenance_visits_per_year"], int)
    assert data["status"] in ["PENDING", "ACTIVE", "EXPIRED", "VOID"]


def assert_callback(data: dict):
    _common_full(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert data["reason"] in [
        "SEAM_LIFT", "INFILL_MIGRATION", "DRAINAGE", "WRINKLE", "PET_ODOR", "OTHER",
    ]
    assert isinstance(data["billable"], bool)
    assert isinstance(data["charge_cents"], int)
    assert data["status"] in ["OPEN", "IN_PROGRESS", "RESOLVED", "CANCELLED"]


def assert_payment(data: dict):
    _common_min(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert data["kind"] in ["DEPOSIT", "BALANCE", "REFUND"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ["PENDING", "SETTLED", "FAILED"]
