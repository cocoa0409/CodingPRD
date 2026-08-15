"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_station_payload(**overrides) -> dict:
    defaults = {
        "call_sign": _uniq("K"),
        "market_name": "Metro",
        "default_share_fallback": 2.5,
    }
    defaults.update(overrides)
    return defaults


def create_clock_payload(station_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "name": _uniq("clock"),
        "applies_weekdays": ["MON"],
        "slots": [
            {
                "slot_type": "SPOT_BREAK",
                "hour": 6,
                "capacity_units": 10,
                "capacity_seconds": 600,
            }
        ],
    }
    defaults.update(overrides)
    return defaults


def create_music_category_payload(station_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "code": _uniq("CAT"),
        "min_song_separation_min": 0,
        "min_artist_separation_min": 0,
        "max_spins_per_day": 5,
    }
    defaults.update(overrides)
    return defaults


def create_song_payload(station_id, category_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "category_id": category_id,
        "title": _uniq("Song"),
        "artist": "ArtA",
        "duration_sec": 200,
    }
    defaults.update(overrides)
    return defaults


def create_ratings_book_payload(station_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "survey_name": _uniq("Survey"),
        "period_start": "2026-01-01",
        "period_end": "2026-06-30",
        "share_value": 3.0,
    }
    defaults.update(overrides)
    return defaults


def create_rate_card_entry_payload(station_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "daypart": "MORNING_DRIVE",
        "weekday_set": ["MON"],
        "base_rate_cents": 1000,
        "min_rate_cents": 100,
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_clearance_payload(station_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "program_name": _uniq("Show"),
        "provider": "NetCo",
        "weekday_set": ["MON"],
        "start_hour": 10,
        "duration_hours": 2,
        "barter_avails_per_hour": 1,
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_trade_agreement_payload(station_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "vendor_name": _uniq("Vendor"),
        "credit_limit_cents": 100000,
        "trade_ratio": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_ledger_entry_payload(**overrides) -> dict:
    defaults = {
        "entry_kind": "ADJUSTMENT",
        "amount_cents": 1000,
        "note": "manual adjustment",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(station_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "advertiser_name": _uniq("Adv"),
        "order_kind": "CASH",
        "flight_start": "2026-05-01",
        "flight_end": "2026-05-31",
        "rate_tier": "FIXED",
        "reprice_policy": "LOCKED_AT_BOOKING",
        "daypart_targets": [{"daypart": "MORNING_DRIVE", "units": 1}],
    }
    defaults.update(overrides)
    return defaults


def create_log_payload(station_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "log_date": "2026-05-04",
    }
    defaults.update(overrides)
    return defaults


def create_spot_payload(order_id, log_id, expected_order_version, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "log_id": log_id,
        "daypart": "MORNING_DRIVE",
        "hour": 6,
        "duration_sec": 60,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_barter_avail_payload(clearance_id, log_id, expected_clearance_version, **overrides) -> dict:
    defaults = {
        "clearance_id": clearance_id,
        "log_id": log_id,
        "hour": 10,
        "duration_sec": 60,
        "expected_clearance_version": expected_clearance_version,
    }
    defaults.update(overrides)
    return defaults


def create_endorsement_contract_payload(station_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "advertiser_name": _uniq("AdvE"),
        "host_name": _uniq("Host"),
        "program_weekdays": ["WED"],
        "program_start_hour": 6,
        "program_end_hour": 9,
        "reads_per_week": 2,
        "start_date": "2026-05-01",
        "end_date": "2026-05-31",
    }
    defaults.update(overrides)
    return defaults


def create_live_read_payload(contract_id, log_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "log_id": log_id,
        "hour": 7,
    }
    defaults.update(overrides)
    return defaults


def create_remote_event_payload(station_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "event_name": _uniq("Remote"),
        "sponsor_name": _uniq("Sponsor"),
        "event_date": "2026-05-01",
        "spot_units_promised": 1,
        "package_price_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def as_run_import_payload(aired_spot_ids=None, aired_live_read_ids=None, aired_barter_avail_ids=None) -> dict:
    return {
        "aired_spot_ids": list(aired_spot_ids or []),
        "aired_live_read_ids": list(aired_live_read_ids or []),
        "aired_barter_avail_ids": list(aired_barter_avail_ids or []),
    }
