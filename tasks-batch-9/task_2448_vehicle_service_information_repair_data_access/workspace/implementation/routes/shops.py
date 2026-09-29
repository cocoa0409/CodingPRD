"""Shops, data credit, coverage reads, technicians and diagnostic tools."""

from flask import Blueprint

from auth import authenticate, require_shop_scope
from calc import coverage_report
from envelope import object_response
from errors import err
from serialize import project
from services import append_audit, cascade_revoke_seats, find, sorted_rows
from store import store
from validate import body_object, check_allowed, get_dt, get_enum, get_int, get_ref, get_str, pagination, q_enum

from routes.common import IDENTITY_STATUSES, TIERS, TOOL_STATUSES, paged

bp = Blueprint("shops", __name__)

SHOP_READERS = ("PlatformAdmin", "ComplianceOfficer", "ShopManager")


def _scoped_shop_id(body, field="shop_id"):
    """Ladder rung 3 compares the supplied identifier before anything else."""
    value = body.get(field)
    if not isinstance(value, str) or not value:
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string identifier." % field)
    return value


# -- shops ----------------------------------------------------------------


@bp.post("/shops")
def register_shop():
    authenticate(("PlatformAdmin",))
    body = body_object()
    check_allowed(body, ("name", "tier"))
    name = get_str(body, "name", min_len=1, max_len=120)
    tier = get_enum(body, "tier", TIERS)

    row = store.base_row()
    row["name"] = name
    row["tier"] = tier
    row["funded_credit_total_cents"] = 0
    row["data_credit_balance_cents"] = 0
    row["gateway_fee_accrued_cents"] = 0
    row["coverage_completeness_pct"] = 0.00
    store.shops[row["id"]] = row
    return object_response(project("shop", row), 201)


@bp.get("/shops/<shop_id>")
def read_shop(shop_id):
    user_id, role = authenticate(SHOP_READERS)
    require_shop_scope(role, user_id, shop_id)
    row = find(store.shops, shop_id, "ERR_SHOP_NOT_FOUND")
    return object_response(project("shop", row))


@bp.post("/shops/<shop_id>/credit-funding")
def fund_shop(shop_id):
    authenticate(("PlatformAdmin",))
    body = body_object()
    check_allowed(body, ("amount_cents", "funding_ref"))
    amount_cents = get_int(body, "amount_cents", minimum=1)
    get_str(body, "funding_ref", min_len=1)
    shop = find(store.shops, shop_id, "ERR_SHOP_NOT_FOUND")

    shop["funded_credit_total_cents"] = shop["funded_credit_total_cents"] + amount_cents
    shop["data_credit_balance_cents"] = shop["data_credit_balance_cents"] + amount_cents
    store.touch(shop)
    return object_response(project("shop", shop))


@bp.get("/shops/<shop_id>/coverage-map")
def coverage_map(shop_id):
    user_id, role = authenticate(SHOP_READERS)
    require_shop_scope(role, user_id, shop_id)
    basis = q_enum("basis", ("EFFECTIVE", "DECLARED"), default="EFFECTIVE")
    find(store.shops, shop_id, "ERR_SHOP_NOT_FOUND")
    return object_response(coverage_report(shop_id, basis))


# -- technicians ----------------------------------------------------------


@bp.post("/technicians")
def enrol_technician():
    user_id, role = authenticate(("ShopManager",))
    body = body_object()
    shop_id = _scoped_shop_id(body)
    require_shop_scope(role, user_id, shop_id)
    check_allowed(body, ("shop_id", "full_name", "credential_expires_at"))
    full_name = get_str(body, "full_name", min_len=1, max_len=120)
    expires_raw, expires = get_dt(body, "credential_expires_at")
    find(store.shops, shop_id, "ERR_SHOP_NOT_FOUND")

    row = store.base_row()
    row["shop_id"] = shop_id
    row["full_name"] = full_name
    row["identity_status"] = "UNVERIFIED"
    row["credential_expires_at"] = expires_raw
    row["_credential_expires_at"] = expires
    row["identity_document_ref"] = None
    row["verified_by_user_id"] = None
    store.technicians[row["id"]] = row
    return object_response(project("technician", row), 201)


@bp.get("/shops/<shop_id>/technicians")
def list_shop_technicians(shop_id):
    user_id, role = authenticate(SHOP_READERS)
    require_shop_scope(role, user_id, shop_id)
    identity_status = q_enum("identity_status", IDENTITY_STATUSES)
    limit, offset = pagination()
    find(store.shops, shop_id, "ERR_SHOP_NOT_FOUND")

    rows = [
        row
        for row in store.technicians.values()
        if row["shop_id"] == shop_id
        and (identity_status is None or row["identity_status"] == identity_status)
    ]
    return paged("technician", rows, limit, offset)


@bp.post("/technicians/<technician_id>/verify")
def verify_technician(technician_id):
    user_id, role = authenticate(("ComplianceOfficer",))
    body = body_object()
    check_allowed(body, ("identity_document_ref", "credential_expires_at"))
    document_ref = get_str(body, "identity_document_ref", min_len=1)
    expires_raw, expires = get_dt(body, "credential_expires_at")
    technician = find(store.technicians, technician_id, "ERR_TECHNICIAN_NOT_FOUND")

    if technician["identity_status"] not in ("UNVERIFIED", "SUSPENDED"):
        raise err(
            "ERR_INVALID_STATE", "Only an UNVERIFIED or SUSPENDED technician may be verified."
        )
    if expires <= store.now():
        raise err(
            "ERR_SECURITY_CREDENTIAL_EXPIRED",
            "credential_expires_at must lie strictly after the current logical clock.",
        )

    technician["identity_status"] = "VERIFIED"
    technician["identity_document_ref"] = document_ref
    technician["credential_expires_at"] = expires_raw
    technician["_credential_expires_at"] = expires
    technician["verified_by_user_id"] = user_id
    store.touch(technician)
    append_audit(role, user_id, "Technician", technician["id"], "TECHNICIAN_VERIFIED")
    return object_response(project("technician", technician))


@bp.post("/technicians/<technician_id>/suspend")
def suspend_technician(technician_id):
    user_id, role = authenticate(("ComplianceOfficer",))
    body = body_object()
    check_allowed(body, ("reason",))
    reason = get_str(body, "reason", min_len=1)
    technician = find(store.technicians, technician_id, "ERR_TECHNICIAN_NOT_FOUND")

    if technician["identity_status"] not in ("UNVERIFIED", "VERIFIED"):
        raise err(
            "ERR_INVALID_STATE", "Only an UNVERIFIED or VERIFIED technician may be suspended."
        )

    technician["identity_status"] = "SUSPENDED"
    store.touch(technician)
    append_audit(
        role,
        user_id,
        "Technician",
        technician["id"],
        "TECHNICIAN_SUSPENDED",
        "reason=%s" % reason,
    )

    seats = sorted_rows(
        [
            seat
            for seat in store.seat_assignments.values()
            if seat["technician_id"] == technician["id"]
        ]
    )
    cascade_revoke_seats(seats, "TECHNICIAN_SUSPENDED", "TECHNICIAN_SUSPENDED", "SYSTEM", None)
    return object_response(project("technician", technician))


@bp.post("/technicians/<technician_id>/revoke")
def revoke_technician(technician_id):
    user_id, role = authenticate(("ComplianceOfficer",))
    body = body_object()
    check_allowed(body, ("reason",))
    get_str(body, "reason", min_len=1)
    technician = find(store.technicians, technician_id, "ERR_TECHNICIAN_NOT_FOUND")

    if technician["identity_status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Only a SUSPENDED technician may be revoked.")

    technician["identity_status"] = "REVOKED"
    store.touch(technician)
    return object_response(project("technician", technician))


# -- diagnostic tools -----------------------------------------------------


@bp.post("/diagnostic-tools")
def register_diagnostic_tool():
    user_id, role = authenticate(("ShopManager",))
    body = body_object()
    shop_id = _scoped_shop_id(body)
    require_shop_scope(role, user_id, shop_id)
    check_allowed(body, ("shop_id", "serial_no", "oem_attestation_expires_at"))
    serial_no = get_str(body, "serial_no", min_len=4, max_len=40)
    expires_raw, expires = get_dt(body, "oem_attestation_expires_at")
    find(store.shops, shop_id, "ERR_SHOP_NOT_FOUND")
    for existing in store.diagnostic_tools.values():
        if existing["shop_id"] == shop_id and existing["serial_no"] == serial_no:
            raise err("ERR_INVALID_REQUEST", "serial_no must be unique within this shop.")

    row = store.base_row()
    row["shop_id"] = shop_id
    row["serial_no"] = serial_no
    row["oem_attestation_expires_at"] = expires_raw
    row["_oem_attestation_expires_at"] = expires
    row["status"] = "IDLE"
    row["occupied_by_session_id"] = None
    store.diagnostic_tools[row["id"]] = row
    return object_response(project("diagnostic_tool", row), 201)


@bp.get("/shops/<shop_id>/diagnostic-tools")
def list_shop_tools(shop_id):
    user_id, role = authenticate(SHOP_READERS)
    require_shop_scope(role, user_id, shop_id)
    status = q_enum("status", TOOL_STATUSES)
    limit, offset = pagination()
    find(store.shops, shop_id, "ERR_SHOP_NOT_FOUND")

    rows = [
        row
        for row in store.diagnostic_tools.values()
        if row["shop_id"] == shop_id and (status is None or row["status"] == status)
    ]
    return paged("diagnostic_tool", rows, limit, offset)
