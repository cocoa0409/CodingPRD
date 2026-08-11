"""Domain thresholds — numeric constants from the PRD's calculation rules (§2.7-§3)."""

THRESHOLDS = {
    # Progressive matrix / sanction determination (PRD §3.2, §3.3)
    "OCCURRENCE_WINDOW_DAYS": 365,     # rolling lookback for occurrence_index
    "BAND_CAP_INDEX": 3,               # matrix lookup clamps index to at most 3
    "SUSPENSION_CAP_DAYS": 10,         # absolute per-sanction cap
    "MDR_THRESHOLD_DAYS": 10,          # strict-greater cumulative trigger
    "MDR_DUE_DAYS": 10,                # determination completion window
    # Due-process windows (PRD §3.4, §3.5)
    "NOTICE_WINDOW_DAYS": 1,           # notice within 1 day of proposal
    "CONFERENCE_DEADLINE_DAYS": 3,     # conference_deadline = issued_at + 3 days
    "APPEAL_WINDOW_DAYS": 5,           # appeal_deadline = issued_at + 5 days
    "CONFERENCE_ATTEMPT_CAP": 2,       # hard cap on conference attempts
    "HEARING_WINDOW_DAYS": 10,         # hearing start <= referral + 10 days
    "EVIDENCE_LEAD_DAYS": 2,           # packet served <= start - 2 days
    # Expungement (PRD §3.8)
    "EXPUNGEMENT_WAIT_DAYS": 730,      # inclusive two-year wait
    # Disproportionality report rounding (PRD §2.10, §3.9)
    "RISK_DISPLAY_DECIMALS": 4,
    "RATIO_DECIMALS": 2,
    "SHARE_GAP_DECIMALS": 4,
}

TEST_DEFAULTS = {
    # Startup value of the logical clock (PRD §2.4)
    "CLOCK_START": "2026-05-01T00:00:00Z",
    "REFERRER_ID": "admin_ref_1",
    "CLASSIFIER_ID": "admin_adj_1",
    "DISTRICT_ADMIN_ID": "da_1",
    "DIRECTOR_ID": "ssd_1",
    "OFFICER_ID": "ho_1",
}
