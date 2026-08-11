"""Domain thresholds — numeric constants from PRD calculations (§2.4, §3)."""

THRESHOLDS = {
    # Logical clock (PRD §2.4)
    "DEFAULT_CLOCK": "2026-05-01T00:00:00Z",
    # Registration fee tiers (PRD §3.2)
    "TIER1_LIMIT_CENTS": 50000,
    "TIER1_FEE_CENTS": 1000,
    "TIER2_LIMIT_CENTS": 200000,
    "TIER2_FEE_CENTS": 2000,
    "TIER3_FEE_CENTS": 3500,
    "ENGRAVING_FEE_CENTS": 1500,
    # Duplicate confidence auto-flag threshold (PRD §3.2)
    "AUTO_FLAG_THRESHOLD_BP": 8500,
    # Match notify threshold (PRD §3.5)
    "NOTIFY_THRESHOLD_BP": 7000,
    # Transfers (PRD §3.3)
    "TRANSFER_FEE_CENTS": 300,
    "TRANSFER_EXPIRY_DAYS": 7,
    # Disposition wait (PRD §3.7)
    "DISPOSITION_WAIT_DAYS": 30,
    # Storage accrual (PRD §3.7)
    "STORAGE_FREE_DAYS": 5,
    "STORAGE_RATE_CENTS_PER_DAY": 150,
    # Auction reserve / waterfall (PRD §3.7)
    "MIN_RESERVE_CENTS": 1000,
    "COMMISSION_TIER1_LIMIT_CENTS": 50000,
    # Bid increment (PRD §3.7)
    "MIN_INCREMENT_FLOOR_CENTS": 500,
    # Auction window inflation buffer (PRD §3.7)
    "AUCTION_BUFFER_HOURS": 12,
}
