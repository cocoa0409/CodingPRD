"""Domain thresholds — numeric constants drawn from PRD calculations.

PRD §3.5 — pass/fail thresholds:
  PESTICIDE_RESIDUE: pass iff value <= 0.50 (boundary inclusive)
  HEAVY_METALS:     pass iff value <= 0.20 (boundary inclusive)
  MICROORGANISMS:   pass iff value < 100000  (strict; equality fails)

PRD §3.6 — cold chain:
  Three or more consecutive out-of-range readings constitute one abnormal segment.

PRD §2.3 — pagination defaults:
  limit defaults to 10, with a minimum of 1 and a maximum of 100; offset defaults to 0.
"""

# -------- Pass/fail thresholds (PRD §3.5) --------
MAX_PESTICIDE_MG_PER_KG = 0.50
MAX_HEAVY_METAL_MG_PER_KG = 0.20
MAX_MICRO_CFU_PER_G = 100000

# -------- Cold-chain (PRD §3.6) --------
MIN_CONSECUTIVE_BREACHES = 3

# -------- Pagination (PRD §2.3) --------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# -------- Test convenience --------
THRESHOLDS = {
    "MAX_PESTICIDE_MG_PER_KG": MAX_PESTICIDE_MG_PER_KG,
    "MAX_HEAVY_METAL_MG_PER_KG": MAX_HEAVY_METAL_MG_PER_KG,
    "MAX_MICRO_CFU_PER_G": MAX_MICRO_CFU_PER_G,
    "MIN_CONSECUTIVE_BREACHES": MIN_CONSECUTIVE_BREACHES,
}
