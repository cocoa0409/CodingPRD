"""Raw materials, material lots, and identity testing (PRD section 3.2)."""
from flask import Blueprint

from db import store, new_entity, touch
from errors import (
    raise_error,
    ERR_LOT_STATE,
    ERR_IDENTITY_TEST_STATE,
    ERR_SOD_VIOLATION,
)
from middleware import require_roles, ANY_ROLE
from response import ok
from util import (
    ALLERGEN_CLASSES,
    body,
    dec,
    invalid,
    not_found,
    paginate,
    req_enum,
    req_num,
    req_str,
    sorted_by_created,
)

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------------------------
# Raw materials
# ---------------------------------------------------------------------------
@bp.post("/api/raw-materials")
@require_roles("ProductionPlanner")
def create_raw_material(user_id, role):
    data = body()
    name = req_str(data, "name")
    allergen_class = req_enum(data, "allergen_class", ALLERGEN_CLASSES)
    material = new_entity({"name": name, "allergen_class": allergen_class})
    store["raw_materials"][material["id"]] = material
    return ok(material, 201)


@bp.get("/api/raw-materials/<material_id>")
@require_roles(*ANY_ROLE)
def get_raw_material(user_id, role, material_id):
    material = store["raw_materials"].get(material_id)
    if material is None:
        not_found()
    return ok(material)


@bp.get("/api/raw-materials/<material_id>/material-lots")
@require_roles(*ANY_ROLE)
def list_material_lots(user_id, role, material_id):
    material = store["raw_materials"].get(material_id)
    if material is None:
        not_found()
    items = sorted_by_created(
        l for l in store["material_lots"].values() if l["raw_material_id"] == material_id
    )
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/api/raw-materials/<material_id>/formula-lines")
@require_roles(*ANY_ROLE)
def list_material_formula_lines(user_id, role, material_id):
    material = store["raw_materials"].get(material_id)
    if material is None:
        not_found()
    items = sorted_by_created(
        l for l in store["formula_lines"].values() if l["raw_material_id"] == material_id
    )
    page, meta = paginate(items)
    return ok(page, 200, meta)


# ---------------------------------------------------------------------------
# Material lots
# ---------------------------------------------------------------------------
@bp.post("/api/material-lots")
@require_roles("ProductionOperator")
def create_material_lot(user_id, role):
    data = body()
    raw_material_id = req_str(data, "raw_material_id")
    if raw_material_id not in store["raw_materials"]:
        not_found("raw_material_id does not identify an existing raw material")
    supplier_name = req_str(data, "supplier_name")
    supplier_coa_ref = req_str(data, "supplier_coa_ref")
    qty_received = req_num(data, "qty_received")
    if not dec(qty_received) > 0:
        invalid("'qty_received' must be greater than zero")
    lot = new_entity({
        "raw_material_id": raw_material_id,
        "supplier_name": supplier_name,
        "supplier_coa_ref": supplier_coa_ref,
        "qty_received": qty_received,
        "qty_remaining": qty_received,
        "status": "QUARANTINE",
    })
    store["material_lots"][lot["id"]] = lot
    return ok(lot, 201)


@bp.get("/api/material-lots/<lot_id>")
@require_roles(*ANY_ROLE)
def get_material_lot(user_id, role, lot_id):
    lot = store["material_lots"].get(lot_id)
    if lot is None:
        not_found()
    return ok(lot)


@bp.get("/api/material-lots/<lot_id>/identity-tests")
@require_roles(*ANY_ROLE)
def list_lot_identity_tests(user_id, role, lot_id):
    lot = store["material_lots"].get(lot_id)
    if lot is None:
        not_found()
    items = sorted_by_created(
        t for t in store["identity_tests"].values() if t["material_lot_id"] == lot_id
    )
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/api/material-lots/<lot_id>/consumptions")
@require_roles(*ANY_ROLE)
def list_lot_consumptions(user_id, role, lot_id):
    lot = store["material_lots"].get(lot_id)
    if lot is None:
        not_found()
    items = sorted_by_created(
        c for c in store["batch_consumptions"].values() if c["material_lot_id"] == lot_id
    )
    page, meta = paginate(items)
    return ok(page, 200, meta)


# ---------------------------------------------------------------------------
# Identity testing (two-person clearance workflow).
# ---------------------------------------------------------------------------
@bp.post("/api/material-lots/<lot_id>/identity-tests")
@require_roles("QAChemist")
def submit_identity_test(user_id, role, lot_id):
    lot = store["material_lots"].get(lot_id)
    if lot is None:
        not_found()
    if lot["status"] not in ("QUARANTINE", "IDENTITY_FAILED"):
        raise_error(
            ERR_LOT_STATE,
            "Identity testing requires the lot to be in QUARANTINE or IDENTITY_FAILED",
        )
    data = body()
    result = req_enum(data, "result", ("PASS", "FAIL"))
    coa_match = data.get("coa_match")
    if not isinstance(coa_match, bool):
        invalid("'coa_match' must be a boolean")
    test = new_entity({
        "material_lot_id": lot_id,
        "result": result,
        "coa_match": coa_match,
        "tested_by_id": user_id,
        "review_outcome": None,
        "reviewed_by_id": None,
        "status": "SUBMITTED",
    })
    store["identity_tests"][test["id"]] = test
    lot["status"] = "IDENTITY_PASSED" if result == "PASS" else "IDENTITY_FAILED"
    touch(lot)
    return ok(test, 201)


@bp.post("/api/identity-tests/<test_id>/coa-review")
@require_roles("QAManager")
def coa_review(user_id, role, test_id):
    test = store["identity_tests"].get(test_id)
    if test is None:
        not_found()
    if test["status"] != "SUBMITTED":
        raise_error(ERR_IDENTITY_TEST_STATE, "Identity test is not in SUBMITTED status")
    if user_id == test["tested_by_id"]:
        raise_error(
            ERR_SOD_VIOLATION,
            "The reviewing manager must differ from the chemist who submitted the test",
        )
    data = body()
    review_outcome = req_enum(data, "review_outcome", ("APPROVE", "REJECT"))
    if review_outcome == "APPROVE" and test["result"] != "PASS":
        invalid("An APPROVE outcome is lawful only on a PASS identity test")
    lot = store["material_lots"].get(test["material_lot_id"])
    test["review_outcome"] = review_outcome
    test["reviewed_by_id"] = user_id
    if review_outcome == "APPROVE":
        test["status"] = "COA_APPROVED"
        if lot is not None:
            lot["status"] = "RELEASED"
            touch(lot)
    else:
        test["status"] = "COA_REJECTED"
        if lot is not None:
            lot["status"] = "REJECTED"
            touch(lot)
    touch(test)
    return ok(test)
