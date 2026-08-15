"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_timestamp_instant(value: str, expected_prefix: str):
    """Assert a domain timestamp denotes the expected instant. Comparison is made
    on the second-resolution prefix so fractional-digit formatting (PRD §2.4)
    does not affect the outcome."""
    assert isinstance(value, str) and value.startswith(expected_prefix), (
        f"Expected timestamp instant {expected_prefix!r}, got {value!r}"
    )


def assert_dock_berth(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["max_length_m"], (int, float))
    assert isinstance(data["max_beam_m"], (int, float))
    assert isinstance(data["max_depth_m"], (int, float))
    assert isinstance(data["daily_rate_cents"], int)
    assert data["daily_rate_cents"] >= 0


def assert_vessel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["imo_number"], str) and data["imo_number"]
    assert isinstance(data["length_m"], (int, float))
    assert isinstance(data["beam_m"], (int, float))
    assert isinstance(data["draft_m"], (int, float))
    assert isinstance(data["owner_user_id"], str) and data["owner_user_id"]


def assert_subcontractor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["trade_codes"], list)
    assert isinstance(data["day_rate_cents"], int)
    assert data["day_rate_cents"] >= 0


def assert_repair_project(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "BID_SUBMITTED", "CONTRACTED", "IN_DOCK",
        "WORK_COMPLETE", "DELIVERED", "CLOSED",
    ]
    assert isinstance(data["vessel_id"], str)
    assert isinstance(data["dock_id"], str)
    assert isinstance(data["contract_delivery_date"], str)
    assert isinstance(data["bid_total_cents"], int)
    assert isinstance(data["critical_path_days"], int)
    assert isinstance(data["provisional_ld_cents"], int)
    for nullable in (
        "awarded_price_cents", "contracted_price_cents", "ld_daily_rate_cents",
        "actual_dock_in_utc", "forecast_delivery_utc", "liquidated_damages_cents",
        "delivered_at_utc", "warranty_end_utc",
    ):
        assert nullable in data, f"missing field {nullable}"


def assert_dock_reservation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["BOOKED", "ACTIVE", "RELEASED", "CANCELLED"]
    assert isinstance(data["project_id"], str)
    assert isinstance(data["dock_id"], str)
    assert isinstance(data["dockage_fee_cents"], int)
    assert data["dockage_fee_cents"] >= 0


def assert_work_item(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PLANNED", "IN_PROGRESS", "COMPLETE", "CANCELLED"]
    assert data["pricing_mode"] in ["LUMP_SUM", "TIME_AND_MATERIALS"]
    assert data["origin_kind"] in ["BASE_SPEC", "CHANGE_ORDER", "WARRANTY_REWORK"]
    assert isinstance(data["line_total_cents"], int)
    assert isinstance(data["duration_days"], int)
    assert data["duration_days"] >= 1
    assert isinstance(data["depends_on_ids"], list)
    assert isinstance(data["ready"], bool)


def assert_change_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["UNDER_REVIEW", "APPROVED", "REJECTED", "WITHDRAWN"]
    assert isinstance(data["proposed_cost_cents"], int)
    assert isinstance(data["requires_owner_countersign"], bool)
    assert isinstance(data["schedule_delta_days"], int)
    assert isinstance(data["proposed_by_user_id"], str)


def assert_survey(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "PASSED", "FAILED"]
    assert data["survey_type"] in [
        "CLASS_RENEWAL", "CLASS_INTERMEDIATE", "USCG_INSPECTION", "LOAD_LINE",
    ]
    assert isinstance(data["surveyor_user_id"], str)


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["APPLIED", "GRANTED", "SUSPENDED", "CLOSED", "EXPIRED"]
    assert data["permit_type"] in [
        "HOT_WORK", "PAINT_SPRAY", "BALLAST_DISCHARGE", "HULL_BLASTING",
    ]


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["FILED", "ACCEPTED", "DENIED", "CLOSED"]
    assert isinstance(data["project_id"], str)
    assert isinstance(data["work_item_id"], str)
    assert isinstance(data["filed_by_user_id"], str)


def assert_contract_price_invariant(project: dict, approved_change_orders: list):
    """PRD §3.5: contracted price is the awarded price plus the sum of
    proposed_cost_cents over the project's APPROVED change orders (credit
    orders, whose proposed cost is negative, reduce the contract price)."""
    expected = project["awarded_price_cents"] + sum(
        co["proposed_cost_cents"] for co in approved_change_orders
    )
    assert project["contracted_price_cents"] == expected, (
        f"contracted_price_cents {project['contracted_price_cents']} != "
        f"awarded {project['awarded_price_cents']} + approved deltas "
        f"{[co['proposed_cost_cents'] for co in approved_change_orders]}"
    )
