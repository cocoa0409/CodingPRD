"""
Professional Organizer & Decluttering Service API (Task 0772)

Single-file Flask implementation. In-memory storage only (Python dicts keyed by
UUID). The store starts EMPTY on every boot; every entity is created through the
declared API surface. Boots cleanly from a fresh process on each invocation.
"""

import os
import random
import string
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory data store (keyed by id). Cleared implicitly on every fresh boot.
# ---------------------------------------------------------------------------
DB = {
    "clients": {},
    "organizers": {},
    "projects": {},
    "sessions": {},
    "items": {},
    "product_lines": {},
    "invoices": {},
    "plans": {},
}
_LOCK = threading.RLock()
_SEQ = 0


def next_seq():
    global _SEQ
    _SEQ += 1
    return _SEQ


# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD §1.3 calculation rules)
# ---------------------------------------------------------------------------
OVERTIME_THRESHOLD_HOURS = Decimal("8")
OVERTIME_MULTIPLIER = Decimal("1.5")
WEEKEND_SURCHARGE_PCT = Decimal("0.20")
DONATION_CREDIT_PCT = Decimal("0.10")
HAUL_FLAT_CENTS = 2500
MOVE_PACK_RATE_CENTS = 500
DISCOUNT_TIER_1_MIN = 200000
DISCOUNT_TIER_2_MIN = 500000
TAX_PCT = Decimal("0.08")

ROLES = {"OperationsManager", "Organizer", "BillingAdmin", "Client"}
ALL_ROLES = ["OperationsManager", "Organizer", "BillingAdmin", "Client"]

CATEGORIES = {"BIN", "SHELVING", "SYSTEM", "LABELING"}
DISPOSITIONS = {"KEEP", "HAUL", "DONATE", "SELL"}
CADENCES = {"MONTHLY": 12, "QUARTERLY": 4, "BIANNUAL": 2}
BILLING_MODES = {"HOURLY", "PROJECT"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Helpers: time, ids, rounding
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_uuid():
    import uuid
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def D(x):
    return Decimal(str(x))


def rhu(value):
    """Round half up (away from zero) to whole cents -> int."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_dt(value):
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_VALIDATION", 422, "Invalid datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "Invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Entity lifecycle helpers
# ---------------------------------------------------------------------------
def stamp_new(entity):
    ts = now_iso()
    entity["id"] = new_uuid()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def respond_object(data, status=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": data}), status


def respond_array(items, pagination):
    return (
        jsonify(
            {
                "meta": meta(pagination),
                "response_type": "array",
                "data": items,
            }
        ),
        200,
    )


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def require_auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this operation")
    return uid, role


# ---------------------------------------------------------------------------
# Body / field validation
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {name}")
    return body[name]


def val_str(v, name):
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be a string")
    return v


def val_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be an integer")
    return v


def val_number(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be a number")
    return v


def val_bool(v, name):
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be a boolean")
    return v


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def find(collection, _id, not_found_error):
    obj = DB[collection].get(_id)
    if obj is None:
        raise ApiError(not_found_error, 404, "Resource not found")
    return obj


# ---------------------------------------------------------------------------
# Ledger reconciliation (Project computed fields; SCAFFOLD §1.3 / PRD §2.6)
# ---------------------------------------------------------------------------
def _labor_hours(project_id):
    total = Decimal("0")
    for s in DB["sessions"].values():
        if s["project_id"] == project_id and s["status"] == "COMPLETED":
            total += D(s["logged_hours"])
    return float(total)


def _product_cost(project_id):
    total = 0
    for p in DB["product_lines"].values():
        if p["project_id"] == project_id and p["status"] in ("QUOTED", "ORDERED", "DELIVERED"):
            total += p["client_price_cents"]
    return total


def _haul_cost(project_id):
    total = 0
    for it in DB["items"].values():
        if it["project_id"] == project_id and it["status"] in ("SCHEDULED_HAUL", "HAULED"):
            total += it["haul_fee_cents"]
    return total


def _donation_credit(project_id):
    total = 0
    for it in DB["items"].values():
        if it["project_id"] == project_id and it["status"] == "DONATED":
            total += rhu(D(it["final_value_cents"]) * DONATION_CREDIT_PCT)
    return total


def reconcile_project(project, force_touch=False):
    """Recompute the four ledger fields; bump version if any changed."""
    pid = project["id"]
    old = (
        project["accrued_labor_hours"],
        project["projected_product_cost_cents"],
        project["projected_haul_cost_cents"],
        project["donation_credit_cents"],
    )
    project["accrued_labor_hours"] = _labor_hours(pid)
    project["projected_product_cost_cents"] = _product_cost(pid)
    project["projected_haul_cost_cents"] = _haul_cost(pid)
    project["donation_credit_cents"] = _donation_credit(pid)
    new = (
        project["accrued_labor_hours"],
        project["projected_product_cost_cents"],
        project["projected_haul_cost_cents"],
        project["donation_credit_cents"],
    )
    if force_touch or old != new:
        touch(project)


# ---------------------------------------------------------------------------
# Pagination + filtering
# ---------------------------------------------------------------------------
def parse_int_arg(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def paginate(rows):
    rows = sorted(rows, key=lambda r: r["_seq"])
    limit = parse_int_arg("limit", 10)
    offset = parse_int_arg("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(rows)
    page = rows[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return [serialize(r) for r in page], pagination


# ===========================================================================
# CLIENT
# ===========================================================================
@app.post("/clients")
def create_client():
    with _LOCK:
        require_auth(["OperationsManager"])
        body = get_body()
        full_name = val_str(require_field(body, "full_name"), "full_name")
        email = val_str(require_field(body, "email"), "email")
        home_address = val_str(require_field(body, "home_address"), "home_address")
        access_notes = body.get("access_notes", "")
        if access_notes is None:
            access_notes = ""
        access_notes = val_str(access_notes, "access_notes")
        client = {
            "full_name": full_name,
            "email": email,
            "home_address": home_address,
            "access_notes": access_notes,
        }
        stamp_new(client)
        DB["clients"][client["id"]] = client
        return respond_object(serialize(client), 201)


@app.get("/clients/<cid>")
def get_client(cid):
    with _LOCK:
        require_auth(ALL_ROLES)
        client = find("clients", cid, "ERR_CLIENT_NOT_FOUND")
        return respond_object(serialize(client), 200)


# ===========================================================================
# ORGANIZER
# ===========================================================================
@app.post("/organizers")
def create_organizer():
    with _LOCK:
        require_auth(["OperationsManager"])
        body = get_body()
        full_name = val_str(require_field(body, "full_name"), "full_name")
        email = val_str(require_field(body, "email"), "email")
        rate = val_int(require_field(body, "hourly_rate_cents"), "hourly_rate_cents")
        if rate <= 0:
            raise ApiError("ERR_VALIDATION", 422, "hourly_rate_cents must be > 0")
        active = body.get("active", True)
        if active is None:
            active = True
        active = val_bool(active, "active")
        organizer = {
            "full_name": full_name,
            "email": email,
            "hourly_rate_cents": rate,
            "active": active,
        }
        stamp_new(organizer)
        DB["organizers"][organizer["id"]] = organizer
        return respond_object(serialize(organizer), 201)


@app.get("/organizers/<oid>")
def get_organizer(oid):
    with _LOCK:
        require_auth(["OperationsManager", "Organizer", "BillingAdmin"])
        organizer = find("organizers", oid, "ERR_ORGANIZER_NOT_FOUND")
        return respond_object(serialize(organizer), 200)


# ===========================================================================
# PROJECT
# ===========================================================================
@app.post("/projects")
def create_project():
    with _LOCK:
        require_auth(["OperationsManager"])
        body = get_body()
        client_id = val_str(require_field(body, "client_id"), "client_id")
        lead_organizer_id = val_str(require_field(body, "lead_organizer_id"), "lead_organizer_id")
        title = val_str(require_field(body, "title"), "title")
        billing_mode = require_field(body, "billing_mode")
        if billing_mode not in BILLING_MODES:
            raise ApiError("ERR_VALIDATION", 422, "billing_mode must be HOURLY or PROJECT")

        flat_price_cents = body.get("flat_price_cents", 0)
        if flat_price_cents is None:
            flat_price_cents = 0
        flat_price_cents = val_int(flat_price_cents, "flat_price_cents")
        if flat_price_cents < 0:
            raise ApiError("ERR_VALIDATION", 422, "flat_price_cents must be >= 0")

        scope_rooms = body.get("scope_rooms", [])
        if scope_rooms is None:
            scope_rooms = []
        if not isinstance(scope_rooms, list) or not all(isinstance(x, str) for x in scope_rooms):
            raise ApiError("ERR_VALIDATION", 422, "scope_rooms must be an array of strings")

        move_addon_requested = body.get("move_addon_requested", False)
        if move_addon_requested is None:
            move_addon_requested = False
        move_addon_requested = val_bool(move_addon_requested, "move_addon_requested")

        move_box_count = body.get("move_box_count", 0)
        if move_box_count is None:
            move_box_count = 0
        move_box_count = val_int(move_box_count, "move_box_count")
        if move_box_count < 0:
            raise ApiError("ERR_VALIDATION", 422, "move_box_count must be >= 0")

        # Referential integrity (body FKs)
        find("clients", client_id, "ERR_CLIENT_NOT_FOUND")
        find("organizers", lead_organizer_id, "ERR_ORGANIZER_NOT_FOUND")

        project = {
            "client_id": client_id,
            "lead_organizer_id": lead_organizer_id,
            "title": title,
            "billing_mode": billing_mode,
            "flat_price_cents": flat_price_cents,
            "scope_rooms": list(scope_rooms),
            "move_addon_requested": move_addon_requested,
            "move_box_count": move_box_count,
            "status": "SCOPING",
            "accrued_labor_hours": 0,
            "projected_product_cost_cents": 0,
            "projected_haul_cost_cents": 0,
            "donation_credit_cents": 0,
        }
        stamp_new(project)
        DB["projects"][project["id"]] = project
        return respond_object(serialize(project), 201)


@app.get("/projects")
def list_projects():
    with _LOCK:
        require_auth(ALL_ROLES)
        rows = list(DB["projects"].values())
        cid = request.args.get("client_id")
        loid = request.args.get("lead_organizer_id")
        status = request.args.get("status")
        if cid is not None:
            rows = [r for r in rows if r["client_id"] == cid]
        if loid is not None:
            rows = [r for r in rows if r["lead_organizer_id"] == loid]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        items, pagination = paginate(rows)
        return respond_array(items, pagination)


@app.get("/projects/<pid>")
def get_project(pid):
    with _LOCK:
        require_auth(ALL_ROLES)
        project = find("projects", pid, "ERR_PROJECT_NOT_FOUND")
        return respond_object(serialize(project), 200)


@app.post("/projects/<pid>/activate")
def activate_project(pid):
    with _LOCK:
        require_auth(["OperationsManager"])
        project = find("projects", pid, "ERR_PROJECT_NOT_FOUND")
        if project["status"] != "SCOPING":
            raise ApiError("ERR_PROJECT_NOT_IN_SCOPING", 409, "activate requires SCOPING")
        if not project["scope_rooms"]:
            raise ApiError("ERR_SCOPE_EMPTY", 409, "scope_rooms must be non-empty")
        if project["billing_mode"] == "PROJECT" and project["flat_price_cents"] <= 0:
            raise ApiError("ERR_FLAT_PRICE_REQUIRED", 409, "flat_price_cents must be > 0")
        project["status"] = "ACTIVE"
        touch(project)
        return respond_object(serialize(project), 200)


@app.post("/projects/<pid>/cancel")
def cancel_project(pid):
    with _LOCK:
        require_auth(["OperationsManager"])
        project = find("projects", pid, "ERR_PROJECT_NOT_FOUND")
        if project["status"] in ("CLOSED", "CANCELLED"):
            raise ApiError("ERR_PROJECT_TERMINAL", 409, "Project already terminal")

        project["status"] = "CANCELLED"

        # Cascade: sessions in {SCHEDULED, IN_PROGRESS} -> CANCELLED
        for s in DB["sessions"].values():
            if s["project_id"] == pid and s["status"] in ("SCHEDULED", "IN_PROGRESS"):
                s["status"] = "CANCELLED"
                touch(s)

        # Cascade: product lines in {QUOTED, ORDERED} -> CANCELLED (ledger reversal)
        for p in DB["product_lines"].values():
            if p["project_id"] == pid and p["status"] in ("QUOTED", "ORDERED"):
                p["status"] = "CANCELLED"
                touch(p)

        # Cascade: maintenance plans in {DRAFT, ACTIVE} -> CANCELLED
        for plan in DB["plans"].values():
            if plan["project_id"] == pid and plan["status"] in ("DRAFT", "ACTIVE"):
                plan["status"] = "CANCELLED"
                touch(plan)

        # Ledger sync (product cost dropped by cancellations); single version bump
        reconcile_project(project, force_touch=True)
        return respond_object(serialize(project), 200)


# ===========================================================================
# SESSION
# ===========================================================================
@app.post("/sessions")
def create_session():
    with _LOCK:
        require_auth(["OperationsManager", "Organizer"])
        body = get_body()
        project_id = val_str(require_field(body, "project_id"), "project_id")
        organizer_id = val_str(require_field(body, "organizer_id"), "organizer_id")
        start_raw = require_field(body, "scheduled_start")
        end_raw = require_field(body, "scheduled_end")
        start_dt = parse_dt(start_raw)
        end_dt = parse_dt(end_raw)
        if end_dt <= start_dt:
            raise ApiError("ERR_VALIDATION", 422, "scheduled_end must be after scheduled_start")

        # Body FK existence
        project = find("projects", project_id, "ERR_PROJECT_NOT_FOUND")
        find("organizers", organizer_id, "ERR_ORGANIZER_NOT_FOUND")

        # Parent project state gate
        if project["status"] == "WRAP_UP":
            raise ApiError("ERR_PROJECT_NOT_ACTIVE", 409, "Project not accepting new sessions")
        if project["status"] in ("CLOSED", "CANCELLED"):
            raise ApiError("ERR_PROJECT_TERMINAL", 409, "Project is terminal")

        buffer = timedelta(minutes=30)
        # Organizer double-booking check (evaluated first)
        for s in DB["sessions"].values():
            if s["organizer_id"] != organizer_id or s["status"] == "CANCELLED":
                continue
            o_start = parse_dt(s["scheduled_start"])
            o_end = parse_dt(s["scheduled_end"])
            if start_dt < o_end + buffer and o_start < end_dt + buffer:
                raise ApiError("ERR_ORGANIZER_DOUBLE_BOOKED", 409, "Organizer double-booked")

        # Client home whole-day exclusivity (evaluated second)
        client_id = project["client_id"]
        new_date = start_dt.date()
        for s in DB["sessions"].values():
            if s["status"] == "CANCELLED":
                continue
            sp = DB["projects"].get(s["project_id"])
            if sp is None or sp["client_id"] != client_id:
                continue
            if parse_dt(s["scheduled_start"]).date() == new_date:
                raise ApiError("ERR_CLIENT_HOME_DOUBLE_BOOKED", 409, "Client already booked that day")

        session = {
            "project_id": project_id,
            "organizer_id": organizer_id,
            "scheduled_start": start_raw,
            "scheduled_end": end_raw,
            "logged_hours": 0,
            "labor_cost_cents": 0,
            "is_overtime": False,
            "status": "SCHEDULED",
        }
        stamp_new(session)
        DB["sessions"][session["id"]] = session
        return respond_object(serialize(session), 201)


@app.get("/sessions")
def list_sessions():
    with _LOCK:
        require_auth(ALL_ROLES)
        rows = list(DB["sessions"].values())
        pid = request.args.get("project_id")
        oid = request.args.get("organizer_id")
        status = request.args.get("status")
        if pid is not None:
            rows = [r for r in rows if r["project_id"] == pid]
        if oid is not None:
            rows = [r for r in rows if r["organizer_id"] == oid]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        items, pagination = paginate(rows)
        return respond_array(items, pagination)


@app.get("/sessions/<sid>")
def get_session(sid):
    with _LOCK:
        require_auth(ALL_ROLES)
        session = find("sessions", sid, "ERR_SESSION_NOT_FOUND")
        return respond_object(serialize(session), 200)


def _compute_labor_cost(session, organizer):
    rate = D(organizer["hourly_rate_cents"])
    lh = D(session["logged_hours"])
    base = min(lh, OVERTIME_THRESHOLD_HOURS)
    ot = max(lh - OVERTIME_THRESHOLD_HOURS, Decimal("0"))
    is_overtime = lh > OVERTIME_THRESHOLD_HOURS
    regular = rhu(base * rate)
    overtime = rhu(ot * rate * OVERTIME_MULTIPLIER)
    subtotal = regular + overtime
    start_dt = parse_dt(session["scheduled_start"])
    if start_dt.weekday() in (5, 6):  # Sat=5, Sun=6
        labor = rhu(D(subtotal) * (Decimal("1") + WEEKEND_SURCHARGE_PCT))
    else:
        labor = subtotal
    return labor, is_overtime


@app.post("/sessions/<sid>/complete")
def complete_session(sid):
    with _LOCK:
        uid, role = require_auth(["Organizer"])
        body = get_body()
        logged = require_field(body, "logged_hours")
        logged = val_number(logged, "logged_hours")
        if logged < 0:
            raise ApiError("ERR_VALIDATION", 422, "logged_hours must be >= 0")

        session = find("sessions", sid, "ERR_SESSION_NOT_FOUND")
        # Ownership: assigned organizer only
        if session["organizer_id"] != uid:
            raise ApiError("ERR_FORBIDDEN", 403, "Only the assigned organizer may complete")

        project = find("projects", session["project_id"], "ERR_PROJECT_NOT_FOUND")
        if session["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_SESSION_TRANSITION", 409, "Session not in progress")
        if project["status"] != "ACTIVE":
            raise ApiError("ERR_PROJECT_NOT_ACTIVE", 409, "Project not active")

        session["logged_hours"] = logged
        labor, is_overtime = _compute_labor_cost(session, DB["organizers"][session["organizer_id"]])
        session["labor_cost_cents"] = labor
        session["is_overtime"] = is_overtime
        session["status"] = "COMPLETED"
        touch(session)
        reconcile_project(project)
        return respond_object(serialize(session), 200)


@app.patch("/sessions/<sid>")
def patch_session(sid):
    with _LOCK:
        require_auth(["OperationsManager", "Organizer"])
        body = get_body()
        target = require_field(body, "status")
        if target not in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"):
            raise ApiError("ERR_VALIDATION", 422, "Invalid status value")

        session = find("sessions", sid, "ERR_SESSION_NOT_FOUND")
        project = find("projects", session["project_id"], "ERR_PROJECT_NOT_FOUND")
        current = session["status"]

        if target == "IN_PROGRESS":
            if current != "SCHEDULED":
                raise ApiError("ERR_INVALID_SESSION_TRANSITION", 409, "Cannot start session")
            if project["status"] != "ACTIVE":
                raise ApiError("ERR_PROJECT_NOT_ACTIVE", 409, "Project not active")
            session["status"] = "IN_PROGRESS"
            touch(session)
            return respond_object(serialize(session), 200)

        if target == "CANCELLED":
            if current in ("SCHEDULED", "IN_PROGRESS"):
                session["status"] = "CANCELLED"
                touch(session)
                return respond_object(serialize(session), 200)
            if current == "COMPLETED":
                # Compensating void
                session["status"] = "CANCELLED"
                session["labor_cost_cents"] = 0
                touch(session)
                reconcile_project(project)
                return respond_object(serialize(session), 200)
            raise ApiError("ERR_INVALID_SESSION_TRANSITION", 409, "Cannot cancel from current state")

        raise ApiError("ERR_INVALID_SESSION_TRANSITION", 409, "Unsupported session transition")


# ===========================================================================
# INVENTORY ITEM
# ===========================================================================
@app.post("/inventory-items")
def create_item():
    with _LOCK:
        require_auth(["Organizer"])
        body = get_body()
        project_id = val_str(require_field(body, "project_id"), "project_id")
        room_label = val_str(require_field(body, "room_label"), "room_label")
        description = val_str(require_field(body, "description"), "description")
        disposition = require_field(body, "disposition")
        if disposition not in DISPOSITIONS:
            raise ApiError("ERR_VALIDATION", 422, "Invalid disposition")
        estimated = body.get("estimated_value_cents", 0)
        if estimated is None:
            estimated = 0
        estimated = val_int(estimated, "estimated_value_cents")
        if estimated < 0:
            raise ApiError("ERR_VALIDATION", 422, "estimated_value_cents must be >= 0")

        find("projects", project_id, "ERR_PROJECT_NOT_FOUND")

        status = "KEPT" if disposition == "KEEP" else "LOGGED"
        item = {
            "project_id": project_id,
            "room_label": room_label,
            "description": description,
            "disposition": disposition,
            "estimated_value_cents": estimated,
            "final_value_cents": 0,
            "haul_fee_cents": 0,
            "status": status,
        }
        stamp_new(item)
        DB["items"][item["id"]] = item
        return respond_object(serialize(item), 201)


@app.get("/inventory-items")
def list_items():
    with _LOCK:
        require_auth(ALL_ROLES)
        rows = list(DB["items"].values())
        pid = request.args.get("project_id")
        disposition = request.args.get("disposition")
        status = request.args.get("status")
        if pid is not None:
            rows = [r for r in rows if r["project_id"] == pid]
        if disposition is not None:
            rows = [r for r in rows if r["disposition"] == disposition]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        items, pagination = paginate(rows)
        return respond_array(items, pagination)


@app.get("/inventory-items/<iid>")
def get_item(iid):
    with _LOCK:
        require_auth(ALL_ROLES)
        item = find("items", iid, "ERR_ITEM_NOT_FOUND")
        return respond_object(serialize(item), 200)


@app.post("/inventory-items/<iid>/schedule")
def schedule_item(iid):
    with _LOCK:
        require_auth(["Organizer"])
        item = find("items", iid, "ERR_ITEM_NOT_FOUND")
        if item["status"] != "LOGGED":
            raise ApiError("ERR_INVALID_ITEM_TRANSITION", 409, "Item not schedulable")
        project = find("projects", item["project_id"], "ERR_PROJECT_NOT_FOUND")

        if item["disposition"] in ("HAUL", "SELL"):
            item["haul_fee_cents"] = HAUL_FLAT_CENTS
            item["status"] = "SCHEDULED_HAUL"
            touch(item)
            reconcile_project(project)
        elif item["disposition"] == "DONATE":
            # Provisional credit is planning-only; not added to any ledger.
            item["status"] = "SCHEDULED_DONATION"
            touch(item)
        else:
            raise ApiError("ERR_DISPOSITION_MISMATCH", 409, "Disposition cannot be scheduled")
        return respond_object(serialize(item), 200)


@app.post("/inventory-items/<iid>/confirm")
def confirm_item(iid):
    with _LOCK:
        require_auth(["Organizer"])
        body = get_body()
        item = find("items", iid, "ERR_ITEM_NOT_FOUND")
        project = find("projects", item["project_id"], "ERR_PROJECT_NOT_FOUND")

        if item["status"] == "SCHEDULED_HAUL":
            item["status"] = "HAULED"
            touch(item)
            return respond_object(serialize(item), 200)

        if item["status"] == "SCHEDULED_DONATION":
            final_value = body.get("final_value_cents", 0)
            if final_value is None:
                final_value = 0
            final_value = val_int(final_value, "final_value_cents")
            if final_value < 0:
                raise ApiError("ERR_VALIDATION", 422, "final_value_cents must be >= 0")
            item["final_value_cents"] = final_value
            item["status"] = "DONATED"
            touch(item)
            reconcile_project(project)
            return respond_object(serialize(item), 200)

        raise ApiError("ERR_INVALID_ITEM_TRANSITION", 409, "Item cannot be confirmed")


# ===========================================================================
# PRODUCT LINE
# ===========================================================================
@app.post("/product-lines")
def create_product_line():
    with _LOCK:
        require_auth(["Organizer"])
        body = get_body()
        project_id = val_str(require_field(body, "project_id"), "project_id")
        product_name = val_str(require_field(body, "product_name"), "product_name")
        category = require_field(body, "category")
        if category not in CATEGORIES:
            raise ApiError("ERR_VALIDATION", 422, "Invalid category")
        wholesale = val_int(require_field(body, "wholesale_cost_cents"), "wholesale_cost_cents")
        if wholesale <= 0:
            raise ApiError("ERR_VALIDATION", 422, "wholesale_cost_cents must be > 0")
        quantity = val_int(require_field(body, "quantity"), "quantity")
        if quantity < 1:
            raise ApiError("ERR_VALIDATION", 422, "quantity must be >= 1")
        markup = val_number(require_field(body, "markup_pct"), "markup_pct")
        if markup < 0:
            raise ApiError("ERR_VALIDATION", 422, "markup_pct must be >= 0")

        project = find("projects", project_id, "ERR_PROJECT_NOT_FOUND")

        per_unit = rhu(D(wholesale) * (Decimal("1") + D(markup)))
        client_price = per_unit * quantity

        line = {
            "project_id": project_id,
            "product_name": product_name,
            "category": category,
            "wholesale_cost_cents": wholesale,
            "quantity": quantity,
            "markup_pct": markup,
            "client_price_cents": client_price,
            "status": "QUOTED",
        }
        stamp_new(line)
        DB["product_lines"][line["id"]] = line
        reconcile_project(project)
        return respond_object(serialize(line), 201)


@app.get("/product-lines")
def list_product_lines():
    with _LOCK:
        require_auth(ALL_ROLES)
        rows = list(DB["product_lines"].values())
        pid = request.args.get("project_id")
        status = request.args.get("status")
        if pid is not None:
            rows = [r for r in rows if r["project_id"] == pid]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        items, pagination = paginate(rows)
        return respond_array(items, pagination)


@app.get("/product-lines/<plid>")
def get_product_line(plid):
    with _LOCK:
        require_auth(ALL_ROLES)
        line = find("product_lines", plid, "ERR_PRODUCT_NOT_FOUND")
        return respond_object(serialize(line), 200)


@app.patch("/product-lines/<plid>")
def patch_product_line(plid):
    with _LOCK:
        require_auth(["Organizer", "OperationsManager"])
        body = get_body()
        target = require_field(body, "status")
        if target not in ("QUOTED", "ORDERED", "DELIVERED", "CANCELLED"):
            raise ApiError("ERR_VALIDATION", 422, "Invalid status value")

        line = find("product_lines", plid, "ERR_PRODUCT_NOT_FOUND")
        project = find("projects", line["project_id"], "ERR_PROJECT_NOT_FOUND")
        current = line["status"]

        if target == "ORDERED":
            if current != "QUOTED":
                raise ApiError("ERR_INVALID_PRODUCT_TRANSITION", 409, "Cannot order")
            line["status"] = "ORDERED"
            touch(line)
            return respond_object(serialize(line), 200)

        if target == "DELIVERED":
            if current != "ORDERED":
                raise ApiError("ERR_INVALID_PRODUCT_TRANSITION", 409, "Cannot deliver")
            line["status"] = "DELIVERED"
            touch(line)
            return respond_object(serialize(line), 200)

        if target == "CANCELLED":
            if current not in ("QUOTED", "ORDERED"):
                raise ApiError("ERR_INVALID_PRODUCT_TRANSITION", 409, "Cannot cancel")
            line["status"] = "CANCELLED"
            touch(line)
            reconcile_project(project)  # compensating ledger reversal
            return respond_object(serialize(line), 200)

        raise ApiError("ERR_INVALID_PRODUCT_TRANSITION", 409, "Unsupported transition")


# ===========================================================================
# INVOICE
# ===========================================================================
def _compute_invoice(project):
    pid = project["id"]
    product_subtotal = sum(
        p["client_price_cents"]
        for p in DB["product_lines"].values()
        if p["project_id"] == pid and p["status"] in ("ORDERED", "DELIVERED")
    )
    haul_subtotal = sum(
        it["haul_fee_cents"]
        for it in DB["items"].values()
        if it["project_id"] == pid and it["status"] in ("SCHEDULED_HAUL", "HAULED")
    )
    donation_credit = sum(
        rhu(D(it["final_value_cents"]) * DONATION_CREDIT_PCT)
        for it in DB["items"].values()
        if it["project_id"] == pid and it["status"] == "DONATED"
    )
    move_addon = (
        project["move_box_count"] * MOVE_PACK_RATE_CENTS
        if project["move_addon_requested"]
        else 0
    )
    if project["billing_mode"] == "HOURLY":
        labor_subtotal = sum(
            s["labor_cost_cents"]
            for s in DB["sessions"].values()
            if s["project_id"] == pid and s["status"] == "COMPLETED"
        )
    else:  # PROJECT
        labor_subtotal = project["flat_price_cents"]

    subtotal = labor_subtotal + product_subtotal + haul_subtotal + move_addon - donation_credit
    if subtotal >= DISCOUNT_TIER_2_MIN:
        discount_pct = Decimal("0.10")
    elif subtotal >= DISCOUNT_TIER_1_MIN:
        discount_pct = Decimal("0.05")
    else:
        discount_pct = Decimal("0")
    discount = rhu(D(subtotal) * discount_pct)
    taxable = subtotal - discount
    tax = rhu(D(taxable) * TAX_PCT)
    grand_total = taxable + tax

    return {
        "billing_mode": project["billing_mode"],
        "labor_subtotal_cents": labor_subtotal,
        "product_subtotal_cents": product_subtotal,
        "haul_subtotal_cents": haul_subtotal,
        "donation_credit_cents": donation_credit,
        "move_addon_cents": move_addon,
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "tax_cents": tax,
        "grand_total_cents": grand_total,
    }


@app.post("/invoices")
def create_invoice():
    with _LOCK:
        require_auth(["BillingAdmin"])
        body = get_body()
        project_id = val_str(require_field(body, "project_id"), "project_id")
        expected_version = val_int(require_field(body, "expected_project_version"), "expected_project_version")

        project = find("projects", project_id, "ERR_PROJECT_NOT_FOUND")

        # Business checks (PRD §3.7 order): terminal -> OCC -> active -> unresolved -> billable
        if project["status"] in ("CLOSED", "CANCELLED"):
            raise ApiError("ERR_PROJECT_TERMINAL", 409, "Project is terminal")
        if expected_version != project["version"]:
            raise ApiError("ERR_STALE_PROJECT_VERSION", 412, "Stale project version")
        if project["status"] != "ACTIVE":
            raise ApiError("ERR_PROJECT_NOT_ACTIVE", 409, "Project not active")

        for s in DB["sessions"].values():
            if s["project_id"] == project_id and s["status"] in ("SCHEDULED", "IN_PROGRESS"):
                raise ApiError("ERR_UNRESOLVED_SESSIONS", 409, "Unresolved sessions exist")

        if project["billing_mode"] == "HOURLY":
            has_completed = any(
                s["project_id"] == project_id and s["status"] == "COMPLETED"
                for s in DB["sessions"].values()
            )
            if not has_completed:
                raise ApiError("ERR_NO_BILLABLE_WORK", 422, "No completed sessions to bill")
        else:  # PROJECT
            if project["flat_price_cents"] <= 0:
                raise ApiError("ERR_NO_BILLABLE_WORK", 422, "flat_price_cents must be > 0")

        computed = _compute_invoice(project)
        invoice = {
            "project_id": project_id,
            "expected_project_version": expected_version,
            "status": "ISSUED",
        }
        invoice.update(computed)
        stamp_new(invoice)
        DB["invoices"][invoice["id"]] = invoice

        # Project ACTIVE -> WRAP_UP (version bump)
        project["status"] = "WRAP_UP"
        touch(project)
        return respond_object(serialize(invoice), 201)


@app.get("/invoices")
def list_invoices():
    with _LOCK:
        require_auth(["OperationsManager", "BillingAdmin", "Client"])
        rows = list(DB["invoices"].values())
        pid = request.args.get("project_id")
        status = request.args.get("status")
        if pid is not None:
            rows = [r for r in rows if r["project_id"] == pid]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        items, pagination = paginate(rows)
        return respond_array(items, pagination)


@app.get("/invoices/<iid>")
def get_invoice(iid):
    with _LOCK:
        require_auth(["OperationsManager", "BillingAdmin", "Client"])
        invoice = find("invoices", iid, "ERR_INVOICE_NOT_FOUND")
        return respond_object(serialize(invoice), 200)


def _check_invoice_client_ownership(invoice, uid, role):
    if role == "Client":
        project = DB["projects"].get(invoice["project_id"])
        if project is None or project["client_id"] != uid:
            raise ApiError("ERR_FORBIDDEN", 403, "Client does not own this invoice")


@app.post("/invoices/<iid>/pay")
def pay_invoice(iid):
    with _LOCK:
        uid, role = require_auth(["BillingAdmin", "Client"])
        invoice = find("invoices", iid, "ERR_INVOICE_NOT_FOUND")
        _check_invoice_client_ownership(invoice, uid, role)
        if invoice["status"] != "ISSUED":
            raise ApiError("ERR_INVOICE_NOT_PAYABLE", 409, "Invoice not payable")

        invoice["status"] = "PAID"
        touch(invoice)

        # Cascade: project WRAP_UP -> CLOSED -> maintenance plan DRAFT -> ACTIVE
        project = DB["projects"].get(invoice["project_id"])
        if project is not None and project["status"] == "WRAP_UP":
            project["status"] = "CLOSED"
            touch(project)
            for plan in DB["plans"].values():
                if plan["project_id"] == project["id"] and plan["status"] == "DRAFT":
                    plan["status"] = "ACTIVE"
                    touch(plan)
        return respond_object(serialize(invoice), 200)


@app.patch("/invoices/<iid>")
def patch_invoice(iid):
    with _LOCK:
        uid, role = require_auth(["BillingAdmin", "Client"])
        body = get_body()
        target = require_field(body, "status")
        if target not in ("ISSUED", "DISPUTED", "PAID"):
            raise ApiError("ERR_VALIDATION", 422, "Invalid status value")

        invoice = find("invoices", iid, "ERR_INVOICE_NOT_FOUND")
        _check_invoice_client_ownership(invoice, uid, role)
        current = invoice["status"]

        if target == "DISPUTED":
            if current != "ISSUED":
                raise ApiError("ERR_INVALID_INVOICE_TRANSITION", 409, "Cannot dispute")
            invoice["status"] = "DISPUTED"
            touch(invoice)
            return respond_object(serialize(invoice), 200)

        if target == "ISSUED":
            if current != "DISPUTED":
                raise ApiError("ERR_INVALID_INVOICE_TRANSITION", 409, "Cannot resolve")
            invoice["status"] = "ISSUED"
            touch(invoice)
            return respond_object(serialize(invoice), 200)

        raise ApiError("ERR_INVALID_INVOICE_TRANSITION", 409, "Unsupported invoice transition")


# ===========================================================================
# MAINTENANCE PLAN
# ===========================================================================
@app.post("/maintenance-plans")
def create_plan():
    with _LOCK:
        require_auth(["OperationsManager"])
        body = get_body()
        project_id = val_str(require_field(body, "project_id"), "project_id")
        cadence = require_field(body, "cadence")
        if cadence not in CADENCES:
            raise ApiError("ERR_VALIDATION", 422, "Invalid cadence")
        monthly_fee = val_int(require_field(body, "monthly_fee_cents"), "monthly_fee_cents")
        if monthly_fee < 0:
            raise ApiError("ERR_VALIDATION", 422, "monthly_fee_cents must be >= 0")
        note = body.get("next_followup_note", "")
        if note is None:
            note = ""
        note = val_str(note, "next_followup_note")

        find("projects", project_id, "ERR_PROJECT_NOT_FOUND")

        plan = {
            "project_id": project_id,
            "cadence": cadence,
            "monthly_fee_cents": monthly_fee,
            "visits_per_year": CADENCES[cadence],
            "next_followup_note": note,
            "status": "DRAFT",
        }
        stamp_new(plan)
        DB["plans"][plan["id"]] = plan
        return respond_object(serialize(plan), 201)


@app.get("/maintenance-plans")
def list_plans():
    with _LOCK:
        require_auth(["OperationsManager", "BillingAdmin", "Client"])
        rows = list(DB["plans"].values())
        pid = request.args.get("project_id")
        status = request.args.get("status")
        if pid is not None:
            rows = [r for r in rows if r["project_id"] == pid]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        items, pagination = paginate(rows)
        return respond_array(items, pagination)


@app.get("/maintenance-plans/<plid>")
def get_plan(plid):
    with _LOCK:
        require_auth(["OperationsManager", "BillingAdmin", "Client"])
        plan = find("plans", plid, "ERR_PLAN_NOT_FOUND")
        return respond_object(serialize(plan), 200)


@app.patch("/maintenance-plans/<plid>")
def patch_plan(plid):
    with _LOCK:
        require_auth(["OperationsManager"])
        body = get_body()
        target = require_field(body, "status")
        if target not in ("DRAFT", "ACTIVE", "CANCELLED"):
            raise ApiError("ERR_VALIDATION", 422, "Invalid status value")

        plan = find("plans", plid, "ERR_PLAN_NOT_FOUND")
        current = plan["status"]

        if target == "CANCELLED":
            if current not in ("DRAFT", "ACTIVE"):
                raise ApiError("ERR_INVALID_PLAN_TRANSITION", 409, "Cannot cancel")
            plan["status"] = "CANCELLED"
            touch(plan)
            return respond_object(serialize(plan), 200)

        raise ApiError("ERR_INVALID_PLAN_TRANSITION", 409, "Unsupported plan transition")


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
