"""Pro registration/fetch, background-check submit/decide, and reverse-reachable
lists (PRD §3.2, §4)."""
import re

from flask import Blueprint, request, g

from db import store
from errors import ApiError
from middleware import require_role, _read_headers, VALID_ROLES
from models import (
    common, touch, serialize, PRO_FIELDS, BACKGROUND_CHECK_FIELDS,
    DISPATCH_WINDOW_FIELDS, JOB_FIELDS,
)
from response import object_response, array_response
from services import pricing, vetting
from services.lookup import (
    require_body, require_string, require_enum, require_number,
    require_string_array, require_datetime, get_or_404, paginate,
    sorted_by_creation,
)

bp = Blueprint("pros", __name__)

_ZIP_RE = re.compile(r"^[0-9]{5}$")


# ---------------------------------------------------------------------------
# Registration + fetch
# ---------------------------------------------------------------------------
@bp.post("/pros")
def create_pro():
    user_id, role = _read_headers()
    if role is not None and role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown role")

    body = require_body()
    email = require_string(body, "email")
    full_name = require_string(body, "full_name")
    home_zip = require_string(body, "home_zip_code")
    if not _ZIP_RE.match(home_zip):
        raise ApiError("ERR_INVALID_REQUEST", "home_zip_code must be exactly 5 digits")
    skill_tags = require_string_array(body, "skill_tags", required=False, default=[])
    markup = require_number(body, "truck_stock_markup_pct", required=False,
                            default=0.25, minimum=0, maximum=1)

    for p in store.pros.values():
        if p["email"] == email:
            raise ApiError("ERR_VALIDATION", "email must be unique across Pro")

    pro = {
        "email": email,
        "full_name": full_name,
        "home_zip_code": home_zip,
        "skill_tags": skill_tags,
        "background_check_status": "PENDING",
        "license_status": "NONE",
        "license_expires_on": None,
        "truck_stock_markup_pct": markup,
        "completed_job_count": 0,
        "callback_job_count": 0,
        "callback_rate": 0,
    }
    common(pro)
    store.pros[pro["id"]] = pro
    return object_response(serialize(pro, PRO_FIELDS), status=201)


@bp.get("/pros/<pid>")
@require_role({"PlatformAdmin", "Customer", "Pro", "Dispatcher"})
def get_pro(pid):
    pro = get_or_404(store.pros, pid)
    return object_response(serialize(pro, PRO_FIELDS))


# ---------------------------------------------------------------------------
# Background checks
# ---------------------------------------------------------------------------
def _v_create_bc(body):
    return {
        "check_type": require_enum(body, "check_type", {"CRIMINAL", "IDENTITY", "LICENSE"}),
        "license_expires_on": require_datetime(body, "license_expires_on", required=False, default=None),
    }


@bp.post("/pros/<pid>/background-checks")
@require_role({"PlatformAdmin"}, validate=_v_create_bc)
def create_background_check(pid):
    check_type = g.validated["check_type"]
    license_expires_on = g.validated["license_expires_on"]
    get_or_404(store.pros, pid)

    check = {
        "pro_id": pid,
        "check_type": check_type,
        "license_expires_on": license_expires_on if check_type == "LICENSE" else None,
        "decision": "PENDING",
    }
    common(check)
    store.background_checks[check["id"]] = check
    return object_response(serialize(check, BACKGROUND_CHECK_FIELDS), status=201)


@bp.get("/pros/<pid>/background-checks")
@require_role({"PlatformAdmin", "Pro"})
def list_background_checks(pid):
    get_or_404(store.pros, pid)
    items = [c for c in store.background_checks.values() if c["pro_id"] == pid]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(c, BACKGROUND_CHECK_FIELDS) for c in page],
                          limit, offset, total)


def _v_decide(body):
    decision = require_enum(body, "decision", {"PASS", "FAIL"})
    # expected_pro_version is optional OCC on the Pro record.
    expected_pro_version = body.get("expected_pro_version")
    if expected_pro_version is not None and (
            isinstance(expected_pro_version, bool)
            or not isinstance(expected_pro_version, int)):
        raise ApiError("ERR_INVALID_REQUEST", "expected_pro_version must be an integer")
    return {"decision": decision, "expected_pro_version": expected_pro_version}


@bp.post("/background-checks/<bcid>/decide")
@require_role({"PlatformAdmin"}, validate=_v_decide)
def decide_background_check(bcid):
    decision = g.validated["decision"]
    expected_pro_version = g.validated["expected_pro_version"]

    check = get_or_404(store.background_checks, bcid)
    pro = get_or_404(store.pros, check["pro_id"])

    if expected_pro_version is not None and expected_pro_version != pro["version"]:
        raise ApiError("ERR_STALE_VERSION", "Pro version is stale")

    check["decision"] = decision
    touch(check)

    # license posture (parallel axis) then background posture.
    license_changed = vetting.apply_license_decision(pro, check)
    bg_changed = vetting.recompute_background_status(pro)
    if license_changed or bg_changed:
        touch(pro)

    return object_response(serialize(check, BACKGROUND_CHECK_FIELDS))


# ---------------------------------------------------------------------------
# Reverse-reachable lists
# ---------------------------------------------------------------------------
@bp.get("/pros/<pid>/dispatch-windows")
@require_role({"PlatformAdmin", "Pro", "Dispatcher", "Customer"})
def list_pro_dispatch_windows(pid):
    get_or_404(store.pros, pid)
    items = [w for w in store.dispatch_windows.values() if w["pro_id"] == pid]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(w, DISPATCH_WINDOW_FIELDS) for w in page],
                          limit, offset, total)


@bp.get("/pros/<pid>/jobs")
@require_role({"PlatformAdmin", "Pro", "Dispatcher"})
def list_pro_jobs(pid):
    get_or_404(store.pros, pid)
    items = [j for j in store.jobs.values() if j.get("pro_id") == pid]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(j, JOB_FIELDS) for j in page],
                          limit, offset, total)
