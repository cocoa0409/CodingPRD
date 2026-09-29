"""Device fleet endpoints (PRD 3.3)."""
from flask import Blueprint

import derive
import serialize
import validation as v
from auth import require
from envelope import created, ok, ok_list
from errors import fail
from resolve import get_contract, get_device, get_site
from store import db, new_row, touch

bp = Blueprint("devices", __name__)

REFRESH_SUCCESSOR_STATES = ("ASSESSED", "PLACED", "NETWORKED", "ACTIVE")


@bp.post("/devices")
def create_device():
    require("FleetOpsController")
    body = v.body()
    contract_id = v.id_field(body, "contract_id")
    site_id = v.id_field(body, "site_id")
    asset_tag = v.string_field(body, "asset_tag")
    model_code = v.string_field(body, "model_code")
    duty_cycle = v.int_field(body, "rated_monthly_duty_cycle", minimum=1)
    assessed_mono = v.int_field(body, "assessed_monthly_mono_pages", minimum=0)
    assessed_color = v.int_field(body, "assessed_monthly_color_pages", minimum=0)
    baseline_cost = v.int_field(body, "baseline_cost_micro_dollars_per_page", minimum=1)
    baseline_overhead = v.int_field(body, "baseline_overhead_cents_per_month", minimum=0)
    color_capable = v.bool_field(body, "color_capable", default=False)

    contract = get_contract(contract_id)
    site = get_site(site_id)

    for device in derive.contract_devices(contract["id"]):
        if device["asset_tag"] == asset_tag:
            fail("ERR_ASSET_TAG_DUPLICATE",
                 "asset_tag '%s' already exists on this contract." % asset_tag)

    row = new_row()
    row.update({
        "contract_id": contract["id"],
        "site_id": site["id"],
        "asset_tag": asset_tag,
        "model_code": model_code,
        "color_capable": color_capable,
        "rated_monthly_duty_cycle": duty_cycle,
        "lifecycle_state": "ASSESSED",
        "supply_state": "SUPPLY_OK",
        "toner_level_pct": 100,
        "last_accepted_mono_meter": 0,
        "last_accepted_color_meter": 0,
        "last_read_at": None,
        "secure_release_enrolled": False,
        "assessed_monthly_mono_pages": assessed_mono,
        "assessed_monthly_color_pages": assessed_color,
        "baseline_cost_micro_dollars_per_page": baseline_cost,
        "baseline_overhead_cents_per_month": baseline_overhead,
        "right_sizing_action": "NONE",
        "refresh_due": False,
        "replaced_by_device_id": None,
        "removal_order_id": None,
    })
    db.devices[row["id"]] = row
    return created(serialize.device(row))


@bp.get("/devices/<device_id>")
def read_device(device_id):
    require("AccountManager", "BillingAnalyst", "FleetOpsController",
            "FieldTechnician", "CustomerAdmin")
    device = get_device(device_id)
    return ok(serialize.device(device))


@bp.get("/devices")
def list_devices():
    require("AccountManager", "BillingAnalyst", "FleetOpsController", "FieldTechnician")
    rows = db.sorted_rows("devices")
    for field in ("contract_id", "site_id", "replaced_by_device_id", "removal_order_id",
                  "lifecycle_state", "supply_state"):
        value = v.query_filter(field)
        if value is not None:
            rows = [d for d in rows if d[field] == value]
    data, meta = v.paginate(rows, serialize.device)
    return ok_list(data, meta)


@bp.post("/devices/<device_id>/place")
def place_device(device_id):
    require("FieldTechnician")
    device = get_device(device_id)
    v.body()
    if device["lifecycle_state"] != "ASSESSED":
        fail("ERR_DEVICE_INVALID_STATE",
             "A device in %s cannot be placed." % device["lifecycle_state"])
    contract = derive.device_contract(device)
    if contract is None or contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", "The governing contract is not ACTIVE.")
    device["lifecycle_state"] = "PLACED"
    touch(device)
    return ok(serialize.device(device))


@bp.post("/devices/<device_id>/network-integration")
def network_integrate_device(device_id):
    require("FieldTechnician")
    device = get_device(device_id)
    v.body()
    if device["lifecycle_state"] != "PLACED":
        fail("ERR_DEVICE_INVALID_STATE",
             "A device in %s cannot be network-integrated." % device["lifecycle_state"])
    site = derive.device_site(device)
    if site is None or site["network_vlan_tag"] is None:
        fail("ERR_DEVICE_INVALID_STATE",
             "The hosting site has no network_vlan_tag assigned.")
    device["lifecycle_state"] = "NETWORKED"
    device["secure_release_enrolled"] = site["release_method"] in ("BADGE", "PIN")
    touch(device)
    return ok(serialize.device(device))


@bp.post("/devices/<device_id>/activate")
def activate_device(device_id):
    require("FleetOpsController")
    device = get_device(device_id)
    v.body()
    if device["lifecycle_state"] != "NETWORKED":
        fail("ERR_DEVICE_INVALID_STATE",
             "A device in %s cannot be activated." % device["lifecycle_state"])
    contract = derive.device_contract(device)
    if contract is None or contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", "The governing contract is not ACTIVE.")
    site = derive.device_site(device)
    if site is None or site["secure_release_state"] != "CONFIGURED":
        fail("ERR_SECURE_RELEASE_NOT_CONFIGURED",
             "The hosting site's secure print release is not CONFIGURED.")
    device["lifecycle_state"] = "ACTIVE"
    touch(device)
    return ok(serialize.device(device))


@bp.post("/devices/<device_id>/refresh-replacement")
def refresh_replacement(device_id):
    require("AccountManager")
    device = get_device(device_id)
    body = v.body()
    successor_id = v.id_field(body, "successor_device_id")
    successor = get_device(successor_id)

    if not device["refresh_due"]:
        fail("ERR_DEVICE_NOT_REFRESH_DUE", "The device is not flagged refresh_due.")
    if device["replaced_by_device_id"] is not None:
        fail("ERR_DEVICE_NOT_REFRESH_DUE", "The device already has a successor linked.")
    if successor["id"] == device["id"]:
        fail("ERR_DEVICE_NOT_REFRESH_DUE", "A device cannot replace itself.")
    if successor["contract_id"] != device["contract_id"]:
        fail("ERR_DEVICE_NOT_REFRESH_DUE",
             "The successor device belongs to a different contract.")
    if successor["lifecycle_state"] not in REFRESH_SUCCESSOR_STATES:
        fail("ERR_DEVICE_NOT_REFRESH_DUE",
             "A successor in %s cannot be linked." % successor["lifecycle_state"])

    device["replaced_by_device_id"] = successor["id"]
    touch(device)
    return ok(serialize.device(device))


@bp.get("/devices/<device_id>/statement-lines")
def list_device_statement_lines(device_id):
    require("BillingAnalyst", "AccountManager")
    device = get_device(device_id)
    rows = [l for l in db.lines.values() if l["device_id"] == device["id"]]
    rows.sort(key=lambda l: l["_seq"])
    page_class = v.query_filter("page_class")
    if page_class is not None:
        rows = [l for l in rows if l["page_class"] == page_class]
    data, meta = v.paginate(rows, serialize.statement_line)
    return ok_list(data, meta)
