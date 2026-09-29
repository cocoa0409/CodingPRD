"""Numeric constants and thresholds the PRD pins by name.

Every value here is stated in the PRD prose; nothing is inferred. Tests import
these so a threshold is written once and asserted everywhere.
"""
from __future__ import annotations

# PRD 2.5 — the logical clock reads this until it is set explicitly.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# PRD 2.3 — pagination
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# PRD 3.1 — scope
CHANGE_ORDER_CAP_PCT = 0.20

# PRD 3.2 — civil work under the stormwater permit
RAIN_TRIGGER_INCHES = 0.25
RAIN_BLACKOUT_HOURS = 48
MIN_COMPACTION_PCT = 95.0

# PRD 3.3 — laydown yard
MAX_DAMAGE_RATIO = 0.05

# PRD 3.4 — piles and mechanical completion
REFUSAL_MIN_EMBEDMENT_RATIO = 0.90
PLUMB_TOLERANCE_MM = 12.0
TORQUE_TUBE_TOLERANCE_MM = 25.0

# PRD 3.5 — string testing
IR_MIN_MOHM = 40.0
MODULE_VOC_STC_V = 49.50
VOC_TEMP_COEFF_PER_C = -0.0028
STC_TEMP_C = 25
VOC_TOLERANCE_PCT = 0.03

# PRD 3.6 — outage windows
OUTAGE_SWITCHING_BUFFER_MINUTES = 120

# PRD 3.7 — commissioning weather filters and corrections
MIN_IRRADIANCE_W_M2 = 600
MAX_WIND_M_S = 8.0
AMBIENT_MIN_C = -10
AMBIENT_MAX_C = 45
G_REF_W_M2 = 1000
CELL_TEMP_RISE_PER_W = 0.025
PMAX_TEMP_COEFF_PER_C = -0.0035
CAPACITY_PASS_RATIO = 0.98

# PRD 3.8 — prevailing wage and apprenticeship
PW_LD_RATE = 0.20
DEFAULT_APPRENTICE_MIN_PCT = 15.00

# PRD 3.9 — settlement
PUNCH_HOLDBACK_MULTIPLIER = 1.5

# Role names of PRD 2.1
ROLE_EPC_PROJECT_MANAGER = "EpcProjectManager"
ROLE_CIVIL_SUPERINTENDENT = "CivilSuperintendent"
ROLE_PROCUREMENT_COORDINATOR = "ProcurementCoordinator"
ROLE_INSTALLATION_FOREMAN = "InstallationForeman"
ROLE_UTILITY_COORDINATOR = "UtilityCoordinator"
ROLE_COMMISSIONING_ENGINEER = "CommissioningEngineer"
ROLE_OWNER_ENGINEER = "OwnerEngineer"
ROLE_LABOR_COMPLIANCE_OFFICER = "LaborComplianceOfficer"

ALL_ROLES = (
    ROLE_EPC_PROJECT_MANAGER,
    ROLE_CIVIL_SUPERINTENDENT,
    ROLE_PROCUREMENT_COORDINATOR,
    ROLE_INSTALLATION_FOREMAN,
    ROLE_UTILITY_COORDINATOR,
    ROLE_COMMISSIONING_ENGINEER,
    ROLE_OWNER_ENGINEER,
    ROLE_LABOR_COMPLIANCE_OFFICER,
)

# The commercial baseline every scenario in the design indices is written
# against, so a computed figure asserted in one test is the same figure in the
# next.
BASE_PROJECT = {
    "ac_capacity_kw": 100,
    "dc_capacity_kw": 130,
    "contract_value_cents": 10000000,
    "retainage_pct": 0.05,
    "ld_per_day_cents": 50000,
    "ld_cap_pct": 0.05,
    "sc_deadline_date": "2026-08-01",
    "guaranteed_capacity_kw_ac": 100,
    "guaranteed_performance_ratio": 0.69,
}
