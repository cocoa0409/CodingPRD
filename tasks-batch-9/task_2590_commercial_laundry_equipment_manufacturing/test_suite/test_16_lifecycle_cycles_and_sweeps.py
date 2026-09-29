"""Repeated transitions, clock-driven sweeps and compensating cascades.

Pins the non-idempotent training-completion self-loop, the two sweeps one clock
advance runs, the AUTHORIZED to PROBATION and back cycle, and the certification
regrant that lifts a quality hold back into REWORK.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    CHANNEL_MANAGER,
    COMPLIANCE_OFFICER,
    PLANT_MANAGER,
    PRODUCT_ENGINEER,
    TRAINING_ADMIN,
)


class TestTrainingCompletionReplay:
    def test_01_replaying_a_training_completion_is_refused_not_a_no_op(self, api):
        """The same technician and module cannot be credited twice to a distributor.

        PRD: "Each record is stored as a composite key formed from the technician identifier and the module name joined by a vertical bar, appended to the distributor's append-only `completed_training_keys` array; that composite key is precisely what makes a duplicate submission detectable, and re-submitting the same technician for the same module at the same distributor is rejected with `ERR_TRAINING_RECORD_DUPLICATE`."
        Design: Corner/state_machines/duplicate_training_completion_rejected_not_idempotent
        """
        distributor = fx.make_distributor(api)
        technician = fx.make_distributor_technician(
            api, distributor["id"], "T-201", "Rosa Diaz"
        )
        version_before = distributor["version"]

        first = validate_success(
            api.create_training_completion(
                distributor["id"],
                f.training_completion_payload(
                    technician["id"], "INSTALLATION", "2026-07-20"
                ),
                TRAINING_ADMIN,
            ),
            expected_status=200,
        )
        assert first["distributor_state"] == "PENDING_TRAINING"
        assert len(first["completed_training_keys"]) == 1
        assert first["installation_training_state"] == "IN_PROGRESS"

        response = api.create_training_completion(
            distributor["id"],
            f.training_completion_payload(
                technician["id"], "INSTALLATION", "2026-07-20"
            ),
            TRAINING_ADMIN,
        )
        validate_error(response, E.ERR_TRAINING_RECORD_DUPLICATE, expected_status=409)

        stored = validate_success(
            api.get_distributor(distributor["id"], CHANNEL_MANAGER),
            expected_status=200,
        )
        assert len(stored["completed_training_keys"]) == 1
        assert stored["trained_technician_count"] == 1
        assert stored["version"] == version_before + 1


class TestLogicalClockSweeps:
    def test_01_one_advance_expires_a_technician_and_retires_a_program(self, api):
        """A single clock advance lapses a certification and retires a rebate program.

        PRD: "The first sweep handles technician certification lapse: every `Technician` whose `cert_state` is `ACTIVE` and whose `cert_expires_on` is at or before the new instant moves to `EXPIRED` with `cert_scopes` emptied to an empty array, processed in `created_at` ascending order, and each swept technician's `version` advances by 1."
        Design: Corner/state_machines/clock_advance_expires_technician_and_retires_rebate_program
        """
        technician = fx.make_technician(
            api, employee_code="T-100", full_name="Ann Ito", employer="FACTORY"
        )
        granted = fx.grant_scopes(
            api,
            technician["id"],
            ["DRUM_FAB"],
            expires_on="2026-09-01T00:00:00Z",
        )
        program = fx.make_rebate_program(
            api,
            program_code="UTIL-A-W1",
            utility_code="UTIL-A",
            program_class="COMBINED",
            eligible_product_lines=["ON_PREMISES"],
            max_water_gal_per_cwt=1.10,
            max_kwh_per_cwt=0.45,
            min_capacity_rating_lb=40,
            rebate_base_cents=50000,
            capacity_bonus_cents_per_10lb=10000,
            rebate_cap_cents=70000,
            effective_from="2026-07-01T00:00:00Z",
            effective_to="2026-08-31T00:00:00Z",
        )

        swept = validate_success(
            api.set_clock("2026-09-01T00:00:00Z", PLANT_MANAGER), expected_status=200
        )
        assert swept["current_utc"][:19] == "2026-09-01T00:00:00"
        assert swept["expired_technician_count"] == 1
        assert swept["retired_program_count"] == 1

        stored_technician = validate_success(
            api.get_technician(technician["id"], TRAINING_ADMIN), expected_status=200
        )
        assert stored_technician["cert_state"] == "EXPIRED"
        assert stored_technician["cert_scopes"] == []
        assert stored_technician["cert_expires_on"][:19] == "2026-09-01T00:00:00"
        assert stored_technician["version"] == granted["version"] + 1

        stored_program = validate_success(
            api.get_rebate_program(program["id"], COMPLIANCE_OFFICER),
            expected_status=200,
        )
        assert stored_program["program_state"] == "RETIRED"


class TestDistributorStandingCycle:
    def test_01_probation_and_reinstatement_return_the_distributor_to_authorized(
        self, api, authorized_distributor
    ):
        """A distributor cycles out to PROBATION and back to a clean AUTHORIZED.

        PRD: "A reinstatement moves the distributor from `PROBATION` back to `AUTHORIZED` and resets `probation_reason` to `NONE`."
        Design: Corner/state_machines/distributor_probation_then_reinstatement_cycle
        """
        distributor = authorized_distributor["distributor"]
        version_at_authorization = distributor["version"]

        on_probation = validate_success(
            api.create_distributor_status_action(
                distributor["id"],
                f.status_action_payload("PROBATION", reason="WARRANTY_ABUSE"),
                CHANNEL_MANAGER,
            ),
            expected_status=200,
        )
        assert on_probation["distributor_state"] == "PROBATION"
        assert on_probation["probation_reason"] == "WARRANTY_ABUSE"

        reinstated = validate_success(
            api.create_distributor_status_action(
                distributor["id"],
                f.status_action_payload("REINSTATE"),
                CHANNEL_MANAGER,
            ),
            expected_status=200,
        )
        assert reinstated["distributor_state"] == "AUTHORIZED"
        assert reinstated["probation_reason"] == "NONE"
        assert reinstated["version"] == version_at_authorization + 2
        assert reinstated["installation_training_state"] == "COMPLETE"
        assert reinstated["trained_technician_count"] == 2

    def test_02_a_second_reinstatement_from_authorized_is_refused(
        self, api, authorized_distributor
    ):
        """Reinstatement is only legal from PROBATION, so it cannot be replayed.

        PRD: "Each of the three advances the distributor's `version` by 1, and an action attempted from a state the transition does not permit is `ERR_DISTRIBUTOR_STATE_INVALID`."
        Design: Corner/state_machines/distributor_probation_then_reinstatement_cycle
        """
        distributor = authorized_distributor["distributor"]
        validate_success(
            api.create_distributor_status_action(
                distributor["id"],
                f.status_action_payload("PROBATION", reason="WARRANTY_ABUSE"),
                CHANNEL_MANAGER,
            ),
            expected_status=200,
        )
        validate_success(
            api.create_distributor_status_action(
                distributor["id"],
                f.status_action_payload("REINSTATE"),
                CHANNEL_MANAGER,
            ),
            expected_status=200,
        )

        response = api.create_distributor_status_action(
            distributor["id"], f.status_action_payload("REINSTATE"), CHANNEL_MANAGER
        )
        validate_error(response, E.ERR_DISTRIBUTOR_STATE_INVALID, expected_status=409)

        stored = validate_success(
            api.get_distributor(distributor["id"], CHANNEL_MANAGER),
            expected_status=200,
        )
        assert stored["distributor_state"] == "AUTHORIZED"


class TestCertificationRegrantCompensation:
    def test_01_regrant_clears_the_integrity_hold_and_moves_the_unit_to_rework(
        self, api
    ):
        """Re-certifying the revoked builder frees the held unit into REWORK.

        PRD: "Among those released units, any that is sitting in `QUALITY_HOLD` moves from `QUALITY_HOLD` to `REWORK` with `rework_count` increased by 1; if that increase pushes `rework_count` above the model's `max_rework_cycles`, the unit is scrapped immediately by the rule in §3.6."
        Design: Corner/state_machines/certification_regrant_lifts_quality_hold_back_to_rework
        """
        env = fx.make_floor_environment(api)
        technician_id = env["technician"]["id"]
        unit = fx.make_unit_in_qa_hold(api, env, serial_number="SN-0001")

        validate_success(
            api.create_certification_action(
                technician_id,
                f.revoke_payload(reason="AUDIT_FINDING"),
                TRAINING_ADMIN,
            ),
            expected_status=200,
        )
        held = validate_success(
            api.get_build_order(unit["build"]["id"], PLANT_MANAGER),
            expected_status=200,
        )
        a.assert_build_state(held, "QUALITY_HOLD")
        assert held["integrity_hold"] is True
        held_model = validate_success(
            api.get_machine_model(env["model"]["id"], PRODUCT_ENGINEER),
            expected_status=200,
        )
        assert held_model["quality_hold_unit_count"] == 1

        regranted = validate_success(
            api.create_certification_action(
                technician_id,
                f.grant_payload(
                    scopes=["DRUM_FAB", "BEARING_INSTALL", "CONTROL_INTEGRATION"],
                    expires_on="2027-06-30T00:00:00Z",
                ),
                TRAINING_ADMIN,
            ),
            expected_status=200,
        )
        assert regranted["cert_state"] == "ACTIVE"
        assert regranted["revocation_count"] == 1

        released = validate_success(
            api.get_build_order(unit["build"]["id"], PLANT_MANAGER),
            expected_status=200,
        )
        a.assert_build_state(released, "REWORK")
        assert released["integrity_hold"] is False

        stored_model = validate_success(
            api.get_machine_model(env["model"]["id"], PRODUCT_ENGINEER),
            expected_status=200,
        )
        assert stored_model["quality_hold_unit_count"] == 0
