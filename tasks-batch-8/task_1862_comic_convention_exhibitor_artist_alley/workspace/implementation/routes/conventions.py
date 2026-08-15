"""Convention + CategoryQuota routes."""

from flask import Blueprint

import db
from errors import fail
from helpers import (get_json_body, require_str, require_int, opt_int,
                     require_bool, require_enum, require_list, parse_dt,
                     opt_parse_dt, paginate, sort_by_created, get_or_404,
                     opt_str)
from middleware import require_roles
from response import success_object, success_list
from services import workflow

bp = Blueprint("conventions", __name__)

CATEGORIES = ("ARTIST_ALLEY", "DEALER", "PUBLISHER", "STUDIO", "NONPROFIT")
PHASES = ("SETUP", "APPLICATIONS_OPEN", "JURY_REVIEW", "PLACEMENT",
          "LOGISTICS", "LIVE", "LOAD_OUT", "CLOSED")


def convention_view(c):
    return {k: c[k] for k in (
        "id", "name", "starts_at", "ends_at", "renewal_open_at",
        "application_open_at", "application_close_at", "early_bird_deadline",
        "deposit_window_days", "tax_permit_required", "sales_tax_rate_bp",
        "phase", "ops_run_count", "created_at", "updated_at", "version")}


def quota_view(q):
    return {k: q[k] for k in (
        "id", "convention_id", "category", "max_accepted", "max_waitlisted",
        "accepted_count", "waitlisted_count", "created_at", "updated_at", "version")}


# ---------------------------------------------------------------------------
# POST /conventions
# ---------------------------------------------------------------------------
@bp.route("/conventions", methods=["POST"])
def create_convention():
    require_roles("ShowDirector")
    body = get_json_body()
    name = require_str(body, "name")
    starts_at = parse_dt(body, "starts_at")
    ends_at = parse_dt(body, "ends_at")
    renewal_open_at = parse_dt(body, "renewal_open_at")
    application_open_at = parse_dt(body, "application_open_at")
    application_close_at = parse_dt(body, "application_close_at")
    early_bird_deadline = parse_dt(body, "early_bird_deadline")
    tax_permit_required = require_bool(body, "tax_permit_required")
    sales_tax_rate_bp = require_int(body, "sales_tax_rate_bp", minimum=0)
    deposit_window_days = opt_int(body, "deposit_window_days", minimum=1)
    if deposit_window_days is None:
        deposit_window_days = 14
    category_quotas_in = require_list(body, "category_quotas")
    dock_doors_in = require_list(body, "dock_doors")

    # validate quota entries
    seen_categories = set()
    parsed_quotas = []
    for entry in category_quotas_in:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "category_quotas entries must be objects")
        cat = entry.get("category")
        if cat not in CATEGORIES:
            fail("ERR_INVALID_REQUEST", f"unknown category {cat}")
        if cat in seen_categories:
            fail("ERR_INVALID_REQUEST", f"duplicate category {cat}")
        seen_categories.add(cat)
        ma = entry.get("max_accepted")
        mw = entry.get("max_waitlisted")
        if not isinstance(ma, int) or isinstance(ma, bool) or ma < 0:
            fail("ERR_INVALID_REQUEST", "max_accepted must be a non-negative integer")
        if not isinstance(mw, int) or isinstance(mw, bool) or mw < 0:
            fail("ERR_INVALID_REQUEST", "max_waitlisted must be a non-negative integer")
        parsed_quotas.append({"category": cat, "max_accepted": ma, "max_waitlisted": mw})

    seen_doors = set()
    parsed_doors = []
    for entry in dock_doors_in:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "dock_doors entries must be objects")
        code = entry.get("door_code")
        if not isinstance(code, str):
            fail("ERR_INVALID_REQUEST", "door_code must be a string")
        if code in seen_doors:
            fail("ERR_INVALID_REQUEST", f"duplicate door_code {code}")
        seen_doors.add(code)
        parsed_doors.append(code)

    conv = {
        "id": db.new_id(),
        "name": name,
        "starts_at": db._fmt_iso(starts_at),
        "ends_at": db._fmt_iso(ends_at),
        "renewal_open_at": db._fmt_iso(renewal_open_at),
        "application_open_at": db._fmt_iso(application_open_at),
        "application_close_at": db._fmt_iso(application_close_at),
        "early_bird_deadline": db._fmt_iso(early_bird_deadline),
        "deposit_window_days": deposit_window_days,
        "tax_permit_required": tax_permit_required,
        "sales_tax_rate_bp": sales_tax_rate_bp,
        "phase": "SETUP",
        "ops_run_count": 0,
    }
    db.stamp_created(conv)
    db.conventions[conv["id"]] = conv

    for pq in parsed_quotas:
        q = {
            "id": db.new_id(),
            "convention_id": conv["id"],
            "category": pq["category"],
            "max_accepted": pq["max_accepted"],
            "max_waitlisted": pq["max_waitlisted"],
            "accepted_count": 0,
            "waitlisted_count": 0,
        }
        db.stamp_created(q)
        db.category_quotas[q["id"]] = q

    for code in parsed_doors:
        d = {
            "id": db.new_id(),
            "convention_id": conv["id"],
            "door_code": code,
            "created_at": db.now_iso(),
        }
        db.dock_doors[d["id"]] = d

    return success_object(convention_view(conv), 201)


@bp.route("/conventions/<conventionId>", methods=["GET"])
def get_convention(conventionId):
    require_roles("ShowDirector", "OperationsStaff", "JuryMember", "Exhibitor")
    conv = get_or_404(db.conventions, conventionId)
    return success_object(convention_view(conv), 200)


@bp.route("/conventions/<conventionId>", methods=["PUT"])
def update_convention(conventionId):
    require_roles("ShowDirector")
    conv = get_or_404(db.conventions, conventionId)
    body = get_json_body()
    expected = body.get("expected_convention_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        fail("ERR_INVALID_REQUEST", "expected_convention_version is required")
    if expected != conv["version"]:
        fail("ERR_STALE_CONVENTION_VERSION",
             "expected_convention_version does not match the convention's current version")

    if "name" in body and body["name"] is not None:
        conv["name"] = opt_str(body, "name")
    for field in ("starts_at", "ends_at", "renewal_open_at", "application_open_at",
                  "application_close_at", "early_bird_deadline"):
        dt = opt_parse_dt(body, field)
        if dt is not None:
            conv[field] = db._fmt_iso(dt)
    dwd = opt_int(body, "deposit_window_days", minimum=1)
    if dwd is not None:
        conv["deposit_window_days"] = dwd
    if "tax_permit_required" in body and body["tax_permit_required"] is not None:
        conv["tax_permit_required"] = require_bool(body, "tax_permit_required")
    rate = opt_int(body, "sales_tax_rate_bp", minimum=0)
    if rate is not None:
        conv["sales_tax_rate_bp"] = rate
    db.touch(conv)
    return success_object(convention_view(conv), 200)


@bp.route("/conventions/<conventionId>/advance-phase", methods=["POST"])
def advance_phase(conventionId):
    require_roles("ShowDirector")
    conv = get_or_404(db.conventions, conventionId)
    now = db.now_dt()
    phase = conv["phase"]

    if phase == "SETUP":
        has_quota = any(q["convention_id"] == conv["id"] for q in db.category_quotas.values())
        has_space = any(s["convention_id"] == conv["id"] for s in db.space_units.values())
        if not (has_quota and has_space):
            fail("ERR_PHASE_PRECONDITION",
                 "Requires at least one CategoryQuota and one SpaceUnit")
        conv["phase"] = "APPLICATIONS_OPEN"
    elif phase == "APPLICATIONS_OPEN":
        if now < db._parse_iso(conv["application_close_at"]):
            fail("ERR_PHASE_PRECONDITION",
                 "Clock must be at or after application_close_at")
        conv["phase"] = "JURY_REVIEW"
    elif phase == "JURY_REVIEW":
        open_apps = [a for a in db.applications.values()
                     if a["convention_id"] == conv["id"]
                     and a["status"] in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_REVISION")]
        if open_apps:
            fail("ERR_PHASE_PRECONDITION",
                 "Applications remain in SUBMITTED/UNDER_REVIEW/NEEDS_REVISION")
        conv["phase"] = "PLACEMENT"
    elif phase == "PLACEMENT":
        tentative = [p for p in db.placements.values()
                     if p["status"] == "TENTATIVE"
                     and db.applications.get(p["application_id"], {}).get("convention_id") == conv["id"]]
        if tentative:
            fail("ERR_PHASE_PRECONDITION", "TENTATIVE placements remain")
        conv["phase"] = "LOGISTICS"
    elif phase == "LOGISTICS":
        if now < db._parse_iso(conv["starts_at"]):
            fail("ERR_PHASE_PRECONDITION", "Clock must be at or after starts_at")
        conv["phase"] = "LIVE"
    elif phase == "LIVE":
        if now < db._parse_iso(conv["ends_at"]):
            fail("ERR_PHASE_PRECONDITION", "Clock must be at or after ends_at")
        conv["phase"] = "LOAD_OUT"
    elif phase == "LOAD_OUT":
        active_freight = [fb for fb in db.freight_bookings.values()
                          if fb["status"] in ("REQUESTED", "CONFIRMED", "CHECKED_IN")
                          and db.load_slots.get(fb["load_slot_id"], {}).get("convention_id") == conv["id"]]
        if active_freight:
            fail("ERR_PHASE_PRECONDITION", "Active freight bookings remain")
        open_issues = [t for t in db.issue_tickets.values()
                       if t["convention_id"] == conv["id"]
                       and t["status"] in ("OPEN", "TRIAGED", "ESCALATED")]
        if open_issues:
            fail("ERR_PHASE_PRECONDITION", "Unresolved issue tickets remain")
        conv["phase"] = "CLOSED"
    else:  # CLOSED
        fail("ERR_INVALID_TRANSITION", "Convention is CLOSED (terminal)")

    db.touch(conv)
    return success_object(convention_view(conv), 200)


@bp.route("/conventions/<conventionId>/run-ops", methods=["POST"])
def run_ops(conventionId):
    require_roles("ShowDirector")
    conv = get_or_404(db.conventions, conventionId)
    workflow.run_ops(conv)
    return success_object(convention_view(conv), 200)


# ---------------------------------------------------------------------------
# CategoryQuota endpoints
# ---------------------------------------------------------------------------
@bp.route("/category-quotas", methods=["GET"])
def list_quotas():
    require_roles("ShowDirector", "OperationsStaff", "JuryMember", "Exhibitor")
    items = list(db.category_quotas.values())
    cid = request_arg("convention_id")
    cat = request_arg("category")
    if cid is not None:
        items = [q for q in items if q["convention_id"] == cid]
    if cat is not None:
        items = [q for q in items if q["category"] == cat]
    items = sort_by_created(items)
    limit, offset, total, page = paginate(items)
    return success_list([quota_view(q) for q in page], limit, offset, total)


@bp.route("/category-quotas/<categoryQuotaId>", methods=["GET"])
def get_quota(categoryQuotaId):
    require_roles("ShowDirector", "OperationsStaff", "JuryMember", "Exhibitor")
    q = get_or_404(db.category_quotas, categoryQuotaId)
    return success_object(quota_view(q), 200)


@bp.route("/category-quotas/<categoryQuotaId>", methods=["PATCH"])
def patch_quota(categoryQuotaId):
    require_roles("ShowDirector")
    q = get_or_404(db.category_quotas, categoryQuotaId)
    body = get_json_body()
    new_ma = opt_int(body, "max_accepted", minimum=0)
    new_mw = opt_int(body, "max_waitlisted", minimum=0)
    if new_ma is not None and new_ma < q["accepted_count"]:
        fail("ERR_QUOTA_BELOW_ACCEPTED",
             "max_accepted below the current accepted_count")
    if new_ma is not None:
        q["max_accepted"] = new_ma
    if new_mw is not None:
        q["max_waitlisted"] = new_mw
    db.touch(q)
    return success_object(quota_view(q), 200)


def request_arg(name):
    from flask import request
    v = request.args.get(name)
    return v if v is not None else None
