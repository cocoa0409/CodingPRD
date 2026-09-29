"""Derived numbers: the formulas, their constants, their rounding and their caps.

Every number the server computes rather than accepts is exercised here — the
qualification score of a tester, the coverage ratio of a plan, the severity
rating of a finding, the remediation due date, the training priority score and
the ranking of scope candidates. Each test pins a figure that a plausible
mis-implementation would get wrong by a hair: a cap applied as a sum, a
truncation instead of a half-up rounding, a tie broken on the wrong column.
"""

from test_helpers import (
    advance_clock,
    assert_asset_posture,
    assert_error_id,
    assert_exact_int,
    assert_instant_equals,
    assert_no_alert_raised,
    assert_risk_ledger,
    assert_score,
    assert_severity,
    build_scenario,
    created_data,
    emitted_rows,
    factories,
    report_finding,
    success_data,
    read_plan_version,
)
from test_helpers.api_errors import ERR_COVERAGE_BELOW_MINIMUM
from test_helpers.constants import T_FIELDWORK_DAY, T_PROGRAMME_OPEN

ALL_FOUR_CERTIFICATIONS = ["OSCP", "GPEN", "CREST", "CISSP"]
IDENTITY_PROVIDER = {
    "name": "Identity Provider", "asset_class": "APPLICATION", "criticality_tier": 1,
    "compliance_regimes": ["SOC2"], "exposure_score": 80,
    "last_tested_at": "2025-11-02T00:00:00Z",
}
REPORTING_WAREHOUSE = {
    "name": "Reporting Warehouse", "asset_class": "CLOUD", "criticality_tier": 2,
    "compliance_regimes": [], "exposure_score": 40,
    "last_tested_at": "2026-02-05T00:00:00Z",
}
BRANCH_NETWORK = {
    "name": "Branch Network", "asset_class": "NETWORK", "criticality_tier": 2,
    "compliance_regimes": [], "exposure_score": 35,
    "last_tested_at": "2026-03-05T00:00:00Z",
}
INTERNAL_WIKI = {
    "name": "Internal Wiki", "asset_class": "APPLICATION", "criticality_tier": 3,
    "compliance_regimes": [], "exposure_score": 90, "last_tested_at": None,
}
GOV_CLOUD_TENANT = {
    "name": "Gov Cloud Tenant", "asset_class": "CLOUD", "criticality_tier": 2,
    "compliance_regimes": ["FEDRAMP"], "exposure_score": 70, "last_tested_at": None,
}
OPEN_APPETITE = {"risk_appetite_score": 100}


def _propose(client, plan_id, asset_id, justification, hours):
    """Propose one candidate, re-reading the plan version immediately beforehand."""
    return created_data(
        client.create_scope_item(
            factories.scope_item_payload(
                plan_id,
                asset_id,
                read_plan_version(client, plan_id),
                justification=justification,
                requested_engagement_hours=hours,
            )
        )
    )


def _approve(client, scope_item_id, note="In scope"):
    """Approve a proposed candidate."""
    return success_data(
        client.decide_scope_item(scope_item_id, factories.decision_payload("APPROVE", note=note))
    )


class TestTesterQualificationScoring:
    """The certification points are summed, capped, and rescored on replacement."""

    def test_four_certifications_cap_at_one_hundred_and_a_replacement_rescores(
        self, client
    ):
        """120 raw points clamp to 100, and replacing the list scores the new list alone.

        PRD: "From the certification list the server derives `qualification_score`: award 45 points for `OSCP`, 35 for `GPEN`, 25 for `CREST` and 15 for `CISSP`, add up the points for the certifications the tester actually holds, and cap the total at 100."
        PRD: "A tester whose certification list is later replaced wholesale is rescored the same way from the new list; that is the only way the score changes."

        Design: Corner/calculations/tester_qualification_score_caps_at_one_hundred_and_rescores_on_replacement
        """
        advance_clock(client, T_PROGRAMME_OPEN)
        tester = created_data(
            client.create_tester(
                factories.tester_payload(certifications=ALL_FOUR_CERTIFICATIONS)
            )
        )
        assert_exact_int(tester["qualification_score"], 100, "qualification_score")

        replaced = success_data(client.replace_certifications(tester["id"], ["CREST"]))

        assert_exact_int(replaced["qualification_score"], 25, "qualification_score")
        reread = success_data(client.get_tester(tester["id"]))
        assert_exact_int(reread["qualification_score"], 25, "qualification_score")
        assert reread["certifications"] == ["CREST"], (
            f"certifications: expected the replacement list, got {reread['certifications']}"
        )


class TestPlanCoverageRatio:
    """Coverage counts the top two tiers only, and 60.00 percent is enough."""

    def test_the_third_approval_lands_on_exactly_sixty_percent_and_activates(self, client):
        """Two of five eligible assets is 40.00 and refused; three is 60.00 and accepted.

        PRD: "The denominator is the number of registered assets whose `criticality_tier` is 1 or 2, counted across the whole inventory regardless of which plan they belong to."
        PRD: "It then recomputes `coverage_score` from scratch and requires the recomputed value to be at least 60.00 percent, refusing anything lower with `ERR_COVERAGE_BELOW_MINIMUM` — a plan sitting at exactly 60.00 activates."

        Design: Corner/calculations/plan_coverage_score_activates_at_exactly_sixty_percent
        """
        advance_clock(client, T_PROGRAMME_OPEN)
        payments = created_data(client.create_asset(factories.asset_payload()))
        identity = created_data(client.create_asset(factories.asset_payload(**IDENTITY_PROVIDER)))
        portal = created_data(client.create_asset(factories.partner_portal_asset_payload()))
        created_data(client.create_asset(factories.asset_payload(**REPORTING_WAREHOUSE)))
        created_data(client.create_asset(factories.asset_payload(**BRANCH_NETWORK)))
        plan = created_data(client.create_test_plan(factories.test_plan_payload(**OPEN_APPETITE)))
        assert_exact_int(plan["admission_threshold"], 0, "admission_threshold")
        assert_score(plan["coverage_score"], 0.00, "coverage_score")
        first = _propose(client, plan["id"], payments["id"], "Payments coverage", 120)
        second = _propose(client, plan["id"], identity["id"], "Identity coverage", 100)
        third = _propose(client, plan["id"], portal["id"], "Partner portal coverage", 60)
        _approve(client, first["id"])
        _approve(client, second["id"])
        assert_score(
            success_data(client.get_test_plan(plan["id"]))["coverage_score"],
            40.00,
            "coverage_score with two of five covered",
        )

        refused = client.activate_test_plan(plan["id"])

        assert_error_id(refused, ERR_COVERAGE_BELOW_MINIMUM)
        assert refused.status_code == 422, (
            f"expected HTTP 422 below the coverage minimum, got {refused.status_code}"
        )
        _approve(client, third["id"])
        before = success_data(client.get_test_plan(plan["id"]))
        assert_score(before["coverage_score"], 60.00, "coverage_score")
        assert before["status"] == "DRAFT", (
            f"status: expected DRAFT after the refusal, got {before['status']}"
        )

        activated = success_data(client.activate_test_plan(plan["id"]))

        assert activated["status"] == "ACTIVE", (
            f"status: expected ACTIVE at exactly 60.00, got {activated['status']}"
        )
        assert_score(activated["coverage_score"], 60.00, "coverage_score")

    def test_a_tier_three_asset_enters_neither_side_of_the_fraction(self, client):
        """The tier-3 candidate is scored yet contributes nothing to coverage.

        PRD: "The numerator is the number of **distinct** assets of tier 1 or 2 that this plan has candidates for in either `APPROVED` or `CONSUMED` status."
        PRD: "Tier-3 and tier-4 assets influence neither side of the fraction."

        Design: Corner/calculations/plan_coverage_score_counts_only_tier_one_and_two_assets
        """
        advance_clock(client, T_PROGRAMME_OPEN)
        payments = created_data(client.create_asset(factories.asset_payload()))
        wiki = created_data(client.create_asset(factories.asset_payload(**INTERNAL_WIKI)))
        first_plan = created_data(
            client.create_test_plan(
                factories.test_plan_payload(planned_engagement_count=2, **OPEN_APPETITE)
            )
        )
        wiki_candidate = _propose(client, first_plan["id"], wiki["id"], "Wiki review", 40)
        assert_score(wiki_candidate["priority_score"], 75.50, "priority_score")
        _approve(client, wiki_candidate["id"], note="Cheap and useful")
        second_plan = created_data(
            client.create_test_plan(
                factories.test_plan_payload(planned_engagement_count=2, **OPEN_APPETITE)
            )
        )
        payments_candidate = _propose(
            client, second_plan["id"], payments["id"], "Payments coverage", 120
        )
        assert_score(payments_candidate["priority_score"], 89.80, "priority_score")
        _approve(client, payments_candidate["id"])

        assert_score(
            success_data(client.get_test_plan(first_plan["id"]))["coverage_score"],
            0.00,
            "coverage_score of the tier-3-only plan",
        )
        refused = client.activate_test_plan(first_plan["id"])
        assert_error_id(refused, ERR_COVERAGE_BELOW_MINIMUM)
        assert refused.status_code == 422, (
            f"expected HTTP 422 for the tier-3-only plan, got {refused.status_code}"
        )
        assert_score(
            success_data(client.get_test_plan(second_plan["id"]))["coverage_score"],
            100.00,
            "coverage_score of the tier-1 plan",
        )
        activated = success_data(client.activate_test_plan(second_plan["id"]))
        assert activated["status"] == "ACTIVE", (
            f"status: expected ACTIVE, got {activated['status']}"
        )
        assert_score(activated["coverage_score"], 100.00, "coverage_score")


WIKI_XSS = {
    "title": "Stored XSS in the wiki comment renderer",
    "reproduction_steps": (
        "1. Post a comment containing a script tag 2. Reload the page as another user"
    ),
    "business_impact_narrative": "Session theft against internal editors",
    "technical_base_score": 3.91,
    "exposure_class": "INTERNET",
    "root_cause_theme": "INPUT_VALIDATION",
}


class TestSeverityRating:
    """The rating multiplies, then adds, then clamps, then rounds half-up."""

    def test_a_base_of_three_point_nine_one_rounds_up_to_four_point_six_zero(self, client):
        """3.91 * 1.15 + 0.10 is 4.5965, and half-up rounding lifts it to 4.60.

        PRD: "The rating starts from `technical_base_score` and multiplies it by an exposure multiplier — 0.95 for an `INTERNAL` finding, exactly 1.00 for a `PARTNER` finding, and 1.15 for an `INTERNET` finding."
        PRD: "The resulting total is **clamped down to 10.00 first and only then rounded** half-up to two decimal places, and the result is `severity_score`."
        PRD: "`severity_points` is the band's conserved ledger weight: 40 points for `CRITICAL`, 20 for `HIGH`, 8 for `MEDIUM` and 2 for `LOW`."
        PRD: "`coverage_score` is 100 multiplied by the numerator, divided by the denominator, rounded half-up to two decimal places; and in the degenerate case where the inventory holds no tier-1 or tier-2 asset at all, `coverage_score` is defined as exactly 100.00 rather than being undefined."

        Design: Corner/calculations/finding_severity_rounds_half_up_at_the_third_decimal
        """
        scenario = build_scenario(
            client,
            stage="executing",
            asset=INTERNAL_WIKI,
            plan=OPEN_APPETITE,
            scope_item={"justification": "Wiki review", "requested_engagement_hours": 40},
        )
        plan = success_data(client.get_test_plan(scenario["plan_id"]))
        assert plan["status"] == "ACTIVE", f"status: expected ACTIVE, got {plan['status']}"
        assert_score(plan["coverage_score"], 100.00, "coverage_score of a tier-3-only estate")
        advance_clock(client, T_FIELDWORK_DAY)

        finding = report_finding(client, scenario, **WIKI_XSS)

        assert_severity(finding, score=4.60, band="MEDIUM", points=8, immediate=False)
        assert round(float(finding["severity_score"]), 2) == 4.60, (
            f"severity_score: expected 4.60 from a half-up rounding of 4.5965, "
            f"got {finding['severity_score']}"
        )
        assert_instant_equals(finding["discovered_at"], T_FIELDWORK_DAY, "discovered_at")
        rated = success_data(client.get_test_plan(scenario["plan_id"]))
        assert_risk_ledger(rated, total=8, open_points=8)
        assert_no_alert_raised(client, finding["id"])


IAM_ESCALATION_FINDING = {
    "title": "Assessment role can escalate to tenant administrator",
    "reproduction_steps": (
        "1. Assume the assessment role 2. Attach the administrator policy to it"
    ),
    "business_impact_narrative": "Full control of the government cloud tenant",
    "technical_base_score": 6.5,
    "exposure_class": "PARTNER",
    "root_cause_theme": "CLOUD_IAM",
}
T_ASSIGNMENT_INSTANT = "2026-09-08T12:00:00Z"
DUE_AT = "2026-09-29T12:00:00Z"
EXTENDED_DUE_AT = "2026-10-09T12:00:00Z"
T_ONE_SECOND_PAST_DUE = "2026-10-09T12:00:01Z"
REMEDIATION_PLAN = "Scope the assessment role down to read-only and add a policy boundary"
EXTENSION_REASON = "Change freeze during the quarter close"


class TestRemediationDueDate:
    """Regulation only tightens the severity default, and an extension only shifts it."""

    def test_a_fedramp_asset_tightens_a_high_finding_to_twenty_one_days(self, client):
        """The cap wins over the default, the extension is additive, and due_at is strict.

        PRD: "The severity default gives a `CRITICAL` finding one week — 7 days — a `HIGH` finding 30 days, a `MEDIUM` finding 60 days and a `LOW` finding 120 days."
        PRD: "`due_at` is the creation instant advanced by `sla_days` whole days, so it shares the time-of-day component of the moment the remediation was assigned."
        PRD: "`overdue_flag` is true when the current instant is strictly later than `due_at` **and** the remediation's status is neither `VALIDATED` nor `CLOSED`."

        Design: Corner/calculations/remediation_sla_takes_the_tighter_regime_cap_and_extension_shifts_the_due_date
        """
        scenario = build_scenario(
            client,
            stage="executing",
            asset=GOV_CLOUD_TENANT,
            plan=OPEN_APPETITE,
            scope_item={
                "justification": "FedRAMP boundary assessment",
                "requested_engagement_hours": 100,
            },
            engagement={"engagement_type": "CLOUD_REVIEW"},
            roe={
                "allowed_techniques": ["IAM_ESCALATION"],
                "emergency_stop_procedure": (
                    "Revoke the assessment role and page the cloud on-call"
                ),
            },
            target={"technique_allowlist": ["IAM_ESCALATION"]},
        )
        advance_clock(client, T_FIELDWORK_DAY)
        finding = report_finding(client, scenario, **IAM_ESCALATION_FINDING)
        assert_severity(finding, score=7.00, band="HIGH", immediate=False)
        triaged = success_data(
            client.triage_finding(
                finding["id"],
                factories.triage_payload("ACCEPT", note="Confirmed by the cloud team"),
            )
        )
        assert triaged["status"] == "TRIAGED", (
            f"status: expected TRIAGED, got {triaged['status']}"
        )
        advance_clock(client, T_ASSIGNMENT_INSTANT)

        remediation = created_data(
            client.create_remediation(
                factories.remediation_payload(
                    finding["id"], remediation_plan=REMEDIATION_PLAN
                )
            )
        )

        assert_exact_int(remediation["sla_days"], 21, "sla_days")
        assert_instant_equals(remediation["due_at"], DUE_AT, "due_at")
        assert_exact_int(remediation["extension_count"], 0, "extension_count")
        assert remediation["overdue_flag"] is False, (
            f"overdue_flag: expected false at assignment, got {remediation['overdue_flag']}"
        )
        assert remediation["status"] == "ASSIGNED", (
            f"status: expected ASSIGNED, got {remediation['status']}"
        )

        extended = success_data(
            client.extend_remediation(remediation["id"], 10, EXTENSION_REASON)
        )

        assert_instant_equals(extended["due_at"], EXTENDED_DUE_AT, "due_at")
        assert_exact_int(extended["extension_count"], 1, "extension_count")
        assert_exact_int(extended["sla_days"], 21, "sla_days")
        advance_clock(client, EXTENDED_DUE_AT)
        at_due = success_data(client.get_remediation(remediation["id"]))
        assert at_due["overdue_flag"] is False, (
            "a remediation sitting exactly at due_at is not yet overdue"
        )
        advance_clock(client, T_ONE_SECOND_PAST_DUE)
        past_due = success_data(client.get_remediation(remediation["id"]))
        assert past_due["overdue_flag"] is True, (
            "one second past due_at the flag must be true"
        )


T_SECOND_FINDING_DAY = "2026-09-09T10:00:00Z"
T_ANALYSIS_INSTANT = "2026-09-10T00:00:00Z"
REFUND_INJECTION = {
    "title": "Unauthenticated SQL injection in the refund endpoint",
    "reproduction_steps": "1. POST /refunds with id=1 OR 1=1 2. observe the refund ledger",
    "business_impact_narrative": "An attacker can enumerate and alter refund records",
    "technical_base_score": 8.0,
    "exposure_class": "INTERNET",
    "root_cause_theme": "INPUT_VALIDATION",
}
EXPORT_INJECTION = {
    "title": "Second injection in the statement export",
    "reproduction_steps": (
        "1. GET /statements?filter=1 OR 1=1 2. observe other tenants rows"
    ),
    "business_impact_narrative": "Cross-tenant data exposure through the export filter",
    "technical_base_score": 8.0,
    "exposure_class": "INTERNET",
    "root_cause_theme": "INPUT_VALIDATION",
}


class TestTrainingPriorityBanding:
    """The band is a conjunction: a high score alone does not make training mandatory."""

    def test_two_critical_findings_score_nine_point_nine_seven_but_stay_recommended(
        self, client
    ):
        """4.97 plus 5.00 clears the score gate, while two recurrences miss the count gate.

        PRD: "Its recency multiplier is computed by taking the whole number of days from the finding's `discovered_at` to the generation instant discarding any partial day, dividing that day count by 90, multiplying the result by 0.60, subtracting that product from 1, and then raising the outcome to 0.40 if it fell below — so a finding discovered on the day of generation contributes at full weight, one discovered 90 days earlier contributes at 0.40, and nothing ever decays below 0.40."
        PRD: "Each finding's contribution is its severity weight multiplied by its recency multiplier, **rounded half-up to two decimal places before anything is summed**."
        PRD: "`urgency_band` is `MANDATORY` when `recurrence_count` is at least 3 **and** `priority_score` is at least 8.00, and `RECOMMENDED` in every other case — both conditions must hold, so a single devastating finding is never mandatory training on its own."

        Design: Corner/calculations/training_score_above_eight_stays_recommended_below_three_recurrences
        """
        scenario = build_scenario(client, stage="executing", plan=OPEN_APPETITE)
        advance_clock(client, T_FIELDWORK_DAY)
        first = report_finding(client, scenario, **REFUND_INJECTION)
        assert_severity(first, band="CRITICAL")
        advance_clock(client, T_SECOND_FINDING_DAY)
        second = report_finding(client, scenario, **EXPORT_INJECTION)
        assert_severity(second, band="CRITICAL")
        advance_clock(client, T_ANALYSIS_INSTANT)

        rows = emitted_rows(
            client.generate_training_recommendations(
                scenario["plan_id"], T_PROGRAMME_OPEN, T_ANALYSIS_INSTANT
            )
        )

        assert len(rows) == 1, f"expected exactly one theme row, got {len(rows)}"
        recommendation = rows[0]
        assert recommendation["root_cause_theme"] == "INPUT_VALIDATION", (
            f"root_cause_theme: expected INPUT_VALIDATION, "
            f"got {recommendation['root_cause_theme']}"
        )
        assert_score(recommendation["priority_score"], 9.97, "priority_score")
        assert_exact_int(recommendation["recurrence_count"], 2, "recurrence_count")
        assert_exact_int(
            recommendation["source_engagement_count"], 1, "source_engagement_count"
        )
        assert_instant_equals(
            recommendation["generated_at"], T_ANALYSIS_INSTANT, "generated_at"
        )
        assert recommendation["urgency_band"] == "RECOMMENDED", (
            f"urgency_band: expected RECOMMENDED while recurrence_count is 2, "
            f"got {recommendation['urgency_band']}"
        )


DUPLICATE_INJECTION = {
    "title": "Reflected injection in the same refund parameter",
    "reproduction_steps": (
        "1. POST /refunds with id=1 OR 1=1 2. compare with the first report"
    ),
    "business_impact_narrative": "Same root defect observed from a second entry point",
    "technical_base_score": 3.91,
    "exposure_class": "INTERNET",
    "root_cause_theme": "INPUT_VALIDATION",
}


class TestRiskPointLedgerMovement:
    """Points enter the ledger once and only ever move between buckets."""

    def test_marking_a_duplicate_moves_eight_points_without_changing_the_total(
        self, client
    ):
        """The open bucket loses what the duplicate bucket gains, and the total holds.

        PRD: "The **risk-point invariant** on a test plan is that `total_risk_points` always equals `open_risk_points` plus `closed_risk_points` plus `accepted_risk_points` plus `duplicate_risk_points`."
        PRD: "The plan's ledger subtracts the finding's points from `open_risk_points` and adds the same points to `duplicate_risk_points`, leaving `total_risk_points` untouched."
        PRD: "The asset's `open_finding_count` is decremented, and for a `CRITICAL` finding its `open_critical_finding_count` is decremented too, which may move the asset `ELEVATED` → `CLEARED` with `last_cleared_at` stamped."

        Design: Corner/calculations/marking_a_duplicate_moves_points_from_open_to_duplicate_without_changing_the_total
        """
        scenario = build_scenario(client, stage="executing", plan=OPEN_APPETITE)
        advance_clock(client, T_FIELDWORK_DAY)
        critical = report_finding(client, scenario, **REFUND_INJECTION)
        assert_severity(critical, points=40, band="CRITICAL")
        duplicate = report_finding(client, scenario, **DUPLICATE_INJECTION)
        assert_severity(duplicate, score=5.20, band="MEDIUM", points=8)
        before_plan = success_data(client.get_test_plan(scenario["plan_id"]))
        assert_risk_ledger(before_plan, total=48, open_points=48, duplicate=0)
        before_asset = success_data(client.get_asset(scenario["asset_id"]))
        assert_asset_posture(
            before_asset, exposure_state="ELEVATED", open_findings=2, open_critical=1
        )

        triaged = success_data(
            client.triage_finding(
                duplicate["id"],
                factories.triage_payload(
                    "MARK_DUPLICATE",
                    note="Same root defect as the first report",
                    duplicate_of_finding_id=critical["id"],
                ),
            )
        )

        assert triaged["status"] == "DUPLICATE", (
            f"status: expected DUPLICATE, got {triaged['status']}"
        )
        assert triaged["duplicate_of_finding_id"] == critical["id"], (
            f"duplicate_of_finding_id: expected the first finding, "
            f"got {triaged['duplicate_of_finding_id']}"
        )
        after_plan = success_data(client.get_test_plan(scenario["plan_id"]))
        assert_risk_ledger(
            after_plan, total=48, open_points=40, closed=0, accepted=0, duplicate=8
        )
        after_asset = success_data(client.get_asset(scenario["asset_id"]))
        assert_asset_posture(
            after_asset, exposure_state="ELEVATED", open_findings=1, open_critical=1
        )


PORTAL_TEMPLATE = {
    "asset_class": "APPLICATION", "criticality_tier": 2, "compliance_regimes": ["SOC2"],
    "exposure_score": 60, "last_tested_at": "2026-01-05T00:00:00Z",
}


class TestScopeRankTieBreaks:
    """Equal scores are separated by hours first and creation order second."""

    def test_the_cheaper_candidate_wins_the_tie_and_the_earlier_row_wins_the_rest(
        self, client
    ):
        """Three identical scores rank purely by requested hours then created_at.

        PRD: "They are sorted by `priority_score` descending; where two candidates tie on score, the one with the smaller `requested_engagement_hours` ranks ahead, on the principle that the cheaper candidate wins a tie; where they still tie, the earlier `created_at` ranks ahead."
        PRD: "The candidate's own identifier is never consulted as a tie-break."
        PRD: "The sorted population receives `priority_rank` values of 1, 2, 3 and so on with no gaps, and every candidate whose status is `DEFERRED`, `WITHDRAWN` or `CONSUMED` has `priority_rank` set to null."

        Design: Corner/calculations/scope_rank_breaks_score_ties_by_hours_then_creation_order
        """
        advance_clock(client, T_PROGRAMME_OPEN)
        portal_x = created_data(
            client.create_asset(factories.asset_payload(name="Portal X", **PORTAL_TEMPLATE))
        )
        portal_y = created_data(
            client.create_asset(factories.asset_payload(name="Portal Y", **PORTAL_TEMPLATE))
        )
        portal_z = created_data(
            client.create_asset(factories.asset_payload(name="Portal Z", **PORTAL_TEMPLATE))
        )
        plan = created_data(client.create_test_plan(factories.test_plan_payload(**OPEN_APPETITE)))

        candidate_x = _propose(client, plan["id"], portal_x["id"], "Portal X review", 80)
        assert_score(candidate_x["priority_score"], 64.50, "priority_score")
        assert_exact_int(candidate_x["priority_rank"], 1, "priority_rank of the only candidate")
        candidate_y = _propose(client, plan["id"], portal_y["id"], "Portal Y review", 40)
        assert_score(candidate_y["priority_score"], 64.50, "priority_score")
        candidate_z = _propose(client, plan["id"], portal_z["id"], "Portal Z review", 40)
        assert_score(candidate_z["priority_score"], 64.50, "priority_score")

        ranks = {
            "Y": success_data(client.get_scope_item(candidate_y["id"]))["priority_rank"],
            "Z": success_data(client.get_scope_item(candidate_z["id"]))["priority_rank"],
            "X": success_data(client.get_scope_item(candidate_x["id"]))["priority_rank"],
        }

        assert_exact_int(ranks["Y"], 1, "rank of the first 40-hour candidate")
        assert_exact_int(ranks["Z"], 2, "rank of the second 40-hour candidate")
        assert_exact_int(ranks["X"], 3, "rank of the 80-hour candidate")
        assert sorted(ranks.values()) == [1, 2, 3], (
            f"ranks must be contiguous from 1 with no gaps, got {sorted(ranks.values())}"
        )
