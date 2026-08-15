"""Pricing calculations: provisional quote, final invoice, cancellation fee.

Nine pinned steps, each line rounded half-up to whole cents BEFORE summation.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from db import store


MASKING_RATE = 85            # cents per masking minute
BARREL_FLAT_FEE = 1200       # cents per load run
UNASSIGNED_RACK_FEE = 2000   # cents per planned run when no fixture assigned yet
REWORK_RATE = Decimal("0.20")
HAZMAT_FEE = 2500            # cents
HAZMAT_FAMILIES = {"CHROMIC", "CYANIDE"}


def _d(v):
    return Decimal(str(v))


def round_half_up_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def amortization_cents_per_use(purchase_cost_cents: int, rated_uses: int) -> int:
    """ceil(purchase_cost_cents / rated_uses) — computed at fixture creation."""
    q = (Decimal(purchase_cost_cents) / Decimal(rated_uses)).quantize(
        Decimal("1"), rounding=ROUND_CEILING
    )
    return int(q)


def compute_price(work_order, variant: str) -> int:
    """Compute the nine-step price. variant: 'provisional' or 'final'."""
    # Step 1 — masking line
    masking_cents = 0
    if work_order.get("requires_masking"):
        minutes = work_order.get("masking_minutes_actual") or 0
        masking_cents = round_half_up_cents(_d(minutes) * MASKING_RATE)

    # Step 2 — fixture line
    if variant == "provisional":
        planned_runs = 1
    else:
        planned_runs = work_order.get("completed_load_count", 0)
    fixture_cents = 0
    if work_order.get("routing_mode") == "RACK":
        fixture_id = work_order.get("fixture_id")
        fixture = store.fixtures.get(fixture_id) if fixture_id else None
        if fixture is not None:
            per_use = fixture["amortization_cents_per_use"]
        else:
            per_use = UNASSIGNED_RACK_FEE
        fixture_cents = round_half_up_cents(_d(per_use) * planned_runs)
    else:  # BARREL
        fixture_cents = round_half_up_cents(_d(BARREL_FLAT_FEE) * planned_runs)

    # Step 3 — billing thickness
    billing_thickness_um = round_half_up_1dp(
        (_d(work_order["thickness_spec_min_um"]) + _d(work_order["thickness_spec_max_um"])) / 2
    )

    # Step 4 — processing line
    if billing_thickness_um < Decimal("10"):
        tier_rate = 12
    elif billing_thickness_um < Decimal("25"):
        tier_rate = 15
    else:
        tier_rate = 19
    processing_cents = round_half_up_cents(
        _d(work_order["surface_area_total_dm2"]) * billing_thickness_um * tier_rate
    )

    # Step 5 — rework surcharge
    if variant == "provisional":
        rework_count = 0
    else:
        rework_count = work_order.get("rework_count", 0)
    rework_surcharge_cents = round_half_up_cents(_d(processing_cents) * REWORK_RATE) * rework_count

    # Step 6 — subtotal
    subtotal_cents = masking_cents + fixture_cents + processing_cents + rework_surcharge_cents

    # Step 7 — discount keyed on pre-discount subtotal
    if subtotal_cents >= 1000000:
        rate = Decimal("0.08")
    elif subtotal_cents >= 500000:
        rate = Decimal("0.05")
    else:
        rate = Decimal("0")
    discount_cents = round_half_up_cents(_d(subtotal_cents) * rate)

    # Step 8 — hazmat fee
    if variant == "provisional":
        hazmat_fee_cents = 0
    else:
        family = work_order.get("routed_chemistry_family")
        hazmat_fee_cents = HAZMAT_FEE if family in HAZMAT_FAMILIES else 0

    # Step 9 — total
    return subtotal_cents - discount_cents + hazmat_fee_cents


def compute_processing_component(work_order) -> int:
    """Step 4 of the pricing formula evaluated on the current spec (used by late-cancel fee)."""
    billing_thickness_um = round_half_up_1dp(
        (_d(work_order["thickness_spec_min_um"]) + _d(work_order["thickness_spec_max_um"])) / 2
    )
    if billing_thickness_um < Decimal("10"):
        tier_rate = 12
    elif billing_thickness_um < Decimal("25"):
        tier_rate = 15
    else:
        tier_rate = 19
    return round_half_up_cents(
        _d(work_order["surface_area_total_dm2"]) * billing_thickness_um * tier_rate
    )


def compute_cancellation_fee(work_order) -> int:
    """Late cancel fee: round_half_up(processing_component * 0.5, 0)."""
    processing = compute_processing_component(work_order)
    return round_half_up_cents(_d(processing) * Decimal("0.5"))
