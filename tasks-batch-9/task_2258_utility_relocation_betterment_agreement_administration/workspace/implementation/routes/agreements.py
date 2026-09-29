"""Reimbursement agreements, cost documentation, audit findings and contractor
delay claims (PRD sections 3.8, 3.9)."""
from flask import Blueprint

import calc
import db as store
import enums
import serializers as ser
import services
from errors import ApiError
from middleware import authenticate, check_owner_scope, must_get
from response import created, ok
from validation import (body_json, field_datetime, field_enum, field_id, field_int, field_str)

bp = Blueprint("agreements", __name__)


def _project_of_agreement(agreement):
    return store.db.projects.get(agreement["project_id"])


def _owner_of_agreement(agreement):
    return store.db.owners.get(agreement["owner_id"])


# ========================================================== agreements =======

@bp.post("/uro/agreements")
def create_agreement():
    authenticate(("AgreementOfficer",))
    body = body_json()
    plan_id = field_id(body, "plan_id")
    expected_version = field_int(body, "expected_plan_version", minimum=0)
    ceiling = field_int(body, "not_to_exceed_cents", exclusive_minimum=0)

    plan = must_get("plan", plan_id)
    conflict = store.conflict_of_plan(plan)
    facility = store.facility_of_conflict(conflict) if conflict is not None else None
    owner = store.db.owners.get(facility["owner_id"]) if facility is not None else None
    project = store.project_of_conflict(conflict) if conflict is not None else None
    services.guard_project_open(project)

    if expected_version != plan["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "The supplied expected_plan_version does not match the plan's current "
                       "version.")

    floor = calc.indirect_loaded_estimate(plan, owner)
    if ceiling < floor:
        raise ApiError("ERR_NOT_TO_EXCEED_TOO_LOW",
                       "not_to_exceed_cents must be at least %d cents." % floor)

    rec = store.base_record()
    rec.update({
        "plan_id": plan_id,
        "project_id": project["id"],
        "owner_id": owner["id"],
        "not_to_exceed_cents": ceiling,
        "cost_basis": "ESTIMATE_BASIS",
        "eligible_cost_cents": 0,
        "indirect_cost_cents": 0,
        "betterment_credit_cents": 0,
        "net_allowable_cents": 0,
        "participation_tier_pct": 0,
        "state_share_cents": 0,
        "owner_share_cents": 0,
        "as_built_reference": None,
        "executed_by_user_id": None,
        "execution_status": "DRAFT",
        "settlement_status": "NOT_STARTED",
    })
    store.db.agreements[rec["id"]] = rec
    calc.apply_settlement_figures(rec, "ESTIMATE_BASIS")

    services.touch(plan)          # the OCC parent
    return created(ser.agreement_out(rec))


@bp.post("/uro/agreements/<agreement_id>/circulate")
def circulate_agreement(agreement_id):
    authenticate(("AgreementOfficer",))
    body_json()
    agreement = must_get("agreement", agreement_id)
    if agreement["execution_status"] != "DRAFT":
        raise ApiError("ERR_AGREEMENT_NOT_EXECUTABLE",
                       "Only a DRAFT agreement may be circulated for signature.")
    services.guard_project_open(_project_of_agreement(agreement))

    agreement["execution_status"] = "PENDING_OWNER_SIGNATURE"
    services.touch(agreement)
    return ok(ser.agreement_out(agreement))


@bp.post("/uro/agreements/<agreement_id>/execute")
def execute_agreement(agreement_id):
    user_id, _role = authenticate(("AgreementOfficer",))
    body_json()
    agreement = must_get("agreement", agreement_id)
    if agreement["execution_status"] != "PENDING_OWNER_SIGNATURE":
        raise ApiError("ERR_AGREEMENT_NOT_EXECUTABLE",
                       "Only an agreement pending owner signature may be executed.")

    project = _project_of_agreement(agreement)
    services.guard_project_open(project)
    services.guard_posture(project)
    services.guard_owner_hold(_owner_of_agreement(agreement))

    ledger = calc.project_committed_ledger(project)
    if ledger + agreement["state_share_cents"] > project["reimbursement_authority_cents"]:
        raise ApiError("ERR_AUTHORITY_EXCEEDED",
                       "Executing this agreement would exceed the project's reimbursement "
                       "authority.")

    agreement["execution_status"] = "EXECUTED"
    agreement["executed_by_user_id"] = user_id
    services.touch(agreement)
    services.recompute_project(project)
    return ok(ser.agreement_out(agreement))


@bp.post("/uro/agreements/<agreement_id>/void")
def void_agreement(agreement_id):
    authenticate(("AgreementOfficer",))
    body = body_json()
    field_str(body, "void_reason", min_len=1, max_len=500)

    agreement = must_get("agreement", agreement_id)
    if agreement["execution_status"] == "VOIDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The agreement is already voided.")
    if agreement["settlement_status"] == "SETTLED":
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID", "A settled agreement cannot be voided.")

    project = _project_of_agreement(agreement)
    services.guard_project_open(project)

    agreement["execution_status"] = "VOIDED"
    agreement["settlement_status"] = "VOIDED_OUT"
    services.touch(agreement)
    services.recompute_project(project)
    return ok(ser.agreement_out(agreement))


@bp.post("/uro/agreements/<agreement_id>/open-final-billing")
def open_final_billing(agreement_id):
    authenticate(("AgreementOfficer",))
    body_json()
    agreement = must_get("agreement", agreement_id)
    if agreement["execution_status"] != "EXECUTED":
        raise ApiError("ERR_AGREEMENT_NOT_EXECUTABLE",
                       "Final billing may only be opened on an executed agreement.")
    if agreement["settlement_status"] != "NOT_STARTED":
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID",
                       "The agreement's settlement has already started.")
    services.guard_project_open(_project_of_agreement(agreement))

    agreement["settlement_status"] = "PENDING_FINAL_INVOICE"
    services.touch(agreement)
    return ok(ser.agreement_out(agreement))


@bp.post("/uro/agreements/<agreement_id>/final-settlement")
def final_settlement(agreement_id):
    authenticate(("AgreementOfficer",))
    body = body_json()
    as_built = field_str(body, "as_built_reference", min_len=1, max_len=120)

    agreement = must_get("agreement", agreement_id)
    if agreement["execution_status"] == "VOIDED":
        raise ApiError("ERR_AGREEMENT_NOT_EXECUTABLE",
                       "A voided agreement accepts no settlement action.")
    if agreement["settlement_status"] != "PENDING_FINAL_INVOICE":
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID",
                       "Only an agreement in final billing may be settled.")

    project = _project_of_agreement(agreement)
    services.guard_project_open(project)
    services.guard_owner_hold(_owner_of_agreement(agreement))

    if any(f["status"] == "OPEN" for f in store.findings_of_agreement(agreement_id)):
        raise ApiError("ERR_OPEN_AUDIT_FINDING",
                       "An audit finding of the agreement is still OPEN.")

    eligible = [d for d in store.documents_of_agreement(agreement_id)
                if d["review_status"] == "ACCEPTED"
                and d["doc_type"] not in ("CREDIT_SALVAGE", "INDIRECT")]
    if not eligible:
        raise ApiError("ERR_NO_ELIGIBLE_COST_DOCUMENTATION",
                       "No accepted cost document of an eligible type exists.")

    figures, _included, excluded = calc.settlement_figures(agreement, "ACTUAL_BASIS")
    old_share = agreement["state_share_cents"] if agreement["execution_status"] == "EXECUTED" else 0
    new_share = figures["state_share_cents"] if agreement["execution_status"] == "EXECUTED" else 0
    ledger = calc.project_committed_ledger(project)
    if ledger + (new_share - old_share) > project["reimbursement_authority_cents"]:
        raise ApiError("ERR_AUTHORITY_EXCEEDED",
                       "The settlement revision would exceed the project's reimbursement "
                       "authority.")

    agreement["cost_basis"] = "ACTUAL_BASIS"
    agreement.update(figures)
    agreement["as_built_reference"] = as_built
    agreement["settlement_status"] = "SETTLED"
    services.touch(agreement)

    for document in excluded:
        document["review_status"] = "DISALLOWED"
        document["exclusion_reason"] = "EXCEEDS_NOT_TO_EXCEED_CAP"
        document["disallowed_amount_cents"] = document["amount_cents"]
        services.touch(document)

    services.recompute_project(project)
    return ok(ser.agreement_out(agreement))


# ======================================================= cost documents ======

@bp.post("/uro/cost-documents")
def create_document():
    authenticate(("UtilityOwnerRep",))
    body = body_json()
    agreement_id = field_id(body, "agreement_id")
    doc_type = field_enum(body, "doc_type", enums.DOC_TYPE)
    amount = field_int(body, "amount_cents", exclusive_minimum=0)
    incurred_raw, incurred_dt = field_datetime(body, "incurred_on")
    support = field_str(body, "support_reference", min_len=0, max_len=120, allow_blank=True)

    agreement = must_get("agreement", agreement_id)
    check_owner_scope(agreement["owner_id"])

    if agreement["settlement_status"] != "PENDING_FINAL_INVOICE":
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID",
                       "Cost documents may only be submitted while the agreement is in final "
                       "billing.")
    services.guard_project_open(_project_of_agreement(agreement))

    rec = store.base_record()
    rec.update({
        "agreement_id": agreement_id,
        "doc_type": doc_type,
        "amount_cents": amount,
        "incurred_on": incurred_raw,
        "_incurred_on_dt": incurred_dt,
        "support_reference": support,
        "disallowed_amount_cents": 0,
        "exclusion_reason": None,
        "review_status": "SUBMITTED",
    })
    store.db.documents[rec["id"]] = rec
    return created(ser.document_out(rec))


@bp.post("/uro/cost-documents/<document_id>/review")
def review_document(document_id):
    authenticate(("AgreementOfficer",))
    body = body_json()
    disposition = field_enum(body, "disposition", enums.DOCUMENT_DISPOSITION)
    exclusion_reason = field_enum(body, "exclusion_reason", enums.MANUAL_EXCLUSION_REASON,
                                  required=False)

    document = must_get("document", document_id)
    if document["review_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SUBMITTED cost document may be dispositioned.")

    agreement = store.db.agreements.get(document["agreement_id"])
    if agreement is None or agreement["settlement_status"] != "PENDING_FINAL_INVOICE":
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID",
                       "The parent agreement must be in final billing to disposition a "
                       "document.")
    services.guard_project_open(_project_of_agreement(agreement))

    if disposition == "ACCEPT":
        document["review_status"] = "ACCEPTED"
        document["disallowed_amount_cents"] = 0
        document["exclusion_reason"] = None
    else:
        document["review_status"] = "DISALLOWED"
        document["disallowed_amount_cents"] = document["amount_cents"]
        document["exclusion_reason"] = exclusion_reason
    services.touch(document)

    calc.apply_settlement_figures(agreement)
    services.touch(agreement)
    return ok(ser.document_out(document))


# ======================================================= audit findings ======

@bp.post("/uro/audit-findings")
def create_finding():
    user_id, _role = authenticate(("ExternalAuditor",))
    body = body_json()
    agreement_id = field_id(body, "agreement_id")
    finding_type = field_enum(body, "finding_type", enums.FINDING_TYPE)
    questioned = field_int(body, "questioned_cost_cents", exclusive_minimum=0)

    agreement = must_get("agreement", agreement_id)
    if agreement["executed_by_user_id"] is not None \
            and agreement["executed_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The officer who executed this agreement may not audit it.")
    services.guard_project_open(_project_of_agreement(agreement))

    rec = store.base_record()
    rec.update({
        "agreement_id": agreement_id,
        "finding_type": finding_type,
        "questioned_cost_cents": questioned,
        "auditor_user_id": user_id,
        "disposition": None,
        "status": "OPEN",
    })
    store.db.findings[rec["id"]] = rec

    if agreement["settlement_status"] == "PENDING_FINAL_INVOICE":
        agreement["settlement_status"] = "AUDIT_IN_PROGRESS"
        services.touch(agreement)
    return created(ser.finding_out(rec))


@bp.post("/uro/audit-findings/<finding_id>/resolve")
def resolve_finding(finding_id):
    authenticate(("ExternalAuditor",))
    body = body_json()
    disposition = field_enum(body, "disposition", enums.FINDING_DISPOSITION)

    finding = must_get("finding", finding_id)
    if finding["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an OPEN audit finding may be resolved.")
    agreement = store.db.agreements.get(finding["agreement_id"])
    services.guard_project_open(
        None if agreement is None else _project_of_agreement(agreement))

    finding["status"] = "RESOLVED"
    finding["disposition"] = disposition
    services.touch(finding)

    if agreement is not None and agreement["settlement_status"] == "AUDIT_IN_PROGRESS":
        still_open = [f for f in store.findings_of_agreement(agreement["id"])
                      if f["status"] == "OPEN"]
        if not still_open:
            agreement["settlement_status"] = "PENDING_FINAL_INVOICE"
            services.touch(agreement)
    return ok(ser.finding_out(finding))


# ========================================================= delay claims ======

@bp.post("/uro/delay-claims")
def create_claim():
    authenticate(("ConstructionEngineer",))
    body = body_json()
    project_id = field_id(body, "project_id")
    commitment_id = field_id(body, "commitment_id")
    contractor = field_str(body, "contractor_name", min_len=1, max_len=160)
    claimed_days = field_int(body, "claimed_days", exclusive_minimum=0)
    claimed_amount = field_int(body, "claimed_amount_cents", exclusive_minimum=0)

    project = must_get("project", project_id)
    must_get("commitment", commitment_id)
    services.guard_project_open(project)

    rec = store.base_record()
    rec.update({
        "project_id": project_id,
        "commitment_id": commitment_id,
        "contractor_name": contractor,
        "claimed_days": claimed_days,
        "claimed_amount_cents": claimed_amount,
        "delay_cause": None,
        "compensable_days": 0,
        "daily_rate_cents": 0,
        "allocated_to_owner_cents": 0,
        "allocated_to_state_cents": 0,
        "status": "SUBMITTED",
    })
    store.db.claims[rec["id"]] = rec
    return created(ser.claim_out(rec))


@bp.post("/uro/delay-claims/<claim_id>/analyze")
def analyze_claim(claim_id):
    authenticate(("ConstructionEngineer",))
    body = body_json()
    delay_cause = field_enum(body, "delay_cause", enums.DELAY_CAUSE)

    claim = must_get("claim", claim_id)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SUBMITTED delay claim may be analysed.")
    commitment = store.db.commitments.get(claim["commitment_id"])
    if commitment is None or commitment["status"] not in ("COMPLETE", "BREACHED"):
        raise ApiError("ERR_COMMITMENT_STATE_INVALID",
                       "The referenced commitment must be COMPLETE or BREACHED.")

    project = store.db.projects.get(claim["project_id"])
    services.guard_project_open(project)

    claim["delay_cause"] = delay_cause
    claim["compensable_days"] = calc.claim_compensable_days(commitment["late_days"],
                                                           claim["claimed_days"])
    claim["daily_rate_cents"] = calc.claim_daily_rate(claim["claimed_amount_cents"],
                                                      claim["claimed_days"],
                                                      project["contract_daily_overhead_cents"])
    claim["status"] = "UNDER_ANALYSIS"
    services.touch(claim)
    return ok(ser.claim_out(claim))


@bp.post("/uro/delay-claims/<claim_id>/allocate")
def allocate_claim(claim_id):
    authenticate(("ConstructionEngineer",))
    body_json()
    claim = must_get("claim", claim_id)
    if claim["status"] != "UNDER_ANALYSIS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an analysed delay claim may be allocated.")
    project = store.db.projects.get(claim["project_id"])
    services.guard_project_open(project)

    if claim["compensable_days"] <= 0:
        raise ApiError("ERR_DELAY_NOT_COMPENSABLE",
                       "The analysed claim has no compensable days.")

    to_owner, to_state = calc.claim_allocation(claim["compensable_days"],
                                               claim["daily_rate_cents"],
                                               claim["delay_cause"])
    claim["allocated_to_owner_cents"] = to_owner
    claim["allocated_to_state_cents"] = to_state
    claim["status"] = "ALLOCATED"
    services.touch(claim)

    commitment = store.db.commitments.get(claim["commitment_id"])
    if commitment is not None:
        services.recompute_owner(store.db.owners.get(commitment["owner_id"]))
    services.recompute_project(project)
    return ok(ser.claim_out(claim))


@bp.post("/uro/delay-claims/<claim_id>/withdraw-allocation")
def withdraw_allocation(claim_id):
    authenticate(("ConstructionEngineer",))
    body = body_json()
    field_str(body, "withdrawal_reason", min_len=1, max_len=500)

    claim = must_get("claim", claim_id)
    if claim["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an ALLOCATED delay claim may have its allocation withdrawn.")
    project = store.db.projects.get(claim["project_id"])
    services.guard_project_open(project)

    claim["allocated_to_owner_cents"] = 0
    claim["allocated_to_state_cents"] = 0
    claim["status"] = "UNDER_ANALYSIS"
    services.touch(claim)

    commitment = store.db.commitments.get(claim["commitment_id"])
    if commitment is not None:
        services.recompute_owner(store.db.owners.get(commitment["owner_id"]))
    services.recompute_project(project)
    return ok(ser.claim_out(claim))


@bp.post("/uro/delay-claims/<claim_id>/deny")
def deny_claim(claim_id):
    authenticate(("ConstructionEngineer",))
    body = body_json()
    field_str(body, "denial_reason", min_len=1, max_len=500)

    claim = must_get("claim", claim_id)
    if claim["status"] not in ("SUBMITTED", "UNDER_ANALYSIS"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SUBMITTED or UNDER_ANALYSIS delay claim may be denied.")
    project = store.db.projects.get(claim["project_id"])
    services.guard_project_open(project)

    claim["status"] = "DENIED"
    services.touch(claim)
    services.recompute_project(project)
    return ok(ser.claim_out(claim))
