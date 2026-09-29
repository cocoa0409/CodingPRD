"""Domain constants the specification pins by name or by number.

Everything here is quoted from the PRD rather than inferred: the six role
strings of section 2.1, the pagination bounds of section 2.3, the logical-clock
startup instant of section 2.4, the posture inputs of section 2.5, the
environmental limit tables of section 3.7, the component pack sizes of section
3.5 and the five fee steps of section 3.8.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLE_PROGRAM_MANAGER = "ProgramManager"
ROLE_PRODUCTION_SUPERVISOR = "ProductionSupervisor"
ROLE_MICROBIOLOGY_ANALYST = "MicrobiologyAnalyst"
ROLE_QA_REVIEWER = "QaReviewer"
ROLE_QUALIFIED_PERSON = "QualifiedPerson"
ROLE_CLIENT_REPRESENTATIVE = "ClientRepresentative"

ALL_ROLES: Tuple[str, ...] = (
    ROLE_PROGRAM_MANAGER,
    ROLE_PRODUCTION_SUPERVISOR,
    ROLE_MICROBIOLOGY_ANALYST,
    ROLE_QA_REVIEWER,
    ROLE_QUALIFIED_PERSON,
    ROLE_CLIENT_REPRESENTATIVE,
)

# The five CMO-side roles whose X-User-ID is an opaque operator identifier.
CMO_ROLES: Tuple[str, ...] = (
    ROLE_PROGRAM_MANAGER,
    ROLE_PRODUCTION_SUPERVISOR,
    ROLE_MICROBIOLOGY_ANALYST,
    ROLE_QA_REVIEWER,
    ROLE_QUALIFIED_PERSON,
)

# A role string that is not one of the six.
UNDECLARED_ROLE = "SterilityAssuranceDirector"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# The logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
# "The clock's startup value is exactly 2026-08-01T00:00:00Z".
CLOCK_STARTUP = "2026-08-01T00:00:00Z"
# The working instant every scenario in this suite is written against.
SCENARIO_CLOCK = "2026-09-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Suite posture (PRD 2.5)
# ---------------------------------------------------------------------------
POSTURE_OPEN = "OPEN"
POSTURE_RESTRICTED = "RESTRICTED"
POSTURE_FROZEN = "FROZEN"
# "The roster threshold is two effective operators".
QUALIFIED_OPERATOR_THRESHOLD = 2

# ---------------------------------------------------------------------------
# Suite qualification (PRD 3.2)
# ---------------------------------------------------------------------------
CLEANING_RESIDUE_LIMIT_UG = 100
MEDIA_FILL_MIN_UNITS = 5000
MEDIA_FILL_VALIDITY_DAYS = 183
# SCENARIO_CLOCK read-out plus 183 days.
MEDIA_FILL_VALID_UNTIL = "2027-03-03T00:00:00Z"

# ---------------------------------------------------------------------------
# Environmental monitoring limits (PRD 3.7), keyed grade -> sample type
# ---------------------------------------------------------------------------
EM_LIMITS: Dict[str, Dict[str, Tuple[int, int]]] = {
    "A": {
        "VIABLE_AIR": (1, 1),
        "SURFACE": (1, 1),
        "PERSONNEL_GLOVE": (1, 1),
    },
    "B": {
        "VIABLE_AIR": (5, 10),
        "SURFACE": (3, 5),
        "PERSONNEL_GLOVE": (1, 5),
    },
    "C": {
        "VIABLE_AIR": (50, 100),
        "SURFACE": (15, 25),
        "PERSONNEL_GLOVE": (5, 10),
    },
}

GRADE_WEIGHT: Dict[str, int] = {"A": 3, "B": 2, "C": 1}
SAMPLE_TYPE_SURCHARGE: Dict[str, int] = {
    "PERSONNEL_GLOVE": 25,
    "SURFACE": 10,
    "VIABLE_AIR": 0,
}
BATCH_EXPOSURE_POINTS = 20
RISK_INDEX_SCALE = 20
RISK_INDEX_CORE_CEILING = 100
RISK_INDEX_CAP = 150

# ---------------------------------------------------------------------------
# Deviation risk (PRD 3.7)
# ---------------------------------------------------------------------------
DEVIATION_BASE_POINTS: Dict[str, int] = {"MINOR": 5, "MAJOR": 20, "CRITICAL": 50}
DEVIATION_LINKAGE_BONUS = 15
DEVIATION_RISK_CAP = 120

# ---------------------------------------------------------------------------
# Component demand (PRD 3.5): overage fraction and vendor pack size per line
# ---------------------------------------------------------------------------
COMPONENT_LINES: Dict[str, List[Tuple[str, float, int]]] = {
    "VIAL": [("VIAL", 0.03, 480), ("STOPPER", 0.05, 1000)],
    "PRESYRINGE": [("SYRINGE", 0.03, 500), ("PLUNGER", 0.05, 1000)],
}
# "the standing initial-setup allowance of 60 minutes".
INITIAL_SETUP_MINUTES = 60
# The worked example of PRD 3.5 for a VIAL batch of 10000 containers.
WORKED_VIAL_LINE_UNITS = 10560
WORKED_STOPPER_LINE_UNITS = 11000
WORKED_COMPONENT_DEMAND_UNITS = 21560
FORBIDDEN_SUM_THEN_ROUND_DEMAND = 21000

# ---------------------------------------------------------------------------
# In-process control tolerances (PRD 3.6)
# ---------------------------------------------------------------------------
FILL_WEIGHT_ALERT_FLOOR = 0.0300
FILL_WEIGHT_FAIL_CEILING = 0.0500
VISUAL_AQL = 0.0250

# ---------------------------------------------------------------------------
# Release fee (PRD 3.8)
# ---------------------------------------------------------------------------
FEE_BASE_CENTS = 150000
FEE_PER_UNIT_CENTS = 40
DEVIATION_SURCHARGE_PCT: Dict[str, int] = {
    "NONE": 0,
    "MINOR": 5,
    "MAJOR": 12,
    "CRITICAL": 25,
}
# First matching tier against the pre-discount total.
FEE_DISCOUNT_TIERS: List[Tuple[int, int]] = [
    (2000000, 10),
    (1000000, 6),
    (500000, 3),
]
# The worked example of PRD 3.8 on 8274 units with one open MINOR deviation.
WORKED_FEE_SUBTOTAL_CENTS = 480960
WORKED_FEE_SURCHARGE_CENTS = 24048
WORKED_FEE_PRE_DISCOUNT_CENTS = 505008
WORKED_FEE_DISCOUNT_CENTS = 15150
WORKED_RELEASE_FEE_CENTS = 489858

# ---------------------------------------------------------------------------
# Readiness assessment (PRD 3.9)
# ---------------------------------------------------------------------------
READINESS_TECH_MAX = 30
READINESS_ANALYTICAL_MAX = 25
READINESS_ASEPTIC_MAX = 25
READINESS_OPERATOR_MAX = 20
READINESS_OPERATOR_THRESHOLD = 2
# The worked pair of PRD 3.9.
WORKED_INTAKE_FORECAST_SCORE = 100
WORKED_GMP_AUDIT_SCORE = 47

# ---------------------------------------------------------------------------
# Releasable units (PRD 3.8) worked pair
# ---------------------------------------------------------------------------
WORKED_FILLED_UNIT_COUNT = 8500
WORKED_EXPECTED_REJECT_UNITS = 22
WORKED_ACTUAL_VISUAL_REJECT_UNITS = 166
WORKED_DESTRUCTIVE_TOTAL_UNITS = 60
WORKED_PROVISIONAL_RELEASABLE_UNITS = 8418
WORKED_FINAL_RELEASABLE_UNITS = 8274
WORKED_VARIANT_DELTA_UNITS = 144
