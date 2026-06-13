"""Pricing (provisional quote vs final grant fee) and tiered cancellation refunds.

Covers difficulty instances dual_variant_calc (permit fee divergence),
combinatorial_formula (pinned rounding order; two-factor refund tier),
boundary_precision_check (48h refund boundary), plus the corner calculation
instances (residency flip, refund-preview estimate, probation threshold).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    set_clock, create_facility, create_patron, apply_permit, capture_payment,
    facility_version, grant_permit, setup_granted_permit, get_first_refund,
    cancel_permit, make_patron_headers, make_coordinator_headers,
    TEST_USERS,
)

COORD = TEST_USERS["rec_coordinator_headers"]


def test_quoted_and_final_fee_diverge_by_rounding_order(api):
    """PRD §2.7: "The two pricing calculations differ deliberately in *when* that
    rounding happens relative to summation — the provisional quote rounds each
    component before summing, while the final grant fee sums first and rounds once
    — and those orderings are pinned in §3; they are not interchangeable, and
    identical inputs can legitimately yield a one-cent difference between the two."
    PRD §3.3: "The provisional quote is the sum of those two already-rounded
    components — round each component, then sum."
    PRD §3.6: "Unlike the provisional quote, the final fee sums those two raw
    components first and rounds the single total half up to whole cents once."

    Facility hourly 3333, discount 0.40 -> effective rate 1999.8 cents/hr.
    Window 17:30-19:30 = 0.5h non-prime + 1.5h prime (x1.5).
    Provisional: round(0.5*1999.8)=1000 + round(1.5*1999.8*1.5)=4500 -> 5500.
    Final: round(0.5*1999.8 + 1.5*1999.8*1.5) = round(5499.45) -> 5499.

    Design: Difficulty/dual_variant_calc/dvc_provisional_vs_final_rounding_order_permit
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="Div Court", facility_type="COURT", hourly_rate_cents=3333,
        resident_discount_pct=0.40, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=4000,
        buffer_minutes=0, requires_coi=False,
    )
    patron = create_patron(verified=True, residency="RESIDENT")
    permit = apply_permit(
        facility["id"], patron["id"],
        "2026-08-02T17:30:00Z", "2026-08-02T19:30:00Z",
    )
    assert permit["quoted_fee_cents"] == 5500, "round-per-component-then-sum yields 5500"

    capture_payment(permit["id"], 5499, 4000)
    v = facility_version(facility["id"])
    granted = grant_permit(facility["id"], permit["id"], v)

    assert granted["final_fee_cents"] == 5499, "sum-then-round yields 5499"
    assert granted["quoted_fee_cents"] != granted["final_fee_cents"], (
        "the divergence comes purely from rounding order"
    )


def test_provisional_quote_pins_round_per_component_then_sum(api):
    """PRD §3.3: "The non-prime component is the non-prime hours multiplied by the
    effective rate, rounded half up to whole cents. The prime component is the
    prime hours multiplied by the effective rate multiplied by the facility's
    prime_multiplier, rounded half up to whole cents independently. The provisional
    quote is the sum of those two already-rounded components — round each
    component, then sum."

    Same F_div config and RESIDENT-verified patron: per-component rounding gives
    1000 + 4500 = 5500 (naive sum-then-round of the quote would give 5499).

    Design: Difficulty/combinatorial_formula/cf_rounding_order_pinned_provisional
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="Div2", facility_type="COURT", hourly_rate_cents=3333,
        resident_discount_pct=0.40, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=0, requires_coi=False,
    )
    patron = create_patron(verified=True, residency="RESIDENT")
    permit = apply_permit(
        facility["id"], patron["id"],
        "2026-08-02T17:30:00Z", "2026-08-02T19:30:00Z",
    )
    assert permit["quoted_fee_cents"] == 5500
    assert permit["is_prime_requested"] is True
    assert permit["pricing_residency"] == "RESIDENT"


def test_late_cancel_zero_fee_but_deposit_kept_two_factor_refund(api):
    """PRD §3.7: "If the lead is under 48 hours, none of the usage fee is refunded."
    PRD §3.7: "The deposit is handled separately: the full deposit_held_cents is
    returned as deposit_refund_cents unless the lead is under 24 hours — under one
    day — in which case the deposit is forfeited and the deposit refund is 0."
    PRD §3.7: "The total_refund_cents is the sum of the fee refund and the deposit
    refund, and a Refund is created with these amounts and the supplied
    refund_destination; the permit's refunded_cents is set accordingly."

    final_fee 24000, deposit 5000, lead exactly 30h: fee tier 0% (lead<48),
    deposit kept (lead>=24) -> fee 0, deposit 5000, total 5000.

    Design: Difficulty/combinatorial_formula/cf_nonlinear_refund_two_factor_tier
    """
    ctx = setup_granted_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={
            "name": "Flip Pool", "facility_type": "POOL", "hourly_rate_cents": 10000,
            "resident_discount_pct": 0.40, "prime_multiplier": 1.5,
            "prime_start_hour": 18, "prime_end_hour": 22, "deposit_cents": 5000,
            "requires_coi": False,
        },
        patron_verified=True, patron_overrides={"residency": "RESIDENT"},
        start_at="2026-08-01T17:00:00Z", end_at="2026-08-01T20:00:00Z",
        fee_component_cents=24000, deposit_component_cents=5000,
    )
    facility, patron, permit = ctx["facility"], ctx["patron"], ctx["permit"]

    set_clock("2026-07-31T11:00:00Z")  # lead = 30h before start 2026-08-01T17:00
    cancelled = cancel_permit(
        facility["id"], permit["id"], make_patron_headers(patron["id"]),
        refund_destination="ORIGINAL",
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancelled_lead_hours"] == 30

    refund = get_first_refund(permit["id"])
    assert refund is not None, "a Refund must be created on GRANTED->CANCELLED"
    assert refund["fee_refund_cents"] == 0
    assert refund["deposit_refund_cents"] == 5000
    assert refund["total_refund_cents"] == 5000


def test_refund_lead_exactly_48h_is_partial_fee_tier(api):
    """PRD §3.7: "If the lead is less than seven days but at least 48 hours — at
    least two days — half the usage fee is refunded."
    PRD §3.7: "The fee refund is the chosen fraction of final_fee_cents, rounded
    half up to whole cents, and is recorded as fee_refund_cents."

    final_fee 24000, deposit 5000, lead exactly 48h -> 50% fee = 12000, deposit
    fully kept (lead>=24).

    Design: Difficulty/boundary_precision_check/bpc_refund_lead_48h_partial_boundary
    """
    ctx = setup_granted_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={
            "name": "B48 Pool", "facility_type": "POOL", "hourly_rate_cents": 10000,
            "resident_discount_pct": 0.40, "prime_multiplier": 1.5,
            "prime_start_hour": 18, "prime_end_hour": 22, "deposit_cents": 5000,
            "requires_coi": False,
        },
        patron_verified=True, patron_overrides={"residency": "RESIDENT"},
        start_at="2026-08-01T17:00:00Z", end_at="2026-08-01T20:00:00Z",
        fee_component_cents=24000, deposit_component_cents=5000,
    )
    facility, patron, permit = ctx["facility"], ctx["patron"], ctx["permit"]

    set_clock("2026-07-30T17:00:00Z")  # lead = 48h exactly
    cancelled = cancel_permit(
        facility["id"], permit["id"], make_patron_headers(patron["id"]),
        refund_destination="ORIGINAL",
    )
    assert cancelled["cancelled_lead_hours"] == 48

    refund = get_first_refund(permit["id"])
    assert refund is not None
    assert refund["fee_refund_cents"] == 12000, "50% of 24000 at lead==48h (inclusive)"
    assert refund["deposit_refund_cents"] == 5000


def test_residency_verified_between_apply_and_grant_changes_final_fee(api):
    """PRD §3.6: "residency is re-resolved as of the grant moment: the final
    residency tier is RESIDENT only when the patron's residency is RESIDENT and
    residency_verified is true at the moment of grant, otherwise NON_RESIDENT.
    Because a patron's residency may have been verified between application and
    grant, this snapshot can differ from the one locked into pricing_residency."
    PRD §3.3: "It resolves to RESIDENT only when the patron's residency is RESIDENT
    and their residency_verified is true at application time; in every other case
    it resolves to NON_RESIDENT."

    Apply as RESIDENT-but-unverified (quoted at NON_RESIDENT: 1h np*10000 +
    2h prime*10000*1.5 = 10000+30000 = 40000), verify, then grant -> final
    re-resolves RESIDENT (eff 6000): 1*6000 + 2*6000*1.5 = 6000+18000 = 24000.

    Design: Corner/calculations/residency_flip_between_apply_and_grant
    """
    set_clock("2026-07-01T00:00:00Z")
    facility = create_facility(
        name="RF Pool", facility_type="POOL", hourly_rate_cents=10000,
        resident_discount_pct=0.40, prime_multiplier=1.5,
        prime_start_hour=18, prime_end_hour=22, deposit_cents=0,
    )
    patron = create_patron(residency="RESIDENT")  # not yet verified
    permit = apply_permit(
        facility["id"], patron["id"],
        "2026-08-26T17:00:00Z", "2026-08-26T20:00:00Z",
    )
    assert permit["quoted_fee_cents"] == 40000, "priced NON_RESIDENT at apply (unverified)"

    validate_success(api.verify_residency(patron["id"], COORD), 200)
    capture_payment(permit["id"], 24000, 0)
    v = facility_version(facility["id"])
    granted = grant_permit(facility["id"], permit["id"], v)

    assert granted["final_fee_cents"] == 24000, "priced RESIDENT at grant"
    # PRD §3.6: the grant-moment residency snapshot drives final_fee_cents but is
    # distinct from "the one locked into pricing_residency". Per §3.3 that lock is
    # taken at application time, when the patron was RESIDENT-but-unverified, so
    # pricing_residency stays NON_RESIDENT even though the final fee re-resolved
    # RESIDENT.
    assert granted["pricing_residency"] == "NON_RESIDENT"


def test_refund_preview_is_non_persisted_estimate(api):
    """PRD §3.7: "A patron can preview the cancellation refund before committing.
    The preview computes the same tiered refund using the current clock at the
    moment of the preview and returns a non-persisted Refund shape."
    PRD §3.7: "If the lead is at least 168 hours — a full seven days — the entire
    usage fee is refunded."

    Granted permit final 24000 + deposit 5000, clock at lead 200h -> preview shows
    full 29000 but does not cancel or persist anything.

    Design: Corner/calculations/refund_preview_estimate_does_not_persist
    """
    ctx = setup_granted_permit(
        clock="2026-07-01T00:00:00Z",
        facility_overrides={
            "name": "Prev Pool", "facility_type": "POOL", "hourly_rate_cents": 10000,
            "resident_discount_pct": 0.40, "prime_multiplier": 1.5,
            "prime_start_hour": 18, "prime_end_hour": 22, "deposit_cents": 5000,
        },
        patron_verified=True, patron_overrides={"residency": "RESIDENT"},
        start_at="2026-08-01T17:00:00Z", end_at="2026-08-01T20:00:00Z",
        fee_component_cents=24000, deposit_component_cents=5000,
    )
    facility, patron, permit = ctx["facility"], ctx["patron"], ctx["permit"]

    set_clock("2026-07-24T09:00:00Z")  # lead 200h before 2026-08-01T17:00
    preview = validate_success(
        api.refund_preview(permit["id"], make_patron_headers(patron["id"])), 200)
    assert preview["total_refund_cents"] == 29000, "fee 24000 + deposit 5000, full at lead 200h"

    after = validate_success(api.get_permit(permit["id"], COORD), 200)
    assert after["status"] == "GRANTED", "preview must not cancel"
    assert after["refunded_cents"] == 0, "preview must not persist a refund"


def test_probation_threshold_at_exactly_two_strikes(api):
    """PRD §3.1: "if no_show_strikes is at least 4 the standing is BARRED;
    otherwise if no_show_strikes is at least 2 the standing is PROBATION;
    otherwise the standing is GOOD."
    PRD §3.1: "These two thresholds — two strikes for probation and four strikes
    for being barred — are checked with at-least (inclusive) comparisons."

    Injecting exactly 2 strikes crosses to PROBATION.

    Design: Corner/calculations/probation_threshold_boundary_two_strikes
    """
    patron = create_patron()
    res = api.inject_no_show_strikes(patron["id"], 2, COORD)
    updated = validate_success(res, 200)
    assert updated["no_show_strikes"] == 2
    assert updated["standing"] == "PROBATION"
