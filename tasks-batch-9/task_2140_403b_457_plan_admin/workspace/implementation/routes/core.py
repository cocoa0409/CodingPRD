"""Employers, vendors, plans and the logical clock."""
import datetime
import re

from flask import Blueprint, g, request

import auth
import calc
import derive
import envelope
import serialize
import store
import validate as V
from auth import endpoint
from errors import ApiError

bp = Blueprint("core", __name__)

EIN_RE = re.compile(r"^\d{2}-\d{7}$")


# ---------------------------------------------------------------- employers
@bp.post("/plan-admin/employers")
@endpoint(["SystemOperator"])
def create_employer():
    body = V.body_of(request)
    legal_name = V.req_str(body, "legal_name")
    ein = V.req_str(body, "ein")
    if not EIN_RE.match(ein):
        raise V.bad("Field 'ein' must be formatted NN-NNNNNNN.")
    entity_type = V.req_enum(body, "entity_type", calc.ENTITY_TYPES)
    organization_subtype = V.req_enum(body, "organization_subtype", calc.ORG_SUBTYPES)
    total_employee_count = V.req_int(body, "total_employee_count", minimum=0)
    for row in store.employers.values():
        if row["ein"] == ein:
            raise V.bad("Field 'ein' must be unique across sponsors.")
    row = store.common_fields()
    row.update({
        "legal_name": legal_name,
        "ein": ein,
        "entity_type": entity_type,
        "organization_subtype": organization_subtype,
        "total_employee_count": total_employee_count,
        "is_governmental": calc.is_governmental(entity_type),
        "is_qualified_organization": calc.is_qualified_organization(entity_type,
                                                                   organization_subtype),
    })
    store.employers[row["id"]] = row
    return envelope.created(serialize.employer(row))


@bp.get("/plan-admin/employers/<row_id>")
@endpoint(auth.ALL_ROLES)
def get_employer(row_id):
    return envelope.ok(serialize.employer(auth.employer(row_id)))


# ------------------------------------------------------------------ vendors
@bp.post("/plan-admin/vendors")
@endpoint(["SystemOperator"])
def create_vendor():
    body = V.body_of(request)
    legal_name = V.req_str(body, "legal_name")
    vendor_code = V.req_str(body, "vendor_code")
    contact_email = V.req_str(body, "contact_email")
    for row in store.vendors.values():
        if row["vendor_code"] == vendor_code:
            raise V.bad("Field 'vendor_code' must be unique across providers.")
    row = store.common_fields()
    row.update({"legal_name": legal_name, "vendor_code": vendor_code,
                "contact_email": contact_email})
    store.vendors[row["id"]] = row
    return envelope.created(serialize.vendor(row))


@bp.get("/plan-admin/vendors/<row_id>")
@endpoint(auth.ALL_ROLES)
def get_vendor(row_id):
    return envelope.ok(serialize.vendor(auth.vendor(row_id)))


# -------------------------------------------------------------------- plans
@bp.post("/plan-admin/plans")
@endpoint(["PlanSponsorAdmin"])
def create_plan():
    body = V.body_of(request)
    employer_id = V.req_str(body, "employer_id")
    plan_name = V.req_str(body, "plan_name")
    plan_type = V.req_enum(body, "plan_type", calc.PLAN_TYPES)
    plan_year = V.req_int(body, "plan_year", minimum=2000, maximum=2100)
    reported_participant_count = V.req_int(body, "reported_participant_count", minimum=0)
    permits = {}
    for key in ("permits_loans", "permits_hardship", "permits_unforeseeable_emergency",
                "permits_contract_exchanges", "permits_incoming_transfers",
                "permits_outgoing_transfers"):
        permits[key] = V.opt_bool(body, key, True)

    employer = auth.employer(employer_id)          # rung 5
    auth.require(employer_id == g.user_id)         # rung 6

    row = store.common_fields()
    row.update({
        "employer_id": employer_id,
        "plan_name": plan_name,
        "plan_type": plan_type,
        "plan_year": plan_year,
        "reported_participant_count": reported_participant_count,
        "status": "DRAFT",
        "is_small_plan": reported_participant_count < calc.SMALL_PLAN_PARTICIPANT_THRESHOLD,
        "is_governmental_457": plan_type == "PLAN_457B" and employer["is_governmental"],
        "nondiscrimination_regime": calc.nondiscrimination_regime(employer, plan_type),
        "open_correction_count": 0,
        "compliance_posture": "CLEAR",
        "projected_excess_participant_count": 0,
    })
    row.update(permits)
    store.plans[row["id"]] = row
    return envelope.created(serialize.plan(row))


@bp.get("/plan-admin/plans/<row_id>")
@endpoint(auth.ALL_ROLES)
def get_plan(row_id):
    return envelope.ok(serialize.plan(auth.plan(row_id)))


@bp.get("/plan-admin/plans")
@endpoint(auth.ALL_ROLES)
def list_plans():
    args = request.args
    limit, offset = V.pagination(args)
    employer_id = args.get("employer_id")
    plan_type = V.query_enum(args, "plan_type", calc.PLAN_TYPES)
    status = V.query_enum(args, "status", calc.PLAN_STATUSES)
    items = store.rows(store.plans)
    if employer_id:
        items = [p for p in items if p["employer_id"] == employer_id]
    if plan_type:
        items = [p for p in items if p["plan_type"] == plan_type]
    if status:
        items = [p for p in items if p["status"] == status]
    page, total = envelope.paginate(items, limit, offset)
    return envelope.listing([serialize.plan(p) for p in page], limit, offset, total)


PLAN_TRANSITIONS = {
    ("DRAFT", "ACTIVE"),
    ("ACTIVE", "FROZEN"),
    ("FROZEN", "ACTIVE"),
    ("ACTIVE", "TERMINATED"),
    ("FROZEN", "TERMINATED"),
}


@bp.post("/plan-admin/plans/<row_id>/status")
@endpoint(["PlanSponsorAdmin"])
def plan_status(row_id):
    body = V.body_of(request)
    to_status = V.req_enum(body, "to_status", calc.PLAN_STATUSES)
    plan = auth.plan(row_id)                       # rung 4
    auth.own_plan(plan)                            # rung 6
    if (plan["status"], to_status) not in PLAN_TRANSITIONS:   # rung 9
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Plan cannot move from %s to %s." % (plan["status"], to_status))
    if to_status == "TERMINATED":
        derive.recompute_plan_corrections(plan)
        if plan["open_correction_count"] != 0:
            raise ApiError("ERR_PLAN_UNDER_CORRECTION",
                           "The plan still carries an open remittance correction.")

    if to_status == "ACTIVE" and plan["status"] == "DRAFT":
        employer = store.employers.get(plan["employer_id"])
        plan["nondiscrimination_regime"] = calc.nondiscrimination_regime(employer,
                                                                        plan["plan_type"])
        plan["is_small_plan"] = (plan["reported_participant_count"]
                                 < calc.SMALL_PLAN_PARTICIPANT_THRESHOLD)
        plan["is_governmental_457"] = (plan["plan_type"] == "PLAN_457B"
                                       and employer["is_governmental"])

    plan["status"] = to_status
    store.touch(plan)

    if to_status == "TERMINATED":
        affected_participants = set()
        for election in store.rows(store.contribution_elections):
            if election["plan_id"] == plan["id"] and election["state"] in ("SUBMITTED",
                                                                          "EFFECTIVE"):
                election["state"] = "REVOKED"
                store.touch(election)
                affected_participants.add(election["participant_id"])
        for agreement in store.rows(store.isas):
            if agreement["plan_id"] == plan["id"] and agreement["status"] in ("PENDING",
                                                                             "ACTIVE",
                                                                             "SUSPENDED"):
                agreement["status"] = "TERMINATED"
                store.touch(agreement)
        for va in store.rows(store.vendor_accounts):
            if va["plan_id"] == plan["id"] and va["status"] == "OPEN":
                va["status"] = "CLOSED"
                store.touch(va)
                affected_participants.add(va["participant_id"])
        for pid in affected_participants:
            participant = store.participants.get(pid)
            if participant:
                derive.recompute_participant(participant)
        derive.recompute_plan(plan)
    return envelope.ok(serialize.plan(plan))


# -------------------------------------------------------------------- clock
@bp.post("/plan-admin/_clock/set_current_utc")
@endpoint(["SystemOperator"])
def set_clock():
    body = V.body_of(request)
    raw = V.req_str(body, "to_iso8601")
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except Exception:
        raise V.bad("Field 'to_iso8601' must be an ISO 8601 instant.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    parsed = parsed.astimezone(datetime.timezone.utc)
    previous = store.set_clock(parsed)
    return envelope.ok({"current_utc": store.fmt_ts(parsed),
                        "previous_utc": store.fmt_ts(previous)})
