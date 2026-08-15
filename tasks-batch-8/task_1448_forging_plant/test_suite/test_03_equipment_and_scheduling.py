"""Work centers, die sets, catalog browsing, run scheduling turnaround, and
work-center window conservation (PRD §2.3, §2.4, §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    factories,
    get_success_data,
    is_valid_uuid,
    new_alloy,
    new_die_set,
    new_forge_run,
    new_work_center,
    new_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
FORGE = TEST_USERS["forge_operator_headers"]
DIE = TEST_USERS["die_tech_headers"]
SP = TEST_USERS["sales_planner_headers"]


class TestWorkCenterBasics:
    def test_work_center_rejects_client_supplied_identity(self, api):
        """PRD §2.4: "`id` (string): a server-minted UUID with no type prefix,
        unique across the system." A client-supplied `id` / `version` on
        creation cannot override the server-minted identity.

        Design: Corner/entities/system_field_input_ignored_on_create
        """
        resp = api.create_work_center(
            {
                "code": "WC-9",
                "type": "PRESS",
                "rated_tonnage": 500,
                "id": "11111111-1111-4111-8111-111111111111",
                "version": 99,
            },
            PM,
        )
        wc = validate_success(resp, 201)
        assert wc["id"] != "11111111-1111-4111-8111-111111111111", (
            "server must mint its own id"
        )
        assert is_valid_uuid(wc["id"])
        assert isinstance(wc["version"], int), "version is system-managed"

    def test_work_center_invalid_type_rejected(self, api):
        """PRD §3.4: "A `PlantManager` registers each press and hammer as a
        work center carrying a unique `code`, a `type` of either `PRESS` or
        `HAMMER`, and a `rated_tonnage`."
        PRD §2.10: "Request-body well-formedness — required fields present,
        enum values valid, numeric ranges sane (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/workcenter_invalid_enum_rejected
        """
        resp = api.create_work_center(
            {"code": "WC-9", "type": "SCREW", "rated_tonnage": 500}, PM
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_alloy_spec_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10 when omitted, accepts a minimum of 1, and is bounded
        above at 100. The `offset` parameter specifies how many items to skip
        and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_pagination_envelope_and_defaults
        """
        api.create_alloy_spec(factories.alloy_spec_payload(), PM)
        api.create_alloy_spec(factories.alloy_spec_payload(
            grade_code="AL-7075", name="Aluminum 7075", forge_temp_min_f=750,
            forge_temp_max_f=850, reheat_limit=1, flash_allowance_pct=8.0,
            strokes_per_part=1, flow_stress_ksi=4.0, carbon_max_pct=0.10,
            manganese_max_pct=0.30, grain_flow_min_rating=4,
            macro_etch_required=False), PM)
        api.create_alloy_spec(factories.alloy_spec_payload(
            grade_code="AISI-8620", name="NiCrMo Steel", forge_temp_min_f=2050,
            forge_temp_max_f=2250, reheat_limit=2, flash_allowance_pct=10.0,
            strokes_per_part=3, flow_stress_ksi=7.5, carbon_max_pct=0.23,
            manganese_max_pct=0.90, grain_flow_min_rating=5,
            macro_etch_required=True), PM)
        page1, meta1 = validate_paginated(
            api.list_alloy_specs(PM, params={"limit": 2}))
        assert len(page1) == 2
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_alloy_specs(PM, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["offset"] == 2
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestRequiredTonnage:
    def test_required_tonnage_ceiling(self, api):
        """PRD §3.5: "At creation the server computes and stores
        `required_tonnage`: the `projected_area_in2` multiplied by the alloy's
        `flow_stress_ksi`, divided by two, rounded up to the next whole ton,
        with a floor of one ton."

        25.0 in^2 * 8.0 ksi / 2 = exactly 100 (no upward nudge); 25.01 in^2
        yields ceil(100.04) = 101.

        Design: Corner/calculations/calc_required_tonnage_ceiling
        """
        alloy = new_alloy()
        wo_a = new_work_order(alloy["id"], "WO-40", ordered_qty=2,
                              projected_area_in2=25.0)
        assert wo_a["required_tonnage"] == 100, (
            f"exact boundary must stay 100, got {wo_a['required_tonnage']}"
        )
        wo_b = new_work_order(alloy["id"], "WO-41", ordered_qty=2,
                              projected_area_in2=25.01)
        assert wo_b["required_tonnage"] == 101, (
            f"ceil(100.04) must round up to 101, got {wo_b['required_tonnage']}"
        )


class TestWorkCenterSelector:
    def test_autoselect_lowest_adequate_tonnage_then_empty_pool(self, api):
        """PRD §3.5: "When omitted, the server auto-selects: candidate centers
        must be `UP`, must match the order's `required_process` type, and must
        carry a `rated_tonnage` no less than the order's `required_tonnage`;
        the pool is ranked by ascending `rated_tonnage` with ties broken by
        earlier creation, and an empty pool fails the request with
        `ERR_NO_WORKCENTER_AVAILABLE`."

        The 120t center beats the 500t center for a 100t requirement; with
        both DOWN the pool is empty.

        Design: Corner/calculations/calc_workcenter_selector_lowest_tonnage_and_empty_pool
        """
        alloy = new_alloy()
        die = new_die_set("DIE-34")
        wc_a = new_work_center("WC-A", "PRESS", 500)
        wc_b = new_work_center("WC-B", "PRESS", 120)
        wo = new_work_order(alloy["id"], "WO-44", ordered_qty=4)
        assert wo["required_tonnage"] == 100
        run = new_forge_run(wo["id"], die["id"], "2026-08-03T09:00:00Z",
                            "2026-08-03T10:30:00Z", 4)
        assert run["work_center_id"] == wc_b["id"], (
            f"lowest adequate tonnage must win: expected {wc_b['id']}, got "
            f"{run['work_center_id']}"
        )
        get_success_data(api.set_work_center_status(wc_a["id"], {"status": "DOWN"}, PM))
        get_success_data(api.set_work_center_status(wc_b["id"], {"status": "DOWN"}, PM))
        version = get_success_data(api.get_work_order(wo["id"], SP))["version"]
        resp = api.create_forge_run(
            factories.forge_run_payload(
                wo["id"], die["id"], "2026-08-03T13:00:00Z",
                "2026-08-03T14:30:00Z", 4, version),
            FORGE,
        )
        validate_error(resp, ApiErrorId.ERR_NO_WORKCENTER_AVAILABLE, 409)


class TestDieRetirement:
    def test_install_retired_die_rejected(self, api):
        """PRD §3.4: "Retirement is terminal and available from either
        `AVAILABLE` or `WORN`, moving the die to `RETIRED`."
        PRD §3.4: "Installing an `AVAILABLE` die on a work center requires the
        center to be `UP` (`ERR_WORKCENTER_DOWN`) and no other die set already
        `INSTALLED` there (`ERR_WORKCENTER_HAS_DIE`); success moves the die to
        `INSTALLED` and records the `installed_work_center_id`."

        Design: Corner/state_machines/install_retired_die_rejected
        """
        die = new_die_set("DIE-25")
        wc = new_work_center("WC-1")
        retired = get_success_data(api.retire_die_set(die["id"], DIE))
        assert retired["status"] == "RETIRED"
        resp = api.install_die_set(die["id"], {"work_center_id": wc["id"]}, DIE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_die_set(die["id"], DIE))
        assert after["status"] == "RETIRED"


class TestWorkCenterTurnaround:
    def test_turnaround_gap_below_thirty_minutes_rejected(self, api):
        """PRD §3.5: "Runs sharing a work center must leave at least thirty
        minutes between windows — the new run's `planned_start` must fall no
        earlier than thirty minutes after an existing run's `planned_end`, or
        symmetrically its `planned_end` no later than thirty minutes before
        the other's `planned_start`; a gap of exactly thirty minutes is
        permitted, and runs in `CANCELLED` are excluded from the overlap set.
        A violation is rejected with `ERR_WORKCENTER_WINDOW_OVERLAP`."

        Run B starts only 15 minutes after run A ends on the same center; run D
        reuses the identical window on a different center without conflict.

        Design: Difficulty/resource_temporal_overlap/workcenter_turnaround_buffer_gap
        """
        alloy = new_alloy()
        die = new_die_set("DIE-19")
        wc1 = new_work_center("WC-1", "PRESS", 500)
        wc2 = new_work_center("WC-2", "PRESS", 500)
        wo_p = new_work_order(alloy["id"], "WO-16", ordered_qty=4)
        wo_q = new_work_order(alloy["id"], "WO-17", ordered_qty=4)
        run_a = new_forge_run(wo_p["id"], die["id"], "2026-08-03T09:00:00Z",
                              "2026-08-03T10:30:00Z", 4, work_center_id=wc1["id"])
        assert run_a["status"] == "SCHEDULED"
        run_d = new_forge_run(wo_q["id"], die["id"], "2026-08-03T09:00:00Z",
                              "2026-08-03T10:30:00Z", 4, work_center_id=wc2["id"])
        assert run_d["status"] == "SCHEDULED", "different center: no conflict"
        version_p = get_success_data(api.get_work_order(wo_p["id"], SP))["version"]
        resp_b = api.create_forge_run(
            factories.forge_run_payload(
                wo_p["id"], die["id"], "2026-08-03T10:45:00Z",
                "2026-08-03T12:00:00Z", 4, version_p, wc1["id"]),
            FORGE,
        )
        validate_error(resp_b, ApiErrorId.ERR_WORKCENTER_WINDOW_OVERLAP, 409)

    def test_turnaround_exactly_thirty_minutes_allowed_version_untouched(self, api):
        """PRD §3.5: "a gap of exactly thirty minutes is permitted"
        PRD §3.5: "Successful scheduling leaves the run in `SCHEDULED` and
        increments the order's `version` by one."

        A rejected attempt must not advance the order's version: the follow-up
        run at exactly the 30-minute boundary succeeds against the version
        captured before the rejection.

        Design: Difficulty/resource_temporal_overlap/workcenter_turnaround_buffer_gap
        """
        alloy = new_alloy()
        die = new_die_set("DIE-19")
        wc1 = new_work_center("WC-1", "PRESS", 500)
        wo_p = new_work_order(alloy["id"], "WO-16", ordered_qty=4)
        new_forge_run(wo_p["id"], die["id"], "2026-08-03T09:00:00Z",
                      "2026-08-03T10:30:00Z", 4, work_center_id=wc1["id"])
        version_p = get_success_data(api.get_work_order(wo_p["id"], SP))["version"]
        resp_b = api.create_forge_run(
            factories.forge_run_payload(
                wo_p["id"], die["id"], "2026-08-03T10:45:00Z",
                "2026-08-03T12:00:00Z", 4, version_p, wc1["id"]),
            FORGE,
        )
        validate_error(resp_b, ApiErrorId.ERR_WORKCENTER_WINDOW_OVERLAP, 409)
        resp_c = api.create_forge_run(
            factories.forge_run_payload(
                wo_p["id"], die["id"], "2026-08-03T11:00:00Z",
                "2026-08-03T12:30:00Z", 4, version_p, wc1["id"]),
            FORGE,
        )
        run_c = validate_success(resp_c, 201)
        assert run_c["status"] == "SCHEDULED", (
            "gap of exactly 30 minutes is permitted; the failed attempt must "
            "not have advanced the order's version"
        )


class TestRunCancelWindowConservation:
    def test_run_cancel_frees_workcenter_window(self, api):
        """PRD §3.5: "A run may be cancelled from `SCHEDULED` — by the operator,
        by the die-worn cascade, or by a work-order cancellation — or from
        `IN_PROGRESS` provided no heat has been recorded on it, with an
        operator-initiated cancel otherwise refused as `ERR_RUN_HAS_HEATS`;
        either way the work-center window is freed and the run leaves the
        overlap-check set."

        After run A [09:00,10:30] is cancelled, run C reuses the identical
        window on the same center — impossible while A occupied it.

        Design: Difficulty/compensating_invariant/run_cancel_restores_workcenter_window
        """
        alloy = new_alloy()
        die = new_die_set("DIE-20")
        wc = new_work_center("WC-1", "PRESS", 500)
        wo = new_work_order(alloy["id"], "WO-18", ordered_qty=4)
        run_a = new_forge_run(wo["id"], die["id"], "2026-08-03T09:00:00Z",
                              "2026-08-03T10:30:00Z", 4, work_center_id=wc["id"])
        new_forge_run(wo["id"], die["id"], "2026-08-03T11:00:00Z",
                      "2026-08-03T12:30:00Z", 4, work_center_id=wc["id"])
        cancelled = get_success_data(api.cancel_forge_run(run_a["id"], FORGE))
        assert cancelled["status"] == "CANCELLED"
        run_c = new_forge_run(wo["id"], die["id"], "2026-08-03T09:00:00Z",
                              "2026-08-03T10:30:00Z", 4, work_center_id=wc["id"])
        assert run_c["status"] == "SCHEDULED"
        assert run_c["work_center_id"] == wc["id"]

    def test_surviving_run_still_blocks_its_window_after_cancel(self, api):
        """PRD §3.5: "a gap of exactly thirty minutes is permitted, and runs in
        `CANCELLED` are excluded from the overlap set. A violation is rejected
        with `ERR_WORKCENTER_WINDOW_OVERLAP`."

        Cancelling run A frees only A's window: a new run overlapping the
        surviving run B [11:00,12:30] is still rejected.

        Design: Difficulty/compensating_invariant/run_cancel_restores_workcenter_window
        """
        alloy = new_alloy()
        die = new_die_set("DIE-20")
        wc = new_work_center("WC-1", "PRESS", 500)
        wo = new_work_order(alloy["id"], "WO-18", ordered_qty=4)
        run_a = new_forge_run(wo["id"], die["id"], "2026-08-03T09:00:00Z",
                              "2026-08-03T10:30:00Z", 4, work_center_id=wc["id"])
        new_forge_run(wo["id"], die["id"], "2026-08-03T11:00:00Z",
                      "2026-08-03T12:30:00Z", 4, work_center_id=wc["id"])
        get_success_data(api.cancel_forge_run(run_a["id"], FORGE))
        version = get_success_data(api.get_work_order(wo["id"], SP))["version"]
        resp_d = api.create_forge_run(
            factories.forge_run_payload(
                wo["id"], die["id"], "2026-08-03T11:15:00Z",
                "2026-08-03T12:00:00Z", 4, version, wc["id"]),
            FORGE,
        )
        validate_error(resp_d, ApiErrorId.ERR_WORKCENTER_WINDOW_OVERLAP, 409)
