"""Routes: ProgressConference, RefundClaim."""
from flask import Blueprint

from core import (
    DB, auth, ok, ok_list, body, err, bad_request, not_found, invalid_state, forbidden,
    req_str, req_int, req_enum, req_dt,
    new_resource, new_ledger_entry, touch, get_or_404, sorted_items,
    logical_now, logical_today, parse_dt_val, pod_gate,
    recompute_funding, recompute_voucher_accepted, withdrawal_refund, create_claim,
)
from routes_a import request_arg
from routes_c import _seat_in_pod, _family_owns_seat_or_403

bp = Blueprint("d", __name__)


def _conf_in_pod(pod_id, conf_id):
    c = DB["conferences"].get(conf_id)
    if c is None or c["pod_id"] != pod_id:
        not_found("ProgressConference '%s' does not exist for this pod" % conf_id)
    return c


def _overlap_exists(guide_id, start, end, exclude_id=None):
    """Half-open [start, end) overlap against the guide's non-terminal conferences."""
    if guide_id is None:
        return False
    for c in DB["conferences"].values():
        if c.get("_guide_id") != guide_id or c["id"] == exclude_id:
            continue
        if c["conference_status"] not in ("REQUESTED", "SCHEDULED", "RESCHEDULED"):
            continue
        cs = parse_dt_val(c["scheduled_start"])
        ce = parse_dt_val(c["scheduled_end"])
        if start < ce and cs < end:
            return True
    return False


# ---------------------------------------------------------------------------
# ProgressConference
# ---------------------------------------------------------------------------

@bp.post("/pods/<id>/progress-conferences")
def create_conference(id):
    uid, role = auth("Family", "Guide")
    p = get_or_404("pods", id, "Pod")
    b = body()
    seat_id = req_str(b, "seat_id")
    plan_id = req_str(b, "curriculum_plan_id")
    start = req_dt(b, "scheduled_start")
    end = req_dt(b, "scheduled_end")
    s = _seat_in_pod(id, seat_id)
    plan = DB["plans"].get(plan_id)
    if plan is None:
        not_found("CurriculumPlan '%s' does not exist" % plan_id)
    _family_owns_seat_or_403(uid, role, s)

    # posture gate, then overlap, then window validity, then plan approval
    pod_gate(p, block_frozen=True, block_closed=True)
    guide_id = uid if role == "Guide" else None
    if _overlap_exists(guide_id, start, end):
        err("ERR_CONFERENCE_OVERLAP", 422,
            "Another non-terminal conference for this guide overlaps the requested window")
    now = logical_now()
    if not (start < end) or start <= now:
        err("ERR_INVALID_CONFERENCE_WINDOW", 422,
            "scheduled_start must precede scheduled_end and the window must lie in the future")
    if plan["plan_status"] != "APPROVED" or plan["pod_id"] != id:
        err("ERR_PLAN_NOT_APPROVED", 422,
            "curriculum_plan_id must reference an APPROVED plan belonging to the same pod")
    c = new_resource()
    c.update({
        "pod_id": id,
        "seat_id": seat_id,
        "curriculum_plan_id": plan_id,
        "scheduled_start": b["scheduled_start"],
        "scheduled_end": b["scheduled_end"],
        "conference_status": "REQUESTED",
        "notes_summary": None,
        "cycle_count": 0,
        "_guide_id": guide_id,
    })
    DB["conferences"][c["id"]] = c
    return ok(c, 201)


@bp.get("/pods/<id>/progress-conferences")
def list_pod_conferences(id):
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer", "Guide", "Family")
    get_or_404("pods", id, "Pod")
    items = [c for c in sorted_items(DB["conferences"]) if c["pod_id"] == id]
    st = request_arg("conference_status")
    if st is not None:
        items = [c for c in items if c["conference_status"] == st]
    sid = request_arg("seat_id")
    if sid is not None:
        items = [c for c in items if c["seat_id"] == sid]
    return ok_list(items)


@bp.get("/progress-conferences/<id>")
def get_conference(id):
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer", "Guide", "Family")
    return ok(get_or_404("conferences", id, "ProgressConference"))


@bp.get("/progress-conferences")
def list_conferences():
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer")
    items = sorted_items(DB["conferences"])
    pid = request_arg("pod_id")
    if pid is not None:
        items = [c for c in items if c["pod_id"] == pid]
    sid = request_arg("seat_id")
    if sid is not None:
        items = [c for c in items if c["seat_id"] == sid]
    cpid = request_arg("curriculum_plan_id")
    if cpid is not None:
        items = [c for c in items if c["curriculum_plan_id"] == cpid]
    st = request_arg("conference_status")
    if st is not None:
        items = [c for c in items if c["conference_status"] == st]
    return ok_list(items)


@bp.post("/pods/<id>/progress-conferences/<conf_id>/schedule")
def schedule_conference(id, conf_id):
    uid, role = auth("Guide")
    p = get_or_404("pods", id, "Pod")
    c = _conf_in_pod(id, conf_id)
    if c["conference_status"] not in ("REQUESTED", "RESCHEDULED"):
        invalid_state("Conference must be REQUESTED or RESCHEDULED to schedule")
    if p["status"] != "ACTIVE":
        invalid_state("Pod must be ACTIVE to schedule a conference")
    s = DB["seats"].get(c["seat_id"])
    if s is None or s["seat_status"] != "ENROLLED":
        invalid_state("Seat must be ENROLLED to schedule a conference")
    start = parse_dt_val(c["scheduled_start"])
    end = parse_dt_val(c["scheduled_end"])
    if _overlap_exists(uid, start, end, exclude_id=c["id"]):
        err("ERR_CONFERENCE_OVERLAP", 422,
            "Another non-terminal conference for this guide overlaps the window")
    plan = DB["plans"].get(c["curriculum_plan_id"])
    if plan is None or plan["plan_status"] != "APPROVED" or plan["pod_id"] != id:
        err("ERR_PLAN_NOT_APPROVED", 422, "Conference plan is not APPROVED for this pod")
    c["conference_status"] = "SCHEDULED"
    c["_guide_id"] = uid
    touch(c)
    return ok(c)


@bp.post("/pods/<id>/progress-conferences/<conf_id>/complete")
def complete_conference(id, conf_id):
    auth("Guide")
    get_or_404("pods", id, "Pod")
    c = _conf_in_pod(id, conf_id)
    b = body()
    notes = b.get("notes_summary")
    if not isinstance(notes, str) or notes == "":
        bad_request("notes_summary must be a non-empty string to complete a conference")
    if c["conference_status"] != "SCHEDULED":
        invalid_state("Only a SCHEDULED conference can be completed")
    c["conference_status"] = "COMPLETED"
    c["notes_summary"] = notes
    touch(c)
    return ok(c)


@bp.post("/pods/<id>/progress-conferences/<conf_id>/mark-no-show")
def mark_no_show(id, conf_id):
    auth("Guide")
    get_or_404("pods", id, "Pod")
    c = _conf_in_pod(id, conf_id)
    if c["conference_status"] != "SCHEDULED":
        invalid_state("Only a SCHEDULED conference can be marked NO_SHOW")
    if logical_now() < parse_dt_val(c["scheduled_end"]):
        invalid_state("Conference cannot be marked NO_SHOW before its scheduled_end")
    c["conference_status"] = "NO_SHOW"
    touch(c)
    return ok(c)


@bp.post("/pods/<id>/progress-conferences/<conf_id>/reschedule")
def reschedule_conference(id, conf_id):
    uid, role = auth("Family")
    get_or_404("pods", id, "Pod")
    c = _conf_in_pod(id, conf_id)
    s = DB["seats"].get(c["seat_id"])
    if s is not None:
        _family_owns_seat_or_403(uid, role, s)
    if c["conference_status"] != "NO_SHOW":
        invalid_state("Only a NO_SHOW conference can be rescheduled")
    if c["cycle_count"] >= 3:
        err("ERR_CONFERENCE_CYCLE_LIMIT", 422, "Reschedule cycle limit of 3 reached")
    c["conference_status"] = "RESCHEDULED"
    c["cycle_count"] += 1
    touch(c)
    return ok(c)


@bp.post("/pods/<id>/progress-conferences/<conf_id>/cancel")
def cancel_conference(id, conf_id):
    uid, role = auth("Family")
    get_or_404("pods", id, "Pod")
    c = _conf_in_pod(id, conf_id)
    s = DB["seats"].get(c["seat_id"])
    if s is not None:
        _family_owns_seat_or_403(uid, role, s)
    if c["conference_status"] not in ("REQUESTED", "SCHEDULED", "RESCHEDULED"):
        invalid_state("Conference in status %s cannot be cancelled" % c["conference_status"])
    c["conference_status"] = "CANCELLED"
    touch(c)
    return ok(c)


# ---------------------------------------------------------------------------
# RefundClaim
# ---------------------------------------------------------------------------

def _claim_in_pod(pod_id, claim_id):
    c = DB["claims"].get(claim_id)
    if c is None or c["pod_id"] != pod_id:
        not_found("RefundClaim '%s' does not exist for this pod" % claim_id)
    return c


@bp.post("/pods/<id>/refund-claims")
def create_claim_endpoint(id):
    uid, role = auth("Family", "Registrar")
    p = get_or_404("pods", id, "Pod")
    b = body()
    seat_id = req_str(b, "seat_id")
    kind = req_enum(b, "claim_kind", ("WITHDRAWAL", "DISSOLUTION", "OVERPAYMENT"))
    s = _seat_in_pod(id, seat_id)
    _family_owns_seat_or_403(uid, role, s)
    pod_gate(p, block_frozen=False, block_closed=True)
    for c in DB["claims"].values():
        if c["seat_id"] == seat_id and c["claim_kind"] == kind \
                and c["claim_status"] in ("FILED", "UNDER_REVIEW", "APPROVED"):
            err("ERR_CLAIM_ALREADY_EXISTS", 422,
                "A non-terminal claim already exists for this seat and kind")
    if kind == "WITHDRAWAL" and s["seat_status"] == "WITHDRAWN" and s.get("withdrawn_on"):
        amount = withdrawal_refund(p, s)
    else:
        due = s.get("prorated_due_cents") or 0
        amount = max(0, s["paid_cents"] - due)
    c = create_claim(p, s, kind, amount, uid)
    return ok(c, 201)


@bp.get("/pods/<id>/refund-claims")
def list_pod_claims(id):
    auth("PlatformAdmin", "PodOperator", "Registrar", "Family")
    get_or_404("pods", id, "Pod")
    items = [c for c in sorted_items(DB["claims"]) if c["pod_id"] == id]
    st = request_arg("claim_status")
    if st is not None:
        items = [c for c in items if c["claim_status"] == st]
    kind = request_arg("claim_kind")
    if kind is not None:
        items = [c for c in items if c["claim_kind"] == kind]
    sid = request_arg("seat_id")
    if sid is not None:
        items = [c for c in items if c["seat_id"] == sid]
    return ok_list(items)


@bp.get("/refund-claims/<id>")
def get_claim(id):
    auth("PlatformAdmin", "PodOperator", "Registrar", "Family")
    return ok(get_or_404("claims", id, "RefundClaim"))


@bp.get("/refund-claims")
def list_claims():
    auth("PlatformAdmin", "PodOperator", "Registrar", "ComplianceOfficer")
    items = sorted_items(DB["claims"])
    pid = request_arg("pod_id")
    if pid is not None:
        items = [c for c in items if c["pod_id"] == pid]
    sid = request_arg("seat_id")
    if sid is not None:
        items = [c for c in items if c["seat_id"] == sid]
    st = request_arg("claim_status")
    if st is not None:
        items = [c for c in items if c["claim_status"] == st]
    kind = request_arg("claim_kind")
    if kind is not None:
        items = [c for c in items if c["claim_kind"] == kind]
    return ok_list(items)


@bp.post("/pods/<id>/refund-claims/<claim_id>/begin-review")
def begin_claim_review(id, claim_id):
    auth("Registrar")
    get_or_404("pods", id, "Pod")
    c = _claim_in_pod(id, claim_id)
    if c["claim_status"] != "FILED":
        invalid_state("Only a FILED claim can begin review")
    c["claim_status"] = "UNDER_REVIEW"
    touch(c)
    return ok(c)


@bp.post("/pods/<id>/refund-claims/<claim_id>/decide")
def decide_claim(id, claim_id):
    uid, role = auth("Registrar")
    get_or_404("pods", id, "Pod")
    c = _claim_in_pod(id, claim_id)
    b = body()
    decision = req_enum(b, "decision", ("APPROVED", "DENIED"))
    if c["claim_status"] != "UNDER_REVIEW":
        invalid_state("Only an UNDER_REVIEW claim can be decided")
    # segregation of duties before amount bounds
    if uid == c["filed_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 422,
            "The reviewer's X-User-ID must differ from the claim filer")
    seat = DB["seats"].get(c["seat_id"])
    if decision == "APPROVED":
        amt = req_int(b, "approved_amount_cents")
        if amt > c["claimed_amount_cents"] or amt < 0:
            err("ERR_REFUND_EXCEEDS_CLAIM", 422,
                "approved_amount_cents must be between 0 and claimed_amount_cents")
        c["claim_status"] = "APPROVED"
        c["approved_amount_cents"] = amt
        c["reviewed_by_user_id"] = uid
        if seat is not None:
            seat["refund_due_cents"] = amt
            touch(seat)
    else:
        c["claim_status"] = "DENIED"
        c["reviewed_by_user_id"] = uid
        if seat is not None:
            seat["refund_due_cents"] = 0
            touch(seat)
    touch(c)
    return ok(c)


@bp.post("/pods/<id>/refund-claims/<claim_id>/disburse")
def disburse_claim(id, claim_id):
    auth("PlatformAdmin")
    p = get_or_404("pods", id, "Pod")
    c = _claim_in_pod(id, claim_id)
    if c["claim_status"] != "APPROVED":
        invalid_state("Only an APPROVED claim can be disbursed")
    seat = DB["seats"].get(c["seat_id"])
    # voucher-routed disbursement for DISSOLUTION claims
    if seat is not None and c["claim_kind"] == "DISSOLUTION":
        stu = DB["students"].get(seat["student_id"])
        vid = stu.get("esa_account_id") if stu else None
        v = DB["vouchers"].get(vid) if vid else None
        if v is not None and v["funding_status"] == "FROZEN":
            owner = DB["pods"].get(v.get("_frozen_by_pod_id"))
            seat_ids = {s["id"] for s in DB["seats"].values()
                        if s["student_id"] == v["student_id"]
                        and (owner is None or s["pod_id"] == owner["id"])}
            undecided = any(
                cl["seat_id"] in seat_ids and cl["claim_status"] not in ("APPROVED", "PAID", "DENIED")
                for cl in DB["claims"].values()
            )
            if owner is not None and owner["status"] in ("DISSOLVING", "DISSOLVED") and not undecided:
                # disburse triggers the release, then posts
                v["_frozen_by_pod_id"] = None
                v["funding_status"] = "FUNDED"
                recompute_funding(v)
                touch(v)
                recompute_voucher_accepted(v)
            else:
                invalid_state("Voucher account is FROZEN and cannot be released yet")
    # post a REFUND_REVERSAL payment against a synthesized zero-balance invoice
    today = logical_today().isoformat()
    inv = new_resource()
    inv.update({
        "seat_id": c["seat_id"],
        "billing_period_start": today,
        "billing_period_end": today,
        "line_items": [],
        "subtotal_cents": 0,
        "admin_fee_cents": 0,
        "total_cents": 0,
        "paid_cents": 0,
        "invoice_status": "PAID",
        "due_date": today,
        "_pod_id": id,
    })
    DB["invoices"][inv["id"]] = inv
    from core import logical_now_iso
    pay = new_ledger_entry()
    pay.update({
        "invoice_id": inv["id"],
        "seat_id": c["seat_id"],
        "source_kind": "REFUND_REVERSAL",
        "voucher_account_id": None,
        "amount_cents": c["approved_amount_cents"],
        "paid_at": logical_now_iso(),
        "payment_status": "CLEARED",
        "_pod_id": id,
    })
    DB["payments"][pay["id"]] = pay
    c["claim_status"] = "PAID"
    touch(c)
    return ok(c)
