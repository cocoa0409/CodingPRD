"""Shared domain logic: validators, serializers, calculations, cascades."""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import CLOCK, STORE, iso3, iso_logical, new_id, parse_date, parse_dt, wall_now
from errors import ERR_INVALID_REQUEST, raise_err

# ---------------------------------------------------------------------------
# Enum domains
# ---------------------------------------------------------------------------
COURSES = {"SCY", "SCM", "LCM"}
EVENT_GENDERS = {"M", "F", "MIXED"}
SWIMMER_GENDERS = {"M", "F"}
AGE_GROUPS = {"TEN_AND_UNDER", "ELEVEN_TWELVE", "THIRTEEN_FOURTEEN", "FIFTEEN_AND_OVER"}
STROKES = {
    "FREESTYLE",
    "BACKSTROKE",
    "BREASTSTROKE",
    "BUTTERFLY",
    "INDIVIDUAL_MEDLEY",
    "FREESTYLE_RELAY",
    "MEDLEY_RELAY",
}
TIE_POLICIES = {"SPLIT", "TOP"}
DECK_ROLES = {"REFEREE", "STARTER", "STROKE_TURN_JUDGE", "CHIEF_TIMER"}
DQ_CODES = {
    "FALSE_START",
    "FLY_ARMS_ALTERNATING",
    "BACK_FINISH_NOT_ON_BACK",
    "BR_KICK_DOWNWARD_WHIP",
    "IM_ORDER_VIOLATION",
    "TURN_NO_TOUCH",
    "RELAY_EARLY_TAKEOFF",
}
PAD_STATUSES = {"VALID", "INVALID", "UNKNOWN"}
VARIANTS = {"PRIMARY_PRIORITY", "BACKUP_MEAN_PRIORITY"}

ACTIVE_ENTRY_STATUSES = {"ENTERED", "SEEDED", "FINISHED", "DQ", "NO_SHOW"}
NON_TERMINAL_DQ_STATUSES = {"RECORDED", "COACH_NOTIFIED", "PROTESTED", "UPHELD"}


# ---------------------------------------------------------------------------
# Request body validators — all failures are ERR_INVALID_REQUEST (400)
# ---------------------------------------------------------------------------
def req_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def _missing(name):
    raise_err(ERR_INVALID_REQUEST, "missing required field: %s" % name)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def v_str(b, name):
    if name not in b or b[name] is None:
        _missing(name)
    if not isinstance(b[name], str):
        raise_err(ERR_INVALID_REQUEST, "field %s must be a string" % name)
    return b[name]


def v_int(b, name):
    if name not in b or b[name] is None:
        _missing(name)
    if not is_int(b[name]):
        raise_err(ERR_INVALID_REQUEST, "field %s must be an integer" % name)
    return b[name]


def v_int_opt(b, name, default=None, nullable=False):
    if name not in b:
        return default
    if b[name] is None:
        if nullable:
            return None
        raise_err(ERR_INVALID_REQUEST, "field %s must be an integer" % name)
    if not is_int(b[name]):
        raise_err(ERR_INVALID_REQUEST, "field %s must be an integer" % name)
    return b[name]


def v_bool(b, name):
    if name not in b or b[name] is None:
        _missing(name)
    if not isinstance(b[name], bool):
        raise_err(ERR_INVALID_REQUEST, "field %s must be a boolean" % name)
    return b[name]


def v_enum(b, name, allowed):
    if name not in b or b[name] is None:
        _missing(name)
    if b[name] not in allowed:
        raise_err(ERR_INVALID_REQUEST, "field %s has an invalid value" % name)
    return b[name]


def v_enum_opt(b, name, allowed, default):
    if name not in b or b[name] is None:
        return default
    if b[name] not in allowed:
        raise_err(ERR_INVALID_REQUEST, "field %s has an invalid value" % name)
    return b[name]


def v_date(b, name):
    if name not in b or b[name] is None:
        _missing(name)
    try:
        return parse_date(b[name])
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, "field %s must be a YYYY-MM-DD date" % name)


def v_datetime(b, name):
    """Return (raw_string, parsed_utc_datetime)."""
    if name not in b or b[name] is None:
        _missing(name)
    try:
        return b[name], parse_dt(b[name])
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, "field %s must be an ISO 8601 datetime" % name)


def v_int_list_opt(b, name, default):
    if name not in b or b[name] is None:
        return default
    val = b[name]
    if not isinstance(val, list) or any(not is_int(x) for x in val):
        raise_err(ERR_INVALID_REQUEST, "field %s must be an array of integers" % name)
    return list(val)


def v_str_list(b, name, allowed=None):
    if name not in b or b[name] is None:
        _missing(name)
    val = b[name]
    if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
        raise_err(ERR_INVALID_REQUEST, "field %s must be an array of strings" % name)
    if allowed is not None and any(x not in allowed for x in val):
        raise_err(ERR_INVALID_REQUEST, "field %s has an invalid value" % name)
    return list(val)


def pagination_params():
    """limit: default 10, min 1, max 100 (capped); offset: default 0, min 0."""
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1:
        raise_err(ERR_INVALID_REQUEST, "limit must be at least 1")
    if limit > 100:
        limit = 100
    if offset < 0:
        raise_err(ERR_INVALID_REQUEST, "offset must be at least 0")
    return limit, offset


def paginate(items):
    """items pre-sorted by created_at ASC; returns (page, limit, offset, total)."""
    limit, offset = pagination_params()
    total = len(items)
    return items[offset : offset + limit], limit, offset, total


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------
def get_or_404(collection, rid, error_id):
    obj = STORE[collection].get(rid)
    if obj is None:
        raise_err(error_id, "%s not found: %s" % (collection, rid))
    return obj


def stamp(obj):
    now = iso3(wall_now())
    obj["created_at"] = now
    obj["updated_at"] = now
    obj["version"] = 1
    return obj


def touch(obj):
    obj["updated_at"] = iso3(wall_now())


def bump(obj):
    obj["version"] += 1
    touch(obj)


def meet_of_event(event):
    return STORE["meets"][event["meet_id"]]


def entry_team_id(entry):
    if entry["swimmer_id"] is not None:
        swimmer = STORE["swimmers"].get(entry["swimmer_id"])
        return swimmer["team_id"] if swimmer else None
    relay = STORE["relay_teams"].get(entry["relay_team_id"])
    return relay["team_id"] if relay else None


def lane_for_entry(entry_id):
    for lane in STORE["lane_assignments"].values():
        if lane["entry_id"] == entry_id:
            return lane
    return None


def result_for_entry(entry_id):
    for r in STORE["results"].values():
        if r["entry_id"] == entry_id:
            return r
    return None


# ---------------------------------------------------------------------------
# Derived figures (full recomputation, never incremental adjustment)
# ---------------------------------------------------------------------------
def _q2(x):
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def recompute_team_points(team_id, bump_on_change=True):
    team = STORE["teams"].get(team_id)
    if team is None:
        return
    prov = Decimal("0")
    off = Decimal("0")
    for r in STORE["results"].values():
        if r["team_id"] != team_id:
            continue
        prov += r["points"]
        if r["status"] == "OFFICIAL":
            off += r["points"]
    prov = _q2(prov)
    off = _q2(off)
    if team["provisional_points"] != prov or team["official_points"] != off:
        team["provisional_points"] = prov
        team["official_points"] = off
        if bump_on_change:
            bump(team)
        else:
            touch(team)


def recompute_active_entry_count(team_id, bump_on_change=True):
    team = STORE["teams"].get(team_id)
    if team is None:
        return
    count = 0
    for e in STORE["entries"].values():
        if e["status"] in ACTIVE_ENTRY_STATUSES and entry_team_id(e) == team_id:
            count += 1
    if team["active_entry_count"] != count:
        team["active_entry_count"] = count
        if bump_on_change:
            bump(team)
        else:
            touch(team)


# ---------------------------------------------------------------------------
# Age derivation
# ---------------------------------------------------------------------------
def compute_age(birth_date, start_date):
    b = datetime.strptime(birth_date, "%Y-%m-%d").date()
    s = datetime.strptime(start_date, "%Y-%m-%d").date()
    # A birthday falling exactly on start_date counts.
    return s.year - b.year - (1 if (s.month, s.day) < (b.month, b.day) else 0)


def age_group_of(age):
    if age <= 10:
        return "TEN_AND_UNDER"
    if age <= 12:
        return "ELEVEN_TWELVE"
    if age <= 14:
        return "THIRTEEN_FOURTEEN"
    return "FIFTEEN_AND_OVER"


# ---------------------------------------------------------------------------
# Timing reconciliation
# ---------------------------------------------------------------------------
def backup_mean_rounded(b1, b2):
    """round_half_up((b1 + b2) / 2) to whole centiseconds — rounded FIRST."""
    mean = (Decimal(b1) + Decimal(b2)) / Decimal(2)
    return int(mean.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def auto_confirmable(lane, meet):
    pad = lane["pad_cs"]
    b1 = lane["backup1_cs"]
    b2 = lane["backup2_cs"]
    if pad is None or lane["pad_status"] == "INVALID":
        return False
    if b1 is None or b2 is None:
        return False
    return abs(pad - backup_mean_rounded(b1, b2)) <= meet["timing_delta_threshold_cs"]


def chain_time(lane, variant):
    """First non-null valid source on the variant's chain. Always non-empty at resolve."""
    pad = lane["pad_cs"]
    b1 = lane["backup1_cs"]
    b2 = lane["backup2_cs"]
    watch = lane["watch_cs"]
    pad_ok = pad is not None and lane["pad_status"] != "INVALID"
    mean = backup_mean_rounded(b1, b2) if (b1 is not None and b2 is not None) else None
    if variant == "PRIMARY_PRIORITY":
        candidates = [pad if pad_ok else None, mean, b1, b2, watch]
    else:
        candidates = [mean, pad if pad_ok else None, b1, b2, watch]
    for v in candidates:
        if v is not None:
            return v
    return None


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
def lane_priority(lane_count):
    """Middle-out: order by |lane - (lane_count+1)/2| ASC, ties to the lower lane."""
    mid = (lane_count + 1) / 2.0
    return sorted(range(1, lane_count + 1), key=lambda lane: (abs(lane - mid), lane))


def run_meet_seeding(meet):
    events = sorted(
        (
            e
            for e in STORE["events"].values()
            if e["meet_id"] == meet["id"] and e["status"] == "PENDING"
        ),
        key=lambda e: e["event_number"],
    )
    lane_count = meet["lane_count"]
    prio = lane_priority(lane_count)
    for ev in events:
        candidates = [
            en
            for en in STORE["entries"].values()
            if en["event_id"] == ev["id"]
            and en["status"] == "ENTERED"
            and en["qualification_status"] == "VERIFIED"
        ]
        if not candidates:
            ev["status"] = "CANCELLED"
            ev["version"] += 1
            touch(ev)
            continue
        # seed_time_cs ASC, NT last; tie-break created_at ASC (never id).
        candidates.sort(
            key=lambda en: (
                en["seed_time_cs"] is None,
                en["seed_time_cs"] if en["seed_time_cs"] is not None else 0,
                en["created_at"],
            )
        )
        n = len(candidates)
        num_heats = -(-n // lane_count)  # ceil
        for chunk_i in range(num_heats):
            chunk = candidates[chunk_i * lane_count : (chunk_i + 1) * lane_count]
            heat_number = num_heats - chunk_i  # fastest heat has the highest number
            for pos, en in enumerate(chunk):
                lane = stamp(
                    {
                        "id": new_id(),
                        "event_id": ev["id"],
                        "entry_id": en["id"],
                        "heat_number": heat_number,
                        "lane_number": prio[pos],
                        "lane_status": "ACTIVE",
                        "pad_cs": None,
                        "backup1_cs": None,
                        "backup2_cs": None,
                        "watch_cs": None,
                        "pad_status": "UNKNOWN",
                        "reconciliation_status": "PENDING_READINGS",
                        "reconciled_variant": None,
                        "final_time_cs": None,
                    }
                )
                STORE["lane_assignments"][lane["id"]] = lane
                en["status"] = "SEEDED"
                bump(en)
        ev["status"] = "SEEDED"
        ev["version"] += 1
        touch(ev)


# ---------------------------------------------------------------------------
# Scoring (place_points) and rescoring
# ---------------------------------------------------------------------------
def _create_result(entry, event, final_time_cs, status):
    points = Decimal("0.00")
    result = stamp(
        {
            "id": new_id(),
            "entry_id": entry["id"],
            "event_id": event["id"],
            "team_id": entry_team_id(entry),
            "final_time_cs": final_time_cs,
            "place": None,
            "points": points,
            "status": status,
        }
    )
    STORE["results"][result["id"]] = result
    return result


def place_and_point(meet, event):
    """Competition ranking (1224) + tie policy + relay multiplier over UNOFFICIAL results."""
    res = [
        r
        for r in STORE["results"].values()
        if r["event_id"] == event["id"]
        and r["status"] == "UNOFFICIAL"
        and r["final_time_cs"] is not None
    ]
    res.sort(key=lambda r: r["final_time_cs"])
    table = meet["points_table"]
    policy = meet["scoring_tie_policy"]
    mult = meet["relay_points_multiplier"]

    def base(place):
        return table[place - 1] if 1 <= place <= len(table) else 0

    place = 1
    i = 0
    n = len(res)
    while i < n:
        j = i
        while j < n and res[j]["final_time_cs"] == res[i]["final_time_cs"]:
            j += 1
        k = j - i
        if policy == "SPLIT":
            total = sum(base(p) for p in range(place, place + k))
            pts = _q2(Decimal(total) / Decimal(k))
        else:  # TOP
            pts = _q2(Decimal(base(place)))
        if event["is_relay"]:
            pts = _q2(pts * Decimal(mult))
        for r in res[i:j]:
            if r["place"] != place or r["points"] != pts:
                r["place"] = place
                r["points"] = pts
                bump(r)
        place += k
        i = j


def score_event_completion(event):
    meet = meet_of_event(event)
    ev_entries = [e for e in STORE["entries"].values() if e["event_id"] == event["id"]]
    lanes_by_entry = {
        l["entry_id"]: l
        for l in STORE["lane_assignments"].values()
        if l["event_id"] == event["id"]
    }
    for en in ev_entries:
        if en["status"] == "SEEDED":
            lane = lanes_by_entry.get(en["id"])
            en["status"] = "FINISHED"
            bump(en)
            _create_result(
                en, event, lane["final_time_cs"] if lane else None, "UNOFFICIAL"
            )
        elif en["status"] == "FINISHED":
            # Restored by a DQ overturn before completion; no Result row exists yet.
            if result_for_entry(en["id"]) is None:
                lane = lanes_by_entry.get(en["id"])
                _create_result(
                    en, event, lane["final_time_cs"] if lane else None, "UNOFFICIAL"
                )
        elif en["status"] == "DQ":
            # Pre-confirmed DQ: created directly DQ_EXCLUDED, place null, points 0.00.
            if result_for_entry(en["id"]) is None:
                _create_result(en, event, None, "DQ_EXCLUDED")
    place_and_point(meet, event)
    for tid in {entry_team_id(en) for en in ev_entries}:
        if tid:
            recompute_team_points(tid)


def rescore_event(event):
    meet = meet_of_event(event)
    place_and_point(meet, event)
    team_ids = {
        r["team_id"] for r in STORE["results"].values() if r["event_id"] == event["id"]
    }
    for tid in team_ids:
        if tid:
            recompute_team_points(tid)


# ---------------------------------------------------------------------------
# Record challenges
# ---------------------------------------------------------------------------
def record_challenge_check(event):
    standing = None
    for rec in STORE["records"].values():
        if rec["event_id"] == event["id"] and rec["status"] == "CURRENT":
            standing = rec
            break
    if standing is None:
        return
    challengers = [
        r
        for r in STORE["results"].values()
        if r["event_id"] == event["id"]
        and r["status"] == "OFFICIAL"
        and r["final_time_cs"] is not None
        and r["final_time_cs"] < standing["record_time_cs"]
    ]
    if not challengers:
        return
    best = min(challengers, key=lambda r: (r["final_time_cs"], r["created_at"]))
    entry = STORE["entries"].get(best["entry_id"])
    if entry and entry["swimmer_id"] is not None:
        swimmer = STORE["swimmers"].get(entry["swimmer_id"])
        holder_name = swimmer["full_name"] if swimmer else ""
    else:
        relay = STORE["relay_teams"].get(entry["relay_team_id"]) if entry else None
        holder_name = relay["relay_name"] if relay else ""
    team = STORE["teams"].get(best["team_id"])
    rec = stamp(
        {
            "id": new_id(),
            "event_id": event["id"],
            "record_time_cs": best["final_time_cs"],
            "holder_name": holder_name,
            "holder_team": team["team_code"] if team else "",
            "set_on_date": event["session_date"],
            "challenger_entry_id": best["entry_id"],
            "status": "PENDING_VERIFICATION",
        }
    )
    STORE["records"][rec["id"]] = rec


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def cascade_dq_confirmed(dq):
    lane = STORE["lane_assignments"][dq["lane_assignment_id"]]
    entry = STORE["entries"].get(lane["entry_id"])
    event = STORE["events"][lane["event_id"]]
    if entry is not None and entry["status"] in ("SEEDED", "FINISHED"):
        entry["status"] = "DQ"
        bump(entry)
    if event["status"] == "COMPLETED":
        result = result_for_entry(entry["id"]) if entry else None
        if result is not None and result["status"] != "DQ_EXCLUDED":
            result["status"] = "DQ_EXCLUDED"
            result["place"] = None
            result["points"] = Decimal("0.00")
            result["final_time_cs"] = None
            bump(result)
        rescore_event(event)
        event["version"] += 1
        touch(event)


def cascade_dq_overturned(dq):
    lane = STORE["lane_assignments"][dq["lane_assignment_id"]]
    entry = STORE["entries"].get(lane["entry_id"])
    event = STORE["events"][lane["event_id"]]
    if entry is None or entry["status"] != "DQ":
        return  # DQ was never confirmed; nothing to restore
    entry["status"] = "FINISHED"
    bump(entry)
    if event["status"] == "COMPLETED":
        result = result_for_entry(entry["id"])
        if result is None:
            _create_result(entry, event, lane["final_time_cs"], "UNOFFICIAL")
        elif result["status"] == "DQ_EXCLUDED":
            result["status"] = "UNOFFICIAL"
            result["final_time_cs"] = lane["final_time_cs"]
            bump(result)
        rescore_event(event)
        event["version"] += 1
        touch(event)


def cascade_team_withdraw(team):
    for swimmer in STORE["swimmers"].values():
        if swimmer["team_id"] == team["id"] and swimmer["status"] != "INACTIVE":
            swimmer["status"] = "INACTIVE"
            bump(swimmer)
    for entry in STORE["entries"].values():
        if entry_team_id(entry) != team["id"]:
            continue
        if entry["status"] in ("ENTERED", "SEEDED"):
            if entry["status"] == "SEEDED":
                lane = lane_for_entry(entry["id"])
                if lane is not None and lane["lane_status"] == "ACTIVE":
                    lane["lane_status"] = "VOIDED"
                    bump(lane)
            entry["status"] = "SCRATCHED"
            bump(entry)
    for relay in STORE["relay_teams"].values():
        if relay["team_id"] == team["id"] and relay["status"] in (
            "DECLARED",
            "LEGS_LOCKED",
        ):
            relay["status"] = "SCRATCHED"
            bump(relay)


def cascade_meet_reopen(meet, new_deadline_raw, new_deadline_dt):
    ev_ids = {
        e["id"] for e in STORE["events"].values() if e["meet_id"] == meet["id"]
    }
    doomed = [
        lid
        for lid, l in STORE["lane_assignments"].items()
        if l["event_id"] in ev_ids
    ]
    for lid in doomed:
        del STORE["lane_assignments"][lid]
    for entry in STORE["entries"].values():
        if entry["event_id"] in ev_ids and entry["status"] == "SEEDED":
            entry["status"] = "ENTERED"
            bump(entry)
    for ev in STORE["events"].values():
        if ev["id"] in ev_ids and ev["status"] == "SEEDED":
            ev["status"] = "PENDING"
            ev["version"] += 1
            touch(ev)
    meet["entry_deadline_utc"] = new_deadline_raw
    meet["_deadline_dt"] = new_deadline_dt


# ---------------------------------------------------------------------------
# Scheduling checks
# ---------------------------------------------------------------------------
def windows_overlap(s1, e1, s2, e2):
    """Half-open [start, end) overlap; adjacency (end == start) is allowed."""
    return s1 < e2 and s2 < e1


def recovery_violation(s1, e1, s2, e2, min_gap):
    """Overlap is always a violation; otherwise the gap must be >= min_gap (equal allowed)."""
    if windows_overlap(s1, e1, s2, e2):
        return True
    if e1 <= s2:
        return (s2 - e1) < min_gap
    return (s1 - e2) < min_gap


# ---------------------------------------------------------------------------
# Serializers (public views)
# ---------------------------------------------------------------------------
def pub_meet(m):
    return {
        "id": m["id"],
        "meet_name": m["meet_name"],
        "course": m["course"],
        "start_date": m["start_date"],
        "entry_deadline_utc": m["entry_deadline_utc"],
        "lane_count": m["lane_count"],
        "points_table": list(m["points_table"]),
        "relay_points_multiplier": m["relay_points_multiplier"],
        "max_individual_entries_per_swimmer": m["max_individual_entries_per_swimmer"],
        "dq_protest_window_minutes": m["dq_protest_window_minutes"],
        "min_recovery_minutes": m["min_recovery_minutes"],
        "timing_delta_threshold_cs": m["timing_delta_threshold_cs"],
        "scoring_tie_policy": m["scoring_tie_policy"],
        "status": m["status"],
        "version": m["version"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
    }


def pub_team(t):
    return {
        "id": t["id"],
        "meet_id": t["meet_id"],
        "team_code": t["team_code"],
        "team_name": t["team_name"],
        "status": t["status"],
        "provisional_points": float(t["provisional_points"]),
        "official_points": float(t["official_points"]),
        "active_entry_count": t["active_entry_count"],
        "version": t["version"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
    }


def pub_swimmer(s):
    return {
        "id": s["id"],
        "team_id": s["team_id"],
        "full_name": s["full_name"],
        "birth_date": s["birth_date"],
        "gender": s["gender"],
        "age_on_meet_start": s["age_on_meet_start"],
        "age_group": s["age_group"],
        "status": s["status"],
        "version": s["version"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
    }


def pub_event(e):
    return {
        "id": e["id"],
        "meet_id": e["meet_id"],
        "event_number": e["event_number"],
        "gender": e["gender"],
        "age_group": e["age_group"],
        "stroke": e["stroke"],
        "distance_meters": e["distance_meters"],
        "is_relay": e["is_relay"],
        "qualifying_time_cs": e["qualifying_time_cs"],
        "session_date": e["session_date"],
        "scheduled_start_minute": e["scheduled_start_minute"],
        "scheduled_end_minute": e["scheduled_end_minute"],
        "status": e["status"],
        "version": e["version"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
    }


def pub_entry(e):
    return {
        "id": e["id"],
        "event_id": e["event_id"],
        "swimmer_id": e["swimmer_id"],
        "relay_team_id": e["relay_team_id"],
        "seed_time_cs": e["seed_time_cs"],
        "qualification_status": e["qualification_status"],
        "status": e["status"],
        "version": e["version"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
    }


def pub_relay(r):
    return {
        "id": r["id"],
        "team_id": r["team_id"],
        "event_id": r["event_id"],
        "relay_name": r["relay_name"],
        "entry_id": r["entry_id"],
        "status": r["status"],
        "version": r["version"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def pub_leg(leg):
    return {
        "id": leg["id"],
        "relay_team_id": leg["relay_team_id"],
        "leg_number": leg["leg_number"],
        "swimmer_id": leg["swimmer_id"],
        "created_at": leg["created_at"],
    }


def pub_lane(l):
    return {
        "id": l["id"],
        "event_id": l["event_id"],
        "entry_id": l["entry_id"],
        "heat_number": l["heat_number"],
        "lane_number": l["lane_number"],
        "lane_status": l["lane_status"],
        "pad_cs": l["pad_cs"],
        "backup1_cs": l["backup1_cs"],
        "backup2_cs": l["backup2_cs"],
        "watch_cs": l["watch_cs"],
        "pad_status": l["pad_status"],
        "reconciliation_status": l["reconciliation_status"],
        "reconciled_variant": l["reconciled_variant"],
        "final_time_cs": l["final_time_cs"],
        "version": l["version"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
    }


def pub_result(r):
    return {
        "id": r["id"],
        "entry_id": r["entry_id"],
        "event_id": r["event_id"],
        "team_id": r["team_id"],
        "final_time_cs": r["final_time_cs"],
        "place": r["place"],
        "points": float(r["points"]),
        "status": r["status"],
        "version": r["version"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def pub_official(o):
    return {
        "id": o["id"],
        "meet_id": o["meet_id"],
        "full_name": o["full_name"],
        "lsc_membership_id": o["lsc_membership_id"],
        "certifications": list(o["certifications"]),
        "certification_expires_on": o["certification_expires_on"],
        "version": o["version"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
    }


def pub_assignment(a):
    return {
        "id": a["id"],
        "event_id": a["event_id"],
        "official_id": a["official_id"],
        "role_on_deck": a["role_on_deck"],
        "status": a["status"],
        "version": a["version"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
    }


def pub_dq(d):
    return {
        "id": d["id"],
        "lane_assignment_id": d["lane_assignment_id"],
        "reporting_official_id": d["reporting_official_id"],
        "resolved_by_referee_id": d["resolved_by_referee_id"],
        "dq_code": d["dq_code"],
        "call_notes": d["call_notes"],
        "status": d["status"],
        "notified_at": iso_logical(d["notified_at"]) if d["notified_at"] else None,
        "version": d["version"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
    }


def pub_record(r):
    return {
        "id": r["id"],
        "event_id": r["event_id"],
        "record_time_cs": r["record_time_cs"],
        "holder_name": r["holder_name"],
        "holder_team": r["holder_team"],
        "set_on_date": r["set_on_date"],
        "challenger_entry_id": r["challenger_entry_id"],
        "status": r["status"],
        "version": r["version"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def sort_created(items):
    return sorted(items, key=lambda x: x["created_at"])
