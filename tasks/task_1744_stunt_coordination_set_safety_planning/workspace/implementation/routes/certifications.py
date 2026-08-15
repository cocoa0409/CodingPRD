"""Certification: create (immutable record), revoke."""

from flask import Blueprint, request

from db import store
from domain import (
    get_performer,
    get_production,
    get_certification,
    gate_posture_setup_or_active,
    cert_valid,
    performer_has_valid_cert,
    serialize_certification,
    stamp_new,
    touch,
    HAZARD_CLASSES,
    CERT_LEVELS,
    default_sort_key,
)
from middleware import (
    auth,
    require_role,
    get_body,
    validate_payload,
    pagination_params,
    v_string,
    v_enum,
    v_datetime,
)
from response import ok, ok_list
from util import new_id

bp = Blueprint("certifications", __name__)

READ_ROLES = ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
              "DepartmentHead", "Performer", "EquipmentInspector"]


@bp.post("/api/certifications")
def create_certification():
    body = get_body()
    data = validate_payload(
        body,
        {
            "performer_id": (v_string, True, None),
            "discipline": (v_enum(HAZARD_CLASSES), True, None),
            "level": (v_enum(CERT_LEVELS), True, None),
            "issued_at": (v_datetime, True, None),
            "expires_at": (v_datetime, True, None),
        },
    )
    _, role = auth()
    require_role(role, ["StuntCoordinator"])
    performer = get_performer(data["performer_id"])
    prod = get_production(performer["production_id"])
    gate_posture_setup_or_active(prod)

    cert = stamp_new(
        {
            "id": new_id(),
            "performer_id": performer["id"],
            "discipline": data["discipline"],
            "level": data["level"],
            "issued_at": data["issued_at"],
            "expires_at": data["expires_at"],
            "revoked": False,
        }
    )
    store.certifications[cert["id"]] = cert

    # first valid certification lifts REGISTERED -> QUALIFIED
    if performer["status"] == "REGISTERED" and cert_valid(cert, store.now()):
        performer["status"] = "QUALIFIED"
        touch(performer)
    return ok(serialize_certification(cert), 201)


@bp.get("/api/certifications")
def list_certifications():
    _, role = auth()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    performer_id = request.args.get("performer_id")
    discipline = request.args.get("discipline")
    items = []
    for c in store.certifications.values():
        if performer_id is not None and c["performer_id"] != performer_id:
            continue
        if discipline is not None and c["discipline"] != discipline:
            continue
        items.append(c)
    items.sort(key=default_sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_certification(c) for c in page], total, limit, offset)


@bp.get("/api/certifications/<cid>")
def get_one_certification(cid):
    _, role = auth()
    require_role(role, READ_ROLES)
    cert = get_certification(cid)
    return ok(serialize_certification(cert), 200)


@bp.post("/api/certifications/<cid>/revoke")
def revoke_certification(cid):
    body = get_body()
    validate_payload(body, {"reason": (v_string, False, None)})
    _, role = auth()
    require_role(role, ["SafetyOfficer"])
    cert = get_certification(cid)
    performer = get_performer(cert["performer_id"])
    prod = get_production(performer["production_id"])
    gate_posture_setup_or_active(prod)

    cert["revoked"] = True
    # losing the last valid certification drops QUALIFIED -> REGISTERED
    if performer["status"] == "QUALIFIED" and not performer_has_valid_cert(
        performer["id"], store.now()
    ):
        performer["status"] = "REGISTERED"
        touch(performer)
    return ok(serialize_certification(cert), 200)
