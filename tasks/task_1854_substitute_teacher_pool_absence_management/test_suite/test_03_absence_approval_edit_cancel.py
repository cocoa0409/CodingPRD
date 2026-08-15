"""Absence approval dimension: PENDING gates dispatch, district review
unblocks it, date edits force re-approval, and cancel is refused once the
absence is ASSIGNED."""
from test_helpers import (
    ApiErrorId,
    accepted_assignment_ctx,
    assert_absence,
    basic_world,
    get_absence,
    make_coordinator_headers,
    onboard_substitute,
    report_absence,
    review_absence,
    run_dispatch_batch,
    validate_error,
    validate_success,
)


def test_absence_cancel_rejected_while_assigned(api):
    """PRD 3.3: "A teacher may cancel their own absence, and a coordinator or
    district admin any absence, while its `fill_status` is `REPORTED`,
    `DISPATCHING`, `UNFILLED`, or `COVERED_INTERNALLY`; from `ASSIGNED`,
    `COMPLETED`, `CLOSED`, or an existing `CANCELLED` the attempt fails with
    `ERR_ABSENCE_INVALID_STATE` — an accepted assignment must first be
    released at the assignment level."

    Design: Corner/state_machines/absence_cancel_rejected_while_assigned
    """
    ctx = accepted_assignment_ctx(start_date="2026-08-03", end_date="2026-08-03")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])

    res = api.cancel_absence(ctx["absence"]["id"], coord_headers)
    validate_error(res, ApiErrorId.ERR_ABSENCE_INVALID_STATE, expected_status=409)

    absence = get_absence(ctx["absence"]["id"])
    assert absence["fill_status"] == "ASSIGNED"
    assignment = validate_success(
        api.get_assignment(ctx["assignment"]["id"], coord_headers), 200
    )
    assert assignment["status"] == "ACCEPTED"


def test_pending_approval_gates_dispatch_then_approve_unblocks(api, district_admin_headers):
    """PRD 3.3: "while it is `PENDING` — or has been `REJECTED` — dispatch
    batches, manual offers, and self-claims are all blocked, surfacing
    `ERR_ABSENCE_INVALID_STATE`."
    PRD 3.4: "Third, pick-up: eligible `REPORTED` and `UNFILLED` absences —
    approval clear of `PENDING`/`REJECTED`, `end_date` not yet past, and zero
    internal-coverage days — move to `DISPATCHING`, and the selector of §2.11
    runs for each, creating at most one offer per absence per batch."

    Design: Corner/state_machines/pending_approval_gates_dispatch_then_approve_unblocks
    """
    ctx = basic_world(with_coordinator=False)
    ctx["sub"] = onboard_substitute()
    absence = report_absence(
        ctx["teacher"], start_date="2026-08-03", end_date="2026-08-10"
    )
    assert absence["approval_status"] == "PENDING"

    first_batch = run_dispatch_batch(ctx["district"]["id"], run_for_date="2026-07-29")
    assert first_batch["offers_created"] == 0, (
        "PENDING approval makes the absence invisible to the batch"
    )
    assert get_absence(absence["id"])["fill_status"] == "REPORTED"

    reviewed = review_absence(absence["id"], "APPROVE")
    assert reviewed["approval_status"] == "APPROVED"

    second_batch = run_dispatch_batch(ctx["district"]["id"], run_for_date="2026-07-29")
    assert second_batch["offers_created"] == 1
    assert get_absence(absence["id"])["fill_status"] == "DISPATCHING"


def test_approved_absence_date_edit_forces_reapproval(api):
    """PRD 3.3: "A successful edit increments the absence's `version` by one,
    recomputes `total_days`, and re-runs the approval computation — which cuts
    both ways: stretching an `APPROVED`, `NOT_REQUIRED`, or even `REJECTED`
    absence past the approval threshold drops it back to `PENDING`, where it
    must be re-approved before any further dispatch, offer, or claim;
    shrinking a `PENDING` absence to within the threshold restores
    `NOT_REQUIRED`."

    Design: Corner/state_machines/approved_absence_date_edit_forces_reapproval
    """
    ctx = basic_world()
    absence = report_absence(
        ctx["teacher"], start_date="2026-08-03", end_date="2026-08-10"
    )
    reviewed = review_absence(absence["id"], "APPROVE")
    assert reviewed["approval_status"] == "APPROVED"
    observed_version = reviewed["version"]

    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    edited = validate_success(
        api.update_absence(
            absence["id"],
            {"expected_absence_version": observed_version, "end_date": "2026-08-11"},
            coord_headers,
        ),
        200,
    )
    assert_absence(edited)
    assert edited["total_days"] == 7
    assert edited["approval_status"] == "PENDING", (
        "stretching an APPROVED absence past the threshold reopens approval"
    )
    assert edited["version"] == observed_version + 1
    assert edited["fill_status"] == "REPORTED"
