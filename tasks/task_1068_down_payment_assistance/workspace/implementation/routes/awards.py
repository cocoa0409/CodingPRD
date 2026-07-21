from flask import Blueprint

import store
from errors import ApiError
import context as ctx
import domain
from serializers import public, public_list
import envelope as env

bp = Blueprint("awards", __name__)

ASSISTANCE_TYPES = {"GRANT", "LOAN", "SHARED_APPRECIATION"}


@bp.post("/applications/<aid>/awards")
def create_award(aid):
    ctx.authenticate(["CaseManager"])
    app = ctx.lookup("application", aid)
    data = ctx.body()
    assistance_type = ctx.req_enum(data, "assistance_type", ASSISTANCE_TYPES)
    if app["status"] != "ELIGIBLE":
        raise ApiError("ERR_INVALID_STATE", "Application is not ELIGIBLE.")
    program = store.programs[app["program_id"]]

    rec = store.new_record("award")
    rec.update({
        "application_id": aid,
        "assistance_type": assistance_type,
        "recapture_model": program["recapture_model"],
        "assistance_amount_cents": app["estimated_assistance_cents"],
        "assistance_amount_final_cents": None,
        "allocated_cents": 0,
        "original_disbursed_cents": None,
        "basis_value_cents": None,
        "approved_by_user_id": None,
        "status": "PENDING_EDUCATION",
    })
    store.awards[rec["id"]] = rec
    return env.success(public(rec), 201)


@bp.get("/awards/<wid>")
def get_award(wid):
    ctx.authenticate(["CaseManager", "ProgramAdmin", "ClosingCoordinator", "Servicer"])
    rec = ctx.lookup("award", wid)
    return env.success(public(rec), 200)


@bp.get("/awards")
def list_awards():
    ctx.authenticate(["CaseManager", "ProgramAdmin"])
    limit, offset = ctx.pagination_params()
    filters = {
        "application_id": ctx.query_filter("application_id"),
        "status": ctx.query_filter("status"),
    }
    page, total = ctx.paginate(store.awards.values(), limit, offset, filters)
    return env.list_response(public_list(page), limit, offset, total)


@bp.post("/awards/<wid>/approve")
def approve_award(wid):
    uid, _ = ctx.authenticate(["CaseManager"])
    award = ctx.lookup("award", wid)
    if award["status"] != "PENDING_EDUCATION":
        raise ApiError("ERR_INVALID_STATE", "Award is not PENDING_EDUCATION.")
    app = store.applications[award["application_id"]]
    if app["status"] != "ELIGIBLE":
        raise ApiError("ERR_INVALID_STATE", "Underlying application is not ELIGIBLE.")

    # Segregation of duties.
    if uid == app["reviewed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Approver may not be the reviewer of the application.")

    # Education completeness: any certificate ever issued (VALID or EXPIRED).
    certs = [c for c in store.certificates.values() if c["applicant_id"] == app["applicant_id"]]
    if not certs:
        raise ApiError("ERR_EDUCATION_INCOMPLETE", "Applicant has no education certificate.")

    # Certificate currency: at least one still in-date.
    if not any(store.clock_now() <= c["_expires_dt"] for c in certs):
        raise ApiError("ERR_CERTIFICATE_EXPIRED", "Applicant's certificate has expired.")

    award["approved_by_user_id"] = uid
    award["status"] = "APPROVED"
    store.touch(award)
    return env.success(public(award), 200)


@bp.post("/awards/<wid>/cancel")
def cancel_award(wid):
    ctx.authenticate(["CaseManager"])
    award = ctx.lookup("award", wid)
    if award["status"] not in ("APPROVED", "FUNDED"):
        raise ApiError("ERR_INVALID_STATE", "Award is not APPROVED or FUNDED.")
    domain.cancel_award_cascade(award)
    return env.success(public(award), 200)
