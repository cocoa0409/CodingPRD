"""Core domain services: cascades, calculations, audit readiness."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store
import clock
import util
import errors


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_or_404(table, entity_id, label="Resource"):
    ent = table.get(entity_id)
    if ent is None:
        raise errors.not_found(f"{label} not found: {entity_id}")
    return ent


def get_clinic(cid):
    return get_or_404(store.clinics, cid, "VeterinaryClinic")


def get_vet(vid):
    return get_or_404(store.veterinarians, vid, "Veterinarian")


def get_producer(pid):
    return get_or_404(store.producers, pid, "Producer")


def get_animal_group(gid):
    return get_or_404(store.animal_groups, gid, "AnimalGroup")


def get_drug(did):
    return get_or_404(store.drugs, did, "VfdDrug")


def get_vcp(vid):
    return get_or_404(store.vcp_verifications, vid, "VcpVerification")


def get_vfd(vid):
    return get_or_404(store.vfd_authorizations, vid, "VfdAuthorization")


def get_feed_mill(mid):
    return get_or_404(store.feed_mills, mid, "FeedMill")


def get_feed_order(oid):
    return get_or_404(store.feed_orders, oid, "FeedOrder")


def get_shipment(sid):
    return get_or_404(store.feed_shipments, sid, "FeedShipment")


def get_withdrawal_plan(pid):
    return get_or_404(store.withdrawal_plans, pid, "WithdrawalPlan")


def get_ack(aid):
    return get_or_404(store.distributor_acknowledgments, aid, "DistributorAcknowledgment")


def get_residue_case(rid):
    return get_or_404(store.residue_cases, rid, "ResidueCase")


def get_audit_bundle(aid):
    return get_or_404(store.audit_bundles, aid, "AuditBundle")


# ---------------------------------------------------------------------------
# VFD quota (PRD 2.8)
# ---------------------------------------------------------------------------

def recompute_vfd_remaining(vfd):
    """remaining = authorized - sum(animal_count of orders in VALIDATED/SHIPPED/DELIVERED)."""
    used = 0
    for order in store.feed_orders.values():
        if order.get("vfd_authorization_id") == vfd["id"] and order.get("status") in (
            "VALIDATED", "SHIPPED", "DELIVERED"
        ):
            used += order.get("animal_count", 0)
    vfd["remaining_animal_count"] = vfd["authorized_animal_count"] - used


# ---------------------------------------------------------------------------
# VFD expiration / revocation cascade (PRD 3.4)
# ---------------------------------------------------------------------------

def _cancel_order_for_vfd_cascade(order):
    """Cascade-cancel an order in SUBMITTED or VALIDATED. Sets rejection_reason
    'VFD_EXPIRED', compensating quota + pending count when it was VALIDATED."""
    if order["status"] not in ("SUBMITTED", "VALIDATED"):
        return
    was_validated = order["status"] == "VALIDATED"
    order["status"] = "CANCELLED"
    order["rejection_reason"] = "VFD_EXPIRED"
    util.touch(order)
    if was_validated:
        mill = store.feed_mills.get(order["feed_mill_id"])
        if mill is not None:
            mill["pending_order_count"] = max(0, mill.get("pending_order_count", 0) - 1)
            util.touch(mill)


def cascade_vfd_terminal(vfd, new_status):
    """Transition a VFD into EXPIRED / REVOKED / SUPERSEDED with the shared
    FeedOrder cancellation cascade (PRD 3.4). Bumps VFD version."""
    if vfd["status"] not in ("ISSUED", "PARTIALLY_USED"):
        return
    vfd["status"] = new_status
    util.touch(vfd)
    # Fire per-order cascade
    for order in list(store.feed_orders.values()):
        if order.get("vfd_authorization_id") == vfd["id"]:
            _cancel_order_for_vfd_cascade(order)
    # After order cancellations, recompute quota (validated orders add back).
    recompute_vfd_remaining(vfd)


def expire_vfds_for_vet(vet_id):
    for vfd in list(store.vfd_authorizations.values()):
        if vfd.get("vet_id") == vet_id and vfd.get("status") in ("ISSUED", "PARTIALLY_USED"):
            cascade_vfd_terminal(vfd, "EXPIRED")


def expire_vfds_for_vcp(vet_id, producer_id):
    for vfd in list(store.vfd_authorizations.values()):
        if (
            vfd.get("vet_id") == vet_id
            and vfd.get("producer_id") == producer_id
            and vfd.get("status") in ("ISSUED", "PARTIALLY_USED")
        ):
            cascade_vfd_terminal(vfd, "EXPIRED")


def expire_vfds_for_producer(producer_id):
    for vfd in list(store.vfd_authorizations.values()):
        if vfd.get("producer_id") == producer_id and vfd.get("status") in ("ISSUED", "PARTIALLY_USED"):
            cascade_vfd_terminal(vfd, "EXPIRED")


# ---------------------------------------------------------------------------
# Clock-driven transitions (PRD 2.5)
# ---------------------------------------------------------------------------

def apply_clock_cascades():
    now = clock.now()
    for vfd in list(store.vfd_authorizations.values()):
        if vfd.get("status") in ("ISSUED", "PARTIALLY_USED"):
            exp = util.parse_iso(vfd["expiration_date"], "expiration_date")
            if now >= exp:
                cascade_vfd_terminal(vfd, "EXPIRED")
    for vcp in list(store.vcp_verifications.values()):
        if vcp.get("status") == "ACTIVE":
            exp = util.parse_iso(vcp["expires_on"], "expires_on")
            if now >= exp:
                vcp["status"] = "EXPIRED"
                util.touch(vcp)


# ---------------------------------------------------------------------------
# Withdrawal calculations (PRD 2.6, 3.5, 3.6)
# ---------------------------------------------------------------------------

def compute_provisional_market_date(withdrawal_hours, earliest_market_date):
    from datetime import timedelta
    now = clock.now()
    projected = now + timedelta(hours=withdrawal_hours)
    emd = util.parse_iso(earliest_market_date, "earliest_market_date")
    chosen = max(projected, emd)
    return util.iso_minute(chosen)


def compute_final_market_date(last_feed_consumed_at, withdrawal_hours):
    from datetime import timedelta
    base = util.parse_iso(last_feed_consumed_at, "last_feed_consumed_at")
    return util.iso_minute(base + timedelta(hours=withdrawal_hours))


# ---------------------------------------------------------------------------
# Residue calculations (PRD 3.8)
# ---------------------------------------------------------------------------

def compute_severity_tier(residue_ppb, tolerance_ppb):
    ratio = residue_ppb / tolerance_ppb
    if ratio < 2.0:
        return "TIER_1"
    if ratio < 5.0:
        return "TIER_2"
    return "TIER_3"


def _round_half_up_int(x):
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_penalty_deduction(residue_ppb, tolerance_ppb):
    ratio = residue_ppb / tolerance_ppb
    deduction = 0
    if ratio > 1.0:
        deduction += _round_half_up_int(min(ratio, 2.0) - 1.0) * 50
    if ratio > 2.0:
        deduction += _round_half_up_int(min(ratio, 5.0) - 2.0) * 150
    if ratio > 5.0:
        deduction += _round_half_up_int(ratio - 5.0) * 400
    deduction += 100
    return deduction


# ---------------------------------------------------------------------------
# Clinic audit readiness (PRD 2.9)
# ---------------------------------------------------------------------------

def recompute_audit_ready(clinic):
    score_ok = clinic.get("compliance_score", 0) >= 700
    if not score_ok:
        clinic["audit_ready"] = False
        return
    # any OPEN residue case on any producer reached via any VFD issued by
    # any vet of this clinic
    vet_ids = {v["id"] for v in store.veterinarians.values() if v.get("clinic_id") == clinic["id"]}
    producer_ids = {
        vfd.get("producer_id")
        for vfd in store.vfd_authorizations.values()
        if vfd.get("vet_id") in vet_ids
    }
    for case in store.residue_cases.values():
        if case.get("status") == "OPEN" and case.get("producer_id") in producer_ids:
            clinic["audit_ready"] = False
            return
    clinic["audit_ready"] = True


def recompute_all_clinics_audit_ready():
    for clinic in store.clinics.values():
        recompute_audit_ready(clinic)


# ---------------------------------------------------------------------------
# Audit required records (PRD 2.10, 3.9)
# ---------------------------------------------------------------------------

TERMINAL_STATUS = {
    "VfdAuthorization": {"EXPIRED", "REVOKED", "SUPERSEDED", "FULLY_USED"},
    "FeedOrder": {"DELIVERED", "CANCELLED", "REJECTED"},
    "FeedShipment": {"DELIVERED", "RETURNED", "REJECTED_AT_RECEIPT"},
    "DistributorAcknowledgment": {"LAPSED"},
}


def _record_intersects(rec, terminal_statuses, window_start, window_end):
    """Half-open window [start, end): record.created_at < window_end AND
    (terminal_at IS NULL OR terminal_at >= window_start)."""
    created = util.parse_iso(rec["created_at"], "created_at")
    if not (created < window_end):
        return False
    if rec.get("status") in terminal_statuses:
        terminal_at = util.parse_iso(rec["updated_at"], "updated_at")
        if terminal_at < window_start:
            return False
    return True


def compute_required_record_count(producer_id, window_start, window_end):
    count = 0
    # VFDs for producer
    for vfd in store.vfd_authorizations.values():
        if vfd.get("producer_id") == producer_id and _record_intersects(
            vfd, TERMINAL_STATUS["VfdAuthorization"], window_start, window_end
        ):
            count += 1
    # Orders for producer
    included_orders = []
    included_mill_ids = set()
    for order in store.feed_orders.values():
        if order.get("producer_id") == producer_id and _record_intersects(
            order, TERMINAL_STATUS["FeedOrder"], window_start, window_end
        ):
            count += 1
            included_orders.append(order)
            included_mill_ids.add(order.get("feed_mill_id"))
    # Shipments via those orders
    order_ids = {o["id"] for o in included_orders}
    for shipment in store.feed_shipments.values():
        if shipment.get("feed_order_id") in order_ids and _record_intersects(
            shipment, TERMINAL_STATUS["FeedShipment"], window_start, window_end
        ):
            count += 1
    # DistributorAcknowledgments belonging to feed mills of any included order
    for ack in store.distributor_acknowledgments.values():
        if ack.get("feed_mill_id") in included_mill_ids and _record_intersects(
            ack, TERMINAL_STATUS["DistributorAcknowledgment"], window_start, window_end
        ):
            count += 1
    return count
