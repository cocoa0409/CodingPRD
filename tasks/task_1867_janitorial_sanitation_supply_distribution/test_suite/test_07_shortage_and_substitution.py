"""Shortage response: the depth-3 substitution cascade, proposal accept and
decline adjudication, and the proposal expiry sweep."""
from test_helpers import (
    TEST_USERS,
    get_order,
    get_only_order_line,
    get_proposal,
    make_facility_manager_headers,
    run_daily,
    set_clock,
    setup_pending_proposal,
    setup_placed_order,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["distributor_admin_headers"]


def _fm(facility):
    return make_facility_manager_headers(facility["id"])


class TestShortageCascadeDepth3:
    def test_cascade_cancels_line_and_order_when_no_substitute(self, api):
        """PRD: "When the candidate set is empty the line moves straight to
        `CANCELLED` and no proposal is created"
        PRD: "the order's status follows the auto-transition rules — all lines
        `CANCELLED` collapses the order to `CANCELLED`, otherwise at least one
        line in `SUBSTITUTION_PENDING` drops it to `PARTIALLY_BLOCKED`."

        Design: Difficulty/transitive_cascade/shortage_declare_cascade_depth3
        """
        facility, product, order = setup_placed_order(
            qty=3, base_price_cents=1000, category="EQUIPMENT",
            unit_of_measure="EACH", facility_name="Fac F",
            product_overrides={"sku": "SKU-EQ1", "name": "Vacuum"})
        assert order["total_cents"] == 5200, (
            "subtotal 3000 + fee 2000 + surcharge 200")
        validate_success(api.declare_shortage(product["id"], ADMIN))

        line = get_only_order_line(order["id"])
        assert line["status"] == "CANCELLED", (
            "No ACTIVE EQUIPMENT substitute exists, so the line is CANCELLED")
        proposals, meta = validate_paginated(
            api.list_substitution_proposals(ADMIN))
        assert meta["total_count"] == 0, "No proposal is created"
        after_order = get_order(order["id"])
        assert after_order["status"] == "CANCELLED"

    def test_cascade_releases_stock_and_committed_credit(self, api):
        """PRD: "An `ALLOCATED` line first releases its reservation — units
        return from `qty_allocated` to `qty_on_hand` — and only then is its
        fate decided."
        PRD: "The third link resynchronizes the facility ledger, recomputing
        `committed_cents` over the facility's `PLACED`, `PARTIALLY_BLOCKED`,
        and `DELIVERED` orders — which drops by the cancelled order's total
        when an order auto-cancels."

        Design: Difficulty/transitive_cascade/shortage_declare_cascade_depth3
        """
        facility, product, order = setup_placed_order(
            qty=3, base_price_cents=1000, category="EQUIPMENT",
            unit_of_measure="EACH", facility_name="Fac F",
            product_overrides={"sku": "SKU-EQ1", "name": "Vacuum"})
        validate_success(api.declare_shortage(product["id"], ADMIN))

        after_product = validate_success(
            api.get_product(product["id"], ADMIN))
        assert after_product["status"] == "SHORTAGE"
        assert after_product["qty_on_hand"] == 100
        assert after_product["qty_allocated"] == 0
        after_facility = validate_success(
            api.get_facility(facility["id"], ADMIN))
        assert after_facility["committed_cents"] == 0, "Was 5200"


class TestProposalAccept:
    def test_proposal_accept_swaps_line_and_reprices_order(self, api):
        """PRD: "An accepted proposal swaps the line's `product_id` to the
        proposed product, reprices the line at the proposed product's
        effective unit price at that instant, recomputes `line_total_cents`,
        allocates the proposed product's stock, finalizes
        `price_delta_cents`, and moves the proposal to `ACCEPTED`; the parent
        order's money fields are recomputed, and when no lines remain in
        `SUBSTITUTION_PENDING` the order climbs back to `PLACED`
        automatically, with `committed_cents` adjusted to the new total."
        PRD: "Candidates are ranked by lowest `base_price_cents`, ties broken
        by earliest `created_at`."

        Design: Corner/state_machines/proposal_accept_swaps_line_and_reprices_order
        """
        facility, short, sub, order, proposal = setup_pending_proposal(
            qty=2, short_price=1000, sub_price=900)
        assert proposal["proposed_product_id"] == sub["id"], (
            "The cheapest ACTIVE same-category product is proposed")

        accepted = validate_success(api.accept_proposal(
            proposal["id"], _fm(facility)))
        assert accepted["status"] == "ACCEPTED"
        assert accepted["price_delta_cents"] == -200, (
            "(900 - 1000) * 2 = -200: the substitute is cheaper")

        line = get_only_order_line(order["id"])
        assert line["product_id"] == sub["id"]
        assert line["unit_price_cents"] == 900
        assert line["line_total_cents"] == 1800
        assert line["status"] == "ALLOCATED"

        after_order = get_order(order["id"])
        assert after_order["status"] == "PLACED"
        assert after_order["merchandise_subtotal_cents"] == 1800
        assert after_order["delivery_fee_cents"] == 3200
        assert after_order["fuel_surcharge_cents"] == 200, (
            "Base is 1800 + 3200 = 5000")
        assert after_order["total_cents"] == 5200

        short_after = validate_success(api.get_product(short["id"], ADMIN))
        assert short_after["qty_on_hand"] == 100
        assert short_after["qty_allocated"] == 0
        sub_after = validate_success(api.get_product(sub["id"], ADMIN))
        assert sub_after["qty_on_hand"] == 98
        assert sub_after["qty_allocated"] == 2


class TestProposalDecline:
    def test_proposal_decline_cancels_line_and_order(self, api):
        """PRD: "Decline is the mirror: the proposal must be `PENDING`, the
        line moves `SUBSTITUTION_PENDING → CANCELLED`, the order is recomputed
        — collapsing to `CANCELLED` if every line is now cancelled, or
        returning to `PLACED` if no substitution-pending lines remain — and
        `committed_cents` is adjusted."

        Design: Corner/state_machines/proposal_decline_cancels_line_and_order
        """
        facility, _short, _sub, order, proposal = setup_pending_proposal(
            qty=2, short_price=1000, sub_price=900)
        declined = validate_success(api.decline_proposal(
            proposal["id"], _fm(facility)))
        assert declined["status"] == "DECLINED"

        line = get_only_order_line(order["id"])
        assert line["status"] == "CANCELLED"
        after_order = get_order(order["id"])
        assert after_order["status"] == "CANCELLED", (
            "Single-line order: all lines CANCELLED collapses the order")
        after_facility = validate_success(
            api.get_facility(facility["id"], ADMIN))
        assert after_facility["committed_cents"] == 0, "Was 5200"


class TestProposalExpirySweep:
    def test_substitution_proposal_expiry_sweep(self, api):
        """PRD: "Should the `FacilityManager` do nothing, the daily sweep
        expires a `PENDING` proposal once the clock is strictly past its
        `expires_at`, moving it to `EXPIRED` with exactly the same line,
        order, and ledger effects as a decline."
        PRD: "the system creates a substitution proposal in `PENDING` status
        naming the `order_line_id`, the `original_product_id`, the selector's
        `proposed_product_id`, an `expires_at` exactly 7 days out"

        Design: Corner/endpoints/substitution_proposal_expiry_sweep
        """
        facility, _short, _sub, order, proposal = setup_pending_proposal(
            qty=1, short_price=1000, sub_price=900)
        assert proposal["expires_at"].startswith("2026-08-08T00:00:00"), (
            "Created at the default clock 2026-08-01 plus exactly 7 days")

        set_clock("2026-08-09T00:00:00Z")
        summary = run_daily()
        assert proposal["id"] in summary["expired_proposal_ids"]

        after_proposal = get_proposal(proposal["id"])
        assert after_proposal["status"] == "EXPIRED"
        line = get_only_order_line(order["id"])
        assert line["status"] == "CANCELLED"
        after_order = get_order(order["id"])
        assert after_order["status"] == "CANCELLED"
        after_facility = validate_success(
            api.get_facility(facility["id"], ADMIN))
        assert after_facility["committed_cents"] == 0, (
            "The 5200 commitment is released")
