"""Domain thresholds — numeric constants from PRD calculations (§2.7-§2.10, §3)."""

# Logical clock startup default (PRD §2.4)
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# cvi_issuance_fee constants (PRD §3.4)
FEE_BASE_CENTS = 2500
FEE_CAP_CENTS = 20000
MONITORED_SURCHARGE_CENTS = 1000
PER_HEAD_RATE_CENTS = {
    "CATTLE": 150,
    "SWINE": 90,
    "POULTRY": 25,
    "SHEEP_GOAT": 60,
    "EQUINE": 200,
}

# movement_fee_reconciliation constants (PRD §3.5) — fractional cents per head
PER_HEAD_MOVEMENT_RATE_CENTS = {
    "CATTLE": 137.5,
    "SWINE": 62.5,
    "POULTRY": 10.25,
    "SHEEP_GOAT": 45.5,
    "EQUINE": 210.75,
}

# certificate_validity_window (PRD §2.9)
CVI_VALIDITY_DAYS = 30

# Auto-quarantine window after a POSITIVE test (PRD §3.2): clock + 30 days
AUTO_QUARANTINE_DAYS = 30

# Quarantine minimum re-gap after a LIFTED/EXPIRED order (PRD §3.7)
QUARANTINE_MIN_GAP_DAYS = 14


def expected_cvi_fee_cents(species_code: str, head_count: int, monitored: bool) -> int:
    """Provisional/final issuance fee per PRD §3.4:
    min(FEE_CAP, BASE + rate*head + (MONITORED surcharge if applicable))."""
    raw = (
        FEE_BASE_CENTS
        + PER_HEAD_RATE_CENTS[species_code] * head_count
        + (MONITORED_SURCHARGE_CENTS if monitored else 0)
    )
    return min(FEE_CAP_CENTS, raw)


def expected_movement_fee_cents(species_code: str, head_count: int) -> int:
    """Per-line movement fee per PRD §2.7/§3.5: round_half_up(head * rate)."""
    from decimal import ROUND_HALF_UP, Decimal

    rate = Decimal(str(PER_HEAD_MOVEMENT_RATE_CENTS[species_code]))
    product = rate * Decimal(head_count)
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
