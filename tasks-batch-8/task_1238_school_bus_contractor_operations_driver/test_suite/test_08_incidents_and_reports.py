"""Incidents (SLA deadlines, discipline context, district scoping) and the
computed district daily report (ridership punctuality tiers)."""
from test_helpers import (
    ApiErrorId,
    build_service_day,
    confirm_assignment,
    create_active_contract,
    create_district,
    create_incident,
    create_ridership_report,
    create_route,
    create_submitted_incident,
    get_success_data,
    make_district_admin_headers,
    run_assignment,
    set_clock,
    setup_ops_scenario,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import OPS


class TestIncidentSlaStrictThreshold:
    def _setup_two_critical_incidents(self, api):
        district = create_district(name="D-BND3")
        set_clock("2026-06-01T08:00:00Z")
        first = create_submitted_incident(
            district["id"], category="ACCIDENT", severity="CRITICAL",
            description="Minor collision, no injuries",
            occurred_at="2026-06-01T07:30:00Z")
        second = create_submitted_incident(
            district["id"], category="MEDICAL", severity="CRITICAL",
            description="Student medical event",
            occurred_at="2026-06-01T07:45:00Z")
        return district, first, second

    def test_acknowledge_exactly_at_deadline_is_not_a_breach(self, api):
        """PRD section 3.8: "Submitting from `DRAFT` — or resubmitting from
        `RETURNED_FOR_INFO`, the cyclic loop — moves the incident to `SUBMITTED`,
        stamps `submitted_at` from the logical clock, and sets the SLA deadline
        `district_due_by` from severity: 24 hours for `CRITICAL`, 72 hours for
        `HIGH`, and 168 hours for anything else; resubmission recomputes both
        timestamps afresh."
        PRD section 3.8: "Acknowledgement evaluates the SLA: `sla_breached` is
        true exactly when `acknowledged_at` is strictly later than
        `district_due_by`; an acknowledgement landing exactly at the deadline is
        not a breach."

        Design: Difficulty/boundary_precision_check/incident_sla_strict_breach_threshold
        """
        district, first, _second = self._setup_two_critical_incidents(api)
        assert first["district_due_by"] == "2026-06-02T08:00:00Z", (
            "submitted 2026-06-01T08:00:00Z + 24h CRITICAL window")

        set_clock("2026-06-02T08:00:00Z")
        acknowledged = get_success_data(api.acknowledge_incident(
            first["id"], make_district_admin_headers(district["id"])))
        assert acknowledged["status"] == "ACKNOWLEDGED"
        assert acknowledged["sla_breached"] is False, (
            "exactly at the deadline: strict > means no breach")

    def test_acknowledge_one_second_late_breaches(self, api):
        """PRD section 3.8: "Acknowledgement evaluates the SLA: `sla_breached`
        is true exactly when `acknowledged_at` is strictly later than
        `district_due_by`; an acknowledgement landing exactly at the deadline is
        not a breach."
        PRD section 3.8: "sets the SLA deadline `district_due_by` from severity:
        24 hours for `CRITICAL`, 72 hours for `HIGH`, and 168 hours for anything
        else"

        Design: Difficulty/boundary_precision_check/incident_sla_strict_breach_threshold
        """
        district, _first, second = self._setup_two_critical_incidents(api)
        set_clock("2026-06-02T08:00:01Z")
        acknowledged = get_success_data(api.acknowledge_incident(
            second["id"], make_district_admin_headers(district["id"])))
        assert acknowledged["status"] == "ACKNOWLEDGED"
        assert acknowledged["sla_breached"] is True, (
            "one second past the 24h deadline breaches")


class TestIncidentCreationRules:
    def test_error_discipline_context_required_returns_422(self, api):
        """PRD section 3.8: "When the discipline flag is true, submission
        additionally requires both `route_id` and `service_day_id` to be
        present, else `ERR_DISCIPLINE_CONTEXT_REQUIRED` (HTTP 422)."

        Design: Corner/errors/error_discipline_context_required_returns_422
        """
        district = create_district(name="D-ERR5")
        incident = create_incident(
            district["id"], category="BEHAVIOR", severity="HIGH",
            description="Student fight", occurred_at="2026-04-30T15:00:00Z",
            student_discipline_flag=True)

        resp = api.submit_incident(incident["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_DISCIPLINE_CONTEXT_REQUIRED, 422)
        fetched = validate_success(api.get_incident(incident["id"], OPS))
        assert fetched["status"] == "DRAFT"

    def test_error_future_incident_returns_422(self, api):
        """PRD section 3.8: "a narrative `description`, and an `occurred_at`
        instant that must not lie in the future relative to the logical clock
        (else `ERR_FUTURE_INCIDENT`, HTTP 422)."
        PRD section 2.5: "At server startup the clock is exactly
        `2026-05-01T00:00:00Z`; it never falls back to wall-clock time."

        Design: Corner/errors/error_future_incident_returns_422
        """
        district = create_district(name="D-ERR11")
        resp = api.create_incident(
            {"district_id": district["id"], "category": "MECHANICAL",
             "severity": "LOW", "description": "Future-dated",
             "occurred_at": "2026-05-02T00:00:00Z"},
            OPS)
        validate_error(resp, ApiErrorId.ERR_FUTURE_INCIDENT, 422)

    def test_error_cross_district_reference_on_incident_returns_422(self, api):
        """PRD section 3.8: "Optional context attaches a `route_id`, an involved
        `driver_id`, a `service_day_id`, and a `student_discipline_flag`
        defaulting to false; any route or service day referenced must belong to
        the incident's own district, else `ERR_CROSS_DISTRICT_REFERENCE`
        (HTTP 422)."

        Design: Corner/errors/error_cross_district_reference_on_incident_returns_422
        """
        district_a = create_district(name="D-ERR15A")
        district_b = create_district(name="D-ERR15B")
        contract_b = create_active_contract(district_b["id"], bid_reference="BID-E15")
        route_b = create_route(contract_b["id"], route_code="RB")

        resp = api.create_incident(
            {"district_id": district_a["id"], "category": "BEHAVIOR",
             "severity": "LOW", "description": "Wrong district route",
             "occurred_at": "2026-04-30T15:00:00Z", "route_id": route_b["id"]},
            OPS)
        validate_error(resp, ApiErrorId.ERR_CROSS_DISTRICT_REFERENCE, 422)


class TestRidershipReports:
    def _setup_completed_day(self, api):
        ctx = setup_ops_scenario(district_name="D-ERR16")
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        confirm_assignment(assignments[0]["id"], ctx["driver"]["id"], ctx["bus"]["id"])
        run_assignment(assignments[0]["id"], ctx["driver"]["id"], 420, 480, 60)
        return ctx, day, assignments[0]

    def test_error_duplicate_ridership_report_triggerable(self, api):
        """PRD section 3.8: "Ridership telemetry arrives one report per
        assignment. A `Driver` or `ContractorOps` submits a RidershipReport for
        a `COMPLETED` assignment, carrying the `assignment_id`, the denormalized
        `service_day_id`, the `boardings` and `alightings` counts, and the
        GPS-derived `first_pickup_actual_minute` and `last_dropoff_actual_minute`;
        a second report for the same assignment is rejected with
        `ERR_DUPLICATE_RIDERSHIP_REPORT`."

        Design: Corner/errors/error_duplicate_ridership_report_triggerable
        """
        _ctx, day, assignment = self._setup_completed_day(api)
        create_ridership_report(assignment["id"], day["id"], boardings=40,
                                alightings=40, first_pickup_actual_minute=421,
                                last_dropoff_actual_minute=479)

        resp = api.create_ridership_report(
            {"assignment_id": assignment["id"], "service_day_id": day["id"],
             "boardings": 39, "alightings": 39, "first_pickup_actual_minute": 421,
             "last_dropoff_actual_minute": 479},
            OPS)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RIDERSHIP_REPORT, 409)


class TestOnTimePerformanceTiers:
    def test_on_time_performance_tiers(self, api):
        """PRD section 3.8: "The system derives the punctuality measures:
        `minutes_late` is the larger of zero and the first pickup minute minus
        the assignment's `planned_start_minute` minus a five-minute grace;
        `on_time` is true exactly when `minutes_late` is zero; and
        `student_minutes_late` multiplies `minutes_late` by the `boardings`."
        PRD section 3.8: "On-time performance aggregates over the day's
        `COMPLETED` assignments that have a ridership report: `on_time_pct_x100`
        is the count of on-time reports times ten thousand, divided by the number
        of reports, floored to an integer — the percentage times one hundred —
        and is null when no reports exist. The `on_time_tier` grades the result:
        at least 9500 is `EXCELLENT`, at least 9000 is `SATISFACTORY`, and
        anything below is `DEFICIENT`, with both thresholds inclusive."

        Design: Corner/calculations/on_time_performance_tiers
        """
        ctx = setup_ops_scenario(district_name="D-CALC3",
                                 routes=[(420, 480, 40), (480, 540, 10)])
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        confirm_assignment(assignments[0]["id"], ctx["driver"]["id"], ctx["bus"]["id"])
        confirm_assignment(assignments[1]["id"], ctx["driver"]["id"], ctx["bus"]["id"])
        run_assignment(assignments[0]["id"], ctx["driver"]["id"], 425, 480, 55)
        run_assignment(assignments[1]["id"], ctx["driver"]["id"], 490, 545, 55)

        report1 = create_ridership_report(
            assignments[0]["id"], day["id"], boardings=40, alightings=40,
            first_pickup_actual_minute=425, last_dropoff_actual_minute=478)
        report2 = create_ridership_report(
            assignments[1]["id"], day["id"], boardings=10, alightings=10,
            first_pickup_actual_minute=490, last_dropoff_actual_minute=545)

        # 425 - 420 planned - 5 grace = 0 late -> on time.
        assert report1["minutes_late"] == 0
        assert report1["on_time"] is True
        # 490 - 480 - 5 = 5 minutes late; 5 x 10 boardings.
        assert report2["minutes_late"] == 5
        assert report2["on_time"] is False
        assert report2["student_minutes_late"] == 50

        report = validate_success(api.get_district_report(
            day["id"], make_district_admin_headers(ctx["district"]["id"])))
        assert report["service_day_id"] == day["id"]
        assert report["on_time_pct_x100"] == 5000, "floor(10000 x 1 / 2)"
        assert report["on_time_tier"] == "DEFICIENT", "below 9000"
        assert report["total_boardings"] == 50
        assert report["total_student_minutes_late"] == 50
        assert report["sla_breached_incidents"] == 0
