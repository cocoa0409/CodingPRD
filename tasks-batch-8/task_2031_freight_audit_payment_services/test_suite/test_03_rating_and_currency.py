"""Contract rating variants and currency conversion.

Covers PRD §3.4 line rating (tier selection, minimum charge, fuel surcharge,
accessorial flat-vs-cap minimum) and rating policies, plus PRD §3.7 FX rate
resolution, the invoice-date vs payment-date variants, and the pinned
per-line-round-then-sum order for home totals.
"""
from test_helpers import (
    FINANCE,
    ApiErrorId,
    activate_contract,
    add_run_item,
    audit_invoice_to_cleared,
    build_eur_invoice,
    capture_invoice,
    create_active_client,
    create_contract,
    create_fx_rate,
    create_invoice,
    create_payment_run,
    create_shipment,
    find_line,
    rate_invoice,
    set_clock,
    setup_eur_fx_chain,
    setup_standard_chain,
    validate_error,
    validate_success,
)


def _c1_lane_two_breaks():
    return {
        "origin_country": "US",
        "dest_country": "CA",
        "mode": "LTL",
        "weight_breaks": [
            {"min_kg": 0, "rate_per_kg_minor": 150},
            {"min_kg": 1000, "rate_per_kg_minor": 120},
        ],
        "fuel_surcharge_pct_bp": 1000,
        "accessorials": [{"code": "LIFTGATE", "flat_minor": 5000, "cap_pct_bp": 2000}],
        "minimum_charge_minor": 20000,
    }


def _c2_lane():
    return {
        "origin_country": "US",
        "dest_country": "CA",
        "mode": "LTL",
        "weight_breaks": [{"min_kg": 0, "rate_per_kg_minor": 100}],
        "fuel_surcharge_pct_bp": 1000,
        "accessorials": [{"code": "LIFTGATE", "flat_minor": 5000, "cap_pct_bp": 2000}],
        "minimum_charge_minor": 20000,
    }


class TestRatingPolicyVariants:
    """Two identical 87500-billed LTL invoices over identical 500 kg fixtures;
    the carrier's C1 (150/kg, window from 2026-08-01) is superseded by C2
    (100/kg, window from 2026-08-10)."""

    def _setup(self, api):
        chain = setup_standard_chain(
            client_overrides={
                "audit_tolerance_minor": 500,
                "audit_tolerance_pct_bp": 200,
                "dispute_window_days": 30,
            },
            lanes=[_c1_lane_two_breaks()],
        )
        carrier_id = chain["carrier"]["id"]
        client_id = chain["client"]["id"]
        c2 = create_contract(
            carrier_id,
            lanes=[_c2_lane()],
            name="C2",
            effective_from="2026-08-10",
            effective_to="2026-12-31",
            supersedes_contract_id=chain["contract"]["id"],
        )
        activate_contract(c2["id"], c2["version"])
        lines = [
            {"charge_code": "BASE_FREIGHT", "billed_amount_minor": 75000},
            {"charge_code": "FUEL_SURCHARGE", "billed_amount_minor": 7500},
            {"charge_code": "LIFTGATE", "billed_amount_minor": 5000},
        ]
        invoices = {}
        for number, pro in (("INV-0120A", "PRO-1001"), ("INV-0120B", "PRO-1002")):
            shipment = create_shipment(client_id, carrier_id, pro_number=pro)
            inv = create_invoice(
                client_id,
                carrier_id,
                invoice_number=number,
                shipment_id=shipment["id"],
                invoice_date="2026-08-12",
                billed_total_minor=87500,
                lines=lines,
            )
            capture_invoice(inv["id"])
            invoices[number] = inv
        return chain, c2, invoices

    def test_ship_date_policy_selects_historical_contract(self, api):
        """PRD §3.4: "The contract selector considers the carrier's contracts in
        `ACTIVE` or `SUPERSEDED` status whose half-open window contains the
        as-of date and picks the one with the latest `activated_at`, breaking
        ties by latest `created_at`." PRD §3.4: "`SHIP_DATE`, the default when
        the request omits `policy`, rates as of the shipment's `ship_date` so
        historical contract terms apply".

        Ship date 2026-08-02 falls outside C2's window, so the SUPERSEDED C1
        rates the invoice: max(500 x 150, 20000) + 7500 fuel + 5000 LIFTGATE
        = 87500.

        Design: Difficulty/dual_variant_calc/rating_policy_ship_date_vs_invoice_date
        """
        chain, _c2, invoices = self._setup(api)
        rated = rate_invoice(invoices["INV-0120A"]["id"], policy="SHIP_DATE")
        assert rated["rated_total_minor"] == 87500
        assert rated["rated_contract_id"] == chain["contract"]["id"]

    def test_invoice_date_policy_selects_superseding_contract(self, api):
        """PRD §3.4: "`INVOICE_DATE` rates as of the invoice's `invoice_date`,
        under which a later-superseding contract with lower rates yields a
        different `rated_total_minor` for identical lines."

        Invoice date 2026-08-12 is covered by both contracts; C2 was activated
        later and wins, rating the identical lines at max(500 x 100, 20000) +
        5000 fuel + 5000 LIFTGATE = 60000 != 87500.

        Design: Difficulty/dual_variant_calc/rating_policy_ship_date_vs_invoice_date
        """
        chain, c2, invoices = self._setup(api)
        rated_a = rate_invoice(invoices["INV-0120A"]["id"], policy="SHIP_DATE")
        rated_b = rate_invoice(invoices["INV-0120B"]["id"], policy="INVOICE_DATE")
        assert rated_b["rated_total_minor"] == 60000
        assert rated_b["rated_contract_id"] == c2["id"]
        assert rated_a["rated_total_minor"] != rated_b["rated_total_minor"]


class TestAccessorialCapNestedMin:
    """One rating pass exercising both branches of the accessorial minimum:
    LIFTGATE's flat fee binds (5000 < cap 15000) while RESIDENTIAL's cap binds
    (3750 < flat 8000)."""

    def _setup(self, api):
        lane = {
            "origin_country": "US",
            "dest_country": "CA",
            "mode": "LTL",
            "weight_breaks": [{"min_kg": 0, "rate_per_kg_minor": 150}],
            "fuel_surcharge_pct_bp": 1000,
            "accessorials": [
                {"code": "LIFTGATE", "flat_minor": 5000, "cap_pct_bp": 2000},
                {"code": "RESIDENTIAL", "flat_minor": 8000, "cap_pct_bp": 500},
            ],
            "minimum_charge_minor": 20000,
        }
        chain = setup_standard_chain(lanes=[lane])
        shipment = create_shipment(
            chain["client"]["id"],
            chain["carrier"]["id"],
            accessorials_rendered=["LIFTGATE", "RESIDENTIAL"],
        )
        invoice = create_invoice(
            chain["client"]["id"],
            chain["carrier"]["id"],
            invoice_number="INV-0001",
            shipment_id=shipment["id"],
            billed_total_minor=91250,
            lines=[
                {"charge_code": "BASE_FREIGHT", "billed_amount_minor": 75000},
                {"charge_code": "FUEL_SURCHARGE", "billed_amount_minor": 7500},
                {"charge_code": "LIFTGATE", "billed_amount_minor": 5000},
                {"charge_code": "RESIDENTIAL", "billed_amount_minor": 3750},
            ],
        )
        capture_invoice(invoice["id"])
        return chain, invoice

    def test_flat_binds_for_liftgate_and_cap_binds_for_residential(self, api):
        """PRD §3.4: "otherwise the rated amount is the smaller of the
        accessorial's `flat_minor` and the rated base-freight amount multiplied
        by its `cap_pct_bp` and divided by ten thousand, rounded half up."

        With a 75000 base: LIFTGATE min(5000, 15000) = 5000 (flat binds);
        RESIDENTIAL min(8000, 3750) = 3750 (cap binds).

        Design: Difficulty/combinatorial_formula/accessorial_cap_nested_min_mode_a
        """
        _chain, invoice = self._setup(api)
        rate_invoice(invoice["id"])
        liftgate = find_line(invoice["id"], "LIFTGATE")
        residential = find_line(invoice["id"], "RESIDENTIAL")
        assert liftgate["rated_amount_minor"] == 5000
        assert residential["rated_amount_minor"] == 3750

    def test_tiered_base_minimum_charge_and_fuel_surcharge(self, api):
        """PRD §3.4: "the base amount is that tier's `rate_per_kg_minor`
        multiplied by `actual_weight_kg`; the rated amount is the greater of
        the base amount and the lane's `minimum_charge_minor`. For
        `FUEL_SURCHARGE`, the rated amount is the rated base-freight amount
        multiplied by the lane's `fuel_surcharge_pct_bp` and divided by ten
        thousand, rounded half up."

        Base max(500 x 150, 20000) = 75000; fuel round_half_up(75000 x 1000 /
        10000) = 7500; invoice rated total 75000 + 7500 + 5000 + 3750 = 91250.

        Design: Difficulty/combinatorial_formula/accessorial_cap_nested_min_mode_a
        """
        _chain, invoice = self._setup(api)
        rated = rate_invoice(invoice["id"])
        base = find_line(invoice["id"], "BASE_FREIGHT")
        fuel = find_line(invoice["id"], "FUEL_SURCHARGE")
        assert base["rated_amount_minor"] == 75000
        assert fuel["rated_amount_minor"] == 7500
        assert rated["rated_total_minor"] == 91250


class TestFxDateVariants:
    """EUR 999 invoice (three 333 lines) for a USD client; EUR->USD rates of
    1.10 effective 2026-08-01 and 1.20 effective 2026-08-05."""

    def _setup(self, api):
        chain = setup_eur_fx_chain(
            fx_rates=(("2026-08-01", 1_100_000), ("2026-08-05", 1_200_000))
        )
        lines = [
            {"charge_code": "BASE_FREIGHT", "billed_amount_minor": 333},
            {"charge_code": "DETENTION", "billed_amount_minor": 333},
            {"charge_code": "STORAGE", "billed_amount_minor": 333},
        ]
        invoice = build_eur_invoice(chain, lines)
        finalized = audit_invoice_to_cleared(invoice["id"])
        assert finalized["audit_status"] == "CLEARED", "Setup failed: not CLEARED"
        run = create_payment_run(chain["client"]["id"], run_date="2026-08-10", currency="USD")
        return chain, finalized, run

    def test_home_total_uses_invoice_date_variant(self, api):
        """PRD §3.7: "The invoice-date variant — used for `home_total_minor` at
        finalization and for GL reporting amounts — reads the rate as of the
        invoice's `invoice_date`."

        Invoice date 2026-08-03 resolves the 1.10 rate (the 1.20 rate is not
        yet effective): three lines of round_half_up(333 x 1.10) = 366 sum to
        home_total 1098; approved stays the rated 999 (zero variance).

        Design: Difficulty/dual_variant_calc/fx_invoice_date_vs_payment_date_variant
        """
        _chain, finalized, _run = self._setup(api)
        assert finalized["approved_amount_minor"] == 999
        assert finalized["home_total_minor"] == 1098

    def test_scheduled_amount_uses_payment_date_variant(self, api):
        """PRD §3.7: "The payment-date variant — used when a payment-run item's
        `scheduled_amount_minor` is computed into the run's currency — reads
        the rate as of the run's `run_date`, so a rate change between invoice
        date and run date legitimately yields a different amount for the same
        invoice."

        Run date 2026-08-10 resolves the 1.20 rate: round_half_up(999 x 1.20)
        = 1199, differing from the invoice-date home total of 1098.

        Design: Difficulty/dual_variant_calc/fx_invoice_date_vs_payment_date_variant
        """
        _chain, finalized, run = self._setup(api)
        item = add_run_item(run["id"], finalized["id"])
        assert item["scheduled_amount_minor"] == 1199
        assert finalized["home_total_minor"] == 1098 != item["scheduled_amount_minor"]


class TestFxPerLineRoundingOrder:
    """Per-line conversion rounds each line's share before summing; the
    forbidden sum-then-round order would produce a different number."""

    def test_three_lines_of_333_round_per_line_to_1098(self, api):
        """PRD §3.7: "Invoice-level home totals have a pinned evaluation order:
        each line's approved share is converted first and rounded individually,
        and the per-line results are then summed; summing first and rounding
        once at the end is the forbidden alternative."

        Three 333 EUR lines at 1.10: 3 x round_half_up(366.3) = 3 x 366 = 1098;
        sum-then-round would give round_half_up(999 x 1.10) = 1099.

        Design: Difficulty/combinatorial_formula/fx_per_line_rounding_then_sum_mode_b
        """
        chain = setup_eur_fx_chain()
        lines = [
            {"charge_code": "BASE_FREIGHT", "billed_amount_minor": 333},
            {"charge_code": "DETENTION", "billed_amount_minor": 333},
            {"charge_code": "STORAGE", "billed_amount_minor": 333},
        ]
        invoice = build_eur_invoice(chain, lines)
        finalized = audit_invoice_to_cleared(invoice["id"])
        assert finalized["audit_status"] == "CLEARED", "Setup failed: not CLEARED"
        assert finalized["home_total_minor"] == 1098
        assert finalized["home_total_minor"] != 1099

    def test_two_lines_of_333_round_per_line_to_732(self, api):
        """PRD §3.7: "Invoice-level home totals have a pinned evaluation order:
        each line's approved share is converted first and rounded individually,
        and the per-line results are then summed; summing first and rounding
        once at the end is the forbidden alternative."

        Two 333 EUR lines at 1.10: 2 x 366 = 732 per the pinned order;
        sum-then-round would give round_half_up(666 x 1.10) = 733.

        Design: Difficulty/combinatorial_formula/fx_per_line_rounding_then_sum_mode_b
        """
        chain = setup_eur_fx_chain()
        lines = [
            {"charge_code": "BASE_FREIGHT", "billed_amount_minor": 333},
            {"charge_code": "DETENTION", "billed_amount_minor": 333},
        ]
        invoice = build_eur_invoice(chain, lines, invoice_number="INV-0301")
        finalized = audit_invoice_to_cleared(invoice["id"])
        assert finalized["audit_status"] == "CLEARED", "Setup failed: not CLEARED"
        assert finalized["home_total_minor"] == 732
        assert finalized["home_total_minor"] != 733


class TestFxRateUniqueness:
    def test_duplicate_rate_for_same_pair_and_date_rejected(self, api):
        """PRD §3.7: "One rate may exist per client, currency pair, and
        effective date; a duplicate is rejected with `ERR_DUPLICATE_FX_RATE`."

        Design: Corner/validations/fx_rate_duplicate_date_rejected
        """
        set_clock()
        client = create_active_client()
        create_fx_rate(client["id"], effective_date="2026-08-01", rate_ppm=1_100_000)
        res = api.create_fx_rate(
            client["id"],
            {
                "from_currency": "EUR",
                "to_currency": "USD",
                "effective_date": "2026-08-01",
                "rate_ppm": 1_105_000,
                "source": "MANUAL",
            },
            FINANCE,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_FX_RATE, expected_status=409)
        ok = api.create_fx_rate(
            client["id"],
            {
                "from_currency": "EUR",
                "to_currency": "USD",
                "effective_date": "2026-08-02",
                "rate_ppm": 1_105_000,
                "source": "MANUAL",
            },
            FINANCE,
        )
        created = validate_success(ok, 201)
        assert created["effective_date"] == "2026-08-02"
