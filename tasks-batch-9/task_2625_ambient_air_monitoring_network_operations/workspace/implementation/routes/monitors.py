"""Instrument lifecycle and immutable quality-control activity."""
from flask import Blueprint

import clock
import constants as C
import response
import validate as V
from auth import ALL_ROLES, actor, require
from db import new_record, sorted_by_created, store, touch
from errors import ApiError
from routes.common import (ensure_from_state, ensure_not_terminal, get_method,
                           get_monitor, get_site, network_of,
                           require_method_designated)
from services import compute as K
from services import serialize as S

bp = Blueprint("monitors", __name__)

MONITOR_TERMINAL = ("DECOMMISSIONED",)
APPROVAL_SITE_STATUSES = ("SITING_APPROVED", "OPERATING")


@bp.post("/monitors")
@require("NetworkAdmin")
def install_monitor():
    data = V.body()
    site_id = V.req_id(data, "site_id")
    reference_method_id = V.req_id(data, "reference_method_id")
    poc = V.req_int(data, "poc", lo=1, hi=9)
    is_primary = V.opt_bool(data, "is_primary_for_design_value", default=False)
    installed_at = V.req_datetime(data, "installed_at")
    site = get_site(site_id)
    method = get_method(reference_method_id)
    # (site, the method's pollutant, poc) is unique among live instruments
    for existing in store.monitors.values():
        if existing["monitor_status"] == "DECOMMISSIONED":
            continue
        if existing["site_id"] != site_id or existing["poc"] != poc:
            continue
        other_method = store.reference_methods.get(existing["reference_method_id"])
        if other_method is not None and other_method["pollutant_id"] == method["pollutant_id"]:
            raise ApiError("ERR_DUPLICATE_MONITOR_POC",
                           "POC %d is already in use at this site for this pollutant." % poc)
    rec = new_record()
    rec.update({
        "site_id": site_id,
        "reference_method_id": reference_method_id,
        "poc": poc,
        "is_primary_for_design_value": bool(is_primary),
        "installed_at": installed_at,
        "monitor_status": "PENDING_APPROVAL",
        "last_calibration_at": None,
        "last_span_check_at": None,
        "last_zero_check_at": None,
        "last_maintenance_at": None,
        "consecutive_qc_failure_count": 0,
        "out_of_service_since": None,
        "out_of_service_day_count": 0,
        "qc_posture": "QC_DUE",
        "qc_posture_in_service": "QC_DUE",
    })
    store.monitors[rec["id"]] = rec
    # Both postures are computed immediately from installed_at.
    K.refresh_qc_posture(rec)
    _ = site
    return response.object_response(S.monitor(rec), 201)


@bp.post("/monitors/<monitor_id>/approve")
@require("EpaRegionalReviewer")
def approve_monitor(monitor_id):
    data = V.body()
    V.opt_string(data, "approval_note")
    monitor = get_monitor(monitor_id)
    ensure_not_terminal(monitor["monitor_status"], MONITOR_TERMINAL, "monitor")
    ensure_from_state(monitor["monitor_status"], ("PENDING_APPROVAL",), "monitor")
    site = store.sites.get(monitor["site_id"])
    if site is None or site["status"] not in APPROVAL_SITE_STATUSES:
        raise ApiError("ERR_INVALID_STATE",
                       "The instrument's site must be SITING_APPROVED or OPERATING.")
    require_method_designated(K.method_of_monitor(monitor))
    monitor["monitor_status"] = "APPROVED"
    K.refresh_qc_posture(monitor)
    touch(monitor)
    network = network_of(site)
    if network is not None:
        network.update(K.network_census(network["id"]))
    return response.object_response(S.monitor(monitor))


@bp.post("/monitors/<monitor_id>/commission")
@require("FieldTechnician")
def commission_monitor(monitor_id):
    data = V.body()
    V.opt_string(data, "commission_note")
    monitor = get_monitor(monitor_id)
    ensure_not_terminal(monitor["monitor_status"], MONITOR_TERMINAL, "monitor")
    ensure_from_state(monitor["monitor_status"], ("APPROVED",), "monitor")
    site = store.sites.get(monitor["site_id"])
    if site is None or site["status"] != "OPERATING":
        raise ApiError("ERR_INVALID_STATE", "The instrument's site must be OPERATING.")
    require_method_designated(K.method_of_monitor(monitor))
    monitor["monitor_status"] = "OPERATING"
    K.refresh_qc_posture(monitor)
    touch(monitor)
    site["operating_monitor_count"] = K.operating_monitor_count(site["id"])
    touch(site)
    network = network_of(site)
    if network is not None:
        network.update(K.network_census(network["id"]))
    return response.object_response(S.monitor(monitor))


@bp.post("/monitors/<monitor_id>/service-status")
@require("FieldTechnician")
def change_service_status(monitor_id):
    data = V.body()
    new_status = V.req_enum(data, "new_status", C.SERVICE_STATUS_TARGETS)
    V.opt_string(data, "reason")
    monitor = get_monitor(monitor_id)
    ensure_not_terminal(monitor["monitor_status"], MONITOR_TERMINAL, "monitor")
    site = store.sites.get(monitor["site_id"])
    if new_status == "OUT_OF_SERVICE":
        ensure_from_state(monitor["monitor_status"], ("OPERATING",), "monitor")
        monitor["monitor_status"] = "OUT_OF_SERVICE"
        monitor["out_of_service_since"] = clock.now()
        K.refresh_qc_posture(monitor)
        touch(monitor)
        if site is not None:
            site["operating_monitor_count"] = K.operating_monitor_count(site["id"])
    else:
        ensure_from_state(monitor["monitor_status"], ("OUT_OF_SERVICE",), "monitor")
        if monitor["consecutive_qc_failure_count"] != 0:
            raise ApiError("ERR_INVALID_STATE",
                           "The instrument still carries consecutive quality-control failures.")
        if site is None or site["status"] != "OPERATING":
            raise ApiError("ERR_INVALID_STATE", "The instrument's site must be OPERATING.")
        if monitor["out_of_service_since"] is not None:
            monitor["out_of_service_day_count"] += K.whole_days_between(
                monitor["out_of_service_since"], clock.now())
        monitor["out_of_service_since"] = None
        monitor["monitor_status"] = "OPERATING"
        K.refresh_qc_posture(monitor)
        touch(monitor)
        site["operating_monitor_count"] = K.operating_monitor_count(site["id"])
        touch(site)
    network = network_of(site) if site is not None else None
    if network is not None:
        network.update(K.network_census(network["id"]))
    return response.object_response(S.monitor(monitor))


@bp.post("/monitors/<monitor_id>/qc-events")
@require("FieldTechnician")
def log_qc_event(monitor_id):
    data = V.body()
    event_type = V.req_enum(data, "event_type", C.QC_EVENT_TYPES)
    performed_at = V.req_datetime(data, "performed_at")
    span_drift_pct = V.opt_number(data, "span_drift_pct")
    zero_drift_value = V.opt_number(data, "zero_drift_value")
    declared_failure = V.opt_bool(data, "declared_failure", default=False)
    if event_type == "SPAN_CHECK" and span_drift_pct is None:
        V.bad("Field 'span_drift_pct' is required for a SPAN_CHECK.")
    if event_type == "ZERO_CHECK" and zero_drift_value is None:
        V.bad("Field 'zero_drift_value' is required for a ZERO_CHECK.")
    if performed_at > clock.now():
        V.bad("Field 'performed_at' may not be later than the logical clock.")
    monitor = get_monitor(monitor_id)
    method = K.method_of_monitor(monitor)
    outcome = K.qc_event_outcome_evaluation(
        event_type, method, span_drift_pct, zero_drift_value, declared_failure)
    rec = new_record(common_fields=False)
    rec.update({
        "monitor_id": monitor_id,
        "event_type": event_type,
        "performed_at": performed_at,
        "span_drift_pct": span_drift_pct if event_type == "SPAN_CHECK" else None,
        "zero_drift_value": zero_drift_value if event_type == "ZERO_CHECK" else None,
        "declared_failure": bool(declared_failure),
        "outcome": outcome,
        "performed_by_user_id": actor(),
    })
    store.qc_events[rec["id"]] = rec
    # 1. a PASS or WARN advances the timestamp matching the activity type
    field = C.QC_TIMESTAMP_FIELD[event_type]
    if outcome in ("PASS", "WARN") and field is not None:
        monitor[field] = performed_at
    # 2. the consecutive-failure run
    if outcome == "FAIL":
        monitor["consecutive_qc_failure_count"] += 1
    else:
        monitor["consecutive_qc_failure_count"] = 0
    site = store.sites.get(monitor["site_id"])
    # 3. an OPERATING instrument recording a FAIL is pulled from service
    if outcome == "FAIL" and monitor["monitor_status"] == "OPERATING":
        monitor["monitor_status"] = "OUT_OF_SERVICE"
        monitor["out_of_service_since"] = clock.now()
        if site is not None:
            site["operating_monitor_count"] = K.operating_monitor_count(site["id"])
    # 4. both postures and the network's delinquency counter are recomputed
    K.refresh_qc_posture(monitor)
    touch(monitor)
    network = network_of(site) if site is not None else None
    if network is not None:
        network.update(K.network_census(network["id"]))
    return response.object_response(S.qc_event(rec), 201)


@bp.get("/monitors/<monitor_id>")
@require(*ALL_ROLES)
def read_monitor(monitor_id):
    return response.object_response(S.monitor(get_monitor(monitor_id)))


@bp.get("/monitors")
@require(*ALL_ROLES)
def list_monitors():
    limit, offset = V.pagination()
    site_id = V.q_string("site_id")
    reference_method_id = V.q_string("reference_method_id")
    monitor_status = V.q_enum("monitor_status", C.MONITOR_STATUSES)
    qc_posture = V.q_enum("qc_posture", C.QC_POSTURES)
    is_primary = V.q_bool("is_primary_for_design_value")
    rows = list(store.monitors.values())
    for row in rows:
        K.refresh_qc_posture(row)
    if site_id is not None:
        rows = [m for m in rows if m["site_id"] == site_id]
    if reference_method_id is not None:
        rows = [m for m in rows if m["reference_method_id"] == reference_method_id]
    if monitor_status is not None:
        rows = [m for m in rows if m["monitor_status"] == monitor_status]
    if qc_posture is not None:
        rows = [m for m in rows if m["qc_posture"] == qc_posture]
    if is_primary is not None:
        rows = [m for m in rows if m["is_primary_for_design_value"] == is_primary]
    rows = sorted_by_created(rows)
    page, meta = response.paginate(rows, limit, offset)
    return response.array_response([S.monitor(m) for m in page], pagination=meta)


@bp.get("/monitors/<monitor_id>/qc-events")
@require(*ALL_ROLES)
def list_qc_events(monitor_id):
    limit, offset = V.pagination()
    event_type = V.q_enum("event_type", C.QC_EVENT_TYPES)
    outcome = V.q_enum("outcome", C.QC_OUTCOMES)
    get_monitor(monitor_id)
    rows = [e for e in store.qc_events.values() if e["monitor_id"] == monitor_id]
    if event_type is not None:
        rows = [e for e in rows if e["event_type"] == event_type]
    if outcome is not None:
        rows = [e for e in rows if e["outcome"] == outcome]
    # most recent performed_at first
    rows.sort(key=lambda e: (e["performed_at"], e["_seq"]), reverse=True)
    page, meta = response.paginate(rows, limit, offset)
    return response.array_response([S.qc_event(e) for e in page], pagination=meta)
