"""Dictation capture, claiming, release, cancellation, and job listing rules."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_clinic, add_sla_policy, setup_provider, setup_editor, setup_workgroup,
    create_job, claim_job, submit_job, get_job, get_editor,
    create_dictation_job_payload, create_submit_payload, create_qa_review_payload,
    create_shift_window_payload, set_clock,
    make_provider_headers, make_editor_headers, TEST_USERS,
    iso_seconds_prefix, TEXT_65_CHARS,
)

VENDOR = TEST_USERS["vendor_admin_headers"]


def test_job_initial_state_queued_with_computed_due_at(api):
    """PRD §3.3: "A job that passes the guards is created with its
    `clinic_account_id` copied from the provider's record, `workflow_status`
    `QUEUED`, and `escalation_level` `NONE`."
    PRD §3.3: "The deadline `due_at` is fixed at creation as the job's
    `created_at` plus the governing policy's `tat_minutes`, and it is never
    recomputed afterwards — rework, preemption, and provider returns all leave
    the original deadline untouched."
    PRD §2.4: "Before it has ever been set, the logical clock reads the fixed
    default instant 2026-08-01T00:00:00Z, and it never falls back to wall-clock
    time thereafter."

    Design: Corner/state_machines/job_initial_state_queued_with_computed_due_at
    """
    clinic = setup_clinic()
    add_sla_policy(clinic["id"], priority="STAT", tat_minutes=120,
                   rate_per_line_cents=20, breach_credit_pct=25)
    provider = setup_provider(clinic["id"])
    resp = api.create_dictation_job(
        create_dictation_job_payload(provider["id"], priority="STAT",
                                     audio_duration_seconds=90),
        make_provider_headers(provider["id"]))
    job = validate_success(resp, 201)
    assert job["workflow_status"] == "QUEUED"
    assert job["escalation_level"] == "NONE"
    assert job["claimed_by_editor_id"] is None
    assert iso_seconds_prefix(job["created_at"]) == "2026-08-01T00:00:00"
    assert iso_seconds_prefix(job["due_at"]) == "2026-08-01T02:00:00", (
        f"due_at must be created_at + 120 min, got {job['due_at']}")
    assert job["asr_char_estimate"] == 180, (
        "PRD §3.3: the draft size estimate `asr_char_estimate` is exactly twice "
        "the `audio_duration_seconds`, at two characters per second of audio")


def test_submit_from_queued_returns_job_not_editing(api):
    """PRD §2.6: "when the owner field being compared is null — for example,
    the `claimed_by_editor_id` of an unclaimed job — the ownership check is
    vacuous and evaluation proceeds to the state gates, so a submission
    attempted on a job that is still `QUEUED` fails with
    `ERR_JOB_NOT_EDITING`, not with an ownership error."

    Design: Corner/state_machines/submit_from_queued_returns_job_not_editing
    """
    wg = setup_workgroup()
    job = create_job(wg["provider"])
    editor = wg["editor"]
    resp = api.submit_job(job["id"], create_submit_payload(),
                          make_editor_headers(editor["id"]))
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_EDITING)
    transcripts = validate_success(
        api.list_transcripts(VENDOR, params={"dictation_job_id": job["id"]}))
    assert transcripts == [], "no transcript may be created by a rejected submit"


def test_claim_cancelled_job_returns_not_queued(api):
    """PRD §3.3: "Cancelling a `QUEUED` job simply moves it to `CANCELLED`."
    PRD §3.3: "`CANCELLED` is terminal."
    PRD §3.4: "The claim is gated by a strict battery of checks: the job must
    be `QUEUED` (`ERR_JOB_NOT_QUEUED`); the editor must not be `SUSPENDED`
    (`ERR_EDITOR_NOT_ACTIVE`); if the job's priority is `STAT`, the editor's
    status must be `ACTIVE` — a `PROBATION` editor is a quality risk and is
    refused with `ERR_PROBATION_STAT_FORBIDDEN`; the editor's
    `active_claim_count` must be strictly below their `max_concurrent_claims`
    (`ERR_EDITOR_CAPACITY_FULL`); and the current logical time must fall inside
    at least one declared availability window of that editor
    (`ERR_OUTSIDE_SHIFT_WINDOW`)."

    Design: Corner/state_machines/claim_cancelled_job_returns_not_queued
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    cancelled = validate_success(api.cancel_job(
        job["id"], make_provider_headers(provider["id"])))
    assert cancelled["workflow_status"] == "CANCELLED"
    resp = api.claim_job(job["id"], {"editor_id": editor["id"]},
                         make_editor_headers(editor["id"]))
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_QUEUED)
    assert get_editor(editor["id"])["active_claim_count"] == 0


def test_qa_on_editing_job_returns_not_submitted(api):
    """PRD §3.5: "The review payload names the `dictation_job_id` under review
    — the job must be `SUBMITTED`, otherwise `ERR_JOB_NOT_SUBMITTED` — and
    three error tallies: `critical_error_count`, `major_error_count`, and
    `minor_error_count`, each of which must be zero or greater."

    Design: Corner/state_machines/qa_on_editing_job_returns_not_submitted
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    claim_job(job["id"], editor)
    resp = api.create_qa_review(create_qa_review_payload(job["id"]),
                                TEST_USERS["qa_supervisor_headers"])
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_SUBMITTED)
    reviews = validate_success(api.list_job_qa_reviews(job["id"], VENDOR))
    assert reviews == [], "no QAReview may be recorded for a rejected review"
    assert get_editor(editor["id"])["qa_review_count"] == 0


def test_job_cancel_from_submitted_returns_not_cancellable(api):
    """PRD §3.3: "A queued or in-progress job may be cancelled by its owning
    provider or by a `VendorAdmin`; a job in any other state is rejected with
    `ERR_JOB_NOT_CANCELLABLE`."

    Design: Corner/errors/job_cancel_from_submitted_returns_not_cancellable
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    claim_job(job["id"], editor)
    submit_job(job["id"], editor)
    resp = api.cancel_job(job["id"], make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_CANCELLABLE)
    assert get_job(job["id"])["workflow_status"] == "SUBMITTED"


def test_vendor_admin_release_on_behalf_of_editor(api):
    """PRD §3.4: "Releasing is the compensating action of claiming, available
    to the editor holding the job or to a `VendorAdmin`, and valid only while
    the job is `EDITING` (`ERR_JOB_NOT_EDITING`). The job returns from
    `EDITING` to `QUEUED`, its claim fields are cleared, and the editor's
    `active_claim_count` is decremented."

    Design: Corner/endpoints/vendor_admin_release_on_behalf_of_editor
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    claim_job(job["id"], editor)
    released = validate_success(api.release_job(job["id"], VENDOR))
    assert released["workflow_status"] == "QUEUED"
    assert released["claimed_by_editor_id"] is None
    assert get_editor(editor["id"])["active_claim_count"] == 0


def test_cancel_editing_job_releases_claim_compensation(api):
    """PRD §3.3: "Cancelling a `QUEUED` job simply moves it to `CANCELLED`.
    Cancelling an `EDITING` job additionally performs claim compensation:
    `claimed_by_editor_id` and `claimed_at` are cleared, and the holding
    editor's `active_claim_count` is decremented."

    Design: Corner/endpoints/cancel_editing_job_releases_claim_compensation
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    j1 = create_job(provider)
    j2 = create_job(provider)
    claim_job(j1["id"], editor)
    headers = make_provider_headers(provider["id"])
    c1 = validate_success(api.cancel_job(j1["id"], headers))
    c2 = validate_success(api.cancel_job(j2["id"], headers))
    assert c1["workflow_status"] == "CANCELLED"
    assert c2["workflow_status"] == "CANCELLED"
    assert get_editor(editor["id"])["active_claim_count"] == 0


def test_claim_with_mismatched_editor_id_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `Editor`, `X-User-ID` is the `id` of
    the acting Editor; ownership checks compare the request's `editor_id`
    (when claiming a job or declaring an availability window) or the job's
    `claimed_by_editor_id` (when submitting or releasing a claimed job) to
    `X-User-ID`."
    PRD §2.6: "Ownership comes next for the entity-backed roles, as described
    in §2.1, and a mismatch yields `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/validations/claim_with_mismatched_editor_id_forbidden
    """
    wg = setup_workgroup()
    e1 = wg["editor"]
    e2 = setup_editor(display_name="Editor Two", wide_window=False)
    job = create_job(wg["provider"])
    resp = api.claim_job(job["id"], {"editor_id": e2["id"]},
                         make_editor_headers(e1["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)


def test_claim_at_capacity_returns_capacity_full(api):
    """PRD §3.4: "the editor's `active_claim_count` must be strictly below
    their `max_concurrent_claims` (`ERR_EDITOR_CAPACITY_FULL`)"
    PRD §3.4: "the new editor starts `ACTIVE`, with a `rolling_quality_score`
    of 100.0, a `qa_review_count` of zero, a provisional `skill_tier` of
    `TIER_2` until five reviews have accumulated, a `max_concurrent_claims` of
    3, and an `active_claim_count` of zero."

    Design: Corner/validations/claim_at_capacity_returns_capacity_full
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    jobs = [create_job(provider) for _ in range(4)]
    for job in jobs[:3]:
        claim_job(job["id"], editor)
    resp = api.claim_job(jobs[3]["id"], {"editor_id": editor["id"]},
                         make_editor_headers(editor["id"]))
    validate_error(resp, ApiErrorId.ERR_EDITOR_CAPACITY_FULL)
    assert get_editor(editor["id"])["active_claim_count"] == 3


def test_claim_outside_shift_window_returns_temporal_error(api):
    """PRD §3.4: "the current logical time must fall inside at least one
    declared availability window of that editor (`ERR_OUTSIDE_SHIFT_WINDOW`)."

    Design: Corner/validations/claim_outside_shift_window_returns_temporal_error
    """
    clinic = setup_clinic()
    add_sla_policy(clinic["id"])
    provider = setup_provider(clinic["id"])
    editor = setup_editor(wide_window=False)
    validate_success(api.create_editor_shift_window(
        create_shift_window_payload(
            editor["id"], start_at="2026-08-03T00:00:00Z",
            end_at="2026-08-04T00:00:00Z"),
        make_editor_headers(editor["id"])), 201)
    job = create_job(provider)
    resp = api.claim_job(job["id"], {"editor_id": editor["id"]},
                         make_editor_headers(editor["id"]))
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_SHIFT_WINDOW)
    assert get_job(job["id"])["workflow_status"] == "QUEUED"


def test_claim_release_conserves_claim_count_and_due_at(api):
    """PRD §3.4: "Releasing is the compensating action of claiming, available
    to the editor holding the job or to a `VendorAdmin`, and valid only while
    the job is `EDITING` (`ERR_JOB_NOT_EDITING`). The job returns from
    `EDITING` to `QUEUED`, its claim fields are cleared, and the editor's
    `active_claim_count` is decremented."
    PRD §3.3: "The deadline `due_at` is fixed at creation as the job's
    `created_at` plus the governing policy's `tat_minutes`, and it is never
    recomputed afterwards — rework, preemption, and provider returns all leave
    the original deadline untouched."

    Design: Difficulty/compensating_invariant/claim_release_conserves_active_claim_count
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    assert get_editor(editor["id"])["active_claim_count"] == 0
    job = create_job(provider)
    due_at_create = job["due_at"]
    claim_job(job["id"], editor)
    validate_success(api.release_job(job["id"], make_editor_headers(editor["id"])))
    assert get_editor(editor["id"])["active_claim_count"] == 0
    after = get_job(job["id"])
    assert after["workflow_status"] == "QUEUED"
    assert after["claimed_by_editor_id"] is None
    assert after["claimed_at"] is None
    assert after["due_at"] == due_at_create


def test_claim_release_version_increments_once_per_mutation(api):
    """PRD §2.5: "`version` (integer): a system-managed integer that increments
    with every modification to the resource, and which anchors optimistic
    concurrency control where §2.7 applies."
    PRD §2.5: "Any mutation of a resource — including system-driven mutations
    such as a preemption clearing a job's claim fields, a sweep rewriting a
    provider's status, or a template supersession bumping a provider —
    refreshes that resource's `updated_at` and increments its `version`."

    Design: Difficulty/compensating_invariant/claim_release_conserves_active_claim_count
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    v_create = job["version"]
    claim_job(job["id"], editor)
    validate_success(api.release_job(job["id"], make_editor_headers(editor["id"])))
    after = get_job(job["id"])
    assert after["version"] == v_create + 2, (
        f"create, claim, release each increment exactly once: expected "
        f"{v_create + 2}, got {after['version']}")


def test_dictation_jobs_list_pagination_and_filter(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return. If not provided, it defaults to 10, with a minimum of 1 and a
    maximum of 100. The `offset` parameter specifies the number of items to
    skip and defaults to 0."
    PRD §2.3: "Unless otherwise specified, all list endpoints return resources
    sorted by their creation timestamp in ascending order."
    PRD §2.10: "The dictation-job listing supports filters by `provider_id`,
    `clinic_account_id`, `claimed_by_editor_id`, `template_id`, and
    `workflow_status`, and the transcript listing by `dictation_job_id` and
    `editor_id`; both accept the standard `limit` and `offset` pagination
    parameters of §2.3."

    Design: Corner/entities/dictation_jobs_list_pagination_and_filter
    """
    wg = setup_workgroup()
    provider = wg["provider"]
    j_a = create_job(provider)
    set_clock("2026-08-01T00:00:01Z")
    j_b = create_job(provider)

    page1, meta1 = validate_paginated(api.list_dictation_jobs(
        VENDOR, params={"provider_id": provider["id"], "limit": 1}))
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert page1[0]["id"] == j_a["id"], "created_at ASC: first page holds J_A"

    page2, meta2 = validate_paginated(api.list_dictation_jobs(
        VENDOR, params={"provider_id": provider["id"], "limit": 1, "offset": 1}))
    assert len(page2) == 1
    assert page2[0]["id"] == j_b["id"], "created_at ASC: second page holds J_B"
    assert meta2["has_more"] is False
