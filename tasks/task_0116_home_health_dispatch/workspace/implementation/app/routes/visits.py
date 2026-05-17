"""Visit routes — SCAFFOLD §1.5 / PRD §3.5.

Validation priority order on POST /episodes/{episodeId}/visits:
  3. existence (path: episode)
  6. ERR_EPISODE_NOT_OPEN
  8. ERR_CLINICIAN_LICENSE_EXPIRED (strict inequality: license > visit_date)
  9. ERR_CLINICIAN_NOT_AVAILABLE
 10. ERR_DISCIPLINE_MISMATCH
 12. ERR_VISIT_OUTSIDE_EPISODE
 13. ERR_VISIT_TIME_INVALID
 14. ERR_CLINICIAN_DOUBLE_BOOKED
 16. ERR_HHA_HOURS_EXCEEDED

NOTE: when the request payload contains a clinician_id, we must first resolve
the clinician (404 path-style ERR_NOT_FOUND) — but the SCAFFOLD validations list
treats this as an existence check via the path-parameter "all path-parameter
resources exist". Clinician is a body-payload reference, not a path param;
following the priority order strictly, we resolve it before running the
safety checks (since those preconditions read clinician fields).
"""
from decimal import Decimal

from flask import Blueprint, g, jsonify, request

from ..auth import require_auth
from ..clock import clock_today_iso, parse_date
from ..errors import APIError
from ..helpers import get_json_body, get_pagination_params, require_field
from ..responses import list_response, success_response
from ..services import calculations as calc
from ..services.serialize import visit_view
from ..store import get_lock, get_store, new_id, stamp_create, stamp_update


bp = Blueprint("visits", __name__)


VALID_VISIT_TYPES = {"SN", "PT", "OT", "SLP", "HHA"}
VALID_VISIT_STATUS = {"SCHEDULED", "COMPLETED", "CANCELLED"}


def _find_episode(episode_id: str) -> dict:
    e = get_store().episodes.get(episode_id)
    if e is None:
        raise APIError("ERR_NOT_FOUND", f"Episode {episode_id} not found")
    return e


def _find_visit(visit_id: str) -> dict:
    v = get_store().visits.get(visit_id)
    if v is None:
        raise APIError("ERR_NOT_FOUND", f"Visit {visit_id} not found")
    return v


def _intersect(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Half-open intervals [a_start, a_end) and [b_start, b_end) overlap?"""
    return a_start < b_end and b_start < a_end


@bp.post("/episodes/<episode_id>/visits")
@require_auth("IntakeCoordinator")
def schedule_visit(episode_id: str):
    body = get_json_body()

    with get_lock():
        store = get_store()
        episode = _find_episode(episode_id)

        # Priority 6: Episode must be OPEN.
        if episode["status"] != "OPEN":
            raise APIError("ERR_EPISODE_NOT_OPEN", "Episode is not in OPEN")

        # Parse + minimal shape validation of body fields needed for downstream checks.
        clinician_id = require_field(body, "clinician_id")
        visit_type = require_field(body, "visit_type")
        if visit_type not in VALID_VISIT_TYPES:
            raise APIError(
                "ERR_VALIDATION",
                f"visit_type must be one of {sorted(VALID_VISIT_TYPES)}",
            )
        visit_date = require_field(body, "visit_date")
        parse_date(visit_date)
        start_minute = require_field(body, "start_minute")
        end_minute = require_field(body, "end_minute")
        if not isinstance(start_minute, int) or isinstance(start_minute, bool):
            raise APIError("ERR_VALIDATION", "start_minute must be an integer")
        if not isinstance(end_minute, int) or isinstance(end_minute, bool):
            raise APIError("ERR_VALIDATION", "end_minute must be an integer")

        # Resolve the clinician for downstream priority-ordered checks.
        clinician = store.clinicians.get(clinician_id)
        if clinician is None:
            raise APIError("ERR_NOT_FOUND", f"Clinician {clinician_id} not found")

        # Priority 8: license expiration. STRICT inequality — license must be
        # strictly greater than visit_date.
        if not (parse_date(clinician["license_expiration_date"]) > parse_date(visit_date)):
            raise APIError(
                "ERR_CLINICIAN_LICENSE_EXPIRED",
                "Clinician license is expired on visit date",
            )

        # Priority 9: clinician AVAILABLE.
        if clinician["status"] != "AVAILABLE":
            raise APIError(
                "ERR_CLINICIAN_NOT_AVAILABLE",
                "Clinician is not AVAILABLE",
            )

        # Priority 10: discipline matches visit_type.
        if clinician["discipline"] != visit_type:
            raise APIError(
                "ERR_DISCIPLINE_MISMATCH",
                "Clinician discipline does not match visit_type",
            )

        # Priority 12: visit_date within episode window.
        if not (
            parse_date(episode["start_date"]) <= parse_date(visit_date) <= parse_date(episode["end_date"])
        ):
            raise APIError(
                "ERR_VISIT_OUTSIDE_EPISODE",
                "visit_date outside the episode window",
            )

        # Priority 13: time-window well-formedness.
        if not (0 <= start_minute <= 1439 and 0 <= end_minute <= 1439 and end_minute > start_minute):
            raise APIError("ERR_VISIT_TIME_INVALID", "Invalid visit minute window")

        # Priority 14: clinician double-booking on this date.
        for other in store.visits.values():
            if (
                other["clinician_id"] == clinician_id
                and other["visit_date"] == visit_date
                and other["status"] != "CANCELLED"
                and _intersect(
                    start_minute, end_minute, other["start_minute"], other["end_minute"]
                )
            ):
                raise APIError(
                    "ERR_CLINICIAN_DOUBLE_BOOKED",
                    "Clinician already booked in overlapping window",
                )

        # Priority 16: HHA hours cap.
        # Compute hha_hours for this visit (0 for non-HHA).
        if visit_type == "HHA":
            new_hha_hours = calc.hha_hours_from_minutes(start_minute, end_minute)
        else:
            new_hha_hours = Decimal("0.00")

        if visit_type == "HHA":
            # Sum hha_hours across non-CANCELLED HHA visits on this episode.
            episode_visits = [
                v for v in store.visits.values() if v["episode_id"] == episode_id
            ]
            consumed = calc.consumed_hha_hours(episode_visits)
            oasis = store.oasis_assessments[episode["source_oasis_id"]]
            ordered = calc.to_decimal(oasis.get("hha_companion_hours_ordered", 0))
            if consumed + new_hha_hours > ordered:
                raise APIError(
                    "ERR_HHA_HOURS_EXCEEDED",
                    "Scheduling this HHA visit would exceed the OASIS-ordered cap",
                )

        record = {
            "id": new_id(),
            "episode_id": episode_id,
            "clinician_id": clinician_id,
            "visit_type": visit_type,
            "visit_date": visit_date,
            "start_minute": start_minute,
            "end_minute": end_minute,
            "hha_hours": new_hha_hours,
            "status": "SCHEDULED",
        }
        stamp_create(record)
        store.visits[record["id"]] = record

        body_out, status = success_response(visit_view(record), status=201)
    return jsonify(body_out), status


@bp.get("/episodes/<episode_id>/visits")
@require_auth("IntakeCoordinator", "FieldClinician", "BillingSpecialist")
def list_visits(episode_id: str):
    _find_episode(episode_id)
    limit, offset = get_pagination_params()
    status_filter = request.args.get("status")
    clinician_filter = request.args.get("clinician_id")
    if status_filter is not None and status_filter not in VALID_VISIT_STATUS:
        raise APIError(
            "ERR_VALIDATION",
            f"status must be one of {sorted(VALID_VISIT_STATUS)}",
        )

    items = [v for v in get_store().visits.values() if v["episode_id"] == episode_id]
    if status_filter is not None:
        items = [v for v in items if v["status"] == status_filter]
    if clinician_filter is not None:
        items = [v for v in items if v["clinician_id"] == clinician_filter]
    items.sort(key=lambda v: v["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    body, status = list_response([visit_view(v) for v in page], total, limit, offset)
    return jsonify(body), status


@bp.get("/visits/<visit_id>")
@require_auth("IntakeCoordinator", "FieldClinician", "BillingSpecialist")
def get_visit(visit_id: str):
    v = _find_visit(visit_id)
    body, status = success_response(visit_view(v))
    return jsonify(body), status


@bp.post("/visits/<visit_id>/complete")
@require_auth("FieldClinician")
def complete_visit(visit_id: str):
    with get_lock():
        v = _find_visit(visit_id)

        # Per SCAFFOLD validations: priority 6 (Episode OPEN) before 7 (Visit SCHEDULED).
        episode = get_store().episodes.get(v["episode_id"])
        if episode is not None and episode["status"] != "OPEN":
            raise APIError("ERR_EPISODE_NOT_OPEN", "Parent Episode is not in OPEN")

        if v["status"] != "SCHEDULED":
            raise APIError("ERR_VISIT_NOT_SCHEDULED", "Visit is not in SCHEDULED")

        # Ownership: X-User-ID must equal Visit.clinician_id.
        # NB: per PRD §2.1 — FieldClinician.X-User-ID is the Clinician.id; if
        # this does not match the visit's clinician_id we raise ERR_FORBIDDEN
        # (RBAC denies the action because the role's identity does not own the
        # resource).
        if g.user_id != v["clinician_id"]:
            raise APIError(
                "ERR_FORBIDDEN",
                "Acting clinician does not own this visit",
            )

        # Precondition: ClockState.current_date >= visit_date.
        if parse_date(clock_today_iso()) < parse_date(v["visit_date"]):
            raise APIError(
                "ERR_VISIT_NOT_SCHEDULED",
                "Cannot complete a visit whose visit_date is in the future",
            )

        v["status"] = "COMPLETED"
        stamp_update(v)
        body, status = success_response(visit_view(v))
    return jsonify(body), status


@bp.post("/visits/<visit_id>/cancel")
@require_auth("IntakeCoordinator")
def cancel_visit(visit_id: str):
    with get_lock():
        v = _find_visit(visit_id)

        # Priority 6: parent Episode must be OPEN.
        episode = get_store().episodes.get(v["episode_id"])
        if episode is not None and episode["status"] != "OPEN":
            raise APIError("ERR_EPISODE_NOT_OPEN", "Parent Episode is not in OPEN")

        if v["status"] != "SCHEDULED":
            raise APIError("ERR_VISIT_NOT_SCHEDULED", "Visit is not in SCHEDULED")

        v["status"] = "CANCELLED"
        stamp_update(v)
        body, status = success_response(visit_view(v))
    return jsonify(body), status
