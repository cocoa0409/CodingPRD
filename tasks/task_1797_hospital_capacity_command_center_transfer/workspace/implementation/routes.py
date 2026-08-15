"""All API endpoints. Validation order per PRD 2.8:
auth -> body well-formedness -> existence (left to right) -> state -> OCC ->
domain safety (iso, acuity, service) -> segregation of duties -> temporal ->
window conflicts -> quota/uniqueness.
"""

from datetime import timedelta

from flask import Blueprint, request, g

import errors
from auth import require_roles
from envelope import success
from store import db, now, set_clock, new_entity, touch
from domain_time import fmt, parse_dt
import domain as D

bp = Blueprint("cc", __name__, url_prefix="/cc")


# ---------------------------------------------------------------------------
# Body / query helpers
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True, force=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")


def require_string(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v:
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, f"Field '{field}' must be a non-empty string")
    return v


def opt_string(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, f"Field '{field}' must be a string")
    return v


def require_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        raise errors.err(
            errors.ERR_INVALID_REQUEST,
            400,
            f"Field '{field}' must be one of {allowed}",
        )
    return v


def require_int(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, f"Field '{field}' must be an integer")
    if minimum is not None and v < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, f"Field '{field}' must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, f"Field '{field}' must be <= {maximum}")
    return v


def opt_bool(data, field, default):
    v = data.get(field, default)
    if not isinstance(v, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, f"Field '{field}' must be a boolean")
    return v


def pagination_params():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, "offset must be an integer")
    limit = min(100, max(1, limit))
    offset = max(0, offset)
    return limit, offset


def paginated_list(items, serializer):
    """Sort by created_at ascending, apply limit/offset, emit envelope."""
    limit, offset = pagination_params()
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return success([serializer(e) for e in page], 200, pagination)


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------

def get_facility(fid):
    f = db.facilities.get(fid)
    if f is None:
        raise errors.err(errors.ERR_FACILITY_NOT_FOUND, 404, "Facility not found")
    return f


def get_bed(bid):
    b = db.beds.get(bid)
    if b is None:
        raise errors.err(errors.ERR_BED_NOT_FOUND, 404, "Bed not found")
    return b


def get_physician(pid):
    p = db.physicians.get(pid)
    if p is None:
        raise errors.err(errors.ERR_PHYSICIAN_NOT_FOUND, 404, "Physician not found")
    return p


def get_admission(aid):
    a = db.admissions.get(aid)
    if a is None:
        raise errors.err(errors.ERR_ADMISSION_NOT_FOUND, 404, "Admission not found")
    return a


def get_transfer(tid):
    t = db.transfers.get(tid)
    if t is None:
        raise errors.err(errors.ERR_TRANSFER_REQUEST_NOT_FOUND, 404, "Transfer request not found")
    return t


def get_hold(hid):
    h = db.holds.get(hid)
    if h is None:
        raise errors.err(errors.ERR_HOLD_NOT_FOUND, 404, "Bed hold not found")
    return h


def get_assignment(aid):
    a = db.assignments.get(aid)
    if a is None:
        raise errors.err(errors.ERR_ASSIGNMENT_NOT_FOUND, 404, "Bed assignment not found")
    return a


def get_diversion(did):
    d = db.diversions.get(did)
    if d is None:
        raise errors.err(errors.ERR_DIVERSION_NOT_FOUND, 404, "Diversion event not found")
    return d


def get_boarding(bid):
    r = db.boarding.get(bid)
    if r is None:
        raise errors.err(errors.ERR_BOARDING_RECORD_NOT_FOUND, 404, "Boarding record not found")
    return r


def get_huddle(hid):
    h = db.huddles.get(hid)
    if h is None:
        raise errors.err(errors.ERR_HUDDLE_NOT_FOUND, 404, "Escalation huddle not found")
    return h


def get_forecast(fid):
    f = db.forecasts.get(fid)
    if f is None:
        raise errors.err(errors.ERR_FORECAST_NOT_FOUND, 404, "Capacity forecast not found")
    return f


# ===========================================================================
# Facility
# ===========================================================================

@bp.route("/facilities", methods=["POST"])
@require_roles("SystemAdministrator")
def create_facility():
    data = body()
    require_fields(data, ["name", "region"])
    name = require_string(data, "name")
    region = require_string(data, "region")
    f = new_entity()
    f.update({"name": name, "region": region})
    db.facilities[f["id"]] = f
    return success(D.facility_json(f), 201)


@bp.route("/facilities/<fid>", methods=["GET"])
@require_roles("Any")
def get_facility_endpoint(fid):
    return success(D.facility_json(get_facility(fid)), 200)


@bp.route("/facilities/<fid>/load-score", methods=["GET"])
@require_roles("Any")
def facility_load_score(fid):
    get_facility(fid)
    scores = D.load_scores(fid)
    return success(
        {
            "raw_occupancy_pct": scores["raw"],
            "pressure_weighted_pct": scores["weighted"],
            "service_weighted_occupancy_pct": D.service_weighted_occupancy(fid),
            "diversion_recommended": scores["diversion_recommended"],
            "staffed_beds": scores["staffed_beds"],
            "occupied_beds": scores["occupied_beds"],
            "held_beds": scores["held_beds"],
            "boarding_waiters": scores["boarding_waiters"],
            "active_inbound_transfers": scores["active_inbound_transfers"],
        },
        200,
    )


@bp.route("/facilities/<fid>/bed-candidates", methods=["GET"])
@require_roles("Any")
def facility_bed_candidates(fid):
    get_facility(fid)
    tid = request.args.get("transfer_request_id")
    if not tid:
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, "transfer_request_id is required")
    req = db.transfers.get(tid)
    if req is None or req["facility_id"] != fid:
        raise errors.err(errors.ERR_TRANSFER_REQUEST_NOT_FOUND, 404, "Transfer request not found")
    candidates = D.bed_candidates(fid, req)
    out = []
    for b in candidates:
        j = D.bed_json(b)
        j["score"] = D.bed_score(b, req)
        out.append(j)
    return success({"candidates": out}, 200)


# ===========================================================================
# DiversionEvent
# ===========================================================================

@bp.route("/facilities/<fid>/diversions", methods=["POST"])
@require_roles("HouseSupervisor")
def create_diversion(fid):
    data = body()
    require_fields(data, ["level", "starts_at", "ends_at"])
    level = require_enum(data, "level", ["FULL", "SERVICE"])
    if level == "SERVICE":
        service = require_enum(data, "service", D.SERVICES)
    else:
        if data.get("service") is not None:
            raise errors.err(
                errors.ERR_INVALID_REQUEST, 400, "service is forbidden when level is FULL"
            )
        service = None
    starts_at = parse_dt(data.get("starts_at"), "starts_at")
    ends_at = parse_dt(data.get("ends_at"), "ends_at")
    if not ends_at > starts_at:
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, "ends_at must be after starts_at")
    facility = get_facility(fid)
    # Overlap check against other ACTIVE diversions: half-open windows.
    for d in D.facility_diversions(fid):
        if d["status"] != "ACTIVE":
            continue
        if starts_at < d["ends_at"] and d["starts_at"] < ends_at:
            raise errors.err(
                errors.ERR_DIVERSION_WINDOW_OVERLAP,
                409,
                "Diversion window overlaps an active diversion",
            )
    prev_status = D.diversion_status_of(fid)
    ev = new_entity()
    ev.update(
        {
            "facility_id": facility["id"],
            "level": level,
            "service": service,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "declared_by_user_id": g.user_id,
            "status": "ACTIVE",
            "lifted_at": None,
            "lifted_by_user_id": None,
        }
    )
    db.diversions[ev["id"]] = ev
    # Cascade: on entering DIVERT_FULL, decline INTAKE / CONSULT_PENDING requests.
    new_status = D.diversion_status_of(fid)
    if new_status == "DIVERT_FULL" and prev_status != "DIVERT_FULL":
        for t in D.facility_transfers(fid):
            if t["status"] in ("INTAKE", "CONSULT_PENDING"):
                t["status"] = "DECLINED"
                t["decline_reason"] = "DIVERSION"
                t["accepting_physician_id"] = None
                t["consult_deadline"] = None
                touch(t)
    return success(D.diversion_json(ev), 201)


@bp.route("/facilities/<fid>/diversions", methods=["GET"])
@require_roles("Any")
def list_diversions(fid):
    get_facility(fid)
    items = D.facility_diversions(fid)
    status = request.args.get("status")
    if status:
        items = [d for d in items if d["status"] == status]
    return paginated_list(items, D.diversion_json)


@bp.route("/diversions/<did>/lift", methods=["POST"])
@require_roles("HouseSupervisor")
def lift_diversion(did):
    body()  # tolerate empty/absent body
    d = get_diversion(did)
    if d["status"] != "ACTIVE":
        raise errors.err(errors.ERR_DIVERSION_INVALID_STATE, 409, "Diversion is not ACTIVE")
    if g.user_id == d["declared_by_user_id"]:
        raise errors.err(
            errors.ERR_SOD_DIVERSION_DECLARE_LIFT_SAME_ACTOR,
            403,
            "Diversion must be lifted by a different operator than its declarer",
        )
    if now() < d["created_at"] + timedelta(minutes=D.MIN_DIVERSION_MINUTES):
        raise errors.err(
            errors.ERR_DIVERSION_LIFT_TOO_SOON,
            409,
            "Diversion may not be lifted within 30 minutes of declaration",
        )
    d["status"] = "LIFTED"
    d["lifted_at"] = now()
    d["lifted_by_user_id"] = g.user_id
    touch(d)
    return success(D.diversion_json(d), 200)


# ===========================================================================
# Bed
# ===========================================================================

@bp.route("/facilities/<fid>/beds", methods=["POST"])
@require_roles("SystemAdministrator")
def create_bed(fid):
    data = body()
    require_fields(data, ["unit", "label", "service", "max_acuity", "isolation_capability"])
    unit = require_string(data, "unit")
    label = require_string(data, "label")
    service = require_enum(data, "service", D.SERVICES)
    max_acuity = require_enum(data, "max_acuity", D.ACUITY_LEVELS)
    iso = require_enum(data, "isolation_capability", D.ISO_LEVELS)
    staffed = opt_bool(data, "staffed", True)
    turnover = data.get("turnover_minutes", 45)
    if isinstance(turnover, bool) or not isinstance(turnover, int) or turnover < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, "turnover_minutes must be a non-negative integer")
    facility = get_facility(fid)
    b = new_entity()
    b.update(
        {
            "facility_id": facility["id"],
            "unit": unit,
            "label": label,
            "service": service,
            "max_acuity": max_acuity,
            "isolation_capability": iso,
            "staffed": staffed,
            "turnover_minutes": turnover,
            "status": "AVAILABLE",
            "projected_free_at": None,
            "cooling_until": None,
        }
    )
    db.beds[b["id"]] = b
    return success(D.bed_json(b), 201)


@bp.route("/facilities/<fid>/beds", methods=["GET"])
@require_roles("Any")
def list_beds(fid):
    get_facility(fid)
    items = D.facility_beds(fid)
    status = request.args.get("status")
    service = request.args.get("service")
    if status:
        items = [b for b in items if b["status"] == status]
    if service:
        items = [b for b in items if b["service"] == service]
    return paginated_list(items, D.bed_json)


@bp.route("/beds/<bid>", methods=["GET"])
@require_roles("Any")
def get_bed_endpoint(bid):
    return success(D.bed_json(get_bed(bid)), 200)


@bp.route("/beds/<bid>/status", methods=["POST"])
@require_roles("BedManager")
def set_bed_status(bid):
    data = body()
    require_fields(data, ["to_status"])
    to_status = data.get("to_status")
    if to_status not in ("AVAILABLE", "OUT_OF_SERVICE"):
        raise errors.err(
            errors.ERR_INVALID_REQUEST,
            400,
            "to_status must be AVAILABLE or OUT_OF_SERVICE",
        )
    b = get_bed(bid)
    reachable = (b["status"], to_status) in (
        ("AVAILABLE", "OUT_OF_SERVICE"),
        ("OUT_OF_SERVICE", "AVAILABLE"),
    )
    if not reachable:
        raise errors.err(
            errors.ERR_BED_NOT_AVAILABLE,
            409,
            f"Cannot move bed from {b['status']} to {to_status}",
        )
    b["status"] = to_status
    touch(b)
    return success(D.bed_json(b), 200)


@bp.route("/beds/<bid>/admissions", methods=["GET"])
@require_roles("Any")
def list_bed_admissions(bid):
    get_bed(bid)
    items = [a for a in db.admissions.values() if a["bed_id"] == bid]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    return paginated_list(items, D.admission_json)


@bp.route("/beds/<bid>/bed-holds", methods=["GET"])
@require_roles("Any")
def list_bed_holds(bid):
    get_bed(bid)
    items = [h for h in db.holds.values() if h["bed_id"] == bid]
    status = request.args.get("status")
    if status:
        items = [h for h in items if h["status"] == status]
    return paginated_list(items, D.hold_json)


@bp.route("/beds/<bid>/transfer-requests", methods=["GET"])
@require_roles("Any")
def list_bed_transfers(bid):
    get_bed(bid)
    items = [t for t in db.transfers.values() if t["assigned_bed_id"] == bid]
    status = request.args.get("status")
    if status:
        items = [t for t in items if t["status"] == status]
    return paginated_list(items, D.transfer_json)


# ===========================================================================
# Physician
# ===========================================================================

@bp.route("/facilities/<fid>/physicians", methods=["POST"])
@require_roles("SystemAdministrator")
def create_physician(fid):
    data = body()
    require_fields(data, ["full_name", "services"])
    full_name = require_string(data, "full_name")
    services = data.get("services")
    if not isinstance(services, list) or any(s not in D.SERVICES for s in services):
        raise errors.err(
            errors.ERR_INVALID_REQUEST, 400, "services must be an array of valid service enums"
        )
    status = data.get("status", "ON_CALL")
    if status not in ("ON_CALL", "OFF_CALL"):
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, "status must be ON_CALL or OFF_CALL")
    facility = get_facility(fid)
    p = new_entity()
    p.update(
        {
            "facility_id": facility["id"],
            "full_name": full_name,
            "services": list(services),
            "status": status,
        }
    )
    db.physicians[p["id"]] = p
    return success(D.physician_json(p), 201)


@bp.route("/facilities/<fid>/physicians", methods=["GET"])
@require_roles("Any")
def list_physicians(fid):
    get_facility(fid)
    items = [p for p in db.physicians.values() if p["facility_id"] == fid]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    return paginated_list(items, D.physician_json)


@bp.route("/physicians/<pid>", methods=["GET"])
@require_roles("Any")
def get_physician_endpoint(pid):
    return success(D.physician_json(get_physician(pid)), 200)


@bp.route("/physicians/<pid>/status", methods=["POST"])
@require_roles("HouseSupervisor")
def set_physician_status(pid):
    data = body()
    require_fields(data, ["to_status"])
    to_status = data.get("to_status")
    if to_status not in ("ON_CALL", "OFF_CALL"):
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, "to_status must be ON_CALL or OFF_CALL")
    p = get_physician(pid)
    p["status"] = to_status
    touch(p)
    return success(D.physician_json(p), 200)


@bp.route("/physicians/<pid>/transfer-requests", methods=["GET"])
@require_roles("Any")
def list_physician_transfers(pid):
    get_physician(pid)
    items = [t for t in db.transfers.values() if t["accepting_physician_id"] == pid]
    status = request.args.get("status")
    if status:
        items = [t for t in items if t["status"] == status]
    return paginated_list(items, D.transfer_json)


# ===========================================================================
# Admission
# ===========================================================================

@bp.route("/facilities/<fid>/admissions", methods=["POST"])
@require_roles("BedManager")
def create_admission(fid):
    data = body()
    require_fields(data, ["bed_id", "patient_ref", "acuity", "isolation_need", "service"])
    bed_id = data.get("bed_id")
    if not isinstance(bed_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, "bed_id must be a string")
    patient_ref = require_string(data, "patient_ref")
    acuity = require_enum(data, "acuity", D.ACUITY_LEVELS)
    iso = require_enum(data, "isolation_need", D.ISO_LEVELS)
    service = require_enum(data, "service", D.SERVICES)
    facility = get_facility(fid)
    bed = db.beds.get(bed_id)
    if bed is None or bed["facility_id"] != facility["id"]:
        raise errors.err(errors.ERR_BED_NOT_FOUND, 404, "Bed not found")
    if bed["status"] != "AVAILABLE" or not bed["staffed"]:
        raise errors.err(errors.ERR_BED_NOT_AVAILABLE, 409, "Bed is not available for admission")
    a = new_entity()
    a.update(
        {
            "facility_id": facility["id"],
            "bed_id": bed["id"],
            "patient_ref": patient_ref,
            "acuity": acuity,
            "isolation_need": iso,
            "service": service,
            "status": "ADMITTED",
            "expected_discharge_at": None,
            "discharge_order_signed": False,
            "pending_discharge_at": None,
            "confirmed_discharge_at": None,
        }
    )
    db.admissions[a["id"]] = a
    bed["status"] = "OCCUPIED"
    bed["cooling_until"] = None
    touch(bed)
    return success(D.admission_json(a), 201)


@bp.route("/facilities/<fid>/admissions", methods=["GET"])
@require_roles("Any")
def list_admissions(fid):
    get_facility(fid)
    items = D.facility_admissions(fid)
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    return paginated_list(items, D.admission_json)


@bp.route("/admissions/<aid>", methods=["GET"])
@require_roles("Any")
def get_admission_endpoint(aid):
    return success(D.admission_json(get_admission(aid)), 200)


@bp.route("/admissions/<aid>/pending-discharge", methods=["POST"])
@require_roles("BedManager")
def mark_pending_discharge(aid):
    data = body()
    require_fields(data, ["expected_discharge_at"])
    expected = parse_dt(data.get("expected_discharge_at"), "expected_discharge_at")
    signed = opt_bool(data, "discharge_order_signed", False)
    a = get_admission(aid)
    if a["status"] != "ADMITTED":
        raise errors.err(
            errors.ERR_ADMISSION_INVALID_STATE, 409, "Admission must be ADMITTED"
        )
    a["status"] = "PENDING_DISCHARGE"
    a["pending_discharge_at"] = now()
    a["expected_discharge_at"] = expected
    a["discharge_order_signed"] = signed
    touch(a)
    bed = db.beds.get(a["bed_id"])
    if bed is not None:
        bed["projected_free_at"] = expected + timedelta(minutes=bed["turnover_minutes"])
        touch(bed)
    D.mark_latest_published_forecast_stale(a["facility_id"])
    return success(D.admission_json(a), 200)


@bp.route("/admissions/<aid>/confirm-discharge", methods=["POST"])
@require_roles("BedManager")
def confirm_discharge(aid):
    body()
    a = get_admission(aid)
    if a["status"] != "PENDING_DISCHARGE":
        raise errors.err(
            errors.ERR_ADMISSION_INVALID_STATE, 409, "Admission must be PENDING_DISCHARGE"
        )
    a["status"] = "DISCHARGED"
    a["confirmed_discharge_at"] = now()
    touch(a)
    bed = db.beds.get(a["bed_id"])
    if bed is not None and bed["status"] == "OCCUPIED":
        bed["status"] = "AVAILABLE"
        bed["projected_free_at"] = None
        bed["cooling_until"] = now() + timedelta(minutes=bed["turnover_minutes"])
        touch(bed)
    D.mark_latest_published_forecast_stale(a["facility_id"])
    return success(D.admission_json(a), 200)


@bp.route("/admissions/<aid>/rescind-pending-discharge", methods=["POST"])
@require_roles("BedManager")
def rescind_pending_discharge(aid):
    body()
    a = get_admission(aid)
    if a["status"] != "PENDING_DISCHARGE":
        raise errors.err(
            errors.ERR_ADMISSION_INVALID_STATE, 409, "Admission must be PENDING_DISCHARGE"
        )
    a["status"] = "ADMITTED"
    a["pending_discharge_at"] = None
    a["expected_discharge_at"] = None
    a["discharge_order_signed"] = False
    touch(a)
    bed = db.beds.get(a["bed_id"])
    if bed is not None:
        bed["projected_free_at"] = None
        touch(bed)
    D.mark_latest_published_forecast_stale(a["facility_id"])
    return success(D.admission_json(a), 200)


@bp.route("/admissions/<aid>/boarding-records", methods=["GET"])
@require_roles("Any")
def list_admission_boarding(aid):
    get_admission(aid)
    items = [r for r in db.boarding.values() if r["admission_id"] == aid]
    return paginated_list(items, D.boarding_json)


# ===========================================================================
# TransferRequest
# ===========================================================================

@bp.route("/facilities/<fid>/transfer-requests", methods=["POST"])
@require_roles("TransferCenterCoordinator")
def create_transfer(fid):
    data = body()
    require_fields(
        data,
        ["source_facility_name", "patient_ref", "acuity", "isolation_need", "service", "priority"],
    )
    source_name = require_string(data, "source_facility_name")
    patient_ref = require_string(data, "patient_ref")
    acuity = require_enum(data, "acuity", D.ACUITY_LEVELS)
    iso = require_enum(data, "isolation_need", D.ISO_LEVELS)
    service = require_enum(data, "service", D.SERVICES)
    priority = require_enum(data, "priority", D.PRIORITIES)
    preferred_unit = opt_string(data, "preferred_unit")
    facility = get_facility(fid)
    # Diversion gate on intake.
    posture = D.diversion_status_of(fid)
    if posture == "DIVERT_FULL":
        raise errors.err(errors.ERR_FACILITY_ON_DIVERSION, 409, "Facility is on full diversion")
    if posture == "DIVERT_SERVICE":
        ts = now()
        for d in D.facility_diversions(fid):
            if (
                d["status"] == "ACTIVE"
                and d["level"] == "SERVICE"
                and d["service"] == service
                and d["starts_at"] <= ts < d["ends_at"]
            ):
                raise errors.err(
                    errors.ERR_FACILITY_ON_DIVERSION,
                    409,
                    "Facility is on diversion for this service",
                )
    t = new_entity()
    t.update(
        {
            "facility_id": facility["id"],
            "source_facility_name": source_name,
            "patient_ref": patient_ref,
            "acuity": acuity,
            "isolation_need": iso,
            "service": service,
            "priority": priority,
            "preferred_unit": preferred_unit,
            "status": "INTAKE",
            "accepting_physician_id": None,
            "consult_deadline": None,
            "consult_count": 0,
            "decline_reason": None,
            "intake_coordinator_id": g.user_id,
            "assigned_bed_id": None,
        }
    )
    db.transfers[t["id"]] = t
    return success(D.transfer_json(t), 201)


@bp.route("/facilities/<fid>/transfer-requests", methods=["GET"])
@require_roles("Any")
def list_transfers(fid):
    get_facility(fid)
    items = D.facility_transfers(fid)
    status = request.args.get("status")
    if status:
        items = [t for t in items if t["status"] == status]
    return paginated_list(items, D.transfer_json)


@bp.route("/transfer-requests/<tid>", methods=["GET"])
@require_roles("Any")
def get_transfer_endpoint(tid):
    return success(D.transfer_json(get_transfer(tid)), 200)


@bp.route("/transfer-requests/<tid>/consult", methods=["POST"])
@require_roles("TransferCenterCoordinator")
def dispatch_consult(tid):
    data = body()
    require_fields(data, ["physician_id"])
    physician_id = data.get("physician_id")
    if not isinstance(physician_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, "physician_id must be a string")
    t = get_transfer(tid)
    p = db.physicians.get(physician_id)
    if p is None or p["facility_id"] != t["facility_id"]:
        raise errors.err(errors.ERR_PHYSICIAN_NOT_FOUND, 404, "Physician not found")
    if t["status"] not in ("INTAKE", "DECLINED", "EXPIRED"):
        raise errors.err(
            errors.ERR_TRANSFER_INVALID_STATE,
            409,
            "Consult dispatch requires INTAKE, DECLINED, or EXPIRED",
        )
    if t["service"] not in p["services"]:
        raise errors.err(
            errors.ERR_PHYSICIAN_NOT_CREDENTIALED_FOR_SERVICE,
            422,
            "Physician is not credentialed for the request's service",
        )
    if p["status"] != "ON_CALL":
        raise errors.err(errors.ERR_PHYSICIAN_NOT_ON_CALL, 409, "Physician is not ON_CALL")
    t["status"] = "CONSULT_PENDING"
    t["accepting_physician_id"] = p["id"]
    t["consult_deadline"] = now() + timedelta(minutes=D.CONSULT_TTL_MINUTES)
    t["consult_count"] += 1
    t["decline_reason"] = None
    touch(t)
    return success(D.transfer_json(t), 200)


@bp.route("/transfer-requests/<tid>/consult-response", methods=["POST"])
@require_roles("AcceptingPhysician")
def consult_response(tid):
    data = body()
    require_fields(data, ["decision"])
    decision = require_enum(data, "decision", ["ACCEPT", "DECLINE"])
    decline_reason = data.get("decline_reason")
    if decision == "DECLINE":
        if decline_reason not in D.MANUAL_DECLINE_REASONS:
            raise errors.err(
                errors.ERR_INVALID_REQUEST,
                400,
                "decline_reason must be one of PHYSICIAN_DECLINED, NO_CAPACITY, CLINICAL",
            )
    t = get_transfer(tid)
    # Entity-backed ownership: only the consulted physician may respond.
    if g.user_id != t["accepting_physician_id"]:
        raise errors.err(
            errors.ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "Only the accepting physician may respond to this consult",
        )
    if t["status"] != "CONSULT_PENDING":
        raise errors.err(
            errors.ERR_TRANSFER_INVALID_STATE, 409, "Request is not CONSULT_PENDING"
        )
    if now() >= t["consult_deadline"]:
        raise errors.err(errors.ERR_CONSULT_WINDOW_EXPIRED, 409, "Consult window has expired")
    if decision == "ACCEPT":
        t["status"] = "ACCEPTED"
        t["consult_deadline"] = None
    else:
        t["status"] = "DECLINED"
        t["decline_reason"] = decline_reason
        t["accepting_physician_id"] = None
        t["consult_deadline"] = None
    touch(t)
    return success(D.transfer_json(t), 200)


@bp.route("/transfer-requests/<tid>/cancel", methods=["POST"])
@require_roles("TransferCenterCoordinator")
def cancel_transfer(tid):
    body()
    t = get_transfer(tid)
    if t["status"] not in D.NON_TERMINAL_TRANSFER_STATUSES:
        raise errors.err(
            errors.ERR_TRANSFER_INVALID_STATE, 409, "Transfer request is terminal"
        )
    if t["status"] == "HOLD_PLACED":
        for h in db.holds.values():
            if h["transfer_request_id"] == t["id"] and h["status"] == "ACTIVE":
                D.release_hold_effects(h, "RELEASED")
    t["status"] = "CANCELLED"
    t["accepting_physician_id"] = None
    t["consult_deadline"] = None
    touch(t)
    return success(D.transfer_json(t), 200)


@bp.route("/transfer-requests/<tid>/rebalance", methods=["POST"])
@require_roles("TransferCenterCoordinator")
def rebalance_transfer(tid):
    data = body()
    require_fields(data, ["target_facility_id"])
    target_id = data.get("target_facility_id")
    if not isinstance(target_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, "target_facility_id must be a string")
    t = get_transfer(tid)
    target = db.facilities.get(target_id)
    if target is None:
        raise errors.err(errors.ERR_FACILITY_NOT_FOUND, 404, "Target facility not found")
    if t["status"] not in ("INTAKE", "CONSULT_PENDING", "DECLINED", "EXPIRED"):
        raise errors.err(
            errors.ERR_TRANSFER_INVALID_STATE,
            409,
            "Rebalance requires INTAKE, CONSULT_PENDING, DECLINED, or EXPIRED",
        )
    if D.diversion_status_of(target["id"]) != "ACCEPTING":
        raise errors.err(
            errors.ERR_FACILITY_ON_DIVERSION, 409, "Target facility is not ACCEPTING"
        )
    source_score = D.load_scores(t["facility_id"])["weighted"]
    target_score = D.load_scores(target["id"])["weighted"]
    if D.Decimal(str(source_score)) - D.Decimal(str(target_score)) < D.REBALANCE_MARGIN:
        raise errors.err(
            errors.ERR_REBALANCE_MARGIN_NOT_MET,
            409,
            "Weighted load margin below 10.0",
        )
    t["facility_id"] = target["id"]
    t["status"] = "INTAKE"
    t["accepting_physician_id"] = None
    t["consult_deadline"] = None
    t["decline_reason"] = None
    touch(t)
    return success(D.transfer_json(t), 200)


# ===========================================================================
# BedHold
# ===========================================================================

@bp.route("/transfer-requests/<tid>/bed-holds", methods=["POST"])
@require_roles("TransferCenterCoordinator")
def create_hold(tid):
    data = body()
    bed_id = data.get("bed_id")
    if bed_id is not None and not isinstance(bed_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, "bed_id must be a string")
    ttl = data.get("ttl_minutes", D.HOLD_TTL_MINUTES)
    if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, "ttl_minutes must be a positive integer")
    t = get_transfer(tid)
    if t["status"] != "ACCEPTED":
        raise errors.err(
            errors.ERR_TRANSFER_INVALID_STATE, 409, "Hold placement requires ACCEPTED"
        )
    facility_id = t["facility_id"]
    ts = now()
    if bed_id is not None:
        bed = db.beds.get(bed_id)
        if bed is None or bed["facility_id"] != facility_id:
            raise errors.err(errors.ERR_BED_NOT_FOUND, 404, "Bed not found")
        if bed["status"] != "AVAILABLE" or not bed["staffed"] or D.is_ed_unit(bed["unit"]):
            raise errors.err(errors.ERR_BED_NOT_AVAILABLE, 409, "Bed is not available")
        if D.ISO_RANK[bed["isolation_capability"]] < D.ISO_RANK[t["isolation_need"]]:
            raise errors.err(
                errors.ERR_ISOLATION_INCOMPATIBLE, 422, "Isolation capability insufficient"
            )
        if D.ACUITY_RANK[bed["max_acuity"]] < D.ACUITY_RANK[t["acuity"]]:
            raise errors.err(
                errors.ERR_ACUITY_EXCEEDS_BED_CAPABILITY,
                422,
                "Request acuity exceeds bed capability",
            )
        if bed["service"] != t["service"] and bed["service"] != "MEDICAL":
            raise errors.err(errors.ERR_SERVICE_MISMATCH, 422, "Bed service does not match")
        if bed["cooling_until"] is not None and ts < bed["cooling_until"]:
            raise errors.err(
                errors.ERR_BED_HOLD_WINDOW_CONFLICT, 409, "Bed is in its cooling window"
            )
        if D.active_hold_count(facility_id) >= D.HOLD_QUOTA_PER_FACILITY:
            raise errors.err(errors.ERR_HOLD_QUOTA_EXCEEDED, 409, "Facility hold quota reached")
    else:
        if D.active_hold_count(facility_id) >= D.HOLD_QUOTA_PER_FACILITY:
            raise errors.err(errors.ERR_HOLD_QUOTA_EXCEEDED, 409, "Facility hold quota reached")
        candidates = D.bed_candidates(facility_id, t)
        if not candidates:
            raise errors.err(errors.ERR_NO_ELIGIBLE_BED, 409, "No eligible bed")
        bed = candidates[0]
        if bed["cooling_until"] is not None and ts < bed["cooling_until"]:
            raise errors.err(
                errors.ERR_BED_HOLD_WINDOW_CONFLICT, 409, "Bed is in its cooling window"
            )
    h = new_entity()
    h.update(
        {
            "bed_id": bed["id"],
            "transfer_request_id": t["id"],
            "starts_at": ts,
            "ttl_minutes": ttl,
            "expires_at": ts + timedelta(minutes=ttl),
            "status": "ACTIVE",
            "extend_count": 0,
        }
    )
    db.holds[h["id"]] = h
    bed["status"] = "HELD"
    bed["cooling_until"] = None
    touch(bed)
    t["status"] = "HOLD_PLACED"
    touch(t)
    return success(D.hold_json(h), 201)


@bp.route("/transfer-requests/<tid>/bed-holds", methods=["GET"])
@require_roles("Any")
def list_transfer_holds(tid):
    get_transfer(tid)
    items = [h for h in db.holds.values() if h["transfer_request_id"] == tid]
    status = request.args.get("status")
    if status:
        items = [h for h in items if h["status"] == status]
    return paginated_list(items, D.hold_json)


@bp.route("/bed-holds/<hid>", methods=["GET"])
@require_roles("Any")
def get_hold_endpoint(hid):
    return success(D.hold_json(get_hold(hid)), 200)


@bp.route("/bed-holds/<hid>/extend", methods=["POST"])
@require_roles("TransferCenterCoordinator")
def extend_hold(hid):
    data = body()
    require_fields(data, ["expected_bed_hold_version"])
    expected = data.get("expected_bed_hold_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.err(
            errors.ERR_INVALID_REQUEST, 400, "expected_bed_hold_version must be an integer"
        )
    h = get_hold(hid)
    if h["status"] != "ACTIVE":
        raise errors.err(errors.ERR_HOLD_INVALID_STATE, 409, "Hold is not ACTIVE")
    if expected != h["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, 412, "Stale bed hold version")
    if h["extend_count"] >= D.HOLD_EXTEND_MAX:
        raise errors.err(
            errors.ERR_HOLD_EXTEND_LIMIT_EXCEEDED, 409, "Hold extend limit reached"
        )
    h["expires_at"] = h["expires_at"] + timedelta(minutes=D.EXTEND_MINUTES)
    h["extend_count"] += 1
    touch(h)
    return success(D.hold_json(h), 200)


@bp.route("/bed-holds/<hid>/release", methods=["POST"])
@require_roles("TransferCenterCoordinator")
def release_hold(hid):
    body()
    h = get_hold(hid)
    if h["status"] != "ACTIVE":
        raise errors.err(errors.ERR_HOLD_INVALID_STATE, 409, "Hold is not ACTIVE")
    D.release_hold_effects(h, "RELEASED")
    return success(D.hold_json(h), 200)


@bp.route("/bed-holds/<hid>/bed-assignments", methods=["GET"])
@require_roles("Any")
def list_hold_assignments(hid):
    get_hold(hid)
    items = [a for a in db.assignments.values() if a["bed_hold_id"] == hid]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    return paginated_list(items, D.assignment_json)


# ===========================================================================
# BedAssignment
# ===========================================================================

@bp.route("/transfer-requests/<tid>/bed-assignments", methods=["POST"])
@require_roles("TransferCenterCoordinator")
def create_assignment(tid):
    data = body()
    require_fields(data, ["bed_hold_id", "expected_transfer_request_version"])
    hold_id = data.get("bed_hold_id")
    if not isinstance(hold_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, "bed_hold_id must be a string")
    expected = data.get("expected_transfer_request_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.err(
            errors.ERR_INVALID_REQUEST,
            400,
            "expected_transfer_request_version must be an integer",
        )
    t = get_transfer(tid)
    h = db.holds.get(hold_id)
    if h is None:
        raise errors.err(errors.ERR_HOLD_NOT_FOUND, 404, "Bed hold not found")
    if t["status"] != "HOLD_PLACED":
        raise errors.err(
            errors.ERR_TRANSFER_INVALID_STATE, 409, "Request must be HOLD_PLACED"
        )
    if h["status"] != "ACTIVE" or h["transfer_request_id"] != t["id"]:
        raise errors.err(
            errors.ERR_HOLD_INVALID_STATE, 409, "Hold is not ACTIVE for this request"
        )
    if expected != t["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, 412, "Stale transfer request version")
    a = new_entity()
    a.update(
        {
            "transfer_request_id": t["id"],
            "bed_hold_id": h["id"],
            "bed_id": h["bed_id"],
            "created_by_user_id": g.user_id,
            "status": "PLACED",
            "completed_at": None,
        }
    )
    db.assignments[a["id"]] = a
    t["status"] = "ASSIGNED"
    t["assigned_bed_id"] = h["bed_id"]
    touch(t)
    h["status"] = "CONSUMED"
    touch(h)
    return success(D.assignment_json(a), 201)


@bp.route("/transfer-requests/<tid>/bed-assignments", methods=["GET"])
@require_roles("Any")
def list_transfer_assignments(tid):
    get_transfer(tid)
    items = [a for a in db.assignments.values() if a["transfer_request_id"] == tid]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    return paginated_list(items, D.assignment_json)


@bp.route("/beds/<bid>/bed-assignments", methods=["GET"])
@require_roles("Any")
def list_bed_assignments(bid):
    get_bed(bid)
    items = [a for a in db.assignments.values() if a["bed_id"] == bid]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    return paginated_list(items, D.assignment_json)


@bp.route("/bed-assignments/<aid>/complete", methods=["POST"])
@require_roles("BedManager")
def complete_assignment(aid):
    body()
    a = get_assignment(aid)
    if a["status"] != "PLACED":
        raise errors.err(errors.ERR_INVALID_STATE, 409, "Assignment is not PLACED")
    if g.user_id == a["created_by_user_id"]:
        raise errors.err(
            errors.ERR_SOD_ASSIGNMENT_CREATE_COMPLETE_SAME_ACTOR,
            403,
            "Assignment must be completed by a different operator than its creator",
        )
    a["status"] = "COMPLETED"
    a["completed_at"] = now()
    touch(a)
    t = db.transfers.get(a["transfer_request_id"])
    bed = db.beds.get(a["bed_id"])
    if t is not None and t["status"] == "ASSIGNED":
        t["status"] = "COMPLETED"
        touch(t)
    if bed is not None and bed["status"] == "HELD":
        bed["status"] = "OCCUPIED"
        bed["cooling_until"] = None
        touch(bed)
    if t is not None and bed is not None:
        adm = new_entity()
        adm.update(
            {
                "facility_id": bed["facility_id"],
                "bed_id": bed["id"],
                "patient_ref": t["patient_ref"],
                "acuity": t["acuity"],
                "isolation_need": t["isolation_need"],
                "service": t["service"],
                "status": "ADMITTED",
                "expected_discharge_at": None,
                "discharge_order_signed": False,
                "pending_discharge_at": None,
                "confirmed_discharge_at": None,
            }
        )
        db.admissions[adm["id"]] = adm
    return success(D.assignment_json(a), 200)


# ===========================================================================
# BoardingRecord / EscalationHuddle
# ===========================================================================

@bp.route("/facilities/<fid>/boarding-records", methods=["POST"])
@require_roles("TransferCenterCoordinator")
def create_boarding(fid):
    data = body()
    require_fields(data, ["admission_id"])
    admission_id = data.get("admission_id")
    if not isinstance(admission_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, "admission_id must be a string")
    facility = get_facility(fid)
    adm = db.admissions.get(admission_id)
    if adm is None or adm["facility_id"] != facility["id"]:
        raise errors.err(errors.ERR_ADMISSION_NOT_FOUND, 404, "Admission not found")
    bed = db.beds.get(adm["bed_id"])
    if bed is None or not D.is_ed_unit(bed["unit"]):
        raise errors.err(
            errors.ERR_ADMISSION_NOT_ED_BOARDER, 409, "Admission's bed is not in an ED unit"
        )
    for r in db.boarding.values():
        if r["admission_id"] == adm["id"] and r["placement_status"] in ("WAITING", "OFFERED"):
            raise errors.err(
                errors.ERR_BOARDING_RECORD_ALREADY_OPEN,
                409,
                "Admission already has an open boarding record",
            )
    r = new_entity()
    r.update(
        {
            "facility_id": facility["id"],
            "admission_id": adm["id"],
            "started_at": now(),
            "placement_status": "WAITING",
            "escalation_status": "NONE",
            "executive_escalation": False,
            "last_heartbeat_minutes": None,
        }
    )
    db.boarding[r["id"]] = r
    return success(D.boarding_json(r), 201)


@bp.route("/facilities/<fid>/boarding-records", methods=["GET"])
@require_roles("Any")
def list_boarding(fid):
    get_facility(fid)
    items = D.facility_boarding(fid)
    ps = request.args.get("placement_status")
    if ps:
        items = [r for r in items if r["placement_status"] == ps]
    return paginated_list(items, D.boarding_json)


@bp.route("/boarding-records/<bid>", methods=["GET"])
@require_roles("Any")
def get_boarding_endpoint(bid):
    return success(D.boarding_json(get_boarding(bid)), 200)


@bp.route("/boarding-records/<bid>/heartbeat", methods=["POST"])
@require_roles("TransferCenterCoordinator")
def boarding_heartbeat(bid):
    data = body()
    require_fields(data, ["observed_minutes"])
    observed = data.get("observed_minutes")
    if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
        raise errors.err(
            errors.ERR_INVALID_REQUEST, 400, "observed_minutes must be a non-negative integer"
        )
    r = get_boarding(bid)
    if r["last_heartbeat_minutes"] is not None and observed < r["last_heartbeat_minutes"]:
        raise errors.err(
            errors.ERR_INVALID_REQUEST, 400, "observed_minutes may not regress"
        )
    if r["placement_status"] not in ("WAITING", "OFFERED"):
        raise errors.err(
            errors.ERR_BOARDING_INVALID_STATE, 409, "Boarding record placement is closed"
        )
    r["last_heartbeat_minutes"] = observed
    touch(r)
    D.boarding_escalation_check(r)
    return success(D.boarding_json(r), 200)


@bp.route("/boarding-records/<bid>/offer", methods=["POST"])
@require_roles("TransferCenterCoordinator")
def boarding_offer(bid):
    body()
    r = get_boarding(bid)
    if r["placement_status"] != "WAITING":
        raise errors.err(errors.ERR_BOARDING_INVALID_STATE, 409, "Offer requires WAITING")
    r["placement_status"] = "OFFERED"
    touch(r)
    return success(D.boarding_json(r), 200)


@bp.route("/boarding-records/<bid>/place", methods=["POST"])
@require_roles("TransferCenterCoordinator")
def boarding_place(bid):
    body()
    r = get_boarding(bid)
    if r["placement_status"] != "OFFERED":
        raise errors.err(errors.ERR_BOARDING_INVALID_STATE, 409, "Place requires OFFERED")
    r["placement_status"] = "PLACED"
    touch(r)
    return success(D.boarding_json(r), 200)


@bp.route("/boarding-records/<bid>/leave-ama", methods=["POST"])
@require_roles("TransferCenterCoordinator")
def boarding_leave_ama(bid):
    body()
    r = get_boarding(bid)
    if r["placement_status"] not in ("WAITING", "OFFERED"):
        raise errors.err(
            errors.ERR_BOARDING_INVALID_STATE, 409, "Record is not in an open placement"
        )
    r["placement_status"] = "LEFT_AMA"
    touch(r)
    return success(D.boarding_json(r), 200)


@bp.route("/boarding-records/<bid>/huddles", methods=["POST"])
@require_roles("HouseSupervisor")
def create_manual_huddle(bid):
    body()
    r = get_boarding(bid)
    if r["placement_status"] not in ("WAITING", "OFFERED"):
        raise errors.err(
            errors.ERR_BOARDING_INVALID_STATE, 409, "Boarding record placement is closed"
        )
    if r["escalation_status"] == "HUDDLE_CALLED":
        raise errors.err(
            errors.ERR_HUDDLE_INVALID_STATE, 409, "A huddle is already called"
        )
    h = D.create_huddle(r, "MANUAL")
    return success(D.huddle_json(h), 201)


@bp.route("/boarding-records/<bid>/huddles", methods=["GET"])
@require_roles("Any")
def list_huddles(bid):
    get_boarding(bid)
    items = [h for h in db.huddles.values() if h["boarding_record_id"] == bid]
    status = request.args.get("status")
    if status:
        items = [h for h in items if h["status"] == status]
    return paginated_list(items, D.huddle_json)


@bp.route("/huddles/<hid>/resolve", methods=["POST"])
@require_roles("HouseSupervisor")
def resolve_huddle(hid):
    data = body()
    resolution = opt_string(data, "resolution")
    h = get_huddle(hid)
    if h["status"] != "CALLED":
        raise errors.err(errors.ERR_HUDDLE_INVALID_STATE, 409, "Huddle is not CALLED")
    h["status"] = "RESOLVED"
    h["resolved_at"] = now()
    h["resolution"] = resolution
    touch(h)
    r = db.boarding.get(h["boarding_record_id"])
    if r is not None:
        r["escalation_status"] = "HUDDLE_RESOLVED"
        if D.huddle_count_24h_of(r) >= D.HUDDLE_MAX_PER_WINDOW:
            r["executive_escalation"] = True
        touch(r)
    return success(D.huddle_json(h), 200)


# ===========================================================================
# CapacityForecast
# ===========================================================================

@bp.route("/facilities/<fid>/capacity-forecasts", methods=["POST"])
@require_roles("CapacityPlanner")
def create_forecast(fid):
    data = body()
    require_fields(data, ["horizon_hours"])
    horizon = require_int(data, "horizon_hours", minimum=1, maximum=72)
    facility = get_facility(fid)
    # Supersede all prior PROVISIONAL / PUBLISHED forecasts of the facility.
    for f in D.facility_forecasts(fid):
        if f["status"] in ("PROVISIONAL", "PUBLISHED"):
            f["status"] = "SUPERSEDED"
            touch(f)
    generated_at = now()
    snapshots = D.generate_forecast_snapshots(fid, horizon, generated_at)
    fc = new_entity()
    fc.update(
        {
            "facility_id": facility["id"],
            "horizon_hours": horizon,
            "generated_at": generated_at,
            "variant_snapshots": snapshots["variant_snapshots"],
            "occupancy_pct_committed": snapshots["occupancy_pct_committed"],
            "occupancy_pct_provisional": snapshots["occupancy_pct_provisional"],
            "status": "PROVISIONAL",
            "stale": False,
            "published_at": None,
        }
    )
    db.forecasts[fc["id"]] = fc
    return success(D.forecast_json(fc), 201)


@bp.route("/facilities/<fid>/capacity-forecasts", methods=["GET"])
@require_roles("Any")
def list_forecasts(fid):
    get_facility(fid)
    items = D.facility_forecasts(fid)
    status = request.args.get("status")
    if status:
        items = [f for f in items if f["status"] == status]
    return paginated_list(items, D.forecast_json)


@bp.route("/capacity-forecasts/<fid>", methods=["GET"])
@require_roles("Any")
def get_forecast_endpoint(fid):
    return success(D.forecast_json(get_forecast(fid)), 200)


@bp.route("/capacity-forecasts/<fid>/publish", methods=["POST"])
@require_roles("CapacityPlanner")
def publish_forecast(fid):
    body()
    fc = get_forecast(fid)
    if fc["status"] != "PROVISIONAL":
        raise errors.err(
            errors.ERR_FORECAST_INVALID_STATE, 409, "Forecast is not PROVISIONAL"
        )
    fc["status"] = "PUBLISHED"
    fc["published_at"] = now()
    touch(fc)
    return success(D.forecast_json(fc), 200)


# ===========================================================================
# Test-driving endpoints: logical clock and housekeeping sweep
# ===========================================================================

@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("SystemAdministrator")
def set_current_utc():
    data = body()
    require_fields(data, ["to_iso8601"])
    ts = parse_dt(data.get("to_iso8601"), "to_iso8601")
    set_clock(ts)
    return success({"current_utc": fmt(now())}, 200)


@bp.route("/_sweeps/run", methods=["POST"])
@require_roles("SystemAdministrator")
def run_sweep():
    body()
    ts = now()
    expired_hold_ids = []
    expired_consult_ids = []
    expired_diversion_ids = []
    escalated_boarding_ids = []

    # 1. Expire ACTIVE holds whose expires_at has been reached or passed.
    for h in sorted(db.holds.values(), key=lambda e: e["_seq"]):
        if h["status"] == "ACTIVE" and ts >= h["expires_at"]:
            D.release_hold_effects(h, "EXPIRED")
            expired_hold_ids.append(h["id"])

    # 2. Expire CONSULT_PENDING requests whose deadline has been reached or passed.
    for t in sorted(db.transfers.values(), key=lambda e: e["_seq"]):
        if (
            t["status"] == "CONSULT_PENDING"
            and t["consult_deadline"] is not None
            and ts >= t["consult_deadline"]
        ):
            t["status"] = "EXPIRED"
            t["decline_reason"] = "TIMEOUT"
            t["accepting_physician_id"] = None
            t["consult_deadline"] = None
            touch(t)
            expired_consult_ids.append(t["id"])

    # 3. Expire ACTIVE diversions whose window has ended.
    for d in sorted(db.diversions.values(), key=lambda e: e["_seq"]):
        if d["status"] == "ACTIVE" and ts >= d["ends_at"]:
            d["status"] = "EXPIRED"
            touch(d)
            expired_diversion_ids.append(d["id"])

    # 4. Boarding escalation check for every open boarding record.
    for r in sorted(db.boarding.values(), key=lambda e: e["_seq"]):
        if r["placement_status"] in ("WAITING", "OFFERED"):
            if D.boarding_escalation_check(r):
                escalated_boarding_ids.append(r["id"])

    return success(
        {
            "expired_hold_ids": expired_hold_ids,
            "expired_consult_request_ids": expired_consult_ids,
            "expired_diversion_ids": expired_diversion_ids,
            "escalated_boarding_record_ids": escalated_boarding_ids,
        },
        200,
    )
