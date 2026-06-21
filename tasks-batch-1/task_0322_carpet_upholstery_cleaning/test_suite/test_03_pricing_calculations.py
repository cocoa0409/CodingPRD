"""Pricing-engine tests: the forward quote, the chronological settled price, the
add-on line-price branch, recurring discounts, and the heavy-soiling escalation
boundary.

Covers difficulty instances dual_variant_calc, combinatorial_formula, and the
escalation-count boundary, plus corner calculation/consistency instances.
"""
from test_helpers import (
    validate_success,
    assert_cleaning_job,
    assert_addon,
    setup_quoted_job,
    setup_invoiced_job,
    create_customer,
    create_catalog,
    create_plan,
    create_job,
    add_room,
    quote_job,
    make_customer_headers,
)


# ─── dual_variant_calc ─────────────────────────────────────────

def test_quote_vs_settle_diverge_on_three_heavy_rooms(api):
    """PRD §3.4: "if the running count of HEAVY rooms reaches three or more, a
    one-time escalation surcharge of 4000 cents is added; if there are fewer than
    three heavy rooms, no escalation is added."
    PRD §3.4: "Because the escalation surcharge appears only here, a job with
    three or more heavy rooms settles strictly higher than it quoted, while a
    lightly soiled job settles at the same figure it quoted."

    Design: Difficulty/dual_variant_calc/dual_variant_quote_vs_settle_heavy_job
    """
    ctx = setup_invoiced_job(
        rooms=[("Living Room", 100, "HEAVY"), ("Den", 120, "HEAVY"), ("Hall", 80, "HEAVY")],
    )
    job = ctx["job"]
    assert job["quoted_price_cents"] == 24000, \
        f"forward quote should be 24000, got {job['quoted_price_cents']}"
    assert job["settled_price_cents"] == 28000, \
        f"settled should add 4000 escalation -> 28000, got {job['settled_price_cents']}"
    assert ctx["invoice"]["amount_due_cents"] == 28000, \
        f"invoice face = settled price = 28000, got {ctx['invoice']['amount_due_cents']}"


def test_protectant_line_price_order_sensitivity(api):
    """PRD §3.2: "a PROTECTANT add-on takes the catalog's protectant_cents_per_sqft
    multiplied by the job's current total_sqft, rounded half up to whole cents."
    PRD §3.2: "a PROTECTANT add-on created before any room exists — when total_sqft
    is still 0 — freezes a line_price_cents of 0, and that frozen value is not
    retroactively corrected when rooms are added afterward."

    Design: Difficulty/dual_variant_calc/dual_variant_protectant_price_order_sensitivity
    """
    customer = create_customer()
    catalog = create_catalog()  # protectant_cents_per_sqft = 12
    hdr = make_customer_headers(customer["id"])

    job_early = create_job(customer, catalog["id"])
    job_late = create_job(customer, catalog["id"])
    # job_late gets a 300-sqft room first, then PROTECTANT.
    add_room(job_late, customer["id"], area_label="Great Room", area_sqft=300, soiling_level="LIGHT")

    early_res = api.add_addon(job_early["id"], {"addon_type": "PROTECTANT"}, hdr)
    early_addon = validate_success(early_res, 201)
    assert_addon(early_addon)

    late_res = api.add_addon(job_late["id"], {"addon_type": "PROTECTANT"}, hdr)
    late_addon = validate_success(late_res, 201)
    assert_addon(late_addon)

    assert early_addon["line_price_cents"] == 0, \
        f"protectant before any room (total_sqft=0) prices to 0, got {early_addon['line_price_cents']}"
    assert late_addon["line_price_cents"] == 3600, \
        f"protectant after 300-sqft room = 12*300 = 3600, got {late_addon['line_price_cents']}"


# ─── combinatorial_formula ─────────────────────────────────────

def test_quote_combines_rooms_addons_furniture_and_discount(api):
    """PRD §3.2: "the pre-discount total is the rooms subtotal plus the add-ons
    subtotal plus that furniture surcharge."
    PRD §3.2: "the discount amount is the pre-discount total multiplied by that
    percentage, rounded half up to whole cents exactly once. The frozen
    quoted_price_cents is the pre-discount total minus that single rounded
    discount amount."

    rooms: 200 LIGHT (200*50*1.0=10000) + 100 MODERATE (100*50*1.25=6250) = 16250;
    STAIN 2500; PROTECTANT after rooms 12*300=3600; move-furniture 3000;
    pre = 25350; MONTHLY 15% -> round_half_up(3802.5)=3803; quoted = 21547.

    Design: Difficulty/combinatorial_formula/combinatorial_mode_a_nonlinear_quote_with_discount
    """
    customer = create_customer()
    catalog = create_catalog()
    plan = create_plan(customer["id"], cadence="MONTHLY")
    ctx = setup_quoted_job(
        rooms=[("Living", 200, "LIGHT"), ("Office", 100, "MODERATE")],
        addons=["STAIN", "PROTECTANT"],
        customer=customer,
        catalog=catalog,
        plan_id=plan["id"],
        move_furniture=True,
    )
    job = ctx["job"]
    assert_cleaning_job(job)
    assert job["total_sqft"] == 300, f"total_sqft should be 300, got {job['total_sqft']}"
    assert job["quoted_price_cents"] == 21547, \
        f"quoted should be 21547, got {job['quoted_price_cents']}"


def test_quote_rounds_each_room_line_before_summing(api):
    """PRD §3.2: "that per-room line is rounded half up to whole cents *before*
    being added in; the rooms subtotal is the sum of those individually rounded
    room lines."

    Three rooms at rate 7, 3 sqft, MODERATE: 7*3*1.25 = 26.25 -> round_half_up 26
    each -> sum 78 (the sum-then-round path 78.75 -> 79 is excluded).

    Design: Difficulty/combinatorial_formula/combinatorial_mode_b_round_then_sum_order
    """
    ctx = setup_quoted_job(
        rooms=[("R1", 3, "MODERATE"), ("R2", 3, "MODERATE"), ("R3", 3, "MODERATE")],
        catalog_overrides={"base_rate_cents_per_sqft": 7},
    )
    assert ctx["job"]["quoted_price_cents"] == 78, \
        f"round-each-then-sum gives 78, got {ctx['job']['quoted_price_cents']}"


# ─── boundary_precision_check: escalation count ───────────────

def test_settled_no_escalation_at_two_heavy_rooms(api):
    """PRD §3.4: "if the running count of HEAVY rooms reaches three or more, a
    one-time escalation surcharge of 4000 cents is added; if there are fewer than
    three heavy rooms, no escalation is added."

    Two HEAVY rooms (100 sqft each, rate 50): 100*50*1.6 = 8000 each -> 16000;
    below the count-3 threshold so settled == quoted == 16000.

    Design: Difficulty/boundary_precision_check/boundary_heavy_escalation_count_at_three
    """
    ctx = setup_invoiced_job(
        rooms=[("H1", 100, "HEAVY"), ("H2", 100, "HEAVY")],
    )
    job = ctx["job"]
    assert job["quoted_price_cents"] == 16000, \
        f"quoted should be 16000, got {job['quoted_price_cents']}"
    assert job["settled_price_cents"] == 16000, \
        f"with 2 heavy rooms no escalation: settled == 16000, got {job['settled_price_cents']}"
    assert ctx["invoice"]["amount_due_cents"] == 16000, \
        f"invoice face 16000, got {ctx['invoice']['amount_due_cents']}"


# ─── corner: calculations ──────────────────────────────────────

def test_quarterly_discount_applied_in_quote(api):
    """PRD §3.1: "a QUARTERLY cadence earns ten percent."
    PRD §3.2: "the discount amount is the pre-discount total multiplied by that
    percentage, rounded half up to whole cents exactly once."

    One MODERATE 200-sqft room (rate 50): 200*50*1.25 = 12500 pre-discount;
    10% -> 1250; quoted = 11250.

    Design: Corner/calculations/recurring_quarterly_discount_applied_in_quote
    """
    customer = create_customer()
    plan = create_plan(customer["id"], cadence="QUARTERLY")
    ctx = setup_quoted_job(
        rooms=[("Den", 200, "MODERATE")],
        customer=customer,
        plan_id=plan["id"],
    )
    assert ctx["job"]["quoted_price_cents"] == 11250, \
        f"quarterly 10% discount -> 11250, got {ctx['job']['quoted_price_cents']}"


def test_stain_and_pet_addons_price_flat_from_catalog(api):
    """PRD §3.2: "a STAIN add-on takes the catalog's stain_addon_cents; a PET
    add-on takes the catalog's pet_addon_cents."

    Design: Corner/calculations/stain_pet_addon_flat_prices_from_catalog
    """
    customer = create_customer()
    catalog = create_catalog()  # stain 2500, pet 1800
    hdr = make_customer_headers(customer["id"])
    job = create_job(customer, catalog["id"])
    add_room(job, customer["id"], area_label="Rm", area_sqft=100, soiling_level="LIGHT")

    stain = validate_success(api.add_addon(job["id"], {"addon_type": "STAIN"}, hdr), 201)
    pet = validate_success(api.add_addon(job["id"], {"addon_type": "PET"}, hdr), 201)

    assert stain["line_price_cents"] == 2500, \
        f"STAIN flat = 2500, got {stain['line_price_cents']}"
    assert pet["line_price_cents"] == 1800, \
        f"PET flat = 1800, got {pet['line_price_cents']}"


def test_quote_response_carries_frozen_price_immediately(api):
    """PRD §3.2: "On a successful quote, the job's total_sqft is frozen as the sum
    of its rooms' area_sqft, and the forward-looking quoted_price_cents is computed
    and frozen."

    One LIGHT 100-sqft room (rate 50): 100*50*1.0 = 5000; the quote call's own
    response already carries quoted_price_cents and lifecycle_status QUOTED.

    Design: Corner/consistency_model/immediate_quote_visible_in_same_response
    """
    customer = create_customer()
    catalog = create_catalog()
    job = create_job(customer, catalog["id"])
    add_room(job, customer["id"], area_label="Rm", area_sqft=100, soiling_level="LIGHT")

    res = api.quote_job(job["id"], make_customer_headers(customer["id"]))
    quoted = validate_success(res, 200)
    assert quoted["quoted_price_cents"] == 5000, \
        f"5000 expected in quote response, got {quoted['quoted_price_cents']}"
    assert quoted["lifecycle_status"] == "QUOTED"
