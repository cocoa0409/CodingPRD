"""Shared statutory / state gates and the post-allocation cascades."""

from core import clock, fail, touch
from model import (installments_of_agreement, late_fees_of_agreement,
                   notices_of_agreement, state_is_licensed)

MAX_FIRST_DUE_WINDOW_DAYS = 60
PREMIUM_VARIANCE_TOLERANCE_BPS = 2500


def require_status(agreement, allowed):
    if agreement["status"] not in allowed:
        fail("ERR_AGREEMENT_STATE_INVALID",
             "agreement status %s does not permit this operation"
             % agreement["status"])


def require_stage(agreement, allowed):
    if agreement["delinquency_stage"] not in allowed:
        fail("ERR_DELINQUENCY_STATE_INVALID",
             "delinquency stage %s does not permit this operation"
             % agreement["delinquency_stage"])


def require_policy_status(policy, allowed):
    if policy["status"] not in allowed:
        fail("ERR_POLICY_STATE_INVALID",
             "policy status %s does not permit this operation" % policy["status"])


def require_licensed(rule):
    if not state_is_licensed(rule):
        fail("ERR_STATE_NOT_LICENSED",
             "no effective premium finance license exists for state %s"
             % rule["state_code"])


def require_agent_active(agent):
    if agent["status"] != "ACTIVE":
        fail("ERR_AGENT_SUSPENDED",
             "producing agency %s is %s" % (agent["id"], agent["status"]))


def require_term_within_maximum(count, rule):
    if count > rule["max_term_months"]:
        fail("ERR_TERM_EXCEEDS_STATE_MAXIMUM",
             "installment_count %s exceeds max_term_months %s"
             % (count, rule["max_term_months"]))


def require_first_due_window(due_date):
    today = clock.date()
    if due_date <= today:
        fail("ERR_INVALID_FIRST_DUE_DATE",
             "first_installment_due_date must be strictly after the clock date")
    if (due_date - today).days > MAX_FIRST_DUE_WINDOW_DAYS:
        fail("ERR_INVALID_FIRST_DUE_DATE",
             "first_installment_due_date must be within %s days of the clock date"
             % MAX_FIRST_DUE_WINDOW_DAYS)


def require_down_payment(down_payment_cents, basis_cents, rule):
    if down_payment_cents * 10000 < basis_cents * rule["min_down_payment_bps"]:
        fail("ERR_DOWN_PAYMENT_BELOW_MINIMUM",
             "down payment is below the statutory minimum of %s basis points"
             % rule["min_down_payment_bps"])


def service_fee_ceiling(agreement, rule):
    if (agreement["rate_exception_approved"]
            and agreement["approved_service_fee_cap_cents"] is not None):
        return agreement["approved_service_fee_cap_cents"]
    return rule["max_service_fee_cents"]


def require_service_fee_within_cap(agreement, rule):
    ceiling = service_fee_ceiling(agreement, rule)
    if agreement["service_fee_cents"] > ceiling:
        fail("ERR_SERVICE_FEE_ABOVE_CAP",
             "service_fee_cents %s exceeds the ceiling of %s"
             % (agreement["service_fee_cents"], ceiling))


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def has_past_due(agreement_id):
    return any(r["status"] == "PAST_DUE"
               for r in installments_of_agreement(agreement_id))


def has_outstanding_fee(agreement_id):
    return any(r["status"] == "OUTSTANDING"
               for r in late_fees_of_agreement(agreement_id))


def cure_delinquency(agreement):
    """Cure the collection dimension when no past-due obligation remains."""
    if has_past_due(agreement["id"]) or agreement["late_fee_balance_cents"] != 0:
        return False
    changed = False
    if agreement["delinquency_stage"] in ("LATE", "NOIC_ISSUED"):
        agreement["delinquency_stage"] = "CURRENT"
        changed = True
    for notice in notices_of_agreement(agreement["id"]):
        if notice["status"] == "ISSUED":
            notice["status"] = "CURED"
            notice["cured_date"] = clock.date().isoformat()
            touch(notice)
            changed = True
    return changed


def complete_if_paid_in_full(agreement, payment=None):
    if (agreement["principal_balance_cents"] != 0
            or agreement["unpaid_finance_charge_cents"] != 0
            or agreement["late_fee_balance_cents"] != 0):
        return False
    agreement["status"] = "PAID_IN_FULL"
    for row in installments_of_agreement(agreement["id"]):
        if row["status"] in ("SCHEDULED", "PAST_DUE"):
            delta = row["amount_cents"] - row["paid_cents"]
            if payment is not None and delta:
                contribs = payment.setdefault("_installment_contribs", {})
                contribs[row["id"]] = contribs.get(row["id"], 0) + delta
            row["paid_cents"] = row["amount_cents"]
            row["status"] = "PAID"
            touch(row)
    agreement["refund_due_cents"] = agreement["unapplied_credit_cents"]
    return True
