"""Crews, LaborBookings, OnsitePermits (PRD §3.6)."""
from datetime import timedelta

from flask import Blueprint

from db import STORE, new_id, now_iso, touch
from errors import (ApiError, ERR_JOB_INVALID_STATE, ERR_INVALID_STATE,
                    ERR_CREW_UNQUALIFIED, ERR_CREW_DOUBLE_BOOKED,
                    ERR_PERMIT_WINDOW_CONFLICT, ERR_INVALID_REQUEST,
                    not_found, bad_request)
from middleware import (ALL_OPERATIONAL, require_roles, body, req_str, req_enum,
                        req_dt, req_list, paginate, enum_filter, str_filter)
from response import success
from services import calc
from services.state import get, ser_crew, ser_booking, ser_permit, job_items

bp = Blueprint("labor", __name__)

CAPABILITIES = {"SHOP_BUILD", "ONSITE_PACK", "HAZMAT_CERT"}
BOOKING_STATUSES = {"RESERVED", "CONFIRMED", "COMPLETED", "CANCELLED"}
PERMIT_STATUSES = {"REQUESTED", "CONFIRMED", "CLOSED", "CANCELLED"}
MODES = {"SHOP", "ONSITE"}
MODE_CAPABILITY = {"SHOP": "SHOP_BUILD", "ONSITE": "ONSITE_PACK"}

PERMIT_BUFFER = timedelta(minutes=60)


# ---------------------------------------------------------------------------
# Crews
# ---------------------------------------------------------------------------

@bp.post("/crating/crews")
def create_crew():
    require_roles(["ShopForeman"])
    d = body()
    name = req_str(d, "name")
    caps = req_list(d, "capabilities")
    if not caps or any(not isinstance(c, str) or c not in CAPABILITIES for c in caps):
        raise bad_request("Field 'capabilities' must be a non-empty array drawn from "
                          "SHOP_BUILD|ONSITE_PACK|HAZMAT_CERT")
    rec = {"id": new_id(), "name": name, "capabilities": list(caps), "status": "ACTIVE",
           "created_at": now_iso(), "updated_at": now_iso(), "version": 1}
    STORE["crews"][rec["id"]] = rec
    return success(ser_crew(rec), status=201)


@bp.get("/crating/crews/<cid>")
def get_crew(cid):
    require_roles(ALL_OPERATIONAL)
    c = get("crews", cid)
    if not c:
        raise not_found("Crew not found")
    return success(ser_crew(c))


# ---------------------------------------------------------------------------
# Labor bookings
# ---------------------------------------------------------------------------

@bp.post("/crating/packing-jobs/<jid>/labor-bookings")
def create_booking(jid):
    require_roles(["ShopForeman"])
    d = body()
    crew_id = req_str(d, "crew_id")
    mode = req_enum(d, "mode", MODES)
    start_at = req_dt(d, "start_at")
    end_at = req_dt(d, "end_at")
    if end_at <= start_at:
        raise bad_request("Field 'end_at' must be later than 'start_at'")
    j = get("jobs", jid)
    if not j:
        raise not_found("PackingJob not found")
    crew = get("crews", crew_id)
    if not crew:
        raise not_found("Crew not found")
    if mode != j["mode"]:
        raise ApiError(ERR_INVALID_REQUEST,
                       "Booking mode must equal the job's mode", 400)
    if j["status"] == "QUOTED":
        raise ApiError(ERR_JOB_INVALID_STATE,
                       "Labor may only be booked after quote acceptance", 409)
    # qualification (tier 7)
    needs_hazmat = any(it["hazmat"] or it["battery_in_equipment"] != "NONE"
                       for it in job_items(jid))
    if MODE_CAPABILITY[mode] not in crew["capabilities"] \
            or (needs_hazmat and "HAZMAT_CERT" not in crew["capabilities"]):
        raise ApiError(ERR_CREW_UNQUALIFIED, "Crew lacks required capabilities", 422)
    # half-open [start, end) overlap on the same crew (tier 9); adjacency allowed
    for b in STORE["bookings"].values():
        if b["crew_id"] == crew_id and b["status"] in ("RESERVED", "CONFIRMED"):
            if start_at < b["end_at"] and b["start_at"] < end_at:
                raise ApiError(ERR_CREW_DOUBLE_BOOKED,
                               "Interval overlaps an existing booking on this crew", 409)
    cost = calc.booking_cost(mode, start_at, end_at)
    rec = {"id": new_id(), "packing_job_id": jid, "crew_id": crew_id, "mode": mode,
           "start_at": start_at, "end_at": end_at, "status": "RESERVED",
           "created_at": now_iso(), "updated_at": now_iso(), "version": 1}
    rec.update(cost)
    STORE["bookings"][rec["id"]] = rec
    return success(ser_booking(rec), status=201)


def _get_booking_or_404(bid):
    b = get("bookings", bid)
    if not b:
        raise not_found("LaborBooking not found")
    return b


@bp.get("/crating/labor-bookings/<bid>")
def get_booking(bid):
    require_roles(ALL_OPERATIONAL)
    return success(ser_booking(_get_booking_or_404(bid)))


@bp.get("/crating/labor-bookings")
def list_bookings():
    require_roles(ALL_OPERATIONAL)
    crew_id = str_filter("crew_id")
    job_id = str_filter("packing_job_id")
    status = enum_filter("status", BOOKING_STATUSES)
    recs = [b for b in STORE["bookings"].values()
            if (crew_id is None or b["crew_id"] == crew_id)
            and (job_id is None or b["packing_job_id"] == job_id)
            and (status is None or b["status"] == status)]
    recs.sort(key=lambda b: b["created_at"])
    page, meta = paginate(recs)
    return success([ser_booking(b) for b in page], pagination=meta)


@bp.post("/crating/labor-bookings/<bid>/confirm")
def confirm_booking(bid):
    require_roles(["ShopForeman"])
    b = _get_booking_or_404(bid)
    if b["status"] != "RESERVED":
        raise ApiError(ERR_INVALID_STATE, "confirm requires status RESERVED", 409)
    b["status"] = "CONFIRMED"
    touch(b)
    return success(ser_booking(b))


@bp.post("/crating/labor-bookings/<bid>/complete")
def complete_booking(bid):
    require_roles(["ShopForeman"])
    b = _get_booking_or_404(bid)
    if b["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, "complete requires status CONFIRMED", 409)
    b["status"] = "COMPLETED"
    touch(b)
    return success(ser_booking(b))


@bp.post("/crating/labor-bookings/<bid>/cancel")
def cancel_booking(bid):
    require_roles(["ShopForeman"])
    b = _get_booking_or_404(bid)
    if b["status"] not in ("RESERVED", "CONFIRMED"):
        raise ApiError(ERR_INVALID_STATE,
                       "cancel requires status RESERVED or CONFIRMED", 409)
    b["status"] = "CANCELLED"
    touch(b)
    return success(ser_booking(b))


# ---------------------------------------------------------------------------
# On-site permits
# ---------------------------------------------------------------------------

@bp.post("/crating/packing-jobs/<jid>/onsite-permit")
def create_permit(jid):
    require_roles(["LogisticsCoordinator"])
    d = body()
    window_start = req_dt(d, "window_start")
    window_end = req_dt(d, "window_end")
    if window_end <= window_start:
        raise bad_request("Field 'window_end' must be later than 'window_start'")
    j = get("jobs", jid)
    if not j:
        raise not_found("PackingJob not found")
    cust = get("customers", j["customer_id"])
    site_code = cust["site_code"]
    # closed window +/- 60-minute buffer vs other REQUESTED|CONFIRMED permits
    # on the same site_code; touching within the buffer is a conflict
    ns, ne = window_start - PERMIT_BUFFER, window_end + PERMIT_BUFFER
    for p in STORE["permits"].values():
        if p["site_code"] == site_code and p["status"] in ("REQUESTED", "CONFIRMED"):
            os_, oe = p["window_start"] - PERMIT_BUFFER, p["window_end"] + PERMIT_BUFFER
            if ns <= oe and os_ <= ne:
                raise ApiError(ERR_PERMIT_WINDOW_CONFLICT,
                               "Buffered window conflicts with an existing permit", 409)
    rec = {"id": new_id(), "packing_job_id": jid, "site_code": site_code,
           "window_start": window_start, "window_end": window_end,
           "status": "REQUESTED",
           "created_at": now_iso(), "updated_at": now_iso(), "version": 1}
    STORE["permits"][rec["id"]] = rec
    return success(ser_permit(rec), status=201)


def _get_permit_or_404(pid):
    p = get("permits", pid)
    if not p:
        raise not_found("OnsitePermit not found")
    return p


@bp.get("/crating/onsite-permits/<pid>")
def get_permit(pid):
    require_roles(ALL_OPERATIONAL)
    return success(ser_permit(_get_permit_or_404(pid)))


@bp.get("/crating/onsite-permits")
def list_permits():
    require_roles(ALL_OPERATIONAL)
    job_id = str_filter("packing_job_id")
    site_code = str_filter("site_code")
    status = enum_filter("status", PERMIT_STATUSES)
    recs = [p for p in STORE["permits"].values()
            if (job_id is None or p["packing_job_id"] == job_id)
            and (site_code is None or p["site_code"] == site_code)
            and (status is None or p["status"] == status)]
    recs.sort(key=lambda p: p["created_at"])
    page, meta = paginate(recs)
    return success([ser_permit(p) for p in page], pagination=meta)


@bp.post("/crating/onsite-permits/<pid>/confirm")
def confirm_permit(pid):
    require_roles(["LogisticsCoordinator"])
    p = _get_permit_or_404(pid)
    if p["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE, "confirm requires status REQUESTED", 409)
    p["status"] = "CONFIRMED"
    touch(p)
    return success(ser_permit(p))
