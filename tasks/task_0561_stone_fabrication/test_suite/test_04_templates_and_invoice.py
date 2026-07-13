"""Cutout charge snapshots, per-line final-invoice rounding, change-order re-pricing, and the
template reopen-then-reapprove revision loop."""
import pytest

from test_helpers import (
    validate_success,
    create_cutout_payload,
    setup_priced_project, setup_scheduled_fab, setup_project_with_quote,
    add_template, add_change_order, approve_change_order, approve_template,
)


# --------------------------------------------------------------------------
# Corner/entities — cutout charge snapshot
# --------------------------------------------------------------------------
def test_cutout_charge_cents_computed_snapshot(api, fabricator_headers, salesrep_headers):
    """PRD §3.3: "Each cutout names its `template_id` and a `cutout_type` of `SINK`, `FAUCET`,
    or `COOKTOP`, and snapshots a `charge_cents` at creation equal to the per-cutout charge for
    that type (15,000 cents for `SINK`, 3,500 for `FAUCET`, 12,000 for `COOKTOP`)."

    Design: Corner/entities/cutout_charge_cents_computed_snapshot
    """
    from test_helpers import new_project
    p = new_project(material_grade="PREMIUM")
    t = add_template(p["id"])
    resp = api.create_cutout(t["id"], create_cutout_payload(cutout_type="SINK"), fabricator_headers)
    data = validate_success(resp, expected_status=201)
    assert data["charge_cents"] == 15000


# --------------------------------------------------------------------------
# Difficulty/combinatorial_formula — final invoice rounds tax per line
# --------------------------------------------------------------------------
def test_final_invoice_per_line_rounding_result(api, salesrep_headers):
    """PRD §3.3: "For each line in that order, multiply the base by one plus the tax rate of
    0.0875 and round half up to whole cents; the `final_invoice_cents` is the sum of those
    per-line taxed amounts."

    material 282750 + edge 54375 + two SINK lines of 16313 each = 369751.

    Design: Difficulty/combinatorial_formula/final_invoice_per_line_rounding_order
    """
    ctx = setup_priced_project(with_deposit=False, sink_cutouts=2)
    proj = validate_success(api.get_project(ctx["p_id"], salesrep_headers))
    assert proj["final_invoice_cents"] == 369751


def test_final_invoice_per_line_not_sum_then_round(api, salesrep_headers):
    """PRD §3.3: "The rounding is applied to each line before summation, and the line order is
    fixed as material, edge, cutouts by creation time, then change orders by creation time."

    Per-line rounding yields 369751; the sum-then-round alternative (369750) is rejected.

    Design: Difficulty/combinatorial_formula/final_invoice_per_line_rounding_order
    """
    ctx = setup_priced_project(with_deposit=False, sink_cutouts=2)
    proj = validate_success(api.get_project(ctx["p_id"], salesrep_headers))
    assert proj["final_invoice_cents"] == 369751
    assert proj["final_invoice_cents"] != 369750


# --------------------------------------------------------------------------
# Corner/calculations — change-order re-pricing and reopens_template default
# --------------------------------------------------------------------------
def test_final_invoice_recomputed_with_applied_change_order(api, salesrep_headers):
    """PRD §3.7: "On approval the order moves to `APPLIED`, the project's `final_invoice_cents`
    is recomputed to include the new delta line (taxed per line as in §3.3) and
    `balance_due_cents` is refreshed."

    A non-reopening delta of 50000 adds a taxed line round_half_up(50000*1.0875)=54375,
    moving final_invoice 369751 -> 424126; the template stays APPROVED.

    Design: Corner/calculations/final_invoice_recomputed_with_applied_change_order
    """
    from test_helpers import TEST_USERS
    ctx = setup_priced_project(with_deposit=False, sink_cutouts=2)
    co = add_change_order(ctx["p_id"], delta_cents=50000, reopens_template=False, description="extra faucet")
    applied = validate_success(api.approve_change_order(co["id"], TEST_USERS["shopmanager_headers"]))
    assert applied["status"] == "APPLIED"
    proj = validate_success(api.get_project(ctx["p_id"], salesrep_headers))
    assert proj["final_invoice_cents"] == 424126
    template = validate_success(api.get_template(ctx["t_id"], salesrep_headers))
    assert template["status"] == "APPROVED"


def test_change_order_reopens_template_defaults_true(api, salesrep_headers):
    """PRD §3.7: "a signed `delta_cents` to be added to the final invoice when the order is
    applied, and an optional `reopens_template` flag that defaults to true."

    Design: Corner/calculations/change_order_reopens_template_default_true
    """
    ctx = setup_project_with_quote()
    from test_helpers import current_version, create_change_order_payload
    version = current_version(ctx["p_id"])
    payload = create_change_order_payload(expected_project_version=version, description="tbd", delta_cents=1000)
    # reopens_template intentionally omitted from the payload
    resp = api.create_change_order(ctx["p_id"], payload, salesrep_headers)
    data = validate_success(resp, expected_status=201)
    assert data["reopens_template"] is True


# --------------------------------------------------------------------------
# Difficulty/non_linear_state_machine — template reopen then reapprove cycle
# --------------------------------------------------------------------------
def test_template_reapproved_after_reopen_cycle(api, salesrep_headers):
    """PRD §3.7: "A reopened template can be re-approved, re-pricing the invoice, and a fresh
    fabrication order can then carry the project from `ON_HOLD` back into `IN_PRODUCTION`."
    PRD §3.3: "On approval the template becomes `APPROVED` and the project's
    `final_invoice_cents` is priced, after which `balance_due_cents` is recomputed."

    The template cycles APPROVED -> MEASURED (via a reopening change order) -> APPROVED again.

    Design: Difficulty/non_linear_state_machine/template_reopen_then_reapprove_cycle
    """
    from test_helpers import TEST_USERS
    ctx = setup_scheduled_fab(sink_cutouts=0)
    co = add_change_order(ctx["p_id"], delta_cents=0, reopens_template=True, description="swap edge")
    approve_change_order(co["id"])
    reapproved = validate_success(api.approve_template(ctx["t_id"], TEST_USERS["fabricator_headers"]))
    assert reapproved["status"] == "APPROVED"


def test_reopen_cascade_cancels_fab_and_holds_project(api, salesrep_headers):
    """PRD §3.7: "When the applied order's `reopens_template` is true, the full reopen cascade
    fires: the project's `APPROVED` template returns to `MEASURED`, the project's linked
    fabrication order is cancelled if it is still in `SCHEDULED`, `CUTTING`, `RECUTTING`, or
    `QC_PASSED` (which releases its reserved slab back to `IN_STOCK` per §3.5), and the
    project's `status` becomes `ON_HOLD`."

    Design: Difficulty/non_linear_state_machine/template_reopen_then_reapprove_cycle
    """
    ctx = setup_scheduled_fab(sink_cutouts=0)
    co = add_change_order(ctx["p_id"], delta_cents=0, reopens_template=True, description="swap edge")
    approve_change_order(co["id"])
    fab = validate_success(api.get_fabrication_order(ctx["f_id"], salesrep_headers))
    assert fab["status"] == "CANCELLED"
    proj = validate_success(api.get_project(ctx["p_id"], salesrep_headers))
    assert proj["status"] == "ON_HOLD"
