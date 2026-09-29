"""The surveillance sweep: the only materialiser of clock-driven change."""

import clock
import db
from constants import SURVEILLANCE_INTERVAL_DAYS
from services import calc, derive, nc as nc_service

FIELDS = (
    "certificates_marked_due",
    "certificates_marked_overdue",
    "certificates_suspended",
    "certificates_expired",
    "documents_expired",
    "ingredients_blocked",
    "facility_validations_expired",
    "audits_cancelled",
    "nonconformances_escalated",
)


def _ordered(table):
    return db.ordered(table)


def run():
    now = clock.now()
    counters = derive.Counters()
    touched_applicants = set()

    # 1. surveillance dimension of every live certificate
    for cert in _ordered(db.certificates):
        if cert["status"] not in ("ISSUED", "SUSPENDED"):
            continue
        before_state = cert["surveillance_status"]
        new_state = calc.surveillance_state(cert["surveillance_due_on"], now)
        if new_state != before_state:
            cert["surveillance_status"] = new_state
            db.touch(cert)
            if new_state == "DUE":
                counters.bump("certificates_marked_due")
            elif new_state == "OVERDUE":
                counters.bump("certificates_marked_overdue")
        if cert["surveillance_status"] == "OVERDUE" and cert["status"] == "ISSUED":
            derive.suspend_certificate(cert, "SURVEILLANCE_OVERDUE", counters)
            touched_applicants.add(cert["applicant_id"])

    # 2. term expiry
    for cert in _ordered(db.certificates):
        if cert["status"] not in ("ISSUED", "SUSPENDED"):
            continue
        if cert["expires_on"] is not None and cert["expires_on"] <= now:
            cert["status"] = "EXPIRED"
            db.touch(cert)
            counters.bump("certificates_expired")
            touched_applicants.add(cert["applicant_id"])

    # 3. supplier document expiry, then the ingredient/product/certificate chain
    expired_docs = []
    for doc in _ordered(db.supplier_documents):
        if doc["status"] == "VERIFIED" and doc["expires_on"] is not None \
                and doc["expires_on"] <= now:
            doc["status"] = "EXPIRED"
            db.touch(doc)
            counters.bump("documents_expired")
            expired_docs.append(doc)
    if expired_docs:
        suppliers = {doc["supplier_id"] for doc in expired_docs}
        for supplier_id in suppliers:
            supplier = db.suppliers.get(supplier_id)
            if supplier is not None:
                derive.recompute_supplier(supplier)
        candidate_ids = []
        for doc in expired_docs:
            if doc["ingredient_id"] and doc["ingredient_id"] not in candidate_ids:
                candidate_ids.append(doc["ingredient_id"])
        blocked = []
        for ingredient_id in candidate_ids:
            ingredient = db.ingredients.get(ingredient_id)
            if ingredient is None:
                continue
            derive.recompute_ingredient_docs(ingredient)
            if ingredient["status"] != "APPROVED":
                continue
            required = derive.required_doc_types(ingredient)
            if not set(required).issubset(set(ingredient["verified_doc_types"])):
                blocked.extend(
                    derive.block_ingredient_chain(
                        ingredient, "DOCUMENT_EXPIRED", counters
                    )
                )
        if blocked:
            derive.refresh_products_of_ingredients(
                [i["id"] for i in blocked], counters
            )

    # 4. sanitation validation expiry
    for facility in _ordered(db.facilities):
        if facility["sanitation_validation_status"] == "VALIDATED" \
                and facility["sanitation_expires_on"] is not None \
                and facility["sanitation_expires_on"] <= now:
            facility["sanitation_validation_status"] = "EXPIRED"
            db.touch(facility)
            counters.bump("facility_validations_expired")

    # 5. audits never started
    for audit in _ordered(db.audits):
        if audit["status"] == "SCHEDULED" and audit["onsite_end_at"] <= now:
            audit["status"] = "CANCELLED"
            db.touch(audit)
            counters.bump("audits_cancelled")
            facility = db.facilities.get(audit["facility_id"])
            if facility is not None:
                derive.recompute_facility_audit_outcome(facility)

    # 6. corrective actions never filed
    for nc in _ordered(db.nonconformances):
        if nc["status"] == "OPEN" and nc["ca_due_on"] is not None \
                and now > nc["ca_due_on"]:
            nc_service.escalate(nc, counters)
            counters.bump("nonconformances_escalated")
            touched_applicants.add(nc["applicant_id"])

    # 7. every applicant's posture is recomputed from the settled population
    for applicant in _ordered(db.applicants):
        derive.recompute_applicant(applicant)

    summary = {"run_at": clock.format_iso_instant(now)}
    for field in FIELDS:
        summary[field] = counters.data.get(field, 0)
    return summary


def rebase_surveillance_for_facility(facility_id):
    """A passing surveillance audit resets the clock on that facility's marks."""
    now = clock.now()
    product_ids = [
        product["id"]
        for product in db.products.values()
        if product["facility_id"] == facility_id
    ]
    for cert in db.ordered(db.certificates):
        if cert["product_id"] not in product_ids:
            continue
        if cert["status"] not in ("ISSUED", "SUSPENDED"):
            continue
        cert["surveillance_due_on"] = clock.add_days(now, SURVEILLANCE_INTERVAL_DAYS)
        cert["surveillance_status"] = "CURRENT"
        db.touch(cert)
