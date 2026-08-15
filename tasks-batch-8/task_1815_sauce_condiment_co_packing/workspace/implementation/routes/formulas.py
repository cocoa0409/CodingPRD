"""Formula endpoints: intake, listing, DRAFT spec update with OCC, and the
reformulate cascade (APPROVED -> DRAFT, letter supersede, run auto-cancel)."""
from flask import Blueprint, g, request

from db import STORE
from errors import (
    err,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_FORMULA_NOT_APPROVED,
    ERR_FORMULA_NOT_DRAFT,
    ERR_FORMULA_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
)
from middleware import check_customer_scope, require_roles
from response import paginate, success
from services.core import find_or_404, new_record, serialize, sorted_created, touch
from services.run_ops import cancel_run
from util import as_int, as_str, body_json, check_enum, req

bp = Blueprint("formulas", __name__)

PROCESS_CATEGORIES = ("ACIDIFIED", "LOW_ACID", "ACID")
ALLERGEN_CLASSES = ("NONE", "GLUTEN", "SOY", "NUT", "DAIRY")


@bp.post("/copack/formulas")
def create_formula():
    require_roles("OpsAdmin", "Customer")
    body = body_json()
    # Stage 3 (ownership) precedes stage 4 (existence): a Customer creating for
    # another brand is forbidden even before the referenced account resolves.
    raw_customer_id = body.get("customer_id")
    if isinstance(raw_customer_id, str):
        check_customer_scope(raw_customer_id)
    customer_id = as_str(req(body, "customer_id"), "customer_id")
    find_or_404(STORE.customers, customer_id, ERR_CUSTOMER_NOT_FOUND, "customer")
    product_name = as_str(req(body, "product_name"), "product_name")
    sku_code = as_str(req(body, "sku_code"), "sku_code")
    process_category = check_enum(
        as_str(req(body, "process_category"), "process_category"),
        PROCESS_CATEGORIES, "process_category",
    )
    allergen_class = check_enum(
        as_str(req(body, "allergen_class"), "allergen_class"),
        ALLERGEN_CLASSES, "allergen_class",
    )
    min_run_units = as_int(req(body, "min_run_units"), "min_run_units")
    if min_run_units < 1:
        raise err(ERR_INVALID_REQUEST, 400, "min_run_units must be >= 1")
    unit_rate_cents = as_int(req(body, "unit_rate_cents"), "unit_rate_cents")
    if unit_rate_cents < 0:
        raise err(ERR_INVALID_REQUEST, 400, "unit_rate_cents must be >= 0")
    rec = new_record({
        "customer_id": customer_id,
        "product_name": product_name,
        "sku_code": sku_code,
        "process_category": process_category,
        "allergen_class": allergen_class,
        "min_run_units": min_run_units,
        "unit_rate_cents": unit_rate_cents,
        "revision": 1,
        "status": "DRAFT",
    })
    STORE.formulas[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/copack/formulas")
def list_formulas():
    require_roles("OpsAdmin", "QAReviewer", "Customer")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = []
    for f in sorted_created(STORE.formulas.values()):
        if g.user_role == "Customer" and f["customer_id"] != g.user_id:
            continue
        if customer_id is not None and f["customer_id"] != customer_id:
            continue
        if status is not None and f["status"] != status:
            continue
        items.append(serialize(f))
    return paginate(items)


@bp.get("/copack/formulas/<fid>")
def get_formula(fid):
    require_roles("OpsAdmin", "QAReviewer", "Customer")
    rec = find_or_404(STORE.formulas, fid, ERR_FORMULA_NOT_FOUND, "formula")
    check_customer_scope(rec["customer_id"])
    return success(serialize(rec))


@bp.put("/copack/formulas/<fid>")
def update_formula(fid):
    require_roles("OpsAdmin", "Customer")
    rec = find_or_404(STORE.formulas, fid, ERR_FORMULA_NOT_FOUND, "formula")
    check_customer_scope(rec["customer_id"])
    body = body_json()
    expected = as_int(req(body, "expected_formula_version"), "expected_formula_version")
    # Validate any provided spec fields (request shape, stage 5).
    updates = {}
    if "product_name" in body and body["product_name"] is not None:
        updates["product_name"] = as_str(body["product_name"], "product_name")
    if "process_category" in body and body["process_category"] is not None:
        updates["process_category"] = check_enum(
            as_str(body["process_category"], "process_category"),
            PROCESS_CATEGORIES, "process_category",
        )
    if "allergen_class" in body and body["allergen_class"] is not None:
        updates["allergen_class"] = check_enum(
            as_str(body["allergen_class"], "allergen_class"),
            ALLERGEN_CLASSES, "allergen_class",
        )
    if "min_run_units" in body and body["min_run_units"] is not None:
        v = as_int(body["min_run_units"], "min_run_units")
        if v < 1:
            raise err(ERR_INVALID_REQUEST, 400, "min_run_units must be >= 1")
        updates["min_run_units"] = v
    if "unit_rate_cents" in body and body["unit_rate_cents"] is not None:
        v = as_int(body["unit_rate_cents"], "unit_rate_cents")
        if v < 0:
            raise err(ERR_INVALID_REQUEST, 400, "unit_rate_cents must be >= 0")
        updates["unit_rate_cents"] = v
    # Stage 6: the spec may only move while the formula is in DRAFT.
    if rec["status"] != "DRAFT":
        raise err(ERR_FORMULA_NOT_DRAFT, 409, "formula is no longer in DRAFT")
    # Optimistic concurrency (§2.5).
    if rec["version"] != expected:
        raise err(ERR_STALE_VERSION, 412, "expected_formula_version does not match the current version")
    rec.update(updates)
    touch(rec)
    return success(serialize(rec))


@bp.post("/copack/formulas/<fid>/reformulate")
def reformulate_formula(fid):
    require_roles("OpsAdmin", "Customer")
    rec = find_or_404(STORE.formulas, fid, ERR_FORMULA_NOT_FOUND, "formula")
    check_customer_scope(rec["customer_id"])
    if rec["status"] != "APPROVED":
        raise err(ERR_FORMULA_NOT_APPROVED, 409, "only an APPROVED formula can be reformulated")
    customer = STORE.customers.get(rec["customer_id"])
    # Cascade: the ACTIVE letter is superseded.
    for letter in STORE.letters.values():
        if letter["formula_id"] == fid and letter["status"] == "ACTIVE":
            letter["status"] = "SUPERSEDED"
            touch(letter)
    # Cascade: every PLANNED/CONFIRMED run of this formula is cancelled, with
    # the full CONFIRMED unwind (reservations, consignment, estimate refund).
    for run in list(STORE.runs.values()):
        if run["formula_id"] == fid and run["status"] in ("PLANNED", "CONFIRMED"):
            cancel_run(run, customer)
    rec["status"] = "DRAFT"
    rec["revision"] += 1
    touch(rec)
    return success(serialize(rec))
