"""Two multi-input formulas whose grouping and rounding order are observable.

The severity rating combines four inputs — the tester's technical base score, the
finding's exposure class, the asset's criticality tier and the asset's regime
count — and the exposure multiplier binds to the base score alone, so a reader
who multiplies the whole sum gets a different number. The training-priority
score rounds every finding's contribution before the contributions are added,
so a reader who sums first and rounds once gets a different number too.
"""

import pytest

from test_helpers.assertions import (
    assert_alert_raised,
    assert_instant_equals,
    assert_no_alert_raised,
    assert_risk_ledger,
    assert_severity,
    emitted_rows,
    success_data,
)
from test_helpers.constants import CLOCK_EPOCH, T_FIELDWORK_DAY
from test_helpers.fixtures import advance_clock, build_scenario, report_finding

# The training-analysis timeline, which runs a fortnight either side of the
# ordinary programme window so the recency decay has room to bite.
ENGAGEMENT_WINDOW_START = "2026-08-05T00:00:00Z"
ENGAGEMENT_WINDOW_END = "2026-10-05T00:00:00Z"
T_STAFFING = "2026-08-11T00:00:00Z"
T_OLDEST_FINDING = "2026-08-12T00:00:00Z"
T_MIDDLE_FINDING = "2026-09-27T00:00:00Z"
T_NEWEST_FINDING = "2026-09-30T00:00:00Z"
T_ANALYSIS = "2026-10-01T00:00:00Z"


def _internet_and_internal_findings(client):
    """File one internet-facing and one internal finding on the same tier-1 asset."""
    scenario = build_scenario(
        client,
        roe={
            "exclusions": ["prod-db-01"],
            "allowed_techniques": ["SQLI", "XSS", "AUTHZ_BYPASS"],
        },
        target={"technique_allowlist": ["SQLI", "XSS"]},
    )
    advance_clock(client, T_FIELDWORK_DAY)

    internet = report_finding(
        client,
        scenario,
        title="Unauthenticated admin console reachable from the internet",
        reproduction_steps=(
            "1. Browse to /admin from an external IP 2. Observe the console renders"
        ),
        business_impact_narrative=(
            "Anyone on the internet can administer the payment gateway"
        ),
        technical_base_score=8.0,
        exposure_class="INTERNET",
        root_cause_theme="ACCESS_CONTROL",
    )
    internal = report_finding(
        client,
        scenario,
        secondary=True,
        title="Internal debug endpoint returns configuration",
        reproduction_steps=(
            "1. From the internal VLAN GET /debug/config 2. Observe secrets"
        ),
        business_impact_narrative="Internal staff can read gateway credentials",
        technical_base_score=4.0,
        exposure_class="INTERNAL",
        root_cause_theme="SECRETS_HANDLING",
    )
    return scenario, internet, internal


class TestSeverityRatingGrouping:
    """The exposure multiplier scales the base score and nothing else."""

    def test_the_internet_multiplier_scales_the_base_score_before_the_bonuses_are_added(
        self, client
    ):
        """8.00 * 1.15 = 9.20, plus 0.50 for tier 1 and 0.20 for one regime, is 9.90 —
        not the 10.00 that multiplying the whole sum and clamping would produce.

        PRD: "**The multiplier applies to the technical base score alone, before anything is added.**"

        PRD: "The resulting total is **clamped down to 10.00 first and only then rounded** half-up to two decimal places, and the result is `severity_score`."

        Design: Difficulty/combinatorial_formula/severity_multiplier_binds_only_to_technical_base_score
        """
        _scenario, internet, _internal = _internet_and_internal_findings(client)

        assert internet["severity_score"] == pytest.approx(9.90, abs=0.001)
        assert internet["severity_score"] != pytest.approx(10.00, abs=0.001)
        assert_severity(internet, score=9.90, band="CRITICAL", points=40, immediate=True)

    def test_neither_bonus_is_scaled_by_the_internal_exposure_factor(self, client):
        """4.00 * 0.95 = 3.80 plus the unscaled 0.70 of bonuses is 4.50 — not the 4.47
        that scaling the bonuses along with the base score would produce.

        PRD: "Neither the tier bonus nor the regime bonus is ever multiplied by the exposure factor."

        PRD: "It then adds a regulatory bonus of 0.20 for each compliance regime the asset carries, capped at 0.60 however many regimes there are — so three or more regimes all yield the same 0.60."

        Design: Difficulty/combinatorial_formula/severity_multiplier_binds_only_to_technical_base_score
        """
        _scenario, _internet, internal = _internet_and_internal_findings(client)

        assert internal["severity_score"] == pytest.approx(4.50, abs=0.001)
        assert internal["severity_score"] != pytest.approx(4.47, abs=0.001)
        assert_severity(internal, score=4.50, band="MEDIUM", points=8, immediate=False)

    def test_the_two_band_weights_are_the_plans_whole_risk_ledger(self, client):
        """A CRITICAL finding at 40 points and a MEDIUM one at 8 leave the plan at 48,
        all of it in the open bucket.

        PRD: "`severity_points` is the band's conserved ledger weight: 40 points for `CRITICAL`, 20 for `HIGH`, 8 for `MEDIUM` and 2 for `LOW`."

        PRD: "Its points are added to the plan's `total_risk_points` and to its `open_risk_points`."

        Design: Difficulty/combinatorial_formula/severity_multiplier_binds_only_to_technical_base_score
        """
        scenario, _internet, _internal = _internet_and_internal_findings(client)

        plan = success_data(client.get_test_plan(scenario["plan_id"]))
        assert_risk_ledger(plan, total=48, open_points=48, closed=0, accepted=0, duplicate=0)

    def test_only_the_critical_finding_raises_an_alert_and_it_is_due_within_the_hour(
        self, client
    ):
        """The 9.90 finding raises exactly one alert due 60 minutes after discovery
        because it is internet-facing; the 4.50 finding raises none at all.

        PRD: "Its `ack_deadline_at` is `raised_at` advanced by a window that depends on the finding's `exposure_class`: an internet-facing critical finding must be acknowledged within one hour, that is 60 minutes, while a partner-facing or internal critical finding is allowed four hours, that is 240 minutes."

        PRD: "No alert is ever created for a finding whose band is not `CRITICAL`, and every `CRITICAL` finding has exactly one."

        Design: Difficulty/combinatorial_formula/severity_multiplier_binds_only_to_technical_base_score
        """
        _scenario, internet, internal = _internet_and_internal_findings(client)

        alert = assert_alert_raised(
            client,
            internet["id"],
            ack_deadline_at="2026-09-08T11:00:00Z",
            state="RAISED",
            escalation_level=1,
        )
        assert_instant_equals(alert["raised_at"], internet["discovered_at"], "raised_at")
        assert_no_alert_raised(client, internal["id"])


def _three_access_control_findings(client):
    """File three access-control findings spread across the analysis window."""
    scenario = build_scenario(
        client,
        open_clock=CLOCK_EPOCH,
        engagement={
            "window_start": ENGAGEMENT_WINDOW_START,
            "window_end": ENGAGEMENT_WINDOW_END,
        },
        roe={"allowed_techniques": ["SQLI", "XSS", "AUTHZ_BYPASS"]},
        target={
            "window_start": ENGAGEMENT_WINDOW_START,
            "window_end": ENGAGEMENT_WINDOW_END,
            "technique_allowlist": ["SQLI", "AUTHZ_BYPASS"],
        },
        sign_note="Authorized for the FY2026 window",
        pre_assignment_clock=T_STAFFING,
        assignment={"interval_start": T_STAFFING, "interval_end": T_ANALYSIS},
    )

    advance_clock(client, T_OLDEST_FINDING)
    oldest = report_finding(
        client,
        scenario,
        title="Horizontal privilege escalation in ledger export",
        reproduction_steps=(
            "1. Authenticate as clerk 2. GET /exports/{other_tenant_id}"
        ),
        business_impact_narrative="Clerks can export another tenant's ledger",
        technical_base_score=6.5,
        exposure_class="PARTNER",
        root_cause_theme="ACCESS_CONTROL",
    )

    advance_clock(client, T_MIDDLE_FINDING)
    middle = report_finding(client, scenario)

    advance_clock(client, T_NEWEST_FINDING)
    newest = report_finding(
        client,
        scenario,
        title="Role check missing on settlement approval",
        reproduction_steps=(
            "1. Authenticate as viewer 2. POST /settlements/{id}/approve"
        ),
        business_impact_narrative="Viewers can approve settlements without review",
    )

    advance_clock(client, T_ANALYSIS)
    return scenario, (oldest, middle, newest)


def _run_trend_analysis(client, plan_id):
    """Emit the training recommendations for the whole two-month window."""
    return emitted_rows(
        client.generate_training_recommendations(
            plan_id, window_start=CLOCK_EPOCH, window_end=T_ANALYSIS
        )
    )


class TestTrainingPriorityRoundingOrder:
    """Per-finding rounding precedes the summation, and the difference is 0.01."""

    def test_each_contribution_is_rounded_before_the_contributions_are_summed(self, client):
        """The three contributions round to 4.97, 4.87 and 2.00 and total 11.84; summing
        the raw 4.9666667, 4.8666667 and 2.0 first would give 11.83 instead.

        PRD: "Each finding's contribution is its severity weight multiplied by its recency multiplier, **rounded half-up to two decimal places before anything is summed**."

        PRD: "The rounding order is pinned and observable: summing the unrounded contributions and rounding once at the end produces a different score for the same data, and that is not the required behaviour."

        Design: Difficulty/combinatorial_formula/training_priority_rounds_each_contribution_before_summing
        """
        scenario, _findings = _three_access_control_findings(client)

        rows = _run_trend_analysis(client, scenario["plan_id"])

        assert len(rows) == 1, f"expected one recommendation, got {len(rows)}"
        assert round(float(rows[0]["priority_score"]), 2) == 11.84
        assert round(float(rows[0]["priority_score"]), 2) != 11.83

    def test_the_recommendation_reports_its_recurrence_and_its_source_engagements(
        self, client
    ):
        """Three contributing findings drawn from a single engagement, measured against
        the generation instant that drove the recency decay.

        PRD: "Each recommendation also records `recurrence_count`, the number of contributing findings for the theme in the window; `source_engagement_count`, the number of distinct engagements those contributing findings came from; and `generated_at`, the logical-clock instant of generation, against which the recency decay was measured."

        Design: Difficulty/combinatorial_formula/training_priority_rounds_each_contribution_before_summing
        """
        scenario, _findings = _three_access_control_findings(client)

        rows = _run_trend_analysis(client, scenario["plan_id"])

        assert len(rows) == 1
        recommendation = rows[0]
        assert recommendation["root_cause_theme"] == "ACCESS_CONTROL"
        assert recommendation["recurrence_count"] == 3
        assert recommendation["source_engagement_count"] == 1
        assert_instant_equals(recommendation["generated_at"], T_ANALYSIS, "generated_at")

    def test_the_urgency_band_is_mandatory_because_both_conditions_hold(self, client):
        """Recurrence 3 reaches the count floor and 11.84 clears 8.00, so the theme
        becomes mandatory training rather than a recommendation.

        PRD: "`urgency_band` is `MANDATORY` when `recurrence_count` is at least 3 **and** `priority_score` is at least 8.00, and `RECOMMENDED` in every other case — both conditions must hold, so a single devastating finding is never mandatory training on its own."

        Design: Difficulty/combinatorial_formula/training_priority_rounds_each_contribution_before_summing
        """
        scenario, _findings = _three_access_control_findings(client)

        rows = _run_trend_analysis(client, scenario["plan_id"])

        assert rows[0]["urgency_band"] == "MANDATORY"
        assert rows[0]["recurrence_count"] >= 3
        assert float(rows[0]["priority_score"]) >= 8.00

    def test_the_contributing_findings_are_listed_in_discovery_order(self, client):
        """The oldest discovery comes first and the newest last.

        PRD: "Contributing findings are ordered by `discovered_at` ascending and then by `created_at` ascending, and that same ordering is what `contributing_finding_ids` records."

        Design: Difficulty/combinatorial_formula/training_priority_rounds_each_contribution_before_summing
        """
        scenario, findings = _three_access_control_findings(client)
        oldest, middle, newest = findings

        rows = _run_trend_analysis(client, scenario["plan_id"])

        assert rows[0]["contributing_finding_ids"] == [
            oldest["id"],
            middle["id"],
            newest["id"],
        ]
