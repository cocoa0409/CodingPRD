"""Fleet posture: spare-ratio tiers, pull-out readiness, the RED freeze
cascade and recovery, and posture gating of work-order creation."""
from test_helpers import (
    ApiErrorId,
    assert_posture_shape,
    bus_version,
    create_work_order_payload,
    file_safety_defect,
    get_posture_data,
    get_success_data,
    new_bus,
    new_mechanic,
    new_work_order,
    schedule_wo,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


class TestSpareRatioGreenFloor:
    """GREEN floor is inclusive at spare_ratio 0.20 (5 buses, 1 available)."""

    def test_one_of_five_available_is_green_at_boundary(self, api):
        """PRD §2.6: "The posture tier is then assigned by comparing the spare
        ratio to two thresholds: `GREEN` when the spare ratio is at least 0.20,
        `RED` when the spare ratio is below 0.15, and `YELLOW` in between (at
        least 0.15 and strictly below 0.20)."
        PRD §2.6: "The pull-out minimum is the ceiling of 0.80 multiplied by
        the active count — so with an active count of 10 the minimum is 8, and
        with an active count of 11 the minimum is 9. The fleet is pull-out
        ready when the available count is greater than or equal to that
        minimum."

        Design: Difficulty/boundary_precision_check/spare_ratio_green_floor_inclusive_at_exactly_0_20
        """
        buses, _ = fx.setup_fleet_with_holds(5, 4)

        posture = get_posture_data()
        assert_posture_shape(posture)
        assert posture["active_buses"] == 5
        assert posture["available_buses"] == 1
        assert posture["spare_ratio"] == 0.2, (
            f"1/5 must round to 0.2, got {posture['spare_ratio']}"
        )
        assert posture["posture"] == "GREEN", "GREEN floor is inclusive at 0.20"
        assert posture["pull_out_minimum"] == 4, "ceil(0.80 * 5) == 4"
        assert posture["pull_out_ready"] is False, "1 available < minimum 4"

    def test_fifth_hold_flips_to_red(self, api):
        """PRD §2.6: "The posture tier is then assigned by comparing the spare
        ratio to two thresholds: `GREEN` when the spare ratio is at least 0.20,
        `RED` when the spare ratio is below 0.15, and `YELLOW` in between (at
        least 0.15 and strictly below 0.20)."

        Design: Difficulty/boundary_precision_check/spare_ratio_green_floor_inclusive_at_exactly_0_20
        """
        buses, _ = fx.setup_fleet_with_holds(5, 4)
        before = get_posture_data()
        assert before["posture"] == "GREEN"

        file_safety_defect(buses[4]["id"], description="d5")
        after = get_posture_data()
        assert after["available_buses"] == 0
        assert after["spare_ratio"] == 0.0
        assert after["posture"] == "RED", "0.0 is below the 0.15 RED threshold"


class TestSafetyDefectFreezesScheduledWork:
    """Five-bus RED freeze cascade triggered by SAFETY_CRITICAL defect filing."""

    def _setup(self):
        buses, _ = fx.setup_fleet_with_holds(5, 0)
        lead = new_mechanic(name="Lead", employee_ref="E50")
        wos = []
        for b in buses[:2]:
            wo = new_work_order(
                b["id"], priority="ROUTINE",
                planned_start_date="2026-08-10", planned_end_date="2026-08-12",
                estimated_labor_hours=2, estimated_cost_cents=13_000,
                lead_mechanic_id=lead["id"],
            )
            schedule_wo(wo["id"])
            wos.append(wo)
        return buses, wos

    def test_four_holds_stay_green_and_work_remains_scheduled(self, api):
        """PRD §2.6: "`GREEN` when the spare ratio is at least 0.20, `RED` when
        the spare ratio is below 0.15, and `YELLOW` in between (at least 0.15
        and strictly below 0.20)."
        PRD §2.7: "`SAFETY` is added when a `SAFETY_CRITICAL` defect is created
        and removed when that defect is resolved or withdrawn."

        Design: Difficulty/transitive_cascade/safety_defect_five_bus_cascade_freezes_scheduled_work
        """
        buses, wos = self._setup()
        for b in buses[:4]:
            file_safety_defect(b["id"], description="brake fade")

        posture = get_posture_data()
        assert posture["available_buses"] == 1
        assert posture["spare_ratio"] == 0.2
        assert posture["posture"] == "GREEN", "1/5 = 0.20 sits on the GREEN floor"
        for wo in wos:
            current = get_success_data(api.get_work_order(wo["id"], fx.SUP))
            assert current["status"] == "SCHEDULED", (
                "no RED transition has occurred, so nothing may freeze"
            )

    def test_fifth_safety_defect_blocks_routine_work_fleetwide(self, api):
        """PRD §2.6: "When the posture transitions into `RED`, every work order
        currently in `SCHEDULED` whose `priority` is `ROUTINE` or `ELECTIVE`
        automatically transitions to `BLOCKED` fleet-wide; `EMERGENCY` and
        `URGENT` work orders are never frozen by posture."
        PRD §3.8: "Filing a `SAFETY_CRITICAL` report immediately places the bus
        in `HELD` with the `SAFETY` hold added to `hold_reasons`, recomputes
        the fleet posture (which may trigger the `RED` freeze cascade), and
        increments the bus's `version`."

        Design: Difficulty/transitive_cascade/safety_defect_five_bus_cascade_freezes_scheduled_work
        """
        buses, wos = self._setup()
        for b in buses[:4]:
            file_safety_defect(b["id"], description="brake fade")

        defect5 = file_safety_defect(buses[4]["id"], description="brake fade")
        assert defect5["status"] == "OPEN"

        posture = get_posture_data()
        assert posture["posture"] == "RED"
        assert posture["spare_ratio"] == 0.0
        assert posture["available_buses"] == 0

        for wo in wos:
            current = get_success_data(api.get_work_order(wo["id"], fx.SUP))
            assert current["status"] == "BLOCKED", (
                f"RED entry must freeze SCHEDULED ROUTINE work orders; "
                f"got {current['status']}"
            )
        bus5 = get_success_data(api.get_bus(buses[4]["id"], fx.FM))
        assert bus5["availability_status"] == "HELD"
        assert "SAFETY" in bus5["hold_reasons"]


def test_red_recovery_restores_blocked_work_orders(api):
    """PRD §2.6: "When posture recovers out of `RED` (to either `YELLOW` or
    `GREEN`), every `BLOCKED` work order is restored to `SCHEDULED`."

    Design: Corner/cross_cutting/red_recovery_restores_blocked_work_orders
    """
    buses, _ = fx.setup_fleet_with_holds(5, 0)
    lead = new_mechanic(name="Lead", employee_ref="RCA")
    wos = []
    for b in buses[:2]:
        wo = new_work_order(
            b["id"], priority="ROUTINE",
            planned_start_date="2026-08-10", planned_end_date="2026-08-12",
            estimated_labor_hours=2, estimated_cost_cents=13_000,
            lead_mechanic_id=lead["id"],
        )
        schedule_wo(wo["id"])
        wos.append(wo)
    for b in buses:
        file_safety_defect(b["id"], description="hold")

    frozen = get_success_data(api.get_work_order(wos[0]["id"], fx.SUP))
    assert frozen["status"] == "BLOCKED", "precondition: RED froze the WO (0/5)"

    for i in range(5):
        new_bus(fleet_number=f"RC{6 + i}", vin=f"VINRC{6 + i}",
                model_year=2022, initial_odometer_miles=100)

    posture = get_posture_data()
    assert posture["posture"] == "GREEN", (
        f"5 available of 10 active = 0.5 must be GREEN, got {posture['posture']}"
    )
    for wo in wos:
        current = get_success_data(api.get_work_order(wo["id"], fx.SUP))
        assert current["status"] == "SCHEDULED", (
            f"RED exit must auto-restore BLOCKED work orders; got "
            f"{current['status']}"
        )


def test_posture_yellow_blocks_elective_but_allows_routine(api):
    """PRD §2.6: "Independently of the freeze cascade, attempting to create a
    new work order is also gated by posture (see §3.3): under `YELLOW`,
    `ELECTIVE` work orders are rejected with `ERR_FLEET_POSTURE_YELLOW`; under
    `RED`, both `ELECTIVE` and `ROUTINE` work orders are rejected with
    `ERR_FLEET_POSTURE_RED`."

    Six buses with five held: spare ratio 1/6 = 0.1667 sits in [0.15, 0.20).

    Design: Corner/validations/posture_yellow_blocks_elective_but_allows_routine
    """
    buses, _ = fx.setup_fleet_with_holds(6, 5)
    target = buses[5]
    posture = get_posture_data()
    assert posture["posture"] == "YELLOW", (
        f"1/6 = 0.1667 must be YELLOW, got {posture['posture']}"
    )

    elective = api.create_work_order(
        create_work_order_payload(
            target["id"], bus_version(target["id"]), priority="ELECTIVE",
            planned_start_date="2026-08-10", planned_end_date="2026-08-11",
        ),
        fx.SUP,
    )
    validate_error(elective, ApiErrorId.ERR_FLEET_POSTURE_YELLOW)

    routine = api.create_work_order(
        create_work_order_payload(
            target["id"], bus_version(target["id"]), priority="ROUTINE",
            planned_start_date="2026-08-10", planned_end_date="2026-08-11",
        ),
        fx.SUP,
    )
    created = validate_success(routine, 201)
    assert created["status"] == "DRAFT", "only ELECTIVE is gated at YELLOW"


def test_posture_constraint_beats_fiscal_overhaul_cap(api):
    """PRD §2.10: "The band order is: authentication, then authorization and
    ownership, then existence of path and body references, then schema/format,
    then state-machine legality, then optimistic concurrency, then safety
    (certification, segregation-of-duties, safety-defect handling, on-shift
    dispatch), then referential uniqueness, then temporal windows, then
    business constraint, then fiscal."
    PRD §2.10: "A failed earlier check short-circuits the request; the
    corresponding `error_id` is what the client observes, even if a later check
    would also have failed."
    PRD §3.11: "Mid-life overhauls are ordinary work orders with `wo_type`
    `OVERHAUL`, but they interact specially with the bus lifecycle and with a
    fiscal cap."

    A RED-posture ROUTINE create that also breaches the fiscal overhaul cap
    surfaces ERR_FLEET_POSTURE_RED (constraint band precedes fiscal).

    Design: Corner/validations/posture_constraint_beats_fiscal_overhaul_cap
    """
    bus = new_bus(fleet_number="Y7", vin="VINY7", model_year=2021)
    file_safety_defect(bus["id"], description="hold")
    posture = get_posture_data()
    assert posture["posture"] == "RED", "0 available of 1 active must be RED"

    res = api.create_work_order(
        create_work_order_payload(
            bus["id"], bus_version(bus["id"]), wo_type="OVERHAUL",
            priority="ROUTINE", planned_start_date="2026-08-10",
            planned_end_date="2026-08-20", estimated_labor_hours=40,
            estimated_cost_cents=99_999_999,
        ),
        fx.SUP,
    )
    validate_error(res, ApiErrorId.ERR_FLEET_POSTURE_RED)
