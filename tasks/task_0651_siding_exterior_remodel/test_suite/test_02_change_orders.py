"""Change-order negotiation cycle, approval, and contract-total recompute.

Covers the cyclic SUBMITTED<->NEGOTIATING loop, the depth-2 cascade from approval
into contract total and a subsequently-approved draw's gross, and the forward-vs-
frozen distinction for draws approved before/after a change order.
"""
from test_helpers import (
    api_client as _ac,
    get_success_data, validate_success, validate_error,
    ApiErrorId,
    bootstrap_actors, create_baselined_project, THREE_LINE_ESTIMATE,
    setup_completed_window, add_completed_window,
    request_and_approve_draw, current_project_version,
    create_dual_signed_change_order, approve_change_order,
)


class TestNegotiationCycle:
    def test_negotiate_revise_negotiate_resets_signoffs_and_updates_delta(self, api):
        """PRD §3.7: "From `SUBMITTED`, a `HomeownerClient` may move the change order
        into `NEGOTIATING`, provided the parent project's `workflow_status` is neither
        `COMPLETED` nor `CANCELLED`; entering negotiation resets both `pm_approved`
        and `client_approved` to false."
        PRD §3.7: "From `NEGOTIATING`, a `ProjectManager` revises the proposal,
        supplying a new `delta_cents` and returning the change order to `SUBMITTED`;
        the loop may repeat any number of rounds."

        Design: Difficulty/non_linear_state_machine/nonlinear_changeorder_negotiation_cycle
        """
        proj, est, line_map, actors = create_baselined_project()
        line_id = line_map["SIDING"]["id"]
        co = get_success_data(_ac.create_change_order(
            {"project_id": proj["id"], "target_line_item_id": line_id, "delta_cents": 20000},
            actors["pm_h"]))
        get_success_data(_ac.negotiate_change_order(co["id"], actors["client_h"]))
        get_success_data(_ac.revise_change_order(co["id"], {"delta_cents": 15000}, actors["pm_h"]))
        final = validate_success(_ac.negotiate_change_order(co["id"], actors["client_h"]))
        assert final["status"] == "NEGOTIATING"
        assert final["delta_cents"] == 15000, f"delta should be revised to 15000, got {final['delta_cents']}"
        assert final["pm_approved"] is False
        assert final["client_approved"] is False

    def test_revise_returns_to_submitted_with_new_delta(self, api):
        """PRD §3.7: "From `NEGOTIATING`, a `ProjectManager` revises the proposal,
        supplying a new `delta_cents` and returning the change order to `SUBMITTED`;
        the loop may repeat any number of rounds."

        Design: Difficulty/non_linear_state_machine/nonlinear_changeorder_negotiation_cycle
        """
        proj, est, line_map, actors = create_baselined_project()
        line_id = line_map["SIDING"]["id"]
        co = get_success_data(_ac.create_change_order(
            {"project_id": proj["id"], "target_line_item_id": line_id, "delta_cents": 20000},
            actors["pm_h"]))
        get_success_data(_ac.negotiate_change_order(co["id"], actors["client_h"]))
        revised = validate_success(_ac.revise_change_order(co["id"], {"delta_cents": 15000}, actors["pm_h"]))
        assert revised["status"] == "SUBMITTED"
        assert revised["delta_cents"] == 15000


class TestApprovalRecomputesContract:
    def test_approve_recomputes_contract_total_from_baseline_plus_delta(self, api):
        """PRD §3.9: "Thereafter, on every change-order approval,
        `contract_total_cents` is recomputed as the baseline estimate total plus the
        sum of `delta_cents` across every change order on the project whose `status`
        is `APPROVED`."

        Design: Corner/cross_cutting_complexity_layers/changeorder_approve_recomputes_contract_total
        """
        # Single SIDING line 1000@1000c with 0.10 waste -> extended 1100000;
        # subtotal 1100000, tax 90750, total 1190750.
        proj, est, line_map, actors = create_baselined_project()
        line_id = line_map["SIDING"]["id"]
        co = create_dual_signed_change_order(proj["id"], line_id, actors, delta_cents=20000)
        approve_change_order(proj["id"], co["id"], actors)
        refetched = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert refetched["contract_total_cents"] == 1210750, \
            f"expected 1190750+20000=1210750, got {refetched['contract_total_cents']}"

    def test_approve_adjusts_target_line_extended_and_contract_total(self, api):
        """PRD §3.7: "On a successful approval the change order's `status` becomes
        `APPROVED`, the project's `contract_total_cents` is recomputed (see §3.9), the
        target `EstimateLineItem`'s `extended_cents` is adjusted by the `delta_cents`,
        and the project's `version` is incremented by one."

        Design: Corner/cross_cutting_complexity_layers/cascade_changeorder_approve_adjusts_target_line
        """
        proj, est, line_map, actors = create_baselined_project(line_items=THREE_LINE_ESTIMATE())
        siding_line_id = line_map["SIDING"]["id"]  # extended 990000
        co = create_dual_signed_change_order(proj["id"], siding_line_id, actors, delta_cents=50000)
        approve_change_order(proj["id"], co["id"], actors)
        line = validate_success(_ac.get_line_item(siding_line_id, actors["pm_h"]))
        assert line["extended_cents"] == 1040000, \
            f"expected 990000+50000=1040000, got {line['extended_cents']}"
        refetched = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert refetched["contract_total_cents"] == 1374980, \
            f"expected 1324980+50000=1374980, got {refetched['contract_total_cents']}"


class TestApprovePriorityConflict:
    def test_negotiating_changeorder_approve_returns_invalid_state(self, api):
        """PRD §3.12: "State-machine admissibility comes next: a target resource not
        in a state from which the requested transition is allowed yields
        `ERR_INVALID_STATE` (HTTP 409). Only after all of these do the
        domain-specific business rules described throughout §3 apply."
        PRD §3.7: "approving before both sign-offs are present is rejected with
        `ERR_DUAL_SIGNOFF_INCOMPLETE` (HTTP 409) — and only when the parent
        project's `workflow_status` is neither `COMPLETED` nor `CANCELLED`."

        A change order moved into NEGOTIATING (sign-offs reset to false) fails the
        state check before the dual-sign-off business rule, so approve returns
        ERR_INVALID_STATE.

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_state_vs_dual_signoff_constraint
        """
        proj, est, line_map, actors = create_baselined_project()
        line_id = line_map["SIDING"]["id"]
        co = get_success_data(_ac.create_change_order(
            {"project_id": proj["id"], "target_line_item_id": line_id, "delta_cents": 20000},
            actors["pm_h"]))
        get_success_data(_ac.negotiate_change_order(co["id"], actors["client_h"]))
        v = current_project_version(proj["id"], actors)
        resp = _ac.approve_change_order(co["id"], {"expected_project_version": v}, actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_negotiating_changeorder_approve_status_409(self, api):
        """PRD §3.12: "State-machine admissibility comes next: a target resource not
        in a state from which the requested transition is allowed yields
        `ERR_INVALID_STATE` (HTTP 409). Only after all of these do the
        domain-specific business rules described throughout §3 apply."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_state_vs_dual_signoff_constraint
        """
        proj, est, line_map, actors = create_baselined_project()
        line_id = line_map["SIDING"]["id"]
        co = get_success_data(_ac.create_change_order(
            {"project_id": proj["id"], "target_line_item_id": line_id, "delta_cents": 20000},
            actors["pm_h"]))
        get_success_data(_ac.negotiate_change_order(co["id"], actors["client_h"]))
        v = current_project_version(proj["id"], actors)
        resp = _ac.approve_change_order(co["id"], {"expected_project_version": v}, actors["pm_h"])
        assert resp.status_code == 409
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestDepth2CascadeIntoDrawGross:
    def test_change_order_approval_raises_subsequently_approved_draw_gross(self, api):
        """PRD §3.9: "A progress draw that is approved after a change-order approval
        prices its gross against the new contract total; a draw that was already
        approved before that change order keeps the gross amount frozen at its
        approval-time value."
        PRD §3.10: "The `gross_amount_cents` is the project's `contract_total_cents`
        multiplied by this draw's `milestone_pct`, rounded half-up to whole cents."

        Design: Difficulty/transitive_cascade/cascade_changeorder_approve_depth2_contract_then_draw_gross
        """
        # Project IN_PROGRESS, contract 1324980, one COMPLETED window.
        base = setup_completed_window(line_items=THREE_LINE_ESTIMATE(),
                                      measurement_overrides={"gross_wall_sqft": 2000, "opening_sqft": 200})
        proj, actors = base["project"], base["actors"]
        siding_line_id = base["line_map"]["SIDING"]["id"]
        # Approve a +50000 change order -> contract 1374980.
        co = create_dual_signed_change_order(proj["id"], siding_line_id, actors, delta_cents=50000)
        approve_change_order(proj["id"], co["id"], actors)
        proj_after = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert proj_after["contract_total_cents"] == 1374980
        # Draw approved AFTER the change order prices against the NEW total.
        draw = request_and_approve_draw(proj["id"], base["work_schedule"]["id"], actors, milestone_pct=0.30)
        # round(1374980 * 0.30) = 412494
        assert draw["gross_amount_cents"] == 412494, \
            f"draw approved after CO should use new total, got {draw['gross_amount_cents']}"

    def test_change_order_approval_recomputes_contract_before_draw_reads_it(self, api):
        """PRD §3.9: "The contract total is recomputed at the moment a change order is
        approved, before any subsequent draw approval reads it."
        PRD §3.9: "Thereafter, on every change-order approval, `contract_total_cents`
        is recomputed as the baseline estimate total plus the sum of `delta_cents`
        across every change order on the project whose `status` is `APPROVED`."

        Design: Difficulty/transitive_cascade/cascade_changeorder_approve_depth2_contract_then_draw_gross
        """
        base = setup_completed_window(line_items=THREE_LINE_ESTIMATE(),
                                      measurement_overrides={"gross_wall_sqft": 2000, "opening_sqft": 200})
        proj, actors = base["project"], base["actors"]
        siding_line_id = base["line_map"]["SIDING"]["id"]
        before = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert before["contract_total_cents"] == 1324980
        co = create_dual_signed_change_order(proj["id"], siding_line_id, actors, delta_cents=50000)
        approve_change_order(proj["id"], co["id"], actors)
        after = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert after["contract_total_cents"] == 1374980, \
            f"contract recompute (first cascade hop) expected 1374980, got {after['contract_total_cents']}"


class TestForwardVsFrozenContract:
    def test_draw_before_co_frozen_and_draw_after_co_forward(self, api):
        """PRD §3.9: "A progress draw that is approved after a change-order approval
        prices its gross against the new contract total; a draw that was already
        approved before that change order keeps the gross amount frozen at its
        approval-time value."
        PRD §3.9: "Later change orders never retroactively re-bill a draw that was
        already approved or released."

        Design: Difficulty/dual_variant_calc/dual_variant_contract_total_forward_vs_frozen
        """
        # Project IN_PROGRESS, contract 1324980, two COMPLETED windows.
        base = setup_completed_window(line_items=THREE_LINE_ESTIMATE(),
                                      measurement_overrides={"gross_wall_sqft": 2000, "opening_sqft": 200})
        proj, actors = base["project"], base["actors"]
        ws1 = base["work_schedule"]
        siding_line_id = base["line_map"]["SIDING"]["id"]
        ws2 = add_completed_window(proj["id"], base["crew"]["id"], actors,
                                   milestone="SIDING_INSTALL",
                                   window_start_iso="2026-04-23T08:00:00Z",
                                   window_end_iso="2026-04-23T17:00:00Z")
        # Draw#1 approved BEFORE the change order (frozen at 1324980).
        draw1 = request_and_approve_draw(proj["id"], ws1["id"], actors, milestone_pct=0.30)
        assert draw1["gross_amount_cents"] == 397494, \
            f"draw1 frozen gross should be round(1324980*0.30)=397494, got {draw1['gross_amount_cents']}"
        # Approve a +50000 change order -> contract 1374980.
        co = create_dual_signed_change_order(proj["id"], siding_line_id, actors, delta_cents=50000)
        approve_change_order(proj["id"], co["id"], actors)
        # Draw#2 approved AFTER (forward, against the new total).
        draw2 = request_and_approve_draw(proj["id"], ws2["id"], actors, milestone_pct=0.30)
        assert draw2["gross_amount_cents"] == 412494, \
            f"draw2 forward gross should be round(1374980*0.30)=412494, got {draw2['gross_amount_cents']}"
        proj_after = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert proj_after["contract_total_cents"] == 1374980

    def test_draw1_gross_unchanged_after_later_change_order(self, api):
        """PRD §3.9: "Later change orders never retroactively re-bill a draw that was
        already approved or released."

        Design: Difficulty/dual_variant_calc/dual_variant_contract_total_forward_vs_frozen
        """
        base = setup_completed_window(line_items=THREE_LINE_ESTIMATE(),
                                      measurement_overrides={"gross_wall_sqft": 2000, "opening_sqft": 200})
        proj, actors = base["project"], base["actors"]
        ws1 = base["work_schedule"]
        siding_line_id = base["line_map"]["SIDING"]["id"]
        draw1 = request_and_approve_draw(proj["id"], ws1["id"], actors, milestone_pct=0.30)
        assert draw1["gross_amount_cents"] == 397494
        co = create_dual_signed_change_order(proj["id"], siding_line_id, actors, delta_cents=50000)
        approve_change_order(proj["id"], co["id"], actors)
        # draw1 must remain frozen.
        refetched = validate_success(_ac.get_progress_draw(draw1["id"], actors["pm_h"]))
        assert refetched["gross_amount_cents"] == 397494, \
            f"draw1 must stay frozen at 397494, got {refetched['gross_amount_cents']}"
