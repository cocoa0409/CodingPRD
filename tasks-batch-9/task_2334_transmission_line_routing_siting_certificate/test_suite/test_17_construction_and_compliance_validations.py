"""Rules that guard construction scheduling, starts, completion and closeout.

Compliance posture, not certificate status, is what gates work in the field,
and the two compliance indices part company the moment a finding is corrected.
"""

from test_helpers import (
    ApiErrorId,
    assert_is_null,
    assert_score,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


BLACKOUT_WINDOW_START = "2027-05-01T00:00:00Z"
BLACKOUT_WINDOW_END = "2027-05-10T00:00:00Z"


def _activity_count(api, certificate_id):
    _, meta = validate_paginated(
        api.list_construction_activities(
            fx.DEVELOPER_HEADERS, {"certificate_id": certificate_id}
        )
    )
    return meta["total_count"]


class TestSeasonalBlackout:
    """The restriction is keyed on the segment flag, not on the calendar alone."""

    def test_a_may_window_on_the_habitat_segment_is_refused(self, api):
        """PRD §3.9: "Then the seasonal restriction: if the segment's
        `habitat_blackout` flag is set and the activity's window touches any calendar
        day inside the inclusive month-day range of an `ACTIVE` `SEASONAL_BLACKOUT`
        condition on that certificate, the activity is refused with
        `ERR_SEASONAL_BLACKOUT_VIOLATION` (HTTP 422)."

        Design: Corner/validations/activity_inside_the_seasonal_blackout_rejected
        """
        ctx = fx.setup_issued_certificate(api)

        response = api.create_construction_activity(
            f.construction_activity_payload(
                ctx["cert"], ctx["seg1"], activity_kind="CLEARING", crew_count=6,
                window_start_at=BLACKOUT_WINDOW_START,
                window_end_at=BLACKOUT_WINDOW_END,
            ),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(
            response, ApiErrorId.SEASONAL_BLACKOUT_VIOLATION, expected_status=422
        )

        assert _activity_count(api, ctx["cert"]) == 0, (
            "The refused window writes no activity row"
        )
        segment = fx.read_segment(api, ctx["seg1"])
        assert segment["committed_crew_count"] == 0, (
            f"No crew was committed, got {segment['committed_crew_count']}"
        )
        assert segment["construction_state"] == "PENDING", (
            f"The segment never opened for work, got {segment['construction_state']}"
        )
        assert fx.read_condition(api, ctx["cond1"])["status"] == "ACTIVE", (
            "The blackout condition is still active, which is why it bit"
        )

    def test_the_same_may_window_on_a_segment_without_the_flag_is_accepted(self, api):
        """PRD §3.9: "Conditions that have been `WAIVED` impose no blackout at all,
        and a segment without the habitat flag is never blacked out."

        Design: Corner/validations/blackout_window_on_a_non_habitat_segment_accepted
        """
        ctx = fx.setup_issued_certificate(api)

        activity = validate_success(
            api.create_construction_activity(
                f.construction_activity_payload(
                    ctx["cert"], ctx["seg2"], activity_kind="CLEARING", crew_count=6,
                    window_start_at=BLACKOUT_WINDOW_START,
                    window_end_at=BLACKOUT_WINDOW_END,
                ),
                fx.DEVELOPER_HEADERS,
            ),
            expected_status=201,
        )

        assert activity["status"] == "SCHEDULED", (
            f"Activities open at SCHEDULED, got {activity['status']}"
        )
        assert activity["crew_count"] == 6, (
            f"The declared crew is stored verbatim, got {activity['crew_count']}"
        )
        segment = fx.read_segment(api, ctx["seg2"])
        assert segment["committed_crew_count"] == 6, (
            f"The segment's committed crew grows immediately, got "
            f"{segment['committed_crew_count']}"
        )
        assert segment["construction_state"] == "PENDING", (
            f"Scheduling alone does not open the segment, got "
            f"{segment['construction_state']}"
        )
        assert fx.read_certificate(api, ctx["cert"])["posture"] == "ACTIVE", (
            "The certificate posture is untouched by scheduling"
        )


class TestPostureGates:
    """Posture is the construction gate; status stays ISSUED throughout."""

    def test_no_activity_may_be_scheduled_under_stop_work(self, api):
        """PRD §3.9: "The certificate's posture must be `ACTIVE`, or the request is
        refused with `ERR_CERTIFICATE_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/validations/activity_creation_under_stop_work_rejected
        """
        ctx = fx.setup_issued_certificate(api)
        finding = fx.file_finding(api, ctx, key="ncr1", condition_key="cond1",
                                  severity="SEVERE")

        response = api.create_construction_activity(
            f.construction_activity_payload(
                ctx["cert"], ctx["seg2"], activity_kind="STRINGING", crew_count=5,
                window_start_at="2027-08-02T00:00:00Z",
                window_end_at="2027-08-12T00:00:00Z",
            ),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.CERTIFICATE_NOT_ACTIVE, expected_status=409)

        assert_score(finding["deduction_points"], 48.00, "deduction_points")
        certificate = fx.read_certificate(api, ctx["cert"])
        assert_score(
            certificate["compliance_index_rolling"], 52.00, "compliance_index_rolling"
        )
        assert_score(
            certificate["compliance_index_cumulative"], 52.00,
            "compliance_index_cumulative",
        )
        assert certificate["posture"] == "STOP_WORK", (
            f"52.00 is below the 60.00 rolling floor, got {certificate['posture']}"
        )
        assert certificate["status"] == "ISSUED", (
            f"Posture moved but status did not, got {certificate['status']}"
        )
        assert _activity_count(api, ctx["cert"]) == 0, (
            "No activity row survives the posture gate"
        )

    def test_a_condition_on_a_revoked_certificate_cannot_be_waived(self, api):
        """PRD §3.7: "a waiver against a revoked certificate is refused with
        `ERR_CERTIFICATE_REVOKED` (HTTP 409), and a waiver against a certificate whose
        posture is not `ACTIVE` is refused with `ERR_CERTIFICATE_NOT_ACTIVE` (HTTP
        409)."

        Design: Corner/validations/waiver_on_a_revoked_certificate_rejected
        """
        ctx = fx.setup_revoked_certificate(api)

        response = api.waive_certificate_condition(
            ctx["cond2"],
            f.waiver_payload(
                waiver_reason=(
                    "Monitoring folded into the environmental inspector scope"
                )
            ),
            fx.COMMISSION_STAFF_HEADERS,
        )
        validate_error(response, ApiErrorId.CERTIFICATE_REVOKED, expected_status=409)

        second_finding = fx.read_finding(api, ctx["ncr_sev2"])
        assert_score(second_finding["deduction_points"], 48.00, "deduction_points")
        certificate = fx.read_certificate(api, ctx["cert"])
        assert_score(
            certificate["compliance_index_cumulative"], 4.00,
            "compliance_index_cumulative",
        )
        assert_score(
            certificate["compliance_index_rolling"], 4.00, "compliance_index_rolling"
        )
        assert certificate["posture"] == "REVOKED", (
            f"4.00 is below the 25.00 cumulative floor, got {certificate['posture']}"
        )
        assert fx.read_condition(api, ctx["cond2"])["status"] == "ACTIVE", (
            "The monitoring condition was never waived"
        )


class TestStartAndCompletionGates:
    """The fiscal gate at start, and the open-finding gate at completion."""

    def test_a_start_on_an_underfunded_escrow_is_refused(self, api):
        """PRD §3.9: "And the project's `escrow_funded_cents` must be at least the
        certificate's `escrow_required_cents`, or the start is refused with
        `ERR_ESCROW_UNDERFUNDED` (HTTP 402)."

        Design: Corner/validations/activity_start_with_underfunded_escrow_rejected
        """
        ctx = fx.setup_issued_certificate(api)
        fx.setup_agreed_tract(api, ctx)
        fx.fund_escrow(api, ctx, amount_cents=100_000_000, reference="ESCROW-PARTIAL")
        fx.schedule_activity(
            api, ctx, key="act1", segment_key="seg1", activity_kind="CLEARING",
            crew_count=6, window_start_at="2027-08-02T00:00:00Z",
            window_end_at="2027-08-12T00:00:00Z",
        )
        fx.set_clock(api, "2027-08-02T00:00:00Z")

        response = api.start_activity(
            ctx["act1"], f.activity_start_payload(start_note="Mobilizing"),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.ESCROW_UNDERFUNDED, expected_status=402)

        assert fx.read_certificate(api, ctx["cert"])["escrow_required_cents"] == 533_000_000, (
            "The order's frozen escrow requirement is what the start is measured against"
        )
        project = fx.read_project(api, ctx)
        assert project["escrow_funded_cents"] == 100_000_000, (
            f"Only the partial deposit was funded, got "
            f"{project['escrow_funded_cents']}"
        )
        assert project["stage"] == "CERTIFICATED", (
            f"No activity started, so the project stays CERTIFICATED, got "
            f"{project['stage']}"
        )
        activity = fx.read_activity(api, ctx["act1"])
        assert activity["status"] == "SCHEDULED", (
            f"The refused start leaves the activity SCHEDULED, got {activity['status']}"
        )
        assert_is_null(activity, "started_at", "ConstructionActivity")
        assert fx.read_segment(api, ctx["seg1"])["construction_state"] == "PENDING", (
            "The segment never opened for work"
        )

    def test_completion_is_refused_while_a_finding_on_the_activity_is_open(self, api):
        """PRD §3.9: "It is refused with `ERR_OPEN_NONCONFORMANCE` (HTTP 409) while
        any nonconformance referencing that activity is still `OPEN`."

        Design: Corner/validations/activity_completion_with_an_open_finding_rejected
        """
        ctx = fx.setup_construction_ready(api)
        fx.setup_started_activity(api, ctx, key="act1", crew_count=6)
        finding = fx.file_finding(
            api, ctx, key="ncr_min", condition_key="cond2", severity="MINOR",
            observation="Cultural monitor absent for one shift",
            activity_id=ctx["act1"],
        )

        response = api.complete_activity(
            ctx["act1"],
            f.activity_completion_payload(completion_note="Clearing finished"),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.OPEN_NONCONFORMANCE, expected_status=409)

        assert_score(finding["deduction_points"], 4.80, "deduction_points")
        certificate = fx.read_certificate(api, ctx["cert"])
        assert_score(
            certificate["compliance_index_rolling"], 95.20, "compliance_index_rolling"
        )
        assert_score(
            certificate["compliance_index_cumulative"], 95.20,
            "compliance_index_cumulative",
        )
        assert certificate["posture"] == "ACTIVE", (
            f"95.20 clears both floors, so posture is not the reason, got "
            f"{certificate['posture']}"
        )
        activity = fx.read_activity(api, ctx["act1"])
        assert activity["status"] == "IN_PROGRESS", (
            f"The refused completion leaves the activity running, got "
            f"{activity['status']}"
        )
        assert_is_null(activity, "completed_at", "ConstructionActivity")
        segment = fx.read_segment(api, ctx["seg1"])
        assert segment["committed_crew_count"] == 6, (
            f"The crew is not released by a refused completion, got "
            f"{segment['committed_crew_count']}"
        )
        assert segment["construction_state"] == "ACTIVE", (
            f"The segment is still open for work, got {segment['construction_state']}"
        )
        assert fx.read_project(api, ctx)["stage"] == "CONSTRUCTION", (
            "The first start carried the project into CONSTRUCTION"
        )


class TestCloseoutFloor:
    """A correction restores half the rolling index and nothing cumulative."""

    def test_closeout_below_the_cumulative_floor_is_refused(self, api):
        """PRD §3.9: "Its four gates fire in this order: the certificate's posture
        must be `ACTIVE` (`ERR_CERTIFICATE_NOT_ACTIVE`, HTTP 409);
        `compliance_index_cumulative` must be at least 75.00
        (`ERR_COMPLIANCE_TOO_LOW`, HTTP 422)."

        Design: Corner/validations/closeout_below_the_cumulative_floor_rejected
        """
        ctx = fx.setup_issued_certificate(api)
        fx.file_finding(api, ctx, key="ncr1", condition_key="cond1", severity="SEVERE")
        fx.correct_finding(
            api, ctx, key="ncr1",
            note="Habitat restoration completed and monitor sign-off obtained",
        )

        response = api.close_out_certificate(
            ctx["cert"], f.closeout_payload(closeout_note="Requesting release"),
            fx.COMMISSION_STAFF_HEADERS,
        )
        validate_error(response, ApiErrorId.COMPLIANCE_TOO_LOW, expected_status=422)

        assert fx.read_finding(api, ctx["ncr1"])["status"] == "CORRECTED", (
            "The finding was corrected, which is what lifted the posture"
        )
        certificate = fx.read_certificate(api, ctx["cert"])
        assert_score(
            certificate["compliance_index_rolling"], 76.00, "compliance_index_rolling"
        )
        assert_score(
            certificate["compliance_index_cumulative"], 52.00,
            "compliance_index_cumulative",
        )
        assert certificate["posture"] == "ACTIVE", (
            f"76.00 clears the 60.00 rolling floor, so the posture gate passes, got "
            f"{certificate['posture']}"
        )
        assert certificate["status"] == "ISSUED", (
            f"The refused closeout leaves the certificate ISSUED, got "
            f"{certificate['status']}"
        )
        assert fx.read_condition(api, ctx["cond1"])["status"] == "ACTIVE", (
            "The correction was the last open finding on the condition, so it returned "
            "to ACTIVE"
        )
        assert fx.read_project(api, ctx)["stage"] == "CERTIFICATED", (
            "The project cannot reach ENERGIZED without a closeout"
        )
