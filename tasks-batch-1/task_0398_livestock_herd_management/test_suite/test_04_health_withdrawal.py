"""Health treatments: clearance dates, withhold cycle, route/dose validation, cull gate."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_herd,
    create_animal,
    create_weighed_animal,
    create_drug,
    treat_animal,
    setup_withheld_animal,
    ApiErrorId,
    TEST_USERS,
)

HM = TEST_USERS["herd_manager_headers"]
VET = TEST_USERS["veterinarian_headers"]


class TestParallelClearanceDimension:
    def test_treatment_drives_animal_withheld(self, api):
        """PRD §3.6: "otherwise the treatment is created `WITHDRAWAL_ACTIVE` and drives
        the animal's residue dimension toward `WITHHELD`."
        PRD §3.6: "If the animal was `CLEAR`, it transitions to `WITHHELD`".

        Design: Difficulty/non_linear_state_machine/animal_parallel_dimensions_clearance_cycle
        """
        set_clock("2026-05-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_animal(herd["id"], sex="STEER", birth_date="2024-01-01")
        drug = create_drug(route_withdrawals={"INJECTION_IM": 28, "ORAL": 14})
        treat_animal(animal["id"], drug["id"], route="INJECTION_IM",
                     first_dose_on="2026-05-01", last_dose_on="2026-05-01")
        after = validate_success(api.get_animal(animal["id"], HM))
        assert after["life_status"] == "ACTIVE"
        assert after["meat_clearance_status"] == "WITHHELD"

    def test_clearance_lifts_on_clock_advance_life_status_unchanged(self, api):
        """PRD §3.6: "The withhold lifts only by clock advance: when the clock is set
        to a date on or after the animal's `meat_clear_on` and no remaining treatment
        for that animal still has a clearance date beyond the clock, the residue
        dimension returns to `CLEAR` and `meat_clear_on` is cleared to null".

        Design: Difficulty/non_linear_state_machine/animal_parallel_dimensions_clearance_cycle
        """
        set_clock("2026-05-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_animal(herd["id"], sex="STEER", birth_date="2024-01-01")
        drug = create_drug(route_withdrawals={"INJECTION_IM": 28, "ORAL": 14})
        treat_animal(animal["id"], drug["id"], route="INJECTION_IM",
                     first_dose_on="2026-05-01", last_dose_on="2026-05-01")
        set_clock("2026-05-29T00:00:00Z")
        after = validate_success(api.get_animal(animal["id"], HM))
        assert after["life_status"] == "ACTIVE"
        assert after["meat_clearance_status"] == "CLEAR"


class TestWithdrawalClearanceDate:
    def test_oral_route_clearance_date(self, api):
        """PRD §3.6: "The treatment's `clearance_date` is computed as the `last_dose_on`
        date advanced by the number of withdrawal days the route maps to in
        `route_withdrawals`".

        Design: Corner/calculations/withdrawal_clearance_oral_route_case
        """
        set_clock("2026-05-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_animal(herd["id"], sex="STEER", birth_date="2024-01-01")
        drug = create_drug(route_withdrawals={"ORAL": 14, "INJECTION_IM": 28},
                          category="ANTIPARASITIC")
        ht = validate_success(
            api.create_health_treatment(
                {"animal_id": animal["id"], "drug_product_id": drug["id"],
                 "route": "ORAL", "first_dose_on": "2026-05-01",
                 "last_dose_on": "2026-05-01"},
                VET,
            ),
            expected_status=201,
        )
        assert ht["clearance_date"][:10] == "2026-05-15", (
            f"2026-05-01 + 14 days == 2026-05-15, got {ht['clearance_date']}"
        )
        assert ht["status"] == "WITHDRAWAL_ACTIVE"

    def test_multi_dose_counts_from_last_dose(self, api):
        """PRD §3.6: "so clearance always counts from the last dose, which is what makes
        a multi-dose course clear later than a single dose given on the first date."

        Design: Corner/calculations/withdrawal_multi_dose_counts_from_last_dose
        """
        set_clock("2026-05-10T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_animal(herd["id"], sex="STEER", birth_date="2024-01-01")
        drug = create_drug(route_withdrawals={"INJECTION_IM": 28})
        ht = validate_success(
            api.create_health_treatment(
                {"animal_id": animal["id"], "drug_product_id": drug["id"],
                 "route": "INJECTION_IM", "dose_count": 2,
                 "first_dose_on": "2026-05-01", "last_dose_on": "2026-05-10"},
                VET,
            ),
            expected_status=201,
        )
        assert ht["clearance_date"][:10] == "2026-06-07", (
            f"last_dose 2026-05-10 + 28 days == 2026-06-07, got {ht['clearance_date']}"
        )


class TestTreatmentValidation:
    def test_route_not_in_drug_map_rejected(self, api):
        """PRD §3.6: "The `route` must be one of the permitted route values and,
        crucially, must be a key present in that drug product's `route_withdrawals` map;
        a route that is not a key in the map is rejected with `ERR_ROUTE_NOT_PERMITTED`."

        Design: Corner/validations/route_not_in_drug_map_returns_422
        """
        set_clock("2026-05-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_animal(herd["id"], sex="STEER", birth_date="2024-01-01")
        drug = create_drug(route_withdrawals={"INJECTION_IM": 28})
        resp = api.create_health_treatment(
            {"animal_id": animal["id"], "drug_product_id": drug["id"],
             "route": "ORAL", "first_dose_on": "2026-05-01",
             "last_dose_on": "2026-05-01"},
            VET,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_PERMITTED.value)

    def test_dose_dates_reversed_rejected(self, api):
        """PRD §3.6: "A treatment whose `last_dose_on` precedes `first_dose_on`, or
        whose dose dates lie in the future, is rejected with `ERR_DOSE_DATES_INVALID`."

        Design: Corner/validations/dose_dates_reversed_returns_422
        """
        set_clock("2026-05-10T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_animal(herd["id"], sex="STEER", birth_date="2024-01-01")
        drug = create_drug(route_withdrawals={"INJECTION_IM": 28})
        resp = api.create_health_treatment(
            {"animal_id": animal["id"], "drug_product_id": drug["id"],
             "route": "INJECTION_IM", "dose_count": 2,
             "first_dose_on": "2026-05-10", "last_dose_on": "2026-05-01"},
            VET,
        )
        validate_error(resp, ApiErrorId.ERR_DOSE_DATES_INVALID.value)


class TestResidueSafetyGateOnCull:
    def test_cull_withheld_animal_rejected(self, api):
        """PRD §3.3: "Culling is a terminal removal driven by a `to_status` of `CULLED`
        on an `ACTIVE` animal. It requires that the animal be `ACTIVE` and — as a
        residue-safety gate — that its `meat_clearance_status` be `CLEAR`; a withheld
        animal cannot be culled and is rejected with `ERR_WITHDRAWAL_NOT_CLEARED`."

        Design: Corner/state_machines/cull_withheld_animal_returns_withdrawal_not_cleared
        """
        set_clock("2026-05-01T00:00:00Z")
        _, animal, _, _ = setup_withheld_animal()
        resp = api.set_life_status(animal["id"], {"to_status": "CULLED"}, HM)
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_NOT_CLEARED.value)
