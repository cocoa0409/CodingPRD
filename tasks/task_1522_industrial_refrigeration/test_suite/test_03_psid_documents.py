"""PSI document lifecycle: the review/reaffirm cycle, supersede on issue, and
the expected_system_version optimistic-concurrency guard."""
from test_helpers import (
    PSC,
    ApiErrorId,
    api_client,
    assert_timestamp_instant,
    create_psid_document,
    create_psid_document_payload,
    get_system,
    setup_facility_with_system,
    validate_error,
    validate_success,
)


class TestReviewCycleAndSupersede:

    def test_psid_review_cycle_reaffirms_and_stamps(self):
        """PRD section 3.5: "Between issuances, a `PsCoordinator` may open a
        review, moving `CURRENT` to `UNDER_REVIEW`, and later reaffirm the
        document, returning `UNDER_REVIEW` to `CURRENT` and stamping
        `last_reaffirmed_at` from the logical clock (it stays null until the
        first reaffirmation)."
        PRD section 2.5: "At startup, before any call, the clock reads exactly
        2026-08-01T00:00:00Z."

        Design: Difficulty/non_linear_state_machine/psid_document_review_cycle_and_supersede
        """
        facility, system = setup_facility_with_system()
        doc = create_psid_document(system["id"], doc_type="PID",
                                   revision_label="Rev A",
                                   content_uri="s3://docs/pid-rev-a.pdf")
        assert doc["status"] == "CURRENT"
        assert doc.get("last_reaffirmed_at") is None

        reviewed = validate_success(
            api_client.start_psid_review(doc["id"], PSC), expected_status=200)
        assert reviewed["status"] == "UNDER_REVIEW"

        reaffirmed = validate_success(
            api_client.reaffirm_psid_document(doc["id"], PSC), expected_status=200)
        assert reaffirmed["status"] == "CURRENT"
        # no clock call in this scenario: the startup clock applies
        assert_timestamp_instant(reaffirmed["last_reaffirmed_at"],
                                 "2026-08-01T00:00:00Z")

    def test_psid_issue_supersedes_prior_and_bumps_version(self):
        """PRD section 3.5: "The new document issues directly as `CURRENT`; any
        prior document for the same system-and-type pair standing `CURRENT` or
        `UNDER_REVIEW` is automatically moved to `SUPERSEDED` in the same
        operation, preserving exactly one `CURRENT` document per pair, and the
        system's `version` increments by one."

        Design: Difficulty/non_linear_state_machine/psid_document_review_cycle_and_supersede
        """
        facility, system = setup_facility_with_system()
        version_at_create = system["version"]
        doc1 = create_psid_document(system["id"], doc_type="PID",
                                    revision_label="Rev A",
                                    content_uri="s3://docs/pid-rev-a.pdf")
        # complete the review cycle before the superseding issue
        validate_success(api_client.start_psid_review(doc1["id"], PSC), 200)
        validate_success(api_client.reaffirm_psid_document(doc1["id"], PSC), 200)

        doc2 = create_psid_document(system["id"], doc_type="PID",
                                    revision_label="Rev B",
                                    content_uri="s3://docs/pid-rev-b.pdf")
        assert doc2["status"] == "CURRENT"
        doc1_after = validate_success(api_client.get_psid_document(doc1["id"], PSC),
                                      expected_status=200)
        assert doc1_after["status"] == "SUPERSEDED"
        system_after = get_system(system["id"], PSC)
        # one increment per document issue (two issues here)
        assert system_after["version"] == version_at_create + 2


class TestReaffirmInvalidState:

    def test_reaffirm_current_document_rejected(self):
        """PRD section 3.5: "Between issuances, a `PsCoordinator` may open a
        review, moving `CURRENT` to `UNDER_REVIEW`, and later reaffirm the
        document, returning `UNDER_REVIEW` to `CURRENT` and stamping
        `last_reaffirmed_at` from the logical clock (it stays null until the
        first reaffirmation)."
        PRD section 2.9: "Source-state validity fifth: the target stands in a
        state that permits the requested transition — issuance only from
        `REQUESTED`, permit closure only from `IN_PROGRESS`, investigator
        assignment only from `REPORTED` or `REOPENED`, leak confirmation only
        from `SUSPECTED`, and so on (`ERR_INVALID_STATE`, 409)."

        Design: Corner/state_machines/reaffirm_current_document_rejected
        """
        facility, system = setup_facility_with_system()
        doc = create_psid_document(system["id"], doc_type="PID",
                                   revision_label="Rev A",
                                   content_uri="s3://docs/pid-rev-a.pdf")
        assert doc["status"] == "CURRENT"
        resp = api_client.reaffirm_psid_document(doc["id"], PSC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api_client.get_psid_document(doc["id"], PSC),
                                 expected_status=200)
        assert after["status"] == "CURRENT"
        assert after.get("last_reaffirmed_at") is None


class TestPsidOcc:

    def test_occ_psid_issue_stale_version_rejected(self):
        """PRD section 2.8: "Issuing a new PSI document requires the request to
        carry `expected_system_version`, the refrigeration system's version the
        client last observed. A mismatch with the system's current `version` is
        likewise rejected with `ERR_STALE_VERSION` (412)."

        Design: Corner/complexity_layers/occ_psid_issue_stale_version_rejected
        """
        facility, system = setup_facility_with_system()
        stale_version = system["version"]
        doc1 = create_psid_document(system["id"], doc_type="PID",
                                    revision_label="Rev A",
                                    content_uri="s3://docs/pid-rev-a.pdf")
        # Rev A's issue advanced the system version; the stale token must fail
        resp = api_client.create_psid_document(
            create_psid_document_payload(
                system["id"], stale_version, doc_type="PID",
                revision_label="Rev B", content_uri="s3://docs/pid-rev-b.pdf"),
            PSC)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        doc1_after = validate_success(api_client.get_psid_document(doc1["id"], PSC),
                                      expected_status=200)
        assert doc1_after["status"] == "CURRENT", \
            "Rev A must remain the only CURRENT PID document for the system"

    def test_occ_psid_issue_fresh_version_succeeds(self):
        """PRD section 2.8: "Issuing a new PSI document requires the request to
        carry `expected_system_version`, the refrigeration system's version the
        client last observed. A mismatch with the system's current `version` is
        likewise rejected with `ERR_STALE_VERSION` (412)."
        PRD section 3.5: "The new document issues directly as `CURRENT`; any
        prior document for the same system-and-type pair standing `CURRENT` or
        `UNDER_REVIEW` is automatically moved to `SUPERSEDED` in the same
        operation, preserving exactly one `CURRENT` document per pair, and the
        system's `version` increments by one."

        Design: Corner/complexity_layers/occ_psid_issue_fresh_version_succeeds
        """
        facility, system = setup_facility_with_system()
        doc1 = create_psid_document(system["id"], doc_type="PID",
                                    revision_label="Rev A",
                                    content_uri="s3://docs/pid-rev-a.pdf")
        fresh_version = get_system(system["id"], PSC)["version"]
        resp = api_client.create_psid_document(
            create_psid_document_payload(
                system["id"], fresh_version, doc_type="PID",
                revision_label="Rev B", content_uri="s3://docs/pid-rev-b.pdf"),
            PSC)
        doc2 = validate_success(resp, expected_status=201)
        assert doc2["status"] == "CURRENT"
        doc1_after = validate_success(api_client.get_psid_document(doc1["id"], PSC),
                                      expected_status=200)
        assert doc1_after["status"] == "SUPERSEDED"
        system_after = get_system(system["id"], PSC)
        assert system_after["version"] == fresh_version + 1
