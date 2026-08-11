"""Proof submission, the revision loop, segregation of duties and the 30-day window."""

from test_helpers import (
    ApiErrorId,
    CAMPAIGN_MANAGER,
    SINGLE_RECORD_ROSTER,
    approve_proof,
    assert_proof,
    assert_same_instant,
    build_addressed_scenario,
    build_mailing_list,
    create_account,
    create_campaign,
    create_handwriting_style,
    create_proof,
    create_template,
    expected_expiry,
    headers_for,
    mail_job_payload,
    make_account_owner_headers,
    read_mail_job,
    read_proof,
    set_clock,
    submit_proof,
    template_version,
    validate_error,
    validate_success,
)
from test_helpers import api_client, get_success_data


def _job_with_draft_proof(permit_number, target_in_home_date="2026-06-15"):
    """One ADDRESSED job whose only proof is still in DRAFT."""
    world = build_addressed_scenario(
        permit_number=permit_number, roster=SINGLE_RECORD_ROSTER, list_name="Mini List",
        dedupe_mode=None, lock=False, stage="draft",
        target_in_home_date=target_in_home_date, topup_cents=None,
    )
    world["proof"] = create_proof(world["job"]["id"], world["template"]["id"])
    return world


def _two_jobs_each_with_a_live_approval(permit_number="PMT-141"):
    """Two jobs on one locked list, each approved at the clock's default instant."""
    set_clock()
    account = create_account(permit_number=permit_number)
    style = create_handwriting_style()
    template = create_template(account["id"], style["id"])
    campaign = create_campaign(account["id"])
    mailing_list, _ = build_mailing_list(
        account["id"], roster=SINGLE_RECORD_ROSTER, name="Mini List",
        cass=True, dedupe_mode="EXACT", lock=True,
    )

    jobs, proofs = [], []
    for target in ("2026-06-15", "2026-06-16"):
        job = get_success_data(
            api_client.create_mail_job(
                mail_job_payload(campaign["id"], template["id"],
                                 mailing_list_id=mailing_list["id"],
                                 target_in_home_date=target),
                CAMPAIGN_MANAGER,
            )
        )
        proof = create_proof(job["id"], template["id"])
        submit_proof(proof["id"])
        approve_proof(proof["id"], account["id"], template_id=template["id"])
        jobs.append(read_mail_job(job["id"]))
        proofs.append(read_proof(proof["id"]))
    return {"account": account, "template": template, "jobs": jobs, "proofs": proofs}


def test_rejecting_a_submitted_proof_stores_the_reason_and_leaves_the_job_in_draft(api):
    """PRD §3.5: "**Rejection** is likewise an `AccountOwner` act, requires an open
    write gate and a `SUBMITTED` proof, carries a mandatory `reject_reason` that is
    stored on the proof, moves it `SUBMITTED → REJECTED`, and increments its
    `version`."
    PRD §3.5: "Submitting moves the proof `DRAFT → SUBMITTED`, snapshots
    `pinned_template_version` from the template's current content revision counter
    `version_no`, records `submitted_by_user_id` as the submitting caller's
    `X-User-ID`, and increments the proof's `version`."

    Design: Difficulty/non_linear_state_machine/proof_reject_then_resubmit_revision_loop
    """
    world = _job_with_draft_proof("PMT-110")
    proof_id = world["proof"]["id"]

    submitted = validate_success(
        api.submit_proof(proof_id, headers_for("CampaignManager", "cm-1"))
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["pinned_template_version"] == 1
    assert submitted["submitted_by_user_id"] == "cm-1"

    rejected = validate_success(
        api.reject_proof(
            proof_id, {"reject_reason": "salutation is wrong"},
            make_account_owner_headers(world["account"]["id"]),
        )
    )
    assert_proof(rejected)
    assert rejected["status"] == "REJECTED"
    assert rejected["reject_reason"] == "salutation is wrong"
    assert read_mail_job(world["job"]["id"])["status"] == "DRAFT"


def test_resubmitting_after_a_content_edit_repins_the_revision_and_then_approves(api):
    """PRD §3.5: "The `REJECTED → SUBMITTED` edge behaves identically and re-pins
    `pinned_template_version` to whatever `version_no` the template carries at
    that moment, which is the point of the revision loop: the manager fixes the
    copy, the template's revision counter advances, and the resubmitted proof
    binds to the corrected content."
    PRD §3.5: "The owning mail job moves `DRAFT → PROOFED` and takes the proof's
    `pinned_template_version` as its own."
    PRD §3.2: "**Hop 1** — `version_no` increases by exactly one."

    Design: Difficulty/non_linear_state_machine/proof_reject_then_resubmit_revision_loop
    """
    world = _job_with_draft_proof("PMT-110")
    proof_id = world["proof"]["id"]
    template_id = world["template"]["id"]

    submit_proof(proof_id)
    validate_success(
        api.reject_proof(
            proof_id, {"reject_reason": "salutation is wrong"},
            make_account_owner_headers(world["account"]["id"]),
        )
    )

    edited = validate_success(
        api.patch_template(template_id, {"body_text": "Thank you very kindly"},
                           CAMPAIGN_MANAGER)
    )
    assert edited["version_no"] == 2

    resubmitted = validate_success(
        api.submit_proof(proof_id, headers_for("CampaignManager", "cm-1"))
    )
    assert resubmitted["pinned_template_version"] == 2, "the resubmit re-pins the revision"

    approved = validate_success(
        api.approve_proof(
            proof_id, {"expected_template_version": edited["version"]},
            make_account_owner_headers(world["account"]["id"]),
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["pinned_template_version"] == 2

    job = read_mail_job(world["job"]["id"])
    assert job["status"] == "PROOFED"
    assert job["pinned_template_version"] == 2


def test_an_approval_one_second_short_of_expiry_still_schedules_the_job(api):
    """PRD §3.5: "On success the proof moves `SUBMITTED → APPROVED`,
    `approved_by_user_id` is set to the approver's `X-User-ID`, `approved_at` is
    set to the logical clock's current instant, and `expires_at` is set to exactly
    thirty days after `approved_at`."
    PRD §3.5: "The first is **expiry**: once the logical clock reaches or passes
    `expires_at`, an `APPROVED` proof becomes `EXPIRED`, and the boundary is
    inclusive — an instant exactly equal to `expires_at` is already expired."

    Design: Difficulty/boundary_precision_check/proof_approval_expiry_inclusive_boundary
    """
    world = _two_jobs_each_with_a_live_approval()
    job_a, proof_a = world["jobs"][0], world["proofs"][0]
    assert_same_instant(proof_a["approved_at"], "2026-05-01T00:00:00Z", "approved_at")
    assert_same_instant(
        proof_a["expires_at"], expected_expiry(proof_a["approved_at"]).isoformat(),
        "expires_at",
    )

    set_clock("2026-05-30T23:59:59Z")
    scheduled = validate_success(
        api.schedule_mail_job(job_a["id"], {"target_in_home_date": "2026-06-15"},
                              CAMPAIGN_MANAGER)
    )
    assert scheduled["status"] == "SCHEDULED"
    # MARKETING_MAIL transit is 10 days: 2026-06-15 less 10 days is 2026-06-05.
    assert scheduled["mail_date"] == "2026-06-05"
    assert read_proof(proof_a["id"])["status"] == "APPROVED"


def test_an_instant_exactly_equal_to_expires_at_is_already_stale(api):
    """PRD §3.5: "The first is **expiry**: once the logical clock reaches or passes
    `expires_at`, an `APPROVED` proof becomes `EXPIRED`, and the boundary is
    inclusive — an instant exactly equal to `expires_at` is already expired."
    PRD §3.5: "Rung 25 asks whether the job's most recent approval is **still
    live** — that its proof's status is `APPROVED` rather than `SUPERSEDED` or
    `EXPIRED`, that its `pinned_template_version` still equals the template's
    current `version_no`, and that the logical clock is strictly before its
    `expires_at`. If an approval exists but fails any of those, the answer is
    `ERR_PROOF_APPROVAL_STALE` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/proof_approval_expiry_inclusive_boundary
    """
    world = _two_jobs_each_with_a_live_approval()
    job_b, proof_b = world["jobs"][1], world["proofs"][1]
    assert_same_instant(proof_b["expires_at"], "2026-05-31T00:00:00Z", "expires_at")

    set_clock("2026-05-31T00:00:00Z")
    response = api.schedule_mail_job(
        job_b["id"], {"target_in_home_date": "2026-06-16"}, CAMPAIGN_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_PROOF_APPROVAL_STALE.value)

    assert read_mail_job(job_b["id"])["status"] == "PROOFED"
    assert read_proof(proof_b["id"])["status"] == "EXPIRED"


def test_scheduling_a_job_whose_only_proof_is_still_draft_reports_not_approved(api):
    """PRD §3.5: "Rung 24 asks whether the job has **ever** had a proof reach
    `APPROVED`. If it has not, the answer is `ERR_PROOF_NOT_APPROVED` (HTTP 409)."
    PRD §3.6: "Or it may never have been approved at all, in which case rung 24
    answers `ERR_PROOF_NOT_APPROVED` — and this is the only path by which that
    error is reachable, since a job can enter `PROOFED` only through an approval
    in the first place."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_an_approved_proof_on_the_job
    """
    world = _job_with_draft_proof("PMT-150")

    response = api.schedule_mail_job(
        world["job"]["id"], {"target_in_home_date": "2026-06-15"}, CAMPAIGN_MANAGER
    )
    error = validate_error(response, ApiErrorId.ERR_PROOF_NOT_APPROVED.value)
    assert error["error_id"] != ApiErrorId.ERR_PROOF_APPROVAL_STALE.value


def test_the_refused_schedule_leaves_both_the_job_and_the_proof_where_they_were(api):
    """PRD §3.6: "A `DRAFT` job is deliberately admitted at rung 17 rather than
    refused there, and the reason is diagnostic: by letting a `DRAFT` job through
    the state gate, the ladder allows rungs 24 and 25 to explain *why* it cannot
    be scheduled instead of returning a bare state complaint."
    PRD §3.6: "On success it writes `mail_date` and `blackout_shifted_days` from
    the derivation, sets `scheduled_at` to the logical clock's current instant,
    and increments the job's `version`."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_an_approved_proof_on_the_job
    """
    world = _job_with_draft_proof("PMT-150")

    api.schedule_mail_job(
        world["job"]["id"], {"target_in_home_date": "2026-06-15"}, CAMPAIGN_MANAGER
    )

    proof = read_proof(world["proof"]["id"])
    assert proof["status"] == "DRAFT"
    assert proof["approved_at"] is None

    job = read_mail_job(world["job"]["id"])
    assert job["status"] == "DRAFT"
    assert job["mail_date"] is None
    assert job["scheduled_at"] is None


def test_approving_a_proof_that_was_never_submitted_is_a_proof_state_failure(api):
    """PRD §3.5: "A proof is created against a `mail_job_id` and the `template_id`
    it renders, entering `status` `DRAFT` with `pinned_template_version`,
    `submitted_by_user_id`, `approved_by_user_id`, `approved_at`, `expires_at` and
    `reject_reason` all null."
    PRD §3.5: "and is evaluated in ladder order: the concurrency check at rung 11
    fires `ERR_STALE_VERSION` before the proof's own status is examined at rung 18,
    and the segregation-of-duties check at rung 23 fires
    `ERR_SEGREGATION_OF_DUTIES` only after the proof has been confirmed to be in
    `SUBMITTED`."

    Design: Corner/state_machines/proof_approve_from_draft_returns_proof_invalid_state
    """
    world = _job_with_draft_proof("PMT-214")
    live_version = template_version(world["template"]["id"])

    response = api.approve_proof(
        world["proof"]["id"], {"expected_template_version": live_version},
        make_account_owner_headers(world["account"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PROOF_INVALID_STATE.value)

    proof = read_proof(world["proof"]["id"])
    assert proof["status"] == "DRAFT"
    assert proof["approved_at"] is None
    assert read_mail_job(world["job"]["id"])["status"] == "DRAFT"


def test_the_submitter_of_a_proof_may_not_approve_it(api):
    """PRD §2.1: "The approving `X-User-ID` is compared against the
    `Proof.submitted_by_user_id` recorded at submission, and equality is refused
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §2.1: "One rule crosses role boundaries and deserves early mention: a
    proof may never be approved by the same person who submitted it."

    Design: Corner/rbac/proof_submitter_cannot_approve_own_proof
    """
    world = _job_with_draft_proof("PMT-254", target_in_home_date=None)
    account_id = world["account"]["id"]

    submitted = validate_success(
        api.submit_proof(world["proof"]["id"], headers_for("PlatformAdmin", account_id))
    )
    assert submitted["submitted_by_user_id"] == account_id

    response = api.approve_proof(
        world["proof"]["id"],
        {"expected_template_version": template_version(world["template"]["id"])},
        make_account_owner_headers(account_id),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    proof = read_proof(world["proof"]["id"])
    assert proof["status"] == "SUBMITTED"
    assert proof["approved_at"] is None
    assert read_mail_job(world["job"]["id"])["status"] == "DRAFT"


def test_an_approval_carrying_a_pre_edit_template_version_is_stale(api):
    """PRD §2.7: "**Approving a proof.** `POST /mail/proofs/{proof_id}/approve`
    requires `expected_template_version` matching the current `version` of the
    `Template` the proof renders."
    PRD §2.7: "Editing a template legitimately supersedes outstanding approvals,
    so an approval carrying a stale template version would bind the approver to
    content they never saw. A mismatch is `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_template_version_rejects_proof_approval
    """
    world = _job_with_draft_proof("PMT-260", target_in_home_date=None)
    template_id = world["template"]["id"]
    version_before_edit = world["template"]["version"]

    submit_proof(world["proof"]["id"])
    edited = validate_success(
        api.patch_template(template_id, {"body_text": "Thank you very kindly"},
                           CAMPAIGN_MANAGER)
    )
    assert edited["version"] != version_before_edit

    response = api.approve_proof(
        world["proof"]["id"], {"expected_template_version": version_before_edit},
        make_account_owner_headers(world["account"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    proof = read_proof(world["proof"]["id"])
    assert proof["status"] == "SUBMITTED"
    assert proof["pinned_template_version"] == 1
    assert edited["version_no"] == 2
    assert read_mail_job(world["job"]["id"])["status"] == "DRAFT"
