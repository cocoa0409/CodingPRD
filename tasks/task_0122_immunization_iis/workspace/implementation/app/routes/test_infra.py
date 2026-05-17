"""Test-only endpoints: clock advance and VAERS acknowledgement webhook."""
from __future__ import annotations

from flask import Blueprint, jsonify

from .. import store
from ..auth import require_roles
from ..clock import advance_to, current_iso_timestamp, parse_iso
from ..errors import APIError
from ..helpers import (
    ensure_enum,
    parse_iso_or_400,
    parse_json_body,
    require_field,
)
from ..responses import build_envelope


bp = Blueprint("test_infra", __name__)


ACK_OUTCOMES = {"ACK", "REJECT"}


def _serialize_ae(ae: dict) -> dict:
    return {
        "id": ae["id"],
        "patient_id": ae["patient_id"],
        "dose_id": ae["dose_id"],
        "onset_at": ae["onset_at"],
        "symptom_codes": ae["symptom_codes"],
        "seriousness": ae["seriousness"],
        "clinical_review_status": ae["clinical_review_status"],
        "vaers_submission_status": ae["vaers_submission_status"],
        "vaers_submission_id": ae.get("vaers_submission_id"),
        "vaers_required": ae["vaers_required"],
        "created_at": ae["created_at"],
        "updated_at": ae["updated_at"],
        "version": ae["version"],
    }


@bp.post("/__test__/reset")
def test_reset():
    """Wipe every in-memory collection so each test starts clean.

    Implementation-internal endpoint that is NOT mentioned in the PRD.
    Tests rely on it via the autouse conftest fixture; if it were absent
    the in-memory dicts would accumulate state across tests in the same
    process and violate per-test isolation.
    """
    from ..clock import reset_clock
    store.reset_all()
    try:
        reset_clock()
    except Exception:
        pass
    return jsonify(build_envelope({}, "object")), 200


@bp.post("/_clock/advance")
@require_roles(["PublicHealthOfficer"])
def clock_advance():
    body = parse_json_body()
    target_raw = require_field(body, "to_timestamp")
    target_dt = parse_iso_or_400(target_raw, "to_timestamp")
    new_now = advance_to(target_dt)
    return jsonify(build_envelope({"now": current_iso_timestamp()}, "object")), 200


@bp.post("/_events/vaers-ack")
@require_roles(["PublicHealthOfficer"])
def vaers_ack():
    body = parse_json_body()
    ae_id = require_field(body, "adverse_event_id")
    outcome = ensure_enum(require_field(body, "outcome"), ACK_OUTCOMES, "outcome")
    ae = store.adverse_events.get(ae_id)
    if not ae:
        raise APIError("ERR_ADVERSE_EVENT_NOT_FOUND", f"AdverseEvent {ae_id} not found.")
    if ae["vaers_submission_status"] != "SUBMITTED":
        raise APIError("ERR_INVALID_STATE",
                       f"Cannot ack: vaers_submission_status is {ae['vaers_submission_status']}.")
    with store.lock:
        ae["vaers_submission_status"] = "ACK_RECEIVED" if outcome == "ACK" else "REJECTED"
        store.stamp_update(ae)
    return jsonify(build_envelope(_serialize_ae(ae), "object")), 200
