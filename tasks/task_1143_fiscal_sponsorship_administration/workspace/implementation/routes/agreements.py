"""SponsorshipAgreement + GrantTranche endpoints (PRD §3.2)."""

from flask import Blueprint, request

from db import new_id, parse_iso_date, stamp_new, store, today, touch
from envelope import ok_list, ok_obj
from errors import (
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_MODEL_MISMATCH,
    ERR_PROJECT_NOT_FOUND,
    ERR_STALE_AGREEMENT_VERSION,
    ERR_TRANCHE_NOT_FOUND,
    ERR_TRANCHE_PERIOD_INVALID,
    ERR_TRANCHE_PERIOD_OVERLAP,
    ERR_TRANCHE_STATE_INVALID,
    ERR_VALIDATION,
    raise_err,
)
from security import (
    READ_ROLES,
    auth,
    body,
    opt_enum,
    opt_str,
    req_int,
    req_str,
    require_owner,
    require_role,
)

bp = Blueprint("agreements", __name__)

SPENDING_BASES = ("SETTLED", "FORWARD_LOOKING")


def get_agreement(agreement_id):
    agreement = store.agreements.get(agreement_id)
    if agreement is None:
        raise_err(ERR_AGREEMENT_NOT_FOUND, "agreement not found")
    return agreement


@bp.get("/fsa/agreements")
def list_agreements():
    uid, role = auth()
    require_role(role, READ_ROLES)
    items = list(store.agreements.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [a for a in items if a["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return ok_list(items)


@bp.get("/fsa/agreements/<agreement_id>")
def get_agreement_route(agreement_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    return ok_obj(get_agreement(agreement_id))


@bp.get("/fsa/projects/<project_id>/agreements")
def project_agreements(project_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    if project_id not in store.projects:
        raise_err(ERR_PROJECT_NOT_FOUND, "project not found")
    items = [a for a in store.agreements.values() if a["project_id"] == project_id]
    return ok_list(items)


@bp.post("/fsa/agreements/<agreement_id>/countersign")
def countersign(agreement_id):
    uid, role = auth()
    require_role(role, {"Applicant"})
    agreement = get_agreement(agreement_id)
    # ownership: X-User-ID == source application's applicant_user_id
    project = store.projects.get(agreement["project_id"])
    application = store.applications.get(project["source_application_id"]) if project else None
    anchor = application["applicant_user_id"] if application else None
    require_owner(uid, anchor)
    if agreement["status"] != "PENDING_COUNTERSIGN":
        raise_err(ERR_AGREEMENT_NOT_ACTIVE, "agreement is not PENDING_COUNTERSIGN")
    agreement["status"] = "ACTIVE"
    touch(agreement)
    if project and project["status"] == "PROPOSED":
        project["status"] = "ACTIVE"
        touch(project)
    from db import fund_of_project
    fund = fund_of_project(agreement["project_id"])
    if fund and fund["status"] == "PENDING":
        fund["status"] = "ACTIVE"
        touch(fund)
    return ok_obj(agreement)


@bp.post("/fsa/agreements/<agreement_id>/amend")
def amend(agreement_id):
    data = body()
    expected_version = req_int(data, "expected_agreement_version")
    spending_basis = opt_enum(data, "spending_basis", SPENDING_BASES)
    effective_date = opt_str(data, "effective_date")
    note = opt_str(data, "note")
    uid, role = auth()
    require_role(role, {"SponsorAdmin"})
    agreement = get_agreement(agreement_id)
    if agreement["status"] != "ACTIVE":
        raise_err(ERR_AGREEMENT_NOT_ACTIVE, "agreement is not ACTIVE")
    if expected_version != agreement["version"]:
        raise_err(ERR_STALE_AGREEMENT_VERSION, "expected_agreement_version does not match current version")
    if spending_basis == "FORWARD_LOOKING" and agreement["model"] != "COMPREHENSIVE":
        raise_err(ERR_MODEL_MISMATCH, "FORWARD_LOOKING spending basis requires COMPREHENSIVE model")
    if spending_basis is not None:
        agreement["spending_basis"] = spending_basis
    if effective_date is not None:
        agreement["effective_date"] = effective_date
    if note is not None:
        agreement["amendment_note"] = note
    touch(agreement)
    return ok_obj(agreement)


# ---------------------------------------------------------------------------
# Grant tranches
# ---------------------------------------------------------------------------


@bp.post("/fsa/agreements/<agreement_id>/grant-tranches")
def create_tranche(agreement_id):
    data = body()
    amount = req_int(data, "amount_cents")
    period_start = req_str(data, "period_start")
    period_end = req_str(data, "period_end")
    purpose = req_str(data, "purpose")
    if amount < 1:
        raise_err(ERR_VALIDATION, "amount_cents must be >= 1")
    start = parse_iso_date(period_start)
    end = parse_iso_date(period_end)
    if start is None:
        raise_err(ERR_VALIDATION, "period_start must be an ISO date (YYYY-MM-DD)")
    if end is None:
        raise_err(ERR_VALIDATION, "period_end must be an ISO date (YYYY-MM-DD)")
    uid, role = auth()
    require_role(role, {"SponsorAdmin"})
    agreement = get_agreement(agreement_id)
    # closed-interval overlap against ISSUED tranches (pipeline rule 16)
    for t in store.tranches.values():
        if t["agreement_id"] == agreement["id"] and t["status"] == "ISSUED":
            if start <= t["_period_end"] and t["_period_start"] <= end:
                raise_err(ERR_TRANCHE_PERIOD_OVERLAP, "tranche period overlaps an existing tranche")
    # model gate (rule 20)
    if agreement["model"] != "PRE_APPROVED_GRANT":
        raise_err(ERR_MODEL_MISMATCH, "grant tranches exist only under PRE_APPROVED_GRANT")
    # interval sanity (rule 21)
    if end < start:
        raise_err(ERR_TRANCHE_PERIOD_INVALID, "period_end is earlier than period_start")
    tranche = stamp_new({
        "id": new_id(),
        "agreement_id": agreement["id"],
        "amount_cents": amount,
        "period_start": period_start,
        "period_end": period_end,
        "purpose": purpose,
        "status": "ISSUED",
        "committed_cents": 0,
        "spent_cents": 0,
        "report_note": None,
    })
    tranche["_period_start"] = start
    tranche["_period_end"] = end
    store.tranches[tranche["id"]] = tranche
    return ok_obj(tranche, 201)


@bp.get("/fsa/agreements/<agreement_id>/grant-tranches")
def list_tranches(agreement_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    get_agreement(agreement_id)
    items = [t for t in store.tranches.values() if t["agreement_id"] == agreement_id]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return ok_list(items)


def get_tranche(tranche_id):
    tranche = store.tranches.get(tranche_id)
    if tranche is None:
        raise_err(ERR_TRANCHE_NOT_FOUND, "grant tranche not found")
    return tranche


@bp.get("/fsa/grant-tranches/<tranche_id>")
def get_tranche_route(tranche_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    return ok_obj(get_tranche(tranche_id))


@bp.post("/fsa/grant-tranches/<tranche_id>/close")
def close_tranche(tranche_id):
    data = body()
    report_note = req_str(data, "report_note")
    uid, role = auth()
    require_role(role, {"SponsorAdmin"})
    tranche = get_tranche(tranche_id)
    if tranche["status"] != "ISSUED":
        raise_err(ERR_TRANCHE_STATE_INVALID, "tranche is already CLOSED")
    if today() <= tranche["_period_end"]:
        raise_err(ERR_TRANCHE_STATE_INVALID, "tranche cannot close before its period ends")
    tranche["status"] = "CLOSED"
    tranche["report_note"] = report_note
    touch(tranche)
    return ok_obj(tranche)
