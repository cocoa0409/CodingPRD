"""Completion: estimate-vs-final cost divergence, health score, warranty split, diagnostic waiver."""
from test_helpers import (
    validate_success,
    assert_service_request, assert_appliance,
    setup_diagnosed_request, setup_completed_request,
    get_service_request, get_appliance, get_warranty_contract, TEST_USERS,
)

ADMIN = TEST_USERS["service_admin_headers"]

_MANUFACTURER = {"coverage_type": "MANUFACTURER", "coverage_start": "2025-01-01",
                 "coverage_end": "2027-01-01", "deductible_cents": 0, "coverage_cap_cents": 100000}


# ─── Difficulty: repair_cost_estimate_vs_final_on_service_request ──────────
def test_estimate_subtotal_uses_estimated_labor(api):
    """PRD §3.3: "The `estimated_repair_subtotal_cents` is `estimated_parts_total_cents` plus
    `estimated_labor_total_cents`."

    Design: Difficulty/dual_variant_calc/repair_cost_estimate_vs_final_on_service_request
    """
    # parts 9000 + labor(40,20 -> 15000) = 24000.
    ctx = setup_diagnosed_request(model="M100", part_price_cents=4500,
                                  labor_tasks=[{"minutes": 40}, {"minutes": 20}])
    est = validate_success(api.get_estimate(ctx["est_id"], ADMIN), 200)
    assert est["estimated_repair_subtotal_cents"] == 24000


def test_final_subtotal_uses_actual_labor(api):
    """PRD §3.6: "The final labor total, `final_labor_total_cents`, is computed from
    `actual_labor_tasks` by the same per-task-rounded labor rule (each task's minutes divided
    by 15, rounded up, times 3000 cents, then summed), and `final_parts_total_cents` is the
    actual consumed-parts total from the reserved lines. Their sum is stored as
    `final_repair_subtotal_cents`."

    Design: Difficulty/dual_variant_calc/repair_cost_estimate_vs_final_on_service_request
    """
    # actual labor (55,25) -> ceil(55/15)*3000 + ceil(25/15)*3000 = 12000 + 6000 = 18000;
    # parts 9000; final subtotal 27000 (diverges from the 24000 estimate).
    ctx = setup_completed_request(model="M101", part_price_cents=4500,
                                  labor_tasks=[{"minutes": 40}, {"minutes": 20}],
                                  actual_labor_tasks=[{"minutes": 55}, {"minutes": 25}])
    sr = get_service_request(ctx)
    assert_service_request(sr)
    assert sr["final_labor_total_cents"] == 18000
    assert sr["final_repair_subtotal_cents"] == 27000


# ─── Difficulty: appliance_health_score_at_diagnosis_vs_post_completion ────
def test_health_score_at_diagnosis_excludes_current_request(api):
    """PRD §3.3: "For `health_score_at_diagnosis`, the count of prior repairs is the number of
    this appliance's `COMPLETED` service requests and excludes the current in-flight request
    (which has not yet completed)."
    PRD §3.3: "The raw score is 100, minus the age in years multiplied by 5, minus the number
    of prior repairs multiplied by 8, minus a further 20 if the appliance's `recall_status` is
    `RECALLED`".

    Design: Difficulty/dual_variant_calc/appliance_health_score_at_diagnosis_vs_post_completion
    """
    # age 6 (2020-01-15 -> 2026-06-10), 0 prior repairs, CLEAR: 100 - 6*5 = 70.
    ctx = setup_diagnosed_request(model="M200", purchase_date="2020-01-15",
                                  window_start="2026-06-10T09:00:00Z",
                                  window_end="2026-06-10T10:00:00Z")
    sr = get_service_request(ctx)
    assert sr["health_score_at_diagnosis"] == 70


def test_post_completion_health_score_includes_finished_repair(api):
    """PRD §3.3: "The appliance's own `health_score` field is the post-completion form of the
    same computation and is recomputed when a repair completes, at which point the
    just-completed request is included in the prior-repair count — one more prior repair,
    lowering the score by a further 8 points relative to the at-diagnosis capture."
    PRD §3.6: "the appliance's `completed_repair_count` is incremented by 1, which in turn
    recomputes the appliance's `health_score` in its post-completion form (now counting the
    just-finished repair among the prior repairs)."

    Design: Difficulty/dual_variant_calc/appliance_health_score_at_diagnosis_vs_post_completion
    """
    # after completion: age 6, prior_repairs 1: 100 - 6*5 - 1*8 = 62.
    ctx = setup_completed_request(model="M201", purchase_date="2020-01-15",
                                  window_start="2026-06-10T09:00:00Z",
                                  window_end="2026-06-10T10:00:00Z",
                                  actual_labor_tasks=[{"minutes": 40}, {"minutes": 20}])
    app = get_appliance(ctx)
    assert_appliance(app)
    assert app["completed_repair_count"] == 1
    assert app["health_score"] == 62


# ─── Corner: none_routing_diagnostic_waived_on_completion ──────────────────
def test_none_routing_completed_repair_waives_diagnostic_fee(api):
    """PRD §3.3: "otherwise, if the request has reached `COMPLETED` and the repair subtotal is
    at least 15000 cents ($150.00), the fee is waived to 0 ... The threshold is inclusive — a
    subtotal of exactly 15000 cents waives the fee."
    PRD §3.6: "The request's `customer_responsibility_cents` is recomputed from the final
    subtotal, and its `amount_due_cents` is set to that final customer responsibility."

    Design: Corner/calculations/none_routing_diagnostic_waived_on_completion
    """
    # NONE routing, subtotal 24000 (>= 15000): fee waived, amount_due == 24000 (not 32900).
    ctx = setup_completed_request(model="N70", part_price_cents=4500,
                                  labor_tasks=[{"minutes": 40}, {"minutes": 20}],
                                  actual_labor_tasks=[{"minutes": 40}, {"minutes": 20}])
    sr = get_service_request(ctx)
    assert sr["warranty_routing"] == "NONE"
    assert sr["amount_due_cents"] == 24000


# ─── Corner: manufacturer_routing_full_cover_zero_responsibility ───────────
def test_manufacturer_routing_fully_covers_within_cap(api):
    """PRD §3.4: "Otherwise, if routing is `MANUFACTURER`, the warranty-covered amount is the
    smaller of the repair subtotal and the remaining cap, and the customer responsibility is the
    repair subtotal minus that covered amount — that is, only the overflow above the cap, with
    no deductible (manufacturer deductibles are always 0)."
    PRD §2.9: "When an estimate is approved, the provisional warranty-covered amount is added to
    the covering contract's `claimed_cents`".

    Design: Corner/calculations/manufacturer_routing_full_cover_zero_responsibility
    """
    # subtotal 24000 within cap 100000: covered 24000, responsibility 0, claimed 24000.
    ctx = setup_completed_request(model="N80", warranty=_MANUFACTURER, purchase_date="2024-01-15",
                                  part_price_cents=4500,
                                  labor_tasks=[{"minutes": 40}, {"minutes": 20}],
                                  actual_labor_tasks=[{"minutes": 40}, {"minutes": 20}])
    sr = get_service_request(ctx)
    assert sr["warranty_covered_cents"] == 24000
    assert sr["customer_responsibility_cents"] == 0
    wc = get_warranty_contract(ctx)
    assert wc["claimed_cents"] == 24000
