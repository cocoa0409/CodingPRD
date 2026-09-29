"""One write firing a chain of three or four consequences.

A severe finding reaching a condition, the certificate posture, the activities
and their segments; and a second granted petition reaching the statutory
deadline, the project's schedule posture and its right-of-way hold.
"""

from test_helpers import assert_score, assert_timestamp_equals
from test_helpers import fixtures as fx


class TestSevereFindingCascade:
    """Condition -> certificate posture -> activity -> segment."""

    def test_severe_finding_halts_the_segment_its_activity_was_working(self, api):
        """PRD §3.9: "suspends every activity on that certificate whose status is
        `SCHEDULED` or `IN_PROGRESS` with `suspension_reason` recorded as
        `CERTIFICATE_STOP_WORK`, and moves each affected segment `ACTIVE →
        HALTED` on its construction dimension."

        Design: Difficulty/transitive_cascade/severe_finding_cascades_condition_to_posture_to_activity_to_segment
        """
        ctx = fx.setup_construction_ready(api)
        fx.setup_started_activity(api, ctx)
        fx.file_finding(api, ctx, key="ncr_sev", condition_key="cond1", severity="SEVERE")

        assert fx.read_condition(api, ctx["cond1"])["status"] == "VIOLATED", (
            "The finding's condition moves ACTIVE -> VIOLATED"
        )
        certificate = fx.read_certificate(api, ctx["cert"])
        assert_score(
            certificate["compliance_index_rolling"], 52.00, "compliance_index_rolling"
        )
        assert certificate["posture"] == "STOP_WORK", (
            f"A rolling index of 52.00 forces STOP_WORK, got {certificate['posture']}"
        )
        activity = fx.read_activity(api, ctx["act1"])
        assert activity["status"] == "SUSPENDED", (
            f"The in-progress activity is suspended by the cascade, got "
            f"{activity['status']}"
        )
        assert activity["suspension_reason"] == "CERTIFICATE_STOP_WORK", (
            f"The suspension reason names the certificate stop-work, got "
            f"{activity['suspension_reason']!r}"
        )
        assert fx.read_segment(api, ctx["seg1"])["construction_state"] == "HALTED", (
            "The segment the suspended activity was working moves ACTIVE -> HALTED"
        )
        assert fx.read_segment(api, ctx["seg2"])["construction_state"] == "PENDING", (
            "A segment that was never ACTIVE is untouched by the cascade"
        )
        assert fx.read_project(api, ctx)["stage"] == "CONSTRUCTION", (
            "The cascade halts work without walking the project's stage backwards"
        )

    def test_minor_finding_on_a_light_condition_fires_only_the_first_link(self, api):
        """PRD §3.9: "Posture is derived after **both** indices have been
        refreshed, and in this order: if `compliance_index_cumulative` is
        strictly below 25.00 the posture is `REVOKED`; otherwise, if
        `compliance_index_rolling` is strictly below 60.00 the posture is
        `STOP_WORK`; otherwise it is `ACTIVE`."

        Design: Difficulty/transitive_cascade/severe_finding_cascades_condition_to_posture_to_activity_to_segment
        """
        ctx = fx.setup_construction_ready(api)
        fx.setup_started_activity(api, ctx)
        finding = fx.file_finding(
            api, ctx, key="ncr_min", condition_key="cond2", severity="MINOR",
            observation="Cultural monitor arrived one hour after clearing began",
        )

        assert_score(finding["deduction_points"], 4.80, "deduction_points")
        assert fx.read_condition(api, ctx["cond2"])["status"] == "VIOLATED", (
            "The first link always fires: the named condition is violated"
        )
        certificate = fx.read_certificate(api, ctx["cert"])
        assert_score(
            certificate["compliance_index_rolling"], 95.20, "compliance_index_rolling"
        )
        assert certificate["posture"] == "ACTIVE", (
            "A rolling index of 95.20 is above the 60.00 floor, so posture holds at "
            f"ACTIVE, got {certificate['posture']}"
        )
        activity = fx.read_activity(api, ctx["act1"])
        assert activity["status"] == "IN_PROGRESS", (
            f"With posture unchanged the activity keeps working, got {activity['status']}"
        )
        assert activity.get("suspension_reason") is None, (
            f"No suspension was recorded, got {activity.get('suspension_reason')!r}"
        )
        assert fx.read_segment(api, ctx["seg1"])["construction_state"] == "ACTIVE", (
            "The segment stays ACTIVE because nothing suspended its activity"
        )


class TestSecondInterventionCascade:
    """Petition -> record dimension -> statutory deadline -> project hold."""

    def test_second_grant_lengthens_the_deadline_and_freezes_condemnation(self, api):
        """PRD §3.6: "When a grant brings `party_count` to two or more while the
        record sits at `SCHEDULING`, the record advances `SCHEDULING →
        EVIDENTIARY_REQUIRED`, `suspension_days` is set to 90,
        `decision_deadline_at` is recomputed as the filing instant plus 365 days
        plus those 90 suspension days, and the project's `schedule_posture` and
        `right_of_way_hold` are recomputed from the lengthened deadline."

        Design: Difficulty/transitive_cascade/second_granted_intervention_cascades_deadline_to_right_of_way_hold
        """
        ctx = fx.setup_accepted_application(api)
        fx.setup_two_granted_interventions(api, ctx)

        assert fx.read_intervention(api, ctx["int2"])["status"] == "GRANTED", (
            "The second petition is granted"
        )
        application = fx.read_application(api, ctx["app"])
        assert application["party_count"] == 2, (
            f"Two petitions have been granted, got party_count {application['party_count']}"
        )
        assert application["record_status"] == "EVIDENTIARY_REQUIRED", (
            "The second grant advances the record SCHEDULING -> EVIDENTIARY_REQUIRED, got "
            f"{application['record_status']}"
        )
        assert application["suspension_days"] == 90, (
            f"The statutory suspension is set to 90 days, got "
            f"{application['suspension_days']}"
        )
        assert_timestamp_equals(
            application["decision_deadline_at"], "2027-11-29T00:00:00Z", "decision_deadline_at"
        )
        project = fx.read_project(api, ctx)
        assert project["schedule_posture"] == "AT_RISK", (
            "A 2027-11-29 deadline leaves fewer than 180 days before the 2028-04-01 "
            f"in-service date, got {project['schedule_posture']}"
        )
        assert project["right_of_way_hold"] is True, (
            f"An AT_RISK posture raises the right-of-way hold, got "
            f"{project['right_of_way_hold']}"
        )

    def test_first_grant_alone_fires_none_of_the_downstream_links(self, api):
        """PRD §3.6: "Granting requires the record dimension to be at
        `SCHEDULING`, `EVIDENTIARY_REQUIRED` or `RECORD_OPEN`; it moves the
        petition `PETITIONED → GRANTED` and increments the application's
        `party_count`."

        Design: Difficulty/transitive_cascade/second_granted_intervention_cascades_deadline_to_right_of_way_hold
        """
        ctx = fx.setup_accepted_application(api)
        fx.create_landowner(api, ctx, "lo1")
        fx.petition_to_intervene(api, ctx, "int1", landowner_key="lo1")
        fx.rule_on_petition(api, ctx, "int1", ruling="GRANT")

        application = fx.read_application(api, ctx["app"])
        assert application["party_count"] == 1, (
            f"Only one petition has been granted, got {application['party_count']}"
        )
        assert application["record_status"] == "SCHEDULING", (
            "One party does not require an evidentiary hearing, so the record stays at "
            f"SCHEDULING, got {application['record_status']}"
        )
        assert application["suspension_days"] == 0, (
            f"No statutory suspension attaches to the first grant, got "
            f"{application['suspension_days']}"
        )
        assert_timestamp_equals(
            application["decision_deadline_at"], "2027-08-31T00:00:00Z", "decision_deadline_at"
        )
        project = fx.read_project(api, ctx)
        assert project["schedule_posture"] == "ON_TRACK", (
            "The unlengthened deadline leaves the posture ON_TRACK, got "
            f"{project['schedule_posture']}"
        )
        assert project["right_of_way_hold"] is False, (
            f"An ON_TRACK posture carries no hold, got {project['right_of_way_hold']}"
        )
