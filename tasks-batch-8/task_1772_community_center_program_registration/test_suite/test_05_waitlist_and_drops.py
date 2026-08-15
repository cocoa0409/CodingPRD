"""Parallel registration state axes, the drop -> refund -> promotion chain,
seat conservation, and waitlist ordering fairness."""
from test_helpers import (
    ApiErrorId,
    assert_instant_eq,
    drop_registration,
    get_household_credit,
    get_registration,
    get_session,
    pay_registration,
    register_and_pay,
    register_participant,
    setup_household_with_participants,
    setup_published_session,
    validate_success,
)


def test_payment_moves_only_the_payment_axis(api):
    """PRD §3.6: "Payment expectations attach immediately, on a second state
    axis stored as the registration's `payment_status` — parallel to and
    independent of `enrollment_status`, evolving on its own save for the
    pinned interaction points at creation, promotion, and terminal
    resolution."
    PRD §3.7: "A successful payment creates a `CHARGE` transaction born
    `COMPLETED`, moves the payment axis to `PAID`, adds the amount to the
    registration's `net_paid_cents`, and clears `payment_due_at` to null."

    Design: Difficulty/non_linear_state_machine/registration_parallel_state_axes
    """
    ctx = setup_published_session(capacity=1, fee_resident_cents=5000,
                                  fee_nonresident_cents=5000)
    household, parts = setup_household_with_participants(count=1, account_name="HA")
    registration = register_participant(ctx["session"]["id"], parts[0]["id"],
                                        household["id"])
    assert registration["enrollment_status"] == "ENROLLED"
    assert registration["payment_status"] == "PENDING"
    assert_instant_eq(registration["payment_due_at"], "2026-08-20T00:00:00Z")

    pay_registration(registration["id"], household["id"], amount_cents=5000)
    after = get_registration(registration["id"])
    assert after["enrollment_status"] == "ENROLLED"   # enrollment axis untouched
    assert after["payment_status"] == "PAID"
    assert after["net_paid_cents"] == 5000
    assert after["payment_due_at"] is None


def test_promotion_moves_only_the_enrollment_axis(api):
    """PRD §3.6: "Payment expectations attach immediately, on a second state
    axis stored as the registration's `payment_status` — parallel to and
    independent of `enrollment_status`, evolving on its own save for the
    pinned interaction points at creation, promotion, and terminal
    resolution."
    PRD §3.8: "Otherwise the first-ranked registration is promoted to
    `ENROLLED` with `promoted_at` set to now: when its pinned fee is greater
    than zero its `payment_due_at` becomes forty-eight hours — two days —
    after `promoted_at` and its payment axis stays `PENDING`; when the pinned
    fee is zero its payment axis moves from `PENDING` to `WAIVED` with no
    deadline."

    Design: Difficulty/non_linear_state_machine/registration_parallel_state_axes
    """
    ctx = setup_published_session(capacity=1, fee_resident_cents=5000,
                                  fee_nonresident_cents=5000)
    session_id = ctx["session"]["id"]
    household_a, parts_a = setup_household_with_participants(count=1, account_name="HA")
    household_b, parts_b = setup_household_with_participants(count=1, account_name="HB")
    ra = register_and_pay(session_id, parts_a[0]["id"], household_a["id"])
    rb = register_participant(session_id, parts_b[0]["id"], household_b["id"])
    assert rb["enrollment_status"] == "WAITLISTED"
    assert rb["payment_status"] == "PENDING"
    assert rb["payment_due_at"] is None

    drop_registration(ra["id"], household_a["id"])

    promoted = get_registration(rb["id"])
    assert promoted["enrollment_status"] == "ENROLLED"     # enrollment axis moved
    assert promoted["payment_status"] == "PENDING"         # payment axis stayed
    assert_instant_eq(promoted["promoted_at"], "2026-08-17T00:00:00Z")
    assert_instant_eq(promoted["payment_due_at"], "2026-08-19T00:00:00Z")

    dropped = get_registration(ra["id"])
    assert dropped["enrollment_status"] == "DROPPED"
    assert dropped["payment_status"] == "REFUNDED"   # 5000 < 10000 auto-approved


def _full_session_with_waitlist(fee: int, pay_first: bool = True) -> dict:
    """Capacity-1 published session: RA (household A) occupies the seat,
    RB (household B) waits."""
    ctx = setup_published_session(capacity=1, fee_resident_cents=fee,
                                  fee_nonresident_cents=fee)
    session_id = ctx["session"]["id"]
    household_a, parts_a = setup_household_with_participants(count=1, account_name="HA")
    household_b, parts_b = setup_household_with_participants(count=1, account_name="HB")
    if pay_first:
        ra = register_and_pay(session_id, parts_a[0]["id"], household_a["id"])
    else:
        ra = register_participant(session_id, parts_a[0]["id"], household_a["id"])
    rb = register_participant(session_id, parts_b[0]["id"], household_b["id"])
    return {"ctx": ctx, "ha": household_a, "hb": household_b, "ra": ra, "rb": rb}


def test_voluntary_drop_refund_hop(api):
    """PRD §3.8: "Dropping an `ENROLLED` registration fires the refund rule
    and then the promotion rule." and "If no meeting has been held, the refund
    is the full `net_paid_cents`."
    PRD §3.8: "Issuance then follows the ledger rules of §3.7: a refund
    greater than zero creates a `REFUND` transaction — `PENDING` at or above
    the one-hundred-dollar review threshold, moving the payment axis from
    `PAID` to `REFUND_PENDING`, otherwise `COMPLETED`, moving `PAID` to
    `REFUNDED` and crediting the household — while a zero refund creates
    nothing and leaves `PAID` untouched, and a never-paid `PENDING`
    registration simply voids to `VOID`."

    Design: Difficulty/transitive_cascade/voluntary_drop_promotion_chain
    """
    scenario = _full_session_with_waitlist(fee=8000)
    ra, household_a = scenario["ra"], scenario["ha"]

    drop_registration(ra["id"], household_a["id"])

    after = get_registration(ra["id"])
    assert after["enrollment_status"] == "DROPPED"
    assert after["drop_reason"] == "VOLUNTARY"
    assert after["refund_total_cents"] == 8000     # no meeting held -> 100%
    assert after["payment_status"] == "REFUNDED"   # 8000 < 10000 auto-approved
    assert get_household_credit(household_a["id"]) == 8000


def test_voluntary_drop_promotion_hop(api):
    """PRD §3.8: "Otherwise the first-ranked registration is promoted to
    `ENROLLED` with `promoted_at` set to now: when its pinned fee is greater
    than zero its `payment_due_at` becomes forty-eight hours — two days —
    after `promoted_at` and its payment axis stays `PENDING`; when the pinned
    fee is zero its payment axis moves from `PENDING` to `WAIVED` with no
    deadline. The session's `waitlist_count` decreases by one and its
    `enrolled_count` climbs back by one, so a voluntary drop nets out to a
    decrement followed by an increment, each bumping the session's `version`."

    Design: Difficulty/transitive_cascade/voluntary_drop_promotion_chain
    """
    scenario = _full_session_with_waitlist(fee=8000)
    session_id = scenario["ctx"]["session"]["id"]
    ra, rb = scenario["ra"], scenario["rb"]

    drop_registration(ra["id"], scenario["ha"]["id"])

    session = get_session(session_id)
    assert session["enrolled_count"] == 1    # decremented to 0, incremented back
    assert session["waitlist_count"] == 0
    promoted = get_registration(rb["id"])
    assert promoted["enrollment_status"] == "ENROLLED"
    assert_instant_eq(promoted["promoted_at"], "2026-08-17T00:00:00Z")
    assert_instant_eq(promoted["payment_due_at"], "2026-08-19T00:00:00Z")
    assert promoted["payment_status"] == "PENDING"


def test_drop_promotion_seat_conservation_counts(api):
    """PRD §3.8: "The session's `waitlist_count` decreases by one and its
    `enrolled_count` climbs back by one, so a voluntary drop nets out to a
    decrement followed by an increment, each bumping the session's `version`."

    Design: Difficulty/compensating_invariant/drop_promotion_seat_conservation
    """
    scenario = _full_session_with_waitlist(fee=2000)
    session_id = scenario["ctx"]["session"]["id"]

    before = get_session(session_id)
    assert before["enrolled_count"] == 1
    assert before["waitlist_count"] == 1     # RB waits while RA holds the seat

    drop_registration(scenario["ra"]["id"], scenario["ha"]["id"])

    after = get_session(session_id)
    # The freed seat is handed off, not destroyed: occupied seats conserved.
    assert after["enrolled_count"] == 1 == before["enrolled_count"]
    assert after["waitlist_count"] == 0


def test_drop_promotion_seat_conservation_states(api):
    """PRD §3.8: "Dropping an `ENROLLED` registration fires the refund rule
    and then the promotion rule." and "Otherwise the first-ranked registration
    is promoted to `ENROLLED` with `promoted_at` set to now: when its pinned
    fee is greater than zero its `payment_due_at` becomes forty-eight hours —
    two days — after `promoted_at` and its payment axis stays `PENDING`; when
    the pinned fee is zero its payment axis moves from `PENDING` to `WAIVED`
    with no deadline."

    Design: Difficulty/compensating_invariant/drop_promotion_seat_conservation
    """
    scenario = _full_session_with_waitlist(fee=2000)
    drop_registration(scenario["ra"]["id"], scenario["ha"]["id"])

    assert get_registration(scenario["ra"]["id"])["enrollment_status"] == "DROPPED"
    assert get_registration(scenario["rb"]["id"])["enrollment_status"] == "ENROLLED"


def test_waitlist_ordering_fairness(api):
    """PRD §3.8: "The waitlist promotion selector gathers the session's
    `WAITLISTED` registrations — only while the session is `PUBLISHED` or
    `ACTIVE` — ranks them by `waitlisted_at` ascending with `created_at`
    ascending as the tie-break, and never consults the registration `id` for
    ordering. If no candidate exists, the seat simply stays open. Otherwise
    the first-ranked registration is promoted to `ENROLLED` with `promoted_at`
    set to now: when its pinned fee is greater than zero its `payment_due_at`
    becomes forty-eight hours — two days — after `promoted_at` and its payment
    axis stays `PENDING`; when the pinned fee is zero its payment axis moves
    from `PENDING` to `WAIVED` with no deadline."

    Design: Corner/calculations/waitlist_ordering_fairness
    """
    ctx = setup_published_session(capacity=1, fee_resident_cents=2000,
                                  fee_nonresident_cents=2000)
    session_id = ctx["session"]["id"]
    household_a, parts_a = setup_household_with_participants(count=1, account_name="HA")
    household_b, parts_b = setup_household_with_participants(count=1, account_name="HB")
    household_c, parts_c = setup_household_with_participants(count=1, account_name="HC")
    ra = register_participant(session_id, parts_a[0]["id"], household_a["id"])
    rb = register_participant(session_id, parts_b[0]["id"], household_b["id"])
    rc = register_participant(session_id, parts_c[0]["id"], household_c["id"])
    assert rb["enrollment_status"] == "WAITLISTED"
    assert rc["enrollment_status"] == "WAITLISTED"

    # RA was never paid; its unpaid PENDING axis simply voids on drop.
    drop_registration(ra["id"], household_a["id"])

    # The earlier-waitlisted RB wins the freed seat; RC keeps waiting.
    assert get_registration(rb["id"])["enrollment_status"] == "ENROLLED"
    assert get_registration(rc["id"])["enrollment_status"] == "WAITLISTED"
    assert get_session(session_id)["waitlist_count"] == 1
