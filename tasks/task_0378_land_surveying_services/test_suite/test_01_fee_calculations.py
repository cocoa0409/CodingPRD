"""Fee estimation and final billing: the tiered per-acre field fee, the rush
surcharge, the round-after-sum rounding order, applied-reseal divergence between
the estimate and the final invoice, and the crew scheduling-risk score.

Difficulty queue: dual_variant_calc, combinatorial_formula.
Corner queue: entities (defaults / computed-fee creation).
"""
from test_helpers import (
    fixtures as fx,
    make_coordinator_headers,
    create_survey_order_payload,
    validate_success,
)


# ════════════════════════════════════════════════════════════════════════
# Difficulty/dual_variant_calc/order_estimate_vs_invoice_final_fee_diverge
# ════════════════════════════════════════════════════════════════════════
def test_invoice_final_fee_adds_reseal_and_tax_diverging_from_estimate(api):
    """PRD §3.7: "The invoice `subtotal_cents` is the base plus the field fee plus
    the rush surcharge plus that applied-reseal total. Tax is then computed as 8.25
    percent of the subtotal, rounded half-up to a whole cent, and stored as
    `tax_cents`."
    PRD §3.5: "The revision's `reseal_fee_cents` is added to the order's
    `estimated_fee_cents`, and the order's `revision_count` is incremented by one."

    BOUNDARY 3ac no-rush: base 120000 + field 24000 = estimate 144000. A CLIENT_CHANGE
    reseal (40000) applied to the sealed plat raises estimate to 184000; the issued
    invoice subtotal is 184000, tax round_half_up(184000*0.0825)=15180, total 199180,
    written back as the order's final_fee_cents.

    Design: Difficulty/dual_variant_calc/order_estimate_vs_invoice_final_fee_diverge
    """
    ctx = fx.sealed_plat(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]

    # Apply a CLIENT_CHANGE revision to the SEALED plat (un-seals, +40000 to estimate),
    # then re-seal so the order is SEALED again and an invoice can be issued.
    fx.apply_client_change_revision(ctx)
    fx.reseal_after_revision(ctx)

    order = validate_success(
        api.get_survey_order(ctx["order_id"], make_coordinator_headers(crew["coord"]["id"])), 200)
    assert order["estimated_fee_cents"] == 184000, (
        f"estimate should include applied reseal, got {order['estimated_fee_cents']}")
    assert order["revision_count"] == 1

    # Issue the invoice on this already-resealed order.
    bid = crew["billing"]["id"]
    from test_helpers import (
        create_invoice_payload, issue_invoice_payload, make_billing_clerk_headers,
    )
    invoice = validate_success(
        api.create_invoice(create_invoice_payload(ctx["order_id"], bid),
                           make_billing_clerk_headers(bid)), 201)
    ov = validate_success(
        api.get_survey_order(ctx["order_id"], make_coordinator_headers(crew["coord"]["id"])), 200)["version"]
    issued = validate_success(
        api.issue_invoice(invoice["id"], issue_invoice_payload(ov),
                          make_billing_clerk_headers(bid)), 200)

    assert issued["subtotal_cents"] == 184000
    assert issued["tax_cents"] == 15180
    assert issued["total_cents"] == 199180

    final_order = validate_success(
        api.get_survey_order(ctx["order_id"], make_coordinator_headers(crew["coord"]["id"])), 200)
    assert final_order["final_fee_cents"] == 199180
    assert final_order["final_fee_cents"] != final_order["estimated_fee_cents"]


def test_order_estimate_excludes_reseal_and_tax_at_creation(api):
    """PRD §3.7: "This estimate uses only order-creation inputs — `survey_type`,
    `acreage`, and the `rush` flag — and deliberately ignores any revisions, which
    do not yet exist."

    A fresh BOUNDARY 3ac no-rush order: base 120000 + field 24000 = estimated 144000,
    with no tax and no reseal folded in (those live only on the final invoice).

    Design: Difficulty/dual_variant_calc/order_estimate_vs_invoice_final_fee_diverge
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    order = validate_success(
        api.create_survey_order(
            create_survey_order_payload(survey_type="BOUNDARY", acreage=3, rush=False),
            make_coordinator_headers(cid)), 201)
    assert order["base_fee_cents"] == 120000
    assert order["estimated_fee_cents"] == 144000
    assert order["final_fee_cents"] == 0


# ════════════════════════════════════════════════════════════════════════
# Difficulty/dual_variant_calc/crew_risk_score_vs_order_fee_distinct_domains
# ════════════════════════════════════════════════════════════════════════
def test_crew_risk_score_blends_load_factor(api):
    """PRD §3.8: "The two factors are then blended with a sixty-percent weight on
    the load factor and a forty-percent weight on the license factor; that weighted
    blend is multiplied by one hundred and rounded half-up to produce the final
    integer risk score in the range 0 to 100."

    A TECH with exactly 3 SCHEDULED assignments: load_factor 3/5=0.6, no license
    warning -> raw 0.6*0.6 = 0.36 -> risk_score 36.

    Design: Difficulty/dual_variant_calc/crew_risk_score_vs_order_fee_distinct_domains
    """
    ctx = fx.crew_with_scheduled_assignments(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    tid = ctx["tech_id"]

    tech = validate_success(api.get_crew_member(tid, make_coordinator_headers(cid)), 200)
    assert tech["open_assignment_count"] == 3

    risk = validate_success(api.get_crew_member_risk_score(tid, make_coordinator_headers(cid)), 200)
    assert risk["risk_score"] == 36, f"expected risk_score 36, got {risk.get('risk_score')}"


def test_order_estimate_distinct_from_risk_domain(api):
    """PRD §3.7: "The order's `estimated_fee_cents` is then the base fee plus the
    field fee plus the rush surcharge."

    The fee domain (SurveyOrder estimated_fee_cents) is a different subject than the
    risk domain (CrewMember): a BOUNDARY 3ac no-rush order estimates 144000.

    Design: Difficulty/dual_variant_calc/crew_risk_score_vs_order_fee_distinct_domains
    """
    ctx = fx.crew_with_scheduled_assignments(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    order = validate_success(
        api.get_survey_order(ctx["order_id"], make_coordinator_headers(crew["coord"]["id"])), 200)
    assert order["estimated_fee_cents"] == 144000


# ════════════════════════════════════════════════════════════════════════
# Difficulty/combinatorial_formula/tiered_acre_field_fee_mode_a_nonlinear
# ════════════════════════════════════════════════════════════════════════
def test_tiered_acre_field_fee_nonlinear_bands(api):
    """PRD §3.7: "The first five acres are billed at 8000 cents per acre; the next
    fifteen acres — that is, acreage above five and up to twenty — are billed at 5000
    cents per acre; and every acre beyond twenty is billed at 3000 cents per acre."

    TOPO base 180000; 25 acres -> 5*8000 + 15*5000 + 5*3000 = 130000 field fee;
    no rush -> estimate 310000.

    Design: Difficulty/combinatorial_formula/tiered_acre_field_fee_mode_a_nonlinear
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    order = validate_success(
        api.create_survey_order(
            create_survey_order_payload(survey_type="TOPO", acreage=25, rush=False),
            make_coordinator_headers(cid)), 201)
    assert order["base_fee_cents"] == 180000
    assert order["estimated_fee_cents"] == 310000


def test_field_fee_first_band_only_small_parcel(api):
    """PRD §3.7: "The first five acres are billed at 8000 cents per acre."

    A BOUNDARY order of exactly 3 acres reaches only the first band: field fee
    3*8000 = 24000; base 120000; no rush -> estimate 144000.

    Design: Difficulty/combinatorial_formula/tiered_acre_field_fee_mode_a_nonlinear
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    order = validate_success(
        api.create_survey_order(
            create_survey_order_payload(survey_type="BOUNDARY", acreage=3, rush=False),
            make_coordinator_headers(cid)), 201)
    assert order["base_fee_cents"] == 120000
    assert order["estimated_fee_cents"] == 144000


# ════════════════════════════════════════════════════════════════════════
# Difficulty/combinatorial_formula/invoice_rounding_order_mode_b
# ════════════════════════════════════════════════════════════════════════
def test_invoice_rounding_order_round_after_sum(api):
    """PRD §3.7: "The rush surcharge is computed the same way as in the estimate —
    thirty percent of base-plus-field, rounded half-up, charged only when the
    order's `rush` flag is true, and zero otherwise."
    PRD §3.7: "Tax is then computed as 8.25 percent of the subtotal, rounded
    half-up to a whole cent, and stored as `tax_cents`."

    ALTA 10ac rush: base 350000, field 65000, rush round_half_up(415000*0.30)=124500,
    subtotal 539500, tax round_half_up(539500*0.0825)=44509, total 539500+44509=584009.

    Design: Difficulty/combinatorial_formula/invoice_rounding_order_mode_b
    """
    ctx = fx.draft_invoice_on_sealed_order(survey_type="ALTA", acreage=10, rush=True)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    bid = crew["billing"]["id"]
    from test_helpers import issue_invoice_payload, make_billing_clerk_headers

    order = validate_success(api.get_survey_order(ctx["order_id"], make_coordinator_headers(cid)), 200)
    assert order["estimated_fee_cents"] == 539500

    ov = order["version"]
    issued = validate_success(
        api.issue_invoice(ctx["invoice_id"], issue_invoice_payload(ov),
                          make_billing_clerk_headers(bid)), 200)
    assert issued["subtotal_cents"] == 539500
    assert issued["tax_cents"] == 44509
    assert issued["total_cents"] == 584009


def test_alta_rush_estimate_at_creation(api):
    """PRD §3.7: "take the base fee plus the field fee, multiply that sum by thirty
    percent, and round the single product half-up to a whole cent; when `rush` is
    false the rush surcharge is zero."

    ALTA 10ac rush=true at creation: base 350000 + field 65000 + rush 124500 = 539500.

    Design: Difficulty/combinatorial_formula/invoice_rounding_order_mode_b
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    order = validate_success(
        api.create_survey_order(
            create_survey_order_payload(survey_type="ALTA", acreage=10, rush=True),
            make_coordinator_headers(cid)), 201)
    assert order["base_fee_cents"] == 350000
    assert order["estimated_fee_cents"] == 539500


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/rush_defaults_false_when_omitted
# ════════════════════════════════════════════════════════════════════════
def test_rush_defaults_false_no_surcharge(api):
    """PRD §3.1: "an optional `rush` flag defaulting to false."
    PRD §3.7: "when `rush` is false the rush surcharge is zero."

    Omitting rush on an ELEVATION 4ac order: rush defaults false, estimate is
    base 90000 + field 32000 = 122000 with no 30% surcharge.

    Design: Corner/entities/rush_defaults_false_when_omitted
    """
    crew = fx.full_crew()
    cid = crew["coord"]["id"]
    payload = create_survey_order_payload(survey_type="ELEVATION", acreage=4)
    payload.pop("rush", None)
    order = validate_success(api.create_survey_order(payload, make_coordinator_headers(cid)), 201)
    assert order["rush"] is False
    assert order["estimated_fee_cents"] == 122000
