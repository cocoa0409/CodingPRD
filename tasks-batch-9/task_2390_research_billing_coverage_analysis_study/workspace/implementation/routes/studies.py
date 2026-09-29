"""Study registration, QCT determination, budget, accrual and study reads."""

from decimal import Decimal

from flask import Blueprint, request

import derive
import envelope
import lookup
import serializers
import store
import validation as v
from auth import ALL_ROLES, actor, require
from errors import ApiError

bp = Blueprint("studies", __name__, url_prefix="/research-billing")

FUNDING_SOURCES = ("INDUSTRY_SPONSORED", "FEDERALLY_FUNDED", "INVESTIGATOR_INITIATED")
IND_IDE_STATUSES = ("IND_HELD", "IDE_CATEGORY_A", "IDE_CATEGORY_B", "NONE")
QCT_BASES = ("DEEMED_IND_IDE", "DEEMED_FEDERALLY_FUNDED", "SELF_CERTIFIED",
             "NOT_QUALIFYING_DECLARED")
BASIS_TO_DETERMINATION = {
    "DEEMED_IND_IDE": "DEEMED_QUALIFYING",
    "DEEMED_FEDERALLY_FUNDED": "DEEMED_QUALIFYING",
    "SELF_CERTIFIED": "SELF_CERTIFIED_QUALIFYING",
    "NOT_QUALIFYING_DECLARED": "NON_QUALIFYING",
}
QUALIFYING = ("DEEMED_QUALIFYING", "SELF_CERTIFIED_QUALIFYING")
BUDGET_BASES = ("COVERAGE_DRIVEN", "CALENDAR_DRIVEN")


# ---------------------------------------------------------------------------
@bp.post("/studies")
@require("ResearchBillingManager")
def create_study():
    body = v.body()
    protocol_number = v.req_str(body, "protocol_number", min_len=1, max_len=40)
    title = v.req_str(body, "title")
    sponsor_name = v.req_str(body, "sponsor_name")
    funding_source = v.req_enum(body, "funding_source", FUNDING_SOURCES)
    ind_ide_status = v.req_enum(body, "ind_ide_status", IND_IDE_STATUSES)
    therapeutic_intent = v.req_bool(body, "therapeutic_intent")
    _, registry_number = v.registry_number(body)

    for existing in store.studies.values():
        if existing["protocol_number"] == protocol_number:
            raise ApiError("ERR_DUPLICATE_PROTOCOL_NUMBER")

    rec = store.base_record()
    rec.update({
        "protocol_number": protocol_number,
        "title": title,
        "sponsor_name": sponsor_name,
        "funding_source": funding_source,
        "ind_ide_status": ind_ide_status,
        "therapeutic_intent": therapeutic_intent,
        "registry_number": registry_number,
        "qct_determination": "UNDETERMINED",
        "qct_basis": None,
        "qct_determined_by_user_id": None,
        "qct_determined_at": None,
        "lifecycle_status": "DRAFT",
        "budget_status": "NOT_BUILT",
        "budget_source_analysis_id": None,
        "budget_basis": None,
        "indirect_rate_pct": None,
        "effective_indirect_rate_pct": None,
        "per_patient_subtotal_cents": 0,
        "per_patient_budget_cents": 0,
        "invoiceable_subtotal_cents": 0,
        "invoiceable_budget_cents": 0,
        "budget_built_by_user_id": None,
        "budget_executed_by_user_id": None,
    })
    store.studies[rec["id"]] = rec
    return envelope.created(serializers.study(rec))


@bp.get("/studies")
@require(*ALL_ROLES)
def list_studies():
    limit, offset = envelope.read_pagination(request.args)
    rows = store.by_created(store.studies.values())
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["lifecycle_status"] == status]
    source = request.args.get("budget_source_analysis_id")
    if source:
        rows = [r for r in rows if r["budget_source_analysis_id"] == source]
    page, total = envelope.page(rows, limit, offset)
    return envelope.listing([serializers.study(r) for r in page], limit, offset, total)


@bp.get("/studies/<study_id>")
@require(*ALL_ROLES)
def get_study(study_id):
    rec = lookup.study(study_id)
    return envelope.ok(serializers.study(rec))


# ---------------------------------------------------------------------------
@bp.post("/studies/<study_id>/qct-determination")
@require("ComplianceReviewer")
def qct_determination(study_id):
    body = v.body()
    basis = v.req_enum(body, "basis", QCT_BASES)
    supplied, registry_number = v.registry_number(body)

    rec = lookup.study(study_id)
    determination = BASIS_TO_DETERMINATION[basis]

    # priority 13 - basis supportability
    if basis == "DEEMED_IND_IDE":
        if rec["ind_ide_status"] not in ("IND_HELD", "IDE_CATEGORY_B"):
            raise ApiError("ERR_QCT_BASIS_UNSUPPORTED")
    elif basis == "DEEMED_FEDERALLY_FUNDED":
        if rec["funding_source"] != "FEDERALLY_FUNDED":
            raise ApiError("ERR_QCT_BASIS_UNSUPPORTED")
    elif basis == "SELF_CERTIFIED":
        if not rec["therapeutic_intent"]:
            raise ApiError("ERR_QCT_BASIS_UNSUPPORTED")

    # priority 14 - registry number availability
    if determination in QUALIFYING:
        if registry_number is None and not rec["registry_number"]:
            raise ApiError("ERR_REGISTRY_NUMBER_REQUIRED")

    # priority 15 - downgrade protection
    if determination == "NON_QUALIFYING":
        for analysis in derive.analyses_of(rec["id"]):
            if analysis["status"] != "APPROVED":
                continue
            if derive.analysis_counters(analysis["id"])["qct_conditional_item_count"] >= 1:
                raise ApiError("ERR_QCT_DOWNGRADE_BLOCKED")

    if supplied:
        rec["registry_number"] = registry_number
    rec["qct_determination"] = determination
    rec["qct_basis"] = basis
    rec["qct_determined_by_user_id"] = actor()
    rec["qct_determined_at"] = store.now()
    store.touch(rec)
    return envelope.ok(serializers.study(rec))


# ---------------------------------------------------------------------------
@bp.post("/studies/<study_id>/budget-build")
@require("ResearchBillingManager")
def budget_build(study_id):
    body = v.body()
    source_analysis_id = v.req_id(body, "source_analysis_id")
    basis = v.req_enum(body, "basis", BUDGET_BASES)
    requested_rate = v.req_rate(body, "indirect_rate_pct")
    expected_version = v.req_int(body, "expected_study_version")

    rec = lookup.study(study_id)
    analysis = lookup.analysis(source_analysis_id)

    if expected_version != rec["version"]:
        raise ApiError("ERR_STALE_STUDY_VERSION")

    if analysis["study_id"] != rec["id"] or analysis["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if basis == "CALENDAR_DRIVEN":
        if derive.published_calendar_for_analysis(rec["id"], source_analysis_id) is None:
            raise ApiError("ERR_NO_PUBLISHED_CALENDAR_FOR_BASIS")

    per_patient_subtotal, invoiceable_subtotal = derive.budget_subtotals(
        rec, source_analysis_id, basis)
    rate = derive.effective_indirect_rate(rec, requested_rate, per_patient_subtotal)

    rec["budget_status"] = "BUILT"
    rec["budget_source_analysis_id"] = source_analysis_id
    rec["budget_basis"] = basis
    rec["indirect_rate_pct"] = requested_rate
    rec["effective_indirect_rate_pct"] = rate
    rec["per_patient_subtotal_cents"] = per_patient_subtotal
    rec["invoiceable_subtotal_cents"] = invoiceable_subtotal
    rec["per_patient_budget_cents"] = derive.sum_then_round_total(per_patient_subtotal, rate)
    rec["invoiceable_budget_cents"] = derive.sum_then_round_total(invoiceable_subtotal, rate)
    rec["budget_built_by_user_id"] = actor()
    rec["budget_executed_by_user_id"] = None
    store.touch(rec)
    return envelope.ok(serializers.study(rec))


@bp.post("/studies/<study_id>/budget-execute")
@require("ResearchBillingManager")
def budget_execute(study_id):
    rec = lookup.study(study_id)
    if rec["budget_status"] != "BUILT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if actor() == rec["budget_built_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    rec["budget_status"] = "EXECUTED"
    rec["budget_executed_by_user_id"] = actor()
    store.touch(rec)
    return envelope.ok(serializers.study(rec))


# ---------------------------------------------------------------------------
@bp.post("/studies/<study_id>/accrual")
@require("ResearchBillingManager")
def accrual(study_id):
    body = v.body()
    target_status = v.req_enum(body, "target_status",
                               ("OPEN_TO_ACCRUAL", "CLOSED_TO_ACCRUAL"))
    rec = lookup.study(study_id)

    if target_status == "OPEN_TO_ACCRUAL":
        if rec["lifecycle_status"] != "COVERAGE_APPROVED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if rec["budget_status"] != "EXECUTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if not any(c["status"] == "PUBLISHED" for c in derive.calendars_of(rec["id"])):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if rec["qct_determination"] == "UNDETERMINED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if rec["qct_determination"] in QUALIFYING:
            registry = rec["registry_number"]
            if not registry or not v.REGISTRY_RE.match(registry):
                raise ApiError("ERR_REGISTRY_NUMBER_REQUIRED")
        rec["lifecycle_status"] = "OPEN_TO_ACCRUAL"
        store.touch(rec)
        return envelope.ok(serializers.study(rec))

    if rec["lifecycle_status"] != "OPEN_TO_ACCRUAL":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    rec["lifecycle_status"] = "CLOSED_TO_ACCRUAL"
    store.touch(rec)

    # LC-5 cascade, oldest-created first
    for subject in derive.subjects_of(rec["id"]):
        if subject["status"] not in ("SCREENING", "CONSENTED"):
            continue
        was_consented = subject["status"] == "CONSENTED"
        subject["status"] = "OFF_STUDY"
        store.touch(subject)
        if was_consented:
            for visit in derive.subject_visits_of_subject(subject["id"]):
                if visit["status"] == "SCHEDULED":
                    visit["status"] = "MISSED"
                    store.touch(visit)
    return envelope.ok(serializers.study(rec))


# ---------------------------------------------------------------------------
@bp.get("/studies/<study_id>/charge-review-summary")
@require("ComplianceReviewer", "ResearchBillingManager", "AuditLiaison")
def charge_review_summary(study_id):
    rec = lookup.study(study_id)
    ledger = derive.study_ledger(rec)
    charges = derive.charges_of(rec["id"])
    return envelope.ok({
        "study_id": rec["id"],
        "billing_hold_posture": derive.billing_hold_posture(rec),
        "unrouted_charge_count": sum(1 for c in charges if c["routing_state"] == "UNROUTED"),
        "sponsor_unbilled_cents": ledger["sponsor_unbilled_cents"],
        "sponsor_receivable_cents": ledger["sponsor_receivable_cents"],
        "payer_billed_cents": ledger["payer_billed_cents"],
        "payer_refunded_cents": ledger["payer_refunded_cents"],
        "improper_payer_exposure_cents": ledger["improper_payer_exposure_cents"],
        "delinquent_sponsor_cents": ledger["delinquent_sponsor_cents"],
        "open_finding_count": derive.open_finding_count(rec["id"]),
    })


@bp.get("/studies/<study_id>/sponsor-invoices")
@require("ResearchBillingManager", "ComplianceReviewer", "AuditLiaison")
def list_study_invoices(study_id):
    limit, offset = envelope.read_pagination(request.args)
    rec = lookup.study(study_id)
    rows = derive.invoices_of(rec["id"])
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = envelope.page(rows, limit, offset)
    return envelope.listing([serializers.invoice(r) for r in page], limit, offset, total)


@bp.get("/studies/<study_id>/amendments")
@require("ResearchBillingManager", "ComplianceReviewer", "CoverageAnalyst", "AuditLiaison")
def list_study_amendments(study_id):
    limit, offset = envelope.read_pagination(request.args)
    rec = lookup.study(study_id)
    rows = derive.amendments_of(rec["id"])
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = envelope.page(rows, limit, offset)
    return envelope.listing([serializers.amendment(r) for r in page], limit, offset, total)
