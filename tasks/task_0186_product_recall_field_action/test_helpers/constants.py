"""Domain thresholds — numeric constants from the PRD's calculation rules.

Sourced from PRD Sections 2.9, 3.3, 3.10, 3.11. Generic NON_EXISTENT_UUID
comes from the framework.
"""

# Notification window hours by (classification, regulator, injury) — PRD §3.3.
NOTIFICATION_WINDOW = {
    "CLASS_I_HOURS": 24,
    "CLASS_II_FDA_HOURS": 72,
    "CLASS_II_CPSC_HOURS": 120,
    "CLASS_III_HOURS": 240,
    "CPSC_INJURY_FASTTRACK_HOURS": 24,
}

# Effectiveness target percentages by classification — PRD §3.11.
EFFECTIVENESS_TARGET_PCT = {
    "CLASS_I": 90,
    "CLASS_II": 60,
    "CLASS_III": 30,
}

# Class I goodwill premium multiplier on refunds — PRD §3.10.
CLASS_I_GOODWILL_MULTIPLIER = 1.10

# A syntactically valid UUID that resolves to no resource (for 404 probes).
NON_EXISTENT_RECALL_UUID = "00000000-0000-4000-8000-000000000000"
