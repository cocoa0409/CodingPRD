"""Compensating actions that must undo exactly what they compensate.

Withdrawing a scheduled change and closing a planned finding both reverse an
earlier operation, and both are graded on precision: they must give back the
calendar occupancy, the notification fan-out, the assignee's workload and the
domain's quality debt, and they must leave alone the applied-change history, the
audit numbers of the impact assessment and the severity weight pinned when the
finding was first opened.
"""

from test_helpers import (
    GOVERNANCE_ADMIN_HEADERS,
    assert_freeze_window_released,
    assert_instant_equals,
    refresh_domain,
    setup_domain_with_open_critical_finding,
    setup_notified_scheduled_change,
    validate_success,
)

WITHDRAW_REASON = "Segment taxonomy postponed to the Q4 release"
PLAN_NOTE = "Backfill the contact attributes from the ERP nightly extract"
RESOLUTION_NOTE = "Attribute backfill verified against the certified ERP extract"


def test_scheduled_reference_value_change_reserves_a_twelve_hour_trailing_window(api):
    """PRD §3.8: "The derived boolean `structural` is true for exactly the two
    non-additive types, `HIERARCHY_RESTRUCTURE` and `CLASSIFICATION_UPLIFT`, and
    false for `REFERENCE_VALUE_ADD`; it is never supplied by the client."
    PRD §3.8: "In other words, a structural change impacts every active consumer
    regardless of criticality, whereas a plain reference-value addition impacts
    only the `TIER1` consumers."
    PRD §3.8: "Sixth — and this ordering is normative — the greater of the base
    lead and the floor lead is taken *first*, the two surcharges are added to
    that, and only then is the result capped at thirty days; the capped figure is
    stored as `required_lead_days`."
    PRD §3.8: "Finally, `earliest_apply_at` is set to `submitted_at` advanced by
    `required_lead_days` whole days."
    PRD §3.8: "The freeze window is a closed interval around that instant whose
    extent depends on whether the change is structural: a structural change
    reserves 24 hours of lead before the instant and 48 hours of trail after it,
    while a non-structural change reserves no lead at all and 12 hours of trail."

    Design: Difficulty/compensating_invariant/withdraw_after_schedule_restores_counters_and_notifications
    """
    ctx, request, _tier1, _tier2 = setup_notified_scheduled_change()

    assert request["structural"] is False, (
        f"a reference-value addition is not structural, got {request['structural']!r}"
    )
    assert request["impact_consumer_count"] == 1, (
        "only the TIER1 consumer is impacted by a non-structural change, got "
        f"{request['impact_consumer_count']}"
    )
    assert request["required_lead_days"] == 10, (
        "the greater of the consumer's ten days and the domain's five-day floor "
        f"stands with no surcharge, got {request['required_lead_days']}"
    )
    assert_instant_equals(
        request["earliest_apply_at"], "2026-08-15T00:00:00Z", "earliest_apply_at"
    )
    assert_instant_equals(
        request["freeze_window_start"], "2026-08-16T00:00:00Z", "freeze_window_start"
    )
    assert_instant_equals(
        request["freeze_window_end"], "2026-08-16T12:00:00Z", "freeze_window_end"
    )

    domain = refresh_domain(ctx)
    assert domain["scheduled_change_count"] == 1, (
        f"one change now occupies the calendar, got {domain['scheduled_change_count']}"
    )
    assert domain["reference_data_revision"] == 0, (
        "no change has been applied yet, so the revision stays at 0, got "
        f"{domain['reference_data_revision']}"
    )


def test_only_the_tier1_consumer_is_notified_and_records_its_acknowledgement(api):
    """PRD §3.8: "On success the `status` becomes `SCHEDULED`,
    `scheduled_apply_at` and the two window boundaries are stored, the domain's
    `scheduled_change_count` is incremented by one and its `version` advances by
    one, and the notification fan-out runs: every consumer subscription in the
    impacted set — determined by exactly the same filter the impact assessment
    used — has its `pending_change_request_id` set to this request, its
    `notified_at` stamped from the clock, and its `acknowledged_at` and
    `acknowledged_revision` cleared to null so that a stale acknowledgement from
    an earlier notification cannot be mistaken for a fresh one."
    PRD §3.9: "On success `acknowledged_at` is stamped from the logical clock and
    `acknowledged_revision` captures the domain's `reference_data_revision` at
    acknowledgement time, giving an auditable record of exactly which revision of
    the reference data the consumer signed off against."
    PRD §3.8: "In other words, a structural change impacts every active consumer
    regardless of criticality, whereas a plain reference-value addition impacts
    only the `TIER1` consumers."

    Design: Difficulty/compensating_invariant/withdraw_after_schedule_restores_counters_and_notifications
    """
    _ctx, request, tier1, tier2 = setup_notified_scheduled_change()

    assert tier1["pending_change_request_id"] == request["id"], (
        "the TIER1 consumer must be notified about this very request, got "
        f"{tier1['pending_change_request_id']!r}"
    )
    assert_instant_equals(
        tier1["acknowledged_at"], "2026-08-05T00:00:00Z", "acknowledged_at"
    )
    assert tier1["acknowledged_revision"] == 0, (
        "the acknowledgement captures the domain's current revision of 0, got "
        f"{tier1['acknowledged_revision']}"
    )

    untouched = validate_success(
        api.get_consumer_subscription(tier2["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert untouched["pending_change_request_id"] is None, (
        "a TIER2 consumer is outside the impacted set of a non-structural "
        f"change, got {untouched['pending_change_request_id']!r}"
    )
    assert untouched["notified_at"] is None, (
        f"the TIER2 consumer was never notified, got {untouched['notified_at']!r}"
    )


def test_withdrawal_releases_the_freeze_window_and_the_calendar_occupancy(api):
    """PRD §3.8: "Withdrawing from `SCHEDULED` reverses the schedule:
    `freeze_window_start` and `freeze_window_end` are set to null, the domain's
    `scheduled_change_count` is decremented by one, and the domain's `version`
    advances by one."
    PRD §3.8: "It is reachable from every non-terminal state — `DRAFT`,
    `SUBMITTED`, `UNDER_REVIEW`, `CHANGES_REQUESTED`, `APPROVED` and `SCHEDULED`
    — and it always sets `status` to `WITHDRAWN` and stores the reason."
    PRD §2.8: "`Domain.scheduled_change_count` is the exact integer count of the
    domain's change requests whose `status` is `SCHEDULED`."

    Design: Difficulty/compensating_invariant/withdraw_after_schedule_restores_counters_and_notifications
    """
    ctx, request, _tier1, _tier2 = setup_notified_scheduled_change()

    withdrawn = validate_success(
        api.withdraw_change_request(
            request["id"], {"withdraw_reason": WITHDRAW_REASON}, ctx["steward_headers"]
        )
    )

    assert withdrawn["status"] == "WITHDRAWN", (
        f"the compensating action closes the request, got {withdrawn['status']}"
    )
    assert withdrawn["withdraw_reason"] == WITHDRAW_REASON, (
        f"the supplied reason must be stored, got {withdrawn['withdraw_reason']!r}"
    )
    assert_freeze_window_released(withdrawn)

    domain = refresh_domain(ctx)
    assert domain["scheduled_change_count"] == 0, (
        "the calendar occupancy is fully released, got "
        f"{domain['scheduled_change_count']}"
    )


def test_withdrawal_leaves_the_applied_change_history_exactly_where_it_was(api):
    """PRD §3.8: "Crucially the domain's `reference_data_revision` is left
    unchanged — a withdrawn change never counted as applied, so it never advanced
    the revision and withdrawal must not roll one back."
    PRD §2.8: "Alongside these, `Domain.scorecard_run_seq` is a monotonic epoch
    counter incremented by one per scorecard run on the domain, and
    `Domain.reference_data_revision` is incremented by one every time one of the
    domain's change requests reaches `APPLIED`; neither is ever decremented, not
    even by a withdrawal."
    PRD §2.8: "Withdrawing a scheduled change request must release its freeze
    window, decrement `scheduled_change_count`, and clear the notification
    fan-out it created — while leaving the domain's applied-change history alone,
    which is to say `reference_data_revision` does not move."

    Design: Difficulty/compensating_invariant/withdraw_after_schedule_restores_counters_and_notifications
    """
    ctx, request, _tier1, _tier2 = setup_notified_scheduled_change()

    revision_before = refresh_domain(ctx)["reference_data_revision"]
    assert revision_before == 0, (
        f"no change of this domain has been applied, got {revision_before}"
    )

    validate_success(
        api.withdraw_change_request(
            request["id"], {"withdraw_reason": WITHDRAW_REASON}, ctx["steward_headers"]
        )
    )

    domain = refresh_domain(ctx)
    assert domain["reference_data_revision"] == 0, (
        "a withdrawal must not roll the applied-change revision back or forward, "
        f"got {domain['reference_data_revision']}"
    )
    assert domain["scorecard_run_seq"] == 0, (
        "no scorecard has been run on this domain, and a withdrawal never moves "
        f"the run epoch either, got {domain['scorecard_run_seq']}"
    )


def test_withdrawal_clears_the_notification_quartet_on_the_notified_consumer(api):
    """PRD §3.8: "It also reverses the notification fan-out: every consumer
    subscription whose `pending_change_request_id` names this request has that
    field, plus `notified_at`, `acknowledged_at` and `acknowledged_revision`,
    cleared to null."
    PRD §3.9: "The subscription row, like the master record, runs two independent
    dimensions."
    PRD §3.9: "`status` moves `ACTIVE → SUSPENDED` when a classification uplift
    leaves the consumer under-cleared, and `lineage_status` moves independently
    among `UNDOCUMENTED`, `DOCUMENTED` and `STALE`."

    Design: Difficulty/compensating_invariant/withdraw_after_schedule_restores_counters_and_notifications
    """
    ctx, request, tier1, _tier2 = setup_notified_scheduled_change()

    validate_success(
        api.withdraw_change_request(
            request["id"], {"withdraw_reason": WITHDRAW_REASON}, ctx["steward_headers"]
        )
    )

    consumer = validate_success(
        api.get_consumer_subscription(tier1["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert consumer["pending_change_request_id"] is None, (
        "the pending notification is withdrawn, got "
        f"{consumer['pending_change_request_id']!r}"
    )
    assert consumer["notified_at"] is None, (
        f"the notification instant is cleared, got {consumer['notified_at']!r}"
    )
    assert consumer["acknowledged_at"] is None, (
        "the acknowledgement of a withdrawn notification is cleared, got "
        f"{consumer['acknowledged_at']!r}"
    )
    assert consumer["acknowledged_revision"] is None, (
        f"the acknowledged revision is cleared, got {consumer['acknowledged_revision']!r}"
    )
    assert consumer["status"] == "ACTIVE", (
        f"a withdrawal never suspends a consumer, got {consumer['status']}"
    )


def test_withdrawal_leaves_the_consumer_that_was_never_notified_alone(api):
    """PRD §3.8: "It also reverses the notification fan-out: every consumer
    subscription whose `pending_change_request_id` names this request has that
    field, plus `notified_at`, `acknowledged_at` and `acknowledged_revision`,
    cleared to null."
    PRD §3.8: "In other words, a structural change impacts every active consumer
    regardless of criticality, whereas a plain reference-value addition impacts
    only the `TIER1` consumers."
    PRD §3.9: "A new subscription begins with `status` `ACTIVE` and
    `lineage_status` `UNDOCUMENTED`, an empty `lineage_path`, and
    `lineage_revision`, `lineage_documented_at`, `pending_change_request_id`,
    `notified_at`, `acknowledged_at`, `acknowledged_revision` and
    `suspended_reason` all null."

    Design: Difficulty/compensating_invariant/withdraw_after_schedule_restores_counters_and_notifications
    """
    ctx, request, _tier1, tier2 = setup_notified_scheduled_change()

    validate_success(
        api.withdraw_change_request(
            request["id"], {"withdraw_reason": WITHDRAW_REASON}, ctx["steward_headers"]
        )
    )

    consumer = validate_success(
        api.get_consumer_subscription(tier2["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert consumer["pending_change_request_id"] is None, (
        "the TIER2 consumer held no pending notification before or after the "
        f"withdrawal, got {consumer['pending_change_request_id']!r}"
    )
    assert consumer["notified_at"] is None, (
        f"the TIER2 consumer was never notified, got {consumer['notified_at']!r}"
    )
    assert consumer["status"] == "ACTIVE", (
        f"the uninvolved consumer stays active, got {consumer['status']}"
    )


def test_planning_a_remediation_charges_the_assignee_and_records_the_planner(api):
    """PRD §3.5: "On success the `assigned_steward_id`, `due_at` and `plan_note`
    are stored, `planned_by_steward_id` is set to the acting `X-User-ID`, and the
    assignee's `open_finding_load` is incremented by one."
    PRD §2.8: "`Steward.open_finding_load` is the exact integer count of findings
    whose `assigned_steward_id` is that steward and whose `status` is
    `REMEDIATION_PLANNED` — note the filter is `REMEDIATION_PLANNED` only, so an
    `OPEN` finding never charges anyone's load."
    PRD §3.5: "And `due_at` must fall strictly after the current logical clock —
    a due date equal to the clock is not acceptable — otherwise
    `ERR_DUE_DATE_IN_PAST`."

    Design: Difficulty/compensating_invariant/plan_then_resolve_restores_finding_load_and_posture
    """
    ctx, run, finding = setup_domain_with_open_critical_finding()

    assert run["posture_multiplier_applied"] == 1.00, (
        "the run began against an OPEN posture, so the multiplier is 1.00, got "
        f"{run['posture_multiplier_applied']}"
    )
    assert finding["severity_weight"] == 20.00, (
        "a CRITICAL breach weighs 20 base points at a 1.00 multiplier, got "
        f"{finding['severity_weight']}"
    )
    assert finding["gap_pct"] == 40.00, (
        "the gap is the threshold of 90.00 less the measured 50.00, got "
        f"{finding['gap_pct']}"
    )
    assert (
        validate_success(
            api.get_steward(ctx["steward"]["id"], GOVERNANCE_ADMIN_HEADERS)
        )["open_finding_load"]
        == 0
    ), "an OPEN finding charges nobody's workload"

    planned = validate_success(
        api.plan_finding_remediation(
            finding["id"],
            {
                "assigned_steward_id": ctx["steward"]["id"],
                "due_at": "2026-08-20T00:00:00Z",
                "plan_note": PLAN_NOTE,
            },
            ctx["steward_headers"],
        )
    )

    assert planned["status"] == "REMEDIATION_PLANNED", (
        f"the remediation branch relabels the debt, got {planned['status']}"
    )
    assert planned["planned_by_steward_id"] == ctx["steward"]["id"], (
        "the acting steward is recorded as the planner, got "
        f"{planned['planned_by_steward_id']!r}"
    )
    assert planned["assigned_steward_id"] == ctx["steward"]["id"], (
        f"the nominated assignee is stored, got {planned['assigned_steward_id']!r}"
    )

    assignee = validate_success(
        api.get_steward(ctx["steward"]["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert assignee["open_finding_load"] == 1, (
        f"planning charges the assignee exactly once, got {assignee['open_finding_load']}"
    )


def test_planning_a_remediation_releases_none_of_the_domain_quality_debt(api):
    """PRD §3.5: "The domain's `open_finding_weight` does not change: the
    finding's `severity_weight` was pinned at creation and the finding remains in
    the open set, so planning merely re-labels the debt rather than reducing it."
    PRD §2.8: "`Domain.open_finding_weight` is the two-decimal, half-up-rounded
    sum of `severity_weight` over the domain's findings whose `status` is `OPEN`
    or `REMEDIATION_PLANNED`."
    PRD §2.6: "The posture is then determined in this priority order: it is
    `FROZEN` if the domain holds no such active authoritative registration, or if
    `open_finding_weight` is at least 40.00; otherwise it is `RESTRICTED` if
    `open_finding_weight` is at least 15.00, or if at least one finding in the
    open set is governed by a rule whose `severity` is `CRITICAL`; otherwise it
    is `OPEN`."

    Design: Difficulty/compensating_invariant/plan_then_resolve_restores_finding_load_and_posture
    """
    ctx, _run, finding = setup_domain_with_open_critical_finding()

    assert ctx["domain"]["governance_posture"] == "RESTRICTED", (
        "one open critical finding restricts the domain, got "
        f"{ctx['domain']['governance_posture']}"
    )
    assert ctx["domain"]["open_finding_weight"] == 20.00, (
        f"the domain carries 20.00 of debt, got {ctx['domain']['open_finding_weight']}"
    )

    planned = validate_success(
        api.plan_finding_remediation(
            finding["id"],
            {
                "assigned_steward_id": ctx["steward"]["id"],
                "due_at": "2026-08-20T00:00:00Z",
                "plan_note": PLAN_NOTE,
            },
            ctx["steward_headers"],
        )
    )
    assert planned["severity_weight"] == 20.00, (
        "the severity weight pinned at creation survives the planning step, got "
        f"{planned['severity_weight']}"
    )

    domain = refresh_domain(ctx)
    assert domain["open_finding_weight"] == 20.00, (
        "a planned finding is still in the open set, so the debt stands at "
        f"20.00, got {domain['open_finding_weight']}"
    )
    assert domain["governance_posture"] == "RESTRICTED", (
        "planning is not a release, so the posture stays RESTRICTED, got "
        f"{domain['governance_posture']}"
    )


def test_resolving_a_planned_finding_releases_the_charged_load_exactly_once(api):
    """PRD §3.5: "From `REMEDIATION_PLANNED → RESOLVED`, the finding's `status`
    becomes `RESOLVED`, `resolved_at` is stamped from the clock, `measured_pct`
    is overwritten with the supplied `verified_measured_pct`, `gap_pct` is set to
    0.00, the `resolution_note` is stored, the previously charged assignee's
    `open_finding_load` is decremented by one, the domain's `open_finding_weight`
    is recomputed so that this finding's `severity_weight` leaves the sum, and
    the `governance_posture` is recomputed."
    PRD §2.8: "`Steward.open_finding_load` is the exact integer count of findings
    whose `assigned_steward_id` is that steward and whose `status` is
    `REMEDIATION_PLANNED` — note the filter is `REMEDIATION_PLANNED` only, so an
    `OPEN` finding never charges anyone's load."

    Design: Difficulty/compensating_invariant/plan_then_resolve_restores_finding_load_and_posture
    """
    ctx, _run, finding = setup_domain_with_open_critical_finding()

    validate_success(
        api.plan_finding_remediation(
            finding["id"],
            {
                "assigned_steward_id": ctx["steward"]["id"],
                "due_at": "2026-08-20T00:00:00Z",
                "plan_note": PLAN_NOTE,
            },
            ctx["steward_headers"],
        )
    )
    validate_success(
        api.resolve_quality_finding(
            finding["id"],
            {"verified_measured_pct": 95.00, "resolution_note": RESOLUTION_NOTE},
            ctx["steward_headers"],
        )
    )

    assignee = validate_success(
        api.get_steward(ctx["steward"]["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert assignee["open_finding_load"] == 0, (
        "the workload charge is compensated exactly once, got "
        f"{assignee['open_finding_load']}"
    )


def test_resolving_a_planned_finding_clears_the_debt_and_reopens_the_domain(api):
    """PRD §3.5: "From `REMEDIATION_PLANNED → RESOLVED`, the finding's `status`
    becomes `RESOLVED`, `resolved_at` is stamped from the clock, `measured_pct`
    is overwritten with the supplied `verified_measured_pct`, `gap_pct` is set to
    0.00, the `resolution_note` is stored, the previously charged assignee's
    `open_finding_load` is decremented by one, the domain's `open_finding_weight`
    is recomputed so that this finding's `severity_weight` leaves the sum, and
    the `governance_posture` is recomputed."
    PRD §2.6: "Findings in `RESOLVED` or `WAIVED` leave that sum."
    PRD §3.2: "`RESTRICTED → OPEN` fires on a finding-set recompute triggered by
    resolving or waiving a finding, and requires both that an `ACTIVE`
    `AUTHORITATIVE` registration exists and that the recomputed
    `open_finding_weight` is below 15.00 with no remaining `OPEN` or
    `REMEDIATION_PLANNED` finding whose rule severity is `CRITICAL`; it sets the
    posture to `OPEN` and advances `version`."

    Design: Difficulty/compensating_invariant/plan_then_resolve_restores_finding_load_and_posture
    """
    ctx, _run, finding = setup_domain_with_open_critical_finding()

    validate_success(
        api.plan_finding_remediation(
            finding["id"],
            {
                "assigned_steward_id": ctx["steward"]["id"],
                "due_at": "2026-08-20T00:00:00Z",
                "plan_note": PLAN_NOTE,
            },
            ctx["steward_headers"],
        )
    )
    validate_success(
        api.resolve_quality_finding(
            finding["id"],
            {"verified_measured_pct": 95.00, "resolution_note": RESOLUTION_NOTE},
            ctx["steward_headers"],
        )
    )

    domain = refresh_domain(ctx)
    assert domain["open_finding_weight"] == 0.00, (
        "the resolved finding's weight leaves the sum, got "
        f"{domain['open_finding_weight']}"
    )
    assert domain["governance_posture"] == "OPEN", (
        "no open critical finding remains, so the posture returns to OPEN, got "
        f"{domain['governance_posture']}"
    )


def test_resolved_finding_keeps_its_pinned_weight_with_the_verified_measurement(api):
    """PRD §2.7: "the multiplier derived from that captured posture is computed
    once per request and applied to every finding the request creates; each
    finding's `severity_weight` is then frozen on its row forever; and only after
    all of the request's findings exist are `open_finding_weight` and the posture
    recomputed, exactly once."
    PRD §3.5: "From `REMEDIATION_PLANNED → RESOLVED`, the finding's `status`
    becomes `RESOLVED`, `resolved_at` is stamped from the clock, `measured_pct`
    is overwritten with the supplied `verified_measured_pct`, `gap_pct` is set to
    0.00, the `resolution_note` is stored, the previously charged assignee's
    `open_finding_load` is decremented by one, the domain's `open_finding_weight`
    is recomputed so that this finding's `severity_weight` leaves the sum, and
    the `governance_posture` is recomputed."
    PRD §2.4: "Every deadline, accountability interval, freeze window, lead-time
    comparison and staleness computation described in this document is evaluated
    against this logical clock, and every timestamp field the server writes —
    `activated_at`, `certified_at`, `decertified_at`, `superseded_at`,
    `opened_at`, `resolved_at`, `published_at`, `measured_at`, `decided_at`,
    `submitted_at`, `applied_at`, `lineage_documented_at`, `notified_at` and
    `acknowledged_at` — is stamped from it."

    Design: Difficulty/compensating_invariant/plan_then_resolve_restores_finding_load_and_posture
    """
    ctx, _run, finding = setup_domain_with_open_critical_finding()

    validate_success(
        api.plan_finding_remediation(
            finding["id"],
            {
                "assigned_steward_id": ctx["steward"]["id"],
                "due_at": "2026-08-20T00:00:00Z",
                "plan_note": PLAN_NOTE,
            },
            ctx["steward_headers"],
        )
    )
    resolved = validate_success(
        api.resolve_quality_finding(
            finding["id"],
            {"verified_measured_pct": 95.00, "resolution_note": RESOLUTION_NOTE},
            ctx["steward_headers"],
        )
    )

    assert resolved["status"] == "RESOLVED", (
        f"the verified measurement closes the finding, got {resolved['status']}"
    )
    assert resolved["measured_pct"] == 95.00, (
        "the verified measurement overwrites the observed one, got "
        f"{resolved['measured_pct']}"
    )
    assert resolved["gap_pct"] == 0.00, (
        f"a resolved finding carries no gap, got {resolved['gap_pct']}"
    )
    assert resolved["severity_weight"] == 20.00, (
        "resolution never re-derives the weight under the then-current "
        f"multiplier, got {resolved['severity_weight']}"
    )
    assert_instant_equals(
        resolved["resolved_at"], "2026-08-05T00:00:00Z", "resolved_at"
    )
