"""The yield-breach cascade fired by a single final-inspection rejection.

One QA rejection scraps the unit at a zero rework ceiling, drags the model's
first-pass yield under its floor, pushes the certified dossier back to resurvey,
suspends the model, collapses the rebate entitlement and parks the model's
in-flight sibling unit on quality hold.
"""

from prd_bench_local_runner.testing import validate_success
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    PLANT_MANAGER,
    PRODUCT_ENGINEER,
    make_quality_inspector_headers,
)

# A ceiling of zero rework rounds scraps a unit on its first rejection, and the
# floor of 80.00 is what the resulting 0.00 yield breaches.
MODEL_OVERRIDES = {"max_rework_cycles": 0, "min_first_pass_yield_pct": 80.00}

# 60 lb capacity is two whole ten-pound steps above the program's 40 lb floor,
# so the payable value is 60000 + 2 * 5000 against a cap of 90000.
QUALIFIED_REBATE_CENTS = 70000
PROGRAM_CODE = "UTIL-A-W1"


def _released_model_with_two_units(api):
    """An active rebate program, a certified and released model whose dossier was
    awarded the rebate, one unit waiting in QA_HOLD and one sibling on the floor."""
    program = fx.make_rebate_program(api)
    env = fx.make_floor_environment(api, MODEL_OVERRIDES, certified_only=False)
    unit = fx.make_unit_in_qa_hold(api, env, serial_number="SN-0001")
    sibling = fx.make_build_order(
        api,
        env["model"]["id"],
        serial_number="SN-0002",
        planned_start_at="2026-08-01T14:00:00Z",
    )
    sibling = fx.release_build(api, sibling["id"])
    env["program"] = program
    env["build"] = unit["build"]
    env["sibling"] = sibling
    return env


def _reject_at_final_inspection(api, env):
    """The QA inspector rejects the unit for a drum weld defect."""
    return validate_success(
        api.qa_signoff(
            env["build"]["id"],
            f.qa_signoff_payload("REJECT", defect_code="DRUM_WELD"),
            make_quality_inspector_headers(env["inspector"]["id"]),
        ),
        expected_status=200,
    )


def _read_build(api, build_order_id):
    return validate_success(
        api.get_build_order(build_order_id, PLANT_MANAGER), expected_status=200
    )


def _read_model(api, model_id):
    return validate_success(
        api.get_machine_model(model_id, PRODUCT_ENGINEER), expected_status=200
    )


def _read_dossier(api, dossier_id):
    return validate_success(
        api.get_certification_dossier(dossier_id, COMPLIANCE_OFFICER),
        expected_status=200,
    )


class TestRejectionScrapsTheUnitAtAZeroReworkCeiling:
    def test_01_the_rejected_unit_is_scrapped_inside_the_same_request(self, api):
        """A rework count of 1 exceeds a ceiling of 0, so the unit is scrapped at once.

        PRD: "Whenever `rework_count` is increased — by a failing station log, by a rejecting inspection, or by the release of an integrity hold described in §3.4 — the new value is compared against the model's `max_rework_cycles`, and if it is **strictly greater**, the unit immediately moves from `REWORK` to `SCRAPPED` within the same request."
        Design: Difficulty/transitive_cascade/qa_reject_scrap_yield_breach_suspends_model_and_holds_siblings
        """
        env = _released_model_with_two_units(api)

        _reject_at_final_inspection(api, env)

        build = _read_build(api, env["build"]["id"])
        a.assert_build_state(build, "SCRAPPED")
        assert build["rework_count"] == 1

    def test_02_the_scrapped_unit_records_the_rework_limit_reason(self, api):
        """The scrap is attributed to the rework ceiling rather than to a defect.

        PRD: "A scrapped unit records `scrap_reason` as `REWORK_LIMIT`, increases the model's `scrapped_unit_count` by 1, triggers recomputation of the model's `first_pass_yield_pct`, and advances its own `version` by 1."
        Design: Difficulty/transitive_cascade/qa_reject_scrap_yield_breach_suspends_model_and_holds_siblings
        """
        env = _released_model_with_two_units(api)

        _reject_at_final_inspection(api, env)

        build = _read_build(api, env["build"]["id"])
        assert build["scrap_reason"] == "REWORK_LIMIT"

    def test_03_the_rejecting_inspector_is_recorded_on_the_unit(self, api):
        """The deciding inspector's own identifier is kept on the scrapped unit.

        PRD: "The unit's `rework_count` increases by 1, `qa_inspector_user_id` records the deciding inspector, the unit's `version` advances by 1, and the unit moves from `QA_HOLD` to `REWORK` — from which the `PlantManager` may release it to the floor again, restarting the station chain at drum fabrication."
        Design: Difficulty/transitive_cascade/qa_reject_scrap_yield_breach_suspends_model_and_holds_siblings
        """
        env = _released_model_with_two_units(api)

        _reject_at_final_inspection(api, env)

        build = _read_build(api, env["build"]["id"])
        assert build["qa_inspector_user_id"] == env["inspector"]["id"]


class TestModelYieldBookkeeping:
    def test_01_the_scrap_lands_in_the_model_unit_counters(self, api):
        """The model counts one scrapped unit and no accepted unit.

        PRD: "Hop three is the model bookkeeping — `scrapped_unit_count` or `accepted_unit_count` increased and `first_pass_yield_pct` recomputed."
        Design: Difficulty/transitive_cascade/qa_reject_scrap_yield_breach_suspends_model_and_holds_siblings
        """
        env = _released_model_with_two_units(api)

        _reject_at_final_inspection(api, env)

        model = _read_model(api, env["model"]["id"])
        assert model["scrapped_unit_count"] == 1
        assert model["accepted_unit_count"] == 0

    def test_02_a_single_scrapped_terminal_unit_yields_zero_percent(self, api):
        """One terminal unit that is a scrap gives a first-pass yield of 0.00.

        PRD: "Conversely, a model whose very first finished unit is a scrapped one shows a yield of `0.00` against one terminal unit, and that *does* breach."
        Design: Difficulty/transitive_cascade/qa_reject_scrap_yield_breach_suspends_model_and_holds_siblings
        """
        env = _released_model_with_two_units(api)

        _reject_at_final_inspection(api, env)

        model = _read_model(api, env["model"]["id"])
        a.assert_pct(model["first_pass_yield_pct"], 0.00)


class TestCertifiedDossierPushedBackToResurvey:
    def test_01_the_certified_dossier_moves_to_resurvey_required(self, api):
        """The compliance record is reopened with a yield-breach reason and one resurvey.

        PRD: "Hop four reaches the compliance record: the model's dossier sitting in `CERTIFIED` moves from `CERTIFIED` to `RESURVEY_REQUIRED`, with `resurvey_reason` set to `YIELD_BREACH`, `resurvey_count` increased by 1, `qualified_program_codes` emptied, `rebate_amount_cents` reset to 0, and the dossier's `version` advanced by 1."
        Design: Difficulty/transitive_cascade/qa_reject_scrap_yield_breach_suspends_model_and_holds_siblings
        """
        env = _released_model_with_two_units(api)
        assert env["dossier"]["dossier_state"] == "CERTIFIED"

        _reject_at_final_inspection(api, env)

        dossier = _read_dossier(api, env["dossier"]["id"])
        assert dossier["dossier_state"] == "RESURVEY_REQUIRED"
        assert dossier["resurvey_reason"] == "YIELD_BREACH"
        assert dossier["resurvey_count"] == 1

    def test_02_both_review_verdicts_are_kept_for_the_audit_trail(self, api):
        """The energy and water dimensions stay APPROVED through the pushback.

        PRD: "Both `energy_review_state` and `water_review_state` are deliberately **left at `APPROVED`** rather than reset, because the original review verdicts remain part of the audit trail; only the resurvey submission described in §3.3 resets them to `PENDING`."
        Design: Difficulty/transitive_cascade/qa_reject_scrap_yield_breach_suspends_model_and_holds_siblings
        """
        env = _released_model_with_two_units(api)

        _reject_at_final_inspection(api, env)

        dossier = _read_dossier(api, env["dossier"]["id"])
        assert dossier["energy_review_state"] == "APPROVED"
        assert dossier["water_review_state"] == "APPROVED"

    def test_03_the_dossier_rebate_entitlement_collapses_to_zero(self, api):
        """The 70000-cent award earned at certification is emptied by the pushback.

        PRD: "Hop four reaches the compliance record: the model's dossier sitting in `CERTIFIED` moves from `CERTIFIED` to `RESURVEY_REQUIRED`, with `resurvey_reason` set to `YIELD_BREACH`, `resurvey_count` increased by 1, `qualified_program_codes` emptied, `rebate_amount_cents` reset to 0, and the dossier's `version` advanced by 1."
        Design: Difficulty/transitive_cascade/qa_reject_scrap_yield_breach_suspends_model_and_holds_siblings
        """
        env = _released_model_with_two_units(api)
        a.assert_cents(env["dossier"]["rebate_amount_cents"], QUALIFIED_REBATE_CENTS)
        assert env["dossier"]["qualified_program_codes"] == [PROGRAM_CODE]

        _reject_at_final_inspection(api, env)

        dossier = _read_dossier(api, env["dossier"]["id"])
        assert dossier["qualified_program_codes"] == []
        a.assert_cents(dossier["rebate_amount_cents"], 0)


class TestReleasedModelSuspendedForResurvey:
    def test_01_the_released_model_falls_to_suspended(self, api):
        """A released model whose yield breached is suspended pending resurvey.

        PRD: "Hop five reaches the model itself. A model in `RELEASED` moves from `RELEASED` to `SUSPENDED`, and a model that was certified but never released moves from `CERTIFIED` to `SUSPENDED`; both paths set `suspended_reason` to `YIELD_RESURVEY`, empty `rebate_program_codes`, reset the model's `rebate_amount_cents` to 0, and advance the model's `version` by 1."
        Design: Difficulty/transitive_cascade/qa_reject_scrap_yield_breach_suspends_model_and_holds_siblings
        """
        env = _released_model_with_two_units(api)
        assert env["model"]["certification_state"] == "RELEASED"

        _reject_at_final_inspection(api, env)

        model = _read_model(api, env["model"]["id"])
        assert model["certification_state"] == "SUSPENDED"
        assert model["suspended_reason"] == "YIELD_RESURVEY"

    def test_02_the_model_rebate_snapshot_is_emptied(self, api):
        """The model loses the program codes and the 70000 cents it carried.

        PRD: "Hop five reaches the model itself. A model in `RELEASED` moves from `RELEASED` to `SUSPENDED`, and a model that was certified but never released moves from `CERTIFIED` to `SUSPENDED`; both paths set `suspended_reason` to `YIELD_RESURVEY`, empty `rebate_program_codes`, reset the model's `rebate_amount_cents` to 0, and advance the model's `version` by 1."
        Design: Difficulty/transitive_cascade/qa_reject_scrap_yield_breach_suspends_model_and_holds_siblings
        """
        env = _released_model_with_two_units(api)
        a.assert_cents(env["model"]["rebate_amount_cents"], QUALIFIED_REBATE_CENTS)
        assert env["model"]["rebate_program_codes"] == [PROGRAM_CODE]

        _reject_at_final_inspection(api, env)

        model = _read_model(api, env["model"]["id"])
        assert model["rebate_program_codes"] == []
        a.assert_cents(model["rebate_amount_cents"], 0)


class TestInFlightSiblingUnitGoesOnQualityHold:
    def test_01_the_sibling_on_the_floor_is_parked_on_quality_hold(self, api):
        """The model's other in-production unit stops where it stands.

        PRD: "Hop six reaches production in flight: every build order of that model whose `build_state` is `ON_FLOOR`, `DRUM_DONE`, `BEARINGS_DONE` or `QA_HOLD` moves to `QUALITY_HOLD`, processed in `created_at` ascending order, each advancing its own `version` by 1, and the model's `quality_hold_unit_count` is recomputed once hop six has finished."
        Design: Difficulty/transitive_cascade/qa_reject_scrap_yield_breach_suspends_model_and_holds_siblings
        """
        env = _released_model_with_two_units(api)
        a.assert_build_state(env["sibling"], "ON_FLOOR")

        _reject_at_final_inspection(api, env)

        sibling = _read_build(api, env["sibling"]["id"])
        a.assert_build_state(sibling, "QUALITY_HOLD")

    def test_02_the_yield_cascade_raises_no_integrity_flag(self, api):
        """The held sibling is suspect by certification, not by its labour.

        PRD: "Only the certification-revocation cascade of §3.4 sets `integrity_hold` to true, and only that flag drives claims into `FULFILLMENT_BLOCKED` with `block_reason` of `BUILD_INTEGRITY_HOLD`."
        Design: Difficulty/transitive_cascade/qa_reject_scrap_yield_breach_suspends_model_and_holds_siblings
        """
        env = _released_model_with_two_units(api)

        _reject_at_final_inspection(api, env)

        sibling = _read_build(api, env["sibling"]["id"])
        assert sibling["integrity_hold"] is False

    def test_03_the_model_quality_hold_counter_is_recomputed(self, api):
        """Exactly one unit of the model now sits on quality hold.

        PRD: "Hop six reaches production in flight: every build order of that model whose `build_state` is `ON_FLOOR`, `DRUM_DONE`, `BEARINGS_DONE` or `QA_HOLD` moves to `QUALITY_HOLD`, processed in `created_at` ascending order, each advancing its own `version` by 1, and the model's `quality_hold_unit_count` is recomputed once hop six has finished."
        Design: Difficulty/transitive_cascade/qa_reject_scrap_yield_breach_suspends_model_and_holds_siblings
        """
        env = _released_model_with_two_units(api)

        _reject_at_final_inspection(api, env)

        model = _read_model(api, env["model"]["id"])
        assert model["quality_hold_unit_count"] == 1

    def test_04_the_rebate_program_itself_is_untouched(self, api):
        """The utility program stays ACTIVE; only the clock ever retires one.

        PRD: "Retirement is driven by the logical clock rather than by any operator action."
        Design: Difficulty/transitive_cascade/qa_reject_scrap_yield_breach_suspends_model_and_holds_siblings
        """
        env = _released_model_with_two_units(api)

        _reject_at_final_inspection(api, env)

        program = validate_success(
            api.get_rebate_program(env["program"]["id"], COMPLIANCE_OFFICER),
            expected_status=200,
        )
        assert program["program_state"] == "ACTIVE"
