"""Source tagging: encoding, receipt and read-quality verification (PRD 3.3)."""

from flask import Blueprint

import calc
from db import db, new_id
from errors import ApiError
from middleware import (acting_role, acting_user, require_read, require_roles,
                        scope_store, scope_vendor)
from response import created, ok, ok_list, paginate, read_pagination
from validate import S, body_json, filter_enum, filter_str, lookup, parse_body

bp = Blueprint("tags", __name__)
PREFIX = "/inventory-integrity"

TAG_BATCH_STATUSES = ("DRAFT", "ENCODED", "RECEIVED", "VERIFICATION_FAILED",
                      "VERIFIED_PASS", "SCRAPPED")
BATCH_ENCODING_SCHEMES = ("SGTIN_96", "SGTIN_198")


def _list(collection, predicates):
    matched = [r for r in getattr(db, collection).values()
               if all(r.get(key) == value for key, value in predicates)]
    limit, offset = read_pagination()
    page, total = paginate(calc.newest_first(matched), limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post(PREFIX + "/tag-batches")
def create_tag_batch():
    require_roles("VendorRep", "SystemAdmin")
    body = body_json()
    # Identity scope (tier 3) precedes body foreign-key resolution (tier 5).
    if acting_role() == "VendorRep":
        scope_vendor(body.get("vendor_id"))
    vendor = lookup("vendors", body.get("vendor_id"))
    item = lookup("items", body.get("item_id"))
    store = lookup("stores", body.get("destination_store_id"))
    data = parse_body(body, [S("quantity_encoded", "int", min=1)])
    row = calc.base_row({"id": new_id()})
    record = {
        "id": row["id"],
        "vendor_id": vendor["id"],
        "item_id": item["id"],
        "destination_store_id": store["id"],
        "encoding_scheme": None,
        "epc_prefix": None,
        "quantity_encoded": data["quantity_encoded"],
        "status": "DRAFT",
        "rework_round": 0,
        "required_sample_units": 0,
        "sampled_units": 0,
        "readable_units": 0,
        "duplicate_epc_count": 0,
        "unencoded_units": 0,
        "read_rate_bps": 0,
        "verification_outcome": None,
    }
    record.update({k: row[k] for k in ("created_at", "updated_at", "version", "_seq")})
    db.tag_batches[record["id"]] = record
    return created(record)


@bp.get(PREFIX + "/tag-batches/<tag_batch_id>")
def get_tag_batch(tag_batch_id):
    require_read()
    return ok(lookup("tag_batches", tag_batch_id))


@bp.get(PREFIX + "/tag-batches")
def list_tag_batches():
    require_read()
    status = filter_enum("status", TAG_BATCH_STATUSES)
    predicates = []
    for param in ("vendor_id", "item_id", "destination_store_id"):
        value = filter_str(param)
        if value is not None:
            predicates.append((param, value))
    if status is not None:
        predicates.append(("status", status))
    return _list("tag_batches", predicates)


def _bad_state(message):
    raise ApiError("ERR_TAG_BATCH_INVALID_STATE", message)


def _freeze_sample(batch):
    vendor = db.vendors[batch["vendor_id"]]
    batch["required_sample_units"] = calc.required_sample_units(
        batch["quantity_encoded"], vendor["required_verification_sample_pct"])


@bp.post(PREFIX + "/tag-batches/<tag_batch_id>/encode")
def encode_tag_batch(tag_batch_id):
    require_roles("VendorRep", "SystemAdmin")
    batch = lookup("tag_batches", tag_batch_id)
    scope_vendor(batch["vendor_id"])
    data = parse_body(body_json(), [
        S("epc_prefix", "digits"),
        S("encoding_scheme", "enum", allowed=BATCH_ENCODING_SCHEMES),
    ])
    if batch["status"] != "DRAFT":
        _bad_state("only a DRAFT batch may be encoded")
    item = db.items[batch["item_id"]]
    if (data["encoding_scheme"] != item["tag_encoding_scheme"]
            or len(data["epc_prefix"]) != item["epc_prefix_length"]):
        raise ApiError("ERR_TAG_SCHEME_MISMATCH",
                       "encoding scheme or EPC prefix length does not match the SKU")
    batch["encoding_scheme"] = data["encoding_scheme"]
    batch["epc_prefix"] = data["epc_prefix"]
    batch["status"] = "ENCODED"
    _freeze_sample(batch)
    calc.touch(batch)
    return ok(batch)


@bp.post(PREFIX + "/tag-batches/<tag_batch_id>/receive")
def receive_tag_batch(tag_batch_id):
    require_roles("StoreOps", "InventorySupervisor")
    batch = lookup("tag_batches", tag_batch_id)
    scope_store(batch["destination_store_id"])
    parse_body(body_json(), [])
    if batch["status"] != "ENCODED":
        _bad_state("only an ENCODED batch may be received")
    batch["status"] = "RECEIVED"
    calc.touch(batch)
    return ok(batch)


VERIFY_SPECS = [
    S("sampled_units", "int", min=0),
    S("readable_units", "int", min=0),
    S("duplicate_epc_count", "int", min=0),
    S("unencoded_units", "int", min=0),
]


@bp.post(PREFIX + "/tag-batches/<tag_batch_id>/verify")
def verify_tag_batch(tag_batch_id):
    require_roles("StoreOps", "InventorySupervisor")
    batch = lookup("tag_batches", tag_batch_id)
    scope_store(batch["destination_store_id"])
    data = parse_body(body_json(), VERIFY_SPECS)
    if batch["status"] != "RECEIVED":
        _bad_state("only a RECEIVED batch may be verified")
    if data["sampled_units"] < batch["required_sample_units"]:
        raise ApiError("ERR_SAMPLE_BELOW_REQUIRED",
                       "sampled_units is below the frozen required_sample_units")
    if (data["readable_units"] > data["sampled_units"]
            or data["unencoded_units"] > data["sampled_units"]
            or data["readable_units"] + data["unencoded_units"] > data["sampled_units"]):
        raise ApiError("ERR_INVALID_VERIFICATION_COUNTS",
                       "the submitted sample counts are not internally coherent")

    batch["sampled_units"] = data["sampled_units"]
    batch["readable_units"] = data["readable_units"]
    batch["duplicate_epc_count"] = data["duplicate_epc_count"]
    batch["unencoded_units"] = data["unencoded_units"]
    batch["read_rate_bps"] = calc.read_rate_bps(data["readable_units"], data["sampled_units"])
    outcome = calc.tag_verification_outcome(batch["read_rate_bps"],
                                            data["duplicate_epc_count"],
                                            data["unencoded_units"])
    batch["verification_outcome"] = outcome
    vendor = db.vendors[batch["vendor_id"]]
    position = calc.position_for(batch["destination_store_id"], batch["item_id"])
    if outcome == "PASS":
        batch["status"] = "VERIFIED_PASS"
        calc.touch(batch)
        calc.apply_vendor_score(vendor, calc.TAG_PASS_REWARD_BPS)
        calc.touch(vendor)
        if position is not None:
            position["tag_integrity_hold"] = False
            calc.settle([position["id"]])
    else:
        batch["status"] = "VERIFICATION_FAILED"
        calc.touch(batch)
        calc.apply_vendor_score(vendor, -calc.TAG_FAIL_PENALTY_BPS)
        calc.touch(vendor)
        if position is not None:
            position["tag_integrity_hold"] = True
            calc.settle([position["id"]])
    return ok(batch)


@bp.post(PREFIX + "/tag-batches/<tag_batch_id>/rework")
def rework_tag_batch(tag_batch_id):
    require_roles("VendorRep", "InventorySupervisor")
    batch = lookup("tag_batches", tag_batch_id)
    scope_vendor(batch["vendor_id"])
    parse_body(body_json(), [])
    if batch["status"] != "VERIFICATION_FAILED":
        _bad_state("only a VERIFICATION_FAILED batch may be reworked")
    if batch["rework_round"] >= calc.MAX_REWORK_ROUNDS:
        raise ApiError("ERR_REWORK_LIMIT_REACHED",
                       "the batch has already exhausted its rework rounds")
    batch["rework_round"] += 1
    batch["status"] = "ENCODED"
    batch["sampled_units"] = 0
    batch["readable_units"] = 0
    batch["duplicate_epc_count"] = 0
    batch["unencoded_units"] = 0
    batch["read_rate_bps"] = 0
    batch["verification_outcome"] = None
    _freeze_sample(batch)
    calc.touch(batch)
    return ok(batch)


@bp.post(PREFIX + "/tag-batches/<tag_batch_id>/scrap")
def scrap_tag_batch(tag_batch_id):
    require_roles("InventorySupervisor", "ShrinkController")
    batch = lookup("tag_batches", tag_batch_id)
    parse_body(body_json(), [S("note", "str", required=False, max_len=2000)])
    if batch["status"] != "VERIFICATION_FAILED":
        _bad_state("only a VERIFICATION_FAILED batch may be scrapped")
    batch["status"] = "SCRAPPED"
    # PRD 3.3: scrapping does NOT clear the position's tag_integrity_hold.
    calc.touch(batch)
    return ok(batch)
