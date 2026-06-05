"""Domain thresholds — numeric constants from the Warehouse Management PRD.

NON_EXISTENT_UUID comes from the framework (re-exported via __init__).
"""

# ABC cycle-count cadence in whole days (PRD 3.10). A SKU is due when elapsed
# whole days since its last reconcile are at least the cadence (boundary inclusive).
CADENCE_DAYS = {
    "A": 30,
    "B": 60,
    "C": 90,
}
