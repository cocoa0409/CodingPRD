"""Shared domain services: lookups, rollups, consent posture, cascades."""

from datetime import timedelta

import calc
import db
from errors import fail
from validation import DEEMED_CONSENT_COUNTIES

# --------------------------------------------------------------------------
# Lookups (ladder stages 4 and 5)
# --------------------------------------------------------------------------
def find(collection, row_id, error_id):
    row = db.get(collection, row_id)
    if row is None:
        fail(error_id, "%s does not identify a live row" % row_id)
    return row


def get_property(row_id):
    return find("properties", row_id, "ERR_PROPERTY_NOT_FOUND")


def get_lien(row_id):
    return find("liens", row_id, "ERR_MORTGAGE_LIEN_NOT_FOUND")


def get_product(row_id):
    return find("products", row_id, "ERR_PRODUCT_NOT_FOUND")


def get_contractor(row_id):
    return find("contractors", row_id, "ERR_CONTRACTOR_NOT_FOUND")


def get_application(row_id):
    return find("applications", row_id, "ERR_APPLICATION_NOT_FOUND")


def get_measure(row_id):
    return find("measures", row_id, "ERR_MEASURE_NOT_FOUND")


def get_agreement(row_id):
    return find("agreements", row_id, "ERR_AGREEMENT_NOT_FOUND")


def get_certificate(row_id):
    return find("certificates", row_id, "ERR_CERTIFICATE_NOT_FOUND")


def get_disbursement(row_id):
    return find("disbursements", row_id, "ERR_DISBURSEMENT_NOT_FOUND")


def get_complaint(row_id):
    return find("complaints", row_id, "ERR_COMPLAINT_NOT_FOUND")


def get_assessment(row_id):
    return find("assessments", row_id, "ERR_ASSESSMENT_NOT_FOUND")


def get_installment(row_id):
    return find("installments", row_id, "ERR_INSTALLMENT_NOT_FOUND")


def get_transfer(row_id):
    return find("transfers", row_id, "ERR_TRANSFER_NOT_FOUND")


# --------------------------------------------------------------------------
# Collection helpers
# --------------------------------------------------------------------------
def liens_of(property_id):
    return db.by_created_at([row for row in db.rows("liens") if row["property_id"] == property_id])


def active_liens_of(property_id):
    return [row for row in liens_of(property_id) if row["status"] == "ACTIVE"]


def measures_of(application_id):
    return db.by_created_at(
        [row for row in db.rows("measures") if row["application_id"] == application_id]
    )


def live_measures_of(application_id):
    return [
        row
        for row in measures_of(application_id)
        if row["status"] in ("PROPOSED", "APPROVED")
    ]


def agreements_of(application_id):
    return db.by_created_at(
        [row for row in db.rows("agreements") if row["application_id"] == application_id]
    )


def certificates_of(application_id):
    return db.by_created_at(
        [row for row in db.rows("certificates") if row["application_id"] == application_id]
    )


def disbursements_of_application(application_id):
    return db.by_created_at(
        [row for row in db.rows("disbursements") if row["application_id"] == application_id]
    )


def disbursements_of_contractor(contractor_id):
    return db.by_created_at(
        [row for row in db.rows("disbursements") if row["contractor_id"] == contractor_id]
    )


def complaints_of_application(application_id):
    return db.by_created_at(
        [row for row in db.rows("complaints") if row["application_id"] == application_id]
    )


def complaints_of_contractor(contractor_id):
    return db.by_created_at(
        [row for row in db.rows("complaints") if row["contractor_id"] == contractor_id]
    )


def applications_of_property(property_id):
    return db.by_created_at(
        [row for row in db.rows("applications") if row["property_id"] == property_id]
    )


def applications_of_contractor(contractor_id):
    return db.by_created_at(
        [row for row in db.rows("applications") if row["contractor_id"] == contractor_id]
    )


def assessments_of_property(property_id):
    return db.by_created_at(
        [row for row in db.rows("assessments") if row["property_id"] == property_id]
    )


def installments_of(assessment_id):
    return sorted(
        [row for row in db.rows("installments") if row["assessment_id"] == assessment_id],
        key=lambda row: row["sequence"],
    )


def transfers_of(assessment_id):
    return db.by_created_at(
        [row for row in db.rows("transfers") if row["assessment_id"] == assessment_id]
    )


def live_agreement_of(application_id):
    """The agreement that still governs the deal, if any."""
    ranked = {"EFFECTIVE": 0, "SIGNED": 1, "RECORDED": 2, "ISSUED": 3}
    candidates = [row for row in agreements_of(application_id) if row["status"] in ranked]
    if not candidates:
        return None
    candidates.sort(key=lambda row: (ranked[row["status"]], row["created_at"]))
    return candidates[0]


# --------------------------------------------------------------------------
# Parcel rollups (PRD 2.8)
# --------------------------------------------------------------------------
def recompute_property_rollups(prop, bump=True):
    senior = sum(
        int(row["current_balance_cents"]) for row in active_liens_of(prop["id"])
    )
    recorded = sum(
        int(row["principal_balance_cents"])
        for row in assessments_of_property(prop["id"])
        if row["billing_status"] in ("PENDING_ROLL", "ON_ROLL")
    )
    committed = recorded
    for application in applications_of_property(prop["id"]):
        for agreement in agreements_of(application["id"]):
            if agreement["status"] in ("SIGNED", "EFFECTIVE"):
                committed += int(agreement["financed_amount_cents"])
    equity = calc.equity_ratio_bps(senior, prop["assessed_value_cents"])
    changed = (
        prop.get("senior_lien_balance_cents") != senior
        or prop.get("equity_ratio_bps") != equity
        or prop.get("recorded_pace_principal_cents") != recorded
        or prop.get("committed_pace_principal_cents") != committed
    )
    prop["senior_lien_balance_cents"] = senior
    prop["equity_ratio_bps"] = equity
    prop["recorded_pace_principal_cents"] = recorded
    prop["committed_pace_principal_cents"] = committed
    if changed and bump:
        db.touch(prop)
    return prop


# --------------------------------------------------------------------------
# Contractor ledger and workmanship scores (PRD 2.8, 3.7)
# --------------------------------------------------------------------------
def recompute_contractor_cash(contractor):
    draws = disbursements_of_contractor(contractor["id"])
    gross = sum(
        int(row["amount_cents"]) for row in draws if row["status"] in ("RELEASED", "REVERSED")
    )
    clawed = sum(int(row["amount_cents"]) for row in draws if row["status"] == "REVERSED")
    changed = (
        contractor.get("gross_disbursed_cents") != gross
        or contractor.get("clawed_back_total_cents") != clawed
    )
    contractor["gross_disbursed_cents"] = gross
    contractor["clawed_back_total_cents"] = clawed
    contractor["net_disbursed_cents"] = gross - clawed
    if changed:
        db.touch(contractor)
    return contractor


def fresh_scores(contractor):
    """Both score variants and the open-remedy count, computed but not stored."""
    complaints = complaints_of_contractor(contractor["id"])
    upheld = [
        row for row in complaints if row["status"] in calc.UPHELD_COMPLAINT_STATUSES
    ]
    horizon = db.now()
    trailing = []
    for row in upheld:
        created = db.parse_instant(row["created_at"])
        if created is not None and (horizon - created).days <= calc.TRAILING_WINDOW_DAYS:
            trailing.append(row["severity"])
    return {
        "workmanship_score": calc.workmanship_score(trailing),
        "lifetime_workmanship_score": calc.workmanship_score(
            [row["severity"] for row in upheld]
        ),
        "upheld_open_remedy_count": len(
            [row for row in complaints if row["status"] == "REMEDY_ORDERED"]
        ),
    }


def recompute_workmanship_scores(contractor):
    scores = fresh_scores(contractor)
    contractor["workmanship_score"] = scores["workmanship_score"]
    contractor["lifetime_workmanship_score"] = scores["lifetime_workmanship_score"]
    contractor["upheld_open_remedy_count"] = scores["upheld_open_remedy_count"]
    return contractor


def apply_workmanship_enrollment_cascade(contractor):
    """Links two, three and four of the uphold cascade (PRD 3.7)."""
    trailing = int(contractor["workmanship_score"])
    if contractor["enrollment_status"] == "TERMINATED":
        return
    if trailing < 7000:
        landing = "SUSPENDED"
        reason = "WORKMANSHIP_SCORE_BELOW_7000"
    elif trailing < 9000:
        landing = "PROBATION"
        reason = "WORKMANSHIP_SCORE_BELOW_9000"
    else:
        return
    contractor["enrollment_status"] = landing
    contractor["suspension_reason"] = reason
    hold_reason = (
        "CONTRACTOR_SUSPENSION" if landing == "SUSPENDED" else "CONTRACTOR_PROBATION"
    )
    held_application_ids = set()
    for draw in disbursements_of_contractor(contractor["id"]):
        if draw["status"] == "REQUESTED":
            draw["status"] = "HELD"
            draw["hold_reason"] = hold_reason
            db.touch(draw)
            held_application_ids.add(draw["application_id"])
        elif draw["status"] == "HELD" and hold_reason == "CONTRACTOR_SUSPENSION":
            if draw["hold_reason"] != hold_reason:
                draw["hold_reason"] = hold_reason
                db.touch(draw)
    for application in applications_of_contractor(contractor["id"]):
        if (
            application["status"] == "FUNDING_PENDING"
            and application["id"] in held_application_ids
        ):
            application["status"] = "FUNDING_HELD"
            application["funding_hold_reason"] = hold_reason
            db.touch(application)


def apply_reinstatement_cascade(contractor):
    for draw in disbursements_of_contractor(contractor["id"]):
        if draw["status"] == "HELD":
            draw["status"] = "REQUESTED"
            draw["hold_reason"] = None
            db.touch(draw)
    for application in applications_of_contractor(contractor["id"]):
        if application["status"] == "FUNDING_HELD":
            application["status"] = "FUNDING_PENDING"
            application["funding_hold_reason"] = None
            db.touch(application)


# --------------------------------------------------------------------------
# Lender consent posture (PRD 3.4)
# --------------------------------------------------------------------------
def derive_consent_posture(application):
    if not application.get("_consent_started"):
        return "NOT_STARTED"
    liens = [
        row
        for row in active_liens_of(application["property_id"])
        if row.get("consent_application_id") == application["id"]
    ]
    if any(row["consent_response"] == "DECLINED" for row in liens):
        return "VETOED"
    if any(row["consent_response"] in ("NOT_NOTIFIED", "PENDING") for row in liens):
        return "PENDING"
    return "CLEARED"


def notify_liens(application):
    """Side effect of a successful PROCEED (PRD 3.4)."""
    instant = db.now()
    deadline = instant + timedelta(days=calc.CONSENT_WINDOW_DAYS)
    notified = 0
    for lien in active_liens_of(application["property_id"]):
        lien["consent_application_id"] = application["id"]
        lien["notified_at"] = db.iso(instant)
        lien["consent_deadline_at"] = db.iso(deadline)
        lien["consent_response"] = "PENDING"
        lien["consent_responded_at"] = None
        db.touch(lien)
        notified += 1
    application["_consent_started"] = True
    application["notified_lien_count"] = notified
    application["consent_deadline_at"] = db.iso(deadline) if notified else None
    application["consent_posture"] = derive_consent_posture(application)
    return notified


def deemed_consent_sweep(application, prop):
    """Runs only inside compliance approval, only in deemed-consent counties."""
    if prop["county_code"] not in DEEMED_CONSENT_COUNTIES:
        return
    instant = db.now()
    for lien in active_liens_of(prop["id"]):
        if lien.get("consent_application_id") != application["id"]:
            continue
        if lien["consent_response"] != "PENDING":
            continue
        deadline = db.parse_instant(lien.get("consent_deadline_at"))
        if deadline is not None and instant >= deadline:
            lien["consent_response"] = "DEEMED_CONSENTED"
            lien["consent_responded_at"] = db.iso(instant)
            db.touch(lien)


# --------------------------------------------------------------------------
# Application pricing (submit / cure)
# --------------------------------------------------------------------------
def compute_pricing(application):
    """Every submit-time calculation over the current PROPOSED measure set.

    Returns a plan; nothing is persisted until apply_pricing is called.
    """
    measures = [
        row for row in measures_of(application["id"]) if row["status"] == "PROPOSED"
    ]
    plan = {
        "measures": [],
        "weighted_useful_life_years": None,
        "min_measure_sir_bps": None,
        "portfolio_sir_bps": None,
        "requested_principal_cents": 0,
        "screening_cltv_bps": None,
    }
    if not measures:
        return plan
    pairs = []
    total_pv = 0
    total_cost = 0
    sirs = []
    for measure in measures:
        product = db.get("products", measure["product_id"])
        useful_life = int(product["useful_life_years"])
        pv = calc.pv_savings_cents(measure["estimated_annual_savings_cents"], useful_life)
        ratio = calc.sir_bps(pv, measure["installed_cost_cents"])
        plan["measures"].append((measure, pv, ratio))
        pairs.append((measure["installed_cost_cents"], useful_life))
        total_pv += pv
        total_cost += int(measure["installed_cost_cents"])
        sirs.append(ratio)
    plan["weighted_useful_life_years"] = calc.weighted_useful_life_years(pairs)
    plan["min_measure_sir_bps"] = min(sirs)
    plan["portfolio_sir_bps"] = calc.portfolio_sir_bps(total_pv, total_cost)
    plan["requested_principal_cents"] = total_cost
    prop = db.get("properties", application["property_id"])
    plan["screening_cltv_bps"] = calc.cltv_bps(
        prop["senior_lien_balance_cents"],
        prop["committed_pace_principal_cents"],
        total_cost,
        prop["assessed_value_cents"],
    )
    return plan


def apply_pricing(application, plan):
    for measure, pv, ratio in plan["measures"]:
        if measure["pv_savings_cents"] != pv or measure["sir_bps"] != ratio:
            measure["pv_savings_cents"] = pv
            measure["sir_bps"] = ratio
            db.touch(measure)
    application["weighted_useful_life_years"] = plan["weighted_useful_life_years"]
    application["min_measure_sir_bps"] = plan["min_measure_sir_bps"]
    application["portfolio_sir_bps"] = plan["portfolio_sir_bps"]
    application["requested_principal_cents"] = plan["requested_principal_cents"]
    application["screening_cltv_bps"] = plan["screening_cltv_bps"]


def valuation_basis_value(prop, basis):
    """Returns (basis_actually_used, basis_value_cents)."""
    if basis == "MARKET" and not appraisal_stale(prop):
        return "MARKET", int(prop["market_value_cents"])
    return "ASSESSED", int(prop["assessed_value_cents"])


def appraisal_stale(prop):
    if prop.get("market_value_cents") is None:
        return True
    effective = prop.get("appraisal_effective_on")
    if not effective:
        return True
    age = (db.today() - calc.date_from_iso(effective)).days
    return age > calc.APPRAISAL_FRESH_DAYS
