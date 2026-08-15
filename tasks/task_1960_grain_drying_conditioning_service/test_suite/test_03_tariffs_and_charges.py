"""Tariff windows and the drying charge: brackets, surcharge, floor,
closed-window overlap, charge preview, and issue pins (PRD §3.3, §2.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_charge_schedule_payload,
    create_draft_invoice,
    create_lot,
    create_schedule,
    create_tested_lot,
    get_invoice,
    setup_base,
    setup_dried_lot_scenario,
    validate_error,
    validate_success,
)


def _preview(api, lot_id, headers):
    return validate_success(api.get_charge_preview(lot_id, headers), 200)


class TestTieredBracketSurchargeFloor:
    """Combinatorial drying charge: bracket selection + FM surcharge + floor."""

    def _setup_lot(self, fm):
        ctx = setup_base(with_schedule=True, with_unit=False)
        lot, _test = create_tested_lot(
            ctx["cust"]["id"], sample_moisture_pct=22.5,
            target_moisture_pct=15.0, foreign_material_pct=fm,
            gross_weight_lbs=44000, tare_weight_lbs=34000)
        return ctx, lot

    def test_bracket_selection_points_and_surcharge_flag(self, api, manager_headers):
        """PRD §3.3: "Points removed are the lot's `intake_moisture_pct` minus
        its `target_moisture_pct`, floored at zero. The bracket rate is
        `rate_t1_cents_per_pt_bu` when the intake is at most
        `t1_max_moisture_pct`, `rate_t2_cents_per_pt_bu` when the intake exceeds
        the first edge but is at most `t2_max_moisture_pct`, and
        `rate_t3_cents_per_pt_bu` when the intake exceeds the second edge —
        bracket edges are inclusive downward."
        PRD §3.3: "When the lot's `foreign_material_pct` is strictly greater than
        the schedule's `fm_threshold_pct`, the subtotal is multiplied by one plus
        `fm_surcharge_pct`."

        Design: Difficulty/combinatorial_formula/drying_charge_tiered_bracket_surcharge_floor
        """
        ctx, lot = self._setup_lot(fm=4.2)
        preview = _preview(api, lot["id"], manager_headers)
        assert preview["points_removed"] == pytest.approx(7.5)
        assert preview["rate_cents_per_pt_bu"] == 5  # T2: 20.0 < 22.5 <= 25.0
        assert preview["fm_surcharge_applied"] is True  # 4.2 > 3.0
        assert preview["schedule_id"] == ctx["sched"]["id"]

    def test_charge_amount_combines_bracket_surcharge_floor(self, api, manager_headers):
        """PRD §3.3: "Bushels are the lot's `wet_net_weight_lbs` divided by the
        commodity's pounds per bushel — 56 for CORN, 60 for SOYBEAN, 60 for
        WHEAT — carried at full precision with no rounding."
        PRD §3.3: "The charge is the resulting amount rounded half up to whole
        cents, then raised to `min_charge_cents` if it falls below — the floor
        applies last."

        Design: Difficulty/combinatorial_formula/drying_charge_tiered_bracket_surcharge_floor
        """
        _ctx, lot = self._setup_lot(fm=4.2)
        preview = _preview(api, lot["id"], manager_headers)
        # 178.571428... bu * 7.5 pt * 5c = 6696.43 -> x1.10 = 7366.07 -> 7366
        assert preview["drying_charge_cents"] == 7366


class TestMoistureBracketEdge:
    """Inclusive-downward bracket edges: 20.0 bills T1, 20.1 bills T2."""

    def _two_edge_lots(self):
        ctx = setup_base(with_schedule=True, with_unit=False)
        lot1, _ = create_tested_lot(
            ctx["cust"]["id"], sample_moisture_pct=20.0, target_moisture_pct=15.0,
            foreign_material_pct=2.0, gross_weight_lbs=39600, tare_weight_lbs=34000)
        lot2, _ = create_tested_lot(
            ctx["cust"]["id"], sample_moisture_pct=20.1, target_moisture_pct=15.0,
            foreign_material_pct=2.0, gross_weight_lbs=39600, tare_weight_lbs=34000)
        return lot1, lot2

    def test_intake_exactly_at_bracket_edge_bills_lower_rate(self, api, manager_headers):
        """PRD §3.3: "The bracket rate is `rate_t1_cents_per_pt_bu` when the
        intake is at most `t1_max_moisture_pct`, `rate_t2_cents_per_pt_bu` when
        the intake exceeds the first edge but is at most `t2_max_moisture_pct`,
        and `rate_t3_cents_per_pt_bu` when the intake exceeds the second edge —
        bracket edges are inclusive downward."

        Design: Difficulty/boundary_precision_check/moisture_bracket_edge_20_0_vs_20_1
        """
        lot1, _lot2 = self._two_edge_lots()
        preview = _preview(api, lot1["id"], manager_headers)
        # 100.0 bu * 5.0 pt * 4c = 2000
        assert preview["rate_cents_per_pt_bu"] == 4
        assert preview["drying_charge_cents"] == 2000

    def test_one_tenth_above_edge_bills_next_bracket(self, api, manager_headers):
        """PRD §3.3: "The bracket rate is `rate_t1_cents_per_pt_bu` when the
        intake is at most `t1_max_moisture_pct`, `rate_t2_cents_per_pt_bu` when
        the intake exceeds the first edge but is at most `t2_max_moisture_pct`,
        and `rate_t3_cents_per_pt_bu` when the intake exceeds the second edge —
        bracket edges are inclusive downward."

        Design: Difficulty/boundary_precision_check/moisture_bracket_edge_20_0_vs_20_1
        """
        lot1, lot2 = self._two_edge_lots()
        preview2 = _preview(api, lot2["id"], manager_headers)
        # 100.0 bu * 5.1 pt * 5c = 2550
        assert preview2["rate_cents_per_pt_bu"] == 5
        assert preview2["drying_charge_cents"] == 2550
        # The 0.1-point step across the inclusive edge moves the charge by 550c.
        preview1 = _preview(api, lot1["id"], manager_headers)
        assert preview2["drying_charge_cents"] - preview1["drying_charge_cents"] == 550


class TestScheduleWindowOverlap:
    def test_touching_closed_windows_overlap_rejected(self, api, manager_headers):
        """PRD §3.3: "Each schedule names its `commodity` and an inclusive date
        window from `effective_from` through `effective_to`; windows for the same
        commodity must not overlap under closed-interval semantics — two windows
        sharing even a single boundary day overlap — and a colliding window is
        rejected with `ERR_SCHEDULE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/schedule_closed_window_overlap
        """
        create_schedule()  # CORN [2026-08-01, 2026-12-31]
        res = api.create_charge_schedule(
            create_charge_schedule_payload(effective_from="2026-12-31",
                                           effective_to="2027-03-31"),
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_SCHEDULE_WINDOW_OVERLAP, expected_status=409)

    def test_window_starting_day_after_inclusive_end_legal(self, api, manager_headers):
        """PRD §3.3: "Each schedule names its `commodity` and an inclusive date
        window from `effective_from` through `effective_to`; windows for the same
        commodity must not overlap under closed-interval semantics — two windows
        sharing even a single boundary day overlap — and a colliding window is
        rejected with `ERR_SCHEDULE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/schedule_closed_window_overlap
        """
        create_schedule()  # CORN [2026-08-01, 2026-12-31]
        res = api.create_charge_schedule(
            create_charge_schedule_payload(effective_from="2027-01-01",
                                           effective_to="2027-03-31"),
            manager_headers,
        )
        created = validate_success(res, 201)
        assert created["effective_from"] == "2027-01-01"


class TestChargePreviewFloorAndGate:
    def test_min_charge_floor_applies(self, api, manager_headers):
        """PRD §3.3: "The charge is the resulting amount rounded half up to
        whole cents, then raised to `min_charge_cents` if it falls below — the
        floor applies last."

        Design: Corner/calculations/min_charge_floor_applies
        """
        ctx = setup_base(with_schedule=True, with_unit=False)
        lot, _ = create_tested_lot(
            ctx["cust"]["id"], sample_moisture_pct=15.2, target_moisture_pct=15.0,
            foreign_material_pct=2.0, gross_weight_lbs=39600, tare_weight_lbs=34000)
        preview = _preview(api, lot["id"], manager_headers)
        assert preview["points_removed"] == pytest.approx(0.2)
        # 100.0 bu * 0.2 pt * 4c = 80c < 1500c floor -> 1500
        assert preview["drying_charge_cents"] == 1500

    def test_charge_preview_requires_certified_test(self, api, manager_headers):
        """PRD §3.3: "A lot's charge-preview read returns the computed figures
        once the lot carries a certified moisture baseline"
        PRD §2.9: "Other state mismatches yield `ERR_INVALID_STATE` (all HTTP
        409)."

        Design: Corner/validations/charge_preview_requires_certified_test
        """
        ctx = setup_base(with_schedule=True, with_unit=False)
        lot = create_lot(ctx["cust"]["id"])  # RECEIVED, no certified baseline
        res = api.get_charge_preview(lot["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestIssueSchedulePin:
    def test_stale_schedule_version_on_issue(self, api, manager_headers):
        """PRD §2.7: "Issuing an invoice observes a tariff rather than the
        invoice itself: the request carries `pinned_schedule_version`, which must
        equal the current version of the charge schedule the draft was composed
        against. A mismatch is rejected with `ERR_STALE_SCHEDULE_VERSION`
        (HTTP 409 — not 412). Revising a schedule's rates bumps that schedule's
        version, which is exactly what breaks outstanding issue pins."

        Design: Corner/validations/stale_schedule_version_on_issue
        """
        ctx = setup_dried_lot_scenario(with_schedule=True)
        sched = ctx["sched"]
        invoice = create_draft_invoice(ctx["cust"]["id"])
        revised = validate_success(api.update_charge_schedule(
            sched["id"], {"rate_t2_cents_per_pt_bu": 6}, manager_headers), 200)
        assert revised["version"] == sched["version"] + 1

        res = api.issue_invoice(
            invoice["id"], {"pinned_schedule_version": sched["version"]}, manager_headers)
        validate_error(res, ApiErrorId.ERR_STALE_SCHEDULE_VERSION, expected_status=409)
        assert get_invoice(invoice["id"])["status"] == "DRAFT"
