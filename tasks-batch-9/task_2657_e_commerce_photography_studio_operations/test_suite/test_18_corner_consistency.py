"""Immediate consistency: a write's own consequences and its neighbours' state.

Nothing in this system settles later. The receipt response already carries the
dates it derived, and the first read of every row a cancellation touched is
already correct.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.test_users import ADMIN, COORDINATOR, PRODUCER


# ─── A write reporting its own derived consequences ────────────────────────

def _one_expected_box_from_a_fourteen_day_vendor(api):
    """Vendor NRTH on a 14-day service level with a single pre-advised sample."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api, sample_sla_days=14)
    sample = fx.create_sample(api, vendor["id"])
    return vendor["id"], sample["id"]


def test_the_receipt_response_already_shows_the_new_custody_state(api):
    """The write response itself, not a follow-up read, reports the dock move.

    PRD: "Receiving the box books it into the dock, moving custody `EXPECTED → RECEIVED`."

    Design: Corner/consistency model/every_write_returns_its_own_derived_consequences_in_the_same_response
    """
    _, sample_id = _one_expected_box_from_a_fourteen_day_vendor(api)

    received = validate_success(api.receive_sample(sample_id, COORDINATOR))

    assert received["custody_state"] == "RECEIVED"


def test_the_receipt_response_already_carries_the_dates_it_derived(api):
    """Both stamps and the vendor's counter are settled by the time the call returns.

    PRD: "On success the system stamps `received_at` from the logical clock, derives `due_return_at` by adding the vendor's `sample_sla_days` to `received_at` as exact instant arithmetic (so a 14-day service level received at 09:15 is due back at 09:15 fourteen days later, not at midnight), raises the vendor's `outstanding_sample_count` by one, and increments the vendor's `version` by one."

    Design: Corner/consistency model/every_write_returns_its_own_derived_consequences_in_the_same_response
    """
    vendor_id, sample_id = _one_expected_box_from_a_fourteen_day_vendor(api)

    received = validate_success(api.receive_sample(sample_id, COORDINATOR))

    assert received["received_at"] == "2026-08-03T08:00:00.000Z"
    assert received["due_return_at"] == "2026-08-17T08:00:00.000Z"
    assert validate_success(api.get_vendor(vendor_id, ADMIN))[
        "outstanding_sample_count"
    ] == 1


def test_the_first_read_after_the_receipt_agrees_with_the_write_response(api):
    """No retry, no delay: re-reading the row returns exactly what the write said.

    PRD: "Cascades in this system are synchronous and immediate: by the time a write returns, every downstream consequence has already been applied and every affected row's `version` and `updated_at` have already moved."

    Design: Corner/consistency model/every_write_returns_its_own_derived_consequences_in_the_same_response
    """
    _, sample_id = _one_expected_box_from_a_fourteen_day_vendor(api)
    received = validate_success(api.receive_sample(sample_id, COORDINATOR))

    reread = validate_success(api.get_sample(sample_id, COORDINATOR))

    assert reread["custody_state"] == received["custody_state"]
    assert reread["received_at"] == received["received_at"]
    assert reread["due_return_at"] == received["due_return_at"]
    assert reread["version"] == received["version"]


# ─── A write whose consequences land on other rows ─────────────────────────

def _a_booked_session_holding_one_item_and_one_crew_member(api):
    """A BOOKED 09:00-13:00 model session with one ASSIGNED item and one HELD hold."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(
        api, required_angles=["FRONT"], min_on_model_shots=0
    )
    station = fx.create_station(api)
    provider = fx.create_provider(api)
    photographer = fx.create_photographer(api, minimum_call_hours=0)
    style = fx.create_style(api, vendor["id"], profile["id"])
    item = fx.create_shot_item(
        api,
        style["id"],
        asset_kind="ON_MODEL",
        angle_code="FRONT",
        estimated_minutes=30,
    )
    session = fx.create_session(api, station["id"], provider["id"])
    fx.assign_item(api, item["id"], session["id"])
    booking = fx.create_booking(api, session["id"], photographer["id"])
    return {
        "station_id": station["id"],
        "photographer_id": photographer["id"],
        "session_id": session["id"],
        "item_id": item["id"],
        "booking_id": booking["id"],
    }


def test_the_cancellation_response_already_reports_the_terminal_state(api):
    """The session is cancelled in the body of the call that cancelled it.

    PRD: "Cascades in this system are synchronous and immediate: by the time a write returns, every downstream consequence has already been applied and every affected row's `version` and `updated_at` have already moved."

    Design: Corner/consistency model/cascade_effects_are_visible_on_the_first_read_after_the_write
    """
    world = _a_booked_session_holding_one_item_and_one_crew_member(api)

    cancelled = validate_success(
        api.cancel_session(
            world["session_id"], PRODUCER, {"reason": "sample never arrived"}
        )
    )

    assert cancelled["session_state"] == "CANCELLED"


def test_the_item_and_the_booking_are_already_reverted_on_their_first_read(api):
    """The work is back in the backlog and the hold is off before anyone looks.

    PRD: "Cancellation from either origin runs the identical chain of consequences. At the first level the station's capacity is released: the cancelled session stops counting toward `committed_minutes_today`. At the second level, caused by that cancellation, every talent booking on the session whose `booking_state` is `HELD` or `CONFIRMED` moves to `CANCELLED`, and the session's `committed_talent_cost_cents` is reset to 0. At the third level, caused by those booking cancellations, each affected talent's `booked_minutes_today` is reduced by exactly that booking's `booked_minutes`, so the minute ledger returns to precisely where it stood before the hold was placed. Separately, every shot-list item that had been assigned to the session reverts from `ASSIGNED` to `PLANNED` and has its `session_id` cleared, so the work returns to the backlog rather than disappearing with the session."

    Design: Corner/consistency model/cascade_effects_are_visible_on_the_first_read_after_the_write
    """
    world = _a_booked_session_holding_one_item_and_one_crew_member(api)

    validate_success(
        api.cancel_session(
            world["session_id"], PRODUCER, {"reason": "sample never arrived"}
        )
    )

    item = validate_success(api.get_shot_list_item(world["item_id"], PRODUCER))
    assert item["item_state"] == "PLANNED"
    assert item["session_id"] is None
    booking = validate_success(api.get_talent_booking(world["booking_id"], PRODUCER))
    assert booking["booking_state"] == "CANCELLED"


def test_both_minute_ledgers_are_already_back_where_they_started(api):
    """The station's day and the photographer's day are returned by the same request.

    PRD: "Cancellation from either origin runs the identical chain of consequences. At the first level the station's capacity is released: the cancelled session stops counting toward `committed_minutes_today`. At the second level, caused by that cancellation, every talent booking on the session whose `booking_state` is `HELD` or `CONFIRMED` moves to `CANCELLED`, and the session's `committed_talent_cost_cents` is reset to 0. At the third level, caused by those booking cancellations, each affected talent's `booked_minutes_today` is reduced by exactly that booking's `booked_minutes`, so the minute ledger returns to precisely where it stood before the hold was placed. Separately, every shot-list item that had been assigned to the session reverts from `ASSIGNED` to `PLANNED` and has its `session_id` cleared, so the work returns to the backlog rather than disappearing with the session."

    Design: Corner/consistency model/cascade_effects_are_visible_on_the_first_read_after_the_write
    """
    world = _a_booked_session_holding_one_item_and_one_crew_member(api)
    assert validate_success(api.get_station(world["station_id"], ADMIN))[
        "committed_minutes_today"
    ] == 240

    validate_success(
        api.cancel_session(
            world["session_id"], PRODUCER, {"reason": "sample never arrived"}
        )
    )

    assert validate_success(api.get_station(world["station_id"], ADMIN))[
        "committed_minutes_today"
    ] == 0
    assert validate_success(
        api.get_talent_profile(world["photographer_id"], ADMIN)
    )["booked_minutes_today"] == 0
