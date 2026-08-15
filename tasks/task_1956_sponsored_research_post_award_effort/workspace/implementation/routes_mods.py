"""Routes: modification requests (NCE / rebudget) and final financial reports."""
from flask import Blueprint, request

import serializers as sz
from db import STORES, new_id, now_clock, stamp_new, touch
from errors import err
from middleware import (Shape, auth, body, get_or_404, list_page, require_role,
                        sh_int, sh_str)
from response import ok, ok_created, ok_list
from services import (SIGNIFICANCE_PCT, award_ffr, award_lines, fna_authorized,
                      recompute_award, recompute_fna_line, recompute_posture)
from util import add_months

bp = Blueprint("modifications", __name__)

MOD_TYPES = {"NO_COST_EXTENSION", "REBUDGET"}
MOD_STATUSES = {"DRAFT", "SUBMITTED", "SPONSOR_REVIEW", "APPROVED", "DENIED", "WITHDRAWN"}
FFR_STATUSES = {"DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED"}


# ---------------------------------------------------------------------------
# modification requests
# ---------------------------------------------------------------------------

def _parse_rebudget_lines(raw, sh):
    """Validate the rebudget_lines shape; returns list of (line_id, new_cents) or None."""
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw:
        sh.bad = True
        return None
    out = []
    for item in raw:
        if not isinstance(item, dict):
            sh.bad = True
            return None
        lid = item.get("budget_line_id")
        val = item.get("new_authorized_cents")
        if not isinstance(lid, str) or not lid:
            sh.bad = True
            return None
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            sh.bad = True
            return None
        out.append((lid, val))
    return out


def _significance(a, parsed):
    """rebudget_significance_test: requires_sponsor for REBUDGET requests."""
    for lid, new in parsed:
        line = STORES["budget_lines"].get(lid)
        if line is None:
            continue
        current = line["authorized_cents"]
        baseline = line["baseline_authorized_cents"]
        if new != current:
            if (baseline > 0 and abs(new - baseline) * 100 > SIGNIFICANCE_PCT * baseline) \
                    or (baseline == 0 and new > 0):
                return True  # exactly 25% is NOT significant (strict >)
        if line["category"] == "EQUIPMENT" and new > current:
            return True      # any net increase into EQUIPMENT
        if line["category"] == "PARTICIPANT_SUPPORT" and new < current:
            return True      # any net decrease out of PARTICIPANT_SUPPORT
    return False


@bp.post("/api/modification-requests")
def create_modification():
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantCoordinator"])
    b = body()
    sh = Shape()
    award_id = sh_str(b, "award_id", sh)
    mtype = sh_str(b, "mod_type", sh)
    if mtype is not None and mtype not in MOD_TYPES:
        sh.bad = True
    just = sh_str(b, "justification", sh, min_len=20)
    ext = sh_int(b, "extension_months", sh, required=False, min_v=1, max_v=12)
    parsed = _parse_rebudget_lines(b.get("rebudget_lines"), sh) if "rebudget_lines" in b else None
    if mtype == "NO_COST_EXTENSION" and ext is None:
        sh.bad = True
    if mtype == "REBUDGET" and parsed is None:
        sh.bad = True
    expected = b.get("expected_award_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        sh.bad = True
        expected = None
    # existence (4): award, then rebudget line ids in declared order
    a = get_or_404("awards", award_id, "ERR_AWARD_NOT_FOUND") if award_id else None
    if parsed is not None:
        for lid, _ in parsed:
            get_or_404("budget_lines", lid, "ERR_BUDGET_LINE_NOT_FOUND")
    if a is not None:
        # OCC (5)
        if expected is not None and expected != a["version"]:
            raise err("ERR_STALE_AWARD_VERSION",
                      "expected_award_version does not match the award's current version")
        # structural (10): F_AND_A lines forbidden in rebudgets
        if parsed is not None:
            for lid, _ in parsed:
                line = STORES["budget_lines"].get(lid)
                if line is not None and line["category"] == "F_AND_A":
                    raise err("ERR_F_AND_A_LINE_SYSTEM_MANAGED",
                              "F_AND_A lines are forbidden in rebudget_lines")
            # referential (11): every listed line belongs to this award
            for lid, _ in parsed:
                line = STORES["budget_lines"].get(lid)
                if line is not None and line["award_id"] != a["id"]:
                    raise err("ERR_BUDGET_LINE_AWARD_MISMATCH",
                              "rebudget line belongs to a different award than award_id")
    sh.raise_if_bad()
    # requires_sponsor computed at creation (NCE: second+ extension needs the sponsor)
    if mtype == "NO_COST_EXTENSION":
        requires = a["nce_count"] >= 1
    else:
        requires = _significance(a, parsed)
    m = stamp_new({
        "id": new_id(), "award_id": award_id, "mod_type": mtype,
        "extension_months": ext if mtype == "NO_COST_EXTENSION" else None,
        "rebudget_lines": ([{"budget_line_id": lid, "new_authorized_cents": v}
                            for lid, v in parsed] if mtype == "REBUDGET" and parsed else None),
        "justification": just, "requires_sponsor": requires, "status": "DRAFT",
        "sponsor_decision_reason": None,
    })
    STORES["modifications"][m["id"]] = m
    touch(a)  # modification create increments the award version
    return ok_created(sz.modification(m))


@bp.get("/api/modification-requests")
def list_modifications():
    auth()
    filters = {
        lambda m: m["award_id"]: request.args.get("award_id"),
        lambda m: m["status"]: request.args.get("status"),
        lambda m: m["mod_type"]: request.args.get("mod_type"),
    }
    items, total, limit, offset = list_page("modifications", sz.modification, filters)
    return ok_list(items, total, limit, offset)


@bp.get("/api/modification-requests/<mid>")
def get_modification(mid):
    auth()
    return ok(sz.modification(get_or_404("modifications", mid, "ERR_MODIFICATION_NOT_FOUND")))


@bp.post("/api/modification-requests/<mid>/submit")
def submit_modification(mid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantCoordinator"])
    m = get_or_404("modifications", mid, "ERR_MODIFICATION_NOT_FOUND")
    if m["status"] != "DRAFT":
        raise err("ERR_MODIFICATION_NOT_ACTIONABLE", "Submit requires status DRAFT")
    a = STORES["awards"][m["award_id"]]
    # state (6): SUSPENDED blocks modification submit; requires ACTIVE
    if a["status"] != "ACTIVE":
        raise err("ERR_AWARD_NOT_ACTIVE", "Modification submit requires award status ACTIVE")
    if m["mod_type"] == "NO_COST_EXTENSION":
        # temporal (9): NCE must be submitted before current_end_date
        if now_clock() >= a["current_end_date"]:
            raise err("ERR_NCE_AFTER_END_DATE",
                      "A no-cost extension must be submitted before current_end_date")
    else:
        # structural (10): grand-total invariant over authorized bases
        new_values = {l["budget_line_id"]: l["new_authorized_cents"] for l in m["rebudget_lines"]}
        directs = 0
        equip = part = subs = subs_mtdc = 0
        for line in award_lines(a["id"]):
            auth_new = new_values.get(line["id"], line["authorized_cents"])
            if line["category"] == "F_AND_A":
                continue
            directs += auth_new
            if line["category"] == "EQUIPMENT":
                equip += auth_new
            elif line["category"] == "PARTICIPANT_SUPPORT":
                part += auth_new
            elif line["category"] == "SUBAWARDS":
                subs += auth_new
                subs_mtdc += line.get("mtdc_eligible_cents", 0)
        mtdc = directs - equip - part - subs + subs_mtdc
        from util import D, rhu
        fna = rhu(D(a["f_and_a_rate_bps"]) * D(mtdc) / D(10000))
        if directs + fna != a["total_obligated_cents"]:
            raise err("ERR_REBUDGET_NOT_ZERO_SUM",
                      "Rebudget grand total (directs + recomputed F&A) must equal total_obligated_cents")
        # fiscal (12): SUBAWARDS line new authorized >= its mtdc_eligible_cents
        for lid, new in new_values.items():
            line = STORES["budget_lines"].get(lid)
            if line is not None and line["category"] == "SUBAWARDS" \
                    and new < line.get("mtdc_eligible_cents", 0):
                raise err("ERR_MTDC_ELIGIBLE_EXCEEDS_AUTHORIZED",
                          "SUBAWARDS line new authorized is below its mtdc_eligible_cents")
    m["status"] = "SUBMITTED"
    touch(m)
    return ok(sz.modification(m))


def _apply_effects(m, via_sponsor):
    """APPLY_EFFECTS (modification note, scaffold 1.2)."""
    a = STORES["awards"][m["award_id"]]
    if m["mod_type"] == "NO_COST_EXTENSION":
        a["current_end_date"] = add_months(a["current_end_date"], m["extension_months"])
        a["nce_count"] += 1
        for r in STORES["reports"].values():
            if (r["award_id"] == a["id"] and r["report_type"] == "FINAL_TECHNICAL"
                    and r["status"] != "ACCEPTED"):
                r["due_date"] = add_months(r["due_date"], m["extension_months"])
                touch(r)
    else:
        for l in m["rebudget_lines"]:
            line = STORES["budget_lines"].get(l["budget_line_id"])
            if line is not None:
                line["authorized_cents"] = l["new_authorized_cents"]
                touch(line)
        recompute_fna_line(a)  # F&A recomputed over the new authorized bases
        if via_sponsor:
            # sponsor-decision channel refreshes the baseline snapshot
            for line in award_lines(a["id"]):
                line["baseline_authorized_cents"] = line["authorized_cents"]
                touch(line)
    touch(a)  # either path bumps the award version


@bp.post("/api/modification-requests/<mid>/internal-approve")
def internal_approve(mid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["SponsoredProgramsOfficer"])
    m = get_or_404("modifications", mid, "ERR_MODIFICATION_NOT_FOUND")
    if m["status"] != "SUBMITTED":
        raise err("ERR_MODIFICATION_NOT_ACTIONABLE", "Internal-approve requires status SUBMITTED")
    if m["requires_sponsor"]:
        m["status"] = "SPONSOR_REVIEW"
    else:
        _apply_effects(m, via_sponsor=False)  # grantee authority: apply immediately
        m["status"] = "APPROVED"
    touch(m)
    return ok(sz.modification(m))


@bp.post("/api/modification-requests/<mid>/sponsor-decision")
def sponsor_decision(mid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["SponsorOfficial"])
    m = get_or_404("modifications", mid, "ERR_MODIFICATION_NOT_FOUND")
    if m["status"] != "SPONSOR_REVIEW":
        raise err("ERR_MODIFICATION_NOT_ACTIONABLE", "Sponsor-decision requires status SPONSOR_REVIEW")
    b = body()
    sh = Shape()
    decision = sh_str(b, "decision", sh)
    if decision is not None and decision not in ("APPROVE", "DENY"):
        sh.bad = True
    reason = sh_str(b, "reason", sh, required=False)
    sh.raise_if_bad()
    if decision == "APPROVE":
        _apply_effects(m, via_sponsor=True)
        m["status"] = "APPROVED"
    else:
        m["status"] = "DENIED"
        m["sponsor_decision_reason"] = reason
    touch(m)
    return ok(sz.modification(m))


@bp.post("/api/modification-requests/<mid>/withdraw")
def withdraw_modification(mid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantCoordinator"])
    m = get_or_404("modifications", mid, "ERR_MODIFICATION_NOT_FOUND")
    if m["status"] != "SUBMITTED":
        raise err("ERR_MODIFICATION_NOT_ACTIONABLE", "Withdraw requires status SUBMITTED")
    m["status"] = "WITHDRAWN"
    touch(m)
    return ok(sz.modification(m))


# ---------------------------------------------------------------------------
# final financial reports
# ---------------------------------------------------------------------------

@bp.get("/api/final-financial-reports")
def list_ffrs():
    auth()
    filters = {
        lambda f: f["award_id"]: request.args.get("award_id"),
        lambda f: f["status"]: request.args.get("status"),
    }
    items, total, limit, offset = list_page("ffrs", sz.ffr, filters)
    return ok_list(items, total, limit, offset)


@bp.get("/api/final-financial-reports/<fid>")
def get_ffr(fid):
    auth()
    return ok(sz.ffr(get_or_404("ffrs", fid, "ERR_FFR_NOT_FOUND")))


@bp.post("/api/final-financial-reports/<fid>/submit")
def submit_ffr(fid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["GrantsAccountant"])
    f = get_or_404("ffrs", fid, "ERR_FFR_NOT_FOUND")
    a = STORES["awards"].get(f["award_id"])
    # state (6): award in closeout, FFR actionable
    if a is None or a["status"] != "CLOSEOUT_PENDING":
        raise err("ERR_AWARD_NOT_IN_CLOSEOUT", "FFR submit requires award status CLOSEOUT_PENDING")
    if f["status"] not in ("DRAFT", "RETURNED"):
        raise err("ERR_FFR_NOT_ACTIONABLE", "FFR submit requires status DRAFT or RETURNED")
    aid = a["id"]
    sub_ids = {s["id"] for s in STORES["subawards"].values() if s["award_id"] == aid}
    if any(i["subaward_id"] in sub_ids and i["status"] in ("RECEIVED", "UNDER_REVIEW")
           for i in STORES["invoices"].values()):
        raise err("ERR_CLOSEOUT_INCOMPLETE", "Subaward invoices remain in RECEIVED or UNDER_REVIEW")
    if any(d["award_id"] == aid and d["status"] in ("DRAFT", "SUBMITTED")
           for d in STORES["drawdowns"].values()):
        raise err("ERR_CLOSEOUT_INCOMPLETE", "Drawdown requests remain in DRAFT or SUBMITTED")
    b = body()
    sh = Shape()
    unliq = sh_int(b, "unliquidated_obligations_cents", sh)
    # fiscal (12): all obligations must be liquidated
    if unliq is not None and unliq != 0:
        raise err("ERR_UNLIQUIDATED_OBLIGATIONS", "unliquidated_obligations_cents must be 0")
    sh.raise_if_bad()
    # snapshots at submit
    f["unliquidated_obligations_cents"] = unliq
    f["total_expenditures_cents"] = a["total_direct_spent_cents"] + a["f_and_a_accrued_cents"]
    f["residual_cents"] = a["total_obligated_cents"] - a["cumulative_drawn_cents"]
    f["cost_share_shortfall_cents"] = max(
        0, a["cost_share_committed_cents"] - a["cost_share_met_cents"])
    f["return_reason"] = None
    f["status"] = "SUBMITTED"
    touch(f)
    if a["payment_method"] == "LETTER_OF_CREDIT" and f["cost_share_shortfall_cents"] > 0:
        # final payment adjustment: the shortfall reduces the available pool (floor 0)
        a["_pool_reduction_cents"] = f["cost_share_shortfall_cents"]
        recompute_award(a)
        touch(a)
    return ok(sz.ffr(f))


@bp.post("/api/final-financial-reports/<fid>/accept")
def accept_ffr(fid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["SponsorOfficial"])
    f = get_or_404("ffrs", fid, "ERR_FFR_NOT_FOUND")
    if f["status"] != "SUBMITTED":
        raise err("ERR_FFR_NOT_ACTIONABLE", "FFR accept requires status SUBMITTED")
    f["status"] = "ACCEPTED"
    touch(f)
    a = STORES["awards"].get(f["award_id"])
    if a is not None:
        recompute_posture(a)  # FFR no longer outstanding
    return ok(sz.ffr(f))


@bp.post("/api/final-financial-reports/<fid>/return")
def return_ffr(fid):
    auth()
    require_role(request.headers.get("X-User-Role"), ["SponsorOfficial"])
    f = get_or_404("ffrs", fid, "ERR_FFR_NOT_FOUND")
    if f["status"] != "SUBMITTED":
        raise err("ERR_FFR_NOT_ACTIONABLE", "FFR return requires status SUBMITTED")
    b = body()
    sh = Shape()
    reason = sh_str(b, "return_reason", sh)
    sh.raise_if_bad()
    f["status"] = "RETURNED"
    f["return_reason"] = reason
    touch(f)
    return ok(sz.ffr(f))
