"""Production day lifecycle: open/suspend/resume cycle, open gates,
duplicates, date matching, plant suspension."""
from test_helpers import (
    INSPECTOR_1,
    INSPECTOR_2,
    TEST_USERS,
    ApiErrorId,
    create_production_day_payload,
    validate_error,
    validate_success,
)
from test_helpers import fixtures

ADMIN = TEST_USERS["plant_admin_headers"]
PROD = TEST_USERS["production_manager_headers"]
QA = TEST_USERS["qa_manager_headers"]


class TestOpenSuspendResumeCycle:
    def test_day_cycles_open_suspended_twice(self, api):
        """PRD §3.3: "Suspending an `OPEN` day moves it to `SUSPENDED`; resuming re-runs the full open gate sequence above."

        Design: Difficulty/non_linear_state_machine/production_day_open_suspend_resume_cycle
        """
        env = fixtures.setup_open_day(establishment_number="EST-1645-F")
        day_id = env["day"]["id"]
        assert env["day"]["status"] == "OPEN"

        s1 = validate_success(api.suspend_production_day(day_id, PROD), 200)
        assert s1["status"] == "SUSPENDED"
        o1 = validate_success(api.open_production_day(day_id, PROD), 200)
        assert o1["status"] == "OPEN"
        s2 = validate_success(api.suspend_production_day(day_id, PROD), 200)
        assert s2["status"] == "SUSPENDED"
        o2 = validate_success(api.open_production_day(day_id, PROD), 200)
        assert o2["status"] == "OPEN", (
            "the OPEN <-> SUSPENDED cycle is resumable while the inspector "
            "remains ON_PREMISE"
        )

    def test_resume_reruns_inspector_presence_gate(self, api):
        """PRD §3.3: "Opening a day — from `PLANNED`, or resuming from `SUSPENDED` through the same action — is the most heavily gated transition in the platform, and its checks run in a fixed order."
        PRD §3.3: "Then come four business gates, in this order: the plant's `operating_status` must be `ACTIVE` (`ERR_PLANT_SUSPENDED`); at least one inspector shift of the plant must be `ON_PREMISE` (`ERR_INSPECTOR_NOT_PRESENT`); the logical-clock date must equal `production_date` (`ERR_DAY_DATE_MISMATCH`); and an `EFFECTIVE` HACCP plan must exist for the plant and the day's `process_type` (`ERR_PLAN_NOT_EFFECTIVE`)."

        Design: Difficulty/non_linear_state_machine/production_day_open_suspend_resume_cycle
        """
        env = fixtures.setup_open_day(establishment_number="EST-1645-F2")
        day_id = env["day"]["id"]
        api.suspend_production_day(day_id, PROD)
        # The only inspector departs; nobody is ON_PREMISE now.
        resp_out = api.check_out_shift(
            env["shift"]["id"], fixtures.make_inspector_headers(INSPECTOR_1)
        )
        validate_success(resp_out, 200)

        blocked = api.open_production_day(day_id, PROD)
        validate_error(blocked, ApiErrorId.ERR_INSPECTOR_NOT_PRESENT)

        # A different inspector arrives; the resume gate now passes.
        shift2 = fixtures.schedule_shift(env["plant"]["id"], inspector_id=INSPECTOR_2)
        fixtures.check_in_shift(shift2["id"], inspector_id=INSPECTOR_2)
        resumed = validate_success(api.open_production_day(day_id, PROD), 200)
        assert resumed["status"] == "OPEN"


class TestDayOpenRequiresInspector:
    def test_open_blocked_until_inspector_checks_in(self, api):
        """PRD §3.3: "Then come four business gates, in this order: the plant's `operating_status` must be `ACTIVE` (`ERR_PLANT_SUSPENDED`); at least one inspector shift of the plant must be `ON_PREMISE` (`ERR_INSPECTOR_NOT_PRESENT`); the logical-clock date must equal `production_date` (`ERR_DAY_DATE_MISMATCH`); and an `EFFECTIVE` HACCP plan must exist for the plant and the day's `process_type` (`ERR_PLAN_NOT_EFFECTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/day_open_requires_inspector_shift_on_premise
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-M")
        fixtures.create_effective_plan(plant["id"])
        shift = fixtures.schedule_shift(plant["id"], inspector_id=INSPECTOR_1)
        fixtures.set_clock("2026-08-01T07:00:00Z")
        day = fixtures.plan_production_day(plant["id"])

        blocked = api.open_production_day(day["id"], PROD)
        validate_error(blocked, ApiErrorId.ERR_INSPECTOR_NOT_PRESENT)
        assert blocked.status_code == 422

        fixtures.check_in_shift(shift["id"], inspector_id=INSPECTOR_1)
        opened = validate_success(api.open_production_day(day["id"], PROD), 200)
        assert opened["status"] == "OPEN"

    def test_open_blocked_when_only_shift_is_no_show(self, api):
        """PRD §3.3: "A shift that nobody checks into is swept to `NO_SHOW` when the clock passes its `scheduled_end`, per §2.4."
        PRD §3.3: "at least one inspector shift of the plant must be `ON_PREMISE` (`ERR_INSPECTOR_NOT_PRESENT`);"

        Design: Difficulty/cross_entity_state_dependency/day_open_requires_inspector_shift_on_premise
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-M2")
        fixtures.create_effective_plan(plant["id"])
        shift = fixtures.schedule_shift(plant["id"], inspector_id=INSPECTOR_1)
        # Clock passes the shift's end while still SCHEDULED: swept to NO_SHOW.
        fixtures.set_clock("2026-08-01T19:00:00Z")
        swept = validate_success(api.get_inspector_shift(shift["id"], ADMIN), 200)
        assert swept["status"] == "NO_SHOW"

        day = fixtures.plan_production_day(plant["id"])
        blocked = api.open_production_day(day["id"], PROD)
        validate_error(blocked, ApiErrorId.ERR_INSPECTOR_NOT_PRESENT)


class TestLotStepsRequireOpenDay:
    def test_fabricate_blocked_while_day_suspended(self, api):
        """PRD §3.5: "Every processing step that follows requires the owning day to be `OPEN`, enforced as `ERR_DAY_NOT_OPEN`, and the lot itself must sit in the step's required from-state, enforced as `ERR_LOT_INVALID_STATE`: ante-mortem requires `RECEIVED`, harvest requires `CLEARED`, chill-complete requires `HARVESTED`, fabrication requires `CHILLED` or `RELEASED`, and fabrication completion requires `FABRICATING`."

        Design: Difficulty/cross_entity_state_dependency/lot_fabricate_requires_day_open
        """
        env = fixtures.setup_open_day(establishment_number="EST-1645-N")
        lot = fixtures.receive_lot(env["day"]["id"])
        fixtures.walk_lot_to_chilled(lot["id"])
        validate_success(api.suspend_production_day(env["day"]["id"], PROD), 200)

        blocked = api.fabricate_lot(lot["id"], PROD)
        validate_error(blocked, ApiErrorId.ERR_DAY_NOT_OPEN)
        assert blocked.status_code == 409
        still = validate_success(api.get_lot(lot["id"], PROD), 200)
        assert still["status"] == "CHILLED"

        validate_success(api.open_production_day(env["day"]["id"], PROD), 200)
        resumed = validate_success(api.fabricate_lot(lot["id"], PROD), 200)
        assert resumed["status"] == "FABRICATING"

    def test_cut_record_blocked_while_day_suspended(self, api):
        """PRD §3.5: "While the lot fabricates, the `ProductionManager` records cut lines — like every processing step this requires the owning day to be `OPEN` (`ERR_DAY_NOT_OPEN`) — each line carrying a `primal_type` (`CHUCK`, `RIB`, `LOIN`, `ROUND`, `BRISKET`, `BELLY`, `HAM`, or `OTHER`) and a `weight_lbs` greater than zero."

        Design: Difficulty/cross_entity_state_dependency/lot_fabricate_requires_day_open
        """
        env, lot, _cuts = fixtures.setup_fabricating_lot(
            establishment_number="EST-1645-N2", cuts=(),
        )
        validate_success(api.suspend_production_day(env["day"]["id"], PROD), 200)

        blocked = api.create_cut_record(
            lot["id"], {"primal_type": "CHUCK", "weight_lbs": 600.0}, PROD
        )
        validate_error(blocked, ApiErrorId.ERR_DAY_NOT_OPEN)

        validate_success(api.open_production_day(env["day"]["id"], PROD), 200)
        ok = validate_success(
            api.create_cut_record(
                lot["id"], {"primal_type": "CHUCK", "weight_lbs": 600.0}, PROD
            ),
            201,
        )
        assert ok["primal_type"] == "CHUCK"


class TestDayTransitionAndUniqueness:
    def test_suspend_from_planned_returns_day_invalid_state(self, api):
        """PRD §3.3: "Suspending an `OPEN` day moves it to `SUSPENDED`; resuming re-runs the full open gate sequence above."

        Design: Corner/state_machines/day_suspend_from_planned_returns_day_invalid_state
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-04")
        day = fixtures.plan_production_day(plant["id"])

        resp = api.suspend_production_day(day["id"], PROD)
        validate_error(resp, ApiErrorId.ERR_DAY_INVALID_STATE)
        assert resp.status_code == 409

    def test_duplicate_production_day_same_date_returns_duplicate_day(self, api):
        """PRD §3.3: "At most one non-`CLOSED` day may exist per plant and calendar date; a colliding plan is rejected with `ERR_DUPLICATE_PRODUCTION_DAY`."

        Design: Corner/validations/duplicate_production_day_same_date_returns_duplicate_day
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-27")
        day1 = fixtures.plan_production_day(plant["id"])
        assert day1["status"] == "PLANNED"

        dup = api.create_production_day(
            plant["id"],
            create_production_day_payload(
                production_date="2026-08-01", process_type="SLAUGHTER"
            ),
            PROD,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_PRODUCTION_DAY)
        assert dup.status_code == 422

        nxt = api.create_production_day(
            plant["id"],
            create_production_day_payload(
                production_date="2026-08-02", process_type="RAW_GROUND"
            ),
            PROD,
        )
        day2 = validate_success(nxt, 201)
        assert day2["status"] == "PLANNED"


class TestDayOpenGates:
    def test_open_with_wrong_clock_date_returns_day_date_mismatch(self, api):
        """PRD §3.3: "the logical-clock date must equal `production_date` (`ERR_DAY_DATE_MISMATCH`);"

        Design: Corner/validations/day_open_with_wrong_clock_date_returns_day_date_mismatch
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-35")
        fixtures.create_effective_plan(plant["id"])
        shift = fixtures.schedule_shift(
            plant["id"], inspector_id=INSPECTOR_1,
            scheduled_start="2026-08-01T06:00:00Z",
            scheduled_end="2026-08-02T18:00:00Z",
        )
        fixtures.set_clock("2026-08-01T07:00:00Z")
        fixtures.check_in_shift(shift["id"], inspector_id=INSPECTOR_1)
        day = fixtures.plan_production_day(
            plant["id"], production_date="2026-08-02"
        )

        blocked = api.open_production_day(day["id"], PROD)
        validate_error(blocked, ApiErrorId.ERR_DAY_DATE_MISMATCH)
        assert blocked.status_code == 422

        fixtures.set_clock("2026-08-02T07:00:00Z")
        opened = validate_success(api.open_production_day(day["id"], PROD), 200)
        assert opened["status"] == "OPEN"

    def test_plant_suspended_blocks_new_day_open(self, api):
        """PRD §3.3: "Then come four business gates, in this order: the plant's `operating_status` must be `ACTIVE` (`ERR_PLANT_SUSPENDED`); at least one inspector shift of the plant must be `ON_PREMISE` (`ERR_INSPECTOR_NOT_PRESENT`); the logical-clock date must equal `production_date` (`ERR_DAY_DATE_MISMATCH`); and an `EFFECTIVE` HACCP plan must exist for the plant and the day's `process_type` (`ERR_PLAN_NOT_EFFECTIVE`)."

        Design: Corner/validations/plant_suspended_blocks_new_day_open
        """
        env, _audit, _nr_id = fixtures.setup_suspended_plant_via_humane_failure(
            establishment_number="EST-1645-36",
            shift_end="2026-08-02T18:00:00Z",
        )
        plant = validate_success(api.get_plant(env["plant"]["id"], ADMIN), 200)
        assert plant["operating_status"] == "SUSPENDED"

        day2 = fixtures.plan_production_day(
            env["plant"]["id"], production_date="2026-08-02",
            process_type="SLAUGHTER",
        )
        blocked = api.open_production_day(day2["id"], PROD)
        # The safety gate (plant suspended) is the first business gate; it
        # fires even though the 2026-08-02 date would also mismatch the clock.
        validate_error(blocked, ApiErrorId.ERR_PLANT_SUSPENDED)
        assert blocked.status_code == 422

        after = validate_success(api.get_production_day(day2["id"], PROD), 200)
        assert after["status"] == "PLANNED"
