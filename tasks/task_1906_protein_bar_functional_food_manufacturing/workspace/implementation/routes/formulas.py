"""Formulas, formula revisions, and claim reviews."""
from flask import Blueprint, request

import serialize
from db import STORES, base_record, touch
from errors import (
    not_found, invalid_request, invalid_state, terminal_locked, unprocessable,
    ERR_FORMULA_NOT_FOUND, ERR_REVISION_NOT_FOUND, ERR_CUSTOMER_NOT_FOUND,
    ERR_INGREDIENT_NOT_FOUND, ERR_CLAIM_REVIEW_NOT_FOUND,
    ERR_CUSTOMER_SUSPENDED, ERR_FORMULA_ARCHIVED, ERR_INGREDIENT_DISCONTINUED,
    ERR_LABEL_CLAIM_UNSUBSTANTIATED, ERR_CLAIM_REVIEW_INCOMPLETE,
    ERR_DISCLAIMER_REQUIRED,
)
from middleware import (
    require_roles, rep_list_scope, rep_owns_customer, revision_customer_id,
    scope_fail,
)
from response import ok_object, list_response
from services import calc
from services.inventory import cascade_supersede
from util import (
    get_body, require, opt, check_str, check_int, check_number, check_bool,
    check_enum, check_array, CLAIM_TAG_ENUM, CLAIM_TYPE_ENUM,
)

bp = Blueprint("formulas", __name__)

ALL_READ = ("PlantAdmin", "FormulationScientist", "QualityManager",
            "ProductionPlanner", "LabTechnician", "BrandCustomerRep")
FORMULA_STATUS = ["ACTIVE", "ARCHIVED"]
REVISION_STATUS = ["DRAFT", "SUBMITTED", "NUTRITION_VERIFIED", "CLAIM_REVIEW",
                   "APPROVED", "SUPERSEDED"]
REVIEW_STATUS = ["SUBMITTED", "IN_REVIEW", "APPROVED", "REVISION_REQUESTED"]


def _sorted(name):
    return sorted(STORES[name].values(), key=lambda r: r["_seq"])


def _get_formula(fid):
    rec = STORES["formulas"].get(fid)
    if rec is None:
        raise not_found(ERR_FORMULA_NOT_FOUND, f"Formula {fid} does not exist")
    return rec


def _get_revision(rid):
    rec = STORES["revisions"].get(rid)
    if rec is None:
        raise not_found(ERR_REVISION_NOT_FOUND, f"Revision {rid} does not exist")
    return rec


def _get_claim(crid):
    rec = STORES["claims"].get(crid)
    if rec is None:
        raise not_found(ERR_CLAIM_REVIEW_NOT_FOUND,
                        f"Claim review {crid} does not exist")
    return rec


def _compute_allergen_profile(ingredient_lines):
    seen = set()
    for line in ingredient_lines:
        ing = STORES["ingredients"].get(line["ingredient_id"])
        if ing:
            seen.update(ing.get("allergen_tags") or [])
    return sorted(seen)


def _recompute_claim_reviews(revision):
    """Recompute substantiation_ok on every non-terminal review (no version
    bump — only the revision's version increments on verify-nutrition)."""
    formula = STORES["formulas"].get(revision["formula_id"])
    for cr in STORES["claims"].values():
        if cr["revision_id"] == revision["id"] and cr["status"] != "APPROVED":
            cr["substantiation_ok"] = calc.claim_substantiation_ok(
                revision, formula, cr["claim_tag"])


# ---------------- formulas ----------------

@bp.post("/mfg/formulas")
def create_formula():
    uid, role = require_roles("FormulationScientist", "BrandCustomerRep")
    body = get_body(request)
    # Stage 3 scope for reps (evaluable only when customer_id was supplied)
    cid = body.get("customer_id")
    if role == "BrandCustomerRep" and cid is not None and cid != uid:
        scope_fail()
    # Stage 5 body FK
    customer = None
    if cid is not None:
        customer = STORES["customers"].get(cid)
        if customer is None:
            raise not_found(ERR_CUSTOMER_NOT_FOUND,
                            f"Brand customer {cid} does not exist")
    # Stage 6 shape
    if customer is None:
        raise invalid_request("Missing required field 'customer_id'")
    name = check_str(require(body, "name"), "name")
    bar_weight = check_number(require(body, "bar_weight_g"), "bar_weight_g", gt=0)
    servings = check_int(opt(body, "serving_count_per_bar", 1),
                         "serving_count_per_bar", min_v=1)
    status_raw = opt(body, "status", "ACTIVE")
    check_str(status_raw, "status")
    # Stage 7 enum
    status = check_enum(status_raw, "status", FORMULA_STATUS)
    # Business
    if customer["status"] != "ACTIVE":
        raise unprocessable(ERR_CUSTOMER_SUSPENDED,
                            "SUSPENDED customers cannot create formulas")
    rec = base_record()
    rec.update({
        "customer_id": customer["id"],
        "name": name,
        "bar_weight_g": bar_weight,
        "serving_count_per_bar": servings,
        "status": status,
    })
    STORES["formulas"][rec["id"]] = rec
    return ok_object(serialize.formula(rec), 201)


@bp.get("/mfg/formulas")
def list_formulas():
    uid, role = require_roles(*ALL_READ)
    scoped_cid = rep_list_scope(uid, role)
    items = _sorted("formulas")
    if scoped_cid is not None:
        items = [f for f in items if f["customer_id"] == scoped_cid]
    cid = request.args.get("customer_id")
    if cid is not None:
        items = [f for f in items if f["customer_id"] == cid]
    st = request.args.get("status")
    if st is not None:
        check_enum(st, "status", FORMULA_STATUS)
        items = [f for f in items if f["status"] == st]
    return list_response([serialize.formula(f) for f in items])


@bp.get("/mfg/formulas/<fid>")
def get_formula(fid):
    uid, role = require_roles(*ALL_READ)
    rec = _get_formula(fid)
    rep_owns_customer(uid, role, rec["customer_id"])
    return ok_object(serialize.formula(rec))


# ---------------- revisions ----------------

def _validate_ingredient_lines(body):
    """Stage 5 FK checks (where well-formed) then stage 6 shape checks."""
    raw = body.get("ingredient_lines")
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                iid = entry.get("ingredient_id")
                if isinstance(iid, str) and iid not in STORES["ingredients"]:
                    raise not_found(ERR_INGREDIENT_NOT_FOUND,
                                    f"Ingredient {iid} does not exist")
    lines = check_array(require(body, "ingredient_lines"), "ingredient_lines",
                        min_len=1)
    out = []
    for i, entry in enumerate(lines):
        if not isinstance(entry, dict):
            raise invalid_request(f"ingredient_lines[{i}] must be an object")
        iid = check_str(require(entry, "ingredient_id"),
                        "ingredient_lines.ingredient_id")
        qty = check_number(require(entry, "qty_kg_per_batch"),
                           "ingredient_lines.qty_kg_per_batch", gt=0)
        contrib = check_bool(require(entry, "is_protein_contributor"),
                             "ingredient_lines.is_protein_contributor")
        out.append({"ingredient_id": iid, "qty_kg_per_batch": qty,
                    "is_protein_contributor": contrib})
    return out


@bp.post("/mfg/formulas/<fid>/revisions")
def create_revision(fid):
    require_roles("FormulationScientist")
    formula = _get_formula(fid)
    body = get_body(request)
    lines = _validate_ingredient_lines(body)
    batch_size = check_number(require(body, "batch_size_kg"), "batch_size_kg", gt=0)
    target = check_number(require(body, "target_protein_g_per_serving"),
                          "target_protein_g_per_serving", gte=0)
    tags_raw = opt(body, "claim_tags", [])
    if not isinstance(tags_raw, list):
        raise invalid_request("Field 'claim_tags' must be an array")
    claim_tags = []
    for t in tags_raw:
        claim_tags.append(check_enum(t, "claim_tags", CLAIM_TAG_ENUM))
    if formula["status"] != "ACTIVE":
        raise unprocessable(ERR_FORMULA_ARCHIVED,
                            "ARCHIVED formulas cannot receive new revisions")
    rec = base_record()
    rev_no = sum(1 for r in STORES["revisions"].values()
                 if r["formula_id"] == fid) + 1
    rec.update({
        "formula_id": fid,
        "revision_no": rev_no,
        "ingredient_lines": lines,
        "batch_size_kg": batch_size,
        "target_protein_g_per_serving": target,
        "claim_tags": claim_tags,
        "allergen_profile": _compute_allergen_profile(lines),
        "label_protein_g_per_serving": None,
        "composite_protein_g_per_serving": None,
        "status": "DRAFT",
    })
    STORES["revisions"][rec["id"]] = rec
    return ok_object(serialize.revision(rec), 201)


@bp.get("/mfg/formulas/<fid>/revisions")
def list_revisions(fid):
    uid, role = require_roles(*ALL_READ)
    formula = _get_formula(fid)
    rep_owns_customer(uid, role, formula["customer_id"])
    items = [r for r in _sorted("revisions") if r["formula_id"] == fid]
    st = request.args.get("status")
    if st is not None:
        check_enum(st, "status", REVISION_STATUS)
        items = [r for r in items if r["status"] == st]
    return list_response([serialize.revision(r) for r in items])


@bp.get("/mfg/revisions/<rid>")
def get_revision(rid):
    uid, role = require_roles(*ALL_READ)
    rec = _get_revision(rid)
    rep_owns_customer(uid, role, revision_customer_id(rec))
    return ok_object(serialize.revision(rec))


def _revision_action(rid, allowed_from, target):
    rec = _get_revision(rid)
    if rec["status"] == "SUPERSEDED":
        raise terminal_locked("Revision is SUPERSEDED (terminal)")
    if rec["status"] not in allowed_from:
        raise invalid_state(
            f"Revision in status {rec['status']} cannot transition to {target}")
    return rec


@bp.post("/mfg/revisions/<rid>/submit")
def submit_revision(rid):
    require_roles("FormulationScientist")
    rec = _revision_action(rid, ("DRAFT",), "SUBMITTED")
    for line in rec["ingredient_lines"]:
        ing = STORES["ingredients"].get(line["ingredient_id"])
        if ing is None or ing["status"] != "ACTIVE":
            raise unprocessable(ERR_INGREDIENT_DISCONTINUED,
                                "Revision references a DISCONTINUED ingredient")
    formula = _get_formula(rec["formula_id"])
    if formula["status"] != "ACTIVE":
        raise unprocessable(ERR_FORMULA_ARCHIVED,
                            "Revision's formula is ARCHIVED")
    rec["status"] = "SUBMITTED"
    touch(rec)
    return ok_object(serialize.revision(rec))


@bp.post("/mfg/revisions/<rid>/verify-nutrition")
def verify_nutrition(rid):
    require_roles("QualityManager")
    rec = _revision_action(rid, ("SUBMITTED",), "NUTRITION_VERIFIED")
    formula = _get_formula(rec["formula_id"])
    label_value = calc.label_protein_per_serving(rec, formula)
    if not calc.nutrient_claims_satisfied(rec, label_value):
        raise unprocessable(
            ERR_LABEL_CLAIM_UNSUBSTANTIATED,
            "LABEL-variant substantiation fails a NUTRIENT_CONTENT claim")
    rec["label_protein_g_per_serving"] = label_value
    rec["status"] = "NUTRITION_VERIFIED"
    _recompute_claim_reviews(rec)
    touch(rec)
    return ok_object(serialize.revision(rec))


@bp.post("/mfg/revisions/<rid>/send-claim-review")
def send_claim_review(rid):
    require_roles("FormulationScientist")
    rec = _revision_action(rid, ("NUTRITION_VERIFIED",), "CLAIM_REVIEW")
    rec["status"] = "CLAIM_REVIEW"
    touch(rec)
    return ok_object(serialize.revision(rec))


@bp.post("/mfg/revisions/<rid>/approve")
def approve_revision(rid):
    require_roles("QualityManager")
    rec = _revision_action(rid, ("CLAIM_REVIEW",), "APPROVED")
    for tag in rec.get("claim_tags", []):
        approved = [c for c in STORES["claims"].values()
                    if c["revision_id"] == rid and c["claim_tag"] == tag
                    and c["status"] == "APPROVED"]
        if len(approved) != 1:
            raise unprocessable(
                ERR_CLAIM_REVIEW_INCOMPLETE,
                f"Claim tag {tag} lacks exactly one APPROVED claim review")
    previous = None
    for other in STORES["revisions"].values():
        if (other["formula_id"] == rec["formula_id"] and other["id"] != rid
                and other["status"] == "APPROVED"):
            previous = other
            break
    cascade_supersede(previous, rec)
    rec["status"] = "APPROVED"
    touch(rec)
    return ok_object(serialize.revision(rec))


@bp.post("/mfg/revisions/<rid>/reject-back")
def reject_back_revision(rid):
    require_roles("QualityManager")
    rec = _revision_action(rid, ("CLAIM_REVIEW",), "DRAFT")
    rec["status"] = "DRAFT"
    touch(rec)
    return ok_object(serialize.revision(rec))


@bp.get("/mfg/revisions/<rid>/shelf-life-studies")
def list_revision_studies(rid):
    require_roles("PlantAdmin", "FormulationScientist", "QualityManager",
                  "LabTechnician")
    _get_revision(rid)
    items = [s for s in _sorted("studies") if s["revision_id"] == rid]
    return list_response([serialize.study(s) for s in items])


@bp.get("/mfg/revisions/<rid>/claim-reviews")
def list_revision_claims(rid):
    uid, role = require_roles("PlantAdmin", "FormulationScientist",
                              "QualityManager", "BrandCustomerRep")
    rec = _get_revision(rid)
    rep_owns_customer(uid, role, revision_customer_id(rec))
    items = [c for c in _sorted("claims") if c["revision_id"] == rid]
    return list_response([serialize.claim(c) for c in items])


# ---------------- claim reviews ----------------

@bp.post("/mfg/claim-reviews")
def create_claim_review():
    uid, role = require_roles("FormulationScientist", "BrandCustomerRep")
    body = get_body(request)
    rid = body.get("revision_id")
    revision = STORES["revisions"].get(rid) if isinstance(rid, str) else None
    # Stage 3 rep scope (resolved through revision -> formula)
    if role == "BrandCustomerRep" and revision is not None:
        rep_owns_customer(uid, role, revision_customer_id(revision))
    # Stage 5 body FK
    if isinstance(rid, str) and revision is None:
        raise not_found(ERR_REVISION_NOT_FOUND, f"Revision {rid} does not exist")
    # Stage 6 shape
    if revision is None:
        raise invalid_request("Missing required field 'revision_id'")
    tag_raw = require(body, "claim_tag")
    check_str(tag_raw, "claim_tag")
    type_raw = require(body, "claim_type")
    check_str(type_raw, "claim_type")
    disclaimer = check_bool(opt(body, "structure_function_disclaimer", False),
                            "structure_function_disclaimer")
    # Stage 7 enum
    claim_tag = check_enum(tag_raw, "claim_tag", CLAIM_TAG_ENUM)
    claim_type = check_enum(type_raw, "claim_type", CLAIM_TYPE_ENUM)
    formula = STORES["formulas"].get(revision["formula_id"])
    rec = base_record()
    rec.update({
        "revision_id": revision["id"],
        "claim_tag": claim_tag,
        "claim_type": claim_type,
        "structure_function_disclaimer": disclaimer,
        "substantiation_ok": calc.claim_substantiation_ok(revision, formula,
                                                          claim_tag),
        "reviewer_id": None,
        "status": "SUBMITTED",
    })
    STORES["claims"][rec["id"]] = rec
    return ok_object(serialize.claim(rec), 201)


@bp.get("/mfg/claim-reviews/<crid>")
def get_claim_review(crid):
    require_roles("PlantAdmin", "FormulationScientist", "QualityManager",
                  "BrandCustomerRep")
    return ok_object(serialize.claim(_get_claim(crid)))


def _claim_action(crid, allowed_from):
    rec = _get_claim(crid)
    if rec["status"] not in allowed_from:
        raise invalid_state(
            f"Claim review in status {rec['status']} does not permit this action")
    return rec


@bp.post("/mfg/claim-reviews/<crid>/start-review")
def start_claim_review(crid):
    require_roles("QualityManager")
    rec = _claim_action(crid, ("SUBMITTED",))
    rec["status"] = "IN_REVIEW"
    touch(rec)
    return ok_object(serialize.claim(rec))


@bp.post("/mfg/claim-reviews/<crid>/approve")
def approve_claim_review(crid):
    uid, _role = require_roles("QualityManager")
    rec = _claim_action(crid, ("IN_REVIEW",))
    revision = STORES["revisions"].get(rec["revision_id"])
    if revision is None or revision["status"] not in ("NUTRITION_VERIFIED",
                                                      "CLAIM_REVIEW"):
        raise invalid_state(
            "Parent revision must be NUTRITION_VERIFIED or CLAIM_REVIEW")
    if not rec["substantiation_ok"]:
        raise unprocessable(ERR_LABEL_CLAIM_UNSUBSTANTIATED,
                            "Claim is not substantiated")
    if rec["claim_type"] == "STRUCTURE_FUNCTION" \
            and not rec["structure_function_disclaimer"]:
        raise unprocessable(ERR_DISCLAIMER_REQUIRED,
                            "STRUCTURE_FUNCTION approval requires the disclaimer")
    rec["status"] = "APPROVED"
    rec["reviewer_id"] = uid
    touch(rec)
    return ok_object(serialize.claim(rec))


@bp.post("/mfg/claim-reviews/<crid>/request-revision")
def request_claim_revision(crid):
    uid, _role = require_roles("QualityManager")
    rec = _claim_action(crid, ("IN_REVIEW",))
    rec["status"] = "REVISION_REQUESTED"
    rec["reviewer_id"] = uid
    touch(rec)
    return ok_object(serialize.claim(rec))


@bp.post("/mfg/claim-reviews/<crid>/resubmit")
def resubmit_claim_review(crid):
    require_roles("FormulationScientist", "BrandCustomerRep")
    rec = _claim_action(crid, ("REVISION_REQUESTED",))
    revision = STORES["revisions"].get(rec["revision_id"])
    formula = STORES["formulas"].get(revision["formula_id"]) if revision else None
    if revision is not None and formula is not None:
        rec["substantiation_ok"] = calc.claim_substantiation_ok(
            revision, formula, rec["claim_tag"])
    rec["status"] = "SUBMITTED"
    touch(rec)
    return ok_object(serialize.claim(rec))
