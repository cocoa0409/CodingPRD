"""The remake cycle and its cascade: FINAL-fail -> REMAKE, compensation credit, fresh
fabric reservation, customer remake-risk recomputation, the remake limit, and the
FINAL-pass bubble-up to READY.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_fabric, create_master_tailor, create_open_room,
    create_order_at_scheduled_final, fail_final_into_remake, create_confirmed_order_with_deposit,
    create_fitting_payload,
    TEST_USERS,
)

SA = TEST_USERS["sales_associate_headers"]
FS = TEST_USERS["fitting_specialist_headers"]
SM = TEST_USERS["shop_manager_headers"]


def _schedule(api, order_id, tailor_id, room_id, milestone, version, start_at, end_at):
    return get_success_data(api.create_fitting(
        order_id,
        create_fitting_payload(tailor_id, room_id, milestone, start_at, end_at, version),
        FS))


# ─── Queue A: non_linear_state_machine (remake cycle) ───────────────────

def test_remake_cycle_loops_back_to_in_fitting(api):
    """PRD §3.5: "From `REMAKE`, scheduling a new fitting reopens the workflow: the first fitting of the new round must again be at the `BASTED` milestone, and scheduling it returns the order to `IN_FITTING` at the new remake round."

    Order driven to REMAKE (remake_round 1); scheduling a fresh BASTED loops it back to
    IN_FITTING with remake_round still 1.

    Design: Difficulty/non_linear_state_machine/nonlinear_order_remake_cycle_in_fitting_to_remake_to_in_fitting
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=100)
    bundle = create_order_at_scheduled_final(fabric=fabric, bolt_meters_initial=100)
    bundle = fail_final_into_remake(bundle)
    order = bundle["order"]
    assert order["status"] == "REMAKE"
    assert order["remake_round"] == 1

    new_basted = _schedule(api, order["id"], bundle["tailor"]["id"], bundle["room"]["id"],
                           "BASTED", order["version"],
                           "2026-07-25T09:00:00.000Z", "2026-07-25T10:00:00.000Z")
    after = get_success_data(api.get_order(order["id"], SA))
    assert after["status"] == "IN_FITTING"
    assert after["remake_round"] == 1
    assert new_basted["milestone"] == "BASTED"


def test_remake_increments_round_and_reservation(api):
    """PRD §3.5: "If the failing fitting is at `FINAL` and the order's `remake_round` is below the limit of two remakes, the order cascades from `IN_FITTING` to `REMAKE`. A remake cascade does several things at once: it increments `remake_round` by one".

    Second non-linear instance focusing on the IN_FITTING -> REMAKE leg of the cycle:
    a FINAL fail moves the order to REMAKE and remake_round becomes 1.

    Design: Difficulty/non_linear_state_machine/nonlinear_order_remake_cycle_in_fitting_to_remake_to_in_fitting
    """
    bundle = create_order_at_scheduled_final()
    assert bundle["order"]["remake_round"] == 0
    bundle = fail_final_into_remake(bundle)
    assert bundle["order"]["status"] == "REMAKE"
    assert bundle["order"]["remake_round"] == 1


# ─── Queue A: transitive_cascade (depth-3 FINAL-fail) ───────────────────

def test_final_fail_cascades_remake_credit_and_fabric_rereserve(api):
    """PRD §3.5: "it grants the customer goodwill store credit by adding the computed remake compensation to `store_credit_cents`; it reserves a fresh cut of fabric by reducing the fabric's `bolt_meters_remaining` by the order's `fabric_meters_required` again".
    PRD §3.5: "a base of 5000 cents plus 3000 cents times the quantity (remake round minus one), evaluated after `remake_round` has already been incremented, so the first remake yields exactly the 5000-cent base."

    Depth-3 chain: FINAL fitting FAILED -> order REMAKE -> customer credited 5000 +
    remake_count 1, and a fresh 7m cut reserved (bolt 100 - 7 confirm - 7 remake = 86).

    Design: Difficulty/transitive_cascade/cascade_final_fail_remake_credit_fabric_risk_depth3
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=100)
    bundle = create_order_at_scheduled_final(fabric=fabric, bolt_meters_initial=100,
                                             base_labor_cents=40000, fabric_meters_required=7.0)
    customer_id = bundle["customer"]["id"]
    fabric_id = bundle["fabric"]["id"]
    bundle = fail_final_into_remake(bundle)

    order = bundle["order"]
    assert order["status"] == "REMAKE"
    assert order["remake_round"] == 1

    customer = get_success_data(api.get_customer(customer_id, SA))
    assert customer["store_credit_cents"] == 5000, \
        f"Expected 5000 goodwill credit, got {customer['store_credit_cents']}"
    assert customer["remake_count"] == 1

    fab = get_success_data(api.get_fabric(fabric_id, SM))
    assert fab["bolt_meters_remaining"] == 86, \
        f"Expected 86 (100-7-7), got {fab['bolt_meters_remaining']}"


def test_final_fail_cascade_closes_scheduled_fitting_to_failed(api):
    """PRD §3.5: "it closes the round by transitioning every still-`SCHEDULED` fitting on the order to `FAILED`."
    PRD §3.5: "If the failing fitting is at `FINAL` and the order's `remake_round` is below the limit of two remakes, the order cascades from `IN_FITTING` to `REMAKE`."

    Second transitive-cascade instance on the round-close limb: the FINAL fitting that was
    recorded FAILED ends as FAILED and the order is REMAKE — a distinct cascade limb from
    the credit/fabric effects.

    Design: Difficulty/transitive_cascade/cascade_final_fail_remake_credit_fabric_risk_depth3
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=100)
    bundle = create_order_at_scheduled_final(fabric=fabric, bolt_meters_initial=100,
                                             base_labor_cents=40000, fabric_meters_required=7.0)
    order_id = bundle["order"]["id"]
    final_id = bundle["fittings"]["final"]["id"]
    bundle = fail_final_into_remake(bundle)
    assert bundle["order"]["status"] == "REMAKE"

    fittings = get_success_data(api.list_fittings(order_id, SA))
    final_fitting = next(f for f in fittings if f["id"] == final_id)
    assert final_fitting["outcome"] == "FAILED"


def test_cancel_releases_fabric_and_refunds_deposit_to_credit(api):
    """PRD §3.8: "each active fabric reservation it holds is released by crediting the order's `fabric_meters_required` back onto the fabric's `bolt_meters_remaining`".
    PRD §3.8: "Every `CAPTURED` payment on the order is set to `REFUNDED`, and the sum of those refunded amounts is added to the customer's `store_credit_cents` as a refund-to-credit".
    PRD §3.8: "The linked measurement profile, if `LOCKED`, is moved to `SUPERSEDED`."

    Depth-2 chain from order cancel: cancel releases the 7m reservation (back to 50),
    refunds the 48750 deposit to store credit, and supersedes the profile.

    Design: Difficulty/transitive_cascade/cascade_order_cancel_releases_fabric_and_refunds_to_credit_depth2
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=50)
    bundle = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=50,
                                                 base_labor_cents=40000, fabric_meters_required=7.0)
    order_id = bundle["order"]["id"]
    customer_id = bundle["customer"]["id"]
    profile_id = bundle["profile"]["id"]
    fabric_id = bundle["fabric"]["id"]

    cancelled = validate_success(api.cancel_order(order_id, SM), 200)
    assert cancelled["status"] == "CANCELLED"

    fab = get_success_data(api.get_fabric(fabric_id, SM))
    assert fab["bolt_meters_remaining"] == 50, \
        f"Expected fabric released back to 50, got {fab['bolt_meters_remaining']}"

    customer = get_success_data(api.get_customer(customer_id, SA))
    assert customer["store_credit_cents"] == 48750, \
        f"Expected 48750 refunded to credit, got {customer['store_credit_cents']}"

    profile = get_success_data(api.get_measurement_profile(profile_id, SA))
    assert profile["status"] == "SUPERSEDED"


def test_cancel_in_fitting_fails_scheduled_fittings(api):
    """PRD §3.8: "Every still-`SCHEDULED` fitting on the order is transitioned to `FAILED`."
    PRD §3.8: "A **ShopManager** may cancel an order at any point before it has been picked up — from `DRAFT`, `CONFIRMED`, `IN_FITTING`, or `REMAKE`."

    Second depth-2 cascade instance on a different limb: cancelling an IN_FITTING order
    (reached via a scheduled BASTED fitting) FAILs that still-SCHEDULED fitting as part of
    the cancel cascade.

    Design: Difficulty/transitive_cascade/cascade_order_cancel_releases_fabric_and_refunds_to_credit_depth2
    """
    from test_helpers import create_journeyman_tailor
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=50)
    tailor = create_journeyman_tailor()
    room = create_open_room()
    bundle = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=50,
                                                 base_labor_cents=40000, fabric_meters_required=7.0)
    order = get_success_data(api.get_order(bundle["order"]["id"], SA))
    basted = _schedule(api, order["id"], tailor["id"], room["id"], "BASTED", order["version"],
                       "2026-07-08T09:00:00.000Z", "2026-07-08T10:00:00.000Z")
    in_fitting = get_success_data(api.get_order(order["id"], SA))
    assert in_fitting["status"] == "IN_FITTING"

    validate_success(api.cancel_order(order["id"], SM), 200)
    fittings = get_success_data(api.list_fittings(order["id"], SA))
    basted_after = next(f for f in fittings if f["id"] == basted["id"])
    assert basted_after["outcome"] == "FAILED"


# ─── Queue A: dual_variant_calc (customer remake-risk band) ─────────────

def test_remake_drives_customer_risk_band_high(api):
    """PRD §3.6: "if the rate is at least 0.50 the band is `HIGH_RISK`".
    PRD §3.6: "The rate is the customer's `remake_count` divided by a denominator that is the greater of 1 and the sum of their `completed_order_count` and `remake_count`".
    PRD §3.5: "it increments the customer's lifetime `remake_count` by one and recomputes their `remake_risk_band`".

    One remake, zero completed: remake_rate = 1 / max(1, 0+1) = 1.0 >= 0.50 -> HIGH_RISK.
    This is a customer-domain risk band, distinct from the order's tiered cost.

    Design: Difficulty/dual_variant_calc/dual_variant_customer_remake_risk_band_vs_order_cost
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=50)
    bundle = create_order_at_scheduled_final(fabric=fabric, bolt_meters_initial=50,
                                             base_labor_cents=40000, fabric_meters_required=7.0)
    customer_id = bundle["customer"]["id"]
    bundle = fail_final_into_remake(bundle)
    assert bundle["order"]["status"] == "REMAKE"

    customer = get_success_data(api.get_customer(customer_id, SA))
    assert customer["remake_count"] == 1
    assert customer["completed_order_count"] == 0
    assert customer["remake_risk_band"] == "HIGH_RISK"


def test_remake_grants_goodwill_credit_round_one_base(api):
    """PRD §3.5: "The **remake compensation** granted on each remake is a goodwill credit scaled by the round: it is 5000 cents for the first remake plus an additional 3000 cents for each round beyond the first".
    PRD §3.5: "This raw figure is then capped so the credit never exceeds the order's `locked_total_cents`; the compensation actually granted is the lesser of the scaled figure and the locked total."

    Second dual-variant instance: the customer-domain compensation on remake round 1 is
    min(5000, locked 97500) = 5000.

    Design: Difficulty/dual_variant_calc/dual_variant_customer_remake_risk_band_vs_order_cost
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=50)
    bundle = create_order_at_scheduled_final(fabric=fabric, bolt_meters_initial=50,
                                             base_labor_cents=40000, fabric_meters_required=7.0)
    customer_id = bundle["customer"]["id"]
    assert bundle["order"]["locked_total_cents"] == 97500
    bundle = fail_final_into_remake(bundle)
    customer = get_success_data(api.get_customer(customer_id, SA))
    assert customer["store_credit_cents"] == 5000


# ─── Queue B: state_machines / cross_cutting corner ─────────────────────

def test_final_pass_bubbles_order_to_ready(api):
    """PRD §3.5: "Recording a **pass at the `FINAL` milestone** bubbles the order up from `IN_FITTING` to `READY`, signaling that the garment is made and the order is ready for balance settlement and pickup".

    Design: Corner/state_machines/final_pass_bubbles_order_to_ready
    """
    bundle = create_order_at_scheduled_final()
    order_id = bundle["order"]["id"]
    final = validate_success(api.record_fitting_outcome(
        order_id, bundle["fittings"]["final"]["id"], {"result": "PASS"}, FS), 200)
    assert final["outcome"] == "PASSED"
    after = get_success_data(api.get_order(order_id, SA))
    assert after["status"] == "READY"


def test_remake_limit_blocks_third_final_fail(api):
    """PRD §3.5: "If a final fitting fails when `remake_round` has already reached the limit of two, no further remake is permitted and the request is rejected with `ERR_REMAKE_LIMIT_REACHED` (HTTP 409)."

    Fail FINAL twice (remake_round 2), reach a third FINAL, fail again -> rejected; order
    stays IN_FITTING and remake_round stays 2.

    Design: Corner/cross_cutting_complexity_layers/remake_limit_reached_blocks_third_final_fail
    """
    tailor = create_master_tailor()
    room = create_open_room()
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=200)
    bundle = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=200,
                                                 base_labor_cents=40000, fabric_meters_required=7.0)
    order_id = bundle["order"]["id"]

    day = 1

    def run_round(expect_fail=True, final_result="FAIL"):
        nonlocal day
        order = get_success_data(api.get_order(order_id, SA))
        b = _schedule(api, order_id, tailor["id"], room["id"], "BASTED", order["version"],
                      f"2026-08-{day:02d}T09:00:00.000Z", f"2026-08-{day:02d}T10:00:00.000Z")
        day += 1
        get_success_data(api.record_fitting_outcome(order_id, b["id"], {"result": "PASS"}, FS))
        order = get_success_data(api.get_order(order_id, SA))
        f = _schedule(api, order_id, tailor["id"], room["id"], "FORWARD", order["version"],
                      f"2026-08-{day:02d}T09:00:00.000Z", f"2026-08-{day:02d}T10:00:00.000Z")
        day += 1
        get_success_data(api.record_fitting_outcome(order_id, f["id"], {"result": "PASS"}, FS))
        order = get_success_data(api.get_order(order_id, SA))
        fn = _schedule(api, order_id, tailor["id"], room["id"], "FINAL", order["version"],
                       f"2026-08-{day:02d}T09:00:00.000Z", f"2026-08-{day:02d}T10:00:00.000Z")
        day += 1
        return fn

    # round 0 FINAL fail -> remake_round 1
    fn0 = run_round()
    get_success_data(api.record_fitting_outcome(order_id, fn0["id"], {"result": "FAIL"}, FS))
    # round 1 FINAL fail -> remake_round 2
    fn1 = run_round()
    get_success_data(api.record_fitting_outcome(order_id, fn1["id"], {"result": "FAIL"}, FS))
    # round 2 reaches FINAL; failing now must be rejected (limit reached)
    fn2 = run_round()
    res = api.record_fitting_outcome(order_id, fn2["id"], {"result": "FAIL"}, FS)
    validate_error(res, "ERR_REMAKE_LIMIT_REACHED")
    after = get_success_data(api.get_order(order_id, SA))
    assert after["remake_round"] == 2
