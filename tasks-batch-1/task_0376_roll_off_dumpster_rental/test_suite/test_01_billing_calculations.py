"""Billing calculations: dual-variant estimate-vs-final, the five-component final
charge, the pinned tonnage-before-contamination order, threshold boundaries,
flat contamination fees, and the projected credit gate.

All money is whole integer cents (PRD §2.6); expected values are PRD-derivable
from the container-type pricing profile and the recorded weights.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_contractor_headers,
)
from test_helpers import fixtures
from test_helpers import factories


YARD_ADMIN = TEST_USERS["yard_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
CONTRACTOR = TEST_USERS["contractor_headers"]


def _invoice_for(api, order_id):
    resp = api.list_order_invoice(order_id, BILLING)
    data = validate_success(resp)
    assert len(data) == 1, f"expected exactly one invoice for order {order_id}, got {len(data)}"
    return data[0]


# ===========================================================================
# Queue A — dual_variant_calc
# ===========================================================================
def test_order_estimate_and_final_billing_diverge(api):
    """PRD §3.9 stage one: "the tonnage charge is computed using the estimated
    weight — the estimated_weight_lbs recorded on the PICKUP service stop".
    PRD §3.9 stage two: "the tonnage charge using the final weight — the
    net_weight_lbs of the PICKUP stop's weigh ticket, which replaces the
    estimate". PRD §3.9: "The provisional and final totals diverge whenever the
    estimated weight differs from the scale weight or any contamination is
    found."

    Estimate uses 5000 lb (1000 over -> 9000) so estimated_total_cents =
    50000 + 4500 + 9000 = 63500; final uses net 6200 lb (2200 over -> 19800) so
    final_total_cents = 50000 + 4500 + 19800 = 74300.

    Design: Difficulty/dual_variant_calc/order_estimate_vs_final_billing_diverge
    """
    ctx = fixtures.setup_pickup_ready(
        delivery_date="2026-06-01", pickup_date="2026-06-10",
        estimated_weight_lbs=5000,
        weigh_ticket_overrides={"gross_weight_lbs": 16200, "tare_weight_lbs": 10000},
    )
    resp = api.complete_stop(ctx["pu_stop"]["id"], DISPATCHER)
    validate_success(resp)
    order = validate_success(api.get_rental_order(ctx["order"]["id"], DISPATCHER))
    assert order["estimated_total_cents"] == 63500, order["estimated_total_cents"]
    assert order["final_total_cents"] == 74300, order["final_total_cents"]
    assert order["estimated_total_cents"] != order["final_total_cents"]
    assert order["billing_status"] == "FINALIZED"
    assert order["logistics_status"] == "COMPLETED"


def test_account_credit_current_reading_vs_projected_gate(api):
    """PRD §3.3: "If that projected figure would be below zero — equivalently, if
    the new order's base_rate_cents exceeds the account's current
    available_credit_cents — the booking is rejected with
    ERR_CREDIT_LIMIT_EXCEEDED (HTTP 402)."
    PRD §3.2: "The available_credit_cents is the account's credit_limit_cents
    minus its outstanding_cents."

    Limit 40000, no invoices -> available 40000; a YD30 booking (base 50000)
    has projected 40000-50000 = -10000 < 0, so GET shows 40000 yet POST is 402.

    Design: Difficulty/dual_variant_calc/account_credit_current_vs_projected
    """
    ct = fixtures.create_container_type()  # YD30 base 50000
    account = fixtures.create_account(business_name="Tight", credit_limit_cents=40000)
    acct = validate_success(api.get_contractor_account(account["id"], YARD_ADMIN))
    assert acct["available_credit_cents"] == 40000

    resp = api.create_rental_order(
        factories.create_rental_order_payload(account["id"], ct["id"], site_address="9 Elm",
                                              requested_delivery_date="2026-07-01"),
        make_contractor_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)


def test_booking_allowed_when_base_rate_equals_available_credit(api):
    """PRD §3.3: "If that projected figure would be below zero — equivalently, if
    the new order's base_rate_cents exceeds the account's current
    available_credit_cents — the booking is rejected with
    ERR_CREDIT_LIMIT_EXCEEDED (HTTP 402)."

    Boundary: limit == base 50000, available 50000; projected 50000-50000 = 0,
    which is not below zero (base does not exceed available), so the booking is
    accepted, distinguishing the projected gate's >=0 boundary from the rejected
    case.

    Design: Difficulty/dual_variant_calc/account_credit_current_vs_projected
    """
    ct = fixtures.create_container_type()  # YD30 base 50000
    account = fixtures.create_account(business_name="Exact", credit_limit_cents=50000)
    resp = api.create_rental_order(
        factories.create_rental_order_payload(account["id"], ct["id"], site_address="9b Elm",
                                              requested_delivery_date="2026-07-01"),
        make_contractor_headers(account["id"]),
    )
    order = validate_success(resp, expected_status=201)
    assert order["logistics_status"] == "BOOKED"


def test_dual_variant_divergence_estimate_vs_final_values(api):
    """PRD §3.9 stage one: "its estimated_total_cents is computed in this pinned
    order: (1) the base is the container type's base_rate_cents; (2) the
    overage-day charge is computed as below; (3) the tonnage charge is computed
    using the estimated weight ... (4) the permit charge ...".
    PRD §3.9: "The provisional and final totals diverge whenever the estimated
    weight differs from the scale weight or any contamination is found."

    Also exercises the estimate-vs-final divergence breadth claim:
    estimate 63500 vs final 74300.

    Design: Difficulty/dual_variant_calc/order_estimate_vs_final_billing_diverge
    """
    ctx = fixtures.setup_pickup_ready(
        delivery_date="2026-06-01", pickup_date="2026-06-10",
        estimated_weight_lbs=5000,
        weigh_ticket_overrides={"gross_weight_lbs": 16200, "tare_weight_lbs": 10000},
    )
    validate_success(api.complete_stop(ctx["pu_stop"]["id"], DISPATCHER))
    order = validate_success(api.get_rental_order(ctx["order"]["id"], DISPATCHER))
    assert order["estimated_total_cents"] == 63500
    assert order["final_total_cents"] == 74300


# ===========================================================================
# Queue A — combinatorial_formula
# ===========================================================================
def test_final_charge_composes_five_nonlinear_components(api):
    """PRD §3.9 stage two: "its final_total_cents is computed in this pinned
    order: (1) base equals base_rate_cents; (2) the overage-day charge as below;
    (3) the tonnage charge using the final weight ... (4) permit equals the
    APPROVED permit's permit_fee_cents else 0; (5) the contamination fee as
    below. ... The final is the sum of these five components."
    PRD §3.10: "Its total_cents is the sum of base_cents, overage_day_cents,
    tonnage_cents, permit_cents, and contamination_cents."

    rental_days 8 -> 1 overage day -> 1500; net 7000 -> 3000 over -> 27000;
    permit 20000; HAZMAT 50000 + 3000*15 = 95000; total 193500.

    Design: Difficulty/combinatorial_formula/final_charge_nonlinear_five_components
    """
    ctx = fixtures.setup_pickup_ready(
        delivery_date="2026-06-01", pickup_date="2026-06-08",
        order_overrides={"site_address": "5 Dock", "requires_street_permit": True},
        account_overrides={"business_name": "Haz Co", "credit_limit_cents": 1000000},
        permit_overrides={"municipality": "Springfield", "permit_fee_cents": 20000,
                          "valid_from": "2026-06-01", "valid_until": "2026-06-30"},
        approve=True,
        estimated_weight_lbs=7000,
        weigh_ticket_overrides={"gross_weight_lbs": 17000, "tare_weight_lbs": 10000,
                                "contaminated": True, "contamination_kind": "HAZMAT"},
    )
    validate_success(api.complete_stop(ctx["pu_stop"]["id"], DISPATCHER))
    order = validate_success(api.get_rental_order(ctx["order"]["id"], DISPATCHER))
    assert order["final_total_cents"] == 193500, order["final_total_cents"]

    inv = _invoice_for(api, ctx["order"]["id"])
    assert inv["base_cents"] == 50000
    assert inv["overage_day_cents"] == 1500
    assert inv["tonnage_cents"] == 27000
    assert inv["permit_cents"] == 20000
    assert inv["contamination_cents"] == 95000
    assert inv["total_cents"] == 193500


def test_final_charge_invoice_total_equals_sum_of_five_line_items(api):
    """PRD §3.10: "Its total_cents is the sum of base_cents, overage_day_cents,
    tonnage_cents, permit_cents, and contamination_cents."
    PRD §3.10: "The invoice carries the same line items the final charge was
    built from: base_cents copied from the container type's base rate at
    finalization, the computed overage_day_cents, the computed tonnage_cents,
    permit_cents ... and contamination_cents".

    The issued invoice's total equals the arithmetic sum of its five line items
    and matches the order's final_total_cents (193500).

    Design: Difficulty/combinatorial_formula/final_charge_nonlinear_five_components
    """
    ctx = fixtures.setup_pickup_ready(
        delivery_date="2026-06-01", pickup_date="2026-06-08",
        order_overrides={"site_address": "5b Dock", "requires_street_permit": True},
        account_overrides={"business_name": "Haz Co2", "credit_limit_cents": 1000000},
        permit_overrides={"municipality": "Springfield", "permit_fee_cents": 20000,
                          "valid_from": "2026-06-01", "valid_until": "2026-06-30"},
        approve=True,
        estimated_weight_lbs=7000,
        weigh_ticket_overrides={"gross_weight_lbs": 17000, "tare_weight_lbs": 10000,
                                "contaminated": True, "contamination_kind": "HAZMAT"},
    )
    validate_success(api.complete_stop(ctx["pu_stop"]["id"], DISPATCHER))
    inv = _invoice_for(api, ctx["order"]["id"])
    summed = (inv["base_cents"] + inv["overage_day_cents"] + inv["tonnage_cents"]
              + inv["permit_cents"] + inv["contamination_cents"])
    assert inv["total_cents"] == summed
    order = validate_success(api.get_rental_order(ctx["order"]["id"], DISPATCHER))
    assert order["final_total_cents"] == inv["total_cents"] == 193500


def test_contamination_surcharge_uses_same_overage_pounds_as_tonnage(api):
    """PRD §3.9 contamination fee: "the fee is a flat 50,000 cents plus a
    surcharge of 15 cents for each billable overage pound — where the billable
    overage pounds are the very same pounds used in the final tonnage charge,
    namely the scale net_weight_lbs minus the type's included_tonnage_lbs, never
    below zero (not the full net weight). This is why tonnage must be computed
    before contamination."

    net 7000 -> overage 3000 -> tonnage 3000*9 = 27000 and HAZMAT surcharge
    3000*15 = 45000 (+50000 flat = 95000); rental_days 2 -> 0 overage days;
    total = 50000 + 0 + 27000 + 95000 = 172000.

    Design: Difficulty/combinatorial_formula/contamination_after_tonnage_pinned_eval_order
    """
    ctx = fixtures.setup_pickup_ready(
        delivery_date="2026-06-01", pickup_date="2026-06-02",
        order_overrides={"site_address": "6 Dock"},
        account_overrides={"business_name": "Haz2", "credit_limit_cents": 1000000},
        estimated_weight_lbs=7000,
        weigh_ticket_overrides={"gross_weight_lbs": 17000, "tare_weight_lbs": 10000,
                                "contaminated": True, "contamination_kind": "HAZMAT"},
    )
    validate_success(api.complete_stop(ctx["pu_stop"]["id"], DISPATCHER))
    inv = _invoice_for(api, ctx["order"]["id"])
    assert inv["tonnage_cents"] == 27000
    assert inv["contamination_cents"] == 95000
    assert inv["overage_day_cents"] == 0
    assert inv["total_cents"] == 172000


def test_hazmat_surcharge_slice_matches_tonnage_overage_pounds(api):
    """PRD §3.9 contamination fee: "the billable overage pounds are the very same
    pounds used in the final tonnage charge, namely the scale net_weight_lbs
    minus the type's included_tonnage_lbs, never below zero (not the full net
    weight)."

    The HAZMAT surcharge slice equals (contamination_cents - 50000) = 45000,
    which is 3000 overage lbs * 15; the tonnage charge uses the same 3000 lbs
    (3000 * 9 = 27000).

    Design: Difficulty/combinatorial_formula/contamination_after_tonnage_pinned_eval_order
    """
    ctx = fixtures.setup_pickup_ready(
        delivery_date="2026-06-01", pickup_date="2026-06-02",
        order_overrides={"site_address": "6b Dock"},
        account_overrides={"business_name": "Haz3", "credit_limit_cents": 1000000},
        estimated_weight_lbs=7000,
        weigh_ticket_overrides={"gross_weight_lbs": 17000, "tare_weight_lbs": 10000,
                                "contaminated": True, "contamination_kind": "HAZMAT"},
    )
    validate_success(api.complete_stop(ctx["pu_stop"]["id"], DISPATCHER))
    inv = _invoice_for(api, ctx["order"]["id"])
    surcharge_slice = inv["contamination_cents"] - 50000
    assert surcharge_slice == 45000
    # same 3000 overage lbs drive the tonnage charge at 9 cents/lb
    assert inv["tonnage_cents"] == 3000 * 9


# ===========================================================================
# Queue A — boundary_precision_check (overage-day boundary)
# ===========================================================================
def test_overage_day_charge_zero_at_exactly_included_days(api):
    """PRD §3.9 overage-day charge: "At the boundary, an order whose rental_days
    exactly equals included_days incurs zero overage days, and one day beyond
    that incurs exactly one overage day's fee."
    PRD §3.7: "its rental_days is recomputed as the inclusive span from delivery
    to pickup — that is, picked_up_on minus delivered_on, plus 1".

    delivered 2026-06-01, picked 2026-06-07 -> rental_days 7 == included_days 7
    -> overage_day_cents 0; net 3000 under tonnage so total == base 50000.

    Design: Difficulty/boundary_precision_check/overage_day_boundary_at_included_days
    """
    ctx = fixtures.setup_pickup_ready(
        delivery_date="2026-06-01", pickup_date="2026-06-07",
        account_overrides={"business_name": "Bnd1"},
        estimated_weight_lbs=3000,
        weigh_ticket_overrides={"gross_weight_lbs": 13000, "tare_weight_lbs": 10000},
    )
    validate_success(api.complete_stop(ctx["pu_stop"]["id"], DISPATCHER))
    order = validate_success(api.get_rental_order(ctx["order"]["id"], DISPATCHER))
    assert order["rental_days"] == 7
    inv = _invoice_for(api, ctx["order"]["id"])
    assert inv["overage_day_cents"] == 0
    assert inv["tonnage_cents"] == 0
    assert inv["total_cents"] == 50000


def test_overage_day_charge_one_day_beyond_included_days(api):
    """PRD §3.9 overage-day charge: "At the boundary, an order whose rental_days
    exactly equals included_days incurs zero overage days, and one day beyond
    that incurs exactly one overage day's fee."

    Boundary X+1: delivered 2026-06-01, picked 2026-06-08 -> rental_days 8 ->
    1 overage day -> overage_day_cents == 1500.

    Design: Difficulty/boundary_precision_check/overage_day_boundary_at_included_days
    """
    ctx = fixtures.setup_pickup_ready(
        delivery_date="2026-06-01", pickup_date="2026-06-08",
        account_overrides={"business_name": "Bnd1b"},
        estimated_weight_lbs=3000,
        weigh_ticket_overrides={"gross_weight_lbs": 13000, "tare_weight_lbs": 10000},
    )
    validate_success(api.complete_stop(ctx["pu_stop"]["id"], DISPATCHER))
    order = validate_success(api.get_rental_order(ctx["order"]["id"], DISPATCHER))
    assert order["rental_days"] == 8
    inv = _invoice_for(api, ctx["order"]["id"])
    assert inv["overage_day_cents"] == 1500


# ===========================================================================
# Queue B — calculations: tonnage boundary
# ===========================================================================
def test_tonnage_charge_zero_at_exactly_included_tonnage(api):
    """PRD §3.9 tonnage-overage charge: "At the boundary, a weight exactly equal
    to included_tonnage_lbs yields zero, and one pound over yields exactly one
    unit of the per-pound rate."

    net 4000 == included_tonnage_lbs 4000 -> tonnage_cents 0; rental_days under
    included -> total == base 50000.

    Design: Corner/calculations/tonnage_boundary_at_included_lbs
    """
    ctx = fixtures.setup_pickup_ready(
        delivery_date="2026-06-01", pickup_date="2026-06-05",
        account_overrides={"business_name": "Bdy", "credit_limit_cents": 1000000},
        estimated_weight_lbs=4000,
        weigh_ticket_overrides={"gross_weight_lbs": 14000, "tare_weight_lbs": 10000},
    )
    validate_success(api.complete_stop(ctx["pu_stop"]["id"], DISPATCHER))
    inv = _invoice_for(api, ctx["order"]["id"])
    assert inv["tonnage_cents"] == 0
    assert inv["total_cents"] == 50000


def test_tonnage_charge_one_pound_over_included_tonnage(api):
    """PRD §3.9 tonnage-overage charge: "At the boundary, a weight exactly equal
    to included_tonnage_lbs yields zero, and one pound over yields exactly one
    unit of the per-pound rate."

    Boundary X+1: net 4001 -> 1 overage lb -> tonnage_cents ==
    overage_rate_cents_per_lb (9).

    Design: Corner/calculations/tonnage_boundary_at_included_lbs
    """
    ctx = fixtures.setup_pickup_ready(
        delivery_date="2026-06-01", pickup_date="2026-06-05",
        account_overrides={"business_name": "Bdy2", "credit_limit_cents": 1000000},
        estimated_weight_lbs=4001,
        weigh_ticket_overrides={"gross_weight_lbs": 14001, "tare_weight_lbs": 10000},
    )
    validate_success(api.complete_stop(ctx["pu_stop"]["id"], DISPATCHER))
    inv = _invoice_for(api, ctx["order"]["id"])
    assert inv["tonnage_cents"] == 9


def test_contamination_tires_flat_fee(api):
    """PRD §3.9 contamination fee: "If the kind is TIRES, the fee is a flat 7,500
    cents."
    PRD §3.10: "Its total_cents is the sum of base_cents, overage_day_cents,
    tonnage_cents, permit_cents, and contamination_cents."

    net 3000 under tonnage, rental_days 5 (no overage day), TIRES ->
    contamination 7500; total = 50000 + 7500 = 57500.

    Design: Corner/calculations/contamination_tires_flat_fee
    """
    ctx = fixtures.setup_pickup_ready(
        delivery_date="2026-06-01", pickup_date="2026-06-05",
        account_overrides={"business_name": "Tire", "credit_limit_cents": 1000000},
        estimated_weight_lbs=3000,
        weigh_ticket_overrides={"gross_weight_lbs": 13000, "tare_weight_lbs": 10000,
                                "contaminated": True, "contamination_kind": "TIRES"},
    )
    validate_success(api.complete_stop(ctx["pu_stop"]["id"], DISPATCHER))
    inv = _invoice_for(api, ctx["order"]["id"])
    assert inv["contamination_cents"] == 7500
    assert inv["tonnage_cents"] == 0
    assert inv["overage_day_cents"] == 0
    assert inv["total_cents"] == 57500
