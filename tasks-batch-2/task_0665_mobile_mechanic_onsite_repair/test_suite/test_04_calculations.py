"""Pricing calculations: tiered parts markup, fleet labor discount, estimate vs final.

Translates difficulty rules combinatorial_formula (markup per-unit rounding and final
sum-hours-then-round) and dual_variant_calc (estimate vs final divergence), plus the
corner calculations / endpoints instances on markup and discount.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    make_customer_headers, make_mechanic_headers,
    create_catalog_part, setup_in_progress_request, source_part_line,
    add_finding, resolve_addons, finish_visit, setup_quoted_request,
    setup_dispatched_request, get_request_payment,
)
from test_helpers.test_users import TEST_USERS

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ── Difficulty: markup rounded per unit then multiplied (mode b) ──

def test_part_markup_round_per_unit_then_multiply(api):
    """PRD §3.9: "The markup is computed per single unit and then multiplied by the
    quantity; the per-unit markup is rounded before the multiplication, never after."
    PRD §3.9: "The unit price for the line is the wholesale unit cost plus that per-unit
    markup, stored as `unit_price_cents`, and the line total is the unit price
    multiplied by the quantity, stored as `line_total_cents`."

    Design: Difficulty/combinatorial_formula/part_markup_round_per_unit_then_multiply_mode_b
    """
    part = create_catalog_part(wholesale_cost_cents=10, sku="CP3", name="Clip")
    ctx = setup_in_progress_request(mechanic_rate=9000, email="m3@x.com")
    pl = source_part_line(ctx["service_request"]["id"], ctx["mechanic"]["id"],
                          part["id"], quantity=5)
    assert pl["unit_price_cents"] == 15
    assert pl["line_total_cents"] == 75


def test_part_markup_per_unit_single_quantity(api):
    """PRD §3.9: "The per-unit markup in cents is the first-band amount times 0.45, plus
    the second-band amount times 0.30, plus the third-band amount times 0.18, with that
    marginal sum rounded half-up to a whole number of cents. The unit price for the line
    is the wholesale unit cost plus that per-unit markup, stored as `unit_price_cents`".

    Design: Difficulty/combinatorial_formula/part_markup_round_per_unit_then_multiply_mode_b
    """
    # wc=10: per-unit markup round(10*0.45=4.5)=5 -> unit_price 15; qty 1 -> line_total 15.
    part = create_catalog_part(wholesale_cost_cents=10, sku="CP3b", name="Clip")
    ctx = setup_in_progress_request(mechanic_rate=9000, email="m3b@x.com")
    pl = source_part_line(ctx["service_request"]["id"], ctx["mechanic"]["id"],
                          part["id"], quantity=1)
    assert pl["unit_price_cents"] == 15
    assert pl["line_total_cents"] == 15


def test_part_markup_band_c_marginal_tiers(api):
    """PRD §3.9: "The per-unit markup in cents is the first-band amount times 0.45, plus
    the second-band amount times 0.30, plus the third-band amount times 0.18, with that
    marginal sum rounded half-up to a whole number of cents."
    PRD §3.9: "Because each band is marked up at its own rate and the results summed,
    this is a true marginal computation and not a single blended rate applied to the
    whole cost."

    Design: Corner/calculations/markup_band_c_all_tiers
    """
    part = create_catalog_part(wholesale_cost_cents=30000, sku="BIG1", name="Compressor")
    ctx = setup_in_progress_request(mechanic_rate=9000, email="c13@x.com")
    pl = source_part_line(ctx["service_request"]["id"], ctx["mechanic"]["id"],
                          part["id"], quantity=1)
    assert pl["unit_price_cents"] == 38550
    assert pl["line_total_cents"] == 38550


def test_source_part_line_computed_read(api):
    """PRD §3.6: "snapshots the catalog part's wholesale cost into the line's
    `unit_cost_cents`, and computes the line's `unit_price_cents` and `line_total_cents`
    through the parts markup of §3.9. A directly sourced part is not an add-on, so its
    `is_addon` flag is false."

    Design: Corner/endpoints/source_part_line_computed_read
    """
    part = create_catalog_part(wholesale_cost_cents=4000, sku="EP1", name="Pad")
    ctx = setup_in_progress_request(mechanic_rate=9000, email="c17@x.com")
    pl = source_part_line(ctx["service_request"]["id"], ctx["mechanic"]["id"],
                          part["id"], quantity=2)
    assert pl["unit_price_cents"] == 5800
    assert pl["line_total_cents"] == 11600
    assert pl["status"] == "SOURCED"


# ── Difficulty: final total sum-hours-then-round (mode a) ──

def test_final_total_sum_hours_then_round(api):
    """PRD §3.10: "The labour hours are the visit's `logged_labor_hours` plus the sum of
    `add_on_labor_hours` across only those inspection findings that ended in
    `APPROVED`. Those total hours are multiplied by the mechanic's own
    `labor_rate_cents_per_hour`, and the product is rounded half-up to whole cents — the
    hours are summed first and the single product is rounded once, not rounded per
    finding."

    Design: Difficulty/combinatorial_formula/final_total_sum_hours_then_round_mode_a
    """
    ctx = setup_in_progress_request(mechanic_rate=100, estimated_labor_hours=1.0,
                                    estimated_parts_cents=0, labor_rate_cents_per_hour=100,
                                    email="m4@x.com")
    sr, mechanic, jv = ctx["service_request"], ctx["mechanic"], ctx["job_visit"]
    finding = add_finding(sr["id"], mechanic["id"], jv["id"],
                          description="extra labor", add_on_labor_hours=0.3335)
    resolve_addons(sr["id"], ctx["customer"]["id"],
                   [{"finding_id": finding["id"], "decision": "APPROVED"}])
    finish_visit(jv["id"], mechanic["id"], logged_labor_hours=0.3335, payment_method="CARD")

    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["final_total_cents"] == 67
    assert sr_after["status"] == "COMPLETED"


def test_final_total_completes_request_with_summed_labor(api):
    """PRD §3.10: "Those total hours are multiplied by the mechanic's own
    `labor_rate_cents_per_hour`, and the product is rounded half-up to whole cents — the
    hours are summed first and the single product is rounded once, not rounded per
    finding."
    PRD §3.6: "moves the visit `ON_SITE_WORKING → FINISHED` ... (which in turn drives the
    request `IN_PROGRESS → COMPLETED`)".

    Design: Difficulty/combinatorial_formula/final_total_sum_hours_then_round_mode_a
    """
    ctx = setup_in_progress_request(mechanic_rate=100, estimated_labor_hours=1.0,
                                    estimated_parts_cents=0, labor_rate_cents_per_hour=100,
                                    email="m4b@x.com")
    sr, mechanic, jv = ctx["service_request"], ctx["mechanic"], ctx["job_visit"]
    finding = add_finding(sr["id"], mechanic["id"], jv["id"],
                          description="extra labor", add_on_labor_hours=0.3335)
    resolve_addons(sr["id"], ctx["customer"]["id"],
                   [{"finding_id": finding["id"], "decision": "APPROVED"}])
    jv_finished = finish_visit(jv["id"], mechanic["id"], logged_labor_hours=0.3335,
                               payment_method="CARD")
    assert jv_finished["visit_status"] == "FINISHED"
    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["final_total_cents"] == 67


# ── Corner: fleet labor discount applied in quote ──

def test_fleet_labor_discount_applied_in_quote(api):
    """PRD §3.3: "If the service request carries a fleet account, that labour figure is
    then multiplied by one minus the fleet account's `labor_discount_pct` and rounded
    half-up to whole cents; for a retail request the labour figure is used unchanged.
    The grand total is then the discounted (or undiscounted) labour figure plus the
    estimated parts cents plus the tow fee cents".

    Design: Corner/calculations/fleet_labor_discount_applied_in_quote
    """
    from test_helpers import create_fleet_account
    fleet = create_fleet_account(credit_limit_cents=1_000_000, labor_discount_pct=0.20,
                                 company_name="Disc Fleet")
    ctx = setup_quoted_request(fleet_account_id=fleet["id"], estimated_labor_hours=2.0,
                               estimated_parts_cents=8000, labor_rate_cents_per_hour=9000,
                               email="c14@x.com")
    quote = validate_success(api.get_quote(ctx["quote"]["id"], DISPATCHER), 200)
    assert quote["quoted_total_cents"] == 22400


# ── Difficulty: estimate vs final divergence on the same request ──

def test_estimate_vs_final_total_diverge_on_service_request(api):
    """PRD §3.3: "This estimate is deliberately distinct from the final bill. The
    estimate looks forward from estimated hours and estimated parts; the final total,
    described in §3.6, looks backward at the hours actually logged and the part lines
    actually installed, so the two figures generally diverge."

    Design: Difficulty/dual_variant_calc/estimate_vs_final_total_diverge_on_service_request
    """
    part = create_catalog_part(wholesale_cost_cents=4000, sku="CP1", name="Brake Pad")
    ctx = setup_dispatched_request(estimated_labor_hours=2.0, estimated_parts_cents=8000,
                                   labor_rate_cents_per_hour=9000, mechanic_rate=9000,
                                   scheduled_start_utc="2026-04-02T09:00:00Z",
                                   scheduled_end_utc="2026-04-02T11:00:00Z",
                                   email="m1@x.com")
    sr, mechanic, jv = ctx["service_request"], ctx["mechanic"], ctx["job_visit"]
    assert sr["estimate_total_cents"] == 26000  # frozen estimate copied at approval

    source_part_line(sr["id"], mechanic["id"], part["id"], quantity=2)
    mech_headers = make_mechanic_headers(mechanic["id"])
    get_success_data(api.depart(jv["id"], mech_headers))
    get_success_data(api.start_work(jv["id"], mech_headers))
    finish_visit(jv["id"], mechanic["id"], logged_labor_hours=2.5, payment_method="CARD")

    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    assert sr_after["estimate_total_cents"] == 26000
    assert sr_after["final_total_cents"] == 34100
    assert sr_after["final_total_cents"] != sr_after["estimate_total_cents"]


def test_estimate_frozen_after_approval_independent_of_final(api):
    """PRD §3.2: "the quote moves `SENT → APPROVED` and its input fields are frozen
    (version-pinned) so the approved figures cannot later shift, the request copies the
    quote's `quoted_total_cents` into its own `estimate_total_cents`".
    PRD §3.10: "The final total is the discounted (or undiscounted) labour figure plus
    the parts sum plus the tow component, and it is stored on the request and copied to
    the payment's `total_due_cents`."

    Design: Difficulty/dual_variant_calc/estimate_vs_final_total_diverge_on_service_request
    """
    part = create_catalog_part(wholesale_cost_cents=4000, sku="CP1b", name="Brake Pad")
    ctx = setup_dispatched_request(estimated_labor_hours=2.0, estimated_parts_cents=8000,
                                   labor_rate_cents_per_hour=9000, mechanic_rate=9000,
                                   scheduled_start_utc="2026-04-02T09:00:00Z",
                                   scheduled_end_utc="2026-04-02T11:00:00Z",
                                   email="m1b@x.com")
    sr, mechanic, jv = ctx["service_request"], ctx["mechanic"], ctx["job_visit"]
    source_part_line(sr["id"], mechanic["id"], part["id"], quantity=2)
    mech_headers = make_mechanic_headers(mechanic["id"])
    get_success_data(api.depart(jv["id"], mech_headers))
    get_success_data(api.start_work(jv["id"], mech_headers))
    finish_visit(jv["id"], mechanic["id"], logged_labor_hours=2.5, payment_method="CARD")

    sr_after = validate_success(api.get_service_request(sr["id"], DISPATCHER), 200)
    # The estimate that was pinned at approval is unchanged by the larger final actuals.
    assert sr_after["estimate_total_cents"] == 26000
    payment = get_request_payment(sr["id"])
    assert payment["total_due_cents"] == 34100
