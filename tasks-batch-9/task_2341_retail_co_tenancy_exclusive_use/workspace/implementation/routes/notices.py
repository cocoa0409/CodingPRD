"""Use-violation notices, radius enforcement, disputes and adjudication."""
from flask import Blueprint

import engine
import validate as v
from crud import apply_filters, base, paginate, resolve, strip
from db import store
from errors import ApiError
from middleware import (LIST_READ_ROLES, SINGLE_READ_ROLES, authorize,
                        tenant_scope_lease)
from response import created, listing, ok
from util import D, add_days_dt, as_date, cents, fmt_dt, parse_dt

bp = Blueprint("notices", __name__)

NOTICE_KINDS = ("EXCLUSIVE_USE", "PROHIBITED_USE", "RADIUS")
GROUNDS = ("NO_PROHIBITED_USE", "CARVE_OUT_APPLIES", "CLAUSE_EXPIRED",
           "SCOPE_INAPPLICABLE")
OUTCOMES = ("UPHELD", "DENIED")


def get_notice(notice_id):
    return resolve(store.notices, notice_id, "ERR_NOTICE_NOT_FOUND")


def get_dispute(dispute_id):
    return resolve(store.disputes, dispute_id, "ERR_DISPUTE_NOT_FOUND")


def _new_notice(lease, kind, narrative, cure_period_days, issued_by,
                clause_id=None, restriction_id=None, reported=0, assessed=0):
    issued_at = engine.now()
    notice = base(fmt_dt(issued_at))
    notice.update({
        "violating_lease_id": lease["id"],
        "clause_id": clause_id,
        "radius_restriction_id": restriction_id,
        "notice_kind": kind,
        "narrative": narrative,
        "issued_by_user_id": issued_by,
        "issued_at": fmt_dt(issued_at),
        "cure_period_days": cure_period_days,
        "cure_deadline_at": fmt_dt(add_days_dt(issued_at, cure_period_days)),
        "cure_restart_count": 0,
        "reported_offending_sales_cents": reported,
        "recapture_assessed_cents": assessed,
        "status": "ISSUED",
        "escalated_at": None,
    })
    store.notices[notice["id"]] = notice
    if engine.recompute_use_compliance(lease):
        engine.touch_lease(lease)
    center = engine.center_of_lease(lease)
    if center is not None:
        engine.bump_center(center)
    return notice


@bp.post("/use-violation-notices")
def create_notice():
    role, user_id = authorize(["ComplianceOfficer", "LeaseAdministrator"])
    body = v.body()
    violating_lease_id = v.req_str(body, "violating_lease_id")
    kind = v.req_enum(body, "notice_kind", NOTICE_KINDS)
    narrative = v.opt_str(body, "narrative", default="")
    cure_period_days = v.opt_int(body, "cure_period_days", default=30, minimum=0)
    clause_id = v.opt_id(body, "clause_id")
    if kind == "RADIUS":
        raise ApiError("ERR_INVALID_REQUEST",
                       "A RADIUS notice is minted only by a radius violation report")
    if kind == "EXCLUSIVE_USE" and clause_id is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "An EXCLUSIVE_USE notice requires clause_id")
    if kind == "PROHIBITED_USE" and clause_id is not None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "A PROHIBITED_USE notice must not carry clause_id")

    lease = resolve(store.leases, violating_lease_id, "ERR_LEASE_NOT_FOUND")
    clause = None
    if clause_id is not None:
        clause = resolve(store.clauses, clause_id, "ERR_CLAUSE_NOT_FOUND")
        benefited = store.leases.get(clause["lease_id"])
        if benefited is None or benefited["center_id"] != lease["center_id"]:
            raise ApiError("ERR_CENTER_SCOPE_MISMATCH")
    if clause is not None and clause["status"] != "ACTIVE":
        raise ApiError("ERR_CLAUSE_NOT_ACTIVE")

    notice = _new_notice(lease, kind, narrative, cure_period_days, user_id,
                         clause_id=clause_id)
    return created(strip(notice))


@bp.post("/radius-restrictions/<restriction_id>/violation-report")
def violation_report(restriction_id):
    role, user_id = authorize(["ComplianceOfficer"])
    body = v.body()
    reported = v.req_int(body, "reported_offending_sales_cents", minimum=0)
    narrative = v.req_str(body, "narrative")
    cure_period_days = v.opt_int(body, "cure_period_days", default=30, minimum=0)

    restriction = resolve(store.restrictions, restriction_id,
                          "ERR_RESTRICTION_NOT_FOUND")
    day = engine.today()
    if restriction["status"] != "ACTIVE" \
            or not (as_date(restriction["window_from_date"]) <= day
                    <= as_date(restriction["window_through_date"])):
        raise ApiError("ERR_RADIUS_WINDOW_INACTIVE")

    lease = store.leases.get(restriction["lease_id"])
    if lease is None:
        raise ApiError("ERR_LEASE_NOT_FOUND")

    if restriction["recapture_basis"] == "GROSS_SALES":
        chargeable = D(reported)
    else:
        chargeable = D(reported) - D(restriction["protected_baseline_cents"])
        if chargeable < 0:
            chargeable = D(0)
    assessed = cents(chargeable * D(restriction["recapture_pct"]) / 100)

    notice = _new_notice(lease, "RADIUS", narrative, cure_period_days, user_id,
                         restriction_id=restriction["id"], reported=reported,
                         assessed=assessed)
    return created(strip(notice))


@bp.get("/use-violation-notices/<notice_id>")
def read_notice(notice_id):
    authorize(SINGLE_READ_ROLES)
    return ok(strip(get_notice(notice_id)))


@bp.get("/use-violation-notices")
def list_notices():
    authorize(LIST_READ_ROLES)
    limit, offset = v.pagination()
    records = engine._ordered(list(store.notices.values()))
    records = apply_filters(records, [
        ("violating_lease_id", v.filter_value("violating_lease_id")),
        ("clause_id", v.filter_value("clause_id")),
        ("radius_restriction_id", v.filter_value("radius_restriction_id")),
        ("notice_kind", v.filter_value("notice_kind")),
        ("status", v.filter_value("status")),
    ])
    page, total = paginate(records, limit, offset)
    return listing([strip(r) for r in page], limit, offset, total)


@bp.get("/use-violation-notices/<notice_id>/disputes")
def list_notice_disputes(notice_id):
    authorize(["AssetManager", "LeaseAdministrator", "ComplianceOfficer", "TenantRep"])
    limit, offset = v.pagination()
    notice = get_notice(notice_id)
    records = engine.disputes_of_notice(notice["id"])
    records = apply_filters(records, [
        ("filed_by_tenant_id", v.filter_value("filed_by_tenant_id")),
        ("status", v.filter_value("status")),
        ("grounds_code", v.filter_value("grounds_code")),
    ])
    page, total = paginate(records, limit, offset)
    return listing([strip(r) for r in page], limit, offset, total)


def _pending_dispute(notice):
    return any(d["status"] == "PENDING" for d in engine.disputes_of_notice(notice["id"]))


@bp.post("/use-violation-notices/<notice_id>/cure")
def cure_notice(notice_id):
    authorize(["LeaseAdministrator", "ComplianceOfficer"])
    body = v.body()
    v.opt_str(body, "cure_evidence_code")
    notice = get_notice(notice_id)
    # rung 10 defers the DISPUTED from-state to rung 15
    if notice["status"] not in ("ISSUED", "ESCALATED", "DISPUTED"):
        raise ApiError("ERR_NOTICE_STATE_INVALID")
    if notice["status"] == "DISPUTED" or _pending_dispute(notice):
        raise ApiError("ERR_DISPUTE_PENDING")

    lease = store.leases.get(notice["violating_lease_id"])
    engine.close_notice(notice, "CURED", release_benefited=False)
    center = engine.center_of_lease(lease) if lease else None
    if center is not None:
        engine.bump_center(center)
    return ok(strip(notice))


@bp.post("/use-violation-notices/<notice_id>/escalate")
def escalate(notice_id):
    authorize(["ComplianceOfficer"])
    v.body()
    notice = get_notice(notice_id)
    if notice["status"] not in ("ISSUED", "DISPUTED"):
        raise ApiError("ERR_NOTICE_STATE_INVALID")
    if notice["status"] == "DISPUTED" or _pending_dispute(notice):
        raise ApiError("ERR_DISPUTE_PENDING")
    deadline = parse_dt(notice["cure_deadline_at"])
    if deadline is None or deadline > engine.now():
        raise ApiError("ERR_CURE_PERIOD_NOT_EXPIRED")

    lease = store.leases.get(notice["violating_lease_id"])
    engine.escalate_notice(notice, engine.now())
    center = engine.center_of_lease(lease) if lease else None
    if center is not None:
        engine.bump_center(center)
    return ok(strip(notice))


@bp.post("/use-violation-notices/<notice_id>/withdraw")
def withdraw(notice_id):
    authorize(["ComplianceOfficer"])
    body = v.body()
    v.opt_str(body, "withdrawal_reason_code")
    notice = get_notice(notice_id)
    if notice["status"] not in ("ISSUED", "ESCALATED", "DISPUTED"):
        raise ApiError("ERR_NOTICE_STATE_INVALID")
    if notice["status"] == "DISPUTED" or _pending_dispute(notice):
        raise ApiError("ERR_DISPUTE_PENDING")

    lease = store.leases.get(notice["violating_lease_id"])
    engine.close_notice(notice, "WITHDRAWN", release_benefited=True)
    center = engine.center_of_lease(lease) if lease else None
    if center is not None:
        engine.bump_center(center)
    return ok(strip(notice))


@bp.post("/use-violation-notices/<notice_id>/disputes")
def create_dispute(notice_id):
    role, user_id = authorize(["TenantRep"])
    body = v.body()
    grounds_code = v.req_enum(body, "grounds_code", GROUNDS)
    narrative = v.req_str(body, "narrative")
    extension = v.opt_int(body, "cure_extension_days", default=0, minimum=0,
                          maximum=90)
    notice = get_notice(notice_id)
    lease = store.leases.get(notice["violating_lease_id"])
    if lease is None:
        raise ApiError("ERR_LEASE_NOT_FOUND")
    tenant_scope_lease(role, user_id, lease)

    if notice["status"] != "ISSUED":
        raise ApiError("ERR_NOTICE_STATE_INVALID")
    if _pending_dispute(notice):
        raise ApiError("ERR_DISPUTE_PENDING")

    dispute = base(engine.stamp())
    dispute.update({
        "notice_id": notice["id"],
        "filed_by_tenant_id": user_id,
        "grounds_code": grounds_code,
        "narrative": narrative,
        "cure_extension_days": extension,
        "status": "PENDING",
        "adjudicated_by_user_id": None,
        "adjudicated_at": None,
    })
    store.disputes[dispute["id"]] = dispute

    # the notice moves ISSUED -> DISPUTED and its cure clock freezes where it stands
    notice["status"] = "DISPUTED"
    engine.touch(notice)
    if engine.recompute_use_compliance(lease):
        engine.touch_lease(lease)
    center = engine.center_of_lease(lease)
    if center is not None:
        engine.bump_center(center)
    return created(strip(dispute))


@bp.get("/use-violation-disputes/<dispute_id>")
def read_dispute(dispute_id):
    authorize(["AssetManager", "LeaseAdministrator", "ComplianceOfficer", "TenantRep"])
    return ok(strip(get_dispute(dispute_id)))


@bp.get("/use-violation-disputes")
def list_disputes():
    authorize(["AssetManager", "LeaseAdministrator", "ComplianceOfficer"])
    limit, offset = v.pagination()
    records = engine._ordered(list(store.disputes.values()))
    records = apply_filters(records, [
        ("notice_id", v.filter_value("notice_id")),
        ("filed_by_tenant_id", v.filter_value("filed_by_tenant_id")),
        ("status", v.filter_value("status")),
        ("grounds_code", v.filter_value("grounds_code")),
    ])
    page, total = paginate(records, limit, offset)
    return listing([strip(r) for r in page], limit, offset, total)


@bp.post("/use-violation-disputes/<dispute_id>/adjudicate")
def adjudicate(dispute_id):
    role, user_id = authorize(["ComplianceOfficer"])
    body = v.body()
    outcome = v.req_enum(body, "outcome", OUTCOMES)
    dispute = get_dispute(dispute_id)
    notice = store.notices.get(dispute["notice_id"])
    if notice is None:
        raise ApiError("ERR_NOTICE_NOT_FOUND")

    if dispute["status"] != "PENDING":
        raise ApiError("ERR_DISPUTE_STATE_INVALID")
    if user_id is not None and user_id == notice["issued_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    adjudicated_at = engine.now()
    dispute["adjudicated_by_user_id"] = user_id
    dispute["adjudicated_at"] = fmt_dt(adjudicated_at)
    lease = store.leases.get(notice["violating_lease_id"])

    if outcome == "UPHELD":
        dispute["status"] = "UPHELD"
        engine.touch(dispute)
        notice["status"] = "DISPUTED"  # the from-state for the withdrawal
        engine.close_notice(notice, "WITHDRAWN", release_benefited=True)
        if dispute["grounds_code"] == "SCOPE_INAPPLICABLE":
            if notice.get("clause_id"):
                clause = store.clauses.get(notice["clause_id"])
                if clause is not None and clause["status"] == "ACTIVE":
                    clause["status"] = "WAIVED"
                    engine.touch(clause)
            if notice.get("radius_restriction_id"):
                restriction = store.restrictions.get(notice["radius_restriction_id"])
                if restriction is not None and restriction["status"] == "ACTIVE":
                    restriction["status"] = "WAIVED"
                    engine.touch(restriction)
    else:
        dispute["status"] = "DENIED"
        engine.touch(dispute)
        notice["status"] = "ISSUED"
        notice["cure_restart_count"] = notice["cure_restart_count"] + 1
        notice["cure_deadline_at"] = fmt_dt(add_days_dt(
            adjudicated_at,
            notice["cure_period_days"] + dispute["cure_extension_days"]))
        engine.touch(notice)
        if lease is not None and engine.recompute_use_compliance(lease):
            engine.touch_lease(lease)

    center = engine.center_of_lease(lease) if lease else None
    if center is not None:
        engine.bump_center(center)
    return ok(strip(dispute))
