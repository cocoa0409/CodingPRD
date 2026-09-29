"""Mentor-match proposal, auto-selection ranking and disposition."""

from flask import Blueprint

import calc
import cascades
import domain
from auth import (ADMIN, LEAD, MENTOR, NOVICE, guard, own_match, own_site,
                  role, scope_rows)
from envelope import list_response, pagination, row_response
from errors import ApiError
from store import INITIAL_CLOCK, db, iso, new_row, now, parse_iso, sorted_rows, touch
from validators import (apply_filters, body, enum_field, fk, int_field,
                        path_row, str_field)

bp = Blueprint("matching", __name__)


def _candidates(novice):
    out = []
    for mentor in sorted_rows(list(db.mentors.values())):
        if mentor.get("certification_status") != "CERTIFIED":
            continue
        if mentor.get("site_id") != novice.get("site_id"):
            continue
        if int(mentor.get("active_caseload_count") or 0) >= int(mentor.get("caseload_cap") or 0):
            continue
        site = db.sites.get(mentor.get("site_id"))
        if site is None or site.get("status") != "OPEN":
            continue
        clash = False
        for match in domain.matches_of_mentor(mentor["id"]):
            if (match.get("novice_id") == novice["id"]
                    and match.get("match_status") in domain.LIVE_MATCH_STATES):
                clash = True
                break
        if clash:
            continue
        out.append(mentor)
    return out


def _rank_key(mentor, novice):
    tier = calc.subject_tier(novice.get("subject_area"), mentor.get("subject_endorsements"))
    expires = parse_iso(mentor.get("certification_expires_on")) or INITIAL_CLOCK
    return (
        calc.tier_rank(tier),
        int(mentor.get("active_caseload_count") or 0),
        -expires.timestamp(),
        mentor.get("_created") or INITIAL_CLOCK,
        mentor.get("_seq") or 0,
    )


def _select(novice):
    pool = _candidates(novice)
    if not pool:
        return None
    return sorted(pool, key=lambda m: _rank_key(m, novice))[0]


@bp.post("/mentor-matches")
@guard([ADMIN, LEAD])
def propose_match():
    data = body()
    novice = fk("novices", data, "novice_id")
    explicit = fk("mentors", data, "mentor_id")
    str_field(data, "novice_id", 1, None)
    expected = int_field(data, "expected_mentor_version")
    str_field(data, "mentor_id", 1, None, required=False)
    if role() == LEAD:
        own_site(novice.get("site_id"))

    site = db.sites.get(novice.get("site_id"))
    if site is None or site.get("status") != "OPEN":
        raise ApiError("ERR_SITE_CLOSED")
    if novice.get("program_status") not in ("ENROLLED", "MATCHED"):
        raise ApiError("ERR_NOVICE_PROGRAM_STATE_INVALID")

    selection_mode = "EXPLICIT" if explicit is not None else "AUTO_SELECTED"
    mentor = explicit if explicit is not None else _select(novice)

    if mentor is not None and int(mentor.get("version") or 0) != expected:
        raise ApiError("ERR_STALE_PARENT_VERSION")

    if explicit is not None and explicit.get("site_id") != novice.get("site_id"):
        raise ApiError("ERR_SITE_MISMATCH")

    live = [m for m in domain.matches_of_novice(novice["id"])
            if m.get("match_status") in domain.LIVE_MATCH_STATES]
    if mentor is not None:
        for existing in live:
            if existing.get("mentor_id") == mentor["id"]:
                raise ApiError("ERR_DUPLICATE_ACTIVE_MATCH")
    if live:
        raise ApiError("ERR_NOVICE_ALREADY_MATCHED")
    if mentor is None:
        raise ApiError("ERR_NO_ELIGIBLE_MENTOR")

    tier = calc.subject_tier(novice.get("subject_area"), mentor.get("subject_endorsements"))
    row = new_row({
        "mentor_id": mentor["id"],
        "novice_id": novice["id"],
        "match_status": "PROPOSED",
        "selection_mode": selection_mode,
        "subject_match_tier": tier,
        "site_match": mentor.get("site_id") == novice.get("site_id"),
        "pinned_stipend_rate_cents_per_hour": None,
        "verified_minutes_total": 0,
        "accrued_stipend_cents": 0,
        "activated_at": None,
        "suspended_at": None,
        "ended_at": None,
        "end_reason": None,
    })
    db.matches[row["id"]] = row
    touch(mentor)
    if novice.get("program_status") == "ENROLLED":
        novice["program_status"] = "MATCHED"
        touch(novice)
    return row_response(row, 201)


@bp.get("/mentor-matches")
@guard([ADMIN, LEAD, MENTOR])
def list_matches():
    rows = sorted_rows(list(db.matches.values()))
    rows = scope_rows(rows, novice_getter=domain.novice_of_match,
                      mentor_getter=lambda r: r.get("mentor_id"),
                      novice_id_getter=lambda r: r.get("novice_id"))
    rows = apply_filters(rows, {"mentor_id": ("mentor_id", "str"),
                                "novice_id": ("novice_id", "str"),
                                "match_status": ("match_status", "str")})
    limit, offset = pagination()
    return list_response(rows, limit, offset)


@bp.get("/mentor-matches/<row_id>")
@guard([ADMIN, LEAD, MENTOR, NOVICE])
def get_match(row_id):
    row = path_row("matches", row_id)
    own_match(row)
    return row_response(row)


def _novice_after_end(novice, match_id):
    if novice is None:
        return
    remaining = domain.has_live_match(novice["id"], exclude_id=match_id)
    status = novice.get("program_status")
    if status == "ACTIVE":
        novice["program_status"] = "MATCHED" if remaining else "ENROLLED"
        touch(novice)
    elif status == "MATCHED" and not remaining:
        novice["program_status"] = "ENROLLED"
        touch(novice)


@bp.post("/mentor-matches/<row_id>/disposition")
@guard([ADMIN, LEAD])
def dispose_match(row_id):
    match = path_row("matches", row_id)
    data = body()
    decision = enum_field(data, "decision",
                          ("ACTIVATE", "REJECT", "SUSPEND", "RESUME", "END"))
    reason = str_field(data, "reason", 1, 1000,
                       required=decision in ("REJECT", "END"))
    novice = domain.novice_of_match(match)
    mentor = domain.mentor_of_match(match)
    site = domain.site_of_match(match)
    if role() == LEAD and novice is not None:
        own_site(novice.get("site_id"))

    status = match.get("match_status")
    needed = {
        "ACTIVATE": ("PROPOSED",),
        "REJECT": ("PROPOSED",),
        "SUSPEND": ("ACTIVE",),
        "RESUME": ("SUSPENDED",),
        "END": ("PROPOSED", "ACTIVE", "SUSPENDED"),
    }[decision]
    if status not in needed:
        raise ApiError("ERR_MATCH_STATE_INVALID")

    if decision == "END":
        for log in domain.logs_of_match(match["id"]):
            if log.get("verification_status") in ("SUBMITTED", "DISPUTED"):
                raise ApiError("ERR_MATCH_STATE_INVALID")
        cascades.end_match(match, reason)
        _novice_after_end(novice, match["id"])
        return row_response(match)

    if decision == "REJECT":
        match["match_status"] = "REJECTED"
        match["ended_at"] = iso(now())
        match["end_reason"] = reason
        touch(match)
        _novice_after_end(novice, match["id"])
        return row_response(match)

    if decision == "SUSPEND":
        cascades.suspend_match(match)
        return row_response(match)

    # ACTIVATE and RESUME share the capacity gates.
    if site is None or site.get("status") != "OPEN":
        raise ApiError("ERR_SITE_CLOSED")
    if decision == "ACTIVATE":
        if novice is None or novice.get("program_status") != "MATCHED":
            raise ApiError("ERR_NOVICE_PROGRAM_STATE_INVALID")
    elif novice is None or novice.get("program_status") not in ("MATCHED", "ACTIVE"):
        raise ApiError("ERR_NOVICE_PROGRAM_STATE_INVALID")
    if not domain.mentor_certified_now(mentor):
        raise ApiError("ERR_MENTOR_NOT_CERTIFIED")
    if int(mentor.get("active_caseload_count") or 0) >= int(mentor.get("caseload_cap") or 0):
        raise ApiError("ERR_CASELOAD_CAP_EXCEEDED")
    if int(site.get("active_match_count") or 0) >= int(site.get("mentor_slot_cap") or 0):
        raise ApiError("ERR_SITE_SLOT_CAP_EXCEEDED")

    match["match_status"] = "ACTIVE"
    if decision == "ACTIVATE":
        match["activated_at"] = iso(now())
        match["pinned_stipend_rate_cents_per_hour"] = calc.TIER_RATES[
            match.get("subject_match_tier")]
    else:
        match["suspended_at"] = None
    domain.recompute_mentor_caseload(mentor)
    domain.recompute_site_counter(site)
    touch(match)
    touch(mentor)
    touch(site)
    if novice.get("program_status") == "MATCHED":
        novice["program_status"] = "ACTIVE"
        touch(novice)
    return row_response(match)
