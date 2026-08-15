"""Line scheduling and allergen changeover control: slot overlap/buffer rules,
the changeover level matrix (incl. wet-clean staleness), swab workflow with
segregation of duties, and line OCC (PRD §2.5, §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    fixtures,
    make_lab_technician_headers,
    make_quality_manager_headers,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["plant_admin_headers"]
SCI = TEST_USERS["formulation_scientist_headers"]
QM = TEST_USERS["quality_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
LT = TEST_USERS["lab_technician_headers"]


class TestSlotOverlapAndChangeoverBuffer:
    def test_too_close_gap_and_half_open_overlap_rejected(self, api):
        """PRD §3.6: "The schedule's checks run in order: the slot must not
        begin in the past relative to the logical clock
        (`ERR_SCHEDULE_IN_PAST`, HTTP 422); the half-open interval from
        `start_utc` (inclusive) to `end_utc` (exclusive) must not intersect
        any `CONFIRMED` slot on the same line, with touching endpoints
        permitted (`ERR_SLOT_OVERLAP`, HTTP 409); the gap to each adjacent
        `CONFIRMED` slot must be at least the changeover buffer this run
        requires (`ERR_SLOT_CHANGEOVER_BUFFER_VIOLATION`, HTTP 409); and the
        line's `version` must match `expected_line_version`
        (`ERR_STALE_VERSION`)."
        PRD §3.7: "when the carryover set contains a high-risk allergen
        (`PEANUT` or `TREE_NUT`) or spans two or more distinct allergens, the
        level is `SWAB_VALIDATE`"

        Design: Difficulty/resource_temporal_overlap/slot_changeover_buffer_gap_rule
        """
        ns = fixtures.setup_peanut_line_scenario()
        line_version = fixtures.get_line_version(ns.lp["id"])
        # Gap of 30 minutes after a PEANUT-profile slot: SWAB_VALIDATE needs 90.
        too_close = client.schedule_run(
            ns.run_0["id"],
            {"start_utc": "2026-08-05T10:30:00Z", "end_utc": "2026-08-05T12:00:00Z",
             "expected_line_version": line_version},
            PP,
        )
        validate_error(too_close, ApiErrorId.ERR_SLOT_CHANGEOVER_BUFFER_VIOLATION, 409)
        # [09:30, 11:00) intersects the CONFIRMED [08:00, 10:00) slot.
        overlap = client.schedule_run(
            ns.run_0["id"],
            {"start_utc": "2026-08-05T09:30:00Z", "end_utc": "2026-08-05T11:00:00Z",
             "expected_line_version": line_version},
            PP,
        )
        validate_error(overlap, ApiErrorId.ERR_SLOT_OVERLAP, 409)

    def test_gap_exactly_equal_to_buffer_is_accepted(self, api):
        """PRD §3.6: "the gap to each adjacent `CONFIRMED` slot must be at
        least the changeover buffer this run requires
        (`ERR_SLOT_CHANGEOVER_BUFFER_VIOLATION`, HTTP 409)"
        PRD §3.6: "a computed `buffer_minutes` taken from the required
        changeover level: 0 minutes for `NONE`, 30 for `DRY_CLEAN`, 60 for
        `WET_CLEAN`, and 90 for `SWAB_VALIDATE`."

        Design: Difficulty/resource_temporal_overlap/slot_changeover_buffer_gap_rule
        """
        ns = fixtures.setup_peanut_line_scenario()
        line_version = fixtures.get_line_version(ns.lp["id"])
        # Gap exactly 90 minutes after the PEANUT slot: meets the SWAB_VALIDATE
        # buffer inclusively.
        scheduled = validate_success(
            client.schedule_run(
                ns.run_0["id"],
                {"start_utc": "2026-08-05T11:30:00Z",
                 "end_utc": "2026-08-05T12:30:00Z",
                 "expected_line_version": line_version},
                PP,
            ),
            200,
        )
        assert scheduled["status"] == "SCHEDULED"
        slot = fixtures.get_run_slot(ns.run_0["id"])
        assert slot["buffer_minutes"] == 90
        changeover = fixtures.get_to_changeover(ns.run_0["id"])
        assert changeover["required_level"] == "SWAB_VALIDATE"


class TestChangeoverLevelMatrixStaleness:
    def test_null_wet_clean_and_fresh_wet_clean_levels(self, api):
        """PRD §3.7: "The level is decided by the first rule that matches, in
        this order: when the from-profile is empty, the level is `NONE`; when
        the carryover set is empty — everything the line last ran is also
        declared on the incoming product — the level is `DRY_CLEAN`; when the
        carryover set contains a high-risk allergen (`PEANUT` or `TREE_NUT`)
        or spans two or more distinct allergens, the level is `SWAB_VALIDATE`;
        otherwise, when more than 1,440 minutes — a full 24-hour day — have
        elapsed on the logical clock since the line's `last_wet_clean_utc`, or
        no wet clean has ever been validated, the level is `SWAB_VALIDATE` as
        well; and in every remaining case the level is `WET_CLEAN`."

        Design: Difficulty/combinatorial_formula/changeover_level_flips_on_wet_clean_staleness
        """
        ns = fixtures.setup_staleness_chain_through_c()
        # Run B: carryover {MILK} (|1|, not high-risk) but no wet clean ever
        # validated -> SWAB_VALIDATE.
        co_b = validate_success(client.get_changeover(ns.co_b["id"], QM), 200)
        assert co_b["required_level"] == "SWAB_VALIDATE"
        # Run C: identical single-allergen non-high-risk carryover {SOY}, with
        # staleness 270 minutes (<= 1440) -> WET_CLEAN, buffer 60.
        co_c = validate_success(client.get_changeover(ns.co_c["id"], QM), 200)
        assert co_c["required_level"] == "WET_CLEAN"
        slot_c = fixtures.get_run_slot(ns.run_c["id"])
        assert slot_c["buffer_minutes"] == 60

    def test_stale_wet_clean_flips_same_carryover_shape_to_swab(self, api):
        """PRD §3.7: "otherwise, when more than 1,440 minutes — a full 24-hour
        day — have elapsed on the logical clock since the line's
        `last_wet_clean_utc`, or no wet clean has ever been validated, the
        level is `SWAB_VALIDATE` as well; and in every remaining case the
        level is `WET_CLEAN`."

        Design: Difficulty/combinatorial_formula/changeover_level_flips_on_wet_clean_staleness
        """
        ns = fixtures.setup_staleness_chain_through_c()
        # Run D: carryover {MILK} again, but 1815 minutes (> 1440) since the
        # last validated wet clean (2026-08-02T15:45Z) at schedule time
        # (2026-08-03T22:00Z) -> SWAB_VALIDATE.
        rd = fixtures.create_revision(
            ns.fm["id"], [fixtures.line(ns.soy["id"], 30, True)],
            target_protein=15, claim_tags=[],
        )
        fixtures.march_revision_to_approved(rd["id"])
        fixtures.set_clock("2026-08-03T22:00:00Z")
        run_d = fixtures.create_run(rd["id"], ns.ag["id"], ns.ln1["id"], 100)
        fixtures.schedule_run_fresh(
            run_d["id"], ns.ln1["id"],
            "2026-08-04T08:00:00Z", "2026-08-04T10:00:00Z",
        )
        co_d = fixtures.get_to_changeover(run_d["id"])
        assert co_d["required_level"] == "SWAB_VALIDATE"
        slot_d = fixtures.get_run_slot(run_d["id"])
        assert slot_d["buffer_minutes"] == 90
        # Control: run C's changeover under identical carryover shape was
        # WET_CLEAN when the wet clean was fresh.
        co_c = validate_success(client.get_changeover(ns.co_c["id"], QM), 200)
        assert co_c["required_level"] == "WET_CLEAN"


class TestScheduleGuards:
    def test_schedule_in_past_rejected(self, api):
        """PRD §3.6: "the slot must not begin in the past relative to the
        logical clock (`ERR_SCHEDULE_IN_PAST`, HTTP 422)"

        Design: Corner/validations/c_schedule_in_past
        """
        plant = fixtures.setup_basic_plant()
        fixtures.set_clock("2026-08-05T06:00:00Z")
        run = fixtures.create_run(plant.r1["id"], plant.ag["id"],
                                  plant.ln1["id"], 100)
        resp = client.schedule_run(
            run["id"],
            {"start_utc": "2026-08-04T08:00:00Z", "end_utc": "2026-08-04T10:00:00Z",
             "expected_line_version": fixtures.get_line_version(plant.ln1["id"])},
            PP,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_IN_PAST, 422)
        stayed = validate_success(client.get_production_run(run["id"], PP), 200)
        assert stayed["status"] == "PLANNED"

    def test_stale_line_version_rejected_on_schedule(self, api):
        """PRD §2.5: "Scheduling a production run requires the request to
        carry `expected_line_version`, the client-observed `version` of the
        target production line. Because every successful schedule creates a
        line slot plus a changeover event and increments the line's `version`
        by one, a client holding an older observed version computed its
        overlap and buffer checks against a stale occupancy picture; if
        `expected_line_version` does not match the line's current `version`,
        the schedule is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/c_occ_stale_line_on_schedule
        """
        plant = fixtures.setup_basic_plant(whey_qty=300)
        stale_line_version = plant.ln1["version"]
        fixtures.set_clock("2026-08-05T06:00:00Z")
        run1 = fixtures.create_run(plant.r1["id"], plant.ag["id"],
                                   plant.ln1["id"], 100)
        run2 = fixtures.create_run(plant.r1["id"], plant.ag["id"],
                                   plant.ln1["id"], 100)
        fixtures.schedule_run_fresh(run1["id"], plant.ln1["id"])
        # run1's schedule advanced the line's version; replaying the version
        # observed at line creation is stale.
        resp = client.schedule_run(
            run2["id"],
            {"start_utc": "2026-08-06T12:00:00Z", "end_utc": "2026-08-06T14:00:00Z",
             "expected_line_version": stale_line_version},
            PP,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        stayed = validate_success(client.get_production_run(run2["id"], PP), 200)
        assert stayed["status"] == "PLANNED"


class TestChangeoverSwabWorkflow:
    def test_swab_not_required_and_validator_sod(self, api):
        """PRD §3.7: "A `LabTechnician` then records the allergen swab, moving
        the event from `CLEANING_LOGGED` to `SWAB_RECORDED` — but only when
        the event's `required_level` is `SWAB_VALIDATE`; recording a swab on
        any other level is rejected with `ERR_SWAB_NOT_REQUIRED` (HTTP 422)."
        PRD §3.7: "a swab-controlled event must instead pass through
        `SWAB_RECORDED`, where validation enforces two guards in order — the
        recorded `swab_allergen_ppm` must be at most 20 parts per million
        (`ERR_SWAB_PPM_EXCEEDS_LIMIT`, HTTP 422), and the validator's
        `X-User-ID` must differ from `swab_recorded_by` (`ERR_SOD_VIOLATION`,
        HTTP 422)."

        Design: Corner/validations/c_changeover_sod_and_swab_not_required
        """
        sup = fixtures.create_supplier("S1", "APPROVED", ["MILK", "SOY"])
        whey = fixtures.create_ingredient(
            "WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8
        )
        soy = fixtures.create_ingredient(
            "SOYPROT", "PROTEIN", ["SOY"], nominal_protein_pct=0.85
        )
        fixtures.receive_and_release_lot(whey["id"], sup["id"], "WL-1", 300,
                                         coa_protein_pct=0.8)
        fixtures.receive_and_release_lot(soy["id"], sup["id"], "SPL-1", 100,
                                         coa_protein_pct=0.85)
        cust = fixtures.create_customer("C1")
        ag = fixtures.create_active_agreement(cust["id"], moq=100, committed=3000)
        fm = fixtures.create_formula(cust["id"], "FM", bar_weight_g=60)
        rm = fixtures.create_revision(
            fm["id"], [fixtures.line(whey["id"], 40, True)],
            target_protein=19, claim_tags=[],
        )
        fixtures.march_revision_to_approved(rm["id"])
        fs = fixtures.create_formula(cust["id"], "FS", bar_weight_g=60)
        rsv = fixtures.create_revision(
            fs["id"], [fixtures.line(soy["id"], 30, True)],
            target_protein=15, claim_tags=[],
        )
        fixtures.march_revision_to_approved(rsv["id"])
        l2 = fixtures.create_line("L2")
        fixtures.set_clock("2026-08-05T06:00:00Z")

        run1 = fixtures.create_run(rm["id"], ag["id"], l2["id"], 100)
        fixtures.schedule_run_fresh(run1["id"], l2["id"],
                                    "2026-08-06T08:00:00Z", "2026-08-06T10:00:00Z")
        run2 = fixtures.create_run(rm["id"], ag["id"], l2["id"], 100)
        fixtures.schedule_run_fresh(run2["id"], l2["id"],
                                    "2026-08-06T10:30:00Z", "2026-08-06T12:00:00Z")
        co2 = fixtures.get_to_changeover(run2["id"])
        # Control: identical incoming profile -> empty carryover -> DRY_CLEAN.
        assert co2["required_level"] == "DRY_CLEAN"
        validate_success(client.log_cleaning(co2["id"], PP), 200)

        validate_success(client.verify_pre_run(run1["id"], QM), 200)
        validate_success(client.start_run(run1["id"], PP), 200)
        validate_success(
            client.complete_run(
                run1["id"], {"produced_cases": 100, "scrapped_cases": 0}, PP
            ),
            200,
        )

        run3 = fixtures.create_run(rsv["id"], ag["id"], l2["id"], 100)
        fixtures.schedule_run_fresh(run3["id"], l2["id"],
                                    "2026-08-06T13:30:00Z", "2026-08-06T15:00:00Z")
        co3 = fixtures.get_to_changeover(run3["id"])
        # Control: carryover {MILK} with no validated wet clean -> SWAB_VALIDATE.
        assert co3["required_level"] == "SWAB_VALIDATE"
        validate_success(client.log_cleaning(co3["id"], PP), 200)
        validate_success(
            client.record_swab(co3["id"], {"swab_allergen_ppm": 10},
                               make_lab_technician_headers("shared-9")),
            200,
        )

        # record-swab on a DRY_CLEAN event is rejected.
        validate_error(
            client.record_swab(co2["id"], {"swab_allergen_ppm": 5},
                               make_lab_technician_headers("lt-002")),
            ApiErrorId.ERR_SWAB_NOT_REQUIRED, 422,
        )
        # The swab recorder cannot validate their own swab.
        validate_error(
            client.validate_changeover(co3["id"],
                                       make_quality_manager_headers("shared-9")),
            ApiErrorId.ERR_SOD_VIOLATION, 422,
        )
        validated = validate_success(
            client.validate_changeover(co3["id"],
                                       make_quality_manager_headers("qm-003")),
            200,
        )
        assert validated["status"] == "VALIDATED"

    def test_fail_reclean_cycle_and_swab_ppm_limit(self, api):
        """PRD §3.7: "a swab-controlled event must instead pass through
        `SWAB_RECORDED`, where validation enforces two guards in order — the
        recorded `swab_allergen_ppm` must be at most 20 parts per million
        (`ERR_SWAB_PPM_EXCEEDS_LIMIT`, HTTP 422), and the validator's
        `X-User-ID` must differ from `swab_recorded_by` (`ERR_SOD_VIOLATION`,
        HTTP 422)."
        PRD §3.7: "An event that has `FAILED` may be re-cleaned: logging the
        cleaning again returns it from `FAILED` to `CLEANING_LOGGED` and
        clears its previous `swab_allergen_ppm` and `swab_recorded_by`."
        PRD §3.7: "validating either a `WET_CLEAN` or a `SWAB_VALIDATE` event
        refreshes the line's `last_wet_clean_utc` to the current logical
        clock, incrementing the line's `version`."

        Design: Corner/state_machines/c_changeover_fail_reclean_cycle_and_ppm_limit
        """
        ns = fixtures.setup_swab_gated_run(swab_ppm=21, swab_user_id="lt-001")
        co_id = ns.co_b["id"]
        # 21 ppm exceeds the 20 ppm limit: validation rejected, event stays.
        validate_error(
            client.validate_changeover(co_id, make_quality_manager_headers("qm-001")),
            ApiErrorId.ERR_SWAB_PPM_EXCEEDS_LIMIT, 422,
        )
        mid = validate_success(client.get_changeover(co_id, QM), 200)
        assert mid["status"] == "SWAB_RECORDED"
        # Fail the event, then re-clean: swab fields are cleared.
        failed = validate_success(client.fail_changeover(co_id, QM), 200)
        assert failed["status"] == "FAILED"
        recleaned = validate_success(client.log_cleaning(co_id, PP), 200)
        assert recleaned["status"] == "CLEANING_LOGGED"
        assert recleaned.get("swab_allergen_ppm") is None
        # Fresh swab within the limit, validated by a different user.
        validate_success(
            client.record_swab(co_id, {"swab_allergen_ppm": 10},
                               make_lab_technician_headers("lt-001")),
            200,
        )
        validated = validate_success(
            client.validate_changeover(co_id, make_quality_manager_headers("qm-001")),
            200,
        )
        assert validated["status"] == "VALIDATED"
        line_after = validate_success(client.get_line(ns.lx["id"], QM), 200)
        assert line_after["last_wet_clean_utc"] is not None
        assert line_after["last_wet_clean_utc"].startswith("2026-08-05T06:00:00")
