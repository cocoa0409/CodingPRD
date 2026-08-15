"""STAT preemption, escalation levels, and validation-priority conflicts."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_clinic, add_sla_policy, setup_provider, setup_editor,
    setup_capacity_cascade, create_job, claim_job, submit_job, review_job,
    drive_editor_reviews, set_clock, get_job, get_editor,
    make_provider_headers, make_editor_headers, TEST_USERS,
    iso_seconds_prefix,
)

VENDOR = TEST_USERS["vendor_admin_headers"]


def test_qa_fail_cascade_recomputes_editor_standing(api):
    """PRD §3.5: "The standing cascade still runs, and if the review drags the
    editor's standing down far enough to shrink capacity, this very job may be
    preempted out of the editor's hands immediately afterwards."
    PRD §3.6: "every standing change — whether from a review or from
    reinstatement — triggers a capacity reevaluation with a pinned evaluation
    order: the rolling score (already recomputed by the caller), then the
    standing transition, then the `skill_tier`, then `max_concurrent_claims`,
    and only then preemption."

    Design: Difficulty/transitive_cascade/qa_fail_standing_capacity_preemption_cascade
    """
    fx = setup_capacity_cascade()
    editor_id = fx["editor"]["id"]
    review = review_job(fx["j_r"]["id"], 1, 0, 0)
    assert review["outcome"] == "FAIL"
    editor = get_editor(editor_id)
    # Link 1: the review recomputed the rolling score.
    assert editor["rolling_quality_score"] == pytest.approx(79.00, abs=0.001)
    # Link 2: the new score transitioned standing.
    assert editor["status"] == "PROBATION"
    # Link 3: tier and capacity re-derived from the standing change.
    assert editor["skill_tier"] == "TIER_1"
    assert editor["max_concurrent_claims"] == 1


def test_qa_fail_cascade_preempts_excess_editing_jobs(api):
    """PRD §3.6: "If the editor's `active_claim_count` now exceeds
    `max_concurrent_claims`, the excess number of the editor's `EDITING` jobs
    is force-released. The preemption selector ranks that editor's `EDITING`
    jobs by priority ascending — `ROUTINE` first, then `URGENT`, then `STAT` —
    breaking ties by `claimed_at` descending so the most recently claimed job
    is released first, and any remaining ties by job `created_at` descending."
    PRD §3.5: "On a `FAIL`, the current transcript version moves to
    `REJECTED`, the job returns from `SUBMITTED` to `EDITING` while remaining
    claimed by the same editor — so `active_claim_count` does not change — and
    the job's `rework_count` is incremented by one."

    Design: Difficulty/transitive_cascade/qa_fail_standing_capacity_preemption_cascade
    """
    fx = setup_capacity_cascade()
    review_job(fx["j_r"]["id"], 1, 0, 0)
    j_r = get_job(fx["j_r"]["id"])
    j_u1 = get_job(fx["j_u1"]["id"])
    j_u2 = get_job(fx["j_u2"]["id"])
    editor = get_editor(fx["editor"]["id"])
    # Link 4: capacity shrink force-released two EDITING jobs; the FAILed job's
    # rework re-entry happened before preemption selection (rework_count == 1
    # alongside preempted_count == 1).
    assert j_r["workflow_status"] == "QUEUED"
    assert j_r["rework_count"] == 1
    assert j_r["preempted_count"] == 1
    assert j_u2["workflow_status"] == "QUEUED"
    assert j_u2["preempted_count"] == 1
    assert j_u1["workflow_status"] == "EDITING"
    assert editor["active_claim_count"] == 1


def test_stat_creation_preemption_selects_latest_claimed_job(api):
    """PRD §3.7: "The STAT preemption routine runs in two situations: inline at
    the creation of a `STAT` job (as §3.3 notes), and from the sweep whenever a
    `QUEUED` `STAT` job enters `CRITICAL`. The routine first measures the
    pool's free capacity: the sum, over every editor whose status is `ACTIVE`,
    of that editor's remaining headroom — `max_concurrent_claims` minus
    `active_claim_count`, floored at zero. If free capacity is zero, the
    routine looks for a victim among jobs currently `EDITING` whose priority is
    `ROUTINE` or `URGENT`, ranked by priority ascending — `ROUTINE` before
    `URGENT` — with ties broken by `claimed_at` descending and further ties by
    `created_at` descending."
    PRD §3.7: "The STAT job is then auto-assigned to the victim's former
    editor: it moves straight to `EDITING` with `claimed_by_editor_id` set to
    that editor, `claimed_at` stamped, `first_claimed_at` set if it was still
    null, and the editor's `active_claim_count` incremented — bypassing both
    the shift-window gate and the capacity ceiling that a manual claim would
    face."

    Design: Corner/calculations/stat_creation_preemption_selects_latest_claimed_job
    """
    clinic = setup_clinic()
    add_sla_policy(clinic["id"], priority="ROUTINE", tat_minutes=1440,
                   rate_per_line_cents=10, breach_credit_pct=5)
    add_sla_policy(clinic["id"], priority="STAT", tat_minutes=120,
                   rate_per_line_cents=20, breach_credit_pct=25)
    p1 = setup_provider(clinic["id"], full_name="P One")
    p2 = setup_provider(clinic["id"], full_name="P Two")
    editor = setup_editor()
    j1 = create_job(p1)
    j2 = create_job(p1)
    j3 = create_job(p1)
    set_clock("2026-08-01T00:01:00Z")
    claim_job(j1["id"], editor)
    set_clock("2026-08-01T00:02:00Z")
    claim_job(j2["id"], editor)
    set_clock("2026-08-01T00:03:00Z")
    claim_job(j3["id"], editor)  # active 3 == max 3 -> pool free capacity 0
    set_clock("2026-08-01T00:04:00Z")

    stat_job = create_job(p2, priority="STAT")
    assert stat_job["workflow_status"] == "EDITING", (
        "STAT job auto-assigned to the preempted editor")
    assert stat_job["claimed_by_editor_id"] == editor["id"]
    assert iso_seconds_prefix(stat_job["first_claimed_at"]) == "2026-08-01T00:04:00"
    j3_after = get_job(j3["id"])
    assert j3_after["workflow_status"] == "QUEUED"
    assert j3_after["claimed_by_editor_id"] is None
    assert j3_after["preempted_count"] == 1
    assert get_job(j1["id"])["workflow_status"] == "EDITING"
    assert get_job(j1["id"])["preempted_count"] == 0
    assert get_job(j2["id"])["workflow_status"] == "EDITING"
    assert get_job(j2["id"])["preempted_count"] == 0
    assert get_editor(editor["id"])["active_claim_count"] == 3


def test_escalation_levels_advance_with_clock(api):
    """PRD §3.7: "A job whose deadline has already arrived or passed — the
    current time is at or after `due_at` — is `CRITICAL`. A job not yet at its
    deadline but within its escalation buffer is `ESCALATED`; the buffer is one
    quarter of the governing policy's `tat_minutes`, computed by integer
    division in whole minutes with any fractional minute discarded, so the
    `ESCALATED` band opens when the current time reaches `due_at` minus that
    quarter-turnaround buffer and remains open until the deadline itself.
    Everything earlier stays at `NONE`."

    Design: Corner/state_machines/escalation_levels_advance_with_clock
    """
    clinic = setup_clinic()
    add_sla_policy(clinic["id"], priority="ROUTINE", tat_minutes=1440,
                   rate_per_line_cents=10, breach_credit_pct=5)
    provider = setup_provider(clinic["id"])
    job = create_job(provider, priority="ROUTINE")  # due 2026-08-02T00:00:00Z

    set_clock("2026-08-01T17:59:00Z")  # one minute before the 360-min buffer edge
    assert get_job(job["id"])["escalation_level"] == "NONE"
    set_clock("2026-08-01T18:00:00Z")  # == due_at - 360m, inclusive boundary
    assert get_job(job["id"])["escalation_level"] == "ESCALATED"
    set_clock("2026-08-02T00:00:00Z")  # == due_at, inclusive
    after = get_job(job["id"])
    assert after["escalation_level"] == "CRITICAL"
    assert after["workflow_status"] == "QUEUED", (
        "ROUTINE CRITICAL triggers no preemption")
    assert after["preempted_count"] == 0


def _setup_probation_editor_and_queued_stat():
    """Editor PROBATION (5 x 80.0) whose only window [07-01, 09-01) does not
    cover the trigger instant; a STAT job by another provider, still QUEUED."""
    clinic = setup_clinic()
    add_sla_policy(clinic["id"], priority="ROUTINE", tat_minutes=1440,
                   rate_per_line_cents=10, breach_credit_pct=5)
    add_sla_policy(clinic["id"], priority="STAT", tat_minutes=120,
                   rate_per_line_cents=20, breach_credit_pct=25)
    p1 = setup_provider(clinic["id"], full_name="P One")
    p2 = setup_provider(clinic["id"], full_name="P Two")
    editor = setup_editor()
    drive_editor_reviews(p1, editor, [(0, 4, 0)] * 5)  # rolling 80.00 -> PROBATION
    j_stat = create_job(p2, priority="STAT")  # no free ACTIVE capacity, no victim
    set_clock("2026-09-02T00:00:00Z")
    return clinic, p2, editor, j_stat


def test_probation_stat_claim_rejected_even_outside_window(api):
    """PRD §2.6: "Business rules close the pipeline, again in a fixed relative
    order: the segregation-of-duties check on quality review
    (`ERR_SELF_REVIEW_FORBIDDEN`) precedes the probationary-editor STAT gate
    (`ERR_PROBATION_STAT_FORBIDDEN`), which precedes editor capacity
    (`ERR_EDITOR_CAPACITY_FULL`), which precedes uniqueness constraints
    (`ERR_DUPLICATE_MACRO_SHORTCUT`, `ERR_DUPLICATE_SLA_POLICY`), which precede
    interval well-formedness (`ERR_INVALID_WINDOW`) and the temporal checks
    (`ERR_SHIFT_WINDOW_OVERLAP`, `ERR_OUTSIDE_SHIFT_WINDOW`,
    `ERR_BILLING_PERIOD_OVERLAP`), which precede the referential requirements
    that an SLA policy exist (`ERR_SLA_POLICY_MISSING`) and that a supplied
    template bind correctly to the job (`ERR_TEMPLATE_PROVIDER_MISMATCH`,
    `ERR_TEMPLATE_WORK_TYPE_MISMATCH`)."

    Design: Difficulty/priority_pair_validation_conflict/probation_stat_safety_beats_shift_window_temporal
    """
    _, _, editor, j_stat = _setup_probation_editor_and_queued_stat()
    assert get_editor(editor["id"])["status"] == "PROBATION"
    resp = api.claim_job(j_stat["id"], {"editor_id": editor["id"]},
                         make_editor_headers(editor["id"]))
    validate_error(resp, ApiErrorId.ERR_PROBATION_STAT_FORBIDDEN)


def test_probation_stat_rejection_leaves_job_queued(api):
    """PRD §3.4: "if the job's priority is `STAT`, the editor's status must be
    `ACTIVE` — a `PROBATION` editor is a quality risk and is refused with
    `ERR_PROBATION_STAT_FORBIDDEN`"

    Design: Difficulty/priority_pair_validation_conflict/probation_stat_safety_beats_shift_window_temporal
    """
    _, _, editor, j_stat = _setup_probation_editor_and_queued_stat()
    resp = api.claim_job(j_stat["id"], {"editor_id": editor["id"]},
                         make_editor_headers(editor["id"]))
    validate_error(resp, ApiErrorId.ERR_PROBATION_STAT_FORBIDDEN)
    after = get_job(j_stat["id"])
    assert after["workflow_status"] == "QUEUED"
    assert after["claimed_by_editor_id"] is None
    assert get_editor(editor["id"])["active_claim_count"] == 0
