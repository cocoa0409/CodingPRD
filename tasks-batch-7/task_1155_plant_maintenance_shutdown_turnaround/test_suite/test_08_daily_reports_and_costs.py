"""Daily cost reporting and the EAC cost forecast: tiered line pricing, pinned
rounding order, overhead tier keying, overtime boundaries, ledger
approve/void compensation, duplicate and sequence guards, approval SoD, and
the committed-vs-provisional forecast variants."""
from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_success,
    create_draft_report,
    create_report_line,
    create_shift,
    report_discovery,
    set_clock,
    setup_execution_turnaround,
    setup_submitted_report,
    submit_report,
    triage_discovery,
    make_supervisor_headers,
    make_controller_headers,
    make_manager_headers,
)

REPORTER = "tm-100"
DECIDER = "tm-200"


def _draft_and_submit(ctx, report_date, lines):
    """Draft a report as the contractor's supervisor and submit it."""
    contractor_id = ctx["contractor"]["id"]
    report = create_draft_report(
        ctx["turnaround"]["id"], contractor_id, report_date, lines
    )
    return submit_report(report["id"], contractor_id)


def test_rejected_discovery_quote_leaves_provisional_forecast(api, manager_headers):
    """PRD §3.6: "An `outcome` of `REJECTED` removes the quote from the
    forecast's pending set and recomputes the forecast — which can itself relax
    the turnaround's `cost_posture`."
    PRD §3.8: "The pending-quote figure is the sum of `quoted_cost_cents` over
    discoveries standing in `REPORTED` or `TRIAGED`."

    Design: Corner/calculations/eac_rejected_discovery_leaves_provisional
    """
    ctx = setup_execution_turnaround(
        authorized_budget_cents=400000,
        work_item_overrides={
            "title": "Anchor", "risk_class": "B", "estimated_hours": 100,
            "estimated_cost_cents": 200000,
        },
    )
    t_id = ctx["turnaround"]["id"]
    discovery = report_discovery(
        t_id, REPORTER, description="Corroded trays",
        quoted_cost_cents=300000, quoted_hours=40,
    )
    assert discovery["status"] == "REPORTED"

    before = validate_success(api.get_cost_summary(t_id, manager_headers))
    assert before["committed_cost_cents"] == 200000
    assert before["forecast_provisional_cents"] == 500000, (
        "200000 committed + 300000 pending quote"
    )
    assert before["cost_posture"] == "AT_RISK"

    triage_discovery(discovery["id"])
    validate_success(
        api.decide_discovery(
            discovery["id"], {"outcome": "REJECTED"}, make_manager_headers(DECIDER)
        )
    )

    after = validate_success(api.get_cost_summary(t_id, manager_headers))
    assert after["forecast_provisional_cents"] == 200000, (
        "rejected quote leaves the pending set"
    )
    assert after["cost_posture"] == "WITHIN_BUDGET"


def test_approve_by_submitter_rejected_as_sod(api):
    """PRD §3.8: "Approval belongs to the `CostController`, and segregation of
    duties applies again: the approver's `X-User-ID` must differ from the
    recorded `submitted_by_user_id`, else `ERR_SOD_VIOLATION`."

    Design: Corner/validations/sod_report_approve_by_submitter_rejected
    """
    ctx = setup_submitted_report()
    report = ctx["report"]
    contractor_id = ctx["contractor"]["id"]
    assert report["submitted_by_user_id"] == contractor_id

    resp = api.approve_daily_report(
        report["id"], make_controller_headers(contractor_id)
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    stayed = validate_success(api.get_daily_report(report["id"], make_controller_headers("cc-9")))
    assert stayed["status"] == "SUBMITTED"

    approved = validate_success(
        api.approve_daily_report(report["id"], make_controller_headers("cc-9"))
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "cc-9"


def test_second_report_same_date_rejected_as_duplicate(api):
    """PRD §3.8: "One report per contractor per date is the rule: while a
    non-`VOIDED` report already exists for the same turnaround, contractor, and
    `report_date`, a further draft is rejected with `ERR_DUPLICATE_REPORT`."

    Design: Corner/validations/duplicate_report_rejected
    """
    ctx = setup_execution_turnaround()
    t_id = ctx["turnaround"]["id"]
    contractor_id = ctx["contractor"]["id"]
    worker = ctx["workers"][0]
    shift = create_shift(t_id)
    set_clock("2026-06-15T21:00:00Z")

    create_draft_report(
        t_id, contractor_id, "2026-06-15",
        [create_report_line(worker["id"], shift["id"], 8, False)],
    )
    resp = api.create_daily_report(
        t_id,
        {
            "report_date": "2026-06-15",
            "lines": [create_report_line(worker["id"], shift["id"], 2, False)],
        },
        make_supervisor_headers(contractor_id),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT)


def test_void_out_of_chronological_order_rejected(api, manager_headers):
    """PRD §3.8: "a `CostController` may void an `APPROVED` report only when no
    `APPROVED` report with a later `report_date` exists for the same turnaround
    and contractor — out-of-order voids are rejected with
    `ERR_REPORT_SEQUENCE` — and a void subtracts the report's
    `total_cost_cents` from `reported_cost_cents`, recomputes the forecast, and
    increments both versions."

    Design: Corner/validations/report_void_sequence_guard
    """
    ctx = setup_execution_turnaround()
    t_id = ctx["turnaround"]["id"]
    contractor_id = ctx["contractor"]["id"]
    worker = ctx["workers"][0]
    shift = create_shift(t_id)
    set_clock("2026-06-16T21:00:00Z")

    r1 = _draft_and_submit(ctx, "2026-06-15",
                           [create_report_line(worker["id"], shift["id"], 8, False)])
    validate_success(api.approve_daily_report(r1["id"], make_controller_headers("cc-1")))
    r2 = _draft_and_submit(ctx, "2026-06-16",
                           [create_report_line(worker["id"], shift["id"], 8, False)])
    validate_success(api.approve_daily_report(r2["id"], make_controller_headers("cc-1")))

    turnaround = validate_success(api.get_turnaround(t_id, manager_headers))
    assert turnaround["reported_cost_cents"] == 149600, "74800 + 74800"

    resp = api.void_daily_report(r1["id"], make_controller_headers("cc-1"))
    validate_error(resp, ApiErrorId.ERR_REPORT_SEQUENCE)

    voided = validate_success(
        api.void_daily_report(r2["id"], make_controller_headers("cc-1"))
    )
    assert voided["status"] == "VOIDED"
    turnaround = validate_success(api.get_turnaround(t_id, manager_headers))
    assert turnaround["reported_cost_cents"] == 74800, (
        "only R1 remains APPROVED after voiding the later R2"
    )


def test_night_hazard_ten_hour_line_pricing(api):
    """PRD §3.8: "For each line, the first eight hours are regular hours; the
    next four — hours beyond eight, up to a further four — form the first
    overtime tier; and any hours beyond twelve form the second tier, so a line
    of exactly twelve hours contributes nothing at all to the second tier. The
    line's base price is its regular hours times the base rate of 8500 cents
    per hour, plus its first-tier hours times the base rate times one and a
    half, plus its second-tier hours times the base rate times two. If the
    line's shift is a `NIGHT` shift the whole base is then multiplied by 1.20,
    and if the line's `hazard_flag` is set the result is further multiplied by
    1.15."

    Design: Difficulty/combinatorial_formula/shift_labor_cost_tiered_night_hazard_premium
    """
    ctx = setup_execution_turnaround(
        work_item_overrides={
            "title": "Exchanger clean", "system_area": "CRU-2-E2",
            "risk_class": "B", "estimated_hours": 60, "estimated_cost_cents": 120000,
        }
    )
    t_id = ctx["turnaround"]["id"]
    worker = ctx["workers"][0]
    night = create_shift(
        t_id, shift_date="2026-06-15", shift_type="NIGHT",
        starts_at="2026-06-15T22:00:00Z", ends_at="2026-06-16T08:00:00Z",
        planned_headcount=5,
    )
    set_clock("2026-06-16T12:00:00Z")

    submitted = _draft_and_submit(
        ctx, "2026-06-16",
        [create_report_line(worker["id"], night["id"], 10, True)],
    )
    # (8*8500 + 2*8500*1.5) * 1.20 * 1.15 = 93500 * 1.38 = 129030
    assert submitted["line_costs_cents"] == [129030], (
        f"line cost {submitted['line_costs_cents']} != [129030]"
    )
    assert submitted["labor_cost_cents"] == 129030


def test_night_hazard_report_overhead_and_total(api):
    """PRD §3.8: "Only now is the line rounded — half-up to a whole cent,
    exactly once — and only after rounding is the per-line cap of 250000 cents
    applied, so the cap can never interact with fractional cents."
    PRD §3.8: "If that base is below 200000 cents the report falls in the low
    tier and its `overhead_cents` is its `labor_cost_cents` multiplied by ten
    percent; at or above that threshold the high tier applies fifteen percent."

    Design: Difficulty/combinatorial_formula/shift_labor_cost_tiered_night_hazard_premium
    """
    ctx = setup_execution_turnaround(
        work_item_overrides={
            "title": "Exchanger clean", "system_area": "CRU-2-E2",
            "risk_class": "B", "estimated_hours": 60, "estimated_cost_cents": 120000,
        }
    )
    t_id = ctx["turnaround"]["id"]
    worker = ctx["workers"][0]
    night = create_shift(
        t_id, shift_date="2026-06-15", shift_type="NIGHT",
        starts_at="2026-06-15T22:00:00Z", ends_at="2026-06-16T08:00:00Z",
        planned_headcount=5,
    )
    set_clock("2026-06-16T12:00:00Z")

    submitted = _draft_and_submit(
        ctx, "2026-06-16",
        [create_report_line(worker["id"], night["id"], 10, True)],
    )
    # tier base 0 (no other APPROVED reports) < 200000 -> LOW 10%
    assert submitted["overhead_cents"] == 12903, (
        f"round_half_up(129030 * 0.10): {submitted['overhead_cents']} != 12903"
    )
    assert submitted["total_cost_cents"] == 141933


def test_per_line_rounding_then_sum_pinned(api):
    """PRD §3.8: "The report's `labor_cost_cents` is then the sum of those
    already-rounded per-line costs. This order is pinned: rounding each line
    first and summing second is the only legal evaluation. Consider two lines
    of one-tenth of an hour each, both hazard-flagged on day shifts: each raw
    line value is 977.5 cents, per-line rounding yields 978 plus 978 for a
    total of 1956 cents, whereas summing first and rounding once would
    illegally yield 1955."

    Design: Difficulty/combinatorial_formula/daily_report_per_line_rounding_beats_sum_then_round
    """
    ctx = setup_execution_turnaround(
        work_item_overrides={
            "title": "Gauge calibration", "system_area": "CRU-2-G",
            "work_type": "INSPECTION", "risk_class": "C",
            "estimated_hours": 20, "estimated_cost_cents": 40000,
        }
    )
    t_id = ctx["turnaround"]["id"]
    worker = ctx["workers"][0]
    day = create_shift(
        t_id, shift_date="2026-06-15", shift_type="DAY",
        starts_at="2026-06-15T08:00:00Z", ends_at="2026-06-15T20:00:00Z",
        planned_headcount=5,
    )
    set_clock("2026-06-15T21:00:00Z")

    submitted = _draft_and_submit(
        ctx, "2026-06-15",
        [
            create_report_line(worker["id"], day["id"], 0.1, True),
            create_report_line(worker["id"], day["id"], 0.1, True),
        ],
    )
    assert submitted["line_costs_cents"] == [978, 978], (
        f"round_half_up(977.5) per line: {submitted['line_costs_cents']} != [978, 978]"
    )
    assert submitted["labor_cost_cents"] == 1956, (
        "per-line-then-sum; the forbidden sum-then-round order would give 1955"
    )


def test_per_line_rounding_overhead_and_total(api):
    """PRD §3.8: "First the system takes the turnaround's `reported_cost_cents`
    excluding this candidate report — that is, the sum of `total_cost_cents`
    over the turnaround's other `APPROVED` reports only. If that base is below
    200000 cents the report falls in the low tier and its `overhead_cents` is
    its `labor_cost_cents` multiplied by ten percent; at or above that
    threshold the high tier applies fifteen percent."
    PRD §3.8: "Only then is `total_cost_cents` computed as `labor_cost_cents`
    plus `overhead_cents`."

    Design: Difficulty/combinatorial_formula/daily_report_per_line_rounding_beats_sum_then_round
    """
    ctx = setup_execution_turnaround(
        work_item_overrides={
            "title": "Gauge calibration", "system_area": "CRU-2-G",
            "work_type": "INSPECTION", "risk_class": "C",
            "estimated_hours": 20, "estimated_cost_cents": 40000,
        }
    )
    t_id = ctx["turnaround"]["id"]
    worker = ctx["workers"][0]
    day = create_shift(
        t_id, shift_date="2026-06-15", shift_type="DAY",
        starts_at="2026-06-15T08:00:00Z", ends_at="2026-06-15T20:00:00Z",
        planned_headcount=5,
    )
    set_clock("2026-06-15T21:00:00Z")

    submitted = _draft_and_submit(
        ctx, "2026-06-15",
        [
            create_report_line(worker["id"], day["id"], 0.1, True),
            create_report_line(worker["id"], day["id"], 0.1, True),
        ],
    )
    assert submitted["overhead_cents"] == 196, (
        f"round_half_up(1956 * 0.10): {submitted['overhead_cents']} != 196"
    )
    assert submitted["total_cost_cents"] == 2152


def _setup_two_report_tier_scenario(api):
    """EXECUTION turnaround; R1 (2026-06-15, one 12h DAY line) SUBMITTED and
    APPROVED (reported_cost_cents == 130900); R2 (2026-06-16, identical line)
    drafted. Clock 2026-06-16T12:00:00Z."""
    ctx = setup_execution_turnaround(
        work_item_overrides={
            "title": "Tower tray swap", "system_area": "CRU-2-T",
            "risk_class": "A", "estimated_hours": 200, "estimated_cost_cents": 300000,
        }
    )
    t_id = ctx["turnaround"]["id"]
    worker = ctx["workers"][0]
    day = create_shift(
        t_id, shift_date="2026-06-15", shift_type="DAY",
        starts_at="2026-06-15T08:00:00Z", ends_at="2026-06-15T20:00:00Z",
        planned_headcount=5,
    )
    set_clock("2026-06-16T12:00:00Z")
    r1 = _draft_and_submit(ctx, "2026-06-15",
                           [create_report_line(worker["id"], day["id"], 12, False)])
    # 12h DAY: 68000 + 4*8500*1.5 = 119000 labor; LOW tier overhead 11900
    assert r1["total_cost_cents"] == 130900
    validate_success(api.approve_daily_report(r1["id"], make_controller_headers("cc-1")))
    return ctx, worker, day, r1


def test_overhead_tier_keyed_on_reported_excluding_candidate(api, manager_headers):
    """PRD §3.8: "First the system takes the turnaround's `reported_cost_cents`
    excluding this candidate report — that is, the sum of `total_cost_cents`
    over the turnaround's other `APPROVED` reports only. If that base is below
    200000 cents the report falls in the low tier and its `overhead_cents` is
    its `labor_cost_cents` multiplied by ten percent; at or above that
    threshold the high tier applies fifteen percent."
    PRD §3.8: "Keying the tier on a total that would include this very report
    is forbidden; the base must be settled before the percentage is applied."

    Design: Difficulty/combinatorial_formula/overhead_tier_keyed_on_reported_excluding_candidate
    """
    ctx, worker, day, _r1 = _setup_two_report_tier_scenario(api)
    turnaround = validate_success(
        api.get_turnaround(ctx["turnaround"]["id"], manager_headers)
    )
    assert turnaround["reported_cost_cents"] == 130900

    r2 = _draft_and_submit(ctx, "2026-06-16",
                           [create_report_line(worker["id"], day["id"], 12, False)])
    assert r2["labor_cost_cents"] == 119000, (
        "68000 regular + 4*8500*1.5 first tier; second tier is empty at 12h"
    )
    # tier base 130900 (excluding this candidate) < 200000 -> LOW 10%
    assert r2["overhead_cents"] == 11900, (
        f"include-candidate order would give 17850: {r2['overhead_cents']} != 11900"
    )


def test_overhead_candidate_exclusion_yields_low_tier_total(api, manager_headers):
    """PRD §3.8: "Keying the tier on a total that would include this very
    report is forbidden; the base must be settled before the percentage is
    applied."
    PRD §3.8: "Only then is `total_cost_cents` computed as `labor_cost_cents`
    plus `overhead_cents`."

    Design: Difficulty/combinatorial_formula/overhead_tier_keyed_on_reported_excluding_candidate
    """
    ctx, worker, day, _r1 = _setup_two_report_tier_scenario(api)

    r2 = _draft_and_submit(ctx, "2026-06-16",
                           [create_report_line(worker["id"], day["id"], 12, False)])
    # LOW tier total: 119000 + 11900 = 130900 (not the HIGH-tier 136850)
    assert r2["total_cost_cents"] == 130900, (
        f"{r2['total_cost_cents']} != 130900"
    )

    validate_success(api.approve_daily_report(r2["id"], make_controller_headers("cc-1")))
    turnaround = validate_success(
        api.get_turnaround(ctx["turnaround"]["id"], manager_headers)
    )
    assert turnaround["reported_cost_cents"] == 261800, "130900 + 130900"


def _setup_overtime_boundary_report(api):
    """EXECUTION turnaround with TWO badged workers; DAY shifts SD1
    (08:00-20:00) and SD2 (08:00-20:30) on 2026-06-15; one DRAFT report dated
    2026-06-15 with a 12.0h line (W1) and a 12.5h line (W2). Clock
    2026-06-15T21:00:00Z. Returns the submitted report."""
    ctx = setup_execution_turnaround(
        num_workers=2,
        work_item_overrides={
            "title": "Line boring", "system_area": "CRU-2-L", "risk_class": "B",
            "estimated_hours": 60, "estimated_cost_cents": 120000,
        },
    )
    t_id = ctx["turnaround"]["id"]
    w1, w2 = ctx["workers"]
    sd1 = create_shift(
        t_id, shift_date="2026-06-15", starts_at="2026-06-15T08:00:00Z",
        ends_at="2026-06-15T20:00:00Z", planned_headcount=3,
    )
    sd2 = create_shift(
        t_id, shift_date="2026-06-15", starts_at="2026-06-15T08:00:00Z",
        ends_at="2026-06-15T20:30:00Z", planned_headcount=3,
    )
    set_clock("2026-06-15T21:00:00Z")
    return _draft_and_submit(
        ctx, "2026-06-15",
        [
            create_report_line(w1["id"], sd1["id"], 12.0, False),
            create_report_line(w2["id"], sd2["id"], 12.5, False),
        ],
    )


def test_overtime_second_tier_zero_at_exactly_twelve_hours(api):
    """PRD §3.8: "For each line, the first eight hours are regular hours; the
    next four — hours beyond eight, up to a further four — form the first
    overtime tier; and any hours beyond twelve form the second tier, so a line
    of exactly twelve hours contributes nothing at all to the second tier."

    Design: Difficulty/boundary_precision_check/overtime_second_tier_starts_strictly_after_twelve_hours
    """
    submitted = _setup_overtime_boundary_report(api)
    line_costs = submitted["line_costs_cents"]
    # 12.0h: 68000 + 4*8500*1.5 + 0 -> the boundary contributes ZERO ot2
    assert line_costs[0] == 119000, (
        f"12.0h line must cost 119000 (no ot2 at the boundary): {line_costs[0]}"
    )


def test_overtime_second_tier_counts_hours_beyond_twelve(api):
    """PRD §3.8: "For each line, the first eight hours are regular hours; the
    next four — hours beyond eight, up to a further four — form the first
    overtime tier; and any hours beyond twelve form the second tier, so a line
    of exactly twelve hours contributes nothing at all to the second tier. The
    line's base price is its regular hours times the base rate of 8500 cents
    per hour, plus its first-tier hours times the base rate times one and a
    half, plus its second-tier hours times the base rate times two."

    Design: Difficulty/boundary_precision_check/overtime_second_tier_starts_strictly_after_twelve_hours
    """
    submitted = _setup_overtime_boundary_report(api)
    # 12.5h: 68000 + 51000 + 0.5*8500*2.0 = 127500
    assert submitted["line_costs_cents"] == [119000, 127500]
    assert submitted["labor_cost_cents"] == 246500
    # LOW tier (tier base 0): round_half_up(246500 * 0.10) = 24650
    assert submitted["overhead_cents"] == 24650
    assert submitted["total_cost_cents"] == 271150


def test_approve_posts_total_to_reported_cost_ledger(api, manager_headers):
    """PRD §3.8: "Approval posts to the ledger — the turnaround's
    `reported_cost_cents` rises by the report's `total_cost_cents`, the cost
    forecast and posture are recomputed, `approved_by_user_id` is recorded, and
    both the report's and the turnaround's `version` increment."

    Design: Difficulty/compensating_invariant/report_approve_then_void_restores_money_ledger
    """
    ctx = setup_submitted_report()  # one 8h DAY line: 68000 + 6800 overhead
    report = ctx["report"]
    assert report["total_cost_cents"] == 74800, (
        f"labor 68000 + overhead 6800: {report['total_cost_cents']} != 74800"
    )

    approved = validate_success(
        api.approve_daily_report(report["id"], make_controller_headers("cc-1"))
    )
    assert approved["status"] == "APPROVED"

    turnaround = validate_success(
        api.get_turnaround(ctx["turnaround"]["id"], manager_headers)
    )
    assert turnaround["reported_cost_cents"] == 74800


def test_void_compensates_ledger_back_to_zero(api, manager_headers):
    """PRD §3.8: "a void subtracts the report's `total_cost_cents` from
    `reported_cost_cents`, recomputes the forecast, and increments both
    versions."

    Design: Difficulty/compensating_invariant/report_approve_then_void_restores_money_ledger
    """
    ctx = setup_submitted_report()
    report = ctx["report"]
    validate_success(api.approve_daily_report(report["id"], make_controller_headers("cc-1")))
    turnaround = validate_success(
        api.get_turnaround(ctx["turnaround"]["id"], manager_headers)
    )
    assert turnaround["reported_cost_cents"] == 74800

    voided = validate_success(
        api.void_daily_report(report["id"], make_controller_headers("cc-1"))
    )
    assert voided["status"] == "VOIDED"

    turnaround = validate_success(
        api.get_turnaround(ctx["turnaround"]["id"], manager_headers)
    )
    assert turnaround["reported_cost_cents"] == 0, (
        "the approve/void compensating pair must leave the money ledger unchanged"
    )


def _setup_pending_quote_scenario(api):
    """EXECUTION turnaround (budget 400000, contingency 1000000) with one
    FROZEN item estimated at 200000 and one REPORTED discovery quoted 300000."""
    ctx = setup_execution_turnaround(
        authorized_budget_cents=400000,
        contingency_budget_cents=1000000,
        work_item_overrides={
            "title": "Reboiler bundle pull", "system_area": "CRU-2-E1",
            "risk_class": "B", "estimated_hours": 100, "estimated_cost_cents": 200000,
        },
    )
    discovery = report_discovery(
        ctx["turnaround"]["id"], REPORTER,
        origin_work_item_id=ctx["items"][0]["id"],
        description="Corroded tray rings found on open",
        quoted_cost_cents=300000, quoted_hours=40,
    )
    assert discovery["status"] == "REPORTED"
    return ctx


def test_provisional_forecast_includes_pending_discovery_quote(api, manager_headers):
    """PRD §3.8: "The committed figure is the sum of `estimated_cost_cents`
    over the turnaround's work items standing in `FROZEN`, `SCHEDULED`,
    `IN_PROGRESS`, `ON_HOLD`, or `REOPENED`. The pending-quote figure is the
    sum of `quoted_cost_cents` over discoveries standing in `REPORTED` or
    `TRIAGED`."
    PRD §3.8: "The provisional variant, `forecast_provisional_cents`, is the
    committed figure plus the pending quotes plus the schedule overrun — it
    diverges from the committed variant by exactly those two terms — and feeds
    the `AT_RISK` leg."

    Design: Difficulty/dual_variant_calc/eac_provisional_diverges_from_committed_on_turnaround_cost
    """
    ctx = _setup_pending_quote_scenario(api)
    summary = validate_success(
        api.get_cost_summary(ctx["turnaround"]["id"], manager_headers)
    )
    assert summary["committed_cost_cents"] == 200000
    assert summary["forecast_committed_cents"] == 200000, (
        "the committed variant excludes pending quotes"
    )
    assert summary["forecast_provisional_cents"] == 500000, (
        "200000 committed + 300000 pending quote + 0 overrun: "
        f"{summary['forecast_provisional_cents']} != 500000"
    )
    assert summary["contingency_remaining_cents"] == 1000000


def test_cost_posture_keys_on_provisional_variant(api, manager_headers):
    """PRD §3.8: "Posture is decided only after both variants are settled:
    `cost_posture` is `OVERRUN` when `committed_cost_cents` exceeds
    `authorized_budget_cents`, otherwise `AT_RISK` when
    `forecast_provisional_cents` exceeds `authorized_budget_cents`, otherwise
    `WITHIN_BUDGET`."

    Design: Difficulty/dual_variant_calc/eac_provisional_diverges_from_committed_on_turnaround_cost
    """
    ctx = _setup_pending_quote_scenario(api)
    summary = validate_success(
        api.get_cost_summary(ctx["turnaround"]["id"], manager_headers)
    )
    # committed 200000 <= budget 400000 < provisional 500000 -> AT_RISK,
    # where the COMMITTED variant alone would read WITHIN_BUDGET
    assert summary["cost_posture"] == "AT_RISK", (
        f"posture must key on the provisional variant: {summary['cost_posture']}"
    )
