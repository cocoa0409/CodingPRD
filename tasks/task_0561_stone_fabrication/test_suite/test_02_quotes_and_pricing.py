"""Quote pricing (tiered rates + minimum-job floor), quote listing, and the deposit-vs-balance
dual-variant divergence on the project cost domain."""
import pytest

from test_helpers import (
    validate_success, validate_paginated,
    create_project_payload, create_quote_payload,
    setup_priced_project, new_project,
)


# --------------------------------------------------------------------------
# Corner/calculations — quote above the floor
# --------------------------------------------------------------------------
def test_quote_premium_above_floor_correct_result(api, salesrep_headers):
    """PRD §3.1: "The `subtotal_cents` is the sum of the material, edge, and cutout charges."
    PRD §3.1: "The `quote_total_cents` is then the greater of `subtotal_cents` and a job floor
    of 80,000 cents, so that no quote is ever priced below the minimum job value."

    PREMIUM/OGEE/40sqft/25lf/2 sinks: 6500*40 + 2000*25 + 2*15000 = 340000, above the floor.

    Design: Corner/calculations/quote_standard_no_floor_correct_result
    """
    p = new_project(material_grade="PREMIUM")
    resp = api.create_quote(
        p["id"],
        create_quote_payload(
            expected_project_version=p["version"], est_sqft=40, material_grade="PREMIUM",
            edge_profile="OGEE", edge_linear_ft=25, sink_count=2, faucet_count=0, cooktop_count=0),
        salesrep_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["subtotal_cents"] == 340000
    assert data["quote_total_cents"] == 340000


# --------------------------------------------------------------------------
# Difficulty/combinatorial_formula — tiered pricing lifted by the min-job floor
# --------------------------------------------------------------------------
def test_quote_below_floor_subtotal_computed(api, salesrep_headers):
    """PRD §3.1: "The material charge is the per-square-foot material rate for the quote's grade
    multiplied by `est_sqft`, rounded half up — the rate is 4,500 cents for `STANDARD`, 6,500
    for `PREMIUM`, and 9,500 for `EXOTIC`."
    PRD §3.1: "The edge charge is the per-linear-foot edge rate for the chosen profile multiplied
    by `edge_linear_ft`, rounded half up — the rate is 0 cents for `EASED`, 800 for `BEVELED`,
    1,200 for `BULLNOSE`, and 2,000 for `OGEE`."
    PRD §3.1: "The `subtotal_cents` is the sum of the material, edge, and cutout charges."

    STANDARD/BEVELED/5sqft/4lf/0 cutouts: 4500*5 + 800*4 + 0 = 25700.

    Design: Difficulty/combinatorial_formula/quote_pricing_tiered_with_min_job_floor
    """
    p = new_project(material_grade="STANDARD")
    resp = api.create_quote(
        p["id"],
        create_quote_payload(
            expected_project_version=p["version"], est_sqft=5, material_grade="STANDARD",
            edge_profile="BEVELED", edge_linear_ft=4, sink_count=0, faucet_count=0, cooktop_count=0),
        salesrep_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["subtotal_cents"] == 25700


def test_quote_below_floor_lifted_to_min_job(api, salesrep_headers):
    """PRD §3.1: "The `quote_total_cents` is then the greater of `subtotal_cents` and a job floor
    of 80,000 cents, so that no quote is ever priced below the minimum job value."

    Subtotal 25700 is below 80000, so quote_total is lifted to the 80000 floor.

    Design: Difficulty/combinatorial_formula/quote_pricing_tiered_with_min_job_floor
    """
    p = new_project(material_grade="STANDARD")
    resp = api.create_quote(
        p["id"],
        create_quote_payload(
            expected_project_version=p["version"], est_sqft=5, material_grade="STANDARD",
            edge_profile="BEVELED", edge_linear_ft=4, sink_count=0, faucet_count=0, cooktop_count=0),
        salesrep_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["subtotal_cents"] == 25700
    assert data["quote_total_cents"] == 80000


# --------------------------------------------------------------------------
# Corner/endpoints — quote listing envelope
# --------------------------------------------------------------------------
def test_quotes_reverse_list_and_pagination_envelope(api, salesrep_headers):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and `has_more`
    in the `meta` object of the envelope."
    PRD §3.1: "the prior active quote moves to `SUPERSEDED` and the newest quote becomes the
    single `ACTIVE`, authoritative one."

    Design: Corner/endpoints/quotes_reverse_list_and_pagination_envelope
    """
    ctx = setup_priced_project(with_deposit=False, sink_cutouts=0)
    resp = api.list_quotes(ctx["p_id"], salesrep_headers)
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert "total_count" in meta and "has_more" in meta
    active = [q for q in data if q["status"] == "ACTIVE"]
    assert len(active) == 1, f"expected exactly one ACTIVE quote, got {len(active)}"


# --------------------------------------------------------------------------
# Difficulty/dual_variant_calc — deposit_estimate vs final_balance on the project
# --------------------------------------------------------------------------
def test_quoted_total_and_balance_uses_final_invoice_basis(api, salesrep_headers):
    """PRD §3.1: "Whenever a quote is created, the project's `quoted_total_cents` becomes the
    `quote_total_cents` of its `ACTIVE` quote (0 if there is none) and its `balance_due_cents`
    is recomputed."
    PRD §3.2: "The `balance_due_cents` is the balance basis (the `final_invoice_cents` if present,
    else the `quoted_total_cents`) minus `amount_paid_cents`."

    With an approved template priced at 369751 and no payments, balance_due tracks the
    final_invoice basis (369751), not the quoted total (340000).

    Design: Difficulty/dual_variant_calc/deposit_estimate_vs_final_balance_on_project
    """
    ctx = setup_priced_project(with_deposit=False, sink_cutouts=2)
    proj = validate_success(api.get_project(ctx["p_id"], salesrep_headers))
    assert proj["quoted_total_cents"] == 340000
    assert proj["balance_due_cents"] == 369751


def test_final_balance_variant_diverges_from_deposit_estimate(api, salesrep_headers):
    """PRD §3.3: "For each line in that order, multiply the base by one plus the tax rate of
    0.0875 and round half up to whole cents; the `final_invoice_cents` is the sum of those
    per-line taxed amounts."
    PRD §3.2: "the deposit required is the project's `quoted_total_cents` multiplied by 50
    percent, rounded half up."

    The final_balance variant (final_invoice 369751) diverges from the deposit_estimate
    variant (0.50 * 340000 = 170000) for the identical project.

    Design: Difficulty/dual_variant_calc/deposit_estimate_vs_final_balance_on_project
    """
    ctx = setup_priced_project(with_deposit=False, sink_cutouts=2)
    proj = validate_success(api.get_project(ctx["p_id"], salesrep_headers))
    assert proj["final_invoice_cents"] == 369751
    deposit_estimate = 170000  # round_half_up(340000 * 0.50)
    assert proj["final_invoice_cents"] != deposit_estimate
