"""Dual-variant calculations on two different domains: provisional vs final visit cost, and
projected vs chronological technician risk score. Also the loyalty-discount tier selection
and the free re-clean cost. Translates Difficulty rule dual_variant_calc and the loyalty /
re-clean corner instances.
"""
import math

from test_helpers import (
    validate_success, get_success_data,
    setup_scheduled_visit, setup_completed_visit, setup_open_claim,
    setup_accepted_quote, create_clear_weather_window, create_technician,
    create_visit, schedule_visit, reserve_crew, confirm_crew, upload_photo,
    start_visit, complete_visit, get_invoice_for_visit, set_clock,
    create_plan, generate_plan_visit,
    TEST_USERS, make_field_tech_headers,
)

DISP = TEST_USERS["dispatcher_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Difficulty / dual_variant_calc
# ─────────────────────────────────────────────────────────────────────────

def test_provisional_and_final_cost_diverge_on_remeasure(api):
    """PRD §3.7: "The visit's `provisional_cost_cents`, set at scheduling, is the
    forward-looking estimate; the `final_cost_cents` is the actual figure and diverges from
    the provisional whenever the re-measured areas differ from the quoted areas."
    PRD §3.5: "the visit's `provisional_cost_cents` is set to the backing quote's frozen
    `total_cents` — the estimate".

    Design: Difficulty/dual_variant_calc/visit_provisional_vs_final_cost_diverges
    """
    # 2-story property, ROOF 2000 + SIDING 1500 => quote total 92750 (provisional).
    ctx = setup_scheduled_visit(
        property_overrides={"stories": 2, "roof_sqft": 2000, "siding_sqft": 1500},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000), ("SIDING", "HOUSE_WASH", 1500)],
    )
    visit = ctx["visit"]
    tech = ctx["technician"]
    assert visit["provisional_cost_cents"] == 92750, visit["provisional_cost_cents"]
    asg = confirm_crew(reserve_crew(visit["id"], tech["id"])["id"])
    upload_photo(visit["id"], "BEFORE", tech["id"])
    start_visit(visit["id"], tech["id"])
    upload_photo(visit["id"], "AFTER", tech["id"])
    completed = complete_visit(visit["id"], tech["id"],
                               re_measured_roof_sqft=2200, re_measured_siding_sqft=1600)
    # actual roof 2200 -> 66550, siding 1600 -> 26400, subtotal 92950 + 7500 travel = 100450.
    assert completed["final_cost_cents"] == 100450, completed["final_cost_cents"]
    assert completed["final_cost_cents"] != completed["provisional_cost_cents"]


def test_final_cost_reprices_actual_areas(api):
    """PRD §3.7: "For each line of the backing quote, take that surface's actual re-measured
    area, multiply by the same surface rate keyed on the line's `surface_type` (22, 15, or 11
    cents per square foot for `ROOF`, `SIDING`, `CONCRETE`), by the same service multiplier
    keyed on `service_type` (1.25, 1.0, or 1.1), and by the same height multiplier of 1.0
    plus 0.10 for each story above the first, then round that line half-up to whole cents."

    Design: Difficulty/dual_variant_calc/visit_provisional_vs_final_cost_diverges
    """
    ctx = setup_completed_visit(
        property_overrides={"stories": 2, "roof_sqft": 2000, "siding_sqft": 1500},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000), ("SIDING", "HOUSE_WASH", 1500)],
        re_measured_roof_sqft=2200, re_measured_siding_sqft=1600,
    )
    completed = ctx["completed_visit"]
    assert completed["final_cost_cents"] == 100450, completed["final_cost_cents"]


def test_risk_score_projected_vs_chronological_diverge(api):
    """PRD §3.11: "In **projected** mode, the score is forward-looking. Count the technician's
    currently committed assignments — those whose status is `RESERVED` or `CONFIRMED`.
    Multiply that count by the per-load risk weight of 20."
    PRD §3.11: "Walking that ordered list from the earliest completion, contribute for each
    assignment the per-load weight of 20 multiplied by a geometric decay of 0.5 raised to the
    position index, where the earliest completion has index 0".

    Design: Difficulty/dual_variant_calc/technician_risk_projected_vs_chronological_diverges
    """
    set_clock()
    # One insured tech (cert 2); Visit 1 driven to COMPLETED (CONFIRMED assignment),
    # Visit 2 left SCHEDULED with a RESERVED assignment for the same tech.
    ctx = setup_accepted_quote(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
    )
    cust = ctx["customer"]
    route = ctx["route"]
    create_clear_weather_window(route["id"], start="2026-05-01T00:00:00Z",
                                end="2026-05-02T23:59:59Z", wind_mph=5)
    tech = create_technician(ladder_cert_max_stories=2, insurance_status="ACTIVE")
    # Second property + accepted quote for Visit 2.
    from test_helpers import create_property, create_draft_quote, add_line_item, send_quote, accept_quote
    prop2 = create_property(cust["id"], route["id"], stories=2, roof_sqft=2000)
    q2 = create_draft_quote(prop2["id"], prop2["version"])
    add_line_item(q2["id"], "ROOF", "ROOF_SOFT_WASH", 2000)
    send_quote(q2["id"])
    accept_quote(q2["id"], cust["id"])

    # Visit 1 -> COMPLETED (assignment CONFIRMED).
    v1 = create_visit(ctx["property"]["id"], ctx["quote"]["id"], scheduled_date="2026-05-01")
    v1 = schedule_visit(v1["id"], v1["version"])
    confirm_crew(reserve_crew(v1["id"], tech["id"], "2026-05-01T14:00:00Z")["id"])
    upload_photo(v1["id"], "BEFORE", tech["id"])
    start_visit(v1["id"], tech["id"])
    upload_photo(v1["id"], "AFTER", tech["id"])
    complete_visit(v1["id"], tech["id"], re_measured_roof_sqft=2000)

    # Visit 2 -> SCHEDULED with a RESERVED assignment for the same tech (different day).
    v2 = create_visit(prop2["id"], q2["id"], scheduled_date="2026-05-02")
    v2 = schedule_visit(v2["id"], v2["version"])
    reserve_crew(v2["id"], tech["id"], "2026-05-02T14:00:00Z")

    projected = validate_success(
        api.get_technician_risk_score(tech["id"], DISP, params={"mode": "projected"}))
    chrono = validate_success(
        api.get_technician_risk_score(tech["id"], DISP, params={"mode": "chronological"}))
    # projected: 2 committed (V1 CONFIRMED + V2 RESERVED) * 20 = 40, insured -> +0.
    assert projected["risk_score"] == 40, projected["risk_score"]
    # chronological: 1 COMPLETED-visit assignment -> 20 * 0.5^0 = 20.
    assert chrono["risk_score"] == 20, chrono["risk_score"]
    assert projected["risk_score"] != chrono["risk_score"]


def test_risk_projected_adds_uninsured_penalty(api):
    """PRD §3.11: "Then, if the technician's `insurance_status` is `EXPIRED`, add the
    uninsured penalty of 50; if the insurance is `ACTIVE`, add nothing. Projected mode applies
    no decay."

    Design: Difficulty/dual_variant_calc/technician_risk_projected_vs_chronological_diverges
    """
    # A fresh EXPIRED tech with no assignments: projected = 0*20 + 50 = 50.
    tech = create_technician(ladder_cert_max_stories=3, insurance_status="EXPIRED")
    projected = validate_success(
        api.get_technician_risk_score(tech["id"], DISP, params={"mode": "projected"}))
    assert projected["risk_score"] == 50, projected["risk_score"]


# ─────────────────────────────────────────────────────────────────────────
# Corner / calculations
# ─────────────────────────────────────────────────────────────────────────

def test_loyalty_discount_tier_at_five_visits_is_ten_percent(api):
    """PRD §3.8: "If that count is at least 10, the discount percentage is 0.15; otherwise if
    it is at least 5, the percentage is 0.10; otherwise if it is at least 2, the percentage is
    0.05; otherwise it is 0. The `loyalty_discount_cents` is the `final_cost_cents` multiplied
    by that percentage, rounded half-up to whole cents. The `amount_due_cents` is the
    `final_cost_cents` minus the `loyalty_discount_cents`, floored at 0 so it can never be
    negative."

    Design: Corner/calculations/loyalty_discount_tier5_ten_percent
    """
    set_clock()
    ctx = setup_accepted_quote(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
    )
    cust, route, prop, quote = ctx["customer"], ctx["route"], ctx["property"], ctx["quote"]
    create_clear_weather_window(route["id"], start="2026-05-01T00:00:00Z",
                                end="2026-05-10T23:59:59Z", wind_mph=5)
    tech = create_technician()
    plan = create_plan(prop["id"], quote["id"], cadence_days=1, start_utc="2026-05-01T00:00:00Z")
    v5 = None
    for _ in range(5):
        v5 = generate_plan_visit(plan["id"])
    # 5 generated visits => visits_generated_count == 5 (completion leaves it unchanged) -> 10% tier.
    v5 = schedule_visit(v5["id"], v5["version"])
    confirm_crew(reserve_crew(v5["id"], tech["id"], "2026-05-05T14:00:00Z")["id"])
    upload_photo(v5["id"], "BEFORE", tech["id"])
    start_visit(v5["id"], tech["id"])
    upload_photo(v5["id"], "AFTER", tech["id"])
    completed = complete_visit(v5["id"], tech["id"], re_measured_roof_sqft=2000)
    inv = get_invoice_for_visit(v5["id"])
    final = completed["final_cost_cents"]
    expected_disc = int(math.floor(final * 0.10 + 0.5))
    assert inv["loyalty_discount_cents"] == expected_disc, (
        inv["loyalty_discount_cents"], expected_disc, final)
    assert inv["amount_due_cents"] == max(0, final - expected_disc), inv["amount_due_cents"]


def test_reclean_visit_final_cost_and_invoice_are_zero(api):
    """PRD §3.7: "A re-clean visit — one whose `reclean_of_visit_id` is set — is free: its
    `final_cost_cents` is 0 regardless of measurements."
    PRD §3.8: "Because a re-clean visit has a `final_cost_cents` of 0, both its
    `loyalty_discount_cents` and its `amount_due_cents` are 0."

    Design: Corner/calculations/reclean_visit_final_cost_zero_and_invoice_zero
    """
    ctx = setup_open_claim(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
    )
    tech = ctx["technician"]
    approved = validate_success(api.approve_claim(ctx["claim"]["id"], DISP))
    rc_id = approved["reclean_visit_id"]
    rc = get_success_data(api.get_visit(rc_id, DISP))
    rc = schedule_visit(rc["id"], rc["version"])
    confirm_crew(reserve_crew(rc["id"], tech["id"], "2026-05-02T14:00:00Z")["id"])
    upload_photo(rc["id"], "BEFORE", tech["id"])
    start_visit(rc["id"], tech["id"])
    upload_photo(rc["id"], "AFTER", tech["id"])
    completed = complete_visit(rc["id"], tech["id"], re_measured_roof_sqft=2000)
    assert completed["final_cost_cents"] == 0, completed["final_cost_cents"]
    inv = get_invoice_for_visit(rc["id"])
    assert inv["amount_due_cents"] == 0, inv["amount_due_cents"]
