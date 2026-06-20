"""Breeding records: cyclic lifecycle, gestation, calving cascade, invalid transitions."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_herd,
    create_animal,
    create_breeding_record,
    transition_breeding,
    ApiErrorId,
    TEST_USERS,
)

HM = TEST_USERS["herd_manager_headers"]
VET = TEST_USERS["veterinarian_headers"]


class TestBreedingCycle:
    def test_confirmed_pregnant_returns_to_open(self, api):
        """PRD §3.5: "From either `BRED` or `CONFIRMED_PREGNANT`, a herd manager may
        return the record to `OPEN` (modelling a failed service or a loss), which clears
        `expected_calving_on`."

        Design: Difficulty/non_linear_state_machine/breeding_cycle_confirmed_back_to_open
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        dam = create_animal(herd["id"], sex="FEMALE", birth_date="2022-01-01",
                            birth_weight_kg=42.0)
        record = create_breeding_record(dam["id"], bred_on="2026-02-01")
        transition_breeding(record["id"], "BRED", headers=HM)
        transition_breeding(record["id"], "CONFIRMED_PREGNANT", headers=VET)
        back = transition_breeding(record["id"], "OPEN", headers=HM)
        assert back["status"] == "OPEN"

    def test_rebreed_after_loss_recomputes_expected_calving(self, api):
        """PRD §3.5: "A herd manager moves an `OPEN` record to `BRED`, which requires
        the dam to be `ACTIVE` and `FEMALE` and `bred_on` to not be in the future, and
        which computes the record's `expected_calving_on` as the service date plus the
        species gestation length."
        PRD §3.5: "cattle gestate 283 days".

        Design: Difficulty/non_linear_state_machine/breeding_cycle_confirmed_back_to_open
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        dam = create_animal(herd["id"], sex="FEMALE", birth_date="2022-01-01",
                            birth_weight_kg=42.0)
        record = create_breeding_record(dam["id"], bred_on="2026-02-01")
        transition_breeding(record["id"], "BRED", headers=HM)
        transition_breeding(record["id"], "CONFIRMED_PREGNANT", headers=VET)
        transition_breeding(record["id"], "OPEN", headers=HM)
        rebred = transition_breeding(record["id"], "BRED", headers=HM)
        assert rebred["status"] == "BRED"
        assert rebred["expected_calving_on"][:10] == "2026-11-11", (
            f"2026-02-01 + 283 days == 2026-11-11, got {rebred['expected_calving_on']}"
        )


class TestGestationConstants:
    def test_goat_gestation_150_days(self, api):
        """PRD §3.5: "cattle gestate 283 days, sheep 147 days, and goats 150 days. Thus
        `expected_calving_on` is the `bred_on` date advanced by 283, 147, or 150 whole
        days according to whether the herd's `species` is `CATTLE`, `SHEEP`, or `GOAT`."

        Design: Corner/calculations/expected_calving_goat_gestation
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="GOAT")
        dam = create_animal(herd["id"], sex="FEMALE", birth_date="2023-01-01",
                            birth_weight_kg=4.0)
        record = create_breeding_record(dam["id"], bred_on="2026-02-01")
        bred = transition_breeding(record["id"], "BRED", headers=HM)
        assert bred["expected_calving_on"][:10] == "2026-07-01", (
            f"2026-02-01 + 150 days == 2026-07-01, got {bred['expected_calving_on']}"
        )


class TestCalvingCascade:
    def test_calving_creates_visible_calf(self, api):
        """PRD §3.5: "The transition records `calved_on`, then creates a new animal —
        the calf — in the same herd, with its `dam_animal_id` set to this dam, its
        `life_status` `ACTIVE`, and its `birth_date` equal to `calved_on`; the calf's
        identifier is recorded back onto the breeding record as `calf_animal_id`."
        PRD §3.5: "Creating the calf increments the herd's `active_animal_count` by one".

        Design: Corner/consistency_model/immediate_consistency_calf_visible_in_response
        """
        set_clock("2026-12-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        dam = create_animal(herd["id"], sex="FEMALE", birth_date="2022-01-01",
                            birth_weight_kg=42.0)
        record = create_breeding_record(dam["id"], bred_on="2026-02-01")
        transition_breeding(record["id"], "BRED", headers=HM)
        transition_breeding(record["id"], "CONFIRMED_PREGNANT", headers=VET)
        calved = validate_success(
            api.transition_breeding_record(
                record["id"],
                {"to_status": "CALVED", "calved_on": "2026-11-15",
                 "calf_ear_tag": "M011", "calf_birth_weight_kg": 39.0,
                 "calf_sex": "FEMALE"},
                HM,
            )
        )
        assert calved["status"] == "CALVED"
        calf_id = calved["calf_animal_id"]
        assert calf_id is not None

        calf = validate_success(api.get_animal(calf_id, HM))
        assert calf["life_status"] == "ACTIVE"
        assert calf["dam_animal_id"] == dam["id"]

        herd_after = validate_success(api.get_herd(herd["id"], HM))
        assert herd_after["active_animal_count"] == 2


class TestBreedingInvalidTransitions:
    def test_confirm_pregnant_from_open_rejected(self, api):
        """PRD §3.5: "A veterinarian — and only a veterinarian — confirms pregnancy by
        moving a `BRED` record to `CONFIRMED_PREGNANT`."
        PRD §3.5: "Each transition is legal only from the state the scaffold permits;
        an out-of-order transition is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/confirm_pregnant_from_open_returns_invalid_state
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        dam = create_animal(herd["id"], sex="FEMALE", birth_date="2022-01-01",
                            birth_weight_kg=42.0)
        record = create_breeding_record(dam["id"], bred_on="2026-02-01")
        resp = api.transition_breeding_record(
            record["id"], {"to_status": "CONFIRMED_PREGNANT"}, VET
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
