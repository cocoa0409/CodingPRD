"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Route capacity (PRD section 3.3)
    "SHIFT_MINUTES": 480,
    "MOBILIZATION_TRAFFIC_MINUTES": 60,
    "MOBILIZATION_BASE_MINUTES": 30,
    # Weekly overtime (PRD section 3.4)
    "WEEKLY_OVERTIME_MINUTES": 2400,
    # Stop difficulty minutes (PRD section 3.3)
    "STOP_MINUTES": {"STANDARD": 45, "HEAVY": 75, "COMPLEX": 120},
    # Replacement work order flat basis (PRD section 3.6)
    "REPLACEMENT_STOP_MINUTES": 75,
    # Salvage settlement (PRD section 3.7)
    "PRICE_PER_LB_CENTS": {
        "COBRA_HEAD": 85,
        "FLOOD": 95,
        "POST_TOP": 70,
        "DECORATIVE": 110,
    },
    "MERCURY_DEDUCTION_CENTS": 300,
    "CONTAMINATION_RATE": 0.15,
    "TRANSPORT_FEE_CENTS": 4500,
    # SLA hours (PRD section 3.6)
    "SLA_HOURS": {"CRITICAL": 24, "HIGH": 48, "STANDARD": 96},
    "REOPEN_WINDOW_HOURS": 72,
    # Dark-sky CCT caps per zone (PRD section 2.6)
    "CCT_CAP_KELVIN": {
        "RESIDENTIAL": 3000,
        "ARTERIAL": 4000,
        "DOWNTOWN": 2700,
        "RURAL": 2200,
    },
    # Burn hours per calendar month (PRD section 3.8)
    "BURN_HOURS": {
        "01": 420, "02": 380, "03": 360, "04": 320,
        "05": 290, "06": 270, "07": 280, "08": 310,
        "09": 340, "10": 380, "11": 410, "12": 430,
    },
}

TEST_DEFAULTS = {
    "PROGRAM_BUDGET_CENTS": 10_000_000,
    "FY_REBATE_CAP_CENTS": 100_000,
    "REBATE_CENTS_PER_KWH": 50,
    "BASE_STOPS_PER_SHIFT": 6,
    "HOURLY_RATE_CENTS": 6000,
    "NAMEPLATE_WATTAGE": 250,
    "LED_WATTAGE": 90,
    "LED_CCT_KELVIN_RESIDENTIAL": 2700,
    "LED_CCT_KELVIN_ARTERIAL": 3000,
}

# The logical clock's untouched default (PRD section 2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_MONTH = "2026-08"

# Standard tier rate cards used by fixtures.
MUNICIPAL_TIER_RATES = {"T1": 700, "T2": 1100, "T3": 1500, "T4": 2000, "T5": 2600}
UTILITY_TIER_RATES = {"T1": 900, "T2": 1300, "T3": 1800, "T4": 2400, "T5": 3000}
