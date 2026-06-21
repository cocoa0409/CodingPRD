"""Work and payment lifecycle: the two parallel appointment dimensions, photo
and cure gates, ceramic-vs-non-ceramic finish, terminal lockdown, cancellation,
no-show, and the release loyalty cascade.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_customer_headers,
    set_clock, seed_package, seed_vehicle_size_rate,
    create_customer, create_service_bay, create_mobile_unit,
    book_shop_appointment, book_mobile_appointment,
    advance_to_in_service, attach_photo, advance_to_ready_non_ceramic,
    advance_to_curing_ceramic, advance_ceramic_to_ready,
    pay_full, release_appointment,
)
from test_helpers.test_users import TEST_USERS

DETAILER = TEST_USERS["detailer_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]


def _seed_full_mobile(email, unit_code, start="2026-06-15T09:00:00Z"):
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email=email, full_name="LC Test")
    unit = create_mobile_unit(unit_code=unit_code, travel_buffer_minutes=30)
    appt = book_mobile_appointment(
        cust["id"], unit["id"], tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc=start,
    )
    return cust, appt


def _seed_ceramic_shop(email, bay_code, start="2026-06-15T08:00:00Z"):
    set_clock("2026-06-15T07:00:00Z")
    seed_package(tier="CERAMIC")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email=email, full_name="Ceramic Test")
    bay = create_service_bay(bay_code=bay_code, supports_ceramic=True)
    appt = book_shop_appointment(
        cust["id"], bay, tier="CERAMIC", vehicle_size="SEDAN",
        scheduled_start_utc=start,
    )
    return cust, bay, appt


# ──────────────────────────────────────────────────────────────────────
# Difficulty / non_linear_state_machine /
#   appointment_parallel_work_and_payment_dimensions_evolve_independently
# ──────────────────────────────────────────────────────────────────────

def test_deposit_advances_payment_axis_only():
    """PRD §2.8: "The two advance on their own triggers and are validated independently — an appointment can be fully paid while still in service, or be physically ready while still unpaid."
    PRD §3.7: "Capturing a deposit adds `deposit_cents` to `amount_charged_cents`, moves `payment_status` to `DEPOSIT_HELD`, and recomputes the outstanding balance."

    Design: Difficulty/non_linear_state_machine/appointment_parallel_work_and_payment_dimensions_evolve_independently
    """
    cust, bay, appt = _seed_ceramic_shop("ned@x.com", "B4")
    # CERAMIC/SEDAN provisional 50000, deposit = round_half_up(50000*0.2) = 10000.
    res = validate_success(
        api_client.capture_deposit(appt["id"], {"deposit_cents": 10000}, make_customer_headers(cust["id"])), 200
    )
    assert res["payment_status"] == "DEPOSIT_HELD"
    assert res["work_status"] == "BOOKED"
    assert res["amount_charged_cents"] == 10000
    assert res["outstanding_balance_cents"] == 40000


def test_work_axis_stays_booked_after_deposit():
    """PRD §2.8: "An appointment evolves along two independent axes that live on the same record. The `work_status` axis tracks the physical progress of the job; the `payment_status` axis tracks money."

    Design: Difficulty/non_linear_state_machine/appointment_parallel_work_and_payment_dimensions_evolve_independently
    """
    cust, bay, appt = _seed_ceramic_shop("ned2@x.com", "B4b")
    validate_success(
        api_client.capture_deposit(appt["id"], {"deposit_cents": 10000}, make_customer_headers(cust["id"])), 200
    )
    fetched = validate_success(
        api_client.get_appointment(appt["id"], make_customer_headers(cust["id"])), 200
    )
    assert fetched["work_status"] == "BOOKED"
    assert fetched["payment_status"] == "DEPOSIT_HELD"


# ──────────────────────────────────────────────────────────────────────
# Difficulty / non_linear_state_machine /
#   membership_cyclic_renew_loops_active_to_active
# ──────────────────────────────────────────────────────────────────────

def _seed_active_membership_for_renew(email):
    set_clock("2026-06-01T00:00:00Z")
    seed_package(tier="WASH")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email=email, full_name="Renew Test")
    from test_helpers.fixtures import create_active_membership
    mem = create_active_membership(cust["id"], default_vehicle_size="SEDAN")
    set_clock("2026-07-01T00:00:00Z")
    return cust, mem


def test_renew_keeps_active_and_advances_cycle():
    """PRD §3.5: "Renewing an `ACTIVE` membership is a cyclic transition that keeps the membership `ACTIVE` and is permitted only once the server's clock is at or past `cycle_start_utc` advanced by the thirty-day cycle; renewal expires any credit left unconsumed from the prior cycle (adding that remaining count to `credits_expired_total`), then grants one new credit (incrementing `credits_granted_total`), recomputes `credits_remaining`, and advances `cycle_start_utc` by the thirty-day cycle."

    Design: Difficulty/non_linear_state_machine/membership_cyclic_renew_loops_active_to_active
    """
    cust, mem = _seed_active_membership_for_renew("owen@x.com")
    res = validate_success(api_client.renew_membership(mem["id"], SCHEDULER), 200)
    assert res["status"] == "ACTIVE"
    assert res["credits_granted_total"] == 2
    assert res["cycle_start_utc"] == "2026-07-01T00:00:00.000Z"


def test_renew_grants_second_credit():
    """PRD §3.5: "then grants one new credit (incrementing `credits_granted_total`), recomputes `credits_remaining`, and advances `cycle_start_utc` by the thirty-day cycle."

    Design: Difficulty/non_linear_state_machine/membership_cyclic_renew_loops_active_to_active
    """
    cust, mem = _seed_active_membership_for_renew("owen2@x.com")
    res = validate_success(api_client.renew_membership(mem["id"], SCHEDULER), 200)
    assert res["credits_granted_total"] == 2


# ──────────────────────────────────────────────────────────────────────
# Corner / state_machines / start_prep_without_before_photo_rejected
# ──────────────────────────────────────────────────────────────────────

def test_start_prep_without_before_photo_rejected():
    """PRD §3.4: "A `BEFORE` photo must exist before prep begins, and an `AFTER` photo must exist before service is finished; either gate, when unmet, rejects the transition with `ERR_PHOTO_REQUIRED`."

    Design: Corner/state_machines/start_prep_without_before_photo_rejected
    """
    cust, appt = _seed_full_mobile("ph1@x.com", "MP1")
    get_success_data(api_client.check_in(appt["id"], DETAILER))
    res = api_client.start_prep(appt["id"], DETAILER)
    validate_error(res, "ERR_PHOTO_REQUIRED", 409)


# ──────────────────────────────────────────────────────────────────────
# Corner / state_machines / finish_service_without_after_photo_rejected
# ──────────────────────────────────────────────────────────────────────

def test_finish_service_without_after_photo_rejected():
    """PRD §3.4: "Finishing service is where the two non-ceramic and ceramic paths diverge, and both require that an `AFTER` photo already exists."
    PRD §3.4: "either gate, when unmet, rejects the transition with `ERR_PHOTO_REQUIRED`."

    Design: Corner/state_machines/finish_service_without_after_photo_rejected
    """
    cust, appt = _seed_full_mobile("ph2@x.com", "MP2")
    advance_to_in_service(appt["id"])  # BEFORE photo attached, now IN_SERVICE
    res = api_client.finish_service(appt["id"], DETAILER)
    validate_error(res, "ERR_PHOTO_REQUIRED", 409)


# ──────────────────────────────────────────────────────────────────────
# Corner / state_machines / ceramic_finish_cure_before_release_time_rejected
# ──────────────────────────────────────────────────────────────────────

def test_finish_cure_before_release_time_rejected():
    """PRD §3.4: "From `CURING`, finishing the cure advances the appointment to `READY`, but only once the server's clock is at or past `vehicle_release_utc`; an attempt before the cure has elapsed is rejected with `ERR_CURE_NOT_ELAPSED`."

    Design: Corner/state_machines/ceramic_finish_cure_before_release_time_rejected
    """
    cust, bay, appt = _seed_ceramic_shop("cu1@x.com", "CB1")
    advance_to_curing_ceramic(appt["id"])  # now CURING; release at 2026-06-16T12:45
    set_clock("2026-06-16T12:44:00Z")      # one minute before release
    res = api_client.finish_cure(appt["id"], DETAILER)
    validate_error(res, "ERR_CURE_NOT_ELAPSED", 409)


# ──────────────────────────────────────────────────────────────────────
# Corner / state_machines / ceramic_in_shop_finish_service_goes_to_curing_not_ready
# ──────────────────────────────────────────────────────────────────────

def test_ceramic_finish_service_goes_to_curing():
    """PRD §3.4: "For a ceramic tier (where `tier` is `CERAMIC`), finishing service instead advances `IN_SERVICE` to `CURING`, because the coating must cure before the vehicle can be released; no price cascade fires yet."

    Design: Corner/state_machines/ceramic_in_shop_finish_service_goes_to_curing_not_ready
    """
    cust, bay, appt = _seed_ceramic_shop("ce1@x.com", "CE1")
    finished = advance_to_curing_ceramic(appt["id"])
    assert finished["work_status"] == "CURING"


# ──────────────────────────────────────────────────────────────────────
# Corner / state_machines / cancel_already_cancelled_returns_invalid_state
# ──────────────────────────────────────────────────────────────────────

def test_cancel_already_cancelled_returns_invalid_state():
    """PRD §2.8: "A request to drive either axis along a transition that is not legal from the appointment's current state on that axis is rejected with `ERR_INVALID_STATE`."
    PRD §3.4: "A `Customer` may cancel its own appointment while it is still `BOOKED"

    Design: Corner/state_machines/cancel_already_cancelled_returns_invalid_state
    """
    cust, appt = _seed_full_mobile("cc1@x.com", "MC1")
    get_success_data(api_client.cancel_appointment(appt["id"], make_customer_headers(cust["id"])))
    res = api_client.cancel_appointment(appt["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_STATE", 409)


# ──────────────────────────────────────────────────────────────────────
# Corner / state_machines / released_appointment_terminal_lockdown
# ──────────────────────────────────────────────────────────────────────

def test_released_appointment_rejects_checkin():
    """PRD §3.4: "Checking in advances the appointment from `BOOKED` to `CHECKED_IN`. Check-in is allowed only when the appointment is still `BOOKED"
    PRD §2.8: "A request to drive either axis along a transition that is not legal from the appointment's current state on that axis is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/released_appointment_terminal_lockdown
    """
    cust, appt = _seed_full_mobile("tl1@x.com", "MT1")
    advance_to_ready_non_ceramic(appt["id"])
    pay_full(appt["id"], cust["id"], 12000)
    release_appointment(appt["id"])
    res = api_client.check_in(appt["id"], DETAILER)
    validate_error(res, "ERR_INVALID_STATE", 409)


# ──────────────────────────────────────────────────────────────────────
# Corner / state_machines / no_show_forfeits_deposit_no_refund
# ──────────────────────────────────────────────────────────────────────

def test_no_show_forfeits_deposit_no_refund():
    """PRD §3.4: "A no-show releases the occupancy window so the slot is reusable; if a deposit was being held, that deposit is forfeited — no refund is issued, `amount_refunded_cents` is left unchanged, and `payment_status` remains `DEPOSIT_HELD`."
    PRD §3.4: "a `Scheduler` or `ShopManager` may mark a still-`BOOKED` appointment as `NO_SHOW`, but only once the server's clock is at or past thirty minutes after `scheduled_start_utc`."

    Design: Corner/state_machines/no_show_forfeits_deposit_no_refund
    """
    cust, bay, appt = _seed_ceramic_shop("ns1@x.com", "NS1")
    validate_success(
        api_client.capture_deposit(appt["id"], {"deposit_cents": 10000}, make_customer_headers(cust["id"])), 200
    )
    set_clock("2026-06-15T08:31:00Z")  # > scheduled_start + 30 min
    res = validate_success(api_client.mark_no_show(appt["id"], SCHEDULER), 200)
    assert res["work_status"] == "NO_SHOW"
    assert res["payment_status"] == "DEPOSIT_HELD"
    assert res["amount_refunded_cents"] == 0


# ──────────────────────────────────────────────────────────────────────
# Corner / state_machines / release_cascade_updates_loyalty_tier_to_silver
# ──────────────────────────────────────────────────────────────────────

def test_release_cascade_updates_loyalty_to_silver():
    """PRD §3.6: "A customer is `GOLD` when their `chronological_lifetime_spend_cents` is at least one hundred fifty thousand cents, `SILVER` when it is at least fifty thousand cents (but below the gold threshold), and `BRONZE` otherwise; the comparisons are at-or-above, so a customer sitting exactly on a threshold qualifies for the higher band."
    PRD §3.6: "When release recomputes the realized spend, the released appointment's `final_total_cents` counts toward the sum only if its `payment_status` is `PAID`; the loyalty tier is then recomputed from the new realized spend, and if it rises into a higher band the customer's `loyalty_tier` field is updated."

    Design: Corner/state_machines/release_cascade_updates_loyalty_tier_to_silver
    """
    cust, bay, appt = _seed_ceramic_shop("ls1@x.com", "LS1")
    advance_ceramic_to_ready(appt["id"], "2026-06-16T12:45:00Z")
    pay_full(appt["id"], cust["id"], 50000)
    release_appointment(appt["id"])
    fetched = validate_success(
        api_client.get_customer(cust["id"], make_customer_headers(cust["id"])), 200
    )
    assert fetched["chronological_lifetime_spend_cents"] == 50000
    assert fetched["loyalty_tier"] == "SILVER"
