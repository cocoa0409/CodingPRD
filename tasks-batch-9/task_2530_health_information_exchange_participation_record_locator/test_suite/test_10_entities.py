"""Entity surface: creation, retrieval, listing, defaults and server-owned fields.

These tests exercise the declared shape of the entity families rather than their
workflows: which fields the server mints, which inputs it ignores, what a list
read reports in its `meta` block, and which families are immutable once written.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_created_at,
    assert_full_quartet,
    assert_immutable_shape,
    assert_uuid_id,
)
from test_helpers.factories import participant_payload, patient_record_payload
from test_helpers.fixtures import HieHarness
from test_helpers.test_users import make_privacy_officer_headers

ASHFORD = participant_payload(
    legal_name="Ashford General Hospital",
    org_type="HOSPITAL",
    declared_annual_patient_volume=360012,
    primary_contact_email="hie@ashford.example",
)


class TestParticipantEntitySurface:
    """The registration response, the read-back and the list read."""

    def test_registration_returns_201_in_the_success_envelope_with_every_declared_field(
        self, hie: HieHarness
    ):
        """A created participant comes back wrapped, with all counters at their floor.

        PRD 2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        PRD 2.4: "Creating a new resource returns HTTP 201; every other successful
        operation, including all state transitions and all reads, returns HTTP 200."

        PRD 3.1: "The new organization is born with `onboarding_status` at
        `APPLIED`, `version` at 1, and every derived counter at its floor:
        `sanction_points_active`, `outstanding_balance_cents`,
        `active_subscription_count`, `conformance_attempt_count`,
        `consecutive_failed_attempts` and `remediation_count` all zero, and
        `passed_profiles` an empty list."

        Design: Corner/Entities/participant_creation_returns_applied_with_provisional_fee_and_success_envelope
        """
        response = hie.client.register_participant(hie.admin, **ASHFORD)
        assert response.status_code == 201
        body = response.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"]
        assert isinstance(body["meta"]["api_request_timestamp"], str)

        participant = body["data"]
        assert_full_quartet(participant, expected_version=1)
        assert participant["legal_name"] == "Ashford General Hospital"
        assert participant["org_type"] == "HOSPITAL"
        assert participant["declared_annual_patient_volume"] == 360012
        assert participant["primary_contact_email"] == "hie@ashford.example"
        assert participant["onboarding_status"] == "APPLIED"
        assert participant["sanction_points_active"] == 0
        assert participant["outstanding_balance_cents"] == 0
        assert participant["active_subscription_count"] == 0
        assert participant["conformance_attempt_count"] == 0
        assert participant["consecutive_failed_attempts"] == 0
        assert participant["remediation_count"] == 0
        assert participant["passed_profiles"] == []
        assert participant["quality_score"] is None
        assert participant["quality_grade"] == "UNGRADED"
        assert participant["provisional_monthly_fee_cents"] == 299877
        assert participant["fee_tier"] == "TIER_2"

    def test_reading_the_participant_back_returns_the_stored_row_without_mutating_it(
        self, hie: HieHarness
    ):
        """A read is not a mutation: same id, same computed fee, same version.

        PRD 3.1: "Participants are individually readable, and the participant list
        is filterable by `onboarding_status`, by `org_type` and by `fee_tier`."

        PRD 2.4: "`version`, an integer that starts at 1 when the resource is
        created and increments by exactly 1 on every mutation of that resource,
        including mutations caused by a cascade the caller did not directly
        request."

        Design: Corner/Entities/participant_retrieval_returns_the_stored_row_unchanged
        """
        created = hie.register_participant(**ASHFORD)

        response = hie.client.get_participant(hie.admin, created["id"])
        assert response.status_code == 200
        stored = validate_success(response, 200)
        assert stored["id"] == created["id"]
        assert stored["legal_name"] == "Ashford General Hospital"
        assert stored["provisional_monthly_fee_cents"] == 299877
        assert stored["version"] == 1
        assert stored["onboarding_status"] == "APPLIED"

        again = validate_success(hie.client.get_participant(hie.admin, created["id"]), 200)
        assert again["version"] == 1

    def test_the_participant_list_reports_its_pagination_block_and_narrows_by_org_type(
        self, hie: HieHarness
    ):
        """Three rows oldest-first, then one row once the org_type filter applies.

        PRD 2.3: "The `meta` block of a list response carries `limit`, `offset`,
        `total_count` (the number of rows matching the filter before pagination)
        and `has_more` (true when `offset` plus the number of returned rows is
        less than `total_count`)."

        PRD 2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100;
        `offset` defaults to 0 and has a minimum of 0."

        PRD 3.1: "Participants are individually readable, and the participant list
        is filterable by `onboarding_status`, by `org_type` and by `fee_tier`."

        Design: Corner/Entities/participant_listing_returns_pagination_fields_and_org_type_filter
        """
        first = hie.register_participant(**ASHFORD)
        hie.register_participant(
            legal_name="Brightwater Community Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=96000,
            primary_contact_email="hie@brightwater.example",
        )
        lab = hie.register_participant(
            legal_name="Calder Reference Laboratory",
            org_type="LAB",
            declared_annual_patient_volume=12000,
            primary_contact_email="hie@calderlab.example",
        )

        rows, meta = validate_paginated(hie.client.list_participants(hie.admin))
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(rows) == 3
        assert rows[0]["id"] == first["id"]
        assert rows[2]["id"] == lab["id"]

        labs, lab_meta = validate_paginated(
            hie.client.list_participants(hie.admin, org_type="LAB")
        )
        assert lab_meta["total_count"] == 1
        assert lab_meta["has_more"] is False
        assert [row["id"] for row in labs] == [lab["id"]]
        assert labs[0]["org_type"] == "LAB"

    def test_an_unknown_participant_id_returns_the_participant_not_found_error(
        self, hie: HieHarness
    ):
        """A well-formed but unused UUID is a 404 in the error envelope, not an empty 200.

        PRD 2.7: "Each entity family has its own not-found code:
        `ERR_PARTICIPANT_NOT_FOUND`, `ERR_CONFORMANCE_TEST_NOT_FOUND`,
        `ERR_CONSENT_POLICY_NOT_FOUND`, `ERR_THRESHOLD_CONFIG_NOT_FOUND`,
        `ERR_PATIENT_RECORD_NOT_FOUND`, `ERR_CLUSTER_NOT_FOUND`,
        `ERR_MATCH_LINK_NOT_FOUND`, `ERR_DIRECTIVE_NOT_FOUND`,
        `ERR_QUERY_NOT_FOUND`, `ERR_AUDIT_ENTRY_NOT_FOUND`,
        `ERR_BREAK_GLASS_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`,
        `ERR_DATA_FEED_NOT_FOUND` and `ERR_INVOICE_NOT_FOUND`, all HTTP 404."

        PRD 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/Entities/participant_read_with_unknown_id_returns_participant_not_found
        """
        response = hie.client.get_participant(hie.admin, NON_EXISTENT_UUID)
        validate_error(response, "ERR_PARTICIPANT_NOT_FOUND", 404)
        body = response.json()
        assert body["response_type"] == "error"
        assert sorted(body["meta"]) == ["api_request_id", "api_request_timestamp"]


class TestServerOwnedAndClientOwnedFields:
    """What the caller must supply, what it may omit, and what it may not dictate."""

    TUNER = "privacy-tuner-1"

    def _contributor(self, hie: HieHarness, **overrides):
        """One participant cleared to contribute, under an ACTIVE tuning generation."""
        hie.activate_threshold_config(
            config_label="REF-PROB-E5",
            score_variant_mode="PROBABILISTIC_ONLY",
            headers=make_privacy_officer_headers(self.TUNER),
        )
        return hie.participant_in_conformance_testing(**overrides)

    def test_a_contribution_without_a_birth_date_is_refused_before_any_matching_work(
        self, hie: HieHarness
    ):
        """`birth_date` is required, so the record, its cluster and its links are never written.

        PRD 3.4: "The contribution payload carries the contributor's local
        `source_mrn`, which must be unique within that contributor — a second
        record with the same `(participant_id, source_mrn)` pair is refused with
        `ERR_DUPLICATE_SOURCE_MRN` — together with the demographic fields the
        matching algorithm consumes: `given_name`, `family_name`, `birth_date` as
        an ISO 8601 calendar date in year-month-day form, and `sex` from `M`, `F`,
        `O` or `U`."

        PRD 2.9: "Schema faults on any write endpoint — `ERR_INVALID_REQUEST`.
        This covers a missing required field, a wrong JSON type, an enum value
        outside its declared domain, a numeric field outside its declared range"

        Design: Corner/Entities/patient_record_without_birth_date_returns_invalid_request
        """
        participant = self._contributor(
            hie,
            legal_name="Ellingham Street Clinic",
            org_type="CLINIC",
            declared_annual_patient_volume=24000,
            primary_contact_email="hie@ellingham.example",
        )

        response = hie.client.contribute_patient_record(
            hie.admin,
            participant["id"],
            source_mrn="E5-0001",
            given_name="Nadia",
            family_name="Whitlock",
            sex="F",
            ssn_last4="1102",
            postal_code="02139",
            phone_digits="6175550101",
        )
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        rows, meta = validate_paginated(
            hie.client.list_patient_records(hie.admin, participant_id=participant["id"])
        )
        assert meta["total_count"] == 0
        assert rows == []
        _, cluster_meta = validate_paginated(hie.client.list_identity_clusters(hie.admin))
        assert cluster_meta["total_count"] == 0

    def test_a_policy_that_omits_effective_until_is_stored_as_an_open_ended_draft(
        self, hie: HieHarness
    ):
        """The one optional input defaults to null while the system fields take their floors.

        PRD 3.3: "A null `effective_until` means the generation is open-ended.
        Drafting sets `status` to `DRAFT` and `directive_count` to 0, and
        immediately runs an interval-overlap check against every existing policy
        whose `status` is `DRAFT` or `ACTIVE`: any overlap of the half-open
        intervals is rejected with `ERR_CONSENT_POLICY_INTERVAL_OVERLAP`."

        PRD 3.3: "Activating a draft policy moves it `DRAFT → ACTIVE`, records the
        acting `X-User-ID` as `activated_by_user_id`, and re-runs the overlap test
        against the currently `ACTIVE` set, again rejecting with
        `ERR_CONSENT_POLICY_INTERVAL_OVERLAP`."

        Design: Corner/Entities/consent_policy_omitting_effective_until_defaults_to_open_ended_draft
        """
        response = hie.client.draft_consent_policy(
            make_privacy_officer_headers("privacy-policy-1"),
            policy_version="SP-2026.D",
            model="OPT_IN",
            sensitive_categories_segmented=["BEHAVIORAL_HEALTH", "HIV"],
            default_share_for_treatment=False,
            effective_from="2026-01-01T00:00:00Z",
        )
        assert response.status_code == 201
        policy = validate_success(response, 201)
        assert policy["effective_until"] is None
        assert policy["status"] == "DRAFT"
        assert policy["directive_count"] == 0
        assert policy["activated_by_user_id"] is None
        assert policy["default_share_for_treatment"] is False
        assert_full_quartet(policy, expected_version=1)

    def test_client_supplied_computed_fields_on_a_contribution_are_ignored(
        self, hie: HieHarness
    ):
        """The server recomputes completeness, state and cluster, whatever the caller sent.

        PRD 3.4: "The stored record is born with `match_state` `CLUSTERED` — the
        other two states, `QUARANTINED` and `WITHDRAWN_FROM_INDEX`, are reached
        only through the withdrawal machinery of §3.9 — and with a
        `completeness_score` equal to the count of non-null values among exactly
        six fields: `given_name`, `family_name`, `birth_date`, `ssn_last4`,
        `postal_code` and `phone_digits`."

        PRD 3.4: "The server then mints a fresh identity cluster in `ACTIVE`
        status holding this record alone, points the record's `cluster_id` at it,
        leaves `prior_cluster_id` null, and runs the membership recount described
        at the end of this subsection over that new cluster."

        Design: Corner/Entities/patient_record_computed_fields_recomputed_and_client_values_input_ignored
        """
        participant = self._contributor(
            hie,
            legal_name="Fairhaven Medical Associates",
            org_type="CLINIC",
            declared_annual_patient_volume=36000,
            primary_contact_email="hie@fairhaven.example",
        )

        response = hie.client.contribute_patient_record(
            hie.admin,
            participant["id"],
            completeness_score=99,
            match_state="QUARANTINED",
            cluster_id=NON_EXISTENT_UUID,
            **patient_record_payload(
                source_mrn="E7-0001",
                given_name="Nadia",
                family_name="Whitlock",
                birth_date="1990-02-11",
                sex="F",
                ssn_last4="1102",
                postal_code="02139",
                phone_digits="6175550101",
            ),
        )
        assert response.status_code == 201
        record = validate_success(response, 201)
        assert record["completeness_score"] == 6
        assert record["match_state"] == "CLUSTERED"
        assert record["cluster_id"] != NON_EXISTENT_UUID
        assert record["prior_cluster_id"] is None

        cluster = hie.get_cluster(record["cluster_id"])
        assert cluster["status"] == "ACTIVE"
        assert cluster["member_record_count"] == 1
        assert cluster["primary_record_id"] == record["id"]

    def test_client_supplied_system_fields_on_a_registration_are_ignored(
        self, hie: HieHarness
    ):
        """`id`, `created_at`, `updated_at` and `version` belong to the server.

        PRD 2.4: "Every persisted resource carries a server-minted `id` — a UUID
        with no type prefix of any kind — and a `created_at` timestamp in ISO 8601
        UTC form with exactly three fractional digits."

        PRD 2.5: "Before the clock has ever been set it reads exactly
        `2026-08-01T00:00:00Z`, and it never falls back to real time."

        Design: Corner/Entities/participant_system_fields_are_server_minted_and_client_values_input_ignored
        """
        response = hie.client.register_participant(
            hie.admin,
            legal_name="Glenmore Health Plan",
            org_type="HEALTH_PLAN",
            declared_annual_patient_volume=60000,
            primary_contact_email="hie@glenmore.example",
            id="11111111-1111-4111-8111-111111111111",
            version=77,
            created_at="2020-01-01T00:00:00.000Z",
            updated_at="2020-01-01T00:00:00.000Z",
        )
        assert response.status_code == 201
        participant = validate_success(response, 201)
        assert participant["id"] != "11111111-1111-4111-8111-111111111111"
        assert_uuid_id(participant)
        assert participant["version"] == 1
        assert_created_at(participant)
        assert participant["created_at"] == "2026-08-01T00:00:00.000Z"


class TestDeclaredDomainsAndParentResolution:
    """Values outside a declared domain, and paths whose parent does not exist."""

    def test_an_org_type_outside_its_domain_and_a_negative_volume_are_both_refused(
        self, hie: HieHarness
    ):
        """Neither request writes a row: `DENTIST` is not an org type and volume cannot be negative.

        PRD 3.1: "The registration payload carries the organization's registered
        `legal_name` (one to two hundred characters, non-blank), its `org_type` —
        one of `HOSPITAL`, `CLINIC`, `LAB`, `HEALTH_PLAN` or `PUBLIC_HEALTH` — a
        self-declared `declared_annual_patient_volume` (at least zero and at most
        fifty million unique patients per year), and a `primary_contact_email` for
        the onboarding mailbox, which must contain an `@` character."

        PRD 2.9: "Schema faults on any write endpoint — `ERR_INVALID_REQUEST`."

        Design: Corner/Entities/participant_org_type_outside_its_domain_returns_invalid_enum
        """
        validate_error(
            hie.client.register_participant(
                hie.admin,
                legal_name="Harlow Dental Group",
                org_type="DENTIST",
                declared_annual_patient_volume=12000,
                primary_contact_email="hie@harlow.example",
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            hie.client.register_participant(
                hie.admin,
                legal_name="Harlow Dental Group",
                org_type="CLINIC",
                declared_annual_patient_volume=-5,
                primary_contact_email="hie@harlow.example",
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        _, meta = validate_paginated(hie.client.list_participants(hie.admin))
        assert meta["total_count"] == 0

    def test_scheduling_a_conformance_run_under_an_unknown_participant_is_a_404(
        self, hie: HieHarness
    ):
        """The parent resolves before the profile or the schedule window is inspected.

        PRD 2.7: "Nested paths are resolved strictly left to right. For a path
        such as `/hie/participants/{id}/participation-invoices`, the participant is
        resolved first, and a participant id that does not exist yields
        `ERR_PARTICIPANT_NOT_FOUND` before any body field is inspected."

        Design: Corner/Entities/conformance_test_under_unknown_participant_returns_participant_not_found
        """
        validate_error(
            hie.client.schedule_conformance_test(
                hie.admin,
                NON_EXISTENT_UUID,
                profile="ADT_PUBLISHER",
                scheduled_start="2026-08-01T00:00:00Z",
                scheduled_end="2026-08-01T06:00:00Z",
            ),
            "ERR_PARTICIPANT_NOT_FOUND",
            404,
        )


class TestImmutableResourceFamilies:
    """A measurement window carries `id` and `created_at` and nothing else."""

    def test_a_quality_sample_exposes_only_id_and_created_at(self, hie: HieHarness):
        """No `version` and no `updated_at` on a row that can never be rewritten.

        PRD 2.4: "Three resource families are deliberately immutable once written
        and therefore carry only `id` and `created_at` — for them both `updated_at`
        and `version` are absent from the response entirely."

        PRD 2.8: "**Four decimal places, rounded half up**, governs everything the
        matching subsystem produces and consumes: `auto_link_threshold`,
        `review_lower_bound`, `partial_credit_factor`, the six field weights,
        `match_score`, `top_candidate_score`, a conformance run's `pass_rate`, a
        quality sample's `reject_rate`, and a data feed's `latest_reject_rate`."

        Design: Corner/Entities/feed_quality_sample_is_immutable_with_no_version_field
        """
        participant = hie.participant_in_conformance_testing(
            legal_name="Ironbridge Regional Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=72000,
            primary_contact_email="hie@ironbridge.example",
        )
        feed = hie.provision_feed(participant["id"], feed_type="ADT")
        sample = hie.record_sample(
            feed["id"],
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            messages_received=8000,
            messages_rejected=100,
            required_fields_missing_count=200,
            duplicate_count=50,
            timeliness_p95_seconds=250,
        )
        assert_immutable_shape(sample)
        assert sample["reject_rate"] == pytest.approx(0.0125, abs=0.0001)

        rows, meta = validate_paginated(
            hie.client.list_data_feed_quality_samples(hie.admin, feed["id"])
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == sample["id"]
        assert rows[0]["created_at"] == "2026-08-01T00:00:00.000Z"
        assert_immutable_shape(rows[0])


class TestMatchLinkJunctionTopology:
    """One junction row between two records, discoverable from either end."""

    TUNER = "privacy-tuner-1"
    LEFT_RECORD = patient_record_payload(
        source_mrn="E12-A1",
        given_name="Robert",
        family_name="Nguyen",
        birth_date="1979-04-12",
        sex="M",
        ssn_last4="4417",
        postal_code="94110",
        phone_digits="4155550111",
    )
    RIGHT_RECORD = patient_record_payload(
        source_mrn="E12-B1",
        given_name="Robert",
        family_name="Nguyen",
        birth_date="1979-04-12",
        sex="M",
        ssn_last4="4417",
        postal_code="02139",
        phone_digits="4155550111",
    )

    def test_an_auto_linked_pair_yields_one_link_reachable_from_both_records_and_the_cluster(
        self, hie: HieHarness
    ):
        """The same junction id comes back whether the filter names a record or the cluster.

        PRD 3.4: "Only cross-participant pairs are ever proposed."

        PRD 3.4: "Candidates are evaluated in ascending `created_at` order, and
        **every** candidate produces exactly one `MatchLink` row — links are the
        exchange's permanent record of both agreement and disagreement."

        PRD 3.4: "Links are readable individually and listable with filters on
        `left_record_id`, `right_record_id`, `threshold_config_id`, `cluster_id`,
        `merged_away_cluster_id` and `status`."

        Design: Corner/Entities/match_link_is_a_junction_row_reachable_from_both_records_and_the_cluster
        """
        hie.activate_threshold_config(
            config_label="REF-PROB-E12",
            score_variant_mode="PROBABILISTIC_ONLY",
            headers=make_privacy_officer_headers(self.TUNER),
        )
        left_participant = hie.participant_in_conformance_testing(
            legal_name="Juniper Falls Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=60000,
            primary_contact_email="hie@juniperfalls.example",
        )
        right_participant = hie.participant_in_conformance_testing(
            legal_name="Kingsbridge Family Clinic",
            org_type="CLINIC",
            declared_annual_patient_volume=24000,
            primary_contact_email="hie@kingsbridge.example",
        )

        left_record = hie.contribute_record(
            left_participant["id"], headers=hie.admin, **self.LEFT_RECORD
        )
        right_record = hie.contribute_record(
            right_participant["id"], headers=hie.admin, **self.RIGHT_RECORD
        )
        winner_cluster_id = left_record["cluster_id"]

        by_left, left_meta = validate_paginated(
            hie.client.list_match_links(
                hie.privacy_officer, left_record_id=left_record["id"]
            )
        )
        assert left_meta["total_count"] == 1
        link = by_left[0]
        assert link["match_score"] == pytest.approx(0.9200, abs=0.0001)
        assert link["status"] == "AUTO_LINKED"
        assert link["score_variant"] == "PROBABILISTIC"
        assert link["left_record_id"] == left_record["id"]
        assert link["right_record_id"] == right_record["id"]

        by_right, right_meta = validate_paginated(
            hie.client.list_match_links(
                hie.privacy_officer, right_record_id=right_record["id"]
            )
        )
        assert right_meta["total_count"] == 1
        assert by_right[0]["id"] == link["id"]

        by_cluster, cluster_meta = validate_paginated(
            hie.client.list_match_links(hie.privacy_officer, cluster_id=winner_cluster_id)
        )
        assert cluster_meta["total_count"] == 1
        assert by_cluster[0]["id"] == link["id"]
        assert by_cluster[0]["cluster_id"] == winner_cluster_id
