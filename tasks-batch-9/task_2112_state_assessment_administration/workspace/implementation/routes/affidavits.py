"""Test-security affidavits (PRD 3.1, 2.8)."""

from flask import Blueprint, request

import serialize
from db import create, db, now, ordered, touch
from derive import active_affidavit
from errors import api_error
from middleware import (
    ALL_ROLES,
    PROCTOR,
    body_reference,
    endpoint,
    json_body,
    require_scope,
    resolve,
)
from response import object_response, paginate
from validators import identifier_field, integer_field, string_field

bp = Blueprint("affidavits", __name__)

AFFIDAVIT_VERSION_PATTERN = r"[0-9]{4}\.[0-9]+"


@bp.post("/security-affidavits")
@endpoint(PROCTOR)
def sign_affidavit(actor):
    # Check 4 — a proctor may only attest on the proctor's own record.
    named_proctor = body_reference("proctor_id")
    if named_proctor is not None:
        require_scope(named_proctor == actor.user_id)

    body = json_body()
    proctor_id = identifier_field(body, "proctor_id")
    window_id = identifier_field(body, "window_id")
    affidavit_version = string_field(body, "affidavit_version", pattern=AFFIDAVIT_VERSION_PATTERN)
    expected_proctor_version = integer_field(body, "expected_proctor_version")

    proctor = resolve(db.proctors, proctor_id, "ERR_PROCTOR_NOT_FOUND")
    resolve(db.windows, window_id, "ERR_TEST_WINDOW_NOT_FOUND")

    # Check 7 — version pinning on the parent proctor.
    if expected_proctor_version != proctor["version"]:
        raise api_error("ERR_STALE_PROCTOR_VERSION")

    superseded = active_affidavit(proctor_id, window_id)

    affidavit = create(
        db.affidavits,
        {
            "proctor_id": proctor_id,
            "window_id": window_id,
            "affidavit_version": affidavit_version,
            "signed_at": now(),
            "signer_user_id": actor.user_id,
            "status": "ACTIVE",
            "revoked_reason": None,
        },
    )
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        touch(superseded)
    proctor["latest_affidavit_id"] = affidavit["id"]
    touch(proctor)
    return object_response(serialize.affidavit(affidavit), 201)


@bp.get("/security-affidavits/<security_affidavit_id>")
@endpoint(*ALL_ROLES)
def read_affidavit(actor, security_affidavit_id):
    affidavit = resolve(db.affidavits, security_affidavit_id, "ERR_SECURITY_AFFIDAVIT_NOT_FOUND")
    return object_response(serialize.affidavit(affidavit))


@bp.get("/security-affidavits")
@endpoint(*ALL_ROLES)
def list_affidavits(actor):
    proctor_id = request.args.get("proctor_id")
    window_id = request.args.get("window_id")
    status = request.args.get("status")
    items = [
        affidavit
        for affidavit in db.affidavits.values()
        if (proctor_id is None or affidavit["proctor_id"] == proctor_id)
        and (window_id is None or affidavit["window_id"] == window_id)
        and (status is None or affidavit["status"] == status)
    ]
    return paginate(ordered(items), serialize.affidavit)
