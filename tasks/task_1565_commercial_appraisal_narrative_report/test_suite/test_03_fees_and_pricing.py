"""Fee quoting: TIERED vs PER_SF variants, multifactor TIERED composition,
expedited and size-surcharge boundaries, and the pinned volume-discount
evaluation order (PRD §3.1, §3.2, §3.8)."""
from test_helpers import (
    TEST_USERS,
    add_approach,
    add_data_submission,
    add_support_comparables,
    api_client,
    create_draft_report,
    create_in_progress_engagement,
    create_parties,
    create_submitted_engagement,
    validate_success,
)

EM = TEST_USERS["engagement_manager_headers"]

# Canonical TIERED STANDARD quote inputs: 30,000 sf (no size surcharge),
# N planned approaches, and the expedited band edge days.
STD_TIERED_BASE = dict(property_type="OFFICE", building_sf=30000,
                       intended_use="FINANCING")


def _quote(parties, **overrides) -> int:
    """Create + submit an engagement; return its quoted_fee_cents."""
    eng = create_submitted_engagement(parties, **overrides)
    return eng["quoted_fee_cents"]


def test_fee_tiered_variant_quote(api):
    """PRD §3.2: "Under the `TIERED` schedule, the subtotal starts from a
    tier base — 250,000 cents for `LOW`, 450,000 cents for `STANDARD`, or
    900,000 cents for `HIGH`." With "An approach add-on of 75,000 cents
    applies for every planned approach beyond the first" and, because
    twenty days is strictly less than the STANDARD expedited threshold,
    "the sum of base, surcharge, and add-on is multiplied by 1.25":
    (450,000 + 75,000) * 1.25 = 656,250.

    Design: Difficulty/dual_variant_calc/fee_tiered_vs_per_sf_diverge
    """
    parties = create_parties()
    quote = _quote(parties, **STD_TIERED_BASE, requested_turnaround_days=20,
                   planned_approach_count=2, fee_schedule="TIERED")
    assert quote == 656250, f"TIERED expedited quote expected 656250, got {quote}"


def test_fee_per_sf_variant_diverges(api):
    """PRD §3.2: "Under the `PER_SF` schedule, the subtotal is instead the
    tier's per-square-foot rate — twelve cents for `LOW`, eighteen for
    `STANDARD`, thirty for `HIGH` — multiplied by `building_sf`, plus a flat
    expedited supplement of 100,000 cents when the requested turnaround falls
    strictly below the same tier thresholds. The two schedules share inputs
    but price differently by construction." Identical inputs: 18 * 30,000 +
    100,000 = 640,000, diverging from the TIERED 656,250.

    Design: Difficulty/dual_variant_calc/fee_tiered_vs_per_sf_diverge
    """
    parties = create_parties()
    per_sf = _quote(parties, **STD_TIERED_BASE, requested_turnaround_days=20,
                    planned_approach_count=2, fee_schedule="PER_SF")
    tiered = _quote(parties, **STD_TIERED_BASE, requested_turnaround_days=20,
                    planned_approach_count=2, fee_schedule="TIERED")
    assert per_sf == 640000, f"PER_SF expedited quote expected 640000, got {per_sf}"
    assert tiered != per_sf, "the two schedules must price identical inputs differently"


def test_fee_quote_multifactor_tiered(api):
    """PRD §3.2: "The `complexity_tier` is `HIGH` whenever the property is
    `SPECIAL_PURPOSE`, or the intended use is `LITIGATION`, or the building
    is at least 100,000 square feet — a building of exactly 100,000 square
    feet therefore lands in `HIGH`."; "a size surcharge applies: the excess
    over 50,000 square feet is divided into blocks of 10,000 square feet, the
    block count rounds up to a whole block, and each block adds 15,000
    cents"; "An approach add-on of 75,000 cents applies for every planned
    approach beyond the first, so a single-approach engagement pays none.";
    and "If `requested_turnaround_days` is strictly less than the tier's
    expedited threshold — twenty days for `LOW`, thirty for `STANDARD`,
    forty-five for `HIGH` — the sum of base, surcharge, and add-on is
    multiplied by 1.25". SPECIAL_PURPOSE 65,001 sf, 3 planned approaches,
    30-day turnaround: (900,000 + 30,000 + 150,000) * 1.25 = 1,350,000.

    Design: Difficulty/combinatorial_formula/fee_quote_multifactor_mode_a
    """
    parties = create_parties()
    eng = create_submitted_engagement(
        parties, property_address="1 Special Way",
        property_type="SPECIAL_PURPOSE", building_sf=65001,
        intended_use="FINANCING", requested_turnaround_days=30,
        planned_approach_count=3, fee_schedule="TIERED")
    assert eng["complexity_tier"] == "HIGH"
    assert eng["quoted_fee_cents"] == 1350000, (
        f"expected multifactor TIERED quote 1350000, got {eng['quoted_fee_cents']}")


def test_fee_quote_multifactor_ceil_partial_block(api):
    """PRD §3.2: "the block count rounds up to a whole block" — a 65,000 sf
    building carries 15,000 sf of excess, which is 1.5 blocks and therefore
    ceils to the same 2 blocks (30,000 cents) as 65,001 sf, leaving the rest
    of the multifactor quote unchanged at 1,350,000.

    Design: Difficulty/combinatorial_formula/fee_quote_multifactor_mode_a
    """
    parties = create_parties()
    eng = create_submitted_engagement(
        parties, property_address="1 Special Way",
        property_type="SPECIAL_PURPOSE", building_sf=65000,
        intended_use="FINANCING", requested_turnaround_days=30,
        planned_approach_count=3, fee_schedule="TIERED")
    assert eng["complexity_tier"] == "HIGH"
    assert eng["quoted_fee_cents"] == 1350000, (
        f"ceil(1.5 blocks) must round up to 2 surcharge blocks, got {eng['quoted_fee_cents']}")


def test_expedited_threshold_boundary(api):
    """PRD §3.2: "If `requested_turnaround_days` is strictly less than the
    tier's expedited threshold — twenty days for `LOW`, thirty for
    `STANDARD`, forty-five for `HIGH` — the sum of base, surcharge, and
    add-on is multiplied by 1.25". STANDARD with two planned approaches:
    29 days applies the multiplier ((450,000 + 75,000) * 1.25 = 656,250);
    exactly 30 days does not (525,000).

    Design: Corner/calculations/expedited_threshold_boundary
    """
    parties = create_parties()
    q29 = _quote(parties, **STD_TIERED_BASE, requested_turnaround_days=29,
                 planned_approach_count=2, fee_schedule="TIERED")
    q30 = _quote(parties, **STD_TIERED_BASE, requested_turnaround_days=30,
                 planned_approach_count=2, fee_schedule="TIERED")
    assert q29 == 656250, f"29-day turnaround must be expedited, got {q29}"
    assert q30 == 525000, f"30-day turnaround must not be expedited, got {q30}"


def test_size_surcharge_ceil_boundary(api):
    """PRD §3.2: "When `building_sf` exceeds 50,000 square feet, a size
    surcharge applies: the excess over 50,000 square feet is divided into
    blocks of 10,000 square feet, the block count rounds up to a whole block,
    and each block adds 15,000 cents." At exactly 50,000 sf no surcharge
    applies (900,000 for HIGH non-expedited); at 50,001 sf one block applies
    (915,000).

    Design: Corner/calculations/size_surcharge_ceil_boundary
    """
    parties = create_parties()
    q_exact = _quote(parties, property_address="1 Special Way",
                     property_type="SPECIAL_PURPOSE", building_sf=50000,
                     requested_turnaround_days=45, planned_approach_count=1,
                     fee_schedule="TIERED")
    q_over = _quote(parties, property_address="2 Special Way",
                    property_type="SPECIAL_PURPOSE", building_sf=50001,
                    requested_turnaround_days=45, planned_approach_count=1,
                    fee_schedule="TIERED")
    assert q_exact == 900000, f"no surcharge at exactly 50000 sf, got {q_exact}"
    assert q_over == 915000, f"one ceil block at 50001 sf, got {q_over}"


def _deliver_first_engagement_billing_six_million(parties):
    """Deliver a PER_SF HIGH engagement (30 * 200,000 = 6,000,000 cents) so
    the client's lifetime billed total reaches the TIER_1 discount band."""
    bundle = create_in_progress_engagement(
        parties, property_address="9 Tower Rd", property_type="OFFICE",
        building_sf=200000, intended_use="FINANCING",
        requested_turnaround_days=45, planned_approach_count=1,
        fee_schedule="PER_SF")
    add_data_submission(bundle, accept=True)
    add_support_comparables(bundle)
    add_approach(bundle, complete=True, approach_type="INCOME",
                 weight_pct=100.00, cap_rate_bps=700)
    report = create_draft_report(bundle)
    report = validate_success(
        api_client.submit_review(report["id"], bundle["author_headers"]), 200)
    report = validate_success(
        api_client.review_approve(report["id"], bundle["reviewer_headers"]), 200)
    report = validate_success(
        api_client.issue_to_client(report["id"], bundle["author_headers"]), 200)
    report = validate_success(
        api_client.finalize_report(report["id"], bundle["author_headers"]), 200)
    report = validate_success(
        api_client.sign_report(report["id"], bundle["signer_headers"]), 200)
    validate_success(
        api_client.deliver_report(report["id"], bundle["author_headers"]), 200)
    return bundle


def test_volume_discount_keyed_on_pre_engagement_total(api):
    """PRD §3.2: "The fee quote follows a pinned evaluation order, identical
    at submit and at acceptance: first a pre-discount subtotal is computed
    from the engagement's own attributes; then the discount percentage is
    looked up from the client's `total_billed_cents` exactly as it stands at
    that moment; finally the fee is the subtotal reduced by that discount,
    rounded half-up to whole cents." With 6,000,000 already billed, a
    STANDARD TIERED subtotal of 450,000 is discounted five percent to
    427,500.

    Design: Difficulty/combinatorial_formula/volume_discount_evaluation_order_mode_c
    """
    parties = create_parties(with_signer=True)
    _deliver_first_engagement_billing_six_million(parties)
    client = validate_success(api.get_client(parties["client"]["id"], EM), 200)
    assert client["total_billed_cents"] == 6000000
    assert client["volume_discount_tier"] == "TIER_1"

    eng2 = create_submitted_engagement(
        parties, **STD_TIERED_BASE, requested_turnaround_days=30,
        planned_approach_count=1, fee_schedule="TIERED")
    assert eng2["quoted_fee_cents"] == 427500, (
        f"five percent discount on 450000 must quote 427500, got {eng2['quoted_fee_cents']}")


def test_volume_discount_never_self_referential(api):
    """PRD §3.2: "Because fees are billed only at delivery, the engagement's
    own fee is never part of its own discount base." The first engagement —
    quoted while the client stood at zero billed — prices at the undiscounted
    PER_SF subtotal 30 * 200,000 = 6,000,000 even though delivering it later
    moves the client into TIER_1.

    Design: Difficulty/combinatorial_formula/volume_discount_evaluation_order_mode_c
    """
    parties = create_parties(with_signer=True)
    eng1 = create_submitted_engagement(
        parties, property_address="9 Tower Rd", property_type="OFFICE",
        building_sf=200000, intended_use="FINANCING",
        requested_turnaround_days=45, planned_approach_count=1,
        fee_schedule="PER_SF")
    assert eng1["quoted_fee_cents"] == 6000000, (
        "the engagement's own fee must not be part of its own discount base; "
        f"expected 6000000, got {eng1['quoted_fee_cents']}")
