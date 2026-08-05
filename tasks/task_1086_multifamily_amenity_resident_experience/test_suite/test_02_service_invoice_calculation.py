"""Service invoice: dual-variant (estimate vs actual) and the per-line
rounding rule.

Queue A (Difficulty): dual_variant_calc/service_estimate_vs_actual_diverges,
combinatorial_formula/service_invoice_per_line_rounding_mode_b.
"""
from test_helpers import (
    fixtures as fx,
    make_vendor_headers,
    validate_success,
)


def test_estimate_computed_at_assignment(api):
    """PRD §3.5: "The estimate, produced at assignment, is the vendor's
    `hourly_rate_cents` multiplied by `estimated_hours` and rounded half up,
    plus the `estimated_parts_cents` as an untaxed lump; it is stored as
    `estimated_cost_cents`."

    8000/h x 2h = 16000 plus a 2014 untaxed parts lump = 18014.

    Design: Difficulty/dual_variant_calc/service_estimate_vs_actual_diverges
    """
    ctx = fx.setup_assigned_request(
        api, trade="PLUMBING", estimated_hours=2, estimated_parts_cents=2014,
        vendor_overrides={"name": "PlumbCo", "trades": ["PLUMBING"], "hourly_rate_cents": 8000},
    )
    assert ctx["sr"]["status"] == "ASSIGNED"
    assert ctx["sr"]["estimated_cost_cents"] == 18014


def test_actual_invoice_diverges_from_estimate(api):
    """PRD §3.5: "then, for each part, a taxed line equal to that part's `cents`
    multiplied by one plus a material tax of seven percent, rounded half up.
    Each line is rounded before the lines are summed — never summed then
    rounded."

    Actual: labor 12000 + round(1007*1.07)=1077 twice => 14154, distinct from
    the 18014 estimate.

    Design: Difficulty/dual_variant_calc/service_estimate_vs_actual_diverges
    """
    ctx = fx.setup_started_request(
        api, trade="PLUMBING", estimated_hours=2, estimated_parts_cents=2014,
        vendor_overrides={"name": "PlumbCo", "trades": ["PLUMBING"], "hourly_rate_cents": 8000},
    )
    completed = validate_success(api.complete_service_request(
        ctx["sr"]["id"],
        {"labor_hours": 1.5, "parts": [{"name": "A", "cents": 1007}, {"name": "B", "cents": 1007}]},
        make_vendor_headers(ctx["vendor"]["id"]),
    ))
    assert completed["status"] == "COMPLETED"
    assert completed["final_invoice_cents"] == 14154


def test_per_line_rounding_before_summation(api):
    """PRD §3.5: "Each line is rounded before the lines are summed — never
    summed then rounded."

    round(1007*1.07)=1077 per line, twice, plus 12000 labor => 14154 (summing
    the raw taxed parts then rounding would give 14155).

    Design: Difficulty/combinatorial_formula/service_invoice_per_line_rounding_mode_b
    """
    ctx = fx.setup_started_request(
        api, trade="PLUMBING", estimated_hours=2,
        vendor_overrides={"name": "PlumbCo", "trades": ["PLUMBING"], "hourly_rate_cents": 8000},
    )
    completed = validate_success(api.complete_service_request(
        ctx["sr"]["id"],
        {"labor_hours": 1.5, "parts": [{"name": "A", "cents": 1007}, {"name": "B", "cents": 1007}]},
        make_vendor_headers(ctx["vendor"]["id"]),
    ))
    assert completed["final_invoice_cents"] == 14154


def test_per_line_rounding_persists_on_completed_request(api):
    """PRD §3.5: "The final invoice, stored as `final_invoice_cents`, is the
    subtotal plus that trip fee."

    The rounded-per-line invoice 14154 is the stored final_invoice_cents on the
    COMPLETED request (a ROUTINE request adds no trip fee).

    Design: Difficulty/combinatorial_formula/service_invoice_per_line_rounding_mode_b
    """
    ctx = fx.setup_started_request(
        api, trade="PLUMBING", estimated_hours=2,
        vendor_overrides={"name": "PlumbCo", "trades": ["PLUMBING"], "hourly_rate_cents": 8000},
    )
    validate_success(api.complete_service_request(
        ctx["sr"]["id"],
        {"labor_hours": 1.5, "parts": [{"name": "A", "cents": 1007}, {"name": "B", "cents": 1007}]},
        make_vendor_headers(ctx["vendor"]["id"]),
    ))
    fetched = validate_success(api.get_service_request(ctx["sr"]["id"], fx.PM))
    assert fetched["status"] == "COMPLETED"
    assert fetched["final_invoice_cents"] == 14154
