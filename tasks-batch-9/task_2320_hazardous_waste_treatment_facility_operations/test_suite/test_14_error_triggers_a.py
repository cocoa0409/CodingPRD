"""Rejection paths of the hazardous waste TSDF API: schema closure at the gate,
acceptance criteria re-checked at the dock, the lifetime sampling ceiling, the
permit's method list, residue held back by a failed land disposal restriction,
inspection currency at treatment start, and the three repair-order deadlines.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import TEST_USERS, assert_cents, assert_mass, assert_one_decimal
from test_helpers import fixtures
from test_helpers.factories import (
    batch_operation_payload,
    custody_payload,
    facility_payload,
    manifest_line_payload,
    receipt_line,
    receive_payload,
    repair_action_payload,
    sample_payload,
    treatment_batch_payload,
)


class TestFacilityRegistrationSchemaClosure:
    def test_facility_registration_rejects_an_unknown_body_field(self, api):
        """A speculative key in the registration body fails the schema pass, and no
        facility is written for it.

        "Required fields are present, types are correct, enumerated values are in range, numeric constraints hold, `window_end` is strictly later than `window_start`, each supplied `accepted_quantity_kg` is no greater than the line's `received_quantity_kg`, and unknown fields are rejected — `ERR_INVALID_REQUEST` (400)."

        Design: Corner/errors/facility_create_with_extra_field_rejected
        """
        fixtures.set_clock("2026-08-01T00:00:00Z")

        res = api.create_facility(
            facility_payload(required_assurance_cents=1), TEST_USERS["admin"]
        )

        validate_error(res, "ERR_INVALID_REQUEST")

        _, meta = validate_paginated(api.list_facilities(TEST_USERS["admin"]))
        assert meta["total_count"] == 0, "a refused registration must leave no facility behind"


class TestManifestReceiptAcceptanceCriteria:
    def test_receipt_is_refused_when_a_line_s_profile_was_suspended_after_shipment(self, api):
        """The shipment left the generator under an APPROVED profile, but the profile
        was pulled out of service before the truck reached the dock.

        "It also requires the facility's permit to stand, and requires every received line's waste profile to still be `APPROVED` — a profile that was suspended, allowed to lapse or rejected between shipment and arrival fails the acceptance criteria and the receipt is refused with `ERR_ACCEPTANCE_CRITERIA_FAILED`."

        Design: Corner/errors/receipt_of_a_line_whose_profile_was_suspended_after_shipment_rejected
        """
        fixtures.set_clock("2026-08-01T00:00:00Z")
        facility, _ = fixtures.create_funded_facility()
        generator = fixtures.create_generator()
        profile = fixtures.create_approved_profile(generator["id"], facility["id"])
        manifest = fixtures.create_manifest(
            generator["id"],
            facility["id"],
            lines=[manifest_line_payload(profile["id"], 1000.0, 4, False)],
        )
        fixtures.set_profile_status(profile["id"], "SUSPENDED", "CONSTITUENT_DRIFT")

        res = api.receive_manifest(
            manifest["id"],
            receive_payload([receipt_line(1, 1000.0, 4)]),
            TEST_USERS["clerk"],
        )

        validate_error(res, "ERR_ACCEPTANCE_CRITERIA_FAILED")

        held = fixtures.read_manifest(manifest["id"])
        assert held["status"] == "EN_ROUTE"
        assert held["arrived_at"] is None
        assert_mass(fixtures.read_facility(facility["id"])["received_mass_kg"], 0.0)

        # Reinstating the profile restores acceptance, so the same receipt now stands.
        fixtures.set_profile_status(profile["id"], "APPROVED")
        accepted = validate_success(
            api.receive_manifest(
                manifest["id"],
                receive_payload([receipt_line(1, 1000.0, 4)]),
                TEST_USERS["clerk"],
            )
        )
        assert accepted["status"] == "VERIFIED"


class TestVerificationSamplingCeiling:
    def test_fourth_sample_after_a_recertification_resubmission_is_refused(self, api):
        """Two failures, a pass on the third run, a lapsed recertification and a
        resubmission leave the profile legitimately SUBMITTED, yet the lifetime
        attempt counter still bars a fourth laboratory run.

        "A sample may be recorded only while the profile is `SUBMITTED` and its `sample_attempt_count` is less than 3."

        Design: Corner/errors/fourth_sample_after_recertification_resubmit_rejected
        """
        fixtures.set_clock("2026-08-01T00:00:00Z")
        facility = fixtures.create_facility()
        generator = fixtures.create_generator()
        profile = fixtures.create_draft_profile(
            generator["id"], facility["id"], recertification_months=1
        )

        submitted = fixtures.submit_profile(profile["id"], generator["id"])
        first = fixtures.record_sample(
            profile["id"],
            submitted["version"],
            measured_constituent_ppm=20000.0,
            measured_flash_point_c=43.0,
            measured_ph=7.2,
        )
        assert first["result"] == "FAIL"
        after_first = fixtures.read_profile(profile["id"])
        assert after_first["status"] == "SAMPLE_FAILED"
        assert after_first["sample_attempt_count"] == 1

        resubmitted = fixtures.submit_profile(profile["id"], generator["id"])
        second = fixtures.record_sample(
            profile["id"],
            resubmitted["version"],
            sample_type="FULL",
            measured_constituent_ppm=20000.0,
            measured_flash_point_c=43.0,
            measured_ph=7.2,
        )
        assert second["result"] == "FAIL"
        after_second = fixtures.read_profile(profile["id"])
        assert after_second["status"] == "SAMPLE_FAILED"
        assert after_second["sample_attempt_count"] == 2

        resubmitted_again = fixtures.submit_profile(profile["id"], generator["id"])
        third = fixtures.record_sample(
            profile["id"],
            resubmitted_again["version"],
            sample_type="FULL",
            measured_constituent_ppm=12100.0,
            measured_flash_point_c=42.5,
            measured_ph=7.1,
        )
        assert third["result"] == "PASS"
        after_third = fixtures.read_profile(profile["id"])
        assert after_third["status"] == "SAMPLE_PASSED"
        assert after_third["sample_attempt_count"] == 3

        approved = fixtures.sign_profile_decision(profile["id"], "APPROVE", "INCINERATION")
        assert approved["recertification_due_at"].startswith("2026-09-01T00:00:00")

        fixtures.set_clock("2026-09-02T00:00:00Z")
        assert fixtures.read_profile(profile["id"])["status"] == "EXPIRED"

        recertifying = fixtures.submit_profile(profile["id"], generator["id"])
        assert recertifying["status"] == "SUBMITTED"
        assert recertifying["required_sample_type"] == "FULL"

        res = api.create_profile_sample(
            profile["id"],
            sample_payload(
                recertifying["version"],
                sample_type="FULL",
                measured_constituent_ppm=12100.0,
                measured_flash_point_c=42.5,
                measured_ph=7.1,
            ),
            TEST_USERS["chemist"],
        )

        validate_error(res, "ERR_SAMPLE_LIMIT_EXCEEDED")

        final = fixtures.read_profile(profile["id"])
        assert final["sample_attempt_count"] == 3
        assert final["status"] == "SUBMITTED"


class TestTreatmentSchedulingAgainstThePermit:
    def test_batch_requesting_a_method_the_permit_never_authorised_is_refused(self, api):
        """The drum is sealed, compliant and drawn from an approved profile, but the
        permit authorises incineration only, so neutralisation cannot be scheduled
        and nothing is staged or reserved.

        "The requested or approved treatment method appears in the facility's `permitted_methods` — `ERR_METHOD_NOT_PERMITTED` (403). Applies to the profile decision, treatment batch creation and treatment batch operations."

        Design: Corner/errors/batch_on_an_unpermitted_method_rejected
        """
        scenario = fixtures.setup_sealed_container(
            facility_overrides={"permitted_methods": ["INCINERATION"]}
        )

        res = api.create_treatment_batch(
            treatment_batch_payload(
                scenario.facility["id"],
                scenario.unit["id"],
                [scenario.container["id"]],
                treatment_method="NEUTRALIZATION",
            ),
            TEST_USERS["operator"],
        )

        validate_error(res, "ERR_METHOD_NOT_PERMITTED")

        container = fixtures.read_container(scenario.container["id"])
        assert container["custody_state"] == "SEALED"
        assert container["treatment_batch_id"] is None
        assert_mass(fixtures.read_unit(scenario.unit["id"])["reserved_kg"], 0.0)
        assert_cents(
            fixtures.read_facility(scenario.facility["id"])["active_treatment_liability_cents"],
            0,
            "active_treatment_liability_cents",
        )

        # The permitted method schedules the identical run.
        scheduled = validate_success(
            api.create_treatment_batch(
                treatment_batch_payload(
                    scenario.facility["id"],
                    scenario.unit["id"],
                    [scenario.container["id"]],
                    treatment_method="INCINERATION",
                ),
                TEST_USERS["operator"],
            ),
            expected_status=201,
        )
        assert scheduled["status"] == "PLANNED"


class TestResidueReleaseAfterFailedLandDisposalRestriction:
    def test_emptying_a_drum_from_an_ldr_failed_batch_is_refused(self, api):
        """A lead residue at 900.0 ppm misses the 750 ppm treatment standard, and the
        drum's release is then refused by the land disposal restriction rule rather
        than by the custody state gate.

        "For the two concentration families, `ldr_standard_ppm` is set to the universal treatment standard — 750 ppm for `D008_LEAD` and 560 ppm for `F001_SOLVENTS` — and the result is a pass when `verification_sample_ppm` is at or below that standard and a failure otherwise, so a lead residue at exactly 750.0 ppm passes while one at 750.1 ppm fails."
        "`LDR_FAILED` is deliberately admitted by that state check so that the second precondition, not the state check, is the rule that reports a residue failing its land disposal restriction standard: the batch's `ldr_result` must not be `FAIL`, and when it is, the refusal is `ERR_LDR_STANDARD_NOT_MET`."

        Design: Corner/errors/emptying_a_container_from_an_ldr_failed_batch_rejected
        """
        scenario = fixtures.setup_treated_batch(
            residue_mass_kg=150.0,
            residue_constituent_ppm=900.0,
            treatment_method="STABILIZATION",
            approved_treatment_method="STABILIZATION",
            facility_overrides={"permitted_methods": ["STABILIZATION"]},
            profile_overrides={
                "waste_codes": ["D008"],
                "ldr_subcategory": "D008_LEAD",
                "requested_treatment_method": "STABILIZATION",
            },
            container_overrides={"label_waste_codes": ["D008"], "label_hazard_class": "6.1"},
        )
        failed = fixtures.verify_batch_ldr(scenario.batch["id"], 900.0)
        assert_one_decimal(failed["ldr_standard_ppm"], 750.0, "ldr_standard_ppm")
        assert failed["ldr_result"] == "FAIL"
        assert failed["status"] == "LDR_FAILED"

        res = api.set_container_custody_state(
            scenario.container["id"], custody_payload("EMPTIED"), TEST_USERS["operator"]
        )

        validate_error(res, "ERR_LDR_STANDARD_NOT_MET")

        assert fixtures.read_container(scenario.container["id"])["custody_state"] == "STAGED"
        facility = fixtures.read_facility(scenario.facility["id"])
        assert_mass(facility["treated_residue_kg"], 150.0, "treated_residue_kg")
        assert_mass(facility["destroyed_mass_kg"], 50.0, "destroyed_mass_kg")


class TestTreatmentStartInspectionCurrency:
    def test_start_on_a_unit_past_its_inspection_interval_is_refused(self, api):
        """Eight days after its last inspection a weekly-inspected container area is
        overdue while still reading OPEN, so the start reports the inspection rule.

        "`inspection_overdue` is true when the current clock instant is **strictly** later than `last_inspection_at` advanced by `inspection_frequency_days` days."
        "A unit whose `last_inspection_at` is older than its inspection interval therefore still reads posture `OPEN`, and a start attempt on it fails with the inspection error rather than the posture error."

        Design: Corner/errors/treatment_start_on_an_uninspected_unit_rejected
        """
        scenario = fixtures.setup_planned_batch(window_end="2026-08-09T12:00:00Z")
        fixtures.set_clock("2026-08-09T00:00:00Z")

        overdue_unit = fixtures.read_unit(scenario.unit["id"])
        assert overdue_unit["inspection_overdue"] is True
        assert overdue_unit["posture"] == "OPEN"

        res = api.batch_operation(
            scenario.batch["id"], batch_operation_payload("START"), TEST_USERS["operator"]
        )

        validate_error(res, "ERR_INSPECTION_OVERDUE")
        assert fixtures.read_batch(scenario.batch["id"])["status"] == "PLANNED"

        # A fresh inspection stamps last_inspection_at and clears the lateness.
        fixtures.record_inspection(
            scenario.unit["id"], inspection_type="WEEKLY_CONTAINER_AREA", finding_code="NONE"
        )
        started = validate_success(
            api.batch_operation(
                scenario.batch["id"], batch_operation_payload("START"), TEST_USERS["operator"]
            )
        )
        assert started["status"] == "IN_TREATMENT"


class TestEmissionRepairDeadlines:
    def test_first_repair_attempt_after_its_five_day_deadline_is_refused(self, api):
        """A 300.0 ppm reading on a LEVEL_2 tank opens an order due for its first
        attempt on 2026-08-06; an attempt on 2026-08-07 is refused outright.

        "Two deadlines are stamped at the same time: `first_attempt_due_at` at 5 days after detection and `repair_due_at` at 15 days after detection."
        "`FIRST_ATTEMPT`, performed by a `TreatmentOperator`, advances the order from `OPEN` to `FIRST_ATTEMPTED`; it requires the current clock instant to be at or before `first_attempt_due_at`, failing which it is refused with `ERR_REPAIR_ATTEMPT_LATE`, and it increments `attempt_count` and records `last_monitored_ppm` from `monitored_ppm`."

        Design: Corner/errors/first_repair_attempt_after_its_deadline_rejected
        """
        scenario = fixtures.setup_tank_with_repair_order(measured_organic_vapor_ppm=300.0)
        order = scenario.order
        assert order is not None, "a 300.0 ppm reading on a LEVEL_2 tank must open a repair order"
        assert_one_decimal(order["leak_definition_ppm"], 250.0, "leak_definition_ppm")
        assert order["leak_type"] == "TANK_LEAK"
        assert order["detected_at"].startswith("2026-08-01T00:00:00")
        assert order["first_attempt_due_at"].startswith("2026-08-06T00:00:00")
        assert order["repair_due_at"].startswith("2026-08-16T00:00:00")

        fixtures.set_clock("2026-08-07T00:00:00Z")

        res = api.repair_order_action(
            order["id"],
            repair_action_payload("FIRST_ATTEMPT", monitored_ppm=260.0),
            TEST_USERS["operator"],
        )

        validate_error(res, "ERR_REPAIR_ATTEMPT_LATE")

        untouched = fixtures.read_repair_order(order["id"])
        assert untouched["status"] == "OPEN"
        assert untouched["attempt_count"] == 0

    def test_closure_at_exactly_the_leak_definition_is_refused_while_just_below_closes(self, api):
        """250.0 ppm on a LEVEL_2 tank both opens the order and refuses to close it;
        249.9 ppm closes it and returns the tank to an open posture.

        "Closing an order, also a `ComplianceManager` act, requires `monitored_ppm` to be **strictly** below `leak_definition_ppm`; a reading at or above the leak definition is refused with `ERR_LEAK_PERSISTS`."
        "A reading exactly at the leak definition therefore both opens an order and refuses to close it, while a `LEVEL_2` unit reading 249.9 ppm closes one."

        Design: Corner/errors/closing_a_repair_order_exactly_at_the_leak_definition_rejected
        """
        scenario = fixtures.setup_tank_with_repair_order(measured_organic_vapor_ppm=250.0)
        order = scenario.order
        assert order is not None, "detection is inclusive, so 250.0 ppm opens an order"

        fixtures.set_clock("2026-08-02T00:00:00Z")
        fixtures.repair_action(order["id"], "FIRST_ATTEMPT", monitored_ppm=255.0)

        res = api.repair_order_action(
            order["id"],
            repair_action_payload("CLOSE", monitored_ppm=250.0),
            TEST_USERS["compliance_manager"],
        )

        validate_error(res, "ERR_LEAK_PERSISTS")

        still_open = fixtures.read_repair_order(order["id"])
        assert still_open["status"] == "FIRST_ATTEMPTED"
        assert still_open["attempt_count"] == 1

        closed = validate_success(
            api.repair_order_action(
                order["id"],
                repair_action_payload("CLOSE", monitored_ppm=249.9),
                TEST_USERS["compliance_manager"],
            )
        )
        assert closed["status"] == "REPAIRED"
        assert_one_decimal(closed["last_monitored_ppm"], 249.9, "last_monitored_ppm")
        assert closed["is_overdue"] is False
        assert fixtures.read_unit(scenario.unit["id"])["posture"] == "OPEN"

    def test_delay_of_repair_beyond_the_180_day_ceiling_is_refused(self, api):
        """The justification is one of the two allowed codes, so the refusal isolates
        the date ceiling: 2027-06-01 is past 180 days from the 2026-08-01 detection,
        while 2027-01-28 sits exactly on it.

        "A **delay of repair**, granted by a `ComplianceManager`, is defined from both `OPEN` and `FIRST_ATTEMPTED`, and both paths carry the same two preconditions: `justification_code` must be either `UNIT_SHUTDOWN_REQUIRED` or `PART_UNAVAILABLE`, and the requested `delayed_due_at` must be no later than 180 days after `detected_at`."
        "Either violation is refused with `ERR_DELAY_JUSTIFICATION_INVALID`."

        Design: Corner/errors/delay_of_repair_beyond_the_180_day_ceiling_rejected
        """
        scenario = fixtures.setup_tank_with_repair_order(measured_organic_vapor_ppm=300.0)
        order = scenario.order
        assert order is not None, "a leaking tank must carry an open repair order"

        res = api.repair_order_action(
            order["id"],
            repair_action_payload(
                "DELAY",
                justification_code="PART_UNAVAILABLE",
                delayed_due_at="2027-06-01T00:00:00Z",
            ),
            TEST_USERS["compliance_manager"],
        )

        validate_error(res, "ERR_DELAY_JUSTIFICATION_INVALID")

        unchanged = fixtures.read_repair_order(order["id"])
        assert unchanged["status"] == "OPEN"
        assert unchanged["delayed_due_at"] is None
        assert unchanged["justification_code"] == "NONE"

        # A deadline landing exactly on the 180-day ceiling is granted.
        delayed = validate_success(
            api.repair_order_action(
                order["id"],
                repair_action_payload(
                    "DELAY",
                    justification_code="PART_UNAVAILABLE",
                    delayed_due_at="2027-01-28T00:00:00Z",
                ),
                TEST_USERS["compliance_manager"],
            )
        )
        assert delayed["status"] == "DELAYED"
