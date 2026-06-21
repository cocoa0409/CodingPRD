"""Occupancy / lodging tax remittance: ESTIMATED vs FINAL sweep divergence and
the double-remit guard.

Covers queue-A dual_variant_calc (tax remittance) and queue-B validation corners.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    assert_tax_remittance,
    create_inn_payload,
    create_room_payload,
    create_guest_payload,
    create_booking_payload,
    create_gift_certificate_payload,
    create_tax_remittance_payload,
    TEST_USERS,
    set_clock,
    open_remittance,
)
from test_helpers import api_client

INNKEEPER = TEST_USERS["innkeeper_headers"]
FINANCE = TEST_USERS["finance_headers"]


def _build_inn_two_rooms_guest(api, tax_bps, base_rate=30000):
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="Cedar Inn", lodging_tax_rate_bps=tax_bps), INNKEEPER))
    room_a = get_success_data(api.create_room(
        inn["id"], create_room_payload(inn["id"], name="Oak", base_rate_cents=base_rate,
                                       max_occupancy=2), INNKEEPER))
    room_b = get_success_data(api.create_room(
        inn["id"], create_room_payload(inn["id"], name="Elm", base_rate_cents=base_rate,
                                       max_occupancy=2), INNKEEPER))
    guest = get_success_data(api.create_guest(
        inn["id"], create_guest_payload(inn["id"], full_name="Bo G", email="bo@x.com"), INNKEEPER))
    return inn, room_a, room_b, guest


def _redeem_and_confirm(api, inn_id, room_id, booking_id, amount=34215, face=90000):
    gift = get_success_data(api.create_gift_certificate(
        inn_id, create_gift_certificate_payload(inn_id, face), FINANCE))
    get_success_data(api.redeem_gift(
        inn_id, booking_id,
        {"gift_certificate_id": gift["id"], "amount_cents": amount,
         "expected_gift_certificate_version": gift["version"]},
        INNKEEPER))
    room = get_success_data(api.get_room(inn_id, room_id, INNKEEPER))
    get_success_data(api.confirm_booking(
        inn_id, booking_id, {"expected_room_version": room["version"]}, INNKEEPER))


def _setup_one_checked_out_one_confirmed(api):
    """P1 -> CHECKED_OUT (room_a), P2 -> CONFIRMED only (room_b). Both 3 nights
    checking out 2026-05-12, tax 1450 bps, base 30000 -> lodging_tax 13050 each."""
    set_clock("2026-05-01T00:00:00Z")
    inn, room_a, room_b, guest = _build_inn_two_rooms_guest(api, 1450, base_rate=30000)
    # P1
    p1 = get_success_data(api.create_booking(
        inn["id"], create_booking_payload(inn["id"], room_a["id"], guest["id"],
                                          "2026-05-09", "2026-05-12", channel="DIRECT",
                                          guest_count=1), INNKEEPER))
    _redeem_and_confirm(api, inn["id"], room_a["id"], p1["id"])
    set_clock("2026-05-09T16:00:00Z")
    get_success_data(api.check_in(inn["id"], p1["id"], INNKEEPER))
    set_clock("2026-05-12T11:00:00Z")
    get_success_data(api.check_out(inn["id"], p1["id"], INNKEEPER))
    # P2 -> only confirmed
    p2 = get_success_data(api.create_booking(
        inn["id"], create_booking_payload(inn["id"], room_b["id"], guest["id"],
                                          "2026-05-09", "2026-05-12", channel="DIRECT",
                                          guest_count=1), INNKEEPER))
    _redeem_and_confirm(api, inn["id"], room_b["id"], p2["id"])
    return inn, p1, p2


def test_estimated_remittance_sweeps_confirmed_and_checked_out(api):
    """PRD §3.9: "An `ESTIMATED` remittance is a forward-looking accrual: it
    sweeps bookings in `CONFIRMED`, `CHECKED_IN`, or `CHECKED_OUT` status. A
    `FINAL` remittance sweeps only realized revenue: bookings in `CHECKED_OUT`
    status."
    PRD §3.9: "At open time the system records `swept_booking_count`, the number
    of bookings in the pool, and `tax_total_cents`, the straight sum of the
    already-rounded `lodging_tax_cents` across those bookings."

    Design: Difficulty/dual_variant_calc/tax_remittance_estimated_vs_final_diverge
    """
    inn, _p1, _p2 = _setup_one_checked_out_one_confirmed(api)
    est = open_remittance(inn["id"], "2026-05-01", "2026-05-31", "ESTIMATED")
    assert_tax_remittance(est)
    assert est["swept_booking_count"] == 2, "CHECKED_OUT P1 + CONFIRMED P2"
    assert est["tax_total_cents"] == 26100, "13050 + 13050"


def test_final_remittance_sweeps_only_checked_out(api):
    """PRD §3.9: "An `ESTIMATED` remittance is a forward-looking accrual: it
    sweeps bookings in `CONFIRMED`, `CHECKED_IN`, or `CHECKED_OUT` status. A
    `FINAL` remittance sweeps only realized revenue: bookings in `CHECKED_OUT`
    status."

    Design: Difficulty/dual_variant_calc/tax_remittance_estimated_vs_final_diverge
    """
    inn, _p1, _p2 = _setup_one_checked_out_one_confirmed(api)
    fin = open_remittance(inn["id"], "2026-05-01", "2026-05-31", "FINAL")
    assert fin["swept_booking_count"] == 1, "only CHECKED_OUT P1"
    assert fin["tax_total_cents"] == 13050


def test_final_total_never_exceeds_estimated_for_window(api):
    """PRD §3.9: "Because the final pool is a subset of the estimated pool, the
    final total for a window never exceeds the estimated total for the same
    window."

    Design: Difficulty/dual_variant_calc/tax_remittance_estimated_vs_final_diverge
    """
    inn, _p1, _p2 = _setup_one_checked_out_one_confirmed(api)
    est = open_remittance(inn["id"], "2026-05-01", "2026-05-31", "ESTIMATED")
    fin = open_remittance(inn["id"], "2026-05-01", "2026-05-31", "FINAL")
    assert fin["tax_total_cents"] < est["tax_total_cents"]
    assert fin["tax_total_cents"] == 13050
    assert est["tax_total_cents"] == 26100


# ─── queue B: double-remit guard ─────────────────────────────────────────────
def test_double_remit_rejected_after_first_filing(api):
    """PRD §3.9: "Filing is permitted only while the remittance is `OPEN`
    (otherwise `ERR_INVALID_STATE`) and only when none of the swept bookings has
    already been remitted by an earlier filing; if any swept booking already
    carries `remitted` true, the filing is refused with `ERR_ALREADY_REMITTED`
    so the same revenue is never remitted twice."

    Design: Corner/validations/tax_remittance_double_remit_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    inn = get_success_data(api.create_inn(
        create_inn_payload(name="Bb Inn", lodging_tax_rate_bps=1000), INNKEEPER))
    room = get_success_data(api.create_room(
        inn["id"], create_room_payload(inn["id"], name="G", base_rate_cents=10000,
                                       max_occupancy=2), INNKEEPER))
    guest = get_success_data(api.create_guest(
        inn["id"], create_guest_payload(inn["id"], full_name="Pp G", email="ppg@x.com"), INNKEEPER))
    bk = get_success_data(api.create_booking(
        inn["id"], create_booking_payload(inn["id"], room["id"], guest["id"],
                                          "2026-05-09", "2026-05-12", channel="DIRECT",
                                          guest_count=1), INNKEEPER))
    _redeem_and_confirm(api, inn["id"], room["id"], bk["id"], amount=10000, face=50000)
    set_clock("2026-05-09T16:00:00Z")
    get_success_data(api.check_in(inn["id"], bk["id"], INNKEEPER))
    set_clock("2026-05-12T11:00:00Z")
    get_success_data(api.check_out(inn["id"], bk["id"], INNKEEPER))

    # Open BOTH remittances over the same window while the booking is still
    # unremitted, so each freezes the same booking into its swept set at open
    # time (PRD §3.9: the swept set is recorded at open). Filing rem1 stamps the
    # booking remitted=true; filing rem2 then finds that already-remitted booking
    # in its frozen swept set and is refused with ERR_ALREADY_REMITTED. (Opening
    # rem2 *after* rem1 is filed would instead leave rem2's pool empty, since
    # §3.9 excludes already-remitted bookings at open — a vacuous success, not the
    # double-remit guard this test targets.)
    rem1 = open_remittance(inn["id"], "2026-05-01", "2026-05-31", "FINAL")
    rem2 = open_remittance(inn["id"], "2026-05-01", "2026-05-31", "FINAL")
    get_success_data(api.file_tax_remittance(
        inn["id"], rem1["id"], {"expected_tax_remittance_version": rem1["version"]}, FINANCE))
    res = api.file_tax_remittance(
        inn["id"], rem2["id"], {"expected_tax_remittance_version": rem2["version"]}, FINANCE)
    validate_error(res, "ERR_ALREADY_REMITTED")
    after = get_success_data(api.get_tax_remittance(inn["id"], rem2["id"], FINANCE))
    assert after["status"] == "OPEN"
