"""Community Solar Subscription API — Flask entry point.

In-memory only. No seeding at startup. Every entity is created by tests via
the declared endpoints. Boots fresh on every start.sh invocation.
"""
import os

from flask import Flask, request

import response
import services as svc
import validation as val
from auth import get_caller, require_roles
from db import store, stamp_create, touch
from errors import ApiError, err

app = Flask(__name__)

ALL_ROLES = ("GridOperator", "ProgramAdmin", "Subscriber")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return response.error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return response.error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return response.error("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return response.error("ERR_INVALID_REQUEST", str(e), 400)


# ---------------------------------------------------------------------------
# Lookup helpers (existence — priority 3 / 4)
# ---------------------------------------------------------------------------
def get_or_404(table, rid):
    rec = table.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


def ref_or_404(table, rid):
    rec = table.get(rid)
    if rec is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced resource not found")
    return rec


def owns(role, user_id, subscriber_id):
    """Subscriber ownership check (PRD §2.1)."""
    if role != "Subscriber":
        return True
    return user_id == subscriber_id


def require_ownership(role, user_id, subscriber_id):
    if not owns(role, user_id, subscriber_id):
        raise err("ERR_FORBIDDEN", "Subscriber may only act on their own resources")


def list_response(items, serialize):
    limit, offset = val.parse_pagination()
    page, total, has_more = val.paginate(items, limit, offset)
    data = [serialize(r) for r in page]
    return response.list_success(data, limit, offset, total, has_more, status=200)


# ===========================================================================
# SolarProject
# ===========================================================================
@app.route("/projects", methods=["POST"])
def create_project():
    user_id, role = get_caller()
    require_roles(role, ("GridOperator",))
    body = val.get_json_body()
    name = val.require_string(body, "name")
    state_code = val.require_string(body, "state_code")
    nameplate = val.require_number(body, "nameplate_capacity_kw")
    credit_rate = val.require_int(body, "credit_rate_cents_per_kwh")
    carve_out_pct = body.get("carve_out_pct", 0.40)
    program_fee_rate = body.get("program_fee_rate", 0.10)
    # type checks for optionals
    if carve_out_pct is None:
        carve_out_pct = 0.40
    if program_fee_rate is None:
        program_fee_rate = 0.10
    if not val.is_number(carve_out_pct):
        raise err("ERR_INVALID_REQUEST", "carve_out_pct must be a number")
    if not val.is_number(program_fee_rate):
        raise err("ERR_INVALID_REQUEST", "program_fee_rate must be a number")
    # range validation (priority 6)
    if not (nameplate > 0):
        raise err("ERR_VALIDATION", "nameplate_capacity_kw must be > 0")
    if credit_rate < 0:
        raise err("ERR_VALIDATION", "credit_rate_cents_per_kwh must be >= 0")
    if not (0 <= carve_out_pct <= 1):
        raise err("ERR_VALIDATION", "carve_out_pct must be in [0,1]")
    if not (0 <= program_fee_rate < 1):
        raise err("ERR_VALIDATION", "program_fee_rate must be in [0,1)")

    pid = store.new_id()
    rec = {
        "id": pid,
        "_seq": store.next_seq(),
        "name": name,
        "state_code": state_code,
        "nameplate_capacity_kw": nameplate,
        "carve_out_pct": carve_out_pct,
        "credit_rate_cents_per_kwh": credit_rate,
        "program_fee_rate": program_fee_rate,
        "rec_minted_total": 0,
        "rec_retired_total": 0,
        "rec_available_balance": 0,
        "total_net_savings_cents": 0,
        "status": "OPEN",
    }
    rec.update(stamp_create())
    svc.recompute_project_ledger(rec)
    store.projects[pid] = rec
    return response.success(svc.serialize_project(rec), status=201)


@app.route("/projects/<rid>", methods=["GET"])
def get_project(rid):
    user_id, role = get_caller()
    require_roles(role, ALL_ROLES)
    p = get_or_404(store.projects, rid)
    return response.success(svc.serialize_project(p), status=200)


@app.route("/projects/<rid>/carve-out-adjustments", methods=["POST"])
def create_carve_out_adjustment(rid):
    user_id, role = get_caller()
    require_roles(role, ("ProgramAdmin",))
    p = get_or_404(store.projects, rid)
    body = val.get_json_body()
    new_pct = val.require_number(body, "new_carve_out_pct")
    reason = val.require_string(body, "reason")
    if not (0 <= new_pct <= 1):
        raise err("ERR_VALIDATION", "new_carve_out_pct must be in [0,1]")
    cid = store.new_id()
    prev = p["carve_out_pct"]
    rec = {
        "id": cid,
        "_seq": store.next_seq(),
        "project_id": rid,
        "previous_carve_out_pct": prev,
        "new_carve_out_pct": new_pct,
        "reason": reason,
        "created_at": response.now_iso(),
    }
    store.carve_out_adjustments[cid] = rec
    # side effects: update carve_out_pct, recompute, bump project version
    p["carve_out_pct"] = new_pct
    svc.recompute_project_ledger(p)
    touch(p)
    return response.success(svc.serialize_carve_out_adjustment(rec), status=201)


@app.route("/projects/<rid>/carve-out-adjustments", methods=["GET"])
def list_carve_out_adjustments(rid):
    user_id, role = get_caller()
    require_roles(role, ("GridOperator", "ProgramAdmin"))
    get_or_404(store.projects, rid)
    items = [c for c in store.carve_out_adjustments.values() if c["project_id"] == rid]
    return list_response(items, svc.serialize_carve_out_adjustment)


# ===========================================================================
# Subscriber
# ===========================================================================
@app.route("/subscribers", methods=["POST"])
def create_subscriber():
    user_id, role = get_caller()
    require_roles(role, ("ProgramAdmin",))
    body = val.get_json_body()
    full_name = val.require_string(body, "full_name")
    utility_account_no = val.require_string(body, "utility_account_no")
    state_code = val.require_string(body, "state_code")
    annual_usage = val.require_int(body, "annual_usage_kwh")
    is_low_income = body.get("is_low_income", False)
    if is_low_income is None:
        is_low_income = False
    if not isinstance(is_low_income, bool):
        raise err("ERR_INVALID_REQUEST", "is_low_income must be a boolean")
    if annual_usage < 0:
        raise err("ERR_VALIDATION", "annual_usage_kwh must be >= 0")
    # uniqueness (priority 7)
    for s in store.subscribers.values():
        if s["utility_account_no"] == utility_account_no:
            raise err("ERR_DUPLICATE_RESOURCE", "utility_account_no already exists")
    sid = store.new_id()
    rec = {
        "id": sid,
        "_seq": store.next_seq(),
        "full_name": full_name,
        "utility_account_no": utility_account_no,
        "state_code": state_code,
        "is_low_income": is_low_income,
        "annual_usage_kwh": annual_usage,
        "churn_risk_score": 0,
        "lifetime_savings_cents": 0,
    }
    rec.update(stamp_create())
    svc.recompute_churn_risk(rec)
    store.subscribers[sid] = rec
    return response.success(svc.serialize_subscriber(rec), status=201)


@app.route("/subscribers/<rid>", methods=["GET"])
def get_subscriber(rid):
    user_id, role = get_caller()
    require_roles(role, ALL_ROLES)
    s = get_or_404(store.subscribers, rid)
    return response.success(svc.serialize_subscriber(s), status=200)


# ===========================================================================
# Enrollment
# ===========================================================================
@app.route("/enrollments", methods=["POST"])
def create_enrollment():
    user_id, role = get_caller()
    require_roles(role, ("Subscriber", "ProgramAdmin"))
    body = val.get_json_body()
    # referential existence (priority 4) before required-field typing? PRD §2.9
    # order: referential existence (4) then required-field presence (5). But we
    # must read the FK values first; treat missing FK as ERR_INVALID_REQUEST(5)
    # only if absent. Presence of project_id/subscriber_id is required.
    if "project_id" not in body or body["project_id"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: project_id")
    if "subscriber_id" not in body or body["subscriber_id"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: subscriber_id")
    project_id = body["project_id"]
    subscriber_id = body["subscriber_id"]
    project = ref_or_404(store.projects, project_id)
    subscriber = ref_or_404(store.subscribers, subscriber_id)
    require_ownership(role, user_id, subscriber_id)
    share = val.require_number(body, "requested_share_kw")
    if not (share > 0):
        raise err("ERR_VALIDATION", "requested_share_kw must be > 0")
    eid = store.new_id()
    rec = {
        "id": eid,
        "_seq": store.next_seq(),
        "project_id": project_id,
        "subscriber_id": subscriber_id,
        "requested_share_kw": share,
        "status": "DRAFT",
        "rejection_reason": None,
        "subscription_id": None,
    }
    rec.update(stamp_create())
    store.enrollments[eid] = rec
    return response.success(svc.serialize_enrollment(rec), status=201)


@app.route("/enrollments", methods=["GET"])
def list_enrollments():
    user_id, role = get_caller()
    require_roles(role, ALL_ROLES)
    items = list(store.enrollments.values())
    pid = request.args.get("project_id")
    sub_id = request.args.get("subscriber_id")
    subscription_id = request.args.get("subscription_id")
    if pid is not None:
        items = [e for e in items if e["project_id"] == pid]
    if sub_id is not None:
        items = [e for e in items if e["subscriber_id"] == sub_id]
    if subscription_id is not None:
        items = [e for e in items if e.get("subscription_id") == subscription_id]
    return list_response(items, svc.serialize_enrollment)


@app.route("/enrollments/<rid>", methods=["GET"])
def get_enrollment(rid):
    user_id, role = get_caller()
    require_roles(role, ALL_ROLES)
    e = get_or_404(store.enrollments, rid)
    return response.success(svc.serialize_enrollment(e), status=200)


@app.route("/enrollments/<rid>/submit", methods=["POST"])
def submit_enrollment(rid):
    user_id, role = get_caller()
    require_roles(role, ("Subscriber",))
    e = get_or_404(store.enrollments, rid)
    require_ownership(role, user_id, e["subscriber_id"])
    # state validity (priority 8)
    if e["status"] not in ("DRAFT", "REJECTED"):
        raise err("ERR_INVALID_STATE", "Enrollment not in DRAFT or REJECTED")
    project = store.projects[e["project_id"]]
    svc.recompute_project_ledger(project)
    # business gates (after state): project-full, capacity, usage cap.
    # Ordering per PRD §3.3 wording at submit: project not FULL, then capacity,
    # then annual-usage cap.
    if project["status"] == "FULL":
        raise err("ERR_PROJECT_FULL", "Project is FULL")
    if e["requested_share_kw"] > project["available_kw"]:
        raise err("ERR_CAPACITY_EXCEEDED", "requested_share_kw exceeds available_kw")
    subscriber = store.subscribers[e["subscriber_id"]]
    # annual-usage cap only checked on DRAFT->SUBMITTED per §3.3; the resubmit
    # path (REJECTED->SUBMITTED) re-checks project-full and capacity only.
    if e["status"] == "DRAFT":
        if e["requested_share_kw"] * 1000 > subscriber["annual_usage_kwh"]:
            raise err("ERR_USAGE_CAP_EXCEEDED", "requested_share_kw exceeds annual usage cap")
    e["status"] = "SUBMITTED"
    e["rejection_reason"] = None
    touch(e)
    return response.success(svc.serialize_enrollment(e), status=200)


@app.route("/enrollments/<rid>/approve", methods=["POST"])
def approve_enrollment(rid):
    user_id, role = get_caller()
    require_roles(role, ("ProgramAdmin",))
    e = get_or_404(store.enrollments, rid)
    if e["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Enrollment not SUBMITTED")
    project = store.projects[e["project_id"]]
    subscriber = store.subscribers[e["subscriber_id"]]
    svc.recompute_project_ledger(project)
    if subscriber["is_low_income"]:
        if e["requested_share_kw"] > project["carve_out_available_kw"]:
            raise err("ERR_CARVE_OUT_EXCEEDED", "requested_share_kw exceeds carve_out_available_kw")
    e["status"] = "APPROVED"
    touch(e)
    return response.success(svc.serialize_enrollment(e), status=200)


@app.route("/enrollments/<rid>/reject", methods=["POST"])
def reject_enrollment(rid):
    user_id, role = get_caller()
    require_roles(role, ("ProgramAdmin",))
    e = get_or_404(store.enrollments, rid)
    if e["status"] not in ("SUBMITTED", "APPROVED"):
        raise err("ERR_INVALID_STATE", "Enrollment not SUBMITTED or APPROVED")
    body = val.get_json_body()
    reason = val.require_string(body, "rejection_reason")
    e["status"] = "REJECTED"
    e["rejection_reason"] = reason
    touch(e)
    return response.success(svc.serialize_enrollment(e), status=200)


@app.route("/enrollments/<rid>/activate", methods=["POST"])
def activate_enrollment(rid):
    user_id, role = get_caller()
    require_roles(role, ("ProgramAdmin",))
    e = get_or_404(store.enrollments, rid)
    if e["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Enrollment not APPROVED")
    project = store.projects[e["project_id"]]
    subscriber = store.subscribers[e["subscriber_id"]]
    svc.recompute_project_ledger(project)
    # capacity gate then carve-out gate (PRD §3.4 ordering)
    if e["requested_share_kw"] > project["available_kw"]:
        raise err("ERR_CAPACITY_EXCEEDED", "requested_share_kw exceeds available_kw")
    if subscriber["is_low_income"]:
        if e["requested_share_kw"] > project["carve_out_available_kw"]:
            raise err("ERR_CARVE_OUT_EXCEEDED", "requested_share_kw exceeds carve_out_available_kw")
    # create Subscription
    sub_id = store.new_id()
    sub = {
        "id": sub_id,
        "_seq": store.next_seq(),
        "project_id": e["project_id"],
        "subscriber_id": e["subscriber_id"],
        "enrollment_id": e["id"],
        "share_kw": e["requested_share_kw"],
        "is_carve_out": subscriber["is_low_income"],
        "status": "ACTIVE",
        "transferred_from_subscription_id": None,
        "cancellation_effective_period_id": None,
    }
    sub.update(stamp_create())
    store.subscriptions[sub_id] = sub
    e["status"] = "ACTIVATED"
    e["subscription_id"] = sub_id
    touch(e)
    # ledger sync + version bump on project
    svc.recompute_project_ledger(project)
    touch(project)
    return response.success(svc.serialize_subscription(sub), status=201)


# ===========================================================================
# Subscription
# ===========================================================================
@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    user_id, role = get_caller()
    require_roles(role, ALL_ROLES)
    items = list(store.subscriptions.values())
    filters = {
        "project_id": "project_id",
        "subscriber_id": "subscriber_id",
        "enrollment_id": "enrollment_id",
        "transferred_from_subscription_id": "transferred_from_subscription_id",
        "cancellation_effective_period_id": "cancellation_effective_period_id",
    }
    for qparam, field in filters.items():
        v = request.args.get(qparam)
        if v is not None:
            items = [s for s in items if s.get(field) == v]
    return list_response(items, svc.serialize_subscription)


@app.route("/subscriptions/<rid>", methods=["GET"])
def get_subscription(rid):
    user_id, role = get_caller()
    require_roles(role, ALL_ROLES)
    s = get_or_404(store.subscriptions, rid)
    return response.success(svc.serialize_subscription(s), status=200)


@app.route("/subscriptions/<rid>/suspend", methods=["POST"])
def suspend_subscription(rid):
    user_id, role = get_caller()
    require_roles(role, ("ProgramAdmin",))
    s = get_or_404(store.subscriptions, rid)
    if s["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Subscription not ACTIVE")
    s["status"] = "SUSPENDED"
    touch(s)
    subscriber = store.subscribers[s["subscriber_id"]]
    svc.recompute_churn_risk(subscriber)
    touch(subscriber)
    return response.success(svc.serialize_subscription(s), status=200)


@app.route("/subscriptions/<rid>/resume", methods=["POST"])
def resume_subscription(rid):
    user_id, role = get_caller()
    require_roles(role, ("ProgramAdmin",))
    s = get_or_404(store.subscriptions, rid)
    if s["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Subscription not SUSPENDED")
    s["status"] = "ACTIVE"
    touch(s)
    subscriber = store.subscribers[s["subscriber_id"]]
    svc.recompute_churn_risk(subscriber)
    touch(subscriber)
    return response.success(svc.serialize_subscription(s), status=200)


def current_open_period(project_id):
    """The project's current OPEN period, if any. If multiple, the latest by
    sequence_index."""
    opens = [
        p for p in store.periods.values()
        if p["project_id"] == project_id and p["status"] == "OPEN"
    ]
    if not opens:
        return None
    return max(opens, key=lambda p: p["sequence_index"])


@app.route("/subscriptions/<rid>/transfer", methods=["POST"])
def transfer_subscription(rid):
    user_id, role = get_caller()
    require_roles(role, ("Subscriber",))
    s = get_or_404(store.subscriptions, rid)
    require_ownership(role, user_id, s["subscriber_id"])
    body = val.get_json_body()
    if "target_subscriber_id" not in body or body["target_subscriber_id"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: target_subscriber_id")
    target_id = body["target_subscriber_id"]
    target = ref_or_404(store.subscribers, target_id)
    if "expected_project_version" not in body or body["expected_project_version"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_project_version")
    expected_version = body["expected_project_version"]
    if not val.is_int(expected_version):
        raise err("ERR_INVALID_REQUEST", "expected_project_version must be an integer")
    # state validity (priority 8)
    if s["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Subscription not ACTIVE")
    project = store.projects[s["project_id"]]
    # OCC (priority 9)
    if expected_version != project["version"]:
        raise err("ERR_STALE_PROJECT_VERSION", "expected_project_version mismatch")
    # jurisdiction (priority 11)
    if target["state_code"] != project["state_code"]:
        raise err("ERR_TRANSFER_JURISDICTION_MISMATCH", "target state_code mismatch")
    # create successor
    new_id = store.new_id()
    successor = {
        "id": new_id,
        "_seq": store.next_seq(),
        "project_id": s["project_id"],
        "subscriber_id": target_id,
        "enrollment_id": s["enrollment_id"],
        "share_kw": s["share_kw"],
        "is_carve_out": target["is_low_income"],
        "status": "ACTIVE",
        "transferred_from_subscription_id": s["id"],
        "cancellation_effective_period_id": None,
    }
    successor.update(stamp_create())
    store.subscriptions[new_id] = successor
    # original -> TRANSFERRING -> CANCELLED (system edge)
    s["status"] = "TRANSFERRING"
    touch(s)
    s["status"] = "CANCELLED"
    open_period = current_open_period(s["project_id"])
    s["cancellation_effective_period_id"] = open_period["id"] if open_period else None
    touch(s)
    # ledger recompute + project version bump
    svc.recompute_project_ledger(project)
    touch(project)
    return response.success(svc.serialize_subscription(successor), status=201)


def auto_promote_waitlist(project):
    """Promote oldest QUEUED entry that fits available_kw (PRD §3.6)."""
    svc.recompute_project_ledger(project)
    available = project["available_kw"]
    candidates = [
        w for w in store.waitlist_entries.values()
        if w["project_id"] == project["id"]
        and w["status"] == "QUEUED"
        and w["requested_share_kw"] <= available
    ]
    if not candidates:
        return
    candidates.sort(key=lambda w: (w["queued_at"], w["created_at"], w["_seq"]))
    chosen = candidates[0]
    # mint a fresh DRAFT enrollment for the entry
    eid = store.new_id()
    enrollment = {
        "id": eid,
        "_seq": store.next_seq(),
        "project_id": chosen["project_id"],
        "subscriber_id": chosen["subscriber_id"],
        "requested_share_kw": chosen["requested_share_kw"],
        "status": "DRAFT",
        "rejection_reason": None,
        "subscription_id": None,
    }
    enrollment.update(stamp_create())
    store.enrollments[eid] = enrollment
    chosen["status"] = "PROMOTED"
    chosen["promoted_enrollment_id"] = eid
    touch(chosen)


@app.route("/subscriptions/<rid>/cancel", methods=["POST"])
def cancel_subscription(rid):
    user_id, role = get_caller()
    require_roles(role, ("Subscriber",))
    s = get_or_404(store.subscriptions, rid)
    require_ownership(role, user_id, s["subscriber_id"])
    if s["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Subscription not ACTIVE or SUSPENDED")
    project = store.projects[s["project_id"]]
    was_full = project["status"] == "FULL"
    s["status"] = "CANCELLED"
    open_period = current_open_period(s["project_id"])
    s["cancellation_effective_period_id"] = open_period["id"] if open_period else None
    touch(s)
    # ledger release
    svc.recompute_project_ledger(project)
    touch(project)
    # churn recompute
    subscriber = store.subscribers[s["subscriber_id"]]
    svc.recompute_churn_risk(subscriber)
    touch(subscriber)
    # waitlist auto-promotion cascade
    auto_promote_waitlist(project)
    return response.success(svc.serialize_subscription(s), status=200)


# ===========================================================================
# WaitlistEntry
# ===========================================================================
@app.route("/waitlist-entries", methods=["POST"])
def create_waitlist_entry():
    user_id, role = get_caller()
    require_roles(role, ("Subscriber", "ProgramAdmin"))
    body = val.get_json_body()
    if "project_id" not in body or body["project_id"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: project_id")
    if "subscriber_id" not in body or body["subscriber_id"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: subscriber_id")
    project_id = body["project_id"]
    subscriber_id = body["subscriber_id"]
    ref_or_404(store.projects, project_id)
    ref_or_404(store.subscribers, subscriber_id)
    require_ownership(role, user_id, subscriber_id)
    share = val.require_number(body, "requested_share_kw")
    if not (share > 0):
        raise err("ERR_VALIDATION", "requested_share_kw must be > 0")
    wid = store.new_id()
    rec = {
        "id": wid,
        "_seq": store.next_seq(),
        "project_id": project_id,
        "subscriber_id": subscriber_id,
        "requested_share_kw": share,
        "queued_at": response.now_iso(),
        "status": "QUEUED",
        "promoted_enrollment_id": None,
    }
    rec.update(stamp_create())
    store.waitlist_entries[wid] = rec
    return response.success(svc.serialize_waitlist(rec), status=201)


@app.route("/waitlist-entries", methods=["GET"])
def list_waitlist_entries():
    user_id, role = get_caller()
    require_roles(role, ALL_ROLES)
    items = list(store.waitlist_entries.values())
    for qparam, field in (
        ("project_id", "project_id"),
        ("subscriber_id", "subscriber_id"),
        ("promoted_enrollment_id", "promoted_enrollment_id"),
    ):
        v = request.args.get(qparam)
        if v is not None:
            items = [w for w in items if w.get(field) == v]
    return list_response(items, svc.serialize_waitlist)


@app.route("/waitlist-entries/<rid>", methods=["GET"])
def get_waitlist_entry(rid):
    user_id, role = get_caller()
    require_roles(role, ALL_ROLES)
    w = get_or_404(store.waitlist_entries, rid)
    return response.success(svc.serialize_waitlist(w), status=200)


@app.route("/waitlist-entries/<rid>/withdraw", methods=["POST"])
def withdraw_waitlist_entry(rid):
    user_id, role = get_caller()
    require_roles(role, ("Subscriber",))
    w = get_or_404(store.waitlist_entries, rid)
    require_ownership(role, user_id, w["subscriber_id"])
    if w["status"] != "QUEUED":
        raise err("ERR_WAITLIST_NOT_QUEUED", "Waitlist entry not QUEUED")
    w["status"] = "WITHDRAWN"
    touch(w)
    return response.success(svc.serialize_waitlist(w), status=200)


# ===========================================================================
# BillingPeriod
# ===========================================================================
@app.route("/periods", methods=["POST"])
def create_period():
    user_id, role = get_caller()
    require_roles(role, ("GridOperator",))
    body = val.get_json_body()
    if "project_id" not in body or body["project_id"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: project_id")
    project_id = body["project_id"]
    project = ref_or_404(store.projects, project_id)
    period_month = val.require_string(body, "period_month")
    forecast = val.require_int(body, "forecast_production_kwh")
    if forecast < 0:
        raise err("ERR_VALIDATION", "forecast_production_kwh must be >= 0")
    # uniqueness: period_month unique per project (priority 7)
    for p in store.periods.values():
        if p["project_id"] == project_id and p["period_month"] == period_month:
            raise err("ERR_DUPLICATE_RESOURCE", "period_month already exists for project")
    # assign monotonic sequence_index per project
    existing = [p for p in store.periods.values() if p["project_id"] == project_id]
    seq_index = len(existing)
    pid = store.new_id()
    rec = {
        "id": pid,
        "_seq": store.next_seq(),
        "project_id": project_id,
        "period_month": period_month,
        "sequence_index": seq_index,
        "forecast_production_kwh": forecast,
        "metered_production_kwh": None,
        "status": "OPEN",
        "rollover_kwh": 0,
        "forfeited_kwh": 0,
        "rollover_credit_cents": 0,
        "rec_minted_count": 0,
    }
    rec.update(stamp_create())
    store.periods[pid] = rec
    # run allocation waterfall on forecast basis; create one PROVISIONAL
    # allocation per eligible subscription
    _create_provisional_allocations(rec, project)
    return response.success(svc.serialize_period(rec), status=201)


def _create_provisional_allocations(period, project):
    eligible = svc.eligible_subscriptions_for_period(period)
    for s in eligible:
        aid = store.new_id()
        alloc = {
            "id": aid,
            "_seq": store.next_seq(),
            "period_id": period["id"],
            "subscription_id": s["id"],
            "share_kw_snapshot": s["share_kw"],
            "allocated_kwh": 0,
            "provisional_credit_cents": 0,
            "final_credit_cents": None,
            "status": "PROVISIONAL",
        }
        alloc.update(stamp_create())
        store.allocations[aid] = alloc
    svc.run_waterfall(period)
    # set provisional credit cents from allocated_kwh (forecast basis)
    for a in svc.period_allocations(period["id"]):
        a["provisional_credit_cents"] = svc.provisional_credit(a["allocated_kwh"], project)


@app.route("/periods", methods=["GET"])
def list_periods():
    user_id, role = get_caller()
    require_roles(role, ALL_ROLES)
    items = list(store.periods.values())
    pid = request.args.get("project_id")
    if pid is not None:
        items = [p for p in items if p["project_id"] == pid]
    return list_response(items, svc.serialize_period)


@app.route("/periods/<rid>", methods=["GET"])
def get_period(rid):
    user_id, role = get_caller()
    require_roles(role, ALL_ROLES)
    p = get_or_404(store.periods, rid)
    return response.success(svc.serialize_period(p), status=200)


@app.route("/periods/<rid>/meter", methods=["POST"])
def meter_period(rid):
    user_id, role = get_caller()
    require_roles(role, ("GridOperator",))
    p = get_or_404(store.periods, rid)
    body = val.get_json_body()
    # required field presence (priority 5) — meter reading required (specific)
    if "metered_production_kwh" not in body or body["metered_production_kwh"] is None:
        raise err("ERR_METER_READING_REQUIRED", "metered_production_kwh required")
    metered = body["metered_production_kwh"]
    if not val.is_int(metered) or metered < 0:
        raise err("ERR_METER_READING_REQUIRED", "metered_production_kwh must be >= 0")
    if "expected_period_version" not in body or body["expected_period_version"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_period_version")
    expected_version = body["expected_period_version"]
    if not val.is_int(expected_version):
        raise err("ERR_INVALID_REQUEST", "expected_period_version must be an integer")
    # state validity (priority 8)
    if p["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Period not OPEN")
    # OCC (priority 9)
    if expected_version != p["version"]:
        raise err("ERR_STALE_PERIOD_VERSION", "expected_period_version mismatch")
    project = store.projects[p["project_id"]]
    p["metered_production_kwh"] = metered
    p["status"] = "METERED"
    # distributable switches to metered; re-run waterfall (status stays PROVISIONAL)
    svc.run_waterfall(p)
    # provisional credits remain provisional basis? PRD: only allocated_kwh
    # updated; provisional_credit_cents reflects forecast at OPEN. Per §3.8 the
    # provisional figure is subject to revision but final_credit comes at
    # reconcile. We keep provisional_credit_cents as originally computed at OPEN
    # (forecast basis) — it is not recomputed at meter.
    touch(p)
    return response.success(svc.serialize_period(p), status=200)


@app.route("/periods/<rid>/reconcile", methods=["POST"])
def reconcile_period(rid):
    user_id, role = get_caller()
    require_roles(role, ("GridOperator",))
    p = get_or_404(store.periods, rid)
    body = val.get_json_body()
    if "expected_period_version" not in body or body["expected_period_version"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_period_version")
    expected_version = body["expected_period_version"]
    if not val.is_int(expected_version):
        raise err("ERR_INVALID_REQUEST", "expected_period_version must be an integer")
    if p["status"] != "METERED":
        raise err("ERR_INVALID_STATE", "Period not METERED")
    if expected_version != p["version"]:
        raise err("ERR_STALE_PERIOD_VERSION", "expected_period_version mismatch")
    project = store.projects[p["project_id"]]
    p["status"] = "RECONCILED"
    # depth 1: allocations PROVISIONAL -> FINAL, final_credit_cents computed
    for a in svc.period_allocations(p["id"]):
        a["final_credit_cents"] = svc.final_credit(a["allocated_kwh"], project)
        a["status"] = "FINAL"
        touch(a)
    # depth 2: one Reconciliation per FINAL allocation
    for a in svc.period_allocations(p["id"]):
        if a["status"] != "FINAL":
            continue
        sub = store.subscriptions[a["subscription_id"]]
        gross = a["final_credit_cents"]
        fee = svc.tiered_program_fee(gross, sub, project)
        net = gross - fee
        rcid = store.new_id()
        recon = {
            "id": rcid,
            "_seq": store.next_seq(),
            "subscription_id": a["subscription_id"],
            "period_id": p["id"],
            "allocation_id": a["id"],
            "gross_credit_cents": gross,
            "program_fee_cents": fee,
            "net_savings_cents": net,
            "credit_status": "DRAFT",
            "dispute_status": "NONE",
        }
        recon.update(stamp_create())
        store.reconciliations[rcid] = recon
    # depth 3: mint RECBatch, recompute project rec totals
    rec_count = svc.rec_count_for_period(p)
    p["rec_minted_count"] = rec_count
    bid = store.new_id()
    batch = {
        "id": bid,
        "_seq": store.next_seq(),
        "project_id": p["project_id"],
        "period_id": p["id"],
        "rec_count": rec_count,
        "retirement_beneficiary": None,
        "transfer_counterparty": None,
        "status": "MINTED",
    }
    batch.update(stamp_create())
    store.rec_batches[bid] = batch
    svc.recompute_project_rec_totals(project)
    touch(p)
    return response.success(svc.serialize_period(p), status=200)


@app.route("/periods/<rid>/true-up", methods=["POST"])
def trueup_period(rid):
    user_id, role = get_caller()
    require_roles(role, ("GridOperator",))
    p = get_or_404(store.periods, rid)
    if p["status"] != "RECONCILED":
        raise err("ERR_INVALID_STATE", "Period not RECONCILED")
    project = store.projects[p["project_id"]]
    svc.recompute_project_ledger(project)
    p["status"] = "TRUED_UP"
    svc.trueup_sweep(p, project)
    touch(p)
    return response.success(svc.serialize_period(p), status=200)


@app.route("/periods/<rid>/reopen", methods=["POST"])
def reopen_period(rid):
    user_id, role = get_caller()
    require_roles(role, ("GridOperator",))
    p = get_or_404(store.periods, rid)
    if p["status"] != "RECONCILED":
        raise err("ERR_INVALID_STATE", "Period not RECONCILED")
    # guard: no reconciliation APPLIED (priority 17)
    recons = [r for r in store.reconciliations.values() if r["period_id"] == p["id"]]
    if any(r["credit_status"] == "APPLIED" for r in recons):
        raise err("ERR_RECON_ALREADY_APPLIED", "A reconciliation is already APPLIED")
    # delete reconciliations
    for r in recons:
        del store.reconciliations[r["id"]]
    # allocations FINAL -> PROVISIONAL, clear final_credit_cents
    for a in svc.period_allocations(p["id"]):
        a["status"] = "PROVISIONAL"
        a["final_credit_cents"] = None
        touch(a)
    # reset minted REC batch; rec_minted_count recomputed at next reconcile
    for b in list(store.rec_batches.values()):
        if b["period_id"] == p["id"]:
            del store.rec_batches[b["id"]]
    p["rec_minted_count"] = 0
    p["status"] = "METERED"
    project = store.projects[p["project_id"]]
    svc.recompute_project_rec_totals(project)
    touch(p)
    return response.success(svc.serialize_period(p), status=200)


@app.route("/periods/<rid>/close", methods=["POST"])
def close_period(rid):
    user_id, role = get_caller()
    require_roles(role, ("GridOperator",))
    p = get_or_404(store.periods, rid)
    if p["status"] != "TRUED_UP":
        raise err("ERR_INVALID_STATE", "Period not TRUED_UP")
    recons = [r for r in store.reconciliations.values() if r["period_id"] == p["id"]]
    if any(r["dispute_status"] == "DISPUTED" for r in recons):
        raise err("ERR_OPEN_DISPUTE_BLOCKS_CLOSE", "An open dispute blocks close")
    p["status"] = "CLOSED"
    touch(p)
    # recompute lifetime_savings for affected subscribers
    affected = set()
    for r in recons:
        sub = store.subscriptions.get(r["subscription_id"])
        if sub:
            affected.add(sub["subscriber_id"])
    for sid in affected:
        subscriber = store.subscribers.get(sid)
        if subscriber:
            svc.recompute_lifetime_savings(subscriber)
            touch(subscriber)
    return response.success(svc.serialize_period(p), status=200)


# ===========================================================================
# Allocation
# ===========================================================================
@app.route("/allocations", methods=["GET"])
def list_allocations():
    user_id, role = get_caller()
    require_roles(role, ALL_ROLES)
    items = list(store.allocations.values())
    period_id = request.args.get("period_id")
    subscription_id = request.args.get("subscription_id")
    if period_id is not None:
        items = [a for a in items if a["period_id"] == period_id]
    if subscription_id is not None:
        items = [a for a in items if a["subscription_id"] == subscription_id]
    return list_response(items, svc.serialize_allocation)


@app.route("/allocations/<rid>", methods=["GET"])
def get_allocation(rid):
    user_id, role = get_caller()
    require_roles(role, ALL_ROLES)
    a = get_or_404(store.allocations, rid)
    return response.success(svc.serialize_allocation(a), status=200)


# ===========================================================================
# Reconciliation
# ===========================================================================
@app.route("/reconciliations", methods=["GET"])
def list_reconciliations():
    user_id, role = get_caller()
    require_roles(role, ALL_ROLES)
    items = list(store.reconciliations.values())
    for qparam, field in (
        ("subscription_id", "subscription_id"),
        ("period_id", "period_id"),
        ("allocation_id", "allocation_id"),
    ):
        v = request.args.get(qparam)
        if v is not None:
            items = [r for r in items if r.get(field) == v]
    return list_response(items, svc.serialize_reconciliation)


@app.route("/reconciliations/<rid>", methods=["GET"])
def get_reconciliation(rid):
    user_id, role = get_caller()
    require_roles(role, ALL_ROLES)
    r = get_or_404(store.reconciliations, rid)
    return response.success(svc.serialize_reconciliation(r), status=200)


@app.route("/reconciliations/<rid>/issue", methods=["POST"])
def issue_reconciliation(rid):
    user_id, role = get_caller()
    require_roles(role, ("GridOperator",))
    r = get_or_404(store.reconciliations, rid)
    # state: credit_status DRAFT and linked period RECONCILED
    if r["credit_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Reconciliation not DRAFT")
    period = store.periods.get(r["period_id"])
    if not period or period["status"] != "RECONCILED":
        raise err("ERR_INVALID_STATE", "Linked period not RECONCILED")
    r["credit_status"] = "ISSUED"
    touch(r)
    return response.success(svc.serialize_reconciliation(r), status=200)


@app.route("/reconciliations/<rid>/apply", methods=["POST"])
def apply_reconciliation(rid):
    user_id, role = get_caller()
    require_roles(role, ("GridOperator",))
    r = get_or_404(store.reconciliations, rid)
    if r["credit_status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Reconciliation not ISSUED")
    # dispute gate (priority 15)
    if r["dispute_status"] == "DISPUTED":
        raise err("ERR_DISPUTE_BLOCKS_APPLY", "Dispute blocks apply")
    r["credit_status"] = "APPLIED"
    touch(r)
    # ledger sync: lifetime_savings and project total_net_savings
    sub = store.subscriptions.get(r["subscription_id"])
    if sub:
        subscriber = store.subscribers.get(sub["subscriber_id"])
        if subscriber:
            svc.recompute_lifetime_savings(subscriber)
            touch(subscriber)
        project = store.projects.get(sub["project_id"])
        if project:
            svc.recompute_project_net_savings(project)
            touch(project)
    return response.success(svc.serialize_reconciliation(r), status=200)


@app.route("/reconciliations/<rid>/dispute", methods=["POST"])
def dispute_reconciliation(rid):
    user_id, role = get_caller()
    require_roles(role, ("Subscriber",))
    r = get_or_404(store.reconciliations, rid)
    sub = store.subscriptions.get(r["subscription_id"])
    require_ownership(role, user_id, sub["subscriber_id"] if sub else None)
    # state validity (priority 8) — dispute_status NONE
    if r["dispute_status"] != "NONE":
        raise err("ERR_INVALID_STATE", "Reconciliation dispute_status not NONE")
    # guard: credit not already APPLIED (priority 17)
    if r["credit_status"] == "APPLIED":
        raise err("ERR_RECON_ALREADY_APPLIED", "Credit already APPLIED")
    r["dispute_status"] = "DISPUTED"
    touch(r)
    if sub:
        subscriber = store.subscribers.get(sub["subscriber_id"])
        if subscriber:
            svc.recompute_churn_risk(subscriber)
            touch(subscriber)
    return response.success(svc.serialize_reconciliation(r), status=200)


@app.route("/reconciliations/<rid>/resolve-dispute", methods=["POST"])
def resolve_dispute(rid):
    user_id, role = get_caller()
    require_roles(role, ("ProgramAdmin",))
    r = get_or_404(store.reconciliations, rid)
    if r["dispute_status"] != "DISPUTED":
        raise err("ERR_INVALID_STATE", "Reconciliation not DISPUTED")
    r["dispute_status"] = "RESOLVED"
    touch(r)
    sub = store.subscriptions.get(r["subscription_id"])
    if sub:
        subscriber = store.subscribers.get(sub["subscriber_id"])
        if subscriber:
            svc.recompute_churn_risk(subscriber)
            touch(subscriber)
    return response.success(svc.serialize_reconciliation(r), status=200)


# ===========================================================================
# RECBatch
# ===========================================================================
@app.route("/rec-batches", methods=["GET"])
def list_rec_batches():
    user_id, role = get_caller()
    require_roles(role, ("GridOperator", "ProgramAdmin"))
    items = list(store.rec_batches.values())
    project_id = request.args.get("project_id")
    period_id = request.args.get("period_id")
    if project_id is not None:
        items = [b for b in items if b["project_id"] == project_id]
    if period_id is not None:
        items = [b for b in items if b["period_id"] == period_id]
    return list_response(items, svc.serialize_rec_batch)


@app.route("/rec-batches/<rid>", methods=["GET"])
def get_rec_batch(rid):
    user_id, role = get_caller()
    require_roles(role, ("GridOperator", "ProgramAdmin"))
    b = get_or_404(store.rec_batches, rid)
    return response.success(svc.serialize_rec_batch(b), status=200)


@app.route("/rec-batches/<rid>/allocate", methods=["POST"])
def allocate_rec_batch(rid):
    user_id, role = get_caller()
    require_roles(role, ("ProgramAdmin",))
    b = get_or_404(store.rec_batches, rid)
    if b["status"] != "MINTED":
        raise err("ERR_INVALID_STATE", "REC batch not MINTED")
    b["status"] = "ALLOCATED"
    touch(b)
    return response.success(svc.serialize_rec_batch(b), status=200)


@app.route("/rec-batches/<rid>/retire", methods=["POST"])
def retire_rec_batch(rid):
    user_id, role = get_caller()
    require_roles(role, ("ProgramAdmin",))
    b = get_or_404(store.rec_batches, rid)
    if b["status"] != "ALLOCATED":
        raise err("ERR_INVALID_STATE", "REC batch not ALLOCATED")
    body = val.get_json_body()
    beneficiary = body.get("retirement_beneficiary")
    if beneficiary is None or not isinstance(beneficiary, str) or beneficiary == "":
        raise err("ERR_REC_BENEFICIARY_REQUIRED", "retirement_beneficiary required")
    b["retirement_beneficiary"] = beneficiary
    b["status"] = "RETIRED"
    touch(b)
    project = store.projects.get(b["project_id"])
    if project:
        svc.recompute_project_rec_totals(project)
        touch(project)
    return response.success(svc.serialize_rec_batch(b), status=200)


@app.route("/rec-batches/<rid>/transfer", methods=["POST"])
def transfer_rec_batch(rid):
    user_id, role = get_caller()
    require_roles(role, ("ProgramAdmin",))
    b = get_or_404(store.rec_batches, rid)
    if b["status"] != "ALLOCATED":
        raise err("ERR_INVALID_STATE", "REC batch not ALLOCATED")
    body = val.get_json_body()
    counterparty = body.get("transfer_counterparty")
    if counterparty is None or not isinstance(counterparty, str) or counterparty == "":
        raise err("ERR_REC_COUNTERPARTY_REQUIRED", "transfer_counterparty required")
    b["transfer_counterparty"] = counterparty
    b["status"] = "TRANSFERRED"
    touch(b)
    project = store.projects.get(b["project_id"])
    if project:
        svc.recompute_project_rec_totals(project)
        touch(project)
    return response.success(svc.serialize_rec_batch(b), status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
