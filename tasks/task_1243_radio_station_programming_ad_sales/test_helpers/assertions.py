"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
DAYPARTS = ["MORNING_DRIVE", "MIDDAY", "AFTERNOON_DRIVE", "EVENING", "OVERNIGHT"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_station(data: dict):
    _assert_common(data)
    assert isinstance(data["call_sign"], str) and data["call_sign"]
    assert isinstance(data["market_name"], str) and data["market_name"]
    assert isinstance(data["default_share_fallback"], (int, float))


def assert_clock(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["applies_weekdays"], list) and len(data["applies_weekdays"]) >= 1
    assert all(w in WEEKDAYS for w in data["applies_weekdays"])
    assert isinstance(data["slots"], list)
    for slot in data["slots"]:
        assert slot["slot_type"] in ["MUSIC", "SPOT_BREAK", "LIVE_READ_WINDOW"]
        assert 0 <= slot["hour"] <= 23
        assert isinstance(slot["capacity_units"], int)
        assert isinstance(slot["capacity_seconds"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]


def assert_music_category(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["min_song_separation_min"], int)
    assert isinstance(data["min_artist_separation_min"], int)
    assert isinstance(data["max_spins_per_day"], int)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_song(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert is_valid_uuid(data.get("category_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["artist"], str) and data["artist"]
    assert isinstance(data["duration_sec"], int) and data["duration_sec"] > 0
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_ratings_book(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert isinstance(data["survey_name"], str) and data["survey_name"]
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["period_end"] >= data["period_start"]
    assert data["share_value"] > 0
    assert data["status"] in ["DRAFT", "PUBLISHED", "SUPERSEDED"]


def assert_rate_card_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert data["daypart"] in DAYPARTS
    assert isinstance(data["weekday_set"], list) and len(data["weekday_set"]) >= 1
    assert all(w in WEEKDAYS for w in data["weekday_set"])
    assert isinstance(data["base_rate_cents"], int) and data["base_rate_cents"] > 0
    assert isinstance(data["min_rate_cents"], int) and data["min_rate_cents"] > 0
    assert data["min_rate_cents"] <= data["base_rate_cents"]
    assert data["effective_to"] >= data["effective_from"]
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_clearance(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert isinstance(data["provider"], str) and data["provider"]
    assert isinstance(data["weekday_set"], list) and len(data["weekday_set"]) >= 1
    assert all(w in WEEKDAYS for w in data["weekday_set"])
    assert 0 <= data["start_hour"] <= 23
    assert isinstance(data["duration_hours"], int) and data["duration_hours"] >= 1
    assert data["start_hour"] + data["duration_hours"] <= 24
    assert isinstance(data["barter_avails_per_hour"], int) and data["barter_avails_per_hour"] >= 1
    assert data["status"] in ["PENDING", "CLEARED", "DISAFFIRMED"]


def assert_trade_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] > 0
    assert data["trade_ratio"] > 0
    assert isinstance(data["consumed_cents"], int)
    assert isinstance(data["adjustments_cents"], int)
    assert isinstance(data["available_cents"], int)
    assert data["status"] in ["ACTIVE", "EXHAUSTED", "SUSPENDED", "CLOSED"]
    assert_trade_agreement_invariants(data)


def assert_trade_agreement_invariants(data: dict):
    """Ledger-derived balance invariants (PRD §3.3)."""
    expected = (
        data["credit_limit_cents"] - data["consumed_cents"] + data["adjustments_cents"]
    )
    assert data["available_cents"] == expected, (
        f"available_cents {data['available_cents']} != limit - consumed + adjustments "
        f"({expected})"
    )
    assert data["available_cents"] >= 0, "available_cents may never go negative"


def assert_trade_ledger_entry(data: dict):
    # Append-only: carries ONLY id + created_at among the system fields.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only entry must not carry updated_at"
    assert "version" not in data, "append-only entry must not carry version"
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert data["entry_kind"] in ["DEBIT", "REVERSAL", "ADJUSTMENT"]
    assert isinstance(data["amount_cents"], int)
    if data["entry_kind"] in ("DEBIT", "REVERSAL"):
        assert data["amount_cents"] > 0
    assert isinstance(data["entry_seq"], int) and data["entry_seq"] >= 1


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert isinstance(data["advertiser_name"], str) and data["advertiser_name"]
    assert data["order_kind"] in ["CASH", "TRADE"]
    if data["order_kind"] == "TRADE":
        assert is_valid_uuid(data.get("trade_agreement_id", ""))
    else:
        assert data.get("trade_agreement_id") is None
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data["flight_end"] >= data["flight_start"]
    assert data["rate_tier"] in ["FIXED", "PREEMPTIBLE"]
    assert data["reprice_policy"] in ["LOCKED_AT_BOOKING", "REPRICED_AT_AFFIDAVIT"]
    assert isinstance(data["daypart_targets"], list) and len(data["daypart_targets"]) >= 1
    dayparts = [t["daypart"] for t in data["daypart_targets"]]
    assert len(set(dayparts)) == len(dayparts), "dayparts unique within daypart_targets"
    assert all(t["daypart"] in DAYPARTS and t["units"] >= 1 for t in data["daypart_targets"])
    assert isinstance(data["units_scheduled"], int) and data["units_scheduled"] >= 0
    assert isinstance(data["units_aired"], int) and data["units_aired"] >= 0
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "ACTIVE", "COMPLETED", "CANCELLED",
    ]


def assert_daily_log(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert isinstance(data["log_date"], str)
    assert data.get("clock_id") is None or is_valid_uuid(data["clock_id"])
    assert data["posture"] in [
        "DRAFT", "LOCKED", "AS_RUN", "RECONCILING", "RECONCILED",
        "AFFIDAVIT_ISSUED", "CLOSED",
    ]
    assert isinstance(data["unresolved_discrepancy_count"], int)
    assert data["unresolved_discrepancy_count"] >= 0
    assert isinstance(data["music_placements"], list)
    for i, placement in enumerate(data["music_placements"], start=1):
        assert is_valid_uuid(placement["song_id"])
        assert 0 <= placement["hour"] <= 23
        assert placement["placed_seq"] == i, "placed_seq is per-log monotonic from 1"


def assert_spot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("log_id", ""))
    assert data["daypart"] in DAYPARTS
    assert 0 <= data["hour"] <= 23
    assert data["duration_sec"] in [15, 30, 60]
    assert isinstance(data["air_date"], str)
    assert isinstance(data["unit_rate_cents"], int) and data["unit_rate_cents"] > 0
    assert data["status"] in ["SCHEDULED", "AIRED", "MAKE_GOOD_PENDING", "RESOLVED", "CANCELLED"]
    if data["status"] == "MAKE_GOOD_PENDING":
        assert data.get("make_good_reason") in ["PREEMPTED", "MISSED"]


def assert_barter_avail(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert is_valid_uuid(data.get("clearance_id", ""))
    assert is_valid_uuid(data.get("log_id", ""))
    assert isinstance(data["air_date"], str)
    assert 0 <= data["hour"] <= 23
    assert data["duration_sec"] in [15, 30, 60]
    assert data["status"] in ["SCHEDULED", "AIRED", "MISSED", "CANCELLED"]


def assert_endorsement_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert isinstance(data["advertiser_name"], str) and data["advertiser_name"]
    assert isinstance(data["host_name"], str) and data["host_name"]
    assert isinstance(data["program_weekdays"], list) and len(data["program_weekdays"]) >= 1
    assert all(w in WEEKDAYS for w in data["program_weekdays"])
    assert 0 <= data["program_start_hour"] <= 23
    assert data["program_start_hour"] < data["program_end_hour"] <= 24
    assert isinstance(data["reads_per_week"], int) and data["reads_per_week"] >= 1
    assert data["end_date"] >= data["start_date"]
    assert isinstance(data["contracted_reads_total"], int) and data["contracted_reads_total"] >= 0
    assert isinstance(data["reads_completed"], int) and data["reads_completed"] >= 0
    assert data["status"] in ["DRAFT", "ACTIVE", "COMPLETED", "BREACHED", "CANCELLED"]


def assert_live_read(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_valid_uuid(data.get("log_id", ""))
    assert isinstance(data["air_date"], str)
    assert 0 <= data["hour"] <= 23
    assert data["duration_sec"] in [30, 60]
    assert data["status"] in ["SCHEDULED", "AIRED", "MAKE_GOOD_PENDING", "RESOLVED", "CANCELLED"]


def assert_discrepancy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert is_valid_uuid(data.get("log_id", ""))
    assert data["discrepancy_kind"] in ["MISSED_SPOT", "MISSED_READ", "UNFILLED_BARTER"]
    assert data["status"] in ["UNRESOLVED", "RESOLVED", "WAIVED"]
    # The kind-matched foreign key is set iff the kind calls for it (PRD §3.7).
    assert (data.get("spot_id") is not None) == (data["discrepancy_kind"] == "MISSED_SPOT")
    assert (data.get("live_read_id") is not None) == (data["discrepancy_kind"] == "MISSED_READ")
    if data["discrepancy_kind"] != "UNFILLED_BARTER":
        assert data.get("barter_avail_id") is None
    if data["status"] == "UNRESOLVED":
        assert data.get("resolved_by_user_id") is None


def assert_remote_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", ""))
    assert isinstance(data["event_name"], str) and data["event_name"]
    assert isinstance(data["sponsor_name"], str) and data["sponsor_name"]
    assert isinstance(data["event_date"], str)
    assert isinstance(data["spot_units_promised"], int) and data["spot_units_promised"] >= 1
    assert isinstance(data["package_price_cents"], int) and data["package_price_cents"] > 0
    assert isinstance(data["spots_delivered"], int) and data["spots_delivered"] >= 0
    assert data["status"] in ["PLANNED", "CONFIRMED", "DELIVERED", "DEFAULTED", "CANCELLED"]
