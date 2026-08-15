"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """Every resource carries id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["city"], str) and data["city"]
    assert isinstance(data["current_season"], int)


def assert_sponsor(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["industry_category"] in (
        "BEVERAGE", "BANKING", "AUTO", "AIRLINE", "TECH")
    assert data["sponsor_status"] in ("PROSPECT", "ACTIVE", "SUSPENDED", "BLOCKED")


def assert_asset(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("venue_id", "")), "venue_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert data["asset_class"] in ("SIGNAGE", "DIGITAL", "HOSPITALITY")
    assert isinstance(data["rate_card_unit_cents"], int)
    assert isinstance(data["avg_impressions_per_unit"], int)
    assert isinstance(data["cpm_cents"], int)
    assert data["asset_status"] in ("AVAILABLE", "RETIRED")


def assert_rights_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("venue_id", "")), "venue_id must be a UUID"
    assert data["holder"] in ("TEAM", "VENUE", "LEAGUE")
    assert data["category"] in ("BEVERAGE", "BANKING", "AUTO", "AIRLINE", "TECH")
    assert isinstance(data["first_season"], int)
    assert isinstance(data["last_season"], int)
    assert data["window_status"] in ("RESERVED", "ACTIVE", "RELEASED", "EXPIRED")


def assert_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("venue_id", "")), "venue_id must be a UUID"
    assert is_valid_uuid(data.get("sponsor_id", "")), "sponsor_id must be a UUID"
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["term_first_season"], int)
    assert isinstance(data["term_last_season"], int)
    assert isinstance(data["base_fee_cents"], int)
    assert data["escalator_mode"] in ("COMPOUND", "SIMPLE")
    assert data["contract_status"] in (
        "DRAFT", "PROPOSED", "COUNTERSIGNED", "ACTIVE", "SUSPENDED",
        "EXPIRED", "TERMINATED")
    assert data["rights_status"] in ("CLEAR", "CONTESTED")
    assert isinstance(data["scheduled_total_cents"], int)
    assert isinstance(data["receivable_cents"], int)
    assert isinstance(data["make_good_outstanding_cents"], int)


def assert_grant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert data["category"] in ("BEVERAGE", "BANKING", "AUTO", "AIRLINE", "TECH")
    assert isinstance(data["first_season"], int)
    assert isinstance(data["last_season"], int)
    assert data["grant_status"] in ("PENDING", "ACTIVE", "CONFLICTED", "RELEASED")


def assert_deliverable(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert is_valid_uuid(data.get("asset_id", "")), "asset_id must be a UUID"
    assert isinstance(data["season"], int)
    assert data["unit_kind"] in ("GAME_DISPLAY", "IMPRESSION_BLOCK", "SUITE_NIGHT")
    assert isinstance(data["contracted_units"], int) and data["contracted_units"] > 0
    assert isinstance(data["approved_units"], int) and data["approved_units"] >= 0
    assert data["deliverable_status"] in (
        "SCHEDULED", "IN_PROGRESS", "FULFILLED", "MISSED", "COMPED", "CANCELLED")


def assert_evidence(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("deliverable_id", "")), \
        "deliverable_id must be a UUID"
    assert isinstance(data["units_claimed"], int) and data["units_claimed"] > 0
    assert isinstance(data["evidence_uri"], str) and data["evidence_uri"]
    assert isinstance(data["submitted_by_user_id"], str)
    assert data["submission_status"] in ("SUBMITTED", "APPROVED", "REJECTED", "VOIDED")


def assert_credit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert is_valid_uuid(data.get("deliverable_id", "")), \
        "deliverable_id must be a UUID"
    assert isinstance(data["requested_amount_cents"], int) \
        and data["requested_amount_cents"] > 0
    assert data["credit_status"] in (
        "REQUESTED", "APPROVED", "REDEEMED", "DECLINED", "VOIDED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert isinstance(data["installment_seq"], int) and data["installment_seq"] >= 1
    assert data["installment_label"] in ("SIGNING", "MID_SEASON", "POST_SEASON")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert isinstance(data["credits_applied_cents"], int) \
        and data["credits_applied_cents"] >= 0
    assert data["invoice_status"] in (
        "DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "VOID", "WRITTEN_OFF")
    assert isinstance(data.get("payments", []), list)


def assert_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert isinstance(data["season"], int)
    assert data["report_status"] in ("DRAFT", "ISSUED", "ACKNOWLEDGED")
    assert isinstance(data["delivered_value_provisional_cents"], int)
    assert isinstance(data["delivered_value_final_cents"], int)
    assert isinstance(data["make_good_due_cents"], int)


def assert_opportunity(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert isinstance(data["proposed_fee_cents"], int) \
        and data["proposed_fee_cents"] > 0
    assert data["stage"] in ("IDENTIFIED", "PROPOSED", "NEGOTIATING", "WON", "LOST")


def assert_contract_financial_invariants(data: dict):
    """Derived contract totals are always non-negative integer cents."""
    assert data["receivable_cents"] >= 0, "receivable_cents must be >= 0"
    assert data["make_good_outstanding_cents"] >= 0, \
        "make_good_outstanding_cents must be >= 0"
    assert data["scheduled_total_cents"] >= 0, "scheduled_total_cents must be >= 0"
