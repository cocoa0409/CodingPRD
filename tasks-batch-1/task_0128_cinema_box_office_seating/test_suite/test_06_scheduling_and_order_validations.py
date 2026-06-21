"""Scheduling-time and order-time validation errors, plus pricing-profile and
rental-settlement variant calculations.
"""
from test_helpers import TEST_USERS, get_success_data, validate_error
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import create_showtime_payload

MANAGER = TEST_USERS["manager_headers"]
AGENT = TEST_USERS["agent_headers"]


# ===========================================================================
# Corner/validations/*
# ===========================================================================

def test_matinee_after_cutoff_rejected(api):
    """PRD §3.2: "If the chosen profile is MATINEE but the screening's local start
    hour is 17 or later, the request is rejected with ERR_MATINEE_WINDOW_VIOLATION."

    Design: Corner/validations/matinee_after_cutoff_rejected
    """
    base = fx.setup_base(seat_count=4)
    payload = create_showtime_payload(
        base["film"]["id"], "2026-06-10T18:00:00.000Z",
        pricing_profile="MATINEE", base_price_cents=1000,
    )
    resp = api.create_showtime(base["auditorium"]["id"], payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_MATINEE_WINDOW_VIOLATION.value)


def test_box_office_with_nonzero_fee_rejected(api):
    """PRD §3.2: "a RENTAL screening must carry a positive private_rental_fee_cents,
    while a BOX_OFFICE screening must carry a fee of exactly 0, and any other
    combination is rejected with ERR_RENTAL_FEE_INVALID (the field defaults to 0
    when omitted)."

    Design: Corner/validations/rental_fee_invalid_on_box_office_with_fee
    """
    base = fx.setup_base(seat_count=4)
    payload = create_showtime_payload(
        base["film"]["id"], "2026-06-10T20:00:00.000Z",
        pricing_profile="STANDARD", base_price_cents=1000,
        rental_basis="BOX_OFFICE", private_rental_fee_cents=5000,
    )
    resp = api.create_showtime(base["auditorium"]["id"], payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_RENTAL_FEE_INVALID.value)


def test_split_schedule_missing_week0_rejected(api):
    """PRD §3.1: "The schedule must contain a term whose week_index is 0, and every
    distributor_pct must lie between 0 and 1 inclusive; a schedule missing the week-0
    term or carrying any percentage outside that range is rejected with
    ERR_INVALID_SPLIT_SCHEDULE."

    Design: Corner/validations/invalid_split_schedule_missing_week0_rejected
    """
    distributor = fx.make_distributor()
    payload = {
        "title": "F", "runtime_minutes": 90, "distributor_id": distributor["id"],
        "release_date": "2026-06-01T00:00:00.000Z",
        "split_schedule": [{"week_index": 2, "distributor_pct": 0.50}],
    }
    resp = api.create_film(payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_SPLIT_SCHEDULE.value)


def test_seat_not_on_showtime_rejected(api):
    """PRD §3.4: "Every requested seat must belong to the order's showtime; a seat
    that is not part of that screening's map is rejected with
    ERR_SEAT_NOT_ON_SHOWTIME."

    Design: Corner/validations/seat_not_on_showtime_rejected
    """
    ctx = fx.setup_two_on_sale_showtimes(
        base_price_cents=1000,
        starts_at_x="2026-06-10T20:00:00.000Z",
        starts_at_y="2026-06-12T20:00:00.000Z",
    )
    member = fx.make_member()
    # Order on X requests a seat from Y.
    resp = api.create_order(
        ctx["showtime_x"]["id"],
        {"member_id": member["id"], "seat_ids": ctx["seats_y"][:1],
         "expected_showtime_version": ctx["showtime_x"]["version"]},
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_SEAT_NOT_ON_SHOWTIME.value)


def test_seat_unavailable_when_held_by_another_order(api):
    """PRD §3.4: "Each requested seat must currently be FREE — not held or sold by
    another live order — and a seat that is already taken is rejected with
    ERR_SEAT_UNAVAILABLE."

    Design: Corner/validations/seat_unavailable_when_held_by_another_order
    """
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000)
    seat0 = ctx["seat_ids"][0]
    member_a = fx.make_member(email="a@x.com", full_name="A")
    member_b = fx.make_member(email="b@x.com", full_name="B")

    # A holds seat0.
    fx.create_held_order(ctx["showtime"], member_a, [seat0])
    # B requests the same seat using the current (advanced) version.
    v2 = fx.current_version(ctx["showtime"]["id"])
    resp = api.create_order(
        ctx["showtime"]["id"],
        {"member_id": member_b["id"], "seat_ids": [seat0], "expected_showtime_version": v2},
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_SEAT_UNAVAILABLE.value)


def test_rental_showtime_rejects_per_seat_order(api):
    """PRD §3.4: "A RENTAL screening cannot be sold seat by seat at all; any per-seat
    order against a rental screening is rejected with ERR_RENTAL_NO_SEAT_SALES."

    Design: Corner/validations/rental_showtime_rejects_per_seat_order
    """
    ctx = fx.setup_on_sale_showtime(
        base_price_cents=0, rental_basis="RENTAL", private_rental_fee_cents=80000,
    )
    member = fx.make_member()
    resp = api.create_order(
        ctx["showtime"]["id"],
        {"member_id": member["id"], "seat_ids": ctx["seat_ids"][:1],
         "expected_showtime_version": ctx["showtime"]["version"]},
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_RENTAL_NO_SEAT_SALES.value)


def test_refund_after_showtime_started_past_showtime(api):
    """PRD §3.7: "A refund attempted at or after the screening's start, outside a
    cancel cascade, is rejected with ERR_PAST_SHOWTIME."

    Design: Corner/validations/refund_after_showtime_started_past_showtime
    """
    ctx = fx.setup_paid_order(base_price_cents=1000, num_seats=1, starts_at="2026-06-10T20:00:00.000Z")
    # Advance to just after the showtime's start.
    fx.advance_clock("2026-06-10T20:30:00.000Z")
    resp = api.refund_order(ctx["order"]["id"], {"refund_destination": "ORIGINAL"}, AGENT)
    validate_error(resp, ApiErrorId.ERR_PAST_SHOWTIME.value)


# ===========================================================================
# Corner/calculations/* (matinee multiplier, rental flat cut, BRONZE list price)
# ===========================================================================

def test_matinee_profile_applies_070_multiplier(api):
    """PRD §2.8: "Each profile selects a multiplier applied to the base fare:
    STANDARD multiplies by 1.00, MATINEE by 0.70, and PEAK by 1.30."

    Design: Corner/calculations/matinee_profile_applies_070_multiplier
    """
    # MATINEE start hour 10 (< 17), base 1200 -> round(1200*0.70) = 840.
    ctx = fx.setup_on_sale_showtime(
        base_price_cents=1200, pricing_profile="MATINEE",
        starts_at="2026-06-10T10:00:00.000Z", now="2026-06-02T08:00:00.000Z",
    )
    member = fx.make_member()
    order = fx.create_held_order(ctx["showtime"], member, ctx["seat_ids"][:1])
    tickets = get_success_data(api.list_order_tickets(order["id"], MANAGER))
    assert tickets[0]["provisional_price_cents"] == 840


def test_rental_settlement_flat_distributor_cut(api):
    """PRD §3.9: "For a RENTAL screening ... the applied_distributor_pct is the fixed
    rental cut of 0.10, the distributor_share_cents is that flat fee multiplied by
    0.10 rounded half up to whole cents, and the house_share_cents is the flat fee
    minus that distributor share."

    Design: Corner/calculations/rental_settlement_flat_distributor_cut
    """
    base = fx.setup_base(seat_count=4)
    showtime = fx.schedule_showtime(
        base["auditorium"]["id"], base["film"]["id"], starts_at="2026-06-05T13:00:00.000Z",
        pricing_profile="STANDARD", base_price_cents=0,
        rental_basis="RENTAL", private_rental_fee_cents=80000,
    )
    fx.open_showtime(showtime["id"])
    fx.advance_clock("2026-06-05T15:00:00.000Z")
    closed = get_success_data(api.close_showtime(showtime["id"], MANAGER))
    assert closed["status"] == "CLOSED"

    settlements = get_success_data(api.get_showtime_settlement(showtime["id"], MANAGER))
    s = settlements[0]
    assert s["gross_receipts_cents"] == 80000
    assert s["distributor_share_cents"] == 8000  # round(80000 * 0.10)
    assert s["house_share_cents"] == 72000


def test_combo_bronze_member_pays_list_price(api):
    """PRD §3.5: "For a BRONZE member the member_discount_pct is ignored entirely and
    every combo is charged at list price."

    Design: Corner/calculations/combo_bronze_member_pays_list_price
    """
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000)
    combo = fx.make_combo(name="C1", price_cents=995, member_discount_pct=0.125)
    member = fx.make_member()  # BRONZE, 0 points

    # combos_subtotal_cents is computed at payment (PRD §3.5), so pay before reading it.
    order = fx.create_paid_order(ctx["showtime"], member, ctx["seat_ids"][:1], combo_ids=[combo["id"]])
    member_now = get_success_data(api.get_member(member["id"], MANAGER))
    assert member_now["tier"] == "BRONZE"
    assert order["combos_subtotal_cents"] == 995  # no discount for BRONZE
