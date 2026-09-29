"""Ledgers that must unwind to exactly where they stood.

Cancelling a hold, cancelling a confirmation, and draining a vendor's
outstanding count by two different exit doors.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.test_users import ADMIN, COORDINATOR, PRODUCER


# ─── cancelling_a_held_booking_returns_exactly_its_minutes_to_the_talent_day ──

def _photographer_held_across_two_sessions(api):
    """Two unconfirmed 240-minute holds fill the photographer's 480-minute day."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    st1 = fx.create_station(api, station_code="MODEL-1")
    st2 = fx.create_station(api, station_code="MODEL-2")
    provider = fx.create_provider(api)
    photographer = fx.create_photographer(api)
    ses1 = fx.create_session(api, st1["id"], provider["id"])
    ses2 = fx.create_session(
        api,
        st2["id"],
        provider["id"],
        scheduled_start="2026-08-03T13:00:00Z",
        scheduled_end="2026-08-03T17:00:00Z",
    )
    bk1 = fx.create_booking(api, ses1["id"], photographer["id"])
    bk2 = fx.create_booking(
        api,
        ses2["id"],
        photographer["id"],
        call_time="2026-08-03T13:00:00Z",
        wrap_time="2026-08-03T17:00:00Z",
    )
    return {
        "photographer": photographer,
        "ses1": ses1,
        "ses2": ses2,
        "bk1": bk1,
        "bk2": bk2,
    }


def test_cancelling_one_hold_returns_exactly_its_own_minutes(api):
    """The day falls from 480 to 240 — not to zero, and not left at 480.

    PRD: "Cancellation reverses exactly the ledgers the booking posted and nothing more: the person's `booked_minutes_today` falls by that booking's `booked_minutes` and their `version` increments by one, and when the booking being cancelled was `CONFIRMED` the session's `committed_talent_cost_cents` falls by that booking's `charge_cents` and the session's `version` increments by one."

    Design: Difficulty/compensating_invariant/cancelling_a_held_booking_returns_exactly_its_minutes_to_the_talent_day
    """
    world = _photographer_held_across_two_sessions(api)
    assert validate_success(
        api.get_talent_profile(world["photographer"]["id"], ADMIN)
    )["booked_minutes_today"] == 480

    cancelled = validate_success(
        api.cancel_booking(
            world["bk2"]["id"], PRODUCER, {"reason": "second half dropped from the brief"}
        )
    )

    assert cancelled["booking_state"] == "CANCELLED"
    assert cancelled["booked_minutes"] == 240
    assert validate_success(
        api.get_talent_profile(world["photographer"]["id"], ADMIN)
    )["booked_minutes_today"] == 240
    assert validate_success(api.get_talent_booking(world["bk1"]["id"], PRODUCER))[
        "booking_state"
    ] == "HELD"


def test_cancelling_a_hold_leaves_both_money_ledgers_untouched_at_zero(api):
    """Neither hold was ever confirmed, so there was no money to reverse.

    PRD: "A booking cancelled straight out of `HELD` never touched the money ledger, so it does not adjust it."

    Design: Difficulty/compensating_invariant/cancelling_a_held_booking_returns_exactly_its_minutes_to_the_talent_day
    """
    world = _photographer_held_across_two_sessions(api)

    validate_success(
        api.cancel_booking(
            world["bk2"]["id"], PRODUCER, {"reason": "second half dropped from the brief"}
        )
    )

    for key in ("ses1", "ses2"):
        session = validate_success(
            api.get_shoot_session(world[key]["id"], PRODUCER)
        )
        assert session["committed_talent_cost_cents"] == 0


# ─── cancelling_a_confirmed_booking_unwinds_the_session_money_commitment_to_zero ──

def _confirmed_photographer_on_a_single_session(api):
    """One CONFIRMED 240-minute booking posting 48000 cents against a 500000 cap."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    station = fx.create_station(api)
    provider = fx.create_provider(api)
    photographer = fx.create_photographer(api)
    session = fx.create_session(api, station["id"], provider["id"])
    booking = fx.create_booking(api, session["id"], photographer["id"])
    booking = fx.confirm_booking(api, booking["id"])
    return {"photographer": photographer, "session": session, "booking": booking}


def test_cancelling_a_confirmation_reverses_the_stored_charge_exactly(api):
    """The commitment goes from 48000 to 0 with no residue and no recomputation.

    PRD: "Cancellation reverses exactly the ledgers the booking posted and nothing more: the person's `booked_minutes_today` falls by that booking's `booked_minutes` and their `version` increments by one, and when the booking being cancelled was `CONFIRMED` the session's `committed_talent_cost_cents` falls by that booking's `charge_cents` and the session's `version` increments by one."

    Design: Difficulty/compensating_invariant/cancelling_a_confirmed_booking_unwinds_the_session_money_commitment_to_zero
    """
    world = _confirmed_photographer_on_a_single_session(api)
    assert world["booking"]["charge_cents"] == 48000
    assert validate_success(api.get_shoot_session(world["session"]["id"], PRODUCER))[
        "committed_talent_cost_cents"
    ] == 48000

    cancelled = validate_success(
        api.cancel_booking(
            world["booking"]["id"], PRODUCER, {"reason": "photographer released"}
        )
    )

    assert cancelled["booking_state"] == "CANCELLED"
    assert validate_success(api.get_shoot_session(world["session"]["id"], PRODUCER))[
        "committed_talent_cost_cents"
    ] == 0


def test_the_cancelled_confirmation_also_empties_the_minute_ledger(api):
    """A cancelled booking counts toward neither ledger, and the session survives it.

    PRD: "A talent's `booked_minutes_today` is the sum of `booked_minutes` over that talent's bookings whose `booking_state` is `HELD` or `CONFIRMED` and whose `call_time` falls on that same clock date."

    Design: Difficulty/compensating_invariant/cancelling_a_confirmed_booking_unwinds_the_session_money_commitment_to_zero
    """
    world = _confirmed_photographer_on_a_single_session(api)

    validate_success(
        api.cancel_booking(
            world["booking"]["id"], PRODUCER, {"reason": "photographer released"}
        )
    )

    assert validate_success(
        api.get_talent_profile(world["photographer"]["id"], ADMIN)
    )["booked_minutes_today"] == 0
    assert validate_success(api.get_shoot_session(world["session"]["id"], PRODUCER))[
        "session_state"
    ] == "BOOKED"


# ─── vendor_outstanding_count_drains_the_same_way_for_a_return_and_for_a_write_off ──

def _vendor_holding_two_boxes(api):
    """SMP-3001 waits in the return queue; SMP-3002 sits at the dock."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    vendor = fx.create_vendor(api, sample_sla_days=14)
    smp_a = fx.create_sample(
        api, vendor["id"], barcode="SMP-3001", declared_style_number="TOP1001"
    )
    fx.receive_sample(api, smp_a["id"])
    smp_a = fx.custody_move(api, smp_a["id"], "RETURN_PENDING")
    smp_b = fx.create_sample(
        api, vendor["id"], barcode="SMP-3002", declared_style_number="TOP1002"
    )
    fx.receive_sample(api, smp_b["id"])
    return {"vendor": vendor, "smp_a": smp_a, "smp_b": smp_b}


def test_an_early_return_drains_the_outstanding_count_by_one(api):
    """A box back five days early leaves the count at one and costs nothing.

    PRD: "A vendor's `outstanding_sample_count` is the number of that vendor's samples whose `custody_state` is `RECEIVED`, `IN_STUDIO`, `ON_SET` or `RETURN_PENDING`."

    Design: Difficulty/compensating_invariant/vendor_outstanding_count_drains_the_same_way_for_a_return_and_for_a_write_off
    """
    world = _vendor_holding_two_boxes(api)
    assert validate_success(api.get_vendor(world["vendor"]["id"], ADMIN))[
        "outstanding_sample_count"
    ] == 2

    fx.set_clock(api, "2026-08-10T00:00:00Z")
    returned = validate_success(
        api.return_sample(
            world["smp_a"]["id"], COORDINATOR, {"condition_note": "clean, five days early"}
        )
    )

    assert returned["custody_state"] == "RETURNED"
    assert returned["return_days_late"] == 0
    assert validate_success(api.get_vendor(world["vendor"]["id"], ADMIN))[
        "outstanding_sample_count"
    ] == 1


def test_a_write_off_drains_the_last_box_and_supplies_the_only_strike(api):
    """The second exit door decrements the same counter but also costs a strike.

    PRD: "A vendor's `late_return_count` rises by one each time one of its samples is returned after its `due_return_at`, and by one each time one of its samples is reported lost."

    Design: Difficulty/compensating_invariant/vendor_outstanding_count_drains_the_same_way_for_a_return_and_for_a_write_off
    """
    world = _vendor_holding_two_boxes(api)
    fx.set_clock(api, "2026-08-10T00:00:00Z")
    validate_success(api.return_sample(world["smp_a"]["id"], COORDINATOR))

    lost = validate_success(
        api.report_lost_sample(
            world["smp_b"]["id"], COORDINATOR, {"reason": "never arrived on the rack"}
        )
    )

    assert lost["custody_state"] == "LOST"
    vendor = validate_success(api.get_vendor(world["vendor"]["id"], ADMIN))
    assert vendor["outstanding_sample_count"] == 0
    assert vendor["late_return_count"] == 1
    assert vendor["coordination_hold"] is False
