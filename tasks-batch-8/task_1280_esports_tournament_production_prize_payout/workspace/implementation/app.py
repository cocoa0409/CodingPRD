#!/usr/bin/env python3
"""Esports Tournament Production & Prize Payout API — reference implementation.

In-memory only: module-level dicts keyed by id. Nothing is seeded at startup;
every entity is created via the declared API surface. The logical clock starts
at exactly 2026-08-01T00:00:00Z and only moves via POST /api/_clock/set_current_utc.
"""

import os
import re
import uuid
import threading
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)
LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
_logical_clock = None  # datetime, tz-aware UTC


def _parse_dt(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime. None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_z(dt):
    """Serialize an aware UTC datetime to ISO 8601 with exactly 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now():
    return _logical_clock


def now_iso():
    return _iso_z(_logical_clock)


def init_clock():
    global _logical_clock
    _logical_clock = _parse_dt(CLOCK_DEFAULT)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

db = {
    "tournaments": {},
    "players": {},
    "registrations": {},
    "roster_slots": {},
    "servers": {},
    "matches": {},
    "disputes": {},
    "integrity_cases": {},
    "talents": {},
    "talent_bookings": {},
    "payout_records": {},
    "sponsor_deals": {},
}


def new_id():
    return str(uuid.uuid4())


def stamp_new(rec):
    t = now_iso()
    rec["id"] = new_id()
    rec["created_at"] = t
    rec["updated_at"] = t
    rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_validation(msg="Validation failed"):
    return ApiError("ERR_VALIDATION", msg, 400)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_ownership(msg="Identity does not own the target resource"):
    return ApiError("ERR_OWNERSHIP_MISMATCH", msg, 403)


def err_state(error_id, msg):
    return ApiError(error_id, msg, 409)


def err_biz(error_id, msg, status=422):
    return ApiError(error_id, msg, status)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": _iso_z(datetime.now(timezone.utc)),
    }
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_http_404(e):
    return handle_api_error(err_not_found("Route or resource not found"))


@app.errorhandler(405)
def handle_http_405(e):
    return handle_api_error(err_not_found("Method not allowed"))


@app.errorhandler(500)
def handle_http_500(e):
    return handle_api_error(ApiError("ERR_INTERNAL", str(e), 500))


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

ROLES = {
    "OrganizerAdmin",
    "TournamentDirector",
    "TeamManager",
    "Player",
    "Referee",
    "AntiCheatInvestigator",
    "BroadcastProducer",
    "PayoutOfficer",
    "SponsorManager",
}


class AuthContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_auth(*allowed_roles):
    """Validate X-User-ID / X-User-Role. Returns AuthContext or raises ApiError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role / X-User-ID headers", 401)
    if allowed_roles and role not in allowed_roles:
        raise err_forbidden()
    return AuthContext(user_id, role)


def get_json_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err_validation("Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Field validation helpers
# ---------------------------------------------------------------------------

REGIONS = {"NA", "EU", "APAC", "LATAM"}
CURFEW_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def req_present(body, field):
    if field not in body or body[field] is None:
        raise err_validation(f"Missing required field: {field}")
    return body[field]


def req_string(body, field):
    v = req_present(body, field)
    if not isinstance(v, str) or not v:
        raise err_validation(f"Field {field} must be a non-empty string")
    return v


def req_int(body, field, minimum=None):
    v = req_present(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise err_validation(f"Field {field} must be >= {minimum}")
    return v


def req_enum(body, field, allowed):
    v = req_present(body, field)
    if v not in allowed:
        raise err_validation(f"Field {field} must be one of {sorted(allowed)}")
    return v


def req_datetime(body, field):
    v = req_present(body, field)
    dt = _parse_dt(v)
    if dt is None:
        raise err_validation(f"Field {field} must be a parseable ISO 8601 datetime")
    return dt


def opt_bool(body, field, default=False):
    v = body.get(field, default)
    if not isinstance(v, bool):
        raise err_validation(f"Field {field} must be a boolean")
    return v


def parse_iso_date(value, field="date_of_birth"):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise err_validation(f"Field {field} must be an ISO date YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise err_validation(f"Field {field} must be an ISO date YYYY-MM-DD")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def paginate(items, sort_key=None):
    """Apply limit/offset query params; returns (page, pagination_meta)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_validation("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err_validation("offset must be an integer")
        if offset < 0:
            raise err_validation("offset must be >= 0")
    if sort_key:
        items = sorted(items, key=sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta


# ---------------------------------------------------------------------------
# Entity serializers (computed fields resolved here)
# ---------------------------------------------------------------------------


def serialize_player(p):
    out = dict(p)
    out["active_strike_count"] = compute_active_strike_count(p)
    return out


def serialize_server(s):
    out = dict(s)
    out["booked_minutes"] = compute_booked_minutes(s["id"])
    return out


def compute_active_strike_count(player):
    cutoff = now() - timedelta(days=365)
    count = 0
    for ev in player["ac_strike_events"]:
        issued = _parse_dt(ev["issued_at"])
        if issued is not None and issued > cutoff:
            count += 1
    return count


BOOKED_STATUSES = {
    "SCHEDULED", "LOBBY_OPEN", "LIVE", "PAUSED",
    "COMPLETED", "UNDER_DISPUTE", "CONFIRMED", "OVERTURNED",
}
BUFFER_MINUTES = 15


def compute_booked_minutes(server_id):
    total = 0
    for m in db["matches"].values():
        if m.get("server_id") == server_id and m["status"] in BOOKED_STATUSES:
            total += (m.get("duration_minutes") or 0) + BUFFER_MINUTES
    return total


def refresh_server_booking(server_id):
    if server_id and server_id in db["servers"]:
        db["servers"][server_id]["booked_minutes"] = compute_booked_minutes(server_id)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def get_tournament_or_404(tid):
    t = db["tournaments"].get(tid)
    if t is None:
        raise err_not_found("Tournament not found")
    return t


def get_player_or_404(pid):
    p = db["players"].get(pid)
    if p is None:
        raise err_not_found("Player not found")
    return p


def get_registration_or_404(rid):
    r = db["registrations"].get(rid)
    if r is None:
        raise err_not_found("Registration not found")
    return r


def get_slot_or_404(sid):
    s = db["roster_slots"].get(sid)
    if s is None:
        raise err_not_found("RosterSlot not found")
    return s


def get_server_or_404(sid):
    s = db["servers"].get(sid)
    if s is None:
        raise err_not_found("ServerInstance not found")
    return s


def get_match_or_404(mid):
    m = db["matches"].get(mid)
    if m is None:
        raise err_not_found("Match not found")
    return m


def get_dispute_or_404(did):
    d = db["disputes"].get(did)
    if d is None:
        raise err_not_found("Dispute not found")
    return d


def get_case_or_404(cid):
    c = db["integrity_cases"].get(cid)
    if c is None:
        raise err_not_found("IntegrityCase not found")
    return c


def get_talent_or_404(tid):
    t = db["talents"].get(tid)
    if t is None:
        raise err_not_found("Talent not found")
    return t


def get_booking_or_404(bid):
    b = db["talent_bookings"].get(bid)
    if b is None:
        raise err_not_found("TalentBooking not found")
    return b


def get_payout_or_404(pid):
    p = db["payout_records"].get(pid)
    if p is None:
        raise err_not_found("PayoutRecord not found")
    return p


def get_deal_or_404(did):
    d = db["sponsor_deals"].get(did)
    if d is None:
        raise err_not_found("SponsorDeal not found")
    return d


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------


def dec(value):
    return Decimal(str(value))


def round_half_up_int(value):
    """Round a Decimal to integer cents, ROUND_HALF_UP."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def seed_score_for(reg):
    score = (
        dec("0.50") * dec(reg["region_rank_points"])
        + dec("0.30") * dec(reg["prior_event_points"])
        + dec("0.20") * (dec(reg["qualifier_wins"]) * dec(10))
    )
    return float(score.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def compute_age_years(dob, instant):
    """Whole years between date of birth and instant, calendar-year rollover."""
    d = instant.date()
    years = d.year - dob.year
    if (d.month, d.day) < (dob.month, dob.day):
        years -= 1
    return years


def talent_fee_provisional(talent, start, end):
    total_seconds = Decimal(str((end - start).total_seconds()))
    hours = total_seconds / dec(3600)
    day_units = int((hours / dec(8)).to_integral_value(rounding="ROUND_CEILING"))
    if day_units < 1:
        day_units = 1
    return int(talent["day_rate_cents"]) * day_units


def talent_fee_final(talent, tournament, start, end):
    total_seconds = Decimal(str((end - start).total_seconds()))
    hours = total_seconds / dec(3600)
    day_units = int((hours / dec(8)).to_integral_value(rounding="ROUND_CEILING"))
    if day_units < 1:
        day_units = 1
    base = dec(talent["day_rate_cents"]) * dec(day_units)
    # (3) cross-region uplift on base only
    if talent["home_region"] != tournament["region"]:
        base = dec(round_half_up_int(base * dec("1.15")))
    # (4) overtime
    overtime_hours = hours - dec(8)
    if overtime_hours < 0:
        overtime_hours = dec(0)
    overtime = dec(round_half_up_int(overtime_hours * (dec(talent["day_rate_cents"]) / dec(8)) * dec("1.5")))
    # (5) royalty band from post-uplift base only
    if base < dec(200000):
        band = dec(0)
    elif base < dec(500000):
        band = dec(5)
    else:
        band = dec(10)
    royalty = dec(round_half_up_int(base * band / dec(100)))
    # (6)
    return int(base + overtime + royalty)


# ---------------------------------------------------------------------------
# Bracket generation helpers
# ---------------------------------------------------------------------------


def fill_next_slot(next_match, registration_id):
    """Fill the next match's first empty participant slot (home first, then away)."""
    if next_match["home_registration_id"] is None:
        next_match["home_registration_id"] = registration_id
    elif next_match["away_registration_id"] is None:
        next_match["away_registration_id"] = registration_id
    touch(next_match)


def propagate_winner(match, winner_registration_id):
    """Walkover propagation into next match if it is still PENDING."""
    next_id = match.get("next_match_id")
    if not next_id:
        return
    nxt = db["matches"].get(next_id)
    if nxt is None:
        return
    if nxt["status"] == "PENDING":
        fill_next_slot(nxt, winner_registration_id)


def replace_in_next_slot(next_match, old_reg, new_reg):
    changed = False
    if next_match["home_registration_id"] == old_reg:
        next_match["home_registration_id"] = new_reg
        changed = True
    elif next_match["away_registration_id"] == old_reg:
        next_match["away_registration_id"] = new_reg
        changed = True
    if changed:
        touch(next_match)
    return changed


def clear_in_next_slot(next_match, reg_id):
    changed = False
    if next_match["home_registration_id"] == reg_id:
        next_match["home_registration_id"] = None
        changed = True
    elif next_match["away_registration_id"] == reg_id:
        next_match["away_registration_id"] = None
        changed = True
    if changed:
        touch(next_match)
    return changed


def build_bracket(tournament, locked_regs):
    """Create the match tree. locked_regs must already have seed_position set."""
    seeded = sorted(locked_regs, key=lambda r: r["seed_position"])
    n = len(seeded)
    # smallest power of two >= n
    bracket_size = 1
    while bracket_size < n:
        bracket_size *= 2
    rounds = bracket_size.bit_length() - 1  # log2

    by_seed = {i + 1: seeded[i] for i in range(n)}

    # Create matches round by round; store lookup by (round, slot)
    match_map = {}
    for r in range(1, rounds + 1):
        count = bracket_size // (2 ** r)
        for k in range(1, count + 1):
            m = stamp_new({
                "tournament_id": tournament["id"],
                "bracket_round": r,
                "bracket_slot": k,
                "next_match_id": None,
                "home_registration_id": None,
                "away_registration_id": None,
                "winner_registration_id": None,
                "server_id": None,
                "scheduled_start_at": None,
                "duration_minutes": None,
                "status": "PENDING",
                "home_score": None,
                "away_score": None,
                "assigned_referee_id": None,
                "reported_by_user_id": None,
                "confirmed_by_user_id": None,
                "tactical_pauses_home": 0,
                "tactical_pauses_away": 0,
                "completed_at": None,
                "dispute_window_closes_at": None,
                "forfeiting_registration_id": None,
            })
            db["matches"][m["id"]] = m
            match_map[(r, k)] = m

    # Wire next_match_id: round r slot k -> round r+1 slot ceil(k/2)
    for r in range(1, rounds):
        count = bracket_size // (2 ** r)
        for k in range(1, count + 1):
            nxt_k = (k + 1) // 2
            match_map[(r, k)]["next_match_id"] = match_map[(r + 1, nxt_k)]["id"]

    # Round-1 pairing: slot k -> home seed k, away seed bracket_size + 1 - k
    half = bracket_size // 2
    for k in range(1, half + 1):
        m = match_map[(1, k)]
        home_seed = k
        away_seed = bracket_size + 1 - k
        home_reg = by_seed.get(home_seed)
        away_reg = by_seed.get(away_seed)
        if home_reg is not None:
            m["home_registration_id"] = home_reg["id"]
        if away_reg is not None:
            m["away_registration_id"] = away_reg["id"]
        if away_reg is None and home_reg is not None:
            # Walkover (bye): created directly in FORFEIT with winner = home seed
            m["status"] = "FORFEIT"
            m["winner_registration_id"] = home_reg["id"]
            m["completed_at"] = now_iso()
            m["dispute_window_closes_at"] = now_iso()
            touch(m)
            propagate_winner(m, home_reg["id"])

    return rounds, bracket_size


# ---------------------------------------------------------------------------
# DQ cascade (integrity strikes -> ban -> slot invalidation -> forfeits)
# ---------------------------------------------------------------------------

NON_TERMINAL_MATCH = {"PENDING", "SCHEDULED", "LOBBY_OPEN", "LIVE", "PAUSED", "COMPLETED", "UNDER_DISPUTE", "OVERTURNED"}
DQ_CASCADE_TOURNAMENT_STATUSES = {"REGISTRATION_LOCKED", "SEEDED", "IN_PROGRESS", "COMPLETED"}


def forfeit_match_system(match, forfeiting_reg_id):
    """System DQ cascade forfeit. Winner = other participant; walkover propagation."""
    if match["status"] not in NON_TERMINAL_MATCH:
        return
    if match["home_registration_id"] == forfeiting_reg_id:
        other = match["away_registration_id"]
    elif match["away_registration_id"] == forfeiting_reg_id:
        other = match["home_registration_id"]
    else:
        return
    old_server = match.get("server_id")
    match["status"] = "FORFEIT"
    match["winner_registration_id"] = other
    match["forfeiting_registration_id"] = forfeiting_reg_id
    match["completed_at"] = now_iso()
    match["dispute_window_closes_at"] = now_iso()
    touch(match)
    if other is not None:
        propagate_winner(match, other)
    refresh_server_booking(old_server)


def dq_cascade_for_player(player):
    """BANNED cascade: invalidate active slots on locked+ tournaments, forfeit
    registrations whose starter count fell below roster_size, forfeit matches."""
    affected_reg_ids = []
    for slot in db["roster_slots"].values():
        if slot["player_id"] != player["id"] or slot["status"] != "ACTIVE":
            continue
        reg = db["registrations"].get(slot["registration_id"])
        if reg is None:
            continue
        t = db["tournaments"].get(reg["tournament_id"])
        if t is None or t["status"] not in DQ_CASCADE_TOURNAMENT_STATUSES:
            continue
        slot["status"] = "INELIGIBLE"
        touch(slot)
        if reg["id"] not in affected_reg_ids:
            affected_reg_ids.append(reg["id"])

    forfeited_regs = []
    for rid in affected_reg_ids:
        reg = db["registrations"][rid]
        if reg["status"] != "LOCKED":
            continue
        t = db["tournaments"][reg["tournament_id"]]
        active_starters = sum(
            1 for s in db["roster_slots"].values()
            if s["registration_id"] == rid and s["status"] == "ACTIVE" and s["slot_role"] == "STARTER"
        )
        if active_starters < t["roster_size"]:
            reg["status"] = "FORFEITED"
            touch(reg)
            forfeited_regs.append(rid)

    for rid in forfeited_regs:
        for m in db["matches"].values():
            if m["tournament_id"] != db["registrations"][rid]["tournament_id"]:
                continue
            if m["status"] not in NON_TERMINAL_MATCH:
                continue
            if m.get("home_registration_id") == rid or m.get("away_registration_id") == rid:
                forfeit_match_system(m, rid)


# ---------------------------------------------------------------------------
# Placement assignment
# ---------------------------------------------------------------------------


def assign_placements(tournament):
    """On IN_PROGRESS -> COMPLETED. Uses matches of the current bracket.

    PRD §3.6: FORFEITED registrations keep placement null and receive no
    PayoutRecord in either compute mode, so they are skipped here.
    """
    matches = [m for m in db["matches"].values()
               if m["tournament_id"] == tournament["id"] and m["status"] in {"CONFIRMED", "FORFEIT"}]
    if not matches:
        return
    max_round = max(m["bracket_round"] for m in matches)
    # Reset placements for this tournament's registrations first
    for reg in db["registrations"].values():
        if reg["tournament_id"] == tournament["id"]:
            reg["placement"] = None

    def place(reg_id, value):
        if reg_id is None:
            return
        reg = db["registrations"].get(reg_id)
        if reg is None or reg["status"] == "FORFEITED":
            return
        reg["placement"] = value

    for m in matches:
        home = m.get("home_registration_id")
        away = m.get("away_registration_id")
        winner = m.get("winner_registration_id")
        if winner is None:
            continue
        loser = None
        if home == winner:
            loser = away
        elif away == winner:
            loser = home
        if m["bracket_round"] == max_round:
            place(winner, 1)
            place(loser, 2)
        else:
            place(loser, (2 ** (max_round - m["bracket_round"])) + 1)


# ---------------------------------------------------------------------------
# Routes: clock
# ---------------------------------------------------------------------------


@app.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    with LOCK:
        require_auth("OrganizerAdmin")
        body = get_json_body()
        dt = req_datetime(body, "to_iso8601")
        global _logical_clock
        _logical_clock = dt
        return ok({"current_utc": now_iso()})


# ---------------------------------------------------------------------------
# Routes: tournaments
# ---------------------------------------------------------------------------


@app.route("/api/tournaments", methods=["POST"])
def create_tournament():
    with LOCK:
        require_auth("OrganizerAdmin")
        body = get_json_body()
        name = req_string(body, "name")
        game_title = req_string(body, "game_title")
        region = req_enum(body, "region", REGIONS)
        prize_pool_target_cents = req_int(body, "prize_pool_target_cents", 0)
        roster_size = req_int(body, "roster_size", 1)
        max_roster_size = req_int(body, "max_roster_size", 1)
        if max_roster_size < roster_size:
            raise err_validation("max_roster_size must be >= roster_size")
        opens = req_datetime(body, "registration_opens_at")
        closes = req_datetime(body, "registration_closes_at")
        curfew = req_string(body, "minor_curfew_local")
        if not CURFEW_RE.match(curfew):
            raise err_validation("minor_curfew_local must be HH:MM")
        rec = stamp_new({
            "name": name,
            "game_title": game_title,
            "region": region,
            "prize_pool_target_cents": prize_pool_target_cents,
            "funded_pool_cents": 0,
            "roster_size": roster_size,
            "max_roster_size": max_roster_size,
            "registration_opens_at": _iso_z(opens),
            "registration_closes_at": _iso_z(closes),
            "minor_curfew_local": curfew,
            "status": "DRAFT",
            "bracket_version": 0,
            "placements_assigned": False,
        })
        db["tournaments"][rec["id"]] = rec
        return ok(rec, 201)


@app.route("/api/tournaments/<tid>", methods=["GET"])
def get_tournament(tid):
    with LOCK:
        require_auth(*ROLES)
        return ok(get_tournament_or_404(tid))


@app.route("/api/tournaments/<tid>/fund", methods=["POST"])
def fund_tournament(tid):
    with LOCK:
        require_auth("OrganizerAdmin")
        t = get_tournament_or_404(tid)
        body = get_json_body()
        amount = req_int(body, "amount_cents", 1)
        if t["status"] not in {"DRAFT", "REGISTRATION_OPEN", "REGISTRATION_LOCKED", "SEEDED"}:
            raise err_state("ERR_INVALID_TOURNAMENT_STATUS", "Cannot fund in this status")
        t["funded_pool_cents"] += amount
        touch(t)
        return ok(t)


ADVANCE_TARGETS = {
    "DRAFT": {"REGISTRATION_OPEN", "CANCELLED"},
    "REGISTRATION_OPEN": {"REGISTRATION_LOCKED", "CANCELLED"},
    "SEEDED": {"IN_PROGRESS", "CANCELLED"},
    "IN_PROGRESS": {"COMPLETED"},
    "COMPLETED": {"PAYOUTS_FINALIZED"},
}


@app.route("/api/tournaments/<tid>/advance", methods=["POST"])
def advance_tournament(tid):
    with LOCK:
        require_auth("TournamentDirector")
        t = get_tournament_or_404(tid)
        body = get_json_body()
        target = req_enum(body, "target_status", {
            "REGISTRATION_OPEN", "REGISTRATION_LOCKED", "SEEDED", "IN_PROGRESS",
            "COMPLETED", "PAYOUTS_FINALIZED", "CANCELLED",
        })
        allowed = ADVANCE_TARGETS.get(t["status"], set())
        if target not in allowed:
            raise err_state("ERR_INVALID_TOURNAMENT_STATUS",
                            f"Tournament cannot advance from {t['status']} to {target}")

        if t["status"] == "REGISTRATION_OPEN" and target == "REGISTRATION_LOCKED":
            # precondition: logical clock >= registration_closes_at
            closes = _parse_dt(t["registration_closes_at"])
            if now() < closes:
                raise err_biz("ERR_INVALID_TOURNAMENT_STATUS",
                              "Registration window has not closed yet", 409)
            # cascade
            for reg in db["registrations"].values():
                if reg["tournament_id"] != t["id"]:
                    continue
                if reg["status"] == "APPROVED":
                    reg["status"] = "LOCKED"
                    touch(reg)
                    for slot in db["roster_slots"].values():
                        if slot["registration_id"] == reg["id"] and slot["status"] == "ACTIVE":
                            player = db["players"].get(slot["player_id"])
                            if player is None:
                                continue
                            dob = date.fromisoformat(player["date_of_birth"])
                            age = compute_age_years(dob, now())
                            slot["age_at_lock_years"] = age
                            slot["is_minor"] = age < 18
                            touch(slot)
                elif reg["status"] in {"SUBMITTED", "APPEALED"}:
                    reg["status"] = "REJECTED"
                    touch(reg)

        elif t["status"] == "SEEDED" and target == "IN_PROGRESS":
            for m in db["matches"].values():
                if m["tournament_id"] != t["id"]:
                    continue
                if m["bracket_round"] == 1 and m["home_registration_id"] and m["away_registration_id"]:
                    if m["status"] != "SCHEDULED":
                        raise err_state("ERR_INVALID_TOURNAMENT_STATUS",
                                        "Every round-1 match with both participants must be SCHEDULED")

        elif t["status"] == "IN_PROGRESS" and target == "COMPLETED":
            for m in db["matches"].values():
                if m["tournament_id"] != t["id"]:
                    continue
                if m["status"] not in {"CONFIRMED", "FORFEIT"}:
                    raise err_state("ERR_INVALID_TOURNAMENT_STATUS",
                                    "Every match must be CONFIRMED or FORFEIT")
            assign_placements(t)
            t["placements_assigned"] = True

        elif t["status"] == "COMPLETED" and target == "PAYOUTS_FINALIZED":
            for p in db["payout_records"].values():
                if p["tournament_id"] != t["id"]:
                    continue
                if p["disbursement_status"] not in {"PAID", "VOID"}:
                    raise err_state("ERR_INVALID_TOURNAMENT_STATUS",
                                    "Every payout record must be PAID or VOID")

        elif target == "CANCELLED":
            if t["status"] == "REGISTRATION_OPEN":
                for reg in db["registrations"].values():
                    if reg["tournament_id"] != t["id"]:
                        continue
                    if reg["status"] in {"DRAFT", "SUBMITTED", "APPEALED", "APPROVED"}:
                        reg["status"] = "REJECTED"
                        touch(reg)
            elif t["status"] == "SEEDED":
                affected_servers = set()
                for m in db["matches"].values():
                    if m["tournament_id"] != t["id"]:
                        continue
                    if m["status"] in {"PENDING", "SCHEDULED"}:
                        m["status"] = "CANCELLED"
                        touch(m)
                        if m.get("server_id"):
                            affected_servers.add(m["server_id"])
                for sid in affected_servers:
                    refresh_server_booking(sid)
                for b in db["talent_bookings"].values():
                    if b["tournament_id"] != t["id"]:
                        continue
                    if b["status"] in {"TENTATIVE", "CONFIRMED"}:
                        b["status"] = "CANCELLED"
                        touch(b)

        t["status"] = target
        touch(t)
        return ok(t)


# ---------------------------------------------------------------------------
# Routes: bracket generation
# ---------------------------------------------------------------------------


@app.route("/api/tournaments/<tid>/generate-bracket", methods=["POST"])
def generate_bracket(tid):
    with LOCK:
        require_auth("TournamentDirector")
        t = get_tournament_or_404(tid)
        body = get_json_body()
        expected = req_int(body, "expected_tournament_version")

        if t["status"] not in {"REGISTRATION_LOCKED", "SEEDED"}:
            raise err_state("ERR_INVALID_TOURNAMENT_STATUS",
                            f"generate-bracket not allowed from {t['status']}")

        if t["status"] == "SEEDED":
            # Regeneration: no match may be underway/decided
            for m in db["matches"].values():
                if m["tournament_id"] != t["id"]:
                    continue
                if m["status"] in {"LOBBY_OPEN", "LIVE", "PAUSED", "COMPLETED",
                                   "UNDER_DISPUTE", "CONFIRMED", "OVERTURNED"}:
                    raise err_state("ERR_INVALID_TOURNAMENT_STATUS",
                                    "Cannot regenerate: matches already underway or decided")

        locked = [r for r in db["registrations"].values()
                  if r["tournament_id"] == t["id"] and r["status"] == "LOCKED"]
        if len(locked) < 2:
            raise err_biz("ERR_INSUFFICIENT_FIELD", "Fewer than 2 LOCKED registrations", 422)

        if t["funded_pool_cents"] < t["prize_pool_target_cents"]:
            raise err_biz("ERR_PRIZE_POOL_UNDERFUNDED", "funded_pool_cents below target", 422)

        if expected != t["version"]:
            raise ApiError("ERR_STALE_VERSION", "expected_tournament_version mismatch", 412)

        # On regeneration: cancel existing matches, recompute server bookings
        if t["status"] == "SEEDED":
            affected_servers = set()
            for m in db["matches"].values():
                if m["tournament_id"] != t["id"]:
                    continue
                if m["status"] in {"PENDING", "SCHEDULED"}:
                    m["status"] = "CANCELLED"
                    touch(m)
                    if m.get("server_id"):
                        affected_servers.add(m["server_id"])
            for sid in affected_servers:
                refresh_server_booking(sid)

        # seed_score + seed_position
        for reg in locked:
            reg["seed_score"] = seed_score_for(reg)
        ordered = sorted(
            locked,
            key=lambda r: (
                -dec(str(r["seed_score"])),
                -r["qualifier_wins"],
                r["created_at"],
                r["team_name"],
            ),
        )
        for idx, reg in enumerate(ordered, start=1):
            if reg.get("seed_position") != idx:
                reg["seed_position"] = idx
            touch(reg)

        build_bracket(t, ordered)
        t["bracket_version"] += 1
        t["status"] = "SEEDED"
        touch(t)
        return ok(t, 201)


# ---------------------------------------------------------------------------
# Routes: payout compute
# ---------------------------------------------------------------------------

PCT = {1: dec("50"), 2: dec("25"), 3: dec("12.5")}
MIN_PLACEMENT_CENTS = 100000


@app.route("/api/tournaments/<tid>/payout-records/compute", methods=["POST"])
def compute_payouts(tid):
    with LOCK:
        require_auth("PayoutOfficer")
        t = get_tournament_or_404(tid)
        body = get_json_body()
        mode = req_enum(body, "mode", {"PROVISIONAL", "FINAL"})
        expected = req_int(body, "expected_tournament_version")

        if t["status"] != "COMPLETED":
            raise err_state("ERR_INVALID_TOURNAMENT_STATUS",
                            "Payout compute requires tournament COMPLETED")

        # eligible set: placement in {1,2,3} and not FORFEITED
        placed = [r for r in db["registrations"].values()
                  if r["tournament_id"] == t["id"]
                  and r.get("placement") in (1, 2, 3)
                  and r["status"] != "FORFEITED"]

        if mode == "FINAL":
            # no open integrity cases for players on eligible registrations
            eligible_ids = {r["id"] for r in placed}
            player_ids = set()
            for slot in db["roster_slots"].values():
                if slot["registration_id"] in eligible_ids:
                    player_ids.add(slot["player_id"])
            for c in db["integrity_cases"].values():
                if c["player_id"] in player_ids and c["status"] in {"OPEN", "INVESTIGATING"}:
                    raise err_biz("ERR_INTEGRITY_CASES_PENDING",
                                  "Open integrity cases on eligible registrations", 422)

        if expected != t["version"]:
            raise ApiError("ERR_STALE_VERSION", "expected_tournament_version mismatch", 412)

        # (1) pool total
        sponsor_bonus = sum(
            d["bonus_cents"] for d in db["sponsor_deals"].values()
            if d["tournament_id"] == t["id"] and d["status"] == "ACTIVATED"
        )
        pool_total = t["funded_pool_cents"] + sponsor_bonus

        # (3)(4) percentages with FINAL-variant pro-rata redistribution
        # All registrations with placement in {1,2,3} regardless of FORFEITED status
        all_placed = [r for r in db["registrations"].values()
                      if r["tournament_id"] == t["id"] and r.get("placement") in (1, 2, 3)]
        base_pcts = {}
        for r in all_placed:
            base_pcts[r["id"]] = PCT[r["placement"]]
        pct_map = {}
        if mode == "FINAL":
            # Pro-rata redistribution of excluded (FORFEITED) placements' base_pct
            # to the remaining placed registrations in proportion to their own base_pct.
            excluded = [r for r in all_placed if r["status"] == "FORFEITED"]
            remaining = [r for r in all_placed if r["status"] != "FORFEITED"]
            if excluded:
                total_remaining_pct = sum(base_pcts[r["id"]] for r in remaining)
                for r in remaining:
                    if total_remaining_pct > 0:
                        pct_map[r["id"]] = base_pcts[r["id"]] / total_remaining_pct * dec(100)
                    else:
                        pct_map[r["id"]] = dec(0)
            else:
                pct_map = {r["id"]: base_pcts[r["id"]] for r in remaining}
        else:
            pct_map = {r["id"]: base_pcts[r["id"]] for r in placed}

        # (5) waterfall with floor — placements ascending; 3s by created_at ASC then seed_position ASC
        def waterfall_key(r):
            return (r["placement"], r["created_at"], r.get("seed_position") or 0)

        ordered = sorted([r for r in placed], key=waterfall_key)

        exact = {}
        remaining_pool = dec(pool_total)
        for r in ordered:
            pct = pct_map.get(r["id"], dec(0))
            share = dec(pool_total) * pct / dec(100)
            floor_val = dec(MIN_PLACEMENT_CENTS)
            val = floor_val if floor_val > share else share
            if val > remaining_pool:
                val = remaining_pool
            exact[r["id"]] = val
            remaining_pool -= val

        # (5b) residual sweep
        if remaining_pool > 0 and ordered:
            p1 = [r for r in ordered if r["placement"] == 1]
            if p1:
                target = p1[0]
            else:
                target = sorted(ordered, key=waterfall_key)[0]
            exact[target["id"]] += remaining_pool
            remaining_pool = dec(0)

        # (6) rounding reconciliation
        rounded = {rid: round_half_up_int(v) for rid, v in exact.items()}
        delta = pool_total - sum(rounded.values())
        if ordered and delta != 0:
            target = sorted(ordered, key=waterfall_key)[0]
            rounded[target["id"]] += delta

        # Supersede prior COMPUTED records
        for p in db["payout_records"].values():
            if p["tournament_id"] == t["id"] and p["disbursement_status"] == "COMPUTED":
                p["disbursement_status"] = "VOID"
                touch(p)

        created = []
        for r in ordered:
            # payee_is_minor copied from payee roster slot is_minor at compute time
            payee_is_minor = False
            for slot in db["roster_slots"].values():
                if slot["registration_id"] == r["id"] and slot["player_id"] == r["captain_player_id"]:
                    if slot.get("is_minor"):
                        payee_is_minor = True
                    break
            gross = rounded.get(r["id"], 0)
            rec = stamp_new({
                "tournament_id": t["id"],
                "registration_id": r["id"],
                "payee_player_id": r["captain_player_id"],
                "placement": r["placement"],
                "compute_run_mode": mode,
                "bracket_version": t["bracket_version"],
                "gross_amount_cents": gross,
                "withholding_cents": 0,
                "net_amount_cents": gross,
                "payee_is_minor": payee_is_minor,
                "guardian_name": None,
                "guardian_email": None,
                "doc_status": "PENDING",
                "doc_type": None,
                "doc_verified_by_user_id": None,
                "disbursement_status": "COMPUTED",
                "approved_by_user_id": None,
                "paid_at": None,
            })
            db["payout_records"][rec["id"]] = rec
            created.append(rec)

        touch(t)
        return ok(created, 201)


# ---------------------------------------------------------------------------
# Routes: players
# ---------------------------------------------------------------------------


@app.route("/api/players", methods=["POST"])
def create_player():
    with LOCK:
        require_auth("OrganizerAdmin")
        body = get_json_body()
        handle = req_string(body, "handle")
        dob_raw = req_string(body, "date_of_birth")
        parse_iso_date(dob_raw)
        region = req_enum(body, "region", REGIONS)
        for p in db["players"].values():
            if p["handle"] == handle:
                raise ApiError("ERR_HANDLE_TAKEN", "Player handle already in use", 409)
        rec = stamp_new({
            "handle": handle,
            "date_of_birth": dob_raw,
            "region": region,
            "eligibility_status": "ELIGIBLE",
            "ac_strike_events": [],
        })
        db["players"][rec["id"]] = rec
        return ok(serialize_player(rec), 201)


@app.route("/api/players/<pid>", methods=["GET"])
def get_player(pid):
    with LOCK:
        require_auth("OrganizerAdmin", "TournamentDirector", "Player", "AntiCheatInvestigator", "PayoutOfficer")
        return ok(serialize_player(get_player_or_404(pid)))


@app.route("/api/players/<pid>/eligibility", methods=["POST"])
def player_eligibility(pid):
    with LOCK:
        require_auth("OrganizerAdmin")
        p = get_player_or_404(pid)
        body = get_json_body()
        action = req_enum(body, "action", {"SUSPEND", "REINSTATE"})
        if action == "SUSPEND":
            if p["eligibility_status"] != "ELIGIBLE":
                raise ApiError("ERR_VALIDATION", f"Cannot SUSPEND from {p['eligibility_status']}", 400)
            p["eligibility_status"] = "SUSPENDED"
        else:
            if p["eligibility_status"] != "SUSPENDED":
                raise ApiError("ERR_VALIDATION", f"Cannot REINSTATE from {p['eligibility_status']}", 400)
            p["eligibility_status"] = "ELIGIBLE"
        touch(p)
        return ok(serialize_player(p))


# ---------------------------------------------------------------------------
# Routes: registrations
# ---------------------------------------------------------------------------


@app.route("/api/registrations", methods=["POST"])
def create_registration():
    with LOCK:
        require_auth("OrganizerAdmin")
        body = get_json_body()
        tid = req_string(body, "tournament_id")
        get_tournament_or_404(tid)
        team_name = req_string(body, "team_name")
        email = req_string(body, "manager_contact_email")
        rrp = req_int(body, "region_rank_points")
        pep = req_int(body, "prior_event_points")
        qw = req_int(body, "qualifier_wins")
        captain = req_string(body, "captain_player_id")
        get_player_or_404(captain)
        for r in db["registrations"].values():
            if r["tournament_id"] == tid and r["team_name"] == team_name:
                raise ApiError("ERR_HANDLE_TAKEN", "team_name already used in this tournament", 409)
        rec = stamp_new({
            "tournament_id": tid,
            "team_name": team_name,
            "manager_contact_email": email,
            "region_rank_points": rrp,
            "prior_event_points": pep,
            "qualifier_wins": qw,
            "captain_player_id": captain,
            "status": "DRAFT",
            "appeal_used": False,
            "seed_score": None,
            "seed_position": None,
            "placement": None,
        })
        db["registrations"][rec["id"]] = rec
        return ok(rec, 201)


@app.route("/api/registrations/<rid>", methods=["GET"])
def get_registration(rid):
    with LOCK:
        require_auth("OrganizerAdmin", "TournamentDirector", "TeamManager", "PayoutOfficer")
        return ok(get_registration_or_404(rid))


@app.route("/api/registrations", methods=["GET"])
def list_registrations():
    with LOCK:
        require_auth("OrganizerAdmin", "TournamentDirector", "PayoutOfficer")
        items = list(db["registrations"].values())
        tid = request.args.get("tournament_id")
        status = request.args.get("status")
        captain = request.args.get("captain_player_id")
        if tid is not None:
            items = [r for r in items if r["tournament_id"] == tid]
        if status is not None:
            items = [r for r in items if r["status"] == status]
        if captain is not None:
            items = [r for r in items if r["captain_player_id"] == captain]
        page, meta = paginate(items, sort_key=lambda r: (r["created_at"], r["id"]))
        return ok(page, pagination=meta)


@app.route("/api/registrations/<rid>/submit", methods=["POST"])
def submit_registration(rid):
    with LOCK:
        auth = require_auth("TeamManager")
        reg = get_registration_or_404(rid)
        if auth.user_id != reg["id"]:
            raise err_ownership("TeamManager identity must equal registration id")
        if reg["status"] != "DRAFT":
            raise err_state("ERR_INVALID_REGISTRATION_STATUS",
                            f"Cannot submit from {reg['status']}")
        t = db["tournaments"].get(reg["tournament_id"])
        if t is None:
            raise err_not_found("Tournament not found")
        if t["status"] != "REGISTRATION_OPEN":
            raise err_state("ERR_INVALID_TOURNAMENT_STATUS",
                            "Tournament is not in REGISTRATION_OPEN")
        # business rules before temporal per PRD §2.9:
        # state checks, then safety, then constraint (roster shape etc), then temporal window.
        slots = [s for s in db["roster_slots"].values()
                 if s["registration_id"] == reg["id"] and s["status"] == "ACTIVE"]
        starters = [s for s in slots if s["slot_role"] == "STARTER"]
        if len(starters) != t["roster_size"] or len(slots) > t["max_roster_size"]:
            raise err_biz("ERR_ROSTER_SIZE_VIOLATION",
                          "Roster must have exactly roster_size ACTIVE STARTERs and <= max_roster_size ACTIVE slots")
        for s in slots:
            p = db["players"].get(s["player_id"])
            if p is None:
                raise err_not_found("Player not found")
        for s in slots:
            p = db["players"][s["player_id"]]
            if p["eligibility_status"] != "ELIGIBLE":
                raise err_biz("ERR_PLAYER_INELIGIBLE", "An ACTIVE slot's player is not ELIGIBLE")
        captain_ok = any(
            s["player_id"] == reg["captain_player_id"] and s["slot_role"] == "STARTER"
            for s in starters
        )
        if not captain_ok:
            raise err_biz("ERR_PLAYER_INELIGIBLE", "captain_player_id must be an ACTIVE STARTER")
        # double roster check
        my_players = {s["player_id"] for s in slots}
        for other in db["registrations"].values():
            if other["tournament_id"] != reg["tournament_id"] or other["id"] == reg["id"]:
                continue
            for s in db["roster_slots"].values():
                if s["registration_id"] == other["id"] and s["status"] == "ACTIVE" and s["player_id"] in my_players:
                    raise ApiError("ERR_PLAYER_DOUBLE_ROSTERED",
                                   "Player already ACTIVE on another registration for this tournament", 409)
        # temporal window (priority 9)
        opens = _parse_dt(t["registration_opens_at"])
        closes = _parse_dt(t["registration_closes_at"])
        if now() < opens or now() > closes:
            raise err_biz("ERR_REGISTRATION_WINDOW_CLOSED",
                          "Outside the registration window", 422)
        reg["status"] = "SUBMITTED"
        touch(reg)
        return ok(reg)


@app.route("/api/registrations/<rid>/review", methods=["POST"])
def review_registration(rid):
    with LOCK:
        require_auth("TournamentDirector")
        reg = get_registration_or_404(rid)
        body = get_json_body()
        action = req_enum(body, "action", {"APPROVE", "REJECT"})
        if reg["status"] not in {"SUBMITTED", "APPEALED"}:
            raise err_state("ERR_INVALID_REGISTRATION_STATUS",
                            f"Cannot review from {reg['status']}")
        t = db["tournaments"].get(reg["tournament_id"])
        if t is None:
            raise err_not_found("Tournament not found")
        if t["status"] != "REGISTRATION_OPEN":
            raise err_state("ERR_INVALID_TOURNAMENT_STATUS",
                            "Tournament is not in REGISTRATION_OPEN")
        reg["status"] = "APPROVED" if action == "APPROVE" else "REJECTED"
        touch(reg)
        return ok(reg)


@app.route("/api/registrations/<rid>/appeal", methods=["POST"])
def appeal_registration(rid):
    with LOCK:
        auth = require_auth("TeamManager")
        reg = get_registration_or_404(rid)
        if auth.user_id != reg["id"]:
            raise err_ownership("TeamManager identity must equal registration id")
        if reg["status"] != "REJECTED":
            raise err_state("ERR_INVALID_REGISTRATION_STATUS",
                            f"Cannot appeal from {reg['status']}")
        if reg["appeal_used"]:
            raise err_biz("ERR_APPEAL_EXHAUSTED", "Appeal already used", 422)
        t = db["tournaments"].get(reg["tournament_id"])
        if t is None:
            raise err_not_found("Tournament not found")
        if t["status"] != "REGISTRATION_OPEN":
            raise err_state("ERR_INVALID_TOURNAMENT_STATUS",
                            "Tournament is not in REGISTRATION_OPEN")
        reg["status"] = "APPEALED"
        reg["appeal_used"] = True
        touch(reg)
        return ok(reg)


# ---------------------------------------------------------------------------
# Routes: roster slots
# ---------------------------------------------------------------------------


@app.route("/api/roster-slots", methods=["POST"])
def create_roster_slot():
    with LOCK:
        auth = require_auth("TeamManager")
        body = get_json_body()
        rid = req_string(body, "registration_id")
        pid = req_string(body, "player_id")
        slot_role = req_enum(body, "slot_role", {"STARTER", "SUBSTITUTE"})
        reg = get_registration_or_404(rid)
        get_player_or_404(pid)
        if auth.user_id != reg["id"]:
            raise err_ownership("TeamManager identity must equal registration id")
        if reg["status"] != "DRAFT":
            raise err_state("ERR_INVALID_REGISTRATION_STATUS",
                            "Roster can only be modified while registration is DRAFT")
        # uniqueness: no two non-REMOVED slots with same (registration_id, player_id)
        for s in db["roster_slots"].values():
            if s["registration_id"] == rid and s["player_id"] == pid and s["status"] != "REMOVED":
                raise ApiError("ERR_HANDLE_TAKEN", "Player already has a non-REMOVED slot on this registration", 409)
        # double-roster across registrations of the same tournament
        for other in db["registrations"].values():
            if other["tournament_id"] != reg["tournament_id"] or other["id"] == rid:
                continue
            for s in db["roster_slots"].values():
                if s["registration_id"] == other["id"] and s["status"] == "ACTIVE" and s["player_id"] == pid:
                    raise ApiError("ERR_PLAYER_DOUBLE_ROSTERED",
                                   "Player already ACTIVE on another registration for this tournament", 409)
        # roster size cap on ACTIVE slots
        t = db["tournaments"].get(reg["tournament_id"])
        active_count = sum(
            1 for s in db["roster_slots"].values()
            if s["registration_id"] == rid and s["status"] == "ACTIVE"
        )
        if t is not None and active_count + 1 > t["max_roster_size"]:
            raise err_biz("ERR_ROSTER_SIZE_VIOLATION",
                          "Adding this slot would exceed max_roster_size")
        rec = stamp_new({
            "registration_id": rid,
            "player_id": pid,
            "slot_role": slot_role,
            "status": "ACTIVE",
            "age_at_lock_years": None,
            "is_minor": None,
        })
        db["roster_slots"][rec["id"]] = rec
        return ok(rec, 201)


@app.route("/api/roster-slots/<sid>/remove", methods=["POST"])
def remove_roster_slot(sid):
    with LOCK:
        auth = require_auth("TeamManager")
        slot = get_slot_or_404(sid)
        reg = get_registration_or_404(slot["registration_id"])
        if auth.user_id != reg["id"]:
            raise err_ownership("TeamManager identity must equal registration id")
        if reg["status"] != "DRAFT":
            raise err_state("ERR_INVALID_REGISTRATION_STATUS",
                            "Roster can only be modified while registration is DRAFT")
        if slot["status"] != "ACTIVE":
            raise err_state("ERR_INVALID_REGISTRATION_STATUS",
                            f"Slot is {slot['status']}")
        slot["status"] = "REMOVED"
        touch(slot)
        return ok(slot)


@app.route("/api/roster-slots/<sid>", methods=["GET"])
def get_roster_slot(sid):
    with LOCK:
        require_auth("OrganizerAdmin", "TournamentDirector", "TeamManager")
        return ok(get_slot_or_404(sid))


@app.route("/api/roster-slots", methods=["GET"])
def list_roster_slots():
    with LOCK:
        require_auth("OrganizerAdmin", "TournamentDirector", "TeamManager")
        items = list(db["roster_slots"].values())
        rid = request.args.get("registration_id")
        pid = request.args.get("player_id")
        status = request.args.get("status")
        if rid is not None:
            items = [s for s in items if s["registration_id"] == rid]
        if pid is not None:
            items = [s for s in items if s["player_id"] == pid]
        if status is not None:
            items = [s for s in items if s["status"] == status]
        page, meta = paginate(items, sort_key=lambda s: (s["created_at"], s["id"]))
        return ok(page, pagination=meta)


# ---------------------------------------------------------------------------
# Routes: servers
# ---------------------------------------------------------------------------


@app.route("/api/servers", methods=["POST"])
def create_server():
    with LOCK:
        require_auth("OrganizerAdmin")
        body = get_json_body()
        tid = req_string(body, "tournament_id")
        get_tournament_or_404(tid)
        label = req_string(body, "label")
        region = req_enum(body, "region", REGIONS)
        rec = stamp_new({
            "tournament_id": tid,
            "label": label,
            "region": region,
            "status": "ACTIVE",
            "booked_minutes": 0,
        })
        db["servers"][rec["id"]] = rec
        return ok(serialize_server(rec), 201)


@app.route("/api/servers/<sid>", methods=["GET"])
def get_server(sid):
    with LOCK:
        require_auth("OrganizerAdmin", "TournamentDirector", "Referee")
        return ok(serialize_server(get_server_or_404(sid)))


@app.route("/api/servers", methods=["GET"])
def list_servers():
    with LOCK:
        require_auth("OrganizerAdmin", "TournamentDirector", "Referee")
        items = list(db["servers"].values())
        tid = request.args.get("tournament_id")
        status = request.args.get("status")
        if tid is not None:
            items = [s for s in items if s["tournament_id"] == tid]
        if status is not None:
            items = [s for s in items if s["status"] == status]
        items = [serialize_server(s) for s in items]
        page, meta = paginate(items, sort_key=lambda s: (s["created_at"], s["id"]))
        return ok(page, pagination=meta)


@app.route("/api/servers/<sid>/maintenance", methods=["POST"])
def server_maintenance(sid):
    with LOCK:
        require_auth("OrganizerAdmin")
        srv = get_server_or_404(sid)
        body = get_json_body()
        action = req_enum(body, "action", {"ENTER", "EXIT"})
        if action == "ENTER":
            if srv["status"] == "MAINTENANCE":
                raise ApiError("ERR_VALIDATION", "Server already in MAINTENANCE", 400)
            for m in db["matches"].values():
                if m.get("server_id") == sid and m["status"] in {"LOBBY_OPEN", "LIVE", "PAUSED"}:
                    raise ApiError("ERR_SERVER_IN_MAINTENANCE",
                                   "Server has matches in LOBBY_OPEN/LIVE/PAUSED", 422)
            srv["status"] = "MAINTENANCE"
        else:
            if srv["status"] == "ACTIVE":
                raise ApiError("ERR_VALIDATION", "Server already ACTIVE", 400)
            srv["status"] = "ACTIVE"
        touch(srv)
        return ok(serialize_server(srv))


# ---------------------------------------------------------------------------
# Routes: matches
# ---------------------------------------------------------------------------


@app.route("/api/matches/<mid>", methods=["GET"])
def get_match(mid):
    with LOCK:
        require_auth("OrganizerAdmin", "TournamentDirector", "TeamManager", "Referee", "AntiCheatInvestigator")
        return ok(get_match_or_404(mid))


@app.route("/api/matches", methods=["GET"])
def list_matches():
    with LOCK:
        require_auth("OrganizerAdmin", "TournamentDirector", "TeamManager", "Referee", "AntiCheatInvestigator")
        items = list(db["matches"].values())
        for f in ("tournament_id", "server_id", "next_match_id", "home_registration_id",
                  "away_registration_id", "winner_registration_id", "status"):
            v = request.args.get(f)
            if v is not None:
                items = [m for m in items if str(m.get(f)) == v]
        page, meta = paginate(items, sort_key=lambda m: (m["bracket_round"], m["bracket_slot"]))
        return ok(page, pagination=meta)


TACTICAL_PAUSE_LIMIT = 2


@app.route("/api/matches/<mid>/schedule", methods=["POST"])
def schedule_match(mid):
    with LOCK:
        require_auth("TournamentDirector")
        m = get_match_or_404(mid)
        body = get_json_body()
        server_id = req_string(body, "server_id")
        start = req_datetime(body, "scheduled_start_at")
        duration = req_int(body, "duration_minutes", 1)
        referee = req_string(body, "assigned_referee_id")
        # existence of server FK
        srv = get_server_or_404(server_id)

        if m["status"] != "PENDING":
            raise err_state("ERR_INVALID_MATCH_STATUS", f"Cannot schedule from {m['status']}")
        t = db["tournaments"].get(m["tournament_id"])
        if t is None:
            raise err_not_found("Tournament not found")
        if t["status"] not in {"SEEDED", "IN_PROGRESS"}:
            raise err_state("ERR_INVALID_TOURNAMENT_STATUS",
                            "Tournament must be SEEDED or IN_PROGRESS to schedule")
        if not m.get("home_registration_id") or not m.get("away_registration_id"):
            raise err_state("ERR_INVALID_MATCH_STATUS", "Both participants must be assigned before scheduling")
        if srv["tournament_id"] != m["tournament_id"]:
            raise err_validation("server_id belongs to a different tournament")
        if srv["status"] != "ACTIVE":
            raise err_biz("ERR_SERVER_IN_MAINTENANCE", "Server is in MAINTENANCE", 422)

        # minor curfew (priority 7 safety)
        minor_involved = False
        for reg_id in (m["home_registration_id"], m["away_registration_id"]):
            for s in db["roster_slots"].values():
                if s["registration_id"] == reg_id and s["status"] == "ACTIVE" and s.get("is_minor"):
                    minor_involved = True
                    break
            if minor_involved:
                break
        if minor_involved:
            end_dt = start + timedelta(minutes=duration)
            curfew_h, curfew_m = map(int, t["minor_curfew_local"].split(":"))
            curfew_minutes = curfew_h * 60 + curfew_m
            end_minutes = end_dt.hour * 60 + end_dt.minute + end_dt.second / 60.0
            if not (end_minutes < curfew_minutes):
                raise err_biz("ERR_MINOR_CURFEW_VIOLATION",
                              "Match with a minor must end strictly before curfew", 422)

        # server window overlap (priority 8 constraint) — half-open [start, end+15)
        new_start = start
        new_end = start + timedelta(minutes=duration + BUFFER_MINUTES)
        for other in db["matches"].values():
            if other["id"] == m["id"]:
                continue
            if other.get("server_id") != server_id:
                continue
            if other["status"] not in BOOKED_STATUSES:
                continue
            o_start = _parse_dt(other["scheduled_start_at"])
            if o_start is None:
                continue
            o_end = o_start + timedelta(minutes=(other.get("duration_minutes") or 0) + BUFFER_MINUTES)
            if new_start < o_end and o_start < new_end:
                raise ApiError("ERR_SERVER_WINDOW_CONFLICT",
                               "Half-open [start, end+15min) window collides on this server", 409)

        # schedule-in-past (priority 9 temporal)
        if start < now():
            raise err_biz("ERR_SCHEDULE_IN_PAST", "scheduled_start_at is in the past", 422)

        m["server_id"] = server_id
        m["scheduled_start_at"] = _iso_z(start)
        m["duration_minutes"] = duration
        m["assigned_referee_id"] = referee
        m["status"] = "SCHEDULED"
        touch(m)
        refresh_server_booking(server_id)
        return ok(m)


@app.route("/api/matches/<mid>/officiate", methods=["POST"])
def officiate_match(mid):
    with LOCK:
        auth = require_auth("Referee")
        m = get_match_or_404(mid)
        body = get_json_body()
        action = req_enum(body, "action", {"OPEN_LOBBY", "START", "PAUSE", "RESUME", "FORFEIT"})

        if action == "OPEN_LOBBY":
            if m["status"] != "SCHEDULED":
                raise err_state("ERR_INVALID_MATCH_STATUS", f"Cannot OPEN_LOBBY from {m['status']}")
            for reg_id in (m["home_registration_id"], m["away_registration_id"]):
                reg = db["registrations"].get(reg_id)
                if reg is None:
                    raise err_not_found("Registration not found")
                if reg["status"] != "LOCKED":
                    raise err_state("ERR_INVALID_MATCH_STATUS",
                                    "Both participants must be LOCKED to open lobby")
            srv = db["servers"].get(m.get("server_id"))
            if srv is not None and srv["status"] != "ACTIVE":
                raise err_biz("ERR_SERVER_IN_MAINTENANCE", "Server is in MAINTENANCE", 422)
            m["status"] = "LOBBY_OPEN"

        elif action == "START":
            if m["status"] != "LOBBY_OPEN":
                raise err_state("ERR_INVALID_MATCH_STATUS", f"Cannot START from {m['status']}")
            m["status"] = "LIVE"

        elif action == "PAUSE":
            if m["status"] != "LIVE":
                raise err_state("ERR_INVALID_MATCH_STATUS", f"Cannot PAUSE from {m['status']}")
            reason = req_enum(body, "pause_reason", {"TACTICAL", "TECHNICAL"})
            side = req_enum(body, "pausing_side", {"HOME", "AWAY"})
            if reason == "TACTICAL":
                key = "tactical_pauses_home" if side == "HOME" else "tactical_pauses_away"
                if m[key] >= TACTICAL_PAUSE_LIMIT:
                    raise err_biz("ERR_PAUSE_LIMIT_EXCEEDED",
                                  "Side has consumed 2 TACTICAL pauses", 422)
                m[key] += 1
            m["status"] = "PAUSED"

        elif action == "RESUME":
            if m["status"] != "PAUSED":
                raise err_state("ERR_INVALID_MATCH_STATUS", f"Cannot RESUME from {m['status']}")
            m["status"] = "LIVE"

        elif action == "FORFEIT":
            if m["status"] not in {"SCHEDULED", "LOBBY_OPEN"}:
                raise err_state("ERR_INVALID_MATCH_STATUS", f"Cannot FORFEIT from {m['status']}")
            side = req_enum(body, "forfeiting_side", {"HOME", "AWAY"})
            forfeiting = m["home_registration_id"] if side == "HOME" else m["away_registration_id"]
            winner = m["away_registration_id"] if side == "HOME" else m["home_registration_id"]
            old_server = m.get("server_id")
            m["status"] = "FORFEIT"
            m["winner_registration_id"] = winner
            m["forfeiting_registration_id"] = forfeiting
            m["completed_at"] = now_iso()
            m["dispute_window_closes_at"] = now_iso()
            propagate_winner(m, winner)
            refresh_server_booking(old_server)

        touch(m)
        return ok(m)


@app.route("/api/matches/<mid>/report-result", methods=["POST"])
def report_result(mid):
    with LOCK:
        auth = require_auth("Referee")
        m = get_match_or_404(mid)
        body = get_json_body()
        home_score = req_int(body, "home_score", 0)
        away_score = req_int(body, "away_score", 0)
        if home_score == away_score:
            raise err_validation("Ties are not allowed: home_score must differ from away_score")
        if m["status"] != "LIVE":
            raise err_state("ERR_INVALID_MATCH_STATUS", f"Cannot report result from {m['status']}")
        winner = m["home_registration_id"] if home_score > away_score else m["away_registration_id"]
        m["home_score"] = home_score
        m["away_score"] = away_score
        m["winner_registration_id"] = winner
        m["reported_by_user_id"] = auth.user_id
        m["completed_at"] = now_iso()
        close = now() + timedelta(hours=24)
        m["dispute_window_closes_at"] = _iso_z(close)
        m["status"] = "COMPLETED"
        propagate_winner(m, winner)
        touch(m)
        return ok(m)


@app.route("/api/matches/<mid>/confirm-result", methods=["POST"])
def confirm_result(mid):
    with LOCK:
        auth = require_auth("Referee")
        m = get_match_or_404(mid)
        get_json_body()
        if m["status"] != "COMPLETED":
            raise err_state("ERR_INVALID_MATCH_STATUS", f"Cannot confirm from {m['status']}")
        if m.get("reported_by_user_id") is not None and auth.user_id == m["reported_by_user_id"]:
            raise err_biz("ERR_SEGREGATION_OF_DUTIES",
                          "Reporter cannot confirm own result", 422)
        m["confirmed_by_user_id"] = auth.user_id
        m["status"] = "CONFIRMED"
        touch(m)
        return ok(m)


# ---------------------------------------------------------------------------
# Routes: disputes
# ---------------------------------------------------------------------------


@app.route("/api/disputes", methods=["POST"])
def create_dispute():
    with LOCK:
        auth = require_auth("TeamManager")
        body = get_json_body()
        match_id = req_string(body, "match_id")
        registration_id = req_string(body, "registration_id")
        reason = req_enum(body, "reason", {"RULE_VIOLATION", "SCORE_DISCREPANCY", "TECHNICAL_FAILURE", "CONDUCT"})
        details = req_string(body, "details")
        m = get_match_or_404(match_id)
        reg = get_registration_or_404(registration_id)
        if auth.user_id != reg["id"]:
            raise err_ownership("TeamManager identity must equal filing registration id")
        if m["status"] != "COMPLETED":
            raise err_state("ERR_INVALID_MATCH_STATUS", f"Cannot dispute a match in {m['status']}")
        if reg["id"] not in {m.get("home_registration_id"), m.get("away_registration_id")}:
            raise err_biz("ERR_NOT_MATCH_PARTICIPANT",
                          "Filing registration is not a participant of this match", 422)
        close = _parse_dt(m.get("dispute_window_closes_at"))
        if close is None or now() > close:
            raise err_biz("ERR_DISPUTE_WINDOW_CLOSED", "Dispute window has closed", 422)
        rec = stamp_new({
            "match_id": match_id,
            "registration_id": registration_id,
            "reason": reason,
            "details": details,
            "status": "FILED",
            "appeal_used": False,
            "ruling": None,
            "remedy": None,
        })
        db["disputes"][rec["id"]] = rec
        m["status"] = "UNDER_DISPUTE"
        touch(m)
        return ok(rec, 201)


@app.route("/api/disputes/<did>", methods=["GET"])
def get_dispute(did):
    with LOCK:
        require_auth("OrganizerAdmin", "TournamentDirector", "TeamManager")
        return ok(get_dispute_or_404(did))


@app.route("/api/disputes", methods=["GET"])
def list_disputes():
    with LOCK:
        require_auth("OrganizerAdmin", "TournamentDirector", "TeamManager")
        items = list(db["disputes"].values())
        for f in ("match_id", "registration_id", "status"):
            v = request.args.get(f)
            if v is not None:
                items = [d for d in items if str(d.get(f)) == v]
        page, meta = paginate(items, sort_key=lambda d: (d["created_at"], d["id"]))
        return ok(page, pagination=meta)


@app.route("/api/disputes/<did>/adjudicate", methods=["POST"])
def adjudicate_dispute(did):
    with LOCK:
        auth = require_auth("TournamentDirector")
        d = get_dispute_or_404(did)
        body = get_json_body()
        action = req_enum(body, "action", {"START_REVIEW", "RULE_UPHELD", "RULE_OVERTURNED"})
        m = get_match_or_404(d["match_id"])

        if action == "START_REVIEW":
            if d["status"] not in {"FILED", "APPEALED"}:
                raise err_state("ERR_INVALID_DISPUTE_STATUS", f"Cannot START_REVIEW from {d['status']}")
            d["status"] = "UNDER_REVIEW"

        elif action == "RULE_UPHELD":
            if d["status"] != "UNDER_REVIEW":
                raise err_state("ERR_INVALID_DISPUTE_STATUS", f"Cannot RULE_UPHELD from {d['status']}")
            d["ruling"] = "UPHELD"
            d["status"] = "CLOSED_UPHELD"
            if m["status"] == "UNDER_DISPUTE":
                m["status"] = "CONFIRMED"
                m["confirmed_by_user_id"] = auth.user_id
                touch(m)

        elif action == "RULE_OVERTURNED":
            if d["status"] != "UNDER_REVIEW":
                raise err_state("ERR_INVALID_DISPUTE_STATUS", f"Cannot RULE_OVERTURNED from {d['status']}")
            remedy = req_enum(body, "remedy", {"WINNER_FLIP", "REMATCH"})
            nxt = db["matches"].get(m.get("next_match_id")) if m.get("next_match_id") else None
            advanced_filled = False
            old_winner = m.get("winner_registration_id")
            if nxt is not None and old_winner is not None:
                if nxt.get("home_registration_id") == old_winner or nxt.get("away_registration_id") == old_winner:
                    advanced_filled = True
            if remedy == "WINNER_FLIP":
                if nxt is not None and nxt["status"] not in {"PENDING", "SCHEDULED"}:
                    raise ApiError("ERR_BRACKET_LOCKED_DOWNSTREAM",
                                   "Downstream match has already started", 409)
            else:  # REMATCH
                if nxt is not None and advanced_filled and nxt["status"] != "PENDING":
                    raise ApiError("ERR_BRACKET_LOCKED_DOWNSTREAM",
                                   "Cannot re-queue into a started match", 409)
            d["ruling"] = "OVERTURNED"
            d["remedy"] = remedy
            d["status"] = "CLOSED_OVERTURNED"

            if m["status"] == "UNDER_DISPUTE":
                m["status"] = "OVERTURNED"
                if remedy == "WINNER_FLIP":
                    home = m.get("home_registration_id")
                    away = m.get("away_registration_id")
                    new_winner = away if old_winner == home else home
                    m["winner_registration_id"] = new_winner
                    if nxt is not None and advanced_filled:
                        replace_in_next_slot(nxt, old_winner, new_winner)
                    m["status"] = "CONFIRMED"
                    m["confirmed_by_user_id"] = auth.user_id
                else:  # REMATCH
                    if nxt is not None and advanced_filled and nxt["status"] == "PENDING":
                        clear_in_next_slot(nxt, old_winner)
                    m["home_score"] = None
                    m["away_score"] = None
                    m["winner_registration_id"] = None
                    m["completed_at"] = None
                    m["dispute_window_closes_at"] = None
                    m["status"] = "SCHEDULED"
                touch(m)

        touch(d)
        return ok(d)


@app.route("/api/disputes/<did>/appeal", methods=["POST"])
def appeal_dispute(did):
    with LOCK:
        auth = require_auth("TeamManager")
        d = get_dispute_or_404(did)
        reg = get_registration_or_404(d["registration_id"])
        if auth.user_id != reg["id"]:
            raise err_ownership("TeamManager identity must equal filing registration id")
        if d["status"] != "CLOSED_UPHELD":
            raise err_state("ERR_INVALID_DISPUTE_STATUS", f"Cannot appeal from {d['status']}")
        if d["appeal_used"]:
            raise err_biz("ERR_APPEAL_EXHAUSTED", "Appeal already used", 422)
        d["status"] = "APPEALED"
        d["appeal_used"] = True
        touch(d)
        return ok(d)


# ---------------------------------------------------------------------------
# Routes: integrity cases
# ---------------------------------------------------------------------------


@app.route("/api/integrity-cases", methods=["POST"])
def create_integrity_case():
    with LOCK:
        auth = require_auth("AntiCheatInvestigator")
        body = get_json_body()
        player_id = req_string(body, "player_id")
        get_player_or_404(player_id)
        match_id = body.get("match_id")
        if match_id is not None:
            if not isinstance(match_id, str):
                raise err_validation("match_id must be a string")
            get_match_or_404(match_id)
        evidence = req_string(body, "evidence_summary")
        rec = stamp_new({
            "player_id": player_id,
            "match_id": match_id,
            "evidence_summary": evidence,
            "status": "OPEN",
            "opened_by_user_id": auth.user_id,
            "resolved_by_user_id": None,
            "strike_issued": False,
            "resolved_at": None,
        })
        db["integrity_cases"][rec["id"]] = rec
        return ok(rec, 201)


@app.route("/api/integrity-cases/<cid>", methods=["GET"])
def get_integrity_case(cid):
    with LOCK:
        require_auth("OrganizerAdmin", "AntiCheatInvestigator", "TournamentDirector")
        return ok(get_case_or_404(cid))


@app.route("/api/integrity-cases", methods=["GET"])
def list_integrity_cases():
    with LOCK:
        require_auth("OrganizerAdmin", "AntiCheatInvestigator", "TournamentDirector")
        items = list(db["integrity_cases"].values())
        for f in ("player_id", "match_id", "status"):
            v = request.args.get(f)
            if v is not None:
                items = [c for c in items if str(c.get(f)) == v]
        page, meta = paginate(items, sort_key=lambda c: (c["created_at"], c["id"]))
        return ok(page, pagination=meta)


STRIKE_LIMIT = 3


@app.route("/api/integrity-cases/<cid>/resolve", methods=["POST"])
def resolve_integrity_case(cid):
    with LOCK:
        auth = require_auth("AntiCheatInvestigator")
        c = get_case_or_404(cid)
        body = get_json_body()
        action = req_enum(body, "action", {"BEGIN_INVESTIGATION", "RESOLVE"})

        if action == "BEGIN_INVESTIGATION":
            if c["status"] != "OPEN":
                raise err_state("ERR_INVALID_CASE_STATUS", f"Cannot BEGIN_INVESTIGATION from {c['status']}")
            c["status"] = "INVESTIGATING"
        else:  # RESOLVE
            if c["status"] != "INVESTIGATING":
                raise err_state("ERR_INVALID_CASE_STATUS", f"Cannot RESOLVE from {c['status']}")
            outcome = req_enum(body, "outcome", {"CLEARED", "VIOLATION"})
            # SoD: if match_id non-null, X-User-ID != that match's assigned_referee_id
            if c.get("match_id"):
                m = db["matches"].get(c["match_id"])
                if m is not None and m.get("assigned_referee_id") is not None \
                        and auth.user_id == m["assigned_referee_id"]:
                    raise err_biz("ERR_SEGREGATION_OF_DUTIES",
                                  "Investigator refereed the implicated match", 422)
            player = get_player_or_404(c["player_id"])
            c["resolved_by_user_id"] = auth.user_id
            c["resolved_at"] = now_iso()
            if outcome == "CLEARED":
                c["status"] = "RESOLVED_CLEARED"
            else:
                c["status"] = "RESOLVED_VIOLATION"
                c["strike_issued"] = True
                player["ac_strike_events"].append({
                    "integrity_case_id": c["id"],
                    "issued_at": now_iso(),
                })
                touch(player)
                if compute_active_strike_count(player) >= STRIKE_LIMIT:
                    if player["eligibility_status"] != "BANNED":
                        player["eligibility_status"] = "BANNED"
                        touch(player)
                    dq_cascade_for_player(player)
        touch(c)
        return ok(c)


# ---------------------------------------------------------------------------
# Routes: talents and bookings
# ---------------------------------------------------------------------------


@app.route("/api/talents", methods=["POST"])
def create_talent():
    with LOCK:
        require_auth("BroadcastProducer")
        body = get_json_body()
        stage_name = req_string(body, "stage_name")
        home_region = req_enum(body, "home_region", REGIONS)
        day_rate = req_int(body, "day_rate_cents", 0)
        cross_region = opt_bool(body, "cross_region", False)
        for t in db["talents"].values():
            if t["stage_name"] == stage_name:
                raise ApiError("ERR_HANDLE_TAKEN", "stage_name already in use", 409)
        rec = stamp_new({
            "stage_name": stage_name,
            "home_region": home_region,
            "day_rate_cents": day_rate,
            "cross_region": cross_region,
        })
        db["talents"][rec["id"]] = rec
        return ok(rec, 201)


def talent_window_conflict(talent_id, start, end, exclude_booking_id=None):
    """Closed-interval overlap among CONFIRMED bookings of the same talent."""
    for b in db["talent_bookings"].values():
        if b["talent_id"] != talent_id:
            continue
        if exclude_booking_id is not None and b["id"] == exclude_booking_id:
            continue
        if b["status"] != "CONFIRMED":
            continue
        b_start = _parse_dt(b["shift_start_at"])
        b_end = _parse_dt(b["shift_end_at"])
        if b_start is None or b_end is None:
            continue
        # closed intervals: overlap when start <= other_end AND other_start <= end
        if start <= b_end and b_start <= end:
            return True
    return False


@app.route("/api/talent-bookings", methods=["POST"])
def create_booking():
    with LOCK:
        require_auth("BroadcastProducer")
        body = get_json_body()
        tid = req_string(body, "tournament_id")
        talent_id = req_string(body, "talent_id")
        stage_label = req_string(body, "stage_label")
        start = req_datetime(body, "shift_start_at")
        end = req_datetime(body, "shift_end_at")
        t = get_tournament_or_404(tid)
        talent = get_talent_or_404(talent_id)
        if not (end > start):
            raise err_validation("shift_end_at must be strictly after shift_start_at")
        if talent["home_region"] != t["region"] and not talent["cross_region"]:
            raise err_biz("ERR_TALENT_REGION_MISMATCH",
                          "Talent home region differs and cross_region is false", 422)
        if talent_window_conflict(talent_id, start, end):
            raise ApiError("ERR_TALENT_WINDOW_CONFLICT",
                           "Closed-interval shift collides with a CONFIRMED booking", 409)
        quote = talent_fee_provisional(talent, start, end)
        rec = stamp_new({
            "tournament_id": tid,
            "talent_id": talent_id,
            "stage_label": stage_label,
            "shift_start_at": _iso_z(start),
            "shift_end_at": _iso_z(end),
            "status": "TENTATIVE",
            "fee_quote_cents": quote,
            "fee_final_cents": None,
        })
        db["talent_bookings"][rec["id"]] = rec
        return ok(rec, 201)


@app.route("/api/talent-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    with LOCK:
        require_auth("OrganizerAdmin", "BroadcastProducer")
        return ok(get_booking_or_404(bid))


@app.route("/api/talent-bookings", methods=["GET"])
def list_bookings():
    with LOCK:
        require_auth("OrganizerAdmin", "BroadcastProducer")
        items = list(db["talent_bookings"].values())
        for f in ("tournament_id", "talent_id", "status"):
            v = request.args.get(f)
            if v is not None:
                items = [b for b in items if str(b.get(f)) == v]
        page, meta = paginate(items, sort_key=lambda b: (b["created_at"], b["id"]))
        return ok(page, pagination=meta)


@app.route("/api/talent-bookings/<bid>/transition", methods=["POST"])
def transition_booking(bid):
    with LOCK:
        require_auth("BroadcastProducer")
        b = get_booking_or_404(bid)
        body = get_json_body()
        action = req_enum(body, "action", {"CONFIRM", "SETTLE", "CANCEL"})
        t = db["tournaments"].get(b["tournament_id"])
        if t is None:
            raise err_not_found("Tournament not found")
        talent = get_talent_or_404(b["talent_id"])

        if action == "CONFIRM":
            if b["status"] != "TENTATIVE":
                raise err_state("ERR_INVALID_BOOKING_STATUS", f"Cannot CONFIRM from {b['status']}")
            if t["status"] not in {"SEEDED", "IN_PROGRESS"}:
                raise err_state("ERR_INVALID_BOOKING_STATUS",
                                "Tournament must be SEEDED or IN_PROGRESS to confirm")
            start = _parse_dt(b["shift_start_at"])
            end = _parse_dt(b["shift_end_at"])
            if talent_window_conflict(b["talent_id"], start, end, exclude_booking_id=b["id"]):
                raise ApiError("ERR_TALENT_WINDOW_CONFLICT",
                               "Closed-interval shift collides with a CONFIRMED booking", 409)
            b["status"] = "CONFIRMED"
        elif action == "SETTLE":
            if b["status"] != "CONFIRMED":
                raise err_state("ERR_INVALID_BOOKING_STATUS", f"Cannot SETTLE from {b['status']}")
            if t["status"] not in {"IN_PROGRESS", "COMPLETED"}:
                raise err_state("ERR_INVALID_BOOKING_STATUS",
                                "Tournament must be IN_PROGRESS or COMPLETED to settle")
            start = _parse_dt(b["shift_start_at"])
            end = _parse_dt(b["shift_end_at"])
            b["fee_final_cents"] = talent_fee_final(talent, t, start, end)
            b["status"] = "SETTLED"
        else:  # CANCEL
            if b["status"] not in {"TENTATIVE", "CONFIRMED"}:
                raise err_state("ERR_INVALID_BOOKING_STATUS", f"Cannot CANCEL from {b['status']}")
            b["status"] = "CANCELLED"
        touch(b)
        return ok(b)


# ---------------------------------------------------------------------------
# Routes: payout records
# ---------------------------------------------------------------------------


@app.route("/api/payout-records/<pid>", methods=["GET"])
def get_payout(pid):
    with LOCK:
        require_auth("OrganizerAdmin", "PayoutOfficer", "Player")
        return ok(get_payout_or_404(pid))


@app.route("/api/payout-records", methods=["GET"])
def list_payouts():
    with LOCK:
        require_auth("OrganizerAdmin", "PayoutOfficer", "Player")
        items = list(db["payout_records"].values())
        for f in ("tournament_id", "payee_player_id", "registration_id", "disbursement_status"):
            v = request.args.get(f)
            if v is not None:
                items = [p for p in items if str(p.get(f)) == v]

        def payout_key(p):
            reg = db["registrations"].get(p["registration_id"])
            created = reg["created_at"] if reg else ""
            return (p["placement"], created, p["id"])

        page, meta = paginate(items, sort_key=payout_key)
        return ok(page, pagination=meta)


DOC_TYPES = {"W9", "W8BEN", "GUARDIAN_W9"}


@app.route("/api/payout-records/<pid>/submit-docs", methods=["POST"])
def submit_docs(pid):
    with LOCK:
        auth = require_auth("Player")
        p = get_payout_or_404(pid)
        body = get_json_body()
        doc_type = req_enum(body, "doc_type", DOC_TYPES)
        guardian_name = body.get("guardian_name")
        guardian_email = body.get("guardian_email")
        if auth.user_id != p["payee_player_id"]:
            raise err_ownership("Player identity must equal payee_player_id")
        if p["payee_is_minor"]:
            if doc_type != "GUARDIAN_W9" or not guardian_name or not guardian_email:
                raise err_validation(
                    "Minor payee must submit doc_type GUARDIAN_W9 with guardian_name and guardian_email")
        if p["disbursement_status"] != "COMPUTED":
            raise err_state("ERR_INVALID_PAYOUT_STATUS",
                            "Documents cannot change after approval")
        if p["doc_status"] not in {"PENDING", "REJECTED"}:
            raise err_state("ERR_INVALID_PAYOUT_STATUS",
                            f"Cannot submit docs from doc_status {p['doc_status']}")
        p["doc_type"] = doc_type
        if p["payee_is_minor"]:
            p["guardian_name"] = guardian_name
            p["guardian_email"] = guardian_email
        p["doc_status"] = "SUBMITTED"
        touch(p)
        return ok(p)


@app.route("/api/payout-records/<pid>/verify-docs", methods=["POST"])
def verify_docs(pid):
    with LOCK:
        auth = require_auth("PayoutOfficer")
        p = get_payout_or_404(pid)
        body = get_json_body()
        action = req_enum(body, "action", {"VERIFY", "REJECT"})
        if p["doc_status"] != "SUBMITTED":
            raise err_state("ERR_INVALID_PAYOUT_STATUS",
                            f"Cannot verify docs from doc_status {p['doc_status']}")
        if action == "VERIFY":
            p["doc_status"] = "VERIFIED"
            p["doc_verified_by_user_id"] = auth.user_id
        else:
            p["doc_status"] = "REJECTED"
        touch(p)
        return ok(p)


DOC_THRESHOLD_CENTS = 60000


@app.route("/api/payout-records/<pid>/approve", methods=["POST"])
def approve_payout(pid):
    with LOCK:
        auth = require_auth("PayoutOfficer")
        p = get_payout_or_404(pid)
        get_json_body()
        if p["disbursement_status"] != "COMPUTED":
            raise err_state("ERR_INVALID_PAYOUT_STATUS",
                            f"Cannot approve from disbursement_status {p['disbursement_status']}")
        # fiscal (priority 10): FINAL mode required — PRD §3.8 lists this gate
        # first in the approve prose, so it is evaluated before the doc gates.
        if p["compute_run_mode"] != "FINAL":
            raise err_biz("ERR_PAYOUT_NOT_FINAL", "Approve requires compute_run_mode FINAL", 422)
        # safety gates (priority 7)
        if p["payee_is_minor"]:
            if not (p["doc_status"] == "VERIFIED" and p["doc_type"] == "GUARDIAN_W9"):
                raise err_biz("ERR_GUARDIAN_DOCS_REQUIRED",
                              "Minor payee requires VERIFIED GUARDIAN_W9", 422)
        if p["gross_amount_cents"] >= DOC_THRESHOLD_CENTS:
            if p["doc_status"] != "VERIFIED":
                raise err_biz("ERR_TAX_DOCS_REQUIRED",
                              "gross >= 60000 requires VERIFIED docs", 422)
        if p.get("doc_verified_by_user_id") is not None and auth.user_id == p["doc_verified_by_user_id"]:
            raise err_biz("ERR_SEGREGATION_OF_DUTIES",
                          "Verifier cannot approve own docs", 422)

        # withholding
        if p["doc_status"] == "VERIFIED" and p["doc_type"] == "W9":
            rate = dec(0)
        elif p["doc_status"] == "VERIFIED" and p["doc_type"] == "W8BEN":
            rate = dec(30)
        elif p["doc_status"] == "VERIFIED" and p["doc_type"] == "GUARDIAN_W9":
            rate = dec(0)
        else:
            rate = dec(24)
        withholding = round_half_up_int(dec(p["gross_amount_cents"]) * rate / dec(100))
        p["withholding_cents"] = withholding
        p["net_amount_cents"] = p["gross_amount_cents"] - withholding
        p["approved_by_user_id"] = auth.user_id
        p["disbursement_status"] = "APPROVED"
        touch(p)
        return ok(p)


@app.route("/api/payout-records/<pid>/pay", methods=["POST"])
def pay_payout(pid):
    with LOCK:
        require_auth("PayoutOfficer")
        p = get_payout_or_404(pid)
        get_json_body()
        if p["disbursement_status"] != "APPROVED":
            raise err_state("ERR_INVALID_PAYOUT_STATUS",
                            f"Cannot pay from disbursement_status {p['disbursement_status']}")
        p["disbursement_status"] = "PAID"
        p["paid_at"] = now_iso()
        touch(p)
        return ok(p)


# ---------------------------------------------------------------------------
# Routes: sponsor deals
# ---------------------------------------------------------------------------

CONTENT_RIGHTS = {"VOD", "CLIPS", "REPLAYS", "LOGOS"}
RIGHTS_TIERS = {"TITLE", "PRESENTING", "SUPPORTING"}


@app.route("/api/sponsor-deals", methods=["POST"])
def create_sponsor_deal():
    with LOCK:
        require_auth("OrganizerAdmin")
        body = get_json_body()
        tid = req_string(body, "tournament_id")
        get_tournament_or_404(tid)
        sponsor_name = req_string(body, "sponsor_name")
        contact_user_id = req_string(body, "contact_user_id")
        rights_tier = req_enum(body, "rights_tier", RIGHTS_TIERS)
        bonus_cents = req_int(body, "bonus_cents", 0)
        content_rights = req_present(body, "content_rights")
        if not isinstance(content_rights, list) or any(
            (not isinstance(x, str)) or x not in CONTENT_RIGHTS for x in content_rights
        ):
            raise err_validation("content_rights must be a subset of [VOD, CLIPS, REPLAYS, LOGOS]")
        rec = stamp_new({
            "tournament_id": tid,
            "sponsor_name": sponsor_name,
            "contact_user_id": contact_user_id,
            "rights_tier": rights_tier,
            "bonus_cents": bonus_cents,
            "content_rights": list(content_rights),
            "status": "PROPOSED",
            "activated_at": None,
        })
        db["sponsor_deals"][rec["id"]] = rec
        return ok(rec, 201)


@app.route("/api/sponsor-deals/<did>", methods=["GET"])
def get_sponsor_deal(did):
    with LOCK:
        require_auth("OrganizerAdmin", "SponsorManager", "TournamentDirector")
        return ok(get_deal_or_404(did))


@app.route("/api/sponsor-deals", methods=["GET"])
def list_sponsor_deals():
    with LOCK:
        require_auth("OrganizerAdmin", "SponsorManager", "TournamentDirector")
        items = list(db["sponsor_deals"].values())
        for f in ("tournament_id", "status"):
            v = request.args.get(f)
            if v is not None:
                items = [d for d in items if str(d.get(f)) == v]
        page, meta = paginate(items, sort_key=lambda d: (d["created_at"], d["id"]))
        return ok(page, pagination=meta)


@app.route("/api/sponsor-deals/<did>/transition", methods=["POST"])
def transition_sponsor_deal(did):
    with LOCK:
        auth = require_auth("OrganizerAdmin", "SponsorManager")
        d = get_deal_or_404(did)
        body = get_json_body()
        action = req_enum(body, "action", {"CONTRACT", "ACTIVATE", "VOID"})

        if action == "CONTRACT":
            if auth.role != "OrganizerAdmin":
                raise err_forbidden()
            if d["status"] != "PROPOSED":
                raise err_state("ERR_INVALID_DEAL_STATUS", f"Cannot CONTRACT from {d['status']}")
            d["status"] = "CONTRACTED"
        elif action == "ACTIVATE":
            if auth.role != "SponsorManager":
                raise err_forbidden()
            if d["contact_user_id"] != auth.user_id:
                raise err_ownership("SponsorManager identity must equal contact_user_id")
            if d["status"] != "CONTRACTED":
                raise err_state("ERR_INVALID_DEAL_STATUS", f"Cannot ACTIVATE from {d['status']}")
            d["status"] = "ACTIVATED"
            d["activated_at"] = now_iso()
        else:  # VOID
            if auth.role != "OrganizerAdmin":
                raise err_forbidden()
            if d["status"] not in {"PROPOSED", "CONTRACTED", "ACTIVATED"}:
                raise err_state("ERR_INVALID_DEAL_STATUS", f"Cannot VOID from {d['status']}")
            d["status"] = "VOID"
        touch(d)
        return ok(d)


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

init_clock()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Prefer waitress: a production-grade pure-Python WSGI server that accepts
    # a proper connection backlog and survives heavy concurrent load (the
    # 8-round per-test-server sweep boots ~8x servers at once). The Werkzeug
    # dev server resets/drops connections when CPU-starved, surfacing as
    # flaky ConnectionReset / IncompleteRead / "could not be restarted"
    # failures. Behaviour is identical — this only changes the transport.
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=port, threads=8, backlog=1024,
              connection_limit=1000, channel_timeout=60, _quiet=True)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
