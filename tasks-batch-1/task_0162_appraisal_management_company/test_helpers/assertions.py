"""Entity assertions and domain invariant checkers for the AMC API.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Per-entity assert_{entity}() functions check the field set and types
described in the PRD; domain invariant checkers verify cross-field rules such as
the fee-conservation invariant (PRD §2.7).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_mutable(data: dict):
    """id (UUID, no prefix), created_at/updated_at (ISO 8601), version (int) — PRD §2.6."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_lender(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["approved_panel_appraiser_ids"], list)
    assert isinstance(data["monthly_fee_budget_cents"], int)
    assert isinstance(data["committed_fee_cents"], int)
    assert data["committed_fee_cents"] >= 0, "committed_fee_cents must be non-negative"


def assert_appraiser(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["license_state"], str) and len(data["license_state"]) == 2
    assert data["status"] in ("ACTIVE", "SUSPENDED", "RETIRED")
    assert 0.0 < data["base_fee_share_pct"] <= 1.0
    assert isinstance(data["active_assignment_count"], int)
    assert isinstance(data["completed_count"], int)
    assert isinstance(data["on_time_count"], int)
    assert 0.0 <= data["panel_score"] <= 1.0, "panel_score must be in [0,1]"


def assert_property(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["street_address"], str) and len(data["street_address"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2


def assert_order(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["lender_id"])
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["order_fee_cents"], int) and data["order_fee_cents"] > 0
    assert data["product_type"] in ("URAR_1004", "CONDO_1073", "EXTERIOR_2055")
    assert isinstance(data["rush"], bool)
    assert isinstance(data["sla_hours"], int)
    assert data["status"] in (
        "PLACED", "ASSIGNED", "IN_PROGRESS", "IN_QC", "DELIVERED", "COMPLETED", "CANCELLED",
    )


def assert_assignment(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["appraiser_id"])
    assert isinstance(data["sla_hours"], int)
    assert isinstance(data["revision_round"], int)
    assert data["status"] in (
        "OFFERED", "ACCEPTED", "REVISION", "COMPLETED", "DECLINED", "CANCELLED",
    )


def assert_report(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["assignment_id"])
    assert isinstance(data["opinion_of_value_cents"], int) and data["opinion_of_value_cents"] > 0
    assert data["uad_condition_rating"] in ("C1", "C2", "C3", "C4", "C5", "C6")
    assert data["uad_quality_rating"] in ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6")
    assert isinstance(data["comparable_count"], int) and data["comparable_count"] >= 0
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "RESUBMITTED", "ACCEPTED", "REJECTED",
    )


def assert_compliance_review(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["report_id"])
    assert isinstance(data["uspap_comp_minimum_met"], bool)
    assert isinstance(data["uad_ratings_valid"], bool)
    assert data["outcome"] in ("PENDING", "PASS", "CONDITIONAL", "FAIL")
    assert isinstance(data["finding_codes"], list)


def assert_revision_request(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["report_id"])
    assert data["reason_category"] in (
        "USPAP_DEFICIENCY", "UAD_DEFICIENCY", "DATA_CORRECTION", "VALUE_DISPUTE",
    )
    assert data["origin"] in ("COMPLIANCE", "MANUAL")
    assert data["status"] in ("OPEN", "RESOLVED")


def assert_reconsideration(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["requested_value_cents"], int) and data["requested_value_cents"] > 0
    assert isinstance(data["requires_second_review"], bool)
    assert data["resolution"] in ("REQUESTED", "UNDER_REVIEW", "VALUE_CHANGED", "VALUE_UPHELD")


def assert_fee_split(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["order_id"])
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["appraiser_fee_cents"], int)
    assert isinstance(data["amc_fee_cents"], int)
    assert isinstance(data["revision_penalty_cents"], int)


def assert_firewall_event(data: dict):
    """Audit-only entity (PRD §2.4): id + created_at ONLY, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "FirewallEvent must NOT carry updated_at (audit-only, PRD §2.4)"
    assert "version" not in data, "FirewallEvent must NOT carry version (audit-only, PRD §2.4)"


# ─── Domain invariant checkers ─────────────────────────────────────────
def assert_fee_conservation(fee_split: dict, order_fee_cents: int):
    """Fee-conservation invariant (PRD §2.7): appraiser_fee_cents + amc_fee_cents == order_fee_cents."""
    total = fee_split["appraiser_fee_cents"] + fee_split["amc_fee_cents"]
    assert total == order_fee_cents, (
        f"Fee conservation broken: appraiser {fee_split['appraiser_fee_cents']} + "
        f"amc {fee_split['amc_fee_cents']} = {total}, expected order fee {order_fee_cents}"
    )
