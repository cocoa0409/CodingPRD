"""Reference spine: departments, categories, store clusters, vendors,
vendor authorizations and the logical-clock capability."""
from flask import Blueprint, request

from common import (F, ROLE_ADMIN, PLANNING_ROLES, ANY_ROLE, auth, fail,
                    page_of, pagination, parse_input, public, public_list,
                    parse_dt, iso_ms, respond)
import store
import svc
from store import db, make_row, touch

bp = Blueprint("ref", __name__)


def _filter(rows, name, key=None):
    value = request.args.get(name)
    if value is None:
        return rows
    field = key or name
    return [r for r in rows if r.get(field) == value]


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------
DEPARTMENT_FIELDS = [
    F("name", "str", min_len=1, max_len=120),
    F("code", "str", min_len=2, max_len=8, upper=True),
    F("fiscal_year", "int", minimum=2000, maximum=2100),
    F("sales_target_cents", "int", minimum=1),
    F("margin_target_bps", "int", minimum=0, maximum=9999),
    F("turn_target_x100", "int", minimum=1),
]


@bp.post("/otb/departments")
def create_department():
    auth([ROLE_ADMIN])
    data = parse_input(DEPARTMENT_FIELDS)
    for row in db.departments.values():
        if row["code"] == data["code"]:
            fail("ERR_INVALID_REQUEST", "code must be unique across departments")
    row = make_row(**data)
    db.departments[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/otb/departments/<rid>")
def read_department(rid):
    auth(PLANNING_ROLES)
    return respond(public(store.get_department(rid)))


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
CATEGORY_ROLES = ["TRAFFIC_DRIVER", "DESTINATION", "CONVENIENCE", "SEASONAL", "OCCASIONAL"]

CATEGORY_FIELDS = [
    F("department_id", "str", min_len=1),
    F("name", "str", min_len=1, max_len=120),
    F("code", "str", min_len=2, max_len=8, upper=True),
    F("role", "enum", enum=CATEGORY_ROLES),
    F("sales_share_bps", "int", minimum=1, maximum=10000),
]


@bp.post("/otb/categories")
def create_category():
    auth([ROLE_ADMIN])
    data = parse_input(CATEGORY_FIELDS)
    store.get_department(data["department_id"])
    for row in db.categories.values():
        if row["department_id"] == data["department_id"] and row["code"] == data["code"]:
            fail("ERR_INVALID_REQUEST", "code must be unique within the department")
    row = make_row(**data)
    db.categories[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/otb/categories/<rid>")
def read_category(rid):
    auth(PLANNING_ROLES)
    return respond(public(store.get_category(rid)))


@bp.get("/otb/categories")
def list_categories():
    auth(PLANNING_ROLES)
    limit, offset = pagination()
    rows = store.by_seq(list(db.categories.values()))
    rows = _filter(rows, "department_id")
    rows = _filter(rows, "role")
    window, meta = page_of(rows, limit, offset)
    return respond(public_list(window), 200, meta)


# ---------------------------------------------------------------------------
# Store clusters
# ---------------------------------------------------------------------------
CLUSTER_FIELDS = [
    F("name", "str", min_len=1, max_len=120),
    F("climate_zone", "enum", enum=["COLD", "TEMPERATE", "HOT"]),
    F("demographic_index_bps", "int", minimum=5000, maximum=20000),
    F("volume_tier", "enum", enum=["A", "B", "C"]),
    F("store_count", "int", minimum=1),
    F("sales_index_bps", "int", minimum=3000, maximum=25000),
]


@bp.post("/otb/store-clusters")
def create_cluster():
    auth([ROLE_ADMIN])
    data = parse_input(CLUSTER_FIELDS)
    row = make_row(**data)
    db.clusters[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/otb/store-clusters/<rid>")
def read_cluster(rid):
    auth(PLANNING_ROLES)
    return respond(public(store.get_cluster(rid)))


@bp.get("/otb/store-clusters")
def list_clusters():
    auth(PLANNING_ROLES)
    limit, offset = pagination()
    rows = store.by_seq(list(db.clusters.values()))
    rows = _filter(rows, "climate_zone")
    rows = _filter(rows, "volume_tier")
    window, meta = page_of(rows, limit, offset)
    return respond(public_list(window), 200, meta)


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------
VENDOR_FIELDS = [
    F("name", "str", min_len=1, max_len=160),
    F("code", "str", min_len=2, max_len=8, upper=True),
    F("lead_time_days", "int", minimum=1, maximum=365),
    F("weekly_unit_capacity", "int", minimum=1),
    F("min_order_units", "int", minimum=1),
    F("cancel_cutoff_days", "int", minimum=0, maximum=180),
]

VENDOR_TRANSITIONS = {
    "PENDING": ["AUTHORIZED"],
    "AUTHORIZED": ["SUSPENDED"],
    "SUSPENDED": ["AUTHORIZED"],
}


@bp.post("/otb/vendors")
def create_vendor():
    auth([ROLE_ADMIN])
    data = parse_input(VENDOR_FIELDS)
    for row in db.vendors.values():
        if row["code"] == data["code"]:
            fail("ERR_INVALID_REQUEST", "code must be unique across vendors")
    row = make_row(status="PENDING", **data)
    db.vendors[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/otb/vendors/<rid>")
def read_vendor(rid):
    auth(ANY_ROLE)
    return respond(public(store.get_vendor(rid)))


@bp.post("/otb/vendors/<rid>/status")
def set_vendor_status(rid):
    auth([ROLE_ADMIN])
    data = parse_input([F("status", "enum",
                          enum=["PENDING", "AUTHORIZED", "SUSPENDED"])])
    vendor = store.get_vendor(rid)
    target = data["status"]
    if target not in VENDOR_TRANSITIONS.get(vendor["status"], []):
        fail("ERR_INVALID_STATE",
             "a %s vendor cannot move to %s" % (vendor["status"], target))
    vendor["status"] = target
    if target == "SUSPENDED":
        for auth_row in store.by_seq(list(db.vauths.values())):
            if auth_row["vendor_id"] == vendor["id"] and auth_row["status"] == "ACTIVE":
                auth_row["status"] = "REVOKED"
                touch(auth_row)
    elif target == "AUTHORIZED":
        for auth_row in store.by_seq(list(db.vauths.values())):
            if auth_row["vendor_id"] == vendor["id"] and auth_row["status"] == "REVOKED":
                auth_row["status"] = "ACTIVE"
                touch(auth_row)
    touch(vendor)
    return respond(public(vendor))


# ---------------------------------------------------------------------------
# Vendor authorizations
# ---------------------------------------------------------------------------
VAUTH_FIELDS = [
    F("vendor_id", "str", min_len=1),
    F("category_id", "str", min_len=1),
    F("max_open_units", "int", minimum=1),
]


@bp.post("/otb/vendor-authorizations")
def create_vauth():
    auth([ROLE_ADMIN])
    data = parse_input(VAUTH_FIELDS)
    store.get_vendor(data["vendor_id"])
    store.get_category(data["category_id"])
    row = make_row(status="ACTIVE", **data)
    db.vauths[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/otb/vendor-authorizations/<rid>")
def read_vauth(rid):
    auth(PLANNING_ROLES)
    return respond(public(store.get_vauth(rid)))


@bp.get("/otb/vendor-authorizations")
def list_vauths():
    auth(PLANNING_ROLES)
    limit, offset = pagination()
    rows = store.by_seq(list(db.vauths.values()))
    rows = _filter(rows, "vendor_id")
    rows = _filter(rows, "category_id")
    rows = _filter(rows, "status")
    window, meta = page_of(rows, limit, offset)
    return respond(public_list(window), 200, meta)


# ---------------------------------------------------------------------------
# Logical clock (§2.6)
# ---------------------------------------------------------------------------
@bp.post("/otb/_clock/set_current_utc")
def set_clock():
    auth([ROLE_ADMIN])
    data = parse_input([F("to_iso8601", "datetime")])
    db.clock = parse_dt(data["to_iso8601"])
    expired = svc.expire_overlays_for_clock()
    return respond({"current_utc": iso_ms(db.clock),
                    "expired_overlay_count": expired})
