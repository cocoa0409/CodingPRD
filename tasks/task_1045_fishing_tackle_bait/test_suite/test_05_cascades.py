"""Transitive cascade chains: customer suspension (depth-3: cancel -> seat release ->
waitlist promotion) and guide suspension (depth-2: charter cancel -> booking refund).
"""
from test_helpers import (
    validate_success, get_success_data,
    set_clock, new_customer, new_license_type, issue_license, new_guide, new_charter,
    new_booking, create_paid_booking, TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


def _licensed_customer(dob="1985-01-01"):
    cust = new_customer(date_of_birth=dob)
    lt = new_license_type()
    issue_license(cust["id"], lt["id"])
    return cust


def _suspend_depth3_setup(api):
    """Charter capacity 1 (FULL by A); W1 then W2 WAITLISTED. Returns ids."""
    set_clock("2026-07-15T00:00:00Z")
    guide = new_guide()
    charter = new_charter(guide["id"], title="Solo", start_at="2026-08-01T09:00:00Z",
                          end_at="2026-08-01T12:00:00Z", capacity=1, price_per_seat_cents=10000)
    a = _licensed_customer(dob="1985-01-01")
    ba = new_booking(charter["id"], a["id"], seats=1)  # takes the seat -> FULL
    w1 = _licensed_customer(dob="1988-01-01")
    bw1 = new_booking(charter["id"], w1["id"], seats=1, waitlist_requested=True)
    w2 = _licensed_customer(dob="1989-01-01")
    bw2 = new_booking(charter["id"], w2["id"], seats=1, waitlist_requested=True)
    validate_success(api.set_customer_status(a["id"], {"status": "SUSPENDED"}, MANAGER), 200)
    return {"a": a, "charter": charter, "ba": ba, "bw1": bw1, "bw2": bw2}


# ─── Difficulty: transitive_cascade / customer_suspend_depth3_cancel_release_promote_waitlist
def test_customer_suspend_cancels_own_booking(api):
    """PRD §3.1: "Suspending an active account (ACTIVE → SUSPENDED) is the root of the
    depth-three cascade described in Section 2.8: every booking of that customer still in
    RESERVED or WAITLISTED is cancelled, releasing held seats, possibly returning charters
    from FULL to OPEN, and possibly promoting other customers' waitlisted bookings."

    Design: Difficulty/transitive_cascade/customer_suspend_depth3_cancel_release_promote_waitlist
    """
    ids = _suspend_depth3_setup(api)
    assert get_success_data(api.get_customer(ids["a"]["id"], MANAGER))["status"] == "SUSPENDED"
    ba = get_success_data(api.get_booking(ids["ba"]["id"], MANAGER))
    assert ba["booking_status"] == "CANCELLED"


def test_customer_suspend_promotes_earliest_waitlist(api):
    """PRD §3.5: "the system promotes the earliest-created waitlisted booking (by created_at
    ascending) whose seats fit within the newly available remaining capacity, moving it
    WAITLISTED → RESERVED."

    Design: Difficulty/transitive_cascade/customer_suspend_depth3_cancel_release_promote_waitlist
    """
    ids = _suspend_depth3_setup(api)
    bw1 = get_success_data(api.get_booking(ids["bw1"]["id"], MANAGER))
    bw2 = get_success_data(api.get_booking(ids["bw2"]["id"], MANAGER))
    charter = get_success_data(api.get_charter(ids["charter"]["id"], MANAGER))
    assert bw1["booking_status"] == "RESERVED"   # earliest waitlisted promoted
    assert bw2["booking_status"] == "WAITLISTED"  # later one stays
    assert charter["status"] == "FULL"            # re-filled after promotion


def _suspend_guide_setup(api):
    """Guide with one OPEN charter carrying a PAID 2-seat booking (amount_paid 26000)."""
    set_clock("2026-07-15T00:00:00Z")
    a = _licensed_customer(dob="1985-01-01")
    guide = new_guide()
    charter = new_charter(guide["id"], title="Group", start_at="2026-08-05T09:00:00Z",
                          end_at="2026-08-05T13:00:00Z", capacity=4,
                          price_per_seat_cents=12000, fuel_surcharge_cents=1000)
    booking = create_paid_booking(charter["id"], a["id"], seats=2)  # amount_paid 26000
    validate_success(api.set_guide_status(guide["id"], {"status": "SUSPENDED"}, MANAGER), 200)
    return {"guide": guide, "charter": charter, "booking": booking}


# ─── Difficulty: transitive_cascade / guide_suspend_depth2_cancel_charter_then_refund_booking
def test_guide_suspend_cancels_charter(api):
    """PRD §3.4: "Suspending an available guide (AVAILABLE → SUSPENDED) cancels each of that
    guide's OPEN or FULL charters, which cascades into cancelling and refunding their bookings
    as described below."

    Design: Difficulty/transitive_cascade/guide_suspend_depth2_cancel_charter_then_refund_booking
    """
    ids = _suspend_guide_setup(api)
    assert get_success_data(api.get_guide(ids["guide"]["id"], MANAGER))["status"] == "SUSPENDED"
    charter = get_success_data(api.get_charter(ids["charter"]["id"], MANAGER))
    assert charter["status"] == "CANCELLED"


def test_guide_suspend_full_refunds_paid_booking(api):
    """PRD §3.6: "A shop-initiated cancellation — a charter cancellation or a guide-suspension
    cascade — always refunds the full amount_paid_cents."

    Design: Difficulty/transitive_cascade/guide_suspend_depth2_cancel_charter_then_refund_booking
    """
    ids = _suspend_guide_setup(api)
    booking = get_success_data(api.get_booking(ids["booking"]["id"], MANAGER))
    assert booking["booking_status"] == "CANCELLED"
    assert booking["payment_status"] == "REFUNDED"
    assert booking["refund_amount_cents"] == 26000  # full amount_paid (2*12000 + 2*1000)
