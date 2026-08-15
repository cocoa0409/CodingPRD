"""The airport sweep (rent_charge_overdue_scan), run once per logical-clock set
at the new instant, in the PRD 2.5 order:
  1. offer_window_expiry          (strictly AFTER the deadline flips OPEN -> EXPIRED)
  2. annual_rent_escalation       (before billing, so new charges see new rates)
  3. late_fee_accrual + delinquency flip
  4. insurance_compliance_check   (cert + environmental expiry; auto INSURANCE_LAPSE)
  5. abandoned_aircraft_storage_accrual
  6. cure_deadline escalation     (>= deadline: finding -> ESCALATED_TO_EVICTION,
                                   eviction case auto-FILED, lease EVICTION_PENDING)
  7. monthly_rent_charge billing  (one charge per elapsed calendar-month boundary)
"""
from datetime import timedelta

import db
from services.core import (
    OCCUPYING_LEASE_STATES,
    apply_escalation,
    apply_late_fee,
    covering_certificate,
    create_rent_charge,
    file_finding,
    next_month_boundary,
    open_finding_of_type,
    recompute_lease_derived,
    touch,
)
from timeutil import iso_z, parse_iso, whole_days


def _signature():
    """Cheap change detector: entity counts + version sums across all stores."""
    stores = (
        db.airports, db.hangars, db.rate_schedules, db.applications, db.offers,
        db.leases, db.aircraft, db.certificates, db.env_records, db.inspections,
        db.findings, db.eviction_cases, db.rent_charges,
    )
    counts = sum(len(s) for s in stores)
    versions = sum(e["version"] for s in stores for e in s.values())
    return counts, versions


def run_sweep(now):
    """Run passes in the PRD 2.5 duty order until a fixpoint: duties listed
    before billing (late fees, delinquency) must still observe charges the
    billing pass creates, so the instant's resulting state matches what a live
    system would have produced. Every step is idempotent at a fixed instant."""
    for _ in range(6):
        before = _signature()
        _expire_offers(now)
        _apply_escalations(now)
        _accrue_late_fees_and_delinquency(now)
        _expire_compliance_and_flag_lapses(now)
        _accrue_abandoned_storage(now)
        _escalate_cure_deadlines(now)
        _bill_monthly_charges(now)
        if _signature() == before:
            break


def _expire_offers(now):
    for offer in list(db.offers.values()):
        if offer["status"] != "OPEN":
            continue
        # Sweep boundary is STRICTLY AFTER: at exactly the deadline the row
        # stays OPEN in storage (the accept path rejects it separately).
        if now > parse_iso(offer["acceptance_deadline"]):
            offer["status"] = "EXPIRED"
            touch(offer)
            app = db.applications.get(offer["application_id"])
            if app is not None and app["status"] == "OFFERED":
                app["status"] = "EXPIRED_OFFER"
                touch(app)


def _apply_escalations(now):
    for lease in list(db.leases.values()):
        if lease["status"] not in OCCUPYING_LEASE_STATES:
            continue
        airport = db.airports[lease["airport_id"]]
        apply_escalation(lease, airport, now)


def _accrue_late_fees_and_delinquency(now):
    for charge in list(db.rent_charges.values()):
        if charge["status"] not in ("OPEN", "PARTIALLY_PAID"):
            continue
        lease = db.leases.get(charge["lease_id"])
        if lease is None:
            continue
        airport = db.airports[lease["airport_id"]]
        apply_late_fee(airport, charge, now)
    for lease in list(db.leases.values()):
        recompute_lease_derived(lease, now, flip_delinquent=True)


def _expire_compliance_and_flag_lapses(now):
    for cert in list(db.certificates.values()):
        if cert["status"] == "VALID" and parse_iso(cert["effective_to"]) <= now:
            cert["status"] = "EXPIRED"
            touch(cert)
    for rec in list(db.env_records.values()):
        if rec["status"] in ("PENDING_REVIEW", "APPROVED") and parse_iso(rec["expires_at"]) <= now:
            rec["status"] = "EXPIRED"
            touch(rec)
    for lease in list(db.leases.values()):
        if lease["status"] not in ("ACTIVE", "DELINQUENT"):
            continue
        if covering_certificate(lease["id"], now) is not None:
            continue
        if open_finding_of_type(lease["id"], "INSURANCE_LAPSE") is not None:
            continue
        # System-triggered filing: skips the sublease check, needs only
        # ACTIVE or DELINQUENT.
        file_finding(lease, "INSURANCE_LAPSE", now)


def _accrue_abandoned_storage(now):
    for case in list(db.eviction_cases.values()):
        if case["status"] != "EXECUTED":
            continue
        lease = db.leases.get(case["lease_id"])
        if lease is None:
            continue
        based = [
            a for a in db.aircraft.values()
            if a["lease_id"] == lease["id"] and a["status"] == "BASED"
        ]
        if not based:
            continue
        days_total = whole_days(parse_iso(case["executed_at"]), now)
        days_accrued = days_total - case["storage_days_already_billed"]
        if days_accrued <= 0:
            continue
        amount = days_accrued * case["abandoned_aircraft_storage_cents_per_day"] * len(based)
        period_start = parse_iso(case["executed_at"]) + timedelta(days=case["storage_days_already_billed"])
        create_rent_charge(lease["id"], period_start, now, amount, kind="STORAGE")
        case["storage_days_already_billed"] += days_accrued
        touch(case)
        lease["outstanding_balance_cents"] += amount
        touch(lease)


def _escalate_cure_deadlines(now):
    for finding in list(db.findings.values()):
        if finding["status"] != "OPEN":
            continue
        # Boundary-inclusive: at exactly the cure deadline the finding escalates.
        if now < parse_iso(finding["cure_deadline"]):
            continue
        finding["status"] = "ESCALATED_TO_EVICTION"
        touch(finding)
        case = db.new_entity({
            "lease_id": finding["lease_id"],
            "use_audit_finding_id": finding["id"],
            "reason": "UNCURED_AUDIT",
            "filed_at": iso_z(now),
            "executed_at": None,
            "abandoned_aircraft_storage_cents_per_day": 0,
            "storage_days_already_billed": 0,
            "status": "FILED",
        })
        db.eviction_cases[case["id"]] = case
        lease = db.leases.get(finding["lease_id"])
        if lease is not None and lease["status"] in ("ACTIVE", "DELINQUENT", "CURE_PERIOD"):
            lease["status"] = "EVICTION_PENDING"
            touch(lease)


def _bill_monthly_charges(now):
    for lease in list(db.leases.values()):
        if lease["status"] not in OCCUPYING_LEASE_STATES:
            continue
        rent_charges = sorted(
            [
                c for c in db.rent_charges.values()
                if c["lease_id"] == lease["id"] and c.get("_kind") == "RENT"
            ],
            key=lambda c: (parse_iso(c["period_start"]), c["_seq"]),
        )
        if not rent_charges:
            continue
        boundary = parse_iso(rent_charges[-1]["period_end"])
        created = 0
        # One charge per fully elapsed calendar-month boundary, oldest first;
        # never for a period beginning after the sweep instant.
        while boundary <= now:
            nxt = next_month_boundary(boundary)
            # Escalation already ran this sweep, so the rate in force at this
            # period's start is the lease's current_monthly_rate_cents.
            create_rent_charge(lease["id"], boundary, nxt, lease["current_monthly_rate_cents"], kind="RENT")
            created += 1
            boundary = nxt
        if created:
            lease["outstanding_balance_cents"] += created * lease["current_monthly_rate_cents"]
            touch(lease)
