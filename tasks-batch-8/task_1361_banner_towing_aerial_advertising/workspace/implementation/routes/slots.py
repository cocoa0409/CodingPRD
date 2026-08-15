"""Flight slots, weather assessments, flight logs, proof of flight (PRD 3.5-3.7)."""
from datetime import timedelta

from flask import Blueprint, request

from db import DB, clock_now, new_id, now_iso
from errors import ApiError
from middleware import auth, client_owner_guard
from response import ok, ok_list
from services import (
    aircraft_double_booked,
    cancel_slot_by_client,
    cancel_slot_by_weather,
    capacity_for,
    check_make_good_source,
    consume_capacity,
    go_no_go_verdict,
    hours_remaining,
    log_of_slot,
    maybe_complete_campaign,
    new_evidence_record,
    new_record,
    proof_of_slot,
    pub,
    recompute_campaign,
    select_aircraft,
    select_pilot,
    slot_interval,
    slot_month,
    sorted_created,
    tfr_blocks,
    touch,
    window_contains,
    get_assessment,
    get_campaign,
    get_log,
    get_slot,
)
from util import (
    as_date,
    as_enum,
    as_int,
    as_iso_dt,
    as_num,
    as_str,
    as_version,
    body,
    dec,
    pagination_args,
    required,
    round_tenth_hour,
)

bp = Blueprint("slots", __name__, url_prefix="/btaa")

SLOT_READ = [
    "PlatformAdmin",
    "Dispatcher",
    "FinanceOfficer",
    "ComplianceOfficer",
    "Client",
    "Pilot",
    "GroundCrewLead",
]
ASSESSMENT_READ = ["PlatformAdmin", "Dispatcher", "ComplianceOfficer", "Client", "Pilot"]
LOG_READ = [
    "PlatformAdmin",
    "Dispatcher",
    "FinanceOfficer",
    "ComplianceOfficer",
    "Client",
    "Pilot",
]
PICKUP_TECHNIQUES = {"GROUND_PICKUP", "AERIAL_PICKUP"}
PICKUP_OUTCOMES = {"CLEAN", "RETRIED", "FAILED"}


def _list(recs, filters):
    items = sorted_created(recs)
    for key, val in filters.items():
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([pub(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Flight slot creation = booking in one step (PRD 3.5).
# ---------------------------------------------------------------------------
@bp.post("/campaigns/<cid>/flight_slots")
def create_flight_slot(cid):
    user_id, role = auth(["Client", "Dispatcher"])
    camp = get_campaign(cid)
    data = body()
    route_id = as_str(required(data, "route_id"), "route_id")
    approval_id = as_str(required(data, "airspace_approval_id"), "airspace_approval_id")
    banner_id = as_str(required(data, "banner_id"), "banner_id")
    date_local, date_d = as_date(required(data, "date_local"), "date_local")
    start_raw, start_dt = as_iso_dt(
        required(data, "planned_start_utc"), "planned_start_utc"
    )
    duration = as_int(
        required(data, "planned_duration_hours"), "planned_duration_hours"
    )
    if duration < 1 or duration > 8:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "planned_duration_hours must be an integer in 1..8",
        )
    expected_cap_version = as_version(
        required(data, "expected_seasonal_capacity_version"),
        "expected_seasonal_capacity_version",
    )
    supersedes_slot_id = data.get("supersedes_slot_id")
    if supersedes_slot_id is not None:
        as_str(supersedes_slot_id, "supersedes_slot_id")

    # Body-referenced FK existence (PRD 2.6), in the scaffold-declared order.
    banner = DB["banners"].get(banner_id)
    if banner is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    route = DB["routes"].get(route_id)
    if route is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    approval = DB["airspace_approvals"].get(approval_id)
    if approval is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    if supersedes_slot_id is not None and supersedes_slot_id not in DB["flight_slots"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")

    slot_start, slot_end = slot_interval(start_dt, duration)

    # From-state check (PRD 2.7): state checks run after existence checks and
    # before any business rule. Creating a slot is a transition on the parent
    # campaign; a terminal campaign (COMPLETE / CANCELLED) permits none.
    if camp["status"] not in ("DRAFT", "BOOKED", "IN_FLIGHT"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Campaign is not in a state permitting flight-slot creation",
        )

    # Business rules in the pinned order of PRD 3.5.
    # 1) TFR check (stadium routes only).
    if tfr_blocks(route, slot_start, slot_end, approval):
        raise ApiError(
            "ERR_TFR_BLOCKS_SLOT",
            409,
            "Stadium slot overlaps a PUBLISHED TFR without a waiver",
        )
    # 2) Airspace approval must be GRANTED for this (route, date).
    if (
        approval["status"] != "GRANTED"
        or approval["route_id"] != route["id"]
        or approval["date_local"] != date_local
    ):
        raise ApiError(
            "ERR_AIRSPACE_NOT_APPROVED",
            409,
            "AirspaceApproval is not GRANTED for this route and date",
        )
    # 3) Banner readiness: READY, current revision set, long enough for route.
    if (
        banner["status"] != "READY"
        or not banner.get("current_revision_id")
        or banner["banner_length_ft"] < route["min_banner_length_ft"]
    ):
        raise ApiError(
            "ERR_BANNER_NOT_READY", 409, "Banner is not READY for this route"
        )
    # 4) Make-good source validity.
    if supersedes_slot_id is not None:
        check_make_good_source(supersedes_slot_id)
    # Selectors draft resources on the client's behalf; the aircraft pick is
    # needed for the double-booking check.
    aircraft = select_aircraft(route, banner, duration)
    # 5) Double-booking check on the selected aircraft (half-open overlap).
    if aircraft_double_booked(aircraft["id"], slot_start, slot_end):
        raise ApiError(
            "ERR_AIRCRAFT_DOUBLE_BOOKED",
            409,
            "Selected aircraft has an overlapping FlightSlot",
        )
    pilot = select_pilot(route, duration)
    # 6) Temporal: at least 24h in the future at booking time.
    if slot_start - clock_now() < timedelta(hours=24):
        raise ApiError(
            "ERR_BOOKING_TOO_SOON",
            409,
            "planned_start_utc is less than 24h in the future",
        )
    # 7) Temporal: the planned window must lie entirely inside the approval window.
    if not window_contains(approval, slot_start, slot_end):
        raise ApiError(
            "ERR_OUTSIDE_APPROVAL_WINDOW",
            409,
            "Planned window exceeds the approval window",
        )
    # 8) Seasonal capacity: hours_remaining must cover the planned duration.
    cap = capacity_for(route["base_id"], slot_month({"date_local": date_local}))
    if cap is None or hours_remaining(cap) < duration:
        raise ApiError(
            "ERR_SEASONAL_CAPACITY_EXCEEDED",
            409,
            "Seasonal capacity exhausted for this base and month",
        )
    # Ownership (priority 20, business_referential): a Client books only under
    # campaigns it owns; Dispatchers act on the client's behalf.
    client_owner_guard(role, user_id, camp["client_id"])
    # 9) OCC runs last (PRD 2.10).
    if expected_cap_version != cap["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412, "expected_seasonal_capacity_version is stale"
        )

    rec = new_record()
    rec.update(
        {
            "campaign_id": camp["id"],
            "route_id": route["id"],
            "airspace_approval_id": approval["id"],
            "banner_id": banner["id"],
            "date_local": date_local,
            "planned_start_utc": start_raw,
            "planned_duration_hours": duration,
            "assigned_aircraft_id": aircraft["id"],
            "assigned_pilot_id": pilot["id"],
            "supersedes_slot_id": supersedes_slot_id,
            "consumed_make_good_credit_id": None,
            "status": "BOOKED",
            "weather_hold_count": 0,
            "cancelled_at_utc": None,
            "_planned_start_dt": start_dt,
            "_date_local_date": date_d,
            "_cancelled_dt": None,
        }
    )
    DB["flight_slots"][rec["id"]] = rec
    # Booking consumes capacity immediately (PRD 3.5).
    consume_capacity(rec)
    recompute_campaign(camp)
    return ok(pub(rec), status=201)


@bp.get("/campaigns/<cid>/flight_slots")
def list_campaign_slots(cid):
    user_id, role = auth(SLOT_READ)
    camp = get_campaign(cid)
    client_owner_guard(role, user_id, camp["client_id"])
    recs = [s for s in DB["flight_slots"].values() if s["campaign_id"] == camp["id"]]
    return _list(
        recs,
        {
            "status": request.args.get("status"),
            "date_local": request.args.get("date_local"),
        },
    )


@bp.get("/flight_slots/<sid>")
def get_one_slot(sid):
    user_id, role = auth(SLOT_READ)
    s = get_slot(sid)
    camp = DB["campaigns"].get(s["campaign_id"])
    if camp:
        client_owner_guard(role, user_id, camp["client_id"])
    return ok(pub(s))


@bp.get("/flight_slots")
def list_slots_system():
    user_id, role = auth(SLOT_READ)
    recs = list(DB["flight_slots"].values())
    if role == "Client":
        own = {
            c["id"]
            for c in DB["campaigns"].values()
            if c["client_id"] == user_id
        }
        recs = [s for s in recs if s["campaign_id"] in own]
    return _list(
        recs,
        {
            "route_id": request.args.get("route_id"),
            "airspace_approval_id": request.args.get("airspace_approval_id"),
            "banner_id": request.args.get("banner_id"),
            "assigned_aircraft_id": request.args.get("assigned_aircraft_id"),
            "assigned_pilot_id": request.args.get("assigned_pilot_id"),
            "supersedes_slot_id": request.args.get("supersedes_slot_id"),
            "consumed_make_good_credit_id": request.args.get(
                "consumed_make_good_credit_id"
            ),
            "campaign_id": request.args.get("campaign_id"),
            "status": request.args.get("status"),
            "date_local": request.args.get("date_local"),
        },
    )


# ---------------------------------------------------------------------------
# Scheduling (PRD 3.6)
# ---------------------------------------------------------------------------
@bp.post("/flight_slots/<sid>/schedule")
def schedule_slot(sid):
    auth(["Dispatcher"])
    s = get_slot(sid)
    if s["status"] != "BOOKED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "FlightSlot is not in a state permitting schedule",
        )
    # T-2h cutoff: anything closer than two hours before planned start fails.
    if s["_planned_start_dt"] - clock_now() < timedelta(hours=2):
        raise ApiError(
            "ERR_TOO_LATE_TO_SCHEDULE",
            409,
            "Within T-2h of planned_start_utc",
        )
    route = DB["routes"].get(s["route_id"])
    banner = DB["banners"].get(s["banner_id"])
    # Grounded aircraft / suspended pilots clear assignments; the selector
    # re-picks when the slot is scheduled again (PRD 3.1).
    if not s.get("assigned_aircraft_id"):
        a = select_aircraft(route, banner, s["planned_duration_hours"])
        s["assigned_aircraft_id"] = a["id"]
    if not s.get("assigned_pilot_id"):
        p = select_pilot(route, s["planned_duration_hours"])
        s["assigned_pilot_id"] = p["id"]
    aircraft = DB["aircraft"].get(s["assigned_aircraft_id"])
    if aircraft is None or aircraft["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Assigned aircraft is not ACTIVE"
        )
    pilot = DB["pilots"].get(s["assigned_pilot_id"])
    if pilot is not None and pilot["status"] == "SUSPENDED":
        raise ApiError(
            "ERR_PILOT_SUSPENDED", 409, "Assigned pilot is SUSPENDED"
        )
    if pilot is None or pilot["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Assigned pilot is not ACTIVE")
    s["status"] = "SCHEDULED"
    touch(s)
    camp = DB["campaigns"].get(s["campaign_id"])
    if camp is not None:
        # First scheduling under a BOOKED campaign pushes it to IN_FLIGHT.
        if camp["status"] == "BOOKED":
            camp["status"] = "IN_FLIGHT"
            touch(camp)
        recompute_campaign(camp)
    return ok(pub(s))


@bp.post("/flight_slots/<sid>/reschedule_after_hold")
def reschedule_after_hold(sid):
    auth(["Dispatcher"])
    s = get_slot(sid)
    data = body()
    start_raw, start_dt = as_iso_dt(
        required(data, "planned_start_utc"), "planned_start_utc"
    )
    if s["status"] != "WEATHER_HOLD":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "FlightSlot is not in a state permitting reschedule_after_hold",
        )
    if s["weather_hold_count"] >= 2:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Slot has held twice and must be cancelled instead",
        )
    approval = DB["airspace_approvals"].get(s["airspace_approval_id"])
    slot_start, slot_end = slot_interval(start_dt, s["planned_duration_hours"])
    if approval is None or not window_contains(approval, slot_start, slot_end):
        raise ApiError(
            "ERR_OUTSIDE_APPROVAL_WINDOW",
            409,
            "New planned_start_utc falls outside the approval window",
        )
    s["planned_start_utc"] = start_raw
    s["_planned_start_dt"] = start_dt
    s["status"] = "SCHEDULED"
    touch(s)
    camp = DB["campaigns"].get(s["campaign_id"])
    if camp is not None:
        recompute_campaign(camp)
    return ok(pub(s))


# ---------------------------------------------------------------------------
# Weather assessments (PRD 3.6)
# ---------------------------------------------------------------------------
@bp.post("/flight_slots/<sid>/weather_assessments")
def create_assessment(sid):
    user_id, role = auth(["Pilot", "Dispatcher", "PlatformAdmin"])
    s = get_slot(sid)
    data = body()
    ceiling = as_int(required(data, "ceiling_ft"), "ceiling_ft")
    visibility = as_num(required(data, "visibility_sm"), "visibility_sm")
    wind = as_int(required(data, "wind_kts"), "wind_kts")
    if s["status"] not in ("SCHEDULED", "WEATHER_HOLD"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "FlightSlot is not in a state permitting weather assessment",
        )
    verdict = go_no_go_verdict(visibility, ceiling, wind)
    assessor = user_id if role == "Pilot" else s.get("assigned_pilot_id")
    rec = new_evidence_record()
    rec.update(
        {
            "slot_id": s["id"],
            "assessed_at_utc": now_iso(),
            "ceiling_ft": ceiling,
            "visibility_sm": visibility,
            "wind_kts": wind,
            "verdict": verdict,
            "assessed_by_pilot_id": assessor,
        }
    )
    DB["weather_assessments"][rec["id"]] = rec
    if verdict == "NO_GO":
        # GO/MARGINAL leave the slot untouched; NO_GO drives the machine.
        s["weather_hold_count"] += 1
        if s["weather_hold_count"] >= 2:
            cancel_slot_by_weather(s)
        else:
            s["status"] = "WEATHER_HOLD"
            touch(s)
            camp = DB["campaigns"].get(s["campaign_id"])
            if camp is not None:
                recompute_campaign(camp)
    return ok(pub(rec), status=201)


@bp.get("/flight_slots/<sid>/weather_assessments")
def list_slot_assessments(sid):
    user_id, role = auth(ASSESSMENT_READ)
    s = get_slot(sid)
    camp = DB["campaigns"].get(s["campaign_id"])
    if camp:
        client_owner_guard(role, user_id, camp["client_id"])
    recs = [a for a in DB["weather_assessments"].values() if a["slot_id"] == s["id"]]
    return _list(recs, {})


@bp.get("/weather_assessments/<aid>")
def get_one_assessment(aid):
    user_id, role = auth(ASSESSMENT_READ)
    a = get_assessment(aid)
    if role == "Pilot" and a.get("assessed_by_pilot_id") not in (None, user_id):
        raise ApiError(
            "ERR_UNAUTHORIZED_OWNER", 403, "Pilot does not own this resource"
        )
    if role == "Client":
        s = DB["flight_slots"].get(a["slot_id"])
        camp = DB["campaigns"].get(s["campaign_id"]) if s else None
        if camp:
            client_owner_guard(role, user_id, camp["client_id"])
    return ok(pub(a))


@bp.get("/weather_assessments")
def list_assessments_system():
    user_id, role = auth(["PlatformAdmin", "Dispatcher", "ComplianceOfficer", "Pilot"])
    recs = list(DB["weather_assessments"].values())
    if role == "Pilot":
        recs = [a for a in recs if a.get("assessed_by_pilot_id") == user_id]
    return _list(
        recs,
        {
            "assessed_by_pilot_id": request.args.get("assessed_by_pilot_id"),
            "slot_id": request.args.get("slot_id"),
        },
    )


# ---------------------------------------------------------------------------
# Flight log (PRD 3.6)
# ---------------------------------------------------------------------------
@bp.post("/flight_slots/<sid>/flight_log")
def file_flight_log(sid):
    user_id, role = auth(["Pilot"])
    s = get_slot(sid)
    data = body()
    hobbs_out = as_num(required(data, "hobbs_out"), "hobbs_out")
    hobbs_in = as_num(required(data, "hobbs_in"), "hobbs_in")
    technique = as_enum(
        required(data, "pickup_technique"), "pickup_technique", PICKUP_TECHNIQUES
    )
    outcome = as_enum(
        required(data, "pickup_outcome"), "pickup_outcome", PICKUP_OUTCOMES
    )
    notes = as_str(required(data, "tow_field_notes"), "tow_field_notes")
    pilot = DB["pilots"].get(user_id)
    # Guards fire in the fixed order of PRD 3.6: from-state, endorsement,
    # hobbs sanity, assigned-pilot ownership, segregation of duties.
    if s["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "FlightSlot is not in a state permitting flight_log",
        )
    if technique == "AERIAL_PICKUP" and pilot["tow_endorsement_level"] == "TRAINEE":
        raise ApiError(
            "ERR_PICKUP_TECHNIQUE_NOT_ENDORSED",
            409,
            "AERIAL_PICKUP requires a non-TRAINEE endorsement",
        )
    if not dec(hobbs_in) > dec(hobbs_out):
        raise ApiError(
            "ERR_INVALID_HOBBS", 422, "hobbs_in must be greater than hobbs_out"
        )
    if s.get("assigned_pilot_id") != pilot["id"]:
        raise ApiError(
            "ERR_UNAUTHORIZED_OWNER",
            403,
            "Only the assigned pilot may file the FlightLog",
        )
    approval = DB["airspace_approvals"].get(s.get("airspace_approval_id") or "")
    if approval is not None and approval.get("_granted_by") == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "The granting ComplianceOfficer may not file this FlightLog",
        )

    hobbs_hours = round_tenth_hour(dec(hobbs_in) - dec(hobbs_out))
    filed_at = now_iso()
    rec = new_record()
    rec.update(
        {
            "slot_id": s["id"],
            "aircraft_id": s.get("assigned_aircraft_id"),
            "pilot_id": pilot["id"],
            "hobbs_out": hobbs_out,
            "hobbs_in": hobbs_in,
            "hobbs_hours": float(hobbs_hours),
            "pickup_technique": technique,
            "pickup_outcome": outcome,
            "tow_field_notes": notes,
            "filed_at_utc": filed_at,
            "_hobbs_hours": hobbs_hours,
        }
    )
    DB["flight_logs"][rec["id"]] = rec

    s["status"] = "FLOWN"
    touch(s)

    aircraft = DB["aircraft"].get(rec["aircraft_id"] or "")
    # Season totals accrue only within the active season, May 1 - Sep 30
    # (PRD 2.9), keyed by the flight's local service date.
    month = int(s["date_local"][5:7])
    in_season = 5 <= month <= 9
    if aircraft is not None:
        if in_season:
            aircraft["_season_hours"] += hobbs_hours
            aircraft["season_hours_flown"] = float(aircraft["_season_hours"])
        touch(aircraft)
    if in_season:
        pilot["_season_hours"] += hobbs_hours
        pilot["season_hours_flown"] = float(pilot["_season_hours"])
    # Pickup-failure career consequence: three failures suspend (inclusive).
    if outcome == "FAILED":
        pilot["season_pickup_failure_count"] += 1
        if (
            pilot["season_pickup_failure_count"] >= 3
            and pilot["status"] == "ACTIVE"
        ):
            pilot["status"] = "SUSPENDED"
            for other in DB["flight_slots"].values():
                if (
                    other.get("assigned_pilot_id") == pilot["id"]
                    and other["status"] == "SCHEDULED"
                ):
                    other["status"] = "BOOKED"
                    other["assigned_pilot_id"] = None
                    touch(other)
    touch(pilot)

    camp = DB["campaigns"].get(s["campaign_id"])
    if camp is not None:
        recompute_campaign(camp)
        maybe_complete_campaign(camp)
    return ok(pub(rec), status=201)


@bp.get("/flight_slots/<sid>/flight_logs")
def list_slot_logs(sid):
    user_id, role = auth(LOG_READ)
    s = get_slot(sid)
    camp = DB["campaigns"].get(s["campaign_id"])
    if camp:
        client_owner_guard(role, user_id, camp["client_id"])
    recs = [l for l in DB["flight_logs"].values() if l["slot_id"] == s["id"]]
    return _list(recs, {})


@bp.get("/flight_logs/<lid>")
def get_one_log(lid):
    user_id, role = auth(LOG_READ)
    log = get_log(lid)
    if role == "Pilot" and log.get("pilot_id") != user_id:
        raise ApiError(
            "ERR_UNAUTHORIZED_OWNER", 403, "Pilot does not own this resource"
        )
    if role == "Client":
        s = DB["flight_slots"].get(log["slot_id"])
        camp = DB["campaigns"].get(s["campaign_id"]) if s else None
        if camp:
            client_owner_guard(role, user_id, camp["client_id"])
    return ok(pub(log))


@bp.get("/flight_logs")
def list_logs_system():
    user_id, role = auth(LOG_READ)
    recs = list(DB["flight_logs"].values())
    if role == "Pilot":
        recs = [l for l in recs if l.get("pilot_id") == user_id]
    elif role == "Client":
        own = {c["id"] for c in DB["campaigns"].values() if c["client_id"] == user_id}
        recs = [
            l
            for l in recs
            if (DB["flight_slots"].get(l["slot_id"]) or {}).get("campaign_id") in own
        ]
    return _list(
        recs,
        {
            "aircraft_id": request.args.get("aircraft_id"),
            "pilot_id": request.args.get("pilot_id"),
            "slot_id": request.args.get("slot_id"),
        },
    )


# ---------------------------------------------------------------------------
# Client-initiated cancellation (PRD 3.6)
# ---------------------------------------------------------------------------
@bp.post("/flight_slots/<sid>/cancel_by_client")
def cancel_by_client(sid):
    user_id, role = auth(["Client"])
    s = get_slot(sid)
    if s["status"] not in ("BOOKED", "SCHEDULED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "FlightSlot is not in a state permitting cancel_by_client",
        )
    camp = DB["campaigns"].get(s["campaign_id"])
    client_owner_guard(role, user_id, camp["client_id"] if camp else None)
    cancel_slot_by_client(s)
    return ok(pub(s))


# ---------------------------------------------------------------------------
# Proof of flight (PRD 3.7)
# ---------------------------------------------------------------------------
@bp.post("/flight_slots/<sid>/proof_of_flight")
def submit_proof(sid):
    user_id, role = auth(["Pilot"])
    s = get_slot(sid)
    data = body()
    gps = as_str(required(data, "gps_track_digest"), "gps_track_digest")
    photo = as_str(required(data, "photo_hash"), "photo_hash")
    attestation = data.get("pilot_attestation")
    if attestation is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Missing required field: pilot_attestation"
        )
    if not isinstance(attestation, bool):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Field pilot_attestation must be a boolean"
        )
    if s["status"] != "FLOWN":
        raise ApiError(
            "ERR_SLOT_NOT_FLOWN", 409, "ProofOfFlight requires a FLOWN slot"
        )
    if s.get("assigned_pilot_id") != user_id:
        raise ApiError(
            "ERR_UNAUTHORIZED_OWNER",
            403,
            "Only the assigned pilot may submit ProofOfFlight",
        )
    if proof_of_slot(s["id"]) is not None:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "ProofOfFlight already submitted for this slot"
        )
    rec = new_evidence_record()
    rec.update(
        {
            "slot_id": s["id"],
            "gps_track_digest": gps,
            "photo_hash": photo,
            "pilot_attestation": attestation,
            "submitted_at_utc": now_iso(),
            "finalized": False,
        }
    )
    DB["proof_of_flights"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.get("/flight_slots/<sid>/proof_of_flight")
def list_slot_proofs(sid):
    user_id, role = auth(
        ["PlatformAdmin", "ComplianceOfficer", "Client", "Pilot", "FinanceOfficer"]
    )
    s = get_slot(sid)
    camp = DB["campaigns"].get(s["campaign_id"])
    if camp:
        client_owner_guard(role, user_id, camp["client_id"])
    recs = [p for p in DB["proof_of_flights"].values() if p["slot_id"] == s["id"]]
    return _list(recs, {})


@bp.post("/proof_of_flight/<pid>/finalize")
def finalize_proof(pid):
    auth(["ComplianceOfficer"])
    proof = None
    for p in DB["proof_of_flights"].values():
        if p["id"] == pid:
            proof = p
            break
    if proof is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    proof["finalized"] = True
    return ok(pub(proof))
