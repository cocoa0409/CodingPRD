"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_home_model(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["floor_plan_type"] in {"SINGLE_WIDE", "DOUBLE_WIDE", "TRIPLE_WIDE", "MODULAR"}
    assert isinstance(data["section_count"], int) and data["section_count"] >= 1
    assert data["width_ft"] > 0 and data["length_ft"] > 0
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["factory_lead_time_days"], int) and data["factory_lead_time_days"] >= 0
    assert data["status"] in {"ACTIVE", "DISCONTINUED"}


def assert_community(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["lot_rent_cents"], int) and data["lot_rent_cents"] >= 0
    assert data["status"] in {"ACTIVE", "CLOSED"}


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("community_id", ""))
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert isinstance(data["max_sections"], int) and data["max_sections"] >= 1
    assert data["max_length_ft"] > 0
    assert isinstance(data["utilities_ready"], bool)
    assert data["status"] in {"AVAILABLE", "RESERVED", "LEASED"}


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["phone"], str) and data["phone"]
    assert data["credit_tier"] in {"TIER_A", "TIER_B", "TIER_C"}
    assert data["status"] in {"ACTIVE", "INACTIVE"}


def assert_home_unit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("model_id", ""))
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["unit_kind"] in {"STOCK", "FACTORY_ORDER", "TRADE_IN"}
    assert data["condition_grade"] in {"NEW", "A", "B", "C"}
    assert data["status"] in {
        "AT_FACTORY", "AT_DEALER", "RESERVED", "IN_TRANSIT",
        "ON_SITE", "INSTALLED", "RECONDITIONING", "RETAIL_READY",
    }


def assert_sales_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("home_unit_id", ""))
    assert data["placement_type"] in {"COMMUNITY_LOT", "PRIVATE_LAND"}
    assert data["financing_type"] in {"CHATTEL", "REAL_PROPERTY"}
    for field in (
        "agreed_home_price_cents", "deposit_cents", "options_total_cents",
        "discount_cents", "doc_fee_cents", "transport_charge_cents",
        "total_price_cents", "trade_in_credit_cents", "amount_financed_cents",
        "delay_compensation_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be non-negative integer cents"
    assert data["deal_status"] in {
        "DRAFT", "PENDING_SITE_EVAL", "SITE_APPROVED", "PENDING_FINANCING",
        "FINANCING_APPROVED", "AWAITING_DELIVERY", "DELIVERED", "SET_COMPLETE",
        "TITLED", "CLOSED", "CANCELLED",
    }
    assert data["payment_status"] in {"UNPAID", "DEPOSIT_PAID", "FINANCED", "REFUNDED"}


def assert_order_option(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("sales_order_id", ""))
    assert isinstance(data["option_code"], str) and data["option_code"]
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["line_total_cents"] == data["unit_price_cents"] * data["quantity"]
    assert data["status"] in {"ACTIVE", "VOIDED"}


def assert_site_evaluation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("sales_order_id", ""))
    assert isinstance(data["evaluator_id"], str) and data["evaluator_id"]
    assert data["status"] in {"SCHEDULED", "FINDINGS_RECORDED", "APPROVED", "REJECTED", "SUPERSEDED"}


def assert_financing_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("sales_order_id", ""))
    assert data["financing_type"] in {"CHATTEL", "REAL_PROPERTY"}
    assert isinstance(data["lender_name"], str) and data["lender_name"]
    assert isinstance(data["term_months"], int) and data["term_months"] >= 1
    assert isinstance(data["down_payment_cents"], int) and data["down_payment_cents"] >= 0
    assert data["status"] in {
        "DRAFT", "SUBMITTED", "CONDITIONALLY_APPROVED", "APPROVED",
        "DENIED", "FUNDED", "EXPIRED", "SUPERSEDED",
    }


def assert_transport_crew(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["crew_size"], int) and data["crew_size"] >= 1
    assert isinstance(data["can_set_multiwide"], bool)
    assert isinstance(data["max_sections_per_window"], int) and data["max_sections_per_window"] >= 1
    assert isinstance(data["booked_dates"], list)


def assert_transport_job(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("sales_order_id", ""))
    assert is_valid_uuid(data.get("home_unit_id", ""))
    assert is_valid_uuid(data.get("crew_id", ""))
    assert data["origin"] in {"FACTORY", "DEALER_LOT"}
    assert isinstance(data["distance_miles"], int) and data["distance_miles"] >= 0
    assert isinstance(data["sections_count"], int) and data["sections_count"] >= 1
    assert isinstance(data["escort_required"], bool)
    assert isinstance(data["escort_vehicle_count"], int) and data["escort_vehicle_count"] >= 0
    assert isinstance(data["quoted_cost_cents"], int) and data["quoted_cost_cents"] >= 0
    assert data["status"] in {"SCHEDULED", "DELAYED", "EN_ROUTE", "DELIVERED", "SET_COMPLETE", "CANCELLED"}


def assert_title_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("home_unit_id", ""))
    assert data["title_type"] in {"MANUFACTURED_CERTIFICATE", "REAL_PROPERTY_AFFIXED"}
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["status"] in {"APPLIED", "ISSUED", "CONVERTED", "SURRENDERED"}


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("home_unit_id", ""))
    assert is_valid_uuid(data.get("sales_order_id", ""))
    assert data["claim_type"] in {"FACTORY_DEFECT", "TRANSPORT_DAMAGE", "INSTALLATION_DAMAGE"}
    assert isinstance(data["description"], str) and data["description"]
    assert isinstance(data["estimated_cost_cents"], int) and data["estimated_cost_cents"] >= 0
    assert data["status"] in {"UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "DENIED", "RESOLVED"}


def assert_trade_in_appraisal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("sales_order_id", ""))
    assert is_valid_uuid(data.get("model_id", ""))
    assert isinstance(data["declared_model_year"], int)
    assert data["declared_condition"] in {"A", "B", "C"}
    assert isinstance(data["provisional_credit_cents"], int) and data["provisional_credit_cents"] >= 0
    assert data["status"] in {
        "DRAFT", "INSPECTED", "OFFERED", "ACCEPTED",
        "DECLINED", "SUPERSEDED", "RECONDITIONING", "RETAIL_READY",
    }


def assert_delay_notice(data: dict):
    # Append-only record: id + created_at only (PRD §2.5 exemption).
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "DelayNotice must not carry updated_at"
    assert "version" not in data, "DelayNotice must not carry version"
    assert data["reason"] in {"WEATHER", "PERMIT_HOLD", "FACTORY_DELAY", "SITE_NOT_READY", "ESCORT_UNAVAILABLE"}
    assert isinstance(data["buyer_notified"], bool)
    assert isinstance(data["delay_days"], int) and data["delay_days"] >= 0
    assert isinstance(data["compensation_cents"], int) and data["compensation_cents"] >= 0
    # Polymorphic subject: exactly one of the two references is set (PRD §3.6).
    assert (data.get("transport_job_id") is None) != (data.get("sales_order_id") is None)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant for second-precision comparison (PRD §2.6)."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def assert_instant_equals(actual: str, expected_iso: str):
    """Datetime comparisons are evaluated at second precision (PRD §2.6)."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected instant {expected_iso}, got {actual}"
    )


def assert_booked_dates(data: dict, expected_dates: list):
    """booked_dates is a computed, sorted list of calendar dates (PRD §3.6)."""
    actual = [str(d)[:10] for d in data.get("booked_dates", [])]
    assert actual == list(expected_dates), f"Expected booked_dates {expected_dates}, got {actual}"


def assert_order_money_conservation(order: dict):
    """amount_financed = total - deposit - trade_in_credit (PRD §3.3)."""
    lhs = order["total_price_cents"]
    rhs = order["deposit_cents"] + order["trade_in_credit_cents"] + order["amount_financed_cents"]
    assert lhs == rhs, f"Money conservation violated: total {lhs} != deposit+credit+financed {rhs}"
