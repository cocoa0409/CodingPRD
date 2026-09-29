"""Lease abstracts, the premises lifecycle and the prohibited-use screen."""
from flask import Blueprint

import engine
import validate as v
from crud import apply_filters, base, paginate, resolve, strip
from db import store
from errors import ApiError
from middleware import (LIST_READ_ROLES, SINGLE_READ_ROLES, authorize,
                        tenant_scope_lease)
from response import created, listing, ok
from util import D, as_date, q2

bp = Blueprint("leases", __name__)

PARCEL_KINDS = ("INLINE", "ANCHOR_BOX", "PAD")


def get_lease(lease_id):
    return resolve(store.leases, lease_id, "ERR_LEASE_NOT_FOUND")


def get_center(center_id):
    return resolve(store.centers, center_id, "ERR_CENTER_NOT_FOUND")


def suite_taken(center_id, suite_code, exclude_lease_id=None):
    for lease in engine.leases_of_center(center_id):
        if lease["id"] == exclude_lease_id:
            continue
        if lease["suite_code"] == suite_code \
                and lease["premises_status"] != "TERMINATED":
            return True
    return False


@bp.post("/centers/<center_id>/leases")
def create_lease(center_id):
    authorize(["LeaseAdministrator"])
    body = v.body()
    tenant_id = v.req_str(body, "tenant_id")
    suite_code = v.req_str(body, "suite_code")
    gla_sqft = v.req_int(body, "gla_sqft", exclusive_min=0)
    parcel_kind = v.req_enum(body, "parcel_kind", PARCEL_KINDS)
    primary_use_code = v.req_str(body, "primary_use_code")
    base_rent = v.req_int(body, "base_rent_monthly_cents", exclusive_min=0)
    commencement_date = v.req_date(body, "commencement_date")
    expiration_date = v.req_date(body, "expiration_date")
    incidental = v.opt_str_list(body, "incidental_use_codes", default=[])
    incidental_pct = v.opt_pct(body, "projected_incidental_sales_pct", default=D(0))
    replacement_for = v.opt_id(body, "replacement_for_lease_id")
    if as_date(expiration_date) <= as_date(commencement_date):
        raise ApiError("ERR_INVALID_REQUEST",
                       "expiration_date must be strictly after commencement_date")

    center = get_center(center_id)
    resolve(store.tenants, tenant_id, "ERR_TENANT_NOT_FOUND")
    if replacement_for is not None:
        resolve(store.leases, replacement_for, "ERR_LEASE_NOT_FOUND")

    if suite_taken(center["id"], suite_code):
        raise ApiError("ERR_SUITE_ALREADY_LEASED")

    lease = base(engine.stamp())
    lease.update({
        "center_id": center["id"],
        "tenant_id": tenant_id,
        "replacement_for_lease_id": replacement_for,
        "suite_code": suite_code,
        "gla_sqft": gla_sqft,
        "parcel_kind": parcel_kind,
        "is_anchor": parcel_kind == "ANCHOR_BOX",
        "primary_use_code": primary_use_code,
        "incidental_use_codes": incidental,
        "projected_incidental_sales_pct": q2(incidental_pct),
        "base_rent_monthly_cents": base_rent,
        "commencement_date": commencement_date,
        "expiration_date": expiration_date,
        "premises_status": "DRAFT",
        "remedy_status": "NONE",
        "use_compliance_status": "CLEAR",
        "opened_at": None,
        "dark_since": None,
        "remedy_eligible_at": None,
        "effective_rent_monthly_cents": base_rent,
        "total_abated_cents": 0,
    })
    store.leases[lease["id"]] = lease
    # a DRAFT lease sits outside the occupancy population: no center field moves
    return created(strip(lease))


@bp.get("/leases/<lease_id>")
def read_lease(lease_id):
    authorize(SINGLE_READ_ROLES)
    return ok(strip(get_lease(lease_id)))


@bp.get("/leases")
def list_leases():
    authorize(LIST_READ_ROLES)
    limit, offset = v.pagination()
    records = engine._ordered(list(store.leases.values()))
    records = apply_filters(records, [
        ("center_id", v.filter_value("center_id")),
        ("tenant_id", v.filter_value("tenant_id")),
        ("replacement_for_lease_id", v.filter_value("replacement_for_lease_id")),
        ("premises_status", v.filter_value("premises_status")),
        ("remedy_status", v.filter_value("remedy_status")),
        ("parcel_kind", v.filter_value("parcel_kind")),
    ])
    page, total = paginate(records, limit, offset)
    return listing([strip(r) for r in page], limit, offset, total)


@bp.post("/leases/<lease_id>/screen-use")
def screen_use(lease_id):
    authorize(["LeaseAdministrator", "ComplianceOfficer"])
    v.body()
    lease = get_lease(lease_id)
    return ok(engine.screen_use(lease))


@bp.post("/leases/<lease_id>/execute")
def execute_lease(lease_id):
    authorize(["LeaseAdministrator"])
    v.body()
    lease = get_lease(lease_id)
    center = engine.center_of_lease(lease)

    # rung 9 outranks rung 14 (pinned collision)
    if center["compliance_posture"] == "FROZEN":
        raise ApiError("ERR_CENTER_EXECUTION_FROZEN")
    if lease["premises_status"] != "DRAFT":
        raise ApiError("ERR_LEASE_STATE_INVALID")
    if engine.screen_use(lease)["decision"] == "CONFLICT":
        raise ApiError("ERR_EXCLUSIVE_USE_CONFLICT")
    if suite_taken(center["id"], lease["suite_code"], exclude_lease_id=lease["id"]):
        raise ApiError("ERR_SUITE_ALREADY_LEASED")

    lease["premises_status"] = "EXECUTED"
    engine.touch_lease(lease)
    engine.recompute_center_derived(center)
    for cond in engine.conditions_of_lease(lease["id"]):
        if cond["condition_kind"] == "OPENING":
            engine.evaluate_condition(cond, "LIVE_STRICT")
    engine.bump_center(center)
    return ok(strip(lease))


@bp.post("/leases/<lease_id>/open")
def open_lease(lease_id):
    role, user_id = authorize(["LeaseAdministrator", "TenantRep"])
    v.body()
    lease = get_lease(lease_id)
    tenant_scope_lease(role, user_id, lease)
    center = engine.center_of_lease(lease)

    if lease["premises_status"] != "EXECUTED":
        raise ApiError("ERR_LEASE_STATE_INVALID")

    measurement = engine.latest_certified_measurement(center["id"])
    source = "CERTIFIED_MEASUREMENT" if measurement is not None else "LIVE_STRICT"
    pct, stores, anchors, variant, at_instant = engine.condition_figures(
        source, center, measurement)
    for cond in engine.conditions_of_lease(lease["id"]):
        if cond["condition_kind"] != "OPENING" or cond["status"] == "WAIVED":
            continue
        if not engine.condition_satisfied(cond, pct, stores, anchors, variant,
                                          at_instant):
            raise ApiError("ERR_LEASE_STATE_INVALID",
                           "An OPENING co-tenancy condition is not satisfied")

    lease["premises_status"] = "OPEN"
    lease["opened_at"] = engine.stamp()
    lease["dark_since"] = None
    engine.touch_lease(lease)
    engine.recompute_center_derived(center)
    engine.evaluate_center_conditions(center, "LIVE_STRICT", kinds=("ONGOING",))
    engine.bump_center(center)
    return ok(strip(lease))


@bp.post("/leases/<lease_id>/go-dark")
def go_dark(lease_id):
    role, user_id = authorize(["LeaseAdministrator", "TenantRep"])
    v.body()
    lease = get_lease(lease_id)
    tenant_scope_lease(role, user_id, lease)
    if lease["premises_status"] != "OPEN":
        raise ApiError("ERR_LEASE_STATE_INVALID")
    center = engine.center_of_lease(lease)

    # hop 1
    lease["premises_status"] = "DARK"
    lease["dark_since"] = engine.stamp()
    engine.touch_lease(lease)
    # hop 2
    engine.recompute_center_derived(center)
    # hops 3-5 (evaluation grants eligibility and cascades certificate staleness)
    engine.evaluate_center_conditions(center, "LIVE_STRICT", kinds=("ONGOING",))
    engine.bump_center(center)
    return ok(strip(lease))


@bp.post("/leases/<lease_id>/reopen")
def reopen(lease_id):
    role, user_id = authorize(["LeaseAdministrator", "TenantRep"])
    v.body()
    lease = get_lease(lease_id)
    tenant_scope_lease(role, user_id, lease)
    if lease["premises_status"] != "DARK":
        raise ApiError("ERR_LEASE_STATE_INVALID")
    tenant = store.tenants.get(lease["tenant_id"]) or {}
    if tenant.get("status") == "BANKRUPT":
        raise ApiError("ERR_LEASE_STATE_INVALID",
                       "A bankrupt tenant's premises cannot be reopened")
    center = engine.center_of_lease(lease)

    lease["premises_status"] = "OPEN"
    lease["opened_at"] = engine.stamp()
    lease["dark_since"] = None
    engine.touch_lease(lease)
    engine.recompute_center_derived(center)
    engine.evaluate_center_conditions(center, "LIVE_STRICT", kinds=("ONGOING",))
    engine.bump_center(center)
    return ok(strip(lease))


@bp.post("/leases/<lease_id>/terminate")
def terminate(lease_id):
    authorize(["AssetManager"])
    body = v.body()
    v.opt_str(body, "termination_reason_code")
    lease = get_lease(lease_id)
    if lease["premises_status"] not in ("EXECUTED", "OPEN", "DARK"):
        raise ApiError("ERR_LEASE_STATE_INVALID")
    center = engine.center_of_lease(lease)
    engine.terminate_lease_cascade(lease, by_remedy=False)
    engine.bump_center(center)
    return ok(strip(lease))
