"""Extended warranties: purchase gating, premium-refund variants, coverage
interval overlap, cross-entity cancellation guard, and warranty-duration
conservation (PRD §3.4, §3.9)."""
from test_helpers import set_clock, validate_error, validate_success
from test_helpers import fixtures as F


# ─── Difficulty: dual_variant_calc (premium refund PRO_RATA vs SHORT_RATE) ───
def test_premium_refund_pro_rata_at_elapsed_6(api):
    """PRD §3.9: "Under the `PRO_RATA` method, the raw refund is the premium
    multiplied by the unused span divided by the total covered months — the full
    unused-fraction premium."
    PRD §3.9: "The unused span is the larger of zero and (total covered months
    minus elapsed months)."

    Design: Difficulty/dual_variant_calc/extended_warranty_premium_refund_pro_rata_vs_short_rate
    """
    # P 12000, T 24, elapsed 6 -> 12000 * 18/24 = 9000.
    s = F.setup_active_registration_with_extension(
        ext_months=24, ext_price_cents=12000, ext_cap_cents=40000,
        ext_premium_refund_method="PRO_RATA",
    )
    set_clock("2024-07-15T00:00:00Z")  # 6 whole months after 2024-01-15 effective.
    cancelled = F.cancel_extension(s["extension"]["id"], s["owner"]["id"])
    assert cancelled["premium_refund_cents"] == 9000
    assert cancelled["status"] == "CANCELLED"


def test_premium_refund_short_rate_at_elapsed_6(api):
    """PRD §3.9: "Under the `SHORT_RATE` method, that same pro-rated figure is then
    reduced by a surrender penalty of 10 percent — that is, multiplied by (1 minus
    0.10) — making the short-rate refund strictly less than the pro-rata refund
    for identical premium, span, and elapsed inputs."

    Design: Difficulty/dual_variant_calc/extended_warranty_premium_refund_pro_rata_vs_short_rate
    """
    # P 12000, T 24, elapsed 6 -> 12000*18/24*(1-0.10) = 8100.
    s = F.setup_active_registration_with_extension(
        ext_months=24, ext_price_cents=12000, ext_cap_cents=40000,
        ext_premium_refund_method="SHORT_RATE",
    )
    set_clock("2024-07-15T00:00:00Z")
    cancelled = F.cancel_extension(s["extension"]["id"], s["owner"]["id"])
    assert cancelled["premium_refund_cents"] == 8100
    assert cancelled["status"] == "CANCELLED"


# ─── Difficulty: resource_temporal_overlap (half-open coverage interval) ─────
def test_extension_coverage_interval_overlap_rejected(api):
    """PRD §3.4: "the new extension's coverage interval, running from its effective
    moment for the tier's extension-months span (a half-open interval that
    includes the start and excludes the end), must not overlap the coverage
    interval of any existing `ACTIVE` extension on the same registration ... a
    genuine overlap is rejected with `ERR_COVERAGE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/extended_warranty_coverage_interval_overlap_half_open
    """
    set_clock("2024-01-15T00:00:00Z")
    product = F.create_product()
    F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=20000)
    silver = F.create_tier(product["id"], tier_name="SILVER", extension_months=12, price_cents=6000, coverage_cap_cents=40000)
    gold = F.create_tier(product["id"], tier_name="GOLD", extension_months=12, price_cents=6000, coverage_cap_cents=40000)
    owner = F.create_owner()
    reg = F.create_registration(product["id"], owner["id"], purchase_date="2024-01-15T00:00:00Z")
    F.submit_and_validate_proof(reg["id"], owner["id"], stated_amount_cents=50000)
    # SILVER covers [2024-01-15, 2025-01-15).
    F.purchase_extension(reg["id"], owner["id"], silver["id"], 6000)
    # GOLD at 2024-07-15 would cover [2024-07-15, 2025-07-15) -> overlaps.
    set_clock("2024-07-15T00:00:00Z")
    resp = api.create_extended_warranty(
        {"registration_id": reg["id"], "coverage_tier_id": gold["id"], "amount_paid_cents": 6000},
        F.make_owner_headers(owner["id"]),
    )
    validate_error(resp, "ERR_COVERAGE_OVERLAP")


def test_extension_adjacent_interval_permitted(api):
    """PRD §3.4: "Because the intervals are half-open, an extension whose start
    exactly equals an existing extension's end is adjacent rather than overlapping
    and is therefore permitted".

    Design: Difficulty/resource_temporal_overlap/extended_warranty_coverage_interval_overlap_half_open
    """
    set_clock("2024-01-15T00:00:00Z")
    product = F.create_product()
    F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=20000)
    silver = F.create_tier(product["id"], tier_name="SILVER", extension_months=12, price_cents=6000, coverage_cap_cents=40000)
    gold = F.create_tier(product["id"], tier_name="GOLD", extension_months=12, price_cents=6000, coverage_cap_cents=40000)
    owner = F.create_owner()
    reg = F.create_registration(product["id"], owner["id"], purchase_date="2024-01-15T00:00:00Z")
    F.submit_and_validate_proof(reg["id"], owner["id"], stated_amount_cents=50000)
    # SILVER covers [2024-01-15, 2025-01-15).
    F.purchase_extension(reg["id"], owner["id"], silver["id"], 6000)
    # GOLD at 2025-01-15 (== existing end) is adjacent, not overlapping.
    set_clock("2025-01-15T00:00:00Z")
    resp = api.create_extended_warranty(
        {"registration_id": reg["id"], "coverage_tier_id": gold["id"], "amount_paid_cents": 6000},
        F.make_owner_headers(owner["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"


# ─── Difficulty: cross_entity_state_dependency (cancel needs reg not terminal) ─
def test_extension_cancel_blocked_when_registration_voided(api):
    """PRD §3.4: "Cancellation is an `Owner`-only action and is permitted only when
    the extension is `ACTIVE`, the acting owner is the parent registration's
    current owner, and the parent registration is in `REGISTERED` or `ACTIVE`
    status."

    Design: Difficulty/cross_entity_state_dependency/extension_cancel_requires_registration_not_terminal
    """
    # Voiding the registration cascade-cancels the extension; the extension is no
    # longer ACTIVE and the registration is VOIDED. A cancel must be rejected.
    s = F.setup_active_registration_with_extension(ext_cap_cents=40000)
    validate_success(api.void_registration(s["registration"]["id"], F.ADMIN))
    resp = api.cancel_extended_warranty(s["extension"]["id"], F.make_owner_headers(s["owner"]["id"]))
    validate_error(resp, "ERR_INVALID_STATE")


def test_extension_cancel_succeeds_on_active_registration(api):
    """PRD §3.4: "Cancelling computes the unused-premium refund (detailed in §3.9),
    sets the extension's `status` to `CANCELLED`".

    Design: Difficulty/cross_entity_state_dependency/extension_cancel_requires_registration_not_terminal
    """
    s = F.setup_active_registration_with_extension(ext_cap_cents=40000)
    cancelled = F.cancel_extension(s["extension"]["id"], s["owner"]["id"])
    assert cancelled["status"] == "CANCELLED"


# ─── Difficulty: compensating_invariant (warranty duration conserved) ────────
def test_extension_purchase_then_cancel_restores_warranty_end(api):
    """PRD §3.4: "its `warranty_end_date` is recomputed to include the new tier's
    extension months".
    PRD §3.4: "the registration's `active_tier_id` drops to the next-highest
    `ACTIVE` tier or to `BASE` if none remains, the `warranty_end_date` is
    recomputed accordingly".

    Design: Difficulty/compensating_invariant/extension_purchase_then_cancel_conserves_warranty_duration_months
    """
    s = F.setup_active_registration_with_extension(
        ext_tier_name="GOLD", ext_months=24, ext_price_cents=12000, ext_cap_cents=40000,
        purchase_price_cents=50000,
    )
    # After GOLD (+24mo) the warranty_end advanced to 2027-01-15; cancel returns to base 12mo -> 2025-01-15.
    cancelled = F.cancel_extension(s["extension"]["id"], s["owner"]["id"])
    assert cancelled["status"] == "CANCELLED"
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["warranty_end_date"].startswith("2025-01-15")
    assert reg["active_tier_id"] == s["base_tier"]["id"]


def test_extension_purchase_advances_then_cancel_drops_active_tier(api):
    """PRD §3.4: "its `active_tier_id` is set to the highest-coverage tier now in
    force".
    PRD §3.4: "the registration's `active_tier_id` drops to the next-highest
    `ACTIVE` tier or to `BASE` if none remains".

    Design: Difficulty/compensating_invariant/extension_purchase_then_cancel_conserves_warranty_duration_months
    """
    s = F.setup_active_registration_with_extension(
        ext_tier_name="GOLD", ext_months=24, ext_price_cents=12000, ext_cap_cents=40000,
    )
    reg_with_ext = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg_with_ext["active_tier_id"] == s["ext_tier"]["id"]
    F.cancel_extension(s["extension"]["id"], s["owner"]["id"])
    reg_after = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg_after["active_tier_id"] == s["base_tier"]["id"]


# ─── Corner: calculations (PRO_RATA full premium at zero elapsed) ────────────
def test_premium_refund_pro_rata_full_at_zero_elapsed(api):
    """PRD §3.9: "Under the `PRO_RATA` method, the raw refund is the premium
    multiplied by the unused span divided by the total covered months — the full
    unused-fraction premium."
    PRD §3.9: "In either case the raw refund is rounded to whole cents using
    round-half-up."

    Design: Corner/calculations/premium_refund_pro_rata_full_unused_at_zero_elapsed
    """
    # P 12000, T 24, elapsed 0 -> 12000 * 24/24 = 12000.
    s = F.setup_active_registration_with_extension(
        ext_months=24, ext_price_cents=12000, ext_cap_cents=40000,
        ext_premium_refund_method="PRO_RATA",
    )
    cancelled = F.cancel_extension(s["extension"]["id"], s["owner"]["id"])
    assert cancelled["premium_refund_cents"] == 12000
    assert cancelled["status"] == "CANCELLED"


# ─── Corner: validations (tier mismatch on amount) ───────────────────────────
def test_extended_warranty_amount_mismatch_returns_tier_mismatch(api):
    """PRD §3.4: "Purchase is gated by a tier-matching rule: the amount paid must
    equal the chosen tier's `price_cents`, the tier must be `ACTIVE`, and the tier
    must belong to the registration's product. Any violation — wrong amount,
    retired tier, or a tier from a different product — is rejected with
    `ERR_TIER_MISMATCH` (HTTP 422)."

    Design: Corner/validations/extended_warranty_amount_mismatch_returns_tier_mismatch
    """
    s = F.setup_active_registration(base_cap_cents=20000)
    gold = F.create_tier(s["product"]["id"], tier_name="GOLD", extension_months=24, price_cents=12000, coverage_cap_cents=40000)
    resp = api.create_extended_warranty(
        {"registration_id": s["registration"]["id"], "coverage_tier_id": gold["id"], "amount_paid_cents": 9999},
        F.make_owner_headers(s["owner"]["id"]),
    )
    validate_error(resp, "ERR_TIER_MISMATCH")


# ─── Corner: endpoint (extension purchase advances warranty_end + tier) ──────
def test_extension_purchase_advances_warranty_end_and_active_tier(api):
    """PRD §3.4: "its `warranty_end_date` is recomputed to include the new tier's
    extension months, its `active_tier_id` is set to the highest-coverage tier now
    in force, and its `remaining_coverage_cents` is recomputed to the new active
    tier's cap minus the registration's existing debits."

    Design: Corner/endpoints/extension_purchase_advances_warranty_end_and_active_tier
    """
    # purchase 2024-01-15, base 12 + GOLD 24 -> warranty_end 2027-01-15; cap 40000.
    s = F.setup_active_registration_with_extension(
        ext_tier_name="GOLD", ext_months=24, ext_price_cents=12000, ext_cap_cents=40000,
    )
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["warranty_end_date"].startswith("2027-01-15")
    assert reg["active_tier_id"] == s["ext_tier"]["id"]
    assert reg["remaining_coverage_cents"] == 40000


def test_list_extended_warranties_filter_by_registration_id(api):
    """PRD §4: "List extended warranties (filter by registration_id,
    coverage_tier_id)".
    PRD §2.5: "Several list endpoints support reverse-reachability filters".

    Design: Corner/endpoints/list_extended_warranties_filter_by_registration_id_reverse_reachability
    """
    from test_helpers import validate_paginated
    s = F.setup_active_registration_with_extension(ext_cap_cents=40000)
    resp = api.list_extended_warranties(
        F.make_owner_headers(s["owner"]["id"]), params={"registration_id": s["registration"]["id"]}
    )
    data, _ = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == s["extension"]["id"]
