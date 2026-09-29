"""Findings, the escalation freeze, and the corrective action plan cycle."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    OFFICER,
    PROJECT_OFFICER,
    adjudicate_corrective_action_plan_payload,
    advance_clock,
    api_client,
    lock_scope_baseline,
    make_project_officer_headers,
    refresh_fee_schedule,
    refresh_finding,
    refresh_health_center,
    refresh_scope_change_request,
    refresh_service_site,
    same_instant,
    setup_boot_fs,
    setup_draft_corrective_action_plan,
    setup_draft_scope_change_request,
    setup_open_finding,
    setup_proposed_site,
    submit_scope_change_request,
    validate_error,
    validate_success,
)


def _adjudicate(plan_id, decision, headers, rejection_reason=None):
    payload = adjudicate_corrective_action_plan_payload(decision)
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return api_client.adjudicate_corrective_action_plan(plan_id, payload, headers)


def _submit_plan(plan_id):
    return api_client.submit_corrective_action_plan(plan_id, OFFICER)


def _refresh_plan(plan_id):
    return validate_success(
        api_client.get_corrective_action_plan(plan_id, OFFICER)
    )


def _scope_work_awaiting_review_and_an_overdue_condition():
    """A submitted add-site request plus a CONDITION finding one day past its due date."""
    ctx = setup_boot_fs()
    lock_scope_baseline(ctx)
    annex = setup_proposed_site(
        ctx,
        site_name="Eastside Annex",
        address_line="88 East Ave",
        weekly_service_hours=20,
    )
    request = setup_draft_scope_change_request(
        ctx, request_type="ADD_SITE", target_site_id=annex["id"]
    )
    submit_scope_change_request(request, OFFICER)
    finding = setup_open_finding(
        ctx,
        requirement_code="CLIN-002",
        severity="CONDITION",
        cap_due_days=30,
        service_site_id=ctx["site_id"],
        finding_summary="credentialing files incomplete",
    )
    advance_clock("2026-09-01T00:00:00Z")
    ctx.update({"annex": annex, "annex_id": annex["id"], "request": request, "finding": finding})
    return ctx


def _sweep():
    return validate_success(api_client.run_compliance_sweep(ADMIN))


def test_the_sweep_escalates_the_overdue_condition_and_freezes_the_award():
    """Hops one through three: the finding escalates, conditions land, scope freezes.

    PRD 3.8: "The first hop stamps `escalated_at` with the logical clock and
    recomputes the grantee's `open_condition_count`. The second hop follows: because
    that count has become greater than zero, the grantee's `operational_status` moves
    `ACTIVE → CONDITIONS_IMPOSED`. The third hop follows: because conditions are now
    imposed, the grantee's `scope_posture` moves `OPEN → CHANGE_FROZEN` and the
    grantee's `version` increments by one."

    Design: Difficulty/transitive_cascade/finding_escalation_freezes_scope_and_holds_target_site_depth_five
    """
    ctx = _scope_work_awaiting_review_and_an_overdue_condition()
    assert same_instant(ctx["finding"]["cap_due_at"]) == "2026-08-31T00:00:00Z", (
        "cap_due_at is created_at plus cap_due_days days on the logical clock, got "
        f"{ctx['finding']['cap_due_at']}"
    )

    counts = _sweep()
    assert counts["escalated_finding_count"] == 1
    assert counts["expired_verification_count"] == 0
    assert counts["expired_fee_schedule_count"] == 0
    assert counts["recomputed_health_center_count"] == 1

    escalated = refresh_finding(ctx["finding"]["id"])
    assert escalated["status"] == "ESCALATED"
    assert same_instant(escalated["escalated_at"]) == "2026-09-01T00:00:00Z"

    health_center = refresh_health_center(ctx["health_center_id"])
    assert health_center["open_condition_count"] == 1
    assert health_center["operational_status"] == "CONDITIONS_IMPOSED"
    assert health_center["scope_posture"] == "CHANGE_FROZEN"


def test_the_freeze_parks_the_pending_request_and_puts_its_target_site_on_hold():
    """Hops four and five reach two rows the caller never addressed.

    PRD 3.8: "The fourth hop follows: because scope froze, every change-in-scope
    request of that grantee whose `status` is `SUBMITTED` or `UNDER_REVIEW` is parked
    — `SUBMITTED → HELD` or `UNDER_REVIEW → HELD` — with the departed status recorded
    in `held_from_status` so that the compensating cascade can restore it exactly.
    The fifth hop follows from the fourth: because those requests were parked, every
    `ADD_SITE` request's target site sitting at `PROPOSED` moves `PROPOSED → ON_HOLD`
    with `hold_reason` set to `SCOPE_FROZEN`."

    Design: Difficulty/transitive_cascade/finding_escalation_freezes_scope_and_holds_target_site_depth_five
    """
    ctx = _scope_work_awaiting_review_and_an_overdue_condition()
    _sweep()

    parked = refresh_scope_change_request(ctx["request"]["id"])
    assert parked["status"] == "HELD"
    assert parked["held_from_status"] == "SUBMITTED", (
        "the departed status is recorded so it can be restored exactly, got "
        f"{parked['held_from_status']}"
    )

    held_site = refresh_service_site(ctx["annex_id"])
    assert held_site["status"] == "ON_HOLD"
    assert held_site["hold_reason"] == "SCOPE_FROZEN"

    assert refresh_health_center(ctx["health_center_id"])["in_scope_site_count"] == 1, (
        "the held site never entered scope, so the baseline count is untouched"
    )
    assert refresh_fee_schedule(ctx["fee_schedule_id"])["review_status"] == "CURRENT", (
        "31 elapsed days is well inside the review window and the guideline year "
        "is still the latest published one"
    )


def _plan_rejected_three_times():
    """A progress-report finding whose plan has been submitted and rejected three times."""
    ctx = setup_boot_fs()
    finding = setup_open_finding(
        ctx,
        requirement_code="GOV-014",
        severity="PROGRESS_REPORT_ONLY",
        cap_due_days=30,
        finding_summary="board minutes incomplete",
    )
    plan = setup_draft_corrective_action_plan(
        finding,
        narrative="adopt a minutes template",
        milestone_count=3,
        target_completion_date="2026-08-20T00:00:00Z",
    )
    rounds = []
    for reason in ("no owner named", "milestones not dated", "still unacceptable"):
        submitted = validate_success(_submit_plan(plan["id"]))
        rounds.append(submitted["submit_round"])
        validate_success(_adjudicate(plan["id"], "REJECT", PROJECT_OFFICER, reason))
    ctx.update({"finding": finding, "plan": plan, "rounds": rounds})
    return ctx


def test_the_plan_submit_round_is_capped_two_rungs_tighter_than_the_scope_cycle():
    """Two loop passes exhaust the plan cycle; the third resubmission is refused.

    PRD 3.8: "The same operation is also the loop edge `REJECTED → SUBMITTED`, which
    increments `submit_round` by one, clears `rejection_reason` and
    `adjudicated_by_user_id`, and again drives the parent finding to `CAP_SUBMITTED`.
    This loop is capped tighter than the others: resubmission is permitted only while
    `submit_round` is below 2, and a third pass is rejected with
    `ERR_LOOP_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/corrective_action_plan_reject_resubmit_cycle_capped_at_two_rounds
    """
    ctx = _plan_rejected_three_times()
    assert same_instant(ctx["finding"]["cap_due_at"]) == "2026-08-31T00:00:00Z"
    assert ctx["rounds"] == [0, 1, 2], (
        "the DRAFT to SUBMITTED edge does not count as a resubmission, got "
        f"{ctx['rounds']}"
    )

    validate_error(
        _submit_plan(ctx["plan"]["id"]),
        ApiErrorId.ERR_LOOP_LIMIT_EXCEEDED.value,
    )

    final = _refresh_plan(ctx["plan"]["id"])
    assert final["status"] == "REJECTED"
    assert final["submit_round"] == 2


def test_a_rejection_returns_a_never_escalated_finding_to_open():
    """Each lap ping-pongs the parent finding, which is only possible before escalation.

    PRD 3.8: "`REJECT` moves the plan `SUBMITTED → REJECTED`, stores the
    `rejection_reason`, and returns the parent finding to `OPEN` when that finding had
    *never* been escalated — the edge `CAP_SUBMITTED → OPEN` — while a finding that
    has been escalated at any point stays `ESCALATED` instead."

    Design: Difficulty/non_linear_state_machine/corrective_action_plan_reject_resubmit_cycle_capped_at_two_rounds
    """
    ctx = _plan_rejected_three_times()

    finding = refresh_finding(ctx["finding"]["id"])
    assert finding["status"] == "OPEN", (
        f"the finding ping-pongs back to OPEN, got {finding['status']}"
    )
    assert finding["escalated_at"] is None

    health_center = refresh_health_center(ctx["health_center_id"])
    assert health_center["open_condition_count"] == 0, (
        "a progress-report finding is never escalatable and never counts as a "
        "condition on the award"
    )
    assert health_center["operational_status"] == "ACTIVE"
    assert health_center["scope_posture"] == "OPEN"


def _accepted_plan_on_a_resolved_finding():
    """A plan submitted by the preparer and accepted by the reviewing officer."""
    ctx = setup_boot_fs()
    finding = setup_open_finding(
        ctx,
        requirement_code="FIN-007",
        severity="PROGRESS_REPORT_ONLY",
        cap_due_days=30,
        finding_summary="cost report late",
    )
    plan = setup_draft_corrective_action_plan(
        finding,
        narrative="hire an interim controller",
        milestone_count=2,
        target_completion_date="2026-08-25T00:00:00Z",
    )
    validate_success(_submit_plan(plan["id"]))
    accepted = validate_success(_adjudicate(plan["id"], "ACCEPT", PROJECT_OFFICER))
    ctx.update({"finding": finding, "plan": plan, "accepted": accepted})
    return ctx


def test_re_adjudicating_a_terminal_plan_reports_the_state_rule_not_the_duties_rule():
    """Both rules would reject and both answer 409, so only the error identifier tells.

    PRD 2.12: "And because the state check at rung 11 sits above every safety and
    fiscal rule, an action aimed at a row in the wrong state always reports
    `ERR_INVALID_STATE_TRANSITION`, even when a later rule would also have rejected
    it." PRD 3.8 supplies the duties rule: "Adjudication belongs to a
    `ProjectOfficer` who is not the plan's preparer, driven by a `decision` field
    carrying `ACCEPT` or `REJECT`, with an optional `rejection_reason`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_transition_beats_segregation_of_duties_on_terminal_plan
    """
    ctx = _accepted_plan_on_a_resolved_finding()
    assert ctx["accepted"]["status"] == "ACCEPTED"

    response = _adjudicate(
        ctx["plan"]["id"],
        "REJECT",
        make_project_officer_headers("co-1"),
        "second thoughts",
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)


def test_the_refused_re_adjudication_leaves_the_plan_and_its_finding_terminal():
    """The accepted plan and its resolved finding are untouched by the refusal.

    PRD 3.8: "`ACCEPT` moves the plan `SUBMITTED → ACCEPTED`, which is terminal,
    records the adjudicating officer in `adjudicated_by_user_id`, and moves the parent
    finding `CAP_SUBMITTED → RESOLVED`, also terminal."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_transition_beats_segregation_of_duties_on_terminal_plan
    """
    ctx = _accepted_plan_on_a_resolved_finding()

    validate_error(
        _adjudicate(
            ctx["plan"]["id"],
            "REJECT",
            make_project_officer_headers("co-1"),
            "second thoughts",
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    )

    plan = _refresh_plan(ctx["plan"]["id"])
    assert plan["status"] == "ACCEPTED"
    assert plan["adjudicated_by_user_id"] == "po-1", (
        "the adjudicator recorded is the officer who accepted the plan, got "
        f"{plan['adjudicated_by_user_id']}"
    )
    assert refresh_finding(ctx["finding"]["id"])["status"] == "RESOLVED"
    assert refresh_health_center(ctx["health_center_id"])["open_condition_count"] == 0


def _submitted_plan_against_the_escalated_finding():
    """The full escalation state, answered by a plan now awaiting adjudication."""
    ctx = _scope_work_awaiting_review_and_an_overdue_condition()
    sweep = _sweep()
    before = refresh_health_center(ctx["health_center_id"])
    plan = setup_draft_corrective_action_plan(
        ctx["finding"],
        narrative="re-credential all providers",
        milestone_count=4,
        target_completion_date="2026-08-30T00:00:00Z",
    )
    submitted = validate_success(_submit_plan(plan["id"]))
    ctx.update(
        {
            "sweep": sweep,
            "before": before,
            "plan": plan,
            "submitted_plan": submitted,
            "finding_at_submission": refresh_finding(ctx["finding"]["id"]),
        }
    )
    return ctx


def test_accepting_the_plan_clears_the_condition_and_returns_the_award_to_active():
    """The first two compensating hops undo the counter and both grantee postures.

    PRD 3.8: "The first hop recomputes the grantee's `open_condition_count` as the
    number of that grantee's findings whose `status` is `ESCALATED`, which matters when
    the resolved finding had itself been escalated. The second hop follows: because
    `open_condition_count` has reached zero, the grantee's `operational_status`
    returns `CONDITIONS_IMPOSED → ACTIVE`, its `scope_posture` returns `CHANGE_FROZEN
    → OPEN`, and its `version` increments by one."

    Design: Difficulty/compensating_invariant/cap_acceptance_restores_scope_cardinalities_and_releases_every_held_row
    """
    ctx = _submitted_plan_against_the_escalated_finding()
    assert ctx["sweep"]["escalated_finding_count"] == 1
    assert ctx["before"]["open_condition_count"] == 1
    assert ctx["before"]["operational_status"] == "CONDITIONS_IMPOSED"
    assert ctx["before"]["scope_posture"] == "CHANGE_FROZEN"
    assert ctx["before"]["in_scope_site_count"] == 1
    assert ctx["submitted_plan"]["status"] == "SUBMITTED"
    assert ctx["finding_at_submission"]["status"] == "CAP_SUBMITTED", (
        "an escalated finding still moves to CAP_SUBMITTED while its plan is "
        "under consideration"
    )

    accepted = validate_success(_adjudicate(ctx["plan"]["id"], "ACCEPT", PROJECT_OFFICER))
    assert accepted["status"] == "ACCEPTED"

    resolved = refresh_finding(ctx["finding"]["id"])
    assert resolved["status"] == "RESOLVED"
    assert resolved["escalated_at"] is not None, (
        "the escalation is remembered even though the condition is cleared"
    )

    health_center = refresh_health_center(ctx["health_center_id"])
    assert health_center["open_condition_count"] == 0
    assert health_center["operational_status"] == "ACTIVE"
    assert health_center["scope_posture"] == "OPEN"


def test_accepting_the_plan_releases_the_held_request_and_its_site_without_drift():
    """The third and fourth hops restore the parked rows exactly and clear the markers.

    PRD 3.8: "The third hop follows from the second: because scope reopened, every
    parked change-in-scope request of that grantee leaves `HELD` and returns to
    whatever status its `held_from_status` records — `HELD → SUBMITTED` when it records
    `SUBMITTED`, `HELD → UNDER_REVIEW` when it records `UNDER_REVIEW` — and
    `held_from_status` is cleared. The fourth hop follows from the third: because those
    requests left the parked state, every target site sitting at `ON_HOLD` returns
    `ON_HOLD → PROPOSED` and its `hold_reason` is cleared."

    Design: Difficulty/compensating_invariant/cap_acceptance_restores_scope_cardinalities_and_releases_every_held_row
    """
    ctx = _submitted_plan_against_the_escalated_finding()

    validate_success(_adjudicate(ctx["plan"]["id"], "ACCEPT", PROJECT_OFFICER))

    released = refresh_scope_change_request(ctx["request"]["id"])
    assert released["status"] == "SUBMITTED", (
        "the request returns to the status its held_from_status recorded, got "
        f"{released['status']}"
    )
    assert released["held_from_status"] is None, (
        "the marker is cleared so the restore cannot be replayed"
    )

    site = refresh_service_site(ctx["annex_id"])
    assert site["status"] == "PROPOSED"
    assert site["hold_reason"] is None

    health_center = refresh_health_center(ctx["health_center_id"])
    assert health_center["in_scope_site_count"] == 1, (
        "the cardinalities are restored exactly, with no drift"
    )
    assert health_center["in_scope_service_count"] == 1
