"""Calculation rules (scaffold §1.3, PRD §3.1, §3.4, §3.6, §3.7, §3.10).

All monetary figures are whole dollars, round half up. Decimal is used for every
money computation; rounding points are pinned exactly as the PRD specifies.
"""

from decimal import Decimal

from helpers import round_dollars

# --- crs_community_discount ---
CRS_DISCOUNT_TABLE = {
    1: Decimal("0.45"), 2: Decimal("0.40"), 3: Decimal("0.35"),
    4: Decimal("0.30"), 5: Decimal("0.25"), 6: Decimal("0.20"),
    7: Decimal("0.15"), 8: Decimal("0.10"), 9: Decimal("0.05"),
    10: Decimal("0.00"),
}

# --- premium_quote constants ---
BUILDING_RATE_RR2 = {"HIGH": Decimal("0.0040"), "MODERATE": Decimal("0.0025"), "LOW": Decimal("0.0012")}
CONTENTS_RATE_RR2 = Decimal("0.0020")
BUILDING_RATE_LEGACY = {"AE": Decimal("0.0060"), "VE": Decimal("0.0090"), "X": Decimal("0.0010")}
CONTENTS_RATE_LEGACY = {"AE": Decimal("0.0035"), "VE": Decimal("0.0050"), "X": Decimal("0.0008")}
ZONE_BAND_RR2 = {"VE": "HIGH", "AE": "MODERATE", "X": "LOW"}
ICC_PREMIUM = 75
FEDERAL_POLICY_FEE = 50
HFIAA_PRIMARY = 25
HFIAA_NONPRIMARY = 250

# --- claim_settlement constants ---
ICC_COVERAGE_CAP = 30000

# --- proration / waiting period constants ---
TERM_DAYS = 365
STANDARD_WAITING_DAYS = 30
LENDER_WAITING_DAYS = 0
PROOF_OF_LOSS_DEADLINE_DAYS = 60


def crs_discount_pct(crs_class):
    """Exact table lookup (not rounded). Returns a Decimal fraction."""
    return CRS_DISCOUNT_TABLE[crs_class]


def elev_factor(freeboard):
    """Step schedule for the RR2.0 elevation factor (PRD §3.4 step one).

    f>=3 -> 0.70 ; 1<=f<3 -> 0.85 ; 0<=f<1 -> 1.00 ; -1<=f<0 -> 1.50 ; f<-1 -> 2.00
    """
    f = Decimal(str(freeboard))
    if f >= 3:
        return Decimal("0.70")
    if f >= 1:
        return Decimal("0.85")
    if f >= 0:
        return Decimal("1.00")
    if f >= -1:
        return Decimal("1.50")
    return Decimal("2.00")


def compute_premium(rating_method, flood_zone, building_coverage, contents_coverage,
                    occupancy, crs_discount, freeboard):
    """premium_quote pinned evaluation order (PRD §3.4).

    crs_discount is a Decimal fraction; freeboard is the latest non-superseded
    certificate's freeboard_ft (only used for RR2.0; may be None which the caller
    must avoid for RR2.0 — but if None we treat freeboard as 0 -> factor 1.00 is
    NOT done; instead RR2.0 with no certificate uses elev_factor of a 0 freeboard
    only if explicitly provided). Here freeboard is required for RR2.0 callers.
    """
    bc = Decimal(str(building_coverage))
    cc = Decimal(str(contents_coverage))

    # step 1 risk_base (rounded to whole dollars)
    if rating_method == "RISK_RATING_2_0":
        band = ZONE_BAND_RR2[flood_zone]
        raw = (bc * BUILDING_RATE_RR2[band] + cc * CONTENTS_RATE_RR2) * elev_factor(freeboard)
        risk_base = round_dollars(raw)
    else:  # LEGACY_SUBSIDIZED
        raw = bc * BUILDING_RATE_LEGACY[flood_zone] + cc * CONTENTS_RATE_LEGACY[flood_zone]
        risk_base = round_dollars(raw)

    # step 2 discounted (rounded to whole dollars)
    discounted = round_dollars(Decimal(risk_base) * (Decimal("1") - crs_discount))

    # step 3 surcharge
    surcharge = HFIAA_PRIMARY if occupancy == "PRIMARY_RESIDENCE" else HFIAA_NONPRIMARY

    # step 4 total (flats added onto already-rounded discounted subtotal)
    quoted = discounted + ICC_PREMIUM + FEDERAL_POLICY_FEE + surcharge
    return quoted


def compute_settlement(occupancy, building_loss, contents_loss, depreciation_pct,
                       building_coverage, contents_coverage,
                       building_deductible, contents_deductible,
                       substantial_damage, icc_eligible_cost):
    """claim_settlement (PRD §3.10). Round each bucket before subtracting its deductible."""
    dep = Decimal(str(depreciation_pct))

    # building adjusted loss
    if occupancy == "NON_PRIMARY":
        building_loss_adj = round_dollars(Decimal(str(building_loss)) * (Decimal("1") - dep))
    else:  # PRIMARY_RESIDENCE -> RCV, no depreciation
        building_loss_adj = round_dollars(Decimal(str(building_loss)))

    # contents always ACV
    contents_loss_acv = round_dollars(Decimal(str(contents_loss)) * (Decimal("1") - dep))

    building_payable = max(0, min(building_loss_adj, int(building_coverage)) - int(building_deductible))
    contents_payable = max(0, min(contents_loss_acv, int(contents_coverage)) - int(contents_deductible))

    if substantial_damage:
        icc_payable = min(int(icc_eligible_cost), ICC_COVERAGE_CAP)
    else:
        icc_payable = 0

    settlement_total = building_payable + contents_payable + icc_payable
    return {
        "building_payable": building_payable,
        "contents_payable": contents_payable,
        "icc_payable": icc_payable,
        "settlement_total": settlement_total,
    }


def prorate_earned(quoted_premium, days_elapsed):
    """earned_premium = round(quoted * days_elapsed / term); unearned is exact complement.

    days_elapsed must already be clamped to [0, TERM_DAYS]. Returns (earned, unearned).
    """
    earned = round_dollars(Decimal(str(quoted_premium)) * Decimal(days_elapsed) / Decimal(TERM_DAYS))
    unearned = int(quoted_premium) - earned
    return earned, unearned
