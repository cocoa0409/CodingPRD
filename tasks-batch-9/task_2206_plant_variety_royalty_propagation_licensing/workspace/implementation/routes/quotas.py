"""Production quotas, traceability tag orders and the committed-unit invariant."""

from flask import Blueprint

from common import (check_occ, filtered, require_agreement_active, require_owner,
                    require_quota_not_frozen, resolve, terminal, transition)
from derive import (TAG_COMMITTED, apply, children, recompute_quota_inventory)
from errors import ApiError
from middleware import (ALL_ROLES, LICENSING_OFFICER, PROPAGATOR, endpoint)
from response import collection, created, ok
from store import new_id, store
from validation import ID, Enum, Int, Str, TERRITORY

bp = Blueprint("quotas", __name__)

TAG_ORDER_TERMINAL = ("RECONCILED", "VOIDED")

QUOTA_SCHEMA = [
    ("agreement_id", ID, True),
    ("variety_id", ID, True),
    ("season_code", Str(4, 8), True),
    ("basis", Enum(["PER_PLANT", "PER_ACRE"]), False),
    ("territory_code", TERRITORY, True),
    ("territory_class", Enum(["DOMESTIC", "EXPORT"]), False),
    ("allocated_units", Int(1), True),
]

TAG_ORDER_SCHEMA = [
    ("quota_id", ID, True),
    ("requested_units", Int(1), True),
    ("expected_quota_version", Int(0), True),
]

RECONCILE_SCHEMA = [
    ("activated_units", Int(0), True),
]


@endpoint(bp, "POST", "/production-quotas", [LICENSING_OFFICER], QUOTA_SCHEMA)
def create_quota(actor, body):
    agreement = resolve("agreement_id", body["agreement_id"])
    variety = resolve("variety_id", body["variety_id"])
    require_agreement_active(agreement)
    if body["territory_code"] not in agreement["territory_codes"]:
        raise ApiError("ERR_TERRITORY_NOT_LICENSED")
    for other in children("quotas", "agreement_id", agreement["id"]):
        if (other["variety_id"] == variety["id"]
                and other["season_code"] == body["season_code"]
                and other["territory_code"] == body["territory_code"]
                and other["status"] in ("ACTIVE", "FROZEN")):
            raise ApiError("ERR_DUPLICATE_QUOTA_SEASON")
    record = {
        "id": new_id(),
        "agreement_id": agreement["id"],
        "variety_id": variety["id"],
        "season_code": body["season_code"],
        "basis": body["basis"] or variety["royalty_basis_default"],
        "territory_code": body["territory_code"],
        "territory_class": body["territory_class"] or "DOMESTIC",
        "allocated_units": body["allocated_units"],
        "status": "ACTIVE",
        "tags_committed_units": 0,
        "units_available": body["allocated_units"],
        "tags_activated_units": 0,
    }
    store.stamp_new(record)
    store.quotas[record["id"]] = record
    return created(record)


@endpoint(bp, "GET", "/production-quotas", ALL_ROLES)
def list_quotas(actor):
    records, limit, offset, total = filtered(
        "quotas", "agreement_id", "variety_id", "status", "season_code")
    return collection(records, limit, offset, total)


@endpoint(bp, "GET", "/production-quotas/<quota_id>", ALL_ROLES)
def get_quota(actor, quota_id):
    return ok(resolve("quota_id", quota_id))


# ---------------------------------------------------------------- tag orders
@endpoint(bp, "POST", "/tag-orders", [PROPAGATOR], TAG_ORDER_SCHEMA)
def create_tag_order(actor, body):
    quota = resolve("quota_id", body["quota_id"])
    agreement = store.agreements[quota["agreement_id"]]
    require_owner(actor, agreement["propagator_id"])
    check_occ(body, "expected_quota_version", quota, "ERR_STALE_QUOTA_VERSION")
    terminal(quota["status"] == "CLOSED")
    require_quota_not_frozen(quota)
    require_agreement_active(agreement)
    record = {
        "id": new_id(),
        "quota_id": quota["id"],
        "requested_units": body["requested_units"],
        "serial_prefix": None,
        "status": "REQUESTED",
        "activated_units": 0,
        "voided_units": 0,
        "issued_at": None,
    }
    store.stamp_new(record)
    store.tag_orders[record["id"]] = record
    # A REQUESTED order commits nothing, yet the quota still moves so the next
    # requester's expected_quota_version must be refreshed (PRD 3.6).
    apply(quota, None, force=True)
    return created(record)


@endpoint(bp, "GET", "/tag-orders", ALL_ROLES)
def list_tag_orders(actor):
    records, limit, offset, total = filtered("tag_orders", "quota_id", "status")
    return collection(records, limit, offset, total)


@endpoint(bp, "GET", "/tag-orders/<tag_order_id>", ALL_ROLES)
def get_tag_order(actor, tag_order_id):
    return ok(resolve("tag_order_id", tag_order_id))


@endpoint(bp, "POST", "/tag-orders/<tag_order_id>/issue", [LICENSING_OFFICER], [])
def issue_tag_order(actor, body, tag_order_id):
    order = resolve("tag_order_id", tag_order_id)
    terminal(order["status"] in TAG_ORDER_TERMINAL)
    transition(order["status"] == "REQUESTED")
    quota = store.quotas[order["quota_id"]]
    require_quota_not_frozen(quota)
    agreement = store.agreements[quota["agreement_id"]]
    require_agreement_active(agreement)
    recompute_quota_inventory(quota)
    if int(order["requested_units"]) > int(quota["units_available"]):
        raise ApiError("ERR_QUOTA_UNITS_EXCEEDED")
    variety = store.varieties[quota["variety_id"]]
    ordinal = 0
    for other in children("tag_orders", "quota_id", quota["id"]):
        if other["status"] in TAG_COMMITTED:
            ordinal += 1
    serial_prefix = "%s-%s-%04d" % (
        variety["breeder_code"], quota["season_code"], ordinal + 1)
    apply(order, {
        "status": "ISSUED",
        "serial_prefix": serial_prefix,
        "issued_at": store.now_iso(),
    }, force=True)
    recompute_quota_inventory(quota, force=True)
    return ok(order)


@endpoint(bp, "POST", "/tag-orders/<tag_order_id>/reconcile", [PROPAGATOR],
          RECONCILE_SCHEMA)
def reconcile_tag_order(actor, body, tag_order_id):
    order = resolve("tag_order_id", tag_order_id)
    quota = store.quotas[order["quota_id"]]
    agreement = store.agreements[quota["agreement_id"]]
    require_owner(actor, agreement["propagator_id"])
    terminal(order["status"] in TAG_ORDER_TERMINAL)
    transition(order["status"] == "ISSUED")
    if int(body["activated_units"]) > int(order["requested_units"]):
        raise ApiError("ERR_ACTIVATION_EXCEEDS_ISSUED")
    apply(order, {
        "status": "RECONCILED",
        "activated_units": int(body["activated_units"]),
    }, force=True)
    recompute_quota_inventory(quota, force=True)
    return ok(order)


@endpoint(bp, "POST", "/tag-orders/<tag_order_id>/void", [LICENSING_OFFICER], [])
def void_tag_order(actor, body, tag_order_id):
    order = resolve("tag_order_id", tag_order_id)
    terminal(order["status"] in TAG_ORDER_TERMINAL)
    transition(order["status"] in ("REQUESTED", "ISSUED"))
    quota = store.quotas[order["quota_id"]]
    apply(order, {
        "status": "VOIDED",
        "voided_units": int(order["requested_units"]),
    }, force=True)
    recompute_quota_inventory(quota, force=True)
    return ok(order)
