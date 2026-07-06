"""Domain thresholds — numeric constants drawn from the PRD's calculations."""

# Double-Up match ceiling per customer, in cents (PRD §3.6: "the Double-Up cap of 2000 cents ($20)").
DOUBLEUP_CAP_CENTS = 2000

# Size-based subscription box target values in cents (PRD §3.4).
BOX_TARGET_CENTS = {
    "SMALL": 1500,
    "MEDIUM": 3000,
    "LARGE": 6000,
}

# Same-region market-cycle window separation buffer in hours (PRD §3.2).
CYCLE_BUFFER_HOURS = 24

# A syntactically valid UUID that is never minted by the server, for not-found probes.
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"
