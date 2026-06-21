"""Room temporal conflicts and cross-entity confirm dependencies: half-open
date-interval overlap, zero-gap back-to-back, the instant-level turnover buffer,
RETIRED-room blocking, and the two-night-minimum floor.

Covers queue-A resource_temporal_overlap, boundary_precision (back-to-back),
cross_entity_state_dependency (confirm requires room ACTIVE), and queue-B corners.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_inn_payload,
    create_room_payload,
    create_rate_period_payload,
    create_guest_payload,
    create_booking_payload,
    create_gift_certificate_payload,
    TEST_USERS,
    set_clock,
    setup_inn_room_guest,
    create_booking,
    cover_deposit_via_gift,
    confirm_booking,
    current_room_version,
)
from test_helpers import api_client

INNKEEPER = TEST_USERS["innkeeper_headers"]
HOUSEKEEPER = TEST_USERS["housekeeper_headers"]
FINANCE = TEST_USERS["finance_headers"]


def _confirm_via_gift(api, inn_id, room_id, guest_id, checkin, checkout, amount=None, face=50000):
    bk = create_booking(inn_id, room_id, guest_id, checkin, checkout)
    # Cover the booking's actual deposit_due_cents (channel policy with first-night
    # floor, PRD §3.3) so the confirm's deposit-coverage gate is satisfied; the
    # gift face is sized generously so the redemption itself never under-covers.
    redeem = amount if amount is not None else bk["deposit_due_cents"]
    cover_deposit_via_gift(inn_id, bk["id"], redeem, gift_face_cents=face)
    return confirm_booking(inn_id, room_id, bk["id"]), bk


# ─── resource_temporal_overlap: strict date overlap ──────────────────────────
def test_overlapping_confirm_rejected_double_booked(api):
    """PRD §3.4: "The overlap check (priority 70) looks at the half-open night
    interval running from `checkin_date` up to `checkout_date` and rejects the
    confirm with `ERR_ROOM_DOUBLE_BOOKED` if any other `CONFIRMED` or
    `CHECKED_IN` booking on the same room overlaps it; because the interval is
    half-open, a booking that ends exactly on the night another begins does not
    overlap, so same-day back-to-back turnover is permitted at the date level."

    Design: Difficulty/resource_temporal_overlap/room_date_interval_half_open_overlap_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Crag Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Slate", "base_rate_cents": 10000})
    # bk1: 10-10..10-14 confirmed.
    _confirm_via_gift(api, inn["id"], room["id"], guest["id"], "2026-10-10", "2026-10-14")
    # bk2: 10-12..10-13 strictly inside bk1.
    bk2 = create_booking(inn["id"], room["id"], guest["id"], "2026-10-12", "2026-10-13")
    cover_deposit_via_gift(inn["id"], bk2["id"], 10000, gift_face_cents=50000)
    rv = current_room_version(inn["id"], room["id"])
    res = api.confirm_booking(inn["id"], bk2["id"], {"expected_room_version": rv}, INNKEEPER)
    validate_error(res, "ERR_ROOM_DOUBLE_BOOKED")


def test_overlapping_confirm_leaves_second_booking_pending(api):
    """PRD §3.4: "rejects the confirm with `ERR_ROOM_DOUBLE_BOOKED` if any other
    `CONFIRMED` or `CHECKED_IN` booking on the same room overlaps it; because the
    interval is half-open, a booking that ends exactly on the night another
    begins does not overlap, so same-day back-to-back turnover is permitted at
    the date level."

    Design: Difficulty/resource_temporal_overlap/room_date_interval_half_open_overlap_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Crag2 Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Slate2", "base_rate_cents": 10000})
    _confirm_via_gift(api, inn["id"], room["id"], guest["id"], "2026-10-10", "2026-10-14")
    bk2 = create_booking(inn["id"], room["id"], guest["id"], "2026-10-12", "2026-10-13")
    cover_deposit_via_gift(inn["id"], bk2["id"], 10000, gift_face_cents=50000)
    rv = current_room_version(inn["id"], room["id"])
    api.confirm_booking(inn["id"], bk2["id"], {"expected_room_version": rv}, INNKEEPER)
    after = get_success_data(api.get_booking(inn["id"], bk2["id"], INNKEEPER))
    assert after["reservation_status"] == "PENDING"


# ─── boundary_precision: half-open zero-gap back-to-back ─────────────────────
def test_zero_gap_back_to_back_confirm_succeeds(api):
    """PRD §3.4: "because the interval is half-open, a booking that ends exactly
    on the night another begins does not overlap, so same-day back-to-back
    turnover is permitted at the date level."

    Design: Difficulty/boundary_precision_check/half_open_interval_zero_gap_back_to_back_allowed
    """
    set_clock("2026-08-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Reef Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Pearl", "base_rate_cents": 10000})
    # bk1: 09-10..09-12 confirmed.
    _confirm_via_gift(api, inn["id"], room["id"], guest["id"], "2026-09-10", "2026-09-12",
                      amount=10000, face=10000)
    # bk2 starts EXACTLY on bk1's checkout night 09-12 -> no overlap.
    bk2, _raw = _confirm_via_gift(api, inn["id"], room["id"], guest["id"], "2026-09-12",
                                  "2026-09-14", amount=10000, face=10000)
    assert bk2["reservation_status"] == "CONFIRMED"


def test_back_to_back_does_not_collide_with_prior_interval(api):
    """PRD §3.4: "The overlap check (priority 70) looks at the half-open night
    interval running from `checkin_date` up to `checkout_date` and rejects the
    confirm with `ERR_ROOM_DOUBLE_BOOKED` if any other `CONFIRMED` or
    `CHECKED_IN` booking on the same room overlaps it; because the interval is
    half-open, a booking that ends exactly on the night another begins does not
    overlap, so same-day back-to-back turnover is permitted at the date level."

    Design: Difficulty/boundary_precision_check/half_open_interval_zero_gap_back_to_back_allowed
    """
    set_clock("2026-08-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Reef2 Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Pearl2", "base_rate_cents": 10000})
    bk1, _r1 = _confirm_via_gift(api, inn["id"], room["id"], guest["id"], "2026-09-10",
                                 "2026-09-12", amount=10000, face=10000)
    bk2, _r2 = _confirm_via_gift(api, inn["id"], room["id"], guest["id"], "2026-09-12",
                                 "2026-09-14", amount=10000, face=10000)
    assert bk1["reservation_status"] == "CONFIRMED"
    assert bk2["reservation_status"] == "CONFIRMED"


# ─── resource_temporal_overlap: instant-level turnover buffer ────────────────
def test_checkin_before_turnover_ready_rejected(api):
    """PRD §3.4: "The turnover gate (priority 72) looks at the room's most recent
    non-`SKIPPED` housekeeping task: it must be `DONE` (or there must be no such
    task at all for a fresh room) and its `ready_after` instant must be at or
    before the current logical clock; a check-in attempted while turnover is
    unmet is rejected with `ERR_TURNOVER_NOT_READY`."

    Design: Difficulty/resource_temporal_overlap/room_turnover_buffer_instant_gap_blocks_checkin
    """
    set_clock("2026-11-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Knoll Inn", "lodging_tax_rate_bps": 0, "turnover_minutes": 180},
        room_overrides={"name": "Birch", "base_rate_cents": 10000})
    # bk1: 11-10..11-12, full lifecycle to CHECKED_OUT (ready_after = 11-12 11:00 + 180m = 14:00).
    bk1, _r1 = _confirm_via_gift(api, inn["id"], room["id"], guest["id"], "2026-11-10",
                                 "2026-11-12", amount=10000, face=50000)
    set_clock("2026-11-10T16:00:00Z")
    get_success_data(api.check_in(inn["id"], bk1["id"], INNKEEPER))
    set_clock("2026-11-12T11:00:00Z")
    get_success_data(api.check_out(inn["id"], bk1["id"], INNKEEPER))
    # bk2: 11-12..11-14, confirm OK (zero-gap date overlap allowed).
    bk2, _r2 = _confirm_via_gift(api, inn["id"], room["id"], guest["id"], "2026-11-12",
                                 "2026-11-14", amount=10000, face=50000)
    assert bk2["reservation_status"] == "CONFIRMED"
    # Clock 12:00Z is before ready_after 14:00Z -> turnover not ready.
    set_clock("2026-11-12T12:00:00Z")
    res = api.check_in(inn["id"], bk2["id"], INNKEEPER)
    validate_error(res, "ERR_TURNOVER_NOT_READY")


def test_turnover_buffer_leaves_booking_confirmed(api):
    """PRD §3.4: "a check-in attempted while turnover is unmet is rejected with
    `ERR_TURNOVER_NOT_READY`. This buffer is an instant-level gap distinct from
    the date-level overlap rule of confirmation."

    Design: Difficulty/resource_temporal_overlap/room_turnover_buffer_instant_gap_blocks_checkin
    """
    set_clock("2026-11-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Knoll2 Inn", "lodging_tax_rate_bps": 0, "turnover_minutes": 180},
        room_overrides={"name": "Birch2", "base_rate_cents": 10000})
    bk1, _r1 = _confirm_via_gift(api, inn["id"], room["id"], guest["id"], "2026-11-10",
                                 "2026-11-12", amount=10000, face=50000)
    set_clock("2026-11-10T16:00:00Z")
    get_success_data(api.check_in(inn["id"], bk1["id"], INNKEEPER))
    set_clock("2026-11-12T11:00:00Z")
    get_success_data(api.check_out(inn["id"], bk1["id"], INNKEEPER))
    bk2, _r2 = _confirm_via_gift(api, inn["id"], room["id"], guest["id"], "2026-11-12",
                                 "2026-11-14", amount=10000, face=50000)
    set_clock("2026-11-12T12:00:00Z")
    api.check_in(inn["id"], bk2["id"], INNKEEPER)
    after = get_success_data(api.get_booking(inn["id"], bk2["id"], INNKEEPER))
    assert after["reservation_status"] == "CONFIRMED"


# ─── cross_entity_state_dependency: confirm requires room ACTIVE ─────────────
# NOTE: a test asserting the *error_id* of a confirm against a RETIRED room was
# removed here. PRD §3.4 requires "the room to be `ACTIVE`" for confirmation but
# names NO error_id for that confirm-time gate (it names ERR_ROOM_DOUBLE_BOOKED,
# ERR_DEPOSIT_NOT_MET, ERR_INVALID_STATE for non-PENDING, and ERR_STALE_ROOM_VERSION
# for the others). §3.2's ERR_RESOURCE_RETIRED is scoped verbatim to booking
# *creation* ("Several checks gate booking creation ... Booking against a RETIRED
# room ..."), not confirm. The error surfaced at confirm time is therefore not
# uniquely derivable from PRD prose (a faithful impl could raise ERR_INVALID_STATE
# for "room not ACTIVE" or reuse ERR_RESOURCE_RETIRED), so that assertion is deleted
# per the PRD-First unique-derivability rule. The behavioural consequence that IS
# derivable — the booking stays PENDING after a rejected confirm — is kept below.


def test_confirm_against_retired_room_leaves_pending(api):
    """PRD §3.4: "Confirming a booking advances it from `PENDING` to `CONFIRMED`.
    Confirmation requires the booking to be `PENDING`, the room to be `ACTIVE`,
    the deposit to be fully covered (`deposit_paid_cents` at least
    `deposit_due_cents`, possibly reached via gift redemption), and the night
    interval to be free of conflict."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_room_active
    """
    set_clock("2026-02-01T00:00:00Z")
    inn, room, guest = setup_inn_room_guest(
        inn_overrides={"name": "Bay2 Inn", "lodging_tax_rate_bps": 0},
        room_overrides={"name": "Tide2", "base_rate_cents": 10000})
    bk = create_booking(inn["id"], room["id"], guest["id"], "2026-04-10", "2026-04-12")
    cover_deposit_via_gift(inn["id"], bk["id"], 10000, gift_face_cents=20000)
    rv = current_room_version(inn["id"], room["id"])
    retired = get_success_data(api.retire_room(
        inn["id"], room["id"], {"expected_room_version": rv}, INNKEEPER))
    api.confirm_booking(inn["id"], bk["id"], {"expected_room_version": retired["version"]}, INNKEEPER)
    after = get_success_data(api.get_booking(inn["id"], bk["id"], INNKEEPER))
    assert after["reservation_status"] == "PENDING"


# ─── queue B: two-night minimum ──────────────────────────────────────────────
def test_min_nights_two_night_minimum_rejected(api):
    """PRD §3.2: "And the two-night-minimum rule applies: the system computes
    `nights` and, if the stay touches any night governed by a rate period whose
    `min_nights` exceeds 1, requires `nights` to be at least the largest such
    `min_nights` across all touched periods; a shorter stay is rejected with
    `ERR_MIN_NIGHTS_NOT_MET`."

    Design: Corner/validations/min_nights_two_night_minimum_rejected
    """
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="W Inn", lodging_tax_rate_bps=0), INNKEEPER))
    room = get_success_data(api.create_room(
        inn["id"], create_room_payload(inn["id"], name="G", base_rate_cents=10000,
                                       max_occupancy=2), INNKEEPER))
    get_success_data(api.create_rate_period(
        inn["id"], create_rate_period_payload(
            inn["id"], "2026-08-01", "2026-08-31", label="Peak",
            rate_multiplier_bps=15000, min_nights=2), INNKEEPER))
    guest = get_success_data(api.create_guest(
        inn["id"], create_guest_payload(inn["id"], full_name="Kk G", email="kkg@x.com"), INNKEEPER))
    # 1-night booking 08-10..08-11 inside the min_nights=2 window.
    res = api.create_booking(
        inn["id"],
        create_booking_payload(inn["id"], room["id"], guest["id"], "2026-08-10",
                               "2026-08-11", channel="DIRECT", guest_count=1),
        INNKEEPER)
    validate_error(res, "ERR_MIN_NIGHTS_NOT_MET")
