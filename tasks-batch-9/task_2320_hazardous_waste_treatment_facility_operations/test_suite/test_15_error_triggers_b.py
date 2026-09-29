"""Refusals raised by the facility's own physical, fiscal and permit rules.

Each test drives one documented rejection through the API, then re-reads the
rows the request would have touched to prove the refusal wrote nothing, and —
where the rule has a compensating arm — repeats the call with the one figure
that satisfies the rule.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import TEST_USERS, assert_cents, assert_mass, assert_ratio, assert_unit_state
from test_helpers.api_client import api_client
from test_helpers.factories import (
    complete_batch_payload,
    container_payload,
    manifest_line_payload,
    manifest_payload,
    permit_renewal_payload,
    storage_unit_payload,
    tank_unit_payload,
)
from test_helpers.fixtures import (
    create_draft_profile,
    create_facility,
    create_generator,
    read_facility,
    read_finding,
    read_generator,
    read_line,
    read_profile,
    read_unit,
    set_clock,
    set_finding_status,
    setup_planned_batch,
    setup_received_manifest,
    setup_snc_finding,
    start_batch,
)


class TestPermitRenewalCorrectiveActionCurrency:
    def test_permit_renewal_is_refused_while_an_snc_corrective_action_is_overdue(self):
        """A renewal application filed against a facility carrying a significant
        non-complier finding whose corrective action deadline has passed is refused,
        and the filing succeeds the moment the facility reports the action complete.

        "Both paths carry the same two preconditions: the facility must have no significant-non-complier finding whose corrective action is overdue, otherwise the filing is refused with `ERR_CORRECTIVE_ACTION_OVERDUE`; and the facility's assurance shortfall must be zero, otherwise the filing is refused with `ERR_FINANCIAL_ASSURANCE_SHORTFALL`."
        "`is_overdue` is derived: it is true when the finding's `status` is `OPEN` or `REOPENED` and the current clock instant is strictly later than `corrective_action_due_at`."
        "Filing an `SNC` finding raises the facility's `open_snc_finding_count` and therefore its `corrective_action_reserve_cents` by 5,000,000 cents."
        "`required_assurance_cents` is the sum of `closure_cost_estimate_cents`, the facility's input `post_closure_cost_cents`, `corrective_action_reserve_cents`, and `active_treatment_liability_cents` — the last being the sum of `estimated_treatment_liability_cents` across the facility's batches that are `PLANNED` or `IN_TREATMENT`."
        "Filing moves the facility from `ACTIVE` to `RENEWAL_PENDING`, or from `EXPIRED` to `RENEWAL_PENDING`, and stamps `renewal_requested_at` with the current clock instant while storing the requested expiry."

        Design: Corner/errors/permit_renewal_with_an_overdue_snc_corrective_action_rejected
        """
        scenario = setup_snc_finding(corrective_action_due_at="2026-08-10T00:00:00Z")
        set_clock("2026-08-11T00:00:00Z")

        finding = read_finding(scenario.finding["id"])
        assert finding["is_overdue"] is True

        facility = read_facility(scenario.facility["id"])
        assert_cents(
            facility["corrective_action_reserve_cents"], 5_000_000, "corrective_action_reserve_cents"
        )
        # 25,000,000 base at TIER_1 -> 26,250,000 estimate, plus 8,000,000 of post
        # closure care and the 5,000,000 reserve the open finding holds.
        assert_cents(facility["required_assurance_cents"], 39_250_000, "required_assurance_cents")

        refused = api_client.request_permit_renewal(
            scenario.facility["id"],
            permit_renewal_payload("2029-06-30T00:00:00Z"),
            TEST_USERS["compliance_manager"],
        )
        validate_error(refused, "ERR_CORRECTIVE_ACTION_OVERDUE")

        unchanged = read_facility(scenario.facility["id"])
        assert unchanged["permit_status"] == "ACTIVE"
        assert unchanged["renewal_requested_at"] is None

        set_finding_status(
            scenario.finding["id"], "RESPONDED", corrective_action_completed_on="2026-08-11"
        )
        accepted = api_client.request_permit_renewal(
            scenario.facility["id"],
            permit_renewal_payload("2029-06-30T00:00:00Z"),
            TEST_USERS["compliance_manager"],
        )
        filed = validate_success(accepted, expected_status=200)
        assert filed["permit_status"] == "RENEWAL_PENDING"


class TestStorageUnitRegistrationConstraints:
    def test_duplicate_unit_code_is_refused_inside_one_facility_but_free_at_another(self):
        """A permit designation may be reused only across facility boundaries: the
        second CA-01 at the same facility is refused while CA-01 at a different
        facility registers normally.

        "`manifest_tracking_number` is unique across all manifests, `epa_id` is unique across facilities and separately unique across generators, and `unit_code` is unique within a `facility_id` — `ERR_DUPLICATE_MANIFEST_NUMBER` (409)."

        Design: Corner/errors/second_storage_unit_with_a_duplicate_unit_code_rejected
        """
        set_clock()
        facility_a = create_facility()
        facility_b = create_facility(
            name="Gulf Coast TSDF", epa_id="TXD000333444", permit_number="TX-HW-0092"
        )
        validate_success(
            api_client.create_storage_unit(
                storage_unit_payload(facility_a["id"], unit_code="CA-01"), TEST_USERS["admin"]
            ),
            expected_status=201,
        )

        duplicate = api_client.create_storage_unit(
            storage_unit_payload(
                facility_a["id"],
                unit_code="CA-01",
                permitted_capacity_kg=15000.0,
                aisle_width_cm=150.0,
                aisle_free_container_capacity=6,
                allowed_compatibility_classes=["ACID"],
                air_emission_control_level="LEVEL_1",
                containment_volume_l=4000.0,
            ),
            TEST_USERS["admin"],
        )
        validate_error(duplicate, "ERR_DUPLICATE_MANIFEST_NUMBER")

        at_other_facility = api_client.create_storage_unit(
            storage_unit_payload(
                facility_b["id"],
                unit_code="CA-01",
                permitted_capacity_kg=15000.0,
                aisle_width_cm=150.0,
                aisle_free_container_capacity=6,
                allowed_compatibility_classes=["ACID"],
                air_emission_control_level="LEVEL_1",
                containment_volume_l=4000.0,
            ),
            TEST_USERS["admin"],
        )
        validate_success(at_other_facility, expected_status=201)

        _, meta_a = validate_paginated(
            api_client.list_storage_units(
                TEST_USERS["admin"], params={"facility_id": facility_a["id"]}
            )
        )
        assert meta_a["total_count"] == 1
        _, meta_b = validate_paginated(
            api_client.list_storage_units(
                TEST_USERS["admin"], params={"facility_id": facility_b["id"]}
            )
        )
        assert meta_b["total_count"] == 1

    def test_tank_system_registered_with_a_weekly_inspection_interval_is_refused(self):
        """Seven days between inspections is legal for a container area and illegal
        for a tank system, which must be walked daily.

        "Inspection frequency is capped by unit type: a `CONTAINER_AREA` and a `TEN_DAY_TRANSFER` may be inspected no less often than every 7 days, and a `TANK_SYSTEM` no less often than daily, so a frequency above those ceilings is refused with `ERR_INSPECTION_FREQUENCY_INVALID`."

        Design: Corner/errors/tank_unit_with_a_weekly_inspection_interval_rejected
        """
        set_clock()
        facility = create_facility()

        weekly_tank = api_client.create_storage_unit(
            tank_unit_payload(facility["id"], inspection_frequency_days=7), TEST_USERS["admin"]
        )
        validate_error(weekly_tank, "ERR_INSPECTION_FREQUENCY_INVALID")

        weekly_container_area = api_client.create_storage_unit(
            storage_unit_payload(
                facility["id"], unit_code="CA-01", inspection_frequency_days=7
            ),
            TEST_USERS["admin"],
        )
        container_area = validate_success(weekly_container_area, expected_status=201)
        assert container_area["inspection_frequency_days"] == 7

        _, meta = validate_paginated(
            api_client.list_storage_units(
                TEST_USERS["admin"], params={"facility_id": facility["id"]}
            )
        )
        assert meta["total_count"] == 1

        daily_tank = api_client.create_storage_unit(
            tank_unit_payload(facility["id"], inspection_frequency_days=1), TEST_USERS["admin"]
        )
        tank = validate_success(daily_tank, expected_status=201)
        assert tank["inspection_frequency_days"] == 1


class TestTreatmentCompletionMassBalance:
    def test_completion_reporting_more_residue_than_input_is_refused(self):
        """Treatment may destroy mass but never create it, so a 250.0 kg residue
        reported against a 200.0 kg input is refused and the facility's residue
        and destruction totals stay at zero.

        "Two preconditions apply: `residue_mass_kg` may not exceed `input_mass_kg`, failing which `ERR_MASS_BALANCE_INVALID` is returned; and `residue_flash_point_c` must be present when the batch's land-disposal-restriction family is `D001_IGNITABLE`, failing which the request is invalid."
        "Reported `residue_mass_kg` is no greater than the batch's `input_mass_kg` at completion — `ERR_MASS_BALANCE_INVALID` (422)."
        "`mass_ledger_kg` is the sum of those five destinations, and it must equal `received_mass_kg` after every operation, with no rounding drift."
        "On the facility ledger, `treated_residue_kg` gains the reported `residue_mass_kg` and `destroyed_mass_kg` gains the input mass less the residue mass, so `mass_ledger_kg` is unchanged."

        Design: Corner/errors/completion_with_residue_heavier_than_the_input_rejected
        """
        scenario = setup_planned_batch(net_weight_kg=200.0)
        batch = start_batch(scenario.batch["id"])
        assert_mass(batch["input_mass_kg"], 200.0, "input_mass_kg")

        refused = api_client.batch_operation(
            scenario.batch["id"],
            complete_batch_payload(250.0, 400.0),
            TEST_USERS["operator"],
        )
        validate_error(refused, "ERR_MASS_BALANCE_INVALID")

        still_running = validate_success(
            api_client.get_treatment_batch(scenario.batch["id"], TEST_USERS["operator"])
        )
        assert still_running["status"] == "IN_TREATMENT"
        assert_mass(still_running["residue_mass_kg"], 0.0, "residue_mass_kg")

        facility = read_facility(scenario.facility["id"])
        assert_mass(facility["treated_residue_kg"], 0.0, "treated_residue_kg")
        assert_mass(facility["destroyed_mass_kg"], 0.0, "destroyed_mass_kg")
        assert_mass(facility["mass_ledger_kg"], 1000.0, "mass_ledger_kg")

        # A residue exactly equal to the input is admitted: the ceiling is inclusive.
        completed = validate_success(
            api_client.batch_operation(
                scenario.batch["id"],
                complete_batch_payload(200.0, 400.0),
                TEST_USERS["operator"],
            )
        )
        assert completed["status"] == "TREATED"
        after = read_facility(scenario.facility["id"])
        assert_mass(after["treated_residue_kg"], 200.0, "treated_residue_kg")
        assert_mass(after["destroyed_mass_kg"], 0.0, "destroyed_mass_kg")


class TestContainerPlacementPhysicalRules:
    def test_container_labelled_with_a_waste_code_the_profile_does_not_carry_is_refused(self):
        """A drum labelled D002 against a D001 profile never reaches the unit, so no
        occupancy, allocation or held mass is recorded.

        "A container's `label_waste_codes` equals its profile's `waste_codes` as a set — `ERR_LABEL_CODE_MISMATCH` (422) — and `label_hazard_class` is non-empty with `label_accumulation_start_marked` true before the container may be sealed — `ERR_LABEL_INCOMPLETE` (422)."
        "`container_count` is the number of containers in the unit whose custody is `FILLING`, `SEALED` or `STAGED`."
        "**Mass allocation** requires the container's `net_weight_kg` to be no greater than what remains on its receipt line, that remainder being the line's `accepted_quantity_kg` less its `allocated_container_mass_kg`, where `allocated_container_mass_kg` is the sum of `net_weight_kg` over the line's containers whose custody is anything other than `VOIDED`."

        Design: Corner/errors/container_labelled_with_the_wrong_waste_code_rejected
        """
        scenario = setup_received_manifest(profile_overrides={"waste_codes": ["D001"]})

        mislabelled = api_client.create_container(
            container_payload(
                scenario.line["id"],
                scenario.unit["id"],
                net_weight_kg=200.0,
                capacity_kg=250.0,
                label_waste_codes=["D002"],
            ),
            TEST_USERS["clerk"],
        )
        validate_error(mislabelled, "ERR_LABEL_CODE_MISMATCH")

        assert_unit_state(
            read_unit(scenario.unit["id"]), container_count=0, stored_kg=0.0
        )
        assert_mass(
            read_line(scenario.manifest["id"], 1)["allocated_container_mass_kg"],
            0.0,
            "allocated_container_mass_kg",
        )
        assert_mass(read_facility(scenario.facility["id"])["held_mass_kg"], 0.0, "held_mass_kg")

        corrected = api_client.create_container(
            container_payload(
                scenario.line["id"],
                scenario.unit["id"],
                net_weight_kg=200.0,
                capacity_kg=250.0,
                label_waste_codes=["D001"],
            ),
            TEST_USERS["clerk"],
        )
        validate_success(corrected, expected_status=201)

    def test_container_filled_past_the_headspace_ceiling_is_refused(self):
        """195.0 kg in a 200.0 kg drum is a well-formed request refused for want of
        headspace, while 190.0 kg lands exactly on the 95 percent ceiling and is
        accepted with a fill ratio of 0.9500.

        "A container's `net_weight_kg` is no greater than 95 percent of its `capacity_kg` — `ERR_CONTAINER_OVERFILLED` (422)."
        "The **headspace rule** requires `net_weight_kg` to be no greater than 95 percent of `capacity_kg`, and the container's `fill_ratio` — `net_weight_kg` divided by `capacity_kg`, carried to 4 decimals — is exposed so the margin is visible."
        "`stored_kg` is the sum of `net_weight_kg` over those same containers, to 3 decimals."

        Design: Corner/errors/container_filled_past_the_headspace_ceiling_rejected
        """
        scenario = setup_received_manifest()

        overfilled = api_client.create_container(
            container_payload(
                scenario.line["id"],
                scenario.unit["id"],
                net_weight_kg=195.0,
                capacity_kg=200.0,
            ),
            TEST_USERS["clerk"],
        )
        validate_error(overfilled, "ERR_CONTAINER_OVERFILLED")

        at_the_ceiling = api_client.create_container(
            container_payload(
                scenario.line["id"],
                scenario.unit["id"],
                net_weight_kg=190.0,
                capacity_kg=200.0,
            ),
            TEST_USERS["clerk"],
        )
        placed = validate_success(at_the_ceiling, expected_status=201)
        assert_ratio(placed["fill_ratio"], 0.95, "fill_ratio")

        assert_unit_state(read_unit(scenario.unit["id"]), container_count=1, stored_kg=190.0)
        assert_mass(
            read_line(scenario.manifest["id"], 1)["allocated_container_mass_kg"],
            190.0,
            "allocated_container_mass_kg",
        )


class TestManifestProfileStanding:
    def test_manifest_line_under_a_profile_still_in_draft_is_refused(self):
        """A stream the laboratory never approved cannot be manifested, and the
        refusal names the approval rule rather than the recertification rule one
        rung below it.

        "The waste profile behind a manifest line or a container has a `status` of either `APPROVED` or `EXPIRED`; a profile that never reached approval, or that has been suspended or rejected, is refused here — `ERR_PROFILE_NOT_APPROVED` (409)."
        "A merely lapsed recertification is deliberately not this rule's business: such a profile carries `EXPIRED` and is reported one rung lower, so that `ERR_PROFILE_EXPIRED` remains reachable instead of being masked."
        "A generator opens with `status` of `ACTIVE`, with `suspension_reason_code` null, with all four charge balances — `open_charge_cents`, `settled_charge_cents`, `voided_charge_cents` and `charge_adjustment_cents` — at zero, and with both reliability scores at 100, because no manifest of that generator has closed yet."

        Design: Corner/errors/manifest_line_referencing_a_draft_profile_rejected
        """
        set_clock()
        facility = create_facility()
        generator = create_generator()
        profile = create_draft_profile(generator["id"], facility["id"])
        assert read_profile(profile["id"])["status"] == "DRAFT"

        refused = api_client.create_manifest(
            manifest_payload(
                generator["id"],
                facility["id"],
                lines=[manifest_line_payload(profile["id"], 1000.0, 4, False)],
            ),
            TEST_USERS["clerk"],
        )
        error = validate_error(refused, "ERR_PROFILE_NOT_APPROVED")
        assert error["error_id"] != "ERR_PROFILE_EXPIRED"

        _, meta = validate_paginated(
            api_client.list_manifests(
                TEST_USERS["clerk"], params={"generator_id": generator["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert_cents(
            read_generator(generator["id"])["open_charge_cents"], 0, "open_charge_cents"
        )
