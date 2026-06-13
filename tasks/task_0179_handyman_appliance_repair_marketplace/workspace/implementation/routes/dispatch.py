"""DispatchWindow publish / fetch / list / book (PRD §3.4, §3.5, §2.8).

Booking validation order (PRD §2.9 then §3): existence (404) -> ownership (403)
-> state (409) -> assignability gates (PRO_NOT_CLEARED/LICENSE/SKILL) -> instant?
n/a -> ZIP mismatch -> travel buffer -> customer double-book -> stale version
(OCC). The SCAFFOLD pins ERR_STALE_VERSION at the lowest business priority for
booking; §2.8 frames OCC as the final guard, so we evaluate it last.
"""
import re
from datetime import timedelta

from flask import Blueprint, request, g

from db import store
from errors import ApiError
from middleware import require_role
from models import common, touch, serialize, DISPATCH_WINDOW_FIELDS, JOB_FIELDS
from response import object_response, array_response
from services import vetting
from services.lookup import (
    require_body, require_string, require_int, require_datetime, get_or_404,
    paginate, sorted_by_creation,
)

bp = Blueprint("dispatch", __name__)

_ZIP_RE = re.compile(r"^[0-9]{5}$")
TRAVEL_BUFFER = timedelta(minutes=60)


def _v_create_window(body):
    pro_id = require_string(body, "pro_id")
    window_start = require_datetime(body, "window_start")
    window_end = require_datetime(body, "window_end")
    service_zip = require_string(body, "service_zip_code")
    if not _ZIP_RE.match(service_zip):
        raise ApiError("ERR_INVALID_REQUEST", "service_zip_code must be exactly 5 digits")
    return {"pro_id": pro_id, "window_start": window_start,
            "window_end": window_end, "service_zip": service_zip}


@bp.post("/dispatch-windows")
@require_role({"Pro"}, validate=_v_create_window)
def create_window():
    pro_id = g.validated["pro_id"]
    window_start = g.validated["window_start"]
    window_end = g.validated["window_end"]
    service_zip = g.validated["service_zip"]

    get_or_404(store.pros, pro_id)

    # ownership: a Pro publishes windows only for themselves.
    if g.user_id != pro_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Pro may only publish their own windows")

    # ERR_VALIDATION (422): window_end strictly after window_start.
    if not (window_end > window_start):
        raise ApiError("ERR_VALIDATION", "window_end must be after window_start")

    # overlap with own non-RELEASED windows (half-open intervals; touching ok).
    for w in store.dispatch_windows.values():
        if w["pro_id"] != pro_id or w["hold_state"] == "RELEASED":
            continue
        if window_start < w["window_end"] and w["window_start"] < window_end:
            raise ApiError("ERR_WINDOW_OVERLAP",
                           "New window overlaps an existing non-RELEASED window")

    window = {
        "pro_id": pro_id,
        "window_start": window_start,
        "window_end": window_end,
        "service_zip_code": service_zip,
        "booked_job_id": None,
        "hold_state": "FREE",
    }
    common(window)
    store.dispatch_windows[window["id"]] = window
    return object_response(serialize(window, DISPATCH_WINDOW_FIELDS), status=201)


@bp.get("/dispatch-windows/<wid>")
@require_role({"PlatformAdmin", "Customer", "Pro", "Dispatcher"})
def get_window(wid):
    window = get_or_404(store.dispatch_windows, wid)
    return object_response(serialize(window, DISPATCH_WINDOW_FIELDS))


@bp.get("/dispatch-windows")
@require_role({"PlatformAdmin", "Customer", "Pro", "Dispatcher"})
def list_windows():
    items = list(store.dispatch_windows.values())
    pro_id = request.args.get("pro_id")
    service_zip = request.args.get("service_zip_code")
    booked = request.args.get("booked_job_id")
    if pro_id is not None:
        items = [w for w in items if w["pro_id"] == pro_id]
    if service_zip is not None:
        items = [w for w in items if w["service_zip_code"] == service_zip]
    if booked is not None:
        items = [w for w in items if w.get("booked_job_id") == booked]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(w, DISPATCH_WINDOW_FIELDS) for w in page],
                          limit, offset, total)


def _v_book_window(body):
    job_id = require_string(body, "job_id")
    # expected_dispatchwindow_version is mandatory on this request (PRD §2.8).
    if "expected_dispatchwindow_version" not in body or body["expected_dispatchwindow_version"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: expected_dispatchwindow_version")
    expected_version = body["expected_dispatchwindow_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ApiError("ERR_INVALID_REQUEST", "expected_dispatchwindow_version must be an integer")
    return {"job_id": job_id, "expected_version": expected_version}


@bp.post("/dispatch-windows/<wid>/book")
@require_role({"Customer"}, validate=_v_book_window)
def book_window(wid):
    job_id = g.validated["job_id"]
    expected_version = g.validated["expected_version"]

    # existence: path window, then body FK job (left-to-right, path before body).
    window = get_or_404(store.dispatch_windows, wid)
    job = get_or_404(store.jobs, job_id)

    # ownership: the booking Customer must own the job.
    _own_job = job["customer_id"]
    if g.user_id != _own_job:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Customer does not own this job")

    # state: job must be INSTANT_QUOTED or ESTIMATED, window must be FREE.
    if job["status"] not in ("INSTANT_QUOTED", "ESTIMATED"):
        raise ApiError("ERR_INVALID_STATE", "Job is not in a bookable state")
    if window["hold_state"] != "FREE":
        raise ApiError("ERR_INVALID_STATE", "Window is not FREE")

    # accepted quote must exist and not be superseded.
    accepted = [q for q in store.quotes.values()
                if q["job_id"] == job_id and q["accepted"]]
    if not accepted:
        raise ApiError("ERR_INVALID_STATE", "Job has no accepted quote")
    if all(q["superseded"] for q in accepted):
        raise ApiError("ERR_INVALID_STATE", "Accepted quote has been superseded")
    active_quote = next(q for q in accepted if not q["superseded"])

    # assignability gates: background -> license -> skill (PRD §3.5).
    pro = store.pros[window["pro_id"]]
    category = store.service_categories[job["category_id"]]
    vetting.assert_assignable(pro, category)

    # ZIP mismatch.
    if window["service_zip_code"] != job["address_zip_code"]:
        raise ApiError("ERR_ZIP_MISMATCH", "Window ZIP does not match job ZIP")

    # travel buffer: >= 60 min gap before/after any other BOOKED window of the
    # same Pro when the two serve DIFFERENT ZIPs; same-ZIP back-to-back is fine.
    for w in store.dispatch_windows.values():
        if w["id"] == wid or w["pro_id"] != window["pro_id"]:
            continue
        if w["hold_state"] != "BOOKED":
            continue
        if w["service_zip_code"] == window["service_zip_code"]:
            continue
        # different ZIP: require a 60-minute buffer between the intervals.
        if (window["window_start"] < w["window_end"] + TRAVEL_BUFFER
                and w["window_start"] < window["window_end"] + TRAVEL_BUFFER):
            raise ApiError("ERR_TRAVEL_BUFFER_CONFLICT",
                           "Booking violates the travel buffer")

    # customer double-booking: closed intervals — adjacent/touching is rejected.
    for other in store.jobs.values():
        if other["id"] == job_id or other["customer_id"] != job["customer_id"]:
            continue
        if other["status"] != "SCHEDULED":
            continue
        ow = _booked_window_for_job(other["id"])
        if ow is None:
            continue
        if (window["window_start"] <= ow["window_end"]
                and ow["window_start"] <= window["window_end"]):
            raise ApiError("ERR_CUSTOMER_DOUBLE_BOOKED",
                           "Customer already has an overlapping scheduled job")

    # OCC: expected version must equal the live window version (final guard).
    if expected_version != window["version"]:
        raise ApiError("ERR_STALE_VERSION", "DispatchWindow version is stale")

    # success cascade.
    active_quote["accepted"] = True
    touch(active_quote)
    job["agreed_price_cents"] = active_quote["priced_amount_cents"]
    job["pro_id"] = window["pro_id"]
    job["status"] = "SCHEDULED"
    touch(job)

    window["hold_state"] = "BOOKED"
    window["booked_job_id"] = job_id
    touch(window)  # increments version by 1

    return object_response(serialize(window, DISPATCH_WINDOW_FIELDS))


def _booked_window_for_job(jid):
    for w in store.dispatch_windows.values():
        if w.get("booked_job_id") == jid and w["hold_state"] == "BOOKED":
            return w
    return None
