"""Entity serializers — public views strip internal fields; the shop read
computes period_close_audit_score on read."""

from db import public
from services.scoring import period_close_score


def policyholder_view(ph):
    return public(ph)


def regulation_view(reg):
    return public(reg)


def policy_view(policy):
    return public(policy)


def shop_view(shop):
    data = public(shop)
    data["period_close_audit_score"] = period_close_score(shop)
    return data


def part_view(part):
    return public(part)


def claim_view(claim):
    return public(claim)


def disclosure_view(record):
    return public(record)


def work_order_view(wo):
    return public(wo)


def calibration_view(ev):
    return public(ev)


def invoice_view(invoice):
    return public(invoice)


def line_item_view(line):
    return public(line)


def fraud_alert_view(alert):
    return public(alert)


def warranty_claim_view(wc):
    return public(wc)
