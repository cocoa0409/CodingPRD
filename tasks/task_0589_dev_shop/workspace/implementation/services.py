"""Calculations, ledgers, cascades and serializers.

Every rule traces to a PRD sentence:
  - burn rounds ONCE on the aggregate            (PRD 2.8, 3.5)
  - invoice rounds PER LINE then sums            (PRD 2.8, 3.8)
  - posture boundaries are inclusive (>=)        (PRD 3.5)
  - CR quote order: labour -> tier(labour) -> discount -> overhead -> rush (PRD 3.6)
  - SLA clock chosen by severity; floor minutes; strict > breach (PRD 3.9)
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core import D, ZERO, clock, err, iso3, r2, r4, store, touch

# --- Constants (SCAFFOLD §1.3 / PRD §3) ------------------------------------
AT_RISK_THRESHOLD = Decimal("0.90")
OVERBURNED_THRESHOLD = Decimal("1.00")

TIER1_FLOOR = Decimal("5000.00")
TIER1_DISCOUNT = Decimal("0.05")
TIER2_FLOOR = Decimal("20000.00")
TIER2_DISCOUNT = Decimal("0.10")
PM_OVERHEAD_PCT = Decimal("0.12")
RUSH_PCT = Decimal("0.15")

TAX_RATE = Decimal("0.0825")

MAX_CR_REVISION_ROUNDS = 2
DAILY_HOURS_CAP = Decimal("12")
RETAINER_COOLDOWN_DAYS = 7

BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 17
SLA_RESPONSE_MINUTES = {"SEV1": 60, "SEV2": 240, "SEV3": 480}
SLA_RESOLUTION_MINUTES = {"SEV1": 480, "SEV2": 1440, "SEV3": 2880}
TIER_CREDIT_PCT = {"GOLD": Decimal("0.10"), "SILVER": Decimal("0.05"), "BRONZE": Decimal("0.02")}
CREDIT_CAP_PCT = Decimal("0.25")


# ===========================================================================
# Graph navigation
# ===========================================================================
def sprint_of_ticket(ticket):
    return store.sprints[ticket["sprint_id"]]


def engagement_of_ticket(ticket):
    return store.engagements[sprint_of_ticket(ticket)["engagement_id"]]


def engagement_of_time_entry(te):
    return engagement_of_ticket(store.tickets[te["ticket_id"]])


def sprints_of_engagement(eng_id):
    return [s for s in store.sprints.values() if s["engagement_id"] == eng_id]


def tickets_of_sprint(sprint_id):
    return [t for t in store.tickets.values() if t["sprint_id"] == sprint_id]


def time_entries_of_engagement(eng_id):
    out = []
    for te in store.time_entries.values():
        ticket = store.tickets.get(te["ticket_id"])
        if not ticket:
            continue
        sprint = store.sprints.get(ticket["sprint_id"])
        if sprint and sprint["engagement_id"] == eng_id:
            out.append(te)
    return out


# ===========================================================================
# Ticket / sprint rollups
# ===========================================================================
def recompute_ticket(ticket):
    """PRD 3.3 — actual_hours is the sum of hours over its APPROVED time
    entries (no billable filter here); variance_ratio = actual/estimated @4dp."""
    total = ZERO
    for te in store.time_entries.values():
        if te["ticket_id"] == ticket["id"] and te["status"] == "APPROVED":
            total += te["hours"]
    actual = r2(total)
    est = ticket["estimated_hours"]
    ratio = r4(actual / est) if est and est > 0 else Decimal("0.0000")
    if ticket["actual_hours"] != actual or ticket["variance_ratio"] != ratio:
        ticket["actual_hours"] = actual
        ticket["variance_ratio"] = ratio
        touch(ticket)


def recompute_committed_hours(sprint):
    """PRD 3.2 — sum of estimated_hours over tickets whose status is not CANCELLED."""
    total = ZERO
    for t in tickets_of_sprint(sprint["id"]):
        if t["status"] != "CANCELLED":
            total += t["estimated_hours"]
    total = r2(total)
    if sprint["committed_hours"] != total:
        sprint["committed_hours"] = total
        touch(sprint)


# ===========================================================================
# Engagement burn ledger (PRD 3.5) — approved-only variant is the persisted one
# ===========================================================================
def _burn(eng, statuses):
    hours = ZERO
    for te in time_entries_of_engagement(eng["id"]):
        if te["status"] in statuses and te["billable"]:
            hours += te["hours"]
    hours = r2(hours)
    rate = eng["standard_hourly_rate"]
    contract = eng["contract_value"]
    if rate is None:
        cost = Decimal("0.00")
    else:
        cost = r2(hours * rate)  # ONE rounding, on the aggregate
    if contract is None or contract == 0 or hours == 0:
        ratio = Decimal("0.0000")
    else:
        ratio = r4(cost / contract)
    return hours, cost, ratio


def approved_burn(eng):
    return _burn(eng, ("APPROVED",))


def committed_burn(eng):
    return _burn(eng, ("SUBMITTED", "APPROVED"))


def posture_for(ratio):
    """PRD 3.5 — both boundaries inclusive."""
    if ratio >= OVERBURNED_THRESHOLD:
        return "OVERBURNED"
    if ratio >= AT_RISK_THRESHOLD:
        return "AT_RISK"
    return "HEALTHY"


def apply_freeze_cascade(eng):
    """PRD 3.5 — a non-HEALTHY posture freezes every ACTIVE sprint; a HEALTHY
    posture thaws them. PLANNED and CLOSED sprints are never touched."""
    frozen = eng["budget_posture"] != "HEALTHY"
    for s in sprints_of_engagement(eng["id"]):
        if s["status"] != "ACTIVE":
            continue
        if s["spend_frozen"] != frozen:
            s["spend_frozen"] = frozen
            touch(s)


def recompute_burn_ledger(eng):
    """Burn -> posture -> freeze cascade. Does NOT bump engagement.version;
    callers bump it once where the PRD says so."""
    hours, cost, ratio = approved_burn(eng)
    eng["approved_hours"] = hours
    eng["burned_cost"] = cost
    eng["burn_ratio"] = ratio
    if eng["contract_value"] is None:
        eng["burn_ratio"] = Decimal("0.0000")
        eng["budget_posture"] = "HEALTHY"
    else:
        eng["budget_posture"] = posture_for(eng["burn_ratio"])
    apply_freeze_cascade(eng)


def recompute_scope_hours(eng):
    total = ZERO
    for cr in store.change_requests.values():
        if cr["engagement_id"] == eng["id"] and cr["status"] == "APPROVED":
            total += cr["delta_hours"]
    eng["scope_hours_added"] = r2(total)


# ===========================================================================
# Money ledger (PRD 2.9)
# ===========================================================================
def recompute_money_ledger(eng):
    total = ZERO
    for inv in store.invoices.values():
        if inv["engagement_id"] == eng["id"] and inv["status"] in ("ISSUED", "PAID"):
            total += inv["subtotal"]
    total = r2(total)
    eng["invoiced_amount"] = total
    contract = eng["contract_value"]
    if total == 0:
        eng["billing_status"] = "UNBILLED"
    elif contract is not None and total >= contract:
        eng["billing_status"] = "FULLY_BILLED"
    else:
        eng["billing_status"] = "PARTIALLY_BILLED"


# ===========================================================================
# Change request quote (PRD 3.6) — evaluation order is pinned
# ===========================================================================
def quote_change_request(cr, eng):
    labor_subtotal = r2(cr["delta_hours"] * eng["standard_hourly_rate"])
    if labor_subtotal >= TIER2_FLOOR:
        discount_pct = TIER2_DISCOUNT
    elif labor_subtotal >= TIER1_FLOOR:
        discount_pct = TIER1_DISCOUNT
    else:
        discount_pct = Decimal("0.00")
    discounted_labor = r2(labor_subtotal * (Decimal("1") - discount_pct))
    pm_overhead = r2(discounted_labor * PM_OVERHEAD_PCT)
    rush_fee = r2((discounted_labor + pm_overhead) * RUSH_PCT) if cr["rush"] else Decimal("0.00")
    return discounted_labor + pm_overhead + rush_fee  # no further rounding


# ===========================================================================
# Invoice lines (PRD 3.8) — round per line, then plain-sum
# ===========================================================================
def compute_invoice_lines(eng, kind, milestone=None, retainer=None,
                          period_start=None, period_end=None):
    lines = []
    if kind == "MILESTONE":
        lines.append({"label": milestone["title"], "amount": r2(milestone["amount"])})

    elif kind == "TIME_AND_MATERIALS":
        eligible = []
        for te in time_entries_of_engagement(eng["id"]):
            if te["status"] != "APPROVED" or not te["billable"]:
                continue
            if period_start <= te["work_date"] <= period_end:  # inclusive both ends
                eligible.append(te)
        by_ticket = {}
        for te in eligible:
            by_ticket.setdefault(te["ticket_id"], ZERO)
            by_ticket[te["ticket_id"]] += te["hours"]
        tickets = [store.tickets[tid] for tid in by_ticket]
        # ordered by Ticket.created_at ASC; the ticket id is NEVER used for ordering
        tickets.sort(key=lambda t: (t["created_at"], t["_seq"]))
        for t in tickets:
            amount = r2(by_ticket[t["id"]] * eng["standard_hourly_rate"])
            lines.append({"label": t["title"], "amount": amount})

    elif kind == "RETAINER":
        lines.append({"label": "Monthly retainer", "amount": r2(retainer["monthly_fee"])})
        credit = ZERO
        for inc in store.incidents.values():
            if inc["retainer_id"] != retainer["id"] or inc["status"] != "RESOLVED":
                continue
            resolved_date = inc["resolved_at"].date()
            if period_start <= resolved_date <= period_end:
                credit += inc["sla_credit_amount"]
        if credit > 0:
            lines.append({"label": "SLA credit", "amount": -r2(credit)})

    subtotal = ZERO
    for line in lines:
        subtotal += line["amount"]
    taxable = subtotal if subtotal > 0 else ZERO
    tax = r2(taxable * TAX_RATE)
    total = subtotal + tax
    return lines, subtotal, tax, total


def create_invoice_row(eng, kind, milestone=None, retainer=None,
                       period_start=None, period_end=None):
    from core import new_entity

    lines, subtotal, tax, total = compute_invoice_lines(
        eng, kind, milestone=milestone, retainer=retainer,
        period_start=period_start, period_end=period_end
    )
    inv = new_entity({
        "engagement_id": eng["id"],
        "milestone_id": milestone["id"] if milestone else None,
        "retainer_id": retainer["id"] if retainer else None,
        "kind": kind,
        "period_start": period_start,
        "period_end": period_end,
        "lines": lines,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "status": "DRAFT",
        "issued_at": None,
        "paid_at": None,
    })
    store.invoices[inv["id"]] = inv
    return inv


# ===========================================================================
# SLA clocks (PRD 3.9)
# ===========================================================================
def calendar_minutes(a, b):
    delta = (b - a).total_seconds()
    if delta <= 0:
        return 0
    return int(delta // 60)


def business_minutes(a, b):
    if b <= a:
        return 0
    total = 0
    day = a.date()
    last = b.date()
    while day <= last:
        if day.weekday() < 5:  # Mon-Fri
            win_start = datetime(day.year, day.month, day.day, BUSINESS_START_HOUR,
                                 tzinfo=timezone.utc)
            win_end = datetime(day.year, day.month, day.day, BUSINESS_END_HOUR,
                               tzinfo=timezone.utc)
            lo = max(a, win_start)
            hi = min(b, win_end)
            if hi > lo:
                total += int((hi - lo).total_seconds() // 60)
        day = day + timedelta(days=1)
    return total


def sla_minutes(severity, a, b):
    if severity == "SEV1":
        return calendar_minutes(a, b)
    return business_minutes(a, b)


def compute_sla_credit(incident, retainer):
    pct = Decimal("0.00")
    tier_pct = TIER_CREDIT_PCT[retainer["sla_tier"]]
    if incident["sla_response_breached"]:
        pct += tier_pct
    if incident["sla_resolution_breached"]:
        pct += tier_pct
    if pct > CREDIT_CAP_PCT:
        pct = CREDIT_CAP_PCT
    return r2(retainer["monthly_fee"] * pct)


# ===========================================================================
# Blocker graph (PRD 3.3)
# ===========================================================================
def would_create_cycle(ticket_id, blocker_id):
    if blocker_id == ticket_id:
        return True
    seen = set()
    cur = blocker_id
    while cur:
        if cur == ticket_id:
            return True
        if cur in seen:
            return True
        seen.add(cur)
        nxt = store.tickets.get(cur)
        cur = nxt["blocking_ticket_id"] if nxt else None
    return False


# ===========================================================================
# Serializers — field lists come straight from SCAFFOLD §1.1
# ===========================================================================
def ser_client(c):
    return {
        "id": c["id"], "name": c["name"], "billing_email": c["billing_email"],
        "country_code": c["country_code"], "created_at": c["created_at"],
        "updated_at": c["updated_at"], "version": c["version"],
    }


def ser_engagement(e):
    return {
        "id": e["id"], "client_id": e["client_id"], "title": e["title"],
        "source_channel": e["source_channel"], "status": e["status"],
        "billing_status": e["billing_status"], "billing_model": e["billing_model"],
        "contract_value": e["contract_value"], "budget_hours_cap": e["budget_hours_cap"],
        "standard_hourly_rate": e["standard_hourly_rate"],
        "start_date": e["start_date"], "end_date": e["end_date"],
        "signed_at": e["signed_at"], "approved_hours": e["approved_hours"],
        "burned_cost": e["burned_cost"], "burn_ratio": e["burn_ratio"],
        "budget_posture": e["budget_posture"], "invoiced_amount": e["invoiced_amount"],
        "scope_hours_added": e["scope_hours_added"],
        "created_at": e["created_at"], "updated_at": e["updated_at"], "version": e["version"],
    }


def ser_milestone(m):
    return {
        "id": m["id"], "engagement_id": m["engagement_id"], "sequence": m["sequence"],
        "title": m["title"], "amount": m["amount"], "due_date": m["due_date"],
        "status": m["status"], "accepted_at": m["accepted_at"],
        "created_at": m["created_at"], "updated_at": m["updated_at"], "version": m["version"],
    }


def ser_sprint(s):
    return {
        "id": s["id"], "engagement_id": s["engagement_id"], "milestone_id": s["milestone_id"],
        "name": s["name"], "start_date": s["start_date"], "end_date": s["end_date"],
        "status": s["status"], "spend_frozen": s["spend_frozen"],
        "committed_hours": s["committed_hours"],
        "created_at": s["created_at"], "updated_at": s["updated_at"], "version": s["version"],
    }


def ser_ticket(t):
    return {
        "id": t["id"], "sprint_id": t["sprint_id"],
        "blocking_ticket_id": t["blocking_ticket_id"], "title": t["title"],
        "estimated_hours": t["estimated_hours"], "assignee_user_id": t["assignee_user_id"],
        "status": t["status"], "actual_hours": t["actual_hours"],
        "variance_ratio": t["variance_ratio"], "rework_rounds": t["rework_rounds"],
        "created_at": t["created_at"], "updated_at": t["updated_at"], "version": t["version"],
    }


def ser_time_entry(te):
    return {
        "id": te["id"], "ticket_id": te["ticket_id"],
        "employee_user_id": te["employee_user_id"], "work_date": te["work_date"],
        "hours": te["hours"], "billable": te["billable"], "note": te["note"],
        "status": te["status"], "reviewed_by_user_id": te["reviewed_by_user_id"],
        "created_at": te["created_at"], "updated_at": te["updated_at"], "version": te["version"],
    }


def ser_change_request(cr):
    return {
        "id": cr["id"], "engagement_id": cr["engagement_id"], "title": cr["title"],
        "delta_hours": cr["delta_hours"], "rush": cr["rush"],
        "quoted_amount": cr["quoted_amount"], "status": cr["status"],
        "revision_rounds": cr["revision_rounds"],
        "created_at": cr["created_at"], "updated_at": cr["updated_at"], "version": cr["version"],
    }


def ser_release(r):
    return {
        "id": r["id"], "engagement_id": r["engagement_id"], "milestone_id": r["milestone_id"],
        "version_label": r["version_label"], "status": r["status"],
        "defect_count": r["defect_count"], "qa_rounds": r["qa_rounds"],
        "accepted_at": r["accepted_at"], "environment": r["environment"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_invoice(i):
    return {
        "id": i["id"], "engagement_id": i["engagement_id"], "milestone_id": i["milestone_id"],
        "retainer_id": i["retainer_id"], "kind": i["kind"],
        "period_start": i["period_start"], "period_end": i["period_end"],
        "lines": i["lines"], "subtotal": i["subtotal"], "tax": i["tax"], "total": i["total"],
        "status": i["status"], "issued_at": i["issued_at"], "paid_at": i["paid_at"],
        "created_at": i["created_at"], "updated_at": i["updated_at"], "version": i["version"],
    }


def ser_retainer(r):
    return {
        "id": r["id"], "client_id": r["client_id"], "engagement_id": r["engagement_id"],
        "start_date": r["start_date"], "end_date": r["end_date"],
        "monthly_fee": r["monthly_fee"], "included_hours": r["included_hours"],
        "sla_tier": r["sla_tier"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_incident(i):
    return {
        "id": i["id"], "retainer_id": i["retainer_id"], "severity": i["severity"],
        "summary": i["summary"], "status": i["status"], "opened_at": i["opened_at"],
        "responded_at": i["responded_at"], "resolved_at": i["resolved_at"],
        "response_minutes": i["response_minutes"], "resolution_minutes": i["resolution_minutes"],
        "sla_response_breached": i["sla_response_breached"],
        "sla_resolution_breached": i["sla_resolution_breached"],
        "sla_credit_amount": i["sla_credit_amount"],
        "created_at": i["created_at"], "updated_at": i["updated_at"], "version": i["version"],
    }
