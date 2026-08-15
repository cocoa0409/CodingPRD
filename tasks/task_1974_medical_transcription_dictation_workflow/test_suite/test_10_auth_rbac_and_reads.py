"""Auth pipeline, RBAC exclusivity, not-found catalog, and read listings."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_clinic, add_sla_policy, setup_provider, setup_editor,
    setup_workgroup, create_job, claim_job, submit_job, review_job,
    deliver_job, get_job_transcripts, get_period_line_items,
    create_submit_payload, create_qa_review_payload,
    create_billing_period_payload, create_provider_payload,
    make_provider_headers, make_editor_headers, TEST_USERS,
    iso_seconds_prefix, TEXT_65_CHARS,
)

VENDOR = TEST_USERS["vendor_admin_headers"]
CLIENT = TEST_USERS["client_admin_headers"]
QA = TEST_USERS["qa_supervisor_headers"]

MISSING = "00000000-0000-4000-8000-000000000000"


def test_missing_auth_headers_returns_400(api):
    """PRD §2.1: "Failure to provide valid headers, or presenting a role the
    system does not recognize, results in an
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error."
    PRD §2.6: "First, the presence and recognizability of the `X-User-ID` and
    `X-User-Role` headers is checked; a missing or unrecognized context yields
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/missing_auth_headers_returns_400
    """
    resp = api.get_clinic_account(MISSING, headers=None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_job_action_on_nonexistent_job_returns_404(api):
    """PRD §2.6: "Only then does existence validation run: path identifiers are
    validated left to right, and body foreign-key references
    (`dictation_job_id`, `clinic_account_id`, `provider_id`, `editor_id`,
    `template_id`) must also resolve. Each missing resource raises its own
    not-found error — `ERR_CLINIC_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
    `ERR_EDITOR_NOT_FOUND`, `ERR_JOB_NOT_FOUND`, `ERR_TRANSCRIPT_NOT_FOUND`,
    `ERR_TEMPLATE_NOT_FOUND`, `ERR_MACRO_NOT_FOUND`, or
    `ERR_BILLING_PERIOD_NOT_FOUND`."

    Design: Corner/validations/job_action_on_nonexistent_job_returns_404_before_state
    """
    editor = setup_editor(wide_window=False)
    resp = api.submit_job(MISSING, create_submit_payload(),
                          make_editor_headers(editor["id"]))
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_FOUND)


def test_resource_not_found_catalog_spot_checks(api):
    """PRD §2.6: "Each missing resource raises its own not-found error —
    `ERR_CLINIC_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_EDITOR_NOT_FOUND`,
    `ERR_JOB_NOT_FOUND`, `ERR_TRANSCRIPT_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`,
    `ERR_MACRO_NOT_FOUND`, or `ERR_BILLING_PERIOD_NOT_FOUND`. Existence
    strictly precedes ownership: a resource that does not exist can raise no
    ownership check."

    Design: Corner/errors/resource_not_found_catalog_spot_checks
    """
    wg = setup_workgroup()
    provider = wg["provider"]
    job = create_job(provider)
    p_headers = make_provider_headers(provider["id"])

    r1 = api.get_clinic_account("00000000-0000-4000-8000-000000000001", VENDOR)
    validate_error(r1, ApiErrorId.ERR_CLINIC_NOT_FOUND)
    r2 = api.get_transcript("00000000-0000-4000-8000-000000000002", VENDOR)
    validate_error(r2, ApiErrorId.ERR_TRANSCRIPT_NOT_FOUND)
    r3 = api.update_provider_template(
        "00000000-0000-4000-8000-000000000003",
        {"expected_template_version": 1}, p_headers)
    validate_error(r3, ApiErrorId.ERR_TEMPLATE_NOT_FOUND)
    r4 = api.archive_macro("00000000-0000-4000-8000-000000000004", p_headers)
    validate_error(r4, ApiErrorId.ERR_MACRO_NOT_FOUND)
    r5 = api.close_billing_period("00000000-0000-4000-8000-000000000005", VENDOR)
    validate_error(r5, ApiErrorId.ERR_BILLING_PERIOD_NOT_FOUND)
    # Body-FK miss: the unknown editor_id resolves to the typed editor 404.
    unknown_editor = "00000000-0000-4000-8000-000000000006"
    r6 = api.claim_job(job["id"], {"editor_id": unknown_editor},
                       make_editor_headers(unknown_editor))
    validate_error(r6, ApiErrorId.ERR_EDITOR_NOT_FOUND)


def test_provider_cannot_create_qa_review(api):
    """PRD §2.1: "Access to specific operations is further restricted by role;
    an attempt to perform an action outside the caller's designated role is
    rejected with `ERR_UNAUTHORIZED_ROLE`."
    PRD §4: POST /qa-reviews is authorized for QASupervisor only.

    Design: Corner/rbac/provider_cannot_create_qa_review
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    claim_job(job["id"], editor)
    submit_job(job["id"], editor)
    resp = api.create_qa_review(create_qa_review_payload(job["id"]),
                                make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    reviews = validate_success(api.list_job_qa_reviews(job["id"], VENDOR))
    assert reviews == [], "no QAReview recorded by a forbidden role"


def test_client_admin_cannot_claim_job(api):
    """PRD §2.1: "Access to specific operations is further restricted by role;
    an attempt to perform an action outside the caller's designated role is
    rejected with `ERR_UNAUTHORIZED_ROLE`."
    PRD §4: POST /dictation-jobs/{id}/claim is authorized for Editor only.

    Design: Corner/rbac/client_admin_cannot_claim_job
    """
    wg = setup_workgroup()
    job = create_job(wg["provider"])
    resp = api.claim_job(
        job["id"], {"editor_id": "00000000-0000-4000-8000-0000000000aa"},
        CLIENT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_qa_supervisor_shared_reads_allowed(api):
    """PRD §2.1: "All five roles may use the read endpoints; mutating
    capabilities are enumerated per endpoint in §4."
    PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."

    Design: Corner/rbac/qa_supervisor_shared_reads_allowed
    """
    clinic = setup_clinic()
    add_sla_policy(clinic["id"])
    provider = setup_provider(clinic["id"])
    validate_success(api.get_clinic_account(clinic["id"], QA))
    validate_success(api.list_clinic_providers(clinic["id"], QA))
    validate_success(api.list_clinic_sla_policies(clinic["id"], QA))
    validate_success(api.get_provider(provider["id"], QA))
    validate_success(api.list_dictation_jobs(
        QA, params={"provider_id": provider["id"]}))


def test_fk_reverse_reachability_lists_resolve(api):
    """PRD §2.10: "Reverse lookups are provided as filtered collection
    listings. A clinic's providers, SLA policies, and billing periods are
    listable from the clinic; a provider's templates and macros from the
    provider (macros defaulting to active ones only, with an `include_archived`
    query flag to include archived ones); an editor's availability windows from
    the editor; the quality reviews of a job or of a transcript from each
    parent; and the line items of a billing period or billing a given
    transcript from each parent."
    PRD §2.10: "The dictation-job listing supports filters by `provider_id`,
    `clinic_account_id`, `claimed_by_editor_id`, `template_id`, and
    `workflow_status`, and the transcript listing by `dictation_job_id` and
    `editor_id`; both accept the standard `limit` and `offset` pagination
    parameters of §2.3."

    Design: Corner/endpoints/fk_reverse_reachability_lists_resolve
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    delivered = deliver_job(provider, editor, review=(0, 1, 0))  # score 95.0
    job, transcript = delivered["job"], delivered["transcript"]
    period = validate_success(api.create_billing_period(
        create_billing_period_payload(wg["clinic"]["id"]), VENDOR), 201)
    validate_success(api.close_billing_period(period["id"], VENDOR))

    by_provider = validate_success(api.list_dictation_jobs(
        VENDOR, params={"provider_id": provider["id"]}))
    assert [j["id"] for j in by_provider] == [job["id"]]

    by_editor = validate_success(api.list_dictation_jobs(
        VENDOR, params={"claimed_by_editor_id": editor["id"]}))
    assert by_editor == [], (
        "after delivery the claim ended; the filter reflects current claim state")

    qa_reviews = validate_success(api.list_transcript_qa_reviews(transcript["id"], VENDOR))
    assert len(qa_reviews) == 1
    assert abs(qa_reviews[0]["accuracy_score"] - 95.0) < 0.001

    period_items = get_period_line_items(period["id"])
    assert [i["transcript_id"] for i in period_items] == [transcript["id"]]

    transcript_items = validate_success(
        api.list_transcript_line_items(transcript["id"], VENDOR))
    assert [i["billing_period_id"] for i in transcript_items] == [period["id"]]


def test_claim_response_reflects_mutation_immediately(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.4: "A successful claim moves the job from `QUEUED` to `EDITING`,
    stamps `claimed_by_editor_id` with the editor and `claimed_at` with the
    current time, sets `first_claimed_at` if it has never been set — that
    first-claim instant is the anchor of the `PRODUCTION_WINDOW` turnaround
    measurement — and increments the editor's `active_claim_count` by one."
    PRD §2.4: "Before it has ever been set, the logical clock reads the fixed
    default instant 2026-08-01T00:00:00Z, and it never falls back to wall-clock
    time thereafter."

    Design: Corner/consistency_model/claim_response_reflects_mutation_immediately
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    claimed = validate_success(api.claim_job(
        job["id"], {"editor_id": editor["id"]},
        make_editor_headers(editor["id"])))
    assert claimed["workflow_status"] == "EDITING"
    assert claimed["claimed_by_editor_id"] == editor["id"]
    assert iso_seconds_prefix(claimed["claimed_at"]) == "2026-08-01T00:00:00", (
        "claimed_at reads the logical clock")
    assert claimed["version"] == job["version"] + 1
    assert iso_seconds_prefix(claimed["updated_at"]) == iso_seconds_prefix(
        job["created_at"]), "the logical clock never moved between create and claim"
