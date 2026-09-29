"""Nonconformance creation and the shared escalation side-effect set."""

import clock
import db
from constants import CA_DUE_DAYS, SEVERITY_POINTS
from services import derive


def linked_certificates(nc, audit_fanout=True):
    """The named certificate, else every certificate reached from the source.

    `audit_fanout` is only true on the CRITICAL-at-creation path of §3.8, where the
    PRD spells the resolution out as "either the one named by `certificate_id` or
    the certificate reached from the source". The escalation side-effect set speaks
    of "the linked certificate" instead, so an audit-sourced finding that names no
    certificate has none.
    """
    if nc.get("certificate_id"):
        cert = db.certificates.get(nc["certificate_id"])
        return [cert] if cert is not None else []
    if nc.get("audit_id"):
        if not audit_fanout:
            return []
        audit = db.audits.get(nc["audit_id"])
        if audit is None:
            return []
        product_ids = [
            product["id"]
            for product in db.ordered(db.products)
            if product["facility_id"] == audit["facility_id"]
        ]
        found = []
        for product_id in product_ids:
            found.extend(derive.certificates_for_product(product_id))
        return found
    if nc.get("lot_test_id"):
        lot_test = db.lot_tests.get(nc["lot_test_id"])
        if lot_test is not None:
            cert = derive.active_certificate_for_product(lot_test["product_id"])
            if cert is not None:
                return [cert]
        return []
    if nc.get("complaint_id"):
        complaint = db.consumer_complaints.get(nc["complaint_id"])
        if complaint is not None:
            cert = db.certificates.get(complaint["certificate_id"])
            if cert is not None:
                return [cert]
    return []


def suspend_linked(nc, counters=None, reason="CRITICAL_NONCONFORMANCE",
                   audit_fanout=True):
    for cert in linked_certificates(nc, audit_fanout=audit_fanout):
        if cert["status"] == "ISSUED":
            derive.suspend_certificate(cert, reason, counters)


def create(applicant_id, source_type, category, severity, description,
           raised_by_user_id, certificate_id=None, audit_id=None,
           lot_test_id=None, complaint_id=None, counters=None,
           suspension_reason="CRITICAL_NONCONFORMANCE"):
    now = clock.now()
    row = db.insert(
        db.nonconformances,
        {
            "applicant_id": applicant_id,
            "certificate_id": certificate_id,
            "audit_id": audit_id,
            "lot_test_id": lot_test_id,
            "complaint_id": complaint_id,
            "source_type": source_type,
            "category": category,
            "severity": severity,
            "description": description,
            "status": "OPEN",
            "raised_by_user_id": raised_by_user_id,
            "penalty_points": SEVERITY_POINTS[severity],
            "ca_due_on": clock.add_days(now, CA_DUE_DAYS[severity]),
            "ca_plan_text": None,
            "ca_revision_count": 0,
            "ca_decided_by_user_id": None,
            "ca_rejection_reason": None,
            "ca_verified": False,
            "closed_on": None,
        },
    )
    derive.recompute_applicant_by_id(applicant_id)
    derive.recompute_audits_for_nonconformance(row)
    if severity == "CRITICAL":
        suspend_linked(row, counters, suspension_reason)
    return row


def escalate(nc, counters=None):
    """The shared ESCALATED side-effect set."""
    nc["status"] = "ESCALATED"
    db.touch(nc)
    suspend_linked(nc, counters, audit_fanout=False)
    derive.recompute_applicant_by_id(nc["applicant_id"])
    derive.recompute_audits_for_nonconformance(nc)
    return nc
