"""Business logic: calculations, derived-field reconciliation, schedule gen."""
from decimal import Decimal, ROUND_HALF_UP

import clock
import db

# Categories that form the modified direct base for indirect calculation.
INDIRECT_BASE_CATEGORIES = {"PERSONNEL", "TRAVEL", "OTHER"}


# ---------------------------------------------------------------------------
# Round-half-up helpers
# ---------------------------------------------------------------------------
def round_half_up_int(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# FK / reachability helpers
# ---------------------------------------------------------------------------
def client_for_proposal(proposal):
    eng = db.engagements.get(proposal["engagement_id"])
    if not eng:
        return None
    return db.clients.get(eng["client_id"])


def client_for_submission(submission):
    prop = db.proposals.get(submission["proposal_id"])
    if not prop:
        return None
    return client_for_proposal(prop)


def opportunity_for_proposal(proposal):
    match = db.matches.get(proposal["match_id"])
    if not match:
        return None
    return db.opportunities.get(match["opportunity_id"])


def client_for_deliverable(deliverable):
    prop = db.proposals.get(deliverable["proposal_id"])
    if not prop:
        return None
    return client_for_proposal(prop)


def client_for_revision_request(rr):
    deliverable = db.deliverables.get(rr["deliverable_id"])
    if not deliverable:
        return None
    return client_for_deliverable(deliverable)


# ---------------------------------------------------------------------------
# match_score
# ---------------------------------------------------------------------------
def compute_match(client, opportunity):
    focus_overlap = set(client.get("mission_areas") or []) & set(opportunity.get("focus_areas") or [])
    eligible = (len(focus_overlap) >= 1) and \
        (client["annual_budget_cents"] >= opportunity["min_org_budget_cents"])
    if not eligible:
        return 0, False
    opp_focus = opportunity.get("focus_areas") or []
    focus_component = len(focus_overlap) / len(opp_focus) if opp_focus else 0.0
    budget_fit = min(1.0, client["annual_budget_cents"] / max(1, opportunity["ceiling_amount_cents"]))
    open_pursuits = sum(
        1 for m in db.matches.values()
        if m["client_id"] == client["id"] and m["status"] == "PURSUING"
    )
    if open_pursuits < 3:
        headroom = 1.0
    else:
        headroom = max(0.0, 1.0 - 0.25 * (open_pursuits - 2))
    raw = 50 * focus_component + 30 * budget_fit + 20 * headroom
    return round_half_up_int(raw), True


# ---------------------------------------------------------------------------
# budget_total
# ---------------------------------------------------------------------------
def recompute_budget_total(proposal):
    lines = [bl for bl in db.budget_lines.values() if bl["proposal_id"] == proposal["id"]]
    direct_base = sum(
        bl["amount_cents"] for bl in lines
        if bl["category"] in INDIRECT_BASE_CATEGORIES
    )
    indirect_lines = sorted(
        [bl for bl in lines if bl["category"] == "INDIRECT"],
        key=lambda bl: bl["_seq"],
    )
    for bl in indirect_lines:
        rate = Decimal(str(bl.get("indirect_rate_pct") or 0))
        computed = (Decimal(direct_base) * rate / Decimal(100))
        bl["amount_cents"] = int(computed.to_integral_value(rounding="ROUND_FLOOR"))
    total = sum(bl["amount_cents"] for bl in lines)
    proposal["budget_total_cents"] = total
    return total


# ---------------------------------------------------------------------------
# win_rate / client counters
# ---------------------------------------------------------------------------
def _client_submissions(client_id):
    out = []
    for sub in db.submissions.values():
        sc = client_for_submission(sub)
        if sc and sc["id"] == client_id:
            out.append(sub)
    return out


def recompute_client_counters(client):
    subs = _client_submissions(client["id"])
    submitted = sum(1 for s in subs if s["status"] in ("FILED", "ACCEPTED", "REJECTED"))
    won = sum(1 for s in subs if s["status"] == "ACCEPTED")
    decided = sum(1 for s in subs if s["status"] in ("ACCEPTED", "REJECTED"))
    client["proposals_submitted_count"] = submitted
    client["proposals_won_count"] = won
    if decided == 0:
        client["win_rate_pct"] = 0.0
    else:
        client["win_rate_pct"] = round_half_up_1dp(100.0 * won / decided)


# ---------------------------------------------------------------------------
# open_revision_count
# ---------------------------------------------------------------------------
def recompute_open_revision_count(deliverable):
    count = sum(
        1 for rr in db.revision_requests.values()
        if rr["deliverable_id"] == deliverable["id"] and rr["status"] == "OPEN"
    )
    deliverable["open_revision_count"] = count
    return count


# ---------------------------------------------------------------------------
# usage_count
# ---------------------------------------------------------------------------
def recompute_usage_count(snippet):
    count = sum(
        1 for d in db.deliverables.values()
        if d.get("_imported_snippet_id") == snippet["id"]
    )
    snippet["usage_count"] = count
    return count


# ---------------------------------------------------------------------------
# ytd_billed_cents
# ---------------------------------------------------------------------------
def recompute_ytd_billed(engagement):
    year = clock.get_now().year
    total = 0
    for inv in db.invoices.values():
        if inv["engagement_id"] != engagement["id"]:
            continue
        if inv["status"] != "ISSUED":
            continue
        try:
            inv_year = clock.parse_iso(inv["created_at"]).year
        except Exception:
            inv_year = year
        if inv_year == year:
            total += inv["total_cents"]
    engagement["ytd_billed_cents"] = total
    return total


# ---------------------------------------------------------------------------
# compliance_posture
# ---------------------------------------------------------------------------
def recompute_compliance_status(award):
    late = sum(
        1 for r in db.compliance_reports.values()
        if r["award_id"] == award["id"] and r["status"] == "LATE"
    )
    if late == 0:
        status = "GREEN"
    elif late == 1:
        status = "AT_RISK"
    else:
        status = "DELINQUENT"
    award["compliance_status"] = status
    return status


# ---------------------------------------------------------------------------
# report_schedule
# ---------------------------------------------------------------------------
def add_months(dt, months):
    month_index = dt.year * 12 + (dt.month - 1) + months
    year = month_index // 12
    month = month_index % 12 + 1
    day = dt.day
    # clamp day to month length
    import calendar
    last = calendar.monthrange(year, month)[1]
    if day > last:
        day = last
    return dt.replace(year=year, month=month, day=day)


def generate_report_schedule(award):
    pop = award["period_of_performance_months"]
    cadence = award["report_cadence_months"]
    if cadence <= 0:
        return
    n = pop // cadence
    created = clock.parse_iso(award["created_at"])
    window_start = created
    for k in range(1, n + 1):
        due = add_months(created, k * cadence)
        rec = {
            "award_id": award["id"],
            "due_utc": clock.iso(due),
            "covers_window_start_utc": clock.iso(window_start),
            "report_type": "SCHEDULED",
            "sequence_index": k,
            "submitted_at_utc": None,
            "status": "PENDING",
        }
        db.init_common(rec)
        db.compliance_reports[rec["id"]] = rec
        window_start = due


# ---------------------------------------------------------------------------
# YYYYMM month-index helpers (billing interval overlap, closed interval)
# ---------------------------------------------------------------------------
def yyyymm_index(s):
    """Convert 'YYYYMM' to an integer month index."""
    year = int(s[:4])
    month = int(s[4:6])
    return year * 12 + (month - 1)


def closed_intervals_overlap(a1, b1, a2, b2):
    # [a1,b1] and [a2,b2] overlap iff a1 <= b2 and a2 <= b1
    return a1 <= b2 and a2 <= b1


def half_open_overlap(s1, e1, s2, e2):
    # (s1,e1] and (s2,e2] overlap iff s1 < e2 and s2 < e1
    return s1 < e2 and s2 < e1


# ---------------------------------------------------------------------------
# invoice_total
# ---------------------------------------------------------------------------
def floor_div_decimal(numer, denom):
    return int((Decimal(str(numer)) / Decimal(str(denom))).to_integral_value(rounding="ROUND_FLOOR"))
