"""Handoff age and cold-chain gates, plus validation-priority conflicts at handoff.

Difficulty queue A: state-beats-fiscal and safety-beats-temporal priority pairs,
cold-chain hold-window boundary. Corner queue B: age-check PASS/FAIL boundary,
FAIL blocks handoff.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    assert_age_check,
    make_customer_headers,
    make_picker_headers,
    set_clock,
    create_store,
    create_customer,
    create_picker,
    create_product,
    create_slot,
    place_order,
    get_line_ids,
    claim_order,
    pick_line,
    stage_order,
    capture_order,
    ADMIN,
    OPS,
)

# Claim windows kept clear of the 09:00-11:00 fulfillment window to avoid any
# unrelated picker-window interaction.
EARLY_CLAIM_START = "2026-06-15T07:00:00Z"
EARLY_CLAIM_END = "2026-06-15T07:45:00Z"


def test_handoff_picking_uncaptured_reports_state_error_first(api):
    """PRD §3.7: "Handoff requires the order to be `STAGED` (otherwise `ERR_ORDER_NOT_STAGED`) and its `payment_status` to be `CAPTURED` (otherwise `ERR_PAYMENT_NOT_CAPTURED`)."
    PRD §2.10: "(5) state — the target resource must be in the correct state for the requested transition; ... and (9) fiscal preconditions at capture ... Within an endpoint, a check earlier in this ordering always preempts a later one ... "

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_fiscal_on_handoff
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c9@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": a["id"], "requested_qty": 1}])
    line_id = get_line_ids(order["id"])[0]
    claim_order(order["id"], picker["id"])
    pick_line(line_id, picker["id"], picked_qty=1)  # PICKING (not staged), AUTHORIZED

    resp = api.handoff_order(order["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_STAGED.value, 409)


def test_handoff_staged_uncaptured_reports_fiscal_error(api):
    """PRD §3.7: "Handoff requires the order to be `STAGED` (otherwise `ERR_ORDER_NOT_STAGED`) and its `payment_status` to be `CAPTURED` (otherwise `ERR_PAYMENT_NOT_CAPTURED`)."

    With the state precondition (priority 5) satisfied — the order IS STAGED — the
    later fiscal precondition (priority 9) is the one that surfaces, confirming the
    state check is evaluated and passed before the fiscal one.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_fiscal_on_handoff
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c9b@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": a["id"], "requested_qty": 1}])
    line_id = get_line_ids(order["id"])[0]
    claim_order(order["id"], picker["id"])
    pick_line(line_id, picker["id"], picked_qty=1)
    stage_order(order["id"], picker["id"])  # STAGED but still AUTHORIZED (not captured)

    resp = api.handoff_order(order["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_CAPTURED.value, 409)


def test_handoff_age_required_reported_before_cold_chain(api):
    """PRD §3.7: "In that case the order must have a `PASS` `AgeCheck` on record, or the handoff is refused with `ERR_AGE_VERIFICATION_REQUIRED` ... "
    PRD §2.10: "(7) age-verification safety on handoff; (8) the cold-chain temporal window on handoff ... Within an endpoint, a check earlier in this ordering always preempts a later one ... "

    Design: Difficulty/priority_pair_validation_conflict/ppvc_safety_beats_temporal_on_handoff
    """
    set_clock("2026-06-15T08:00:00Z")
    store = create_store(ebt_enabled=True, cold_chain_hold_minutes=120)
    customer = create_customer(email="c10@x.com")
    picker = create_picker(store["id"])
    wine = create_product(store["id"], sku="WINE", name="Wine", unit_price_cents=1500,
                          age_restricted=True, cold_chain=True)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": wine["id"], "requested_qty": 1}])
    line_id = get_line_ids(order["id"])[0]
    claim_order(order["id"], picker["id"], window_start=EARLY_CLAIM_START,
                window_end=EARLY_CLAIM_END)
    pick_line(line_id, picker["id"], picked_qty=1)
    stage_order(order["id"], picker["id"])  # staged_at = 08:00
    capture_order(order["id"])
    set_clock("2026-06-15T11:00:00Z")  # 180min > 120 -> cold-chain also expired

    resp = api.handoff_order(order["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_AGE_VERIFICATION_REQUIRED.value, 403)


def test_handoff_temporal_error_surfaces_after_age_gate_passes(api):
    """PRD §3.7: "In that case the order must have a `PASS` `AgeCheck` on record, or the handoff is refused with `ERR_AGE_VERIFICATION_REQUIRED` ... "
    PRD §3.7: "A handoff attempted at or after that expiry instant is refused with `ERR_COLD_CHAIN_EXPIRED`."

    With the age safety gate (priority 7) satisfied by a PASS AgeCheck, the
    cold-chain temporal gate (priority 8) is the one that surfaces, confirming the
    safety check is evaluated and passed before the temporal one.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_safety_beats_temporal_on_handoff
    """
    set_clock("2026-06-15T08:00:00Z")
    store = create_store(ebt_enabled=True, cold_chain_hold_minutes=120)
    customer = create_customer(email="c10b@x.com", date_of_birth="1990-01-01")
    picker = create_picker(store["id"])
    wine = create_product(store["id"], sku="WINE", name="Wine", unit_price_cents=1500,
                          age_restricted=True, cold_chain=True)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": wine["id"], "requested_qty": 1}])
    line_id = get_line_ids(order["id"])[0]
    claim_order(order["id"], picker["id"], window_start=EARLY_CLAIM_START,
                window_end=EARLY_CLAIM_END)
    pick_line(line_id, picker["id"], picked_qty=1)
    stage_order(order["id"], picker["id"])  # staged_at = 08:00
    capture_order(order["id"])
    # A PASS age check (adult against slot.window_start 09:00 on 2026-06-15).
    ac = validate_success(
        api.create_age_check(
            {"order_id": order["id"], "verifier_user_id": "ops-1",
             "verified_birth_date": "1990-01-01"}, OPS),
        201,
    )
    assert ac["outcome"] == "PASS"
    set_clock("2026-06-15T11:00:00Z")  # 180min > 120 hold -> cold-chain expired

    resp = api.handoff_order(order["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_COLD_CHAIN_EXPIRED.value, 409)


def test_cold_chain_hold_window_boundary_just_past_expiry(api):
    """PRD §3.7: "Such an order may only be handed off before its staged-hold window expires — that is, while the current clock is strictly earlier than the order's `staged_at` plus the store's `cold_chain_hold_minutes` ... A handoff attempted at or after that expiry instant is refused with `ERR_COLD_CHAIN_EXPIRED`."

    Design: Difficulty/boundary_precision_check/bpc_cold_chain_hold_window_boundary
    """
    set_clock("2026-06-15T08:00:00Z")
    store = create_store(ebt_enabled=True, cold_chain_hold_minutes=120)
    customer = create_customer(email="c12@x.com")
    picker = create_picker(store["id"])
    fish = create_product(store["id"], sku="FISH", name="Fish", unit_price_cents=800,
                          cold_chain=True)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": fish["id"], "requested_qty": 1}])
    line_id = get_line_ids(order["id"])[0]
    claim_order(order["id"], picker["id"], window_start=EARLY_CLAIM_START,
                window_end=EARLY_CLAIM_END)
    pick_line(line_id, picker["id"], picked_qty=1)
    stage_order(order["id"], picker["id"])  # staged_at = 08:00
    capture_order(order["id"])
    set_clock("2026-06-15T10:00:01Z")  # 120m + 1s after stage -> at/after expiry

    resp = api.handoff_order(order["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_COLD_CHAIN_EXPIRED.value, 409)


def test_cold_chain_handoff_allowed_before_expiry(api):
    """PRD §3.7: "Such an order may only be handed off before its staged-hold window expires — that is, while the current clock is strictly earlier than the order's `staged_at` plus the store's `cold_chain_hold_minutes` (the store-configured limit, two hours by default)."

    Design: Difficulty/boundary_precision_check/bpc_cold_chain_hold_window_boundary
    """
    set_clock("2026-06-15T08:00:00Z")
    store = create_store(ebt_enabled=True, cold_chain_hold_minutes=120)
    customer = create_customer(email="c12b@x.com")
    picker = create_picker(store["id"])
    fish = create_product(store["id"], sku="FISH", name="Fish", unit_price_cents=800,
                          cold_chain=True)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": fish["id"], "requested_qty": 1}])
    line_id = get_line_ids(order["id"])[0]
    claim_order(order["id"], picker["id"], window_start=EARLY_CLAIM_START,
                window_end=EARLY_CLAIM_END)
    pick_line(line_id, picker["id"], picked_qty=1)
    stage_order(order["id"], picker["id"])  # staged_at = 08:00
    capture_order(order["id"])
    set_clock("2026-06-15T09:59:59Z")  # strictly before 10:00 expiry

    data = validate_success(api.handoff_order(order["id"], OPS))
    assert data["fulfillment_status"] == "HANDED_OFF"


def test_age_check_pass_at_exact_minimum_age(api):
    """PRD §3.7: "record `PASS` when that age is at least 21 years ... The boundary is inclusive: a birth date that makes the customer exactly 21 years old on the reference date yields `PASS`."

    Design: Corner/calculations/calc_age_check_pass_boundary_inclusive
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="cc9@x.com", date_of_birth="2005-06-15")
    wine = create_product(store["id"], sku="WINE", name="Wine", unit_price_cents=1500,
                          age_restricted=True)
    slot = create_slot(store["id"], capacity=1,
                       window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T11:00:00Z")
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": wine["id"], "requested_qty": 1}])
    resp = api.create_age_check(
        {"order_id": order["id"], "verifier_user_id": "ops-7",
         "verified_birth_date": "2005-06-15"},
        OPS,
    )
    data = validate_success(resp, 201)
    assert_age_check(data)
    assert data["outcome"] == "PASS", "exactly 21 completed years on reference date"


def test_age_check_fail_one_day_short(api):
    """PRD §3.7: "compute the whole completed years from `verified_birth_date` to that reference date, and record `PASS` when that age is at least 21 years ... and `FAIL` otherwise."

    Design: Corner/calculations/calc_age_check_fail_one_day_short
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="cc10@x.com", date_of_birth="2005-06-16")
    wine = create_product(store["id"], sku="WINE", name="Wine", unit_price_cents=1500,
                          age_restricted=True)
    slot = create_slot(store["id"], capacity=1,
                       window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T11:00:00Z")
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": wine["id"], "requested_qty": 1}])
    resp = api.create_age_check(
        {"order_id": order["id"], "verifier_user_id": "ops-7",
         "verified_birth_date": "2005-06-16"},
        OPS,
    )
    data = validate_success(resp, 201)
    assert data["outcome"] == "FAIL", "20 completed years, one day short of 21"


def test_failed_age_check_blocks_handoff(api):
    """PRD §3.7: "and if the order's `AgeCheck` outcome is `FAIL`, the handoff is blocked with `ERR_AGE_VERIFICATION_FAILED`."

    Design: Corner/validations/val_age_verification_failed_blocks_handoff
    """
    set_clock("2026-06-15T09:30:00Z")
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="cc16@x.com", date_of_birth="1990-01-01")
    picker = create_picker(store["id"])
    wine = create_product(store["id"], sku="WINE", name="Wine", unit_price_cents=1500,
                          age_restricted=True)
    slot = create_slot(store["id"], capacity=1,
                       window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T11:00:00Z")
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": wine["id"], "requested_qty": 1}])
    line_id = get_line_ids(order["id"])[0]
    claim_order(order["id"], picker["id"])
    pick_line(line_id, picker["id"], picked_qty=1)
    stage_order(order["id"], picker["id"])
    capture_order(order["id"])
    ac = validate_success(
        api.create_age_check(
            {"order_id": order["id"], "verifier_user_id": "ops-9",
             "verified_birth_date": "2010-01-01"}, OPS),
        201,
    )
    assert ac["outcome"] == "FAIL"

    resp = api.handoff_order(order["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_AGE_VERIFICATION_FAILED.value, 403)
