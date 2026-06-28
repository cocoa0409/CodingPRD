"""Self-pay pricing engine (PRD §2.7, §3.3, §3.6).

Both the forward-looking cart estimate and the chronological order invoice share
the same four-step arithmetic; only the input set differs. All money is integer
cents; round-half-up is applied at each pinned rounding point (per-line repeat
discount, then platform tier discount), per line then summed.
"""
from decimal import Decimal, ROUND_HALF_UP

import db

REPEAT_DISCOUNT_RATE = Decimal("0.15")
PLATFORM_TIER1_CENTS = 20000
PLATFORM_TIER1_RATE = Decimal("0.10")
PLATFORM_TIER2_CENTS = 50000
PLATFORM_TIER2_RATE = Decimal("0.15")


def round_half_up(value):
    """Round a Decimal to the nearest whole cent, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _active_bundles():
    """ACTIVE PanelBundles in deterministic (bundle_code ASC, created_at ASC) order."""
    bundles = [b for b in db.all_rows("panel_bundles") if b["status"] == "ACTIVE"]
    return sorted(bundles, key=lambda b: (b["bundle_code"], b.get("created_at", ""), b.get("_seq", 0)))


def price_lines(lines, fund_source, hsa_balance_cents):
    """Run the four pinned pricing steps over a list of line dicts.

    Each line dict must carry: test_code, unit_list_price_cents,
    repeat_discount_applied. Returns a dict with subtotal_cents, total_cents,
    hsa_applied_cents, patient_due_cents.
    """
    # --- Step A: bundle substitution ---------------------------------------
    # Build a multiset of (test_code -> list of line refs still unmatched),
    # preserving each line so we can price leftovers.
    remaining = {}
    for ln in lines:
        remaining.setdefault(ln["test_code"], []).append(ln)

    subtotal = 0
    for bundle in _active_bundles():
        members = bundle["member_test_codes"]
        # A bundle qualifies if every member still has an unmatched line.
        # Members may repeat? Count required occurrences of each code.
        need = {}
        for code in members:
            need[code] = need.get(code, 0) + 1
        if all(len(remaining.get(code, [])) >= cnt for code, cnt in need.items()):
            subtotal += bundle["bundle_price_cents"]
            for code, cnt in need.items():
                # Consume cnt lines of this code.
                for _ in range(cnt):
                    remaining[code].pop(0)

    # --- Step B: price each line no bundle consumed (per-line repeat disc) ---
    for code, leftover in remaining.items():
        for ln in leftover:
            base = ln["unit_list_price_cents"]
            if ln.get("repeat_discount_applied"):
                line_net = round_half_up(Decimal(base) * (Decimal(1) - REPEAT_DISCOUNT_RATE))
            else:
                line_net = base
            subtotal += line_net

    # --- Step C: platform tier discount keyed on subtotal -------------------
    if subtotal >= PLATFORM_TIER2_CENTS:
        rate = PLATFORM_TIER2_RATE
    elif subtotal >= PLATFORM_TIER1_CENTS:
        rate = PLATFORM_TIER1_RATE
    else:
        rate = Decimal("0")
    platform_discount = round_half_up(Decimal(subtotal) * rate)
    total = subtotal - platform_discount

    # --- Step D: HSA/FSA application ---------------------------------------
    if fund_source == "HSA_FSA":
        hsa_applied = min(hsa_balance_cents, total)
    else:
        hsa_applied = 0
    patient_due = total - hsa_applied

    return {
        "subtotal_cents": subtotal,
        "total_cents": total,
        "hsa_applied_cents": hsa_applied,
        "patient_due_cents": patient_due,
    }
