"""Confirm-gate and dispatch-gate rejections: stale quote, low compliance
score, missing insurance, no confirmed animals, missing deposit, quarantined
animal, unpaid balance, incomplete waiver (PRD §3.4, §3.6, §3.8).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    fixtures as fx,
)
from test_helpers.test_users import make_customer_headers


# =====================================================================
# Corner/validations/quote_stale_after_roster_change_rejected
# =====================================================================
def test_quote_stale_after_roster_change_rejected(api):
    """PRD §3.6: "The quote must be fresh — `quote_fresh` true, meaning no
    roster, add-on, or schedule mutation since the last quote
    (`ERR_QUOTE_STALE`, HTTP 409)."
    PRD §3.4: "Every roster mutation clears the booking's `quote_fresh` to
    false and increments the booking's `version`."

    Design: Corner/validations/quote_stale_after_roster_change_rejected
    """
    ctx = fx.setup_quoted_goat_booking()
    sheep = fx.create_certified_animal("Shelly", "SHEEP", "MEDIUM", 2, 9000)
    # Attaching another animal after the quote stales it.
    fx.attach_animal(ctx["booking"]["id"], sheep["id"])
    resp = api.confirm_booking(ctx["booking"]["id"],
                               make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_QUOTE_STALE)

    booking = fx.get_booking(ctx["booking"]["id"])
    assert booking["quote_fresh"] is False
    assert booking["status"] == "QUOTED", booking["status"]


# =====================================================================
# Corner/validations/low_compliance_score_blocks_confirm
# =====================================================================
def test_low_compliance_score_blocks_confirm(api):
    """PRD §3.6: "The booking's `compliance_screening_score` must be at least
    60 (`ERR_COMPLIANCE_SCORE_TOO_LOW`)."
    PRD §3.4: "`compliance_screening_score` starts at 100 and subtracts 15 per
    in-scope `LARGE` animal, 10 per `MEDIUM`, and 5 per `SMALL`; subtracts 10
    when the venue is `INDOOR`; subtracts 8 when the venue lacks
    `water_access`; subtracts 5 for each handwash station by which the
    requirement exceeds the `planned_handwash_stations` (never below zero);
    subtracts 1 point for every full block of 10 guests beyond the first 30 in
    scope; and adds back 2 points per in-scope animal with `temperament_tier`
    3, with that bonus capped at 10 points."

    Design: Corner/validations/low_compliance_score_blocks_confirm
    """
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer = fx.create_customer()
    venue = fx.create_venue(customer["id"], name="Old Barn Hall",
                            address="3 Barn Rd", venue_type="INDOOR",
                            water_access=False, surface_type="INDOOR_FLOOR")
    ponies = [fx.create_certified_animal(f"Pony{i}", "PONY", "LARGE", 1, 20000)
              for i in range(1, 4)]
    booking = fx.create_booking(customer["id"], venue["id"], guest_count=40,
                                child_guest_count=0,
                                planned_handwash_stations=2)
    for pony in ponies:
        ba = fx.attach_animal(booking["id"], pony["id"])
        fx.confirm_booking_animal(booking["id"], ba["id"])
    quoted = fx.quote(booking["id"])
    # 100 - 45 (3 LARGE) - 10 (INDOOR) - 8 (no water) - 1 (40 guests) = 36.
    assert quoted["compliance_screening_score"] == 36, \
        quoted["compliance_screening_score"]

    resp = api.confirm_booking(booking["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_COMPLIANCE_SCORE_TOO_LOW)


# =====================================================================
# Corner/validations/confirm_without_verified_insurance_rejected
# =====================================================================
def test_confirm_without_verified_insurance_rejected(api):
    """PRD §3.6: "The customer must hold a `VERIFIED` insurance certificate
    with `coverage_amount_cents` of at least 500000 cents for a
    `PRIVATE_PARTY` or at least 1000000 cents for a `SCHOOL_PROGRAM` or
    `LIBRARY_PROGRAM`, and with `expires_at` falling strictly after the
    booking's `end_time` (`ERR_INSURANCE_NOT_VERIFIED`)."

    Design: Corner/validations/confirm_without_verified_insurance_rejected
    """
    # Every earlier gate passes; the customer holds no certificate at all.
    ctx = fx.setup_quoted_goat_booking(with_insurance=False)
    resp = api.confirm_booking(ctx["booking"]["id"],
                               make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INSURANCE_NOT_VERIFIED)


# =====================================================================
# Corner/validations/confirm_with_no_confirmed_animals_rejected
# =====================================================================
def test_confirm_with_no_confirmed_animals_rejected(api):
    """PRD §3.6: "At least one roster attachment must be `CONFIRMED`
    (`ERR_NO_ANIMALS_CONFIRMED`)."

    Design: Corner/validations/confirm_with_no_confirmed_animals_rejected
    """
    # The goat is attached but never confirmed: it stays PROPOSED.
    ctx = fx.setup_quoted_goat_booking(confirm_animal=False)
    resp = api.confirm_booking(ctx["booking"]["id"],
                               make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_ANIMALS_CONFIRMED)


# =====================================================================
# Corner/validations/confirm_without_deposit_rejected
# =====================================================================
def test_confirm_without_deposit_rejected(api):
    """PRD §3.6: "`total_paid_cents` must meet or exceed
    `deposit_amount_cents` (`ERR_DEPOSIT_INSUFFICIENT`)."

    Design: Corner/validations/confirm_without_deposit_rejected
    """
    # Score, handwash, permits (none required), roster, capacity, lead time,
    # quote freshness, and insurance all pass; no payment was ever made.
    ctx = fx.setup_quoted_goat_booking(with_insurance=True)
    assert ctx["quote"]["deposit_amount_cents"] == 4872
    resp = api.confirm_booking(ctx["booking"]["id"],
                               make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT)  # 0 < 4872


# =====================================================================
# Corner/validations/quarantined_animal_attach_confirm_rejected
# =====================================================================
def test_quarantined_animal_attach_confirm_rejected(api):
    """PRD §3.4: "Second, the animal must be `AVAILABLE`; anything else means
    `ERR_ANIMAL_QUARANTINED`."
    PRD §3.2: "**Link 1:** the animal itself moves from `AVAILABLE` to
    `QUARANTINE`."

    Design: Corner/validations/quarantined_animal_attach_confirm_rejected
    """
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer = fx.create_customer()
    venue = fx.create_venue(customer["id"])
    goat = fx.create_animal("Gogo", "GOAT", "SMALL", 3, 8000)
    # FAIL record while the goat is unattached: quarantine, no cascade.
    fx.add_health_record(goat["id"], result="FAIL",
                         valid_until="2026-05-09T00:00:00Z",
                         exam_date="2026-05-09T00:00:00Z")
    assert fx.get_animal(goat["id"])["status"] == "QUARANTINE"

    booking = fx.create_booking(customer["id"], venue["id"], guest_count=10)
    ba = fx.attach_animal(booking["id"], goat["id"])
    resp = api.confirm_booking_animal(booking["id"], ba["id"], fx.COORD)
    validate_error(resp, ApiErrorId.ERR_ANIMAL_QUARANTINED)


# =====================================================================
# Corner/validations/dispatch_with_unpaid_balance_rejected
# =====================================================================
def test_dispatch_with_unpaid_balance_rejected(api):
    """PRD §3.8: "Three gates guard it, in this order: the waiver must be
    `COMPLETE` (`ERR_WAIVER_INCOMPLETE`); the count of `ASSIGNED` staff
    assignments must meet or exceed `required_staff_count`
    (`ERR_STAFF_RATIO_NOT_MET`); and `total_paid_cents` must meet or exceed
    `quoted_total_cents` — the event never rolls with an open balance
    (`ERR_BALANCE_UNPAID`)."

    Design: Corner/validations/dispatch_with_unpaid_balance_rejected
    """
    # Waiver auto-COMPLETE (0 children); one handler meets the staff ratio;
    # only the 4872 deposit of the 16240 quote has been paid.
    ctx = fx.setup_confirmed_goat_booking()
    handler = fx.create_handler("Hank", ["FIRST_AID"])
    fx.assign_handler(ctx["booking"]["id"], handler["id"], "LEAD")
    resp = api.dispatch_booking(ctx["booking"]["id"], fx.COORD)
    validate_error(resp, ApiErrorId.ERR_BALANCE_UNPAID)


# =====================================================================
# Corner/validations/dispatch_with_incomplete_waiver_rejected
# =====================================================================
def test_dispatch_with_incomplete_waiver_rejected(api):
    """PRD §3.8: "Three gates guard it, in this order: the waiver must be
    `COMPLETE` (`ERR_WAIVER_INCOMPLETE`); the count of `ASSIGNED` staff
    assignments must meet or exceed `required_staff_count`
    (`ERR_STAFF_RATIO_NOT_MET`); and `total_paid_cents` must meet or exceed
    `quoted_total_cents` — the event never rolls with an open balance
    (`ERR_BALANCE_UNPAID`)."

    Design: Corner/validations/dispatch_with_incomplete_waiver_rejected
    """
    ctx = fx.setup_confirmed_goat_booking(child_guest_count=5)
    booking_id = ctx["booking"]["id"]
    # Only 2 of the 5 required guardian signatures: waiver PARTIAL.
    fx.sign_waiver(booking_id, ctx["customer"]["id"], 2)
    handler = fx.create_handler("Hank", ["FIRST_AID"])
    fx.assign_handler(booking_id, handler["id"], "LEAD")
    fx.pay(booking_id, ctx["customer"]["id"], 11368)  # balance paid in full
    resp = api.dispatch_booking(booking_id, fx.COORD)
    validate_error(resp, ApiErrorId.ERR_WAIVER_INCOMPLETE)
