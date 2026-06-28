"""State-machine transitions, parallel dimensions, branch forks, and cascades.

Difficulty queue: non_linear_state_machine, transitive_cascade.
Corner queue: state_machines section, cross_cutting (reject/resubmit cycle).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    fixtures as fx, factories as f,
    make_customer_headers,
)
from test_helpers.fixtures import DESIGNER, SCHEDULER, MFG_OPS, ADMIN, MELAMINE_18_UNITS


# ===========================================================================
# Rule 3 — non-linear state machines
# ===========================================================================
class TestParallelAndBranchingStateMachines:
    def test_install_job_sched_and_completion_axes_evolve_independently(self, api):
        """PRD §3.6: "An install job carries two parallel dimensions that evolve
        independently: a scheduling dimension `sched_status` (`PROPOSED`, `BOOKED`,
        `RESCHEDULING`, or `CANCELLED`) starting at `PROPOSED`, and a completion dimension
        `completion_status` (`NOT_STARTED`, `IN_PROGRESS`, or `DONE`) starting at
        `NOT_STARTED`."
        PRD §3.6: "A `Scheduler` starts the install, moving `completion_status` from
        `NOT_STARTED` to `IN_PROGRESS`; this is permitted only while the job's
        `sched_status` is `BOOKED`, its `completion_status` is `NOT_STARTED`, and the
        current time is at or after `window_start`. Starting advances the project from
        `READY_TO_INSTALL` to `INSTALLING` and increments the `version` of both the job
        and the project."

        Design: Difficulty/non_linear_state_machine/install_job_parallel_sched_and_completion_dimensions
        """
        ctx = fx.setup_booked_install_job(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T16:00:00Z",
        )
        fx.set_clock("2026-05-10T08:00:00Z")
        job = get_success_data(api.start_install_job(ctx["install_job"]["id"], SCHEDULER))
        assert job["sched_status"] == "BOOKED", "sched axis stays BOOKED while completion advances"
        assert job["completion_status"] == "IN_PROGRESS"
        proj = get_success_data(api.get_project(ctx["project"]["id"], DESIGNER))
        assert proj["status"] == "INSTALLING"

    def test_booking_leaves_completion_axis_not_started(self, api):
        """PRD §3.6: "An install job carries two parallel dimensions that evolve
        independently: a scheduling dimension `sched_status` (`PROPOSED`, `BOOKED`,
        `RESCHEDULING`, or `CANCELLED`) starting at `PROPOSED`, and a completion dimension
        `completion_status` (`NOT_STARTED`, `IN_PROGRESS`, or `DONE`) starting at
        `NOT_STARTED`."
        PRD §3.6: "On a successful booking, `units_booked` is set to the accepted
        configuration's `total_units` (the same unit count that drives volume pricing and
        lead time), the crew/day capacity is held, and the job's `version` is incremented."

        Design: Difficulty/non_linear_state_machine/install_job_parallel_sched_and_completion_dimensions
        """
        ctx = fx.setup_booked_install_job(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T16:00:00Z",
        )
        job = ctx["install_job"]
        # sched axis advanced to BOOKED while completion axis stays NOT_STARTED.
        assert job["sched_status"] == "BOOKED"
        assert job["completion_status"] == "NOT_STARTED"

    def test_warranty_fit_takes_adjustment_branch(self, api):
        """PRD §3.10: "The **adjustment branch** schedules an on-site adjustment, moving
        the claim from `APPROVED` to `ADJUSTMENT_SCHEDULED`, and is permitted only when
        the `defect_type` is `FIT` or `FINISH`."
        PRD §3.10: "the claim is covered when it is filed within the warranty window of
        365 days of the install's completion **and** the `defect_type` is among the
        covered defects, which are `HARDWARE`, `FINISH`, `FIT`, and `STRUCTURAL`."

        Design: Difficulty/non_linear_state_machine/warranty_claim_branch_fork_adjustment_vs_replacement
        """
        ctx = fx.setup_approved_warranty_claim(defect_type="FIT")
        claim = get_success_data(api.schedule_adjustment_warranty_claim(ctx["claim"]["id"], MFG_OPS))
        assert claim["status"] == "ADJUSTMENT_SCHEDULED"
        assert claim["covered"] is True

    def test_warranty_hardware_takes_replacement_branch(self, api):
        """PRD §3.10: "The **replacement branch** orders a replacement, moving the claim
        from `APPROVED` to `REPLACEMENT_ORDERED`, and is permitted only when the
        `defect_type` is `HARDWARE` or `STRUCTURAL`."

        Design: Difficulty/non_linear_state_machine/warranty_claim_branch_fork_adjustment_vs_replacement
        """
        ctx = fx.setup_approved_warranty_claim(defect_type="HARDWARE")
        claim = get_success_data(api.order_replacement_warranty_claim(ctx["claim"]["id"], MFG_OPS))
        assert claim["status"] == "REPLACEMENT_ORDERED"
        assert claim["covered"] is True


# ===========================================================================
# Rule 4 — transitive cascades
# ===========================================================================
class TestTransitiveCascades:
    def test_install_complete_cascades_depth3_to_order_and_project(self, api):
        """PRD §3.6: "Completion is the deepest cascade in the system: it drives the
        manufacture order from `READY` to `INSTALLED`, advances the project from
        `INSTALLING` to `COMPLETED`, recomputes the project's `balance_due_cents`, and
        increments the `version` of the install job, the manufacture order, and the
        project."

        Design: Difficulty/transitive_cascade/install_complete_cascade_depth3_to_order_then_project
        """
        ctx = fx.setup_completed_project(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T16:00:00Z",
            install_clock="2026-05-10T08:00:00Z",
        )
        job = ctx["install_job"]
        assert job["completion_status"] == "DONE"
        mo = get_success_data(api.get_manufacture_order(ctx["manufacture_order"]["id"], MFG_OPS))
        assert mo["status"] == "INSTALLED"
        proj = get_success_data(api.get_project(ctx["project"]["id"], DESIGNER))
        assert proj["status"] == "COMPLETED"

    def test_manufacture_order_only_reaches_installed_via_install_completion(self, api):
        """PRD §3.5: "The manufacture order reaches its terminal `INSTALLED` state later,
        when the corresponding install job is completed, at which point its `version` is
        incremented again."
        PRD §3.6: "Completion is the deepest cascade in the system: it drives the
        manufacture order from `READY` to `INSTALLED`, advances the project from
        `INSTALLING` to `COMPLETED`, recomputes the project's `balance_due_cents`"

        Design: Difficulty/transitive_cascade/install_complete_cascade_depth3_to_order_then_project
        """
        ctx = fx.setup_booked_install_job(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T16:00:00Z",
        )
        # Before install completion the order sits at READY (not yet INSTALLED).
        mo_before = get_success_data(api.get_manufacture_order(ctx["manufacture_order"]["id"], MFG_OPS))
        assert mo_before["status"] == "READY"
        fx.set_clock("2026-05-10T08:00:00Z")
        get_success_data(api.start_install_job(ctx["install_job"]["id"], SCHEDULER))
        get_success_data(api.complete_install_job(ctx["install_job"]["id"], SCHEDULER))
        # The hop to INSTALLED is caused by the install completion, not a direct call.
        mo_after = get_success_data(api.get_manufacture_order(ctx["manufacture_order"]["id"], MFG_OPS))
        assert mo_after["status"] == "INSTALLED"

    def test_project_cancel_cascades_to_consults_and_quotes(self, api):
        """PRD §3.1: "Cancellation moves the project to `CANCELLED` and cascades: every
        non-terminal `DesignConsult` of the project (those in `SCHEDULED` or `RENDERED`)
        transitions to `CANCELLED`, and every `Quote` of the project that is in `DRAFT`
        or `ISSUED` transitions to `VOID`."

        Design: Difficulty/transitive_cascade/project_cancel_cascade_depth2_to_consults_and_quotes
        """
        # Project QUOTED with a SCHEDULED consult and an ISSUED (not accepted) quote.
        customer = fx.create_customer(zip_code="90001")
        project = fx.create_project(customer["id"], room_type="WALK_IN_CLOSET")
        consult = fx.add_design_consult(project["id"])
        cfg, _ = fx.add_finalized_config(project["id"], material_grade="MELAMINE")
        quote = fx.add_quote(project["id"], cfg["id"])
        quote = fx.issue_quote(quote["id"])
        # Cancel as owner.
        cancelled = get_success_data(
            api.cancel_project(project["id"], make_customer_headers(customer["id"]))
        )
        assert cancelled["status"] == "CANCELLED"
        consult_after = get_success_data(api.list_design_consults(project["id"], DESIGNER))
        consult_after = consult_after["data"] if isinstance(consult_after, dict) and "data" in consult_after else consult_after
        assert any(c["id"] == consult["id"] and c["status"] == "CANCELLED" for c in consult_after)
        quote_after = get_success_data(api.get_quote(quote["id"], DESIGNER))
        assert quote_after["status"] == "VOID"

    def test_project_cancel_voids_draft_quote(self, api):
        """PRD §3.1: "Cancellation moves the project to `CANCELLED` and cascades: every
        non-terminal `DesignConsult` of the project (those in `SCHEDULED` or `RENDERED`)
        transitions to `CANCELLED`, and every `Quote` of the project that is in `DRAFT` or
        `ISSUED` transitions to `VOID`."

        Design: Difficulty/transitive_cascade/project_cancel_cascade_depth2_to_consults_and_quotes
        """
        # Project DESIGNING with a DRAFT (un-issued) quote and a SCHEDULED consult.
        customer = fx.create_customer(zip_code="90001")
        project = fx.create_project(customer["id"], room_type="WALK_IN_CLOSET")
        consult = fx.add_design_consult(project["id"])
        cfg, _ = fx.add_finalized_config(project["id"], material_grade="MELAMINE")
        draft_quote = fx.add_quote(project["id"], cfg["id"])  # left in DRAFT
        cancelled = get_success_data(
            api.cancel_project(project["id"], make_customer_headers(customer["id"]))
        )
        assert cancelled["status"] == "CANCELLED"
        consult_after = get_success_data(api.get_quote(draft_quote["id"], DESIGNER))
        assert consult_after["status"] == "VOID"


# ===========================================================================
# Corner — state_machines section
# ===========================================================================
class TestStateMachineCorners:
    def test_cancel_already_cancelled_project_invalid_state(self, api):
        """PRD §3.1: "A customer may cancel their own project, but only before any deposit
        is captured: cancellation is permitted while the project is in `LEAD`,
        `DESIGNING`, or `QUOTED`, and is not available once the project has reached
        `DEPOSIT_PAID` or any later state — an attempt against a project in any other
        state is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_already_cancelled_project_invalid_state
        """
        customer = fx.create_customer(zip_code="90001")
        project = fx.create_project(customer["id"], room_type="GARAGE")
        ch = make_customer_headers(customer["id"])
        get_success_data(api.cancel_project(project["id"], ch))
        resp = api.cancel_project(project["id"], ch)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_cancel_after_deposit_paid_rejected(self, api):
        """PRD §3.1: "cancellation is permitted while the project is in `LEAD`,
        `DESIGNING`, or `QUOTED`, and is not available once the project has reached
        `DEPOSIT_PAID` or any later state — an attempt against a project in any other
        state is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_after_deposit_paid_rejected
        """
        ctx = fx.setup_deposit_paid(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS, deposit_amount=17820,
        )
        resp = api.cancel_project(ctx["project"]["id"], make_customer_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_resolved_warranty_claim_cannot_be_re_resolved(self, api):
        """PRD §3.10: "From either `ADJUSTMENT_SCHEDULED` or `REPLACEMENT_ORDERED`, the
        operator resolves the claim, moving it to the terminal `RESOLVED` state and
        incrementing its `version`."

        Design: Corner/state_machines/terminal_warranty_resolved_no_further_transition
        """
        ctx = fx.setup_approved_warranty_claim(defect_type="FIT")
        claim_id = ctx["claim"]["id"]
        get_success_data(api.schedule_adjustment_warranty_claim(claim_id, MFG_OPS))
        get_success_data(api.resolve_warranty_claim(claim_id, MFG_OPS))
        resp = api.resolve_warranty_claim(claim_id, MFG_OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_render_already_rendered_consult_invalid_state(self, api):
        """PRD §3.2: "Attaching a 3D rendering moves a `SCHEDULED` consult to `RENDERED`;
        this requires a `rendering_url` to be supplied, which is written onto the consult,
        and increments the consult's `version`."

        Design: Corner/state_machines/design_consult_render_requires_scheduled_idempotency
        """
        customer = fx.create_customer(zip_code="90001")
        project = fx.create_project(customer["id"], room_type="WALK_IN_CLOSET")
        consult = fx.add_design_consult(project["id"])
        get_success_data(api.render_design_consult(
            consult["id"], {"rendering_url": "https://r/1.glb"}, DESIGNER))
        resp = api.render_design_consult(
            consult["id"], {"rendering_url": "https://r/2.glb"}, DESIGNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_render_sets_url_and_transitions(self, api):
        """PRD §3.2: "Attaching a 3D rendering moves a `SCHEDULED` consult to `RENDERED`;
        this requires a `rendering_url` to be supplied, which is written onto the consult,
        and increments the consult's `version`."

        Design: Corner/state_machines/design_consult_render_valid_transition_sets_url
        """
        customer = fx.create_customer(zip_code="90001")
        project = fx.create_project(customer["id"], room_type="WALK_IN_CLOSET")
        consult = fx.add_design_consult(project["id"])
        rendered = get_success_data(api.render_design_consult(
            consult["id"], {"rendering_url": "https://r/main.glb"}, DESIGNER))
        assert rendered["status"] == "RENDERED"
        assert rendered["rendering_url"] == "https://r/main.glb"

    def test_first_consult_bubbles_project_to_designing(self, api):
        """PRD §3.1: "Scheduling the first design consult for a project that is still
        `LEAD` advances it to `DESIGNING`."
        PRD §3.2: "If the project was still `LEAD`, creating this first consult advances
        the project to `DESIGNING` and increments the project's `version`."

        Design: Corner/state_machines/first_design_consult_bubbles_project_to_designing
        """
        customer = fx.create_customer(zip_code="90001")
        project = fx.create_project(customer["id"], room_type="WALK_IN_CLOSET")
        assert project["version"] == 1
        fx.add_design_consult(project["id"])
        proj = get_success_data(api.get_project(project["id"], DESIGNER))
        assert proj["status"] == "DESIGNING"
        assert proj["version"] == 2

    def test_config_finalize_locks_measure_cross_entity(self, api):
        """PRD §3.2: "On a successful finalize, the system recomputes the configuration's
        `total_units`, sets the backing measure's `confirmed` flag to true (locking it),
        and increments the `version` of both the configuration and the measure."

        Design: Corner/state_machines/config_finalize_locks_measure_cross_entity
        """
        ctx = fx.setup_designing_project(zip_code="90001", room_type="WALK_IN_CLOSET")
        measure = fx.add_space_measure(ctx["project"]["id"])
        cfg = fx.add_component_config(
            ctx["project"]["id"], measure["id"], material_grade="MELAMINE",
            line_items=[{"component_type": "SHELF", "quantity": 8, "unit_price_cents": 5000}],
        )
        cfg = fx.finalize_config(cfg["id"])
        assert cfg["status"] == "FINALIZED"
        assert cfg["total_units"] == 8
        measure_after = get_success_data(api.list_space_measures(ctx["project"]["id"], DESIGNER))
        measure_after = measure_after["data"] if isinstance(measure_after, dict) and "data" in measure_after else measure_after
        m = next(m for m in measure_after if m["id"] == measure["id"])
        assert m["confirmed"] is True

    def test_quote_expiry_auto_transition_on_read(self, api):
        """PRD §3.4: "Whenever a project is read, a project's quotes are listed, or a quote
        is read directly, the system sweeps the relevant quotes: any quote that is
        `ISSUED` and whose `expires_at` is now in the past — that is, the current time is
        strictly greater than `expires_at` — is transitioned to `EXPIRED`, and its
        `version` is incremented."

        Design: Corner/state_machines/quote_expiry_auto_transition_on_read
        """
        fx.set_clock("2026-04-01T00:00:00Z")
        ctx = fx.setup_finalized_config_scenario(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE",
            line_items=[{"component_type": "SHELF", "quantity": 8, "unit_price_cents": 5000}],
        )
        quote = fx.add_quote(ctx["project"]["id"], ctx["config"]["id"])
        quote = fx.issue_quote(quote["id"])
        fx.set_clock("2026-09-01T00:00:00Z")
        swept = get_success_data(api.get_quote(quote["id"], DESIGNER))
        assert swept["status"] == "EXPIRED"

    def test_accept_quote_after_expiry_rejected(self, api):
        """PRD §3.3: "Acceptance is permitted only while the quote is `ISSUED` and the
        current time is at or before its `expires_at`; if the quote has passed
        `expires_at`, acceptance is rejected with `ERR_QUOTE_EXPIRED`."

        Design: Corner/state_machines/quote_accept_after_expiry_rejected
        """
        fx.set_clock("2026-04-01T00:00:00Z")
        ctx = fx.setup_finalized_config_scenario(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE",
            line_items=[{"component_type": "SHELF", "quantity": 8, "unit_price_cents": 5000}],
        )
        quote = fx.add_quote(ctx["project"]["id"], ctx["config"]["id"])
        quote = fx.issue_quote(quote["id"])
        fx.set_clock("2026-09-01T00:00:00Z")
        resp = api.accept_quote(quote["id"], make_customer_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED.value)

    def test_second_finalize_on_confirmed_measure_rejected(self, api):
        """PRD §3.2: "If the measure is already confirmed — meaning some other
        configuration has already been finalized against it — the finalize is rejected
        with `ERR_MEASURE_ALREADY_CONFIRMED`, enforcing the rule that a single space
        measure may back at most one finalized configuration."

        Design: Corner/state_machines/measure_already_confirmed_second_finalize_rejected
        """
        ctx = fx.setup_designing_project(zip_code="90001", room_type="WALK_IN_CLOSET")
        measure = fx.add_space_measure(ctx["project"]["id"])
        cfg1 = fx.add_component_config(
            ctx["project"]["id"], measure["id"], material_grade="MELAMINE",
            line_items=[{"component_type": "SHELF", "quantity": 8, "unit_price_cents": 5000}],
        )
        fx.finalize_config(cfg1["id"])
        cfg2 = fx.add_component_config(
            ctx["project"]["id"], measure["id"], material_grade="WOOD",
            line_items=[{"component_type": "SHELF", "quantity": 9, "unit_price_cents": 5000}],
        )
        resp = api.finalize_component_config(cfg2["id"], DESIGNER)
        validate_error(resp, ApiErrorId.ERR_MEASURE_ALREADY_CONFIRMED.value)

    def test_change_order_reject_then_fresh_resubmit(self, api):
        """PRD §3.7: "Its lifecycle is `SUBMITTED` → `APPROVED` → `APPLIED`, with
        `REJECTED` as an alternate terminal outcome; a rejected change can be resubmitted
        as a brand-new change order."

        Design: Corner/cross_cutting_complexity_layers/change_order_reject_then_resubmit_cycle
        """
        ctx = fx.setup_deposit_paid(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", deposit_amount=5000000,
        )
        proj, quote = ctx["project"], ctx["quote"]
        co1 = fx.submit_change_order(proj["id"], quote["id"], "SCHEDULE_CHANGE")
        co1 = fx.reject_change_order(co1["id"])
        assert co1["status"] == "REJECTED"
        co2 = fx.submit_change_order(proj["id"], quote["id"], "SCHEDULE_CHANGE")
        assert co2["status"] == "SUBMITTED"
