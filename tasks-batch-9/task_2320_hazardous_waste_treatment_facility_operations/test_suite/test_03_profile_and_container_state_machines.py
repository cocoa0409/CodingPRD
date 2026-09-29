"""Waste profile verification cycles and the container's two independent dimensions.

The laboratory loop is not a straight line: a profile that fails verification goes
back to the generator, returns for another run, and is then judged under a tighter
tolerance set. A container likewise carries two dimensions that never move each
other — where the drum is, and what shape it is in.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_ratio,
    assert_unit_state,
    factories,
    fixtures,
)

DECLARED_CONSTITUENT_PPM = 12000.0


def _profile_resubmitted_after_two_failed_verifications() -> fixtures.Scenario:
    """A profile declared at 12000 ppm that has been round-tripped twice.

    The first run measures 15000 ppm — a 0.2500 deviation that breaches even the
    0.15 fingerprint allowance. The second run measures 13400 ppm, a 0.1167
    deviation that a fingerprint tolerance would have passed but the tightened
    0.10 allowance refuses. The profile is then resubmitted a third time and is
    waiting in SUBMITTED for the laboratory.
    """
    fixtures.set_clock()
    facility = fixtures.create_facility()
    generator = fixtures.create_generator()
    profile = fixtures.create_draft_profile(
        generator["id"],
        facility["id"],
        physical_form="BULK_LIQUID",
        declared_constituent_ppm=DECLARED_CONSTITUENT_PPM,
        declared_flash_point_c=42.0,
        declared_ph=7.0,
    )
    first_submission = fixtures.submit_profile(profile["id"], generator["id"])
    fixtures.record_sample(
        profile["id"], first_submission["version"], measured_constituent_ppm=15000.0
    )
    first_failure = fixtures.read_profile(profile["id"])

    second_submission = fixtures.submit_profile(
        profile["id"],
        generator["id"],
        payload={"revised_declared_constituent_ppm": DECLARED_CONSTITUENT_PPM},
    )
    fixtures.record_sample(
        profile["id"],
        second_submission["version"],
        sample_type="FULL",
        measured_constituent_ppm=13400.0,
    )
    second_failure = fixtures.read_profile(profile["id"])

    third_submission = fixtures.submit_profile(
        profile["id"],
        generator["id"],
        payload={"revised_declared_constituent_ppm": DECLARED_CONSTITUENT_PPM},
    )
    return fixtures.Scenario(
        facility=facility,
        generator=generator,
        profile=profile,
        first_submission=first_submission,
        first_failure=first_failure,
        second_failure=second_failure,
        resubmitted=third_submission,
    )


def _record_third_laboratory_run(scenario: fixtures.Scenario) -> dict:
    """The third run measures 13200 ppm: a deviation of exactly 0.1000."""
    return validate_success(
        api_client.create_profile_sample(
            scenario.profile["id"],
            factories.sample_payload(
                scenario.resubmitted["version"],
                sample_type="FULL",
                measured_constituent_ppm=13200.0,
                measured_flash_point_c=43.0,
                measured_ph=7.2,
            ),
            TEST_USERS["chemist"],
        ),
        expected_status=201,
    )


def _container_filling_in_an_open_container_area() -> fixtures.Scenario:
    """A 200.0 kg drum placed FILLING and COMPLIANT into an OPEN container area."""
    return fixtures.setup_container_in_storage(net_weight_kg=200.0)


class TestWasteProfileSampleFailureResubmitCycle:
    def test_third_laboratory_run_is_judged_under_the_tightened_tolerance(self):
        """The tolerance set is chosen by the profile's `required_sample_type`, and the choice actually made is copied onto the sample as `applied_tolerance_type` so that the decision is auditable after the fact.

        Under a `FULL` tolerance, those three allowances tighten to 0.10, 3.0 degrees Celsius and 0.5 respectively.
        `constituent_deviation_pct` is the absolute difference between `measured_constituent_ppm` and the profile's `declared_constituent_ppm`, divided by the declared concentration or by 1 when the declared concentration is smaller than 1, rounded half up to 4 decimals before any comparison.
        Every comparison is strictly greater than, so a deviation landing exactly on its allowance passes.
        If none breaches, the sample's `result` is `PASS` and `failure_reason_code` is `NONE`.

        Design: Difficulty/non_linear_state_machine/waste_profile_sample_failure_resubmit_cycle
        """
        scenario = _profile_resubmitted_after_two_failed_verifications()

        sample = _record_third_laboratory_run(scenario)

        assert sample["applied_tolerance_type"] == "FULL"
        assert_ratio(sample["constituent_deviation_pct"], 0.1000, "constituent_deviation_pct")
        assert sample["result"] == "PASS"
        assert sample["failure_reason_code"] == "NONE"

    def test_each_failed_verification_ratchets_the_profile_towards_a_full_run(self):
        """A failing sample that leaves the incremented attempt count below 3 moves the profile from `SUBMITTED` to `SAMPLE_FAILED` and forces `required_sample_type` to `FULL`.

        Recording a sample always increments the profile's `sample_attempt_count` by one, sets `latest_sample_result` from the sample's result, and advances the profile's `version`.
        Because the second clause looks at attempts already made, any resubmission after a failed sample escalates to `FULL` and stays there for the life of that profile.
        In all three cases the profile lands in `SUBMITTED` and `required_sample_type` is recomputed.
        A passing sample moves the profile from `SUBMITTED` to `SAMPLE_PASSED`.

        Design: Difficulty/non_linear_state_machine/waste_profile_sample_failure_resubmit_cycle
        """
        scenario = _profile_resubmitted_after_two_failed_verifications()

        assert scenario.first_failure["status"] == "SAMPLE_FAILED"
        assert scenario.first_failure["sample_attempt_count"] == 1
        assert scenario.first_failure["required_sample_type"] == "FULL"
        assert scenario.second_failure["status"] == "SAMPLE_FAILED"
        assert scenario.second_failure["sample_attempt_count"] == 2
        assert scenario.resubmitted["status"] == "SUBMITTED"
        assert scenario.resubmitted["required_sample_type"] == "FULL"

        _record_third_laboratory_run(scenario)

        profile = fixtures.read_profile(scenario.profile["id"])
        assert profile["status"] == "SAMPLE_PASSED"
        assert profile["sample_attempt_count"] == 3
        assert profile["required_sample_type"] == "FULL"
        assert profile["latest_sample_result"] == "PASS"


class TestContainerCustodyAndConditionDimensions:
    def test_sealing_a_deficient_drum_leaves_its_condition_where_it_stood(self):
        """A container can be `SEALED` and `CONDEMNED` at the same time, and a custody move never touches condition while a condition change never touches custody.

        From `COMPLIANT` to `DEFICIENT` — reachable by direct request, by an inspection whose `finding_code` is `LABEL_DEFICIENT` or `OVERFILL`, or by the profile suspension cascade — the container stores `last_finding_code`, its custody is untouched, the holding unit recomputes posture from `OPEN` to `RESTRICTED`, and, caused by that posture change, `PLANNED` batches on the unit move to `HELD` with `held_reason_code` of `UNIT_POSTURE`.
        Sealing a container advances it from `FILLING` to `SEALED` and is permitted only when `label_accumulation_start_marked` is true, failing which the request is refused with `ERR_LABEL_INCOMPLETE`; the move leaves `compliance_state` untouched, because the dimensions are independent.

        Design: Difficulty/non_linear_state_machine/container_parallel_custody_and_compliance_dimensions
        """
        scenario = _container_filling_in_an_open_container_area()
        assert scenario.container["custody_state"] == "FILLING"
        assert scenario.container["compliance_state"] == "COMPLIANT"

        deficient = validate_success(
            api_client.set_container_compliance_state(
                scenario.container["id"],
                factories.compliance_payload("DEFICIENT", "LABEL_DEFICIENT"),
                TEST_USERS["compliance_manager"],
            )
        )
        assert deficient["compliance_state"] == "DEFICIENT"
        assert deficient["last_finding_code"] == "LABEL_DEFICIENT"
        assert deficient["custody_state"] == "FILLING"
        assert_unit_state(fixtures.read_unit(scenario.unit["id"]), posture="RESTRICTED")

        sealed = validate_success(
            api_client.set_container_custody_state(
                scenario.container["id"],
                factories.custody_payload("SEALED"),
                TEST_USERS["clerk"],
            )
        )
        assert sealed["custody_state"] == "SEALED"
        assert sealed["compliance_state"] == "DEFICIENT"
        assert sealed["last_finding_code"] == "LABEL_DEFICIENT"
        assert_unit_state(
            fixtures.read_unit(scenario.unit["id"]),
            posture="RESTRICTED",
            container_count=1,
            stored_kg=200.0,
        )

    def test_condition_recovery_reopens_the_unit_while_custody_stays_sealed(self):
        """From `DEFICIENT` back to `COMPLIANT`, `last_finding_code` is cleared to null, the unit recomputes posture, and batches that are `HELD` with `held_reason_code` of `UNIT_POSTURE` return to `PLANNED` once posture is `OPEN` again.

        Otherwise it is `RESTRICTED` when any container in the unit is `DEFICIENT`, or when `utilization_pct` reaches or exceeds 0.9000 — the utilisation threshold is inclusive, so a unit sitting at exactly 0.9000 is restricted.
        `container_count` is the number of containers in the unit whose custody is `FILLING`, `SEALED` or `STAGED`.
        `stored_kg` is the sum of `net_weight_kg` over those same containers, to 3 decimals.

        Design: Difficulty/non_linear_state_machine/container_parallel_custody_and_compliance_dimensions
        """
        scenario = _container_filling_in_an_open_container_area()
        fixtures.set_container_compliance(
            scenario.container["id"], "DEFICIENT", "LABEL_DEFICIENT"
        )
        fixtures.seal_container(scenario.container["id"])

        recovered = validate_success(
            api_client.set_container_compliance_state(
                scenario.container["id"],
                factories.compliance_payload("COMPLIANT"),
                TEST_USERS["compliance_manager"],
            )
        )

        assert recovered["compliance_state"] == "COMPLIANT"
        assert recovered["last_finding_code"] is None
        assert recovered["custody_state"] == "SEALED"
        assert_unit_state(
            fixtures.read_unit(scenario.unit["id"]),
            posture="OPEN",
            container_count=1,
            stored_kg=200.0,
        )
