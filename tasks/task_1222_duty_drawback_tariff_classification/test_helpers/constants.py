"""Domain thresholds and pinned numeric constants from PRD 2.4 and 3."""

THRESHOLDS = {
    # PRD 2.4: the drawback refund rate is 99% of eligible duty (9900 bps).
    "REFUND_RATE_BPS": 9900,
    # PRD 3.7: the first tier spans the first 1000000 cents of recovery.
    "TIER1_CAP_CENTS": 1000000,
    # PRD 3.7: the second tier bills at 80% of the agreed rate (2000-bps discount).
    "TIER2_DISCOUNT_BPS": 2000,
    # PRD 3.7: the accrued variant applies an 80% realization haircut.
    "REALIZATION_BPS": 8000,
    # PRD 3.4: the statutory filing window is five years from the earliest entry.
    "FILING_WINDOW_YEARS": 5,
    # PRD 3.9: drawback records are retained for three years after payment.
    "RETENTION_YEARS": 3,
    # PRD 3.8 culpability rates in basis points.
    "CULPABILITY_NONE_BPS": 0,
    "CULPABILITY_NEGLIGENCE_BPS": 500,
    "CULPABILITY_GROSS_NEGLIGENCE_BPS": 2000,
    "CULPABILITY_FRAUD_BPS": 10000,
}

TEST_DEFAULTS = {
    # The logical clock before any set call (PRD 1).
    "CLOCK_DEFAULT": "2026-05-01T00:00:00Z",
    # Canonical fixture economics: entry duty 82500 over 100 units (unit 825);
    # a 40-unit direct line refunds round_half_up(0.99 * 825 * 40) = 32670.
    "ENTRY_DUTY_PAID_CENTS": 82500,
    "DIRECT_LINE_QTY40_CENTS": 32670,
    "SETTLED_FEE_ON_32670": 8168,
    "ACCRUED_FEE_ON_32670": 6534,
}
