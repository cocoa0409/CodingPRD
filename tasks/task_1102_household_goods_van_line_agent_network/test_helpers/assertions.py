"""Entity assertions and domain invariant checkers (PRD sections 2.4, 2.9, 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_AGENT_STATUSES = ["ACTIVE", "SUSPENDED", "TERMINATED"]
_AGENT_CAPABILITIES = ["BOOKING", "ORIGIN", "HAULING", "DESTINATION"]
_COMMISSION_TIERS = ["STANDARD", "PREFERRED", "PREMIER"]
_TARIFF_STATUSES = ["DRAFT", "PUBLISHED"]
_ORDER_STATUSES = [
    "REGISTERED", "BOOKED", "IN_TRANSIT", "IN_SIT", "OUT_FOR_DELIVERY",
    "DELIVERED", "SETTLED", "CLOSED", "CANCELLED",
]
_BILLING_STATUSES = ["UNBILLED", "PROVISIONALLY_BILLED", "FINAL_BILLED", "PAID"]
_PRICING_MODES = ["BINDING", "NON_BINDING"]
_ESTIMATE_STATUSES = ["ISSUED", "ACCEPTED", "DECLINED", "SUPERSEDED", "EXPIRED", "VOIDED"]
_ASSIGNMENT_STATUSES = ["PROPOSED", "CONFIRMED", "RELEASED", "COMPLETED"]
_COVERAGE_TYPES = ["RELEASED_VALUE", "FULL_VALUE_PROTECTION"]
_COVERAGE_STATUSES = ["ELECTED", "LOCKED", "SUPERSEDED"]
_TICKET_KINDS = ["ORIGINAL", "REWEIGH"]
_REWEIGH_STATUSES = [
    "REQUESTED", "PERFORMED", "APPLIED", "DECLINED_BY_CUSTOMER", "CANCELLED", "EXPIRED",
]
_WAREHOUSE_STATUSES = ["ACTIVE", "INACTIVE"]
_SIT_LOT_STATUSES = ["IN_STORAGE", "RELEASED", "CONVERTED_PERMANENT"]
_CREW_STATUSES = ["REQUESTED", "CONFIRMED", "COMPLETED", "INVOICED", "CANCELLED"]
_SERVICE_ENDS = ["ORIGIN", "DESTINATION"]
_STATEMENT_STATUSES = ["PROVISIONAL", "FINAL", "RECONCILED"]
_CLAIM_STATUSES = ["FILED", "OFFER_MADE", "DISPUTED", "ACCEPTED", "PAID", "WITHDRAWN"]
_DISPUTE_STATUSES = [
    "OPENED", "RESPONSE_FILED", "ARBITRATION_DOCKETED", "DECIDED", "CLOSED", "WITHDRAWN",
]
_FEE_ALLOCATIONS = ["FILER", "RESPONDENT", "SPLIT"]


def _assert_common_fields(data: dict):
    """PRD section 2.4: id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive int, got {data.get('version')!r}"
    )


def assert_agent(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["agent_code"], str) and data["agent_code"]
    assert isinstance(data["capabilities"], list) and len(data["capabilities"]) >= 1
    assert all(c in _AGENT_CAPABILITIES for c in data["capabilities"])
    assert isinstance(data["home_market"], str) and data["home_market"]
    assert data["commission_tier"] in _COMMISSION_TIERS
    assert isinstance(data["quality_score"], int)
    assert isinstance(data["ytd_linehaul_share_cents"], int)
    assert data["status"] in _AGENT_STATUSES


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["phone"], str) and data["phone"]
    assert data["status"] == "ACTIVE"


def assert_tariff(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["tariff_code"], str) and data["tariff_code"]
    assert is_iso8601_timestamp(data["effective_start"])
    assert is_iso8601_timestamp(data["effective_end"])
    assert isinstance(data["base_rate_cents_per_cwt"], int)
    assert isinstance(data["mileage_bands"], list) and len(data["mileage_bands"]) >= 1
    for band in data["mileage_bands"]:
        assert isinstance(band["min_miles"], int)
        assert isinstance(band["max_miles"], int)
        assert isinstance(band["rate_multiplier"], (int, float))
    assert isinstance(data["fuel_surcharge_pct"], (int, float))
    assert isinstance(data["sit_daily_rate_cents_per_cwt"], int)
    assert isinstance(data["hourly_labor_rate_cents"], int)
    assert data["status"] in _TARIFF_STATUSES


def assert_move_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_number"], str) and data["order_number"]
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["tariff_id"])
    assert data["pricing_mode"] in _PRICING_MODES
    assert isinstance(data["origin_city"], str) and data["origin_city"]
    assert isinstance(data["origin_state"], str) and data["origin_state"]
    assert isinstance(data["destination_city"], str) and data["destination_city"]
    assert isinstance(data["destination_state"], str) and data["destination_state"]
    assert isinstance(data["mileage"], int) and data["mileage"] >= 1
    assert is_iso8601_timestamp(data["pickup_date"])
    assert data["status"] in _ORDER_STATUSES
    assert data["billing_status"] in _BILLING_STATUSES
    for money_field in (
        "collected_at_delivery_cents", "final_charges_cents",
        "delivery_amount_due_cents", "deferred_balance_cents",
    ):
        value = data.get(money_field)
        assert value is None or isinstance(value, int), (
            f"{money_field} must be integer cents or null, got {value!r}"
        )
    for weight_field in ("estimated_weight_lbs", "actual_weight_lbs"):
        value = data.get(weight_field)
        assert value is None or isinstance(value, int), (
            f"{weight_field} must be int or null, got {value!r}"
        )


def assert_estimate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    supersedes = data.get("supersedes_estimate_id")
    assert supersedes is None or is_valid_uuid(supersedes)
    assert data["estimate_kind"] in _PRICING_MODES
    assert isinstance(data["estimated_weight_lbs"], int) and data["estimated_weight_lbs"] >= 1
    assert isinstance(data["packing_services_cents"], int) and data["packing_services_cents"] >= 0
    for component in ("linehaul_cents", "fuel_surcharge_cents",
                      "valuation_premium_cents", "estimated_charges_cents"):
        assert isinstance(data[component], int), f"{component} must be integer cents"
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in _ESTIMATE_STATUSES


def assert_agent_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["agent_id"])
    assert data["role"] in _AGENT_CAPABILITIES
    assert isinstance(data["split_pct"], (int, float))
    amount = data.get("split_amount_cents")
    assert amount is None or isinstance(amount, int)
    assert data["status"] in _ASSIGNMENT_STATUSES


def assert_valuation_coverage(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert data["coverage_type"] in _COVERAGE_TYPES
    assert isinstance(data["declared_value_cents"], int) and data["declared_value_cents"] >= 0
    assert isinstance(data["deductible_cents"], int)
    assert data["deductible_cents"] in (0, 25000, 50000)
    assert isinstance(data["premium_cents"], int) and data["premium_cents"] >= 0
    assert data["status"] in _COVERAGE_STATUSES


def assert_weight_ticket(data: dict):
    """WeightTicket is immutable scale evidence: id + created_at only; PRD section
    2.4 states updated_at and version are absent from it."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "WeightTicket must not expose updated_at"
    assert "version" not in data, "WeightTicket must not expose version"
    assert is_valid_uuid(data["order_id"])
    assert data["ticket_kind"] in _TICKET_KINDS
    assert isinstance(data["scale_location"], str) and data["scale_location"]
    assert is_iso8601_timestamp(data["weighed_at"])
    assert isinstance(data["tare_weight_lbs"], int) and data["tare_weight_lbs"] >= 1
    assert isinstance(data["gross_weight_lbs"], int)
    assert isinstance(data["net_weight_lbs"], int)


def assert_reweigh_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert data["requested_by_role"] in ["CUSTOMER", "BOOKING_AGENT"]
    ticket = data.get("resulting_ticket_id")
    assert ticket is None or is_valid_uuid(ticket)
    assert data["status"] in _REWEIGH_STATUSES


def assert_warehouse(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["market"], str) and data["market"]
    assert isinstance(data["capacity_cwt"], int) and data["capacity_cwt"] >= 1
    assert isinstance(data["occupied_cwt"], int) and data["occupied_cwt"] >= 0
    assert data["status"] in _WAREHOUSE_STATUSES


def assert_sit_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["stored_weight_cwt"], int) and data["stored_weight_cwt"] >= 1
    assert is_iso8601_timestamp(data["checked_in_at"])
    released = data.get("released_at")
    assert released is None or is_iso8601_timestamp(released)
    assert isinstance(data["days_stored"], int) and data["days_stored"] >= 0
    assert isinstance(data["accrued_storage_cents"], int) and data["accrued_storage_cents"] >= 0
    assert data["status"] in _SIT_LOT_STATUSES


def assert_crew_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["agent_id"])
    assert data["service_end"] in _SERVICE_ENDS
    assert is_iso8601_timestamp(data["service_date"])
    assert isinstance(data["start_hour"], int) and 0 <= data["start_hour"] <= 23
    assert isinstance(data["end_hour"], int) and 1 <= data["end_hour"] <= 24
    assert isinstance(data["crew_size"], int) and data["crew_size"] >= 1
    assert isinstance(data["labor_hours"], int) and data["labor_hours"] >= 1
    assert isinstance(data["invoice_amount_cents"], int)
    assert data["status"] in _CREW_STATUSES


def assert_revenue_statement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    for money_field in (
        "linehaul_revenue_cents", "accessorial_revenue_cents", "booking_share_cents",
        "origin_share_cents", "hauling_share_cents", "destination_share_cents",
        "van_line_share_cents", "chargeback_total_cents",
    ):
        assert isinstance(data[money_field], int), f"{money_field} must be integer cents"
    assert data["status"] in _STATEMENT_STATUSES


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["valuation_coverage_id"])
    assert is_iso8601_timestamp(data["filed_at"])
    assert isinstance(data["description"], str)
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] >= 1
    assert isinstance(data["claimed_item_weight_lbs"], int) and data["claimed_item_weight_lbs"] >= 1
    offer = data.get("offer_amount_cents")
    assert offer is None or isinstance(offer, int)
    settled = data.get("settled_amount_cents")
    assert settled is None or isinstance(settled, int)
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
    assert data["status"] in _CLAIM_STATUSES


def assert_dispute(data: dict):
    _assert_common_fields(data)
    claim_id = data.get("claim_id")
    statement_id = data.get("revenue_statement_id")
    assert claim_id is None or is_valid_uuid(claim_id)
    assert statement_id is None or is_valid_uuid(statement_id)
    assert (claim_id is None) != (statement_id is None), (
        "exactly one of claim_id / revenue_statement_id must be present"
    )
    assert data["opened_by_role"] in ["CUSTOMER", "AGENT"]
    assert isinstance(data["filer_user_id"], str) and data["filer_user_id"]
    assert isinstance(data["subject_amount_cents"], int) and data["subject_amount_cents"] >= 1
    fee = data.get("fee_allocated_to")
    assert fee is None or fee in _FEE_ALLOCATIONS
    decision = data.get("decision_amount_cents")
    assert decision is None or isinstance(decision, int)
    assert data["status"] in _DISPUTE_STATUSES


# ---------------------------------------------------------------------------
# Domain invariant checkers (PRD sections 2.9 and 3.8)
# ---------------------------------------------------------------------------
def assert_warehouse_occupancy_invariant(warehouse: dict, in_storage_lots: list):
    """PRD section 2.9: occupied_cwt equals the sum of stored_weight_cwt over the
    warehouse's lots whose status is IN_STORAGE."""
    expected = sum(lot["stored_weight_cwt"] for lot in in_storage_lots)
    assert warehouse["occupied_cwt"] == expected, (
        f"occupied_cwt {warehouse['occupied_cwt']} != sum of IN_STORAGE lots {expected}"
    )


def assert_waterfall_conservation(statement: dict, valuation_premium_cents: int = 0):
    """PRD section 3.8: the four role shares plus the van-line share net of the
    valuation premium equal linehaul_revenue_cents exactly."""
    total = (
        statement["booking_share_cents"]
        + statement["origin_share_cents"]
        + statement["hauling_share_cents"]
        + statement["destination_share_cents"]
        + (statement["van_line_share_cents"] - valuation_premium_cents)
    )
    assert total == statement["linehaul_revenue_cents"], (
        f"waterfall conservation violated: shares sum to {total}, "
        f"linehaul_revenue_cents is {statement['linehaul_revenue_cents']}"
    )


def assert_quality_score_invariants(agent: dict):
    """PRD section 2.9: quality_score starts at 100 and never falls below zero."""
    assert 0 <= agent["quality_score"] <= 100
