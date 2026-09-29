"""Derived sets, the risk index / posture recomputation and the posture cascades.

PRD sections 2.9 and 3.9.  Posture is never set directly by a request; it is
recomputed as a consequence, and a recomputation that lands on a different value
fires a posture transition with its own side effects.
"""

import calc
import db


# --- derived sets -----------------------------------------------------------

def active_lines(product_id):
    """The product's ACTIVE supplement-facts lines in ascending panel_position order."""
    rows = [
        r
        for r in db.all_rows("product_ingredients")
        if r["product_id"] == product_id and r["line_status"] == "ACTIVE"
    ]
    rows.sort(key=lambda r: r["panel_position"])
    return rows


def active_ingredient_ids(product_id):
    return [r["ingredient_id"] for r in active_lines(product_id)]


def products_with_active_line_on(ingredient_id):
    """Every product carrying `ingredient_id` on an ACTIVE line, in creation order."""
    seen = []
    for line in db.all_rows("product_ingredients"):
        if line["ingredient_id"] != ingredient_id or line["line_status"] != "ACTIVE":
            continue
        if line["product_id"] in seen:
            continue
        seen.append(line["product_id"])
    return [db.get("products", pid) for pid in seen if db.get("products", pid) is not None]


DERIVED_LOT_STATUSES = ("RELEASED", "RECALLED", "REJECTED")


def derived_supplier_ids(product):
    """PRD 2.9: suppliers of RELEASED/RECALLED/REJECTED lots of the product's active ingredients.

    A QUARANTINED lot never contributes a supplier.  An empty set satisfies every
    supplier condition vacuously.
    """
    ingredient_ids = set(active_ingredient_ids(product["id"]))
    result = []
    for lot in db.all_rows("lots"):
        if lot["lot_status"] not in DERIVED_LOT_STATUSES:
            continue
        if lot["ingredient_id"] not in ingredient_ids:
            continue
        if lot["supplier_id"] not in result:
            result.append(lot["supplier_id"])
    return result


def derived_suppliers(product):
    rows = []
    for supplier_id in derived_supplier_ids(product):
        row = db.get("suppliers", supplier_id)
        if row is not None:
            rows.append(row)
    return rows


def products_for_supplier(supplier_id):
    """Every product whose derived supplier set contains `supplier_id`."""
    return [p for p in db.all_rows("products") if supplier_id in derived_supplier_ids(p)]


def claims_of(product_id):
    return [c for c in db.all_rows("claims") if c["product_id"] == product_id]


def dossiers_of(claim_id):
    return [d for d in db.all_rows("dossiers") if d["claim_id"] == claim_id]


def panels_of(product_id):
    return [p for p in db.all_rows("panels") if p["product_id"] == product_id]


def required_warning_codes(product_id):
    codes = set([calc.ALWAYS_REQUIRED_CODE])
    for line in active_lines(product_id):
        ingredient = db.get("ingredients", line["ingredient_id"])
        if ingredient is None:
            continue
        if ingredient["allergen_code"] is not None:
            codes.add("ALLERGEN_" + ingredient["allergen_code"])
        if ingredient["contraindication_code"] is not None:
            codes.add("CONTRAINDICATION_" + ingredient["contraindication_code"])
    return sorted(codes)


def has_disclaimer_obligation(product_id):
    for claim in claims_of(product_id):
        if (
            claim["substantiation_status"] == "APPROVED"
            and claim["claim_type"] in calc.DISCLAIMER_CLAIM_TYPES
        ):
            return True
    return False


# --- risk index and posture -------------------------------------------------

def recompute_risk_index(product):
    """Recompute compliance_risk_index from the stored counters, then the posture."""
    product["compliance_risk_index"] = calc.risk_index(product)
    db.touch(product)
    recompute_posture(product)


def target_posture(product):
    index = product["compliance_risk_index"]
    suppliers = derived_suppliers(product)
    ingredients = [db.get("ingredients", i) for i in active_ingredient_ids(product["id"])]
    ingredients = [i for i in ingredients if i is not None]

    frozen = (
        index >= calc.FROZEN_THRESHOLD
        or any(s["qualification_status"] == "DISQUALIFIED" for s in suppliers)
        or any(i["eligibility_status"] == "NDI_OBJECTED" for i in ingredients)
    )
    if frozen:
        return "FROZEN"
    restricted = index >= calc.RESTRICTED_THRESHOLD or any(
        s["qualification_status"] == "PROBATION" for s in suppliers
    )
    if restricted:
        return "RESTRICTED"
    return "OPEN"


def recompute_posture(product):
    """Recompute the posture and, when it moves, fire the transition's side effects."""
    current = product["label_posture"]
    target = target_posture(product)
    if target == current:
        return current

    product["label_posture"] = target
    product["requires_label_revision"] = target != "OPEN"
    db.touch(product)

    if target == "RESTRICTED" and current == "OPEN":
        _retract_claim_work(product)
    elif target == "FROZEN":
        _dismantle_label(product)
    return target


def _retract_claim_work(product):
    """OPEN -> RESTRICTED: approved claims are pulled back for recheck (PRD 3.9)."""
    for claim in claims_of(product["id"]):
        if claim["substantiation_status"] != "APPROVED":
            continue
        claim["substantiation_status"] = "REVISION_REQUESTED"
        claim["requires_recheck"] = True
        db.touch(claim)
        product["active_claim_count"] -= 1
        db.touch(product)
        for dossier in dossiers_of(claim["id"]):
            if dossier["dossier_status"] != "ACCEPTED":
                continue
            dossier["dossier_status"] = "UNDER_REVIEW"
            dossier["reviewed_by_user_id"] = None
            dossier["reviewed_at"] = None
            dossier["review_decision"] = None
            db.touch(dossier)


def _dismantle_label(product):
    """OPEN|RESTRICTED -> FROZEN: every live panel is superseded (PRD 3.9)."""
    for panel in panels_of(product["id"]):
        if panel["panel_status"] not in ("DRAFT", "VALIDATED", "LOCKED"):
            continue
        panel["panel_status"] = "SUPERSEDED"
        db.touch(panel)
    if product["lifecycle_status"] == "LABEL_LOCKED":
        product["lifecycle_status"] = "DRAFT"
        db.touch(product)


# --- ledgers ----------------------------------------------------------------

def supplier_qualification_cascade(supplier):
    """Recompute the posture of every product whose derived supplier set holds this supplier."""
    for product in products_for_supplier(supplier["id"]):
        recompute_posture(product)


def ingredient_objection_cascade(ingredient):
    for product in products_with_active_line_on(ingredient["id"]):
        recompute_posture(product)


def recompute_line_dv(line):
    ingredient = db.get("ingredients", line["ingredient_id"])
    rdi = None if ingredient is None else ingredient["rdi_mg"]
    established, percent = calc.percent_dv(line["amount_per_serving_mg"], rdi)
    line["dv_established"] = established
    line["percent_dv_declared"] = percent
