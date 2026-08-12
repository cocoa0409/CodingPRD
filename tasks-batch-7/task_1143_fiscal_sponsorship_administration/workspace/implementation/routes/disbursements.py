"""DisbursementRequest endpoints (PRD §3.4)."""

from flask import Blueprint, request

from db import (
    agreement_of_project,
    fund_of_project,
    new_id,
    parse_iso_date,
    stamp_new,
    store,
    touch,
)
from envelope import ok_list, ok_obj
from errors import (
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_AMOUNT_BELOW_MINIMUM,
    ERR_CRITICAL_INCIDENT_OPEN,
    ERR_DISBURSEMENT_NOT_FOUND,
    ERR_DISBURSEMENT_STATE_INVALID,
    ERR_FUND_NOT_ACTIVE,
    ERR_INSUFFICIENT_FUNDS,
    ERR_NO_COVERING_TRANCHE,
    ERR_PROJECT_NOT_ACTIVE,
    ERR_PROJECT_NOT_FOUND,
    ERR_SEVERE_POSTURE_BLOCKS_SPEND,
    ERR_SOD_VIOLATION,
    ERR_STAFF_ENGAGEMENT_REQUIRED,
    ERR_TRANCHE_BUDGET_EXCEEDED,
    ERR_VALIDATION,
    raise_err,
)
from security import (
    READ_ROLES,
    auth,
    body,
    opt_str,
    req_enum,
    req_int,
    req_str,
    require_owner,
    require_role,
)
from services import (
    HIGH_VALUE_THRESHOLD_CENTS,
    has_open_critical_incident,
    pay_disbursement,
    release_commitment,
    spendable_balance,
    take_commitment,
)

bp = Blueprint("disbursements", __name__)

PAYEE_TYPES = ("VENDOR", "STAFF", "OTHER")
COMPLIANCE_DECISIONS = ("APPROVE", "RETURN", "REJECT")
SPONSOR_DECISIONS = ("APPROVE", "REJECT")


def get_disbursement(disb_id):
    disb = store.disbursements.get(disb_id)
    if disb is None:
        raise_err(ERR_DISBURSEMENT_NOT_FOUND, "disbursement request not found")
    return disb


@bp.post("/fsa/projects/<project_id>/disbursement-requests")
def create_disbursement(project_id):
    data = body()
    amount = req_int(data, "amount_cents")
    purpose = req_str(data, "purpose")
    payee_type = req_enum(data, "payee_type", PAYEE_TYPES)
    payee_name = req_str(data, "payee_name")
    spend_date = req_str(data, "spend_date")
    staff_engagement_id = opt_str(data, "staff_engagement_id")
    # staff_engagement_id presence is enforced at submit (ERR_STAFF_ENGAGEMENT_REQUIRED,
    # validation rule 22), not at draft creation; the draft records whatever was provided.
    if parse_iso_date(spend_date) is None:
        raise_err(ERR_VALIDATION, "spend_date must be an ISO date (YYYY-MM-DD)")
    uid, role = auth()
    require_role(role, {"ProjectLead"})
    require_owner(uid, project_id)
    project = store.projects.get(project_id)
    if project is None:
        raise_err(ERR_PROJECT_NOT_FOUND, "project not found")
    if amount < 1:
        raise_err(ERR_AMOUNT_BELOW_MINIMUM, "amount_cents must be at least 1")
    fund = fund_of_project(project["id"])
    disb = stamp_new({
        "id": new_id(),
        "project_id": project["id"],
        "fund_account_id": fund["id"] if fund else None,
        "staff_engagement_id": staff_engagement_id,
        "grant_tranche_id": None,
        "amount_cents": amount,
        "purpose": purpose,
        "payee_type": payee_type,
        "payee_name": payee_name,
        "spend_date": spend_date,
        "status": "DRAFT",
        "high_value": amount >= HIGH_VALUE_THRESHOLD_CENTS,
        "exit_settled": False,
        "auto_reject_reason": None,
        "submitted_by_user_id": None,
        "compliance_approved_by_user_id": None,
        "sponsor_approved_by_user_id": None,
        "paid_by_user_id": None,
    })
    store.disbursements[disb["id"]] = disb
    return ok_obj(disb, 201)


@bp.get("/fsa/disbursement-requests")
def list_disbursements():
    uid, role = auth()
    require_role(role, READ_ROLES)
    items = list(store.disbursements.values())
    for param in (
        "project_id",
        "fund_account_id",
        "staff_engagement_id",
        "grant_tranche_id",
        "status",
    ):
        v = request.args.get(param)
        if v is not None:
            items = [d for d in items if d[param] == v]
    return ok_list(items)


@bp.get("/fsa/disbursement-requests/<disb_id>")
def get_disbursement_route(disb_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    return ok_obj(get_disbursement(disb_id))


@bp.post("/fsa/disbursement-requests/<disb_id>/submit")
def submit_disbursement(disb_id):
    uid, role = auth()
    require_role(role, {"ProjectLead"})
    disb = get_disbursement(disb_id)
    require_owner(uid, disb["project_id"])
    if disb["status"] != "DRAFT":
        raise_err(ERR_DISBURSEMENT_STATE_INVALID, "disbursement is not DRAFT")
    project = store.projects.get(disb["project_id"])
    if project is None or project["status"] != "ACTIVE":
        raise_err(ERR_PROJECT_NOT_ACTIVE, "project is not ACTIVE")
    agreement = agreement_of_project(disb["project_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise_err(ERR_AGREEMENT_NOT_ACTIVE, "agreement is not ACTIVE")
    fund = store.funds.get(disb["fund_account_id"])
    if fund is None or fund["status"] != "ACTIVE":
        raise_err(ERR_FUND_NOT_ACTIVE, "fund account is not ACTIVE")
    if project["oversight_posture"] == "SEVERE":
        raise_err(ERR_SEVERE_POSTURE_BLOCKS_SPEND, "SEVERE oversight posture blocks disbursement submit")
    # STAFF payee referential check
    if disb["payee_type"] == "STAFF":
        eng = store.engagements.get(disb.get("staff_engagement_id") or "")
        if (
            eng is None
            or eng["project_id"] != disb["project_id"]
            or eng["status"] != "ACTIVE"
        ):
            raise_err(ERR_STAFF_ENGAGEMENT_REQUIRED, "STAFF payee requires an ACTIVE engagement of this project")
    # covering tranche under PRE_APPROVED_GRANT
    tranche = None
    if agreement["model"] == "PRE_APPROVED_GRANT":
        spend = parse_iso_date(disb["spend_date"])
        for t in store.tranches.values():
            if (
                t["agreement_id"] == agreement["id"]
                and t["status"] == "ISSUED"
                and t["_period_start"] <= spend <= t["_period_end"]
            ):
                tranche = t
                break
        if tranche is None:
            raise_err(ERR_NO_COVERING_TRANCHE, "no ISSUED tranche covers the spend_date")
        disb["grant_tranche_id"] = tranche["id"]
    # fund sufficiency under the agreement's spending-basis variant
    if disb["amount_cents"] > spendable_balance(fund, agreement):
        raise_err(ERR_INSUFFICIENT_FUNDS, "amount exceeds the spendable balance")
    if tranche is not None:
        remaining = tranche["amount_cents"] - tranche["spent_cents"] - tranche["committed_cents"]
        if disb["amount_cents"] > remaining:
            raise_err(ERR_TRANCHE_BUDGET_EXCEEDED, "amount exceeds the tranche's remaining budget")
    take_commitment(disb, fund)
    disb["submitted_by_user_id"] = uid
    disb["status"] = "SUBMITTED"
    touch(disb)
    return ok_obj(disb)


@bp.post("/fsa/disbursement-requests/<disb_id>/compliance-review")
def compliance_review_disbursement(disb_id):
    data = body()
    decision = req_enum(data, "decision", COMPLIANCE_DECISIONS)
    opt_str(data, "note")
    uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    disb = get_disbursement(disb_id)
    if disb["status"] != "SUBMITTED":
        raise_err(ERR_DISBURSEMENT_STATE_INVALID, "disbursement is not SUBMITTED")
    if uid == disb["submitted_by_user_id"]:
        raise_err(ERR_SOD_VIOLATION, "reviewer must differ from the submitter")
    fund = store.funds.get(disb["fund_account_id"])
    if decision == "APPROVE":
        disb["compliance_approved_by_user_id"] = uid
        disb["status"] = "PENDING_SPONSOR" if disb["high_value"] else "APPROVED_FOR_PAYMENT"
    elif decision == "RETURN":
        release_commitment(disb, fund)
        disb["status"] = "DRAFT"
    else:  # REJECT
        release_commitment(disb, fund)
        disb["status"] = "REJECTED"
    touch(disb)
    return ok_obj(disb)


@bp.post("/fsa/disbursement-requests/<disb_id>/sponsor-approve")
def sponsor_approve(disb_id):
    data = body()
    decision = req_enum(data, "decision", SPONSOR_DECISIONS)
    opt_str(data, "note")
    uid, role = auth()
    require_role(role, {"SponsorAdmin"})
    disb = get_disbursement(disb_id)
    if disb["status"] != "PENDING_SPONSOR":
        raise_err(ERR_DISBURSEMENT_STATE_INVALID, "disbursement is not PENDING_SPONSOR")
    if uid == disb["submitted_by_user_id"] or uid == disb["compliance_approved_by_user_id"]:
        raise_err(ERR_SOD_VIOLATION, "sponsor approver must differ from prior actors")
    if decision == "APPROVE":
        disb["sponsor_approved_by_user_id"] = uid
        disb["status"] = "APPROVED_FOR_PAYMENT"
    else:
        fund = store.funds.get(disb["fund_account_id"])
        release_commitment(disb, fund)
        disb["status"] = "REJECTED"
    touch(disb)
    return ok_obj(disb)


@bp.post("/fsa/disbursement-requests/<disb_id>/pay")
def pay(disb_id):
    uid, role = auth()
    require_role(role, {"FinanceOfficer"})
    disb = get_disbursement(disb_id)
    if disb["status"] != "APPROVED_FOR_PAYMENT":
        raise_err(ERR_DISBURSEMENT_STATE_INVALID, "disbursement is not APPROVED_FOR_PAYMENT")
    prior_actors = {disb["submitted_by_user_id"], disb["compliance_approved_by_user_id"]}
    if disb.get("sponsor_approved_by_user_id"):
        prior_actors.add(disb["sponsor_approved_by_user_id"])
    if uid in prior_actors:
        raise_err(ERR_SOD_VIOLATION, "payer must differ from all prior actors")
    if has_open_critical_incident(disb["project_id"]):
        raise_err(ERR_CRITICAL_INCIDENT_OPEN, "an open CRITICAL incident blocks payment")
    fund = store.funds.get(disb["fund_account_id"])
    pay_disbursement(disb, fund)
    disb["paid_by_user_id"] = uid
    return ok_obj(disb)


@bp.post("/fsa/disbursement-requests/<disb_id>/cancel")
def cancel(disb_id):
    uid, role = auth()
    require_role(role, {"ProjectLead"})
    disb = get_disbursement(disb_id)
    require_owner(uid, disb["project_id"])
    if disb["status"] not in ("DRAFT", "SUBMITTED"):
        raise_err(ERR_DISBURSEMENT_STATE_INVALID, "disbursement cannot be cancelled from %s" % disb["status"])
    if disb["status"] == "SUBMITTED":
        fund = store.funds.get(disb["fund_account_id"])
        release_commitment(disb, fund)
    disb["status"] = "CANCELLED"
    touch(disb)
    return ok_obj(disb)
