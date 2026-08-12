"""Cross-entity derived state (billing_posture, Property.posture, cached
figures) and logical-clock-driven system transitions."""

from datetime import timedelta

from db import db, clock, touch
from services import calc


def recompute_billing_posture(lease):
    """billing_posture is derived, never set directly:
    FROZEN if any RecoveryBilling DISPUTED; else DELINQUENT if any ISSUED
    billing is unpaid more than 60 days past issued_at; else CURRENT."""
    new = "CURRENT"
    now = clock.current()
    for b in db["recovery_billings"].values():
        if b["lease_id"] != lease["id"]:
            continue
        if b["status"] == "DISPUTED":
            new = "FROZEN"
            break
    if new != "FROZEN":
        for b in db["recovery_billings"].values():
            if b["lease_id"] != lease["id"]:
                continue
            if b["status"] == "ISSUED" and b.get("issued_at"):
                issued = clock_parse(b["issued_at"])
                if now > issued + timedelta(days=60):
                    new = "DELINQUENT"
                    break
    if lease["billing_posture"] != new:
        lease["billing_posture"] = new
        touch(lease)
        recompute_property_posture(lease["property_id"])


def clock_parse(s):
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def recompute_property_posture(property_id):
    prop = db["properties"].get(property_id)
    if prop is None:
        return
    new = "OPERATING"
    for lease in db["leases"].values():
        if lease["property_id"] == property_id and \
           lease["status"] == "ACTIVE" and \
           lease["billing_posture"] == "FROZEN":
            new = "SUSPENDED"
            break
    if prop["posture"] != new:
        prop["posture"] = new
        touch(prop)


def recompute_recovery_ytd(lease):
    """cached_recovery_ytd_cents: ISSUED or PAID recovery billings in the
    current fiscal year."""
    prop = db["properties"][lease["property_id"]]
    fy = calc.current_fiscal_year(prop)
    total = 0
    for b in db["recovery_billings"].values():
        if b["lease_id"] == lease["id"] and \
           b["fiscal_year"] == fy and \
           b["status"] in ("ISSUED", "PAID"):
            total += b["estimate_cents"] or 0
    lease["cached_recovery_ytd_cents"] = total


def process_clock_transitions():
    """All date-driven system transitions, triggered by the logical clock
    advancing (POST /lease-admin/_clock/set_current_utc)."""
    today = clock.current().date()
    now = clock.current()

    # 1. Lease natural expiration: ACTIVE -> EXPIRED when clock reaches or
    #    passes expiration_date.
    for lease in list(db["leases"].values()):
        if lease["status"] == "ACTIVE" and \
           today >= calc.d(lease["expiration_date"]):
            lease["status"] = "EXPIRED"
            touch(lease)
            # Expiration cascade, same atomic instant.
            for cd in db["critical_dates"].values():
                if cd["lease_id"] == lease["id"] and \
                   cd["status"] == "PENDING" and \
                   calc.d(cd["due_date"]) <= today:
                    cd["status"] = "LAPSED"
                    touch(cd)
            for r in db["reconciliations"].values():
                if r["lease_id"] == lease["id"] and \
                   r["status"] in ("OPEN", "POSTED"):
                    r["status"] = "CLOSED"
                    touch(r)
            for doc in db["compliance_docs"].values():
                if doc["lease_id"] == lease["id"] and \
                   doc["status"] in ("SUBMITTED", "UNDER_REVIEW"):
                    doc["status"] = "EXPIRED"
                    touch(doc)

    # 2. CriticalDate lapsing: PENDING/NOTIFIED whose due_date has passed.
    for cd in list(db["critical_dates"].values()):
        if cd["status"] in ("PENDING", "NOTIFIED") and \
           today > calc.d(cd["due_date"]):
            cd["status"] = "LAPSED"
            touch(cd)

    # 3. ComplianceDoc expiry: SUBMITTED/UNDER_REVIEW/ACCEPTED past period_end.
    for doc in list(db["compliance_docs"].values()):
        if doc["status"] in ("SUBMITTED", "UNDER_REVIEW", "ACCEPTED") and \
           today >= calc.d(doc["period_end"]):
            doc["status"] = "EXPIRED"
            touch(doc)
            # An expiring insurance cert may leave the lease uncovered.
            lease = db["leases"].get(doc["lease_id"])
            if lease is not None:
                recompute_billing_posture(lease)

    # 4. AuditRight time-barring: INVOKED/FIELDWORK at or past window close.
    for ar in list(db["audit_rights"].values()):
        if ar["status"] in ("INVOKED", "FIELDWORK") and \
           ar.get("window_close_date") and \
           today >= calc.d(ar["window_close_date"]):
            ar["status"] = "TIME_BARRED"
            touch(ar)
            # ESCALATED challenges on the same reconciliation revert.
            for ch in db["tenant_challenges"].values():
                if ch["reconciliation_id"] == ar["reconciliation_id"] and \
                   ch["status"] == "ESCALATED":
                    ch["status"] = "UNDER_REVIEW"
                    touch(ch)

    # 5. billing_posture recomputation across leases (DELINQUENT windows move
    #    with the clock).
    for lease in list(db["leases"].values()):
        recompute_billing_posture(lease)
