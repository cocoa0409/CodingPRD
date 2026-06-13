"""Visit endpoints: rooming, charting, discharge, transfer, billing
(PRD §3.5, §3.6, §3.7)."""
from flask import Blueprint, request

import clock
import serialize
from db import db, stamp_create, touch
from errors import err
from middleware import authorize
from response import ok_object, ok_array
from validation import get_json_body, parse_pagination, paginate, require_str
from routes.lookup import get_path, get_fk
from services import compute

bp = Blueprint("visits", __name__)

READ_ROLES = ["ClinicManager", "FrontDeskClerk", "Provider"]
TRANSFER_REASONS = {"ACUITY_ESCALATION", "CAPABILITY_GAP", "PATIENT_REQUEST"}
TRANSFER_MODES = {"AMBULANCE", "PRIVATE_VEHICLE"}


# ---------------------------------------------------------------------------
# Rooming: POST /visits
# ---------------------------------------------------------------------------
@bp.route("/visits", methods=["POST"])
def create_visit():
    authorize(["Provider"])
    body = get_json_body()

    # Body FK resolution (P11) — left to right per the listed order.
    qe_id = body.get("queue_entry_id")
    provider_id = body.get("provider_id")
    room_id = body.get("exam_room_id")
    if qe_id is None or provider_id is None or room_id is None:
        raise err("ERR_INVALID_REQUEST", "queue_entry_id, provider_id, exam_room_id required")
    qe = get_fk("queue_entry", qe_id)
    provider = get_fk("provider", provider_id)
    room = get_fk("exam_room", room_id)

    # Well-formedness (P20): expected_clinic_version required.
    expected_version = body.get("expected_clinic_version")
    if expected_version is None or not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise err("ERR_INVALID_REQUEST", "expected_clinic_version required")
    override = body.get("override", False)
    if not isinstance(override, bool):
        raise err("ERR_INVALID_REQUEST", "override must be boolean")

    clinic = db.clinics.get(qe["clinic_id"])

    # State legality (P30): queue entry must be READY_FOR_PROVIDER.
    if qe["status"] != "READY_FOR_PROVIDER":
        raise err("ERR_INVALID_STATE", "queue entry not READY_FOR_PROVIDER")

    # OCC (P31): expected_clinic_version must match the clinic's current version.
    if clinic is None or expected_version != clinic["version"]:
        raise err("ERR_STALE_VERSION", "clinic version mismatch")

    # P40 queue order: must be the lowest priority_rank among READY_FOR_PROVIDER.
    if not override and not _is_front_ready(qe):
        raise err("ERR_QUEUE_ORDER_VIOLATION", "not the front-of-line READY entry")

    # P41 isolation: airborne entry needs an ISOLATION room.
    if qe["airborne_precaution"] and room["room_type"] != "ISOLATION":
        raise err("ERR_ISOLATION_REQUIRED", "airborne entry requires ISOLATION room")

    # P43 room available.
    if room["status"] != "AVAILABLE":
        raise err("ERR_ROOM_UNAVAILABLE", "exam room not AVAILABLE")

    # P44 provider capacity.
    active = _provider_active_count(provider["id"])
    if not provider["on_shift"] or active >= provider["max_concurrent_visits"]:
        raise err("ERR_PROVIDER_AT_CAPACITY", "provider off-shift or at capacity")

    # All checks passed — create the visit and cascade.
    visit = stamp_create({
        "queue_entry_id": qe["id"],
        "patient_id": qe["patient_id"],
        "exam_room_id": room["id"],
        "provider_id": provider["id"],
        "clinical_status": "IN_EXAM",
        "billing_status": "OPEN",
        "chart_note": None,
        "acuity_at_rooming": qe["esi_level"],
        "charges_subtotal_cents": 0,
        "patient_responsibility_cents": 0,
        "disposition": None,
    })
    db.visits[visit["id"]] = visit

    # QueueEntry -> ROOMED.
    qe["status"] = "ROOMED"
    touch(qe)

    # ExamRoom AVAILABLE -> OCCUPIED (cascade).
    room["status"] = "OCCUPIED"
    room["current_visit_id"] = visit["id"]
    touch(room)

    # Provider active_visit_count is derived; touch for version bump.
    touch(provider)

    # Decrement depth / recompute posture / rooms; bump clinic version.
    compute.recompute_clinic(clinic)

    return ok_object(serialize.visit(visit), 201)


def _provider_active_count(provider_id):
    return sum(
        1 for v in db.visits.values()
        if v.get("provider_id") == provider_id and v["clinical_status"] in ("IN_EXAM", "CHARTING")
    )


def _is_front_ready(qe):
    ready = [
        q for q in compute.ranked_active_entries(qe["clinic_id"])
        if q["status"] == "READY_FOR_PROVIDER"
    ]
    if not ready:
        return False
    return ready[0]["id"] == qe["id"]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.route("/visits/<vid>", methods=["GET"])
def get_visit(vid):
    authorize(READ_ROLES)
    visit = get_path("visit", vid)
    return ok_object(serialize.visit(visit))


@bp.route("/visits", methods=["GET"])
def list_visits():
    authorize(READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.visits.values())
    for key in ("queue_entry_id", "provider_id", "exam_room_id", "patient_id"):
        val = request.args.get(key)
        if val is not None:
            items = [v for v in items if v.get(key) == val]
    items.sort(key=lambda v: (v["created_at"], v["id"]))
    page = paginate(items, limit, offset)
    return ok_array([serialize.visit(v) for v in page], limit, offset, len(items))


# ---------------------------------------------------------------------------
# Clinical dimension
# ---------------------------------------------------------------------------
@bp.route("/visits/<vid>/start-charting", methods=["POST"])
def start_charting(vid):
    authorize(["Provider"])
    visit = get_path("visit", vid)
    if visit["clinical_status"] != "IN_EXAM":
        raise err("ERR_INVALID_STATE", "visit not IN_EXAM")
    visit["clinical_status"] = "CHARTING"
    touch(visit)
    return ok_object(serialize.visit(visit))


@bp.route("/visits/<vid>/complete-charting", methods=["POST"])
def complete_charting(vid):
    authorize(["Provider"])
    visit = get_path("visit", vid)
    body = get_json_body()
    chart_note = body.get("chart_note")
    if not isinstance(chart_note, str) or chart_note == "":
        raise err("ERR_INVALID_REQUEST", "chart_note required")
    if visit["clinical_status"] != "CHARTING":
        raise err("ERR_INVALID_STATE", "visit not CHARTING")

    visit["chart_note"] = chart_note
    visit["clinical_status"] = "PENDING_DISCHARGE"
    touch(visit)
    _release_room_and_provider(visit)
    return ok_object(serialize.visit(visit))


@bp.route("/visits/<vid>/discharge", methods=["POST"])
def discharge(vid):
    authorize(["Provider"])
    visit = get_path("visit", vid)
    # State legality first (P30), then fiscal (P52).
    if visit["clinical_status"] != "PENDING_DISCHARGE":
        raise err("ERR_INVALID_STATE", "visit not PENDING_DISCHARGE")
    if visit["billing_status"] not in ("CHARGES_POSTED", "INVOICED", "SETTLED"):
        raise err("ERR_CHARGES_NOT_FINALIZED", "charges must be finalized before discharge")
    if not _has_discharge_instruction(visit["id"]):
        raise err("ERR_INVALID_STATE", "discharge instruction required")

    visit["clinical_status"] = "DISCHARGED"
    visit["disposition"] = "HOME"
    touch(visit)
    return ok_object(serialize.visit(visit))


@bp.route("/visits/<vid>/transfer", methods=["POST"])
def transfer(vid):
    authorize(["Provider"])
    visit = get_path("visit", vid)
    body = get_json_body()
    require_str(body, "destination_facility")
    reason = body.get("transfer_reason")
    if reason not in TRANSFER_REASONS:
        raise err("ERR_INVALID_REQUEST", "invalid transfer_reason")
    mode = body.get("mode", "AMBULANCE")
    if mode not in TRANSFER_MODES:
        raise err("ERR_INVALID_REQUEST", "invalid mode")

    if visit["clinical_status"] not in ("IN_EXAM", "CHARTING"):
        raise err("ERR_INVALID_STATE", "visit not IN_EXAM or CHARTING")

    # P51 ambulance required for acute visits.
    if visit["acuity_at_rooming"] is not None and visit["acuity_at_rooming"] <= 2 and mode != "AMBULANCE":
        raise err("ERR_AMBULANCE_REQUIRED", "acute transfer must use AMBULANCE")

    # Create referral.
    referral = stamp_create({
        "visit_id": visit["id"],
        "destination_facility": body["destination_facility"],
        "transfer_reason": reason,
        "mode": mode,
        "accepted_at": None,
        "status": "INITIATED",
    })
    db.referrals[referral["id"]] = referral

    visit["clinical_status"] = "TRANSFERRED"
    visit["disposition"] = "ER_TRANSFER"
    touch(visit)
    _release_room_and_provider(visit)

    # Cascade: cancel any SCHEDULED occ-health order on the same queue entry.
    for o in db.occ_health_orders.values():
        if o["queue_entry_id"] == visit["queue_entry_id"] and o["status"] == "SCHEDULED":
            o["status"] = "CANCELLED"
            touch(o)

    return ok_object(serialize.visit(visit))


# ---------------------------------------------------------------------------
# Billing dimension
# ---------------------------------------------------------------------------
@bp.route("/visits/<vid>/post-charges", methods=["POST"])
def post_charges(vid):
    authorize(["Provider"])
    visit = get_path("visit", vid)

    # P53 billing frozen: once advanced past CHARGES_POSTED.
    if visit["billing_status"] in ("INVOICED", "SETTLED"):
        raise err("ERR_BILLING_FROZEN", "billing frozen")
    # State legality (P30): must be OPEN.
    if visit["billing_status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "billing not OPEN")
    # Precondition: at least one non-voided charge.
    has_charge = any(
        c["visit_id"] == visit["id"] and not c["voided"]
        for c in db.charges.values()
    )
    if not has_charge:
        raise err("ERR_INVALID_STATE", "no non-voided charge on visit")

    subtotal, responsibility = compute.compute_responsibility(visit)
    visit["charges_subtotal_cents"] = subtotal
    visit["patient_responsibility_cents"] = responsibility
    visit["billing_status"] = "CHARGES_POSTED"
    touch(visit)
    return ok_object(serialize.visit(visit))


@bp.route("/visits/<vid>/invoice", methods=["POST"])
def invoice(vid):
    authorize(["FrontDeskClerk"])
    visit = get_path("visit", vid)
    if visit["billing_status"] != "CHARGES_POSTED":
        raise err("ERR_INVALID_STATE", "billing not CHARGES_POSTED")
    visit["billing_status"] = "INVOICED"
    touch(visit)
    return ok_object(serialize.visit(visit))


@bp.route("/visits/<vid>/settle", methods=["POST"])
def settle(vid):
    authorize(["FrontDeskClerk"])
    visit = get_path("visit", vid)
    body = get_json_body()
    expected = body.get("expected_visit_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_INVALID_REQUEST", "expected_visit_version required")
    # State legality (P30) before OCC (P31).
    if visit["billing_status"] != "INVOICED":
        raise err("ERR_INVALID_STATE", "billing not INVOICED")
    if expected != visit["version"]:
        raise err("ERR_STALE_VERSION", "visit version mismatch")
    visit["billing_status"] = "SETTLED"
    touch(visit)
    return ok_object(serialize.visit(visit))


# ---------------------------------------------------------------------------
# Shared cascade helpers
# ---------------------------------------------------------------------------
def _release_room_and_provider(visit):
    """Release the occupied room into CLEANING and free provider capacity."""
    room = db.exam_rooms.get(visit.get("exam_room_id"))
    if room is not None and room["status"] == "OCCUPIED" and room["current_visit_id"] == visit["id"]:
        room["status"] = "CLEANING"
        room["current_visit_id"] = None
        touch(room)
    provider = db.providers.get(visit.get("provider_id"))
    if provider is not None:
        touch(provider)
    qe = db.queue_entries.get(visit.get("queue_entry_id"))
    if qe is not None:
        clinic = db.clinics.get(qe["clinic_id"])
        if clinic is not None:
            compute.recompute_clinic(clinic)


def _has_discharge_instruction(visit_id):
    return any(d["visit_id"] == visit_id for d in db.discharge_instructions.values())
