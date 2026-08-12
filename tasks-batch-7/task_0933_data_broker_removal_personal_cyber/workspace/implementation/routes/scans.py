"""Scan runs, findings and the exposure inventory (PRD §3.4)."""

from flask import Blueprint, request

import cascades
import constants as K
import context
import derive
import envelope
import ledger
import rows
import serializers
import states
from clock import CLOCK, whole_days_between
from context import Ctx
from errors import ApiError
from store import DB, ordered

bp = Blueprint("scans", __name__)

ALL_READ_ROLES = [
    K.ROLE_PLATFORM_ADMIN,
    K.ROLE_PRIVACY_AGENT,
    K.ROLE_ACCOUNT_OWNER,
    K.ROLE_MEMBER,
    K.ROLE_AUDITOR,
]


def _profile_of(scan):
    return DB.profiles.get(scan["profile_id"])


def _account_of_scan(scan):
    return derive.account_of_profile(_profile_of(scan))


@bp.post("/scan-runs")
def queue_scan():
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT, K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    ctx.load_body()
    fields = ctx.validate(
        [
            {"name": "profile_id", "type": "string", "required": True},
            {"name": "kind", "type": "string", "required": True, "enum": K.SCAN_KINDS},
        ]
    )
    # Rung 11
    profile = DB.profiles.get(fields["profile_id"])
    if profile is None:
        raise ApiError("ERR_PROFILE_NOT_FOUND")
    member = DB.members.get(profile["member_id"])
    account = derive.account_of_profile(profile)
    # Rung 12
    ctx.own(account["id"], profile["member_id"])
    # Rungs 13-15
    ctx.write_gates(account)
    # Rung 16
    if member["authorization_status"] != "GRANTED":
        raise ApiError("ERR_AUTHORIZATION_REVOKED")
    # Rung 20
    if profile["status"] != "ACTIVE":
        raise ApiError("ERR_PROFILE_NOT_ACTIVE")
    last = profile["last_completed_scan_at"]
    # Rung 29 -- RECURRING interval, INCLUSIVE at 7 whole elapsed days.
    if fields["kind"] == "RECURRING" and last is not None:
        if whole_days_between(last, CLOCK.now) < K.RESCAN_MIN_INTERVAL_DAYS:
            raise ApiError("ERR_RESCAN_TOO_SOON")
    # Rung 30
    if fields["kind"] == "INITIAL" and last is not None:
        raise ApiError("ERR_INITIAL_SCAN_ALREADY_DONE")
    # Rung 44
    pools = derive.pool_figures(account["id"])
    if pools["scan"]["remaining"] < 1:
        raise ApiError("ERR_SCAN_QUOTA_EXCEEDED")

    scan = rows.new_row(
        "scans",
        {
            "profile_id": profile["id"],
            "kind": fields["kind"],
            "status": "QUEUED",
            "retry_count": 0,
            "started_at": None,
            "completed_at": None,
            "failure_reason": None,
            "entitlement_units_held": 1,
            "findings_count": 0,
            "reappearance_hit_count": 0,
        },
    )
    ledger.append(
        account_id=account["id"],
        member_id=profile["member_id"],
        resource_type="SCAN",
        entry_type="CONSUME",
        amount=1,
        reason_code="SCAN_QUEUED",
        source_reference=scan["id"],
    )
    return envelope.created(serializers.scan(scan))


@bp.get("/scan-runs")
def list_scans():
    ctx = Ctx(request, ALL_READ_ROLES)
    status = context.enum_filter(request, "status", K.SCAN_STATUSES)
    limit, offset = context.pagination(request)
    profile_id = context.plain_filter(request, "profile_id")
    # `kind` is NOT on rung 8's closed list.
    kind = context.plain_filter(request, "kind")
    result = []
    for scan in DB.scans.values():
        if profile_id is not None and scan["profile_id"] != profile_id:
            continue
        if status is not None and scan["status"] != status:
            continue
        if kind is not None and scan["kind"] != kind:
            continue
        if not _visible(ctx, scan):
            continue
        result.append(scan)
    page, total = context.window(ordered(result), limit, offset)
    return envelope.listing([serializers.scan(s) for s in page], limit, offset, total)


def _visible(ctx, scan):
    if not ctx.is_scoped_caller:
        return True
    profile = _profile_of(scan)
    if profile is None:
        return False
    account = derive.account_of_profile(profile)
    if account is None or account["id"] != ctx.caller_member["account_id"]:
        return False
    if ctx.is_non_primary_member and profile["member_id"] != ctx.caller_member["id"]:
        return False
    return True


@bp.get("/scan-runs/<scan_id>")
def read_scan(scan_id):
    ctx = Ctx(request, ALL_READ_ROLES)
    scan = ctx.path("scan", scan_id)
    profile = _profile_of(scan)
    ctx.own(derive.account_of_profile(profile)["id"], profile["member_id"])
    return envelope.ok(serializers.scan(scan))


@bp.post("/scan-runs/<scan_id>/start")
def start_scan(scan_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT])
    scan = ctx.path("scan", scan_id)
    ctx.write_gates(_account_of_scan(scan))
    # Rung 20 deliberately EXCLUDES this edge (PRD rung 20).
    states.gate("scan_status", scan["status"], ("QUEUED",))
    scan["status"] = "RUNNING"
    scan["started_at"] = CLOCK.now
    rows.touch(scan)
    return envelope.ok(serializers.scan(scan))


@bp.post("/scan-runs/<scan_id>/complete")
def complete_scan(scan_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT])
    scan = ctx.path("scan", scan_id)
    ctx.write_gates(_account_of_scan(scan))
    states.gate("scan_status", scan["status"], ("RUNNING",))
    scan["status"] = "COMPLETED"
    scan["completed_at"] = CLOCK.now
    profile = _profile_of(scan)
    # The single write the 7-day recurring interval is measured from.
    profile["last_completed_scan_at"] = CLOCK.now
    rows.touch(profile)
    # entitlement_units_held stays 1: completion never gives the unit back.
    rows.touch(scan)
    return envelope.ok(serializers.scan(scan))


@bp.post("/scan-runs/<scan_id>/fail")
def fail_scan(scan_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT])
    scan = ctx.path("scan", scan_id)
    ctx.load_body()
    fields = ctx.validate([{"name": "failure_reason", "type": "string", "required": True}])
    ctx.write_gates(_account_of_scan(scan))
    states.gate("scan_status", scan["status"], ("RUNNING",))
    scan["status"] = "FAILED"
    scan["failure_reason"] = fields["failure_reason"]
    rows.touch(scan)
    return envelope.ok(serializers.scan(scan))


@bp.post("/scan-runs/<scan_id>/retry")
def retry_scan(scan_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT])
    scan = ctx.path("scan", scan_id)
    ctx.write_gates(_account_of_scan(scan))
    states.gate("scan_status", scan["status"], ("FAILED",))
    profile = _profile_of(scan)
    # Rung 20 -- FAILED scans survive a pause, which makes this reachable.
    if profile["status"] != "ACTIVE":
        raise ApiError("ERR_PROFILE_NOT_ACTIVE")
    # Rung 34
    if scan["retry_count"] >= K.MAX_SCAN_RETRIES:
        raise ApiError("ERR_SCAN_RETRY_CAP_REACHED")
    scan["status"] = "QUEUED"
    scan["retry_count"] = scan["retry_count"] + 1
    scan["started_at"] = None
    rows.touch(scan)
    return envelope.ok(serializers.scan(scan))


@bp.post("/scan-runs/<scan_id>/cancel")
def cancel_scan(scan_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT, K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    scan = ctx.path("scan", scan_id)
    profile = _profile_of(scan)
    account = derive.account_of_profile(profile)
    ctx.own(account["id"], profile["member_id"])
    ctx.write_gates(account)
    states.gate("scan_status", scan["status"], ("QUEUED", "FAILED"))
    reason = "SCAN_CANCELLED" if scan["status"] == "QUEUED" else "SCAN_ABANDONED"
    cascades.cancel_scan(scan, reason, account["id"])
    return envelope.ok(serializers.scan(scan))


# --- findings: candidate selection then classification ----------------------

@bp.post("/scan-runs/<scan_id>/findings")
def record_finding(scan_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT])
    scan = ctx.path("scan", scan_id)
    ctx.load_body()
    fields = ctx.validate(
        [
            {"name": "broker_id", "type": "string", "required": True},
            {
                "name": "exposure_kind",
                "type": "string",
                "required": True,
                "enum": K.EXPOSURE_KINDS,
            },
            {"name": "source_url", "type": "string", "required": True},
        ]
    )
    # Rung 11
    broker = DB.brokers.get(fields["broker_id"])
    if broker is None:
        raise ApiError("ERR_BROKER_NOT_FOUND")
    ctx.write_gates(_account_of_scan(scan))
    states.gate("scan_status", scan["status"], ("RUNNING",))
    # Rung 22
    if broker["status"] != "ACTIVE":
        raise ApiError("ERR_BROKER_RETIRED")

    profile = _profile_of(scan)
    # Candidate selection runs FIRST: last_seen_at DESC, created_at DESC.
    candidates = [
        e
        for e in derive.profile_exposures(profile["id"])
        if e["broker_id"] == broker["id"]
        and e["status"] in ("FOUND", "SUPPRESSED", "REAPPEARED", "RE_SUPPRESSED")
    ]
    candidate = None
    if candidates:
        candidates.sort(key=lambda e: (e["last_seen_at"], e["created_at"], e["id"]), reverse=True)
        candidate = candidates[0]

    # Classification.
    if candidate is None:
        classification = "FRESH"
    elif candidate["status"] in ("FOUND", "REAPPEARED"):
        classification = "RESIGHTING"
    else:
        elapsed = whole_days_between(candidate["last_suppressed_at"], CLOCK.now)
        classification = (
            "REAPPEARANCE" if elapsed < K.REAPPEARANCE_COOLOFF_DAYS else "FRESH"
        )

    if classification == "FRESH":
        exposure = rows.new_row(
            "exposures",
            {
                "profile_id": profile["id"],
                "broker_id": broker["id"],
                "discovered_by_scan_id": scan["id"],
                "exposure_kind": fields["exposure_kind"],
                "source_url": fields["source_url"],
                "status": "FOUND",
                "first_found_at": CLOCK.now,
                "last_seen_at": CLOCK.now,
                "last_suppressed_at": None,
                "suppression_count": 0,
                "reappearance_count": 0,
            },
        )
    elif classification == "REAPPEARANCE":
        exposure = candidate
        exposure["status"] = "REAPPEARED"
        exposure["reappearance_count"] = exposure["reappearance_count"] + 1
        exposure["last_seen_at"] = CLOCK.now
        rows.touch(exposure)
        scan["reappearance_hit_count"] = scan["reappearance_hit_count"] + 1
    else:  # RESIGHTING
        exposure = candidate
        exposure["last_seen_at"] = CLOCK.now
        rows.touch(exposure)

    # findings_count and reappearance_hit_count are declared `computed` in §1.1
    # and the endpoint's side-effect list deliberately omits a ScanRun version
    # bump (every other transition endpoint states one), so the scan row's
    # version and updated_at are NOT touched here.
    scan["findings_count"] = scan["findings_count"] + 1
    return envelope.ok(serializers.exposure(exposure))
