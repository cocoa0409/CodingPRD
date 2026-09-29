"""Payload factories — one per write endpoint, input fields only."""
from .constants import TEST_DEFAULTS


def venue_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["VENUE_NAME"],
        "seat_capacity": TEST_DEFAULTS["SEAT_CAPACITY"],
        "house_hold_seats": TEST_DEFAULTS["HOUSE_HOLD_SEATS"],
        "trailer_reel_minutes": TEST_DEFAULTS["TRAILER_REEL_MINUTES"],
        "turnaround_minutes": TEST_DEFAULTS["TURNAROUND_MINUTES"],
        "min_useful_gap_minutes": TEST_DEFAULTS["MIN_USEFUL_GAP_MINUTES"],
        "dcp_ingest_lane_count": TEST_DEFAULTS["DCP_INGEST_LANE_COUNT"],
        "open_local_time": TEST_DEFAULTS["OPEN_LOCAL_TIME"],
        "last_start_local_time": TEST_DEFAULTS["LAST_START_LOCAL_TIME"],
        "utc_offset_minutes": TEST_DEFAULTS["UTC_OFFSET_MINUTES"],
        "max_first_run_share": TEST_DEFAULTS["MAX_FIRST_RUN_SHARE"],
        "weekly_repertory_target": TEST_DEFAULTS["WEEKLY_REPERTORY_TARGET"],
        "supported_formats": list(TEST_DEFAULTS["SUPPORTED_FORMATS"]),
        "base_house_nut_weekly_cents": TEST_DEFAULTS["BASE_HOUSE_NUT_WEEKLY_CENTS"],
    }
    payload.update(overrides)
    return payload


def distributor_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["DISTRIBUTOR_NAME"],
        "contact_email": TEST_DEFAULTS["DISTRIBUTOR_EMAIL"],
        "default_terms_variant": "SLIDING_SCALE_90_10",
        "default_min_run_days": TEST_DEFAULTS["DEFAULT_MIN_RUN_DAYS"],
        "default_distributor_share_pct": TEST_DEFAULTS[
            "DEFAULT_DISTRIBUTOR_SHARE_PCT"
        ],
        "requires_advance_guarantee": False,
    }
    payload.update(overrides)
    return payload


def title_payload(rights_holder_distributor_id, **overrides) -> dict:
    payload = {
        "title_name": TEST_DEFAULTS["TITLE_NAME"],
        "release_year": TEST_DEFAULTS["RELEASE_YEAR"],
        "runtime_minutes": TEST_DEFAULTS["RUNTIME_MINUTES"],
        "is_first_run": False,
        "native_format": "DCP_2K",
        "rights_holder_distributor_id": rights_holder_distributor_id,
    }
    payload.update(overrides)
    return payload


def booking_payload(title_id, distributor_id, venue_id, **overrides) -> dict:
    payload = {
        "title_id": title_id,
        "distributor_id": distributor_id,
        "venue_id": venue_id,
        "terms_variant": "SLIDING_SCALE_90_10",
        "house_nut_cents": TEST_DEFAULTS["HOUSE_NUT_CENTS"],
        "distributor_share_pct": TEST_DEFAULTS["DEFAULT_DISTRIBUTOR_SHARE_PCT"],
        "guarantee_cents": TEST_DEFAULTS["GUARANTEE_CENTS"],
        "min_run_days": TEST_DEFAULTS["MIN_RUN_DAYS"],
        "engagement_start_date": TEST_DEFAULTS["ENGAGEMENT_START_DATE"],
        "engagement_end_date": TEST_DEFAULTS["ENGAGEMENT_END_DATE"],
    }
    payload.update(overrides)
    return payload


def counter_payload(expected_booking_version, **overrides) -> dict:
    payload = {
        "expected_booking_version": expected_booking_version,
        "proposed_house_nut_cents": TEST_DEFAULTS["HOUSE_NUT_CENTS"],
        "proposed_distributor_share_pct": TEST_DEFAULTS[
            "DEFAULT_DISTRIBUTOR_SHARE_PCT"
        ],
        "proposed_min_run_days": TEST_DEFAULTS["MIN_RUN_DAYS"],
        "proposed_guarantee_cents": TEST_DEFAULTS["GUARANTEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def cinema_offer_payload(**overrides) -> dict:
    payload = {
        "proposed_house_nut_cents": TEST_DEFAULTS["HOUSE_NUT_CENTS"],
        "proposed_distributor_share_pct": TEST_DEFAULTS[
            "DEFAULT_DISTRIBUTOR_SHARE_PCT"
        ],
        "proposed_min_run_days": TEST_DEFAULTS["MIN_RUN_DAYS"],
        "proposed_guarantee_cents": TEST_DEFAULTS["GUARANTEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def clearance_payload(title_id, booking_id, **overrides) -> dict:
    payload = {
        "title_id": title_id,
        "booking_id": booking_id,
        "licensor_name": TEST_DEFAULTS["LICENSOR_NAME"],
        "license_fee_cents": TEST_DEFAULTS["LICENSE_FEE_CENTS"],
        "territory": TEST_DEFAULTS["TERRITORY"],
        "window_start_date": TEST_DEFAULTS["WINDOW_START_DATE"],
        "window_end_date": TEST_DEFAULTS["WINDOW_END_DATE"],
        "max_screenings": TEST_DEFAULTS["MAX_SCREENINGS"],
        "source_format": "DCP_2K",
    }
    payload.update(overrides)
    return payload


def dcp_asset_payload(title_id, source_distributor_id, venue_id, **overrides) -> dict:
    payload = {
        "title_id": title_id,
        "source_distributor_id": source_distributor_id,
        "venue_id": venue_id,
        "format": "DCP_2K",
        "is_encrypted": False,
        "carrier_ref": TEST_DEFAULTS["CARRIER_REF"],
        "ingest_window_start_at": TEST_DEFAULTS["INGEST_WINDOW_START_AT"],
        "ingest_window_end_at": TEST_DEFAULTS["INGEST_WINDOW_END_AT"],
    }
    payload.update(overrides)
    return payload


def kdm_key_payload(dcp_asset_id, venue_id, valid_from, valid_until, **overrides) -> dict:
    payload = {
        "dcp_asset_id": dcp_asset_id,
        "venue_id": venue_id,
        "server_ref": TEST_DEFAULTS["SERVER_REF"],
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    payload.update(overrides)
    return payload


def showtime_payload(
    venue_id,
    title_id,
    booking_id,
    clearance_id,
    dcp_asset_id,
    start_at,
    expected_clearance_version,
    **overrides,
) -> dict:
    payload = {
        "venue_id": venue_id,
        "title_id": title_id,
        "booking_id": booking_id,
        "clearance_id": clearance_id,
        "dcp_asset_id": dcp_asset_id,
        "strand": "REPERTORY_SERIES",
        "start_at": start_at,
        "base_price_cents": TEST_DEFAULTS["BASE_PRICE_CENTS"],
        "public_sale_opens_at": TEST_DEFAULTS["PUBLIC_SALE_OPENS_AT"],
        "format": "DCP_2K",
        "expected_clearance_version": expected_clearance_version,
    }
    payload.update(overrides)
    return payload


def auto_schedule_payload(
    venue_id,
    title_id,
    booking_id,
    clearance_id,
    dcp_asset_id,
    target_date,
    earliest_local_time,
    latest_local_time,
    expected_clearance_version,
    **overrides,
) -> dict:
    payload = {
        "venue_id": venue_id,
        "title_id": title_id,
        "booking_id": booking_id,
        "clearance_id": clearance_id,
        "dcp_asset_id": dcp_asset_id,
        "strand": "REPERTORY_SERIES",
        "target_date": target_date,
        "earliest_local_time": earliest_local_time,
        "latest_local_time": latest_local_time,
        "base_price_cents": TEST_DEFAULTS["BASE_PRICE_CENTS"],
        "public_sale_opens_at": TEST_DEFAULTS["PUBLIC_SALE_OPENS_AT"],
        "format": "DCP_2K",
        "expected_clearance_version": expected_clearance_version,
    }
    payload.update(overrides)
    return payload


def special_event_payload(showtime_id, **overrides) -> dict:
    payload = {
        "showtime_id": showtime_id,
        "event_type": "FILMMAKER_QA",
        "guest_name": "Chris Marker",
        "extra_minutes": 30,
        "surcharge_cents": 300,
        "guest_fee_cents": 25000,
    }
    payload.update(overrides)
    return payload


def ticket_order_payload(showtime_id, quantity=1, **overrides) -> dict:
    payload = {
        "showtime_id": showtime_id,
        "quantity": quantity,
        "purchaser_email": "walkup@example.com",
    }
    payload.update(overrides)
    return payload


def member_payload(**overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["MEMBER_NAME"],
        "email": TEST_DEFAULTS["MEMBER_EMAIL"],
        "join_date": TEST_DEFAULTS["JOIN_DATE"],
    }
    payload.update(overrides)
    return payload


def donation_payload(amount_cents, received_at, **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "received_at": received_at}
    payload.update(overrides)
    return payload


def settlement_payload(booking_id, expected_booking_version, variant="PROVISIONAL",
                       **overrides) -> dict:
    payload = {
        "booking_id": booking_id,
        "variant": variant,
        "expected_booking_version": expected_booking_version,
    }
    payload.update(overrides)
    return payload


def resolve_settlement_payload(outcome, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def clock_payload(current_utc, **overrides) -> dict:
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload
