"""Formula and FormulaComponent endpoints (PRD §3.3, §3.4, §3.5, §2.9)."""

from decimal import Decimal

from flask import Blueprint, request

import constants as K
import serializers as S
from db import base_entity, db, now_logical, touch
from errors import fail
from middleware import ALL_ROLES, auth
from response import created, no_content, ok, ok_array
from routes.common import list_response, need
from services import cascade, costing, graph, ledger
from validate import (as_bool, as_decimal, as_enum, as_int, as_str, body_json,
                      optional, present, require)

bp = Blueprint("formulas", __name__)

EDITABLE = ("DRAFT", "COSTED", "REWORK_REQUIRED")
DELETE_BLOCKED = ("SUBMITTED", "APPROVED", "SUPERSEDED", "ARCHIVED")


def _formula(formula_id):
    return need(db.formulas, formula_id, "ERR_FORMULA_NOT_FOUND", "formula")


def _new_formula(brief, name, parent_formula_id, tier):
    formula = base_entity()
    formula.update({
        "brief_id": brief["id"],
        "parent_formula_id": parent_formula_id,
        "superseded_by_formula_id": None,
        "name": name,
        "iteration_no": len(ledger.formulas_of_brief(brief["id"])) + 1,
        "confidentiality_tier": tier,
        "status": "DRAFT",
        "bench_cost_per_kg_cents": None,
        "bench_cost_in_use_cents_per_tonne": None,
        "firm_cost_in_use_cents_per_tonne": None,
        "allergen_codes": [],
        "natural_claim_eligible": None,
        "kosher_eligible": None,
        "halal_eligible": None,
        "cost_stale": False,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "rework_reason": None,
    })
    db.formulas[formula["id"]] = formula
    return formula


def _fallback_to_draft(formula):
    """§3.3: editing composition invalidates any costing already done."""
    if formula["status"] in ("COSTED", "REWORK_REQUIRED"):
        formula["status"] = "DRAFT"
        costing.clear_cost_and_claim(formula)
        touch(formula)


@bp.post("/formulas")
def create_formula():
    auth(["Flavorist"])
    body = body_json()
    brief_id = as_str(require(body, "brief_id"), "brief_id")
    name = as_str(require(body, "name"), "name", 1, 120)
    parent_formula_id = optional(body, "parent_formula_id")
    if parent_formula_id is not None:
        parent_formula_id = as_str(parent_formula_id, "parent_formula_id")
    tier = optional(body, "confidentiality_tier")
    if tier is not None:
        tier = as_enum(tier, "confidentiality_tier", K.TIERS)

    brief = need(db.briefs, brief_id, "ERR_BRIEF_NOT_FOUND", "customer brief")
    parent = None
    if parent_formula_id is not None:
        parent = _formula(parent_formula_id)
        if parent["brief_id"] != brief_id:
            fail("ERR_PARENT_FORMULA_MISMATCH",
                 "parent formula belongs to a different brief")

    if tier is None:
        tier = brief["confidentiality_tier"]
    formula = _new_formula(brief, name, parent_formula_id, tier)
    return created(S.formula_out(formula))


@bp.get("/formulas")
def list_formulas():
    auth(ALL_ROLES)
    brief_id = request.args.get("brief_id")
    parent_formula_id = request.args.get("parent_formula_id")
    superseded_by = request.args.get("superseded_by_formula_id")
    status = request.args.get("status")
    rows = []
    for formula in db.formulas.values():
        if brief_id is not None and formula["brief_id"] != brief_id:
            continue
        if parent_formula_id is not None and \
                formula["parent_formula_id"] != parent_formula_id:
            continue
        if superseded_by is not None and \
                formula["superseded_by_formula_id"] != superseded_by:
            continue
        if status is not None and formula["status"] != status:
            continue
        rows.append(formula)
    return list_response(rows, S.formula_out)


@bp.get("/formulas/<formula_id>")
def get_formula(formula_id):
    auth(ALL_ROLES)
    return ok(S.formula_out(_formula(formula_id)))


def _disclose_full_flag():
    """Parsed after the tier/expiry rungs but before the redaction rung."""
    raw = request.args.get("disclose_full")
    if raw is None:
        return False
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    fail("ERR_INVALID_REQUEST", "disclose_full must be true or false")


@bp.get("/formulas/<formula_id>/composition")
def read_composition(formula_id):
    auth(ALL_ROLES)
    formula = _formula(formula_id)
    grant_id = request.args.get("grant_id")
    grant = db.grants.get(grant_id) if grant_id is not None else None
    tier = formula["confidentiality_tier"]

    # priority 24 - tier and grant
    if K.TIER_RANK[tier] > K.TIER_RANK["TIER_1_STANDARD"]:
        if grant is None:
            fail("ERR_IP_TIER_FORBIDDEN",
                 "reading a %s composition requires a disclosure grant" % tier)
        if grant["formula_id"] != formula["id"]:
            fail("ERR_IP_TIER_FORBIDDEN",
                 "the grant was issued for a different formula")
        if K.TIER_RANK[grant["disclosed_tier"]] < K.TIER_RANK[tier]:
            fail("ERR_IP_TIER_FORBIDDEN",
                 "the grant's disclosed_tier does not reach %s" % tier)
    elif grant_id is not None and grant is None:
        fail("ERR_GRANT_NOT_FOUND", "disclosure grant %s does not exist" % grant_id)

    # priority 26 - the grant must be live
    if grant is not None and not now_logical() < grant["expires_at"]:
        fail("ERR_DISCLOSURE_GRANT_EXPIRED", "the disclosure grant has expired")

    # priority 28 - only a FULL grant un-redacts
    disclose_full = _disclose_full_flag()
    if disclose_full and (grant is None or grant["redaction_level"] != "FULL"):
        fail("ERR_REDACTION_LEVEL_INSUFFICIENT",
             "disclose_full requires a grant with redaction_level FULL")

    redacted = grant is not None and grant["redaction_level"] == "REDACTED"
    rows = []
    for index, line in enumerate(graph.components_of(formula["id"])):
        if redacted:
            rows.append(S.component_redacted_out(line, index + 1))
        else:
            rows.append(S.component_out(line, index + 1))
    return ok_array(rows)


@bp.post("/formulas/<formula_id>/components")
def add_component(formula_id):
    auth(["Flavorist"])
    body = body_json()
    component_type = as_enum(require(body, "component_type"), "component_type",
                             K.COMPONENT_TYPES)
    raw_material_id = optional(body, "raw_material_id")
    if raw_material_id is not None:
        raw_material_id = as_str(raw_material_id, "raw_material_id")
    sub_formula_id = optional(body, "sub_formula_id")
    if sub_formula_id is not None:
        sub_formula_id = as_str(sub_formula_id, "sub_formula_id")
    weight_pct = as_decimal(require(body, "weight_pct"), "weight_pct", 4,
                            gt=0, le=100)

    formula = _formula(formula_id)

    material = None
    if raw_material_id is not None:
        material = need(db.materials, raw_material_id, "ERR_MATERIAL_NOT_FOUND",
                        "raw material")
    if sub_formula_id is not None:
        need(db.formulas, sub_formula_id, "ERR_FORMULA_NOT_FOUND", "formula")

    # priority 38 - polymorphic shape
    if component_type == "RAW_MATERIAL":
        if raw_material_id is None or sub_formula_id is not None:
            fail("ERR_COMPONENT_TYPE_MISMATCH",
                 "a RAW_MATERIAL line carries raw_material_id only")
    else:
        if sub_formula_id is None or raw_material_id is not None:
            fail("ERR_COMPONENT_TYPE_MISMATCH",
                 "a SUB_FORMULA line carries sub_formula_id only")

    if formula["status"] not in EDITABLE:
        fail("ERR_FORMULA_STATE_INVALID",
             "cannot edit the composition of a %s formula" % formula["status"])

    # priority 57 - safety ceiling
    if component_type == "RAW_MATERIAL":
        ceiling = Decimal(material["max_use_ppm"]) / Decimal(10000)
        if weight_pct > ceiling:
            fail("ERR_MAX_USE_EXCEEDED",
                 "weight_pct exceeds the material ceiling of %s percent" % ceiling)

    # priority 60 - the component DAG stays acyclic
    if component_type == "SUB_FORMULA":
        if sub_formula_id == formula["id"] or \
                graph.reaches_formula(sub_formula_id, formula["id"]):
            fail("ERR_FORMULA_CYCLE",
                 "the referenced sub-formula would create a cycle")

    # priority 62 - the running weight sum
    if graph.total_weight_pct(formula["id"]) + weight_pct > Decimal("100.0000"):
        fail("ERR_WEIGHT_SUM_INVALID",
             "the line would drive total_weight_pct above 100.0000")

    component = base_entity()
    component.update({
        "formula_id": formula["id"],
        "component_type": component_type,
        "raw_material_id": raw_material_id,
        "sub_formula_id": sub_formula_id,
        "weight_pct": weight_pct,
        "contribution_cents": None,
    })
    db.components[component["id"]] = component
    _fallback_to_draft(formula)
    return created(S.component_out(component))


@bp.post("/formulas/<formula_id>/cost")
def cost_formula(formula_id):
    auth(["Flavorist"])
    body_json()
    formula = _formula(formula_id)
    if formula["status"] != "DRAFT":
        fail("ERR_FORMULA_STATE_INVALID",
             "cannot cost a formula in status %s" % formula["status"])

    lines = graph.components_of(formula["id"])
    for line in lines:
        if line["component_type"] != "SUB_FORMULA":
            continue
        sub = db.formulas.get(line["sub_formula_id"])
        if sub is None or sub["status"] not in ("COSTED", "APPROVED"):
            fail("ERR_SUB_FORMULA_NOT_COSTED",
                 "sub-formula %s is not costed" % line["sub_formula_id"])

    if not lines:
        fail("ERR_FORMULA_NO_COMPONENTS", "an empty formula cannot be costed")

    if graph.total_weight_pct(formula["id"]) != Decimal("100.0000"):
        fail("ERR_WEIGHT_SUM_INVALID",
             "total_weight_pct must equal 100.0000 exactly at costing time")

    brief = db.briefs.get(formula["brief_id"])
    costing.apply_bench_cost(formula)
    costing.apply_cost_in_use(formula, brief)
    costing.apply_claim_profile(formula)
    formula["status"] = "COSTED"
    touch(formula)
    return ok(S.formula_out(formula))


@bp.post("/formulas/<formula_id>/submit")
def submit_formula(formula_id):
    user_id, _role = auth(["Flavorist"])
    body_json()
    formula = _formula(formula_id)
    if formula["status"] != "COSTED":
        fail("ERR_FORMULA_STATE_INVALID",
             "cannot submit a formula in status %s" % formula["status"])

    brief = db.briefs.get(formula["brief_id"])
    if brief is None or brief["status"] != "ACCEPTED":
        fail("ERR_BRIEF_NOT_ACCEPTED",
             "the owning brief is not in ACCEPTED")

    overlap = set(formula["allergen_codes"]) & set(brief["allergen_exclusions"])
    if overlap:
        fail("ERR_ALLERGEN_EXCLUSION_BREACH",
             "the formula carries excluded allergens: %s"
             % ", ".join(sorted(overlap)))

    for claim in graph.required_claim_set(brief):
        flag = cascade.ELIGIBILITY_FLAG[claim]
        if not formula.get(flag):
            fail("ERR_CLAIM_UNSUBSTANTIATED",
                 "the brief requires the %s claim" % claim)

    if formula["bench_cost_in_use_cents_per_tonne"] > \
            brief["cost_in_use_cap_cents_per_tonne"]:
        fail("ERR_COST_IN_USE_CAP_EXCEEDED",
             "bench cost in use exceeds the brief's cap")

    formula["status"] = "SUBMITTED"
    formula["submitted_by_user_id"] = user_id
    touch(formula)
    return ok(S.formula_out(formula))


@bp.post("/formulas/<formula_id>/decision")
def decide_formula(formula_id):
    user_id, _role = auth(["TechnicalDirector"])
    body = body_json()
    decision = as_enum(require(body, "decision"), "decision",
                       ("APPROVED", "REWORK_REQUIRED"))
    if present(body, "decision_note"):
        as_str(body["decision_note"], "decision_note")

    formula = _formula(formula_id)
    if formula["status"] != "SUBMITTED":
        fail("ERR_FORMULA_STATE_INVALID",
             "cannot decide a formula in status %s" % formula["status"])

    brief = db.briefs.get(formula["brief_id"])
    if decision == "APPROVED" and (brief is None or brief["status"] != "ACCEPTED"):
        fail("ERR_BRIEF_NOT_ACCEPTED", "the owning brief is not in ACCEPTED")

    if formula["submitted_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the approver may not be the submitter")

    if decision == "APPROVED":
        formula["status"] = "APPROVED"
        formula["approved_by_user_id"] = user_id
        touch(formula)
        if brief is not None:
            for forecast in ledger.forecasts_of_brief(brief["id"]):
                if forecast["status"] not in ("ACTIVE", "AT_RISK"):
                    continue
                forecast["status"] = "ACTIVE"
                cascade.revalue_forecast(forecast, brief)
                touch(forecast)
    else:
        formula["status"] = "REWORK_REQUIRED"
        formula["rework_reason"] = "DIRECTOR_REJECTION"
        touch(formula)
        if brief is not None:
            for forecast in ledger.forecasts_of_brief(brief["id"]):
                if forecast["status"] != "ACTIVE":
                    continue
                cascade.revalue_forecast(forecast, brief)
                touch(forecast)
    return ok(S.formula_out(formula))


@bp.post("/formulas/<formula_id>/revisions")
def revise_formula(formula_id):
    auth(["Flavorist"])
    body = body_json()
    name = as_str(require(body, "name"), "name", 1, 120)
    expected = as_int(require(body, "expected_formula_version"),
                      "expected_formula_version", minimum=1)
    carry = optional(body, "carry_components", False)
    carry = as_bool(carry, "carry_components")

    formula = _formula(formula_id)
    if formula["status"] not in ("APPROVED", "REWORK_REQUIRED"):
        fail("ERR_FORMULA_NOT_REVISABLE",
             "a formula in status %s cannot be revised" % formula["status"])
    if expected != formula["version"]:
        fail("ERR_STALE_FORMULA_VERSION",
             "expected_formula_version %s does not match the current version %s"
             % (expected, formula["version"]))

    brief = db.briefs.get(formula["brief_id"])
    successor = _new_formula(brief, name, formula["id"],
                             formula["confidentiality_tier"])
    if carry:
        for line in graph.components_of(formula["id"]):
            copy = base_entity()
            copy.update({
                "formula_id": successor["id"],
                "component_type": line["component_type"],
                "raw_material_id": line["raw_material_id"],
                "sub_formula_id": line["sub_formula_id"],
                "weight_pct": line["weight_pct"],
                "contribution_cents": None,
            })
            db.components[copy["id"]] = copy

    formula["status"] = "SUPERSEDED"
    formula["superseded_by_formula_id"] = successor["id"]
    touch(formula)
    cascade.cancel_batches_for_supersession(
        formula["id"], "PARENT_SUPERSEDED",
        statuses=("REQUESTED", "TOLERANCE_SET"))
    return created(S.formula_out(successor))


# --- FormulaComponent -------------------------------------------------------

@bp.get("/formula-components")
def list_components():
    auth(ALL_ROLES)
    formula_id = request.args.get("formula_id")
    raw_material_id = request.args.get("raw_material_id")
    sub_formula_id = request.args.get("sub_formula_id")
    component_type = request.args.get("component_type")
    rows = []
    for line in db.components.values():
        if formula_id is not None and line["formula_id"] != formula_id:
            continue
        if raw_material_id is not None and line["raw_material_id"] != raw_material_id:
            continue
        if sub_formula_id is not None and line["sub_formula_id"] != sub_formula_id:
            continue
        if component_type is not None and line["component_type"] != component_type:
            continue
        rows.append(line)
    return list_response(rows, S.component_out)


@bp.get("/formula-components/<component_id>")
def get_component(component_id):
    auth(ALL_ROLES)
    component = need(db.components, component_id, "ERR_COMPONENT_NOT_FOUND",
                     "formula component")
    return ok(S.component_out(component))


@bp.delete("/formula-components/<component_id>")
def delete_component(component_id):
    auth(["Flavorist"])
    component = need(db.components, component_id, "ERR_COMPONENT_NOT_FOUND",
                     "formula component")
    formula = db.formulas.get(component["formula_id"])
    if formula is not None and formula["status"] in DELETE_BLOCKED:
        fail("ERR_FORMULA_STATE_INVALID",
             "cannot delete a line from a %s formula" % formula["status"])
    del db.components[component_id]
    if formula is not None:
        _fallback_to_draft(formula)
    return no_content()
