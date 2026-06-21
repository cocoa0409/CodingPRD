"""Boarding charge calculation (PRD §3.6, scaffold calculations.boarding_charge).

provisional (at DRAFT->ACTIVE): daily * BILLING_MONTH_DAYS (30); ignores suspensions
  and actual move-out.
final (at end): occupied_days = floor day-difference start_date (incl) -> end_date
  (excl); charged_days = occupied_days - suspended_days; final = daily * charged_days.
"""
from clock import parse_iso, whole_days_between

BILLING_MONTH_DAYS = 30


def provisional_charge(stall, agreement):
    return stall["daily_rate_cents"] * BILLING_MONTH_DAYS


def final_charge(stall, agreement):
    start = parse_iso(agreement["start_date"])
    end = parse_iso(agreement["end_date"])
    occupied_days = whole_days_between(start, end)
    charged_days = occupied_days - agreement["suspended_days"]
    return stall["daily_rate_cents"] * charged_days
