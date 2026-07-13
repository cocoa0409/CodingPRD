"""Community Garden & Plot Allocation API (Flask, in-memory)."""
import os
import random
import string
import functools

from flask import Flask, request, jsonify, g

import store
from store import (
    now,
    iso,
    parse_dt,
    new_id,
)

app = Flask(__name__, static_folder=None)

ROLES = {"Gardener", "GardenManager", "Treasurer"}


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": "req_"
        + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": iso(now()),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, limit, offset, total_count):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def _handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def _handle_404(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require(*allowed_roles):
    """Decorator: validate auth headers and role membership before the handler."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid credentials")
            if role not in allowed_roles:
                raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def own_or_403(gardener_id):
    """For Gardener-owned actions, X-User-ID must equal the resource gardener_id."""
    if g.role == "Gardener" and g.user_id != gardener_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Gardener does not own this resource")


# ---------------------------------------------------------------------------
# Body / query parsing helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return data


def verr(msg="Invalid request body"):
    raise ApiError("ERR_VALIDATION", 422, msg)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        verr("Field '%s' is required" % field)
    return v


def req_enum(data, field, allowed):
    v = req_str(data, field)
    if v not in allowed:
        verr("Field '%s' must be one of %s" % (field, sorted(allowed)))
    return v


def req_dt(data, field):
    if field not in data or data.get(field) is None:
        verr("Field '%s' is required" % field)
    try:
        return parse_dt(data[field])
    except (ValueError, TypeError):
        verr("Field '%s' must be an ISO-8601 datetime" % field)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float))) and not isinstance(v, bool)


def req_int(data, field):
    v = data.get(field)
    if not _is_int(v):
        verr("Field '%s' must be an integer" % field)
    return v


def pagination():
    limit = request.args.get("limit", "10")
    offset = request.args.get("offset", "0")
    try:
        limit = int(limit)
        offset = int(offset)
    except (ValueError, TypeError):
        verr("limit/offset must be integers")
    if limit < 1 or limit > 100:
        verr("limit must be between 1 and 100")
    if offset < 0:
        verr("offset must be >= 0")
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    rows = sorted(rows, key=lambda r: (r["created_at"], r["id"]))
    total = len(rows)
    window = rows[offset : offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_garden(gid):
    obj = store.gardens.get(gid)
    if obj is None:
        raise ApiError("ERR_GARDEN_NOT_FOUND", 404, "Garden not found")
    return obj


def get_plot(pid):
    obj = store.plots.get(pid)
    if obj is None:
        raise ApiError("ERR_PLOT_NOT_FOUND", 404, "Plot not found")
    return obj


def get_gardener(gid):
    obj = store.gardeners.get(gid)
    if obj is None:
        raise ApiError("ERR_GARDENER_NOT_FOUND", 404, "Gardener not found")
    return obj


def get_application(aid):
    obj = store.applications.get(aid)
    if obj is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "Application not found")
    return obj


def get_assignment(aid):
    obj = store.assignments.get(aid)
    if obj is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404, "Assignment not found")
    return obj


def get_compliance_case(cid):
    obj = store.compliance_cases.get(cid)
    if obj is None:
        raise ApiError("ERR_COMPLIANCE_CASE_NOT_FOUND", 404, "Compliance case not found")
    return obj


def get_tool(tid):
    obj = store.tools.get(tid)
    if obj is None:
        raise ApiError("ERR_TOOL_NOT_FOUND", 404, "Tool not found")
    return obj


def get_tool_loan(lid):
    obj = store.tool_loans.get(lid)
    if obj is None:
        raise ApiError("ERR_TOOL_LOAN_NOT_FOUND", 404, "Tool loan not found")
    return obj


def touch(entity):
    entity["updated_at"] = now()
    entity["version"] += 1


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
@require("GardenManager")
def clock_set():
    data = body()
    dt = req_dt(data, "to_iso8601")
    store.set_clock(dt)
    return ok({}, 200)


# ===========================================================================
# Garden
# ===========================================================================
@app.route("/gardens", methods=["POST"])
@require("GardenManager")
def create_garden():
    data = body()
    name = req_str(data, "name")
    season_label = req_str(data, "season_label")
    season_start = req_dt(data, "season_start")
    season_end = req_dt(data, "season_end")
    offer_window_days = 7
    if "offer_window_days" in data and data.get("offer_window_days") is not None:
        offer_window_days = req_int(data, "offer_window_days")
        if offer_window_days < 1:
            verr("offer_window_days must be >= 1")
    ts = now()
    obj = {
        "id": new_id(),
        "name": name,
        "season_label": season_label,
        "season_start": season_start,
        "season_end": season_end,
        "offer_window_days": offer_window_days,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.gardens[obj["id"]] = obj
    return ok(store.ser_garden(obj), 201)


@app.route("/gardens/<gid>", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def read_garden(gid):
    return ok(store.ser_garden(get_garden(gid)), 200)


@app.route("/gardens/<gid>/tools", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def list_garden_tools(gid):
    get_garden(gid)
    category = request.args.get("category")
    rows = [t for t in store.tools.values() if t["garden_id"] == gid]
    if category:
        rows = [t for t in rows if t["category"] == category]
    return paginate(rows, store.ser_tool)


@app.route("/gardens/<gid>/shed-bookings", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def list_garden_shed_bookings(gid):
    get_garden(gid)
    rows = [b for b in store.shed_bookings.values() if b["garden_id"] == gid]
    return paginate(rows, store.ser_shed_booking)


@app.route("/gardens/<gid>/expire-offers", methods=["POST"])
@require("GardenManager")
def expire_offers(gid):
    get_garden(gid)
    expired = []
    for a in store.applications.values():
        if (
            a["garden_id"] == gid
            and a["status"] == "OFFERED"
            and a["offer_expires_at"] is not None
            and a["offer_expires_at"] < now()
        ):
            plot = store.plots.get(a["offered_plot_id"])
            a["status"] = "EXPIRED"
            a["offered_plot_id"] = None
            a["offer_expires_at"] = None
            touch(a)
            if plot is not None and plot["status"] == "RESERVED":
                plot["status"] = "AVAILABLE"
                touch(plot)
            expired.append(a)
    expired.sort(key=lambda r: (r["created_at"], r["id"]))
    data = [store.ser_application(a) for a in expired]
    from flask import jsonify as _jsonify

    body_out = {"meta": _meta(), "response_type": "array", "data": data}
    return _jsonify(body_out), 200


# ===========================================================================
# Plot
# ===========================================================================
@app.route("/plots", methods=["POST"])
@require("GardenManager")
def create_plot():
    data = body()
    garden_id = req_str(data, "garden_id")
    get_garden(garden_id)
    label = req_str(data, "label")
    size = req_enum(data, "size", store.SIZES)
    ts = now()
    obj = {
        "id": new_id(),
        "garden_id": garden_id,
        "label": label,
        "size": size,
        "status": "AVAILABLE",
        "current_assignment_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.plots[obj["id"]] = obj
    return ok(store.ser_plot(obj), 201)


@app.route("/plots/<pid>", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def read_plot(pid):
    return ok(store.ser_plot(get_plot(pid)), 200)


@app.route("/plots", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def list_plots():
    rows = list(store.plots.values())
    garden_id = request.args.get("garden_id")
    status = request.args.get("status")
    size = request.args.get("size")
    if garden_id:
        rows = [p for p in rows if p["garden_id"] == garden_id]
    if status:
        rows = [p for p in rows if p["status"] == status]
    if size:
        rows = [p for p in rows if p["size"] == size]
    return paginate(rows, store.ser_plot)


# --- allocation helpers -----------------------------------------------------
def _select_top_candidate(plot):
    """Top-ranked WAITLISTED application for (plot.garden_id, plot.size) or None."""
    candidates = [
        a
        for a in store.applications.values()
        if a["status"] == "WAITLISTED"
        and a["garden_id"] == plot["garden_id"]
        and a["requested_size"] == plot["size"]
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda a: (
            -store.priority_score(store.gardeners[a["gardener_id"]]),
            a["created_at"],
            a["id"],
        )
    )
    return candidates[0]


def _make_offer(plot, application):
    application["status"] = "OFFERED"
    application["offered_plot_id"] = plot["id"]
    application["offer_expires_at"] = now() + _timedelta_days(
        store.gardens[plot["garden_id"]]["offer_window_days"]
    )
    touch(application)
    plot["status"] = "RESERVED"
    touch(plot)


def _timedelta_days(days):
    from datetime import timedelta

    return timedelta(days=days)


def _create_assignment(plot, gardener, garden, application_id, renewed_from=None):
    ts = now()
    size = plot["size"]
    prov = store.provisional_fee_cents(size)
    obj = {
        "id": new_id(),
        "plot_id": plot["id"],
        "gardener_id": gardener["id"],
        "garden_id": garden["id"],
        "application_id": application_id,
        "renewed_from_assignment_id": renewed_from,
        "season_start": garden["season_start"],
        "season_end": garden["season_end"],
        "size": size,
        "occupancy_status": "ACTIVE",
        "fee_status": "UNPAID",
        "provisional_fee_cents": prov,
        "final_fee_cents": None,
        "required_work_hours": store.REQUIRED_WORK_HOURS[size],
        "logged_work_hours": 0,
        "_paid_amount_cents": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.assignments[obj["id"]] = obj
    gardener["balance_owed_cents"] += prov
    touch(gardener)
    return obj


@app.route("/plots/<pid>/offer", methods=["POST"])
@require("GardenManager")
def offer_plot(pid):
    plot = get_plot(pid)
    if plot["status"] != "AVAILABLE":
        raise ApiError("ERR_PLOT_NOT_AVAILABLE", 409, "Plot is not available")
    candidate = _select_top_candidate(plot)
    if candidate is None:
        raise ApiError("ERR_NO_ELIGIBLE_APPLICANT", 409, "No eligible waitlisted applicant")
    _make_offer(plot, candidate)
    return ok(store.ser_application(candidate), 200)


@app.route("/plots/<pid>/assign", methods=["POST"])
@require("GardenManager")
def assign_plot(pid):
    plot = get_plot(pid)
    data = body()
    gardener_id = req_str(data, "gardener_id")
    gardener = get_gardener(gardener_id)
    if "expected_plot_version" not in data or data.get("expected_plot_version") is None:
        verr("expected_plot_version is required")
    expected = req_int(data, "expected_plot_version")
    if plot["status"] != "AVAILABLE":
        raise ApiError("ERR_PLOT_NOT_AVAILABLE", 409, "Plot is not available")
    if expected != plot["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Plot version is stale")
    garden = store.gardens[plot["garden_id"]]
    _assert_no_season_conflict(plot, garden)
    assignment = _create_assignment(plot, gardener, garden, application_id=None)
    plot["status"] = "ASSIGNED"
    plot["current_assignment_id"] = assignment["id"]
    touch(plot)
    return ok(store.ser_assignment(assignment), 201)


def _assert_no_season_conflict(plot, garden):
    s_start = garden["season_start"]
    s_end = garden["season_end"]
    for a in store.assignments.values():
        if a["plot_id"] != plot["id"]:
            continue
        if a["occupancy_status"] in ("RENEWED", "ENDED", "FORFEITED"):
            continue
        # half-open overlap: a.start < s_end and s_start < a.end
        if a["season_start"] < s_end and s_start < a["season_end"]:
            raise ApiError("ERR_PLOT_SEASON_CONFLICT", 409, "Season overlaps existing assignment")


# ===========================================================================
# Gardener
# ===========================================================================
@app.route("/gardeners", methods=["POST"])
@require("GardenManager")
def create_gardener():
    data = body()
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    for existing in store.gardeners.values():
        if existing["email"] == email:
            raise ApiError("ERR_DUPLICATE_EMAIL", 409, "Email already registered")
    ts = now()
    obj = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "tenure_seasons": 0,
        "standing": "GOOD",
        "strike_count": 0,
        "balance_owed_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.gardeners[obj["id"]] = obj
    return ok(store.ser_gardener(obj), 201)


@app.route("/gardeners/<gid>", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def read_gardener(gid):
    return ok(store.ser_gardener(get_gardener(gid)), 200)


@app.route("/gardeners/<gid>/shed-bookings", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def list_gardener_shed_bookings(gid):
    get_gardener(gid)
    rows = [b for b in store.shed_bookings.values() if b["gardener_id"] == gid]
    return paginate(rows, store.ser_shed_booking)


# ===========================================================================
# Application
# ===========================================================================
@app.route("/applications", methods=["POST"])
@require("Gardener")
def create_application():
    data = body()
    gardener_id = req_str(data, "gardener_id")
    own_or_403(gardener_id)
    garden_id = req_str(data, "garden_id")
    gardener = get_gardener(gardener_id)
    get_garden(garden_id)
    requested_size = req_enum(data, "requested_size", store.SIZES)
    # duplicate live application on the same shelf
    for a in store.applications.values():
        if (
            a["gardener_id"] == gardener_id
            and a["garden_id"] == garden_id
            and a["requested_size"] == requested_size
            and a["status"] in ("WAITLISTED", "OFFERED")
        ):
            raise ApiError("ERR_DUPLICATE_APPLICATION", 409, "Duplicate live application")
    ts = now()
    obj = {
        "id": new_id(),
        "gardener_id": gardener_id,
        "garden_id": garden_id,
        "requested_size": requested_size,
        "status": "WAITLISTED",
        "priority_score_at_submission": store.priority_score(gardener),
        "offered_plot_id": None,
        "offer_expires_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.applications[obj["id"]] = obj
    return ok(store.ser_application(obj), 201)


@app.route("/applications/<aid>", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def read_application(aid):
    return ok(store.ser_application(get_application(aid)), 200)


@app.route("/applications", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def list_applications():
    rows = list(store.applications.values())
    gardener_id = request.args.get("gardener_id")
    garden_id = request.args.get("garden_id")
    status = request.args.get("status")
    requested_size = request.args.get("requested_size")
    if gardener_id:
        rows = [a for a in rows if a["gardener_id"] == gardener_id]
    if garden_id:
        rows = [a for a in rows if a["garden_id"] == garden_id]
    if status:
        rows = [a for a in rows if a["status"] == status]
    if requested_size:
        rows = [a for a in rows if a["requested_size"] == requested_size]
    return paginate(rows, store.ser_application)


@app.route("/applications/<aid>/accept", methods=["POST"])
@require("Gardener")
def accept_application(aid):
    application = get_application(aid)
    own_or_403(application["gardener_id"])
    if application["status"] != "OFFERED":
        raise ApiError("ERR_OFFER_NOT_PENDING", 409, "Application is not in OFFERED state")
    plot = store.plots.get(application["offered_plot_id"])
    if plot is None or plot["status"] != "RESERVED":
        raise ApiError("ERR_OFFER_NOT_PENDING", 409, "Offer is no longer pending")
    if application["requested_size"] != plot["size"]:
        raise ApiError("ERR_SIZE_MISMATCH", 409, "Requested size does not match plot size")
    if application["offer_expires_at"] is not None and now() > application["offer_expires_at"]:
        raise ApiError("ERR_OFFER_EXPIRED", 409, "Offer has expired")
    gardener = store.gardeners[application["gardener_id"]]
    garden = store.gardens[plot["garden_id"]]
    application["status"] = "ACCEPTED"
    touch(application)
    assignment = _create_assignment(plot, gardener, garden, application_id=application["id"])
    plot["status"] = "ASSIGNED"
    plot["current_assignment_id"] = assignment["id"]
    touch(plot)
    return ok(store.ser_assignment(assignment), 201)


@app.route("/applications/<aid>/decline", methods=["POST"])
@require("Gardener")
def decline_application(aid):
    application = get_application(aid)
    own_or_403(application["gardener_id"])
    if application["status"] != "OFFERED":
        raise ApiError("ERR_OFFER_NOT_PENDING", 409, "Application is not in OFFERED state")
    plot = store.plots.get(application["offered_plot_id"])
    application["status"] = "DECLINED"
    application["offered_plot_id"] = None
    application["offer_expires_at"] = None
    touch(application)
    if plot is not None and plot["status"] == "RESERVED":
        plot["status"] = "AVAILABLE"
        touch(plot)
    return ok(store.ser_application(application), 200)


# ===========================================================================
# Assignment
# ===========================================================================
@app.route("/assignments/<aid>", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def read_assignment(aid):
    return ok(store.ser_assignment(get_assignment(aid)), 200)


@app.route("/assignments", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def list_assignments():
    rows = list(store.assignments.values())
    for field in (
        "plot_id",
        "gardener_id",
        "garden_id",
        "application_id",
        "renewed_from_assignment_id",
        "occupancy_status",
        "fee_status",
    ):
        val = request.args.get(field)
        if val:
            rows = [a for a in rows if a[field] == val]
    return paginate(rows, store.ser_assignment)


def _has_blocking_compliance(assignment_id):
    for c in store.compliance_cases.values():
        if c["assignment_id"] == assignment_id and c["status"] in ("OPEN", "WARNED", "ESCALATED"):
            return True
    return False


@app.route("/assignments/<aid>/request-renewal", methods=["POST"])
@require("Gardener")
def request_renewal(aid):
    assignment = get_assignment(aid)
    own_or_403(assignment["gardener_id"])
    if assignment["occupancy_status"] != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE", 409, "Assignment is not ACTIVE")
    if _has_blocking_compliance(aid):
        raise ApiError("ERR_RENEWAL_BLOCKED_BY_COMPLIANCE", 409, "Open compliance case blocks renewal")
    gardener = store.gardeners[assignment["gardener_id"]]
    if gardener["balance_owed_cents"] != 0:
        raise ApiError("ERR_OUTSTANDING_BALANCE", 402, "Outstanding balance blocks renewal")
    assignment["occupancy_status"] = "RENEWAL_PENDING"
    touch(assignment)
    return ok(store.ser_assignment(assignment), 200)


@app.route("/assignments/<aid>/confirm-renewal", methods=["POST"])
@require("GardenManager")
def confirm_renewal(aid):
    assignment = get_assignment(aid)
    if assignment["occupancy_status"] != "RENEWAL_PENDING":
        raise ApiError("ERR_RENEWAL_NOT_PENDING", 409, "Assignment is not RENEWAL_PENDING")
    if _has_blocking_compliance(aid):
        raise ApiError("ERR_RENEWAL_BLOCKED_BY_COMPLIANCE", 409, "Open compliance case blocks renewal")
    gardener = store.gardeners[assignment["gardener_id"]]
    if gardener["balance_owed_cents"] != 0:
        raise ApiError("ERR_OUTSTANDING_BALANCE", 402, "Outstanding balance blocks renewal")
    assignment["occupancy_status"] = "RENEWED"
    touch(assignment)
    plot = store.plots[assignment["plot_id"]]
    garden = store.gardens[assignment["garden_id"]]
    new_assignment = _create_assignment(
        plot, gardener, garden, application_id=None, renewed_from=assignment["id"]
    )
    plot["current_assignment_id"] = new_assignment["id"]
    gardener["tenure_seasons"] += 1
    touch(gardener)
    return ok(store.ser_assignment(new_assignment), 201)


def _close_assignment(assignment, terminal_status):
    """Shared settle/forfeit fee reconciliation and plot release."""
    assignment["final_fee_cents"] = store.final_fee_cents(assignment)
    assignment["occupancy_status"] = terminal_status
    if assignment["fee_status"] == "UNPAID":
        gardener = store.gardeners[assignment["gardener_id"]]
        gardener["balance_owed_cents"] += (
            assignment["final_fee_cents"] - assignment["provisional_fee_cents"]
        )
        touch(gardener)
    touch(assignment)
    plot = store.plots.get(assignment["plot_id"])
    if plot is not None and plot["current_assignment_id"] == assignment["id"]:
        plot["status"] = "AVAILABLE"
        plot["current_assignment_id"] = None
        touch(plot)
    return plot


@app.route("/assignments/<aid>/settle", methods=["POST"])
@require("GardenManager")
def settle_assignment(aid):
    assignment = get_assignment(aid)
    if assignment["occupancy_status"] not in ("ACTIVE", "RENEWAL_PENDING"):
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE", 409, "Assignment is not active")
    _close_assignment(assignment, "ENDED")
    return ok(store.ser_assignment(assignment), 200)


@app.route("/assignments/<aid>/forfeit", methods=["POST"])
@require("GardenManager")
def forfeit_assignment(aid):
    assignment = get_assignment(aid)
    if assignment["occupancy_status"] not in ("ACTIVE", "RENEWAL_PENDING"):
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE", 409, "Assignment is not active")
    plot = _close_assignment(assignment, "FORFEITED")
    # conditional auto-offer to the top waitlisted applicant
    if plot is not None and plot["status"] == "AVAILABLE":
        candidate = _select_top_candidate(plot)
        if candidate is not None:
            _make_offer(plot, candidate)
    return ok(store.ser_assignment(assignment), 200)


def _owed_fee(assignment):
    if assignment["final_fee_cents"] is not None:
        return assignment["final_fee_cents"]
    return assignment["provisional_fee_cents"]


@app.route("/assignments/<aid>/pay", methods=["POST"])
@require("Treasurer")
def pay_assignment(aid):
    assignment = get_assignment(aid)
    data = body()
    if "amount_cents" not in data or data.get("amount_cents") is None:
        verr("amount_cents is required")
    amount = req_int(data, "amount_cents")
    if assignment["fee_status"] != "UNPAID":
        raise ApiError("ERR_FEE_NOT_PAYABLE", 409, "Fee is not payable")
    if amount != _owed_fee(assignment):
        raise ApiError("ERR_AMOUNT_MISMATCH", 422, "Amount does not match owed fee")
    assignment["fee_status"] = "PAID"
    assignment["_paid_amount_cents"] = amount
    touch(assignment)
    gardener = store.gardeners[assignment["gardener_id"]]
    gardener["balance_owed_cents"] -= amount
    touch(gardener)
    return ok(store.ser_assignment(assignment), 200)


@app.route("/assignments/<aid>/waive-fee", methods=["POST"])
@require("Treasurer")
def waive_fee(aid):
    assignment = get_assignment(aid)
    if assignment["fee_status"] != "UNPAID":
        raise ApiError("ERR_FEE_NOT_PAYABLE", 409, "Fee is not payable")
    outstanding = _owed_fee(assignment)
    assignment["fee_status"] = "WAIVED"
    touch(assignment)
    gardener = store.gardeners[assignment["gardener_id"]]
    gardener["balance_owed_cents"] -= outstanding
    touch(gardener)
    return ok(store.ser_assignment(assignment), 200)


@app.route("/assignments/<aid>/refund", methods=["POST"])
@require("Treasurer")
def refund_fee(aid):
    assignment = get_assignment(aid)
    data = body()
    if "amount_cents" not in data or data.get("amount_cents") is None:
        verr("amount_cents is required")
    amount = req_int(data, "amount_cents")
    if assignment["fee_status"] != "PAID":
        raise ApiError("ERR_FEE_NOT_REFUNDABLE", 409, "Fee is not refundable")
    if amount != assignment["_paid_amount_cents"]:
        raise ApiError("ERR_AMOUNT_MISMATCH", 422, "Amount does not match amount paid")
    assignment["fee_status"] = "REFUNDED"
    touch(assignment)
    gardener = store.gardeners[assignment["gardener_id"]]
    gardener["balance_owed_cents"] += amount
    touch(gardener)
    return ok(store.ser_assignment(assignment), 200)


def _forfeit_and_reoffer(assignment):
    plot = _close_assignment(assignment, "FORFEITED")
    if plot is not None and plot["status"] == "AVAILABLE":
        candidate = _select_top_candidate(plot)
        if candidate is not None:
            _make_offer(plot, candidate)


# ===========================================================================
# WorkLog
# ===========================================================================
@app.route("/work-logs", methods=["POST"])
@require("Gardener")
def create_work_log():
    data = body()
    assignment_id = req_str(data, "assignment_id")
    assignment = get_assignment(assignment_id)
    own_or_403(assignment["gardener_id"])
    hours = data.get("hours")
    if not _is_num(hours):
        verr("hours must be a number")
    if hours <= 0:
        verr("hours must be > 0")
    logged_on = req_dt(data, "logged_on")
    note = data.get("note")
    if note is not None and not isinstance(note, str):
        verr("note must be a string")
    ts = now()
    obj = {
        "id": new_id(),
        "assignment_id": assignment_id,
        "hours": hours,
        "logged_on": logged_on,
        "note": note,
        "created_at": ts,
    }
    store.work_logs[obj["id"]] = obj
    assignment["logged_work_hours"] += hours
    touch(assignment)
    return ok(store.ser_work_log(obj), 201)


@app.route("/assignments/<aid>/work-logs", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def list_work_logs(aid):
    get_assignment(aid)
    rows = [w for w in store.work_logs.values() if w["assignment_id"] == aid]
    return paginate(rows, store.ser_work_log)


# ===========================================================================
# WaterReading
# ===========================================================================
@app.route("/water-readings", methods=["POST"])
@require("Gardener")
def create_water_reading():
    data = body()
    assignment_id = req_str(data, "assignment_id")
    assignment = get_assignment(assignment_id)
    own_or_403(assignment["gardener_id"])
    period_index = data.get("period_index")
    if not _is_int(period_index):
        verr("period_index must be an integer")
    if period_index < 1 or period_index > store.SEASON_PERIODS:
        verr("period_index out of range")
    gallons_used = data.get("gallons_used")
    if not _is_num(gallons_used):
        verr("gallons_used must be a number")
    if gallons_used < 0:
        verr("gallons_used must be >= 0")
    recorded_on = req_dt(data, "recorded_on")
    for r in store.water_readings.values():
        if r["assignment_id"] == assignment_id and r["period_index"] == period_index:
            verr("Duplicate water reading for assignment/period")
    ts = now()
    obj = {
        "id": new_id(),
        "assignment_id": assignment_id,
        "period_index": period_index,
        "gallons_used": gallons_used,
        "recorded_on": recorded_on,
        "created_at": ts,
    }
    store.water_readings[obj["id"]] = obj
    return ok(store.ser_water_reading(obj), 201)


@app.route("/assignments/<aid>/water-readings", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def list_water_readings(aid):
    get_assignment(aid)
    rows = [r for r in store.water_readings.values() if r["assignment_id"] == aid]
    return paginate(rows, store.ser_water_reading)


# ===========================================================================
# ComplianceCase
# ===========================================================================
@app.route("/compliance-cases", methods=["POST"])
@require("GardenManager")
def create_compliance_case():
    data = body()
    assignment_id = req_str(data, "assignment_id")
    assignment = get_assignment(assignment_id)
    violation_type = req_enum(
        data, "violation_type", {"NEGLECT", "RULE_BREACH", "UNPAID_FEE", "WATER_ABUSE"}
    )
    ts = now()
    obj = {
        "id": new_id(),
        "assignment_id": assignment_id,
        "gardener_id": assignment["gardener_id"],
        "violation_type": violation_type,
        "status": "OPEN",
        "cure_deadline": None,
        "opened_on": ts,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.compliance_cases[obj["id"]] = obj
    gardener = store.gardeners[assignment["gardener_id"]]
    gardener["strike_count"] += 1
    gardener["standing"] = store.standing_for(gardener["strike_count"])
    touch(gardener)
    return ok(store.ser_compliance_case(obj), 201)


@app.route("/compliance-cases/<cid>", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def read_compliance_case(cid):
    return ok(store.ser_compliance_case(get_compliance_case(cid)), 200)


@app.route("/compliance-cases", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def list_compliance_cases():
    rows = list(store.compliance_cases.values())
    for field in ("assignment_id", "gardener_id", "status"):
        val = request.args.get(field)
        if val:
            rows = [c for c in rows if c[field] == val]
    return paginate(rows, store.ser_compliance_case)


@app.route("/compliance-cases/<cid>/warn", methods=["POST"])
@require("GardenManager")
def warn_compliance_case(cid):
    case = get_compliance_case(cid)
    if case["status"] != "OPEN":
        raise ApiError("ERR_COMPLIANCE_NOT_OPEN", 409, "Compliance case is not OPEN")
    case["status"] = "WARNED"
    case["cure_deadline"] = now() + _timedelta_days(store.CURE_GRACE_DAYS)
    touch(case)
    return ok(store.ser_compliance_case(case), 200)


@app.route("/compliance-cases/<cid>/resolve", methods=["POST"])
@require("GardenManager")
def resolve_compliance_case(cid):
    case = get_compliance_case(cid)
    if case["status"] != "WARNED":
        raise ApiError("ERR_COMPLIANCE_NOT_WARNED", 409, "Compliance case is not WARNED")
    if now() > case["cure_deadline"]:
        raise ApiError("ERR_CURE_PERIOD_EXPIRED", 409, "Cure period has expired")
    case["status"] = "CURED"
    touch(case)
    return ok(store.ser_compliance_case(case), 200)


@app.route("/compliance-cases/<cid>/escalate", methods=["POST"])
@require("GardenManager")
def escalate_compliance_case(cid):
    case = get_compliance_case(cid)
    if case["status"] != "WARNED":
        raise ApiError("ERR_COMPLIANCE_NOT_WARNED", 409, "Compliance case is not WARNED")
    if now() <= case["cure_deadline"]:
        raise ApiError("ERR_CURE_PERIOD_ACTIVE", 409, "Cure period still active")
    case["status"] = "ESCALATED"
    touch(case)
    assignment = store.assignments.get(case["assignment_id"])
    if assignment is not None and assignment["occupancy_status"] in ("ACTIVE", "RENEWAL_PENDING"):
        _forfeit_and_reoffer(assignment)
    return ok(store.ser_compliance_case(case), 200)


# ===========================================================================
# Tool
# ===========================================================================
@app.route("/tools", methods=["POST"])
@require("GardenManager")
def create_tool():
    data = body()
    garden_id = req_str(data, "garden_id")
    get_garden(garden_id)
    name = req_str(data, "name")
    category = req_enum(data, "category", {"HAND", "POWER", "CART"})
    cleaning_buffer_hours = 4
    if "cleaning_buffer_hours" in data and data.get("cleaning_buffer_hours") is not None:
        cleaning_buffer_hours = req_int(data, "cleaning_buffer_hours")
        if cleaning_buffer_hours < 0:
            verr("cleaning_buffer_hours must be >= 0")
    ts = now()
    obj = {
        "id": new_id(),
        "garden_id": garden_id,
        "name": name,
        "category": category,
        "cleaning_buffer_hours": cleaning_buffer_hours,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.tools[obj["id"]] = obj
    return ok(store.ser_tool(obj), 201)


# ===========================================================================
# ToolLoan
# ===========================================================================
def _gardener_has_active_assignment(gardener_id, garden_id):
    for a in store.assignments.values():
        if (
            a["gardener_id"] == gardener_id
            and a["garden_id"] == garden_id
            and a["occupancy_status"] == "ACTIVE"
        ):
            return True
    return False


@app.route("/tool-loans", methods=["POST"])
@require("Gardener")
def create_tool_loan():
    data = body()
    tool_id = req_str(data, "tool_id")
    gardener_id = req_str(data, "gardener_id")
    own_or_403(gardener_id)
    tool = get_tool(tool_id)
    get_gardener(gardener_id)
    checked_out_at = req_dt(data, "checked_out_at")
    due_at = req_dt(data, "due_at")
    if not (due_at > checked_out_at):
        verr("due_at must be after checked_out_at")
    if not _gardener_has_active_assignment(gardener_id, tool["garden_id"]):
        raise ApiError("ERR_NOT_ACTIVE_GARDENER", 403, "Gardener has no active assignment in garden")
    # buffer-guarded overlap against non-returned loans of the same tool
    from datetime import timedelta

    for existing in store.tool_loans.values():
        if existing["tool_id"] != tool_id:
            continue
        if existing["status"] != "CHECKED_OUT":
            continue
        eff_end = existing["returned_at"] if existing["returned_at"] else existing["due_at"]
        occ_end = eff_end + timedelta(hours=tool["cleaning_buffer_hours"])
        # intersection of [checked_out_at, due_at] with [existing.checked_out_at, occ_end)
        if checked_out_at < occ_end and existing["checked_out_at"] <= due_at:
            raise ApiError("ERR_TOOL_TIME_CONFLICT", 409, "Tool loan window conflicts")
    ts = now()
    obj = {
        "id": new_id(),
        "tool_id": tool_id,
        "gardener_id": gardener_id,
        "checked_out_at": checked_out_at,
        "due_at": due_at,
        "returned_at": None,
        "status": "CHECKED_OUT",
        "late_fine_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.tool_loans[obj["id"]] = obj
    return ok(store.ser_tool_loan(obj), 201)


@app.route("/tool-loans/<lid>", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def read_tool_loan(lid):
    return ok(store.ser_tool_loan(get_tool_loan(lid)), 200)


@app.route("/tool-loans", methods=["GET"])
@require("GardenManager", "Gardener", "Treasurer")
def list_tool_loans():
    rows = list(store.tool_loans.values())
    for field in ("tool_id", "gardener_id", "status"):
        val = request.args.get(field)
        if val:
            rows = [l for l in rows if l[field] == val]
    return paginate(rows, store.ser_tool_loan)


@app.route("/tool-loans/<lid>/return", methods=["POST"])
@require("Gardener")
def return_tool_loan(lid):
    loan = get_tool_loan(lid)
    own_or_403(loan["gardener_id"])
    data = body()
    returned_at = req_dt(data, "returned_at")
    if loan["status"] != "CHECKED_OUT":
        raise ApiError("ERR_LOAN_NOT_OUTSTANDING", 409, "Loan is not outstanding")
    loan["returned_at"] = returned_at
    if returned_at <= loan["due_at"]:
        loan["status"] = "RETURNED"
        loan["late_fine_cents"] = 0
    else:
        loan["status"] = "RETURNED_LATE"
        loan["late_fine_cents"] = store.tool_late_fine_cents(returned_at, loan["due_at"])
    touch(loan)
    return ok(store.ser_tool_loan(loan), 200)


# ===========================================================================
# ShedBooking
# ===========================================================================
@app.route("/shed-bookings", methods=["POST"])
@require("Gardener")
def create_shed_booking():
    data = body()
    garden_id = req_str(data, "garden_id")
    gardener_id = req_str(data, "gardener_id")
    own_or_403(gardener_id)
    get_garden(garden_id)
    get_gardener(gardener_id)
    starts_at = req_dt(data, "starts_at")
    ends_at = req_dt(data, "ends_at")
    if not (ends_at > starts_at):
        verr("ends_at must be after starts_at")
    purpose = req_enum(data, "purpose", {"STORAGE", "WORKSHOP", "MEETING"})
    if not _gardener_has_active_assignment(gardener_id, garden_id):
        raise ApiError("ERR_NOT_ACTIVE_GARDENER", 403, "Gardener has no active assignment in garden")
    for existing in store.shed_bookings.values():
        if existing["garden_id"] != garden_id:
            continue
        # half-open intersection: starts_at < existing.ends_at and existing.starts_at < ends_at
        if starts_at < existing["ends_at"] and existing["starts_at"] < ends_at:
            raise ApiError("ERR_SHED_TIME_CONFLICT", 409, "Shed booking window conflicts")
    ts = now()
    obj = {
        "id": new_id(),
        "garden_id": garden_id,
        "gardener_id": gardener_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "purpose": purpose,
        "created_at": ts,
    }
    store.shed_bookings[obj["id"]] = obj
    return ok(store.ser_shed_booking(obj), 201)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
