"""Transitive cascades: the lot-sample-fail quarantine chain (applicator ->
program -> build order -> suspect units), applicator requalification and order
resumption, and the ECN apply disposition chain (supersede -> cancel -> scrap
-> consigned transfer)."""
from test_helpers import (
    ApiErrorId,
    assert_consigned_lot_conservation,
    get_success_data,
    make_consigned_lot,
    make_ecn,
    make_released_drawing,
    pass_unit_tests,
    record_pull_test,
    requalify_line,
    setup_order_in_build,
    setup_qualified_line,
    ship_unit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ENG = TEST_USERS["harness_engineer_headers"]
PROC = TEST_USERS["process_engineer_headers"]
PLAN = TEST_USERS["production_planner_headers"]
MAT = TEST_USERS["materials_clerk_headers"]

ECN_BOM = [
    {"find_number": "C1", "component_type": "CONNECTOR", "mpn": "CON-500",
     "qty_per_harness": 1, "supply_type": "CUSTOMER_CONSIGNED", "unit_cost_cents": 450},
    {"find_number": "T1", "component_type": "TERMINAL", "mpn": "TERM-20",
     "qty_per_harness": 1, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 25},
]


def _quarantined_two_order_scene(api):
    """Two independent qualified lines and in-build orders; the first line's
    applicator is then quarantined by a failing lot sample. Returns the scene."""
    line1 = setup_qualified_line(api, tag="TC1", first_article_force=35.0)
    ctx1 = setup_order_in_build(api, line=line1, tag="TC1", qty_ordered=3, units=2)
    u1, u2 = ctx1["units"]
    pass_unit_tests(api, u1["id"], line1["inspector"]["id"])
    line2 = setup_qualified_line(api, tag="TC1-CTRL", inspector=line1["inspector"],
                                 first_article_force=35.0)
    ctx2 = setup_order_in_build(api, line=line2, tag="TC1-CTRL", qty_ordered=2,
                                units=1, builder=ctx1["builder"])
    fail = record_pull_test(
        api, line1["applicator"]["id"], line1["program"]["id"], line1["inspector"]["id"],
        sample_kind="LOT_SAMPLE", measured_force_n=20.0,
    )
    return {
        "line1": line1, "ctx1": ctx1, "u1": u1, "u2": u2,
        "line2": line2, "ctx2": ctx2, "u3": ctx2["units"][0], "fail": fail,
    }


class TestQuarantineCascade:
    def test_quarantine_cascade_holds_order_and_suspects_units(self, api):
        """PRD §3.4: "A failing lot sample fires the deepest cascade in the system. The applicator moves `QUALIFIED → QUARANTINED`. Every `QUALIFIED` machine program on that applicator moves to `HELD`. Each build order whose pinned drawing is the held program's drawing and whose status is `KITTING`, `IN_BUILD`, or `TESTING` moves to `QC_HOLD`, saving its prior status in `qc_hold_return_status` and recording the culprit program in `held_by_program_id`."
        PRD §3.4: "every harness unit whose build order belongs to that same drawing and entered `QC_HOLD` through this quarantine, whose status is `BUILT`, `REWORK`, or `TEST_PASS`, and whose `created_at` is at or after the quarantined applicator's `qualified_at`, moves to `SUSPECT` — `suspect_marked_at` stamped from the clock and both `continuity_pass` and `hipot_pass` reset to false."

        Design: Difficulty/transitive_cascade/lot_sample_fail_quarantine_sweep
        """
        scene = _quarantined_two_order_scene(api)
        assert scene["fail"]["result"] == "FAIL", (
            f"20.0 N is below the 30.0 N minimum: {scene['fail']}"
        )
        applicator = get_success_data(api.get_applicator(scene["line1"]["applicator"]["id"], PROC))
        assert applicator["status"] == "QUARANTINED", f"depth 1 — applicator: {applicator}"
        program = get_success_data(api.get_machine_program(scene["line1"]["program"]["id"], PROC))
        assert program["status"] == "HELD", f"depth 2 — program held: {program}"
        order = get_success_data(api.get_build_order(scene["ctx1"]["order"]["id"], PLAN))
        assert order["status"] == "QC_HOLD", f"depth 3 — order frozen: {order}"
        assert order["qc_hold_return_status"] == "IN_BUILD", (
            f"prior status saved for resumption: {order}"
        )
        assert order["held_by_program_id"] == scene["line1"]["program"]["id"], (
            f"culprit program recorded: {order}"
        )
        u1 = get_success_data(api.get_harness_unit(scene["u1"]["id"], PLAN))
        u2 = get_success_data(api.get_harness_unit(scene["u2"]["id"], PLAN))
        assert u1["status"] == "SUSPECT", f"depth 4 — TEST_PASS unit swept to SUSPECT: {u1}"
        assert u1["continuity_pass"] is False and u1["hipot_pass"] is False, (
            f"the sweep resets both test flags: {u1}"
        )
        assert u1["suspect_marked_at"] is not None, "suspect_marked_at is stamped"
        assert u2["status"] == "SUSPECT", f"depth 4 — BUILT unit swept to SUSPECT: {u2}"

    def test_quarantine_sweep_leaves_other_drawing_untouched(self, api):
        """PRD §3.4: "Units on orders of other drawings, and units already `SHIPPED` or `SCRAPPED`, are never selected."
        PRD §3.4: "Each build order whose pinned drawing is the held program's drawing and whose status is `KITTING`, `IN_BUILD`, or `TESTING` moves to `QC_HOLD`, saving its prior status in `qc_hold_return_status` and recording the culprit program in `held_by_program_id`."

        Design: Difficulty/transitive_cascade/lot_sample_fail_quarantine_sweep
        """
        scene = _quarantined_two_order_scene(api)
        applicator2 = get_success_data(api.get_applicator(scene["line2"]["applicator"]["id"], PROC))
        assert applicator2["status"] == "QUALIFIED", (
            f"control applicator on another drawing is untouched: {applicator2}"
        )
        order2 = get_success_data(api.get_build_order(scene["ctx2"]["order"]["id"], PLAN))
        assert order2["status"] == "IN_BUILD", (
            f"control order of another drawing is untouched: {order2}"
        )
        u3 = get_success_data(api.get_harness_unit(scene["u3"]["id"], PLAN))
        assert u3["status"] == "BUILT", f"control unit is never selected: {u3}"


class TestRequalificationCycle:
    def test_lot_sample_fail_quarantines_applicator_and_holds_program(self, api):
        """PRD §3.4: "The record's `result` is `PASS` when the measured force is at least the snapshot minimum, and `FAIL` otherwise."
        PRD §3.4: "A failing lot sample fires the deepest cascade in the system. The applicator moves `QUALIFIED → QUARANTINED`. Every `QUALIFIED` machine program on that applicator moves to `HELD`."

        Design: Difficulty/non_linear_state_machine/applicator_quarantine_requalification_cycle
        """
        line = setup_qualified_line(api, tag="NL2", first_article_force=32.0)
        fail = record_pull_test(
            api, line["applicator"]["id"], line["program"]["id"], line["inspector"]["id"],
            sample_kind="LOT_SAMPLE", measured_force_n=29.9,
        )
        assert fail["result"] == "FAIL", f"29.9 N is below the 30.0 N minimum: {fail}"
        applicator = get_success_data(api.get_applicator(line["applicator"]["id"], PROC))
        program = get_success_data(api.get_machine_program(line["program"]["id"], PROC))
        assert applicator["status"] == "QUARANTINED", f"lot-sample FAIL quarantines: {applicator}"
        assert program["status"] == "HELD", f"the applicator's QUALIFIED program is held: {program}"

    def test_requalification_restores_applicator_and_program(self, api):
        """PRD §3.4: "When a first-article test passes, the applicator moves `AVAILABLE → QUALIFIED` with `qualified_at` stamped from the clock, and the program qualifies with it: `DRAFT → QUALIFIED` for a first qualification, or `HELD → QUALIFIED` for a requalification after a quarantine — requalification additionally requiring that at least one `CLOSED` setup for the pair was created after the quarantine occurred."
        PRD §3.2: "An applicator may enter setup from `AVAILABLE`, `QUALIFIED`, or `QUARANTINED`; opening the window moves it to `IN_SETUP`, points its `current_program_id` at the setup's program, and increments its `version`."

        Design: Difficulty/non_linear_state_machine/applicator_quarantine_requalification_cycle
        """
        line = setup_qualified_line(api, tag="NL2R", first_article_force=32.0)
        record_pull_test(
            api, line["applicator"]["id"], line["program"]["id"], line["inspector"]["id"],
            sample_kind="LOT_SAMPLE", measured_force_n=29.9,
        )
        requal = requalify_line(api, line, force=31.0)
        assert requal["result"] == "PASS", f"31.0 N clears the 30.0 N minimum: {requal}"
        applicator = get_success_data(api.get_applicator(line["applicator"]["id"], PROC))
        program = get_success_data(api.get_machine_program(line["program"]["id"], PROC))
        assert applicator["status"] == "QUALIFIED", (
            f"full cycle AVAILABLE -> IN_SETUP -> QUALIFIED -> QUARANTINED -> IN_SETUP -> QUALIFIED: {applicator}"
        )
        assert program["status"] == "QUALIFIED", f"HELD -> QUALIFIED requalification: {program}"

    def test_quarantine_resume_restores_orders_but_not_units(self, api):
        """PRD §3.4: "A program's return from `HELD` to `QUALIFIED` releases the orders it froze: every build order sitting in `QC_HOLD` whose `held_by_program_id` is that program restores to its saved `qc_hold_return_status`, clearing both `qc_hold_return_status` and `held_by_program_id`, processed in order of the orders' `created_at` ascending."
        PRD §3.4: "Units thrown into `SUSPECT` by the quarantine are deliberately not auto-restored — they clear only through passing retests or scrap."
        PRD §3.7: "When both flags stand true, the unit advances: from `BUILT` it moves to `TEST_PASS`; from `SUSPECT` it returns to `TEST_PASS` only when both a passing continuity record and a passing hipot record carry `tested_at` at or after the unit's `suspect_marked_at`, and the return clears `suspect_marked_at`."

        Design: Corner/cross_cutting_complexity_layers/c_quarantine_resume_restores_orders
        """
        line = setup_qualified_line(api, tag="L3", first_article_force=35.0)
        ctx = setup_order_in_build(api, line=line, tag="L3", qty_ordered=3, units=2)
        u1, u2 = ctx["units"]
        record_pull_test(
            api, line["applicator"]["id"], line["program"]["id"], line["inspector"]["id"],
            sample_kind="LOT_SAMPLE", measured_force_n=20.0,
        )
        held = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        assert held["status"] == "QC_HOLD" and held["qc_hold_return_status"] == "IN_BUILD"

        requalify_line(api, line, force=31.0)
        program = get_success_data(api.get_machine_program(line["program"]["id"], PROC))
        assert program["status"] == "QUALIFIED", f"requalified program: {program}"
        order = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        assert order["status"] == "IN_BUILD", f"order resumed to its saved status: {order}"
        assert order["held_by_program_id"] is None, f"culprit reference cleared: {order}"
        assert order["qc_hold_return_status"] is None, f"return status cleared: {order}"

        # Retest one suspect unit back to TEST_PASS; the other stays SUSPECT.
        pass_unit_tests(api, u1["id"], line["inspector"]["id"])
        u1_after = get_success_data(api.get_harness_unit(u1["id"], PLAN))
        u2_after = get_success_data(api.get_harness_unit(u2["id"], PLAN))
        assert u1_after["status"] == "TEST_PASS", (
            f"SUSPECT cleared by passing retests at or after suspect_marked_at: {u1_after}"
        )
        assert u1_after["suspect_marked_at"] is None, "the return clears suspect_marked_at"
        assert u2_after["status"] == "SUSPECT", (
            f"units are not auto-restored; an unretested unit stays SUSPECT: {u2_after}"
        )


class TestEcnLifecycleAndApply:
    def test_ecn_lifecycle_errors(self, api):
        """PRD §3.8: "The `to_revision` must differ from `from_revision` — an unchanged revision rejects with `ERR_ECN_REVISION_UNCHANGED` — and at most one ECN may be `OPEN` per drawing: opening a second rejects with `ERR_ECN_ALREADY_OPEN`."
        PRD §3.8: "Applying an ECN requires it be `OPEN` (otherwise `ERR_ECN_NOT_OPEN`) and fires a four-deep cascade."
        PRD §3.8: "Cancelling an ECN — also requiring `OPEN`, else `ERR_ECN_NOT_OPEN` — simply moves it to the terminal `CANCELLED` with no further effect."

        Design: Corner/validations/c_ecn_lifecycle_errors
        """
        drawing, _components = make_released_drawing(api, tag="V8", revision="A")
        unchanged = api.create_ecn(
            {"ecn_code": "ECN-V8-A", "drawing_id": drawing["id"],
             "to_revision": "A", "wip_disposition": "REWORK"}, ENG
        )
        validate_error(unchanged, ApiErrorId.ERR_ECN_REVISION_UNCHANGED)
        ecn = validate_success(
            api.create_ecn(
                {"ecn_code": "ECN-V8-B", "drawing_id": drawing["id"],
                 "to_revision": "B", "wip_disposition": "REWORK"}, ENG
            ),
            201,
        )
        second = api.create_ecn(
            {"ecn_code": "ECN-V8-C", "drawing_id": drawing["id"],
             "to_revision": "C", "wip_disposition": "SCRAP"}, ENG
        )
        validate_error(second, ApiErrorId.ERR_ECN_ALREADY_OPEN)
        validate_success(api.apply_ecn(ecn["id"], ENG), 200)
        reapply = api.apply_ecn(ecn["id"], ENG)
        validate_error(reapply, ApiErrorId.ERR_ECN_NOT_OPEN)
        cancel = api.cancel_ecn(ecn["id"], ENG)
        validate_error(cancel, ApiErrorId.ERR_ECN_NOT_OPEN)

    def _ecn_scrap_scene(self, api, tag):
        line = setup_qualified_line(api, tag=tag, bom=ECN_BOM)
        lot = make_consigned_lot(api, lot_code=f"LOT-{tag}", qty_received=5)
        ctx = setup_order_in_build(api, line=line, tag=tag, qty_ordered=2,
                                   default_lot_id=lot["id"], units=2)
        u1, u2 = ctx["units"]
        pass_unit_tests(api, u1["id"], line["inspector"]["id"])
        ship_unit(api, u1["id"])
        ecn = make_ecn(api, drawing_id=line["drawing"]["id"], ecn_code=f"ECN-{tag}",
                       to_revision="B", wip_disposition="SCRAP")
        applied = validate_success(api.apply_ecn(ecn["id"], ENG), 200)
        return {"line": line, "lot": lot, "ctx": ctx, "u1": u1, "u2": u2,
                "ecn": ecn, "applied": applied}

    def test_ecn_apply_supersedes_drawing_and_copies_bom(self, api):
        """PRD §3.8: "The old drawing moves `RELEASED → SUPERSEDED` with `superseded_at` stamped."
        PRD §3.8: "A new harness drawing is created at the `to_revision` — its `drawing_number`, `customer_code`, and `workmanship_class` copied from the old drawing, its status `DRAFT`, and every component row of the old drawing copied onto it — and the ECN's `new_drawing_id` points at it."
        PRD §3.8: "Under `SCRAP`, the order moves to `CANCELLED`; every unit in `BUILT`, `REWORK`, `TEST_PASS`, or `SUSPECT` moves to `SCRAPPED` with `scrap_reason` `ECN_DISPOSITION`, earning the same per-unit scrap recovery credit and driving the same consigned consumed-to-scrapped FIFO transfer and liability recompute as a manual scrap; and every kit of the order in `PICKING` or `STAGED` moves to `RETURNED` with all its non-voided issues voided and consigned `qty_issued_open` restored to `qty_on_hand`."

        Design: Difficulty/transitive_cascade/ecn_apply_scrap_disposition_chain
        """
        scene = self._ecn_scrap_scene(api, "TC2A")
        old = get_success_data(api.get_drawing(scene["line"]["drawing"]["id"], ENG))
        assert old["status"] == "SUPERSEDED", f"depth 1 — old revision superseded: {old}"
        new_drawing_id = scene["applied"]["new_drawing_id"]
        new_drawing = get_success_data(api.get_drawing(new_drawing_id, ENG))
        assert new_drawing["revision"] == "B" and new_drawing["status"] == "DRAFT", (
            f"new revision row created DRAFT at the to_revision: {new_drawing}"
        )
        components, meta = validate_paginated(
            api.list_components(ENG, params={"drawing_id": new_drawing_id})
        )
        assert meta["total_count"] == 2 and len(components) == 2, (
            f"every component row copied onto the new revision: {meta}"
        )
        order = get_success_data(api.get_build_order(scene["ctx"]["order"]["id"], PLAN))
        assert order["status"] == "CANCELLED", (
            f"depth 2 — SCRAP disposition cancels the pinned order: {order}"
        )

    def test_ecn_scrap_disposition_scraps_units_and_transfers_consigned(self, api):
        """PRD §3.8: "Under `SCRAP`, the order moves to `CANCELLED`; every unit in `BUILT`, `REWORK`, `TEST_PASS`, or `SUSPECT` moves to `SCRAPPED` with `scrap_reason` `ECN_DISPOSITION`, earning the same per-unit scrap recovery credit and driving the same consigned consumed-to-scrapped FIFO transfer and liability recompute as a manual scrap; and every kit of the order in `PICKING` or `STAGED` moves to `RETURNED` with all its non-voided issues voided and consigned `qty_issued_open` restored to `qty_on_hand`."
        PRD §3.7: "for each BOM line of the unit's pinned drawing revision — all supply types included — a line credit of `qty_per_harness` times `unit_cost_cents` times the 0.8 recovery rate is rounded half-up to integer cents, and the per-line credits are then summed into a unit credit (the rounding order is pinned: round each line first, then sum; summing first and rounding once is a different, rejected result)."
        PRD §3.6: "`book_liability_cents` is `qty_scrapped` times `unit_liability_cents` (the settlement-at-book-value variant), and `replacement_liability_cents` is `qty_scrapped` times `replacement_cost_cents` (the settlement-at-replacement-cost variant); the two diverge whenever replacement cost differs from book."

        Design: Difficulty/transitive_cascade/ecn_apply_scrap_disposition_chain
        """
        scene = self._ecn_scrap_scene(api, "TC2B")
        u1 = get_success_data(api.get_harness_unit(scene["u1"]["id"], PLAN))
        u2 = get_success_data(api.get_harness_unit(scene["u2"]["id"], PLAN))
        assert u1["status"] == "SHIPPED", f"the shipped unit is terminal and survives: {u1}"
        assert u2["status"] == "SCRAPPED" and u2["scrap_reason"] == "ECN_DISPOSITION", (
            f"depth 3 — WIP unit scrapped by disposition: {u2}"
        )
        lot = get_success_data(api.get_consigned_lot(scene["lot"]["id"], MAT))
        # depth 4 — the scrapped unit's consigned piece transfers consumed -> scrapped.
        assert lot["qty_consumed"] == 1 and lot["qty_scrapped"] == 1, (
            f"one of the two consumed pieces followed the scrapped unit: {lot}"
        )
        assert lot["qty_on_hand"] == 3, f"untouched on-hand pieces: {lot}"
        assert lot["book_liability_cents"] == 500, f"1 x 500 book liability: {lot}"
        assert_consigned_lot_conservation(lot)
        order = get_success_data(api.get_build_order(scene["ctx"]["order"]["id"], PLAN))
        # Per-line credit, rounded first: round(450*0.8)=360 + round(25*0.8)=20 -> 380.
        assert order["scrap_recovery_credit_cents"] == 380, (
            f"per-line rounded scrap credit accumulates to the order: {order}"
        )
