"""Fees, surcharges, refund valuation, and the no-show suspension cascade.

Translates difficulty instances `fee_assessment_late_vs_no_show_on_member`,
`entitlement_refund_provisional_vs_final_cash`, `late_cancel_window_exact_boundary_is_late`,
`no_show_cascade_fee_strike_suspend_depth3`, and corner instances from sections
`calculations`, `entities`, and `endpoints`.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_member_headers,
    set_clock, create_room, create_teacher, create_member,
    create_active_entitlement, create_published_session,
    book_reservation, run_session_no_show,
    make_member_established, drive_member_no_show_strikes,
    first_fee_charge, get_member_fee_charges,
    assert_no_version_field,
)

MGR = TEST_USERS["studio_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: fee_assessment_late_vs_no_show_on_member
# Established member with no_show_strike_count == 2 -> tier-1 surcharge (+25%).
# ---------------------------------------------------------------------------
def _setup_established_member_two_strikes():
    """Member established (attended once -> is_new_student=false) and driven to
    no_show_strike_count == 2 via two completed no-shows. Returns (member, entitlement, room,
    teacher). Clock left at 2026-02-01T00:00:00Z."""
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Reformer A", room_type="REFORMER", station_capacity=4)
    teacher = create_teacher(full_name="Tara", certifications=["REFORMER"])
    member = create_member(email="m@x.com", full_name="Mae")
    ent = create_active_entitlement(member["id"], kind="MEMBERSHIP", price_cents=12000, credits_total=-1)
    make_member_established(member["id"], room["id"], teacher["id"], ent["id"],
                           discipline="REFORMER",
                           start_utc="2026-02-01T05:00:00Z", end_utc="2026-02-01T05:30:00Z")
    drive_member_no_show_strikes(member["id"], room["id"], teacher["id"], ent["id"], 2,
                                 discipline="REFORMER")
    return member, ent, room, teacher


def test_late_cancel_fee_with_two_prior_strikes_is_1875(api):
    """PRD §3.7: "The base is 2500 cents for a no-show and 1500 cents for a late cancel."
    PRD §3.7: "A repeat-offender surcharge is keyed on the member's `no_show_strike_count` read
    at the instant *before* this event would increment it: if that prior count is at least 4 the
    surcharge is 50 percent of the base; otherwise if it is at least 2 the surcharge is 25 percent
    of the base; otherwise there is no surcharge."
    PRD §3.7: "the strike tier always reads `no_show_strike_count`, even for a late cancel, even
    though a late cancel does not itself increment that count"

    Design: Difficulty/dual_variant_calc/fee_assessment_late_vs_no_show_on_member
    """
    member, ent, room, teacher = _setup_established_member_two_strikes()
    session = create_published_session(room["id"], teacher["id"], discipline="REFORMER",
                                       start_utc="2026-02-02T10:00:00Z",
                                       end_utc="2026-02-02T11:00:00Z", published_capacity=4)
    res = book_reservation(member["id"], session["id"], ent["id"])
    # Move into the late window (within 12h of start) and cancel.
    set_clock("2026-02-02T00:00:00Z")
    cancelled = validate_success(api.cancel_reservation(res["id"], make_member_headers(member["id"])), 200)
    assert cancelled["status"] == "CANCELLED_LATE"
    charges = [c for c in get_member_fee_charges(member["id"]) if c["reservation_id"] == res["id"]]
    assert len(charges) == 1
    assert charges[0]["fee_type"] == "LATE_CANCEL"
    assert charges[0]["amount_cents"] == 1875, "base 1500 + 25% tier-1 surcharge = 1875"


def test_no_show_fee_with_two_prior_strikes_is_3125(api):
    """PRD §3.7: "The base is 2500 cents for a no-show and 1500 cents for a late cancel."
    PRD §3.7: "A repeat-offender surcharge is keyed on the member's `no_show_strike_count` read
    at the instant *before* this event would increment it: if that prior count is at least 4 the
    surcharge is 50 percent of the base; otherwise if it is at least 2 the surcharge is 25 percent
    of the base; otherwise there is no surcharge."

    Design: Difficulty/dual_variant_calc/fee_assessment_late_vs_no_show_on_member
    """
    member, ent, room, teacher = _setup_established_member_two_strikes()
    session = create_published_session(room["id"], teacher["id"], discipline="REFORMER",
                                       start_utc="2026-02-03T10:00:00Z",
                                       end_utc="2026-02-03T11:00:00Z", published_capacity=4)
    res = book_reservation(member["id"], session["id"], ent["id"])
    set_clock("2026-02-03T10:00:00Z")
    api.start_class_session(session["id"], MGR)
    api.complete_class_session(session["id"], MGR)  # still BOOKED -> NO_SHOW
    assert validate_success(api.get_reservation(res["id"], MGR), 200)["status"] == "NO_SHOW"
    charges = [c for c in get_member_fee_charges(member["id"]) if c["reservation_id"] == res["id"]]
    assert len(charges) == 1
    assert charges[0]["fee_type"] == "NO_SHOW"
    assert charges[0]["amount_cents"] == 3125, "base 2500 + 25% tier-1 surcharge = 3125"


# ---------------------------------------------------------------------------
# Difficulty: entitlement_refund_provisional_vs_final_cash
# ---------------------------------------------------------------------------
def _setup_pack_member_two_sessions():
    """Member with an ACTIVE 10-credit pack (price 12000), booked R1 on S1 and R2 on S2.
    Returns (member, ent, s1, s2, r1, r2)."""
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Reformer A", room_type="REFORMER", station_capacity=4)
    teacher = create_teacher(full_name="Tara", certifications=["REFORMER"])
    member = create_member(email="m2@x.com", full_name="Mo")
    ent = create_active_entitlement(member["id"], kind="CLASS_PACK", price_cents=12000, credits_total=10)
    s1 = create_published_session(room["id"], teacher["id"], discipline="REFORMER",
                                  start_utc="2026-02-10T10:00:00Z",
                                  end_utc="2026-02-10T11:00:00Z", published_capacity=4)
    r1 = book_reservation(member["id"], s1["id"], ent["id"])
    s2 = create_published_session(room["id"], teacher["id"], discipline="REFORMER",
                                  start_utc="2026-02-11T10:00:00Z",
                                  end_utc="2026-02-11T11:00:00Z", published_capacity=4)
    r2 = book_reservation(member["id"], s2["id"], ent["id"])
    return member, ent, s1, s2, r1, r2


def test_member_early_cancel_refunds_exactly_one_credit(api):
    """PRD §3.7: "When a member early-cancels their own reservation (a `BOOKED` or `WAITLISTED`
    reservation moving to `CANCELLED_EARLY`), the refund is provisional: exactly one whole credit
    is returned to the entitlement (its `credits_used` drops by one) and no cash moves."

    Design: Difficulty/dual_variant_calc/entitlement_refund_provisional_vs_final_cash
    """
    member, ent, s1, s2, r1, r2 = _setup_pack_member_two_sessions()
    # credits_used == 2 after two bookings; cancel R1 well before S1 (clock still 2026-02-01).
    cancelled = validate_success(api.cancel_reservation(r1["id"], make_member_headers(member["id"])), 200)
    assert cancelled["status"] == "CANCELLED_EARLY"
    data = validate_success(api.get_entitlement(ent["id"], MGR), 200)
    assert data["credits_used"] == 1, "exactly one credit returned"


def test_studio_cancel_returns_credit_to_entitlement(api):
    """PRD §3.6: "When a manager cancels a `SCHEDULED`, `OPEN`, or `FULL` session, every
    reservation that is `BOOKED`, `WAITLISTED`, or `CHECKED_IN` moves to `CANCELLED_EARLY`, no
    late-cancel or no-show fee is assessed, and every such reservation that had `credit_charged`
    true has its credit returned to the owning entitlement (the entitlement's `credits_used`
    decreases by one)."

    Design: Difficulty/dual_variant_calc/entitlement_refund_provisional_vs_final_cash
    """
    member, ent, s1, s2, r1, r2 = _setup_pack_member_two_sessions()
    api.cancel_class_session(s2["id"], MGR)
    assert validate_success(api.get_reservation(r2["id"], MGR), 200)["status"] == "CANCELLED_EARLY"
    data = validate_success(api.get_entitlement(ent["id"], MGR), 200)
    assert data["credits_used"] == 1, "R2's credit returned by the studio-cancel cascade"


# ---------------------------------------------------------------------------
# Difficulty: late_cancel_window_exact_boundary_is_late
# ---------------------------------------------------------------------------
def _setup_established_member_zero_strikes_with_booking(start_utc):
    """Established member (is_new_student=false, 0 strikes) with a MEMBERSHIP, BOOKED on a
    session starting at `start_utc`. Returns (member, ent, reservation)."""
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    member = create_member(email="bd@x.com", full_name="Bo")
    ent = create_active_entitlement(member["id"], kind="MEMBERSHIP", price_cents=10000, credits_total=-1)
    make_member_established(member["id"], room["id"], teacher["id"], ent["id"],
                           discipline="VINYASA",
                           start_utc="2026-02-01T06:00:00Z", end_utc="2026-02-01T07:00:00Z")
    session = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                       start_utc=start_utc,
                                       end_utc="2026-02-10T13:00:00Z", published_capacity=10)
    res = book_reservation(member["id"], session["id"], ent["id"])
    return member, ent, res


def test_cancel_at_exact_12h_boundary_is_late(api):
    """PRD §3.6: "The cutoff is the session's `start_utc` minus 12 hours. If the logical clock is
    strictly before that cutoff the cancel is EARLY; if the clock is at or after the cutoff it is
    LATE — the boundary instant itself counts as LATE, so a cancel exactly 12 hours before start is
    a late cancel and is charged a fee."

    Design: Difficulty/boundary_precision_check/late_cancel_window_exact_boundary_is_late
    """
    member, ent, res = _setup_established_member_zero_strikes_with_booking("2026-02-10T12:00:00Z")
    # Cutoff = 2026-02-10T00:00:00Z exactly; clock == cutoff -> LATE.
    set_clock("2026-02-10T00:00:00Z")
    cancelled = validate_success(api.cancel_reservation(res["id"], make_member_headers(member["id"])), 200)
    assert cancelled["status"] == "CANCELLED_LATE"


def test_cancel_at_exact_boundary_charges_base_late_fee(api):
    """PRD §3.7: "The base is 2500 cents for a no-show and 1500 cents for a late cancel."
    PRD §3.7: "A repeat-offender surcharge is keyed on the member's `no_show_strike_count` read
    at the instant *before* this event would increment it: if that prior count is at least 4 the
    surcharge is 50 percent of the base; otherwise if it is at least 2 the surcharge is 25 percent
    of the base; otherwise there is no surcharge."

    Design: Difficulty/boundary_precision_check/late_cancel_window_exact_boundary_is_late
    """
    member, ent, res = _setup_established_member_zero_strikes_with_booking("2026-02-10T12:00:00Z")
    set_clock("2026-02-10T00:00:00Z")
    api.cancel_reservation(res["id"], make_member_headers(member["id"]))
    charges = [c for c in get_member_fee_charges(member["id"]) if c["reservation_id"] == res["id"]]
    assert len(charges) == 1
    assert charges[0]["amount_cents"] == 1500, "0 prior strikes -> base only"


# ---------------------------------------------------------------------------
# Difficulty: no_show_cascade_fee_strike_suspend_depth3
# ---------------------------------------------------------------------------
def _setup_member_at_strike_two_with_booking():
    """Established member at no_show_strike_count == 2 with a BOOKED reservation on a fresh
    session S. Returns (member, ent, session, reservation)."""
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(name="Mat A", room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    member = create_member(email="sus@x.com", full_name="Sue")
    ent = create_active_entitlement(member["id"], kind="MEMBERSHIP", price_cents=10000, credits_total=-1)
    make_member_established(member["id"], room["id"], teacher["id"], ent["id"],
                           discipline="VINYASA",
                           start_utc="2026-02-01T05:00:00Z", end_utc="2026-02-01T05:30:00Z")
    drive_member_no_show_strikes(member["id"], room["id"], teacher["id"], ent["id"], 2,
                                 discipline="VINYASA")
    session = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                       start_utc="2026-02-05T10:00:00Z",
                                       end_utc="2026-02-05T11:00:00Z", published_capacity=10)
    res = book_reservation(member["id"], session["id"], ent["id"])
    return member, ent, session, res


def test_no_show_increments_strike_and_raises_fee(api):
    """PRD §3.6: "Each reservation still `BOOKED` becomes `NO_SHOW`: a `FeeCharge` of type
    `NO_SHOW` is raised and the member's `outstanding_fee_cents` rises by its amount, the member's
    `no_show_strike_count` increases by one (and if that count reaches at least 3 the member's
    `account_status` becomes `SUSPENDED`), and the held credit is forfeited rather than refunded."

    Design: Difficulty/transitive_cascade/no_show_cascade_fee_strike_suspend_depth3
    """
    member, ent, session, res = _setup_member_at_strike_two_with_booking()
    set_clock("2026-02-05T10:00:00Z")
    api.start_class_session(session["id"], MGR)
    api.complete_class_session(session["id"], MGR)
    assert validate_success(api.get_reservation(res["id"], MGR), 200)["status"] == "NO_SHOW"
    member_data = validate_success(api.get_member(member["id"], MGR), 200)
    assert member_data["no_show_strike_count"] == 3
    charges = [c for c in get_member_fee_charges(member["id"]) if c["reservation_id"] == res["id"]]
    assert len(charges) == 1 and charges[0]["fee_type"] == "NO_SHOW"


def test_third_strike_suspends_member_account(api):
    """PRD §3.6: "the member's `no_show_strike_count` increases by one (and if that count reaches
    at least 3 the member's `account_status` becomes `SUSPENDED`)"

    Design: Difficulty/transitive_cascade/no_show_cascade_fee_strike_suspend_depth3
    """
    member, ent, session, res = _setup_member_at_strike_two_with_booking()
    set_clock("2026-02-05T10:00:00Z")
    api.start_class_session(session["id"], MGR)
    api.complete_class_session(session["id"], MGR)
    member_data = validate_success(api.get_member(member["id"], MGR), 200)
    assert member_data["account_status"] == "SUSPENDED", "3rd strike crosses the threshold"


# ---------------------------------------------------------------------------
# Corner: new-student grace, fee-charge immutability, settle
# ---------------------------------------------------------------------------
def test_fee_zero_for_new_student_grace(api):
    """PRD §3.7: "a member still flagged `is_new_student` pays nothing — the assessed
    `amount_cents` is 0 regardless of base or surcharge."

    Design: Corner/calculations/fee_zero_for_new_student_grace
    """
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    member = create_member(email="ng@x.com", full_name="Ng")  # is_new_student=true
    ent = create_active_entitlement(member["id"], price_cents=10000, credits_total=-1)
    session = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                       start_utc="2026-02-02T12:00:00Z",
                                       end_utc="2026-02-02T13:00:00Z", published_capacity=10)
    res = book_reservation(member["id"], session["id"], ent["id"])
    set_clock("2026-02-02T06:00:00Z")  # within the late window
    cancelled = validate_success(api.cancel_reservation(res["id"], make_member_headers(member["id"])), 200)
    assert cancelled["status"] == "CANCELLED_LATE"
    charges = [c for c in get_member_fee_charges(member["id"]) if c["reservation_id"] == res["id"]]
    assert len(charges) == 1
    assert charges[0]["amount_cents"] == 0, "new-student grace -> 0"
    member_data = validate_success(api.get_member(member["id"], MGR), 200)
    assert member_data["outstanding_fee_cents"] == 0


def _setup_member_with_unpaid_no_show_fee():
    """Established member with one UNPAID NO_SHOW FeeCharge (amount 2500, 0 prior strikes).
    Returns (member, fee_charge)."""
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    member = create_member(email="se@x.com", full_name="Se")
    ent = create_active_entitlement(member["id"], price_cents=10000, credits_total=-1)
    make_member_established(member["id"], room["id"], teacher["id"], ent["id"],
                           discipline="VINYASA",
                           start_utc="2026-02-01T06:00:00Z", end_utc="2026-02-01T07:00:00Z")
    ns = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                  start_utc="2026-02-02T06:00:00Z",
                                  end_utc="2026-02-02T07:00:00Z", published_capacity=10)
    run_session_no_show(member["id"], ns["id"], ent["id"], start_clock="2026-02-02T06:00:00Z")
    fc = first_fee_charge(member["id"])
    return member, fc


def test_fee_charge_immutable_no_version_field(api):
    """PRD §2.4: "A `FeeCharge` has no `updated_at` and no `version` field; its lifecycle
    (settling or waiving) is expressed through its `status` rather than a version counter."

    Design: Corner/entities/fee_charge_immutable_no_version_field
    """
    member, fc = _setup_member_with_unpaid_no_show_fee()
    assert_no_version_field(fc)
    assert "id" in fc and "created_at" in fc
    assert fc["fee_type"] == "NO_SHOW"
    assert fc["status"] == "UNPAID"


def test_fee_charge_settle_resolves_and_reduces_outstanding(api):
    """PRD §3.7: "A `StudioManager` settles a fee by supplying a `resolution`, moving the charge
    from `UNPAID` to `PAID` or `WAIVED` and reducing the member's `outstanding_fee_cents` by the
    charge amount"

    Design: Corner/endpoints/fee_charge_settle_resolves_and_reduces_outstanding
    """
    member, fc = _setup_member_with_unpaid_no_show_fee()
    resp = api.settle_fee_charge(fc["id"], {"resolution": "PAID"}, MGR)
    data = validate_success(resp, 200)
    assert data["status"] == "PAID"
    member_data = validate_success(api.get_member(member["id"], MGR), 200)
    assert member_data["outstanding_fee_cents"] == 0


def test_settle_already_resolved_fee_returns_error(api):
    """PRD §3.7: "settling a charge that is already `PAID` or `WAIVED` is rejected with
    `ERR_FEE_ALREADY_RESOLVED` (HTTP 409)."

    Design: Corner/endpoints/settle_already_resolved_fee_returns_error
    """
    member, fc = _setup_member_with_unpaid_no_show_fee()
    api.settle_fee_charge(fc["id"], {"resolution": "PAID"}, MGR)
    resp = api.settle_fee_charge(fc["id"], {"resolution": "WAIVED"}, MGR)
    validate_error(resp, ApiErrorId.ERR_FEE_ALREADY_RESOLVED.value, 409)
