"""Reservation parallel state dimensions, certification expiry/renewal cycle,
cross-entity state dependencies, and invalid-state lockdowns.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_tier,
    register_member,
    create_certification_for,
    setup_member_machine_cert,
    setup_confirmed_reservation,
    create_held_reservation,
    set_clock,
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
# non_linear_state_machine / reservation_parallel_occupancy_x_billing_dimensions
# ===========================================================================
def test_release_hold_moves_both_dimensions_back(api):
    """PRD §3.5: "Reservations track two parallel dimensions that advance
    independently. The **occupancy_status** runs over `HELD`, `CONFIRMED`,
    `CHECKED_IN`, `COMPLETED`, `CANCELLED`, and `NO_SHOW` ... The **billing_status**
    runs over `UNBILLED`, `HOLD_PLACED`, `SETTLED`, and `REFUNDED`."
    PRD §3.6: "Before the window opens, a member may **release the hold**, moving the
    reservation from `CONFIRMED` back to `HELD`. ... Releasing refunds
    `wallet_credit_cents` by `estimate_charge_cents`, sets `billing_status` back to
    `UNBILLED`."

    Confirm advances occupancy HELD->CONFIRMED and billing UNBILLED->HOLD_PLACED;
    release-hold returns occupancy to HELD and billing to UNBILLED.

    Design: Difficulty/non_linear_state_machine/reservation_parallel_occupancy_x_billing_dimensions
    """
    member, machine, cert, res = setup_confirmed_reservation(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000, start_at="2026-04-15T10:00:00Z", end_at="2026-04-15T11:00:00Z",
    )
    assert res["occupancy_status"] == "CONFIRMED"
    assert res["billing_status"] == "HOLD_PLACED"
    mh = make_member_headers(member["id"])
    released = validate_success(api.release_hold(res["id"], mh))
    assert released["occupancy_status"] == "HELD"
    assert released["billing_status"] == "UNBILLED"


def test_release_hold_refunds_estimate_to_wallet(api):
    """PRD §3.6: "Releasing refunds `wallet_credit_cents` by `estimate_charge_cents`,
    sets `billing_status` back to `UNBILLED`, restores `prepaid_minutes_remaining` by
    `free_minutes_applied`, resets `free_minutes_applied` to 0, and appends a
    `WalletEntry` of kind `REFUND` with a positive `amount_cents` equal to the
    estimate."

    A 60-min LASER reserve estimates 4820; after confirm-then-release the wallet
    returns to its pre-confirm 10000.

    Design: Difficulty/non_linear_state_machine/reservation_parallel_occupancy_x_billing_dimensions
    """
    member, machine, cert, res = setup_confirmed_reservation(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000, start_at="2026-04-15T10:00:00Z", end_at="2026-04-15T11:00:00Z",
    )
    mh = make_member_headers(member["id"])
    validate_success(api.release_hold(res["id"], mh))
    after = validate_success(api.get_member(member["id"], mh))
    assert after["wallet_credit_cents"] == 10000, after["wallet_credit_cents"]


# ===========================================================================
# non_linear_state_machine / certification_cyclic_active_expired_active_loop
# ===========================================================================
def test_certification_lapses_to_expired_on_refresh(api):
    """PRD §3.4: "Re-evaluating a certification against the logical clock moves it
    from `ACTIVE` to `EXPIRED` only when it is currently `ACTIVE` and the clock now
    is at or past its `expires_at`."

    A LASER cert granted at the 2026-04-01 clock default expires 2027-04-01; after
    advancing the clock to 2027-05-01 and calling refresh-expiry the cert is EXPIRED.

    Design: Difficulty/non_linear_state_machine/certification_cyclic_active_expired_active_loop
    """
    tier = create_tier(**MAKER_TIER)
    member = register_member(tier["id"])
    cert = create_certification_for(member["id"], "LASER")
    set_clock("2027-05-01T00:00:00Z")
    expired = validate_success(
        api.refresh_expiry(cert["id"], make_staff_headers(member["id"]))
    )
    assert expired["status"] == "EXPIRED", expired["status"]


def test_renew_returns_to_active_and_advances_expiry(api):
    """PRD §3.4: "Renewing an expired certification moves it from `EXPIRED` back to
    `ACTIVE`, sets a fresh `granted_at` to the clock now and `expires_at` to 365 days
    later, and recomputes `readiness_score`."

    Renewed at clock 2027-05-01: status returns to ACTIVE and expires_at becomes
    2028-04-30T00:00:00.000Z (2028 is a leap year).

    Design: Difficulty/non_linear_state_machine/certification_cyclic_active_expired_active_loop
    """
    tier = create_tier(**MAKER_TIER)
    member = register_member(tier["id"])
    cert = create_certification_for(member["id"], "LASER")
    sh = make_staff_headers(member["id"])
    set_clock("2027-05-01T00:00:00Z")
    validate_success(api.refresh_expiry(cert["id"], sh))
    renewed = validate_success(api.renew_certification(cert["id"], sh))
    assert renewed["status"] == "ACTIVE", renewed["status"]
    assert renewed["expires_at"] == "2028-04-30T00:00:00.000Z", renewed["expires_at"]


# ===========================================================================
# cross_entity_state_dependency / reservation_confirm_requires_member_active
# ===========================================================================
def test_confirm_blocked_when_member_suspended(api):
    """PRD §3.6: "The confirm proceeds only when all of the following hold, each with
    its own rejection: the member's `subscription_status` is `ACTIVE`."
    PRD §2.6: "an illegal transition for the resource's current state is
    `ERR_INVALID_STATE` (HTTP 409)."

    A suspended member with a fresh HELD reservation cannot confirm it.

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_requires_member_active
    """
    member, machine, cert = setup_member_machine_cert(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000,
    )
    # Suspend first (no live reservations), then create a fresh HELD reservation.
    validate_success(api.suspend_member(member["id"], make_staff_headers(member["id"])))
    res = create_held_reservation(
        member, machine, cert, "2026-04-28T10:00:00Z", "2026-04-28T11:00:00Z"
    )
    mh = make_member_headers(member["id"])
    v = validate_success(api.get_member(member["id"], mh))["version"]
    validate_error(
        api.confirm_reservation(res["id"], v, mh), ApiErrorId.ERR_INVALID_STATE.value
    )


def test_confirm_blocked_when_suspended_leaves_reservation_held(api):
    """PRD §3.6: "The confirm proceeds only when all of the following hold, each with
    its own rejection: the member's `subscription_status` is `ACTIVE`."
    PRD §3.5: "A new reservation begins `HELD` on its occupancy dimension."

    The rejected confirm leaves the reservation in HELD (unchanged).

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_requires_member_active
    """
    member, machine, cert = setup_member_machine_cert(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000,
    )
    validate_success(api.suspend_member(member["id"], make_staff_headers(member["id"])))
    res = create_held_reservation(
        member, machine, cert, "2026-04-28T10:00:00Z", "2026-04-28T11:00:00Z"
    )
    mh = make_member_headers(member["id"])
    v = validate_success(api.get_member(member["id"], mh))["version"]
    validate_error(api.confirm_reservation(res["id"], v, mh), ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = validate_success(api.get_reservation(res["id"], mh))
    assert refreshed["occupancy_status"] == "HELD", refreshed["occupancy_status"]


# ===========================================================================
# Corner / state_machines / confirm_already_confirmed_reservation_returns_invalid_state
# ===========================================================================
def test_confirm_already_confirmed_returns_invalid_state(api):
    """PRD §2.6: "an illegal transition for the resource's current state is
    `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.6: "It moves the reservation from `HELD` to `CONFIRMED`."

    Confirming a reservation already in CONFIRMED (not HELD) is rejected; the
    single 4820 debit is not repeated, so the wallet stays 5180.

    Design: Corner/state_machines/confirm_already_confirmed_reservation_returns_invalid_state
    """
    member, machine, cert, res = setup_confirmed_reservation(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000, start_at="2026-05-10T10:00:00Z", end_at="2026-05-10T11:00:00Z",
    )
    mh = make_member_headers(member["id"])
    v = validate_success(api.get_member(member["id"], mh))["version"]
    validate_error(api.confirm_reservation(res["id"], v, mh), ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_member(member["id"], mh))
    assert after["wallet_credit_cents"] == 5180, after["wallet_credit_cents"]


# ===========================================================================
# Corner / state_machines / cancel_terminal_completed_reservation_returns_invalid_state
# ===========================================================================
def test_cancel_completed_reservation_returns_invalid_state(api):
    """PRD §3.6: "A member may **cancel** a reservation that is `HELD` or
    `CONFIRMED`."
    PRD §2.6: "an illegal transition for the resource's current state is
    `ERR_INVALID_STATE` (HTTP 409)."

    A reservation driven to COMPLETED (a terminal occupancy state) cannot be
    cancelled.

    Design: Corner/state_machines/cancel_terminal_completed_reservation_returns_invalid_state
    """
    member, machine, cert, res = setup_confirmed_reservation(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000, start_at="2026-05-12T10:00:00Z", end_at="2026-05-12T11:00:00Z",
    )
    mh = make_member_headers(member["id"])
    set_clock("2026-05-12T10:00:00Z")
    validate_success(api.check_in(res["id"], mh))
    set_clock("2026-05-12T10:30:00Z")
    completed = validate_success(api.check_out(res["id"], mh))
    assert completed["occupancy_status"] == "COMPLETED"
    validate_error(api.cancel_reservation(res["id"], mh), ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner / state_machines / check_in_before_window_returns_window_not_open
# ===========================================================================
def test_check_in_before_window_returns_window_not_open(api):
    """PRD §3.6: "**Checking in** moves the reservation from `CONFIRMED` to
    `CHECKED_IN`. It is permitted only while the reservation is `CONFIRMED` and the
    logical clock now is at or after `start_at` and strictly before `end_at`; a
    check-in attempted before the window opens or after it closes is refused with
    `ERR_WINDOW_NOT_OPEN` (HTTP 409)."

    With the clock at its 2026-04-01 default and the window opening 2026-05-15,
    check-in is rejected.

    Design: Corner/state_machines/check_in_before_window_returns_window_not_open
    """
    member, machine, cert, res = setup_confirmed_reservation(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000, start_at="2026-05-15T10:00:00Z", end_at="2026-05-15T11:00:00Z",
    )
    mh = make_member_headers(member["id"])
    validate_error(api.check_in(res["id"], mh), ApiErrorId.ERR_WINDOW_NOT_OPEN.value)


# ===========================================================================
# Corner / state_machines / certification_expired_blocks_confirm_via_invalid_state
# ===========================================================================
def test_expired_cert_confirm_returns_certification_required(api):
    """PRD §3.6: "if the machine's `requires_certification` is true, a certification
    on the member and the machine's `machine_class` with `status` of `ACTIVE` exists
    and is the one named by `certification_id`, or else `ERR_CERTIFICATION_REQUIRED`
    (HTTP 409)."

    After the relied-upon cert lapses to EXPIRED, confirming a new HELD reservation
    that names it is rejected — no ACTIVE cert on (member, class).

    Design: Corner/state_machines/certification_expired_blocks_confirm_via_invalid_state
    """
    member, machine, cert = setup_member_machine_cert(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000,
    )
    sh = make_staff_headers(member["id"])
    set_clock("2027-05-01T00:00:00Z")
    validate_success(api.refresh_expiry(cert["id"], sh))
    res = create_held_reservation(
        member, machine, cert, "2027-06-01T10:00:00Z", "2027-06-01T11:00:00Z"
    )
    mh = make_member_headers(member["id"])
    v = validate_success(api.get_member(member["id"], mh))["version"]
    validate_error(
        api.confirm_reservation(res["id"], v, mh), ApiErrorId.ERR_CERTIFICATION_REQUIRED.value
    )
