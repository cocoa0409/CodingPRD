"""Permit fee calculation: dual variant (NEW vs RENEWAL_EARLY), per-component
rounding, and the renewal window (Difficulty: dual_variant_calc,
combinatorial_formula; Corner: calculations)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, make_vendor_headers,
    FEE_NEW_STANDARD_MEDIUM, FEE_RENEWAL_EARLY_STANDARD_MEDIUM,
    FEE_RENEWAL_LATE_STANDARD_MEDIUM,
)
from test_helpers import fixtures as fx

PO = TEST_USERS["permit_officer_headers"]


# --------------------------------------------------------------------------- #
# dual_variant_calc / permit_fee_new_vs_renewal_early
# --------------------------------------------------------------------------- #
def test_new_issuance_fee_standard_medium(api):
    """PRD §3.4: "The base component is 20,000 cents for a NEW issuance ... The zone
    component is a surcharge determined by the permit's zone type: 15,000 cents for a
    PRIME zone and 5,000 cents for a STANDARD zone. The size component is a tier fee
    determined by the cart's size_sqft: a small cart of 20 square feet or fewer costs
    3,500 cents, a medium cart of 21 through 40 square feet costs 6,500 cents"

    Design: Difficulty/dual_variant_calc/permit_fee_new_vs_renewal_early
    """
    ctx = fx.setup_issued_permit(seniority_years=5)
    permit = ctx["permit"]
    assert permit["fee_variant"] == "NEW"
    assert permit["fee_amount_cents"] == FEE_NEW_STANDARD_MEDIUM  # 34257


def test_early_renewal_discounts_base_component(api):
    """PRD §3.4: "for a RENEWAL_EARLY renewal it is the base fee discounted to 80% —
    that is, 20,000 multiplied by 0.80 and rounded half up, giving 16,000 cents."
    PRD §3.4: "When the clock is strictly before expires_at, the renewal is
    RENEWAL_EARLY."

    Design: Difficulty/dual_variant_calc/permit_fee_new_vs_renewal_early
    """
    ctx = fx.setup_issued_permit(seniority_years=5)
    permit, vendor = ctx["permit"], ctx["vendor"]
    renewed = validate_success(
        api.renew_permit(permit["id"], make_vendor_headers(vendor["id"])), 200)
    assert renewed["fee_variant"] == "RENEWAL_EARLY"
    assert renewed["fee_amount_cents"] == FEE_RENEWAL_EARLY_STANDARD_MEDIUM  # 29907
    assert FEE_RENEWAL_EARLY_STANDARD_MEDIUM != FEE_NEW_STANDARD_MEDIUM


# --------------------------------------------------------------------------- #
# combinatorial_formula / permit_fee_round_per_component_then_sum
# --------------------------------------------------------------------------- #
def test_fee_rounds_tax_per_component(api):
    """PRD §2.5: "Where a fee is assembled from several components each carrying tax,
    the tax on each component is rounded half up independently and only then are the
    components and their taxes summed — the system never sums first and rounds once."
    PRD §3.4: "the tax is computed as the base component times 0.0875 rounded half up,
    plus the zone component times 0.0875 rounded half up, plus the size component
    times 0.0875 rounded half up — each rounding performed before the three tax
    figures are summed."

    Design: Difficulty/combinatorial_formula/permit_fee_round_per_component_then_sum
    """
    ctx = fx.setup_issued_permit()
    # per-component tax: round(1750)+round(437.5=>438)+round(568.75=>569)=2757
    # fee = 20000+5000+6500+2757 = 34257 (sum-then-round would give 34256)
    assert ctx["permit"]["fee_amount_cents"] == 34_257


def test_fee_distinct_from_sum_then_round(api):
    """PRD §2.5: "the tax on each component is rounded half up independently and only
    then are the components and their taxes summed — the system never sums first and
    rounds once."

    Design: Difficulty/combinatorial_formula/permit_fee_round_per_component_then_sum
    """
    ctx = fx.setup_issued_permit()
    fee = ctx["permit"]["fee_amount_cents"]
    assert fee == 34_257
    assert fee != 34_256  # the sum-then-round result


# --------------------------------------------------------------------------- #
# Corner calculations: renewal_late_adds_penalty
# --------------------------------------------------------------------------- #
def test_late_renewal_within_grace_adds_penalty(api):
    """PRD §3.4: "When the clock is at or after expires_at but strictly before
    expires_at plus the 30-day grace period, the renewal is RENEWAL_LATE."
    PRD §3.4: "For a RENEWAL_LATE renewal only, a late penalty of 7,500 cents is
    added after the tax has been included."

    Design: Corner/calculations/renewal_late_adds_penalty
    """
    ctx = fx.setup_issued_permit(insurance_overrides={
        "insurance_expires_at": "2028-05-01T00:00:00Z"})
    permit, vendor = ctx["permit"], ctx["vendor"]
    # issued 2026-06-01 -> expires 2027-06-01; advance into the grace window.
    fx.set_clock("2027-06-10T00:00:00Z")
    renewed = validate_success(
        api.renew_permit(permit["id"], make_vendor_headers(vendor["id"])), 200)
    assert renewed["fee_variant"] == "RENEWAL_LATE"
    assert renewed["fee_amount_cents"] == FEE_RENEWAL_LATE_STANDARD_MEDIUM  # 41757


# --------------------------------------------------------------------------- #
# Corner calculations: renewal_after_grace_closed
# --------------------------------------------------------------------------- #
def test_renewal_after_grace_window_closed(api):
    """PRD §3.4: "When the clock has reached or passed expires_at plus 30 days, the
    renewal window has closed and the request is rejected with
    ERR_RENEWAL_WINDOW_CLOSED."

    Design: Corner/calculations/renewal_after_grace_closed
    """
    ctx = fx.setup_issued_permit(insurance_overrides={
        "insurance_expires_at": "2028-05-01T00:00:00Z"})
    permit, vendor = ctx["permit"], ctx["vendor"]
    # expires 2027-06-01 + 30 days = 2027-07-01; 2027-07-05 is past grace.
    fx.set_clock("2027-07-05T00:00:00Z")
    res = api.renew_permit(permit["id"], make_vendor_headers(vendor["id"]))
    validate_error(res, "ERR_RENEWAL_WINDOW_CLOSED", expected_status=422)
