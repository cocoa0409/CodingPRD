"""Domain thresholds and shared narrative fixtures from the PRD."""

# PRD §2.5: the logical clock starts here at server startup.
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# PRD §2.6 customer risk rating constants.
RISK_BASE = 100
RISK_SAR_POINTS = 250
RISK_LE_INQUIRY_POINTS = 150
RISK_EXITED_ACCOUNT_POINTS = 400
RISK_TIER_PROHIBITED = 700
RISK_TIER_HIGH = 400
RISK_TIER_MEDIUM = 200

# PRD §3.10 QA sampling quota constants.
QA_SAMPLE_RATE = 0.34
QA_MIN_SAMPLE = 1
QA_MAX_SAMPLE = 25

# PRD §2.8 / §3.6 timing constants (days).
INITIAL_FILING_DAYS = 30
UNIDENTIFIED_EXTENSION_DAYS = 30
CONTINUING_REVIEW_DAYS = 90
CONTINUING_FILING_DAYS = 120

# PRD §2.5 / §3.2 / §3.8 operational timing constants (days).
STALE_ALERT_DAYS_DEFAULT = 30
SHARE_EXPIRY_DAYS = 30
SHARE_DUPLICATE_BUFFER_DAYS = 90
CERTIFICATION_VALIDITY_DAYS = 365
SAR_FILINGS_WINDOW_DAYS = 365

# PRD §3.5: minimum narrative length for QA submission.
NARRATIVE_MIN_LENGTH = 500

# Standard SAR narrative used across workflow fixtures (exactly 640 chars).
NARRATIVE_STANDARD = (
    "Narrative: Between 2026-03-10 and 2026-04-10 the subject account received "
    "a pattern of cash deposits in amounts between 300000 and 500000 cents, each "
    "below the 1000000-cent reporting threshold, aggregating 1300000 cents across "
    "three branch and ATM visits within seven days. The customer could not explain "
    "the source of funds when contacted, the stated occupation is inconsistent "
    "with cash-intensive activity, and the deposits were followed by rapid "
    "transfers out of the account. This activity is consistent with structuring "
    "designed to evade currency transaction reporting requirements under 31 USC "
    "5324 and is being reported as suspicious."
)

# Reworked narrative used after a QA FAIL round-trip (726 chars).
NARRATIVE_REWORKED = (
    "Narrative (reworked): Between 2026-03-10 and 2026-04-10 the subject account "
    "received a pattern of cash deposits in amounts between 300000 and 500000 "
    "cents, each below the 1000000-cent reporting threshold, aggregating 1300000 "
    "cents across three branch and ATM visits within seven days. The customer "
    "could not explain the source of funds when contacted, the stated occupation "
    "is inconsistent with cash-intensive activity, and the deposits were followed "
    "by rapid transfers out of the account. A review of prior filings confirms no "
    "earlier SAR exists for this subject. This activity is consistent with "
    "structuring designed to evade currency transaction reporting requirements "
    "under 31 USC 5324 and is being reported as suspicious."
)

# Continuing-activity narrative for a second SAR in a chain (639 chars).
NARRATIVE_CONTINUING = (
    "Narrative: Continuing activity review found that between 2026-04-11 and "
    "2026-05-01 the subject account again received structured cash deposits below "
    "the reporting threshold, aggregating 900000 cents across four visits, "
    "demonstrating that the suspicious activity reported in the initial SAR of "
    "2026-05-05 has continued despite the earlier filing. The pattern, amounts, "
    "and branches match the previously reported activity, the customer remains "
    "unable to document the source of funds, and the funds continue to move out "
    "within days of deposit. This continuing-activity SAR is filed under the "
    "90-day review cycle requirement of 31 USC 5318(g)."
)

# Continuing-activity narrative used when probing the closed activity window (577 chars).
NARRATIVE_WINDOW_PROBE = (
    "Narrative: Continuing activity review found that the structuring pattern "
    "reported in the initial SAR persisted into the next review period, with "
    "additional cash deposits below the reporting threshold aggregating 900000 "
    "cents. The window recorded here intentionally starts one day earlier than "
    "standard, on the final day of the previously reported period, to test "
    "closed-interval window enforcement. All other facts mirror the initial "
    "filing: same branches, same amounts, same unexplained source of funds, and "
    "the same rapid onward movement of funds within days of each deposit."
)

# Deliberately short narrative (100 chars) below the QA-submission minimum.
NARRATIVE_SHORT = (
    "Subject moved cash in small amounts. Source of funds unknown. "
    "Pattern looks like structuring. Filed."
)

# Text used by a stale-writer overwrite attempt; must never be stored.
NARRATIVE_STALE_ATTEMPT = (
    "Stale overwrite attempt with different text that must not be stored anywhere at all."
)
