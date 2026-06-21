"""Refund depreciation: straight-line vs declining-balance, the msrp/purchase
baseline clamp, the remaining-coverage cap, and depreciation boundaries
(PRD §3.7, §3.8)."""
from test_helpers import set_clock, validate_success
from test_helpers import fixtures as F


# ─── Difficulty: dual_variant_calc (straight-line vs declining-balance) ──────
def test_refund_straight_line_value_at_elapsed_12(api):
    """PRD §3.8: "the system computes a remaining-life fraction equal to the larger
    of zero and (lifespan minus elapsed months), divided by the lifespan; the raw
    payout is the baseline multiplied by that fraction."
    PRD §3.8: "the baseline is the lesser of the registration's purchase price and
    the product's MSRP".

    Design: Difficulty/dual_variant_calc/refund_proration_straight_line_vs_declining_balance
    """
    # base 50000, elapsed 12, L 48 -> 50000 * (48-12)/48 = 37500.
    s = F.setup_adjudicated_refund_claim(
        ext_kwargs={
            "ext_depreciation": "STRAIGHT_LINE", "ext_cap_cents": 40000,
            "ext_refund_eligible": True, "purchase_price_cents": 50000,
        },
        reported_date="2025-01-15T00:00:00Z",
        adjudicate_clock="2025-01-15T00:00:00Z",
    )
    assert s["claim"]["assessed_value_cents"] == 37500


def test_refund_declining_balance_value_at_elapsed_12(api):
    """PRD §3.8: "the raw payout is the baseline multiplied by a monthly decay rate
    of 0.97 raised to the power of the elapsed months. This geometric decay never
    reaches zero and stays strictly positive for the same inputs, so for identical
    purchase facts the declining-balance payout diverges from the straight-line
    one."

    Design: Difficulty/dual_variant_calc/refund_proration_straight_line_vs_declining_balance
    """
    # base 50000, elapsed 12: 50000 * 0.97**12 = 34692 (round_half_up); cap 40000 not binding.
    s = F.setup_adjudicated_refund_claim(
        ext_kwargs={
            "ext_depreciation": "DECLINING_BALANCE", "ext_cap_cents": 40000,
            "ext_refund_eligible": True, "purchase_price_cents": 50000,
        },
        reported_date="2025-01-15T00:00:00Z",
        adjudicate_clock="2025-01-15T00:00:00Z",
    )
    assert s["claim"]["assessed_value_cents"] == 34692


# ─── Difficulty: combinatorial_formula (assessed capped by pre-debit remaining)
def test_assessed_capped_by_pre_debit_remaining_coverage(api):
    """PRD §3.8: "the assessed value is the smaller of the rounded raw payout and
    the registration's remaining-coverage value read from the pre-adjudication
    ledger."
    PRD §3.8: "read remaining coverage from the ledger as it stands before this
    adjudication, compute the assessed value as the minimum of the rounded raw
    payout and that pre-adjudication remaining-coverage value, write the debit
    ledger entry for the assessed amount".

    Design: Difficulty/combinatorial_formula/adjudication_assessed_capped_by_pre_debit_remaining_coverage
    """
    # straight-line raw 37500, cap 30000 binds -> assessed 30000, remaining 0.
    s = F.setup_adjudicated_refund_claim(
        ext_kwargs={
            "ext_depreciation": "STRAIGHT_LINE", "ext_cap_cents": 30000,
            "ext_refund_eligible": True, "purchase_price_cents": 50000,
        },
        reported_date="2025-01-15T00:00:00Z",
        adjudicate_clock="2025-01-15T00:00:00Z",
    )
    assert s["claim"]["assessed_value_cents"] == 30000
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["remaining_coverage_cents"] == 0


def test_assessed_below_cap_leaves_remaining_positive(api):
    """PRD §3.8: "the assessed value is the smaller of the rounded raw payout and
    the registration's remaining-coverage value read from the pre-adjudication
    ledger."
    PRD §3.7: "then decrements the registration's `remaining_coverage_cents` by
    that assessed value through ledger reconciliation."

    Design: Difficulty/combinatorial_formula/adjudication_assessed_capped_by_pre_debit_remaining_coverage
    """
    # straight-line raw 37500 < cap 40000 -> assessed 37500, remaining 2500.
    s = F.setup_adjudicated_refund_claim(
        ext_kwargs={
            "ext_depreciation": "STRAIGHT_LINE", "ext_cap_cents": 40000,
            "ext_refund_eligible": True, "purchase_price_cents": 50000,
        },
        reported_date="2025-01-15T00:00:00Z",
        adjudicate_clock="2025-01-15T00:00:00Z",
    )
    assert s["claim"]["assessed_value_cents"] == 37500
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["remaining_coverage_cents"] == 2500


# ─── Difficulty: boundary_precision_check ────────────────────────────────────
def test_straight_line_refund_zero_at_end_of_serviceable_life(api):
    """PRD §3.8: "the system computes a remaining-life fraction equal to the larger
    of zero and (lifespan minus elapsed months), divided by the lifespan ... This
    decays linearly and reaches zero at the end of the serviceable life."

    Design: Difficulty/boundary_precision_check/straight_line_refund_zero_at_end_of_serviceable_life
    """
    # serviceable_lifespan 12, elapsed exactly 12 -> fraction 0 -> assessed 0.
    s = F.setup_active_registration(
        base_cap_cents=40000, base_refund_eligible=True,
        product_overrides={"base_warranty_months": 24, "serviceable_lifespan_months": 12},
        purchase_price_cents=50000,
    )
    claim = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2025-01-15T00:00:00Z")
    F.issue_rma(claim["id"])
    set_clock("2025-01-15T00:00:00Z")
    adjudicated = F.adjudicate_approve(claim["id"], "REFUND")
    assert adjudicated["assessed_value_cents"] == 0
    assert adjudicated["status"] == "ADJUDICATED"


def test_straight_line_refund_positive_one_month_before_end_of_life(api):
    """PRD §3.8: "the system computes a remaining-life fraction equal to the larger
    of zero and (lifespan minus elapsed months), divided by the lifespan; the raw
    payout is the baseline multiplied by that fraction."
    PRD §2.6: "the raw value is computed in cents and then rounded to a whole cent
    using the round-half-up convention."

    Design: Difficulty/boundary_precision_check/straight_line_refund_zero_at_end_of_serviceable_life
    """
    # lifespan 12, elapsed 11 -> fraction 1/12; base 50000 -> 4166.67 -> round_half_up 4167.
    s = F.setup_active_registration(
        base_cap_cents=40000, base_refund_eligible=True,
        product_overrides={"base_warranty_months": 24, "serviceable_lifespan_months": 12},
        purchase_price_cents=50000,
    )
    claim = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2024-12-15T00:00:00Z")
    F.issue_rma(claim["id"])
    set_clock("2024-12-15T00:00:00Z")
    adjudicated = F.adjudicate_approve(claim["id"], "REFUND")
    assert adjudicated["assessed_value_cents"] == 4167
    assert adjudicated["status"] == "ADJUDICATED"


def test_claim_reported_date_exactly_on_warranty_end_is_in_window(api):
    """PRD §3.6: "the claim's reported date is on or before the registration's
    `warranty_end_date`; a reported date past the warranty end (or a registration
    no longer eligible) is rejected with `ERR_WARRANTY_EXPIRED`."

    Design: Difficulty/boundary_precision_check/claim_reported_date_exactly_on_warranty_end_is_in_window
    """
    # base_warranty 12 from 2024-01-15 -> warranty_end 2025-01-15; reported exactly then.
    s = F.setup_active_registration(
        base_cap_cents=20000, product_overrides={"base_warranty_months": 12},
        purchase_price_cents=50000,
    )
    set_clock("2025-01-15T00:00:00Z")
    claim = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2025-01-15T00:00:00Z")
    issued = F.issue_rma(claim["id"])
    assert issued["status"] == "RMA_ISSUED"
    assert issued["rma_number"] is not None


def test_claim_reported_date_one_day_past_warranty_end_is_expired(api):
    """PRD §3.6: "the claim's reported date is on or before the registration's
    `warranty_end_date`; a reported date past the warranty end (or a registration
    no longer eligible) is rejected with `ERR_WARRANTY_EXPIRED`."

    Design: Difficulty/boundary_precision_check/claim_reported_date_exactly_on_warranty_end_is_in_window
    """
    from test_helpers import validate_error
    # warranty_end 2025-01-15; a claim reported 2025-01-16 is one day past -> expired.
    s = F.setup_active_registration(
        base_cap_cents=20000, product_overrides={"base_warranty_months": 12},
        purchase_price_cents=50000,
    )
    set_clock("2025-01-16T00:00:00Z")
    resp = api.create_claim(
        {"registration_id": s["registration"]["id"], "defect_category": "MANUFACTURING", "reported_date": "2025-01-16T00:00:00Z"},
        F.make_owner_headers(s["owner"]["id"]),
    )
    validate_error(resp, "ERR_WARRANTY_EXPIRED")


# ─── Corner: calculations (straight-line midlife, msrp clamp) ────────────────
def test_refund_straight_line_midlife_value(api):
    """PRD §3.8: "the raw payout is the baseline multiplied by that fraction."
    PRD §3.8: "The elapsed age is the number of whole months from the
    registration's purchase date to the claim's reported date, taking the floor".

    Design: Corner/calculations/refund_proration_straight_line_correct_midlife_value
    """
    # base 50000, elapsed 6, L 48 -> 50000*(48-6)/48 = 43750, cap 50000 not binding.
    s = F.setup_adjudicated_refund_claim(
        ext_kwargs={
            "ext_depreciation": "STRAIGHT_LINE", "ext_cap_cents": 50000,
            "ext_refund_eligible": True, "purchase_price_cents": 50000,
            "base_cap_cents": 10000,
        },
        reported_date="2024-07-15T00:00:00Z",
        adjudicate_clock="2024-07-15T00:00:00Z",
    )
    assert s["claim"]["assessed_value_cents"] == 43750
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["remaining_coverage_cents"] == 6250


def test_refund_baseline_clamped_to_msrp_when_purchase_exceeds(api):
    """PRD §3.8: "In both variants the baseline is the lesser of the registration's
    purchase price and the product's MSRP — that is, the smaller of
    `purchase_price_cents` and `msrp_cents`."

    Design: Corner/calculations/refund_proration_base_is_min_of_purchase_price_and_msrp
    """
    # purchase 60000 > msrp 40000 -> base 40000; elapsed 0 -> assessed 40000.
    s = F.setup_adjudicated_refund_claim(
        ext_kwargs={
            "ext_depreciation": "STRAIGHT_LINE", "ext_cap_cents": 50000,
            "ext_refund_eligible": True, "purchase_price_cents": 60000,
            "base_cap_cents": 10000,
            "product_overrides": {"msrp_cents": 40000},
        },
        reported_date="2024-01-15T00:00:00Z",
        adjudicate_clock="2024-01-15T00:00:00Z",
    )
    assert s["claim"]["assessed_value_cents"] == 40000


# ─── Corner: consistency_model (immediate assessed value in response) ────────
def test_adjudicate_response_reflects_assessed_value_immediately(api):
    """PRD §2.9: "All such cascades complete atomically within the request that
    triggers them; there is no deferred or background settlement."
    PRD §3.7: "the system sets the claim's `resolution_type` to the admin-chosen
    branch and computes the claim's `assessed_value_cents`."

    Design: Corner/consistency_model/adjudicate_response_reflects_assessed_value_in_same_request
    """
    s = F.setup_active_registration_with_extension(
        ext_depreciation="STRAIGHT_LINE", ext_cap_cents=40000, ext_refund_eligible=True,
        purchase_price_cents=50000,
    )
    claim = F.file_claim(s["registration"]["id"], s["owner"]["id"], reported_date="2025-01-15T00:00:00Z")
    F.issue_rma(claim["id"])
    set_clock("2025-01-15T00:00:00Z")
    resp = api.adjudicate_claim(claim["id"], {"decision": "approve", "resolution_type": "REFUND"}, F.ADMIN)
    data = validate_success(resp)
    assert data["assessed_value_cents"] == 37500
    assert data["status"] == "ADJUDICATED"
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["remaining_coverage_cents"] == 2500
