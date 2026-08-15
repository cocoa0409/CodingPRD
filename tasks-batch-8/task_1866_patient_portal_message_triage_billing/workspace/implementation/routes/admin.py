"""Master-data routes: patients, staff, pools, coverage windows, on-call
shifts, delegation grants, clock, SLA sweep."""

from flask import Blueprint, request

import db
from db import CLOCK, fmt_ts
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_TIME_RANGE,
    ERR_COVERAGE_WINDOW_OVERLAP,
    ERR_ONCALL_SHIFT_OVERLAP,
    ERR_ONCALL_PROVIDER_TYPE,
    ERR_INVALID_DELEGATION_TARGET,
    ERR_DELEGATION_WINDOW_OVERLAP,
    ERR_GRANT_ALREADY_REVOKED,
    ERR_NOT_GRANT_OWNER,
    ERR_PATIENT_OWNERSHIP_MISMATCH,
)
from middleware import (
    authenticate, get_body, req_field, req_string, req_enum, req_int, req_datetime,
    opt_field, new_entity, touch, public, get_or_404, sorted_by_created,
    parse_pagination, _parse_dt, require_patient_ownership,
)
from response import success_object, success_list
from services import domain

bp = Blueprint("admin", __name__)

PLAN_TYPES = {"COPAY", "COINSURANCE"}
POOL_KINDS = {"NURSE_TRIAGE", "PROVIDER_INBOX", "FRONT_DESK", "BILLING"}
DEADLINE_POLICIES = {"FROM_RECEIPT", "FROM_TRIAGE"}
STAFF_ROLES_READ = ["PracticeAdmin", "TriageNurse", "FrontDesk", "Provider", "BillingSpecialist"]


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

@bp.route("/inbox/patients", methods=["POST"])
def create_patient():
    ctx = authenticate(["PracticeAdmin"])
    body = get_body()
    full_name = req_string(body, "full_name")
    plan_type = req_enum(body, "plan_type", PLAN_TYPES)
    copay_cents = body.get("copay_cents")
    coinsurance_pct = body.get("coinsurance_pct")
    dob = opt_field(body, "date_of_birth")

    if plan_type == "COPAY":
        if isinstance(copay_cents, bool) or not isinstance(copay_cents, int):
            raise_err(ERR_INVALID_REQUEST, "copay_cents is required when plan_type == COPAY")
        if coinsurance_pct is not None:
            raise_err(ERR_INVALID_REQUEST, "coinsurance_pct must be absent when plan_type == COPAY")
    else:  # COINSURANCE
        if coinsurance_pct is None or isinstance(coinsurance_pct, bool) or not isinstance(coinsurance_pct, (int, float)):
            raise_err(ERR_INVALID_REQUEST, "coinsurance_pct is required when plan_type == COINSURANCE")
        if not (0 < coinsurance_pct <= 1):
            raise_err(ERR_INVALID_REQUEST, "coinsurance_pct must satisfy 0 < pct <= 1")
        if copay_cents is not None:
            raise_err(ERR_INVALID_REQUEST, "copay_cents must be absent when plan_type == COINSURANCE")

    patient = new_entity({
        "full_name": full_name,
        "date_of_birth": dob,
        "plan_type": plan_type,
        "copay_cents": copay_cents if plan_type == "COPAY" else None,
        "coinsurance_pct": coinsurance_pct if plan_type == "COINSURANCE" else None,
        "outstanding_billed_cents": 0,
        "education_gate_open": False,
    })
    db.patients[patient["id"]] = patient
    return success_object(public(patient), 201)


@bp.route("/inbox/patients/<pid>", methods=["GET"])
def get_patient(pid):
    ctx = authenticate(STAFF_ROLES_READ + ["Patient"])
    patient = db.patients.get(pid)
    # Tier 4: patient ownership — a Patient caller may only read own record.
    if ctx.role == "Patient":
        if ctx.patient is None or pid != ctx.user_id:
            raise_err(ERR_PATIENT_OWNERSHIP_MISMATCH, "Patients may only read their own record")
    if patient is None:
        raise_err(ERR_NOT_FOUND, "patient not found: %s" % pid)
    return success_object(public(patient))


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------

@bp.route("/inbox/staff", methods=["POST"])
def create_staff():
    authenticate(["PracticeAdmin"])
    body = get_body()
    full_name = req_string(body, "full_name")
    staff_type = req_enum(body, "staff_type",
                          {"PROVIDER", "NURSE", "FRONT_DESK", "BILLING_SPECIALIST", "PRACTICE_ADMIN"})
    member = new_entity({
        "full_name": full_name,
        "staff_type": staff_type,
        "open_inbox_count": 0,
        "inbox_overloaded": False,
    })
    db.staff[member["id"]] = member
    return success_object(public(member), 201)


@bp.route("/inbox/staff/<sid>", methods=["GET"])
def get_staff(sid):
    authenticate(STAFF_ROLES_READ)
    member = get_or_404(db.staff, sid, "staff member")
    return success_object(public(member))


@bp.route("/inbox/staff/<sid>/burden-summary", methods=["GET"])
def burden_summary(sid):
    authenticate(STAFF_ROLES_READ)
    member = get_or_404(db.staff, sid, "staff member")
    # metric query param accepted (ATTRIBUTED default | TOUCHED); both variants
    # are always returned per endpoint output contract.
    metric = opt_field(request.args, "metric", "ATTRIBUTED")
    if metric not in ("ATTRIBUTED", "TOUCHED"):
        raise_err(ERR_INVALID_REQUEST, "metric must be ATTRIBUTED or TOUCHED")
    attributed = sum(
        1 for m in db.portal_messages.values()
        if m.get("resolved_by_id") == sid and m["status"] in ("RESOLVED", "CLOSED")
    )
    touched_ids = {
        e["message_id"] for e in db.time_entries.values() if e["staff_id"] == sid
    }
    clinical = sum(
        e["minutes"] for e in db.time_entries.values()
        if e["staff_id"] == sid and e["entry_kind"] == "CLINICAL_REVIEW"
    )
    data = {
        "open_inbox_count": member["open_inbox_count"],
        "inbox_overloaded": member["inbox_overloaded"],
        "attributed_resolutions": attributed,
        "touched_resolutions": len(touched_ids),
        "clinical_minutes": clinical,
    }
    return success_object(data)


# ---------------------------------------------------------------------------
# Pools
# ---------------------------------------------------------------------------

@bp.route("/inbox/pools", methods=["POST"])
def create_pool():
    authenticate(["PracticeAdmin"])
    body = get_body()
    name = req_string(body, "name")
    pool_kind = req_enum(body, "pool_kind", POOL_KINDS)
    t_e = req_int(body, "target_minutes_emergent")
    t_u = req_int(body, "target_minutes_urgent")
    t_r = req_int(body, "target_minutes_routine")
    policy = req_enum(body, "deadline_policy", DEADLINE_POLICIES)
    pool = new_entity({
        "name": name,
        "pool_kind": pool_kind,
        "target_minutes_emergent": t_e,
        "target_minutes_urgent": t_u,
        "target_minutes_routine": t_r,
        "deadline_policy": policy,
    })
    db.pools[pool["id"]] = pool
    return success_object(public(pool), 201)


@bp.route("/inbox/pools/<pid>", methods=["GET"])
def get_pool(pid):
    authenticate(STAFF_ROLES_READ)
    pool = get_or_404(db.pools, pid, "pool")
    return success_object(public(pool))


# ---------------------------------------------------------------------------
# Coverage windows
# ---------------------------------------------------------------------------

@bp.route("/inbox/coverage-windows", methods=["POST"])
def create_coverage_window():
    authenticate(["PracticeAdmin"])
    body = get_body()
    pool_id = req_string(body, "pool_id")
    staff_id = req_string(body, "staff_id")
    # Existence, left to right: pool, then staff.
    get_or_404(db.pools, pool_id, "pool")
    get_or_404(db.staff, staff_id, "staff member")
    start = req_datetime(body, "start_utc")
    end = req_datetime(body, "end_utc")

    if not (end > start):
        raise_err(ERR_INVALID_TIME_RANGE, "end_utc must be strictly later than start_utc")

    # Half-open overlap for the same staff_id; adjacency allowed.
    for w in db.coverage_windows.values():
        if w["staff_id"] != staff_id:
            continue
        ws = _parse_dt(w["start_utc"])
        we = _parse_dt(w["end_utc"])
        if start < we and ws < end:
            raise_err(ERR_COVERAGE_WINDOW_OVERLAP,
                      "Coverage window intersects an existing window for this staff member")

    window = new_entity({
        "pool_id": pool_id,
        "staff_id": staff_id,
        "start_utc": fmt_ts(start),
        "end_utc": fmt_ts(end),
    })
    db.coverage_windows[window["id"]] = window
    return success_object(public(window), 201)


@bp.route("/inbox/coverage-windows", methods=["GET"])
def list_coverage_windows():
    authenticate(STAFF_ROLES_READ)
    limit, offset = parse_pagination()
    pool_id = opt_field(request.args, "pool_id")
    staff_id = opt_field(request.args, "staff_id")
    items = list(db.coverage_windows.values())
    if pool_id is not None:
        items = [w for w in items if w["pool_id"] == pool_id]
    if staff_id is not None:
        items = [w for w in items if w["staff_id"] == staff_id]
    items = sorted_by_created(items)
    total = len(items)
    return success_list([public(w) for w in items[offset:offset + limit]], limit, offset, total)


@bp.route("/inbox/coverage-windows/<wid>", methods=["GET"])
def get_coverage_window(wid):
    authenticate(STAFF_ROLES_READ)
    window = get_or_404(db.coverage_windows, wid, "coverage window")
    return success_object(public(window))


# ---------------------------------------------------------------------------
# On-call shifts
# ---------------------------------------------------------------------------

@bp.route("/inbox/on-call-shifts", methods=["POST"])
def create_on_call_shift():
    authenticate(["PracticeAdmin"])
    body = get_body()
    provider_id = req_string(body, "provider_id")
    provider = get_or_404(db.staff, provider_id, "staff member")
    start = req_datetime(body, "start_utc")
    end = req_datetime(body, "end_utc")

    # Check order per PRD §3.2: provider type, then range, then overlap.
    if provider["staff_type"] != "PROVIDER":
        raise_err(ERR_ONCALL_PROVIDER_TYPE, "OnCallShift.provider_id must reference a PROVIDER")
    if not (end > start):
        raise_err(ERR_INVALID_TIME_RANGE, "end_utc must be strictly later than start_utc")

    # Closed-interval overlap for same provider; touching counts as overlap.
    for s in db.on_call_shifts.values():
        if s["provider_id"] != provider_id:
            continue
        ss = _parse_dt(s["start_utc"])
        se = _parse_dt(s["end_utc"])
        if start <= se and ss <= end:
            raise_err(ERR_ONCALL_SHIFT_OVERLAP,
                      "On-call shift intersects an existing shift for this provider")

    shift = new_entity({
        "provider_id": provider_id,
        "start_utc": fmt_ts(start),
        "end_utc": fmt_ts(end),
    })
    db.on_call_shifts[shift["id"]] = shift
    return success_object(public(shift), 201)


@bp.route("/inbox/on-call-shifts", methods=["GET"])
def list_on_call_shifts():
    authenticate(STAFF_ROLES_READ)
    limit, offset = parse_pagination()
    provider_id = opt_field(request.args, "provider_id")
    items = list(db.on_call_shifts.values())
    if provider_id is not None:
        items = [s for s in items if s["provider_id"] == provider_id]
    items = sorted_by_created(items)
    total = len(items)
    return success_list([public(s) for s in items[offset:offset + limit]], limit, offset, total)


@bp.route("/inbox/on-call-shifts/<sid>", methods=["GET"])
def get_on_call_shift(sid):
    authenticate(STAFF_ROLES_READ)
    shift = get_or_404(db.on_call_shifts, sid, "on-call shift")
    return success_object(public(shift))


# ---------------------------------------------------------------------------
# Delegation grants
# ---------------------------------------------------------------------------

@bp.route("/inbox/delegation-grants", methods=["POST"])
def create_delegation_grant():
    ctx = authenticate(["Provider"])
    body = get_body()
    delegate_staff_id = req_string(body, "delegate_staff_id")
    pool_id = req_string(body, "pool_id")
    start = req_datetime(body, "start_utc")
    end = req_datetime(body, "end_utc")

    delegator_id = ctx.user_id
    # Delegation target validity (ERR_INVALID_DELEGATION_TARGET).
    delegate = db.staff.get(delegate_staff_id)
    pool = db.pools.get(pool_id)
    if (delegate_staff_id == delegator_id or delegate is None
            or pool is None or pool["pool_kind"] != "PROVIDER_INBOX"):
        raise_err(ERR_INVALID_DELEGATION_TARGET,
                  "Delegation target invalid: delegate == delegator, delegate/pool missing, or pool not PROVIDER_INBOX")

    if not (end > start):
        raise_err(ERR_INVALID_TIME_RANGE, "end_utc must be strictly later than start_utc")

    # Closed-interval overlap among ACTIVE grants for the same pair.
    for g in db.delegation_grants.values():
        if g["status"] != "ACTIVE":
            continue
        if g["delegator_provider_id"] != delegator_id or g["delegate_staff_id"] != delegate_staff_id:
            continue
        gs = _parse_dt(g["start_utc"])
        ge = _parse_dt(g["end_utc"])
        if start <= ge and gs <= end:
            raise_err(ERR_DELEGATION_WINDOW_OVERLAP,
                      "Grant window intersects an existing ACTIVE grant for this delegator+delegate pair")

    grant = new_entity({
        "delegator_provider_id": delegator_id,
        "delegate_staff_id": delegate_staff_id,
        "pool_id": pool_id,
        "start_utc": fmt_ts(start),
        "end_utc": fmt_ts(end),
        "status": "ACTIVE",
        "revoked_at": None,
    })
    db.delegation_grants[grant["id"]] = grant
    return success_object(public(grant), 201)


@bp.route("/inbox/delegation-grants", methods=["GET"])
def list_delegation_grants():
    authenticate(STAFF_ROLES_READ)
    limit, offset = parse_pagination()
    delegator = opt_field(request.args, "delegator_provider_id")
    delegate = opt_field(request.args, "delegate_staff_id")
    pool_id = opt_field(request.args, "pool_id")
    status = opt_field(request.args, "status")
    items = list(db.delegation_grants.values())
    if delegator is not None:
        items = [g for g in items if g["delegator_provider_id"] == delegator]
    if delegate is not None:
        items = [g for g in items if g["delegate_staff_id"] == delegate]
    if pool_id is not None:
        items = [g for g in items if g["pool_id"] == pool_id]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    items = sorted_by_created(items)
    total = len(items)
    return success_list([public(g) for g in items[offset:offset + limit]], limit, offset, total)


@bp.route("/inbox/delegation-grants/<gid>", methods=["GET"])
def get_delegation_grant(gid):
    authenticate(STAFF_ROLES_READ)
    grant = get_or_404(db.delegation_grants, gid, "delegation grant")
    return success_object(public(grant))


@bp.route("/inbox/delegation-grants/<gid>/revoke", methods=["POST"])
def revoke_delegation_grant(gid):
    ctx = authenticate(["Provider"])
    grant = get_or_404(db.delegation_grants, gid, "delegation grant")
    if grant["status"] != "ACTIVE":
        raise_err(ERR_GRANT_ALREADY_REVOKED, "Delegation grant is not ACTIVE")
    if ctx.user_id != grant["delegator_provider_id"]:
        raise_err(ERR_NOT_GRANT_OWNER, "Only the grant's delegator may revoke it")

    grant["status"] = "REVOKED"
    grant["revoked_at"] = CLOCK.now_iso()
    touch(grant)

    # Cascade hop 1: reassign delegate's in-flight messages in this pool to
    # the delegator (status retained).
    delegate_id = grant["delegate_staff_id"]
    delegator_id = grant["delegator_provider_id"]
    n = 0
    for m in db.portal_messages.values():
        if (m.get("assignee_id") == delegate_id
                and m.get("assigned_pool_id") == grant["pool_id"]
                and m["status"] in ("ASSIGNED", "IN_REVIEW", "PENDING_COSIGN")):
            m["assignee_id"] = delegator_id
            # A message pending cosign by this delegator keeps its designated
            # cosigner; if the designee was the delegate (cannot happen per
            # grant semantics), nothing to clear here.
            touch(m)
            n += 1

    # Cascade hop 2: zero-sum count shift + overload re-evaluation.
    if n:
        domain.recompute_staff_counts(delegate_id)
        domain.recompute_staff_counts(delegator_id)

    return success_object(public(grant))


# ---------------------------------------------------------------------------
# Test-driving endpoints: logical clock + SLA sweep
# ---------------------------------------------------------------------------

@bp.route("/inbox/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(["PracticeAdmin"])
    body = get_body()
    to_iso8601 = req_field(body, "to_iso8601")
    if not isinstance(to_iso8601, str):
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO-8601 string")
    try:
        now = CLOCK.set(to_iso8601)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO-8601 timestamp")
    return success_object({"current_utc": fmt_ts(now)})


@bp.route("/inbox/_sla/sweep", methods=["POST"])
def sla_sweep():
    authenticate(["PracticeAdmin"])
    now = CLOCK.now()
    swept = 0
    newly = 0
    for m in db.portal_messages.values():
        if m["status"] in ("RESOLVED", "CLOSED"):
            continue
        due = m.get("response_due_at")
        if not due:
            continue
        swept += 1
        if m.get("sla_breached"):
            continue
        effective = m.get("first_response_at")
        effective_dt = _parse_dt(effective) if effective else now
        if effective_dt > _parse_dt(due):
            m["sla_breached"] = True
            touch(m)
            newly += 1
    return success_object({"swept_count": swept, "newly_breached_count": newly})
