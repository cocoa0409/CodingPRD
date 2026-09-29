"""Derived app-product posture: counters and program states (PRD 2.11)."""

import db
from services.calc import REGULATED_CLASSES


def product_of_element(element):
    return db.get("app_products", element.get("app_product_id"))


def product_of_consumer(consumer):
    return db.get("app_products", consumer.get("app_product_id"))


def product_of_mapping(mapping):
    element = db.get("data_elements", mapping.get("data_element_id"))
    if element is None:
        return None
    return db.get("app_products", element.get("app_product_id"))


def product_of_consent(record):
    consumer = db.get("consumers", record.get("consumer_id"))
    if consumer is None:
        return None
    return product_of_consumer(consumer)


def product_of_request(row):
    consumer = db.get("consumers", row.get("consumer_id"))
    if consumer is None:
        return None
    return product_of_consumer(consumer)


def product_of_zone(zone):
    return db.get("app_products", zone.get("app_product_id"))


def product_of_campaign(campaign):
    zone = db.get("geofence_zones", campaign.get("geofence_zone_id"))
    if zone is None:
        return None
    return product_of_zone(zone)


# ---------------------------------------------------------------- element counts

def recount_elements(product):
    if product is None:
        return
    active = [e for e in db.db.data_elements.values()
              if e.get("app_product_id") == product["id"] and e.get("status") == "ACTIVE"]
    regulated = [e for e in active if e.get("chd_classification") in REGULATED_CLASSES]
    db.set_fields(product,
                  active_element_count=len(active),
                  regulated_element_count=len(regulated))


def recount_regulated_elements(product):
    if product is None:
        return
    active = [e for e in db.db.data_elements.values()
              if e.get("app_product_id") == product["id"] and e.get("status") == "ACTIVE"]
    regulated = [e for e in active if e.get("chd_classification") in REGULATED_CLASSES]
    db.set_fields(product, regulated_element_count=len(regulated))


# -------------------------------------------------------- share-consent counter

def recount_share_consent(product):
    """The conserved quantity of PRD 3.5, recomputed from the live records."""
    if product is None:
        return
    consumer_ids = set(c["id"] for c in db.db.consumers.values()
                       if c.get("app_product_id") == product["id"])
    total = len([r for r in db.db.consent_records.values()
                 if r.get("consumer_id") in consumer_ids
                 and r.get("record_state") == "ACTIVE"
                 and r.get("sharing_state") == "GRANTED"])
    db.set_fields(product, active_share_consent_count=total)


# -------------------------------------------------------------- breach exposure

def recount_exposure(product):
    if product is None:
        return
    total = 0
    for incident in db.db.breach_incidents.values():
        if incident.get("app_product_id") != product["id"]:
            continue
        if incident.get("state") in ("REPORTABLE", "NOTIFIED"):
            total += incident.get("exposure_contribution_cents", 0)
    db.set_fields(product, exposure_cents=total)


# ------------------------------------------------------- security program state

def refresh_security_program_state(product):
    if product is None:
        return
    finalized = [a for a in db.db.security_risk_assessments.values()
                 if a.get("app_product_id") == product["id"] and a.get("state") == "FINALIZED"]
    if not finalized:
        db.set_fields(product, security_program_state="NONE")
        return
    finalized.sort(key=db.sort_key)
    latest = finalized[-1]
    state = "CURRENT" if latest.get("risk_tier") in ("LOW", "MODERATE") else "STALE"
    db.set_fields(product, security_program_state=state)


# ----------------------------------------------------------- consumer counters

def recount_deletion_completed(consumer):
    if consumer is None:
        return
    total = len([r for r in db.db.consumer_requests.values()
                 if r.get("consumer_id") == consumer["id"]
                 and r.get("request_kind") == "DELETE"
                 and r.get("state") == "FULFILLED"])
    db.set_fields(consumer, deletion_completed_count=total)


def recount_outstanding_tasks(request_row):
    if request_row is None:
        return
    total = len([t for t in db.db.deletion_tasks.values()
                 if t.get("consumer_request_id") == request_row["id"]
                 and t.get("state") in ("PENDING", "NOTIFIED", "FAILED")])
    db.set_fields(request_row, outstanding_task_count=total)
