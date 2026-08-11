"""Business logic: serializers, computed fields, cascades, calculations."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import touch

ACTIVE_ENG_STATUSES = ("SIGNED", "ACTIVE")
NONTERMINAL_ENG_STATUSES = ("DRAFT", "PROPOSED", "NEGOTIATING", "SIGNED", "ACTIVE")
LINE_MULT = {
    "PREP": Decimal("1.00"),
    "TESTIMONY": Decimal("1.25"),
    "TRAVEL_TIME": Decimal("0.50"),
}


def cents(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round2(dec):
    return float(dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------- computed experts
def active_engagement_count(expert_id):
    return sum(
        1
        for e in db.engagements.values()
        if e["expert_id"] == expert_id and e["status"] in ACTIVE_ENG_STATUSES
    )


def evaluation_count(expert_id):
    return sum(1 for ev in db.evaluations if ev["expert_id"] == expert_id)


def compute_ratings(expert_id):
    evals = [ev for ev in db.evaluations if ev["expert_id"] == expert_id]
    if not evals:
        return 0.0, 0.0
    scores = [Decimal(str(ev["overall_score"])) for ev in evals]
    simple = sum(scores) / Decimal(len(scores))
    now = db.clock.now()
    wsum = Decimal(0)
    weighted = Decimal(0)
    for ev in evals:
        age_seconds = (now - db.parse_iso(ev["evaluated_at"])).total_seconds()
        age_days = int(age_seconds // 86400)  # whole days, floor
        periods = age_days // 180  # floor
        w = Decimal("0.5") ** periods
        wsum += w
        weighted += w * Decimal(str(ev["overall_score"]))
    decayed = weighted / wsum
    return round2(simple), round2(decayed)


def refresh_expert_ratings(expert):
    simple, decayed = compute_ratings(expert["id"])
    if simple != expert["rating_simple"] or decayed != expert["rating_decayed"]:
        expert["rating_simple"] = simple
        expert["rating_decayed"] = decayed
        touch(expert)
    return simple, decayed


def fire_probation_cascade(expert):
    """Every PENDING conflict check for the expert -> FLAGGED (ROSTER_PROBATION);
    affected SCREENING requests whose checks thereby all landed FLAGGED and in
    which no candidate satisfies the READY predicate revert to OPEN."""
    affected_req_ids = set()
    for cc in db.conflict_checks.values():
        if cc["expert_id"] == expert["id"] and cc["status"] == "PENDING":
            cc["status"] = "FLAGGED"
            cc["resolution_rationale"] = "ROSTER_PROBATION"
            touch(cc)
            affected_req_ids.add(cc["engagement_request_id"])
    for rid in affected_req_ids:
        req = db.engagement_requests.get(rid)
        if not req or req["status"] != "SCREENING":
            continue
        checks = [
            c for c in db.conflict_checks.values() if c["engagement_request_id"] == rid
        ]
        if (
            checks
            and all(c["status"] == "FLAGGED" for c in checks)
            and not has_qualified_candidate(rid)
        ):
            req["status"] = "OPEN"
            touch(req)


def has_qualified_candidate(request_id):
    checks = {}
    for c in db.conflict_checks.values():
        if c["engagement_request_id"] == request_id:
            checks[c["expert_id"]] = c["status"]
    reviews = {}
    for r in db.credential_reviews.values():
        if r["engagement_request_id"] == request_id:
            reviews[r["expert_id"]] = r["status"]
    for eid, cst in checks.items():
        if cst in ("CLEARED", "WAIVED") and reviews.get(eid) in (
            "PASSED",
            "PASSED_WITH_CONDITIONS",
        ):
            return True
    return False


def maybe_promote_request(request_id):
    req = db.engagement_requests.get(request_id)
    if req and req["status"] == "SCREENING" and has_qualified_candidate(request_id):
        req["status"] = "READY"
        touch(req)


# ------------------------------------------------------------- case aggregates
def schedule_estimate_cents(sched, eng):
    val = (
        Decimal(str(sched["estimated_hours"]))
        * Decimal(eng["hourly_rate_cents"])
        * Decimal("1.25")
    )
    return cents(val)


def compute_case_figures(case_id):
    engs = [e for e in db.engagements.values() if e["case_id"] == case_id]
    eng_by_id = {e["id"]: e for e in engs}
    invs = [i for i in db.invoices.values() if i["engagement_id"] in eng_by_id]
    actuals = sum(i["computed_total_cents"] for i in invs if i["status"] == "PAID")
    approved = sum(i["computed_total_cents"] for i in invs if i["status"] == "APPROVED")
    pending = sum(
        i["computed_total_cents"] for i in invs if i["status"] in ("SUBMITTED", "DISPUTED")
    )
    retainer = sum(
        e["retainer_funded_cents"]
        - e["retainer_drawn_cents"]
        - e["retainer_refunded_cents"]
        for e in engs
        if e["status"] == "ACTIVE"
    )
    sched = sum(
        schedule_estimate_cents(s, eng_by_id[s["engagement_id"]])
        for s in db.schedules.values()
        if s["engagement_id"] in eng_by_id and s["status"] == "CONFIRMED"
    )
    committed = actuals + approved + pending + retainer + sched
    return actuals, approved, committed


def recompute_case(case_id):
    """Recompute the case's three spend figures; a changed recomputation is a
    mutation of the case (updated_at refresh + version increment)."""
    case = db.cases.get(case_id)
    if not case:
        return
    a, ap, c = compute_case_figures(case_id)
    if (a, ap, c) != (
        case["actuals_paid_cents"],
        case["approved_outstanding_cents"],
        case["committed_cents"],
    ):
        case["actuals_paid_cents"] = a
        case["approved_outstanding_cents"] = ap
        case["committed_cents"] = c
        touch(case)


# ------------------------------------------------------------- invoice math
def compute_invoice(engagement, line_items, travel_expense_cents):
    """Per-line round-half-up THEN sum (pinned order), plus capped expense.
    Returns (computed_total_cents, expense_allow_cents)."""
    service = 0
    rate = Decimal(engagement["hourly_rate_cents"])
    for li in line_items:
        raw = Decimal(str(li["hours"])) * rate * LINE_MULT[li["kind"]]
        service += cents(raw)
    room = max(
        0,
        engagement["expense_cap_cents"] - engagement["expenses_approved_cents"],
    )
    allow = min(travel_expense_cents, room)
    return service + allow, allow


# ------------------------------------------------------------- overlap checks
def expert_conflict(expert_id, start_dt, end_dt, exclude_id=None):
    """Half-open [start, end) overlap over PROPOSED/CONFIRMED sessions of the
    same expert. Adjacency is allowed."""
    for e in db.engagements.values():
        if e["expert_id"] != expert_id:
            continue
        for s in db.schedules.values():
            if s["engagement_id"] != e["id"]:
                continue
            if s["status"] not in ("PROPOSED", "CONFIRMED"):
                continue
            if exclude_id and s["id"] == exclude_id:
                continue
            es = db.parse_iso(s["start_at"])
            ee = db.parse_iso(s["end_at"])
            if es < end_dt and start_dt < ee:
                return True
    return False


def venue_conflict(venue_id, start_dt, end_dt, exclude_id=None):
    """Closed-interval overlap with a 30-minute turnover buffer on both ends;
    touching buffered windows conflict."""
    buf = timedelta(minutes=30)
    ns, ne = start_dt - buf, end_dt + buf
    for s in db.schedules.values():
        if s.get("venue_id") != venue_id:
            continue
        if s["status"] not in ("PROPOSED", "CONFIRMED"):
            continue
        if exclude_id and s["id"] == exclude_id:
            continue
        es = db.parse_iso(s["start_at"]) - buf
        ee = db.parse_iso(s["end_at"]) + buf
        if es <= ne and ns <= ee:
            return True
    return False


# ------------------------------------------------------------- termination
def terminate_engagement(eng):
    """Execute the SIGNED/ACTIVE -> TERMINATED cascade per the state machine."""
    case_id = eng["case_id"]
    if eng["status"] == "ACTIVE":
        for s in db.schedules.values():
            if s["engagement_id"] == eng["id"] and s["status"] in (
                "PROPOSED",
                "CONFIRMED",
            ):
                s["status"] = "CANCELLED"  # no cancellation fee on this path
                touch(s)
        for r in db.reports.values():
            if r["engagement_id"] == eng["id"] and r["status"] in (
                "DRAFT",
                "IN_REVIEW",
                "REVISION_REQUESTED",
                "FINALIZED",
                "DISCLOSED",
            ):
                r["status"] = "WITHDRAWN"
                touch(r)
        # withdrawing the case's only DISCLOSED report reverts TRIAL_PREP
        case = db.cases[case_id]
        if case["status"] == "TRIAL_PREP":
            eng_ids = {
                e["id"] for e in db.engagements.values() if e["case_id"] == case_id
            }
            still_disclosed = any(
                r["status"] == "DISCLOSED" and r["engagement_id"] in eng_ids
                for r in db.reports.values()
            )
            if not still_disclosed:
                case["status"] = "DISCOVERY"
                touch(case)
        for p in db.productions.values():
            if p["engagement_id"] == eng["id"] and p["status"] in (
                "REQUESTED",
                "DELIVERED",
            ):
                p["status"] = "RECALLED"
                touch(p)
        for i in db.invoices.values():
            if i["engagement_id"] == eng["id"] and i["status"] in (
                "SUBMITTED",
                "DISPUTED",
            ):
                i["status"] = "REJECTED"
                touch(i)
        eng["retainer_refunded_cents"] = (
            eng["retainer_funded_cents"]
            - eng["retainer_drawn_cents"]
            - eng["retainer_refunded_cents"]
        )
    else:  # SIGNED
        eng["retainer_refunded_cents"] = (
            eng["retainer_funded_cents"] - eng["retainer_drawn_cents"]
        )
    eng["status"] = "TERMINATED"
    touch(eng)
    recompute_case(case_id)


# ------------------------------------------------------------- serializers
def expert_view(e):
    return {
        "id": e["id"],
        "full_name": e["full_name"],
        "specialty_area": e["specialty_area"],
        "roster_status": e["roster_status"],
        "daubert_challenge_count": e["daubert_challenge_count"],
        "daubert_exclusion_count": e["daubert_exclusion_count"],
        "max_concurrent_engagements": e["max_concurrent_engagements"],
        "active_engagement_count": active_engagement_count(e["id"]),
        "evaluation_count": evaluation_count(e["id"]),
        "rating_simple": e["rating_simple"],
        "rating_decayed": e["rating_decayed"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def case_view(c):
    return {
        "id": c["id"],
        "case_number": c["case_number"],
        "court": c["court"],
        "title": c["title"],
        "budget_cents": c["budget_cents"],
        "trial_date": c["trial_date"],
        "report_deadline": c["report_deadline"],
        "status": c["status"],
        "actuals_paid_cents": c["actuals_paid_cents"],
        "committed_cents": c["committed_cents"],
        "approved_outstanding_cents": c["approved_outstanding_cents"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def request_view(r):
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "specialty_area": r["specialty_area"],
        "notes": r["notes"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def check_view(c):
    return {
        "id": c["id"],
        "engagement_request_id": c["engagement_request_id"],
        "expert_id": c["expert_id"],
        "adverse_parties": c["adverse_parties"],
        "status": c["status"],
        "resolution_rationale": c["resolution_rationale"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def review_view(r):
    return {
        "id": r["id"],
        "engagement_request_id": r["engagement_request_id"],
        "expert_id": r["expert_id"],
        "status": r["status"],
        "daubert_notes": r["daubert_notes"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def engagement_view(e):
    return {
        "id": e["id"],
        "engagement_request_id": e["engagement_request_id"],
        "case_id": e["case_id"],
        "expert_id": e["expert_id"],
        "status": e["status"],
        "hourly_rate_cents": e["hourly_rate_cents"],
        "retainer_cents": e["retainer_cents"],
        "expense_cap_cents": e["expense_cap_cents"],
        "negotiation_round_count": e["negotiation_round_count"],
        "nda_executed": e["nda_executed"],
        "retainer_funded_cents": e["retainer_funded_cents"],
        "retainer_drawn_cents": e["retainer_drawn_cents"],
        "retainer_refunded_cents": e["retainer_refunded_cents"],
        "retainer_remaining_cents": e["retainer_funded_cents"]
        - e["retainer_drawn_cents"]
        - e["retainer_refunded_cents"],
        "expenses_approved_cents": e["expenses_approved_cents"],
        "created_by_user_id": e["created_by_user_id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def production_view(p):
    return {
        "id": p["id"],
        "engagement_id": p["engagement_id"],
        "title": p["title"],
        "privilege_tier": p["privilege_tier"],
        "content_ref": p["content_ref"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def report_view(r):
    return {
        "id": r["id"],
        "engagement_id": r["engagement_id"],
        "title": r["title"],
        "report_type": r["report_type"],
        "deadline_at": r["deadline_at"],
        "status": r["status"],
        "revision_count": r["revision_count"],
        "submitted_at": r["submitted_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def venue_view(v):
    return {
        "id": v["id"],
        "name": v["name"],
        "location": v["location"],
        "capacity": v["capacity"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def schedule_view(s):
    return {
        "id": s["id"],
        "engagement_id": s["engagement_id"],
        "venue_id": s["venue_id"],
        "kind": s["kind"],
        "start_at": s["start_at"],
        "end_at": s["end_at"],
        "estimated_hours": s["estimated_hours"],
        "travel_required": s["travel_required"],
        "actual_hours": s["actual_hours"],
        "cancellation_fee_cents": s["cancellation_fee_cents"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def invoice_view(i):
    return {
        "id": i["id"],
        "engagement_id": i["engagement_id"],
        "period_start": i["period_start"],
        "period_end": i["period_end"],
        "line_items": i["line_items"],
        "travel_expense_cents": i["travel_expense_cents"],
        "total_cents": i["total_cents"],
        "computed_total_cents": i["computed_total_cents"],
        "status": i["status"],
        "dispute_count": i["dispute_count"],
        "retainer_draw_cents": i["retainer_draw_cents"],
        "billed_to_client_cents": i["billed_to_client_cents"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def evaluation_view(ev):
    # Terminal record: only id + created_at; no updated_at / version.
    return {
        "id": ev["id"],
        "engagement_id": ev["engagement_id"],
        "expert_id": ev["expert_id"],
        "overall_score": ev["overall_score"],
        "quality_score": ev["quality_score"],
        "timeliness_score": ev["timeliness_score"],
        "testimony_score": ev["testimony_score"],
        "comments": ev["comments"],
        "evaluated_at": ev["evaluated_at"],
        "created_at": ev["created_at"],
    }
