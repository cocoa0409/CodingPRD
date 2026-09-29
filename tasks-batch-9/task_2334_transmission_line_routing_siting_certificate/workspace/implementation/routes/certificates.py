"""Certificates, conditions, waivers and closeout (PRD §3.7, §3.9)."""

from flask import Blueprint

import response as resp
from db import store
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from services import calc, derive
from validation import (
    apply_filters,
    collection_list,
    find_path,
    get_body,
    opt_str,
    paginate,
    req_str,
)

bp = Blueprint("certificates", __name__)


@bp.get("/siting/certificates")
@endpoint(ALL_ROLES)
def list_certificates():
    rows, pagination = collection_list(
        store.certificates, ["application_id", "certified_route_id", "status", "posture"]
    )
    return resp.listing(rows, pagination)


@bp.get("/siting/certificates/<certificate_id>")
@endpoint(ALL_ROLES)
def read_certificate(certificate_id):
    return resp.ok(find_path(store.certificates, certificate_id))


@bp.get("/siting/certificates/<certificate_id>/conditions")
@endpoint(ALL_ROLES)
def list_certificate_conditions(certificate_id):
    find_path(store.certificates, certificate_id)
    rows = apply_filters(
        derive.conditions_of_certificate(certificate_id),
        ["category", "constraint_kind", "status"],
    )
    rows, pagination = paginate(rows)
    return resp.listing(rows, pagination)


@bp.get("/siting/certificate-conditions")
@endpoint(ALL_ROLES)
def list_conditions():
    rows, pagination = collection_list(
        store.certificate_conditions,
        ["certificate_id", "category", "constraint_kind", "status"],
    )
    return resp.listing(rows, pagination)


@bp.get("/siting/certificate-conditions/<condition_id>")
@endpoint(ALL_ROLES)
def read_condition(condition_id):
    return resp.ok(find_path(store.certificate_conditions, condition_id))


@bp.post("/siting/certificate-conditions/<condition_id>/waiver")
@endpoint(["CommissionStaff"])
def waive_condition(condition_id):
    condition = find_path(store.certificate_conditions, condition_id)
    body = get_body()
    waiver_reason = req_str(body, "waiver_reason")

    if condition["status"] == "WAIVED":
        raise ApiError("ERR_TERMINAL_STATE", "The condition is already WAIVED.")
    if condition["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE condition may be waived.")

    certificate = store.certificates.get(condition["certificate_id"])
    if certificate is not None:
        if certificate["posture"] == "REVOKED":
            raise ApiError("ERR_CERTIFICATE_REVOKED", "The certificate has been revoked.")
        if certificate["posture"] != "ACTIVE":
            raise ApiError(
                "ERR_CERTIFICATE_NOT_ACTIVE",
                "The certificate's posture is %s." % certificate["posture"],
            )

    derive.apply(condition, status="WAIVED", waiver_reason=waiver_reason)
    return resp.created(condition)


@bp.post("/siting/certificates/<certificate_id>/closeout")
@endpoint(["CommissionStaff"])
def close_certificate(certificate_id):
    certificate = find_path(store.certificates, certificate_id)
    body = get_body()
    opt_str(body, "closeout_note")

    if certificate["status"] == "CLOSED":
        raise ApiError("ERR_TERMINAL_STATE", "The certificate is already CLOSED.")
    if certificate["posture"] != "ACTIVE":
        raise ApiError(
            "ERR_CERTIFICATE_NOT_ACTIVE", "The certificate's posture is %s." % certificate["posture"]
        )
    if calc.D(certificate["compliance_index_cumulative"]) < calc.CLOSEOUT_FLOOR:
        raise ApiError(
            "ERR_COMPLIANCE_TOO_LOW",
            "compliance_index_cumulative must be at least %s." % calc.CLOSEOUT_FLOOR,
        )

    segments = derive.segments_of_route(certificate["certified_route_id"])
    for segment in segments:
        if segment["construction_state"] != "COMPLETE":
            raise ApiError(
                "ERR_SEGMENTS_INCOMPLETE", "A segment on the certified route is not COMPLETE."
            )
    for finding in derive.findings_of_certificate(certificate_id):
        if finding["status"] == "OPEN":
            raise ApiError("ERR_OPEN_NONCONFORMANCE", "A nonconformance is still OPEN.")

    derive.apply(certificate, status="CLOSED")

    application = store.applications.get(certificate["application_id"])
    project = store.projects.get(application["project_id"]) if application else None
    if project is not None:
        released = project["escrow_balance_cents"]
        derive.update(
            project,
            escrow_balance_cents=0,
            escrow_funded_cents=project["escrow_funded_cents"] - released,
            stage="ENERGIZED",
        )
    return resp.created(certificate)
