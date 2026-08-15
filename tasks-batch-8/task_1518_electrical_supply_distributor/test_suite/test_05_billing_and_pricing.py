"""Release billing: firm vs escalation variants, the reel/cut-charge branch,
the min-cut boundary, provisional estimates, and the escalation cap."""
from test_helpers import (
    CREDIT_MGR,
    SALES_REP,
    ApiErrorId,
    api_client,
    create_awarded_quote,
    create_contractor,
    create_foot_item,
    create_job_account,
    create_quote,
    create_release,
    receive_stock,
    set_clock,
    set_index_reading,
    setup_cut_boundary_delivered_pair,
    setup_firm_and_escalation_delivered_pair,
    setup_requested_release,
    validate_error,
    validate_success,
    walk_release,
)


class TestProvisionalEstimate:

    def test_release_estimate_uses_requested_qty_and_cut_charge(self):
        """PRD section 3.6: "An `estimated_total_cents` is computed as a
        provisional extension — the billing formula of §3.8 evaluated with
        each line's `qty_requested` as the billed quantity and the logical
        clock as it stands at creation."
        PRD section 3.6: "The release's `billed_total_cents`, `truck_id`,
        `delivery_date`, `window_start_hour`, `window_end_hour`, and
        `invoiced_on` are all null at this stage."

        Design: Corner/calculations/release_estimate_uses_requested_qty_and_cut_charge
        """
        ctx = setup_requested_release(item_kind="foot", line_qty=100,
                                      line_price=45.25, stock_qty=None,
                                      credit_limit_cents=10_000_000)
        release = ctx["release"]
        # FIRM provisional: round(100 x 45.25) = 4525, plus the 1500 cut
        # charge because 100 ft is less than the 500-ft reel.
        assert release["estimated_total_cents"] == 6025, (
            f"provisional estimate must be 4525 + 1500 = 6025, got "
            f"{release['estimated_total_cents']}")
        assert release["billed_total_cents"] is None, (
            "billed_total_cents stays null until the release is invoiced")


class TestFirmVsEscalationBilling:

    def test_firm_price_billing_ignores_index_movement(self):
        """PRD section 3.8: "`FIRM_PRICE` bills at that pinned price, while
        `ESCALATION` scales the base price by the capped index ratio taken at
        the logical clock's year-month at invoice time, with the resulting
        unit price rounded half-up to four decimal places."
        PRD section 3.3: "`FIRM_PRICE` bills at the award-pinned quote price
        and ignores commodity-index movement entirely."

        Design: Difficulty/dual_variant_calc/release_billing_firm_vs_escalation
        """
        world = setup_firm_and_escalation_delivered_pair()
        resp = api_client.invoice_release(world["rf"]["id"], CREDIT_MGR)
        firm = validate_success(resp, expected_status=200)
        # 200 ft x 45.25 = 9050, plus 1500 cut charge (200 < 500-ft reel).
        assert firm["billed_total_cents"] == 10_550, (
            f"FIRM billing ignores the 100 -> 110 index move: expected "
            f"10550, got {firm['billed_total_cents']}")

    def test_escalation_billing_scales_with_index_ratio(self):
        """PRD section 3.3: "`ESCALATION` scales the quote price by the ratio
        of the commodity index at billing time to the index pinned at award:
        the base index is the quote's `award_index_value`, and the current
        index is the latest published reading whose `month` is on or before
        the year-month of the logical clock at billing time."

        Design: Difficulty/dual_variant_calc/release_billing_firm_vs_escalation
        """
        world = setup_firm_and_escalation_delivered_pair()
        firm = validate_success(
            api_client.invoice_release(world["rf"]["id"], CREDIT_MGR),
            expected_status=200)
        esc = validate_success(
            api_client.invoice_release(world["re"]["id"], CREDIT_MGR),
            expected_status=200)
        # Ratio 110/100 = 1.10; eff unit = 49.775 c/ft; 200 x 49.775 = 9955,
        # plus the 1500 cut charge.
        assert esc["billed_total_cents"] == 11_455, (
            f"ESCALATION billing applies the 1.10 ratio: expected 11455, got "
            f"{esc['billed_total_cents']}")
        assert esc["billed_total_cents"] - firm["billed_total_cents"] == 905


class TestCutChargeReelBoundary:

    def test_below_reel_length_incurs_cut_charge(self):
        """PRD section 3.8: "for a `FOOT` item the same rounded product is
        taken and, when the shipped quantity is less than the item's
        `reel_length_ft`, the flat `cut_charge_cents` is added on top — a full
        reel or more escapes the cut charge."

        Design: Difficulty/combinatorial_formula/cut_charge_reel_boundary_extension
        """
        world = setup_cut_boundary_delivered_pair()
        billed = validate_success(
            api_client.invoice_release(world["ra"]["id"], CREDIT_MGR),
            expected_status=200)
        # 499 ft ships less than the 500-ft reel: round(499 x 45.25) = 22580
        # plus the 1500 cut charge.
        assert billed["billed_total_cents"] == 24_080, (
            f"499 ft (< 500-ft reel) must bill 22580 + 1500 = 24080, got "
            f"{billed['billed_total_cents']}")

    def test_full_reel_length_escapes_cut_charge(self):
        """PRD section 3.8: "for a `FOOT` item the same rounded product is
        taken and, when the shipped quantity is less than the item's
        `reel_length_ft`, the flat `cut_charge_cents` is added on top — a full
        reel or more escapes the cut charge."

        Design: Difficulty/combinatorial_formula/cut_charge_reel_boundary_extension
        """
        world = setup_cut_boundary_delivered_pair()
        billed = validate_success(
            api_client.invoice_release(world["rb"]["id"], CREDIT_MGR),
            expected_status=200)
        # 500 ft == the 500-ft reel: round(500 x 45.25) = 22625, no cut charge.
        assert billed["billed_total_cents"] == 22_625, (
            f"500 ft (== reel) must bill 22625 with no cut charge, got "
            f"{billed['billed_total_cents']}")


class TestEscalationCap:

    def test_escalation_cap_clamps_ratio(self):
        """PRD section 3.3: "An optional `escalation_cap_pct`, expressed as a
        fraction, clamps the escalation ratio to at most one plus that
        fraction: a cap of 0.10 limits the ratio to 1.10 no matter how far the
        index has run."

        Design: Corner/calculations/escalation_cap_clamps_ratio
        """
        contractor = create_contractor("Juliett Electric", 10_000_000)
        thhn = create_foot_item()
        receive_stock(thhn["id"], 200)
        set_index_reading("2026-08", 100.0)
        job = create_job_account(contractor["id"], "Capped Job",
                                 jobsite_address="40 Site Rd",
                                 pricing_mode="ESCALATION",
                                 escalation_cap_pct=0.10)
        quote = create_awarded_quote(job["id"], [(thhn["id"], 100, 45.25)])
        release = create_release(job["id"], quote["id"], [(thhn["id"], 100)])
        walk_release(release["id"], "DELIVERED", truck_id="T1",
                     delivery_date="2026-08-10", window=(8, 12))
        set_index_reading("2026-09", 150.0)
        set_clock("2026-09-05T00:00:00Z")

        billed = validate_success(
            api_client.invoice_release(release["id"], CREDIT_MGR),
            expected_status=200)
        # Uncapped ratio would be 1.50; the 0.10 cap clamps it to 1.10, so
        # eff unit = 49.775 and round_half_up(100 x 49.775) = 4978, plus the
        # 1500 cut charge (100 < 500-ft reel).
        assert billed["billed_total_cents"] == 6_478, (
            f"cap 0.10 must clamp the ratio to 1.10: expected 6478, got "
            f"{billed['billed_total_cents']}")


class TestMinCutBoundary:

    def _draft_quote_on_thhn(self):
        contractor = create_contractor("Lima Electric", 10_000_000)
        thhn = create_foot_item()
        job = create_job_account(contractor["id"], "Min Cut Job",
                                 jobsite_address="16 Site Rd")
        quote = create_quote(job["id"])
        return quote, thhn

    def test_qty_at_min_cut_accepted(self):
        """PRD section 3.4: "Adding a line to a quote that is not `DRAFT` is
        rejected with `ERR_QUOTE_NOT_DRAFT`, and for a `FOOT` item a `qty`
        below the item's `min_cut_ft` is rejected with `ERR_BELOW_MIN_CUT`."

        Design: Difficulty/boundary_precision_check/min_cut_exact_boundary
        """
        quote, thhn = self._draft_quote_on_thhn()
        resp = api_client.create_quote_line(
            {"quote_id": quote["id"], "catalog_item_id": thhn["id"],
             "qty": 50, "unit_price_cents": 45.25},
            SALES_REP)
        data = validate_success(resp, expected_status=201)
        assert data["qty"] == 50, (
            "qty exactly equal to min_cut_ft (50) is not below the floor")

    def test_qty_below_min_cut_rejected(self):
        """PRD section 3.4: "Adding a line to a quote that is not `DRAFT` is
        rejected with `ERR_QUOTE_NOT_DRAFT`, and for a `FOOT` item a `qty`
        below the item's `min_cut_ft` is rejected with `ERR_BELOW_MIN_CUT`."

        Design: Difficulty/boundary_precision_check/min_cut_exact_boundary
        """
        quote, thhn = self._draft_quote_on_thhn()
        resp = api_client.create_quote_line(
            {"quote_id": quote["id"], "catalog_item_id": thhn["id"],
             "qty": 49, "unit_price_cents": 45.25},
            SALES_REP)
        validate_error(resp, ApiErrorId.ERR_BELOW_MIN_CUT)
