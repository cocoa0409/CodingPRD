"""Deterministic error precedence when two guards could both fire on one request.

Each test constructs a scenario where exactly two named PRD checks are violated and
asserts the higher-precedence error is the one reported.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_tier,
    register_member,
    setup_member_machine_cert,
    create_held_reservation,
    make_member_headers,
)

MONTHLY_8000 = {
    "code": "MAKER", "name": "Maker", "billing_mode": "MONTHLY",
    "monthly_fee_cents": 8000, "discount_bps": 1000, "prepaid_machine_minutes": 0,
    "locker_free_liters": 50, "unsupervised_allowed": True,
}
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
# priority_pair_validation_conflict / waiver_required_beats_insufficient_funds
# ===========================================================================
def test_activate_unwaived_unfunded_reports_waiver_required(api):
    """PRD §3.2: "Activation moves the member from `PENDING_WAIVER` to `ACTIVE`. It
    is permitted only when `waiver_signed_at` is not null — otherwise the request is
    refused with `ERR_WAIVER_REQUIRED` (HTTP 409) — and when the member's `tier_id`
    resolves to a real tier. For a `MONTHLY` tier, activation also requires that
    `wallet_credit_cents` cover the **forward** prorated fee described in §3.9; if it
    does not, the activation is `ERR_INSUFFICIENT_FUNDS` (HTTP 409)."

    A member who has NOT signed the waiver AND has a 0 wallet against an 8000c
    monthly fee fails both guards; the waiver guard (named first) wins:
    ERR_WAIVER_REQUIRED, not ERR_INSUFFICIENT_FUNDS.

    Design: Difficulty/priority_pair_validation_conflict/waiver_required_beats_insufficient_funds
    """
    tier = create_tier(**MONTHLY_8000)
    member = register_member(tier["id"])  # PENDING_WAIVER, wallet 0, no waiver
    mh = make_member_headers(member["id"])
    validate_error(api.activate_member(member["id"], mh), ApiErrorId.ERR_WAIVER_REQUIRED.value)


def test_activate_waiver_failure_leaves_member_pending(api):
    """PRD §3.2: "Activation moves the member from `PENDING_WAIVER` to `ACTIVE`. It
    is permitted only when `waiver_signed_at` is not null — otherwise the request is
    refused with `ERR_WAIVER_REQUIRED` (HTTP 409)."
    PRD §3.2: "Registration starts the member in `PENDING_WAIVER` subscription status."

    The rejected activation leaves subscription_status PENDING_WAIVER (unchanged).

    Design: Difficulty/priority_pair_validation_conflict/waiver_required_beats_insufficient_funds
    """
    tier = create_tier(**MONTHLY_8000)
    member = register_member(tier["id"])
    mh = make_member_headers(member["id"])
    validate_error(api.activate_member(member["id"], mh), ApiErrorId.ERR_WAIVER_REQUIRED.value)
    after = validate_success(api.get_member(member["id"], mh))
    assert after["subscription_status"] == "PENDING_WAIVER", after["subscription_status"]


# ===========================================================================
# priority_pair_validation_conflict / invalid_state_beats_reservation_overlap
# ===========================================================================
def test_confirm_cancelled_reservation_reports_invalid_state_over_overlap(api):
    """PRD §2.6: "Only after these five gates do the state-machine and business rules
    of §3 apply: an illegal transition for the resource's current state is
    `ERR_INVALID_STATE` (HTTP 409), and the domain-specific safety, temporal, and
    fiscal checks described throughout §3 follow in the order their own narratives
    lay out."
    PRD §3.6: "the window still does not overlap another non-terminal reservation on
    the machine, or else `ERR_RESERVATION_OVERLAP` (HTTP 409)."

    Confirming an already-CANCELLED reservation whose window also overlaps a live
    confirmed reservation reports ERR_INVALID_STATE — the state check precedes the
    overlap (business_temporal) check.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_reservation_overlap
    """
    member, machine, cert = setup_member_machine_cert(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=20000,
    )
    mh = make_member_headers(member["id"])
    # X: 10:00-11:00 created then cancelled while HELD.
    res_x = create_held_reservation(
        member, machine, cert, "2026-04-22T10:00:00Z", "2026-04-22T11:00:00Z"
    )
    validate_success(api.cancel_reservation(res_x["id"], mh))
    # Y: 10:30-11:30 confirmed, occupying the LASER window so X would overlap.
    res_y = create_held_reservation(
        member, machine, cert, "2026-04-22T10:30:00Z", "2026-04-22T11:30:00Z"
    )
    v1 = validate_success(api.get_member(member["id"], mh))["version"]
    validate_success(api.confirm_reservation(res_y["id"], v1, mh))
    # Now confirm the CANCELLED X: state beats overlap.
    v2 = validate_success(api.get_member(member["id"], mh))["version"]
    validate_error(
        api.confirm_reservation(res_x["id"], v2, mh), ApiErrorId.ERR_INVALID_STATE.value
    )


def test_confirm_cancelled_reservation_does_not_change_its_state(api):
    """PRD §3.6: "A member may **cancel** a reservation that is `HELD` or
    `CONFIRMED`. Cancellation moves `occupancy_status` to `CANCELLED`."
    PRD §2.6: "an illegal transition for the resource's current state is
    `ERR_INVALID_STATE` (HTTP 409)."

    The CANCELLED reservation X stays CANCELLED after the rejected confirm.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_reservation_overlap
    """
    member, machine, cert = setup_member_machine_cert(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=20000,
    )
    mh = make_member_headers(member["id"])
    res_x = create_held_reservation(
        member, machine, cert, "2026-04-22T10:00:00Z", "2026-04-22T11:00:00Z"
    )
    validate_success(api.cancel_reservation(res_x["id"], mh))
    res_y = create_held_reservation(
        member, machine, cert, "2026-04-22T10:30:00Z", "2026-04-22T11:30:00Z"
    )
    v1 = validate_success(api.get_member(member["id"], mh))["version"]
    validate_success(api.confirm_reservation(res_y["id"], v1, mh))
    v2 = validate_success(api.get_member(member["id"], mh))["version"]
    validate_error(api.confirm_reservation(res_x["id"], v2, mh), ApiErrorId.ERR_INVALID_STATE.value)
    x_after = validate_success(api.get_reservation(res_x["id"], mh))
    assert x_after["occupancy_status"] == "CANCELLED", x_after["occupancy_status"]
