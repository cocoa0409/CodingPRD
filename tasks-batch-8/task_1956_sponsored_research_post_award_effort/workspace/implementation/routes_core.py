"""Routes: logical clock, sponsors, persons, awards, budget lines, commitments."""
from flask import Blueprint, request

import serializers as sz
from db import STORES, new_id, now_clock, set_clock, stamp_new, touch
from errors import err
from middleware import (Shape, auth, body, get_or_404, list_page, require_role,
                        sh_dt, sh_int, sh_pct, sh_str)
from response import ok, ok_created, ok_list
from services import (fna_authorized, find_line, overdue_sweep, recompute_fna_line,
                      recompute_posture, award_ffr)
from util import fmt_dt

bp = Blueprint("core", __name__)

SPONSOR_TYPES = {"FEDERAL", "FEDERAL_FLOW_THROUGH", "INDUSTRY", "FOUNDATION", "STATE"}
PAYMENT_METHODS = {"LETTER_OF_CREDIT", "COST_REIMBURSABLE_INVOICE", "FIXED_PRICE_SCHEDULE"}
ROLE_TYPES = {"PRINCIPAL_INVESTIGATOR", "RESEARCH_STAFF"}
CATEGORIES = {"PERSONNEL_SALARIES", "FRINGE_BENEFITS", "EQUIPMENT", "TRAVEL",
              "PARTICIPANT_SUPPORT", "MATERIALS_SUPPLIES", "SUBAWARDS", "OTHER_DIRECT", "F_AND_A"}
AWARD_STATUSES = {"PENDING_SETUP", "ACTIVE", "SUSPENDED", "CLOSEOUT_PENDING", "CLOSED"}
POSTURES = {"OPEN", "RESTRICTED", "FROZEN"}


# ---------------------------------------------------------------------------
# logical clock (test-driving)
# ---------------------------------------------------------------------------

@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    auth()
    require_role(auth_role(), ["SystemAdmin"])
    b = body()
    sh = Shape()
    to = sh_dt(b, "to_iso8601", sh)
    sh.raise_if_bad()
    set_clock(to)
    overdue_sweep()  # overdue sweep + posture recompute + FROZEN drawdown cascade
    return ok({"current_utc": fmt_dt(now_clock())})


def auth_role():
    return request.headers.get("X-User-Role")


# ---------------------------------------------------------------------------
# sponsors
# ---------------------------------------------------------------------------

@bp.post("/api/sponsors")
def create_sponsor():
    auth()
    require_role(auth_role(), ["SponsoredProgramsOfficer"])
    b = body()
    sh = Shape()
    name = sh_str(b, "name", sh)
    stype = sh_str(b, "sponsor_type", sh)
    if stype is not None and stype not in SPONSOR_TYPES:
        sh.bad = True
    pm = sh_str(b, "payment_method", sh)
    if pm is not None and pm not in PAYMENT_METHODS:
        sh.bad = True
    cap = b.get("salary_cap_annual_cents")
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int)):
        sh.bad = True
        cap = None
    fna = sh_int(b, "f_and_a_rate_bps", sh)
    apr = sh_int(b, "late_payment_apr_bps", sh, required=False, default=0)
    sh.raise_if_bad()
    s = stamp_new({
        "id": new_id(), "name": name, "sponsor_type": stype, "payment_method": pm,
        "salary_cap_annual_cents": cap, "f_and_a_rate_bps": fna,
        "late_payment_apr_bps": apr if apr is not None else 0,
    })
    STORES["sponsors"][s["id"]] = s
    return ok_created(sz.sponsor(s))


@bp.get("/api/sponsors")
def list_sponsors():
    auth()
    f_pm = request.args.get("payment_method")
    f_st = request.args.get("sponsor_type")
    items, total, limit, offset = list_page(
        "sponsors", sz.sponsor,
        {lambda s: s["payment_method"]: f_pm, lambda s: s["sponsor_type"]: f_st})
    return ok_list(items, total, limit, offset)


@bp.get("/api/sponsors/<sid>")
def get_sponsor(sid):
    auth()
    return ok(sz.sponsor(get_or_404("sponsors", sid, "ERR_SPONSOR_NOT_FOUND")))


# ---------------------------------------------------------------------------
# persons
# ---------------------------------------------------------------------------

@bp.post("/api/persons")
def create_person():
    auth()
    require_role(auth_role(), ["SponsoredProgramsOfficer"])
    b = body()
    sh = Shape()
    name = sh_str(b, "full_name", sh)
    rtype = sh_str(b, "role_type", sh)
    if rtype is not None and rtype not in ROLE_TYPES:
        sh.bad = True
    ibs = sh_int(b, "institutional_base_salary_annual_cents", sh, min_v=1)
    months = sh_int(b, "appointment_months", sh)
    if months is not None and months not in (9, 12):
        sh.bad = True
    sh.raise_if_bad()
    p = stamp_new({
        "id": new_id(), "full_name": name, "role_type": rtype,
        "institutional_base_salary_annual_cents": ibs, "appointment_months": months,
    })
    STORES["persons"][p["id"]] = p
    return ok_created(sz.person(p))


@bp.get("/api/persons")
def list_persons():
    auth()
    f_rt = request.args.get("role_type")
    items, total, limit, offset = list_page(
        "persons", sz.person, {lambda p: p["role_type"]: f_rt})
    return ok_list(items, total, limit, offset)


@bp.get("/api/persons/<pid>")
def get_person(pid):
    auth()
    return ok(sz.person(get_or_404("persons", pid, "ERR_PERSON_NOT_FOUND")))


# ---------------------------------------------------------------------------
# awards
# ---------------------------------------------------------------------------

def _create_fna_line(award_id):
    line = stamp_new({
        "id": new_id(), "award_id": award_id, "category": "F_AND_A",
        "authorized_cents": 0, "baseline_authorized_cents": 0, "spent_cents": 0,
        "mtdc_eligible_cents": 0,
    })
    STORES["budget_lines"][line["id"]] = line
    return line


@bp.post("/api/awards")
def create_award():
    auth()
    require_role(auth_role(), ["SponsoredProgramsOfficer"])
    b = body()
    sh = Shape()
    sponsor_id = sh_str(b, "sponsor_id", sh)
    pi_id = sh_str(b, "pi_id", sh)
    number = sh_str(b, "award_number", sh)
    title = sh_str(b, "title", sh)
    start = sh_dt(b, "project_start_date", sh)
    end = sh_dt(b, "original_end_date", sh)
    obligated = sh_int(b, "total_obligated_cents", sh, min_v=0)
    fringe = sh_int(b, "fringe_rate_bps", sh)
    cost_share = sh_int(b, "cost_share_committed_cents", sh, required=False, default=0)
    # existence, body FK order: sponsor_id, pi_id
    sponsor = get_or_404("sponsors", sponsor_id, "ERR_SPONSOR_NOT_FOUND") if sponsor_id else None
    pi = get_or_404("persons", pi_id, "ERR_PERSON_NOT_FOUND") if pi_id else None
    if sponsor_id and sponsor is None:
        pass
    if pi_id and pi is None:
        pass
    # structural: globally unique award_number
    if number is not None:
        for a in STORES["awards"].values():
            if a["award_number"] == number:
                raise err("ERR_DUPLICATE_AWARD_NUMBER", "award_number already exists")
    sh.raise_if_bad()
    a = stamp_new({
        "id": new_id(), "sponsor_id": sponsor_id, "pi_id": pi_id,
        "award_number": number, "title": title,
        "project_start_date": start, "original_end_date": end, "current_end_date": end,
        "total_obligated_cents": obligated,
        "salary_cap_annual_cents": sponsor.get("salary_cap_annual_cents"),
        "f_and_a_rate_bps": sponsor["f_and_a_rate_bps"],
        "payment_method": sponsor["payment_method"],
        "fringe_rate_bps": fringe,
        "cost_share_committed_cents": cost_share if cost_share is not None else 0,
        "status": "PENDING_SETUP", "posture": "OPEN",
        "mtdc_spent_cents": 0, "f_and_a_accrued_cents": 0, "total_direct_spent_cents": 0,
        "cost_share_met_cents": 0, "cumulative_drawn_cents": 0, "reserved_draw_cents": 0,
        "available_draw_pool_cents": 0, "nce_count": 0, "residual_deobligated_cents": None,
        "_pool_reduction_cents": 0,
    })
    STORES["awards"][a["id"]] = a
    _create_fna_line(a["id"])
    return ok_created(sz.award(a))


@bp.get("/api/awards")
def list_awards():
    auth()
    filters = {
        lambda a: a["sponsor_id"]: request.args.get("sponsor_id"),
        lambda a: a["pi_id"]: request.args.get("pi_id"),
        lambda a: a["status"]: request.args.get("status"),
        lambda a: a["posture"]: request.args.get("posture"),
    }
    items, total, limit, offset = list_page("awards", sz.award, filters)
    return ok_list(items, total, limit, offset)


@bp.get("/api/awards/<aid>")
def get_award(aid):
    auth()
    return ok(sz.award(get_or_404("awards", aid, "ERR_AWARD_NOT_FOUND")))


@bp.post("/api/awards/<aid>/activate")
def activate_award(aid):
    auth()
    require_role(auth_role(), ["SponsoredProgramsOfficer"])
    a = get_or_404("awards", aid, "ERR_AWARD_NOT_FOUND")
    if a["status"] != "PENDING_SETUP":
        raise err("ERR_AWARD_NOT_ACTIVE", "Activation requires award status PENDING_SETUP")
    fna, directs, _ = fna_authorized(a)
    if directs + fna != a["total_obligated_cents"]:
        raise err("ERR_BUDGET_NOT_FULLY_ALLOCATED",
                  "Sum of authorized across all lines (incl. computed F&A) != total_obligated_cents")
    if not any(l["category"] != "F_AND_A" for l in STORES["budget_lines"].values()
               if l["award_id"] == aid):
        raise err("ERR_INVALID_REQUEST", "At least one non-F_AND_A budget line must exist")
    for l in STORES["budget_lines"].values():
        if l["award_id"] == aid:
            l["baseline_authorized_cents"] = l["authorized_cents"]
            touch(l)
    a["status"] = "ACTIVE"
    recompute_posture(a)
    touch(a)
    return ok(sz.award(a))


@bp.post("/api/awards/<aid>/suspend")
def suspend_award(aid):
    auth()
    require_role(auth_role(), ["SponsorOfficial"])
    a = get_or_404("awards", aid, "ERR_AWARD_NOT_FOUND")
    if a["status"] != "ACTIVE":
        raise err("ERR_AWARD_NOT_ACTIVE", "Suspension requires award status ACTIVE")
    a["status"] = "SUSPENDED"
    touch(a)
    return ok(sz.award(a))


@bp.post("/api/awards/<aid>/reinstate")
def reinstate_award(aid):
    auth()
    require_role(auth_role(), ["SponsorOfficial"])
    a = get_or_404("awards", aid, "ERR_AWARD_NOT_FOUND")
    if a["status"] != "SUSPENDED":
        raise err("ERR_AWARD_NOT_SUSPENDED", "Reinstate requires award status SUSPENDED")
    a["status"] = "ACTIVE"
    recompute_posture(a)
    touch(a)
    return ok(sz.award(a))


@bp.post("/api/awards/<aid>/initiate-closeout")
def initiate_closeout(aid):
    auth()
    require_role(auth_role(), ["GrantsAccountant"])
    a = get_or_404("awards", aid, "ERR_AWARD_NOT_FOUND")
    if a["status"] != "ACTIVE":
        raise err("ERR_AWARD_NOT_ACTIVE", "Initiate-closeout requires award status ACTIVE")
    if now_clock() < a["current_end_date"]:
        raise err("ERR_CLOSEOUT_TOO_EARLY", "Logical clock has not reached current_end_date")
    a["status"] = "CLOSEOUT_PENDING"
    # exactly one FFR per award: drop any leftover, create a fresh DRAFT
    for fid in [f["id"] for f in STORES["ffrs"].values() if f["award_id"] == aid]:
        del STORES["ffrs"][fid]
    f = stamp_new({
        "id": new_id(), "award_id": aid, "status": "DRAFT",
        "unliquidated_obligations_cents": None, "total_expenditures_cents": None,
        "cost_share_shortfall_cents": 0, "residual_cents": None, "return_reason": None,
    })
    STORES["ffrs"][f["id"]] = f
    recompute_posture(a)
    touch(a)
    return ok(sz.award(a))


@bp.post("/api/awards/<aid>/reopen")
def reopen_award(aid):
    auth()
    require_role(auth_role(), ["SponsorOfficial"])
    a = get_or_404("awards", aid, "ERR_AWARD_NOT_FOUND")
    if a["status"] != "CLOSEOUT_PENDING":
        raise err("ERR_AWARD_NOT_IN_CLOSEOUT", "Reopen requires award status CLOSEOUT_PENDING")
    f = award_ffr(aid)
    if f is not None and f["status"] in ("DRAFT", "RETURNED"):
        del STORES["ffrs"][f["id"]]
    a["status"] = "ACTIVE"
    recompute_posture(a)
    touch(a)
    return ok(sz.award(a))


@bp.post("/api/awards/<aid>/close")
def close_award(aid):
    auth()
    require_role(auth_role(), ["GrantsAccountant"])
    a = get_or_404("awards", aid, "ERR_AWARD_NOT_FOUND")
    if a["status"] != "CLOSEOUT_PENDING":
        raise err("ERR_AWARD_NOT_IN_CLOSEOUT", "Close requires award status CLOSEOUT_PENDING")
    f = award_ffr(aid)
    if f is None or f["status"] != "ACCEPTED":
        raise err("ERR_CLOSEOUT_INCOMPLETE", "FinalFinancialReport must be ACCEPTED")
    if any(r["award_id"] == aid and r["status"] in ("OPEN", "PARTIALLY_PAID", "DISPUTED")
           for r in STORES["receivables"].values()):
        raise err("ERR_CLOSEOUT_INCOMPLETE", "Open receivables remain")
    if any(d["award_id"] == aid and d["status"] in ("DRAFT", "SUBMITTED")
           for d in STORES["drawdowns"].values()):
        raise err("ERR_CLOSEOUT_INCOMPLETE", "Open drawdown requests remain")
    award_sub_ids = {s["id"] for s in STORES["subawards"].values() if s["award_id"] == aid}
    if any(i["subaward_id"] in award_sub_ids and i["status"] in ("RECEIVED", "UNDER_REVIEW")
           for i in STORES["invoices"].values()):
        raise err("ERR_CLOSEOUT_INCOMPLETE", "Subaward invoices in flight remain")
    if any(r["award_id"] == aid and r["status"] != "ACCEPTED"
           for r in STORES["reports"].values()):
        raise err("ERR_CLOSEOUT_INCOMPLETE", "All report requirements must be ACCEPTED")
    a["residual_deobligated_cents"] = a["total_obligated_cents"] - a["cumulative_drawn_cents"]
    a["total_obligated_cents"] = a["cumulative_drawn_cents"]
    a["status"] = "CLOSED"
    touch(a)
    return ok(sz.award(a))


# ---------------------------------------------------------------------------
# budget lines
# ---------------------------------------------------------------------------

@bp.post("/api/budget-lines")
def create_budget_line():
    auth()
    require_role(auth_role(), ["GrantCoordinator"])
    b = body()
    sh = Shape()
    award_id = sh_str(b, "award_id", sh)
    category = sh_str(b, "category", sh)
    if category is not None and category not in CATEGORIES:
        sh.bad = True
    authorized = sh_int(b, "authorized_cents", sh, min_v=0)
    mtdc_eligible = sh_int(b, "mtdc_eligible_cents", sh, required=False, min_v=0, default=0)
    a = get_or_404("awards", award_id, "ERR_AWARD_NOT_FOUND") if award_id else None
    if a is not None:
        # state: lines load only while PENDING_SETUP
        if a["status"] != "PENDING_SETUP":
            raise err("ERR_AWARD_NOT_ACTIVE", "Budget lines load only while the award is PENDING_SETUP")
        # structural: F_AND_A category is system-managed
        if category == "F_AND_A":
            raise err("ERR_F_AND_A_LINE_SYSTEM_MANAGED", "The F_AND_A budget line is system-managed")
        # fiscal: SUBAWARDS mtdc_eligible must not exceed authorized
        if (category == "SUBAWARDS" and authorized is not None and mtdc_eligible is not None
                and mtdc_eligible > authorized):
            raise err("ERR_MTDC_ELIGIBLE_EXCEEDS_AUTHORIZED",
                      "mtdc_eligible_cents exceeds authorized_cents")
    sh.raise_if_bad()
    line = stamp_new({
        "id": new_id(), "award_id": award_id, "category": category,
        "authorized_cents": authorized, "baseline_authorized_cents": 0, "spent_cents": 0,
        "mtdc_eligible_cents": mtdc_eligible if (category == "SUBAWARDS" and mtdc_eligible) else 0,
    })
    STORES["budget_lines"][line["id"]] = line
    recompute_fna_line(a)
    touch(a)  # every budget-line load increments the parent award version
    return ok_created(sz.budget_line(line))


@bp.get("/api/budget-lines")
def list_budget_lines():
    auth()
    filters = {
        lambda l: l["award_id"]: request.args.get("award_id"),
        lambda l: l["category"]: request.args.get("category"),
    }
    items, total, limit, offset = list_page("budget_lines", sz.budget_line, filters)
    return ok_list(items, total, limit, offset)


@bp.get("/api/budget-lines/<lid>")
def get_budget_line(lid):
    auth()
    return ok(sz.budget_line(get_or_404("budget_lines", lid, "ERR_BUDGET_LINE_NOT_FOUND")))


# ---------------------------------------------------------------------------
# effort commitments
# ---------------------------------------------------------------------------

@bp.post("/api/effort-commitments")
def create_commitment():
    auth()
    require_role(auth_role(), ["GrantCoordinator"])
    b = body()
    sh = Shape()
    award_id = sh_str(b, "award_id", sh)
    person_id = sh_str(b, "person_id", sh)
    pct = sh_pct(b, "committed_effort_pct", sh, lo_exclusive=0, hi_inclusive=100)
    key = b.get("is_key_personnel", False)
    if not isinstance(key, bool):
        sh.bad = True
        key = False
    a = get_or_404("awards", award_id, "ERR_AWARD_NOT_FOUND") if award_id else None
    p = get_or_404("persons", person_id, "ERR_PERSON_NOT_FOUND") if person_id else None
    if a is not None:
        if a["status"] not in ("PENDING_SETUP", "ACTIVE"):
            raise err("ERR_AWARD_NOT_ACTIVE",
                      "Commitments record only while the award is PENDING_SETUP or ACTIVE")
        if p is not None and any(c["award_id"] == award_id and c["person_id"] == person_id
                                 for c in STORES["commitments"].values()):
            raise err("ERR_DUPLICATE_COMMITMENT", "Commitment already exists for (award_id, person_id)")
    sh.raise_if_bad()
    c = {"id": new_id(), "award_id": award_id, "person_id": person_id,
         "committed_effort_pct": float(pct), "is_key_personnel": key}
    from util import now_iso
    c["created_at"] = now_iso()  # commitments carry only id + created_at
    STORES["commitments"][c["id"]] = c
    return ok_created(sz.commitment(c))


@bp.get("/api/effort-commitments")
def list_commitments():
    auth()
    filters = {
        lambda c: c["award_id"]: request.args.get("award_id"),
        lambda c: c["person_id"]: request.args.get("person_id"),
    }
    items, total, limit, offset = list_page("commitments", sz.commitment, filters)
    return ok_list(items, total, limit, offset)


@bp.get("/api/effort-commitments/<cid>")
def get_commitment(cid):
    auth()
    return ok(sz.commitment(get_or_404("commitments", cid, "ERR_COMMITMENT_NOT_FOUND")))
