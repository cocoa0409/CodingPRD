"""Tag audit scan and tracker finding routes."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, new_id, now_iso, touch
from errors import ApiError
from response import ok, ok_list
from services.consent import (
    PURPOSE_CATEGORIES,
    parse_dt,
    check_role,
    check_read_role,
    current_user_id,
    pagination_args,
    sort_created,
)
from services.audit import recompute_vendor_risk, approved_vendors_of_property

bp = Blueprint("scans", __name__)
blueprint = bp

SCAN_COOLDOWN_MINUTES = 120


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _get_scan_or_404(scan_id):
    scan = store["tag_audit_scans"].get(scan_id)
    if scan is None:
        raise ApiError("ERR_SCAN_NOT_FOUND", "TagAuditScan not found", 404)
    return scan


def _get_finding_or_404(finding_id):
    finding = store["tracker_findings"].get(finding_id)
    if finding is None:
        raise ApiError("ERR_FINDING_NOT_FOUND", "TrackerFinding not found", 404)
    return finding


# ---------------------------------------------------------------------------
# POST /v1/tag-audit-scans — schedule (ComplianceAuditor)
# ---------------------------------------------------------------------------


@bp.post("/v1/tag-audit-scans")
def create_scan():
    check_role("ComplianceAuditor")
    body = _body()
    property_id = body.get("property_id")
    if not isinstance(property_id, str) or not property_id:
        raise ApiError("ERR_INVALID_REQUEST", "property_id is required", 400)
    scheduled_start_raw = body.get("scheduled_start")
    scheduled_start = parse_dt(scheduled_start_raw) if isinstance(scheduled_start_raw, str) else None
    if scheduled_start is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "scheduled_start must be an ISO8601 datetime", 400
        )
    duration = body.get("duration_minutes")
    if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", "duration_minutes must be an integer > 0", 400
        )
    if property_id not in store["properties"]:
        raise ApiError("ERR_PROPERTY_NOT_FOUND", "Property not found", 404)

    # cooldown rule: the new window expanded by 120 minutes on both sides must
    # not intersect any other scan's raw window; exact edge adjacency allowed
    buffer = timedelta(minutes=SCAN_COOLDOWN_MINUTES)
    new_start = scheduled_start
    new_end = scheduled_start + timedelta(minutes=duration)
    for other in store["tag_audit_scans"].values():
        if other.get("property_id") != property_id:
            continue
        other_start = parse_dt(other.get("scheduled_start"))
        if other_start is None:
            continue
        other_end = other_start + timedelta(minutes=int(other.get("duration_minutes", 0)))
        if (new_start - buffer) < other_end and (new_end + buffer) > other_start:
            raise ApiError(
                "ERR_SCAN_WINDOW_CONFLICT",
                "Scan window (with cooldown buffer) intersects an existing scan of the property",
                409,
            )

    now = now_iso()
    scan = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "property_id": property_id,
        "scheduled_start": scheduled_start_raw,
        "duration_minutes": duration,
        "status": "SCHEDULED",
        "created_by_user_id": current_user_id(),
        "findings_created_count": 0,
        "unauthorized_findings_count": 0,
    }
    store["tag_audit_scans"][scan["id"]] = scan
    return ok(scan, status=201)


# ---------------------------------------------------------------------------
# Scan reads
# ---------------------------------------------------------------------------


@bp.get("/v1/tag-audit-scans")
def list_scans():
    check_read_role()
    limit, offset = pagination_args()
    items = list(store["tag_audit_scans"].values())
    property_id = request.args.get("property_id")
    if property_id is not None:
        items = [s for s in items if s.get("property_id") == property_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s.get("status") == status]
    items = sort_created(items)
    total = len(items)
    return ok_list(items[offset : offset + limit], total, limit, offset)


@bp.get("/v1/tag-audit-scans/<scan_id>")
def get_scan(scan_id):
    check_read_role()
    return ok(_get_scan_or_404(scan_id))


# ---------------------------------------------------------------------------
# POST /v1/tag-audit-scans/{id}/run — execute detection (ComplianceAuditor)
# ---------------------------------------------------------------------------


@bp.post("/v1/tag-audit-scans/<scan_id>/run")
def run_scan(scan_id):
    check_role("ComplianceAuditor")
    scan = _get_scan_or_404(scan_id)
    if scan.get("status") != "SCHEDULED":
        raise ApiError(
            "ERR_SCAN_NOT_RUNNABLE", "Run requires the scan to be SCHEDULED", 409
        )
    body = _body()
    observed = body.get("observed_trackers")
    if not isinstance(observed, list):
        raise ApiError(
            "ERR_INVALID_REQUEST", "observed_trackers must be a list", 400
        )
    for item in observed:
        if not isinstance(item, dict):
            raise ApiError(
                "ERR_INVALID_REQUEST", "each observed tracker must be an object", 400
            )
        sig = item.get("tracker_signature")
        purpose = item.get("purpose_category")
        if not isinstance(sig, str) or not sig:
            raise ApiError(
                "ERR_INVALID_REQUEST", "tracker_signature must be a string", 400
            )
        if purpose not in PURPOSE_CATEGORIES:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "purpose_category must be one of NECESSARY, ANALYTICS, ADVERTISING, SALE_SHARE",
                400,
            )

    # dedupe by tracker_signature, first observation wins (order preserved)
    seen = set()
    distinct = []
    for item in observed:
        if item["tracker_signature"] in seen:
            continue
        seen.add(item["tracker_signature"])
        distinct.append(item)

    approved = approved_vendors_of_property(scan.get("property_id"))
    findings_created = 0
    unauthorized = 0
    affected_vendors = set()
    for item in distinct:
        signature = item["tracker_signature"]
        purpose = item["purpose_category"]
        matches = [v for v in approved if signature in (v.get("tracker_signatures") or [])]
        now = now_iso()
        if not matches:
            finding = {
                "id": new_id(),
                "created_at": now,
                "updated_at": now,
                "version": 1,
                "scan_id": scan_id,
                "tracker_signature": signature,
                "violation_type": "UNAUTHORIZED_TRACKER",
                "severity": "HIGH",
                "vendor_id": None,
                "status": "OPEN",
                "remediated_by_user_id": None,
                "confirmed_by_user_id": None,
            }
            unauthorized += 1
        else:
            # match selector: earliest-created APPROVED vendor declaring the signature
            vendor = matches[0]
            if purpose in (vendor.get("declared_purposes") or []):
                continue  # fully conforming observation: no finding
            finding = {
                "id": new_id(),
                "created_at": now,
                "updated_at": now,
                "version": 1,
                "scan_id": scan_id,
                "tracker_signature": signature,
                "violation_type": "PURPOSE_MISMATCH",
                "severity": "MEDIUM",
                "vendor_id": vendor["id"],
                "status": "OPEN",
                "remediated_by_user_id": None,
                "confirmed_by_user_id": None,
            }
            affected_vendors.add(vendor["id"])
        store["tracker_findings"][finding["id"]] = finding
        findings_created += 1

    scan["status"] = "COMPLETED"
    scan["findings_created_count"] = findings_created
    scan["unauthorized_findings_count"] = unauthorized
    touch(scan)
    for vendor_id in affected_vendors:
        recompute_vendor_risk(vendor_id)
    return ok(scan)


# ---------------------------------------------------------------------------
# Finding reads
# ---------------------------------------------------------------------------


@bp.get("/v1/tag-audit-scans/<scan_id>/findings")
def list_scan_findings(scan_id):
    check_read_role()
    _get_scan_or_404(scan_id)
    limit, offset = pagination_args()
    items = [f for f in store["tracker_findings"].values() if f.get("scan_id") == scan_id]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f.get("status") == status]
    items = sort_created(items)
    total = len(items)
    return ok_list(items[offset : offset + limit], total, limit, offset)


@bp.get("/v1/vendors/<vendor_id>/tracker-findings")
def list_vendor_findings(vendor_id):
    check_read_role()
    if vendor_id not in store["vendors"]:
        raise ApiError("ERR_VENDOR_NOT_FOUND", "Vendor not found", 404)
    limit, offset = pagination_args()
    items = [
        f for f in store["tracker_findings"].values() if f.get("vendor_id") == vendor_id
    ]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f.get("status") == status]
    items = sort_created(items)
    total = len(items)
    return ok_list(items[offset : offset + limit], total, limit, offset)


# ---------------------------------------------------------------------------
# PUT /v1/tracker-findings/{id} — role-split adjudication
# ---------------------------------------------------------------------------

FINDING_STATUSES = {"OPEN", "REMEDIATED", "CONFIRMED_VIOLATION", "CLOSED"}


@bp.put("/v1/tracker-findings/<finding_id>")
def adjudicate_finding(finding_id):
    body = _body()
    new_status = body.get("status")
    if new_status not in FINDING_STATUSES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "status must be one of OPEN, REMEDIATED, CONFIRMED_VIOLATION, CLOSED",
            400,
        )
    # role split by payload: REMEDIATED is a VendorManager act;
    # CONFIRMED_VIOLATION / CLOSED are ComplianceAuditor acts
    if new_status == "REMEDIATED":
        check_role("VendorManager")
    elif new_status in ("CONFIRMED_VIOLATION", "CLOSED"):
        check_role("ComplianceAuditor")
    else:
        check_role("VendorManager", "ComplianceAuditor")
    finding = _get_finding_or_404(finding_id)
    current = finding.get("status")

    if new_status == "REMEDIATED":
        if current != "OPEN":
            raise ApiError(
                "ERR_FINDING_INVALID_STATE", "Remediate requires the finding to be OPEN", 409
            )
        finding["remediated_by_user_id"] = current_user_id()
    elif new_status == "CONFIRMED_VIOLATION":
        if current != "OPEN":
            raise ApiError(
                "ERR_FINDING_INVALID_STATE", "Confirm requires the finding to be OPEN", 409
            )
        # segregation of duties: the scan's creator may not confirm its findings
        scan = store["tag_audit_scans"].get(finding.get("scan_id"))
        if scan is not None and current_user_id() == scan.get("created_by_user_id"):
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
                "The auditor who created a scan may not confirm violations on it",
                403,
            )
        finding["confirmed_by_user_id"] = current_user_id()
    elif new_status == "CLOSED":
        if current not in ("REMEDIATED", "CONFIRMED_VIOLATION"):
            raise ApiError(
                "ERR_FINDING_INVALID_STATE",
                "Close requires the finding to be REMEDIATED or CONFIRMED_VIOLATION",
                409,
            )
    else:
        raise ApiError(
            "ERR_FINDING_INVALID_STATE", "Transition to %s is not permitted" % new_status, 409
        )

    finding["status"] = new_status
    touch(finding)
    recompute_vendor_risk(finding.get("vendor_id"))
    return ok(finding)
