"""Dual-variant calculations: candidate prioritisation and engagement assurance."""

from test_helpers import factories
from test_helpers.assertions import (
    assert_engagement_axes,
    assert_exact_int,
    assert_score,
    assert_severity,
    created_data,
    find_alert_for_finding,
    success_data,
)
from test_helpers.constants import T_FIELDWORK_DAY, T_PROGRAMME_OPEN
from test_helpers.fixtures import (
    accept_finding,
    advance_clock,
    build_scenario,
    open_remediation,
    open_retest,
    report_finding,
    submit_evidence,
    read_plan_version,
)
from test_helpers.test_users import program_manager_headers


def _plan_with_two_candidates(client):
    """A risk-driven plan holding the payments application and the analytics lake."""
    advance_clock(client, T_PROGRAMME_OPEN)
    asset_a = created_data(client.create_asset(factories.asset_payload()))
    asset_b = created_data(client.create_asset(factories.analytics_lake_asset_payload()))
    plan = created_data(client.create_test_plan(factories.test_plan_payload()))
    candidate_a = created_data(
        client.create_scope_item(
            factories.scope_item_payload(plan["id"], asset_a["id"], plan["version"])
        )
    )
    candidate_b = created_data(
        client.create_scope_item(
            factories.scope_item_payload(
                plan["id"],
                asset_b["id"],
                read_plan_version(client, plan["id"]),
                justification="Cloud IAM review requested by audit",
                requested_engagement_hours=60,
            )
        )
    )
    return {
        "plan_id": plan["id"],
        "candidate_a_id": candidate_a["id"],
        "candidate_b_id": candidate_b["id"],
    }


class TestCandidatePrioritisationWeighting:
    """The two weight vectors score the same estate differently."""

    def test_risk_driven_weighting_puts_the_exposed_payments_estate_first(self, client):
        """Under the default weighting the tier-1 payments application outscores the
        never-tested analytics lake, and the lake falls below the admission threshold.

        PRD: "Under `RISK_DRIVEN` — the default — exposure is weighted 0.45, tier points 0.30, staleness points 0.20 and regime points 0.05, so attack surface and business criticality dominate."

        Design: Difficulty/dual_variant_calc/scope_priority_score_mode_flip_inverts_candidate_ranking
        """
        programme = _plan_with_two_candidates(client)

        plan = success_data(client.get_test_plan(programme["plan_id"]))
        assert_exact_int(plan["admission_threshold"], 60, "admission_threshold")

        candidate_a = success_data(client.get_scope_item(programme["candidate_a_id"]))
        assert_score(candidate_a["priority_score"], 89.80, "payments priority_score")
        assert_exact_int(candidate_a["priority_rank"], 1, "payments priority_rank")
        assert candidate_a["scored_mode"] == "RISK_DRIVEN"

        candidate_b = success_data(client.get_scope_item(programme["candidate_b_id"]))
        assert_score(candidate_b["priority_score"], 58.00, "analytics priority_score")
        assert_exact_int(candidate_b["priority_rank"], 2, "analytics priority_rank")
        assert candidate_b["below_threshold_flag"] is True

    def test_switching_to_compliance_driven_weighting_inverts_the_ranking(self, client):
        """Rescoring the same two candidates under the regulatory weighting swaps their
        ranks and lifts the heavily regulated lake above the admission threshold.

        PRD: "Under `COMPLIANCE_DRIVEN` the weights become 0.20 for exposure, 0.25 for tier points, 0.15 for staleness points and 0.40 for regime points, so regulatory footprint dominates instead — which is enough to invert the relative ranking of the same two assets."

        Design: Difficulty/dual_variant_calc/scope_priority_score_mode_flip_inverts_candidate_ranking
        """
        programme = _plan_with_two_candidates(client)

        success_data(
            client.set_prioritization_mode(programme["plan_id"], "COMPLIANCE_DRIVEN")
        )

        candidate_a = success_data(client.get_scope_item(programme["candidate_a_id"]))
        candidate_b = success_data(client.get_scope_item(programme["candidate_b_id"]))

        assert_score(candidate_a["priority_score"], 72.25, "payments priority_score")
        assert_score(candidate_b["priority_score"], 75.50, "analytics priority_score")
        assert_exact_int(candidate_a["priority_rank"], 2, "payments priority_rank")
        assert_exact_int(candidate_b["priority_rank"], 1, "analytics priority_rank")
        assert candidate_b["below_threshold_flag"] is False

    def test_each_candidate_records_the_weighting_that_produced_its_score(self, client):
        """Both rescored candidates report the mode that produced the stored score.

        PRD: "The rounded result is written to `priority_score`, and the mode that produced it is recorded in `scored_mode` so a reader can always tell which weighting a stored score reflects."

        Design: Difficulty/dual_variant_calc/scope_priority_score_mode_flip_inverts_candidate_ranking
        """
        programme = _plan_with_two_candidates(client)

        success_data(
            client.set_prioritization_mode(programme["plan_id"], "COMPLIANCE_DRIVEN")
        )

        candidate_a = success_data(client.get_scope_item(programme["candidate_a_id"]))
        candidate_b = success_data(client.get_scope_item(programme["candidate_b_id"]))
        assert candidate_a["scored_mode"] == "COMPLIANCE_DRIVEN"
        assert candidate_b["scored_mode"] == "COMPLIANCE_DRIVEN"


def _engagement_with_one_open_critical_and_one_closed_medium(client):
    """Wind an engagement down to the point where only the closing actions remain."""
    scenario = build_scenario(
        client,
        roe={
            "exclusions": ["prod-db-01"],
            "allowed_techniques": ["SQLI", "XSS", "AUTHZ_BYPASS"],
        },
        target={"technique_allowlist": ["SQLI", "XSS"]},
    )
    advance_clock(client, T_FIELDWORK_DAY)

    critical = report_finding(
        client, scenario, title="Authorization bypass on refund endpoint"
    )
    alert = find_alert_for_finding(client, critical["id"])
    success_data(
        client.acknowledge_critical_alert(
            alert["id"], "Refund endpoint disabled at the gateway"
        )
    )

    medium = report_finding(
        client, scenario, secondary=True, root_cause_theme="INPUT_VALIDATION"
    )

    accept_finding(client, critical["id"])
    accept_finding(client, medium["id"], note="Confirmed")

    remediation = open_remediation(
        client,
        medium["id"],
        validation_requirement="EVIDENCE_ONLY",
        remediation_plan="Disable debug error handler in production profile",
    )
    submit_evidence(client, remediation["id"], "s3://evidence/rem2/config-diff.txt")
    verification = open_retest(
        client, remediation["id"], evidence_uri="s3://evidence/rem2/retest.har"
    )
    success_data(
        client.sign_off_retest_verification(
            verification["id"], "Stack traces no longer returned"
        )
    )
    return scenario, critical, medium


class TestEngagementAssuranceVariants:
    """The provisional and final assurance numbers read the same findings differently."""

    def test_provisional_assurance_deducts_for_the_closed_finding_as_well(self, client):
        """At fieldwork completion both the open critical finding and the already closed
        medium one are deducted, so the engagement scores 70.00 with no credit at all.

        PRD: "The **provisional** variant, stamped into `provisional_assurance_score` when fieldwork completes and before any remediation has been verified, counts every finding of the engagement whose status is anything other than `DUPLICATE` — so findings that have already been closed still count against it — and grants no credit whatsoever."

        Design: Difficulty/dual_variant_calc/assurance_score_provisional_and_final_diverge_on_identical_findings
        """
        scenario, critical, medium = _engagement_with_one_open_critical_and_one_closed_medium(
            client
        )

        engagement = success_data(
            client.drive_execution(scenario["engagement_id"], "COMPLETE_FIELDWORK")
        )
        assert_score(
            engagement["provisional_assurance_score"], 70.00, "provisional_assurance_score"
        )

        rated_critical = success_data(
            client.get_finding(critical["id"], headers=program_manager_headers())
        )
        assert_severity(rated_critical, score=9.20, band="CRITICAL")
        rated_medium = success_data(
            client.get_finding(medium["id"], headers=program_manager_headers())
        )
        assert_severity(rated_medium, score=4.50, band="MEDIUM")
        assert rated_medium["status"] == "CLOSED"

    def test_final_assurance_excludes_the_closed_finding_and_credits_its_closure(
        self, client
    ):
        """At closure the same data scores 80.00: the closed medium finding leaves the
        deduction set and earns a retest credit, so the two variants differ by 10.00.

        PRD: "The **final** variant, stamped into `final_assurance_score` when the engagement closes or is terminated, excludes both `DUPLICATE` and `CLOSED` findings from its deduction set and then adds back a retest credit of 5 points for each finding of the engagement that has reached `CLOSED`, capped at 20 points however many closures there were."

        Design: Difficulty/dual_variant_calc/assurance_score_provisional_and_final_diverge_on_identical_findings
        """
        scenario, _critical, _medium = _engagement_with_one_open_critical_and_one_closed_medium(
            client
        )

        success_data(client.drive_execution(scenario["engagement_id"], "COMPLETE_FIELDWORK"))
        success_data(client.drive_execution(scenario["engagement_id"], "REPORT"))
        closed = success_data(client.drive_execution(scenario["engagement_id"], "CLOSE"))

        assert_score(closed["final_assurance_score"], 80.00, "final_assurance_score")
        assert_score(
            closed["provisional_assurance_score"], 70.00, "provisional_assurance_score"
        )
        assert_engagement_axes(closed, execution_state="CLOSED")

    def test_the_plan_closes_when_its_only_engagement_closes(self, client):
        """Closing the plan's single engagement bubbles up and closes the plan itself.

        PRD: "There is no operation that closes a plan directly: the plan moves `ACTIVE` → `CLOSED` when the bubble-up condition holds — the plan has at least one engagement, and every engagement of the plan has reached `CLOSED` on its execution axis."

        Design: Difficulty/dual_variant_calc/assurance_score_provisional_and_final_diverge_on_identical_findings
        """
        scenario, _critical, _medium = _engagement_with_one_open_critical_and_one_closed_medium(
            client
        )

        success_data(client.drive_execution(scenario["engagement_id"], "COMPLETE_FIELDWORK"))
        success_data(client.drive_execution(scenario["engagement_id"], "REPORT"))
        success_data(client.drive_execution(scenario["engagement_id"], "CLOSE"))

        plan = success_data(client.get_test_plan(scenario["plan_id"]))
        assert plan["status"] == "CLOSED"
