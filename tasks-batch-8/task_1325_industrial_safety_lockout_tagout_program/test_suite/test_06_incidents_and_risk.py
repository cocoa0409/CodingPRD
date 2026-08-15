"""Incident reports and machine risk scoring: dismissal filtering, the two
risk-window variants, and the HIGH-tier automatic shutdown cascade."""
from test_helpers import (
    assert_instant_equal,
    bootstrap_manager,
    create_approved_survey,
    create_active_procedure,
    create_machine,
    dismiss_incident,
    get_incident,
    get_lock,
    get_machine,
    get_session,
    issue_lock,
    link_incident,
    register_employee,
    report_incident,
    set_logical_clock,
    setup_session_in_setup,
)

INCIDENT_SET = (
    ("NEAR_MISS", "2025-12-10T00:00:00Z", 2),
    ("NEAR_MISS", "2026-01-15T00:00:00Z", 2),
    ("PROPERTY_DAMAGE", "2026-02-01T00:00:00Z", 3),
)


class TestRiskWindowVariantsDiverge:
    def _setup_dual_window_scenario(self, api):
        """Two machines, identical incident sets; machine B's procedure is
        activated at 2026-01-01T00:00:00Z."""
        mgr = bootstrap_manager("E-MGR-RW", "Mgr RW")
        surveyor = register_employee(mgr, "E-W1-RW", "W1 RW")
        machine_a = create_machine(mgr, asset_tag="A-RW-100", name="Press A",
                                   area="Line 1", risk_window_policy="ROLLING_12MO")
        set_logical_clock(mgr, "2026-01-01T00:00:00Z")
        machine_b = create_machine(
            mgr, asset_tag="B-RW-100", name="Press B", area="Line 1",
            risk_window_policy="SINCE_PROCEDURE_ACTIVATION")
        survey_b = create_approved_survey(mgr, surveyor, machine_b["id"])
        procedure_b = create_active_procedure(mgr, machine_b["id"], survey_b["id"])
        set_logical_clock(mgr, "2026-08-01T00:00:00Z")

        incidents = {"a": [], "b": []}
        for label, machine in (("a", machine_a), ("b", machine_b)):
            for kind, occurred_at, severity in INCIDENT_SET:
                incident = report_incident(mgr, machine["id"], kind=kind,
                                           occurred_at=occurred_at,
                                           severity=severity)
                incidents[label].append(incident["id"])
        return mgr, machine_a, machine_b, procedure_b, incidents

    def test_rolling_12mo_window_counts_all_three_incidents(self, api):
        """PRD §3.8: "Under `ROLLING_12MO`, the window is the trailing 365 days:
        reports whose `occurred_at` falls on or after the instant exactly 365
        days before the current clock count, and older reports drop out even if
        they postdate the current procedure's activation."
        PRD §3.8: "Each included report contributes a weight determined by its
        `kind`: `NEAR_MISS` contributes 1, `FIRST_AID` 2, `PROPERTY_DAMAGE` 3,
        and `INJURY` 5."
        PRD §3.8: "The `risk_score` is the sum of those weights, computed in
        integer arithmetic with no rounding, and the `risk_tier` is derived from
        the score: below 5 is `LOW`; at least 5 and below 10 is `MEDIUM`; 10 or
        more is `HIGH`."

        Design: Difficulty/dual_variant_calc/risk_window_variants_diverge
        """
        mgr, machine_a, _machine_b, _proc_b, incidents = \
            self._setup_dual_window_scenario(api)
        for incident_id in incidents["a"]:
            link_incident(mgr, incident_id)

        machine_a = get_machine(mgr, machine_a["id"])
        assert machine_a["risk_score"] == 5, "1 + 1 + 3 over the trailing 365 days"
        assert machine_a["risk_tier"] == "MEDIUM"
        assert machine_a["status"] == "IN_SERVICE", \
            "MEDIUM does not trigger the automatic shutdown"

    def test_since_procedure_activation_window_drops_pre_activation_incident(self, api):
        """PRD §3.8: "Under `SINCE_PROCEDURE_ACTIVATION`, the window opens at the
        `activated_at` of the machine's current procedure — defined as the
        revision with the greatest `revision_no` that is neither `SUPERSEDED` nor
        `RETIRED` — and reports before that instant drop out even when they fall
        inside the trailing year; if the machine has no such procedure, the score
        is zero."
        PRD §3.8: "The `risk_score` is the sum of those weights, computed in
        integer arithmetic with no rounding, and the `risk_tier` is derived from
        the score: below 5 is `LOW`; at least 5 and below 10 is `MEDIUM`; 10 or
        more is `HIGH`."

        Design: Difficulty/dual_variant_calc/risk_window_variants_diverge
        """
        mgr, _machine_a, machine_b, procedure_b, incidents = \
            self._setup_dual_window_scenario(api)
        assert_instant_equal(procedure_b["activated_at"], "2026-01-01T00:00:00Z")
        for incident_id in incidents["b"]:
            link_incident(mgr, incident_id)

        machine_b = get_machine(mgr, machine_b["id"])
        assert machine_b["risk_score"] == 4, \
            "the 2025-12-10 near-miss predates activation and drops out: 1 + 3"
        assert machine_b["risk_tier"] == "LOW"
        assert machine_b["status"] == "IN_SERVICE"


class TestDismissedIncidentsExcluded:
    def test_dismissed_incidents_excluded_from_risk(self, api):
        """PRD §3.8: "Dismissal moves the report to `DISMISSED`, and a dismissed
        report never contributes to risk scoring."
        PRD §3.8: "Each included report contributes a weight determined by its
        `kind`: `NEAR_MISS` contributes 1, `FIRST_AID` 2, `PROPERTY_DAMAGE` 3,
        and `INJURY` 5."
        PRD §3.8: "The `risk_score` is the sum of those weights, computed in
        integer arithmetic with no rounding, and the `risk_tier` is derived from
        the score: below 5 is `LOW`; at least 5 and below 10 is `MEDIUM`; 10 or
        more is `HIGH`."

        Design: Corner/calculations/dismissed_incidents_excluded_from_risk
        """
        mgr = bootstrap_manager("E-MGR-DI", "Mgr DI")
        machine = create_machine(mgr, asset_tag="A-DI-1", name="Press",
                                 area="Bay 17")
        near_miss = report_incident(mgr, machine["id"], kind="NEAR_MISS",
                                    occurred_at="2026-07-20T00:00:00Z", severity=1)
        damage = report_incident(mgr, machine["id"], kind="PROPERTY_DAMAGE",
                                 occurred_at="2026-07-21T00:00:00Z", severity=3)

        dismissed = dismiss_incident(mgr, near_miss["id"])
        assert dismissed["status"] == "DISMISSED"
        linked = link_incident(mgr, damage["id"])
        assert linked["status"] == "LINKED"

        machine = get_machine(mgr, machine["id"])
        assert machine["risk_score"] == 3, "only the LINKED report contributes"
        assert machine["risk_tier"] == "LOW"
        assert machine["status"] == "IN_SERVICE"


class TestHighRiskCascade:
    def _setup_machine_at_medium(self, api, suffix):
        """Session in SETUP with an ISSUED lock; first INJURY linked (score 5)."""
        ctx = setup_session_in_setup(asset_tag=f"A-IC-{suffix}")
        ctx["lock"] = issue_lock(ctx["primary"], ctx["session"]["id"],
                                 f"L-IC-{suffix}1", f"T-IC-{suffix}1")
        ctx["i1"] = report_incident(ctx["mgr"], ctx["machine"]["id"],
                                    kind="INJURY",
                                    occurred_at="2026-07-01T00:00:00Z", severity=4)
        ctx["i2"] = report_incident(ctx["mgr"], ctx["machine"]["id"],
                                    kind="INJURY",
                                    occurred_at="2026-07-02T00:00:00Z", severity=5)
        return ctx

    def test_first_injury_link_reaches_medium_without_shutdown(self, api):
        """PRD §3.8: "When a linkage causes the machine's `risk_tier` to cross
        into `HIGH` — that is, the recomputed `risk_score` reaches 10 or more —
        the machine moves itself from `IN_SERVICE` to `OUT_OF_SERVICE`, with the
        same cascades as the manual transition: sessions still in `SETUP` are
        cancelled, their `ISSUED` locks are voided, and `open_session_count` is
        recomputed. The safeguard fires only on crossing into `HIGH`, never when
        the machine is already there, and — exactly like the manual path —
        sessions in `LOCKED` are treated as work in progress and are not
        cancelled."
        PRD §3.8: "The `risk_score` is the sum of those weights, computed in
        integer arithmetic with no rounding, and the `risk_tier` is derived from
        the score: below 5 is `LOW`; at least 5 and below 10 is `MEDIUM`; 10 or
        more is `HIGH`."

        Design: Difficulty/transitive_cascade/incident_link_high_risk_cascade
        """
        ctx = self._setup_machine_at_medium(api, "A")
        link_incident(ctx["mgr"], ctx["i1"]["id"])

        machine = get_machine(ctx["mgr"], ctx["machine"]["id"])
        assert machine["risk_score"] == 5, "one INJURY contributes 5"
        assert machine["risk_tier"] == "MEDIUM"
        assert machine["status"] == "IN_SERVICE", \
            "no crossing yet — the conditional cascade does not fire"
        assert get_session(ctx["mgr"], ctx["session"]["id"])["status"] == "SETUP"
        assert get_lock(ctx["mgr"], ctx["lock"]["id"])["status"] == "ISSUED"

    def test_second_injury_link_crosses_into_high_and_cascades(self, api):
        """PRD §3.8: "When a linkage causes the machine's `risk_tier` to cross
        into `HIGH` — that is, the recomputed `risk_score` reaches 10 or more —
        the machine moves itself from `IN_SERVICE` to `OUT_OF_SERVICE`, with the
        same cascades as the manual transition: sessions still in `SETUP` are
        cancelled, their `ISSUED` locks are voided, and `open_session_count` is
        recomputed. The safeguard fires only on crossing into `HIGH`, never when
        the machine is already there, and — exactly like the manual path —
        sessions in `LOCKED` are treated as work in progress and are not
        cancelled."
        PRD §3.8: "Linkage moves the report to `LINKED`, stamps `linked_at` with
        the clock, and recomputes the machine's `risk_score`."

        Design: Difficulty/transitive_cascade/incident_link_high_risk_cascade
        """
        ctx = self._setup_machine_at_medium(api, "B")
        link_incident(ctx["mgr"], ctx["i1"]["id"])
        link_incident(ctx["mgr"], ctx["i2"]["id"])

        machine = get_machine(ctx["mgr"], ctx["machine"]["id"])
        assert machine["risk_score"] == 10, "two INJURY reports: 5 + 5"
        assert machine["risk_tier"] == "HIGH"
        assert machine["status"] == "OUT_OF_SERVICE", \
            "crossing into HIGH forces the machine out of service"
        assert get_session(ctx["mgr"], ctx["session"]["id"])["status"] == "CANCELLED"
        assert get_lock(ctx["mgr"], ctx["lock"]["id"])["status"] == "VOIDED"

        assert get_incident(ctx["mgr"], ctx["i1"]["id"])["status"] == "LINKED"
        assert get_incident(ctx["mgr"], ctx["i2"]["id"])["status"] == "LINKED"
