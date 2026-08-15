"""Soiled intake reconciliation, the dispute/reweigh/resolve loop, and the wash
plant: dosing, sanitization validation, release, and segregation of duties
(PRD 3.4, 3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_batch,
    assert_intake,
    assert_pool,
    create_batch,
    create_formula,
    intake_event,
    make_plant_operator_headers,
    read_batch,
    read_pool,
    record_sanitization,
    setup_batch_in_washing,
    setup_batch_validating,
    setup_completed_stop_with_intake,
    setup_loaded_batch,
    start_wash,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers.fixtures import OPERATOR


class TestIntakeDisputeLoop:
    def test_intake_reweigh_loop_recomputes_reconciliation(self, api):
        """PRD 3.4: "Reweighing a `DISPUTED` intake with a fresh `scale_weight_g`
        overwrites the weight, recomputes `expected_weight_g`, `variance_pct`, and
        `verified_count` from the new reading, and lands back in `RECONCILED` when the
        new variance is at most 10.00 percent — otherwise it stays `DISPUTED`, and
        reweighing may repeat."

        Design: Corner/state_machines/intake_reweigh_loop_recomputes_reconciliation
        """
        ctx = setup_completed_stop_with_intake(clean_items=80, scale_weight_g=8801)
        intake = ctx["intake"]
        assert intake["status"] == "DISPUTED"
        assert float(intake["variance_pct"]) == pytest.approx(10.01, abs=0.001)

        reweighed = intake_event(intake["id"], "REWEIGH", scale_weight_g=8000)
        assert_intake(reweighed)
        assert reweighed["status"] == "RECONCILED", (
            "an on-target reweigh lands the intake back in RECONCILED"
        )
        assert float(reweighed["variance_pct"]) == pytest.approx(0.00, abs=0.001)
        assert reweighed["verified_count"] == 80, "COUNT_BASIS verified count is the curbside count"

    def test_resolve_disputed_intake_accept_weight_pins_count(self, api):
        """PRD 3.4: "Resolution closes the loop: resolving a `DISPUTED` intake takes
        a `resolution` of `ACCEPT_COUNT` or `ACCEPT_WEIGHT` and moves it to the
        terminal `RESOLVED` state, pinning `verified_count` to the stop's
        `clean_items_delivered` under `ACCEPT_COUNT` or to the weight-derived figure
        under `ACCEPT_WEIGHT`, and recording the choice in the intake's `resolution`
        field."

        Design: Corner/state_machines/resolve_disputed_intake_accept_weight_pins_count
        """
        ctx = setup_completed_stop_with_intake(clean_items=80, scale_weight_g=8801)
        intake = ctx["intake"]
        assert intake["status"] == "DISPUTED"

        resolved = intake_event(intake["id"], "RESOLVE", resolution="ACCEPT_WEIGHT")
        assert_intake(resolved)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution"] == "ACCEPT_WEIGHT"
        assert resolved["verified_count"] == 88, (
            f"ACCEPT_WEIGHT pins round_half_up(8801 / 100) = 88, got "
            f"{resolved['verified_count']}"
        )


class TestWashLoad:
    def test_load_disputed_intake_rejected(self, api):
        """PRD 3.5: "Every referenced intake must be in `RECONCILED` or `RESOLVED` —
        a `DISPUTED` intake is rejected with `ERR_WEIGHT_VARIANCE_EXCEEDED` — and must
        not already be loaded into another batch (its `wash_batch_id` must be null,
        else `ERR_INVALID_STATE`)."

        Design: Corner/validations/load_disputed_intake_rejected
        """
        # 9000 g against an expected 8000 g is variance 12.50 -> DISPUTED.
        ctx = setup_completed_stop_with_intake(
            clean_items=80, scale_weight_g=9000, intake_soil="HEAVY"
        )
        intake = ctx["intake"]
        assert intake["status"] == "DISPUTED"
        assert float(intake["variance_pct"]) == pytest.approx(12.50, abs=0.001)

        formula = create_formula()
        batch = create_batch(formula["id"], "HEAVY", "HARD")
        response = _client.load_batch(
            batch["id"], {"soiled_intake_ids": [intake["id"]]}, OPERATOR
        )
        validate_error(response, ApiErrorId.ERR_WEIGHT_VARIANCE_EXCEEDED.value)

        after = read_batch(batch["id"])
        assert after["status"] == "RECEIVING"
        assert after["total_load_g"] == 0, "a rejected load leaves the batch empty"


class TestWashDosing:
    def test_dosing_clamp_at_max_boundary(self, api):
        """PRD 3.5: "a 25000-gram load under the same conditions yields a raw
        1617.19 ml that rounds to 1617 and clamps to 900 ml of detergent, with 200 ml
        of sanitizer."

        Design: Corner/calculations/dosing_clamp_at_max_boundary
        """
        ctx = setup_loaded_batch(
            clean_items=250, scale_weight_g=25000, intake_soil="HEAVY",
            batch_soil="HEAVY", water_hardness="HARD",
        )
        batch = start_wash(ctx["batch"]["id"])
        assert_batch(batch)
        assert batch["total_load_g"] == 25000
        assert batch["dosed_detergent_ml"] == 900, (
            f"raw 1617.19 ml rounds to 1617 and clamps to MAX 900, got "
            f"{batch['dosed_detergent_ml']}"
        )
        assert batch["dosed_sanitizer_ml"] == 200, (
            f"sanitizer is never clamped: 8 ml/kg x 25 kg = 200, got "
            f"{batch['dosed_sanitizer_ml']}"
        )


class TestSanitizationValidation:
    def test_sanitization_threshold_boundaries(self, api):
        """PRD 3.5: "The batch passes when all three hold: the peak temperature
        reached at least `min_temp_celsius`, the dwell lasted at least
        `min_dwell_seconds`, and the chlorine reading sits between `chlorine_ppm_min`
        and `chlorine_ppm_max`, both bounds inclusive."
        PRD 3.5: "against a formula of 71 degrees, 180 seconds, and a 50-to-200 ppm
        band, a reading of (71, 180, 50) passes, while (71, 179, 100), (70, 180, 100),
        and (71, 180, 201) all fail."

        Design: Corner/calculations/sanitization_threshold_boundaries
        """
        ctx = setup_batch_in_washing(
            batch_soil="NORMAL", water_hardness="MEDIUM"
        )
        batch_id = ctx["batch"]["id"]

        first = record_sanitization(batch_id, 71, 179, 100)
        assert first["validation_passed"] is False, "dwell 179 < 180 fails"

        rewash_1 = _client.batch_event(batch_id, {"event_type": "REWASH"}, OPERATOR)
        validate_success(rewash_1)

        second = record_sanitization(batch_id, 71, 180, 201)
        assert second["validation_passed"] is False, "ppm 201 > 200 fails"

        rewash_2 = _client.batch_event(batch_id, {"event_type": "REWASH"}, OPERATOR)
        validate_success(rewash_2)

        third = record_sanitization(batch_id, 71, 180, 50)
        assert third["validation_passed"] is True, (
            "(71, 180, 50) sits exactly on every inclusive bound and passes"
        )


class TestRelease:
    def test_wash_release_success_moves_pool_units(self, api):
        """PRD 3.5: "Release returns `verified_count` units per intake from
        `in_wash_units` to `on_hand_units` in each intake's size pool and moves the
        batch to the terminal `RELEASED` state."

        Design: Corner/state_machines/wash_release_success_moves_pool_units
        """
        ctx = setup_batch_validating(
            clean_items=80, scale_weight_g=8000,
            batch_soil="NORMAL", water_hardness="MEDIUM",
        )
        batch = ctx["batch"]
        assert batch["validation_passed"] is True  # (71, 180, 100) passes

        released = validate_success(
            _client.batch_event(
                batch["id"], {"event_type": "RELEASE"},
                # op-2 validated; the starter was op-1, so duties are segregated.
                make_plant_operator_headers("op-2"),
            )
        )
        assert released["status"] == "RELEASED"

        pool = read_pool(ctx["pool"]["id"])
        assert_pool(pool)
        assert pool["on_hand_units"] == 492, (
            f"412 on-hand after the kit issue + 80 released back = 492, got "
            f"{pool['on_hand_units']}"
        )
        assert pool["in_wash_units"] == 0
        assert pool["checked_out_units"] == 8, (
            "88 kitted units minus the 80 returned through the wash stay with the customer"
        )

    def test_release_same_operator_returns_segregation_error(self, api):
        """PRD 3.5: "Release is the most guarded transition in the plant, with three
        checks evaluated in order: `validation_passed` must be true
        (`ERR_SANITIZATION_NOT_VALIDATED`); segregation of duties requires
        `validated_by` to differ from `wash_started_by`
        (`ERR_SEGREGATION_OF_DUTIES`); and every loaded intake must still be
        `RECONCILED` or `RESOLVED` (`ERR_WEIGHT_VARIANCE_EXCEEDED`)."

        Design: Corner/validations/release_same_operator_returns_segregation_error
        """
        op1 = make_plant_operator_headers("op-1")
        ctx = setup_batch_validating(
            starter_headers=op1,
            validator_headers=op1,
            peak_temp_celsius=71,
            dwell_seconds=180,
            chlorine_ppm=100,
            batch_soil="NORMAL",
            water_hardness="MEDIUM",
        )
        batch = ctx["batch"]
        assert batch["validation_passed"] is True
        assert batch["wash_started_by"] == "op-1"
        assert batch["validated_by"] == "op-1"

        response = _client.batch_event(batch["id"], {"event_type": "RELEASE"}, op1)
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        after = read_batch(batch["id"])
        assert after["status"] == "VALIDATING", "a rejected RELEASE leaves the batch VALIDATING"
