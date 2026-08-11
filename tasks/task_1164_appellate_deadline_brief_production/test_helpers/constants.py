"""Domain thresholds and defaults — numeric constants named by the PRD."""

THRESHOLDS = {
    # PRD §3.4: briefing-schedule windows (court rules carry defaults)
    "DEFAULT_OPENING_DAYS": 40,
    "DEFAULT_RESPONSE_DAYS": 30,
    # PRD §3.3: transcript delivery window, thirty days by default
    "TRANSCRIPT_DELIVERY_DAYS": 30,
    # PRD §3.7: minimum argument notice, fourteen days by default
    "ARGUMENT_NOTICE_DAYS": 14,
    # PRD §3.8: rehearing / certiorari windows
    "FEDERAL_REHEARING_WINDOW_DAYS": 14,
    "STATE_REHEARING_WINDOW_DAYS": 30,
    "CERT_WINDOW_DAYS": 90,
    # PRD §2.3: pagination bounds
    "PAGINATION_DEFAULT_LIMIT": 10,
    "PAGINATION_MIN_LIMIT": 1,
    "PAGINATION_MAX_LIMIT": 100,
}

TEST_DEFAULTS = {
    # PRD §2.5: boot-time logical clock
    "BOOT_CLOCK": "2026-05-01T00:00:00Z",
    "JUDGMENT_ENTERED_AT": "2026-05-02T00:00:00Z",
    "HEARING_DATE": "2026-04-01T10:00:00Z",
    "SERVED_EMAILS": ["opposing.counsel@example.com"],
    "BRIEF_PAGE_COUNT": 5,
    "BRIEF_WORD_COUNT": 1000,
    "ESTIMATED_PAGES": 5,
    "COURT_ADMIN_ID": "test-court-admin-1",
    "COURT_CLERK_ID": "test-court-clerk-1",
    "PARALEGAL_ID": "test-paralegal-1",
}
