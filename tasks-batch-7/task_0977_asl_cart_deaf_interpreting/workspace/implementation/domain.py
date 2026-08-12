"""Business logic: serializers, derived fields, calculations, cascades, sweeps."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from core import DB, now, iso, err
import core


# --------------------------------------------------------------------------
# Shared enums / constants
# --------------------------------------------------------------------------
MODALITIES = {"ASL_ONSITE", "CART_ONSITE", "VRI"}
ADA_CONTEXTS = {"MEDICAL", "LEGAL", "EDUCATION", "GENERAL"}
CRED_LEVELS = {"SCREENED", "CERTIFIED", "SPECIALIST"}
LEVEL_RANK = {"SCREENED": 1, "CERTIFIED": 2, "SPECIALIST": 3}
CREDENTIALS = {"RID_NIC", "RID_CI_CT", "STATE_QA", "CART_CRR", "NAD_V", "LEGAL_SCL"}
COMPLAINT_CATEGORIES = {"QUALITY", "LATENESS", "PROFESSIONALISM", "BILLING", "ACCESS"}
SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}
PENALTY = {"MINOR": 5, "MAJOR": 15, "CRITICAL": 30}
CREDIT_PCT_DEFAULT = {"MINOR": Decimal("0.10"), "MAJOR": Decimal("0.25"),
                      "CRITICAL": Decimal("0.50")}
REQUIRED_CREDENTIAL = {"LEGAL": "SPECIALIST", "MEDICAL": "CERTIFIED",
                       "EDUCATION": "CERTIFIED", "GENERAL": "SCREENED"}

MILEAGE_CAP_MILES = 200
TRAVEL_TIME_CAP_MIN = 240
ESTIMATED_TRAVEL_MINUTES_ONSITE = 60
TRAVEL_BUFFER_MIN = 30
VRI_MAX_CONCURRENT_SESSIONS = 3
STRIKE_WINDOW_DAYS = 365
STRIKE_SUSPENSION_THRESHOLD = 3
QUALITY_OFFER_GATE = 40


# --------------------------------------------------------------------------
# Money helpers (integer cents, ROUND_HALF_UP, per-line rounding)
# --------------------------------------------------------------------------
def rhu(value):
    """Round half-up to integer cents. value: Decimal/int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_dec(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def touch(entity):
    """Universal mutation rule: refresh updated_at, bump version (PRD §2.5)."""
    entity["updated_at"] = now()
    entity["version"] += 1


# --------------------------------------------------------------------------
# Derived fields (recomputed on read)
# --------------------------------------------------------------------------
def org_outstanding_balance(org_id):
    total = 0
    for inv in DB.invoices.values():
        if (inv["org_id"] == org_id and inv["issue_status"] == "ISSUED"
                and inv["payment_status"] != "PAID"):
            total += inv["amount_due_cents"]
    return total


def interpreter_active_strikes(interpreter_id):
    window_start = now() - timedelta(days=STRIKE_WINDOW_DAYS)
    count = 0
    for s in DB.strikes.values():
        if (s["interpreter_id"] == interpreter_id and s["status"] == "ACTIVE"
                and s["occurred_at"] >= window_start):
            count += 1
    return count


def interpreter_quality(interpreter_id):
    """Returns (quality_score, quality_score_provisional)."""
    final_pen = 0
    provisional_pen = 0
    for c in DB.complaints.values():
        if c["interpreter_id"] != interpreter_id:
            continue
        if c["status"] == "SUBSTANTIATED":
            final_pen += c["penalty_points"]
            provisional_pen += c["penalty_points"]
        elif c["status"] in ("FILED", "UNDER_REVIEW"):
            provisional_pen += PENALTY[c["severity"]]
    return max(0, 100 - final_pen), max(0, 100 - provisional_pen)


# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------
def ser_org(o):
    return {
        "id": o["id"], "name": o["name"], "org_type": o["org_type"],
        "status": o["status"], "credit_limit_cents": o["credit_limit_cents"],
        "outstanding_balance_cents": org_outstanding_balance(o["id"]),
        "created_at": iso(o["created_at"]), "updated_at": iso(o["updated_at"]),
        "version": o["version"],
    }


def ser_rate_card(c):
    return {
        "id": c["id"], "modality": c["modality"], "ada_context": c["ada_context"],
        "credential_level": c["credential_level"],
        "hourly_rate_cents": c["hourly_rate_cents"],
        "minimum_billable_minutes": c["minimum_billable_minutes"],
        "travel_rate_cents_per_hour": c["travel_rate_cents_per_hour"],
        "mileage_rate_cents_per_mile": c["mileage_rate_cents_per_mile"],
        "vri_platform_fee_cents_per_min": c["vri_platform_fee_cents_per_min"],
        "cancel_full_refund_notice_hours": c["cancel_full_refund_notice_hours"],
        "cancel_partial_notice_hours": c["cancel_partial_notice_hours"],
        "late_cancel_fee_pct": c["late_cancel_fee_pct"],
        "effective_from": iso(c["effective_from"]),
        "status": c["status"],
        "created_at": iso(c["created_at"]), "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def ser_interpreter(i):
    strikes = interpreter_active_strikes(i["id"])
    q, qp = interpreter_quality(i["id"])
    return {
        "id": i["id"], "full_name": i["full_name"],
        "modalities_offered": list(i["modalities_offered"]),
        "home_zip": i["home_zip"],
        "vri_platform_certified": i["vri_platform_certified"],
        "status": i["status"],
        "active_strike_count": strikes,
        "quality_score": q,
        "quality_score_provisional": qp,
        "created_at": iso(i["created_at"]), "updated_at": iso(i["updated_at"]),
        "version": i["version"],
    }


def ser_certification(c):
    return {
        "id": c["id"], "interpreter_id": c["interpreter_id"],
        "credential": c["credential"], "level": c["level"],
        "issued_on": iso(c["issued_on"]), "expires_on": iso(c["expires_on"]),
        "verified": c["verified"],
        "created_at": iso(c["created_at"]), "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def ser_window(w):
    return {
        "id": w["id"], "interpreter_id": w["interpreter_id"],
        "start_at": iso(w["start_at"]), "end_at": iso(w["end_at"]),
        "modalities": list(w["modalities"]),
        "created_at": iso(w["created_at"]), "updated_at": iso(w["updated_at"]),
        "version": w["version"],
    }


def ser_request(r):
    return {
        "id": r["id"], "org_id": r["org_id"], "consumer_name": r["consumer_name"],
        "modality": r["modality"], "ada_context": r["ada_context"],
        "scheduled_start": iso(r["scheduled_start"]),
        "scheduled_end": iso(r["scheduled_end"]),
        "onsite_address": r["onsite_address"],
        "estimated_mileage": r["estimated_mileage"],
        "required_credential_level": r["required_credential_level"],
        "status": r["status"],
        "offer_attempt_count": r["offer_attempt_count"],
        "cancellation_fee_cents": r["cancellation_fee_cents"],
        "cancelled_at": iso(r["cancelled_at"]),
        "closed_at": iso(r["closed_at"]),
        "created_at": iso(r["created_at"]), "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"], "request_id": a["request_id"],
        "interpreter_id": a["interpreter_id"],
        "rate_card_id": a["rate_card_id"],
        "rate_card_version": a["rate_card_version"],
        "status": a["status"],
        "offered_at": iso(a["offered_at"]),
        "response_deadline": iso(a["response_deadline"]),
        "accepted_at": iso(a["accepted_at"]),
        "pinned_hourly_rate_cents": a["pinned_hourly_rate_cents"],
        "pinned_minimum_billable_minutes": a["pinned_minimum_billable_minutes"],
        "pinned_travel_rate_cents_per_hour": a["pinned_travel_rate_cents_per_hour"],
        "pinned_mileage_rate_cents_per_mile": a["pinned_mileage_rate_cents_per_mile"],
        "pinned_vri_platform_fee_cents_per_min": a["pinned_vri_platform_fee_cents_per_min"],
        "pinned_cancel_full_refund_notice_hours": a["pinned_cancel_full_refund_notice_hours"],
        "pinned_cancel_partial_notice_hours": a["pinned_cancel_partial_notice_hours"],
        "pinned_late_cancel_fee_pct": a["pinned_late_cancel_fee_pct"],
        "estimated_cost_cents": a["estimated_cost_cents"],
        "cancelled_by": a["cancelled_by"],
        "cancel_notice_hours": a["cancel_notice_hours"],
        "cancellation_fee_cents": a["cancellation_fee_cents"],
        "no_show_marked_at": iso(a["no_show_marked_at"]),
        "travel_minutes_claimed": a["travel_minutes_claimed"],
        "mileage_claimed": a["mileage_claimed"],
        "created_at": iso(a["created_at"]), "updated_at": iso(a["updated_at"]),
        "version": a["version"],
    }


def ser_encounter(e):
    return {
        "id": e["id"], "assignment_id": e["assignment_id"],
        "modality_delivered": e["modality_delivered"],
        "actual_start": iso(e["actual_start"]),
        "actual_end": iso(e["actual_end"]),
        "actual_minutes": e["actual_minutes"],
        "billable_minutes": e["billable_minutes"],
        "verified": e["verified"],
        "verify_deadline": iso(e["verify_deadline"]),
        "verified_by": e["verified_by"],
        "corrected_start": iso(e["corrected_start"]),
        "corrected_end": iso(e["corrected_end"]),
        "created_at": iso(e["created_at"]), "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


def ser_invoice(inv):
    return {
        "id": inv["id"], "org_id": inv["org_id"],
        "assignment_id": inv["assignment_id"],
        "encounter_id": inv["encounter_id"],
        "issue_status": inv["issue_status"],
        "dispute_status": inv["dispute_status"],
        "payment_status": inv["payment_status"],
        "line_items": [dict(li) for li in inv["line_items"]],
        "subtotal_cents": inv["subtotal_cents"],
        "credits_applied_cents": inv["credits_applied_cents"],
        "payments_applied_cents": inv["payments_applied_cents"],
        "amount_due_cents": inv["amount_due_cents"],
        "issued_at": iso(inv["issued_at"]),
        "dispute_reason": inv["dispute_reason"],
        "created_at": iso(inv["created_at"]), "updated_at": iso(inv["updated_at"]),
        "version": inv["version"],
    }


def ser_complaint(c):
    return {
        "id": c["id"], "org_id": c["org_id"], "assignment_id": c["assignment_id"],
        "interpreter_id": c["interpreter_id"], "category": c["category"],
        "severity": c["severity"], "narrative": c["narrative"],
        "status": c["status"], "penalty_points": c["penalty_points"],
        "credit_pct": c["credit_pct"],
        "credit_amount_cents": c["credit_amount_cents"],
        "reopen_count": c["reopen_count"],
        "created_at": iso(c["created_at"]), "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def ser_credit_memo(m):
    return {
        "id": m["id"], "org_id": m["org_id"], "complaint_id": m["complaint_id"],
        "amount_cents": m["amount_cents"], "remaining_cents": m["remaining_cents"],
        "status": m["status"],
        "applications": [{"invoice_id": ap["invoice_id"],
                          "amount_cents": ap["amount_cents"]}
                         for ap in m["applications"]],
        "created_at": iso(m["created_at"]), "updated_at": iso(m["updated_at"]),
        "version": m["version"],
    }


def ser_strike(s):
    # StrikeRecord deliberately carries only id + created_at (no updated_at/version)
    return {
        "id": s["id"], "interpreter_id": s["interpreter_id"],
        "assignment_id": s["assignment_id"],
        "occurred_at": iso(s["occurred_at"]),
        "status": s["status"],
        "rescinded_at": iso(s["rescinded_at"]),
        "created_at": iso(s["created_at"]),
    }


def ser_report(r):
    return {
        "id": r["id"], "org_id": r["org_id"],
        "window_start": iso(r["window_start"]), "window_end": iso(r["window_end"]),
        "generated_at": iso(r["generated_at"]),
        "total_requests": r["total_requests"],
        "filled_count": r["filled_count"],
        "unfilled_count": r["unfilled_count"],
        "cancelled_count": r["cancelled_count"],
        "fulfillment_rate": r["fulfillment_rate"],
        "no_show_count": r["no_show_count"],
        "avg_response_minutes": r["avg_response_minutes"],
        "total_billed_cents": r["total_billed_cents"],
        "complaint_count": r["complaint_count"],
        "substantiated_count": r["substantiated_count"],
        "ada_context_mix": dict(r["ada_context_mix"]),
        "created_at": iso(r["created_at"]), "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


# --------------------------------------------------------------------------
# Fetch helpers with not-found errors
# --------------------------------------------------------------------------
def get_org(org_id):
    o = DB.orgs.get(org_id)
    if o is None:
        err(core.E_ORG_NF, 404, f"Organization {org_id} not found")
    return o


def get_rate_card(card_id):
    c = DB.rate_cards.get(card_id)
    if c is None:
        err(core.E_CARD_NF, 404, f"Rate card {card_id} not found")
    return c


def get_interpreter(iid):
    i = DB.interpreters.get(iid)
    if i is None:
        err(core.E_INTERP_NF, 404, f"Interpreter {iid} not found")
    return i


def get_request(rid):
    r = DB.requests.get(rid)
    if r is None:
        err(core.E_REQUEST_NF, 404, f"Request {rid} not found")
    return r


def get_assignment(aid):
    a = DB.assignments.get(aid)
    if a is None:
        err(core.E_ASSIGN_NF, 404, f"Assignment {aid} not found")
    return a


def get_encounter(eid):
    e = DB.encounters.get(eid)
    if e is None:
        err(core.E_ENCOUNTER_NF, 404, f"Encounter {eid} not found")
    return e


def get_invoice(iid):
    inv = DB.invoices.get(iid)
    if inv is None:
        err(core.E_INVOICE_NF, 404, f"Invoice {iid} not found")
    return inv


def get_complaint(cid):
    c = DB.complaints.get(cid)
    if c is None:
        err(core.E_COMPLAINT_NF, 404, f"Complaint {cid} not found")
    return c


def get_memo(mid):
    m = DB.credit_memos.get(mid)
    if m is None:
        err(core.E_MEMO_NF, 404, f"Credit memo {mid} not found")
    return m


def get_strike(sid):
    s = DB.strikes.get(sid)
    if s is None:
        err(core.E_STRIKE_NF, 404, f"Strike {sid} not found")
    return s


def get_report(rid):
    r = DB.reports.get(rid)
    if r is None:
        err(core.E_REPORT_NF, 404, f"Report {rid} not found")
    return r


# --------------------------------------------------------------------------
# Request helpers
# --------------------------------------------------------------------------
def outstanding_offer(req):
    """The request's currently OFFERED assignment, if any."""
    for a in DB.assignments.values():
        if a["request_id"] == req["id"] and a["status"] == "OFFERED":
            return a
    return None


def active_assignment(req):
    """The request's live assignment (ACCEPTED/CONFIRMED/EN_ROUTE/ON_SITE)."""
    for a in DB.assignments.values():
        if (a["request_id"] == req["id"]
                and a["status"] in ("ACCEPTED", "CONFIRMED", "EN_ROUTE", "ON_SITE")):
            return a
    return None


def encounter_of_assignment(aid):
    for e in DB.encounters.values():
        if e["assignment_id"] == aid:
            return e
    return None


def invoice_of_assignment(aid):
    for inv in DB.invoices.values():
        if inv["assignment_id"] == aid:
            return inv
    return None


def request_rematch_or_unfilled(req):
    """CONFIRMED/OFFERED -> MATCHING while attempts remain, else UNFILLED."""
    req["status"] = "MATCHING" if req["offer_attempt_count"] < 3 else "UNFILLED"
    touch(req)


# --------------------------------------------------------------------------
# Calculations
# --------------------------------------------------------------------------
def compute_estimated_cost(req, card):
    """Provisional estimate at offer creation (calculations.estimated_cost)."""
    sched_seconds = (req["scheduled_end"] - req["scheduled_start"]).total_seconds()
    sched_minutes = math.ceil(sched_seconds / 60)
    est_billable = max(sched_minutes, card["minimum_billable_minutes"])
    labor = rhu(Decimal(est_billable * card["hourly_rate_cents"]) / Decimal(60))
    if req["modality"] == "VRI":
        travel = 0
        mileage = 0
        platform = sched_minutes * card["vri_platform_fee_cents_per_min"]
    else:
        travel = rhu(Decimal(ESTIMATED_TRAVEL_MINUTES_ONSITE
                             * card["travel_rate_cents_per_hour"]) / Decimal(60))
        miles = min(Decimal(str(req["estimated_mileage"])), Decimal(MILEAGE_CAP_MILES))
        mileage = rhu(miles * Decimal(card["mileage_rate_cents_per_mile"]))
        platform = 0
    return labor + travel + mileage + platform


def select_rate_card(req):
    """Latest effective_from wins; ties break to earliest created_at (id unused)."""
    eligible = []
    for c in DB.rate_cards.values():
        if (c["status"] == "ACTIVE"
                and c["modality"] == req["modality"]
                and c["ada_context"] == req["ada_context"]
                and c["credential_level"] == req["required_credential_level"]
                and c["effective_from"] <= now()):
            eligible.append(c)
    if not eligible:
        err(core.E_CARD_NF, 404,
            "No ACTIVE rate card matches this request's modality, context, and level")
    eligible.sort(key=lambda c: (-c["effective_from"].timestamp(),
                                 c["created_at"], c["_seq"]))
    return eligible[0]


def availability_covers(interpreter_id, req):
    """Merged half-open modality windows must cover [start, end)."""
    intervals = []
    for w in DB.availability_windows.values():
        if (w["interpreter_id"] == interpreter_id
                and req["modality"] in w["modalities"]):
            intervals.append((w["start_at"], w["end_at"]))
    intervals.sort()
    cur = req["scheduled_start"]
    for s, e in intervals:
        if s <= cur and e > cur:
            cur = e
        if cur >= req["scheduled_end"]:
            return True
    return cur >= req["scheduled_end"]


def compute_cancellation_fee(assignment, req):
    """Tiered fee from pinned windows. Returns (fee_cents, notice_hours)."""
    notice_seconds = (req["scheduled_start"] - now()).total_seconds()
    min_charge = rhu(Decimal(assignment["pinned_minimum_billable_minutes"]
                             * assignment["pinned_hourly_rate_cents"]) / Decimal(60))
    if notice_seconds >= assignment["pinned_cancel_full_refund_notice_hours"] * 3600:
        fee = 0
    elif notice_seconds >= assignment["pinned_cancel_partial_notice_hours"] * 3600:
        fee = rhu(Decimal(str(assignment["pinned_late_cancel_fee_pct"]))
                  * Decimal(min_charge))
    else:
        fee = min_charge
    return fee, notice_seconds / 3600.0


def build_invoice_line_items(assignment, req, encounter):
    """final_invoice_billing: round per line, then sum. Zero lines omitted
    (LABOR always present)."""
    lines = []
    billable = encounter["billable_minutes"]
    labor_amt = rhu(Decimal(billable * assignment["pinned_hourly_rate_cents"])
                    / Decimal(60))
    lines.append({"kind": "LABOR", "quantity": billable,
                  "unit_rate_cents": assignment["pinned_hourly_rate_cents"],
                  "amount_cents": labor_amt})
    if req["modality"] != "VRI":
        tmin = min(assignment["travel_minutes_claimed"], TRAVEL_TIME_CAP_MIN)
        tamt = rhu(Decimal(tmin * assignment["pinned_travel_rate_cents_per_hour"])
                   / Decimal(60))
        if tamt > 0:
            lines.append({"kind": "TRAVEL_TIME", "quantity": tmin,
                          "unit_rate_cents": assignment["pinned_travel_rate_cents_per_hour"],
                          "amount_cents": tamt})
        miles = min(Decimal(str(assignment["mileage_claimed"])),
                    Decimal(MILEAGE_CAP_MILES))
        mamt = rhu(miles * Decimal(assignment["pinned_mileage_rate_cents_per_mile"]))
        if mamt > 0:
            miles_out = assignment["mileage_claimed"]
            if miles_out > MILEAGE_CAP_MILES:
                miles_out = MILEAGE_CAP_MILES
            lines.append({"kind": "MILEAGE", "quantity": miles_out,
                          "unit_rate_cents": assignment["pinned_mileage_rate_cents_per_mile"],
                          "amount_cents": mamt})
    else:
        pamt = encounter["actual_minutes"] * assignment["pinned_vri_platform_fee_cents_per_min"]
        if pamt > 0:
            lines.append({"kind": "PLATFORM_FEE",
                          "quantity": encounter["actual_minutes"],
                          "unit_rate_cents": assignment["pinned_vri_platform_fee_cents_per_min"],
                          "amount_cents": pamt})
    return lines


def fiscal_gate(org, estimated_cost_cents):
    if org_outstanding_balance(org["id"]) + estimated_cost_cents > org["credit_limit_cents"]:
        err(core.E_CREDIT_LIMIT, 402,
            "Outstanding balance plus estimated cost exceeds the org credit limit")


# --------------------------------------------------------------------------
# Invoice settlement / credit waterfall
# --------------------------------------------------------------------------
def recompute_invoice(inv):
    """Recompute amount_due and payment_status; bubble request to CLOSED on PAID."""
    inv["amount_due_cents"] = max(
        0, inv["subtotal_cents"] - inv["credits_applied_cents"]
        - inv["payments_applied_cents"])
    if inv["amount_due_cents"] == 0:
        new_ps = "PAID"
    elif inv["credits_applied_cents"] + inv["payments_applied_cents"] > 0:
        new_ps = "PARTIALLY_PAID"
    else:
        new_ps = "UNPAID"
    became_paid = new_ps == "PAID" and inv["payment_status"] != "PAID"
    inv["payment_status"] = new_ps
    touch(inv)
    if became_paid and inv["issue_status"] == "ISSUED" and inv["encounter_id"] is not None:
        a = DB.assignments.get(inv["assignment_id"])
        if a is not None:
            req = DB.requests.get(a["request_id"])
            if req is not None and req["status"] == "COMPLETED":
                req["status"] = "CLOSED"
                req["closed_at"] = now()
                touch(req)


def run_credit_waterfall(memo):
    """Apply memo to org's ISSUED unpaid invoices, oldest issued_at first."""
    eligible = [inv for inv in DB.invoices.values()
                if inv["org_id"] == memo["org_id"]
                and inv["issue_status"] == "ISSUED"
                and inv["payment_status"] != "PAID"]
    eligible.sort(key=lambda inv: (inv["issued_at"], inv["created_at"], inv["_seq"]))
    remaining = memo["amount_cents"]
    for inv in eligible:
        if remaining <= 0:
            break
        applied = min(remaining, inv["amount_due_cents"])
        if applied <= 0:
            continue
        inv["credits_applied_cents"] += applied
        memo["applications"].append({"invoice_id": inv["id"],
                                     "amount_cents": applied, "reversed": False})
        recompute_invoice(inv)
        remaining -= applied
    memo["remaining_cents"] = remaining
    memo["status"] = "EXHAUSTED" if remaining == 0 else "OPEN"


def create_credit_memo(org, amount_cents, complaint_id=None):
    memo = {
        "id": core.new_id(), "org_id": org["id"], "complaint_id": complaint_id,
        "amount_cents": amount_cents, "remaining_cents": amount_cents,
        "status": "OPEN", "applications": [],
        "created_at": now(), "updated_at": now(), "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.credit_memos[memo["id"]] = memo
    run_credit_waterfall(memo)
    touch(org)
    return memo


def create_fee_only_invoice(req, assignment, fee_cents):
    line = {"kind": "CANCELLATION_FEE", "quantity": 1,
            "unit_rate_cents": fee_cents, "amount_cents": fee_cents}
    inv = {
        "id": core.new_id(), "org_id": req["org_id"],
        "assignment_id": assignment["id"], "encounter_id": None,
        "issue_status": "DRAFT", "dispute_status": "NONE",
        "payment_status": "UNPAID", "line_items": [line],
        "subtotal_cents": fee_cents, "credits_applied_cents": 0,
        "payments_applied_cents": 0, "amount_due_cents": fee_cents,
        "issued_at": None, "dispute_reason": None,
        "created_at": now(), "updated_at": now(), "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.invoices[inv["id"]] = inv
    return inv


# --------------------------------------------------------------------------
# Cascades
# --------------------------------------------------------------------------
def cancel_assignment_system(assignment, from_states_with_zero_fee=("ACCEPTED", "CONFIRMED")):
    """SYSTEM cancel (supersede / suspension): no fee ever charged."""
    prev = assignment["status"]
    assignment["status"] = "CANCELLED"
    assignment["cancelled_by"] = "SYSTEM"
    if prev in from_states_with_zero_fee:
        assignment["cancellation_fee_cents"] = 0
    touch(assignment)


def suspend_interpreter(interp):
    """ACTIVE -> SUSPENDED plus the non-terminal assignment cascade."""
    interp["status"] = "SUSPENDED"
    touch(interp)
    owned = [a for a in DB.assignments.values()
             if a["interpreter_id"] == interp["id"]
             and a["status"] in ("OFFERED", "ACCEPTED", "CONFIRMED")]
    owned.sort(key=lambda a: a["_seq"])
    for a in owned:
        cancel_assignment_system(a)
        req = DB.requests.get(a["request_id"])
        if req is not None and req["status"] in ("OFFERED", "CONFIRMED"):
            request_rematch_or_unfilled(req)


def record_strike(interpreter_id, occurred_at, assignment_id=None):
    """Create strike, recompute rolling count, auto-suspend at >= 3."""
    strike = {
        "id": core.new_id(), "interpreter_id": interpreter_id,
        "assignment_id": assignment_id, "occurred_at": occurred_at,
        "status": "ACTIVE", "rescinded_at": None,
        "created_at": now(), "_seq": DB.next_seq(),
    }
    DB.strikes[strike["id"]] = strike
    interp = DB.interpreters.get(interpreter_id)
    if interp is not None and interp["status"] == "ACTIVE":
        if interpreter_active_strikes(interpreter_id) >= STRIKE_SUSPENSION_THRESHOLD:
            suspend_interpreter(interp)
    return strike


def cancel_request_tree(req, cancelled_by):
    """Cancel a request end-to-end; shared by /requests/{id}/cancel and the
    REQUESTER branch of /assignments/{id}/cancel."""
    fee = 0
    assignment = None
    if req["status"] == "OFFERED":
        assignment = outstanding_offer(req)
        if assignment is not None:
            assignment["status"] = "CANCELLED"
            assignment["cancelled_by"] = cancelled_by
            touch(assignment)
    elif req["status"] == "CONFIRMED":
        assignment = active_assignment(req)
        if assignment is not None and assignment["status"] in ("CONFIRMED", "EN_ROUTE"):
            fee, notice_hours = compute_cancellation_fee(assignment, req)
            assignment["status"] = "CANCELLED"
            assignment["cancelled_by"] = cancelled_by
            assignment["cancel_notice_hours"] = notice_hours
            assignment["cancellation_fee_cents"] = fee
            touch(assignment)
    req["status"] = "CANCELLED"
    req["cancellation_fee_cents"] = fee
    req["cancelled_at"] = now()
    touch(req)
    if fee > 0 and assignment is not None:
        create_fee_only_invoice(req, assignment, fee)


# --------------------------------------------------------------------------
# Lazy offer expiry + deferred clock sweeps (PRD §2.4)
# --------------------------------------------------------------------------
def lazy_expire_assignment(a):
    if a["status"] == "OFFERED" and now() >= a["response_deadline"]:
        a["status"] = "EXPIRED"
        touch(a)
        req = DB.requests.get(a["request_id"])
        if req is not None and req["status"] == "OFFERED":
            request_rematch_or_unfilled(req)


def lazy_expire_all():
    for a in list(DB.assignments.values()):
        lazy_expire_assignment(a)


def run_clock_sweeps():
    """Order: (1) offer expiry, (2) encounter auto-verify, (3) UNFILLED sweep."""
    expired = 0
    verified = 0
    unfilled = 0
    # (1) expire OFFERED assignments at/past response_deadline
    for a in sorted(DB.assignments.values(), key=lambda x: x["_seq"]):
        if a["status"] == "OFFERED" and now() >= a["response_deadline"]:
            a["status"] = "EXPIRED"
            touch(a)
            expired += 1
            req = DB.requests.get(a["request_id"])
            if req is not None and req["status"] == "OFFERED":
                request_rematch_or_unfilled(req)
    # (2) auto-verify encounters at/past verify_deadline
    for e in sorted(DB.encounters.values(), key=lambda x: x["_seq"]):
        if (not e["verified"] and e["verify_deadline"] is not None
                and now() >= e["verify_deadline"]):
            e["verified"] = True
            e["verified_by"] = "SYSTEM"
            touch(e)
            verified += 1
            a = DB.assignments.get(e["assignment_id"])
            if a is not None and a["status"] == "COMPLETED":
                req = DB.requests.get(a["request_id"])
                if req is not None and req["status"] == "IN_PROGRESS":
                    req["status"] = "COMPLETED"
                    touch(req)
    # (3) MATCHING/OFFERED requests at/past scheduled_start -> UNFILLED
    for req in sorted(DB.requests.values(), key=lambda x: x["_seq"]):
        if req["status"] in ("MATCHING", "OFFERED") and now() >= req["scheduled_start"]:
            if req["status"] == "OFFERED":
                a = outstanding_offer(req)
                if a is not None:
                    a["status"] = "EXPIRED"
                    touch(a)
                    expired += 1
            req["status"] = "UNFILLED"
            touch(req)
            unfilled += 1
    return expired, verified, unfilled
