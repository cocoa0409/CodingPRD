"""Incidents: recordability fork, close duties, OSHA deadlines, logical clock."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_incident,
    add_media,
    assert_instant_equal,
    create_incident_payload,
    get_incident,
    get_report,
    make_active_project,
    make_report,
    make_report_bundle,
    make_safety_officer_headers,
    make_work_area,
    set_clock,
    validate_error,
    validate_success,
)

_ADMIN = TEST_USERS["system_admin_headers"]
_SO = TEST_USERS["safety_officer_headers"]

_LONG_NARRATIVE = ("Worker fell from a ladder at level 3 east and was "
                   "hospitalized overnight for observation.")


class TestRecordableBranchingFork:
    def test_recordable_and_non_recordable_close_branches(self, api):
        """PRD section 3.5: "Those same three severities are exactly the
        recordable ones: the computed `recordable` flag is true for them and
        false for the rest." and "A `FATALITY` incident's
        `osha_notification_deadline` falls eight hours after occurrence; a
        `LOST_TIME` incident's falls twenty-four hours after" and "the report's
        `retention_class` also flips to `CLAIMS_HOLD`, a sticky classification
        that survives the incident's later closure."

        Design: Difficulty/non_linear_state_machine/incident_recordable_branching_fork
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        rid, aid = ctx["report"]["id"], ctx["area"]["id"]
        set_clock("2026-08-05T17:00:00Z")

        i1 = add_incident(rid, aid, occurred_at="2026-08-05T09:00:00Z",
                          severity="NEAR_MISS",
                          narrative="Crane load swung over walkway; no contact.")
        i2 = add_incident(rid, aid, occurred_at="2026-08-05T10:00:00Z",
                          severity="LOST_TIME", narrative=_LONG_NARRATIVE)
        assert i1["recordable"] is False
        assert i2["recordable"] is True
        assert_instant_equal(i2["osha_notification_deadline"],
                             "2026-08-06T10:00:00Z",
                             "LOST_TIME deadline is occurred_at + 24h")

        add_media(rid, aid, role="SafetyOfficer", user_id="so-1",
                  captured_at="2026-08-05T10:05:00Z", linked_incident_id=i2["id"])
        validate_success(api.begin_investigation(i1["id"], _SO))
        validate_success(api.notify_osha(i2["id"], _SO))

        closer = make_safety_officer_headers("so-2")
        closed1 = validate_success(api.close_incident(
            i1["id"], {"outcome": "NOT_RECORDABLE"}, closer))
        assert closed1["status"] == "CLOSED_NOT_RECORDABLE"
        closed2 = validate_success(api.close_incident(
            i2["id"], {"outcome": "RECORDABLE"}, closer))
        assert closed2["status"] == "CLOSED_RECORDABLE"

        report = get_report(rid)
        assert report["retention_class"] == "CLAIMS_HOLD", \
            "CLAIMS_HOLD is sticky after the recordable close"
        assert report["distribution_hold"] is False, \
            "no open incidents remain after both closes"
        assert report["has_open_incident"] is False

    @pytest.mark.parametrize("severity,expected_recordable", [
        ("FIRST_AID", False),
        ("NEAR_MISS", False),
        ("PROPERTY_DAMAGE", False),
        ("MEDICAL_TREATMENT", True),
        ("LOST_TIME", True),
        ("FATALITY", True),
    ])
    def test_recordable_flag_by_severity(self, api, severity, expected_recordable):
        """PRD section 3.5: "Those same three severities are exactly the
        recordable ones: the computed `recordable` flag is true for them and
        false for the rest."

        Design: Difficulty/non_linear_state_machine/incident_recordable_branching_fork
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        set_clock("2026-08-05T17:00:00Z")
        narrative = _LONG_NARRATIVE if expected_recordable else "Brief note."
        incident = add_incident(ctx["report"]["id"], ctx["area"]["id"],
                                occurred_at="2026-08-05T09:00:00Z",
                                severity=severity, narrative=narrative)
        assert incident["recordable"] is expected_recordable
        if severity == "FATALITY":
            assert_instant_equal(incident["osha_notification_deadline"],
                                 "2026-08-05T17:00:00Z")
        elif severity == "LOST_TIME":
            assert_instant_equal(incident["osha_notification_deadline"],
                                 "2026-08-06T09:00:00Z")
        else:
            assert incident["osha_notification_deadline"] is None


class TestRecordableCloseDuties:
    def test_close_requires_osha_notification_and_linked_media(self, api):
        """PRD section 3.5: "if a notification deadline exists, notification
        must already have occurred (else `ERR_OSHA_NOTIFICATION_REQUIRED`), and
        at least one `ACTIVE` media attachment must be linked to the incident
        (else `ERR_INCIDENT_MEDIA_REQUIRED`)." Each duty is exercised in
        isolation: the first incident has media but no notification; the second
        has notification but no media.

        Design: Corner/errors/incident_close_requires_media_and_osha
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        rid, aid = ctx["report"]["id"], ctx["area"]["id"]
        set_clock("2026-08-05T17:00:00Z")
        closer = make_safety_officer_headers("so-2")

        # Duty 1 isolated: media linked, notification missing.
        i1 = add_incident(rid, aid, occurred_at="2026-08-05T09:00:00Z",
                          severity="LOST_TIME", narrative=_LONG_NARRATIVE)
        add_media(rid, aid, captured_at="2026-08-05T09:05:00Z",
                  linked_incident_id=i1["id"])
        err1 = api.close_incident(i1["id"], {"outcome": "RECORDABLE"}, closer)
        validate_error(err1, ApiErrorId.ERR_OSHA_NOTIFICATION_REQUIRED)
        assert err1.status_code == 409

        # Duty 2 isolated: notification done, media missing.
        i2 = add_incident(rid, aid, occurred_at="2026-08-05T10:00:00Z",
                          severity="LOST_TIME", narrative=_LONG_NARRATIVE)
        validate_success(api.notify_osha(i2["id"], _SO))
        err2 = api.close_incident(i2["id"], {"outcome": "RECORDABLE"}, closer)
        validate_error(err2, ApiErrorId.ERR_INCIDENT_MEDIA_REQUIRED)
        assert err2.status_code == 409

    def test_close_outcome_must_match_recordability(self, api):
        """PRD section 3.5: "the outcome must agree with the computed
        `recordable` flag: a `RECORDABLE` close of a non-recordable incident, or
        the reverse, fails with `ERR_INCIDENT_RECORDABLE_MISMATCH`." The
        FIRST_AID incident carries linked media so the linked-media duty is
        satisfied and only the mismatch rule can fail.

        Design: Corner/errors/incident_recordable_mismatch_both_directions
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        rid, aid = ctx["report"]["id"], ctx["area"]["id"]
        set_clock("2026-08-05T17:00:00Z")
        closer = make_safety_officer_headers("so-2")

        i1 = add_incident(rid, aid, occurred_at="2026-08-05T09:00:00Z",
                          severity="FIRST_AID", narrative="Minor scrape.")
        add_media(rid, aid, captured_at="2026-08-05T09:05:00Z",
                  linked_incident_id=i1["id"])
        err1 = api.close_incident(i1["id"], {"outcome": "RECORDABLE"}, closer)
        validate_error(err1, ApiErrorId.ERR_INCIDENT_RECORDABLE_MISMATCH)
        assert err1.status_code == 422

        i2 = add_incident(rid, aid, occurred_at="2026-08-05T10:00:00Z",
                          severity="MEDICAL_TREATMENT", narrative=_LONG_NARRATIVE)
        err2 = api.close_incident(i2["id"], {"outcome": "NOT_RECORDABLE"}, closer)
        validate_error(err2, ApiErrorId.ERR_INCIDENT_RECORDABLE_MISMATCH)
        assert err2.status_code == 422

    def test_notify_osha_on_non_recordable_rejected(self, api):
        """PRD section 3.5: "a transition reserved for recordable incidents, so
        notifying on a non-recordable incident fails with
        `ERR_OSHA_NOT_APPLICABLE`".

        Design: Corner/errors/notify_osha_on_non_recordable_rejected
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        set_clock("2026-08-05T17:00:00Z")
        incident = add_incident(ctx["report"]["id"], ctx["area"]["id"],
                                occurred_at="2026-08-05T09:00:00Z",
                                severity="NEAR_MISS", narrative="Load swung wide.")
        assert incident["recordable"] is False

        resp = api.notify_osha(incident["id"], _SO)
        validate_error(resp, ApiErrorId.ERR_OSHA_NOT_APPLICABLE)
        assert resp.status_code == 409


class TestOshaDeadline:
    def test_notification_overdue_strictly_after_deadline(self, api):
        """PRD section 3.5: "The computed `notification_overdue` flag is true
        only when the incident is recordable, a deadline exists,
        `osha_notified_at` is still null, and the logical clock reads strictly
        later than the deadline — at the deadline instant exactly, the incident
        is not yet overdue. The flag recomputes whenever the logical clock is
        set."

        Design: Corner/calculations/osha_deadline_overdue_strictly_greater
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        rid, aid = ctx["report"]["id"], ctx["area"]["id"]
        set_clock("2026-08-05T14:00:00Z")

        incident = add_incident(rid, aid, occurred_at="2026-08-05T06:00:00Z",
                                severity="FATALITY",
                                narrative="Worker struck by reversing haul truck "
                                          "at the north gate area.")
        assert_instant_equal(incident["osha_notification_deadline"],
                             "2026-08-05T14:00:00Z",
                             "FATALITY deadline is occurred_at + 8h")

        at_deadline = get_incident(incident["id"])
        assert at_deadline["notification_overdue"] is False, \
            "at the deadline instant exactly, the incident is not yet overdue"

        set_clock("2026-08-05T14:00:01Z")
        past_deadline = get_incident(incident["id"])
        assert past_deadline["notification_overdue"] is True


class TestValidationOrderSafetyBeforeTemporal:
    def test_thin_narrative_reported_before_future_occurrence(self, api):
        """PRD section 2.9: "checks execute in a fixed order, and the first
        failing check produces the error response." Safety rules sit in layer 7
        ("thin incident narratives (`ERR_INCIDENT_NARRATIVE_REQUIRED`)") ahead
        of temporal rules in layer 9 ("incidents dated in the future
        (`ERR_INCIDENT_OCCURRED_IN_FUTURE`)"), so a FATALITY incident that is
        both thin and future-dated reports the narrative failure.

        Design: Difficulty/priority_pair_validation_conflict/incident_create_safety_beats_temporal
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        set_clock("2026-08-05T17:00:00Z")

        resp = api.create_incident(
            create_incident_payload(
                ctx["report"]["id"], ctx["area"]["id"],
                occurred_at="2026-08-06T09:00:00Z", severity="FATALITY",
                narrative="short"),
            _SO)
        validate_error(resp, ApiErrorId.ERR_INCIDENT_NARRATIVE_REQUIRED)
        assert resp.status_code == 422

        rows = api.list_incidents(_SO, params={"report_id": ctx["report"]["id"]})
        assert rows.json()["meta"]["total_count"] == 0, "no incident row created"

    def test_each_rule_fires_in_isolation(self, api):
        """PRD section 3.5: "When severity is `MEDICAL_TREATMENT`, `LOST_TIME`,
        or `FATALITY`, the narrative must run to at least fifty characters —
        thinner accounts are rejected with `ERR_INCIDENT_NARRATIVE_REQUIRED`."
        and "the `occurred_at` instant — which must not lie in the future of the
        logical clock, else `ERR_INCIDENT_OCCURRED_IN_FUTURE`".

        Design: Difficulty/priority_pair_validation_conflict/incident_create_safety_beats_temporal
        """
        ctx = make_report_bundle(with_weather=False, with_crew=False)
        rid, aid = ctx["report"]["id"], ctx["area"]["id"]
        set_clock("2026-08-05T17:00:00Z")

        thin_only = api.create_incident(
            create_incident_payload(rid, aid, occurred_at="2026-08-05T09:00:00Z",
                                    severity="FATALITY", narrative="short"),
            _SO)
        validate_error(thin_only, ApiErrorId.ERR_INCIDENT_NARRATIVE_REQUIRED)

        future_only = api.create_incident(
            create_incident_payload(rid, aid, occurred_at="2026-08-06T09:00:00Z",
                                    severity="FATALITY", narrative=_LONG_NARRATIVE),
            _SO)
        validate_error(future_only, ApiErrorId.ERR_INCIDENT_OCCURRED_IN_FUTURE)
        assert future_only.status_code == 422


class TestLogicalClock:
    def test_clock_default_and_set(self, api):
        """PRD section 2.5: "At server startup the logical clock reads exactly
        2026-08-01T00:00:00Z, and it advances only when explicitly set. A
        `SystemAdmin`-only test-driving capability sets the clock to a supplied
        `to_iso8601` instant and answers with the resulting `current_utc`".
        PRD section 3.5: "the `occurred_at` instant — which must not lie in the
        future of the logical clock, else `ERR_INCIDENT_OCCURRED_IN_FUTURE`".

        Design: Corner/endpoints/clock_default_and_set
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        report = make_report(project["id"], report_date="2026-08-01")

        at_now = add_incident(report["id"], area["id"],
                              occurred_at="2026-08-01T00:00:00Z",
                              severity="FIRST_AID", narrative="ok")
        assert at_now["id"], "occurred_at equal to the default clock is not future"

        future = api.create_incident(
            create_incident_payload(report["id"], area["id"],
                                    occurred_at="2026-08-01T00:00:01Z",
                                    severity="FIRST_AID",
                                    narrative="future by 1s"),
            _SO)
        validate_error(future, ApiErrorId.ERR_INCIDENT_OCCURRED_IN_FUTURE)
        assert future.status_code == 422

        clock = set_clock("2026-08-01T00:00:01Z")
        assert_instant_equal(clock["current_utc"], "2026-08-01T00:00:01Z")

        after_set = add_incident(report["id"], area["id"],
                                 occurred_at="2026-08-01T00:00:01Z",
                                 severity="FIRST_AID", narrative="now allowed")
        assert after_set["id"]
