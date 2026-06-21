"""State-machine behaviour: the non-linear hold/resume cycle, warranty
branching, parallel parts/execution dimensions, invalid transitions, terminal
lockdown, idempotency, initial state, and the retire cascade.

Covers Difficulty queue rule non_linear_state_machine plus the Corner
state_machines section.
"""
import pytest

from test_helpers import (
    fixtures as fx,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    TEST_USERS,
    make_technician_headers,
)

PLANNER = TEST_USERS["planner_headers"]
MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
WARRANTY = TEST_USERS["warranty_admin_headers"]


# =========================================================================
# Rule 3 — non_linear_state_machine
# =========================================================================

class TestHoldResumeCycle:
    def test_hold_then_resume_returns_to_in_progress(self, api):
        """PRD §3.6: "While in progress, a technician may put the order ON_HOLD
        and later resume it back to IN_PROGRESS; this hold-and-resume cycle is
        the one non-linear loop in the execution dimension."

        Design: Difficulty/non_linear_state_machine/work_order_in_progress_hold_resume_cycle
        """
        fx.set_clock("2026-04-01T00:00:00Z")
        site, asset, tech = fx.setup_site_asset_tech(
            asset_overrides={"criticality": "MEDIUM", "acquisition_cost_cents": 100_000},
            tech_overrides={"skill_level": "SENIOR"},
        )
        wo = fx.setup_in_progress_work_order(
            asset["id"], tech["id"], severity="MAJOR", estimated_labor_hours=5
        )
        th = make_technician_headers(tech["id"])
        held = validate_success(api.hold_work_order(wo["id"], th))
        assert held["execution_status"] == "ON_HOLD"
        resumed = validate_success(api.resume_work_order(wo["id"], th))
        assert resumed["execution_status"] == "IN_PROGRESS"

    def test_opened_at_unchanged_across_hold_resume(self, api):
        """PRD §3.6: "Starting an ASSIGNED order advances it to IN_PROGRESS and
        sets opened_at to the current clock instant if it was previously null."

        Design: Difficulty/non_linear_state_machine/work_order_in_progress_hold_resume_cycle
        """
        fx.set_clock("2026-04-01T00:00:00Z")
        site, asset, tech = fx.setup_site_asset_tech(
            asset_overrides={"criticality": "MEDIUM", "acquisition_cost_cents": 100_000},
            tech_overrides={"skill_level": "SENIOR"},
        )
        started = fx.setup_in_progress_work_order(
            asset["id"], tech["id"], severity="MAJOR", estimated_labor_hours=5
        )
        opened_first = started["opened_at"]
        assert opened_first is not None
        th = make_technician_headers(tech["id"])
        validate_success(api.hold_work_order(started["id"], th))
        resumed = validate_success(api.resume_work_order(started["id"], th))
        assert resumed["opened_at"] == opened_first, (
            "opened_at is set only if previously null; the second IN_PROGRESS entry "
            "must not reset it"
        )


class TestWarrantyBranching:
    def test_approve_branch_sets_approved(self, api):
        """PRD §3.9: "Approval sets the claim to APPROVED, records the optional
        decision_reason, links the work order by setting its warranty_claim_id
        to this claim, and reimburses the site by decreasing budget_spent_cents
        by the work order's actual_cost_cents".

        Design: Difficulty/non_linear_state_machine/warranty_claim_branching_approve_or_deny
        """
        site, asset, tech, closed, claim = fx.setup_warranted_closed_wo_with_claim(
            claim_type="REPAIR",
            actual_cost_cents=100_000,
            acquisition_cost_cents=800_000,
        )
        approved = validate_success(
            api.approve_claim(claim["id"], {"decision_reason": "ok"}, WARRANTY)
        )
        assert approved["status"] == "APPROVED"

    def test_deny_branch_zeroes_payable_and_keeps_budget(self, api):
        """PRD §3.9: "Denial requires only that the claim be SUBMITTED; it sets
        the claim to DENIED, records the optional decision_reason, fixes
        payable_cost_cents at 0, and leaves the site's budget_spent_cents
        unchanged so the close-time charge stands."

        Design: Difficulty/non_linear_state_machine/warranty_claim_branching_approve_or_deny
        """
        site, asset, tech, closed, claim = fx.setup_warranted_closed_wo_with_claim(
            claim_type="REPAIR",
            actual_cost_cents=100_000,
            acquisition_cost_cents=800_000,
        )
        denied = validate_success(
            api.deny_claim(claim["id"], {"decision_reason": "out of scope"}, WARRANTY)
        )
        assert denied["status"] == "DENIED"
        assert denied["payable_cost_cents"] == 0
        site_after = validate_success(api.get_site(site["id"], MANAGER))
        assert site_after["budget_spent_cents"] == 100_000, (
            "denied claim leaves the close-time charge standing"
        )


# =========================================================================
# Corner — state_machines section
# =========================================================================

class TestInvalidTransitions:
    def test_start_from_draft_is_invalid_state(self, api):
        """PRD §3.6: "Starting an ASSIGNED order advances it to IN_PROGRESS".
        PRD §3.10: "State validity comes next: an action whose target is not in
        a state from which the transition is defined yields ERR_INVALID_STATE."

        PRD §2.2: a Technician "may start, hold, resume, or close only the work
        orders assigned to them"; ownership compares the order's
        assigned_technician_id to X-User-ID. PRD §3.10 evaluates authorization
        (ERR_FORBIDDEN) *before* state validity (ERR_INVALID_STATE). A DRAFT
        order always has assigned_technician_id=null (PRD §3.4), so no Technician
        identity can pass the ownership gate to reach the state check — a
        PRD-faithful server must reject this with ERR_FORBIDDEN. The assertion is
        therefore relaxed to accept either the ownership rejection or the state
        rejection; both leave the order in DRAFT.

        Design: Corner/state_machines/start_work_order_from_draft_invalid_state
        """
        site, asset, tech = fx.setup_site_asset_tech(tech_overrides={"skill_level": "SENIOR"})
        wo = fx.create_corrective_work_order(asset["id"], severity="MAJOR", estimated_labor_hours=2)
        validate_error_is_one_of(
            api.start_work_order(wo["id"], make_technician_headers(tech["id"])),
            ["ERR_FORBIDDEN", "ERR_INVALID_STATE"],
        )
        after = validate_success(api.get_work_order(wo["id"], PLANNER))
        assert after["execution_status"] == "DRAFT"

    def test_cancel_closed_work_order_terminal_lockdown(self, api):
        """PRD §3.6: "Closing an order is permitted only while it is IN_PROGRESS.
        ... A successful close advances execution_status to CLOSED".
        PRD §3.5: "A work order may be cancelled by a planner while its execution
        status is DRAFT, UNASSIGNED, or ASSIGNED."

        Design: Corner/state_machines/cancel_closed_work_order_terminal_lockdown
        """
        fx.set_clock("2026-06-01T00:00:00Z")
        site, asset, tech, closed = fx.setup_closed_work_order_full(
            actual_cost_cents=1000,
            tech_overrides={"skill_level": "SENIOR"},
            wo_overrides={"severity": "MAJOR", "estimated_labor_hours": 2},
        )
        validate_error(api.cancel_work_order(closed["id"], PLANNER), "ERR_INVALID_STATE")
        after = validate_success(api.get_work_order(closed["id"], PLANNER))
        assert after["execution_status"] == "CLOSED"

    def test_resolve_already_resolved_downtime_rejected(self, api):
        """PRD §3.8: "Resolving sets ended_at, marks the event RESOLVED, and sets
        duration_hours to the elapsed time in hours".
        PRD §3.10: "an action whose target is not in a state from which the
        transition is defined yields ERR_INVALID_STATE."

        Design: Corner/state_machines/resolve_already_resolved_downtime_idempotency_rejected
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset()
        dt = fx.open_downtime(asset["id"], "OPERATOR_ERROR", "2026-05-01T00:00:00Z")
        fx.resolve_downtime(dt["id"], "2026-05-01T02:00:00Z")
        validate_error(
            api.resolve_downtime_event(
                dt["id"], {"ended_at": "2026-05-01T03:00:00Z"},
                TEST_USERS["technician_headers"],
            ),
            "ERR_INVALID_STATE",
        )
        after = validate_success(api.get_downtime_event(dt["id"], MANAGER))
        assert after["duration_hours"] == pytest.approx(2, abs=0.01), (
            "duration unchanged from the first resolve"
        )

    def test_commit_parts_with_no_reservation_invalid_state(self, api):
        """PRD §3.7: "Committing parts is a single action that operates on the
        whole work order: it requires the order to be IN_PROGRESS and at least
        one reservation to be RESERVED."

        Design: Corner/state_machines/commit_parts_with_no_reserved_reservation_invalid_state
        """
        site, asset, tech = fx.setup_site_asset_tech(tech_overrides={"skill_level": "SENIOR"})
        wo = fx.setup_in_progress_work_order(
            asset["id"], tech["id"], severity="MAJOR", estimated_labor_hours=2
        )
        validate_error(api.commit_parts(wo["id"], CLERK), "ERR_INVALID_STATE")
        after = validate_success(api.get_work_order(wo["id"], PLANNER))
        assert after["parts_status"] == "NONE"


class TestInitialAndParallelState:
    def test_new_work_order_initial_state_draft_none(self, api):
        """PRD §3.4: "Every work order starts with execution_status of DRAFT,
        parts_status of NONE, a null assigned_technician_id, a null
        warranty_claim_id, null opened_at and closed_at, and an
        actual_cost_cents of 0."

        Design: Corner/state_machines/new_work_order_initial_state_draft_none
        """
        site, asset = fx.setup_site_and_asset()
        wo = fx.create_corrective_work_order(
            asset["id"], severity="ROUTINE", estimated_labor_hours=1
        )
        assert wo["execution_status"] == "DRAFT"
        assert wo["parts_status"] == "NONE"

    def test_commit_advances_parts_only_execution_unchanged(self, api):
        """PRD §3.7: "It transitions every RESERVED reservation on the order to
        COMMITTED, freezing each reservation's committed_cost_cents as its qty
        multiplied by the part's unit_cost_cents, and sets the work order's
        parts_status to COMMITTED."

        Design: Corner/state_machines/parallel_dimensions_parts_committed_while_execution_in_progress
        """
        site, asset, tech = fx.setup_site_asset_tech(tech_overrides={"skill_level": "SENIOR"})
        part = fx.create_spare_part(sku="GASK-7", on_hand_qty=10, unit_cost_cents=800)
        wo = fx.create_corrective_work_order(asset["id"], severity="MAJOR", estimated_labor_hours=2)
        fx.release_to_queue(wo["id"])
        fx.assign(wo["id"], tech["id"])
        fx.reserve(wo["id"], part["id"], 2, part["version"])
        fx.start(wo["id"], tech["id"])
        committed = validate_success(api.commit_parts(wo["id"], CLERK))
        assert committed["parts_status"] == "COMMITTED"
        assert committed["execution_status"] == "IN_PROGRESS", (
            "the parts dimension does not change execution_status"
        )


class TestRetireCascade:
    def test_retire_deactivates_pm_schedules(self, api):
        """PRD §3.2: "A successful retire moves the asset to the terminal RETIRED
        status, increments its version, and cascades by setting active to false
        on every PM schedule of that asset so no further preventive work is
        generated."

        Design: Corner/state_machines/retire_asset_deactivates_pm_schedules_cascade
        """
        site, asset = fx.setup_site_and_asset()
        sched = fx.create_pm_schedule(
            asset["id"], "CALENDAR", calendar_interval_days=90,
            estimated_labor_hours=2, severity="ROUTINE",
        )
        retired = validate_success(
            api.retire_asset(asset["id"], {"expected_asset_version": asset["version"]}, MANAGER)
        )
        assert retired["status"] == "RETIRED"
        sched_after = validate_success(api.get_pm_schedule(sched["id"], PLANNER))
        assert sched_after["active"] is False
