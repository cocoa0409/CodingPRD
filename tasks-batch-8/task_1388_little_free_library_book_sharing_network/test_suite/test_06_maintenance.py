"""Maintenance pipeline: SLA deadlines, reimbursement math, reopen loop."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_timestamp_equals,
    create_active_steward,
    create_chartered_box,
    create_steward_with_active_box,
    make_steward_headers,
    pin_clock,
    report_maintenance,
    resolve_maintenance,
    triage_maintenance,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
MOD1 = TEST_USERS["mod1_headers"]


class TestReopenRevisionLoop:
    def _setup_resolved_then_reopened(self, api):
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Rosa Parks", box_name="Elm Box"
        )
        request = report_maintenance(box["id"], category="VANDALISM",
                                     description="Shelf torn off")
        triage_maintenance(request["id"], severity="HIGH",
                           scheduled_date="2026-08-03")
        first = resolve_maintenance(request["id"], labor_hours=1)
        return steward, box, request, first

    def test_first_resolution_and_reopen_resets_reimbursement(self, api):
        """PRD §3.5: "The same resolution stamps `resolved_at`, sets
        `sla_breached` by strict comparison — resolving strictly later than
        `sla_deadline_at` is a breach, while resolving exactly at the deadline
        is not — and bumps `resolution_count`, which accumulates across every
        resolution including ones after a reopen."
        PRD §3.5: "Reopening resets `reimbursement_cents` to null pending
        recomputation at the next resolution and recomputes the box's posture."
        PRD §3.5: "labor adds 500 cents per hour, itself rounded half-up to
        whole cents."

        Design: Difficulty/non_linear_state_machine/maintenance_reopen_revision_loop
        """
        steward, box, request, first = self._setup_resolved_then_reopened(api)
        assert first["status"] == "RESOLVED"
        assert first["resolution_count"] == 1
        # HIGH 72h x 1.0 SUMMER multiplier from triaged_at 2026-08-01T00:00:00Z.
        assert first["reimbursement_cents"] == 500
        assert_timestamp_equals(first["sla_deadline_at"],
                                "2026-08-04T00:00:00Z")

        reopened = validate_success(
            api.reopen_maintenance_request(
                request["id"], make_steward_headers(steward["id"])
            ),
            200,
        )
        assert reopened["status"] == "REOPENED"
        assert reopened["reimbursement_cents"] is None

    def test_second_resolve_recomputes_reimbursement_and_deadline(self, api):
        """PRD §3.5: "Within a strict fourteen-day window after `resolved_at`,
        the box's owner steward (anyone else drawing `ERR_FORBIDDEN_OWNERSHIP`)
        or a `NetworkAdmin` may reopen it, moving the request to `REOPENED`."
        PRD §3.5: "each parts line is reimbursed at eighty percent of its
        extended cost — quantity times unit cost times 0.8 — with every line
        rounded half-up to whole cents before the rounded lines are summed."
        PRD §3.5: "Triaging moves the request to `SCHEDULED`, stamps
        `triaged_at`, and computes the `sla_deadline_at`: the triage instant
        plus the severity's base allowance — 336 hours (fourteen days) for
        `LOW`, 168 hours (seven days) for `MEDIUM`, 72 hours (three days) for
        `HIGH`, 24 hours (one day) for `CRITICAL` — multiplied by the request's
        season multiplier."

        Design: Difficulty/non_linear_state_machine/maintenance_reopen_revision_loop
        """
        steward, box, request, first = self._setup_resolved_then_reopened(api)
        validate_success(
            api.reopen_maintenance_request(
                request["id"], make_steward_headers(steward["id"])
            ),
            200,
        )
        triage_maintenance(request["id"], severity="LOW",
                           scheduled_date="2026-08-04")
        second = resolve_maintenance(
            request["id"],
            parts=[{"description": "Hinge kit", "qty": 2,
                    "unit_cost_cents": 100}],
            labor_hours=0,
        )
        assert second["status"] == "RESOLVED"
        assert second["resolution_count"] == 2
        # round_half_up(2 * 100 * 0.8) = 160, labor 0.
        assert second["reimbursement_cents"] == 160
        # LOW 336h x 1.0 from the second triaged_at 2026-08-01T00:00:00Z.
        assert_timestamp_equals(second["sla_deadline_at"],
                                "2026-08-15T00:00:00Z")


class TestPartsReimbursement:
    def _setup_triaged_medium(self, api):
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Mary Anning", box_name="Pine St Box"
        )
        request = report_maintenance(box["id"], category="VANDALISM",
                                     description="Door kicked in")
        triaged = triage_maintenance(request["id"], severity="MEDIUM",
                                     scheduled_date="2026-08-05")
        return request, triaged

    def test_parts_reimbursement_per_line_rounding_order(self, api):
        """PRD §3.5: "each parts line is reimbursed at eighty percent of its
        extended cost — quantity times unit cost times 0.8 — with every line
        rounded half-up to whole cents before the rounded lines are summed
        (the pinning rule of §2.9)."
        PRD §2.9: "Reimbursement rounding is pinned to a specific order: every
        parts line is rounded half-up to whole cents first, and only then are
        the rounded line amounts summed; summing raw line products and rounding
        once at the end is forbidden because it yields different cents."

        Design: Difficulty/combinatorial_formula/parts_reimbursement_per_line_rounding_order
        """
        request, _triaged = self._setup_triaged_medium(api)
        resolved = resolve_maintenance(
            request["id"],
            parts=[
                {"description": "Replacement board", "qty": 1,
                 "unit_cost_cents": 101},
                {"description": "Paint tins", "qty": 2, "unit_cost_cents": 51},
            ],
            labor_hours=0,
        )
        # round_half_up(80.8)=81 plus round_half_up(81.6)=82 -> 163;
        # the forbidden sum-first order would yield 162.
        assert resolved["reimbursement_cents"] == 163

    def test_sla_deadline_and_season_fields_for_medium_request(self, api):
        """PRD §3.5: "Triaging moves the request to `SCHEDULED`, stamps
        `triaged_at`, and computes the `sla_deadline_at`: the triage instant
        plus the severity's base allowance — 336 hours (fourteen days) for
        `LOW`, 168 hours (seven days) for `MEDIUM`, 72 hours (three days) for
        `HIGH`, 24 hours (one day) for `CRITICAL` — multiplied by the request's
        season multiplier, so a winter report doubles every allowance."
        PRD §3.5: "Two seasonal facts are pinned at report time from the UTC
        month of the request's `created_at`: the `season_at_report` — `WINTER`
        for December through February, `SPRING` for March through May, `SUMMER`
        for June through August, `FALL` for September through November — and
        the `season_multiplier`, which is 2.0 for winter reports and 1.0 in
        every other season."
        PRD §3.5: "resolving strictly later than `sla_deadline_at` is a breach,
        while resolving exactly at the deadline is not."

        Design: Difficulty/combinatorial_formula/parts_reimbursement_per_line_rounding_order
        """
        request, _triaged = self._setup_triaged_medium(api)
        resolved = resolve_maintenance(request["id"])
        assert_timestamp_equals(resolved["sla_deadline_at"],
                                "2026-08-08T00:00:00Z")
        assert resolved["sla_breached"] is False
        assert resolved["season_at_report"] == "SUMMER"
        assert resolved["season_multiplier"] == 1.0


class TestWinterSla:
    def test_sla_winter_doubling_and_breach_boundary(self, api):
        """PRD §3.5: "the `season_multiplier`, which is 2.0 for winter reports
        and 1.0 in every other season".
        PRD §3.5: "the triage instant plus the severity's base allowance — 336
        hours (fourteen days) for `LOW`, 168 hours (seven days) for `MEDIUM`,
        72 hours (three days) for `HIGH`, 24 hours (one day) for `CRITICAL` —
        multiplied by the request's season multiplier, so a winter report
        doubles every allowance."
        PRD §3.5: "resolving strictly later than `sla_deadline_at` is a breach,
        while resolving exactly at the deadline is not."

        Design: Corner/calculations/sla_winter_doubling_and_breach_boundary
        """
        pin_clock("2026-12-01T00:00:00Z")
        steward, box = create_steward_with_active_box(
            steward_name="Winter Owner", box_name="Winter Box",
            region_code="WA",
        )
        req1 = report_maintenance(box["id"], category="WEATHER_DAMAGE",
                                  description="Ice damage A")
        req2 = report_maintenance(box["id"], category="WEATHER_DAMAGE",
                                  description="Ice damage B")
        triage_maintenance(req1["id"], severity="CRITICAL",
                           scheduled_date="2026-12-02")
        triaged2 = triage_maintenance(req2["id"], severity="CRITICAL",
                                      scheduled_date="2026-12-02")
        # CRITICAL 24h x 2.0 WINTER multiplier from triaged_at 2026-12-01.
        assert_timestamp_equals(triaged2["sla_deadline_at"],
                                "2026-12-03T00:00:00Z")
        assert triaged2["season_multiplier"] == 2.0
        assert triaged2["season_at_report"] == "WINTER"

        # Resolving exactly at the deadline is NOT a breach (strict >).
        pin_clock("2026-12-03T00:00:00Z")
        resolved1 = resolve_maintenance(req1["id"])
        assert resolved1["sla_breached"] is False

        # One second later is a breach.
        pin_clock("2026-12-03T00:00:01Z")
        resolved2 = resolve_maintenance(req2["id"])
        assert resolved2["sla_breached"] is True


class TestReimbursementCap:
    def test_reimbursement_capped_at_max(self, api):
        """PRD §3.5: "the total is the parts subtotal plus labor, capped at
        15,000 cents (one hundred fifty dollars), with `parts` defaulting to
        empty and `labor_hours` to 0 when omitted."

        Design: Corner/calculations/reimbursement_capped_at_max
        """
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Cap Owner", box_name="Cap Box"
        )
        request = report_maintenance(box["id"], category="WEATHER_DAMAGE",
                                     description="Full rebuild")
        triage_maintenance(request["id"], severity="MEDIUM",
                           scheduled_date="2026-08-02")
        resolved = resolve_maintenance(
            request["id"],
            parts=[{"description": "Full rebuild kit", "qty": 200,
                    "unit_cost_cents": 1000}],
            labor_hours=0,
        )
        # min(160000 + 0, 15000) clamps at the cap.
        assert resolved["reimbursement_cents"] == 15000


class TestTemporalGates:
    def test_schedule_date_in_past_rejected(self, api):
        """PRD §3.5: "The operator supplies a `severity` of `LOW`, `MEDIUM`,
        `HIGH`, or `CRITICAL` (anything else is `ERR_INVALID_REQUEST`) and a
        `scheduled_date` that must not lie before the current logical date
        (`ERR_SCHEDULE_DATE_PAST`)."

        Design: Corner/validations/schedule_date_in_past_rejected
        """
        pin_clock()
        steward = create_active_steward(full_name="Past Tester",
                                        email="past@example.org")
        box = create_chartered_box(steward, name="Past Box")
        request = report_maintenance(box["id"], category="WEAR",
                                     description="Loose screw")

        res = api.triage_maintenance_request(
            request["id"],
            {"severity": "LOW", "scheduled_date": "2026-07-01"},
            MOD1,
        )
        validate_error(res, ApiErrorId.ERR_SCHEDULE_DATE_PAST.value,
                       expected_status=422)

        after = validate_success(
            api.get_maintenance_request(request["id"], MOD1), 200
        )
        assert after["status"] == "REPORTED"
        assert after["severity"] is None

    def test_reopen_window_expired_at_exactly_14_days(self, api):
        """PRD §3.5: "Within a strict fourteen-day window after `resolved_at`,
        the box's owner steward (anyone else drawing `ERR_FORBIDDEN_OWNERSHIP`)
        or a `NetworkAdmin` may reopen it, moving the request to `REOPENED`; at
        exactly fourteen days the window is already expired and the attempt
        fails with `ERR_REOPEN_WINDOW_EXPIRED`, as does any later attempt."

        Design: Corner/validations/reopen_window_expired_at_exactly_14_days
        """
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Reopen Tester", box_name="Reopen Box"
        )
        request = report_maintenance(box["id"], category="VANDALISM",
                                     description="Scratch")
        triage_maintenance(request["id"], severity="LOW",
                           scheduled_date="2026-08-01")
        resolve_maintenance(request["id"])

        pin_clock("2026-08-15T00:00:00Z")
        res = api.reopen_maintenance_request(
            request["id"], make_steward_headers(steward["id"])
        )
        validate_error(res, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED.value,
                       expected_status=422)

        after = validate_success(
            api.get_maintenance_request(request["id"], MOD1), 200
        )
        assert after["status"] == "RESOLVED"
        assert after["resolution_count"] == 1


class TestWontFixTerminal:
    def test_maintenance_wont_fix_terminal_lockdown(self, api):
        """PRD §3.5: "Alternatively, an `outcome` of `WONT_FIX` closes a
        `REPORTED` or `SCHEDULED` request with no payout; from `SCHEDULED` the
        box's counters and posture are recomputed, while from `REPORTED`
        nothing downstream changes since the request never carried a severity."
        PRD §2.8: "State preconditions. The target entity sits in the exact
        from-state the transition requires — failures are `ERR_INVALID_STATE`
        or `ERR_DRIVE_NOT_OPEN` (409)."

        Design: Corner/state_machines/maintenance_wont_fix_terminal_lockdown
        """
        pin_clock()
        steward = create_active_steward(full_name="Terminal Owner",
                                        email="term@example.org")
        box = create_chartered_box(steward, name="Terminal Box")
        request = report_maintenance(box["id"], category="INSTALLATION_DEFECT",
                                     description="Post misaligned")
        triage_maintenance(request["id"], severity="LOW",
                           scheduled_date="2026-08-02")
        closed = resolve_maintenance(request["id"], outcome="WONT_FIX",
                                     resolution_notes="Cosmetic only")
        assert closed["status"] == "WONT_FIX"

        res = api.triage_maintenance_request(
            request["id"],
            {"severity": "HIGH", "scheduled_date": "2026-08-03"},
            MOD1,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value,
                       expected_status=409)

        after = validate_success(
            api.get_maintenance_request(request["id"], MOD1), 200
        )
        assert after["status"] == "WONT_FIX"
        assert after["resolution_count"] == 0
