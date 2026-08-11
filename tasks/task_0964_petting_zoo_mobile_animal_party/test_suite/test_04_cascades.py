"""Transitive cascades: the depth-3 health-FAIL quarantine cascade and the
depth-2 customer-cancel staff-release cascade (PRD §3.2, §3.7).
"""
from test_helpers import (
    validate_success,
    entries_of_type, sum_of_type,
    fixtures as fx,
)
from test_helpers.test_users import make_customer_headers


# =====================================================================
# Difficulty/transitive_cascade/health_fail_quarantine_cascade
# =====================================================================
def test_health_fail_quarantines_animal_and_removes_attachment(api):
    """PRD §3.2: "**Link 1:** the animal itself moves from `AVAILABLE` to
    `QUARANTINE`."
    PRD §3.2: "**Link 2:** every booking attachment of this animal whose
    status is `PROPOSED` or `CONFIRMED`, on any parent booking that is not in
    a terminal state (`INVOICED` or any of the cancelled states), is removed
    with `removal_reason` `QUARANTINE`."
    PRD §3.2: "**Link 3:** if such a parent booking was `CONFIRMED` and its
    remaining count of `CONFIRMED` roster attachments is now zero, the booking
    itself is cancelled for compliance — it moves to `CANCELLED_COMPLIANCE`
    with the full compliance refund variant of §3.7 (a `FORFEIT` entry of
    everything paid, a `PENALTY` entry, `payment_status` `FORFEITED`) and the
    shared cancel cascade."

    Design: Difficulty/transitive_cascade/health_fail_quarantine_cascade
    """
    ctx = fx.setup_confirmed_goat_booking()
    booking_id = ctx["booking"]["id"]
    goat_id = ctx["animal"]["id"]

    fx.add_health_record(goat_id, result="FAIL",
                         valid_until="2026-06-10T09:00:00Z",
                         exam_date="2026-06-10T09:00:00Z")

    # Link 1
    assert fx.get_animal(goat_id)["status"] == "QUARANTINE"
    # Link 2
    attachments = fx.list_booking_animals(booking_id)
    ba = [a for a in attachments if a["id"] == ctx["booking_animal"]["id"]][0]
    assert ba["status"] == "REMOVED", ba["status"]
    assert ba["removal_reason"] == "QUARANTINE", ba["removal_reason"]
    # Link 3: the goat was the booking's last CONFIRMED animal
    assert fx.get_booking(booking_id)["status"] == "CANCELLED_COMPLIANCE"


def test_health_fail_cascade_forfeits_payments_and_charges_penalty(api):
    """PRD §3.7: "A compliance cancellation refunds nothing at all and
    additionally appends a `PENALTY` ledger entry of 20 percent of
    `quoted_total_cents`, rounded half up. In all variants the unrefunded
    remainder, when nonzero, is appended as a `FORFEIT` entry, and refunds are
    appended as `REFUND` entries."
    PRD §3.7: "Otherwise `payment_status` becomes `REFUND_FULL` when the
    refund equals the amount paid, `REFUND_PARTIAL` when the refund is
    positive but smaller, and `FORFEITED` when nothing is refunded."

    Design: Difficulty/transitive_cascade/health_fail_quarantine_cascade
    """
    ctx = fx.setup_confirmed_goat_booking()
    booking_id = ctx["booking"]["id"]

    fx.add_health_record(ctx["animal"]["id"], result="FAIL",
                         valid_until="2026-06-10T09:00:00Z",
                         exam_date="2026-06-10T09:00:00Z")

    booking = fx.get_booking(booking_id)
    assert booking["payment_status"] == "FORFEITED", booking["payment_status"]

    ledger = fx.list_ledger(booking_id)
    assert sum_of_type(ledger, "PAYMENT") == 4872
    assert sum_of_type(ledger, "FORFEIT") == 4872  # everything paid
    # round_half_up(0.20 * 16240)
    assert sum_of_type(ledger, "PENALTY") == 3248
    assert entries_of_type(ledger, "REFUND") == []


# =====================================================================
# Difficulty/transitive_cascade/customer_cancel_staff_release_cascade
# =====================================================================
def test_customer_cancel_releases_staff_and_refunds_in_full(api):
    """PRD §3.7: "168 hours or more before start refunds everything paid"
    PRD §3.7: "Every `ASSIGNED` staff assignment moves to `RELEASED` with
    `release_reason` `BOOKING_CANCELLED`, and each release recomputes the
    affected handler's `scheduled_minutes_total`."

    Design: Difficulty/transitive_cascade/customer_cancel_staff_release_cascade
    """
    ctx = fx.setup_confirmed_goat_booking()
    booking_id = ctx["booking"]["id"]
    handler = fx.create_handler("Hank", ["FIRST_AID"])
    assignment = fx.assign_handler(booking_id, handler["id"], "LEAD")

    cancelled = validate_success(api.cancel_booking(
        booking_id, "CUSTOMER", make_customer_headers(ctx["customer"]["id"])))
    assert cancelled["status"] == "CANCELLED_CUSTOMER", cancelled["status"]
    # Clock 2026-05-10, event 2026-06-17: >= 168h tier, 100% of 4872.
    assert cancelled["payment_status"] == "REFUND_FULL", cancelled["payment_status"]

    assignments = fx.list_staff_assignments(booking_id)
    sa = [a for a in assignments if a["id"] == assignment["id"]][0]
    assert sa["status"] == "RELEASED", sa["status"]
    assert sa["release_reason"] == "BOOKING_CANCELLED", sa["release_reason"]


def test_customer_cancel_release_restores_handler_minutes_and_ledger(api):
    """PRD §3.3: "Each handler carries a derived `scheduled_minutes_total`:
    the sum of event durations, in minutes, over all of that handler's staff
    assignments currently in `ASSIGNED` status."
    PRD §3.7: "In all variants the unrefunded remainder, when nonzero, is
    appended as a `FORFEIT` entry, and refunds are appended as `REFUND`
    entries."

    Design: Difficulty/transitive_cascade/customer_cancel_staff_release_cascade
    """
    ctx = fx.setup_confirmed_goat_booking()
    booking_id = ctx["booking"]["id"]
    handler = fx.create_handler("Hank", ["FIRST_AID"])
    fx.assign_handler(booking_id, handler["id"], "LEAD")
    # The 120-minute event counts against the handler while ASSIGNED.
    assert fx.get_handler(handler["id"])["scheduled_minutes_total"] == 120

    validate_success(api.cancel_booking(
        booking_id, "CUSTOMER", make_customer_headers(ctx["customer"]["id"])))
    # Link 2: the release cascade recomputes the total back to 0.
    assert fx.get_handler(handler["id"])["scheduled_minutes_total"] == 0

    ledger = fx.list_ledger(booking_id)
    assert sum_of_type(ledger, "PAYMENT") == 4872
    assert sum_of_type(ledger, "REFUND") == 4872  # 100% tier
    assert entries_of_type(ledger, "FORFEIT") == []
