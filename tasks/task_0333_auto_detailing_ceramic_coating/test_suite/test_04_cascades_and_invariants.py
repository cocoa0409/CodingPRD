"""Cascades and conserved-quantity invariants: rework-approve spawn cascade,
cancel-refund-then-reproject cascade, refund cash conservation, membership
cancel credit conservation, the renew credit ledger, the membership-lapse
cross-entity clear, and the refund chronological-spend cascade.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_customer_headers,
    set_clock, seed_package, seed_vehicle_size_rate,
    create_customer, create_service_bay, create_mobile_unit,
    create_active_membership,
    book_shop_appointment, book_mobile_appointment,
    advance_to_ready_non_ceramic, pay_full, release_appointment,
    complete_ceramic_shop_to_released,
    setup_released_ceramic_with_in_window_claim,
    assert_payment_conservation, assert_credit_conservation,
)
from test_helpers.test_users import TEST_USERS

DETAILER = TEST_USERS["detailer_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
SHOP_MANAGER = TEST_USERS["shop_manager_headers"]


# ──────────────────────────────────────────────────────────────────────
# Difficulty / transitive_cascade /
#   rework_approve_spawns_appointment_then_forces_paid_depth3
# ──────────────────────────────────────────────────────────────────────

def test_rework_approve_spawns_zero_cost_appointment():
    """PRD §3.8: "Approving moves the claim to `APPROVED` and runs the rework-spawn cascade: its first hop creates a new appointment cloning the original's `tier`, `vehicle_size`, `location_mode`, and resource, beginning in `work_status` `BOOKED`, with `spawned_from_rework_claim_id` set to this claim and both `provisional_total_cents` and `final_total_cents` at zero (the zero-cost guarantee)"
    PRD §3.8: "The claim's `rework_appointment_id` is set to the spawned appointment's id, and the claim's `version` increments."

    Design: Difficulty/transitive_cascade/rework_approve_spawns_appointment_then_forces_paid_depth3
    """
    cust, bay, orig, claim = setup_released_ceramic_with_in_window_claim(email="pam@x.com")
    res = validate_success(
        api_client.approve_rework_claim(
            claim["id"], {"expected_claim_version": claim["version"]}, SCHEDULER
        ),
        200,
    )
    assert res["status"] == "APPROVED"
    assert res["rework_appointment_id"] is not None

    rework = validate_success(
        api_client.get_appointment(res["rework_appointment_id"], make_customer_headers(cust["id"])), 200
    )
    assert rework["spawned_from_rework_claim_id"] == claim["id"]
    assert rework["final_total_cents"] == 0
    assert rework["provisional_total_cents"] == 0


def test_rework_spawned_appointment_forced_paid_zero_outstanding():
    """PRD §3.8: "its second hop forces the spawned appointment's `payment_status` to `PAID` with `outstanding_balance_cents` at zero, so it is releasable without any payment."

    Design: Difficulty/transitive_cascade/rework_approve_spawns_appointment_then_forces_paid_depth3
    """
    cust, bay, orig, claim = setup_released_ceramic_with_in_window_claim(email="pam2@x.com")
    res = validate_success(
        api_client.approve_rework_claim(
            claim["id"], {"expected_claim_version": claim["version"]}, SCHEDULER
        ),
        200,
    )
    rework = validate_success(
        api_client.get_appointment(res["rework_appointment_id"], make_customer_headers(cust["id"])), 200
    )
    assert rework["payment_status"] == "PAID"
    assert rework["outstanding_balance_cents"] == 0


# ──────────────────────────────────────────────────────────────────────
# Difficulty / transitive_cascade /
#   appointment_cancel_refunds_deposit_then_reprojects_loyalty_depth2
# ──────────────────────────────────────────────────────────────────────

def _seed_ceramic_with_deposit(email, bay_code):
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="CERAMIC")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email=email, full_name="Cancel Test")
    bay = create_service_bay(bay_code=bay_code, supports_ceramic=True)
    appt = book_shop_appointment(
        cust["id"], bay, tier="CERAMIC", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T09:00:00Z",
    )
    validate_success(
        api_client.capture_deposit(appt["id"], {"deposit_cents": 10000}, make_customer_headers(cust["id"])), 200
    )
    return cust, appt


def test_cancel_refunds_held_deposit():
    """PRD §3.4: "if a deposit was being held (`payment_status` is `DEPOSIT_HELD`) — cascades a full deposit refund: the held amount is added to `amount_refunded_cents`, `payment_status` moves to `REFUNDED`, `outstanding_balance_cents` is recomputed"

    Design: Difficulty/transitive_cascade/appointment_cancel_refunds_deposit_then_reprojects_loyalty_depth2
    """
    cust, appt = _seed_ceramic_with_deposit("quin@x.com", "B6")
    res = validate_success(
        api_client.cancel_appointment(appt["id"], make_customer_headers(cust["id"])), 200
    )
    assert res["work_status"] == "CANCELLED"
    assert res["payment_status"] == "REFUNDED"
    assert res["amount_refunded_cents"] == 10000


def test_cancel_reprojects_loyalty_spend_to_zero():
    """PRD §3.4: "and the customer's projected spend and loyalty tier are recomputed because the cancelled appointment leaves the projected set."
    PRD §3.6: "those whose `work_status` is one of `BOOKED`, `CHECKED_IN`, `IN_PREP`, `IN_SERVICE`, `CURING`, or `READY` and whose `payment_status` is not `PAID"

    Design: Difficulty/transitive_cascade/appointment_cancel_refunds_deposit_then_reprojects_loyalty_depth2
    """
    cust, appt = _seed_ceramic_with_deposit("quin2@x.com", "B6b")
    get_success_data(api_client.cancel_appointment(appt["id"], make_customer_headers(cust["id"])))
    fetched = validate_success(
        api_client.get_customer(cust["id"], make_customer_headers(cust["id"])), 200
    )
    assert fetched["projected_lifetime_spend_cents"] == 0


# ──────────────────────────────────────────────────────────────────────
# Difficulty / compensating_invariant /
#   refund_preserves_payment_cash_conservation_cents
# ──────────────────────────────────────────────────────────────────────

def _seed_paid_released_full(email, unit_code):
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email=email, full_name="Refund Test")
    unit = create_mobile_unit(unit_code=unit_code, travel_buffer_minutes=30)
    appt = book_mobile_appointment(
        cust["id"], unit["id"], tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T09:00:00Z",
    )
    advance_to_ready_non_ceramic(appt["id"])
    pay_full(appt["id"], cust["id"], 12000)
    release_appointment(appt["id"])
    return cust, appt


def test_refund_full_compensating_amounts():
    """PRD §3.7: "A refund is a full compensating reversal: `amount_refunded_cents` is increased by the full `amount_charged_cents`, `payment_status` moves to `REFUNDED` (a terminal payment state), and the outstanding balance is recomputed so the conservation invariant holds afterward with zero net cash retained."

    Design: Difficulty/compensating_invariant/refund_preserves_payment_cash_conservation_cents
    """
    cust, appt = _seed_paid_released_full("zoe@x.com", "M6")
    res = validate_success(api_client.refund(appt["id"], SHOP_MANAGER), 200)
    assert res["payment_status"] == "REFUNDED"
    assert res["amount_charged_cents"] == 12000
    assert res["amount_refunded_cents"] == 12000
    assert res["outstanding_balance_cents"] == 12000


def test_refund_preserves_payment_conservation_identity():
    """PRD §3.7: "The payment-conservation invariant holds at all times: the amount charged minus the amount refunded plus the outstanding balance always equals `final_total_cents` minus `credit_applied_cents`."

    Design: Difficulty/compensating_invariant/refund_preserves_payment_cash_conservation_cents
    """
    cust, appt = _seed_paid_released_full("zoe2@x.com", "M6b")
    res = validate_success(api_client.refund(appt["id"], SHOP_MANAGER), 200)
    assert_payment_conservation(res)


# ──────────────────────────────────────────────────────────────────────
# Difficulty / compensating_invariant /
#   membership_cancel_preserves_credit_count_conservation
# ──────────────────────────────────────────────────────────────────────

def _seed_active_membership_for_cancel(email):
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="WASH")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email=email, full_name="Cancel Mem")
    mem = create_active_membership(cust["id"], default_vehicle_size="SEDAN")
    return cust, mem


def test_membership_cancel_expires_credits_and_clears_pointer():
    """PRD §3.5: "Cancelling moves the membership to `CANCELLED`, expires all remaining credits to `credits_expired_total` with `credits_remaining` recomputed to zero, and clears the customer's `membership_id` to null."

    Design: Difficulty/compensating_invariant/membership_cancel_preserves_credit_count_conservation
    """
    cust, mem = _seed_active_membership_for_cancel("abe@x.com")
    res = validate_success(
        api_client.cancel_membership(
            mem["id"], {"expected_membership_version": mem["version"]},
            make_customer_headers(cust["id"]),
        ),
        200,
    )
    assert res["status"] == "CANCELLED"
    assert res["credits_granted_total"] == 1
    assert res["credits_expired_total"] == 1
    assert res["credits_remaining"] == 0

    fetched_cust = validate_success(
        api_client.get_customer(cust["id"], make_customer_headers(cust["id"])), 200
    )
    assert fetched_cust["membership_id"] is None


def test_membership_cancel_preserves_credit_conservation():
    """PRD §3.5: "the invariant that granted equals consumed plus expired plus remaining holds at all times."

    Design: Difficulty/compensating_invariant/membership_cancel_preserves_credit_count_conservation
    """
    cust, mem = _seed_active_membership_for_cancel("abe2@x.com")
    res = validate_success(
        api_client.cancel_membership(
            mem["id"], {"expected_membership_version": mem["version"]},
            make_customer_headers(cust["id"]),
        ),
        200,
    )
    assert_credit_conservation(res)


# ──────────────────────────────────────────────────────────────────────
# Corner / state_machines / reject_rework_claim_branch
# ──────────────────────────────────────────────────────────────────────

def test_reject_rework_claim_no_spawn():
    """PRD §3.8: "Rejecting a claim, also by a `Scheduler` or `ShopManager`, simply moves it from `SUBMITTED` to `REJECTED`."

    Design: Corner/state_machines/reject_rework_claim_branch
    """
    cust, bay, orig, claim = setup_released_ceramic_with_in_window_claim(email="rj1@x.com")
    res = validate_success(api_client.reject_rework_claim(claim["id"], SCHEDULER), 200)
    assert res["status"] == "REJECTED"
    assert res["rework_appointment_id"] is None


# ──────────────────────────────────────────────────────────────────────
# Corner / state_machines / membership_lapse_clears_customer_membership_id_cross_entity
# ──────────────────────────────────────────────────────────────────────

def test_membership_lapse_clears_customer_membership_id():
    """PRD §3.5: "a `Scheduler` or `ShopManager` lapses the membership to `LAPSED`: all remaining credits are expired (added to `credits_expired_total`, with `credits_remaining` recomputed to zero), and a lapse cascade clears the customer's `membership_id` to null so future bookings price as a non-member."

    Design: Corner/state_machines/membership_lapse_clears_customer_membership_id_cross_entity
    """
    set_clock("2026-06-01T00:00:00Z")
    seed_package(tier="WASH")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="lp1@x.com", full_name="Lp One")
    mem = create_active_membership(cust["id"], default_vehicle_size="SEDAN")
    set_clock("2026-07-01T00:00:00Z")
    get_success_data(api_client.mark_membership_past_due(mem["id"], SCHEDULER))
    set_clock("2026-08-01T00:00:00Z")
    res = validate_success(api_client.lapse_membership(mem["id"], SCHEDULER), 200)
    assert res["status"] == "LAPSED"
    assert res["credits_remaining"] == 0

    fetched_cust = validate_success(
        api_client.get_customer(cust["id"], make_customer_headers(cust["id"])), 200
    )
    assert fetched_cust["membership_id"] is None


# ──────────────────────────────────────────────────────────────────────
# Corner / cross_cutting_complexity_layers /
#   cascade_refund_updates_chronological_spend_after_release
# ──────────────────────────────────────────────────────────────────────

def test_refund_drops_chronological_spend_to_zero():
    """PRD §3.7: "A refund also recomputes the customer's realized chronological spend and loyalty tier, because the refunded appointment no longer counts as realized."
    PRD §3.6: "A refund removes the refunded appointment from the realized sum and likewise recomputes the tier."

    Design: Corner/cross_cutting_complexity_layers/cascade_refund_updates_chronological_spend_after_release
    """
    cust, appt = _seed_paid_released_full("cr1@x.com", "CR1")
    # Released+PAID: chronological is 12000 first.
    pre = validate_success(
        api_client.get_customer(cust["id"], make_customer_headers(cust["id"])), 200
    )
    assert pre["chronological_lifetime_spend_cents"] == 12000
    get_success_data(api_client.refund(appt["id"], SHOP_MANAGER))
    post = validate_success(
        api_client.get_customer(cust["id"], make_customer_headers(cust["id"])), 200
    )
    assert post["chronological_lifetime_spend_cents"] == 0
    assert post["loyalty_tier"] == "BRONZE"


# ──────────────────────────────────────────────────────────────────────
# Corner / cross_cutting_complexity_layers /
#   renew_expires_unconsumed_credit_then_grants_new
# ──────────────────────────────────────────────────────────────────────

def test_renew_expires_prior_credit_then_grants_new():
    """PRD §3.5: "renewal expires any credit left unconsumed from the prior cycle (adding that remaining count to `credits_expired_total`), then grants one new credit (incrementing `credits_granted_total`), recomputes `credits_remaining"

    Design: Corner/cross_cutting_complexity_layers/renew_expires_unconsumed_credit_then_grants_new
    """
    set_clock("2026-06-01T00:00:00Z")
    seed_package(tier="WASH")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="rn1@x.com", full_name="Rn One")
    mem = create_active_membership(cust["id"], default_vehicle_size="SEDAN")
    set_clock("2026-07-01T00:00:00Z")
    res = validate_success(api_client.renew_membership(mem["id"], SCHEDULER), 200)
    assert res["credits_granted_total"] == 2
    assert res["credits_expired_total"] == 1
    assert res["credits_remaining"] == 1
    assert_credit_conservation(res)
