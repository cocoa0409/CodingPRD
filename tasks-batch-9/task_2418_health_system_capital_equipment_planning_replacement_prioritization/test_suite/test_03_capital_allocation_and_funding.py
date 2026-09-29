"""The facility allocation waterfall, the funding cascade and capital conservation."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_service_event,
    assert_allocation,
    assert_cents,
    assert_conserved_capital_identity,
    assert_decimal,
    cast_vote,
    close_intake,
    close_voting,
    fund,
    live_allocation,
    make_asset,
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
    withdraw_funding,
)

CLOCK = "2026-08-01T00:00:00Z"
_PLANNER = TEST_USERS["planner_headers"]
_PLANNER_ALLOC = TEST_USERS["planner_alloc_headers"]
_PLANNER_FUND = TEST_USERS["planner_fund_headers"]

CT_JUSTIFICATION = (
    "CT-16 scanner at end of service life; replacement restores stroke protocol throughput."
)
MRI_JUSTIFICATION = (
    "1.5T magnet loses OEM support in 2026; replacement is required to keep the MRI suite "
    "compliant."
)


# ─── Setup builders ───────────────────────────────────────────────────


def _north_facility():
    return make_facility(
        name="North Regional Hospital", code="NRH", region="NORTH",
        max_concurrent_construction=1,
    )


def _committee_pair():
    chair = make_member("CHAIR", 3, full_name="Dana Whitfield")
    finance = make_member("FINANCE", 2, full_name="Roy Adeyemi")
    return chair, finance


def _approve(request_id, chair, finance):
    cast_vote(request_id, chair["id"], "APPROVE",
              rationale="Safety driver and regulatory mandate both support replacement.")
    cast_vote(request_id, finance["id"], "APPROVE")
    return close_voting(request_id, chair["id"],
                        decision_note="Approved on a 5-of-5 counted weight.")


def _two_facility_pro_rata_cycle():
    """Two facilities scored into one 2027 cycle with a completed PRO_RATA run."""
    pin_clock(CLOCK)
    facility_a = _north_facility()
    facility_b = make_facility(
        name="South Metro Center", code="SMC", region="SOUTH", max_concurrent_construction=2
    )
    department_a = make_department(
        facility_a["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    department_b = make_department(
        facility_b["id"], name="Advanced MRI Suite", modality_scope="MRI"
    )
    asset_a = make_asset(
        facility_a["id"], department_a["id"],
        modality="CT", model_name="Aquilon CT-16", install_date="2020-08-02T00:00:00Z",
        expected_life_years=10, acquisition_cost_cents=240000000,
        oem_support_end_date="2029-01-01T00:00:00Z",
    )
    for event_date in ("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"):
        add_service_event(asset_a["id"], event_date, "CORRECTIVE", downtime_hours=4.00)
    asset_b = make_asset(
        facility_b["id"], department_b["id"],
        modality="MRI", model_name="Helion MR-1.5T", install_date="2020-08-02T00:00:00Z",
        expected_life_years=10, acquisition_cost_cents=300000000,
        oem_support_end_date="2026-12-01T00:00:00Z",
    )
    for event_date in ("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z",
                       "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z"):
        add_service_event(asset_b["id"], event_date, "CORRECTIVE", downtime_hours=0.00)
    cycle = make_cycle(
        plan_year=2027, plan_year_start="2027-01-01T00:00:00Z",
        total_capital_cents=500000000, contingency_pct=0.10, facility_contingency_pct=0.05,
    )
    cycle = open_intake(cycle["id"])
    request_a = make_request(
        cycle["id"], department_a["id"], asset_a["id"],
        clinical_justification=CT_JUSTIFICATION,
        current_annual_volume=1200, projected_annual_volume=1801,
        estimated_capital_cents=250000001, annual_service_contract_cents=12345678,
        disposable_unit_cents=1230, facility_modification_cents=60000000,
        regulatory_mandate_flag=True, mandate_deadline="2027-06-30T00:00:00Z",
    )
    submit(request_a["id"], department_a["id"])
    request_b = make_request(
        cycle["id"], department_b["id"], asset_b["id"],
        clinical_justification=MRI_JUSTIFICATION,
        current_annual_volume=20000, projected_annual_volume=21999,
        estimated_capital_cents=150000000, annual_service_contract_cents=9000001,
        disposable_unit_cents=100, facility_modification_cents=40000000,
        regulatory_mandate_flag=True, mandate_deadline="2027-06-30T00:00:00Z",
    )
    submit(request_b["id"], department_b["id"])
    screen(request_a["id"], "ACCEPT")
    screen(request_b["id"], "ACCEPT")
    close_intake(cycle["id"])
    cycle = run_scoring(cycle["id"])
    cycle = run_allocation(cycle["id"], "PRO_RATA", cycle["version"])
    allocation_a = live_allocation(cycle["id"], facility_a["id"])
    allocation_b = live_allocation(cycle["id"], facility_b["id"])
    return {
        "facility_a": facility_a, "facility_b": facility_b,
        "cycle": refresh_cycle(cycle["id"]),
        "allocation_a": allocation_a, "allocation_b": allocation_b,
    }


def _two_request_cycle_at_its_ceiling():
    """A 2029 cycle whose whole pool is claimed by the higher-scoring of two requests."""
    pin_clock(CLOCK)
    facility = _north_facility()
    department = make_department(
        facility["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    asset_5 = make_asset(
        facility["id"], department["id"],
        modality="CT", model_name="Aquilon CT-24", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=150000000,
        oem_support_end_date="2029-06-01T00:00:00Z",
    )
    asset_6 = make_asset(
        facility["id"], department["id"],
        modality="CT", model_name="Aquilon CT-20", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=90000000,
        oem_support_end_date="2029-06-01T00:00:00Z",
    )
    cycle = make_cycle(
        plan_year=2029, plan_year_start="2029-01-01T00:00:00Z",
        total_capital_cents=100000000, contingency_pct=0.00, facility_contingency_pct=0.00,
    )
    cycle = open_intake(cycle["id"])
    request_3 = make_request(
        cycle["id"], department["id"], asset_5["id"],
        clinical_justification="CT-24 scanner replacement doubles the department's throughput.",
        current_annual_volume=1000, projected_annual_volume=2000,
        estimated_capital_cents=100000000, annual_service_contract_cents=10000000,
        disposable_unit_cents=500,
    )
    request_4 = make_request(
        cycle["id"], department["id"], asset_6["id"],
        clinical_justification="CT-20 scanner replacement lifts the department's volume modestly.",
        current_annual_volume=1000, projected_annual_volume=1200,
        estimated_capital_cents=40000000, annual_service_contract_cents=5000000,
        disposable_unit_cents=300,
    )
    for request in (request_3, request_4):
        submit(request["id"], department["id"])
        screen(request["id"], "ACCEPT")
    close_intake(cycle["id"])
    cycle = run_scoring(cycle["id"])
    chair, finance = _committee_pair()
    cycle = run_allocation(cycle["id"], "PRO_RATA", cycle["version"])
    allocation = live_allocation(cycle["id"], facility["id"])
    _approve(request_3["id"], chair, finance)
    return {
        "cycle": refresh_cycle(cycle["id"]), "allocation": allocation,
        "request_3": refresh_request(request_3["id"]),
        "request_4": refresh_request(request_4["id"]),
        "asset_5": asset_5, "asset_6": asset_6,
    }


def _approved_request_with_whole_pool():
    """A 2030 cycle whose only scored request is APPROVED and has no installation project."""
    pin_clock(CLOCK)
    facility = _north_facility()
    department = make_department(
        facility["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    asset = make_asset(
        facility["id"], department["id"],
        modality="CT", model_name="Aquilon CT-32", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=120000000,
        oem_support_end_date="2029-06-01T00:00:00Z",
    )
    cycle = make_cycle(
        plan_year=2030, plan_year_start="2030-01-01T00:00:00Z",
        total_capital_cents=500000000, contingency_pct=0.00, facility_contingency_pct=0.00,
    )
    cycle = open_intake(cycle["id"])
    request = make_request(
        cycle["id"], department["id"], asset["id"],
        clinical_justification=(
            "CT-32 replacement doubles interventional CT capacity for the 2030 plan year."
        ),
        current_annual_volume=1000, projected_annual_volume=2000,
        estimated_capital_cents=100000000, annual_service_contract_cents=10000000,
        disposable_unit_cents=500,
    )
    submit(request["id"], department["id"])
    screen(request["id"], "ACCEPT")
    close_intake(cycle["id"])
    cycle = run_scoring(cycle["id"])
    chair, finance = _committee_pair()
    cycle = run_allocation(cycle["id"], "PRO_RATA", cycle["version"])
    allocation = live_allocation(cycle["id"], facility["id"])
    request = _approve(request["id"], chair, finance)
    return {
        "cycle": refresh_cycle(cycle["id"]), "allocation": allocation,
        "request": request, "asset": asset,
    }


def _funded_ct_request_with_quote():
    """The CT request funded at its full estimate with a round-one quote pending."""
    pin_clock(CLOCK)
    facility = _north_facility()
    department = make_department(
        facility["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    asset = make_asset(
        facility["id"], department["id"],
        modality="CT", model_name="Aquilon CT-16", install_date="2020-08-02T00:00:00Z",
        expected_life_years=10, acquisition_cost_cents=240000000,
        oem_support_end_date="2029-01-01T00:00:00Z",
    )
    for event_date in ("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"):
        add_service_event(asset["id"], event_date, "CORRECTIVE",
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
    chair, finance = _committee_pair()
    cycle = run_allocation(cycle["id"], "PRO_RATA", cycle["version"])
    allocation = live_allocation(cycle["id"], facility["id"])
    _approve(request["id"], chair, finance)
    request = fund(request["id"])
    contract = make_gpo_contract(
        contract_code="GPO-CT-2027", vendor_name="Aquilon Medical Systems",
        small_tier_pct=0.05, mid_tier_pct=0.12, large_tier_pct=0.18,
        tier_mid_floor_cents=100000000, tier_large_floor_cents=240000000,
        multi_unit_addendum_pct=0.03, trade_in_cap_pct=0.10,
        expires_on="2027-12-31T00:00:00Z",
    )
    quote = make_quote(
        request["id"], contract["id"], vendor_name="Aquilon Medical Systems",
        list_price_cents=250000001, service_escalation_pct=0.04,
        valid_until="2027-12-31T00:00:00Z", trade_in_asset_id=asset["id"],
        trade_in_offer_cents=30000000, multi_unit_count=2, warranty_months=12,
    )
    return {
        "cycle": refresh_cycle(cycle["id"]), "allocation": allocation,
        "request": request, "asset": asset, "quote": quote,
    }


def _two_facility_cycle_with_mixed_committee_outcomes():
    """A 2031 cycle where one request is funded, one deferred and one out of capital."""
    pin_clock(CLOCK)
    facility_a = _north_facility()
    facility_b = make_facility(
        name="South Metro Center", code="SMC", region="SOUTH", max_concurrent_construction=2
    )
    department_a = make_department(
        facility_a["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    department_b = make_department(
        facility_b["id"], name="Advanced MRI Suite", modality_scope="MRI"
    )
    asset_a = make_asset(
        facility_a["id"], department_a["id"],
        modality="CT", model_name="Aquilon CT-24", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=150000000,
        oem_support_end_date="2029-06-01T00:00:00Z",
    )
    asset_b = make_asset(
        facility_a["id"], department_a["id"],
        modality="CT", model_name="Aquilon CT-20", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=90000000,
        oem_support_end_date="2029-06-01T00:00:00Z",
    )
    asset_c = make_asset(
        facility_b["id"], department_b["id"],
        modality="MRI", model_name="Helion MR-1.5T", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=80000000,
        oem_support_end_date="2029-06-01T00:00:00Z",
    )
    cycle = make_cycle(
        plan_year=2031, plan_year_start="2031-01-01T00:00:00Z",
        total_capital_cents=200000000, contingency_pct=0.00, facility_contingency_pct=0.00,
    )
    cycle = open_intake(cycle["id"])
    request_a = make_request(
        cycle["id"], department_a["id"], asset_a["id"],
        clinical_justification="CT-24 replacement doubles interventional CT throughput.",
        current_annual_volume=1000, projected_annual_volume=2000,
        estimated_capital_cents=100000000, annual_service_contract_cents=10000000,
        disposable_unit_cents=500,
    )
    request_b = make_request(
        cycle["id"], department_a["id"], asset_b["id"],
        clinical_justification="CT-20 replacement lifts routine imaging volume modestly.",
        current_annual_volume=1000, projected_annual_volume=1200,
        estimated_capital_cents=80000000, annual_service_contract_cents=8000000,
        disposable_unit_cents=400,
    )
    request_c = make_request(
        cycle["id"], department_b["id"], asset_c["id"],
        clinical_justification="MRI replacement raises the suite's annual scan volume by half.",
        current_annual_volume=1000, projected_annual_volume=1500,
        estimated_capital_cents=60000000, annual_service_contract_cents=6000000,
        disposable_unit_cents=300,
    )
    for request, department in ((request_a, department_a), (request_b, department_a),
                               (request_c, department_b)):
        submit(request["id"], department["id"])
        screen(request["id"], "ACCEPT")
    close_intake(cycle["id"])
    cycle = run_scoring(cycle["id"])
    chair, finance = _committee_pair()
    cycle = run_allocation(cycle["id"], "PRO_RATA", cycle["version"])
    allocation_a = live_allocation(cycle["id"], facility_a["id"])
    allocation_b = live_allocation(cycle["id"], facility_b["id"])
    _approve(request_a["id"], chair, finance)
    cast_vote(request_b["id"], chair["id"], "APPROVE")
    cast_vote(request_b["id"], finance["id"], "REJECT",
              rationale="The volume case does not justify the capital this year.")
    close_voting(request_b["id"], chair["id"],
                 decision_note="Majority support only; deferring to a later cycle.")
    _approve(request_c["id"], chair, finance)
    fund(request_a["id"])
    return {
        "cycle": refresh_cycle(cycle["id"]),
        "allocation_a": refresh_allocation(allocation_a["id"]),
        "allocation_b": refresh_allocation(allocation_b["id"]),
        "request_a": refresh_request(request_a["id"]),
        "request_b": refresh_request(request_b["id"]),
        "request_c": refresh_request(request_c["id"]),
    }


# ─── The two allocation variants on one score set ─────────────────────


def test_rank_ordered_rerun_supersedes_the_pro_rata_grants_it_replaces(api):
    """PRD §3.6: "Under `PRO_RATA`, total demand is the sum of `demand_cents` across the
    participating facilities, and each facility's provisional grant is the smaller of its
    own `demand_cents` and the distributable amount multiplied by that facility's demand
    divided by total demand, taking the **floor** of the quotient rather than rounding it
    — flooring under-commits by design so that the shortfall can be redistributed rather
    than over-committing the pool."
    PRD §3.6: "A permitted re-run moves every existing allocation row of the cycle to
    `posture` `SUPERSEDED` with that row's `version` incremented, builds a fresh
    allocation set from the current composite scores under the newly requested
    `allocation_method`, and overwrites the cycle's `allocation_method`,
    `allocated_by_user_id` and every allocation aggregate, incrementing the cycle's
    `version`."

    Design: Difficulty/dual_variant_calc/allocation_pro_rata_vs_rank_ordered_diverge_on_same_score_set
    """
    ctx = _two_facility_pro_rata_cycle()

    assert_cents(ctx["allocation_b"]["allocated_cents"], 171000000, "PRO_RATA allocated_cents")
    assert_cents(ctx["allocation_a"]["allocated_cents"], 279000000, "PRO_RATA allocated_cents")

    validate_success(
        api.allocate_cycle(ctx["cycle"]["id"],
                           {"allocation_method": "RANK_ORDERED",
                            "expected_cycle_version": ctx["cycle"]["version"]},
                           _PLANNER_ALLOC)
    )

    superseded_b = refresh_allocation(ctx["allocation_b"]["id"])
    superseded_a = refresh_allocation(ctx["allocation_a"]["id"])
    assert superseded_b["posture"] == "SUPERSEDED"
    assert superseded_a["posture"] == "SUPERSEDED"
    assert_cents(superseded_b["allocated_cents"], 171000000, "superseded allocated_cents")
    assert_cents(superseded_a["allocated_cents"], 279000000, "superseded allocated_cents")
    assert_cents(superseded_b["contingency_reserve_cents"], 8550000,
                 "contingency_reserve_cents")
    assert_cents(superseded_a["contingency_reserve_cents"], 13950000,
                 "contingency_reserve_cents")


def test_rank_ordered_fills_the_top_ranked_facility_before_the_next(api):
    """PRD §3.6: "Under `RANK_ORDERED`, the remaining pool starts at the distributable
    amount and the ranking is walked exactly once."
    PRD §3.6: "The top-ranked facility is filled to its full demand before the next
    facility receives anything, so a lower-ranked facility can legitimately receive
    nothing at all."
    PRD §3.6: "Cycle-level aggregates are written from the same run: `unallocated_cents`
    is the distributable amount less the sum of every `allocated_cents`,
    `contingency_drawn_cents` is the sum of every `contingency_reserve_cents`,
    `allocation_count` is the number of rows created, and `exhausted_allocation_count` is
    set to 0."

    Design: Difficulty/dual_variant_calc/allocation_pro_rata_vs_rank_ordered_diverge_on_same_score_set
    """
    ctx = _two_facility_pro_rata_cycle()

    validate_success(
        api.allocate_cycle(ctx["cycle"]["id"],
                           {"allocation_method": "RANK_ORDERED",
                            "expected_cycle_version": ctx["cycle"]["version"]},
                           _PLANNER_ALLOC)
    )

    live_b = live_allocation(ctx["cycle"]["id"], ctx["facility_b"]["id"])
    assert_allocation(live_b)
    assert_cents(live_b["allocated_cents"], 190000000, "allocated_cents")
    assert_cents(live_b["contingency_reserve_cents"], 9500000, "contingency_reserve_cents")
    assert_cents(live_b["committed_cents"], 0, "committed_cents")
    assert_cents(live_b["available_cents"], 190000000, "available_cents")

    live_a = live_allocation(ctx["cycle"]["id"], ctx["facility_a"]["id"])
    assert_allocation(live_a)
    assert_cents(live_a["allocated_cents"], 260000000, "allocated_cents")
    assert_cents(live_a["contingency_reserve_cents"], 13000000, "contingency_reserve_cents")
    assert_cents(live_a["committed_cents"], 0, "committed_cents")
    assert_cents(live_a["available_cents"], 260000000, "available_cents")

    cycle_after = refresh_cycle(ctx["cycle"]["id"])
    assert cycle_after["allocation_method"] == "RANK_ORDERED"
    assert_cents(cycle_after["system_contingency_cents"], 50000000, "system_contingency_cents")
    assert_cents(cycle_after["distributable_cents"], 450000000, "distributable_cents")
    assert_cents(cycle_after["unallocated_cents"], 0, "unallocated_cents")
    assert_cents(cycle_after["contingency_drawn_cents"], 22500000, "contingency_drawn_cents")
    assert cycle_after["allocation_count"] == 2
    assert cycle_after["status"] == "ALLOCATED"


# ─── Funding: the deepest cascade ─────────────────────────────────────


def test_funding_exhausts_the_allocation_and_auto_commits_the_cycle(api):
    """PRD §3.9: "Where the draw brings the allocation's `available_cents` exactly to
    zero, that row's `posture` moves to `EXHAUSTED`."
    PRD §3.9: "Because a row became exhausted, the cycle's `exhausted_allocation_count`
    rises by one; and where that count then equals the cycle's `allocation_count`, the
    cycle itself moves `ALLOCATED → COMMITTED` with the cycle's `version` incremented."

    Design: Difficulty/transitive_cascade/fund_request_cascades_allocation_cycle_and_sibling_deferral
    """
    ctx = _two_request_cycle_at_its_ceiling()

    data = validate_success(api.fund_request(ctx["request_3"]["id"], _PLANNER_FUND))
    assert data["status"] == "FUNDED"
    assert_cents(data["funded_amount_cents"], 100000000, "funded_amount_cents")

    allocation_after = refresh_allocation(ctx["allocation"]["id"])
    assert_cents(allocation_after["allocated_cents"], 100000000, "allocated_cents")
    assert_decimal(allocation_after["weighted_score"], 48.83, "weighted_score")
    assert_cents(allocation_after["committed_cents"], 100000000, "committed_cents")
    assert_cents(allocation_after["available_cents"], 0, "available_cents")
    assert allocation_after["posture"] == "EXHAUSTED"
    assert_conserved_capital_identity(allocation_after)

    cycle_after = refresh_cycle(ctx["cycle"]["id"])
    assert cycle_after["exhausted_allocation_count"] == 1
    assert cycle_after["allocation_count"] == 1
    assert cycle_after["status"] == "COMMITTED"
    assert_cents(cycle_after["unallocated_cents"], 0, "unallocated_cents")
    assert_cents(cycle_after["contingency_drawn_cents"], 0, "contingency_drawn_cents")


def test_funding_defers_the_losing_sibling_and_pends_only_the_funded_asset(api):
    """PRD §3.9: "Because the cycle reached `COMMITTED`, every request of that cycle still
    standing in `SCORED` or `IN_COMMITTEE` is moved to `DEFERRED` — `SCORED → DEFERRED`
    and `IN_COMMITTEE → DEFERRED` — in `created_at` ascending order, each with its own
    `version` incremented."
    PRD §3.9: "and the asset moves from `IN_SERVICE` or `DERATED` to
    `REPLACEMENT_PENDING` — either `IN_SERVICE → REPLACEMENT_PENDING` or `DERATED →
    REPLACEMENT_PENDING` — with the asset's `version` incremented."

    Design: Difficulty/transitive_cascade/fund_request_cascades_allocation_cycle_and_sibling_deferral
    """
    ctx = _two_request_cycle_at_its_ceiling()

    validate_success(api.fund_request(ctx["request_3"]["id"], _PLANNER_FUND))

    sibling = refresh_request(ctx["request_4"]["id"])
    assert sibling["status"] == "DEFERRED"
    assert_decimal(sibling["composite_score"], 41.69, "composite_score")
    funded = refresh_request(ctx["request_3"]["id"])
    assert_decimal(funded["composite_score"], 51.69, "composite_score")

    assert refresh_asset(ctx["asset_5"]["id"])["status"] == "REPLACEMENT_PENDING"
    assert refresh_asset(ctx["asset_6"]["id"])["status"] == "IN_SERVICE"


# ─── Funding and its withdrawal conserve the allocation ───────────────


def test_funding_commits_the_whole_facility_slice(api):
    """PRD §3.9: "The amount drawn is deliberately simple: it is the accepted quote's
    `net_capital_cents` when the request has a quote standing in `ACCEPTED`, and
    `estimated_capital_cents` when it does not, plus `facility_modification_cents` in
    either case."
    PRD §2.10: "Each facility's slice of a cycle's pool is held on a `FacilityAllocation`
    row, and for the life of that row the following identity holds exactly: the sum of
    `allocated_cents` and `released_contingency_cents` equals the sum of
    `committed_cents` and `available_cents`."

    Design: Difficulty/compensating_invariant/fund_then_withdraw_funding_conserves_allocation_capital
    """
    ctx = _approved_request_with_whole_pool()

    validate_success(api.fund_request(ctx["request"]["id"], _PLANNER_FUND))

    allocation_after = refresh_allocation(ctx["allocation"]["id"])
    assert_cents(allocation_after["allocated_cents"], 100000000, "allocated_cents")
    assert_cents(allocation_after["released_contingency_cents"], 0,
                 "released_contingency_cents")
    assert_cents(allocation_after["committed_cents"], 100000000, "committed_cents")
    assert_cents(allocation_after["available_cents"], 0, "available_cents")
    assert allocation_after["posture"] == "EXHAUSTED"
    assert_conserved_capital_identity(allocation_after)

    cycle_after = refresh_cycle(ctx["cycle"]["id"])
    assert cycle_after["exhausted_allocation_count"] == 1
    assert cycle_after["allocation_count"] == 1
    assert cycle_after["status"] == "COMMITTED"

    request_after = refresh_request(ctx["request"]["id"])
    assert request_after["status"] == "FUNDED"
    assert_cents(request_after["funded_amount_cents"], 100000000, "funded_amount_cents")
    assert refresh_asset(ctx["asset"]["id"])["status"] == "REPLACEMENT_PENDING"


def test_withdrawing_funding_returns_the_capital_without_reverting_the_cycle(api):
    """PRD §3.9: "On success the allocation's `committed_cents` falls by the released
    amount, `available_cents` is recomputed and the allocation's `version` is
    incremented; where `available_cents` becomes greater than zero on a row whose
    `posture` was `EXHAUSTED`, the posture returns to `ACTIVE` and the cycle's
    `exhausted_allocation_count` is decremented, though the cycle's own `status` is never
    reverted."
    PRD §3.9: "The asset leaves `REPLACEMENT_PENDING` — `REPLACEMENT_PENDING → DERATED`
    or `REPLACEMENT_PENDING → IN_SERVICE` — moving to `DERATED` when its
    `adjusted_ruls_score` is at most 15.00 or `unresolved_recall` is true and to
    `IN_SERVICE` otherwise, with the asset's `version` incremented."

    Design: Difficulty/compensating_invariant/fund_then_withdraw_funding_conserves_allocation_capital
    """
    ctx = _approved_request_with_whole_pool()
    fund(ctx["request"]["id"])

    released = withdraw_funding(
        ctx["request"]["id"],
        withdrawal_reason="Vendor delivery slipped past the plan year; releasing the capital.",
    )
    assert released["status"] == "APPROVED"
    assert_cents(released["funded_amount_cents"], 0, "funded_amount_cents")

    allocation_after = refresh_allocation(ctx["allocation"]["id"])
    assert_cents(allocation_after["committed_cents"], 0, "committed_cents")
    assert_cents(allocation_after["available_cents"], 100000000, "available_cents")
    assert allocation_after["posture"] == "ACTIVE"
    assert_cents(allocation_after["contingency_reserve_cents"], 0,
                 "contingency_reserve_cents")
    assert allocation_after["contingency_status"] == "HELD"
    assert_conserved_capital_identity(allocation_after)

    cycle_after = refresh_cycle(ctx["cycle"]["id"])
    assert cycle_after["exhausted_allocation_count"] == 0
    assert cycle_after["status"] == "COMMITTED", "the settled cycle is never reverted"

    asset_after = refresh_asset(ctx["asset"]["id"])
    assert asset_after["status"] == "IN_SERVICE"
    assert asset_after["disposition_status"] == "NONE"
    assert_cents(asset_after["trade_in_credit_applied_cents"], 0,
                 "trade_in_credit_applied_cents")

    request_after = refresh_request(ctx["request"]["id"])
    assert_decimal(request_after["composite_score"], 59.69, "composite_score")
    assert_cents(request_after["budgetary_tco_cents"], 160106313, "budgetary_tco_cents")
    assert_cents(request_after["baseline_year1_opex_cents"], 10850000,
                 "baseline_year1_opex_cents")


# ─── Accepting and withdrawing a quote conserve the trade-in claim ─────


def test_accepted_quote_claims_the_trade_in_and_lowers_the_committed_draw(api):
    """PRD §3.8: "Where the accepted quote names a trade-in asset, that asset's
    `trade_in_credit_applied_cents` is set to the quote's `trade_in_credit_cents`, its
    `disposition_status` becomes `HELD_FOR_TRADE_IN`, and its `version` is incremented."
    PRD §2.10: "Every operation that moves capital — funding a request, withdrawing
    funding, accepting a vendor quote that changes the capital term, withdrawing an
    accepted quote, releasing the facility contingency reserve — recomputes
    `available_cents` from that identity and refreshes `posture` in the same write."

    Design: Difficulty/compensating_invariant/quote_accept_then_withdraw_conserves_asset_trade_in_claim
    """
    ctx = _funded_ct_request_with_quote()

    accepted = validate_success(api.accept_quote(ctx["quote"]["id"], _PLANNER, {}))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["gpo_tier"] == "LARGE"
    assert_cents(accepted["net_capital_cents"], 178965001, "net_capital_cents")
    assert_cents(accepted["trade_in_credit_cents"], 19885000, "trade_in_credit_cents")

    asset_after = refresh_asset(ctx["asset"]["id"])
    assert_cents(asset_after["trade_in_credit_applied_cents"], 19885000,
                 "trade_in_credit_applied_cents")
    assert asset_after["disposition_status"] == "HELD_FOR_TRADE_IN"

    request_after = refresh_request(ctx["request"]["id"])
    assert_cents(request_after["funded_amount_cents"], 238965001, "funded_amount_cents")
    assert_cents(request_after["negotiated_operating_5y_cents"], 65266362,
                 "negotiated_operating_5y_cents")
    assert_cents(request_after["negotiated_tco_cents"], 304231363, "negotiated_tco_cents")
    assert_cents(request_after["baseline_year1_opex_cents"], 1882946,
                 "baseline_year1_opex_cents")
    assert_cents(request_after["budgetary_tco_cents"], 388961531, "budgetary_tco_cents")

    allocation_after = refresh_allocation(ctx["allocation"]["id"])
    assert_cents(allocation_after["committed_cents"], 238965001, "committed_cents")
    assert_cents(allocation_after["available_cents"], 71035000, "available_cents")
    assert allocation_after["posture"] == "ACTIVE"
    assert_conserved_capital_identity(allocation_after)

    cycle_after = refresh_cycle(ctx["cycle"]["id"])
    assert cycle_after["exhausted_allocation_count"] == 0
    assert cycle_after["status"] == "COMMITTED"


def test_withdrawing_the_accepted_quote_releases_the_trade_in_and_restores_the_draw(api):
    """PRD §3.8: "Withdrawing an **accepted** quote unwinds the acceptance: the asset's
    `trade_in_credit_applied_cents` returns to 0 and its `disposition_status` moves from
    `HELD_FOR_TRADE_IN` back to `NONE` with the asset's `version` incremented; the
    request's `negotiated_operating_5y_cents` and `negotiated_tco_cents` return to null,
    `baseline_year1_opex_cents` falls back to the budgetary year-one figure, the funded
    amount is recomputed and the request's `version` is incremented; and where the
    request stands in `FUNDED` the allocation's `committed_cents` is adjusted by the
    delta, `available_cents` recomputed, `posture` refreshed and the allocation's
    `version` incremented."

    Design: Difficulty/compensating_invariant/quote_accept_then_withdraw_conserves_asset_trade_in_claim
    """
    ctx = _funded_ct_request_with_quote()
    validate_success(api.accept_quote(ctx["quote"]["id"], _PLANNER, {}))

    withdrawn = validate_success(
        api.withdraw_quote(ctx["quote"]["id"], _PLANNER,
                           {"withdrawal_reason": "Vendor rescinded the trade-in allowance."})
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert_cents(withdrawn["net_capital_cents"], 178965001, "net_capital_cents")
    assert_cents(withdrawn["trade_in_credit_cents"], 19885000, "trade_in_credit_cents")

    asset_after = refresh_asset(ctx["asset"]["id"])
    assert_cents(asset_after["trade_in_credit_applied_cents"], 0,
                 "trade_in_credit_applied_cents")
    assert asset_after["disposition_status"] == "NONE"
    assert asset_after["status"] == "REPLACEMENT_PENDING"

    request_after = refresh_request(ctx["request"]["id"])
    assert request_after["negotiated_operating_5y_cents"] is None
    assert request_after["negotiated_tco_cents"] is None
    assert_cents(request_after["baseline_year1_opex_cents"], 14228624,
                 "baseline_year1_opex_cents")
    assert_cents(request_after["budgetary_tco_cents"], 388961531, "budgetary_tco_cents")
    assert_cents(request_after["funded_amount_cents"], 310000001, "funded_amount_cents")

    allocation_after = refresh_allocation(ctx["allocation"]["id"])
    assert_cents(allocation_after["allocated_cents"], 310000001, "allocated_cents")
    assert_cents(allocation_after["released_contingency_cents"], 0,
                 "released_contingency_cents")
    assert_cents(allocation_after["committed_cents"], 310000001, "committed_cents")
    assert_cents(allocation_after["available_cents"], 0, "available_cents")
    assert allocation_after["posture"] == "EXHAUSTED"
    assert_conserved_capital_identity(allocation_after)

    cycle_after = refresh_cycle(ctx["cycle"]["id"])
    assert cycle_after["exhausted_allocation_count"] == 1
    assert_cents(cycle_after["unallocated_cents"], 139999999, "unallocated_cents")
    assert_cents(cycle_after["contingency_drawn_cents"], 15500000, "contingency_drawn_cents")
    assert cycle_after["status"] == "COMMITTED"
    assert refresh_quote(ctx["quote"]["id"])["status"] == "WITHDRAWN"


# ─── Which fault wins when a fund call breaks two rules ───────────────


def test_funding_a_deferred_request_reports_request_state_not_insufficiency(api):
    """PRD §2.11: "When one call violates several rules, exactly one error is returned:
    the one earliest in the following order."
    PRD §2.11: "16. The replacement request not in the state set the operation requires,
    on every request transition endpoint and on quote creation, installation-project
    creation and audit creation — `ERR_REQUEST_INVALID_STATE`, 409."

    Design: Difficulty/priority_pair_validation_conflict/request_state_beats_allocation_capacity_on_fund
    """
    ctx = _two_facility_cycle_with_mixed_committee_outcomes()

    assert ctx["request_b"]["status"] == "DEFERRED"
    response = api.fund_request(ctx["request_b"]["id"], _PLANNER_FUND)
    validate_error(response, ApiErrorId.ERR_REQUEST_INVALID_STATE.value, 409)

    after = refresh_request(ctx["request_b"]["id"])
    assert after["status"] == "DEFERRED"
    assert_cents(after["funded_amount_cents"], 0, "funded_amount_cents")


def test_funding_an_approved_request_beyond_its_slice_reports_insufficiency(api):
    """PRD §2.11: "39. The draw or delta exceeding the allocation's available capital, on
    request fund, quote accept and quote withdraw — `ERR_ALLOCATION_INSUFFICIENT`, 409."
    PRD §3.9: "Funding requires the request to stand in `APPROVED`, the cycle to stand in
    `ALLOCATED`, an allocation row with `posture` `ACTIVE` or `EXHAUSTED` to exist for the
    cycle and the request's facility, and that row's `available_cents` to be at least the
    computed draw."

    Design: Difficulty/priority_pair_validation_conflict/request_state_beats_allocation_capacity_on_fund
    """
    ctx = _two_facility_cycle_with_mixed_committee_outcomes()

    assert ctx["request_c"]["status"] == "APPROVED"
    response = api.fund_request(ctx["request_c"]["id"], _PLANNER_FUND)
    validate_error(response, ApiErrorId.ERR_ALLOCATION_INSUFFICIENT.value, 409)

    assert refresh_request(ctx["request_c"]["id"])["status"] == "APPROVED"
    assert_cents(refresh_request(ctx["request_c"]["id"])["funded_amount_cents"], 0,
                 "funded_amount_cents")
    assert refresh_request(ctx["request_a"]["id"])["status"] == "FUNDED"
    assert_cents(refresh_request(ctx["request_a"]["id"])["funded_amount_cents"], 100000000,
                 "funded_amount_cents")

    allocation_a = refresh_allocation(ctx["allocation_a"]["id"])
    assert_cents(allocation_a["demand_cents"], 180000000, "demand_cents")
    assert_cents(allocation_a["allocated_cents"], 150000000, "allocated_cents")
    assert_cents(allocation_a["contingency_reserve_cents"], 0, "contingency_reserve_cents")
    assert_cents(allocation_a["committed_cents"], 100000000, "committed_cents")
    assert_cents(allocation_a["available_cents"], 50000000, "available_cents")
    assert allocation_a["posture"] == "ACTIVE"

    allocation_b = refresh_allocation(ctx["allocation_b"]["id"])
    assert_cents(allocation_b["demand_cents"], 60000000, "demand_cents")
    assert_cents(allocation_b["allocated_cents"], 50000000, "allocated_cents")
    assert_cents(allocation_b["committed_cents"], 0, "committed_cents")
    assert_cents(allocation_b["available_cents"], 50000000, "available_cents")
    assert allocation_b["posture"] == "ACTIVE"

    cycle_after = refresh_cycle(ctx["cycle"]["id"])
    assert cycle_after["status"] == "ALLOCATED"
    assert cycle_after["allocation_count"] == 2
    assert_cents(cycle_after["unallocated_cents"], 0, "unallocated_cents")
    assert_cents(cycle_after["contingency_drawn_cents"], 0, "contingency_drawn_cents")
    assert cycle_after["exhausted_allocation_count"] == 0
