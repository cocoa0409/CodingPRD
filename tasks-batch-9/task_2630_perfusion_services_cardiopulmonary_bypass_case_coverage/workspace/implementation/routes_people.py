"""Perfusionists, certification cycles and continuing-education claims."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import constants as C
import serialize
import svc
import valid as V
from auth import ROLE_CHIEF, ROLE_CONTRACT_ADMIN, ROLE_PERFUSIONIST, endpoint
from envelope import ok, ok_list
from errors import ApiError
from store import db, insert, ordered, stamp_new, touch

D = Decimal
bp = Blueprint("people", __name__)

PEOPLE_READ = (ROLE_CONTRACT_ADMIN, ROLE_CHIEF, ROLE_PERFUSIONIST)


@bp.post("/perfusionists")
@endpoint([ROLE_CONTRACT_ADMIN])
def create_perfusionist(actor):
    body = V.payload()
    V.require(body, "full_name", "employee_code")
    row = {
        "full_name": V.vstr(body, "full_name", max_len=120, required=True),
        "employee_code": V.vstr(body, "employee_code", required=True),
        "employment_status": V.venum(body, "employment_status", C.EMPLOYMENT_STATUSES,
                                     default="ACTIVE"),
        "is_chief": V.vbool(body, "is_chief", default=False),
        "ecmo_privileged": V.vbool(body, "ecmo_privileged", default=False),
        "career_case_count": V.vint(body, "career_case_count", minimum=0, default=0),
        "ce_credits_verified": D("0.0"),
        "ce_credits_pending": D("0.0"),
        "readiness_score": D("0.000"),
        "readiness_variant_last": None,
    }
    for other in db.perfusionists.values():
        if other["employee_code"] == row["employee_code"]:
            raise ApiError("ERR_DUPLICATE_CODE")
    stamp_new(row)
    insert("perfusionists", row)
    return ok(serialize.perfusionist(row), 201)


@bp.get("/perfusionists/<pid>")
@endpoint(PEOPLE_READ)
def read_perfusionist(actor, pid):
    return ok(serialize.perfusionist(svc.get_perfusionist(pid)))


# ------------------------------------------------------- certifications

@bp.post("/perfusionists/<pid>/certifications")
@endpoint([ROLE_CONTRACT_ADMIN])
def create_certification(actor, pid):
    body = V.payload()
    V.require(body, "cert_code", "issued_on", "expires_on")
    row = {
        "perfusionist_id": pid,
        "cert_code": V.venum(body, "cert_code", C.CERT_CODES, required=True),
        "status": "ACTIVE",
        "issued_on": V.vdt(body, "issued_on", required=True),
        "expires_on": V.vdt(body, "expires_on", required=True),
        "cycle_credit_requirement": V.vint(body, "cycle_credit_requirement", minimum=1,
                                           default=45),
        "remediation_credits_required": D("0.0"),
        "probation_credits_banked": D("0.0"),
        "probation_count": 0,
    }
    perf = svc.get_perfusionist(pid)
    if row["expires_on"] <= row["issued_on"]:
        raise ApiError("ERR_INVALID_TIME_WINDOW")
    stamp_new(row)
    insert("certifications", row)
    svc.refresh_ce_ledger(perf)
    return ok(serialize.certification(row), 201)


@bp.get("/perfusionists/<pid>/certifications")
@endpoint(PEOPLE_READ)
def list_certifications(actor, pid):
    limit, offset = V.pagination()
    svc.get_perfusionist(pid)
    rows = [r for r in ordered("certifications") if r["perfusionist_id"] == pid]
    cert_code = request.args.get("cert_code")
    status = request.args.get("status")
    if cert_code is not None:
        rows = [r for r in rows if r["cert_code"] == cert_code]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([serialize.certification(r) for r in V.page(rows, limit, offset)],
                   limit, offset, len(rows))


# --------------------------------------------------------- CE activities

@bp.post("/perfusionists/<pid>/ce-activities")
@endpoint([ROLE_CONTRACT_ADMIN, ROLE_CHIEF, ROLE_PERFUSIONIST])
def create_ce_activity(actor, pid):
    body = V.payload()
    V.require(body, "category", "credit_hours", "activity_date", "accreditation_body")
    row = {
        "perfusionist_id": pid,
        "category": V.venum(body, "category", C.CE_CATEGORIES, required=True),
        "credit_hours": V.vnum(body, "credit_hours", minimum=0, maximum=20, max_dp=1,
                               required=True),
        "activity_date": V.vdt(body, "activity_date", required=True),
        "accreditation_body": V.venum(body, "accreditation_body", C.CE_BODIES, required=True),
        "status": "SUBMITTED",
        "counted_toward_remediation": False,
    }
    if row["credit_hours"] <= 0:
        raise ApiError("ERR_INVALID_FIELD_VALUE", "Field 'credit_hours' must be greater than zero.")
    perf = svc.get_perfusionist(pid)
    cert = calc.ccp_certification(pid)
    if not calc.in_cycle_window(row["activity_date"], cert):
        raise ApiError("ERR_CE_ACTIVITY_OUTSIDE_CYCLE")
    stamp_new(row)
    insert("ce_activities", row)
    svc.refresh_ce_ledger(perf)
    return ok(serialize.ce_activity(row), 201)


@bp.get("/perfusionists/<pid>/ce-activities")
@endpoint(PEOPLE_READ)
def list_ce_activities(actor, pid):
    limit, offset = V.pagination()
    svc.get_perfusionist(pid)
    rows = [r for r in ordered("ce_activities") if r["perfusionist_id"] == pid]
    status = request.args.get("status")
    category = request.args.get("category")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    return ok_list([serialize.ce_activity(r) for r in V.page(rows, limit, offset)],
                   limit, offset, len(rows))


@bp.post("/ce-activities/<aid>/verification")
@endpoint([ROLE_CONTRACT_ADMIN])
def adjudicate_ce_activity(actor, aid):
    body = V.payload()
    V.require(body, "decision")
    decision = V.venum(body, "decision", ("VERIFIED", "REJECTED", "REVOKED"), required=True)
    V.vstr(body, "note", allow_empty=True)
    activity = svc.get_ce_activity(aid)

    if decision in ("VERIFIED", "REJECTED"):
        if activity["status"] != "SUBMITTED":
            raise ApiError("ERR_CE_ACTIVITY_STATE_INVALID")
    else:
        if activity["status"] != "VERIFIED":
            raise ApiError("ERR_CE_ACTIVITY_STATE_INVALID")

    perf = db.perfusionists.get(activity["perfusionist_id"])
    cert = calc.ccp_certification(activity["perfusionist_id"])
    hours = D(activity["credit_hours"])

    if decision == "VERIFIED":
        activity["status"] = "VERIFIED"
        if cert is not None and cert["status"] == "PROBATION":
            activity["counted_toward_remediation"] = True
            cert["probation_credits_banked"] = calc.dp(
                D(cert["probation_credits_banked"]) + hours, 1)
            touch(cert)
        touch(activity)
        if perf is not None:
            svc.refresh_ce_ledger(perf)
        if cert is not None and cert["status"] == "PROBATION":
            if D(cert["probation_credits_banked"]) >= D(cert["remediation_credits_required"]):
                cert["status"] = "ACTIVE"
                cert["remediation_credits_required"] = D("0.0")
                cert["probation_credits_banked"] = D("0.0")
                touch(cert)
    elif decision == "REJECTED":
        activity["status"] = "REJECTED"
        touch(activity)
        if perf is not None:
            svc.refresh_ce_ledger(perf)
    else:
        activity["status"] = "REVOKED"
        if activity["counted_toward_remediation"]:
            if cert is not None:
                banked = D(cert["probation_credits_banked"]) - hours
                if banked < 0:
                    banked = D(0)
                cert["probation_credits_banked"] = calc.dp(banked, 1)
                touch(cert)
            activity["counted_toward_remediation"] = False
        touch(activity)
        if perf is not None:
            svc.refresh_ce_ledger(perf)

    return ok(serialize.ce_activity(activity))
