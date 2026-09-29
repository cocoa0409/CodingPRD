"""Site, secure print release and parts-locker endpoints (PRD 3.2)."""
from flask import Blueprint

import derive
import serialize
import validation as v
from auth import require
from envelope import created, ok, ok_list
from errors import fail
from resolve import get_contract, get_site
from store import db, new_row, touch

bp = Blueprint("sites", __name__)

RELEASE_METHODS = ("NONE", "BADGE", "PIN")
PROBE_RESULTS = ("PASS", "DEFERRED", "FAIL")


@bp.post("/sites")
def create_site():
    require("AccountManager")
    body = v.body()
    contract_id = v.id_field(body, "contract_id")
    name = v.string_field(body, "name")
    region = v.string_field(body, "address_region", upper_case=True)
    cap = v.int_field(body, "toner_unit_cap", required=False, minimum=1, default=4)
    vlan = v.int_field(body, "network_vlan_tag", required=False,
                       minimum=1, maximum=4094, default=None)
    contract = get_contract(contract_id)

    row = new_row()
    row.update({
        "contract_id": contract["id"],
        "name": name,
        "address_region": region,
        "secure_release_state": "UNCONFIGURED",
        "release_method": "NONE",
        "network_vlan_tag": vlan,
        "toner_unit_cap": cap,
    })
    db.sites[row["id"]] = row
    return created(serialize.site(row))


@bp.get("/sites/<site_id>")
def read_site(site_id):
    require("AccountManager", "BillingAnalyst", "FleetOpsController",
            "FieldTechnician", "CustomerAdmin")
    site = get_site(site_id)
    return ok(serialize.site(site))


@bp.get("/sites")
def list_sites():
    require("AccountManager", "BillingAnalyst", "FleetOpsController")
    rows = db.sorted_rows("sites")
    contract_id = v.query_filter("contract_id")
    if contract_id is not None:
        rows = [s for s in rows if s["contract_id"] == contract_id]
    state = v.query_filter("secure_release_state")
    if state is not None:
        rows = [s for s in rows if s["secure_release_state"] == state]
    data, meta = v.paginate(rows, serialize.site)
    return ok_list(data, meta)


@bp.post("/sites/<site_id>/secure-release-config")
def secure_release_config(site_id):
    user_id, _role = require("CustomerAdmin")
    site = get_site(site_id)
    body = v.body()
    method = v.enum_field(body, "release_method", RELEASE_METHODS)
    probe = v.enum_field(body, "probe_result", PROBE_RESULTS)
    vlan = v.int_field(body, "network_vlan_tag", required=False,
                       minimum=1, maximum=4094, default=None)
    if probe in ("PASS", "DEFERRED") and method not in ("BADGE", "PIN"):
        fail("ERR_INVALID_REQUEST",
             "A %s probe requires release_method BADGE or PIN." % probe)
    if probe == "PASS" and vlan is None:
        fail("ERR_INVALID_REQUEST", "A PASS probe requires network_vlan_tag.")
    if user_id != site["id"]:
        fail("ERR_SITE_OWNERSHIP_REQUIRED",
             "A CustomerAdmin may only configure its own site.")

    if probe == "PASS":
        site["release_method"] = method
        site["network_vlan_tag"] = vlan
        site["secure_release_state"] = "CONFIGURED"
        touch(site)
        for device in db.sorted_rows("devices"):
            if device["site_id"] != site["id"]:
                continue
            if device["lifecycle_state"] != "NETWORKED":
                continue
            device["secure_release_enrolled"] = True
            touch(device)
    elif probe == "DEFERRED":
        site["release_method"] = method
        if vlan is not None:
            site["network_vlan_tag"] = vlan
        site["secure_release_state"] = "PENDING_VALIDATION"
        touch(site)
    else:
        site["secure_release_state"] = "FAILED"
        touch(site)
    return ok(serialize.site(site))


@bp.post("/sites/<site_id>/spare-part-stocks")
def adjust_stock(site_id):
    require("FleetOpsController")
    site = get_site(site_id)
    body = v.body()
    part_sku = v.string_field(body, "part_sku")
    qty_delta = v.int_field(body, "qty_delta")

    row = derive.stock_row(site["id"], part_sku)
    current = row["on_hand_qty"] if row is not None else 0
    if qty_delta == 0:
        fail("ERR_PART_STOCK_UNDERFLOW", "Field 'qty_delta' must not be zero.")
    if current + qty_delta < 0:
        fail("ERR_PART_STOCK_UNDERFLOW",
             "The adjustment would drive on_hand_qty below zero.")

    if row is None:
        row = new_row()
        row.update({
            "site_id": site["id"],
            "part_sku": part_sku,
            "on_hand_qty": qty_delta,
        })
        db.stocks[row["id"]] = row
    else:
        row["on_hand_qty"] = current + qty_delta
        touch(row)
    return ok(serialize.stock(row))


@bp.get("/sites/<site_id>/spare-part-stocks")
def list_stocks(site_id):
    require("FleetOpsController", "FieldTechnician", "AccountManager")
    site = get_site(site_id)
    rows = [s for s in db.sorted_rows("stocks") if s["site_id"] == site["id"]]
    part_sku = v.query_filter("part_sku")
    if part_sku is not None:
        rows = [s for s in rows if s["part_sku"] == part_sku]
    data, meta = v.paginate(rows, serialize.stock)
    return ok_list(data, meta)
