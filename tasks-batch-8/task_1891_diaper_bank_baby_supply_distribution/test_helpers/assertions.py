"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. Structural assertions check field presence,
types, enum membership, and the derived-field identities the PRD pins (for
example available_units == on_hand_units - reserved_units); specific expected
values live in the tests themselves.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import SIZE_CODES


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def _assert_optional_timestamp(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{field} must be null or ISO 8601, got {value!r}"
    )


def _assert_intake_lines(lines):
    assert isinstance(lines, list) and len(lines) >= 1, "lines must be a non-empty array"
    for line in lines:
        assert line["size_code"] in SIZE_CODES, f"unknown size_code {line.get('size_code')!r}"
        assert isinstance(line["quantity"], int) and line["quantity"] >= 1


def assert_partner_agency(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["agency_code"], str) and data["agency_code"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["children_served_monthly"], int) and data["children_served_monthly"] >= 0
    assert isinstance(data["storage_capacity_units"], int) and data["storage_capacity_units"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["active_allocated_units"], int) and data["active_allocated_units"] >= 0


def assert_grant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["funder_name"], str) and data["funder_name"]
    assert isinstance(data["grant_code"], str) and data["grant_code"]
    assert isinstance(data["total_amount_cents"], int) and data["total_amount_cents"] > 0
    assert data["restriction"] in ("UNRESTRICTED", "PRODUCT_PURCHASE_ONLY", "OPERATIONS_ONLY")
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ("ACTIVE", "CLOSED", "EXHAUSTED")
    for field in ("committed_cents", "spent_cents", "available_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert_grant_funds_invariants(data)


def assert_grant_funds_invariants(data: dict):
    """The PRD funds identity: available == total - committed - spent, always."""
    assert data["available_cents"] == (
        data["total_amount_cents"] - data["committed_cents"] - data["spent_cents"]
    ), (
        f"available_cents {data['available_cents']} != total {data['total_amount_cents']} "
        f"- committed {data['committed_cents']} - spent {data['spent_cents']}"
    )


def assert_inventory(data: dict):
    _assert_common_fields(data)
    assert data["initialized"] is True
    sizes = data["sizes"]
    assert isinstance(sizes, dict), "sizes must be a map keyed by size code"
    assert set(sizes.keys()) == set(SIZE_CODES), (
        f"sizes must carry every size code, got {sorted(sizes.keys())}"
    )
    total = 0
    for code in SIZE_CODES:
        entry = sizes[code]
        for field in ("on_hand_units", "reserved_units",
                      "reorder_threshold_units", "available_units"):
            assert isinstance(entry[field], int), f"sizes.{code}.{field} must be an integer"
        assert isinstance(entry["restock_needed"], bool)
        # PRD: the two derived quantities must always agree with the first three.
        assert entry["available_units"] == entry["on_hand_units"] - entry["reserved_units"], (
            f"sizes.{code}.available_units must equal on_hand_units - reserved_units"
        )
        assert entry["restock_needed"] == (
            entry["on_hand_units"] <= entry["reorder_threshold_units"]
        ), f"sizes.{code}.restock_needed inconsistent with threshold"
        total += entry["on_hand_units"]
    assert data["total_on_hand_units"] == total, (
        "total_on_hand_units must equal the sum of on_hand_units across all sizes"
    )


def size_entry(inventory: dict, size_code: str) -> dict:
    """Return the per-size ledger entry for `size_code` from an Inventory body."""
    return inventory["sizes"][size_code]


def assert_intake_batch(data: dict):
    _assert_common_fields(data)
    assert data["source_type"] in ("DONATION", "PURCHASE")
    assert data["donor_name"] is None or isinstance(data["donor_name"], str)
    assert data["purchase_order_id"] is None or isinstance(data["purchase_order_id"], str)
    _assert_intake_lines(data["lines"])
    assert isinstance(data["total_units"], int) and data["total_units"] >= 1
    assert data["total_units"] == sum(line["quantity"] for line in data["lines"]), (
        "total_units must equal the sum of line quantities"
    )
    assert isinstance(data["valued_total_cents"], int) and data["valued_total_cents"] >= 0
    assert data["status"] in ("COUNTED", "POSTED", "VOIDED")
    _assert_optional_timestamp(data, "posted_at")


def assert_purchase_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["grant_id"], str)
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    for line in data["lines"]:
        assert line["size_code"] in SIZE_CODES
        assert isinstance(line["quantity"], int) and line["quantity"] >= 1
        assert isinstance(line["unit_cost_cents"], int) and line["unit_cost_cents"] >= 0
    assert isinstance(data["total_cost_cents"], int) and data["total_cost_cents"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "RECEIVED", "CANCELLED")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data["submitted_by_user_id"] is None or isinstance(data["submitted_by_user_id"], str)
    assert data["received_intake_batch_id"] is None or isinstance(
        data["received_intake_batch_id"], str)


def assert_allocation_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert data["formula_variant"] in ("NEED_WEIGHTED", "EQUAL_SPLIT")
    assert data["status"] in ("DRAFT", "PUBLISHED", "FINALIZED")
    _assert_optional_timestamp(data, "computed_at")
    _assert_optional_timestamp(data, "published_at")
    assert isinstance(data["total_allocated_units"], int) and data["total_allocated_units"] >= 0


def assert_allocation_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["allocation_run_id"], str)
    assert isinstance(data["agency_id"], str)
    assert data["size_code"] in SIZE_CODES
    assert isinstance(data["allocated_units"], int) and data["allocated_units"] >= 0
    assert isinstance(data["fulfilled_units"], int) and data["fulfilled_units"] >= 0
    assert isinstance(data["released_units"], int) and data["released_units"] >= 0
    assert data["status"] in ("PROJECTED", "ALLOCATED", "PARTIALLY_FULFILLED",
                              "FULFILLED", "RELEASED")
    assert data["fulfilled_units"] <= data["allocated_units"], (
        "fulfilled_units may not exceed allocated_units"
    )


def assert_distribution_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["host_agency_id"], str)
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert is_iso8601_timestamp(data["starts_at"]), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data["ends_at"]), "ends_at must be ISO 8601"
    assert data["status"] in ("SCHEDULED", "OPEN", "LOCKED", "COMPLETED", "CANCELLED")
    _assert_optional_timestamp(data, "completed_at")
    assert isinstance(data["issued_total_units"], int) and data["issued_total_units"] >= 0


def assert_issuance(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["household_id"], str)
    _assert_intake_lines(data["lines"])
    assert isinstance(data["total_units"], int) and data["total_units"] >= 1
    assert data["total_units"] == sum(line["quantity"] for line in data["lines"]), (
        "total_units must equal the sum of line quantities"
    )
    assert data["status"] in ("RECORDED", "FULFILLED", "VOIDED")
    _assert_optional_timestamp(data, "fulfilled_at")
    assert isinstance(data["recorded_by_role"], str) and data["recorded_by_role"]


def assert_client_household(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["household_code"], str) and data["household_code"]
    assert isinstance(data["children_sizes"], list) and 1 <= len(data["children_sizes"]) <= 8
    for code in data["children_sizes"]:
        assert code in SIZE_CODES
    assert isinstance(data["consent_on_file"], bool)
    assert isinstance(data["privacy_restricted"], bool)
    assert data["eligibility_status"] in ("PENDING_REVIEW", "ELIGIBLE", "INELIGIBLE")
    assert data["eligibility_reason"] is None or isinstance(data["eligibility_reason"], str)
    assert isinstance(data["monthly_allotment_units"], int)
    assert data["monthly_allotment_units"] == 50 * len(data["children_sizes"]), (
        "monthly_allotment_units must equal fifty times the number of children"
    )
    assert isinstance(data["consumed_this_month_units"], int)
    assert data["consumed_this_month_units"] >= 0


def assert_volunteer_shift(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert is_iso8601_timestamp(data["starts_at"]), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data["ends_at"]), "ends_at must be ISO 8601"
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["signups"], list)
    for signup in data["signups"]:
        assert isinstance(signup["volunteer_email"], str) and signup["volunteer_email"]
        assert isinstance(signup["volunteer_name"], str) and signup["volunteer_name"]
        assert is_iso8601_timestamp(signup["signed_up_at"]), "signed_up_at must be ISO 8601"
    assert isinstance(data["signup_count"], int)
    assert data["signup_count"] == len(data["signups"]), (
        "signup_count must equal the length of the signups array"
    )
    assert data["status"] in ("OPEN", "FULL")
    # PRD: FULL exactly when the signup count reaches capacity.
    assert (data["status"] == "FULL") == (data["signup_count"] == data["capacity"]), (
        "status must be FULL exactly when signup_count == capacity"
    )


def find_forecast_size_entry(sizes: list, size_code: str) -> dict:
    """Locate the per-size entry for `size_code` in a forecast sizes array.

    The PRD pins a per-size array under `sizes`; each entry identifies its size
    through a size-code field.
    """
    assert isinstance(sizes, list), "forecast sizes must be an array"
    for entry in sizes:
        if entry.get("size_code") == size_code or entry.get("size") == size_code:
            return entry
    raise AssertionError(f"No forecast entry found for {size_code}: {sizes!r}")
