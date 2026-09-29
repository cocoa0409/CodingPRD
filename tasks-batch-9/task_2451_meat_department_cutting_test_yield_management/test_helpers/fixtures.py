"""Composite setup helpers.

The harness restarts the server before every test, so each test starts against
an empty database with the logical clock at its initial instant. Everything a
test needs is therefore built here from scratch through the public endpoints —
nothing is seeded behind the API's back.

These helpers only *build state*. They return the created resources so that the
test itself owns every assertion about derived values.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import DEPARTMENT_DEFAULTS, FIXTURE_CLOCK, TEST_DEFAULTS
from .factories import (
    case_plan_line_payload,
    case_plan_payload,
    cutting_test_line_payload,
    cutting_test_payload,
    department_payload,
    fill_payload,
    grind_input_payload,
    grind_run_payload,
    markdown_payload,
    pre_order_payload,
    price_activation_payload,
    price_proposal_payload,
    primal_purchase_payload,
    retail_item_payload,
    shrink_event_payload,
    shrink_reconciliation_payload,
    temperature_log_payload,
    transition_payload,
    trim_lot_payload,
)
from .test_users import TEST_USERS

# Header shortcuts, so a composite helper reads like the narrative it builds.
ADMIN = TEST_USERS["store_admin_headers"]
CUTTER = TEST_USERS["meat_cutter_headers"]
CUTTER_2 = TEST_USERS["second_meat_cutter_headers"]
MANAGER = TEST_USERS["meat_manager_headers"]
MANAGER_2 = TEST_USERS["second_meat_manager_headers"]
ANALYST = TEST_USERS["pricing_analyst_headers"]
CLERK = TEST_USERS["service_clerk_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock. Only a StoreAdmin may drive it."""
    return get_success_data(api.set_clock(current_utc, ADMIN), 200)


# ---------------------------------------------------------------------------
# Departments and catalogue
# ---------------------------------------------------------------------------

def create_department(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_department(department_payload(**overrides), ADMIN), 201
    )


def read_department(api: ApiClient, department_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_department(department_id, headers or ADMIN), 200)


def create_retail_item(api: ApiClient, department_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_retail_item(retail_item_payload(department_id, **overrides), ADMIN),
        201,
    )


def create_ground_item(api: ApiClient, department_id: str, **overrides) -> Dict[str, Any]:
    """A GROUND item — its cost basis can only ever come from a grind blend."""
    fields: Dict[str, Any] = {
        "item_code": TEST_DEFAULTS["GRD80_ITEM_CODE"],
        "subprimal_code": TEST_DEFAULTS["GRD80_SUBPRIMAL_CODE"],
        "product_class": "GROUND",
    }
    fields.update(overrides)
    return create_retail_item(api, department_id, **fields)


def read_retail_item(api: ApiClient, item_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_retail_item(item_id, headers or MANAGER), 200)


# ---------------------------------------------------------------------------
# Primal purchases
# ---------------------------------------------------------------------------

def create_primal_purchase(api: ApiClient, department_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_primal_purchase(
            primal_purchase_payload(department_id, **overrides), CUTTER
        ),
        201,
    )


def read_primal_purchase(api: ApiClient, purchase_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_primal_purchase(purchase_id, headers or CUTTER), 200)


# ---------------------------------------------------------------------------
# Cutting tests
# ---------------------------------------------------------------------------

def create_cutting_test(
    api: ApiClient,
    purchase_id: str,
    test_weight_lb: float,
    expected_version: int,
    headers=None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_cutting_test(
            cutting_test_payload(purchase_id, test_weight_lb, expected_version),
            headers or CUTTER,
        ),
        201,
    )


def add_cutting_test_line(
    api: ApiClient,
    test_id: str,
    line_seq: int,
    subprimal_code: str,
    disposition: str,
    yield_weight_lb: float,
    market_value_per_lb_cents: int,
    lean_pct: Optional[float] = None,
    retail_item_id: Optional[str] = None,
    headers=None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_cutting_test_line(
            test_id,
            cutting_test_line_payload(
                line_seq,
                subprimal_code,
                disposition,
                yield_weight_lb,
                market_value_per_lb_cents,
                lean_pct=lean_pct,
                retail_item_id=retail_item_id,
            ),
            headers or CUTTER,
        ),
        201,
    )


def read_cutting_test(api: ApiClient, test_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_cutting_test(test_id, headers or CUTTER), 200)


def read_cutting_test_line(api: ApiClient, line_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_cutting_test_line(line_id, headers or CUTTER), 200)


def submit_cutting_test(api: ApiClient, test_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_cutting_test(test_id, transition_payload("SUBMIT"), headers or CUTTER),
        200,
    )


def approve_cutting_test(api: ApiClient, test_id: str, headers=None) -> Dict[str, Any]:
    """Approval must come from an operator other than the submitter."""
    return get_success_data(
        api.transition_cutting_test(test_id, transition_payload("APPROVE"), headers or MANAGER),
        200,
    )


def reject_cutting_test(
    api: ApiClient, test_id: str, reason: str = "Bench weight does not tie out", headers=None
) -> Dict[str, Any]:
    return get_success_data(
        api.transition_cutting_test(
            test_id, transition_payload("REJECT", rejection_reason=reason), headers or MANAGER
        ),
        200,
    )


def revise_cutting_test(api: ApiClient, test_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_cutting_test(test_id, transition_payload("REVISE"), headers or CUTTER),
        200,
    )


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

def propose_price(api: ApiClient, item_id: str, purchase_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.create_price_proposal(
            item_id, price_proposal_payload(purchase_id), headers or ANALYST
        ),
        201,
    )


def activate_price_from_cutting_test(
    api: ApiClient, item_id: str, expected_version: int, cutting_test_id: str, headers=None
) -> Dict[str, Any]:
    return get_success_data(
        api.create_price_activation(
            item_id,
            price_activation_payload(expected_version, cutting_test_id=cutting_test_id),
            headers or MANAGER,
        ),
        201,
    )


def activate_price_from_grind_run(
    api: ApiClient, item_id: str, expected_version: int, grind_run_id: str, headers=None
) -> Dict[str, Any]:
    return get_success_data(
        api.create_price_activation(
            item_id,
            price_activation_payload(expected_version, grind_run_id=grind_run_id),
            headers or MANAGER,
        ),
        201,
    )


def suspend_retail_item(api: ApiClient, item_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_retail_item(item_id, transition_payload("SUSPEND"), headers or MANAGER),
        200,
    )


def reinstate_retail_item(api: ApiClient, item_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_retail_item(item_id, transition_payload("REINSTATE"), headers or MANAGER),
        200,
    )


# ---------------------------------------------------------------------------
# Case plans
# ---------------------------------------------------------------------------

def create_case_plan(
    api: ApiClient, department_id: str, service_date: str, headers=None
) -> Dict[str, Any]:
    return get_success_data(
        api.create_case_plan(
            case_plan_payload(department_id, service_date), headers or MANAGER
        ),
        201,
    )


def add_case_plan_line(
    api: ApiClient,
    plan_id: str,
    retail_item_id: str,
    line_seq: int,
    facings: int,
    expected_movement_lb: float,
    headers=None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_case_plan_line(
            plan_id,
            case_plan_line_payload(retail_item_id, line_seq, facings, expected_movement_lb),
            headers or MANAGER,
        ),
        201,
    )


def read_case_plan(api: ApiClient, plan_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_case_plan(plan_id, headers or MANAGER), 200)


def read_case_plan_line(api: ApiClient, line_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_case_plan_line(line_id, headers or MANAGER), 200)


def publish_case_plan(api: ApiClient, plan_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_case_plan(plan_id, transition_payload("PUBLISH"), headers or MANAGER),
        200,
    )


def suspend_case_plan(api: ApiClient, plan_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_case_plan(plan_id, transition_payload("SUSPEND"), headers or MANAGER),
        200,
    )


def resume_case_plan(api: ApiClient, plan_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_case_plan(plan_id, transition_payload("RESUME"), headers or MANAGER),
        200,
    )


def close_case_plan(api: ApiClient, plan_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_case_plan(plan_id, transition_payload("CLOSE"), headers or MANAGER),
        200,
    )


def fill_line(api: ApiClient, line_id: str, filled_lb: float, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.create_fill(line_id, fill_payload(filled_lb), headers or CUTTER), 201
    )


def mark_down_line(
    api: ApiClient,
    line_id: str,
    markdown_lb: float,
    markdown_price_per_lb_cents: int,
    headers=None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_markdown(
            line_id,
            markdown_payload(markdown_lb, markdown_price_per_lb_cents),
            headers or ANALYST,
        ),
        201,
    )


def write_off_line(api: ApiClient, line_id: str, shrink_lb: float, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.create_shrink_event(line_id, shrink_event_payload(shrink_lb), headers or MANAGER),
        201,
    )


# ---------------------------------------------------------------------------
# Trim lots, grind runs and grind inputs
# ---------------------------------------------------------------------------

def create_trim_lot_from_line(
    api: ApiClient,
    department_id: str,
    lot_code: str,
    received_lb: float,
    cutting_test_line_id: str,
    pack_date: Optional[str] = None,
    headers=None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_trim_lot(
            trim_lot_payload(
                department_id,
                lot_code,
                received_lb,
                pack_date or FIXTURE_CLOCK[:10],
                cutting_test_line_id=cutting_test_line_id,
            ),
            headers or CUTTER,
        ),
        201,
    )


def rework_trim_lot(
    api: ApiClient,
    department_id: str,
    lot_code: str,
    received_lb: float,
    source_trim_lot_id: str,
    pack_date: Optional[str] = None,
    headers=None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_trim_lot(
            trim_lot_payload(
                department_id,
                lot_code,
                received_lb,
                pack_date or FIXTURE_CLOCK[:10],
                source_trim_lot_id=source_trim_lot_id,
            ),
            headers or CUTTER,
        ),
        201,
    )


def read_trim_lot(api: ApiClient, lot_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_trim_lot(lot_id, headers or CUTTER), 200)


def discard_trim_lot(api: ApiClient, lot_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_trim_lot(lot_id, transition_payload("DISCARD"), headers or CUTTER),
        200,
    )


def create_grind_run(
    api: ApiClient,
    department_id: str,
    target_retail_item_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    declared_coo: str = "USA",
    target_lean_pct: float = 85.0,
    headers=None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_grind_run(
            grind_run_payload(
                department_id,
                target_retail_item_id,
                scheduled_start_at,
                scheduled_end_at,
                declared_coo=declared_coo,
                target_lean_pct=target_lean_pct,
                **overrides,
            ),
            headers or CUTTER,
        ),
        201,
    )


def add_grind_input(
    api: ApiClient,
    run_id: str,
    trim_lot_id: str,
    input_seq: int,
    weight_lb: float,
    headers=None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_grind_input(
            run_id, grind_input_payload(trim_lot_id, input_seq, weight_lb), headers or CUTTER
        ),
        201,
    )


def read_grind_run(api: ApiClient, run_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_grind_run(run_id, headers or CUTTER), 200)


def read_grind_input(api: ApiClient, input_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_grind_input(input_id, headers or CUTTER), 200)


def start_grind_run(api: ApiClient, run_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_grind_run(run_id, transition_payload("START"), headers or CUTTER), 200
    )


def complete_grind_run(api: ApiClient, run_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_grind_run(run_id, transition_payload("COMPLETE"), headers or CUTTER),
        200,
    )


def abort_grind_run(
    api: ApiClient, run_id: str, reason: str = "Grinder plate failure", headers=None
) -> Dict[str, Any]:
    return get_success_data(
        api.transition_grind_run(
            run_id, transition_payload("ABORT", abort_reason=reason), headers or MANAGER
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Cold chain
# ---------------------------------------------------------------------------

def post_reading(
    api: ApiClient, department_id: str, case_code: str, reading_c: float, headers=None
) -> Dict[str, Any]:
    return get_success_data(
        api.create_temperature_log(
            temperature_log_payload(department_id, case_code, reading_c), headers or CUTTER
        ),
        201,
    )


def read_case_failure(api: ApiClient, failure_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_case_failure(failure_id, headers or MANAGER), 200)


def list_case_failures(api: ApiClient, headers=None, params=None) -> Any:
    return api.list_case_failures(headers or MANAGER, params)


def only_case_failure(api: ApiClient, headers=None) -> Dict[str, Any]:
    """Return the single case failure the department has opened so far."""
    from prd_bench_local_runner.testing import validate_paginated

    rows, _meta = validate_paginated(api.list_case_failures(headers or MANAGER))
    assert len(rows) == 1, f"expected exactly one case failure, found {len(rows)}"
    return rows[0]


def contain_case_failure(
    api: ApiClient, failure_id: str, note: str = "Product moved to backup case", headers=None
) -> Dict[str, Any]:
    return get_success_data(
        api.transition_case_failure(
            failure_id, transition_payload("CONTAIN", containment_note=note), headers or CUTTER
        ),
        200,
    )


def escalate_case_failure(api: ApiClient, failure_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_case_failure(
            failure_id, transition_payload("ESCALATE"), headers or MANAGER
        ),
        200,
    )


def resolve_case_failure(
    api: ApiClient, failure_id: str, disposition: str = "NONE", headers=None
) -> Dict[str, Any]:
    """Resolution must come from an operator other than the reporter."""
    return get_success_data(
        api.transition_case_failure(
            failure_id, transition_payload("RESOLVE", disposition=disposition), headers or MANAGER
        ),
        200,
    )


def halt_department(
    api: ApiClient, department_id: str, case_code: str = "CASE-A"
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive the posture to SALES_HALTED with two consecutive out-of-spec
    readings, the second of which reaches the consecutive-failure threshold."""
    first = post_reading(api, department_id, case_code, 4.5)
    second = post_reading(api, department_id, case_code, 4.6)
    return first, second


def restrict_department(
    api: ApiClient, department_id: str, case_code: str = "CASE-A"
) -> Dict[str, Any]:
    """One out-of-spec reading leaves the run counter at 1, which is enough to
    make the posture SALES_RESTRICTED without opening a failure."""
    return post_reading(api, department_id, case_code, 4.5)


# ---------------------------------------------------------------------------
# Pre-orders
# ---------------------------------------------------------------------------

def create_pre_order(
    api: ApiClient,
    department_id: str,
    retail_item_id: str,
    requested_weight_lb: float,
    pickup_window_start_at: str,
    pickup_window_end_at: str,
    headers=None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_pre_order(
            pre_order_payload(
                department_id,
                retail_item_id,
                requested_weight_lb,
                pickup_window_start_at,
                pickup_window_end_at,
                **overrides,
            ),
            headers or CLERK,
        ),
        201,
    )


def read_pre_order(api: ApiClient, order_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_pre_order(order_id, headers or CLERK), 200)


def confirm_pre_order(api: ApiClient, order_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_pre_order(order_id, transition_payload("CONFIRM"), headers or CLERK), 200
    )


def amend_pre_order(api: ApiClient, order_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_pre_order(order_id, transition_payload("AMEND"), headers or CLERK), 200
    )


def stage_pre_order(
    api: ApiClient, order_id: str, case_plan_line_id: str, headers=None
) -> Dict[str, Any]:
    return get_success_data(
        api.transition_pre_order(
            order_id,
            transition_payload("STAGE", staged_case_plan_line_id=case_plan_line_id),
            headers or CUTTER,
        ),
        200,
    )


def pick_up_pre_order(api: ApiClient, order_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_pre_order(order_id, transition_payload("PICK_UP"), headers or CLERK), 200
    )


def cancel_pre_order(api: ApiClient, order_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_pre_order(order_id, transition_payload("CANCEL"), headers or CLERK), 200
    )


def forfeit_pre_order(api: ApiClient, order_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_pre_order(order_id, transition_payload("FORFEIT"), headers or MANAGER), 200
    )


# ---------------------------------------------------------------------------
# Reconciliations
# ---------------------------------------------------------------------------

def draft_reconciliation(
    api: ApiClient,
    department_id: str,
    period_start_date: str,
    period_end_date: str,
    basis: str = "YIELD_MODEL",
    headers=None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_shrink_reconciliation(
            shrink_reconciliation_payload(
                department_id, period_start_date, period_end_date, basis=basis
            ),
            headers or ANALYST,
        ),
        201,
    )


def read_reconciliation(api: ApiClient, recon_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_shrink_reconciliation(recon_id, headers or ANALYST), 200)


def post_reconciliation(
    api: ApiClient, recon_id: str, override_reason: Optional[str] = None, headers=None
) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    if override_reason is not None:
        fields["override_reason"] = override_reason
    return get_success_data(
        api.transition_shrink_reconciliation(
            recon_id, transition_payload("POST", **fields), headers or MANAGER
        ),
        200,
    )


def dispute_reconciliation(
    api: ApiClient, recon_id: str, reason: str = "Physical count disputed by the analyst", headers=None
) -> Dict[str, Any]:
    return get_success_data(
        api.transition_shrink_reconciliation(
            recon_id, transition_payload("DISPUTE", dispute_reason=reason), headers or ANALYST
        ),
        200,
    )


def redraft_reconciliation(api: ApiClient, recon_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.transition_shrink_reconciliation(
            recon_id, transition_payload("REDRAFT"), headers or ANALYST
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Composite scenarios — the recurring chains, each returning every row it made
# ---------------------------------------------------------------------------

def seeded_department(api: ApiClient, **overrides) -> Dict[str, Any]:
    """Clock pinned to the fixture instant plus a department on its defaults."""
    set_clock(api, FIXTURE_CLOCK)
    return create_department(api, **overrides)


def department_with_catalogue(api: ApiClient, **overrides) -> Dict[str, Any]:
    """Department, one WHOLE_MUSCLE item and one GROUND item."""
    department = seeded_department(api, **overrides)
    whole_muscle = create_retail_item(api, department["id"])
    ground = create_ground_item(api, department["id"])
    return {
        "department": department,
        "whole_muscle_item": whole_muscle,
        "ground_item": ground,
    }


def received_primal(api: ApiClient, **overrides) -> Dict[str, Any]:
    """Department, catalogue and one received primal purchase."""
    ctx = department_with_catalogue(api)
    ctx["purchase"] = create_primal_purchase(api, ctx["department"]["id"], **overrides)
    return ctx


def draft_cutting_test(api: ApiClient) -> Dict[str, Any]:
    """A DRAFT test whose three lines exactly account for the bench weight: a
    salable cut, a grind-trim line and a fat-and-bone loss line."""
    ctx = received_primal(api)
    purchase = ctx["purchase"]
    test = create_cutting_test(
        api, purchase["id"], purchase["net_weight_lb"], purchase["version"]
    )
    lines = [
        add_cutting_test_line(
            api,
            test["id"],
            1,
            "RIBEYE_STEAK",
            "SALABLE_CUT",
            62.0,
            1450,
            retail_item_id=ctx["whole_muscle_item"]["id"],
        ),
        add_cutting_test_line(
            api, test["id"], 2, "GRIND_TRIM_81", "GRIND_TRIM", 18.5, 420, lean_pct=78.0
        ),
        add_cutting_test_line(
            api, test["id"], 3, "FAT_AND_BONE", "FAT_BONE_LOSS", 18.0, 0
        ),
    ]
    ctx["cutting_test"] = test
    ctx["lines"] = lines
    return ctx


def submitted_cutting_test(api: ApiClient) -> Dict[str, Any]:
    ctx = draft_cutting_test(api)
    ctx["cutting_test"] = submit_cutting_test(api, ctx["cutting_test"]["id"])
    return ctx


def approved_cutting_test(api: ApiClient) -> Dict[str, Any]:
    """Submitted by one cutter and approved by a different operator, so the
    segregation-of-duties rung is satisfied."""
    ctx = submitted_cutting_test(api)
    ctx["cutting_test"] = approve_cutting_test(api, ctx["cutting_test"]["id"])
    ctx["lines"] = [read_cutting_test_line(api, line["id"]) for line in ctx["lines"]]
    ctx["purchase"] = read_primal_purchase(api, ctx["purchase"]["id"])
    return ctx


def proposed_item(api: ApiClient) -> Dict[str, Any]:
    """An approved cutting test plus a provisional price on the salable item."""
    ctx = approved_cutting_test(api)
    ctx["whole_muscle_item"] = propose_price(
        api, ctx["whole_muscle_item"]["id"], ctx["purchase"]["id"]
    )
    return ctx


def priced_item(api: ApiClient) -> Dict[str, Any]:
    """Provisional proposal followed by the final activation off the measured
    cut-test cost basis, leaving the item PRICED."""
    ctx = proposed_item(api)
    item = ctx["whole_muscle_item"]
    ctx["whole_muscle_item"] = activate_price_from_cutting_test(
        api, item["id"], item["version"], ctx["cutting_test"]["id"]
    )
    return ctx


def published_plan(
    api: ApiClient,
    facings: int = 4,
    expected_movement_lb: float = 30.0,
    service_date: Optional[str] = None,
) -> Dict[str, Any]:
    """A priced item merchandised on a single published case-plan line."""
    ctx = priced_item(api)
    plan = create_case_plan(
        api, ctx["department"]["id"], service_date or FIXTURE_CLOCK[:10]
    )
    line = add_case_plan_line(
        api, plan["id"], ctx["whole_muscle_item"]["id"], 1, facings, expected_movement_lb
    )
    ctx["plan"] = publish_case_plan(api, plan["id"])
    ctx["line"] = line
    return ctx


def filled_plan_line(
    api: ApiClient,
    filled_lb: Optional[float] = None,
    facings: int = 4,
    expected_movement_lb: float = 30.0,
) -> Dict[str, Any]:
    """A published plan whose only line has been filled to its required pounds,
    which dates the line on that first fill."""
    ctx = published_plan(api, facings=facings, expected_movement_lb=expected_movement_lb)
    pounds = filled_lb if filled_lb is not None else float(ctx["line"]["required_fill_lb"])
    ctx["line"] = fill_line(api, ctx["line"]["id"], pounds)
    ctx["plan"] = read_case_plan(api, ctx["plan"]["id"])
    return ctx


def trim_lots_for_blend(
    api: ApiClient,
    lot_a_lb: float = 10.0,
    lot_b_lb: float = 10.0,
) -> Dict[str, Any]:
    """Two trim lots of different country of origin, harvested from two
    approved cutting tests on two separately received primals, so a blend over
    both derives a MULTIPLE origin label."""
    ctx = approved_cutting_test(api)
    department_id = ctx["department"]["id"]

    lot_a = create_trim_lot_from_line(
        api, department_id, "TL-A78", lot_a_lb, ctx["lines"][1]["id"]
    )

    second_item = create_retail_item(
        api,
        department_id,
        item_code="STRIP01",
        subprimal_code="STRIP_STEAK",
        product_class="WHOLE_MUSCLE",
    )
    second_purchase = create_primal_purchase(
        api,
        department_id,
        primal_code="BEEF_STRIP_LOIN",
        country_of_origin="CAN",
        gross_weight_lb=40.0,
        invoice_cost_cents=36000,
        receiving_shrink_lb=0.0,
        freight_cost_cents=0,
        vendor_allowance_cents=0,
    )
    second_test = create_cutting_test(
        api,
        second_purchase["id"],
        second_purchase["net_weight_lb"],
        second_purchase["version"],
    )
    add_cutting_test_line(
        api,
        second_test["id"],
        1,
        "STRIP_STEAK",
        "SALABLE_CUT",
        25.0,
        1600,
        retail_item_id=second_item["id"],
    )
    second_trim_line = add_cutting_test_line(
        api, second_test["id"], 2, "GRIND_TRIM_90", "GRIND_TRIM", 15.0, 500, lean_pct=90.0
    )
    submit_cutting_test(api, second_test["id"])
    approve_cutting_test(api, second_test["id"])

    lot_b = create_trim_lot_from_line(
        api, department_id, "TL-B92", lot_b_lb, second_trim_line["id"]
    )

    ctx["second_item"] = second_item
    ctx["second_purchase"] = read_primal_purchase(api, second_purchase["id"])
    ctx["second_test"] = read_cutting_test(api, second_test["id"])
    ctx["lot_a"] = read_trim_lot(api, lot_a["id"])
    ctx["lot_b"] = read_trim_lot(api, lot_b["id"])
    return ctx


def scheduled_grind_run(
    api: ApiClient,
    declared_coo: str = "MULTIPLE",
    target_lean_pct: float = 85.0,
    scheduled_start_at: str = "2026-08-05T09:00:00Z",
    scheduled_end_at: str = "2026-08-05T10:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    """Two trim lots plus a run scheduled against the department's GROUND item,
    which must first be priced so the run may start."""
    ctx = trim_lots_for_blend(api)
    ground = ctx["ground_item"]
    ctx["ground_item"] = propose_price(api, ground["id"], ctx["purchase"]["id"])
    ctx["grind_run"] = create_grind_run(
        api,
        ctx["department"]["id"],
        ctx["ground_item"]["id"],
        scheduled_start_at,
        scheduled_end_at,
        declared_coo=declared_coo,
        target_lean_pct=target_lean_pct,
        **overrides,
    )
    return ctx


def grind_run_with_inputs(
    api: ApiClient,
    lot_a_pounds: float = 10.0,
    lot_b_pounds: float = 10.0,
    **overrides,
) -> Dict[str, Any]:
    ctx = scheduled_grind_run(api, **overrides)
    ctx["input_a"] = add_grind_input(
        api, ctx["grind_run"]["id"], ctx["lot_a"]["id"], 1, lot_a_pounds
    )
    ctx["input_b"] = add_grind_input(
        api, ctx["grind_run"]["id"], ctx["lot_b"]["id"], 2, lot_b_pounds
    )
    ctx["grind_run"] = read_grind_run(api, ctx["grind_run"]["id"])
    return ctx


def running_grind_run(api: ApiClient, **overrides) -> Dict[str, Any]:
    ctx = grind_run_with_inputs(api, **overrides)
    ctx["grind_run"] = start_grind_run(api, ctx["grind_run"]["id"])
    return ctx


def confirmed_pre_order(
    api: ApiClient,
    requested_weight_lb: float = 4.0,
    pickup_window_start_at: str = "2026-08-05T14:00:00Z",
    pickup_window_end_at: str = "2026-08-05T16:00:00Z",
) -> Dict[str, Any]:
    """A priced item, an order against it, and the confirmation that pins the
    quote and collects the deposit."""
    ctx = priced_item(api)
    order = create_pre_order(
        api,
        ctx["department"]["id"],
        ctx["whole_muscle_item"]["id"],
        requested_weight_lb,
        pickup_window_start_at,
        pickup_window_end_at,
    )
    ctx["pre_order"] = confirm_pre_order(api, order["id"])
    return ctx


def staged_pre_order(
    api: ApiClient,
    requested_weight_lb: float = 4.0,
    pickup_window_start_at: str = "2026-08-05T14:00:00Z",
    pickup_window_end_at: str = "2026-08-05T16:00:00Z",
) -> Dict[str, Any]:
    """A filled case line with a confirmed order staged against it."""
    ctx = filled_plan_line(api)
    order = create_pre_order(
        api,
        ctx["department"]["id"],
        ctx["whole_muscle_item"]["id"],
        requested_weight_lb,
        pickup_window_start_at,
        pickup_window_end_at,
    )
    confirm_pre_order(api, order["id"])
    ctx["pre_order"] = stage_pre_order(api, order["id"], ctx["line"]["id"])
    ctx["line"] = read_case_plan_line(api, ctx["line"]["id"])
    return ctx


def plan_ready_for_reconciliation(
    api: ApiClient,
    filled_lb: Optional[float] = None,
) -> Dict[str, Any]:
    """A published plan with one filled line inside the reconciliation period,
    which is the smallest state a reconciliation can measure."""
    ctx = filled_plan_line(api, filled_lb=filled_lb)
    return ctx


def collect(rows: List[Dict[str, Any]], key: str) -> List[Any]:
    """Pull one field out of a list of rows, in the order the rows came back."""
    return [row[key] for row in rows]
