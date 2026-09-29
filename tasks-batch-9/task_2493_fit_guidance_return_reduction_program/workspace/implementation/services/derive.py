"""Derived aggregates and the cascades that hang off them (PRD 2.8, 2.11, 3.8).

Every counter, score, rate and classification in the program is *recomputed from
its inputs* rather than incrementally adjusted, which is what lets a reversal
walk the derived state back down.
"""

from datetime import timedelta

import clock
import constants as C
from db import db, mutating, ordered, touch
from numeric import bp_rate, floor_div


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def lines_of_item(item_id):
    return [ol for ol in db.order_lines.values() if ol["item_id"] == item_id]


def lines_of_customer(customer_id):
    return [ol for ol in db.order_lines.values()
            if ol["customer_profile_id"] == customer_id]


def cases_of_lines(lines):
    line_ids = {ol["id"] for ol in lines}
    return [rc for rc in db.return_cases.values() if rc["order_line_id"] in line_ids]


def cases_of_item(item_id):
    return cases_of_lines(lines_of_item(item_id))


def cases_of_customer(customer_id):
    return cases_of_lines(lines_of_customer(customer_id))


def postings_of_case(case_id):
    return ordered([p for p in db.postings.values() if p["return_case_id"] == case_id])


def specs_of_item(item_id):
    return ordered([s for s in db.specs.values() if s["item_id"] == item_id])


def verified_specs_of_item(item_id):
    return [s for s in specs_of_item(item_id) if s["status"] == "VERIFIED"]


def active_mapping_of_item(item_id):
    rows = ordered([m for m in db.mappings.values()
                    if m["item_id"] == item_id and m["status"] == "ACTIVE"])
    return rows[-1] if rows else None


def feedback_of_item(item_id):
    return ordered([f for f in db.feedback.values() if f["item_id"] == item_id])


def deployments_of_item(item_id):
    return ordered([d for d in db.deployments.values() if d["item_id"] == item_id])


def deployments_of_intervention(intervention_id):
    return ordered([d for d in db.deployments.values()
                    if d["intervention_id"] == intervention_id])


# ---------------------------------------------------------------------------
# Vendor: reliability score and standing (PRD 2.11)
# ---------------------------------------------------------------------------
def apply_vendor_derivation(vendor):
    vendor_items = {i["id"] for i in db.items.values()
                    if i["vendor_id"] == vendor["id"]}
    chargebacks = 0
    for case in db.return_cases.values():
        line = db.order_lines.get(case["order_line_id"])
        if line is None or line["item_id"] not in vendor_items:
            continue
        if case["reason_family"] == "QUALITY" and case["status"] == "RESOLVED_REFUNDED":
            chargebacks += 1
    vendor["quality_chargeback_count"] = chargebacks
    score = (10000
             - C.QUALITY_CHARGEBACK_PENALTY_BP * vendor["quality_chargeback_count"]
             - C.CORRECTION_ROUND_PENALTY_BP * vendor["correction_round_count"])
    vendor["reliability_score_bp"] = max(0, score)
    if vendor["reliability_score_bp"] < C.VENDOR_SUSPEND_BP:
        vendor["status"] = "SUSPENDED"
    elif (vendor["reliability_score_bp"] < C.VENDOR_PROBATION_BP
          or vendor["correction_spend_cents"] > vendor["correction_budget_cents"]):
        vendor["status"] = "PROBATION"
    else:
        vendor["status"] = "ACTIVE"


def recompute_vendor(vendor):
    with mutating(vendor):
        apply_vendor_derivation(vendor)


def debit_vendor_correction_round(vendor_id):
    """A correction round was opened: charge the funded allowance (PRD 2.11)."""
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        return
    with mutating(vendor):
        vendor["correction_round_count"] += 1
        vendor["correction_spend_cents"] += C.CORRECTION_COST_CENTS
        apply_vendor_derivation(vendor)


# ---------------------------------------------------------------------------
# CatalogItem: chronic return score (calculations.item_chronic_return_score)
# ---------------------------------------------------------------------------
def apply_item_derivation(item):
    item_id = item["id"]
    lines = lines_of_item(item_id)
    units = sum(ol["quantity"] for ol in lines
                if ol["status"] in C.PURCHASED_LINE_STATUSES)
    cases = cases_of_lines(lines)
    closed = [rc for rc in cases if rc["status"] in C.RESOLVED_CASE_STATUSES]

    fit_count = len([rc for rc in closed if rc["reason_family"] == "FIT"])
    expectation_count = len([rc for rc in closed
                             if rc["reason_family"] == "EXPECTATION"])

    item["units_sold_count"] = units
    item["fit_return_count"] = fit_count
    item["expectation_return_count"] = expectation_count
    item["total_return_count"] = len(closed)
    item["fit_return_rate_bp"] = bp_rate(fit_count, units)
    item["expectation_return_rate_bp"] = bp_rate(expectation_count, units)
    item["chronic_return_score_bp"] = floor_div(
        C.FIT_WEIGHT_BP * item["fit_return_rate_bp"]
        + C.EXPECTATION_WEIGHT_BP * item["expectation_return_rate_bp"],
        10000,
    )

    case_ids = {rc["id"] for rc in cases}
    item["return_cost_accrued_cents"] = sum(
        p["amount_cents"] for p in db.postings.values()
        if p["return_case_id"] in case_ids
    )

    active_feedback = [f for f in feedback_of_item(item_id) if f["status"] == "ACTIVE"]
    item["fit_signal_weight_total"] = sum(f["signal_weight"] for f in active_feedback)
    item["active_fit_feedback_count"] = len(active_feedback)

    score = item["chronic_return_score_bp"]
    if score >= C.CHRONIC_THRESHOLD_BP and fit_count >= C.MIN_FIT_RETURNS_CHRONIC:
        item["fit_watch_state"] = "CHRONIC"
    elif score >= C.WATCH_THRESHOLD_BP and fit_count >= C.MIN_FIT_RETURNS_WATCH:
        item["fit_watch_state"] = "WATCH"
    else:
        item["fit_watch_state"] = "NORMAL"


def recompute_item(item, stats=None, set_pdp_review=False):
    """Recompute the item's derived block and run the chronic cascade on a flip."""
    previous = item["fit_watch_state"]
    with mutating(item):
        if set_pdp_review:
            item["pdp_review_required"] = True
        apply_item_derivation(item)
    current = item["fit_watch_state"]
    if current != previous and stats is not None:
        if current == "WATCH":
            stats["watch_flips"] = stats.get("watch_flips", 0) + 1
        elif current == "CHRONIC":
            stats["chronic_flips"] = stats.get("chronic_flips", 0) + 1
    if current == "CHRONIC" and previous != "CHRONIC":
        chronic_cascade(item, stats)
    return previous, current


# ---------------------------------------------------------------------------
# The chronic cascade (PRD 3.8 / 2.8)
# ---------------------------------------------------------------------------
def chronic_cascade(item, stats=None):
    # a) storefront axis: a LISTED item is suspended
    if item["listing_status"] == "LISTED":
        item["listing_status"] = "SUSPENDED"
        touch(item)

    # b) readiness axis falls back to UNVERIFIED
    previous_readiness = item["fit_readiness"]
    if previous_readiness in ("CHART_MAPPED", "GUIDANCE_READY"):
        item["fit_readiness"] = "UNVERIFIED"
        touch(item)

    # c) the item's single VERIFIED specification is reopened, debiting the vendor
    verified = verified_specs_of_item(item["id"])
    if len(verified) == 1:
        spec = verified[0]
        with mutating(spec):
            spec["status"] = "CORRECTION_REQUESTED"
            spec["correction_reason"] = "CHRONIC_FIT_RETURNS"
        debit_vendor_correction_round(item["vendor_id"])
        if stats is not None:
            stats["corrections_opened"] = stats.get("corrections_opened", 0) + 1

    # d) because the readiness axis fell away from GUIDANCE_READY, the item's
    #    running badge / chart deployments are terminated
    if previous_readiness == "GUIDANCE_READY":
        terminate_readiness_deployments(item)


def terminate_readiness_deployments(item):
    for deployment in deployments_of_item(item["id"]):
        if deployment["status"] != "ACTIVE":
            continue
        intervention = db.interventions.get(deployment["intervention_id"])
        if intervention is None:
            continue
        if intervention["lever"] not in C.READINESS_SENSITIVE_LEVERS:
            continue
        terminate_deployment(deployment, "MAPPING_SUPERSEDED")


def readiness_fall_to_unverified(item):
    """Drop the readiness axis to UNVERIFIED, bumping the item's version."""
    if item["fit_readiness"] in ("CHART_MAPPED", "GUIDANCE_READY"):
        item["fit_readiness"] = "UNVERIFIED"
        touch(item)
        return True
    return False


# ---------------------------------------------------------------------------
# InterventionDeployment termination / Intervention roll-up
# ---------------------------------------------------------------------------
def terminate_deployment(deployment, reason_code):
    now = clock.now()
    with mutating(deployment):
        deployment["status"] = "TERMINATED"
        deployment["terminated_reason_code"] = reason_code
        if now < deployment["window_end"]:
            deployment["window_end"] = now
    deployment["_hop_run"] = db.ops_run_seq
    intervention = db.interventions.get(deployment["intervention_id"])
    if intervention is not None:
        recompute_intervention(intervention)


def funding_posture(net_savings_cents):
    if net_savings_cents >= 0:
        return "FUNDED"
    if net_savings_cents >= -C.FUNDING_TOLERANCE_CENTS:
        return "UNDER_REVIEW"
    return "DEFUNDED"


def apply_intervention_derivation(intervention):
    deployments = deployments_of_intervention(intervention["id"])
    measured = [d for d in deployments if d["status"] == "MEASURED"]
    intervention["deployment_count"] = len(deployments)
    intervention["measured_deployment_count"] = len(measured)
    intervention["gross_savings_cents"] = sum(
        d["attributed_savings_cents"] or 0 for d in measured)
    intervention["spend_cents"] = sum(
        d["spend_cents"] for d in deployments
        if d["status"] in ("TERMINATED", "MEASURED"))
    intervention["net_savings_cents"] = (intervention["gross_savings_cents"]
                                        - intervention["spend_cents"])
    intervention["funding_posture"] = funding_posture(
        intervention["net_savings_cents"])


def recompute_intervention(intervention):
    with mutating(intervention):
        apply_intervention_derivation(intervention)


# ---------------------------------------------------------------------------
# CustomerProfile: abuse standing and policy class
# (calculations.customer_abuse_and_policy_class)
# ---------------------------------------------------------------------------
def apply_customer_derivation(customer):
    customer_id = customer["id"]
    lines = lines_of_customer(customer_id)
    purchase_line_count = len([ol for ol in lines
                               if ol["status"] in C.PURCHASED_LINE_STATUSES])
    cases = cases_of_lines(lines)

    return_case_count = len([rc for rc in cases
                             if rc["status"] in C.LIVE_OR_CLOSED_CASE_STATUSES])
    change_of_mind_count = len([rc for rc in cases
                                if rc["reason_family"] == "CHANGE_OF_MIND"
                                and rc["status"] == "RESOLVED_REFUNDED"])

    customer["purchase_line_count"] = purchase_line_count
    customer["return_case_count"] = return_case_count
    customer["change_of_mind_count"] = change_of_mind_count
    customer["return_rate_bp"] = bp_rate(return_case_count, purchase_line_count)

    cutoff = clock.now() - timedelta(days=C.ABUSE_WINDOW_DAYS)
    strikes = 0
    for case in cases:
        if case["status"] != "RESOLVED_REFUNDED":
            continue
        if case["reason_family"] != "CHANGE_OF_MIND":
            continue
        if case["refund_amount_cents"] <= 0:
            continue
        if case["requested_at"] is not None and case["requested_at"] > cutoff:
            strikes += 1
    customer["abuse_strike_count"] = strikes

    rate_block = (customer["return_rate_bp"] >= C.ABUSE_RATE_BLOCK_BP
                  and purchase_line_count >= C.ABUSE_RATE_MIN_LINES)
    if strikes >= C.ABUSE_BLOCKED_STRIKES or rate_block:
        customer["abuse_status"] = "BLOCKED"
    elif strikes >= C.ABUSE_RESTRICTED_STRIKES:
        customer["abuse_status"] = "RESTRICTED"
    elif strikes >= C.ABUSE_WATCH_STRIKES:
        customer["abuse_status"] = "WATCH"
    else:
        customer["abuse_status"] = "CLEAR"

    customer["policy_class"] = derive_policy_class(customer)

    customer["refunded_total_cents"] = sum(
        rc["refund_amount_cents"] for rc in cases
        if rc["status"] == "RESOLVED_REFUNDED")


def derive_policy_class(customer):
    if customer["abuse_status"] in ("RESTRICTED", "BLOCKED"):
        return "RESTRICTED_WINDOW"
    if customer["tier"] == "PLUS" and customer["abuse_status"] == "CLEAR":
        return "EXTENDED_WINDOW"
    return "STANDARD_WINDOW"


def recompute_customer(customer, stats=None):
    previous = customer["abuse_status"]
    with mutating(customer):
        apply_customer_derivation(customer)
    current = customer["abuse_status"]
    if (stats is not None
            and C.ABUSE_STATUS_RANK[current] < C.ABUSE_STATUS_RANK[previous]):
        stats["abuse_downgrades"] = stats.get("abuse_downgrades", 0) + 1
    return previous, current


def effective_window_days(base_window_days, policy_class):
    return max(C.MIN_EFFECTIVE_WINDOW_DAYS,
               base_window_days + C.POLICY_CLASS_DELTA_DAYS[policy_class])
