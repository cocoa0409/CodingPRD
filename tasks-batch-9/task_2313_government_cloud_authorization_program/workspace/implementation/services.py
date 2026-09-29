"""Counter reconciliation, cascades and cross-entity side effects (PRD §2.11, §3)."""
from datetime import timedelta
from decimal import Decimal

import calc
from core import (
    db,
    fail,
    make_instant,
    new_record,
    now,
    rows,
    touch,
)

NOTICE_SOURCE_STATES = ("PACKAGE_ACCESS_GRANTED", "INCREMENTAL_REVIEW", "REUSE_ACCEPTED")
PACKAGE_OPEN_STATES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED")


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def offering_of_engagement(engagement):
    return db.offerings.get(engagement["offering_id"])


def authorization_of_offering(offering_id):
    found = None
    for a in rows("authorizations"):
        if a["offering_id"] == offering_id:
            found = a
    return found


def offering_of_authorization(authorization):
    return db.offerings.get(authorization["offering_id"])


def packages_of(offering_id):
    return [p for p in rows("packages") if p["offering_id"] == offering_id]


def grants_of_authorization(authorization_id):
    return [g for g in rows("reuse_grants") if g["authorization_id"] == authorization_id]


def grants_of_agency(agency_id):
    return [g for g in rows("reuse_grants") if g["agency_id"] == agency_id]


def periods_of(authorization_id):
    return [p for p in rows("monitoring_periods") if p["authorization_id"] == authorization_id]


def submissions_of(period_id):
    return [s for s in rows("scan_submissions") if s["monitoring_period_id"] == period_id]


def deviations_of(poam_item_id):
    return [d for d in rows("deviations") if d["poam_item_id"] == poam_item_id]


# ---------------------------------------------------------------------------
# Counter reconciliation (values only; version bumps are explicit at call sites)
# ---------------------------------------------------------------------------


def sync_agency(agency):
    agency["sponsored_offering_count"] = sum(
        1 for o in rows("offerings") if o.get("sponsor_agency_id") == agency["id"]
    )
    grants = grants_of_agency(agency["id"])
    agency["reuse_grant_count"] = sum(1 for g in grants if g["access_state"] != "REVOKED")
    agency["open_notice_count"] = sum(1 for g in grants if g["access_state"] == "NOTICE_ISSUED")


def sync_offering_packages(offering):
    pkgs = packages_of(offering["id"])
    offering["open_package_count"] = sum(1 for p in pkgs if p["status"] in PACKAGE_OPEN_STATES)
    offering["superseded_package_count"] = sum(1 for p in pkgs if p["status"] == "SUPERSEDED")


def sync_engagement_hours(engagement):
    allocated, unallocated = calc.hour_ledger(engagement)
    engagement["allocated_hours"] = allocated
    engagement["unallocated_hours"] = unallocated


def sync_period_counters(period):
    subs = submissions_of(period["id"])
    period["accepted_submission_count"] = sum(1 for s in subs if s["status"] == "ACCEPTED")
    period["late_submission_count"] = sum(1 for s in subs if s["status"] == "LATE_ACCEPTED")
    period["rejected_submission_count"] = sum(1 for s in subs if s["status"] == "REJECTED")
    covered = set()
    for s in subs:
        if s["status"] in ("ACCEPTED", "LATE_ACCEPTED"):
            covered.update(s["scan_types"])
    period["covered_scan_types"] = sorted(covered)


def sync_authorization_seats(authorization):
    granted = sum(
        1 for g in grants_of_authorization(authorization["id"]) if g["access_state"] != "REVOKED"
    )
    authorization["reuse_seats_granted"] = granted
    authorization["reuse_seats_available"] = int(authorization["reuse_seats_total"]) - granted


def sync_authorization_findings(authorization):
    items = calc.findings_of(authorization["offering_id"])
    authorization["total_findings_count"] = len(items)
    authorization["open_findings_count"] = sum(
        1 for i in items if i["remediation_status"] != "CLOSED"
    )
    authorization["closed_findings_count"] = sum(
        1 for i in items if i["remediation_status"] == "CLOSED"
    )
    authorization["risk_accepted_findings_count"] = sum(
        1 for i in items if i["risk_disposition"] == "RISK_ACCEPTED"
    )
    score = calc.residual_risk(authorization["offering_id"])
    authorization["residual_risk_score"] = score
    authorization["poam_risk_tier"] = calc.risk_tier(score)


def refresh_authorization_for_offering(offering_id):
    """Recompute the authorization's derived fields; the refresh counts as a mutation."""
    authorization = authorization_of_offering(offering_id)
    if authorization is None:
        return None
    sync_authorization_findings(authorization)
    sync_authorization_seats(authorization)
    touch(authorization)
    return authorization


# ---------------------------------------------------------------------------
# Engagement / test-slot cascades
# ---------------------------------------------------------------------------


def complete_scheduled_slots(engagement):
    for slot in calc.slots_of(engagement["id"]):
        if slot["status"] == "SCHEDULED":
            slot["status"] = "COMPLETED"
            touch(slot)


def void_engagement(engagement):
    """Cascade: the package it backs was rejected at the revision limit."""
    if engagement["status"] not in ("PLAN_APPROVED", "TESTING", "REPORT_DELIVERED"):
        return
    for slot in calc.slots_of(engagement["id"]):
        if slot["status"] == "SCHEDULED":
            slot["status"] = "CANCELLED"
            touch(slot)
    engagement["status"] = "VOIDED"
    sync_engagement_hours(engagement)
    touch(engagement)


# ---------------------------------------------------------------------------
# PoamItem creation used by the assessment report
# ---------------------------------------------------------------------------


def create_poam_item(offering_id, control_id, severity, detected_at, source, supersedes_item_id=None):
    item = new_record()
    item.update(
        {
            "offering_id": offering_id,
            "supersedes_item_id": supersedes_item_id,
            "control_id": control_id,
            "severity": severity,
            "source": source,
            "detected_at": detected_at,
            "anchor_at": detected_at,
            "granted_extension_days": 0,
            "remediation_status": "OPEN",
            "risk_disposition": "NONE",
            "closure_reason": None,
            "reopen_count": 0,
        }
    )
    calc.recompute_deadline(item)
    db.poam_items[item["id"]] = item
    return item


# ---------------------------------------------------------------------------
# Monitoring period creation
# ---------------------------------------------------------------------------


def create_monitoring_period(authorization, period_month):
    window_start, window_end, scan_due_at = calc.month_bounds(period_month)
    period = new_record()
    period.update(
        {
            "authorization_id": authorization["id"],
            "period_month": period_month,
            "window_start": window_start,
            "window_end": window_end,
            "scan_due_at": scan_due_at,
            "status": "OPEN",
            "accepted_submission_count": 0,
            "late_submission_count": 0,
            "rejected_submission_count": 0,
            "covered_scan_types": [],
            "closed_at": None,
        }
    )
    db.monitoring_periods[period["id"]] = period
    return period


# ---------------------------------------------------------------------------
# Authorization decision cascade (PRD §3.7, four links)
# ---------------------------------------------------------------------------


def authorize_package(package, offering):
    agency = db.agencies.get(offering.get("sponsor_agency_id"))
    suffix = agency["agency_code"] if (offering["authorization_path"] == "AGENCY_SPONSORED" and agency) else "BOARD"
    package["letter_reference"] = "AUTH-LTR-%d-%s" % (int(package["submission_round"]), suffix)

    authorized_at = now()
    authorization = new_record()
    authorization.update(
        {
            "offering_id": offering["id"],
            "package_id": package["id"],
            "authorization_path": package["authorization_path"],
            "impact_level": offering.get("final_impact_level"),
            "authorized_at": authorized_at,
            "expires_at": make_instant(authorized_at + timedelta(days=1095)),
            "letter_reference": package["letter_reference"],
            "authorization_status": "AUTHORIZED",
            "monitoring_posture": "ACTIVE",
            "consecutive_deficient_periods": 0,
            "residual_risk_score": Decimal("0.00"),
            "poam_risk_tier": "NONE",
            "total_findings_count": 0,
            "open_findings_count": 0,
            "closed_findings_count": 0,
            "risk_accepted_findings_count": 0,
            "reuse_seats_total": 5,
            "reuse_seats_granted": 0,
            "reuse_seats_available": 5,
        }
    )
    sync_authorization_findings(authorization)
    sync_authorization_seats(authorization)
    db.authorizations[authorization["id"]] = authorization

    # link 2: the offering follows the authorization row into AUTHORIZED
    offering["status"] = "AUTHORIZED"

    # link 3: first monitoring period for the month containing authorized_at
    create_monitoring_period(authorization, calc.month_string(authorized_at))

    # link 4: re-anchor the offering's open ASSESSMENT findings
    for item in calc.findings_of(offering["id"]):
        if item["source"] != "ASSESSMENT":
            continue
        if item["remediation_status"] == "CLOSED":
            continue
        if item["detected_at"] >= authorized_at:
            continue
        item["anchor_at"] = authorized_at
        calc.recompute_deadline(item)
        touch(item)

    return authorization


# ---------------------------------------------------------------------------
# Reuse notices and revocation cascades
# ---------------------------------------------------------------------------


def issue_reuse_notices(authorization):
    for grant in grants_of_authorization(authorization["id"]):
        if grant["access_state"] not in NOTICE_SOURCE_STATES:
            continue
        grant["access_state"] = "NOTICE_ISSUED"
        grant["notice_count"] = int(grant["notice_count"]) + 1
        touch(grant)
        agency = db.agencies.get(grant["agency_id"])
        if agency is not None:
            sync_agency(agency)
            touch(agency)


def revoke_all_grants(authorization, reason):
    for grant in grants_of_authorization(authorization["id"]):
        if grant["access_state"] == "REVOKED":
            continue
        grant["access_state"] = "REVOKED"
        grant["revoked_reason"] = reason
        touch(grant)
        agency = db.agencies.get(grant["agency_id"])
        if agency is not None:
            sync_agency(agency)
            touch(agency)
    sync_authorization_seats(authorization)


# ---------------------------------------------------------------------------
# Monitoring period close cascade (PRD §3.8)
# ---------------------------------------------------------------------------


def close_monitoring_period(period):
    authorization = db.authorizations[period["authorization_id"]]
    offering = offering_of_authorization(authorization)
    clock = now()

    sync_period_counters(period)
    covered = set(period["covered_scan_types"])
    compliant = (
        set(calc.REQUIRED_SCAN_TYPES).issubset(covered)
        and int(period["rejected_submission_count"]) == 0
        and not _has_overdue_high(offering["id"], period["window_end"])
    )

    period["status"] = "CLOSED_COMPLIANT" if compliant else "CLOSED_DEFICIENT"
    period["closed_at"] = clock
    touch(period)

    if compliant:
        authorization["consecutive_deficient_periods"] = 0
        if authorization["monitoring_posture"] == "AT_RISK":
            authorization["monitoring_posture"] = "ACTIVE"
        if authorization["authorization_status"] == "SUSPENDED":
            authorization["authorization_status"] = "AUTHORIZED"
            if offering is not None and offering["status"] == "SUSPENDED":
                offering["status"] = "AUTHORIZED"
                touch(offering)
    else:
        run = int(authorization["consecutive_deficient_periods"]) + 1
        authorization["consecutive_deficient_periods"] = run
        if run == 1:
            if authorization["monitoring_posture"] == "ACTIVE":
                authorization["monitoring_posture"] = "AT_RISK"
                issue_reuse_notices(authorization)
        else:
            if authorization["monitoring_posture"] in ("ACTIVE", "AT_RISK"):
                authorization["monitoring_posture"] = "ESCALATED"
                issue_reuse_notices(authorization)
            if run == 2:
                if authorization["authorization_status"] == "AUTHORIZED":
                    authorization["authorization_status"] = "SUSPENDED"
                    if offering is not None and offering["status"] == "AUTHORIZED":
                        offering["status"] = "SUSPENDED"
                        touch(offering)
            else:
                if authorization["authorization_status"] in ("AUTHORIZED", "SUSPENDED"):
                    authorization["authorization_status"] = "REVOKED"
                    revoke_all_grants(authorization, "AUTHORIZATION_REVOKED")

    # expiry is applied independently of the compliance verdict
    if clock >= authorization["expires_at"] and authorization["authorization_status"] in (
        "AUTHORIZED",
        "SUSPENDED",
    ):
        authorization["authorization_status"] = "EXPIRED"

    sync_authorization_findings(authorization)
    sync_authorization_seats(authorization)
    touch(authorization)

    if authorization["authorization_status"] in ("AUTHORIZED", "SUSPENDED"):
        nxt = calc.next_month_string(period["period_month"])
        if not any(p["period_month"] == nxt for p in periods_of(authorization["id"])):
            create_monitoring_period(authorization, nxt)

    return period


def _has_overdue_high(offering_id, as_of):
    for item in calc.findings_of(offering_id):
        if item["severity"] != "HIGH":
            continue
        if item["remediation_status"] == "CLOSED":
            continue
        if item["deadline_at"] <= as_of:
            return True
    return False


# ---------------------------------------------------------------------------
# Ownership helpers (validation tier 8)
# ---------------------------------------------------------------------------


def require_offering_owner(offering, user_id):
    if offering.get("owner_user_id") != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting user does not own this offering.")


def require_engagement_assessor(engagement, user_id):
    if engagement.get("assessor_user_id") != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting user is not this engagement's assessor.")
