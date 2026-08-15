"""Loan servicing posture re-evaluation and watchlist risk score."""
import db
from services.common import now_iso, touch


def loan_open_assessments(loan_id):
    return [
        a for a in db.covenant_assessments.values()
        if a["loan_id"] == loan_id and a["status"] == "OPEN"
    ]


def loan_active_entries(loan_id):
    return [
        e for e in db.watchlist_entries.values()
        if e["loan_id"] == loan_id and e["status"] == "ACTIVE"
    ]


def _set_reserve_flags(loan, elevated=None, frozen=None):
    for r in db.reserve_accounts.values():
        if r["loan_id"] != loan["id"]:
            continue
        changed = False
        if elevated is not None and r["elevated_retainage"] != elevated:
            r["elevated_retainage"] = elevated
            changed = True
        if frozen is not None and r["disbursement_frozen"] != frozen:
            r["disbursement_frozen"] = frozen
            changed = True
        if changed:
            touch(r)


def reevaluate_servicing(loan):
    """§2.9/§3.6 automatic posture transitions. SPECIAL_SERVICING only leaves via reinstate."""
    if loan["servicing_status"] == "SPECIAL_SERVICING":
        return
    has_open = len(loan_open_assessments(loan["id"])) > 0
    has_active = len(loan_active_entries(loan["id"])) > 0
    if loan["servicing_status"] == "PERFORMING" and (has_open or has_active):
        loan["servicing_status"] = "WATCHLIST"
        touch(loan)
        _set_reserve_flags(loan, elevated=True)
    elif loan["servicing_status"] == "WATCHLIST" and not has_open and not has_active:
        loan["servicing_status"] = "PERFORMING"
        touch(loan)
        _set_reserve_flags(loan, elevated=False)


def escalate_to_special_servicing(loan, entry):
    """WATCHLIST -> SPECIAL_SERVICING cascade (§3.6)."""
    entry["status"] = "ESCALATED"
    touch(entry)
    loan["servicing_status"] = "SPECIAL_SERVICING"
    touch(loan)
    _set_reserve_flags(loan, elevated=True, frozen=True)
    # SUBMITTED draws -> REJECTED (never held); APPROVED draws -> CANCELLED (release hold)
    for r in db.reserve_accounts.values():
        if r["loan_id"] != loan["id"]:
            continue
        for d in db.disbursement_requests.values():
            if d["reserve_account_id"] != r["id"]:
                continue
            if d["status"] == "SUBMITTED":
                d["status"] = "REJECTED"
                touch(d)
            elif d["status"] == "APPROVED":
                d["status"] = "CANCELLED"
                touch(d)
                r["held_cents"] -= d["amount_cents"]
                touch(r)
    # AVAILABLE extension options -> SUSPENDED
    for o in db.extension_options.values():
        if o["loan_id"] == loan["id"] and o["status"] == "AVAILABLE":
            o["status"] = "SUSPENDED"
            touch(o)


def loan_days_delinquent(loan):
    if loan["payment_status"] in ("DELINQUENT", "DEFAULT") and loan.get("delinquent_since_dt"):
        delta = db.get_clock() - loan["delinquent_since_dt"]
        return max(0, int(delta.total_seconds() // 86400))
    return 0


def latest_completed_inspection(loan):
    best = None
    for insp in db.inspections.values():
        prop = db.properties.get(insp["property_id"])
        if not prop or prop["loan_id"] != loan["id"]:
            continue
        if insp["status"] != "COMPLETED":
            continue
        if best is None or insp["completed_at_dt"] > best["completed_at_dt"]:
            best = insp
    return best


def compute_risk_score(loan):
    """calculations.watchlist_risk_score (§3.6)."""
    dscr = loan.get("current_dscr")
    if dscr is None:
        dscr_c = 10
    elif dscr >= 1.25:
        dscr_c = 0
    elif dscr >= 1.10:
        dscr_c = 15
    elif dscr >= 1.00:
        dscr_c = 30
    else:
        dscr_c = 45

    dd = loan_days_delinquent(loan)
    if dd <= 0:
        del_c = 0
    elif dd <= 29:
        del_c = 10
    elif dd <= 59:
        del_c = 20
    else:
        del_c = 35

    insp = latest_completed_inspection(loan)
    if insp is None:
        insp_c = 5
    else:
        insp_c = {"GOOD": 0, "FAIR": 5, "POOR": 15, "CRITICAL": 25}[insp["condition_rating"]]

    ltv = loan.get("current_ltv")
    if ltv is None:
        ltv_c = 10
    elif ltv < 0.65:
        ltv_c = 0
    elif ltv < 0.75:
        ltv_c = 10
    elif ltv < 0.85:
        ltv_c = 20
    else:
        ltv_c = 30

    synergy = 10 if (dd >= 30 and dscr is not None and dscr < 1.00) else 0
    return min(100, dscr_c + del_c + insp_c + ltv_c + synergy)


def has_active_risk_entry(loan_id):
    return any(
        e["loan_id"] == loan_id and e["criterion"] == "RISK_SCORE" and e["status"] == "ACTIVE"
        for e in db.watchlist_entries.values()
    )


def reevaluate_risk(loan):
    score = compute_risk_score(loan)
    if score >= 70 and not has_active_risk_entry(loan["id"]):
        create_watchlist_entry(
            loan, "RISK_SCORE", source_ref=None,
            risk_score_at_creation=score, escalation_review=(score >= 85),
        )


def create_watchlist_entry(loan, criterion, source_ref=None, risk_score_at_creation=None,
                           escalation_review=False):
    from services.common import stamp_new
    e = {
        "id": db.new_id(),
        "loan_id": loan["id"],
        "criterion": criterion,
        "status": "ACTIVE",
        "risk_score_at_creation": risk_score_at_creation,
        "escalation_review": escalation_review,
        "source_ref": source_ref,
        "resolved_at": None,
    }
    stamp_new(e)
    db.watchlist_entries[e["id"]] = e
    return e
