"""Validation priority conflicts, boundary precision, cross-entity preconditions,
and crew/window scheduling rules.

Difficulty queue: priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap.
Corner queue: validations section (window/change-target/finance), endpoints (balance).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    fixtures as fx, factories as f,
    make_customer_headers,
)
from test_helpers.fixtures import DESIGNER, SCHEDULER, MFG_OPS, ADMIN, MELAMINE_18_UNITS


SHELF_10 = [{"component_type": "SHELF", "quantity": 10, "unit_price_cents": 5000}]


# ===========================================================================
# Rule 5 — validation priority conflicts
# ===========================================================================
class TestValidationPriorityConflicts:
    def test_order_state_check_beats_window_before_ready(self, api):
        """PRD §2.10: "Then the target resource's current state is checked against the
        requested transition (`ERR_INVALID_STATE`), followed by the optimistic-concurrency
        version checks on the two guarded writes (`ERR_STALE_PROJECT_VERSION`, then
        `ERR_STALE_QUOTE_VERSION`). Only after these structural checks pass does the
        system evaluate the domain-specific business rules"
        PRD §3.6: "Booking requires that the job's `sched_status` is `PROPOSED`, the job's
        manufacture order is `READY`, the crew is active, the crew's `region` equals the
        project's `install_region`, the `window_start` is at or after the manufacture
        order's `promised_ready_date`, and the crew has sufficient daily capacity for the
        window's day."

        Design: Difficulty/priority_pair_validation_conflict/lead_time_state_beats_window_before_ready_temporal
        """
        # Manufacture order still QUEUED (not READY); window before any promised date.
        fx.set_clock("2026-04-01T00:00:00Z")
        ctx = fx.setup_deposit_paid(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10, deposit_amount=5000000,
        )
        crew = fx.create_crew(region="WEST", daily_capacity_units=100, crew_name="W-state")
        job = fx.propose_install_job(
            ctx["project"]["id"], ctx["manufacture_order"]["id"], crew["id"],
            "2026-04-15T08:00:00Z", "2026-04-15T16:00:00Z",
        )
        resp = api.book_install_job(job["id"], SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_window_check_surfaces_once_order_state_passes(self, api):
        """PRD §2.10: "Then the target resource's current state is checked against the
        requested transition (`ERR_INVALID_STATE`), followed by the optimistic-concurrency
        version checks on the two guarded writes (`ERR_STALE_PROJECT_VERSION`, then
        `ERR_STALE_QUOTE_VERSION`). Only after these structural checks pass does the
        system evaluate the domain-specific business rules"
        PRD §3.6: "The `window_start` must also be at or after the manufacture order's
        `promised_ready_date`; a window starting before the order is promised ready is
        rejected with `ERR_WINDOW_BEFORE_READY`."

        Design: Difficulty/priority_pair_validation_conflict/lead_time_state_beats_window_before_ready_temporal
        """
        # Same window 2026-04-15 as the companion test, proposed while the order is still
        # QUEUED (promised_ready_date null, so the proposal-time window check does not yet
        # apply). The order is then driven to READY, stamping promised_ready_date to
        # 2026-04-21 (start 2026-04-01 + 20-day lead). The state precondition now passes,
        # so at booking the window-before-ready business check surfaces — confirming it
        # was masked by the ERR_INVALID_STATE check while the order was still QUEUED.
        fx.set_clock("2026-04-01T00:00:00Z")
        ctx = fx.setup_deposit_paid(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10, deposit_amount=5000000,
        )
        crew = fx.create_crew(region="WEST", daily_capacity_units=100, crew_name="W-after")
        # Propose while QUEUED: promised_ready_date is null, so the window is accepted.
        job = fx.propose_install_job(
            ctx["project"]["id"], ctx["manufacture_order"]["id"], crew["id"],
            "2026-04-15T08:00:00Z", "2026-04-15T16:00:00Z",
        )
        mo = fx.start_manufacture(ctx["manufacture_order"]["id"])
        assert mo["promised_ready_date"].startswith("2026-04-21")
        fx.set_clock("2026-04-21T00:00:00Z")
        fx.complete_manufacture(mo["id"])
        # Window 2026-04-15 is now before promised_ready_date 2026-04-21.
        resp = api.book_install_job(job["id"], SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_WINDOW_BEFORE_READY.value)

    def test_crew_region_mismatch_beats_capacity(self, api):
        """PRD §2.10: "Only after these structural checks pass does the system evaluate
        the domain-specific business rules — region matching, measure confirmation,
        lead-time gates, scheduling-window validity, quote expiry, crew capacity, warranty
        coverage and branch matching, deposit floors, financing limits, configuration
        finalization, and change-target validity"
        PRD §3.6: "A crew whose region does not match the project's region is rejected
        with `ERR_CREW_REGION_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/crew_region_referential_beats_capacity_constraint
        """
        # Project WEST, ManufactureOrder READY; crew EAST with capacity 1 (job 10 units > 1).
        ctx = fx.setup_ready_to_install(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10,
        )
        crew = fx.create_crew(region="EAST", daily_capacity_units=1, crew_name="East-mini")
        job = fx.propose_install_job(
            ctx["project"]["id"], ctx["manufacture_order"]["id"], crew["id"],
            "2026-05-10T08:00:00Z", "2026-05-10T16:00:00Z",
        )
        resp = api.book_install_job(job["id"], SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_CREW_REGION_MISMATCH.value)

    def test_capacity_check_surfaces_once_region_matches(self, api):
        """PRD §2.10: "the system evaluate the domain-specific business rules — region
        matching, measure confirmation, lead-time gates, scheduling-window validity, quote
        expiry, crew capacity, warranty coverage and branch matching"
        PRD §3.6: "the booking is allowed only if that already-booked total plus this
        job's units is at most the crew's `daily_capacity_units`; if the sum would exceed
        the capacity, the booking is rejected with `ERR_CREW_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/crew_region_referential_beats_capacity_constraint
        """
        # Crew region WEST matches the project; single job's 10 units exceed capacity 1.
        # With region matching, the capacity error surfaces — confirming region was the
        # earlier-ranked check in the prior test.
        ctx = fx.setup_ready_to_install(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10,
        )
        crew = fx.create_crew(region="WEST", daily_capacity_units=1, crew_name="W-mini")
        job = fx.propose_install_job(
            ctx["project"]["id"], ctx["manufacture_order"]["id"], crew["id"],
            "2026-05-10T08:00:00Z", "2026-05-10T16:00:00Z",
        )
        resp = api.book_install_job(job["id"], SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED.value)


# ===========================================================================
# Rule 6 — boundary precision
# ===========================================================================
class TestBoundaryPrecision:
    def test_manufacture_complete_exactly_at_promised_ready_allowed(self, api):
        """PRD §3.5: "An attempt to complete before the promised ready date — that is,
        when the current time is earlier than `promised_ready_date` — is rejected with
        `ERR_LEAD_TIME_NOT_ELAPSED`; the boundary is inclusive, so completing exactly at
        `promised_ready_date` is allowed."

        Design: Difficulty/boundary_precision_check/lead_time_complete_exactly_at_promised_ready_date_inclusive
        """
        fx.set_clock("2026-04-01T00:00:00Z")
        ctx = fx.setup_deposit_paid(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10, deposit_amount=5000000,
        )
        mo = fx.start_manufacture(ctx["manufacture_order"]["id"])
        assert mo["lead_time_days"] == 20
        assert mo["promised_ready_date"].startswith("2026-04-21")
        # complete exactly at promised_ready_date (inclusive >=).
        fx.set_clock("2026-04-21T00:00:00Z")
        completed = get_success_data(api.complete_manufacture_order(mo["id"], MFG_OPS))
        assert completed["status"] == "READY"

    def test_manufacture_complete_one_second_before_ready_rejected(self, api):
        """PRD §3.5: "An attempt to complete before the promised ready date — that is,
        when the current time is earlier than `promised_ready_date` — is rejected with
        `ERR_LEAD_TIME_NOT_ELAPSED`; the boundary is inclusive, so completing exactly at
        `promised_ready_date` is allowed."

        Design: Difficulty/boundary_precision_check/lead_time_complete_exactly_at_promised_ready_date_inclusive
        """
        fx.set_clock("2026-04-01T00:00:00Z")
        ctx = fx.setup_deposit_paid(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10, deposit_amount=5000000,
        )
        mo = fx.start_manufacture(ctx["manufacture_order"]["id"])
        # one second before promised_ready_date 2026-04-21T00:00:00Z.
        fx.set_clock("2026-04-20T23:59:59Z")
        resp = api.complete_manufacture_order(mo["id"], MFG_OPS)
        validate_error(resp, ApiErrorId.ERR_LEAD_TIME_NOT_ELAPSED.value)

    def test_finalize_empty_line_items_rejected(self, api):
        """PRD §3.2: "Finalizing a configuration is the act that prepares it for pricing.
        It is permitted only when the configuration is in `DRAFT`, its `line_items` are
        non-empty, and the backing space measure is not yet confirmed."

        Design: Difficulty/boundary_precision_check/config_finalize_empty_line_items_zero_set_rejected
        """
        ctx = fx.setup_designing_project(zip_code="90001", room_type="WALK_IN_CLOSET")
        measure = fx.add_space_measure(ctx["project"]["id"])
        cfg = get_success_data(api.create_component_config(
            ctx["project"]["id"],
            f.create_component_config_payload(measure["id"], material_grade="MELAMINE", line_items=[]),
            DESIGNER,
        ))
        resp = api.finalize_component_config(cfg["id"], DESIGNER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_finalize_single_line_item_succeeds(self, api):
        """PRD §3.2: "Finalizing a configuration is the act that prepares it for pricing.
        It is permitted only when the configuration is in `DRAFT`, its `line_items` are
        non-empty, and the backing space measure is not yet confirmed."

        Design: Difficulty/boundary_precision_check/config_finalize_empty_line_items_zero_set_rejected
        """
        # The other side of the empty-set boundary: a one-element line_items array
        # (smallest non-empty set) finalizes successfully.
        ctx = fx.setup_designing_project(zip_code="90001", room_type="WALK_IN_CLOSET")
        measure = fx.add_space_measure(ctx["project"]["id"])
        cfg = fx.add_component_config(
            ctx["project"]["id"], measure["id"], material_grade="MELAMINE",
            line_items=[{"component_type": "SHELF", "quantity": 1, "unit_price_cents": 5000}],
        )
        finalized = get_success_data(api.finalize_component_config(cfg["id"], DESIGNER))
        assert finalized["status"] == "FINALIZED"


# ===========================================================================
# Rule 7 — cross-entity state dependency
# ===========================================================================
class TestCrossEntityStateDependency:
    def test_install_book_requires_manufacture_order_ready(self, api):
        """PRD §3.6: "Booking requires that the job's `sched_status` is `PROPOSED`, the
        job's manufacture order is `READY`, the crew is active, the crew's `region` equals
        the project's `install_region`, the `window_start` is at or after the manufacture
        order's `promised_ready_date`, and the crew has sufficient daily capacity for the
        window's day."

        Design: Difficulty/cross_entity_state_dependency/install_book_requires_manufacture_order_ready_pair_job_order
        """
        # ManufactureOrder IN_PRODUCTION (started but not completed); job proposed.
        fx.set_clock("2026-04-01T00:00:00Z")
        ctx = fx.setup_deposit_paid(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10, deposit_amount=5000000,
        )
        mo = fx.start_manufacture(ctx["manufacture_order"]["id"])
        assert mo["status"] == "IN_PRODUCTION"
        crew = fx.create_crew(region="WEST", daily_capacity_units=100, crew_name="W-prod")
        job = fx.propose_install_job(
            ctx["project"]["id"], mo["id"], crew["id"],
            "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
        )
        resp = api.book_install_job(job["id"], SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_install_book_succeeds_once_manufacture_order_ready(self, api):
        """PRD §3.6: "Booking requires that the job's `sched_status` is `PROPOSED`, the
        job's manufacture order is `READY`, the crew is active, the crew's `region` equals
        the project's `install_region`, the `window_start` is at or after the manufacture
        order's `promised_ready_date`, and the crew has sufficient daily capacity for the
        window's day."
        PRD §3.6: "Booking a proposed job moves its `sched_status` from `PROPOSED` to
        `BOOKED`."

        Design: Difficulty/cross_entity_state_dependency/install_book_requires_manufacture_order_ready_pair_job_order
        """
        # Order driven all the way to READY: the InstallJob book now succeeds.
        ctx = fx.setup_ready_to_install(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10,
        )
        assert ctx["manufacture_order"]["status"] == "READY"
        crew = fx.create_crew(region="WEST", daily_capacity_units=100, crew_name="W-rdy")
        job = fx.propose_install_job(
            ctx["project"]["id"], ctx["manufacture_order"]["id"], crew["id"],
            "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
        )
        booked = get_success_data(api.book_install_job(job["id"], SCHEDULER))
        assert booked["sched_status"] == "BOOKED"

    def test_quote_issue_succeeds_once_config_finalized(self, api):
        """PRD §3.3: "Issuing a quote moves it from `DRAFT` to `ISSUED`, but only if the
        quote is in `DRAFT` and its referenced configuration is `FINALIZED`; otherwise the
        issue is rejected with `ERR_CONFIG_NOT_FINALIZED`."

        Design: Difficulty/cross_entity_state_dependency/quote_issue_requires_config_finalized_pair_quote_config
        """
        # The same Quote->ComponentConfig pairing, with the config now FINALIZED: issue OK.
        ctx = fx.setup_finalized_config_scenario(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10,
        )
        assert ctx["config"]["status"] == "FINALIZED"
        quote = fx.add_quote(ctx["project"]["id"], ctx["config"]["id"])
        issued = get_success_data(api.issue_quote(quote["id"], DESIGNER))
        assert issued["status"] == "ISSUED"


# ===========================================================================
# Rule 8 — resource temporal overlap
# ===========================================================================
class TestResourceTemporalOverlap:
    def test_crew_same_day_aggregate_capacity_overflow(self, api):
        """PRD §3.6: "The capacity check works on the UTC calendar date of `window_start`:
        the system sums the `units_booked` of every install job on the same crew with
        `sched_status` of `BOOKED` whose `window_start` falls on that same calendar day,
        and the booking is allowed only if that already-booked total plus this job's units
        is at most the crew's `daily_capacity_units`; if the sum would exceed the capacity,
        the booking is rejected with `ERR_CREW_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/crew_same_day_aggregate_capacity_overflow
        """
        fx.set_clock("2026-04-01T00:00:00Z")
        crew = fx.create_crew(region="WEST", daily_capacity_units=12, crew_name="West-cap")
        # Project 1: 10-unit job booked on 2026-05-10.
        ctx1 = fx.setup_ready_to_install(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10,
        )
        job1 = fx.propose_install_job(
            ctx1["project"]["id"], ctx1["manufacture_order"]["id"], crew["id"],
            "2026-05-10T08:00:00Z", "2026-05-10T12:00:00Z",
        )
        fx.book_install_job(job1["id"])
        # Project 2: 5-unit job, same crew, same day; 10+5=15 > 12.
        ctx2 = fx.setup_ready_to_install(
            zip_code="90002", room_type="GARAGE",
            material_grade="MELAMINE",
            line_items=[{"component_type": "SHELF", "quantity": 5, "unit_price_cents": 5000}],
            start_clock="2026-04-01T00:00:00Z", ready_clock="2026-05-05T00:00:00Z",
        )
        job2 = fx.propose_install_job(
            ctx2["project"]["id"], ctx2["manufacture_order"]["id"], crew["id"],
            "2026-05-10T13:00:00Z", "2026-05-10T17:00:00Z",
        )
        resp = api.book_install_job(job2["id"], SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED.value)

    def test_crew_same_day_sum_exactly_at_capacity_allowed(self, api):
        """PRD §3.6: "The boundary is inclusive: a total exactly equal to
        `daily_capacity_units` is permitted, and only a total strictly greater than it is
        refused."

        Design: Difficulty/resource_temporal_overlap/crew_same_day_aggregate_capacity_overflow
        """
        fx.set_clock("2026-04-01T00:00:00Z")
        crew = fx.create_crew(region="WEST", daily_capacity_units=15, crew_name="West-cap2")
        ctx1 = fx.setup_ready_to_install(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10,
        )
        job1 = fx.propose_install_job(
            ctx1["project"]["id"], ctx1["manufacture_order"]["id"], crew["id"],
            "2026-05-10T08:00:00Z", "2026-05-10T12:00:00Z",
        )
        fx.book_install_job(job1["id"])
        # Second 5-unit job, same crew, same day: 10 + 5 == 15 == capacity (inclusive OK).
        ctx2 = fx.setup_ready_to_install(
            zip_code="90002", room_type="GARAGE",
            material_grade="MELAMINE",
            line_items=[{"component_type": "SHELF", "quantity": 5, "unit_price_cents": 5000}],
            start_clock="2026-04-01T00:00:00Z", ready_clock="2026-05-05T00:00:00Z",
        )
        job2 = fx.propose_install_job(
            ctx2["project"]["id"], ctx2["manufacture_order"]["id"], crew["id"],
            "2026-05-10T13:00:00Z", "2026-05-10T17:00:00Z",
        )
        booked = get_success_data(api.book_install_job(job2["id"], SCHEDULER))
        assert booked["sched_status"] == "BOOKED"

    def test_install_window_before_promised_ready_rejected(self, api):
        """PRD §3.6: "At proposal time the window must be valid ... The `window_start`
        must also be at or after the manufacture order's `promised_ready_date`; a window
        starting before the order is promised ready is rejected with
        `ERR_WINDOW_BEFORE_READY`."

        Design: Difficulty/resource_temporal_overlap/install_window_must_start_on_or_after_promised_ready_date
        """
        ctx = fx.setup_ready_to_install(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10,
        )
        # promised_ready_date is 2026-05-05; the manufacture order is already READY, so
        # the proposal-time window-start check is live and a window starting 2026-05-04
        # (before promised ready) is rejected at proposal.
        assert ctx["manufacture_order"]["promised_ready_date"].startswith("2026-05-05")
        crew = fx.create_crew(region="WEST", daily_capacity_units=100, crew_name="W-wbr")
        resp = api.create_install_job(
            f.create_install_job_payload(
                ctx["project"]["id"], ctx["manufacture_order"]["id"], crew["id"],
                "2026-05-04T08:00:00Z", "2026-05-04T16:00:00Z",
            ),
            SCHEDULER,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_BEFORE_READY.value)

    def test_install_window_starting_at_promised_ready_allowed(self, api):
        """PRD §3.6: "The `window_start` must also be at or after the manufacture order's
        `promised_ready_date`; a window starting before the order is promised ready is
        rejected with `ERR_WINDOW_BEFORE_READY`."

        Design: Difficulty/resource_temporal_overlap/install_window_must_start_on_or_after_promised_ready_date
        """
        # promised_ready_date is 2026-05-05; a window starting exactly at it (inclusive
        # "at or after") books successfully — the other side of the half-open lower bound.
        ctx = fx.setup_ready_to_install(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10,
        )
        assert ctx["manufacture_order"]["promised_ready_date"].startswith("2026-05-05")
        crew = fx.create_crew(region="WEST", daily_capacity_units=100, crew_name="W-atready")
        job = fx.propose_install_job(
            ctx["project"]["id"], ctx["manufacture_order"]["id"], crew["id"],
            "2026-05-05T08:00:00Z", "2026-05-05T16:00:00Z",
        )
        booked = get_success_data(api.book_install_job(job["id"], SCHEDULER))
        assert booked["sched_status"] == "BOOKED"


# ===========================================================================
# Corner — validations section + endpoints (balance read)
# ===========================================================================
class TestValidationCorners:
    def test_finance_exceeds_total_at_submit(self, api):
        """PRD §3.9: "this is permitted only while the application is `DRAFT`, its quote
        is `ACCEPTED`, and the `requested_amount_cents` is at most the quote's
        `total_cents`. A request to finance more than the quote total is rejected with
        `ERR_FINANCE_EXCEEDS_TOTAL`."

        Design: Corner/validations/finance_exceeds_total_at_submit
        """
        ctx = fx.setup_accepted_quote(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS,
        )
        proj, quote, customer = ctx["project"], ctx["quote"], ctx["customer"]
        app = fx.create_financing_application(proj["id"], quote["id"], 80000, 24, customer["id"])
        resp = api.submit_financing_application(app["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_FINANCE_EXCEEDS_TOTAL.value)

    def test_invalid_window_end_not_after_start(self, api):
        """PRD §3.6: "At proposal time the window must be valid: `window_end` must be
        strictly after `window_start`, and both must fall on the same UTC calendar day; a
        window that violates either condition is rejected with `ERR_INVALID_WINDOW`."

        Design: Corner/validations/invalid_window_end_not_after_start
        """
        ctx = fx.setup_ready_to_install(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10,
        )
        crew = fx.create_crew(region="WEST", daily_capacity_units=100, crew_name="W-iw")
        resp = api.create_install_job(
            f.create_install_job_payload(
                ctx["project"]["id"], ctx["manufacture_order"]["id"], crew["id"],
                "2026-05-10T08:00:00Z", "2026-05-10T08:00:00Z",
            ),
            SCHEDULER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)

    def test_change_target_invalid_schedule_change_with_config(self, api):
        """PRD §3.7: "A change order that supplies the wrong combination — a
        `CONFIG_REVISION` missing or naming a non-finalized `revised_config_id`, or a
        `SCHEDULE_CHANGE` that supplies a `revised_config_id` — is rejected with
        `ERR_CHANGE_TARGET_INVALID`."

        Design: Corner/validations/change_target_invalid_schedule_change_with_config
        """
        ctx = fx.setup_deposit_paid(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10, deposit_amount=5000000,
        )
        proj, quote = ctx["project"], ctx["quote"]
        # SCHEDULE_CHANGE that wrongly supplies a revised_config_id.
        resp = api.create_change_order(
            {
                "project_id": proj["id"], "base_quote_id": quote["id"],
                "change_type": "SCHEDULE_CHANGE",
                "revised_config_id": ctx["config"]["id"],
            },
            DESIGNER,
        )
        validate_error(resp, ApiErrorId.ERR_CHANGE_TARGET_INVALID.value)

    def test_balance_computed_read_matches_reconciliation(self, api):
        """PRD §3.8: "The balance is the project's accepted-quote total (taken from the
        quote referenced by `accepted_quote_id`, or zero if none is set yet) minus the sum
        of the `amount_cents` of every deposit of the project whose status is `CAPTURED`,
        minus the financed amount."

        Design: Corner/endpoints/balance_computed_read_matches_reconciliation
        """
        ctx = fx.setup_deposit_paid(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS, deposit_amount=17820,
        )
        bal = validate_success(api.get_project_balance(ctx["project"]["id"], ADMIN))
        # 71280 accepted - 17820 captured deposit - 0 financed = 53460.
        assert bal["balance_due_cents"] == 53460
