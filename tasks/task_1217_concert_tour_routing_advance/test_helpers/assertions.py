"""Entity assertions and domain invariant checkers (PRD §2.4 common fields, §3 workflows)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """PRD §2.4: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_tour(data: dict):
    _assert_common(data)
    assert isinstance(data["tour_name"], str) and data["tour_name"]
    assert isinstance(data["artist_name"], str) and data["artist_name"]
    assert isinstance(data["window_start_date"], str)
    assert isinstance(data["window_end_date"], str)
    assert data["status"] in ["PLANNING", "ROUTING", "ON_SALE", "IN_PROGRESS",
                              "SETTLEMENT_REVIEW", "CLOSED"]
    assert data["posture"] in ["OPEN", "RESTRICTED", "FROZEN"]
    for field in ("projected_gross_cents", "projected_cost_cents",
                  "settled_gross_cents", "settled_cost_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_market(data: dict):
    _assert_common(data)
    assert isinstance(data["market_code"], str) and data["market_code"]
    assert isinstance(data["metro_name"], str)
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert isinstance(data["radius_miles"], int)
    assert isinstance(data["exclusivity_window_days"], int)
    assert isinstance(data["territory_rank"], int)


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["venue_name"], str) and data["venue_name"]
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert isinstance(data["base_rent_cents"], int)
    assert isinstance(data["curfew_local_time"], str)
    assert isinstance(data["available_dates"], list)
    assert isinstance(data["booked_dates"], list)


def assert_routing_leg(data: dict):
    _assert_common(data)
    assert isinstance(data["from_market_id"], str)
    assert isinstance(data["to_market_id"], str)
    assert isinstance(data["travel_date"], str)
    assert isinstance(data["drive_miles"], int)
    assert isinstance(data["drive_minutes"], int)
    assert isinstance(data["crew_rest_required"], bool)
    assert isinstance(data["leg_index"], int)
    assert data["status"] in ["PLANNED", "LOCKED", "COMPLETED", "CANCELLED"]


def assert_show(data: dict):
    _assert_common(data)
    assert isinstance(data["market_id"], str)
    assert isinstance(data["venue_id"], str)
    assert isinstance(data["show_date"], str)
    assert isinstance(data["on_sale_at"], str)
    assert isinstance(data["avg_ticket_price_cents"], int)
    assert isinstance(data["tickets_sold"], int)
    assert data["status"] in ["HOLD_REQUESTED", "HOLD_PLACED", "CONFIRMED", "ADVANCED",
                              "PERFORMED", "SETTLED", "CANCELLED"]
    assert data["posture"] in ["OPEN", "GATED"]
    # capacity / gross_potential_cents are frozen at first hold acceptance (PRD §3.3);
    # before that they may be null.
    if data.get("capacity") is not None:
        assert isinstance(data["capacity"], int)
    if data.get("gross_potential_cents") is not None:
        assert isinstance(data["gross_potential_cents"], int)
    assert isinstance(data["projected_gross_cents"], int)
    assert isinstance(data["projected_cost_cents"], int)


def assert_promoter_hold(data: dict):
    _assert_common(data)
    assert isinstance(data["show_id"], str)
    assert isinstance(data["promoter_name"], str)
    assert isinstance(data["guarantee_cents"], int)
    assert isinstance(data["versus_pct"], int) and 0 <= data["versus_pct"] <= 100
    assert isinstance(data["counter_count"], int) and data["counter_count"] >= 0
    assert is_iso8601_timestamp(data["hold_expires_at"]), "hold_expires_at must be ISO 8601"
    assert data["status"] in ["PENDING", "COUNTERED", "ACCEPTED", "REJECTED",
                              "EXPIRED", "WITHDRAWN"]


def assert_advance_packet(data: dict):
    _assert_common(data)
    assert isinstance(data["show_id"], str)
    assert data["tech_rider_status"] in ["PENDING", "SUBMITTED", "APPROVED", "REJECTED"]
    assert data["hospitality_status"] in ["PENDING", "SUBMITTED", "APPROVED", "REJECTED"]
    assert data["immigration_status"] in ["PENDING", "SUBMITTED", "APPROVED", "REJECTED",
                                          "NOT_REQUIRED"]
    assert isinstance(data["daysheet_issued"], bool)
    assert isinstance(data["packet_revision"], int)


def assert_budget_line(data: dict):
    _assert_common(data)
    assert isinstance(data["show_id"], str)
    assert data["category"] in ["VENUE_RENT", "CREW", "TRANSPORT", "BACKLINE",
                                "MARKETING", "HOSPITALITY", "INSURANCE", "MISC"]
    assert isinstance(data["description"], str)
    assert isinstance(data["estimated_cents"], int)
    if data.get("actual_cents") is not None:
        assert isinstance(data["actual_cents"], int)
    assert isinstance(data["is_committed"], bool)


def assert_marketing_spend(data: dict):
    _assert_common(data)
    assert isinstance(data["show_id"], str)
    assert data["channel"] in ["RADIO", "SOCIAL", "OOH", "PRINT", "INFLUENCER"]
    assert isinstance(data["spend_cents"], int)
    assert isinstance(data["flight_start_date"], str)
    assert isinstance(data["flight_end_date"], str)
    assert isinstance(data["attributed_ticket_sales"], int)
    # PRD §3.6: a line with zero attributed sales has a null cpa_cents
    if data["attributed_ticket_sales"] == 0:
        assert data.get("cpa_cents") is None
    else:
        assert isinstance(data["cpa_cents"], int)


def assert_settlement(data: dict):
    _assert_common(data)
    assert isinstance(data["show_id"], str)
    assert data["status"] in ["DRAFT", "SUBMITTED", "VERIFIED", "PAID"]
    if data["status"] != "DRAFT":
        assert isinstance(data["box_office_gross_cents"], int)
        assert isinstance(data["taxes_cents"], int)
        assert isinstance(data["facility_fees_cents"], int)
        assert isinstance(data["promoter_expenses_cents"], int)
        assert isinstance(data["artist_share_cents"], int)
        assert isinstance(data["variance_cents"], int)
        assert data["variance_flag"] in ["NONE", "MINOR", "MATERIAL"]


def assert_compliance_hold(data: dict):
    _assert_common(data)
    assert isinstance(data["tour_id"], str)
    assert data["hold_kind"] in ["RADIUS_CONFLICT", "VENUE_DOUBLE_BOOK", "REST_VIOLATION",
                                 "BUDGET_OVERRUN", "ADVANCE_OVERDUE"]
    assert data["severity"] in ["STANDARD", "CRITICAL"]
    assert isinstance(data["reason"], str)
    assert data["status"] in ["ACTIVE", "RESOLVED"]
