"""Episode routes — SCAFFOLD §1.5 / PRD §3.4."""
from flask import Blueprint, jsonify, request

from ..auth import require_auth
from ..clock import clock_today_iso
from ..errors import APIError
from ..helpers import get_json_body, get_pagination_params, require_field
from ..responses import list_response, success_response
from ..services.episodes import close_episode, episode_can_close, open_episode_from_oasis
from ..services.serialize import claim_view, episode_view
from ..store import get_lock, get_store


bp = Blueprint("episodes", __name__)


VALID_STATUS_FILTERS = {"OPEN", "CLOSED", "EXPIRED"}


def _find_patient(patient_id: str) -> dict:
    p = get_store().patients.get(patient_id)
    if p is None:
        raise APIError("ERR_NOT_FOUND", f"Patient {patient_id} not found")
    return p


def _find_episode(episode_id: str) -> dict:
    e = get_store().episodes.get(episode_id)
    if e is None:
        raise APIError("ERR_NOT_FOUND", f"Episode {episode_id} not found")
    return e


@bp.post("/patients/<patient_id>/episodes")
@require_auth("IntakeCoordinator")
def open_episode(patient_id: str):
    patient = _find_patient(patient_id)
    body = get_json_body()
    source_oasis_id = require_field(body, "source_oasis_id")

    with get_lock():
        store = get_store()
        oasis = store.oasis_assessments.get(source_oasis_id)
        if oasis is None or oasis["patient_id"] != patient_id:
            raise APIError(
                "ERR_NOT_FOUND",
                f"OASIS {source_oasis_id} not found for patient {patient_id}",
            )

        # State precondition: OASIS must be LOCKED.
        if oasis["status"] != "LOCKED":
            raise APIError(
                "ERR_OASIS_NOT_LOCKED",
                "Source OASIS is not in LOCKED status",
            )

        # OCC / business referential: OASIS not already used.
        for e in store.episodes.values():
            if e.get("source_oasis_id") == source_oasis_id:
                raise APIError(
                    "ERR_OASIS_ALREADY_USED",
                    "Source OASIS has already opened another Episode",
                )

        # No other OPEN episode for the patient.
        for e in store.episodes.values():
            if e["patient_id"] == patient_id and e["status"] == "OPEN":
                raise APIError(
                    "ERR_PATIENT_HAS_OPEN_EPISODE",
                    "Patient already has an OPEN Episode",
                )

        # Compute fields, persist Episode + paired PDGMClaim.
        # Use real wall-clock for audit timestamps, but tests are date-based.
        episode, claim = open_episode_from_oasis(patient, oasis, now=None)

        body_out, status = success_response(episode_view(episode), status=201)
    return jsonify(body_out), status


@bp.get("/episodes/<episode_id>")
@require_auth("IntakeCoordinator", "FieldClinician", "BillingSpecialist", "PlatformAdmin")
def get_episode(episode_id: str):
    e = _find_episode(episode_id)
    body, status = success_response(episode_view(e))
    return jsonify(body), status


@bp.get("/episodes")
@require_auth("BillingSpecialist", "IntakeCoordinator", "PlatformAdmin")
def list_episodes():
    limit, offset = get_pagination_params()
    patient_filter = request.args.get("patient_id")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in VALID_STATUS_FILTERS:
        raise APIError(
            "ERR_VALIDATION",
            f"status must be one of {sorted(VALID_STATUS_FILTERS)}",
        )

    items = list(get_store().episodes.values())
    if patient_filter is not None:
        items = [e for e in items if e["patient_id"] == patient_filter]
    if status_filter is not None:
        items = [e for e in items if e["status"] == status_filter]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    body, status = list_response([episode_view(e) for e in page], total, limit, offset)
    return jsonify(body), status


@bp.post("/episodes/<episode_id>/close")
@require_auth("BillingSpecialist")
def close_episode_route(episode_id: str):
    with get_lock():
        e = _find_episode(episode_id)
        if e["status"] != "OPEN":
            raise APIError("ERR_EPISODE_NOT_OPEN", "Episode is not in OPEN")
        episode_can_close(e, clock_today_iso())
        close_episode(e, now=None)
        body, status = success_response(episode_view(e))
    return jsonify(body), status


@bp.get("/episodes/<episode_id>/claim")
@require_auth("BillingSpecialist", "IntakeCoordinator")
def get_episode_claim(episode_id: str):
    # left-to-right: episode first.
    _find_episode(episode_id)
    store = get_store()
    for c in store.pdgm_claims.values():
        if c["episode_id"] == episode_id:
            body, status = success_response(claim_view(c))
            return jsonify(body), status
    raise APIError("ERR_NOT_FOUND", f"No claim for episode {episode_id}")
