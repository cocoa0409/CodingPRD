"""SalonAccount, ProfessionalLicense, and credit-ledger endpoints."""

from flask import Blueprint, request

import errors as E
import middleware as M
import response as R
import services as S
from db import store, new_id, stamp_created, touch, clock_iso, dt_to_iso

bp = Blueprint("salons", __name__)

READ_ROLES = S.ALL_ROLES
LEDGER_ROLES = {"DistributionAdmin", "ComplianceOfficer", "SalonBuyer"}
LICENSE_TYPES = {"COSMETOLOGY", "ESTHETICIAN", "BARBER", "NAIL_TECH", "SALON_BUSINESS"}


# ---------------------------------------------------------------------------
# SalonAccount
# ---------------------------------------------------------------------------
@bp.post("/api/salon-accounts")
def create_salon():
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"legal_name", "territory_code", "assigned_consultant_id"})
    legal_name = M.req_string(data, "legal_name")
    territory_code = M.req_string(data, "territory_code")
    assigned = data.get("assigned_consultant_id")
    if assigned is not None and (not isinstance(assigned, str) or assigned == ""):
        raise E.invalid_request("assigned_consultant_id must be a string")
    M.require_role(ctx, {"SalesConsultant"})
    if assigned is not None and assigned not in store.consultants:
        raise E.consultant_not_found()
    salon = {
        "id": new_id(),
        "legal_name": legal_name,
        "territory_code": territory_code,
        "assigned_consultant_id": assigned,
        "status": "PENDING_VERIFICATION",
        "tier": "SILVER",
        "tier_override_active": False,
        "education_credit_points": 0,
        "diversion_strike_points": 0,
        "diversion_risk_score": 0,
        "trailing_12m_delivered_volume_cents": 0,
        "suspension_reason": None,
    }
    stamp_created(salon)
    store.salons[salon["id"]] = salon
    return R.success_object(S.pub(salon), 201)


@bp.get("/api/salon-accounts")
def list_salons():
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    items = list(store.salons.values())
    if ctx.role == "SalonBuyer":
        items = [s for s in items if s["id"] == ctx.user_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    tier = request.args.get("tier")
    if tier is not None:
        items = [s for s in items if s["tier"] == tier]
    aci = request.args.get("assigned_consultant_id")
    if aci is not None:
        items = [s for s in items if s["assigned_consultant_id"] == aci]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.pub_list(page), limit, offset, total)


@bp.get("/api/salon-accounts/<sid>")
def get_salon(sid):
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    salon = S.get_salon(sid)
    S.buyer_scope(ctx, salon["id"])
    return R.success_object(S.pub(salon))


@bp.post("/api/salon-accounts/<sid>/suspend")
def suspend_salon(sid):
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"reason"})
    M.req_string(data, "reason")
    M.require_role(ctx, {"ComplianceOfficer"})
    salon = S.get_salon(sid)
    if salon["status"] != "ACTIVE":
        raise E.invalid_account_state("Only an ACTIVE salon can be suspended")
    S.suspend_salon(salon, "MANUAL")
    return R.success_object(S.pub(salon))


@bp.post("/api/salon-accounts/<sid>/reinstate")
def reinstate_salon(sid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, {"ComplianceOfficer"})
    salon = S.get_salon(sid)
    if salon["status"] != "SUSPENDED":
        raise E.invalid_account_state("Only a SUSPENDED salon can be reinstated")
    if not S.salon_has_valid_license(salon):
        raise E.no_valid_license()
    salon["status"] = "ACTIVE"
    salon["suspension_reason"] = None
    touch(salon)
    return R.success_object(S.pub(salon))


@bp.post("/api/salon-accounts/<sid>/deactivate")
def deactivate_salon(sid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, {"ComplianceOfficer"})
    salon = S.get_salon(sid)
    if salon["status"] not in ("ACTIVE", "SUSPENDED"):
        raise E.invalid_account_state("Only an ACTIVE or SUSPENDED salon can be deactivated")
    S.deactivate_salon(salon)
    return R.success_object(S.pub(salon))


@bp.post("/api/salon-accounts/<sid>/tier-override")
def tier_override(sid):
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"tier", "expected_salon_account_version"})
    tier = M.req_enum(data, "tier", S.TIERS)
    expected = M.req_int(data, "expected_salon_account_version")
    M.require_role(ctx, {"DistributionAdmin"})
    salon = S.get_salon(sid)
    if expected != salon["version"]:
        raise E.stale_version()
    salon["tier"] = tier
    salon["tier_override_active"] = True
    touch(salon)
    return R.success_object(S.pub(salon))


@bp.post("/api/salon-accounts/<sid>/evaluate-tier")
def evaluate_tier(sid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, {"DistributionAdmin"})
    salon = S.get_salon(sid)
    S.evaluate_salon_tier(salon)
    return R.success_object(S.pub(salon))


# ---------------------------------------------------------------------------
# ProfessionalLicense
# ---------------------------------------------------------------------------
@bp.post("/api/salon-accounts/<sid>/licenses")
def submit_license(sid):
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"license_number", "issuing_state", "license_type", "valid_until"})
    license_number = M.req_string(data, "license_number")
    issuing_state = M.req_string(data, "issuing_state")
    license_type = M.req_enum(data, "license_type", LICENSE_TYPES)
    valid_until = M.req_datetime(data, "valid_until")
    M.require_role(ctx, {"SalesConsultant", "SalonBuyer"})
    S.buyer_scope(ctx, sid)
    salon = S.get_salon(sid)
    if valid_until <= store.clock:
        raise E.license_date_invalid()
    lic = {
        "id": new_id(),
        "salon_account_id": salon["id"],
        "license_number": license_number,
        "issuing_state": issuing_state,
        "license_type": license_type,
        "valid_until": dt_to_iso(valid_until),
        "status": "SUBMITTED",
        "reviewed_by_user_id": None,
    }
    stamp_created(lic)
    store.licenses[lic["id"]] = lic
    return R.success_object(S.pub(lic), 201)


@bp.get("/api/salon-accounts/<sid>/licenses")
def list_licenses(sid):
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    S.buyer_scope(ctx, sid)
    salon = S.get_salon(sid)
    items = S.licenses_of_salon(salon["id"])
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.pub_list(page), limit, offset, total)


@bp.get("/api/licenses/<lid>")
def get_license(lid):
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    lic = S.get_license(lid)
    S.buyer_scope(ctx, lic["salon_account_id"])
    return R.success_object(S.pub(lic))


@bp.post("/api/licenses/<lid>/verify")
def verify_license(lid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, {"ComplianceOfficer"})
    lic = S.get_license(lid)
    if lic["status"] != "SUBMITTED":
        raise E.invalid_license_state("Only a SUBMITTED license can be verified")
    if S.parse_dt(lic["valid_until"]) <= store.clock:
        raise E.license_date_invalid()
    lic["status"] = "VERIFIED"
    lic["reviewed_by_user_id"] = ctx.user_id
    touch(lic)
    salon = store.salons.get(lic["salon_account_id"])
    if salon is not None and salon["status"] == "PENDING_VERIFICATION":
        salon["status"] = "ACTIVE"
        touch(salon)
    return R.success_object(S.pub(lic))


@bp.post("/api/licenses/<lid>/reject")
def reject_license(lid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, {"ComplianceOfficer"})
    lic = S.get_license(lid)
    if lic["status"] != "SUBMITTED":
        raise E.invalid_license_state("Only a SUBMITTED license can be rejected")
    lic["status"] = "REJECTED"
    lic["reviewed_by_user_id"] = ctx.user_id
    touch(lic)
    return R.success_object(S.pub(lic))


# ---------------------------------------------------------------------------
# Education-credit ledger
# ---------------------------------------------------------------------------
@bp.get("/api/salon-accounts/<sid>/credit-ledger")
def credit_ledger(sid):
    ctx = M.require_auth()
    M.require_role(ctx, LEDGER_ROLES)
    S.buyer_scope(ctx, sid)
    salon = S.get_salon(sid)
    items = S.credit_entries_of_salon(salon["id"])
    et = request.args.get("entry_type")
    if et is not None:
        items = [e for e in items if e["entry_type"] == et]
    page, limit, offset, total = M.paginate(items, key=S.ledger_sort_key)
    return R.success_list(S.pub_list(page), limit, offset, total)
