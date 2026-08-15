"""SLA due timestamps, strict-greater breach comparisons, and the two report bases."""
from test_helpers import (
    TEST_USERS,
    assert_instant_equals,
    complete_as_technician,
    create_work_order,
    dispatch_in_house,
    set_clock,
    setup_property_resident_technician,
    sign_off,
    start_as_technician,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _metric_row(report: dict, priority: str) -> dict:
    rows = [m for m in report["metrics"] if m.get("priority") == priority]
    assert len(rows) == 1, f"expected exactly one {priority} row, got {report['metrics']!r}"
    return rows[0]


def _pct(value) -> float:
    return float(value)


class TestSlaDueTimestamps:
    def test_due_timestamps_computed_at_creation(self, api):
        """PRD §3.2: "The system snapshots the resident's current `unit_number` onto the work order so later unit reassignments do not rewrite history, initializes `recall_count` to 0 and `resident_signoff` to false, and computes the two SLA due timestamps: `response_due_at` is the work order's `created_at` plus the property's response-hours value for the chosen priority, and `completion_due_at` is `created_at` plus the property's completion-hours value for that priority."
        PRD §3.1: "The SLA configuration is expressed as six hour-valued fields: `emergency_response_hours` defaults to 4, `emergency_completion_hours` defaults to 24, `urgent_response_hours` defaults to 24, `urgent_completion_hours` defaults to 72, `routine_response_hours` defaults to 72, and `routine_completion_hours` defaults to 168."
        PRD §2.4: "On server boot the logical clock starts at the fixed default `2026-08-01T00:00:00Z`; it does not read wall-clock time and must not fall back to it."

        Design: Corner/calculations/sla_due_timestamps_computed_at_creation
        """
        bundle = setup_property_resident_technician("Due Property", unit_number="301")
        wo = create_work_order(
            bundle["property"]["id"], bundle["resident"]["id"],
            category="PLUMBING", priority="ROUTINE", description="Slow drip",
        )
        # Created at the boot clock 2026-08-01T00:00:00Z; ROUTINE is +72h / +168h.
        assert_instant_equals(wo["response_due_at"], "2026-08-04T00:00:00Z", "response_due_at")
        assert_instant_equals(
            wo["completion_due_at"], "2026-08-08T00:00:00Z", "completion_due_at"
        )


class TestResponseSlaBreachBoundary:
    def test_response_breach_is_strictly_greater(self, api):
        """PRD §3.2: "Both breach flags use a strictly-greater comparison — landing exactly on the due timestamp is compliant."
        PRD §3.3: "The first dispatch of a work order also stamps `first_responded_at` with the current logical clock and immediately recomputes `response_sla_breached` as whether that stamp is strictly later than `response_due_at`."

        Design: Corner/calculations/response_sla_breach_strict_greater_boundary
        """
        bundle = setup_property_resident_technician("Breach Property", unit_number="302")
        prop_id = bundle["property"]["id"]
        res_id = bundle["resident"]["id"]
        tech_id = bundle["technician"]["id"]
        # Both orders are created at the boot clock; ROUTINE response due is +72h,
        # i.e. 2026-08-04T00:00:00Z.
        wo_a = create_work_order(prop_id, res_id, description="Job A")
        wo_b = create_work_order(prop_id, res_id, description="Job B")

        # Dispatch A with the clock sitting exactly on the due timestamp.
        set_clock("2026-08-04T00:00:00Z")
        resp_a = dispatch_in_house(
            wo_a["id"], tech_id,
            scheduled_start_at="2026-08-04T10:00:00Z",
            scheduled_end_at="2026-08-04T11:00:00Z",
        )
        assert resp_a["response_sla_breached"] is False, "equality is not a breach"

        # One second past the due timestamp the same dispatch breaches.
        set_clock("2026-08-04T00:00:01Z")
        resp_b = dispatch_in_house(
            wo_b["id"], tech_id,
            scheduled_start_at="2026-08-04T12:00:00Z",
            scheduled_end_at="2026-08-04T13:00:00Z",
        )
        assert resp_b["response_sla_breached"] is True


class TestSlaReportBases:
    def _setup_report_scenario(self, api):
        """One compliant COMPLETED ROUTINE order (A) and one never-dispatched
        ROUTINE order (B) that is past both of its due timestamps at report time."""
        bundle = setup_property_resident_technician("SLA Property", unit_number="101")
        prop_id = bundle["property"]["id"]
        res_id = bundle["resident"]["id"]
        tech_id = bundle["technician"]["id"]

        # Work order A: created at the boot clock 2026-08-01, responded at once,
        # completed 2026-08-02 — inside both ROUTINE deadlines (08-04 / 08-08).
        wo_a = create_work_order(prop_id, res_id, description="Leak A")
        dispatch_in_house(wo_a["id"], tech_id,
                          scheduled_start_at="2026-08-01T10:00:00Z",
                          scheduled_end_at="2026-08-01T12:00:00Z")
        start_as_technician(wo_a["id"], tech_id)
        sign_off(wo_a["id"], res_id)
        set_clock("2026-08-02T00:00:00Z")
        complete_as_technician(wo_a["id"], tech_id,
                               photo_urls=["https://x/a1.jpg"], damage_reported=False)

        # Work order B: created 2026-08-02 (due 08-05 / 08-09) and never dispatched.
        wo_b = create_work_order(prop_id, res_id, description="Leak B")

        # At report time the clock is past both of B's deadlines.
        set_clock("2026-08-11T00:00:00Z")
        return bundle, wo_a, wo_b

    def test_closed_only_basis_excludes_open_orders(self, api):
        """PRD §3.10: "Under `CLOSED_ONLY`, only work orders in `COMPLETED` or `CLOSED` status are eligible; open work is excluded entirely."
        PRD §3.10: "Each row reports `response_compliance_pct` and `completion_compliance_pct`, each computed as one hundred times the number of compliant work orders divided by the number eligible, rounded half-up to two decimal places. When a priority has no eligible work orders at all, both percentages report as 100.00."

        Design: Difficulty/dual_variant_calc/sla_report_open_inclusive_vs_closed_only
        """
        bundle, _, _ = self._setup_report_scenario(api)
        report = validate_success(
            api.get_sla_report(
                bundle["property"]["id"],
                MANAGER,
                params={
                    "window_start": "2026-08-01T00:00:00Z",
                    "window_end": "2026-08-12T00:00:00Z",
                    "basis": "CLOSED_ONLY",
                },
            ),
            200,
        )
        routine = _metric_row(report, "ROUTINE")
        # Only work order A is eligible under CLOSED_ONLY; it is compliant on both.
        assert abs(_pct(routine["response_compliance_pct"]) - 100.00) < 0.005
        assert abs(_pct(routine["completion_compliance_pct"]) - 100.00) < 0.005
        # Priorities with no eligible work orders report 100.00.
        for priority in ("EMERGENCY", "URGENT"):
            row = _metric_row(report, priority)
            assert abs(_pct(row["response_compliance_pct"]) - 100.00) < 0.005
            assert abs(_pct(row["completion_compliance_pct"]) - 100.00) < 0.005

    def test_open_inclusive_basis_counts_breached_open_orders(self, api):
        """PRD §3.10: "Under `OPEN_INCLUSIVE`, work orders in `TRIAGED`, `ASSIGNED`, `IN_PROGRESS`, or `REOPENED` status also enter the denominator."
        PRD §3.10: "For an open work order under the inclusive basis, each dimension is evaluated live against the logical clock: it is response-compliant when its `first_responded_at` is set and not later than `response_due_at`, or — if never yet dispatched — when the current time has not passed `response_due_at`; and completion-compliant when its `completed_at` is set and not later than `completion_due_at`, or — if not yet completed — when the current time has not passed `completion_due_at`."

        Design: Difficulty/dual_variant_calc/sla_report_open_inclusive_vs_closed_only
        """
        bundle, _, _ = self._setup_report_scenario(api)
        report = validate_success(
            api.get_sla_report(
                bundle["property"]["id"],
                MANAGER,
                params={
                    "window_start": "2026-08-01T00:00:00Z",
                    "window_end": "2026-08-12T00:00:00Z",
                    "basis": "OPEN_INCLUSIVE",
                },
            ),
            200,
        )
        routine = _metric_row(report, "ROUTINE")
        # A compliant + B past both deadlines and never dispatched => 1 of 2 compliant.
        assert abs(_pct(routine["response_compliance_pct"]) - 50.00) < 0.005
        assert abs(_pct(routine["completion_compliance_pct"]) - 50.00) < 0.005

        # The two bases disagree on the identical underlying data (100.00 vs 50.00).
        closed = validate_success(
            api.get_sla_report(
                bundle["property"]["id"],
                MANAGER,
                params={
                    "window_start": "2026-08-01T00:00:00Z",
                    "window_end": "2026-08-12T00:00:00Z",
                    "basis": "CLOSED_ONLY",
                },
            ),
            200,
        )
        closed_routine = _metric_row(closed, "ROUTINE")
        assert abs(_pct(closed_routine["response_compliance_pct"]) - 100.00) < 0.005
        assert (
            _pct(closed_routine["response_compliance_pct"])
            != _pct(routine["response_compliance_pct"])
        )
