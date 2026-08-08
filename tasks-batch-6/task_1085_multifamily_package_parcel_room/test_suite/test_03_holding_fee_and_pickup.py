"""Holding-fee accrual (provisional/final, cap, round-per-day), pickup, and cold-chain.

Queue A (Difficulty): holding_fee_provisional_vs_final, holding_fee_cap_min_max_nonlinear,
holding_fee_round_per_day_then_sum, pickup_state_beats_invalid_code,
cold_chain_expired_strictly_after_deadline.
Queue B (Corner): provisional_fee_zero_within_grace_window, error_invalid_pickup_code_returns_403,
resident_picks_up_own_package_succeeds, pickup_from_logged_returns_invalid_state,
pickup_twice_terminal_lockdown_returns_invalid_state.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    pickup_payload, notify_payload,
    WRONG_PICKUP_CODE,
    TEST_USERS, make_resident_headers,
    setup_notified_locker_package,
    advance_clock, get_package, list_package_charges, get_property,
    log_package, make_property, make_carrier, make_resident,
)
from test_helpers import api_client

PM = TEST_USERS["pm_headers"]
CONCIERGE = TEST_USERS["concierge_headers"]


# ─── holding_fee_provisional_vs_final ─────────────────────────────────────────
def test_provisional_and_final_fee_diverge(api):
    """PRD §3.5: "The **provisional** variant (surfaced live as `provisional_fee_cents` while
    the package is still `AWAITING_PICKUP`) uses the current clock as its end and therefore
    grows as time passes; the **final** variant (pinned into `final_fee_cents`) freezes its end
    at the pickup instant or at the return-initiate instant and never re-grows thereafter."

    Design: Difficulty/dual_variant_calc/holding_fee_provisional_vs_final
    """
    ctx = setup_notified_locker_package(resident_overrides={"loyalty_discount_pct": 0.10})
    advance_clock("2026-05-06T00:00:00Z")
    prov = get_package(ctx["package"]["id"])["provisional_fee_cents"]
    assert prov == 300, f"expected provisional 300 at 5-day/2-chargeable, got {prov}"
    advance_clock("2026-05-09T00:00:00Z")
    picked = validate_success(
        api.pickup_package(ctx["package"]["id"], pickup_payload(ctx["pickup_code"]), CONCIERGE), 200)
    assert picked["final_fee_cents"] == 750, f"expected final 750, got {picked['final_fee_cents']}"


def test_collected_charge_is_net_after_loyalty_discount(api):
    """PRD §3.4: "a `StorageCharge` of type `HOLDING_FEE` is created already `COLLECTED`, with
    `amount_cents` equal to the net amount after the resident's loyalty discount".

    Design: Difficulty/dual_variant_calc/holding_fee_provisional_vs_final
    """
    ctx = setup_notified_locker_package(resident_overrides={"loyalty_discount_pct": 0.10})
    advance_clock("2026-05-09T00:00:00Z")
    picked = validate_success(
        api.pickup_package(ctx["package"]["id"], pickup_payload(ctx["pickup_code"]), CONCIERGE), 200)
    assert picked["status"] == "PICKED_UP"
    charges = list_package_charges(ctx["package"]["id"])
    collected = [c for c in charges if c["status"] == "COLLECTED"]
    assert len(collected) == 1, f"expected one COLLECTED charge, got {charges}"
    assert collected[0]["amount_cents"] == 675, "net = round_half_up(750 * (1 - 0.10)) == 675"


# ─── holding_fee_cap_min_max_nonlinear ────────────────────────────────────────
def test_cold_oversize_fee_clamped_to_cap_at_return_initiate(api):
    """PRD §3.5: "If the package `is_oversize`, the property's `oversize_surcharge_cents` is
    added once to the gross as a flat surcharge. The gross is then capped: the final gross is
    the smaller of the computed gross and the property's `holding_fee_cap_cents`."

    Design: Difficulty/combinatorial_formula/holding_fee_cap_min_max_nonlinear
    """
    ctx = setup_notified_locker_package(
        resident_overrides={"loyalty_discount_pct": 0.0}, bank_storage="REFRIGERATED",
        locker_size="OVERSIZE", pkg_size="OVERSIZE", pkg_storage_type="COLD")
    advance_clock("2026-05-20T00:00:00Z")
    initiated = validate_success(api.return_initiate(ctx["package"]["id"], CONCIERGE), 200)
    assert initiated["status"] == "RETURN_INITIATED"
    assert initiated["final_fee_cents"] == 5000, (
        f"raw 16*300+500=5300 clamped to cap 5000, got {initiated['final_fee_cents']}")


def test_capped_fee_posts_outstanding_charge_at_cap(api):
    """PRD §3.7: "when that fee is greater than zero it creates a `StorageCharge` of type
    `HOLDING_FEE` in `OUTSTANDING` status carrying the net amount, thereby increasing the
    property's `uncollected_fee_cents`."

    Design: Difficulty/combinatorial_formula/holding_fee_cap_min_max_nonlinear
    """
    ctx = setup_notified_locker_package(
        resident_overrides={"loyalty_discount_pct": 0.0}, bank_storage="REFRIGERATED",
        locker_size="OVERSIZE", pkg_size="OVERSIZE", pkg_storage_type="COLD")
    advance_clock("2026-05-20T00:00:00Z")
    validate_success(api.return_initiate(ctx["package"]["id"], CONCIERGE), 200)
    charges = list_package_charges(ctx["package"]["id"])
    outstanding = [c for c in charges if c["status"] == "OUTSTANDING"]
    assert len(outstanding) == 1 and outstanding[0]["amount_cents"] == 5000
    assert get_property(ctx["property"]["id"])["uncollected_fee_cents"] == 5000


# ─── holding_fee_round_per_day_then_sum ───────────────────────────────────────
def test_fee_rounds_per_day_then_sums(api):
    """PRD §3.5: "The gross fee is built by rounding each individual day's rate to whole cents
    with round-half-up and then summing those rounded per-day amounts across all chargeable
    days — the rounding happens per day, before summation, never once on the total."

    Design: Difficulty/combinatorial_formula/holding_fee_round_per_day_then_sum
    """
    ctx = setup_notified_locker_package(
        prop_overrides={"holding_fee_daily_cents": 101, "perishable_fee_multiplier": 1.5},
        resident_overrides={"loyalty_discount_pct": 0.0}, bank_storage="REFRIGERATED",
        locker_size="MEDIUM", pkg_size="MEDIUM", pkg_storage_type="COLD")
    advance_clock("2026-05-08T00:00:00Z")
    picked = validate_success(
        api.pickup_package(ctx["package"]["id"], pickup_payload(ctx["pickup_code"]), CONCIERGE), 200)
    assert picked["final_fee_cents"] == 608, (
        f"per-day 151.5->152 x 4 chargeable = 608 (not 606 sum-then-round), "
        f"got {picked['final_fee_cents']}")


def test_round_per_day_charge_amount_matches(api):
    """PRD §3.5: "The gross fee is built by rounding each individual day's rate to whole cents
    with round-half-up and then summing those rounded per-day amounts across all chargeable
    days — the rounding happens per day, before summation, never once on the total."

    Design: Difficulty/combinatorial_formula/holding_fee_round_per_day_then_sum
    """
    ctx = setup_notified_locker_package(
        prop_overrides={"holding_fee_daily_cents": 101, "perishable_fee_multiplier": 1.5},
        resident_overrides={"loyalty_discount_pct": 0.0}, bank_storage="REFRIGERATED",
        locker_size="MEDIUM", pkg_size="MEDIUM", pkg_storage_type="COLD")
    advance_clock("2026-05-08T00:00:00Z")
    validate_success(
        api.pickup_package(ctx["package"]["id"], pickup_payload(ctx["pickup_code"]), CONCIERGE), 200)
    charges = list_package_charges(ctx["package"]["id"])
    collected = [c for c in charges if c["status"] == "COLLECTED"]
    assert len(collected) == 1 and collected[0]["amount_cents"] == 608


# ─── pickup_state_beats_invalid_code (priority 4 outranks priority 10) ────────
def test_pickup_of_return_initiated_with_wrong_code_reports_invalid_state(api):
    """PRD §2.10: "(4) target resource in a state permitting the operation (`ERR_INVALID_STATE`,
    409);"
    PRD §2.10: "(10) pickup-code match (`ERR_INVALID_PICKUP_CODE`, 403);"
    PRD §2.10: "Where a lower-numbered check would fire, it takes precedence over any
    higher-numbered one on the same request."

    Design: Difficulty/priority_pair_validation_conflict/pickup_state_beats_invalid_code
    """
    ctx = setup_notified_locker_package()
    validate_success(api.return_initiate(ctx["package"]["id"], CONCIERGE), 200)
    res = api.pickup_package(ctx["package"]["id"], pickup_payload(WRONG_PICKUP_CODE), CONCIERGE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_pickup_of_picked_up_with_wrong_code_reports_invalid_state(api):
    """PRD §2.10: "(4) target resource in a state permitting the operation (`ERR_INVALID_STATE`,
    409);"
    PRD §2.10: "(10) pickup-code match (`ERR_INVALID_PICKUP_CODE`, 403);"
    PRD §2.10: "Where a lower-numbered check would fire, it takes precedence over any
    higher-numbered one on the same request."

    Design: Difficulty/priority_pair_validation_conflict/pickup_state_beats_invalid_code
    """
    ctx = setup_notified_locker_package()
    validate_success(
        api.pickup_package(ctx["package"]["id"], pickup_payload(ctx["pickup_code"]), CONCIERGE), 200)
    res = api.pickup_package(ctx["package"]["id"], pickup_payload(WRONG_PICKUP_CODE), CONCIERGE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── cold_chain_expired_strictly_after_deadline ───────────────────────────────
def test_perishable_pickup_strictly_after_deadline_expired(api):
    """PRD §3.4: "for a `PERISHABLE` package the current clock must not be strictly after its
    `cold_chain_deadline_at`, otherwise the pickup is refused with `ERR_COLD_CHAIN_EXPIRED`
    (a pickup exactly at the deadline remains allowed)."

    Design: Difficulty/boundary_precision_check/cold_chain_expired_strictly_after_deadline
    """
    ctx = setup_notified_locker_package(
        prop_overrides={"perishable_hold_hours": 48}, bank_storage="REFRIGERATED",
        locker_size="MEDIUM", pkg_size="MEDIUM", pkg_storage_type="PERISHABLE")
    advance_clock("2026-05-03T00:00:01Z")
    res = api.pickup_package(ctx["package"]["id"], pickup_payload(ctx["pickup_code"]), CONCIERGE)
    validate_error(res, "ERR_COLD_CHAIN_EXPIRED", expected_status=409)


def test_perishable_pickup_exactly_at_deadline_allowed(api):
    """PRD §3.4: "for a `PERISHABLE` package the current clock must not be strictly after its
    `cold_chain_deadline_at`, otherwise the pickup is refused with `ERR_COLD_CHAIN_EXPIRED`
    (a pickup exactly at the deadline remains allowed)."

    Design: Difficulty/boundary_precision_check/cold_chain_expired_strictly_after_deadline
    """
    ctx = setup_notified_locker_package(
        prop_overrides={"perishable_hold_hours": 48}, bank_storage="REFRIGERATED",
        locker_size="MEDIUM", pkg_size="MEDIUM", pkg_storage_type="PERISHABLE")
    advance_clock("2026-05-03T00:00:00Z")
    picked = validate_success(
        api.pickup_package(ctx["package"]["id"], pickup_payload(ctx["pickup_code"]), CONCIERGE), 200)
    assert picked["status"] == "PICKED_UP"


# ─── provisional_fee_zero_within_grace_window (Corner) ────────────────────────
def test_provisional_fee_zero_at_grace_boundary(api):
    """PRD §3.5: "The number of chargeable days is the elapsed days minus the property's
    `holding_fee_grace_days`, but never less than zero."

    Design: Corner/calculations/provisional_fee_zero_within_grace_window
    """
    ctx = setup_notified_locker_package()  # default grace 3
    advance_clock("2026-05-04T00:00:00Z")  # 3 elapsed days -> chargeable max(0, 3-3) == 0
    prov = get_package(ctx["package"]["id"])["provisional_fee_cents"]
    assert prov == 0, f"expected provisional 0 at grace boundary, got {prov}"


# ─── error_invalid_pickup_code_returns_403 (Corner) ───────────────────────────
def test_wrong_pickup_code_rejected_and_state_unchanged(api):
    """PRD §3.4: "The supplied code must equal the package's `pickup_code`; a mismatch is
    rejected with `ERR_INVALID_PICKUP_CODE`."

    Design: Corner/errors/error_invalid_pickup_code_returns_403
    """
    ctx = setup_notified_locker_package()
    res = api.pickup_package(ctx["package"]["id"], pickup_payload("999999"), CONCIERGE)
    validate_error(res, "ERR_INVALID_PICKUP_CODE", expected_status=403)
    assert get_package(ctx["package"]["id"])["status"] == "AWAITING_PICKUP"


# ─── resident_picks_up_own_package_succeeds (Corner) ──────────────────────────
def test_resident_picks_up_own_package(api):
    """PRD §3.4: "A `Resident` picking up their own package, or `ConciergeStaff` acting on the
    resident's behalf, presents the `pickup_code`. When the actor is a resident, the package's
    `resident_id` must equal the resident's `X-User-ID`."

    Design: Corner/rbac/resident_picks_up_own_package_succeeds
    """
    ctx = setup_notified_locker_package()
    headers = make_resident_headers(ctx["resident"]["id"])
    picked = validate_success(
        api.pickup_package(ctx["package"]["id"], pickup_payload(ctx["pickup_code"]), headers), 200)
    assert picked["status"] == "PICKED_UP"


# ─── pickup_from_logged_returns_invalid_state (Corner) ────────────────────────
def test_pickup_of_logged_package_rejected(api):
    """PRD §3.4: "The package must be in `AWAITING_PICKUP`".
    PRD §3.7: "A package in any state other than the one each transition expects yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pickup_from_logged_returns_invalid_state
    """
    prop = make_property(name="IS Court")
    carrier = make_carrier(prop["id"])
    resident = make_resident(prop["id"])
    pkg = log_package(prop["id"], resident["id"], carrier["id"])  # LOGGED, never notified
    res = api.pickup_package(pkg["id"], pickup_payload("ABC123"), CONCIERGE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── pickup_twice_terminal_lockdown_returns_invalid_state (Corner) ────────────
def test_second_pickup_on_picked_up_package_rejected(api):
    """PRD §3.4: "The package must be in `AWAITING_PICKUP`".
    PRD §3.7: "A package in any state other than the one each transition expects yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pickup_twice_terminal_lockdown_returns_invalid_state
    """
    ctx = setup_notified_locker_package()
    validate_success(
        api.pickup_package(ctx["package"]["id"], pickup_payload(ctx["pickup_code"]), CONCIERGE), 200)
    res = api.pickup_package(ctx["package"]["id"], pickup_payload(ctx["pickup_code"]), CONCIERGE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
