"""Promotion lifecycle: transitions, the ACTIVE<->PAUSED cycle, archive cascade,
window and blackout temporal semantics, and the expiry sweep.

Translates queue A (Difficulty): non_linear_state_machine (promotion cycle),
transitive_cascade (archive disables coupons), resource_temporal_overlap (blackout
and exclusive-end window). Translates queue B (Corner): state_machines (promotion
invalid transitions, initial state, archive-with-reservations, coupon auto-exhaust)
and cross_cutting (scheduled expiry sweep).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock,
    advance_clock,
    create_promotion,
    create_coupon,
    activate_promotion,
    pause_promotion,
    create_active_promotion,
    create_customer,
    setup_priced_cart_with_coupon,
    setup_locked_cart_with_coupon,
    apply,
    reprice,
    lock,
    get_promotion,
)
from test_helpers.factories import create_promotion_payload, apply_coupon_payload, create_line_payload
from test_helpers.api_client import api_client
from test_helpers.test_users import make_shopper_headers

ADMIN = TEST_USERS["merchant_admin_headers"]


# ───────────────────────────── promotion initial / invalid transitions ─────
def test_promotion_initial_state_is_draft(api):
    """PRD §3.2: "A `MerchantAdmin` authors a `Promotion` in `DRAFT`."
    PRD §3.2: "Every promotion exposes its `status`, which starts at `DRAFT`."

    Design: Corner/state_machines/promotion_initial_state_is_draft
    """
    promo = create_promotion("PERCENT_OFF", name="InitP", percent_off=0.10)
    assert promo["status"] == "DRAFT"


def test_activate_from_archived_returns_invalid_state(api):
    """PRD §3.3: "A transition requested from a state that does not admit it is
    rejected with `ERR_INVALID_STATE`."
    PRD §3.3: "Archival is the single terminal state and may be reached from
    `DRAFT`, `PAUSED`, or `EXPIRED`."

    Design: Corner/state_machines/activate_from_archived_returns_invalid_state
    """
    promo = create_promotion("PERCENT_OFF", name="ArchP", percent_off=0.10)
    get_success_data(api.archive_promotion(promo["id"], ADMIN))
    res = api.activate_promotion(promo["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_pause_from_draft_returns_invalid_state(api):
    """PRD §3.3: "An active promotion can be paused and resumed in a revision
    loop. Pausing moves `status` from `ACTIVE` to `PAUSED` with no precondition"
    PRD §3.3: "A transition requested from a state that does not admit it is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pause_from_draft_returns_invalid_state
    """
    promo = create_promotion("PERCENT_OFF", name="DraftPause", percent_off=0.10)
    res = api.pause_promotion(promo["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ───────────────────────── non_linear_state_machine: ACTIVE<->PAUSED cycle ──
def test_promotion_active_pause_cycle_returns_to_active(api):
    """PRD §3.3: "An active promotion can be paused and resumed in a revision
    loop. Pausing moves `status` from `ACTIVE` to `PAUSED` with no precondition"
    PRD §3.3: "Re-activating moves `status` from `PAUSED` back to `ACTIVE`,
    permitted only while the clock is still before `active_until`"

    Design: Difficulty/non_linear_state_machine/nlsm_promotion_active_pause_cycle
    """
    set_clock("2026-06-15T00:00:00Z")
    promo = create_promotion("PERCENT_OFF", name="CYC", percent_off=0.10)
    promo = activate_promotion(promo["id"])
    assert promo["status"] == "ACTIVE"
    paused = pause_promotion(promo["id"])
    assert paused["status"] == "PAUSED"
    reactivated = validate_success(api.activate_promotion(promo["id"], ADMIN), 200)
    assert reactivated["status"] == "ACTIVE", "second activate returns to a prior state"


def test_promotion_pause_resume_status_transitions(api):
    """PRD §3.3: "Pausing moves `status` from `ACTIVE` to `PAUSED` with no
    precondition; while `PAUSED`, any new application that references the
    promotion is rejected with `ERR_PROMO_NOT_REDEEMABLE`, though redemptions
    already reserved are left untouched."

    Design: Difficulty/non_linear_state_machine/nlsm_promotion_active_pause_cycle
    """
    set_clock("2026-06-15T00:00:00Z")
    promo, _ = create_active_promotion("PERCENT_OFF", name="CYC2", percent_off=0.10)
    paused = validate_success(api.pause_promotion(promo["id"], ADMIN), 200)
    assert paused["status"] == "PAUSED"


# ─────────────────────── transitive_cascade: archive disables child coupons ─
def test_archive_paused_promotion_disables_child_coupons(api):
    """PRD §3.3: "Archiving moves `status` to `ARCHIVED` and cascades down to set
    every child coupon to `DISABLED`."
    PRD §3.4: "a promotion's archival also drives all its coupons to `DISABLED`
    by the same effect."

    Design: Difficulty/transitive_cascade/tc_archive_disables_coupons_depth2
    """
    set_clock("2026-06-15T00:00:00Z")
    promo = create_promotion("PERCENT_OFF", name="ARC", percent_off=0.10)
    k1 = create_coupon(promo["id"], code="K1", use_mode="MULTI_USE", max_total_redemptions=10)
    k2 = create_coupon(promo["id"], code="K2", use_mode="MULTI_USE", max_total_redemptions=10)
    activate_promotion(promo["id"])
    pause_promotion(promo["id"])

    archived = validate_success(api.archive_promotion(promo["id"], ADMIN), 200)
    assert archived["status"] == "ARCHIVED"

    k1_after = validate_success(api.get_coupon(promo["id"], k1["id"], ADMIN), 200)
    k2_after = validate_success(api.get_coupon(promo["id"], k2["id"], ADMIN), 200)
    assert k1_after["status"] == "DISABLED"
    assert k2_after["status"] == "DISABLED"


def test_archive_draft_promotion_disables_child_coupons(api):
    """PRD §3.3: "Archiving moves `status` to `ARCHIVED` and cascades down to set
    every child coupon to `DISABLED`."

    Design: Difficulty/transitive_cascade/tc_archive_disables_coupons_depth2
    """
    promo = create_promotion("PERCENT_OFF", name="ARCd", percent_off=0.10)
    k1 = create_coupon(promo["id"], code="DK1", use_mode="MULTI_USE", max_total_redemptions=10)
    archived = validate_success(api.archive_promotion(promo["id"], ADMIN), 200)
    assert archived["status"] == "ARCHIVED"
    k1_after = validate_success(api.get_coupon(promo["id"], k1["id"], ADMIN), 200)
    assert k1_after["status"] == "DISABLED"


def test_archive_paused_with_reservations_rejected(api):
    """PRD §3.3: "From `PAUSED`, archival additionally requires that no `RESERVED`
    redemption is outstanding beneath the promotion; an attempt while
    reservations are live is rejected with `ERR_PROMO_HAS_RESERVATIONS`."

    Design: Corner/state_machines/archive_paused_with_reservations_rejected
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="SM8")
    promo, _ = create_active_promotion("PERCENT_OFF", name="RES", percent_off=0.10,
                                       coupon_code="RESK", coupon_use_mode="MULTI_USE",
                                       coupon_overrides={"max_total_redemptions": 10})
    setup_locked_cart_with_coupon(cust["id"], "RESK", [("A", 2000, 1)])
    pause_promotion(promo["id"])
    res = api.archive_promotion(promo["id"], ADMIN)
    validate_error(res, "ERR_PROMO_HAS_RESERVATIONS", expected_status=409)


# ─────────────── resource_temporal_overlap: blackout half-open interval ─────
def test_blackout_window_half_open_suppresses_inside(api):
    """PRD §3.3: "While the clock falls within any blackout interval of a
    promotion — at or after `starts_at` and before `ends_at` — that promotion is
    not redeemable even if its main window is open and its status is `ACTIVE`."
    PRD §3.8: "The promotion must be redeemable — `ACTIVE`, with the clock inside
    its window and outside every blackout, and the coupon `ENABLED` — else
    `ERR_PROMO_NOT_REDEEMABLE`."

    Design: Difficulty/resource_temporal_overlap/rto_blackout_window_half_open_inside
    """
    set_clock("2026-06-05T00:00:00Z")
    cust = create_customer(display_name="R1")
    promo = create_promotion("PERCENT_OFF", name="BLK", percent_off=0.10)
    get_success_data(api_client.create_blackout(promo["id"],
                     {"starts_at": "2026-06-10T00:00:00Z", "ends_at": "2026-06-20T00:00:00Z",
                      "reason": "inventory freeze"}, ADMIN))
    create_coupon(promo["id"], code="BLKC", use_mode="MULTI_USE", max_total_redemptions=10)
    activate_promotion(promo["id"])
    cart = get_success_data(api_client.create_cart({"customer_id": cust["id"]},
                            make_shopper_headers(cust["id"])))
    get_success_data(api_client.add_line(cart["id"], create_line_payload("A", 2000, 1),
                     make_shopper_headers(cust["id"])))
    set_clock("2026-06-15T00:00:00Z")  # inside the half-open blackout

    res = api_client.apply_coupon(cart["id"], apply_coupon_payload("BLKC"),
                                  make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_PROMO_NOT_REDEEMABLE", expected_status=409)


def test_blackout_end_is_exclusive_redeemable_at_ends_at(api):
    """PRD §3.3: "While the clock falls within any blackout interval of a
    promotion — at or after `starts_at` and before `ends_at` — that promotion is
    not redeemable even if its main window is open and its status is `ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/rto_blackout_window_half_open_inside
    """
    set_clock("2026-06-05T00:00:00Z")
    cust = create_customer(display_name="R1b")
    promo = create_promotion("PERCENT_OFF", name="BLKb", percent_off=0.10)
    get_success_data(api_client.create_blackout(promo["id"],
                     {"starts_at": "2026-06-10T00:00:00Z", "ends_at": "2026-06-20T00:00:00Z",
                      "reason": "freeze"}, ADMIN))
    create_coupon(promo["id"], code="BLKCB", use_mode="MULTI_USE", max_total_redemptions=10)
    activate_promotion(promo["id"])
    cart = get_success_data(api_client.create_cart({"customer_id": cust["id"]},
                            make_shopper_headers(cust["id"])))
    get_success_data(api_client.add_line(cart["id"], create_line_payload("A", 2000, 1),
                     make_shopper_headers(cust["id"])))
    set_clock("2026-06-20T00:00:00Z")  # exactly ends_at -> blackout end is exclusive -> not inside

    res = api_client.apply_coupon(cart["id"], apply_coupon_payload("BLKCB"),
                                  make_shopper_headers(cust["id"]))
    app = validate_success(res, 201)
    assert app["status"] == "APPLIED", "clock == ends_at is outside the half-open blackout"


def test_active_window_exclusive_end_expires(api):
    """PRD §3.3: "When the clock reaches or passes `active_until`, the expiry
    sweep transitions a promotion from either `ACTIVE` or `PAUSED` to `EXPIRED`,
    after which it is no longer redeemable."
    PRD §3.2: "Once `ACTIVE`, the promotion is eligible to be applied whenever the
    clock falls within the half-open window from `active_from` up to but not
    including `active_until`."

    Design: Difficulty/resource_temporal_overlap/rto_active_window_exclusive_end_expires
    """
    set_clock("2026-06-05T00:00:00Z")
    cust = create_customer(display_name="R2")
    promo = create_promotion("PERCENT_OFF", name="EXPW", percent_off=0.10,
                             active_from="2026-06-01T00:00:00Z",
                             active_until="2026-06-20T00:00:00Z")
    create_coupon(promo["id"], code="EXPC", use_mode="MULTI_USE", max_total_redemptions=10)
    activate_promotion(promo["id"])
    cart = get_success_data(api_client.create_cart({"customer_id": cust["id"]},
                            make_shopper_headers(cust["id"])))
    get_success_data(api_client.add_line(cart["id"], create_line_payload("A", 2000, 1),
                     make_shopper_headers(cust["id"])))
    set_clock("2026-06-20T00:00:00Z")  # exactly active_until -> expiry sweep

    promo_after = get_promotion(promo["id"])
    assert promo_after["status"] == "EXPIRED"
    res = api_client.apply_coupon(cart["id"], apply_coupon_payload("EXPC"),
                                  make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_PROMO_NOT_REDEEMABLE", expected_status=409)


def test_active_window_inclusive_start_redeemable_at_active_from(api):
    """PRD §3.2: "Once `ACTIVE`, the promotion is eligible to be applied whenever
    the clock falls within the half-open window from `active_from` up to but not
    including `active_until`."

    Design: Difficulty/resource_temporal_overlap/rto_active_window_exclusive_end_expires
    """
    set_clock("2026-06-01T00:00:00Z")  # exactly active_from (inclusive)
    cust = create_customer(display_name="R2b")
    promo = create_promotion("PERCENT_OFF", name="EXPWb", percent_off=0.10,
                             active_from="2026-06-01T00:00:00Z",
                             active_until="2026-06-20T00:00:00Z")
    create_coupon(promo["id"], code="EXPCB", use_mode="MULTI_USE", max_total_redemptions=10)
    activate_promotion(promo["id"])
    cart = get_success_data(api_client.create_cart({"customer_id": cust["id"]},
                            make_shopper_headers(cust["id"])))
    get_success_data(api_client.add_line(cart["id"], create_line_payload("A", 2000, 1),
                     make_shopper_headers(cust["id"])))
    res = api_client.apply_coupon(cart["id"], apply_coupon_payload("EXPCB"),
                                  make_shopper_headers(cust["id"]))
    app = validate_success(res, 201)
    assert app["status"] == "APPLIED", "clock == active_from is inside the window (inclusive start)"


# ─────────────────── scheduled expiry sweep on clock advance ────────────────
def test_scheduled_expiry_sweep_on_clock_advance(api):
    """PRD §2.8: "Either operation runs an expiry sweep: any promotion in
    `ACTIVE` or `PAUSED` whose window has closed — that is, the clock has reached
    or passed its `active_until` — is automatically transitioned to `EXPIRED`."

    Design: Corner/cross_cutting_complexity_layers/scheduled_expiry_sweep_on_clock_advance
    """
    set_clock("2026-06-05T00:00:00Z")
    promo = create_promotion("PERCENT_OFF", name="SCH", percent_off=0.10,
                             active_from="2026-06-01T00:00:00Z",
                             active_until="2026-06-10T00:00:00Z")
    activate_promotion(promo["id"])
    advance_clock(864000)  # 10 days -> past 2026-06-10
    promo_after = get_promotion(promo["id"])
    assert promo_after["status"] == "EXPIRED"
