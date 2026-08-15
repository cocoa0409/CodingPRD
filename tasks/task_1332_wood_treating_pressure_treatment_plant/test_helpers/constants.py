"""Domain thresholds and numeric constants (PRD §2.5, §3.6–§3.9)."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value, ndigits: int) -> Decimal:
    """Round half-up to `ndigits` decimal places (PRD §2.6)."""
    quant = Decimal("1") if ndigits == 0 else Decimal("1." + "0" * ndigits)
    return Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)


# --- Species penetration factors (PRD §3.6) ---
SPECIES_PENETRATION_FACTOR = {
    "SPF": 0.85,
    "SYP": 0.92,
    "DOUGLAS_FIR": 0.65,
    "HEM_FIR": 0.72,
    "PONDEROSA_PINE": 0.78,
}
SPECIES_INCISED_FACTOR = {
    "DOUGLAS_FIR": 0.95,
    "HEM_FIR": 0.93,
}

# --- Assay outcome rule (PRD §3.7) ---
PASS_THRESHOLD_FRACTION = 0.90  # pass_threshold_pcf = target_retention_pcf * 0.90

# --- Registration fee schedule (PRD §3.8) ---
BASE_FEE_CENTS = {"UC3B": 1500, "UC4A": 3200, "UC4B": 5800, "UC4C": 9100}
TIER2_DISCOUNT = Decimal("0.05")   # above 10 mbf, up to and including 50 mbf
TIER3_DISCOUNT = Decimal("0.12")   # above 50 mbf
TIER2_MAX_MBF = 50.0
TIER1_MAX_MBF = 10.0
CUSTOM_TREAT_UPLIFT = Decimal("0.18")
TERM_MULTIPLIER = {"5": Decimal("1.00"), "25": Decimal("1.45"), "50": Decimal("1.95")}

# --- Hazard liability (PRD §3.8 drip pads; §3.7 scrap) ---
PER_LITER_RATE_CENTS = 250                  # $2.50/L
BREACH_THRESHOLD_LITERS = 50.0              # surcharge applies when strictly greater
CRITICAL_BREACH_SURCHARGE_CENTS = 250000    # $2,500
BREACH_COMPLIANCE_PENALTY = 50
SCRAP_DISPOSAL_PER_MBF_CENTS = 75000        # $750 per mbf
SCRAP_COMPLIANCE_PENALTY = 100

# --- Compliance score (PRD §2.5, §3.9) ---
INITIAL_COMPLIANCE_SCORE = 1000
SUSPEND_THRESHOLD = 300
FINDING_DEDUCTION = {"CRITICAL": 200, "MAJOR": 100, "MINOR": 25}

# --- Tagging gates (PRD §3.8) ---
DRIP_MIN_DWELL_HOURS = 24

# --- Re-treat loop (PRD §3.7) ---
MAX_CYCLE_NUMBER = 3

# --- Deterministic logical time used across tests (PRD §2.10) ---
CLOCK_NOW = "2026-08-10T08:00:00Z"
SLOT_START = "2026-08-10T07:00:00Z"
SLOT_END = "2026-08-12T23:59:00Z"
DRIP_ENTER = "2026-08-10T18:00:00Z"
DRIP_EXIT_OK = "2026-08-12T18:30:00Z"     # 48.5h dwell (>= 24h)
DRIP_EXIT_SHORT = "2026-08-11T06:00:00Z"  # 12h dwell (< 24h)
ASSAY_RECORDED_AT = "2026-08-10T18:00:00Z"
INSPECTION_WINDOW_WIDE = ("2026-08-01T00:00:00Z", "2027-01-01T00:00:00Z")
