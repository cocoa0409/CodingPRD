"""Suppliers, qualifications, audits, corrective actions (PRD §3.3, §3.9)."""
from flask import Blueprint, g, request

from .envelope import (
    ALL_ROLES,
    ERR_AUDIT_ALREADY_OPEN,
    ERR_AUDIT_WINDOW_NOT_OPEN,
    ERR_DOCUMENT_PACK_INCOMPLETE,
    ERR_DUPLICATE,
    ERR_INVALID_STATE,
    ERR_OPEN_CAPAS_EXIST,
    ERR_QUALIFICATION_IN_PROGRESS,
    ERR_QUALIFICATION_SCORE_TOO_LOW,
    ERR_TEMPORAL_GUARD_VIOLATION,
    body,
    err,
    invalid,
    list_page,
    not_found,
    pagination_params,
    require_bool,
    require_int,
    require_roles,
    require_str,
    respond_object,
)
from .services import (
    RISK_TIERS,
    recompute_overdue_count,
    recompute_risk,
    schedule_next_audit,
    sources_of_supplier,
    suspend_supplier,
    supplier_has_overdue_capas,
)
from .store import (
    STORE,
    new_record,
    parse_dt,
    ser_audit,
    ser_capa,
    ser_qualification,
    ser_supplier,
    set_dt,
    set_dt_system,
    touch,
)

bp = Blueprint("suppliers", __name__)

READERS_NO_AUTHOR = (
    "ProcurementManager",
    "QualityManager",
    "SupplierQualityEngineer",
    "RegulatoryAffairs",
    "PlatformAdmin",
)


def get_supplier_or_404(supplier_id):
    sup = STORE.suppliers.get(supplier_id)
    if sup is None:
        not_found("supplier not found")
    return sup


def get_qualification_or_404(supplier_id, qualification_id):
    qual = STORE.qualifications.get(qualification_id)
    if qual is None or qual["supplier_id"] != supplier_id:
        not_found("qualification not found")
    return qual


def get_audit_or_404(supplier_id, audit_id):
    audit = STORE.audits.get(audit_id)
    if audit is None or audit["supplier_id"] != supplier_id:
        not_found("audit not found")
    return audit


def get_capa_or_404(audit_id, capa_id):
    capa = STORE.capas.get(capa_id)
    if capa is None or capa["audit_id"] != audit_id:
        not_found("corrective action not found")
    return capa


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

@bp.post("/sourcing/suppliers")
@require_roles("ProcurementManager")
def create_supplier():
    data = body()
    code = data.get("supplier_code")
    if isinstance(code, str):
        for other in STORE.suppliers.values():
            if other["supplier_code"] == code:
                err(ERR_DUPLICATE, 409, "supplier_code already exists")

    code = require_str(data, "supplier_code")
    legal_name = require_str(data, "legal_name")
    risk_tier = data.get("risk_tier")
    if risk_tier not in RISK_TIERS:
        invalid("risk_tier must be one of TIER_A, TIER_B, TIER_C")
    country = require_str(data, "country_of_operation")

    rec = new_record()
    rec.update(
        {
            "supplier_code": code,
            "legal_name": legal_name,
            "risk_tier": risk_tier,
            "country_of_operation": country,
            "status": "PROSPECT",
            "composite_risk_score": 0,
            "last_audit_closed_at": None,
            "open_overdue_capa_count": 0,
            "requalification_cycle": 0,
        }
    )
    STORE.suppliers[rec["id"]] = rec
    return respond_object(ser_supplier(rec), 201)


@bp.get("/sourcing/suppliers")
@require_roles(*ALL_ROLES)
def list_suppliers():
    limit, offset = pagination_params()
    status = request.args.get("status")
    risk_tier = request.args.get("risk_tier")
    rows = list(STORE.suppliers.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if risk_tier is not None:
        rows = [r for r in rows if r["risk_tier"] == risk_tier]
    return list_page(rows, ser_supplier, limit, offset)


@bp.get("/sourcing/suppliers/<supplier_id>")
@require_roles(*ALL_ROLES)
def get_supplier(supplier_id):
    return respond_object(ser_supplier(get_supplier_or_404(supplier_id)))


@bp.post("/sourcing/suppliers/<supplier_id>/suspend")
@require_roles("QualityManager")
def suspend_supplier_endpoint(supplier_id):
    sup = get_supplier_or_404(supplier_id)
    if sup["status"] != "QUALIFIED":
        err(ERR_INVALID_STATE, 409, "supplier is not QUALIFIED")
    suspend_supplier(sup)
    return respond_object(ser_supplier(sup))


@bp.post("/sourcing/suppliers/<supplier_id>/disqualify")
@require_roles("QualityManager")
def disqualify_supplier(supplier_id):
    sup = get_supplier_or_404(supplier_id)
    if sup["status"] != "SUSPENDED":
        err(ERR_INVALID_STATE, 409, "supplier is not SUSPENDED")
    open_capas = [
        c
        for c in STORE.capas.values()
        if c["status"] in ("OPEN", "SUBMITTED", "REJECTED")
        and STORE.audits.get(c["audit_id"]) is not None
        and STORE.audits[c["audit_id"]]["supplier_id"] == sup["id"]
    ]
    if open_capas:
        err(ERR_OPEN_CAPAS_EXIST, 409, "supplier has open corrective actions")

    sup["status"] = "DISQUALIFIED"
    touch(sup)
    affected_ingredients = set()
    for src in sources_of_supplier(sup["id"]):
        if src["status"] in ("PROVISIONAL", "ACTIVE", "SUSPENDED"):
            src["status"] = "REVOKED"
            touch(src)
            affected_ingredients.add(src["ingredient_id"])
            for decl in STORE.declarations.values():
                if decl["approved_source_id"] == src["id"] and decl["status"] == "CURRENT":
                    decl["status"] = "SUPERSEDED"
                    touch(decl)
    for ing_id in affected_ingredients:
        ing = STORE.ingredients.get(ing_id)
        if ing is not None:
            from .services import recompute_dual_source

            recompute_dual_source(ing)
    return respond_object(ser_supplier(sup))


# ---------------------------------------------------------------------------
# Qualifications
# ---------------------------------------------------------------------------

@bp.post("/sourcing/suppliers/<supplier_id>/qualifications")
@require_roles("SupplierQualityEngineer")
def create_qualification(supplier_id):
    sup = get_supplier_or_404(supplier_id)
    if sup["status"] not in ("PROSPECT", "SUSPENDED"):
        err(ERR_INVALID_STATE, 409, "supplier is not PROSPECT or SUSPENDED")
    in_progress = [
        q
        for q in STORE.qualifications.values()
        if q["supplier_id"] == sup["id"] and q["status"] in ("SUBMITTED", "UNDER_EVALUATION")
    ]
    if in_progress:
        err(ERR_QUALIFICATION_IN_PROGRESS, 409, "another qualification is in progress")

    data = body()
    score = require_int(data, "questionnaire_score")
    if score < 0 or score > 100:
        invalid("questionnaire_score must be between 0 and 100")
    doc_pack = require_bool(data, "document_pack_complete")

    was_suspended = sup["status"] == "SUSPENDED"
    sup["status"] = "IN_QUALIFICATION"
    if was_suspended:
        sup["requalification_cycle"] += 1
    touch(sup)

    rec = new_record()
    rec.update(
        {
            "supplier_id": sup["id"],
            "questionnaire_score": score,
            "document_pack_complete": doc_pack,
            "decision_note": None,
            "status": "SUBMITTED",
            "evaluated_by_user_id": None,
        }
    )
    STORE.qualifications[rec["id"]] = rec
    return respond_object(ser_qualification(rec), 201)


@bp.get("/sourcing/suppliers/<supplier_id>/qualifications")
@require_roles(*READERS_NO_AUTHOR)
def list_qualifications(supplier_id):
    get_supplier_or_404(supplier_id)
    limit, offset = pagination_params()
    status = request.args.get("status")
    rows = [q for q in STORE.qualifications.values() if q["supplier_id"] == supplier_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_page(rows, ser_qualification, limit, offset)


@bp.post("/sourcing/suppliers/<supplier_id>/qualifications/<qualification_id>/evaluate")
@require_roles("QualityManager")
def evaluate_qualification(supplier_id, qualification_id):
    get_supplier_or_404(supplier_id)
    qual = get_qualification_or_404(supplier_id, qualification_id)
    if qual["status"] != "SUBMITTED":
        err(ERR_INVALID_STATE, 409, "qualification is not SUBMITTED")
    qual["status"] = "UNDER_EVALUATION"
    touch(qual)
    return respond_object(ser_qualification(qual))


@bp.post("/sourcing/suppliers/<supplier_id>/qualifications/<qualification_id>/decide")
@require_roles("QualityManager")
def decide_qualification(supplier_id, qualification_id):
    sup = get_supplier_or_404(supplier_id)
    qual = get_qualification_or_404(supplier_id, qualification_id)
    if qual["status"] != "UNDER_EVALUATION":
        err(ERR_INVALID_STATE, 409, "qualification is not UNDER_EVALUATION")
    data = body()
    decision = data.get("decision")
    note = data.get("decision_note")

    if decision == "APPROVE":
        # Qualification gates (9 before 10) precede the decision_note shape check (23).
        if qual["questionnaire_score"] < 70:
            err(ERR_QUALIFICATION_SCORE_TOO_LOW, 422, "questionnaire_score below 70")
        if qual["document_pack_complete"] is not True:
            err(ERR_DOCUMENT_PACK_INCOMPLETE, 422, "document pack incomplete")
        if not isinstance(note, str) or note == "":
            invalid("decision_note is required")
        qual["status"] = "APPROVED"
        qual["decision_note"] = note
        qual["evaluated_by_user_id"] = g.user_id
        touch(qual)
        sup["status"] = "QUALIFIED"
        touch(sup)
        recompute_risk(sup)
        return respond_object(ser_qualification(qual))
    elif decision == "REJECT":
        if not isinstance(note, str) or note == "":
            invalid("decision_note is required")
        qual["status"] = "REJECTED"
        qual["decision_note"] = note
        qual["evaluated_by_user_id"] = g.user_id
        touch(qual)
        if sup["requalification_cycle"] == 0:
            sup["status"] = "PROSPECT"
        else:
            sup["status"] = "SUSPENDED"
        touch(sup)
        return respond_object(ser_qualification(qual))
    else:
        invalid("decision must be APPROVE or REJECT")


# ---------------------------------------------------------------------------
# Audits
# ---------------------------------------------------------------------------

@bp.post("/sourcing/suppliers/<supplier_id>/audits")
@require_roles("SupplierQualityEngineer")
def create_audit(supplier_id):
    sup = get_supplier_or_404(supplier_id)
    data = body()
    start_raw = data.get("scheduled_window_start")
    end_raw = data.get("scheduled_window_end")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        invalid("scheduled_window_start and scheduled_window_end are required")
    try:
        start_dt = parse_dt(start_raw)
    except ValueError:
        invalid("scheduled_window_start must be a valid ISO8601 timestamp")
    try:
        end_dt = parse_dt(end_raw)
    except ValueError:
        invalid("scheduled_window_end must be a valid ISO8601 timestamp")
    if end_dt <= start_dt:
        invalid("scheduled_window_end must be strictly after scheduled_window_start")

    cadence_source = (
        "ESCALATED"
        if sup["status"] == "SUSPENDED" or supplier_has_overdue_capas(sup["id"])
        else "TIER_CADENCE"
    )
    rec = new_record()
    rec.update(
        {
            "supplier_id": sup["id"],
            "audit_score": None,
            "findings_summary": None,
            "cadence_source": cadence_source,
            "status": "SCHEDULED",
            "_report_issued_dt": None,
            "_closed_dt": None,
        }
    )
    set_dt(rec, "scheduled_window_start", start_raw)
    set_dt(rec, "scheduled_window_end", end_raw)
    STORE.audits[rec["id"]] = rec
    return respond_object(ser_audit(rec), 201)


@bp.get("/sourcing/suppliers/<supplier_id>/audits")
@require_roles(*READERS_NO_AUTHOR)
def list_audits(supplier_id):
    get_supplier_or_404(supplier_id)
    limit, offset = pagination_params()
    status = request.args.get("status")
    rows = [a for a in STORE.audits.values() if a["supplier_id"] == supplier_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_page(rows, ser_audit, limit, offset)


@bp.post("/sourcing/suppliers/<supplier_id>/audits/<audit_id>/start")
@require_roles("SupplierQualityEngineer")
def start_audit(supplier_id, audit_id):
    get_supplier_or_404(supplier_id)
    audit = get_audit_or_404(supplier_id, audit_id)
    if audit["status"] != "SCHEDULED":
        err(ERR_INVALID_STATE, 409, "audit is not SCHEDULED")
    if not (audit["scheduled_window_start__dt"] <= STORE.clock < audit["scheduled_window_end__dt"]):
        err(ERR_AUDIT_WINDOW_NOT_OPEN, 422, "logical clock is outside the audit window")
    open_audits = [
        a
        for a in STORE.audits.values()
        if a["supplier_id"] == supplier_id
        and a["id"] != audit["id"]
        and a["status"] in ("IN_PROGRESS", "REPORT_ISSUED")
    ]
    if open_audits:
        err(ERR_AUDIT_ALREADY_OPEN, 409, "another audit of this supplier is open")
    audit["status"] = "IN_PROGRESS"
    touch(audit)
    return respond_object(ser_audit(audit))


@bp.post("/sourcing/suppliers/<supplier_id>/audits/<audit_id>/issue-report")
@require_roles("SupplierQualityEngineer")
def issue_report(supplier_id, audit_id):
    get_supplier_or_404(supplier_id)
    audit = get_audit_or_404(supplier_id, audit_id)
    if audit["status"] != "IN_PROGRESS":
        err(ERR_INVALID_STATE, 409, "audit is not IN_PROGRESS")
    data = body()
    score = data.get("audit_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        invalid("audit_score is required and must be an integer in [0, 100]")
    if isinstance(score, float) and not score.is_integer():
        invalid("audit_score must be an integer in [0, 100]")
    score = int(score)
    if score < 0 or score > 100:
        invalid("audit_score must be in [0, 100]")
    summary = data.get("findings_summary")
    if not isinstance(summary, str) or summary == "":
        invalid("findings_summary is required")
    audit["audit_score"] = score
    audit["findings_summary"] = summary
    audit["status"] = "REPORT_ISSUED"
    audit["_report_issued_dt"] = STORE.clock
    touch(audit)
    return respond_object(ser_audit(audit))


@bp.post("/sourcing/suppliers/<supplier_id>/audits/<audit_id>/close")
@require_roles("QualityManager")
def close_audit(supplier_id, audit_id):
    sup = get_supplier_or_404(supplier_id)
    audit = get_audit_or_404(supplier_id, audit_id)
    if audit["status"] != "REPORT_ISSUED":
        err(ERR_INVALID_STATE, 409, "audit is not REPORT_ISSUED")
    open_capas = [
        c
        for c in STORE.capas.values()
        if c["audit_id"] == audit["id"] and c["status"] != "VERIFIED"
    ]
    if open_capas:
        err(ERR_OPEN_CAPAS_EXIST, 409, "audit has corrective actions not VERIFIED")

    audit["status"] = "CLOSED"
    audit["_closed_dt"] = STORE.clock
    touch(audit)
    set_dt_system(sup, "last_audit_closed_at", STORE.clock)
    touch(sup)
    recompute_risk(sup)  # audit component = 100 - audit_score; may auto-suspend
    schedule_next_audit(sup)
    return respond_object(ser_audit(audit))


@bp.post("/sourcing/suppliers/<supplier_id>/audits/<audit_id>/cancel")
@require_roles("QualityManager")
def cancel_audit(supplier_id, audit_id):
    get_supplier_or_404(supplier_id)
    audit = get_audit_or_404(supplier_id, audit_id)
    if audit["status"] != "SCHEDULED":
        err(ERR_INVALID_STATE, 409, "audit is not SCHEDULED")
    audit["status"] = "CANCELLED"
    touch(audit)
    return respond_object(ser_audit(audit))


# ---------------------------------------------------------------------------
# Corrective actions
# ---------------------------------------------------------------------------

@bp.post("/sourcing/suppliers/<supplier_id>/audits/<audit_id>/corrective-actions")
@require_roles("QualityManager")
def create_capa(supplier_id, audit_id):
    sup = get_supplier_or_404(supplier_id)
    audit = get_audit_or_404(supplier_id, audit_id)
    if audit["status"] != "REPORT_ISSUED":
        err(ERR_INVALID_STATE, 409, "audit is not REPORT_ISSUED")
    data = body()

    # Temporal guard (8): due_date strictly after the audit report-issue time.
    due_raw = data.get("due_date")
    if isinstance(due_raw, str):
        try:
            due_dt = parse_dt(due_raw)
        except ValueError:
            invalid("due_date must be a valid ISO8601 timestamp")
        else:
            if audit["_report_issued_dt"] is not None and due_dt <= audit["_report_issued_dt"]:
                err(
                    ERR_TEMPORAL_GUARD_VIOLATION,
                    422,
                    "due_date must be strictly after the audit report issue time",
                )

    description = data.get("description")
    if not isinstance(description, str) or len(description) < 10:
        invalid("description must be at least 10 characters")
    if not isinstance(due_raw, str):
        invalid("due_date is required and must be an ISO8601 string")

    rec = new_record()
    rec.update(
        {
            "audit_id": audit["id"],
            "description": description,
            "response_text": None,
            "verification_note": None,
            "status": "OPEN",
        }
    )
    set_dt(rec, "due_date", due_raw)
    STORE.capas[rec["id"]] = rec
    recompute_overdue_count(sup)
    return respond_object(ser_capa(rec), 201)


@bp.get("/sourcing/suppliers/<supplier_id>/audits/<audit_id>/corrective-actions")
@require_roles(*READERS_NO_AUTHOR)
def list_capas(supplier_id, audit_id):
    get_supplier_or_404(supplier_id)
    audit = get_audit_or_404(supplier_id, audit_id)
    limit, offset = pagination_params()
    status = request.args.get("status")
    rows = [c for c in STORE.capas.values() if c["audit_id"] == audit["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_page(rows, ser_capa, limit, offset)


@bp.post(
    "/sourcing/suppliers/<supplier_id>/audits/<audit_id>/corrective-actions/<capa_id>/submit-response"
)
@require_roles("SupplierQualityEngineer")
def submit_capa_response(supplier_id, audit_id, capa_id):
    get_supplier_or_404(supplier_id)
    audit = get_audit_or_404(supplier_id, audit_id)
    capa = get_capa_or_404(audit["id"], capa_id)
    if capa["status"] not in ("OPEN", "REJECTED"):
        err(ERR_INVALID_STATE, 409, "CAPA is not OPEN or REJECTED")
    data = body()
    response_text = data.get("response_text")
    if not isinstance(response_text, str) or response_text == "":
        invalid("response_text is required")
    capa["response_text"] = response_text
    capa["status"] = "SUBMITTED"
    touch(capa)
    return respond_object(ser_capa(capa))


@bp.post(
    "/sourcing/suppliers/<supplier_id>/audits/<audit_id>/corrective-actions/<capa_id>/verify"
)
@require_roles("QualityManager")
def verify_capa(supplier_id, audit_id, capa_id):
    sup = get_supplier_or_404(supplier_id)
    audit = get_audit_or_404(supplier_id, audit_id)
    capa = get_capa_or_404(audit["id"], capa_id)
    if capa["status"] != "SUBMITTED":
        err(ERR_INVALID_STATE, 409, "CAPA is not SUBMITTED")
    data = body()
    note = data.get("verification_note")
    if not isinstance(note, str) or len(note) < 10:
        invalid("verification_note must be at least 10 characters")
    capa["verification_note"] = note
    capa["status"] = "VERIFIED"
    touch(capa)
    recompute_risk(sup)  # recomputes overdue count and composite risk
    return respond_object(ser_capa(capa))


@bp.post(
    "/sourcing/suppliers/<supplier_id>/audits/<audit_id>/corrective-actions/<capa_id>/reject-response"
)
@require_roles("QualityManager")
def reject_capa_response(supplier_id, audit_id, capa_id):
    sup = get_supplier_or_404(supplier_id)
    audit = get_audit_or_404(supplier_id, audit_id)
    capa = get_capa_or_404(audit["id"], capa_id)
    if capa["status"] != "SUBMITTED":
        err(ERR_INVALID_STATE, 409, "CAPA is not SUBMITTED")
    data = body()
    note = data.get("verification_note")
    if not isinstance(note, str) or len(note) < 10:
        invalid("verification_note must be at least 10 characters")
    capa["verification_note"] = note
    capa["status"] = "REJECTED"
    touch(capa)
    recompute_overdue_count(sup)  # PRD §3.9: rejection recomputes the count only
    return respond_object(ser_capa(capa))
