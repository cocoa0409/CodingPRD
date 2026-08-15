"""Quoting and settlement: provisional vs final money variants, per-line
rounding order, make-ready waiver chain, tier boundaries, and the invoice
lifecycle around the order-minimum recovery boundary."""
from test_helpers import (
    ApiErrorId,
    assert_invoice,
    assert_job,
    create_customer,
    create_job,
    setup_settlement_job,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLERK
from test_helpers.api_client import api_client


class TestProvisionalVsFinalSettlement:
    def test_provisional_quote_at_creation(self, api):
        """PRD §3.2: "The second computation is the forward-looking quote, recorded on the job as `provisional_subtotal_cents` and `provisional_total_cents`."
        PRD §3.2: "The make-ready line is 180000 cents for an `OFFSET` job and 25000 cents for a `DIGITAL` job, with one exception: the offset make-ready is waived to zero whenever the print line alone reaches at least 400000 cents; the digital make-ready is never waived."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_settlement_money
        """
        customer = create_customer(name="Beta", brand_code="BTA")
        job = validate_success(
            api.create_job(
                {
                    "customer_id": customer["id"],
                    "quantity_ordered": 20000,
                    "blank_w_cin": 900,
                    "blank_h_cin": 600,
                    "grain_rotation_allowed": True,
                    "substrate_code": "SBS18",
                    "caliper_pts": 18,
                    "finish_coat": True,
                    "finish_foil": False,
                    "finish_emboss": False,
                    "required_ink_slots": ["BRAND_RED"],
                    "requires_retail_compliance": False,
                },
                ADMIN,
            ),
            201,
        )
        assert_job(job)
        assert job["route_type"] == "OFFSET"
        # print 20000*24=480000 (waives make-ready) + board 1350*320=432000
        # + coat rhu(20000*950/1000)=19000 + make_ready 0 == 931000
        assert job["provisional_subtotal_cents"] == 931000
        assert job["provisional_total_cents"] == 931000

    def test_final_settlement_diverges_from_provisional(self, api):
        """PRD §3.8: "It recomputes every line against actuals and flips the `variant` to `FINAL`."
        PRD §3.8: "The board line becomes the job's `sheets_consumed_actual` multiplied by the `unit_cost_cents` of the board stock recorded in the job's `board_stock_id`."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_settlement_money
        """
        ctx, invoice = setup_settlement_job(
            quantity_ordered=20000,
            finishes=["COAT"],
            sheets_printed=1400,
            sheets_good=1300,
        )
        finalized = validate_success(api.finalize_invoice(invoice["id"], CLERK), 200)
        assert_invoice(finalized)
        assert finalized["variant"] == "FINAL"
        # print 480000 + board 1400*300=420000 + coat rhu(32500*950/1000)=30875
        # + make_ready 0 (waived) == 930875
        assert finalized["subtotal_cents"] == 930875
        assert finalized["make_ready_waived"] is True
        assert finalized["make_ready_line_cents"] == 0
        assert finalized["minimum_recovery_cents"] == 0
        assert finalized["total_cents"] == 930875

        job_after = validate_success(api.get_job(ctx["job"]["id"], ADMIN), 200)
        assert job_after["provisional_total_cents"] == 931000
        assert (
            job_after["provisional_total_cents"] != finalized["total_cents"]
        ), "provisional (931000) and final (930875) variants diverge by 125c"


class TestFinishingPerLineRoundingOrder:
    def test_each_finishing_line_rounded_half_up_individually(self, api):
        """PRD §3.8: "Rounding order is pinned at settlement: every charge line is rounded half-up to whole cents individually, and the `subtotal_cents` is the sum of those already-rounded lines."
        PRD §3.8: "with 20750 good cartons and coating, foil, and embossing all completed, the per-line amounts are 19713, 54988, and 36831 cents and sum to 111532, whereas a single aggregate rounding would produce 111531."

        Design: Difficulty/combinatorial_formula/finishing_per_line_rounding_order
        """
        ctx, invoice = setup_settlement_job(
            quantity_ordered=20000,
            finishes=["COAT", "FOIL", "EMBOSS"],
            sheets_printed=1400,
            sheets_good=830,
        )
        job_after = validate_success(api.get_job(ctx["job"]["id"], ADMIN), 200)
        assert job_after["good_cartons_actual"] == 20750  # 830 good sheets * 25 ups

        finalized = validate_success(api.finalize_invoice(invoice["id"], CLERK), 200)
        amounts = {line["code"]: line["amount_cents"] for line in finalized["lines"]}
        assert amounts["FINISH_COAT"] == 19713  # rhu(20750*950/1000) = rhu(19712.5)
        assert amounts["FINISH_FOIL"] == 54988  # rhu(54987.5)
        assert amounts["FINISH_EMBOSS"] == 36831  # rhu(36831.25)

    def test_subtotal_is_sum_of_rounded_lines_not_aggregate_rounding(self, api):
        """PRD §3.8: "Summing unrounded line values and rounding once at the end is forbidden, because the two orders disagree in the cents — with 20750 good cartons and coating, foil, and embossing all completed, the per-line amounts are 19713, 54988, and 36831 cents and sum to 111532, whereas a single aggregate rounding would produce 111531."

        Design: Difficulty/combinatorial_formula/finishing_per_line_rounding_order
        """
        ctx, invoice = setup_settlement_job(
            quantity_ordered=20000,
            finishes=["COAT", "FOIL", "EMBOSS"],
            sheets_printed=1400,
            sheets_good=830,
        )
        finalized = validate_success(api.finalize_invoice(invoice["id"], CLERK), 200)
        # print 480000 + board 1400*300=420000 + finishing 111532 + make_ready 0
        assert finalized["subtotal_cents"] == 1011532
        assert finalized["subtotal_cents"] != 1011531, (
            "aggregate-rounded order is forbidden; per-line-then-sum is pinned"
        )
        assert finalized["make_ready_waived"] is True
        assert finalized["minimum_recovery_cents"] == 0
        assert finalized["total_cents"] == 1011532


class TestMakeReadyWaiverChain:
    def test_print_line_just_below_waiver_threshold_charges_make_ready(self, api):
        """PRD §3.8: "Third, the waiver is decided from the print line alone — `make_ready_waived` is true exactly when the job routes `OFFSET` and the print line is at least 400000 cents; the print line by construction contains no make-ready, so the test is self-contained."

        Design: Difficulty/combinatorial_formula/makeready_waiver_and_minimum_chain
        """
        customer = create_customer(name="Epsilon", brand_code="EPS")
        job = create_job(customer["id"], quantity_ordered=16666, finish_coat=False,
                         required_ink_slots=[])
        invoice = validate_success(
            api.create_invoice({"job_id": job["id"]}, CLERK), 201
        )
        assert_invoice(invoice)
        # print 16666*24 = 399984 < 400000 -> not waived
        assert invoice["make_ready_waived"] is False
        assert invoice["make_ready_line_cents"] == 180000
        # 399984 + board 1126*320=360320 + 180000
        assert invoice["subtotal_cents"] == 940304
        assert invoice["minimum_recovery_cents"] == 0
        assert invoice["total_cents"] == 940304

    def test_print_line_at_waiver_threshold_waives_make_ready(self, api):
        """PRD §3.2: "the offset make-ready is waived to zero whenever the print line alone reaches at least 400000 cents; the digital make-ready is never waived."
        PRD §3.8: "Fourth, the `make_ready_line_cents` is zero when waived, otherwise 180000 cents for `OFFSET` or 25000 cents for `DIGITAL`."

        Design: Difficulty/combinatorial_formula/makeready_waiver_and_minimum_chain
        """
        customer = create_customer(name="Epsilon", brand_code="EPB")
        job = create_job(customer["id"], quantity_ordered=16667, finish_coat=False,
                         required_ink_slots=[])
        invoice = validate_success(
            api.create_invoice({"job_id": job["id"]}, CLERK), 201
        )
        # print 16667*24 = 400008 >= 400000 -> waived
        assert invoice["make_ready_waived"] is True
        assert invoice["make_ready_line_cents"] == 0
        # 400008 + board 360320
        assert invoice["subtotal_cents"] == 760328
        assert invoice["total_cents"] == 760328


def test_job_creation_computed_fields(api):
    """PRD §3.2: "Otherwise, if `quantity_ordered` is at most 2500, the job routes `DIGITAL`; larger quantities route `OFFSET`."
    PRD §3.2: "Should that subtotal fall short of the plant's 750000-cent order minimum, a minimum-recovery amount equal to the shortfall is added, while a subtotal of exactly 750000 cents recovers nothing; the `provisional_total_cents` is the subtotal plus that recovery."

    Design: Corner/entities/job_creation_computed_fields
    """
    customer = create_customer(name="Acme", brand_code="ACM")
    job = validate_success(
        api.create_job(
            {
                "customer_id": customer["id"],
                "quantity_ordered": 3000,
                "blank_w_cin": 900,
                "blank_h_cin": 600,
                "grain_rotation_allowed": True,
                "substrate_code": "SBS18",
                "caliper_pts": 18,
                "finish_coat": True,
                "finish_foil": False,
                "finish_emboss": False,
                "required_ink_slots": ["BRAND_RED"],
                "requires_retail_compliance": False,
            },
            ADMIN,
        ),
        201,
    )
    assert_job(job)
    assert job["route_type"] == "OFFSET"  # 3000 > 2500
    assert job["status"] == "QUOTED"
    # print 3000*38=114000 + board 204*320=65280 + coat rhu(2850.0)=2850
    # + make_ready 180000 == 362130
    assert job["provisional_subtotal_cents"] == 362130
    assert job["provisional_total_cents"] == 750000  # recovery 387870


def test_tier_boundary_provisional_print(api):
    """PRD §3.2: "A tiered unit price is read from that billable quantity: a billable quantity of at least 10000 bills at 24 cents per carton; at least 5000 bills at 30 cents; at least 2500 bills at 38 cents; and any smaller billable quantity — always at least the 1000-carton minimum — bills at 45 cents."
    PRD §3.2: "The boundary is inclusive: an order of exactly 2500 cartons routes `DIGITAL`, while 2501 routes `OFFSET`."

    Design: Corner/calculations/tier_boundary_provisional_print
    """
    customer = create_customer(name="Acme", brand_code="ACM")
    job_2499 = create_job(customer["id"], quantity_ordered=2499, finish_coat=False,
                          required_ink_slots=[])
    assert job_2499["route_type"] == "DIGITAL"
    # print 2499*45=112455 + board 162*320=51840 + make_ready 25000
    assert job_2499["provisional_subtotal_cents"] == 189295
    assert job_2499["provisional_total_cents"] == 750000

    job_2500 = create_job(customer["id"], quantity_ordered=2500, finish_coat=False,
                          required_ink_slots=[])
    assert job_2500["route_type"] == "DIGITAL"
    # print 2500*38=95000 + board 51840 + 25000
    assert job_2500["provisional_subtotal_cents"] == 171840
    assert job_2500["provisional_total_cents"] == 750000


class TestMinimumRecoveryAndInvoiceLifecycle:
    def _settled_5000_job(self, api, labor_minutes):
        return setup_settlement_job(
            quantity_ordered=5000,
            finishes=["COAT"],
            sheets_printed=1300,
            sheets_good=200,
            kit={
                "units_per_kit": 3,
                "kits_planned": 20,
                "kits_completed": 20,
                "labor_minutes_actual": labor_minutes,
            },
        )

    def test_subtotal_exactly_at_minimum_recovers_nothing(self, api):
        """PRD §3.8: "Sixth, `minimum_recovery_cents` is the amount by which that subtotal falls short of 750000 cents, floored at zero — a subtotal of exactly 750000 cents recovers nothing."
        PRD §3.8: "Each `COMPLETED` kit order contributes a kitting line: its `labor_minutes_actual` at 150 cents per minute plus its `kits_completed` at 85 cents per kit."

        Design: Corner/calculations/minimum_recovery_exact_boundary_and_invoice_lifecycle
        """
        ctx, invoice = self._settled_5000_job(api, labor_minutes=157)
        finalized = validate_success(api.finalize_invoice(invoice["id"], CLERK), 200)
        # 150000 print + 390000 board + 4750 coat + 25250 kit + 180000 make-ready
        assert finalized["subtotal_cents"] == 750000
        assert finalized["minimum_recovery_cents"] == 0
        assert finalized["total_cents"] == 750000
        # print 150000 < 400000 -> not waived
        assert finalized["make_ready_line_cents"] == 180000

        # One open invoice per job while FINALIZED.
        dup = api.create_invoice({"job_id": ctx["job"]["id"]}, CLERK)
        validate_error(dup, ApiErrorId.ERR_INVOICE_ALREADY_OPEN)

        # Voiding releases the one-open-invoice constraint.
        voided = validate_success(api.void_invoice(invoice["id"], CLERK), 200)
        assert voided["status"] == "VOIDED"

        fresh = validate_success(
            api.create_invoice({"job_id": ctx["job"]["id"]}, CLERK), 201
        )
        assert fresh["status"] == "DRAFT"
        assert fresh["variant"] == "PROVISIONAL"
        # provisional snapshot: 150000 + 339*320=108480 + 4750 + 180000
        assert fresh["subtotal_cents"] == 443230

        refinalized = validate_success(api.finalize_invoice(fresh["id"], CLERK), 200)
        assert refinalized["total_cents"] == 750000
        settled = validate_success(api.settle_invoice(fresh["id"], CLERK), 200)
        assert settled["status"] == "SETTLED"

    def test_subtotal_one_cent_below_minimum_recovers_shortfall(self, api):
        """PRD §3.8: "Sixth, `minimum_recovery_cents` is the amount by which that subtotal falls short of 750000 cents, floored at zero — a subtotal of exactly 750000 cents recovers nothing. Seventh, `total_cents` is the subtotal plus the recovery."

        Design: Corner/calculations/minimum_recovery_shortfall_boundary
        """
        ctx, invoice = self._settled_5000_job(api, labor_minutes=156)
        finalized = validate_success(api.finalize_invoice(invoice["id"], CLERK), 200)
        # kit line 156*150 + 20*85 = 25100 -> subtotal 749850
        assert finalized["subtotal_cents"] == 749850
        assert finalized["minimum_recovery_cents"] == 150
        assert finalized["total_cents"] == 750000
