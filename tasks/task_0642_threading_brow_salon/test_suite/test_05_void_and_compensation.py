"""The compensating void cascade: a void must leave loyalty balance, retail stock,
and drawn package credits exactly as they stood before the visit existed. Also the
member-risk dual-variant (no-show strike domain distinct from the cost domain) and
the cyclic package DEPLETED<->ACTIVE compensation.

Covers difficulty queue A rules `transitive_cascade` (3-hop settled void),
`compensating_invariant` (retail-stock and loyalty conservation), and
`dual_variant_calc` (strike domain); plus corner queue B
`state_machines/package_depleted_then_active_on_void_cyclic_compensation`.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
)
import test_helpers as th

FRONT_DESK = TEST_USERS["front_desk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ===========================================================================
# Difficulty A: transitive_cascade / void_settled_visit_compensates_three_hops
# ===========================================================================
def test_void_settled_visit_reverses_loyalty_to_zero(api):
    """PRD §3.8: "If the visit had already been settled — `payment_status` is `SETTLED`
    — then the payment moves to `REFUNDED`, a `REVERSAL` ledger entry of negative
    `loyalty_earned` is written to claw back the points the visit granted, and the
    `stock_qty` of each `RetailProduct` referenced by a `RETAIL` line is restored."

    Design: Difficulty/transitive_cascade/void_settled_visit_compensates_three_hops
    """
    # BRONZE package, package_eligible service, retail SERUM line, completed (credit
    # drawn -> service free), settled (loyalty earned), then voided.
    salon = th.create_and_open_salon(loyalty_earn_rate_bps=500)
    chair = th.add_chair(salon["id"])
    tech = th.add_technician(salon["id"])
    svc = th.add_service_item(salon["id"], package_eligible=True)
    serum = th.add_retail_product(salon["id"], unit_price_cents=3000, initial_stock_qty=10)
    member = th.add_member(salon["id"])
    pkg = th.add_active_package(member["id"], "BRONZE")
    ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
    visit = th.seat_visit(salon["id"], ticket["id"], chair["id"], tech["id"],
                          salon["version"], membership_package_id=pkg["id"])
    th.add_retail_line(visit["id"], serum["id"], quantity=1)
    th.complete_visit(visit["id"], tech["id"])
    th.settle_visit(visit["id"])
    voided = validate_success(api.void_service_visit(visit["id"], MANAGER))
    assert voided["service_status"] == "VOIDED"
    assert voided["payment_status"] == "REFUNDED"
    member_after = validate_success(api.get_member(member["id"], FRONT_DESK))
    assert member_after["loyalty_balance"] == 0, (
        f"loyalty should return to 0 after REVERSAL, got {member_after['loyalty_balance']}"
    )


def test_void_settled_visit_restores_credit_and_stock(api):
    """PRD §3.8: "If the visit had drawn a package credit — that is, `used_package_credit`
    is true — the package's `credits_remaining` is incremented by one ... the
    `stock_qty` of each `RetailProduct` referenced by a `RETAIL` line is restored."

    Design: Difficulty/transitive_cascade/void_settled_visit_compensates_three_hops
    """
    salon = th.create_and_open_salon(loyalty_earn_rate_bps=500)
    chair = th.add_chair(salon["id"])
    tech = th.add_technician(salon["id"])
    svc = th.add_service_item(salon["id"], package_eligible=True)
    serum = th.add_retail_product(salon["id"], unit_price_cents=3000, initial_stock_qty=10)
    member = th.add_member(salon["id"])
    pkg = th.add_active_package(member["id"], "BRONZE")  # 4 credits
    ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
    visit = th.seat_visit(salon["id"], ticket["id"], chair["id"], tech["id"],
                          salon["version"], membership_package_id=pkg["id"])
    th.add_retail_line(visit["id"], serum["id"], quantity=1)
    th.complete_visit(visit["id"], tech["id"])  # credit drawn -> 3 remaining
    th.settle_visit(visit["id"])
    validate_success(api.void_service_visit(visit["id"], MANAGER))
    pkg_after = validate_success(api.get_package(pkg["id"], MANAGER))
    assert pkg_after["credits_remaining"] == 4, (
        f"credit should be restored to 4, got {pkg_after['credits_remaining']}"
    )
    prod_after = validate_success(api.get_retail_product(serum["id"], MANAGER))
    assert prod_after["stock_qty"] == 10, (
        f"stock should be restored to 10, got {prod_after['stock_qty']}"
    )


# ===========================================================================
# Difficulty A: compensating_invariant / void_conserves_retail_stock
# ===========================================================================
def test_void_conserves_retail_stock(api):
    """PRD §2.10: "The most demanding case is the void, which is a compensating action:
    it must leave the member's loyalty balance, the retail stock, and any drawn package
    credit exactly as they stood before the visit existed."

    Design: Difficulty/compensating_invariant/void_conserves_retail_stock
    """
    s = th.setup_seated_visit()
    salon, visit = s["salon"], s["visit"]
    serum = th.add_retail_product(salon["id"], unit_price_cents=3000, initial_stock_qty=10)
    th.add_retail_line(visit["id"], serum["id"], quantity=3)  # stock -> 7
    mid = validate_success(api.get_retail_product(serum["id"], MANAGER))
    assert mid["stock_qty"] == 7
    voided = validate_success(api.void_service_visit(visit["id"], MANAGER))
    assert voided["service_status"] == "VOIDED"
    after = validate_success(api.get_retail_product(serum["id"], MANAGER))
    assert after["stock_qty"] == 10, f"stock must return to 10, got {after['stock_qty']}"


def test_void_voids_all_active_lines_and_conserves_stock(api):
    """PRD §3.8: "Finally, every `ACTIVE` `VisitLineItem` on the visit is moved to
    `VOIDED`. Taken together, these effects guarantee that a voided visit leaves no
    residue in loyalty, inventory, or package credits."

    Design: Difficulty/compensating_invariant/void_conserves_retail_stock
    """
    s = th.setup_seated_visit()
    salon, visit = s["salon"], s["visit"]
    serum = th.add_retail_product(salon["id"], unit_price_cents=3000, initial_stock_qty=10)
    line = th.add_retail_line(visit["id"], serum["id"], quantity=3)  # stock -> 7
    validate_success(api.void_service_visit(visit["id"], MANAGER))
    line_after = validate_success(api.get_line_item(line["id"], MANAGER))
    assert line_after["status"] == "VOIDED"
    prod = validate_success(api.get_retail_product(serum["id"], MANAGER))
    assert prod["stock_qty"] == 10  # no inventory residue


# ===========================================================================
# Difficulty A: compensating_invariant / void_conserves_member_loyalty_balance
# ===========================================================================
def test_void_conserves_member_loyalty_balance(api):
    """PRD §3.8: "If the visit had already been settled — `payment_status` is `SETTLED`
    — then the payment moves to `REFUNDED`, a `REVERSAL` ledger entry of negative
    `loyalty_earned` is written to claw back the points the visit granted."

    Design: Difficulty/compensating_invariant/void_conserves_member_loyalty_balance
    """
    s = th.setup_seated_visit(loyalty_earn_rate_bps=500)  # member starts at 0 balance
    visit, member = s["visit"], s["member"]
    th.complete_visit(visit["id"], s["tech"]["id"])  # earn computed
    th.settle_visit(visit["id"])  # EARN written, balance > 0
    voided = validate_success(api.void_service_visit(visit["id"], MANAGER))
    assert voided["payment_status"] == "REFUNDED"
    after = validate_success(api.get_member(member["id"], FRONT_DESK))
    assert after["loyalty_balance"] == 0, (
        f"REVERSAL must cancel EARN, balance back to 0, got {after['loyalty_balance']}"
    )


def test_void_settled_visit_writes_reversal_entry(api):
    """PRD §3.8: "a `REVERSAL` ledger entry of negative `loyalty_earned` is written to
    claw back the points the visit granted."
    PRD §3.1: "The `loyalty_balance` is a derived figure equal to the sum of the signed
    `points` across every `LoyaltyLedgerEntry` for that member, floored at zero."

    Design: Difficulty/compensating_invariant/void_conserves_member_loyalty_balance
    """
    s = th.setup_seated_visit(loyalty_earn_rate_bps=500)
    visit, member = s["visit"], s["member"]
    completed = th.complete_visit(visit["id"], s["tech"]["id"])
    earned = completed["loyalty_earned"]
    assert earned > 0
    settled = th.settle_visit(visit["id"])
    mid = validate_success(api.get_member(member["id"], FRONT_DESK))
    assert mid["loyalty_balance"] == earned  # EARN posted
    validate_success(api.void_service_visit(visit["id"], MANAGER))
    after = validate_success(api.get_member(member["id"], FRONT_DESK))
    assert after["loyalty_balance"] == 0  # REVERSAL exactly cancels EARN


# ===========================================================================
# Difficulty A: dual_variant_calc / no_show_strike_score_distinct_from_cost_domain
# ===========================================================================
def test_no_show_strike_domain_escalates_member_status(api):
    """PRD §3.7: "at the moment a no-show is recorded the member's standing is
    re-evaluated against two thresholds ... otherwise a member whose strike count is at
    least two is moved to `SUSPENDED`."

    Design: Difficulty/dual_variant_calc/no_show_strike_score_distinct_from_cost_domain
    """
    salon = th.create_and_open_salon()
    svc = th.add_service_item(salon["id"])
    member = th.drive_member_to_strikes(salon["id"], svc["id"], 2)
    assert member["no_show_strikes"] == 2
    assert member["status"] == "SUSPENDED"


def test_no_show_strike_score_is_member_domain_not_cost(api):
    """PRD §3.7: "No-shows feed a separate risk track on the member. Each un-expired
    no-show contributes one strike to `no_show_strikes`."

    Design: Difficulty/dual_variant_calc/no_show_strike_score_distinct_from_cost_domain
    """
    salon = th.create_and_open_salon()
    svc = th.add_service_item(salon["id"])
    member = th.drive_member_to_strikes(salon["id"], svc["id"], 1)
    # One strike: still on the risk track, but below the suspend threshold and the cost
    # domain (loyalty balance) is untouched.
    assert member["no_show_strikes"] == 1
    assert member["status"] == "ACTIVE"
    assert member["loyalty_balance"] == 0


# ===========================================================================
# Corner B: state_machines / package_depleted_then_active_on_void_cyclic_compensation
# ===========================================================================
def test_package_depleted_then_active_on_void(api):
    """PRD §3.6: "A package is `ACTIVE` while `credits_remaining` is above zero,
    transitions to `DEPLETED` the moment its last credit is consumed at a visit
    finalization, and can swing back from `DEPLETED` to `ACTIVE` if a void restores a
    credit."

    Design: Corner/state_machines/package_depleted_then_active_on_void_cyclic_compensation
    """
    th.set_clock("2026-02-01T09:00:00Z")
    salon = th.create_and_open_salon(set_default_clock=False)
    chair = th.add_chair(salon["id"], sanitation_minutes=0)
    tech = th.add_technician(salon["id"])
    svc = th.add_service_item(salon["id"], package_eligible=True)
    member = th.add_member(salon["id"])
    pkg = th.add_active_package(member["id"], "BRONZE")  # 4 credits

    # Draw down to the last credit: complete 4 package-eligible visits.
    last_visit_id = None
    for _ in range(4):
        live = validate_success(api.get_salon(salon["id"], MANAGER))
        ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
        visit = th.seat_visit(salon["id"], ticket["id"], chair["id"], tech["id"],
                              live["version"], membership_package_id=pkg["id"])
        th.complete_visit(visit["id"], tech["id"])
        validate_success(api.mark_chair_sanitized(chair["id"], FRONT_DESK))
        last_visit_id = visit["id"]

    depleted = validate_success(api.get_package(pkg["id"], MANAGER))
    assert depleted["credits_remaining"] == 0
    assert depleted["status"] == "DEPLETED"

    # Void the last visit -> a credit is restored, swinging the package back to ACTIVE.
    validate_success(api.void_service_visit(last_visit_id, MANAGER))
    after = validate_success(api.get_package(pkg["id"], MANAGER))
    assert after["credits_remaining"] == 1
    assert after["status"] == "ACTIVE"
