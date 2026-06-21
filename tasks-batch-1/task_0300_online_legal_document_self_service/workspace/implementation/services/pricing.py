"""Calculation rules: provisional/final pricing, completeness, credit & money
conservation (SCAFFOLD §1.3, PRD §3.4/§3.5/§3.7)."""

import constants
from common import apply_discount_cents, touch
from db import store


# --------------------------------------------------------------------------
# Document portion (shared by provisional and final pricing).
# Each line is discounted and round_half_up'd BEFORE summation (pinned order).
# --------------------------------------------------------------------------
def document_portion_cents(project, plan):
    d = plan["subscription_discount_pct"]
    doc_type = project["document_type"]
    state = project["state_code"]

    l_base = constants.BASE_PRICE_CENTS[doc_type]
    l_state = constants.STATE_SURCHARGE_CENTS[state]
    extra_clauses = max(0, project["assembled_clause_count"] - plan["included_clause_count"])
    l_extra = extra_clauses * constants.EXTRA_CLAUSE_FEE_CENTS

    return (
        apply_discount_cents(l_base, d)
        + apply_discount_cents(l_state, d)
        + apply_discount_cents(l_extra, d)
    )


def review_surcharge_cents(plan):
    """review_pricing: REVIEW_SURCHARGE_CENTS net of plan.review_discount_pct."""
    return apply_discount_cents(constants.REVIEW_SURCHARGE_CENTS, plan["review_discount_pct"])


# --------------------------------------------------------------------------
# Completeness ratios.
# --------------------------------------------------------------------------
def compute_provisional_completeness(project, answers):
    total = constants.TOTAL_REQUIRED_QUESTIONS[project["document_type"]]
    answered = 0
    for v in answers.values():
        if _non_empty(v):
            answered += 1
    answered = min(answered, total)
    return answered, total, (answered / total)


def _non_empty(v):
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


def required_mandatory_count(document_type, state_code):
    """Live count of mandatory ClauseTemplates for (type,state)."""
    return sum(
        1 for t in store.clause_templates.values()
        if t["document_type"] == document_type
        and t["state_code"] == state_code
        and t["is_mandatory"] is True
    )


def assembled_mandatory_count(project_id):
    return sum(
        1 for c in store.assembled_clauses.values()
        if c["document_project_id"] == project_id and c["is_mandatory"] is True
    )


def compute_assembled_completeness(project):
    required = required_mandatory_count(project["document_type"], project["state_code"])
    if required == 0:
        return 1.0
    assembled = assembled_mandatory_count(project["id"])
    return assembled / required


# --------------------------------------------------------------------------
# Order recomputation helpers (money_conservation invariant maintained).
# --------------------------------------------------------------------------
def order_for_project(project_id):
    for o in store.orders.values():
        if o["document_project_id"] == project_id:
            return o
    return None


def recompute_net(order):
    order["net_collected_cents"] = order["amount_charged_cents"] - order["amount_refunded_cents"]


def set_provisional_quote(project, plan):
    order = order_for_project(project["id"])
    if order is None:
        return
    order["provisional_quote_cents"] = document_portion_cents(project, plan)
    touch(order)
