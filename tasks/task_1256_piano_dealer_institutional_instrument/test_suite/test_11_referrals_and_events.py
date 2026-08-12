"""Restoration referrals and showroom event management (PRD §3.8, §3.9)."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_available_instrument, create_referral, assess_referral, quote_referral,
    create_quoted_referral, create_event, open_event_rsvp, get_event, get_instrument,
    create_showroom_event_payload, set_clock, TEST_USERS,
)

MANAGER = TEST_USERS["store_manager_headers"]
ASSOCIATE = TEST_USERS["sales_associate_headers"]


def _available_used_instrument(serial="SN-RF-1"):
    return create_available_instrument(
        serial_number=serial, category="GRAND", manufacturer="Steinway", model="B",
        year_built=1975, condition_grade="POOR", acquisition_type="USED",
        list_price_cents=900_000, floor_price_cents=700_000)


def test_referral_quote_from_referred_rejected(api):
    """PRD §3.8: "Assessment records a `condition_score` between 1 and 100 together with
    `estimate_low_cents` and `estimate_high_cents`, moving the referral to `ASSESSED`. A
    binding quote records `final_quote_cents`, moving to `QUOTED`."
    PRD §3.8: "Each step requires its exact source state, else
    `ERR_REFERRAL_NOT_ACTIONABLE`."

    Design: Corner/validations/referral_quote_from_referred_rejected
    """
    instrument = _available_used_instrument()
    referral = create_referral(instrument["id"], shop_name="Golden Era Restorations")
    assert referral["status"] == "REFERRED"

    res = api.quote_referral(referral["id"], {"final_quote_cents": 250_000}, MANAGER)
    validate_error(res, "ERR_REFERRAL_NOT_ACTIONABLE")
    after = validate_success(api.get_restoration_referral(referral["id"], MANAGER), 200)
    assert after["status"] == "REFERRED"


def test_referral_commission_holds_instrument_and_restoration_cycle(api):
    """PRD §3.8: "The decision step takes a `decision` of `COMMISSIONED` or `DECLINED`, both
    terminal. Commissioning requires the instrument to be `AVAILABLE` — it is placed into
    `RESTORATION_HOLD`, and an unavailable instrument is rejected with
    `ERR_INSTRUMENT_NOT_AVAILABLE`."
    PRD §3.8: "When the workshop work is done, a `StoreManager` completes restoration,
    moving the instrument from `RESTORATION_HOLD` back to `IN_PREP` (only
    `RESTORATION_HOLD` is eligible), ready to be prepped and listed again per §3.1."

    Design: Corner/validations/referral_commission_holds_instrument_and_restoration_cycle
    """
    instrument = _available_used_instrument("SN-RC-1")
    referral = create_quoted_referral(instrument["id"])

    commissioned = validate_success(api.record_referral_decision(
        referral["id"], {"decision": "COMMISSIONED"}, MANAGER), 200)
    assert commissioned["status"] == "COMMISSIONED"
    assert get_instrument(instrument["id"])["status"] == "RESTORATION_HOLD", (
        "commissioning places the instrument into RESTORATION_HOLD")

    restored = validate_success(api.complete_restoration(instrument["id"], MANAGER), 200)
    assert restored["status"] == "IN_PREP", (
        "cycle completes: AVAILABLE -> RESTORATION_HOLD -> IN_PREP")


def test_room_adjacency_allowed_but_overlap_rejected(api):
    """PRD §3.9: "Room bookings use half-open overlap semantics: an event conflicts only
    with a non-`CANCELLED` event in the same room whose window strictly overlaps, so
    back-to-back scheduling — one event's `end_at` equal to the next's `start_at` — is
    allowed. An overlapping submission is rejected with `ERR_ROOM_WINDOW_CONFLICT`."

    Design: Corner/validations/room_adjacency_allowed_but_overlap_rejected
    """
    event_a = create_event(room="MAIN_SHOWROOM", title="Recital A",
                           start_at="2026-06-05T18:00:00Z", end_at="2026-06-05T20:00:00Z",
                           capacity=40, artist_guarantee_cents=100_000, split_pct=0.60)
    assert event_a["status"] == "PLANNED"

    event_b = validate_success(api.create_showroom_event(
        create_showroom_event_payload(room="MAIN_SHOWROOM", title="Recital B",
                                      start_at="2026-06-05T20:00:00Z",
                                      end_at="2026-06-05T22:00:00Z", capacity=40,
                                      artist_guarantee_cents=100_000, split_pct=0.60),
        MANAGER), 201)
    assert event_b["status"] == "PLANNED", "back-to-back (20:00 == end of A) is allowed"

    res = api.create_showroom_event(
        create_showroom_event_payload(room="MAIN_SHOWROOM", title="Recital C",
                                      start_at="2026-06-05T19:00:00Z",
                                      end_at="2026-06-05T21:00:00Z", capacity=40,
                                      artist_guarantee_cents=100_000, split_pct=0.60),
        MANAGER)
    validate_error(res, "ERR_ROOM_WINDOW_CONFLICT")


def test_event_capacity_boundary_full_at_exact_capacity(api):
    """PRD §3.9: "While open, a `SalesAssociate` adds parties by supplying a `party_size`
    that defaults to 1; each addition must leave `rsvp_count` plus `party_size` no greater
    than `capacity`, else `ERR_EVENT_CAPACITY_EXCEEDED`, and a successful addition grows
    `rsvp_count` by the party size."
    (Capacity 2: two single-seat RSVPs fill it exactly; the third is rejected.)

    Design: Corner/validations/event_capacity_boundary_full_at_exact_capacity
    """
    event = create_event(room="RECITAL_HALL", title="Salon Evening",
                         start_at="2026-06-06T18:00:00Z", end_at="2026-06-06T20:00:00Z",
                         capacity=2, artist_guarantee_cents=50_000, split_pct=0.50)
    open_event_rsvp(event["id"])

    first = validate_success(api.add_rsvp(event["id"], {"party_size": 1}, ASSOCIATE), 201)
    assert first["rsvp_count"] == 1
    second = validate_success(api.add_rsvp(event["id"], {"party_size": 1}, ASSOCIATE), 201)
    assert second["rsvp_count"] == 2, "rsvp_count == capacity is allowed (inclusive)"

    res = api.add_rsvp(event["id"], {"party_size": 1}, ASSOCIATE)
    validate_error(res, "ERR_EVENT_CAPACITY_EXCEEDED")
    assert get_event(event["id"])["rsvp_count"] == 2, "rejected RSVP must not add seats"


def test_event_settle_before_end_rejected(api):
    """PRD §3.9: "After the event has ended — the logical clock at or past `end_at` — a
    `StoreManager` settles it by supplying the `gross_cents` ticket receipts."
    PRD §3.9: "Settlement before `end_at`, or against an event not in `RSVP_OPEN`, is
    rejected with `ERR_EVENT_NOT_SETTLABLE` — the same code that guards opening RSVPs and
    cancellation against the wrong state."
    (Event 18:00-20:00; settle attempted with the clock at 19:00.)

    Design: Corner/state_machines/event_settle_before_end_rejected
    """
    event = create_event(room="RECITAL_HALL", title="Artist Series: Opening",
                         start_at="2026-06-01T18:00:00Z", end_at="2026-06-01T20:00:00Z",
                         capacity=50, artist_guarantee_cents=200_000, split_pct=0.70)
    open_event_rsvp(event["id"])
    set_clock("2026-06-01T19:00:00Z")

    res = api.settle_event(event["id"], {"gross_cents": 250_000}, MANAGER)
    validate_error(res, "ERR_EVENT_NOT_SETTLABLE")
    after = get_event(event["id"])
    assert after["status"] == "RSVP_OPEN", "rejected settle must not change state"


def test_artist_payout_guarantee_floor_and_split_branch(api):
    """PRD §3.9: "The artist's `payout_cents` is the greater of the `artist_guarantee_cents`
    and the `split_pct` share of the gross rounded half-up to whole cents, and the event
    reaches its terminal `SETTLED`."
    (Guarantee 200000, split 0.70: gross 250000 -> max(200000, 175000) == 200000; gross
    400000 -> max(200000, 280000) == 280000.)

    Design: Corner/calculations/artist_payout_guarantee_floor_and_split_branch
    """
    e1 = create_event(room="MAIN_SHOWROOM", title="Artist Series A",
                      start_at="2026-06-02T18:00:00Z", end_at="2026-06-02T20:00:00Z",
                      capacity=50, artist_guarantee_cents=200_000, split_pct=0.70)
    e2 = create_event(room="MAIN_SHOWROOM", title="Artist Series B",
                      start_at="2026-06-02T21:00:00Z", end_at="2026-06-02T23:00:00Z",
                      capacity=50, artist_guarantee_cents=200_000, split_pct=0.70)
    open_event_rsvp(e1["id"])
    open_event_rsvp(e2["id"])
    set_clock("2026-06-03T00:00:00Z")

    settled_1 = validate_success(api.settle_event(e1["id"], {"gross_cents": 250_000}, MANAGER), 200)
    assert settled_1["status"] == "SETTLED"
    assert settled_1["payout_cents"] == 200_000, "guarantee branch wins below the split"

    settled_2 = validate_success(api.settle_event(e2["id"], {"gross_cents": 400_000}, MANAGER), 200)
    assert settled_2["status"] == "SETTLED"
    assert settled_2["payout_cents"] == 280_000, "split branch wins above the guarantee"
