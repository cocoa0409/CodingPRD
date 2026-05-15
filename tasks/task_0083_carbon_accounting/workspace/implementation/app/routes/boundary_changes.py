"""BoundaryChange endpoints (immutable append-only log)."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..errors import api_error
from ..response import list_envelope, success_envelope
from ..services.boundary import resolve_org_boundary
from ..store import store
from ..utils import (
    get_json_body,
    page_slice,
    parse_iso_datetime,
    parse_pagination,
    require_enum,
    require_str,
)
from ._helpers import get_facility_or_404, get_org_or_404


boundary_changes_bp = Blueprint("boundary_changes", __name__)


CHANGE_TYPES = {"ADD_FACILITY", "REMOVE_FACILITY", "APPROACH_SWITCH", "OWNERSHIP_ADJUSTMENT"}
APPROACHES = {"EQUITY_SHARE", "FINANCIAL_CONTROL", "OPERATIONAL_CONTROL"}


@boundary_changes_bp.route("/organizations/<org_id>/boundary-changes", methods=["POST"])
@require_auth(["PlatformAdmin"])
def create_boundary_change(org_id):
    get_org_or_404(org_id)
    body = get_json_body()
    change_type = require_enum(body, "change_type", CHANGE_TYPES)

    facility_id = body.get("facility_id")
    if change_type == "APPROACH_SWITCH":
        if facility_id is not None:
            raise api_error("ERR_VALIDATION_FAILED", "facility_id must be null on APPROACH_SWITCH")
    else:
        if not isinstance(facility_id, str) or not facility_id:
            raise api_error("ERR_VALIDATION_FAILED", "facility_id required for non-APPROACH_SWITCH")
        # Existence + cross-org check
        f = store.facilities.get(facility_id)
        if not f:
            raise api_error("ERR_NOT_FOUND", f"Facility {facility_id} not found")
        if f.get("organization_id") != org_id:
            raise api_error("ERR_CROSS_ORG_REFERENCE", "facility_id belongs to a different organization")

    from_approach = body.get("from_approach")
    to_approach = body.get("to_approach")
    if change_type == "APPROACH_SWITCH":
        if from_approach not in APPROACHES or to_approach not in APPROACHES:
            raise api_error("ERR_VALIDATION_FAILED", "from_approach/to_approach required on APPROACH_SWITCH")
    else:
        if from_approach is not None or to_approach is not None:
            raise api_error("ERR_VALIDATION_FAILED", "from_approach/to_approach only on APPROACH_SWITCH")

    eff = parse_iso_datetime(body.get("effective_date"))
    rationale = require_str(body, "rationale", min_len=5, max_len=1000)

    # Effective date strict monotonicity
    prior = [bc for bc in store.boundary_changes.values() if bc.get("organization_id") == org_id]
    prior.sort(key=lambda b: b.get("effective_date", ""))
    previous_change_id = None
    if prior:
        last = prior[-1]
        last_eff = parse_iso_datetime(last["effective_date"])
        if not (eff > last_eff):
            raise api_error(
                "ERR_BOUNDARY_CHANGE_ORDER",
                "effective_date must be strictly greater than previous boundary change",
            )
        previous_change_id = last["id"]

    actor_user_id = g.user_id
    actor_role = g.user_role

    # If APPROACH_SWITCH applied, also update organization's consolidation_approach
    payload = {
        "organization_id": org_id,
        "previous_change_id": previous_change_id,
        "change_type": change_type,
        "facility_id": facility_id,
        "from_approach": from_approach,
        "to_approach": to_approach,
        "effective_date": body.get("effective_date"),
        "rationale": rationale,
        "recorded_by_user_id": actor_user_id,
    }

    with store.lock:
        store.stamp_event(payload)
        store.boundary_changes[payload["id"]] = payload
        # Side effects:
        if change_type == "APPROACH_SWITCH":
            org = store.organizations[org_id]
            org["consolidation_approach"] = to_approach
            org["updated_at"] = payload["created_at"]
            org["version"] = org.get("version", 0) + 1
        elif change_type == "REMOVE_FACILITY":
            f = store.facilities[facility_id]
            f["status"] = "RETIRED"
            f["updated_at"] = payload["created_at"]
            f["version"] = f.get("version", 0) + 1
        resolve_org_boundary(org_id)
        store.append_audit(
            organization_id=org_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            event_type="BOUNDARY_CHANGE",
            target_entity="BoundaryChange",
            target_id=payload["id"],
            payload_json={"change_type": change_type, "facility_id": facility_id},
        )

    return success_envelope(payload, status=201)


@boundary_changes_bp.route("/organizations/<org_id>/boundary-changes", methods=["GET"])
@require_auth(["PlatformAdmin", "DataSteward", "Verifier", "Discloser"])
def list_boundary_changes(org_id):
    get_org_or_404(org_id)
    limit, offset = parse_pagination()
    items = [bc for bc in store.boundary_changes.values() if bc.get("organization_id") == org_id]
    items.sort(key=lambda x: (x.get("created_at", ""), x.get("id", "")))
    page, total = page_slice(items, limit, offset)
    return list_envelope(page, total, limit, offset)
