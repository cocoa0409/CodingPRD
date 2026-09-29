"""Gates held shut by the state of a neighbouring entity.

In each case the acting resource's own payload is complete and never changes;
the only thing that moves is a field on another row — a sample's custody, a
station's calibration window, a release's signature — and that alone flips the
refusal into an acceptance.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_RELEASE_NOT_ON_FILE,
    ERR_SAMPLE_NOT_IN_STUDIO,
    ERR_STATION_CALIBRATION_EXPIRED,
)
from test_helpers.test_users import ADMIN, PRODUCER, make_photographer_headers


# ─── session_lock_blocked_by_sample_custody_then_admitted_after_the_box_hits_the_rack ──

def _booked_session_whose_sample_is_still_at_the_dock(api):
    """A required item is on the call sheet, but its matched sample never left the dock."""
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    world.style = fx.create_style(
        api, world.vendor_id, world.profile_id, priority_tier="C"
    )
    world.sample = fx.create_sample(api, world.vendor_id)
    fx.receive_sample(api, world.sample_id)
    world.sample = fx.match_sample(api, world.sample_id, world.style_id)
    world.items.append(
        fx.create_shot_item(api, world.style_id, asset_kind="ON_MODEL", angle_code="FRONT")
    )
    world.session = fx.create_session(api, world.station_id, world.provider_id)
    fx.assign_item(api, world.item_id, world.session_id)
    return world


def test_lock_refused_while_the_matched_sample_has_not_reached_the_rack(api):
    """The call sheet is complete but the goods are not in the building.

    PRD: "A style on the call sheet with no such sample refuses the freeze with `ERR_SAMPLE_NOT_IN_STUDIO`."

    Design: Difficulty/cross_entity_state_dependency/session_lock_blocked_by_sample_custody_then_admitted_after_the_box_hits_the_rack
    """
    world = _booked_session_whose_sample_is_still_at_the_dock(api)

    validate_error(
        api.lock_session(world.session_id, PRODUCER), ERR_SAMPLE_NOT_IN_STUDIO, 409
    )

    assert world.read_session()["session_state"] == "BOOKED"


def test_moving_the_box_onto_the_rack_carries_the_style_forward(api):
    """One custody move satisfies the gate and advances the style behind it.

    PRD: "Only one of these moves has a consequence beyond the sample itself: on `RECEIVED → IN_STUDIO`, if the matched style's `content_state` is either `NOT_STARTED` or `BLOCKED`, that style advances to `SAMPLE_READY` and its `version` increments by one."

    Design: Difficulty/cross_entity_state_dependency/session_lock_blocked_by_sample_custody_then_admitted_after_the_box_hits_the_rack
    """
    world = _booked_session_whose_sample_is_still_at_the_dock(api)

    moved = fx.custody_move(api, world.sample_id, "IN_STUDIO")

    assert moved["custody_state"] == "IN_STUDIO"
    assert world.read_style()["content_state"] == "SAMPLE_READY"


def test_the_same_lock_request_succeeds_once_the_sample_is_on_the_rack(api):
    """Nothing about the session changed, yet the freeze is now admitted.

    PRD: "On success the session moves `BOOKED → LOCKED` and further shot-list assignment to it is rejected."

    Design: Difficulty/cross_entity_state_dependency/session_lock_blocked_by_sample_custody_then_admitted_after_the_box_hits_the_rack
    """
    world = _booked_session_whose_sample_is_still_at_the_dock(api)
    validate_error(
        api.lock_session(world.session_id, PRODUCER), ERR_SAMPLE_NOT_IN_STUDIO, 409
    )

    fx.custody_move(api, world.sample_id, "IN_STUDIO")
    locked = validate_success(api.lock_session(world.session_id, PRODUCER))

    assert locked["session_state"] == "LOCKED"


# ─── asset_ingest_gated_by_station_calibration_window_alone ─────────────────

def _shooting_session_whose_station_calibration_has_lapsed(api):
    """A session started on 1 August, then watched from a clock past the lapse."""
    world = fx.build_reference_data(
        api,
        clock="2026-08-01T08:00:00Z",
        station_kw={"calibrated_until": "2026-08-02T00:00:00Z"},
        profile_kw={"required_angles": ["FRONT"]},
    )
    fx.build_style_on_the_rack(api, world, style_kw={"priority_tier": "C"})
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


def _ingest_body(world):
    return f.asset_payload(world.item_id, "TOP1001_FRONT_001", 1, {"season": "FW26"})


def test_ingest_refused_once_the_clock_leaves_the_calibration_window(api):
    """A lapsed bench cannot certify colour, so the file is turned away.

    PRD: "The station the session occupies must be currently calibrated: its `calibrated_until` must be non-null and must fall strictly after the current logical clock, since a station that has never been calibrated or whose calibration has lapsed cannot certify colour — either case is `ERR_STATION_CALIBRATION_EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/asset_ingest_gated_by_station_calibration_window_alone
    """
    world = _shooting_session_whose_station_calibration_has_lapsed(api)

    validate_error(
        api.create_asset(
            _ingest_body(world), make_photographer_headers(world.photographer_id)
        ),
        ERR_STATION_CALIBRATION_EXPIRED,
        409,
    )

    item = world.read_item()
    assert item["item_state"] == "ASSIGNED"
    assert item["live_asset_count"] == 0


def test_the_identical_body_is_accepted_inside_the_calibration_window(api):
    """No field of the ingest changes; only where the clock sits relative to the lapse.

    PRD: "An accepted ingest lands the asset in `asset_state` `INGESTED`, copies the item's `session_id` onto the asset's own `session_id`, and records the acting photographer as `captured_by_talent_id`."

    Design: Difficulty/cross_entity_state_dependency/asset_ingest_gated_by_station_calibration_window_alone
    """
    world = _shooting_session_whose_station_calibration_has_lapsed(api)
    validate_error(
        api.create_asset(
            _ingest_body(world), make_photographer_headers(world.photographer_id)
        ),
        ERR_STATION_CALIBRATION_EXPIRED,
        409,
    )

    fx.set_clock(api, "2026-08-01T11:00:00Z")
    asset = validate_success(
        api.create_asset(
            _ingest_body(world), make_photographer_headers(world.photographer_id)
        ),
        201,
    )

    assert asset["asset_state"] == "INGESTED"
    assert asset["session_id"] == world.session_id
    assert asset["captured_by_talent_id"] == world.photographer_id


def test_the_admitted_capture_carries_the_item_and_the_style_forward(api):
    """The first live file on the last required item takes the style to `SHOT`.

    PRD: "Ingesting the first non-rejected file against the item advances it `ASSIGNED → CAPTURED`, which happens precisely when its `live_asset_count` rises from 0 to 1; at that moment, if every shot-list item of the style whose `required` flag is true and whose `item_state` is not `WAIVED` is now `CAPTURED`, the style advances to `SHOT` and its `version` increments by one."

    Design: Difficulty/cross_entity_state_dependency/asset_ingest_gated_by_station_calibration_window_alone
    """
    world = _shooting_session_whose_station_calibration_has_lapsed(api)
    fx.set_clock(api, "2026-08-01T11:00:00Z")

    validate_success(
        api.create_asset(
            _ingest_body(world), make_photographer_headers(world.photographer_id)
        ),
        201,
    )

    item = world.read_item()
    assert item["item_state"] == "CAPTURED"
    assert item["live_asset_count"] == 1
    assert world.read_style()["content_state"] == "SHOT"


# ─── model_booking_confirmation_waits_on_release_signature_state ────────────

def _held_model_booking_behind_an_unsigned_release(api):
    """A covering release exists, with every term right except the signature."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    station = fx.create_station(api)
    provider = fx.create_provider(api)
    model = fx.create_model(api, minimum_call_hours=0, max_daily_minutes=600)
    release = fx.create_release(
        api,
        model["id"],
        scope="ECOM_ONLY",
        territory="GLOBAL",
        valid_from="2026-07-01T00:00:00Z",
        valid_until="2026-09-01T00:00:00Z",
    )
    session = fx.create_session(api, station["id"], provider["id"])
    booking = fx.create_booking(
        api, session["id"], model["id"], role_on_set="MODEL"
    )
    return {
        "model": model,
        "release": release,
        "session": session,
        "booking": booking,
    }


def test_confirmation_refused_while_the_release_is_only_pending(api):
    """An unsigned document is no document at all for confirmation purposes.

    PRD: "If nothing qualifies the confirmation is refused with `ERR_RELEASE_NOT_ON_FILE`."

    Design: Difficulty/cross_entity_state_dependency/model_booking_confirmation_waits_on_release_signature_state
    """
    world = _held_model_booking_behind_an_unsigned_release(api)

    validate_error(
        api.confirm_booking(world["booking"]["id"], PRODUCER),
        ERR_RELEASE_NOT_ON_FILE,
        422,
    )

    booking = validate_success(
        api.get_talent_booking(world["booking"]["id"], PRODUCER)
    )
    assert booking["booking_state"] == "HELD"
    assert validate_success(api.get_shoot_session(world["session"]["id"], PRODUCER))[
        "committed_talent_cost_cents"
    ] == 0


def test_countersigning_stamps_the_document_from_the_logical_clock(api):
    """The signature is the only thing that moves, and it is clock-stamped.

    PRD: "Countersigning moves it `PENDING → SIGNED` and stamps `signed_at` from the logical clock, but only while the document is still `PENDING` and the clock is strictly before `valid_until`; a document already `SIGNED`, already `EXPIRED`, or whose `valid_until` has been reached is refused with `ERR_RELEASE_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/model_booking_confirmation_waits_on_release_signature_state
    """
    world = _held_model_booking_behind_an_unsigned_release(api)

    signed = validate_success(
        api.sign_release_document(world["release"]["id"], ADMIN)
    )

    assert signed["doc_state"] == "SIGNED"
    assert signed["signed_at"] == "2026-08-03T08:00:00.000Z"


def test_the_signature_unblocks_the_confirmation_and_is_pinned_onto_it(api):
    """The selected document's identity and scope are written onto the booking.

    PRD: "For a model booking it pins the provenance of the rights by writing the selected document's identifier into `release_document_id` and copying its `scope` into `usage_rights_scope`; for a stylist or photographer booking both of those fields remain null, because no release is required and therefore none is pinned."

    Design: Difficulty/cross_entity_state_dependency/model_booking_confirmation_waits_on_release_signature_state
    """
    world = _held_model_booking_behind_an_unsigned_release(api)
    validate_error(
        api.confirm_booking(world["booking"]["id"], PRODUCER),
        ERR_RELEASE_NOT_ON_FILE,
        422,
    )
    fx.sign_release(api, world["release"]["id"])

    confirmed = validate_success(
        api.confirm_booking(world["booking"]["id"], PRODUCER)
    )

    assert confirmed["booking_state"] == "CONFIRMED"
    assert confirmed["release_document_id"] == world["release"]["id"]
    assert confirmed["usage_rights_scope"] == "ECOM_ONLY"


def test_confirmation_commits_the_four_hour_model_charge_to_the_session(api):
    """Four hours at 25000 cents an hour lands on the session's commitment.

    PRD: "The session's `committed_talent_cost_cents` then rises by the booking's `charge_cents` and the session's `version` increments by one."

    Design: Difficulty/cross_entity_state_dependency/model_booking_confirmation_waits_on_release_signature_state
    """
    world = _held_model_booking_behind_an_unsigned_release(api)
    fx.sign_release(api, world["release"]["id"])

    confirmed = validate_success(
        api.confirm_booking(world["booking"]["id"], PRODUCER)
    )

    assert confirmed["charge_cents"] == 100000
    assert validate_success(api.get_shoot_session(world["session"]["id"], PRODUCER))[
        "committed_talent_cost_cents"
    ] == 100000
    assert validate_success(api.get_talent_profile(world["model"]["id"], ADMIN))[
        "booked_minutes_today"
    ] == 240
