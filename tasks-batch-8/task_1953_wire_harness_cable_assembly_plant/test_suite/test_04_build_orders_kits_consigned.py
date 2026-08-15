"""Build orders, kits, and consigned lots: release-to-kitting gating, OCC on
order edits, issue-time business rules (substitution, mpn, on-hand, over-issue,
budget), shortage derivation, kit state gates, and lot bucket reconciliation."""
from test_helpers import (
    ApiErrorId,
    assert_consigned_lot,
    assert_consigned_lot_conservation,
    assert_kit,
    deliver_kit,
    get_success_data,
    get_order_kit,
    issue_line,
    make_build_order,
    make_consigned_lot,
    make_released_drawing,
    release_order_to_kitting,
    setup_order_in_build,
    setup_qualified_line,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers import make_line_operator_headers

PLAN = TEST_USERS["production_planner_headers"]
MAT = TEST_USERS["materials_clerk_headers"]

CONSIGNED_BOM = [
    {"find_number": "C1", "component_type": "CONNECTOR", "mpn": "CON-500",
     "qty_per_harness": 1, "supply_type": "CUSTOMER_CONSIGNED", "unit_cost_cents": 450},
]
TWO_LINE_BOM = [
    {"find_number": "T1", "component_type": "TERMINAL", "mpn": "TERM-20",
     "qty_per_harness": 2, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 100},
    {"find_number": "W1", "component_type": "WIRE", "mpn": "WIRE-20",
     "qty_per_harness": 1, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 50},
]


class TestKitShortageAndStaging:
    def test_kit_auto_stage_on_zero_shortage(self, api):
        """PRD §3.6: "When the shortage reaches zero and at least one non-voided issue exists, the kit moves `PICKING → STAGED` on its own."
        PRD §3.6: "Every accepted issue recomputes the kit's `shortage_count` — summed over the pinned BOM lines, the amount by which each line's needed quantity exceeds its non-voided issued quantity, with negative differences counting as zero — and refreshes the order's `material_spent_cents` and `actual_cost_cents`."

        Design: Corner/state_machines/c_kit_auto_stage_on_zero_shortage
        """
        ctx = setup_order_in_build(
            api, tag="S3", qty_ordered=1, issue_plan=[], deliver=False,
            line_kwargs={"bom": TWO_LINE_BOM},
        )
        kit = ctx["kit"]
        components = ctx["line"]["components"]
        # Needed: T1 x2 and W1 x1 -> total 3. First issue leaves shortage 1.
        kit = issue_line(api, kit["id"], components["T1"]["id"], 2, "FACTORY_STOCK")
        assert_kit(kit)
        assert kit["status"] == "PICKING", f"kit keeps picking while shortage > 0: {kit}"
        assert kit["shortage_count"] == 1, f"shortage recomputes to 3 - 2 = 1: {kit}"
        # The completing issue drives the shortage to exactly zero: auto-stage.
        kit = issue_line(api, kit["id"], components["W1"]["id"], 1, "FACTORY_STOCK")
        assert kit["status"] == "STAGED", f"zero shortage with an issue present auto-stages: {kit}"
        assert kit["shortage_count"] == 0, f"shortage is exactly zero: {kit}"

    def test_kit_state_gates(self, api):
        """PRD §3.6: "Delivering a kit, again a `MaterialsClerk` action, requires the kit be `STAGED` (otherwise `ERR_KIT_NOT_STAGED`)."
        PRD §3.6: "Recording an issue requires the kit to be `PICKING` (otherwise `ERR_KIT_NOT_PICKING`)"

        Design: Corner/state_machines/c_kit_state_gates
        """
        ctx = setup_order_in_build(api, tag="S4", qty_ordered=1, issue_plan=[], deliver=False)
        kit = ctx["kit"]
        components = ctx["line"]["components"]
        deliver_early = api.deliver_kit(kit["id"], MAT)
        validate_error(deliver_early, ApiErrorId.ERR_KIT_NOT_STAGED)
        issue_line(api, kit["id"], components["T1"]["id"], 1, "FACTORY_STOCK")
        issue_after_stage = api.create_kit_issue(
            kit["id"],
            {"component_id": components["T1"]["id"], "qty_issued": 1, "source": "FACTORY_STOCK"},
            MAT,
        )
        validate_error(issue_after_stage, ApiErrorId.ERR_KIT_NOT_PICKING)

    def test_kit_shortage_partial_issue_recompute(self, api):
        """PRD §3.5: "its `kit_seq` is one greater than the count of the order's existing kits, its status is `PICKING`, its `issues` list is empty, and its `shortage_count` initializes to the total needed across the pinned BOM — for each BOM line, `qty_per_harness` multiplied by the order's `qty_ordered`, summed."
        PRD §3.6: "Every accepted issue recomputes the kit's `shortage_count` — summed over the pinned BOM lines, the amount by which each line's needed quantity exceeds its non-voided issued quantity, with negative differences counting as zero — and refreshes the order's `material_spent_cents` and `actual_cost_cents`."

        Design: Corner/calculations/c_kit_shortage_partial_issue_recompute
        """
        bom = [
            {"find_number": "T1", "component_type": "TERMINAL", "mpn": "TERM-20",
             "qty_per_harness": 4, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 100},
        ]
        ctx = setup_order_in_build(
            api, tag="C3", qty_ordered=1, issue_plan=[], deliver=False,
            line_kwargs={"bom": bom},
        )
        kit = ctx["kit"]
        assert kit["shortage_count"] == 4, (
            f"initial shortage equals total needed (qty_per_harness 4 x qty_ordered 1): {kit}"
        )
        kit = issue_line(api, kit["id"], ctx["line"]["components"]["T1"]["id"], 1, "FACTORY_STOCK")
        assert kit["shortage_count"] == 3, f"issue response recomputes shortage to 3: {kit}"
        reread = get_success_data(api.get_kit(kit["id"], MAT))
        assert reread["shortage_count"] == 3, f"read-after-write agrees on shortage 3: {reread}"
        assert reread["status"] == "PICKING", f"kit keeps picking at shortage 3: {reread}"


class TestKitLifecycleGates:
    def test_order_kitting_state_gates(self, api):
        """PRD §3.5: "The planner may also cancel an `OPEN` order outright, moving it `OPEN → CANCELLED`; cancellation on an order in any other status likewise rejects with `ERR_BUILD_ORDER_NOT_OPEN`."
        PRD §3.7: "Recording a build requires no payload fields; the order must be `IN_BUILD` (otherwise `ERR_BUILD_ORDER_NOT_IN_BUILD`)."

        Design: Corner/state_machines/c_order_kitting_state_gates
        """
        ctx = setup_order_in_build(api, tag="S8", qty_ordered=1, issue_plan=[], deliver=False)
        order = ctx["order"]
        assert order["status"] == "KITTING"
        cancel = api.cancel_build_order(order["id"], PLAN)
        validate_error(cancel, ApiErrorId.ERR_BUILD_ORDER_NOT_OPEN)
        builder = ctx["builder"]
        build = api.create_harness_unit(order["id"], make_line_operator_headers(builder["id"]))
        validate_error(build, ApiErrorId.ERR_BUILD_ORDER_NOT_IN_BUILD)

    def test_release_to_kitting_requires_qualified_program(self, api):
        """PRD §3.5: "Release demands that at least one machine program for the order's drawing is `QUALIFIED` (otherwise `ERR_NO_QUALIFIED_PROGRAM`) and that no kit of this order is currently `PICKING` or `STAGED`."

        Design: Corner/validations/c_release_without_qualified_program_rejected
        """
        drawing, _components = make_released_drawing(api, tag="V14")
        order = make_build_order(api, drawing_id=drawing["id"], order_code="BO-V14", qty_ordered=1)
        resp = api.release_build_order_to_kitting(order["id"], PLAN)
        validate_error(resp, ApiErrorId.ERR_NO_QUALIFIED_PROGRAM)
        kits, meta = validate_paginated(
            api.list_kits(MAT, params={"build_order_id": order["id"]})
        )
        assert meta["total_count"] == 0 and kits == [], (
            f"no kit is created by a rejected release: {meta}"
        )
        reread = get_success_data(api.get_build_order(order["id"], PLAN))
        assert reread["status"] == "OPEN", f"order stays OPEN after a rejected release: {reread}"


class TestBuildOrderOcc:
    def test_build_order_patch_stale_version_rejected(self, api):
        """PRD §2.7: "however, if `expected_build_order_version` no longer matches the build order's current `version` — because another write has advanced it since the client last read the order — the request is rejected with `ERR_STALE_BUILD_ORDER_VERSION` (HTTP 412), preventing the client from overwriting state it has not observed."
        PRD §2.4: "The `version` field is a system-managed integer that increments by one on every mutation of the resource, including mutations caused by automatic reconciliations and cascades, and it underpins the optimistic concurrency rules of §2.7."

        Design: Corner/cross_cutting_complexity_layers/c_build_order_patch_stale_version_rejected
        """
        drawing, _components = make_released_drawing(api, tag="L1")
        order = make_build_order(api, drawing_id=drawing["id"], order_code="BO-L1", qty_ordered=1)
        observed_version = order["version"]
        first = validate_success(
            api.patch_build_order(
                order["id"],
                {"expected_build_order_version": observed_version, "qty_ordered": 5},
                PLAN,
            ),
            200,
        )
        assert first["version"] == observed_version + 1, (
            f"the accepted patch increments the order version by one: {first}"
        )
        stale = api.patch_build_order(
            order["id"],
            {"expected_build_order_version": observed_version, "qty_ordered": 6},
            PLAN,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_BUILD_ORDER_VERSION)
        reread = get_success_data(api.get_build_order(order["id"], PLAN))
        assert reread["qty_ordered"] == 5, f"the losing patch did not apply: {reread}"


class TestConsignedIssueRules:
    def test_consigned_substitution_forbidden(self, api):
        """PRD §3.6: "Supply-type compliance forbids substitution: a BOM line declared `CUSTOMER_CONSIGNED` may only be issued with `source` `CONSIGNED_LOT`, and a `FACTORY_STOCK` line only with `source` `FACTORY_STOCK` — crossing the two rejects with `ERR_CONSIGNED_SUBSTITUTION_FORBIDDEN`."

        Design: Corner/validations/c_consigned_substitution_forbidden
        """
        ctx = setup_order_in_build(
            api, tag="V4", qty_ordered=1, issue_plan=[], deliver=False,
            line_kwargs={"bom": CONSIGNED_BOM},
        )
        kit = ctx["kit"]
        resp = api.create_kit_issue(
            kit["id"],
            {
                "component_id": ctx["line"]["components"]["C1"]["id"],
                "qty_issued": 1,
                "source": "FACTORY_STOCK",
            },
            MAT,
        )
        validate_error(resp, ApiErrorId.ERR_CONSIGNED_SUBSTITUTION_FORBIDDEN)
        reread = get_success_data(api.get_kit(kit["id"], MAT))
        assert reread["shortage_count"] == 1 and reread["status"] == "PICKING", (
            f"the rejected issue changes nothing: {reread}"
        )

    def test_consigned_mpn_mismatch_rejected(self, api):
        """PRD §3.6: "A referenced consigned lot must be `ACTIVE` (otherwise `ERR_CONSIGNED_LOT_NOT_ISSUABLE`), and the lot's `mpn` must equal the BOM line's `mpn` (otherwise `ERR_CONSIGNED_MPN_MISMATCH`)."

        Design: Corner/validations/c_consigned_mpn_mismatch_rejected
        """
        ctx = setup_order_in_build(
            api, tag="V5", qty_ordered=1, issue_plan=[], deliver=False,
            line_kwargs={"bom": CONSIGNED_BOM},
        )
        lot = make_consigned_lot(api, lot_code="LOT-V5", mpn="CON-OTHER", qty_received=5)
        resp = api.create_kit_issue(
            ctx["kit"]["id"],
            {
                "component_id": ctx["line"]["components"]["C1"]["id"],
                "qty_issued": 1,
                "source": "CONSIGNED_LOT",
                "consigned_lot_id": lot["id"],
            },
            MAT,
        )
        validate_error(resp, ApiErrorId.ERR_CONSIGNED_MPN_MISMATCH)
        lot_after = get_success_data(api.get_consigned_lot(lot["id"], MAT))
        assert lot_after["qty_on_hand"] == 5, f"the mismatched issue touched no buckets: {lot_after}"
        assert lot_after["qty_issued_open"] == 0

    def test_consigned_insufficient_on_hand_rejected(self, api):
        """PRD §3.6: "The `qty_issued` must not exceed the lot's `qty_on_hand` (otherwise `ERR_CONSIGNED_INSUFFICIENT_ON_HAND`)."

        Design: Corner/validations/c_consigned_insufficient_on_hand
        """
        ctx = setup_order_in_build(
            api, tag="V10", qty_ordered=2, issue_plan=[], deliver=False,
            line_kwargs={"bom": CONSIGNED_BOM},
        )
        lot = make_consigned_lot(api, lot_code="LOT-V10", qty_received=1)
        resp = api.create_kit_issue(
            ctx["kit"]["id"],
            {
                "component_id": ctx["line"]["components"]["C1"]["id"],
                "qty_issued": 2,
                "source": "CONSIGNED_LOT",
                "consigned_lot_id": lot["id"],
            },
            MAT,
        )
        validate_error(resp, ApiErrorId.ERR_CONSIGNED_INSUFFICIENT_ON_HAND)
        lot_after = get_success_data(api.get_consigned_lot(lot["id"], MAT))
        assert lot_after["qty_on_hand"] == 1 and lot_after["qty_issued_open"] == 0, (
            f"the rejected issue moved no pieces: {lot_after}"
        )

    def test_kit_line_over_issue_rejected(self, api):
        """PRD §3.6: "Cumulative non-voided issues against a BOM line must not exceed that line's needed quantity — `qty_per_harness` times `qty_ordered` (otherwise `ERR_KIT_LINE_OVER_ISSUE`)."

        Design: Corner/validations/c_kit_line_over_issue
        """
        bom = [
            {"find_number": "T1", "component_type": "TERMINAL", "mpn": "TERM-20",
             "qty_per_harness": 2, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 100},
        ]
        ctx = setup_order_in_build(
            api, tag="V11", qty_ordered=1, issue_plan=[], deliver=False,
            line_kwargs={"bom": bom},
        )
        kit = ctx["kit"]
        # Needed is 2 (qty_per_harness 2 x qty_ordered 1); issuing 3 over-ships the line.
        resp = api.create_kit_issue(
            kit["id"],
            {
                "component_id": ctx["line"]["components"]["T1"]["id"],
                "qty_issued": 3,
                "source": "FACTORY_STOCK",
            },
            MAT,
        )
        validate_error(resp, ApiErrorId.ERR_KIT_LINE_OVER_ISSUE)
        reread = get_success_data(api.get_kit(kit["id"], MAT))
        assert reread["shortage_count"] == 2 and reread["status"] == "PICKING", (
            f"the over-issue did not apply: {reread}"
        )

    def test_component_not_on_drawing_rejected(self, api):
        """PRD §3.6: "The issued component must belong to the order's pinned drawing revision (otherwise `ERR_COMPONENT_NOT_ON_DRAWING`)."

        Design: Corner/validations/c_component_not_on_drawing_rejected
        """
        line1 = setup_qualified_line(api, tag="V12")
        _drawing2, components2 = make_released_drawing(
            api, tag="V12B",
            bom=[{"find_number": "X1", "component_type": "SEAL", "mpn": "SEAL-1",
                  "qty_per_harness": 1, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 10}],
        )
        order = make_build_order(api, drawing_id=line1["drawing"]["id"],
                                 order_code="BO-V12", qty_ordered=1)
        release_order_to_kitting(api, order["id"])
        kit = get_order_kit(api, order["id"])
        # X1 lives on the OTHER released drawing; the order's pinned BOM governs.
        resp = api.create_kit_issue(
            kit["id"],
            {"component_id": components2["X1"]["id"], "qty_issued": 1, "source": "FACTORY_STOCK"},
            MAT,
        )
        validate_error(resp, ApiErrorId.ERR_COMPONENT_NOT_ON_DRAWING)


class TestMaterialBudget:
    def test_material_budget_boundary(self, api):
        """PRD §3.6: "And when the order carries a budget, the issue is allowed only if `material_spent_cents` plus this issue's extended cost (`qty_issued` times `unit_cost_snapshot_cents`) stays at or below `material_budget_cents` — equality is permitted, and only a strictly-greater result rejects with `ERR_MATERIAL_BUDGET_EXCEEDED`."

        Design: Corner/validations/c_material_budget_boundary
        """
        bom = [
            {"find_number": "T1", "component_type": "TERMINAL", "mpn": "TERM-20",
             "qty_per_harness": 4, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 250},
            {"find_number": "W1", "component_type": "WIRE", "mpn": "WIRE-20",
             "qty_per_harness": 1, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 100},
        ]
        ctx = setup_order_in_build(
            api, tag="V6", qty_ordered=1, material_budget_cents=1000,
            issue_plan=[], deliver=False, line_kwargs={"bom": bom},
        )
        kit = ctx["kit"]
        components = ctx["line"]["components"]
        # 4 x 250 = 1000 == budget exactly: allowed (equality permitted).
        issue_line(api, kit["id"], components["T1"]["id"], 4, "FACTORY_STOCK")
        order = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        assert order["material_spent_cents"] == 1000, (
            f"spend at exactly the budget cap is allowed: {order}"
        )
        # 1000 + 100 = 1100 > 1000: strictly greater rejects.
        resp = api.create_kit_issue(
            kit["id"],
            {"component_id": components["W1"]["id"], "qty_issued": 1, "source": "FACTORY_STOCK"},
            MAT,
        )
        validate_error(resp, ApiErrorId.ERR_MATERIAL_BUDGET_EXCEEDED)
        order = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        assert order["material_spent_cents"] == 1000, (
            f"the rejected issue did not apply: {order}"
        )


class TestConsignedLotReconciliation:
    def test_lot_auto_depletes_at_zero(self, api):
        """PRD §3.6: "Issuing moves pieces from `qty_on_hand` into `qty_issued_open`. Line-side delivery of a kit moves its consigned pieces from `qty_issued_open` into `qty_consumed`."
        PRD §3.6: "Delivery moves each non-voided consigned issue's pieces from the lot's `qty_issued_open` into `qty_consumed`, stamps `delivered_at` from the clock, runs the lot reconciliation that may auto-`DEPLETE` the lot, and — on the order's first delivery — moves the build order `KITTING → IN_BUILD`."
        PRD §3.6: "When reconciliation finds both `qty_on_hand` and `qty_issued_open` at zero — after a delivery or a scrap transfer — the lot auto-transitions `ACTIVE → DEPLETED`."

        Design: Corner/state_machines/c_lot_auto_depletes_at_zero
        """
        line = setup_qualified_line(api, tag="S9", bom=CONSIGNED_BOM)
        lot = make_consigned_lot(api, lot_code="LOT-S9", qty_received=2)
        ctx = setup_order_in_build(
            api, line=line, tag="S9", qty_ordered=2,
            default_lot_id=lot["id"], deliver=False, units=0,
        )
        kit = ctx["kit"]
        assert kit["status"] == "STAGED", f"full consigned coverage stages the kit: {kit}"
        mid = get_success_data(api.get_consigned_lot(lot["id"], MAT))
        assert_consigned_lot(mid)
        assert mid["status"] == "ACTIVE", (
            f"not depleted while pieces sit in an open issue: {mid}"
        )
        assert mid["qty_on_hand"] == 0 and mid["qty_issued_open"] == 2, (
            f"issuing moved both pieces on_hand -> issued_open: {mid}"
        )
        assert_consigned_lot_conservation(mid)
        deliver_kit(api, kit["id"])
        after = get_success_data(api.get_consigned_lot(lot["id"], MAT))
        assert after["status"] == "DEPLETED", (
            f"delivery zeroes both on_hand and issued_open -> DEPLETED: {after}"
        )
        assert after["qty_consumed"] == 2 and after["qty_issued_open"] == 0, (
            f"delivery moved issued_open -> consumed: {after}"
        )

    def test_actual_cost_excludes_voided_issues_after_return(self, api):
        """PRD §3.5: "The `actual_cost_cents` is the sum over all non-voided kit issues of the order of `qty_issued` times `unit_cost_snapshot_cents`, and equals `material_spent_cents`; the two variants diverge whenever consigned liability differs from standard cost or issues over- or under-ship against the BOM."
        PRD §3.6: "Returning a kit is allowed from `PICKING` or `STAGED` and moves the kit to `RETURNED`: every non-voided issue becomes voided, consigned pieces move from `qty_issued_open` back to `qty_on_hand`, and the order's `material_spent_cents` and `actual_cost_cents` recompute with voided issues excluded."

        Design: Corner/calculations/c_actual_cost_excludes_voided_issues
        """
        bom = [
            {"find_number": "T1", "component_type": "TERMINAL", "mpn": "TERM-20",
             "qty_per_harness": 2, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 100},
        ]
        ctx = setup_order_in_build(
            api, tag="C4", qty_ordered=1, deliver=False, units=0,
            line_kwargs={"bom": bom},
        )
        order = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        assert order["material_spent_cents"] == 200 and order["actual_cost_cents"] == 200, (
            f"issued 2 x 100 cents of factory stock: {order}"
        )
        returned = validate_success(api.return_kit(ctx["kit"]["id"], MAT), 200)
        assert returned["status"] == "RETURNED", f"kit return moves STAGED -> RETURNED: {returned}"
        order = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        assert order["material_spent_cents"] == 0 and order["actual_cost_cents"] == 0, (
            f"voided issues are excluded from spend and actual cost: {order}"
        )


class TestValidationPrecedenceOnIssue:
    def test_depleted_lot_issue_reports_referential_error_over_budget(self, api):
        """PRD §2.6: "When several checks could reject the same request, the server evaluates them in a fixed priority order and surfaces the first failure."
        PRD §2.6: "8. **Business referential integrity** — the issued component belongs to the order's pinned drawing revision, the referenced lot is issuable, the lot's part number matches the BOM line's, and a lot-sample pull test references the program actually loaded on the applicator."
        PRD §2.6: "11. **Fiscal rules** — the material budget cap."
        PRD §3.6: "A referenced consigned lot must be `ACTIVE` (otherwise `ERR_CONSIGNED_LOT_NOT_ISSUABLE`), and the lot's `mpn` must equal the BOM line's `mpn` (otherwise `ERR_CONSIGNED_MPN_MISMATCH`)."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_depleted_lot_issue
        """
        line = setup_qualified_line(api, tag="PP2", bom=CONSIGNED_BOM)
        lot = make_consigned_lot(api, lot_code="LOT-PP2", qty_received=1)
        # First order consumes the only piece; delivery auto-depletes the lot.
        setup_order_in_build(api, line=line, tag="PP2A", qty_ordered=1,
                             default_lot_id=lot["id"], units=0)
        depleted = get_success_data(api.get_consigned_lot(lot["id"], MAT))
        assert depleted["status"] == "DEPLETED", f"fully consumed lot auto-depleted: {depleted}"
        # Second order caps material spend at 100 cents; the issue would cost 500.
        order2 = make_build_order(api, drawing_id=line["drawing"]["id"],
                                  order_code="BO-PP2B", qty_ordered=1,
                                  material_budget_cents=100)
        release_order_to_kitting(api, order2["id"])
        kit2 = get_order_kit(api, order2["id"])
        resp = api.create_kit_issue(
            kit2["id"],
            {
                "component_id": line["components"]["C1"]["id"],
                "qty_issued": 1,
                "source": "CONSIGNED_LOT",
                "consigned_lot_id": lot["id"],
            },
            MAT,
        )
        error = validate_error(resp, ApiErrorId.ERR_CONSIGNED_LOT_NOT_ISSUABLE)
        assert error["error_id"] != ApiErrorId.ERR_MATERIAL_BUDGET_EXCEEDED, (
            "the referential rejection (tier 8) surfaces before the fiscal cap (tier 11)"
        )

    def test_issue_into_depleted_lot_rejected_without_budget(self, api):
        """PRD §3.6: "A referenced consigned lot must be `ACTIVE` (otherwise `ERR_CONSIGNED_LOT_NOT_ISSUABLE`), and the lot's `mpn` must equal the BOM line's `mpn` (otherwise `ERR_CONSIGNED_MPN_MISMATCH`)."
        PRD §3.6: "When reconciliation finds both `qty_on_hand` and `qty_issued_open` at zero — after a delivery or a scrap transfer — the lot auto-transitions `ACTIVE → DEPLETED`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_depleted_lot_issue
        """
        line = setup_qualified_line(api, tag="PP2S", bom=CONSIGNED_BOM)
        lot = make_consigned_lot(api, lot_code="LOT-PP2S", qty_received=1)
        setup_order_in_build(api, line=line, tag="PP2S-A", qty_ordered=1,
                             default_lot_id=lot["id"], units=0)
        # Uncapped second order: only the lot-status rule can fail.
        order2 = make_build_order(api, drawing_id=line["drawing"]["id"],
                                  order_code="BO-PP2S-B", qty_ordered=1)
        release_order_to_kitting(api, order2["id"])
        kit2 = get_order_kit(api, order2["id"])
        resp = api.create_kit_issue(
            kit2["id"],
            {
                "component_id": line["components"]["C1"]["id"],
                "qty_issued": 1,
                "source": "CONSIGNED_LOT",
                "consigned_lot_id": lot["id"],
            },
            MAT,
        )
        validate_error(resp, ApiErrorId.ERR_CONSIGNED_LOT_NOT_ISSUABLE)
