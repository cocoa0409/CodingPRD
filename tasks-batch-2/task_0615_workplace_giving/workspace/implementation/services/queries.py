"""Cross-aggregate query helpers (consumption sums, year extraction, lookups)."""
from db import db, parse_iso


def program_of(record):
    return db.programs.get(record["program_id"])


def settled_year(donation):
    """Calendar year of donation.settled_at (UTC)."""
    if not donation.get("settled_at"):
        return None
    return parse_iso(donation["settled_at"]).year


def match_consumed_ytd(employee):
    """Sum matched_amount_cents over employee's MatchingGift in {FINALIZED,
    SETTLED} for the program tax_year (PRD §3.2)."""
    prog = db.programs.get(employee["program_id"])
    if prog is None:
        return 0
    tax_year = prog["tax_year"]
    total = 0
    for m in db.matching_gifts.values():
        if m["employee_id"] != employee["id"]:
            continue
        if m["status"] not in ("FINALIZED", "SETTLED"):
            continue
        donation = db.donations.get(m["donation_id"])
        # tax_year membership: the gift's matched amounts count for the program
        # tax_year. Consumption is per employee per tax_year; gifts under the
        # same program share that program's tax_year.
        total += m["matched_amount_cents"]
    return total


def dfd_consumed_ytd(employee):
    """Sum grant_amount_cents over employee's VolunteerLog in {APPROVED,
    SETTLED} for the program tax_year (PRD §3.2)."""
    total = 0
    for log in db.volunteer_logs.values():
        if log["employee_id"] != employee["id"]:
            continue
        if log["status"] not in ("APPROVED", "SETTLED"):
            continue
        total += log["grant_amount_cents"]
    return total


def grants_referencing_source(source_type, source_id, statuses):
    out = []
    for g in db.grants.values():
        if g["source_type"] == source_type and g["source_id"] == source_id and g["status"] in statuses:
            out.append(g)
    return out
