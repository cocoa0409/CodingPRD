"""Domain thresholds and numeric constants named in the PRD (§2.4, §2.10, §3)."""

# Logical plant clock (PRD §2.4): server-start default before any explicit set.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Combustion efficiency constants (PRD §3.5).
ENTHALPY_STEAM_BTU_PER_LB = 1190.0
ENTHALPY_FEEDWATER_BTU_PER_LB = 180.0
FUEL_HHV_BTU_PER_GAL = 140000.0
DRY_GAS_LOSS_PCT = 6.5
MOISTURE_LOSS_PCT = 4.0
BLOWDOWN_ENTHALPY_PCT = 100.0
RADIATION_LOSS_PCT = 1.5
HEAT_LOSS_EPSILON = 0.000001

# Steam trap loss projection constants (PRD §3.7).
NAPIER_COEFF = 51.45
GRASHOF_COEFF = 24.24
HOURS_PER_YEAR = 8760
DEFAULT_FUEL_COST_PER_GAL = 3.50
METHOD_NAPIER = "napier_theoretical"
METHOD_GRASHOF = "grashof_empirical"

# Blowdown recommendation constants (PRD §3.3).
TARGET_CYCLES = 10.0
MAX_CYCLES = 10.0
LB_PER_GAL_WATER = 8.345
BLOWDOWN_MIN_GAL_DAY = 5.0
BLOWDOWN_MAX_GAL_DAY = 5000.0

# Lead/lag selector constants (PRD §3.4).
CYCLES_PENALTY_WEIGHT = 0.15
LEAD_BONUS = 5000.0

# Expiry windows (PRD §3.2, §3.6).
CERT_EXPIRING_WINDOW_DAYS = 30
CERT_EXPIRING_WINDOW_SECONDS = 30 * 86400  # 2,592,000
LICENSE_EXPIRING_WINDOW_DAYS = 60
LICENSE_EXPIRING_WINDOW_SECONDS = 60 * 86400  # 5,184,000

# Water mass balance (PRD §2.10).
DRIFT_TOLERANCE_GAL = 25.0

# Inspection booking occupancy (PRD §2.11).
INSPECTION_DURATION_HOURS = 4
INSPECTION_BUFFER_HOURS = 2

# Standard in-spec chemistry reading used across fixtures: cycles 5.0 (<= 10.0).
IN_SPEC_CHEMISTRY = {
    "conductivity_boiler_umho": 5000,
    "conductivity_feedwater_umho": 1000,
    "sulfite_residual_ppm": 30,
    "phosphate_residual_ppm": 40,
}

# Common relief-valve geometry used across fixtures.
DEFAULT_RELIEF_SETPOINT_PSI = 165
DEFAULT_RELIEF_TOLERANCE_PCT = 3.0
DEFAULT_HEADER_PRESSURE_PSI = 150
