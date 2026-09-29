"""Credit-quantity and money calculations of the mitigation banking API.

Every test in this module exercises one pinned arithmetic contract of the PRD:
the two-variant release quantity of a performance milestone, the two-variant
price of a credit sale, the per-stratum rounding order of the work plan credit
yield, the four-input marginal-tier price with its binding ceiling, and the
single-pass capitalisation of the long-term stewardship endowment.
"""

from test_helpers import (
    add_milestone,
    approve_release,
    assert_cents,
    assert_credits,
    assert_ledger_shape,
    assert_score,
    bank_state,
    claim_milestone,
    draft_work_plan,
    execute_sale,
    file_and_accept_monitoring_report,
    fund_stewardship,
    ledger_rows,
    measurements,
    milestone_state,
    permittee_state,
    quote_credits,
    reserve_sale,
    reset_clock,
    set_clock,
    setup_draft_bank,
    setup_sellable_bank,
    setup_sellable_bank_with_second_milestone,
    submit_work_plan,
)

# Measurements for monitoring year 3 that miss the hydroperiod and invasive
# cover standards while meeting both year-3 standards exactly.
YEAR3_PARTIAL_MEASUREMENTS = measurements(
    HYDROPERIOD_DAYS=114,
    INVASIVE_COVER_PCT=12.0,
    NATIVE_COVER_PCT=80.0,
    STEM_DENSITY_PER_ACRE=400,
)


def _bank_with_two_releases_and_a_partial_year_three():
    """A bank whose INSTRUMENT_EXECUTION and CONSTRUCTION_COMPLETE tranches are
    released, whose PERF_YEAR_3 milestone is scheduled and claimable, and whose
    monitoring year 3 report has been accepted with a PARTIAL compliance."""
    reset_clock()
    world = setup_sellable_bank_with_second_milestone(
        second_release_pct=0.200, claim_second=True
    )
    construction = world["milestones"]["CONSTRUCTION_COMPLETE"]
    approve_release(world, construction["id"], member_index=0)
    perf3 = add_milestone(
        world,
        milestone_code="PERF_YEAR_3",
        release_pct=0.250,
        window_start="2029-09-01T00:00:00Z",
        window_end="2029-10-01T00:00:00Z",
        predecessor_milestone_id=construction["id"],
    )
    set_clock("2029-09-05T00:00:00Z")
    report = file_and_accept_monitoring_report(
        world,
        monitoring_year=3,
        window_start="2029-06-01T00:00:00Z",
        window_end="2029-09-01T00:00:00Z",
        measurements_array=YEAR3_PARTIAL_MEASUREMENTS,
        member_index=1,
    )
    return world, perf3, report


def test_perf_year_3_provisional_and_final_release_quantities_diverge():
    """A PERF_YEAR_3 milestone claimed against a 0.9350 PARTIAL monitoring year
    carries both quantities on one row: 24.69 provisional at attainment factor
    1.00 and 22.22 final at the 0.90 factor the score earns.

    PRD §3.6: "That provisional figure is the bank's authorised credit total multiplied by the milestone's release percentage, rounded half up to 2 decimal places."
    PRD §3.6: "The provisional variant always applies an attainment factor of exactly 1.00 and consults no monitoring report whatsoever, which is why a claim can never fail on ecological grounds."
    PRD §3.6: "The final release quantity is then the *already-rounded* provisional quantity multiplied by the selected factor, rounded half up to 2 decimal places again."
    PRD §3.6: "Where a partial factor of 0.90 applies, the 10 percent difference between the provisional and final quantities is simply never released; it does not linger anywhere and never re-enters the bank's available credits."
    Design: Difficulty/dual_variant_calc/milestone_release_provisional_vs_final_diverge_on_partial_attainment
    """
    world, perf3, _report = _bank_with_two_releases_and_a_partial_year_three()

    claimed = claim_milestone(world, perf3["id"])
    assert claimed["status"] == "CLAIMED", (
        f"claiming must advance the milestone to CLAIMED, got {claimed['status']}"
    )
    assert_credits(
        claimed["provisional_release_credits"],
        24.69,
        "provisional_release_credits stamped at claim time",
    )

    approved = approve_release(world, perf3["id"], member_index=0)
    assert approved["status"] == "APPROVED", (
        f"approving the release must advance the milestone to APPROVED, got {approved['status']}"
    )
    assert_credits(
        approved["final_release_credits"],
        22.22,
        "final_release_credits stamped at release approval",
    )
    assert_score(
        approved["attainment_factor_applied"], 0.90, "attainment_factor_applied"
    )

    row = milestone_state(perf3["id"], world)
    assert_credits(
        row["provisional_release_credits"],
        24.69,
        "provisional_release_credits survives the approval unchanged",
    )
    assert_credits(row["final_release_credits"], 22.22, "final_release_credits")
    assert_credits(
        row["provisional_release_credits"] - row["final_release_credits"],
        2.47,
        "the tenth of the tranche the partial factor never releases",
    )


def test_partial_attainment_release_writes_only_the_final_quantity_to_the_ledger():
    """The RELEASED ledger entry and the bank's recomputed aggregates carry the
    final 22.22 credits, never the provisional 24.69, so the bank ends the
    cascade with 56.79 credits released and available.

    PRD §3.7: "The compliance status then follows from those two outputs in order: it is `PASS` when no standard failed, otherwise `PARTIAL` when the attainment score is at least 0.85 — the boundary is inclusive — and otherwise `FAIL`."
    PRD §3.6: "Otherwise the factor is selected from the report's attainment score by two thresholds, both of which are inclusive at their boundary: a score of at least 0.95 earns a factor of 1.00, a score of at least 0.85 but below 0.95 earns a factor of 0.90, and a score below 0.85 is rejected with `ERR_COMPLIANCE_FAILED`."
    PRD §3.6: "A ledger entry of type `RELEASED` is appended carrying the final release quantity as a positive delta, attributed through a source entity type of `RELEASE_MILESTONE` and the milestone's own identifier, with a memo naming the release, its milestone code and the attainment factor applied."
    PRD §3.6: "The bank's `credits_released` and `credits_available` are recomputed from the ledger, and the posture is recomputed — which is typically the moment a bank moves from `RESTRICTED` to `OPEN`, once credits exist and no remedial action is standing."
    Design: Difficulty/dual_variant_calc/milestone_release_provisional_vs_final_diverge_on_partial_attainment
    """
    world, perf3, report = _bank_with_two_releases_and_a_partial_year_three()

    assert_score(report["attainment_score"], 0.9350, "attainment_score")
    assert report["compliance_status"] == "PARTIAL", (
        "a year missing two standards on an otherwise excellent score is PARTIAL, "
        f"got {report['compliance_status']}"
    )

    claim_milestone(world, perf3["id"])
    approve_release(world, perf3["id"], member_index=0)

    released = ledger_rows(world, entry_type="RELEASED")
    assert len(released) == 3, (
        f"expected one RELEASED entry per approved milestone, got {len(released)}"
    )
    last = released[-1]
    assert_credits(
        last["delta_credits"],
        22.22,
        "the RELEASED delta carries the final, not the provisional, quantity",
    )
    assert last["source_entity_type"] == "RELEASE_MILESTONE", (
        f"expected RELEASE_MILESTONE, got {last['source_entity_type']}"
    )
    assert last["source_id"] == perf3["id"], (
        "the RELEASED entry must be attributed to the approved milestone"
    )

    assert_ledger_shape(
        ledger_rows(world),
        [
            ("GENERATED", 0.00, 0.00),
            ("RELEASED", 14.82, 14.82),
            ("RELEASED", 19.75, 34.57),
            ("RELEASED", 22.22, 56.79),
        ],
    )

    bank = bank_state(world)
    assert_credits(bank["credits_released"], 56.79, "credits_released")
    assert_credits(bank["credits_available"], 56.79, "credits_available")


def _sellable_bank_with_a_reserved_eight_credit_sale():
    """A sellable bank whose endowment sits at the interim gate when an 8.00
    credit quote is priced and reserved, and is completed in full afterwards."""
    reset_clock()
    world = setup_sellable_bank(
        permittee_deposit_cents=40_000_000, permittee_required_credits=12.00
    )
    sale = quote_credits(world, 8.00)
    reserve_sale(world, sale["id"])
    bank = fund_stewardship(world, 85_260_000)
    return world, sale, bank


def test_quoted_price_freezes_the_stewardship_surcharge_the_settled_price_drops():
    """The quote freezes the 8 percent surcharge of a 25 percent funded
    endowment at 32216400, while settlement re-reads the now fully funded
    endowment and settles at 29830000 under the nested repricing ceiling.

    PRD §3.8: "That whole calculation is run twice in a sale's life, and the two runs can legitimately disagree."
    PRD §3.8: "The quoted variant runs at quote creation, using the bank's stewardship funding state and demand index as they stand at that moment, and the figure it produces never changes afterwards."
    PRD §3.8: "The executed variant runs again at settlement: it re-reads the stewardship funding state — which may have been cured in the meantime, clearing the 8 percent surcharge — and re-runs the demand measurement against the settlement-time clock, and then applies one further nested ceiling on top of the price cap already described."
    PRD §3.8: "The settled price is whichever is smaller of the freshly recomputed price and the quoted price multiplied by 1.10 and rounded half up to whole cents."
    Design: Difficulty/dual_variant_calc/sale_price_quoted_vs_executed_diverge_when_endowment_completed
    """
    world, sale, bank = _sellable_bank_with_a_reserved_eight_credit_sale()

    assert sale["service_area_tier"] == "PRIMARY", (
        f"an impact inside the bank's own site watershed is PRIMARY, got {sale['service_area_tier']}"
    )
    assert_score(sale["quoted_demand_index"], 0.0000, "quoted_demand_index")
    assert_cents(sale["quoted_price_cents"], 32216400, "quoted_price_cents")
    assert_cents(
        bank["stewardship_funded_cents"], 113680000, "stewardship_funded_cents"
    )

    executed = execute_sale(world, sale["id"])
    assert executed["status"] == "EXECUTED", (
        f"settlement must advance the sale to EXECUTED, got {executed['status']}"
    )
    assert_cents(executed["executed_price_cents"], 29830000, "executed_price_cents")
    assert_cents(
        executed["quoted_price_cents"],
        32216400,
        "the quoted price is retained unchanged after settlement",
    )
    assert_cents(
        executed["quoted_price_cents"] - executed["executed_price_cents"],
        2386400,
        "the cleared stewardship surcharge",
    )


def test_settlement_debits_escrow_at_the_executed_price_and_moves_the_credits():
    """Settlement debits the buyer's escrow by the executed 29830000 rather than
    the quoted 32216400, and converts the 8.00 held credits into sold credits.

    PRD §3.8: "The bank's credits on hold, credits sold and available credits are recomputed, the buyer's escrow balance is recomputed as deposits minus settled prices, the posture is recomputed and lands on `SOLD_OUT` when available credits have reached exactly zero, and the bank's `version` increments by one."
    PRD §3.1: "`escrow_balance_cents` is the deposited total minus the sum of the settled prices of all of this holder's sales standing in `EXECUTED` or `ASSIGNED` status, and likewise starts at 0."
    Design: Difficulty/dual_variant_calc/sale_price_quoted_vs_executed_diverge_when_endowment_completed
    """
    world, sale, _bank = _sellable_bank_with_a_reserved_eight_credit_sale()

    execute_sale(world, sale["id"])

    buyer = permittee_state(world)
    assert_cents(buyer["deposited_cents"], 40000000, "deposited_cents")
    assert_cents(
        buyer["escrow_balance_cents"],
        10170000,
        "escrow debited by the executed price, not the quoted price",
    )

    bank = bank_state(world)
    assert_credits(bank["credits_sold"], 8.00, "credits_sold")
    assert_credits(bank["credits_on_hold"], 0.00, "credits_on_hold")
    assert_credits(bank["credits_available"], 6.82, "credits_available")


def test_work_plan_total_planned_credits_rounds_each_stratum_before_summing():
    """Three strata of 101.50 x 0.375, 70.50 x 0.625 and 33.30 x 0.500 yield
    98.77 planned credits because each product is rounded to 2 decimal places
    before the terms are added.

    PRD §3.4: "Each stratum's credit contribution is its acreage multiplied by its lift factor, rounded half up to 2 decimal places, and the plan total is the sum of those already-rounded per-stratum contributions."
    PRD §3.4: "Summing the unrounded products and rounding the single total at the end is forbidden and yields a different number in the ordinary case where several strata each land on a half-cent boundary; the per-stratum-first order is normative."
    Design: Difficulty/combinatorial_formula/work_plan_yield_rounds_per_stratum_before_summation
    """
    reset_clock()
    world = setup_draft_bank()

    work_plan = draft_work_plan(world)

    assert_credits(
        work_plan["total_planned_credits"],
        98.77,
        "total_planned_credits summed from already-rounded per-stratum contributions",
    )
    assert len(work_plan["credit_strata"]) == 3, (
        f"expected the three drafted strata, got {len(work_plan['credit_strata'])}"
    )


def test_work_plan_credit_yield_stays_on_the_plan_until_the_instrument_is_executed():
    """A freshly drafted plan holds its 98.77 credit yield in DRAFT while the
    bank's authorised credit total is still 0.00.

    PRD §3.4: "A plan opens in `DRAFT`, with `submitted_at`, `decided_at` and `return_reason` all null."
    PRD §3.4: "The plan's credit yield sits on the plan until the banking instrument is executed, and only then is it copied onto the bank."
    Design: Difficulty/combinatorial_formula/work_plan_yield_rounds_per_stratum_before_summation
    """
    reset_clock()
    world = setup_draft_bank()

    work_plan = draft_work_plan(world)

    assert work_plan["status"] == "DRAFT", (
        f"a drafted plan opens in DRAFT, got {work_plan['status']}"
    )
    assert work_plan["submitted_at"] is None, "submitted_at opens null"
    assert work_plan["decided_at"] is None, "decided_at opens null"
    assert_credits(work_plan["total_planned_credits"], 98.77, "total_planned_credits")

    bank = bank_state(world)
    assert_credits(
        bank["total_authorized_credits"],
        0.00,
        "nothing is authorised while the plan is unapproved",
    )


def test_work_plan_total_planned_credits_is_rederived_on_submission():
    """Submitting the plan re-derives the same 98.77 total from the same strata.

    PRD §3.4: "The plan total is computed when the plan is first drafted and re-derived on every submission of that plan."
    PRD §3.4: "Submission by the owning sponsor advances `DRAFT → SUBMITTED` and stamps `submitted_at`, and is admissible only when the hydrology restoration acreage and the planting acreage together come to more than zero — a plan that restores nothing has nothing to submit."
    Design: Difficulty/combinatorial_formula/work_plan_yield_rounds_per_stratum_before_summation
    """
    reset_clock()
    world = setup_draft_bank()
    draft_work_plan(world)

    submitted = submit_work_plan(world)

    assert submitted["status"] == "SUBMITTED", (
        f"submission advances the plan to SUBMITTED, got {submitted['status']}"
    )
    assert_credits(
        submitted["total_planned_credits"],
        98.77,
        "total_planned_credits re-derived on submission",
    )


def _sellable_bank_for_a_secondary_area_buyer():
    """A sellable bank whose endowment is only at the interim gate, plus a buyer
    whose impact watershed is inside the service area but is not the site
    watershed."""
    reset_clock()
    return setup_sellable_bank(
        permittee_deposit_cents=40_000_000,
        permittee_required_credits=9.00,
        permittee_impact_huc8_code="03130003",
    )


def test_secondary_underfunded_six_credit_quote_is_capped_below_the_gross_price():
    """A 6.00 credit quote straddling the 5.00 tier boundary on a DEPRESSIONAL
    bank, with the SECONDARY 12 percent and the underfunded 8 percent charged
    against one premium base, prices at the 26001500 ceiling rather than the
    27132000 gross.

    PRD §3.8: "The requested quantity is then split across three marginal tiers, evaluated in order."
    PRD §3.8: "Each tier carrying a non-zero quantity contributes its quantity multiplied by the base price and by its multiplier, rounded half up to whole cents, and the tiered subtotal is the sum of those already-rounded tier amounts; a tier carrying zero credits contributes nothing and is not rounded at all."
    PRD §3.8: "The combined premium is the subtotal multiplied by the sum of those two percentages, rounded half up to whole cents — the two are never rounded separately and then added."
    PRD §3.8: "Finally a ceiling is applied: the price cap is the tiered subtotal multiplied by 1.15, rounded half up to whole cents, and the price charged is whichever of the gross price and the cap is smaller."
    Design: Difficulty/combinatorial_formula/sale_price_four_input_interaction_capped_below_gross
    """
    world = _sellable_bank_for_a_secondary_area_buyer()

    sale = quote_credits(world, 6.00, impact_huc8_code="03130003")

    assert sale["service_area_tier"] == "SECONDARY", (
        "an impact watershed inside the service area but outside the site watershed "
        f"is SECONDARY, got {sale['service_area_tier']}"
    )
    assert_score(sale["quoted_demand_index"], 0.0000, "quoted_demand_index")
    assert_cents(
        sale["quoted_price_cents"],
        26001500,
        "quoted_price_cents held down by the tiered-subtotal ceiling",
    )


def test_quote_places_no_hold_on_the_bank_credit_pool():
    """The quote leaves the bank's 14.82 released credits entirely available:
    only a reservation places a hold.

    PRD §3.8: "A quote opens in `QUOTED` status with `hold_start_at`, `hold_expires_at`, `executed_price_cents`, `executed_at`, `assigned_at`, `assignment_reference`, `cancelled_reason` and `cancelled_at` all null, raises the bank's `open_quote_count` by one and increments the bank's `version` by one."
    PRD §2.11: "`credits_on_hold` is the negation of the total of the deltas of its `HOLD_PLACED` and `HOLD_RELEASED` entries taken together."
    Design: Difficulty/combinatorial_formula/sale_price_four_input_interaction_capped_below_gross
    """
    world = _sellable_bank_for_a_secondary_area_buyer()

    sale = quote_credits(world, 6.00, impact_huc8_code="03130003")

    assert sale["status"] == "QUOTED", (
        f"a new quote opens in QUOTED, got {sale['status']}"
    )
    assert sale["hold_start_at"] is None, "a quote has no hold start instant"
    assert sale["hold_expires_at"] is None, "a quote has no hold expiry instant"
    assert sale["executed_price_cents"] is None, "a quote carries no settled price"

    bank = bank_state(world)
    assert_credits(bank["credits_on_hold"], 0.00, "credits_on_hold")
    assert_credits(bank["credits_available"], 14.82, "credits_available")


def test_stewardship_requirement_is_a_single_pass_capitalisation_plus_fee():
    """An annual stewardship cost of 4200000 cents capitalises once to a
    112000000 base endowment and takes a 1680000 administrative fee on top,
    giving 113680000 rather than the far larger fixed-point figure.

    PRD §3.2: "The calculation capitalises the annual stewardship cost at a non-wasting payout rate of 3.75 percent: the base endowment is the annual stewardship cost divided by 0.0375, rounded **up** to the next whole cent whatever the remainder."
    PRD §3.2: "An administrative fee of 1.50 percent of that base endowment is then computed and rounded half up to whole cents."
    PRD §3.2: "The required endowment is the base endowment plus the administrative fee."
    PRD §3.2: "The fee is derived once from the fee-free base endowment and added afterwards; no iteration to convergence is performed."
    Design: Difficulty/combinatorial_formula/stewardship_endowment_single_pass_not_fixed_point
    """
    reset_clock()

    world = setup_draft_bank()
    bank = world["bank"]

    assert_cents(
        bank["annual_stewardship_cost_cents"], 4200000, "annual_stewardship_cost_cents"
    )
    assert_cents(
        bank["stewardship_required_cents"],
        113680000,
        "stewardship_required_cents from the pinned single-pass capitalisation",
    )


def test_new_bank_opens_unfunded_frozen_and_without_an_easement():
    """Registration quantifies the endowment requirement but funds none of it:
    the bank opens in DRAFT, FROZEN, with no easement and every credit aggregate
    at zero.

    PRD §3.2: "A newly registered bank opens in `DRAFT` status with a `sales_posture` of `FROZEN`, and every credit aggregate — `total_authorized_credits`, `credits_released`, `credits_sold`, `credits_on_hold` and `credits_available` — initialised to 0.00."
    PRD §3.2: "Its `easement_recorded` flag is false with `easement_recorded_at` and `easement_deed_reference` both null; its `stewardship_funded_cents`, `deferral_count` and `open_quote_count` are 0; and `instrument_executed_at` and `closed_at` are null."
    Design: Difficulty/combinatorial_formula/stewardship_endowment_single_pass_not_fixed_point
    """
    reset_clock()

    world = setup_draft_bank()
    bank = world["bank"]

    assert bank["status"] == "DRAFT", (
        f"a newly registered bank opens in DRAFT, got {bank['status']}"
    )
    assert bank["sales_posture"] == "FROZEN", (
        f"a DRAFT bank is FROZEN by the posture ladder, got {bank['sales_posture']}"
    )
    assert bank["easement_recorded"] is False, "the easement is not recorded at registration"
    assert_cents(bank["stewardship_funded_cents"], 0, "stewardship_funded_cents")
    assert_credits(bank["total_authorized_credits"], 0.00, "total_authorized_credits")
    assert_credits(bank["credits_released"], 0.00, "credits_released")
    assert_credits(bank["credits_available"], 0.00, "credits_available")
