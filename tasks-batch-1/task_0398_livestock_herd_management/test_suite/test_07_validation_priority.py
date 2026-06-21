"""Validation precedence pairs and pedigree referential checks."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_herd,
    create_animal,
    create_weighed_animal,
    create_sale_lot,
    add_ticket,
    create_drug,
    treat_animal,
    ApiErrorId,
    TEST_USERS,
)

HM = TEST_USERS["herd_manager_headers"]
VET = TEST_USERS["veterinarian_headers"]
CLERK = TEST_USERS["sale_clerk_headers"]


class TestStateBeatsSafety:
    def test_sell_withdrawn_lot_returns_invalid_state_not_safety(self, api):
        """PRD §3.10: "A sell or withdraw requested on a lot that is not `OPEN` fails
        the state check with `ERR_INVALID_STATE`."
        PRD §2.5: "then the state-transition legality check (`ERR_INVALID_STATE`) for
        state-changing endpoints. The remaining domain-specific business rules described
        throughout §2 and §3 are evaluated after these foundational layers".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_sell_withheld_nonopen_lot
        """
        set_clock("2026-05-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_weighed_animal(herd["id"], 500.0, weighed_at="2026-04-20")
        lot = create_sale_lot(herd["id"], channel="AUCTION", commission_pct=0.05)
        add_ticket(lot["id"], animal["id"], 500.0, lot["version"])
        validate_success(api.withdraw_lot(lot["id"], CLERK))
        # Now drive the ticketed animal WITHHELD via an IM-28 treatment.
        drug = create_drug(route_withdrawals={"INJECTION_IM": 28})
        treat_animal(animal["id"], drug["id"], route="INJECTION_IM",
                     first_dose_on="2026-05-01", last_dose_on="2026-05-01")
        # Selling the WITHDRAWN lot: the state check wins over the safety check.
        resp = api.sell_lot(lot["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_withdrawn_lot_is_terminal_for_sell(self, api):
        """PRD §3.10: "A sell or withdraw requested on a lot that is not `OPEN` fails
        the state check with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_sell_withheld_nonopen_lot
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_weighed_animal(herd["id"], 500.0, weighed_at="2026-03-20")
        lot = create_sale_lot(herd["id"], channel="AUCTION", commission_pct=0.05)
        add_ticket(lot["id"], animal["id"], 500.0, lot["version"])
        validate_success(api.withdraw_lot(lot["id"], CLERK))
        resp = api.sell_lot(lot["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestExistenceBeatsPedigree:
    def test_nonexistent_dam_returns_not_found_not_pedigree(self, api):
        """PRD §2.5: "before any business rule is evaluated, every referenced resource
        named in the path and in the body's foreign-key fields must exist, or the
        request fails with `ERR_NOT_FOUND`."
        PRD §2.5: "then referenced-resource existence (`ERR_NOT_FOUND`), then
        request-shape validation of required fields, types, enum domains, and numeric
        ranges (`ERR_INVALID_REQUEST`)".

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_pedigree_on_create_animal
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        female_sire = create_animal(herd["id"], sex="FEMALE", birth_date="2022-01-01")
        resp = api.create_animal(
            {"herd_id": herd["id"], "ear_tag": "J002", "sex": "STEER",
             "birth_date": "2026-01-01", "birth_weight_kg": 38.0,
             "dam_animal_id": "00000000-0000-4000-8000-000000000000",
             "sire_animal_id": female_sire["id"]},
            HM,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_existing_dam_wrong_sex_alone_returns_pedigree(self, api):
        """PRD §3.2: "a `dam_animal_id` must reference an animal whose `sex` is
        `FEMALE`, and a `sire_animal_id` must reference an animal whose `sex` is `MALE`.
        A pedigree link that violates either rule is rejected with
        `ERR_INVALID_PEDIGREE`."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_pedigree_on_create_animal
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        steer_dam = create_animal(herd["id"], sex="STEER", birth_date="2024-01-01")
        resp = api.create_animal(
            {"herd_id": herd["id"], "ear_tag": "X011", "sex": "STEER",
             "birth_date": "2026-01-01", "birth_weight_kg": 38.0,
             "dam_animal_id": steer_dam["id"]},
            HM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PEDIGREE.value)


class TestPedigreeReferential:
    def test_male_dam_reference_rejected(self, api):
        """PRD §3.2: "a `dam_animal_id` must reference an animal whose `sex` is
        `FEMALE` ... A pedigree link that violates either rule is rejected with
        `ERR_INVALID_PEDIGREE`."

        Design: Corner/errors/error_invalid_pedigree_triggerable
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        steer_dam = create_animal(herd["id"], sex="STEER", birth_date="2024-01-01")
        resp = api.create_animal(
            {"herd_id": herd["id"], "ear_tag": "X011", "sex": "STEER",
             "birth_date": "2026-01-01", "birth_weight_kg": 38.0,
             "dam_animal_id": steer_dam["id"]},
            HM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PEDIGREE.value)
