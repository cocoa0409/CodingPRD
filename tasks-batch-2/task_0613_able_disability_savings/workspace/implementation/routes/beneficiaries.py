"""Beneficiary, Certification, and death routes."""
from datetime import date

from flask import Blueprint, request

from db import db, stamp_new, touch
from middleware import get_identity, require_role
from response import ok, created, ok_list
from errors import err
from services import domain
from routes.common import (
    get_body, find_or_404, require_string, optional_int, optional_bool,
    require_enum, paginate,
)

bp = Blueprint("beneficiaries", __name__)

ALL_ROLES = {"ProgramAdministrator", "Beneficiary", "AuthorizedRepresentative"}
CERT_BASIS = {"SSI_SSDI_ENTITLEMENT", "DISABILITY_DIAGNOSIS"}


def _parse_date(s):
    return date.fromisoformat(str(s)[:10])


# ---------------------------------------------------------------------------
# Beneficiary
# ---------------------------------------------------------------------------
@bp.post("/able/beneficiaries")
def create_beneficiary():
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    body = get_body()
    require_string(body, "program_id")
    require_string(body, "full_name")
    require_string(body, "birth_date")
    require_string(body, "disability_onset_date")
    require_string(body, "state_code")
    find_or_404(db.programs, body["program_id"], "Program")
    b = {
        "program_id": body["program_id"],
        "full_name": body["full_name"],
        "birth_date": body["birth_date"],
        "disability_onset_date": body["disability_onset_date"],
        "state_code": body["state_code"],
        "other_countable_resources_cents": optional_int(body, "other_countable_resources_cents", 0),
        "receives_ssi": optional_bool(body, "receives_ssi", False),
        "receives_medicaid": optional_bool(body, "receives_medicaid", False),
        "employer_retirement_plan_participant": optional_bool(body, "employer_retirement_plan_participant", False),
        "gross_employment_income_ytd_cents": optional_int(body, "gross_employment_income_ytd_cents", 0),
        "is_deceased": False,
    }
    stamp_new(b)
    db.beneficiaries[b["id"]] = b
    return created(domain.serialize_beneficiary(b))


@bp.get("/able/beneficiaries/<bid>")
def get_beneficiary(bid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    b = find_or_404(db.beneficiaries, bid, "Beneficiary")
    return ok(domain.serialize_beneficiary(b))


@bp.get("/able/beneficiaries")
def list_beneficiaries():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    program_id = request.args.get("program_id")
    items = list(db.beneficiaries.values())
    if program_id is not None:
        items = [b for b in items if b["program_id"] == program_id]
    page, limit, offset, total = paginate(items)
    return ok_list([domain.serialize_beneficiary(b) for b in page],
                   limit, offset, total)


@bp.post("/able/beneficiaries/<bid>/record_death")
def record_death(bid):
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    b = find_or_404(db.beneficiaries, bid, "Beneficiary")
    # state precondition: not already deceased
    if b["is_deceased"]:
        raise err("ERR_INVALID_STATE", "Beneficiary already deceased")
    b["is_deceased"] = True
    touch(b)
    # cascade to account(s)
    for acct in db.accounts.values():
        if acct["beneficiary_id"] != bid:
            continue
        if acct["status"] in ("OPEN", "SUSPENDED"):
            acct["status"] = "FROZEN_DEATH"
            touch(acct)
            # revoke ACTIVE representatives
            for rep in db.authorized_representatives.values():
                if rep["account_id"] == acct["id"] and rep["status"] == "ACTIVE":
                    rep["status"] = "REVOKED"
                    touch(rep)
            # reject REQUESTED / APPROVED distributions
            for dist in db.distributions.values():
                if dist["account_id"] == acct["id"] and dist["status"] in ("REQUESTED", "APPROVED"):
                    dist["status"] = "REJECTED"
                    touch(dist)
    return ok(domain.serialize_beneficiary(b))


# ---------------------------------------------------------------------------
# Certification
# ---------------------------------------------------------------------------
@bp.post("/able/beneficiaries/<bid>/certifications")
def create_certification(bid):
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    b = find_or_404(db.beneficiaries, bid, "Beneficiary")
    body = get_body()
    require_enum(body, "basis", CERT_BASIS)
    require_string(body, "effective_date")
    require_string(body, "expires_on")
    diagnosis_code = body.get("diagnosis_code")
    # ERR_DIAGNOSIS_REQUIRED (422) for DISABILITY_DIAGNOSIS without code (priority 11)
    if body["basis"] == "DISABILITY_DIAGNOSIS":
        if not isinstance(diagnosis_code, str) or diagnosis_code == "":
            raise err("ERR_DIAGNOSIS_REQUIRED",
                      "diagnosis_code required for DISABILITY_DIAGNOSIS basis")
    # certification_window_overlap (half-open) against ALL existing certs (any status)
    new_eff = _parse_date(body["effective_date"])
    new_exp = _parse_date(body["expires_on"])
    for c in db.certifications.values():
        if c["beneficiary_id"] != bid:
            continue
        c_eff = _parse_date(c["effective_date"])
        c_exp = _parse_date(c["expires_on"])
        # half-open: overlap iff new.eff < c.exp AND c.eff < new.exp
        if new_eff < c_exp and c_eff < new_exp:
            raise err("ERR_CERT_WINDOW_OVERLAP",
                      "Certification window overlaps an existing window")
    c = {
        "beneficiary_id": bid,
        "basis": body["basis"],
        "diagnosis_code": diagnosis_code if isinstance(diagnosis_code, str) and diagnosis_code != "" else None,
        "effective_date": body["effective_date"],
        "expires_on": body["expires_on"],
        "status": "PENDING",
    }
    stamp_new(c)
    db.certifications[c["id"]] = c
    return created(domain.serialize_certification(c))


@bp.get("/able/certifications/<cid>")
def get_certification(cid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    c = find_or_404(db.certifications, cid, "Certification")
    return ok(domain.serialize_certification(c))


@bp.get("/able/certifications")
def list_certifications():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    beneficiary_id = request.args.get("beneficiary_id")
    items = list(db.certifications.values())
    if beneficiary_id is not None:
        items = [c for c in items if c["beneficiary_id"] == beneficiary_id]
    page, limit, offset, total = paginate(items)
    return ok_list([domain.serialize_certification(c) for c in page],
                   limit, offset, total)


@bp.post("/able/certifications/<cid>/decide")
def decide_certification(cid):
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    c = find_or_404(db.certifications, cid, "Certification")
    body = get_body()
    decision = require_enum(body, "decision", {"APPROVE", "DENY"})
    # state: must be PENDING (priority 6)
    if c["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Certification is not PENDING")
    b = db.beneficiaries[c["beneficiary_id"]]
    if decision == "APPROVE":
        # onset age strictly < disability_onset_max_age (priority 10)
        program = db.programs[b["program_id"]]
        onset_age = _onset_age(b["birth_date"], b["disability_onset_date"])
        if onset_age >= program["disability_onset_max_age"]:
            raise err("ERR_ONSET_AGE_INELIGIBLE",
                      "Disability onset age is not below the eligibility maximum")
        # diagnosis required for DISABILITY_DIAGNOSIS basis (priority 11)
        if c["basis"] == "DISABILITY_DIAGNOSIS":
            if not c.get("diagnosis_code"):
                raise err("ERR_DIAGNOSIS_REQUIRED",
                          "diagnosis_code required for DISABILITY_DIAGNOSIS basis")
        c["status"] = "CERTIFIED"
    else:
        c["status"] = "DENIED"
    touch(c)
    touch(b)  # eligibility recomputed -> mutation
    return ok(domain.serialize_certification(c))


def _onset_age(birth_date, onset_date):
    bd = _parse_date(birth_date)
    od = _parse_date(onset_date)
    age = od.year - bd.year
    if (od.month, od.day) < (bd.month, bd.day):
        age -= 1
    return age
