"""Existence lookups (PRD §2.5 left-to-right; priority 3 -> 404).

Each helper raises the entity-specific NOT_FOUND error so the route layer can
validate path/body ids in order.
"""
from __future__ import annotations

from typing import Dict

import db
from errors import (
    APIError,
    ERR_ADDON_NOT_FOUND,
    ERR_CATALOG_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_CREW_NOT_FOUND,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_INVOICE_NOT_FOUND,
    ERR_JOB_NOT_FOUND,
    ERR_PLAN_NOT_FOUND,
    ERR_ROOM_NOT_FOUND,
)


def get_customer(cid: str) -> Dict:
    c = db.customers.get(cid)
    if c is None:
        raise APIError(ERR_CUSTOMER_NOT_FOUND, 404, "Customer not found")
    return c


def get_catalog(cid: str) -> Dict:
    c = db.service_catalogs.get(cid)
    if c is None:
        raise APIError(ERR_CATALOG_NOT_FOUND, 404, "ServiceCatalog not found")
    return c


def get_crew(cid: str) -> Dict:
    c = db.crews.get(cid)
    if c is None:
        raise APIError(ERR_CREW_NOT_FOUND, 404, "Crew not found")
    return c


def get_plan(pid: str) -> Dict:
    p = db.recurring_plans.get(pid)
    if p is None:
        raise APIError(ERR_PLAN_NOT_FOUND, 404, "RecurringPlan not found")
    return p


def get_job(jid: str) -> Dict:
    j = db.cleaning_jobs.get(jid)
    if j is None:
        raise APIError(ERR_JOB_NOT_FOUND, 404, "CleaningJob not found")
    return j


def get_room(rid: str) -> Dict:
    r = db.room_assessments.get(rid)
    if r is None:
        raise APIError(ERR_ROOM_NOT_FOUND, 404, "RoomAssessment not found")
    return r


def get_addon(aid: str) -> Dict:
    a = db.add_ons.get(aid)
    if a is None:
        raise APIError(ERR_ADDON_NOT_FOUND, 404, "AddOn not found")
    return a


def get_invoice(iid: str) -> Dict:
    i = db.invoices.get(iid)
    if i is None:
        raise APIError(ERR_INVOICE_NOT_FOUND, 404, "Invoice not found")
    return i


def get_claim(cid: str) -> Dict:
    c = db.guarantee_claims.get(cid)
    if c is None:
        raise APIError(ERR_CLAIM_NOT_FOUND, 404, "GuaranteeClaim not found")
    return c
