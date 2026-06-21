"""Entity serializers — produce the public JSON view of each stored row.

Election turnout fields are computed on read (PRD §3.8): the stored counts
total_registered / total_ballots_accepted are kept fresh by recompute calls,
while turnout_pct / projected_turnout_pct are derived here per turnout_rate.
"""

from decimal import Decimal, ROUND_HALF_UP

import db

# Audit-bearing common fields (PRD §2.4).
_FULL_COMMON = ["id", "created_at", "updated_at", "version"]
# Lightweight immutable entities carry only id + created_at.
_LIGHT_COMMON = ["id", "created_at"]


def _round2(value):
    """Round to 2 dp half-up, returned as a float (e.g. 33.33)."""
    q = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def _turnout(election):
    eid = election["id"]
    total_registered = election.get("total_registered", 0)

    in_person = sum(
        1 for r in db.registrations.values()
        if r.get("election_id") == eid and r.get("early_voted_at") is not None
    )
    final_absentee = sum(
        1 for b in db.ballots.values()
        if b.get("election_id") == eid and b.get("request_status") == "ACCEPTED"
    )
    projected_absentee = sum(
        1 for b in db.ballots.values()
        if b.get("election_id") == eid
        and b.get("request_status") in ("RETURNED", "ACCEPTED")
    )
    if total_registered == 0:
        return 0.00, 0.00
    final_cast = final_absentee + in_person
    projected_cast = projected_absentee + in_person
    turnout_pct = _round2(Decimal(final_cast) / Decimal(total_registered) * 100)
    projected_pct = _round2(Decimal(projected_cast) / Decimal(total_registered) * 100)
    return turnout_pct, projected_pct


def election_view(e):
    out = {k: e[k] for k in _FULL_COMMON}
    out.update({
        "name": e["name"],
        "election_date": e["election_date"],
        "registration_deadline": e["registration_deadline"],
        "absentee_request_deadline": e["absentee_request_deadline"],
        "cure_deadline": e["cure_deadline"],
        "early_voting_start": e["early_voting_start"],
        "early_voting_end": e["early_voting_end"],
        "status": e["status"],
        "total_registered": e.get("total_registered", 0),
        "total_ballots_accepted": e.get("total_ballots_accepted", 0),
    })
    turnout_pct, projected_pct = _turnout(e)
    out["turnout_pct"] = turnout_pct
    out["projected_turnout_pct"] = projected_pct
    return out


def precinct_view(p):
    out = {k: p[k] for k in _FULL_COMMON}
    out.update({
        "election_id": p["election_id"],
        "code": p["code"],
        "county_fips": p["county_fips"],
        "street_low": p["street_low"],
        "street_high": p["street_high"],
        "max_registrations": p["max_registrations"],
        "assigned_count": p.get("assigned_count", 0),
        "capacity_posture": p.get("capacity_posture", "OPEN"),
        "tally_status": p["tally_status"],
        "reported_vote_count": p.get("reported_vote_count"),
        "tally_recorded_by_user_id": p.get("tally_recorded_by_user_id"),
    })
    return out


def registration_view(r):
    out = {k: r[k] for k in _FULL_COMMON}
    out.update({
        "election_id": r["election_id"],
        "precinct_id": r.get("precinct_id"),
        "first_name": r["first_name"],
        "last_name": r["last_name"],
        "national_id": r["national_id"],
        "is_citizen": r["is_citizen"],
        "date_of_birth": r["date_of_birth"],
        "county_fips": r["county_fips"],
        "street_number": r["street_number"],
        "party": r["party"],
        "early_voted_at": r.get("early_voted_at"),
        "status": r["status"],
        "reviewed_by_user_id": r.get("reviewed_by_user_id"),
    })
    return out


def ballot_view(b):
    out = {k: b[k] for k in _FULL_COMMON}
    out.update({
        "registration_id": b["registration_id"],
        "election_id": b.get("election_id"),
        "precinct_id": b.get("precinct_id"),
        "mailing_address": b["mailing_address"],
        "request_status": b["request_status"],
        "cure_status": b["cure_status"],
        "returned_at": b.get("returned_at"),
    })
    return out


def cure_case_view(c):
    out = {k: c[k] for k in _FULL_COMMON}
    out.update({
        "ballot_id": c["ballot_id"],
        "election_id": c.get("election_id"),
        "reason": c["reason"],
        "voter_response_text": c.get("voter_response_text"),
        "status": c["status"],
        "adjudicated_by_user_id": c.get("adjudicated_by_user_id"),
    })
    return out


def machine_view(m):
    out = {k: m[k] for k in _FULL_COMMON}
    out.update({
        "precinct_id": m["precinct_id"],
        "serial": m["serial"],
        "role": m["role"],
        "status": m["status"],
        "backup_for_machine_id": m.get("backup_for_machine_id"),
        "capacity": m["capacity"],
    })
    return out


def failure_view(f):
    out = {k: f[k] for k in _LIGHT_COMMON}
    out.update({
        "machine_id": f["machine_id"],
        "reported_at": f["reported_at"],
        "backup_machine_id": f.get("backup_machine_id"),
        "resolution": f["resolution"],
    })
    return out


def checkin_view(c):
    out = {k: c[k] for k in _LIGHT_COMMON}
    out.update({
        "registration_id": c["registration_id"],
        "precinct_id": c.get("precinct_id"),
        "checked_in_at": c["checked_in_at"],
    })
    return out


def recount_view(rc):
    out = {k: rc[k] for k in _FULL_COMMON}
    out.update({
        "election_id": rc["election_id"],
        "precinct_id": rc["precinct_id"],
        "original_count": rc.get("original_count"),
        "machine_recount": rc.get("machine_recount"),
        "hand_recount": rc.get("hand_recount"),
        "certified_count": rc.get("certified_count"),
        "status": rc["status"],
    })
    return out


def clock_view():
    return {"current_utc": db.current_utc_iso()}
