"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    """PRD §2.4 — every persisted resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_client(data: dict):
    _assert_common_fields(data, "Client")
    assert isinstance(data["name"], str) and 0 < len(data["name"]) <= 120
    assert data["industry"] in ["RETAIL", "FINANCE", "CPG", "TECH", "AUTO"]
    assert isinstance(data["billing_email"], str) and len(data["billing_email"]) > 0
    assert data["status"] in ["ACTIVE", "CREDIT_HOLD"]


def assert_rate_card(data: dict):
    _assert_common_fields(data, "RateCard")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    for field in (
        "rate_junior_cents_per_hour",
        "rate_senior_cents_per_hour",
        "rate_director_cents_per_hour",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be a non-negative integer"


def assert_staff_member(data: dict):
    _assert_common_fields(data, "StaffMember")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["grade"] in ["JUNIOR", "SENIOR", "DIRECTOR"]
    assert isinstance(data["standard_daily_capacity_minutes"], int)
    assert 1 <= data["standard_daily_capacity_minutes"] <= 1440
    assert isinstance(data["cost_rate_cents_per_hour"], int)
    assert data["cost_rate_cents_per_hour"] >= 0


def assert_media_placement(data: dict):
    _assert_common_fields(data, "MediaPlacement")
    assert isinstance(data["publisher_name"], str) and len(data["publisher_name"]) > 0
    assert data["channel"] in ["DISPLAY", "VIDEO", "SOCIAL", "OOH", "PRINT"]
    assert isinstance(data["min_dark_days"], int) and 0 <= data["min_dark_days"] <= 30


def assert_retainer(data: dict):
    _assert_common_fields(data, "Retainer")
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["funded_cents"], int) and data["funded_cents"] >= 0
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 0
    assert data["status"] in ["ACTIVE", "DEPLETED"]
    # PRD §3.1 — the retainer's status follows its balance mechanically.
    if data["balance_cents"] > 0:
        assert data["status"] == "ACTIVE", "a retainer with balance > 0 must be ACTIVE"
    else:
        assert data["status"] == "DEPLETED", "a retainer whose balance reached 0 must be DEPLETED"


def assert_sow(data: dict):
    _assert_common_fields(data, "SOW")
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["rate_card_id"])
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["labor_cap_cents"], int) and data["labor_cap_cents"] >= 0
    assert 0 <= data["markup_pct"] <= 1
    assert data["status"] in ["DRAFT", "COUNTERSIGNED", "EXPIRED"]
    assert isinstance(data["consumed_labor_cents"], int) and data["consumed_labor_cents"] >= 0
    if data["status"] == "DRAFT":
        # PRD §3.2 — a new SOW has all four of its pinned columns set to null.
        assert data["pinned_rate_card_version"] is None
        assert data["pinned_rate_junior_cents_per_hour"] is None
        assert data["pinned_rate_senior_cents_per_hour"] is None
        assert data["pinned_rate_director_cents_per_hour"] is None


def assert_campaign(data: dict):
    _assert_common_fields(data, "Campaign")
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["sow_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["brief_summary"], str) and 0 < len(data["brief_summary"]) <= 2000
    assert data["objective"] in ["AWARENESS", "CONSIDERATION", "CONVERSION"]
    assert data["status"] in ["DRAFT", "IN_FLIGHT", "ON_HOLD", "WRAP_UP", "CLOSED"]


def assert_deliverable(data: dict):
    _assert_common_fields(data, "Deliverable")
    assert is_valid_uuid(data["campaign_id"])
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["current_asset_version"], int) and data["current_asset_version"] >= 0
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert data["status"] in ["DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED"]


def assert_time_entry(data: dict):
    _assert_common_fields(data, "TimeEntry")
    assert is_valid_uuid(data["campaign_id"])
    assert is_valid_uuid(data["staff_id"])
    assert isinstance(data["work_date"], str) and len(data["work_date"]) == 10
    assert isinstance(data["minutes"], int) and data["minutes"] >= 1
    assert isinstance(data["billable"], bool)
    assert data["status"] in ["SUBMITTED", "APPROVED", "BILLED"]
    for field in (
        "pinned_rate_cents_per_hour",
        "estimated_amount_cents",
        "regular_minutes",
        "overtime_minutes",
        "billable_amount_cents",
        "internal_cost_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be a non-negative integer"
    if not data["billable"]:
        # PRD §3.5 — if billable is false the chargeable columns are all 0.
        assert data["pinned_rate_cents_per_hour"] == 0
        assert data["estimated_amount_cents"] == 0
        assert data["billable_amount_cents"] == 0


def assert_vendor_cost(data: dict):
    _assert_common_fields(data, "VendorCost")
    assert is_valid_uuid(data["campaign_id"])
    assert isinstance(data["vendor_name"], str) and len(data["vendor_name"]) > 0
    assert data["vendor_type"] in ["FREELANCER", "PRODUCTION", "PRINT", "OTHER"]
    assert isinstance(data["estimated_amount_cents"], int) and data["estimated_amount_cents"] >= 0
    assert data["status"] in ["SUBMITTED", "APPROVED", "BILLED"]


def assert_media_plan(data: dict):
    _assert_common_fields(data, "MediaPlan")
    assert is_valid_uuid(data["campaign_id"])
    assert isinstance(data["approved_budget_cents"], int) and data["approved_budget_cents"] >= 0
    assert isinstance(data["allowed_channels"], list) and len(data["allowed_channels"]) > 0
    for channel in data["allowed_channels"]:
        assert channel in ["DISPLAY", "VIDEO", "SOCIAL", "OOH", "PRINT"]
    assert isinstance(data["uncommitted_cents"], int) and data["uncommitted_cents"] >= 0
    assert data["status"] in ["DRAFT", "APPROVED", "LOCKED"]


def assert_insertion_order(data: dict):
    _assert_common_fields(data, "InsertionOrder")
    assert is_valid_uuid(data["media_plan_id"])
    assert is_valid_uuid(data["placement_id"])
    assert isinstance(data["gross_cents"], int) and data["gross_cents"] >= 1
    assert isinstance(data["delivered_impressions"], int) and data["delivered_impressions"] >= 0
    assert isinstance(data["delivered_spend_cents"], int) and data["delivered_spend_cents"] >= 0
    assert data["status"] in ["RESERVED", "PLACED", "DELIVERED", "CANCELLED"]


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["campaign_id"])
    assert is_valid_uuid(data["retainer_id"])
    assert data["billing_mode"] in ["PROVISIONAL", "FINAL"]
    assert data["approval_status"] in ["DRAFT", "ISSUED", "VOID"]
    assert data["payment_status"] in ["UNPAID", "PARTIALLY_PAID", "PAID"]
    for field in (
        "line_count",
        "labor_cents",
        "vendor_base_cents",
        "vendor_marked_up_cents",
        "media_gross_cents",
        "media_commission_cents",
        "subtotal_cents",
        "discount_cents",
        "admin_fee_cents",
        "total_cents",
        "retainer_applied_cents",
        "cash_due_cents",
        "amount_paid_cents",
    ):
        assert isinstance(data[field], int), f"Invoice.{field} must be an integer number of cents"
    assert_invoice_money_invariants(data)


def assert_invoice_money_invariants(data: dict):
    """PRD §3.8 — the five-step total, and the split of the total into retainer + cash."""
    assert (
        data["subtotal_cents"]
        == data["labor_cents"] + data["vendor_marked_up_cents"] + data["media_commission_cents"]
    ), "subtotal_cents must be labor + marked-up vendor + media commission"
    assert (
        data["total_cents"]
        == data["subtotal_cents"] - data["discount_cents"] + data["admin_fee_cents"]
    ), "total_cents must be subtotal less discount plus admin fee"
    assert data["retainer_applied_cents"] + data["cash_due_cents"] in (0, data["total_cents"]), (
        "once issued, retainer_applied_cents + cash_due_cents must equal total_cents"
    )
    assert data["amount_paid_cents"] <= data["cash_due_cents"], (
        "amount_paid_cents must never exceed cash_due_cents"
    )


def assert_retainer_cash_conserved(retainer: dict, invoices: list):
    """PRD §2.9 — funded_cents == balance_cents + sum of retainer_applied_cents over ISSUED invoices."""
    applied = sum(
        inv["retainer_applied_cents"]
        for inv in invoices
        if inv["retainer_id"] == retainer["id"] and inv["approval_status"] == "ISSUED"
    )
    assert retainer["funded_cents"] == retainer["balance_cents"] + applied, (
        f"Retainer cash drift: funded {retainer['funded_cents']} != "
        f"balance {retainer['balance_cents']} + applied {applied}"
    )


def assert_media_budget_conserved(media_plan: dict, insertion_orders: list):
    """PRD §2.9 — approved_budget_cents == uncommitted_cents + gross of RESERVED/PLACED/DELIVERED orders."""
    committed = sum(
        io["gross_cents"]
        for io in insertion_orders
        if io["media_plan_id"] == media_plan["id"]
        and io["status"] in ("RESERVED", "PLACED", "DELIVERED")
    )
    assert media_plan["approved_budget_cents"] == media_plan["uncommitted_cents"] + committed, (
        f"Media budget drift: approved {media_plan['approved_budget_cents']} != "
        f"uncommitted {media_plan['uncommitted_cents']} + committed {committed}"
    )
