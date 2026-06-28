"""Progress draws: approval gate, retainage cap, release/clawback ledger, OCC."""
from test_helpers import (
    api_client as _ac,
    get_success_data, validate_success, validate_error,
    ApiErrorId,
    bootstrap_actors, THREE_LINE_ESTIMATE,
    setup_completed_window, setup_approved_draw, setup_scheduled_window,
    add_completed_window, request_and_approve_draw, release_draw,
    current_project_version, create_dual_signed_change_order, approve_change_order,
    make_finance_officer_headers,
)


class TestDrawApprovalGate:
    def test_approve_against_non_completed_window_returns_milestone_incomplete(self, api):
        """PRD §3.10: "A `ProjectManager` approves a `REQUESTED` draw only when the
        referenced `WorkSchedule` is `COMPLETED` (otherwise rejected with
        `ERR_MILESTONE_INCOMPLETE`, HTTP 409) and the project is `IN_PROGRESS`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_draw_approve_requires_workschedule_completed
        """
        # Project IN_PROGRESS via a started+completed window; a SECOND window only CONFIRMED.
        base = setup_completed_window()
        proj, actors, crew = base["project"], base["actors"], base["crew"]
        # The first window is COMPLETED; build a second, CONFIRMED-only window.
        ws2 = add_completed_window(proj["id"], crew["id"], actors, milestone="SIDING_INSTALL",
                                   window_start_iso="2026-04-23T08:00:00Z",
                                   window_end_iso="2026-04-23T17:00:00Z", complete=False)
        draw = get_success_data(_ac.create_progress_draw(
            proj["id"], {"work_schedule_id": ws2["id"], "milestone_pct": 0.30}, actors["pm_h"]))
        resp = _ac.approve_progress_draw(draw["id"], actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_MILESTONE_INCOMPLETE.value)

    def test_approve_against_completed_window_succeeds(self, api):
        """PRD §3.10: "A `ProjectManager` approves a `REQUESTED` draw only when the
        referenced `WorkSchedule` is `COMPLETED` (otherwise rejected with
        `ERR_MILESTONE_INCOMPLETE`, HTTP 409) and the project is `IN_PROGRESS`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_draw_approve_requires_workschedule_completed
        """
        base = setup_completed_window()
        proj, actors, ws = base["project"], base["actors"], base["work_schedule"]
        draw = get_success_data(_ac.create_progress_draw(
            proj["id"], {"work_schedule_id": ws["id"], "milestone_pct": 0.30}, actors["pm_h"]))
        approved = validate_success(_ac.approve_progress_draw(draw["id"], actors["pm_h"]))
        assert approved["status"] == "APPROVED"

    def test_approve_missing_signoff_changeorder_does_not_apply_here(self, api):
        """PRD §3.7: "approving before both sign-offs are present is rejected with
        `ERR_DUAL_SIGNOFF_INCOMPLETE` (HTTP 409) — and only when the parent
        project's `workflow_status` is neither `COMPLETED` nor `CANCELLED`."

        Approving a SUBMITTED change order with only the PM sign-off (client_approved
        still false) is rejected with ERR_DUAL_SIGNOFF_INCOMPLETE.

        Design: Corner/validations/changeorder_approve_missing_signoff_returns_dual_signoff_incomplete
        """
        from test_helpers import create_baselined_project
        proj, est, line_map, actors = create_baselined_project()
        line_id = line_map["SIDING"]["id"]
        co = get_success_data(_ac.create_change_order(
            {"project_id": proj["id"], "target_line_item_id": line_id, "delta_cents": 20000},
            actors["pm_h"]))
        get_success_data(_ac.sign_change_order(co["id"], actors["pm_h"]))  # only PM signs
        v = current_project_version(proj["id"], actors)
        resp = _ac.approve_change_order(co["id"], {"expected_project_version": v}, actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_DUAL_SIGNOFF_INCOMPLETE.value)

    def test_request_draw_invalid_milestone_pct_returns_range_error(self, api):
        """PRD §3.11: "A `term_months` outside the allowed set, a `milestone_pct`
        outside its zero-to-one range, or a `waste_factor_pct` outside its
        zero-to-0.50 range are all numeric-range violations reported as
        `ERR_VALIDATION_RANGE` (HTTP 422)."

        Design: Corner/validations/progressdraw_request_invalid_milestone_pct_returns_range_error
        """
        base = setup_completed_window()
        proj, actors, ws = base["project"], base["actors"], base["work_schedule"]
        resp = _ac.create_progress_draw(
            proj["id"], {"work_schedule_id": ws["id"], "milestone_pct": 1.5}, actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_VALIDATION_RANGE.value)


class TestRetainageCap:
    def test_second_draw_retainage_capped_by_headroom(self, api):
        """PRD §3.10: "The `retainage_cents` actually withheld on this draw is the
        smaller of the raw retainage and that headroom — earlier draws fill the cap
        first, and once the cap is full a later draw withholds nothing."
        PRD §3.10: "The `net_released_cents` is the `gross_amount_cents` minus the
        `retainage_cents`."

        Design: Corner/calculations/draw_retainage_cap_binding_variant
        """
        # Contract 1324980. Draw#1 30% APPROVED then RELEASED -> retainage_held 39749.
        actors = bootstrap_actors(with_finance=True)
        base = setup_completed_window(line_items=THREE_LINE_ESTIMATE(),
                                      measurement_overrides={"gross_wall_sqft": 2000, "opening_sqft": 200},
                                      actors=actors)
        proj, crew, ws1 = base["project"], base["crew"], base["work_schedule"]
        draw1 = request_and_approve_draw(proj["id"], ws1["id"], actors, milestone_pct=0.30)
        release_draw(proj["id"], draw1["id"], actors)
        ws2 = add_completed_window(proj["id"], crew["id"], actors, milestone="SIDING_INSTALL",
                                   window_start_iso="2026-04-23T08:00:00Z",
                                   window_end_iso="2026-04-23T17:00:00Z")
        # Draw#2 40%: gross 529992, raw retainage 52999, headroom 66249-39749=26500 -> capped.
        draw2 = request_and_approve_draw(proj["id"], ws2["id"], actors, milestone_pct=0.40)
        assert draw2["gross_amount_cents"] == 529992, \
            f"gross expected 529992, got {draw2['gross_amount_cents']}"
        assert draw2["retainage_cents"] == 26500, \
            f"retainage capped at headroom 26500, got {draw2['retainage_cents']}"
        assert draw2["net_released_cents"] == 503492, \
            f"net expected 503492, got {draw2['net_released_cents']}"


class TestCashCompensation:
    def test_release_then_clawback_restores_ledger(self, api):
        """PRD §3.10: "On release the draw's `status` becomes `RELEASED`, the
        project's `amount_released_cents` is increased by this draw's
        `net_released_cents`, its `retainage_held_cents` is increased by this draw's
        `retainage_cents`, and the project's `version` is incremented by one."
        PRD §3.10: "Clawback requires the draw to be `RELEASED` and
        `expected_project_version` to match the project's current `version`; on
        success the draw's `status` becomes `CLAWED_BACK`, the project's
        `amount_released_cents` is decreased by the draw's `net_released_cents`, its
        `retainage_held_cents` is decreased by the draw's `retainage_cents`, and the
        project's `version` is incremented by one."

        Design: Difficulty/compensating_invariant/compensating_cash_release_then_clawback
        """
        actors = bootstrap_actors(with_finance=True)
        base = setup_completed_window(line_items=THREE_LINE_ESTIMATE(),
                                      measurement_overrides={"gross_wall_sqft": 2000, "opening_sqft": 200},
                                      actors=actors)
        proj, ws = base["project"], base["work_schedule"]
        draw = request_and_approve_draw(proj["id"], ws["id"], actors, milestone_pct=0.30)
        # gross 397494, retainage 39749, net 357745
        release_draw(proj["id"], draw["id"], actors)
        v = current_project_version(proj["id"], actors, headers=actors["fin_h"])
        clawed = validate_success(_ac.clawback_progress_draw(
            draw["id"], {"expected_project_version": v}, actors["fin_h"]))
        assert clawed["status"] == "CLAWED_BACK"
        refetched = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert refetched["amount_released_cents"] == 0, \
            f"amount_released must return to 0, got {refetched['amount_released_cents']}"
        assert refetched["retainage_held_cents"] == 0, \
            f"retainage_held must return to 0, got {refetched['retainage_held_cents']}"

    def test_release_increases_ledger_clawback_reverses_exactly(self, api):
        """PRD §3.10: "On release the draw's `status` becomes `RELEASED`, the
        project's `amount_released_cents` is increased by this draw's
        `net_released_cents`, its `retainage_held_cents` is increased by this draw's
        `retainage_cents`, and the project's `version` is incremented by one."

        Design: Difficulty/compensating_invariant/compensating_cash_release_then_clawback
        """
        actors = bootstrap_actors(with_finance=True)
        base = setup_completed_window(line_items=THREE_LINE_ESTIMATE(),
                                      measurement_overrides={"gross_wall_sqft": 2000, "opening_sqft": 200},
                                      actors=actors)
        proj, ws = base["project"], base["work_schedule"]
        draw = request_and_approve_draw(proj["id"], ws["id"], actors, milestone_pct=0.30)
        release_draw(proj["id"], draw["id"], actors)
        after_release = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert after_release["amount_released_cents"] == 357745, \
            f"net 357745 released, got {after_release['amount_released_cents']}"
        assert after_release["retainage_held_cents"] == 39749, \
            f"retainage 39749 held, got {after_release['retainage_held_cents']}"
        v = current_project_version(proj["id"], actors, headers=actors["fin_h"])
        get_success_data(_ac.clawback_progress_draw(draw["id"], {"expected_project_version": v}, actors["fin_h"]))
        after_clawback = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert after_clawback["amount_released_cents"] == 0
        assert after_clawback["retainage_held_cents"] == 0


class TestSegregationOfDuties:
    def test_releasing_officer_equal_to_approver_returns_segregation(self, api):
        """PRD §3.10: "the releasing officer's `X-User-ID` must not equal the draw's
        `approved_by_staff_id` — the officer who releases the cash may not be the
        manager who approved the draw; a violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/progressdraw_release_segregation_of_duties_returns_forbidden
        """
        base = setup_approved_draw()  # PM (actors["pm_id"]) approved -> approved_by_staff_id = pm_id
        proj, actors, draw = base["project"], base["actors"], base["draw"]
        # Attempt release as FinanceOfficer but using the SAME X-User-ID as the approver.
        same_person_headers = make_finance_officer_headers(actors["pm_id"])
        v = current_project_version(proj["id"], actors, headers=same_person_headers)
        resp = _ac.release_progress_draw(
            draw["id"], {"expected_project_version": v}, same_person_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


class TestReleaseOCC:
    def test_release_with_stale_version_returns_412(self, api):
        """PRD §2.5: "If another writer has advanced the project's version since the
        officer last read it — for instance because a change order was just approved,
        legitimately advancing the contract total and bumping the version — the
        release is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), preventing
        the officer from releasing cash figures computed against a contract baseline
        they have not observed."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_release_returns_412
        """
        actors = bootstrap_actors(with_finance=True)
        base = setup_completed_window(line_items=[{"scope_kind": "SIDING", "quantity": 1800, "unit_price_cents": 500}],
                                      measurement_overrides={"gross_wall_sqft": 2000, "opening_sqft": 200},
                                      actors=actors)
        proj, ws = base["project"], base["work_schedule"]
        siding_line_id = base["line_map"]["SIDING"]["id"]
        draw = request_and_approve_draw(proj["id"], ws["id"], actors, milestone_pct=0.30)
        # FinanceOfficer captures the version BEFORE the interleaving change order.
        stale_v = current_project_version(proj["id"], actors, headers=actors["fin_h"])
        # A change order is approved -> bumps Project.version, making stale_v stale.
        co = create_dual_signed_change_order(proj["id"], siding_line_id, actors, delta_cents=50000)
        approve_change_order(proj["id"], co["id"], actors)
        resp = _ac.release_progress_draw(
            draw["id"], {"expected_project_version": stale_v}, actors["fin_h"])
        validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION.value)
