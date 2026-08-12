"""Routes: logical clock, FacilitySite, Pod lifecycle, SafetyPolicy, CurriculumPlan, LicensingDetermination."""
from flask import Blueprint

from core import (
    DB, auth, ok, ok_list, body, err, bad_request, not_found, invalid_state,
    req_str, opt_str, req_int, opt_int, req_bool, req_enum, opt_enum, req_date, req_dt,
    new_resource, touch, get_or_404, sorted_items, dt_iso, logical_now, logical_today,
    refresh_posture, recompute_enrolled_count, recompute_compliance, pod_gate,
    supersede_plan, try_activate_pod, create_claim, dissolution_pool_amounts,
    recompute_accepted_for_pod, parse_date_val,
    ZONING_CLASSES, EXEMPT_ZONING, GRADE_BANDS,
)

bp = Blueprint("a", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    auth("PlatformAdmin")
    b = body()
    to = req_dt(b, "to_iso8601")
    DB["clock"] = to
    from core import run_clock_transitions
    run_clock_transitions()
    return ok({"current_utc": dt_iso(DB["clock"])})


# ---------------------------------------------------------------------------
# FacilitySite
# ---------------------------------------------------------------------------

@bp.post("/facility-sites")
def create_site():
    auth("PlatformAdmin")
    b = body()
    s = new_resource()
    s.update({
        "site_name": req_str(b, "site_name"),
        "address_line1": req_str(b, "address_line1"),
        "jurisdiction_code": req_str(b, "jurisdiction_code"),
        "zoning_class": req_enum(b, "zoning_class", ZONING_CLASSES),
        "max_occupancy": req_int(b, "max_occupancy", min_v=1),
        "indoor_sqft": req_int(b, "indoor_sqft", min_v=1),
        "site_status": "AVAILABLE",
    })
    DB["sites"][s["id"]] = s
    return ok(s, 201)


@bp.get("/facility-sites/<id>")
def get_site(id):
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer")
    return ok(get_or_404("sites", id, "FacilitySite"))


@bp.get("/facility-sites")
def list_sites():
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer")
    items = sorted_items(DB["sites"])
    st = request_arg("site_status")
    if st is not None:
        items = [s for s in items if s["site_status"] == st]
    jc = request_arg("jurisdiction_code")
    if jc is not None:
        items = [s for s in items if s["jurisdiction_code"] == jc]
    return ok_list(items)


def request_arg(name):
    from flask import request
    return request.args.get(name)


@bp.post("/facility-sites/<id>/archive")
def archive_site(id):
    auth("PlatformAdmin")
    s = get_or_404("sites", id, "FacilitySite")
    if s["site_status"] != "AVAILABLE":
        invalid_state("Only an AVAILABLE site can be archived")
    for p in DB["pods"].values():
        if p["facility_site_id"] == id and p["status"] != "DISSOLVED":
            invalid_state("Site is referenced by a non-DISSOLVED pod")
    s["site_status"] = "ARCHIVED"
    touch(s)
    return ok(s)


@bp.post("/facility-sites/<id>/release")
def release_site(id):
    auth("PlatformAdmin")
    s = get_or_404("sites", id, "FacilitySite")
    if s["site_status"] != "LEASED":
        invalid_state("Only a LEASED site can be released")
    blocking = ("DRAFT", "FORMING", "LICENSING_REVIEW", "ACTIVE", "SUSPENDED", "DISSOLVING")
    for p in DB["pods"].values():
        if p["facility_site_id"] == id and p["status"] in blocking:
            invalid_state("Site is referenced by a pod in status %s" % p["status"])
    s["site_status"] = "AVAILABLE"
    touch(s)
    return ok(s)


# ---------------------------------------------------------------------------
# Pod
# ---------------------------------------------------------------------------

@bp.post("/pods")
def create_pod():
    auth("PodOperator")
    b = body()
    import re as _re
    name = req_str(b, "name")
    pod_code = req_str(b, "pod_code")
    if not _re.match(r"^[A-Za-z0-9]{4,24}$", pod_code):
        bad_request("pod_code must be 4-24 alphanumeric characters")
    for p in DB["pods"].values():
        if p["pod_code"].lower() == pod_code.lower():
            bad_request("pod_code must be unique (case-insensitive)")
    academic_year = req_str(b, "academic_year")
    ts = req_date(b, "term_start_date")
    te = req_date(b, "term_end_date")
    if te < ts:
        bad_request("term_end_date must not precede term_start_date")
    seat_capacity = req_int(b, "seat_capacity", min_v=5, max_v=30)
    tuition = req_int(b, "tuition_full_year_cents", min_v=1)
    min_guides = req_int(b, "min_guides_required", min_v=1)
    site_id = req_str(b, "facility_site_id")
    site = DB["sites"].get(site_id)
    if site is None:
        not_found("FacilitySite '%s' does not exist" % site_id)
    if site["site_status"] == "ARCHIVED":
        bad_request("Archived sites cannot host new pods")

    p = new_resource()
    p.update({
        "name": name,
        "pod_code": pod_code,
        "academic_year": academic_year,
        "term_start_date": ts.isoformat(),
        "term_end_date": te.isoformat(),
        "seat_capacity": seat_capacity,
        "enrolled_count": 0,
        "tuition_full_year_cents": tuition,
        "min_guides_required": min_guides,
        "facility_site_id": site_id,
        "status": "DRAFT",
        "posture": "OPEN",
        "compliance_flag": "COMPLIANT",
        "dissolution_reason": None,
        "dissolved_at": None,
        "_proration_mode": opt_enum(b, "proration_mode", ("PER_DAY", "PER_WEEK"), default="PER_DAY"),
        "_refund_mode": opt_enum(b, "withdrawal_refund_mode", ("SLIDING_SCALE", "FLAT_FEE"), default="SLIDING_SCALE"),
        "_flat_fee_cents": opt_int(b, "flat_fee_cents", default=None, min_v=0),
        "_ratio_mode": opt_enum(b, "ratio_mode", ("FTE_WEIGHTED", "HEADCOUNT"), default="FTE_WEIGHTED"),
    })
    refresh_posture(p)
    DB["pods"][p["id"]] = p
    return ok(p, 201)


@bp.get("/pods/<id>")
def get_pod(id):
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer", "Guide", "Family", "Registrar")
    return ok(get_or_404("pods", id, "Pod"))


@bp.get("/pods")
def list_pods():
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer", "Guide", "Family", "Registrar")
    items = sorted_items(DB["pods"])
    st = request_arg("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    po = request_arg("posture")
    if po is not None:
        items = [p for p in items if p["posture"] == po]
    fs = request_arg("facility_site_id")
    if fs is not None:
        items = [p for p in items if p["facility_site_id"] == fs]
    return ok_list(items)


def _approved_policy(pod_id):
    return [sp for sp in DB["policies"].values()
            if sp["pod_id"] == pod_id and sp["policy_status"] == "APPROVED"]


def _approved_plans(pod_id):
    return [cp for cp in DB["plans"].values()
            if cp["pod_id"] == pod_id and cp["plan_status"] == "APPROVED"]


@bp.post("/pods/<id>/open-enrollment")
def open_enrollment(id):
    auth("PodOperator")
    p = get_or_404("pods", id, "Pod")
    if p["status"] != "DRAFT":
        invalid_state("Pod must be DRAFT to open enrollment")
    site = DB["sites"].get(p["facility_site_id"])
    if site is None or site["site_status"] not in ("AVAILABLE", "LEASED"):
        invalid_state("Referenced facility site is not AVAILABLE or LEASED")
    if not _approved_policy(id):
        err_safety()
    if not _approved_plans(id):
        err("ERR_CURRICULUM_INADEQUATE", 422, "Pod has no APPROVED curriculum plan")
    p["status"] = "FORMING"
    if site["site_status"] == "AVAILABLE":
        site["site_status"] = "LEASED"
        touch(site)
    refresh_posture(p)
    touch(p)
    return ok(p)


def err_safety():
    err("ERR_SAFETY_POLICY_MISSING", 422, "Pod has no APPROVED safety policy, or policy fails content requirements")


@bp.post("/pods/<id>/revert-to-draft")
def revert_to_draft(id):
    auth("PodOperator")
    p = get_or_404("pods", id, "Pod")
    if p["status"] != "FORMING":
        invalid_state("Pod must be FORMING to revert to DRAFT")
    for s in DB["seats"].values():
        if s["pod_id"] == id and s["seat_status"] in ("RESERVED", "ENROLLED"):
            invalid_state("Pod has reserved or enrolled seats")
    p["status"] = "DRAFT"
    refresh_posture(p)
    touch(p)
    return ok(p)


@bp.post("/pods/<id>/suspend")
def suspend_pod(id):
    auth("ComplianceOfficer")
    p = get_or_404("pods", id, "Pod")
    if p["status"] != "ACTIVE":
        invalid_state("Pod must be ACTIVE to suspend")
    if p["compliance_flag"] not in ("AT_RISK", "VIOLATION"):
        invalid_state("Pod compliance_flag must be AT_RISK or VIOLATION to suspend")
    p["status"] = "SUSPENDED"
    p["posture"] = "FROZEN"
    touch(p)
    recompute_accepted_for_pod(p)
    return ok(p)


@bp.post("/pods/<id>/reinstate")
def reinstate_pod(id):
    auth("ComplianceOfficer")
    p = get_or_404("pods", id, "Pod")
    if p["status"] != "SUSPENDED":
        invalid_state("Pod must be SUSPENDED to reinstate")
    recompute_compliance(p, allow_autosuspend=False)
    if p["compliance_flag"] != "COMPLIANT":
        invalid_state("Pod compliance_flag must be COMPLIANT to reinstate")
    p["status"] = "ACTIVE"
    refresh_posture(p)
    touch(p)
    recompute_accepted_for_pod(p)
    return ok(p)


@bp.post("/pods/<id>/dissolve")
def dissolve_pod(id):
    uid, _ = auth("PodOperator")
    p = get_or_404("pods", id, "Pod")
    b = body()
    expected = req_int(b, "expected_pod_version")
    reason = opt_str(b, "dissolution_reason")

    status = p["status"]
    if status == "DRAFT":
        # zero-seat branch: DRAFT -> DISSOLVED directly
        if expected != p["version"]:
            err_stale()
        p["status"] = "DISSOLVED"
        p["dissolved_at"] = dt_iso(logical_now())
        p["posture"] = "CLOSED"
        if reason is not None:
            p["dissolution_reason"] = reason
        touch(p)
        return ok(p)

    if status == "ACTIVE":
        enrolled = [s for s in DB["seats"].values()
                    if s["pod_id"] == id and s["seat_status"] == "ENROLLED"]
        if not enrolled:
            err("ERR_NO_ENROLLED_SEATS_FOR_DISSOLUTION", 422,
                "Dissolution cascade requires at least one ENROLLED seat from ACTIVE")
    elif status == "SUSPENDED":
        enrolled = [s for s in DB["seats"].values()
                    if s["pod_id"] == id and s["seat_status"] == "ENROLLED"]
    else:
        err("ERR_NO_ENROLLED_SEATS_FOR_DISSOLUTION", 422,
            "Pod status %s does not permit dissolution" % status)

    if not reason:
        bad_request("dissolution_reason is required when transitioning into DISSOLVING")
    if expected != p["version"]:
        err_stale()

    # ---- enter DISSOLVING with the five-fold cascade ----
    p["dissolution_reason"] = reason
    p["status"] = "DISSOLVING"
    p["posture"] = "CLOSED"
    today = logical_today()

    for s in enrolled:
        s["seat_status"] = "WITHDRAWN"
        s["withdrawn_on"] = today.isoformat()
        touch(s)
        stu = DB["students"].get(s["student_id"])
        if stu is not None and stu["student_status"] != "WITHDRAWN":
            stu["student_status"] = "WITHDRAWN"
            touch(stu)

    for a in DB["assignments"].values():
        if a["pod_id"] == id and a["assignment_status"] in ("SCHEDULED", "ACTIVE"):
            a["assignment_status"] = "TERMINATED_EARLY"
            touch(a)

    for pl in DB["plans"].values():
        if pl["pod_id"] == id and pl["plan_status"] == "APPROVED":
            supersede_plan(pl)

    amounts = dissolution_pool_amounts(p, enrolled)
    for s in enrolled:
        create_claim(p, s, "DISSOLUTION", amounts.get(s["id"], 0), uid)

    for s in enrolled:
        stu = DB["students"].get(s["student_id"])
        if stu is None:
            continue
        vid = stu.get("esa_account_id")
        if vid:
            v = DB["vouchers"].get(vid)
            if v is not None and v["funding_status"] != "FROZEN":
                v["funding_status"] = "FROZEN"
                v["_frozen_by_pod_id"] = id
                touch(v)
                from core import recompute_voucher_accepted
                recompute_voucher_accepted(v)

    recompute_enrolled_count(p)
    refresh_posture(p)
    touch(p)
    return ok(p)


def err_stale():
    err("ERR_STALE_VERSION", 412, "expected_pod_version does not match the pod's current version")


@bp.post("/pods/<id>/finalize-dissolution")
def finalize_dissolution(id):
    auth("PlatformAdmin")
    p = get_or_404("pods", id, "Pod")
    if p["status"] != "DISSOLVING":
        invalid_state("Pod must be DISSOLVING to finalize dissolution")
    for c in DB["claims"].values():
        if c["pod_id"] == id and c["claim_kind"] == "DISSOLUTION" \
                and c["claim_status"] not in ("APPROVED", "PAID", "DENIED"):
            invalid_state("All DISSOLUTION refund claims must be decided before finalization")
    for v in DB["vouchers"].values():
        if v.get("_frozen_by_pod_id") == id and v["funding_status"] == "FROZEN":
            invalid_state("All frozen voucher accounts must be released before finalization")
    p["dissolved_at"] = dt_iso(logical_now())
    p["status"] = "DISSOLVED"
    p["posture"] = "CLOSED"
    for s in DB["seats"].values():
        if s["pod_id"] == id and s["seat_status"] == "WITHDRAWN":
            s["seat_status"] = "RELEASED"
            touch(s)
    # families left with zero ENROLLED students -> INACTIVE
    for fam in DB["families"].values():
        if fam["family_status"] != "ACTIVE":
            continue
        has_enrolled = False
        for stu in DB["students"].values():
            if stu["family_id"] != fam["id"]:
                continue
            for s in DB["seats"].values():
                if s["student_id"] == stu["id"] and s["seat_status"] == "ENROLLED":
                    has_enrolled = True
                    break
            if has_enrolled:
                break
        if not has_enrolled:
            fam["family_status"] = "INACTIVE"
            touch(fam)
    touch(p)
    return ok(p)


# ---------------------------------------------------------------------------
# SafetyPolicy
# ---------------------------------------------------------------------------

@bp.post("/pods/<id>/safety-policies")
def create_policy(id):
    auth("PodOperator")
    p = get_or_404("pods", id, "Pod")
    b = body()
    pod_gate(p, block_frozen=False, block_closed=True)
    policy_version = req_int(b, "policy_version", min_v=1)
    existing = [sp["policy_version"] for sp in DB["policies"].values() if sp["pod_id"] == id]
    if existing and policy_version <= max(existing):
        bad_request("policy_version must be monotonically increasing within the pod")
    text = req_str(b, "emergency_plan_text")
    immun = req_enum(b, "immunization_policy", ("REQUIRED", "EXEMPTION_ALLOWED", "NOT_REQUIRED"))
    bgc = req_bool(b, "background_check_required")
    cadence = req_int(b, "drill_cadence_days")
    sp = new_resource()
    sp.update({
        "pod_id": id,
        "policy_version": policy_version,
        "emergency_plan_text": text,
        "immunization_policy": immun,
        "background_check_required": bgc,
        "drill_cadence_days": cadence,
        "policy_status": "DRAFT",
        "approved_at": None,
    })
    DB["policies"][sp["id"]] = sp
    return ok(sp, 201)


@bp.get("/pods/<id>/safety-policies")
def list_pod_policies(id):
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer")
    get_or_404("pods", id, "Pod")
    items = [sp for sp in sorted_items(DB["policies"]) if sp["pod_id"] == id]
    st = request_arg("policy_status")
    if st is not None:
        items = [sp for sp in items if sp["policy_status"] == st]
    return ok_list(items)


@bp.get("/safety-policies/<id>")
def get_policy(id):
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer")
    return ok(get_or_404("policies", id, "SafetyPolicy"))


@bp.get("/safety-policies")
def list_policies():
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer")
    items = sorted_items(DB["policies"])
    pid = request_arg("pod_id")
    if pid is not None:
        items = [sp for sp in items if sp["pod_id"] == pid]
    st = request_arg("policy_status")
    if st is not None:
        items = [sp for sp in items if sp["policy_status"] == st]
    return ok_list(items)


@bp.post("/pods/<id>/safety-policies/<policy_id>/approve")
def approve_policy(id, policy_id):
    auth("PlatformAdmin")
    get_or_404("pods", id, "Pod")
    sp = DB["policies"].get(policy_id)
    if sp is None or sp["pod_id"] != id:
        not_found("SafetyPolicy '%s' does not exist for this pod" % policy_id)
    if sp["policy_status"] != "DRAFT":
        invalid_state("Only a DRAFT safety policy can be approved")
    if len(sp["emergency_plan_text"]) < 200:
        err_safety()
    if not (7 <= sp["drill_cadence_days"] <= 90):
        err_safety()
    for other in DB["policies"].values():
        if other["pod_id"] == id and other["id"] != policy_id and other["policy_status"] == "APPROVED":
            other["policy_status"] = "SUPERSEDED"
            touch(other)
    sp["policy_status"] = "APPROVED"
    sp["approved_at"] = dt_iso(logical_now())
    touch(sp)
    return ok(sp)


# ---------------------------------------------------------------------------
# CurriculumPlan
# ---------------------------------------------------------------------------

@bp.post("/pods/<id>/curriculum-plans")
def create_plan(id):
    auth("PodOperator")
    p = get_or_404("pods", id, "Pod")
    b = body()
    pod_gate(p, block_frozen=False, block_closed=True)
    name = req_str(b, "plan_name")
    bands = b.get("grade_bands_covered")
    if not isinstance(bands, list) or not bands or any(not isinstance(x, str) or x not in GRADE_BANDS for x in bands):
        bad_request("grade_bands_covered must be a non-empty list of grade bands")
    mag = req_bool(b, "multi_age_grouping")
    # PRD 3.2 enforces the 1200-minute weekly floor at plan APPROVAL
    # (ERR_CURRICULUM_INADEQUATE); creation only applies 2.4 format
    # validation (wrong type / non-positive amount -> ERR_INVALID_REQUEST).
    minutes = req_int(b, "total_instructional_minutes_per_week", min_v=1)
    cp = new_resource()
    cp.update({
        "pod_id": id,
        "plan_name": name,
        "grade_bands_covered": list(bands),
        "multi_age_grouping": mag,
        "total_instructional_minutes_per_week": minutes,
        "plan_status": "DRAFT",
        "approved_at": None,
        "approved_safety_policy_id": None,
    })
    DB["plans"][cp["id"]] = cp
    return ok(cp, 201)


def _enrolled_bands(pod_id):
    bands = set()
    for s in DB["seats"].values():
        if s["pod_id"] == pod_id and s["seat_status"] == "ENROLLED":
            stu = DB["students"].get(s["student_id"])
            if stu is not None and stu.get("grade_band"):
                bands.add(stu["grade_band"])
    return bands


def _plan_covers_enrolled(plan):
    return _enrolled_bands(plan["pod_id"]).issubset(set(plan["grade_bands_covered"]))


@bp.get("/pods/<id>/curriculum-plans")
def list_pod_plans(id):
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer", "Guide")
    get_or_404("pods", id, "Pod")
    items = [cp for cp in sorted_items(DB["plans"]) if cp["pod_id"] == id]
    st = request_arg("plan_status")
    if st is not None:
        items = [cp for cp in items if cp["plan_status"] == st]
    return ok_list(items)


@bp.get("/curriculum-plans/<id>")
def get_plan(id):
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer", "Guide")
    return ok(get_or_404("plans", id, "CurriculumPlan"))


@bp.get("/curriculum-plans")
def list_plans():
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer")
    items = sorted_items(DB["plans"])
    pid = request_arg("pod_id")
    if pid is not None:
        items = [cp for cp in items if cp["pod_id"] == pid]
    asp = request_arg("approved_safety_policy_id")
    if asp is not None:
        items = [cp for cp in items if cp.get("approved_safety_policy_id") == asp]
    st = request_arg("plan_status")
    if st is not None:
        items = [cp for cp in items if cp["plan_status"] == st]
    return ok_list(items)


@bp.post("/pods/<id>/curriculum-plans/<plan_id>/submit")
def submit_plan(id, plan_id):
    auth("PodOperator")
    get_or_404("pods", id, "Pod")
    cp = DB["plans"].get(plan_id)
    if cp is None or cp["pod_id"] != id:
        not_found("CurriculumPlan '%s' does not exist for this pod" % plan_id)
    if cp["plan_status"] != "DRAFT":
        invalid_state("Only a DRAFT plan can be submitted")
    if not _plan_covers_enrolled(cp):
        err("ERR_CURRICULUM_INADEQUATE", 422,
            "Plan must cover every grade band present among the pod's ENROLLED seats")
    cp["plan_status"] = "SUBMITTED"
    touch(cp)
    return ok(cp)


@bp.post("/pods/<id>/curriculum-plans/<plan_id>/approve")
def approve_plan(id, plan_id):
    auth("PlatformAdmin")
    get_or_404("pods", id, "Pod")
    cp = DB["plans"].get(plan_id)
    if cp is None or cp["pod_id"] != id:
        not_found("CurriculumPlan '%s' does not exist for this pod" % plan_id)
    if cp["plan_status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED plan can be approved")
    approved = _approved_policy(id)
    if not approved:
        err("ERR_CURRICULUM_INADEQUATE", 422, "Pod has no APPROVED safety policy")
    if cp["total_instructional_minutes_per_week"] < 1200 or not _plan_covers_enrolled(cp):
        err("ERR_CURRICULUM_INADEQUATE", 422,
            "Plan does not meet the 1200-minute floor or grade-band coverage")
    for other in DB["plans"].values():
        if other["pod_id"] == id and other["id"] != plan_id and other["plan_status"] == "APPROVED":
            supersede_plan(other)
    pinned = max(approved, key=lambda sp: sp["policy_version"])
    cp["plan_status"] = "APPROVED"
    cp["approved_at"] = dt_iso(logical_now())
    cp["approved_safety_policy_id"] = pinned["id"]
    touch(cp)
    return ok(cp)


@bp.post("/pods/<id>/curriculum-plans/<plan_id>/revise")
def revise_plan(id, plan_id):
    auth("PodOperator")
    get_or_404("pods", id, "Pod")
    cp = DB["plans"].get(plan_id)
    if cp is None or cp["pod_id"] != id:
        not_found("CurriculumPlan '%s' does not exist for this pod" % plan_id)
    if cp["plan_status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED plan can be revised back to DRAFT")
    cp["plan_status"] = "DRAFT"
    touch(cp)
    return ok(cp)


# ---------------------------------------------------------------------------
# LicensingDetermination
# ---------------------------------------------------------------------------

@bp.post("/pods/<id>/licensing-determinations")
def create_determination(id):
    auth("PodOperator")
    p = get_or_404("pods", id, "Pod")
    b = body()
    kind = req_enum(b, "submission_kind", ("EXEMPTION_CLAIM", "FULL_LICENSE"))
    if p["status"] != "FORMING":
        invalid_state("Pod must be FORMING to submit a licensing determination")
    for d in DB["determinations"].values():
        if d["pod_id"] == id and d["determination_status"] in ("SUBMITTED", "UNDER_REVIEW"):
            invalid_state("Another determination is already SUBMITTED or UNDER_REVIEW for this pod")
    jc = opt_str(b, "jurisdiction_code")
    if jc is None:
        site = DB["sites"].get(p["facility_site_id"])
        jc = site["jurisdiction_code"] if site else None
    if not jc:
        bad_request("jurisdiction_code is required")
    d = new_resource()
    d.update({
        "pod_id": id,
        "jurisdiction_code": jc,
        "submission_kind": kind,
        "determination_status": "SUBMITTED",
        "decided_at": None,
        "revision_number": 0,
        "denial_reason": None,
    })
    DB["determinations"][d["id"]] = d
    p["status"] = "LICENSING_REVIEW"
    p["posture"] = "RESTRICTED"
    touch(p)
    return ok(d, 201)


@bp.get("/pods/<id>/licensing-determinations")
def list_pod_determinations(id):
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer")
    get_or_404("pods", id, "Pod")
    items = [d for d in sorted_items(DB["determinations"]) if d["pod_id"] == id]
    st = request_arg("determination_status")
    if st is not None:
        items = [d for d in items if d["determination_status"] == st]
    return ok_list(items)


@bp.get("/licensing-determinations/<id>")
def get_determination(id):
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer")
    return ok(get_or_404("determinations", id, "LicensingDetermination"))


@bp.get("/licensing-determinations")
def list_determinations():
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer")
    items = sorted_items(DB["determinations"])
    pid = request_arg("pod_id")
    if pid is not None:
        items = [d for d in items if d["pod_id"] == pid]
    st = request_arg("determination_status")
    if st is not None:
        items = [d for d in items if d["determination_status"] == st]
    return ok_list(items)


@bp.post("/pods/<id>/licensing-determinations/<det_id>/begin-review")
def begin_review(id, det_id):
    auth("ComplianceOfficer")
    get_or_404("pods", id, "Pod")
    d = DB["determinations"].get(det_id)
    if d is None or d["pod_id"] != id:
        not_found("LicensingDetermination '%s' does not exist for this pod" % det_id)
    if d["determination_status"] not in ("SUBMITTED", "RESUBMITTED"):
        invalid_state("Determination must be SUBMITTED or RESUBMITTED to begin review")
    d["determination_status"] = "UNDER_REVIEW"
    touch(d)
    return ok(d)


@bp.post("/pods/<id>/licensing-determinations/<det_id>/decide")
def decide_determination(id, det_id):
    auth("ComplianceOfficer")
    p = get_or_404("pods", id, "Pod")
    d = DB["determinations"].get(det_id)
    if d is None or d["pod_id"] != id:
        not_found("LicensingDetermination '%s' does not exist for this pod" % det_id)
    b = body()
    decision = req_enum(b, "decision", ("EXEMPT_GRANTED", "LICENSE_GRANTED", "LICENSE_REQUIRED", "DENIED"))
    if d["determination_status"] != "UNDER_REVIEW":
        invalid_state("Determination must be UNDER_REVIEW to decide")

    if decision == "EXEMPT_GRANTED":
        site = DB["sites"].get(p["facility_site_id"])
        if p["seat_capacity"] > 10 or site is None or site["zoning_class"] not in EXEMPT_ZONING:
            err("ERR_EXEMPTION_NOT_ELIGIBLE", 422,
                "Pod/FacilitySite does not meet licensing-exemption criteria")
        d["determination_status"] = "EXEMPT_GRANTED"
        d["decided_at"] = dt_iso(logical_now())
        touch(d)
        try_activate_pod(p)
    elif decision == "LICENSE_GRANTED":
        if d["submission_kind"] != "FULL_LICENSE":
            invalid_state("LICENSE_GRANTED requires submission_kind == FULL_LICENSE")
        d["determination_status"] = "LICENSE_GRANTED"
        d["decided_at"] = dt_iso(logical_now())
        touch(d)
        try_activate_pod(p)
    elif decision == "LICENSE_REQUIRED":
        d["determination_status"] = "LICENSE_REQUIRED"
        d["decided_at"] = dt_iso(logical_now())
        touch(d)
        if p["status"] == "LICENSING_REVIEW":
            p["status"] = "FORMING"
            refresh_posture(p)
            touch(p)
    else:  # DENIED
        reason = opt_str(b, "denial_reason")
        if not reason:
            bad_request("denial_reason is required when decision is DENIED")
        d["determination_status"] = "DENIED"
        d["denial_reason"] = reason
        d["decided_at"] = dt_iso(logical_now())
        touch(d)
        if p["status"] == "LICENSING_REVIEW":
            p["status"] = "FORMING"
            p["compliance_flag"] = "AT_RISK"
            refresh_posture(p)
            touch(p)
    return ok(d)


@bp.post("/pods/<id>/licensing-determinations/<det_id>/resubmit")
def resubmit_determination(id, det_id):
    auth("PodOperator")
    get_or_404("pods", id, "Pod")
    d = DB["determinations"].get(det_id)
    if d is None or d["pod_id"] != id:
        not_found("LicensingDetermination '%s' does not exist for this pod" % det_id)
    if d["determination_status"] not in ("DENIED", "LICENSE_REQUIRED"):
        invalid_state("Only DENIED or LICENSE_REQUIRED determinations can be resubmitted")
    b = body()
    rev = req_int(b, "revision_number")
    if rev != d["revision_number"] + 1:
        bad_request("revision_number must be exactly one greater than the current revision_number")
    if d["determination_status"] == "LICENSE_REQUIRED":
        kind = req_enum(b, "submission_kind", ("EXEMPTION_CLAIM", "FULL_LICENSE"))
        if kind != "FULL_LICENSE":
            bad_request("Resubmitting a LICENSE_REQUIRED determination requires submission_kind FULL_LICENSE")
        d["submission_kind"] = "FULL_LICENSE"
    d["revision_number"] = d["revision_number"] + 1
    d["determination_status"] = "RESUBMITTED"
    touch(d)
    # the pod re-enters licensing review so a later grant can cascade to ACTIVE
    p = DB["pods"].get(id)
    if p is not None and p["status"] == "FORMING":
        p["status"] = "LICENSING_REVIEW"
        p["posture"] = "RESTRICTED"
        touch(p)
    return ok(d)
