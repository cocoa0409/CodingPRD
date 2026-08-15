"""Quality holds: lot blocking, the bloom release gate at 2.00%, the
RELEASE/SCRAP branch divergence, terminal-state lockdown, and the scrap cascade
into the window projection."""
import pytest

from test_helpers import (
    QA,
    ApiErrorId,
    create_quality_hold,
    disposition_hold,
    get_hold,
    get_lot,
    get_window,
    make_line_operator_headers,
    produce_lot,
    setup_active_lot,
    setup_runnable_plant,
    validate_error,
)


def _setup_two_lots(api, units_1=1000, units_2=800, **plant_kwargs):
    """One plant with two ACTIVE lots produced by two runs on separate days."""
    plant = setup_runnable_plant(**plant_kwargs)
    run_1, lot_1 = produce_lot(
        plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
        plant["line"]["id"], planned_units=units_1, output_units=units_1,
        scheduled_start="2026-09-05T08:00:00Z",
        scheduled_end="2026-09-05T16:00:00Z")
    run_2, lot_2 = produce_lot(
        plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
        plant["line"]["id"], planned_units=units_2, output_units=units_2,
        scheduled_start="2026-09-06T08:00:00Z",
        scheduled_end="2026-09-06T16:00:00Z")
    plant.update({"run_1": run_1, "lot_1": lot_1, "run_2": run_2, "lot_2": lot_2})
    return plant


class TestHoldBlocksAndReleaseUnblocks:
    def test_hold_blocks_lot_and_release_trims(self, api):
        """PRD §3.7: "The hold is born `OPEN`, and its creation blocks the lot:
        the lot moves from `ACTIVE` to `BLOCKED`"
        PRD §3.7: "A permitted release moves the hold to `RELEASED` and trims the
        lot: `qty_on_hand` decreases by the hold's `affected_units` and
        `qty_scrapped` increases by the same amount, writing the affected units
        off. The remainder then unblocks — `BLOCKED` back to `ACTIVE`"
        PRD §3.7: "in all three branches the hold stamps `disposition_by` — null
        until this moment — with the manager's `X-User-ID`"

        Design: Corner/state_machines/hold_blocks_and_release_unblocks_lot
        """
        plant = setup_active_lot(output_units=100)
        lot = plant["lot"]

        # Hold creation is shared between QualityManager and LineOperator.
        hold = create_quality_hold(lot["id"], defect_type="FOREIGN_MATERIAL",
                                   affected_units=1,
                                   headers=make_line_operator_headers("op-1"))
        assert hold["status"] == "OPEN"
        assert hold["opened_by"] == "op-1"
        assert hold["disposition_by"] is None
        assert hold["lot_qty_at_open"] == 100
        assert get_lot(lot["id"])["status"] == "BLOCKED"

        disposition_hold(hold["id"], "RELEASE", user_id="qm-1")
        lot = get_lot(lot["id"])
        assert lot["status"] == "ACTIVE"
        assert lot["qty_on_hand"] == 99
        assert lot["qty_scrapped"] == 1
        hold = get_hold(hold["id"])
        assert hold["status"] == "RELEASED"
        assert hold["disposition_by"] == "qm-1"


class TestReleaseScrapBranching:
    def test_release_branch_trims_and_unblocks(self, api):
        """PRD §3.7: "A permitted release moves the hold to `RELEASED` and trims
        the lot: `qty_on_hand` decreases by the hold's `affected_units` and
        `qty_scrapped` increases by the same amount, writing the affected units
        off. The remainder then unblocks — `BLOCKED` back to `ACTIVE`"

        Design: Difficulty/non_linear_state_machine/hold_release_scrap_branching
        """
        plant = _setup_two_lots(api)
        hold = create_quality_hold(plant["lot_1"]["id"], defect_type="BLOOM",
                                   affected_units=19)
        disposition_hold(hold["id"], "RELEASE")

        hold = get_hold(hold["id"])
        assert hold["status"] == "RELEASED"
        lot = get_lot(plant["lot_1"]["id"])
        assert lot["status"] == "ACTIVE"
        assert lot["qty_on_hand"] == 981
        assert lot["qty_scrapped"] == 19

    def test_scrap_branch_writes_off_full_lot(self, api):
        """PRD §3.7: "The lot's full remaining `qty_on_hand` moves into
        `qty_scrapped`, `qty_on_hand` becomes zero, and the lot lands in
        `SCRAPPED` — this applies whether the lot was `ACTIVE` or `BLOCKED` under
        the hold"

        Design: Difficulty/non_linear_state_machine/hold_release_scrap_branching
        """
        plant = _setup_two_lots(api)
        hold = create_quality_hold(plant["lot_2"]["id"], defect_type="BLOOM",
                                   affected_units=16)
        disposition_hold(hold["id"], "SCRAP")

        hold = get_hold(hold["id"])
        assert hold["status"] == "SCRAPPED"
        lot = get_lot(plant["lot_2"]["id"])
        assert lot["status"] == "SCRAPPED"
        assert lot["qty_on_hand"] == 0
        assert lot["qty_scrapped"] == 800


class TestBloomReleaseGate:
    def test_release_forbidden_at_exactly_two_percent(self, api):
        """PRD §3.7: "`defect_rate_pct` is one hundred times `affected_units`
        divided by `lot_qty_at_open`, rounded half-up to two decimal places."
        PRD §3.7: "for a `BLOOM` hold, release is only permitted when the rounded
        `defect_rate_pct` is below 2.00 percent — at 2.00 percent or worse,
        release is rejected with `ERR_BLOOM_RELEASE_FORBIDDEN` and only scrap or
        rework remain on the table"

        Design: Difficulty/boundary_precision_check/bloom_rate_two_percent_boundary
        """
        plant = _setup_two_lots(api, units_1=1000, units_2=1000)
        hold_1 = create_quality_hold(plant["lot_1"]["id"], defect_type="BLOOM",
                                     affected_units=20)
        assert hold_1["defect_rate_pct"] == pytest.approx(2.0), (
            "20 / 1000 sits exactly at the threshold")

        resp = api.disposition_quality_hold(hold_1["id"], {"action": "RELEASE"},
                                            QA)
        validate_error(resp, ApiErrorId.ERR_BLOOM_RELEASE_FORBIDDEN)
        assert get_hold(hold_1["id"])["status"] == "OPEN"
        assert get_lot(plant["lot_1"]["id"])["status"] == "BLOCKED"

    def test_release_permitted_just_below_two_percent(self, api):
        """PRD §3.7: "for a `BLOOM` hold, release is only permitted when the
        rounded `defect_rate_pct` is below 2.00 percent"

        Design: Difficulty/boundary_precision_check/bloom_rate_two_percent_boundary
        """
        plant = _setup_two_lots(api, units_1=1000, units_2=1000)
        hold_2 = create_quality_hold(plant["lot_2"]["id"], defect_type="BLOOM",
                                     affected_units=19)
        assert hold_2["defect_rate_pct"] == pytest.approx(1.9), (
            "19 / 1000 sits just below the threshold")

        disposition = disposition_hold(hold_2["id"], "RELEASE")
        assert disposition["status"] == "RELEASED"
        lot = get_lot(plant["lot_2"]["id"])
        assert lot["status"] == "ACTIVE"
        assert lot["qty_on_hand"] == 981
        assert lot["qty_scrapped"] == 19


class TestTerminalLockdown:
    def test_disposition_from_released_rejected(self, api):
        """PRD §3.7: "Disposition belongs to the `QualityManager` alone, who
        supplies an `action` of `RELEASE`, `SCRAP`, or `REWORK` on a hold that
        must be `OPEN` (otherwise `ERR_INVALID_STATE`)"
        PRD §3.7: "`RELEASED`, `SCRAPPED`, and `CLOSED_REWORK` are all terminal
        for the hold."

        Design: Corner/state_machines/hold_disposition_from_terminal_rejected
        """
        plant = setup_active_lot(output_units=100)
        hold = create_quality_hold(plant["lot"]["id"], defect_type="BLOOM",
                                   affected_units=1)
        disposition_hold(hold["id"], "RELEASE")
        assert get_hold(hold["id"])["status"] == "RELEASED"

        resp = api.disposition_quality_hold(hold["id"], {"action": "SCRAP"}, QA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_hold(hold["id"])["status"] == "RELEASED"
        lot = get_lot(plant["lot"]["id"])
        assert lot["status"] == "ACTIVE"
        assert lot["qty_on_hand"] == 99


class TestScrapCascade:
    def _setup_blocked_lot(self, api):
        """HOLIDAY window (target 10000) with one 4000-unit ACTIVE lot, blocked
        by an OPEN bloom hold (affected 40, rate 1.00)."""
        plant = setup_active_lot(output_units=4000, product_type="SEASONAL",
                                 sku_code="TRUFFLE-24", base_price_cents=1000,
                                 shelf_life_days=180, season_code="HOLIDAY",
                                 target_units=10000)
        hold = create_quality_hold(plant["lot"]["id"], defect_type="BLOOM",
                                   affected_units=40)
        return plant, hold

    def test_scrap_disposition_terminates_hold_and_lot(self, api):
        """PRD §3.7: "The lot's full remaining `qty_on_hand` moves into
        `qty_scrapped`, `qty_on_hand` becomes zero, and the lot lands in
        `SCRAPPED`" and "The hold becomes `SCRAPPED`"

        Design: Difficulty/transitive_cascade/scrap_disposition_cascades_to_window_shortfall
        """
        plant, hold = self._setup_blocked_lot(api)
        disposition_hold(hold["id"], "SCRAP")

        hold = get_hold(hold["id"])
        assert hold["status"] == "SCRAPPED"
        lot = get_lot(plant["lot"]["id"])
        assert lot["status"] == "SCRAPPED"
        assert lot["qty_on_hand"] == 0
        assert lot["qty_scrapped"] == 4000

    def test_scrap_cascade_flips_window_shortfall(self, api):
        """PRD §3.7: "the window projection is recomputed with its `version`
        incremented, and the write-off may be exactly what flips the window's
        `shortfall` to true."
        PRD §3.4: "The confirmed variant — the post-production truth — sets
        `confirmed_build_units` to the sum of `qty_on_hand` over exactly those
        lots whose producing run belongs to this window and whose `status` is
        `ACTIVE`; blocked, depleted, and scrapped lots contribute nothing."

        Design: Difficulty/transitive_cascade/scrap_disposition_cascades_to_window_shortfall
        """
        plant = setup_active_lot(output_units=4000, product_type="SEASONAL",
                                 sku_code="TRUFFLE-24", base_price_cents=1000,
                                 shelf_life_days=180, season_code="HOLIDAY",
                                 target_units=10000)
        window = get_window(plant["window"]["id"])
        assert window["confirmed_build_units"] == 4000, (
            "the ACTIVE lot counts toward the confirmed build before the hold")
        assert window["shortfall"] is True  # 4000 < 10000

        hold = create_quality_hold(plant["lot"]["id"], defect_type="BLOOM",
                                   affected_units=40)
        disposition_hold(hold["id"], "SCRAP")

        window = get_window(plant["window"]["id"])
        assert window["confirmed_build_units"] == 0, (
            "scrapped lots contribute nothing after the disposition cascade")
        assert window["shortfall"] is True, "0 < target 10000"
