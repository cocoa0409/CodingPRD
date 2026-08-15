"""Application routes (PRD §3.2, §3.4): creation with priority-window and
continuation-chain gates, filing, grant (annuity schedule generation),
official-register lapse, withdrawal, and DRAFT re-parenting.
"""

from flask import Blueprint, request

import db as dbmod
import serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_CLIENT_SUSPENDED,
    ERR_PRIORITY_WINDOW_EXPIRED,
    ERR_DUPLICATE_APPLICATION_NUMBER,
    ERR_PARENT_APPLICATION_LAPSED,
    ERR_PARENT_FAMILY_MISMATCH,
    ERR_PRIORITY_CHAIN_CYCLE,
    ERR_PARENT_NOT_PCT,
    ERR_ASSIGNMENT_RECORDATION_REQUIRED,
    ERR_INVALID_STATE,
)
from middleware import require_roles, get_json_body, parse_pagination, ALL_ROLES
from response import success_object, success_list
from services.common import (
    new_id, stamp_new, bump, get_family, get_application,
    family_of_application, client_of_family, rule_for_jurisdiction,
    check_allowed_fields, req_str, req_enum, req_date, ensure_transition,
    JURISDICTIONS, APPLICATION_TYPES, ENTITY_SIZES,
)
from services import calc
from services.cascade import application_terminal_cascade

bp = Blueprint("applications", __name__)

_CREATE_FIELDS = {
    "jurisdiction", "application_type", "filing_date", "application_number",
    "entity_size", "parent_application_id",
}


def _check_continuation_chain(family, child_app_id, parent_id, application_type):
    """continuation_chain_check (PRD §3.2), invoked whenever a parent is
    supplied. Existence of the parent itself is resolved by the caller at
    the existence stage; here: lapsed, family, cycle, PCT gates in PRD order."""
    parent = get_application(parent_id)
    if parent["status"] == "LAPSED":
        raise_err(ERR_PARENT_APPLICATION_LAPSED, "Proposed parent application is LAPSED")
    if parent["family_id"] != family["id"]:
        raise_err(ERR_PARENT_FAMILY_MISMATCH, "Proposed parent belongs to a different family")
    # Cycle: walk parent links upward from the proposed parent.
    seen = set()
    cursor = parent
    while cursor is not None:
        if cursor["id"] == child_app_id:
            raise_err(ERR_PRIORITY_CHAIN_CYCLE, "Continuation chain would be cyclic")
        if cursor["id"] in seen:
            break
        seen.add(cursor["id"])
        next_id = cursor.get("parent_application_id")
        cursor = dbmod.DB["applications"].get(next_id) if next_id else None
    if application_type == "PCT_NATIONAL_PHASE" and parent["application_type"] != "PCT_INTERNATIONAL":
        raise_err(ERR_PARENT_NOT_PCT, "PCT_NATIONAL_PHASE requires a PCT_INTERNATIONAL parent")


@bp.post("/families/<family_id>/applications")
def create_application(family_id):
    require_roles(["DocketingClerk"])
    family = get_family(family_id)
    body = get_json_body()

    # Existence stage (priority 4): body FK references resolve after the path.
    parent_id = body.get("parent_application_id")
    if parent_id is not None and isinstance(parent_id, str):
        get_application(parent_id)
    jurisdiction = body.get("jurisdiction")
    rule = None
    if isinstance(jurisdiction, str) and jurisdiction in JURISDICTIONS:
        rule = rule_for_jurisdiction(jurisdiction)
        if rule is None:
            raise_err(ERR_NOT_FOUND, f"No JurisdictionRule for jurisdiction {jurisdiction}")

    # Body shape (priority 6).
    check_allowed_fields(body, _CREATE_FIELDS)
    jurisdiction = req_enum(body, "jurisdiction", JURISDICTIONS)
    application_type = req_enum(body, "application_type", APPLICATION_TYPES)
    filing_date = req_date(body, "filing_date")
    application_number = req_str(body, "application_number")
    entity_size = req_enum(body, "entity_size", ENTITY_SIZES)
    if parent_id is not None and not isinstance(parent_id, str):
        raise_err(ERR_INVALID_REQUEST, "parent_application_id must be a string id")

    # Business rules in the fixed PRD §2.9 order.
    if application_type == "PARIS_CONVENTION":
        deadline = calc.add_months(family["first_priority_date"], rule["paris_window_months"])
        if filing_date > deadline:
            raise_err(ERR_PRIORITY_WINDOW_EXPIRED, "Filing date is beyond the Paris Convention window")
    elif application_type == "PCT_NATIONAL_PHASE":
        deadline = calc.add_months(family["first_priority_date"], rule["pct_window_months"])
        if filing_date > deadline:
            raise_err(ERR_PRIORITY_WINDOW_EXPIRED, "Filing date is beyond the PCT national-phase window")

    duplicate = any(
        a["family_id"] == family["id"]
        and a["status"] != "WITHDRAWN"
        and a["application_number"] == application_number
        for a in dbmod.DB["applications"].values()
    )
    if duplicate:
        raise_err(ERR_DUPLICATE_APPLICATION_NUMBER, "application_number already used in this family")

    if parent_id is not None:
        _check_continuation_chain(family, None, parent_id, application_type)

    client = client_of_family(family)
    if client["status"] == "SUSPENDED":
        raise_err(ERR_CLIENT_SUSPENDED, "Client is SUSPENDED")

    rec = stamp_new({
        "id": new_id(),
        "family_id": family["id"],
        "jurisdiction": jurisdiction,
        "application_type": application_type,
        "filing_date": filing_date,
        "application_number": application_number,
        "entity_size": entity_size,
        "parent_application_id": parent_id,
        "grant_date": None,
        "status": "DRAFT",
        "open_docket_count": 0,
    })
    dbmod.DB["applications"][rec["id"]] = rec
    return success_object(serialize.application(rec), 201)


@bp.get("/families/<family_id>/applications")
def list_family_applications(family_id):
    require_roles(ALL_ROLES)
    family = get_family(family_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [a for a in dbmod.DB["applications"].values() if a["family_id"] == family["id"]]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize.application(r) for r in page], total, limit, offset)


@bp.get("/applications/<application_id>")
def get_application_route(application_id):
    require_roles(ALL_ROLES)
    return success_object(serialize.application(get_application(application_id)))


@bp.patch("/applications/<application_id>")
def reparent_application(application_id):
    require_roles(["DocketingClerk"])
    rec = get_application(application_id)
    body = get_json_body()
    parent_id = body.get("parent_application_id")
    if parent_id is not None:
        if not isinstance(parent_id, str):
            raise_err(ERR_INVALID_REQUEST, "parent_application_id must be a string id or null")
        get_application(parent_id)
    check_allowed_fields(body, {"parent_application_id"})
    ensure_transition(rec, {"DRAFT"}, "applications", "Application")
    if parent_id is not None:
        family = dbmod.DB["families"][rec["family_id"]]
        _check_continuation_chain(family, rec["id"], parent_id, rec["application_type"])
    rec["parent_application_id"] = parent_id
    bump(rec)
    return success_object(serialize.application(rec))


@bp.post("/applications/<application_id>/file")
def file_application(application_id):
    require_roles(["DocketingClerk"])
    rec = get_application(application_id)
    ensure_transition(rec, {"DRAFT"}, "applications", "Application")
    family = family_of_application(rec)
    client = client_of_family(family)
    if client["status"] == "SUSPENDED":
        raise_err(ERR_CLIENT_SUSPENDED, "Client is SUSPENDED")
    if family["status"] not in ("ACTIVE", "PRUNING_REVIEW"):
        raise_err(ERR_INVALID_STATE, f"Family in state {family['status']} does not permit filing")
    rec["status"] = "PENDING"
    bump(rec)
    return success_object(serialize.application(rec))


@bp.post("/applications/<application_id>/grant")
def grant_application(application_id):
    require_roles(["DocketingClerk"])
    rec = get_application(application_id)
    body = get_json_body()
    check_allowed_fields(body, {"grant_date"})
    grant_date = req_date(body, "grant_date")
    ensure_transition(rec, {"PENDING"}, "applications", "Application")
    rule = rule_for_jurisdiction(rec["jurisdiction"])
    if rule["requires_recorded_assignment_for_grant"]:
        recorded = any(
            a["application_id"] == rec["id"] and a["status"] == "RECORDED"
            for a in dbmod.DB["assignments"].values()
        )
        if not recorded:
            raise_err(
                ERR_ASSIGNMENT_RECORDATION_REQUIRED,
                "Jurisdiction requires a RECORDED assignment before grant",
            )
    rec["status"] = "GRANTED"
    rec["grant_date"] = grant_date
    bump(rec)
    # Annuity schedule materializes at grant (PRD §3.4), ascending period_year.
    for period_year, due, window_end in calc.obligation_schedule(rule, grant_date):
        base_local, est_usd = calc.on_time_estimate_usd(rule, rec["entity_size"], period_year)
        ob = stamp_new({
            "id": new_id(),
            "application_id": rec["id"],
            "period_year": period_year,
            "due_date": due,
            "surcharge_window_end": window_end,
            "base_fee_local_cents": base_local,
            "estimated_amount_usd_cents": est_usd,
            "authorized_amount_cents": None,
            "paid_amount_cents": None,
            "status": "SCHEDULED",
        })
        dbmod.DB["obligations"][ob["id"]] = ob
    return success_object(serialize.application(rec))


@bp.post("/applications/<application_id>/record-lapse")
def record_lapse(application_id):
    require_roles(["DocketingClerk"])
    rec = get_application(application_id)
    ensure_transition(rec, {"GRANTED"}, "applications", "Application")
    application_terminal_cascade(rec, "LAPSED")
    return success_object(serialize.application(rec))


@bp.post("/applications/<application_id>/withdraw")
def withdraw_application(application_id):
    require_roles(["DocketingClerk"])
    rec = get_application(application_id)
    ensure_transition(rec, {"DRAFT"}, "applications", "Application")
    rec["status"] = "WITHDRAWN"
    bump(rec)
    return success_object(serialize.application(rec))
