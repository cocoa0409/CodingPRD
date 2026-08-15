"""Business logic: serializers, calculations (§1.3), cascades (§2.9), ops-run sweeps (§2.4)."""
from datetime import datetime, timedelta, timezone

from decimal import Decimal, ROUND_HALF_UP

from core import db, now, new_resource, bump, fmt_dt

UTC = timezone.utc
D2 = Decimal("0.01")
D4 = Decimal("0.0001")
D0 = Decimal("1")


def dec(v):
    return Decimal(str(v))


def _num(d):
    """Decimal -> JSON number (int when integral, else float)."""
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ==================================================================
# Computed employee counters (recomputed on every read, §2.8)
# ==================================================================
def open_case_count(emp_id):
    return sum(1 for c in db["cases"].values()
               if c["subject_employee_id"] == emp_id
               and c["review_status"] in ("OPEN", "UNDER_INVESTIGATION", "REOPENED"))


def training_overdue_count(emp_id):
    return sum(1 for t in db["training"].values()
               if t["employee_id"] == emp_id and t["status"] == "OVERDUE")


# ==================================================================
# Time windows
# ==================================================================
def month_window(ym):
    """'YYYY-MM' -> half-open [first instant of month, first instant of next month)."""
    y, m = int(ym[0:4]), int(ym[5:7])
    start = datetime(y, m, 1, tzinfo=UTC)
    end = datetime(y + 1, 1, 1, tzinfo=UTC) if m == 12 else datetime(y, m + 1, 1, tzinfo=UTC)
    return start, end


def quarter_window(q):
    """'YYYY-Qn' -> Q1=[Jan1,Apr1) Q2=[Apr1,Jul1) Q3=[Jul1,Oct1) Q4=[Oct1,next Jan1)."""
    y, qn = int(q[0:4]), int(q[6])
    m = {1: 1, 2: 4, 3: 7, 4: 10}[qn]
    start = datetime(y, m, 1, tzinfo=UTC)
    end = datetime(y + 1, 1, 1, tzinfo=UTC) if qn == 4 else datetime(y, m + 3, 1, tzinfo=UTC)
    return start, end


# ==================================================================
# calc_execution_quality (§1.3)
# ==================================================================
def compute_eq(snap):
    start, end = month_window(snap["period_month"])
    total_imp = Decimal("0")
    total_qty = 0
    count = 0
    for o in db["orders"].values():
        if o["status"] != "EXECUTED":
            continue
        if o["order_type"] != snap["order_type"]:
            continue
        a = db["arrangements"].get(o["arrangement_id"] or "")
        if a is None or a["venue_id"] != snap["venue_id"]:
            continue
        ex_at = o["executed_at"]
        if ex_at is None or not (start <= ex_at < end):
            continue
        bid = dec(o["arrival_nbbo_bid_cents"])
        ask = dec(o["arrival_nbbo_ask_cents"])
        ex = dec(o["executed_price_cents"])
        if snap["variant"] == "FAR_TOUCH":
            ps = (ask - ex) if o["side"] == "BUY" else (ex - bid)
        else:  # MIDPOINT
            mid = (bid + ask) / 2  # exact, .5 precision kept
            ps = (mid - ex) if o["side"] == "BUY" else (ex - mid)
        # pinned nested rounding order
        ps = ps.quantize(D2, rounding=ROUND_HALF_UP)
        line = (ps * o["quantity"]).quantize(D2, rounding=ROUND_HALF_UP)
        total_imp += line
        total_qty += o["quantity"]
        count += 1
    avg = Decimal("0") if total_qty == 0 else (total_imp / total_qty).quantize(D4, rounding=ROUND_HALF_UP)
    return {"order_count": count,
            "total_quantity": total_qty,
            "total_improvement_cents": _num(total_imp),
            "avg_improvement_cents_per_share": _num(avg)}


# ==================================================================
# calc_pfof_accrual (§1.3)
# ==================================================================
def covering_arrangement(order):
    """Arrangement of the order's venue whose half-open window contains executed_at."""
    a0 = db["arrangements"].get(order["arrangement_id"] or "")
    if a0 is None:
        return None
    vid = a0["venue_id"]
    best = None
    for a in db["arrangements"].values():
        if a["venue_id"] != vid:
            continue
        if a["effective_from"] <= order["executed_at"] < a["effective_to"]:
            if best is None or a["effective_from"] > best["effective_from"]:
                best = a
    return best


def tier_eval(shares, tiers, variant):
    """Integer cents for one (arrangement, month) group; round-half-up per band (MARGINAL)
    or once on the whole group (RETROACTIVE)."""
    if variant == "MARGINAL":
        total = 0
        for i, t in enumerate(tiers):
            lo = t["min_monthly_shares"]
            hi = tiers[i + 1]["min_monthly_shares"] if i + 1 < len(tiers) else None
            band = max(0, (min(shares, hi) if hi is not None else shares) - lo)
            total += int((dec(band) * dec(t["rate_cents_per_share"])).quantize(D0, rounding=ROUND_HALF_UP))
        return total
    # RETROACTIVE: single highest qualifying tier rate applies to ALL shares
    rate = None
    for t in tiers:
        if t["min_monthly_shares"] <= shares:
            rate = t["rate_cents_per_share"]
    if rate is None:
        rate = 0
    return int((dec(shares) * dec(rate)).quantize(D0, rounding=ROUND_HALF_UP))


def compute_venue_lines(disc):
    """Returns (venue_lines, total_pfof_cents). Pins arrangement_id + current
    arrangement version of the venue-month group with the greatest max(executed_at)."""
    qstart, qend = quarter_window(disc["quarter"])
    groups = {}
    for o in db["orders"].values():
        if o["status"] != "EXECUTED":
            continue
        ex_at = o["executed_at"]
        if ex_at is None or not (qstart <= ex_at < qend):
            continue
        a = covering_arrangement(o)
        if a is None:
            continue  # uncovered volume: excluded from accrual (blocks submit instead)
        key = (a["id"], ex_at.year * 100 + ex_at.month)
        g = groups.get(key)
        if g is None:
            g = {"arrangement": a, "venue_id": a["venue_id"], "S": 0, "max_exec": ex_at}
            groups[key] = g
        g["S"] += o["quantity"]
        if ex_at > g["max_exec"]:
            g["max_exec"] = ex_at
    by_venue = {}
    for g in groups.values():
        v = by_venue.get(g["venue_id"])
        if v is None:
            v = {"total_shares": 0, "pfof_cents": 0, "groups": []}
            by_venue[g["venue_id"]] = v
        v["total_shares"] += g["S"]
        v["pfof_cents"] += tier_eval(g["S"], g["arrangement"]["pfof_tiers"], disc["pricing_variant"])
        v["groups"].append(g)
    lines = []
    for vid in sorted(by_venue.keys()):
        v = by_venue[vid]
        latest = max(v["groups"], key=lambda g: g["max_exec"])
        a = latest["arrangement"]
        lines.append({"venue_id": vid,
                      "arrangement_id": a["id"],
                      "arrangement_version": a["version"],
                      "total_shares": v["total_shares"],
                      "pfof_cents": v["pfof_cents"]})
    return lines, sum(l["pfof_cents"] for l in lines)


# ==================================================================
# calc_front_running_score (§1.3) + alert creation
# ==================================================================
def fr_score(o, p):
    delta = abs((o["executed_at"] - p["executed_at"]).total_seconds())
    d_delta = dec(delta)
    tf = Decimal(50) * max(Decimal(0), Decimal(1) - d_delta / Decimal(3600))
    size_ratio = min(p["quantity"], o["quantity"]) / max(p["quantity"], o["quantity"])
    sf = Decimal(30) * dec(size_ratio)
    same_side = p["side"] == o["side"]
    side = Decimal(20) if same_side else Decimal(0)
    # factors summed first, rounded once at the end (rounding factors first is forbidden)
    score = int((tf + sf + side).quantize(D0, rounding=ROUND_HALF_UP))
    inputs = {"delta_seconds": int(delta) if delta == int(delta) else delta,
              "size_ratio": size_ratio,
              "same_side": same_side}
    return score, inputs


def create_alert(alert_type, subject_employee_id, order_id, trade_id, score, score_inputs):
    a = new_resource()
    a.update({"alert_type": alert_type,
              "subject_employee_id": subject_employee_id,
              "related_order_id": order_id,
              "related_trade_id": trade_id,
              "case_id": None,
              "score": score,
              "score_inputs": score_inputs,
              "status": "NEW"})
    db["alerts"][a["id"]] = a
    return a


def forward_front_running_scan(order):
    """On Order -> EXECUTED at T: prior employee trades in [T-3600s, T)."""
    T = order["executed_at"]
    lo = T - timedelta(seconds=3600)
    for p in list(db["trades"].values()):
        if p["symbol"] != order["symbol"]:
            continue
        if p["status"] not in ("EXECUTION_REPORTED", "RECONCILED"):
            continue
        pt = p["executed_at"]
        if pt is None or not (lo <= pt < T):
            continue
        score, inputs = fr_score(order, p)
        create_alert("FRONT_RUNNING", p["employee_id"], order["id"], p["id"], score, inputs)


def reverse_front_running_scan(trade):
    """On PersonalTrade -> EXECUTION_REPORTED at Pt: later client orders in (Pt, Pt+3600s]."""
    Pt = trade["executed_at"]
    hi = Pt + timedelta(seconds=3600)
    for o in list(db["orders"].values()):
        if o["symbol"] != trade["symbol"] or o["status"] != "EXECUTED":
            continue
        ot = o["executed_at"]
        if ot is None or not (Pt < ot <= hi):
            continue
        score, inputs = fr_score(o, trade)
        create_alert("FRONT_RUNNING", trade["employee_id"], o["id"], trade["id"], score, inputs)


def marking_close_check(order):
    """calc_marking_close_score: only for MARKET_ON_CLOSE; deviation >= 25 bps (inclusive)."""
    if order["order_type"] != "MARKET_ON_CLOSE":
        return
    bid = dec(order["arrival_nbbo_bid_cents"])
    ask = dec(order["arrival_nbbo_ask_cents"])
    mid = (bid + ask) / 2  # exact .5 precision, never pre-rounded
    dev = abs(dec(order["executed_price_cents"]) - mid) * Decimal(10000) / mid
    deviation_bps = int(dev.quantize(D0, rounding=ROUND_HALF_UP))
    if deviation_bps >= 25:
        score = min(100, deviation_bps * 2)
        create_alert("MARKING_THE_CLOSE", None, order["id"], None, score,
                     {"deviation_bps": deviation_bps})


# ==================================================================
# calc_lexicon_score (§1.3)
# ==================================================================
def active_lexicon_policy():
    for p in db["lexicon"].values():
        if p["status"] == "ACTIVE":
            return p
    return None


def lexicon_score(body_text, policy):
    """Case-insensitive substring; each term counts at most once."""
    if policy is None:
        return 0, [], None
    low = body_text.lower()
    matched = []
    score = 0
    for t in policy["terms"]:
        if t["term"].lower() in low:
            matched.append(t["term"])
            score += t["weight"]
    return score, matched, policy["version"]


def create_case(subject_employee_id, opened_from, source_comm_item_id=None, linked_alert_ids=None):
    c = new_resource()
    c.update({"subject_employee_id": subject_employee_id,
              "opened_from": opened_from,
              "source_comm_item_id": source_comm_item_id,
              "linked_alert_ids": list(linked_alert_ids or []),
              "review_status": "OPEN",
              "disposition": None,
              "dispositioned_at": None,
              "filing_status": "NOT_REQUIRED",
              "filing_due_at": None,
              "filing_submitted_at": None,
              "late_fee_cents": 0})
    db["cases"][c["id"]] = c
    return c


def escalate_comm_item(item):
    item["status"] = "ESCALATED"
    create_case(item["author_employee_id"], "COMM_REVIEW", source_comm_item_id=item["id"])


def rescore_queued_comm_items():
    """Lexicon cascade: rescore QUEUED items against the ACTIVE policy (score 0 when none);
    auto-escalate at >= 100 (link 2) creating cases (link 3); never auto-down-tier.
    IN_REVIEW items are untouched."""
    policy = active_lexicon_policy()
    for item in list(db["comm_items"].values()):
        if item["status"] != "QUEUED":
            continue
        score, matched, ver = lexicon_score(item["body_text"], policy)
        item["score"] = score
        item["matched_terms"] = matched
        item["scored_policy_version"] = ver
        if score >= 100:
            escalate_comm_item(item)
        bump(item)


# ==================================================================
# calc_late_filing_fee (§1.3)
# ==================================================================
LATE_BASE_CENTS = 50000
LATE_PER_DAY_CENTS = 5000
LATE_CAP_CENTS = 500000


def calc_late_fee(submitted_at, due_at):
    if submitted_at <= due_at:  # on time, boundary inclusive
        return 0
    seconds_late = (submitted_at - due_at).total_seconds()
    days_late = int(seconds_late // 86400)  # partial days discarded
    return min(LATE_CAP_CENTS, LATE_BASE_CENTS + LATE_PER_DAY_CENTS * days_late)


# ==================================================================
# Cascades (§2.9)
# ==================================================================
def cancel_routed_orders(arrangement):
    for o in db["orders"].values():
        if o["arrangement_id"] == arrangement["id"] and o["status"] == "ROUTED":
            o["status"] = "CANCELLED"
            bump(o)


def cascade_arrangement_suspended(arrangement):
    arrangement["status"] = "SUSPENDED"
    bump(arrangement)
    cancel_routed_orders(arrangement)


def cascade_venue_suspended(venue):
    venue["status"] = "SUSPENDED"
    bump(venue)
    for a in db["arrangements"].values():
        if a["venue_id"] == venue["id"] and a["status"] == "ACTIVE":
            cascade_arrangement_suspended(a)


def cascade_employee_terminated(emp):
    for t in db["trades"].values():
        if t["employee_id"] != emp["id"]:
            continue
        if t["status"] == "PRECLEARANCE_REQUESTED":
            t["status"] = "DENIED"
            t["denial_reason"] = "EMPLOYMENT_ENDED"
            t["decided_at"] = now()
            bump(t)
        elif t["status"] == "APPROVED":
            t["status"] = "EXPIRED"
            bump(t)
    for ta in db["training"].values():
        if ta["employee_id"] == emp["id"] and ta["status"] in ("ASSIGNED", "OVERDUE"):
            ta["status"] = "CANCELLED"
            bump(ta)


# ==================================================================
# Ops-run checkpoint sweeps (§2.4)
# ==================================================================
def run_ops_sweeps():
    n = now()
    tally = {"restricted_activated": 0, "restricted_expired": 0,
             "preclearances_expired": 0, "preclearances_denied": 0,
             "attestations_due": 0, "attestations_lapsed": 0,
             "training_marked_overdue": 0}
    # RestrictedListEntry epoch transitions
    for r in db["restricted"].values():
        if r["status"] == "SCHEDULED":
            if n >= r["effective_to"]:
                r["status"] = "EXPIRED"
                bump(r)
                tally["restricted_expired"] += 1
            elif n >= r["effective_from"]:
                r["status"] = "ACTIVE"
                bump(r)
                tally["restricted_activated"] += 1
                # activation cascade: deny still-pending preclearances in this symbol
                for t in db["trades"].values():
                    if t["symbol"] == r["symbol"] and t["status"] == "PRECLEARANCE_REQUESTED":
                        t["status"] = "DENIED"
                        t["denial_reason"] = "RESTRICTED_LIST"
                        t["decided_at"] = n
                        bump(t)
                        tally["preclearances_denied"] += 1
        elif r["status"] == "ACTIVE":
            if n >= r["effective_to"]:
                r["status"] = "EXPIRED"
                bump(r)
                tally["restricted_expired"] += 1
    # APPROVED personal trades past expires_at -> EXPIRED (strictly past)
    for t in db["trades"].values():
        if t["status"] == "APPROVED" and t["expires_at"] is not None and n > t["expires_at"]:
            t["status"] = "EXPIRED"
            bump(t)
            tally["preclearances_expired"] += 1
    # Attestation CURRENT->DUE->LAPSED (terminated employees admit no transitions)
    for e in db["employees"].values():
        if e["employment_status"] == "TERMINATED":
            continue
        due = e["attestation_due_at"]
        if due is None:
            continue
        if n >= due:
            if e["attestation_status"] != "LAPSED":
                e["attestation_status"] = "LAPSED"
                bump(e)
                tally["attestations_lapsed"] += 1
        elif n >= due - timedelta(days=30):
            if e["attestation_status"] == "CURRENT":
                e["attestation_status"] = "DUE"
                bump(e)
                tally["attestations_due"] += 1
    # Training ASSIGNED -> OVERDUE past due_date (strictly past)
    for ta in db["training"].values():
        if ta["status"] == "ASSIGNED" and ta["due_date"] is not None and n > ta["due_date"]:
            ta["status"] = "OVERDUE"
            bump(ta)
            tally["training_marked_overdue"] += 1
    return tally


# ==================================================================
# Serializers
# ==================================================================
def ser_employee(e):
    return {"id": e["id"], "full_name": e["full_name"], "employee_ref": e["employee_ref"],
            "department": e["department"],
            "employment_status": e["employment_status"],
            "attestation_status": e["attestation_status"],
            "attestation_due_at": fmt_dt(e["attestation_due_at"]),
            "last_attested_at": fmt_dt(e["last_attested_at"]),
            "open_case_count": open_case_count(e["id"]),
            "training_overdue_count": training_overdue_count(e["id"]),
            "created_at": fmt_dt(e["created_at"]), "updated_at": fmt_dt(e["updated_at"]),
            "version": e["version"]}


def ser_venue(v):
    return {"id": v["id"], "venue_code": v["venue_code"], "name": v["name"],
            "venue_type": v["venue_type"], "status": v["status"],
            "created_at": fmt_dt(v["created_at"]), "updated_at": fmt_dt(v["updated_at"]),
            "version": v["version"]}


def ser_arrangement(a):
    return {"id": a["id"], "venue_id": a["venue_id"],
            "effective_from": fmt_dt(a["effective_from"]),
            "effective_to": fmt_dt(a["effective_to"]),
            "pfof_tiers": a["pfof_tiers"], "routing_fee_bps": a["routing_fee_bps"],
            "status": a["status"],
            "created_at": fmt_dt(a["created_at"]), "updated_at": fmt_dt(a["updated_at"]),
            "version": a["version"]}


def ser_order(o):
    return {"id": o["id"], "client_ref": o["client_ref"], "symbol": o["symbol"],
            "side": o["side"], "quantity": o["quantity"], "order_type": o["order_type"],
            "limit_price_cents": o["limit_price_cents"],
            "arrival_nbbo_bid_cents": o["arrival_nbbo_bid_cents"],
            "arrival_nbbo_ask_cents": o["arrival_nbbo_ask_cents"],
            "arrangement_id": o["arrangement_id"], "status": o["status"],
            "routed_at": fmt_dt(o["routed_at"]),
            "executed_price_cents": o["executed_price_cents"],
            "executed_at": fmt_dt(o["executed_at"]),
            "created_at": fmt_dt(o["created_at"]), "updated_at": fmt_dt(o["updated_at"]),
            "version": o["version"]}


def ser_snapshot(s):
    # PROVISIONAL recomputes metrics on every read; LOCKED returns frozen values
    metrics = compute_eq(s) if s["status"] == "PROVISIONAL" else s["frozen_metrics"]
    return {"id": s["id"], "venue_id": s["venue_id"], "order_type": s["order_type"],
            "period_month": s["period_month"], "variant": s["variant"], "status": s["status"],
            "order_count": metrics["order_count"],
            "total_quantity": metrics["total_quantity"],
            "total_improvement_cents": metrics["total_improvement_cents"],
            "avg_improvement_cents_per_share": metrics["avg_improvement_cents_per_share"],
            "created_at": fmt_dt(s["created_at"]), "updated_at": fmt_dt(s["updated_at"]),
            "version": s["version"]}


def ser_disclosure(d):
    # DRAFT recomputes venue_lines on read; other states return frozen lines
    if d["status"] == "DRAFT":
        lines, total = compute_venue_lines(d)
    else:
        lines, total = d["frozen_lines"], d["frozen_total"]
    return {"id": d["id"], "quarter": d["quarter"], "pricing_variant": d["pricing_variant"],
            "revision_number": d["revision_number"], "supersedes_id": d["supersedes_id"],
            "has_pending_revision": d["has_pending_revision"], "status": d["status"],
            "venue_lines": lines, "total_pfof_cents": total,
            "submitted_at": fmt_dt(d["submitted_at"]),
            "created_at": fmt_dt(d["created_at"]), "updated_at": fmt_dt(d["updated_at"]),
            "version": d["version"]}


def ser_review(r):
    return {"id": r["id"], "quarter": r["quarter"], "snapshot_ids": r["snapshot_ids"],
            "venue_decisions": r["venue_decisions"],
            "created_by_user_id": r["created_by_user_id"],
            "voter_user_ids": r["voter_user_ids"], "status": r["status"],
            "created_at": fmt_dt(r["created_at"]), "updated_at": fmt_dt(r["updated_at"]),
            "version": r["version"]}


def ser_alert(a):
    return {"id": a["id"], "alert_type": a["alert_type"],
            "subject_employee_id": a["subject_employee_id"],
            "related_order_id": a["related_order_id"],
            "related_trade_id": a["related_trade_id"],
            "case_id": a["case_id"], "score": a["score"],
            "score_inputs": a["score_inputs"], "status": a["status"],
            "created_at": fmt_dt(a["created_at"]), "updated_at": fmt_dt(a["updated_at"]),
            "version": a["version"]}


def ser_case(c):
    return {"id": c["id"], "subject_employee_id": c["subject_employee_id"],
            "opened_from": c["opened_from"], "source_comm_item_id": c["source_comm_item_id"],
            "linked_alert_ids": c["linked_alert_ids"],
            "review_status": c["review_status"], "disposition": c["disposition"],
            "dispositioned_at": fmt_dt(c["dispositioned_at"]),
            "filing_status": c["filing_status"],
            "filing_due_at": fmt_dt(c["filing_due_at"]),
            "filing_submitted_at": fmt_dt(c["filing_submitted_at"]),
            "late_fee_cents": c["late_fee_cents"],
            "created_at": fmt_dt(c["created_at"]), "updated_at": fmt_dt(c["updated_at"]),
            "version": c["version"]}


def ser_trade(t):
    return {"id": t["id"], "employee_id": t["employee_id"], "symbol": t["symbol"],
            "side": t["side"], "quantity": t["quantity"], "status": t["status"],
            "decided_at": fmt_dt(t["decided_at"]), "denial_reason": t["denial_reason"],
            "expires_at": fmt_dt(t["expires_at"]),
            "executed_price_cents": t["executed_price_cents"],
            "executed_at": fmt_dt(t["executed_at"]),
            "reconciled_at": fmt_dt(t["reconciled_at"]),
            "created_at": fmt_dt(t["created_at"]), "updated_at": fmt_dt(t["updated_at"]),
            "version": t["version"]}


def ser_restricted(r):
    return {"id": r["id"], "symbol": r["symbol"], "restriction_kind": r["restriction_kind"],
            "effective_from": fmt_dt(r["effective_from"]),
            "effective_to": fmt_dt(r["effective_to"]), "status": r["status"],
            "created_at": fmt_dt(r["created_at"]), "updated_at": fmt_dt(r["updated_at"]),
            "version": r["version"]}


def ser_comm_item(i):
    return {"id": i["id"], "channel": i["channel"], "author_employee_id": i["author_employee_id"],
            "body_text": i["body_text"], "captured_at": fmt_dt(i["captured_at"]),
            "score": i["score"], "matched_terms": i["matched_terms"],
            "scored_policy_version": i["scored_policy_version"], "status": i["status"],
            "created_at": fmt_dt(i["created_at"]), "updated_at": fmt_dt(i["updated_at"]),
            "version": i["version"]}


def ser_lexicon(p):
    return {"id": p["id"], "name": p["name"], "terms": p["terms"], "status": p["status"],
            "created_at": fmt_dt(p["created_at"]), "updated_at": fmt_dt(p["updated_at"]),
            "version": p["version"]}


def ser_policy(p):
    return {"id": p["id"], "policy_code": p["policy_code"], "title": p["title"],
            "version_label": p["version_label"], "status": p["status"],
            "created_at": fmt_dt(p["created_at"]), "updated_at": fmt_dt(p["updated_at"]),
            "version": p["version"]}


def ser_training(t):
    return {"id": t["id"], "employee_id": t["employee_id"], "policy_id": t["policy_id"],
            "due_date": fmt_dt(t["due_date"]), "status": t["status"],
            "completed_at": fmt_dt(t["completed_at"]),
            "created_at": fmt_dt(t["created_at"]), "updated_at": fmt_dt(t["updated_at"]),
            "version": t["version"]}
