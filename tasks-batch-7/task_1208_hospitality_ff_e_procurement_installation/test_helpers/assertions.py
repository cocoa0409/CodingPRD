"""Entity assertions and domain invariant checkers (PRD §2.4, §2.10, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

BRAND_PROGRAMS = ["MARQUEE_SELECT", "MARQUEE_LUXE", "INDIE_SOFT"]
BUDGET_CATEGORIES = [
    "FURNITURE", "LIGHTING", "TEXTILES", "DECOR",
    "APPLIANCES", "FREIGHT", "INSTALLATION",
]
PROJECT_STATUSES = ["PLANNING", "PROCUREMENT", "INSTALLATION", "COMPLETED", "CANCELLED"]
PROJECT_POSTURES = ["OPEN", "SEALED", "FROZEN"]
SPEC_STATUSES = ["DRAFT", "SUBMITTED", "BRAND_APPROVED", "BRAND_REJECTED", "LOCKED"]
BID_STATUSES = [
    "SUBMITTED", "SAMPLE_APPROVED", "SAMPLE_REJECTED",
    "AWARDED", "ORDERED", "REJECTED",
]
PO_FULFILLMENT_STATUSES = [
    "ISSUED", "ACKNOWLEDGED", "READY_TO_SHIP", "CONSOLIDATED",
    "DELIVERED", "CLOSED", "CANCELLED",
]
PO_INVOICE_STATUSES = ["UNBILLED", "PARTIALLY_INVOICED", "INVOICED", "PAID"]
PO_LINE_STATUSES = [
    "OPEN", "PARTIALLY_RECEIVED", "FULLY_RECEIVED", "RECONCILED", "CANCELLED",
]
SHIPMENT_STATUSES = [
    "PLANNED", "CONSOLIDATING", "SEALED", "IN_TRANSIT", "RECEIVED", "CANCELLED",
]
RECEIVING_EVENT_STATUSES = ["DRAFT", "POSTED", "REVERSED"]
CLAIM_STATUSES = [
    "OPEN", "SUBMITTED", "DISPUTED", "RESOLVED_CREDIT",
    "RESOLVED_REPLACEMENT", "DENIED", "VOID",
]
CLAIM_TYPES = ["DAMAGE", "SHORTAGE"]
ROOM_TYPES = ["GUEST_KING", "GUEST_DOUBLE", "SUITE", "CORRIDOR", "LOBBY"]
WINDOW_STATUSES = ["PLANNED", "RELEASED", "IN_PROGRESS", "COMPLETE", "CANCELLED"]
TASK_STATUSES = ["SCHEDULED", "COMPLETE", "CANCELLED"]
ATTIC_DIRECTIONS = ["IN", "OUT", "WRITE_OFF"]
CHANGE_ORDER_STATUSES = ["PROPOSED", "APPLIED", "REJECTED"]


def _assert_common_fields(data: dict):
    """PRD §2.4 primary-resource fields."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an int starting at 1"
    )


def assert_ffe_project(data: dict):
    """Validate FFEProject response structure against the PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["hotel_name"], str) and data["hotel_name"]
    assert data["brand_program"] in BRAND_PROGRAMS
    assert isinstance(data["total_budget_cents"], int)
    assert data["total_budget_cents"] > 0
    assert isinstance(data["unallocated_contingency_cents"], int)
    assert 0 <= data["unallocated_contingency_cents"] <= data["total_budget_cents"]
    assert isinstance(data["default_crew_capacity_per_floor_day"], int)
    assert data["default_crew_capacity_per_floor_day"] >= 1
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["actual_spend_cents"], int)
    assert isinstance(data["sunk_fees_cents"], int)
    assert data["procurement_posture"] in PROJECT_POSTURES
    assert data["status"] in PROJECT_STATUSES


def assert_budget_line(data: dict):
    """Validate BudgetLine response structure against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert data["category"] in BUDGET_CATEGORIES
    assert isinstance(data["budgeted_cents"], int) and data["budgeted_cents"] >= 0
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["actual_cents"], int)
    # PRD §2.10 variance identities hold on every read.
    assert data["variance_commitment_cents"] == (
        data["budgeted_cents"] - data["committed_cents"] - data["actual_cents"]
    ), "variance_commitment_cents must equal budgeted - committed - actual"
    assert data["variance_final_cents"] == (
        data["budgeted_cents"] - data["actual_cents"]
    ), "variance_final_cents must equal budgeted - actual"


def assert_spec_item(data: dict):
    """Validate SpecItem response structure against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert data["category"] in BUDGET_CATEGORIES
    assert isinstance(data["description"], str)
    assert isinstance(data["brand_standard_ref"], str)
    assert isinstance(data["quantity_per_room"], int)
    assert data["quantity_per_room"] >= 1
    assert isinstance(data["room_count"], int) and data["room_count"] >= 1
    # PRD §3.2: total_qty is the product of quantity_per_room and room_count.
    assert data["total_qty"] == data["quantity_per_room"] * data["room_count"]
    assert isinstance(data["unit_budget_cents"], int)
    assert data["unit_budget_cents"] >= 1
    assert isinstance(data["required_lead_days"], int)
    assert data["required_lead_days"] >= 0
    assert isinstance(data["is_critical"], bool)
    assert 0 < data["attic_target_pct"] <= 1
    assert isinstance(data["attic_min_qty"], int) and data["attic_min_qty"] >= 0
    assert isinstance(data["attic_max_qty"], int)
    assert data["attic_max_qty"] >= data["attic_min_qty"]
    assert isinstance(data["attic_target_qty"], int)
    assert data["attic_target_qty"] >= 0
    assert data["status"] in SPEC_STATUSES


def assert_vendor_bid(data: dict):
    """Validate VendorBid response structure against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("spec_item_id", ""))
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["unit_price_cents"], int)
    assert data["unit_price_cents"] >= 1
    assert isinstance(data["freight_estimate_cents"], int)
    assert data["freight_estimate_cents"] >= 0
    assert isinstance(data["lead_time_days"], int) and data["lead_time_days"] >= 0
    assert isinstance(data["sample_round"], int) and 1 <= data["sample_round"] <= 2
    assert isinstance(data["evaluated_cost_cents"], int)
    assert data["status"] in BID_STATUSES


def assert_purchase_order(data: dict):
    """Validate PurchaseOrder response structure against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert data.get("shipment_id") is None or is_valid_uuid(data["shipment_id"])
    assert data["fulfillment_status"] in PO_FULFILLMENT_STATUSES
    assert data["invoice_status"] in PO_INVOICE_STATUSES
    assert isinstance(data["total_extended_cents"], int)
    assert isinstance(data["total_cube_m3"], int)


def assert_po_line(data: dict):
    """Validate POLine response structure against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("purchase_order_id", ""))
    assert is_valid_uuid(data.get("spec_item_id", ""))
    assert isinstance(data["quantity_ordered"], int)
    assert data["quantity_ordered"] >= 1
    assert isinstance(data["declared_cube_m3"], int)
    assert data["declared_cube_m3"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    # PRD §3.4: extended_cents is the exact product of quantity and unit price.
    assert data["extended_cents"] == data["quantity_ordered"] * data["unit_price_cents"]
    for pool in (
        "qty_received", "qty_damaged_unresolved", "qty_damaged_credited",
        "qty_short", "qty_installable", "qty_installed", "qty_attic",
    ):
        assert isinstance(data[pool], int) and data[pool] >= 0, (
            f"{pool} must be a non-negative int"
        )
    assert isinstance(data["freight_alloc_provisional_cents"], int)
    assert data.get("freight_alloc_final_cents") is None or isinstance(
        data["freight_alloc_final_cents"], int
    )
    assert isinstance(data["damage_credit_cents"], int)
    assert isinstance(data["actual_landed_cents"], int)
    assert data["status"] in PO_LINE_STATUSES


def assert_po_line_pool_invariant(data: dict):
    """PRD §3.4 pool identity: qty_installable is what remains of qty_received
    after damaged pools, installs, and attic stock."""
    assert_po_line(data)
    assert data["qty_installable"] == (
        data["qty_received"]
        - data["qty_damaged_unresolved"]
        - data["qty_damaged_credited"]
        - data["qty_installed"]
        - data["qty_attic"]
    ), "qty_installable must equal received minus damaged/installed/attic pools"


def assert_shipment(data: dict):
    """Validate Shipment response structure against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data["carrier_name"], str) and data["carrier_name"]
    assert isinstance(data["total_cube_m3"], int) and data["total_cube_m3"] >= 0
    # PRD §2.11: freight_mode and freight_total_cents remain null until sealed.
    assert data.get("freight_mode") in ("FCL", "LTL", None)
    assert data.get("freight_total_cents") is None or isinstance(
        data["freight_total_cents"], int
    )
    assert data["status"] in SHIPMENT_STATUSES
    if data["status"] in ("PLANNED", "CONSOLIDATING"):
        assert data.get("freight_mode") is None
        assert data.get("freight_total_cents") is None


def assert_receiving_event(data: dict):
    """Validate ReceivingEvent response structure against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("shipment_id", ""))
    assert isinstance(data["lines"], list)
    for entry in data["lines"]:
        assert is_valid_uuid(entry.get("po_line_id", ""))
        assert isinstance(entry["qty_received"], int) and entry["qty_received"] >= 1
        assert isinstance(entry["qty_damaged"], int)
        assert 0 <= entry["qty_damaged"] <= entry["qty_received"]
    assert data["status"] in RECEIVING_EVENT_STATUSES


def assert_damage_claim(data: dict):
    """Validate DamageClaim response structure against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("po_line_id", ""))
    assert data["claim_type"] in CLAIM_TYPES
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["claimed_credit_cents"], int)
    assert data["claimed_credit_cents"] >= 0
    assert data.get("approved_credit_cents") is None or isinstance(
        data["approved_credit_cents"], int
    )
    assert data["status"] in CLAIM_STATUSES


def assert_room(data: dict):
    """Validate Room response structure against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data["floor_number"], int) and data["floor_number"] >= 1
    assert isinstance(data["room_number"], str) and data["room_number"]
    assert data["room_type"] in ROOM_TYPES


def assert_installation_window(data: dict):
    """Validate InstallationWindow response structure against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data["floor_number"], int) and data["floor_number"] >= 1
    assert isinstance(data["start_date"], str) and data["start_date"]
    assert isinstance(data["end_date"], str) and data["end_date"]
    assert data["end_date"] > data["start_date"]
    assert isinstance(data["crew_count"], int) and data["crew_count"] >= 1
    assert data["status"] in WINDOW_STATUSES


def assert_installation_task(data: dict):
    """Validate InstallationTask response structure against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("window_id", ""))
    assert is_valid_uuid(data.get("room_id", ""))
    assert is_valid_uuid(data.get("po_line_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in TASK_STATUSES


def assert_attic_stock_movement(data: dict):
    """Validate AtticStockMovement: append-only event carrying only id and
    created_at (PRD §2.4) plus its own event fields."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "append-only movement must not expose updated_at"
    assert "version" not in data, "append-only movement must not expose version"
    assert is_valid_uuid(data.get("po_line_id", ""))
    assert data["direction"] in ATTIC_DIRECTIONS
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["resulting_installable"], int)
    assert data["resulting_installable"] >= 0
    assert isinstance(data["resulting_attic"], int) and data["resulting_attic"] >= 0


def assert_change_order(data: dict):
    """Validate ChangeOrder response structure against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["adjustments"], list) and data["adjustments"]
    for adj in data["adjustments"]:
        assert is_valid_uuid(adj.get("budget_line_id", ""))
        assert isinstance(adj["delta_cents"], int) and adj["delta_cents"] != 0
    assert isinstance(data["proposer_user_id"], str) and data["proposer_user_id"]
    assert data.get("fee_cents") is None or isinstance(data["fee_cents"], int)
    assert data["status"] in CHANGE_ORDER_STATUSES


def assert_project_rollup_invariants(project: dict, budget_lines: list):
    """PRD §2.10: project committed/actual are the sums of the budget lines."""
    assert project["committed_cents"] == sum(
        bl["committed_cents"] for bl in budget_lines
    ), "project committed_cents must equal the sum of budget-line committed_cents"
    assert project["actual_spend_cents"] == sum(
        bl["actual_cents"] for bl in budget_lines
    ), "project actual_spend_cents must equal the sum of budget-line actual_cents"


def assert_funding_envelope_conserved(project: dict, budget_lines: list):
    """The funding envelope E = SUM(budgeted_cents) + unallocated_contingency_cents
    + sunk_fees_cents is invariant under change-order draws and returns."""
    envelope = (
        sum(bl["budgeted_cents"] for bl in budget_lines)
        + project["unallocated_contingency_cents"]
        + project["sunk_fees_cents"]
    )
    assert envelope == project["total_budget_cents"], (
        f"funding envelope {envelope} must equal total_budget_cents "
        f"{project['total_budget_cents']}"
    )
