"""ProcessAuthorityLetter endpoints: submission (statutory process bounds),
activation (revision freshness gate, supersede of other ACTIVE letters,
TRIAL_PASSED -> APPROVED), and reads."""
from flask import Blueprint, g, request

from db import STORE
from errors import (
    err,
    ERR_FORMULA_NOT_FOUND,
    ERR_FORMULA_NOT_TRIAL_PASSED,
    ERR_INVALID_PROCESS_LIMITS,
    ERR_INVALID_REQUEST,
    ERR_LETTER_NOT_FOUND,
    ERR_LETTER_NOT_SUBMITTED,
    ERR_LETTER_REVISION_STALE,
)
from middleware import check_customer_scope, require_roles
from response import paginate, success
from services.core import find_or_404, new_record, serialize, sorted_created, touch
from util import as_int, as_num, as_str, body_json, req

bp = Blueprint("letters", __name__)


@bp.post("/copack/process-authority-letters")
def create_letter():
    require_roles("ProcessAuthority")
    body = body_json()
    raw_formula_id = body.get("formula_id")
    if isinstance(raw_formula_id, str):
        find_or_404(STORE.formulas, raw_formula_id, ERR_FORMULA_NOT_FOUND, "formula")
    formula_id = as_str(req(body, "formula_id"), "formula_id")
    formula = find_or_404(STORE.formulas, formula_id, ERR_FORMULA_NOT_FOUND, "formula")
    formula_revision = as_int(req(body, "formula_revision"), "formula_revision")
    if formula_revision < 1:
        raise err(ERR_INVALID_REQUEST, 400, "formula_revision must be >= 1")
    authority_name = as_str(req(body, "authority_name"), "authority_name")
    letter_number = as_str(req(body, "letter_number"), "letter_number")
    max_ph = as_num(req(body, "max_ph"), "max_ph")
    max_water_activity = as_num(req(body, "max_water_activity"), "max_water_activity")
    # Stage 6: the formula must be in TRIAL_PASSED or APPROVED.
    if formula["status"] not in ("TRIAL_PASSED", "APPROVED"):
        raise err(ERR_FORMULA_NOT_TRIAL_PASSED, 409, "formula must be TRIAL_PASSED or APPROVED to submit a letter")
    # Stage 7: scheduled-process limits sit inside the statutory bounds:
    # 0 < max_ph < 4.6 and 0 < max_water_activity < 1.0 (PRD §3.3).
    if not (0 < max_ph < 4.6) or not (0 < max_water_activity < 1.0):
        raise err(ERR_INVALID_PROCESS_LIMITS, 422, "process limits fall outside the statutory bounds")
    rec = new_record({
        "formula_id": formula_id,
        "formula_revision": formula_revision,
        "authority_name": authority_name,
        "letter_number": letter_number,
        "max_ph": max_ph,
        "max_water_activity": max_water_activity,
        "status": "SUBMITTED",
    })
    STORE.letters[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/copack/process-authority-letters")
def list_letters():
    require_roles("OpsAdmin", "QAReviewer", "ProcessAuthority", "Customer")
    formula_id = request.args.get("formula_id")
    items = []
    for letter in sorted_created(STORE.letters.values()):
        if g.user_role == "Customer":
            f = STORE.formulas.get(letter["formula_id"])
            if f is None or f["customer_id"] != g.user_id:
                continue
        if formula_id is not None and letter["formula_id"] != formula_id:
            continue
        items.append(serialize(letter))
    return paginate(items)


@bp.get("/copack/process-authority-letters/<lid>")
def get_letter(lid):
    require_roles("OpsAdmin", "QAReviewer", "ProcessAuthority", "Customer")
    rec = find_or_404(STORE.letters, lid, ERR_LETTER_NOT_FOUND, "letter")
    f = STORE.formulas.get(rec["formula_id"])
    if f is not None:
        check_customer_scope(f["customer_id"])
    return success(serialize(rec))


@bp.post("/copack/process-authority-letters/<lid>/activate")
def activate_letter(lid):
    require_roles("ProcessAuthority")
    rec = find_or_404(STORE.letters, lid, ERR_LETTER_NOT_FOUND, "letter")
    if rec["status"] != "SUBMITTED":
        raise err(ERR_LETTER_NOT_SUBMITTED, 409, "letter is not SUBMITTED")
    formula = STORE.formulas.get(rec["formula_id"])
    if formula is None or formula["status"] not in ("TRIAL_PASSED", "APPROVED"):
        raise err(ERR_FORMULA_NOT_TRIAL_PASSED, 409, "formula must be TRIAL_PASSED or APPROVED to activate a letter")
    # Stage 9: the pinned revision must still match the formula's revision.
    if rec["formula_revision"] != formula["revision"]:
        raise err(ERR_LETTER_REVISION_STALE, 409, "letter was drafted against an older formula revision")
    # Side effects: every other ACTIVE letter for this formula is superseded.
    for other in STORE.letters.values():
        if other["formula_id"] == rec["formula_id"] and other["id"] != rec["id"] and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            touch(other)
    rec["status"] = "ACTIVE"
    touch(rec)
    # A TRIAL_PASSED formula advances to APPROVED; an APPROVED one stays put.
    if formula["status"] == "TRIAL_PASSED":
        formula["status"] = "APPROVED"
        touch(formula)
    return success(serialize(rec))
