"""Difficulty queue A — combinatorial_formula instances (demand score inputs;
productivity per-clean rounding order)."""
import pytest

from test_helpers import (
    CLOCK_T0800,
    api_client,
    create_placement_demand_payload,
    get_success_data,
    set_clock,
    setup_basic_scenario,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    assign_request,
    complete_request,
    create_bed,
    create_request,
    create_standard,
    create_unit,
    seed_supplies,
    start_request,
    submit_audit,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
ANY = TEST_USERS["any_headers"]


class TestDemandScoreMultiInputNonlinear:
    def test_score_combines_base_wait_and_scarcity(self, api):
        """PRD §3.2: "The score combines three parts. First, an urgency base:
        1000 for `STAT`, 500 for `URGENT`, 100 for `STANDARD`. Second, a
        waiting component: 2 points per whole minute waited since creation,
        with partial minutes discarded and negative waits impossible, counting
        at most the first 120 minutes — two hours — of waiting. Third, a
        scarcity bonus of 50 points, applied exactly when the unit currently
        has no `READY` bed of the `required_bed_kind`. The total is rounded to
        two decimal places, half up."

        Design: Difficulty/combinatorial_formula/demand_score_multi_input_nonlinear
        """
        set_clock(CLOCK_T0800)
        unit = create_unit()
        create_standard("ROUTINE")
        create_bed(unit["id"], "B1", "STANDARD")  # stays VACANT_DIRTY
        demand = get_success_data(
            api.create_placement_demand(
                create_placement_demand_payload(
                    unit_id=unit["id"],
                    urgency_tier="URGENT",
                    needed_by="2026-08-01T18:00:00Z",
                ),
                COORDINATOR,
            )
        )

        set_clock("2026-08-01T08:30:00Z")
        d = get_success_data(api.get_placement_demand(demand["id"], ANY))
        # 500 + min(30,120)*2 + 50 = 610.
        assert d["priority_score"] == pytest.approx(610.0, abs=0.01)
        assert d["status"] == "OPEN"

        # Regrade swaps the tier base; wait unchanged.
        get_success_data(
            api.regrade_placement_demand(demand["id"], {"urgency_tier": "STAT"}, COORDINATOR)
        )
        d = get_success_data(api.get_placement_demand(demand["id"], ANY))
        # 1000 + 60 + 50 = 1110.
        assert d["priority_score"] == pytest.approx(1110.0, abs=0.01)

        # Regrade back and push the wait past the 120-minute cap.
        get_success_data(
            api.regrade_placement_demand(
                demand["id"], {"urgency_tier": "URGENT"}, COORDINATOR
            )
        )
        set_clock("2026-08-01T11:20:00Z")
        d = get_success_data(api.get_placement_demand(demand["id"], ANY))
        # 500 + min(200,120)*2 + 50 = 790.
        assert d["priority_score"] == pytest.approx(790.0, abs=0.01)

    def test_scarcity_bonus_removed_by_ready_bed_of_matching_kind(self, api):
        """PRD §3.2: "Third, a scarcity bonus of 50 points, applied exactly
        when the unit currently has no `READY` bed of the `required_bed_kind`."
        PRD §3.2: "A demand's `priority_score` is recomputed on every read, at
        every ops-run, on the demand's own creation, regrade, or cancellation,
        and whenever a bed of the matching kind in the unit enters or leaves
        `READY`, because bed scarcity feeds the score."

        Design: Difficulty/combinatorial_formula/demand_score_multi_input_nonlinear
        """
        set_clock(CLOCK_T0800)
        ctx_unit = create_unit()
        create_standard("ROUTINE")
        seed_supplies("DISINFECTANT", "CLOTH")
        from test_helpers.fixtures import create_technician, create_staff
        from test_helpers import make_technician_headers

        tech = create_technician("T1")
        get_success_data(
            api.clock_in_staff(tech["id"], make_technician_headers(tech["id"]))
        )
        auditor = create_staff("A1", capabilities=("AUDIT",), display_name="Auditor One")
        demand = get_success_data(
            api.create_placement_demand(
                create_placement_demand_payload(
                    unit_id=ctx_unit["id"], urgency_tier="URGENT"
                ),
                COORDINATOR,
            )
        )
        # Drive bed READY at 08:45 -> the demand matches at that instant.
        bed = create_bed(ctx_unit["id"], "B1", "STANDARD")
        req = create_request(bed["id"], "ROUTINE")
        assign_request(req["id"], tech["id"])
        start_request(req["id"], tech["id"])
        set_clock("2026-08-01T08:45:00Z")
        complete_request(req["id"], tech["id"])
        submit_audit(req["id"], auditor["id"], rlu_reading=100)

        # The matching demand is now MATCHED (bed of its kind is READY).
        d = get_success_data(api.get_placement_demand(demand["id"], ANY))
        assert d["status"] == "MATCHED"
        # Score without scarcity bonus: 500 + 45*2 = 590.
        assert d["priority_score"] == pytest.approx(590.0, abs=0.01)


class TestProductivityPerLineRoundingOrder:
    def test_per_clean_rounding_before_summation(self, api):
        """PRD §3.6: "The per-clean credit is the base credit for the request's
        `clean_type` — 1.00 for `ROUTINE`, 1.50 for `ISOLATION`, 2.00 for
        `TERMINAL` — multiplied by the clamped factor, and it is rounded to two
        decimal places half-up **per clean, before summation**;
        `verified_credit_total` is the sum of those rounded credits. Rounding
        order is observable: three cleans at a raw credit of 1.125 each total
        3.39 (three times 1.13), not the 3.38 that summing raw and rounding
        once would give."

        Design: Difficulty/combinatorial_formula/productivity_per_line_rounding_order
        """
        ctx = setup_basic_scenario()
        tech = ctx["tech"]
        b2 = create_bed(ctx["unit"]["id"], "B2", "STANDARD")
        b3 = create_bed(ctx["unit"]["id"], "B3", "STANDARD")

        # Clean 1: 08:00 -> 08:40 (ef = 45/40 = 1.125 -> credit 1.13).
        r1 = create_request(ctx["bed"]["id"], "ROUTINE")
        assign_request(r1["id"], tech["id"])
        start_request(r1["id"], tech["id"])
        set_clock("2026-08-01T08:40:00Z")
        complete_request(r1["id"], tech["id"])
        submit_audit(r1["id"], ctx["auditor"]["id"], rlu_reading=100)

        # Clean 2: 08:40 -> 09:20.
        r2 = create_request(b2["id"], "ROUTINE")
        assign_request(r2["id"], tech["id"])
        start_request(r2["id"], tech["id"])
        set_clock("2026-08-01T09:20:00Z")
        complete_request(r2["id"], tech["id"])
        submit_audit(r2["id"], ctx["auditor"]["id"], rlu_reading=100)

        # Clean 3: 09:20 -> 10:00.
        r3 = create_request(b3["id"], "ROUTINE")
        assign_request(r3["id"], tech["id"])
        start_request(r3["id"], tech["id"])
        set_clock("2026-08-01T10:00:00Z")
        complete_request(r3["id"], tech["id"])
        submit_audit(r3["id"], ctx["auditor"]["id"], rlu_reading=100)

        prod = get_success_data(api.get_staff_productivity(tech["id"], ANY))
        assert prod["verified_credit_total"] == pytest.approx(3.39, abs=0.005)
        assert prod["qa_fail_count"] == 0

    def test_completed_clean_count_tracks_verified_cleans(self, api):
        """PRD §3.6: "The completing technician is credited:
        `completed_clean_count` rises by one, `verified_credit_total` absorbs
        the per-clean credit described below, and both `productivity_score` and
        `stat_eligible` recompute."

        Design: Difficulty/combinatorial_formula/productivity_per_line_rounding_order
        """
        ctx = setup_basic_scenario()
        tech = ctx["tech"]
        b2 = create_bed(ctx["unit"]["id"], "B2", "STANDARD")
        b3 = create_bed(ctx["unit"]["id"], "B3", "STANDARD")

        for bed_id in (ctx["bed"]["id"], b2["id"], b3["id"]):
            r = create_request(bed_id, "ROUTINE")
            assign_request(r["id"], tech["id"])
            start_request(r["id"], tech["id"])
            # Advance 40 minutes per clean.
            now = get_success_data(api.get_clean_request(r["id"], ANY))["started_at"]
            hh, mm = int(now[11:13]), int(now[14:16])
            total = hh * 60 + mm + 40
            set_clock(f"2026-08-01T{total // 60:02d}:{total % 60:02d}:00Z")
            complete_request(r["id"], tech["id"])
            submit_audit(r["id"], ctx["auditor"]["id"], rlu_reading=100)

        prod = get_success_data(api.get_staff_productivity(tech["id"], ANY))
        assert prod["completed_clean_count"] == 3
        assert prod["verified_credit_total"] == pytest.approx(3.39, abs=0.005)
