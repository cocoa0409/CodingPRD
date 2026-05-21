"""Domain constants — pulled from the scaffold §1.3 and §1.4."""
from __future__ import annotations


# --- Lessee / lease thresholds (account ledger gating) ---
# §3.2 / §3.8: suspend at SUSPEND_THRESHOLD_CENTS, default at the strictly higher DEFAULT_THRESHOLD_CENTS
# Chosen to be reachable in a single collision approval (each claim is capped at DEDUCTIBLE_CAP_CENTS).
SUSPEND_THRESHOLD_CENTS = 100_000          # $1,000
DEFAULT_THRESHOLD_CENTS = 200_000          # $2,000 (strictly higher than suspend, below cap)

# --- Collision claim ---
MAX_REVISION_ROUNDS = 2                    # §1.4 ERR_REVISION_LIMIT_REACHED, design rule "third request rejected"
DEDUCTIBLE_CAP_CENTS = 250_000             # $2,500 (scaffold §1.3 collision_settlement.constants)
GOOD_TELEMATICS_DISCOUNT_BPS = 2_500       # 25% in basis points

# --- Overage settlement ---
DISPUTE_WINDOW_DAYS = 14

# Tiered overage breakpoints / multipliers (scaffold §1.3 overage_settlement.constants)
TIER1_BREAK = 500
TIER2_BREAK = 2_000
TIER2_MULT_BPS = 12_500     # 1.25x
TIER3_MULT_BPS = 15_000     # 1.50x

# --- IFTA cents-per-gallon table (scaffold §1.3 ifta_tax.constants) ---
IFTA_RATES: dict[str, int] = {
    "CA": 87,
    "TX": 20,
    "NY": 45,
    "IL": 47,
    "FL": 36,
    "OH": 47,
    "PA": 75,
    "GA": 32,
    "WA": 49,
    "AZ": 26,
}


# Domain enums / role table (kept here so any layer can import without circular issues)
VALID_ROLES = {"FleetManager", "TaxAdmin", "ClaimAdjuster", "VendorOps", "Lessee"}

VALID_BASE_JURISDICTIONS = set(IFTA_RATES.keys())          # CA, TX, NY, IL, FL, OH, PA, GA, WA, AZ
VALID_VEHICLE_CLASSES = {"CLASS_3", "CLASS_5", "CLASS_7", "CLASS_8"}
IFTA_ELIGIBLE_CLASSES = {"CLASS_7", "CLASS_8"}
