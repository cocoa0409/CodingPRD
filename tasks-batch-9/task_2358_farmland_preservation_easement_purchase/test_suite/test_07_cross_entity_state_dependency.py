"""Writes on one entity gated by a state dimension living on another entity.

Filing an application reads the parcel's eligibility dimension; submitting an
amendment reads the easement's compliance dimension. Neither gate is visible on
the row being written.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_cure_plan,
    api_client,
    create_application_payload,
    create_open_round,
    draft_amendment,
    file_application,
    make_landowner_headers,
    read_amendment,
    read_easement,
    read_parcel,
    run_sweep,
    set_clock,
    setup_easement_with_open_violation,
    setup_filed_application,
    setup_recorded_easement,
    submit_amendment,
    verify_cure,
    withdrawal_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestFilingGatedByParcelEligibility:
    """The filing gate reads the parcel's own status, not the application's."""

    def test_a_parcel_already_under_application_refuses_a_second_filing(self):
        """The first filing moves the parcel out of ELIGIBLE and closes the door.

        PRD §3.3: "The parcel's `status` must be `ELIGIBLE` and its
        `restricted_value_cents` must be strictly below its
        `unrestricted_value_cents`, otherwise `ERR_PARCEL_NOT_ELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/application_filing_is_gated_by_the_parcel_eligibility_dimension
        """
        scenario = setup_filed_application()
        landowner_id = scenario["landowner"]["id"]
        parcel = read_parcel(scenario["parcel"]["id"])
        assert parcel["status"] == "UNDER_APPLICATION"

        response = api_client.create_application(
            create_application_payload(
                scenario["round"]["id"], parcel["id"], landowner_id
            ),
            make_landowner_headers(landowner_id),
        )
        validate_error(response, ApiErrorId.ERR_PARCEL_NOT_ELIGIBLE.value)

    def test_withdrawal_returns_the_parcel_to_eligible_and_reopens_filing(self):
        """The gate swings both ways: releasing the land re-admits a filing.

        PRD §3.5: "The parcel returns `UNDER_APPLICATION → ELIGIBLE` with its
        `version` incremented, and the application's `version` increments."

        Design: Difficulty/cross_entity_state_dependency/application_filing_is_gated_by_the_parcel_eligibility_dimension
        """
        scenario = setup_filed_application()
        landowner_id = scenario["landowner"]["id"]
        landowner_headers = make_landowner_headers(landowner_id)

        validate_success(
            api_client.withdraw_application(
                scenario["application"]["id"], withdrawal_payload(), landowner_headers
            )
        )
        released = read_parcel(scenario["parcel"]["id"])
        assert released["status"] == "ELIGIBLE"

        refiled = file_application(
            scenario["round"]["id"], scenario["parcel"]["id"], landowner_id
        )
        assert refiled["status"] == "RECEIVED"
        assert read_parcel(scenario["parcel"]["id"])["status"] == "UNDER_APPLICATION"

    def test_an_encumbered_parcel_refuses_a_filing_on_a_later_round(self):
        """A parcel already carrying an easement is permanently out of intake.

        PRD §3.7: "The parcel moves `UNDER_APPLICATION → ENCUMBERED` with its
        `version` incremented."

        Design: Difficulty/cross_entity_state_dependency/application_filing_is_gated_by_the_parcel_eligibility_dimension
        """
        scenario = setup_recorded_easement()
        landowner_id = scenario["landowner"]["id"]
        encumbered = read_parcel(scenario["parcel"]["id"])
        assert encumbered["status"] == "ENCUMBERED"

        # A fresh round whose intake window straddles the 2026-12-15 clock.
        later_round = create_open_round(
            scenario["program"]["id"],
            round_label="2027 Cycle A",
            opens_on="2026-12-01T00:00:00Z",
            closes_on="2027-03-31T00:00:00Z",
        )
        assert later_round["status"] == "OPEN"

        response = api_client.create_application(
            create_application_payload(
                later_round["id"], encumbered["id"], landowner_id
            ),
            make_landowner_headers(landowner_id),
        )
        validate_error(response, ApiErrorId.ERR_PARCEL_NOT_ELIGIBLE.value)


class TestAmendmentSubmissionGatedByCompliance:
    """A STRICT program admits submission only from `COMPLIANT`."""

    def test_an_open_violation_blocks_submission_under_a_strict_policy(self):
        """The draft is admissible; the submission is not.

        PRD §3.9: "The easement's `stewardship_hold` must be false, and its
        `compliance_status` must be admissible under the program's policy: a
        `STRICT` program requires `compliance_status` to be exactly `COMPLIANT`,
        while a `CONDITIONAL` program also admits `VIOLATION_CURED`. Any other
        posture is rejected with `ERR_EASEMENT_NOT_COMPLIANT`."

        Design: Difficulty/cross_entity_state_dependency/amendment_submission_is_gated_by_the_easement_compliance_dimension_under_strict_policy
        """
        scenario = setup_easement_with_open_violation()
        assert scenario["program"]["amendment_policy"] == "STRICT"
        easement_id = scenario["easement"]["id"]
        assert scenario["easement"]["compliance_status"] == "VIOLATION_OPEN"
        assert scenario["easement"]["stewardship_hold"] is True

        # Drafting has no compliance precondition at all.
        draft = draft_amendment(easement_id, amendment_type="BOUNDARY_ADJUSTMENT")
        assert draft["status"] == "DRAFT"

        response = api_client.submit_amendment(draft["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_EASEMENT_NOT_COMPLIANT.value)
        assert read_amendment(draft["id"])["status"] == "DRAFT"
        assert read_easement(easement_id)["pending_amendment_count"] == 0

    def test_a_freshly_cured_easement_still_blocks_submission_under_strict(self):
        """`VIOLATION_CURED` is a posture only a CONDITIONAL program admits.

        PRD §3.9: "Since a freshly cured easement sits in `VIOLATION_CURED`, only
        a `CONDITIONAL` program can reinstate immediately; a `STRICT` program
        must wait for the sweep to return the easement to `COMPLIANT` ninety days
        after the cure."

        Design: Difficulty/cross_entity_state_dependency/amendment_submission_is_gated_by_the_easement_compliance_dimension_under_strict_policy
        """
        scenario = setup_easement_with_open_violation()
        easement_id = scenario["easement"]["id"]
        violation_id = scenario["violation"]["id"]

        set_clock("2026-12-20T00:00:00Z")
        accept_cure_plan(violation_id)
        set_clock("2027-01-10T00:00:00Z")
        verify_cure(violation_id)

        cured = read_easement(easement_id)
        assert cured["compliance_status"] == "VIOLATION_CURED"
        # The hold is released even though the posture is not yet COMPLIANT.
        assert cured["stewardship_hold"] is False

        draft = draft_amendment(easement_id, amendment_type="BOUNDARY_ADJUSTMENT")
        response = api_client.submit_amendment(draft["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_EASEMENT_NOT_COMPLIANT.value)

    def test_a_conditional_policy_admits_the_same_cured_easement(self):
        """The only difference is one program field on a third entity.

        PRD §3.9: "a `STRICT` program requires `compliance_status` to be exactly
        `COMPLIANT`, while a `CONDITIONAL` program also admits
        `VIOLATION_CURED`."

        Design: Difficulty/cross_entity_state_dependency/amendment_submission_is_gated_by_the_easement_compliance_dimension_under_strict_policy
        """
        scenario = setup_easement_with_open_violation(
            program_overrides={"amendment_policy": "CONDITIONAL"}
        )
        easement_id = scenario["easement"]["id"]
        violation_id = scenario["violation"]["id"]

        set_clock("2026-12-20T00:00:00Z")
        accept_cure_plan(violation_id)
        set_clock("2027-01-10T00:00:00Z")
        verify_cure(violation_id)
        assert read_easement(easement_id)["compliance_status"] == "VIOLATION_CURED"

        draft = draft_amendment(easement_id, amendment_type="BOUNDARY_ADJUSTMENT")
        submitted = submit_amendment(draft["id"])
        assert submitted["status"] == "UNDER_REVIEW"
        assert read_easement(easement_id)["pending_amendment_count"] == 1

    def test_the_ninety_day_sweep_restores_compliant_and_unblocks_strict(self):
        """Under STRICT the gate opens only once the sweep clears the posture.

        PRD §3.8: "an easement in `VIOLATION_CURED` with `open_violation_count`
        at 0 returns to `COMPLIANT` once the logical clock reaches or passes the
        latest `cured_on` among its violations advanced by 90 days with no new
        violation opened in the meantime."

        Design: Difficulty/cross_entity_state_dependency/amendment_submission_is_gated_by_the_easement_compliance_dimension_under_strict_policy
        """
        scenario = setup_easement_with_open_violation()
        easement_id = scenario["easement"]["id"]
        violation_id = scenario["violation"]["id"]

        set_clock("2026-12-20T00:00:00Z")
        accept_cure_plan(violation_id)
        set_clock("2027-01-10T00:00:00Z")
        verify_cure(violation_id)

        # 2027-01-10 advanced by 90 days.
        set_clock("2027-04-10T00:00:00Z")
        counters = run_sweep()
        assert counters["cleared_to_compliant_count"] == 1

        restored = read_easement(easement_id)
        assert restored["compliance_status"] == "COMPLIANT"

        draft = draft_amendment(easement_id, amendment_type="BOUNDARY_ADJUSTMENT")
        submitted = submit_amendment(draft["id"])
        assert submitted["status"] == "UNDER_REVIEW"
