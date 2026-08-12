"""Booking state-machine guards, terminal lockdown, the compound waiver
machine, payment ledger side effects, and per-mutation version increments
(PRD §2.4, §2.9, §3.6, §3.7, §3.8).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    fixtures as fx,
)
from test_helpers.test_users import make_customer_headers


# =====================================================================
# Corner/state_machines/booking_in_draft_cannot_complete
# =====================================================================
def test_booking_in_draft_cannot_complete(api):
    """PRD §3.8: "Closing the event moves the booking from `IN_PROGRESS` to
    `COMPLETED`."
    PRD §2.9: "**State validity** — the target resource is in a valid
    from-state for the requested transition, including the rule that terminal
    states accept no further transitions; failures are `ERR_INVALID_STATE`."
    PRD §3.8: "Completion recomputes the compliance score in its audited
    variant into `compliance_audited_score` (null until now)"

    Design: Corner/state_machines/booking_in_draft_cannot_complete
    """
    ctx = fx.setup_draft_booking(guest_count=10)
    resp = api.complete_booking(ctx["booking"]["id"], 10, fx.COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    booking = fx.get_booking(ctx["booking"]["id"])
    assert booking["status"] == "DRAFT", booking["status"]
    assert booking["compliance_audited_score"] is None


# =====================================================================
# Corner/state_machines/cancelled_booking_cannot_dispatch
# =====================================================================
def test_cancelled_booking_cannot_dispatch(api):
    """PRD §3.7: "Any attempt from another state is `ERR_INVALID_STATE`, and
    the terminal states — `INVOICED`, `CANCELLED_CUSTOMER`,
    `CANCELLED_WEATHER`, `CANCELLED_COMPLIANCE` — accept no transitions at
    all."
    PRD §3.7: "When the booking was never paid (`total_paid_cents` is zero),
    no ledger entries are created for any variant and `payment_status` stays
    `UNPAID`."
    PRD §3.7: "The booking's `quote_fresh` clears to false and its `version`
    increments."

    Design: Corner/state_machines/cancelled_booking_cannot_dispatch
    """
    ctx = fx.setup_draft_booking(guest_count=10)
    booking_id = ctx["booking"]["id"]
    v_pre = ctx["booking"]["version"]

    cancelled = validate_success(api.cancel_booking(
        booking_id, "CUSTOMER", make_customer_headers(ctx["customer"]["id"])))
    assert cancelled["status"] == "CANCELLED_CUSTOMER", cancelled["status"]
    assert cancelled["version"] == v_pre + 1

    resp = api.dispatch_booking(booking_id, fx.COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert fx.get_booking(booking_id)["status"] == "CANCELLED_CUSTOMER"
    # total_paid_cents was 0: the refund waterfall wrote nothing.
    assert fx.list_ledger(booking_id) == []


# =====================================================================
# Corner/state_machines/waiver_compound_status_progression
# =====================================================================
def test_waiver_compound_status_progression(api):
    """PRD §3.6: "Creating a booking auto-creates exactly one waiver whose
    `required_signatures` equals the booking's `child_guest_count` and whose
    `signed_count` starts at 0; the waiver's `status` is derived from those
    two numbers — `PENDING` when nothing is signed, `PARTIAL` when some but
    not all required signatures are in, and `COMPLETE` when the counts meet."

    Design: Corner/state_machines/waiver_compound_status_progression
    """
    ctx = fx.setup_draft_booking(guest_count=10, child_guest_count=5)
    booking_id = ctx["booking"]["id"]

    waiver = fx.get_waiver(booking_id, ctx["customer"]["id"])
    assert waiver["status"] == "PENDING", waiver["status"]
    assert waiver["required_signatures"] == 5  # equals child_guest_count
    assert waiver["signed_count"] == 0

    partial = validate_success(api.sign_waiver(
        booking_id, 2, make_customer_headers(ctx["customer"]["id"])))
    assert partial["status"] == "PARTIAL", partial["status"]
    assert partial["signed_count"] == 2

    complete = validate_success(api.sign_waiver(
        booking_id, 3, make_customer_headers(ctx["customer"]["id"])))
    assert complete["status"] == "COMPLETE", complete["status"]
    assert complete["signed_count"] == 5


# =====================================================================
# Corner/state_machines/payment_creates_ledger_side_effect
# =====================================================================
def test_payment_creates_ledger_side_effect(api):
    """PRD §3.6: "Each accepted payment appends a `PAYMENT` ledger entry,
    recomputes `total_paid_cents`, and advances `payment_status`"
    PRD §2.10: "A booking's `total_paid_cents` is always the sum of its
    `PAYMENT` entries and is recomputed whenever a payment is recorded."

    Design: Corner/state_machines/payment_creates_ledger_side_effect
    """
    ctx = fx.setup_quoted_goat_booking()  # quoted 16240
    booking_id = ctx["booking"]["id"]

    entry = validate_success(api.create_payment(
        booking_id, {"amount_cents": 1000, "method": "CARD"},
        make_customer_headers(ctx["customer"]["id"])), expected_status=201)
    assert entry["entry_type"] == "PAYMENT", entry["entry_type"]
    assert entry["amount_cents"] == 1000, entry["amount_cents"]

    assert fx.get_booking(booking_id)["total_paid_cents"] == 1000
    ledger = fx.list_ledger(booking_id)
    payments = [e for e in ledger if e["entry_type"] == "PAYMENT"]
    assert len(payments) == 1 and payments[0]["amount_cents"] == 1000


# =====================================================================
# Corner/cross_cutting_layers/booking_version_increments_on_each_mutation
# =====================================================================
def test_booking_version_increments_on_each_mutation(api):
    """PRD §2.4: "`version`, an integer that starts at 1 and increments by
    exactly 1 on every mutation of that resource."
    PRD §3.4: "Every roster mutation clears the booking's `quote_fresh` to
    false and increments the booking's `version`."
    PRD §3.4: "It also sets `quote_fresh` to true and increments the booking's
    `version`."

    Design: Corner/cross_cutting_layers/booking_version_increments_on_each_mutation
    """
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer = fx.create_customer()
    venue = fx.create_venue(customer["id"])
    goat = fx.create_certified_animal()

    booking = fx.create_booking(customer["id"], venue["id"], guest_count=10)
    assert booking["version"] == 1, booking["version"]  # create

    fx.attach_animal(booking["id"], goat["id"])
    after_attach = fx.get_booking(booking["id"])
    assert after_attach["version"] == 2, after_attach["version"]  # roster write

    quoted = fx.quote(booking["id"])
    assert quoted["version"] == 3, quoted["version"]  # quote
