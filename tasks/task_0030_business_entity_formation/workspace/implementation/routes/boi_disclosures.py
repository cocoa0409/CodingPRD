"""BOIDisclosure routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
import errors
import middleware
import response
from routes._helpers import parse_json_body_required, parse_pagination, sort_by_created
from services import access, calculations, core, serialize, validation

bp = Blueprint("boi_disclosures", __name__)


def _serialize_boi(b: dict) -> dict:
    """Include the derived boi_filing_deadline in GET-shaped responses."""
    be = db.business_entities.get(b["business_entity_id"])
    if be is None:
        deadline_iso = None
    else:
        formed_at = be.get("_formed_at_dt")
        created_clock = b.get("_creation_clock_dt")
        if formed_at is None or created_clock is None:
            deadline_iso = None
        else:
            deadline = calculations.boi_filing_deadline_utc(
                b["triggering_event"], formed_at, created_clock
            )
            deadline_iso = db.iso_format(deadline)
    return serialize.boi_disclosure(b, boi_filing_deadline_iso=deadline_iso)


@bp.route("/business-entities/<be_id>/boi-disclosures", methods=["POST"])
def create_boi_disclosure(be_id: str):
    role, user_id = middleware.require_auth(["Filer"])
    be = access.get_business_entity_or_404(be_id)
    access.require_filer_owns(role, user_id, be["id"])

    if be["status"] == "DISSOLVED":
        raise errors.err_entity_dissolved()

    body = parse_json_body_required()
    triggering_event = body.get("triggering_event")
    owners = body.get("beneficial_owners_json")
    if triggering_event is None:
        raise errors.err_invalid_request("Missing required field: triggering_event.")
    if owners is None:
        raise errors.err_invalid_request("Missing required field: beneficial_owners_json.")
    if triggering_event not in validation.TRIGGER_EVENTS:
        raise errors.err_invalid_request("triggering_event invalid.")

    validation.validate_beneficial_owners_json(owners)

    now = db.now_utc()
    b = {
        "business_entity_id": be["id"],
        "beneficial_owners_json": owners,
        "triggering_event": triggering_event,
        "status": "DRAFT",
        "submitted_at": None,
        "_creation_clock_dt": now,
    }
    core.stamp_create_common(b)
    db.boi_disclosures[b["id"]] = b
    return response.success_object(_serialize_boi(b), status=201)


@bp.route("/boi-disclosures/<b_id>/submit", methods=["POST"])
def submit_boi_disclosure(b_id: str):
    role, user_id = middleware.require_auth(["Filer"])
    b = access.get_boi_disclosure_or_404(b_id)
    access.require_filer_owns(role, user_id, b["business_entity_id"])
    be = db.business_entities.get(b["business_entity_id"])

    if b["status"] not in ("DRAFT", "AMENDED"):
        raise errors.err_invalid_state(f"BOI is in {b['status']}; cannot submit.")
    if be is not None and be["status"] == "DISSOLVED":
        raise errors.err_entity_dissolved()

    # Priority 50: re-check beneficial owners
    validation.validate_beneficial_owners_json(b["beneficial_owners_json"])

    # Cross-entity gate: exactly one ACTIVE RegisteredAgent
    if be is not None and core.active_registered_agent_count(be["id"]) != 1:
        raise errors.err_invalid_state("Submit requires exactly one ACTIVE RegisteredAgent.")

    # Priority 75: BOI deadline check
    now = db.now_utc()
    formed_at = be["_formed_at_dt"]
    deadline = calculations.boi_filing_deadline_utc(
        b["triggering_event"], formed_at, b["_creation_clock_dt"]
    )
    if now > deadline:
        raise errors.err_boi_past_deadline()

    b["status"] = "SUBMITTED"
    b["submitted_at"] = db.iso_format(now)
    b["_submitted_at_dt"] = now
    core.stamp_update_common(b)

    core.emit_event(be["id"], "BOI_SUBMITTED", {"boi_disclosure_id": b["id"]})

    # Recompute parent posture (BOI freshness affects it)
    if be is not None:
        core.recompute_be_posture(be)

    return response.success_object(_serialize_boi(b))


@bp.route("/boi-disclosures/<b_id>/amend", methods=["POST"])
def amend_boi_disclosure(b_id: str):
    role, user_id = middleware.require_auth(["Filer"])
    b = access.get_boi_disclosure_or_404(b_id)
    access.require_filer_owns(role, user_id, b["business_entity_id"])
    be = db.business_entities.get(b["business_entity_id"])

    if b["status"] != "SUBMITTED":
        raise errors.err_invalid_state(f"BOI is in {b['status']}; cannot amend.")
    if be is not None and be["status"] == "DISSOLVED":
        raise errors.err_entity_dissolved()

    body = parse_json_body_required()
    owners = body.get("beneficial_owners_json")
    if owners is None:
        raise errors.err_invalid_request("Missing required field: beneficial_owners_json.")
    validation.validate_beneficial_owners_json(owners)

    b["beneficial_owners_json"] = owners
    b["status"] = "AMENDED"
    core.stamp_update_common(b)
    return response.success_object(_serialize_boi(b))


@bp.route("/business-entities/<be_id>/boi-disclosures", methods=["GET"])
def list_boi_disclosures(be_id: str):
    middleware.require_auth(["Filer", "StateAdmin", "ComplianceOfficer"])
    be = access.get_business_entity_or_404(be_id)

    limit, offset = parse_pagination()
    st = request.args.get("status")
    items = core.children_boi_disclosures(be["id"])
    if st is not None:
        items = [x for x in items if x["status"] == st]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_array([_serialize_boi(x) for x in page],
                                  limit=limit, offset=offset, total_count=total)
