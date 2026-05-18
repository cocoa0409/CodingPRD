"""Property endpoints + insurance event."""
from __future__ import annotations

from flask import Blueprint

from db import store
from errors import err_invalid_state, err_not_found, err_validation_failed
from middleware import require_auth
from response import success
from services.engine import (
    cascade_default_for_property,
    stamp_create,
    stamp_ledger,
    stamp_update,
)
from services.serializers import insurance_event_view, property_view

from routes._helpers import (
    enforce_borrower_owns_property,
    get_borrower_or_404,
    get_enum,
    get_int,
    get_json,
    get_property_or_404,
    get_string,
)

bp = Blueprint("properties", __name__)

_OCCUPANCY_VALUES = {"PRIMARY", "SECONDARY", "INVESTMENT"}
_INSURANCE_EVENT_TYPES = {"LAPSE", "REINSTATE"}


@bp.post("/properties")
@require_auth(["Originator", "PlatformAdmin"], endpoint_key="POST /properties")
def create_property():
    body = get_json()
    borrower_id = get_string(body, "borrower_id", required=True)
    address = get_string(body, "address", required=True)
    appraised = get_int(body, "appraised_value_cents", required=True)
    occupancy = get_enum(body, "occupancy", _OCCUPANCY_VALUES, default="PRIMARY")

    if not (1 <= len(address) <= 300):
        raise err_validation_failed("address must be 1..300 chars.")
    if appraised < 100_000:
        raise err_validation_failed("appraised_value_cents must be >= 100000.")

    with store.lock:
        # Body-level foreign-key existence (priority 7).
        get_borrower_or_404(borrower_id)
        p = {
            "borrower_id": borrower_id,
            "address": address,
            "appraised_value_cents": appraised,
            "occupancy": occupancy,
            "insurance_status": "ACTIVE",
            "insurance_lapsed_at": None,
        }
        stamp_create(p)
        store.properties[p["id"]] = p
    return success(property_view(p), 201)


@bp.get("/properties/<pid>")
@require_auth(
    ["Originator", "Servicer", "Borrower", "PlatformAdmin"],
    endpoint_key="GET /properties/{id}",
)
def get_property(pid: str):
    p = get_property_or_404(pid)
    enforce_borrower_owns_property(p)
    return success(property_view(p), 200)


@bp.post("/properties/<pid>/insurance-events")
@require_auth(
    ["Servicer", "PlatformAdmin"],
    endpoint_key="POST /properties/{id}/insurance-events",
)
def create_insurance_event(pid: str):
    body = get_json()
    event_type = get_enum(body, "event_type", _INSURANCE_EVENT_TYPES, required=True)

    with store.lock:
        p = get_property_or_404(pid)
        # Validation priority 16: state preconditions.
        if event_type == "LAPSE" and p["insurance_status"] != "ACTIVE":
            raise err_invalid_state("LAPSE requires insurance_status==ACTIVE.")
        if event_type == "REINSTATE" and p["insurance_status"] != "LAPSED":
            raise err_invalid_state("REINSTATE requires insurance_status==LAPSED.")

        evt = {
            "property_id": pid,
            "event_type": event_type,
            "recorded_at": store.now(),
        }
        stamp_ledger(evt)
        store.insurance_events[evt["id"]] = evt

        if event_type == "LAPSE":
            p["insurance_status"] = "LAPSED"
            p["insurance_lapsed_at"] = store.now()
            stamp_update(p)
            cascade_default_for_property(
                pid, source_event_id=evt["id"], trigger="INSURANCE_LAPSE"
            )
        else:  # REINSTATE
            p["insurance_status"] = "ACTIVE"
            p["insurance_lapsed_at"] = None
            stamp_update(p)
            # PRD §2.8: REINSTATE does NOT auto-reactivate HELOCs.

    return success(insurance_event_view(evt), 201)
