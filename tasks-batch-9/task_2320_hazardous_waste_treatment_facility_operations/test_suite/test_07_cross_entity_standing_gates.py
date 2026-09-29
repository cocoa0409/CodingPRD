"""Operations refused because of the standing of a row they only reference.

A treatment run held back by its facility's lapsed permit, and a waste profile
approval held back by the standing of the offering generator.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import TEST_USERS, api_client, assert_mass, fixtures
from test_helpers.factories import batch_operation_payload, profile_decision_payload


def _planned_batch_whose_facility_permit_has_lapsed() -> fixtures.Scenario:
    """A batch planned on 2026-08-01 for a window on 2026-08-20, under a permit
    that expires on 2026-08-10, with the clock carried inside the window."""
    scenario = fixtures.setup_planned_batch(
        facility_overrides={"permit_expires_at": "2026-08-10T00:00:00Z"},
        declared_quantity_kg=500.0,
        declared_container_count=1,
        net_weight_kg=200.0,
        window_start="2026-08-20T00:00:00Z",
        window_end="2026-08-20T12:00:00Z",
    )
    fixtures.set_clock("2026-08-20T01:00:00Z")
    return scenario


def _start_the_run(scenario: fixtures.Scenario):
    return api_client.batch_operation(
        scenario.batch["id"], batch_operation_payload("START"), TEST_USERS["operator"]
    )


def _sample_passed_profile_of_a_suspended_generator() -> fixtures.Scenario:
    """A profile that has cleared its verification sample, whose generator was
    suspended before the decision could be signed."""
    fixtures.set_clock()
    facility = fixtures.create_facility()
    generator = fixtures.create_generator()
    profile = fixtures.create_draft_profile(generator["id"], facility["id"])
    submitted = fixtures.submit_profile(profile["id"], generator["id"])
    fixtures.record_sample(profile["id"], submitted["version"])
    fixtures.set_generator_status(generator["id"], "SUSPENDED", reason_code="UNPAID_INVOICES")
    return fixtures.Scenario(
        facility=facility,
        generator=fixtures.read_generator(generator["id"]),
        profile=fixtures.read_profile(profile["id"]),
    )


def _sign_the_approval(scenario: fixtures.Scenario):
    return api_client.decide_waste_profile(
        scenario.profile["id"],
        profile_decision_payload("APPROVE", "INCINERATION"),
        TEST_USERS["chemist_2"],
    )


class TestTreatmentStartAgainstPermitStanding:
    def test_start_is_refused_once_the_permit_term_has_run_out(self):
        """The clock passing the permit expiry is enough on its own to refuse the
        start of an otherwise sound planned run.

        PRD: "**Permit standing.** The facility's `permit_status` is either `ACTIVE` or `RENEWAL_PENDING` for waste acceptance and for treatment — `ERR_PERMIT_NOT_ACTIVE` (403)."
        PRD: "`START` advances the batch from `PLANNED` to `IN_TREATMENT` and carries five preconditions: the facility's permit must stand as `ACTIVE` or `RENEWAL_PENDING`, failing which `ERR_PERMIT_NOT_ACTIVE` is returned; the batch's `treatment_method` must appear in the facility's `permitted_methods`, failing which `ERR_METHOD_NOT_PERMITTED` is returned; the unit's posture must be exactly `OPEN`, failing which `ERR_UNIT_POSTURE_BLOCKED` is returned; the unit must not be inspection-overdue, failing which `ERR_INSPECTION_OVERDUE` is returned; and the current clock instant must be at or after `window_start`, failing which the request is an invalid state."
        PRD: "Whenever the facility is read or touched by a mutation and the clock has passed `permit_expires_at`, an `ACTIVE` facility is observed as `EXPIRED` and a `RENEWAL_PENDING` facility is likewise observed as `EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/treatment_batch_start_blocked_by_facility_permit_expired
        """
        scenario = _planned_batch_whose_facility_permit_has_lapsed()
        assert fixtures.read_facility(scenario.facility["id"])["permit_status"] == "EXPIRED"

        validate_error(_start_the_run(scenario), "ERR_PERMIT_NOT_ACTIVE")

    def test_refused_start_leaves_the_batch_planned_and_its_mass_reserved(self):
        """The lapse does not cascade: the batch keeps PLANNED and its input mass
        stays reserved on the storage unit.

        PRD: "Neither lapse cascades: batches that were already `PLANNED` keep that status, but they can no longer be started, because starting treatment requires the permit to stand and would otherwise be refused with `ERR_PERMIT_NOT_ACTIVE`."
        PRD: "`reserved_kg` is the sum of `input_mass_kg` over the batches on the unit whose `status` is `PLANNED` or `IN_TREATMENT`, to 3 decimals."

        Design: Difficulty/cross_entity_state_dependency/treatment_batch_start_blocked_by_facility_permit_expired
        """
        scenario = _planned_batch_whose_facility_permit_has_lapsed()
        validate_error(_start_the_run(scenario), "ERR_PERMIT_NOT_ACTIVE")

        assert fixtures.read_batch(scenario.batch["id"])["status"] == "PLANNED"
        unit = fixtures.read_unit(scenario.unit["id"])
        assert_mass(unit["reserved_kg"], 200.0, "reserved_kg")


class TestProfileApprovalAgainstGeneratorStanding:
    def test_approval_is_refused_while_the_offering_generator_is_suspended(self):
        """A suspended offeror blocks the approval signature even though the sample
        passed, the signer is a second chemist and the method is permitted.

        PRD: "**Generator standing.** The generator on the operation's path is neither `SUSPENDED` nor `TERMINATED` — `ERR_GENERATOR_SUSPENDED` (409)."
        PRD: "Moving from `ACTIVE` to `SUSPENDED` records the supplied reason code in `suspension_reason_code`, after which new waste profile approval decisions for that generator are refused with `ERR_GENERATOR_SUSPENDED`."
        PRD: "Approval is defined only from `SAMPLE_PASSED` and carries three preconditions, all of which must hold: the acting `X-User-ID` must differ from the `recorded_by_user_id` of the profile's most recent sample — that is, the last sample when the profile's samples are ordered by `created_at` ascending — failing which the request is refused with `ERR_SEGREGATION_OF_DUTIES`; the owning generator must be `ACTIVE`, failing which `ERR_GENERATOR_SUSPENDED` is returned; and the method being approved must appear in the `permitted_methods` of the facility named by the profile's `facility_id`, failing which `ERR_METHOD_NOT_PERMITTED` is returned."

        Design: Difficulty/cross_entity_state_dependency/profile_approval_blocked_by_generator_suspended
        """
        scenario = _sample_passed_profile_of_a_suspended_generator()
        assert scenario.generator["status"] == "SUSPENDED"
        assert scenario.profile["status"] == "SAMPLE_PASSED"

        validate_error(_sign_the_approval(scenario), "ERR_GENERATOR_SUSPENDED")

    def test_refused_approval_leaves_the_profile_unsigned(self):
        """The profile stays where the passing sample left it, with nothing of the
        approval written.

        PRD: "A passing sample moves the profile from `SUBMITTED` to `SAMPLE_PASSED`."
        PRD: "A new profile opens in `DRAFT`, with `sample_attempt_count` at zero, `latest_sample_result` of `NONE`, and `approved_treatment_method`, `approved_at`, `approved_by_user_id`, `recertification_due_at` and `suspension_reason_code` all null."

        Design: Difficulty/cross_entity_state_dependency/profile_approval_blocked_by_generator_suspended
        """
        scenario = _sample_passed_profile_of_a_suspended_generator()
        validate_error(_sign_the_approval(scenario), "ERR_GENERATOR_SUSPENDED")

        profile = fixtures.read_profile(scenario.profile["id"])
        assert profile["status"] == "SAMPLE_PASSED"
        assert profile["approved_at"] is None
        assert profile["approved_treatment_method"] is None
        assert profile["approved_by_user_id"] is None
        assert profile["recertification_due_at"] is None
