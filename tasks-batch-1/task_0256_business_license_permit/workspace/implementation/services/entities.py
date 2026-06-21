"""Entity construction / mutation helpers shared across routes.

Common fields per PRD §2.5: id, created_at, updated_at, version. ActivityCategory
is the lone exception — only id + created_at (no updated_at, no version).
"""
from datetime import datetime, timezone

from db import store, now_iso
import errors


# ---------------------------------------------------------------------------
def stamp_create(record):
    """Attach standard system fields to a fresh mutable entity."""
    rid = store.new_id()
    ts = now_iso()
    record["id"] = rid
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Bump version + updated_at together on any mutation (PRD §2.5)."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Existence lookups (raise ERR_NOT_FOUND when missing)
def get_activity_category(cid):
    rec = store.activity_categories.get(cid)
    if rec is None:
        raise errors.not_found("ActivityCategory not found")
    return rec


def get_business(bid):
    rec = store.businesses.get(bid)
    if rec is None:
        raise errors.not_found("Business not found")
    return rec


def get_application(aid):
    rec = store.applications.get(aid)
    if rec is None:
        raise errors.not_found("Application not found")
    return rec


def get_inspection(iid):
    rec = store.inspections.get(iid)
    if rec is None:
        raise errors.not_found("Inspection not found")
    return rec


def get_license(lid):
    rec = store.licenses.get(lid)
    if rec is None:
        raise errors.not_found("License not found")
    return rec


def get_endorsement(eid):
    rec = store.endorsements.get(eid)
    if rec is None:
        raise errors.not_found("Endorsement not found")
    return rec


def get_transfer(tid):
    rec = store.transfers.get(tid)
    if rec is None:
        raise errors.not_found("OwnershipTransfer not found")
    return rec


def get_fee_assessment(fid):
    rec = store.fee_assessments.get(fid)
    if rec is None:
        raise errors.not_found("FeeAssessment not found")
    return rec


# ---------------------------------------------------------------------------
# FeeAssessment ledger helper
def create_fee_assessment(kind, amount, license_id=None, application_id=None, settled=False):
    rec = {
        "license_id": license_id,
        "application_id": application_id,
        "kind": kind,
        "amount": amount,
        "settled": settled,
    }
    stamp_create(rec)
    store.fee_assessments[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Clock helpers
def parse_iso8601(value):
    """Parse an ISO 8601 instant into an aware UTC datetime. Raises ValueError on bad input."""
    if not isinstance(value, str):
        raise ValueError("clock instant must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Advance a datetime by whole months, keeping day/time where possible."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # clamp day to last valid day of target month
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
            if day < 1:
                raise


def days_overdue(expires_on_dt, clock_now):
    """Whole UTC days from expires_on to now, floored (discard fractional day)."""
    delta = clock_now - expires_on_dt
    return delta.days if delta.days >= 0 else delta.days  # timedelta.days is already floor toward -inf


# ---------------------------------------------------------------------------
# Risk-score recompute (audited variant) over a business
import services.calc as calc


def sum_failed_items_for_business(business_id):
    """AUDITED open_violation_count = sum of Inspection.failed_item_count across this
    business's inspections (reached via the business's applications)."""
    app_ids = {a["id"] for a in store.applications.values() if a.get("business_id") == business_id}
    total = 0
    for insp in store.inspections.values():
        if insp.get("application_id") in app_ids:
            total += int(insp.get("failed_item_count") or 0)
    return total


def activity_base_risk_for_business(business_id):
    """Pick the activity_base_risk for the business. Use the most-recent application's
    activity category; fall back to 0 if none."""
    apps = [a for a in store.applications.values() if a.get("business_id") == business_id]
    if not apps:
        return 0
    apps.sort(key=lambda a: a["created_at"])
    latest = apps[-1]
    cat = store.activity_categories.get(latest.get("activity_category_id"))
    if cat is None:
        return 0
    return int(cat.get("activity_base_risk") or 0)


def recompute_audited_risk(business):
    score = calc.compliance_risk_score(
        activity_base_risk_for_business(business["id"]),
        sum_failed_items_for_business(business["id"]),
        business["standing"],
        business["prior_revocation_flag"],
    )
    business["compliance_risk_score"] = score
    return score
