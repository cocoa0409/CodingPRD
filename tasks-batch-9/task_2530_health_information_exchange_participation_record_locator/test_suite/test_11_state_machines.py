"""Onboarding and conformance lifecycles: legal moves, refused moves, and the loop.

Every transition in this file is requested as an `action` value on a multiplexed
capability, so the tests check both the state the entity lands in and the fields
the transition is declared to write.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.factories import conformance_test_payload
from test_helpers.fixtures import HieHarness
from test_helpers.test_users import make_hie_admin_headers, make_participant_admin_headers

LEGAL_SIGNATORY = "admin-legal-1"
CERTIFIER = "admin-cert-1"


class TestOnboardingTransitions:
    """The onboarding chain from APPLIED through certification's gate."""

    def test_submitting_for_legal_review_moves_applied_to_legal_review_and_bumps_version(
        self, hie: HieHarness
    ):
        """The only forward move out of APPLIED, and it touches nothing else.

        PRD 3.1: "A `ParticipantAdmin` acting for its own organization opens the
        process by submitting for legal review, advancing `APPLIED → LEGAL_REVIEW`;
        the transition requires `onboarding_status` to be exactly `APPLIED` and
        requires `X-User-ID` to equal the participant's own `id`."

        PRD 3.1: "Each step is requested as an `action` value on a single
        multiplexed onboarding capability, and every step increments the
        participant's `version` by 1."

        Design: Corner/State Machines/submit_for_legal_review_moves_applied_to_legal_review
        """
        participant = hie.register_participant(
            legal_name="Larkspur Community Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=48000,
            primary_contact_email="hie@larkspur.example",
        )
        assert participant["version"] == 1
        assert participant["onboarding_status"] == "APPLIED"

        response = hie.client.transition_onboarding(
            make_participant_admin_headers(participant["id"]),
            participant["id"],
            action="SUBMIT_FOR_LEGAL_REVIEW",
        )
        moved = validate_success(response, 200)
        assert moved["onboarding_status"] == "LEGAL_REVIEW"
        assert moved["version"] == 2
        assert moved["agreement_version"] is None
        assert moved["agreement_signed_at"] is None
        assert moved["agreement_executed_by_user_id"] is None

    def test_certifying_with_two_of_the_three_required_profiles_is_refused(
        self, hie: HieHarness
    ):
        """`passed_profiles` must cover all three; two is not a superset.

        PRD 3.1: "The participant's `passed_profiles` must cover, as a superset,
        the three required certification profiles — `ADT_PUBLISHER`,
        `DOCUMENT_SOURCE` and `QUERY_RESPONDER` — failing which the attempt is
        rejected with `ERR_CERTIFICATION_PROFILES_INCOMPLETE`."

        PRD 3.1: "When all three hold, the participant advances
        `CONFORMANCE_TESTING → CERTIFIED`, with `certified_by_user_id` set to the
        acting `X-User-ID` and `certified_at` set to the logical clock."

        Design: Corner/State Machines/certify_without_all_required_profiles_returns_certification_profiles_incomplete
        """
        participant = hie.participant_in_conformance_testing(
            legal_name="Marlowe Point Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=60000,
            primary_contact_email="hie@marlowepoint.example",
            signatory_headers=make_hie_admin_headers(LEGAL_SIGNATORY),
        )
        hie.pass_profile(participant["id"], "ADT_PUBLISHER")
        hie.pass_profile(participant["id"], "DOCUMENT_SOURCE")

        validate_error(
            hie.client.transition_onboarding(
                make_hie_admin_headers(CERTIFIER), participant["id"], action="CERTIFY"
            ),
            "ERR_CERTIFICATION_PROFILES_INCOMPLETE",
            409,
        )

        stored = hie.get_participant(participant["id"])
        assert stored["onboarding_status"] == "CONFORMANCE_TESTING"
        assert stored["certified_by_user_id"] is None
        assert stored["certified_at"] is None
        assert stored["passed_profiles"] == ["ADT_PUBLISHER", "DOCUMENT_SOURCE"]

    def test_executing_the_agreement_stores_the_signatory_and_lands_in_conformance_testing(
        self, hie: HieHarness
    ):
        """One request, four side effects, and a state the caller never asked for.

        PRD 3.1: "That request must carry both an `agreement_version` label and a
        `signed_at` instant; the server stores them as `agreement_version` and
        `agreement_signed_at` respectively and records the acting `X-User-ID` as
        `agreement_executed_by_user_id`."

        PRD 3.1: "Execution does not stop there: **within the same request** the
        server performs the system transition `AGREEMENT_EXECUTED →
        CONFORMANCE_TESTING`, which resets `consecutive_failed_attempts` to 0, so
        the response body already reports `onboarding_status` as
        `CONFORMANCE_TESTING`."

        Design: Corner/State Machines/execute_agreement_records_signatory_and_auto_advances_to_conformance_testing
        """
        participant = hie.register_participant(
            legal_name="Norwood Crossing Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=84000,
            primary_contact_email="hie@norwoodcrossing.example",
        )
        in_review = hie.submit_for_legal_review(participant["id"])
        assert in_review["version"] == 2

        executed = validate_success(
            hie.client.transition_onboarding(
                make_hie_admin_headers(LEGAL_SIGNATORY),
                participant["id"],
                action="EXECUTE_AGREEMENT",
                agreement_version="DURSA-2026.1",
                signed_at="2026-07-20T09:30:00Z",
            ),
            200,
        )
        assert executed["onboarding_status"] == "CONFORMANCE_TESTING"
        assert executed["agreement_version"] == "DURSA-2026.1"
        assert executed["agreement_signed_at"].startswith("2026-07-20T09:30:00")
        assert executed["agreement_executed_by_user_id"] == LEGAL_SIGNATORY
        assert executed["version"] == 3
        assert executed["consecutive_failed_attempts"] == 0

    def test_certifying_from_legal_review_reports_the_transition_fault_not_the_profile_gap(
        self, hie: HieHarness
    ):
        """Priority 10 outranks the certification gate, so the state fault is what surfaces.

        PRD 2.9: "The requested action is not an outgoing transition of the
        entity's current non-terminal state, or a declared precondition of the
        selected transition that carries no error code of its own is unsatisfied —
        `ERR_INVALID_STATE_TRANSITION`, on every action endpoint."

        PRD 2.9: "When a single request violates more than one rule, the response
        reports the violation with the lowest precedence number in the ordering
        below."

        Design: Corner/State Machines/certify_from_legal_review_returns_invalid_state_transition
        """
        participant = hie.register_participant(
            legal_name="Oakhurst Valley Clinic",
            org_type="CLINIC",
            declared_annual_patient_volume=18000,
            primary_contact_email="hie@oakhurst.example",
        )
        hie.submit_for_legal_review(participant["id"])

        response = hie.client.transition_onboarding(
            make_hie_admin_headers(CERTIFIER), participant["id"], action="CERTIFY"
        )
        validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)
        assert "ERR_CERTIFICATION_PROFILES_INCOMPLETE" not in str(response.json())

        stored = hie.get_participant(participant["id"])
        assert stored["onboarding_status"] == "LEGAL_REVIEW"
        assert stored["version"] == 2


class TestConformanceRunLifecycle:
    """Where a run starts, what locks it down, and how the failure loop closes."""

    def test_a_freshly_booked_run_starts_in_running_as_the_first_attempt(
        self, hie: HieHarness
    ):
        """No run is ever created directly in PASSED or FAILED.

        PRD 3.2: "The created run has `status` `RUNNING`, its `participant_id`
        taken from the path, its `executed_by_user_id` recorded from the acting
        `X-User-ID`, and an `attempt_number` computed as one more than the count of
        that participant's prior runs for the same `profile` — equivalently, the
        run's one-based ordinal among same-profile runs ordered by ascending
        `created_at`."

        PRD 3.2: "Booking also increments the participant's
        `conformance_attempt_count` by 1."

        PRD 3.2: "Two derived values are written. `pass_rate` is
        `assertions_passed` divided by `assertions_total`, rounded half up to four
        decimal places."

        Design: Corner/State Machines/scheduled_conformance_run_starts_in_running_with_attempt_number_one
        """
        participant = hie.participant_in_conformance_testing(
            legal_name="Pemberton Heights Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=66000,
            primary_contact_email="hie@pemberton.example",
            signatory_headers=make_hie_admin_headers(LEGAL_SIGNATORY),
        )

        response = hie.client.schedule_conformance_test(
            hie.admin,
            participant["id"],
            **conformance_test_payload(
                profile="QUERY_RESPONDER",
                scheduled_start="2026-08-01T00:00:00Z",
                scheduled_end="2026-08-01T06:00:00Z",
            ),
        )
        assert response.status_code == 201
        run = validate_success(response, 201)
        assert run["status"] == "RUNNING"
        assert run["attempt_number"] == 1
        assert run["pass_rate"] is None
        assert run["critical_failure"] is False
        assert run["participant_id"] == participant["id"]
        assert run["executed_by_user_id"] == hie.admin["X-User-ID"]

        assert hie.get_participant(participant["id"])["conformance_attempt_count"] == 1

    def test_a_passed_run_cannot_be_waived(self, hie: HieHarness):
        """PASSED is terminal for a run, so the waiver never reaches its precondition.

        PRD 2.9: "The entity is already in a terminal state — `ERR_TERMINAL_STATE`,
        on every action endpoint."

        PRD 3.2: "A `HieAdmin` may waive it, moving the run `FAILED → WAIVED` with
        a supplied `waiver_reason`; the waiver appends the `profile` to
        `passed_profiles` under the same deduplicate-and-sort rule and resets
        `consecutive_failed_attempts` to 0, exactly as a pass would."

        Design: Corner/State Machines/waiver_on_an_already_passed_conformance_run_returns_terminal_state
        """
        participant = hie.participant_in_conformance_testing(
            legal_name="Quarrymill Regional Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=54000,
            primary_contact_email="hie@quarrymill.example",
            signatory_headers=make_hie_admin_headers(LEGAL_SIGNATORY),
        )
        run = hie.pass_profile(participant["id"], "ADT_PUBLISHER")
        assert run["status"] == "PASSED"

        validate_error(
            hie.client.waive_conformance_test(
                hie.admin,
                run["id"],
                waiver_reason="Attempting to waive a run that already passed.",
            ),
            "ERR_TERMINAL_STATE",
            409,
        )

        stored = validate_success(hie.client.get_conformance_test(hie.admin, run["id"]), 200)
        assert stored["status"] == "PASSED"
        assert stored["waiver_reason"] is None

    def test_repeating_the_legal_review_submission_is_refused_the_second_time(
        self, hie: HieHarness
    ):
        """The action endpoint is not idempotent: version advances exactly once.

        PRD 2.9: "The requested action is not an outgoing transition of the
        entity's current non-terminal state, or a declared precondition of the
        selected transition that carries no error code of its own is unsatisfied —
        `ERR_INVALID_STATE_TRANSITION`, on every action endpoint."

        PRD 3.1: "A `ParticipantAdmin` acting for its own organization opens the
        process by submitting for legal review, advancing `APPLIED → LEGAL_REVIEW`;
        the transition requires `onboarding_status` to be exactly `APPLIED` and
        requires `X-User-ID` to equal the participant's own `id`."

        Design: Corner/State Machines/repeating_submit_for_legal_review_is_rejected_on_the_second_attempt
        """
        participant = hie.register_participant(
            legal_name="Rosevale Community Clinic",
            org_type="CLINIC",
            declared_annual_patient_volume=21000,
            primary_contact_email="hie@rosevale.example",
        )
        headers = make_participant_admin_headers(participant["id"])

        first = validate_success(
            hie.client.transition_onboarding(
                headers, participant["id"], action="SUBMIT_FOR_LEGAL_REVIEW"
            ),
            200,
        )
        assert first["onboarding_status"] == "LEGAL_REVIEW"
        assert first["version"] == 2

        validate_error(
            hie.client.transition_onboarding(
                headers, participant["id"], action="SUBMIT_FOR_LEGAL_REVIEW"
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        assert hie.get_participant(participant["id"])["version"] == 2

    def test_three_failures_push_the_participant_into_remediation_and_resuming_returns_it(
        self, hie: HieHarness
    ):
        """The onboarding cycle is re-enterable: nothing proven is discarded on the way round.

        PRD 3.2: "On a failure, `consecutive_failed_attempts` is incremented by 1,
        and when it reaches the consecutive-failure limit of three the server
        immediately fires the system transition `CONFORMANCE_TESTING →
        REMEDIATION` on the owning participant, incrementing `remediation_count` by
        1, leaving `suspension_reason` untouched and leaving `passed_profiles`
        intact."

        PRD 3.1: "A `ParticipantAdmin` acting for its own organization closes the
        loop by resuming conformance, `REMEDIATION → CONFORMANCE_TESTING`, which
        resets `consecutive_failed_attempts` to 0 while deliberately preserving
        both `passed_profiles` and `conformance_attempt_count` — nothing already
        proven is thrown away."

        PRD 3.2: "The floor is inclusive, which is observable at the boundary: 190
        assertions passed out of 200 yields exactly 0.9500 and passes, while 189
        out of 200 yields 0.9450 and fails."

        Design: Corner/State Machines/onboarding_loops_conformance_testing_to_remediation_and_back
        """
        participant = hie.participant_in_conformance_testing(
            legal_name="Stonebrook Medical Center",
            org_type="HOSPITAL",
            declared_annual_patient_volume=78000,
            primary_contact_email="hie@stonebrook.example",
            signatory_headers=make_hie_admin_headers(LEGAL_SIGNATORY),
        )

        first = hie.fail_profile(
            participant["id"], "ADT_PUBLISHER", assertions_total=200, assertions_passed=189
        )
        assert first["status"] == "FAILED"
        assert abs(first["pass_rate"] - 0.9450) < 0.0001
        assert first["attempt_number"] == 1

        second = hie.fail_profile(
            participant["id"], "ADT_PUBLISHER", assertions_total=200, assertions_passed=189
        )
        assert second["attempt_number"] == 2
        after_two = hie.get_participant(participant["id"])
        assert after_two["onboarding_status"] == "CONFORMANCE_TESTING"
        assert after_two["consecutive_failed_attempts"] == 2

        third = hie.fail_profile(
            participant["id"], "ADT_PUBLISHER", assertions_total=200, assertions_passed=189
        )
        assert third["attempt_number"] == 3
        assert third["status"] == "FAILED"

        in_remediation = hie.get_participant(participant["id"])
        assert in_remediation["onboarding_status"] == "REMEDIATION"
        assert in_remediation["remediation_count"] == 1
        assert in_remediation["consecutive_failed_attempts"] == 3
        assert in_remediation["conformance_attempt_count"] == 3
        assert in_remediation["passed_profiles"] == []

        resumed = validate_success(
            hie.client.transition_onboarding(
                make_participant_admin_headers(participant["id"]),
                participant["id"],
                action="RESUME_CONFORMANCE",
            ),
            200,
        )
        assert resumed["onboarding_status"] == "CONFORMANCE_TESTING"
        assert resumed["consecutive_failed_attempts"] == 0
        assert resumed["conformance_attempt_count"] == 3
        assert resumed["passed_profiles"] == []

        runs, meta = validate_paginated(
            hie.client.list_participant_conformance_tests(
                hie.admin, participant["id"], profile="ADT_PUBLISHER"
            )
        )
        assert meta["total_count"] == 3
        assert [row["attempt_number"] for row in runs] == [1, 2, 3]
