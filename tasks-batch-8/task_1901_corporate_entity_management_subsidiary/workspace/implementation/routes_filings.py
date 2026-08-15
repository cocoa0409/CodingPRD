"""Routes: AnnualFiling calendar, prepare/submit/accept/reject."""
from flask import Blueprint, request

import store
import services as svc
from errors import (
    ERR_FILING_NOT_FOUND, ERR_FILING_NOT_PREPARED, ERR_FILING_NOT_SUBMITTED,
    ERR_ENTITY_NOT_ACTIVE, ERR_SEGREGATION_OF_DUTIES,
    raise_err,
)
from middleware import require_roles, get_body, ALL_ROLES
from response import ok_object, paginate, sort_records

bp = Blueprint("filings", __name__)

CS = ["CorporateSecretary"]
FC_CS = ["FilingCoordinator", "CorporateSecretary"]


def get_filing_or_404(filingId):
    rec = store.filings.get(filingId)
    if rec is None:
        raise_err(ERR_FILING_NOT_FOUND)
    return rec


def lazy_filing_overdue(filing):
    """Lazy OVERDUE evaluation for one filing (+ event + posture recompute)."""
    if (filing["status"] in ("SCHEDULED", "PREPARED")
            and svc.parse_date(filing["due_date"]) < store.today()):
        filing["status"] = "OVERDUE"
        store.touch(filing)
        svc.append_event(filing["entity_id"], "FILING_OVERDUE", {"filing_id": filing["id"]})
        svc.recompute_posture(store.entities[filing["entity_id"]])


@bp.route("/api/filings", methods=["GET"])
def list_filings():
    require_roles(ALL_ROLES)
    # Lazy OVERDUE evaluation for listed filings
    for f in list(store.filings.values()):
        lazy_filing_overdue(f)
    records = sort_records(list(store.filings.values()))
    for param, field in (("entity_id", "entity_id"), ("jurisdiction_id", "jurisdiction_id"),
                         ("filing_type", "filing_type"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    period = request.args.get("period_year")
    if period is not None:
        try:
            p = int(period)
            records = [r for r in records if r["period_year"] == p]
        except ValueError:
            records = []
    return paginate([svc.serialize(r) for r in records], request.args)


@bp.route("/api/filings/<filingId>", methods=["GET"])
def get_filing(filingId):
    require_roles(ALL_ROLES)
    rec = get_filing_or_404(filingId)
    lazy_filing_overdue(rec)
    return ok_object(svc.serialize(rec))


def _entity_gate_for_filing(filing):
    entity = store.entities[filing["entity_id"]]
    if entity["status"] not in ("ACTIVE", "DISSOLUTION_PENDING"):
        raise_err(ERR_ENTITY_NOT_ACTIVE,
                  "Filing operations require entity status ACTIVE or DISSOLUTION_PENDING")
    return entity


@bp.route("/api/filings/<filingId>/prepare", methods=["POST"])
def prepare_filing(filingId):
    require_roles(FC_CS)
    rec = get_filing_or_404(filingId)
    get_body()
    lazy_filing_overdue(rec)
    if rec["status"] not in ("SCHEDULED", "OVERDUE", "REJECTED"):
        raise_err(ERR_FILING_NOT_PREPARED,
                  "prepare requires status IN {SCHEDULED, OVERDUE, REJECTED}")
    entity = _entity_gate_for_filing(rec)
    jurisdiction = store.jurisdictions[rec["jurisdiction_id"]]
    # ESTIMATED variant: shares_basis from prior ACCEPTED FRANCHISE_TAX filing,
    # else the snapshot recorded at generation time.
    if rec["filing_type"] == "FRANCHISE_TAX":
        priors = [f for f in svc.filings_of(entity["id"])
                  if f["jurisdiction_id"] == rec["jurisdiction_id"]
                  and f["filing_type"] == "FRANCHISE_TAX" and f["status"] == "ACCEPTED"
                  and f["period_year"] < rec["period_year"]]
        if priors:
            priors.sort(key=lambda f: (f["period_year"], f.get("_seq", 0)))
            rec["shares_basis"] = priors[-1]["shares_basis"]
        rec["tax_estimated_cents"] = svc.calc_franchise_tax(
            entity["entity_type"], jurisdiction["franchise_tax_method"], rec["shares_basis"])
    else:
        rec["tax_estimated_cents"] = 0
    rec["status"] = "PREPARED"
    store.touch(rec)
    return ok_object(svc.serialize(rec))


@bp.route("/api/filings/<filingId>/submit", methods=["POST"])
def submit_filing(filingId):
    user_id, _ = require_roles(FC_CS)
    rec = get_filing_or_404(filingId)
    get_body()
    lazy_filing_overdue(rec)
    if rec["status"] not in ("PREPARED", "OVERDUE"):
        raise_err(ERR_FILING_NOT_PREPARED,
                  "submit requires status IN {PREPARED, OVERDUE}")
    entity = _entity_gate_for_filing(rec)
    jurisdiction = store.jurisdictions[rec["jurisdiction_id"]]
    today = store.today()
    # ACTUAL variant from current authorized_shares
    if rec["filing_type"] == "FRANCHISE_TAX":
        rec["tax_assessed_cents"] = svc.calc_franchise_tax(
            entity["entity_type"], jurisdiction["franchise_tax_method"],
            entity["authorized_shares"])
    else:
        rec["tax_assessed_cents"] = 0
    days_late, penalty = svc.calc_late_penalty(
        jurisdiction, rec["due_date"], today,
        rec["tax_assessed_cents"], rec["report_fee_cents"])
    rec["days_late"] = days_late
    rec["penalty_cents"] = penalty
    rec["fee_cents"] = rec["report_fee_cents"] + rec["tax_assessed_cents"] + penalty
    rec["submitted_date"] = svc.fmt_date(today)
    rec["submitted_by_user_id"] = user_id
    rec["status"] = "SUBMITTED"
    store.touch(rec)
    entity["fees_accrued_cents"] += rec["fee_cents"]
    store.touch(entity)  # increments LegalEntity.version by 1
    return ok_object(svc.serialize(rec))


@bp.route("/api/filings/<filingId>/accept", methods=["POST"])
def accept_filing(filingId):
    user_id, _ = require_roles(CS)
    rec = get_filing_or_404(filingId)
    get_body()
    lazy_filing_overdue(rec)
    if rec["status"] != "SUBMITTED":
        raise_err(ERR_FILING_NOT_SUBMITTED, "accept requires status == SUBMITTED")
    if user_id == rec["submitted_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Acceptor must differ from submitter")
    rec["status"] = "ACCEPTED"
    store.touch(rec)
    # Period rollover: next period, same jurisdiction and filing type
    entity = store.entities[rec["entity_id"]]
    jurisdiction = store.jurisdictions[rec["jurisdiction_id"]]
    if jurisdiction["id"] == entity["formation_jurisdiction_id"]:
        owes = entity["status"] == "ACTIVE"
    else:
        owes = any(q for q in svc.quals_of(entity["id"])
                   if q["jurisdiction_id"] == jurisdiction["id"]
                   and q["status"] in ("QUALIFIED", "WITHDRAWAL_PENDING"))
    next_period = rec["period_year"] + 1
    if owes and not svc._filing_exists(entity["id"], jurisdiction["id"],
                                       rec["filing_type"], next_period):
        svc._create_filing(entity, jurisdiction, rec["filing_type"], next_period)
    return ok_object(svc.serialize(rec))


@bp.route("/api/filings/<filingId>/reject", methods=["POST"])
def reject_filing(filingId):
    user_id, _ = require_roles(CS)
    rec = get_filing_or_404(filingId)
    get_body()  # optional reason
    lazy_filing_overdue(rec)
    if rec["status"] != "SUBMITTED":
        raise_err(ERR_FILING_NOT_SUBMITTED, "reject requires status == SUBMITTED")
    if user_id == rec["submitted_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Rejecter must differ from submitter")
    rec["status"] = "REJECTED"
    store.touch(rec)
    entity = store.entities[rec["entity_id"]]
    entity["fees_accrued_cents"] -= rec["fee_cents"]  # exact reversal of the accrual
    store.touch(entity)  # increments LegalEntity.version by 1
    return ok_object(svc.serialize(rec))
