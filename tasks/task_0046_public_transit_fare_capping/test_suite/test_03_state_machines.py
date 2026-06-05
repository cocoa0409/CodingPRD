"""State machines: invalid transitions, terminal lockdown, initial state, the Tap
branching capture/reject/reverse fork, and the ReducedFareCard verify/expire cycle.

Covers Corner queue (B) state_machines instances and Difficulty queue (A) rule
non_linear_state_machine.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_tap_payload, create_reduced_fare_card_payload, verify_payload,
    TEST_USERS, make_rider_headers,
    set_clock, make_fare_product, register_rider, add_funding_source, load_balance,
    open_week, record_tap, settle, create_captured_tap, setup_funded_rider,
    get_funding_source, get_fare_week, get_tap,
    ApiErrorId,
)


# ─── Corner: invalid transitions / terminal lockdown / initial state ──────

def test_settle_already_captured_tap_invalid_state(api):
    """PRD §3.7: "Settlement is defined only out of `PENDING` (otherwise
    `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/settle_already_captured_tap_returns_invalid_state
    """
    world = setup_funded_rider(balance=1000, product_overrides={"transfer_discount_pct": 0})
    captured = create_captured_tap(world, "2026-06-01T09:00:00Z")
    assert captured["status"] == "CAPTURED"
    res = api.settle_tap(captured["id"], TEST_USERS["payment_gateway_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    fs = get_funding_source(world["rider"]["id"], world["funding_source"]["id"])
    assert fs["prepaid_balance_cents"] == 700, "no second debit"


def test_reverse_pending_tap_invalid_state(api):
    """PRD §3.10: "Reversal is defined only out of `CAPTURED` (otherwise
    `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/reverse_a_pending_tap_returns_invalid_state
    """
    world = setup_funded_rider(balance=0)
    tap = record_tap(world["rider"]["id"], world["week"]["id"],
                     world["funding_source"]["id"], "2026-06-01T09:00:00Z")
    res = api.reverse_tap(tap["id"], TEST_USERS["fare_admin_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_verify_revoked_card_invalid_state(api):
    """PRD §3.4: "Finally, a `FareAdmin` may revoke a card from any of
    `PENDING_VERIFICATION`, `VERIFIED`, or `EXPIRED`, moving it to the terminal
    `REVOKED` status; a revocation request against a card already `REVOKED` is an
    `ERR_INVALID_STATE`."
    PRD §3.4: "Attempting to verify a card that is in neither `PENDING_VERIFICATION`
    nor `EXPIRED` is an `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/verify_revoked_card_returns_invalid_state_terminal_lockdown
    """
    make_fare_product(zone_code="ZONEX")
    set_clock("2026-06-01T12:00:00Z")
    rider = register_rider(home_zone_code="ZONEX", email="rv@x.com")
    card = validate_success(api.create_reduced_fare_card(
        create_reduced_fare_card_payload(rider["id"], program_code="SENIOR"),
        make_rider_headers(rider["id"])), 201)
    validate_success(api.revoke_reduced_fare_card(
        card["id"], TEST_USERS["fare_admin_headers"]), 200)
    res = api.verify_reduced_fare_card(
        card["id"], verify_payload(card["verification_token"]),
        TEST_USERS["fare_admin_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_close_week_with_pending_tap_invalid_state(api):
    """PRD §3.11: "Closing is permitted only when no tap in `PENDING` status
    references the week; any pending tap must first be settled or the close is
    refused."
    PRD §3.11: "A `FareAdmin` seals a fare week by closing it, a transition defined
    only out of `OPEN` (otherwise `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/close_week_with_pending_tap_returns_invalid_state
    """
    world = setup_funded_rider(balance=0)
    record_tap(world["rider"]["id"], world["week"]["id"],
               world["funding_source"]["id"], "2026-06-01T09:00:00Z")
    res = api.close_fare_week(world["week"]["id"], TEST_USERS["fare_admin_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    week = get_fare_week(world["rider"]["id"], world["week"]["id"])
    assert week["status"] == "OPEN"


def test_newly_created_tap_is_pending_unpriced(api):
    """PRD §3.6: "A tap is created in `PENDING` status — the states being `PENDING`,
    `CAPTURED`, `REJECTED`, and `REVERSED` — and is **not** priced at creation;
    pricing happens at settle."

    Design: Corner/state_machines/newly_created_tap_starts_pending
    """
    world = setup_funded_rider(balance=0)
    res = api.create_tap(
        create_tap_payload(world["rider"]["id"], world["week"]["id"],
                           world["funding_source"]["id"], "2026-06-01T09:00:00Z"),
        make_rider_headers(world["rider"]["id"]))
    tap = validate_success(res, 201)
    assert tap["status"] == "PENDING"
    assert tap["charge_cents"] == 0


# ─── Difficulty rule non_linear_state_machine ─────────────────────────────
#   instance: tap_branching_capture_vs_reject_then_reverse

def test_tap_settle_forks_capture_vs_reject_by_funds(api):
    """PRD §3.7: "If instead the computed `charge_cents` exceeds the funding source's
    `prepaid_balance_cents` — insufficient funds — the tap takes the divergent
    branch: its `status` is set to `REJECTED` with `charge_cents` recording the
    amount that could not be settled, and there is no debit to the funding source
    and no change to the fare week's `charged_total_cents` or to any allocation."
    PRD §3.7: "The HTTP response in this case is `ERR_INSUFFICIENT_FUNDS` (HTTP 402),
    but the tap is nonetheless persisted as `REJECTED` and is discoverable by
    fetching it afterward".

    Design: Difficulty/non_linear_state_machine/tap_branching_capture_vs_reject_then_reverse
    """
    # transfer_discount_pct 0 so the second ride is priced at full fare (no free
    # transfer), letting the funds precondition drive the reject branch.
    world = setup_funded_rider(balance=300,
                               product_overrides={"transfer_discount_pct": 0})
    # T1 captures, drains the balance to 0.
    t1 = record_tap(world["rider"]["id"], world["week"]["id"],
                    world["funding_source"]["id"], "2026-06-01T09:00:00Z")
    captured = settle(t1["id"])
    assert captured["status"] == "CAPTURED"
    # T2 rejects: 300 > balance 0.
    t2 = record_tap(world["rider"]["id"], world["week"]["id"],
                    world["funding_source"]["id"], "2026-06-01T10:00:00Z")
    res = api.settle_tap(t2["id"], TEST_USERS["payment_gateway_headers"])
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value, expected_status=402)
    persisted = get_tap(world["rider"]["id"], t2["id"])
    assert persisted["status"] == "REJECTED", "rejection is recorded, not discarded"
    week = get_fare_week(world["rider"]["id"], world["week"]["id"])
    assert week["charged_total_cents"] == 300, "rejected tap did not accrue"


def test_captured_tap_can_reverse_and_restores_ledger(api):
    """PRD §3.10: "On reversal the system credits the funding source's
    `prepaid_balance_cents` by the tap's `charge_cents`, decrements the fare week's
    `charged_total_cents` by that same `charge_cents` so the weekly reconciliation
    invariant holds ... The tap moves to the terminal `REVERSED` status".

    Design: Difficulty/non_linear_state_machine/tap_branching_capture_vs_reject_then_reverse
    """
    world = setup_funded_rider(balance=300)
    t1 = record_tap(world["rider"]["id"], world["week"]["id"],
                    world["funding_source"]["id"], "2026-06-01T09:00:00Z")
    captured = settle(t1["id"])
    assert captured["status"] == "CAPTURED"
    res = api.reverse_tap(t1["id"], TEST_USERS["fare_admin_headers"])
    reversed_tap = validate_success(res, 200)
    assert reversed_tap["status"] == "REVERSED"
    fs = get_funding_source(world["rider"]["id"], world["funding_source"]["id"])
    assert fs["prepaid_balance_cents"] == 300, "300 credited back"
    week = get_fare_week(world["rider"]["id"], world["week"]["id"])
    assert week["charged_total_cents"] == 0, "300 decremented"


# ─── Difficulty rule non_linear_state_machine ─────────────────────────────
#   instance: reduced_fare_card_cyclic_verified_expired_verified

def test_verified_card_refresh_expiry_moves_to_expired(api):
    """PRD §3.4: "it can also be forced by a `FareAdmin` through a refresh-expiry
    capability that re-evaluates a `VERIFIED` card against the current clock and
    moves it to `EXPIRED` exactly when `expires_on` is strictly before the current
    fare day."

    Design: Difficulty/non_linear_state_machine/reduced_fare_card_cyclic_verified_expired_verified
    """
    make_fare_product(zone_code="ZONEX")
    set_clock("2026-06-01T12:00:00Z")
    rider = register_rider(home_zone_code="ZONEX", email="r6@x.com")
    card = validate_success(api.create_reduced_fare_card(
        create_reduced_fare_card_payload(rider["id"], program_code="DISABILITY",
                                         expires_on="2026-06-10"),
        make_rider_headers(rider["id"])), 201)
    validate_success(api.verify_reduced_fare_card(
        card["id"], verify_payload(card["verification_token"]),
        TEST_USERS["fare_admin_headers"]), 200)
    set_clock("2026-06-15T12:00:00Z")
    res = api.refresh_expiry_reduced_fare_card(card["id"], TEST_USERS["fare_admin_headers"])
    refreshed = validate_success(res, 200)
    assert refreshed["status"] == "EXPIRED"


def test_expired_card_can_be_reverified_after_renewal(api):
    """PRD §3.4: "a `FareAdmin` may extend a card's `expires_on` (a renewal that
    updates `expires_on` and increments the card's `version`), after which the card
    may be verified again, closing the loop `VERIFIED → EXPIRED → VERIFIED`."
    PRD §3.4: "Verification is also defined out of the `EXPIRED` state under the same
    two preconditions — matching token and `expires_on` on or after the current fare
    day — so an expired card can be brought back to `VERIFIED`."

    Design: Difficulty/non_linear_state_machine/reduced_fare_card_cyclic_verified_expired_verified
    """
    make_fare_product(zone_code="ZONEX")
    set_clock("2026-06-01T12:00:00Z")
    rider = register_rider(home_zone_code="ZONEX", email="r6b@x.com")
    card = validate_success(api.create_reduced_fare_card(
        create_reduced_fare_card_payload(rider["id"], program_code="DISABILITY",
                                         expires_on="2026-06-10"),
        make_rider_headers(rider["id"])), 201)
    token = card["verification_token"]
    validate_success(api.verify_reduced_fare_card(
        card["id"], verify_payload(token), TEST_USERS["fare_admin_headers"]), 200)
    set_clock("2026-06-15T12:00:00Z")
    expired = validate_success(api.refresh_expiry_reduced_fare_card(
        card["id"], TEST_USERS["fare_admin_headers"]), 200)
    assert expired["status"] == "EXPIRED"
    validate_success(api.patch_reduced_fare_card(
        card["id"], {"expires_on": "2027-01-01"}, TEST_USERS["fare_admin_headers"]), 200)
    res = api.verify_reduced_fare_card(
        card["id"], verify_payload(token), TEST_USERS["fare_admin_headers"])
    re_verified = validate_success(res, 200)
    assert re_verified["status"] == "VERIFIED", "cycle VERIFIED -> EXPIRED -> VERIFIED closed"
