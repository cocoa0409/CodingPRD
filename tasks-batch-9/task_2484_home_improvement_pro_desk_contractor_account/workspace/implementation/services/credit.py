"""Credit exposure, authorization, freezes and account holds (PRD 3.3)."""
from decimal import Decimal

import db
from services.money import round_half_up

FREEZE_UTILIZATION_PCT = Decimal("0.90")


def credit_line_of(account_id):
    lines = db.where("credit_lines", pro_account_id=account_id)
    return lines[0] if lines else None


def freeze_threshold_cents(credit_line):
    return round_half_up(Decimal(credit_line["limit_cents"]) * FREEZE_UTILIZATION_PCT)


def recompute_exposure(credit_line):
    """Exposure is recomputed from the account's AUTHORIZED/INVOICED orders."""
    if credit_line is None:
        return None
    exposure = 0
    for order in db.where("pro_orders", pro_account_id=credit_line["pro_account_id"]):
        if order["credit_status"] not in ("AUTHORIZED", "INVOICED"):
            continue
        exposure += (order.get("total_cents") or 0)
        exposure -= (order.get("credited_refund_cents") or 0)
    credit_line["exposure_cents"] = exposure
    credit_line["available_cents"] = credit_line["limit_cents"] - exposure
    db.touch(credit_line)
    return credit_line


def freeze(credit_line, reason_code):
    """ACTIVE -> FROZEN, cascading the owning account ACTIVE -> HOLD."""
    credit_line["status"] = "FROZEN"
    credit_line["frozen_reason_code"] = reason_code
    db.touch(credit_line)
    account = db.get("pro_accounts", credit_line["pro_account_id"])
    if account is not None and account["status"] == "ACTIVE":
        account["status"] = "HOLD"
        db.touch(account)
    return credit_line


def utilization_review(credit_line):
    """Pinned to the AUTHORIZED -> INVOICED transition only."""
    if credit_line is None or credit_line["status"] != "ACTIVE":
        return False
    if credit_line["exposure_cents"] >= freeze_threshold_cents(credit_line):
        freeze(credit_line, "UTILIZATION_REVIEW")
        return True
    return False
