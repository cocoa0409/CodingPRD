"""Two timelines with opposite edge semantics.

The statewide consent timeline is half-open, so adjacency is legal. The emergency
cooldown interval is closed at both ends and keyed per clinician and cluster, so
the far endpoint still collides while a different clinician is free.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.factories import consent_policy_payload, patient_record_payload
from test_helpers.fixtures import HieHarness
from test_helpers.test_users import make_clinician_headers, make_privacy_officer_headers

POLICY_OFFICER = "privacy-policy-1"


class TestStatewidePolicyTimelineIsHalfOpen:
    """Overlap is refused; a successor starting at the exclusive edge is accepted."""

    def _officer(self):
        return make_privacy_officer_headers(POLICY_OFFICER)

    def test_overlapping_successor_is_refused_but_an_adjacent_one_supersedes_the_incumbent(
        self, hie: HieHarness
    ):
        """June is contested; 2026-07-01 is not, because the upper bound is exclusive.

        PRD 3.3: "Adjacency is explicitly permitted — a new generation whose
        `effective_from` is exactly an incumbent's `effective_until` does not
        overlap it and is accepted."

        PRD 3.3: "The activation then supersedes history: every policy whose
        `status` is `ACTIVE` and whose `effective_until` is non-null and at or
        before the newly activated policy's `effective_from` is moved
        `ACTIVE → SUPERSEDED`, each such row incrementing its own `version` by 1."

        Design: Difficulty/resource_temporal_overlap/statewide_consent_policy_timeline_rejects_overlap_but_accepts_adjacent_generation
        """
        officer = self._officer()
        incumbent_draft = validate_success(
            hie.client.draft_consent_policy(
                officer,
                **consent_policy_payload(
                    policy_version="SP-2026.A",
                    model="OPT_IN",
                    sensitive_categories_segmented=["BEHAVIORAL_HEALTH", "HIV"],
                    default_share_for_treatment=False,
                    effective_from="2026-01-01T00:00:00Z",
                    effective_until="2026-07-01T00:00:00Z",
                )
            ),
            201,
        )
        assert incumbent_draft["status"] == "DRAFT"
        incumbent = validate_success(
            hie.client.activate_consent_policy(officer, incumbent_draft["id"]), 200
        )
        assert incumbent["status"] == "ACTIVE"

        validate_error(
            hie.client.draft_consent_policy(
                officer,
                **consent_policy_payload(
                    policy_version="SP-2026.B",
                    model="OPT_OUT",
                    sensitive_categories_segmented=["BEHAVIORAL_HEALTH"],
                    default_share_for_treatment=True,
                    effective_from="2026-06-01T00:00:00Z",
                )
            ),
            "ERR_CONSENT_POLICY_INTERVAL_OVERLAP",
            409,
        )
        assert (
            len(
                validate_success(
                    hie.client.list_consent_policies(hie.privacy_officer, limit=100), 200
                )
            )
            == 1
        )

        adjacent_draft = validate_success(
            hie.client.draft_consent_policy(
                officer,
                **consent_policy_payload(
                    policy_version="SP-2026.C",
                    model="OPT_OUT",
                    sensitive_categories_segmented=["BEHAVIORAL_HEALTH", "HIV", "SUD"],
                    default_share_for_treatment=True,
                    effective_from="2026-07-01T00:00:00Z",
                )
            ),
            201,
        )
        assert adjacent_draft["status"] == "DRAFT"

        successor = validate_success(
            hie.client.activate_consent_policy(officer, adjacent_draft["id"]), 200
        )
        assert successor["status"] == "ACTIVE"
        assert successor["activated_by_user_id"] == POLICY_OFFICER

        assert (
            validate_success(
                hie.client.get_consent_policy(hie.privacy_officer, incumbent["id"]), 200
            )["status"]
            == "SUPERSEDED"
        )
        active = validate_success(
            hie.client.list_consent_policies(hie.privacy_officer, status="ACTIVE", limit=100),
            200,
        )
        assert [row["id"] for row in active] == [successor["id"]]

    def test_a_draft_incumbent_reserves_its_interval_and_is_not_superseded(
        self, hie: HieHarness
    ):
        """The overlap check spans DRAFT rows, while supersession touches only ACTIVE ones.

        PRD 3.3: "Drafting sets `status` to `DRAFT` and `directive_count` to 0, and
        immediately runs an interval-overlap check against every existing policy
        whose `status` is `DRAFT` or `ACTIVE`: any overlap of the half-open
        intervals is rejected with `ERR_CONSENT_POLICY_INTERVAL_OVERLAP`."

        PRD 3.3: "A policy with a null `effective_until` is never superseded this
        way."

        Design: Difficulty/resource_temporal_overlap/statewide_consent_policy_timeline_rejects_overlap_but_accepts_adjacent_generation
        """
        officer = self._officer()
        reserved = validate_success(
            hie.client.draft_consent_policy(
                officer,
                **consent_policy_payload(
                    policy_version="SP-2026.A",
                    effective_from="2026-01-01T00:00:00Z",
                    effective_until="2026-07-01T00:00:00Z",
                )
            ),
            201,
        )
        assert reserved["status"] == "DRAFT"

        validate_error(
            hie.client.draft_consent_policy(
                officer,
                **consent_policy_payload(
                    policy_version="SP-2026.B", effective_from="2026-06-01T00:00:00Z"
                )
            ),
            "ERR_CONSENT_POLICY_INTERVAL_OVERLAP",
            409,
        )

        open_ended_draft = validate_success(
            hie.client.draft_consent_policy(
                officer,
                **consent_policy_payload(
                    policy_version="SP-2026.C", effective_from="2026-07-01T00:00:00Z"
                )
            ),
            201,
        )
        open_ended = validate_success(
            hie.client.activate_consent_policy(officer, open_ended_draft["id"]), 200
        )
        assert open_ended["status"] == "ACTIVE"
        assert open_ended["effective_until"] is None

        assert (
            validate_success(
                hie.client.get_consent_policy(hie.privacy_officer, reserved["id"]), 200
            )["status"]
            == "DRAFT"
        )
        active = validate_success(
            hie.client.list_consent_policies(hie.privacy_officer, status="ACTIVE", limit=100),
            200,
        )
        assert [row["id"] for row in active] == [open_ended["id"]]


class TestBreakGlassCooldownIsClosedAndPerClinician:
    """Five hours of occupation, inclusive at the far end, keyed per clinician."""

    FIRST_CLINICIAN = "clin-t-1"
    SECOND_CLINICIAN = "clin-t-2"
    FIRST_RECORD = patient_record_payload(
        source_mrn="T-3001",
        given_name="Adaeze",
        family_name="Nwachukwu",
        birth_date="1968-01-27",
        sex="F",
        ssn_last4="2245",
        postal_code="19104",
        phone_digits="2155550133",
    )
    SECOND_RECORD = patient_record_payload(
        source_mrn="T-3002",
        given_name="Soren",
        family_name="Lindqvist",
        birth_date="1991-12-03",
        sex="M",
        ssn_last4="8871",
        postal_code="55401",
        phone_digits="6125550159",
    )
    TRIAGE_JUSTIFICATION = (
        "Multi-vehicle incident triage; unidentified casualties require immediate "
        "history retrieval."
    )
    SECOND_WAVE_JUSTIFICATION = (
        "Second casualty wave from the same incident; identity still unconfirmed and "
        "history needed now."
    )
    RELIEF_JUSTIFICATION = (
        "Relieving physician taking over triage; needs the same unidentified casualty "
        "history immediately."
    )
    COOLDOWN_ELAPSED_JUSTIFICATION = (
        "Cooldown elapsed and the casualty is still unidentified; reopening emergency "
        "access for continued care."
    )

    def _trauma_center_with_two_clusters(self, hie: HieHarness):
        hie.activate_threshold_config(
            headers=make_privacy_officer_headers("privacy-tuner-1"),
            config_label="REF-PROB-T",
            score_variant_mode="PROBABILISTIC_ONLY",
        )
        participant = hie.certified_participant(
            legal_name="Thornhill Regional Trauma Center",
            org_type="HOSPITAL",
            declared_annual_patient_volume=156000,
            primary_contact_email="hie@thornhill.example",
        )
        first = hie.contribute_record(
            participant["id"], headers=hie.admin, **self.FIRST_RECORD
        )
        second = hie.contribute_record(
            participant["id"], headers=hie.admin, **self.SECOND_RECORD
        )
        return participant, first, second

    def _open(self, hie: HieHarness, cluster_id, participant_id, clinician, justification):
        return hie.client.open_break_glass_access(
            make_clinician_headers(clinician),
            cluster_id=cluster_id,
            invoking_participant_id=participant_id,
            emergency_category="DISASTER",
            justification_text=justification,
        )

    def test_far_endpoint_of_the_cooldown_still_collides_while_a_second_clinician_is_free(
        self, hie: HieHarness
    ):
        """Exactly five hours after opening is inside the interval; one second later is not.

        PRD 3.8: "Each prior session defines an occupation interval for the pair
        `(cluster_id, invoking_clinician_user_id)` running from its `opened_at` to
        one hour after its `expires_at` — that is, five hours from opening in
        total."

        PRD 3.8: "The interval is **closed at both ends**: a re-invocation landing
        exactly at the far endpoint still collides."

        Design: Difficulty/resource_temporal_overlap/break_glass_cooldown_interval_is_closed_at_both_ends_and_scoped_per_clinician
        """
        participant, record, _second_record = self._trauma_center_with_two_clusters(hie)
        cluster_id = record["cluster_id"]

        assert hie.set_clock("2026-09-01T00:00:00Z").startswith("2026-09-01T00:00:00")
        first_session = validate_success(
            self._open(
                hie,
                cluster_id,
                participant["id"],
                self.FIRST_CLINICIAN,
                self.TRIAGE_JUSTIFICATION,
            ),
            201,
        )
        assert first_session["opened_at"].startswith("2026-09-01T00:00:00")
        assert first_session["expires_at"].startswith("2026-09-01T04:00:00")

        assert hie.set_clock("2026-09-01T05:00:00Z").startswith("2026-09-01T05:00:00")
        validate_error(
            self._open(
                hie,
                cluster_id,
                participant["id"],
                self.FIRST_CLINICIAN,
                self.SECOND_WAVE_JUSTIFICATION,
            ),
            "ERR_BREAK_GLASS_COOLDOWN_ACTIVE",
            409,
        )

        relief_session = validate_success(
            self._open(
                hie,
                cluster_id,
                participant["id"],
                self.SECOND_CLINICIAN,
                self.RELIEF_JUSTIFICATION,
            ),
            201,
        )
        assert relief_session["opened_at"].startswith("2026-09-01T05:00:00")
        assert relief_session["expires_at"].startswith("2026-09-01T09:00:00")

        assert hie.set_clock("2026-09-01T05:00:01Z").startswith("2026-09-01T05:00:01")
        reopened = validate_success(
            self._open(
                hie,
                cluster_id,
                participant["id"],
                self.FIRST_CLINICIAN,
                self.COOLDOWN_ELAPSED_JUSTIFICATION,
            ),
            201,
        )
        assert reopened["opened_at"].startswith("2026-09-01T05:00:01")
        assert reopened["expires_at"].startswith("2026-09-01T09:00:01")

        assert hie.get_break_glass(first_session["id"])["session_status"] == "EXPIRED"

        sessions = validate_success(
            hie.client.list_break_glass_accesses(
                hie.privacy_officer, cluster_id=cluster_id, limit=100
            ),
            200,
        )
        assert len(sessions) == 3

    def test_the_interval_survives_expiry_and_does_not_reach_a_second_cluster(
        self, hie: HieHarness
    ):
        """An EXPIRED session still blocks its own cluster and only its own cluster.

        PRD 3.8: "The interval survives expiry — an `EXPIRED` session still
        occupies its window for cooldown purposes."

        PRD 3.8: "If the logical clock falls inside any such interval for the same
        cluster and the same clinician, the new invocation is refused with
        `ERR_BREAK_GLASS_COOLDOWN_ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/break_glass_cooldown_interval_is_closed_at_both_ends_and_scoped_per_clinician
        """
        participant, record, other_record = self._trauma_center_with_two_clusters(hie)
        assert record["cluster_id"] != other_record["cluster_id"]

        hie.set_clock("2026-09-01T00:00:00Z")
        first_session = validate_success(
            self._open(
                hie,
                record["cluster_id"],
                participant["id"],
                self.FIRST_CLINICIAN,
                self.TRIAGE_JUSTIFICATION,
            ),
            201,
        )

        hie.set_clock("2026-09-01T04:00:01Z")
        assert hie.get_break_glass(first_session["id"])["session_status"] == "EXPIRED"

        validate_error(
            self._open(
                hie,
                record["cluster_id"],
                participant["id"],
                self.FIRST_CLINICIAN,
                self.SECOND_WAVE_JUSTIFICATION,
            ),
            "ERR_BREAK_GLASS_COOLDOWN_ACTIVE",
            409,
        )

        elsewhere = validate_success(
            self._open(
                hie,
                other_record["cluster_id"],
                participant["id"],
                self.FIRST_CLINICIAN,
                self.RELIEF_JUSTIFICATION,
            ),
            201,
        )
        assert elsewhere["cluster_id"] == other_record["cluster_id"]
        assert elsewhere["opened_at"].startswith("2026-09-01T04:00:01")
        assert elsewhere["session_status"] == "OPEN"
