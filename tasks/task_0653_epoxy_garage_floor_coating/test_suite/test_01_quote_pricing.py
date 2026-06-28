"""Quote pricing engine: estimate vs final, the combinatorial formula, the
pinned evaluation order, volume-tier boundaries, the small-job floor, and
financing payment.

All expected cent values are literal, pre-computed from the PRD §3.4 pricing
engine and §3.7 proration rules.
"""
from test_helpers import (
    api_client, TEST_USERS, get_success_data, validate_success,
    make_customer_headers, make_crew_headers,
    create_system_with_color, create_customer, create_project, record_assessment,
    create_estimate_quote, send_quote, project_version, set_clock,
    create_crew, book_install, setup_completed_install, setup_accepted_project,
    create_financing_plan,
)
from test_helpers.factories import complete_install_payload

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
SCHED = TEST_USERS["scheduler_headers"]


# ===========================================================================
# Difficulty/dual_variant_calc/quote_estimate_vs_final_grand_total_diverge
# ===========================================================================
def test_estimate_grand_total_metallic_heavy_peak():
    """PRD §3.4: "The system material subtotal `system_material_cents` is the
    per-square-foot material rate for the chosen sku ... multiplied by the priced
    area; if the system's family is `METALLIC`, that material subtotal is then
    multiplied by the metallic complexity factor of 1.20 and rounded half up to
    whole cents".

    Design: Difficulty/dual_variant_calc/quote_estimate_vs_final_grand_total_diverge
    """
    sys, color = create_system_with_color(family="METALLIC", sku="METALLIC")
    cust = create_customer("Dana Owner", email="dana1@example.com")
    proj = create_project(cust["id"])
    assess = record_assessment(
        proj["id"], measured_sqft=600, oil_stain_pct=100, crack_density=50,
        crack_linear_ft=30, spalling=False, moisture_pct=0,
    )
    quote = create_estimate_quote(
        proj["id"], assess["id"], sys["id"], color["id"], install_season="PEAK"
    )
    assert quote["grand_total_cents"] == 827507, (
        f"ESTIMATE grand_total expected 827507, got {quote['grand_total_cents']}"
    )


def test_final_quote_reprices_from_onsite_sqft_diverges_from_estimate():
    """PRD §3.6: "a new quote with `variant` of `FINAL` is created using exactly
    the same pricing engine as the estimate, except that its billable area comes
    from the install job's `as_measured_sqft` and its crack figure from
    `as_measured_crack_ft` rather than from the assessment - so a slab that
    measured differently in the field produces a different `grand_total_cents`."

    Design: Difficulty/dual_variant_calc/quote_estimate_vs_final_grand_total_diverge
    """
    set_clock("2026-05-01T00:00:00Z")
    sys, color = create_system_with_color(family="METALLIC", sku="METALLIC")
    crew = create_crew("Crew Metal A", metallic_certified=True, max_sqft_per_day=1000)
    cust = create_customer("Dana Owner", email="dana2@example.com")
    proj = create_project(cust["id"])
    assess = record_assessment(
        proj["id"], measured_sqft=600, oil_stain_pct=100, crack_density=50,
        crack_linear_ft=30, spalling=False, moisture_pct=0,
    )
    quote = create_estimate_quote(
        proj["id"], assess["id"], sys["id"], color["id"], install_season="PEAK"
    )
    estimate_grand = quote["grand_total_cents"]
    send_quote(quote["id"])
    pv = project_version(proj["id"])
    get_success_data(api_client.accept_quote(
        quote["id"], {"expected_project_version": pv}, make_customer_headers(cust["id"])
    ))
    job = book_install(proj["id"], crew["id"], install_date="2026-05-10T09:00:00Z")
    set_clock("2026-05-10T09:00:00Z")
    get_success_data(api_client.start_install_job(job["id"], make_crew_headers(crew["id"])))
    get_success_data(api_client.complete_install_job(
        job["id"], complete_install_payload(700, 40), make_crew_headers(crew["id"])
    ))
    finals = get_success_data(
        api_client.list_quotes(proj["id"], SALES, params={"variant": "FINAL"})
    )
    final_grand = finals[0]["grand_total_cents"]
    assert estimate_grand == 827507, f"estimate expected 827507, got {estimate_grand}"
    assert final_grand == 969797, f"FINAL expected 969797, got {final_grand}"
    assert final_grand != estimate_grand, "FINAL (sqft 700) must diverge from ESTIMATE (sqft 600)"


# ===========================================================================
# Difficulty/combinatorial_formula/quote_metallic_mult_and_volume_tier_nonlinear
# ===========================================================================
def test_metallic_material_multiplier_applied():
    """PRD §3.4: "if the system's family is `METALLIC`, that material subtotal is
    then multiplied by the metallic complexity factor of 1.20 and rounded half up
    to whole cents (the complexity factor applies to material only, never to labor)."

    Design: Difficulty/combinatorial_formula/quote_metallic_mult_and_volume_tier_nonlinear
    """
    sys, color = create_system_with_color(family="METALLIC", sku="METALLIC")
    cust = create_customer("Dana Owner", email="dana3@example.com")
    proj = create_project(cust["id"])
    assess = record_assessment(
        proj["id"], measured_sqft=600, oil_stain_pct=100, crack_density=50,
        crack_linear_ft=30, spalling=False, moisture_pct=0,
    )
    quote = create_estimate_quote(
        proj["id"], assess["id"], sys["id"], color["id"], install_season="PEAK"
    )
    assert quote["system_material_cents"] == 576000, (
        f"expected 576000 (800*600*1.20), got {quote['system_material_cents']}"
    )
    assert quote["grand_total_cents"] == 827507


def test_volume_discount_tier_keyed_on_subtotal():
    """PRD §3.4: "the discount percentage is 10 percent when the base is at least
    600,000 cents, otherwise 5 percent when the base is at least 300,000 cents, and
    otherwise 0 percent ... The system stores that tier in `volume_discount_pct_bps`
    as basis points - 0, 500, or 1000".

    Design: Difficulty/combinatorial_formula/quote_metallic_mult_and_volume_tier_nonlinear
    """
    sys, color = create_system_with_color(family="METALLIC", sku="METALLIC")
    cust = create_customer("Dana Owner", email="dana4@example.com")
    proj = create_project(cust["id"])
    assess = record_assessment(
        proj["id"], measured_sqft=600, oil_stain_pct=100, crack_density=50,
        crack_linear_ft=30, spalling=False, moisture_pct=0,
    )
    quote = create_estimate_quote(
        proj["id"], assess["id"], sys["id"], color["id"], install_season="PEAK"
    )
    assert quote["volume_discount_pct_bps"] == 1000, (
        f"pre_discount 891675 >= 600000 -> 1000 bps, got {quote['volume_discount_pct_bps']}"
    )
    assert quote["grand_total_cents"] == 827507


# ===========================================================================
# Difficulty/combinatorial_formula/quote_eval_order_discount_before_mobilization_pinned
# ===========================================================================
def _eval_order_quote(season="STANDARD"):
    sys, color = create_system_with_color(family="FLAKE", sku="FLAKE_STANDARD")
    cust = create_customer("Dana Owner", email=f"dana-eo-{season}@example.com")
    proj = create_project(cust["id"])
    assess = record_assessment(
        proj["id"], measured_sqft=600, oil_stain_pct=50, crack_density=20,
        crack_linear_ft=15, spalling=True, moisture_pct=30,
    )
    return create_estimate_quote(
        proj["id"], assess["id"], sys["id"], color["id"], install_season=season
    )


def test_mobilization_added_after_discount():
    """PRD §3.4: "The `grand_total_cents` is the pre-discount base minus the
    discount, plus the mobilization fee - the mobilization fee is added *after* the
    discount and is never itself discounted."

    Design: Difficulty/combinatorial_formula/quote_eval_order_discount_before_mobilization_pinned
    """
    quote = _eval_order_quote()
    assert quote["discount_cents"] == 18975, f"expected 18975 (5% of 379500), got {quote['discount_cents']}"
    assert quote["mobilization_cents"] == 25000, f"expected 25000, got {quote['mobilization_cents']}"
    assert quote["grand_total_cents"] == 385525, (
        f"expected 379500 - 18975 + 25000 = 385525, got {quote['grand_total_cents']}"
    )


def test_mobilization_is_flat_25000():
    """PRD §3.4: "The flat trip fee `mobilization_cents` is exactly 25,000 cents."

    Design: Difficulty/combinatorial_formula/quote_eval_order_discount_before_mobilization_pinned
    """
    quote = _eval_order_quote(season="OFF")
    assert quote["mobilization_cents"] == 25000, (
        f"mobilization is a flat 25000 regardless of season, got {quote['mobilization_cents']}"
    )


# ===========================================================================
# Difficulty/boundary_precision_check/volume_tier_boundary_480_vs_479_sqft
# ===========================================================================
def _volume_boundary_quote(sqft, email):
    sys, color = create_system_with_color(family="FLAKE", sku="FLAKE_STANDARD")
    cust = create_customer("Dana Owner", email=email)
    proj = create_project(cust["id"])
    assess = record_assessment(
        proj["id"], measured_sqft=sqft, oil_stain_pct=50, crack_density=20,
        crack_linear_ft=10, spalling=True, moisture_pct=30,
    )
    return create_estimate_quote(
        proj["id"], assess["id"], sys["id"], color["id"], install_season="STANDARD"
    )


def test_volume_tier_at_boundary_480_sqft():
    """PRD §3.4: "the discount percentage is ... 5 percent when the base is at
    least 300,000 cents ... both thresholds are inclusive."

    Design: Difficulty/boundary_precision_check/volume_tier_boundary_480_vs_479_sqft
    """
    quote = _volume_boundary_quote(480, "vb480@example.com")
    assert quote["volume_discount_pct_bps"] == 500, (
        f"pre_discount exactly 300000 (>= boundary) -> 500 bps, got {quote['volume_discount_pct_bps']}"
    )
    assert quote["grand_total_cents"] == 310000, f"expected 310000, got {quote['grand_total_cents']}"


def test_volume_tier_just_below_boundary_479_sqft():
    """PRD §3.4: "the discount percentage is ... 5 percent when the base is at
    least 300,000 cents, and otherwise 0 percent; both thresholds are inclusive."

    Design: Difficulty/boundary_precision_check/volume_tier_boundary_480_vs_479_sqft
    """
    quote = _volume_boundary_quote(479, "vb479@example.com")
    assert quote["volume_discount_pct_bps"] == 0, (
        f"pre_discount 299375 (< boundary) -> 0 bps, got {quote['volume_discount_pct_bps']}"
    )
    assert quote["grand_total_cents"] == 324375, (
        f"expected 324375 (no discount; smaller job costs more), got {quote['grand_total_cents']}"
    )


# ===========================================================================
# Corner/calculations/quote_small_job_billable_floor_applied
# ===========================================================================
def test_small_job_priced_at_billable_floor():
    """PRD §3.4: "it determines the billable area `priced_sqft`, which for an
    estimate is the greater of the assessment's `measured_sqft` and the small-job
    floor of 250 square feet."

    Design: Corner/calculations/quote_small_job_billable_floor_applied
    """
    sys, color = create_system_with_color(family="FLAKE", sku="FLAKE_STANDARD")
    cust = create_customer("Cora Customer", email="cora-small@example.com")
    proj = create_project(cust["id"])
    assess = record_assessment(
        proj["id"], measured_sqft=100, oil_stain_pct=20, crack_density=5,
        crack_linear_ft=0, spalling=False, moisture_pct=10,
    )
    quote = create_estimate_quote(
        proj["id"], assess["id"], sys["id"], color["id"], install_season="STANDARD"
    )
    assert quote["priced_sqft"] == 250, f"expected floored 250, got {quote['priced_sqft']}"
    assert quote["grand_total_cents"] == 150000, f"expected 150000, got {quote['grand_total_cents']}"


# ===========================================================================
# Corner/calculations/financing_monthly_payment_computed_on_quote
# ===========================================================================
def test_financing_monthly_payment_zero_apr():
    """PRD §3.4: "When that monthly rate is exactly zero, the monthly payment is
    the principal divided by the `term_months`, rounded half up."

    Design: Corner/calculations/financing_monthly_payment_computed_on_quote
    """
    fp = create_financing_plan("0pct 24mo", apr_bps=0, term_months=24, min_principal_cents=0)
    sys, color = create_system_with_color(family="FLAKE", sku="FLAKE_STANDARD")
    cust = create_customer("Cora Customer", email="cora-fin@example.com")
    proj = create_project(cust["id"])
    assess = record_assessment(
        proj["id"], measured_sqft=600, oil_stain_pct=50, crack_density=20,
        crack_linear_ft=15, spalling=True, moisture_pct=30,
    )
    quote = create_estimate_quote(
        proj["id"], assess["id"], sys["id"], color["id"],
        install_season="STANDARD", financing_plan_id=fp["id"],
    )
    assert quote["grand_total_cents"] == 385525, f"expected 385525, got {quote['grand_total_cents']}"
    assert quote["monthly_payment_cents"] == 16064, (
        f"expected round_half_up(385525/24)=16064, got {quote['monthly_payment_cents']}"
    )
