"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Standard system-managed fields carried by every primary resource
    (PRD §2.5): id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_rodeo(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["city"], str) and data["city"]
    assert is_iso8601_timestamp(data["entries_close_at"])
    assert data["posture"] in [
        "DRAFT", "ENTRIES_OPEN", "DRAW_LOCKED", "IN_PROGRESS",
        "COMPLETED", "SETTLED", "CANCELLED",
    ]
    assert isinstance(data["unclaimed_purse_cents"], int)
    assert data["unclaimed_purse_cents"] >= 0


def assert_rodeo_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["rodeo_id"])
    assert data["event_code"] in [
        "BAREBACK", "SADDLE_BRONC", "BULL_RIDING", "TIE_DOWN_ROPING",
        "STEER_WRESTLING", "TEAM_ROPING", "BARREL_RACING",
    ]
    assert data["discipline"] in ["ROUGH_STOCK", "TIMED"]
    assert 1 <= data["go_rounds"] <= 3
    assert data["entry_fee_cents"] >= 1000
    assert data["added_money_cents"] >= 0
    assert data["per_performance_slots"] >= 1
    assert 1 <= data["payout_places"] <= 4
    assert isinstance(data["drawn_rounds"], list)
    for g in data["drawn_rounds"]:
        assert isinstance(g, int)


def assert_performance(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["rodeo_id"])
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["arena"], str) and data["arena"]
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["ends_at"] > data["starts_at"]
    assert data["arena_capacity"] >= 1
    assert isinstance(data["sold_tickets"], int) and data["sold_tickets"] >= 0
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_contestant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["card_number"], str) and data["card_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in ["GOOD_STANDING", "SUSPENDED"]


def assert_stock_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["rodeo_id"])
    assert isinstance(data["contractor_name"], str) and data["contractor_name"]
    assert data["day_rate_cents"] >= 0
    assert data["per_out_fee_cents"] >= 0
    assert data["status"] in ["PROPOSED", "ACTIVE", "SETTLED", "TERMINATED"]
    assert isinstance(data["day_rate_total_cents"], int)
    assert isinstance(data["per_out_total_cents"], int)
    assert isinstance(data["settlement_cents"], int)
    assert data["settlement_basis"] in (None, "DAY_RATE", "PER_OUT")


def assert_stock_animal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["tag_number"], str) and data["tag_number"]
    assert data["event_code"] in [
        "BAREBACK", "SADDLE_BRONC", "BULL_RIDING", "TIE_DOWN_ROPING",
        "STEER_WRESTLING", "TEAM_ROPING", "BARREL_RACING",
    ]
    assert isinstance(data["welfare_out_count"], int)
    assert data["welfare_out_count"] >= 0
    assert data["status"] in ["AVAILABLE", "DRAWN", "COMPETED", "INJURED", "RETIRED"]


def assert_judge(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["card_number"], str) and data["card_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["certification"] in ["PRCA_CARD", "PRCA_GOLD"]


def assert_judge_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["judge_id"])
    assert is_valid_uuid(data["performance_id"])
    assert data["position"] in ["ARENA_1", "ARENA_2", "BARRIER", "TIMER"]


def assert_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["contestant_id"])
    assert is_valid_uuid(data["rodeo_event_id"])
    assert data["status"] in [
        "ENTERED", "WAITLISTED", "DRAWN", "TURNED_OUT",
        "DRAWN_OUT", "CANCELLED", "COMPETED",
    ]
    for field in (
        "entry_fee_cents", "purse_contribution_cents", "committee_retention_cents",
        "sanction_fee_cents", "fee_charges_cents", "contribution_charges_cents",
        "refunded_cents", "refunded_contribution_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must be non-negative"
    assert data["turn_out_reason"] in (None, "VOLUNTARY", "MEDICAL")
    assert "vet_report_id" in data
    assert data["vet_report_id"] is None or is_valid_uuid(data["vet_report_id"])


def assert_draw_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["entry_id"])
    assert is_valid_uuid(data["rodeo_event_id"])
    assert isinstance(data["go_round_number"], int) and data["go_round_number"] >= 1
    assert is_valid_uuid(data["performance_id"])
    assert "animal_id" in data
    assert data["animal_id"] is None or is_valid_uuid(data["animal_id"])
    assert isinstance(data["draw_position"], int) and data["draw_position"] >= 1
    assert data["status"] in ["PENDING", "COMPLETED", "RELEASED"]


def assert_run_result(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["draw_assignment_id"])
    assert is_valid_uuid(data["entry_id"])
    assert is_valid_uuid(data["rodeo_event_id"])
    assert is_valid_uuid(data["judge_id"])
    assert data["status"] in ["RECORDED", "VERIFIED", "AMENDED", "VOIDED"]
    assert data["outcome"] in ["QUALIFIED", "DISQUALIFIED", "NO_SCORE", "NO_TIME"]
    assert isinstance(data["qualified_flag"], bool)
    assert isinstance(data["disqualified_flag"], bool)
    assert "amendment_reason" in data
    assert "verified_at" in data


def assert_payout(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["rodeo_event_id"])
    assert data["computed_variant"] in ["PROVISIONAL", "FINAL"]
    assert data["status"] in ["PROVISIONAL", "FINAL", "DISBURSED"]
    assert isinstance(data["purse_cents"], int) and data["purse_cents"] >= 0
    assert isinstance(data["average_pool_cents"], int)
    assert isinstance(data["go_round_pools"], list)
    for pool in data["go_round_pools"]:
        assert isinstance(pool["go_round"], int) and pool["go_round"] >= 1
        assert isinstance(pool["pool_cents"], int) and pool["pool_cents"] >= 0
    assert isinstance(data["place_lines"], list)
    for line in data["place_lines"]:
        assert isinstance(line["scope"], str)
        assert line["scope"] == "AVERAGE" or line["scope"].startswith("GO_ROUND_")
        assert isinstance(line["place"], int) and line["place"] >= 1
        assert is_valid_uuid(line["contestant_id"])
        assert isinstance(line["amount_cents"], int)
        assert isinstance(line["tied_count"], int) and line["tied_count"] >= 1


def assert_vet_report(data: dict):
    """Vet reports are append-only: id and created_at only, no updated_at
    and no version keys (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "vet report must not carry updated_at"
    assert "version" not in data, "vet report must not carry version"
    assert data["subject_type"] in ["ANIMAL", "CONTESTANT"]
    assert data["disposition"] in ["CLEARED", "INJURED_TURNOUT", "RETIRED"]
    assert isinstance(data["findings"], str)
    assert isinstance(data["veterinarian_name"], str) and data["veterinarian_name"]


def assert_ticket_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["performance_id"])
    assert isinstance(data["section"], str) and data["section"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["quantity"] * data["unit_price_cents"]
    assert data["status"] in ["PAID", "REFUNDED"]


# --- Domain invariant checkers ------------------------------------------------

def place_lines_for(payout: dict, scope: str) -> list:
    """All place lines of a payout for one scope ('GO_ROUND_1', 'AVERAGE', ...)."""
    return [l for l in payout["place_lines"] if l["scope"] == scope]


def place_line_for(payout: dict, scope: str, contestant_id: str) -> dict:
    """The single place line a contestant holds within a scope."""
    matches = [
        l for l in payout["place_lines"]
        if l["scope"] == scope and l["contestant_id"] == contestant_id
    ]
    assert len(matches) == 1, (
        f"Expected exactly one line for {contestant_id} in {scope}, "
        f"got {len(matches)}"
    )
    return matches[0]
