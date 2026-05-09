"""Path-parameter lookups with strict left-to-right validation (PRD §2.6)."""

from __future__ import annotations

from db import db
from errors import err


def get_platform(pid: str) -> dict:
    p = db.platforms.get(pid)
    if not p:
        raise err("ERR_PLATFORM_NOT_FOUND", f"Platform '{pid}' not found.")
    return p


def get_drug(pid: str, drug_id: str) -> tuple[dict, dict]:
    platform = get_platform(pid)
    d = db.drugs.get(drug_id)
    if not d or d.get("platform_id") != pid:
        raise err("ERR_DRUG_NOT_FOUND", f"Drug '{drug_id}' not found.")
    return platform, d


def get_vendor(pid: str, vendor_id: str) -> tuple[dict, dict]:
    platform = get_platform(pid)
    v = db.vendors.get(vendor_id)
    if not v or v.get("platform_id") != pid:
        raise err("ERR_VENDOR_NOT_FOUND", f"Vendor '{vendor_id}' not found.")
    return platform, v


def get_pharmacist(pid: str, pharmacist_id: str) -> tuple[dict, dict]:
    platform = get_platform(pid)
    p = db.pharmacists.get(pharmacist_id)
    if not p or p.get("platform_id") != pid:
        raise err("ERR_PHARMACIST_NOT_FOUND", f"Pharmacist '{pharmacist_id}' not found.")
    return platform, p


def get_customer(pid: str, customer_id: str) -> tuple[dict, dict]:
    platform = get_platform(pid)
    c = db.customers.get(customer_id)
    if not c or c.get("platform_id") != pid:
        raise err("ERR_CUSTOMER_NOT_FOUND", f"Customer '{customer_id}' not found.")
    return platform, c


def get_prescription(pid: str, rx_id: str) -> tuple[dict, dict]:
    platform = get_platform(pid)
    rx = db.prescriptions.get(rx_id)
    if not rx or rx.get("platform_id") != pid:
        raise err("ERR_PRESCRIPTION_NOT_FOUND", f"Prescription '{rx_id}' not found.")
    return platform, rx


def get_order(pid: str, order_id: str) -> tuple[dict, dict]:
    platform = get_platform(pid)
    o = db.orders.get(order_id)
    if not o or o.get("platform_id") != pid:
        raise err("ERR_ORDER_NOT_FOUND", f"Order '{order_id}' not found.")
    return platform, o


def get_review(pid: str, order_id: str, review_id: str) -> tuple[dict, dict, dict]:
    platform, order = get_order(pid, order_id)
    review = db.pharmacist_reviews.get(review_id)
    if not review or review.get("platform_id") != pid or review.get("order_id") != order_id:
        raise err("ERR_REVIEW_NOT_FOUND", f"Review '{review_id}' not found.")
    return platform, order, review


def get_shipment(pid: str, shipment_id: str) -> tuple[dict, dict]:
    platform = get_platform(pid)
    s = db.cold_chain_shipments.get(shipment_id)
    if not s or s.get("platform_id") != pid:
        raise err("ERR_SHIPMENT_NOT_FOUND", f"Shipment '{shipment_id}' not found.")
    return platform, s


def get_report(pid: str, report_id: str) -> tuple[dict, dict]:
    platform = get_platform(pid)
    r = db.adverse_reaction_reports.get(report_id)
    if not r or r.get("platform_id") != pid:
        raise err("ERR_REPORT_NOT_FOUND", f"Report '{report_id}' not found.")
    return platform, r


def get_rule(pid: str, rule_id: str) -> tuple[dict, dict]:
    platform = get_platform(pid)
    r = db.purchase_limit_rules.get(rule_id)
    if not r or r.get("platform_id") != pid:
        raise err("ERR_RULE_NOT_FOUND", f"Rule '{rule_id}' not found.")
    return platform, r
