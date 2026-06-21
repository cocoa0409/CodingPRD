"""Site lifecycle (cyclic ACTIVE<->MAINTENANCE + RETIRED), the retire and
checkout cascades, optimistic concurrency on site version, and maintenance-hold
clearing.

Covers difficulty queue non_linear_state_machine (site cyclic) + transitive_cascade,
and corner state_machines / cross_cutting_complexity_layers claims.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    make_guest_headers,
    make_operator_headers,
    create_reservation_payload,
    ApiErrorId,
    setup_base_scenario,
    set_clock,
    create_reservation,
    create_confirmed_reservation,
    create_checked_in_reservation,
    check_out_reservation,
    pay_deposit,
    confirm_reservation,
    current_site_version,
    get_site,
    get_reservation,
    get_guest,
    retire_site,
)

OP = make_operator_headers()


# ===========================================================================
# Difficulty: non_linear_state_machine / site_cyclic_active_maintenance_active
# Corner stub corner_site_cycle_covered_by_difficulty is owned by this instance.
# ===========================================================================
def test_site_cycles_active_to_maintenance_to_active(api):
    """PRD §3.3: "From `ACTIVE` an operator may move it to `MAINTENANCE`; this
    transition is permitted only while the site is `ACTIVE`, and it bumps the
    site's `version`. ... From `MAINTENANCE` an operator may return it to
    `ACTIVE` (permitted only while it is `MAINTENANCE`), again bumping `version`."

    Design: Difficulty/non_linear_state_machine/site_cyclic_active_maintenance_active
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    v0 = site["version"]
    maint = validate_success(
        api.maintenance_site(site["id"], {"expected_site_version": v0}, OP),
        expected_status=200)
    assert maint["status"] == "MAINTENANCE"
    react = validate_success(
        api.reactivate_site(site["id"], {"expected_site_version": maint["version"]}, OP),
        expected_status=200)
    assert react["status"] == "ACTIVE"
    # create=1, maintenance=2, reactivate=3.
    assert react["version"] == 3


def test_maintenance_from_maintenance_is_invalid_state(api):
    """PRD §3.3: "this transition is permitted only while the site is `ACTIVE`"
    PRD §3.3: "Attempting any of these transitions from a state in which it is
    not defined is rejected with `ERR_INVALID_STATE` (409)."

    Design: Difficulty/non_linear_state_machine/site_cyclic_active_maintenance_active
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    v0 = site["version"]
    maint = validate_success(
        api.maintenance_site(site["id"], {"expected_site_version": v0}, OP),
        expected_status=200)
    # A second maintenance from MAINTENANCE is undefined.
    resp = api.maintenance_site(site["id"], {"expected_site_version": maint["version"]}, OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Difficulty: transitive_cascade /
#   site_retire_cancels_reservations_refunds_payments_recompute_guest
# ===========================================================================
def test_retire_site_cascades_cancel_refund_and_zero_booked_nights(api):
    """PRD §3.3: "First, every reservation on the site whose `reservation_status`
    is `REQUESTED`, `CONFIRMED`, or `CHECKED_IN` is moved to `CANCELLED`. Second,
    each such cancelled reservation that had a positive `amount_paid_cents`
    receives a `REFUND` payment for the full `amount_paid_cents` and has its
    `payment_status` set to `REFUNDED`, with the payment's `reason` recorded as
    `SITE_RETIRED`. ... Finally the site's `booked_night_count` is reset to 0 and
    its `version` is incremented."

    Design: Difficulty/transitive_cascade/site_retire_cancels_reservations_refunds_payments_recompute_guest
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    confirmed = create_confirmed_reservation(site, guest, "2026-08-01", "2026-08-11")
    retired = retire_site(site["id"])
    assert retired["status"] == "RETIRED"
    assert retired["booked_night_count"] == 0
    res = get_reservation(confirmed["id"])
    assert res["reservation_status"] == "CANCELLED"
    assert res["payment_status"] == "REFUNDED"


def test_retire_site_refund_payment_records_full_amount_paid(api):
    """PRD §3.3: "each such cancelled reservation that had a positive
    `amount_paid_cents` receives a `REFUND` payment for the full
    `amount_paid_cents` and has its `payment_status` set to `REFUNDED`"
    PRD §3.7: "`amount_paid_cents` is the sum of `DEPOSIT` and `BALANCE` payment
    amounts minus the `REFUND` amounts on the reservation"

    Design: Difficulty/transitive_cascade/site_retire_cancels_reservations_refunds_payments_recompute_guest
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    confirmed = create_confirmed_reservation(site, guest, "2026-08-01", "2026-08-11")
    deposit = confirmed["deposit_due_cents"]
    retire_site(site["id"])
    # The full deposit was refunded -> net amount_paid back to 0.
    res = get_reservation(confirmed["id"])
    assert res["amount_paid_cents"] == 0
    payments, _ = _list_payments(api, confirmed["id"])
    refunds = [p for p in payments if p["type"] == "REFUND"]
    assert len(refunds) == 1
    assert refunds[0]["amount_cents"] == deposit


# ===========================================================================
# Difficulty: transitive_cascade /
#   checkout_reconciles_charge_settles_balance_updates_guest
# ===========================================================================
def test_checkout_settles_balance_and_updates_guest(api):
    """PRD §3.7: "If the resulting `balance_cents` is greater than 0, the system
    auto-records a `BALANCE` payment for exactly that remaining balance and sets
    `payment_status` to `PAID_IN_FULL`. The guest's `completed_stays_count` is
    then increased by 1 and `lifetime_spend_cents` increased by the final
    `total_due_cents`."

    Design: Difficulty/transitive_cascade/checkout_reconciles_charge_settles_balance_updates_guest
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    res = create_checked_in_reservation(
        site, guest, "2026-08-01", "2026-08-11", checkin_clock="2026-08-01T12:00:00Z")
    set_clock("2026-08-11T12:00:00Z")  # full stay
    final = check_out_reservation(res)
    assert final["reservation_status"] == "CHECKED_OUT"
    assert final["payment_status"] == "PAID_IN_FULL"
    assert final["total_due_cents"] == 48600
    assert final["balance_cents"] == 0
    g = get_guest(guest["id"])
    assert g["completed_stays_count"] == 1
    assert g["lifetime_spend_cents"] == 48600


def test_checkout_full_stay_reconciles_total_due(api):
    """PRD §3.7: "It then re-runs the final stay charge over those `priced_nights`
    and reassembles `total_due_cents` per §3.6"
    PRD §3.5: "An operator later checks the guest out, moving a `CHECKED_IN`
    reservation to the terminal `CHECKED_OUT` state, permitted only when the
    reservation is `CHECKED_IN`"

    Design: Difficulty/transitive_cascade/checkout_reconciles_charge_settles_balance_updates_guest
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    res = create_checked_in_reservation(
        site, guest, "2026-08-01", "2026-08-11", checkin_clock="2026-08-01T12:00:00Z")
    set_clock("2026-08-11T12:00:00Z")
    final = check_out_reservation(res)
    # Full stay: priced_nights stays at the full 10, total unchanged at 48600.
    assert final["priced_nights"] == 10
    assert final["total_due_cents"] == 48600


# ===========================================================================
# Corner: state_machines / retired_site_rejects_new_reservation
# ===========================================================================
def test_reservation_on_retired_site_rejected(api):
    """PRD §3.5: "site availability is checked: the site must be neither `RETIRED`
    nor `MAINTENANCE`, or the request is rejected with `ERR_SITE_UNAVAILABLE`
    (409)."

    Design: Corner/state_machines/retired_site_rejects_new_reservation
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    retired = retire_site(site["id"])
    resp = api.create_reservation(
        site["id"],
        create_reservation_payload(guest["id"], "2026-08-01", "2026-08-11", retired["version"]),
        make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_SITE_UNAVAILABLE.value)


# ===========================================================================
# Corner: state_machines / cleared_maintenance_hold_no_longer_blocks_reservation
# ===========================================================================
def test_cleared_hold_no_longer_blocks_reservation(api):
    """PRD §3.4: "A cleared hold no longer blocks reservations on the site."
    PRD §3.4: "from `ACTIVE` an operator may clear it, moving it to the terminal
    `CLEARED` state, which is permitted only while it is `ACTIVE` and which bumps
    the host site's `version`."

    Design: Corner/state_machines/cleared_maintenance_hold_no_longer_blocks_reservation
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30, "turnover_buffer_days": 0})
    hold = validate_success(
        api.create_maintenance_hold(
            site["id"],
            {"start_date": "2026-08-10", "end_date": "2026-08-12",
             "reason": "repair", "expected_site_version": site["version"]},
            OP),
        expected_status=201)
    validate_success(api.clear_maintenance_hold(hold["id"], OP), expected_status=200)
    v = current_site_version(site["id"])
    resp = api.create_reservation(
        site["id"],
        create_reservation_payload(guest["id"], "2026-08-10", "2026-08-12", v),
        make_guest_headers(guest["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["reservation_status"] == "REQUESTED"


# ===========================================================================
# Corner: cross_cutting_complexity_layers / occ_stale_site_version_on_reservation_create
# ===========================================================================
def test_create_with_stale_site_version_rejected(api):
    """PRD §2.6: "when a reservation is created against a site, the request must
    carry `expected_site_version` matching that site's current `version`. If
    another writer has advanced the site's `version` since the client last read
    it, the create is rejected with `ERR_STALE_SITE_VERSION` (HTTP 412) before
    any locking takes place."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_site_version_on_reservation_create
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    stale_version = site["version"]
    # First create advances the site version.
    create_reservation(site, guest, "2026-08-01", "2026-08-05", expected_site_version=stale_version)
    # Second create still carrying the now-stale pre-create version.
    resp = api.create_reservation(
        site["id"],
        create_reservation_payload(guest["id"], "2026-09-01", "2026-09-05", stale_version),
        make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_SITE_VERSION.value)


# ===========================================================================
# Corner: cross_cutting_complexity_layers / occ_fresh_site_version_succeeds_and_bumps
# ===========================================================================
def test_create_with_fresh_site_version_succeeds_and_bumps(api):
    """PRD §2.6: "when a reservation is created against a site, the request must
    carry `expected_site_version` matching that site's current `version`."
    PRD §3.5: "Creation computes the provisional charges described in §3.6 and
    increases the site's `booked_night_count` by `nights`, bumping the site's
    `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_fresh_site_version_succeeds_and_bumps
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    create_reservation(site, guest, "2026-08-01", "2026-08-05", expected_site_version=site["version"])
    fresh_version = current_site_version(site["id"])
    resp = api.create_reservation(
        site["id"],
        create_reservation_payload(guest["id"], "2026-09-01", "2026-09-05", fresh_version),
        make_guest_headers(guest["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["reservation_status"] == "REQUESTED"
    assert get_site(site["id"])["version"] > fresh_version


# ===========================================================================
# Corner: cross_cutting_complexity_layers / derived_booked_night_count_after_create
# ===========================================================================
def test_booked_night_count_after_create(api):
    """PRD §3.5: "the site's `booked_night_count` is recomputed as the sum of
    `nights` across the reservations on that site whose `reservation_status` is
    `REQUESTED`, `CONFIRMED`, or `CHECKED_IN`"

    Design: Corner/cross_cutting_complexity_layers/derived_booked_night_count_after_create
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    create_reservation(site, guest, "2026-08-01", "2026-08-11")
    assert get_site(site["id"])["booked_night_count"] == 10


def _list_payments(api, reservation_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_payments(reservation_id, OP))
