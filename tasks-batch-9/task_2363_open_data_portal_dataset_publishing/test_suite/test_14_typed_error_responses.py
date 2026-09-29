"""
Typed error responses: the not-found family that names the resource it failed to
resolve, the uniqueness and singleton refusals, and the state guards that answer
with their own specific code instead of the generic one. Every refusal here is
also checked for totality — a rejected request must leave the portal untouched.
"""

from test_helpers import (
    ANONYMOUS_HEADERS,
    ERR_ASSESSMENT_EXISTS,
    ERR_ASSESSMENT_NOT_FOUND,
    ERR_DATASET_NOT_FOUND,
    ERR_DATASET_NOT_PUBLISHED,
    ERR_DEPARTMENT_NOT_FOUND,
    ERR_DUPLICATE_DATASET_SLUG,
    ERR_DUPLICATE_DEPARTMENT_CODE,
    ERR_DUPLICATE_LICENSE_CODE,
    ERR_DUPLICATE_MEMBER_EMAIL,
    ERR_DUPLICATE_SHOWCASE_LABEL,
    ERR_DUPLICATE_USAGE_EPOCH,
    ERR_DUPLICATE_VOTE,
    ERR_ISSUE_NOT_FOUND,
    ERR_LICENSE_NOT_FOUND,
    ERR_MEMBER_NOT_FOUND,
    ERR_METADATA_NOT_FOUND,
    ERR_METADATA_RECORD_EXISTS,
    ERR_NO_PREDECESSOR_VERSION,
    ERR_PIPELINE_NOT_FOUND,
    ERR_PRIVACY_CLEARANCE_REQUIRED,
    ERR_REQUEST_NOT_FOUND,
    ERR_RUN_NOT_FOUND,
    ERR_RUNNER_NOT_FOUND,
    ERR_SHOWCASE_NOT_FOUND,
    ERR_VERSION_NOT_FOUND,
    ERR_VERSION_NOT_LIVE,
    NON_EXISTENT_UUID,
    PORTAL_ADMIN_HEADERS,
    PRIVACY_ASSESSOR_HEADERS,
    assert_dataset_states,
    assert_exactly_one_live_version,
    assert_money,
    factories,
    find_showcase_app,
    find_version_by_index,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CORRIDOR_MAP = {
    "name": "Corridor Delay Map",
    "url": "https://civic.example/corridor-map",
}

SIGNAL_TIMING_REQUEST = {
    "title": "Signal timing plans",
    "rationale": "Needed to audit corridor delays across the downtown grid.",
}


def test_unknown_path_identifiers_answer_each_resource_specific_not_found_error(api):
    """Eleven single-resource reads on an empty portal, each naming its own resource.

    The PRD: "Path resolution, on every endpoint that has path parameters: each
    addressed resource resolves, checked left to right (see §2.8), answering with the
    not-found code for the *first* unresolvable segment — one of
    `ERR_DATASET_NOT_FOUND`, `ERR_DEPARTMENT_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
    `ERR_RUNNER_NOT_FOUND`, `ERR_METADATA_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
    `ERR_PIPELINE_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_VERSION_NOT_FOUND`,
    `ERR_ISSUE_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND` or
    `ERR_SHOWCASE_NOT_FOUND`, all 404."

    Each read below is made with a role the endpoint authorises, so nothing can be
    answered by priority 2, and the database is empty, so the addressed id cannot
    resolve. A single shared not-found code would fail this test: every answer must
    name the resource type that failed to resolve, at 404.

    Design: Corner/errors/unknown_path_ids_return_typed_not_found_errors
    """
    fixtures.reset_clock_to_start(api=api)

    reads = [
        (
            "GET /open-data/departments/{departmentId}",
            lambda: api.get_department(NON_EXISTENT_UUID, ANONYMOUS_HEADERS),
            ERR_DEPARTMENT_NOT_FOUND,
        ),
        (
            "GET /open-data/licenses/{licenseId}",
            lambda: api.get_license(NON_EXISTENT_UUID, ANONYMOUS_HEADERS),
            ERR_LICENSE_NOT_FOUND,
        ),
        (
            "GET /open-data/ingest-runners/{runnerId}",
            lambda: api.get_ingest_runner(NON_EXISTENT_UUID, PORTAL_ADMIN_HEADERS),
            ERR_RUNNER_NOT_FOUND,
        ),
        (
            "GET /open-data/metadata-records/{metadataRecordId}",
            lambda: api.get_metadata_record(NON_EXISTENT_UUID, ANONYMOUS_HEADERS),
            ERR_METADATA_NOT_FOUND,
        ),
        (
            "GET /open-data/privacy-assessments/{assessmentId}",
            lambda: api.get_privacy_assessment(NON_EXISTENT_UUID, PORTAL_ADMIN_HEADERS),
            ERR_ASSESSMENT_NOT_FOUND,
        ),
        (
            "GET /open-data/publication-pipelines/{pipelineId}",
            lambda: api.get_publication_pipeline(NON_EXISTENT_UUID, PORTAL_ADMIN_HEADERS),
            ERR_PIPELINE_NOT_FOUND,
        ),
        (
            "GET /open-data/pipeline-runs/{runId}",
            lambda: api.get_pipeline_run(NON_EXISTENT_UUID, PORTAL_ADMIN_HEADERS),
            ERR_RUN_NOT_FOUND,
        ),
        (
            "GET /open-data/dataset-versions/{versionId}",
            lambda: api.get_dataset_version(NON_EXISTENT_UUID, ANONYMOUS_HEADERS),
            ERR_VERSION_NOT_FOUND,
        ),
        (
            "GET /open-data/quality-issues/{issueId}",
            lambda: api.get_quality_issue(NON_EXISTENT_UUID, ANONYMOUS_HEADERS),
            ERR_ISSUE_NOT_FOUND,
        ),
        (
            "GET /open-data/members/{memberId}",
            lambda: api.get_member(NON_EXISTENT_UUID, PORTAL_ADMIN_HEADERS),
            ERR_MEMBER_NOT_FOUND,
        ),
        (
            "GET /open-data/dataset-requests/{requestId}",
            lambda: api.get_dataset_request(NON_EXISTENT_UUID, ANONYMOUS_HEADERS),
            ERR_REQUEST_NOT_FOUND,
        ),
    ]

    for endpoint, read, expected_error_id in reads:
        response = read()
        assert response.status_code == 404, (
            f"{endpoint} with an unresolvable id must answer 404, "
            f"got {response.status_code}"
        )
        error = validate_error(response, expected_error_id, 404)
        assert error["error_id"] == expected_error_id, (
            f"{endpoint} must answer {expected_error_id}, got {error['error_id']}"
        )


def test_unknown_body_foreign_keys_answer_the_typed_not_found_before_later_guards(api):
    """A dangling licence, runner and member reference in three write bodies.

    Priority 5 of the ladder requires that "every foreign key supplied in the body
    resolves to an existing row — otherwise the corresponding 404 from the same family
    as priority 3 (`ERR_DEPARTMENT_NOT_FOUND`, `ERR_DATASET_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, `ERR_RUNNER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
    `ERR_VERSION_NOT_FOUND`, `ERR_ISSUE_NOT_FOUND` or `ERR_PIPELINE_NOT_FOUND`)."

    Ordering decides two of these three answers, and the PRD fixes it: "All validations
    are evaluated in the ascending priority order below". The metadata-record body
    names an unknown `license_id` on a dataset that already holds an `ACCEPTED` record,
    so priority 5 must answer `ERR_LICENSE_NOT_FOUND` and not the priority 10
    `ERR_METADATA_RECORD_EXISTS`. The quality-issue body names an unknown
    `reporter_member_id` while the caller is a real, different member — the priority 7
    check that would otherwise fire is "Member self-scope, on
    `POST /open-data/quality-issues`, `POST /open-data/dataset-requests`,
    `POST /open-data/dataset-requests/{requestId}/votes` and
    `POST /open-data/datasets/{datasetId}/showcase-apps`:
    `ERR_MEMBER_SCOPE_VIOLATION` (403) as described in §2.1", where §2.1 says
    "Ownership checks compare `X-User-ID` to whichever member reference the body
    carries — `reporter_member_id` when filing a quality issue, `requester_member_id`
    when asking for a new dataset, `member_id` when casting a vote,
    `submitter_member_id` when submitting a showcase application." The answer must
    therefore be `ERR_MEMBER_NOT_FOUND` at 404, not `ERR_MEMBER_SCOPE_VIOLATION` at
    403. The pipeline body carries the dataset's true current `version`, so
    `ERR_RUNNER_NOT_FOUND` is the only guard armed there.

    Design: Corner/errors/unknown_body_foreign_keys_return_typed_not_found_errors
    """
    ctx = fixtures.setup_published_dataset(api=api)
    member = fixtures.setup_member(api=api)
    dataset_version_token = fixtures.current_dataset_version(ctx["dataset_id"], api=api)

    validate_error(
        api.create_metadata_record(
            factories.metadata_record_payload(ctx["dataset_id"], NON_EXISTENT_UUID),
            ctx["coordinator_headers"],
        ),
        ERR_LICENSE_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_publication_pipeline(
            factories.pipeline_payload(
                ctx["dataset_id"], NON_EXISTENT_UUID, dataset_version_token
            ),
            ctx["coordinator_headers"],
        ),
        ERR_RUNNER_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_quality_issue(
            factories.quality_issue_payload(
                ctx["dataset_id"],
                NON_EXISTENT_UUID,
                severity="HIGH",
                category="ACCURACY",
                description="Counts look doubled after the weekend refresh.",
            ),
            member["member_headers"],
        ),
        ERR_MEMBER_NOT_FOUND,
        404,
    )

    records, records_meta = validate_paginated(
        api.list_metadata_records(ANONYMOUS_HEADERS, params={"dataset_id": ctx["dataset_id"]})
    )
    assert records_meta["total_count"] == 1, (
        f"Only the accepted record built in setup may exist, "
        f"got total_count {records_meta['total_count']}"
    )
    assert records[0]["license_id"] == ctx["license_id"], (
        f"The surviving record must still reference the real licence, "
        f"got {records[0]['license_id']!r}"
    )

    _, pipelines_meta = validate_paginated(api.list_publication_pipelines(PORTAL_ADMIN_HEADERS))
    assert pipelines_meta["total_count"] == 0, (
        f"A refused pipeline must not be persisted, "
        f"got total_count {pipelines_meta['total_count']}"
    )

    _, issues_meta = validate_paginated(api.list_quality_issues(ANONYMOUS_HEADERS))
    assert issues_meta["total_count"] == 0, (
        f"A refused quality issue must not be persisted, "
        f"got total_count {issues_meta['total_count']}"
    )


def test_duplicate_department_licence_slug_and_member_email_are_each_refused(api):
    """The four scalar identities are unique across their whole collection.

    The PRD: "Scalar uniqueness, on `POST /open-data/departments`,
    `POST /open-data/licenses`, `POST /open-data/datasets` and
    `POST /open-data/members/register`: `Department.code`, `LicenseTerm.code`,
    `Dataset.slug` and `CommunityMember.email` are each unique across their own
    collection, answering `ERR_DUPLICATE_DEPARTMENT_CODE`,
    `ERR_DUPLICATE_LICENSE_CODE`, `ERR_DUPLICATE_DATASET_SLUG` or
    `ERR_DUPLICATE_MEMBER_EMAIL` (409)."

    Each of the four collections already holds one row, and each retry re-uses only the
    unique scalar. All four must be refused at 409 with their own code, and no second
    row may survive anywhere.

    Design: Corner/errors/duplicate_scalar_identities_are_rejected
    """
    ctx = fixtures.setup_funded_department(api=api, credit_units=0)
    dataset = fixtures.inventory_dataset(ctx["department_id"], api=api)
    member = fixtures.register_member(api=api)

    validate_error(
        api.create_department(
            factories.department_payload(name="Duplicate Transportation Department"),
            PORTAL_ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_DEPARTMENT_CODE,
        409,
    )
    validate_error(
        api.create_license(
            factories.license_payload(name="Creative Commons Attribution 4.0 (copy)"),
            PORTAL_ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_LICENSE_CODE,
        409,
    )
    validate_error(
        api.create_dataset(
            factories.dataset_payload(ctx["department_id"], title="Weekly Traffic Counts (copy)"),
            ctx["coordinator_headers"],
        ),
        ERR_DUPLICATE_DATASET_SLUG,
        409,
    )
    validate_error(
        api.register_member(
            factories.member_payload(display_name="Ana Reuser (copy)"), ANONYMOUS_HEADERS
        ),
        ERR_DUPLICATE_MEMBER_EMAIL,
        409,
    )

    departments, departments_meta = validate_paginated(
        api.list_departments(ANONYMOUS_HEADERS, params={"code": "DOT"})
    )
    assert departments_meta["total_count"] == 1, (
        f"Exactly one department may carry code DOT, "
        f"got total_count {departments_meta['total_count']}"
    )
    assert departments[0]["id"] == ctx["department_id"], (
        f"The surviving department must be the first one, got {departments[0]['id']!r}"
    )

    licenses, licenses_meta = validate_paginated(api.list_licenses(ANONYMOUS_HEADERS))
    assert licenses_meta["total_count"] == 1, (
        f"Exactly one licence may carry code CC-BY-4.0, "
        f"got total_count {licenses_meta['total_count']}"
    )
    assert licenses[0]["id"] == ctx["license_id"], (
        f"The surviving licence must be the first one, got {licenses[0]['id']!r}"
    )

    datasets, datasets_meta = validate_paginated(api.list_datasets(ANONYMOUS_HEADERS))
    assert datasets_meta["total_count"] == 1, (
        f"Exactly one dataset may carry slug weekly-traffic-counts, "
        f"got total_count {datasets_meta['total_count']}"
    )
    assert datasets[0]["id"] == dataset["id"], (
        f"The surviving dataset must be the first one, got {datasets[0]['id']!r}"
    )

    surviving_member = fixtures.read_member(member["id"], api=api)
    assert surviving_member["email"] == "ana@civic.example", (
        f"The first member must keep the contested email, got {surviving_member['email']!r}"
    )


def test_duplicate_usage_epoch_showcase_label_and_vote_are_each_refused(api):
    """Three uniqueness rules scoped inside one parent row, each with its own code.

    The PRD: "Collection-member uniqueness, on
    `POST /open-data/datasets/{datasetId}/usage-report`,
    `POST /open-data/datasets/{datasetId}/showcase-apps` and
    `POST /open-data/dataset-requests/{requestId}/votes`: `epoch_index` is unique per
    dataset (`ERR_DUPLICATE_USAGE_EPOCH`), showcase `label` is unique per dataset
    (`ERR_DUPLICATE_SHOWCASE_LABEL`), and a member may hold at most one vote per
    request (`ERR_DUPLICATE_VOTE`), all 409."

    Each refusal must be total, which is observable in the derived figures. Epoch 1 was
    recorded with 2000 api calls and 500 downloads, and "Each selected epoch is valued
    at 0.60 times its `api_call_count` plus 0.40 times its `download_count`." — 1400 —
    while "a dataset with a single epoch keeps only the 0.50 weight and the remaining
    0.50 is simply lost", giving 700, and "The weighted total is divided by 50, rounded
    half up to two decimal places once, and capped at 100.00, giving
    `engagement_index`; `observed_demand_score` is set to the same value." So
    `engagement_index` stands at 14.00 and the rejected 9999/9999 epoch must not shift
    it. The single vote was cast by a brand-new member, and "A new member begins with
    `accepted_issue_count`, `rejected_issue_count`, `approved_showcase_count` and
    `decay_epochs` all zero, `reputation_score` 50.00, `vote_weight` 2, `status`
    `ACTIVE`, and `last_credited_at` initialised to the member's own `created_at`.",
    while "`weighted_vote_total` is then the plain sum of every stored `weight` across
    the whole array with no time window, and `demand_signal` is that total multiplied
    by 5, capped at 100, and rounded half up to two decimal places." — so the request
    must still read 2 and 10.00 after the duplicate vote is refused.

    Design: Corner/errors/duplicate_collection_members_are_rejected
    """
    ctx = fixtures.setup_published_dataset(api=api)
    fixtures.report_usage_epoch(ctx["dataset_id"], 1, 2000, 500, api=api)
    member = fixtures.setup_member(api=api)
    fixtures.submit_showcase_app(
        ctx["dataset_id"], member["member_id"], "corridor-map", api=api, **CORRIDOR_MAP
    )
    request = fixtures.open_dataset_request(member["member_id"], api=api, **SIGNAL_TIMING_REQUEST)
    fixtures.cast_vote(request["id"], member["member_id"], api=api)

    validate_error(
        api.report_dataset_usage(
            ctx["dataset_id"], factories.usage_report_payload(1, 9999, 9999), PORTAL_ADMIN_HEADERS
        ),
        ERR_DUPLICATE_USAGE_EPOCH,
        409,
    )
    validate_error(
        api.submit_showcase_app(
            ctx["dataset_id"],
            factories.showcase_app_payload(
                "corridor-map",
                member["member_id"],
                name="Corridor Delay Map v2",
                url="https://civic.example/corridor-map-2",
            ),
            member["member_headers"],
        ),
        ERR_DUPLICATE_SHOWCASE_LABEL,
        409,
    )
    validate_error(
        api.cast_request_vote(
            request["id"], factories.vote_payload(member["member_id"]), member["member_headers"]
        ),
        ERR_DUPLICATE_VOTE,
        409,
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert len(dataset["usage_epochs"]) == 1, (
        f"Expected exactly 1 usage epoch, got {len(dataset['usage_epochs'])}: "
        f"{dataset['usage_epochs']}"
    )
    assert dataset["usage_epochs"][0]["api_call_count"] == 2000, (
        f"The stored epoch must keep its 2000 api calls, "
        f"got {dataset['usage_epochs'][0]['api_call_count']}"
    )
    assert_money(dataset["engagement_index"], 14.00, "engagement_index")

    assert len(dataset["showcase_apps"]) == 1, (
        f"Expected exactly 1 showcase entry, got {len(dataset['showcase_apps'])}: "
        f"{dataset['showcase_apps']}"
    )
    entry = find_showcase_app(dataset, "corridor-map")
    assert entry["name"] == "Corridor Delay Map", (
        f"The stored entry must keep its original name, got {entry['name']!r}"
    )

    stored_request = validate_success(api.get_dataset_request(request["id"], ANONYMOUS_HEADERS))
    assert stored_request["weighted_vote_total"] == 2, (
        f"Expected weighted_vote_total 2 after the duplicate vote is refused, "
        f"got {stored_request['weighted_vote_total']}"
    )
    assert_money(stored_request["demand_signal"], 10.00, "demand_signal")
    assert len(stored_request["votes"]) == 1, (
        f"Expected exactly 1 stored vote, got {len(stored_request['votes'])}"
    )


def test_second_metadata_record_and_second_assessment_are_refused_while_first_is_draft(api):
    """The per-dataset singletons count a first row that is still only `DRAFT`.

    The PRD: "Per-dataset singletons, on `POST /open-data/metadata-records` and
    `POST /open-data/privacy-assessments`: a dataset may hold at most one metadata
    record whose `status` is `DRAFT`, `SUBMITTED` or `ACCEPTED`
    (`ERR_METADATA_RECORD_EXISTS`, 409) and at most one privacy assessment whose
    `status` is `DRAFT`, `SUBMITTED` or `CLEARED` (`ERR_ASSESSMENT_EXISTS`, 409)."

    Both incumbents here are merely `DRAFT`, which is the weakest of the counted
    statuses, and both second creations must still be refused at 409 with their own
    code, leaving one record and one assessment for the dataset.

    Design: Corner/errors/per_dataset_singleton_records_are_rejected
    """
    ctx = fixtures.setup_screening_dataset(api=api, credit_units=0)
    record = fixtures.draft_metadata_record(
        ctx["dataset_id"], ctx["license_id"], ctx["department_id"], api=api
    )
    assessment = fixtures.open_privacy_assessment(ctx["dataset_id"], api=api)
    assert record["status"] == "DRAFT", (
        f"Setup must leave the first record DRAFT, got {record['status']}"
    )
    assert assessment["status"] == "DRAFT", (
        f"Setup must leave the first assessment DRAFT, got {assessment['status']}"
    )

    validate_error(
        api.create_metadata_record(
            factories.metadata_record_payload(ctx["dataset_id"], ctx["license_id"]),
            ctx["coordinator_headers"],
        ),
        ERR_METADATA_RECORD_EXISTS,
        409,
    )
    validate_error(
        api.create_privacy_assessment(
            factories.privacy_assessment_payload(ctx["dataset_id"]), PRIVACY_ASSESSOR_HEADERS
        ),
        ERR_ASSESSMENT_EXISTS,
        409,
    )

    records, records_meta = validate_paginated(
        api.list_metadata_records(ANONYMOUS_HEADERS, params={"dataset_id": ctx["dataset_id"]})
    )
    assert records_meta["total_count"] == 1, (
        f"The dataset may hold exactly one metadata record, "
        f"got total_count {records_meta['total_count']}"
    )
    assert records[0]["id"] == record["id"], (
        f"The surviving record must be the first one, got {records[0]['id']!r}"
    )

    assessments, assessments_meta = validate_paginated(
        api.list_privacy_assessments(PORTAL_ADMIN_HEADERS)
    )
    assert assessments_meta["total_count"] == 1, (
        f"The dataset may hold exactly one privacy assessment, "
        f"got total_count {assessments_meta['total_count']}"
    )
    assert assessments[0]["id"] == assessment["id"], (
        f"The surviving assessment must be the first one, got {assessments[0]['id']!r}"
    )

    unchanged_record = validate_success(api.get_metadata_record(record["id"], ANONYMOUS_HEADERS))
    assert unchanged_record["status"] == "DRAFT", (
        f"The refused creation must leave the first record DRAFT, "
        f"got {unchanged_record['status']}"
    )
    unchanged_assessment = validate_success(
        api.get_privacy_assessment(assessment["id"], PORTAL_ADMIN_HEADERS)
    )
    assert unchanged_assessment["status"] == "DRAFT", (
        f"The refused creation must leave the first assessment DRAFT, "
        f"got {unchanged_assessment['status']}"
    )


def test_mark_ready_reports_the_missing_clearance_when_no_assessment_was_ever_opened(api):
    """The metadata half of the readiness gate is satisfied; the privacy half is absent.

    The PRD: "The dataset advances `SCREENING → READY` only when exactly one metadata
    record for it sits in `ACCEPTED` and exactly one privacy assessment for it sits in
    `CLEARED`; a missing acceptance is `ERR_METADATA_NOT_ACCEPTED` and a missing
    clearance is `ERR_PRIVACY_CLEARANCE_REQUIRED`." The ladder repeats the pairing:
    "Cross-entity readiness, on `POST /open-data/datasets/{datasetId}/mark-ready` and
    `POST /open-data/datasets/{datasetId}/publish`: readiness requires an `ACCEPTED`
    metadata record (`ERR_METADATA_NOT_ACCEPTED`) and a `CLEARED` privacy assessment
    (`ERR_PRIVACY_CLEARANCE_REQUIRED`); publication requires the metadata record to
    still be `ACCEPTED`."

    The record is `ACCEPTED` and no assessment row exists at all, so only the second
    half can fail: the answer must be `ERR_PRIVACY_CLEARANCE_REQUIRED` at 409 and not
    `ERR_METADATA_NOT_ACCEPTED`, and the dataset must stay in `SCREENING`.

    Design: Corner/errors/mark_ready_without_any_privacy_assessment_returns_4XX
    """
    ctx = fixtures.setup_screening_dataset(api=api, credit_units=0)
    record = fixtures.land_accepted_metadata(
        ctx["dataset_id"], ctx["license_id"], ctx["department_id"], api=api
    )
    assert record["status"] == "ACCEPTED", (
        f"Setup must leave the record ACCEPTED, got {record['status']}"
    )

    validate_error(
        api.mark_dataset_ready(ctx["dataset_id"], ctx["coordinator_headers"]),
        ERR_PRIVACY_CLEARANCE_REQUIRED,
        409,
    )

    unchanged_record = validate_success(api.get_metadata_record(record["id"], ANONYMOUS_HEADERS))
    assert unchanged_record["status"] == "ACCEPTED", (
        f"The acceptance must be untouched by the refusal, got {unchanged_record['status']}"
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, publication_status="SCREENING")

    _, assessments_meta = validate_paginated(api.list_privacy_assessments(PORTAL_ADMIN_HEADERS))
    assert assessments_meta["total_count"] == 0, (
        f"No privacy assessment may exist in this scenario, "
        f"got total_count {assessments_meta['total_count']}"
    )


def test_manual_version_on_a_ready_dataset_is_refused_as_not_published(api):
    """Version history only exists for a dataset that has actually been published.

    The PRD, on publishing a version by hand: "This is permitted while the dataset's
    `publication_status` is `PUBLISHED` and also while it is `UNDER_REMEDIATION`,
    because a corrective version is precisely what lifts remediation; any other state
    is refused with `ERR_DATASET_NOT_PUBLISHED`." The ladder confirms which of the four
    state codes applies: "The rejection is `ERR_INVALID_STATE_TRANSITION` in the
    general case, and the more specific `ERR_DATASET_NOT_PUBLISHED`,
    `ERR_PIPELINE_NOT_ARMED` or `ERR_VERSION_NOT_LIVE` where the guard is precisely
    about the dataset being published, the pipeline being armed, or the version being
    live. All four are 409."

    The dataset is `READY` and has never been published. The `expected_dataset_version`
    token is read from the dataset itself, so the priority 12 optimistic-concurrency
    check passes and the answer must be `ERR_DATASET_NOT_PUBLISHED` at 409, never
    `ERR_STALE_DATASET_VERSION` at 412. No version row may be minted.

    Design: Corner/errors/manual_version_on_a_ready_dataset_returns_4XX
    """
    ctx = fixtures.setup_ready_dataset(api=api, credit_units=0)
    dataset_version_token = fixtures.current_dataset_version(ctx["dataset_id"], api=api)

    validate_error(
        api.create_dataset_version(
            factories.dataset_version_payload(
                ctx["dataset_id"],
                "SCHEMA_CHANGE",
                50000,
                dataset_version_token,
                notes="Initial load attempted out of band",
            ),
            ctx["coordinator_headers"],
        ),
        ERR_DATASET_NOT_PUBLISHED,
        409,
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(dataset, publication_status="READY")
    assert dataset["live_row_count"] == 0, (
        f"An unpublished dataset must keep live_row_count 0, got {dataset['live_row_count']}"
    )
    assert dataset["version_index_high_water"] == 0, (
        f"An unpublished dataset must keep version_index_high_water 0, "
        f"got {dataset['version_index_high_water']}"
    )

    _, versions_meta = validate_paginated(api.list_dataset_versions(ANONYMOUS_HEADERS))
    assert versions_meta["total_count"] == 0, (
        f"A refused version must not be persisted, "
        f"got total_count {versions_meta['total_count']}"
    )


def test_link_correction_pointing_at_a_superseded_version_is_refused(api):
    """A correction must be attached to the version that is currently live.

    The PRD: "The attachment requires the acting coordinator to own the dataset's
    department and requires the referenced version to belong to the same dataset, to
    carry `change_type` `CORRECTION` and to currently be `LIVE`." The ladder names the
    code: "The rejection is `ERR_INVALID_STATE_TRANSITION` in the general case, and the
    more specific `ERR_DATASET_NOT_PUBLISHED`, `ERR_PIPELINE_NOT_ARMED` or
    `ERR_VERSION_NOT_LIVE` where the guard is precisely about the dataset being
    published, the pipeline being armed, or the version being live. All four are 409."

    Two corrective versions are published in a row, and "The new version takes
    `version_index` equal to the dataset's `version_index_high_water` plus one, a
    matching `version_label`, `status` `LIVE`, `published_at` at the current logical
    instant, and `supersedes_version_id` pointing at the previously `LIVE` version,
    which moves to `SUPERSEDED` with `superseded_at` stamped." The version aimed at is
    therefore a `CORRECTION` belonging to this dataset, offered by its owning
    coordinator, and failing only the liveness clause — so `ERR_VERSION_NOT_LIVE` is
    the single derivable answer. The dataset stays `UNDER_REMEDIATION` with
    `public_access_suspended` true, because "When the dataset is sitting in
    `UNDER_REMEDIATION` and no *other* quality issue on that dataset is still
    `ACCEPTED` with `severity` `CRITICAL` and `category` `PRIVACY`, the same request
    returns the dataset `UNDER_REMEDIATION → PUBLISHED`: `public_access_suspended`
    becomes false, `remediation_opened_at` is cleared to null, and `currency_status` is
    re-derived" — only the successful attachment does that. Aiming at the live version
    instead then lands: "It sets the issue's `resolution_version_id` to that version,
    sets that version's own `correction_issue_id` back to the issue, moves the issue
    `ACCEPTED → CORRECTED`, and clears `correction_breached`."

    Design: Corner/errors/link_correction_with_superseded_version_returns_4XX
    """
    ctx = fixtures.setup_published_dataset(api=api)
    member = fixtures.setup_member(api=api)
    issue = fixtures.file_and_triage_issue(
        ctx["dataset_id"], member["member_id"], ctx["department_id"], api=api
    )
    issue = fixtures.accept_quality_issue(issue["id"], ctx["department_id"], api=api)
    assert issue["status"] == "ACCEPTED", (
        f"Setup must leave the issue ACCEPTED, got {issue['status']}"
    )
    remediating = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(remediating, publication_status="UNDER_REMEDIATION")

    superseded_correction = fixtures.publish_version(
        ctx["dataset_id"], ctx["department_id"], "CORRECTION", 50500, api=api
    )
    live_correction = fixtures.publish_version(
        ctx["dataset_id"], ctx["department_id"], "CORRECTION", 50750, api=api
    )

    validate_error(
        api.link_correction(
            issue["id"],
            factories.link_correction_payload(superseded_correction["id"]),
            ctx["coordinator_headers"],
        ),
        ERR_VERSION_NOT_LIVE,
        409,
    )

    demoted = validate_success(
        api.get_dataset_version(superseded_correction["id"], ANONYMOUS_HEADERS)
    )
    assert demoted["status"] == "SUPERSEDED", (
        f"The second version must have been demoted to SUPERSEDED, got {demoted['status']}"
    )
    still_live = validate_success(api.get_dataset_version(live_correction["id"], ANONYMOUS_HEADERS))
    assert still_live["status"] == "LIVE", (
        f"The third version must still be LIVE, got {still_live['status']}"
    )
    assert still_live["version_index"] == 3, (
        f"The third version must carry version_index 3, got {still_live['version_index']}"
    )
    assert_exactly_one_live_version(fixtures.versions_of_dataset(ctx["dataset_id"], api=api))

    refused_issue = validate_success(api.get_quality_issue(issue["id"], ANONYMOUS_HEADERS))
    assert refused_issue["status"] == "ACCEPTED", (
        f"The refused attachment must leave the issue ACCEPTED, got {refused_issue['status']}"
    )
    assert refused_issue["resolution_version_id"] is None, (
        f"The refused attachment must leave resolution_version_id null, "
        f"got {refused_issue['resolution_version_id']!r}"
    )

    held = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(held, publication_status="UNDER_REMEDIATION")
    assert held["public_access_suspended"] is True, (
        f"Remediation must still be in force, got public_access_suspended "
        f"{held['public_access_suspended']!r}"
    )

    corrected = fixtures.link_correction(
        issue["id"], ctx["department_id"], live_correction["id"], api=api
    )
    assert corrected["status"] == "CORRECTED", (
        f"Attaching the LIVE corrective version must move the issue to CORRECTED, "
        f"got {corrected['status']}"
    )
    assert corrected["resolution_version_id"] == live_correction["id"], (
        f"Expected resolution_version_id {live_correction['id']}, "
        f"got {corrected['resolution_version_id']!r}"
    )
    lifted = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert_dataset_states(lifted, publication_status="PUBLISHED")
    assert lifted["public_access_suspended"] is False, (
        f"The correction must lift remediation, got public_access_suspended "
        f"{lifted['public_access_suspended']!r}"
    )


def test_retracting_the_first_version_is_refused_for_want_of_a_predecessor(api):
    """Retraction is a rollback, and the first version has nothing behind it.

    The PRD: "Retracting the `LIVE` version takes an optional `reason` and requires a
    predecessor to restore: the version's `version_index` must be at least 2 and the
    immediately preceding version must currently be `SUPERSEDED`, or the request is
    refused with `ERR_NO_PREDECESSOR_VERSION`."

    Publication minted exactly one version — "A first `DatasetVersion` is minted with
    `version_index` set to the dataset's `version_index_high_water` plus one — which is
    1 — a `version_label` of `"v"` followed by that index, a `change_type` of
    `INITIAL`, a `row_count` equal to the supplied `initial_row_count`, a `status` of
    `LIVE`, a `published_at` stamped at the current logical instant, and
    `supersedes_version_id` null because there is nothing before it." — and "On the
    dataset, `version_index_high_water` becomes 1, `live_row_count` becomes the initial
    row count, and `last_published_at` becomes the current logical instant." So the
    retraction must be refused at 409 and the 50000 published rows must survive it.

    Design: Corner/errors/retract_of_the_first_version_returns_4XX
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    versions = fixtures.versions_of_dataset(ctx["dataset_id"], api=api)
    assert len(versions) == 1, (
        f"Setup must leave exactly one version, got {len(versions)}: "
        f"{[(v.get('version_index'), v.get('status')) for v in versions]}"
    )
    first_version = find_version_by_index(versions, 1)

    validate_error(
        api.retract_dataset_version(
            first_version["id"], PORTAL_ADMIN_HEADERS, {"reason": "Wrong extract loaded"}
        ),
        ERR_NO_PREDECESSOR_VERSION,
        409,
    )

    unchanged = validate_success(api.get_dataset_version(first_version["id"], ANONYMOUS_HEADERS))
    assert unchanged["status"] == "LIVE", (
        f"The refused retraction must leave the version LIVE, got {unchanged['status']}"
    )
    assert unchanged["version_index"] == 1, (
        f"Expected version_index 1, got {unchanged['version_index']}"
    )
    assert unchanged["retracted_at"] is None, (
        f"The refused retraction must leave retracted_at null, got {unchanged['retracted_at']!r}"
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert dataset["live_row_count"] == 50000, (
        f"Expected live_row_count 50000 to be preserved, got {dataset['live_row_count']}"
    )
    assert dataset["version_index_high_water"] == 1, (
        f"Expected version_index_high_water 1, got {dataset['version_index_high_water']}"
    )


def test_showcase_decision_on_an_unknown_label_answers_showcase_not_found(api):
    """Two path segments, resolved in order: the dataset first, then the label.

    The PRD: "In that case the identifiers are resolved strictly left to right: a
    request naming a dataset that does not exist answers `ERR_DATASET_NOT_FOUND`
    without ever looking for the showcase entry, and only once the dataset resolves
    does a missing label answer `ERR_SHOWCASE_NOT_FOUND`."

    The dataset holds one entry, because "A member submits one against a dataset by
    supplying a `label` that must be unique within that dataset, the application's
    `name`, its `url`, and their own `submitter_member_id`." and "The entry is appended
    to the dataset's `showcase_apps` with `status` `SUBMITTED` and `decided_at` null."
    Moderating a label that was never submitted must answer `ERR_SHOWCASE_NOT_FOUND` at
    404 while the real entry stays untouched, and the submitter must earn nothing —
    "On approval the submitter's `approved_showcase_count` increases by 1 and their
    `reputation_score` and `vote_weight` are re-derived; a rejection credits nothing."

    Design: Corner/errors/showcase_decision_on_unknown_label_returns_not_found
    """
    ctx = fixtures.setup_published_dataset(api=api, credit_units=0)
    member = fixtures.setup_member(api=api)
    fixtures.submit_showcase_app(
        ctx["dataset_id"], member["member_id"], "corridor-map", api=api, **CORRIDOR_MAP
    )

    validate_error(
        api.decide_showcase_app(
            ctx["dataset_id"],
            "transit-dashboard",
            factories.decision_payload("APPROVE"),
            PORTAL_ADMIN_HEADERS,
        ),
        ERR_SHOWCASE_NOT_FOUND,
        404,
    )
    validate_error(
        api.decide_showcase_app(
            NON_EXISTENT_UUID,
            "corridor-map",
            factories.decision_payload("APPROVE"),
            PORTAL_ADMIN_HEADERS,
        ),
        ERR_DATASET_NOT_FOUND,
        404,
    )

    dataset = fixtures.read_dataset(ctx["dataset_id"], api=api)
    assert len(dataset["showcase_apps"]) == 1, (
        f"Expected exactly 1 showcase entry, got {len(dataset['showcase_apps'])}: "
        f"{dataset['showcase_apps']}"
    )
    entry = find_showcase_app(dataset, "corridor-map")
    assert entry["status"] == "SUBMITTED", (
        f"The undecided entry must still be SUBMITTED, got {entry['status']}"
    )
    assert entry["decided_at"] is None, (
        f"The undecided entry must keep decided_at null, got {entry['decided_at']!r}"
    )

    submitter = fixtures.read_member(member["member_id"], api=api)
    assert submitter["approved_showcase_count"] == 0, (
        f"A failed moderation must credit nothing, got approved_showcase_count "
        f"{submitter['approved_showcase_count']}"
    )
    assert_money(submitter["reputation_score"], 50.00, "reputation_score")
