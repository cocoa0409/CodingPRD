"""Error-catalogue reachability: every code the contract names is provably distinct.

The exchange's error vocabulary is only meaningful if each code is reachable on
its own terms. These cases drive the not-found family, the governance-activation
gates, the directive coherence rules, the data-contribution gates, the
authorization ladder and the review-claim separation, each through the narrowest
request that can produce it.
"""

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
)


def _testing_participant(hie: HieHarness, legal_name: str, email: str, **overrides):
    """A participant parked at CONFORMANCE_TESTING, ready to contribute data."""
    overrides.setdefault("org_type", "HOSPITAL")
    overrides.setdefault("declared_annual_patient_volume", 60000)
    return hie.participant_in_conformance_testing(
        legal_name=legal_name, primary_contact_email=email, **overrides
    )


class TestTheNotFoundFamilyIsNotCollapsed:
    """Twelve reads on an empty store must name twelve different entity families."""

    def test_each_entity_family_answers_with_its_own_not_found_code(self, hie: HieHarness):
        """Every read of an unknown id names its own family, all at HTTP 404.

        PRD 2.7: "Each entity family has its own not-found code:
        `ERR_PARTICIPANT_NOT_FOUND`, `ERR_CONFORMANCE_TEST_NOT_FOUND`,
        `ERR_CONSENT_POLICY_NOT_FOUND`, `ERR_THRESHOLD_CONFIG_NOT_FOUND`,
        `ERR_PATIENT_RECORD_NOT_FOUND`, `ERR_CLUSTER_NOT_FOUND`,
        `ERR_MATCH_LINK_NOT_FOUND`, `ERR_DIRECTIVE_NOT_FOUND`,
        `ERR_QUERY_NOT_FOUND`, `ERR_AUDIT_ENTRY_NOT_FOUND`,
        `ERR_BREAK_GLASS_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`,
        `ERR_DATA_FEED_NOT_FOUND` and `ERR_INVOICE_NOT_FOUND`, all HTTP 404."

        PRD 2.9: "A path identifier that resolves to nothing, on any endpoint
        carrying a path id — the family-specific not-found code from §2.7."

        Design: Corner/Errors/every_not_found_error_in_the_catalog_is_reachable_by_an_unknown_id
        """
        admin = hie.admin
        officer = hie.privacy_officer
        expected = [
            (hie.client.get_conformance_test(admin, NON_EXISTENT_UUID),
             "ERR_CONFORMANCE_TEST_NOT_FOUND"),
            (hie.client.get_match_threshold_config(admin, NON_EXISTENT_UUID),
             "ERR_THRESHOLD_CONFIG_NOT_FOUND"),
            (hie.client.get_patient_record(admin, NON_EXISTENT_UUID),
             "ERR_PATIENT_RECORD_NOT_FOUND"),
            (hie.client.get_identity_cluster(admin, NON_EXISTENT_UUID),
             "ERR_CLUSTER_NOT_FOUND"),
            (hie.client.get_match_link(admin, NON_EXISTENT_UUID),
             "ERR_MATCH_LINK_NOT_FOUND"),
            (hie.client.get_consent_directive(officer, NON_EXISTENT_UUID),
             "ERR_DIRECTIVE_NOT_FOUND"),
            (hie.client.get_record_locator_query(officer, NON_EXISTENT_UUID),
             "ERR_QUERY_NOT_FOUND"),
            (hie.client.get_access_audit_entry(officer, NON_EXISTENT_UUID),
             "ERR_AUDIT_ENTRY_NOT_FOUND"),
            (hie.client.get_break_glass_access(officer, NON_EXISTENT_UUID),
             "ERR_BREAK_GLASS_NOT_FOUND"),
            (hie.client.get_notification_subscription(admin, NON_EXISTENT_UUID),
             "ERR_SUBSCRIPTION_NOT_FOUND"),
            (hie.client.get_data_feed(admin, NON_EXISTENT_UUID),
             "ERR_DATA_FEED_NOT_FOUND"),
            (hie.client.get_participation_invoice(admin, NON_EXISTENT_UUID),
             "ERR_INVOICE_NOT_FOUND"),
        ]
        for response, error_id in expected:
            validate_error(response, error_id, 404)
        assert len({error_id for _, error_id in expected}) == 12


class TestGovernanceMustBeActiveNotMerelyDrafted:
    """A drafted generation governs nothing; activation is what switches it on."""

    TUNER = "privacy-tuner-1"
    POLICY_OFFICER = "privacy-policy-1"

    def test_activation_is_what_unblocks_contribution_and_directive_recording(
        self, hie: HieHarness
    ):
        """Both governance gates refuse a DRAFT generation and pass once it is ACTIVE.

        PRD 3.4: "If no generation is `ACTIVE`, the whole contribution is refused
        with `ERR_NO_ACTIVE_THRESHOLD_CONFIG`."

        PRD 3.6: "There must also be a consent policy generation currently `ACTIVE`
        and governing the logical clock, failing which the recording is refused
        with `ERR_NO_ACTIVE_CONSENT_POLICY`."

        Design: Corner/Errors/governance_generations_must_be_active_not_merely_drafted
        """
        tuner = make_privacy_officer_headers(self.TUNER)
        policy_officer = make_privacy_officer_headers(self.POLICY_OFFICER)

        draft_config = hie.draft_threshold_config(config_label="G1-DRAFT-ONLY", headers=tuner)
        assert draft_config["status"] == "DRAFT"
        draft_policy = hie.draft_consent_policy(
            policy_version="G1-DRAFT-ONLY",
            model="OPT_OUT",
            sensitive_categories_segmented=["BEHAVIORAL_HEALTH"],
            default_share_for_treatment=True,
            effective_from="2026-01-01T00:00:00Z",
            headers=policy_officer,
        )
        assert draft_policy["status"] == "DRAFT"

        participant = _testing_participant(
            hie, "Oakhurst Valley Hospital", "hie@oakhurst.example"
        )
        contribution = dict(
            source_mrn="G1-0001",
            given_name="Prudence",
            family_name="Nakamura",
            birth_date="1966-09-12",
            sex="F",
            ssn_last4="2277",
            postal_code="98104",
            phone_digits="2065550163",
        )
        validate_error(
            hie.client.contribute_patient_record(hie.admin, participant["id"], **contribution),
            "ERR_NO_ACTIVE_THRESHOLD_CONFIG",
            409,
        )

        activated_config = validate_success(
            hie.client.activate_match_threshold_config(tuner, draft_config["id"]), 200
        )
        assert activated_config["status"] == "ACTIVE"

        record = get_success_data(
            hie.client.contribute_patient_record(hie.admin, participant["id"], **contribution)
        )
        cluster_id = record["cluster_id"]
        cluster_version = hie.cluster_version(cluster_id)

        validate_error(
            hie.client.record_consent_directive(
                policy_officer,
                cluster_id,
                directive_type="OPT_OUT",
                scope="ALL_PARTICIPANTS",
                expected_cluster_version=cluster_version,
            ),
            "ERR_NO_ACTIVE_CONSENT_POLICY",
            409,
        )

        activated_policy = validate_success(
            hie.client.activate_consent_policy(policy_officer, draft_policy["id"]), 200
        )
        assert activated_policy["status"] == "ACTIVE"

        directive = get_success_data(
            hie.client.record_consent_directive(
                policy_officer,
                cluster_id,
                directive_type="OPT_OUT",
                scope="ALL_PARTICIPANTS",
                expected_cluster_version=cluster_version,
            )
        )
        assert directive["status"] == "ACTIVE"
        assert directive["policy_id"] == draft_policy["id"]
        assert hie.get_cluster(cluster_id)["active_directive_count"] == 1


class TestDirectiveShapeCoherence:
    """All three coherence rules share one code, and a refusal writes nothing."""

    POLICY_OFFICER = "privacy-policy-1"

    def test_each_incoherent_shape_is_refused_and_leaves_the_version_reusable(
        self, hie: HieHarness
    ):
        """Three malformed shapes are refused, and the fourth reuses the same version.

        PRD 3.6: "Three coherence rules apply, and any of them failing yields
        `ERR_DIRECTIVE_SCOPE_PARTICIPANT_REQUIRED`: a `SINGLE_PARTICIPANT` scope
        requires a non-null `scoped_participant_id`; an `ALL_PARTICIPANTS` scope
        requires `scoped_participant_id` to be null; and a
        `SENSITIVE_CATEGORY_RESTRICTION` requires a non-empty
        `restricted_categories` list, whose members are drawn from
        `BEHAVIORAL_HEALTH`, `SUD`, `HIV`, `REPRODUCTIVE` and `GENETIC`."

        Design: Corner/Errors/directive_scope_shape_errors_are_each_reachable
        """
        officer = make_privacy_officer_headers(self.POLICY_OFFICER)
        hie.activate_consent_policy(
            policy_version="G2-POLICY-1",
            model="OPT_OUT",
            sensitive_categories_segmented=["BEHAVIORAL_HEALTH", "HIV"],
            default_share_for_treatment=True,
            effective_from="2026-01-01T00:00:00Z",
            headers=officer,
        )
        hie.activate_threshold_config(config_label="REF-PROB-G2")

        participant = _testing_participant(
            hie,
            "Pinecrest Regional Hospital",
            "hie@pinecrest.example",
            declared_annual_patient_volume=72000,
        )
        record = hie.contribute_record(
            participant["id"],
            headers=hie.admin,
            source_mrn="G2-0001",
            given_name="Quentin",
            family_name="Abernathy",
            birth_date="1958-12-05",
            sex="M",
            ssn_last4="8830",
            postal_code="37203",
            phone_digits="6155550154",
        )
        cluster_id = record["cluster_id"]
        pinned_version = hie.cluster_version(cluster_id)

        incoherent_shapes = [
            dict(directive_type="OPT_OUT", scope="SINGLE_PARTICIPANT"),
            dict(
                directive_type="OPT_OUT",
                scope="ALL_PARTICIPANTS",
                scoped_participant_id=participant["id"],
            ),
            dict(
                directive_type="SENSITIVE_CATEGORY_RESTRICTION",
                scope="ALL_PARTICIPANTS",
                restricted_categories=[],
            ),
        ]
        for shape in incoherent_shapes:
            validate_error(
                hie.client.record_consent_directive(
                    officer, cluster_id, expected_cluster_version=pinned_version, **shape
                ),
                "ERR_DIRECTIVE_SCOPE_PARTICIPANT_REQUIRED",
                422,
            )
            assert hie.cluster_version(cluster_id) == pinned_version

        directive = get_success_data(
            hie.client.record_consent_directive(
                officer,
                cluster_id,
                directive_type="OPT_OUT",
                scope="SINGLE_PARTICIPANT",
                scoped_participant_id=participant["id"],
                expected_cluster_version=pinned_version,
            )
        )
        assert directive["status"] == "ACTIVE"
        assert directive["scope"] == "SINGLE_PARTICIPANT"
        assert directive["scoped_participant_id"] == participant["id"]
        assert directive["recorded_by_user_id"] == self.POLICY_OFFICER


class TestContributionAndSchedulingGates:
    """The data-plane gates: onboarding depth, MRN uniqueness and passed profiles."""

    CONTRIBUTION = dict(
        source_mrn="SHARED-0001",
        given_name="Rosalind",
        family_name="Achterberg",
        birth_date="1977-06-08",
        sex="F",
        ssn_last4="6641",
        postal_code="53703",
        phone_digits="6085550137",
    )

    def test_each_gate_refuses_on_its_own_and_a_failed_profile_stays_re_attemptable(
        self, hie: HieHarness
    ):
        """An APPLIED contributor, a reused MRN and a passed profile are each refused.

        PRD 3.3: "Contribution is only open to a participant whose
        `onboarding_status` is `CONFORMANCE_TESTING` or `CERTIFIED`; anything else
        is rejected with `ERR_PARTICIPANT_NOT_ONBOARDED_FOR_DATA`."

        PRD 2.9: "A duplicate `(participant_id, source_mrn)` pair —
        `ERR_DUPLICATE_SOURCE_MRN`, on
        `POST /hie/participants/{id}/patient-records`."

        PRD 3.2: "A profile that already has a `PASSED` run for the same
        participant cannot be re-booked: the attempt is rejected with
        `ERR_CONFORMANCE_PROFILE_ALREADY_PASSED`."

        PRD 3.2: "A `FAILED` or `WAIVED` profile may always be re-attempted."

        Design: Corner/Errors/data_contribution_and_conformance_scheduling_gates_are_each_reachable
        """
        hie.activate_threshold_config(config_label="REF-PROB-G3")
        applicant = hie.register_participant(
            legal_name="Quarryhill Community Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=60000,
            primary_contact_email="hie@quarryhill.example",
        )
        assert applicant["onboarding_status"] == "APPLIED"

        tester = _testing_participant(
            hie, "Ravenswood General Hospital", "hie@ravenswood.example"
        )
        hie.pass_profile(tester["id"], "ADT_PUBLISHER")
        failed_run = hie.fail_profile(
            tester["id"], "DOCUMENT_SOURCE", assertions_total=200, assertions_passed=180
        )
        assert failed_run["status"] == "FAILED"

        validate_error(
            hie.client.contribute_patient_record(
                hie.admin, applicant["id"], **self.CONTRIBUTION
            ),
            "ERR_PARTICIPANT_NOT_ONBOARDED_FOR_DATA",
            409,
        )

        record = get_success_data(
            hie.client.contribute_patient_record(hie.admin, tester["id"], **self.CONTRIBUTION)
        )
        assert record["match_state"] == "CLUSTERED"

        validate_error(
            hie.client.contribute_patient_record(hie.admin, tester["id"], **self.CONTRIBUTION),
            "ERR_DUPLICATE_SOURCE_MRN",
            409,
        )
        validate_error(
            hie.client.schedule_conformance_test(
                hie.admin,
                tester["id"],
                profile="ADT_PUBLISHER",
                scheduled_start="2026-08-02T00:00:00Z",
                scheduled_end="2026-08-02T06:00:00Z",
            ),
            "ERR_CONFORMANCE_PROFILE_ALREADY_PASSED",
            409,
        )

        retry = get_success_data(
            hie.client.schedule_conformance_test(
                hie.admin,
                tester["id"],
                profile="DOCUMENT_SOURCE",
                scheduled_start="2026-08-02T00:00:00Z",
                scheduled_end="2026-08-02T06:00:00Z",
            )
        )
        assert retry["attempt_number"] == 2
        assert retry["status"] == "RUNNING"


class TestAuthorizationLadderBelowTheEndpointCheck:
    """Action, scope and purpose each refuse a caller the endpoint itself admits."""

    SIGNATORY = "admin-legal-1"
    CLINICIAN = "clin-g4-1"

    def test_action_scope_and_purpose_each_refuse_a_caller_the_endpoint_admits(
        self, hie: HieHarness
    ):
        """Three separate 403s, none of them reachable as a plain endpoint-role failure.

        PRD 2.9: "On the five multiplexed action endpoints (participant onboarding
        transitions, match-link steward decision, data-feed status transitions,
        subscription lifecycle transitions, invoice administrative transitions),
        the caller's role is not permitted for the specific action value requested
        — `ERR_ACTION_NOT_PERMITTED_FOR_ROLE`."

        PRD 2.3: "Where the acting role is one of the two entity-backed roles
        (`ParticipantAdmin`, `PublicHealthOfficer`) and `X-User-ID` does not equal
        the participant that owns the addressed resource — or does not equal the
        `querying_participant_id` / `invoking_participant_id` named in the payload
        — the request fails with `ERR_PARTICIPANT_SCOPE_VIOLATION` (HTTP 403)."

        PRD 2.3: "On a record locator query the `purpose_of_use` value must lie
        inside the set permitted for the caller's role: a `Clinician` may assert
        `TREATMENT` only; a `ParticipantAdmin` may assert `PAYMENT` or
        `OPERATIONS` only; a `PublicHealthOfficer` may assert `PUBLIC_HEALTH` or
        `TREATMENT` only."

        Design: Corner/Errors/action_scope_and_purpose_authorization_errors_are_each_reachable
        """
        applicant = hie.register_participant(
            legal_name="Saltmarsh Regional Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=60000,
            primary_contact_email="hie@saltmarsh.example",
        )
        tester = _testing_participant(
            hie,
            "Thistledown Medical Group",
            "hie@thistledown.example",
            org_type="CLINIC",
            declared_annual_patient_volume=30000,
        )

        validate_error(
            hie.client.transition_onboarding(
                make_hie_admin_headers(self.SIGNATORY),
                applicant["id"],
                action="SUBMIT_FOR_LEGAL_REVIEW",
            ),
            "ERR_ACTION_NOT_PERMITTED_FOR_ROLE",
            403,
        )
        validate_error(
            hie.client.contribute_patient_record(
                make_participant_admin_headers(applicant["id"]),
                tester["id"],
                source_mrn="G4-0001",
                given_name="Tobias",
                family_name="Lindqvist",
                birth_date="1988-01-19",
                sex="M",
                ssn_last4="4409",
                postal_code="55401",
                phone_digits="6125550118",
            ),
            "ERR_PARTICIPANT_SCOPE_VIOLATION",
            403,
        )
        validate_error(
            hie.client.submit_record_locator_query(
                make_clinician_headers(self.CLINICIAN),
                querying_participant_id=tester["id"],
                purpose_of_use="OPERATIONS",
                family_name="Lindqvist",
                given_name="Tobias",
                birth_date="1988-01-19",
            ),
            "ERR_PURPOSE_NOT_PERMITTED_FOR_ROLE",
            403,
        )

        assert hie.get_participant(applicant["id"])["onboarding_status"] == "APPLIED"


class TestOnlyTheClaimantDecidesTheReview:
    """The claim binds the review to one user identity, not to the role.""" 

    REVIEWER = "privacy-reviewer-1"
    OTHER_REVIEWER = "privacy-reviewer-2"
    CLINICIAN = "clin-g5-1"
    JUSTIFICATION = (
        "Cardiac arrest in the emergency department; implanted device and "
        "anticoagulant history needed."
    )
    REVIEW_NOTE = "Reviewed and appropriate"

    def test_a_second_officer_can_neither_decide_nor_reclaim_the_review(self, hie: HieHarness):
        """Same role, different user: both the decision and the re-claim are refused.

        PRD 3.8: "The claim requires that `X-User-ID` differ from
        `invoking_clinician_user_id`, and a claim attempted on a session whose
        `review_claimed_by_user_id` is already set to another user is refused with
        `ERR_REVIEW_NOT_CLAIMED_BY_ACTOR`."

        PRD 3.8: "Only the claimant may decide: an acting `X-User-ID` other than
        `review_claimed_by_user_id` is refused with
        `ERR_REVIEW_NOT_CLAIMED_BY_ACTOR`."

        Design: Corner/Errors/review_decision_belongs_to_the_officer_who_claimed_it
        """
        hie.activate_threshold_config(config_label="REF-PROB-G5")
        participant = hie.certified_participant(
            legal_name="Umberfield Medical Center",
            org_type="HOSPITAL",
            declared_annual_patient_volume=84000,
            primary_contact_email="hie@umberfield.example",
        )
        record = hie.contribute_record(
            participant["id"],
            headers=hie.admin,
            source_mrn="G5-0001",
            given_name="Verity",
            family_name="Osei",
            birth_date="1969-08-24",
            sex="F",
            ssn_last4="3376",
            postal_code="21201",
            phone_digits="4105550149",
        )

        session = hie.open_break_glass(
            record["cluster_id"],
            participant["id"],
            emergency_category="LIFE_THREATENING",
            justification_text=self.JUSTIFICATION,
            clinician_user_id=self.CLINICIAN,
        )
        assert session["session_status"] == "OPEN"
        assert session["review_status"] == "PENDING_REVIEW"

        claimed = validate_success(
            hie.client.claim_break_glass_review(
                make_privacy_officer_headers(self.REVIEWER), session["id"]
            ),
            200,
        )
        assert claimed["review_claimed_by_user_id"] == self.REVIEWER
        assert claimed["review_status"] == "UNDER_REVIEW"

        intruder = make_privacy_officer_headers(self.OTHER_REVIEWER)
        validate_error(
            hie.client.decide_break_glass_review(
                intruder, session["id"], outcome="JUSTIFIED", review_note=self.REVIEW_NOTE
            ),
            "ERR_REVIEW_NOT_CLAIMED_BY_ACTOR",
            403,
        )
        validate_error(
            hie.client.claim_break_glass_review(intruder, session["id"]),
            "ERR_REVIEW_NOT_CLAIMED_BY_ACTOR",
            403,
        )

        decided = validate_success(
            hie.client.decide_break_glass_review(
                make_privacy_officer_headers(self.REVIEWER),
                session["id"],
                outcome="JUSTIFIED",
                review_note=self.REVIEW_NOTE,
            ),
            200,
        )
        assert decided["review_status"] == "JUSTIFIED"
        assert decided["reviewer_user_id"] == self.REVIEWER
        assert decided["sanction_points_awarded"] == 0
        assert decided["decided_at"].startswith("2026-08-01T00:00:00")
