"""EMS / PCB Assembly REST API — entry point and all route handlers.

In-memory only. Starts empty on every boot. Nothing is seeded.
"""

import os

from flask import Flask, request

import calculations as calc
import db
import errors
import inventory as inv
import lookups as lk
import pagination as pg
import response as resp
import serializers as ser
import workflows as wf
from errors import ApiError
from middleware import authenticate, require_roles

app = Flask(__name__)
app.url_map.strict_slashes = False

ALL_ROLES = {"ProcessEngineer", "ProductionPlanner", "QualityEngineer"}

# Valid enum domains
PACKAGE_TYPES = {"0402", "0603", "0805", "SOT23", "QFN", "BGA", "THT"}
FAILURE_CLASSES = {"WORKMANSHIP", "COMPONENT", "DESIGN", "NO_FAULT_FOUND"}
TEST_RESULTS = {"PASS", "FAIL"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(exc):
    return resp.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    return resp.error(errors.ERR_NOT_FOUND, "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(exc):
    return resp.error(errors.ERR_NOT_FOUND, "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_uncaught(exc):
    if isinstance(exc, ApiError):
        return resp.error(exc.error_id, exc.message, exc.http_status)
    return resp.error(errors.ERR_VALIDATION, f"Unexpected error: {exc}", 422)


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------
def body():
    """Parse the JSON body; return {} when absent. Malformed JSON -> 400."""
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise errors.invalid_request(f"Missing required field: {f}")


def as_bool(data, key, default):
    if key not in data or data[key] is None:
        return default
    val = data[key]
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field '{key}' must be a boolean.")
    return val


def as_int(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {key}")
        return default
    val = data[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field '{key}' must be an integer.")
    return val


def as_str(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {key}")
        return default
    val = data[key]
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field '{key}' must be a string.")
    return val


def non_empty_str(data, key, required=True, default=None):
    val = as_str(data, key, required=required, default=default)
    if required and (val is None or val.strip() == ""):
        raise errors.invalid_request(f"Field '{key}' must be a non-empty string.")
    return val


# ===========================================================================
# PARTS
# ===========================================================================
@app.route("/parts", methods=["POST"])
def create_part():
    _, role = authenticate()
    require_roles(role, {"ProcessEngineer"})
    data = body()
    require_fields(data, ["internal_pn", "description", "package_type", "standard_cost_cents"])
    internal_pn = non_empty_str(data, "internal_pn")
    description = as_str(data, "description")
    package_type = as_str(data, "package_type")
    if package_type not in PACKAGE_TYPES:
        raise errors.invalid_request("package_type is not a known footprint family.")
    standard_cost_cents = as_int(data, "standard_cost_cents")
    if standard_cost_cents < 0:
        raise errors.validation("standard_cost_cents must be >= 0.")
    is_rohs_required = as_bool(data, "is_rohs_required", True)
    contains_conflict_minerals = as_bool(data, "contains_conflict_minerals", False)

    # uniqueness of internal_pn across all parts
    for p in db.parts.values():
        if p["internal_pn"] == internal_pn:
            raise errors.validation("internal_pn must be unique across all parts.")

    rec = db.new_record({
        "internal_pn": internal_pn,
        "description": description,
        "package_type": package_type,
        "is_rohs_required": is_rohs_required,
        "contains_conflict_minerals": contains_conflict_minerals,
        "standard_cost_cents": standard_cost_cents,
        "total_on_hand_qty": 0,
        "available_qty": 0,
    })
    db.parts[rec["id"]] = rec
    return resp.success(ser.public(rec), 201)


@app.route("/parts/<rid>", methods=["GET"])
def get_part(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = lk.part_path(rid)
    return resp.success(ser.public(rec), 200)


@app.route("/parts", methods=["GET"])
def list_parts():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = pg.get_pagination()
    page, total = pg.order_and_page(list(db.parts.values()), limit, offset)
    return resp.success_list(ser.public_list(page), limit, offset, total, 200)


# ===========================================================================
# VENDORS
# ===========================================================================
@app.route("/vendors", methods=["POST"])
def create_vendor():
    _, role = authenticate()
    require_roles(role, {"ProcessEngineer"})
    data = body()
    require_fields(data, ["name", "cage_code"])
    name = non_empty_str(data, "name")
    cage_code = as_str(data, "cage_code")
    is_rohs_certified = as_bool(data, "is_rohs_certified", False)

    for v in db.vendors.values():
        if v["name"] == name:
            raise errors.validation("vendor name must be unique.")

    rec = db.new_record({
        "name": name,
        "cage_code": cage_code,
        "is_rohs_certified": is_rohs_certified,
        "status": "ACTIVE",
    })
    db.vendors[rec["id"]] = rec
    return resp.success(ser.public(rec), 201)


@app.route("/vendors/<rid>", methods=["GET"])
def get_vendor(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = lk.vendor_path(rid)
    return resp.success(ser.public(rec), 200)


@app.route("/vendors/<rid>/suspend", methods=["POST"])
def suspend_vendor(rid):
    _, role = authenticate()
    require_roles(role, {"ProcessEngineer"})
    rec = lk.vendor_path(rid)
    if rec["status"] != "ACTIVE":
        raise errors.invalid_state("Vendor is not ACTIVE.")
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    return resp.success(ser.public(rec), 200)


# ===========================================================================
# AVL ENTRIES
# ===========================================================================
@app.route("/avl-entries", methods=["POST"])
def create_avl():
    _, role = authenticate()
    require_roles(role, {"ProcessEngineer"})
    data = body()
    require_fields(data, ["part_id", "vendor_id", "vendor_pn", "approval_rank"])
    part_id = as_str(data, "part_id")
    vendor_id = as_str(data, "vendor_id")
    vendor_pn = as_str(data, "vendor_pn")
    approval_rank = as_int(data, "approval_rank")
    if approval_rank < 1:
        raise errors.validation("approval_rank must be >= 1.")
    # FK resolution
    lk.get_fk(db.parts, part_id)
    lk.get_fk(db.vendors, vendor_id)

    rec = db.new_record({
        "part_id": part_id,
        "vendor_id": vendor_id,
        "vendor_pn": vendor_pn,
        "approval_rank": approval_rank,
        "status": "APPROVED",
    })
    db.avl_entries[rec["id"]] = rec
    return resp.success(ser.public(rec), 201)


@app.route("/avl-entries/<rid>", methods=["GET"])
def get_avl(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = lk.avl_path(rid)
    return resp.success(ser.public(rec), 200)


@app.route("/avl-entries", methods=["GET"])
def list_avl():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = pg.get_pagination()
    part_id = request.args.get("part_id")
    vendor_id = request.args.get("vendor_id")
    recs = list(db.avl_entries.values())
    if part_id is not None:
        recs = [r for r in recs if r["part_id"] == part_id]
    if vendor_id is not None:
        recs = [r for r in recs if r["vendor_id"] == vendor_id]
    page, total = pg.order_and_page(recs, limit, offset)
    return resp.success_list(ser.public_list(page), limit, offset, total, 200)


@app.route("/avl-entries/<rid>/revoke", methods=["POST"])
def revoke_avl(rid):
    _, role = authenticate()
    require_roles(role, {"ProcessEngineer"})
    rec = lk.avl_path(rid)
    if rec["status"] != "APPROVED":
        raise errors.invalid_state("AVL entry is not APPROVED.")
    rec["status"] = "REVOKED"
    db.touch(rec)
    return resp.success(ser.public(rec), 200)


@app.route("/avl-entries/<rid>/receive-lot", methods=["POST"])
def receive_lot(rid):
    _, role = authenticate()
    require_roles(role, {"ProductionPlanner"})
    avl = lk.avl_path(rid)
    data = body()
    require_fields(data, ["lot_code", "received_qty", "unit_cost_cents",
                          "received_at", "expected_avl_entry_version"])
    lot_code = non_empty_str(data, "lot_code")
    received_qty = as_int(data, "received_qty")
    unit_cost_cents = as_int(data, "unit_cost_cents")
    received_at = as_str(data, "received_at")
    expected_version = as_int(data, "expected_avl_entry_version")
    is_rohs_compliant = as_bool(data, "is_rohs_compliant", False)
    has_cmrt = as_bool(data, "has_cmrt", False)

    # Validation order: state validity -> OCC -> business rule.
    # AVL must be APPROVED (state) and vendor ACTIVE -> ERR_AVL_NOT_APPROVED (422).
    # OCC (412) is checked before that business gate per §2.7.
    if expected_version != avl["version"]:
        raise ApiError(errors.ERR_STALE_AVL_VERSION, 412,
                       "expected_avl_entry_version does not match current version.")

    vendor = db.vendors.get(avl["vendor_id"])
    if avl["status"] != "APPROVED" or vendor is None or vendor["status"] != "ACTIVE":
        raise ApiError(errors.ERR_AVL_NOT_APPROVED, 422,
                       "Lot may only be received against an APPROVED approval with an ACTIVE vendor.")

    # business-rule shape: received_qty > 0, unit_cost >= 0
    if received_qty <= 0:
        raise errors.validation("received_qty must be > 0.")
    if unit_cost_cents < 0:
        raise errors.validation("unit_cost_cents must be >= 0.")

    # lot_code unique within part
    for l in db.inventory_lots.values():
        if l["part_id"] == avl["part_id"] and l["lot_code"] == lot_code:
            raise errors.validation("lot_code must be unique within the part.")

    lot = db.new_record({
        "part_id": avl["part_id"],
        "avl_entry_id": avl["id"],
        "lot_code": lot_code,
        "received_qty": received_qty,
        "remaining_qty": received_qty,
        "unit_cost_cents": unit_cost_cents,
        "is_rohs_compliant": is_rohs_compliant,
        "has_cmrt": has_cmrt,
        "received_at": received_at,
        "status": "AVAILABLE",
    })
    db.inventory_lots[lot["id"]] = lot
    inv.recompute_part_rollups(avl["part_id"])
    db.touch(avl)
    return resp.success(ser.public(lot), 201)


# ===========================================================================
# INVENTORY LOTS
# ===========================================================================
@app.route("/inventory-lots/<rid>", methods=["GET"])
def get_lot(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = lk.lot_path(rid)
    return resp.success(ser.public(rec), 200)


@app.route("/inventory-lots", methods=["GET"])
def list_lots():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = pg.get_pagination()
    part_id = request.args.get("part_id")
    avl_entry_id = request.args.get("avl_entry_id")
    recs = list(db.inventory_lots.values())
    if part_id is not None:
        recs = [r for r in recs if r["part_id"] == part_id]
    if avl_entry_id is not None:
        recs = [r for r in recs if r["avl_entry_id"] == avl_entry_id]
    page, total = pg.order_and_page(recs, limit, offset)
    return resp.success_list(ser.public_list(page), limit, offset, total, 200)


@app.route("/inventory-lots/<rid>/quarantine", methods=["POST"])
def quarantine_lot(rid):
    _, role = authenticate()
    require_roles(role, {"QualityEngineer"})
    lot = lk.lot_path(rid)
    if lot["status"] != "AVAILABLE":
        raise errors.invalid_state("Lot is not AVAILABLE.")
    lot["status"] = "QUARANTINED"
    db.touch(lot)
    inv.recompute_part_rollups(lot["part_id"])
    return resp.success(ser.public(lot), 200)


# ===========================================================================
# BOMS
# ===========================================================================
@app.route("/boms", methods=["POST"])
def create_bom():
    _, role = authenticate()
    require_roles(role, {"ProcessEngineer"})
    data = body()
    require_fields(data, ["product_code", "revision"])
    product_code = non_empty_str(data, "product_code")
    revision = non_empty_str(data, "revision")
    supersedes_bom_id = as_str(data, "supersedes_bom_id", required=False, default=None)
    if supersedes_bom_id is not None:
        lk.get_fk(db.boms, supersedes_bom_id)

    # revision unique within product_code
    for b in db.boms.values():
        if b["product_code"] == product_code and b["revision"] == revision:
            raise errors.validation("revision must be unique within product_code.")

    rec = db.new_record({
        "product_code": product_code,
        "revision": revision,
        "supersedes_bom_id": supersedes_bom_id,
        "status": "DRAFT",
        "line_count": 0,
    })
    db.boms[rec["id"]] = rec
    return resp.success(ser.public(rec), 201)


@app.route("/boms/<rid>", methods=["GET"])
def get_bom(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = lk.bom_path(rid)
    return resp.success(ser.public(rec), 200)


@app.route("/boms", methods=["GET"])
def list_boms():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = pg.get_pagination()
    supersedes_bom_id = request.args.get("supersedes_bom_id")
    product_code = request.args.get("product_code")
    recs = list(db.boms.values())
    if supersedes_bom_id is not None:
        recs = [r for r in recs if r["supersedes_bom_id"] == supersedes_bom_id]
    if product_code is not None:
        recs = [r for r in recs if r["product_code"] == product_code]
    page, total = pg.order_and_page(recs, limit, offset)
    return resp.success_list(ser.public_list(page), limit, offset, total, 200)


@app.route("/boms/<rid>/lines", methods=["POST"])
def add_bom_line(rid):
    _, role = authenticate()
    require_roles(role, {"ProcessEngineer"})
    bom = lk.bom_path(rid)
    data = body()
    require_fields(data, ["part_id", "ref_designators", "qty_per_assembly"])
    part_id = as_str(data, "part_id")
    ref_designators = data.get("ref_designators")
    qty_per_assembly = as_int(data, "qty_per_assembly")
    is_dnp = as_bool(data, "is_dnp", False)

    if not isinstance(ref_designators, list) or len(ref_designators) == 0:
        raise errors.invalid_request("ref_designators must be a non-empty array.")
    for d in ref_designators:
        if not isinstance(d, str):
            raise errors.invalid_request("ref_designators must contain strings.")

    # FK resolution
    lk.get_fk(db.parts, part_id)

    if qty_per_assembly <= 0:
        raise errors.validation("qty_per_assembly must be > 0.")

    # designator-mismatch checks
    if qty_per_assembly != len(ref_designators):
        raise ApiError(errors.ERR_DESIGNATOR_MISMATCH, 422,
                       "qty_per_assembly must equal the number of ref_designators.")
    # duplicates within this line
    if len(set(ref_designators)) != len(ref_designators):
        raise ApiError(errors.ERR_DESIGNATOR_MISMATCH, 422,
                       "Duplicate reference designator within the BOM.")
    # duplicates against other lines of the same BOM
    existing = set()
    for ln in db.bom_lines.values():
        if ln["bom_id"] == bom["id"]:
            existing.update(ln["ref_designators"])
    for d in ref_designators:
        if d in existing:
            raise ApiError(errors.ERR_DESIGNATOR_MISMATCH, 422,
                           "Duplicate reference designator within the BOM.")

    line = db.new_record({
        "bom_id": bom["id"],
        "part_id": part_id,
        "ref_designators": list(ref_designators),
        "qty_per_assembly": qty_per_assembly,
        "is_dnp": is_dnp,
    })
    db.bom_lines[line["id"]] = line
    bom["line_count"] = bom.get("line_count", 0) + 1
    db.touch(bom)
    return resp.success(ser.public(line), 201)


@app.route("/boms/<rid>/lines", methods=["GET"])
def list_bom_lines_of_bom(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    bom = lk.bom_path(rid)
    limit, offset = pg.get_pagination()
    recs = [l for l in db.bom_lines.values() if l["bom_id"] == bom["id"]]
    page, total = pg.order_and_page(recs, limit, offset)
    return resp.success_list(ser.public_list(page), limit, offset, total, 200)


@app.route("/bom-lines", methods=["GET"])
def list_bom_lines():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = pg.get_pagination()
    part_id = request.args.get("part_id")
    bom_id = request.args.get("bom_id")
    recs = list(db.bom_lines.values())
    if part_id is not None:
        recs = [r for r in recs if r["part_id"] == part_id]
    if bom_id is not None:
        recs = [r for r in recs if r["bom_id"] == bom_id]
    page, total = pg.order_and_page(recs, limit, offset)
    return resp.success_list(ser.public_list(page), limit, offset, total, 200)


@app.route("/bom-lines/<rid>", methods=["GET"])
def get_bom_line(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = lk.bom_line_path(rid)
    return resp.success(ser.public(rec), 200)


@app.route("/boms/<rid>/release", methods=["POST"])
def release_bom(rid):
    _, role = authenticate()
    require_roles(role, {"ProcessEngineer"})
    bom = lk.bom_path(rid)
    if bom["status"] != "DRAFT":
        raise errors.invalid_state("BOM is not in DRAFT.")
    lines = [l for l in db.bom_lines.values() if l["bom_id"] == bom["id"]]
    if len(lines) < 1:
        raise ApiError(errors.ERR_NO_APPROVED_SOURCE, 422,
                       "BOM must have at least one line to release.")
    # every non-DNP line's part must have >= 1 APPROVED AvlEntry
    for ln in lines:
        if ln["is_dnp"]:
            continue
        has_approved = any(
            a["part_id"] == ln["part_id"] and a["status"] == "APPROVED"
            for a in db.avl_entries.values()
        )
        if not has_approved:
            raise ApiError(errors.ERR_NO_APPROVED_SOURCE, 422,
                           "A non-DNP line's part has no APPROVED approval.")

    bom["status"] = "RELEASED"
    db.touch(bom)

    # Cascade onto the superseded revision.
    prior_id = bom.get("supersedes_bom_id")
    if prior_id is not None:
        prior = db.boms.get(prior_id)
        if prior is not None and prior["status"] == "RELEASED":
            prior["status"] = "OBSOLETE"
            db.touch(prior)
            # cancel PLANNED work orders anchored to the now-OBSOLETE prior BOM
            for wo in db.work_orders.values():
                if wo["bom_id"] == prior["id"] and wo["status"] == "PLANNED":
                    wo["status"] = "CANCELLED"
                    db.touch(wo)

    return resp.success(ser.public(bom), 200)


# ===========================================================================
# LINE PROGRAMS
# ===========================================================================
@app.route("/line-programs", methods=["POST"])
def create_line_program():
    _, role = authenticate()
    require_roles(role, {"ProcessEngineer"})
    data = body()
    require_fields(data, ["bom_id", "line_code", "feeder_slot_count", "program_checksum"])
    bom_id = as_str(data, "bom_id")
    line_code = as_str(data, "line_code")
    feeder_slot_count = as_int(data, "feeder_slot_count")
    program_checksum = as_str(data, "program_checksum")
    lk.get_fk(db.boms, bom_id)
    if feeder_slot_count <= 0:
        raise errors.validation("feeder_slot_count must be > 0.")

    rec = db.new_record({
        "bom_id": bom_id,
        "line_code": line_code,
        "feeder_slot_count": feeder_slot_count,
        "program_checksum": program_checksum,
        "status": "UNVERIFIED",
    })
    db.line_programs[rec["id"]] = rec
    return resp.success(ser.public(rec), 201)


@app.route("/line-programs/<rid>", methods=["GET"])
def get_line_program(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = lk.line_program_path(rid)
    return resp.success(ser.public(rec), 200)


@app.route("/line-programs", methods=["GET"])
def list_line_programs():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = pg.get_pagination()
    bom_id = request.args.get("bom_id")
    recs = list(db.line_programs.values())
    if bom_id is not None:
        recs = [r for r in recs if r["bom_id"] == bom_id]
    page, total = pg.order_and_page(recs, limit, offset)
    return resp.success_list(ser.public_list(page), limit, offset, total, 200)


@app.route("/line-programs/<rid>/verify", methods=["POST"])
def verify_line_program(rid):
    _, role = authenticate()
    require_roles(role, {"ProcessEngineer"})
    rec = lk.line_program_path(rid)
    if rec["status"] != "UNVERIFIED":
        raise errors.invalid_state("Line program is not UNVERIFIED.")
    rec["status"] = "VERIFIED"
    db.touch(rec)
    return resp.success(ser.public(rec), 200)


# ===========================================================================
# WORK ORDERS
# ===========================================================================
@app.route("/work-orders", methods=["POST"])
def create_work_order():
    _, role = authenticate()
    require_roles(role, {"ProductionPlanner"})
    data = body()
    require_fields(data, ["bom_id", "planned_qty"])
    bom_id = as_str(data, "bom_id")
    planned_qty = as_int(data, "planned_qty")
    bom = lk.get_fk(db.boms, bom_id)
    if planned_qty <= 0:
        raise errors.validation("planned_qty must be > 0.")
    if bom["status"] != "RELEASED":
        raise errors.validation("Work order must anchor a RELEASED BOM.")

    rec = db.new_record({
        "bom_id": bom_id,
        "planned_qty": planned_qty,
        "line_program_id": None,
        "status": "PLANNED",
        "kit_shortage_count": 0,
        "built_qty": 0,
        "passed_qty": 0,
        "first_pass_yield_pct": 0,
        "material_cost_cents": 0,
    })
    db.work_orders[rec["id"]] = rec
    return resp.success(ser.public(rec), 201)


@app.route("/work-orders/<rid>", methods=["GET"])
def get_work_order(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = lk.work_order_path(rid)
    return resp.success(ser.public(rec), 200)


@app.route("/work-orders", methods=["GET"])
def list_work_orders():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = pg.get_pagination()
    bom_id = request.args.get("bom_id")
    line_program_id = request.args.get("line_program_id")
    status = request.args.get("status")
    recs = list(db.work_orders.values())
    if bom_id is not None:
        recs = [r for r in recs if r["bom_id"] == bom_id]
    if line_program_id is not None:
        recs = [r for r in recs if r["line_program_id"] == line_program_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total = pg.order_and_page(recs, limit, offset)
    return resp.success_list(ser.public_list(page), limit, offset, total, 200)


@app.route("/work-orders/<rid>/kit", methods=["POST"])
def kit_work_order(rid):
    _, role = authenticate()
    require_roles(role, {"ProductionPlanner"})
    wo = lk.work_order_path(rid)
    if wo["status"] != "PLANNED":
        raise errors.invalid_state("Work order is not PLANNED.")
    bom = db.boms.get(wo["bom_id"])
    if bom is None or bom["status"] != "RELEASED":
        raise errors.validation("Anchoring BOM is not RELEASED.")

    # Building requirements: RoHS gate raises before any requirement is committed.
    # If requirements already exist from a previous failed attempt, none would be
    # left because shortage keeps the WO PLANNED but the requirements persist;
    # to be deterministic, remove any existing requirements for this WO first.
    existing = [kr_id for kr_id, kr in db.kit_requirements.items()
                if kr["work_order_id"] == wo["id"]]
    for kr_id in existing:
        del db.kit_requirements[kr_id]

    shortage = wf.kit_work_order(wo, bom)
    wo["kit_shortage_count"] = shortage
    if shortage > 0:
        # remain PLANNED; recompute rollups already done; reject
        db.touch(wo)
        raise ApiError(errors.ERR_KIT_SHORTAGE, 409,
                       "Kitting could not fully reserve one or more requirements.")
    wo["status"] = "KITTED"
    db.touch(wo)
    return resp.success(ser.public(wo), 200)


@app.route("/work-orders/<rid>/setup", methods=["POST"])
def setup_work_order(rid):
    _, role = authenticate()
    require_roles(role, {"ProductionPlanner"})
    wo = lk.work_order_path(rid)
    data = body()
    require_fields(data, ["line_program_id"])
    line_program_id = as_str(data, "line_program_id")
    program = lk.get_fk(db.line_programs, line_program_id)
    if wo["status"] != "KITTED":
        raise errors.invalid_state("Work order is not KITTED.")
    if program["status"] != "VERIFIED" or program["bom_id"] != wo["bom_id"]:
        raise ApiError(errors.ERR_PROGRAM_NOT_READY, 422,
                       "Line program must be VERIFIED and target the work order's BOM.")
    wo["line_program_id"] = line_program_id
    wo["status"] = "SETUP"
    db.touch(wo)
    return resp.success(ser.public(wo), 200)


@app.route("/work-orders/<rid>/start", methods=["POST"])
def start_work_order(rid):
    _, role = authenticate()
    require_roles(role, {"ProductionPlanner"})
    wo = lk.work_order_path(rid)
    if wo["status"] != "SETUP":
        raise errors.invalid_state("Work order is not SETUP.")
    cost = wf.start_consume(wo)
    wo["material_cost_cents"] = cost
    wo["status"] = "RUNNING"
    db.touch(wo)
    return resp.success(ser.public(wo), 200)


@app.route("/work-orders/<rid>/units", methods=["POST"])
def serialize_unit(rid):
    _, role = authenticate()
    require_roles(role, {"ProductionPlanner"})
    wo = lk.work_order_path(rid)
    if wo["status"] != "RUNNING":
        raise errors.invalid_state("Work order is not RUNNING.")

    unit = db.new_record({
        "work_order_id": wo["id"],
        "serial_number": db.mint_serial(),
        "quality_status": "BUILT",
        "disposition": "IN_PROCESS",
        "defect_code": None,
        "rework_count": 0,
    })
    db.units[unit["id"]] = unit
    wf.recompute_built_qty(wo)
    if wo["built_qty"] >= wo["planned_qty"]:
        wo["status"] = "AT_TEST"
    db.touch(wo)
    return resp.success(ser.public(unit), 201)


@app.route("/work-orders/<rid>/units", methods=["GET"])
def list_wo_units(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    wo = lk.work_order_path(rid)
    limit, offset = pg.get_pagination()
    recs = wf.units_for_wo(wo["id"])
    page, total = pg.order_and_page(recs, limit, offset)
    return resp.success_list(ser.public_list(page), limit, offset, total, 200)


@app.route("/work-orders/<rid>/kit-requirements", methods=["GET"])
def list_wo_kit_reqs(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    wo = lk.work_order_path(rid)
    limit, offset = pg.get_pagination()
    recs = wf.kit_requirements_for_wo(wo["id"])
    page, total = pg.order_and_page(recs, limit, offset)
    return resp.success_list(ser.public_list(page), limit, offset, total, 200)


@app.route("/work-orders/<rid>/finalize-test", methods=["POST"])
def finalize_test(rid):
    _, role = authenticate()
    require_roles(role, {"QualityEngineer"})
    wo = lk.work_order_path(rid)
    if wo["status"] != "AT_TEST":
        raise errors.invalid_state("Work order is not AT_TEST.")
    wf.recompute_wo_yield(wo)
    units = wf.units_for_wo(wo["id"])
    all_resolved = all(u["quality_status"] in ("PASS", "REWORKED") for u in units)
    if all_resolved:
        wo["status"] = "PASSED"
    elif wo["first_pass_yield_pct"] < calc.MIN_YIELD_PCT:
        wo["status"] = "FAILED"
    else:
        # Neither finalize outcome is satisfied: some unit is still BUILT/FAIL
        # yet FPY is at or above the floor. The transition is not defined.
        raise errors.invalid_state(
            "Cannot finalize: outstanding BUILT/FAIL units with FPY above the floor.")
    db.touch(wo)
    return resp.success(ser.public(wo), 200)


@app.route("/work-orders/<rid>/close", methods=["POST"])
def close_work_order(rid):
    _, role = authenticate()
    require_roles(role, {"ProductionPlanner"})
    wo = lk.work_order_path(rid)
    if wo["status"] != "PASSED":
        raise errors.invalid_state("Work order is not PASSED.")
    # no OPEN rework under any unit of this WO
    unit_ids = {u["id"] for u in wf.units_for_wo(wo["id"])}
    for ro in db.rework_orders.values():
        if ro["unit_id"] in unit_ids and ro["status"] == "OPEN":
            raise ApiError(errors.ERR_OPEN_REWORK_BLOCKS_CLOSE, 409,
                           "An OPEN rework order blocks closing the work order.")
    wo["status"] = "CLOSED"
    db.touch(wo)
    return resp.success(ser.public(wo), 200)


@app.route("/work-orders/<rid>/cancel", methods=["POST"])
def cancel_work_order(rid):
    _, role = authenticate()
    require_roles(role, {"ProductionPlanner"})
    wo = lk.work_order_path(rid)
    if wo["status"] not in ("PLANNED", "KITTED"):
        raise errors.invalid_state("Work order can only be cancelled while PLANNED or KITTED.")
    if wo["status"] == "KITTED":
        wf.release_reservations(wo["id"])
    wo["status"] = "CANCELLED"
    db.touch(wo)
    return resp.success(ser.public(wo), 200)


@app.route("/work-orders/<rid>/ship", methods=["POST"])
def ship_work_order(rid):
    _, role = authenticate()
    require_roles(role, {"ProductionPlanner"})
    wo = lk.work_order_path(rid)
    data = body()
    require_fields(data, ["expected_work_order_version"])
    expected_version = as_int(data, "expected_work_order_version")
    if wo["status"] not in ("PASSED", "CLOSED"):
        raise errors.invalid_state("Work order must be PASSED or CLOSED to ship.")
    if expected_version != wo["version"]:
        raise ApiError(errors.ERR_STALE_WORK_ORDER_VERSION, 412,
                       "expected_work_order_version does not match current version.")
    for u in wf.units_for_wo(wo["id"]):
        if u["quality_status"] in ("PASS", "REWORKED"):
            u["disposition"] = "SHIPPED"
            db.touch(u)
    db.touch(wo)
    return resp.success(ser.public(wo), 200)


# ===========================================================================
# KIT REQUIREMENTS (read)
# ===========================================================================
@app.route("/kit-requirements/<rid>", methods=["GET"])
def get_kit_requirement(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = lk.kit_req_path(rid)
    return resp.success(ser.public(rec), 200)


@app.route("/kit-requirements", methods=["GET"])
def list_kit_requirements():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = pg.get_pagination()
    part_id = request.args.get("part_id")
    work_order_id = request.args.get("work_order_id")
    recs = list(db.kit_requirements.values())
    if part_id is not None:
        recs = [r for r in recs if r["part_id"] == part_id]
    if work_order_id is not None:
        recs = [r for r in recs if r["work_order_id"] == work_order_id]
    page, total = pg.order_and_page(recs, limit, offset)
    return resp.success_list(ser.public_list(page), limit, offset, total, 200)


# ===========================================================================
# UNITS
# ===========================================================================
@app.route("/units/<rid>", methods=["GET"])
def get_unit(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = lk.unit_path(rid)
    return resp.success(ser.public(rec), 200)


@app.route("/units/<rid>/test-result", methods=["POST"])
def unit_test_result(rid):
    _, role = authenticate()
    require_roles(role, {"QualityEngineer"})
    unit = lk.unit_path(rid)
    data = body()
    require_fields(data, ["result"])
    result = as_str(data, "result")
    if result not in TEST_RESULTS:
        raise errors.invalid_request("result must be PASS or FAIL.")
    wo = db.work_orders.get(unit["work_order_id"])
    if unit["quality_status"] != "BUILT" or wo is None or wo["status"] != "AT_TEST":
        raise errors.invalid_state("Unit must be BUILT and its work order AT_TEST.")

    if result == "PASS":
        unit["quality_status"] = "PASS"
    else:  # FAIL
        defect_code = data.get("defect_code")
        if defect_code is None or not isinstance(defect_code, str) or defect_code == "":
            raise errors.invalid_request("defect_code is required for a FAIL result.")
        unit["quality_status"] = "FAIL"
        unit["defect_code"] = defect_code
    db.touch(unit)
    wf.recompute_wo_yield(wo)
    # yield recompute does not itself bump version; reflect ledger sync on WO
    db.touch(wo)
    return resp.success(ser.public(unit), 200)


# ===========================================================================
# REWORK ORDERS
# ===========================================================================
@app.route("/rework-orders", methods=["POST"])
def create_rework_order():
    _, role = authenticate()
    require_roles(role, {"ProductionPlanner"})
    data = body()
    require_fields(data, ["unit_id", "defect_code"])
    unit_id = as_str(data, "unit_id")
    defect_code = as_str(data, "defect_code")
    eco_id = as_str(data, "eco_id", required=False, default=None)
    unit = lk.get_fk(db.units, unit_id)
    if eco_id is not None:
        lk.get_fk(db.ecos, eco_id)
    if unit["quality_status"] not in ("FAIL", "REWORKED"):
        raise errors.invalid_state("Unit must be FAIL or REWORKED to open a rework.")

    rec = db.new_record({
        "unit_id": unit_id,
        "eco_id": eco_id,
        "defect_code": defect_code,
        "added_material_cost_cents": 0,
        "status": "OPEN",
    })
    db.rework_orders[rec["id"]] = rec
    return resp.success(ser.public(rec), 201)


@app.route("/rework-orders/<rid>", methods=["GET"])
def get_rework_order(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = lk.rework_path(rid)
    return resp.success(ser.public(rec), 200)


@app.route("/rework-orders", methods=["GET"])
def list_rework_orders():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = pg.get_pagination()
    unit_id = request.args.get("unit_id")
    eco_id = request.args.get("eco_id")
    recs = list(db.rework_orders.values())
    if unit_id is not None:
        recs = [r for r in recs if r["unit_id"] == unit_id]
    if eco_id is not None:
        recs = [r for r in recs if r["eco_id"] == eco_id]
    page, total = pg.order_and_page(recs, limit, offset)
    return resp.success_list(ser.public_list(page), limit, offset, total, 200)


@app.route("/rework-orders/<rid>/close", methods=["POST"])
def close_rework_order(rid):
    _, role = authenticate()
    require_roles(role, {"ProductionPlanner"})
    ro = lk.rework_path(rid)
    data = body()
    require_fields(data, ["replacement_part_id", "replacement_qty", "acting_user_id"])
    replacement_part_id = as_str(data, "replacement_part_id")
    replacement_qty = as_int(data, "replacement_qty")
    acting_user_id = as_str(data, "acting_user_id")
    replacement_part = lk.get_fk(db.parts, replacement_part_id)

    if ro["status"] != "OPEN":
        raise errors.invalid_state("Rework order is not OPEN.")

    unit = db.units.get(ro["unit_id"])
    if unit is None or unit["quality_status"] not in ("FAIL", "REWORKED"):
        raise errors.invalid_state("Target unit must be FAIL or REWORKED.")

    # ECO gate: when eco_id present, must be APPROVED, and SoD on author.
    if ro.get("eco_id") is not None:
        eco = db.ecos.get(ro["eco_id"])
        if eco is None or eco["status"] != "APPROVED":
            raise ApiError(errors.ERR_REWORK_ECO_NOT_APPROVED, 422,
                           "Linked ECO is not APPROVED.")
        if acting_user_id == eco.get("authored_by_user_id"):
            raise ApiError(errors.ERR_SOD_VIOLATION, 409,
                           "Rework closer must differ from the ECO author.")

    if replacement_qty <= 0:
        raise errors.validation("replacement_qty must be > 0.")

    # Consume replacement material FIFO (RoHS + CMRT gates apply).
    base_part_cost = wf.consume_fifo(replacement_part, replacement_qty, check_cmrt_gate=True)
    added = calc.rework_material_cost(base_part_cost)
    ro["added_material_cost_cents"] = added

    # Roll into parent work order's material_cost_cents.
    wo = db.work_orders.get(unit["work_order_id"])
    if wo is not None:
        wo["material_cost_cents"] = wo.get("material_cost_cents", 0) + added
        db.touch(wo)

    # Mark unit REWORKED, increment rework_count.
    unit["quality_status"] = "REWORKED"
    unit["rework_count"] = unit.get("rework_count", 0) + 1
    db.touch(unit)

    # FPY unaffected (unit already excluded from first_pass), but keep WO ledger
    # synced for passed_qty etc.
    if wo is not None:
        wf.recompute_wo_yield(wo)

    ro["status"] = "CLOSED"
    db.touch(ro)
    return resp.success(ser.public(ro), 200)


@app.route("/rework-orders/<rid>/abandon", methods=["POST"])
def abandon_rework_order(rid):
    _, role = authenticate()
    require_roles(role, {"ProductionPlanner"})
    ro = lk.rework_path(rid)
    if ro["status"] != "OPEN":
        raise errors.invalid_state("Rework order is not OPEN.")
    unit = db.units.get(ro["unit_id"])
    if unit is not None:
        unit["disposition"] = "SCRAPPED"
        db.touch(unit)
    ro["status"] = "ABANDONED"
    db.touch(ro)
    return resp.success(ser.public(ro), 200)


# ===========================================================================
# ECOs
# ===========================================================================
@app.route("/ecos", methods=["POST"])
def create_eco():
    user_id, role = authenticate()
    require_roles(role, {"ProcessEngineer"})
    data = body()
    require_fields(data, ["title", "bom_id", "change_summary"])
    title = as_str(data, "title")
    bom_id = as_str(data, "bom_id")
    change_summary = as_str(data, "change_summary")
    lk.get_fk(db.boms, bom_id)

    rec = db.new_record({
        "title": title,
        "bom_id": bom_id,
        "change_summary": change_summary,
        "authored_by_user_id": user_id,
        "approved_by_user_id": None,
        "status": "DRAFT",
    })
    db.ecos[rec["id"]] = rec
    return resp.success(ser.public(rec), 201)


@app.route("/ecos/<rid>", methods=["GET"])
def get_eco(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = lk.eco_path(rid)
    return resp.success(ser.public(rec), 200)


@app.route("/ecos", methods=["GET"])
def list_ecos():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = pg.get_pagination()
    bom_id = request.args.get("bom_id")
    status = request.args.get("status")
    recs = list(db.ecos.values())
    if bom_id is not None:
        recs = [r for r in recs if r["bom_id"] == bom_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total = pg.order_and_page(recs, limit, offset)
    return resp.success_list(ser.public_list(page), limit, offset, total, 200)


@app.route("/ecos/<rid>/submit", methods=["POST"])
def submit_eco(rid):
    _, role = authenticate()
    require_roles(role, {"ProcessEngineer"})
    eco = lk.eco_path(rid)
    data = body()
    require_fields(data, ["acting_user_id"])
    acting_user_id = as_str(data, "acting_user_id")
    if eco["status"] not in ("DRAFT", "REJECTED"):
        raise errors.invalid_state("ECO must be DRAFT or REJECTED to submit.")
    if acting_user_id != eco["authored_by_user_id"]:
        raise ApiError(errors.ERR_SOD_VIOLATION, 409,
                       "Only the author may submit the ECO.")
    eco["status"] = "SUBMITTED"
    db.touch(eco)
    return resp.success(ser.public(eco), 200)


@app.route("/ecos/<rid>/approve", methods=["POST"])
def approve_eco(rid):
    _, role = authenticate()
    require_roles(role, {"QualityEngineer"})
    eco = lk.eco_path(rid)
    data = body()
    require_fields(data, ["acting_user_id"])
    acting_user_id = as_str(data, "acting_user_id")
    if eco["status"] != "SUBMITTED":
        raise errors.invalid_state("ECO must be SUBMITTED to approve.")
    if acting_user_id == eco["authored_by_user_id"]:
        raise ApiError(errors.ERR_SOD_VIOLATION, 409,
                       "Approver must differ from the ECO author.")
    eco["status"] = "APPROVED"
    eco["approved_by_user_id"] = acting_user_id
    db.touch(eco)
    return resp.success(ser.public(eco), 200)


@app.route("/ecos/<rid>/reject", methods=["POST"])
def reject_eco(rid):
    _, role = authenticate()
    require_roles(role, {"QualityEngineer"})
    eco = lk.eco_path(rid)
    if eco["status"] != "SUBMITTED":
        raise errors.invalid_state("ECO must be SUBMITTED to reject.")
    eco["status"] = "REJECTED"
    db.touch(eco)
    return resp.success(ser.public(eco), 200)


@app.route("/ecos/<rid>/implement", methods=["POST"])
def implement_eco(rid):
    _, role = authenticate()
    require_roles(role, {"ProcessEngineer"})
    eco = lk.eco_path(rid)
    if eco["status"] != "APPROVED":
        raise errors.invalid_state("ECO must be APPROVED to implement.")
    eco["status"] = "IMPLEMENTED"
    db.touch(eco)
    return resp.success(ser.public(eco), 200)


# ===========================================================================
# RMAs
# ===========================================================================
@app.route("/rmas", methods=["POST"])
def create_rma():
    _, role = authenticate()
    require_roles(role, {"QualityEngineer"})
    data = body()
    require_fields(data, ["unit_id", "reported_defect_code"])
    unit_id = as_str(data, "unit_id")
    reported_defect_code = as_str(data, "reported_defect_code")
    unit = lk.get_fk(db.units, unit_id)
    if unit["disposition"] != "SHIPPED":
        raise ApiError(errors.ERR_UNIT_NOT_SHIPPED, 422,
                       "RMA may only be opened for a SHIPPED unit.")
    rec = db.new_record({
        "unit_id": unit_id,
        "reported_defect_code": reported_defect_code,
        "failure_class": None,
        "status": "RECEIVED",
        "warranty_credit_cents": 0,
    })
    db.rmas[rec["id"]] = rec
    return resp.success(ser.public(rec), 201)


@app.route("/rmas/<rid>", methods=["GET"])
def get_rma(rid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = lk.rma_path(rid)
    return resp.success(ser.public(rec), 200)


@app.route("/rmas", methods=["GET"])
def list_rmas():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = pg.get_pagination()
    unit_id = request.args.get("unit_id")
    status = request.args.get("status")
    recs = list(db.rmas.values())
    if unit_id is not None:
        recs = [r for r in recs if r["unit_id"] == unit_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total = pg.order_and_page(recs, limit, offset)
    return resp.success_list(ser.public_list(page), limit, offset, total, 200)


@app.route("/rmas/<rid>/triage", methods=["POST"])
def triage_rma(rid):
    _, role = authenticate()
    require_roles(role, {"QualityEngineer"})
    rma = lk.rma_path(rid)
    data = body()
    require_fields(data, ["failure_class"])
    failure_class = as_str(data, "failure_class")
    if failure_class not in FAILURE_CLASSES:
        raise errors.invalid_request("failure_class is not a known value.")
    if rma["status"] != "RECEIVED":
        raise errors.invalid_state("RMA must be RECEIVED to triage.")

    unit = db.units.get(rma["unit_id"])
    wo = db.work_orders.get(unit["work_order_id"]) if unit else None
    material_cost = wo["material_cost_cents"] if wo else 0
    built_qty = wo["built_qty"] if wo else 0
    rework_count = unit["rework_count"] if unit else 0

    credit = calc.rma_warranty_credit(material_cost, built_qty, failure_class, rework_count)
    rma["failure_class"] = failure_class
    rma["warranty_credit_cents"] = credit
    rma["status"] = "TRIAGED"
    db.touch(rma)
    return resp.success(ser.public(rma), 200)


@app.route("/rmas/<rid>/repair", methods=["POST"])
def repair_rma(rid):
    _, role = authenticate()
    require_roles(role, {"ProductionPlanner"})
    rma = lk.rma_path(rid)
    if rma["status"] != "TRIAGED":
        raise errors.invalid_state("RMA must be TRIAGED to repair.")
    if rma["failure_class"] == "NO_FAULT_FOUND":
        raise errors.validation("A NO_FAULT_FOUND RMA cannot be routed to repair.")
    unit = db.units.get(rma["unit_id"])
    if unit is not None:
        unit["disposition"] = "IN_PROCESS"
        unit["quality_status"] = "REWORKED"
        db.touch(unit)
    rma["status"] = "REPAIRED"
    db.touch(rma)
    return resp.success(ser.public(rma), 200)


@app.route("/rmas/<rid>/scrap", methods=["POST"])
def scrap_rma(rid):
    _, role = authenticate()
    require_roles(role, {"QualityEngineer"})
    rma = lk.rma_path(rid)
    if rma["status"] != "TRIAGED":
        raise errors.invalid_state("RMA must be TRIAGED to scrap.")
    unit = db.units.get(rma["unit_id"])
    if unit is not None:
        unit["disposition"] = "SCRAPPED"
        db.touch(unit)
    rma["status"] = "SCRAPPED"
    db.touch(rma)
    return resp.success(ser.public(rma), 200)


@app.route("/rmas/<rid>/close", methods=["POST"])
def close_rma(rid):
    _, role = authenticate()
    require_roles(role, {"ProductionPlanner"})
    rma = lk.rma_path(rid)
    if rma["status"] not in ("REPAIRED", "SCRAPPED"):
        raise errors.invalid_state("RMA must be REPAIRED or SCRAPPED to close.")
    if rma["status"] == "REPAIRED":
        unit = db.units.get(rma["unit_id"])
        if unit is not None:
            unit["disposition"] = "SHIPPED"
            db.touch(unit)
    rma["status"] = "CLOSED"
    db.touch(rma)
    return resp.success(ser.public(rma), 200)


# ===========================================================================
# TEST DRIVER (PRD §3.11 / SCAFFOLD §1.5 priority rung 3)
# ===========================================================================
@app.route("/_test/build-and-test-units", methods=["POST"])
def build_and_test_units():
    _, role = authenticate()
    require_roles(role, {"ProductionPlanner"})
    data = body()
    require_fields(data, ["work_order_id", "pass_first_count",
                          "rework_from_fail_count", "replacement_part_id"])
    work_order_id = as_str(data, "work_order_id")
    pass_first_count = as_int(data, "pass_first_count")
    rework_from_fail_count = as_int(data, "rework_from_fail_count")
    replacement_part_id = as_str(data, "replacement_part_id")

    wo = lk.get_fk(db.work_orders, work_order_id)
    replacement_part = lk.get_fk(db.parts, replacement_part_id)

    if wo["status"] != "RUNNING":
        raise errors.invalid_state("Work order must be RUNNING for the test driver.")
    if pass_first_count < 0 or rework_from_fail_count < 0:
        raise errors.validation("counts must be >= 0.")
    if pass_first_count + rework_from_fail_count != wo["planned_qty"]:
        raise errors.validation(
            "pass_first_count + rework_from_fail_count must equal planned_qty.")

    # Serialize exactly planned_qty units.
    serialized = []
    for _ in range(wo["planned_qty"]):
        unit = db.new_record({
            "work_order_id": wo["id"],
            "serial_number": db.mint_serial(),
            "quality_status": "BUILT",
            "disposition": "IN_PROCESS",
            "defect_code": None,
            "rework_count": 0,
        })
        db.units[unit["id"]] = unit
        serialized.append(unit)
    wf.recompute_built_qty(wo)
    # Built fully -> advance to AT_TEST (test results require AT_TEST).
    wo["status"] = "AT_TEST"
    db.touch(wo)

    # First `pass_first_count` -> PASS on first test.
    idx = 0
    for _ in range(pass_first_count):
        unit = serialized[idx]
        unit["quality_status"] = "PASS"
        db.touch(unit)
        idx += 1

    # Next `rework_from_fail_count` -> FAIL then non-ECO rework to REWORKED.
    for _ in range(rework_from_fail_count):
        unit = serialized[idx]
        unit["quality_status"] = "FAIL"
        unit["defect_code"] = "DRIVER_FAIL"
        db.touch(unit)
        # Open + close a non-ECO rework consuming qty 1 of replacement_part FIFO.
        ro = db.new_record({
            "unit_id": unit["id"],
            "eco_id": None,
            "defect_code": "DRIVER_FAIL",
            "added_material_cost_cents": 0,
            "status": "OPEN",
        })
        db.rework_orders[ro["id"]] = ro
        base_part_cost = wf.consume_fifo(replacement_part, 1, check_cmrt_gate=True)
        added = calc.rework_material_cost(base_part_cost)
        ro["added_material_cost_cents"] = added
        wo["material_cost_cents"] = wo.get("material_cost_cents", 0) + added
        unit["quality_status"] = "REWORKED"
        unit["rework_count"] = unit.get("rework_count", 0) + 1
        db.touch(unit)
        ro["status"] = "CLOSED"
        db.touch(ro)
        idx += 1

    wf.recompute_wo_yield(wo)
    db.touch(wo)
    return resp.success(ser.public(wo), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
