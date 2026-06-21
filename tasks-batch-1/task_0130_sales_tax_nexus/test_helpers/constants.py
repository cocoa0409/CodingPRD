"""Domain constants used across the Sales Tax Nexus test suite.

These are the canonical reference-data values the design indices build on, plus
the derived expected results that the PRD's calculations pin exactly. Generic
NON_EXISTENT_UUID comes from the framework.
"""

# Canonical CA jurisdiction (DESTINATION-sourced) used throughout the indices.
CA_JURISDICTION = {
    "state_code": "CA",
    "sourcing_rule": "DESTINATION",
    "state_rate": 0.0725,
    "local_rate": 0.0100,
    "reduced_rate": 0.02,
    "economic_nexus_sales_threshold": 100000.00,
    "economic_nexus_txn_threshold": 0,
}
CA_COMBINED_RATE = 0.0825          # state_rate + local_rate
CA_REDUCED_RATE = 0.02

# Canonical TX jurisdiction (ORIGIN-sourced), combined 0.0625.
TX_JURISDICTION = {
    "state_code": "TX",
    "sourcing_rule": "ORIGIN",
    "state_rate": 0.0625,
    "local_rate": 0.0000,
    "reduced_rate": 0.00,
    "economic_nexus_sales_threshold": 500000.00,
    "economic_nexus_txn_threshold": 0,
}
TX_COMBINED_RATE = 0.0625

# Canonical NY jurisdiction with a transaction-count nexus threshold.
NY_JURISDICTION = {
    "state_code": "NY",
    "sourcing_rule": "DESTINATION",
    "state_rate": 0.08,
    "local_rate": 0.00,
    "reduced_rate": 0.00,
    "economic_nexus_sales_threshold": 99999999.00,
    "economic_nexus_txn_threshold": 3,
}
NY_COMBINED_RATE = 0.08

# Economic-nexus thresholds (the dollar/count breakpoints).
CA_SALES_THRESHOLD = 100000.00
NY_TXN_THRESHOLD = 3

# A standard non-existent UUID with valid v4 shape, used by the indices for
# reference-not-found scenarios.
NONEXISTENT_UUID_V4 = "00000000-0000-4000-8000-000000000000"
