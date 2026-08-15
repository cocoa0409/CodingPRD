"""Domain logic: derived fields, calculations (scaffold §1.3), cascades, serializers."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from core import (
    db, now, today, iso_z, add_months, add_years_date, age_on, touch, new_rec,
    mint_badge_number,
)

CLEARANCE_TYPES = ("BACKGROUND", "HEALTH_TB", "HEALTH_FLU")
VALIDITY_MONTHS = {"BACKGROUND": 24, "HEALTH_TB": 12, "HEALTH_FLU": 12}
CATEGORY_MULT = {
    "PATIENT_FACING": Decimal("1.5"),
    "FUNDRAISING": Decimal("1.2"),
    "GIFT_SHOP": Decimal("1.0"),
    "COMMUNITY": Decimal("1.0"),
    "CLERICAL": Decimal("0.8"),
}
TIER_ORDER = ["NONE", "BRONZE", "SILVER", "GOLD", "PRESIDENT"]
TIER_THRESHOLDS = {
    "PRESIDENT": Decimal("1000.00"),
    "GOLD": Decimal("600.00"),
    "SILVER": Decimal("300.00"),
    "BRONZE": Decimal("100.00"),
}
GRACE = timedelta(days=30)


# ---------------------------------------------------------------------------
# Clearance / posture (calculations.compliance_posture)
# ---------------------------------------------------------------------------
def latest_clearance(volunteer_id, ctype):
    cands = [c for c in db["clearances"].values()
             if c["volunteer_id"] == volunteer_id and c["clearance_type"] == ctype]
    if not cands:
        return None
    return max(cands, key=lambda c: c["_seq"])


def compliance_posture(vol):
    n = now()
    verdicts = []
    for t in CLEARANCE_TYPES:
        c = latest_clearance(vol["id"], t)
        if c is None or c["status"] in ("SUBMITTED", "REJECTED", "REVOKED"):
            verdicts.append("HARD")
            continue
        # CLEARED or EXPIRED: evaluate expires_at
        exp = c["expires_at"]
        if n > exp + GRACE:
            verdicts.append("HARD")
        elif exp < n <= exp + GRACE:
            verdicts.append("GRACE")
        elif exp - GRACE <= n <= exp:
            verdicts.append("GRACE")
        else:
            verdicts.append("OK")
    if "HARD" in verdicts:
        return "FROZEN"
    if "GRACE" in verdicts:
        return "RESTRICTED"
    return "CLEAR"


# ---------------------------------------------------------------------------
# Hours / recognition (calculations.recognition_points_weighted, tier assignment)
# ---------------------------------------------------------------------------
def entry_points(minutes, category):
    hrs = Decimal(minutes) / Decimal(60)
    return (hrs * CATEGORY_MULT[category]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def approved_entries(volunteer_id):
    return [e for e in db["hours"].values()
            if e["volunteer_id"] == volunteer_id and e["status"] == "APPROVED"]


def total_service_hours(volunteer_id):
    mins = sum(e["minutes"] for e in approved_entries(volunteer_id))
    return (Decimal(mins) / Decimal(60)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def recognition_points(volunteer_id):
    total = Decimal("0.00")
    for e in approved_entries(volunteer_id):
        total += entry_points(e["minutes"], e["service_category"])
    return total


def tier_for_points(points):
    for tier in ("PRESIDENT", "GOLD", "SILVER", "BRONZE"):
        if points >= TIER_THRESHOLDS[tier]:
            return tier
    return "NONE"


def record_tier_change(vol, before_tier, after_tier, after_points):
    vol["_tier"] = after_tier
    if before_tier == after_tier:
        return None
    direction = "TIER_INCREASED" if TIER_ORDER.index(after_tier) > TIER_ORDER.index(before_tier) \
        else "TIER_DECREASED"
    rec = {
        "id": new_rec()["id"],
        "volunteer_id": vol["id"],
        "event_type": direction,
        "tier": after_tier,
        "points_snapshot": after_points,
        "created_at": now(),
        "_seq": None,
    }
    from core import next_seq
    rec["_seq"] = next_seq()
    db["events"][rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Service years (calculations.service_year_hours)
# ---------------------------------------------------------------------------
def joined_date(vol):
    return vol["joined_at"].date()


def current_service_year_start(vol):
    """Most recent anniversary of joined_at <= today (joined date in year one)."""
    j = joined_date(vol)
    t = today()
    k = 0
    while add_years_date(j, k + 1) <= t:
        k += 1
    return add_years_date(j, k)


def service_year_hours(vol, start_d, end_d):
    """Approved hours in [start_d, end_d) minus 2.0 per NO_SHOW in the window, floored at 0."""
    start_dt, end_dt = start_d, end_d
    mins = 0
    for e in approved_entries(vol["id"]):
        if start_d <= e["service_date"] < end_d:
            mins += e["minutes"]
    approved_hrs = Decimal(mins) / Decimal(60)
    no_shows = 0
    from datetime import datetime, timezone
    sdt = datetime(start_d.year, start_d.month, start_d.day, tzinfo=timezone.utc)
    edt = datetime(end_d.year, end_d.month, end_d.day, tzinfo=timezone.utc)
    for a in db["assignments"].values():
        if a["volunteer_id"] != vol["id"] or a["status"] != "NO_SHOW":
            continue
        sh = db["shifts"].get(a["shift_id"])
        if sh and sdt <= sh["end_at"] < edt:
            no_shows += 1
    val = approved_hrs - Decimal("2.0") * no_shows
    if val < 0:
        val = Decimal("0.0")
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def most_recent_completed_year(vol):
    """Return (start_date, end_date) of the most recent fully completed service year."""
    j = joined_date(vol)
    t = today()
    k = 0
    while add_years_date(j, k + 1) <= t:
        k += 1
    if k == 0:
        return None
    return (add_years_date(j, k - 1), add_years_date(j, k))


# ---------------------------------------------------------------------------
# Juniors / shifts helpers
# ---------------------------------------------------------------------------
def is_junior_at(vol, d):
    return age_on(parse_dob(vol), d) < 18


def parse_dob(vol):
    from core import parse_date
    return parse_date(vol["date_of_birth"])


def shift_duration_hours(shift):
    secs = Decimal(str((shift["end_at"] - shift["start_at"]).total_seconds()))
    return (secs / Decimal(3600)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def shift_duration_minutes(shift):
    secs = (shift["end_at"] - shift["start_at"]).total_seconds()
    return int(secs // 60)


def half_open_overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


def volunteer_live_assignments(volunteer_id):
    return [a for a in db["assignments"].values()
            if a["volunteer_id"] == volunteer_id and a["status"] in ("SIGNED_UP", "CONFIRMED")]


def has_overlap(volunteer_id, shift):
    for a in volunteer_live_assignments(volunteer_id):
        other = db["shifts"].get(a["shift_id"])
        if other is None:
            continue
        if half_open_overlap(shift["start_at"], shift["end_at"], other["start_at"], other["end_at"]):
            return True
    return False


def junior_weekly_projected_hours(vol, shift):
    """Sum durations of the volunteer's SIGNED_UP/CONFIRMED shifts in the ISO week
    containing shift.start_at, plus the new shift's duration."""
    start_date = shift["start_at"].date()
    monday = start_date - timedelta(days=start_date.weekday())
    from datetime import datetime, timezone
    week_start = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
    week_end = week_start + timedelta(days=7)
    total = Decimal("0.00")
    for a in volunteer_live_assignments(vol["id"]):
        other = db["shifts"].get(a["shift_id"])
        if other is None:
            continue
        if week_start <= other["start_at"] < week_end:
            total += shift_duration_hours(other)
    total += shift_duration_hours(shift)
    return total


# ---------------------------------------------------------------------------
# Waitlist promotion (calculations.waitlist_promotion)
# ---------------------------------------------------------------------------
def run_waitlist_promotion(shift):
    cands = [a for a in db["assignments"].values()
             if a["shift_id"] == shift["id"] and a["status"] == "WAITLISTED"]
    cands.sort(key=lambda a: a["_seq"])
    for cand in cands:
        vol = db["volunteers"].get(cand["volunteer_id"])
        if vol is None:
            continue
        if vol["service_status"] != "ACTIVE":
            continue
        if compliance_posture(vol) == "FROZEN":
            continue
        if has_overlap(vol["id"], shift):
            continue
        cand["status"] = "SIGNED_UP"
        cand["signed_up_at"] = now()
        touch(cand)
        shift["filled_count"] += 1
        touch(shift)
        return cand
    return None


def cancel_assignment(a, promote=True):
    shift = db["shifts"].get(a["shift_id"])
    was_live = a["status"] in ("SIGNED_UP", "CONFIRMED")
    a["status"] = "CANCELLED"
    touch(a)
    if was_live and shift is not None:
        shift["filled_count"] -= 1
        touch(shift)
        if promote and shift["status"] == "PUBLISHED":
            run_waitlist_promotion(shift)


# ---------------------------------------------------------------------------
# Placement rescind / slot fill (calculations.slot_fill_evaluation)
# ---------------------------------------------------------------------------
def rescind_placement(p, via_request_cancel=False):
    was_accepted = p["status"] == "ACCEPTED"
    p["status"] = "RESCINDED"
    p["rescinded_at"] = now()
    touch(p)
    if was_accepted:
        req = db["requests"].get(p["request_id"])
        if req is not None:
            req["slots_filled"] -= 1
            if not via_request_cancel and req["status"] == "FILLED" \
                    and req["slots_filled"] < req["slots_needed"]:
                req["status"] = "OPEN"
                req["filled_at"] = None
            touch(req)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def freeze_cascade(vol, posture_before):
    """After a clearance mutation: if posture flipped to FROZEN, cancel the
    volunteer's future live assignments and promote waitlists per shift."""
    if posture_before == "FROZEN":
        return
    if compliance_posture(vol) != "FROZEN":
        return
    n = now()
    affected = [a for a in db["assignments"].values()
                if a["volunteer_id"] == vol["id"]
                and a["status"] in ("SIGNED_UP", "CONFIRMED", "WAITLISTED")]
    affected = [a for a in affected
                if db["shifts"].get(a["shift_id"]) is not None
                and db["shifts"][a["shift_id"]]["start_at"] > n]
    affected.sort(key=lambda a: a["_seq"])
    for a in affected:
        cancel_assignment(a, promote=True)


def live_badge(vol):
    for b in db["badges"].values():
        if b["volunteer_id"] == vol["id"] and b["status"] in ("PENDING", "ISSUED", "SUSPENDED"):
            return b
    return None


def suspend_volunteer(vol, reason):
    vol["service_status"] = "SUSPENDED"
    vol["suspension_reason"] = reason
    badge = live_badge(vol)
    if badge is not None and badge["status"] == "ISSUED":
        badge["status"] = "SUSPENDED"
        touch(badge)
    touch(vol)


def separation_cascade(vol):
    """Volunteer -> SEPARATED side effects. Caller sets separated_at/reason after."""
    vol["service_status"] = "SEPARATED"
    n = now()
    # badge
    badge = live_badge(vol)
    if badge is not None:
        badge["status"] = "REVOKED"
        badge["revoked_at"] = n
        badge["revoke_reason"] = "SEPARATION"
        touch(badge)
    # future live assignments
    affected = [a for a in db["assignments"].values()
                if a["volunteer_id"] == vol["id"]
                and a["status"] in ("SIGNED_UP", "CONFIRMED", "WAITLISTED")
                and db["shifts"].get(a["shift_id"]) is not None
                and db["shifts"][a["shift_id"]]["start_at"] > n]
    affected.sort(key=lambda a: a["_seq"])
    for a in affected:
        cancel_assignment(a, promote=True)
    # placements
    for p in sorted(db["placements"].values(), key=lambda x: x["_seq"]):
        if p["volunteer_id"] != vol["id"]:
            continue
        if p["status"] in ("OFFERED", "COUNTERED"):
            rescind_placement(p)
        elif p["status"] == "ACCEPTED":
            rescind_placement(p)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def dec_num(d):
    return float(d)


def ser_application(a):
    return {
        "id": a["id"],
        "full_name": a["full_name"],
        "date_of_birth": a["date_of_birth"],
        "email": a["email"],
        "phone": a["phone"],
        "notes": a["notes"],
        "status": a["status"],
        "volunteer_id": a["volunteer_id"],
        "decided_by_user_id": a["decided_by_user_id"],
        "decided_at": iso_z(a["decided_at"]) if a["decided_at"] else None,
        "rejection_reason": a["rejection_reason"],
        "info_request_note": a["info_request_note"],
        "created_at": iso_z(a["created_at"]),
        "updated_at": iso_z(a["updated_at"]),
        "version": a["version"],
    }


def ser_volunteer(v):
    points = recognition_points(v["id"])
    return {
        "id": v["id"],
        "full_name": v["full_name"],
        "date_of_birth": v["date_of_birth"],
        "email": v["email"],
        "phone": v["phone"],
        "notes": v["notes"],
        "service_status": v["service_status"],
        "compliance_posture": compliance_posture(v),
        "total_service_hours": dec_num(total_service_hours(v["id"])),
        "recognition_points": dec_num(points),
        "recognition_tier": tier_for_points(points),
        "joined_at": iso_z(v["joined_at"]),
        "current_service_year_start": current_service_year_start(v).isoformat(),
        "separated_at": iso_z(v["separated_at"]) if v["separated_at"] else None,
        "separation_reason": v["separation_reason"],
        "suspension_reason": v["suspension_reason"],
        "is_junior_today": is_junior_at(v, today()),
        "created_at": iso_z(v["created_at"]),
        "updated_at": iso_z(v["updated_at"]),
        "version": v["version"],
    }


def ser_clearance(c):
    return {
        "id": c["id"],
        "volunteer_id": c["volunteer_id"],
        "clearance_type": c["clearance_type"],
        "document_ref": c["document_ref"],
        "status": c["status"],
        "submitted_by_user_id": c["submitted_by_user_id"],
        "adjudicated_by_user_id": c["adjudicated_by_user_id"],
        "adjudicated_at": iso_z(c["adjudicated_at"]) if c["adjudicated_at"] else None,
        "expires_at": iso_z(c["expires_at"]) if c["expires_at"] else None,
        "adjudication_notes": c["adjudication_notes"],
        "created_at": iso_z(c["created_at"]),
        "updated_at": iso_z(c["updated_at"]),
        "version": c["version"],
    }


def ser_department(d):
    return {
        "id": d["id"],
        "name": d["name"],
        "head_user_id": d["head_user_id"],
        "junior_allowed": d["junior_allowed"],
        "created_at": iso_z(d["created_at"]),
        "updated_at": iso_z(d["updated_at"]),
        "version": d["version"],
    }


def ser_role(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "category": r["category"],
        "minimum_age": r["minimum_age"],
        "can_supervise_juniors": r["can_supervise_juniors"],
        "required_training_codes": list(r["required_training_codes"]),
        "created_at": iso_z(r["created_at"]),
        "updated_at": iso_z(r["updated_at"]),
        "version": r["version"],
    }


def ser_request(r):
    return {
        "id": r["id"],
        "department_id": r["department_id"],
        "role_id": r["role_id"],
        "slots_needed": r["slots_needed"],
        "slots_filled": r["slots_filled"],
        "notes": r["notes"],
        "status": r["status"],
        "filled_at": iso_z(r["filled_at"]) if r["filled_at"] else None,
        "created_at": iso_z(r["created_at"]),
        "updated_at": iso_z(r["updated_at"]),
        "version": r["version"],
    }


def ser_placement(p):
    return {
        "id": p["id"],
        "request_id": p["request_id"],
        "volunteer_id": p["volunteer_id"],
        "offer_note": p["offer_note"],
        "counter_note": p["counter_note"],
        "counter_rounds": p["counter_rounds"],
        "status": p["status"],
        "accepted_at": iso_z(p["accepted_at"]) if p["accepted_at"] else None,
        "rescinded_at": iso_z(p["rescinded_at"]) if p["rescinded_at"] else None,
        "created_at": iso_z(p["created_at"]),
        "updated_at": iso_z(p["updated_at"]),
        "version": p["version"],
    }


def ser_training(t):
    return {
        "id": t["id"],
        "volunteer_id": t["volunteer_id"],
        "training_code": t["training_code"],
        "recurrence": t["recurrence"],
        "status": t["status"],
        "completed_at": iso_z(t["completed_at"]) if t["completed_at"] else None,
        "expires_at": iso_z(t["expires_at"]) if t["expires_at"] else None,
        "created_at": iso_z(t["created_at"]),
        "updated_at": iso_z(t["updated_at"]),
        "version": t["version"],
    }


def ser_shift(s):
    return {
        "id": s["id"],
        "department_id": s["department_id"],
        "role_id": s["role_id"],
        "start_at": iso_z(s["start_at"]),
        "end_at": iso_z(s["end_at"]),
        "capacity": s["capacity"],
        "allow_waitlist": s["allow_waitlist"],
        "filled_count": s["filled_count"],
        "status": s["status"],
        "created_at": iso_z(s["created_at"]),
        "updated_at": iso_z(s["updated_at"]),
        "version": s["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"],
        "shift_id": a["shift_id"],
        "volunteer_id": a["volunteer_id"],
        "status": a["status"],
        "supervisor_assignment_id": a["supervisor_assignment_id"],
        "signed_up_at": iso_z(a["signed_up_at"]) if a["signed_up_at"] else None,
        "confirmed_at": iso_z(a["confirmed_at"]) if a["confirmed_at"] else None,
        "created_at": iso_z(a["created_at"]),
        "updated_at": iso_z(a["updated_at"]),
        "version": a["version"],
    }


def ser_hour_entry(e):
    return {
        "id": e["id"],
        "volunteer_id": e["volunteer_id"],
        "shift_assignment_id": e["shift_assignment_id"],
        "service_date": e["service_date"].isoformat(),
        "minutes": e["minutes"],
        "service_category": e["service_category"],
        "notes": e["notes"],
        "status": e["status"],
        "approved_at": iso_z(e["approved_at"]) if e["approved_at"] else None,
        "decision_reason": e["decision_reason"],
        "created_at": iso_z(e["created_at"]),
        "updated_at": iso_z(e["updated_at"]),
        "version": e["version"],
    }


def ser_badge(b):
    return {
        "id": b["id"],
        "volunteer_id": b["volunteer_id"],
        "badge_number": b["badge_number"],
        "status": b["status"],
        "issued_at": iso_z(b["issued_at"]) if b["issued_at"] else None,
        "revoked_at": iso_z(b["revoked_at"]) if b["revoked_at"] else None,
        "revoke_reason": b["revoke_reason"],
        "created_at": iso_z(b["created_at"]),
        "updated_at": iso_z(b["updated_at"]),
        "version": b["version"],
    }


def campaign_figures(c):
    attributed = [s for s in db["sales"].values() if s["campaign_id"] == c["id"]]
    gross = sum(s["total_cents"] for s in attributed)
    completed = [s for s in attributed if s["status"] == "COMPLETED"]
    raised = sum(s["total_cents"] for s in completed)
    cogs = 0
    for s in completed:
        for line in s["_lines"]:
            cogs += line["qty"] * line["unit_cost_cents"]
    net = raised - cogs
    return gross, raised, net


def ser_campaign(c):
    gross, raised, net = campaign_figures(c)
    return {
        "id": c["id"],
        "name": c["name"],
        "goal_cents": c["goal_cents"],
        "start_at": iso_z(c["start_at"]),
        "end_at": iso_z(c["end_at"]),
        "promo_discount_pct": c["promo_discount_pct"],
        "status": c["status"],
        "created_by_user_id": c["created_by_user_id"],
        "closed_at": iso_z(c["closed_at"]) if c["closed_at"] else None,
        "gross_receipts_cents": gross,
        "raised_cents": raised,
        "net_proceeds_cents": net,
        "disbursed_cents": c["disbursed_cents"],
        "created_at": iso_z(c["created_at"]),
        "updated_at": iso_z(c["updated_at"]),
        "version": c["version"],
    }


def ser_item(i):
    return {
        "id": i["id"],
        "sku": i["sku"],
        "name": i["name"],
        "unit_price_cents": i["unit_price_cents"],
        "unit_cost_cents": i["unit_cost_cents"],
        "stock_on_hand": i["stock_on_hand"],
        "reorder_level": i["reorder_level"],
        "is_active": i["is_active"],
        "created_at": iso_z(i["created_at"]),
        "updated_at": iso_z(i["updated_at"]),
        "version": i["version"],
    }


def ser_sale(s):
    return {
        "id": s["id"],
        "cashier_volunteer_id": s["cashier_volunteer_id"],
        "buyer_volunteer_id": s["buyer_volunteer_id"],
        "campaign_id": s["campaign_id"],
        "lines": [{"item_id": ln["item_id"], "qty": ln["qty"]} for ln in s["_lines"]],
        "total_cents": s["total_cents"],
        "discount_pct_applied": s["discount_pct_applied"],
        "tendered_cents": s["tendered_cents"],
        "change_cents": s["change_cents"],
        "status": s["status"],
        "voided_at": iso_z(s["voided_at"]) if s["voided_at"] else None,
        "void_reason": s["void_reason"],
        "voided_by_user_id": s["voided_by_user_id"],
        "created_at": iso_z(s["created_at"]),
        "updated_at": iso_z(s["updated_at"]),
        "version": s["version"],
    }


def ser_event(e):
    return {
        "id": e["id"],
        "volunteer_id": e["volunteer_id"],
        "event_type": e["event_type"],
        "tier": e["tier"],
        "points_snapshot": dec_num(e["points_snapshot"]),
        "created_at": iso_z(e["created_at"]),
    }
