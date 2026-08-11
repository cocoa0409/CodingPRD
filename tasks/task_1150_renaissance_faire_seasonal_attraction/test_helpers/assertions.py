"""Entity assertions and domain invariant checkers (PRD §2.4, §2.10, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Every resource carries the §2.4 system-managed field set."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_season(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ["PLANNING", "BUILD", "OPEN", "STRIKE", "CLOSED"]
    assert data["readiness_posture"] in ["BLOCKED", "CONDITIONAL", "READY"]
    assert isinstance(data["daily_capacity"], int) and data["daily_capacity"] >= 1
    assert isinstance(data["group_min_size"], int) and data["group_min_size"] >= 2
    assert isinstance(data["volunteer_confirmed_hours"], (int, float))
    assert isinstance(data["outstanding_admissions"], int)
    assert isinstance(data["season_weeks"], int) and data["season_weeks"] >= 1


def assert_faire_day(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert data["status"] in [
        "SCHEDULED", "OPEN_FOR_SALES", "WEATHER_HOLD",
        "OPERATING", "COMPLETED", "CANCELLED_WEATHER",
    ]
    assert isinstance(data["tickets_sold_count"], int)


def assert_performer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["stage_name"], str) and data["stage_name"]
    assert data["act_type"] in ["MUSIC", "COMBAT", "COMEDY", "ACROBATICS", "ROVING"]
    assert isinstance(data["base_day_rate_cents"], int) and data["base_day_rate_cents"] >= 0


def assert_cast_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert is_valid_uuid(data.get("performer_id", ""))
    assert data["status"] in [
        "DRAFT", "OFFERED", "COUNTERED", "ACCEPTED",
        "REHEARSING", "PERFORMING", "COMPLETED", "TERMINATED",
    ]
    assert isinstance(data["offered_day_rate_cents"], int)
    assert isinstance(data["negotiation_round"], int) and data["negotiation_round"] >= 0
    assert isinstance(data["accrued_payout_cents"], int)
    assert isinstance(data["completed_rehearsal_hours"], (int, float))


def assert_rehearsal_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data["stage_name"], str) and data["stage_name"]
    assert data["status"] in ["SCHEDULED", "ATTENDED", "NO_SHOW", "CANCELLED"]
    assert isinstance(data["hours_credit"], (int, float))


def assert_vendor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert data["category"] in ["FOOD", "BEVERAGE", "ARTISAN", "GAMES"]


def assert_vendor_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert is_valid_uuid(data.get("vendor_id", ""))
    assert data["status"] in [
        "JURY_REVIEW", "JURIED_IN", "JURIED_OUT",
        "WAITLISTED", "APPEALED", "WITHDRAWN",
    ]
    assert isinstance(data["booth_size_sqft"], int) and data["booth_size_sqft"] >= 1
    assert data["requested_location_tier"] in ["PRIME", "STANDARD", "MEADOW"]
    assert isinstance(data["appeal_used"], bool)


def assert_booth_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data["booth_site"], str) and data["booth_site"]
    assert data["status"] in ["RESERVED", "CONFIRMED", "SUSPENDED", "RELEASED", "SETTLED"]
    assert isinstance(data["provisional_fee_cents"], int)
    assert isinstance(data["weather_credit_cents"], int)


def assert_food_permit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["status"] in [
        "APPLIED", "ISSUED", "AWAITING_REINSPECTION",
        "FAILED_FINAL", "REVOKED", "EXPIRED",
    ]
    assert isinstance(data["inspection_attempts"], int) and data["inspection_attempts"] >= 0


def assert_ticket_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert isinstance(data["buyer_email"], str) and data["buyer_email"]
    assert data["order_type"] in ["DAY", "SEASON", "GROUP"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    assert isinstance(data["retained_cents"], int)
    assert data["payment_status"] in ["UNPAID", "PAID", "PARTIALLY_REFUNDED", "REFUNDED"]
    assert data["redemption_status"] in [
        "UNREDEEMED", "PARTIALLY_REDEEMED", "FULLY_REDEEMED", "RAINCHECKED", "VOID",
    ]


def assert_ticket(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert data["ticket_type"] in ["DAY", "SEASON"]
    assert data["status"] in ["VALID", "REDEEMED", "RAINCHECKED", "VOID", "EXPIRED"]


def assert_rain_check(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert is_valid_uuid(data.get("ticket_id", ""))
    assert is_valid_uuid(data.get("issued_for_day_id", ""))
    assert data["status"] in ["ISSUED", "REDEEMED", "EXPIRED"]


def assert_volunteer_shift(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert is_valid_uuid(data.get("faire_day_id", ""))
    assert isinstance(data["volunteer_handle"], str) and data["volunteer_handle"]
    assert data["role"] in ["GATE", "PARKING", "TAVERN", "INFO", "BACKSTAGE"]
    assert data["status"] in ["SIGNED_UP", "CONFIRMED", "WORKED", "NO_SHOW", "CANCELLED"]
    assert isinstance(data["hours"], (int, float))


def assert_conduct_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert data["category"] in ["COSTUME_POLICY", "WEAPON_UNTIED", "BEHAVIOR", "VENDOR_CONDUCT"]
    assert isinstance(data["subject_description"], str) and data["subject_description"]
    assert data["status"] in ["REPORTED", "UPHELD", "DISMISSED"]
    assert data["sanction"] in ["NONE", "BAN_GUEST", "REVOKE_PERMIT"]


def assert_build_task(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("season_id", ""))
    assert data["phase"] in ["BUILD", "STRIKE"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ["PENDING", "IN_PROGRESS", "DONE"]
    assert isinstance(data["depends_on_task_ids"], list)


def assert_order_money_invariant(order: dict):
    """PRD §2.10: refunded_cents + retained_cents == total_cents at all times."""
    assert order["refunded_cents"] + order["retained_cents"] == order["total_cents"], (
        f"Money invariant violated: {order['refunded_cents']} + "
        f"{order['retained_cents']} != {order['total_cents']}"
    )


def assert_outstanding_admissions(season: dict, expected: int):
    """PRD §2.10: outstanding_admissions equals VALID tickets + ISSUED rain checks."""
    assert season["outstanding_admissions"] == expected, (
        f"Expected outstanding_admissions == {expected}, "
        f"got {season['outstanding_admissions']}"
    )
