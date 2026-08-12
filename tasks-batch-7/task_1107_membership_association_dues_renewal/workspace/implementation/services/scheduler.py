"""Renewal-cycle sweep and clock-advance scheduler — SCAFFOLD scheduler endpoints / PRD §3.8."""
from datetime import timedelta

import db
from services import pricing, lifecycle


def _auto_renew_charge(member, invoice):
    """Record an auto-renew PaymentAttempt and cascade per §3.5. Auto attempts succeed."""
    idx = 1
    for a in db.payment_attempts.values():
        if a["invoice_id"] == invoice["id"]:
            idx = max(idx, a["attempt_index"] + 1)
    attempt = lifecycle.new_entity({
        "invoice_id": invoice["id"],
        "attempt_index": idx,
        "attempted_at": db.iso(db.now_utc()),
        "outcome": "SUCCEEDED",
        "decline_code": None,
    })
    db.payment_attempts[attempt["id"]] = attempt
    lifecycle.settle_invoice(invoice)


def run_sweep():
    """The renewal-cycle sweep: issue renewal invoices, auto-renew charges, advance state transitions."""
    now = db.now_utc()
    lookahead = now + timedelta(days=db.RENEWAL_LOOKAHEAD_DAYS)

    for member in list(db.members.values()):
        category = db.membership_categories.get(member["category_id"])
        if category is None:
            continue

        # --- Renewal invoice issuance for ACTIVE/GRACE members near or past period end ---
        # PRD §3.8 + §3.7: the renewal invoice must exist while the member is in GRACE
        # so that "recovery from grace" via settling it is possible.
        if member["status"] in ("ACTIVE", "GRACE") and member.get("current_period_end"):
            cpe = db.parse_dt(member["current_period_end"])
            if cpe <= lookahead:  # cpe is within lookahead days in the future, or already past
                # check if an unpaid renewal invoice already exists for the next period
                has_open = any(
                    inv["member_id"] == member["id"]
                    and inv["payment_status"] in ("PENDING", "FAILED_RETRYABLE")
                    and inv.get("dues_schedule_id") is not None
                    and db.parse_dt(inv["due_at"]) > cpe - timedelta(seconds=1)
                    for inv in db.dues_invoices.values()
                )
                if not has_open:
                    try:
                        lifecycle.open_term_and_invoice(member, "RENEWAL", cpe)
                    except Exception:
                        pass

        # --- Auto-renew charge attempts for unpaid invoices that have reached due_at ---
        # PRD §3.8: the sweep performs an auto-renew charge attempt for every ACTIVE
        # AutoRenewAuthorization. Deferred until the invoice's due_at so a freshly
        # issued renewal invoice stays PENDING (and manually payable) until due.
        for a in db.auto_renew_authorizations.values():
            if a["member_id"] != member["id"] or a["status"] != "ACTIVE":
                continue
            if member["status"] not in ("ACTIVE", "GRACE"):
                continue
            for inv in db.dues_invoices.values():
                if inv["member_id"] != member["id"]:
                    continue
                if inv["payment_status"] not in ("PENDING", "FAILED_RETRYABLE"):
                    continue
                if inv.get("dues_schedule_id") is None:
                    continue
                if db.parse_dt(inv["due_at"]) > now:
                    continue
                if any(p["invoice_id"] == inv["id"] for p in db.payment_attempts.values()):
                    continue  # already auto-charged or manually attempted
                _auto_renew_charge(member, inv)
                break

        # --- ACTIVE -> GRACE ---
        if member["status"] == "ACTIVE" and member.get("current_period_end"):
            cpe = db.parse_dt(member["current_period_end"])
            if now > cpe:
                covered = any(
                    inv["member_id"] == member["id"] and inv["payment_status"] == "SETTLED"
                    and db.parse_dt(inv["due_at"]) >= cpe
                    and inv["membership_term_id"] is not None
                    and db.membership_terms.get(inv["membership_term_id"], {}).get("period_end") is not None
                    and db.parse_dt(db.membership_terms[inv["membership_term_id"]]["period_end"]) > cpe
                    for inv in db.dues_invoices.values()
                )
                if not covered:
                    member["status"] = "GRACE"
                    lifecycle.propagate_benefits(member, "GRACE")
                    lifecycle.recompute_risk_score(member)
                    db.touch(member)

        # --- GRACE -> LAPSED ---
        if member["status"] == "GRACE" and member.get("current_period_end"):
            cpe = db.parse_dt(member["current_period_end"])
            if now > cpe + timedelta(days=int(category["lapse_grace_days"])):
                member["status"] = "LAPSED"
                db.member_lapse_ts[member["id"]] = now
                # auto-renew: if last attempt DECLINED_HARD and authorization ACTIVE -> suspend
                for a in db.auto_renew_authorizations.values():
                    if a["member_id"] == member["id"] and a["status"] == "ACTIVE":
                        last = None
                        for inv in db.dues_invoices.values():
                            if inv["member_id"] != member["id"]:
                                continue
                            o = lifecycle.last_attempt_outcome(inv["id"])
                            if o:
                                last = o
                        if last == "DECLINED_HARD":
                            a["status"] = "SUSPENDED_HARD_DECLINE"
                            db.touch(a)
                lifecycle.propagate_benefits(member, "LAPSED")
                lifecycle.recompute_risk_score(member)
                db.touch(member)

        # --- LAPSED -> EXPELLED ---
        if member["status"] == "LAPSED":
            lapse_ts = db.member_lapse_ts.get(member["id"])
            if lapse_ts and now > lapse_ts + timedelta(days=int(category["reinstatement_window_days"])):
                member["status"] = "EXPELLED"
                for r in db.reinstatement_requests.values():
                    if r["member_id"] == member["id"] and r["status"] == "PENDING":
                        r["status"] = "EXPIRED"
                        db.touch(r)
                for a in db.auto_renew_authorizations.values():
                    if a["member_id"] == member["id"] and a["status"] != "REVOKED":
                        a["status"] = "REVOKED"
                        a["revoked_at"] = db.iso(now)
                        db.touch(a)
                lifecycle.propagate_benefits(member, "EXPELLED")
                db.touch(member)

        # --- PENDING reinstatement -> EXPIRED (same window rule) ---
        if member["status"] == "LAPSED":
            lapse_ts = db.member_lapse_ts.get(member["id"])
            if lapse_ts:
                for r in db.reinstatement_requests.values():
                    if r["member_id"] == member["id"] and r["status"] == "PENDING":
                        if now > lapse_ts + timedelta(days=int(category["reinstatement_window_days"])):
                            r["status"] = "EXPIRED"
                            db.touch(r)
