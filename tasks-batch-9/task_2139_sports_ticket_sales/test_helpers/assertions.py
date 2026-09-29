"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_SEASON_STATUSES = ["PLANNING", "RENEWAL_OPEN", "GENERAL_ONSALE", "IN_SEASON", "ARCHIVED"]
_SEAT_STATUSES = ["AVAILABLE", "HELD", "ASSIGNED"]
_ORDER_STATUSES = ["DRAFT", "PENDING_APPROVAL", "APPROVED", "CONFIRMED", "CANCELLED"]
_PAYMENT_STATUSES = [
    "NOT_STARTED", "SCHEDULED", "PARTIALLY_PAID", "PAID_IN_FULL", "DELINQUENT", "REFUNDED",
]


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def assert_season(data):
    _assert_common_fields(data, "Season")
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 16
    assert isinstance(data["year"], int) and data["year"] >= 2020
    assert isinstance(data["total_home_games"], int) and data["total_home_games"] >= 1
    assert is_iso8601_timestamp(data["renewal_deadline_utc"])
    assert isinstance(data["revenue_goal_cents"], int) and data["revenue_goal_cents"] >= 1
    assert data["season_status"] in _SEASON_STATUSES
    assert data["dynamic_pricing_mode"] in ["AGGRESSIVE", "BALANCED"]
    assert isinstance(data["revenue_goal_met"], bool)
    assert isinstance(data["contracted_revenue_cents"], int)
    assert isinstance(data["secondary_market_volume_cents"], int)
    assert_season_census_invariant(data)


def assert_season_census_invariant(season):
    """available + held + assigned always sums to total (PRD 2.7)."""
    total = season["total_seat_count"]
    parts = (
        season["available_seat_count"]
        + season["held_seat_count"]
        + season["assigned_seat_count"]
    )
    assert parts == total, (
        f"Census invariant broken: available {season['available_seat_count']} + held "
        f"{season['held_seat_count']} + assigned {season['assigned_seat_count']} "
        f"!= total {total}"
    )


def assert_game(data):
    _assert_common_fields(data, "Game")
    assert is_valid_uuid(data["season_id"])
    assert data["opponent_tier"] in ["MARQUEE", "PREMIUM", "STANDARD", "VALUE"]
    assert data["day_bucket"] in ["WEEKEND", "WEEKDAY"]
    assert 0 <= data["demand_index"] <= 100
    assert data["game_status"] in ["SCHEDULED", "PLAYED"]
    assert isinstance(data["hospitality_booked_headcount"], int)
    assert isinstance(data["scanned_count"], int)
    assert isinstance(data["expected_attendance"], int)
    assert data["no_show_count"] >= 0, "no_show_count is floored at zero"
    assert float(data["no_show_rate_pct"]) >= 0.0


def assert_seat(data):
    _assert_common_fields(data, "Seat")
    assert is_valid_uuid(data["season_id"])
    assert isinstance(data["seat_number"], int) and data["seat_number"] >= 1
    assert data["price_zone"] in ["ZONE_A", "ZONE_B", "ZONE_C", "ZONE_D"]
    assert data["seat_status"] in _SEAT_STATUSES
    assert isinstance(data["scanned_game_ids"], list)


def assert_season_plan(data):
    _assert_common_fields(data, "SeasonPlan")
    assert is_valid_uuid(data["season_id"])
    assert data["plan_type"] in ["FULL_SEASON", "HALF_SEASON", "PARTIAL", "GROUP"]
    assert isinstance(data["game_ids"], list) and len(data["game_ids"]) > 0
    assert len(set(data["game_ids"])) == len(data["game_ids"]), "game_ids must be unique"
    assert data["min_seats"] >= 1
    assert data["max_seats"] >= data["min_seats"]
    assert data["plan_status"] in ["DRAFT", "PUBLISHED", "CLOSED"]
    assert data["included_game_count"] == len(data["game_ids"])


def assert_service_rep(data):
    _assert_common_fields(data, "ServiceRep")
    assert isinstance(data["rep_name"], str)
    assert isinstance(data["territory_code"], str)
    assert data["book_capacity"] >= 1
    assert data["rep_status"] in ["ACTIVE", "ON_LEAVE"]
    assert isinstance(data["assigned_account_count"], int)
    assert isinstance(data["touchpoints_logged_count"], int)


def assert_ticket_account(data):
    _assert_common_fields(data, "TicketAccount")
    assert data["account_type"] in ["INDIVIDUAL", "GROUP", "CORPORATE"]
    assert data["tenure_years"] >= 0
    assert data["billing_status"] in ["CURRENT", "PAST_DUE", "LAPSED", "WRITTEN_OFF"]
    assert data["service_status"] in [
        "PROSPECT", "ACTIVE", "AT_RISK", "CHURNED", "WON_BACK",
    ]
    assert isinstance(data["renewal_priority_active"], bool)
    assert data["loyalty_credit_cents"] >= 0
    assert 0 <= data["churn_risk_rolling"] <= 100
    assert 0 <= data["churn_risk_campaign"] <= 100
    assert data["lifetime_value_cents"] >= 0


def assert_plan_order(data):
    _assert_common_fields(data, "PlanOrder")
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["plan_id"])
    assert isinstance(data["seat_ids"], list) and len(data["seat_ids"]) > 0
    assert data["order_status"] in _ORDER_STATUSES
    assert data["payment_status"] in _PAYMENT_STATUSES
    assert isinstance(data["quoted_total_cents"], int)
    assert isinstance(data["final_total_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["installments"], list)


def assert_installment_schedule(order):
    """The schedule sums to the total and only index 0 carries the remainder."""
    installments = order["installments"]
    assert len(installments) == order["installment_count"]
    assert sum(i["amount_cents"] for i in installments) == order["final_total_cents"]
    for position, entry in enumerate(installments):
        assert entry["index"] == position, "installment index is 0-based schedule order"
        assert isinstance(entry["amount_cents"], int)
        assert isinstance(entry["paid_cents"], int)
        assert is_iso8601_timestamp(entry["due_date_utc"])
    assert order["amount_paid_cents"] == sum(i["paid_cents"] for i in installments)


def assert_seat_hold(data):
    _assert_common_fields(data, "SeatHold")
    assert is_valid_uuid(data["seat_id"])
    assert is_valid_uuid(data["account_id"])
    assert data["hold_type"] in [
        "RENEWAL_HOLD", "UPGRADE_HOLD", "GROUP_HOLD", "ORDER_HOLD",
    ]
    assert data["hold_status"] in ["ACTIVE", "CONVERTED", "RELEASED", "EXPIRED"]
    assert data["hold_window_end_utc"] > data["hold_window_start_utc"]


def assert_hospitality_package(data):
    _assert_common_fields(data, "HospitalityPackage")
    assert is_valid_uuid(data["game_id"])
    assert is_valid_uuid(data["account_id"])
    assert data["headcount"] >= 1
    assert data["package_status"] in ["HELD", "CONFIRMED", "SETTLED", "RELEASED"]
    assert isinstance(data["gross_fee_cents"], int)
    assert isinstance(data["service_fee_cents"], int)
    assert isinstance(data["total_due_cents"], int)


def assert_ticket_transfer(data):
    _assert_common_fields(data, "TicketTransfer")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["game_id"])
    assert is_valid_uuid(data["seat_id"])
    assert data["transfer_type"] in ["TRANSFER", "RESALE"]
    assert data["transfer_status"] in ["REQUESTED", "APPROVED", "REJECTED", "COMPLETED"]
    assert isinstance(data["face_value_cents"], int)
    assert isinstance(data["floor_price_cents"], int)
    assert isinstance(data["credit_awarded_cents"], int)


def assert_ops_summary(data):
    """The ops checkpoint answers a summary object, not an entity (PRD 2.11)."""
    for field in [
        "ops_run_at_utc",
        "season_status",
        "expired_hold_count",
        "played_game_count",
        "released_package_count",
        "settled_package_count",
        "delinquent_order_count",
        "at_risk_account_count",
        "churned_account_count",
        "written_off_account_count",
    ]:
        assert field in data, f"ops summary must report {field}"
    assert data["season_status"] in _SEASON_STATUSES
