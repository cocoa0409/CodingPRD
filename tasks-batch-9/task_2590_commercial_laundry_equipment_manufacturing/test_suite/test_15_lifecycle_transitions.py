"""Guarded lifecycle transitions for build orders, machine models and dossiers.

Pins the PLANNED entry state of a serialized unit, the QA_HOLD-only final
inspection gate, the RELEASED-only manual suspension, the FAIL edge that sends a
BEARINGS_DONE unit to REWORK, and the terminal REJECTED certification dossier.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    ENERGY_REVIEWER,
    PLANT_MANAGER,
    PRODUCT_ENGINEER,
    WATER_REVIEWER,
    make_quality_inspector_headers,
    make_technician_headers,
)


class TestBuildOrderEntryState:
    def test_01_new_unit_enters_planned_with_every_counter_at_zero(
        self, api, certified_model
    ):
        """A unit opened against an already-certified model still enters PLANNED.

        PRD: "A new unit begins with `build_state` at `PLANNED`, `rework_count` at 0, `integrity_hold` false, `labor_minutes_total` at 0, `station_pass_count` at 0, `scrap_reason` at `NONE`, `qa_inspector_user_id` null and `accepted_at` null."
        Design: Corner/state_machines/build_order_initial_state_is_planned
        """
        model = certified_model["model"]
        response = api.create_build_order(
            f.build_order_payload(
                model["id"],
                serial_number="SN-0001",
                planned_start_at="2026-08-01T07:00:00Z",
            ),
            PLANT_MANAGER,
        )
        build = validate_success(response, expected_status=201)

        a.assert_build_state(build, "PLANNED")
        assert build["rework_count"] == 0
        assert build["station_pass_count"] == 0
        assert build["labor_minutes_total"] == 0
        assert build["integrity_hold"] is False
        assert build["scrap_reason"] == "NONE"
        assert build["accepted_at"] is None
        assert build["qa_inspector_user_id"] is None

        stored_model = validate_success(
            api.get_machine_model(model["id"], PRODUCT_ENGINEER), expected_status=200
        )
        assert stored_model["certification_state"] == "CERTIFIED"
        assert stored_model["accepted_unit_count"] == 0


class TestFinalInspectionStateGate:
    def test_01_qa_signoff_on_a_unit_still_on_the_floor_is_refused(self, api):
        """Final inspection is reachable only from QA_HOLD, never from ON_FLOOR.

        PRD: "The unit must be in `QA_HOLD`, or the request is `ERR_BUILD_STATE_INVALID`."
        Design: Corner/state_machines/qa_signoff_from_on_floor_rejected
        """
        env = fx.make_certified_model(api)
        # The inspector identity resolves to a real technician row but holds no
        # scopes at all, so the state check must outrank the certification check.
        inspector = fx.make_technician(
            api, employee_code="T-900", full_name="Ken Ono", employer="FACTORY"
        )
        build = fx.make_build_order(
            api, env["model"]["id"], serial_number="SN-0001"
        )
        fx.release_build(api, build["id"])

        response = api.qa_signoff(
            build["id"],
            f.qa_signoff_payload("APPROVE"),
            make_quality_inspector_headers(inspector["id"]),
        )
        validate_error(response, E.ERR_BUILD_STATE_INVALID, expected_status=409)

        stored = validate_success(
            api.get_build_order(build["id"], PLANT_MANAGER), expected_status=200
        )
        a.assert_build_state(stored, "ON_FLOOR")
        assert stored["qa_inspector_user_id"] is None

        stored_model = validate_success(
            api.get_machine_model(env["model"]["id"], PRODUCT_ENGINEER),
            expected_status=200,
        )
        assert stored_model["accepted_unit_count"] == 0


class TestModelManualSuspension:
    def test_01_suspending_a_certified_but_unreleased_model_is_refused(
        self, api, certified_model
    ):
        """A manual suspension is available only on a model that reached RELEASED.

        PRD: "A manual suspension moves the model from `RELEASED` to `SUSPENDED`, sets `suspended_reason` to `MANUAL`, empties `rebate_program_codes` and resets `rebate_amount_cents` to 0, and advances the model's `version` by 1; attempting it from any state other than `RELEASED` is likewise `ERR_MODEL_STATE_INVALID`."
        Design: Corner/state_machines/model_suspend_before_release_rejected
        """
        model = certified_model["model"]
        response = api.machine_model_lifecycle_action(
            model["id"],
            f.lifecycle_action_payload("SUSPEND", reason="MANUAL"),
            PRODUCT_ENGINEER,
        )
        validate_error(response, E.ERR_MODEL_STATE_INVALID, expected_status=409)

        stored = validate_success(
            api.get_machine_model(model["id"], PRODUCT_ENGINEER), expected_status=200
        )
        assert stored["certification_state"] == "CERTIFIED"
        assert stored["suspended_reason"] == "NONE"


class TestStationChainFailEdge:
    def test_01_failing_control_log_sends_a_bearings_done_unit_to_rework(self, api):
        """A failing control-integration log short-circuits the chain into REWORK.

        PRD: "A `FAIL` logged while the unit is in `ON_FLOOR`, `DRUM_DONE` or `BEARINGS_DONE` writes the log, moves the unit to `REWORK`, increases `rework_count` by 1, and advances the unit's `version` by 1 — and if that increase pushes `rework_count` above the model's `max_rework_cycles`, the unit is scrapped immediately by the rule set out in §3.6."
        Design: Corner/state_machines/station_log_fail_from_bearings_done_jumps_to_rework
        """
        env = fx.make_floor_environment(api)
        technician_id = env["technician"]["id"]
        build = fx.make_build_order(api, env["model"]["id"], serial_number="SN-0001")
        fx.release_build(api, build["id"])
        fx.log_station_pass(
            api,
            build["id"],
            env["stations"]["drum"],
            technician_id,
            "2026-08-01T08:00:00Z",
            "2026-08-01T09:00:00Z",
        )
        fx.log_station_pass(
            api,
            build["id"],
            env["stations"]["bearing"],
            technician_id,
            "2026-08-01T09:00:00Z",
            "2026-08-01T10:00:00Z",
            bearing_preload_micron=24.00,
        )

        response = api.create_station_log(
            build["id"],
            f.station_log_payload(
                env["stations"]["control"]["id"],
                "CONTROL_INTEGRATION",
                "2026-08-01T10:00:00Z",
                "2026-08-01T10:30:00Z",
                "FAIL",
                defect_code="CONTROL_FIRMWARE",
            ),
            make_technician_headers(technician_id),
        )
        log = validate_success(response, expected_status=201)
        assert log["outcome"] == "FAIL"
        assert log["defect_code"] == "CONTROL_FIRMWARE"
        assert log["labor_minutes"] == 30

        stored = validate_success(
            api.get_build_order(build["id"], PLANT_MANAGER), expected_status=200
        )
        a.assert_build_state(stored, "REWORK")
        assert stored["station_pass_count"] == 2
        assert stored["labor_minutes_total"] == 150

        rows, meta = validate_paginated(
            api.list_station_logs(PLANT_MANAGER, build_order_id=build["id"])
        )
        assert len(rows) == 3
        assert meta["total_count"] == 3


class TestDossierTerminalRejection:
    def test_01_a_rejected_dossier_locks_the_still_pending_dimension(self, api):
        """One REJECT ends the dossier and the second dimension can never be decided.

        PRD: "`REJECTED` is terminal for a dossier; there is no appeal path, and the parent model is untouched and remains in `certification_state` `DRAFT`."
        Design: Corner/state_machines/dossier_rejected_state_is_terminal_and_locks_reviews
        """
        model = fx.make_model(api)
        dossier = fx.make_dossier(api, model["id"])

        rejected = validate_success(
            api.create_dossier_review(
                dossier["id"],
                f.review_payload(
                    "ENERGY", "REJECT", note="kWh drift beyond tolerance"
                ),
                ENERGY_REVIEWER,
            ),
            expected_status=200,
        )
        assert rejected["dossier_state"] == "REJECTED"
        assert rejected["energy_review_state"] == "REJECTED"
        assert rejected["water_review_state"] == "PENDING"

        response = api.create_dossier_review(
            dossier["id"], f.review_payload("WATER", "APPROVE"), WATER_REVIEWER
        )
        validate_error(response, E.ERR_DOSSIER_STATE_INVALID, expected_status=409)

        stored = validate_success(
            api.get_certification_dossier(dossier["id"], COMPLIANCE_OFFICER),
            expected_status=200,
        )
        assert stored["water_review_state"] == "PENDING"
        assert stored["water_reviewer_user_id"] is None
        assert stored["certified_at"] is None

        stored_model = validate_success(
            api.get_machine_model(model["id"], PRODUCT_ENGINEER), expected_status=200
        )
        assert stored_model["certification_state"] == "DRAFT"
