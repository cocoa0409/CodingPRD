"""Order completion, cancellation cascades, turnaround SLA, panel score, and the
appraiser-load conservation invariant.

Covers queue A (Difficulty) dual_variant_calc (turnaround), combinatorial_formula
(panel score), compensating_invariant (load conservation), plus queue B
state_machines (cancel cascade, terminal lockdown).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, factories, fixtures,
)

COORD = TEST_USERS["coordinator_headers"]


def test_turnaround_projected_vs_actual_diverge(api):
    """PRD §3.9: "the base SLA is 120 hours for `URAR_1004`".
    PRD §3.9: "At completion the **actual** turnaround is computed on the assignment's
    `actual_turnaround_hours`: the whole-hours elapsed from the assignment's `accepted_at`
    to the completion clock time, floored to a whole number of hours."

    Design: Difficulty/dual_variant_calc/turnaround_projected_vs_actual_diverges
    """
    # placement clock 06-01, accept 06-02, complete 06-04 (48h after accept); URAR no rush -> sla 120.
    res = fixtures.setup_order_completed_clean(
        order_fee_cents=60000, base_fee_share_pct=0.50, product_type="URAR_1004",
        placed_at="2026-06-01T00:00:00Z", accepted_at="2026-06-02T00:00:00Z",
        completed_at="2026-06-04T00:00:00Z",
    )
    order = res["order_after_complete"]
    asg = res["assignment_after_complete"]
    assert order["sla_hours"] == 120, f"projected URAR_1004 SLA must be 120, got {order['sla_hours']}"
    assert asg["actual_turnaround_hours"] == 48, (
        f"actual turnaround from accept to complete must be 48 whole hours, "
        f"got {asg['actual_turnaround_hours']}"
    )
    assert order["sla_hours"] != asg["actual_turnaround_hours"], "projected and actual must diverge"


def test_assignment_copies_projected_sla_at_creation(api):
    """PRD §3.9: "The order's `sla_hours` is fixed once placed, and the assignment copies
    it onto its own `sla_hours` at assignment creation as the clock it will be measured
    against."
    PRD §3.2: "copies the order's `sla_hours` onto the assignment's own `sla_hours`".

    Design: Difficulty/dual_variant_calc/turnaround_projected_vs_actual_diverges
    """
    # URAR_1004 no rush -> projected sla 120; the assignment must copy that value.
    base = fixtures.setup_order_ready_to_assign(product_type="URAR_1004")
    order = base["order"]
    assert order["sla_hours"] == 120, f"projected URAR_1004 SLA must be 120, got {order['sla_hours']}"
    asg = validate_success(
        api.create_assignment(order["id"], factories.assignment_create_payload(order["version"]), COORD),
        201,
    )
    assert asg["sla_hours"] == 120, (
        f"assignment must copy the order's projected sla_hours (120), got {asg['sla_hours']}"
    )


def test_panel_score_zero_when_suspended(api):
    """PRD §3.8: "When the appraiser's `status` is anything other than `ACTIVE`, the panel
    score is zero."
    PRD §3.1: "When a coordinator changes an appraiser's `status`, the panel score is
    recomputed; a move to `SUSPENDED` or `RETIRED` drives that score to zero."

    Design: Difficulty/combinatorial_formula/panel_score_weighted_nonlinear_three_inputs
    """
    appraiser = fixtures.create_appraiser(license_state="NY", full_name="Susp Score A")
    validate_success(
        api.set_appraiser_status(appraiser["id"], factories.set_appraiser_status_payload("SUSPENDED"), COORD),
        200,
    )
    data = validate_success(api.get_appraiser(appraiser["id"], COORD), 200)
    assert data["panel_score"] == 0.0, f"SUSPENDED appraiser panel_score must be 0, got {data['panel_score']}"


def test_appraiser_load_conserved_after_cancel(api):
    """PRD §3.8: "The `active_assignment_count` is the number of this appraiser's
    assignments whose status is not `DECLINED`, `CANCELLED`, or `COMPLETED` — a conserved
    quantity, incremented when an assignment is accepted and decremented on cascade-cancel
    and on completion."
    PRD §3.8: "the order's non-terminal assignment, if any, cascades to `CANCELLED` and the
    owning appraiser's `active_assignment_count` is decremented (preserving the conserved
    count)".

    Design: Difficulty/compensating_invariant/appraiser_load_conservation_on_cancel_compensation
    """
    base = fixtures.setup_order_ready_to_assign()
    order = base["order"]
    appraiser = base["appraiser"]
    asg = fixtures.assign_order(order["id"], order["version"])
    fixtures.accept_assignment(asg["id"], appraiser["id"])  # active_assignment_count -> 1
    v = fixtures.current_order_version(order["id"])
    validate_success(api.cancel_order(order["id"], factories.assignment_create_payload(v), COORD), 200)

    data = validate_success(api.get_appraiser(appraiser["id"], COORD), 200)
    assert data["active_assignment_count"] == 0, (
        f"cancel cascade must decrement active load back to 0, got {data['active_assignment_count']}"
    )
    asg_after = validate_success(api.get_assignment(asg["id"], COORD), 200)
    assert asg_after["status"] == "CANCELLED", f"accepted assignment must cascade to CANCELLED, got {asg_after['status']}"


def test_appraiser_load_conserved_after_completion(api):
    """PRD §3.8: "The `active_assignment_count` is the number of this appraiser's
    assignments whose status is not `DECLINED`, `CANCELLED`, or `COMPLETED` — a conserved
    quantity, incremented when an assignment is accepted and decremented on cascade-cancel
    and on completion."
    PRD §3.8: "The owning appraiser's counters are then refreshed: `active_assignment_count`
    is decremented (the conserved active load)".

    Design: Difficulty/compensating_invariant/appraiser_load_conservation_on_cancel_compensation
    """
    # Drive a clean order to COMPLETED; the completion path also decrements the active load.
    res = fixtures.setup_order_completed_clean(
        placed_at="2026-06-01T00:00:00Z", accepted_at="2026-06-02T00:00:00Z",
        completed_at="2026-06-04T00:00:00Z",
    )
    appraiser_id = res["appraiser"]["id"]
    data = validate_success(api.get_appraiser(appraiser_id, COORD), 200)
    assert data["active_assignment_count"] == 0, (
        f"completion must decrement active load back to 0 (conserved), got {data['active_assignment_count']}"
    )
    asg_after = res["assignment_after_complete"]
    assert asg_after["status"] == "COMPLETED", f"assignment must be COMPLETED, got {asg_after['status']}"


def test_cancel_in_qc_order_cascades_terminal_states(api):
    """PRD §3.8: "Cancellation advances the order to `CANCELLED` and runs several cascades:
    the order's non-terminal assignment, if any, cascades to `CANCELLED` and the owning
    appraiser's `active_assignment_count` is decremented (preserving the conserved count); a
    submitted report on a cancelled order cascades to `REJECTED`; the fee split is zeroed,
    with `appraiser_fee_cents` and `amc_fee_cents` both set to zero; and the lender's
    `committed_fee_cents` is recomputed so this order drops out of the current-month
    commitment."

    Design: Corner/state_machines/order_cancel_cascades_assignment_and_report_terminal
    """
    # IN_QC: assigned, accepted, report submitted, compliance opened (PENDING).
    base = fixtures.setup_order_in_qc(comparable_count=5)
    order = base["order"]
    v = fixtures.current_order_version(order["id"])
    validate_success(api.cancel_order(order["id"], factories.assignment_create_payload(v), COORD), 200)

    asg = validate_success(api.get_assignment(base["assignment"]["id"], COORD), 200)
    assert asg["status"] == "CANCELLED", f"assignment must cascade to CANCELLED, got {asg['status']}"
    report = validate_success(api.get_report(base["report"]["id"], COORD), 200)
    assert report["status"] == "REJECTED", f"submitted report must cascade to REJECTED, got {report['status']}"
    fee_split = validate_success(api.get_order_fee_split(order["id"], COORD), 200)[0]
    assert fee_split["appraiser_fee_cents"] == 0, f"cancelled fee split must zero appraiser share, got {fee_split['appraiser_fee_cents']}"


def test_cancel_completed_order_terminal_lockdown(api):
    """PRD §3.1: "The order's `status` ranges over `PLACED`, `ASSIGNED`, `IN_PROGRESS`,
    `IN_QC`, `DELIVERED`, `COMPLETED`, and `CANCELLED`, with `COMPLETED` and `CANCELLED`
    terminal."
    PRD §3.8: "A coordinator may cancel a non-terminal order — one in `PLACED`, `ASSIGNED`,
    `IN_PROGRESS`, or `IN_QC` — provided the supplied `expected_order_version` matches the
    order's `version`."

    Design: Corner/state_machines/cancel_completed_order_terminal_lockdown
    """
    res = fixtures.setup_order_completed_clean(
        placed_at="2026-06-01T00:00:00Z", accepted_at="2026-06-02T00:00:00Z",
        completed_at="2026-06-04T00:00:00Z",
    )
    order_id = res["order"]["id"]
    v = fixtures.current_order_version(order_id)
    resp = api.cancel_order(order_id, factories.assignment_create_payload(v), COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
