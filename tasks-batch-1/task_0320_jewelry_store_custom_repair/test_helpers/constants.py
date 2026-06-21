"""Domain thresholds — numeric constants from PRD calculations (§2.6, §3.x).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Custom-order totals (PRD §3.3)
PROVISIONAL_MARKUP = 0.20            # estimated materials marked up 20 percent
DEPOSIT_PCT = 0.30                   # deposit is 30 percent of provisional total

# Custom-order revision loop (PRD §3.3)
MAX_REVISIONS = 3                    # 4th request-revision (revision_count == 3) is rejected

# Layaway schedule (PRD §3.5)
DOWN_PAYMENT_PCT = 0.20             # down payment is 20 percent of snapshot price
RESTOCK_PCT = 0.15                  # restocking fee is 15 percent of snapshot price
MAX_RESTOCK_CENTS = 50_000         # restocking fee capped at 50000 cents

# Trade-in buyback credit (PRD §3.6)
PURITY_FACTOR = {"K14": 0.585, "K18": 0.750, "K24": 1.000}
CONDITION_FACTOR = {"EXCELLENT": 0.90, "GOOD": 0.75, "FAIR": 0.55}
MIN_BUYBACK_CENTS = 2_500          # buyback clamp floor
MAX_BUYBACK_CENTS = 5_000_000      # buyback clamp ceiling

# Repair rush surcharge tiers (PRD §3.4)
RUSH_TIER1_MAX = 10_000            # below this -> 10 percent
RUSH_TIER2_MAX = 50_000           # up to and including this -> 20 percent; above -> 30 percent
RUSH_PCT_LOW = 0.10
RUSH_PCT_MID = 0.20
RUSH_PCT_HIGH = 0.30

# Appraisal replacement value (PRD §3.2)
DEFAULT_REPLACEMENT_FACTOR = 1.30
REPLACEMENT_FACTOR_MIN = 1.00
REPLACEMENT_FACTOR_MAX = 2.00

# Appraiser appointment scheduling (PRD §2.10)
APPRAISAL_BUFFER_MINUTES = 30

# Layaway installment range (PRD §3.5)
INSTALLMENT_COUNT_MIN = 2
INSTALLMENT_COUNT_MAX = 24
