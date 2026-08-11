"""ExitPlan endpoints: propose, due diligence, signoff fork-join, execute
waterfall, abandon (PRD §3.8)."""

from flask import Blueprint, request

from db import agreement_of_project, fund_of_project, iso, new_id, now, stamp_new, store, touch
from envelope import ok_list, ok_obj
from errors import (
    ERR_ACTIVE_EXIT_PLAN_EXISTS,
    ERR_CRITICAL_INCIDENT_OPEN,
    ERR_EXIT_PLAN_NOT_FOUND,
    ERR_EXIT_STATE_INVALID,
    ERR_OPEN_COMPLIANCE_BLOCKS_EXIT,
    ERR_PROJECT_NOT_FOUND,
    ERR_SEVERE_POSTURE_BLOCKS_SPEND,
    ERR_SIGNER_REUSED,
    ERR_SIGNOFF_PARTY_REPEATED,
    ERR_UNAUTHORIZED_ROLE,
    raise_err,
)
from security import (
    READ_ROLES,
    auth,
    body,
    req_enum,
    req_str,
    require_owner,
    require_role,
)
from services import (
    has_open_critical_incident,
    exit_waterfall,
    pay_disbursement,
    post_ledger,
    release_commitment,
)

bp = Blueprint("exits", __name__)

PARTIES = ("SPONSOR_BOARD", "PROJECT_LEAD", "SUCCESSOR_REP")
NON_TERMINAL_PLAN_STATES = ("PROPOSED", "DUE_DILIGENCE", "APPROVED")


def get_exit_plan(plan_id):
    plan = store.exit_plans.get(plan_id)
    if plan is None:
        raise_err(ERR_EXIT_PLAN_NOT_FOUND, "exit plan not found")
    return plan


@bp.post("/fsa/projects/<project_id>/exit-plans")
def create_exit_plan(project_id):
    data = body()
    successor_entity_name = req_str(data, "successor_entity_name")
    successor_ein = req_str(data, "successor_ein")
    reason = req_str(data, "reason")
    uid, role = auth()
    require_role(role, {"ProjectLead", "SponsorAdmin"})
    if role == "ProjectLead":
        require_owner(uid, project_id)
    if project_id not in store.projects:
        raise_err(ERR_PROJECT_NOT_FOUND, "project not found")
    for p in store.exit_plans.values():
        if p["project_id"] == project_id and p["status"] in NON_TERMINAL_PLAN_STATES:
            raise_err(ERR_ACTIVE_EXIT_PLAN_EXISTS, "a non-terminal exit plan already exists")
    plan = stamp_new({
        "id": new_id(),
        "project_id": project_id,
        "successor_entity_name": successor_entity_name,
        "successor_ein": successor_ein,
        "reason": reason,
        "status": "PROPOSED",
        "signoffs": [],
        "committed_payout_cents": 0,
        "reserve_cents": 0,
        "exit_fee_cents": 0,
        "transfer_cents": 0,
    })
    store.exit_plans[plan["id"]] = plan
    return ok_obj(plan, 201)


@bp.get("/fsa/exit-plans/<plan_id>")
def get_exit_plan_route(plan_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    return ok_obj(get_exit_plan(plan_id))


@bp.get("/fsa/projects/<project_id>/exit-plans")
def list_exit_plans(project_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    if project_id not in store.projects:
        raise_err(ERR_PROJECT_NOT_FOUND, "project not found")
    items = [p for p in store.exit_plans.values() if p["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return ok_list(items)


@bp.post("/fsa/exit-plans/<plan_id>/begin-due-diligence")
def begin_due_diligence(plan_id):
    uid, role = auth()
    require_role(role, {"SponsorAdmin"})
    plan = get_exit_plan(plan_id)
    if plan["status"] != "PROPOSED":
        raise_err(ERR_EXIT_STATE_INVALID, "exit plan is not PROPOSED")
    project = store.projects.get(plan["project_id"])
    # pipeline order §2.11: critical-incident gate (10), open-compliance (11), posture (12)
    if has_open_critical_incident(plan["project_id"]):
        raise_err(ERR_CRITICAL_INCIDENT_OPEN, "an open CRITICAL incident blocks due diligence")
    if any(
        r["project_id"] == plan["project_id"] and r["status"] in ("OPEN", "ESCALATED")
        for r in store.reviews.values()
    ):
        raise_err(ERR_OPEN_COMPLIANCE_BLOCKS_EXIT, "an OPEN or ESCALATED review blocks due diligence")
    if project and project["oversight_posture"] != "NORMAL":
        raise_err(ERR_SEVERE_POSTURE_BLOCKS_SPEND, "oversight posture blocks due diligence")
    plan["status"] = "DUE_DILIGENCE"
    touch(plan)
    return ok_obj(plan)


@bp.post("/fsa/exit-plans/<plan_id>/signoff")
def signoff(plan_id):
    data = body()
    party = req_enum(data, "party", PARTIES)
    uid, role = auth()
    require_role(role, {"SponsorAdmin", "ProjectLead"})
    # party-role binding: PROJECT_LEAD requires ProjectLead with ownership anchor;
    # SPONSOR_BOARD / SUCCESSOR_REP require SponsorAdmin
    plan = get_exit_plan(plan_id)
    if party == "PROJECT_LEAD":
        if role != "ProjectLead":
            raise_err(ERR_UNAUTHORIZED_ROLE, "PROJECT_LEAD signoff requires the ProjectLead role")
        require_owner(uid, plan["project_id"])
    else:
        if role != "SponsorAdmin":
            raise_err(ERR_UNAUTHORIZED_ROLE, "%s signoff requires the SponsorAdmin role" % party)
    if plan["status"] != "DUE_DILIGENCE":
        raise_err(ERR_EXIT_STATE_INVALID, "exit plan is not in DUE_DILIGENCE")
    if any(s["party"] == party for s in plan["signoffs"]):
        raise_err(ERR_SIGNOFF_PARTY_REPEATED, "party %s already signed" % party)
    if any(s["signer_user_id"] == uid for s in plan["signoffs"]):
        raise_err(ERR_SIGNER_REUSED, "signer already recorded under another party")
    plan["signoffs"].append({
        "party": party,
        "signer_user_id": uid,
        "signed_at": iso(now()),
    })
    if len(plan["signoffs"]) == 3:
        plan["status"] = "APPROVED"
    touch(plan)
    return ok_obj(plan)


@bp.post("/fsa/exit-plans/<plan_id>/execute")
def execute(plan_id):
    uid, role = auth()
    require_role(role, {"SponsorAdmin"})
    plan = get_exit_plan(plan_id)
    if plan["status"] != "APPROVED":
        raise_err(ERR_EXIT_STATE_INVALID, "exit plan is not APPROVED")
    project = store.projects.get(plan["project_id"])
    fund = fund_of_project(plan["project_id"])
    # waterfall computed atomically before any mutation (§2.11 rule 28 inside)
    G, bucket1, bucket2, bucket3, bucket4 = exit_waterfall(project, fund)
    # commit: SUBMITTED auto-reject with release; DRAFT auto-cancel
    for d in list(store.disbursements.values()):
        if d["project_id"] != project["id"]:
            continue
        if d["status"] == "SUBMITTED":
            release_commitment(d, fund)
            d["status"] = "REJECTED"
            touch(d)
        elif d["status"] == "DRAFT":
            d["status"] = "CANCELLED"
            touch(d)
    # bucket one: pay out PENDING_SPONSOR / APPROVED_FOR_PAYMENT with exit_settled
    for d in list(store.disbursements.values()):
        if d["project_id"] == project["id"] and d["status"] in ("PENDING_SPONSOR", "APPROVED_FOR_PAYMENT"):
            pay_disbursement(d, fund, exit_settled=True)
    # bucket two: reserve
    fund["reserved_cents"] = bucket2
    if bucket2 > 0:
        post_ledger(fund["id"], "RESERVE_HOLD", -bucket2,
                    "Compliance reserve held at exit for plan %s" % plan["id"])
    # bucket three: exit fee
    fund["total_fees_charged_cents"] += bucket3
    post_ledger(fund["id"], "FEE_DEBIT", -bucket3,
                "Exit fee for plan %s" % plan["id"])
    # bucket four: transfer to successor
    fund["total_transferred_out_cents"] += bucket4
    if bucket4 > 0:
        post_ledger(fund["id"], "EXIT_TRANSFER_DEBIT", -bucket4,
                    "Exit transfer to successor for plan %s" % plan["id"])
    fund["status"] = "CLOSED"
    touch(fund)
    agreement = agreement_of_project(project["id"])
    if agreement and agreement["status"] == "ACTIVE":
        agreement["status"] = "SUPERSEDED_BY_INDEPENDENCE"
        touch(agreement)
    if project["status"] == "ACTIVE":
        project["status"] = "SPUN_OFF"
        touch(project)
    plan["committed_payout_cents"] = bucket1
    plan["reserve_cents"] = bucket2
    plan["exit_fee_cents"] = bucket3
    plan["transfer_cents"] = bucket4
    plan["status"] = "COMPLETED"
    touch(plan)
    return ok_obj(plan)


@bp.post("/fsa/exit-plans/<plan_id>/abandon")
def abandon(plan_id):
    data = body()
    req_str(data, "reason")
    uid, role = auth()
    require_role(role, {"SponsorAdmin", "ProjectLead"})
    plan = get_exit_plan(plan_id)
    if role == "ProjectLead":
        require_owner(uid, plan["project_id"])
    if plan["status"] not in NON_TERMINAL_PLAN_STATES:
        raise_err(ERR_EXIT_STATE_INVALID, "exit plan cannot be abandoned from %s" % plan["status"])
    plan["status"] = "ABANDONED"
    touch(plan)
    return ok_obj(plan)
