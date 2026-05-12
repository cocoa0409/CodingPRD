"""Lease routes."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request, g

import db
from errors import err
from clock import now, parse_iso, to_utc_midnight, iso
from middleware import require_auth, get_pagination
from response import success, success_list
from services.lookups import get_lease, get_tenant, get_unit, get_deposit_for_lease
from services.validation import (
    require_body, get_body, require_str, require_int, require_iso,
    require_enum, opt_int, opt_iso, require_bool,
)
from services.occ import check_version
from services.rent import generate_for_lease, void_after, validate_stepped_schedule
from services.unit_status import update_status, update_unit_by_id
from services.lease_checks import overlapping_lease_exists
from services.calendar_utils import closed_interval_overlap_half_open
from services.audit import record as audit_record
from services.tenant_ledger import recompute_for_tenant


bp = Blueprint("leases", __name__)

ESCALATION_MODES = {"NONE", "ANNUAL", "BIENNIAL", "STEPPED"}


def _lease_public(le: dict) -> dict:
    out = db.public(le)
    # PRD §3.6: each Deposit is bound 1:1 to its Lease via lease_id.
    # Expose the inverse pointer on the lease for convenient discovery.
    for dep in db.deposits.values():
        if dep.get("lease_id") == le.get("id"):
            out["deposit_id"] = dep["id"]
            break
    return out


def _check_tenant_ownership_lease(le: dict) -> None:
    if g.user_role == "Tenant" and le.get("tenant_id") != g.user_id:
        raise err("ERR_FORBIDDEN", "Tenants can only access their own lease")


@bp.post("/leases")
@require_auth(roles={"LeasingAgent"})
def create_lease():
    body = require_body(request)
    unit_id = require_str(body, "unit_id")
    tenant_id = require_str(body, "tenant_id")
    # FK existence
    unit = get_unit(unit_id)
    get_tenant(tenant_id)
    start_date = require_iso(body, "start_date")
    end_date = require_iso(body, "end_date")
    if end_date <= start_date:
        raise err("ERR_INVALID_DATE_RANGE", "end_date must be strictly after start_date")
    base_rent = require_int(body, "base_monthly_rent_cents", min_value=0)
    escalation_mode = require_enum(body, "escalation_mode", ESCALATION_MODES)
    escalation_pct_bps = opt_int(body, "escalation_pct_bps", min_value=0, default=0) or 0
    rent_free_days = opt_int(body, "rent_free_days", min_value=0, default=0) or 0
    deposit_months = require_int(body, "deposit_months", min_value=1, max_value=6)

    # rent_free_days < lease window length in days
    lease_days = (end_date - start_date).days
    if rent_free_days >= lease_days:
        raise err("ERR_VALIDATION",
                  "rent_free_days must be strictly less than the lease window length")

    stepped_schedule = body.get("stepped_schedule")
    if escalation_mode == "STEPPED":
        if not isinstance(stepped_schedule, list) or not stepped_schedule:
            raise err("ERR_STEPPED_SCHEDULE_INVALID",
                      "stepped_schedule required when escalation_mode=STEPPED")
        validate_stepped_schedule(stepped_schedule, start_date, end_date)
        # normalize ISO strings
        norm = []
        for r in stepped_schedule:
            norm.append({
                "effective_from": iso(parse_iso(r["effective_from"])),
                "monthly_rent_cents": int(r["monthly_rent_cents"]),
            })
        stepped_schedule = norm
    else:
        stepped_schedule = None

    le = {
        "unit_id": unit_id,
        "tenant_id": tenant_id,
        "start_date": iso(start_date),
        "end_date": iso(end_date),
        "base_monthly_rent_cents": base_rent,
        "escalation_mode": escalation_mode,
        "escalation_pct_bps": escalation_pct_bps,
        "stepped_schedule": stepped_schedule,
        "rent_free_days": rent_free_days,
        "deposit_months": deposit_months,
        "status": "DRAFT",
        "terminated_on": None,
        "amendment_count": 0,
    }
    db.stamp_create(le)
    db.leases[le["id"]] = le
    return success(_lease_public(le), status=201)


@bp.post("/leases/<lease_id>/sign")
@require_auth(roles={"LeasingAgent"})
def sign_lease(lease_id):
    le = get_lease(lease_id)
    # Optimistic concurrency
    body = get_body(request)
    check_version(body, le)
    if le["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", f"Lease must be DRAFT (current: {le['status']})")
    tenant = get_tenant(le["tenant_id"])
    if tenant["qualification_status"] != "APPROVED":
        raise err("ERR_TENANT_NOT_APPROVED",
                  "Tenant qualification_status must be APPROVED to sign lease")
    unit = get_unit(le["unit_id"])
    update_status(unit)
    # PRD §3.3 allows adjacency (end_date of one lease == start_date of
    # another). The derived unit status becomes LEASED whenever any
    # non-terminal lease exists, so we cannot use unit.status alone as
    # the gate. Per PRD's narrative intent — ERR_UNIT_NOT_AVAILABLE
    # versus ERR_LEASE_OVERLAP are separate concerns — the
    # unit-availability check rejects only when the unit is in a state
    # that is unrecoverable for signing (RETIRED or UNDER_RENOVATION).
    # Lease-on-lease overlap is then handled by ERR_LEASE_OVERLAP,
    # which uses the half-open interval semantics that permit
    # adjacency.
    if unit["status"] in {"RETIRED", "UNDER_RENOVATION"}:
        raise err("ERR_UNIT_NOT_AVAILABLE",
                  f"Unit must be VACANT or RESERVED (current: {unit['status']})")
    start_dt = parse_iso(le["start_date"])
    end_dt = parse_iso(le["end_date"])
    if overlapping_lease_exists(le["unit_id"], start_dt, end_dt, exclude_lease_id=lease_id):
        raise err("ERR_LEASE_OVERLAP", "Lease window overlaps another non-terminated lease")
    # Renovation conflict
    rs = unit.get("renovation_start_date")
    re_d = unit.get("renovation_end_date")
    if rs and re_d:
        rs_dt = parse_iso(rs)
        re_dt = parse_iso(re_d)
        extended = re_dt + timedelta(days=1)
        if closed_interval_overlap_half_open(rs_dt, extended, start_dt, end_dt):
            raise err("ERR_RENOVATION_LEASE_CONFLICT",
                      "Lease window overlaps unit renovation interval (with 1-day buffer)")
    # Re-validate stepped schedule
    if le["escalation_mode"] == "STEPPED":
        validate_stepped_schedule(le.get("stepped_schedule") or [], start_dt, end_dt)

    le["status"] = "SIGNED"
    db.stamp_update(le)

    # Create deposit
    required = int(le["deposit_months"]) * int(le["base_monthly_rent_cents"])
    deposit = {
        "lease_id": le["id"],
        "required_cents": required,
        "collected_cents": 0,
        "retained_cents": 0,
        "refunded_cents": 0,
        "frozen_status": "UNFROZEN",
        "adjustment_status": "AT_REST",
        "pending_deduction_items": [],
    }
    db.stamp_create(deposit)
    db.deposits[deposit["id"]] = deposit

    # Generate rent schedule items
    generate_for_lease(le)

    # Cascade unit to LEASED
    unit["_reserved"] = False
    db.stamp_update(unit)
    update_status(unit)

    # Audit
    audit_record(
        subject_kind="LEASE", subject_id=le["id"], action="CONTRACT_SIGNED",
        actor_role=g.user_role, actor_id=g.user_id,
        payload={"lease_id": le["id"], "unit_id": le["unit_id"],
                 "tenant_id": le["tenant_id"],
                 "deposit_id": deposit["id"]},
    )
    return success(_lease_public(le))


@bp.post("/leases/<lease_id>/activate")
@require_auth(roles={"LeasingAgent"})
def activate_lease(lease_id):
    le = get_lease(lease_id)
    body = get_body(request)
    check_version(body, le)
    if le["status"] != "SIGNED":
        raise err("ERR_INVALID_STATE", f"Lease must be SIGNED (current: {le['status']})")
    d = get_deposit_for_lease(le["id"])
    if d is None or d["collected_cents"] != d["required_cents"]:
        raise err("ERR_DEPOSIT_INCOMPLETE",
                  "Deposit must be fully collected before activation")
    today = to_utc_midnight(now())
    start_dt = parse_iso(le["start_date"])
    if today < start_dt:
        raise err("ERR_LEASE_NOT_YET_STARTED", "Lease start_date has not been reached")
    le["status"] = "ACTIVE"
    db.stamp_update(le)
    return success(_lease_public(le))


@bp.post("/leases/<lease_id>/amend")
@require_auth(roles={"LeasingAgent"})
def amend_lease(lease_id):
    le = get_lease(lease_id)
    body = require_body(request)
    check_version(body, le)
    if le["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", f"Lease must be ACTIVE to amend (current: {le['status']})")
    # Validate payload fields - allowed keys
    allowed = {
        "new_base_monthly_rent_cents", "new_end_date", "new_rent_free_days",
        "new_deposit_months", "new_stepped_schedule", "new_escalation_mode",
        "new_escalation_pct_bps", "effective_from", "version",
    }
    for k in body.keys():
        if k not in allowed:
            raise err("ERR_AMENDMENT_PAYLOAD_INVALID", f"Unknown amendment field: {k}")
    if "effective_from" not in body:
        raise err("ERR_VALIDATION", "effective_from required for amendment")
    eff = require_iso(body, "effective_from")

    # Field-level constraints (basic types)
    if "new_base_monthly_rent_cents" in body and body["new_base_monthly_rent_cents"] is not None:
        if isinstance(body["new_base_monthly_rent_cents"], bool) or not isinstance(body["new_base_monthly_rent_cents"], int) or body["new_base_monthly_rent_cents"] < 0:
            raise err("ERR_AMENDMENT_PAYLOAD_INVALID", "new_base_monthly_rent_cents invalid")
    if "new_deposit_months" in body and body["new_deposit_months"] is not None:
        v = body["new_deposit_months"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1 or v > 6:
            raise err("ERR_AMENDMENT_PAYLOAD_INVALID", "new_deposit_months must be 1..6")
    if "new_rent_free_days" in body and body["new_rent_free_days"] is not None:
        v = body["new_rent_free_days"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise err("ERR_AMENDMENT_PAYLOAD_INVALID", "new_rent_free_days must be >= 0")
    if "new_escalation_mode" in body and body["new_escalation_mode"] is not None:
        if body["new_escalation_mode"] not in ESCALATION_MODES:
            raise err("ERR_AMENDMENT_PAYLOAD_INVALID", "new_escalation_mode invalid")
    if "new_escalation_pct_bps" in body and body["new_escalation_pct_bps"] is not None:
        v = body["new_escalation_pct_bps"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise err("ERR_AMENDMENT_PAYLOAD_INVALID", "new_escalation_pct_bps invalid")
    if "new_end_date" in body and body["new_end_date"] is not None:
        try:
            parse_iso(body["new_end_date"])
        except Exception:
            raise err("ERR_AMENDMENT_PAYLOAD_INVALID", "new_end_date must be ISO 8601")
    if "new_stepped_schedule" in body and body["new_stepped_schedule"] is not None:
        # Basic shape check; full validation in confirm step
        sched = body["new_stepped_schedule"]
        if not isinstance(sched, list):
            raise err("ERR_AMENDMENT_PAYLOAD_INVALID", "new_stepped_schedule must be a list")

    # Store the pending amendment payload
    payload = {k: v for k, v in body.items() if k != "version"}
    payload["effective_from"] = iso(eff)
    db.pending_amendments[lease_id] = payload

    le["status"] = "AMENDMENT_PENDING"
    db.stamp_update(le)

    # Cascade deposit adjustment_status
    d = get_deposit_for_lease(le["id"])
    if d is not None:
        d["adjustment_status"] = "ADJUSTMENT_PENDING"
        db.stamp_update(d)

    return success(_lease_public(le))


@bp.post("/leases/<lease_id>/amend-confirm")
@require_auth(roles={"FinanceOfficer"})
def amend_confirm(lease_id):
    le = get_lease(lease_id)
    body = get_body(request)
    check_version(body, le)
    if le["status"] != "AMENDMENT_PENDING":
        raise err("ERR_INVALID_STATE",
                  f"Lease must be AMENDMENT_PENDING (current: {le['status']})")
    payload = db.pending_amendments.get(lease_id)
    if payload is None:
        raise err("ERR_AMENDMENT_PAYLOAD_INVALID", "No pending amendment payload found")

    new_end_date = payload.get("new_end_date")
    eff = parse_iso(payload["effective_from"])
    start_dt = parse_iso(le["start_date"])
    end_dt = parse_iso(new_end_date) if new_end_date else parse_iso(le["end_date"])

    # Date range sanity
    if end_dt <= start_dt:
        raise err("ERR_INVALID_DATE_RANGE", "end_date must be > start_date")

    # Re-validate stepped schedule (after merging old + new)
    new_mode = payload.get("new_escalation_mode") or le["escalation_mode"]
    new_sched = payload.get("new_stepped_schedule") if "new_stepped_schedule" in payload else le.get("stepped_schedule")
    if new_mode == "STEPPED":
        if not isinstance(new_sched, list) or not new_sched:
            raise err("ERR_STEPPED_SCHEDULE_INVALID",
                      "stepped_schedule required when escalation_mode=STEPPED")
        validate_stepped_schedule(new_sched, start_dt, end_dt)

    # Overlap check if end_date changed
    if new_end_date and parse_iso(new_end_date) != parse_iso(le["end_date"]):
        if overlapping_lease_exists(le["unit_id"], start_dt, end_dt, exclude_lease_id=lease_id):
            raise err("ERR_LEASE_OVERLAP",
                      "Amended lease window overlaps another non-terminated lease")
    # Renovation conflict
    unit = get_unit(le["unit_id"])
    rs = unit.get("renovation_start_date")
    re_d = unit.get("renovation_end_date")
    if rs and re_d:
        rs_dt = parse_iso(rs)
        re_dt = parse_iso(re_d)
        extended = re_dt + timedelta(days=1)
        if closed_interval_overlap_half_open(rs_dt, extended, start_dt, end_dt):
            raise err("ERR_RENOVATION_LEASE_CONFLICT",
                      "Amended lease window overlaps unit renovation interval (with 1-day buffer)")

    # Apply changes
    old_required = int(le["deposit_months"]) * int(le["base_monthly_rent_cents"])
    if "new_base_monthly_rent_cents" in payload and payload["new_base_monthly_rent_cents"] is not None:
        le["base_monthly_rent_cents"] = int(payload["new_base_monthly_rent_cents"])
    if new_end_date:
        le["end_date"] = iso(parse_iso(new_end_date))
    if "new_rent_free_days" in payload and payload["new_rent_free_days"] is not None:
        v = int(payload["new_rent_free_days"])
        lease_days = (parse_iso(le["end_date"]) - parse_iso(le["start_date"])).days
        if v >= lease_days:
            raise err("ERR_AMENDMENT_PAYLOAD_INVALID",
                      "new_rent_free_days must be < lease window length")
        le["rent_free_days"] = v
    if "new_deposit_months" in payload and payload["new_deposit_months"] is not None:
        le["deposit_months"] = int(payload["new_deposit_months"])
    if "new_escalation_mode" in payload and payload["new_escalation_mode"] is not None:
        le["escalation_mode"] = payload["new_escalation_mode"]
    if "new_escalation_pct_bps" in payload and payload["new_escalation_pct_bps"] is not None:
        le["escalation_pct_bps"] = int(payload["new_escalation_pct_bps"])
    if "new_stepped_schedule" in payload and payload["new_stepped_schedule"] is not None:
        le["stepped_schedule"] = [
            {"effective_from": iso(parse_iso(r["effective_from"])),
             "monthly_rent_cents": int(r["monthly_rent_cents"])}
            for r in payload["new_stepped_schedule"]
        ]
    if le["escalation_mode"] != "STEPPED":
        le["stepped_schedule"] = None

    le["amendment_count"] = int(le.get("amendment_count") or 0) + 1
    le["status"] = "ACTIVE"
    db.stamp_update(le)

    # Regenerate rent schedule from effective_from
    generate_for_lease(le, from_date=eff)

    # Recompute deposit
    d = get_deposit_for_lease(le["id"])
    new_required = int(le["deposit_months"]) * int(le["base_monthly_rent_cents"])
    if d is not None:
        d["required_cents"] = new_required
        delta = new_required - old_required
        if delta > 0:
            d["adjustment_status"] = "ADJUSTMENT_PENDING"
        elif delta < 0:
            # Refund the over-held amount immediately
            refund_amount = min(-delta, d["collected_cents"])
            d["collected_cents"] = d["collected_cents"] - refund_amount
            d["refunded_cents"] = d["refunded_cents"] + refund_amount
            d["adjustment_status"] = "AT_REST"
        else:
            d["adjustment_status"] = "AT_REST"
        db.stamp_update(d)
        recompute_for_tenant(le["tenant_id"])

    # Clear pending payload
    db.pending_amendments.pop(lease_id, None)

    # Audit
    audit_record(
        subject_kind="LEASE", subject_id=le["id"], action="CONTRACT_AMENDED",
        actor_role=g.user_role, actor_id=g.user_id,
        payload={"lease_id": le["id"], "amendment_count": le["amendment_count"],
                 "effective_from": payload["effective_from"]},
    )
    return success(_lease_public(le))


@bp.post("/leases/<lease_id>/amend-cancel")
@require_auth(roles={"LeasingAgent"})
def amend_cancel(lease_id):
    le = get_lease(lease_id)
    body = get_body(request)
    check_version(body, le)
    if le["status"] != "AMENDMENT_PENDING":
        raise err("ERR_INVALID_STATE",
                  f"Lease must be AMENDMENT_PENDING (current: {le['status']})")
    le["status"] = "ACTIVE"
    db.stamp_update(le)
    d = get_deposit_for_lease(le["id"])
    if d is not None:
        d["adjustment_status"] = "AT_REST"
        db.stamp_update(d)
    db.pending_amendments.pop(lease_id, None)
    return success(_lease_public(le))


@bp.post("/leases/<lease_id>/renew")
@require_auth(roles={"LeasingAgent"})
def renew_lease(lease_id):
    le = get_lease(lease_id)
    body = require_body(request)
    check_version(body, le)
    if le["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", f"Lease must be ACTIVE (current: {le['status']})")
    new_end = require_iso(body, "new_end_date")
    new_base = body.get("new_base_monthly_rent_cents")
    if new_base is not None:
        if isinstance(new_base, bool) or not isinstance(new_base, int) or new_base < 0:
            raise err("ERR_VALIDATION", "new_base_monthly_rent_cents must be a non-negative int")

    old_end = parse_iso(le["end_date"])
    if new_end <= old_end:
        raise err("ERR_INVALID_DATE_RANGE", "new_end_date must be > existing end_date")

    # 60-day window check
    today = to_utc_midnight(now())
    if today < old_end - timedelta(days=60):
        raise err("ERR_RENEWAL_WINDOW_NOT_OPEN",
                  "Renewal window opens 60 days before lease end_date")

    # Overlap check: (old_end, new_end_date) — exclusive at both ends per scaffold.
    # Use a tiny offset; effectively half-open (old_end, new_end). We pass (old_end, new_end) which
    # means another lease starting at old_end exactly is allowed (adjacency).
    if overlapping_lease_exists(le["unit_id"], old_end, new_end, exclude_lease_id=lease_id):
        raise err("ERR_LEASE_OVERLAP", "New window overlaps another non-terminated lease")
    # Renovation conflict
    unit = get_unit(le["unit_id"])
    rs = unit.get("renovation_start_date")
    re_d = unit.get("renovation_end_date")
    if rs and re_d:
        rs_dt = parse_iso(rs)
        re_dt = parse_iso(re_d)
        extended = re_dt + timedelta(days=1)
        if closed_interval_overlap_half_open(rs_dt, extended,
                                             parse_iso(le["start_date"]), new_end):
            raise err("ERR_RENOVATION_LEASE_CONFLICT",
                      "Extended lease window overlaps unit renovation interval")

    old_base = int(le["base_monthly_rent_cents"])
    old_required = int(le["deposit_months"]) * old_base

    le["end_date"] = iso(new_end)
    if new_base is not None:
        le["base_monthly_rent_cents"] = int(new_base)
    db.stamp_update(le)

    # Add new RentScheduleItem rows for periods in (old_end, new_end)
    # We pass from_date = old_end. generate_for_lease will not regenerate earlier rows.
    # But the existing month containing old_end may need preservation. Use from_date that
    # is just after old_end — since old_end is exclusive (half-open), months whose
    # period_start >= old_end are new.
    generate_for_lease(le, from_date=old_end)

    # Recompute deposit
    d = get_deposit_for_lease(le["id"])
    new_required = int(le["deposit_months"]) * int(le["base_monthly_rent_cents"])
    if d is not None:
        d["required_cents"] = new_required
        delta = new_required - old_required
        if delta > 0:
            d["adjustment_status"] = "ADJUSTMENT_PENDING"
        elif delta < 0:
            refund_amount = min(-delta, d["collected_cents"])
            d["collected_cents"] = d["collected_cents"] - refund_amount
            d["refunded_cents"] = d["refunded_cents"] + refund_amount
            # delta < 0 doesn't change adjustment_status (stays as previous; usually AT_REST)
        db.stamp_update(d)
        recompute_for_tenant(le["tenant_id"])

    audit_record(
        subject_kind="LEASE", subject_id=le["id"], action="CONTRACT_RENEWED",
        actor_role=g.user_role, actor_id=g.user_id,
        payload={"lease_id": le["id"], "new_end_date": le["end_date"],
                 "new_base_monthly_rent_cents": le["base_monthly_rent_cents"]},
    )
    return success(_lease_public(le))


@bp.post("/leases/<lease_id>/move-out-request")
@require_auth(roles={"Tenant"})
def move_out_request(lease_id):
    le = get_lease(lease_id)
    _check_tenant_ownership_lease(le)
    body = require_body(request)
    target = require_iso(body, "target_move_out_date")
    if le["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", f"Lease must be ACTIVE (current: {le['status']})")

    today = to_utc_midnight(now())
    if (target - today).days < 30:
        raise err("ERR_MOVE_OUT_LEAD_TIME",
                  "target_move_out_date must be >= 30 days from today")
    end_dt = parse_iso(le["end_date"])
    if target > end_dt:
        raise err("ERR_INVALID_DATE_RANGE",
                  "target_move_out_date cannot be later than lease.end_date")

    req = {
        "lease_id": lease_id,
        "requested_on": iso(now()),
        "target_move_out_date": iso(target),
        "status": "SUBMITTED",
        "inspection_findings": [],
        "restoration_done": False,
    }
    db.stamp_create(req)
    db.move_out_requests[req["id"]] = req

    le["status"] = "TERMINATING"
    db.stamp_update(le)

    d = get_deposit_for_lease(le["id"])
    if d is not None:
        d["frozen_status"] = "FROZEN"
        db.stamp_update(d)

    return success(db.public(req), status=201)


@bp.get("/leases/<lease_id>")
@require_auth(roles={"PropertyManager", "LeasingAgent", "FinanceOfficer", "Tenant"})
def get_lease_route(lease_id):
    le = get_lease(lease_id)
    _check_tenant_ownership_lease(le)
    return success(_lease_public(le))


@bp.get("/leases/<lease_id>/rent-schedule")
@require_auth(roles={"PropertyManager", "LeasingAgent", "FinanceOfficer", "Tenant"})
def rent_schedule_route(lease_id):
    le = get_lease(lease_id)
    _check_tenant_ownership_lease(le)
    limit, offset = get_pagination()
    rows = [db.public(r) for r in db.rent_schedule_items.values()
            if r["lease_id"] == lease_id]
    rows.sort(key=lambda r: (r["period_start"], r["created_at"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list(page, limit=limit, offset=offset, total_count=total)
