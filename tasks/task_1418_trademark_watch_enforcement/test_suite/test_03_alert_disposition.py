"""Alert disposition gates: escalate threshold boundary, dismiss/monitor band,
the monitoring re-assessment loop, invalid from-states, and the opposition window."""
import pytest

from test_helpers import (
    ApiErrorId,
    assess_alert,
    create_alert,
    create_record,
    get_alert,
    get_record,
    make_associate_headers,
    publish_record,
    set_clock,
    setup_assessed_alert,
    setup_published_record,
    triage_alert,
    validate_error,
    validate_success,
)


class TestEscalateThresholdBoundary:
    def _assessed_alert(self, record_id, mark, goods, channels,
                        wm=0.55, wg=0.25, wc=0.20, fame=0, mark_text="AKME"):
        alert = create_alert(record_id, mark, goods, channels,
                             conflicting_mark_text=mark_text)
        alert = triage_alert(alert["id"])
        return assess_alert(alert["id"], alert["version"], wm, wg, wc, fame,
                            rationale="boundary")

    def test_score_exactly_70_escalates(self, api):
        """PRD §3.4: "The `final_score` must be at least 70, else
        `ERR_SCORE_BELOW_THRESHOLD`."
        PRD §3.4: "A successful escalation creates the matter — the response body is
        the created matter, not the alert"

        Design: Difficulty/boundary_precision_check/escalate_threshold_score_70_vs_69_45
        """
        _, record = setup_published_record(classes=(9, 25))
        alert = self._assessed_alert(record["id"], 80, 80, 30)
        assert alert["final_score"] == pytest.approx(70.00, abs=0.001)

        res = api.escalate_alert(alert["id"], {"matter_type": "INFRINGEMENT"},
                                 make_associate_headers("assoc_1"))
        matter = validate_success(res, 201)
        assert matter["status"] == "ACTIVE"
        assert matter["matter_type"] == "INFRINGEMENT"
        assert get_alert(alert["id"])["status"] == "ESCALATED"

    def test_score_69_45_rejected_below_threshold(self, api):
        """PRD §3.4: "The `final_score` must be at least 70, else
        `ERR_SCORE_BELOW_THRESHOLD`."

        Design: Difficulty/boundary_precision_check/escalate_threshold_score_70_vs_69_45
        """
        _, record = setup_published_record(classes=(9, 25))
        alert = self._assessed_alert(record["id"], 79, 80, 30, mark_text="ACM3")
        assert alert["final_score"] == pytest.approx(69.45, abs=0.001)

        res = api.escalate_alert(alert["id"], {"matter_type": "INFRINGEMENT"},
                                 make_associate_headers("assoc_1"))
        validate_error(res, ApiErrorId.ERR_SCORE_BELOW_THRESHOLD, expected_status=422)
        assert get_alert(alert["id"])["status"] == "UNDER_ASSESSMENT"


class TestDismissMonitorBand:
    def test_dismiss_boundary_at_score_40(self, api, associate_headers):
        """PRD §3.3: "Dismissal into `DISMISSED` requires `final_score` below 40 and
        carries a `dismiss_reason`; an alert scoring 40 or above cannot be dismissed
        and the attempt is rejected with `ERR_SCORE_ABOVE_DISMISS_CAP`."
        PRD §3.3: "An attorney may place the alert into `MONITORING` only when
        `final_score` is at least 40 but below 70; an attempt outside that band is
        rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/dismiss_boundary_at_score_40
        """
        _, record, alert = setup_assessed_alert(
            classes=(9,), similarity_mark=50, similarity_goods=30,
            similarity_channels=30, weight_mark=0.5, weight_goods=0.3,
            weight_channels=0.2, fame_adjustment=0)
        assert alert["final_score"] == pytest.approx(40.00, abs=0.001)

        res = api.dismiss_alert(alert["id"], {"dismiss_reason": "trying the boundary"},
                                associate_headers)
        validate_error(res, ApiErrorId.ERR_SCORE_ABOVE_DISMISS_CAP, expected_status=422)

        monitored = validate_success(api.monitor_alert(alert["id"], associate_headers), 200)
        assert monitored["status"] == "MONITORING"

    def test_alert_monitor_reassess_dismiss_loop(self, api, associate_headers):
        """PRD §3.3: "From `TRIAGED` an `AssociateAttorney` records an attorney
        assessment, moving the alert to `UNDER_ASSESSMENT`; the same assessment
        action also loops an `UNDER_ASSESSMENT` alert back into `UNDER_ASSESSMENT`
        (superseding the prior result) and re-opens a `MONITORING` alert into
        `UNDER_ASSESSMENT` for re-assessment."
        PRD §3.3: "Dismissal into `DISMISSED` requires `final_score` below 40 and
        carries a `dismiss_reason`; an alert scoring 40 or above cannot be dismissed
        and the attempt is rejected with `ERR_SCORE_ABOVE_DISMISS_CAP`."

        Design: Corner/state_machines/alert_monitor_reassess_dismiss_loop
        """
        _, record, alert = setup_assessed_alert(
            classes=(9,), similarity_mark=70, similarity_goods=40,
            similarity_channels=40, weight_mark=0.5, weight_goods=0.3,
            weight_channels=0.2, fame_adjustment=0)
        assert alert["final_score"] == pytest.approx(55.00, abs=0.001)
        assert alert["final_tier"] == "MEDIUM"

        monitored = validate_success(api.monitor_alert(alert["id"], associate_headers), 200)
        assert monitored["status"] == "MONITORING"

        fresh = get_alert(alert["id"])
        reassessed = assess_alert(alert["id"], fresh["version"], weight_mark=0.5,
                                  weight_goods=0.3, weight_channels=0.2,
                                  fame_adjustment=-20,
                                  rationale="downgraded after review")
        assert reassessed["status"] == "UNDER_ASSESSMENT"
        assert reassessed["assessment_round"] == 2
        assert reassessed["final_score"] == pytest.approx(35.00, abs=0.001)

        dismissed = validate_success(
            api.dismiss_alert(alert["id"], {"dismiss_reason": "no realistic confusion"},
                              associate_headers), 200)
        assert dismissed["status"] == "DISMISSED"

    def test_escalate_from_triaged_returns_invalid_state(self, api, associate_headers):
        """PRD §3.4: "An `AssociateAttorney` escalates an `UNDER_ASSESSMENT` alert by
        supplying the `matter_type`"
        PRD §2.10: "State — the target entity is in a state from which the requested
        transition is declared, including terminal-state lockdown, else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/escalate_from_triaged_returns_invalid_state
        """
        _, record = setup_published_record(classes=(9,))
        alert = create_alert(record["id"], 90, 90, 90)
        alert = triage_alert(alert["id"])

        res = api.escalate_alert(alert["id"], {"matter_type": "INFRINGEMENT"},
                                 associate_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_alert(alert["id"])["status"] == "TRIAGED"


class TestOppositionEscalationWindow:
    def test_opposition_escalation_window_boundary(self, api, associate_headers):
        """PRD §3.4: "an opposition requires the record to be `PUBLISHED` (anything
        else is `ERR_INVALID_STATE`) and the logical clock must not have passed
        `opposition_due_at` (else `ERR_OPPOSITION_WINDOW_CLOSED`)"
        PRD §3.2: "it moves the record from `APPLICATION_PENDING` to `PUBLISHED` and
        computes `opposition_due_at` as thirty calendar days after publication,
        rolled forward past any Saturday or Sunday under the `CALENDAR_ROLL_FORWARD`
        variant"

        Design: Corner/validations/opposition_escalation_window_boundary
        """
        # Publication 2026-07-31 (Friday) -> opposition_due_at 2026-08-31T00:00:00Z
        # (2026-08-30 was a Sunday, rolled forward to Monday).
        client_a, record_t = setup_published_record(classes=(9,),
                                                    publication_date="2026-07-31T00:00:00Z")
        alert_t = create_alert(record_t["id"], 80, 70, 60,
                               conflicting_mark_text="ONT1ME")
        alert_t = triage_alert(alert_t["id"])
        alert_t = assess_alert(alert_t["id"], alert_t["version"])

        record_l = create_record(client_a["id"], mark_text="TOOLATE", app_no="US-L1")
        record_l = publish_record(record_l["id"], "2026-07-31T00:00:00Z")
        alert_l = create_alert(record_l["id"], 80, 70, 60,
                               conflicting_mark_text="T00LATE")
        alert_l = triage_alert(alert_l["id"])
        alert_l = assess_alert(alert_l["id"], alert_l["version"])

        set_clock("2026-08-31T00:00:00Z")
        res_ok = api.escalate_alert(alert_t["id"], {"matter_type": "OPPOSITION"},
                                    associate_headers)
        matter_t = validate_success(res_ok, 201)
        assert matter_t["matter_type"] == "OPPOSITION"
        assert get_record(record_t["id"])["status"] == "UNDER_CHALLENGE"

        set_clock("2026-08-31T00:00:01Z")
        res_late = api.escalate_alert(alert_l["id"], {"matter_type": "OPPOSITION"},
                                      associate_headers)
        validate_error(res_late, ApiErrorId.ERR_OPPOSITION_WINDOW_CLOSED,
                       expected_status=422)
        assert get_alert(alert_l["id"])["status"] == "UNDER_ASSESSMENT"
        assert get_record(record_l["id"])["status"] == "PUBLISHED"
