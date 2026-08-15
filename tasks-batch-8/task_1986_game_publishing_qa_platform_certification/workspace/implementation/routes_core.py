"""Clock, ops-run, titles, vendors, test plans, assignments routes."""

from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import require_role
from response import success_object, success_list, success_empty
import helpers as H

bp = Blueprint("core", __name__)

PLATFORMS = ("PS5", "XSX", "SWITCH2", "PC")


def _body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.", 400)
    return b


def _req_str(b, field):
    v = b.get(field)
    if v is None or not isinstance(v, str) or not v:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} is required and must be a string.", 400)
    return v


def _opt_bool(b, field, default=False):
    v = b.get(field, default)
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be a boolean.", 400)
    return v


# ---------------- clock & ops ----------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role("PlatformAdmin")
    b = _body()
    to = b.get("to_iso8601")
    dt = H.parse_iso_dt(to, "to_iso8601")
    db.clock = dt
    return success_empty(200)


@bp.route("/qa-cert/ops/run", methods=["POST"])
def ops_run():
    require_role("PlatformAdmin")
    now = db.clock
    for w in db.windows.values():
        if w["status"] in ("RESERVED", "CONFIRMED") and w["_end"] < now:
            w["status"] = "EXPIRED"
            H.touch(w)
    sla_hours = {"BLOCKER": 24, "CRITICAL": 72, "MAJOR": 168, "MINOR": 720}
    from datetime import timedelta
    for bug in db.bugs.values():
        if bug["status"] == "OPEN":
            sev = bug["severity"]
            if sev in sla_hours:
                if now > bug["_created"] + timedelta(hours=sla_hours[sev]):
                    if not bug["sla_breached"]:
                        bug["sla_breached"] = True
                        H.touch(bug)
    return success_empty(200)


# ---------------- titles ----------------

@bp.route("/qa-cert/titles", methods=["POST"])
def create_title():
    require_role("ReleaseManager")
    b = _body()
    title_code = _req_str(b, "title_code")
    name = _req_str(b, "name")
    platform_codes = b.get("platform_codes")
    if not isinstance(platform_codes, list) or len(platform_codes) == 0:
        raise ApiError("ERR_INVALID_REQUEST", "platform_codes must be a non-empty array.", 400)
    for pc in platform_codes:
        if pc not in PLATFORMS:
            raise ApiError("ERR_INVALID_REQUEST", "platform_codes has an unknown platform.", 400)
    target_launch_date = _req_str(b, "target_launch_date")
    H.parse_iso_date(target_launch_date, "target_launch_date")
    budget = b.get("cert_budget_total_cents")
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 0:
        raise ApiError("ERR_INVALID_REQUEST", "cert_budget_total_cents must be an integer >= 0.", 400)
    for t in db.titles.values():
        if t["title_code"] == title_code:
            raise ApiError("ERR_INVALID_REQUEST", "title_code must be unique.", 400)
    t = {
        "title_code": title_code,
        "name": name,
        "platform_codes": platform_codes,
        "target_launch_date": target_launch_date,
        "cert_budget_total_cents": budget,
        "hotfix_rollback_count": 0,
        "embargoed": False,
        "embargo_reason": None,
        "status": "CONCEPT",
    }
    H.init_common(t)
    db.titles[t["id"]] = t
    return success_object(H.title_view(t), 201)


@bp.route("/qa-cert/titles/<titleId>", methods=["GET"])
def get_title(titleId):
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    t = db.titles.get(titleId)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "Title not found.", 404)
    return success_object(H.title_view(t))


@bp.route("/qa-cert/titles", methods=["GET"])
def list_titles():
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    title_code = request.args.get("title_code")
    status = request.args.get("status")
    items = [t for t in db.titles.values()]
    if title_code is not None:
        items = [t for t in items if t["title_code"] == title_code]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items.sort(key=lambda x: (x["_created"], x["id"]))
    limit, offset = H.get_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([H.title_view(t) for t in page], limit, offset, total)


@bp.route("/qa-cert/titles/<titleId>/transition", methods=["POST"])
def title_transition(titleId):
    require_role("ReleaseManager")
    t = db.titles.get(titleId)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "Title not found.", 404)
    b = _body()
    to_status = _req_str(b, "to_status")
    linear = {
        "CONCEPT": "IN_DEVELOPMENT",
        "IN_DEVELOPMENT": "CERTIFICATION",
        "CERTIFICATION": "CERT_APPROVED",
        "CERT_APPROVED": "LAUNCHED",
        "LAUNCHED": "SUNSET",
    }
    if to_status not in ("IN_DEVELOPMENT", "CERTIFICATION", "CERT_APPROVED", "LAUNCHED", "SUNSET"):
        raise ApiError("ERR_INVALID_REQUEST", "Unknown to_status.", 400)
    expected_from = None
    for k, v in linear.items():
        if v == to_status:
            expected_from = k
            break
    if t["status"] != expected_from:
        raise ApiError("ERR_INVALID_STATE", "Illegal title transition.", 409)
    if to_status == "CERT_APPROVED":
        ok = any(p["title_id"] == t["id"] and p["status"] == "APPROVED"
                 for p in db.packages.values())
        if not ok:
            raise ApiError("ERR_NO_APPROVED_PACKAGE",
                           "Title cannot reach CERT_APPROVED without an APPROVED package.", 409)
    if to_status == "LAUNCHED":
        if H.open_blocker_count(t["id"]) != 0:
            raise ApiError("ERR_OPEN_BLOCKERS_EXIST", "Open BLOCKER bugs exist.", 409)
    t["status"] = to_status
    H.touch(t)
    return success_object(H.title_view(t))


@bp.route("/qa-cert/titles/<titleId>/embargo", methods=["POST"])
def title_embargo(titleId):
    require_role("ComplianceManager")
    t = db.titles.get(titleId)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "Title not found.", 404)
    b = _body()
    embargoed = b.get("embargoed")
    if not isinstance(embargoed, bool):
        raise ApiError("ERR_INVALID_REQUEST", "embargoed must be a boolean.", 400)
    reason = b.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ApiError("ERR_INVALID_REQUEST", "reason must be a string.", 400)
    t["embargoed"] = embargoed
    t["embargo_reason"] = reason
    H.touch(t)
    return success_object(H.title_view(t))


# ---------------- vendors ----------------

@bp.route("/qa-cert/vendors", methods=["POST"])
def create_vendor():
    require_role("VendorManager")
    b = _body()
    name = _req_str(b, "name")
    cap = b.get("weekly_capacity_hours")
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1 or cap > 10000:
        raise ApiError("ERR_INVALID_REQUEST", "weekly_capacity_hours must be an integer in 1..10000.", 400)
    rate = b.get("cost_rate_cents_per_hour")
    if not isinstance(rate, int) or isinstance(rate, bool) or rate < 1:
        raise ApiError("ERR_INVALID_REQUEST", "cost_rate_cents_per_hour must be an integer >= 1.", 400)
    for v in db.vendors.values():
        if v["name"] == name:
            raise ApiError("ERR_INVALID_REQUEST", "Vendor name must be unique.", 400)
    v = {
        "name": name,
        "weekly_capacity_hours": cap,
        "cost_rate_cents_per_hour": rate,
        "status": "ACTIVE",
    }
    H.init_common(v)
    db.vendors[v["id"]] = v
    return success_object(H.vendor_view(v), 201)


@bp.route("/qa-cert/vendors/<vendorId>", methods=["GET"])
def get_vendor(vendorId):
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    v = db.vendors.get(vendorId)
    if v is None:
        raise ApiError("ERR_NOT_FOUND", "Vendor not found.", 404)
    return success_object(H.vendor_view(v))


@bp.route("/qa-cert/vendors", methods=["GET"])
def list_vendors():
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    status = request.args.get("status")
    items = list(db.vendors.values())
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items.sort(key=lambda x: (x["_created"], x["id"]))
    limit, offset = H.get_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([H.vendor_view(v) for v in page], limit, offset, total)


@bp.route("/qa-cert/vendors/<vendorId>/transition", methods=["POST"])
def vendor_transition(vendorId):
    require_role("VendorManager")
    v = db.vendors.get(vendorId)
    if v is None:
        raise ApiError("ERR_NOT_FOUND", "Vendor not found.", 404)
    b = _body()
    to_status = _req_str(b, "to_status")
    legal = {
        ("ACTIVE", "SUSPENDED"),
        ("SUSPENDED", "ACTIVE"),
        ("ACTIVE", "TERMINATED"),
        ("SUSPENDED", "TERMINATED"),
    }
    if to_status not in ("SUSPENDED", "ACTIVE", "TERMINATED"):
        raise ApiError("ERR_INVALID_REQUEST", "Unknown to_status.", 400)
    if (v["status"], to_status) not in legal:
        raise ApiError("ERR_INVALID_STATE", "Illegal vendor transition.", 409)
    v["status"] = to_status
    H.touch(v)
    if to_status == "TERMINATED":
        for a in list(db.assignments.values()):
            if a["vendor_id"] == v["id"] and a["status"] in ("SCHEDULED", "IN_PROGRESS"):
                H.cancel_assignment_cascade(a)
    return success_object(H.vendor_view(v))


@bp.route("/qa-cert/vendors/<vendorId>/invoice", methods=["GET"])
def vendor_invoice(vendorId):
    require_role("VendorManager")
    v = db.vendors.get(vendorId)
    if v is None:
        raise ApiError("ERR_NOT_FOUND", "Vendor not found.", 404)
    from decimal import Decimal, ROUND_HALF_UP
    week_raw = request.args.get("week_start_date")
    if week_raw is None:
        week = H.monday_of_current_week()
    else:
        week = H.parse_iso_date(week_raw, "week_start_date")
    variant = request.args.get("variant", "FINAL")
    if variant not in ("PROVISIONAL", "FINAL"):
        raise ApiError("ERR_INVALID_REQUEST", "variant must be PROVISIONAL or FINAL.", 400)
    week_str = week.isoformat()
    rate = v["cost_rate_cents_per_hour"]
    subtotal = 0
    line_count = 0
    if variant == "PROVISIONAL":
        for a in db.assignments.values():
            if a["vendor_id"] == v["id"] and a["week_start_date"] == week_str and \
                    a["status"] in ("SCHEDULED", "IN_PROGRESS", "DONE"):
                subtotal += a["reserved_hours"] * rate
                line_count += 1
        clawback = 0
    else:
        for a in db.assignments.values():
            if a["vendor_id"] == v["id"] and a["week_start_date"] == week_str and \
                    a["status"] == "DONE":
                regular = min(a["actual_hours"], a["reserved_hours"])
                ot = max(0, a["actual_hours"] - a["reserved_hours"])
                line = int(Decimal(regular * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                line += int((Decimal(ot) * Decimal(rate) * Decimal("1.5")).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP))
                subtotal += line
                line_count += 1
        escapes = 0
        for bug in db.bugs.values():
            if bug.get("found_by_vendor_id") == v["id"] and bug.get("found_post_launch") and \
                    bug["status"] not in ("DUPLICATE", "WONT_FIX") and \
                    bug["_created"] <= db.clock:
                escapes += 1
        clawback_pct = min(50, 10 * escapes)
        clawback = int((Decimal(subtotal) * Decimal(clawback_pct) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
    total = subtotal - clawback
    return success_object({
        "week_start_date": week_str,
        "variant": variant,
        "line_count": line_count,
        "subtotal_cents": subtotal,
        "clawback_cents": clawback,
        "total_cents": total,
    })


# ---------------- test plans ----------------

@bp.route("/qa-cert/test-plans", methods=["POST"])
def create_plan():
    require_role("QALead")
    b = _body()
    title_id = _req_str(b, "title_id")
    t = db.titles.get(title_id)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "Title not found.", 404)
    platform_code = _req_str(b, "platform_code")
    if platform_code not in PLATFORMS:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown platform_code.", 400)
    for p in db.test_plans.values():
        if p["title_id"] == title_id and p["platform_code"] == platform_code and \
                p["status"] != "ARCHIVED":
            raise ApiError("ERR_DUPLICATE_TEST_PLAN",
                           "A non-ARCHIVED plan already exists for (title, platform).", 409)
    p = {
        "title_id": title_id,
        "platform_code": platform_code,
        "status": "DRAFT",
        "entries": [],
    }
    H.init_common(p)
    db.test_plans[p["id"]] = p
    return success_object(H.plan_view(p), 201)


@bp.route("/qa-cert/test-plans/<planId>", methods=["GET"])
def get_plan(planId):
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    p = db.test_plans.get(planId)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "Test plan not found.", 404)
    return success_object(H.plan_view(p))


@bp.route("/qa-cert/test-plans", methods=["GET"])
def list_plans():
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    title_id = request.args.get("title_id")
    platform_code = request.args.get("platform_code")
    status = request.args.get("status")
    items = list(db.test_plans.values())
    if title_id is not None:
        items = [p for p in items if p["title_id"] == title_id]
    if platform_code is not None:
        items = [p for p in items if p["platform_code"] == platform_code]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda x: (x["_created"], x["id"]))
    limit, offset = H.get_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([H.plan_view(p) for p in page], limit, offset, total)


@bp.route("/qa-cert/test-plans/<planId>/entries", methods=["POST"])
def add_plan_entry(planId):
    require_role("QALead")
    p = db.test_plans.get(planId)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "Test plan not found.", 404)
    b = _body()
    feature_area = _req_str(b, "feature_area")
    platform_layer = _req_str(b, "platform_layer")
    is_cert_blocker = b.get("is_cert_blocker")
    if not isinstance(is_cert_blocker, bool):
        raise ApiError("ERR_INVALID_REQUEST", "is_cert_blocker must be a boolean.", 400)
    required_coverage_hours = b.get("required_coverage_hours")
    if not isinstance(required_coverage_hours, int) or isinstance(required_coverage_hours, bool) \
            or required_coverage_hours < 0:
        raise ApiError("ERR_INVALID_REQUEST", "required_coverage_hours must be an integer >= 0.", 400)
    if p["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_DRAFT", "Entries can only be added while the plan is DRAFT.", 409)
    for e in p["entries"]:
        if e["feature_area"] == feature_area:
            raise ApiError("ERR_DUPLICATE_FEATURE_AREA", "feature_area already present.", 409)
    p["entries"].append({
        "feature_area": feature_area,
        "platform_layer": platform_layer,
        "is_cert_blocker": is_cert_blocker,
        "required_coverage_hours": required_coverage_hours,
    })
    H.touch(p)
    return success_object(H.plan_view(p), 201)


@bp.route("/qa-cert/test-plans/<planId>/transition", methods=["POST"])
def plan_transition(planId):
    require_role("QALead")
    p = db.test_plans.get(planId)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "Test plan not found.", 404)
    b = _body()
    to_status = _req_str(b, "to_status")
    if to_status not in ("IN_REVIEW", "APPROVED", "DRAFT", "ARCHIVED"):
        raise ApiError("ERR_INVALID_REQUEST", "Unknown to_status.", 400)
    cur = p["status"]
    if to_status == "IN_REVIEW":
        if cur != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Plan must be DRAFT.", 409)
        if len(p["entries"]) < 1:
            raise ApiError("ERR_NO_PLAN_ENTRIES", "Plan cannot enter IN_REVIEW with zero entries.", 409)
    elif to_status == "APPROVED":
        if cur != "IN_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "Plan must be IN_REVIEW.", 409)
        view = H.plan_view(p)
        for e in view["entries"]:
            if e["is_cert_blocker"] and e["coverage_status"] != "COVERED":
                raise ApiError("ERR_REQUIRED_COVERAGE_MISSING",
                               "Every cert-blocker entry must be COVERED.", 409)
    elif to_status == "DRAFT":
        if cur != "IN_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "Plan must be IN_REVIEW.", 409)
    elif to_status == "ARCHIVED":
        if cur not in ("DRAFT", "IN_REVIEW"):
            raise ApiError("ERR_INVALID_STATE", "Plan must be DRAFT or IN_REVIEW.", 409)
    p["status"] = to_status
    H.touch(p)
    return success_object(H.plan_view(p))


# ---------------- assignments ----------------

@bp.route("/qa-cert/assignments", methods=["POST"])
def create_assignment():
    require_role("VendorManager")
    b = _body()
    vendor_id = _req_str(b, "vendor_id")
    plan_id = _req_str(b, "plan_id")
    feature_area = _req_str(b, "feature_area")
    week_start_date = _req_str(b, "week_start_date")
    reserved_hours = b.get("reserved_hours")
    if not isinstance(reserved_hours, int) or isinstance(reserved_hours, bool) or \
            reserved_hours < 1 or reserved_hours > 168:
        raise ApiError("ERR_INVALID_REQUEST", "reserved_hours must be an integer in 1..168.", 400)
    v = db.vendors.get(vendor_id)
    if v is None:
        raise ApiError("ERR_NOT_FOUND", "Vendor not found.", 404)
    p = db.test_plans.get(plan_id)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "Test plan not found.", 404)
    if v["status"] != "ACTIVE":
        raise ApiError("ERR_VENDOR_NOT_ACTIVE", "Vendor must be ACTIVE.", 409)
    if p["status"] in ("LOCKED", "ARCHIVED"):
        raise ApiError("ERR_INVALID_STATE", "Plan is not assignable.", 409)
    entry = None
    for e in p["entries"]:
        if e["feature_area"] == feature_area:
            entry = e
            break
    if entry is None:
        raise ApiError("ERR_ENTRY_NOT_FOUND", "No embedded entry with the given feature_area.", 404)
    week = H.parse_iso_date(week_start_date, "week_start_date")
    if week.weekday() != 0:
        raise ApiError("ERR_WEEK_START_NOT_MONDAY", "week_start_date must be a Monday.", 422)
    committed = 0
    for a in db.assignments.values():
        if a["vendor_id"] == v["id"] and a["week_start_date"] == week.isoformat() and \
                a["status"] in ("SCHEDULED", "IN_PROGRESS"):
            committed += a["reserved_hours"]
    if committed + reserved_hours > v["weekly_capacity_hours"]:
        raise ApiError("ERR_VENDOR_CAPACITY_EXCEEDED", "Weekly capacity exceeded.", 409)
    a = {
        "vendor_id": vendor_id,
        "plan_id": plan_id,
        "feature_area": feature_area,
        "week_start_date": week.isoformat(),
        "reserved_hours": reserved_hours,
        "actual_hours": None,
        "status": "SCHEDULED",
    }
    H.init_common(a)
    db.assignments[a["id"]] = a
    return success_object(H.public(a), 201)


@bp.route("/qa-cert/assignments/<assignmentId>", methods=["GET"])
def get_assignment(assignmentId):
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    a = db.assignments.get(assignmentId)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "Assignment not found.", 404)
    return success_object(H.public(a))


@bp.route("/qa-cert/assignments", methods=["GET"])
def list_assignments():
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    vendor_id = request.args.get("vendor_id")
    plan_id = request.args.get("plan_id")
    week_start_date = request.args.get("week_start_date")
    status = request.args.get("status")
    items = list(db.assignments.values())
    if vendor_id is not None:
        items = [a for a in items if a["vendor_id"] == vendor_id]
    if plan_id is not None:
        items = [a for a in items if a["plan_id"] == plan_id]
    if week_start_date is not None:
        items = [a for a in items if a["week_start_date"] == week_start_date]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda x: (x["_created"], x["id"]))
    limit, offset = H.get_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([H.public(a) for a in page], limit, offset, total)


@bp.route("/qa-cert/assignments/<assignmentId>/transition", methods=["POST"])
def assignment_transition(assignmentId):
    require_role("VendorManager")
    a = db.assignments.get(assignmentId)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "Assignment not found.", 404)
    b = _body()
    to_status = _req_str(b, "to_status")
    if to_status not in ("IN_PROGRESS", "DONE", "CANCELLED"):
        raise ApiError("ERR_INVALID_REQUEST", "Unknown to_status.", 400)
    if to_status == "IN_PROGRESS":
        if a["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Assignment must be SCHEDULED.", 409)
        a["status"] = "IN_PROGRESS"
        H.touch(a)
    elif to_status == "DONE":
        if a["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE", "Assignment must be IN_PROGRESS.", 409)
        actual = b.get("actual_hours")
        if not isinstance(actual, int) or isinstance(actual, bool) or actual < 0:
            raise ApiError("ERR_INVALID_REQUEST", "actual_hours must be an integer >= 0.", 400)
        a["actual_hours"] = actual
        a["status"] = "DONE"
        H.touch(a)
    elif to_status == "CANCELLED":
        if a["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            raise ApiError("ERR_INVALID_STATE", "Assignment must be SCHEDULED or IN_PROGRESS.", 409)
        H.cancel_assignment_cascade(a)
    return success_object(H.public(a))
