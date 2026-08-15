"""Quality control: reject-rate boundary (strictly-greater HOLD), segregation
of duties, double-decision priority, and the order-level repress cycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_qc_report,
    create_queued_order,
    create_release,
    decide_qc_report,
    file_qc_report,
    get_order,
    issue_standard_invoice,
    make_pm_headers,
    press_run,
    schedule_order,
    setup_world,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CSR, PM


def _two_splatter_orders_in_qc_review(world):
    """Two SPLATTER orders (tolerance 8.0) on adjacent same-family slots,
    both driven to QC_REVIEW."""
    line_id = world["line"]["id"]
    rel2 = create_release(world["customer"]["id"], catalog_number="BP2-002",
                          title="TB2b", weight_gram=140)
    variants = [{"color_config": "SPLATTER", "quantity": 100}]
    o1 = create_queued_order(world, quantity_ordered=100, variants=variants)["order"]
    schedule_order(o1, line_id, date="2026-08-10", start_hour=0, end_hour=1,
                   planned_units=100)
    o2 = create_queued_order(world, release=rel2, quantity_ordered=100,
                             variants=variants)["order"]
    schedule_order(o2, line_id, date="2026-08-10", start_hour=1, end_hour=2,
                   planned_units=100)
    press_run(o1["id"], slot_date="2026-08-10")
    press_run(o2["id"], slot_date="2026-08-10")
    return o1, o2


class TestRejectRateBoundary:
    def test_reject_rate_equal_to_tolerance_passes(self, api):
        """PRD §3.7: "The `outcome` is `HOLD` exactly when that rate is
        strictly greater than the snapshot tolerance; a rate equal to the
        tolerance still yields `PASS`."
        PRD §3.7: "The system records the filer's identity in `filed_by`,
        snapshots the order's current tolerance into `tolerance_pct_snapshot`,
        and computes the `reject_rate_pct` — one hundred times the rejected
        units divided by the pressed units, rounded half-up to two decimal
        places."

        Design: Difficulty/boundary_precision_check/reject_rate_strictly_greater_boundary
        """
        world = setup_world(release_over={"weight_gram": 140})
        o1, _o2 = _two_splatter_orders_in_qc_review(world)
        qc = file_qc_report(o1["id"], 100, 8)
        assert_qc_report(qc)
        assert qc["tolerance_pct_snapshot"] == pytest.approx(8.0)
        assert qc["reject_rate_pct"] == pytest.approx(8.0)
        assert qc["outcome"] == "PASS", (
            "a rate exactly equal to the tolerance must PASS (HOLD is strictly greater)"
        )
        assert qc["status"] == "FILED"
        assert qc["filed_by"] == "qa-1"

    def test_reject_rate_above_tolerance_hold_blocks_accept(self, api):
        """PRD §3.7: "The `outcome` is `HOLD` exactly when that rate is
        strictly greater than the snapshot tolerance; a rate equal to the
        tolerance still yields `PASS`."
        PRD §3.7: "A `decision` of `ACCEPT` is lawful only when the outcome is
        `PASS` — accepting a `HOLD` report is rejected with
        `ERR_QC_HOLD_REQUIRES_REPRESS`"

        Design: Difficulty/boundary_precision_check/reject_rate_strictly_greater_boundary
        """
        world = setup_world(release_over={"weight_gram": 140})
        _o1, o2 = _two_splatter_orders_in_qc_review(world)
        qc = file_qc_report(o2["id"], 100, 9)
        assert qc["reject_rate_pct"] == pytest.approx(9.0)
        assert qc["outcome"] == "HOLD"

        resp = api.decide_qc_report(
            qc["id"], {"decision": "ACCEPT", "fault": "NONE"}, PM
        )
        validate_error(resp, ApiErrorId.ERR_QC_HOLD_REQUIRES_REPRESS)


class TestSegregationOfDuties:
    def _qc_review_with_report(self, world):
        staged = create_queued_order(world, quantity_ordered=1000)
        order = schedule_order(staged["order"], world["line"]["id"],
                               planned_units=1000)
        press_run(order["id"])
        qc = file_qc_report(order["id"], 1000, 30, filer="qa-1")
        return order, qc

    def test_sod_same_user_decision_rejected(self, api):
        """PRD §3.7: "The decision belongs to a `ProductionManager`, and never
        to the filer: if the deciding `X-User-ID` matches the report's
        `filed_by`, the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`,
        and the deciding identity is recorded as `decided_by`."

        Design: Corner/validations/sod_same_user_decision_rejected
        """
        world = setup_world()
        _order, qc = self._qc_review_with_report(world)
        assert qc["filed_by"] == "qa-1"

        # Same identity under the ProductionManager role -> SoD rejection.
        resp = api.decide_qc_report(
            qc["id"], {"decision": "ACCEPT", "fault": "NONE"},
            make_pm_headers("qa-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        qcs = validate_success(api.list_order_qc_reports(_order["id"], CSR), 200)
        assert qcs[0]["status"] == "FILED", "a rejected decision must not decide the report"

        decided = decide_qc_report(qc["id"], "ACCEPT", "NONE", decider="pm-2")
        assert decided["status"] == "DECIDED"
        assert decided["decided_by"] == "pm-2"

    def test_state_beats_sod_double_decision_by_filer(self, api):
        """PRD §2.9: "5. State preconditions — the target resource is not in
        the exact from-state the requested transition requires, rejected with
        `ERR_ORDER_INVALID_STATE`, `ERR_TOOLING_JOB_INVALID_STATE`,
        `ERR_TEST_PRESSING_INVALID_STATE`, `ERR_PRINT_JOB_INVALID_STATE`,
        `ERR_QC_REPORT_ALREADY_DECIDED`, `ERR_SHIPMENT_INVALID_STATE`, or
        `ERR_INVOICE_INVALID_STATE` as appropriate to the resource."
        PRD §2.9: "6. Segregation of duties — a quality decision attempted by
        the inspector who filed the report, rejected with
        `ERR_SEGREGATION_OF_DUTIES`; this check applies only to quality
        decisions."
        PRD §2.9: "the ordering above is normative, not illustrative."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_sod_on_qc_decision
        """
        world = setup_world()
        _order, qc = self._qc_review_with_report(world)
        decide_qc_report(qc["id"], "ACCEPT", "NONE", decider="pm-1")

        # Second decision by the filer violates both the FILED-state gate and
        # segregation of duties; the state error (priority 5) must win.
        resp = api.decide_qc_report(
            qc["id"], {"decision": "REPRESS", "fault": "PLANT"},
            make_pm_headers("qa-1"),
        )
        validate_error(resp, ApiErrorId.ERR_QC_REPORT_ALREADY_DECIDED)

    def test_state_gate_double_decision_by_other_manager(self, api):
        """PRD §3.7: "Deciding a report already `DECIDED` is
        `ERR_QC_REPORT_ALREADY_DECIDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_sod_on_qc_decision
        """
        world = setup_world()
        _order, qc = self._qc_review_with_report(world)
        decide_qc_report(qc["id"], "ACCEPT", "NONE", decider="pm-1")

        resp = api.decide_qc_report(
            qc["id"], {"decision": "REPRESS", "fault": "PLANT"},
            make_pm_headers("pm-2"),
        )
        validate_error(resp, ApiErrorId.ERR_QC_REPORT_ALREADY_DECIDED)


class TestRepressCycle:
    def _run_repress_cycle(self, world):
        """Run 1: 1000 pressed / 100 rejected (10.00 > 5.0 HOLD) -> REPRESS
        PLANT. Top-up slot. Run 2: 100 pressed / 0 rejected -> ACCEPT."""
        line_id = world["line"]["id"]
        staged = create_queued_order(world, quantity_ordered=1000)
        order = schedule_order(staged["order"], line_id, date="2026-08-10",
                               start_hour=0, end_hour=8, planned_units=1000)
        press_run(order["id"], slot_date="2026-08-10")
        qc1 = file_qc_report(order["id"], 1000, 100)
        assert qc1["outcome"] == "HOLD"
        decide_qc_report(qc1["id"], "REPRESS", "PLANT", decider="pm-1")

        mid = get_order(order["id"])
        assert mid["production_status"] == "QUEUED"

        # Repress top-up commit covers only the 100-unit shortfall.
        order = schedule_order(mid, line_id, date="2026-08-11",
                               start_hour=0, end_hour=4, planned_units=100)
        press_run(order["id"], slot_date="2026-08-11")
        qc2 = file_qc_report(order["id"], 100, 0)
        assert qc2["outcome"] == "PASS"
        decide_qc_report(qc2["id"], "ACCEPT", "NONE", decider="pm-1")
        return order["id"], qc1, qc2

    def test_repress_cycle_banks_good_units(self, api):
        """PRD §3.7: "Repress loops the order `QC_REVIEW` → `QUEUED`:
        `repress_round` increments, `repress_fault` records the fault, the
        run's pressed and rejected totals accumulate as on acceptance, and the
        run's good units are banked into `accepted_units` — the repress
        re-covers only the rejected shortfall, never the good units."

        Design: Difficulty/non_linear_state_machine/press_order_repress_cycle
        """
        world = setup_world()
        line_id = world["line"]["id"]
        staged = create_queued_order(world, quantity_ordered=1000)
        order = schedule_order(staged["order"], line_id, date="2026-08-10",
                               start_hour=0, end_hour=8, planned_units=1000)
        press_run(order["id"], slot_date="2026-08-10")
        qc1 = file_qc_report(order["id"], 1000, 100)
        assert qc1["outcome"] == "HOLD", "10.00 > 5.0 must HOLD"
        decide_qc_report(qc1["id"], "REPRESS", "PLANT", decider="pm-1")

        mid = get_order(order["id"])
        assert mid["production_status"] == "QUEUED", (
            "REPRESS must loop the order back to QUEUED"
        )
        assert mid["accepted_units"] == 900, (
            f"900 good units from run 1 must be banked, got {mid['accepted_units']}"
        )
        assert mid["repress_round"] == 1
        assert mid["repress_fault"] == "PLANT"
        assert mid["pressed_units_total"] == 1000
        assert mid["rejected_units_total"] == 100

        order = schedule_order(mid, line_id, date="2026-08-11",
                               start_hour=0, end_hour=4, planned_units=100)
        press_run(order["id"], slot_date="2026-08-11")
        qc2 = file_qc_report(order["id"], 100, 0)
        assert qc2["outcome"] == "PASS"
        decide_qc_report(qc2["id"], "ACCEPT", "NONE", decider="pm-1")

        final = get_order(order["id"])
        assert final["production_status"] == "COMPLETED"
        assert final["accepted_units"] == 1000
        assert final["repress_round"] == 1

    def test_repress_cycle_invoice_plant_credit(self, api):
        """PRD §3.9: "The repress line carries a flat 150000-cent adjustment
        per repress round, charged against the plant when `repress_fault` is
        `PLANT` (a negative line) and passed to the customer when it is
        `CUSTOMER` (a positive line); no repress, no line adjustment."
        PRD §3.9: "The tooling gross is the quoted `quote_tooling_cents`, plus,
        when the latest repress fault was `CUSTOMER`, one 30000-cent stamper
        fee per side for each repress round."

        Design: Difficulty/non_linear_state_machine/press_order_repress_cycle
        """
        world = setup_world()
        order_id, _qc1, _qc2 = self._run_repress_cycle(world)
        invoice = issue_standard_invoice(order_id)
        # Billed = min(accepted 1000, floor(1000*1.10)) = 1000:
        # pressing 288420 + surcharge 25000 + tooling 95000 + setup 40000
        # + repress (-150000 PLANT) = 298420. No extra stamper fee for PLANT.
        assert invoice["net_cents"] == 298420
        assert invoice["gross_cents"] == 298420
        repress_lines = [l for l in invoice["lines"] if l["gross_cents"] == -150000]
        assert len(repress_lines) == 1, (
            "the invoice must carry one -150000 PLANT-fault repress credit line"
        )
