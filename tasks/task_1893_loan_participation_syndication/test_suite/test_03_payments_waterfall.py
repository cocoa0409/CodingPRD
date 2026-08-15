"""Distribution waterfall arithmetic: day-count variants, tiered allocation,
servicing-fee evaluation order (PRD §3.4, §3.5)."""
from test_helpers import (
    api_client,
    assert_distribution_run,
    assert_pools_cover_lines,
    assert_waterfall_conservation,
    create_and_remit_run,
    create_payment,
    create_run,
    get_facility,
    get_participant,
    get_success_data,
    lines_for_run,
    make_agent_headers,
    setup_funded_facility,
    validate_success,
)

AGENT = make_agent_headers()

# Standard syndicate: 6000/3000/1000 bps shares on a 10,000,000 facility.
STANDARD_COMMITMENTS = [("P1", 6_000_000), ("P2", 3_000_000), ("P3", 1_000_000)]


def _run_pools_for_basis(day_count_basis, draw_amount=3_000_000, payment=40_000):
    """Facility fully funded on a single draw from 2026-08-01; one REGULAR
    payment valued 2026-08-31 (30 calendar days); returns the run."""
    setup = setup_funded_facility(
        [("Solo " + day_count_basis, draw_amount)],
        draw_amount,
        facility_overrides={
            "facility_name": "Fac " + day_count_basis,
            "total_commitment_cents": draw_amount,
            "day_count_basis": day_count_basis,
        },
    )
    pay = create_payment(
        setup["facility"]["id"], setup["borrower"]["id"], payment, "2026-08-31"
    )
    return create_run(pay["id"])


class TestDayCountBasisVariants:
    def test_interest_day_count_basis_variants_diverge(self):
        """PRD §3.4: "Under `ACT_360` the segment's days are the calendar days
        between its start and end, over a denominator of 360. Under `ACT_365`
        the same calendar days sit over a denominator of 365, so identical
        inputs yield a slightly smaller charge. Under `BASIS_30_360` the day
        count clamps every month to thirty days: it is 360 times the difference
        in years, plus 30 times the difference in month numbers, plus the
        difference between the two day-of-month values with each day first
        clamped to at most 30, all over a denominator of 360 — so a segment from
        2026-08-01 to 2026-08-31 counts 29 days, diverging from both actual-day
        bases."
        PRD §3.4: "Each segment's interest is the floor of the draw's
        `outstanding_cents` times the segment rate in basis points times the
        segment days, divided by the basis denominator times ten thousand".

        Design: Difficulty/dual_variant_calc/interest_day_count_basis_variants_diverge
        """
        run360 = _run_pools_for_basis("ACT_360")
        run365 = _run_pools_for_basis("ACT_365")
        run30 = _run_pools_for_basis("BASIS_30_360")

        # Identical principal (3,000,000) and calendar window (30 days) at
        # 1200 bps: 30000 / floor(108,000,000,000/3,650,000)=29589 / 29 days -> 29000.
        assert run360["interest_pool_cents"] == 30_000
        assert run365["interest_pool_cents"] == 29_589
        assert run30["interest_pool_cents"] == 29_000
        pools = {run360["interest_pool_cents"], run365["interest_pool_cents"],
                 run30["interest_pool_cents"]}
        assert len(pools) == 3, "the three bases must diverge on identical inputs"

    def test_act360_exceeds_basis_30_360_on_larger_position(self):
        """PRD §3.4: "Under `BASIS_30_360` the day count clamps every month to
        thirty days: it is 360 times the difference in years, plus 30 times the
        difference in month numbers, plus the difference between the two
        day-of-month values with each day first clamped to at most 30, all over
        a denominator of 360 — so a segment from 2026-08-01 to 2026-08-31 counts
        29 days, diverging from both actual-day bases."
        PRD §3.4: "Under `ACT_360` the segment's days are the calendar days
        between its start and end, over a denominator of 360."

        Design: Difficulty/dual_variant_calc/interest_day_count_basis_variants_diverge
        """
        run360 = _run_pools_for_basis("ACT_360", draw_amount=6_000_000, payment=70_000)
        run30 = _run_pools_for_basis("BASIS_30_360", draw_amount=6_000_000, payment=70_000)
        # 6,000,000 at 1200 bps: 30 calendar days -> 60,000; 29 clamped days -> 58,000.
        assert run360["interest_pool_cents"] == 60_000
        assert run30["interest_pool_cents"] == 58_000
        assert run360["interest_pool_cents"] > run30["interest_pool_cents"]


class TestWaterfallTieredAllocation:
    def test_waterfall_tiered_allocation_exact_split(self):
        """PRD §3.5: "The waterfall then allocates the payment in strict order.
        First the servicing fee comes off the top, capped at the payment amount,
        leaving the remainder. Second, the interest pool `interest_pool_cents`
        takes the smaller of that remainder and the facility's
        `accrued_interest_cents` recomputed to the payment's `value_date`. Third,
        the entire remaining cash becomes the principal pool
        `principal_pool_cents`".
        PRD §3.5: "each participant's allocation from a pool is the floor of the
        pool times the participant's `share_bps` divided by ten thousand, and the
        leftover cents are distributed one cent at a time in descending order of
        `share_bps`, breaking ties by descending `commitment_cents`, then earlier
        `created_at`, then ascending `participant_name`".

        Design: Difficulty/combinatorial_formula/waterfall_tiered_allocation_exact_split
        """
        setup = setup_funded_facility(STANDARD_COMMITMENTS, 5_000_000)
        facility = setup["facility"]
        borrower = setup["borrower"]
        p1, p2, p3 = setup["participants"]

        pay = create_payment(facility["id"], borrower["id"], 200_000, "2026-08-31")
        run = create_run(pay["id"])

        # 30 days ACT/360 on 5,000,000: accrued 50,000; fee floor(5M*25*30/3.6M)=1,041.
        assert run["servicing_fee_cents"] == 1_041
        assert run["interest_pool_cents"] == 50_000
        assert run["principal_pool_cents"] == 148_959
        assert_waterfall_conservation(run, 200_000)
        lines = lines_for_run(run["id"])
        assert_pools_cover_lines(run, lines)

        validate_success(api_client.remit_distribution_run(run["id"], AGENT))
        # floor splits with remainder cents to the highest shares first.
        assert get_participant(p1["id"])["cumulative_interest_cents"] == 30_000
        assert get_participant(p1["id"])["cumulative_principal_cents"] == 89_376
        assert get_participant(p2["id"])["cumulative_interest_cents"] == 15_000
        assert get_participant(p2["id"])["cumulative_principal_cents"] == 44_688
        assert get_participant(p3["id"])["cumulative_interest_cents"] == 5_000
        assert get_participant(p3["id"])["cumulative_principal_cents"] == 14_895

        refreshed = get_facility(facility["id"])
        assert refreshed["outstanding_principal_cents"] == 4_851_041
        assert refreshed["accrued_interest_cents"] == 0

    def test_waterfall_interest_pool_capped_by_remaining_cash(self):
        """PRD §3.5: "Second, the interest pool `interest_pool_cents` takes the
        smaller of that remainder and the facility's `accrued_interest_cents`
        recomputed to the payment's `value_date`. Third, the entire remaining
        cash becomes the principal pool `principal_pool_cents`".
        PRD §3.5: "Two conservation invariants always hold:
        `servicing_fee_cents` plus the interest and principal pools equals the
        payment's `amount_cents`, and the line totals plus `agent_retained_cents`
        equal the two pools."

        Design: Difficulty/combinatorial_formula/waterfall_tiered_allocation_exact_split
        """
        setup = setup_funded_facility(STANDARD_COMMITMENTS, 5_000_000)
        facility = setup["facility"]
        borrower = setup["borrower"]
        p1, p2, p3 = setup["participants"]

        # Payment (30,000) is smaller than accrued interest (50,000): the second
        # min() branch binds and the principal pool is zero.
        pay = create_payment(facility["id"], borrower["id"], 30_000, "2026-08-31")
        run = create_run(pay["id"])
        assert run["servicing_fee_cents"] == 1_041
        assert run["interest_pool_cents"] == 28_959
        assert run["principal_pool_cents"] == 0
        assert_waterfall_conservation(run, 30_000)

        lines = {line["participant_id"]: line for line in lines_for_run(run["id"])}
        # floor(28,959 * share) with remainder cents by descending share.
        assert lines[p1["id"]]["interest_cents"] == 17_376
        assert lines[p2["id"]]["interest_cents"] == 8_688
        assert lines[p3["id"]]["interest_cents"] == 2_895
        assert all(line["principal_cents"] == 0 for line in lines.values())
        assert_pools_cover_lines(run, list(lines.values()))


class TestServicingFeeEvaluationOrder:
    def test_servicing_fee_pre_run_outstanding_evaluation_order(self):
        """PRD §3.5: "The raw fee is the floor of the facility's
        `outstanding_principal_cents` — as of run creation, deliberately before
        this run's principal pool is applied — times `servicing_fee_bps` times
        those fee days, divided by 360 times ten thousand."
        PRD §3.5: "Its baseline is the facility's `last_distribution_value_date`
        if any run has preceded this one, otherwise the `settled_at` date of the
        facility's first settled draw".

        Design: Difficulty/combinatorial_formula/servicing_fee_pre_run_outstanding_evaluation_order
        """
        setup = setup_funded_facility(STANDARD_COMMITMENTS, 5_000_000)
        facility = setup["facility"]
        borrower = setup["borrower"]

        pay1 = create_payment(facility["id"], borrower["id"], 200_000, "2026-08-31")
        create_and_remit_run(pay1["id"])
        after_first = get_facility(facility["id"])
        assert after_first["outstanding_principal_cents"] == 4_851_041
        assert after_first["last_distribution_value_date"] == "2026-08-31"

        pay2 = create_payment(facility["id"], borrower["id"], 100_000, "2026-09-15")
        run2 = create_run(pay2["id"])
        # 15 days past the 2026-08-31 baseline on PRE-RUN outstanding 4,851,041:
        # fee floor(4,851,041 * 25 * 15 / 3,600,000) == 505; interest
        # floor(4,851,041 * 1200 * 15 / 3,600,000) == 24,255.
        assert run2["servicing_fee_cents"] == 505
        assert run2["interest_pool_cents"] == 24_255
        assert run2["principal_pool_cents"] == 75_240
        assert_waterfall_conservation(run2, 100_000)

    def test_servicing_fee_capped_at_payment_amount(self):
        """PRD §3.5: "The retained `servicing_fee_cents` is the smaller of that
        raw fee and the payment's `amount_cents`."

        Design: Difficulty/combinatorial_formula/servicing_fee_pre_run_outstanding_evaluation_order
        """
        setup = setup_funded_facility([("Solo", 10_000_000)], 10_000_000)
        facility = setup["facility"]
        borrower = setup["borrower"]

        # Raw fee floor(10M * 25 * 30 / 3.6M) == 2,083 exceeds the 100-cent
        # payment, so the fee is capped at the payment amount and both pools are
        # zero.
        pay = create_payment(facility["id"], borrower["id"], 100, "2026-08-31")
        run = create_run(pay["id"])
        assert run["servicing_fee_cents"] == 100
        assert run["interest_pool_cents"] == 0
        assert run["principal_pool_cents"] == 0
        assert_waterfall_conservation(run, 100)
