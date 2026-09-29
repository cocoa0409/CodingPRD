"""Reusable ladder guards shared by the route modules."""

from datetime import timedelta

import calc
import derive
from core import (
    DB, acting_user, fail, now_clock, parse_date, parse_instant, rows,
)


def require_unique(collection, field, value, message=None):
    for row in DB[collection].values():
        if row.get(field) == value:
            fail("ERR_INVALID_REQUEST", message or "%s must be unique" % field)


# --- priority 11 -----------------------------------------------------------

def require_period_open(period):
    if period is None:
        return
    if period.get("status") != "OPEN":
        fail("ERR_PERIOD_LOCKED",
             "the fiscal period is %s" % period.get("status"))


def period_of(row):
    return DB["fiscal_periods"].get(row.get("fiscal_period_id"))


# --- priority 12 / 13 ------------------------------------------------------

def require_not_terminal(status, terminal_states, label="resource"):
    if status in terminal_states:
        fail("ERR_TERMINAL_STATE", "the %s is already %s" % (label, status))


def require_state(status, allowed, label="resource"):
    if status not in allowed:
        fail("ERR_INVALID_STATE", "the %s is %s" % (label, status))


# --- priority 19 -----------------------------------------------------------

def require_dual_control(*forbidden_user_ids):
    actor = acting_user()
    for forbidden in forbidden_user_ids:
        if forbidden is not None and actor == forbidden:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "the acting user may not also perform this step")


# --- priorities 20 to 23 ---------------------------------------------------

def require_funder_not_restricted(funder):
    if funder.get("status") == "RESTRICTED":
        fail("ERR_FUNDER_RESTRICTED", "the funder is RESTRICTED")


def require_funder_cleared(funder):
    if funder.get("status") != "CLEARED":
        fail("ERR_FUNDER_RESTRICTED", "the funder is not CLEARED")


def require_risk_below_hard_bar(score):
    if int(score) >= calc.RISK_HARD_BAR:
        fail("ERR_FUNDER_RISK_TOO_HIGH",
             "independence_risk_score %s is at or above the hard bar" % score)


def require_active_disclosure(funder_id, coverage_area_id):
    if coverage_area_id is None or derive.active_disclosure(funder_id, coverage_area_id) is None:
        fail("ERR_DISCLOSURE_REQUIRED",
             "an ACTIVE firewall disclosure is required for this funder and beat")


def require_no_stale_disclosure(funder_id, coverage_area_id=None):
    if derive.stale_disclosure(funder_id, coverage_area_id) is not None:
        fail("ERR_DISCLOSURE_STALE",
             "a firewall disclosure is awaiting re-attestation")


# --- priority 24 -----------------------------------------------------------

def require_publication_gate_open(coverage_area_id):
    area = DB["coverage_areas"].get(coverage_area_id) if coverage_area_id else None
    if area is None or area.get("publication_gate") != "OPEN":
        fail("ERR_PUBLICATION_GATE_BLOCKED",
             "the beat's publication gate is not OPEN")


# --- priority 34 -----------------------------------------------------------

def require_cooling_off(proposal, funder):
    """Thirty days must have elapsed since the funder was last restricted, and
    no other SUBMITTED or AWARDED proposal of this funder may carry a
    restriction window falling within thirty days of this one."""
    restricted_at = parse_instant(funder.get("restricted_at"))
    if restricted_at is not None:
        if now_clock() < restricted_at + timedelta(days=calc.COOLING_OFF_DAYS):
            fail("ERR_FUNDER_COOLING_OFF_VIOLATION",
                 "the funder cooling-off window has not elapsed")
    start = parse_date(proposal.get("restriction_start_date"))
    end = parse_date(proposal.get("restriction_end_date"))
    if start is None or end is None:
        return
    for other in rows("grant_proposals"):
        if other["id"] == proposal["id"]:
            continue
        if other.get("funder_id") != funder["id"]:
            continue
        if other.get("status") not in ("SUBMITTED", "AWARDED"):
            continue
        other_start = parse_date(other.get("restriction_start_date"))
        other_end = parse_date(other.get("restriction_end_date"))
        if calc.windows_within_days(start, end, other_start, other_end,
                                    calc.COOLING_OFF_DAYS):
            fail("ERR_FUNDER_COOLING_OFF_VIOLATION",
                 "another proposal of this funder sits inside the cooling-off window")
