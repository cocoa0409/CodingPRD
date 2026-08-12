"""Member lifecycle cascades, risk score, benefit/directory propagation, payment handling."""
from datetime import timedelta
from decimal import Decimal

import db
import errors
from services import pricing


# ---------------------------------------------------------------------------
# Serializers (include system-managed common fields per PRD §2.4)
# ---------------------------------------------------------------------------
def base_fields(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def category_out(c):
    d = base_fields(c)
    d.update({
        "code": c["code"], "name": c["name"],
        "is_voting": c["is_voting"],
        "is_directory_eligible": c["is_directory_eligible"],
        "allows_auto_renew": c["allows_auto_renew"],
        "lapse_grace_days": c["lapse_grace_days"],
        "reinstatement_window_days": c["reinstatement_window_days"],
        "status": c["status"],
    })
    return d


def chapter_out(c):
    d = base_fields(c)
    d.update({"code": c["code"], "name": c["name"],
              "is_affiliate": c["is_affiliate"], "status": c["status"]})
    return d


def policy_out(p):
    d = base_fields(p)
    d.update({"code": p["code"], "mode": p["mode"],
              "calendar_anchor_month": p["calendar_anchor_month"],
              "calendar_anchor_day": p["calendar_anchor_day"],
              "proration_method": p["proration_method"],
              "status": p["status"]})
    return d


def schedule_out(s):
    d = base_fields(s)
    d.update({"category_id": s["category_id"],
              "effective_from": s["effective_from"],
              "effective_to": s.get("effective_to"),
              "annual_amount_cents": s["annual_amount_cents"],
              "chapter_share_bps": s["chapter_share_bps"],
              "increase_notice_days": s["increase_notice_days"],
              "status": s["status"]})
    return d


def member_out(m):
    d = base_fields(m)
    d.update({
        "email": m["email"], "full_name": m["full_name"],
        "category_id": m["category_id"],
        "home_chapter_id": m["home_chapter_id"],
        "cycle_policy_id": m["cycle_policy_id"],
        "joined_at": m["joined_at"],
        "status": m["status"],
        "current_period_start": m.get("current_period_start"),
        "current_period_end": m.get("current_period_end"),
        "lifetime_dues_paid_cents": m.get("lifetime_dues_paid_cents", 0),
        "risk_score": m.get("risk_score", 0),
    })
    return d


def term_out(t):
    d = base_fields(t)
    d.update({"member_id": t["member_id"],
              "period_start": t["period_start"],
              "period_end": t["period_end"],
              "opened_by": t["opened_by"],
              "status": t["status"]})
    return d


def invoice_out(i):
    d = base_fields(i)
    d.update({"member_id": i["member_id"],
              "membership_term_id": i["membership_term_id"],
              "dues_schedule_id": i["dues_schedule_id"],
              "amount_cents": i["amount_cents"],
              "chapter_share_cents": i.get("chapter_share_cents"),
              "issued_at": i["issued_at"],
              "due_at": i["due_at"],
              "settled_at": i.get("settled_at"),
              "payment_status": i["payment_status"],
              "fulfillment_status": i["fulfillment_status"]})
    return d


def attempt_out(a):
    d = base_fields(a)
    d.update({"invoice_id": a["invoice_id"],
              "attempt_index": a["attempt_index"],
              "attempted_at": a["attempted_at"],
              "outcome": a["outcome"],
              "decline_code": a.get("decline_code")})
    return d


def auto_renew_out(a):
    d = base_fields(a)
    d.update({"member_id": a["member_id"],
              "payment_method_token": a["payment_method_token"],
              "authorized_at": a["authorized_at"],
              "revoked_at": a.get("revoked_at"),
              "status": a["status"]})
    return d


def entitlement_out(e):
    d = base_fields(e)
    d.update({"member_id": e["member_id"],
              "benefit_code": e["benefit_code"],
              "granted_at": e["granted_at"],
              "suspended_at": e.get("suspended_at"),
              "status": e["status"]})
    return d


def listing_out(l):
    d = base_fields(l)
    d.update({"member_id": l["member_id"],
              "display_name": l["display_name"],
              "specialty_tags": l["specialty_tags"],
              "is_public": l["is_public"],
              "visibility_state": l["visibility_state"]})
    return d


def notice_out(n):
    d = base_fields(n)
    d.update({"schedule_id": n["schedule_id"],
              "noticed_at": n["noticed_at"],
              "effective_from": n["effective_from"],
              "audience_size": n["audience_size"],
              "status": n["status"]})
    return d


def revenue_out(r):
    d = base_fields(r)
    d.update({"member_id": r["member_id"],
              "revenue_kind": r["revenue_kind"],
              "amount_cents": r["amount_cents"],
              "occurred_at": r["occurred_at"],
              "fiscal_period": r["fiscal_period"]})
    return d


def reinstatement_out(r):
    d = base_fields(r)
    d.update({"member_id": r["member_id"],
              "requested_at": r["requested_at"],
              "back_dues_invoice_id": r["back_dues_invoice_id"],
              "decided_at": r.get("decided_at"),
              "status": r["status"]})
    return d


# ---------------------------------------------------------------------------
# Risk score — SCAFFOLD member_risk_score / PRD §3.9
# ---------------------------------------------------------------------------
def recompute_risk_score(member):
    if member["status"] not in ("ACTIVE", "GRACE", "LAPSED"):
        return
    now = db.now_utc()
    cutoff_90 = now - timedelta(days=90)
    failed_90 = 0
    for inv in db.dues_invoices.values():
        if inv["member_id"] != member["id"]:
            continue
        for a in db.payment_attempts.values():
            if a["invoice_id"] != inv["id"]:
                continue
            if a["outcome"] in ("DECLINED_TRANSIENT", "DECLINED_HARD"):
                if db.parse_dt(a["attempted_at"]) >= cutoff_90:
                    failed_90 += 1
    failed_component = min(40, 20 * failed_90)

    expiry_component = 0
    if member.get("current_period_end"):
        days_to_end = (db.parse_dt(member["current_period_end"]) - now).days
        expiry_component = max(0, 30 - (days_to_end // 2))

    cutoff_30 = now - timedelta(days=30)
    usage_events = [t for t in db.benefit_usage_events.get(member["id"], [])
                    if t >= cutoff_30]
    usage_component = max(0, 30 - len(usage_events))

    score = failed_component + expiry_component + usage_component
    member["risk_score"] = max(0, min(100, score))


# ---------------------------------------------------------------------------
# Benefit & directory propagation — SCAFFOLD benefit_suspension_propagation / PRD §3.9
# ---------------------------------------------------------------------------
def recompute_listing_visibility(listing, member):
    category = db.membership_categories.get(member["category_id"])
    eligible = bool(category and category["is_directory_eligible"])
    if member["status"] in ("GRACE", "LAPSED"):
        listing["visibility_state"] = "HIDDEN_LAPSE"
    elif member["status"] in ("RESIGNED", "EXPELLED") or not listing["is_public"]:
        listing["visibility_state"] = "HIDDEN_OPT_OUT"
    elif not eligible:
        listing["visibility_state"] = "HIDDEN_CATEGORY"
    elif listing["is_public"] and member["status"] == "ACTIVE":
        listing["visibility_state"] = "VISIBLE"
    else:
        listing["visibility_state"] = "HIDDEN_OPT_OUT"
    db.touch(listing)


def propagate_benefits(member, to_state):
    target = "SUSPENDED" if to_state in ("GRACE", "LAPSED") else "REVOKED"
    now_iso = db.iso(db.now_utc())
    for e in db.benefit_entitlements.values():
        if e["member_id"] == member["id"] and e["status"] == "ACTIVE":
            e["status"] = target
            if target == "SUSPENDED":
                e["suspended_at"] = now_iso
            db.touch(e)
    # Directory
    for l in db.directory_listings.values():
        if l["member_id"] == member["id"]:
            recompute_listing_visibility(l, member)
    # Invoice fulfillment propagation (PRD §3.9)
    for inv in db.dues_invoices.values():
        if inv["member_id"] != member["id"]:
            continue
        if inv["fulfillment_status"] == "COVERAGE_ACTIVE":
            if to_state in ("GRACE", "LAPSED"):
                inv["fulfillment_status"] = "COVERAGE_SUSPENDED"
                db.touch(inv)
            elif to_state in ("RESIGNED", "EXPELLED"):
                inv["fulfillment_status"] = "COVERAGE_ENDED"
                db.touch(inv)


def restore_benefits(member):
    now_iso = db.iso(db.now_utc())
    for e in db.benefit_entitlements.values():
        if e["member_id"] == member["id"] and e["status"] == "SUSPENDED":
            e["status"] = "ACTIVE"
            e["suspended_at"] = None
            db.touch(e)
    for l in db.directory_listings.values():
        if l["member_id"] == member["id"]:
            recompute_listing_visibility(l, member)
    for inv in db.dues_invoices.values():
        if inv["member_id"] == member["id"] and inv["fulfillment_status"] == "COVERAGE_SUSPENDED":
            inv["fulfillment_status"] = "COVERAGE_ACTIVE"
            db.touch(inv)


def new_entity(extra):
    now_iso = db.iso(db.now_utc())
    e = {"id": db.new_id(), "created_at": now_iso, "updated_at": now_iso, "version": 1}
    e.update(extra)
    return e


def write_off_open_invoices(member):
    for inv in db.dues_invoices.values():
        if inv["member_id"] == member["id"] and inv["payment_status"] in ("PENDING", "FAILED_RETRYABLE"):
            inv["payment_status"] = "WRITTEN_OFF"
            inv["fulfillment_status"] = "COVERAGE_ENDED"
            db.touch(inv)


def revoke_auto_renew(member):
    for a in db.auto_renew_authorizations.values():
        if a["member_id"] == member["id"] and a["status"] != "REVOKED":
            a["status"] = "REVOKED"
            a["revoked_at"] = db.iso(db.now_utc())
            db.touch(a)


def create_term(member, period_start, period_end, opened_by):
    t = new_entity({
        "member_id": member["id"],
        "period_start": db.iso(period_start),
        "period_end": db.iso(period_end),
        "opened_by": opened_by,
        "status": "OPEN",
    })
    db.membership_terms[t["id"]] = t
    return t


def create_invoice(member, term, amount_cents, schedule, due_at):
    inv = new_entity({
        "member_id": member["id"],
        "membership_term_id": term["id"] if term else None,
        "dues_schedule_id": schedule["id"] if schedule else None,
        "amount_cents": amount_cents,
        "chapter_share_cents": None,
        "issued_at": db.iso(db.now_utc()),
        "due_at": db.iso(due_at),
        "settled_at": None,
        "payment_status": "PENDING",
        "fulfillment_status": "NOT_DUE",
    })
    db.dues_invoices[inv["id"]] = inv
    return inv


def failed_attempt_count(invoice_id):
    n = 0
    for a in db.payment_attempts.values():
        if a["invoice_id"] == invoice_id and a["outcome"] in ("DECLINED_TRANSIENT", "DECLINED_HARD"):
            n += 1
    return n


def last_attempt_outcome(invoice_id):
    best = None
    for a in db.payment_attempts.values():
        if a["invoice_id"] != invoice_id:
            continue
        if best is None or a["attempt_index"] > best["attempt_index"]:
            best = a
    return best["outcome"] if best else None


def settle_invoice(invoice):
    """SETTLED cascade — SCAFFOLD DuesInvoice transition 1 / PRD §3.5."""
    member = db.members[invoice["member_id"]]
    now_iso = db.iso(db.now_utc())
    schedule = db.dues_schedules.get(invoice["dues_schedule_id"])
    share = pricing.chapter_share(invoice["amount_cents"], schedule["chapter_share_bps"]) if schedule else 0

    invoice["payment_status"] = "SETTLED"
    invoice["fulfillment_status"] = "COVERAGE_ACTIVE"
    invoice["settled_at"] = now_iso
    invoice["chapter_share_cents"] = share
    db.touch(invoice)

    # chapter share ledger accrual
    ch = member["home_chapter_id"]
    db.chapter_share_ledger[ch] = db.chapter_share_ledger.get(ch, 0) + share

    # term OPEN
    term = db.membership_terms.get(invoice["membership_term_id"])
    if term and term["status"] != "OPEN":
        term["status"] = "OPEN"
        db.touch(term)

    # member ledger + grace recovery
    member["lifetime_dues_paid_cents"] = member.get("lifetime_dues_paid_cents", 0) + invoice["amount_cents"]
    if member["status"] == "GRACE" and term:
        member["status"] = "ACTIVE"
        member["current_period_start"] = term["period_start"]
        member["current_period_end"] = term["period_end"]
        restore_benefits(member)
    recompute_risk_score(member)
    db.touch(member)


def open_term_and_invoice(member, opened_by, at_dt):
    """Create a term + invoice for the period containing at_dt (join or renewal)."""
    amount, period_start, period_end, schedule = pricing.compute_invoice_amount(member, at_dt)
    term = create_term(member, period_start, period_end, opened_by)
    inv = create_invoice(member, term, amount, schedule, period_end)
    return term, inv
