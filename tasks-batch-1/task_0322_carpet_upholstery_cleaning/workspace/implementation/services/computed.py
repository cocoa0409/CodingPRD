"""Recomputation of derived/computed fields (PRD §2.8, §2.10, scaffold §1.3).

A change to a computed field is still a mutation of its owning resource, so the
owner is touch()-ed (version bump + updated_at) whenever a derived field moves.
"""
from __future__ import annotations

from typing import Dict

import db
from services.common import touch


def rooms_of_job(job_id: str):
    return [r for r in db.room_assessments.values() if r["cleaning_job_id"] == job_id]


def addons_of_job(job_id: str):
    return [a for a in db.add_ons.values() if a["cleaning_job_id"] == job_id]


def ledger_of_customer(customer_id: str):
    return [e for e in db.wallet_ledger_entries.values() if e["customer_id"] == customer_id]


def recompute_total_sqft(job: Dict) -> None:
    """job.total_sqft = sum(room.area_sqft). A change is a mutation of the
    owning job (PRD §2.8), so the job's version/updated_at are bumped. Since
    area_sqft >= 1, adding a room always changes the sum."""
    total = sum(r["area_sqft"] for r in rooms_of_job(job["id"]))
    if job.get("total_sqft") != total:
        job["total_sqft"] = total
        touch(job)


def recompute_wallet_credit(customer: Dict) -> None:
    """wallet_credit_cents = sum(delta_cents) over the customer's ledger.

    Append-only, no status filter (PRD §2.10). Never below 0 by construction.
    Touches the customer (computed-field change is a mutation).
    """
    total = sum(e["delta_cents"] for e in ledger_of_customer(customer["id"]))
    if customer.get("wallet_credit_cents") != total:
        customer["wallet_credit_cents"] = total
        touch(customer)


def recompute_amount_paid(invoice: Dict) -> None:
    """invoice.amount_paid_cents = sum of APPLIED Payment.amount_cents."""
    total = sum(
        p["amount_cents"]
        for p in db.payments.values()
        if p["invoice_id"] == invoice["id"] and p["status"] == "APPLIED"
    )
    invoice["amount_paid_cents"] = total
