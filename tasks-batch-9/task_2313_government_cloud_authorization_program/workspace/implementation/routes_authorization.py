"""Packages, authorizations, continuous monitoring, significant changes, agency reuse."""
from decimal import Decimal

from flask import Blueprint

import calc
import services as svc
from core import (
    AGENCY_OFFICIAL,
    ANY_ROLE,
    BOARD,
    LEAD,
    PERIOD_MONTH_RE,
    authenticate,
    body,
    created,
    db,
    fail,
    iso,
    listing,
    lookup,
    make_instant,
    new_record,
    now,
    ok,
    opt_int,
    opt_str,
    pagination,
    paginate,
    parse_instant,
    query_enum,
    query_str,
    req_enum,
    req_instant,
    req_int,
    req_str,
    req_str_array,
    rows,
    touch,
    uid,
)

bp = Blueprint("authorization", __name__)

PACKAGE_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "REVISION_REQUESTED",
    "AUTHORIZED",
    "REJECTED",
    "SUPERSEDED",
)
AUTHORIZATION_STATUSES = ("AUTHORIZED", "SUSPENDED", "REVOKED", "EXPIRED")
POSTURES = ("ACTIVE", "AT_RISK", "ESCALATED")
PERIOD_STATUSES = ("OPEN", "CLOSED_COMPLIANT", "CLOSED_DEFICIENT")
SUBMISSION_STATUSES = ("ACCEPTED", "LATE_ACCEPTED", "REJECTED")
CHANGE_KINDS = ("BOUNDARY_CHANGE", "NEW_SERVICE", "TECH_REFRESH")
CHANGE_STATUSES = ("SUBMITTED", "APPROVED", "DENIED")
ACCESS_STATES = (
    "REQUESTED",
    "PACKAGE_ACCESS_GRANTED",
    "INCREMENTAL_REVIEW",
    "REUSE_ACCEPTED",
    "NOTICE_ISSUED",
    "REVOKED",
)
REVOKE_REASONS = ("AGENCY_REQUEST", "POSTURE_ESCALATION", "AUTHORIZATION_REVOKED")
PACKAGE_READ_STATES = (
    "PACKAGE_ACCESS_GRANTED",
    "INCREMENTAL_REVIEW",
    "REUSE_ACCEPTED",
    "NOTICE_ISSUED",
)
MIN_CRM_COVERAGE = Decimal("90.00")
MAX_SUBMISSION_RISK = Decimal("50.00")
MAX_INCREMENTAL_FINDINGS = 5


def _require_path_queue(authorization_path, actor_role):
    """Validation tier 4."""
    if authorization_path == "PROGRAM_BOARD" and actor_role != BOARD:
        fail("ERR_WRONG_REVIEW_QUEUE", "This decision belongs to a ProgramBoardReviewer.")
    if authorization_path == "AGENCY_SPONSORED" and actor_role != AGENCY_OFFICIAL:
        fail("ERR_WRONG_REVIEW_QUEUE", "This decision belongs to the sponsoring agency official.")


def _require_sponsor(offering, actor_role):
    """Validation tier 34."""
    if actor_role != AGENCY_OFFICIAL:
        return
    if offering is None or offering.get("sponsor_agency_id") != uid():
        fail("ERR_SPONSOR_AGENCY_MISMATCH", "The acting official is not the offering's sponsor.")


def _require_active_authorization(authorization):
    """Validation tier 14."""
    if (
        authorization["authorization_status"] != "AUTHORIZED"
        or authorization["monitoring_posture"] == "ESCALATED"
    ):
        fail("ERR_AUTHORIZATION_NOT_ACTIVE", "The authorization is not active for this operation.")


# ---------------------------------------------------------------------------
# Authorization packages
# ---------------------------------------------------------------------------


@bp.post("/authorization-packages")
def create_package():
    authenticate((LEAD,))
    b = body()
    offering_id = req_str(b, "offering_id")
    engagement_id = req_str(b, "engagement_id")
    expected_version = req_int(b, "expected_offering_version", minimum=0)
    offering = lookup("offerings", offering_id)
    engagement = lookup("engagements", engagement_id)
    svc.require_offering_owner(offering, uid())
    if int(offering["version"]) != expected_version:
        fail("ERR_STALE_OFFERING_VERSION", "The offering has been modified since it was read.")
    existing = svc.packages_of(offering["id"])
    if len(existing) >= 3:
        fail("ERR_REVISION_LIMIT_EXCEEDED", "The offering already holds three authorization packages.")
    if engagement["offering_id"] != offering["id"]:
        fail("ERR_ENGAGEMENT_OFFERING_MISMATCH", "The engagement belongs to another offering.")
    for prior in existing:
        if prior["status"] in ("DRAFT", "REVISION_REQUESTED"):
            prior["status"] = "SUPERSEDED"
            touch(prior)
    rec = new_record()
    rec.update(
        {
            "offering_id": offering["id"],
            "engagement_id": engagement["id"],
            "authorization_path": offering.get("authorization_path"),
            "status": "DRAFT",
            "submission_round": 0,
            "submitted_at": None,
            "crm_coverage_pct": None,
            "residual_risk_score_at_submission": None,
            "open_findings_at_submission": None,
            "reviewed_by_user_id": None,
            "revision_note": None,
            "letter_reference": None,
        }
    )
    db.packages[rec["id"]] = rec
    svc.sync_offering_packages(offering)
    touch(offering)
    return created(rec)


@bp.post("/authorization-packages/<ident>/submit")
def submit_package(ident):
    authenticate((LEAD,))
    body()
    package = lookup("packages", ident)
    offering = db.offerings.get(package["offering_id"])
    engagement = db.engagements.get(package["engagement_id"])
    if offering is not None:
        svc.require_offering_owner(offering, uid())
    if package["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        fail("ERR_INVALID_STATE", "Only a DRAFT or REVISION_REQUESTED package may be submitted.")
    if offering is None or offering["status"] not in ("IN_ASSESSMENT", "PACKAGE_SUBMITTED"):
        fail("ERR_INVALID_STATE", "The offering is not in a submittable state.")
    if engagement is None or engagement["status"] != "REPORT_DELIVERED":
        fail(
            "ERR_ENGAGEMENT_REPORT_NOT_DELIVERED",
            "The backing engagement has not delivered its report.",
        )
    coverage = calc.crm_coverage(offering)["overall_coverage_pct"]
    if coverage < MIN_CRM_COVERAGE:
        fail("ERR_CRM_COVERAGE_INSUFFICIENT", "CRM coverage must be at least 90.00 percent.")
    submitted_at = now()
    risk = calc.residual_risk(offering["id"], variant="at_submission", as_of=submitted_at)
    if risk >= MAX_SUBMISSION_RISK:
        fail("ERR_RESIDUAL_RISK_TOO_HIGH", "Submission-time residual risk must be below 50.00.")
    if calc.overdue_high_count(offering["id"], submitted_at) > 0:
        fail("ERR_OVERDUE_HIGH_FINDINGS", "An open HIGH finding is at or past its deadline.")
    if engagement["total_cost_usd"] > offering["assessment_budget_usd"]:
        fail(
            "ERR_ASSESSMENT_BUDGET_EXCEEDED",
            "The engagement cost exceeds the offering's assessment budget.",
        )
    open_findings = sum(
        1 for i in calc.findings_of(offering["id"]) if i["remediation_status"] != "CLOSED"
    )
    package["status"] = "SUBMITTED"
    package["revision_note"] = None
    package["submitted_at"] = submitted_at
    package["submission_round"] = int(package["submission_round"]) + 1
    package["crm_coverage_pct"] = coverage
    package["residual_risk_score_at_submission"] = risk
    package["open_findings_at_submission"] = open_findings
    touch(package)
    offering["status"] = "PACKAGE_SUBMITTED"
    svc.sync_offering_packages(offering)
    touch(offering)
    return ok(package)


@bp.post("/authorization-packages/<ident>/review")
def review_package(ident):
    authenticate((BOARD,))
    body()
    package = lookup("packages", ident)
    if package["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED package may be taken into review.")
    package["status"] = "UNDER_REVIEW"
    package["reviewed_by_user_id"] = uid()
    touch(package)
    return ok(package)


@bp.post("/authorization-packages/<ident>/revision-request")
def revision_request(ident):
    authenticate((BOARD,))
    b = body()
    note = req_str(b, "revision_note")
    package = lookup("packages", ident)
    if package["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW package may be sent back for revision.")
    package["revision_note"] = note
    if int(package["submission_round"]) >= 3:
        package["status"] = "REJECTED"
        touch(package)
        engagement = db.engagements.get(package["engagement_id"])
        if engagement is not None:
            svc.void_engagement(engagement)
        offering = db.offerings.get(package["offering_id"])
        if offering is not None:
            svc.sync_offering_packages(offering)
            touch(offering)
    else:
        package["status"] = "REVISION_REQUESTED"
        touch(package)
    return ok(package)


@bp.post("/authorization-packages/<ident>/decision")
def decide_package(ident):
    actor_role = authenticate((BOARD, AGENCY_OFFICIAL))[1]
    package = db.packages.get(ident)
    offering = db.offerings.get(package["offering_id"]) if package else None
    if package is not None:
        _require_path_queue(package.get("authorization_path"), actor_role)
    b = body()
    decision = req_enum(b, "decision", ("AUTHORIZE", "REJECT"))
    opt_str(b, "risk_acceptance_note", None)
    if package is None:
        fail("ERR_PACKAGE_NOT_FOUND")
    if package["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW package may be decided.")
    if actor_role == BOARD and uid() == package.get("reviewed_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES", "The reviewer of a package may not decide it.")
    _require_sponsor(offering, actor_role)
    if decision == "AUTHORIZE":
        package["status"] = "AUTHORIZED"
        svc.authorize_package(package, offering)
    else:
        package["status"] = "REJECTED"
    touch(package)
    if offering is not None:
        svc.sync_offering_packages(offering)
        touch(offering)
    return ok(package)


@bp.get("/authorization-packages/<ident>")
def read_package(ident):
    actor_role = authenticate(ANY_ROLE)[1]
    package = lookup("packages", ident)
    if actor_role == AGENCY_OFFICIAL:
        offering = db.offerings.get(package["offering_id"])
        allowed = offering is not None and offering.get("sponsor_agency_id") == uid()
        if not allowed:
            auth_ids = {
                a["id"] for a in rows("authorizations") if a["offering_id"] == package["offering_id"]
            }
            for grant in svc.grants_of_agency(uid()):
                if grant["authorization_id"] in auth_ids and grant["access_state"] in PACKAGE_READ_STATES:
                    allowed = True
                    break
        if not allowed:
            fail("ERR_PACKAGE_ACCESS_DENIED", "The acting agency may not read this package.")
    return ok(package)


@bp.get("/authorization-packages")
def list_packages():
    authenticate(ANY_ROLE)
    offering_id = query_str("offering_id")
    engagement_id = query_str("engagement_id")
    status = query_enum("status", PACKAGE_STATUSES)
    limit, offset = pagination()
    result = rows("packages")
    if offering_id is not None:
        result = [p for p in result if p["offering_id"] == offering_id]
    if engagement_id is not None:
        result = [p for p in result if p["engagement_id"] == engagement_id]
    if status is not None:
        result = [p for p in result if p["status"] == status]
    page, total = paginate(result, limit, offset)
    return listing(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Authorizations
# ---------------------------------------------------------------------------


@bp.get("/authorizations/<ident>")
def read_authorization(ident):
    authenticate(ANY_ROLE)
    return ok(lookup("authorizations", ident))


@bp.get("/authorizations")
def list_authorizations():
    authenticate(ANY_ROLE)
    offering_id = query_str("offering_id")
    package_id = query_str("package_id")
    status = query_enum("authorization_status", AUTHORIZATION_STATUSES)
    posture = query_enum("monitoring_posture", POSTURES)
    limit, offset = pagination()
    result = rows("authorizations")
    if offering_id is not None:
        result = [a for a in result if a["offering_id"] == offering_id]
    if package_id is not None:
        result = [a for a in result if a["package_id"] == package_id]
    if status is not None:
        result = [a for a in result if a["authorization_status"] == status]
    if posture is not None:
        result = [a for a in result if a["monitoring_posture"] == posture]
    page, total = paginate(result, limit, offset)
    return listing(page, limit, offset, total)


@bp.get("/authorizations/<ident>/risk-summary")
def risk_summary(ident):
    authenticate(ANY_ROLE)
    authorization = lookup("authorizations", ident)
    offering_id = authorization["offering_id"]
    evaluated_at = now()
    live = calc.residual_risk(offering_id, as_of=evaluated_at)
    open_findings = sum(
        1 for i in calc.findings_of(offering_id) if i["remediation_status"] != "CLOSED"
    )
    return ok(
        {
            "residual_risk_score": live,
            "poam_risk_tier": calc.risk_tier(live),
            "stored_residual_risk_score": authorization["residual_risk_score"],
            "open_findings_count": open_findings,
            "overdue_high_count": calc.overdue_high_count(offering_id, evaluated_at),
            "evaluated_at": evaluated_at,
        }
    )


# ---------------------------------------------------------------------------
# Monitoring periods
# ---------------------------------------------------------------------------


@bp.post("/authorizations/<ident>/monitoring-periods")
def create_monitoring_period(ident):
    authenticate((LEAD, BOARD))
    b = body()
    period_month = req_str(b, "period_month")
    if not PERIOD_MONTH_RE.match(period_month):
        fail("ERR_INVALID_REQUEST", "Field 'period_month' must match YYYY-MM.")
    authorization = lookup("authorizations", ident)
    _require_active_authorization(authorization)
    for existing in svc.periods_of(authorization["id"]):
        if existing["period_month"] == period_month:
            fail(
                "ERR_DUPLICATE_MONITORING_PERIOD",
                "A monitoring period already exists for that month.",
            )
    period = svc.create_monitoring_period(authorization, period_month)
    return created(period)


@bp.get("/authorizations/<ident>/monitoring-periods")
def list_monitoring_periods(ident):
    authenticate(ANY_ROLE)
    status = query_enum("status", PERIOD_STATUSES)
    limit, offset = pagination()
    authorization = lookup("authorizations", ident)
    result = svc.periods_of(authorization["id"])
    if status is not None:
        result = [p for p in result if p["status"] == status]
    page, total = paginate(result, limit, offset)
    return listing(page, limit, offset, total)


@bp.get("/monitoring-periods/<ident>")
def read_monitoring_period(ident):
    authenticate(ANY_ROLE)
    return ok(lookup("monitoring_periods", ident))


@bp.post("/monitoring-periods/<ident>/scan-submissions")
def create_scan_submission(ident):
    authenticate((LEAD,))
    b = body()
    scan_types = req_str_array(b, "scan_types", allowed=calc.SCAN_TYPES)
    period = lookup("monitoring_periods", ident)
    authorization = db.authorizations.get(period["authorization_id"])
    offering = svc.offering_of_authorization(authorization) if authorization else None
    if offering is not None:
        svc.require_offering_owner(offering, uid())
    missing = [t for t in calc.REQUIRED_SCAN_TYPES if t not in scan_types]
    if missing:
        fail("ERR_INCOMPLETE_SCAN_SET", "scan_types must include %s." % ", ".join(missing))
    submitted_at = now()
    if submitted_at < period["window_start"]:
        fail("ERR_SCAN_WINDOW_NOT_OPEN", "The monitoring period has not begun.")
    days_late, status = calc.timeliness(submitted_at, period["scan_due_at"])
    rec = new_record(audit=False)
    rec.update(
        {
            "monitoring_period_id": period["id"],
            "scan_types": scan_types,
            "submitted_at": submitted_at,
            "days_late": days_late,
            "status": status,
            "submitted_by_user_id": uid(),
        }
    )
    db.scan_submissions[rec["id"]] = rec
    svc.sync_period_counters(period)
    touch(period)
    return created(rec)


@bp.get("/monitoring-periods/<ident>/scan-submissions")
def list_scan_submissions(ident):
    authenticate(ANY_ROLE)
    status = query_enum("status", SUBMISSION_STATUSES)
    limit, offset = pagination()
    period = lookup("monitoring_periods", ident)
    result = svc.submissions_of(period["id"])
    if status is not None:
        result = [s for s in result if s["status"] == status]
    page, total = paginate(result, limit, offset)
    return listing(page, limit, offset, total)


@bp.post("/monitoring-periods/<ident>/close")
def close_period(ident):
    authenticate((BOARD, AGENCY_OFFICIAL))
    body()
    period = lookup("monitoring_periods", ident)
    if period["status"] != "OPEN":
        fail("ERR_ALREADY_TERMINAL", "The monitoring period is already closed.")
    if now() < period["window_end"]:
        fail("ERR_PERIOD_NOT_ENDED", "The monitoring period has not ended yet.")
    svc.close_monitoring_period(period)
    return ok(period)


# ---------------------------------------------------------------------------
# Significant change requests
# ---------------------------------------------------------------------------


@bp.post("/significant-change-requests")
def create_change_request():
    authenticate((LEAD,))
    b = body()
    offering_id = req_str(b, "offering_id")
    change_kind = req_enum(b, "change_kind", CHANGE_KINDS)
    description = req_str(b, "description")
    window_start = req_instant(b, "window_start")
    window_end = req_instant(b, "window_end")
    added = opt_int(b, "added_service_count", 0, minimum=0)
    offering = lookup("offerings", offering_id)
    svc.require_offering_owner(offering, uid())
    if offering["status"] != "AUTHORIZED":
        fail("ERR_INVALID_STATE", "A change request requires the offering to be AUTHORIZED.")
    if not window_start < window_end:
        fail("ERR_WINDOW_INVALID", "window_start must be strictly before window_end.")
    for other in rows("change_requests"):
        if other["offering_id"] != offering["id"]:
            continue
        if other["status"] not in ("SUBMITTED", "APPROVED"):
            continue
        if not calc.change_windows_separated(
            window_start, window_end, other["window_start"], other["window_end"]
        ):
            fail(
                "ERR_CHANGE_WINDOW_BUFFER_VIOLATION",
                "The window is within seven days of another change window.",
            )
    rec = new_record()
    rec.update(
        {
            "offering_id": offering["id"],
            "change_kind": change_kind,
            "description": description,
            "window_start": window_start,
            "window_end": window_end,
            "added_service_count": added,
            "requires_reassessment": change_kind == "BOUNDARY_CHANGE" or added >= 3,
            "status": "SUBMITTED",
            "decided_by_user_id": None,
        }
    )
    db.change_requests[rec["id"]] = rec
    offering["status"] = "CHANGE_UNDER_REVIEW"
    touch(offering)
    return created(rec)


@bp.post("/significant-change-requests/<ident>/decision")
def decide_change_request(ident):
    actor_role = authenticate((BOARD, AGENCY_OFFICIAL))[1]
    change = db.change_requests.get(ident)
    offering = db.offerings.get(change["offering_id"]) if change else None
    if change is not None and offering is not None:
        _require_path_queue(offering.get("authorization_path"), actor_role)
    b = body()
    decision = req_enum(b, "decision", ("APPROVE", "DENY"))
    if change is None:
        fail("ERR_CHANGE_REQUEST_NOT_FOUND")
    if change["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED change request may be decided.")
    _require_sponsor(offering, actor_role)
    change["decided_by_user_id"] = uid()
    change["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    touch(change)
    if offering is not None:
        if decision == "APPROVE":
            if change["change_kind"] in ("BOUNDARY_CHANGE", "NEW_SERVICE"):
                offering["boundary_version"] = int(offering["boundary_version"]) + 1
            if change["change_kind"] == "NEW_SERVICE":
                offering["included_service_count"] = int(offering["included_service_count"]) + int(
                    change["added_service_count"]
                )
        outstanding = any(
            c["offering_id"] == offering["id"] and c["status"] == "SUBMITTED"
            for c in rows("change_requests")
        )
        if not outstanding and offering["status"] == "CHANGE_UNDER_REVIEW":
            offering["status"] = "AUTHORIZED"
        touch(offering)
    return ok(change)


@bp.get("/significant-change-requests/<ident>")
def read_change_request(ident):
    authenticate(ANY_ROLE)
    return ok(lookup("change_requests", ident))


@bp.get("/significant-change-requests")
def list_change_requests():
    authenticate(ANY_ROLE)
    offering_id = query_str("offering_id")
    status = query_enum("status", CHANGE_STATUSES)
    change_kind = query_enum("change_kind", CHANGE_KINDS)
    limit, offset = pagination()
    result = rows("change_requests")
    if offering_id is not None:
        result = [c for c in result if c["offering_id"] == offering_id]
    if status is not None:
        result = [c for c in result if c["status"] == status]
    if change_kind is not None:
        result = [c for c in result if c["change_kind"] == change_kind]
    page, total = paginate(result, limit, offset)
    return listing(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Reuse grants
# ---------------------------------------------------------------------------


@bp.post("/reuse-grants")
def create_reuse_grant():
    authenticate((AGENCY_OFFICIAL,))
    b = body()
    authorization_id = req_str(b, "authorization_id")
    agency_id = req_str(b, "agency_id")
    expected_version = req_int(b, "expected_authorization_version", minimum=0)
    authorization = lookup("authorizations", authorization_id)
    agency = lookup("agencies", agency_id)
    if agency["id"] != uid():
        fail("ERR_NOT_RESOURCE_OWNER", "An official may only request reuse for their own agency.")
    if int(authorization["version"]) != expected_version:
        fail(
            "ERR_STALE_AUTHORIZATION_VERSION",
            "The authorization has been modified since it was read.",
        )
    _require_active_authorization(authorization)
    for grant in svc.grants_of_authorization(authorization["id"]):
        if grant["agency_id"] == agency["id"] and grant["access_state"] != "REVOKED":
            fail("ERR_DUPLICATE_REUSE_GRANT", "This agency already holds a live grant.")
    if int(authorization["reuse_seats_available"]) <= 0:
        fail("ERR_REUSE_SEATS_EXHAUSTED", "The authorization has no reuse seat available.")
    rec = new_record()
    rec.update(
        {
            "authorization_id": authorization["id"],
            "agency_id": agency["id"],
            "access_state": "REQUESTED",
            "incremental_review_findings_count": 0,
            "reuse_accepted_at": None,
            "notice_count": 0,
            "revoked_reason": None,
        }
    )
    db.reuse_grants[rec["id"]] = rec
    svc.sync_agency(agency)
    touch(agency)
    svc.sync_authorization_seats(authorization)
    touch(authorization)
    return created(rec)


@bp.post("/reuse-grants/<ident>/package-access")
def grant_package_access(ident):
    authenticate((LEAD,))
    body()
    grant = lookup("reuse_grants", ident)
    authorization = db.authorizations.get(grant["authorization_id"])
    offering = svc.offering_of_authorization(authorization) if authorization else None
    if offering is not None:
        svc.require_offering_owner(offering, uid())
    if grant["access_state"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "Only a REQUESTED grant may be given package access.")
    grant["access_state"] = "PACKAGE_ACCESS_GRANTED"
    touch(grant)
    return ok(grant)


@bp.post("/reuse-grants/<ident>/incremental-review")
def incremental_review(ident):
    authenticate((AGENCY_OFFICIAL,))
    b = body()
    decision = req_enum(b, "decision", ("MORE_INFO", "ACCEPT"))
    findings_count = req_int(b, "findings_count", minimum=0)
    grant = lookup("reuse_grants", ident)
    if grant["agency_id"] != uid():
        fail("ERR_NOT_RESOURCE_OWNER", "The grant belongs to another agency.")
    state = grant["access_state"]
    if decision == "MORE_INFO":
        if state not in ("PACKAGE_ACCESS_GRANTED", "INCREMENTAL_REVIEW"):
            fail("ERR_INVALID_STATE", "MORE_INFO is not legal from the current access state.")
    else:
        if state not in ("PACKAGE_ACCESS_GRANTED", "INCREMENTAL_REVIEW", "NOTICE_ISSUED"):
            fail("ERR_INVALID_STATE", "ACCEPT is not legal from the current access state.")
    authorization = db.authorizations.get(grant["authorization_id"])
    if decision == "ACCEPT":
        if authorization is None or authorization["authorization_status"] != "AUTHORIZED":
            fail("ERR_AUTHORIZATION_NOT_ACTIVE", "The authorization is no longer AUTHORIZED.")
        if findings_count > MAX_INCREMENTAL_FINDINGS:
            fail(
                "ERR_INCREMENTAL_FINDINGS_EXCEED_TOLERANCE",
                "An acceptance tolerates at most 5 incremental findings.",
            )
    grant["incremental_review_findings_count"] = findings_count
    if decision == "MORE_INFO":
        grant["access_state"] = "INCREMENTAL_REVIEW"
        touch(grant)
    else:
        previous = state
        grant["access_state"] = "REUSE_ACCEPTED"
        grant["reuse_accepted_at"] = now()
        touch(grant)
        if previous == "NOTICE_ISSUED":
            agency = db.agencies.get(grant["agency_id"])
            if agency is not None:
                svc.sync_agency(agency)
                touch(agency)
    return ok(grant)


@bp.post("/reuse-grants/<ident>/revoke")
def revoke_reuse_grant(ident):
    actor_role = authenticate((AGENCY_OFFICIAL, BOARD))[1]
    b = body()
    reason = req_enum(b, "reason", REVOKE_REASONS)
    grant = lookup("reuse_grants", ident)
    if actor_role == AGENCY_OFFICIAL and grant["agency_id"] != uid():
        fail("ERR_NOT_RESOURCE_OWNER", "The grant belongs to another agency.")
    if grant["access_state"] == "REVOKED":
        fail("ERR_ALREADY_TERMINAL", "The reuse grant is already revoked.")
    grant["access_state"] = "REVOKED"
    grant["revoked_reason"] = reason
    touch(grant)
    agency = db.agencies.get(grant["agency_id"])
    if agency is not None:
        svc.sync_agency(agency)
        touch(agency)
    authorization = db.authorizations.get(grant["authorization_id"])
    if authorization is not None:
        svc.sync_authorization_seats(authorization)
        touch(authorization)
    return ok(grant)


@bp.get("/reuse-grants/<ident>")
def read_reuse_grant(ident):
    authenticate(ANY_ROLE)
    return ok(lookup("reuse_grants", ident))


@bp.get("/reuse-grants")
def list_reuse_grants():
    authenticate(ANY_ROLE)
    authorization_id = query_str("authorization_id")
    agency_id = query_str("agency_id")
    access_state = query_enum("access_state", ACCESS_STATES)
    limit, offset = pagination()
    result = rows("reuse_grants")
    if authorization_id is not None:
        result = [g for g in result if g["authorization_id"] == authorization_id]
    if agency_id is not None:
        result = [g for g in result if g["agency_id"] == agency_id]
    if access_state is not None:
        result = [g for g in result if g["access_state"] == access_state]
    page, total = paginate(result, limit, offset)
    return listing(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate((BOARD,))
    b = body()
    instant = req_instant(b, "to_iso8601")
    db.clock = make_instant(instant, instant.raw or iso(instant))
    return ok({"current_utc": db.clock})
