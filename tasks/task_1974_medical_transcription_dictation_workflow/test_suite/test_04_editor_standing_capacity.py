"""Editor standing ladder, rolling quality window, and capacity preemption."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_workgroup, setup_probation_editor, setup_capacity_cascade,
    create_job, claim_job, submit_job, review_job, drive_editor_reviews,
    get_job, get_editor, get_job_transcripts,
    make_provider_headers, make_editor_headers, TEST_USERS,
)

VENDOR = TEST_USERS["vendor_admin_headers"]


def test_rework_cycle_burns_transcript_versions(api):
    """PRD §3.5: "The transcript records its owning `dictation_job_id`, the
    authoring `editor_id` — the claiming editor at submit time, which becomes
    the segregation-of-duties anchor for quality review — and a
    `version_number` that starts at 1 for the job's first submission and
    increases by one with each subsequent submission."
    PRD §3.5: "On a `FAIL`, the current transcript version moves to
    `REJECTED`, the job returns from `SUBMITTED` to `EDITING` while remaining
    claimed by the same editor — so `active_claim_count` does not change — and
    the job's `rework_count` is incremented by one."

    Design: Difficulty/non_linear_state_machine/dictation_job_rework_cycle
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    claim_job(job["id"], editor)
    submit_job(job["id"], editor)
    review_job(job["id"], 1, 0, 0)   # FAIL -> v1 REJECTED, back to EDITING
    submit_job(job["id"], editor)
    review_job(job["id"], 1, 0, 0)   # FAIL -> v2 REJECTED, back to EDITING
    submit_job(job["id"], editor)
    review = review_job(job["id"], 0, 1, 0)  # 95.0 PASS -> v3 DELIVERED
    assert review["outcome"] == "PASS"
    after = get_job(job["id"])
    assert after["workflow_status"] == "DELIVERED"
    assert after["rework_count"] == 2, "two full EDITING->SUBMITTED->EDITING loops"
    versions = {(t["version_number"], t["status"])
                for t in get_job_transcripts(job["id"])}
    assert versions == {(1, "REJECTED"), (2, "REJECTED"), (3, "DELIVERED")}, (
        f"expected v1/v2 REJECTED and v3 DELIVERED, got {versions}")


def test_rework_loops_do_not_disturb_standing_before_five_reviews(api):
    """PRD §3.6: "Standing transitions are evaluated only once an editor has at
    least five reviews; before that, the editor's standing is not disturbed and
    the `skill_tier` remains its provisional `TIER_2`."

    Design: Difficulty/non_linear_state_machine/dictation_job_rework_cycle
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    job = create_job(provider)
    claim_job(job["id"], editor)
    for _ in range(2):
        submit_job(job["id"], editor)
        review_job(job["id"], 1, 0, 0)  # FAIL each time
    submit_job(job["id"], editor)
    review_job(job["id"], 0, 1, 0)  # PASS on the third submission
    editor_after = get_editor(editor["id"])
    assert editor_after["qa_review_count"] == 3
    assert editor_after["status"] == "ACTIVE", (
        "rework loops alone never trigger standing evaluation below 5 reviews")
    assert editor_after["skill_tier"] == "TIER_2"


def test_editor_falls_to_probation_below_85(api):
    """PRD §3.6: "From `ACTIVE`, an editor falls to `PROBATION` when the
    rolling score drops below 85, and falls directly to `SUSPENDED` when it
    drops below 70."
    PRD §3.6: "the system takes the twenty most recent reviews of that
    editor's transcripts — any outcome counts — ordered by creation time
    descending with `editor_sequence` descending as the tie-break, and sets
    `rolling_quality_score` to the mean of the `accuracy_score` values across
    that window, rounded half-up to two decimal places."

    Design: Difficulty/non_linear_state_machine/editor_standing_probation_recovery_cycle
    """
    wg = setup_probation_editor()  # five reviews of 84.0 (m=3, i=1)
    editor = get_editor(wg["editor"]["id"])
    assert editor["qa_review_count"] == 5
    assert editor["rolling_quality_score"] == pytest.approx(84.00, abs=0.001)
    assert editor["status"] == "PROBATION", "5 x 84.0 -> rolling 84.00 < 85"
    assert editor["skill_tier"] == "TIER_1"
    assert editor["max_concurrent_claims"] == 1


def test_editor_recovers_to_active_at_exactly_90(api):
    """PRD §3.6: "From `PROBATION`, an editor climbs back to `ACTIVE` when the
    rolling score reaches at least 90, but drops to `SUSPENDED` when the
    rolling score is below 75 or when the latest review contains any critical
    error at all."
    PRD §3.6: "the `skill_tier` follows from the rolling score: `TIER_3` at 95
    or above, `TIER_2` at 85 or above but below 95, and `TIER_1` below 85."

    Design: Difficulty/non_linear_state_machine/editor_standing_probation_recovery_cycle
    """
    wg = setup_probation_editor()
    provider, editor = wg["provider"], wg["editor"]
    # Review 6 (100.0): rolling (420+100)/6 = 86.67 — still PROBATION (< 90).
    drive_editor_reviews(provider, editor, [(0, 0, 0)])
    mid = get_editor(editor["id"])
    assert mid["rolling_quality_score"] == pytest.approx(86.67, abs=0.001)
    assert mid["status"] == "PROBATION"
    # Review 7 (100.0): rolling 620/7 = 88.57 — still PROBATION.
    drive_editor_reviews(provider, editor, [(0, 0, 0)])
    mid2 = get_editor(editor["id"])
    assert mid2["rolling_quality_score"] == pytest.approx(88.57, abs=0.001)
    assert mid2["status"] == "PROBATION"
    # Review 8 (100.0): rolling 720/8 = 90.00 — recovery boundary is inclusive.
    drive_editor_reviews(provider, editor, [(0, 0, 0)])
    final = get_editor(editor["id"])
    assert final["rolling_quality_score"] == pytest.approx(90.00, abs=0.001)
    assert final["status"] == "ACTIVE", "rolling >= 90 recovers PROBATION -> ACTIVE"
    assert final["skill_tier"] == "TIER_2"
    assert final["max_concurrent_claims"] == 3


def test_capacity_reevaluation_editor_end_state(api):
    """PRD §3.6: "every standing change — whether from a review or from
    reinstatement — triggers a capacity reevaluation with a pinned evaluation
    order: the rolling score (already recomputed by the caller), then the
    standing transition, then the `skill_tier`, then `max_concurrent_claims`,
    and only then preemption."
    PRD §3.6: "Capacity follows from the tier: a `TIER_1` editor may hold 1
    concurrent claim, a `TIER_2` editor 3, a `TIER_3` editor 5, and a
    `SUSPENDED` editor 0."

    Design: Difficulty/combinatorial_formula/capacity_reevaluation_pinned_order
    """
    fx = setup_capacity_cascade()
    editor = fx["editor"]
    review = review_job(fx["j_r"]["id"], 1, 0, 0)  # 75.0 FAIL, 5th review
    assert review["accuracy_score"] == pytest.approx(75.0, abs=0.001)
    assert review["outcome"] == "FAIL"
    after = get_editor(editor["id"])
    assert after["rolling_quality_score"] == pytest.approx(79.00, abs=0.001), (
        "(80*4 + 75)/5 == 79.00")
    assert after["status"] == "PROBATION", "step (2): 79.00 < 85 -> PROBATION"
    assert after["skill_tier"] == "TIER_1", "step (3): rolling < 85 -> TIER_1"
    assert after["max_concurrent_claims"] == 1, "step (4): TIER_1 -> 1"
    assert after["active_claim_count"] == 1, "step (5): 3 - 1 = 2 jobs preempted"


def test_capacity_preemption_survivor_set(api):
    """PRD §3.6: "If the editor's `active_claim_count` now exceeds
    `max_concurrent_claims`, the excess number of the editor's `EDITING` jobs
    is force-released. The preemption selector ranks that editor's `EDITING`
    jobs by priority ascending — `ROUTINE` first, then `URGENT`, then `STAT` —
    breaking ties by `claimed_at` descending so the most recently claimed job
    is released first, and any remaining ties by job `created_at` descending.
    Each preempted job moves from `EDITING` back to `QUEUED`, its
    `claimed_by_editor_id` and `claimed_at` are cleared, its `preempted_count`
    is incremented, and the editor's `active_claim_count` is decremented
    accordingly."

    Design: Difficulty/combinatorial_formula/capacity_reevaluation_pinned_order
    """
    fx = setup_capacity_cascade()
    review_job(fx["j_r"]["id"], 1, 0, 0)
    j_r = get_job(fx["j_r"]["id"])
    j_u1 = get_job(fx["j_u1"]["id"])
    j_u2 = get_job(fx["j_u2"]["id"])
    # ROUTINE-first: J_R preempted despite having just failed back to EDITING.
    assert j_r["workflow_status"] == "QUEUED"
    assert j_r["rework_count"] == 1
    assert j_r["preempted_count"] == 1
    assert j_r["claimed_by_editor_id"] is None
    # URGENT tie broken by claimed_at DESC: J_U2 (00:03) preempted over J_U1.
    assert j_u2["workflow_status"] == "QUEUED"
    assert j_u2["preempted_count"] == 1
    # Sole survivor.
    assert j_u1["workflow_status"] == "EDITING"
    assert j_u1["preempted_count"] == 0


def test_editor_reinstate_preserves_rolling_and_rederives_capacity(api):
    """PRD §3.6: "A `SUSPENDED` editor never recovers automatically: only a
    `VendorAdmin` reinstatement returns the editor to `ACTIVE` — attempted on
    an editor who is not `SUSPENDED` it fails with `ERR_EDITOR_NOT_ACTIVE` —
    and reinstatement leaves the `rolling_quality_score` untouched while
    re-deriving the tier and capacity from the current score."

    Design: Corner/state_machines/editor_reinstate_preserves_rolling_and_rederives_capacity
    """
    wg = setup_probation_editor()  # 5 x 84.0 -> PROBATION
    provider, editor = wg["provider"], wg["editor"]
    j6 = create_job(provider)
    claim_job(j6["id"], editor)
    submit_job(j6["id"], editor)
    review_job(j6["id"], 1, 0, 0)  # 75.0 FAIL; latest critical > 0 while PROBATION
    suspended = get_editor(editor["id"])
    assert suspended["status"] == "SUSPENDED", (
        "PROBATION + latest review with critical errors -> SUSPENDED")
    assert suspended["rolling_quality_score"] == pytest.approx(82.50, abs=0.001), (
        "(84*5 + 75)/6 == 82.50")
    assert suspended["max_concurrent_claims"] == 0
    j6_after = get_job(j6["id"])
    assert j6_after["workflow_status"] == "QUEUED", "suspension preempted the job"
    assert j6_after["preempted_count"] == 1

    reinstated = validate_success(api.reinstate_editor(editor["id"], VENDOR))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["rolling_quality_score"] == pytest.approx(82.50, abs=0.001), (
        "reinstatement leaves the rolling score untouched")
    assert reinstated["skill_tier"] == "TIER_1", "re-derived from 82.50, not reset"
    assert reinstated["max_concurrent_claims"] == 1


def test_rolling_window_limits_to_20_reviews(api):
    """PRD §3.6: "Quality review feeds a rolling reputation for each editor.
    After every recorded review, the system takes the twenty most recent
    reviews of that editor's transcripts — any outcome counts — ordered by
    creation time descending with `editor_sequence` descending as the
    tie-break, and sets `rolling_quality_score` to the mean of the
    `accuracy_score` values across that window, rounded half-up to two decimal
    places."
    PRD §3.6: "the `skill_tier` follows from the rolling score: `TIER_3` at 95
    or above, `TIER_2` at 85 or above but below 95, and `TIER_1` below 85."

    Design: Corner/calculations/rolling_window_limits_to_20_reviews
    """
    wg = setup_workgroup()
    provider, editor = wg["provider"], wg["editor"]
    # Review 1: score 0.0 (4 criticals). The failed job stays claimed, so
    # release it (VendorAdmin may release any editor's job).
    j0 = create_job(provider)
    claim_job(j0["id"], editor)
    submit_job(j0["id"], editor)
    review_job(j0["id"], 4, 0, 0)
    validate_success(api.release_job(j0["id"], VENDOR))
    # Reviews 2..21: twenty reviews of 100.0 each.
    drive_editor_reviews(provider, editor, [(0, 0, 0)] * 20)
    after = get_editor(editor["id"])
    assert after["qa_review_count"] == 21
    assert after["rolling_quality_score"] == pytest.approx(100.00, abs=0.001), (
        "the initial 0.0 review fell out of the 20-review window")
    assert after["skill_tier"] == "TIER_3", "rolling >= 95"
    assert after["max_concurrent_claims"] == 5
    assert after["status"] == "ACTIVE"


def test_probation_editor_may_claim_routine_job(api):
    """PRD §3.4: "if the job's priority is `STAT`, the editor's status must be
    `ACTIVE` — a `PROBATION` editor is a quality risk and is refused with
    `ERR_PROBATION_STAT_FORBIDDEN`"
    PRD §3.4: "A successful claim moves the job from `QUEUED` to `EDITING`,
    stamps `claimed_by_editor_id` with the editor and `claimed_at` with the
    current time, sets `first_claimed_at` if it has never been set — that
    first-claim instant is the anchor of the `PRODUCTION_WINDOW` turnaround
    measurement — and increments the editor's `active_claim_count` by one."

    Design: Difficulty/cross_entity_state_dependency/claim_gated_by_editor_standing
    """
    wg = setup_probation_editor()  # PROBATION, rolling 84.00
    editor = wg["editor"]
    assert get_editor(editor["id"])["status"] == "PROBATION"
    job = create_job(wg["provider"], priority="ROUTINE")
    claimed = validate_success(api.claim_job(
        job["id"], {"editor_id": editor["id"]}, make_editor_headers(editor["id"])))
    assert claimed["workflow_status"] == "EDITING", (
        "PROBATION gates only STAT claims; a ROUTINE claim succeeds")


def test_suspended_editor_claim_rejected_and_jobs_preempted(api):
    """PRD §3.6: "From `PROBATION`, an editor climbs back to `ACTIVE` when the
    rolling score reaches at least 90, but drops to `SUSPENDED` when the
    rolling score is below 75 or when the latest review contains any critical
    error at all."
    PRD §3.4: "The claim is gated by a strict battery of checks: the job must
    be `QUEUED` (`ERR_JOB_NOT_QUEUED`); the editor must not be `SUSPENDED`
    (`ERR_EDITOR_NOT_ACTIVE`); if the job's priority is `STAT`, the editor's
    status must be `ACTIVE` — a `PROBATION` editor is a quality risk and is
    refused with `ERR_PROBATION_STAT_FORBIDDEN`; the editor's
    `active_claim_count` must be strictly below their `max_concurrent_claims`
    (`ERR_EDITOR_CAPACITY_FULL`); and the current logical time must fall inside
    at least one declared availability window of that editor
    (`ERR_OUTSIDE_SHIFT_WINDOW`)."

    Design: Difficulty/cross_entity_state_dependency/claim_gated_by_editor_standing
    """
    wg = setup_probation_editor()  # PROBATION, rolling 84.00
    provider, editor = wg["provider"], wg["editor"]
    j_ok = create_job(provider)
    claim_job(j_ok["id"], editor)
    submit_job(j_ok["id"], editor)
    review_job(j_ok["id"], 1, 0, 0)  # critical > 0 while PROBATION -> SUSPENDED
    suspended = get_editor(editor["id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["max_concurrent_claims"] == 0
    preempted = get_job(j_ok["id"])
    assert preempted["workflow_status"] == "QUEUED", (
        "SUSPENDED -> max 0 -> held job preempted back to the queue")
    assert preempted["preempted_count"] == 1
    j2 = create_job(provider)
    resp = api.claim_job(j2["id"], {"editor_id": editor["id"]},
                         make_editor_headers(editor["id"]))
    validate_error(resp, ApiErrorId.ERR_EDITOR_NOT_ACTIVE)
