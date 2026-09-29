"""Reference registers: registrars, domains, complainants, the panelist roster,
the logical clock and the deadline sweep."""

from datetime import timedelta

from flask import Blueprint, request

import db
import response
import validate as v
from errors import ApiError
from middleware import auth, body
from services import calc, logic

bp = Blueprint("registry", __name__)


# ------------------------------------------------------------------ registrars
@bp.post("/udrp/registrars")
def create_registrar():
    auth("ProviderAdmin")
    payload = body()
    name = v.req_str(payload, "name", 1, 255)
    iana_id = v.req_str(payload, "iana_id", 1, 16)
    contact_email = v.req_str(payload, "contact_email", 1, 320)
    hours = v.opt_int(payload, "verification_response_hours", 1, 336, 48)
    lock_sla = v.opt_int(payload, "lock_sla_hours", 1, 336, 24)
    if any(r["iana_id"] == iana_id for r in db.registrars.values()):
        v.bad("iana_id must be unique across all registrars.")
    row = db.base_row(
        name=name,
        iana_id=iana_id,
        contact_email=contact_email,
        verification_response_hours=hours,
        lock_sla_hours=lock_sla,
        status="ACTIVE",
        overdue_verification_count=0,
    )
    db.registrars[row["id"]] = row
    return response.ok(db.public(row), 201)


@bp.get("/udrp/registrars/<registrar_id>")
def read_registrar(registrar_id):
    auth("ProviderAdmin", "CaseManager", "RegistrarAgent")
    row = logic.resource_or_404(db.registrars, registrar_id)
    return response.ok(db.public(row))


@bp.post("/udrp/registrars/<registrar_id>/status")
def set_registrar_status(registrar_id):
    auth("ProviderAdmin")
    row = logic.resource_or_404(db.registrars, registrar_id)
    payload = body()
    status = v.req_enum(payload, "status", ("ACTIVE", "SUSPENDED"))
    row["status"] = status
    db.touch(row)
    return response.ok(db.public(row))


# --------------------------------------------------------------------- domains
@bp.post("/udrp/domains")
def create_domain():
    auth("ProviderAdmin", "CaseManager")
    payload = body()
    if v.present(payload, "registrar_id"):
        logic.resource_or_404(db.registrars, payload["registrar_id"])
    registrar_id = v.req_str(payload, "registrar_id")
    domain_name = v.req_str(payload, "domain_name", 4, 253).lower()
    registrant_name = v.req_str(payload, "registrant_name_public", 1, 255)
    registrant_email = v.req_str(payload, "registrant_email_public", 1, 320)
    registration_raw, _ = v.req_dt(payload, "registration_date")
    expiry_raw, _ = v.req_dt(payload, "expiry_date")
    if any(r["domain_name"] == domain_name for r in db.domains.values()):
        raise ApiError("ERR_DUPLICATE_DOMAIN_NAME")
    row = db.base_row(
        domain_name=domain_name,
        registrar_id=registrar_id,
        registrant_name_public=registrant_name,
        registrant_email_public=registrant_email,
        registration_date=registration_raw,
        expiry_date=expiry_raw,
        lock_status="UNLOCKED",
        locked_at=None,
        executed_at=None,
    )
    db.domains[row["id"]] = row
    return response.ok(db.public(row), 201)


@bp.get("/udrp/domains/<domain_id>")
def read_domain(domain_id):
    auth("ProviderAdmin", "CaseManager", "RegistrarAgent", "Complainant",
         "Respondent", "Panelist")
    return response.ok(db.public(logic.domain_or_404(domain_id)))


@bp.post("/udrp/domains/<domain_id>/lock")
def set_domain_lock(domain_id):
    auth("RegistrarAgent", "ProviderAdmin")
    row = logic.domain_or_404(domain_id)
    payload = body()
    lock_status = v.req_enum(payload, "lock_status", ("UNLOCKED", "LOCKED"))
    if row["lock_status"] in ("TRANSFER_EXECUTED", "CANCELLATION_EXECUTED"):
        v.bad("The domain's lock state is terminal and may not be changed.")
    row["lock_status"] = lock_status
    row["locked_at"] = db.now_str() if lock_status == "LOCKED" else None
    db.touch(row)
    return response.ok(db.public(row))


@bp.get("/udrp/domains")
def list_domains():
    auth("ProviderAdmin", "CaseManager", "RegistrarAgent")
    limit, offset = v.pagination(request.args)
    registrar_id = request.args.get("registrar_id")
    lock_status = v.query_enum(request.args, "lock_status",
                               ("UNLOCKED", "LOCKED", "TRANSFER_EXECUTED",
                                "CANCELLATION_EXECUTED"))
    rows = db.ordered(db.domains)
    if registrar_id:
        rows = [r for r in rows if r["registrar_id"] == registrar_id]
    if lock_status:
        rows = [r for r in rows if r["lock_status"] == lock_status]
    window, total = response.paginate(rows, limit, offset)
    return response.ok_list([db.public(r) for r in window], limit, offset, total)


# ---------------------------------------------------------------- complainants
@bp.post("/udrp/complainants")
def create_complainant():
    auth("ProviderAdmin", "CaseManager")
    payload = body()
    row = db.base_row(
        legal_name=v.req_str(payload, "legal_name", 1, 255),
        country_code=v.req_country(payload, "country_code"),
        email=v.req_str(payload, "email", 1, 320),
        open_case_count=0,
        adverse_rdnh_findings=0,
    )
    db.complainants[row["id"]] = row
    return response.ok(db.public(row), 201)


@bp.get("/udrp/complainants/<complainant_id>")
def read_complainant(complainant_id):
    auth("ProviderAdmin", "CaseManager", "Complainant")
    row = logic.resource_or_404(db.complainants, complainant_id)
    return response.ok(db.public(row))


# ------------------------------------------------------------------- panelists
@bp.post("/udrp/panelists")
def create_panelist():
    auth("ProviderAdmin")
    payload = body()
    full_name = v.req_str(payload, "full_name", 1, 255)
    nationality = v.req_country(payload, "nationality_code")
    roster_raw, _ = v.req_dt(payload, "roster_admitted_at")
    firm_name = v.opt_str(payload, "firm_name", 1, 255)
    specializations = v.opt_str_list(payload, "specializations", 0, None,
                                     distinct=False)
    ceiling = v.opt_int(payload, "max_overlapping_engagements", 1, 20, 5)
    row = db.base_row(
        full_name=full_name,
        nationality_code=nationality,
        firm_name=firm_name,
        specializations=specializations,
        roster_admitted_at=roster_raw,
        max_overlapping_engagements=ceiling,
        status="AVAILABLE",
        unavailable_from=None,
        unavailable_to=None,
        active_case_load=0,
    )
    db.panelists[row["id"]] = row
    return response.ok(db.public(row), 201)


@bp.get("/udrp/panelists/<panelist_id>")
def read_panelist(panelist_id):
    auth("ProviderAdmin", "CaseManager", "Panelist")
    return response.ok(db.public(logic.panelist_or_404(panelist_id)))


@bp.post("/udrp/panelists/<panelist_id>/availability")
def set_availability(panelist_id):
    auth("ProviderAdmin", "Panelist")
    row = logic.panelist_or_404(panelist_id)
    payload = body()
    status = v.opt_enum(payload, "status", ("AVAILABLE", "UNAVAILABLE", "SUSPENDED"))
    ceiling = v.opt_int(payload, "max_overlapping_engagements", 1, 20)
    clears_blackout = "unavailable_from" in payload and payload["unavailable_from"] is None
    from_raw, _ = v.opt_dt(payload, "unavailable_from")
    to_raw, _ = v.opt_dt(payload, "unavailable_to")
    if status is not None:
        row["status"] = status
    if ceiling is not None:
        row["max_overlapping_engagements"] = ceiling
    if clears_blackout:
        # Supplying unavailable_from as null clears the declared blackout entirely.
        row["unavailable_from"] = None
        row["unavailable_to"] = None
    else:
        if from_raw is not None:
            row["unavailable_from"] = from_raw
        if to_raw is not None:
            row["unavailable_to"] = to_raw
        if "unavailable_to" in payload and payload["unavailable_to"] is None:
            row["unavailable_to"] = None
    db.touch(row)
    return response.ok(db.public(row))


# ---------------------------------------------------- logical clock and sweep
@bp.post("/udrp/_clock/set_current_utc")
def set_clock():
    auth("ProviderAdmin")
    payload = body()
    _, moment = v.req_dt(payload, "current_utc")
    db.set_now(moment)
    return response.ok({})


@bp.post("/udrp/_ops/deadline-sweep")
def deadline_sweep():
    auth("ProviderAdmin")
    body()
    clock = db.now()
    counters = {
        "expired_notice_count": 0,
        "overdue_verification_count": 0,
        "defaulted_case_count": 0,
        "closed_case_count": 0,
    }

    # Stage 1 -- uncured deficiency notices expire and close their case in full.
    for notice in db.ordered(db.notices):
        if notice["status"] != "OPEN":
            continue
        if clock <= db.parse_dt(notice["correction_deadline_at"]):
            continue
        notice["status"] = "EXPIRED"
        db.touch(notice)
        counters["expired_notice_count"] += 1
        case = db.cases.get(notice["case_id"])
        if case is not None and case["status"] == "DEFICIENT":
            logic.close_case(case, "ADMIN_CLOSED",
                             refund_pct=calc.REFUND_PCT_PRE_CLEARANCE,
                             refund_reference="AUTO-CLOSE-REFUND")
            counters["closed_case_count"] += 1

    # Stage 2 -- registrar verifications past their due instant go overdue.
    for verification in db.ordered(db.verifications):
        if verification["status"] != "REQUESTED":
            continue
        if clock <= db.parse_dt(verification["due_at"]):
            continue
        logic.mark_verification_overdue(verification)
        counters["overdue_verification_count"] += 1

    # Stage 3 -- commenced cases whose window and grace have lapsed default.
    for case in db.ordered(db.cases):
        if case["status"] != "COMMENCED" or not case.get("response_due_at"):
            continue
        if logic.case_response(case["id"]) is not None:
            continue
        cutoff = calc.default_cutoff(db.parse_dt(case["response_due_at"]))
        if clock <= cutoff:
            continue
        case["status"] = "DEFAULT"
        case["default_recorded"] = True
        db.touch(case)
        counters["defaulted_case_count"] += 1

    return response.ok(counters)
