"""SeniorLien endpoints + default event."""
from __future__ import annotations

from flask import Blueprint

from db import store
from errors import err_invalid_state, err_validation_failed
from middleware import require_auth
from response import success
from services.engine import (
    cascade_default_for_property,
    stamp_create,
    stamp_ledger,
    stamp_update,
)
from services.serializers import senior_lien_default_event_view, senior_lien_view

from routes._helpers import (
    enforce_borrower_owns_senior_lien,
    get_int,
    get_json,
    get_property_or_404,
    get_senior_lien_or_404,
    get_string,
)

bp = Blueprint("senior_liens", __name__)


@bp.post("/senior-liens")
@require_auth(["Originator", "PlatformAdmin"], endpoint_key="POST /senior-liens")
def create_senior_lien():
    body = get_json()
    property_id = get_string(body, "property_id", required=True)
    holder_name = get_string(body, "holder_name", required=True)
    principal_balance_cents = get_int(body, "principal_balance_cents", required=True)
    if not (1 <= len(holder_name) <= 200):
        raise err_validation_failed("holder_name must be 1..200 chars.")
    if principal_balance_cents < 0:
        raise err_validation_failed("principal_balance_cents must be >= 0.")

    with store.lock:
        get_property_or_404(property_id)
        s = {
            "property_id": property_id,
            "holder_name": holder_name,
            "principal_balance_cents": principal_balance_cents,
            "status": "CURRENT",
            "defaulted_at": None,
        }
        stamp_create(s)
        store.senior_liens[s["id"]] = s
    return success(senior_lien_view(s), 201)


@bp.get("/senior-liens/<sid>")
@require_auth(
    ["Originator", "Servicer", "Borrower", "PlatformAdmin"],
    endpoint_key="GET /senior-liens/{id}",
)
def get_senior_lien(sid: str):
    s = get_senior_lien_or_404(sid)
    enforce_borrower_owns_senior_lien(s)
    return success(senior_lien_view(s), 200)


@bp.post("/senior-liens/<sid>/default-events")
@require_auth(
    ["Servicer", "PlatformAdmin"],
    endpoint_key="POST /senior-liens/{id}/default-events",
)
def create_default_event(sid: str):
    with store.lock:
        s = get_senior_lien_or_404(sid)
        # Validation priority 18: senior lien must be CURRENT.
        if s["status"] != "CURRENT":
            raise err_invalid_state("SeniorLien is not CURRENT.")
        evt = {
            "senior_lien_id": sid,
            "recorded_at": store.now(),
        }
        stamp_ledger(evt)
        store.senior_lien_default_events[evt["id"]] = evt
        s["status"] = "DEFAULTED"
        s["defaulted_at"] = store.now()
        stamp_update(s)
        cascade_default_for_property(
            s["property_id"], source_event_id=evt["id"], trigger="SENIOR_LIEN_DEFAULT"
        )
    return success(senior_lien_default_event_view(evt), 201)
