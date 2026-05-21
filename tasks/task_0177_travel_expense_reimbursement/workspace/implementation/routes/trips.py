"""Trip endpoints and lifecycle transitions."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.errors import (
    err_cross_entity_state,
    err_invalid_state,
    err_not_found,
    err_per_diem_unavailable,
    err_reference_not_found,
    err_segregation_of_duties,
    err_stale_version,
    err_validation,
)
from core.pagination import paginate, parse_pagination
from core.serializers import serialize_trip
from core.store import store
from core.utils import lock, parse_iso
from services import calculations
from services.clock_service import get_now
from services.per_diem_service import resolve_per_diem
from services.timestamps import stamp_create, stamp_update


bp = Blueprint("trips", __name__)


_VALID_STATUSES = {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "CHANGES_REQUESTED", "COMPLETED", "CANCELLED"}


def _validate_create_payload(body):
    required = ["traveler_id", "purpose", "origin_city", "origin_state",
                "destination_city", "destination_state", "start_date", "end_date"]
    for f in required:
        if body.get(f) is None or body.get(f) == "":
            raise err_validation(f"{f} is required.")
    if not isinstance(body["purpose"], str) or not (1 <= len(body["purpose"]) <= 500):
        raise err_validation("purpose must be 1-500 chars.")
    try:
        start = parse_iso(body["start_date"])
        end = parse_iso(body["end_date"])
    except ValueError as exc:
        raise err_validation(str(exc))
    if end is None or start is None or end < start:
        raise err_validation("end_date must be >= start_date.")


def _ensure_traveler(traveler_id):
    emp = store.employees.get(traveler_id)
    if emp is None:
        raise err_reference_not_found(f"traveler_id {traveler_id} not found.")
    if emp.get("role") != "TRAVELER":
        raise err_reference_not_found(f"Employee {traveler_id} is not a TRAVELER.")
    return emp


@bp.post("/trips")
@require_roles("TRAVELER")
def create_trip():
    body = get_json_body()
    _validate_create_payload(body)

    _ensure_traveler(body["traveler_id"])

    # A traveler can only create a trip for themselves
    if body["traveler_id"] != current_user_id():
        raise err_segregation_of_duties("Cannot create a trip on behalf of another employee.")

    with lock():
        rec = {
            "traveler_id": body["traveler_id"],
            "purpose": body["purpose"],
            "origin_city": body["origin_city"],
            "origin_state": body["origin_state"],
            "destination_city": body["destination_city"],
            "destination_state": body["destination_state"],
            "start_date": body["start_date"],
            "end_date": body["end_date"],
            "status": "DRAFT",
            "estimated_budget_cents": 0,
            "pinned_per_diem_rate_id": None,
            "approved_at": None,
        }
        stamp_create(rec)
        store.trips[rec["id"]] = rec

    return success_response(serialize_trip(rec), status=201)


@bp.get("/trips")
@require_roles("TRAVELER", "MANAGER", "FINANCE_REVIEWER", "ADMIN")
def list_trips():
    traveler_id = request.args.get("traveler_id")
    status_f = request.args.get("status")
    sd_from = request.args.get("start_date_from")
    sd_to = request.args.get("start_date_to")

    sd_from_dt = parse_iso(sd_from) if sd_from else None
    sd_to_dt = parse_iso(sd_to) if sd_to else None

    items = list(store.trips.values())
    if traveler_id:
        items = [t for t in items if t["traveler_id"] == traveler_id]
    if status_f:
        items = [t for t in items if t["status"] == status_f]
    if sd_from_dt:
        items = [t for t in items if parse_iso(t["start_date"]) >= sd_from_dt]
    if sd_to_dt:
        items = [t for t in items if parse_iso(t["start_date"]) <= sd_to_dt]

    items.sort(key=lambda t: t["created_at"])
    limit, offset = parse_pagination()
    page, meta = paginate(items, limit, offset)
    return success_response(
        [serialize_trip(t) for t in page],
        response_type="array",
        pagination=meta,
    )


@bp.get("/trips/<tid>")
@require_roles("TRAVELER", "MANAGER", "FINANCE_REVIEWER", "ADMIN")
def get_trip(tid):
    trip = store.trips.get(tid)
    if trip is None:
        raise err_not_found(f"Trip {tid} not found.")
    return success_response(serialize_trip(trip))


@bp.patch("/trips/<tid>")
@require_roles("TRAVELER")
def patch_trip(tid):
    trip = store.trips.get(tid)
    if trip is None:
        raise err_not_found(f"Trip {tid} not found.")
    if trip["status"] not in {"DRAFT", "CHANGES_REQUESTED"}:
        raise err_invalid_state(f"Cannot edit trip in status {trip['status']}.")
    if trip["traveler_id"] != current_user_id():
        raise err_segregation_of_duties("Only the owning traveler may edit this trip.")

    body = get_json_body()

    # OCC version check
    if "version" in body and body["version"] is not None:
        if body["version"] != trip["version"]:
            raise err_stale_version(
                f"version mismatch: client={body['version']}, server={trip['version']}."
            )

    with lock():
        for field in ("purpose", "origin_city", "origin_state",
                      "destination_city", "destination_state",
                      "start_date", "end_date"):
            if field in body and body[field] is not None:
                trip[field] = body[field]
        # Re-validate dates
        try:
            s = parse_iso(trip["start_date"])
            e = parse_iso(trip["end_date"])
        except ValueError as exc:
            raise err_validation(str(exc))
        if e < s:
            raise err_validation("end_date must be >= start_date.")

        # If CHANGES_REQUESTED -> DRAFT, clear computed fields
        if trip["status"] == "CHANGES_REQUESTED":
            trip["status"] = "DRAFT"
            trip["estimated_budget_cents"] = 0
            trip["pinned_per_diem_rate_id"] = None

        stamp_update(trip)

    return success_response(serialize_trip(trip))


@bp.post("/trips/<tid>/submit")
@require_roles("TRAVELER")
def submit_trip(tid):
    trip = store.trips.get(tid)
    if trip is None:
        raise err_not_found(f"Trip {tid} not found.")
    if trip["status"] != "DRAFT":
        raise err_invalid_state(f"Trip status is {trip['status']}, not DRAFT.")
    if trip["traveler_id"] != current_user_id():
        raise err_segregation_of_duties("Only the owning traveler may submit this trip.")

    # Per-diem must cover start_date
    start = parse_iso(trip["start_date"])
    rate = resolve_per_diem(trip["destination_city"], trip["destination_state"], start)
    if rate is None:
        raise err_per_diem_unavailable(
            f"No PerDiemRate covers {trip['destination_city']}, {trip['destination_state']} on {trip['start_date']}."
        )

    end = parse_iso(trip["end_date"])
    if end < start:
        raise err_validation("end_date must be >= start_date.")

    with lock():
        budget, used_rate = calculations.compute_trip_budget(trip, variant="provisional")
        trip["estimated_budget_cents"] = budget
        # Note: do NOT pin the rate id at submission — it is pinned at approval.
        trip["status"] = "SUBMITTED"
        stamp_update(trip)

    return success_response(serialize_trip(trip))


def _ensure_manager_of(trip):
    """Acting user must be the traveler's manager."""
    traveler = store.employees.get(trip["traveler_id"])
    if traveler is None:
        raise err_reference_not_found("Trip's traveler no longer exists.")
    if current_user_id() != traveler.get("manager_id"):
        raise err_segregation_of_duties("Acting user is not the traveler's manager.")


@bp.post("/trips/<tid>/approve")
@require_roles("MANAGER")
def approve_trip(tid):
    trip = store.trips.get(tid)
    if trip is None:
        raise err_not_found(f"Trip {tid} not found.")
    if trip["status"] != "SUBMITTED":
        raise err_invalid_state(f"Trip status is {trip['status']}, not SUBMITTED.")
    _ensure_manager_of(trip)
    if (trip.get("estimated_budget_cents") or 0) <= 0:
        raise err_invalid_state("estimated_budget_cents must be > 0.")

    start = parse_iso(trip["start_date"])
    rate = resolve_per_diem(trip["destination_city"], trip["destination_state"], start)
    if rate is None:
        raise err_per_diem_unavailable(
            f"No PerDiemRate covers {trip['destination_city']}, {trip['destination_state']} on {trip['start_date']}."
        )

    with lock():
        from services.clock_service import get_now_iso
        trip["pinned_per_diem_rate_id"] = rate["id"]
        trip["status"] = "APPROVED"
        trip["approved_at"] = get_now_iso()
        stamp_update(trip)

    return success_response(serialize_trip(trip))


@bp.post("/trips/<tid>/reject")
@require_roles("MANAGER")
def reject_trip(tid):
    trip = store.trips.get(tid)
    if trip is None:
        raise err_not_found(f"Trip {tid} not found.")
    if trip["status"] != "SUBMITTED":
        raise err_invalid_state(f"Trip status is {trip['status']}, not SUBMITTED.")
    _ensure_manager_of(trip)

    with lock():
        trip["status"] = "REJECTED"
        stamp_update(trip)
        # Cascade hop 1: pending VirtualCards (REQUESTED) -> CLOSED
        for card in store.cards_for_trip(tid):
            if card["status"] == "REQUESTED":
                card["status"] = "CLOSED"
                stamp_update(card)
        # Cascade hop 2: any ExpenseReport on this trip -> REJECTED
        for report in store.reports_for_trip(tid):
            if report["status"] != "REJECTED":
                report["status"] = "REJECTED"
                stamp_update(report)

    return success_response(serialize_trip(trip))


@bp.post("/trips/<tid>/request-changes")
@require_roles("MANAGER")
def request_changes_trip(tid):
    trip = store.trips.get(tid)
    if trip is None:
        raise err_not_found(f"Trip {tid} not found.")
    if trip["status"] != "SUBMITTED":
        raise err_invalid_state(f"Trip status is {trip['status']}, not SUBMITTED.")
    _ensure_manager_of(trip)

    with lock():
        trip["status"] = "CHANGES_REQUESTED"
        stamp_update(trip)

    return success_response(serialize_trip(trip))


@bp.post("/trips/<tid>/complete")
@require_roles("TRAVELER")
def complete_trip(tid):
    trip = store.trips.get(tid)
    if trip is None:
        raise err_not_found(f"Trip {tid} not found.")
    if trip["status"] != "APPROVED":
        raise err_invalid_state(f"Trip status is {trip['status']}, not APPROVED.")
    if trip["traveler_id"] != current_user_id():
        raise err_segregation_of_duties("Only the owning traveler may complete this trip.")

    now = get_now()
    end = parse_iso(trip["end_date"])
    if now.date() < end.date():
        raise err_invalid_state(
            f"Cannot complete trip before end_date {trip['end_date']}."
        )

    with lock():
        trip["status"] = "COMPLETED"
        stamp_update(trip)
        # Cascade: ACTIVE cards -> LOCKED with locked_reason='trip_completed'
        for card in store.cards_for_trip(tid):
            if card["status"] == "ACTIVE":
                card["status"] = "LOCKED"
                card["locked_reason"] = "trip_completed"
                stamp_update(card)

    return success_response(serialize_trip(trip))


@bp.post("/trips/<tid>/cancel")
@require_roles("TRAVELER")
def cancel_trip(tid):
    trip = store.trips.get(tid)
    if trip is None:
        raise err_not_found(f"Trip {tid} not found.")
    if trip["status"] != "APPROVED":
        raise err_invalid_state(f"Trip status is {trip['status']}, not APPROVED.")
    if trip["traveler_id"] != current_user_id():
        raise err_segregation_of_duties("Only the owning traveler may cancel this trip.")

    # No ExpenseReport in non-DRAFT status
    for report in store.reports_for_trip(tid):
        if report["status"] != "DRAFT":
            raise err_invalid_state(
                f"ExpenseReport {report['id']} is in {report['status']}; cannot cancel trip."
            )

    with lock():
        trip["status"] = "CANCELLED"
        stamp_update(trip)
        # Cascade: REQUESTED/ISSUED/ACTIVE cards -> CLOSED
        for card in store.cards_for_trip(tid):
            if card["status"] in {"REQUESTED", "ISSUED", "ACTIVE"}:
                card["status"] = "CLOSED"
                stamp_update(card)

    return success_response(serialize_trip(trip))
