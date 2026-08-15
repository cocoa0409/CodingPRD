"""Screening staffing: the computed screening-requirement read in its
PROJECTION and ACTUAL variants, the begin-turnaround staffing gate, and lane
open/close staffing semantics."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_manifest_entry,
    check_in_entry,
    create_open_lane,
    create_port_call,
    create_screening_lane,
    create_terminal,
    open_lane,
    setup_arrived_call,
    setup_base,
    validate_error,
    validate_success,
)

OPERATOR = TEST_USERS["operator_headers"]


def _screening_requirement(api, terminal_id, port_call_id, mode=None):
    resp = api.get_screening_requirement(terminal_id, OPERATOR,
                                         port_call_id=port_call_id, mode=mode)
    return validate_success(resp)


class TestProjectionVsActual:
    def _setup(self):
        """Lane OPEN with 2 officers; call booked 961 embark over a 12-hour
        turnaround; two EMBARK entries checked in."""
        ctx = setup_base(vessel_name="MV B")
        pc = create_port_call(ctx["terminal"]["id"], ctx["vessel"]["id"],
                              booked_embark_pax=961, booked_debark_pax=100)
        ctx["port_call"] = pc
        ctx["lane"] = create_open_lane(ctx["terminal"]["id"],
                                       officers_assigned=2)
        ves = ctx["vessel"]["id"]
        e1 = add_manifest_entry(pc["id"], ves, "P1", direction="EMBARK")
        e2 = add_manifest_entry(pc["id"], ves, "P2", direction="EMBARK")
        check_in_entry(e1["id"])
        check_in_entry(e2["id"])
        return ctx

    def test_projection_uses_booked_embark_pax(self, api):
        """PRD §3.5: "The numerator depends on the requested `mode`: under the
        default `PROJECTION` mode it is the call's `booked_embark_pax`; under
        `ACTUAL` mode it is the count of the call's `EMBARK` entries currently
        in `CHECKED_IN`, `SCREENED`, or `EMBARKED`, so the requirement tightens
        or relaxes as check-ins actually arrive."
        PRD §3.5: "The embarkation window, reported as `embark_window_hours`,
        is that turnaround length minus two tail hours reserved at the end of
        the call, raised to a floor of one hour and capped at eight hours."

        Design: Difficulty/dual_variant_calc/screening_requirement_projection_vs_actual
        """
        ctx = self._setup()
        data = _screening_requirement(api, ctx["terminal"]["id"],
                                      ctx["port_call"]["id"])
        assert data["required_officers"] == 3, "ceil(961 / (60 x 8))"
        assert data["embark_window_hours"] == 8, "min(8, 12 - 2)"
        assert data["assigned_officers"] == 2

    def test_actual_mode_uses_live_manifest_rows(self, api):
        """PRD §3.5: "The numerator depends on the requested `mode`: under the
        default `PROJECTION` mode it is the call's `booked_embark_pax`; under
        `ACTUAL` mode it is the count of the call's `EMBARK` entries currently
        in `CHECKED_IN`, `SCREENED`, or `EMBARKED`, so the requirement tightens
        or relaxes as check-ins actually arrive."
        PRD §3.5: "The read also reports `assigned_officers` — the sum of
        `officers_assigned` across the terminal's `OPEN` lanes only — and
        `satisfied`, which is true exactly when `assigned_officers` is at least
        `required_officers`; equality satisfies."

        Design: Difficulty/dual_variant_calc/screening_requirement_projection_vs_actual
        """
        ctx = self._setup()
        data = _screening_requirement(api, ctx["terminal"]["id"],
                                      ctx["port_call"]["id"], mode="ACTUAL")
        assert data["required_officers"] == 1, "ceil(2 / (60 x 8))"
        assert data["assigned_officers"] == 2
        assert data["satisfied"] is True


class TestNestedMinCeil:
    def _setup_three_calls(self):
        ctx = setup_base(vessel_name="MV D")
        term = ctx["terminal"]["id"]
        ves = ctx["vessel"]["id"]
        pc_x = create_port_call(term, ves, voyage_ref="VX",
                                scheduled_eta="2026-08-10T08:00:00Z",
                                scheduled_etd="2026-08-10T20:00:00Z",
                                booked_embark_pax=960, booked_debark_pax=0)
        pc_y = create_port_call(term, ves, voyage_ref="VY",
                                scheduled_eta="2026-08-12T08:00:00Z",
                                scheduled_etd="2026-08-12T20:00:00Z",
                                booked_embark_pax=961, booked_debark_pax=0)
        pc_z = create_port_call(term, ves, voyage_ref="VZ",
                                scheduled_eta="2026-08-14T08:00:00Z",
                                scheduled_etd="2026-08-14T15:00:00Z",
                                booked_embark_pax=961, booked_debark_pax=0)
        ctx["pc_x"] = pc_x
        ctx["pc_y"] = pc_y
        ctx["pc_z"] = pc_z
        return ctx

    def test_exact_division_does_not_round_up(self, api):
        """PRD §3.5: "The officer requirement, `required_officers`, divides the
        passenger numerator by the per-window officer throughput — sixty
        passengers per officer per hour, multiplied by the embarkation window
        in hours — and rounds the quotient up to a whole officer."

        Design: Difficulty/combinatorial_formula/screening_requirement_nested_min_ceil
        """
        ctx = self._setup_three_calls()
        data = _screening_requirement(api, ctx["terminal"]["id"],
                                      ctx["pc_x"]["id"])
        assert data["required_officers"] == 2, (
            "960 / (60 x 8) == 2.0 exactly; the ceiling adds nothing"
        )
        assert data["embark_window_hours"] == 8

    def test_ceil_and_min_arm(self, api):
        """PRD §3.5: "The officer requirement, `required_officers`, divides the
        passenger numerator by the per-window officer throughput — sixty
        passengers per officer per hour, multiplied by the embarkation window
        in hours — and rounds the quotient up to a whole officer."
        PRD §3.5: "The embarkation window, reported as `embark_window_hours`,
        is that turnaround length minus two tail hours reserved at the end of
        the call, raised to a floor of one hour and capped at eight hours."

        Design: Difficulty/combinatorial_formula/screening_requirement_nested_min_ceil
        """
        ctx = self._setup_three_calls()
        data_y = _screening_requirement(api, ctx["terminal"]["id"],
                                        ctx["pc_y"]["id"])
        assert data_y["required_officers"] == 3, "ceil(961 / 480) == 3"

        data_z = _screening_requirement(api, ctx["terminal"]["id"],
                                        ctx["pc_z"]["id"])
        assert data_z["embark_window_hours"] == 5, "min(8, 7 - 2)"
        assert data_z["required_officers"] == 4, "ceil(961 / (60 x 5))"


class TestBeginTurnaroundStaffingGate:
    def test_staffing_boundary_equality_satisfies(self, api):
        """PRD §3.3: "With the vessel alongside, a `TerminalOperator` begins
        the turnaround. The gate is screening staffing, computed per §3.5: the
        officers assigned across the terminal's `OPEN` screening lanes must
        meet the staffing requirement derived from the call's booked embarking
        passengers, or the request is rejected with `ERR_SCREENING_CAPACITY`
        (HTTP 409)."
        PRD §3.5: "The read also reports `assigned_officers` — the sum of
        `officers_assigned` across the terminal's `OPEN` lanes only — and
        `satisfied`, which is true exactly when `assigned_officers` is at least
        `required_officers`; equality satisfies."

        Design: Corner/validations/begin_turnaround_staffing_boundary
        """
        ctx = setup_arrived_call(booked_embark_pax=961, booked_debark_pax=0)
        create_open_lane(ctx["terminal"]["id"], lane_code="L1",
                         officers_assigned=2)
        lane2 = create_screening_lane(ctx["terminal"]["id"], lane_code="L2")

        short = api.begin_turnaround(ctx["port_call"]["id"], OPERATOR)
        validate_error(short, ApiErrorId.ERR_SCREENING_CAPACITY)

        open_lane(lane2["id"], officers_assigned=1)
        turned = validate_success(api.begin_turnaround(ctx["port_call"]["id"],
                                                       OPERATOR))
        assert turned["status"] == "TURNAROUND", (
            "3 assigned meets the requirement of exactly 3"
        )


class TestComputedRead:
    def test_satisfied_flag_tracks_assigned_vs_required(self, api):
        """PRD §3.5: "The read also reports `assigned_officers` — the sum of
        `officers_assigned` across the terminal's `OPEN` lanes only — and
        `satisfied`, which is true exactly when `assigned_officers` is at least
        `required_officers`; equality satisfies."

        Design: Corner/endpoints/screening_requirement_computed_read_satisfied_flag
        """
        ctx = setup_base()
        pc = create_port_call(ctx["terminal"]["id"], ctx["vessel"]["id"],
                              booked_embark_pax=961, booked_debark_pax=0)
        create_open_lane(ctx["terminal"]["id"], lane_code="L1",
                         officers_assigned=2)
        lane2 = create_screening_lane(ctx["terminal"]["id"], lane_code="L2")

        first = _screening_requirement(api, ctx["terminal"]["id"], pc["id"])
        assert first["required_officers"] == 3
        assert first["assigned_officers"] == 2
        assert first["satisfied"] is False

        open_lane(lane2["id"], officers_assigned=1)
        second = _screening_requirement(api, ctx["terminal"]["id"], pc["id"])
        assert second["assigned_officers"] == 3
        assert second["satisfied"] is True


class TestLaneStaffing:
    def test_open_requires_at_least_one_officer(self, api):
        """PRD §3.5: "A `TerminalOperator` opens a lane by supplying
        `officers_assigned`, which must be at least 1 — a lane cannot open
        unstaffed, and the attempt is rejected with `ERR_VALIDATION`; opening
        records the supplied staffing on the lane."

        Design: Corner/validations/lane_open_zero_officers_rejected
        """
        terminal = create_terminal()
        lane = create_screening_lane(terminal["id"])

        bad = api.open_screening_lane(lane["id"], {"officers_assigned": 0},
                                      OPERATOR)
        validate_error(bad, ApiErrorId.ERR_VALIDATION)

        opened = open_lane(lane["id"], officers_assigned=1)
        assert opened["status"] == "OPEN"
        assert opened["officers_assigned"] == 1

    def test_open_close_cycle_resets_officers(self, api):
        """PRD §3.5: "A lane is created `CLOSED` with `officers_assigned` at
        0."
        PRD §3.5: "A `TerminalOperator` opens a lane by supplying
        `officers_assigned`, which must be at least 1 — a lane cannot open
        unstaffed, and the attempt is rejected with `ERR_VALIDATION`; opening
        records the supplied staffing on the lane. Closing a lane returns it to
        `CLOSED` and resets `officers_assigned` to 0."

        Design: Corner/state_machines/lane_open_close_cycle_resets_officers
        """
        terminal = create_terminal()
        lane = create_screening_lane(terminal["id"])
        assert lane["status"] == "CLOSED"
        assert lane["officers_assigned"] == 0

        opened = open_lane(lane["id"], officers_assigned=3)
        assert opened["status"] == "OPEN"
        assert opened["officers_assigned"] == 3

        closed = validate_success(api.close_screening_lane(lane["id"], OPERATOR))
        assert closed["status"] == "CLOSED"
        assert closed["officers_assigned"] == 0
