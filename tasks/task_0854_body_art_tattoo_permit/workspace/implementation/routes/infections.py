"""Infection-report routes — PRD §3.7 (two independent axes)."""

from flask import Blueprint

import config
import domain
import serialize
import store
import validate as V
from auth import authenticate, require_owns_establishment
from envelope import array_response, force, send, watch
from errors import ApiError
from util import hours

bp = Blueprint("infections", __name__)

READ_ROLES = ["HealthOfficer", "Inspector", "RecordsClerk", "EstablishmentOperator"]


@bp.post("/body-art/infection-reports")
def create_infection_report():
    caller = authenticate(["PublicUser", "EstablishmentOperator"])
    data = V.body()
    establishment_id = V.req_id(data, "establishment_id")
    artist_id = V.opt_id(data, "artist_id")
    reporter_contact = V.req_string(data, "reporter_contact", 1, 120)
    infection_type = V.req_enum(data, "infection_type", config.INFECTION_TYPES)
    procedure_date = V.req_datetime(data, "procedure_date")
    symptom_onset_at = V.req_datetime(data, "symptom_onset_at")
    if symptom_onset_at < procedure_date:
        raise V.bad("symptom_onset_at must be at or after procedure_date.")

    est = V.get_establishment(establishment_id)
    if artist_id is not None:
        V.get_artist(artist_id)
    require_owns_establishment(caller, establishment_id)

    created_at = store.now()
    rec = domain.new_record(
        {
            "establishment_id": est["id"],
            "artist_id": artist_id,
            "reporter_contact": reporter_contact,
            "infection_type": infection_type,
            "procedure_date": procedure_date,
            "symptom_onset_at": symptom_onset_at,
            "investigation_status": "RECEIVED",
            "notification_status": "PENDING",
            "notification_due_at": created_at
            + hours(config.INFECTION_NOTIFICATION_DEADLINE_HOURS),
            "notification_late": False,
            "reopen_count": 0,
        }
    )
    store.infection_reports[rec["id"]] = rec
    return send(lambda: serialize.infection_report(rec), 201)


@bp.get("/body-art/infection-reports/<infection_report_id>")
def read_infection_report(infection_report_id):
    authenticate(READ_ROLES)
    rec = V.get_infection_report(infection_report_id)
    return send(lambda: serialize.infection_report(rec), 200)


@bp.get("/body-art/infection-reports")
def list_infection_reports():
    authenticate(READ_ROLES)
    limit, offset = V.pagination()
    establishment_id = V.filter_string("establishment_id")
    artist_id = V.filter_string("artist_id")
    investigation_status = V.filter_enum(
        "investigation_status", config.INVESTIGATION_STATUSES
    )
    notification_status = V.filter_enum(
        "notification_status", config.NOTIFICATION_STATUSES
    )

    rows = store.sorted_rows(store.infection_reports)
    if establishment_id is not None:
        rows = [r for r in rows if r["establishment_id"] == establishment_id]
    if artist_id is not None:
        rows = [r for r in rows if r["artist_id"] == artist_id]
    if investigation_status is not None:
        rows = [r for r in rows if r["investigation_status"] == investigation_status]
    if notification_status is not None:
        rows = [r for r in rows if r["notification_status"] == notification_status]
    page, total = V.paginate(rows, limit, offset)
    return array_response(
        [serialize.infection_report(r) for r in page], limit, offset, total
    )


@bp.post("/body-art/infection-reports/<infection_report_id>/investigation")
def advance_investigation(infection_report_id):
    authenticate(["HealthOfficer"])
    rec = V.get_infection_report(infection_report_id)
    data = V.body()
    action = V.req_enum(data, "action", config.INVESTIGATION_ACTIONS)

    expected_from = {
        "SCREEN": "RECEIVED",
        "CONFIRM": "SCREENING",
        "RULE_OUT": "SCREENING",
        "REOPEN": "RULED_OUT",
    }[action]
    if rec["investigation_status"] != expected_from:
        raise ApiError("ERR_INFECTION_STATE_INVALID")

    est = store.establishments.get(rec["establishment_id"])

    if action == "SCREEN":
        watch(rec)
        rec["investigation_status"] = "SCREENING"
    elif action == "CONFIRM":
        watch(rec)
        rec["investigation_status"] = "CONFIRMED"
        artist = (
            store.artists.get(rec["artist_id"]) if rec.get("artist_id") else None
        )
        if artist is not None:
            watch(artist)
            artist["bbp_recert_required"] = True
            if artist["permit_status"] == "ACTIVE":
                artist["permit_status"] = "PROBATION"
        if est is not None:
            force(est)
            domain.recompute_active_artist_count(est)
            domain.recompute_risk_and_posture(est)
    elif action == "RULE_OUT":
        watch(rec)
        rec["investigation_status"] = "RULED_OUT"
        if est is not None:
            domain.recompute_risk_and_posture(est)
    else:  # REOPEN
        if rec["reopen_count"] >= config.INFECTION_MAX_REOPENS:
            raise ApiError("ERR_INFECTION_REOPEN_LIMIT")
        watch(rec)
        rec["investigation_status"] = "SCREENING"
        rec["reopen_count"] += 1
        if est is not None:
            domain.recompute_risk_and_posture(est)

    return send(lambda: serialize.infection_report(rec), 200)


@bp.post("/body-art/infection-reports/<infection_report_id>/notification")
def advance_notification(infection_report_id):
    authenticate(["HealthOfficer"])
    rec = V.get_infection_report(infection_report_id)
    data = V.body()
    action = V.req_enum(data, "action", config.NOTIFICATION_ACTIONS)

    current = rec["notification_status"]
    if action == "NOTIFY":
        if current != "PENDING":
            raise ApiError("ERR_INFECTION_STATE_INVALID")
        watch(rec)
        rec["notification_status"] = "CDC_NOTIFIED"
        rec["notification_late"] = store.now() >= rec["notification_due_at"]
    elif action == "MARK_NOT_REQUIRED":
        if current != "PENDING":
            raise ApiError("ERR_INFECTION_STATE_INVALID")
        if rec["infection_type"] != "OTHER":
            raise ApiError("ERR_NOTIFICATION_NOT_WAIVABLE")
        watch(rec)
        rec["notification_status"] = "NOT_REQUIRED"
    else:  # CLOSE
        if current not in ("CDC_NOTIFIED", "NOT_REQUIRED"):
            raise ApiError("ERR_INFECTION_STATE_INVALID")
        watch(rec)
        rec["notification_status"] = "CLOSED"

    return send(lambda: serialize.infection_report(rec), 200)
