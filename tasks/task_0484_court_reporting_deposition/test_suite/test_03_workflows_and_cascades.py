"""Lifecycle workflows and cascades: the cyclic read-and-sign/errata loop, the
branching job paths (cancel vs run-and-adjourn), the adjourn depth-3 cascade
(complete -> price), the cancel depth-2 cascade (release -> revert posture),
and the compensating invariants (release+reassign role count, void+recreate
invoice total).
"""
from test_helpers import (
    validate_success,
    validate_paginated,
    setup_reporter_job,
    setup_confirmed_reporter_job,
    setup_read_sign_open_transcript,
    run_session,
    cancel_job,
    file_errata,
    open_read_sign,
    create_invoice,
    issue_invoice,
    add_assignment,
    make_billing_clerk_headers,
    make_schedule_coordinator_headers,
)

BILLING = make_billing_clerk_headers()
COORD = make_schedule_coordinator_headers()


# ---------------------------------------------------------------------------
# Rule 3 — non-linear (cyclic) state machine + branching job
# ---------------------------------------------------------------------------
def test_read_sign_errata_cycle_increments_round_twice(api):
    """PRD §3.10: "Filing creates the errata sheet, stamping its `round` to the
    transcript's current `errata_round` plus one, increments the transcript's
    `errata_round` by one, and moves the order to `ERRATA_FILED`." PRD §3.10: "To
    exchange another round, the `ScheduleCoordinator` re-opens the window,
    transitioning the order back from `ERRATA_FILED` to `READ_SIGN_OPEN`... this
    loop may repeat." Two errata rounds drive errata_round to 2 and status to
    ERRATA_FILED.

    Design: Difficulty/non_linear_state_machine/transcript_read_sign_errata_cycle_multiple_rounds
    """
    sc, _ = setup_read_sign_open_transcript(
        jurisdiction="STATE_CA", turnaround_tier="STANDARD",
        certified_copy=True, estimated_pages=30, final_pages=30)
    file_errata(sc, corrections=[{"page": 4, "line": 12, "from_text": "fife", "to_text": "five"}],
                reason="transcription error round 1")
    open_read_sign(sc)
    file_errata(sc, corrections=[{"page": 7, "line": 3, "from_text": "to", "to_text": "two"}],
                reason="transcription error round 2")
    to = validate_success(api.get_transcript_order(sc.transcript_order_id, COORD))
    assert to["errata_round"] == 2, f"errata_round should be 2, got {to['errata_round']}"
    assert to["status"] == "ERRATA_FILED", (
        f"status should be ERRATA_FILED, got {to['status']}")


def test_job_cancel_branch_releases_without_fee(api):
    """PRD §3.5: "Cancelling a job... cascades every `ACTIVE` assignment on the
    job to `RELEASED`." PRD §3.2: "Its `appearance_fee_cents` field is present
    from creation but holds 0 until the job adjourns and the fee is computed."
    The cancel branch RELEASES the assignment with no appearance fee.

    Design: Difficulty/non_linear_state_machine/job_branching_cancel_vs_session_path_diverge
    """
    sc = setup_confirmed_reporter_job(
        scheduled_start="2026-06-06T09:00:00Z",
        scheduled_end="2026-06-06T11:00:00Z",
        hourly_appearance_cents=10000)
    cancel_job(sc.job_id)
    job = validate_success(api.get_job(sc.job_id, COORD))
    asg = validate_success(api.get_assignment(sc.assignment_id, COORD))
    assert job["status"] == "CANCELLED", f"job should be CANCELLED, got {job['status']}"
    assert asg["status"] == "RELEASED", f"assignment should be RELEASED, got {asg['status']}"
    assert asg["appearance_fee_cents"] == 0, (
        f"cancelled-branch assignment should have 0 fee, got {asg['appearance_fee_cents']}")


def test_job_session_branch_completes_and_prices(api):
    """PRD §3.5: "Adjournment also fires a multi-part cascade: first, every
    `ACTIVE` assignment on the job transitions to `COMPLETED`; second, each newly
    completed assignment has its `appearance_fee_cents` computed from the job's
    `actual_start` and `actual_end` as described in §3.6." The run-and-adjourn
    branch COMPLETES the assignment and prices it (2h @10000=20000).

    Design: Difficulty/non_linear_state_machine/job_branching_cancel_vs_session_path_diverge
    """
    sc = setup_confirmed_reporter_job(
        scheduled_start="2026-06-06T09:00:00Z",
        scheduled_end="2026-06-06T11:00:00Z",
        hourly_appearance_cents=10000)
    run_session(sc.job_id, "2026-06-06T09:00:00Z", "2026-06-06T11:00:00Z")
    asg = validate_success(api.get_assignment(sc.assignment_id, COORD))
    assert asg["status"] == "COMPLETED", (
        f"run-branch assignment should be COMPLETED, got {asg['status']}")
    assert asg["appearance_fee_cents"] == 20000, (
        f"2h @10000 should price to 20000, got {asg['appearance_fee_cents']}")


# ---------------------------------------------------------------------------
# Rule 4 — transitive cascade chains
# ---------------------------------------------------------------------------
def test_adjourn_cascade_completes_then_prices_assignment(api):
    """PRD §3.5: "first, every `ACTIVE` assignment on the job transitions to
    `COMPLETED`; second, each newly completed assignment has its
    `appearance_fee_cents` computed from the job's `actual_start` and
    `actual_end`." A 2h actual session @10000 yields COMPLETED + 20000.

    Design: Difficulty/transitive_cascade/adjourn_cascade_completes_assignment_then_computes_fee_depth3
    """
    sc = setup_confirmed_reporter_job(
        scheduled_start="2026-06-07T09:00:00Z",
        scheduled_end="2026-06-07T13:00:00Z",
        hourly_appearance_cents=10000)
    run_session(sc.job_id, "2026-06-07T09:00:00Z", "2026-06-07T11:00:00Z")
    asg = validate_success(api.get_assignment(sc.assignment_id, BILLING))
    assert asg["status"] == "COMPLETED", (
        f"adjourn cascade should complete the assignment, got {asg['status']}")
    assert asg["appearance_fee_cents"] == 20000, (
        f"2h @10000 cascade fee should be 20000, got {asg['appearance_fee_cents']}")


def test_cancel_cascade_releases_then_reverts_posture(api):
    """PRD §3.5: "Cancellation moves the job to `CANCELLED`, cascades every
    `ACTIVE` assignment on the job to `RELEASED` (which frees each resource's time
    window for future overlap checks), recomputes the staffing posture down to
    `UNSTAFFED`." Cancel from CONFIRMED releases the assignment and reverts posture
    to UNSTAFFED.

    Design: Difficulty/transitive_cascade/cancel_cascade_releases_assignment_then_reverts_posture_depth2
    """
    sc = setup_confirmed_reporter_job(
        scheduled_start="2026-06-08T09:00:00Z",
        scheduled_end="2026-06-08T11:00:00Z",
        hourly_appearance_cents=10000)
    cancel_job(sc.job_id)
    job = validate_success(api.get_job(sc.job_id, COORD))
    asg = validate_success(api.get_assignment(sc.assignment_id, COORD))
    assert job["status"] == "CANCELLED", f"job should be CANCELLED, got {job['status']}"
    assert job["staffing_posture"] == "UNSTAFFED", (
        f"posture should revert to UNSTAFFED, got {job['staffing_posture']}")
    assert asg["status"] == "RELEASED", f"assignment should be RELEASED, got {asg['status']}"


# ---------------------------------------------------------------------------
# Rule 9 — compensating-action invariants
# ---------------------------------------------------------------------------
def test_release_then_reassign_conserves_reporter_role_count(api):
    """PRD §3.3: "Releasing moves the assignment from `ACTIVE` to `RELEASED`...
    and triggers a recomputation of the parent job's staffing posture." PRD §3.4:
    "If every required role is covered, the posture is `READY`." After releasing
    the reporter and re-assigning a new one, exactly one ACTIVE REPORTER remains
    and posture is READY.

    Design: Difficulty/compensating_invariant/release_then_reassign_conserves_reporter_role_count
    """
    sc = setup_reporter_job(
        scheduled_start="2026-06-17T09:00:00Z",
        scheduled_end="2026-06-17T11:00:00Z")
    # Second reporter for the compensating re-assignment.
    sc2 = setup_reporter_job(scheduled_start="2026-09-01T09:00:00Z",
                             scheduled_end="2026-09-01T11:00:00Z")
    new_reporter_id = sc2.reporter_id
    validate_success(api.release_assignment(sc.assignment_id, COORD))
    add_assignment(sc.job_id, new_reporter_id, "REPORTER")
    job = validate_success(api.get_job(sc.job_id, COORD))
    assert job["staffing_posture"] == "READY", (
        f"posture should remain READY after release+reassign, got {job['staffing_posture']}")
    rows, _ = validate_paginated(
        api.list_job_assignments(sc.job_id, COORD, params={"status": "ACTIVE"}))
    active_reporters = sum(1 for a in rows if a["role"] == "REPORTER")
    assert active_reporters == 1, (
        f"exactly one ACTIVE REPORTER should remain, got {active_reporters}")


def test_void_then_recreate_conserves_invoice_total(api):
    """PRD §3.14: "An invoice can also be voided from either `DRAFT` or `ISSUED`."
    PRD §3.14: "On issue, all three subtotals and the grand total are recomputed
    and frozen from current job, transcript, and exhibit state." Voiding an issued
    invoice and issuing a fresh one for the same job/transcript yields an identical
    total_cents (TX EXPEDITE_14 60p no-exhibit, reporter @15000 + videographer
    @8000, 2h => 70625).

    Design: Difficulty/compensating_invariant/void_then_recreate_conserves_invoice_total_cents
    """
    # TX EXPEDITE_14 60p job billed with a reporter @15000 and videographer @8000
    # over a 2h session; transcript delivered; first invoice issued.
    sc2, inv1 = _setup_tx_two_resource_issued_invoice(api)
    validate_success(api.void_invoice(inv1["id"], BILLING))
    voided = validate_success(api.get_invoice(inv1["id"], BILLING))
    assert voided["status"] == "VOID", f"first invoice should be VOID, got {voided['status']}"
    create_invoice(sc2)
    inv2 = issue_invoice(sc2)
    assert inv2["total_cents"] == 70625, (
        f"recreated invoice total should reconcile to 70625, got {inv2['total_cents']}")


def _setup_tx_two_resource_issued_invoice(api):
    """TX EXPEDITE_14 60p job billed with a reporter @15000 + videographer @8000
    over a 2h session, transcript delivered, invoice created and issued."""
    from test_helpers import (
        make_attorney, make_case, make_reporter, make_videographer, make_job,
        add_assignment, confirm_job, run_session, order_transcript, deliver_rough,
        certify, sign, deliver_transcript, JobScenario,
    )
    att = make_attorney()
    case = make_case(att["id"], jurisdiction="STATE_TX")
    rep = make_reporter(hourly_appearance_cents=15000, certifications=["RPR"])
    vid = make_videographer(hourly_appearance_cents=8000)
    job = make_job(case["id"], scheduled_start="2026-06-18T09:00:00Z",
                   scheduled_end="2026-06-18T12:00:00Z", requires_videographer=True)
    sc = JobScenario(attorney_id=att["id"], case_id=case["id"], reporter_id=rep["id"],
                     job_id=job["id"], jurisdiction="STATE_TX")
    sc.assignment_id = add_assignment(job["id"], rep["id"], "REPORTER")["id"]
    sc.videographer_id = vid["id"]
    sc.videographer_assignment_id = add_assignment(job["id"], vid["id"], "VIDEOGRAPHER")["id"]
    confirm_job(job["id"])
    run_session(job["id"], "2026-06-18T09:00:00Z", "2026-06-18T11:00:00Z")
    order_transcript(sc, turnaround_tier="EXPEDITE_14", certified_copy=True,
                     estimated_pages=60)
    deliver_rough(sc)
    certify(sc, final_pages=60)
    open_read_sign(sc)
    sign(sc)
    deliver_transcript(sc)
    create_invoice(sc)
    inv = issue_invoice(sc)
    return sc, inv
