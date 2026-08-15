"""Quoting, confirmation credit gate, OCC superseding writes, and customer
credit-status behavior."""
import pytest

from test_helpers import (
    ApiErrorId,
    CANONICAL_QUOTE_TOTAL,
    assert_press_order,
    create_customer,
    create_order,
    create_press_line,
    create_release,
    make_customer_headers,
    quote_order,
    set_clock,
    setup_world,
    suspend_customer,
    reinstate_customer,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BILLING, CSR


class TestQuotePricing:
    def test_quote_prices_canonical_black_order(self, api):
        """PRD §3.3: "The pressing component, `quote_pressing_cents`, prices the
        ordered quantity on marginal tiers: the first 299 units at 320 cents
        each, units 300 through 999 (the next 700 units) at 275 each, units
        1000 through 4999 (the next 4000) at 240 each, and every unit from 5000
        onward at 210."
        PRD §3.3: "The `quote_subtotal_cents` is the sum of those four
        components; the `quote_discount_cents` is the subtotal multiplied by
        the snapshotted tier percentage, rounded half-up to whole cents; and
        the `quote_total_cents` is the subtotal minus the discount."

        Design: Difficulty/dual_variant_calc/quote_vs_final_invoice_divergence
        """
        world = setup_world(with_line=False, with_bath=False)
        order = create_order(world["release"]["id"], quantity_ordered=1000)
        quoted = quote_order(order)
        assert_press_order(quoted)
        assert quoted["production_status"] == "QUOTED"
        # 299*320 + 700*275 + 1*240 = 288420
        assert quoted["quote_pressing_cents"] == 288420
        # weight surcharge 1000 * 25 (180g)
        assert quoted["quote_surcharge_cents"] == 25000
        # 2*17500 lacquer + ceil(1000/1000)*2*30000 stampers
        assert quoted["quote_tooling_cents"] == 95000
        assert quoted["quote_setup_cents"] == 40000
        assert quoted["quote_subtotal_cents"] == 448420
        assert quoted["quote_discount_cents"] == 0  # STANDARD tier
        assert quoted["quote_total_cents"] == CANONICAL_QUOTE_TOTAL

    def test_quote_variant_floor_and_setup_components(self, api):
        """PRD §3.3: "each variant line contributes the greater of its quantity
        times its per-unit color surcharge and a 5000-cent minimum — except
        `BLACK`, whose per-unit surcharge is zero and which never incurs the
        minimum — with per-unit surcharges of 0 for `BLACK`, 35 for
        `SOLID_COLOR`, 55 for `SPLATTER`, 65 for `MARBLED`, and 120 for
        `PICTURE_DISC`"
        PRD §3.3: "The setup component, `quote_setup_cents`, is a flat 40000
        cents per order plus 15000 cents for each variant whose configuration
        is not `BLACK`."

        Design: Difficulty/combinatorial_formula/quote_tier_floor_and_status_branch
        """
        world = setup_world(customer_over={"discount_tier": "SILVER"},
                            with_line=False, with_bath=False)
        order = create_order(
            world["release"]["id"], quantity_ordered=1000,
            variants=[
                {"color_config": "SOLID_COLOR", "quantity": 100},
                {"color_config": "BLACK", "quantity": 900},
            ],
        )
        quoted = quote_order(order)
        # max(100*35, 5000) = 5000 (floor engages) + 1000*25 weight = 30000
        assert quoted["quote_surcharge_cents"] == 30000
        # 40000 + 15000 * 1 non-BLACK variant
        assert quoted["quote_setup_cents"] == 55000
        assert quoted["quote_subtotal_cents"] == 468420
        # SILVER 3%: round_half_up(468420 * 0.03) = round_half_up(14052.6)
        assert quoted["quote_discount_cents"] == 14053
        assert quoted["quote_total_cents"] == 454367

    def test_quote_marginal_tier_straddle(self, api):
        """PRD §3.3: "The pressing component, `quote_pressing_cents`, prices the
        ordered quantity on marginal tiers: the first 299 units at 320 cents
        each, units 300 through 999 (the next 700 units) at 275 each, units
        1000 through 4999 (the next 4000) at 240 each, and every unit from 5000
        onward at 210."
        PRD §3.3: "The tooling component, `quote_tooling_cents`, is 17500 cents
        per side for lacquer cutting plus one stamper fee of 30000 cents per
        side for every 1000-unit stamper life the ordered quantity requires,
        with the stamper count rounded up to a whole stamper."

        Design: Difficulty/combinatorial_formula/quote_tier_floor_and_status_branch
        """
        world = setup_world(customer_over={"discount_tier": "SILVER"},
                            release_over={"weight_gram": 140,
                                          "release_date": "2027-02-01"},
                            with_line=False, with_bath=False)
        order = create_order(
            world["release"]["id"], quantity_ordered=5200,
            variants=[
                {"color_config": "SPLATTER", "quantity": 200},
                {"color_config": "BLACK", "quantity": 5000},
            ],
        )
        quoted = quote_order(order)
        # 299*320 + 700*275 + 4000*240 + 201*210 = 1290390
        assert quoted["quote_pressing_cents"] == 1290390
        # 2*17500 + ceil(5200/1000)*2*30000 = 35000 + 360000
        assert quoted["quote_tooling_cents"] == 395000
        # subtotal 1751390; discount round_half_up(1751390*0.03) = 52542
        assert quoted["quote_discount_cents"] == 52542
        assert quoted["quote_total_cents"] == 1698848


class TestOccRequote:
    def test_requote_supersede_then_stale_rejected(self, api):
        """PRD §2.7: "Re-quoting a press order requires
        `expected_press_order_version` carrying the order's current `version`.
        A re-quote legitimately supersedes the prior quote while the order
        remains `QUOTED`, so a second sequential re-quote faces no state
        precondition; instead, if another writer has advanced the order's
        `version` since the client last read it, the re-quote is rejected with
        `ERR_STALE_VERSION`, preventing the client from silently overwriting a
        quote it never observed."
        PRD §3.3: "Re-quoting a `QUOTED` order recomputes every component and
        the snapshot, superseding the prior quote in place (`QUOTED` →
        `QUOTED`), and every quote or re-quote increments the order's
        `version`."

        Design: Corner/cross_cutting_layers/occ_requote_stale_version
        """
        world = setup_world(with_line=False, with_bath=False)
        order = create_order(world["release"]["id"], quantity_ordered=1000)
        quoted = quote_order(order)

        # First re-quote with the current version: legitimate supersede.
        r1 = api.quote_press_order(
            order["id"], {"expected_press_order_version": quoted["version"]}, CSR
        )
        requoted = validate_success(r1, 200)
        assert requoted["production_status"] == "QUOTED"
        assert requoted["version"] == quoted["version"] + 1, (
            "each quote or re-quote must increment the order's version by exactly one"
        )

        # Replaying the now-stale captured version is rejected.
        r2 = api.quote_press_order(
            order["id"], {"expected_press_order_version": quoted["version"]}, CSR
        )
        validate_error(r2, ApiErrorId.ERR_STALE_VERSION)


class TestCreditBoundary:
    def _setup_quoted_order(self, credit_limit: int):
        world = setup_world(customer_over={"credit_limit_cents": credit_limit},
                            with_line=False, with_bath=False)
        order = create_order(world["release"]["id"], quantity_ordered=1000)
        quoted = quote_order(order)
        assert quoted["quote_total_cents"] == 448420
        return world, quoted

    def test_credit_limit_equal_to_quote_passes(self, api):
        """PRD §3.3: "the customer's outstanding balance — the sum, across the
        customer's invoices in `ISSUED` or `PARTIALLY_PAID` status, of
        `net_cents` less `paid_cents` less `credited_cents` — plus this order's
        `quote_total_cents` may not exceed `credit_limit_cents`, with equality
        permitted; a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/credit_limit_inclusive_boundary
        """
        world, quoted = self._setup_quoted_order(448420)
        resp = api.confirm_press_order(
            quoted["id"],
            {"expected_press_order_version": quoted["version"]},
            make_customer_headers(world["customer"]["id"]),
        )
        data = validate_success(resp, 200)
        assert data["production_status"] == "CONFIRMED", (
            "credit limit exactly equal to quote_total must confirm (inclusive boundary)"
        )

    def test_credit_limit_one_cent_short_rejected(self, api):
        """PRD §3.3: "the customer's outstanding balance — the sum, across the
        customer's invoices in `ISSUED` or `PARTIALLY_PAID` status, of
        `net_cents` less `paid_cents` less `credited_cents` — plus this order's
        `quote_total_cents` may not exceed `credit_limit_cents`, with equality
        permitted; a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/credit_limit_inclusive_boundary
        """
        world, quoted = self._setup_quoted_order(448419)
        resp = api.confirm_press_order(
            quoted["id"],
            {"expected_press_order_version": quoted["version"]},
            make_customer_headers(world["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


class TestValidationPriority:
    def test_confirm_draft_order_state_beats_credit(self, api):
        """PRD §2.9: "When several checks could reject the same request, the
        system evaluates them in a fixed priority order, and the first failure
        determines the error returned."
        PRD §2.9: "5. State preconditions — the target resource is not in the
        exact from-state the requested transition requires, rejected with
        `ERR_ORDER_INVALID_STATE`"
        PRD §2.9: "11. Credit availability at confirmation — rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED`."
        PRD §2.9: "the ordering above is normative, not illustrative."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
        """
        world = setup_world(customer_over={"credit_limit_cents": 1},
                            with_line=False, with_bath=False)
        order = create_order(world["release"]["id"], quantity_ordered=1000)
        # DRAFT order: confirm violates the state gate; a 1-cent limit would
        # also breach credit once priced. State (priority 5) must win.
        resp = api.confirm_press_order(
            order["id"],
            {"expected_press_order_version": order["version"]},
            make_customer_headers(world["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)

    def test_confirm_draft_order_state_gate_isolated(self, api):
        """PRD §3.3: "the order must be `QUOTED` (otherwise
        `ERR_ORDER_INVALID_STATE`)"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
        """
        world = setup_world(with_line=False, with_bath=False)
        order = create_order(world["release"]["id"], quantity_ordered=1000)
        resp = api.confirm_press_order(
            order["id"],
            {"expected_press_order_version": order["version"]},
            make_customer_headers(world["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)

    def test_variant_minimum_beats_lead_time(self, api):
        """PRD §2.9: "8. Order composition — order minimum, variant sum,
        per-variant minimums, and code uniqueness (`ERR_ORDER_BELOW_MINIMUM`,
        `ERR_VARIANT_SUM_MISMATCH`, `ERR_VARIANT_BELOW_MINIMUM`,
        `ERR_DUPLICATE_CODE`), applying to order creation, quoting, press-line
        registration, plating-bath registration, and release creation."
        PRD §2.9: "10. Temporal rules — lead time at order creation and
        press-start date gating (`ERR_LEAD_TIME_VIOLATION`,
        `ERR_PRESS_DATE_NOT_REACHED`), applying to order creation and
        production events."
        PRD §2.9: "the ordering above is normative, not illustrative."

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_create
        """
        world = setup_world(with_line=False, with_bath=False, clock="2026-08-01T00:00:00Z")
        payload = {
            "release_id": world["release"]["id"],
            "quantity_ordered": 200,
            "sides": 2,
            "plating_route": "TWO_STEP",
            "variants": [
                {"color_config": "SPLATTER", "quantity": 99},
                {"color_config": "BLACK", "quantity": 101},
            ],
            "requested_completion_date": "2026-08-10",
        }
        resp = api.create_press_order(payload, CSR)
        # Both priority-8 (variant minimum) and priority-10 (lead time) fail;
        # the composition error must surface.
        validate_error(resp, ApiErrorId.ERR_VARIANT_BELOW_MINIMUM)

    def test_variant_minimum_isolated_without_temporal_violation(self, api):
        """PRD §3.2: "each variant must meet its configuration minimum — a
        single unit suffices for `BLACK`, while `SOLID_COLOR`, `SPLATTER`, and
        `MARBLED` each require at least 100 and `PICTURE_DISC` at least 200
        (`ERR_VARIANT_BELOW_MINIMUM`)"

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_create
        """
        world = setup_world(with_line=False, with_bath=False, clock="2026-08-01T00:00:00Z")
        payload = {
            "release_id": world["release"]["id"],
            "quantity_ordered": 100,
            "sides": 2,
            "plating_route": "TWO_STEP",
            "variants": [
                {"color_config": "SPLATTER", "quantity": 99},
                {"color_config": "BLACK", "quantity": 1},
            ],
            # no requested_completion_date: only the composition rule can fail
        }
        resp = api.create_press_order(payload, CSR)
        validate_error(resp, ApiErrorId.ERR_VARIANT_BELOW_MINIMUM)


class TestSuspendedCustomer:
    def test_suspended_customer_gates_and_quote_snapshot(self, api):
        """PRD §3.1: "a quote snapshots the customer's tier percentage at quote
        time (zero if the customer is `SUSPENDED` then)"
        PRD §3.3: "the customer must be `ACTIVE` (otherwise
        `ERR_CUSTOMER_SUSPENDED`)"

        Design: Corner/validations/suspended_customer_gates_and_quote_snapshot
        """
        world = setup_world(customer_over={"discount_tier": "GOLD"},
                            with_line=False, with_bath=False)
        cust = world["customer"]

        order1 = create_order(world["release"]["id"], quantity_ordered=1000)
        quoted1 = quote_order(order1)
        assert quoted1["discount_pct_snapshot"] == pytest.approx(0.05)
        assert quoted1["quote_total_cents"] == 425999  # 448420 - 22421

        suspend_customer(cust["id"])

        # Confirm is blocked while the customer is suspended.
        r_conf = api.confirm_press_order(
            quoted1["id"],
            {"expected_press_order_version": quoted1["version"]},
            make_customer_headers(cust["id"]),
        )
        validate_error(r_conf, ApiErrorId.ERR_CUSTOMER_SUSPENDED)

        # A quote taken while SUSPENDED snapshots a zero discount.
        order2 = create_order(world["release"]["id"], quantity_ordered=1000)
        quoted2 = quote_order(order2)
        assert quoted2["discount_pct_snapshot"] == 0
        assert quoted2["quote_total_cents"] == 448420

        reinstate_customer(cust["id"])
        r_conf2 = api.confirm_press_order(
            quoted1["id"],
            {"expected_press_order_version": quoted1["version"]},
            make_customer_headers(cust["id"]),
        )
        data = validate_success(r_conf2, 200)
        assert data["production_status"] == "CONFIRMED"


class TestOccCreditRevision:
    def test_occ_credit_revision_stale(self, api):
        """PRD §2.7: "Revising a customer's credit limit requires
        `expected_customer_version` matching the customer's current `version`.
        Such revisions supersede the prior limit and are always permitted for
        an existing customer; a revision carrying a stale
        `expected_customer_version` — the version having advanced through prior
        revisions or credit-status transitions — is rejected with
        `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_layers/occ_credit_revision_stale
        """
        set_clock()
        cust = create_customer(name="OC3", contact_email="oc3@x.com",
                               credit_limit_cents=1000000)

        r1 = api.revise_credit_limit(
            cust["id"],
            {"new_credit_limit_cents": 2000000,
             "expected_customer_version": cust["version"]},
            CSR,
        )
        revised = validate_success(r1, 200)
        assert revised["credit_limit_cents"] == 2000000
        assert revised["version"] == cust["version"] + 1

        # Replay of the creation version is stale.
        r2 = api.revise_credit_limit(
            cust["id"],
            {"new_credit_limit_cents": 3000000,
             "expected_customer_version": cust["version"]},
            CSR,
        )
        validate_error(r2, ApiErrorId.ERR_STALE_VERSION)

        # A credit-status flip also advances the version; the pre-suspend
        # version is stale afterwards.
        suspend_customer(cust["id"])
        r3 = api.revise_credit_limit(
            cust["id"],
            {"new_credit_limit_cents": 3000000,
             "expected_customer_version": revised["version"]},
            CSR,
        )
        validate_error(r3, ApiErrorId.ERR_STALE_VERSION)


class TestImmediateConsistency:
    def test_immediate_visibility_after_mutation(self, api):
        """PRD §3.1: "passing `action` as `SUSPEND` moves an `ACTIVE` customer
        to `SUSPENDED`, and `REINSTATE` returns it to `ACTIVE`; each flip
        increments the customer's `version`."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        set_clock()
        cust = create_customer(name="CM1", contact_email="cm1@x.com",
                               credit_limit_cents=1000)
        resp = api.set_credit_status(cust["id"], {"action": "SUSPEND"}, BILLING)
        mutated = validate_success(resp, 200)
        assert mutated["status"] == "SUSPENDED", (
            "the mutation response itself must already show SUSPENDED"
        )
        assert mutated["version"] == cust["version"] + 1

        got = validate_success(api.get_customer(cust["id"], CSR), 200)
        assert got["status"] == "SUSPENDED", (
            "a subsequent read must reflect the mutation with no reconciliation delay"
        )
