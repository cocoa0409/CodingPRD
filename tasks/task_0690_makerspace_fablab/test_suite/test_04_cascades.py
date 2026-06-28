"""Cascade workflows: suspension unwinding a member's reservations with wallet
refund, workshop completion resolving stragglers, and membership cancellation
releasing lockers.
"""
from test_helpers import (
    validate_success,
    setup_confirmed_reservation,
    setup_running_workshop_with_enrollment,
    create_active_member,
    assign_locker,
    make_member_headers,
    make_staff_headers,
)

MAKER_TIER = {
    "code": "MAKER", "name": "Maker", "billing_mode": "MONTHLY",
    "monthly_fee_cents": 0, "discount_bps": 1000, "prepaid_machine_minutes": 0,
    "locker_free_liters": 50, "unsupervised_allowed": True,
}
LASER_MACHINE = {
    "machine_class": "LASER", "hourly_rate_cents": 4800, "setup_fee_cents": 500,
    "min_billing_minutes": 30, "cooldown_minutes": 15, "requires_certification": True,
}


# ===========================================================================
# transitive_cascade / member_suspend_cancels_reservation_refunds_wallet_depth3
# ===========================================================================
def test_suspend_cascades_cancel_to_confirmed_reservation(api):
    """PRD §3.10: "A `StaffInstructor` (or `FacilityAdmin`) may **suspend** an
    `ACTIVE` member, moving them to `SUSPENDED`. Suspension triggers cascade A: every
    reservation belonging to that member whose `occupancy_status` is `HELD` or
    `CONFIRMED` is cancelled, and each such cancellation refunds its wallet hold
    exactly as a direct cancellation would."

    Suspending a member with a CONFIRMED reservation cascades that reservation to
    CANCELLED with billing REFUNDED.

    Design: Difficulty/transitive_cascade/member_suspend_cancels_reservation_refunds_wallet_depth3
    """
    member, machine, cert, res = setup_confirmed_reservation(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000, start_at="2026-04-20T10:00:00Z", end_at="2026-04-20T11:00:00Z",
    )
    suspended = validate_success(api.suspend_member(member["id"], make_staff_headers(member["id"])))
    assert suspended["subscription_status"] == "SUSPENDED"
    res_after = validate_success(api.get_reservation(res["id"], make_member_headers(member["id"])))
    assert res_after["occupancy_status"] == "CANCELLED", res_after["occupancy_status"]
    assert res_after["billing_status"] == "REFUNDED", res_after["billing_status"]


def test_suspend_cascade_refunds_wallet_hold(api):
    """PRD §3.10: "Suspension triggers cascade A: every reservation belonging to that
    member whose `occupancy_status` is `HELD` or `CONFIRMED` is cancelled, and each
    such cancellation refunds its wallet hold exactly as a direct cancellation
    would."
    PRD §3.6: "the cancellation refunds `wallet_credit_cents` by
    `estimate_charge_cents`."

    The 4820 hold is refunded by the cascaded cancel, returning the wallet to its
    pre-confirm 10000.

    Design: Difficulty/transitive_cascade/member_suspend_cancels_reservation_refunds_wallet_depth3
    """
    member, machine, cert, res = setup_confirmed_reservation(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000, start_at="2026-04-20T10:00:00Z", end_at="2026-04-20T11:00:00Z",
    )
    assert res["estimate_charge_cents"] == 4820
    validate_success(api.suspend_member(member["id"], make_staff_headers(member["id"])))
    mh = make_member_headers(member["id"])
    after = validate_success(api.get_member(member["id"], mh))
    assert after["wallet_credit_cents"] == 10000, after["wallet_credit_cents"]


# ===========================================================================
# transitive_cascade / workshop_complete_noshow_enrollment_depth2
# ===========================================================================
def test_complete_workshop_resolves_enrolled_to_no_show(api):
    """PRD §3.9: "Completing a workshop moves it from `RUNNING` to `COMPLETED` and,
    as a cascade, resolves every enrollment still in `ENROLLED` to `NO_SHOW`."

    Completing a RUNNING workshop with one still-ENROLLED member resolves that
    enrollment to NO_SHOW.

    Design: Difficulty/transitive_cascade/workshop_complete_noshow_enrollment_depth2
    """
    instructor, student, ws, enr = setup_running_workshop_with_enrollment(
        capacity=3, machine_class=None, starts_at="2026-04-05T09:00:00Z"
    )
    completed = validate_success(
        api.complete_workshop(ws["id"], make_staff_headers(instructor["id"]))
    )
    assert completed["status"] == "COMPLETED"
    enr_after = validate_success(
        api.get_enrollment(enr["id"], make_staff_headers(instructor["id"]))
    )
    assert enr_after["status"] == "NO_SHOW", enr_after["status"]


def test_complete_workshop_reaches_completed_status(api):
    """PRD §3.9: "Completing a workshop moves it from `RUNNING` to `COMPLETED` and,
    as a cascade, resolves every enrollment still in `ENROLLED` to `NO_SHOW`."

    The workshop itself reaches COMPLETED after the complete action.

    Design: Difficulty/transitive_cascade/workshop_complete_noshow_enrollment_depth2
    """
    instructor, student, ws, enr = setup_running_workshop_with_enrollment(
        capacity=3, machine_class=None, starts_at="2026-04-05T09:00:00Z"
    )
    completed = validate_success(
        api.complete_workshop(ws["id"], make_staff_headers(instructor["id"]))
    )
    assert completed["status"] == "COMPLETED", completed["status"]


# ===========================================================================
# Corner / cross_cutting_complexity_layers / cascade_member_cancel_releases_lockers
# ===========================================================================
def test_member_cancel_releases_assigned_locker(api):
    """PRD §3.10: "Cancellation cancels every reservation of that member whose
    `occupancy_status` is `HELD`, `CONFIRMED`, or `CHECKED_IN`, refunding each wallet
    hold; releases every locker of that member whose `status` is `ASSIGNED`, moving
    each to `RELEASED`."

    Cancelling a member who holds an ASSIGNED locker cascades the locker to RELEASED.

    Design: Corner/cross_cutting_complexity_layers/cascade_member_cancel_releases_lockers
    """
    member = create_active_member(tier_overrides=MAKER_TIER, topup_cents=10000)
    locker = assign_locker(member, used_liters=10, capacity_liters=100)
    mh = make_member_headers(member["id"])
    cancelled = validate_success(api.cancel_member(member["id"], mh))
    assert cancelled["subscription_status"] == "CANCELLED"
    locker_after = validate_success(api.get_locker(locker["id"], mh))
    assert locker_after["status"] == "RELEASED", locker_after["status"]
