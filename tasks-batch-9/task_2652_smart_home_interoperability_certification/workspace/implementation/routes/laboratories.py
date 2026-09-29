"""Test laboratories: accreditation and competency (PRD 3.3)."""

from flask import Blueprint

import calc
import cascade
import common as C
import enums as E
import middleware as M
import shape as S
from db import new_row, now, ordered, set_fields, store
from errors import ApiError
from response import list_response, object_response
from serial import public, public_list

bp = Blueprint("laboratories", __name__)


@bp.post("/test-laboratories")
def create_laboratory():
    M.auth([M.PROGRAM_ADMIN])
    body = S.body_obj()
    name = S.req_str(body, "name", 1, 120)
    bench_capacity = S.req_int(body, "bench_capacity", 1, 32)
    device_types = S.req_str_array(body, "authorized_device_types")
    accreditation_expires_at = S.req_dt(body, "accreditation_expires_at")
    for value in device_types:
        S.check_enum(value, E.DEVICE_TYPES, "authorized_device_types")
    for row in store.laboratories.values():
        if row["name"] == name:
            raise ApiError("ERR_DUPLICATE_NAME", "name already exists")

    lab = new_row(
        name=name,
        bench_capacity=bench_capacity,
        authorized_device_types=list(device_types),
        accreditation_expires_at=accreditation_expires_at,
        accreditation_status="PROVISIONAL",
        competency_score=None,
        competency_variant=None,
        competency_reviewed_at=None,
        reserved_bench_minutes=0,
    )
    store.laboratories[lab["id"]] = lab
    return object_response(public(lab), 201)


@bp.get("/test-laboratories/<laboratory_id>")
def get_laboratory(laboratory_id):
    M.auth(M.ALL_ROLES)
    return object_response(public(C.must("laboratory", laboratory_id)), 200)


@bp.get("/test-laboratories")
def list_laboratories():
    M.auth(M.ALL_ROLES)
    limit, offset = S.paging()
    status = S.q_str("accreditation_status")
    device_type = S.q_enum("device_type", E.DEVICE_TYPES)
    rows = ordered(store.laboratories.values())
    if status is not None:
        rows = [r for r in rows if r["accreditation_status"] == status]
    if device_type is not None:
        rows = [r for r in rows if device_type in r["authorized_device_types"]]
    page, total = C.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


ACCREDITATION_ORIGINS = {
    "AUTHORIZE": ("PROVISIONAL",),
    "SUSPEND": ("AUTHORIZED",),
    "REINSTATE": ("SUSPENDED",),
    "REVOKE": ("PROVISIONAL", "AUTHORIZED", "SUSPENDED"),
}
ACCREDITATION_TARGET = {
    "AUTHORIZE": "AUTHORIZED",
    "SUSPEND": "SUSPENDED",
    "REINSTATE": "AUTHORIZED",
    "REVOKE": "REVOKED",
}


@bp.post("/test-laboratories/<laboratory_id>/accreditation-decision")
def accreditation_decision(laboratory_id):
    M.auth([M.PROGRAM_ADMIN])
    lab = C.must("laboratory", laboratory_id)
    body = S.body_obj()
    decision = S.req_str(body, "decision")
    S.check_enum(decision, E.ACCREDITATION_DECISIONS, "decision")
    # rung 15
    if lab["accreditation_status"] not in ACCREDITATION_ORIGINS[decision]:
        raise ApiError("ERR_INVALID_LABORATORY_STATE",
                       "%s is not available from %s" % (decision, lab["accreditation_status"]))
    # rung 29
    if decision in ("AUTHORIZE", "REINSTATE"):
        if not lab["accreditation_expires_at"] > now():
            raise ApiError("ERR_ACCREDITATION_EXPIRED", "accreditation has expired")

    set_fields(lab, accreditation_status=ACCREDITATION_TARGET[decision])
    if decision == "REVOKE":
        cascade.laboratory_revocation_cascade(lab)
    return object_response(public(lab), 200)


@bp.post("/test-laboratories/<laboratory_id>/competency-review")
def competency_review(laboratory_id):
    M.auth([M.PROGRAM_ADMIN])
    lab = C.must("laboratory", laboratory_id)
    body = S.body_obj()
    variant = S.req_str(body, "variant")
    S.check_enum(variant, E.COMPETENCY_VARIANTS, "variant")
    # rung 15
    if lab["accreditation_status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_LABORATORY_STATE",
                       "a competency review requires an AUTHORIZED laboratory")
    # rung 47
    if not calc.competency_sessions(lab["id"], variant):
        raise ApiError("ERR_NO_COMPLETED_SESSIONS",
                       "no COMPLETE sessions fall inside the %s window" % variant)

    result = calc.competency(lab, variant)
    fields = {
        "competency_score": result["competency_score"],
        "competency_variant": variant,
        "competency_reviewed_at": now(),
    }
    if result["competency_score"] < E.COMPETENCY_SUSPENSION_THRESHOLD:
        fields["accreditation_status"] = "SUSPENDED"
    set_fields(lab, **fields)
    return object_response(public(lab), 200)


@bp.get("/test-laboratories/<laboratory_id>/competency")
def read_competency(laboratory_id):
    M.auth([M.PROGRAM_ADMIN, M.TEST_LABORATORY, M.COMPLIANCE_OFFICER])
    lab = C.must("laboratory", laboratory_id)
    variant = S.q_enum("variant", E.COMPETENCY_VARIANTS) or "ROLLING_90D"
    result = calc.competency(lab, variant)
    result["on_time_ratio"] = str(result["on_time_ratio"])
    result["dispute_free_ratio"] = str(result["dispute_free_ratio"])
    result["competency_score"] = str(result["competency_score"])
    return object_response(result, 200)
