"""Work-order gates: create/schedule/start validations, labor-entry rules,
overhaul fiscal cap, and per-entry labor rounding."""
from test_helpers import (
    ApiErrorId,
    add_labor,
    assert_work_order,
    bus_version,
    create_in_progress_wo,
    create_work_order_payload,
    get_success_data,
    labor_entry_payload,
    make_mechanic_headers,
    new_bus,
    new_mechanic,
    new_mechanic_with_certs,
    new_part,
    new_work_order,
    reserve_line,
    schedule_wo,
    start_wo,
    validate_error,
    validate_success,
    wo_event,
)
from test_helpers import fixtures as fx

UNKNOWN_BUS_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_work_order_create_unknown_bus_not_found(api):
    """PRD §2.11: "The same rule applies to foreign-key references carried in
    the request body — `bus_id`, `part_id`, `work_order_id`, `campaign_id`,
    `defect_report_id`, `mechanic_id`, and `new_part_id` must each resolve to
    an existing record."

    Design: Corner/validations/work_order_create_unknown_bus_not_found
    """
    bus = new_bus(base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    payload = create_work_order_payload(UNKNOWN_BUS_ID, bus["version"])
    res = api.create_work_order(payload, fx.SUP)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_duplicate_open_work_order_same_type_rejected(api):
    """PRD §3.3: "A bus may have at most one non-terminal work order of a given
    `wo_type`; a second open one is rejected with
    `ERR_DUPLICATE_OPEN_WORK_ORDER`."

    Design: Corner/validations/duplicate_open_work_order_same_type_rejected
    """
    bus = new_bus(base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    new_work_order(bus["id"], wo_type="CORRECTIVE",
                   planned_start_date="2026-08-10", planned_end_date="2026-08-11")

    dup = api.create_work_order(
        create_work_order_payload(
            bus["id"], bus_version(bus["id"]), wo_type="CORRECTIVE",
            priority="URGENT", planned_start_date="2026-08-12",
            planned_end_date="2026-08-13",
        ),
        fx.SUP,
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_OPEN_WORK_ORDER)

    other = api.create_work_order(
        create_work_order_payload(
            bus["id"], bus_version(bus["id"]), wo_type="PM_A",
            planned_start_date="2026-08-12", planned_end_date="2026-08-13",
            estimated_labor_hours=1, estimated_cost_cents=6_500,
        ),
        fx.SUP,
    )
    created = validate_success(other, 201)
    assert created["status"] == "DRAFT", "a different wo_type on the same bus is allowed"


def test_wo_start_second_in_progress_bus_rejected(api):
    """PRD §3.3: "The bus's `availability_status` must be `AVAILABLE` or
    `HELD`, and there must be no other work order in the `IN_PROGRESS` family
    on the same bus (otherwise `ERR_BUS_NOT_AVAILABLE`)."

    Design: Corner/validations/wo_start_second_in_progress_bus_rejected
    """
    buses = fx.new_buses(6, model_year=2021,
                         base_warranty_expiry_miles=5_000,
                         base_warranty_expiry_date="2024-01-01")
    bus = buses[0]
    lead = new_mechanic_with_certs("PM_INSPECTION")
    wo1 = create_in_progress_wo(
        bus["id"], lead, wo_type="CORRECTIVE",
        planned_start_date="2026-08-02", planned_end_date="2026-08-03",
    )
    wo2 = new_work_order(
        bus["id"], wo_type="PM_A", planned_start_date="2026-08-05",
        planned_end_date="2026-08-06", estimated_labor_hours=2,
        estimated_cost_cents=13_000, lead_mechanic_id=lead["id"],
    )
    schedule_wo(wo2["id"])

    res = wo_event(wo2["id"], "START")
    validate_error(res, ApiErrorId.ERR_BUS_NOT_AVAILABLE)
    wo2_after = get_success_data(api.get_work_order(wo2["id"], fx.SUP))
    wo1_after = get_success_data(api.get_work_order(wo1["id"], fx.SUP))
    assert wo2_after["status"] == "SCHEDULED"
    assert wo1_after["status"] == "IN_PROGRESS"


class TestWorkOrderWindowBuffer:
    """Buffered closed-interval overlap check at SCHEDULE time."""

    def _bus_with_scheduled_pm_a(self):
        bus = new_bus(fleet_number="W1", vin="VINW1", model_year=2022,
                      initial_odometer_miles=50_000,
                      base_warranty_expiry_miles=5_000,
                      base_warranty_expiry_date="2024-01-01")
        wo1 = new_work_order(bus["id"], wo_type="PM_A",
                             planned_start_date="2026-08-10",
                             planned_end_date="2026-08-12",
                             estimated_labor_hours=4, estimated_cost_cents=26_000)
        schedule_wo(wo1["id"])
        return bus, wo1

    def test_window_starting_exactly_end_plus_one_rejected(self, api):
        """PRD §3.3: "the new window conflicts unless its start is strictly
        more than one day after the other window's end, or its end is strictly
        more than one day before the other window's start. A conflict is
        rejected with `ERR_WO_WINDOW_OVERLAP`."

        A start of 2026-08-13 fails: 13 > 12 + 1 is false.

        Design: Difficulty/resource_temporal_overlap/work_order_bus_window_one_day_buffer_required
        """
        bus, _ = self._bus_with_scheduled_pm_a()
        wo2 = new_work_order(bus["id"], wo_type="PM_B",
                             planned_start_date="2026-08-13",
                             planned_end_date="2026-08-14",
                             estimated_labor_hours=6, estimated_cost_cents=39_000)
        res = wo_event(wo2["id"], "SCHEDULE")
        validate_error(res, ApiErrorId.ERR_WO_WINDOW_OVERLAP)

    def test_window_starting_end_plus_two_allowed(self, api):
        """PRD §3.3: "the new window conflicts unless its start is strictly
        more than one day after the other window's end, or its end is strictly
        more than one day before the other window's start. A conflict is
        rejected with `ERR_WO_WINDOW_OVERLAP`."

        A start of 2026-08-14 satisfies 14 > 12 + 1 and schedules cleanly.

        Design: Difficulty/resource_temporal_overlap/work_order_bus_window_one_day_buffer_required
        """
        bus, _ = self._bus_with_scheduled_pm_a()
        wo3 = new_work_order(bus["id"], wo_type="PM_C",
                             planned_start_date="2026-08-14",
                             planned_end_date="2026-08-15",
                             estimated_labor_hours=8, estimated_cost_cents=52_000)
        scheduled = validate_success(wo_event(wo3["id"], "SCHEDULE"))
        assert scheduled["status"] == "SCHEDULED"


def test_labor_hours_zero_rejected(api):
    """PRD §3.5: "Only the work order's lead mechanic may append an entry
    (otherwise `ERR_FORBIDDEN`), and `hours` must satisfy 0 < hours ≤ 16
    (otherwise `ERR_LABOR_HOURS_INVALID`)."

    Design: Corner/validations/labor_hours_zero_rejected
    """
    bus = new_bus(base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    lead = new_mechanic()
    wo = create_in_progress_wo(bus["id"], lead)
    res = api.add_labor_entry(
        wo["id"],
        labor_entry_payload(hours=0),
        make_mechanic_headers(lead["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LABOR_HOURS_INVALID)


def test_submit_qa_without_labor_rejected(api):
    """PRD §3.4: "There must be at least one labor entry
    (`ERR_QA_WITHOUT_LABOR`)."

    Design: Corner/validations/submit_qa_without_labor_rejected
    """
    bus = new_bus(base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    lead = new_mechanic()
    wo = create_in_progress_wo(bus["id"], lead)

    res = wo_event(wo["id"], "SUBMIT_QA", headers=make_mechanic_headers(lead["id"]))
    validate_error(res, ApiErrorId.ERR_QA_WITHOUT_LABOR)
    after = get_success_data(api.get_work_order(wo["id"], fx.SUP))
    assert after["status"] == "IN_PROGRESS"


def test_submit_qa_with_reserved_line_rejected(api):
    """PRD §3.4: "No part line on the work order may still be in `issue_status`
    `RESERVED` or `ISSUED` (`ERR_LINES_UNRESOLVED`) — everything pulled must be
    either consumed, returned, or released."

    Design: Corner/validations/submit_qa_with_reserved_line_rejected
    """
    bus = new_bus(base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    part = new_part(sku="P-Y27", unit_cost_cents=300, initial_on_hand=5)
    lead = new_mechanic()
    wo = create_in_progress_wo(bus["id"], lead, estimated_cost_cents=6_800)
    reserve_line(wo["id"], part["id"], qty=1)
    add_labor(wo["id"], lead, hours=1)

    res = wo_event(wo["id"], "SUBMIT_QA", headers=make_mechanic_headers(lead["id"]))
    validate_error(res, ApiErrorId.ERR_LINES_UNRESOLVED)
    after = get_success_data(api.get_work_order(wo["id"], fx.SUP))
    assert after["status"] == "IN_PROGRESS"


def test_labor_entry_by_non_lead_mechanic_forbidden(api):
    """PRD §3.5: "Only the work order's lead mechanic may append an entry
    (otherwise `ERR_FORBIDDEN`), and `hours` must satisfy 0 < hours ≤ 16
    (otherwise `ERR_LABOR_HOURS_INVALID`)."
    PRD §2.1: "Ownership checks that compare the caller to a mechanic — for
    example the labor-entry rule that only the work order's lead may post
    hours, or the road-call rule that only the dispatched mechanic may report
    arrival or clear — compare the relevant foreign key on the resource
    directly against `X-User-ID`."

    Design: Corner/rbac/labor_entry_by_non_lead_mechanic_forbidden
    """
    bus = new_bus(base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    lead = new_mechanic(name="Lead")
    other = new_mechanic(name="Other")
    wo = create_in_progress_wo(bus["id"], lead)

    res = api.add_labor_entry(
        wo["id"], labor_entry_payload(hours=1), make_mechanic_headers(other["id"])
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    after = get_success_data(api.get_work_order(wo["id"], fx.SUP))
    assert after["labor_total_cents"] == 0, "no labor may be recorded for a non-lead"


def test_overhaul_cost_cap_exact_boundary_allowed_then_exceeded(api):
    """PRD §3.11: "At create time, an overhaul's `estimated_cost_cents` is
    checked against a cap of 40 percent of the bus's `replacement_cost_cents`,
    rounded half-up; an estimate strictly greater than the cap is rejected with
    `ERR_OVERHAUL_COST_CAP_EXCEEDED`, while an estimate exactly equal to the
    cap is allowed."

    Cap here: round_half_up(30,000,000 * 0.40) = 12,000,000 cents.

    Design: Corner/validations/overhaul_cost_cap_exact_boundary_allowed_then_exceeded
    """
    bus1 = new_bus(fleet_number="Y13", vin="VINY13", model_year=2021,
                   base_warranty_expiry_miles=5_000,
                   base_warranty_expiry_date="2024-01-01")
    bus2 = new_bus(fleet_number="Y14", vin="VINY14", model_year=2021,
                   base_warranty_expiry_miles=5_000,
                   base_warranty_expiry_date="2024-01-01")

    at_cap = api.create_work_order(
        create_work_order_payload(
            bus1["id"], bus_version(bus1["id"]), wo_type="OVERHAUL",
            planned_start_date="2026-08-10", planned_end_date="2026-08-20",
            estimated_labor_hours=40, estimated_cost_cents=12_000_000,
        ),
        fx.SUP,
    )
    created = validate_success(at_cap, 201)
    assert created["status"] == "DRAFT", "an estimate exactly at the cap is allowed"

    over_cap = api.create_work_order(
        create_work_order_payload(
            bus2["id"], bus_version(bus2["id"]), wo_type="OVERHAUL",
            planned_start_date="2026-08-10", planned_end_date="2026-08-20",
            estimated_labor_hours=40, estimated_cost_cents=12_000_001,
        ),
        fx.SUP,
    )
    validate_error(over_cap, ApiErrorId.ERR_OVERHAUL_COST_CAP_EXCEEDED)


class TestLaborRoundingPerEntry:
    """Per-entry rounding order for labor cost (three 0.5h NIGHT entries)."""

    def _setup_started_wo(self):
        bus = new_bus(fleet_number="B200", vin="VINB200", model_year=2022,
                      initial_odometer_miles=50_000,
                      base_warranty_expiry_miles=100_000,
                      base_warranty_expiry_date="2027-01-01")
        lead = new_mechanic(name="Night Tech", employee_ref="E10")
        wo = create_in_progress_wo(bus["id"], lead, estimated_labor_hours=2,
                                   estimated_cost_cents=12_000)
        return bus, lead, wo

    def _post_three_night_halves(self, wo_id, lead):
        for _ in range(3):
            add_labor(wo_id, lead, work_date="2026-08-02",
                      shift_type="NIGHT", hours=0.5)

    def test_labor_total_rounds_per_entry_then_sums(self, api):
        """PRD §2.8: "First, labor cost is rounded **per entry, before
        summation**: each labor entry's amount is individually rounded half-up
        to the nearest cent, and only then are the per-entry amounts summed to
        form `labor_total_cents`. Three half-hour `NIGHT` entries therefore
        contribute three times the rounding of one half-hour entry, which is
        not the same as rounding one 1.5-hour total."

        round_half_up(0.5 * 6500 * 1.25) = 4063 per entry; 3 x 4063 = 12189,
        not the 12188 that sum-then-round would produce.

        Design: Difficulty/combinatorial_formula/labor_rounding_per_entry_then_sum_pinned
        """
        _, lead, wo = self._setup_started_wo()
        self._post_three_night_halves(wo["id"], lead)

        after = get_success_data(api.get_work_order(wo["id"], fx.SUP))
        assert after["labor_total_cents"] == 12_189, (
            f"per-entry rounding must give 12189, got "
            f"{after['labor_total_cents']} (12188 means sum-then-round)"
        )
        assert after["total_cost_cents"] == 12_189, "no parts or cores posted"

    def test_each_labor_entry_amount_rounded_individually(self, api):
        """PRD §3.5: "Each labor entry's `amount_cents` is `hours` multiplied
        by the base rate multiplied by the differential for its `shift_type`,
        rounded half-up to the nearest cent *before* any summation."
        PRD §3.5: "Each entry records `work_date`, `shift_type`, `hours`, the
        acting `mechanic_id`, and a computed `amount_cents`."

        Design: Difficulty/combinatorial_formula/labor_rounding_per_entry_then_sum_pinned
        """
        _, lead, wo = self._setup_started_wo()
        self._post_three_night_halves(wo["id"], lead)

        after = get_success_data(api.get_work_order(wo["id"], fx.SUP))
        amounts = [e["amount_cents"] for e in after["labor_entries"]]
        assert amounts == [4_063, 4_063, 4_063], (
            f"each 0.5h NIGHT entry rounds to 4063; got {amounts}"
        )
