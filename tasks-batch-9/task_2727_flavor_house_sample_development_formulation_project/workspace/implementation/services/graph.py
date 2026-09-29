"""Component-DAG traversal helpers (PRD §1 / §3.3, scaffold §1.3)."""

from decimal import Decimal

from db import db, by_creation, now_logical


def components_of(formula_id):
    """The formula's component lines in ascending creation order.

    sequence_no is derived from this ordering, so the list index + 1 *is* the
    sequence_no of each line (contiguous by construction, §3.3).
    """
    rows = [c for c in db.components.values() if c["formula_id"] == formula_id]
    return by_creation(rows)


def sequence_no_of(component):
    rows = components_of(component["formula_id"])
    for index, row in enumerate(rows):
        if row["id"] == component["id"]:
            return index + 1
    return None


def component_count(formula_id):
    return len(components_of(formula_id))


def total_weight_pct(formula_id):
    total = Decimal("0")
    for line in components_of(formula_id):
        total += line["weight_pct"]
    return total.quantize(Decimal("0.0001"))


def leaf_materials(formula_id, seen=None):
    """Transitive raw-material leaves, de-duplicated, in traversal order."""
    if seen is None:
        seen = set()
    if formula_id in seen:
        return []
    seen.add(formula_id)
    out = []
    for line in components_of(formula_id):
        if line["component_type"] == "RAW_MATERIAL":
            if line["raw_material_id"] not in out:
                out.append(line["raw_material_id"])
        else:
            for material_id in leaf_materials(line["sub_formula_id"], seen):
                if material_id not in out:
                    out.append(material_id)
    return out


def reaches_formula(start_formula_id, target_formula_id, seen=None):
    """True when start transitively contains target below it."""
    if seen is None:
        seen = set()
    if start_formula_id in seen:
        return False
    seen.add(start_formula_id)
    for line in components_of(start_formula_id):
        if line["component_type"] != "SUB_FORMULA":
            continue
        if line["sub_formula_id"] == target_formula_id:
            return True
        if reaches_formula(line["sub_formula_id"], target_formula_id, seen):
            return True
    return False


def formula_contains_material(formula_id, material_id):
    return material_id in leaf_materials(formula_id)


def formulas_containing_material(material_id):
    return [f for f in by_creation(list(db.formulas.values()))
            if formula_contains_material(f["id"], material_id)]


# --- certificate helpers -----------------------------------------------------

def substantiated(material_id, claim_type):
    """A VERIFIED record for the claim whose valid_until >= the logical clock."""
    clock = now_logical()
    for record in db.records.values():
        if record["raw_material_id"] != material_id:
            continue
        if record["claim_type"] != claim_type:
            continue
        if record["status"] != "VERIFIED":
            continue
        if record["valid_until"] >= clock:
            return True
    return False


def material_claim_status(material_id):
    for record in db.records.values():
        if record["raw_material_id"] == material_id and record["status"] == "REVOKED":
            return "RESTRICTED"
    return "CLEAR"


def material_verified_claim_types(material_id):
    found = set()
    for claim in ("ALLERGEN_FREE_STATEMENT", "HALAL", "KOSHER", "NATURAL"):
        if substantiated(material_id, claim):
            found.add(claim)
    return sorted(found)


def required_claim_set(brief):
    """The claims a brief demands (§3.2)."""
    required = []
    if brief.get("natural_claim_required"):
        required.append("NATURAL")
    if brief.get("kosher_required"):
        required.append("KOSHER")
    if brief.get("halal_required"):
        required.append("HALAL")
    return required


def brief_of_formula(formula):
    return db.briefs.get(formula["brief_id"])


def brief_of_lot(lot):
    formula = db.formulas.get(lot["formula_id"])
    if formula is None:
        return None
    return db.briefs.get(formula["brief_id"])
