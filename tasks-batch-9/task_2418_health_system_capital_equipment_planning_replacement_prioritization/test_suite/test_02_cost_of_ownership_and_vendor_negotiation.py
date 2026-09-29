"""Five-year cost of ownership, group-purchasing pricing and the negotiation loop."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_service_event,
    assert_cents,
    assert_decimal,
    assert_request,
    assert_vendor_quote,
    cast_vote,
    close_intake,
    close_voting,
    fund,
    live_allocation,
    make_asset,
    make_clinical_requester_headers,
    make_cycle,
    make_department,
    make_facility,
    make_gpo_contract,
    make_member,
    make_quote,
    make_request,
    open_intake,
    pin_clock,
    refresh_allocation,
    refresh_asset,
    refresh_cycle,
    refresh_quote,
    refresh_request,
    run_allocation,
    run_scoring,
    screen,
    submit,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
_PLANNER = TEST_USERS["planner_headers"]

CT_JUSTIFICATION = (
    "CT-16 scanner at end of service life; replacement restores stroke protocol throughput."
)
MRI_JUSTIFICATION = (
    "1.5T magnet loses OEM support in 2026; replacement is required to keep the MRI suite "
    "compliant."
)


# ─── Setup builders ───────────────────────────────────────────────────


def _mri_draft_request():
    """SMC's MRI suite with a DRAFT request whose service contract escalates."""
    pin_clock(CLOCK)
    facility = make_facility(
        name="South Metro Center", code="SMC", region="SOUTH", max_concurrent_construction=2
    )
    department = make_department(
        facility["id"], name="Advanced MRI Suite", modality_scope="MRI"
    )
    asset = make_asset(
        facility["id"], department["id"],
        modality="MRI", model_name="Helion MR-1.5T", install_date="2020-08-02T00:00:00Z",
        expected_life_years=10, acquisition_cost_cents=300000000,
        oem_support_end_date="2026-12-01T00:00:00Z",
    )
    for event_date in ("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z",
                       "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z"):
        add_service_event(asset["id"], event_date, "CORRECTIVE", downtime_hours=0.00)
    cycle = make_cycle(
        plan_year=2027, plan_year_start="2027-01-01T00:00:00Z",
        total_capital_cents=500000000, contingency_pct=0.10, facility_contingency_pct=0.05,
    )
    cycle = open_intake(cycle["id"])
    request = make_request(
        cycle["id"], department["id"], asset["id"],
        clinical_justification=MRI_JUSTIFICATION,
        current_annual_volume=20000, projected_annual_volume=21999,
        estimated_capital_cents=150000000, annual_service_contract_cents=9000001,
        disposable_unit_cents=100, facility_modification_cents=40000000,
        regulatory_mandate_flag=True, mandate_deadline="2027-06-30T00:00:00Z",
    )
    return department, request


def _scored_ct_request():
    """NRH's CT-16 estate with the request scored inside a 2027 cycle."""
    pin_clock(CLOCK)
    facility = make_facility(
        name="North Regional Hospital", code="NRH", region="NORTH",
        max_concurrent_construction=1,
    )
    department = make_department(
        facility["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    asset = make_asset(
        facility["id"], department["id"],
        modality="CT", model_name="Aquilon CT-16", install_date="2020-08-02T00:00:00Z",
        expected_life_years=10, acquisition_cost_cents=240000000,
        oem_support_end_date="2029-01-01T00:00:00Z",
    )
    add_service_event(asset["id"], "2026-05-01T00:00:00Z", "CORRECTIVE",
                      downtime_hours=4.00, cost_cents=500000)
    add_service_event(asset["id"], "2026-06-01T00:00:00Z", "CORRECTIVE",
                      downtime_hours=4.00, cost_cents=500000)
    cycle = make_cycle(
        plan_year=2027, plan_year_start="2027-01-01T00:00:00Z",
        total_capital_cents=500000000, contingency_pct=0.10, facility_contingency_pct=0.05,
    )
    cycle = open_intake(cycle["id"])
    request = make_request(
        cycle["id"], department["id"], asset["id"],
        clinical_justification=CT_JUSTIFICATION,
        current_annual_volume=1200, projected_annual_volume=1801,
        estimated_capital_cents=250000001, annual_service_contract_cents=12345678,
        disposable_unit_cents=1230, facility_modification_cents=60000000,
        regulatory_mandate_flag=True, mandate_deadline="2027-06-30T00:00:00Z",
    )
    submit(request["id"], department["id"])
    screen(request["id"], "ACCEPT")
    close_intake(cycle["id"])
    cycle = run_scoring(cycle["id"])
    return facility, department, asset, cycle, refresh_request(request["id"])


def _gpo_contract():
    return make_gpo_contract(
        contract_code="GPO-CT-2027", vendor_name="Aquilon Medical Systems",
        small_tier_pct=0.05, mid_tier_pct=0.12, large_tier_pct=0.18,
        tier_mid_floor_cents=100000000, tier_large_floor_cents=240000000,
        multi_unit_addendum_pct=0.03, trade_in_cap_pct=0.10,
        expires_on="2027-12-31T00:00:00Z",
    )


def _quote_payload(asset_id):
    return {
        "vendor_name": "Aquilon Medical Systems",
        "list_price_cents": 250000001,
        "service_escalation_pct": 0.04,
        "valid_until": "2027-12-31T00:00:00Z",
        "trade_in_asset_id": asset_id,
        "trade_in_offer_cents": 30000000,
        "multi_unit_count": 2,
        "warranty_months": 12,
    }


def _scored_ct_request_with_contract():
    """Scored CT request plus the live group-purchasing contract that will price it."""
    facility, department, asset, cycle, request = _scored_ct_request()
    return facility, department, asset, cycle, request, _gpo_contract()


def _submitted_quote_on_scored_request():
    """A round-one quote standing in SUBMITTED on the scored CT request."""
    facility, department, asset, cycle, request, contract = _scored_ct_request_with_contract()
    quote = make_quote(request["id"], contract["id"], **_quote_payload(asset["id"]))
    return asset, cycle, request, quote


def _funded_ct_request_with_quote():
    """The CT request carried to FUNDED with a round-one quote awaiting acceptance."""
    facility, department, asset, cycle, request = _scored_ct_request()
    chair = make_member("CHAIR", 3, full_name="Dana Whitfield")
    finance = make_member("FINANCE", 2, full_name="Roy Adeyemi")
    cycle = run_allocation(cycle["id"], "PRO_RATA", cycle["version"])
    allocation = live_allocation(cycle["id"], facility["id"])
    cast_vote(request["id"], chair["id"], "APPROVE",
              rationale="Safety driver and regulatory mandate both support replacement.")
    cast_vote(request["id"], finance["id"], "APPROVE")
    close_voting(request["id"], chair["id"],
                 decision_note="Approved on a 5-of-5 counted weight.")
    request = fund(request["id"])
    contract = _gpo_contract()
    quote = make_quote(request["id"], contract["id"], **_quote_payload(asset["id"]))
    return asset, cycle, request, allocation, quote


# ─── Budgetary projection: per-year rounding before the sum ───────────


def test_budgetary_operating_total_rounds_each_plan_year_before_summing(api):
    """PRD §3.4: "In the **budgetary** variant the service contract escalates at five
    percent a year: the service cost of plan year one is `annual_service_contract_cents`
    itself, and the service cost of each later year is `annual_service_contract_cents`
    multiplied by one plus five hundredths raised to the power of the year number less
    one, the product evaluated exactly as a decimal and only then rounded half up to
    whole cents."
    PRD §3.4: "Each of the five years is rounded to whole cents **before** the
    summation, and `budgetary_operating_5y_cents` is the sum over the five years of that
    year's service cost plus that year's disposables cost."

    Design: Difficulty/combinatorial_formula/tco_per_year_rounding_order_pinned_on_service_escalation
    """
    department, request = _mri_draft_request()

    data = validate_success(
        api.submit_request(request["id"], make_clinical_requester_headers(department["id"]))
    )
    assert_request(data)
    assert data["status"] == "SUBMITTED"
    assert_cents(data["budgetary_operating_5y_cents"], 60400201, "budgetary_operating_5y_cents")
    assert data["budgetary_operating_5y_cents"] != 60400202, (
        "rounding a single five-year sum instead of each year overstates the total by a cent"
    )
    assert_cents(data["budgetary_tco_cents"], 250400201, "budgetary_tco_cents")


def test_submission_writes_the_ramped_budgetary_baseline_and_leaves_negotiated_null(api):
    """PRD §3.4: "Disposables are driven by `projected_annual_volume` multiplied by
    `disposable_unit_cents`; plan year one carries a utilization ramp of eighty-five
    hundredths, so year one's disposables are that product multiplied by 0.85 and
    rounded half up to whole cents, while years two through five each carry the full
    unramped product."
    PRD §3.4: "Submission also writes `baseline_year1_opex_cents` as the year-one service
    cost plus the year-one disposables cost of the authoritative variant, which at
    submission time is the budgetary one; this figure is the business-case baseline the
    post-implementation audit measures actual operating cost against."
    PRD §3.4: "The two negotiated-variant fields, `negotiated_operating_5y_cents` and
    `negotiated_tco_cents`, stay null until a vendor quote is accepted."

    Design: Difficulty/combinatorial_formula/tco_per_year_rounding_order_pinned_on_service_escalation
    """
    department, request = _mri_draft_request()

    data = validate_success(
        api.submit_request(request["id"], make_clinical_requester_headers(department["id"]))
    )
    assert_cents(data["baseline_year1_opex_cents"], 10869916, "baseline_year1_opex_cents")
    assert data["negotiated_operating_5y_cents"] is None
    assert data["negotiated_tco_cents"] is None


# ─── Quote pricing: six ordered steps ─────────────────────────────────


def test_quote_pricing_reads_the_tier_from_the_list_price_and_the_addendum_after_discount(api):
    """PRD §3.8: "Step one selects `gpo_tier` from the **list** price alone: `LARGE` when
    `list_price_cents` is at or above `tier_large_floor_cents`, otherwise `MID` when it
    is at or above `tier_mid_floor_cents`, otherwise `SMALL`."
    PRD §3.8: "Step three sets `multi_unit_addendum_cents`, when `multi_unit_count` is at
    least 2, to the list price less the group-purchasing discount, multiplied by
    `multi_unit_addendum_pct`, rounded half up; when the count is 1 the addendum is 0."

    Design: Difficulty/combinatorial_formula/quote_pricing_evaluation_order_pinned_tier_addendum_cap
    """
    _facility, _department, asset, _cycle, request, contract = _scored_ct_request_with_contract()

    data = validate_success(
        api.create_quote(request["id"], {"gpo_contract_id": contract["id"],
                                        **_quote_payload(asset["id"])}, _PLANNER),
        201,
    )
    assert_vendor_quote(data)
    assert data["gpo_tier"] == "LARGE"
    assert_cents(data["gpo_discount_cents"], 45000000, "gpo_discount_cents")
    assert_cents(data["multi_unit_addendum_cents"], 6150000, "multi_unit_addendum_cents")
    assert data["multi_unit_addendum_cents"] != 7500000, (
        "the addendum applies to the post-discount amount, never to the list price"
    )
    assert_cents(data["subtotal_cents"], 198850001, "subtotal_cents")
    assert data["status"] == "SUBMITTED"
    assert data["negotiation_round"] == 1


def test_quote_trade_in_credit_caps_against_the_subtotal_and_raising_it_moves_nothing(api):
    """PRD §3.8: "Step five sets `trade_in_credit_cents`, when a `trade_in_asset_id` is
    present, to the smaller of `trade_in_offer_cents` and the subtotal multiplied by
    `trade_in_cap_pct` rounded half up; with no trade-in asset the credit is 0."
    PRD §3.8: "A new quote is born in `SUBMITTED` with `negotiation_round` 1, and raising
    it changes nothing on the request — the request's cost of ownership and funded amount
    move only when a quote is accepted."

    Design: Difficulty/combinatorial_formula/quote_pricing_evaluation_order_pinned_tier_addendum_cap
    """
    _facility, _department, asset, _cycle, request, contract = _scored_ct_request_with_contract()

    data = validate_success(
        api.create_quote(request["id"], {"gpo_contract_id": contract["id"],
                                        **_quote_payload(asset["id"])}, _PLANNER),
        201,
    )
    assert_cents(data["trade_in_credit_cents"], 19885000, "trade_in_credit_cents")
    assert_cents(data["net_capital_cents"], 178965001, "net_capital_cents")
    assert data["net_capital_cents"] != 177750001, (
        "capping the credit against the list price rather than the subtotal overstates it"
    )

    request_after = refresh_request(request["id"])
    assert_cents(request_after["funded_amount_cents"], 0, "funded_amount_cents")
    assert request_after["negotiated_tco_cents"] is None
    asset_after = refresh_asset(asset["id"])
    assert_cents(asset_after["trade_in_credit_applied_cents"], 0,
                 "trade_in_credit_applied_cents")
    assert asset_after["disposition_status"] == "NONE"


# ─── The two cost-of-ownership variants on one funded request ─────────


def test_accepting_a_quote_makes_the_negotiated_variant_diverge_from_the_budgetary_one(api):
    """PRD §3.8: "The escalation fraction is the quote's own `service_escalation_pct`
    rather than the budgetary five percent."
    PRD §3.8: "The service contract of a year may be waived: year one is waived when
    `warranty_months` is at least 12, and years one and two are both waived when
    `warranty_months` is at least 24 — a twelve-month warranty never waives year two."
    PRD §3.8: "`negotiated_operating_5y_cents` is the five-year sum of per-year service
    plus per-year disposables, and `negotiated_tco_cents` is the negotiated capital term
    plus that operating total."

    Design: Difficulty/dual_variant_calc/tco_budgetary_vs_negotiated_diverge_on_funded_request
    """
    _asset, _cycle, request, _allocation, quote = _funded_ct_request_with_quote()

    data = validate_success(api.accept_quote(quote["id"], _PLANNER, {}))
    assert data["status"] == "ACCEPTED"
    assert_cents(data["net_capital_cents"], 178965001, "net_capital_cents")

    after = refresh_request(request["id"])
    assert_cents(after["budgetary_operating_5y_cents"], 78961530,
                 "budgetary_operating_5y_cents")
    assert_cents(after["budgetary_tco_cents"], 388961531, "budgetary_tco_cents")
    assert_cents(after["negotiated_operating_5y_cents"], 65266362,
                 "negotiated_operating_5y_cents")
    assert_cents(after["negotiated_tco_cents"], 304231363, "negotiated_tco_cents")
    assert after["budgetary_tco_cents"] - after["negotiated_tco_cents"] == 84730168, (
        "the two variants must diverge by the waived year and the negotiated capital term"
    )
    assert_cents(after["baseline_year1_opex_cents"], 1882946, "baseline_year1_opex_cents")


def test_quote_acceptance_recomputes_the_draw_and_returns_the_allocation_to_active(api):
    """PRD §3.8: "Because a quote is now accepted, the negotiated cost-of-ownership
    variant runs and rewrites the request's `negotiated_operating_5y_cents`,
    `negotiated_tco_cents` and `baseline_year1_opex_cents`, the funded amount is
    recomputed into `funded_amount_cents`, and the request's `version` is incremented."
    PRD §3.8: "Where the request already stands in `FUNDED`, the change in funded amount
    is applied as a delta to the facility allocation: `committed_cents` moves by the
    difference, `available_cents` is recomputed, `posture` is refreshed and the
    allocation's `version` is incremented; and where that recomputation lifts
    `available_cents` above zero on a row that had been `EXHAUSTED`, the posture returns
    to `ACTIVE`, the cycle's `exhausted_allocation_count` is decremented and the cycle's
    `version` is incremented."
    PRD §3.8: "Where the accepted quote names a trade-in asset, that asset's
    `trade_in_credit_applied_cents` is set to the quote's `trade_in_credit_cents`, its
    `disposition_status` becomes `HELD_FOR_TRADE_IN`, and its `version` is incremented."

    Design: Difficulty/dual_variant_calc/tco_budgetary_vs_negotiated_diverge_on_funded_request
    """
    asset, cycle, request, allocation, quote = _funded_ct_request_with_quote()

    validate_success(api.accept_quote(quote["id"], _PLANNER, {}))

    after = refresh_request(request["id"])
    assert_cents(after["funded_amount_cents"], 238965001, "funded_amount_cents")
    assert after["status"] == "FUNDED"

    allocation_after = refresh_allocation(allocation["id"])
    assert_cents(allocation_after["allocated_cents"], 310000001, "allocated_cents")
    assert_cents(allocation_after["committed_cents"], 238965001, "committed_cents")
    assert_cents(allocation_after["available_cents"], 71035000, "available_cents")
    assert allocation_after["posture"] == "ACTIVE"

    cycle_after = refresh_cycle(cycle["id"])
    assert cycle_after["exhausted_allocation_count"] == 0
    assert cycle_after["status"] == "COMMITTED", "a committed cycle is sticky"

    asset_after = refresh_asset(asset["id"])
    assert_cents(asset_after["trade_in_credit_applied_cents"], 19885000,
                 "trade_in_credit_applied_cents")
    assert asset_after["disposition_status"] == "HELD_FOR_TRADE_IN"


# ─── The negotiation loop and its round cap ───────────────────────────


def test_counter_increments_the_round_while_revise_reprices_without_advancing_it(api):
    """PRD §3.8: "A counter increments `negotiation_round` by one and re-runs the whole
    six-step pricing over the new list price, rewriting `gpo_tier`,
    `gpo_discount_cents`, `multi_unit_addendum_cents`, `subtotal_cents`,
    `trade_in_credit_cents` and `net_capital_cents`."
    PRD §3.8: "A revise re-runs the pricing but does **not** increment
    `negotiation_round`."

    Design: Difficulty/non_linear_state_machine/vendor_quote_negotiation_cycle_bounded_by_round_cap
    """
    _asset, _cycle, _request, quote = _submitted_quote_on_scored_request()

    countered = validate_success(
        api.counter_quote(quote["id"], {"counter_list_price_cents": 239999999,
                                       "counter_note": "Counter below the LARGE tier floor."},
                          _PLANNER)
    )
    assert countered["status"] == "COUNTERED"
    assert countered["negotiation_round"] == 2
    assert countered["gpo_tier"] == "MID"
    assert_cents(countered["gpo_discount_cents"], 28800000, "gpo_discount_cents")
    assert_cents(countered["multi_unit_addendum_cents"], 6336000, "multi_unit_addendum_cents")
    assert_cents(countered["subtotal_cents"], 204863999, "subtotal_cents")
    assert_cents(countered["trade_in_credit_cents"], 20486400, "trade_in_credit_cents")
    assert_cents(countered["net_capital_cents"], 184377599, "net_capital_cents")

    revised = validate_success(
        api.revise_quote(quote["id"], {"revised_list_price_cents": 245000000}, _PLANNER)
    )
    assert revised["status"] == "SUBMITTED"
    assert revised["negotiation_round"] == 2, "a revise never advances the round counter"
    assert revised["gpo_tier"] == "LARGE"
    assert_cents(revised["net_capital_cents"], 175385700, "net_capital_cents")


def test_revise_beyond_the_third_round_is_refused_and_leaves_the_quote_countered(api):
    """PRD §3.8: "The loop `SUBMITTED → COUNTERED → SUBMITTED` may repeat only while
    `negotiation_round` is at most 3; a revise attempted once the round counter has
    passed 3 is rejected with `ERR_NEGOTIATION_ROUND_LIMIT`."
    PRD §3.8: "Both floors are inclusive, so a list price exactly equal to the large
    floor is `LARGE`."

    Design: Difficulty/non_linear_state_machine/vendor_quote_negotiation_cycle_bounded_by_round_cap
    """
    _asset, _cycle, request, quote = _submitted_quote_on_scored_request()

    validate_success(
        api.counter_quote(quote["id"], {"counter_list_price_cents": 239999999,
                                       "counter_note": "Counter below the LARGE tier floor."},
                          _PLANNER)
    )
    validate_success(
        api.revise_quote(quote["id"], {"revised_list_price_cents": 245000000}, _PLANNER)
    )
    round_three = validate_success(
        api.counter_quote(quote["id"], {"counter_list_price_cents": 241000000}, _PLANNER)
    )
    assert round_three["negotiation_round"] == 3
    assert_cents(round_three["net_capital_cents"], 172522260, "net_capital_cents")
    revised_three = validate_success(
        api.revise_quote(quote["id"], {"revised_list_price_cents": 244000000}, _PLANNER)
    )
    assert revised_three["negotiation_round"] == 3
    assert_cents(revised_three["net_capital_cents"], 174669840, "net_capital_cents")
    round_four = validate_success(
        api.counter_quote(quote["id"], {"counter_list_price_cents": 240000000}, _PLANNER)
    )
    assert round_four["negotiation_round"] == 4
    assert round_four["gpo_tier"] == "LARGE"
    assert_cents(round_four["gpo_discount_cents"], 43200000, "gpo_discount_cents")
    assert_cents(round_four["multi_unit_addendum_cents"], 5904000, "multi_unit_addendum_cents")
    assert_cents(round_four["subtotal_cents"], 190896000, "subtotal_cents")
    assert_cents(round_four["net_capital_cents"], 171806400, "net_capital_cents")

    response = api.revise_quote(quote["id"], {"revised_list_price_cents": 239000000}, _PLANNER)
    validate_error(response, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT.value, 409)

    quote_after = refresh_quote(quote["id"])
    assert quote_after["status"] == "COUNTERED"
    assert quote_after["negotiation_round"] == 4
    assert_cents(quote_after["list_price_cents"], 240000000, "list_price_cents")
    request_after = refresh_request(request["id"])
    assert request_after["status"] == "SCORED"
    assert_cents(request_after["funded_amount_cents"], 0, "funded_amount_cents")
    assert request_after["negotiated_tco_cents"] is None


def test_scored_request_carries_the_capital_weighted_composite_the_quote_prices(api):
    """PRD §3.5: "`composite_score` is that weighted sum less the department's
    `utilization_penalty_points` — an integer point count, subtracted after weighting and
    never itself weighted — rounded half up to two decimals and clamped into the range
    0.00 through 100.00."
    PRD §3.8: "Step two takes the fraction of the selected tier — `large_tier_pct`,
    `mid_tier_pct` or `small_tier_pct` — and sets `gpo_discount_cents` to the list price
    multiplied by that fraction, rounded half up."

    Design: Difficulty/combinatorial_formula/quote_pricing_evaluation_order_pinned_tier_addendum_cap
    """
    _facility, _department, asset, _cycle, request, contract = _scored_ct_request_with_contract()

    assert_decimal(request["composite_score"], 66.18, "composite_score")

    data = validate_success(
        api.create_quote(request["id"], {"gpo_contract_id": contract["id"],
                                        **_quote_payload(asset["id"])}, _PLANNER),
        201,
    )
    assert_cents(data["gpo_discount_cents"], 45000000, "gpo_discount_cents")
    assert data["gpo_tier"] == "LARGE"
