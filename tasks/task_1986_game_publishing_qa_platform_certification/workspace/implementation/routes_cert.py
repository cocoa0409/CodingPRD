"""Builds, bugs, submission packages, checklists, findings routes."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import require_role
from response import success_object, success_list
import helpers as H

bp = Blueprint("cert", __name__)

PLATFORMS = ("PS5", "XSX", "SWITCH2", "PC")
PATCH_CLASSES = ("BASE", "DAY_ONE_PATCH", "HOTFIX")
BUG_SEVERITIES = ("BLOCKER", "CRITICAL", "MAJOR", "MINOR", "TRIVIAL")
BUG_CATEGORIES = ("GAMEPLAY", "AUDIO", "GRAPHICS", "NETWORK", "COMPLIANCE",
                  "LOCALIZATION", "PERFORMANCE")
BLOCKER_OPEN_STATUSES = ("OPEN", "TRIAGED", "IN_PROGRESS", "REOPENED")

BASE_FEE_CENTS = {"PS5": 120000, "XSX": 120000, "SWITCH2": 90000, "PC": 60000}
FEE_CAP_CENTS = {"PS5": 250000, "XSX": 250000, "SWITCH2": 200000, "PC": 150000}

TRC_CATALOG = {
    "PS5": [
        ("TRC-PS-01", "REQUIRED", True),
        ("TRC-PS-02", "REQUIRED", False),
        ("TRC-PS-03", "REQUIRED", False),
        ("TRC-PS-04", "RECOMMENDED", False),
    ],
    "XSX": [
        ("XR-XB-01", "REQUIRED", True),
        ("XR-XB-02", "REQUIRED", False),
        ("XR-XB-03", "RECOMMENDED", False),
    ],
    "SWITCH2": [
        ("LOT-NS-01", "REQUIRED", False),
        ("LOT-NS-02", "REQUIRED", False),
    ],
    "PC": [
        ("ST-PC-01", "REQUIRED", True),
        ("ST-PC-02", "RECOMMENDED", False),
    ],
}

PLATFORM_TERRITORY = {"PS5": "ESRB", "XSX": "ESRB", "SWITCH2": "CERO", "PC": "USK"}


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


# ---------------- blocker cascade ----------------

def _withdraw_package_system(pkg):
    """System withdrawal: cause SYSTEM_BUILD_INVALIDATED, refund escrow."""
    pkg["withdrawn_cause"] = "SYSTEM_BUILD_INVALIDATED"
    pkg["status"] = "WITHDRAWN"
    H.touch(pkg)
    H.maybe_unlock_plan(pkg["test_plan_id"])


def _release_launch_windows(title_id, platform_code):
    for w in db.windows.values():
        if w["title_id"] == title_id and w["platform_code"] == platform_code and \
                w["kind"] == "LAUNCH" and w["status"] in ("RESERVED", "CONFIRMED"):
            w["status"] = "RELEASED"
            H.touch(w)


def _build_demote_cascade(build):
    """CANDIDATE -> IN_TEST plus package withdrawal + LAUNCH window release."""
    if build["status"] != "CANDIDATE":
        return
    build["status"] = "IN_TEST"
    H.touch(build)
    for pkg in list(db.packages.values()):
        if pkg["build_id"] == build["id"] and pkg["status"] in ("ASSEMBLING", "SUBMITTED", "IN_REVIEW"):
            _withdraw_package_system(pkg)
    _release_launch_windows(build["title_id"], build["platform_code"])


def _build_retire_cascade(build):
    """CANDIDATE -> RETIRED plus same package/window cascade."""
    build["status"] = "RETIRED"
    H.touch(build)
    for pkg in list(db.packages.values()):
        if pkg["build_id"] == build["id"] and pkg["status"] in ("ASSEMBLING", "SUBMITTED", "IN_REVIEW"):
            _withdraw_package_system(pkg)
    _release_launch_windows(build["title_id"], build["platform_code"])


def _maybe_blocker_cascade(bug):
    """Fire hop 1 if bug is effectively BLOCKER-open and its build is CANDIDATE."""
    if bug["severity"] == "BLOCKER" and bug["status"] in BLOCKER_OPEN_STATUSES:
        build = db.builds.get(bug["build_id"])
        if build is not None and build["status"] == "CANDIDATE":
            _build_demote_cascade(build)


# ---------------- builds ----------------

@bp.route("/qa-cert/builds", methods=["POST"])
def create_build():
    require_role("QALead")
    b = _body()
    title_id = _req_str(b, "title_id")
    t = db.titles.get(title_id)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "Title not found.", 404)
    platform_code = _req_str(b, "platform_code")
    if platform_code not in PLATFORMS:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown platform_code.", 400)
    version_string = _req_str(b, "version_string")
    patch_class = b.get("patch_class", "BASE")
    if patch_class not in PATCH_CLASSES:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown patch_class.", 400)
    for bd in db.builds.values():
        if bd["title_id"] == title_id and bd["platform_code"] == platform_code and \
                bd["version_string"] == version_string:
            raise ApiError("ERR_DUPLICATE_BUILD_VERSION",
                           "version_string already used for (title, platform).", 409)
    bd = {
        "title_id": title_id,
        "platform_code": platform_code,
        "version_string": version_string,
        "patch_class": patch_class,
        "status": "RECEIVED",
    }
    H.init_common(bd)
    db.builds[bd["id"]] = bd
    return success_object(H.public(bd), 201)


@bp.route("/qa-cert/builds/<buildId>", methods=["GET"])
def get_build(buildId):
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    bd = db.builds.get(buildId)
    if bd is None:
        raise ApiError("ERR_NOT_FOUND", "Build not found.", 404)
    return success_object(H.public(bd))


@bp.route("/qa-cert/builds", methods=["GET"])
def list_builds():
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    title_id = request.args.get("title_id")
    platform_code = request.args.get("platform_code")
    status = request.args.get("status")
    items = list(db.builds.values())
    if title_id is not None:
        items = [x for x in items if x["title_id"] == title_id]
    if platform_code is not None:
        items = [x for x in items if x["platform_code"] == platform_code]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    items.sort(key=lambda x: (x["_created"], x["id"]))
    limit, offset = H.get_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([H.public(x) for x in page], limit, offset, total)


@bp.route("/qa-cert/builds/<buildId>/transition", methods=["POST"])
def build_transition(buildId):
    require_role("QALead")
    bd = db.builds.get(buildId)
    if bd is None:
        raise ApiError("ERR_NOT_FOUND", "Build not found.", 404)
    b = _body()
    to_status = _req_str(b, "to_status")
    if to_status not in ("IN_TEST", "TEST_PASSED", "TEST_FAILED", "CANDIDATE", "RETIRED"):
        raise ApiError("ERR_INVALID_REQUEST", "Unknown to_status.", 400)
    cur = bd["status"]
    if to_status == "IN_TEST":
        if cur not in ("RECEIVED", "TEST_FAILED", "CANDIDATE"):
            raise ApiError("ERR_INVALID_STATE", "Illegal build transition.", 409)
        if cur == "CANDIDATE":
            _build_demote_cascade(bd)
        else:
            bd["status"] = "IN_TEST"
            H.touch(bd)
    elif to_status == "TEST_PASSED":
        if cur != "IN_TEST":
            raise ApiError("ERR_INVALID_STATE", "Build must be IN_TEST.", 409)
        bd["status"] = "TEST_PASSED"
        H.touch(bd)
    elif to_status == "TEST_FAILED":
        if cur != "IN_TEST":
            raise ApiError("ERR_INVALID_STATE", "Build must be IN_TEST.", 409)
        bd["status"] = "TEST_FAILED"
        H.touch(bd)
    elif to_status == "CANDIDATE":
        if cur != "TEST_PASSED":
            raise ApiError("ERR_INVALID_STATE", "Build must be TEST_PASSED.", 409)
        for bug in db.bugs.values():
            if bug["build_id"] == bd["id"] and bug["severity"] == "BLOCKER" and \
                    bug["status"] in BLOCKER_OPEN_STATUSES:
                raise ApiError("ERR_OPEN_BLOCKERS_EXIST", "Open BLOCKER bugs on this build.", 409)
        bd["status"] = "CANDIDATE"
        H.touch(bd)
    elif to_status == "RETIRED":
        if cur != "CANDIDATE":
            raise ApiError("ERR_INVALID_STATE", "Build must be CANDIDATE.", 409)
        _build_retire_cascade(bd)
    return success_object(H.public(bd))


# ---------------- bugs ----------------

@bp.route("/qa-cert/bugs", methods=["POST"])
def create_bug():
    require_role("QALead")
    b = _body()
    title_id = _req_str(b, "title_id")
    t = db.titles.get(title_id)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "Title not found.", 404)
    build_id = _req_str(b, "build_id")
    bd = db.builds.get(build_id)
    if bd is None:
        raise ApiError("ERR_NOT_FOUND", "Build not found.", 404)
    severity = _req_str(b, "severity")
    if severity not in BUG_SEVERITIES:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown severity.", 400)
    category = _req_str(b, "category")
    if category not in BUG_CATEGORIES:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown category.", 400)
    found_by_vendor_id = b.get("found_by_vendor_id")
    if found_by_vendor_id is not None:
        if not isinstance(found_by_vendor_id, str):
            raise ApiError("ERR_INVALID_REQUEST", "found_by_vendor_id must be a string.", 400)
        if db.vendors.get(found_by_vendor_id) is None:
            raise ApiError("ERR_NOT_FOUND", "Vendor not found.", 404)
    found_post_launch = b.get("found_post_launch", False)
    if not isinstance(found_post_launch, bool):
        raise ApiError("ERR_INVALID_REQUEST", "found_post_launch must be a boolean.", 400)
    regression_of_id = b.get("regression_of_id")
    if regression_of_id is not None:
        if not isinstance(regression_of_id, str):
            raise ApiError("ERR_INVALID_REQUEST", "regression_of_id must be a string.", 400)
        target = db.bugs.get(regression_of_id)
        if target is None:
            raise ApiError("ERR_NOT_FOUND", "Regression target bug not found.", 404)
    if bd["title_id"] != title_id:
        raise ApiError("ERR_BUILD_TITLE_MISMATCH", "Build belongs to a different title.", 422)
    if regression_of_id is not None:
        target = db.bugs[regression_of_id]
        if target["title_id"] != title_id or target["status"] not in ("RESOLVED", "VERIFIED", "CLOSED"):
            raise ApiError("ERR_REGRESSION_TARGET_NOT_CLOSED",
                           "regression_of_id must reference a bug of the same title in "
                           "RESOLVED, VERIFIED, or CLOSED.", 422)
    bug = {
        "title_id": title_id,
        "build_id": build_id,
        "severity": severity,
        "category": category,
        "found_by_vendor_id": found_by_vendor_id,
        "regression_of_id": regression_of_id,
        "is_regression": regression_of_id is not None,
        "found_post_launch": found_post_launch,
        "sla_breached": False,
        "reopened_count": 0,
        "status": "OPEN",
    }
    H.init_common(bug)
    db.bugs[bug["id"]] = bug
    _maybe_blocker_cascade(bug)
    return success_object(H.public(bug), 201)


@bp.route("/qa-cert/bugs/<bugId>", methods=["GET"])
def get_bug(bugId):
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    bug = db.bugs.get(bugId)
    if bug is None:
        raise ApiError("ERR_NOT_FOUND", "Bug not found.", 404)
    return success_object(H.public(bug))


@bp.route("/qa-cert/bugs", methods=["GET"])
def list_bugs():
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    title_id = request.args.get("title_id")
    build_id = request.args.get("build_id")
    severity = request.args.get("severity")
    status = request.args.get("status")
    found_by_vendor_id = request.args.get("found_by_vendor_id")
    regression_of_id = request.args.get("regression_of_id")
    items = list(db.bugs.values())
    if title_id is not None:
        items = [x for x in items if x["title_id"] == title_id]
    if build_id is not None:
        items = [x for x in items if x["build_id"] == build_id]
    if severity is not None:
        items = [x for x in items if x["severity"] == severity]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    if found_by_vendor_id is not None:
        items = [x for x in items if x.get("found_by_vendor_id") == found_by_vendor_id]
    if regression_of_id is not None:
        items = [x for x in items if x.get("regression_of_id") == regression_of_id]
    items.sort(key=lambda x: (x["_created"], x["id"]))
    limit, offset = H.get_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([H.public(x) for x in page], limit, offset, total)


@bp.route("/qa-cert/bugs/<bugId>/triage", methods=["POST"])
def triage_bug(bugId):
    require_role("QALead")
    bug = db.bugs.get(bugId)
    if bug is None:
        raise ApiError("ERR_NOT_FOUND", "Bug not found.", 404)
    b = _body()
    severity = _req_str(b, "severity")
    if severity not in BUG_SEVERITIES:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown severity.", 400)
    category = b.get("category")
    if category is not None:
        if category not in BUG_CATEGORIES:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown category.", 400)
    if bug["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Bug must be OPEN to triage.", 409)
    bug["severity"] = severity
    if category is not None:
        bug["category"] = category
    bug["status"] = "TRIAGED"
    H.touch(bug)
    _maybe_blocker_cascade(bug)
    return success_object(H.public(bug))


@bp.route("/qa-cert/bugs/<bugId>/transition", methods=["POST"])
def bug_transition(bugId):
    require_role("QALead")
    bug = db.bugs.get(bugId)
    if bug is None:
        raise ApiError("ERR_NOT_FOUND", "Bug not found.", 404)
    b = _body()
    to_status = _req_str(b, "to_status")
    if to_status not in ("IN_PROGRESS", "RESOLVED", "VERIFIED", "CLOSED",
                         "REOPENED", "WONT_FIX", "DUPLICATE"):
        raise ApiError("ERR_INVALID_REQUEST", "Unknown to_status.", 400)
    cur = bug["status"]
    if to_status == "IN_PROGRESS":
        if cur not in ("TRIAGED", "REOPENED"):
            raise ApiError("ERR_INVALID_STATE", "Bug must be TRIAGED or REOPENED.", 409)
        bug["status"] = "IN_PROGRESS"
        H.touch(bug)
    elif to_status == "RESOLVED":
        if cur != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE", "Bug must be IN_PROGRESS.", 409)
        bug["status"] = "RESOLVED"
        H.touch(bug)
    elif to_status == "VERIFIED":
        if cur != "RESOLVED":
            raise ApiError("ERR_INVALID_STATE", "Bug must be RESOLVED.", 409)
        bug["status"] = "VERIFIED"
        H.touch(bug)
    elif to_status == "CLOSED":
        if cur != "VERIFIED":
            raise ApiError("ERR_INVALID_STATE", "Bug must be VERIFIED.", 409)
        bug["status"] = "CLOSED"
        H.touch(bug)
    elif to_status == "REOPENED":
        if cur not in ("RESOLVED", "VERIFIED"):
            raise ApiError("ERR_INVALID_STATE", "Bug must be RESOLVED or VERIFIED.", 409)
        new_sev = b.get("severity")
        if new_sev is not None:
            if new_sev not in BUG_SEVERITIES:
                raise ApiError("ERR_INVALID_REQUEST", "Unknown severity.", 400)
            bug["severity"] = new_sev
        bug["reopened_count"] += 1
        bug["status"] = "REOPENED"
        H.touch(bug)
        _maybe_blocker_cascade(bug)
    elif to_status in ("WONT_FIX", "DUPLICATE"):
        resolution = b.get("resolution")
        if to_status == "WONT_FIX":
            if cur not in ("TRIAGED", "IN_PROGRESS"):
                raise ApiError("ERR_INVALID_STATE", "Bug must be TRIAGED or IN_PROGRESS.", 409)
        else:
            if cur != "TRIAGED":
                raise ApiError("ERR_INVALID_STATE", "Bug must be TRIAGED.", 409)
        if resolution is None or not isinstance(resolution, str) or not resolution:
            raise ApiError("ERR_INVALID_REQUEST", "resolution is required.", 400)
        bug["status"] = to_status
        H.touch(bug)
    return success_object(H.public(bug))


# ---------------- submission packages ----------------

def _submission_fee(platform_code, round_no, expedited, submit_dt):
    base = BASE_FEE_CENTS[platform_code]
    round_mult = Decimal("1.00") if round_no == 1 else (
        Decimal("0.50") if round_no == 2 else Decimal("0.25"))
    exped_mult = Decimal("1.75") if expedited else Decimal("1.00")
    wknd_mult = Decimal("1.20") if submit_dt.weekday() >= 5 else Decimal("1.00")
    fee_pre_cap = (Decimal(base) * round_mult * exped_mult * wknd_mult).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(min(fee_pre_cap, Decimal(FEE_CAP_CENTS[platform_code])))


def _seed_checklist(package_id, platform_code):
    items = []
    for code, sev, auto in TRC_CATALOG[platform_code]:
        items.append({
            "requirement_code": code,
            "severity": sev,
            "auto_verifiable": auto,
            "status": "UNVERIFIED",
            "waiver_status": "NONE",
            "waiver_justification": None,
            "waiver_requested_by_user_id": None,
        })
    c = {
        "submission_package_id": package_id,
        "platform_code": platform_code,
        "items": items,
    }
    H.init_common(c)
    db.checklists[c["id"]] = c
    return c


@bp.route("/qa-cert/titles/<titleId>/submission-packages", methods=["POST"])
def create_package(titleId):
    user_id, _ = require_role("CertificationLead")
    t = db.titles.get(titleId)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "Title not found.", 404)
    b = _body()
    platform_code = _req_str(b, "platform_code")
    build_id = _req_str(b, "build_id")
    test_plan_id = _req_str(b, "test_plan_id")
    expected_title_version = b.get("expected_title_version")
    expedited = b.get("expedited", False)
    if not isinstance(expedited, bool):
        raise ApiError("ERR_INVALID_REQUEST", "expedited must be a boolean.", 400)
    if platform_code not in PLATFORMS:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown platform_code.", 400)
    bd = db.builds.get(build_id)
    if bd is None:
        raise ApiError("ERR_NOT_FOUND", "Build not found.", 404)
    plan = db.test_plans.get(test_plan_id)
    if plan is None:
        raise ApiError("ERR_NOT_FOUND", "Test plan not found.", 404)
    # OCC (priority 3.5, before business rules)
    if expected_title_version is not None:
        if not isinstance(expected_title_version, int) or isinstance(expected_title_version, bool):
            raise ApiError("ERR_INVALID_REQUEST", "expected_title_version must be an integer.", 400)
        if expected_title_version != t["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_title_version does not match the title's current version.", 412)
    # business gates
    if t["status"] not in ("IN_DEVELOPMENT", "CERTIFICATION"):
        raise ApiError("ERR_INVALID_STATE", "Title must be IN_DEVELOPMENT or CERTIFICATION.", 409)
    if platform_code not in t["platform_codes"]:
        raise ApiError("ERR_INVALID_REQUEST", "platform_code is not in the title's platform_codes.", 400)
    if bd["title_id"] != t["id"]:
        raise ApiError("ERR_BUILD_TITLE_MISMATCH", "Build belongs to a different title.", 422)
    if bd["platform_code"] != platform_code:
        raise ApiError("ERR_BUILD_PLATFORM_MISMATCH", "Build targets a different platform.", 422)
    if bd["status"] != "CANDIDATE":
        raise ApiError("ERR_BUILD_NOT_CANDIDATE", "Build must be CANDIDATE.", 409)
    if plan["title_id"] != t["id"] or plan["platform_code"] != platform_code or \
            plan["status"] not in ("APPROVED", "LOCKED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Test plan must match (title, platform) and be APPROVED or LOCKED.", 409)
    # round: 1 + count of prior non-SUPERSEDED packages for same (title, platform)
    prior = sum(1 for p in db.packages.values()
                if p["title_id"] == t["id"] and p["platform_code"] == platform_code
                and p["status"] != "SUPERSEDED")
    pkg = {
        "title_id": t["id"],
        "platform_code": platform_code,
        "build_id": build_id,
        "test_plan_id": test_plan_id,
        "checklist_id": None,
        "round": 1 + prior,
        "expedited": expedited,
        "fee_cents": None,
        "readiness_optimistic_pct": None,
        "readiness_strict_pct": None,
        "submitted_at": None,
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "withdrawn_cause": None,
        "status": "ASSEMBLING",
    }
    H.init_common(pkg)
    db.packages[pkg["id"]] = pkg
    checklist = _seed_checklist(pkg["id"], platform_code)
    pkg["checklist_id"] = checklist["id"]
    # supersede prior ASSEMBLING sibling for same (title, platform)
    for p in list(db.packages.values()):
        if p["id"] != pkg["id"] and p["title_id"] == t["id"] and \
                p["platform_code"] == platform_code and p["status"] == "ASSEMBLING":
            p["status"] = "SUPERSEDED"
            H.touch(p)
            H.maybe_unlock_plan(p["test_plan_id"])
    # lock plan
    if plan["status"] == "APPROVED":
        plan["status"] = "LOCKED"
        H.touch(plan)
    # title version bump
    H.touch(t)
    opt, strict = H.readiness(checklist)
    pkg["readiness_optimistic_pct"] = opt
    pkg["readiness_strict_pct"] = strict
    return success_object(H.public(pkg), 201)


@bp.route("/qa-cert/submission-packages/<packageId>", methods=["GET"])
def get_package(packageId):
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    p = db.packages.get(packageId)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "Package not found.", 404)
    return success_object(H.public(p))


@bp.route("/qa-cert/submission-packages", methods=["GET"])
def list_packages():
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    title_id = request.args.get("title_id")
    platform_code = request.args.get("platform_code")
    build_id = request.args.get("build_id")
    test_plan_id = request.args.get("test_plan_id")
    status = request.args.get("status")
    items = list(db.packages.values())
    if title_id is not None:
        items = [x for x in items if x["title_id"] == title_id]
    if platform_code is not None:
        items = [x for x in items if x["platform_code"] == platform_code]
    if build_id is not None:
        items = [x for x in items if x["build_id"] == build_id]
    if test_plan_id is not None:
        items = [x for x in items if x["test_plan_id"] == test_plan_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    items.sort(key=lambda x: (x["_created"], x["id"]))
    limit, offset = H.get_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([H.public(x) for x in page], limit, offset, total)


@bp.route("/qa-cert/submission-packages/<packageId>/transition", methods=["POST"])
def package_transition(packageId):
    user_id, role = require_role("CertificationLead", "PlatformReviewer")
    p = db.packages.get(packageId)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "Package not found.", 404)
    b = _body()
    to_status = _req_str(b, "to_status")
    if to_status not in ("SUBMITTED", "IN_REVIEW", "APPROVED", "REJECTED", "WITHDRAWN"):
        raise ApiError("ERR_INVALID_REQUEST", "Unknown to_status.", 400)
    # per-action role enforcement
    if to_status in ("SUBMITTED", "WITHDRAWN") and role != "CertificationLead":
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS",
                       "Only CertificationLead may submit or withdraw.", 403)
    if to_status in ("IN_REVIEW", "APPROVED", "REJECTED") and role != "PlatformReviewer":
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS",
                       "Only PlatformReviewer may review or decide.", 403)
    t = db.titles.get(p["title_id"])
    cur = p["status"]
    if to_status == "SUBMITTED":
        if cur != "ASSEMBLING":
            raise ApiError("ERR_PACKAGE_NOT_ASSEMBLING", "Package must be ASSEMBLING.", 409)
        if t["embargoed"]:
            raise ApiError("ERR_TITLE_UNDER_EMBARGO", "Title is under embargo.", 403)
        now = db.clock
        for bw in db.blackouts.values():
            if bw["platform_code"] == p["platform_code"]:
                lo = bw["_start"] - timedelta(hours=bw["buffer_hours"])
                hi = bw["_end"] + timedelta(hours=bw["buffer_hours"])
                if lo <= now <= hi:
                    raise ApiError("ERR_SUBMISSION_BLACKOUT_ACTIVE",
                                   "Submit timestamp inside a buffered blackout interval.", 409)
        checklist = db.checklists[p["checklist_id"]]
        for item in checklist["items"]:
            if item["status"] not in ("PASSED", "WAIVED", "NA"):
                raise ApiError("ERR_CHECKLIST_INCOMPLETE",
                               "Every checklist item must be PASSED, WAIVED, or NA.", 409)
        if H.open_blocker_count(t["id"]) != 0:
            raise ApiError("ERR_OPEN_BLOCKERS_EXIST", "Open BLOCKER bugs exist on the title.", 409)
        for other in db.packages.values():
            if other["title_id"] == t["id"] and other["platform_code"] == p["platform_code"] and \
                    other["status"] == "REJECTED":
                for f in db.findings.values():
                    if f["submission_package_id"] == other["id"] and \
                            f["severity"] == "CATEGORY_A" and \
                            f["status"] in ("OPEN", "FIXED_IN_BUILD"):
                        raise ApiError("ERR_OPEN_CATEGORY_A_FINDINGS",
                                       "Open CATEGORY_A findings on a rejected package.", 409)
        territory = PLATFORM_TERRITORY[p["platform_code"]]
        granted = any(f["title_id"] == t["id"] and f["territory"] == territory and
                      f["status"] == "GRANTED" for f in db.filings.values())
        if not granted:
            raise ApiError("ERR_AGE_RATING_NOT_GRANTED",
                           "No GRANTED age-rating filing for the platform's territory.", 409)
        for pk in db.packs.values():
            if pk["title_id"] == t["id"] and pk["is_required"]:
                if pk["translation_status"] != "LOCKED" or pk["signoff_status"] != "SIGNED":
                    raise ApiError("ERR_LOCALIZATION_NOT_LOCKED",
                                   "A required localization pack is not LOCKED+SIGNED.", 409)
        fee = _submission_fee(p["platform_code"], p["round"], p["expedited"], now)
        view = H.title_view(t)
        if view["cert_budget_available_cents"] < fee:
            raise ApiError("ERR_CERT_BUDGET_EXCEEDED", "Budget does not cover the fee.", 402)
        p["fee_cents"] = fee
        p["submitted_at"] = H.clock_iso()
        p["submitted_by_user_id"] = user_id
        p["status"] = "SUBMITTED"
        H.touch(p)
    elif to_status == "IN_REVIEW":
        if cur != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Package must be SUBMITTED.", 409)
        p["status"] = "IN_REVIEW"
        H.touch(p)
    elif to_status in ("APPROVED", "REJECTED"):
        if cur != "IN_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "Package must be IN_REVIEW.", 409)
        if user_id == p["submitted_by_user_id"]:
            raise ApiError("ERR_SELF_CERT_DECISION",
                           "The package submitter cannot decide the same package.", 403)
        p["decided_by_user_id"] = user_id
        p["status"] = to_status
        H.touch(p)
        if to_status == "APPROVED":
            bd = db.builds.get(p["build_id"])
            if bd is not None and bd["status"] == "CANDIDATE":
                bd["status"] = "CONSUMED"
                H.touch(bd)
            H.maybe_unlock_plan(p["test_plan_id"])
    elif to_status == "WITHDRAWN":
        if cur not in ("ASSEMBLING", "SUBMITTED", "IN_REVIEW"):
            raise ApiError("ERR_INVALID_STATE",
                           "Package must be ASSEMBLING, SUBMITTED, or IN_REVIEW.", 409)
        p["withdrawn_cause"] = "MANUAL"
        p["status"] = "WITHDRAWN"
        H.touch(p)
        H.maybe_unlock_plan(p["test_plan_id"])
    return success_object(H.public(p))


# ---------------- compliance checklists ----------------

@bp.route("/qa-cert/compliance-checklists/<checklistId>", methods=["GET"])
def get_checklist(checklistId):
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    c = db.checklists.get(checklistId)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "Checklist not found.", 404)
    return success_object(H.checklist_view(c))


@bp.route("/qa-cert/compliance-checklists", methods=["GET"])
def list_checklists():
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    sp_id = request.args.get("submission_package_id")
    items = list(db.checklists.values())
    if sp_id is not None:
        items = [c for c in items if c["submission_package_id"] == sp_id]
    items.sort(key=lambda x: (x["_created"], x["id"]))
    limit, offset = H.get_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([H.checklist_view(c) for c in page], limit, offset, total)


def _find_item(c, requirement_code):
    for item in c["items"]:
        if item["requirement_code"] == requirement_code:
            return item
    return None


def _checklist_editable(c):
    pkg = db.packages.get(c["submission_package_id"])
    if pkg is None or pkg["status"] != "ASSEMBLING":
        raise ApiError("ERR_CHECKLIST_NOT_EDITABLE",
                       "Checklist item edits require the owning package to be ASSEMBLING.", 409)
    return pkg


@bp.route("/qa-cert/compliance-checklists/<checklistId>/items/verify", methods=["POST"])
def verify_item(checklistId):
    require_role("ComplianceManager")
    c = db.checklists.get(checklistId)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "Checklist not found.", 404)
    b = _body()
    requirement_code = _req_str(b, "requirement_code")
    result = _req_str(b, "result")
    if result not in ("PASSED", "FAILED", "NA"):
        raise ApiError("ERR_INVALID_REQUEST", "result must be PASSED, FAILED, or NA.", 400)
    item = _find_item(c, requirement_code)
    if item is None:
        raise ApiError("ERR_NOT_FOUND", "Checklist item not found.", 404)
    # state legality (priority 5) before structural gates (priority 9)
    if item["status"] not in ("UNVERIFIED", "FAILED"):
        raise ApiError("ERR_INVALID_STATE", "Item must be UNVERIFIED or FAILED.", 409)
    pkg = _checklist_editable(c)
    if result == "NA" and item["severity"] != "RECOMMENDED":
        raise ApiError("ERR_NA_NOT_ALLOWED_FOR_REQUIRED",
                       "NA is only accepted for RECOMMENDED items.", 400)
    if item["status"] == "FAILED" and result == "PASSED" and \
            item["waiver_status"] == "PENDING":
        item["waiver_status"] = "SUPERSEDED"
    item["status"] = result
    H.touch(c)
    H.refresh_package_readiness(pkg["id"])
    return success_object(H.checklist_view(c))


@bp.route("/qa-cert/compliance-checklists/<checklistId>/items/waive", methods=["POST"])
def waive_item(checklistId):
    user_id, _ = require_role("CertificationLead")
    c = db.checklists.get(checklistId)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "Checklist not found.", 404)
    b = _body()
    requirement_code = _req_str(b, "requirement_code")
    justification = _req_str(b, "justification")
    expected_checklist_version = b.get("expected_checklist_version")
    item = _find_item(c, requirement_code)
    if item is None:
        raise ApiError("ERR_NOT_FOUND", "Checklist item not found.", 404)
    # OCC (priority 4) immediately after existence, before all business rules
    if expected_checklist_version is not None:
        if not isinstance(expected_checklist_version, int) or \
                isinstance(expected_checklist_version, bool):
            raise ApiError("ERR_INVALID_REQUEST", "expected_checklist_version must be an integer.", 400)
        if expected_checklist_version != c["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_checklist_version does not match the checklist's version.", 412)
    _checklist_editable(c)
    if item["status"] != "FAILED":
        raise ApiError("ERR_WAIVER_REQUIRES_FAILED_ITEM",
                       "Waivers may only be requested for items in FAILED.", 409)
    if item["waiver_status"] == "PENDING":
        item["waiver_status"] = "SUPERSEDED"
    item["waiver_status"] = "PENDING"
    item["waiver_justification"] = justification
    item["waiver_requested_by_user_id"] = user_id
    H.touch(c)
    return success_object(H.checklist_view(c))


@bp.route("/qa-cert/compliance-checklists/<checklistId>/items/waiver-decision", methods=["POST"])
def waiver_decision(checklistId):
    user_id, _ = require_role("ComplianceManager")
    c = db.checklists.get(checklistId)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "Checklist not found.", 404)
    b = _body()
    requirement_code = _req_str(b, "requirement_code")
    decision = _req_str(b, "decision")
    if decision not in ("APPROVED", "REJECTED"):
        raise ApiError("ERR_INVALID_REQUEST", "decision must be APPROVED or REJECTED.", 400)
    item = _find_item(c, requirement_code)
    if item is None:
        raise ApiError("ERR_NOT_FOUND", "Checklist item not found.", 404)
    if item["waiver_status"] != "PENDING":
        raise ApiError("ERR_WAIVER_NOT_PENDING", "The item's waiver_status must be PENDING.", 409)
    if user_id == item["waiver_requested_by_user_id"]:
        raise ApiError("ERR_SELF_WAIVER_DECISION",
                       "The waiver requester cannot decide that waiver.", 403)
    pkg = db.packages.get(c["submission_package_id"])
    if decision == "APPROVED":
        item["waiver_status"] = "APPROVED"
        item["status"] = "WAIVED"
    else:
        item["waiver_status"] = "REJECTED"
    H.touch(c)
    if pkg is not None:
        H.refresh_package_readiness(pkg["id"])
    return success_object(H.checklist_view(c))


# ---------------- cert findings ----------------

@bp.route("/qa-cert/submission-packages/<packageId>/findings", methods=["POST"])
def create_finding(packageId):
    require_role("PlatformReviewer")
    p = db.packages.get(packageId)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "Package not found.", 404)
    b = _body()
    severity = _req_str(b, "severity")
    if severity not in ("CATEGORY_A", "CATEGORY_B"):
        raise ApiError("ERR_INVALID_REQUEST", "severity must be CATEGORY_A or CATEGORY_B.", 400)
    requirement_code = _req_str(b, "requirement_code")
    description = _req_str(b, "description")
    if p["status"] not in ("IN_REVIEW", "REJECTED"):
        raise ApiError("ERR_PACKAGE_NOT_REVIEWABLE",
                       "Findings can only be filed while the package is IN_REVIEW or REJECTED.", 409)
    f = {
        "submission_package_id": p["id"],
        "severity": severity,
        "requirement_code": requirement_code,
        "description": description,
        "status": "OPEN",
        "fixed_in_build_id": None,
        "reopen_count": 0,
    }
    H.init_common(f)
    db.findings[f["id"]] = f
    return success_object(H.public(f), 201)


@bp.route("/qa-cert/cert-findings/<findingId>", methods=["GET"])
def get_finding(findingId):
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    f = db.findings.get(findingId)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", "Finding not found.", 404)
    return success_object(H.public(f))


@bp.route("/qa-cert/cert-findings", methods=["GET"])
def list_findings():
    require_role(*("ReleaseManager", "QALead", "VendorManager", "CertificationLead",
                   "PlatformReviewer", "ComplianceManager", "PlatformAdmin"))
    sp_id = request.args.get("submission_package_id")
    status = request.args.get("status")
    severity = request.args.get("severity")
    fixed_in_build_id = request.args.get("fixed_in_build_id")
    items = list(db.findings.values())
    if sp_id is not None:
        items = [f for f in items if f["submission_package_id"] == sp_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    if severity is not None:
        items = [f for f in items if f["severity"] == severity]
    if fixed_in_build_id is not None:
        items = [f for f in items if f.get("fixed_in_build_id") == fixed_in_build_id]
    items.sort(key=lambda x: (x["_created"], x["id"]))
    limit, offset = H.get_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([H.public(f) for f in page], limit, offset, total)


@bp.route("/qa-cert/cert-findings/<findingId>/transition", methods=["POST"])
def finding_transition(findingId):
    user_id, role = require_role("CertificationLead", "PlatformReviewer")
    f = db.findings.get(findingId)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", "Finding not found.", 404)
    b = _body()
    to_status = _req_str(b, "to_status")
    if to_status not in ("FIXED_IN_BUILD", "VERIFIED", "OPEN"):
        raise ApiError("ERR_INVALID_REQUEST", "Unknown to_status.", 400)
    if to_status == "FIXED_IN_BUILD" and role != "CertificationLead":
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS",
                       "Only CertificationLead may mark a finding fixed.", 403)
    if to_status in ("VERIFIED", "OPEN") and role != "PlatformReviewer":
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS",
                       "Only PlatformReviewer may verify findings.", 403)
    pkg = db.packages.get(f["submission_package_id"])
    if to_status == "FIXED_IN_BUILD":
        if f["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Finding must be OPEN.", 409)
        build_id = b.get("build_id")
        if build_id is None or not isinstance(build_id, str):
            raise ApiError("ERR_INVALID_REQUEST", "build_id is required.", 400)
        bd = db.builds.get(build_id)
        if bd is None:
            raise ApiError("ERR_NOT_FOUND", "Build not found.", 404)
        if bd["title_id"] != pkg["title_id"]:
            raise ApiError("ERR_BUILD_TITLE_MISMATCH", "Build belongs to a different title.", 422)
        if bd["platform_code"] != pkg["platform_code"]:
            raise ApiError("ERR_BUILD_PLATFORM_MISMATCH", "Build targets a different platform.", 422)
        rejected_build = db.builds.get(pkg["build_id"])
        if rejected_build is not None and bd["_created"] <= rejected_build["_created"]:
            raise ApiError("ERR_FINDING_BUILD_NOT_NEWER",
                           "Fix build must be created strictly after the rejected package's build.", 422)
        if bd["status"] not in ("TEST_PASSED", "CANDIDATE"):
            raise ApiError("ERR_FIX_BUILD_NOT_QUALIFIED",
                           "Fix build must be TEST_PASSED or CANDIDATE.", 409)
        f["fixed_in_build_id"] = build_id
        f["status"] = "FIXED_IN_BUILD"
        H.touch(f)
    elif to_status == "VERIFIED":
        if f["status"] != "FIXED_IN_BUILD":
            raise ApiError("ERR_INVALID_STATE", "Finding must be FIXED_IN_BUILD.", 409)
        f["status"] = "VERIFIED"
        H.touch(f)
        # close REJECTED package when this was the last non-VERIFIED finding
        if pkg is not None and pkg["status"] == "REJECTED":
            siblings = [x for x in db.findings.values()
                        if x["submission_package_id"] == pkg["id"]]
            if len(siblings) >= 1 and all(x["status"] == "VERIFIED" for x in siblings):
                pkg["status"] = "CLOSED"
                H.touch(pkg)
                H.maybe_unlock_plan(pkg["test_plan_id"])
    elif to_status == "OPEN":
        if f["status"] != "FIXED_IN_BUILD":
            raise ApiError("ERR_INVALID_STATE", "Finding must be FIXED_IN_BUILD.", 409)
        f["reopen_count"] += 1
        f["fixed_in_build_id"] = None
        f["status"] = "OPEN"
        H.touch(f)
    return success_object(H.public(f))
