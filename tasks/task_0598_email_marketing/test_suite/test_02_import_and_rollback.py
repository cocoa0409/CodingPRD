"""Bulk import, its pinned per-row check order, and the compensating rollback."""
from test_helpers import (
    NON_EXISTENT_UUID,
    PLATFORM,
    ApiErrorId,
    add_subscriber,
    add_subscribers,
    advance_epoch_to,
    assert_import_row_conservation,
    audience_version,
    create_approved_campaign,
    create_audience,
    create_import_job_payload,
    create_published_template,
    import_rows,
    provision_tenant,
    read_audience,
    run_import,
    schedule_ok,
    unsubscribe,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestImportRowDisposition:
    def test_row_checks_run_format_then_suppression_then_duplicate(self, api):
        """PRD §3.3: "Second suppression: if the address matches a suppression entry of the
        audience's account, the row is counted into `suppressed_count` and skipped — suppression
        beats duplication, and an address that is both suppressed and already present on the list
        is reported as suppressed, not as a duplicate."
        PRD §3.3: "First format: if the row's address contains no `@` character, the row is
        counted into `rejected_count` and processing moves to the next row."
        PRD §3.3: "Third duplication: if the address was already accepted by an earlier row of
        this same job, or a subscriber with that address already exists in this audience in any
        `consent_state`, the row is counted into `duplicate_count` and skipped."

        Design: Corner/calculations/import_row_disposition_conserves_rows_and_prefers_suppression
        """
        tenant = provision_tenant(initial_send_credits=0)
        audience = create_audience(tenant, double_optin_required=False)
        add_subscriber(audience["id"], "x1@x.com", tenant.author_headers)
        suppressed = add_subscriber(audience["id"], "sup@x.com", tenant.author_headers)
        unsubscribe(suppressed)

        rows = ["bad-address", "sup@x.com", "x1@x.com", "n1@x.com", "n1@x.com", "n2@x.com"]
        job = validate_success(
            api.create_import_job(
                audience["id"],
                create_import_job_payload(import_rows(rows), audience_version(audience["id"])),
                tenant.author_headers,
            ),
            201,
        )

        assert job["row_count"] == 6
        assert job["accepted_count"] == 2, "n1@x.com (first occurrence) and n2@x.com"
        assert job["rejected_count"] == 1, "'bad-address' carries no '@'"
        assert job["duplicate_count"] == 2, "x1@x.com already exists; n1@x.com repeats in-batch"
        assert job["suppressed_count"] == 1, "sup@x.com is suppressed, not a duplicate"
        assert job["status"] == "PARTIAL"
        assert len(job["created_subscriber_ids"]) == 2
        assert_import_row_conservation(job)
        assert read_audience(audience["id"])["subscriber_count"] == 4

    def test_second_import_carrying_a_stale_audience_version_is_rejected(self, api):
        """PRD §2.6: "Creating an import job requires `expected_audience_version` in the request
        body, carrying the `version` of the target `Audience` as the client last read it. A
        mismatch with the audience's current `version` is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.3: "All three outcomes are successful requests that increment the audience's
        `version` by one; even a `REJECTED` job, which creates nothing and leaves
        `created_subscriber_ids` empty, still burns the version, so a client that retries after a
        rejection must re-read the audience first."

        Design: Corner/cross_cutting_layers/occ_stale_audience_version_on_import_returns_412
        """
        tenant = provision_tenant(initial_send_credits=0)
        audience = create_audience(tenant, double_optin_required=False)
        captured_version = audience["version"]

        first = validate_success(
            api.create_import_job(
                audience["id"],
                create_import_job_payload(import_rows(["i1@x.com", "i2@x.com"]), captured_version),
                tenant.author_headers,
            ),
            201,
        )
        assert first["status"] == "COMPLETED"

        resp = api.create_import_job(
            audience["id"],
            create_import_job_payload(import_rows(["i3@x.com", "i4@x.com"]), captured_version),
            tenant.author_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

        assert read_audience(audience["id"])["subscriber_count"] == 2, "i3/i4 were never created"
        jobs, _ = validate_paginated(api.list_import_jobs(audience["id"], tenant.author_headers))
        assert len(jobs) == 1


class TestImportRollback:
    def test_rollback_of_a_partial_import_restores_the_contact_counts(self, api):
        """PRD §3.3: "A successful rollback moves the job to `ROLLED_BACK` and archives exactly
        the rows the job created: every subscriber in `created_subscriber_ids` whose
        `consent_state` is not already `ARCHIVED` transitions to `ARCHIVED`, whether it currently
        sits in `PENDING`, `CONFIRMED` or `UNSUBSCRIBED`."
        PRD §3.3: "Because those contacts have left the counted set, the audience's
        `subscriber_count` is recomputed from its formula, and because that changed, the account's
        `billable_contact_count` is recomputed from its formula in turn — restoring the pre-import
        contact count."

        Design: Difficulty/compensating_invariant/contact_count_conservation_across_import_and_rollback
        """
        tenant = provision_tenant(initial_send_credits=0)
        audience = create_audience(tenant, double_optin_required=False)
        add_subscribers(audience["id"], ["s1@x.com", "s2@x.com"], tenant.author_headers)
        assert read_audience(audience["id"])["subscriber_count"] == 2

        job = run_import(
            audience["id"],
            ["e1@x.com", "e2@x.com", "e3@x.com", "s1@x.com"],
            tenant.author_headers,
        )
        assert job["accepted_count"] == 3
        assert job["duplicate_count"] == 1
        assert job["status"] == "PARTIAL"
        assert read_audience(audience["id"])["subscriber_count"] == 5

        rolled = validate_success(
            api.rollback_import_job(job["id"], tenant.author_headers)
        )
        assert rolled["status"] == "ROLLED_BACK"
        assert rolled["row_count"] == 4
        assert rolled["rejected_count"] == 0
        assert rolled["suppressed_count"] == 0

        assert read_audience(audience["id"])["subscriber_count"] == 2, "back to the pre-import value"
        assert tenant.refresh()["billable_contact_count"] == 2

    def test_rollback_archives_exactly_the_rows_the_job_created(self, api):
        """PRD §3.3: "A successful rollback moves the job to `ROLLED_BACK` and archives exactly
        the rows the job created: every subscriber in `created_subscriber_ids` whose
        `consent_state` is not already `ARCHIVED` transitions to `ARCHIVED`, whether it currently
        sits in `PENDING`, `CONFIRMED` or `UNSUBSCRIBED`."
        PRD §3.3: "`created_subscriber_ids` lists the ids the job created, in row order."

        Design: Difficulty/compensating_invariant/contact_count_conservation_across_import_and_rollback
        """
        tenant = provision_tenant(initial_send_credits=0)
        audience = create_audience(tenant, double_optin_required=False)
        add_subscribers(audience["id"], ["s1@x.com", "s2@x.com"], tenant.author_headers)

        job = run_import(
            audience["id"],
            ["e1@x.com", "e2@x.com", "e3@x.com", "s1@x.com"],
            tenant.author_headers,
        )
        validate_success(api.rollback_import_job(job["id"], tenant.author_headers))

        archived, _ = validate_paginated(
            api.list_subscribers(
                PLATFORM, {"audience_id": audience["id"], "consent_state": "ARCHIVED"}
            )
        )
        confirmed, _ = validate_paginated(
            api.list_subscribers(
                PLATFORM, {"audience_id": audience["id"], "consent_state": "CONFIRMED"}
            )
        )
        assert len(archived) == 3, "exactly the three rows the job created"
        assert len(confirmed) == 2, "the duplicate row created nothing, so nothing to undo"
        assert sorted(s["id"] for s in archived) == sorted(job["created_subscriber_ids"])

    def test_rollback_is_refused_once_a_send_references_an_imported_contact(self, api):
        """PRD §3.3: "Rollback is the compensating action. A `CampaignAuthor` may roll back a job
        whose `status` is `COMPLETED` or `PARTIAL`, provided that no send has ever been minted for
        any subscriber in `created_subscriber_ids`; a job in any other status, or one whose
        contacts have already been mailed, is refused with `ERR_IMPORT_NOT_ROLLBACKABLE`."

        Design: Corner/errors/err_import_not_rollbackable_once_sends_exist
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        job = run_import(audience["id"], ["i1@x.com"], tenant.author_headers)
        assert job["status"] == "COMPLETED"

        # Mail the imported contact: create -> approve -> schedule -> dispatch.
        template = create_published_template(tenant)
        campaign = create_approved_campaign(tenant, audience["id"], template["id"])
        schedule_ok(tenant, campaign["id"], "2026-05-02T10:00:00Z", 60)
        advance_epoch_to("2026-05-02T10:00:00Z")

        resp = api.rollback_import_job(job["id"], tenant.author_headers)
        validate_error(resp, ApiErrorId.ERR_IMPORT_NOT_ROLLBACKABLE.value)

        after = validate_success(api.list_import_jobs(audience["id"], tenant.author_headers))
        assert after[0]["status"] == "COMPLETED"
        assert read_audience(audience["id"])["subscriber_count"] == 1

    def test_rollback_of_an_unknown_import_job_is_a_not_found(self, api):
        """PRD §2.5: "Path identifiers resolve, left to right, the leftmost miss winning —
        `ERR_ACCOUNT_NOT_FOUND`, `ERR_AUDIENCE_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`,
        `ERR_TEMPLATE_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_JOURNEY_NOT_FOUND`,
        `ERR_IMPORT_JOB_NOT_FOUND` or `ERR_SEND_NOT_FOUND` as appropriate."

        Design: Corner/errors/err_import_job_not_found_on_rollback
        """
        tenant = provision_tenant(with_approver=False)
        resp = api.rollback_import_job(NON_EXISTENT_UUID, tenant.author_headers)
        validate_error(resp, ApiErrorId.ERR_IMPORT_JOB_NOT_FOUND.value)
