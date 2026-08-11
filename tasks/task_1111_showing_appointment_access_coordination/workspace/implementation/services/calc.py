"""Calculations and cascades per PRD §3 and scaffold §1.3.

Covers: approval deadline, access window, agent standing ladder (with CASCADE B
fan-out on transition into SUSPENDED), feedback score rollup (pinned rounding
order), daily showing count, buffered overlap, seller report metrics, the
listing-withdrawal cascade (CASCADE A), buyer cancellation, and the six-step
expiration sweep.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
import errors
from services import core

MIN_REVIEW_WINDOW_MINUTES = 30
CONFIRM_DEADLINE_MINUTES = 60
VACANT_EARLY_ENTRY_MINUTES = 60
VACANT_EXIT_GRACE_MINUTES = 60
OCCUPIED_EARLY_ENTRY_MINUTES = 15
NO_SHOW_WEIGHT = 25
LATE_CANCEL_WEIGHT = 10
RESTRICT_POINTS = 15
SUSPEND_POINTS = 30
STRIKE_TTL_DAYS = 90
FEEDBACK_DUE_HOURS = 72
LATE_CANCEL_WINDOW_HOURS = 24
MAX_DURATION_MINUTES = 120

VACANT_INSTRUCTIONS = ("Vacant property: self-access with lockbox/code "
                       "anytime inside the access window.")
OCCUPIED_INSTRUCTIONS = ("Occupied property: occupant-approved access; "
                         "arrive no earlier than 15 minutes before start.")

OCCUPANCY_STATES = {"PENDING_APPROVAL", "APPROVED", "CONFIRMED"}
TERMINAL_STATES = {"COMPLETED", "NO_SHOW", "CANCELLED", "EXPIRED"}


# ---------------------------------------------------------------------------
# calc_approval_deadline (PRD §3.3)
# ---------------------------------------------------------------------------

def compute_deadlines(listing, seller, start_at, created_at):
    """Returns (approval_deadline, confirm_by_deadline, born_approved)."""
    confirm_by = start_at - timedelta(minutes=CONFIRM_DEADLINE_MINUTES)
    if listing["occupancy_type"] == "VACANT" and seller["auto_approve"]:
        return created_at, confirm_by, True
    floor = created_at + timedelta(minutes=MIN_REVIEW_WINDOW_MINUTES)
    cap = min(created_at + timedelta(minutes=seller["approval_timeout_minutes"]),
              start_at - timedelta(minutes=listing["min_notice_minutes"]))
    return max(floor, cap), confirm_by, False


# ---------------------------------------------------------------------------
# calc_access_window (PRD §3.5)
# ---------------------------------------------------------------------------

def access_window(listing, showing):
    if listing["occupancy_type"] == "VACANT":
        return (showing["start_at"] - timedelta(minutes=VACANT_EARLY_ENTRY_MINUTES),
                showing["end_at"] + timedelta(minutes=VACANT_EXIT_GRACE_MINUTES),
                VACANT_INSTRUCTIONS)
    return (showing["start_at"] - timedelta(minutes=OCCUPIED_EARLY_ENTRY_MINUTES),
            showing["end_at"] + timedelta(minutes=listing["buffer_minutes"]),
            OCCUPIED_INSTRUCTIONS)


# ---------------------------------------------------------------------------
# calc_agent_standing (PRD §3.6) — with CASCADE B fan-out
# ---------------------------------------------------------------------------

def recompute_agent_standing(agent):
    """Recompute points + standing. On transition INTO SUSPENDED, cancel the
    agent's future requests (CASCADE B hop 3/4). Returns nothing."""
    points = sum(s["weight"] for s in core.strikes_of_agent(agent["id"])
                 if s["status"] == "ACTIVE")
    agent["active_strike_points"] = points
    if points >= SUSPEND_POINTS:
        new_standing = "SUSPENDED"
    elif points >= RESTRICT_POINTS:
        new_standing = "RESTRICTED"
    else:
        new_standing = "GOOD_STANDING"
    old = agent["standing"]
    if new_standing == old:
        # Still refresh points visibility timestamp semantics: points changed but
        # standing did not — PRD ties version bumps to standing changes and to
        # explicit mutations. Points are computed state; only bump on change.
        return
    agent["standing"] = new_standing
    core.touch(agent)
    if new_standing == "SUSPENDED" and old != "SUSPENDED":
        _suspend_cascade(agent)


def _suspend_cascade(agent):
    """CASCADE B hop 3/4: cancel every future request of the agent in
    {PENDING_APPROVAL, APPROVED, CONFIRMED}."""
    now = clock.now()
    for req in list(db.showing_requests.values()):
        if (req["buyer_agent_id"] == agent["id"]
                and req["status"] in OCCUPANCY_STATES
                and req["start_at"] > now):
            _system_cancel_request(req)


def _system_cancel_request(req):
    """System-cancellation shape depends on how far the request progressed
    (PRD §3.6 closing note)."""
    now = clock.now()
    was_confirmed = req["status"] == "CONFIRMED"
    req["status"] = "CANCELLED"
    req["cancel_actor"] = "SYSTEM"
    req["cancelled_at"] = now
    core.touch(req)
    if was_confirmed:
        listing = db.listings.get(req["listing_id"])
        if listing is not None:
            listing["confirmed_showing_count"] -= 1
            core.touch(listing)
        for cred in core.credentials_of_request(req["id"]):
            if cred["status"] == "ISSUED":
                cred["status"] = "REVOKED"
                core.touch(cred)
                core.add_activity(req["listing_id"], req["id"],
                                  "CREDENTIAL_REVOKED", "SYSTEM",
                                  "Credential revoked by system cancellation.")
        for fb in core.feedback_of_request(req["id"]):
            if fb["status"] == "SCHEDULED":
                fb["status"] = "CANCELLED"
                core.touch(fb)
    core.add_activity(req["listing_id"], req["id"], "CANCELLED", "SYSTEM",
                      "Showing request cancelled by system.")


# ---------------------------------------------------------------------------
# Strikes
# ---------------------------------------------------------------------------

def create_strike(agent_id, showing_request_id, strike_type, listing_id):
    weight = NO_SHOW_WEIGHT if strike_type == "NO_SHOW" else LATE_CANCEL_WEIGHT
    strike = core.stamp_new({
        "agent_id": agent_id,
        "showing_request_id": showing_request_id,
        "strike_type": strike_type,
        "weight": weight,
        "status": "ACTIVE",
        "expires_at": clock.now() + timedelta(days=STRIKE_TTL_DAYS),
    })
    db.strike_records[strike["id"]] = strike
    core.add_activity(listing_id, showing_request_id, "STRIKE_ISSUED", "SYSTEM",
                      f"{strike_type} strike issued (weight {weight}).")
    agent = db.agents.get(agent_id)
    if agent is not None:
        recompute_agent_standing(agent)
    return strike


# ---------------------------------------------------------------------------
# calc_feedback_score_rollup (PRD §3.7) — pinned rounding order
# ---------------------------------------------------------------------------

_W = (Decimal("0.30"), Decimal("0.25"), Decimal("0.20"), Decimal("0.15"), Decimal("0.10"))


def per_feedback_score(q1, q2, q3, q4, q5):
    raw = sum(w * Decimal(q) for w, q in zip(_W, (q1, q2, q3, q4, q5)))
    return float(raw.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def recompute_listing_avg_feedback(listing):
    scores = [Decimal(str(f["overall_score"]))
              for f in db.feedback_requests.values()
              if f["status"] == "SUBMITTED"
              and db.showing_requests.get(f["showing_request_id"], {}).get("listing_id") == listing["id"]]
    if not scores:
        avg = Decimal("0.0")
    else:
        avg = (sum(scores) / Decimal(len(scores))).quantize(Decimal("0.1"),
                                                            rounding=ROUND_HALF_UP)
    listing["avg_feedback_score"] = float(avg)
    core.touch(listing)


# ---------------------------------------------------------------------------
# calc_daily_showing_count / calc_buffered_overlap (PRD §3.3)
# ---------------------------------------------------------------------------

def daily_showing_count(listing_id, start_at, exclude_id=None):
    day = start_at.date()
    return sum(1 for r in db.showing_requests.values()
               if r["listing_id"] == listing_id
               and r["status"] in OCCUPANCY_STATES
               and r["id"] != exclude_id
               and r["start_at"].date() == day)


def overlap_conflict(listing, new_start, new_end, exclude_id=None):
    """Buffered half-open overlap: strict inequalities; touching allowed."""
    buf = timedelta(minutes=listing["buffer_minutes"])
    for r in db.showing_requests.values():
        if (r["listing_id"] != listing["id"]
                or r["status"] not in OCCUPANCY_STATES
                or r["id"] == exclude_id):
            continue
        if new_start < r["end_at"] + buf and r["start_at"] - buf < new_end:
            return True
    return False


def blackout_conflict(listing_id, new_start, new_end):
    """Closed-interval intersection, no buffer; touching counts."""
    for b in db.blackout_windows.values():
        if b["listing_id"] != listing_id:
            continue
        if new_start <= b["end_at"] and b["start_at"] <= new_end:
            return True
    return False


def validate_new_window(listing, start_at, end_at, exclude_id=None):
    """PRD §2.7 stages 9-12, 14 in pinned order: time-range, lead time,
    buffered overlap, blackout, daily cap."""
    now = clock.now()
    # Stage 9: time-range sanity
    if end_at <= start_at or (end_at - start_at) > timedelta(minutes=MAX_DURATION_MINUTES):
        raise errors.err(errors.ERR_INVALID_TIME_RANGE,
                         "end_at must be later than start_at and duration <= 120 minutes.", 422)
    # Stage 10: lead time
    if start_at - now < timedelta(minutes=listing["min_notice_minutes"]):
        raise errors.err(errors.ERR_INSUFFICIENT_LEAD_TIME,
                         "start_at does not satisfy the listing's minimum notice.", 422)
    # Stage 11: buffered overlap
    if overlap_conflict(listing, start_at, end_at, exclude_id=exclude_id):
        raise errors.err(errors.ERR_SHOWING_OVERLAP_CONFLICT,
                         "Window conflicts with an existing showing under the buffered rule.", 409)
    # Stage 12: blackout intersection
    if blackout_conflict(listing["id"], start_at, end_at):
        raise errors.err(errors.ERR_BLACKOUT_CONFLICT,
                         "Window intersects a blackout window of the listing.", 409)
    # Stage 14: daily cap
    if daily_showing_count(listing["id"], start_at, exclude_id=exclude_id) \
            >= listing["max_showings_per_day"]:
        raise errors.err(errors.ERR_DAILY_SHOWING_LIMIT,
                         "Listing has reached its daily showing cap.", 409)


# ---------------------------------------------------------------------------
# CASCADE A — listing withdrawal (PRD §3.2)
# ---------------------------------------------------------------------------

def cascade_withdraw_listing(listing):
    for req in [r for r in core.requests_of_listing(listing["id"])
                if r["status"] in OCCUPANCY_STATES]:
        _system_cancel_request(req)


# ---------------------------------------------------------------------------
# Buyer-agent cancellation (PRD §3.6)
# ---------------------------------------------------------------------------

def buyer_cancel_request(req, actor_role):
    """Cancel from PENDING_APPROVAL / APPROVED / CONFIRMED by the buyer agent.
    CONFIRMED cancellation runs the full unwind + possible LATE_CANCEL strike."""
    now = clock.now()
    was_confirmed = req["status"] == "CONFIRMED"
    req["status"] = "CANCELLED"
    req["cancel_actor"] = "BUYER_AGENT"
    req["cancelled_at"] = now
    core.touch(req)
    if was_confirmed:
        listing = db.listings.get(req["listing_id"])
        if listing is not None:
            listing["confirmed_showing_count"] -= 1
            core.touch(listing)
        for cred in core.credentials_of_request(req["id"]):
            if cred["status"] == "ISSUED":
                cred["status"] = "REVOKED"
                core.touch(cred)
                core.add_activity(req["listing_id"], req["id"],
                                  "CREDENTIAL_REVOKED", actor_role,
                                  "Credential revoked on buyer cancellation.")
        for fb in core.feedback_of_request(req["id"]):
            if fb["status"] == "SCHEDULED":
                fb["status"] = "CANCELLED"
                core.touch(fb)
        # Late cancel: start_at - now < 24h
        if req["start_at"] - now < timedelta(hours=LATE_CANCEL_WINDOW_HOURS):
            create_strike(req["buyer_agent_id"], req["id"], "LATE_CANCEL",
                          req["listing_id"])
    core.add_activity(req["listing_id"], req["id"], "CANCELLED", actor_role,
                      "Showing request cancelled by buyer agent.")


# ---------------------------------------------------------------------------
# Expiration sweep (PRD §2.11) — six pinned steps
# ---------------------------------------------------------------------------

def run_sweep():
    now = clock.now()
    counts = {
        "requests_expired_count": 0,
        "requests_completed_count": 0,
        "credentials_expired_count": 0,
        "feedback_sent_count": 0,
        "feedback_expired_count": 0,
        "strikes_expired_count": 0,
    }

    # Step 1: PENDING_APPROVAL past approval_deadline -> EXPIRED
    for req in sorted(db.showing_requests.values(), key=lambda r: r["created_at"]):
        if req["status"] == "PENDING_APPROVAL" and now >= req["approval_deadline"]:
            req["status"] = "EXPIRED"
            core.touch(req)
            core.add_activity(req["listing_id"], req["id"], "EXPIRED", "SYSTEM",
                              "Approval deadline passed; request expired.")
            counts["requests_expired_count"] += 1

    # Step 2: APPROVED past confirm_by_deadline -> EXPIRED
    for req in sorted(db.showing_requests.values(), key=lambda r: r["created_at"]):
        if req["status"] == "APPROVED" and now >= req["confirm_by_deadline"]:
            req["status"] = "EXPIRED"
            core.touch(req)
            core.add_activity(req["listing_id"], req["id"], "EXPIRED", "SYSTEM",
                              "Confirm-by deadline passed; request expired.")
            counts["requests_expired_count"] += 1

    # Step 3: CONFIRMED past end_at with a USED credential -> COMPLETED,
    #         feedback SCHEDULED -> SENT in the same step
    for req in sorted(db.showing_requests.values(), key=lambda r: r["created_at"]):
        if req["status"] == "CONFIRMED" and now > req["end_at"]:
            used = any(c["status"] == "USED"
                       for c in core.credentials_of_request(req["id"]))
            if not used:
                continue
            req["status"] = "COMPLETED"
            req["completed_at"] = now
            core.touch(req)
            listing = db.listings.get(req["listing_id"])
            if listing is not None:
                listing["confirmed_showing_count"] -= 1
                core.touch(listing)
            for fb in core.feedback_of_request(req["id"]):
                if fb["status"] == "SCHEDULED":
                    fb["status"] = "SENT"
                    fb["sent_at"] = now
                    fb["due_at"] = now + timedelta(hours=FEEDBACK_DUE_HOURS)
                    core.touch(fb)
                    core.add_activity(req["listing_id"], req["id"],
                                      "FEEDBACK_SENT", "SYSTEM",
                                      "Feedback request sent after completion.")
                    counts["feedback_sent_count"] += 1
            core.add_activity(req["listing_id"], req["id"], "COMPLETED", "SYSTEM",
                              "Showing completed (credential used, window ended).")
            counts["requests_completed_count"] += 1

    # Step 4: ISSUED credentials past expires_at -> EXPIRED
    for cred in sorted(db.access_credentials.values(), key=lambda c: c["created_at"]):
        if cred["status"] == "ISSUED" and now >= cred["expires_at"]:
            cred["status"] = "EXPIRED"
            core.touch(cred)
            req = db.showing_requests.get(cred["showing_request_id"])
            listing_id = req["listing_id"] if req else None
            core.add_activity(listing_id, cred["showing_request_id"],
                              "CREDENTIAL_EXPIRED", "SYSTEM",
                              "Credential expired past its window.")
            counts["credentials_expired_count"] += 1

    # Step 5: SENT feedback past due_at -> EXPIRED
    for fb in sorted(db.feedback_requests.values(), key=lambda f: f["created_at"]):
        if fb["status"] == "SENT" and now >= fb["due_at"]:
            fb["status"] = "EXPIRED"
            core.touch(fb)
            counts["feedback_expired_count"] += 1

    # Step 6: ACTIVE strikes past expires_at -> EXPIRED + standing recompute
    for strike in sorted(db.strike_records.values(), key=lambda s: s["created_at"]):
        if strike["status"] == "ACTIVE" and now >= strike["expires_at"]:
            strike["status"] = "EXPIRED"
            core.touch(strike)
            agent = db.agents.get(strike["agent_id"])
            if agent is not None:
                recompute_agent_standing(agent)
            counts["strikes_expired_count"] += 1

    return counts


# ---------------------------------------------------------------------------
# calc_seller_report_metrics (PRD §3.8)
# ---------------------------------------------------------------------------

def seller_report(listing, mode):
    reqs = core.requests_of_listing(listing["id"])

    def cnt(status):
        return sum(1 for r in reqs if r["status"] == status)

    completed = cnt("COMPLETED")
    no_show = cnt("NO_SHOW")
    cancelled = cnt("CANCELLED")
    expired = cnt("EXPIRED")
    declined = cnt("DECLINED")
    terminal_total = completed + no_show + cancelled + expired + declined

    def rate2(num, den):
        return float((Decimal(num) / Decimal(den)).quantize(Decimal("0.01"),
                                                            rounding=ROUND_HALF_UP))

    completion_rate = rate2(completed, terminal_total) if terminal_total else 0.0
    if mode == "PROVISIONAL":
        provisional = rate2(completed, max(completed + no_show + cnt("CONFIRMED"), 1))
    else:
        provisional = None

    return {
        "mode": mode,
        "pending_approval_count": cnt("PENDING_APPROVAL"),
        "approved_count": cnt("APPROVED"),
        "confirmed_count": cnt("CONFIRMED"),
        "completed_count": completed,
        "no_show_count": no_show,
        "cancelled_count": cancelled,
        "expired_count": expired,
        "declined_count": declined,
        "completion_rate": completion_rate,
        "provisional_completion_rate": provisional,
        "avg_feedback_score": listing["avg_feedback_score"],
    }
