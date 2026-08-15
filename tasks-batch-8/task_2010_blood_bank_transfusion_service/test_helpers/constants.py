"""Domain thresholds — numeric constants named in the PRD narratives."""

# Logical clock (PRD logical-clock section)
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
BASE_NOW = "2026-08-10T09:00:00Z"

# Class shelf lives in hours (PRD unit-intake section)
CLASS_SHELF_HOURS = {
    "RBC": 1008,
    "WHOLE_BLOOD": 840,
    "PLT_APHERESIS": 120,
    "PLT_POOL": 120,
    "FFP": 8760,
    "CRYO": 8760,
}
THAWED_FFP_HOURS = 24
THAWED_CRYO_HOURS = 6
POOLED_PLT_HOURS = 4

# Specimen / reservation / bedside windows (PRD narratives)
TS_VALIDITY_HOURS = 72
XM_HOLD_HOURS = 72
TRANSFUSION_START_WINDOW_HOURS = 4
EMERGENCY_ACK_WINDOW_HOURS = 24
RETURN_RESTOCK_WINDOW_MINUTES = 30

# Cooler scheduling (PRD transport-cooler section)
COOLER_REDISPATCH_BUFFER_MINUTES = 60
CHECKOUT_MAX_DURATION_HOURS = 12

# Posture / prospective horizon / wastage (PRD posture and wastage sections)
INBOUND_HORIZON_HOURS = 24
DEFAULT_MIN_SHELF_HOURS = 4
WASTAGE_WINDOW_DAYS = 30
EXCESSIVE_WASTAGE_RATE = 0.05

# Supplier-order pricing (PRD replenishment section; integer cents)
PRICE_CENTS = {
    "RBC": 21997,
    "WHOLE_BLOOD": 34995,
    "PLT_APHERESIS": 54995,
    "PLT_POOL": 47995,
    "FFP": 7995,
    "CRYO": 6495,
}
TIER2_QTY = 50      # >= 50 units: 10% discount
TIER1_QTY = 20      # >= 20 units: 5% discount
TIER2_DISCOUNT = 0.10
TIER1_DISCOUNT = 0.05
EMERGENCY_SURCHARGE = 1.25

# Protocol pack constitution (PRD massive-transfusion-protocol section)
PACK_SPEC = [
    {"product_type": "RBC", "qty": 4},
    {"product_type": "FFP", "qty": 2},
    {"product_type": "PLT_APHERESIS", "qty": 1},
]

# The twelve-antigen panel (PRD vocabulary section)
ANTIGEN_PANEL = ["K", "k", "C", "c", "E", "e", "Jka", "Jkb", "Fya", "Fyb", "S", "s"]

# Named operator identifiers used across setup chains (opaque identities —
# the PRD never ties X-User-ID to a persisted entity id).
TECH_A_ID = "tech-a"
TECH_B_ID = "tech-b"
TECH_C_ID = "tech-c"
DOC_1_ID = "doc-1"
DOC_2_ID = "doc-2"
SUPERVISOR_ID = "sup-1"
COORDINATOR_ID = "coord-1"
QO_1_ID = "qo-1"
QO_2_ID = "qo-2"
