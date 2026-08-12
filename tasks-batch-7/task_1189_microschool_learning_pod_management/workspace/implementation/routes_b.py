"""Routes: Guide, GuideAssignment, Family, Student, VoucherAccount."""
import re
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

from flask import Blueprint

from core import (
    DB, auth, ok, ok_list, body, err, bad_request, not_found, invalid_state, forbidden,
    req_str, req_int, req_enum, opt_enum, req_date, req_bool, opt_bool,
    new_resource, touch, get_or_404, sorted_items, logical_today,
    parse_date_val, grade_band_for, recompute_compliance, pod_gate,
    recompute_funding, recompute_voucher_accepted, rhu,
)
from routes_a import request_arg

bp = Blueprint("b", __name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# Guide
# ---------------------------------------------------------------------------

@bp.post("/guides")
def create_guide():
    auth("PlatformAdmin")
    b = body()
    name = req_str(b, "full_name")
    email = req_str(b, "email")
    if not _EMAIL_RE.match(email):
        bad_request("email is malformed")
    for g in DB["guides"].values():
        if g["email"].lower() == email.lower():
            bad_request("email must be unique across guides")
    tier = req_enum(b, "certification_tier", ("APPRENTICE", "CERTIFIED", "LEAD"))
    g = new_resource()
    g.update({
        "full_name": name,
        "email": email,
        "certification_tier": tier,
        "fte_weight": 0.5 if tier == "APPRENTICE" else 1.0,
        "guide_status": "CANDIDATE",
    })
    DB["guides"][g["id"]] = g
    return ok(g, 201)


@bp.get("/guides/<id>")
def get_guide(id):
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer")
    return ok(get_or_404("guides", id, "Guide"))


@bp.post("/guides/<id>/activate")
def activate_guide(id):
    auth("PlatformAdmin")
    g = get_or_404("guides", id, "Guide")
    if g["guide_status"] != "CANDIDATE":
        invalid_state("Only a CANDIDATE guide can be activated")
    g["guide_status"] = "ACTIVE"
    touch(g)
    return ok(g)


@bp.post("/guides/<id>/deactivate")
def deactivate_guide(id):
    auth("PlatformAdmin")
    g = get_or_404("guides", id, "Guide")
    if g["guide_status"] != "ACTIVE":
        invalid_state("Only an ACTIVE guide can be deactivated")
    for a in DB["assignments"].values():
        if a["guide_id"] == id and a["assignment_status"] in ("SCHEDULED", "ACTIVE"):
            invalid_state("Guide has SCHEDULED or ACTIVE assignments")
    g["guide_status"] = "INACTIVE"
    touch(g)
    return ok(g)


# ---------------------------------------------------------------------------
# GuideAssignment
# ---------------------------------------------------------------------------

@bp.post("/pods/<id>/guide-assignments")
def create_assignment(id):
    auth("PodOperator")
    p = get_or_404("pods", id, "Pod")
    b = body()
    guide_id = req_str(b, "guide_id")
    ws = req_date(b, "window_start_date")
    we = req_date(b, "window_end_date")
    hours = req_int(b, "weekly_hours", min_v=4, max_v=40)
    is_primary = opt_bool(b, "is_primary", default=False)

    guide = DB["guides"].get(guide_id)
    if guide is None:
        not_found("Guide '%s' does not exist" % guide_id)

    # posture gate first
    pod_gate(p, block_frozen=True, block_closed=True)
    # then window overlap (inclusive both ends) against the guide's live assignments
    for a in DB["assignments"].values():
        if a["guide_id"] != guide_id or a["assignment_status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        aws = parse_date_val(a["window_start_date"])
        awe = parse_date_val(a["window_end_date"])
        if ws <= awe and aws <= we:
            err("ERR_GUIDE_WINDOW_OVERLAP", 422,
                "Window overlaps another SCHEDULED/ACTIVE assignment for this guide")
    # then window validity
    ts = parse_date_val(p["term_start_date"])
    te = parse_date_val(p["term_end_date"])
    if ws > we or we < ts or ws > te:
        err("ERR_INVALID_WINDOW", 422,
            "window_start_date must not exceed window_end_date and the window must intersect the pod term")
    # then guide standing
    if guide["guide_status"] != "ACTIVE":
        err("ERR_GUIDE_INACTIVE", 422, "Guide is not ACTIVE")

    a = new_resource()
    a.update({
        "pod_id": id,
        "guide_id": guide_id,
        "window_start_date": ws.isoformat(),
        "window_end_date": we.isoformat(),
        "weekly_hours": hours,
        "assignment_status": "SCHEDULED",
        "is_primary": is_primary,
    })
    DB["assignments"][a["id"]] = a
    return ok(a, 201)


@bp.get("/pods/<id>/guide-assignments")
def list_pod_assignments(id):
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer", "Guide")
    get_or_404("pods", id, "Pod")
    items = [a for a in sorted_items(DB["assignments"]) if a["pod_id"] == id]
    st = request_arg("assignment_status")
    if st is not None:
        items = [a for a in items if a["assignment_status"] == st]
    gid = request_arg("guide_id")
    if gid is not None:
        items = [a for a in items if a["guide_id"] == gid]
    return ok_list(items)


@bp.get("/guide-assignments/<id>")
def get_assignment(id):
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer", "Guide")
    return ok(get_or_404("assignments", id, "GuideAssignment"))


@bp.get("/guide-assignments")
def list_assignments():
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer")
    items = sorted_items(DB["assignments"])
    pid = request_arg("pod_id")
    if pid is not None:
        items = [a for a in items if a["pod_id"] == pid]
    gid = request_arg("guide_id")
    if gid is not None:
        items = [a for a in items if a["guide_id"] == gid]
    st = request_arg("assignment_status")
    if st is not None:
        items = [a for a in items if a["assignment_status"] == st]
    return ok_list(items)


@bp.post("/pods/<id>/guide-assignments/<asg_id>/terminate")
def terminate_assignment(id, asg_id):
    auth("PodOperator")
    p = get_or_404("pods", id, "Pod")
    a = DB["assignments"].get(asg_id)
    if a is None or a["pod_id"] != id:
        not_found("GuideAssignment '%s' does not exist for this pod" % asg_id)
    cur = a["assignment_status"]
    if cur == "SCHEDULED":
        if p["status"] not in ("DRAFT", "FORMING", "LICENSING_REVIEW", "ACTIVE", "SUSPENDED"):
            invalid_state("Pod status %s does not permit terminating an assignment" % p["status"])
        a["assignment_status"] = "TERMINATED_EARLY"
        touch(a)
        # PRD 3.4: the ratio is recomputed "whenever an assignment starts,
        # ends, or terminates", and "The termination recomputes the pod's
        # compliance flag, and if the ratio is found in violation the pod is
        # automatically suspended."
        recompute_compliance(p, allow_autosuspend=True)
        from core import refresh_posture
        refresh_posture(p)
        return ok(a)
    if cur != "ACTIVE":
        invalid_state("Assignment in status %s cannot be terminated" % cur)
    if p["status"] not in ("ACTIVE", "SUSPENDED"):
        invalid_state("Pod status %s does not permit terminating an ACTIVE assignment" % p["status"])
    # staffing-floor guard
    projected = Fraction(0)
    for o in DB["assignments"].values():
        if o["id"] == asg_id or o["pod_id"] != id:
            continue
        if o["assignment_status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        g = DB["guides"].get(o["guide_id"])
        if g is None:
            continue
        from core import guide_weight
        projected += guide_weight(g, p) * min(Fraction(1), Fraction(o["weekly_hours"], 30))
    today = logical_today()
    replacement = any(
        o["pod_id"] == id and o["id"] != asg_id and o["assignment_status"] == "SCHEDULED"
        and today <= parse_date_val(o["window_start_date"]) <= today + timedelta(days=7)
        for o in DB["assignments"].values()
    )
    if projected < Fraction(p["min_guides_required"]) and not replacement:
        invalid_state("Termination would drop projected staffing below min_guides_required")
    a["assignment_status"] = "TERMINATED_EARLY"
    touch(a)
    # scaffold-pinned auto-cascade: ratio VIOLATION on terminate suspends the pod
    recompute_compliance(p, allow_autosuspend=True)
    from core import refresh_posture
    refresh_posture(p)
    return ok(a)


# ---------------------------------------------------------------------------
# Family & Student
# ---------------------------------------------------------------------------

@bp.post("/families")
def create_family():
    auth("Registrar")
    b = body()
    name = req_str(b, "family_name")
    email = req_str(b, "primary_contact_email")
    if not _EMAIL_RE.match(email):
        bad_request("primary_contact_email is malformed")
    for f in DB["families"].values():
        if f["primary_contact_email"].lower() == email.lower():
            bad_request("primary_contact_email must be unique across families")
    state = req_str(b, "billing_address_state")
    if not re.match(r"^[A-Za-z]{2}$", state):
        bad_request("billing_address_state must be a two-letter US state code")
    f = new_resource()
    f.update({
        "family_name": name,
        "primary_contact_email": email,
        "billing_address_state": state,
        "family_status": "PROSPECT",
    })
    DB["families"][f["id"]] = f
    return ok(f, 201)


@bp.get("/families/<id>")
def get_family(id):
    uid, role = auth("PlatformAdmin", "Registrar", "Family")
    f = get_or_404("families", id, "Family")
    if role == "Family" and uid != id:
        forbidden("Family callers may only access their own family record")
    return ok(f)


@bp.get("/families/<id>/students")
def list_family_students(id):
    uid, role = auth("PlatformAdmin", "Registrar", "Family")
    get_or_404("families", id, "Family")
    if role == "Family" and uid != id:
        forbidden("Family callers may only access their own family record")
    items = [s for s in sorted_items(DB["students"]) if s["family_id"] == id]
    st = request_arg("student_status")
    if st is not None:
        items = [s for s in items if s["student_status"] == st]
    return ok_list(items)


@bp.post("/families/<id>/students")
def create_student(id):
    auth("Registrar")
    get_or_404("families", id, "Family")
    b = body()
    first = req_str(b, "legal_first_name")
    last = req_str(b, "legal_last_name")
    dob = req_date(b, "date_of_birth")
    esa = b.get("esa_account_id")
    if esa is not None:
        if not isinstance(esa, str):
            bad_request("esa_account_id must be a string")
        v = DB["vouchers"].get(esa)
        if v is None:
            not_found("VoucherAccount '%s' does not exist" % esa)
        # voucher must belong to this (new) student — impossible unless pre-linked
        err("ERR_VOUCHER_STUDENT_MISMATCH", 422,
            "esa_account_id references a VoucherAccount owned by a different student")
    s = new_resource()
    s.update({
        "family_id": id,
        "legal_first_name": first,
        "legal_last_name": last,
        "date_of_birth": dob.isoformat(),
        "grade_band": grade_band_for(dob, logical_today()),
        "esa_account_id": None,
        "student_status": "APPLICANT",
    })
    DB["students"][s["id"]] = s
    return ok(s, 201)


@bp.get("/students/<id>")
def get_student(id):
    uid, role = auth("PlatformAdmin", "Registrar", "Family")
    s = get_or_404("students", id, "Student")
    if role == "Family" and s["family_id"] != uid:
        forbidden("Family callers may only access their own students")
    return ok(s)


@bp.get("/students")
def list_students():
    auth("PlatformAdmin", "Registrar", "ComplianceOfficer")
    items = sorted_items(DB["students"])
    fid = request_arg("family_id")
    if fid is not None:
        items = [s for s in items if s["family_id"] == fid]
    esa = request_arg("esa_account_id")
    if esa is not None:
        items = [s for s in items if s.get("esa_account_id") == esa]
    st = request_arg("student_status")
    if st is not None:
        items = [s for s in items if s["student_status"] == st]
    return ok_list(items)


# ---------------------------------------------------------------------------
# VoucherAccount
# ---------------------------------------------------------------------------

@bp.post("/students/<id>/voucher-accounts")
def create_voucher(id):
    auth("Registrar")
    stu = get_or_404("students", id, "Student")
    b = body()
    program = req_str(b, "program_code")
    awarded = req_int(b, "awarded_annual_cents", min_v=1)
    schedule = opt_enum(b, "release_schedule", ("QUARTERLY", "MONTHLY"), default="QUARTERLY")
    v = new_resource()
    balance = awarded
    if schedule == "MONTHLY":
        balance = min(awarded, max(1, rhu(Decimal(awarded) / Decimal(10))))
    v.update({
        "student_id": id,
        "program_code": program,
        "awarded_annual_cents": awarded,
        "disbursable_balance_cents": balance,
        "verification_status": "PENDING_VERIFICATION",
        "funding_status": "FUNDED",
        "accepted_by_pod": False,
        "_release_schedule": schedule,
        "_frozen_by_pod_id": None,
    })
    recompute_funding(v)
    DB["vouchers"][v["id"]] = v
    # link the student to this voucher account
    stu["esa_account_id"] = v["id"]
    touch(stu)
    recompute_voucher_accepted(v)
    return ok(v, 201)


@bp.get("/voucher-accounts/<id>")
def get_voucher(id):
    auth("PlatformAdmin", "Registrar", "ComplianceOfficer")
    return ok(get_or_404("vouchers", id, "VoucherAccount"))


@bp.get("/voucher-accounts")
def list_vouchers():
    auth("PlatformAdmin", "Registrar", "ComplianceOfficer")
    items = sorted_items(DB["vouchers"])
    sid = request_arg("student_id")
    if sid is not None:
        items = [v for v in items if v["student_id"] == sid]
    vs = request_arg("verification_status")
    if vs is not None:
        items = [v for v in items if v["verification_status"] == vs]
    fs = request_arg("funding_status")
    if fs is not None:
        items = [v for v in items if v["funding_status"] == fs]
    return ok_list(items)


@bp.post("/voucher-accounts/<id>/verify")
def verify_voucher(id):
    auth("ComplianceOfficer")
    v = get_or_404("vouchers", id, "VoucherAccount")
    if v["verification_status"] != "PENDING_VERIFICATION":
        invalid_state("Only a PENDING_VERIFICATION account can be verified")
    v["verification_status"] = "VERIFIED"
    touch(v)
    recompute_voucher_accepted(v)
    return ok(v)


@bp.post("/voucher-accounts/<id>/reject")
def reject_voucher(id):
    auth("ComplianceOfficer")
    v = get_or_404("vouchers", id, "VoucherAccount")
    if v["verification_status"] != "PENDING_VERIFICATION":
        invalid_state("Only a PENDING_VERIFICATION account can be rejected")
    v["verification_status"] = "REJECTED"
    touch(v)
    recompute_voucher_accepted(v)
    return ok(v)


@bp.post("/voucher-accounts/<id>/release")
def release_voucher(id):
    auth("PlatformAdmin")
    v = get_or_404("vouchers", id, "VoucherAccount")
    if v["funding_status"] != "FROZEN":
        invalid_state("Only a FROZEN account can be released")
    pod_id = v.get("_frozen_by_pod_id")
    pod = DB["pods"].get(pod_id) if pod_id else None
    if pod is None or pod["status"] not in ("DISSOLVING", "DISSOLVED"):
        invalid_state("Owning pod must be in dissolution before release")
    seat_ids = {s["id"] for s in DB["seats"].values()
                if s["student_id"] == v["student_id"] and s["pod_id"] == pod_id}
    for c in DB["claims"].values():
        if c["seat_id"] in seat_ids and c["claim_status"] not in ("APPROVED", "PAID", "DENIED"):
            invalid_state("All refund claims for the seat must be decided before release")
    v["_frozen_by_pod_id"] = None
    # recompute from thresholds (clears FROZEN)
    v["funding_status"] = "FUNDED"
    recompute_funding(v)
    touch(v)
    recompute_voucher_accepted(v)
    return ok(v)
