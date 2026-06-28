"""Multi-resource cascades (session complete/cancel), waitlist promotion, optimistic
concurrency (stale session/pack version, version increment), and multi-studio coverage.

Translates queue-A `transitive_cascade` and queue-B `state_machines` /
`cross_cutting_complexity_layers` instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    make_instructor_headers,
    fixtures,
)

MGR = TEST_USERS["studio_manager_headers"]


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / session_complete_noshow_penalty_suspend_depth3
# ---------------------------------------------------------------------------
def test_session_complete_noshow_penalty_suspend_depth3(api):
    """PRD 3.4: "When a session is **completed**, every reservation still in `BOOKED`
    is swept to `NO_SHOW` attendance with `FEE_CHARGED` billing (the held credit is not
    returned). For each such new no-show the system creates a penalty charge of kind
    `NO_SHOW` with `amount_cents` snapshotted from the studio's `no_show_fee_cents` and
    `counts_as_strike` true; creating that charge recomputes the member's
    `active_strike_count`, and if it reaches the suspend threshold the member is moved to
    `SUSPENDED`."

    Design: Difficulty/transitive_cascade/session_complete_noshow_penalty_suspend_depth3
    """
    # Member already has 2 strikes; one BOOKED reservation remains on a session past end.
    ctx = fixtures.setup_member_with_late_cancels(num_strikes=2, final_strike=True)
    studio_id = ctx["studio"]["id"]
    member_id = ctx["member"]["id"]
    assert fixtures.get_member(member_id)["active_strike_count"] == 2

    # Book a third session and let it complete with the reservation still BOOKED.
    fixtures.set_clock("2026-06-07T08:00:00Z")
    s3 = fixtures.create_session(
        studio_id, ctx["room"]["id"], ctx["instructor"]["id"],
        start_utc="2026-06-07T18:00:00Z", end_utc="2026-06-07T19:00:00Z",
    )
    r3 = fixtures.book(studio_id, s3["id"], member_id, ctx["bikes"][0]["id"], s3["version"])
    fixtures.set_clock("2026-06-07T19:30:00Z")  # past end_utc
    completed = validate_success(api.complete_session(studio_id, s3["id"], MGR))
    assert completed["status"] == "COMPLETED"

    reservation = validate_success(api.get_reservation(r3["id"], make_member_headers(member_id)))
    assert reservation["attendance_status"] == "NO_SHOW"
    assert reservation["billing_status"] == "FEE_CHARGED"
    member = fixtures.get_member(member_id)
    assert member["active_strike_count"] == 3
    assert member["account_status"] == "SUSPENDED"


def test_session_complete_creates_no_show_penalty(api):
    """PRD 3.4: "For each such new no-show the system creates a penalty charge of kind
    `NO_SHOW` with `amount_cents` snapshotted from the studio's `no_show_fee_cents` and
    `counts_as_strike` true".

    Design: Difficulty/transitive_cascade/session_complete_noshow_penalty_suspend_depth3
    """
    ctx = fixtures.setup_booked_reservation(
        n_bikes=1, start_utc="2026-06-05T18:00:00Z", end_utc="2026-06-05T19:00:00Z",
    )
    studio_id = ctx["studio"]["id"]
    member_id = ctx["member"]["id"]
    fixtures.set_clock("2026-06-05T19:30:00Z")
    validate_success(api.complete_session(studio_id, ctx["session"]["id"], MGR))
    charges = validate_success(
        api.list_penalty_charges(make_member_headers(member_id), params={"member_id": member_id})
    )
    no_shows = [c for c in charges if c["kind"] == "NO_SHOW"]
    assert len(no_shows) == 1
    assert no_shows[0]["amount_cents"] == 3000  # default no_show_fee_cents
    assert no_shows[0]["counts_as_strike"] is True


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / session_cancel_refund_restore_pack_depth2
# ---------------------------------------------------------------------------
def test_session_cancel_refund_restore_pack_depth2(api):
    """PRD 3.2: "every reservation still in `BOOKED` moves to `EARLY_CANCELLED`
    attendance with `CREDIT_REFUNDED` billing. Second, as a consequence of each such
    refund, any class-pack that had been charged has its `consumed_credits` decremented
    by one, and a pack that was sitting in `EXHAUSTED` returns to `ACTIVE`."

    Design: Difficulty/transitive_cascade/session_cancel_refund_restore_pack_depth2
    """
    # 1-credit pack EXHAUSTED by a real booking debit (first-ride comp already burned);
    # the studio cancels the session, restoring the credit (EXHAUSTED -> ACTIVE).
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    bike_id = estate["bikes"][0]["id"]
    instr_id = estate["instructor"]["id"]
    member, pack = fixtures.setup_member_past_first_ride(
        studio_id, estate["room"]["id"], instr_id, bike_id, purchased_credits=1, price_cents=2000
    )
    s2 = fixtures.create_session(
        studio_id, estate["room"]["id"], instr_id,
        start_utc="2026-06-10T18:00:00Z", end_utc="2026-06-10T19:00:00Z",
    )
    res = fixtures.book(studio_id, s2["id"], member["id"], bike_id, s2["version"])
    mid = fixtures.get_pack(pack["id"], member["id"])
    assert mid["status"] == "EXHAUSTED"
    cancelled = validate_success(api.cancel_session(studio_id, s2["id"], MGR))
    assert cancelled["status"] == "CANCELLED"
    reservation = validate_success(
        api.get_reservation(res["id"], make_member_headers(member["id"]))
    )
    assert reservation["attendance_status"] == "EARLY_CANCELLED"
    assert reservation["billing_status"] == "CREDIT_REFUNDED"
    final = fixtures.get_pack(pack["id"], member["id"])
    assert final["status"] == "ACTIVE"
    assert final["remaining_credits"] == 1


def test_session_cancel_refunds_booking_no_penalty(api):
    """PRD 3.2: "No penalty charge is ever created by a studio cancel; the studio never
    penalizes a member for its own cancellation."
    PRD 3.2: "every reservation still in `BOOKED` moves to `EARLY_CANCELLED` attendance
    with `CREDIT_REFUNDED` billing."

    Design: Difficulty/transitive_cascade/session_cancel_refund_restore_pack_depth2
    """
    # A second booking (real credit debit) on a future session, then studio cancel.
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    member, pack = fixtures.setup_member_with_pack(studio_id, purchased_credits=5)
    # First ride comp + check-in so the next booking debits a real credit.
    s1 = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"],
        start_utc="2026-06-02T10:00:00Z", end_utc="2026-06-02T11:00:00Z",
    )
    r1 = fixtures.book(studio_id, s1["id"], member["id"], estate["bikes"][0]["id"], s1["version"])
    fixtures.set_clock("2026-06-02T10:30:00Z")
    fixtures.check_in(studio_id, s1["id"], r1["id"], estate["instructor"]["id"])
    s2 = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"],
        start_utc="2026-06-20T18:00:00Z", end_utc="2026-06-20T19:00:00Z",
    )
    r2 = fixtures.book(studio_id, s2["id"], member["id"], estate["bikes"][0]["id"], s2["version"])
    assert fixtures.get_pack(pack["id"], member["id"])["remaining_credits"] == 4
    validate_success(api.cancel_session(studio_id, s2["id"], MGR))
    reservation = validate_success(api.get_reservation(r2["id"], make_member_headers(member["id"])))
    assert reservation["attendance_status"] == "EARLY_CANCELLED"
    assert reservation["billing_status"] == "CREDIT_REFUNDED"
    # Credit restored.
    assert fixtures.get_pack(pack["id"], member["id"])["remaining_credits"] == 5
    # No penalty charge created.
    charges = validate_success(
        api.list_penalty_charges(make_member_headers(member["id"]), params={"member_id": member["id"]})
    )
    assert charges == [], "studio cancel must not penalize the member"


# ---------------------------------------------------------------------------
# Queue B: state_machines / waitlist_promotion_on_early_cancel_bubble
# ---------------------------------------------------------------------------
def test_waitlist_promotion_on_early_cancel(api):
    """PRD 3.6: "When an early or late cancellation frees a seat, the system attempts to
    **promote** off the waitlist ... On promotion the system creates a fresh reservation
    for that member in `BOOKED` attendance and `CREDIT_HELD` billing on an auto-assigned
    free `ACTIVE` bike ... It debits one credit from the entry's pre-authorized pack ...
    sets the entry's `promoted_reservation_id` to the new reservation, and moves the
    entry's status to `PROMOTED`."

    Design: Corner/state_machines/waitlist_promotion_on_early_cancel_bubble
    """
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    bike_id = estate["bikes"][0]["id"]
    instr_id = estate["instructor"]["id"]
    member_a, _ = fixtures.setup_member_with_pack(studio_id, email="ma@x.com", full_name="Mem A")
    # The waiter is past their first ride so the promotion debits a real pack credit.
    waiter, waiter_pack = fixtures.setup_member_past_first_ride(
        studio_id, estate["room"]["id"], instr_id, bike_id, purchased_credits=5, price_cents=5000,
        first_ride_start="2026-06-02T10:00:00Z", first_ride_end="2026-06-02T11:00:00Z",
        first_ride_checkin="2026-06-02T10:30:00Z",
    )
    fixtures.set_clock("2026-06-03T00:00:00Z")
    # A future 1-bike session, fully booked by member A; the waiter queues.
    session = fixtures.create_session(
        studio_id, estate["room"]["id"], instr_id,
        start_utc="2026-06-20T18:00:00Z", end_utc="2026-06-20T19:00:00Z",
    )
    fixtures.book(studio_id, session["id"], member_a["id"], bike_id, session["version"])
    entry0 = fixtures.join_waitlist(studio_id, session["id"], waiter["id"], waiter_pack["id"])
    # Member A early-cancels -> the waiter is promoted.
    res_a = validate_success(
        api.list_reservations(
            make_member_headers(member_a["id"]),
            params={"session_id": session["id"], "member_id": member_a["id"]},
        )
    )[0]
    cancelled = fixtures.cancel_reservation(studio_id, session["id"], res_a["id"], member_a["id"])
    assert cancelled["attendance_status"] == "EARLY_CANCELLED"
    entry = validate_success(
        api.get_waitlist_entry(entry0["id"], make_member_headers(waiter["id"]))
    )
    assert entry["status"] == "PROMOTED"
    after = fixtures.get_session(session["id"], waiter["id"])
    assert after["booked_count"] == 1
    pack = fixtures.get_pack(waiter_pack["id"], waiter["id"])
    assert pack["remaining_credits"] == 4  # one credit debited from the 5-credit pack


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_complexity_layers / occ_stale_session_version_on_booking
# ---------------------------------------------------------------------------
def test_occ_stale_session_version_on_booking(api):
    """PRD 2.10: "If a prior booking, a cancellation, or an automatic waitlist
    promotion has advanced the session's `version` since the client read it, the
    client's picture of which seats remain free is stale, so the booking is rejected
    with `ERR_STALE_SESSION_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_session_version_on_booking
    """
    estate = fixtures.setup_studio_estate(n_bikes=2)
    studio_id = estate["studio"]["id"]
    member_a, _ = fixtures.setup_member_with_pack(studio_id, email="ma@x.com", full_name="Mem A")
    member_b, _ = fixtures.setup_member_with_pack(studio_id, email="mb@x.com", full_name="Mem B")
    session = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"]
    )
    stale_version = session["version"]
    # Member A books, advancing session.version.
    fixtures.book(studio_id, session["id"], member_a["id"], estate["bikes"][0]["id"], stale_version)
    # Member B books with the pre-first (stale) version.
    resp = api.create_reservation(
        studio_id, session["id"],
        {
            "member_id": member_b["id"],
            "bike_id": estate["bikes"][1]["id"],
            "expected_session_version": stale_version,
        },
        make_member_headers(member_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_SESSION_VERSION.value, expected_status=412)


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_complexity_layers / occ_stale_pack_version_on_refund
# ---------------------------------------------------------------------------
def test_occ_stale_pack_version_on_refund(api):
    """PRD 2.10: "Because a credit debit, a credit restore, or an expiry transition
    changes the pack's remaining-credit count and therefore its prorated refund base, a
    refund issued against a stale pack view is rejected with `ERR_STALE_PACK_VERSION`".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_pack_version_on_refund
    """
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    bike_id = estate["bikes"][0]["id"]
    instr_id = estate["instructor"]["id"]
    # Burn the first-ride comp (no pack change). Then capture the pack version the client
    # last observed, and let a real-credit booking (later checked in, so no BOOKED hold
    # remains charged to the pack) bump the pack's version past that captured value.
    member, pack = fixtures.setup_member_past_first_ride(
        studio_id, estate["room"]["id"], instr_id, bike_id, purchased_credits=5, price_cents=5000
    )
    stale_pack_version = fixtures.get_pack(pack["id"], member["id"])["version"]
    s2 = fixtures.create_session(
        studio_id, estate["room"]["id"], instr_id,
        start_utc="2026-06-15T10:00:00Z", end_utc="2026-06-15T11:00:00Z",
    )
    r2 = fixtures.book(studio_id, s2["id"], member["id"], bike_id, s2["version"])  # debits credit
    fixtures.set_clock("2026-06-15T10:30:00Z")
    fixtures.check_in(studio_id, s2["id"], r2["id"], instr_id)  # ATTENDED -> no BOOKED hold
    assert fixtures.get_pack(pack["id"], member["id"])["version"] > stale_pack_version
    # Refund with the stale (pre-debit) pack version -> rejected on the version mismatch.
    resp = api.refund_credit_pack(pack["id"], {"expected_pack_version": stale_pack_version}, MGR)
    validate_error(resp, ApiErrorId.ERR_STALE_PACK_VERSION.value, expected_status=412)


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_complexity_layers / occ_version_increments_on_session_mutation
# ---------------------------------------------------------------------------
def test_booking_increments_session_version(api):
    """PRD 3.4: "on success the session's `version` is incremented and its
    `booked_count` recomputed."
    PRD 2.4: "The `version` field is an integer that begins at the resource's creation
    and increments by one on every mutation."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_session_mutation
    """
    estate = fixtures.setup_studio_estate(n_bikes=2)
    studio_id = estate["studio"]["id"]
    member, _ = fixtures.setup_member_with_pack(studio_id)
    session = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"]
    )
    assert session["version"] == 1
    fixtures.book(studio_id, session["id"], member["id"], estate["bikes"][0]["id"], session["version"])
    live = fixtures.get_session(session["id"], member["id"])
    assert live["version"] == 2
    assert live["booked_count"] == 1


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_complexity_layers / multi_studio_pack_covers_away_session
# ---------------------------------------------------------------------------
def test_multi_studio_pack_covers_away_session(api):
    """PRD 3.4: "a `MULTI_STUDIO` pack covers the booking only when the session's
    `studio_id` appears in the pack's `grant_studio_ids` (the home studio is ignored) ...
    The chosen pack's id is recorded as the reservation's `credit_pack_id`; if it is a
    `CLASS_PACK` its `consumed_credits` is incremented by one".

    Design: Corner/cross_cutting_complexity_layers/multi_studio_pack_covers_away_session
    """
    two = fixtures.setup_two_studios()
    studio_a, studio_b = two["studio_a"], two["studio_b"]
    instr_id = two["instructor"]["id"]
    member = fixtures.register_member(studio_a["id"])
    pack = fixtures.create_credit_pack(
        member["id"], purchased_credits=5, price_cents=5000,
        scope="MULTI_STUDIO", grant_studio_ids=[studio_a["id"], studio_b["id"]],
    )
    # First ride at A uses the comp; check in to consume it.
    sa = fixtures.create_session(
        studio_a["id"], two["room_a"]["id"], instr_id,
        start_utc="2026-06-10T18:00:00Z", end_utc="2026-06-10T19:00:00Z",
    )
    ra = fixtures.book(studio_a["id"], sa["id"], member["id"], two["bike_a"]["id"], sa["version"])
    fixtures.set_clock("2026-06-10T18:30:00Z")
    fixtures.check_in(studio_a["id"], sa["id"], ra["id"], instr_id)
    # Book at B -> debits one real credit from the MULTI_STUDIO pack.
    sb = fixtures.create_session(
        studio_b["id"], two["room_b"]["id"], instr_id,
        start_utc="2026-06-12T18:00:00Z", end_utc="2026-06-12T19:00:00Z",
    )
    res = validate_success(
        api.create_reservation(
            studio_b["id"], sb["id"],
            {
                "member_id": member["id"],
                "bike_id": two["bike_b"]["id"],
                "expected_session_version": sb["version"],
            },
            make_member_headers(member["id"]),
        ),
        expected_status=201,
    )
    assert res["attendance_status"] == "BOOKED"
    assert res["first_ride_discount_applied"] is False
    assert res["credit_pack_id"] == pack["id"]
    assert fixtures.get_pack(pack["id"], member["id"])["remaining_credits"] == 4
