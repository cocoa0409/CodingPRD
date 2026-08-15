"""Voyage lifecycle, ballast water events, determinations, and reports
(PRD 3.2, 3.3, 3.4)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from auth import ALL_ROLES, require_roles
from db import now, store
from errors import (ApiError, ERR_DISCHARGE_WITHOUT_UPTAKE,
                    ERR_DUPLICATE_VOYAGE_NUMBER, ERR_EVENT_OUT_OF_WINDOW,
                    ERR_EXCHANGE_TOO_CLOSE, ERR_INVALID_STATE,
                    ERR_STALE_VERSION, ERR_TANK_BALANCE_NEGATIVE,
                    ERR_VALIDATION, ERR_VESSEL_FROZEN,
                    ERR_VOLUME_EXCEEDS_CAPACITY)
from response import ok, ok_list
from services import (compute_determination, create_noncompliance,
                      determination_json, event_json, get_report, get_vessel,
                      get_voyage, mint, report_json, round3, touch,
                      voyage_json)
from utils import (by_created, get_body, pagination_params, parse_dt,
                   query_bool, query_filter, req_bool, req_enum, req_field,
                   req_int, req_num, req_str)

bp = Blueprint("voyages", __name__)

EVENT_KINDS = ("UPTAKE", "DISCHARGE", "EXCHANGE_START", "EXCHANGE_COMPLETE",
               "TREATMENT_START", "TREATMENT_COMPLETE", "TANK_FLUSH",
               "SEDIMENT_DISPOSAL")
TRIGGER_MANUAL = "MANUAL_RECOMPUTE"


def _check_not_frozen(vessel):
    if vessel["compliance_posture"] == "FROZEN":
        raise ApiError(ERR_VESSEL_FROZEN, 409,
                       "vessel compliance posture is FROZEN; the operation is "
                       "blocked by an enforcement hold")


# ---------------------------------------------------------------------------
# Voyages
# ---------------------------------------------------------------------------

@bp.post("/vessels/<vessel_id>/voyages")
@require_roles("ShoreComplianceOfficer", "VesselMaster")
def create_voyage(vessel_id):
    vessel = get_vessel(vessel_id)
    body = get_body()
    number = req_str(body, "voyage_number")
    departure_port = req_str(body, "departure_port")
    arrival_port = req_str(body, "arrival_port")
    departed_at = parse_dt(req_field(body, "departed_at"), "departed_at")
    arrived_at = None
    if body.get("arrived_at") is not None:
        arrived_at = parse_dt(body["arrived_at"], "arrived_at")
    crosses = req_bool(body, "crosses_captain_of_port_zones")
    eez = req_bool(body, "enters_us_eez")

    with store.lock:
        if any(v for v in store.voyages.values()
               if v["vessel_id"] == vessel["id"] and v["voyage_number"] == number):
            raise ApiError(ERR_DUPLICATE_VOYAGE_NUMBER, 409,
                           "voyage_number is already in use for the vessel")
        voyage = mint({
            "vessel_id": vessel["id"],
            "voyage_number": number,
            "departure_port": departure_port,
            "arrival_port": arrival_port,
            "departed_at": departed_at,
            "arrived_at": arrived_at,
            "crosses_captain_of_port_zones": crosses,
            "enters_us_eez": eez,
            "compliance_status": "PENDING",
            "reporting_status": "NOT_DUE",
            "determination_id": None,
            "bw_record_book_id": None,
        })
        store.voyages[voyage["id"]] = voyage
    return ok(voyage_json(voyage), 201)


@bp.get("/vessels/<vessel_id>/voyages")
@require_roles(*ALL_ROLES)
def list_voyages(vessel_id):
    vessel = get_vessel(vessel_id)
    limit, offset = pagination_params()
    compliance = query_filter("compliance_status")
    reporting = query_filter("reporting_status")
    items = [v for v in store.voyages.values() if v["vessel_id"] == vessel["id"]]
    if compliance is not None:
        items = [v for v in items if v["compliance_status"] == compliance]
    if reporting is not None:
        items = [v for v in items if v["reporting_status"] == reporting]
    items = by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([voyage_json(v) for v in page], total, limit, offset)


@bp.get("/vessels/<vessel_id>/voyages/<voyage_id>")
@require_roles(*ALL_ROLES)
def fetch_voyage(vessel_id, voyage_id):
    vessel = get_vessel(vessel_id)
    return ok(voyage_json(get_voyage(vessel, voyage_id)), 200)


@bp.post("/vessels/<vessel_id>/voyages/<voyage_id>/depart")
@require_roles("VesselMaster")
def depart_voyage(vessel_id, voyage_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    if voyage["compliance_status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a PENDING voyage may depart")
    _check_not_frozen(vessel)
    has_approved_plan = any(
        p for p in store.plans.values()
        if p["vessel_id"] == vessel["id"] and p["status"] == "APPROVED")
    if not has_approved_plan:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "the vessel has no APPROVED ballast water management "
                       "plan")
    with store.lock:
        voyage["compliance_status"] = "IN_PROGRESS"
        compute_determination(vessel, voyage, "VOYAGE_DEPARTURE")
        book = mint({
            "vessel_id": vessel["id"],
            "book_kind": "BALLAST_WATER",
            "voyage_id": voyage["id"],
            "status": "OPEN",
        })
        store.record_books[book["id"]] = book
        voyage["bw_record_book_id"] = book["id"]
        voyage["reporting_status"] = "DUE"
        due_at = (voyage["arrived_at"] - timedelta(hours=24)
                  if voyage["arrived_at"] is not None else None)
        report = mint({
            "voyage_id": voyage["id"],
            "report_type": "PRE_ARRIVAL",
            "due_at": due_at,
            "submitted_at": None,
            "status": "DRAFT",
            "payload_summary": None,
            "rejection_reason": None,
        })
        store.reports[report["id"]] = report
        touch(voyage)
    return ok(voyage_json(voyage), 200)


@bp.post("/vessels/<vessel_id>/voyages/<voyage_id>/arrive")
@require_roles("VesselMaster")
def arrive_voyage(vessel_id, voyage_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    if voyage["compliance_status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an IN_PROGRESS voyage may arrive")
    _check_not_frozen(vessel)
    body = get_body()
    arrived_at = parse_dt(req_field(body, "arrived_at"), "arrived_at")

    with store.lock:
        voyage["arrived_at"] = arrived_at
        det = compute_determination(vessel, voyage, "VOYAGE_ARRIVAL")
        # Fill in the PRE_ARRIVAL deadline once the arrival time is known.
        for report in store.reports.values():
            if (report["voyage_id"] == voyage["id"]
                    and report["report_type"] == "PRE_ARRIVAL"
                    and report["due_at"] is None):
                report["due_at"] = arrived_at - timedelta(hours=24)
                touch(report)

        basis = det["determination_basis"]
        if basis in ("EXCHANGE_COMPLIANT", "TREATMENT_COMPLIANT"):
            voyage["compliance_status"] = "COMPLIANT"
            touch(vessel)
        elif basis in ("NONCOMPLIANT_MIXED", "NONCOMPLIANT_NO_METHOD") or any(
                r for r in store.noncompliance.values()
                if r["voyage_id"] == voyage["id"]
                and r["response_status"] == "OPEN"
                and r["severity"] in ("MAJOR", "CRITICAL")):
            voyage["compliance_status"] = "NONCOMPLIANT"
            already = any(
                r for r in store.noncompliance.values()
                if r["voyage_id"] == voyage["id"]
                and r["source_type"] == "DETERMINATION_NONCOMPLIANT")
            if not already:
                create_noncompliance(vessel, voyage["id"],
                                     "DETERMINATION_NONCOMPLIANT", det["id"])
            touch(vessel)
        elif basis in ("EXEMPT_SAME_COTP", "EXEMPT_NO_US_EEZ"):
            voyage["compliance_status"] = "EXEMPT"
        touch(voyage)
    return ok(voyage_json(voyage), 200)


# ---------------------------------------------------------------------------
# Ballast water events
# ---------------------------------------------------------------------------

@bp.post("/vessels/<vessel_id>/voyages/<voyage_id>/ballast-events")
@require_roles("VesselMaster")
def create_ballast_event(vessel_id, voyage_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    body = get_body()
    expected = req_int(body, "expected_voyage_version")
    if expected != voyage["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_voyage_version does not match the voyage's "
                       "current version")
    _check_not_frozen(vessel)

    kind = req_enum(body, "event_kind", EVENT_KINDS)
    occurred_at = parse_dt(req_field(body, "occurred_at"), "occurred_at")
    tank_id = req_str(body, "tank_id")
    # PRD 2.6: volumes are carried at 3 decimal places, rounded half up, so
    # the persisted event volume is the carried value and every downstream
    # consumer (tank balance, determination sums) sees the carried number.
    volume = round3(req_num(body, "volume_m3", gt=0))

    latitude = longitude = distance = salinity = source_port = None
    if kind in ("EXCHANGE_START", "EXCHANGE_COMPLETE", "DISCHARGE"):
        latitude = req_field(body, "latitude")
        longitude = req_field(body, "longitude")
        if isinstance(latitude, bool) or not isinstance(latitude, (int, float)):
            raise ApiError(ERR_VALIDATION, 400, "latitude must be a number")
        if isinstance(longitude, bool) or not isinstance(longitude, (int, float)):
            raise ApiError(ERR_VALIDATION, 400, "longitude must be a number")
    if kind in ("EXCHANGE_COMPLETE", "DISCHARGE"):
        distance = req_num(body, "distance_from_shore_nm", gte=0)
    if kind == "UPTAKE":
        salinity = req_num(body, "salinity_ppt", gte=0)
        source_port = req_str(body, "source_port_locode")

    with store.lock:
        # Priority 7: event must be inside the voyage window and not future.
        window_start = voyage["departed_at"] - timedelta(hours=6)
        if occurred_at < window_start or occurred_at > now():
            raise ApiError(ERR_EVENT_OUT_OF_WINDOW, 422,
                           "occurred_at is outside the voyage window or in "
                           "the future")
        if voyage["arrived_at"] is not None:
            window_end = voyage["arrived_at"] + timedelta(hours=6)
            if occurred_at > window_end:
                raise ApiError(ERR_EVENT_OUT_OF_WINDOW, 422,
                               "occurred_at is outside the voyage window or "
                               "in the future")

        existing = [e for e in store.ballast_events.values()
                    if e["voyage_id"] == voyage["id"]]

        # Priority 8: DISCHARGE requires a prior UPTAKE on the same tank.
        if kind == "DISCHARGE":
            has_uptake = any(
                e for e in existing
                if e["event_kind"] == "UPTAKE" and e["tank_id"] == tank_id
                and e["occurred_at"] <= occurred_at)
            if not has_uptake:
                raise ApiError(ERR_DISCHARGE_WITHOUT_UPTAKE, 422,
                               "DISCHARGE on a tank with no prior UPTAKE")

        # Priority 9: physically implausible inshore exchange.
        if kind == "EXCHANGE_COMPLETE" and distance is not None and distance < 3:
            raise ApiError(ERR_EXCHANGE_TOO_CLOSE, 422,
                           "EXCHANGE_COMPLETE closer than 3 nm from shore is "
                           "physically implausible")

        # Priority 15: chronological per-tank balance must never go negative.
        timeline = [e for e in existing if e["tank_id"] == tank_id
                    and e["event_kind"] in ("UPTAKE", "DISCHARGE")]
        timeline.sort(key=lambda e: (e["occurred_at"], e["_seq"]))
        balance = Decimal("0")
        inserted = False
        candidate = Decimal(str(volume)) if kind in ("UPTAKE", "DISCHARGE") else None
        for e in timeline:
            if not inserted and (occurred_at, float("inf")) < (e["occurred_at"], 0):
                if kind == "UPTAKE":
                    balance += candidate
                elif kind == "DISCHARGE":
                    balance -= candidate
                if balance < 0:
                    raise ApiError(ERR_TANK_BALANCE_NEGATIVE, 422,
                                   "chronological per-tank balance would go "
                                   "negative")
                inserted = True
            if e["event_kind"] == "UPTAKE":
                balance += Decimal(str(e["volume_m3"]))
            else:
                balance -= Decimal(str(e["volume_m3"]))
            if balance < 0:
                raise ApiError(ERR_TANK_BALANCE_NEGATIVE, 422,
                               "chronological per-tank balance would go "
                               "negative")
        if not inserted:
            if kind == "UPTAKE":
                balance += candidate
            elif kind == "DISCHARGE":
                balance -= candidate
            if balance < 0:
                raise ApiError(ERR_TANK_BALANCE_NEGATIVE, 422,
                               "chronological per-tank balance would go "
                               "negative")

        # Priority 16: a single event may not exceed ballast capacity.
        if volume > vessel["ballast_capacity_m3"]:
            raise ApiError(ERR_VOLUME_EXCEEDS_CAPACITY, 422,
                           "volume_m3 exceeds the vessel's ballast capacity")

        event = mint({
            "voyage_id": voyage["id"],
            "event_kind": kind,
            "occurred_at": occurred_at,
            "tank_id": tank_id,
            "volume_m3": volume,
            "latitude": latitude,
            "longitude": longitude,
            "distance_from_shore_nm": distance,
            "salinity_ppt": salinity,
            "source_port_locode": source_port,
        }, ledger=True)
        store.ballast_events[event["id"]] = event
        touch(voyage)
        compute_determination(vessel, voyage, "BALLAST_EVENT_RECORDED")

        # A POST_DISCHARGE report is due 6 hours after the last DISCHARGE.
        if kind == "DISCHARGE":
            report = next(
                (r for r in store.reports.values()
                 if r["voyage_id"] == voyage["id"]
                 and r["report_type"] == "POST_DISCHARGE"), None)
            new_due = occurred_at + timedelta(hours=6)
            if report is None:
                report = mint({
                    "voyage_id": voyage["id"],
                    "report_type": "POST_DISCHARGE",
                    "due_at": new_due,
                    "submitted_at": None,
                    "status": "DRAFT",
                    "payload_summary": None,
                    "rejection_reason": None,
                })
                store.reports[report["id"]] = report
            elif report["status"] == "DRAFT":
                report["due_at"] = new_due
                touch(report)

    return ok(event_json(event), 201)


@bp.get("/vessels/<vessel_id>/voyages/<voyage_id>/ballast-events")
@require_roles(*ALL_ROLES)
def list_ballast_events(vessel_id, voyage_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    limit, offset = pagination_params()
    kind = query_filter("event_kind")
    tank = query_filter("tank_id")
    items = [e for e in store.ballast_events.values()
             if e["voyage_id"] == voyage["id"]]
    if kind is not None:
        items = [e for e in items if e["event_kind"] == kind]
    if tank is not None:
        items = [e for e in items if e["tank_id"] == tank]
    items = by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([event_json(e) for e in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Determinations
# ---------------------------------------------------------------------------

@bp.get("/vessels/<vessel_id>/voyages/<voyage_id>/determinations")
@require_roles(*ALL_ROLES)
def list_determinations(vessel_id, voyage_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    limit, offset = pagination_params()
    is_current = query_bool("is_current")
    items = [d for d in store.determinations.values()
             if d["voyage_id"] == voyage["id"]]
    if is_current is not None:
        items = [d for d in items if d["is_current"] == is_current]
    # Newest first.
    items.sort(key=lambda d: (d["created_at"], d["_seq"]), reverse=True)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([determination_json(d) for d in page], total, limit, offset)


@bp.post("/vessels/<vessel_id>/voyages/<voyage_id>/determinations/recompute")
@require_roles("ShoreComplianceOfficer", "FlagSurveyor")
def recompute_determination(vessel_id, voyage_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    _check_not_frozen(vessel)
    with store.lock:
        det = compute_determination(vessel, voyage, TRIGGER_MANUAL)
        touch(voyage)
    return ok(determination_json(det), 201)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@bp.get("/vessels/<vessel_id>/voyages/<voyage_id>/reports")
@require_roles(*ALL_ROLES)
def list_reports(vessel_id, voyage_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    limit, offset = pagination_params()
    report_type = query_filter("report_type")
    status = query_filter("status")
    items = [r for r in store.reports.values() if r["voyage_id"] == voyage["id"]]
    if report_type is not None:
        items = [r for r in items if r["report_type"] == report_type]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([report_json(r) for r in page], total, limit, offset)


@bp.post("/vessels/<vessel_id>/voyages/<voyage_id>/reports/<report_id>/submit")
@require_roles("VesselMaster")
def submit_report(vessel_id, voyage_id, report_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    report = get_report(voyage, report_id)
    if report["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a DRAFT report may be submitted")
    if voyage["reporting_status"] not in ("DUE", "OVERDUE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "the voyage reporting status does not permit "
                       "submission")
    _check_not_frozen(vessel)
    body = get_body()
    payload = req_field(body, "payload_summary")
    with store.lock:
        report["payload_summary"] = payload
        report["submitted_at"] = now()
        report["status"] = "SUBMITTED"
        touch(report)
        voyage["reporting_status"] = "SUBMITTED"
        touch(voyage)
    return ok(report_json(report), 200)


@bp.post("/vessels/<vessel_id>/voyages/<voyage_id>/reports/<report_id>/acknowledge")
@require_roles("FlagSurveyor")
def acknowledge_report(vessel_id, voyage_id, report_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    report = get_report(voyage, report_id)
    if report["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a SUBMITTED report may be acknowledged")
    with store.lock:
        report["status"] = "ACKNOWLEDGED"
        touch(report)
        voyage["reporting_status"] = "ACKNOWLEDGED"
        touch(voyage)
    return ok(report_json(report), 200)


@bp.post("/vessels/<vessel_id>/voyages/<voyage_id>/reports/<report_id>/reject")
@require_roles("FlagSurveyor")
def reject_report(vessel_id, voyage_id, report_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    report = get_report(voyage, report_id)
    if report["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a SUBMITTED report may be rejected")
    body = get_body()
    reason = req_str(body, "rejection_reason")
    with store.lock:
        report["status"] = "REJECTED"
        report["rejection_reason"] = reason
        touch(report)
        voyage["reporting_status"] = "DUE"
        touch(voyage)
    return ok(report_json(report), 200)
