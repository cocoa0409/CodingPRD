"""Scheduling a second treatment run against windows already booked.

One unit whose decontamination buffer stretches across a class change, and one
facility whose permit caps simultaneous runs across two separate units.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import TEST_USERS, api_client, assert_cents, assert_mass, fixtures
from test_helpers.factories import manifest_line_payload, receipt_line, treatment_batch_payload


def _unit_running_organic_solvent_with_an_acid_drum_waiting() -> fixtures.Scenario:
    """One unit permitted for organic solvent and acid waste: a planned run on the
    solvent drum from 00:00 to 12:00 on 2026-08-02, and a sealed acid drum in the
    same unit ready for a run of its own."""
    fixtures.set_clock()
    facility, instrument = fixtures.create_funded_facility()
    generator = fixtures.create_generator()
    unit = fixtures.create_storage_unit(
        facility["id"],
        allowed_compatibility_classes=["ORGANIC_SOLVENT", "ACID"],
        aisle_free_container_capacity=20,
    )
    solvent_profile = fixtures.create_approved_profile(generator["id"], facility["id"])
    acid_profile = fixtures.create_approved_profile(
        generator["id"],
        facility["id"],
        profile_overrides={
            "waste_codes": ["D002"],
            "physical_form": "SLUDGE",
            "compatibility_class": "ACID",
            "requested_treatment_method": "NEUTRALIZATION",
        },
        approved_treatment_method="NEUTRALIZATION",
    )
    manifest = fixtures.create_manifest(
        generator["id"],
        facility["id"],
        lines=[
            manifest_line_payload(solvent_profile["id"], 400.0, 1, False),
            manifest_line_payload(acid_profile["id"], 400.0, 1, False),
        ],
    )
    fixtures.receive_manifest(
        manifest["id"], [receipt_line(1, 400.0, 1), receipt_line(2, 400.0, 1)]
    )
    lines = fixtures.read_lines(manifest["id"])
    solvent_drum = fixtures.place_container(
        lines[0]["id"], unit["id"], container_type="TOTE", capacity_kg=400.0, net_weight_kg=200.0
    )
    fixtures.seal_container(solvent_drum["id"])
    acid_drum = fixtures.place_container(
        lines[1]["id"],
        unit["id"],
        container_type="TOTE",
        capacity_kg=400.0,
        net_weight_kg=300.0,
        label_waste_codes=["D002"],
        label_hazard_class="8",
    )
    fixtures.seal_container(acid_drum["id"])
    solvent_run = fixtures.create_batch(
        facility["id"],
        unit["id"],
        [solvent_drum["id"]],
        treatment_method="INCINERATION",
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T12:00:00Z",
    )
    return fixtures.Scenario(
        facility=fixtures.read_facility(facility["id"]),
        instrument=instrument,
        generator=generator,
        unit=fixtures.read_unit(unit["id"]),
        solvent_drum=fixtures.read_container(solvent_drum["id"]),
        acid_drum=fixtures.read_container(acid_drum["id"]),
        solvent_run=solvent_run,
    )


def _schedule_acid_run_three_hours_after(scenario: fixtures.Scenario):
    """Ask for the acid run from 15:00 to 20:00, three hours after the solvent run
    ends."""
    return api_client.create_treatment_batch(
        treatment_batch_payload(
            scenario.facility["id"],
            scenario.unit["id"],
            [scenario.acid_drum["id"]],
            treatment_method="NEUTRALIZATION",
            window_start="2026-08-02T15:00:00Z",
            window_end="2026-08-02T20:00:00Z",
        ),
        TEST_USERS["operator"],
    )


def _facility_capped_at_one_run_with_two_units() -> fixtures.Scenario:
    """A facility whose permit allows one simultaneous run: unit CA-01 carries a
    planned run from 00:00 to 12:00 on 2026-08-02, and unit CA-02 holds a sealed
    drum of its own."""
    scenario = fixtures.setup_sealed_container(
        facility_overrides={"max_concurrent_treatment_batches": 1},
        declared_quantity_kg=1250.5,
        declared_container_count=5,
        net_weight_kg=200.0,
    )
    second_unit = fixtures.create_storage_unit(scenario.facility["id"], unit_code="CA-02")
    second_drum = fixtures.place_container(
        scenario.line["id"], second_unit["id"], net_weight_kg=200.0
    )
    fixtures.seal_container(second_drum["id"])
    scenario.first_run = fixtures.create_batch(
        scenario.facility["id"],
        scenario.unit["id"],
        [scenario.container["id"]],
        treatment_method="INCINERATION",
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T12:00:00Z",
    )
    scenario.second_unit = fixtures.read_unit(second_unit["id"])
    scenario.second_drum = fixtures.read_container(second_drum["id"])
    scenario.facility = fixtures.read_facility(scenario.facility["id"])
    return scenario


def _schedule_touching_run_in_the_second_unit(scenario: fixtures.Scenario):
    """Ask for a run in the second unit starting exactly when the first run ends."""
    return api_client.create_treatment_batch(
        treatment_batch_payload(
            scenario.facility["id"],
            scenario.second_unit["id"],
            [scenario.second_drum["id"]],
            treatment_method="INCINERATION",
            window_start="2026-08-02T12:00:00Z",
            window_end="2026-08-02T18:00:00Z",
        ),
        TEST_USERS["operator"],
    )


class TestDecontaminationBufferAcrossAClassChange:
    def test_run_three_hours_after_a_different_class_conflicts(self):
        """A run starting three hours after a run of another dominant class ends is
        still inside that run's four-hour decontamination buffer.

        PRD: "Each such batch's window is treated as half-open — its start instant is inside the window and its end instant is not — and it is extended by a four-hour decontamination buffer whenever that batch's `dominant_compatibility_class` differs from the candidate's, and by nothing at all when the two classes are the same."
        PRD: "A conflict exists when the candidate's `window_start` falls strictly before the existing batch's buffered end and the existing batch's `window_start` falls strictly before the candidate's `window_end`."
        PRD: "Any conflict is `ERR_TREATMENT_WINDOW_CONFLICT`."
        PRD: "Two runs of the same dominant class that merely touch — the candidate starting exactly when the existing one ends — do not conflict, since the interval is half-open and no buffer applies; two runs of different dominant classes starting three hours after the previous one ended do conflict, because the four-hour buffer still covers that instant."

        Design: Difficulty/resource_temporal_overlap/unit_batch_class_change_buffer_overlap_rejected
        """
        scenario = _unit_running_organic_solvent_with_an_acid_drum_waiting()
        assert scenario.solvent_run["dominant_compatibility_class"] == "ORGANIC_SOLVENT"

        validate_error(
            _schedule_acid_run_three_hours_after(scenario), "ERR_TREATMENT_WINDOW_CONFLICT"
        )

    def test_conflicting_request_stages_nothing_and_reserves_nothing(self):
        """The refused request leaves the acid drum sealed and unassigned, and the
        unit's reserved mass carries only the first run.

        PRD: "Staging is not a caller-driven custody request at all: it happens as a side effect of batch scheduling, advancing each listed container from `SEALED` to `STAGED`, setting its `treatment_batch_id` to the new batch, and requiring the container to be `COMPLIANT` — a container in any other condition makes the batch creation an invalid state."
        PRD: "Creation stages each listed container, raises the unit's `reserved_kg` by the frozen input mass, and raises the facility's `active_treatment_liability_cents` and `required_assurance_cents` by the frozen liability."
        PRD: "`reserved_kg` is the sum of `input_mass_kg` over the batches on the unit whose `status` is `PLANNED` or `IN_TREATMENT`, to 3 decimals."

        Design: Difficulty/resource_temporal_overlap/unit_batch_class_change_buffer_overlap_rejected
        """
        scenario = _unit_running_organic_solvent_with_an_acid_drum_waiting()
        validate_error(
            _schedule_acid_run_three_hours_after(scenario), "ERR_TREATMENT_WINDOW_CONFLICT"
        )

        acid_drum = fixtures.read_container(scenario.acid_drum["id"])
        assert acid_drum["custody_state"] == "SEALED"
        assert acid_drum["treatment_batch_id"] is None
        assert fixtures.read_batch(scenario.solvent_run["id"])["status"] == "PLANNED"
        unit = fixtures.read_unit(scenario.unit["id"])
        assert_mass(unit["reserved_kg"], 200.0, "reserved_kg")


class TestFacilityConcurrencyOverTouchingWindows:
    def test_touching_window_in_another_unit_exhausts_the_permit_cap(self):
        """A run in a second unit that starts exactly when the first ends counts
        against a cap of one, and reports the facility cap rather than the
        unit-level conflict.

        PRD: "Count every batch of the same `facility_id` in the same five non-terminal statuses whose `window_start` is at or before the candidate's `window_end` and whose `window_end` is at or after the candidate's `window_start`."
        PRD: "When that count reaches or exceeds the facility's `max_concurrent_treatment_batches`, the scheduling is refused with `ERR_FACILITY_CONCURRENCY_EXCEEDED`."
        PRD: "Because this check closes both endpoints, a candidate in a *different* unit that merely touches an existing batch's end instant still counts against a facility cap of one — the unit-level check does not apply across units, but the facility-level count does."

        Design: Difficulty/resource_temporal_overlap/facility_closed_interval_concurrency_touching_windows_counts
        """
        scenario = _facility_capped_at_one_run_with_two_units()
        assert scenario.facility["max_concurrent_treatment_batches"] == 1

        refusal = validate_error(
            _schedule_touching_run_in_the_second_unit(scenario),
            "ERR_FACILITY_CONCURRENCY_EXCEEDED",
        )
        assert refusal["error_id"] != "ERR_TREATMENT_WINDOW_CONFLICT"

    def test_refused_second_run_leaves_the_first_run_and_both_units_as_they_were(self):
        """Nothing is staged in the second unit and the facility still carries only
        the first run's 44,000-cent treatment liability.

        PRD: "Staging is not a caller-driven custody request at all: it happens as a side effect of batch scheduling, advancing each listed container from `SEALED` to `STAGED`, setting its `treatment_batch_id` to the new batch, and requiring the container to be `COMPLIANT` — a container in any other condition makes the batch creation an invalid state."
        PRD: "Three figures are frozen at creation and never recomputed thereafter: `input_mass_kg`, the sum of `net_weight_kg` across the staged containers to 3 decimals; `dominant_compatibility_class`, the compatibility class of the staged container with the greatest `net_weight_kg`, with the lowest container `created_at` breaking a tie; and `estimated_treatment_liability_cents`, `input_mass_kg` multiplied by 220 cents per kilogram and rounded half up to whole cents."
        PRD: "`required_assurance_cents` is the sum of `closure_cost_estimate_cents`, the facility's input `post_closure_cost_cents`, `corrective_action_reserve_cents`, and `active_treatment_liability_cents` — the last being the sum of `estimated_treatment_liability_cents` across the facility's batches that are `PLANNED` or `IN_TREATMENT`."

        Design: Difficulty/resource_temporal_overlap/facility_closed_interval_concurrency_touching_windows_counts
        """
        scenario = _facility_capped_at_one_run_with_two_units()
        validate_error(
            _schedule_touching_run_in_the_second_unit(scenario),
            "ERR_FACILITY_CONCURRENCY_EXCEEDED",
        )

        assert fixtures.read_batch(scenario.first_run["id"])["status"] == "PLANNED"
        second_drum = fixtures.read_container(scenario.second_drum["id"])
        assert second_drum["custody_state"] == "SEALED"
        assert second_drum["treatment_batch_id"] is None
        second_unit = fixtures.read_unit(scenario.second_unit["id"])
        assert_mass(second_unit["reserved_kg"], 0.0, "reserved_kg")
        facility = fixtures.read_facility(scenario.facility["id"])
        assert_cents(
            facility["active_treatment_liability_cents"],
            44_000,
            "active_treatment_liability_cents",
        )
