"""State-machine corners: reverse edges, preconditions, initial states, terminals.

Undeclared transitions, non-idempotent actions, the terminal lockdown, and the
side effects that ride along with a state change rather than merely following it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_RELEASE_INVALID_STATE,
    ERR_SAMPLE_INVALID_CUSTODY,
    ERR_SESSION_NOT_LOCKED,
    ERR_SESSION_TERMINAL,
)
from test_helpers.test_users import ADMIN, COORDINATOR, PRODUCER


def _a_frozen_call_sheet(api):
    """One required FRONT item assigned to a 09:00-13:00 MODEL session, LOCKED."""
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    fx.build_style_on_the_rack(api, world)
    fx.build_planned_session(api, world)
    world.session = fx.lock_session(api, world.session_id)
    return world


def test_unlocking_a_frozen_call_sheet_returns_the_session_to_booked(api):
    """Reopening bumps the version but disturbs neither the item nor the capacity.

    PRD: "`LOCKED → BOOKED` restores assignment to the call sheet, and is refused with `ERR_SESSION_NOT_LOCKED` if the session is not currently locked."

    Design: Corner/state_machines/unlock_returns_a_locked_session_to_booked
    """
    world = _a_frozen_call_sheet(api)
    locked_version = world.session["version"]
    assert world.session["session_state"] == "LOCKED"

    reopened = validate_success(api.unlock_session(world.session_id, PRODUCER))

    assert reopened["session_state"] == "BOOKED"
    assert reopened["version"] == locked_version + 1
    item = world.read_item(0)
    assert item["item_state"] == "ASSIGNED"
    assert item["session_id"] == world.session_id
    assert world.read_station()["committed_minutes_today"] == 240


def test_unlocking_a_session_that_was_never_frozen_is_refused(api):
    """The reverse edge demands LOCKED, so a BOOKED session cannot take it.

    PRD: "`LOCKED → BOOKED` restores assignment to the call sheet, and is refused with `ERR_SESSION_NOT_LOCKED` if the session is not currently locked."

    Design: Corner/state_machines/unlock_on_a_booked_session_is_refused_by_its_precondition
    """
    world = fx.build_reference_data(api)
    session = fx.create_session(api, world.station_id, world.provider_id)

    validate_error(
        api.unlock_session(session["id"], PRODUCER), ERR_SESSION_NOT_LOCKED, 409
    )

    after = validate_success(api.get_shoot_session(session["id"], PRODUCER))
    assert after["session_state"] == "BOOKED"


def test_waiving_a_required_item_drops_the_style_requirement_counter(api):
    """The terminal move carries the counter and the version with it.

    PRD: "When the waived item's `required` flag was true, the style's `required_item_count` falls by one, and the style's `version` increments by one."

    Design: Corner/state_machines/waiving_a_required_item_decrements_the_style_requirement_counter
    """
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    world.style = fx.create_style(api, world.vendor_id, world.profile_id)
    style_version_at_registration = world.style["version"]
    item = fx.create_shot_item(api, world.style_id)
    assert validate_success(api.get_style(world.style_id, PRODUCER))[
        "required_item_count"
    ] == 1

    waived = validate_success(
        api.waive_shot_list_item(
            item["id"], PRODUCER, {"reason": "angle dropped from the category brief"}
        )
    )

    assert waived["item_state"] == "WAIVED"
    style = world.read_style()
    assert style["required_item_count"] == 0
    assert style["version"] == style_version_at_registration + 2
    assert style["content_state"] == "NOT_STARTED"


def test_walking_a_received_sample_straight_to_the_floor_is_undeclared(api):
    """ON_SET is reachable from the rack only, however well identified the box is.

    PRD: "Any origin-destination pair not in that list is an undeclared transition and is refused with `ERR_SAMPLE_INVALID_CUSTODY`."

    Design: Corner/state_machines/custody_move_to_on_set_from_received_is_not_a_declared_edge
    """
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    world.style = fx.create_style(api, world.vendor_id, world.profile_id)
    world.sample = fx.create_sample(api, world.vendor_id)
    fx.receive_sample(api, world.sample_id)
    fx.match_sample(api, world.sample_id, world.style_id)

    validate_error(
        api.custody_move_sample(
            world.sample_id, f.custody_move_payload("ON_SET"), COORDINATOR
        ),
        ERR_SAMPLE_INVALID_CUSTODY,
        409,
    )

    sample = world.read_sample()
    assert sample["custody_state"] == "RECEIVED"
    assert sample["match_state"] == "MATCHED"
    assert world.read_style()["content_state"] == "NOT_STARTED"


def _four_rows_nobody_has_advanced(api):
    """A session, a hold, a shot-list item and a release, all straight from create."""
    world = fx.build_reference_data(api, profile_kw={"required_angles": ["FRONT"]})
    world.style = fx.create_style(api, world.vendor_id, world.profile_id)
    world.session = fx.create_session(api, world.station_id, world.provider_id)
    world.bookings.append(
        fx.create_booking(api, world.session_id, world.photographer_id)
    )
    world.items.append(fx.create_shot_item(api, world.style_id))
    world.release = fx.create_release(
        api,
        world.photographer_id,
        territory="GLOBAL",
        valid_from="2026-07-01T00:00:00Z",
        valid_until="2026-09-01T00:00:00Z",
    )
    return world


def test_a_newly_scheduled_session_starts_booked(api):
    """No client input chooses the state a session opens in.

    PRD: "On success the session is created in `session_state` `BOOKED`."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    world = _four_rows_nobody_has_advanced(api)

    assert world.read_session()["session_state"] == "BOOKED"


def test_a_newly_placed_hold_starts_held(api):
    """A hold opens with both usage-rights fields still empty.

    PRD: "A successful hold lands in `booking_state` `HELD` with `usage_rights_scope` and `release_document_id` both null, raises the booked person's `booked_minutes_today` by `booked_minutes` and increments that person's `version` by one, and increments the parent session's `version` by one."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    world = _four_rows_nobody_has_advanced(api)

    booking = world.read_booking(0)

    assert booking["booking_state"] == "HELD"
    assert booking["usage_rights_scope"] is None
    assert booking["release_document_id"] is None


def test_a_newly_defined_shot_list_item_starts_planned(api):
    """The item opens off any call sheet, with nothing captured and nothing costed.

    PRD: "A new item lands in `item_state` `PLANNED` with `session_id` null, `live_asset_count` 0 and `allocated_cost_cents` 0, and if its `required` flag is true the parent style's `required_item_count` rises by one; either way the style's `version` increments by one."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    world = _four_rows_nobody_has_advanced(api)

    item = world.read_item(0)

    assert item["item_state"] == "PLANNED"
    assert item["session_id"] is None
    assert item["live_asset_count"] == 0
    assert item["allocated_cost_cents"] == 0


def test_a_newly_recorded_release_starts_pending_and_unsigned(api):
    """The signature is a later act, so the stamp is absent at creation.

    PRD: "A new release lands in `doc_state` `PENDING` with `signed_at` null."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    world = _four_rows_nobody_has_advanced(api)

    release = validate_success(
        api.get_release_document(world.release["id"], ADMIN)
    )

    assert release["doc_state"] == "PENDING"
    assert release["signed_at"] is None


def test_cancelling_an_already_cancelled_session_is_refused_as_terminal(api):
    """The second cancel is rejected, so no side effect gets a second run either.

    PRD: "Cancellation is available while the session is still `BOOKED` or `LOCKED`, optionally with a `reason`; a session already `WRAPPED` or `CANCELLED` cannot be cancelled again and the attempt is refused with `ERR_SESSION_TERMINAL`."

    Design: Corner/state_machines/cancelling_an_already_cancelled_session_hits_the_terminal_lockdown
    """
    world = fx.build_reference_data(api)
    session = fx.create_session(api, world.station_id, world.provider_id)
    validate_success(
        api.cancel_session(session["id"], PRODUCER, {"reason": "brief pulled"})
    )

    validate_error(
        api.cancel_session(session["id"], PRODUCER, {"reason": "pulled again"}),
        ERR_SESSION_TERMINAL,
        409,
    )

    after = validate_success(api.get_shoot_session(session["id"], PRODUCER))
    assert after["session_state"] == "CANCELLED"
    assert world.read_station()["committed_minutes_today"] == 0


def test_countersigning_an_already_signed_release_keeps_the_first_stamp(api):
    """Signing is not idempotent, and the timestamp is not refreshed.

    PRD: "Countersigning moves it `PENDING → SIGNED` and stamps `signed_at` from the logical clock, but only while the document is still `PENDING` and the clock is strictly before `valid_until`; a document already `SIGNED`, already `EXPIRED`, or whose `valid_until` has been reached is refused with `ERR_RELEASE_INVALID_STATE`."

    Design: Corner/state_machines/signing_an_already_signed_release_is_rejected_on_the_second_call
    """
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    model = fx.create_model(api, minimum_call_hours=0, max_daily_minutes=600)
    release = fx.create_release(
        api,
        model["id"],
        territory="GLOBAL",
        valid_from="2026-07-01T00:00:00Z",
        valid_until="2026-09-01T00:00:00Z",
    )
    fx.sign_release(api, release["id"])
    fx.set_clock(api, "2026-08-03T09:00:00Z")

    validate_error(
        api.sign_release_document(release["id"], ADMIN),
        ERR_RELEASE_INVALID_STATE,
        409,
    )

    after = validate_success(api.get_release_document(release["id"], ADMIN))
    assert after["doc_state"] == "SIGNED"
    assert after["signed_at"] == "2026-08-03T08:00:00.000Z"


def _a_call_sheet_with_one_assigned_item_and_a_waived_sibling(api):
    """FRONT is on the 09:00-13:00 call sheet; BACK was waived before the cancel."""
    world = fx.build_reference_data(api)
    world.style = fx.create_style(api, world.vendor_id, world.profile_id)
    front = fx.create_shot_item(api, world.style_id, angle_code="FRONT")
    back = fx.create_shot_item(api, world.style_id, angle_code="BACK")
    fx.waive_item(api, back["id"], reason="back angle cut")
    world.items = [front, back]
    world.session = fx.create_session(api, world.station_id, world.provider_id)
    fx.assign_item(api, front["id"], world.session_id)
    booking = fx.create_booking(api, world.session_id, world.photographer_id)
    world.bookings.append(fx.confirm_booking(api, booking["id"]))
    return world


def test_cancelling_a_session_reverts_the_assigned_item_and_spares_the_waived_one(api):
    """The item cascade reads item_state, so the terminal sibling is left alone.

    PRD: "Separately, every shot-list item that had been assigned to the session reverts from `ASSIGNED` to `PLANNED` and has its `session_id` cleared, so the work returns to the backlog rather than disappearing with the session."

    Design: Corner/state_machines/session_cancel_reverts_assigned_items_but_leaves_waived_ones_alone
    """
    world = _a_call_sheet_with_one_assigned_item_and_a_waived_sibling(api)

    cancelled = validate_success(
        api.cancel_session(world.session_id, PRODUCER, {"reason": "location flooded"})
    )

    assert cancelled["session_state"] == "CANCELLED"
    front = world.read_item(0)
    assert front["item_state"] == "PLANNED"
    assert front["session_id"] is None
    assert world.read_item(1)["item_state"] == "WAIVED"
    assert world.read_style()["required_item_count"] == 1


def test_cancelling_a_session_cancels_the_confirmed_hold_and_clears_the_money(api):
    """The confirmed booking goes terminal and the session's fiscal commitment resets.

    PRD: "At the second level, caused by that cancellation, every talent booking on the session whose `booking_state` is `HELD` or `CONFIRMED` moves to `CANCELLED`, and the session's `committed_talent_cost_cents` is reset to 0."

    Design: Corner/state_machines/session_cancel_reverts_assigned_items_but_leaves_waived_ones_alone
    """
    world = _a_call_sheet_with_one_assigned_item_and_a_waived_sibling(api)
    assert world.read_session()["committed_talent_cost_cents"] == 48000

    validate_success(
        api.cancel_session(world.session_id, PRODUCER, {"reason": "location flooded"})
    )

    assert world.read_booking(0)["booking_state"] == "CANCELLED"
    assert world.read_session()["committed_talent_cost_cents"] == 0


def test_cancelling_a_session_returns_the_talents_minutes_exactly(api):
    """The photographer's day ledger falls back by the booking's own minutes.

    PRD: "At the third level, caused by those booking cancellations, each affected talent's `booked_minutes_today` is reduced by exactly that booking's `booked_minutes`, so the minute ledger returns to precisely where it stood before the hold was placed."

    Design: Corner/state_machines/session_cancel_reverts_assigned_items_but_leaves_waived_ones_alone
    """
    world = _a_call_sheet_with_one_assigned_item_and_a_waived_sibling(api)
    assert world.read_booking(0)["booked_minutes"] == 240
    assert world.read_talent(world.photographer_id)["booked_minutes_today"] == 240

    validate_success(
        api.cancel_session(world.session_id, PRODUCER, {"reason": "location flooded"})
    )

    assert world.read_talent(world.photographer_id)["booked_minutes_today"] == 0


def test_cancelling_a_session_releases_the_station_capacity_it_had_committed(api):
    """The cancelled interval stops counting against the bay's day.

    PRD: "At the first level the station's capacity is released: the cancelled session stops counting toward `committed_minutes_today`."

    Design: Corner/state_machines/session_cancel_reverts_assigned_items_but_leaves_waived_ones_alone
    """
    world = _a_call_sheet_with_one_assigned_item_and_a_waived_sibling(api)
    assert world.read_station()["committed_minutes_today"] == 240

    validate_success(
        api.cancel_session(world.session_id, PRODUCER, {"reason": "location flooded"})
    )

    assert world.read_station()["committed_minutes_today"] == 0
