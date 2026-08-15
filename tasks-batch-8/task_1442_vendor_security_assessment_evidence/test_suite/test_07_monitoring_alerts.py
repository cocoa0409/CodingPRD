"""Continuous monitoring: alert lifecycle, escalation cascades, reassessment
pull-forward conservation, and posture-based risk scoring (PRD §3.8)."""
import pytest

from test_helpers import (
    ANALYST,
    ApiErrorId,
    assert_instant_equal,
    assert_score,
    create_alert,
    get_success_data,
    list_schedule_events,
    setup_active_policy,
    setup_approved_vendor,
    register_vendor,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _get_alert(api, vendor_id, alert_id):
    alerts = get_success_data(api.list_alerts(vendor_id, ANALYST))
    for alert in alerts:
        if alert["id"] == alert_id:
            return alert
    raise AssertionError(f"Alert {alert_id} not found for vendor {vendor_id}")


class TestEscalationCascade:
    def _approved_vendor_with_critical_alert(self, api):
        ctx = setup_approved_vendor()  # TIER_1, clean pass at the default clock
        alert = create_alert(ctx["vendor"]["id"], signal="BREACH_REPORT", severity="CRITICAL")
        get_success_data(api.acknowledge_alert(ctx["vendor"]["id"], alert["id"], {}, ANALYST))
        return ctx, alert

    def test_escalation_spawns_cycle_and_pulls_due_forward(self, api):
        """PRD §3.8: "Escalating moves the alert `ACKNOWLEDGED → ESCALATED`, its
        terminal state, and pulls the vendor's `next_reassessment_due` forward to
        the current clock plus 14 days for a `CRITICAL` alert, or plus 30 days for
        a `HIGH` one, but only ever earlier — if the existing due date is already
        sooner it stands. The escalation appends a `ReassessmentSchedule` event of
        kind `ALERT_ESCALATION` whose `reason_ref` points at the alert, moves the
        vendor's posture to `ASSESSING`, creates a fresh `DRAFT` assessment cycle
        as the vendor's new `active_cycle_id`, and increments both the alert's and
        the vendor's `version`."

        Existing due is 2029-08-01 (TIER_1 +36 months); min -> 2026-08-15.

        Design: Difficulty/transitive_cascade/alert_escalation_spawns_cycle_and_recomputes_risk
        """
        ctx, alert = self._approved_vendor_with_critical_alert(api)
        escalated = validate_success(
            api.escalate_alert(ctx["vendor"]["id"], alert["id"], {"disposition": "confirmed breach"}, ANALYST),
            200,
        )
        assert escalated["status"] == "ESCALATED"
        vendor = get_success_data(api.get_vendor(ctx["vendor"]["id"], ANALYST))
        assert vendor["posture"] == "ASSESSING"
        assert vendor["active_cycle_id"] is not None
        new_cycle = get_success_data(api.get_cycle(vendor["active_cycle_id"], ANALYST))
        assert new_cycle["status"] == "DRAFT"
        assert new_cycle["id"] != ctx["cycle"]["id"]
        assert_instant_equal(vendor["next_reassessment_due"], "2026-08-15T00:00:00Z")
        events = list_schedule_events(ctx["vendor"]["id"], kind="ALERT_ESCALATION")
        assert any(e["reason_ref"] == alert["id"] for e in events), (
            "An ALERT_ESCALATION event must reference the escalated alert"
        )

    def test_escalation_recomputes_risk_score(self, api):
        """PRD §3.8: "start from a base by posture — 50 for `ONBOARDING`, 60 for
        `ASSESSING`, 20 for `APPROVED`, 45 for `CONDITIONAL`, 85 for `SUSPENDED`,
        70 for `OFFBOARDING`, and 10 for `OFFBOARDED`. Add 5 for every `OPEN` or
        `ACKNOWLEDGED` alert of `HIGH` severity and 10 for every such `CRITICAL`
        alert."
        PRD §3.8: "The score refreshes at vendor registration and attribute
        revision, on every posture change and cycle closure, when alerts are
        recorded, dismissed, or escalated, and when an acceptance expires."

        APPROVED + ACKNOWLEDGED CRITICAL: 20 + 10 = 30.0; after escalation the
        alert is terminal ESCALATED and the posture base is ASSESSING: 60.0.

        Design: Difficulty/transitive_cascade/alert_escalation_spawns_cycle_and_recomputes_risk
        """
        ctx, alert = self._approved_vendor_with_critical_alert(api)
        before = get_success_data(api.get_vendor(ctx["vendor"]["id"], ANALYST))
        assert_score(before["risk_score"], 30.0)
        validate_success(
            api.escalate_alert(ctx["vendor"]["id"], alert["id"], {"disposition": "confirmed"}, ANALYST), 200
        )
        after = get_success_data(api.get_vendor(ctx["vendor"]["id"], ANALYST))
        assert_score(after["risk_score"], 60.0)


class TestPostureBaseVariants:
    def test_approved_vendor_with_critical_alert_scores_thirty(self, api):
        """PRD §3.8: "start from a base by posture — 50 for `ONBOARDING`, 60 for
        `ASSESSING`, 20 for `APPROVED`, 45 for `CONDITIONAL`, 85 for `SUSPENDED`,
        70 for `OFFBOARDING`, and 10 for `OFFBOARDED`. Add 5 for every `OPEN` or
        `ACKNOWLEDGED` alert of `HIGH` severity and 10 for every such `CRITICAL`
        alert."
        PRD §3.8: "The alert opens in `OPEN`, and recording it already refreshes
        the vendor's `risk_score` and bumps the vendor's `version`."

        Design: Difficulty/dual_variant_calc/vendor_risk_score_posture_base_variants
        """
        ctx = setup_approved_vendor()
        create_alert(ctx["vendor"]["id"], signal="BREACH_REPORT", severity="CRITICAL")
        vendor = get_success_data(api.get_vendor(ctx["vendor"]["id"], ANALYST))
        assert vendor["posture"] == "APPROVED"
        assert_score(vendor["risk_score"], 30.0)  # base 20 + OPEN CRITICAL 10

    def test_onboarding_vendor_with_critical_alert_scores_sixty(self, api):
        """PRD §3.8: "start from a base by posture — 50 for `ONBOARDING`, 60 for
        `ASSESSING`, 20 for `APPROVED`, 45 for `CONDITIONAL`, 85 for `SUSPENDED`,
        70 for `OFFBOARDING`, and 10 for `OFFBOARDED`. Add 5 for every `OPEN` or
        `ACKNOWLEDGED` alert of `HIGH` severity and 10 for every such `CRITICAL`
        alert."

        The identical alert modifier on a different posture base diverges:
        ONBOARDING 50 + 10 = 60.0.

        Design: Difficulty/dual_variant_calc/vendor_risk_score_posture_base_variants
        """
        setup_active_policy()
        vendor, _contact = register_vendor()
        create_alert(vendor["id"], signal="BREACH_REPORT", severity="CRITICAL")
        vendor = get_success_data(api.get_vendor(vendor["id"], ANALYST))
        assert vendor["posture"] == "ONBOARDING"
        assert_score(vendor["risk_score"], 60.0)


class TestReassessmentDueConservation:
    def test_dismiss_leaves_next_reassessment_due_unchanged(self, api):
        """PRD §3.8: "dismissing an `ACKNOWLEDGED` alert requires a non-empty
        `disposition` and moves it to `DISMISSED`, refreshing the vendor's risk
        score."
        PRD §3.8: "The same pull-forward machinery serves two other events: a
        risk-acceptance expiry pulls the due date forward to the current clock plus
        30 days under the identical never-later rule (§3.6), and whenever
        `next_reassessment_due` is simply reached for a vendor in `APPROVED` or
        `CONDITIONAL`, the platform returns the vendor to `ASSESSING` and opens a
        fresh `DRAFT` cycle as the active cycle."

        Dismissal is not a pull-forward trigger, so the due date stands.

        Design: Difficulty/compensating_invariant/reassessment_due_conserved_under_escalate_dismiss_pair
        """
        ctx = setup_approved_vendor()
        vendor = get_success_data(api.get_vendor(ctx["vendor"]["id"], ANALYST))
        assert_instant_equal(vendor["next_reassessment_due"], "2029-08-01T00:00:00Z")
        alert = create_alert(ctx["vendor"]["id"], signal="NEGATIVE_NEWS", severity="LOW")
        get_success_data(api.acknowledge_alert(ctx["vendor"]["id"], alert["id"], {}, ANALYST))
        dismissed = validate_success(
            api.dismiss_alert(ctx["vendor"]["id"], alert["id"], {"disposition": "not relevant"}, ANALYST), 200
        )
        assert dismissed["status"] == "DISMISSED"
        after = get_success_data(api.get_vendor(ctx["vendor"]["id"], ANALYST))
        assert_instant_equal(after["next_reassessment_due"], "2029-08-01T00:00:00Z")

    def test_escalation_pulls_forward_with_min_semantics(self, api):
        """PRD §3.8: "Escalating moves the alert `ACKNOWLEDGED → ESCALATED`, its
        terminal state, and pulls the vendor's `next_reassessment_due` forward to
        the current clock plus 14 days for a `CRITICAL` alert, or plus 30 days for
        a `HIGH` one, but only ever earlier — if the existing due date is already
        sooner it stands."

        Design: Difficulty/compensating_invariant/reassessment_due_conserved_under_escalate_dismiss_pair
        """
        from test_helpers import parse_instant

        ctx = setup_approved_vendor()
        low = create_alert(ctx["vendor"]["id"], signal="NEGATIVE_NEWS", severity="LOW")
        get_success_data(api.acknowledge_alert(ctx["vendor"]["id"], low["id"], {}, ANALYST))
        get_success_data(api.dismiss_alert(ctx["vendor"]["id"], low["id"], {"disposition": "noise"}, ANALYST))
        before = get_success_data(api.get_vendor(ctx["vendor"]["id"], ANALYST))
        critical = create_alert(ctx["vendor"]["id"], signal="BREACH_REPORT", severity="CRITICAL")
        get_success_data(api.acknowledge_alert(ctx["vendor"]["id"], critical["id"], {}, ANALYST))
        validate_success(
            api.escalate_alert(ctx["vendor"]["id"], critical["id"], {"disposition": "confirmed"}, ANALYST), 200
        )
        after = get_success_data(api.get_vendor(ctx["vendor"]["id"], ANALYST))
        assert_instant_equal(after["next_reassessment_due"], "2026-08-15T00:00:00Z")
        assert parse_instant(after["next_reassessment_due"]) <= parse_instant(before["next_reassessment_due"])


class TestEscalationPreconditions:
    def test_low_severity_alert_not_escalatable(self, api):
        """PRD §3.8: "Escalation is the heavy path and is restricted twice over: the
        alert must be `ACKNOWLEDGED` with `severity` `HIGH` or `CRITICAL`, and the
        vendor's posture must be `APPROVED` or `CONDITIONAL` — anything else is
        rejected with `ERR_ALERT_NOT_ESCALATABLE` (HTTP 422)."

        Design: Corner/state_machines/monitored_alert_escalate_requires_high_or_critical
        """
        ctx = setup_approved_vendor()
        alert = create_alert(ctx["vendor"]["id"], signal="NEGATIVE_NEWS", severity="LOW")
        get_success_data(api.acknowledge_alert(ctx["vendor"]["id"], alert["id"], {}, ANALYST))
        res = api.escalate_alert(ctx["vendor"]["id"], alert["id"], {}, ANALYST)
        validate_error(res, ApiErrorId.ERR_ALERT_NOT_ESCALATABLE)
        assert _get_alert(api, ctx["vendor"]["id"], alert["id"])["status"] == "ACKNOWLEDGED"
