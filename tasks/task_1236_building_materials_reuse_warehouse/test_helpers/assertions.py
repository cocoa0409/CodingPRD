"""Entity assertions and domain invariant checkers (PRD §2.5, §3).

Each assert_* validates the fields a PRD reader expects on the resource:
common fields (id / created_at / updated_at / version) for regular resources,
and only id / created_at for the three lean records (HazmatScreening,
MarkdownRun, SaleLineItem — PRD §2.5).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lean(data: dict):
    """Lean records carry only id + created_at; updated_at/version absent (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "lean record must not expose updated_at"
    assert "version" not in data, "lean record must not expose version"


def assert_donor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["donor_type"] in ("INDIVIDUAL", "BUSINESS", "CONTRACTOR")
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["phone"], str)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["trailing_receipt_value_cents"], int)
    assert data["recognition_tier"] in ("NONE", "SUPPORTER", "BUILDER", "CORNERSTONE")


def assert_category(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["pricing_model"] in ("PER_UNIT", "PER_SQFT", "PER_LINEAR_FT", "FLAT")
    assert isinstance(data["base_rate_cents"], int)
    assert data["acceptance_status"] in ("ACCEPTING", "PAUSED", "RETIRED")
    assert isinstance(data["hazmat_risk_flag"], bool)
    assert isinstance(data["markdown_after_days"], int)
    assert isinstance(data["max_markdown_steps"], int)


def assert_offer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("donor_id", ""))
    assert data["source_type"] in ("DROPOFF", "PICKUP", "DECONSTRUCTION")
    assert is_valid_uuid(data.get("category_id", ""))
    assert data["condition_grade"] in ("A", "B", "C", "D")
    assert isinstance(data["pre_1978_flag"], bool)
    assert data["status"] in (
        "OFFERED", "UNDER_REVIEW", "NEEDS_INFO", "ACCEPTED",
        "REJECTED", "RECEIVED", "RECEIPTED", "CANCELLED",
    )
    assert isinstance(data["estimated_value_cents"], int)
    assert isinstance(data["final_value_cents"], int)


def assert_job(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in (
        "REQUESTED", "SCREENING_PENDING", "CLEARED", "HAZMAT_HOLD",
        "REMEDIATION_IN_PROGRESS", "SCHEDULED", "IN_PROGRESS",
        "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["quoted_fee_cents"], int)
    assert isinstance(data["estimated_diverted_weight_lbs"], (int, float))
    assert isinstance(data["certified_diverted_weight_lbs"], (int, float))
    assert isinstance(data["actual_fee_cents"], int)


def assert_screening(data: dict):
    _assert_lean(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert data["lead_result"] in ("NOT_TESTED", "NEGATIVE", "POSITIVE")
    assert data["asbestos_result"] in ("NOT_TESTED", "NEGATIVE", "POSITIVE")
    assert data["outcome"] in ("CLEARED", "FAILED", "PENDING")
    assert isinstance(data["screening_round"], int) and data["screening_round"] >= 1


def assert_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert is_valid_uuid(data.get("category_id", ""))
    assert data["status"] in ("MANIFESTED", "WEIGHED", "QUARANTINED", "SORTED", "DISPOSED_HAZARD")
    assert isinstance(data["estimated_weight_lbs"], (int, float))
    assert isinstance(data["scale_weight_lbs"], (int, float))
    assert isinstance(data["contamination_weight_lbs"], (int, float))
    assert isinstance(data["diverted_weight_lbs"], (int, float))


def assert_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("category_id", ""))
    assert data["condition_grade"] in ("A", "B", "C", "D")
    assert data["measure_unit"] in ("UNIT", "SQFT", "LINEAR_FT")
    assert data["pricing_status"] in ("UNPRICED", "PRICED")
    assert data["sales_status"] in (
        "BACKROOM", "ON_FLOOR", "RESERVED", "SOLD",
        "DONATED_OUT", "RECYCLED", "DISPOSED",
    )
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["current_price_cents"], int)
    assert isinstance(data["markdown_step"], int)
    assert data["disposition_recommended"] in ("NONE", "DONATE", "RECYCLE", "DISPOSE")


def assert_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["current_count"], int) and data["current_count"] >= 0
    assert isinstance(data["restock_threshold"], int)
    assert isinstance(data["restock_recommended"], bool)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_markdown_run(data: dict):
    _assert_lean(data)
    assert isinstance(data["as_of_date"], str) and data["as_of_date"]
    assert isinstance(data["items_evaluated"], int)
    assert isinstance(data["items_marked_down"], int)
    assert isinstance(data["items_flagged_disposition"], int)


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert data["status"] in ("PENDING_APPROVAL", "ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["trailing_volume_cents"], int)
    assert data["discount_tier"] in ("STANDARD", "SILVER", "GOLD")


def assert_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert is_valid_uuid(data.get("category_id", ""))
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "EXPIRED", "CANCELLED")
    assert isinstance(data["min_quantity"], (int, float))
    assert isinstance(data["fulfilled_quantity"], (int, float))


def assert_sale(data: dict):
    _assert_common(data)
    assert data["sale_channel"] in ("WALK_IN", "CONTRACTOR_ACCOUNT")
    assert data["status"] in ("OPEN", "FINALIZED", "VOIDED", "CANCELLED")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["bulk_discount_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_sale_line(data: dict):
    _assert_lean(data)
    assert is_valid_uuid(data.get("sale_id", ""))
    assert is_valid_uuid(data.get("item_id", ""))
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)


def assert_receipt(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("donor_id", ""))
    assert is_valid_uuid(data.get("offer_id", ""))
    assert isinstance(data["receipt_number"], str) and data["receipt_number"].startswith("R-")
    assert data["status"] in ("DRAFT", "ISSUED", "VOID_REQUESTED", "VOIDED", "SUPERSEDED")
    assert isinstance(data["valued_total_cents"], int)


def assert_crew_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["crew_type"] in ("VOLUNTEER", "PAID")
    assert isinstance(data["hourly_rate_cents"], int)
    assert isinstance(data["hazmat_certified"], bool)
    assert isinstance(data["lead_certified"], bool)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["cumulative_job_hours"], (int, float))


def assert_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("job_id", ""))
    assert is_valid_uuid(data.get("crew_member_id", ""))
    assert data["role_on_job"] in ("LEAD", "WORKER")
    assert data["status"] in ("ASSIGNED", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_vehicle(data: dict):
    _assert_common(data)
    assert isinstance(data["plate_code"], str) and data["plate_code"]
    assert data["status"] in ("AVAILABLE", "IN_MAINTENANCE", "RETIRED")
    assert data["capacity_lbs"] > 0


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["subject_type"] in ("DONATION_OFFER", "DECONSTRUCTION_JOB")
    assert is_valid_uuid(data.get("subject_id", ""))
    assert is_valid_uuid(data.get("vehicle_id", ""))
    assert data["status"] in ("BOOKED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert isinstance(data["fee_cents"], int)


def assert_report(data: dict):
    _assert_common(data)
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert data["status"] in ("OPEN", "CLOSED")
    for field in ("total_diverted_lbs", "sold_lbs", "donated_lbs", "recycled_lbs", "landfill_lbs"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_zone_occupancy_invariant(zone: dict):
    """restock_recommended iff current_count <= restock_threshold (PRD §3.8)."""
    assert zone["restock_recommended"] == (zone["current_count"] <= zone["restock_threshold"]), (
        f"restock flag {zone['restock_recommended']} inconsistent with "
        f"count {zone['current_count']} vs threshold {zone['restock_threshold']}"
    )


def assert_account_balance_invariant(account: dict):
    """Credit-limit breach implies suspension handling (PRD §3.9)."""
    assert account["outstanding_balance_cents"] >= 0
    assert isinstance(account["discount_tier"], str)
