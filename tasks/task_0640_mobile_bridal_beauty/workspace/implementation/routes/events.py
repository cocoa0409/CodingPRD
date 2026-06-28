"""Bridal events, faces, quoting/revision, completion, cancellation (PRD §3.2-3.4, §3.15-3.16)."""
from flask import Blueprint, request

import errors
from db import store, LOCK
from middleware import get_identity, require_role, parse_pagination, get_json_body
from response import object_response, array_response
from services.common import base_fields, touch, public, paginate
from services import calc
from services.domain import (
    recompute_party_size, pending_or_confirmed_faces, confirmed_faces,
    invoice_for_event, reconcile_balance,
)
from services.validate import (
    require_str, require_enum, require_number_min, require_datetime, optional_bool,
)

bp = Blueprint("events", __name__)

SERVICE_TYPES = {"HAIR", "MAKEUP", "BOTH"}
CANCEL_REASONS = {"CLIENT_CHOICE", "WEATHER", "ARTIST_UNAVAILABLE"}


def serialize_event(e):
    return {
        "id": e["id"],
        "client_id": e["client_id"],
        "event_date_utc": e["event_date_utc"],
        "ready_by_utc": e["ready_by_utc"],
        "venue_distance_km": e["venue_distance_km"],
        "party_size": e["party_size"],
        "status": e["status"],
        "quote_revision": e["quote_revision"],
        "estimated_total_cents": e["estimated_total_cents"],
        "trial_required": e["trial_required"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_face(f):
    return {
        "id": f["id"],
        "event_id": f["event_id"],
        "person_label": f["person_label"],
        "service_type": f["service_type"],
        "is_bride": f["is_bride"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def serialize_cancellation(c):
    return {
        "id": c["id"],
        "event_id": c["event_id"],
        "reason": c["reason"],
        "hours_before_event": c["hours_before_event"],
        "refund_tier": c["refund_tier"],
        "deposit_refund_cents": c["deposit_refund_cents"],
        "balance_relief_cents": c["balance_relief_cents"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def _require_event(event_id):
    e = store.events.get(event_id)
    if e is None:
        raise errors.not_found()
    return e


def _check_event_owner(event, user_id):
    """Client ownership: X-User-ID == event.client_id (PRD §2.4)."""
    if user_id != event["client_id"]:
        raise errors.not_event_owner()


# ---------------------------------------------------------------------------
# Event CRUD
# ---------------------------------------------------------------------------
@bp.route("/bridal-beauty/events", methods=["POST"])
def create_event():
    user_id, role = get_identity()
    require_role(role, {"Client", "Coordinator"})
    body = get_json_body()

    client_id = require_str(body, "client_id")
    event_date = require_datetime(body, "event_date_utc")
    ready_by = require_datetime(body, "ready_by_utc")
    distance = require_number_min(body, "venue_distance_km", 0)
    trial_required = optional_bool(body, "trial_required", True)

    with LOCK:
        # ready_by_utc must be > now and <= event_date_utc (SCAFFOLD entity constraint).
        if not (ready_by > store.clock_now and ready_by <= event_date):
            raise errors.invalid_request(
                "ready_by_utc must be after now and no later than event_date_utc")
        rec = base_fields()
        rec.update({
            "client_id": client_id,
            "event_date_utc": body["event_date_utc"],
            "ready_by_utc": body["ready_by_utc"],
            "_event_date_dt": event_date,
            "_ready_by_dt": ready_by,
            "venue_distance_km": distance,
            "party_size": 0,
            "status": "DRAFT",
            "quote_revision": 0,
            "estimated_total_cents": 0,
            "trial_required": trial_required,
        })
        store.events[rec["id"]] = rec
        return object_response(serialize_event(rec), 201)


@bp.route("/bridal-beauty/events/<event_id>", methods=["GET"])
def get_event(event_id):
    user_id, role = get_identity()
    require_role(role, {"Client", "Coordinator", "Artist"})
    e = _require_event(event_id)
    return object_response(serialize_event(e), 200)


@bp.route("/bridal-beauty/events", methods=["GET"])
def list_events():
    user_id, role = get_identity()
    require_role(role, {"Coordinator", "Client"})
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    client_f = request.args.get("client_id")

    items = list(store.events.values())
    if status_f is not None:
        items = [e for e in items if e["status"] == status_f]
    if client_f is not None:
        items = [e for e in items if e["client_id"] == client_f]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_event(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Faces
# ---------------------------------------------------------------------------
@bp.route("/bridal-beauty/events/<event_id>/faces", methods=["POST"])
def add_face(event_id):
    user_id, role = get_identity()
    require_role(role, {"Client", "Coordinator"})
    body = get_json_body()

    with LOCK:
        e = _require_event(event_id)
        person_label = require_str(body, "person_label")
        service_type = require_enum(body, "service_type", SERVICE_TYPES)
        is_bride = optional_bool(body, "is_bride", False)
        rec = base_fields()
        rec.update({
            "event_id": event_id,
            "person_label": person_label,
            "service_type": service_type,
            "is_bride": is_bride,
            "status": "PENDING",
        })
        store.faces[rec["id"]] = rec
        recompute_party_size(e)
        touch(e)
        return object_response(serialize_face(rec), 201)


@bp.route("/bridal-beauty/faces/<face_id>/confirm", methods=["POST"])
def confirm_face(face_id):
    user_id, role = get_identity()
    require_role(role, {"Client", "Coordinator"})
    with LOCK:
        f = store.faces.get(face_id)
        if f is None:
            raise errors.not_found()
        if f["status"] != "PENDING":
            raise errors.invalid_state("Face is not PENDING")
        f["status"] = "CONFIRMED"
        touch(f)
        e = store.events.get(f["event_id"])
        if e is not None:
            recompute_party_size(e)
            touch(e)
        return object_response(serialize_face(f), 200)


@bp.route("/bridal-beauty/faces/<face_id>/remove", methods=["POST"])
def remove_face(face_id):
    user_id, role = get_identity()
    require_role(role, {"Client", "Coordinator"})
    with LOCK:
        f = store.faces.get(face_id)
        if f is None:
            raise errors.not_found()
        if f["status"] not in ("PENDING", "CONFIRMED"):
            raise errors.invalid_state("Face cannot be removed from its current state")
        f["status"] = "REMOVED"
        touch(f)
        e = store.events.get(f["event_id"])
        if e is not None:
            recompute_party_size(e)
            touch(e)
        return object_response(serialize_face(f), 200)


@bp.route("/bridal-beauty/events/<event_id>/faces", methods=["GET"])
def list_faces(event_id):
    user_id, role = get_identity()
    require_role(role, {"Client", "Coordinator", "Artist"})
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    _require_event(event_id)
    items = [f for f in store.faces.values() if f["event_id"] == event_id]
    if status_f is not None:
        items = [f for f in items if f["status"] == status_f]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_face(f) for f in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Quote / Revision
# ---------------------------------------------------------------------------
def _select_quote_artist():
    """Cheapest ACTIVE LEAD artist; tie-break created_at asc (PRD §3.4)."""
    candidates = [a for a in store.artists.values()
                  if a["status"] == "ACTIVE" and a["skill_tier"] == "LEAD"]
    if not candidates:
        raise errors.no_lead_artist()
    candidates.sort(key=lambda a: (
        a["hair_rate_per_face_cents"] + a["makeup_rate_per_face_cents"],
        a["_seq"],
    ))
    return candidates[0]


@bp.route("/bridal-beauty/events/<event_id>/quote", methods=["POST"])
def quote_event(event_id):
    user_id, role = get_identity()
    require_role(role, {"Coordinator"})
    with LOCK:
        e = _require_event(event_id)
        if e["status"] not in ("DRAFT", "REVISION_REQUESTED"):
            raise errors.invalid_state("Event cannot be quoted from its current state")
        # Preconditions (PRD §3.3): >= 1 PENDING/CONFIRMED face.
        faces = pending_or_confirmed_faces(event_id)
        if len(faces) < 1:
            raise errors.invalid_state("Event has no PENDING or CONFIRMED faces")
        # DRAFT->QUOTED additionally requires ready_by_utc > now.
        if e["status"] == "DRAFT" and not (e["_ready_by_dt"] > store.clock_now):
            raise errors.invalid_state("ready_by_utc deadline is not in the future")
        # Select quoting artist (raises ERR_NO_LEAD_ARTIST if none).
        artist = _select_quote_artist()
        total = calc.quote_total(faces, artist, e["venue_distance_km"])
        e["estimated_total_cents"] = total
        e["quote_revision"] += 1
        recompute_party_size(e)
        e["status"] = "QUOTED"
        touch(e)
        return object_response(serialize_event(e), 200)


@bp.route("/bridal-beauty/events/<event_id>/request-revision", methods=["POST"])
def request_revision(event_id):
    user_id, role = get_identity()
    require_role(role, {"Client"})
    with LOCK:
        e = _require_event(event_id)
        _check_event_owner(e, user_id)
        if e["status"] != "QUOTED":
            raise errors.invalid_state("Event is not QUOTED")
        # No SIGNED contract exists for this event (precondition).
        signed = any(c for c in store.contracts.values()
                     if c["event_id"] == event_id and c["status"] == "SIGNED")
        if signed:
            raise errors.invalid_state("A signed contract exists for this event")
        e["estimated_total_cents"] = 0
        e["status"] = "REVISION_REQUESTED"
        touch(e)
        return object_response(serialize_event(e), 200)


@bp.route("/bridal-beauty/events/<event_id>/complete", methods=["POST"])
def complete_event(event_id):
    user_id, role = get_identity()
    require_role(role, {"Coordinator"})
    with LOCK:
        e = _require_event(event_id)
        if e["status"] != "SCHEDULED":
            raise errors.invalid_state("Event is not SCHEDULED")
        assignments = [a for a in store.assignments.values() if a["event_id"] == event_id]
        if not assignments or any(a["status"] != "COMPLETED" for a in assignments):
            raise errors.invalid_state("Not every assignment is COMPLETED")
        inv = invoice_for_event(event_id)
        if inv is None or inv["balance_status"] != "PAID":
            raise errors.invalid_state("Invoice balance is not PAID")
        # Side effect: all CONFIRMED faces -> SERVICED.
        for f in confirmed_faces(event_id):
            f["status"] = "SERVICED"
            touch(f)
        e["status"] = "COMPLETED"
        touch(e)
        return object_response(serialize_event(e), 200)


# ---------------------------------------------------------------------------
# Cancellation (PRD §3.16) — cascade
# ---------------------------------------------------------------------------
@bp.route("/bridal-beauty/events/<event_id>/cancel", methods=["POST"])
def cancel_event(event_id):
    user_id, role = get_identity()
    require_role(role, {"Client"})
    body = get_json_body()
    with LOCK:
        e = _require_event(event_id)
        _check_event_owner(e, user_id)
        reason = require_enum(body, "reason", CANCEL_REASONS)
        status = e["status"]
        if status not in ("DRAFT", "QUOTED", "CONTRACTED", "SCHEDULED"):
            raise errors.invalid_state("Event cannot be cancelled from its current state")

        hours = calc.hours_before(e["_event_date_dt"], store.clock_now)

        rec = base_fields()
        rec.update({
            "event_id": event_id,
            "reason": reason,
            "hours_before_event": float(hours),
            "refund_tier": None,
            "deposit_refund_cents": 0,
            "balance_relief_cents": 0,
        })

        if status in ("DRAFT", "QUOTED"):
            # Clean: no money moved, no contract — FULL_REFUND, no cascade.
            rec["refund_tier"] = "FULL_REFUND"
        else:
            # CONTRACTED or SCHEDULED -> run cancellation settlement.
            tier = calc.resolve_refund_tier(reason, hours)
            rec["refund_tier"] = tier
            inv = invoice_for_event(event_id)
            deposit_refund = 0
            balance_relief = 0
            if inv is not None:
                # Reconcile balance first to reflect current outstanding.
                reconcile_balance(inv)
                outstanding = inv["balance_amount_cents"]
                deposit_paid = inv["deposit_status"] == "PAID"
                if tier == "FULL_REFUND":
                    deposit_refund = inv["deposit_amount_cents"] if deposit_paid else 0
                    balance_relief = outstanding
                else:  # DEPOSIT_FORFEIT or FULL_FORFEIT
                    deposit_refund = 0
                    balance_relief = outstanding

                # Drive the invoice axes (cascade hop 2).
                if deposit_paid:
                    if tier == "FULL_REFUND":
                        inv["deposit_status"] = "REFUNDED"
                    else:
                        inv["deposit_status"] = "FORFEITED"
                if outstanding > 0:
                    inv["_relief_written_off"] = inv.get("_relief_written_off", 0) + outstanding
                    inv["balance_status"] = "WRITTEN_OFF"
                    reconcile_balance(inv)
                touch(inv)
            rec["deposit_refund_cents"] = deposit_refund
            rec["balance_relief_cents"] = balance_relief

            # Void the signed contract (system consequence).
            for c in store.contracts.values():
                if c["event_id"] == event_id and c["status"] == "SIGNED":
                    c["status"] = "VOIDED"
                    touch(c)

            if status == "SCHEDULED":
                # Release SCHEDULED assignments (cascade hop 3).
                for a in store.assignments.values():
                    if a["event_id"] == event_id and a["status"] == "SCHEDULED":
                        a["status"] = "CANCELLED"
                        touch(a)

            # CONFIRMED + PENDING faces -> REMOVED.
            for f in store.faces.values():
                if f["event_id"] == event_id and f["status"] in ("CONFIRMED", "PENDING"):
                    f["status"] = "REMOVED"
                    touch(f)

        store.cancellations[rec["id"]] = rec
        e["status"] = "CANCELLED"
        touch(e)
        return object_response(serialize_cancellation(rec), 200)


@bp.route("/bridal-beauty/events/<event_id>/cancellation", methods=["GET"])
def list_cancellation(event_id):
    user_id, role = get_identity()
    require_role(role, {"Client", "Coordinator"})
    limit, offset = parse_pagination()
    _require_event(event_id)
    items = [c for c in store.cancellations.values() if c["event_id"] == event_id]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_cancellation(c) for c in page], limit, offset, total)
