"""The synchronous multi-hop cascades of PRD 2.11 and section 3."""

import clock
import constants as K
import db
from services import posture
from services.calc import add_days, reclassify_product


def active_consent_record(consumer_id):
    rows = [r for r in db.rows_of("consent_records")
            if r.get("consumer_id") == consumer_id and r.get("record_state") == "ACTIVE"]
    return rows[-1] if rows else None


# ------------------------------------------------ data element retirement (3.2)

def retire_element(element, reason):
    """Hops 1-4 of the data element retirement cascade."""
    element["status"] = "RETIRED"
    element["retired_reason"] = reason
    db.touch(element)
    retired_ids = [element["id"]]

    # hop 2: transitively retire ACTIVE elements derived from a just-retired one.
    frontier = [element["id"]]
    while frontier:
        children = [e for e in db.rows_of("data_elements")
                    if e.get("derived_from_element_id") in frontier
                    and e.get("status") == "ACTIVE"]
        if not children:
            break
        nxt = []
        for child in children:
            child["status"] = "RETIRED"
            child["retired_reason"] = "SOURCE_ELEMENT_RETIRED"
            db.touch(child)
            retired_ids.append(child["id"])
            nxt.append(child["id"])
        frontier = nxt

    # hop 3: retire every non-terminal mapping onto any retired element.
    for mapping in db.rows_of("element_purpose_mappings"):
        if mapping.get("data_element_id") in retired_ids and \
                mapping.get("status") in ("PROPOSED", "ACTIVE", "SUSPENDED"):
            mapping["status"] = "RETIRED"
            mapping["suspension_reason"] = "SOURCE_ELEMENT_RETIRED"
            db.touch(mapping)

    # hop 4: refresh the product's element counters.
    posture.recount_elements(posture.product_of_element(element))


def reinstate_element(element):
    element["status"] = "ACTIVE"
    element["retired_reason"] = None
    db.touch(element)
    reclassify_product(element["app_product_id"])
    posture.recount_elements(posture.product_of_element(element))


# ------------------------------------------- vendor agreement termination (3.4)

def terminate_vendor(vendor):
    """The five-hop vendor termination cascade."""
    # hop 1
    vendor["agreement_state"] = "TERMINATED"
    vendor["terminated_at"] = clock.now()
    db.touch(vendor)

    # hop 2
    suspended_any = False
    for mapping in db.rows_of("element_purpose_mappings"):
        if mapping.get("vendor_id") == vendor["id"] and mapping.get("status") == "ACTIVE":
            mapping["status"] = "SUSPENDED"
            mapping["suspension_reason"] = "VENDOR_AGREEMENT_TERMINATED"
            db.touch(mapping)
            suspended_any = True
    if not suspended_any:
        return

    # hop 3
    product = db.get("app_products", vendor.get("app_product_id"))
    unseated_any = False
    for policy in db.rows_of("privacy_policy_versions"):
        if policy.get("app_product_id") == vendor.get("app_product_id") and \
                policy.get("state") == "PUBLISHED":
            policy["state"] = "SUPERSEDED_PENDING_UPDATE"
            db.touch(policy)
            unseated_any = True
    if not unseated_any:
        return

    # hop 4
    db.set_fields(product, policy_compliance_state="LAPSED")

    # hop 5
    zone_ids = set(z["id"] for z in db.db.geofence_zones.values()
                   if z.get("app_product_id") == vendor.get("app_product_id"))
    for campaign in db.rows_of("geofence_campaigns"):
        if campaign.get("geofence_zone_id") in zone_ids and campaign.get("state") == "ACTIVE":
            campaign["state"] = "PAUSED"
            campaign["pause_reason"] = "POLICY_LAPSED"
            db.touch(campaign)


# ---------------------------------------------------- consent withdrawal (3.5)

def withdraw_axis(record, axis, product):
    """Applies one consumer-driven withdrawal and its dependent hops."""
    now = clock.now()
    record["last_withdrawn_axis"] = axis
    record["last_withdrawn_at"] = now
    record["processing_halt_deadline_at"] = add_days(now, K.PROCESSING_HALT_DAYS)

    if axis == "COLLECT":
        record["collection_state"] = "WITHDRAWN"
        if record.get("sharing_state") == "GRANTED":
            record["sharing_state"] = "WITHDRAWN"
        if record.get("sale_state") == "AUTHORIZED":
            record["sale_state"] = "REVOKED"
    elif axis == "SHARE":
        record["sharing_state"] = "WITHDRAWN"
        if record.get("sale_state") == "AUTHORIZED":
            record["sale_state"] = "REVOKED"
    else:
        record["sale_state"] = "REVOKED"
    db.touch(record)
    posture.recount_share_consent(product)


def withdraw_all_axes(record):
    """Fulfilment hop 3: the deletion right collapses the whole record."""
    now = clock.now()
    if record.get("collection_state") == "GRANTED":
        record["collection_state"] = "WITHDRAWN"
    if record.get("sharing_state") == "GRANTED":
        record["sharing_state"] = "WITHDRAWN"
    if record.get("sale_state") == "AUTHORIZED":
        record["sale_state"] = "REVOKED"
    record["last_withdrawn_axis"] = "COLLECT"
    record["last_withdrawn_at"] = now
    record["processing_halt_deadline_at"] = add_days(now, K.PROCESSING_HALT_DAYS)
    db.touch(record)


# ------------------------------------------------- rights request outcomes (3.7)

def fulfill_request(request_row):
    """Moves a VERIFIED request to FULFILLED and runs hops 3 and 4."""
    request_row["state"] = "FULFILLED"
    db.touch(request_row)
    if request_row.get("request_kind") != "DELETE":
        return
    consumer = db.get("consumers", request_row.get("consumer_id"))
    product = posture.product_of_consumer(consumer) if consumer else None
    record = active_consent_record(request_row.get("consumer_id"))
    if record is not None:
        withdraw_all_axes(record)
    posture.recount_deletion_completed(consumer)
    posture.recount_share_consent(product)


def deny_request(request_row, reason):
    previous_state = request_row["state"]
    request_row["state"] = "DENIED"
    request_row["denial_reason"] = reason
    if previous_state == "VERIFICATION_PENDING":
        request_row["verification_window_ends_at"] = None
    db.touch(request_row)
    if previous_state == "VERIFIED":
        for task in db.rows_of("deletion_tasks"):
            if task.get("consumer_request_id") == request_row["id"] and \
                    task.get("state") in ("PENDING", "NOTIFIED", "FAILED"):
                task["state"] = "FAILED"
                task["failure_reason"] = "REQUEST_DENIED"
                db.touch(task)
        posture.recount_outstanding_tasks(request_row)
