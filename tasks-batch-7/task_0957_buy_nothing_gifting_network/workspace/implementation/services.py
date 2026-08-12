from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from utils import new_uuid, iso, iso_or_none

DAY = 86400
OFFER_WINDOW = timedelta(hours=24)
STRIKE_TTL = timedelta(days=90)
SUSPENSION_LEN = timedelta(days=14)
WISHLIST_TTL = timedelta(days=30)
SETTLE_AFTER = timedelta(days=7)
PICKUP_BUFFER = timedelta(minutes=15)
SLA_HOURS = {"GREEN": 96, "YELLOW": 72, "RED": 48}

CATEGORIES = ("FURNITURE", "CLOTHING", "FOOD", "HOUSEHOLD", "ELECTRONICS", "OTHER")
CLAIM_MODES = ("FIRST_COME", "FAIRNESS_DRAW", "GIVER_PICK")


# ---------------------------------------------------------------------------
# Entity construction / mutation helpers
# ---------------------------------------------------------------------------

def new_entity():
    t = db.now()
    return {
        "id": new_uuid(),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": db.store.next_seq(),
    }


def touch(e):
    e["updated_at"] = db.now()
    e["version"] += 1


def add_event(member_id, event_type, base_points):
    ev = {
        "id": new_uuid(),
        "member_id": member_id,
        "event_type": event_type,
        "base_points": base_points,
        "status": "PENDING",
        "settled_at": None,
        "created_at": db.now(),
        "_seq": db.store.next_seq(),
    }
    db.store.events[ev["id"]] = ev
    return ev


def days_old(t):
    return int((db.now() - t).total_seconds() // DAY)


# ---------------------------------------------------------------------------
# Computed fields
# ---------------------------------------------------------------------------

def active_strike_points(member_id):
    return sum(
        a["severity_points"] or 0
        for a in db.store.actions.values()
        if a["member_id"] == member_id and a["action_type"] == "STRIKE"
        and a["status"] == "ACTIVE"
    )


def given_count_90d(member_id):
    return sum(
        1 for p in db.store.posts.values()
        if p["giver_id"] == member_id and p["status"] == "FULFILLED"
        and p["fulfilled_at"] is not None and days_old(p["fulfilled_at"]) <= 90
    )


def received_count_90d(member_id):
    return sum(
        1 for c in db.store.claims.values()
        if c["claimer_id"] == member_id and c["status"] == "FULFILLED"
        and c["fulfilled_at"] is not None and days_old(c["fulfilled_at"]) <= 90
    )


def _event_points(ev):
    age = days_old(ev["created_at"])
    if age <= 30:
        weight = Decimal("1.0")
    elif age <= 90:
        weight = Decimal("0.75")
    else:
        weight = Decimal("0.5")
    # Round each event FIRST to 1 decimal (half-up), then sum.
    return (Decimal(ev["base_points"]) * weight).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )


def reputation_scores(member_id):
    official = Decimal("0.0")
    pending = Decimal("0.0")
    for ev in db.store.events.values():
        if ev["member_id"] != member_id:
            continue
        pts = _event_points(ev)
        if ev["status"] == "SETTLED":
            official += pts
        if ev["status"] in ("PENDING", "SETTLED"):
            pending += pts
    return float(official), float(pending)


def fairness_score(member):
    raw = (
        50
        + 2 * given_count_90d(member["id"])
        - 3 * received_count_90d(member["id"])
        - 10 * active_strike_points(member["id"])
        + (5 if days_old(member["created_at"]) >= 180 else 0)
    )
    return min(100, max(0, raw))


def group_member_count(group_id):
    return sum(
        1 for ms in db.store.memberships.values()
        if ms["group_id"] == group_id and ms["status"] == "APPROVED"
    )


def group_health(group_id):
    completed = sum(
        1 for p in db.store.posts.values()
        if p["group_id"] == group_id and p["status"] == "FULFILLED"
        and p["fulfilled_at"] is not None and days_old(p["fulfilled_at"]) <= 30
    )
    open_reports = sum(
        1 for r in db.store.reports.values()
        if r["group_id"] == group_id and r["status"] in ("OPEN", "UNDER_REVIEW")
    )
    overdue = sum(
        1 for r in db.store.reports.values()
        if r["group_id"] == group_id and r["resolved_at"] is not None
        and days_old(r["resolved_at"]) <= 30 and r["resolved_at"] > r["sla_due_at"]
    )
    score = 2 * completed - 5 * open_reports - 10 * overdue
    if score >= 20:
        tier = "GREEN"
    elif score >= 0:
        tier = "YELLOW"
    else:
        tier = "RED"
    return score, tier


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(e):
    return {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


def ser_member(m):
    official, pending = reputation_scores(m["id"])
    out = _common(m)
    out.update({
        "email": m["email"],
        "display_name": m["display_name"],
        "status": m["status"],
        "reputation_score": official,
        "pending_reputation_score": pending,
        "fairness_score": fairness_score(m),
        "active_strike_points": active_strike_points(m["id"]),
        "given_count_90d": given_count_90d(m["id"]),
        "received_count_90d": received_count_90d(m["id"]),
        "suspension_ends_at": iso_or_none(m["suspension_ends_at"]),
    })
    return out


def ser_group(g):
    count = group_member_count(g["id"])
    score, tier = group_health(g["id"])
    out = _common(g)
    out.update({
        "name": g["name"],
        "zip_code": g["zip_code"],
        "join_policy": g["join_policy"],
        "capacity": g["capacity"],
        "member_count": count,
        "roster_status": "FULL" if count >= g["capacity"] else "ACCEPTING",
        "health_score": score,
        "health_tier": tier,
    })
    return out


def ser_membership(ms):
    out = _common(ms)
    out.update({
        "member_id": ms["member_id"],
        "group_id": ms["group_id"],
        "role": ms["role"],
        "status": ms["status"],
    })
    return out


def ser_post(p):
    out = _common(p)
    out.update({
        "group_id": p["group_id"],
        "giver_id": p["giver_id"],
        "title": p["title"],
        "description": p["description"],
        "category": p["category"],
        "claim_mode": p["claim_mode"],
        "status": p["status"],
        "expires_at": iso(p["expires_at"]),
        "current_claim_id": p["current_claim_id"],
        "current_offer_expires_at": iso_or_none(p["current_offer_expires_at"]),
    })
    return out


def ser_claim(c):
    out = _common(c)
    out.update({
        "post_id": c["post_id"],
        "claimer_id": c["claimer_id"],
        "status": c["status"],
        "claim_seq": c["claim_seq"],
        "offered_at": iso_or_none(c["offered_at"]),
        "offer_expires_at": iso_or_none(c["offer_expires_at"]),
    })
    return out


def ser_plan(pl):
    out = _common(pl)
    out.update({
        "claim_id": pl["claim_id"],
        "proposer_id": pl["proposer_id"],
        "last_proposer_id": pl["last_proposer_id"],
        "window_start": iso(pl["window_start"]),
        "window_end": iso(pl["window_end"]),
        "location_note": pl["location_note"],
        "round_number": pl["round_number"],
        "status": pl["status"],
    })
    return out


def ser_wishlist(w):
    out = _common(w)
    out.update({
        "member_id": w["member_id"],
        "group_id": w["group_id"],
        "keyword": w["keyword"],
        "category": w["category"],
        "status": w["status"],
        "matched_post_id": w["matched_post_id"],
        "expires_at": iso(w["expires_at"]),
    })
    return out


def ser_alert(a):
    out = _common(a)
    out.update({
        "group_id": a["group_id"],
        "creator_id": a["creator_id"],
        "zone": a["zone"],
        "starts_at": iso(a["starts_at"]),
        "ends_at": iso(a["ends_at"]),
        "status": a["status"],
    })
    return out


def ser_report(r):
    out = _common(r)
    out.update({
        "group_id": r["group_id"],
        "reporter_id": r["reporter_id"],
        "target_type": r["target_type"],
        "target_id": r["target_id"],
        "category": r["category"],
        "details": r["details"],
        "status": r["status"],
        "reviewed_by": r["reviewed_by"],
        "sla_due_at": iso(r["sla_due_at"]),
        "resolved_at": iso_or_none(r["resolved_at"]),
    })
    return out


def ser_action(a):
    out = _common(a)
    out.update({
        "report_id": a["report_id"],
        "member_id": a["member_id"],
        "action_type": a["action_type"],
        "severity_points": a["severity_points"],
        "rationale": a["rationale"],
        "status": a["status"],
        "active_until": iso(a["active_until"]),
    })
    return out


def ser_event(ev):
    # ReputationEvent is an append-only ledger entry: only id + created_at.
    return {
        "id": ev["id"],
        "member_id": ev["member_id"],
        "event_type": ev["event_type"],
        "base_points": ev["base_points"],
        "status": ev["status"],
        "settled_at": iso_or_none(ev["settled_at"]),
        "created_at": iso(ev["created_at"]),
    }


# ---------------------------------------------------------------------------
# Claim queue: ranking, promotion, vacancy cascade
# ---------------------------------------------------------------------------

def _post_of(claim):
    return db.store.posts.get(claim["post_id"])


def queue_rank_key(post):
    if post["claim_mode"] == "FAIRNESS_DRAW":
        def key(c):
            claimer = db.store.members.get(c["claimer_id"])
            fs = fairness_score(claimer) if claimer else 0
            return (-fs, c["created_at"], c["claim_seq"])
        return key
    # FIRST_COME: pure chronological; claimer attributes ignored.
    return lambda c: (c["created_at"], c["claim_seq"])


def promote_claim(claim, post):
    claim["status"] = "OFFERED"
    claim["offered_at"] = db.now()
    claim["offer_expires_at"] = db.now() + OFFER_WINDOW
    touch(claim)
    post["status"] = "RESERVED"
    post["current_claim_id"] = claim["id"]
    post["current_offer_expires_at"] = claim["offer_expires_at"]
    touch(post)


def vacancy_cascade(post):
    """Re-evaluate a post's head slot after the previous head departed."""
    if post["status"] not in ("OPEN", "RESERVED"):
        return
    live = any(
        c["post_id"] == post["id"] and c["status"] in ("OFFERED", "ACCEPTED")
        for c in db.store.claims.values()
    )
    if live:
        return
    if post["claim_mode"] == "GIVER_PICK":
        if post["status"] == "RESERVED":
            post["status"] = "OPEN"
            post["current_claim_id"] = None
            post["current_offer_expires_at"] = None
            touch(post)
        return
    queued = [
        c for c in db.store.claims.values()
        if c["post_id"] == post["id"] and c["status"] == "QUEUED"
    ]
    if not queued:
        if post["status"] == "RESERVED":
            post["status"] = "OPEN"
            post["current_claim_id"] = None
            post["current_offer_expires_at"] = None
            touch(post)
        return
    winner = min(queued, key=queue_rank_key(post))
    promote_claim(winner, post)


# ---------------------------------------------------------------------------
# Wishlist matching
# ---------------------------------------------------------------------------

def wishlist_matches_post(w, post):
    return (
        w["keyword"].lower() in post["title"].lower()
        and (w["category"] is None or w["category"] == post["category"])
    )


def match_wishlists_on_publish(post):
    for w in db.store.wishlists.values():
        if (w["group_id"] == post["group_id"] and w["status"] == "ACTIVE"
                and wishlist_matches_post(w, post)):
            w["status"] = "MATCHED"
            w["matched_post_id"] = post["id"]
            touch(w)


def release_matched_wishlists(post):
    for w in db.store.wishlists.values():
        if w["status"] == "MATCHED" and w["matched_post_id"] == post["id"]:
            w["status"] = "ACTIVE"
            w["matched_post_id"] = None
            touch(w)


def fulfill_wishlists(claimer_id, post):
    for w in db.store.wishlists.values():
        if (w["member_id"] == claimer_id and w["group_id"] == post["group_id"]
                and w["status"] in ("ACTIVE", "MATCHED")
                and wishlist_matches_post(w, post)):
            w["status"] = "FULFILLED"
            touch(w)


# ---------------------------------------------------------------------------
# Post withdrawal
# ---------------------------------------------------------------------------

def withdraw_post(post):
    """Execute the WITHDRAWN transition (manual or CONTENT_REMOVAL)."""
    st = post["status"]
    if st == "DRAFT":
        post["status"] = "WITHDRAWN"
        touch(post)
        return
    if st == "OPEN":
        for c in db.store.claims.values():
            if c["post_id"] == post["id"] and c["status"] == "QUEUED":
                c["status"] = "WITHDRAWN"
                touch(c)
        post["status"] = "WITHDRAWN"
        touch(post)
        release_matched_wishlists(post)
        return
    if st == "RESERVED":
        for c in db.store.claims.values():
            if c["post_id"] == post["id"] and c["status"] in ("QUEUED", "OFFERED"):
                c["status"] = "WITHDRAWN"
                touch(c)
        post["status"] = "WITHDRAWN"
        post["current_claim_id"] = None
        post["current_offer_expires_at"] = None
        touch(post)
        release_matched_wishlists(post)
        return


# ---------------------------------------------------------------------------
# Member sanction cascades
# ---------------------------------------------------------------------------

def withdraw_member_claims(member_id, group_id=None):
    for c in db.store.claims.values():
        if c["claimer_id"] != member_id or c["status"] not in ("QUEUED", "OFFERED"):
            continue
        post = _post_of(c)
        if post is None:
            continue
        if group_id is not None and post["group_id"] != group_id:
            continue
        was_head = c["status"] == "OFFERED"
        c["status"] = "WITHDRAWN"
        touch(c)
        if was_head:
            vacancy_cascade(post)


def suspend_member(m):
    m["status"] = "SUSPENDED"
    m["suspension_ends_at"] = db.now() + SUSPENSION_LEN
    touch(m)
    withdraw_member_claims(m["id"])


def ban_member(m):
    m["status"] = "BANNED"
    m["suspension_ends_at"] = None
    touch(m)
    for ms in db.store.memberships.values():
        if ms["member_id"] == m["id"] and ms["status"] in ("REQUESTED", "APPROVED"):
            was_approved = ms["status"] == "APPROVED"
            ms["status"] = "REMOVED"
            touch(ms)
            if was_approved:
                group = db.store.groups.get(ms["group_id"])
                if group is not None:
                    touch(group)  # member_count / roster_status recomputed
    withdraw_member_claims(m["id"])


def recompute_strike_status(m, allow_unban=False):
    pts = active_strike_points(m["id"])
    if m["status"] == "ACTIVE":
        if pts >= 6:
            ban_member(m)
        elif pts >= 3:
            suspend_member(m)
    elif m["status"] == "SUSPENDED":
        if pts >= 6:
            ban_member(m)
        elif pts < 3:
            m["status"] = "ACTIVE"
            m["suspension_ends_at"] = None
            touch(m)
    elif m["status"] == "BANNED" and allow_unban:
        if pts < 3:
            m["status"] = "ACTIVE"
            m["suspension_ends_at"] = None
            touch(m)
        elif pts < 6:
            m["status"] = "SUSPENDED"
            m["suspension_ends_at"] = db.now() + SUSPENSION_LEN
            touch(m)


# ---------------------------------------------------------------------------
# Pickup window overlap (giver's porch, confirmed plans only)
# ---------------------------------------------------------------------------

def pickup_window_conflict(giver_id, new_start, new_end):
    for pl in db.store.plans.values():
        if pl["status"] != "CONFIRMED":
            continue
        claim = db.store.claims.get(pl["claim_id"])
        if claim is None:
            continue
        post = db.store.posts.get(claim["post_id"])
        if post is None or post["giver_id"] != giver_id:
            continue
        # Closed-interval semantics with a 15-minute buffer on BOTH sides;
        # strict inequalities pin the boundary.
        if new_start < pl["window_end"] + PICKUP_BUFFER and \
                new_end > pl["window_start"] - PICKUP_BUFFER:
            return True
    return False


def curb_zone_overlap_count(group_id, zone, starts_at, ends_at):
    count = 0
    for a in db.store.alerts.values():
        if a["group_id"] != group_id or a["zone"] != zone:
            continue
        if a["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        # Half-open intervals: overlap iff each starts before the other ends.
        if starts_at < a["ends_at"] and a["starts_at"] < ends_at:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Epoch sweep (driven by POST /v1/_clock/set_current_utc)
# ---------------------------------------------------------------------------

def epoch_sweep():
    now = db.now()

    # 1. Offer expiry: OFFERED -> EXPIRED at offer_expires_at + vacancy cascade.
    for c in sorted(db.store.claims.values(), key=lambda c: (c["created_at"], c["_seq"])):
        if c["status"] == "OFFERED" and now >= c["offer_expires_at"]:
            c["status"] = "EXPIRED"
            touch(c)
            post = _post_of(c)
            if post is not None:
                vacancy_cascade(post)

    # 2. Post expiry: OPEN -> EXPIRED at expires_at.
    for p in sorted(db.store.posts.values(), key=lambda p: p["_seq"]):
        if p["status"] == "OPEN" and now >= p["expires_at"]:
            p["status"] = "EXPIRED"
            touch(p)
            for c in db.store.claims.values():
                if c["post_id"] == p["id"] and c["status"] == "QUEUED":
                    c["status"] = "WITHDRAWN"
                    touch(c)
            release_matched_wishlists(p)

    # 3. Curb alerts: SCHEDULED -> ACTIVE at starts_at, ACTIVE -> ENDED at ends_at.
    for a in sorted(db.store.alerts.values(), key=lambda a: a["_seq"]):
        if a["status"] == "SCHEDULED" and now >= a["starts_at"]:
            a["status"] = "ACTIVE"
            touch(a)
    for a in sorted(db.store.alerts.values(), key=lambda a: a["_seq"]):
        if a["status"] == "ACTIVE" and now >= a["ends_at"]:
            a["status"] = "ENDED"
            touch(a)

    # 4. Reputation settlement: PENDING -> SETTLED once age >= 7 days.
    for ev in sorted(db.store.events.values(), key=lambda e: e["_seq"]):
        if ev["status"] == "PENDING" and now >= ev["created_at"] + SETTLE_AFTER:
            ev["status"] = "SETTLED"
            ev["settled_at"] = now

    # 5. Strike expiry: ACTIVE -> EXPIRED at active_until, then recompute.
    affected = []
    for act in sorted(db.store.actions.values(), key=lambda a: a["_seq"]):
        if act["status"] == "ACTIVE" and now >= act["active_until"]:
            act["status"] = "EXPIRED"
            touch(act)
            if act["member_id"] not in affected:
                affected.append(act["member_id"])
    for mid in affected:
        m = db.store.members.get(mid)
        if m is not None:
            recompute_strike_status(m)

    # 6. Suspension reinstatement at suspension_ends_at.
    for m in db.store.members.values():
        if (m["status"] == "SUSPENDED" and m["suspension_ends_at"] is not None
                and now >= m["suspension_ends_at"]):
            m["status"] = "ACTIVE"
            m["suspension_ends_at"] = None
            touch(m)

    # 7. Wishlist expiry at expires_at.
    for w in db.store.wishlists.values():
        if w["status"] in ("ACTIVE", "MATCHED") and now >= w["expires_at"]:
            if w["status"] == "MATCHED":
                w["matched_post_id"] = None
            w["status"] = "EXPIRED"
            touch(w)
