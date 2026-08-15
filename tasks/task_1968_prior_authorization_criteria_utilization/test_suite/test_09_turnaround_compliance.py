"""Turnaround SLA matrix and the logical-clock breach sweep (PRD §2.5)."""
from test_helpers import (
    TEST_USERS,
    basic_um_environment,
    create_provider,
    list_request_events,
    make_active_criteria_set,
    pended_request,
    set_clock,
    validate_success,
)

ADMIN = TEST_USERS["um_admin_headers"]


class TestDueAtMatrix:
    def test_due_at_matrix_three_cells(self, api):
        """PRD §2.5: "A request's `due_at` is its `received_at` plus the SLA hours for the pairing of the request's `urgency` and the governing criteria set's `line_of_business`: 24 hours for `URGENT` requests under `MEDICARE` or `MEDICAID`, 48 hours for `URGENT` requests under `COMMERCIAL`, 72 hours for `STANDARD` requests under `MEDICARE`, 120 hours for `STANDARD` requests under `MEDICAID`, and 168 hours for `STANDARD` requests under `COMMERCIAL`."
        PRD §2.5: "At startup the clock reads exactly `2026-08-01T00:00:00Z`, and the server must not fall back to wall-clock time before an administrator explicitly sets the clock."

        Design: Corner/calculations/due_at_matrix_three_cells
        """
        cs1, _g1 = make_active_criteria_set(
            name="Commercial Set", line_of_business="COMMERCIAL",
        )
        cs2, _g2 = make_active_criteria_set(
            name="Medicare Set", line_of_business="MEDICARE",
        )
        cs3, _g3 = make_active_criteria_set(
            name="Medicaid Set", line_of_business="MEDICAID",
        )
        provider = create_provider(name="SLA Provider")
        r1 = pended_request(provider["id"], cs1["id"], member_ref="S-01",
                            urgency="STANDARD")
        r2 = pended_request(provider["id"], cs2["id"], member_ref="S-02",
                            urgency="URGENT")
        r3 = pended_request(provider["id"], cs3["id"], member_ref="S-03",
                            urgency="STANDARD")
        assert r1["due_at"] == "2026-08-08T00:00:00.000Z", "168h STANDARD x COMMERCIAL"
        assert r2["due_at"] == "2026-08-02T00:00:00.000Z", "24h URGENT x MEDICARE"
        assert r3["due_at"] == "2026-08-06T00:00:00.000Z", "120h STANDARD x MEDICAID"


class TestBreachBoundary:
    def _setup_standard_request(self):
        provider, cs, _gv = basic_um_environment()
        req = pended_request(provider["id"], cs["id"])
        assert req["due_at"] == "2026-08-08T00:00:00.000Z"
        return req

    def test_at_due_at_is_not_a_breach(self, api):
        """PRD §2.5: "Breach comparison is strict and measured in whole seconds: a case breaches only when the logical clock is strictly later than its `due_at`; at the exact `due_at` instant the case is still compliant."

        Design: Difficulty/boundary_precision_check/tat_breach_strictly_greater_boundary
        """
        req = self._setup_standard_request()
        sweep = set_clock("2026-08-08T00:00:00Z")
        assert sweep["requests_flagged"] == 0
        reread = validate_success(api.get_prior_auth_request(req["id"], ADMIN))
        assert reread["is_tat_breached"] is False, (
            "clock == due_at is not a breach; the comparison is strict"
        )

    def test_one_second_past_due_at_breaches(self, api):
        """PRD §2.5: "Breach comparison is strict and measured in whole seconds: a case breaches only when the logical clock is strictly later than its `due_at`; at the exact `due_at` instant the case is still compliant."
        PRD §2.5: "The clock-advance sweep flags every undetermined request (one in `PENDED_REVIEW` or `ESCALATED_MD`) and every undecided appeal (one in `RECEIVED` or `IN_REVIEW`) whose `due_at` is strictly before the new clock, setting the sticky boolean `is_tat_breached` and emitting a `TAT_BREACHED` compliance event per flagged row."

        Design: Difficulty/boundary_precision_check/tat_breach_strictly_greater_boundary
        """
        req = self._setup_standard_request()
        sweep = set_clock("2026-08-08T00:00:01Z")
        assert sweep["requests_flagged"] == 1
        reread = validate_success(api.get_prior_auth_request(req["id"], ADMIN))
        assert reread["is_tat_breached"] is True
        events = list_request_events(req["id"], event_type="TAT_BREACHED")
        assert len(events) == 1


class TestSweepIdempotency:
    def test_second_advance_flags_nothing_new(self, api):
        """PRD §2.5: "The sweep is idempotent — rows already flagged are skipped and produce no duplicate events."
        PRD §2.5: "An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and immediately runs the turnaround-breach sweep described below; the response reports the new `current_utc` along with `requests_flagged` and `appeals_flagged` counts."

        Design: Corner/calculations/breach_sweep_idempotent_on_second_advance
        """
        provider, cs, _gv = basic_um_environment()
        req = pended_request(provider["id"], cs["id"])
        first = set_clock("2026-08-09T00:00:00Z")
        assert first["requests_flagged"] == 1
        second = set_clock("2026-08-10T00:00:00Z")
        assert second["requests_flagged"] == 0, (
            "sticky flag: the sweep does not double-count"
        )
        events = list_request_events(req["id"], event_type="TAT_BREACHED")
        assert len(events) == 1, "exactly one TAT_BREACHED event after both advances"
