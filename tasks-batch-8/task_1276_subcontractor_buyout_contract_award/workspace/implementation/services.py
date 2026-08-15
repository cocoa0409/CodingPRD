"""Business logic: lookups, serializers, computed fields, cascades, calculations."""
from decimal import Decimal
from fractions import Fraction

from db import DB, now_iso
from errors import ApiError
from util import parse_dt, parse_ymd, round_half_up_cents

TERMINAL_SUB_STATES = ("DEFAULTED", "REPLACED", "TERMINATED")
MAX_NEGOTIATION_ROUNDS = 2
RETAINAGE_MIN = Decimal("0.05")
RETAINAGE_MAX = Decimal("0.10")
BONDING_POLICIES = ("REQUIRED", "PER_TRADE_RISK", "WAIVED")
GAP_CATEGORIES = ("SCOPE", "ALLOWANCE", "ALTERNATE", "INSURANCE_EXCLUSION", "LIFE_SAFETY")
RESOLUTION_KINDS = (
    "ALLOWANCE_WITH_QUALIFICATION",
    "ALTERNATE_ACCEPT",
    "CONTINGENCY_DRAW",
    "BID_CLARIFICATION",
)
WORKERS_COMP_KINDS = ("STATUTORY", "EXCESS_LIMIT")
EVALUATION_BASES = ("FULL_ENDORSEMENTS", "GAP_ANALYSIS")
TRADE_HISTORIES = ("CLEAN", "CLAIMS")

INS_SNAPSHOT_DEFAULTS = {
    "gl_occurrence_cents": 0,
    "gl_aggregate_cents": 0,
    "auto_cents": 0,
    "umbrella_cents": 0,
    "workers_comp": "STATUTORY",
    "ai_required": False,
    "wos_required": False,
    "ptd_required": False,
    "pollution_required": False,
}


# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------

def stamp(rec):
    t = now_iso()
    rec["created_at"] = t
    rec["updated_at"] = t
    rec["version"] = 1


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Lookups (existence, hierarchical left-to-right)
# ---------------------------------------------------------------------------

def _lookup(store, rid, label):
    rec = DB[store].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found")
    return rec


def get_project(rid):
    return _lookup("projects", rid, "Project")


def get_package(rid):
    return _lookup("trade_packages", rid, "TradePackage")


def get_bid(rid, pkg_id=None):
    bid = DB["bids"].get(rid)
    if bid is None or (pkg_id is not None and bid["trade_package_id"] != pkg_id):
        raise ApiError("ERR_NOT_FOUND", 404, "Bid not found")
    return bid


def get_gap(rid):
    return _lookup("scope_gaps", rid, "ScopeGap")


def get_subcontract(rid):
    return _lookup("subcontracts", rid, "Subcontract")


def get_sov(rid):
    return _lookup("schedule_of_values", rid, "ScheduleOfValues")


def get_change_order(rid):
    return _lookup("change_orders", rid, "ChangeOrder")


def project_of(pkg):
    return DB["projects"][pkg["project_id"]]


def package_of(sub):
    return DB["trade_packages"][sub["trade_package_id"]]


def subs_of(pkg):
    return [s for s in DB["subcontracts"].values() if s["trade_package_id"] == pkg["id"]]


def bids_of(pkg):
    return [b for b in DB["bids"].values() if b["trade_package_id"] == pkg["id"]]


def gaps_of(pkg):
    return [g for g in DB["scope_gaps"].values() if g["trade_package_id"] == pkg["id"]]


def certs_of(sub):
    return [c for c in DB["insurance_certificates"].values() if c["subcontract_id"] == sub["id"]]


def project_clock(project):
    return parse_dt(project["current_time_utc"])


def ensure_sub_not_terminal(sub):
    if sub["status"] in TERMINAL_SUB_STATES:
        raise ApiError(
            "ERR_SUBCONTRACT_TERMINAL",
            409,
            "Operation invalid on DEFAULTED / REPLACED / TERMINATED subcontract",
        )


def ensure_no_open_life_safety_gap(pkg):
    for g in gaps_of(pkg):
        if g["category"] == "LIFE_SAFETY" and g["status"] == "OPEN":
            raise ApiError(
                "ERR_UNRESOLVED_LIFE_SAFETY_GAP",
                409,
                "OPEN LIFE_SAFETY ScopeGap blocks award/issue",
            )


# ---------------------------------------------------------------------------
# Package financials (buyout_savings_vs_estimate)
# ---------------------------------------------------------------------------

def consumed_contingency(pkg):
    total = 0
    for g in gaps_of(pkg):
        if g["status"] == "RESOLVED" and g.get("resolution_kind") == "CONTINGENCY_DRAW":
            total += g.get("priced_amount_cents") or 0
    return total


def package_financials(pkg, basis="PROVISIONAL"):
    project = project_of(pkg)
    anchor_statuses = {"EXECUTED"} if basis == "PROVISIONAL" else {"EXECUTED", "PENDING_AWARD"}
    awarded = sum(
        s["contract_value_cents"] for s in subs_of(pkg) if s["status"] in anchor_statuses
    )
    consumed = consumed_contingency(pkg)
    savings = pkg["estimated_budget_cents"] - awarded - consumed
    target = round_half_up_cents(
        Decimal(str(project["buyout_target_savings_pct"]))
        * Decimal(pkg["estimated_budget_cents"])
    )
    if savings >= target:
        posture = "FAVORABLE"
    elif savings >= 0:
        posture = "NEUTRAL"
    else:
        posture = "UNFAVORABLE"
    return awarded, savings, posture


def recompute_package(pkg):
    awarded, savings, posture = package_financials(pkg, "PROVISIONAL")
    pkg["awarded_value_cents"] = awarded
    pkg["buyout_savings_cents"] = savings
    pkg["buyout_posture"] = posture
    touch(pkg)


# ---------------------------------------------------------------------------
# Bubble-up reconciliation (PRD section 2.8)
# ---------------------------------------------------------------------------

def evaluate_project_bubble(project):
    pkgs = [p for p in DB["trade_packages"].values() if p["project_id"] == project["id"]]
    if project["status"] == "BUYOUT_OPEN" and pkgs and all(
        p["status"] == "AWARDED" for p in pkgs
    ):
        project["status"] = "BUYOUT_COMPLETE"
        touch(project)


def evaluate_package_bubble(pkg):
    """Reconcile derived package/project states after a subcontract mutation."""
    subs = subs_of(pkg)
    executed = [s for s in subs if s["status"] == "EXECUTED"]
    project = project_of(pkg)
    if (
        pkg["status"] == "BUYOUT_IN_PROGRESS"
        and len(executed) == 1
        and all(s["status"] in ("EXECUTED",) + TERMINAL_SUB_STATES for s in subs)
    ):
        pkg["status"] = "AWARDED"
        touch(pkg)
        evaluate_project_bubble(project)
    elif pkg["status"] == "AWARDED" and len(executed) == 0:
        pkg["status"] = "BUYOUT_IN_PROGRESS"
        touch(pkg)
        if project["status"] == "BUYOUT_COMPLETE":
            project["status"] = "BUYOUT_OPEN"
            touch(project)


# ---------------------------------------------------------------------------
# Fiscal headroom (recommend-award / award)
# ---------------------------------------------------------------------------

def fiscal_cap(pkg):
    return pkg["estimated_budget_cents"] + (
        pkg["budgeted_contingency_cents"] - consumed_contingency(pkg)
    )


def projected_total(pkg, this_value_cents, exclude_sub_id=None):
    awarded = sum(
        s["contract_value_cents"] for s in subs_of(pkg) if s["status"] == "EXECUTED"
    )
    pending = sum(
        s["contract_value_cents"]
        for s in subs_of(pkg)
        if s["status"] == "PENDING_AWARD" and s["id"] != exclude_sub_id
    )
    return awarded + this_value_cents + pending


# ---------------------------------------------------------------------------
# Negotiation completeness + bid leveling
# ---------------------------------------------------------------------------

def check_negotiation_completeness(bid, dispositions, selections,
                                   dispositions_present, selections_present):
    allowances = bid.get("allowances") or []
    alternates = bid.get("alternates") or []
    if (allowances and not dispositions_present) or (alternates and not selections_present):
        raise ApiError(
            "ERR_NEGOTIATION_TERMS_INCOMPLETE",
            409,
            "Negotiation terms payload incomplete for the bid's allowances/alternates",
        )
    disp_by_id = {d.get("allowance_id"): d for d in (dispositions or [])}
    for a in allowances:
        if a.get("allowance_id") not in disp_by_id:
            raise ApiError(
                "ERR_ALLOWANCE_UNRESOLVED",
                409,
                "Outstanding allowance on the source bid lacks a disposition",
            )
    sel_by_id = {s.get("alternate_id"): s for s in (selections or [])}
    for a in alternates:
        if a.get("alternate_id") not in sel_by_id:
            raise ApiError(
                "ERR_ALTERNATE_UNRESOLVED",
                409,
                "Outstanding alternate on the source bid lacks a selection",
            )


def recompute_leveled_value(bid, round_rec):
    lv = bid["base_bid_cents"]
    alt_by_id = {a.get("alternate_id"): a for a in (bid.get("alternates") or [])}
    for sel in round_rec.get("alternate_selections") or []:
        alt = alt_by_id.get(sel.get("alternate_id"))
        if alt is not None and sel.get("selected") is True:
            lv += alt.get("price_delta_cents", 0)
    allow_by_id = {a.get("allowance_id"): a for a in (bid.get("allowances") or [])}
    for d in round_rec.get("allowance_dispositions") or []:
        allow = allow_by_id.get(d.get("allowance_id"))
        if allow is None:
            continue
        action = d.get("action")
        if action == "REPRICE":
            lv += d.get("priced_cents", allow["amount_cents"]) - allow["amount_cents"]
        elif action == "REJECT":
            lv -= allow["amount_cents"]
        # ACCEPT contributes 0
    bid["leveled_value_cents"] = lv
    touch(bid)


# ---------------------------------------------------------------------------
# Insurance compliance (insurance_compliance_check)
# ---------------------------------------------------------------------------

def _vp_waived_insurance_gap(pkg):
    for g in gaps_of(pkg):
        if (
            g["category"] == "INSURANCE_EXCLUSION"
            and g["status"] == "RESOLVED"
            and g.get("waived_by_role") == "VicePresident"
        ):
            return True
    return False


def evaluate_certificate(cert, sub, pkg, project):
    """Set compliance_verdict (and EXPIRED status on expiry failure) in place."""
    snap = sub["insurance_requirements_snapshot"]
    numeric_fail = (
        cert["gl_occurrence_cents"] < snap["gl_occurrence_cents"]
        or cert["gl_aggregate_cents"] < snap["gl_aggregate_cents"]
        or cert["auto_cents"] < snap["auto_cents"]
        or cert["umbrella_cents"] < snap["umbrella_cents"]
        or cert["workers_comp"] != "STATUTORY"
    )
    endorsement_fail = (
        (snap["ai_required"] and not cert["ai_endorsed"])
        or (snap["wos_required"] and not cert["wos_endorsed"])
        or (snap["ptd_required"] and not cert["ptd_endorsed"])
        or (snap["pollution_required"] and cert["pollution_cents"] == 0)
    )
    expiry_fail = parse_ymd(cert["expires_on"]) <= project_clock(project).date()
    if expiry_fail and cert["status"] == "ISSUED":
        cert["status"] = "EXPIRED"
    if numeric_fail or expiry_fail:
        verdict = "NON_COMPLIANT"
    elif endorsement_fail:
        if cert["evaluation_basis"] == "GAP_ANALYSIS" and _vp_waived_insurance_gap(pkg):
            verdict = "COMPLIANT_BY_GAP_ANALYSIS"
        else:
            verdict = "NON_COMPLIANT"
    else:
        verdict = "COMPLIANT"
    cert["compliance_verdict"] = verdict


def recompute_insurance_status(sub):
    certs = certs_of(sub)
    if any(
        c["compliance_verdict"] in ("COMPLIANT", "COMPLIANT_BY_GAP_ANALYSIS")
        for c in certs
    ):
        status = "COMPLIANT"
    elif certs and all(c["status"] == "EXPIRED" for c in certs):
        status = "EXPIRED_CERT_ONLY"
    elif any(c["compliance_verdict"] == "NON_COMPLIANT" for c in certs):
        status = "NON_COMPLIANT"
    else:
        status = "MISSING"
    if sub["insurance_status"] != status:
        sub["insurance_status"] = status
        touch(sub)


def reevaluate_certificates_for_project(project):
    """Clock advance: flip ISSUED certs whose expiry is reached by the new clock."""
    clock_date = project_clock(project).date()
    for pkg in [p for p in DB["trade_packages"].values() if p["project_id"] == project["id"]]:
        for sub in subs_of(pkg):
            changed = False
            for cert in certs_of(sub):
                if cert["status"] == "ISSUED" and parse_ymd(cert["expires_on"]) <= clock_date:
                    cert["status"] = "EXPIRED"
                    cert["compliance_verdict"] = "NON_COMPLIANT"
                    touch(cert)
                    changed = True
            if changed:
                recompute_insurance_status(sub)


def insurance_gate(sub, pkg, project):
    """Re-evaluate expiry against the current clock, then enforce COMPLIANT."""
    clock_date = project_clock(project).date()
    changed = False
    for cert in certs_of(sub):
        if cert["status"] == "ISSUED" and parse_ymd(cert["expires_on"]) <= clock_date:
            cert["status"] = "EXPIRED"
            cert["compliance_verdict"] = "NON_COMPLIANT"
            touch(cert)
            changed = True
    if changed:
        recompute_insurance_status(sub)
    status = sub["insurance_status"]
    if status == "COMPLIANT":
        return
    if status == "MISSING":
        raise ApiError("ERR_INSURANCE_MISSING", 409, "No insurance certificate on file")
    if status == "EXPIRED_CERT_ONLY":
        raise ApiError(
            "ERR_INSURANCE_CERT_EXPIRED", 409, "All certificates expired relative to the project clock"
        )
    raise ApiError(
        "ERR_INSURANCE_NON_COMPLIANT", 409, "Certificates on file evaluated NON_COMPLIANT"
    )


# ---------------------------------------------------------------------------
# Bonding (trade_risk_score + bond_premium_quote)
# ---------------------------------------------------------------------------

def trade_risk_score(sub, pkg, trade_history):
    cv = sub["contract_value_cents"]
    if cv < 5_000_000:
        value_score = 10
    elif cv <= 10_000_000:
        value_score = 20
    else:
        value_score = 35
    est = pkg["estimated_budget_cents"]
    if est > 0:
        size_score = 0 if Fraction(cv, est) <= Fraction(1, 4) else 25
    else:
        size_score = 25 if cv > 0 else 0
    history_score = 10 if trade_history == "CLEAN" else 25
    return max(0, min(100, value_score + size_score + history_score))


def bond_decision_for(policy, score):
    if policy == "REQUIRED":
        return "SURETY_BOND"
    if policy == "WAIVED":
        return "NOT_REQUIRED"
    if score <= 40:
        return "NOT_REQUIRED"
    if score <= 60:
        return "SURETY_BOND"
    return "SUBGUARD"


def bond_premium(decision, contract_value_cents):
    if decision == "NOT_REQUIRED":
        return 0
    rate = Decimal("0.015") if decision == "SURETY_BOND" else Decimal("0.010")
    return round_half_up_cents(Decimal(contract_value_cents) * rate)


# ---------------------------------------------------------------------------
# Schedule of values (sov_line_allocation)
# ---------------------------------------------------------------------------

def sov_allocate(lines, contract_value_cents):
    weights = [l["weight_numerator"] for l in lines]
    total_w = sum(weights)
    if total_w <= 0 or any(w < 1 for w in weights):
        raise ApiError(
            "ERR_SOV_IMBALANCE",
            409,
            "SOV allocation does not balance (non-positive total weight or weight < 1)",
        )
    allocations = []
    prev_cum = 0
    cumw = 0
    last = len(lines) - 1
    for i, w in enumerate(weights):
        cumw += w
        if i < last:
            cum_round = round_half_up_cents(
                Decimal(contract_value_cents * cumw) / Decimal(total_w)
            )
            allocations.append(cum_round - prev_cum)
            prev_cum = cum_round
        else:
            allocations.append(contract_value_cents - prev_cum)
    return allocations


# ---------------------------------------------------------------------------
# Change-order authority (change_authority_check)
# ---------------------------------------------------------------------------

def authority_check(sub, co, approver_role):
    tiers = [
        t
        for t in (sub.get("change_authority_limits") or [])
        if approver_role in (t.get("roles") or [])
    ]
    if not tiers:
        raise ApiError(
            "ERR_CO_AUTHORITY_EXCEEDED",
            409,
            "Change-order amount exceeds every authority tier available to the approver",
        )

    def sort_key(tier):
        mv = tier.get("max_value_cents", -1)
        return (1, 0) if mv == -1 else (0, mv)

    best = max(tiers, key=sort_key)
    if best.get("max_value_cents", -1) != -1 and co["amount_cents"] > best["max_value_cents"]:
        raise ApiError(
            "ERR_CO_AUTHORITY_EXCEEDED",
            409,
            "Change-order amount exceeds every authority tier available to the approver",
        )
    pct = best.get("max_cumulative_pct", -1)
    if pct != -1:
        numerator = sub["cumulative_co_cents"] + co["amount_cents"]
        cv = sub["contract_value_cents"]
        if cv <= 0:
            exceeds = numerator > 0
        else:
            exceeds = Fraction(numerator, cv) > Fraction(str(pct))
        if exceeds:
            raise ApiError(
                "ERR_CO_CUMULATIVE_LIMIT",
                409,
                "Cumulative approved change orders would exceed the approver tier's max_cumulative_pct",
            )


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_project(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "project_number": p["project_number"],
        "estimated_budget_cents": p["estimated_budget_cents"],
        "buyout_target_savings_pct": p["buyout_target_savings_pct"],
        "status": p["status"],
        "current_time_utc": p["current_time_utc"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_package(pkg, basis="PROVISIONAL"):
    awarded, savings, posture = package_financials(pkg, basis)
    return {
        "id": pkg["id"],
        "project_id": pkg["project_id"],
        "trade_code": pkg["trade_code"],
        "title": pkg["title"],
        "estimated_budget_cents": pkg["estimated_budget_cents"],
        "budgeted_contingency_cents": pkg["budgeted_contingency_cents"],
        "spec_section": pkg.get("spec_section"),
        "bid_due_at": pkg.get("bid_due_at"),
        "bonding_policy": pkg["bonding_policy"],
        "status": pkg["status"],
        "awarded_value_cents": awarded,
        "buyout_savings_cents": savings,
        "buyout_posture": posture,
        "created_at": pkg["created_at"],
        "updated_at": pkg["updated_at"],
        "version": pkg["version"],
    }


def ser_bid(b):
    return {
        "id": b["id"],
        "trade_package_id": b["trade_package_id"],
        "bidder_name": b["bidder_name"],
        "contact_email": b["contact_email"],
        "base_bid_cents": b["base_bid_cents"],
        "alternates": b.get("alternates") or [],
        "allowances": b.get("allowances") or [],
        "bid_received_at": b["bid_received_at"],
        "leveled_value_cents": b["leveled_value_cents"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_gap(g):
    return {
        "id": g["id"],
        "trade_package_id": g["trade_package_id"],
        "category": g["category"],
        "description": g["description"],
        "estimated_impact_cents": g.get("estimated_impact_cents"),
        "resolution_kind": g.get("resolution_kind"),
        "priced_amount_cents": g.get("priced_amount_cents"),
        "waived_by_role": g.get("waived_by_role"),
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def ser_subcontract(s):
    return {
        "id": s["id"],
        "trade_package_id": s["trade_package_id"],
        "subcontractor_name": s["subcontractor_name"],
        "source_bid_id": s["source_bid_id"],
        "replaces_subcontract_id": s.get("replaces_subcontract_id"),
        "replacement_subcontract_id": s.get("replacement_subcontract_id"),
        "flow_down_terms": s["flow_down_terms"],
        "insurance_requirements_snapshot": s["insurance_requirements_snapshot"],
        "payment_terms": s["payment_terms"],
        "change_authority_limits": s["change_authority_limits"],
        "contract_value_cents": s["contract_value_cents"],
        "cumulative_co_cents": s["cumulative_co_cents"],
        "negotiation_round": s["negotiation_round"],
        "insurance_status": s["insurance_status"],
        "bonding_requirement": s["bonding_requirement"],
        "sov_status": s["sov_status"],
        "default_flag": s["default_flag"],
        "default_recorded_at": s.get("default_recorded_at"),
        "estimated_replacement_cost_cents": s.get("estimated_replacement_cost_cents"),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_round(r):
    return {
        "id": r["id"],
        "subcontract_id": r["subcontract_id"],
        "round_index": r["round_index"],
        "proposed_value_cents": r["proposed_value_cents"],
        "allowance_dispositions": r.get("allowance_dispositions") or [],
        "alternate_selections": r.get("alternate_selections") or [],
        "note": r.get("note"),
        "recorded_at": r["recorded_at"],
        "created_at": r["created_at"],
    }


def ser_cert(c):
    return {
        "id": c["id"],
        "subcontract_id": c["subcontract_id"],
        "certificate_number": c["certificate_number"],
        "gl_occurrence_cents": c["gl_occurrence_cents"],
        "gl_aggregate_cents": c["gl_aggregate_cents"],
        "auto_cents": c["auto_cents"],
        "umbrella_cents": c["umbrella_cents"],
        "workers_comp": c["workers_comp"],
        "ai_endorsed": c["ai_endorsed"],
        "wos_endorsed": c["wos_endorsed"],
        "ptd_endorsed": c["ptd_endorsed"],
        "pollution_cents": c["pollution_cents"],
        "expires_on": c["expires_on"],
        "evaluation_basis": c["evaluation_basis"],
        "compliance_verdict": c["compliance_verdict"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_bond(b):
    return {
        "id": b["id"],
        "subcontract_id": b["subcontract_id"],
        "trade_risk_score": b["trade_risk_score"],
        "trade_history": b["trade_history"],
        "decision": b["decision"],
        "premium_cents": b["premium_cents"],
        "decided_by_user_id": b["decided_by_user_id"],
        "decision_rationale": b.get("decision_rationale"),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_sov(s):
    return {
        "id": s["id"],
        "subcontract_id": s["subcontract_id"],
        "revision_number": s["revision_number"],
        "lines": s["lines"],
        "status": s["status"],
        "approved_at": s.get("approved_at"),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_change_order(c):
    return {
        "id": c["id"],
        "subcontract_id": c["subcontract_id"],
        "description": c["description"],
        "amount_cents": c["amount_cents"],
        "initiating_role": c.get("initiating_role"),
        "approval_roles_received": c["approval_roles_received"],
        "created_by_user_id": c["created_by_user_id"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def sorted_created(records):
    return sorted(records, key=lambda r: r["created_at"])
