"""Standalone issuance endpoints (PRD §3.5)."""

from db import store, touch
from errors import ERR_NOT_FOUND, ERR_INVALID_EVENT_STATE, ERR_INVALID_STATE, raise_err
from middleware import authenticate, require_role, forbid
from response import success_object, get_body  # noqa: F401  (get_body: optional reason)
from serialize import issuance_json
from . import make_blueprint

bp = make_blueprint("issuances")


@bp.route("/issuances/<issuance_id>/void", methods=["POST"])
def void_issuance(issuance_id):
    uid, role = authenticate()
    require_role(role, ["AgencyCoordinator", "PrivacyOfficer"])
    i = store.issuances.get(issuance_id)
    if i is None:
        raise_err(ERR_NOT_FOUND, "Issuance not found.")
    ev = store.distribution_events.get(i["event_id"])
    if role == "AgencyCoordinator" and (ev is None or ev["host_agency_id"] != uid):
        forbid()
    if i["status"] != "RECORDED":
        raise_err(ERR_INVALID_STATE, "Only a RECORDED issuance can be voided.")
    if ev is None or ev["status"] not in ("OPEN", "LOCKED"):
        raise_err(ERR_INVALID_EVENT_STATE,
                  "Issuances may be voided only while the event is OPEN or LOCKED.")
    get_body()  # optional reason; accepted and not persisted
    i["status"] = "VOIDED"
    touch(i)
    return success_object(issuance_json(i))
