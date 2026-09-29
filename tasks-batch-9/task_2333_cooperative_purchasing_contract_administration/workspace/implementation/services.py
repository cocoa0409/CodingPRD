"""Cascades, derived-field recomputation and shared lookups (PRD 2.10)."""

from decimal import Decimal

import calc
from calc import D, cents, num, pct2, rhu
from db import create_row, db, get_dt, iso, logical_now, ordered, set_dt
from middleware import register_new, touch

LIVE_USAGE_STATUSES = ("RECORDED", "CONFIRMED")
LEDGER_REPORT_STATUSES = ("ACCEPTED", "RECONCILED")
NON_REJECTED_REPORT_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED", "RECONCILED")
CHARGED_COMPLAINT_STATUSES = ("SUBSTANTIATED", "APPEALED", "CLOSED")


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def contracts_of_supplier(supplier_id):
    return [c for c in ordered(db.contracts) if c["supplier_id"] == supplier_id]


def contracts_of_solicitation(solicitation_id):
    return [c for c in ordered(db.contracts)
            if c["solicitation_id"] == solicitation_id]


def line_items_of_contract(contract_id):
    return [li for li in ordered(db.line_items) if li["contract_id"] == contract_id]


def analyses_of_contract(contract_id):
    return [a for a in ordered(db.analyses) if a["contract_id"] == contract_id]


def analyses_of_member(member_id):
    return [a for a in ordered(db.analyses) if a["member_agency_id"] == member_id]


def reports_of_contract(contract_id):
    return [r for r in ordered(db.reports) if r["contract_id"] == contract_id]


def reports_of_supplier(supplier_id):
    ids = set(c["id"] for c in contracts_of_supplier(supplier_id))
    return [r for r in ordered(db.reports) if r["contract_id"] in ids]


def complaints_of_supplier(supplier_id):
    ids = set(c["id"] for c in contracts_of_supplier(supplier_id))
    return [c for c in ordered(db.complaints) if c["contract_id"] in ids]


def usages_of_contract(contract_id):
    return [u for u in ordered(db.usages) if u["contract_id"] == contract_id]


def usages_of_member(member_id):
    return [u for u in ordered(db.usages) if u["member_agency_id"] == member_id]


def responses_of_solicitation(solicitation_id):
    return [r for r in ordered(db.responses)
            if r["solicitation_id"] == solicitation_id]


def rule_for_state(state_code):
    for rule in db.state_law_rules.values():
        if rule["state_code"] == state_code:
            return rule
    return None


# --------------------------------------------------------------------------
# piggyback opinion voiding
# --------------------------------------------------------------------------

def void_analyses(analyses, reason):
    for analysis in analyses:
        analysis["status"] = "VOIDED"
        analysis["voided_reason"] = reason
        touch(analysis)


def void_contract_determined(contract, reason):
    void_analyses(
        [a for a in analyses_of_contract(contract["id"]) if a["status"] == "DETERMINED"],
        reason,
    )


# --------------------------------------------------------------------------
# contract execution cascades driven by the system
# --------------------------------------------------------------------------

def system_suspend_contract(contract):
    """ACTIVE -> SUSPENDED plus its own hop (voiding DETERMINED opinions)."""
    if contract["status"] != "ACTIVE":
        return False
    contract["status"] = "SUSPENDED"
    touch(contract)
    void_contract_determined(contract, "CONTRACT_SUSPENDED")
    return True


def withdraw_line_items(contract):
    for line in line_items_of_contract(contract["id"]):
        if line["status"] != "WITHDRAWN":
            line["status"] = "WITHDRAWN"
            touch(line)


def system_terminate_contract(contract):
    previous = contract["status"]
    if previous not in ("PENDING_EXECUTION", "ACTIVE", "SUSPENDED"):
        return False
    contract["status"] = "TERMINATED"
    touch(contract)
    withdraw_line_items(contract)
    if previous in ("ACTIVE", "SUSPENDED"):
        void_contract_determined(contract, "CONTRACT_TERMINATED")
    return True


def system_suspend_supplier(supplier):
    """QUALIFIED -> SUSPENDED with both hops (PRD 3.1)."""
    if supplier["qualification_status"] != "QUALIFIED":
        return False
    supplier["qualification_status"] = "SUSPENDED"
    touch(supplier)
    for contract in contracts_of_supplier(supplier["id"]):
        system_suspend_contract(contract)
    return True


# --------------------------------------------------------------------------
# supplier performance (PRD 3.9)
# --------------------------------------------------------------------------

def recompute_supplier_performance(supplier):
    total = Decimal("0.00")
    for complaint in complaints_of_supplier(supplier["id"]):
        if complaint["status"] in CHARGED_COMPLAINT_STATUSES and not complaint[
                "points_reversed"]:
            total += calc.DEDUCTION_POINTS_BY_SEVERITY.get(
                complaint["severity"], Decimal("0.00"))
    reports = reports_of_supplier(supplier["id"])
    flagged = sum(1 for r in reports if r.get("variance_flagged"))
    delinquent = sum(1 for r in reports if r.get("fee_status") == "DELINQUENT")
    total += calc.VARIANCE_DEDUCTION_POINTS * Decimal(flagged)
    total += calc.DELINQUENCY_DEDUCTION_POINTS * Decimal(delinquent)
    total = pct2(total)

    score = pct2(Decimal(100) - total)
    if score < Decimal("0.00"):
        score = pct2(Decimal("0.00"))
    if score > Decimal("100.00"):
        score = pct2(Decimal("100.00"))
    tier = calc.performance_tier(score)

    substantiated = sum(
        1 for c in complaints_of_supplier(supplier["id"])
        if c["status"] in CHARGED_COMPLAINT_STATUSES and not c["points_reversed"]
    )

    changed = (
        num(total) != supplier["deduction_points_total"]
        or num(score) != supplier["performance_score"]
        or tier != supplier["performance_tier"]
        or substantiated != supplier["substantiated_complaint_count"]
        or delinquent != supplier["delinquent_report_count"]
    )
    supplier["deduction_points_total"] = num(total)
    supplier["performance_score"] = num(score)
    supplier["performance_tier"] = tier
    supplier["substantiated_complaint_count"] = substantiated
    supplier["delinquent_report_count"] = delinquent
    if changed:
        touch(supplier)

    # A tier rewritten to PROBATION suspends the supplier without any request.
    if tier == "PROBATION":
        system_suspend_supplier(supplier)


# --------------------------------------------------------------------------
# member / contract usage ledgers (PRD 3.6)
# --------------------------------------------------------------------------

def recompute_member_committed_spend(member):
    total = 0
    for usage in usages_of_member(member["id"]):
        if usage["status"] in LIVE_USAGE_STATUSES:
            total += int(usage["total_cents"])
    if member["committed_spend_cents"] != total:
        member["committed_spend_cents"] = total
        touch(member)


def recompute_contract_usage_total(contract):
    total = 0
    for usage in usages_of_contract(contract["id"]):
        if usage["status"] in LIVE_USAGE_STATUSES:
            total += int(usage["chargeable_base_cents"])
    if contract["usage_chargeable_cents_total"] != total:
        contract["usage_chargeable_cents_total"] = total
        touch(contract)


# --------------------------------------------------------------------------
# fee ledgers (PRD 3.7)
# --------------------------------------------------------------------------

def _ledger_over(reports):
    assessed = 0
    remitted = 0
    for report in reports:
        if report["status"] in LEDGER_REPORT_STATUSES:
            assessed += int(report["reported_fee_cents"])
            remitted += int(report["remitted_cents"])
        if report["status"] == "RECONCILED" and report["fee_true_up_cents"] is not None:
            assessed += int(report["fee_true_up_cents"])
    return assessed, remitted


def recompute_contract_fee_ledger(contract):
    assessed, remitted = _ledger_over(reports_of_contract(contract["id"]))
    outstanding = assessed - remitted
    changed = (
        contract["fee_assessed_cents_total"] != assessed
        or contract["fee_remitted_cents_total"] != remitted
        or contract["fee_outstanding_cents"] != outstanding
    )
    contract["fee_assessed_cents_total"] = assessed
    contract["fee_remitted_cents_total"] = remitted
    contract["fee_outstanding_cents"] = outstanding
    if changed:
        touch(contract)
    return outstanding


def recompute_supplier_fee_ledger(supplier):
    assessed, remitted = _ledger_over(reports_of_supplier(supplier["id"]))
    changed = (
        supplier["fee_assessed_cents_total"] != assessed
        or supplier["fee_remitted_cents_total"] != remitted
    )
    supplier["fee_assessed_cents_total"] = assessed
    supplier["fee_remitted_cents_total"] = remitted
    if changed:
        touch(supplier)


# --------------------------------------------------------------------------
# compliance posture (PRD 3.7)
# --------------------------------------------------------------------------

def recompute_compliance_posture(contract):
    delinquent = [r for r in reports_of_contract(contract["id"])
                  if r["fee_status"] == "DELINQUENT"]
    count = len(delinquent)
    outstanding = sum(int(r["reported_fee_cents"]) - int(r["remitted_cents"])
                      for r in delinquent)
    if count >= calc.DELINQUENCY_COUNT_THRESHOLD or (
            outstanding >= calc.DELINQUENCY_AMOUNT_THRESHOLD_CENTS and count >= 1):
        posture = "DELINQUENT"
    elif count == 1:
        posture = "WATCH"
    else:
        posture = "COMPLIANT"

    changed = (contract["compliance_posture"] != posture
               or contract["delinquent_report_count"] != count)
    contract["compliance_posture"] = posture
    contract["delinquent_report_count"] = count
    if changed:
        touch(contract)

    # Only the count trigger suspends the contract.
    if posture == "DELINQUENT" and count >= calc.DELINQUENCY_COUNT_THRESHOLD:
        system_suspend_contract(contract)
    return posture


# --------------------------------------------------------------------------
# report period sweep (PRD 3.7)
# --------------------------------------------------------------------------

def sweep_report(report, contract):
    period_start = get_dt(report, "period_start")
    period_end = get_dt(report, "period_end")
    swept = []
    for usage in usages_of_contract(contract["id"]):
        if usage["status"] != "CONFIRMED":
            continue
        ordered_at = get_dt(usage, "ordered_at")
        if ordered_at is None or ordered_at < period_start or ordered_at > period_end:
            continue
        if usage["usage_report_id"] not in (None, report["id"]):
            continue
        swept.append(usage)
    swept.sort(key=lambda u: (get_dt(u, "ordered_at"), u.get("created_at") or "",
                              u.get("_seq") or 0))

    chargeable = sum(int(u["chargeable_base_cents"]) for u in swept)
    usage_total = sum(int(u["total_cents"]) for u in swept)

    for usage in swept:
        if usage["usage_report_id"] != report["id"]:
            usage["usage_report_id"] = report["id"]
            touch(usage)

    report["swept_usage_count"] = len(swept)
    report["reported_chargeable_cents"] = chargeable
    report["reported_usage_cents"] = usage_total
    report["reported_fee_cents"] = calc.reported_fee(
        chargeable, contract["admin_fee_rate_bps"])
    return swept


def clear_sweep(report):
    for usage in ordered(db.usages):
        if usage["usage_report_id"] == report["id"]:
            usage["usage_report_id"] = None
            touch(usage)
    report["swept_usage_count"] = 0
    report["reported_chargeable_cents"] = 0
    report["reported_usage_cents"] = 0
    report["reported_fee_cents"] = 0


def swept_usages(report):
    return [u for u in ordered(db.usages) if u["usage_report_id"] == report["id"]]


# --------------------------------------------------------------------------
# solicitation audit package (PRD 3.2)
# --------------------------------------------------------------------------

def mark_audit_stale(solicitation):
    status = solicitation["audit_package_status"]
    if status not in ("ASSEMBLED", "CERTIFIED"):
        return
    solicitation["audit_package_status"] = "STALE"
    solicitation["audit_completeness_pct"] = None
    if status == "CERTIFIED":
        solicitation["certified_at"] = None
        solicitation["_dt"]["certified_at"] = None
        solicitation["certified_by_user_id"] = None
    touch(solicitation)


def assemble_audit_package(solicitation):
    responses = responses_of_solicitation(solicitation["id"])
    responsive = [r for r in responses if r["status"] == "RESPONSIVE"]
    contracts = contracts_of_solicitation(solicitation["id"])
    contract_ids = set(c["id"] for c in contracts)
    has_approved_amendment = any(
        a["status"] == "APPROVED" and a["contract_id"] in contract_ids
        for a in db.amendments.values()
    )

    required = list(calc.BASE_AUDIT_DOC_CODES)
    if has_approved_amendment:
        required.append(calc.AMENDMENT_LOG_CODE)

    posted = solicitation["posted_at"] is not None
    responsive_count = int(solicitation["responsive_response_count"])
    every_scored = responsive_count >= 1 and all(
        r["technical_score"] is not None for r in responsive)

    evidence = {
        "NOTICE_OF_SOLICITATION": posted,
        "SPECIFICATION_PACKAGE": solicitation["specification_document_ref"] is not None,
        "PROCUREMENT_METHOD_JUSTIFICATION":
            solicitation["method_justification_ref"] is not None,
        "ADDENDA_LOG": posted,
        "RESPONSE_TABULATION": responsive_count >= 1,
        "EVALUATION_SCORESHEET": every_scored,
        "AWARD_RECOMMENDATION": solicitation["status"] in ("AWARD_PENDING", "AWARDED"),
        "CONTRACT_EXECUTION": any(
            c["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED", "TERMINATED")
            for c in contracts),
        "AMENDMENT_LOG": solicitation["amendment_log_document_ref"] is not None,
    }

    present = [code for code in required if evidence.get(code)]
    pct = pct2(Decimal(100) * Decimal(len(present)) / Decimal(len(required)))

    solicitation["audit_required_doc_codes"] = required
    solicitation["audit_present_doc_codes"] = present
    solicitation["audit_completeness_pct"] = num(pct)


# --------------------------------------------------------------------------
# solicitation scoring (PRD 3.2)
# --------------------------------------------------------------------------

def score_solicitation(solicitation):
    responsive = [r for r in responses_of_solicitation(solicitation["id"])
                  if r["status"] == "RESPONSIVE"]
    scored = calc.score_responses(
        responsive,
        solicitation["technical_weight_pct"],
        solicitation["price_weight_pct"],
    )
    for entry in scored:
        response = entry["response"]
        response["price_score"] = num(entry["price_score"])
        response["composite_score"] = num(entry["composite_score"])
        response["award_rank"] = entry["award_rank"]
        touch(response)


def rank_one_response(solicitation_id):
    for response in responses_of_solicitation(solicitation_id):
        if response["status"] == "RESPONSIVE" and response["award_rank"] == 1:
            return response
    return None


# --------------------------------------------------------------------------
# line item construction (shared by award publishing and expansions)
# --------------------------------------------------------------------------

def active_skus(contract_id):
    return set(li["sku"] for li in line_items_of_contract(contract_id)
               if li["status"] != "WITHDRAWN")


def build_line_item(contract, spec, origin):
    row = create_row(
        db.line_items,
        contract_id=contract["id"],
        sku=spec["sku"],
        item_description=spec["item_description"],
        unit_of_measure=spec["unit_of_measure"],
        base_unit_price_cents=spec["base_unit_price_cents"],
        price_floor_cents=spec["price_floor_cents"],
        origin=origin,
        status="ACTIVE",
        price_effective_from=None,
        last_price_change_at=None,
        price_change_count=0,
    )
    set_dt(row, "price_effective_from", contract["base_term_start"])
    set_dt(row, "last_price_change_at", None)
    register_new(row)
    return row
