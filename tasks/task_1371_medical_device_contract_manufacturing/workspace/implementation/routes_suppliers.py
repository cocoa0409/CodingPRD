"""Supplier lifecycle, quality agreements, parts, change notifications, audits
(PRD sections 3.4 and 3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from auth import SUPPLIER_QUALITY_ENGINEER, context, require_role
from domain import (active_agreement_of, hold_inflight_lots_with_part,
                    list_data, lots_containing_part, recompute_supplier_scores,
                    revalidate_protocol, serialize, serialize_supplier,
                    suspend_supplier)
from envelope import pagination_params, success
from errors import ApiError, err_stale_version, err_state
from store import DB, bump, new_entity, now
from validate import (get_body, get_or_404, opt_bool, opt_fk, opt_int,
                      req_bool, req_dt, req_enum, req_int, req_str)

bp = Blueprint("suppliers", __name__)
SQE = SUPPLIER_QUALITY_ENGINEER


def _list(kind, extra_filters=()):
    context()
    filters = [(name, request.args.get(name)) for name in extra_filters]
    items = list_data(kind, filters)
    limit, offset = pagination_params()
    page = items[offset:offset + limit]
    ser = serialize_supplier if kind == "suppliers" else serialize
    return success([ser(o) for o in page], 200, pagination={
        "limit": limit, "offset": offset, "total_count": len(items),
        "has_more": offset + len(page) < len(items),
    })


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

@bp.post("/api/suppliers")
def create_supplier():
    uid, role = context()
    require_role(role, SQE)
    data = get_body()
    supplier_code = req_str(data, "supplier_code")
    name = req_str(data, "name")
    if any(s["supplier_code"] == supplier_code for s in DB["suppliers"].values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, "supplier_code already exists")
    supplier = new_entity({
        "supplier_code": supplier_code,
        "name": name,
        "status": "PENDING_QUALIFICATION",
        "quality_score": 100,
        "quality_score_finalized": 100,
        "applied_penalty_points": 0,
        "applied_finalized_penalty_points": 0,
        "risk_tier": "LOW",
        "last_audit_completed_at": None,
    })
    DB["suppliers"][supplier["id"]] = supplier
    return success(serialize_supplier(supplier), 201)


@bp.get("/api/suppliers")
def list_suppliers():
    return _list("suppliers", ["status"])


@bp.get("/api/suppliers/<id>")
def get_supplier(id):
    context()
    return success(serialize_supplier(get_or_404("suppliers", id)), 200)


@bp.post("/api/suppliers/<id>/qualify")
def qualify_supplier(id):
    uid, role = context()
    require_role(role, SQE)
    supplier = get_or_404("suppliers", id)
    if supplier["status"] != "PENDING_QUALIFICATION":
        raise err_state()
    if active_agreement_of(id) is None:
        raise ApiError("ERR_NO_ACTIVE_QUALITY_AGREEMENT", 409,
                       "Qualification requires at least one ACTIVE quality agreement")
    supplier["status"] = "QUALIFIED"
    bump(supplier)
    return success(serialize_supplier(supplier), 200)


@bp.post("/api/suppliers/<id>/suspend")
def suspend_supplier_ep(id):
    uid, role = context()
    require_role(role, SQE)
    supplier = get_or_404("suppliers", id)
    if supplier["status"] != "QUALIFIED":
        raise err_state()
    suspend_supplier(supplier)
    return success(serialize_supplier(supplier), 200)


@bp.post("/api/suppliers/<id>/reinstate")
def reinstate_supplier(id):
    uid, role = context()
    require_role(role, SQE)
    supplier = get_or_404("suppliers", id)
    if supplier["status"] != "SUSPENDED":
        raise err_state()
    if supplier["quality_score"] < 50:
        raise ApiError("ERR_SCORE_BELOW_REINSTATE_THRESHOLD", 409,
                       "Reinstatement requires quality_score >= 50")
    if active_agreement_of(id) is None:
        raise ApiError("ERR_NO_ACTIVE_QUALITY_AGREEMENT", 409,
                       "Reinstatement requires at least one ACTIVE quality agreement")
    supplier["status"] = "QUALIFIED"
    bump(supplier)
    # hold-release on parts; lot holds must still be cleared individually
    for part in DB["parts"].values():
        if part["supplier_id"] == id and part["status"] == "ON_HOLD":
            part["status"] = "QUALIFIED"
            bump(part)
    return success(serialize_supplier(supplier), 200)


@bp.post("/api/suppliers/<id>/disqualify")
def disqualify_supplier(id):
    uid, role = context()
    require_role(role, SQE)
    supplier = get_or_404("suppliers", id)
    if supplier["status"] not in ("QUALIFIED", "SUSPENDED"):
        raise err_state()
    supplier["status"] = "DISQUALIFIED"
    bump(supplier)
    for part in DB["parts"].values():
        if part["supplier_id"] == id and part["status"] in ("QUALIFIED", "ON_HOLD"):
            part["status"] = "DISQUALIFIED"
            bump(part)
            hold_inflight_lots_with_part(part["id"])
    for a in DB["agreements"].values():
        if a["supplier_id"] == id and a["status"] == "ACTIVE":
            a["status"] = "TERMINATED"
            bump(a)
    return success(serialize_supplier(supplier), 200)


# ---------------------------------------------------------------------------
# Quality agreements
# ---------------------------------------------------------------------------

@bp.post("/api/suppliers/<supplierId>/quality-agreements")
def create_agreement(supplierId):
    uid, role = context()
    require_role(role, SQE)
    data = get_body()
    agreement_code = req_str(data, "agreement_code")
    audit_rights = req_bool(data, "audit_rights_granted")
    eff_from = req_dt(data, "effective_from")
    eff_to = req_dt(data, "effective_to")
    expected = req_int(data, "expected_supplier_version")
    audit_notice = opt_int(data, "audit_notice_days", 30)
    change_notice = opt_int(data, "change_notice_days", 90)
    supplier = get_or_404("suppliers", supplierId)
    # step 5: optimistic concurrency
    if expected != supplier["version"]:
        raise err_stale_version()
    # step 12
    if any(a["agreement_code"] == agreement_code for a in DB["agreements"].values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, "agreement_code already exists")
    # creation supersedes the supplier's existing DRAFT agreements
    for a in DB["agreements"].values():
        if a["supplier_id"] == supplierId and a["status"] == "DRAFT":
            a["status"] = "SUPERSEDED"
            bump(a)
    agreement = new_entity({
        "supplier_id": supplierId,
        "agreement_code": agreement_code,
        "audit_rights_granted": audit_rights,
        "audit_notice_days": audit_notice,
        "change_notice_days": change_notice,
        "effective_from": eff_from,
        "effective_to": eff_to,
        "status": "DRAFT",
    })
    DB["agreements"][agreement["id"]] = agreement
    # OCC side effect: the supplier's version advances by one
    bump(supplier)
    return success(serialize(agreement), 201)


@bp.get("/api/quality-agreements")
def list_agreements():
    return _list("agreements", ["supplier_id", "status"])


@bp.get("/api/quality-agreements/<id>")
def get_agreement(id):
    context()
    return success(serialize(get_or_404("agreements", id)), 200)


@bp.post("/api/quality-agreements/<id>/activate")
def activate_agreement(id):
    uid, role = context()
    require_role(role, SQE)
    agreement = get_or_404("agreements", id)
    if agreement["status"] != "DRAFT":
        raise err_state()
    # step 10: temporal window (masks the step-12 supplier-disqualified check)
    current = now()
    if not (agreement["effective_from"] <= current < agreement["effective_to"]):
        raise ApiError("ERR_AGREEMENT_NOT_IN_EFFECT", 409,
                       "Activation requires effective_from <= now < effective_to")
    supplier = DB["suppliers"].get(agreement["supplier_id"])
    if supplier is not None and supplier["status"] == "DISQUALIFIED":
        raise ApiError("ERR_SUPPLIER_DISQUALIFIED", 409,
                       "Agreement activation is forbidden while the supplier is DISQUALIFIED")
    # activating supersedes any other ACTIVE agreement of the same supplier
    for a in DB["agreements"].values():
        if a["id"] != id and a["supplier_id"] == agreement["supplier_id"] and a["status"] == "ACTIVE":
            a["status"] = "SUPERSEDED"
            bump(a)
    agreement["status"] = "ACTIVE"
    bump(agreement)
    return success(serialize(agreement), 200)


@bp.post("/api/quality-agreements/<id>/terminate")
def terminate_agreement(id):
    uid, role = context()
    require_role(role, SQE)
    agreement = get_or_404("agreements", id)
    if agreement["status"] != "ACTIVE":
        raise err_state()
    agreement["status"] = "TERMINATED"
    bump(agreement)
    supplier = DB["suppliers"].get(agreement["supplier_id"])
    if supplier is not None and supplier["status"] == "QUALIFIED" and \
            active_agreement_of(supplier["id"]) is None:
        suspend_supplier(supplier)
    return success(serialize(agreement), 200)


# ---------------------------------------------------------------------------
# Supplier parts
# ---------------------------------------------------------------------------

@bp.post("/api/suppliers/<supplierId>/parts")
def create_part(supplierId):
    uid, role = context()
    require_role(role, SQE)
    data = get_body()
    part_number = req_str(data, "part_number")
    description = req_str(data, "description")
    critical = opt_bool(data, "critical", False)
    get_or_404("suppliers", supplierId)
    if any(p["supplier_id"] == supplierId and p["part_number"] == part_number
           for p in DB["parts"].values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, "part_number already exists for this supplier")
    part = new_entity({
        "supplier_id": supplierId,
        "part_number": part_number,
        "description": description,
        "critical": critical,
        "quantity_received": 0,
        "quantity_remaining": 0,
        "quantity_committed": 0,
        "quantity_in_released_lots": 0,
        "quantity_in_scrapped_lots": 0,
        "status": "QUALIFIED",
    })
    DB["parts"][part["id"]] = part
    return success(serialize(part), 201)


@bp.get("/api/supplier-parts")
def list_parts():
    return _list("parts", ["supplier_id", "status"])


@bp.get("/api/supplier-parts/<id>")
def get_part(id):
    context()
    return success(serialize(get_or_404("parts", id)), 200)


@bp.post("/api/supplier-parts/<id>/receive")
def receive_part(id):
    uid, role = context()
    require_role(role, SQE)
    data = get_body()
    quantity = req_int(data, "quantity", min_value=1)
    part = get_or_404("parts", id)
    part["quantity_received"] += quantity
    part["quantity_remaining"] += quantity
    bump(part)
    return success(serialize(part), 200)


@bp.post("/api/supplier-parts/<id>/reinstate")
def reinstate_part(id):
    uid, role = context()
    require_role(role, SQE)
    part = get_or_404("parts", id)
    if part["status"] != "ON_HOLD":
        raise err_state()
    supplier = DB["suppliers"].get(part["supplier_id"])
    if supplier is not None and supplier["status"] in ("SUSPENDED", "DISQUALIFIED"):
        raise ApiError("ERR_SUPPLIER_NOT_CLEAR", 409,
                       "Part reinstate is blocked while the supplier is SUSPENDED or DISQUALIFIED")
    if any(s.get("supplier_part_id") == id and s["status"] in ("SUBMITTED", "UNDER_REVIEW")
           for s in DB["scns"].values()):
        raise ApiError("ERR_SCN_PENDING", 409,
                       "A change notification on this part is SUBMITTED or UNDER_REVIEW")
    part["status"] = "QUALIFIED"
    bump(part)
    return success(serialize(part), 200)


# ---------------------------------------------------------------------------
# Supplier change notifications
# ---------------------------------------------------------------------------

@bp.post("/api/suppliers/<supplierId>/change-notifications")
def create_scn(supplierId):
    uid, role = context()
    require_role(role, SQE)
    data = get_body()
    change_description = req_str(data, "change_description")
    impact_class = req_enum(data, "impact_class", ("MINOR", "MAJOR"))
    proposed = req_dt(data, "proposed_effective_date")
    part_id = opt_fk(data, "supplier_part_id")
    get_or_404("suppliers", supplierId)
    part = get_or_404("parts", part_id) if part_id is not None else None
    # step 10: change-notice window against the ACTIVE agreement
    agreement = active_agreement_of(supplierId)
    if agreement is not None:
        if proposed - now() < timedelta(days=agreement["change_notice_days"]):
            raise ApiError("ERR_CHANGE_NOTICE_WINDOW_BREACHED", 409,
                           "proposed_effective_date is inside the ACTIVE agreement's change_notice_days")
    # step 11: part must belong to the path supplier
    if part is not None and part["supplier_id"] != supplierId:
        raise ApiError("ERR_PART_NOT_OF_SUPPLIER", 422,
                       "supplier_part_id references a part of a different supplier")
    scn = new_entity({
        "supplier_id": supplierId,
        "supplier_part_id": part_id,
        "change_description": change_description,
        "impact_class": impact_class,
        "proposed_effective_date": proposed,
        "notified_at": now(),
        "status": "SUBMITTED",
    })
    DB["scns"][scn["id"]] = scn
    return success(serialize(scn), 201)


@bp.get("/api/change-notifications")
def list_scns():
    return _list("scns", ["supplier_id", "supplier_part_id", "status"])


@bp.get("/api/change-notifications/<id>")
def get_scn(id):
    context()
    return success(serialize(get_or_404("scns", id)), 200)


@bp.post("/api/change-notifications/<id>/start-review")
def start_review_scn(id):
    uid, role = context()
    require_role(role, SQE)
    scn = get_or_404("scns", id)
    if scn["status"] != "SUBMITTED":
        raise err_state()
    scn["status"] = "UNDER_REVIEW"
    bump(scn)
    return success(serialize(scn), 200)


@bp.post("/api/change-notifications/<id>/accept")
def accept_scn(id):
    uid, role = context()
    require_role(role, SQE)
    scn = get_or_404("scns", id)
    if scn["status"] != "UNDER_REVIEW":
        raise err_state()
    scn["status"] = "ACCEPTED"
    bump(scn)
    if scn["impact_class"] == "MAJOR" and scn.get("supplier_part_id"):
        part = DB["parts"].get(scn["supplier_part_id"])
        if part is not None:
            if part["status"] == "QUALIFIED":
                part["status"] = "ON_HOLD"
                bump(part)
            hold_inflight_lots_with_part(part["id"])
            if part["critical"]:
                affected_dmr_ids = {l["dmr_id"] for l in lots_containing_part(part["id"])}
                for p in DB["protocols"].values():
                    if p["status"] == "VALIDATED" and p["dmr_id"] in affected_dmr_ids:
                        revalidate_protocol(p, "SUPPLIER_CHANGE")
    return success(serialize(scn), 200)


@bp.post("/api/change-notifications/<id>/reject")
def reject_scn(id):
    uid, role = context()
    require_role(role, SQE)
    scn = get_or_404("scns", id)
    if scn["status"] != "UNDER_REVIEW":
        raise err_state()
    scn["status"] = "REJECTED"
    bump(scn)
    return success(serialize(scn), 200)


# ---------------------------------------------------------------------------
# Supplier audits
# ---------------------------------------------------------------------------

@bp.post("/api/suppliers/<supplierId>/audits")
def create_audit(supplierId):
    uid, role = context()
    require_role(role, SQE)
    data = get_body()
    start = req_dt(data, "scheduled_start")
    end = req_dt(data, "scheduled_end")
    if not start < end:
        from errors import err_validation
        raise err_validation("scheduled_start must be strictly before scheduled_end")
    get_or_404("suppliers", supplierId)
    # step 10: half-open window overlap vs other SCHEDULED audits of the supplier
    for a in DB["audits"].values():
        if a["supplier_id"] == supplierId and a["status"] == "SCHEDULED":
            if start < a["scheduled_end"] and a["scheduled_start"] < end:
                raise ApiError("ERR_AUDIT_WINDOW_OVERLAP", 409,
                               "Audit window overlaps another SCHEDULED audit of this supplier")
    # step 10: notice period of the ACTIVE agreement
    agreement = active_agreement_of(supplierId)
    if agreement is not None:
        if start - now() < timedelta(days=agreement["audit_notice_days"]):
            raise ApiError("ERR_AUDIT_NOTICE_WINDOW_BREACHED", 409,
                           "scheduled_start is inside the ACTIVE agreement's audit_notice_days")
    audit = new_entity({
        "supplier_id": supplierId,
        "scheduled_start": start,
        "scheduled_end": end,
        "status": "SCHEDULED",
        "findings_count": None,
        "major_findings_count": None,
        "penalty_points": 0,
        "completed_at": None,
    })
    DB["audits"][audit["id"]] = audit
    return success(serialize(audit), 201)


@bp.get("/api/supplier-audits")
def list_audits():
    return _list("audits", ["supplier_id", "status"])


@bp.get("/api/supplier-audits/<id>")
def get_audit(id):
    context()
    return success(serialize(get_or_404("audits", id)), 200)


@bp.post("/api/supplier-audits/<id>/complete")
def complete_audit(id):
    uid, role = context()
    require_role(role, SQE)
    data = get_body()
    findings = req_int(data, "findings_count", min_value=0)
    major = req_int(data, "major_findings_count", min_value=0)
    audit = get_or_404("audits", id)
    if audit["status"] != "SCHEDULED":
        raise err_state()
    audit["status"] = "COMPLETED"
    audit["findings_count"] = findings
    audit["major_findings_count"] = major
    audit["penalty_points"] = findings * 2 + major * 8
    audit["completed_at"] = now()
    bump(audit)
    supplier = DB["suppliers"].get(audit["supplier_id"])
    if supplier is not None:
        supplier["last_audit_completed_at"] = now()
        bump(supplier)
        recompute_supplier_scores(supplier)
        if supplier["quality_score"] < 50 and supplier["status"] == "QUALIFIED":
            suspend_supplier(supplier)
    return success(serialize(audit), 200)


@bp.post("/api/supplier-audits/<id>/cancel")
def cancel_audit(id):
    uid, role = context()
    require_role(role, SQE)
    audit = get_or_404("audits", id)
    if audit["status"] != "SCHEDULED":
        raise err_state()
    audit["status"] = "CANCELLED"
    bump(audit)
    return success(serialize(audit), 200)
