"""Return authorizations, chargeback variants, and the hold cascade (PRD §3.6, §2.6).

Covers the RMA state gates and quantity caps, the current-rate provisional vs
original-rate final chargeback split, pinned per-line rounding, the zero-drift
round trip, and the entry -> balance -> COMMISSION_HOLD cascade.
"""
from test_helpers import (
    ApiErrorId,
    approve_rma,
    checkout_sample,
    create_customer,
    create_invoiced_order,
    create_order,
    create_principal,
    create_rate_schedule,
    create_agreement,
    activate_agreement,
    create_rep,
    create_rma,
    create_sample_unit,
    get_checkout,
    get_principal,
    get_rep,
    get_rma,
    get_sample_unit,
    invoice_order,
    list_entries,
    make_order_line,
    make_principal_ops_headers,
    order_line,
    reject_rma,
    set_clock,
    setup_base_scenario,
    ship_order,
    sum_entry_amounts,
    validate_error,
    TEST_USERS,
)


def _admin():
    return TEST_USERS["agency_admin_headers"]


class TestRmaCreationGates:
    def test_rma_create_on_placed_order_rejected(self, api):
        """PRD §3.6: "The order must already be `SHIPPED`, `INVOICED`, or `PAID` — an
        attempt against an order in any other state fails with
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/validations/rma_create_on_placed_order_rejected
        """
        base = setup_base_scenario(
            agreement_territories=["CA", "OR", "WA"], reps=(("R1", ["CA", "OR", "WA"]),),
        )
        order = create_order(
            base["customer"]["id"], base["principal"]["id"], "PO-1",
            lines=[make_order_line(quantity=5, unit_price_cents=5000)],
        )
        resp = api.create_rma(
            {"order_id": order["id"], "lines": [{"line_id": "L1", "qty": 1}]}, _admin(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_rma_qty_exceeds_shipped_and_cumulative_pending(self, api):
        """PRD §3.6: "Per line, the requested `qty` may not exceed what was shipped
        minus what has already been returned minus the quantities already sitting on
        open (requested or approved) return authorizations for that line; an
        over-claim fails with `ERR_RETURN_QTY_EXCEEDS_SHIPPED`."

        Design: Corner/validations/rma_qty_exceeds_shipped_and_cumulative_pending
        """
        base = setup_base_scenario(
            agreement_territories=["CA", "OR", "WA"], reps=(("R1", ["CA", "OR", "WA"]),),
        )
        order = create_order(
            base["customer"]["id"], base["principal"]["id"], "PO-1",
            lines=[make_order_line(quantity=100, unit_price_cents=5000)],
        )
        ship_order(order["id"], base["principal"]["id"])

        over = api.create_rma(
            {"order_id": order["id"], "lines": [{"line_id": "L1", "qty": 150}]}, _admin(),
        )
        validate_error(over, ApiErrorId.ERR_RETURN_QTY_EXCEEDS_SHIPPED)

        pending = create_rma(order["id"], [{"line_id": "L1", "qty": 60}])
        assert pending["status"] == "REQUESTED"

        still_over = api.create_rma(
            {"order_id": order["id"], "lines": [{"line_id": "L1", "qty": 50}]}, _admin(),
        )
        # 60 pending + 50 requested exceeds the 100 shipped.
        validate_error(still_over, ApiErrorId.ERR_RETURN_QTY_EXCEEDS_SHIPPED)

        # Boundary is inclusive: exactly the remaining 40 is accepted.
        edge = create_rma(order["id"], [{"line_id": "L1", "qty": 40}])
        assert edge["status"] == "REQUESTED"


class TestRmaTerminalStates:
    def test_rma_rejected_then_receive_rejected(self, api):
        """PRD §3.6: "Termination is final in both directions: `REJECTED`, `CLOSED`,
        and `EXPIRED` are all terminal." and "Rejection moves the authorization from
        `REQUESTED` to `REJECTED` with no further effect."

        Design: Corner/state_machines/rma_rejected_then_receive_rejected
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
        principal = base["principal"]
        r1 = base["reps"][0]
        order = create_invoiced_order(
            base["customer"]["id"], principal["id"], "PO-1",
            lines=[make_order_line(quantity=100, unit_price_cents=5000)],
        )
        rma = create_rma(order["id"], [{"line_id": "L1", "qty": 10}])
        reject_rma(rma["id"], principal["id"])

        resp = api.receive_rma(rma["id"], make_principal_ops_headers(principal["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        chargebacks = list_entries(order_id=order["id"], entry_type="CHARGEBACK")
        assert chargebacks == [], "a rejected RMA posts no chargeback entries"
        # 100 x 5000c at 1000bp = 50,000c; the spec rep's 6000bp share is 30,000c.
        assert get_rep(r1["id"])["commission_balance_cents"] == 30000

    def test_rma_expiry_after_receipt_window(self, api):
        """PRD §3.6: "If the clock reaches forty-five days after `approved_at` without
        a receipt, the sweep moves the authorization from `APPROVED` to `EXPIRED`; the
        provisional estimate is discarded back to null and no quantities change."

        Design: Corner/validations/rma_expiry_after_receipt_window
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"],
                                   reps=(("R1", ["CA", "OR", "WA"]),))
        principal = base["principal"]
        order = create_invoiced_order(
            base["customer"]["id"], principal["id"], "PO-1",
            lines=[make_order_line(quantity=100, unit_price_cents=5000)],
        )
        rma = create_rma(order["id"], [{"line_id": "L1", "qty": 10}])
        approve_rma(rma["id"], principal["id"])

        # Approved at the 2026-08-01 default clock; +45 days is 2026-09-15 exactly.
        set_clock("2026-09-15T00:00:00Z")
        expired = get_rma(rma["id"])
        assert expired["status"] == "EXPIRED"
        assert expired["provisional_chargeback_cents"] is None

        resp = api.receive_rma(rma["id"], make_principal_ops_headers(principal["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert list_entries(order_id=order["id"], entry_type="CHARGEBACK") == []


class TestChargebackRateVariants:
    def _setup_superseded_schedule_rma(self, api):
        """Invoice under the 1000bp schedule, supersede with a 500bp CONNECTORS
        schedule, then open and approve an RMA for 10 units of L1."""
        base = setup_base_scenario()
        principal = base["principal"]
        order = create_invoiced_order(
            base["customer"]["id"], principal["id"], "PO-1",
            lines=[
                make_order_line("L1", "CONNECTORS", 100, 5000),
                make_order_line("L2", "CABLES", 50, 2000),
            ],
        )
        current = get_principal(principal["id"])
        create_rate_schedule(
            principal["id"], current["version"],
            family_rates=[
                {"family_code": "CONNECTORS", "base_rate_bp": 500},
                {"family_code": "CABLES", "base_rate_bp": 800},
            ],
        )
        rma = create_rma(order["id"], [{"line_id": "L1", "qty": 10}])
        return base, order, rma

    def test_provisional_current_rate_vs_final_original_rate(self, api):
        """PRD §3.6: "Approval moves it to `APPROVED`, stamps `approved_at`, and
        computes a `provisional_chargeback_cents` estimate using the current-rate
        variant of the chargeback calculation: each returned line is priced at the
        rate its family would earn right now — the currently active schedule's base
        rate scaled by the current attainment tier multiplier, with no registration
        bonus — regardless of what rate was actually applied at invoice." and "The
        owning operator's receipt confirmation moves the authorization from `APPROVED`
        to `CLOSED`, stamps `received_at`, and computes `final_chargeback_cents` with
        the original-rate variant: each returned line is priced at the
        `applied_rate_bp` stored on that line at invoice time."

        Design: Difficulty/dual_variant_calc/chargeback_original_vs_current_rate
        """
        base, order, rma = self._setup_superseded_schedule_rma(api)
        principal = base["principal"]

        approved = approve_rma(rma["id"], principal["id"])
        # CURRENT_RATE: 10 x 5000c x 500bp / 10000 = 2500c (tier 0 at 600bp attainment).
        assert approved["provisional_chargeback_cents"] == 2500

        received = api.receive_rma(
            rma["id"], make_principal_ops_headers(principal["id"]),
        ).json()["data"]
        # ORIGINAL_RATE: 10 x 5000c x stored 1000bp / 10000 = 5000c.
        assert received["final_chargeback_cents"] == 5000
        assert received["status"] == "CLOSED"
        assert received["final_chargeback_cents"] != approved["provisional_chargeback_cents"]

    def test_final_chargeback_entries_and_balances(self, api):
        """PRD §3.6: "One `CHARGEBACK` ledger entry posts per rep per order, dividing
        the final chargeback across the order's locked split rows exactly as the
        accrual was allocated; each entry's `business_date` is the receipt time." and
        "Finally, the principal's `credited_ytd_sales_cents` is reduced by the value
        of the returned goods — per line, the received quantity multiplied by the
        line's `unit_price_cents` — and is floored at zero so returns can never drag
        the year-to-date pool negative."

        Design: Difficulty/dual_variant_calc/chargeback_original_vs_current_rate
        """
        base, order, rma = self._setup_superseded_schedule_rma(api)
        principal = base["principal"]
        r1, r2 = base["reps"]
        approve_rma(rma["id"], principal["id"])
        api.receive_rma(rma["id"], make_principal_ops_headers(principal["id"]))

        chargebacks = list_entries(order_id=order["id"], entry_type="CHARGEBACK")
        by_rep = {e["rep_id"]: e["amount_cents"] for e in chargebacks}
        # Final 5000c split 6000/4000 like the accrual: -3000 / -2000.
        assert by_rep == {r1["id"]: -3000, r2["id"]: -2000}
        # Accruals were +34,800 / +23,200 (50,000 + 8,000 at 60/40).
        assert get_rep(r1["id"])["commission_balance_cents"] == 31800
        assert get_rep(r2["id"])["commission_balance_cents"] == 21200
        # 600,000c invoiced less 10 x 5000c returned.
        assert get_principal(principal["id"])["credited_ytd_sales_cents"] == 550000


class TestChargebackRounding:
    def _setup_two_line_rma(self, api):
        base = setup_base_scenario()
        principal = base["principal"]
        order = create_invoiced_order(
            base["customer"]["id"], principal["id"], "PO-R",
            lines=[
                make_order_line("L1", "CONNECTORS", 3, 1151),
                make_order_line("L2", "CONNECTORS", 7, 929),
            ],
        )
        rma = create_rma(order["id"], [{"line_id": "L1", "qty": 3},
                                       {"line_id": "L2", "qty": 7}])
        return base, order, rma

    def test_chargeback_rounds_each_line_before_summing(self, api):
        """PRD §3.6: "Rounding order is pinned in both variants: each line's amount —
        its returned quantity multiplied by the line's `unit_price_cents` and scaled
        by the applicable rate in basis points — is first rounded half up to whole
        cents, and only then are the per-line amounts summed; the system never sums
        first and rounds once." Per-line: round_half_up(345.3)=345 and
        round_half_up(650.3)=650, summing to 995 — never the 996 that a
        sum-then-round of 995.6 would produce.

        Design: Difficulty/combinatorial_formula/chargeback_per_line_round_then_sum
        """
        base, order, rma = self._setup_two_line_rma(api)
        principal = base["principal"]
        approved = approve_rma(rma["id"], principal["id"])
        assert approved["provisional_chargeback_cents"] == 995
        received = api.receive_rma(
            rma["id"], make_principal_ops_headers(principal["id"]),
        ).json()["data"]
        assert received["final_chargeback_cents"] == 995

    def test_invoice_commission_matches_per_line_rounding(self, api):
        """PRD §3.5: "the line's commission is the net amount scaled by the effective
        rate and divided by 10,000, rounded half up to whole cents." The same per-line
        rounding prices the invoice: 345c and 650c. PRD §3.6: receipt divides "the
        final chargeback across the order's locked split rows exactly as the accrual
        was allocated" — here 207+390 = 597c and 138+260 = 398c against the 60/40
        split rows.

        Design: Difficulty/combinatorial_formula/chargeback_per_line_round_then_sum
        """
        base, order, rma = self._setup_two_line_rma(api)
        principal = base["principal"]
        r1, r2 = base["reps"]
        invoiced = api.get_order(order["id"], _admin()).json()["data"]
        assert order_line(invoiced, "L1")["commission_cents"] == 345
        assert order_line(invoiced, "L2")["commission_cents"] == 650

        approve_rma(rma["id"], principal["id"])
        api.receive_rma(rma["id"], make_principal_ops_headers(principal["id"]))
        cb = list_entries(order_id=order["id"], entry_type="CHARGEBACK")
        assert sum_entry_amounts([e for e in cb if e["rep_id"] == r1["id"]]) == -597
        assert sum_entry_amounts([e for e in cb if e["rep_id"] == r2["id"]]) == -398


class TestRoundTripInvariant:
    def _setup_full_return(self, api):
        base = setup_base_scenario()
        principal = base["principal"]
        order = create_invoiced_order(
            base["customer"]["id"], principal["id"], "PO-1",
            lines=[
                make_order_line("L1", "CONNECTORS", 100, 5000),
                make_order_line("L2", "CABLES", 50, 2000),
            ],
        )
        rma = create_rma(order["id"], [{"line_id": "L1", "qty": 100},
                                       {"line_id": "L2", "qty": 50}])
        approve_rma(rma["id"], principal["id"])
        return base, order, rma

    def test_full_return_restores_zero_balances(self, api):
        """PRD §2.6: "A rep's `commission_balance_cents` is the algebraic sum of every
        ledger entry posted for that rep: accruals and positive adjustments add,
        chargebacks, payments, charges, recoveries, and negative adjustments
        subtract." A full return at the stored original rates is the exact
        compensation of the invoice accruals, returning every balance to the
        pre-order baseline of zero.

        Design: Difficulty/compensating_invariant/commission_ledger_round_trip_zero_drift
        """
        base, order, rma = self._setup_full_return(api)
        principal = base["principal"]
        r1, r2 = base["reps"]
        received = api.receive_rma(
            rma["id"], make_principal_ops_headers(principal["id"]),
        ).json()["data"]
        # L1 50,000c + L2 8,000c at the stored 1000bp/800bp rates.
        assert received["final_chargeback_cents"] == 58000
        assert get_rep(r1["id"])["commission_balance_cents"] == 0
        assert get_rep(r2["id"])["commission_balance_cents"] == 0

    def test_full_return_entries_net_to_zero_per_rep(self, api):
        """PRD §2.6: "A rep's `commission_balance_cents` is the algebraic sum of every
        ledger entry posted for that rep". PRD §3.6: "One `CHARGEBACK` ledger entry
        posts per rep per order, dividing the final chargeback across the order's
        locked split rows exactly as the accrual was allocated". Per rep, ACCRUAL +
        CHARGEBACK against the same order net to exactly zero.

        Design: Difficulty/compensating_invariant/commission_ledger_round_trip_zero_drift
        """
        base, order, rma = self._setup_full_return(api)
        principal = base["principal"]
        r1, r2 = base["reps"]
        api.receive_rma(rma["id"], make_principal_ops_headers(principal["id"]))

        entries = list_entries(order_id=order["id"])
        per_rep = {}
        for e in entries:
            per_rep[e["rep_id"]] = per_rep.get(e["rep_id"], 0) + e["amount_cents"]
        assert per_rep == {r1["id"]: 0, r2["id"]: 0}, (
            f"forward + compensating pair must net to zero per rep, got {per_rep}"
        )


class TestReceiptToHoldCascade:
    def _setup_hold_scenario(self, api):
        """Rep RH with 100,000c accrued, pushed to 15,000c by an overdue sample
        charge, with a full-quantity RMA approved and ready to receive."""
        principal = create_principal(name="P2", annual_quota_cents=100_000_000)
        agreement = create_agreement(principal["id"], territory_codes=["NV"])
        activate_agreement(agreement["id"])
        create_rate_schedule(
            principal["id"], principal["version"],
            family_rates=[{"family_code": "CONNECTORS", "base_rate_bp": 1000}],
            attainment_tiers=[{"min_attainment_bp": 0, "multiplier_bp": 10000}],
            registration_bonus_bp=0,
        )
        rep = create_rep("RH", ["NV"])
        customer = create_customer(name="CH", spec_territory_code="NV",
                                   ship_to_territory_code="NV")
        order = create_invoiced_order(
            customer["id"], principal["id"], "PO-H",
            lines=[make_order_line(quantity=100, unit_price_cents=10000)],
        )
        unit = create_sample_unit(principal["id"], serial_number="S-1",
                                  value_cents=100_000)
        checkout = checkout_sample(unit["id"], rep["id"])
        # Due 2026-08-31; the 2026-09-01 sweep charges one started month (8500bp).
        set_clock("2026-09-01T00:00:00Z")
        rma = create_rma(order["id"], [{"line_id": "L1", "qty": 100}])
        approve_rma(rma["id"], principal["id"])
        return principal, rep, order, checkout, rma

    def test_overdue_sample_charge_lowers_balance(self, api):
        """PRD §3.8: "A checkout left open past its `due_at` does not linger: the
        clock sweep moves it from `OPEN` to `CHARGED`, posts a `SAMPLE_CHARGE` entry
        for the full depreciated value as of the sweep date, writes the unit off to
        `WRITTEN_OFF`, and cascades into the rep's balance recompute and hold check."
        and "The unit loses fifteen percent of list per started month, and the
        remaining factor is never allowed below twenty percent of list." 31 days is
        one started month: 85% of 100,000c = 85,000c.

        Design: Difficulty/transitive_cascade/rma_receipt_chargeback_balance_hold_cascade
        """
        principal, rep, order, checkout, rma = self._setup_hold_scenario(api)
        charged = get_checkout(checkout["id"])
        assert charged["status"] == "CHARGED"
        assert charged["charge_cents"] == 85000
        assert get_sample_unit(charged["sample_unit_id"])["status"] == "WRITTEN_OFF"
        # 100,000c accrual - 85,000c sample charge = 15,000c: still above the floor.
        assert get_rep(rep["id"])["commission_balance_cents"] == 15000
        assert get_rep(rep["id"])["status"] == "ACTIVE"

    def test_rma_receipt_drives_rep_into_commission_hold(self, api):
        """PRD §3.6: "Every touched rep's `commission_balance_cents` is recomputed as
        the sum of its entries, and any rep whose balance falls below the
        negative-50,000-cent floor moves from `ACTIVE` to `COMMISSION_HOLD`." The
        full-quantity receipt charges back 100,000c at the stored 1000bp rate, driving
        the 15,000c balance to -85,000c — below the floor.

        Design: Difficulty/transitive_cascade/rma_receipt_chargeback_balance_hold_cascade
        """
        principal, rep, order, checkout, rma = self._setup_hold_scenario(api)
        received = api.receive_rma(
            rma["id"], make_principal_ops_headers(principal["id"]),
        ).json()["data"]
        # Schedule unchanged: ORIGINAL_RATE == 1000bp -> 100 x 10000c x 1000bp.
        assert received["final_chargeback_cents"] == 100000

        cb = list_entries(order_id=order["id"], entry_type="CHARGEBACK")
        assert len(cb) == 1 and cb[0]["rep_id"] == rep["id"]
        assert cb[0]["amount_cents"] == -100000

        after = get_rep(rep["id"])
        assert after["commission_balance_cents"] == -85000
        assert after["status"] == "COMMISSION_HOLD"
