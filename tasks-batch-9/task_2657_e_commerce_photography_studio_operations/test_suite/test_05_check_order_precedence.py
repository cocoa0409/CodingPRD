"""Requests that violate two rules at once, where the order of judgement decides.

PRD §2.7 makes the sequence normative, so each of these pairs has exactly one
correct `error_id` and the other code must not surface.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_RELEASE_NOT_ON_FILE,
    ERR_SESSION_NOT_BOOKED,
    ERR_STATION_CALIBRATION_EXPIRED,
)
from test_helpers.test_users import PRODUCER
from test_helpers.test_users import make_photographer_headers


def _cancelled_session_and_a_clashing_confirmed_booking(api):
    """The photographer is already confirmed 09:00-13:00 on another station's session."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    station_one = fx.create_station(api, station_code="MODEL-1")
    station_two = fx.create_station(api, station_code="MODEL-2")
    provider = fx.create_provider(api)
    photographer = fx.create_photographer(api)
    session_one = fx.create_session(api, station_one["id"], provider["id"])
    booking = fx.create_booking(api, session_one["id"], photographer["id"])
    fx.confirm_booking(api, booking["id"])
    session_two = fx.create_session(api, station_two["id"], provider["id"])
    validate_success(
        api.cancel_session(session_two["id"], PRODUCER, {"reason": "brief pulled"})
    )
    return {
        "session_two": session_two,
        "photographer": photographer,
    }


def test_cancelled_session_gate_outranks_the_talent_overlap_it_also_breaks(api):
    """A hold on a cancelled session fails on state, not on the double booking.

    PRD: "The session must currently be `BOOKED`; a hold placed against a session that has already been locked, has started shooting, or has wrapped or been cancelled is refused with `ERR_SESSION_NOT_BOOKED`."

    Design: Difficulty/priority_pair_validation_conflict/cancelled_session_state_gate_outranks_talent_double_booking
    """
    world = _cancelled_session_and_a_clashing_confirmed_booking(api)

    response = api.create_talent_booking(
        f.booking_payload(
            world["session_two"]["id"],
            world["photographer"]["id"],
            fx.session_version(api, world["session_two"]["id"]),
        ),
        PRODUCER,
    )

    error = validate_error(response, ERR_SESSION_NOT_BOOKED, 409)
    assert error["error_id"] != "ERR_TALENT_OVERLAP"


def test_the_refused_hold_writes_nothing_to_either_ledger(api):
    """The cancelled session stays cancelled and the minute ledger keeps its 240.

    PRD: "Cancelled sessions and cancelled or released bookings are excluded from the two minute counters; released bookings do remain inside `committed_talent_cost_cents`."

    Design: Difficulty/priority_pair_validation_conflict/cancelled_session_state_gate_outranks_talent_double_booking
    """
    world = _cancelled_session_and_a_clashing_confirmed_booking(api)

    api.create_talent_booking(
        f.booking_payload(
            world["session_two"]["id"],
            world["photographer"]["id"],
            fx.session_version(api, world["session_two"]["id"]),
        ),
        PRODUCER,
    )

    talent = validate_success(
        api.get_talent_profile(world["photographer"]["id"], PRODUCER)
    )
    session = validate_success(
        api.get_shoot_session(world["session_two"]["id"], PRODUCER)
    )
    assert talent["booked_minutes_today"] == 240
    assert session["session_state"] == "CANCELLED"
    assert session["committed_talent_cost_cents"] == 0


def _held_model_booking_over_a_tiny_budget(api):
    """A model with no release at all, held for a 100000-cent charge on a 1000-cent cap."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    station = fx.create_station(api)
    provider = fx.create_provider(api)
    model = fx.create_talent(
        api,
        full_name="Ada Vell",
        talent_type="MODEL",
        hourly_rate_cents=25000,
        day_rate_cents=150000,
        minimum_call_hours=0,
        max_daily_minutes=600,
    )
    session = fx.create_session(
        api, station["id"], provider["id"], budget_cap_cents=1000
    )
    booking = fx.create_booking(
        api, session["id"], model["id"], role_on_set="MODEL"
    )
    return {"session": session, "booking": booking, "model": model}


def test_missing_release_outranks_the_budget_the_same_booking_also_blows(api):
    """Paperwork is checked before money, so the release code surfaces.

    PRD: "If nothing qualifies the confirmation is refused with `ERR_RELEASE_NOT_ON_FILE`."

    Design: Difficulty/priority_pair_validation_conflict/missing_model_release_outranks_session_budget_breach_on_confirm
    """
    world = _held_model_booking_over_a_tiny_budget(api)

    response = api.confirm_booking(world["booking"]["id"], PRODUCER)

    error = validate_error(response, ERR_RELEASE_NOT_ON_FILE, 422)
    assert error["error_id"] != "ERR_SESSION_BUDGET_EXCEEDED"


def test_the_refused_confirmation_pins_no_rights_and_commits_no_money(api):
    """The booking stays held with nothing pinned and the session commits nothing.

    PRD: "A successful confirmation moves the booking `HELD → CONFIRMED`."

    Design: Difficulty/priority_pair_validation_conflict/missing_model_release_outranks_session_budget_breach_on_confirm
    """
    world = _held_model_booking_over_a_tiny_budget(api)

    api.confirm_booking(world["booking"]["id"], PRODUCER)

    booking = validate_success(
        api.get_talent_booking(world["booking"]["id"], PRODUCER)
    )
    session = validate_success(
        api.get_shoot_session(world["session"]["id"], PRODUCER)
    )
    assert booking["booking_state"] == "HELD"
    assert booking["release_document_id"] is None
    assert session["committed_talent_cost_cents"] == 0


def _shooting_session_on_a_lapsed_station(api):
    """A session started while calibration held, then left shooting past its expiry."""
    world = fx.build_reference_data(
        api,
        clock="2026-08-01T08:00:00Z",
        profile_kw={"required_angles": ["FRONT"]},
        station_kw={"calibrated_until": "2026-08-02T00:00:00Z"},
    )
    fx.build_style_on_the_rack(api, world)
    fx.build_planned_session(
        api,
        world,
        item_specs=[{"asset_kind": "ON_MODEL", "angle_code": "FRONT"}],
        session_kw={
            "scheduled_start": "2026-08-01T09:00:00Z",
            "scheduled_end": "2026-08-01T13:00:00Z",
        },
        booking_kw={
            "call_time": "2026-08-01T09:00:00Z",
            "wrap_time": "2026-08-01T13:00:00Z",
        },
    )
    fx.build_shooting_session(api, world, start_clock="2026-08-01T09:00:00Z")
    fx.set_clock(api, "2026-08-03T10:00:00Z")
    return world


def test_lapsed_calibration_outranks_the_metadata_the_same_file_is_missing(api):
    """The safety gate fires first, so the incomplete season tag is never reached.

    PRD: "The station the session occupies must be currently calibrated: its `calibrated_until` must be non-null and must fall strictly after the current logical clock, since a station that has never been calibrated or whose calibration has lapsed cannot certify colour — either case is `ERR_STATION_CALIBRATION_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/expired_station_calibration_outranks_incomplete_asset_metadata
    """
    world = _shooting_session_on_a_lapsed_station(api)

    response = api.create_asset(
        f.asset_payload(
            world.item_id,
            "TOP1001_FRONT_001",
            metadata_tags={"photographer": "Pia Ren"},
        ),
        make_photographer_headers(world.photographer_id),
    )

    error = validate_error(response, ERR_STATION_CALIBRATION_EXPIRED, 409)
    assert error["error_id"] != "ERR_ASSET_METADATA_INCOMPLETE"


def test_the_refused_ingest_leaves_the_item_and_the_style_where_they_were(api):
    """No asset is created, so nothing downstream of the ingest moves.

    PRD: "The item's `live_asset_count` rises by one and, when it rises from 0 to 1, the item advances `ASSIGNED → CAPTURED`; if that capture completes the style's required non-waived set, the style advances to `SHOT` and its `version` increments by one."

    Design: Difficulty/priority_pair_validation_conflict/expired_station_calibration_outranks_incomplete_asset_metadata
    """
    world = _shooting_session_on_a_lapsed_station(api)

    api.create_asset(
        f.asset_payload(
            world.item_id,
            "TOP1001_FRONT_001",
            metadata_tags={"photographer": "Pia Ren"},
        ),
        make_photographer_headers(world.photographer_id),
    )

    item = world.read_item(0)
    assert item["item_state"] == "ASSIGNED"
    assert item["live_asset_count"] == 0
    assert world.read_style()["content_state"] == "SCHEDULED"
