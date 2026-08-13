"""Crew calls and union labor accounting: dual-variant costing, per-line
rounding order, overtime boundaries, turnaround buffers, and the call
lifecycle gates."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_planning_production, create_technician, create_crew_call, get_crew_call,
    transition_crew_call, create_assignment, get_crew_assignment,
    confirm_assignment, report_hours_worked, confirm_crew_call, set_clock,
    make_crew_chief_headers,
)

PM = TEST_USERS["production_manager_headers"]
CALL_END = "2026-09-01T18:00:00Z"


def _worked_call(api, ruleset, specs, headcount=None,
                 call_start="2026-09-01T08:00:00Z", call_end=CALL_END):
    """One crew call (PUBLISHED -> CONFIRMED) whose assignments have all reported
    hours; clock at call_end so the call can complete. `specs` is a list of
    (union_card_no, hourly_rate_cents, worked_hours).

    `call_start`/`call_end` may be overridden when a test runs more than one
    scenario in sequence: the logical clock only advances (PRD §2.4), so any
    later scenario's publish deadline (call_start - 48h, PRD §3.5) must still
    lie at or after the clock value left behind by the earlier scenario."""
    ctx = setup_planning_production(venue_overrides={"union_ruleset": ruleset})
    call = create_crew_call(ctx["production"]["id"],
                            required_headcount=headcount or len(specs),
                            call_start=call_start, call_end=call_end)
    transition_crew_call(call["id"], "PUBLISHED")
    triples = []
    for card, rate, hours in specs:
        tech = create_technician(union_card_no=card, hourly_rate_cents=rate)
        asg = create_assignment(call["id"], tech["id"])
        confirm_assignment(asg["id"], tech["id"])
        triples.append((tech, asg, hours))
    confirm_crew_call(call["id"])
    for tech, asg, hours in triples:
        report_hours_worked(asg["id"], tech["id"], hours)
    set_clock(call_end)
    return ctx, call, triples


class TestDualVariantLaborCost:
    def test_labor_cost_iatse_vs_non_union(self, api):
        """PRD §3.5: "An `IATSE` call adds a flat two-hour meal penalty to the paid-hours total whenever the technician's `worked_hours` exceeded six hours; `TEAMSTERS` calls omit the meal penalty. Paid hours equal the straight-time hours, plus one and a half times the first-tier overtime hours, plus twice the double-time hours, plus the meal penalty hours; the assignment's `labor_charge_cents` is the technician's `hourly_rate_cents` multiplied by those paid hours, rounded half-up to whole cents. Under the non-union variant (`NON_UNION`), straight time runs to a fixed ten hours, hours beyond ten are paid at one and a half times, there is no double-time tier and no meal penalty, and the charge is the same rate-times-paid-hours product rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/labor_union_vs_non_union_ruleset
        """
        # IATSE, 10.00h @ 10000: 8 ST + 2 OT1 x1.5 + 2h meal penalty = 13 paid hours.
        _, call1, triples1 = _worked_call(api, "IATSE", [("U-1001", 10000, 10.00)])
        data = transition_crew_call(call1["id"], "COMPLETED")
        assert data["labor_cost_cents"] == 130000
        asg1 = get_crew_assignment(triples1[0][1]["id"])
        assert asg1["labor_charge_cents"] == 130000
        assert asg1["status"] == "RECONCILED"
        # NON_UNION, identical inputs: 10 ST = 10 paid hours.
        # The first scenario left the logical clock at 2026-09-01T18:00; the
        # second call's window must sit at least 48h beyond that or the
        # publish deadline (PRD §3.5) has already passed.
        _, call2, _ = _worked_call(api, "NON_UNION", [("U-1002", 10000, 10.00)],
                                   call_start="2026-09-10T08:00:00Z",
                                   call_end="2026-09-10T18:00:00Z")
        data = transition_crew_call(call2["id"], "COMPLETED")
        assert data["labor_cost_cents"] == 100000
        assert 130000 - 100000 == 30000

    def test_labor_cost_teamsters_omits_meal_penalty(self, api):
        """PRD §3.5: "An `IATSE` call adds a flat two-hour meal penalty to the paid-hours total whenever the technician's `worked_hours` exceeded six hours; `TEAMSTERS` calls omit the meal penalty."

        Design: Difficulty/dual_variant_calc/labor_union_vs_non_union_ruleset
        """
        # TEAMSTERS, 10.00h @ 10000: 8 ST + 2 OT1 x1.5 = 11 paid hours, no meal penalty.
        _, call, _ = _worked_call(api, "TEAMSTERS", [("U-1001", 10000, 10.00)])
        data = transition_crew_call(call["id"], "COMPLETED")
        assert data["labor_cost_cents"] == 110000


class TestPerLineRoundingOrder:
    def test_per_line_rounding_before_summation(self, api):
        """PRD §3.5: "The computation is pinned: each assignment's charge is rounded half-up to whole cents *before* summation, and summing unrounded lines and rounding once is a different, forbidden order."

        Design: Difficulty/combinatorial_formula/crew_labor_per_line_rounding_order
        """
        # NON_UNION 10.50h @ 6667: 10 ST + 0.5 OT1 x1.5 = 10.75 paid hours
        # -> round_half_up(6667 x 10.75) = round_half_up(71670.25) = 71670 per line.
        _, call, triples = _worked_call(api, "NON_UNION",
                                        [("U-1001", 6667, 10.50), ("U-1002", 6667, 10.50)])
        data = transition_crew_call(call["id"], "COMPLETED")
        for _, asg, _ in triples:
            assert get_crew_assignment(asg["id"])["labor_charge_cents"] == 71670
        assert data["labor_cost_cents"] == 143340, \
            "per-line rounding yields 143340, not the forbidden sum-then-round 143341"

    def test_min_call_hours_floor_applies(self, api):
        """PRD §3.5: "The per-assignment charge starts from billable hours — the greater of the technician's `worked_hours` and the venue's `min_call_hours`, so short shifts still bill the union minimum."

        Design: Difficulty/combinatorial_formula/crew_labor_per_line_rounding_order
        """
        # NON_UNION, worked 2.00h with venue min_call_hours 4: billable 4 -> 40000.
        _, call, _ = _worked_call(api, "NON_UNION", [("U-1001", 10000, 2.00)])
        data = transition_crew_call(call["id"], "COMPLETED")
        assert data["labor_cost_cents"] == 40000


class TestOvertimeThresholds:
    def test_overtime_threshold_eight_hours_exact(self, api):
        """PRD §3.5: "Under the union variant (`IATSE` or `TEAMSTERS`), billable hours split into three tiers: straight-time hours are the smaller of the billable hours and the venue's `ot1_threshold_hours`; first-tier overtime hours are the hours beyond `ot1_threshold_hours` (never negative), capped at the span between `ot2_threshold_hours` and `ot1_threshold_hours`; and double-time hours are whatever remains beyond `ot2_threshold_hours` (never negative)."

        Design: Difficulty/boundary_precision_check/overtime_threshold_eight_hours_exact
        """
        _, call, triples = _worked_call(api, "IATSE",
                                        [("U-1001", 10000, 8.00), ("U-1002", 10000, 8.01)])
        transition_crew_call(call["id"], "COMPLETED")
        # 8.00h: 8 ST + 2h meal penalty = 10 paid hours -> 100000 (zero OT1).
        assert get_crew_assignment(triples[0][1]["id"])["labor_charge_cents"] == 100000
        # 8.01h: +0.01 OT1 x1.5 = +0.015 paid hours -> 100150.
        assert get_crew_assignment(triples[1][1]["id"])["labor_charge_cents"] == 100150

    def test_double_time_threshold_twelve_hours_exact(self, api):
        """PRD §3.5: "first-tier overtime hours are the hours beyond `ot1_threshold_hours` (never negative), capped at the span between `ot2_threshold_hours` and `ot1_threshold_hours`; and double-time hours are whatever remains beyond `ot2_threshold_hours` (never negative)."

        Design: Difficulty/boundary_precision_check/overtime_threshold_eight_hours_exact
        """
        _, call, triples = _worked_call(api, "IATSE",
                                        [("U-1001", 10000, 12.00), ("U-1002", 10000, 12.01)])
        transition_crew_call(call["id"], "COMPLETED")
        # 12.00h: 8 ST + 4 OT1 x1.5 + 0 OT2 + 2h meal = 16 paid hours -> 160000.
        assert get_crew_assignment(triples[0][1]["id"])["labor_charge_cents"] == 160000
        # 12.01h: +0.01 OT2 x2 = +0.02 paid hours -> 160200.
        assert get_crew_assignment(triples[1][1]["id"])["labor_charge_cents"] == 160200


class TestTechnicianTurnaround:
    def test_turnaround_gap_below_minimum_rejected(self, api):
        """PRD §3.5: "First, turnaround: for every other assignment of the same technician in `ASSIGNED`, `CONFIRMED`, or `WORKED` status, the rest gap between the two call windows must be at least the venue's `turnaround_min_hours` — a gap exactly equal to the minimum passes — and a tighter turnaround is rejected with `ERR_TECHNICIAN_TURNAROUND` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/technician_turnaround_buffer
        """
        ctx = setup_planning_production()  # turnaround_min_hours 8
        tech = create_technician()
        call1 = create_crew_call(ctx["production"]["id"],
                                 call_start="2026-09-01T08:00:00Z",
                                 call_end="2026-09-01T16:00:00Z")
        transition_crew_call(call1["id"], "PUBLISHED")
        create_assignment(call1["id"], tech["id"])
        call2 = create_crew_call(ctx["production"]["id"],
                                 call_start="2026-09-01T20:00:00Z",
                                 call_end="2026-09-02T04:00:00Z")
        transition_crew_call(call2["id"], "PUBLISHED")
        resp = api.create_crew_assignment(call2["id"], {"technician_id": tech["id"]}, PM)
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_TURNAROUND)  # 4h gap < 8h
        call3 = create_crew_call(ctx["production"]["id"],
                                 call_start="2026-09-02T00:00:00Z",
                                 call_end="2026-09-02T08:00:00Z")
        transition_crew_call(call3["id"], "PUBLISHED")
        data = validate_success(api.create_crew_assignment(
            call3["id"], {"technician_id": tech["id"]}, PM), expected_status=201)
        assert data["status"] == "ASSIGNED", "gap exactly 8h meets the >= rule"

    def test_turnaround_ignores_terminal_assignments(self, api):
        """PRD §3.5: "First, turnaround: for every other assignment of the same technician in `ASSIGNED`, `CONFIRMED`, or `WORKED` status, the rest gap between the two call windows must be at least the venue's `turnaround_min_hours` — a gap exactly equal to the minimum passes — and a tighter turnaround is rejected with `ERR_TECHNICIAN_TURNAROUND` (HTTP 409)."
        PRD §3.5: "Technicians who never appeared are marked `NO_SHOW` from `ASSIGNED` or `CONFIRMED` by the `ProductionManager`."

        Design: Difficulty/resource_temporal_overlap/technician_turnaround_buffer
        """
        ctx = setup_planning_production()
        tech = create_technician()
        call1 = create_crew_call(ctx["production"]["id"],
                                 call_start="2026-09-01T08:00:00Z",
                                 call_end="2026-09-01T16:00:00Z")
        transition_crew_call(call1["id"], "PUBLISHED")
        asg1 = create_assignment(call1["id"], tech["id"])
        validate_success(api.transition_crew_assignment(asg1["id"], {"to": "NO_SHOW"}, PM))
        call2 = create_crew_call(ctx["production"]["id"],
                                 call_start="2026-09-01T20:00:00Z",
                                 call_end="2026-09-02T04:00:00Z")
        transition_crew_call(call2["id"], "PUBLISHED")
        data = validate_success(api.create_crew_assignment(
            call2["id"], {"technician_id": tech["id"]}, PM), expected_status=201)
        assert data["status"] == "ASSIGNED", "a NO_SHOW assignment no longer blocks the gap"


class TestCrewCallGates:
    def test_assignment_classification_mismatch(self, api):
        """PRD §3.5: "Second, classification: the technician's trade must match the call's department mapping — `LIGHTING` calls take `LIGHTING_TECH`, `RIGGING` calls take `RIGGER`, and `STAGEHANDS` calls take `STAGEHAND` — and a mismatch is rejected with `ERR_CLASSIFICATION_MISMATCH` (HTTP 422)."

        Design: Corner/errors/assignment_classification_mismatch
        """
        ctx = setup_planning_production()
        rigger = create_technician(full_name="Rg One", union_card_no="U-2001",
                                   classification="RIGGER", hourly_rate_cents=11000)
        lt = create_technician()
        call = create_crew_call(ctx["production"]["id"])
        transition_crew_call(call["id"], "PUBLISHED")
        resp = api.create_crew_assignment(call["id"], {"technician_id": rigger["id"]}, PM)
        validate_error(resp, ApiErrorId.ERR_CLASSIFICATION_MISMATCH)
        data = validate_success(api.create_crew_assignment(
            call["id"], {"technician_id": lt["id"]}, PM), expected_status=201)
        assert data["status"] == "ASSIGNED"

    def test_crew_call_confirm_headcount_unmet(self, api):
        """PRD §3.5: "Once the count of `CONFIRMED` assignments reaches the call's `required_headcount`, the `ProductionManager` may confirm the call itself (`PUBLISHED` → `CONFIRMED`); shortfalls are rejected with `ERR_CREW_HEADCOUNT_UNMET` (HTTP 409)."

        Design: Corner/errors/crew_call_confirm_headcount_unmet
        """
        ctx = setup_planning_production()
        t1 = create_technician(union_card_no="U-1001")
        t2 = create_technician(full_name="Lt Two", union_card_no="U-1002")
        call = create_crew_call(ctx["production"]["id"], required_headcount=2)
        transition_crew_call(call["id"], "PUBLISHED")
        asg1 = create_assignment(call["id"], t1["id"])
        asg2 = create_assignment(call["id"], t2["id"])
        confirm_assignment(asg1["id"], t1["id"])
        resp = api.transition_crew_call(call["id"], {"to": "CONFIRMED"}, PM)
        validate_error(resp, ApiErrorId.ERR_CREW_HEADCOUNT_UNMET)
        confirm_assignment(asg2["id"], t2["id"])
        data = transition_crew_call(call["id"], "CONFIRMED")
        assert data["status"] == "CONFIRMED", "2 >= 2 meets the headcount gate"

    def test_crew_call_publish_inside_lead_time(self, api):
        """PRD §3.5: "Publishing a call (`DRAFT` → `PUBLISHED`) is deadline-gated: the logical clock must be at or before `call_start` minus the venue's `crew_call_publish_lead_hours`, or the publish is rejected with `ERR_CREW_CALL_LATE` (HTTP 422)."

        Design: Corner/errors/crew_call_publish_inside_lead_time
        """
        ctx = setup_planning_production()
        call_ok = create_crew_call(ctx["production"]["id"])
        set_clock("2026-08-30T08:00:00Z")  # exactly call_start - 48h: "at or before" passes
        data = transition_crew_call(call_ok["id"], "PUBLISHED")
        assert data["status"] == "PUBLISHED"
        call_late = create_crew_call(ctx["production"]["id"])
        set_clock("2026-08-31T09:00:00Z")  # 23h before call_start < 48h lead
        resp = api.transition_crew_call(call_late["id"], {"to": "PUBLISHED"}, PM)
        validate_error(resp, ApiErrorId.ERR_CREW_CALL_LATE)
        assert get_crew_call(call_late["id"])["status"] == "DRAFT"

    def test_call_complete_before_call_end_too_early(self, api):
        """PRD §3.5: "Completing the call (`CONFIRMED` → `COMPLETED`) requires every assignment to be in `WORKED`, `NO_SHOW`, or `CANCELLED` (otherwise `ERR_INVALID_STATE`) and requires the logical clock to have reached `call_end` (otherwise `ERR_TOO_EARLY`)."
        PRD §2.4: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter."

        Design: Corner/errors/call_complete_before_call_end_too_early
        """
        ctx = setup_planning_production()
        tech = create_technician()
        call = create_crew_call(ctx["production"]["id"])
        transition_crew_call(call["id"], "PUBLISHED")
        asg = create_assignment(call["id"], tech["id"])
        confirm_assignment(asg["id"], tech["id"])
        confirm_crew_call(call["id"])
        report_hours_worked(asg["id"], tech["id"], 8.00)
        # The logical clock is still at startup (2026-08-01), before call_end.
        resp = api.transition_crew_call(call["id"], {"to": "COMPLETED"}, PM)
        validate_error(resp, ApiErrorId.ERR_TOO_EARLY)
        after = get_crew_call(call["id"])
        assert after["status"] == "CONFIRMED"
        assert after.get("labor_cost_cents") is None

    def test_worked_hours_bounds(self, api):
        """PRD §3.5: "A `CONFIRMED` assignment advances to `WORKED` either by the owning `CrewChief` (same ownership rule) or by a `ProductionManager` entering hours on their behalf; both supply `worked_hours`, which must be greater than 0, at most 24, and expressed with no more than 2 decimal places, else `ERR_HOURS_OUT_OF_RANGE` (HTTP 422) — and per the pipeline, this range check runs after all state checks, so an hours report against a stale-state assignment reports the state error instead."

        Design: Corner/errors/worked_hours_bounds
        """
        ctx = setup_planning_production()
        tech = create_technician()
        call = create_crew_call(ctx["production"]["id"])
        transition_crew_call(call["id"], "PUBLISHED")
        asg = create_assignment(call["id"], tech["id"])
        confirm_assignment(asg["id"], tech["id"])
        resp = api.transition_crew_assignment(
            asg["id"], {"to": "WORKED", "worked_hours": 25}, make_crew_chief_headers(tech["id"]))
        validate_error(resp, ApiErrorId.ERR_HOURS_OUT_OF_RANGE)
        resp = api.transition_crew_assignment(
            asg["id"], {"to": "WORKED", "worked_hours": 0}, make_crew_chief_headers(tech["id"]))
        validate_error(resp, ApiErrorId.ERR_HOURS_OUT_OF_RANGE)
        assert get_crew_assignment(asg["id"])["status"] == "CONFIRMED"
        data = report_hours_worked(asg["id"], tech["id"], 24.00)
        assert data["status"] == "WORKED", "24.00 is the inclusive upper bound"

    def test_crew_chief_cannot_confirm_others_assignment(self, api):
        """PRD §2.1: "A `CrewChief` confirming an assignment or reporting hours on it must be the technician named by that assignment, or the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/errors/crew_chief_cannot_confirm_others_assignment
        """
        ctx = setup_planning_production()
        t1 = create_technician(union_card_no="U-1001")
        t2 = create_technician(full_name="Lt Two", union_card_no="U-1002")
        call = create_crew_call(ctx["production"]["id"], required_headcount=2)
        transition_crew_call(call["id"], "PUBLISHED")
        asg1 = create_assignment(call["id"], t1["id"])
        resp = api.transition_crew_assignment(
            asg1["id"], {"to": "CONFIRMED"}, make_crew_chief_headers(t2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        data = confirm_assignment(asg1["id"], t1["id"])
        assert data["status"] == "CONFIRMED"
