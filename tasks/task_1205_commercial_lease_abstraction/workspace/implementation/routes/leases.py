"""Lease endpoints: CRUD, abstraction lifecycle, activation, termination,
rent roll."""

from db import db, new_resource, touch
from errors import err
from response import success_object
from services import calc
from services.core import (
    recompute_billing_posture, recompute_property_posture,
    recompute_recovery_ytd,
)
from services.validate import (
    body, req_string, req_int, req_enum, req_date, filter_arg_str,
    opt_int,
)
from routes.helpers import (
    get_property_or_404, get_lease_or_404, list_response,
)
from flask import Blueprint

bp = Blueprint("leases", __name__)

ESCALATION_TYPES = {"NONE", "FIXED_PCT", "CPI", "STEPPED"}
RECOVERY_STRUCTURES = {"NNN", "MODIFIED_GROSS", "GROSS"}
LEASE_STATUS = {"DRAFT", "ACTIVE", "EXPIRED", "TERMINATED"}
ABSTRACTION_STATUS = {"PENDING", "ABSTRACTED", "CERTIFIED"}
BILLING_POSTURE = {"CURRENT", "FROZEN", "DELINQUENT"}


@bp.post("/lease-admin/properties/<property_id>/leases")
def create_lease(property_id):
    prop = get_property_or_404(property_id)
    data = body()
    tenant_legal_name = req_string(data, "tenant_legal_name")
    suite = req_string(data, "suite")
    leased_sf = req_int(data, "leased_sf", min_v=1)
    if leased_sf > prop["total_rentable_sf"]:
        err("ERR_INVALID_REQUEST",
            "leased_sf must not exceed the property's total_rentable_sf")
    commencement_date = req_date(data, "commencement_date")
    expiration_date = req_date(data, "expiration_date")
    base_rent_annual_cents = req_int(data, "base_rent_annual_cents", min_v=0)
    escalation_type = req_enum(data, "escalation_type", ESCALATION_TYPES)
    recovery_structure = req_enum(data, "recovery_structure",
                                  RECOVERY_STRUCTURES)
    pro_rata_share_bps = req_int(data, "pro_rata_share_bps",
                                 min_v=0, max_v=10000)
    security_deposit_cents = req_int(data, "security_deposit_cents", min_v=0)
    # Temporal well-formedness (pipeline step 5).
    if calc.d(commencement_date) >= calc.d(expiration_date):
        err("ERR_INVALID_DATE_RANGE",
            "commencement_date must precede expiration_date")

    lid, common = new_resource()
    lease = {
        **common,
        "property_id": property_id,
        "tenant_legal_name": tenant_legal_name,
        "suite": suite,
        "leased_sf": leased_sf,
        "commencement_date": commencement_date,
        "expiration_date": expiration_date,
        "base_rent_annual_cents": base_rent_annual_cents,
        "escalation_type": escalation_type,
        "recovery_structure": recovery_structure,
        "pro_rata_share_bps": pro_rata_share_bps,
        "status": "DRAFT",
        "abstraction_status": "PENDING",
        "billing_posture": "CURRENT",
        "cached_annual_rent_cents": 0,
        "cached_recovery_ytd_cents": 0,
        "security_deposit_cents": security_deposit_cents,
        "abstractor_user_id": None,
        "certifier_user_id": None,
    }
    db["leases"][lid] = lease
    return success_object(lease, status=201)


@bp.get("/lease-admin/leases/<lease_id>")
def get_lease(lease_id):
    return success_object(get_lease_or_404(lease_id))


@bp.get("/lease-admin/leases")
def list_leases():
    return list_response(db["leases"].values(), filters=[
        (filter_arg_str("property_id"), lambda r, v: r["property_id"] == v),
        (filter_arg_str("status"), lambda r, v: r["status"] == v),
        (filter_arg_str("abstraction_status"),
         lambda r, v: r["abstraction_status"] == v),
        (filter_arg_str("billing_posture"),
         lambda r, v: r["billing_posture"] == v),
    ])


@bp.get("/lease-admin/properties/<property_id>/leases")
def list_property_leases(property_id):
    get_property_or_404(property_id)
    return list_response(
        [l for l in db["leases"].values() if l["property_id"] == property_id])


@bp.post("/lease-admin/leases/<lease_id>/abstract")
def abstract_lease(lease_id):
    from middleware import current_user_id
    lease = get_lease_or_404(lease_id)
    if lease["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Abstraction requires Lease.status == DRAFT")
    if lease["abstraction_status"] != "PENDING":
        err("ERR_INVALID_STATE",
            "Abstraction requires abstraction_status == PENDING")
    lease["abstraction_status"] = "ABSTRACTED"
    lease["abstractor_user_id"] = current_user_id()
    touch(lease)
    return success_object(lease)


@bp.post("/lease-admin/leases/<lease_id>/certify")
def certify_lease(lease_id):
    from middleware import current_user_id
    lease = get_lease_or_404(lease_id)
    if lease["abstraction_status"] != "ABSTRACTED":
        err("ERR_INVALID_STATE",
            "Certification requires abstraction_status == ABSTRACTED")
    # Segregation of duties (pipeline step 7).
    if current_user_id() is not None and \
       current_user_id() == lease["abstractor_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES",
            "Certifier must differ from the abstractor")
    lease["abstraction_status"] = "CERTIFIED"
    lease["certifier_user_id"] = current_user_id()
    touch(lease)
    return success_object(lease)


@bp.post("/lease-admin/leases/<lease_id>/reopen-abstraction")
def reopen_abstraction(lease_id):
    lease = get_lease_or_404(lease_id)
    data = body()
    expected = req_int(data, "expected_lease_version", min_v=0)
    if lease["abstraction_status"] != "CERTIFIED":
        err("ERR_INVALID_STATE",
            "Reopen requires abstraction_status == CERTIFIED")
    if lease["status"] != "DRAFT":
        err("ERR_INVALID_STATE",
            "Cannot reopen abstraction after activation")
    # OCC precondition (pipeline step 14).
    if expected != lease["version"]:
        err("ERR_STALE_VERSION",
            "expected_lease_version does not match the lease's current version")
    lease["abstraction_status"] = "PENDING"
    lease["abstractor_user_id"] = None
    lease["certifier_user_id"] = None
    touch(lease)
    return success_object(lease)


@bp.post("/lease-admin/leases/<lease_id>/activate")
def activate_lease(lease_id):
    lease = get_lease_or_404(lease_id)
    if lease["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Activation requires Lease.status == DRAFT")
    if lease["abstraction_status"] != "CERTIFIED":
        err("ERR_ABSTRACTION_NOT_CERTIFIED",
            "Lease abstraction must be CERTIFIED before activation")
    # Schedule coverage: lines must cover [commencement, expiration) with no
    # gap.
    start = calc.d(lease["commencement_date"])
    end = calc.d(lease["expiration_date"])
    lines = sorted(
        [l for l in db["rent_schedule_lines"].values()
         if l["lease_id"] == lease_id],
        key=lambda l: calc.d(l["period_start"]))
    cursor = start
    for l in lines:
        ps, pe = calc.d(l["period_start"]), calc.d(l["period_end"])
        if ps > cursor:
            err("ERR_SCHEDULE_GAP",
                "Rent schedule has a gap within [commencement_date, expiration_date)")
        if pe > cursor:
            cursor = pe
        if cursor >= end:
            break
    if cursor < end:
        err("ERR_SCHEDULE_GAP",
            "Rent schedule has a gap within [commencement_date, expiration_date)")
    # Billing initialized: at least one DRAFT/ISSUED RecoveryBilling for the
    # current fiscal year.
    prop = db["properties"][lease["property_id"]]
    fy = calc.current_fiscal_year(prop)
    has_billing = any(
        b for b in db["recovery_billings"].values()
        if b["lease_id"] == lease_id and b["fiscal_year"] == fy
        and b["status"] in ("DRAFT", "ISSUED"))
    if not has_billing:
        err("ERR_BILLING_NOT_INITIALIZED",
            "No DRAFT/ISSUED RecoveryBilling exists for the current fiscal year")
    lease["status"] = "ACTIVE"
    calc.recompute_cached_annual_rent(lease)
    touch(lease)
    recompute_property_posture(lease["property_id"])
    return success_object(lease)


@bp.post("/lease-admin/leases/<lease_id>/terminate")
def terminate_lease(lease_id):
    lease = get_lease_or_404(lease_id)
    if lease["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Termination requires Lease.status == ACTIVE")
    # Fiscal gates: no outstanding ISSUED unpaid billing; no OPEN/CHALLENGED
    # reconciliation.
    for b in db["recovery_billings"].values():
        if b["lease_id"] == lease_id and b["status"] == "ISSUED":
            err("ERR_OUTSTANDING_BILLING",
                "An outstanding ISSUED unpaid RecoveryBilling exists")
    for r in db["reconciliations"].values():
        if r["lease_id"] == lease_id and r["status"] in ("OPEN", "CHALLENGED"):
            err("ERR_OPEN_RECONCILIATION",
                "A Reconciliation in OPEN or CHALLENGED state exists")
    lease["status"] = "TERMINATED"
    touch(lease)
    # Cascade: all PENDING CriticalDates -> WAIVED.
    for cd in db["critical_dates"].values():
        if cd["lease_id"] == lease_id and cd["status"] == "PENDING":
            cd["status"] = "WAIVED"
            touch(cd)
    # Cascade: all DRAFT RecoveryBillings -> VOID.
    for b in db["recovery_billings"].values():
        if b["lease_id"] == lease_id and b["status"] == "DRAFT":
            b["status"] = "VOID"
            touch(b)
    recompute_property_posture(lease["property_id"])
    return success_object(lease)


@bp.get("/lease-admin/leases/<lease_id>/rent-roll")
def rent_roll(lease_id):
    from services.validate import filter_arg_int
    lease = get_lease_or_404(lease_id)
    fy = filter_arg_int("fiscal_year", min_v=2000, max_v=2100)
    if fy is None:
        err("ERR_INVALID_REQUEST", "Query parameter fiscal_year is required")
    basis = filter_arg_str("basis") or "cash"
    if basis not in ("cash", "straight_line"):
        err("ERR_INVALID_REQUEST", "basis must be cash or straight_line")
    prop = db["properties"][lease["property_id"]]
    fy_start, fy_end = calc.fiscal_year_window(prop, fy)
    if basis == "cash":
        total = calc.annual_rent_total(lease_id, fy_start, fy_end)
    else:
        total = calc.straight_line_rent(lease_id, fy_start, fy_end)
    return success_object({
        "fiscal_year": fy,
        "basis": basis,
        "total_rent_cents": total,
        "recovery_ytd_cents": lease["cached_recovery_ytd_cents"],
    })
