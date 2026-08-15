"""Formula endpoints: create, OCC-guarded update, approve, revise (PRD 3.1)."""
from flask import Blueprint

from db import store, new_entity, touch
from errors import (
    raise_error,
    ERR_FORMULA_STATE,
    ERR_FORMULA_INCOMPLETE,
    ERR_STALE_VERSION,
)
from middleware import require_roles, ANY_ROLE
from response import ok
from services import (
    check_tier_entries_shape,
    check_tier_ordering,
    compute_planned_weigh_qty,
    create_lines,
    formula_lines,
    normalize_tiers,
    validate_line_payload,
)
from util import (
    ALLERGEN_CLASSES,
    DOSAGE_FORMS,
    OVERAGE_BASES,
    body,
    invalid,
    is_int,
    not_found,
    paginate,
    req_enum,
    req_int,
    req_str,
    sorted_by_created,
)

bp = Blueprint("formulas", __name__)

_SCALAR_FIELDS = (
    "name",
    "dosage_form",
    "allergen_class",
    "min_order_qty",
    "batch_size_units",
    "shelf_life_months",
    "overage_basis",
)


def _validate_scalar_fields(data):
    name = req_str(data, "name")
    dosage_form = req_enum(data, "dosage_form", DOSAGE_FORMS)
    allergen_class = req_enum(data, "allergen_class", ALLERGEN_CLASSES)
    min_order_qty = req_int(data, "min_order_qty", min_val=1)
    batch_size_units = req_int(data, "batch_size_units", min_val=1)
    shelf_life_months = req_int(data, "shelf_life_months", min_val=1)
    overage_basis = req_enum(data, "overage_basis", OVERAGE_BASES)
    return {
        "name": name,
        "dosage_form": dosage_form,
        "allergen_class": allergen_class,
        "min_order_qty": min_order_qty,
        "batch_size_units": batch_size_units,
        "shelf_life_months": shelf_life_months,
        "overage_basis": overage_basis,
    }


def _read_optional_array(data, field):
    value = data.get(field)
    if value is None:
        return []
    if not isinstance(value, list):
        invalid("'%s' must be an array" % field)
    return value


@bp.post("/api/customers/<customer_id>/formulas")
@require_roles("ProductionPlanner")
def create_formula(user_id, role, customer_id):
    customer = store["customers"].get(customer_id)
    if customer is None:
        not_found()
    data = body()
    fields = _validate_scalar_fields(data)
    lines_payload = _read_optional_array(data, "lines")
    tiers = _read_optional_array(data, "price_tiers")
    for line in lines_payload:
        validate_line_payload(line)
    check_tier_entries_shape(tiers)
    check_tier_ordering(tiers, fields["min_order_qty"])

    formula = new_entity(dict(fields))
    formula.update({
        "customer_id": customer_id,
        "price_tiers": normalize_tiers(tiers),
        "revised_from_formula_id": None,
        "status": "DRAFT",
    })
    store["formulas"][formula["id"]] = formula
    create_lines(formula["id"], lines_payload)
    return ok(formula, 201)


@bp.get("/api/formulas/<formula_id>")
@require_roles(*ANY_ROLE)
def get_formula(user_id, role, formula_id):
    formula = store["formulas"].get(formula_id)
    if formula is None:
        not_found()
    return ok(formula)


@bp.put("/api/formulas/<formula_id>")
@require_roles("ProductionPlanner")
def update_formula(user_id, role, formula_id):
    formula = store["formulas"].get(formula_id)
    if formula is None:
        not_found()
    data = body()
    # Optimistic concurrency (PRD 2.8): checked before any business logic.
    expected = data.get("expected_formula_version")
    if not is_int(expected):
        invalid("'expected_formula_version' must carry the caller's last-observed version")
    if expected != formula["version"]:
        raise_error(
            ERR_STALE_VERSION,
            "expected_formula_version does not match the formula's current version",
        )
    if formula["status"] != "DRAFT":
        raise_error(ERR_FORMULA_STATE, "Only a DRAFT formula may be edited in place")

    updates = {}
    if "name" in data:
        updates["name"] = req_str(data, "name")
    if "dosage_form" in data:
        updates["dosage_form"] = req_enum(data, "dosage_form", DOSAGE_FORMS)
    if "allergen_class" in data:
        updates["allergen_class"] = req_enum(data, "allergen_class", ALLERGEN_CLASSES)
    if "min_order_qty" in data:
        updates["min_order_qty"] = req_int(data, "min_order_qty", min_val=1)
    if "batch_size_units" in data:
        updates["batch_size_units"] = req_int(data, "batch_size_units", min_val=1)
    if "shelf_life_months" in data:
        updates["shelf_life_months"] = req_int(data, "shelf_life_months", min_val=1)
    if "overage_basis" in data:
        updates["overage_basis"] = req_enum(data, "overage_basis", OVERAGE_BASES)

    lines_payload = data.get("lines")
    if lines_payload is not None:
        if not isinstance(lines_payload, list):
            invalid("'lines' must be an array")
        for line in lines_payload:
            validate_line_payload(line)

    tiers = data.get("price_tiers")
    if tiers is not None:
        if not isinstance(tiers, list):
            invalid("'price_tiers' must be an array")
        check_tier_entries_shape(tiers)
        effective_moq = updates.get("min_order_qty", formula["min_order_qty"])
        check_tier_ordering(tiers, effective_moq)

    # All validation passed; apply atomically.
    formula.update(updates)
    if lines_payload is not None:
        create_lines(formula_id, lines_payload)
    if tiers is not None:
        formula["price_tiers"] = normalize_tiers(tiers)
    touch(formula)
    return ok(formula)


@bp.get("/api/formulas/<formula_id>/lines")
@require_roles(*ANY_ROLE)
def list_formula_lines(user_id, role, formula_id):
    formula = store["formulas"].get(formula_id)
    if formula is None:
        not_found()
    items = sorted_by_created(formula_lines(formula_id))
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/api/formulas/<formula_id>/revisions")
@require_roles(*ANY_ROLE)
def list_formula_revisions(user_id, role, formula_id):
    formula = store["formulas"].get(formula_id)
    if formula is None:
        not_found()
    items = sorted_by_created(
        f for f in store["formulas"].values() if f.get("revised_from_formula_id") == formula_id
    )
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.post("/api/formulas/<formula_id>/approve")
@require_roles("QAManager")
def approve_formula(user_id, role, formula_id):
    formula = store["formulas"].get(formula_id)
    if formula is None:
        not_found()
    if formula["status"] != "DRAFT":
        raise_error(ERR_FORMULA_STATE, "Only a DRAFT formula may be approved")
    lines = formula_lines(formula_id)
    if len(lines) < 1:
        raise_error(ERR_FORMULA_INCOMPLETE, "Approval requires at least one formula line")
    label_claim_count = sum(1 for l in lines if l["is_label_claim_line"])
    if label_claim_count != 1:
        raise_error(
            ERR_FORMULA_INCOMPLETE,
            "Approval requires exactly one label-claim line",
        )
    tiers = formula["price_tiers"]
    if len(tiers) < 1:
        raise_error(ERR_FORMULA_INCOMPLETE, "Approval requires at least one price tier")
    check_tier_ordering(tiers, formula["min_order_qty"])

    for line in lines:
        line["planned_weigh_qty_mg"] = compute_planned_weigh_qty(formula, line)
        touch(line)
    formula["status"] = "APPROVED"
    touch(formula)

    predecessor_id = formula.get("revised_from_formula_id")
    if predecessor_id:
        predecessor = store["formulas"].get(predecessor_id)
        if predecessor is not None and predecessor["status"] == "APPROVED":
            predecessor["status"] = "SUPERSEDED"
            touch(predecessor)
    return ok(formula)


@bp.post("/api/formulas/<formula_id>/revise")
@require_roles("ProductionPlanner")
def revise_formula(user_id, role, formula_id):
    source = store["formulas"].get(formula_id)
    if source is None:
        not_found()
    if source["status"] != "APPROVED":
        raise_error(ERR_FORMULA_STATE, "Only an APPROVED formula may be revised")
    fields = {k: source[k] for k in _SCALAR_FIELDS}
    revision = new_entity(fields)
    revision.update({
        "customer_id": source["customer_id"],
        "price_tiers": [dict(t) for t in source["price_tiers"]],
        "revised_from_formula_id": source["id"],
        "status": "DRAFT",
    })
    store["formulas"][revision["id"]] = revision
    lines_payload = [
        {
            "raw_material_id": l["raw_material_id"],
            "theoretical_qty_mg_per_unit": l["theoretical_qty_mg_per_unit"],
            "overage_pct": l["overage_pct"],
            "is_label_claim_line": l["is_label_claim_line"],
            "label_claim_mg_per_unit": l["label_claim_mg_per_unit"],
        }
        for l in sorted_by_created(formula_lines(formula_id))
    ]
    create_lines(revision["id"], lines_payload)
    return ok(revision, 201)
