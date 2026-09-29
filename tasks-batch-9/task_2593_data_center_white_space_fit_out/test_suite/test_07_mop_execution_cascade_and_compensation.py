"""Executing a change against a busway cascades four links deep, and closing or
backing it out compensates every one of them exactly."""
import pytest

from test_helpers.constants import USER_IDS
from test_helpers.fixtures import (
    add_powered_rack,
    advance_phase,
    back_out_mop,
    create_tenant,
    execute_mop,
    prove_zone_and_cooling,
    read_busway,
    read_cage,
    read_feed,
    read_hall,
    read_mop,
    read_rack,
    set_clock,
    setup_fit_out_hall,
    setup_scheduled_mop,
    setup_secured_cage,
)

AUTHOR = USER_IDS["ELECTRICAL_CONTRACTOR"]
WINDOW_START = "2026-08-05T02:00:00Z"
WINDOW_END = "2026-08-05T06:00:00Z"
INSIDE_WINDOW = "2026-08-05T02:30:00Z"


def _commissioning_hall_with_caged_powered_rack(code, tenant_code):
    """One SECURED cage holding one POWERED dual-corded rack in a COMMISSIONING hall."""
    tenant = create_tenant(tenant_code, contracted_kw=100.00)
    ctx = setup_fit_out_hall(code, tenant_mode="MULTI_TENANT")
    ctx["tenant"] = tenant
    cage_ctx = setup_secured_cage(
        ctx["hall_id"],
        tenant["id"],
        perimeter_length_m=40.0,
        camera_coverage_m=38.0,
        reader_zones=("Z-N", "Z-S"),
    )
    ctx.update(cage_ctx)
    prove_zone_and_cooling(ctx)
    add_powered_rack(
        ctx,
        design_kw=15.00,
        feed_kw=7.50,
        asset_tag="AT-0001",
        cage_id=cage_ctx["cage_id"],
        tenant_id=tenant["id"],
    )
    advance_phase(ctx["hall_id"], "COMMISSIONING")
    ctx["mop"] = setup_scheduled_mop(
        ctx["hall_id"],
        "BUSWAY",
        ctx["bw_a"]["id"],
        risk_class="MEDIUM",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        author_user_id=AUTHOR,
    )
    return ctx


class TestBuswayIsolationCascade:
    """Isolating one run moves the run, its feeds, the racks that lost redundancy and
    the cages those racks sit in."""

    def test_execution_isolates_the_run_and_degrades_the_cage_four_links_down(self):
        """Executing the change captures the run's state, isolates it, derates only the
        feed on that run, drops the dual-corded rack to AT_RISK with its prior status
        remembered, and degrades the cage holding it.

        PRD: "any rack whose energised feed count now falls below its
        `required_feed_count` records its current status in `pre_risk_status` and moves
        to `AT_RISK` — from `POWERED` or from `RELEASED`, whichever it held."

        Design: Difficulty/transitive_cascade/mop_execute_busway_isolation_cascade_depth_four
        """
        ctx = _commissioning_hall_with_caged_powered_rack("HI1", "TN-I1")
        set_clock(INSIDE_WINDOW)
        executed = execute_mop(ctx["mop"]["id"], AUTHOR)

        assert executed["status"] == "IN_EXECUTION"
        assert executed["executed_at"] == INSIDE_WINDOW
        assert executed["pre_execution_target_state"] == "ENERGIZED", (
            "the run's status is captured verbatim so it can be put back"
        )
        assert read_busway(ctx["bw_a"]["id"])["status"] == "ISOLATED"
        assert read_busway(ctx["bw_b"]["id"])["status"] == "ENERGIZED", (
            "the untargeted run is untouched"
        )
        assert read_feed(ctx["rack_1_feed_a"]["id"])["status"] == "DERATED"
        assert read_feed(ctx["rack_1_feed_b"]["id"])["status"] == "ENERGIZED"

        rack = read_rack(ctx["rack_1"]["id"])
        assert rack["status"] == "AT_RISK"
        assert rack["pre_risk_status"] == "POWERED"
        assert rack["energized_feed_count"] == 1
        assert read_cage(ctx["cage_id"])["operational_status"] == "DEGRADED"

    def test_the_isolation_locks_the_room_without_moving_the_ledger(self):
        """A derated feed still counts, so committed load and the run's own committed
        figure are unchanged; the custody partition swings to the fit-out side and the
        release posture becomes LOCKED.

        PRD: "a derated feed still counts toward that run's `committed_kw` and toward
        the hall's `committed_kw`, so the ledger does not move."

        Design: Difficulty/transitive_cascade/mop_execute_busway_isolation_cascade_depth_four
        """
        ctx = _commissioning_hall_with_caged_powered_rack("HI2", "TN-I2")
        set_clock(INSIDE_WINDOW)
        execute_mop(ctx["mop"]["id"], AUTHOR)

        hall = read_hall(ctx["hall_id"])
        assert hall["committed_kw"] == pytest.approx(15.00, abs=0.005)
        assert read_busway(ctx["bw_a"]["id"])["committed_kw"] == pytest.approx(
            7.500, abs=0.0005
        )
        assert hall["at_risk_rack_count"] == 1
        assert hall["custody_ops_count"] == 0
        assert hall["custody_fitout_count"] == 1
        assert hall["rack_total_count"] == 1
        assert hall["release_posture"] == "LOCKED", (
            "an executing change outranks every other posture branch"
        )
        assert hall["open_mop_count"] == 1
        assert hall["thermal_load_kw"] == pytest.approx(12.75, abs=0.005), (
            "an at-risk rack still contributes heat to the demand figure"
        )
        assert hall["status"] == "COMMISSIONING"


class TestBackOutCompensatesTheCascade:
    """Backing out is the exact inverse of execution, custody counters included."""

    def test_back_out_restores_every_link_of_the_cascade(self):
        """The run returns to the captured ENERGIZED state, both feeds re-energise, the
        rack returns to the status pre_risk_status recorded with that field cleared, and
        the cage returns to SECURED.

        PRD: "Each rack at `AT_RISK` whose energised feed count is once more equal to
        its `required_feed_count` returns to whatever `pre_risk_status` recorded — to
        `POWERED` if that is what it held, or to `RELEASED` if that is what it held —
        and `pre_risk_status` is cleared back to null."

        Design: Difficulty/compensating_invariant/mop_execute_then_back_out_conserves_rack_custody_counts
        """
        ctx = _commissioning_hall_with_caged_powered_rack("HT1", "TN-T1")
        set_clock(INSIDE_WINDOW)
        execute_mop(ctx["mop"]["id"], AUTHOR)

        backed_out = back_out_mop(ctx["mop"]["id"], AUTHOR, note="abandoned")
        assert backed_out["status"] == "BACKED_OUT"
        assert backed_out["closed_at"] == INSIDE_WINDOW

        assert read_busway(ctx["bw_a"]["id"])["status"] == "ENERGIZED"
        assert read_feed(ctx["rack_1_feed_a"]["id"])["status"] == "ENERGIZED"
        assert read_feed(ctx["rack_1_feed_b"]["id"])["status"] == "ENERGIZED"
        rack = read_rack(ctx["rack_1"]["id"])
        assert rack["status"] == "POWERED"
        assert rack["pre_risk_status"] is None
        assert rack["energized_feed_count"] == 2
        assert read_cage(ctx["cage_id"])["operational_status"] == "SECURED"

    def test_custody_counters_land_exactly_on_their_pre_execution_values(self):
        """Every hall figure the cascade touched — the custody partition, the at-risk
        count, the ledger, the chargeable roll-up, the demand figure and the release
        posture — reads exactly as it did before the change ran.

        PRD: "Finally the custody partition and the release posture are re-derived, and
        the custody counts land exactly on their pre-execution values — that identity is
        the test of whether the compensation was complete."

        Design: Difficulty/compensating_invariant/mop_execute_then_back_out_conserves_rack_custody_counts
        """
        ctx = _commissioning_hall_with_caged_powered_rack("HT2", "TN-T2")
        before = read_hall(ctx["hall_id"])
        assert before["custody_ops_count"] == 1
        assert before["custody_fitout_count"] == 0

        set_clock(INSIDE_WINDOW)
        execute_mop(ctx["mop"]["id"], AUTHOR)
        back_out_mop(ctx["mop"]["id"], AUTHOR, note="abandoned")

        after = read_hall(ctx["hall_id"])
        assert after["custody_ops_count"] == before["custody_ops_count"]
        assert after["custody_fitout_count"] == before["custody_fitout_count"]
        assert after["at_risk_rack_count"] == 0
        assert after["committed_kw"] == pytest.approx(15.00, abs=0.005)
        assert after["chargeable_kw"] == pytest.approx(15.68, abs=0.005), (
            "15.00 kW at the 1.045 overhead factor"
        )
        assert after["thermal_load_kw"] == pytest.approx(12.75, abs=0.005)
        assert after["release_posture"] == "OPEN"
        assert after["open_mop_count"] == 0, (
            "a backed-out change is terminal and occupies no window"
        )
        assert after["status"] == "COMMISSIONING"
        assert read_mop(ctx["mop"]["id"])["status"] == "BACKED_OUT"
