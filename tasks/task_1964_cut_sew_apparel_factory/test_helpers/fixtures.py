"""Composite setup helpers.

Most test claims need the system in a state that takes many API calls to reach
(approved pack -> planned order -> approved marker -> cut bundles -> released
bundle -> operator + assignment -> logged/verified entries -> audits/payroll).
These fixtures encapsulate the plumbing so tests can focus on assertions.

All helpers use get_success_data() internally so setup failures surface as
clear "Setup failed" errors instead of confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_fabric_roll_payload,
    create_line_assignment_payload,
    create_marker_payload,
    create_operation_spec_payload,
    create_operator_payload,
    create_payroll_run_payload,
    create_piece_work_entry_payload,
    create_production_order_payload,
    create_quality_audit_payload,
    create_sewing_line_payload,
    create_style_payload,
    create_tech_pack_payload,
    create_trim_item_payload,
    create_trim_requirement_payload,
)
from .test_users import (
    TEST_USERS,
    make_sewing_operator_headers,
)

MERCH = TEST_USERS["merchandiser_headers"]
MERCH_M1 = TEST_USERS["merchandiser_headers"]  # u-m1
MATS = TEST_USERS["materials_planner_headers"]
CUTMGR = TEST_USERS["cutting_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
SUPER = TEST_USERS["line_supervisor_headers"]
QI1 = TEST_USERS["quality_inspector_headers"]
QI2 = TEST_USERS["quality_inspector2_headers"]
CLERK = TEST_USERS["payroll_clerk_headers"]
PM = TEST_USERS["plant_manager_headers"]
PM2 = TEST_USERS["plant_manager2_headers"]
ANY = TEST_USERS["any_headers"]


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def create_style(merch_headers=None, **overrides):
    payload = create_style_payload(**overrides)
    return get_success_data(api_client.create_style(payload, merch_headers or MERCH))


def create_draft_tech_pack(style_id, merch_headers=None, **overrides):
    payload = create_tech_pack_payload(style_id=style_id, **overrides)
    return get_success_data(api_client.create_tech_pack(payload, merch_headers or MERCH))


def add_operation_spec(tech_pack_id, merch_headers=None, **overrides):
    payload = create_operation_spec_payload(tech_pack_id=tech_pack_id, **overrides)
    return get_success_data(api_client.create_operation_spec(payload, merch_headers or MERCH))


def add_trim_requirement(tech_pack_id, trim_item_id, merch_headers=None, **overrides):
    payload = create_trim_requirement_payload(
        tech_pack_id=tech_pack_id, trim_item_id=trim_item_id, **overrides
    )
    return get_success_data(api_client.create_trim_requirement(payload, merch_headers or MERCH))


def submit_tech_pack(tech_pack_id, merch_headers=None):
    return get_success_data(api_client.submit_tech_pack(tech_pack_id, merch_headers or MERCH))


def review_tech_pack(tech_pack_id, decision, expected_style_version, pm_headers=None):
    return get_success_data(
        api_client.review_tech_pack(
            tech_pack_id,
            {"decision": decision, "expected_style_version": expected_style_version},
            pm_headers or PM,
        )
    )


def get_style(style_id):
    return get_success_data(api_client.get_style(style_id, ANY))


def approve_tech_pack(tech_pack_id, pm_headers=None):
    """Submit + APPROVE the pack; re-points style.active_tech_pack_id. Returns pack."""
    submit_tech_pack(tech_pack_id, MERCH)
    style = get_style(get_success_data(api_client.get_tech_pack(tech_pack_id, ANY))["style_id"])
    return review_tech_pack(tech_pack_id, "APPROVE", style["version"], pm_headers or PM)


def create_available_fabric_roll(mats_headers=None, **overrides):
    """Create a roll and record QC PASS. Returns the roll (status AVAILABLE)."""
    roll = get_success_data(
        api_client.create_fabric_roll(create_fabric_roll_payload(**overrides), mats_headers or MATS)
    )
    return get_success_data(
        api_client.record_fabric_qc(roll["id"], {"result": "PASS"}, mats_headers or MATS)
    )


def create_trim_item(mats_headers=None, **overrides):
    return get_success_data(
        api_client.create_trim_item(create_trim_item_payload(**overrides), mats_headers or MATS)
    )


def receive_trim(trim_item_id, qty, mats_headers=None):
    return get_success_data(
        api_client.receive_trim_item(trim_item_id, {"qty": qty}, mats_headers or MATS)
    )


def create_production_order(style_id, planner_headers=None, **overrides):
    payload = create_production_order_payload(style_id=style_id, **overrides)
    return get_success_data(
        api_client.create_production_order(payload, planner_headers or PLANNER)
    )


def plan_order(order_id, tech_pack_id, planner_headers=None):
    return get_success_data(
        api_client.plan_production_order(
            order_id, {"tech_pack_id": tech_pack_id}, planner_headers or PLANNER
        )
    )


def create_operator(super_headers=None, **overrides):
    return get_success_data(
        api_client.create_operator(create_operator_payload(**overrides), super_headers or SUPER)
    )


def create_sewing_line(planner_headers=None, **overrides):
    return get_success_data(
        api_client.create_sewing_line(create_sewing_line_payload(**overrides), planner_headers or PLANNER)
    )


def create_line_assignment(sewing_line_id, order_id, operation_spec_id, operator_id,
                           super_headers=None, **overrides):
    payload = create_line_assignment_payload(
        sewing_line_id=sewing_line_id,
        production_order_id=order_id,
        operation_spec_id=operation_spec_id,
        operator_id=operator_id,
        **overrides,
    )
    return get_success_data(api_client.create_line_assignment(payload, super_headers or SUPER))


def log_piece_work(bundle_id, operation_spec_id, operator_id, **overrides):
    """Log a piece-work entry as the entity-backed SewingOperator caller."""
    payload = create_piece_work_entry_payload(
        bundle_id=bundle_id, operation_spec_id=operation_spec_id, **overrides
    )
    return get_success_data(
        api_client.create_piece_work_entry(payload, make_sewing_operator_headers(operator_id))
    )


def verify_entry(entry_id, super_headers=None):
    return get_success_data(
        api_client.review_piece_work_entry(entry_id, {"decision": "VERIFY"}, super_headers or SUPER)
    )


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — approved pack, planned order, cut bundle
# ---------------------------------------------------------------------------

def setup_style_with_approved_pack(style_overrides=None, pack_overrides=None,
                                   ops=None, trim_lines=None, merch_headers=None):
    """Style + DRAFT pack + ops/trim lines + submit + APPROVE.

    ops: list of operation-spec override dicts (default: one op).
    trim_lines: list of (trim_item_id, overrides) pairs.
    Returns (style, pack, ops_list).
    """
    merch = merch_headers or MERCH
    style = create_style(merch, **(style_overrides or {}))
    pack = create_draft_tech_pack(style["id"], merch, **(pack_overrides or {}))
    ops_list = []
    for op_over in (ops if ops is not None else [{}]):
        ops_list.append(add_operation_spec(pack["id"], merch, **op_over))
    for trim_item_id, req_over in (trim_lines or []):
        add_trim_requirement(pack["id"], trim_item_id, merch, **req_over)
    pack = approve_tech_pack(pack["id"], PM)
    style = get_style(style["id"])
    return style, pack, ops_list


def setup_planned_order_with_bundle(order_qty, size="M", style_overrides=None,
                                    pack_overrides=None, ops=None, trim_lines=None,
                                    marker_length_yards=40.0, received_yards=41.3,
                                    color="navy"):
    """Approved pack -> order -> plan -> roll QC PASS -> marker approve ->
    start-cutting -> cut -> one bundle per size line.

    Returns dict with keys: style, pack, ops, order, roll, marker, bundles.
    """
    style, pack, ops_list = setup_style_with_approved_pack(
        style_overrides=style_overrides, pack_overrides=pack_overrides,
        ops=ops, trim_lines=trim_lines,
    )
    order = create_production_order(
        style["id"], PLANNER, color=color, size_quantities=[{"size": size, "qty": order_qty}]
    )
    order = plan_order(order["id"], pack["id"], PLANNER)
    roll = create_available_fabric_roll(MATS, received_yards=received_yards)
    marker = get_success_data(api_client.create_marker(
        create_marker_payload(
            production_order_id=order["id"], fabric_roll_id=roll["id"],
            marker_length_yards=marker_length_yards, planned_pieces=order_qty,
        ),
        CUTMGR,
    ))
    marker = get_success_data(api_client.approve_marker(
        marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR
    ))
    order = get_success_data(api_client.start_cutting(order["id"], PLANNER))
    marker = get_success_data(api_client.cut_marker(
        marker["id"], {"size_quantities": [{"size": size, "qty": order_qty}]}, CUTMGR
    ))
    # list endpoint is paginated; unwrap via the paginated validator.
    from prd_bench_local_runner.testing import validate_paginated
    bundle_list, _ = validate_paginated(
        api_client.list_bundles(ANY, params={"marker_id": marker["id"]})
    )
    return {
        "style": style, "pack": pack, "ops": ops_list, "order": order,
        "roll": get_success_data(api_client.get_fabric_roll(roll["id"], ANY)),
        "marker": marker, "bundles": bundle_list,
    }


def setup_released_bundle_with_operator(order_qty=10, size="M", ops=None,
                                        work_date="2026-08-03",
                                        assign_start=480, assign_end=580,
                                        assigned_pieces=None, **kwargs):
    """Full floor setup: cut bundle released; operator with a line assignment
    matching (order, op, shift_date == work_date).

    Returns the setup dict from setup_planned_order_with_bundle plus keys
    operator, line, assignment, bundle (the released first bundle).
    """
    ctx = setup_planned_order_with_bundle(order_qty, size=size, ops=ops, **kwargs)
    bundle = ctx["bundles"][0]
    bundle = get_success_data(api_client.release_bundle(bundle["id"], SUPER))
    operator = create_operator(SUPER)
    line = create_sewing_line(PLANNER)
    op_id = ctx["ops"][0]["id"]
    assignment = create_line_assignment(
        line["id"], ctx["order"]["id"], op_id, operator["id"], SUPER,
        shift_date=work_date, start_minute=assign_start, end_minute=assign_end,
        assigned_pieces=assigned_pieces if assigned_pieces is not None else order_qty,
    )
    ctx.update({
        "operator": operator, "line": line, "assignment": assignment, "bundle": bundle,
    })
    return ctx


def setup_completed_bundle(order_qty=2, size="M", **kwargs):
    """Released bundle driven to COMPLETED: one full-qty entry logged + verified
    for each op of the pinned pack. Returns the floor-setup context."""
    ctx = setup_released_bundle_with_operator(order_qty=order_qty, size=size, **kwargs)
    entry = log_piece_work(
        ctx["bundle"]["id"], ctx["ops"][0]["id"], ctx["operator"]["id"], qty=order_qty
    )
    entry = verify_entry(entry["id"], SUPER)
    bundle = get_success_data(api_client.get_bundle(ctx["bundle"]["id"], ANY))
    ctx["entry"] = entry
    ctx["bundle"] = bundle
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle — payroll
# ---------------------------------------------------------------------------

def setup_verified_entry_for_payroll(order_qty=100, sam_seconds=54, piece_rate_cents=12,
                                     work_date="2026-08-03", assign_minutes=100):
    """The canonical payroll shape from the design index: one VERIFIED entry on
    work_date with the operator assigned `assign_minutes` minutes that day.
    earned_minutes = order_qty * sam_seconds / 60; attended = assign_minutes."""
    ctx = setup_released_bundle_with_operator(
        order_qty=order_qty,
        ops=[{"sam_seconds": sam_seconds, "piece_rate_cents": piece_rate_cents,
              "machine_type": "OVERLOCK", "name": "join sides"}],
        work_date=work_date, assign_start=480, assign_end=480 + assign_minutes,
        assigned_pieces=order_qty,
    )
    entry = log_piece_work(
        ctx["bundle"]["id"], ctx["ops"][0]["id"], ctx["operator"]["id"],
        work_date=work_date, qty=order_qty,
    )
    entry = verify_entry(entry["id"], SUPER)
    ctx["entry"] = entry
    return ctx


def create_open_payroll_run(clerk_headers=None, **overrides):
    return get_success_data(
        api_client.create_payroll_run(create_payroll_run_payload(**overrides),
                                      clerk_headers or CLERK)
    )


def calculate_payroll_run(run_id, expected_version, clerk_headers=None):
    return get_success_data(
        api_client.calculate_payroll_run(
            run_id, {"expected_payroll_run_version": expected_version},
            clerk_headers or CLERK,
        )
    )


def setup_calculated_payroll_run(clerk_headers=None, **run_overrides):
    """Create a run and calculate it (empty sweep allowed). Returns CALCULATED run."""
    clerk = clerk_headers or CLERK
    run = create_open_payroll_run(clerk, **run_overrides)
    return calculate_payroll_run(run["id"], run["version"], clerk)


# ---------------------------------------------------------------------------
# Tier 4: quality audit lifecycle
# ---------------------------------------------------------------------------

def create_audit(order_id, qi_headers=None, **overrides):
    payload = create_quality_audit_payload(production_order_id=order_id, **overrides)
    return get_success_data(api_client.create_quality_audit(payload, qi_headers or QI1))


def record_audit(audit_id, defects_found, qi_headers=None):
    return get_success_data(
        api_client.record_quality_audit(audit_id, {"defects_found": defects_found},
                                        qi_headers or QI1)
    )


def setup_order_with_failed_audit(order_qty=2, defects=1, **kwargs):
    """Order with one COMPLETED bundle; audit recorded FAIL; order QC_FAILED.

    Returns (ctx, audit).
    """
    ctx = setup_completed_bundle(order_qty=order_qty, **kwargs)
    audit = create_audit(ctx["order"]["id"], QI1)
    audit = record_audit(audit["id"], defects, QI1)
    return ctx, audit


def setup_rework_recorded_audit(order_qty=2, defects=1, **kwargs):
    """Failed audit taken through rework-complete -> REWORK_RECORDED.

    Returns (ctx, audit) with order quality_status REWORK_IN_PROGRESS.
    """
    ctx, audit = setup_order_with_failed_audit(order_qty=order_qty, defects=defects, **kwargs)
    audit = get_success_data(api_client.rework_complete_quality_audit(audit["id"], QI1))
    return ctx, audit


def setup_qc_passed_order(order_qty=2, **kwargs):
    """Order with one COMPLETED bundle and a PASS audit -> quality QC_PASSED."""
    ctx = setup_completed_bundle(order_qty=order_qty, **kwargs)
    audit = create_audit(ctx["order"]["id"], QI1)
    audit = record_audit(audit["id"], 0, QI1)
    ctx["audit"] = audit
    ctx["order"] = get_success_data(api_client.get_production_order(ctx["order"]["id"], ANY))
    return ctx
