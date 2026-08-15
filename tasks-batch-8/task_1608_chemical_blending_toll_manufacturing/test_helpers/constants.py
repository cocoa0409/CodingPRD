"""Domain thresholds and lookup tables from the PRD (§2.5, §2.6, §3.5, §3.8)."""

# Logical clock startup default (PRD §2.5).
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Standard pricing-agreement window used by fixtures: covers the default clock.
DEFAULT_WINDOW_START = "2026-08-01T00:00:00Z"
DEFAULT_WINDOW_END = "2026-12-31T00:00:00Z"

# Cleaning acceptance limit in parts per million (PRD §2.6 / §3.5).
RESIDUE_LIMIT_PPM = 50

# DOT bulk-packaging placard threshold in litres (PRD §3.8).
PLACARD_VOLUME_THRESHOLD_L = 454

# Fixed package capacities in litres (PRD §3.8).
PACKAGE_CAPACITY_L = {
    "DRUM_205L": 205,
    "IBC_1000L": 1000,
    "TOTE_500L": 500,
    "PAIL_20L": 20,
}

# Zone -> the single GHS class it admits (PRD §2.6).
ZONE_ALLOWED = {
    "Z_FLAM": "FLAMMABLE",
    "Z_OXID": "OXIDIZER",
    "Z_ACID": "ACID",
    "Z_BASE": "BASE",
    "Z_TOXIC": "TOXIN",
    "Z_GENERAL": "NON_HAZ",
}

# Inverse of ZONE_ALLOWED: the zone that admits a given GHS class.
ZONE_FOR_GHS = {v: k for k, v in ZONE_ALLOWED.items()}

# Hazard severity order, most severe first (PRD §2.6).
SEVERITY_ORDER = ["FLAMMABLE", "OXIDIZER", "TOXIN", "ACID", "BASE", "NON_HAZ"]

# Forbidden co-location / sequential-use pairings (symmetric) (PRD §2.6).
INCOMPATIBLE_PAIRS = {
    frozenset({"FLAMMABLE", "OXIDIZER"}),
    frozenset({"ACID", "BASE"}),
    frozenset({"TOXIN", "FLAMMABLE"}),
    frozenset({"TOXIN", "OXIDIZER"}),
}

# GHS class -> DOT placard class mapping (PRD §3.8).
PLACARD_CLASS_FOR_GHS = {
    "FLAMMABLE": "CLASS_3_FLAMMABLE",
    "OXIDIZER": "CLASS_5_1_OXIDIZER",
    "TOXIN": "CLASS_6_1_TOXIC",
    "ACID": "CLASS_8_CORROSIVE",
    "BASE": "CLASS_8_CORROSIVE",
}

# Signal words consistent with a classification (PRD §3.7): DANGER for the
# three most severe classes, WARNING or NONE otherwise.
DANGER_SIGNAL_CLASSES = {"FLAMMABLE", "OXIDIZER", "TOXIN"}

# Batch statuses that count as in-flight (PRD §3.1 / §3.3).
IN_FLIGHT_BATCH_STATUSES = {"INTAKE", "RELEASED", "CHARGING", "MIXING", "HOLD_QA"}

# Terminal batch statuses (PRD §3.6).
TERMINAL_BATCH_STATUSES = {"COMPLETED", "CANCELLED", "REJECTED_QA"}
