"""Fee pipeline calculations: proration variants and rounding order, the
subsidy cap snapshot and eligibility filter, program cost report variants, and
cycle-total conservation across reverse/repost pairs."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_permit,
    apply_for_permit,
    close_and_export_cycle,
    close_cycle,
    create_employee,
    create_lot,
    create_program,
    create_route_payload,
    create_trip_payload,
    get_cycle,
    issue_violations,
    list_all_charge_entries,
    open_billing_cycle,
    permit_fee_entries,
    post_adjustment,
    put_employee_on_billing_hold,
    set_logical_clock,
    setup_active_permit,
    setup_program_lot_cycle,
    sum_non_reversed,
    trip_event_payload,
    validate_success,
)

ADMIN = TEST_USERS["parking_admin_headers"]
PAYROLL = TEST_USERS["payroll_admin_headers"]
DISPATCHER = TEST_USERS["shuttle_dispatcher_headers"]


# ─── Dual-variant proration (CALENDAR_DAY vs HALF_MONTH) ──────────────

def _setup_dual_proration(api):
    """Two programs identical except proration_mode, each with pool 100000, a
    CORE lot (capacity 10), an OPEN August 2026 cycle, and one DAY employee
    holding an OFFERED permit; clock parked at 2026-08-11T09:00:00Z."""
    set_logical_clock("2026-08-01T00:00:00Z")
    bundles = {}
    for key, mode in (("cal", "CALENDAR_DAY"), ("half", "HALF_MONTH")):
        program = create_program(name=f"P-{key.upper()}",
                                 proration_mode=mode,
                                 monthly_subsidy_pool_cents=100000)
        lot = create_lot(program["id"], code="CORE-A", tier="CORE", capacity=10)
        cycle = open_billing_cycle(program["id"], "2026-08-01", "2026-08-31")
        employee = create_employee(program["id"], badge_number="B001",
                                   shift_pattern="DAY")
        bundles[key] = {"program": program, "lot": lot, "cycle": cycle,
                        "employee": employee}
    # Apply only after the clock reaches the intended activation date, so the
    # offer (default 72h TTL) is still valid when the test accepts it.
    set_logical_clock("2026-08-11T09:00:00Z")
    for key in ("cal", "half"):
        permit = apply_for_permit(bundles[key]["employee"], bundles[key]["lot"])
        assert permit["status"] == "OFFERED"
        bundles[key]["permit"] = permit
    return bundles


def test_proration_calendar_day_posts_7316(api):
    """PRD section 3.4: "Under `CALENDAR_DAY`, the amount is the full-month net
    fee multiplied by the active-day count and divided by the period length,
    rounded half-up to integer cents. Consider a net fee of 10800 cents activated
    on 2026-08-11 inside a 31-day period: the span covers 21 active days, and the
    entry posts 7316 cents."

    Design: Difficulty/dual_variant_calc/proration_calendar_day_vs_half_month
    """
    bundles = _setup_dual_proration(api)
    cal = bundles["cal"]

    accepted = accept_permit(cal["permit"], cal["employee"])
    assert accepted["status"] == "ACTIVE"
    assert accepted["monthly_fee_cents"] == 12000, "gross snapshot: 12000 x 1.0"

    fees = permit_fee_entries(cal["permit"]["id"])
    assert len(fees) == 1
    entry = fees[0]
    # net = 12000 - min(1200, 100000, 12000) = 10800; 21 active days of 31.
    assert entry["amount_cents"] == 7316
    assert entry["span_start"] == "2026-08-11"
    assert entry["span_end"] == "2026-08-31"
    assert entry["status"] == "PENDING"


def test_proration_half_month_posts_full_10800(api):
    """PRD section 3.4: "Under `HALF_MONTH`, the period splits on its fifteenth
    day. For spans that begin a billing — activation and reinstatement spans —
    the entry posts the full net fee when the span's start falls on or before the
    fifteenth day of the period (counting `period_start` as day 1), and half the
    net fee rounded half-up when it starts later." and "The same 10800-cent
    activation on 2026-08-11 starts on day 11 of the period, so `HALF_MONTH`
    posts the full 10800 cents — a deliberate divergence from the 7316 cents the
    calendar-day variant produces."

    Design: Difficulty/dual_variant_calc/proration_calendar_day_vs_half_month
    """
    bundles = _setup_dual_proration(api)
    half = bundles["half"]
    cal = bundles["cal"]

    accepted_half = accept_permit(half["permit"], half["employee"])
    assert accepted_half["status"] == "ACTIVE"
    half_fees = permit_fee_entries(half["permit"]["id"])
    assert len(half_fees) == 1
    assert half_fees[0]["amount_cents"] == 10800, (
        "day_index 11 <= 15 -> the full net fee, not the prorated 7316"
    )

    # Identical inputs produce an identical gross snapshot; only the proration
    # variant diverges.
    accepted_cal = accept_permit(cal["permit"], cal["employee"])
    assert accepted_cal["monthly_fee_cents"] == 12000
    assert accepted_half["monthly_fee_cents"] == 12000


# ─── Per-entry rounding order ─────────────────────────────────────────

class TestProrationPerEntryRoundingOrder:
    """Nested rounding: two identical ROTATING permits each post
    round_half_up(10200 * 10/31) == 3290; the pinned per-entry-then-sum order
    yields 6580, where sum-then-round would yield 6581."""

    def _drive(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        bundle = setup_program_lot_cycle(
            program_overrides={"monthly_subsidy_pool_cents": 0},
            lot_overrides={"capacity": 10},
        )
        e1 = create_employee(bundle["program"]["id"], badge_number="B001",
                             shift_pattern="ROTATING")
        e2 = create_employee(bundle["program"]["id"], badge_number="B002",
                             shift_pattern="ROTATING")
        # Move the clock before applying, so both offers (72h TTL) are still
        # valid at accept time on 2026-08-22.
        set_logical_clock("2026-08-22T08:00:00Z")
        p1 = apply_for_permit(e1, bundle["lot"], vehicle_plate="P001")
        p2 = apply_for_permit(e2, bundle["lot"], vehicle_plate="P002")
        accept_permit(p1, e1)
        accept_permit(p2, e2)
        return bundle, p1, p2

    def test_each_entry_rounded_individually(self, api):
        """PRD section 2.6: "Every charge entry amount is rounded half-up to
        integer cents at posting time, and a billing cycle's total is the plain
        integer sum of its non-reversed entries — never re-rounded after
        summation. This per-entry-then-sum ordering is pinned; sum-then-round is
        not acceptable."

        Design: Difficulty/combinatorial_formula/proration_per_entry_rounding_order
        """
        _bundle, p1, p2 = self._drive(api)
        for permit in (p1, p2):
            fees = permit_fee_entries(permit["id"])
            assert len(fees) == 1
            # gross 10200, no subsidy; 10 active days (08-22..08-31) of 31.
            assert fees[0]["amount_cents"] == 3290, (
                "round_half_up(10200 * 10/31) per entry"
            )
            assert fees[0]["span_start"] == "2026-08-22"
            assert fees[0]["span_end"] == "2026-08-31"

    def test_cycle_total_is_sum_of_rounded_entries(self, api):
        """PRD section 2.6: "Every charge entry amount is rounded half-up to
        integer cents at posting time, and a billing cycle's total is the plain
        integer sum of its non-reversed entries — never re-rounded after
        summation. This per-entry-then-sum ordering is pinned; sum-then-round is
        not acceptable."

        Design: Difficulty/combinatorial_formula/proration_per_entry_rounding_order
        """
        bundle, _p1, _p2 = self._drive(api)
        cycle = get_cycle(bundle["cycle"]["id"])
        assert cycle["total_charges_cents"] == 6580, (
            "3290 + 3290 — NOT 6581, which the rejected sum-then-round order "
            "would produce"
        )


# ─── Tier x shift x pool interaction ──────────────────────────────────

class TestFeeTierShiftPoolInteraction:
    """The min(pct x gross, cap, gross) subsidy binds at the pool-derived
    per-capita cap (500), so a NIGHT permit nets 8500 instead of 5400."""

    def _drive(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        program = create_program(name="P-FEE", monthly_subsidy_pool_cents=1000)
        lot = create_lot(program["id"], code="CORE-A", tier="CORE", capacity=10)
        cycle1 = open_billing_cycle(program["id"], "2026-08-01", "2026-08-31")
        e1 = create_employee(program["id"], badge_number="B001",
                             shift_pattern="DAY")
        e2 = create_employee(program["id"], badge_number="B002",
                             shift_pattern="NIGHT")
        p1 = apply_for_permit(e1, lot, vehicle_plate="P001")
        p2 = apply_for_permit(e2, lot, vehicle_plate="P002")
        accept_permit(p1, e1)
        accept_permit(p2, e2)
        # Close August before opening September, so the program has exactly one
        # OPEN cycle when later fees post ("the program's OPEN cycle", §3.4).
        close_cycle(cycle1["id"])
        # Two ACTIVE, GOOD_STANDING permits -> September cap floor(1000/2) = 500.
        cycle2 = open_billing_cycle(program["id"], "2026-09-01", "2026-09-30")
        # Apply and accept E3 while its offer is fresh (within the 72h TTL).
        set_logical_clock("2026-09-05T09:00:00Z")
        e3 = create_employee(program["id"], badge_number="B003",
                             shift_pattern="NIGHT")
        p3 = apply_for_permit(e3, lot, vehicle_plate="P003")
        accept_permit(p3, e3)
        return {"program": program, "lot": lot, "cycle2": cycle2,
                "p1": p1, "p2": p2, "p3": p3}

    def test_september_cap_and_new_permit_net(self, api):
        """PRD section 3.4: "The full-month subsidy is the smallest of three
        values: the shift subsidy percentage applied to the gross fee and rounded
        half-up, the billed cycle's `subsidy_per_capita_cap_cents` snapshot, and
        the gross fee itself."
        PRD section 3.6: "The cap stored as `subsidy_per_capita_cap_cents` is the
        program's `monthly_subsidy_pool_cents` floor-divided by that eligible
        count, with the denominator raised to a minimum of one so an empty
        program still yields a defined cap."

        Design: Difficulty/combinatorial_formula/fee_tier_shift_pool_interaction
        """
        ctx = self._drive(api)
        cycle2 = get_cycle(ctx["cycle2"]["id"])
        assert cycle2["subsidy_per_capita_cap_cents"] == 500, (
            "floor(1000 / 2) frozen at creation"
        )

        fees = permit_fee_entries(ctx["p3"]["id"])
        assert len(fees) == 1
        entry = fees[0]
        # NIGHT gross 9000; subsidy min(3600, 500, 9000) = 500 -> net 8500;
        # 26 active days (09-05..09-30) of a 30-day period.
        assert entry["amount_cents"] == 7367, "round_half_up(8500 * 26/30)"
        assert entry["span_start"] == "2026-09-05"
        assert entry["span_end"] == "2026-09-30"

    def test_cycle_total_and_subsidy_cents(self, api):
        """PRD section 3.4: "The entry's `amount_cents` is then the net fee
        prorated over the entry's billed span, and its `subsidy_cents` is the
        full subsidy scaled by exactly the same proration ratio and rounded
        half-up; `subsidy_cents` is 0 on every non-fee charge type."
        PRD section 3.6: "Creation also posts a full-period `PENDING`
        `PERMIT_FEE` entry for every permit `ACTIVE` at that instant, each
        spanning `period_start` through `period_end` and priced per §3.4 using
        this cycle's cap for the subsidy derivation."

        Design: Difficulty/combinatorial_formula/fee_tier_shift_pool_interaction
        """
        ctx = self._drive(api)
        fees = permit_fee_entries(ctx["p3"]["id"])
        assert fees[0]["subsidy_cents"] == 433, "round_half_up(500 * 26/30)"

        cycle2 = get_cycle(ctx["cycle2"]["id"])
        # Full-period entries 11500 (DAY: 12000 - 500) and 8500 (NIGHT:
        # 9000 - 500), plus E3's 7367.
        assert cycle2["total_charges_cents"] == 27367


# ─── Subsidy cap evaluation order ─────────────────────────────────────

class TestSubsidyCapEvaluationOrder:
    """The September cap divides pool 900 by the pre-fee eligibility snapshot
    (3 ACTIVE, GOOD_STANDING permits), giving 300 for every shift."""

    def _drive(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        program = create_program(name="P-SUB", monthly_subsidy_pool_cents=900)
        lot = create_lot(program["id"], code="CORE-A", tier="CORE", capacity=10)
        open_billing_cycle(program["id"], "2026-08-01", "2026-08-31")
        employees = {}
        for badge, shift in (("B001", "DAY"), ("B002", "NIGHT"),
                             ("B003", "ROTATING")):
            emp = create_employee(program["id"], badge_number=badge,
                                  shift_pattern=shift)
            permit = apply_for_permit(emp, lot, vehicle_plate=f"P{badge[1:]}")
            accept_permit(permit, emp)
            employees[shift] = (emp, permit)
        cycle2 = open_billing_cycle(program["id"], "2026-09-01", "2026-09-30")
        return program, cycle2, employees

    def test_cap_uses_pre_fee_eligibility_snapshot(self, api):
        """PRD section 3.6: "The server first reads every employee's current
        `standing` — a position settled by prior cycles only — then counts the
        program's permits in `ACTIVE` status whose employee is in
        `GOOD_STANDING`, evaluated across all lots of the program at the creation
        instant. The cap stored as `subsidy_per_capita_cap_cents` is the
        program's `monthly_subsidy_pool_cents` floor-divided by that eligible
        count, with the denominator raised to a minimum of one so an empty
        program still yields a defined cap."

        Design: Difficulty/combinatorial_formula/subsidy_cap_evaluation_order
        """
        _program, cycle2, _employees = self._drive(api)
        cycle2 = get_cycle(cycle2["id"])
        assert cycle2["subsidy_per_capita_cap_cents"] == 300, (
            "floor(900 / 3) using the standing snapshot taken before any "
            "September fee exists"
        )

    def test_full_period_entries_clamped_to_cap(self, api):
        """PRD section 3.6: "Creation also posts a full-period `PENDING`
        `PERMIT_FEE` entry for every permit `ACTIVE` at that instant, each
        spanning `period_start` through `period_end` and priced per §3.4 using
        this cycle's cap for the subsidy derivation."
        PRD section 3.4: "The full-month subsidy is the smallest of three values:
        the shift subsidy percentage applied to the gross fee and rounded
        half-up, the billed cycle's `subsidy_per_capita_cap_cents` snapshot, and
        the gross fee itself. Subsidy percentages are 10% for `DAY`, 40% for
        `NIGHT`, 25% for `ROTATING`, and 15% for `SPLIT`."

        Design: Difficulty/combinatorial_formula/subsidy_cap_evaluation_order
        """
        _program, cycle2, employees = self._drive(api)
        expected = {"DAY": 11700, "NIGHT": 8700, "ROTATING": 9900}
        for shift, (_emp, permit) in employees.items():
            sept = [f for f in permit_fee_entries(permit["id"])
                    if f["cycle_id"] == cycle2["id"]]
            assert len(sept) == 1
            assert sept[0]["span_start"] == "2026-09-01"
            assert sept[0]["span_end"] == "2026-09-30"
            assert sept[0]["amount_cents"] == expected[shift], (
                f"{shift}: nominal subsidy clamped to the 300 cap"
            )

        cycle2 = get_cycle(cycle2["id"])
        assert cycle2["total_charges_cents"] == 30300


def test_subsidy_cap_excludes_billing_hold_employees(api):
    """PRD section 3.6: "The server first reads every employee's current
    `standing` — a position settled by prior cycles only — then counts the
    program's permits in `ACTIVE` status whose employee is in `GOOD_STANDING`,
    evaluated across all lots of the program at the creation instant."
    PRD section 3.6: "Creation also posts a full-period `PENDING` `PERMIT_FEE`
    entry for every permit `ACTIVE` at that instant, each spanning `period_start`
    through `period_end` and priced per §3.4 using this cycle's cap for the
    subsidy derivation."

    Design: Corner/calculations/subsidy_cap_excludes_billing_hold_employees
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    program = create_program(name="P-FILT", monthly_subsidy_pool_cents=900)
    lot = create_lot(program["id"], code="CORE-A", tier="CORE", capacity=10)
    cycle1 = open_billing_cycle(program["id"], "2026-08-01", "2026-08-31")
    permits = {}
    employees = {}
    for badge, shift in (("B001", "DAY"), ("B002", "NIGHT"), ("B003", "ROTATING")):
        emp = create_employee(program["id"], badge_number=badge,
                              shift_pattern=shift)
        permit = apply_for_permit(emp, lot, vehicle_plate=f"P{badge[1:]}")
        accept_permit(permit, emp)
        employees[shift] = emp
        permits[shift] = permit

    # E2 (NIGHT) goes onto BILLING_HOLD before the September cycle is created.
    put_employee_on_billing_hold(cycle1["id"], employees["NIGHT"]["id"],
                                 amount_cents=100)

    cycle2 = open_billing_cycle(program["id"], "2026-09-01", "2026-09-30")
    cycle2 = get_cycle(cycle2["id"])
    assert cycle2["subsidy_per_capita_cap_cents"] == 450, (
        "only the two GOOD_STANDING permit holders count: floor(900 / 2)"
    )

    expected = {"DAY": 11550, "NIGHT": 8550, "ROTATING": 9750}
    for shift, permit in permits.items():
        sept = [f for f in permit_fee_entries(permit["id"])
                if f["cycle_id"] == cycle2["id"]]
        assert len(sept) == 1
        assert sept[0]["amount_cents"] == expected[shift], (
            f"{shift}: subsidy clamped to 450 for every ACTIVE permit, "
            "including the held one"
        )
    assert cycle2["total_charges_cents"] == 29850


# ─── Cost report: GROSS vs NET variants ───────────────────────────────

class TestCostReportGrossVsNet:
    """One aggregation, two variants: gross ignores subsidy spend, net
    subtracts it."""

    def _drive(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        program = create_program(name="P-COST", monthly_subsidy_pool_cents=100000)
        lot = create_lot(program["id"], code="CORE-A", tier="CORE", capacity=10,
                         monthly_maintenance_cents=30000)
        create_lot(program["id"], code="REM-A", tier="REMOTE", capacity=10,
                   monthly_maintenance_cents=15000)
        open_billing_cycle(program["id"], "2026-08-01", "2026-08-31")
        for badge, shift in (("B001", "DAY"), ("B002", "NIGHT"),
                             ("B003", "ROTATING")):
            emp = create_employee(program["id"], badge_number=badge,
                                  shift_pattern=shift)
            permit = apply_for_permit(emp, lot, vehicle_plate=f"P{badge[1:]}")
            accept_permit(permit, emp)
        route = validate_success(
            api.create_route(create_route_payload(lot["id"]), DISPATCHER), 201
        )
        # Three COMPLETED trips at 4000 cents each.
        for hh, boarded in (("08:00", 12), ("08:10", 8), ("08:20", 5)):
            trip = validate_success(
                api.create_trip(
                    create_trip_payload(route["id"], f"2026-08-02T{hh}:00Z"),
                    DISPATCHER,
                ),
                201,
            )
            set_logical_clock(f"2026-08-02T{hh}:00Z")
            validate_success(
                api.trip_event(trip["id"], trip_event_payload("DEPART"),
                               DISPATCHER),
                200,
            )
            validate_success(
                api.trip_event(trip["id"],
                               trip_event_payload("COMPLETE",
                                                  boarded_count=boarded),
                               DISPATCHER),
                200,
            )
        report = validate_success(
            api.get_program_cost_report(program["id"], PAYROLL), 200
        )
        return report

    def test_total_cost_subsidy_spend_and_active_count(self, api):
        """PRD section 3.6: "`total_cost_cents` aggregates, over every route of
        the program, the all-time count of `COMPLETED` trips each multiplied by
        its route's `operating_cost_per_trip_cents`, and adds the
        `monthly_maintenance_cents` of every lot of the program.
        `subsidy_spent_cents` sums `subsidy_cents` over the program's
        `PERMIT_FEE` entries not in `REVERSED` status. `active_permit_count`
        counts the program's permits in `ACTIVE` at read time."

        Design: Difficulty/dual_variant_calc/cost_report_gross_vs_net
        """
        report = self._drive(api)
        assert report["total_cost_cents"] == 57000, (
            "3 trips x 4000 + 30000 + 15000 maintenance"
        )
        assert report["subsidy_spent_cents"] == 7350, "1200 + 3600 + 2550"
        assert report["active_permit_count"] == 3

    def test_gross_and_net_cost_per_employee(self, api):
        """PRD section 3.6: "`gross_cost_per_employee_cents` divides the total
        cost by the active-permit count — with the denominator raised to a
        minimum of one — rounded half-up to integer cents, and
        `net_cost_per_employee_cents` performs the same division after
        subtracting the subsidy spend from the total cost, so the net figure is
        lower whenever any subsidy has been spent."

        Design: Difficulty/dual_variant_calc/cost_report_gross_vs_net
        """
        report = self._drive(api)
        assert report["gross_cost_per_employee_cents"] == 19000, (
            "round_half_up(57000 / 3)"
        )
        assert report["net_cost_per_employee_cents"] == 16550, (
            "round_half_up((57000 - 7350) / 3) — diverges from gross by exactly "
            "the per-capita subsidy"
        )


# ─── Cycle total conservation across reverse/repost pairs ─────────────

class TestCycleTotalSpanTruncationConservation:
    """Money never drifts: 10800 -> REVERSED + 5574 -> +3832 on reinstate ->
    C REVERSED + 2090 on revoke."""

    def test_totals_at_each_step(self, api):
        """PRD section 2.6: "Every charge entry amount is rounded half-up to
        integer cents at posting time, and a billing cycle's total is the plain
        integer sum of its non-reversed entries — never re-rounded after
        summation."
        PRD section 3.5: "From `ACTIVE`, revocation applies the same span
        truncation as suspension — the pending fee entry whose span contains the
        revocation date is reversed and reposted through the revocation date,
        earlier ended spans untouched, skipped without an `OPEN` cycle — then
        releases the occupied slot and runs an immediate waitlist promotion pass
        on the lot."

        Design: Difficulty/compensating_invariant/cycle_total_span_truncation_conservation
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        bundle = setup_active_permit(
            program_overrides={"monthly_subsidy_pool_cents": 100000},
            lot_overrides={"capacity": 5},
        )
        cycle_id = bundle["cycle"]["id"]
        p1 = bundle["permit"]
        assert get_cycle(cycle_id)["total_charges_cents"] == 10800

        set_logical_clock("2026-08-16T09:00:00Z")
        validate_success(api.permit_event(p1["id"], {"event_type": "SUSPEND"},
                                          ADMIN), 200)
        assert get_cycle(cycle_id)["total_charges_cents"] == 5574, (
            "A 10800 REVERSED, B [08-01..08-16] 5574 PENDING"
        )

        set_logical_clock("2026-08-21T09:00:00Z")
        validate_success(api.permit_event(p1["id"], {"event_type": "REINSTATE"},
                                          ADMIN), 200)
        assert get_cycle(cycle_id)["total_charges_cents"] == 9406, "5574 + 3832"

        set_logical_clock("2026-08-26T09:00:00Z")
        validate_success(api.permit_event(p1["id"], {"event_type": "REVOKE"},
                                          ADMIN), 200)
        assert get_cycle(cycle_id)["total_charges_cents"] == 7664, (
            "B 5574 + D [08-21..08-26] 2090; A and C are REVERSED and excluded"
        )

    def test_entries_match_sum_invariant_throughout(self, api):
        """PRD section 3.6: "`SETTLED` and `REVERSED` are terminal, and `REVERSED`
        entries are excluded from `total_charges_cents`."
        PRD section 2.10: "Derived figures — a lot's `occupied_slots` and
        `reserved_slots`, an employee's `balance_due_cents` and `standing`, a
        cycle's `total_charges_cents` — are always recomputed from their defining
        source rows rather than stored independently, so they stay correct after
        every direct write and every cascade."

        Design: Difficulty/compensating_invariant/cycle_total_span_truncation_conservation
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        bundle = setup_active_permit(
            program_overrides={"monthly_subsidy_pool_cents": 100000},
            lot_overrides={"capacity": 5},
        )
        cycle_id = bundle["cycle"]["id"]
        p1 = bundle["permit"]

        def check_total():
            entries = list_all_charge_entries(cycle_id=cycle_id)
            assert get_cycle(cycle_id)["total_charges_cents"] == sum_non_reversed(
                entries
            ), "total equals the sum of non-REVERSED entries at every read"
            return entries

        check_total()
        set_logical_clock("2026-08-16T09:00:00Z")
        validate_success(api.permit_event(p1["id"], {"event_type": "SUSPEND"},
                                          ADMIN), 200)
        check_total()
        set_logical_clock("2026-08-21T09:00:00Z")
        validate_success(api.permit_event(p1["id"], {"event_type": "REINSTATE"},
                                          ADMIN), 200)
        check_total()
        set_logical_clock("2026-08-26T09:00:00Z")
        validate_success(api.permit_event(p1["id"], {"event_type": "REVOKE"},
                                          ADMIN), 200)
        entries = check_total()

        fees = sorted(
            (f for f in entries if f["charge_type"] == "PERMIT_FEE"),
            key=lambda f: (f["span_start"], f["span_end"]),
        )
        assert len(fees) == 4
        signature = [(f["span_start"], f["span_end"], f["amount_cents"],
                      f["status"]) for f in fees]
        assert signature == [
            ("2026-08-01", "2026-08-16", 5574, "PENDING"),
            ("2026-08-01", "2026-08-31", 10800, "REVERSED"),
            ("2026-08-21", "2026-08-26", 2090, "PENDING"),
            ("2026-08-21", "2026-08-31", 3832, "REVERSED"),
        ]
