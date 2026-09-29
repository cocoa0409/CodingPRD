"""Exact boundaries in the scorecard threshold and the change calendar.

Two governance rules turn on an exact instant or an exact percentage rather
than on a comfortable range: a quality measurement that lands precisely on its
rule's pass threshold, and a freeze window that clears a neighbouring window by
precisely the mandatory separation buffer. Both are exercised from each side of
their boundary here, so the direction of the comparison and the rounding mode
are both visible in the result.
"""

from test_helpers import (
    GOVERNANCE_ADMIN_HEADERS,
    assert_freeze_window_released,
    assert_instant_equals,
    setup_approved_structural_requests,
    setup_governed_domain,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_measurement_exactly_at_threshold_passes_and_opens_no_finding(api):
    """PRD §3.4: "Otherwise each evaluated rule earns points: a rule whose
    `measured_pct` is greater than or equal to its `threshold_pct` earns its
    full `weight_points` — exact equality is a pass and earns the full weight —
    while a rule that falls short earns its `weight_points` multiplied by the
    ratio of its `measured_pct` to its `threshold_pct`, and that per-rule figure
    is rounded half up to two decimal places *before* anything is added up."
    PRD §3.4: "`rules_evaluated_count` records how many rules entered the
    denominator and `rules_failed_count` how many of them had a `measured_pct`
    strictly below their `threshold_pct`."
    PRD §3.4: "Findings are then opened, in ascending `rule_code` order, for
    each evaluated rule that fell short — but with a deduplication rule that
    matters enormously in practice."

    Design: Difficulty/boundary_precision_check/measured_pct_exactly_at_threshold_earns_full_weight
    """
    ctx = setup_governed_domain()

    response = api.create_scorecard_run(
        ctx["domain"]["id"],
        {"basis": "CERTIFIED", "measurements": [{"rule_code": "QR1", "measured_pct": 90.00}]},
        ctx["steward_headers"],
    )
    run = validate_success(response, 201)

    assert run["rules_evaluated_count"] == 1, (
        "the single ACTIVE rule must enter the denominator, got "
        f"{run['rules_evaluated_count']}"
    )
    assert run["rules_failed_count"] == 0, (
        "a measurement equal to the threshold is not strictly below it, so no "
        f"rule failed, got {run['rules_failed_count']}"
    )
    assert run["findings_created_count"] == 0, (
        "no rule fell short, so no finding may be opened, got "
        f"{run['findings_created_count']}"
    )
    assert run["weighted_score"] == 100.00, (
        "a measurement exactly at the threshold earns all 40 weight points, so "
        f"the weighted score must be 100.00, got {run['weighted_score']}"
    )


def test_measurement_at_threshold_leaves_the_domain_open_with_no_quality_debt(api):
    """PRD §3.4: "A `PROVISIONAL` run writes its `weighted_score` to the
    domain's `quality_score_provisional`; a `CERTIFIED` run writes it to
    `quality_score_certified`."
    PRD §2.8: "`Domain.open_finding_weight` is the two-decimal, half-up-rounded
    sum of `severity_weight` over the domain's findings whose `status` is `OPEN`
    or `REMEDIATION_PLANNED`."
    PRD §2.6: "The posture is then determined in this priority order: it is
    `FROZEN` if the domain holds no such active authoritative registration, or
    if `open_finding_weight` is at least 40.00; otherwise it is `RESTRICTED` if
    `open_finding_weight` is at least 15.00, or if at least one finding in the
    open set is governed by a rule whose `severity` is `CRITICAL`; otherwise it
    is `OPEN`."

    Design: Difficulty/boundary_precision_check/measured_pct_exactly_at_threshold_earns_full_weight
    """
    ctx = setup_governed_domain()

    validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {"basis": "CERTIFIED", "measurements": [{"rule_code": "QR1", "measured_pct": 90.00}]},
            ctx["steward_headers"],
        ),
        201,
    )

    domain = validate_success(
        api.get_domain(ctx["domain"]["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert domain["quality_score_certified"] == 100.00, (
        "a certified-basis run must publish its weighted score as the domain's "
        f"certified quality score, got {domain['quality_score_certified']}"
    )
    assert domain["open_finding_weight"] == 0.00, (
        "a passing measurement opens no finding, so the domain carries no "
        f"quality debt, got {domain['open_finding_weight']}"
    )
    assert domain["governance_posture"] == "OPEN", (
        "with a certified authoritative source and no open finding weight the "
        f"posture must be OPEN, got {domain['governance_posture']}"
    )


def test_measurement_one_point_below_threshold_rounds_per_rule_before_summing(api):
    """PRD §3.4: "Otherwise each evaluated rule earns points: a rule whose
    `measured_pct` is greater than or equal to its `threshold_pct` earns its
    full `weight_points` — exact equality is a pass and earns the full weight —
    while a rule that falls short earns its `weight_points` multiplied by the
    ratio of its `measured_pct` to its `threshold_pct`, and that per-rule figure
    is rounded half up to two decimal places *before* anything is added up."
    PRD §3.4: "The run's `weighted_score` is one hundred times the earned total
    divided by that denominator, rounded half up to two decimal places — a
    second and final rounding."
    PRD §3.4: "A `PROVISIONAL` run writes its `weighted_score` to the domain's
    `quality_score_provisional`; a `CERTIFIED` run writes it to
    `quality_score_certified`."

    Design: Difficulty/boundary_precision_check/measured_pct_exactly_at_threshold_earns_full_weight
    """
    ctx = setup_governed_domain()

    run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {"basis": "CERTIFIED", "measurements": [{"rule_code": "QR1", "measured_pct": 89.00}]},
            ctx["steward_headers"],
        ),
        201,
    )

    assert run["rules_failed_count"] == 1, (
        "a measurement one point below the threshold falls short, got "
        f"{run['rules_failed_count']} failed rules"
    )
    assert run["findings_created_count"] == 1, (
        "the first breach of a rule opens exactly one new finding, got "
        f"{run['findings_created_count']}"
    )
    assert run["weighted_score"] == 98.90, (
        "the per-rule figure must be rounded to 39.56 before the scorecard "
        f"total is taken, giving a weighted score of 98.90, got {run['weighted_score']}"
    )

    domain = validate_success(
        api.get_domain(ctx["domain"]["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert domain["quality_score_certified"] == 98.90, (
        "the domain's certified quality score must carry the run's weighted "
        f"score of 98.90, got {domain['quality_score_certified']}"
    )


def test_finding_below_threshold_carries_the_gap_and_the_pinned_severity_weight(api):
    """PRD §3.4: "Only where no such open finding exists is a new one created,
    in `status` `OPEN`, carrying the observed `measured_pct`, the corresponding
    `gap_pct`, and a freshly pinned `severity_weight`."
    PRD §3.4: "If the rule already carries a finding in `OPEN` or
    `REMEDIATION_PLANNED` status, no new finding is created; instead that
    existing finding's `measured_pct` is refreshed to the newly observed value
    and its `gap_pct` is recomputed as the rule's `threshold_pct` minus the new
    `measured_pct`, rounded half up to two decimal places, and its
    `severity_weight` is left strictly untouched."
    PRD §3.4: "The base points come from the breached rule's `severity`: a
    `LOW`-severity rule contributes 1 point, `MEDIUM` contributes 3, `HIGH`
    contributes 8 and `CRITICAL` contributes 20."
    PRD §3.4: "Those base points are then multiplied by a posture multiplier:
    1.00 when the domain's posture was `OPEN`, 1.25 when it was `RESTRICTED`
    and 1.50 when it was `FROZEN`."
    PRD §2.6: "The posture is then determined in this priority order: it is
    `FROZEN` if the domain holds no such active authoritative registration, or
    if `open_finding_weight` is at least 40.00; otherwise it is `RESTRICTED` if
    `open_finding_weight` is at least 15.00, or if at least one finding in the
    open set is governed by a rule whose `severity` is `CRITICAL`; otherwise it
    is `OPEN`."

    Design: Difficulty/boundary_precision_check/measured_pct_exactly_at_threshold_earns_full_weight
    """
    ctx = setup_governed_domain()

    run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {"basis": "CERTIFIED", "measurements": [{"rule_code": "QR1", "measured_pct": 89.00}]},
            ctx["steward_headers"],
        ),
        201,
    )

    findings, meta = validate_paginated(
        api.list_quality_findings(
            GOVERNANCE_ADMIN_HEADERS,
            params={"scorecard_run_id": run["id"], "quality_rule_id": ctx["rules"]["QR1"]["id"]},
        )
    )
    assert meta["total_count"] == 1, (
        f"the breached rule must carry exactly one finding, got {meta['total_count']}"
    )
    finding = findings[0]
    assert finding["status"] == "OPEN", (
        f"a freshly opened finding is OPEN, got {finding['status']}"
    )
    assert finding["measured_pct"] == 89.00, (
        f"the finding must carry the observed measurement 89.00, got {finding['measured_pct']}"
    )
    assert finding["gap_pct"] == 1.00, (
        "the gap is the rule's threshold of 90.00 less the observed 89.00, so "
        f"1.00, got {finding['gap_pct']}"
    )
    assert finding["severity_weight"] == 8.00, (
        "a HIGH-severity breach pinned while the domain was OPEN weighs 8 base "
        f"points times a 1.00 multiplier, so 8.00, got {finding['severity_weight']}"
    )

    domain = validate_success(
        api.get_domain(ctx["domain"]["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert domain["open_finding_weight"] == 8.00, (
        "the domain's quality debt is the single open finding's pinned weight "
        f"of 8.00, got {domain['open_finding_weight']}"
    )
    assert domain["governance_posture"] == "OPEN", (
        "8.00 of open finding weight is below the 15.00 restricted bar, so the "
        f"posture stays OPEN, got {domain['governance_posture']}"
    )


def test_structural_freeze_window_reserves_24_hours_lead_and_48_hours_trail(api):
    """PRD §3.8: "The freeze window is a closed interval around that instant
    whose extent depends on whether the change is structural: a structural
    change reserves 24 hours of lead before the instant and 48 hours of trail
    after it, while a non-structural change reserves no lead at all and 12 hours
    of trail."
    PRD §3.8: "Second, a base lead time is taken as the largest
    `required_lead_days` among the impacted consumers, or zero when the impacted
    set is empty."
    PRD §3.8: "Third, a floor lead time is taken as the domain's
    `notification_lead_days_floor` when at least one consumer is impacted, and
    zero when none is."

    Design: Difficulty/boundary_precision_check/freeze_window_separation_exactly_72_hours_accepted
    """
    ctx = setup_governed_domain()
    first, _second = setup_approved_structural_requests(ctx, count=2)

    assert first["required_lead_days"] == 0, (
        "with no active consumer subscription both the base lead and the floor "
        f"lead are zero, got {first['required_lead_days']}"
    )

    scheduled = validate_success(
        api.schedule_change_request(
            first["id"], {"scheduled_apply_at": "2026-08-20T00:00:00Z"}, ctx["owner_headers"]
        )
    )

    assert scheduled["status"] == "SCHEDULED", (
        f"an approved change scheduled inside its lead time becomes SCHEDULED, "
        f"got {scheduled['status']}"
    )
    assert_instant_equals(
        scheduled["freeze_window_start"], "2026-08-19T00:00:00Z", "freeze_window_start"
    )
    assert_instant_equals(
        scheduled["freeze_window_end"], "2026-08-22T00:00:00Z", "freeze_window_end"
    )


def test_freeze_window_one_second_short_of_the_separation_buffer_is_refused(api):
    """PRD §3.8: "Because the window endpoints are inclusive, a mandatory
    separation buffer of 72 hours is required between windows: for every *other*
    change request of the same domain currently in `SCHEDULED` status, the new
    window is acceptable only if its start falls at or after that other window's
    end plus 72 hours, or its end plus 72 hours falls at or before that other
    window's start."
    PRD §3.8: "Exactly 72 hours of separation is accepted; one second less is
    refused with `ERR_FREEZE_WINDOW_CONFLICT`."
    PRD §3.8: "A new request is created in `status` `DRAFT` with
    `requester_steward_id` taken from the acting `X-User-ID`,
    `reviewer_steward_id` null, `impact_consumer_count` and `required_lead_days`
    at 0, `revision_cycle_count` at 0, and `submitted_at`, `earliest_apply_at`,
    `scheduled_apply_at`, `freeze_window_start`, `freeze_window_end`,
    `applied_at`, `review_note` and `withdraw_reason` all null."

    Design: Difficulty/boundary_precision_check/freeze_window_separation_exactly_72_hours_accepted
    """
    ctx = setup_governed_domain()
    first, second = setup_approved_structural_requests(ctx, count=2)

    validate_success(
        api.schedule_change_request(
            first["id"], {"scheduled_apply_at": "2026-08-20T00:00:00Z"}, ctx["owner_headers"]
        )
    )

    response = api.schedule_change_request(
        second["id"], {"scheduled_apply_at": "2026-08-25T23:59:59Z"}, ctx["owner_headers"]
    )
    validate_error(response, "ERR_FREEZE_WINDOW_CONFLICT")

    stored = validate_success(
        api.get_change_request(second["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert stored["status"] == "APPROVED", (
        "a window refused for insufficient separation leaves the request "
        f"APPROVED and unscheduled, got {stored['status']}"
    )
    assert stored["scheduled_apply_at"] is None, (
        "the refused schedule must store no apply instant, got "
        f"{stored['scheduled_apply_at']!r}"
    )
    assert_freeze_window_released(stored)


def test_freeze_window_with_exactly_72_hours_of_separation_is_accepted(api):
    """PRD §3.8: "Because the window endpoints are inclusive, a mandatory
    separation buffer of 72 hours is required between windows: for every *other*
    change request of the same domain currently in `SCHEDULED` status, the new
    window is acceptable only if its start falls at or after that other window's
    end plus 72 hours, or its end plus 72 hours falls at or before that other
    window's start."
    PRD §3.8: "Exactly 72 hours of separation is accepted; one second less is
    refused with `ERR_FREEZE_WINDOW_CONFLICT`."
    PRD §2.8: "`Domain.scheduled_change_count` is the exact integer count of
    the domain's change requests whose `status` is `SCHEDULED`."

    Design: Difficulty/boundary_precision_check/freeze_window_separation_exactly_72_hours_accepted
    """
    ctx = setup_governed_domain()
    first, second = setup_approved_structural_requests(ctx, count=2)

    validate_success(
        api.schedule_change_request(
            first["id"], {"scheduled_apply_at": "2026-08-20T00:00:00Z"}, ctx["owner_headers"]
        )
    )

    adjacent = validate_success(
        api.schedule_change_request(
            second["id"], {"scheduled_apply_at": "2026-08-26T00:00:00Z"}, ctx["owner_headers"]
        )
    )

    assert adjacent["status"] == "SCHEDULED", (
        "a window opening exactly 72 hours after the incumbent window closes is "
        f"accepted, got status {adjacent['status']}"
    )
    assert_instant_equals(
        adjacent["freeze_window_start"], "2026-08-25T00:00:00Z", "freeze_window_start"
    )
    assert_instant_equals(
        adjacent["freeze_window_end"], "2026-08-28T00:00:00Z", "freeze_window_end"
    )

    domain = validate_success(
        api.get_domain(ctx["domain"]["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert domain["scheduled_change_count"] == 2, (
        "both windows now occupy the change calendar, so the scheduled change "
        f"count must be 2, got {domain['scheduled_change_count']}"
    )
