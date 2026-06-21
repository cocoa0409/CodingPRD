"""Reservation/unit lifecycle, parallel dimensions, cross-entity gating, and the
multi-link cascades that fire from check-in, settle, and cancel.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, TEST_USERS, make_renter_headers,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["shop_admin_headers"]
AGENT = TEST_USERS["rental_agent_headers"]


# ===========================================================================
# Queue A — non_linear_state_machine
# ===========================================================================

def test_confirm_advances_parallel_lifecycle_and_payment_dimensions(api):
    """PRD §3.5: "When a renter is satisfied with the quote, confirming the
    reservation advances it from `QUOTED` to `CONFIRMED`."
    PRD §3.5: "On success, the reservation snapshots `deposit_cents` from its rate
    card, its `payment_status` moves from `UNPAID` to `DEPOSIT_HELD`, and a ledger
    entry of type `DEPOSIT_HOLD` is written for the positive deposit amount."
    PRD §3.5: "The payment dimension advances independently of the lifecycle
    dimension: `payment_status` is its own parallel state machine whose start is
    `UNPAID` and whose terminal states are `SETTLED` and `REFUNDED`."

    Design: Difficulty/non_linear_state_machine/reservation_parallel_lifecycle_and_payment_dimensions
    """
    fx.set_clock("2026-05-03T08:00:00Z")
    s = fx.setup_catalog(category="SUP", asset_tag="SUP-3",
                         customer_overrides={"email": "ana@x.com", "skill_level": "EXPERT"},
                         customer_actor="RENTER")
    cust_id = s["customer"]["id"]
    res = fx.create_reservation(cust_id, s["gear_unit"]["id"], s["gear_unit"]["version"],
                                "2026-05-03T08:00:00Z", "2026-05-03T10:00:00Z", actor="RENTER")
    confirmed = validate_success(
        api.confirm_reservation(res["id"], make_renter_headers(cust_id)))
    assert confirmed["lifecycle_status"] == "CONFIRMED"
    assert confirmed["payment_status"] == "DEPOSIT_HELD"


def test_gear_unit_condition_cycle_returns_to_available(api):
    """PRD §3.8: "Finally the unit leaves inspection: it returns from `INSPECTING` to
    `AVAILABLE` when its `condition` is `GOOD` or `WORN`, ... in either case
    `active_reservation_id` is cleared."
    PRD §3.3: "the unit transitions from `AVAILABLE` to `RESERVED`, with its
    `active_reservation_id` set to the new reservation and its `version` incremented."

    Design: Difficulty/non_linear_state_machine/gear_unit_condition_cycle_returns_to_available
    """
    s = fx.setup_returned_reservation(category="SUP", clock="2026-05-04T08:00:00Z",
                                      pickup_at="2026-05-04T08:00:00Z",
                                      due_at="2026-05-04T10:00:00Z",
                                      return_clock="2026-05-04T09:30:00Z",
                                      checkin_rating="GOOD", asset_tag="SUP-4")
    fx.settle_reservation(s["reservation"]["id"])
    unit = validate_success(api.get_gear_unit(s["gear_unit"]["id"], AGENT))
    assert unit["availability"] == "AVAILABLE"
    assert unit["active_reservation_id"] is None


# ===========================================================================
# Queue A — transitive_cascade
# ===========================================================================

def test_loss_checkin_cascade_retires_unit_and_suspends_customer(api):
    """PRD §3.6: "If the check-in rating is `LOST`, the `outcome` is `LOSS`, the
    `charge_cents` is the rate card's `loss_fee_cents`, and `waiver_applied` is false."
    PRD §3.6: "when the check-in rating is `LOST` the unit is routed from `INSPECTING`
    to `RETIRED` and permanently removed from rentable inventory, with
    `active_reservation_id` cleared."
    PRD §3.2: "it is `SUSPENDED` whenever the open loss balance is greater than 0 **or**
    the strike total is at least 4"
    PRD §3.8: "Settlement also re-derives the customer's standing in its final variant,
    by which point the posted unsettled loss is reflected in `open_loss_balance_cents`."

    Design: Difficulty/transitive_cascade/loss_checkin_cascade_depth3_retire_unit_and_suspend_customer
    """
    s = fx.setup_picked_up_reservation(category="SKI", clock="2026-05-05T08:00:00Z",
                                       pickup_at="2026-05-05T08:00:00Z",
                                       due_at="2026-05-05T10:00:00Z", checkout_rating="GOOD",
                                       reservation_overrides={"damage_waiver_opted": False},
                                       customer_overrides={"email": "cy@x.com", "skill_level": "EXPERT"},
                                       asset_tag="SKI-1")
    res_id = s["reservation"]["id"]
    fx.set_clock("2026-05-05T09:30:00Z")
    fx.checkin_reservation(res_id, "LOST")
    fx.settle_reservation(res_id)

    assessment = fx.get_assessment_for_reservation(res_id)
    assert assessment["outcome"] == "LOSS"
    assert assessment["charge_cents"] == 20000

    unit = validate_success(api.get_gear_unit(s["gear_unit"]["id"], AGENT))
    assert unit["availability"] == "RETIRED"

    customer = validate_success(api.get_customer(s["customer"]["id"], AGENT))
    assert customer["standing"] == "SUSPENDED"


def test_cancel_cascade_releases_unit_and_refunds_deposit(api):
    """PRD §3.9: "Cancellation moves the `lifecycle_status` to `CANCELLED`, releases
    the unit by moving its `availability` from `RESERVED` back to `AVAILABLE` and
    clearing `active_reservation_id`. If the reservation's `payment_status` was
    `DEPOSIT_HELD`, a `DEPOSIT_REFUND` ledger entry is written for the negative
    deposit amount and the `payment_status` moves to `REFUNDED`."

    Design: Difficulty/transitive_cascade/cancel_cascade_depth2_release_unit_and_refund_deposit
    """
    s = fx.setup_confirmed_reservation(category="SKI", clock="2026-05-06T08:00:00Z",
                                       pickup_at="2026-05-06T08:00:00Z",
                                       due_at="2026-05-06T10:00:00Z",
                                       customer_overrides={"email": "del@x.com", "skill_level": "EXPERT"},
                                       asset_tag="SKI-2")
    res_id = s["reservation"]["id"]
    cancelled = validate_success(api.cancel_reservation(res_id, AGENT))
    assert cancelled["payment_status"] == "REFUNDED"

    unit = validate_success(api.get_gear_unit(s["gear_unit"]["id"], AGENT))
    assert unit["availability"] == "AVAILABLE"

    entries = fx.get_ledger_for_reservation(res_id)
    types_amounts = {(e["entry_type"], e["amount_cents"]) for e in entries}
    assert ("DEPOSIT_HOLD", 5000) in types_amounts
    assert ("DEPOSIT_REFUND", -5000) in types_amounts


# ===========================================================================
# Queue A — cross_entity_state_dependency
# ===========================================================================

def test_checkout_succeeds_when_gear_unit_reserved(api):
    """PRD §3.6: "Checkout advances the reservation from `CONFIRMED` to `PICKED_UP`,
    stamps `picked_up_at` with the current clock, moves the unit's `availability` from
    `RESERVED` to `CHECKED_OUT`, and sets the unit's `condition` from the checkout
    rating."

    Design: Difficulty/cross_entity_state_dependency/checkout_requires_gear_unit_reserved
    """
    s = fx.setup_confirmed_reservation(category="KAYAK", clock="2026-05-11T08:00:00Z",
                                       pickup_at="2026-05-11T08:00:00Z",
                                       due_at="2026-05-11T10:00:00Z",
                                       customer_overrides={"email": "ida@x.com", "skill_level": "EXPERT"},
                                       asset_tag="KAY-3")
    res = validate_success(
        api.checkout_reservation(s["reservation"]["id"], {"condition_rating": "GOOD"}, AGENT))
    assert res["lifecycle_status"] == "PICKED_UP"
    unit = validate_success(api.get_gear_unit(s["gear_unit"]["id"], AGENT))
    assert unit["availability"] == "CHECKED_OUT"


def test_confirm_blocked_when_customer_suspended(api):
    """PRD §3.5: "The customer's `standing` must not be `SUSPENDED`; a suspended renter
    is turned away with `ERR_CUSTOMER_SUSPENDED`."
    PRD §3.2: "it is `SUSPENDED` whenever the open loss balance is greater than 0 **or**
    the strike total is at least 4"

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_customer_suspended
    """
    s = fx.setup_suspended_customer(category="KAYAK", clock="2026-05-12T08:00:00Z",
                                    asset_tag1="KAY-4")
    customer = validate_success(api.get_customer(s["customer"]["id"], AGENT))
    assert customer["standing"] == "SUSPENDED"

    # Fresh QUOTED reservation on a second unit for the same suspended customer.
    unit2 = fx.create_gear_unit(s["gear_type"]["id"], s["rate_card"]["id"], asset_tag="KAY-5")
    res2 = fx.create_reservation(s["customer"]["id"], unit2["id"], unit2["version"],
                                 "2026-05-13T08:00:00Z", "2026-05-13T10:00:00Z", actor=AGENT)
    resp = api.confirm_reservation(res2["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED.value)


# ===========================================================================
# Queue A — compensating_invariant
# ===========================================================================

def test_cancel_deposit_money_conservation_nets_zero(api):
    """PRD §3.9: "The compensating invariant is that the net money on a cancelled
    reservation's ledger returns to zero — the held deposit is fully conserved on the
    way out."
    PRD §3.5: "a ledger entry of type `DEPOSIT_HOLD` is written for the positive
    deposit amount."

    Design: Difficulty/compensating_invariant/cancel_deposit_money_conservation_nets_zero
    """
    s = fx.setup_confirmed_reservation(category="KAYAK", clock="2026-05-16T08:00:00Z",
                                       pickup_at="2026-05-16T08:00:00Z",
                                       due_at="2026-05-16T10:00:00Z",
                                       customer_overrides={"email": "moe@x.com", "skill_level": "EXPERT"},
                                       asset_tag="KAY-7")
    res_id = s["reservation"]["id"]
    fx.cancel_reservation(res_id, actor=AGENT)
    entries = fx.get_ledger_for_reservation(res_id)
    assert sum(e["amount_cents"] for e in entries) == 0
    types_amounts = {(e["entry_type"], e["amount_cents"]) for e in entries}
    assert ("DEPOSIT_HOLD", 5000) in types_amounts
    assert ("DEPOSIT_REFUND", -5000) in types_amounts


def test_cancel_inventory_conservation_unit_returns_available(api):
    """PRD §3.9: "Cancellation moves the `lifecycle_status` to `CANCELLED`, releases
    the unit by moving its `availability` from `RESERVED` back to `AVAILABLE` and
    clearing `active_reservation_id`."
    PRD §3.3: "the unit transitions from `AVAILABLE` to `RESERVED`, with its
    `active_reservation_id` set to the new reservation and its `version` incremented."

    Design: Difficulty/compensating_invariant/cancel_inventory_count_conservation_unit_returns_to_available
    """
    fx.set_clock("2026-05-17T08:00:00Z")
    gt = fx.create_gear_type(category="KAYAK", name="Fishing", size_label="L")
    rc = fx.create_rate_card(gt["id"])
    unit = fx.create_gear_unit(gt["id"], rc["id"], asset_tag="KAY-8")
    cust = fx.create_customer(actor=AGENT, email="nia@x.com", skill_level="EXPERT")

    before, before_meta = validate_paginated(
        api.list_gear_units(AGENT, params={"gear_type_id": gt["id"], "availability": "AVAILABLE"}))
    assert before_meta["total_count"] == 1

    res = fx.create_reservation(cust["id"], unit["id"], unit["version"],
                                "2026-05-17T08:00:00Z", "2026-05-17T10:00:00Z", actor=AGENT)
    fx.cancel_reservation(res["id"], actor=AGENT)

    after, after_meta = validate_paginated(
        api.list_gear_units(AGENT, params={"gear_type_id": gt["id"], "availability": "AVAILABLE"}))
    assert after_meta["total_count"] == 1
    unit_now = validate_success(api.get_gear_unit(unit["id"], AGENT))
    assert unit_now["availability"] == "AVAILABLE"


# ===========================================================================
# Queue B — state_machines (corner)
# ===========================================================================

def test_confirm_from_already_confirmed_returns_invalid_state(api):
    """PRD §3.9: "A request to drive a reservation through a transition it is not
    currently positioned for is rejected with `ERR_INVALID_STATE`."
    PRD §3.5: "confirming the reservation advances it from `QUOTED` to `CONFIRMED`."

    Design: Corner/state_machines/confirm_from_already_confirmed_returns_invalid_state
    """
    s = fx.setup_confirmed_reservation(category="KAYAK", clock="2026-06-03T08:00:00Z",
                                       pickup_at="2026-06-03T08:00:00Z",
                                       due_at="2026-06-03T10:00:00Z",
                                       customer_overrides={"email": "sue@x.com", "skill_level": "EXPERT"},
                                       asset_tag="IS-1")
    resp = api.confirm_reservation(s["reservation"]["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_from_picked_up_returns_invalid_state(api):
    """PRD §3.9: "A reservation may be cancelled while it is still `QUOTED` or
    `CONFIRMED` — never after pickup."
    PRD §3.9: "A request to drive a reservation through a transition it is not
    currently positioned for is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_from_picked_up_returns_invalid_state
    """
    s = fx.setup_picked_up_reservation(category="KAYAK", clock="2026-06-04T08:00:00Z",
                                       pickup_at="2026-06-04T08:00:00Z",
                                       due_at="2026-06-04T10:00:00Z",
                                       customer_overrides={"email": "ty@x.com", "skill_level": "EXPERT"},
                                       asset_tag="PU-1")
    resp = api.cancel_reservation(s["reservation"]["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_terminal_cancelled_reservation_rejects_confirm(api):
    """PRD §3.9: "Both `CLOSED` and `CANCELLED` are terminal lifecycle states. A
    request to drive a reservation through a transition it is not currently positioned
    for is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_cancelled_reservation_rejects_confirm
    """
    s = fx.setup_quoted_reservation(category="KAYAK", clock="2026-06-05T08:00:00Z",
                                    pickup_at="2026-06-05T08:00:00Z",
                                    due_at="2026-06-05T10:00:00Z",
                                    customer_overrides={"email": "uma@x.com", "skill_level": "EXPERT"},
                                    asset_tag="TC-1")
    fx.cancel_reservation(s["reservation"]["id"], actor=AGENT)
    resp = api.confirm_reservation(s["reservation"]["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_repair_returns_unit_from_maintenance_to_available(api):
    """PRD §3.8: "A unit parked in `MAINTENANCE` is returned to service by a `ShopAdmin`
    repair, which moves the unit from `MAINTENANCE` back to `AVAILABLE` and steps its
    `condition` from `DAMAGED` to `WORN`."

    Design: Corner/state_machines/repair_returns_unit_from_maintenance_to_available
    """
    s = fx.setup_returned_reservation(category="SKI", clock="2026-06-06T08:00:00Z",
                                      pickup_at="2026-06-06T08:00:00Z",
                                      due_at="2026-06-06T10:00:00Z",
                                      return_clock="2026-06-06T09:30:00Z",
                                      checkin_rating="DAMAGED",
                                      reservation_overrides={"damage_waiver_opted": False},
                                      customer_overrides={"email": "vic@x.com", "skill_level": "EXPERT"},
                                      asset_tag="REP-1")
    fx.settle_reservation(s["reservation"]["id"])
    repaired = validate_success(api.repair_gear_unit(s["gear_unit"]["id"], ADMIN))
    assert repaired["availability"] == "AVAILABLE"
    assert repaired["condition"] == "WORN"


def test_damaged_settle_routes_unit_to_maintenance(api):
    """PRD §3.8: "or moves from `INSPECTING` to `MAINTENANCE` when its `condition` is
    `DAMAGED`; in either case `active_reservation_id` is cleared."
    PRD §3.6: "otherwise the `charge_cents` is `loss_fee_cents` multiplied by 0.40 and
    rounded half up to whole cents, with `waiver_applied` false."

    Design: Corner/state_machines/damaged_settle_routes_unit_to_maintenance_conditional_cascade
    """
    s = fx.setup_returned_reservation(category="SKI", clock="2026-06-07T08:00:00Z",
                                      pickup_at="2026-06-07T08:00:00Z",
                                      due_at="2026-06-07T10:00:00Z",
                                      return_clock="2026-06-07T09:30:00Z",
                                      checkin_rating="DAMAGED",
                                      reservation_overrides={"damage_waiver_opted": False},
                                      customer_overrides={"email": "wei@x.com", "skill_level": "EXPERT"},
                                      asset_tag="DMG-1")
    fx.settle_reservation(s["reservation"]["id"])
    unit = validate_success(api.get_gear_unit(s["gear_unit"]["id"], AGENT))
    assert unit["availability"] == "MAINTENANCE"
    assessment = fx.get_assessment_for_reservation(s["reservation"]["id"])
    # round(20000 * 0.40) = 8000.
    assert assessment["charge_cents"] == 8000
    assert assessment["outcome"] == "DAMAGE"


def test_damage_waiver_suppresses_damage_charge(api):
    """PRD §3.6: "when `damage_waiver_opted` is true the `charge_cents` is 0 and
    `waiver_applied` is true"

    Design: Corner/state_machines/damage_waiver_suppresses_damage_charge
    """
    s = fx.setup_picked_up_reservation(category="SKI", clock="2026-06-08T08:00:00Z",
                                       pickup_at="2026-06-08T08:00:00Z",
                                       due_at="2026-06-08T10:00:00Z",
                                       reservation_overrides={"damage_waiver_opted": True},
                                       customer_overrides={"email": "xia@x.com", "skill_level": "EXPERT"},
                                       asset_tag="WV-1")
    fx.set_clock("2026-06-08T09:30:00Z")
    fx.checkin_reservation(s["reservation"]["id"], "DAMAGED")
    assessment = fx.get_assessment_for_reservation(s["reservation"]["id"])
    assert assessment["charge_cents"] == 0
    assert assessment["waiver_applied"] is True


def test_dispute_then_reassess_returns_assessment_to_assessed(api):
    """PRD §3.7: "A renter who disagrees with an assessment on their own rental may
    dispute it, moving its `status` from `ASSESSED` to `DISPUTED`."
    PRD §3.7: "A `ShopAdmin` resolves a dispute by reassessing, moving the `status`
    from `DISPUTED` back to `ASSESSED`; reassessment also requires
    `expected_damage_assessment_version` to match, increments the `version`"

    Design: Corner/state_machines/dispute_then_reassess_returns_assessment_to_assessed
    """
    s = fx.setup_disputed_assessment(category="SKI", clock="2026-06-09T08:00:00Z",
                                     pickup_at="2026-06-09T08:00:00Z",
                                     due_at="2026-06-09T10:00:00Z",
                                     return_clock="2026-06-09T09:30:00Z",
                                     checkin_rating="DAMAGED", asset_tag="CYC-1")
    disputed = s["assessment"]
    reassessed = validate_success(api.reassess_damage_assessment(
        disputed["id"], {"expected_damage_assessment_version": disputed["version"]}, ADMIN))
    assert reassessed["status"] == "ASSESSED"


def test_confirm_holds_deposit_ledger_sync(api):
    """PRD §3.5: "a ledger entry of type `DEPOSIT_HOLD` is written for the positive
    deposit amount."
    PRD §3.5: "the reservation snapshots `deposit_cents` from its rate card, its
    `payment_status` moves from `UNPAID` to `DEPOSIT_HELD`"

    Design: Corner/state_machines/confirm_holds_deposit_ledger_sync_side_effect
    """
    s = fx.setup_quoted_reservation(category="KAYAK", clock="2026-06-10T08:00:00Z",
                                    pickup_at="2026-06-10T08:00:00Z",
                                    due_at="2026-06-10T10:00:00Z",
                                    customer_overrides={"email": "zoe@x.com", "skill_level": "EXPERT"},
                                    asset_tag="LED-1")
    confirmed = validate_success(api.confirm_reservation(s["reservation"]["id"], AGENT))
    assert confirmed["deposit_cents"] == 5000
    entries = fx.get_ledger_for_reservation(s["reservation"]["id"])
    holds = [e for e in entries if e["entry_type"] == "DEPOSIT_HOLD"]
    assert len(holds) == 1
    assert holds[0]["amount_cents"] == 5000


# ===========================================================================
# Queue B — consistency_model (corner)
# ===========================================================================

def test_confirm_response_reflects_deposit_immediately(api):
    """PRD §3.5: "On success, the reservation snapshots `deposit_cents` from its rate
    card, its `payment_status` moves from `UNPAID` to `DEPOSIT_HELD`"

    Design: Corner/consistency_model/confirm_response_reflects_deposit_immediately
    """
    s = fx.setup_quoted_reservation(category="KAYAK", clock="2026-06-23T08:00:00Z",
                                    pickup_at="2026-06-23T08:00:00Z",
                                    due_at="2026-06-23T10:00:00Z",
                                    customer_overrides={"email": "lyn@x.com", "skill_level": "EXPERT"},
                                    asset_tag="IMM-1")
    confirmed = validate_success(api.confirm_reservation(s["reservation"]["id"], AGENT))
    assert confirmed["deposit_cents"] == 5000
    assert confirmed["payment_status"] == "DEPOSIT_HELD"
