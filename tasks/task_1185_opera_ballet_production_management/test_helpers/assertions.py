"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """All sixteen resource types share the four system-managed properties (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_partner_company(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["partner_kind"] in ("CO_PRODUCER", "RENTER")
    assert data["standing"] in ("GOOD", "WATCH", "BARRED")


def assert_production(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["work_type"] in ("OPERA", "BALLET")
    assert isinstance(data["build_budget_cents"], int) and data["build_budget_cents"] > 0
    assert isinstance(data["default_surtitle_language"], str)
    assert isinstance(data["build_cost_balance_cents"], int)
    assert isinstance(data["season_revenue_cents"], int)
    assert data["status"] in ("DESIGN", "BUILD", "REHEARSAL", "IN_REPERTORY", "ARCHIVED")


def assert_build_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["production_id"])
    assert data["item_kind"] in ("SET", "COSTUME", "PROP")
    assert isinstance(data["quoted_cost_cents"], int) and data["quoted_cost_cents"] > 0
    assert data["status"] in ("ORDERED", "BUILT", "DELIVERED", "IN_USE", "CANCELLED")


def assert_co_production_share(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["company_id"])
    assert 0 < data["share_percentage"] <= 100
    assert data["cost_split_method"] in ("GROSS_COST", "NET_REVENUE_SHARE")
    assert data["status"] in ("PROPOSED", "RATIFIED", "DISPUTED", "SETTLED")
    assert isinstance(data["accrued_revenue_share_cents"], int)


def assert_artist(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["discipline"] in (
        "PRINCIPAL_DANCER", "CORPS_DANCER", "SOPRANO", "TENOR", "CHORUS", "ORCHESTRA",
    )
    assert data["union_code"] in ("AGMA", "AFM", "EQUITY")


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["artist_id"])
    assert data["engagement_type"] in ("PRINCIPAL", "COVER", "CHORUS", "ORCHESTRA")
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0
    assert isinstance(data["weekly_hours_cap"], int) and data["weekly_hours_cap"] > 0
    assert isinstance(data["rest_floor_hours"], int) and data["rest_floor_hours"] > 0
    assert data["status"] in (
        "DRAFT", "OFFERED", "SIGNED", "ACTIVE", "CLOSED", "DECLINED", "TERMINATED",
    )


def assert_role(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["production_id"])
    assert isinstance(data["role_name"], str) and data["role_name"]
    assert data["voice_type"] in (
        "SOPRANO", "MEZZO", "TENOR", "BARITONE", "BASS",
        "DANCER_M", "DANCER_F", "NON_SINGING",
    )
    assert data["casting_status"] in ("UNFILLED", "PRINCIPAL_SET", "FULLY_CAST")


def assert_cast_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["role_id"])
    assert is_valid_uuid(data["contract_id"])
    assert data["slot"] in ("PRINCIPAL", "COVER_1", "COVER_2")
    assert data["status"] in ("PROPOSED", "CONFIRMED", "RELEASED", "WITHDRAWN")


def assert_rehearsal_room(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["kind"] in ("STUDIO", "STAGE", "ORCHESTRA_PIT")
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert isinstance(data["hourly_rate_cents"], int)


def assert_rehearsal_call(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["room_id"])
    assert data["call_type"] in (
        "BLOCKING", "STAGING", "ORCHESTRA_READ", "DANCE_CALL", "TECH", "DRESS",
    )
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert isinstance(data["confirmed_headcount"], int) and data["confirmed_headcount"] >= 0
    assert data["status"] in ("DRAFT", "PUBLISHED", "COMPLETED", "CANCELLED")


def assert_call_participant(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["call_id"])
    assert is_valid_uuid(data["contract_id"])
    assert data["status"] in (
        "INVITED", "WAIVER_PENDING", "CONFIRMED", "CHECKED_IN", "DECLINED", "REMOVED",
    )


def assert_stage_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["production_id"])
    assert data["slot_type"] in (
        "LOAD_IN", "LOAD_OUT", "TECH", "PERFORMANCE_SLOT", "DRESS_ON_STAGE",
    )
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["status"] in ("PLANNED", "LOCKED", "DONE", "CANCELLED")


def assert_performance(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["production_id"])
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["lifecycle_status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert data["sales_status"] in ("NOT_ON_SALE", "ON_SALE", "SALES_CLOSED")
    assert data["readiness_status"] in ("AWAITING_TECH", "TECH_READY", "CLEARED_FOR_AUDIENCE")
    assert isinstance(data["realized_revenue_cents"], int)


def assert_seat_inventory(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["performance_id"])
    assert data["section"] in ("STALLS", "BALCONY", "BOX", "GALLERY")
    assert isinstance(data["total_seats"], int) and data["total_seats"] > 0
    assert isinstance(data["seats_held"], int) and data["seats_held"] >= 0
    assert isinstance(data["seats_sold"], int) and data["seats_sold"] >= 0
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["current_price_cents"], int)


def assert_surtitle_track(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["production_id"])
    assert isinstance(data["language"], str) and data["language"]
    assert isinstance(data["cue_count"], int) and data["cue_count"] > 0
    assert data["status"] in ("DRAFT", "TRANSLATED", "CUES_LOCKED", "LIVE")


def assert_rental_offer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["renter_company_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["performances_count"], int) and data["performances_count"] > 0
    assert isinstance(data["per_performance_fee_cents"], int)
    assert isinstance(data["negotiation_rounds"], int) and data["negotiation_rounds"] >= 0
    assert data["status"] in (
        "DRAFT", "SENT", "COUNTERED", "ACCEPTED",
        "SETTLED", "DECLINED", "WITHDRAWN", "SUPERSEDED",
    )


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_build_budget_conservation(production: dict, committed_cents: int):
    """PRD §3.2: balance plus committed equals build_budget_cents at all times."""
    balance = production["build_cost_balance_cents"]
    budget = production["build_budget_cents"]
    assert balance + committed_cents == budget, (
        f"build budget conservation violated: balance {balance} + committed "
        f"{committed_cents} != budget {budget}"
    )


def assert_seat_conservation(inventory: dict):
    """PRD §3.8: availability is always total_seats minus seats_held minus seats_sold."""
    total = inventory["total_seats"]
    held = inventory["seats_held"]
    sold = inventory["seats_sold"]
    available = total - held - sold
    assert held + sold <= total, (
        f"seat conservation violated: held {held} + sold {sold} > total {total}"
    )
    assert available >= 0, "availability must never go negative"
    return available
