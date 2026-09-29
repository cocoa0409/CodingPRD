"""Derived-field recomputation and the declared cascades.

Nothing here seeds data: every function only reads or mutates rows that the
API itself created.
"""

import calculations as calc
import db
from errors import ApiError

# ---------------------------------------------------------------- lookups
_NOT_FOUND = {
    "grades": "ERR_GRADE_NOT_FOUND",
    "batches": "ERR_BATCH_NOT_FOUND",
    "geometries": "ERR_GEOMETRY_NOT_FOUND",
    "recipes": "ERR_RECIPE_NOT_FOUND",
    "coating_runs": "ERR_COATING_RUN_NOT_FOUND",
    "wheels": "ERR_WHEEL_NOT_FOUND",
    "grinding_runs": "ERR_GRINDING_RUN_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "dossiers": "ERR_DOSSIER_NOT_FOUND",
    "trials": "ERR_TRIAL_NOT_FOUND",
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "jobs": "ERR_JOB_NOT_FOUND",
}


def collection(name):
    return getattr(db, name)


def must_exist(name, row_id):
    coll = collection(name)
    row = coll.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(_NOT_FOUND[name], "No such resource: %s." % (row_id,))
    return row


def code_taken(name, field, value):
    for row in collection(name).values():
        if row.get(field) == value:
            return True
    return False


def require_unique(name, field, value):
    if code_taken(name, field, value):
        raise ApiError("ERR_DUPLICATE_CODE", "%s %r already exists." % (field, value))


def where(name, **filters):
    rows = []
    for row in collection(name).values():
        ok = True
        for key, value in filters.items():
            if row.get(key) != value:
                ok = False
                break
        if ok:
            rows.append(row)
    return db.ordered(rows)


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]


# ---------------------------------------------------------------- CarbideGrade
def grade_qualified_product_count(grade):
    n = 0
    for p in db.products.values():
        if p["grade_id"] == grade["id"] and p["release_status"] in ("RELEASED", "RESTRICTED"):
            n += 1
    return n


def grade_has_passed_batch(grade):
    for b in db.batches.values():
        if (
            b["grade_id"] == grade["id"]
            and b["stage"] == "SINTERED"
            and b["qc_status"] == "PASSED"
            and b["pinned_grade_revision"] == grade["revision"]
        ):
            return True
    return False


# ---------------------------------------------------------------- CoatingRecipe
def recipe_pool(recipe):
    return [
        r
        for r in db.coating_runs.values()
        if r["recipe_id"] == recipe["id"]
        and r["status"] == "COMPLETED"
        and r["pinned_recipe_revision"] == recipe["revision"]
    ]


def recipe_adhesion_class(recipe):
    pool = recipe_pool(recipe)
    classes = [r["adhesion_hf_class"] for r in pool if r["adhesion_hf_class"] is not None]
    if not classes:
        return None
    return min(classes)


def recipe_is_validated(recipe):
    total = calc.D(recipe["total_thickness_um"])
    tolerance = calc.THICKNESS_TOLERANCE_FRACTION * total
    for r in recipe_pool(recipe):
        if r["adhesion_hf_class"] is None or r["measured_thickness_um"] is None:
            continue
        if r["adhesion_hf_class"] > calc.MAX_VALIDATED_HF_CLASS:
            continue
        if abs(calc.D(r["measured_thickness_um"]) - total) <= tolerance:
            return True
    return False


# ---------------------------------------------------------------- GrindingWheel
def wheel_remaining(wheel):
    return wheel["initial_life_units"] - wheel["consumed_life_units"]


def wheel_charge(wheel, units):
    """Charge abrasive and apply the AVAILABLE -> DRESSING threshold move."""
    wheel["consumed_life_units"] = wheel["consumed_life_units"] + units
    if (
        wheel["status"] == "AVAILABLE"
        and wheel_remaining(wheel) < calc.DRESS_THRESHOLD_UNITS
    ):
        wheel["status"] = "DRESSING"
    db.touch(wheel)


def wheel_reverse(wheel, units):
    """Exact reversal used by grinding-run void."""
    wheel["consumed_life_units"] = wheel["consumed_life_units"] - units
    if (
        wheel["status"] == "DRESSING"
        and wheel_remaining(wheel) >= calc.DRESS_THRESHOLD_UNITS
    ):
        wheel["status"] = "AVAILABLE"
    db.touch(wheel)


# ---------------------------------------------------------------- ToolProduct
def product_open_order_units(product):
    total = 0
    for o in db.orders.values():
        if o["product_id"] == product["id"] and o["status"] in (
            "SUBMITTED",
            "ENGINEERING_REVIEW",
            "CONFIRMED",
            "ON_HOLD",
        ):
            total += o["quantity"]
    return total


def product_refs(product):
    grade = db.grades.get(product["grade_id"])
    geometry = db.geometries.get(product["geometry_id"])
    recipe = (
        db.recipes.get(product["coating_recipe_id"])
        if product["coating_recipe_id"]
        else None
    )
    return grade, geometry, recipe


def recompute_lead_time(product):
    grade, geometry, recipe = product_refs(product)
    days, eligible = calc.engineering_lead_time_days(
        product["order_class"],
        geometry["status"] if geometry else None,
        recipe,
        grade["status"] if grade else None,
    )
    changed = (
        product.get("engineering_lead_time_days") != days
        or product.get("expedite_eligible") != eligible
    )
    product["engineering_lead_time_days"] = days
    product["expedite_eligible"] = eligible
    return changed


def recompute_product_index(product):
    source = []
    for d in db.dossiers.values():
        if d["product_id"] != product["id"] or d["status"] != "APPROVED":
            continue
        for t in db.ordered(
            [t for t in db.trials.values() if t["dossier_id"] == d["id"]]
        ):
            if t["status"] == "COMPLETED" and t["verdict"] == "PASS":
                source.append(t)
    index, groups = calc.product_tool_life_index(source)
    product["tool_life_index"] = None if index is None else float(index)
    product["qualified_workpiece_groups"] = groups


def product_has_open_demand(product):
    for o in db.orders.values():
        if o["product_id"] == product["id"] and o["status"] in (
            "SUBMITTED",
            "ENGINEERING_REVIEW",
            "CONFIRMED",
            "ON_HOLD",
        ):
            return True
    return False


def supply_stocked_to_mto_cascade(product):
    """Hop 4: CONFIRMED orders on this product return to engineering review."""
    for o in db.ordered([o for o in db.orders.values() if o["product_id"] == product["id"]]):
        if o["status"] == "CONFIRMED":
            o["status"] = "ENGINEERING_REVIEW"
            o["requires_reconfirmation"] = True
            db.touch(o)


# ---------------------------------------------------------------- QualificationDossier
def dossier_trials(dossier):
    return db.ordered(
        [t for t in db.trials.values() if t["dossier_id"] == dossier["id"]]
    )


def dossier_completed_trials(dossier):
    return [t for t in dossier_trials(dossier) if t["status"] == "COMPLETED"]


def dossier_counters(dossier):
    completed = dossier_completed_trials(dossier)
    passed = [t for t in completed if t["verdict"] == "PASS"]
    product = db.products.get(dossier["product_id"])
    geometry = db.geometries.get(product["geometry_id"]) if product else None
    cls = geometry["application_class"] if geometry else None
    score = None
    if completed and cls is not None:
        score = calc.dossier_composite_score(cls, completed)
    return len(completed), len(passed), (None if score is None else float(score))


def dossier_passed_groups(dossier):
    groups = set()
    for t in dossier_completed_trials(dossier):
        if t["verdict"] == "PASS":
            groups.add(t["workpiece_group"])
    return sorted(groups)


# ---------------------------------------------------------------- Customer
def customer_reserved_credit(customer):
    total = 0
    for j in db.jobs.values():
        if j["customer_id"] == customer["id"] and j["status"] in (
            "RECEIVED",
            "INSPECTED",
            "REFURBISHED",
        ):
            total += j["reserved_credit_cents"]
    return total


def customer_orders(customer):
    return db.ordered(
        [o for o in db.orders.values() if o["customer_id"] == customer["id"]]
    )


def apply_credit_movement(customer, delta, allow_resume=True):
    """Applies delta then runs the hold / resume cascade of PRD 3.8."""
    customer["regrind_credit_cents"] = customer["regrind_credit_cents"] + delta
    if customer["account_status"] == "ACTIVE" and customer["regrind_credit_cents"] < 0:
        customer["account_status"] = "CREDIT_HOLD"
        for o in customer_orders(customer):
            if o["status"] in ("SUBMITTED", "ENGINEERING_REVIEW"):
                o["status"] = "ON_HOLD"
                o["hold_reason"] = "CREDIT_HOLD"
                db.touch(o)
    elif (
        allow_resume
        and customer["account_status"] == "CREDIT_HOLD"
        and customer["regrind_credit_cents"] >= 0
    ):
        customer["account_status"] = "ACTIVE"
        for o in customer_orders(customer):
            if o["status"] == "ON_HOLD":
                o["status"] = "SUBMITTED"
                o["hold_reason"] = None
                db.touch(o)


def customer_has_open_work(customer):
    for o in db.orders.values():
        if o["customer_id"] == customer["id"] and o["status"] in (
            "DRAFT",
            "SUBMITTED",
            "ENGINEERING_REVIEW",
            "CONFIRMED",
            "ON_HOLD",
        ):
            return True
    for j in db.jobs.values():
        if j["customer_id"] == customer["id"] and j["status"] in (
            "RECEIVED",
            "INSPECTED",
            "REFURBISHED",
        ):
            return True
    return False


# ---------------------------------------------------------------- ReconditionJob
def job_chain_length(job_id):
    """Number of predecessor hops behind job_id, inclusive of that job."""
    seen = set()
    length = 0
    cursor = job_id
    while cursor and cursor not in seen:
        seen.add(cursor)
        row = db.jobs.get(cursor)
        if row is None:
            break
        length += 1
        cursor = row.get("predecessor_job_id")
    return length


def predecessor_already_used(job_id):
    for j in db.jobs.values():
        if j.get("predecessor_job_id") == job_id:
            return True
    return False


# ---------------------------------------------------------------- restriction cascade
def revision_cascade(products, pin_field, new_revision):
    """Hops 2 to 4 of PRD 2.7, plus the lead-time recompute of every product.

    `products` is every product referencing the revised definition.  A product
    is mutated (version + 1) when the cascade restricted it or when the
    lead-time recomputation actually changed a stored value.
    """
    for product in db.ordered(products):
        pinned = product.get(pin_field)
        touched = False
        if (
            product["release_status"] == "RELEASED"
            and pinned is not None
            and pinned < new_revision
        ):
            product["release_status"] = "RESTRICTED"
            touched = True
            if product["supply_status"] == "STOCKED":
                product["supply_status"] = "MAKE_TO_ORDER"
                supply_stocked_to_mto_cascade(product)
        if recompute_lead_time(product):
            touched = True
        if touched:
            db.touch(product)


def recompute_lead_times_for(products):
    """Lead-time refresh outside the restriction cascade (geometry release)."""
    for product in db.ordered(products):
        if recompute_lead_time(product):
            db.touch(product)
