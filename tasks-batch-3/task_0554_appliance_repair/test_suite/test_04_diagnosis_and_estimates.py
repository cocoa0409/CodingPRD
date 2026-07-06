"""Diagnosis: warranty routing, labor/warranty pricing, estimate lifecycle."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_estimate,
    create_diagnose_payload, create_revision_payload,
    provision_base, setup_diagnosed_request, setup_declined_none_request,
    get_service_request,
    make_technician_headers, make_customer_headers, TEST_USERS,
)

ADMIN = TEST_USERS["service_admin_headers"]

_EXTENDED_5000 = {
    "coverage_type": "EXTENDED", "coverage_start": "2025-01-01", "coverage_end": "2027-01-01",
    "deductible_cents": 5000, "coverage_cap_cents": 100000,
}


# ─── Difficulty: warranty_customer_responsibility_extended_mode_a ───────────
def test_extended_customer_responsibility_is_deductible_plus_overflow(api):
    """PRD §3.4: "Otherwise, when routing is `EXTENDED` or `HOME_WARRANTY`, the warranty-covered
    amount is again the smaller of the repair subtotal and the remaining cap, and the customer
    responsibility is the contract's `deductible_cents` plus the repair subtotal minus that
    covered amount."
    PRD §3.3: "The `estimated_repair_subtotal_cents` is `estimated_parts_total_cents` plus
    `estimated_labor_total_cents`."

    Design: Difficulty/combinatorial_formula/warranty_customer_responsibility_extended_mode_a
    """
    # parts 4500*2=9000, labor ceil(40/15)*3000 + ceil(20/15)*3000 = 9000+6000 = 15000, subtotal 24000.
    # covered = min(24000, 100000) = 24000; responsibility = 5000 + (24000 - 24000) = 5000.
    ctx = setup_diagnosed_request(warranty=_EXTENDED_5000, purchase_date="2024-01-15",
                                  part_price_cents=4500,
                                  labor_tasks=[{"minutes": 40}, {"minutes": 20}],
                                  required_parts=None)  # defaults to part x2
    est = validate_success(api.get_estimate(ctx["est_id"], ADMIN), 200)
    assert_estimate(est)
    assert est["estimated_repair_subtotal_cents"] == 24000
    assert est["estimated_customer_responsibility_cents"] == 5000


def test_extended_routing_selected_at_diagnosis(api):
    """PRD §3.3: "The best candidate wins: `warranty_routing` becomes its `coverage_type` and
    `covering_contract_id` becomes its `id`."

    Design: Difficulty/combinatorial_formula/warranty_customer_responsibility_extended_mode_a
    """
    ctx = setup_diagnosed_request(warranty=_EXTENDED_5000, purchase_date="2024-01-15",
                                  part_price_cents=4500,
                                  labor_tasks=[{"minutes": 40}, {"minutes": 20}])
    sr = get_service_request(ctx)
    assert sr["warranty_routing"] == "EXTENDED"


# ─── Difficulty: labor_cost_round_up_per_task_mode_b ───────────────────────
def test_labor_total_rounds_up_each_task_before_summing(api):
    """PRD §3.3: "for each task independently, take its `minutes`, divide by 15 and round up to
    the next whole quarter-hour, and multiply that number of quarter-hours by 3000 cents (a
    $30.00 charge per started quarter-hour); the estimate's labor total is the sum of those
    per-task charges. The rounding order is fixed — each task is rounded up on its own and only
    then are the tasks summed; summing the raw minutes first and rounding once would generally
    understate the labor and is not permitted."

    Design: Difficulty/combinatorial_formula/labor_cost_round_up_per_task_mode_b
    """
    # ceil(40/15)*3000 + ceil(20/15)*3000 = 9000 + 6000 = 15000 (NOT ceil(60/15)*3000 = 12000).
    # The part is priced at 0, so parts total is 0 and only labor drives the estimate.
    ctx = setup_diagnosed_request(part_price_cents=0,
                                  labor_tasks=[{"minutes": 40}, {"minutes": 20}])
    est = validate_success(api.get_estimate(ctx["est_id"], ADMIN), 200)
    assert est["estimated_labor_total_cents"] == 15000


def test_zero_priced_parts_isolate_labor_total(api):
    """PRD §3.3: "Its `estimated_parts_total_cents` is the sum, over each line in
    `required_parts`, of the referenced `Part`'s `unit_price_cents` multiplied by that line's
    `quantity`."

    Design: Difficulty/combinatorial_formula/labor_cost_round_up_per_task_mode_b
    """
    ctx = setup_diagnosed_request(part_price_cents=0,
                                  labor_tasks=[{"minutes": 40}, {"minutes": 20}])
    est = validate_success(api.get_estimate(ctx["est_id"], ADMIN), 200)
    assert est["estimated_parts_total_cents"] == 0


# ─── Difficulty: warranty_coverage_end_inclusive_boundary ──────────────────
def test_service_date_equal_to_coverage_end_still_covered(api):
    """PRD §3.1: "Coverage is considered active on a given service date when `coverage_start`
    is on or before that date and that date is on or before `coverage_end` — both ends
    inclusive."

    Design: Difficulty/boundary_precision_check/warranty_coverage_end_inclusive_boundary
    """
    warranty = {"coverage_type": "EXTENDED", "coverage_start": "2025-01-01",
                "coverage_end": "2026-06-10", "deductible_cents": 5000, "coverage_cap_cents": 100000}
    # service_date is the diagnosis appointment window_start date == coverage_end (2026-06-10).
    ctx = setup_diagnosed_request(warranty=warranty, model="MC10",
                                  window_start="2026-06-10T09:00:00Z",
                                  window_end="2026-06-10T10:00:00Z")
    sr = get_service_request(ctx)
    assert sr["warranty_routing"] == "EXTENDED"


def test_service_date_equal_to_coverage_end_pins_contract(api):
    """PRD §3.1: "Coverage is considered active on a given service date when `coverage_start`
    is on or before that date and that date is on or before `coverage_end` — both ends
    inclusive."
    PRD §3.3: "The best candidate wins: `warranty_routing` becomes its `coverage_type` and
    `covering_contract_id` becomes its `id`."

    Design: Difficulty/boundary_precision_check/warranty_coverage_end_inclusive_boundary
    """
    warranty = {"coverage_type": "EXTENDED", "coverage_start": "2025-01-01",
                "coverage_end": "2026-06-10", "deductible_cents": 5000, "coverage_cap_cents": 100000}
    ctx = setup_diagnosed_request(warranty=warranty, model="MC11",
                                  window_start="2026-06-10T09:00:00Z",
                                  window_end="2026-06-10T10:00:00Z")
    sr = get_service_request(ctx)
    assert sr["covering_contract_id"] == ctx["wc_id"]


# ─── Corner: diagnose_from_intake_returns_invalid_state ────────────────────
def test_diagnose_before_scheduling_rejected(api):
    """PRD §3.3: "Once a technician is on site, the assigned technician records the diagnosis,
    advancing the request `SCHEDULED → DIAGNOSED`."
    PRD §2.1: "(4) the target resource being in a state that permits the transition
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/diagnose_from_intake_returns_invalid_state
    """
    ctx = provision_base(model="N40")  # request is INTAKE, never scheduled
    res = api.diagnose(ctx["sr_id"], create_diagnose_payload([{"minutes": 40}], []),
                       make_technician_headers(ctx["tech_id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


# ─── Corner: decision_on_declined_estimate_returns_estimate_not_pending ────
def test_second_decision_on_declined_estimate_rejected(api):
    """PRD §3.4: "only the customer who owns the request may do so (`ERR_NOT_OWNER`), and the
    estimate must be `PENDING_APPROVAL` or the decision is rejected with
    `ERR_ESTIMATE_NOT_PENDING`."

    Design: Corner/state_machines/decision_on_declined_estimate_returns_estimate_not_pending
    """
    ctx = setup_declined_none_request(model="N50")
    res = api.decide_estimate(ctx["est_id"], {"decision": "APPROVE"},
                              make_customer_headers(ctx["cust_id"]))
    validate_error(res, ApiErrorId.ERR_ESTIMATE_NOT_PENDING)


# ─── Corner: revision_supersedes_prior_estimate ────────────────────────────
def test_revision_supersedes_prior_and_keeps_request_diagnosed(api):
    """PRD §3.4: "When accepted, the prior estimate transitions `PENDING_APPROVAL → SUPERSEDED`,
    a new `Estimate` is created in `PENDING_APPROVAL` with its `estimated_*` amounts recomputed,
    and the request's `version` is incremented by 1."

    Design: Corner/state_machines/revision_supersedes_prior_estimate
    """
    ctx = setup_diagnosed_request(model="N60")
    est1_id = ctx["est_id"]
    sr = get_service_request(ctx)
    revision = create_revision_payload([{"minutes": 60}], [{"part_id": ctx["part_id"], "quantity": 1}],
                                       sr["version"])
    est2 = validate_success(api.revise_estimate(ctx["sr_id"], revision,
                                                make_technician_headers(ctx["tech_id"])), 201)
    est1 = validate_success(api.get_estimate(est1_id, ADMIN), 200)
    assert est1["status"] == "SUPERSEDED"
    assert est2["status"] == "PENDING_APPROVAL"
    sr_after = get_service_request(ctx)
    assert sr_after["status"] == "DIAGNOSED"
