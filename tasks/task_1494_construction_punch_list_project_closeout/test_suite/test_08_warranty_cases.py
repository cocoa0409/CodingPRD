"""Warranty callbacks: window boundary, triage SLA math under CALENDAR vs BUSINESS,
and case state-machine rules."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_warranty_case_payload,
    get_project,
    report_warranty_case,
    set_clock,
    setup_closed_project,
    setup_substantially_complete_project,
    validate_error,
    validate_success,
)

PM = TEST_USERS["gc_pm_headers"]
OWNER = TEST_USERS["owner_rep_headers"]


class TestSlaModeVariants:

    def test_major_case_friday_triage_calendar_vs_business(self):
        """PRD §3.7: "A `MAJOR` case triaged on Friday, 4 September 2026 at 10:00 UTC, for example, falls due on 11 September 2026 at 10:00 UTC under `CALENDAR`, but not until 15 September 2026 at 10:00 UTC under `BUSINESS`."
        PRD §3.7: "SLA timestamps are ISO 8601 UTC at second precision."

        Design: Difficulty/dual_variant_calc/warranty_sla_calendar_vs_business_variant
        """
        ctx_a = setup_closed_project(name="Proj A", warranty_sla_mode="CALENDAR")
        ctx_b = setup_closed_project(
            name="Proj B", warranty_sla_mode="BUSINESS",
            walk_start="2026-08-05T10:00:00Z", walk_end="2026-08-05T11:00:00Z",
            walk_complete_at="2026-08-05T11:00:00Z", sc_clock="2026-08-05T11:00:00Z",
            occupancy_date="2026-08-06T00:00:00Z",
            training_start="2026-08-07T09:00:00Z", training_end="2026-08-07T10:00:00Z",
        )
        case_a = report_warranty_case(ctx_a["project"]["id"], title="Lobby door drags")
        case_b = report_warranty_case(ctx_b["project"]["id"], title="Lobby door drags")

        set_clock("2026-09-04T10:00:00Z")  # a Friday
        triaged_a = validate_success(api_client.triage_warranty_case(
            case_a["id"], {"severity": "MAJOR"}, PM,
        ), 200)
        triaged_b = validate_success(api_client.triage_warranty_case(
            case_b["id"], {"severity": "MAJOR"}, PM,
        ), 200)
        assert triaged_a["sla_due_at"] == "2026-09-11T10:00:00Z"  # CALENDAR: +7 days
        assert triaged_b["sla_due_at"] == "2026-09-15T10:00:00Z"  # BUSINESS: skips two weekends
        assert triaged_a["sla_due_at"] != triaged_b["sla_due_at"]

    def test_triage_replaces_severity_and_sets_sla(self):
        """PRD §3.7: "Triage, performed by the `GCProjectManager`, moves the case from `REPORTED` to `TRIAGED`, sets `severity` from the request payload — replacing the value given at report time — and computes `sla_due_at` according to the project's `warranty_sla_mode`."
        PRD §3.7: "The case starts in `REPORTED`, stamps `reported_at` with the logical clock, and leaves `sla_due_at` null until triage."

        Design: Difficulty/dual_variant_calc/warranty_sla_calendar_vs_business_variant
        """
        ctx = setup_closed_project(name="Proj", warranty_sla_mode="CALENDAR")
        case = report_warranty_case(ctx["project"]["id"], title="Door closer weak",
                                    severity="MINOR")
        assert case["status"] == "REPORTED"
        assert case["sla_due_at"] is None

        set_clock("2026-09-04T10:00:00Z")
        triaged = validate_success(api_client.triage_warranty_case(
            case["id"], {"severity": "MAJOR"}, PM,
        ), 200)
        assert triaged["status"] == "TRIAGED"
        assert triaged["severity"] == "MAJOR"
        assert triaged["sla_due_at"] == "2026-09-11T10:00:00Z"


class TestSlaSeverityConstants:

    def test_sla_severity_constants_calendar(self):
        """PRD §3.7: "The response window is one day for `CRITICAL`, seven days for `MAJOR`, and thirty days for `MINOR`."
        PRD §3.7: "Under `CALENDAR` mode the due instant is simply the triage instant plus that many days, with the time of day preserved; weekend days count toward the window."

        Design: Corner/calculations/warranty_sla_severity_constants_calendar
        """
        ctx = setup_closed_project(name="Proj", warranty_sla_mode="CALENDAR")
        critical = report_warranty_case(ctx["project"]["id"], title="Leak",
                                        severity="CRITICAL", description="pipe burst")
        minor = report_warranty_case(ctx["project"]["id"], title="Squeak",
                                     severity="MINOR", description="door squeak")
        set_clock("2026-09-04T10:00:00Z")
        triaged_critical = validate_success(api_client.triage_warranty_case(
            critical["id"], {"severity": "CRITICAL"}, PM,
        ), 200)
        triaged_minor = validate_success(api_client.triage_warranty_case(
            minor["id"], {"severity": "MINOR"}, PM,
        ), 200)
        assert triaged_critical["sla_due_at"] == "2026-09-05T10:00:00Z"  # +1 day
        assert triaged_minor["sla_due_at"] == "2026-10-04T10:00:00Z"  # +30 days


class TestWarrantyWindowBoundary:

    def _closed_project_with_pinned_sc_date(self):
        # SC instant pinned at 2026-08-05T12:00:00Z, so the warranty window ends
        # exactly 365 days later, at 2027-08-05T12:00:00Z.
        return setup_closed_project(
            name="Proj W",
            sc_clock="2026-08-05T12:00:00Z",
            occupancy_date="2026-08-05T12:00:00Z",
            training_start="2026-08-06T09:00:00Z",
            training_end="2026-08-06T10:00:00Z",
        )

    def test_case_at_exact_window_end_accepted(self):
        """PRD §3.7: "A case is admissible only while the logical clock reads no later than `warranty_start_date` plus 365 days, and the interval is closed at its end: a report landing exactly at the final instant is accepted, while one a single second later is rejected with `ERR_WARRANTY_EXPIRED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/warranty_case_closed_interval_end_boundary
        """
        ctx = self._closed_project_with_pinned_sc_date()
        assert get_project(ctx["project"]["id"])["warranty_start_date"].startswith("2026-08-05")
        set_clock("2027-08-05T12:00:00Z")  # exactly warranty_start_date + 365 days
        case = validate_success(api_client.create_warranty_case(
            create_warranty_case_payload(ctx["project"]["id"], title="At-end case"),
            OWNER,
        ), 201)
        assert case["status"] == "REPORTED"

    def test_case_one_second_past_window_end_rejected(self):
        """PRD §3.7: "A case is admissible only while the logical clock reads no later than `warranty_start_date` plus 365 days, and the interval is closed at its end: a report landing exactly at the final instant is accepted, while one a single second later is rejected with `ERR_WARRANTY_EXPIRED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/warranty_case_closed_interval_end_boundary
        """
        ctx = self._closed_project_with_pinned_sc_date()
        set_clock("2027-08-05T12:00:01Z")  # one second past the end
        resp = api_client.create_warranty_case(
            create_warranty_case_payload(ctx["project"]["id"], title="Late case"),
            OWNER,
        )
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)


class TestWarrantyCaseStates:

    def test_warranty_case_before_project_closed_returns_error(self):
        """PRD §3.7: "Reporting against a project that is not yet `CLOSED` fails with `ERR_PROJECT_NOT_CLOSED` (HTTP 409)."

        Design: Corner/validations/warranty_case_before_project_closed_returns_error
        """
        ctx = setup_substantially_complete_project(name="Proj")
        resp = api_client.create_warranty_case(
            create_warranty_case_payload(ctx["project"]["id"], title="Too early"),
            OWNER,
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_CLOSED)

    def test_resolve_from_reported_returns_invalid_state(self):
        """PRD §3.7: "Resolution moves a `TRIAGED` case to `RESOLVED` and stores a `resolution_note`."
        PRD §2.10: "8. State-machine and project-phase validity (`ERR_INVALID_STATE`, or `ERR_PROJECT_NOT_CLOSED` for warranty reporting against a project that is not closed)."

        Design: Corner/state_machines/warranty_case_resolve_from_reported_returns_invalid_state
        """
        ctx = setup_closed_project(name="Proj")
        case = report_warranty_case(ctx["project"]["id"], title="Drip",
                                    description="sink drip")
        resp = api_client.resolve_warranty_case(case["id"], {"resolution_note": "fixed"}, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api_client.get_warranty_case(case["id"], PM), 200)
        assert after["status"] == "REPORTED"
        assert after["sla_due_at"] is None
