"""The pool at named sites: waterfall refusals, re-runs, the fund cascade and its reversal."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    allocation_rows,
    assert_allocation,
    assert_cents,
    assert_conserved_capital_identity,
    assert_decimal,
    cast_vote,
    close_intake,
    close_voting,
    fund,
    get_success_data,
    live_allocation,
    make_asset,
    make_cycle,
    make_member,
    make_request,
    open_intake,
    refresh_allocation,
    refresh_asset,
    refresh_cycle,
    refresh_request,
    run_allocation,
    run_scoring,
    screen,
    setup_allocated_cycle,
    setup_estate,
    setup_intake_open_cycle,
    setup_project,
    setup_quoted_request,
    setup_scored_request,
    setup_two_facility_cycle,
    submit,
    validate_error,
    validate_success,
    withdraw,
)

_PLANNER = TEST_USERS["planner_headers"]
_ALLOCATOR = TEST_USERS["planner_alloc_headers"]
_FUNDER = TEST_USERS["planner_fund_headers"]
_AUDITOR = TEST_USERS["auditor_headers"]


def _two_scored_requests_at_one_facility():
    """Two CT scanners in one department, both requests SCORED, cycle ALLOCATED at 200000000."""
    ctx = setup_intake_open_cycle()
    ctx["sibling_asset"] = make_asset(
        ctx["facility"]["id"], ctx["department"]["id"],
        modality="CT", model_name="Aquilon CT-8B", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=100000000,
        oem_support_end_date="2029-06-01T00:00:00Z",
    )
    ctx["request"] = make_request(
        ctx["cycle"]["id"], ctx["department"]["id"], ctx["asset"]["id"]
    )
    ctx["sibling_request"] = make_request(
        ctx["cycle"]["id"], ctx["department"]["id"], ctx["sibling_asset"]["id"]
    )
    for request in (ctx["request"], ctx["sibling_request"]):
        submit(request["id"], ctx["department"]["id"])
        screen(request["id"], "ACCEPT")
    close_intake(ctx["cycle"]["id"])
    ctx["cycle"] = run_scoring(ctx["cycle"]["id"])
    ctx["cycle"] = run_allocation(
        ctx["cycle"]["id"], "RANK_ORDERED", ctx["cycle"]["version"]
    )
    ctx["allocation"] = live_allocation(ctx["cycle"]["id"], ctx["facility"]["id"])
    ctx["chair"] = make_member("CHAIR", 3, full_name="Dana Okafor")
    cast_vote(ctx["request"]["id"], ctx["chair"]["id"], "APPROVE")
    ctx["request"] = close_voting(ctx["request"]["id"], ctx["chair"]["id"])
    return ctx


def _two_cycles_one_over_reserved_one_empty():
    """Cycle 2027 reserves more than it withheld; cycle 2028 has nothing left to score."""
    ctx = setup_estate()
    over_reserved = open_intake(
        make_cycle(plan_year=2027, plan_year_start="2027-01-01T00:00:00Z",
                   total_capital_cents=500000000, contingency_pct=0.00,
                   facility_contingency_pct=0.05)["id"]
    )
    emptied = open_intake(
        make_cycle(plan_year=2028, plan_year_start="2028-01-01T00:00:00Z",
                   total_capital_cents=500000000, contingency_pct=0.10,
                   facility_contingency_pct=0.05)["id"]
    )
    kept = make_request(over_reserved["id"], ctx["department"]["id"], ctx["asset"]["id"])
    dropped = make_request(emptied["id"], ctx["department"]["id"], ctx["asset"]["id"])
    for request in (kept, dropped):
        submit(request["id"], ctx["department"]["id"])
        screen(request["id"], "ACCEPT")
    withdraw(dropped["id"], ctx["department"]["id"],
             withdrawal_reason="The mandated configuration is unavailable.")
    for cycle in (over_reserved, emptied):
        close_intake(cycle["id"])
    ctx["over_reserved"] = run_scoring(over_reserved["id"])
    ctx["emptied"] = run_scoring(emptied["id"])
    ctx["kept"] = refresh_request(kept["id"])
    ctx["dropped"] = refresh_request(dropped["id"])
    return ctx


def _two_facility_cycle_with_a_chair():
    """NRH and SRH each holding one SCORED request of 100000000, plus a system-wide chair."""
    ctx = setup_two_facility_cycle()
    ctx["chair"] = make_member("CHAIR", 3, full_name="Dana Okafor")
    return ctx


def _approve(ctx, request_key):
    request = ctx[request_key]
    cast_vote(request["id"], ctx["chair"]["id"], "APPROVE")
    ctx[request_key] = close_voting(request["id"], ctx["chair"]["id"])
    return ctx[request_key]


# ─── What the waterfall refuses ───────────────────────────────────────


def test_an_over_reserved_cycle_and_a_cycle_with_nothing_scored_both_write_no_row(api):
    """PRD §3.6: "The drawn contingency may not exceed `system_contingency_cents`; when it would,
    the entire run is rejected with `ERR_CONTINGENCY_RESERVE_EXCEEDED` and no allocation row is
    written at all."
    PRD §3.6: "When no request of the cycle stands in `SCORED` the run is rejected with
    `ERR_NO_ELIGIBLE_REQUESTS`."
    PRD §3.6: "`contingency_reserve_cents` is the facility's `allocated_cents` multiplied by the
    cycle's `facility_contingency_pct`, rounded half up to whole cents; it is drawn from the
    cycle's system contingency **on top of** the facility's allocated capital, and is never taken
    out of `allocated_cents`."
    PRD §2.11: "40. The facility contingency reserves exceeding the system contingency, on an
    allocation run — `ERR_CONTINGENCY_RESERVE_EXCEEDED`, 422."
    PRD §2.11: "42. No scored request to allocate against, on an allocation run —
    `ERR_NO_ELIGIBLE_REQUESTS`, 409."

    Design: Corner/validations/allocate_rejects_an_over_reserved_cycle_and_an_empty_cycle_without_writing_a_row
    """
    ctx = _two_cycles_one_over_reserved_one_empty()
    over_reserved_version = ctx["over_reserved"]["version"]
    emptied_version = ctx["emptied"]["version"]

    validate_error(
        api.allocate_cycle(
            ctx["over_reserved"]["id"],
            {"allocation_method": "PRO_RATA",
             "expected_cycle_version": over_reserved_version},
            _ALLOCATOR,
        ),
        ApiErrorId.ERR_CONTINGENCY_RESERVE_EXCEEDED.value, 422,
    )
    validate_error(
        api.allocate_cycle(
            ctx["emptied"]["id"],
            {"allocation_method": "RANK_ORDERED", "expected_cycle_version": emptied_version},
            _ALLOCATOR,
        ),
        ApiErrorId.ERR_NO_ELIGIBLE_REQUESTS.value, 409,
    )

    assert allocation_rows(ctx["over_reserved"]["id"]) == []
    assert allocation_rows(ctx["emptied"]["id"]) == []

    after_over = refresh_cycle(ctx["over_reserved"]["id"])
    assert after_over["status"] == "SCORING"
    assert after_over["version"] == over_reserved_version
    assert after_over["allocation_method"] is None
    assert after_over["allocated_by_user_id"] is None
    assert after_over["allocation_count"] == 0
    assert_cents(after_over["distributable_cents"], 0, "distributable_cents")
    assert_cents(after_over["contingency_drawn_cents"], 0, "contingency_drawn_cents")

    after_empty = refresh_cycle(ctx["emptied"]["id"])
    assert after_empty["status"] == "SCORING"
    assert after_empty["version"] == emptied_version
    assert after_empty["scored_count"] == 0
    assert ctx["dropped"]["status"] == "WITHDRAWN"

    assert_decimal(ctx["kept"]["composite_score"], 39.69, "composite_score")


def test_replaying_the_version_that_just_allocated_is_refused_and_the_re_run_supersedes(api):
    """PRD §2.8: "Running the facility allocation for a capital cycle requires
    `expected_cycle_version`, carrying the client's last observed `version` of that
    `CapitalCycle`."
    PRD §2.8: "When the value does not match the cycle's current `version`, the run is rejected
    with `ERR_STALE_CYCLE_VERSION` (HTTP 412)."
    PRD §3.6: "A permitted re-run moves every existing allocation row of the cycle to `posture`
    `SUPERSEDED` with that row's `version` incremented, builds a fresh allocation set from the
    current composite scores under the newly requested `allocation_method`, and overwrites the
    cycle's `allocation_method`, `allocated_by_user_id` and every allocation aggregate,
    incrementing the cycle's `version`."
    PRD §2.6: "`version` is an integer that starts at 1 when the row is created and increases by
    exactly one on every mutation of that row, including mutations performed as a side effect of
    an operation on another resource."

    Design: Corner/cross_cutting_complexity_layers/a_re_allocation_needs_the_current_cycle_version_and_supersedes_rather_than_edits
    """
    ctx = setup_scored_request()
    scored_version = ctx["cycle"]["version"]

    first_run = validate_success(
        api.allocate_cycle(
            ctx["cycle"]["id"],
            {"allocation_method": "RANK_ORDERED", "expected_cycle_version": scored_version},
            _ALLOCATOR,
        )
    )
    assert first_run["status"] == "ALLOCATED"
    assert first_run["allocation_count"] == 1
    assert_cents(first_run["distributable_cents"], 500000000, "distributable_cents")
    assert first_run["version"] == scored_version + 1

    validate_error(
        api.allocate_cycle(
            ctx["cycle"]["id"],
            {"allocation_method": "PRO_RATA", "expected_cycle_version": scored_version},
            _ALLOCATOR,
        ),
        ApiErrorId.ERR_STALE_CYCLE_VERSION.value, 412,
    )
    unbumped = refresh_cycle(ctx["cycle"]["id"])
    assert unbumped["version"] == first_run["version"]

    second_run = validate_success(
        api.allocate_cycle(
            ctx["cycle"]["id"],
            {"allocation_method": "PRO_RATA", "expected_cycle_version": unbumped["version"]},
            _ALLOCATOR,
        )
    )
    assert second_run["allocation_method"] == "PRO_RATA"
    assert second_run["allocation_count"] == 1
    assert second_run["exhausted_allocation_count"] == 0
    assert second_run["version"] == unbumped["version"] + 1

    rows = allocation_rows(ctx["cycle"]["id"])
    assert len(rows) == 2
    superseded, live = rows
    assert superseded["posture"] == "SUPERSEDED"
    assert superseded["version"] == 2
    assert live["posture"] == "ACTIVE"
    assert live["version"] == 1
    assert_cents(live["allocated_cents"], 100000000, "allocated_cents")
    assert_cents(live["committed_cents"], 0, "committed_cents")
    assert_cents(live["available_cents"], 100000000, "available_cents")

    patched_facility = validate_success(
        api.patch_facility(ctx["facility"]["id"], {"max_concurrent_construction": 2}, _PLANNER)
    )
    # The facility was minted at version 1 and bumped to 2 when its asset was
    # registered (PRD §3.1 increments `active_asset_count` and the facility's
    # `version`), so this planner edit lands on version 3.
    assert patched_facility["version"] == 3


def test_a_facility_whose_request_left_scored_loses_its_row_and_can_never_be_funded(api):
    """PRD §3.6: "Only requests of the cycle whose status is exactly `SCORED` are eligible."
    PRD §3.6: "Requests in `DRAFT`, `SUBMITTED`, `SCREENED`, `RETURNED`, `IN_COMMITTEE`,
    `DEFERRED`, `WITHDRAWN` or `REJECTED` are excluded, and a facility none of whose departments
    has a `SCORED` request receives no allocation row at all."
    PRD §3.9: "Funding requires the request to stand in `APPROVED`, the cycle to stand in
    `ALLOCATED`, an allocation row with `posture` `ACTIVE` or `EXHAUSTED` to exist for the cycle
    and the request's facility, and that row's `available_cents` to be at least the computed
    draw."
    PRD §2.11: "38. No usable facility allocation, on request fund, quote accept and quote
    withdraw — `ERR_NO_FACILITY_ALLOCATION`, 409."

    Design: Corner/validations/a_re_allocation_supersedes_the_row_of_a_facility_whose_request_left_scored
    """
    ctx = _two_facility_cycle_with_a_chair()
    first_run = run_allocation(ctx["cycle"]["id"], "RANK_ORDERED", ctx["cycle"]["version"])
    assert first_run["allocation_count"] == 2
    assert_cents(first_run["unallocated_cents"], 300000000, "unallocated_cents")
    _approve(ctx, "request_b")

    re_run = validate_success(
        api.allocate_cycle(
            ctx["cycle"]["id"],
            {"allocation_method": "RANK_ORDERED",
             "expected_cycle_version": refresh_cycle(ctx["cycle"]["id"])["version"]},
            _ALLOCATOR,
        )
    )
    assert re_run["allocation_count"] == 1
    assert_cents(re_run["unallocated_cents"], 400000000, "unallocated_cents")
    assert re_run["exhausted_allocation_count"] == 0
    assert re_run["status"] == "ALLOCATED"

    southern_rows = allocation_rows(ctx["cycle"]["id"], ctx["facility_b"]["id"])
    assert len(southern_rows) == 1
    assert southern_rows[0]["posture"] == "SUPERSEDED"

    northern_rows = allocation_rows(ctx["cycle"]["id"], ctx["facility_a"]["id"])
    assert len(northern_rows) == 2
    assert [row["posture"] for row in northern_rows] == ["SUPERSEDED", "ACTIVE"]
    fresh = northern_rows[1]
    assert_allocation(fresh)
    assert_cents(fresh["allocated_cents"], 100000000, "allocated_cents")
    assert_cents(fresh["committed_cents"], 0, "committed_cents")
    assert_cents(fresh["available_cents"], 100000000, "available_cents")

    validate_error(
        api.fund_request(ctx["request_b"]["id"], _FUNDER),
        ApiErrorId.ERR_NO_FACILITY_ALLOCATION.value, 409,
    )
    assert refresh_request(ctx["request_b"]["id"])["status"] == "APPROVED"
    assert refresh_request(ctx["request_a"]["id"])["status"] == "SCORED"


def test_capital_committed_at_one_site_freezes_the_whole_cycles_allocation(api):
    """PRD §3.6: "A re-run is permitted while the cycle sits in `ALLOCATED`, but only while
    nothing has been spent: every allocation row of the cycle whose `posture` is not `SUPERSEDED`
    must have `committed_cents` of zero, and a re-run attempted after any capital has been
    committed is rejected with `ERR_ALLOCATION_ALREADY_COMMITTED`."
    PRD §3.9: "Because a row became exhausted, the cycle's `exhausted_allocation_count` rises by
    one; and where that count then equals the cycle's `allocation_count`, the cycle itself moves
    `ALLOCATED → COMMITTED` with the cycle's `version` incremented."
    PRD §3.6: "Under `PRO_RATA`, total demand is the sum of `demand_cents` across the
    participating facilities, and each facility's provisional grant is the smaller of its own
    `demand_cents` and the distributable amount multiplied by that facility's demand divided by
    total demand, taking the **floor** of the quotient rather than rounding it — flooring
    under-commits by design so that the shortfall can be redistributed rather than
    over-committing the pool."
    PRD §2.11: "41. An allocation re-run attempted after capital has been committed, on an
    allocation run — `ERR_ALLOCATION_ALREADY_COMMITTED`, 409."

    Design: Corner/validations/a_re_allocation_after_any_facility_has_committed_capital_is_rejected
    """
    ctx = _two_facility_cycle_with_a_chair()
    allocated = run_allocation(ctx["cycle"]["id"], "PRO_RATA", ctx["cycle"]["version"])
    assert allocated["allocation_count"] == 2
    assert_cents(allocated["unallocated_cents"], 300000000, "unallocated_cents")
    for facility_key in ("facility_a", "facility_b"):
        row = live_allocation(ctx["cycle"]["id"], ctx[facility_key]["id"])
        assert_cents(row["allocated_cents"], 100000000, "allocated_cents")

    _approve(ctx, "request_a")
    fund(ctx["request_a"]["id"])

    after_fund = refresh_cycle(ctx["cycle"]["id"])
    assert after_fund["status"] == "ALLOCATED"
    assert after_fund["exhausted_allocation_count"] == 1
    assert after_fund["allocation_count"] == 2
    assert refresh_request(ctx["request_b"]["id"])["status"] == "SCORED"

    validate_error(
        api.allocate_cycle(
            ctx["cycle"]["id"],
            {"allocation_method": "RANK_ORDERED",
             "expected_cycle_version": after_fund["version"]},
            _ALLOCATOR,
        ),
        ApiErrorId.ERR_ALLOCATION_ALREADY_COMMITTED.value, 409,
    )

    northern = live_allocation(ctx["cycle"]["id"], ctx["facility_a"]["id"])
    assert_cents(northern["committed_cents"], 100000000, "committed_cents")
    assert_cents(northern["available_cents"], 0, "available_cents")
    assert northern["posture"] == "EXHAUSTED"
    southern = live_allocation(ctx["cycle"]["id"], ctx["facility_b"]["id"])
    assert_cents(southern["committed_cents"], 0, "committed_cents")
    assert southern["posture"] == "ACTIVE"

    unmoved = refresh_cycle(ctx["cycle"]["id"])
    assert unmoved["allocation_method"] == "PRO_RATA"
    assert unmoved["version"] == after_fund["version"]


# ─── The reserve on top of the slice ──────────────────────────────────


def test_releasing_the_facility_reserve_once_lifts_the_ceiling_and_twice_is_a_state_fault(api):
    """PRD §3.6: "Releasing a facility's contingency reserve is a separate planner act."
    PRD §3.6: "It moves `contingency_status` from `HELD` to `RELEASED`, sets
    `released_contingency_cents` equal to `contingency_reserve_cents`, and recomputes
    `available_cents` as `allocated_cents` plus `released_contingency_cents` less
    `committed_cents`."
    PRD §3.6: "A release attempted on a row whose `contingency_status` is already `RELEASED`, or
    on a row whose `posture` is `SUPERSEDED`, is rejected with
    `ERR_CONTINGENCY_ALREADY_RELEASED`."
    PRD §2.10: "Each facility's slice of a cycle's pool is held on a `FacilityAllocation` row, and
    for the life of that row the following identity holds exactly: the sum of `allocated_cents`
    and `released_contingency_cents` equals the sum of `committed_cents` and `available_cents`."
    PRD §2.11: "20. The facility contingency reserve already released, or the allocation
    superseded, on contingency release — `ERR_CONTINGENCY_ALREADY_RELEASED`, 409."

    Design: Corner/validations/releasing_an_already_released_contingency_is_rejected
    """
    ctx = setup_allocated_cycle(
        allocation_method="RANK_ORDERED",
        cycle={"plan_year": 2027, "plan_year_start": "2027-01-01T00:00:00Z",
               "total_capital_cents": 500000000, "contingency_pct": 0.10,
               "facility_contingency_pct": 0.05},
    )
    allocation = ctx["allocation"]
    assert_cents(allocation["allocated_cents"], 100000000, "allocated_cents")
    assert_cents(allocation["contingency_reserve_cents"], 5000000, "contingency_reserve_cents")
    assert allocation["contingency_status"] == "HELD"

    released = validate_success(api.release_contingency(allocation["id"], _ALLOCATOR))
    assert_allocation(released)
    assert released["contingency_status"] == "RELEASED"
    assert_cents(released["released_contingency_cents"], 5000000, "released_contingency_cents")
    assert_cents(released["allocated_cents"], 100000000, "allocated_cents")
    assert_cents(released["committed_cents"], 0, "committed_cents")
    assert_cents(released["available_cents"], 105000000, "available_cents")
    assert released["posture"] == "ACTIVE"
    assert released["version"] == 2
    assert_conserved_capital_identity(released)

    validate_error(
        api.release_contingency(allocation["id"], _ALLOCATOR),
        ApiErrorId.ERR_CONTINGENCY_ALREADY_RELEASED.value, 409,
    )
    unchanged = refresh_allocation(allocation["id"])
    assert unchanged["version"] == 2
    assert_cents(unchanged["available_cents"], 105000000, "available_cents")

    cycle = refresh_cycle(ctx["cycle"]["id"])
    assert_cents(cycle["contingency_drawn_cents"], 5000000, "contingency_drawn_cents")
    assert_cents(cycle["system_contingency_cents"], 50000000, "system_contingency_cents")


# ─── Drawing on the slice and putting it back ─────────────────────────


def test_the_draw_is_the_capital_figure_and_negotiation_is_what_makes_it_fit(api):
    """PRD §3.9: "The amount drawn is deliberately simple: it is the accepted quote's
    `net_capital_cents` when the request has a quote standing in `ACCEPTED`, and
    `estimated_capital_cents` when it does not, plus `facility_modification_cents` in either
    case."
    PRD §3.9: "A quote in `SUPERSEDED` or `WITHDRAWN` is never treated as the accepted one, and
    the five-year figures are never used here — the draw is a capital figure, not a
    cost-of-ownership figure."
    PRD §3.9: "On success the request moves `APPROVED → FUNDED`, `funded_amount_cents` is written
    and the request's `version` is incremented; the allocation's `committed_cents` rises by the
    funded amount, `available_cents` is recomputed and the allocation's `version` is incremented;
    and the asset moves from `IN_SERVICE` or `DERATED` to `REPLACEMENT_PENDING` — either
    `IN_SERVICE → REPLACEMENT_PENDING` or `DERATED → REPLACEMENT_PENDING` — with the asset's
    `version` incremented."
    PRD §2.11: "39. The draw or delta exceeding the allocation's available capital, on request
    fund, quote accept and quote withdraw — `ERR_ALLOCATION_INSUFFICIENT`, 409."

    Design: Corner/validations/funding_over_the_allocation_is_rejected_until_a_negotiated_quote_fits
    """
    ctx = setup_quoted_request(
        base="approved", allocation_method="RANK_ORDERED",
        cycle={"plan_year": 2027, "plan_year_start": "2027-01-01T00:00:00Z",
               "total_capital_cents": 60000000, "contingency_pct": 0.00,
               "facility_contingency_pct": 0.00},
        contract={"contract_code": "GPO-OK"},
    )
    allocation = ctx["allocation"]
    assert_cents(allocation["demand_cents"], 100000000, "demand_cents")
    assert_cents(allocation["allocated_cents"], 60000000, "allocated_cents")
    assert_cents(allocation["available_cents"], 60000000, "available_cents")
    assert_cents(allocation["contingency_reserve_cents"], 0, "contingency_reserve_cents")
    cycle = refresh_cycle(ctx["cycle"]["id"])
    assert_cents(cycle["distributable_cents"], 60000000, "distributable_cents")
    assert_cents(cycle["unallocated_cents"], 0, "unallocated_cents")

    validate_error(
        api.fund_request(ctx["request"]["id"], _FUNDER),
        ApiErrorId.ERR_ALLOCATION_INSUFFICIENT.value, 409,
    )
    assert refresh_request(ctx["request"]["id"])["status"] == "APPROVED"
    assert_cents(refresh_allocation(allocation["id"])["committed_cents"], 0, "committed_cents")

    validate_success(
        api.counter_quote(
            ctx["quote"]["id"],
            {"counter_list_price_cents": 60000000,
             "counter_note": "The committee can only fund 60000000."},
            _PLANNER,
        )
    )
    revised = validate_success(
        api.revise_quote(ctx["quote"]["id"], {"revised_list_price_cents": 60000000}, _PLANNER)
    )
    assert revised["status"] == "SUBMITTED"
    assert revised["negotiation_round"] == 2
    assert revised["gpo_tier"] == "SMALL"
    assert_cents(revised["gpo_discount_cents"], 3000000, "gpo_discount_cents")
    assert_cents(revised["subtotal_cents"], 57000000, "subtotal_cents")
    assert_cents(revised["net_capital_cents"], 57000000, "net_capital_cents")

    validate_success(api.accept_quote(ctx["quote"]["id"], _PLANNER))
    negotiated = refresh_request(ctx["request"]["id"])
    assert_cents(negotiated["negotiated_operating_5y_cents"], 59013226,
                 "negotiated_operating_5y_cents")
    assert_cents(negotiated["negotiated_tco_cents"], 116013226, "negotiated_tco_cents")
    assert_cents(negotiated["funded_amount_cents"], 57000000, "funded_amount_cents")
    assert negotiated["status"] == "APPROVED"
    assert_cents(refresh_allocation(allocation["id"])["committed_cents"], 0, "committed_cents")

    funded = validate_success(api.fund_request(ctx["request"]["id"], _FUNDER))
    assert funded["status"] == "FUNDED"
    assert_cents(funded["funded_amount_cents"], 57000000, "funded_amount_cents")

    after = refresh_allocation(allocation["id"])
    assert_cents(after["committed_cents"], 57000000, "committed_cents")
    assert_cents(after["available_cents"], 3000000, "available_cents")
    assert after["posture"] == "ACTIVE"
    assert_conserved_capital_identity(after)
    after_cycle = refresh_cycle(ctx["cycle"]["id"])
    assert after_cycle["status"] == "ALLOCATED"
    assert after_cycle["exhausted_allocation_count"] == 0
    assert refresh_asset(ctx["asset"]["id"])["status"] == "REPLACEMENT_PENDING"


def test_the_fund_response_already_carries_the_cascade_and_stops_where_it_should(api):
    """PRD §2.10: "Every operation that moves capital — funding a request, withdrawing funding,
    accepting a vendor quote that changes the capital term, withdrawing an accepted quote,
    releasing the facility contingency reserve — recomputes `available_cents` from that identity
    and refreshes `posture` in the same write."
    PRD §2.10: "A cascade never silently skips a hop, and a cascade never partially applies:
    either every hop is written or the whole call is rejected."
    PRD §3.9: "Where the draw brings the allocation's `available_cents` exactly to zero, that
    row's `posture` moves to `EXHAUSTED`."
    PRD §3.6: "A new row starts with `contingency_status` `HELD`, `released_contingency_cents` 0
    and `committed_cents` 0, so `available_cents` equals `allocated_cents`, and `posture` is
    `ACTIVE` when `available_cents` is above zero and `EXHAUSTED` when it is zero."
    PRD §3.9: "Because the cycle reached `COMMITTED`, every request of that cycle still standing
    in `SCORED` or `IN_COMMITTEE` is moved to `DEFERRED` — `SCORED → DEFERRED` and
    `IN_COMMITTEE → DEFERRED` — in `created_at` ascending order, each with its own `version`
    incremented."

    Design: Corner/consistency_model/the_fund_response_is_already_the_post_cascade_state_for_every_touched_row
    """
    ctx = _two_scored_requests_at_one_facility()
    assert_cents(ctx["allocation"]["allocated_cents"], 200000000, "allocated_cents")

    funded = validate_success(api.fund_request(ctx["request"]["id"], _FUNDER))
    assert funded["status"] == "FUNDED"
    assert_cents(funded["funded_amount_cents"], 100000000, "funded_amount_cents")

    echoed = get_success_data(api.get_request(ctx["request"]["id"], _AUDITOR))
    assert echoed["status"] == "FUNDED"
    assert_cents(echoed["funded_amount_cents"], 100000000, "funded_amount_cents")

    rows = get_success_data(
        api.list_allocations(_AUDITOR, params={"cycle_id": ctx["cycle"]["id"]})
    )
    assert len(rows) == 1
    allocation = rows[0]
    assert_cents(allocation["allocated_cents"], 200000000, "allocated_cents")
    assert_cents(allocation["committed_cents"], 100000000, "committed_cents")
    assert_cents(allocation["available_cents"], 100000000, "available_cents")
    assert allocation["posture"] == "ACTIVE"
    assert allocation["version"] == 2
    assert_conserved_capital_identity(allocation)

    cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], _AUDITOR))
    assert cycle["status"] == "ALLOCATED"
    assert cycle["exhausted_allocation_count"] == 0
    assert cycle["allocation_count"] == 1
    assert get_success_data(api.get_request(ctx["sibling_request"]["id"], _AUDITOR))[
        "status"] == "SCORED"

    asset = get_success_data(api.get_asset(ctx["asset"]["id"], _AUDITOR))
    assert asset["status"] == "REPLACEMENT_PENDING"
    assert asset["version"] == 2
    assert_decimal(asset["adjusted_ruls_score"], 25.00, "adjusted_ruls_score")


def test_funding_cannot_be_unwound_while_a_project_is_still_on_the_books(api):
    """PRD §3.9: "Withdrawing funding accepts an optional `withdrawal_reason`, requires the
    request to stand in `FUNDED`, and requires that no installation project of the request has
    `record_status` `ACTIVE` — an active project must be cancelled first, and otherwise the
    withdrawal is rejected with `ERR_PROJECT_ACTIVE`."
    PRD §3.9: "On success the allocation's `committed_cents` falls by the released amount,
    `available_cents` is recomputed and the allocation's `version` is incremented; where
    `available_cents` becomes greater than zero on a row whose `posture` was `EXHAUSTED`, the
    posture returns to `ACTIVE` and the cycle's `exhausted_allocation_count` is decremented,
    though the cycle's own `status` is never reverted."
    PRD §3.9: "The asset leaves `REPLACEMENT_PENDING` — `REPLACEMENT_PENDING → DERATED` or
    `REPLACEMENT_PENDING → IN_SERVICE` — moving to `DERATED` when its `adjusted_ruls_score` is at
    most 15.00 or `unresolved_recall` is true and to `IN_SERVICE` otherwise, with the asset's
    `version` incremented."
    PRD §3.10: "It accepts an optional `cancellation_reason`, requires `record_status` `ACTIVE`
    with `go_live_at` still null, moves `record_status` from `ACTIVE` to `CANCELLED` — the
    transition `ACTIVE → CANCELLED` on that axis — and increments the project's `version`."
    PRD §2.11: "50. An active installation project blocking a funding withdrawal, on
    withdraw-funding — `ERR_PROJECT_ACTIVE`, 409."

    Design: Corner/validations/withdraw_funding_is_blocked_until_the_installation_project_is_cancelled
    """
    ctx = setup_project(allocation_method="RANK_ORDERED")
    reason = {"withdrawal_reason": "Vendor cannot deliver in the plan year."}

    validate_error(
        api.withdraw_funding(ctx["request"]["id"], _FUNDER, reason),
        ApiErrorId.ERR_PROJECT_ACTIVE.value, 409,
    )
    blocked = refresh_request(ctx["request"]["id"])
    assert blocked["status"] == "FUNDED"
    assert_cents(blocked["funded_amount_cents"], 100000000, "funded_amount_cents")
    assert_cents(
        refresh_allocation(ctx["allocation"]["id"])["committed_cents"], 100000000,
        "committed_cents",
    )

    cancelled = validate_success(
        api.cancel_project(
            ctx["project"]["id"], _PLANNER, {"cancellation_reason": "Funding is being reversed."}
        )
    )
    assert cancelled["record_status"] == "CANCELLED"
    assert cancelled["construction_status"] == ctx["project"]["construction_status"]
    assert cancelled["equipment_status"] == ctx["project"]["equipment_status"]

    unwound = validate_success(api.withdraw_funding(ctx["request"]["id"], _FUNDER, reason))
    assert unwound["status"] == "APPROVED"
    assert_cents(unwound["funded_amount_cents"], 0, "funded_amount_cents")

    allocation = refresh_allocation(ctx["allocation"]["id"])
    assert_cents(allocation["committed_cents"], 0, "committed_cents")
    assert_cents(allocation["available_cents"], 100000000, "available_cents")
    assert allocation["posture"] == "ACTIVE"
    assert_conserved_capital_identity(allocation)

    cycle = refresh_cycle(ctx["cycle"]["id"])
    assert cycle["exhausted_allocation_count"] == 0
    assert cycle["status"] == "COMMITTED"

    assert refresh_asset(ctx["asset"]["id"])["status"] == "IN_SERVICE"


def test_a_withdrawal_re_derives_both_scored_counters_before_the_pool_is_split(api):
    """PRD §3.3: "The cycle carries the running arithmetic of the plan year, all of it written by
    the allocation machinery rather than by a caller: `system_contingency_cents` and
    `distributable_cents` and `unallocated_cents` and `contingency_drawn_cents`, the count
    `allocation_count` of allocation rows for the cycle whose posture is not `SUPERSEDED`, the
    count `exhausted_allocation_count` of allocation rows whose posture is `EXHAUSTED`,
    `scored_count` as the number of the cycle's requests that stand in `SCORED` after the most
    recent scoring run, and `expedited_count` as the number of the cycle's requests whose
    `expedited` flag is currently true."
    PRD §3.4: "Withdrawal accepts an optional `withdrawal_reason` and performs the transition to
    `WITHDRAWN` from any of `DRAFT`, `RETURNED`, `SUBMITTED`, `SCREENED` or `SCORED` — so
    `DRAFT → WITHDRAWN`, `RETURNED → WITHDRAWN`, `SUBMITTED → WITHDRAWN`, `SCREENED → WITHDRAWN`
    and `SCORED → WITHDRAWN` are all permitted, incrementing the request's `version`; where the
    request was `SCORED`, the owning cycle's `scored_count` and `expedited_count` are refreshed
    and the cycle's `version` is incremented."
    PRD §3.5: "Finally, `expedited` is true when `composite_score` is at least 85.00, and false
    below it; the comparison is inclusive at 85.00."
    PRD §3.6: "Under `RANK_ORDERED`, the remaining pool starts at the distributable amount and the
    ranking is walked exactly once."

    Design: Corner/cross_cutting_complexity_layers/the_cycle_counters_reconcile_after_a_score_a_withdrawal_and_an_allocation
    """
    ctx = setup_intake_open_cycle()
    mandated_asset = make_asset(
        ctx["facility"]["id"], ctx["department"]["id"],
        modality="CT", model_name="Aquilon CT-X", install_date="2016-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=100000000,
        oem_support_end_date="2026-12-01T00:00:00Z",
    )
    routine = make_request(ctx["cycle"]["id"], ctx["department"]["id"], ctx["asset"]["id"])
    mandated = make_request(
        ctx["cycle"]["id"], ctx["department"]["id"], mandated_asset["id"],
        regulatory_mandate_flag=True, mandate_deadline="2027-06-01T00:00:00Z",
    )
    for request in (routine, mandated):
        submit(request["id"], ctx["department"]["id"])
        screen(request["id"], "ACCEPT")
    close_intake(ctx["cycle"]["id"])

    scored_cycle = run_scoring(ctx["cycle"]["id"])
    assert scored_cycle["status"] == "SCORING"
    assert scored_cycle["scored_count"] == 2
    assert scored_cycle["expedited_count"] == 1

    hot = refresh_request(mandated["id"])
    assert_decimal(hot["safety_driver"], 75.00, "safety_driver")
    assert_decimal(hot["growth_driver"], 100.00, "growth_driver")
    assert_decimal(hot["regulatory_driver"], 100.00, "regulatory_driver")
    assert_decimal(hot["eos_driver"], 100.00, "eos_driver")
    assert_decimal(hot["composite_score"], 91.25, "composite_score")
    assert hot["expedited"] is True
    cool = refresh_request(routine["id"])
    assert_decimal(cool["composite_score"], 39.69, "composite_score")
    assert cool["expedited"] is False

    gone = withdraw(mandated["id"], ctx["department"]["id"],
                    withdrawal_reason="Vendor withdrew the mandated configuration.")
    assert gone["status"] == "WITHDRAWN"

    after_withdraw = refresh_cycle(ctx["cycle"]["id"])
    assert after_withdraw["scored_count"] == 1
    # PRD §3.3 defines `expedited_count` as "the number of the cycle's requests
    # whose `expedited` flag is currently true" — no status restriction, and
    # withdrawal never clears the flag, so the refreshed count still reads 1
    # while `scored_count` (requests "that stand in SCORED") drops to 1.
    assert after_withdraw["expedited_count"] == 1
    assert after_withdraw["version"] == scored_cycle["version"] + 1

    allocated = run_allocation(
        ctx["cycle"]["id"], "RANK_ORDERED", after_withdraw["version"]
    )
    assert allocated["status"] == "ALLOCATED"
    assert allocated["allocation_count"] == 1
    assert_cents(allocated["distributable_cents"], 500000000, "distributable_cents")
    assert allocated["exhausted_allocation_count"] == 0
    row = live_allocation(ctx["cycle"]["id"], ctx["facility"]["id"])
    assert_cents(row["allocated_cents"], 100000000, "allocated_cents")

    survivors = get_success_data(
        api.list_requests(_PLANNER, params={"cycle_id": ctx["cycle"]["id"], "status": "SCORED"})
    )
    assert len(survivors) == 1
    assert survivors[0]["id"] == routine["id"]
