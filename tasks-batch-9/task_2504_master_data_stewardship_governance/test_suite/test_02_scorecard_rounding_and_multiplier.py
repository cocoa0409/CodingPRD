"""Scorecard arithmetic where the order of the steps decides the answer.

Earned points are rounded rule by rule before they are added up, and the
posture multiplier that weights a run's findings is captured once at the start
of the run and applied unchanged to every finding that run creates.
"""

from test_helpers import (
    GOVERNANCE_ADMIN_HEADERS,
    read_domain,
    run_scorecard,
    setup_governed_domain,
    validate_paginated,
    validate_success,
)


def _awkward_threshold_rules():
    """Eighty weight points over thresholds that do not divide cleanly."""
    return [
        {
            "rule_code": "QR1",
            "dimension": "COMPLETENESS",
            "weight_points": 40,
            "threshold_pct": 90.00,
            "severity": "CRITICAL",
            "owner": "owner",
        },
        {
            "rule_code": "QR2",
            "dimension": "VALIDITY",
            "weight_points": 30,
            "threshold_pct": 80.00,
            "severity": "HIGH",
            "owner": "steward",
        },
        {
            "rule_code": "QR4",
            "dimension": "CONSISTENCY",
            "weight_points": 10,
            "threshold_pct": 99.00,
            "severity": "LOW",
            "owner": "steward",
        },
    ]


def _awkward_measurements():
    return [
        {"rule_code": "QR1", "measured_pct": 10.00},
        {"rule_code": "QR2", "measured_pct": 10.00},
        {"rule_code": "QR4", "measured_pct": 50.00},
    ]


def _four_equal_rules():
    """One hundred weight points split evenly across four severities."""
    return [
        {
            "rule_code": "QR1",
            "dimension": "COMPLETENESS",
            "weight_points": 25,
            "threshold_pct": 90.00,
            "severity": "CRITICAL",
            "owner": "owner",
        },
        {
            "rule_code": "QR2",
            "dimension": "VALIDITY",
            "weight_points": 25,
            "threshold_pct": 90.00,
            "severity": "CRITICAL",
            "owner": "owner",
        },
        {
            "rule_code": "QR3",
            "dimension": "TIMELINESS",
            "weight_points": 25,
            "threshold_pct": 90.00,
            "severity": "MEDIUM",
            "owner": "steward",
        },
        {
            "rule_code": "QR4",
            "dimension": "CONSISTENCY",
            "weight_points": 25,
            "threshold_pct": 90.00,
            "severity": "LOW",
            "owner": "steward",
        },
    ]


def _finding_for(api, rule):
    findings, meta = validate_paginated(
        api.list_quality_findings(
            GOVERNANCE_ADMIN_HEADERS, params={"quality_rule_id": rule["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"rule {rule['rule_code']} must carry exactly one finding, got "
        f"{meta['total_count']}"
    )
    return findings[0]


def test_earned_points_are_rounded_rule_by_rule_before_being_summed(api):
    """Rounding each rule's points first gives 16.55, not 16.56.

    First, the scorecard rounds **per rule and then sums**: each evaluated rule's earned points are rounded to two decimal places first, and the already-rounded terms are then added together.
    Summing unrounded points and rounding once at the end is wrong.
    Otherwise each evaluated rule earns points: a rule whose `measured_pct` is greater than or equal to its `threshold_pct` earns its full `weight_points` — exact equality is a pass and earns the full weight — while a rule that falls short earns its `weight_points` multiplied by the ratio of its `measured_pct` to its `threshold_pct`, and that per-rule figure is rounded half up to two decimal places *before* anything is added up.
    The already-rounded per-rule figures are then summed to give the earned total.
    The denominator is the plain sum of `weight_points` over the evaluated rules.
    The run's `weighted_score` is one hundred times the earned total divided by that denominator, rounded half up to two decimal places — a second and final rounding.
    A `PROVISIONAL` run writes its `weighted_score` to the domain's `quality_score_provisional`; a `CERTIFIED` run writes it to `quality_score_certified`.

    Design: Difficulty/combinatorial_formula/scorecard_rounds_per_rule_before_summation
    """
    ctx = setup_governed_domain(rules=_awkward_threshold_rules())

    run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {"basis": "PROVISIONAL", "measurements": _awkward_measurements()},
            ctx["steward_headers"],
        ),
        201,
    )

    assert run["weighted_score"] == 16.55, (
        "rounding 4.4444 to 4.44, 3.75 and 5.0505 to 5.05 before summing gives "
        "13.24 earned over an eighty point budget, which must score 16.55 and "
        f"not the 16.56 an unrounded sum would give, got {run['weighted_score']}"
    )
    assert run["rules_evaluated_count"] == 3, (
        "all three measured rules must enter the denominator, got "
        f"{run['rules_evaluated_count']}"
    )
    assert run["rules_failed_count"] == 3, (
        "every rule was measured below its threshold, got "
        f"{run['rules_failed_count']} failures"
    )
    assert run["findings_created_count"] == 3, (
        "no breach was previously known, so all three failures must open new "
        f"findings, got {run['findings_created_count']}"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["quality_score_provisional"] == 16.55, (
        "the domain's provisional quality score must carry the run's score of "
        f"16.55, got {domain['quality_score_provisional']}"
    )


def test_each_new_finding_pins_the_weight_its_rule_severity_earns(api):
    """A run from an open posture weights every finding at its plain base points.

    The base points come from the breached rule's `severity`: a `LOW`-severity rule contributes 1 point, `MEDIUM` contributes 3, `HIGH` contributes 8 and `CRITICAL` contributes 20.
    Those base points are then multiplied by a posture multiplier: 1.00 when the domain's posture was `OPEN`, 1.25 when it was `RESTRICTED` and 1.50 when it was `FROZEN`.
    The multiplier is derived from the posture as it stood at the instant the run started, which the run records as `posture_before`; it is computed once and recorded as `posture_multiplier_applied`, and the *same* multiplier is applied to every finding the run creates.
    Each finding's `severity_weight` is the base points times that multiplier, rounded half up to two decimal places, and it is frozen on the finding row forever after — nothing recomputes it.
    Only where no such open finding exists is a new one created, in `status` `OPEN`, carrying the observed `measured_pct`, the corresponding `gap_pct`, and a freshly pinned `severity_weight`.

    Design: Difficulty/combinatorial_formula/scorecard_rounds_per_rule_before_summation
    """
    ctx = setup_governed_domain(rules=_awkward_threshold_rules())

    run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {"basis": "PROVISIONAL", "measurements": _awkward_measurements()},
            ctx["steward_headers"],
        ),
        201,
    )

    assert run["posture_before"] == "OPEN", (
        "a governed domain with no quality debt starts the run at an open "
        f"posture, got {run['posture_before']}"
    )
    assert run["posture_multiplier_applied"] == 1.00, (
        "an open posture pins the run's multiplier at 1.00, got "
        f"{run['posture_multiplier_applied']}"
    )

    critical = _finding_for(api, ctx["rules"]["QR1"])
    assert critical["severity_weight"] == 20.00, (
        f"a critical breach at an open posture must weigh 20.00, got "
        f"{critical['severity_weight']}"
    )
    assert critical["gap_pct"] == 80.00, (
        "a 90.00 threshold measured at 10.00 must record a gap of 80.00, got "
        f"{critical['gap_pct']}"
    )

    high = _finding_for(api, ctx["rules"]["QR2"])
    assert high["severity_weight"] == 8.00, (
        f"a high-severity breach at an open posture must weigh 8.00, got "
        f"{high['severity_weight']}"
    )
    assert high["gap_pct"] == 70.00, (
        "an 80.00 threshold measured at 10.00 must record a gap of 70.00, got "
        f"{high['gap_pct']}"
    )

    low = _finding_for(api, ctx["rules"]["QR4"])
    assert low["severity_weight"] == 1.00, (
        f"a low-severity breach at an open posture must weigh 1.00, got "
        f"{low['severity_weight']}"
    )
    assert low["gap_pct"] == 49.00, (
        "a 99.00 threshold measured at 50.00 must record a gap of 49.00, got "
        f"{low['gap_pct']}"
    )


def test_the_runs_findings_restrict_the_domain_after_a_single_recompute(api):
    """Twenty-nine points of fresh quality debt restricts the domain.

    Only after every finding of the run exists does the system recompute `open_finding_weight` and the `governance_posture`, exactly once, and the resulting posture is recorded on the run as `posture_after`.
    The first is `open_finding_weight`: the sum, rounded half-up to two decimal places, of `severity_weight` over every `QualityFinding` whose governing rule belongs to this domain and whose `status` is either `OPEN` or `REMEDIATION_PLANNED`.
    The posture is then determined in this priority order: it is `FROZEN` if the domain holds no such active authoritative registration, or if `open_finding_weight` is at least 40.00; otherwise it is `RESTRICTED` if `open_finding_weight` is at least 15.00, or if at least one finding in the open set is governed by a rule whose `severity` is `CRITICAL`; otherwise it is `OPEN`.

    Design: Difficulty/combinatorial_formula/scorecard_rounds_per_rule_before_summation
    """
    ctx = setup_governed_domain(rules=_awkward_threshold_rules())

    run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {"basis": "PROVISIONAL", "measurements": _awkward_measurements()},
            ctx["steward_headers"],
        ),
        201,
    )

    assert run["posture_after"] == "RESTRICTED", (
        "twenty-nine points of open finding weight, including a critical "
        f"breach, must leave the run restricted, got {run['posture_after']}"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["open_finding_weight"] == 29.00, (
        "20.00 plus 8.00 plus 1.00 of pinned severity weight must total 29.00, "
        f"got {domain['open_finding_weight']}"
    )
    assert domain["governance_posture"] == "RESTRICTED", (
        "an open finding weight between 15.00 and 40.00 must restrict the "
        f"domain, got {domain['governance_posture']}"
    )


def test_one_multiplier_serves_every_finding_a_single_run_creates(api):
    """A restricted run weights all three of its findings at 1.25, not more.

    The multiplier is derived from the posture as it stood at the instant the run started, which the run records as `posture_before`; it is computed once and recorded as `posture_multiplier_applied`, and the *same* multiplier is applied to every finding the run creates.
    Each finding's `severity_weight` is the base points times that multiplier, rounded half up to two decimal places, and it is frozen on the finding row forever after — nothing recomputes it.
    A run that begins `FROZEN` and creates three findings therefore weights all three at 1.50, not the first at 1.50 and the later ones at some higher multiplier.
    The base points come from the breached rule's `severity`: a `LOW`-severity rule contributes 1 point, `MEDIUM` contributes 3, `HIGH` contributes 8 and `CRITICAL` contributes 20.
    Those base points are then multiplied by a posture multiplier: 1.00 when the domain's posture was `OPEN`, 1.25 when it was `RESTRICTED` and 1.50 when it was `FROZEN`.
    Only after every finding of the run exists does the system recompute `open_finding_weight` and the `governance_posture`, exactly once, and the resulting posture is recorded on the run as `posture_after`.

    Design: Difficulty/combinatorial_formula/posture_multiplier_pinned_once_per_scorecard_run
    """
    ctx = setup_governed_domain(rules=_four_equal_rules())
    run_scorecard(
        ctx,
        basis="PROVISIONAL",
        measurements=[{"rule_code": "QR1", "measured_pct": 50.00}],
    )

    second_run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {
                "basis": "PROVISIONAL",
                "measurements": [
                    {"rule_code": "QR2", "measured_pct": 50.00},
                    {"rule_code": "QR3", "measured_pct": 50.00},
                    {"rule_code": "QR4", "measured_pct": 50.00},
                ],
            },
            ctx["steward_headers"],
        ),
        201,
    )

    assert second_run["posture_before"] == "RESTRICTED", (
        "the first run's critical finding left the domain restricted, so the "
        f"second run must start from RESTRICTED, got {second_run['posture_before']}"
    )
    assert second_run["posture_multiplier_applied"] == 1.25, (
        "a restricted starting posture pins the run's multiplier at 1.25, got "
        f"{second_run['posture_multiplier_applied']}"
    )
    assert second_run["findings_created_count"] == 3, (
        "three previously unmeasured rules each open a new finding, got "
        f"{second_run['findings_created_count']}"
    )
    assert second_run["weighted_score"] == 55.56, (
        "three rules each earning 13.89 of 25 points must score 55.56, got "
        f"{second_run['weighted_score']}"
    )

    assert _finding_for(api, ctx["rules"]["QR2"])["severity_weight"] == 25.00, (
        "twenty base points at the run's pinned 1.25 multiplier must weigh 25.00"
    )
    medium_weight = _finding_for(api, ctx["rules"]["QR3"])["severity_weight"]
    assert medium_weight == 3.75, (
        "three base points at the run's pinned 1.25 multiplier must weigh 3.75, "
        f"not the 4.50 a re-derived multiplier would give, got {medium_weight}"
    )
    low_weight = _finding_for(api, ctx["rules"]["QR4"])["severity_weight"]
    assert low_weight == 1.25, (
        "one base point at the run's pinned 1.25 multiplier must weigh 1.25, "
        f"not the 1.50 a re-derived multiplier would give, got {low_weight}"
    )


def test_quality_debt_from_the_restricted_run_freezes_the_domain(api):
    """The single post-run recompute lands the domain at exactly 50.00 and frozen.

    Only after every finding of the run exists does the system recompute `open_finding_weight` and the `governance_posture`, exactly once, and the resulting posture is recorded on the run as `posture_after`.
    The first is `open_finding_weight`: the sum, rounded half-up to two decimal places, of `severity_weight` over every `QualityFinding` whose governing rule belongs to this domain and whose `status` is either `OPEN` or `REMEDIATION_PLANNED`.
    The posture is then determined in this priority order: it is `FROZEN` if the domain holds no such active authoritative registration, or if `open_finding_weight` is at least 40.00; otherwise it is `RESTRICTED` if `open_finding_weight` is at least 15.00, or if at least one finding in the open set is governed by a rule whose `severity` is `CRITICAL`; otherwise it is `OPEN`.
    Both thresholds are inclusive lower bounds — a weight of exactly 40.00 is `FROZEN`, and a weight of exactly 15.00 with no open critical finding is `RESTRICTED`.

    Design: Difficulty/combinatorial_formula/posture_multiplier_pinned_once_per_scorecard_run
    """
    ctx = setup_governed_domain(rules=_four_equal_rules())
    run_scorecard(
        ctx,
        basis="PROVISIONAL",
        measurements=[{"rule_code": "QR1", "measured_pct": 50.00}],
    )

    second_run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {
                "basis": "PROVISIONAL",
                "measurements": [
                    {"rule_code": "QR2", "measured_pct": 50.00},
                    {"rule_code": "QR3", "measured_pct": 50.00},
                    {"rule_code": "QR4", "measured_pct": 50.00},
                ],
            },
            ctx["steward_headers"],
        ),
        201,
    )

    assert second_run["posture_after"] == "FROZEN", (
        "fifty points of open finding weight must leave the run frozen, got "
        f"{second_run['posture_after']}"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["open_finding_weight"] == 50.00, (
        "20.00 from the first run plus 25.00, 3.75 and 1.25 from the second "
        "must total exactly 50.00, not the 51.00 an escalating multiplier would "
        f"give, got {domain['open_finding_weight']}"
    )
    assert domain["governance_posture"] == "FROZEN", (
        "an open finding weight of at least 40.00 must freeze the domain, got "
        f"{domain['governance_posture']}"
    )


def test_an_earlier_findings_weight_is_never_recomputed_by_a_later_run(api):
    """The critical finding keeps the 20.00 its own run pinned on it.

    Each finding's `severity_weight` is the base points times that multiplier, rounded half up to two decimal places, and it is frozen on the finding row forever after — nothing recomputes it.
    If the rule already carries a finding in `OPEN` or `REMEDIATION_PLANNED` status, no new finding is created; instead that existing finding's `measured_pct` is refreshed to the newly observed value and its `gap_pct` is recomputed as the rule's `threshold_pct` minus the new `measured_pct`, rounded half up to two decimal places, and its `severity_weight` is left strictly untouched.
    Those base points are then multiplied by a posture multiplier: 1.00 when the domain's posture was `OPEN`, 1.25 when it was `RESTRICTED` and 1.50 when it was `FROZEN`.

    Design: Difficulty/combinatorial_formula/posture_multiplier_pinned_once_per_scorecard_run
    """
    ctx = setup_governed_domain(rules=_four_equal_rules())

    first_run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {
                "basis": "PROVISIONAL",
                "measurements": [{"rule_code": "QR1", "measured_pct": 50.00}],
            },
            ctx["steward_headers"],
        ),
        201,
    )
    assert first_run["posture_multiplier_applied"] == 1.00, (
        "the first run starts from an open posture and must pin 1.00, got "
        f"{first_run['posture_multiplier_applied']}"
    )
    assert first_run["weighted_score"] == 55.56, (
        "13.89 earned points of a twenty-five point denominator must score "
        f"55.56, got {first_run['weighted_score']}"
    )
    assert first_run["posture_after"] == "RESTRICTED", (
        "one open critical finding must restrict the domain, got "
        f"{first_run['posture_after']}"
    )

    run_scorecard(
        ctx,
        basis="PROVISIONAL",
        measurements=[
            {"rule_code": "QR2", "measured_pct": 50.00},
            {"rule_code": "QR3", "measured_pct": 50.00},
            {"rule_code": "QR4", "measured_pct": 50.00},
        ],
    )

    critical = _finding_for(api, ctx["rules"]["QR1"])
    assert critical["severity_weight"] == 20.00, (
        "the first run's critical finding must still carry the 20.00 it was "
        f"pinned with, got {critical['severity_weight']}"
    )
