"""Quote pricing (base / add-ons / tax / total), dual-variant reconciliation, and
financing APR/amortization. Translates Difficulty queue rules dual_variant_calc,
combinatorial_formula, and the financing boundary instance of boundary_precision_check.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_quote_payload, create_quote_accept_payload,
    create_manufacture_order_payload, create_financing_payload,
    setup_designed_project, setup_quoted_project, setup_permitting_project,
    setup_in_manufacture, make_homeowner_headers,
    TEST_USERS,
)

SD = TEST_USERS["sales_designer_headers"]
MF = TEST_USERS["manufacturer_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Rule 2: combinatorial_formula
# ─────────────────────────────────────────────────────────────────────────

def test_base_price_tiered_rate_times_material_multiplier(api):
    """PRD §3.2: "The base price is the project's current `footprint_sqft` multiplied by
    the per-square-foot rate, multiplied by the material multiplier, divided by 1,000,
    with the final product rounded half up to whole cents."
    PRD §3.2: "A per-square-foot rate in cents is selected by `structure_type` — 4,500
    cents for `SCREEN_ROOM`, 9,000 cents for `THREE_SEASON`, and 16,000 cents for
    `FOUR_SEASON`."

    Design: Difficulty/combinatorial_formula/base_price_tiered_rate_times_material_multiplier
    """
    ho, pj, m = setup_designed_project(
        homeowner_overrides={"ground_snow_load_psf": 40, "design_wind_speed_mph": 140},
        project_overrides={"structure_type": "FOUR_SEASON",
                           "material": "THERMAL_BREAK_ALUMINUM"},
        measurement_overrides={"width_in": 180, "depth_in": 160, "wall_height_in": 108,
                               "existing_slab": False},
    )
    q = validate_success(api.create_quote(create_quote_payload(pj["id"]), SD), 201)
    # 200.00 * 16000 * 1300 / 1000 = 4,160,000
    assert q["base_price_cents"] == 4160000, q["base_price_cents"]


def test_addons_slab_plus_engineering_for_four_season(api):
    """PRD §3.2: "If the currently accepted measurement's `existing_slab` is false, a slab
    pour of 320,150 cents is added. If the project's `requires_engineering` is true, an
    engineering stamp of 95,075 cents is added."

    Design: Difficulty/combinatorial_formula/base_price_tiered_rate_times_material_multiplier
    """
    ho, pj, m = setup_designed_project(
        homeowner_overrides={"ground_snow_load_psf": 40, "design_wind_speed_mph": 140},
        project_overrides={"structure_type": "FOUR_SEASON",
                           "material": "THERMAL_BREAK_ALUMINUM"},
        measurement_overrides={"width_in": 180, "depth_in": 160, "wall_height_in": 108,
                               "existing_slab": False},
    )
    q = validate_success(api.create_quote(create_quote_payload(pj["id"]), SD), 201)
    # slab 320150 + engineering stamp 95075 = 415,225 (no HOA, hoa_governed false)
    assert q["addons_cents"] == 415225, q["addons_cents"]


def test_tax_sum_then_round_order_pinned(api):
    """PRD §2.8: "sales tax is computed **once on the sum** of all taxable line items (base
    price plus add-ons) and then rounded a single time; it is never computed by rounding
    each line item's tax separately and summing those rounded amounts."

    Design: Difficulty/combinatorial_formula/tax_sum_then_round_order_pinned
    """
    # THREE_SEASON/ALUMINUM, wind 130 (requires_engineering true), 90x92 -> footprint 57.50,
    # existing_slab false. base = 57.50*9000*1000/1000 = 517500.
    ho, pj, m = setup_designed_project(
        homeowner_overrides={"ground_snow_load_psf": 10, "design_wind_speed_mph": 130},
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 90, "depth_in": 92, "wall_height_in": 96,
                               "existing_slab": False},
    )
    q = validate_success(api.create_quote(create_quote_payload(pj["id"]), SD), 201)
    assert q["base_price_cents"] == 517500, q["base_price_cents"]
    assert q["addons_cents"] == 415225, q["addons_cents"]
    # tax = round_half_up((517500 + 415225) * 75 / 1000) = 69954 (sum-then-round; per-line=69955)
    assert q["tax_cents"] == 69954, q["tax_cents"]


def test_total_is_base_plus_addons_plus_tax(api):
    """PRD §3.2: "The grand total, `total_cents`, is `base_price_cents` plus `addons_cents`
    plus `tax_cents`."

    Design: Difficulty/combinatorial_formula/tax_sum_then_round_order_pinned
    """
    ho, pj, m = setup_designed_project(
        homeowner_overrides={"ground_snow_load_psf": 10, "design_wind_speed_mph": 130},
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 90, "depth_in": 92, "wall_height_in": 96,
                               "existing_slab": False},
    )
    q = validate_success(api.create_quote(create_quote_payload(pj["id"]), SD), 201)
    # 517500 + 415225 + 69954 = 1,002,679
    assert q["total_cents"] == 1002679, q["total_cents"]


# ─────────────────────────────────────────────────────────────────────────
# Rule 1: dual_variant_calc
# ─────────────────────────────────────────────────────────────────────────

def test_estimate_quote_base_and_total_at_design_time(api):
    """PRD §3.2: "A per-square-foot rate in cents is selected by `structure_type` — 4,500
    cents for `SCREEN_ROOM`, 9,000 cents for `THREE_SEASON`, and 16,000 cents for
    `FOUR_SEASON`."
    PRD §3.2: "The estimate is the provisional price the homeowner accepts at design time."

    Design: Difficulty/dual_variant_calc/quote_estimate_vs_final_diverge_on_remeasure
    """
    # THREE_SEASON/ALUMINUM, 120x144 -> footprint 120.00, existing_slab true, low load.
    ho, pj, m, q = setup_quoted_project(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 120, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    # base = 120.00 * 9000 * 1000 / 1000 = 1,080,000; addons 0; tax = round(1080000*75/1000)=81000
    assert q["variant"] == "ESTIMATE"
    assert q["base_price_cents"] == 1080000, q["base_price_cents"]
    assert q["total_cents"] == 1161000, q["total_cents"]


def test_manufacture_start_issues_final_variant_quote(api):
    """PRD §3.5: "When the `Manufacturer` starts production, the order moves
    `QUEUED → IN_PRODUCTION`, and the system performs the dual-variant reconciliation: it
    creates a new `FINAL`-variant `Quote` with `revision_no` one greater than the current
    highest, priced by the same base/add-ons/tax/total rules but recomputed against the
    currently accepted measurement, then supersedes the prior `ACCEPTED` quote and repoints
    `accepted_quote_id` to this final quote."

    Design: Difficulty/dual_variant_calc/quote_estimate_vs_final_diverge_on_remeasure
    """
    ho, pj, q, mo = setup_in_manufacture(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 120, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    get_success_data(api.start_manufacture_order(mo["id"], MF))
    quotes, _ = _quotes(api, pj["id"])
    final_quotes = [x for x in quotes if x["variant"] == "FINAL"]
    assert len(final_quotes) == 1, quotes
    # Same measurement (no re-measure): FINAL base equals the ESTIMATE base.
    assert final_quotes[0]["base_price_cents"] == 1080000, final_quotes[0]
    # exactly one ACCEPTED quote remains after the FINAL supersede.
    accepted = [x for x in quotes if x["status"] == "ACCEPTED"]
    assert len(accepted) == 1, quotes


def test_final_base_differs_after_remeasure(api):
    """PRD §3.1: "every `ISSUED` quote on the project is set to `SUPERSEDED`, because a
    re-measure invalidates any outstanding estimate."
    PRD §3.2: "The base price is the project's current `footprint_sqft` multiplied by the
    per-square-foot rate, multiplied by the material multiplier, divided by 1,000, with the
    final product rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/quote_final_base_differs_after_remeasure
    """
    # 120x144 designed + ESTIMATE issued (NOT accepted); then re-measure 130x144.
    ho, pj, m1, qold = setup_quoted_project(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 120, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    # re-measure to 130x144 (supersedes the 120 measurement and the outstanding ESTIMATE)
    m2 = get_success_data(api.create_measurement(
        {"project_id": pj["id"], "width_in": 130, "depth_in": 144, "wall_height_in": 96,
         "existing_slab": True}, SD))
    get_success_data(api.accept_measurement(m2["id"], SD))
    get_success_data(api.finalize_design(pj["id"], SD))
    qnew = validate_success(api.create_quote(create_quote_payload(pj["id"]), SD), 201)
    pv = get_success_data(api.get_project(pj["id"], SD))["version"]
    get_success_data(api.accept_quote(qnew["id"], create_quote_accept_payload(pv),
                     make_homeowner_headers(ho["id"])))

    qold_after = get_success_data(api.get_quote(qold["id"], SD))
    assert qold_after["status"] == "SUPERSEDED", qold_after
    # base = 130.00 * 9000 * 1000 / 1000 = 1,170,000; tax = round(1170000*75/1000)=87750
    assert qnew["base_price_cents"] == 1170000, qnew
    assert qnew["total_cents"] == 1257750, qnew
    pj_after = get_success_data(api.get_project(pj["id"], SD))
    assert pj_after["footprint_sqft"] == 130.00, pj_after["footprint_sqft"]
    assert pj_after["accepted_quote_id"] == qnew["id"], pj_after


def test_remeasure_footprint_recomputed_to_130(api):
    """PRD §3.1: "the project's `width_in`, `depth_in`, and `footprint_sqft` are recomputed
    from it"

    Design: Difficulty/dual_variant_calc/quote_final_base_differs_after_remeasure
    """
    ho, pj, m1, qold = setup_quoted_project(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 120, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    m2 = get_success_data(api.create_measurement(
        {"project_id": pj["id"], "width_in": 130, "depth_in": 144, "wall_height_in": 96,
         "existing_slab": True}, SD))
    get_success_data(api.accept_measurement(m2["id"], SD))
    pj_after = get_success_data(api.get_project(pj["id"], SD))
    # 130 * 144 / 144 = 130.00
    assert pj_after["footprint_sqft"] == 130.00, pj_after["footprint_sqft"]
    assert pj_after["width_in"] == 130, pj_after["width_in"]


def test_lead_time_promised_vs_actual_diverge(api):
    """PRD §3.5: "The `promised_ready_at` is the logical clock at order time plus that many
    lead-time days — the planning estimate stamped when the order is created."
    PRD §3.5: "Marking the order `READY` requires it to be `IN_PRODUCTION` and records
    `ready_at` as the logical clock at that moment — the realized completion instant, which
    can diverge from `promised_ready_at` if the logical clock advanced by more or fewer days
    than the planned lead time."

    Design: Difficulty/dual_variant_calc/lead_time_promised_vs_actual_diverge
    """
    from test_helpers import set_clock
    set_clock("2026-05-01T00:00:00Z")
    # FOUR_SEASON/THERMAL_BREAK_ALUMINUM, 180x160 -> footprint 200.00.
    # lead = 35 (TBA) + 0 (200.00 not > 200) + 10 (FOUR_SEASON) = 45 days.
    ho, pj, q, mo = setup_in_manufacture(
        homeowner_overrides={"ground_snow_load_psf": 40, "design_wind_speed_mph": 140},
        project_overrides={"structure_type": "FOUR_SEASON",
                           "material": "THERMAL_BREAK_ALUMINUM"},
        measurement_overrides={"width_in": 180, "depth_in": 160, "wall_height_in": 108,
                               "existing_slab": False},
        with_engineering=True,
        engineering_overrides={"rated_wind_mph": 150, "rated_snow_psf": 45},
    )
    assert mo["lead_time_days"] == 45, mo["lead_time_days"]
    assert mo["promised_ready_at"] == "2026-06-15T00:00:00.000Z", mo["promised_ready_at"]
    get_success_data(api.start_manufacture_order(mo["id"], MF))
    set_clock("2026-05-11T00:00:00Z")
    ready = get_success_data(api.ready_manufacture_order(mo["id"], MF))
    assert ready["ready_at"] == "2026-05-11T00:00:00.000Z", ready["ready_at"]
    assert ready["promised_ready_at"] == "2026-06-15T00:00:00.000Z", ready["promised_ready_at"]


def test_lead_time_value_for_four_season_thermal_break(api):
    """PRD §3.5: "The lead time begins at a material base — 21 days for `ALUMINUM`, 28 days
    for `VINYL`, and 35 days for `THERMAL_BREAK_ALUMINUM`."
    PRD §3.5: "If the `structure_type` is `FOUR_SEASON`, a further 10 days are added."

    Design: Difficulty/dual_variant_calc/lead_time_promised_vs_actual_diverge
    """
    from test_helpers import set_clock
    set_clock("2026-05-01T00:00:00Z")
    ho, pj, q, mo = setup_in_manufacture(
        homeowner_overrides={"ground_snow_load_psf": 40, "design_wind_speed_mph": 140},
        project_overrides={"structure_type": "FOUR_SEASON",
                           "material": "THERMAL_BREAK_ALUMINUM"},
        measurement_overrides={"width_in": 180, "depth_in": 160, "wall_height_in": 108,
                               "existing_slab": False},
        with_engineering=True,
        engineering_overrides={"rated_wind_mph": 150, "rated_snow_psf": 45},
    )
    # 35 (TBA base) + 10 (FOUR_SEASON) = 45; footprint 200.00 is NOT > 200 so no surcharge.
    assert mo["lead_time_days"] == 45, mo["lead_time_days"]


# ─────────────────────────────────────────────────────────────────────────
# Rule 6: boundary_precision_check (financing)
# ─────────────────────────────────────────────────────────────────────────

def test_financing_apr_tier_credit_score_700_boundary(api):
    """PRD §3.3: "The cutoffs are inclusive at the bottom of each tier — a 700 score earns
    the 999-basis-point rate, not 1,499, and a 650 score is approvable at 1,499 basis points,
    whereas a 649 score is declined."

    Design: Difficulty/boundary_precision_check/financing_apr_tier_credit_score_700_boundary
    """
    # SCREEN_ROOM/ALUMINUM, 60x144 -> footprint 60.00, existing_slab true.
    # base = 60.00*4500*1000/1000 = 270000; tax = round(270000*75/1000)=20250; total=290250.
    ho, pj, m, q = setup_permitting_project(
        project_overrides={"structure_type": "SCREEN_ROOM", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 60, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    assert q["total_cents"] == 290250, q["total_cents"]
    fa = get_success_data(api.create_financing_application(
        create_financing_payload(pj["id"], q["id"], down_payment_cents=0, term_months=12,
                                 credit_score=700), make_homeowner_headers(ho["id"])))
    decided = validate_success(api.decide_financing_application(fa["id"], SD), 200)
    assert decided["status"] == "APPROVED", decided
    assert decided["apr_bps"] == 999, decided["apr_bps"]


def test_financing_monthly_payment_amortized(api):
    """PRD §3.3: "the monthly rate is `apr_bps` divided by 10,000 (converting basis points
    to a fraction) and then divided by 12; the term in months is `term_months`."
    PRD §3.3: "Otherwise the payment is the principal multiplied by the amortization factor —
    the monthly rate times one plus the monthly rate raised to the power of the number of
    months, all divided by the quantity one plus the monthly rate raised to the power of the
    number of months minus one — with the result rounded half up to whole cents in a single
    final step."

    Design: Difficulty/boundary_precision_check/financing_apr_tier_credit_score_700_boundary
    """
    ho, pj, m, q = setup_permitting_project(
        project_overrides={"structure_type": "SCREEN_ROOM", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 60, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    fa = get_success_data(api.create_financing_application(
        create_financing_payload(pj["id"], q["id"], down_payment_cents=0, term_months=12,
                                 credit_score=700), make_homeowner_headers(ho["id"])))
    decided = validate_success(api.decide_financing_application(fa["id"], SD), 200)
    # principal 290250, apr 999 bps over 12 months -> amortized 25516 cents.
    assert decided["amount_financed_cents"] == 290250, decided["amount_financed_cents"]
    assert decided["monthly_payment_cents"] == 25516, decided["monthly_payment_cents"]


def _quotes(api, project_id):
    resp = api.list_project_quotes(project_id, SD)
    body = resp.json()
    return body.get("data", []), body.get("meta", {})
