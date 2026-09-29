"""Member-level derivations (PRD sections 3.1 and 3.8)."""

import calc
from db import db, ordered


def apply_phase_schedule(member):
    """Re-derive distribution_phase_bps and voting_weight_bps in place."""
    conference = db.conference
    phase_schedule_years = conference["phase_schedule_years"] if conference else 3
    distribution_bps, voting_bps = calc.phase_schedule(
        member["status"], member["phase_year"], phase_schedule_years
    )
    member["distribution_phase_bps"] = distribution_bps
    member["voting_weight_bps"] = voting_bps


def conference_members(conference_id=None):
    members = list(db.members.values())
    if conference_id is not None:
        members = [m for m in members if m["conference_id"] == conference_id]
    return ordered(members)


def eligible_voting_weight_bps(conference_id=None):
    """PRD section 3.2: sum of positive voting weights, snapshotted at close."""
    total = 0
    for member in conference_members(conference_id):
        if member["voting_weight_bps"] > 0:
            total += member["voting_weight_bps"]
    return total


def has_any_voter(conference_id=None):
    for member in conference_members(conference_id):
        if member["voting_weight_bps"] > 0:
            return True
    return False


def validated_unit_count(member_id, fiscal_year=None, window=None):
    count = 0
    for unit in db.postseason_units.values():
        if unit["member_id"] != member_id or unit["status"] != "VALIDATED":
            continue
        if fiscal_year is not None and unit["fiscal_year"] != fiscal_year:
            continue
        if window is not None and not (window[0] <= unit["fiscal_year"] <= window[1]):
            continue
        count += 1
    return count
