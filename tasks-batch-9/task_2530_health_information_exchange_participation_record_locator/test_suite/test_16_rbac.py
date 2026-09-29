"""Role authorization and the duty separations that outrank it.

Three questions are asked here. Can a role reach everything the contract grants
it, addressing its own organization? Is every peer role refused the operations
another role reserves? And where the contract keys a refusal on the acting user
identity rather than on the role, does the identity alone decide the outcome?
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import HieHarness
from test_helpers.test_users import (
    make_clinician_headers,
    make_hie_admin_headers,
    make_participant_admin_headers,
    make_privacy_officer_headers,
    make_public_health_officer_headers,
)


class TestParticipantAdminReachesEverythingItIsGranted:
    """The entity-backed role, acting for its own organization, end to end."""

    SIGNATORY = "admin-legal-1"
    WITHDRAWAL_REASON = "Board vote reversed the participation decision"

    def test_both_exclusive_actions_and_all_three_shared_operations_succeed(
        self, hie: HieHarness
    ):
        """Its own admin drives the organization from APPLIED to WITHDRAWN and back through data.

        PRD 2.3: "The per-action split is as follows: only a `HieAdmin` may drive
        `EXECUTE_AGREEMENT`, `CERTIFY`, `REMEDIATE`, `SUSPEND`, `REINSTATE` or
        `TERMINATE` on a participant, and only a `HieAdmin` may `WRITE_OFF` an
        invoice; only a `ParticipantAdmin` may drive `SUBMIT_FOR_LEGAL_REVIEW`,
        `RESUME_CONFORMANCE` or `WITHDRAW`; and only a `PrivacyOfficer` may issue a
        match-link `REOPEN`."

        PRD 3.1: "Withdrawal is available to a `ParticipantAdmin` acting for its own
        organization from any pre-certification state: the same withdraw action is
        accepted while `onboarding_status` is `APPLIED`, `LEGAL_REVIEW`,
        `AGREEMENT_EXECUTED`, `CONFORMANCE_TESTING` or `REMEDIATION`, in every case
        moving the participant to `WITHDRAWN` with identical side effects — every
        conformance run of that participant still in `RUNNING` is forced to
        `FAILED` with its `failure_categories` set to a single-member list
        containing `TRANSPORT`."

        PRD 3.5: "When the qualifying set is empty the participant is ungraded:
        `quality_score` is null, `grade` and `provisional_grade` are both
        `UNGRADED`, `penalty_points` is zero, and the four components,
        `average_p95_seconds` and `base_quality_score` are all reported as zero."

        Design: Corner/RBAC/participant_admin_performs_its_exclusive_and_shared_operations
        """
        hie.activate_threshold_config(config_label="REF-PROB-R1")
        participant = hie.register_participant(
            legal_name="Westbrook Family Health Center",
            org_type="CLINIC",
            declared_annual_patient_volume=30000,
            primary_contact_email="hie@westbrook.example",
        )
        own_admin = make_participant_admin_headers(participant["id"])

        after_submission = validate_success(
            hie.client.transition_onboarding(
                own_admin, participant["id"], action="SUBMIT_FOR_LEGAL_REVIEW"
            ),
            200,
        )
        assert after_submission["onboarding_status"] == "LEGAL_REVIEW"

        after_agreement = validate_success(
            hie.client.transition_onboarding(
                make_hie_admin_headers(self.SIGNATORY),
                participant["id"],
                action="EXECUTE_AGREEMENT",
                agreement_version="DURSA-2026.1",
                signed_at="2026-08-01T00:00:00Z",
            ),
            200,
        )
        assert after_agreement["onboarding_status"] == "CONFORMANCE_TESTING"

        run = get_success_data(
            hie.client.schedule_conformance_test(
                own_admin,
                participant["id"],
                profile="ADT_PUBLISHER",
                scheduled_start="2026-08-01T00:00:00Z",
                scheduled_end="2026-08-01T06:00:00Z",
            )
        )
        assert run["status"] == "RUNNING"

        record = get_success_data(
            hie.client.contribute_patient_record(
                own_admin,
                participant["id"],
                source_mrn="R1-0001",
                given_name="Winifred",
                family_name="Baptiste",
                birth_date="1994-03-30",
                sex="F",
                ssn_last4="5512",
                postal_code="04101",
                phone_digits="2075550122",
            )
        )
        assert record["match_state"] == "CLUSTERED"

        scorecard = validate_success(
            hie.client.get_participant_scorecard(own_admin, participant["id"]), 200
        )
        assert scorecard["samples_counted"] == 0
        assert scorecard["quality_score"] is None
        assert scorecard["grade"] == "UNGRADED"

        withdrawn = validate_success(
            hie.client.transition_onboarding(
                own_admin,
                participant["id"],
                action="WITHDRAW",
                reason=self.WITHDRAWAL_REASON,
            ),
            200,
        )
        assert withdrawn["onboarding_status"] == "WITHDRAWN"

        forced = validate_success(hie.client.get_conformance_test(hie.admin, run["id"]), 200)
        assert forced["status"] == "FAILED"
        assert forced["failure_categories"] == ["TRANSPORT"]


class TestThePeerRoleMatrixIsRefusedInEveryDirection:
    """Priority 2 fires for every direction, not only for the non-admin case."""

    POLICY_OFFICER = "privacy-policy-1"
    CLINICIAN = "clin-r2-1"

    def test_six_otherwise_valid_requests_are_each_refused_at_the_endpoint_role_check(
        self, hie: HieHarness
    ):
        """Each caller is absent from its target endpoint's role list, so nothing is looked up.

        PRD 2.3: "A role string outside that set, or a recognized role that is not
        listed among the authorized roles for the addressed endpoint, is rejected
        with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        PRD 2.9: "`X-User-Role` unrecognized, or not authorized for the addressed
        endpoint, on any endpoint — `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/RBAC/each_role_is_refused_the_other_roles_exclusive_operations
        """
        officer = make_privacy_officer_headers(self.POLICY_OFFICER)
        clinician = make_clinician_headers(self.CLINICIAN)
        stand_in_participant = NON_EXISTENT_UUID

        refusals = [
            hie.client.register_participant(
                officer,
                legal_name="Yellowpine Health Alliance",
                org_type="HOSPITAL",
                declared_annual_patient_volume=40000,
                primary_contact_email="hie@yellowpine.example",
            ),
            hie.client.draft_consent_policy(
                clinician,
                policy_version="R2-ATTEMPT",
                model="OPT_IN",
                sensitive_categories_segmented=[],
                default_share_for_treatment=False,
                effective_from="2026-01-01T00:00:00Z",
            ),
            hie.client.set_logical_clock(
                make_participant_admin_headers(stand_in_participant),
                to_iso8601="2026-09-01T00:00:00Z",
            ),
            hie.client.open_break_glass_access(
                make_public_health_officer_headers(stand_in_participant),
                cluster_id=NON_EXISTENT_UUID,
                invoking_participant_id=stand_in_participant,
                emergency_category="LIFE_THREATENING",
                justification_text=(
                    "Unresponsive patient in the field; medication and allergy "
                    "history required immediately."
                ),
            ),
            hie.client.claim_break_glass_review(hie.admin, NON_EXISTENT_UUID),
            hie.client.get_patient_record(clinician, NON_EXISTENT_UUID),
        ]
        for response in refusals:
            validate_error(response, "ERR_ROLE_NOT_PERMITTED", 403)


class TestTheSignatoryMayNotCertify:
    """Both calls are HieAdmin; only the operator identity differs."""

    SIGNATORY = "admin-legal-1"
    CERTIFIER = "admin-cert-1"

    def test_the_signing_administrator_is_refused_and_a_second_one_certifies(
        self, hie: HieHarness
    ):
        """The refusal leaves the participant in CONFORMANCE_TESTING with no certification stamp.

        PRD 3.1: "The acting `X-User-ID` must differ from the stored
        `agreement_executed_by_user_id`, failing which the attempt is rejected with
        `ERR_SOD_CERTIFIER_IS_SIGNATORY`."

        PRD 3.1: "When all three hold, the participant advances
        `CONFORMANCE_TESTING → CERTIFIED`, with `certified_by_user_id` set to the
        acting `X-User-ID` and `certified_at` set to the logical clock."

        Design: Corner/RBAC/the_agreement_signatory_may_not_certify_the_same_participant
        """
        signatory = make_hie_admin_headers(self.SIGNATORY)
        participant = hie.participant_in_conformance_testing(
            legal_name="Zephyr Point Medical Center",
            org_type="HOSPITAL",
            declared_annual_patient_volume=96000,
            primary_contact_email="hie@zephyrpoint.example",
            signatory_headers=signatory,
        )
        assert participant["agreement_executed_by_user_id"] == self.SIGNATORY
        for profile in ("ADT_PUBLISHER", "DOCUMENT_SOURCE", "QUERY_RESPONDER"):
            hie.pass_profile(participant["id"], profile)

        validate_error(
            hie.client.transition_onboarding(signatory, participant["id"], action="CERTIFY"),
            "ERR_SOD_CERTIFIER_IS_SIGNATORY",
            403,
        )
        untouched = hie.get_participant(participant["id"])
        assert untouched["onboarding_status"] == "CONFORMANCE_TESTING"
        assert untouched["certified_at"] is None

        certified = validate_success(
            hie.client.transition_onboarding(
                make_hie_admin_headers(self.CERTIFIER), participant["id"], action="CERTIFY"
            ),
            200,
        )
        assert certified["onboarding_status"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == self.CERTIFIER
        assert certified["certified_at"].startswith("2026-08-01T00:00:00")


class TestTheTunerMayNotStewardItsOwnLinks:
    """The separation is keyed on the generation pinned into the link."""

    TUNER = "privacy-tuner-1"
    STEWARD = "privacy-steward-1"
    REVIEW_NOTE = "Same patient; demographic drift explained by a marriage record."

    def test_the_activating_officer_is_refused_and_a_peer_officer_confirms(
        self, hie: HieHarness
    ):
        """The refusal does not consume the cluster version, so the peer reuses it.

        PRD 3.5: "And the acting `X-User-ID` must differ from the
        `activated_by_user_id` of the tuning generation pinned to this link, failing
        which it is rejected with `ERR_SOD_STEWARD_IS_TUNER` — the officer who tuned
        the thresholds does not get to adjudicate the links those thresholds
        produced."

        PRD 3.5: "The supplied `expected_cluster_version` must equal the current
        `version` of the cluster holding the link's left record."

        PRD 3.5: "The cluster with the earlier `created_at` wins; the loser moves
        `ACTIVE → MERGED_AWAY` with `merged_into_cluster_id` set to the winner."

        Design: Corner/RBAC/the_officer_who_activated_the_generation_may_not_steward_its_links
        """
        tuner = make_privacy_officer_headers(self.TUNER)
        steward = make_privacy_officer_headers(self.STEWARD)
        generation = hie.activate_threshold_config(
            config_label="R4-TUNED-BY-TUNER-1", headers=tuner
        )
        assert generation["activated_by_user_id"] == self.TUNER

        left_owner = hie.participant_in_conformance_testing(
            legal_name="Arborglen Regional Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=72000,
            primary_contact_email="hie@arborglen.example",
        )
        left_record = hie.contribute_record(
            left_owner["id"],
            headers=hie.admin,
            source_mrn="A-5001",
            given_name="Maria",
            family_name="Gonzalez",
            birth_date="1991-07-22",
            sex="F",
            ssn_last4="3321",
            postal_code="78701",
            phone_digits="5125550143",
        )
        right_owner = hie.participant_in_conformance_testing(
            legal_name="Brackenridge Family Clinic",
            org_type="CLINIC",
            declared_annual_patient_volume=24000,
            primary_contact_email="hie@brackenridge.example",
        )
        right_record = hie.contribute_record(
            right_owner["id"],
            headers=hie.admin,
            source_mrn="R-6001",
            given_name="Mari",
            family_name="Gonzales",
            birth_date="1991-07-22",
            sex="F",
            ssn_last4="3321",
            postal_code="78701",
            phone_digits="2125550143",
        )
        # PRD 3.4: "The stored record is born with `match_state` `CLUSTERED`" and a
        # PROPOSED -> PENDING_REVIEW routing "mutates **no** cluster membership at
        # all", so the review band leaves the record's own state untouched.
        assert right_record["match_state"] == "CLUSTERED"

        link = hie.only_link_between(right_record["id"])
        assert link["match_score"] == pytest.approx(0.7700, abs=0.0001)
        assert link["threshold_config_id"] == generation["id"]

        pinned_version = hie.cluster_version(left_record["cluster_id"])
        validate_error(
            hie.client.record_steward_decision(
                tuner,
                link["id"],
                decision="CONFIRM",
                expected_cluster_version=pinned_version,
                review_note=self.REVIEW_NOTE,
            ),
            "ERR_SOD_STEWARD_IS_TUNER",
            403,
        )
        untouched = validate_success(hie.client.get_match_link(steward, link["id"]), 200)
        assert untouched["status"] == "PENDING_REVIEW"
        assert untouched["reviewed_by_user_id"] is None

        confirmed = validate_success(
            hie.client.record_steward_decision(
                steward,
                link["id"],
                decision="CONFIRM",
                expected_cluster_version=pinned_version,
                review_note=self.REVIEW_NOTE,
            ),
            200,
        )
        assert confirmed["status"] == "LINKED"
        assert confirmed["reviewed_by_user_id"] == self.STEWARD

        absorbed = hie.get_cluster(right_record["cluster_id"])
        assert absorbed["status"] == "MERGED_AWAY"
        assert absorbed["merged_into_cluster_id"] == left_record["cluster_id"]
