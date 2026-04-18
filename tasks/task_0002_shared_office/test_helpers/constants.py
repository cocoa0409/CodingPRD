"""Domain thresholds and constants for the Shared Office API.

Numeric constants quoted from PRD:
  - PRD §2.9: tax rate 0.0825, late-fee weekly rate 0.015.
  - PRD §3.1: default credit_limit_cents = 500_000.
  - PRD §3.3: workstation-daily constant = 8 hours/day; overstay block rate = 500
    cents per started 30-minute block; meeting-room round unit = 0.5 hour; event-area
    block = 4 hours; event-area weekend discount halves the gross.
  - PRD §3.3 / §3.4: check-in grace window is 15 minutes; visitor check-in window
    starts 30 minutes before expected_arrival_at and ends 6 hours after
    expected_departure_at.
  - PRD §3.6: penalty factor = 0.3 of monthly_rate_cents * remaining_full_months.
  - PRD §3.7: due_at = issued_at + 14 days; overdue-frozen threshold is strictly
    more than 30 days past due_at.
  - PRD §2.3: pagination limit in [1, 100], offset >= 0.
"""


THRESHOLDS = {
    # PRD §2.9: tax rate.
    "TAX_RATE": 0.0825,
    # PRD §2.9 / §3.7: late-fee weekly rate.
    "LATE_FEE_RATE_PER_WEEK": 0.015,
    # PRD §3.1: default credit limit when the caller omits it.
    "DEFAULT_CREDIT_LIMIT_CENTS": 500_000,
    # PRD §3.3: meeting-room rounding unit in hours.
    "MEETING_ROOM_ROUND_UNIT_HOURS": 0.5,
    # PRD §3.3: workstation-daily hours-per-day constant.
    "WORKSTATION_DAILY_HOURS_PER_DAY": 8,
    # PRD §3.3: event-area block length.
    "EVENT_AREA_BLOCK_HOURS": 4,
    # PRD §3.4: overstay rate per started 30-minute block (5.00 dollars in cents).
    "OVERSTAY_RATE_CENTS_PER_30MIN": 500,
    # PRD §3.6: penalty factor for MONTHLY termination.
    "PENALTY_FACTOR": 0.3,
    # PRD §3.7: due_at offset.
    "DUE_AT_OFFSET_DAYS": 14,
    # PRD §3.3: reservation check-in grace window.
    "CHECKIN_GRACE_MINUTES_BEFORE_START": 15,
    # PRD §3.4: visitor check-in early grace.
    "VISITOR_EARLY_GRACE_MINUTES": 30,
    # PRD §3.4: visitor late grace (expected_departure_at + 6h).
    "VISITOR_LATE_GRACE_HOURS": 6,
    # PRD §2.10: strictly more than 30 days overdue makes posture FROZEN.
    "OVERDUE_FROZEN_DAYS": 30,
    # PRD §2.3: pagination bounds.
    "PAGINATION_MIN_LIMIT": 1,
    "PAGINATION_MAX_LIMIT": 100,
    "PAGINATION_DEFAULT_LIMIT": 10,
}


# Convenience defaults used by the factories — not numeric contract thresholds.
TEST_DEFAULTS = {
    "TENANT_LEGAL_NAME": "Acme Shared Office Tenant",
    "MEMBER_FULL_NAME": "Test Member",
    "TENANT_CREDIT_LIMIT_CENTS": 500_000,
    "RESOURCE_CAPACITY": 4,
    "WORKSTATION_HOURLY_RATE_CENTS": 800,
    "WORKSTATION_DAILY_RATE_CENTS": 5000,
    "MEETING_ROOM_HOURLY_RATE_CENTS": 991,
    "EVENT_AREA_BLOCK_RATE_CENTS": 10_000,
    "LEASE_MONTHLY_RATE_CENTS": 90_000,
}
