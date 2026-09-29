"""Derived-field recomputation and the multi-hop cascades (PRD 2.7, 3.5-3.9).

Every hop guards on the SOURCE state, so a cascade that re-enters an already
transitioned entity terminates instead of looping.  System-triggered hops are
silently skipped when their own preconditions do not hold.
"""

from decimal import Decimal

import calc
import lookup
import store
from store import db, mark_dirty, now

RISK_INPUT_STATUSES = ("UNDER_INVESTIGATION", "ROOT_CAUSE_IDENTIFIED", "CAPA_OPENED", "CLOSED")


# =========================================================================
# derived-field recomputation
# =========================================================================
def recompute_risk_scores(product):
    """scaffold 1.3 design_risk_score (both variants, same input set)."""
    gross = Decimal("0")
    mitigated = Decimal("0")
    for incident in lookup.incidents_of_product(product["id"]):
        if incident["status"] not in RISK_INPUT_STATUSES:
            continue
        points = incident["incident_points"]
        if points is None:
            continue
        gross += points
        if _has_verified_capa(incident["id"]):
            mitigated += points * calc.CAPA_CREDIT_FACTOR
        else:
            mitigated += points
    product["risk_score_gross"] = calc.rhu(min(gross, calc.RISK_SCORE_CEILING), 2)
    product["risk_score_mitigated"] = calc.rhu(min(mitigated, calc.RISK_SCORE_CEILING), 2)
    mark_dirty(product)


def _has_verified_capa(incident_id):
    for action in db.corrective_actions.values():
        if action["field_incident_id"] == incident_id and action["status"] == "VERIFIED":
            return True
    return False


def recompute_dhf_retention(product):
    """scaffold 1.3 dhf_retention_until."""
    candidates = []

    c_lot = None
    for lot in lookup.lots_of_product(product["id"]):
        if lot["status"] in ("RELEASED", "QUARANTINED") and lot["released_at"] is not None:
            if c_lot is None or lot["released_at"] > c_lot:
                c_lot = lot["released_at"]

    c_incident = None
    for incident in lookup.incidents_of_product(product["id"]):
        if incident["status"] == "CLOSED" and incident["closed_at"] is not None:
            if c_incident is None or incident["closed_at"] > c_incident:
                c_incident = incident["closed_at"]

    c_recall = (
        product["market_status_changed_at"] if product["market_status"] == "RECALLED" else None
    )
    c_freeze = product["design_frozen_at"]

    if c_freeze is None:
        product["dhf_retention_until"] = None
        product["retention_anchor_source"] = None
        mark_dirty(product)
        return

    candidates = [
        ("LOT_RELEASE", c_lot),
        ("INCIDENT_CLOSURE", c_incident),
        ("RECALL", c_recall),
        ("DESIGN_FREEZE", c_freeze),
    ]
    anchor = None
    for _source, value in candidates:
        if value is not None and (anchor is None or value > anchor):
            anchor = value
    source = None
    for name, value in candidates:
        if value is not None and value == anchor:
            source = name
            break
    product["dhf_retention_until"] = calc.add_years(anchor, calc.RETENTION_YEARS)
    product["retention_anchor_source"] = source
    mark_dirty(product)


def recompute_held_registration_count(product):
    count = 0
    for registration in lookup.registrations_of_product(product["id"]):
        if registration["hold_flag"]:
            count += 1
    product["held_registration_count"] = count
    mark_dirty(product)
    return count


def recompute_lot_samples(lot, product):
    """scaffold 1.3 lot_conformance_index steps 3."""
    samples = sorted(lookup.samples_of_lot(lot["id"]), key=lambda row: row["sample_seq"])
    lot["joint_sample_count"] = len(samples)
    lot["joint_fail_count"] = len([s for s in samples if s["result"] == "FAIL"])
    lot["conformance_index"] = calc.conformance_index([s["margin_pct"] for s in samples])
    lot["required_joint_sample_count"] = calc.required_joint_sample_count(lot["produced_units"])
    mark_dirty(lot)


def recompute_campaign_counters(campaign):
    tests = lookup.load_tests_of_campaign(campaign["id"])
    campaign["load_test_count"] = len(tests)
    campaign["failed_test_count"] = len([t for t in tests if t["outcome"] == "FAIL"])
    mark_dirty(campaign)


# =========================================================================
# listing / campaign / reservation helpers
# =========================================================================
def cancel_reservations_of_campaign(campaign):
    for reservation in lookup.where(db.bench_reservations, test_campaign_id=campaign["id"]):
        if reservation["status"] != "HELD":
            continue
        reservation["status"] = "CANCELLED"
        mark_dirty(reservation)
        bench = db.test_benches.get(reservation["test_bench_id"])
        if bench is not None:
            bench["reserved_minutes_total"] = (
                bench["reserved_minutes_total"] - reservation["duration_minutes"]
            )
            mark_dirty(bench)


def cancel_planned_campaigns(product_id):
    for campaign in lookup.campaigns_of_product(product_id):
        if campaign["status"] != "PLANNED":
            continue
        campaign["status"] = "CANCELLED"
        mark_dirty(campaign)
        cancel_reservations_of_campaign(campaign)


def _apply_listing_suspension(record, reason):
    record["status"] = "SUSPENDED"
    record["suspended_at"] = now()
    record["suspension_reason"] = reason
    record["audit_due_at"] = None
    mark_dirty(record)


def suspend_listed_listings(product, reason):
    for record in lookup.listings_of_product(product["id"]):
        if record["status"] == "LISTED":
            _apply_listing_suspension(record, reason)


def restore_suspended_listings(product):
    for record in lookup.listings_of_product(product["id"]):
        if record["status"] != "SUSPENDED":
            continue
        record["status"] = "LISTED"
        record["suspended_at"] = None
        record["suspension_reason"] = None
        body = db.listing_bodies.get(record["listing_body_id"])
        if body is not None:
            record["audit_due_at"] = calc.add_days(now(), body["audit_interval_days"])
        mark_dirty(record)


# =========================================================================
# product market-status cascades
# =========================================================================
def product_enter_stop_ship(product, reason_code):
    """RETAIL_RELEASED -> STOP_SHIP plus its listing and campaign hops.

    Returns True when the transition applied; False when the guard blocked it
    (already STOP_SHIP, RECALLED or never released) so the chain terminates.
    """
    if product["market_status"] != "RETAIL_RELEASED":
        return False
    product["market_status"] = "STOP_SHIP"
    product["stop_ship_reason_code"] = reason_code
    product["market_status_changed_at"] = now()
    mark_dirty(product)
    suspend_listed_listings(product, "STOP_SHIP_CASCADE")
    cancel_planned_campaigns(product["id"])
    return True


def listing_suspend(record, reason_code):
    """LISTED -> SUSPENDED, then the product stop-ship hop."""
    _apply_listing_suspension(record, reason_code)
    product = db.products.get(record["product_id"])
    if product is not None:
        product_enter_stop_ship(product, "LISTING_SUSPENDED")


def resume_ship_ready(product):
    if product["market_status"] != "STOP_SHIP":
        return False
    if product["risk_score_mitigated"] >= calc.RISK_CLEAR_THRESHOLD:
        return False
    for lot in lookup.lots_of_product(product["id"]):
        if lot["status"] == "QUARANTINED":
            return False
    if product["held_registration_count"] != 0:
        return False
    return True


def product_resume_ship(product):
    """STOP_SHIP -> RETAIL_RELEASED plus the listing restoration hop."""
    product["market_status"] = "RETAIL_RELEASED"
    product["stop_ship_reason_code"] = None
    product["market_status_changed_at"] = now()
    mark_dirty(product)
    restore_suspended_listings(product)


def try_system_resume(product):
    """System-triggered arm: silently skipped when a precondition fails."""
    if not resume_ship_ready(product):
        return False
    product_resume_ship(product)
    return True


# =========================================================================
# lot quarantine cascade (5 hops)
# =========================================================================
def lot_quarantine(lot, reason_code):
    product = db.products.get(lot["product_id"])
    lot["units_quarantined"] = lot["units_quarantined"] + lot["units_wip"] + lot["units_released"]
    lot["units_wip"] = 0
    lot["units_released"] = 0
    lot["status"] = "QUARANTINED"
    lot["quarantine_reason_code"] = reason_code
    mark_dirty(lot)

    # HOP 1 — registrations of the lot are placed on hold.
    for registration in lookup.registrations_of_lot(lot["id"]):
        if registration["registration_status"] in ("REGISTERED", "NOTIFIED"):
            if not registration["hold_flag"]:
                registration["hold_flag"] = True
                mark_dirty(registration)

    if product is None:
        return
    # HOP 2 — held count recomputed; a released model moves to STOP_SHIP.
    held = recompute_held_registration_count(product)
    if held > 0:
        # HOPS 3-5 happen inside the stop-ship transition.
        product_enter_stop_ship(product, "LOT_QUARANTINE")


# =========================================================================
# audit failure cascade (4 hops)
# =========================================================================
def audit_failure_cascade(campaign):
    # HOP 1 — the audited listing is suspended for AUDIT_FAILURE.
    record = None
    if campaign["listing_record_id"]:
        record = db.listing_records.get(campaign["listing_record_id"])
    if record is not None and record["status"] == "LISTED":
        _apply_listing_suspension(record, "AUDIT_FAILURE")
        product = db.products.get(record["product_id"])
        # HOP 2 (and HOPS 4-5: campaign / reservation cancellation).
        if product is not None:
            product_enter_stop_ship(product, "LISTING_SUSPENDED")

    # HOP 3 — the sampled lot is quarantined for AUDIT_FAILURE.
    lot = None
    if campaign["sampled_lot_id"]:
        lot = db.production_lots.get(campaign["sampled_lot_id"])
    if lot is not None and lot["status"] in ("IN_PROCESS", "RELEASED"):
        lot_quarantine(lot, "AUDIT_FAILURE")


# =========================================================================
# CAPA verification cascade (4 hops)
# =========================================================================
def capa_verification_cascade(action, verifier_id):
    action["status"] = "VERIFIED"
    action["verified_at"] = now()
    action["verified_by_user_id"] = verifier_id
    mark_dirty(action)

    # HOP 1/2 — the incident closes.
    incident = db.field_incidents.get(action["field_incident_id"])
    if incident is None:
        return
    if incident["status"] == "CAPA_OPENED":
        incident["status"] = "CLOSED"
        incident["closed_at"] = now()
        mark_dirty(incident)

    product = db.products.get(incident["product_id"])
    if product is None:
        return
    # HOP 3 — risk scores and retention are re-derived.
    recompute_risk_scores(product)
    recompute_dhf_retention(product)
    # HOP 4 — the model may resume shipping.
    try_system_resume(product)


# =========================================================================
# recall announcement
# =========================================================================
def in_scope_lots(recall):
    scope = set(recall["affected_revision_ids"])
    result = []
    for lot in lookup.lots_of_product(recall["product_id"]):
        if lot["design_revision_id"] not in scope:
            continue
        if lot["status"] not in ("RELEASED", "QUARANTINED"):
            continue
        if lot["released_at"] is None:
            continue
        result.append(lot)
    return result


def recall_exposure(recall):
    """scaffold 1.3 recall_exposure_units (both variants)."""
    lots = in_scope_lots(recall)
    lot_ids = set(lot["id"] for lot in lots)
    shipped = 0
    for lot in lots:
        shipped += lot["produced_units"] or 0
    registered = 0
    for registration in db.consumer_registrations.values():
        if registration["production_lot_id"] not in lot_ids:
            continue
        if registration["registration_status"] in ("REGISTERED", "NOTIFIED", "ACKNOWLEDGED"):
            registered += 1
    if shipped == 0:
        coverage = Decimal("0.00")
    else:
        coverage = calc.rhu(Decimal(registered) / Decimal(shipped) * Decimal(100), 2)
    return lots, shipped, registered, coverage


def announce_recall(recall):
    product = db.products[recall["product_id"]]
    lots, shipped, registered, coverage = recall_exposure(recall)
    lot_ids = set(lot["id"] for lot in lots)

    recall["status"] = "ANNOUNCED"
    recall["announced_at"] = now()
    recall["exposure_units_shipped_basis"] = shipped
    recall["exposure_units_registered_basis"] = registered
    recall["notification_coverage_pct"] = coverage
    recall["units_remedied"] = 0
    recall["units_outstanding"] = registered
    mark_dirty(recall)

    # in-scope registrations are stamped with the recall
    for registration in db.consumer_registrations.values():
        if registration["production_lot_id"] not in lot_ids:
            continue
        if registration["registration_status"] != "REGISTERED":
            continue
        registration["recall_event_id"] = recall["id"]
        mark_dirty(registration)

    product["market_status"] = "RECALLED"
    product["market_status_changed_at"] = now()
    if product["design_status"] == "DESIGN_FROZEN":
        product["design_status"] = "DESIGN_OBSOLETE"
    mark_dirty(product)

    for record in lookup.listings_of_product(product["id"]):
        if record["status"] in ("LISTED", "SUSPENDED"):
            record["status"] = "WITHDRAWN"
            record["audit_due_at"] = None
            mark_dirty(record)

    recompute_dhf_retention(product)
