"""Routes: expenditures (with the four-link posting cascade) and cost transfers."""
from flask import Blueprint, request

import serializers as sz
from db import STORES, new_id, now_clock, stamp_new, touch
from errors import err
from middleware import (Shape, auth, body, get_or_404, list_page, require_role,
                        sh_bool, sh_dt, sh_int, sh_pct, sh_str)
from response import ok, ok_created, ok_list
from services import (apply_transfer_effects, exp_mtdc_eligible, find_line,
                      fringe_for, recompute_award, recompute_statements_for,
                      salary_charge, RETROACTIVE_DAYS)
from util import whole_days

bp = Blueprint("expenditures", __name__)

EXP_TYPES = {"SALARY", "TRAVEL", "EQUIPMENT", "SUPPLIES", "PARTICIPANT_SUPPORT",
             "OTHER_DIRECT", "SUBAWARD_PAYMENT"}
TYPE_TO_CATEGORY = {
    "SALARY": "PERSONNEL_SALARIES", "TRAVEL": "TRAVEL", "EQUIPMENT": "EQUIPMENT",
    "SUPPLIES": "MATERIALS_SUPPLIES", "PARTICIPANT_SUPPORT": "PARTICIPANT_SUPPORT",
    "OTHER_DIRECT": "OTHER_DIRECT",
}
EXP_STATUSES = {"PENDING_REVIEW", "POSTED", "DISALLOWED", "TRANSFERRED_OUT"}
TRANSFER_STATUSES = {"DRAFT", "SUBMITTED", "PENDING_COUNTERSIGN", "APPROVED", "DENIED"}


# ---------------------------------------------------------------------------
# expenditures
# ---------------------------------------------------------------------------

@bp.post("/api/expenditures")
def create_expenditure():
    uid, role = auth()
    require_role(role, ["GrantCoordinator"])
    b = body()
    sh = Shape()
    award_id = sh_str(b, "award_id", sh)
    line_id = sh_str(b, "budget_line_id", sh)
    etype = sh_str(b, "expenditure_type", sh)
    if etype is not None and etype not in EXP_TYPES:
        sh.bad = True
    tx = sh_dt(b, "transaction_date", sh)
    alloc = sh_bool(b, "is_allocable", sh)
    reas = sh_bool(b, "is_reasonable", sh)
    cons = sh_bool(b, "is_consistent", sh)
    if alloc is None or reas is None or cons is None:
        sh.bad = True
    amount = sh_int(b, "amount_cents", sh, required=False)
    effort = sh_pct(b, "effort_pct", sh, lo_exclusive=0, hi_inclusive=100, required=False)
    months = sh_pct(b, "period_months", sh, lo_exclusive=0, hi_inclusive=12, required=False)
    person_id = sh_str(b, "person_id", sh, required=False)
    cost_share = sh_bool(b, "is_cost_share", sh, default=False)
    disbursed = sh_bool(b, "cash_disbursed", sh, default=False)
    descr = sh_str(b, "description", sh, required=False)
    # existence, body FK declared order: award_id, budget_line_id, ... person_id
    a = get_or_404("awards", award_id, "ERR_AWARD_NOT_FOUND") if award_id else None
    line = get_or_404("budget_lines", line_id, "ERR_BUDGET_LINE_NOT_FOUND") if line_id else None
    p = get_or_404("persons", person_id, "ERR_PERSON_NOT_FOUND") if person_id else None
    if a is not None:
        # state (6): SUSPENDED blocks financial writes
        if a["status"] == "SUSPENDED":
            raise err("ERR_AWARD_NOT_ACTIVE", "Expenditure create is blocked while the award is SUSPENDED")
        # posture (7): create requires OPEN
        if a["posture"] == "RESTRICTED":
            raise err("ERR_AWARD_RESTRICTED", "Award posture RESTRICTED blocks expenditure create")
        if a["posture"] == "FROZEN":
            raise err("ERR_AWARD_FROZEN", "Award posture FROZEN blocks expenditure create")
        # structural (10): SUBAWARD_PAYMENT is system-managed
        if etype == "SUBAWARD_PAYMENT":
            raise err("ERR_EXPENDITURE_TYPE_SYSTEM_MANAGED",
                      "SUBAWARD_PAYMENT expenditures are created only by subaward-invoice approval")
        # referential (11)
        if line is not None:
            if line["award_id"] != a["id"]:
                raise err("ERR_BUDGET_LINE_AWARD_MISMATCH",
                          "budget_line_id belongs to a different award than award_id")
            if etype in TYPE_TO_CATEGORY and line["category"] != TYPE_TO_CATEGORY[etype]:
                raise err("ERR_CATEGORY_TYPE_MISMATCH",
                          "expenditure_type does not match the line category mapping")
    # shape-dependent requirements
    if etype == "SALARY":
        if person_id is None:
            sh.bad = True
        if effort is None:
            sh.bad = True
        if months is None:
            sh.bad = True
    elif etype in EXP_TYPES and etype != "SUBAWARD_PAYMENT":
        if amount is None:
            sh.bad = True
    sh.raise_if_bad()

    if etype == "SALARY":
        amt, over_cap = salary_charge(p, a, effort, months)
        fringe = fringe_for(a, amt)
        eff_f, mon_f = float(effort), float(months)
    else:
        amt, over_cap, fringe = amount, 0, 0
        eff_f = float(effort) if effort is not None else None
        mon_f = float(months) if months is not None else None
    e = stamp_new({
        "id": new_id(), "award_id": award_id, "budget_line_id": line_id,
        "person_id": person_id if etype == "SALARY" else None,
        "transferred_from_id": None, "expenditure_type": etype,
        "amount_cents": amt, "fringe_cents": fringe, "over_cap_cents": over_cap,
        "mtdc_eligible_cents": exp_mtdc_eligible(etype, amt, cost_share),
        "effort_pct": eff_f, "period_months": mon_f,
        "transaction_date": tx, "is_cost_share": cost_share, "cash_disbursed": disbursed,
        "is_allocable": alloc, "is_reasonable": reas, "is_consistent": cons,
        "description": descr, "status": "PENDING_REVIEW", "disallow_reason": None,
        "posted_at": None, "invoiced_receivable_id": None, "submitted_by_user_id": uid,
    })
    STORES["expenditures"][e["id"]] = e
    return ok_created(sz.expenditure(e))


@bp.get("/api/expenditures")
def list_expenditures():
    auth()
    filters = {
        lambda e: e["award_id"]: request.args.get("award_id"),
        lambda e: e["budget_line_id"]: request.args.get("budget_line_id"),
        lambda e: e.get("person_id"): request.args.get("person_id"),
        lambda e: e["status"]: request.args.get("status"),
        lambda e: e.get("transferred_from_id"): request.args.get("transferred_from_id"),
        lambda e: e.get("invoiced_receivable_id"): request.args.get("invoiced_receivable_id"),
        lambda e: e["expenditure_type"]: request.args.get("expenditure_type"),
    }
    items, total, limit, offset = list_page("expenditures", sz.expenditure, filters)
    return ok_list(items, total, limit, offset)


@bp.get("/api/expenditures/<eid>")
def get_expenditure(eid):
    auth()
    return ok(sz.expenditure(get_or_404("expenditures", eid, "ERR_EXPENDITURE_NOT_FOUND")))


@bp.post("/api/expenditures/<eid>/post")
def post_expenditure(eid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantsAccountant"])
    e = get_or_404("expenditures", eid, "ERR_EXPENDITURE_NOT_FOUND")
    # state (6): machine validity, then award status
    if e["status"] != "PENDING_REVIEW":
        raise err("ERR_EXPENDITURE_NOT_REVIEWABLE", "Post requires status PENDING_REVIEW")
    a = STORES["awards"][e["award_id"]]
    if a["status"] != "ACTIVE":
        raise err("ERR_AWARD_NOT_ACTIVE", "Posting requires award status ACTIVE")
    # posture (7)
    if a["posture"] == "FROZEN":
        raise err("ERR_AWARD_FROZEN", "Award posture FROZEN blocks expenditure post")
    # compliance (8): allowability attestations
    if not (e["is_allocable"] and e["is_reasonable"] and e["is_consistent"]):
        raise err("ERR_ALLOWABILITY_INCOMPLETE",
                  "Posting requires is_allocable, is_reasonable and is_consistent all true")
    # temporal (9): period of performance (closed interval)
    if not (a["project_start_date"] <= e["transaction_date"] <= a["current_end_date"]):
        raise err("ERR_OUTSIDE_PERIOD_OF_PERFORMANCE",
                  "transaction_date outside [project_start_date, current_end_date]")
    # referential (11): SALARY requires an EffortCommitment for (person, award)
    if e["expenditure_type"] == "SALARY":
        if not any(c["award_id"] == e["award_id"] and c["person_id"] == e["person_id"]
                   for c in STORES["commitments"].values()):
            raise err("ERR_SALARY_NO_COMMITMENT",
                      "SALARY post requires an EffortCommitment for (person, award)")
    # fiscal (12): line sufficiency, pinned order salaries-then-fringe; cost-share skips
    line = STORES["budget_lines"].get(e["budget_line_id"])
    if not e["is_cost_share"]:
        if e["expenditure_type"] == "SALARY":
            e["fringe_cents"] = fringe_for(a, e["amount_cents"])  # provisional rate at post time
            if line is None or line["spent_cents"] + e["amount_cents"] > line["authorized_cents"]:
                raise err("ERR_BUDGET_LINE_EXCEEDED", "PERSONNEL_SALARIES line would exceed authorized_cents")
            if e["fringe_cents"] > 0:
                fl = find_line(e["award_id"], "FRINGE_BENEFITS")
                if fl is None or fl["spent_cents"] + e["fringe_cents"] > fl["authorized_cents"]:
                    raise err("ERR_BUDGET_LINE_EXCEEDED", "FRINGE_BENEFITS line would exceed authorized_cents")
        else:
            if line is None or line["spent_cents"] + e["amount_cents"] > line["authorized_cents"]:
                raise err("ERR_BUDGET_LINE_EXCEEDED", "Budget line would exceed authorized_cents")

    # ---- four-link cascade (atomic) ----
    clock = now_clock()
    e["status"] = "POSTED"
    e["posted_at"] = clock
    if e["is_cost_share"]:
        a["cost_share_met_cents"] += e["amount_cents"]  # cost share bypasses the lines
    else:
        if line is not None:
            line["spent_cents"] += e["amount_cents"]
            touch(line)
        if e["expenditure_type"] == "SALARY" and e["fringe_cents"] > 0:
            fl = find_line(e["award_id"], "FRINGE_BENEFITS")
            fl["spent_cents"] += e["fringe_cents"]
            touch(fl)
    if e["expenditure_type"] == "SALARY":
        # over-cap salary always lands in institutional cost share
        a["cost_share_met_cents"] += e["over_cap_cents"]
    recompute_award(a)                       # links 2-3: aggregates + LOC pool
    if e["expenditure_type"] == "SALARY":
        recompute_statements_for(e["person_id"], e["award_id"], e["transaction_date"])
    touch(a)                                 # post increments parent award version
    touch(e)
    return ok(sz.expenditure(e))


@bp.post("/api/expenditures/<eid>/disallow")
def disallow_expenditure(eid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantsAccountant"])
    e = get_or_404("expenditures", eid, "ERR_EXPENDITURE_NOT_FOUND")
    if e["status"] != "PENDING_REVIEW":
        raise err("ERR_EXPENDITURE_NOT_REVIEWABLE", "Disallow requires status PENDING_REVIEW")
    b = body()
    sh = Shape()
    reason = sh_str(b, "disallow_reason", sh)
    sh.raise_if_bad()
    e["status"] = "DISALLOWED"
    e["disallow_reason"] = reason
    touch(e)
    return ok(sz.expenditure(e))


@bp.post("/api/expenditures/<eid>/resubmit")
def resubmit_expenditure(eid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantCoordinator"])
    e = get_or_404("expenditures", eid, "ERR_EXPENDITURE_NOT_FOUND")
    if e["status"] != "DISALLOWED":
        raise err("ERR_EXPENDITURE_NOT_REVIEWABLE", "Resubmit requires status DISALLOWED")
    b = body()
    sh = Shape()
    alloc = sh_bool(b, "is_allocable", sh)
    reas = sh_bool(b, "is_reasonable", sh)
    cons = sh_bool(b, "is_consistent", sh)
    amount = sh_int(b, "amount_cents", sh, required=False)
    sh.raise_if_bad()
    if alloc is not None:
        e["is_allocable"] = alloc
    if reas is not None:
        e["is_reasonable"] = reas
    if cons is not None:
        e["is_consistent"] = cons
    # for SALARY any amount_cents input is ignored (computed by salary_charge_with_cap)
    if amount is not None and e["expenditure_type"] != "SALARY":
        e["amount_cents"] = amount
        e["mtdc_eligible_cents"] = exp_mtdc_eligible(e["expenditure_type"], amount, e["is_cost_share"])
    e["status"] = "PENDING_REVIEW"
    e["disallow_reason"] = None
    touch(e)
    return ok(sz.expenditure(e))


# ---------------------------------------------------------------------------
# cost transfers
# ---------------------------------------------------------------------------

@bp.post("/api/cost-transfers")
def create_transfer():
    uid, role = auth()
    require_role(role, ["GrantCoordinator", "GrantsAccountant"])
    b = body()
    sh = Shape()
    src_id = sh_str(b, "source_expenditure_id", sh)
    tgt_award_id = sh_str(b, "target_award_id", sh)
    tgt_line_id = sh_str(b, "target_budget_line_id", sh)
    just = sh_str(b, "justification", sh, min_len=20)
    enh = sh_str(b, "enhanced_justification", sh, required=False)
    # existence, body FK declared order
    src = get_or_404("expenditures", src_id, "ERR_EXPENDITURE_NOT_FOUND") if src_id else None
    tgt_award = get_or_404("awards", tgt_award_id, "ERR_AWARD_NOT_FOUND") if tgt_award_id else None
    tgt_line = get_or_404("budget_lines", tgt_line_id, "ERR_BUDGET_LINE_NOT_FOUND") if tgt_line_id else None
    if src is not None:
        # state (6): source must be POSTED
        if src["status"] != "POSTED":
            raise err("ERR_EXPENDITURE_NOT_REVIEWABLE", "Transfer source must be POSTED")
        # compliance (8): transferability
        if src["expenditure_type"] == "SALARY":
            raise err("ERR_SALARY_NOT_TRANSFERABLE",
                      "Salary corrections route via payroll/effort, not transfers")
        if src["is_cost_share"]:
            raise err("ERR_COST_SHARE_NOT_TRANSFERABLE", "Cost-share entries are not transferable")
        # referential (11)
        if tgt_award is not None and tgt_award["id"] == src["award_id"]:
            raise err("ERR_TRANSFER_TARGET_SAME_AS_SOURCE",
                      "target_award_id equals the source expenditure's award")
        if tgt_line is not None:
            if tgt_award is not None and tgt_line["award_id"] != tgt_award["id"]:
                raise err("ERR_BUDGET_LINE_AWARD_MISMATCH",
                          "target_budget_line_id belongs to a different award than target_award_id")
            src_line = STORES["budget_lines"].get(src["budget_line_id"])
            if src_line is not None and tgt_line["category"] != src_line["category"]:
                raise err("ERR_CATEGORY_TYPE_MISMATCH",
                          "Target line category differs from the source line category")
    sh.raise_if_bad()
    t = stamp_new({
        "id": new_id(), "source_expenditure_id": src_id, "target_award_id": tgt_award_id,
        "target_budget_line_id": tgt_line_id, "justification": just,
        "enhanced_justification": enh, "is_retroactive": None, "days_since_posting": None,
        "status": "DRAFT", "created_by_user_id": uid, "submitted_by_user_id": None,
        "approved_by_user_id": None, "countersigned_by_user_id": None, "deny_reason": None,
    })
    STORES["transfers"][t["id"]] = t
    return ok_created(sz.cost_transfer(t))


@bp.get("/api/cost-transfers")
def list_transfers():
    auth()
    filters = {
        lambda t: t["source_expenditure_id"]: request.args.get("source_expenditure_id"),
        lambda t: t["target_award_id"]: request.args.get("target_award_id"),
        lambda t: t["target_budget_line_id"]: request.args.get("target_budget_line_id"),
        lambda t: t["status"]: request.args.get("status"),
    }
    items, total, limit, offset = list_page("transfers", sz.cost_transfer, filters)
    return ok_list(items, total, limit, offset)


@bp.get("/api/cost-transfers/<tid>")
def get_transfer(tid):
    auth()
    return ok(sz.cost_transfer(get_or_404("transfers", tid, "ERR_TRANSFER_NOT_FOUND")))


@bp.post("/api/cost-transfers/<tid>/submit")
def submit_transfer(tid):
    uid, role = auth()
    require_role(role, ["GrantCoordinator", "GrantsAccountant"])
    t = get_or_404("transfers", tid, "ERR_TRANSFER_NOT_FOUND")
    if t["status"] != "DRAFT":
        raise err("ERR_TRANSFER_NOT_ACTIONABLE", "Submit requires status DRAFT")
    b = body()
    sh = Shape()
    enh = sh_str(b, "enhanced_justification", sh, required=False)
    src = STORES["expenditures"][t["source_expenditure_id"]]
    # timeliness frozen at submit; exactly 90 days is timely
    days = whole_days(src["posted_at"], now_clock())
    retro = days > RETROACTIVE_DAYS
    enh_value = enh if enh is not None else t.get("enhanced_justification")
    if retro and (enh_value is None or len(enh_value) < 50):
        raise err("ERR_ENHANCED_JUSTIFICATION_REQUIRED",
                  "Retroactive transfer (> 90 days) requires enhanced_justification >= 50 chars")
    sh.raise_if_bad()
    if enh is not None:
        t["enhanced_justification"] = enh
    t["days_since_posting"] = days
    t["is_retroactive"] = retro
    t["submitted_by_user_id"] = uid
    t["status"] = "SUBMITTED"
    touch(t)
    return ok(sz.cost_transfer(t))


def _transfer_posture_check(t):
    """Posture gate (priority 7): target award must not be FROZEN."""
    tgt_award = STORES["awards"][t["target_award_id"]]
    if tgt_award["posture"] == "FROZEN":
        raise err("ERR_AWARD_FROZEN", "Target award posture FROZEN blocks transfer approval")


def _transfer_line_fit(t):
    """Fiscal (priority 12): target line spent + amount <= authorized."""
    src = STORES["expenditures"][t["source_expenditure_id"]]
    tgt_line = STORES["budget_lines"].get(t["target_budget_line_id"])
    if tgt_line is None or tgt_line["spent_cents"] + src["amount_cents"] > tgt_line["authorized_cents"]:
        raise err("ERR_BUDGET_LINE_EXCEEDED", "Target line would exceed authorized_cents")


@bp.post("/api/cost-transfers/<tid>/approve")
def approve_transfer(tid):
    uid, role = auth()
    require_role(role, ["GrantsAccountant"])
    t = get_or_404("transfers", tid, "ERR_TRANSFER_NOT_FOUND")
    if t["status"] != "SUBMITTED":
        raise err("ERR_TRANSFER_NOT_ACTIONABLE", "Approve requires status SUBMITTED")
    tgt_award = STORES["awards"][t["target_award_id"]]
    # state (6): target award status requirement on the child operation
    if tgt_award["status"] not in ("ACTIVE", "CLOSEOUT_PENDING"):
        raise err("ERR_AWARD_NOT_ACTIVE", "Target award must be ACTIVE or CLOSEOUT_PENDING")
    # posture (7)
    _transfer_posture_check(t)
    # compliance (8): segregation of duties — approver must differ from submitter
    if uid == t["submitted_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Approver X-User-ID must differ from submitted_by_user_id")
    # fiscal (12): target line fit
    _transfer_line_fit(t)
    if t["is_retroactive"]:
        # retroactive routes to countersign; no ledger effects yet
        t["approved_by_user_id"] = uid
        t["status"] = "PENDING_COUNTERSIGN"
        touch(t)
        return ok(sz.cost_transfer(t))
    apply_transfer_effects(t, uid)
    t["approved_by_user_id"] = uid
    t["status"] = "APPROVED"
    touch(t)
    return ok(sz.cost_transfer(t))


@bp.post("/api/cost-transfers/<tid>/countersign")
def countersign_transfer(tid):
    uid, role = auth()
    require_role(role, ["SponsoredProgramsOfficer"])
    t = get_or_404("transfers", tid, "ERR_TRANSFER_NOT_FOUND")
    if t["status"] != "PENDING_COUNTERSIGN":
        raise err("ERR_TRANSFER_NOT_ACTIONABLE", "Countersign requires status PENDING_COUNTERSIGN")
    _transfer_posture_check(t)   # re-check target posture (7)
    _transfer_line_fit(t)        # re-check target line fit (12)
    apply_transfer_effects(t, uid)
    t["countersigned_by_user_id"] = uid
    t["status"] = "APPROVED"
    touch(t)
    return ok(sz.cost_transfer(t))


@bp.post("/api/cost-transfers/<tid>/deny")
def deny_transfer(tid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantsAccountant", "SponsoredProgramsOfficer"])
    t = get_or_404("transfers", tid, "ERR_TRANSFER_NOT_FOUND")
    if t["status"] not in ("SUBMITTED", "PENDING_COUNTERSIGN"):
        raise err("ERR_TRANSFER_NOT_ACTIONABLE", "Deny requires status SUBMITTED or PENDING_COUNTERSIGN")
    b = body()
    sh = Shape()
    reason = sh_str(b, "deny_reason", sh)
    sh.raise_if_bad()
    t["status"] = "DENIED"
    t["deny_reason"] = reason
    touch(t)
    return ok(sz.cost_transfer(t))


@bp.post("/api/cost-transfers/<tid>/revise")
def revise_transfer(tid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantCoordinator", "GrantsAccountant"])
    t = get_or_404("transfers", tid, "ERR_TRANSFER_NOT_FOUND")
    if t["status"] != "DENIED":
        raise err("ERR_TRANSFER_NOT_ACTIONABLE", "Revise requires status DENIED")
    b = body()
    sh = Shape()
    just = sh_str(b, "justification", sh, required=False, min_len=20)
    sh.raise_if_bad()
    if just is not None:
        t["justification"] = just
    t["status"] = "DRAFT"
    t["deny_reason"] = None
    touch(t)
    return ok(sz.cost_transfer(t))
