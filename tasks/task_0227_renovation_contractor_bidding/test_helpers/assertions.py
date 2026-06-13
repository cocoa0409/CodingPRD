"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response shape against the PRD contract.
assert_escrow_invariants() enforces the escrow ledger identity from PRD 2.6.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id is a UUID; created_at/updated_at are ISO 8601; version is a positive int.
    (PRD 2.4: every resource carries id, created_at, updated_at, version.)"""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 and increments per mutation"


def assert_homeowner(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0


def assert_contractor(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["trade"] in ["GENERAL", "ELECTRICAL", "PLUMBING", "HVAC", "ROOFING"]
    assert isinstance(data["license_number"], str)
    assert is_iso8601_timestamp(data["license_expiry"])
    assert isinstance(data["insurance_coverage_cents"], int)
    assert data["insurance_coverage_cents"] >= 0
    assert data["qualification_status"] in ["PENDING", "QUALIFIED", "SUSPENDED", "REVOKED"]
    assert isinstance(data["rating_sum"], int) and data["rating_sum"] >= 0
    assert isinstance(data["rating_count"], int) and data["rating_count"] >= 0
    assert isinstance(data["average_rating"], (int, float)) and data["average_rating"] >= 0


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["homeowner_id"], str)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["budget_cap_cents"], int) and data["budget_cap_cents"] > 0
    assert is_iso8601_timestamp(data["bid_deadline"])
    assert data["required_trade"] in ["GENERAL", "ELECTRICAL", "PLUMBING", "HVAC", "ROOFING"]
    assert isinstance(data["min_rating"], (int, float)) and 0 <= data["min_rating"] <= 5
    assert data["status"] in [
        "DRAFT", "OPEN_FOR_BIDS", "AWARDED", "IN_PROGRESS",
        "COMPLETED", "DISPUTED", "CANCELLED",
    ]
    assert isinstance(data["contract_value_cents"], int) and data["contract_value_cents"] >= 0
    assert isinstance(data["scope_locked"], bool)


def assert_scope_line_item(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["description"], str)
    assert data["quantity"] > 0
    assert data["unit"] in ["SQFT", "UNIT", "HOUR", "LUMP"]
    assert isinstance(data["estimated_unit_cost_cents"], int) and data["estimated_unit_cost_cents"] >= 0
    assert isinstance(data["estimated_total_cents"], int) and data["estimated_total_cents"] >= 0


def assert_bid(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["contractor_id"], str)
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["duration_days"], int) and data["duration_days"] > 0
    assert data["status"] in ["DRAFT", "SUBMITTED", "REVISING", "AWARDED", "REJECTED", "WITHDRAWN"]
    assert isinstance(data["rank_score"], (int, float))


def assert_bid_line_item(data: dict):
    _assert_common(data)
    assert isinstance(data["bid_id"], str)
    assert isinstance(data["scope_line_item_id"], str)
    assert data["quantity"] > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["line_total_cents"], int) and data["line_total_cents"] >= 0


def assert_milestone(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["title"], str)
    assert 0 < data["release_pct"] <= 1
    assert data["status"] in ["PENDING", "DRAW_REQUESTED", "APPROVED", "PAID", "DISPUTED"]


def assert_escrow(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    for field in ("funded_cents", "released_cents", "retained_cents", "available_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["status"] in ["UNFUNDED", "FUNDED", "CLOSED"]


def assert_escrow_invariants(data: dict):
    """PRD 2.6: available_cents == funded - released - retained, and available is
    never negative."""
    assert data["available_cents"] == (
        data["funded_cents"] - data["released_cents"] - data["retained_cents"]
    ), "available_cents must equal funded - released - retained"
    assert data["available_cents"] >= 0, "available_cents must never be negative"
    assert data["retained_cents"] >= 0
    assert data["released_cents"] >= 0


def assert_draw(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["milestone_id"], str)
    assert isinstance(data["contractor_id"], str)
    for field in ("gross_amount_cents", "retainage_cents", "net_release_cents"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["net_release_cents"] == data["gross_amount_cents"] - data["retainage_cents"]
    assert data["status"] in ["REQUESTED", "APPROVED", "PAID", "REJECTED", "DISPUTED"]


def assert_lien_waiver(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["contractor_id"], str)
    assert isinstance(data["draw_id"], str)
    assert data["waiver_type"] in ["CONDITIONAL", "UNCONDITIONAL"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ["COLLECTED", "VOIDED"]


def assert_change_order(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["bid_id"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["delta_cents"], int)
    assert data["status"] in ["PROPOSED", "APPROVED", "REJECTED"]


def assert_dispute(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert data["subject_type"] in ["DRAW", "CHANGE_ORDER"]
    assert isinstance(data["subject_id"], str)
    assert data["raised_by"] in ["HOMEOWNER", "CONTRACTOR"]
    assert isinstance(data["reason"], str)
    assert data["status"] in ["OPEN", "RESOLVED"]
    if data.get("resolution") is not None:
        assert data["resolution"] in ["UPHELD", "OVERTURNED"]
