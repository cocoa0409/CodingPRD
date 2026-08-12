"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Regulatory rate floor: 80.00% of Medicare benchmark (PRD §3.4)
    "SAFETY_FLOOR_BPS": 8000,
    # Simulation pass threshold: 75.00% (PRD §3.6)
    "PASS_THRESHOLD_BPS": 7500,
    # Case-rate outlier: threshold 3.0x base, share 80% (PRD §3.6)
    "OUTLIER_THRESHOLD_BPS": 30000,
    "OUTLIER_SHARE_BPS": 8000,
    # Continuity of care max days (PRD §3.9)
    "COC_MAX_DAYS": 90,
    # Notice minimum days (PRD §3.9)
    "NOTICE_MIN_DAYS": 90,
    # Basis-point denominator
    "BPS_DENOMINATOR": 10000,
}

TEST_DEFAULTS = {
    "LOCALITY_CODE": "L01",
    "NETWORK_NAME": "PPO-NET",
    "NETWORK_LOB": "COMMERCIAL_PPO",
    "PROVIDER_NAME": "Prov A",
    "PROVIDER_TIN": "TIN-A",
    "PROVIDER_NPI": "NPI-A",
    "BASE_EFFECTIVE_DATE": "2026-07-01",
    "TERM_MONTHS": 36,
    "ESCALATOR_BPS": 0,
    "ESCALATOR_MODE": "ANNIVERSARY",
    "HCPCS_CODE": "99213",
    "SERVICE_CATEGORY": "OFFICE_VISIT",
    "BENCHMARK_YEAR": 2026,
    "BENCHMARK_CENTS": 10000,
    "VERSION_EFFECTIVE_DATE": "2026-07-01",
    # Submitter / signer for the segregation-of-duties flow
    "SUBMITTER_USER_ID": "cm-1",
    "SIGNER_USER_ID": "cl-1",
    # Default logical clock (PRD §2.6)
    "DEFAULT_CLOCK": "2026-05-01T00:00:00Z",
}
