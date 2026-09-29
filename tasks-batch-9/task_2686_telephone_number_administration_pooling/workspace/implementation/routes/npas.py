"""Area codes: creation, listings and the manual jeopardy declaration (PRD 3.2)."""

from flask import Blueprint

from db import base_record, by_created, db
from errors import fail
from middleware import (
    ROLE_ADMIN,
    ROLE_APPROVER,
    ROLE_CARRIER,
    ROLE_COMMENTER,
    ROLE_PORTING,
    body,
    opt_enum,
    opt_str,
    req_str,
    require_roles,
)
from response import object_response, paginate
from routes.common import NPA_PATTERN, STATE_PATTERN, field, filter_rows
from services import constants as C
from services import core, serialize

bp = Blueprint("npas", __name__)

READERS = (ROLE_ADMIN, ROLE_APPROVER, ROLE_CARRIER, ROLE_PORTING, ROLE_COMMENTER)
RC_READERS = (ROLE_ADMIN, ROLE_APPROVER, ROLE_CARRIER, ROLE_PORTING)


def new_npa(npa_code, state_code, npa_type, relief_parent_npa_id=None):
    record = base_record(
        npa_code=npa_code,
        state_code=state_code,
        npa_type=npa_type,
        relief_parent_npa_id=relief_parent_npa_id,
        status="ACTIVE",
        jeopardy_declared_at=None,
        permissive_dialing_end_at=None,
    )
    db.npas[record["id"]] = record
    return record


@bp.route("/numbering/npas", methods=["POST"])
def create_npa():
    require_roles(ROLE_ADMIN)
    payload = body()
    npa_code = req_str(payload, "npa_code", 3, 3, NPA_PATTERN)
    state_code = req_str(payload, "state_code", 2, 2, STATE_PATTERN)
    npa_type = opt_enum(payload, "npa_type", C.NPA_TYPES, "GEOGRAPHIC")

    for existing in db.npas.values():
        if existing["npa_code"] == npa_code:
            fail("ERR_DUPLICATE_NPA_CODE", "npa_code %s already exists" % npa_code)

    record = new_npa(npa_code, state_code, npa_type)
    return object_response(serialize.npa(record), 201)


@bp.route("/numbering/npas", methods=["GET"])
def list_npas():
    require_roles(*READERS)
    rows = by_created(db.npas.values())
    rows = filter_rows(
        rows,
        [
            ("state_code", field("state_code")),
            ("status", field("status")),
            ("npa_type", field("npa_type")),
            ("relief_parent_npa_id", field("relief_parent_npa_id")),
        ],
    )
    return paginate(rows, serialize.npa)


@bp.route("/numbering/npas/<npa_id>", methods=["GET"])
def get_npa(npa_id):
    require_roles(*READERS)
    return object_response(serialize.npa(core.get_npa(npa_id)))


@bp.route("/numbering/npas/<npa_id>/rate-centers", methods=["GET"])
def list_npa_rate_centers(npa_id):
    require_roles(*RC_READERS)
    npa = core.get_npa(npa_id)
    rows = core.rate_centers_of_npa(npa["id"])
    rows = filter_rows(
        rows,
        [
            ("state_code", field("state_code")),
            ("lata_code", field("lata_code")),
            ("pooling_status", field("pooling_status")),
        ],
    )
    return paginate(rows, serialize.rate_center)


@bp.route("/numbering/npas/<npa_id>/jeopardy-declarations", methods=["POST"])
def declare_jeopardy(npa_id):
    require_roles(ROLE_ADMIN)
    payload = body()
    opt_str(payload, "reason", 1, 500)
    npa = core.get_npa(npa_id)
    if npa["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "jeopardy may only be declared on an ACTIVE code")
    core.declare_jeopardy(npa)
    return object_response(serialize.npa(npa))
