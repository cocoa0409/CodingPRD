"""Work orders: provisional vs final pricing, production pipeline, bay windows,
cancel cascades, and the cloth-ledger invariant."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_sail_design,
    create_work_order,
    drive_job_to_finishing,
    drive_job_to_qc_passed,
    get_cloth_bolt,
    get_production_job,
    get_sail_design,
    get_work_order,
    lock_work_order,
    schedule_production_job,
    setup_approved_design,
    setup_delivered_work_order,
    setup_locked_work_order,
    setup_open_work_order_with_bolt,
    start_cutting,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    TEST_USERS,
)

MGR = TEST_USERS["loft_manager_headers"]
SAIL = TEST_USERS["sailmaker_headers"]


# ---------------------------------------------------------------------------
# Provisional (forward-looking) vs final (chronological) pricing — PRD §3.4/§3.5
# ---------------------------------------------------------------------------

def test_provisional_quote_differs_from_final_invoice_when_option_declined(api):
    """PRD §3.4: "Being forward-looking, this provisional variant takes the
    design's `option_codes` and `reinforcement_level` as-is, and it may include
    options the customer later declines at fit check."
    PRD §3.5: "Options the customer declined at fit check are excluded, which is
    precisely how the invoice can diverge from the quote."

    Design: Difficulty/dual_variant_calc/work_order_provisional_vs_final_invoice_diverge
    """
    ctx = setup_delivered_work_order(cloth_tier="RACE", option_codes=["BATTENS"], fitted_option_codes=[])
    order = ctx["work_order"]
    # Provisional: (61.50 * 9500 + 18000) * 1.00 = 602250 — includes BATTENS.
    assert order["quoted_total_cents"] == 602250, (
        f"provisional quote must include the design's BATTENS option: {order['quoted_total_cents']}"
    )
    # Final: 61.50 * 9500 + 0 fitted options = 584250 — BATTENS declined.
    assert order["invoiced_total_cents"] == 584250, (
        f"final invoice must exclude the declined option: {order['invoiced_total_cents']}"
    )
    assert order["quoted_total_cents"] != order["invoiced_total_cents"]


def test_final_invoice_includes_options_actually_fitted(api):
    """PRD §3.5: "The invoice subtotal is the sum of those job shares plus the
    flat fees of the options actually fitted at fit check — the same per-option
    price list as the provisional quote — and the total is rounded half-up to
    whole cents."

    Design: Difficulty/dual_variant_calc/work_order_provisional_vs_final_invoice_diverge
    """
    ctx = setup_delivered_work_order(
        cloth_tier="RACE", option_codes=["BATTENS"], fitted_option_codes=["BATTENS"]
    )
    order = ctx["work_order"]
    # Final: 61.50 * 9500 + 18000 (BATTENS actually fitted) = 602250.
    assert order["invoiced_total_cents"] == 602250, (
        f"final invoice must add the fitted option's flat fee: {order['invoiced_total_cents']}"
    )
    assert order["quoted_total_cents"] == 602250


# ---------------------------------------------------------------------------
# Tiered multi-input provisional quote — PRD §3.4
# ---------------------------------------------------------------------------

def test_quote_with_heavy_duty_surcharge_and_class_complexity(api):
    """PRD §3.4: "When the measured area is strictly greater than 150.00 square
    metres, the heavy-duty surcharge increases that base by 4 percent for each
    level of the design's `reinforcement_level` — that is, the base is multiplied
    by one plus 0.04 times the reinforcement level."
    PRD §3.4: "The base plus the option fees is multiplied by a class-complexity
    factor keyed on the boat's `racing_class` — 1.00 for `NONE`, 1.00 for `PHRF`,
    1.05 for `ORC`, 1.05 for `J70`, 1.08 for `J105`, and 1.15 for `TP52` — and the
    result is rounded half-up to a whole number of cents."

    Design: Difficulty/combinatorial_formula/sail_price_tiered_multi_input_mode_a
    """
    ctx = setup_locked_work_order(
        racing_class="TP52", hull_length_m=15.6,
        i_height_m=21.0, j_base_m=6.0, p_main_m=22.0, e_main_m=8.0,
        cloth_tier="CRUISE", reinforcement_level=2, option_codes=["BATTENS", "UV_STRIP"],
    )
    # area = 0.5*22*8 + 0.5*21*6 = 88 + 63 = 151.00 (> 150.00 -> surcharge)
    # base = 151.00 * 4200 * (1 + 0.04*2) = 684936; options 18000 + 9000 = 27000
    # (684936 + 27000) * 1.15 = 818726.4 -> round half-up -> 818726
    assert ctx["work_order"]["quoted_total_cents"] == 818726, (
        f"got {ctx['work_order']['quoted_total_cents']}"
    )


def test_quote_surcharge_scales_with_reinforcement_level(api):
    """PRD §3.4: "the base is multiplied by one plus 0.04 times the reinforcement
    level."

    Design: Difficulty/combinatorial_formula/sail_price_tiered_multi_input_mode_a
    """
    ctx = setup_locked_work_order(
        racing_class="TP52", hull_length_m=15.6,
        i_height_m=21.0, j_base_m=6.0, p_main_m=22.0, e_main_m=8.0,
        cloth_tier="CRUISE", reinforcement_level=1, option_codes=["BATTENS", "UV_STRIP"],
    )
    # base = 151.00 * 4200 * 1.04 = 659568; (659568 + 27000) * 1.15 = 789553.2 -> 789553
    assert ctx["work_order"]["quoted_total_cents"] == 789553, (
        f"got {ctx['work_order']['quoted_total_cents']}"
    )


# ---------------------------------------------------------------------------
# Boundary: measured area exactly 150.00 (strict >) — PRD §3.4
# ---------------------------------------------------------------------------

def test_area_exactly_150_skips_heavy_duty_surcharge(api):
    """PRD §3.4: "When the measured area is strictly greater than 150.00 square
    metres, the heavy-duty surcharge increases that base by 4 percent for each
    level of the design's `reinforcement_level`"

    Design: Difficulty/boundary_precision_check/sail_area_exactly_150_no_heavy_duty_surcharge
    """
    ctx = setup_locked_work_order(
        racing_class="NONE", hull_length_m=14.0,
        i_height_m=15.0, j_base_m=8.0, p_main_m=20.0, e_main_m=9.0,
        cloth_tier="CRUISE", reinforcement_level=3, option_codes=[],
    )
    # area = 0.5*20*9 + 0.5*15*8 = 90 + 60 = 150.00 exactly -> NO surcharge
    sheet = validate_success(api.get_measurement_sheet(ctx["sheet"]["id"], MGR))
    assert float(sheet["measured_area_sqm"]) == pytest.approx(150.00, abs=1e-6)
    # quoted = 150.00 * 4200 * 1.00 = 630000 (reinforcement_level 3 irrelevant)
    assert ctx["work_order"]["quoted_total_cents"] == 630000, (
        f"150.00 is not strictly greater than 150.00: {ctx['work_order']['quoted_total_cents']}"
    )


def test_area_just_over_150_applies_surcharge(api):
    """PRD §3.4: "When the measured area is strictly greater than 150.00 square
    metres, the heavy-duty surcharge increases that base by 4 percent for each
    level of the design's `reinforcement_level`"

    Design: Difficulty/boundary_precision_check/sail_area_exactly_150_no_heavy_duty_surcharge
    """
    ctx = setup_locked_work_order(
        racing_class="NONE", hull_length_m=14.0,
        i_height_m=15.0, j_base_m=8.0, p_main_m=20.0, e_main_m=9.01,
        cloth_tier="CRUISE", reinforcement_level=3, option_codes=[],
    )
    # area = 0.5*20*9.01 + 0.5*15*8 = 90.10 + 60 = 150.10 (> 150.00 -> surcharge)
    sheet = validate_success(api.get_measurement_sheet(ctx["sheet"]["id"], MGR))
    assert float(sheet["measured_area_sqm"]) == pytest.approx(150.10, abs=1e-6)
    # quoted = 150.10 * 4200 * 1.12 = 706070.4 -> round half-up -> 706070
    assert ctx["work_order"]["quoted_total_cents"] == 706070, (
        f"got {ctx['work_order']['quoted_total_cents']}"
    )


# ---------------------------------------------------------------------------
# QC failure loop: QC_FAILED -> SCHEDULED — PRD §3.4
# ---------------------------------------------------------------------------

def test_qc_failed_job_reschedules_back_to_scheduled(api):
    """PRD §3.4: "Failing quality control moves `FINISHING` to `QC_FAILED` and
    stores the sailmaker's `qc_notes` from the payload."
    PRD §3.4: "a `QC_FAILED` job can be rescheduled into a fresh bay window,
    moving it back to `SCHEDULED`; the reschedule re-runs the bay-turnaround check
    against the new dates and recomputes the reservation on the new window."

    Design: Difficulty/non_linear_state_machine/production_job_qc_fail_loops_back_to_scheduled
    """
    ctx = setup_locked_work_order(hull_length_m=11.0)
    wo_id = ctx["work_order"]["id"]
    job = schedule_production_job(wo_id, bay_code="BAY_B",
                                  scheduled_start_date="2026-09-10", scheduled_end_date="2026-09-12")
    drive_job_to_finishing(wo_id, job["id"])

    failed = validate_success(api.qc_fail(wo_id, job["id"], {"qc_notes": "seam puckering"}, SAIL))
    assert failed["job_status"] == "QC_FAILED"
    assert failed["qc_notes"] == "seam puckering", "qc-fail must store the payload's qc_notes"

    rescheduled = validate_success(
        api.reschedule_job(
            wo_id, job["id"],
            {"bay_code": "BAY_B", "scheduled_start_date": "2026-09-20", "scheduled_end_date": "2026-09-22"},
            SAIL,
        )
    )
    assert rescheduled["job_status"] == "SCHEDULED", (
        f"reschedule must return the job to SCHEDULED, got {rescheduled['job_status']}"
    )
    assert rescheduled["scheduled_start_date"] == "2026-09-20"
    assert rescheduled["scheduled_end_date"] == "2026-09-22"


def test_rescheduled_job_completes_pipeline(api):
    """PRD §3.4: "a `QC_FAILED` job can be rescheduled into a fresh bay window,
    moving it back to `SCHEDULED`" — the reworked job then runs the pipeline
    again, and "when every non-cancelled sibling job under the same work order has
    also reached `QC_PASSED` — bubbles the parent from `IN_PRODUCTION` to
    `READY_FOR_FIT_CHECK`."

    Design: Difficulty/non_linear_state_machine/production_job_qc_fail_loops_back_to_scheduled
    """
    ctx = setup_locked_work_order(hull_length_m=11.0)
    wo_id = ctx["work_order"]["id"]
    job = schedule_production_job(wo_id, bay_code="BAY_B",
                                  scheduled_start_date="2026-09-10", scheduled_end_date="2026-09-12")
    drive_job_to_finishing(wo_id, job["id"])
    validate_success(api.qc_fail(wo_id, job["id"], {"qc_notes": "panel mismatch"}, SAIL))
    validate_success(
        api.reschedule_job(
            wo_id, job["id"],
            {"bay_code": "BAY_B", "scheduled_start_date": "2026-09-20", "scheduled_end_date": "2026-09-22"},
            SAIL,
        )
    )

    passed = drive_job_to_qc_passed(wo_id, job["id"])
    assert passed["job_status"] == "QC_PASSED"
    order = get_work_order(wo_id)
    assert order["order_status"] == "READY_FOR_FIT_CHECK", (
        f"parent must bubble to READY_FOR_FIT_CHECK, got {order['order_status']}"
    )


# ---------------------------------------------------------------------------
# Cancel cascade: three hops — PRD §3.4
# ---------------------------------------------------------------------------

def test_cancel_open_order_cascades_three_hops(api):
    """PRD §3.4: "Cancelling an `OPEN` work order moves it to `CANCELLED` and
    cascades in three hops: first, every production job of the order in
    `SCHEDULED`, `CUTTING`, `SEAMING`, or `FINISHING` transitions to `CANCELLED`;
    second, each such cancellation releases its `reserved_cloth_sqm` back to the
    cloth ledger and the bolt's `available_sqm` is recomputed; third, if the
    pinned sail design has no other non-cancelled work order referencing it, that
    design transitions to `ARCHIVED`."

    Design: Difficulty/transitive_cascade/work_order_cancel_cascades_three_hops
    """
    ctx = setup_open_work_order_with_bolt(hull_length_m=11.0)
    wo_id = ctx["work_order"]["id"]
    job = schedule_production_job(wo_id, bay_code="BAY_A",
                                  scheduled_start_date="2026-10-01", scheduled_end_date="2026-10-03")

    cancelled = validate_success(api.cancel_work_order(wo_id, MGR))
    assert cancelled["order_status"] == "CANCELLED"

    assert get_production_job(job["id"])["job_status"] == "CANCELLED", "hop 1: job must be CANCELLED"
    bolt = get_cloth_bolt(ctx["bolt"]["id"])
    assert float(bolt["available_sqm"]) == pytest.approx(500.0, abs=1e-6), (
        f"hop 2: reservation must be released (500.0), got {bolt['available_sqm']}"
    )
    design = get_sail_design(ctx["design"]["id"])
    assert design["design_status"] == "ARCHIVED", (
        f"hop 3: orphaned design must be ARCHIVED, got {design['design_status']}"
    )


def test_cancel_leaves_design_approved_when_another_order_references_it(api):
    """PRD §3.4: "third, if the pinned sail design has no other non-cancelled work
    order referencing it, that design transitions to `ARCHIVED`." — the archival
    is conditional on the design being orphaned.

    Design: Difficulty/transitive_cascade/work_order_cancel_cascades_three_hops
    """
    ctx = setup_open_work_order_with_bolt(hull_length_m=11.0)
    design_id = ctx["design"]["id"]
    wo_a = ctx["work_order"]
    job_a = schedule_production_job(wo_a["id"], bay_code="BAY_A",
                                    scheduled_start_date="2026-10-01", scheduled_end_date="2026-10-03")
    # A second OPEN order pins the same design (no production job of its own).
    wo_b = create_work_order(ctx["customer"]["id"], ctx["boat"]["id"],
                             order_kind="NEW_SAIL", sail_design_id=design_id)

    validate_success(api.cancel_work_order(wo_a["id"], MGR))

    assert get_work_order(wo_a["id"])["order_status"] == "CANCELLED"
    assert get_production_job(job_a["id"])["job_status"] == "CANCELLED"
    bolt = get_cloth_bolt(ctx["bolt"]["id"])
    assert float(bolt["available_sqm"]) == pytest.approx(500.0, abs=1e-6)
    design = get_sail_design(design_id)
    assert design["design_status"] == "APPROVED", (
        f"design still referenced by a non-cancelled order must survive, got {design['design_status']}"
    )
    assert get_work_order(wo_b["id"])["order_status"] == "OPEN"


# ---------------------------------------------------------------------------
# Cross-entity gate: cutting requires the pinned design APPROVED — PRD §3.4
# ---------------------------------------------------------------------------

def test_start_cutting_rejected_after_design_superseded(api):
    """PRD §3.4: "Starting cutting moves a job from `SCHEDULED` to `CUTTING` and
    is permitted only while the parent work order is in `DESIGN_LOCKED` or
    `IN_PRODUCTION` and the pinned design is `APPROVED`"
    PRD §3.3: "When a prior design for the same boat is sitting in `APPROVED`,
    creating a new revision transitions that prior design from `APPROVED` to
    `SUPERSEDED`"
    PRD §2.5: "Fourth, the generic source-state legality of the requested
    transition is verified (failure yields `ERR_INVALID_STATE`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/production_cutting_requires_design_approved
    """
    ctx = setup_locked_work_order(hull_length_m=11.0)
    wo_id = ctx["work_order"]["id"]
    job = schedule_production_job(wo_id, bay_code="BAY_C",
                                  scheduled_start_date="2026-09-15", scheduled_end_date="2026-09-17")
    # A second revision supersedes the pinned design; the locked order survives
    # because the cancel-on-supersede rule covers only OPEN orders (PRD §3.3).
    create_sail_design(ctx["boat"]["id"], ctx["sheet"]["id"], cloth_tier="PERFORMANCE")
    prior = get_sail_design(ctx["design"]["id"])
    assert prior["design_status"] == "SUPERSEDED"
    assert get_work_order(wo_id)["order_status"] == "DESIGN_LOCKED"

    resp = api.start_cutting(wo_id, job["id"], SAIL)
    # PRD §3.4 pins the gate ("permitted only while ... the pinned design is
    # APPROVED") but names no error_id for it: §2.5's step-4 generic state
    # legality supports ERR_INVALID_STATE, while the catalogue's design-state
    # error supports ERR_DESIGN_NOT_IN_REQUIRED_STATE. Both are faithful.
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_DESIGN_NOT_IN_REQUIRED_STATE]
    )
    assert get_production_job(job["id"])["job_status"] == "SCHEDULED", (
        "rejected start-cutting must leave the job SCHEDULED"
    )


def test_start_cutting_bubbles_parent_to_in_production(api):
    """PRD §3.4: "when the first job under an order starts cutting, the parent
    bubbles from `DESIGN_LOCKED` to `IN_PRODUCTION` automatically."

    Design: Difficulty/cross_entity_state_dependency/production_cutting_requires_design_approved
    """
    ctx = setup_locked_work_order(hull_length_m=11.0)
    wo_id = ctx["work_order"]["id"]
    job = schedule_production_job(wo_id, bay_code="BAY_C",
                                  scheduled_start_date="2026-09-15", scheduled_end_date="2026-09-17")

    started = start_cutting(wo_id, job["id"])
    assert started["job_status"] == "CUTTING"
    order = get_work_order(wo_id)
    assert order["order_status"] == "IN_PRODUCTION", (
        f"parent must bubble to IN_PRODUCTION, got {order['order_status']}"
    )


# ---------------------------------------------------------------------------
# Bay windows: closed interval + one full turnaround day — PRD §2.10
# ---------------------------------------------------------------------------

def _setup_two_locked_orders_same_bay():
    """Two locked NEW_SAIL orders pinning one design; the first holds BAY_A
    2026-09-01..2026-09-05 inclusive."""
    ctx = setup_locked_work_order(hull_length_m=11.0)
    job_a = schedule_production_job(ctx["work_order"]["id"], bay_code="BAY_A",
                                    scheduled_start_date="2026-09-01", scheduled_end_date="2026-09-05")
    wo_b = create_work_order(ctx["customer"]["id"], ctx["boat"]["id"],
                             order_kind="NEW_SAIL", sail_design_id=ctx["design"]["id"])
    lock_work_order(wo_b["id"])
    return ctx, job_a, wo_b


def test_bay_window_next_day_start_conflicts(api):
    """PRD §2.10: "In effect, at least one full calendar day of turnaround must
    separate one job's last day in a bay from the next job's first day in that
    same bay." and "A scheduling or rescheduling request that violates this rule
    is rejected with `ERR_BAY_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/bay_window_closed_interval_with_turnaround_gap
    """
    _, job_a, wo_b = _setup_two_locked_orders_same_bay()
    # Prior job's last day 2026-09-05; starting 2026-09-06 leaves no full gap day.
    resp = api.create_production_job(
        wo_b["id"],
        {"bay_code": "BAY_A", "scheduled_start_date": "2026-09-06", "scheduled_end_date": "2026-09-08"},
        SAIL,
    )
    validate_error(resp, ApiErrorId.ERR_BAY_WINDOW_CONFLICT)


def test_bay_window_full_gap_day_allowed(api):
    """PRD §2.10: "In effect, at least one full calendar day of turnaround must
    separate one job's last day in a bay from the next job's first day in that
    same bay. Jobs in `CANCELLED` status are excluded from the conflict set."

    Design: Difficulty/resource_temporal_overlap/bay_window_closed_interval_with_turnaround_gap
    """
    _, job_a, wo_b = _setup_two_locked_orders_same_bay()
    # Starting 2026-09-07 leaves 2026-09-06 as the full turnaround day.
    job_b = schedule_production_job(wo_b["id"], bay_code="BAY_A",
                                    scheduled_start_date="2026-09-07", scheduled_end_date="2026-09-09")
    assert job_b["job_status"] == "SCHEDULED", (
        f"a full gap day must satisfy the turnaround rule, got {job_b['job_status']}"
    )


# ---------------------------------------------------------------------------
# Cloth ledger invariant: reserve then release restores availability — PRD §2.9
# ---------------------------------------------------------------------------

def test_qc_pass_restores_cloth_availability(api):
    """PRD §2.9: "Reservations are returned to the ledger in exactly two
    circumstances — when a job passes quality control, and when a job is cancelled
    — and each return recomputes the bolt's `available_sqm`."

    Design: Difficulty/compensating_invariant/cloth_available_sqm_restored_after_qc_pass_release
    """
    ctx = setup_locked_work_order(hull_length_m=11.0)
    wo_id = ctx["work_order"]["id"]
    bolt_id = ctx["bolt"]["id"]
    job = schedule_production_job(wo_id, bay_code="BAY_B",
                                  scheduled_start_date="2026-09-20", scheduled_end_date="2026-09-22")
    drive_job_to_finishing(wo_id, job["id"])

    passed = validate_success(api.qc_pass(wo_id, job["id"], SAIL))
    assert passed["job_status"] == "QC_PASSED"
    bolt = get_cloth_bolt(bolt_id)
    assert float(bolt["available_sqm"]) == pytest.approx(500.0, abs=1e-6), (
        f"reserve+release round-trip must restore 500.0 exactly, got {bolt['available_sqm']}"
    )


def test_cloth_reservation_visible_then_released(api):
    """PRD §2.9: "its `available_sqm` is derived, not stored by hand — it equals
    the bolt's `total_sqm` minus the sum of `reserved_cloth_sqm` across all
    non-terminal production jobs booked against that bolt."
    PRD §2.9: "Reservations are returned to the ledger in exactly two
    circumstances — when a job passes quality control, and when a job is cancelled
    — and each return recomputes the bolt's `available_sqm`."

    Design: Difficulty/compensating_invariant/cloth_available_sqm_restored_after_qc_pass_release
    """
    ctx = setup_locked_work_order(hull_length_m=11.0)
    wo_id = ctx["work_order"]["id"]
    bolt_id = ctx["bolt"]["id"]
    job = schedule_production_job(wo_id, bay_code="BAY_B",
                                  scheduled_start_date="2026-09-20", scheduled_end_date="2026-09-22")

    during = get_cloth_bolt(bolt_id)
    assert float(during["available_sqm"]) == pytest.approx(438.5, abs=1e-6), (
        f"500.0 - 61.50 reserved must show 438.5, got {during['available_sqm']}"
    )
    drive_job_to_qc_passed(wo_id, job["id"])
    after = get_cloth_bolt(bolt_id)
    assert float(after["available_sqm"]) == pytest.approx(500.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Corner: terminal lockdown, cloth shortage, ledger read
# ---------------------------------------------------------------------------

def test_cancelled_work_order_rejects_further_transitions(api):
    """PRD §3.4: "A `LoftManager` locks an `OPEN` order into `DESIGN_LOCKED`" —
    `CANCELLED` is a terminal status, and PRD §2.5: "Fourth, the generic
    source-state legality of the requested transition is verified (failure yields
    `ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/work_order_terminal_cancelled_rejects_further_transitions
    """
    ctx = setup_approved_design()
    order = create_work_order(ctx["customer"]["id"], ctx["boat"]["id"], order_kind="RIGGING_SERVICE")
    cancelled = validate_success(api.cancel_work_order(order["id"], MGR))
    assert cancelled["order_status"] == "CANCELLED"

    resp = api.lock_design(order["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_cloth_shortage_rejects_job_scheduling(api):
    """PRD §2.9: "If the reservation exceeds what is available for that tier,
    scheduling is rejected with `ERR_CLOTH_SHORTAGE` (HTTP 409)."

    Design: Corner/validations/cloth_shortage_rejects_job_scheduling
    """
    # 50.0 sqm bolt but the 61.50 sqm design needs more.
    ctx = setup_locked_work_order(hull_length_m=11.0, cloth_total_sqm=50.0)
    resp = api.create_production_job(
        ctx["work_order"]["id"],
        {"bay_code": "BAY_A", "scheduled_start_date": "2026-12-01", "scheduled_end_date": "2026-12-03"},
        SAIL,
    )
    validate_error(resp, ApiErrorId.ERR_CLOTH_SHORTAGE)


def test_cloth_ledger_reflects_reservation(api):
    """PRD §2.9: "its `available_sqm` is derived, not stored by hand — it equals
    the bolt's `total_sqm` minus the sum of `reserved_cloth_sqm` across all
    non-terminal production jobs booked against that bolt. Registering a bolt
    initializes `available_sqm` to `total_sqm`."

    Design: Corner/endpoints/get_cloth_ledger_reflects_reservation
    """
    ctx = setup_locked_work_order(hull_length_m=11.0)
    schedule_production_job(ctx["work_order"]["id"], bay_code="BAY_C",
                            scheduled_start_date="2026-12-10", scheduled_end_date="2026-12-12")

    bolt = validate_success(api.get_cloth_bolt(ctx["bolt"]["id"], SAIL))
    assert float(bolt["available_sqm"]) == pytest.approx(438.5, abs=1e-6), (
        f"500.0 total - 61.50 reserved must read 438.5, got {bolt['available_sqm']}"
    )
