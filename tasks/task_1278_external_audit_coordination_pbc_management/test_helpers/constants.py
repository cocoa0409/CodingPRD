"""Domain thresholds and shared test constants (PRD §2.8, §3).

The logical clock boots pinned at 2026-08-01T00:00:00Z (PRD §2.8); fixture
dates sit at or after that instant.
"""

BOOT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Valid 64-char lowercase hex sha256 stand-ins (PRD §3.2 hash format).
VALID_SHA256_A = "a" * 64
VALID_SHA256_B = "b" * 64
VALID_SHA256_C = "c" * 64

TEST_DEFAULTS = {
    "CLIENT_NAME": "TestClient Co",
    "FISCAL_YEAR_END": "2026-06-30",
    "BASE_FEE_CENTS": 800_000,
    "MATERIALITY_CENTS": 100_000,
    "LOCATION_MATERIALITY_CENTS": 50_000,
    "FILING_DEADLINE": "2026-12-31",
    "PBC_DUE_DATE": "2026-11-30",
    "PBC_OWNER": "prep1",
    "PBC_TITLE": "Trial balance",
    "EVIDENCE_FILE_NAME": "evidence.pdf",
    "EVIDENCE_FILE_SIZE_BYTES": 1024,
    "QUERY_SUBJECT": "Revenue recognition",
    "QUERY_SEVERITY": "LOW",
    "SAMPLING_TITLE": "Sampling round 1",
    "SAMPLING_WINDOW_START": "2026-09-01",
    "SAMPLING_WINDOW_END": "2026-09-15",
    "SAMPLE_SIZE": 5,
    "VISIT_AUDITOR": "aud1",
    "VISIT_START": "2026-09-01",
    "VISIT_END": "2026-09-10",
    "ADJUSTMENT_DESCRIPTION": "Revenue cutoff",
    "ADJUSTMENT_AMOUNT_CENTS": 5_000,
    "ADJUSTMENT_DIRECTION": "DEBIT",
    "FEE_SCOPE_DESCRIPTION": "Extra subsidiary scope",
    "FEE_DELTA_CENTS": 50_000,
    # Users involved in segregation-of-duties flows (PRD §3.8).
    "REP_PREPARER_USER": "prep_a",
    "REP_SIGNER_USER": "ctrl_b",
}
