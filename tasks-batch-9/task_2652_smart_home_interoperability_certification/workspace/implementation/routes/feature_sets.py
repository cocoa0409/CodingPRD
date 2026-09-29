"""Feature sets (PRD 3.1)."""

import re

from flask import Blueprint

import common as C
import enums as E
import middleware as M
import queries as Q
import shape as S
from db import new_row, ordered, set_fields, store
from errors import ApiError
from response import list_response, object_response
from serial import public, public_list

bp = Blueprint("feature_sets", __name__)

FEATURE_CODE_RE = re.compile(r"^[A-Z0-9_]+$")


@bp.post("/feature-sets")
def create_feature_set():
    M.auth([M.PROGRAM_ADMIN])
    body = S.body_obj()
    # rung 5 -- body foreign keys in input-declaration order
    spec = C.body_fk("specification", body, "specification_id")
    depends_on = C.body_fk("feature_set", body, "depends_on_feature_set_id")
    # rung 6 -- shape and ranges
    S.req_str(body, "specification_id")
    device_type = S.req_str(body, "device_type")
    feature_code = S.req_str(body, "feature_code", 1, 48)
    if not FEATURE_CODE_RE.match(feature_code):
        S.bad("feature_code must use uppercase letters, digits and underscores")
    obligation = S.req_str(body, "obligation")
    test_case_count = S.req_int(body, "test_case_count", 1, 500)
    security_relevant = False
    if "security_relevant" in body and body.get("security_relevant") is not None:
        security_relevant = S.req_bool(body, "security_relevant")
    depends_on_id = S.opt_str(body, "depends_on_feature_set_id")
    if obligation == "CONDITIONAL":
        if depends_on_id is None:
            S.bad("depends_on_feature_set_id is required when obligation is CONDITIONAL")
    elif obligation in ("MANDATORY", "OPTIONAL") and depends_on_id is not None:
        S.bad("depends_on_feature_set_id must be null unless obligation is CONDITIONAL")
    # rung 7 -- enum membership
    S.check_enum(device_type, E.DEVICE_TYPES, "device_type")
    S.check_enum(obligation, E.OBLIGATIONS, "obligation")
    # rung 13 -- the version must still be DRAFT
    if spec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SPECIFICATION_STATE",
                       "feature sets may only be added to a DRAFT version")
    # rung 31 -- feature_code uniqueness within (specification_id, device_type)
    for row in Q.feature_sets_for(spec["id"], device_type):
        if row["feature_code"] == feature_code:
            raise ApiError("ERR_DUPLICATE_FEATURE_CODE",
                           "feature_code already exists for this device class")
    # rung 32 -- dependency edge validity
    if depends_on is not None:
        if (depends_on["specification_id"] != spec["id"]
                or depends_on["device_type"] != device_type):
            raise ApiError("ERR_FEATURE_DEPENDENCY_CYCLE",
                           "a dependency must share the specification and device class")
        seen = set()
        cursor = depends_on
        while cursor is not None:
            if cursor["id"] in seen:
                raise ApiError("ERR_FEATURE_DEPENDENCY_CYCLE", "dependency graph must stay acyclic")
            seen.add(cursor["id"])
            nxt = cursor.get("depends_on_feature_set_id")
            cursor = store.feature_sets.get(nxt) if nxt else None

    feature_set = new_row(
        specification_id=spec["id"],
        device_type=device_type,
        feature_code=feature_code,
        obligation=obligation,
        test_case_count=test_case_count,
        security_relevant=security_relevant,
        depends_on_feature_set_id=depends_on["id"] if depends_on is not None else None,
    )
    store.feature_sets[feature_set["id"]] = feature_set
    set_fields(spec, feature_set_count=len(Q.feature_sets_of_spec(spec["id"])))
    return object_response(public(feature_set), 201)


@bp.get("/feature-sets/<feature_set_id>")
def get_feature_set(feature_set_id):
    M.auth(M.ALL_ROLES)
    return object_response(public(C.must("feature_set", feature_set_id)), 200)


@bp.get("/feature-sets")
def list_feature_sets():
    M.auth(M.ALL_ROLES)
    limit, offset = S.paging()
    specification_id = S.q_str("specification_id")
    device_type = S.q_enum("device_type", E.DEVICE_TYPES)
    obligation = S.q_enum("obligation", E.OBLIGATIONS)
    depends_on = S.q_str("depends_on_feature_set_id")
    rows = ordered(store.feature_sets.values())
    if specification_id is not None:
        rows = [r for r in rows if r["specification_id"] == specification_id]
    if device_type is not None:
        rows = [r for r in rows if r["device_type"] == device_type]
    if obligation is not None:
        rows = [r for r in rows if r["obligation"] == obligation]
    if depends_on is not None:
        rows = [r for r in rows if r["depends_on_feature_set_id"] == depends_on]
    page, total = C.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)
