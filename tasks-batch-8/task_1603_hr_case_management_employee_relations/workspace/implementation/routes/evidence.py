"""Evidence item logging, review, admission, exclusion, archival (PRD §3.3)."""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request

from db import db, custody_seq
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_UNAUTHORIZED, ERR_SEGREGATION_OF_DUTIES,
    ERR_DOCUMENTATION_STANDARD, ERR_INVALID_REQUEST,
)
from middleware import authorize, require_investigator
from response import success_object
from services.core import (
    new_record, touch, require_path, require_ref, list_response,
    serialize_evidence, check_case_not_held, touch_case_manifest,
)
from validate import Payload

bp = Blueprint("evidence", __name__)

READ_ROLES = {"ERManager", "Investigator", "LegalCounsel"}
EVIDENCE_TYPES = {"DOCUMENT", "EMAIL", "CHAT_LOG", "PHOTO", "AUDIO", "VIDEO",
                  "PHYSICAL", "TESTIMONY"}
REVIEWABLE_CASE_STATES = {"INVESTIGATING", "FINDINGS_DRAFT"}


@bp.post("/er/cases/<cid>/evidence-items")
def log_evidence(cid):
    caller = authorize({"Investigator"})
    case = require_path("cases", cid)
    p = Payload(request.get_json(silent=True))
    submitted_by = p.get_str("submitted_by_employee_id", required=True)
    evidence_type = p.get_enum("evidence_type", EVIDENCE_TYPES, required=True)
    description = p.get_str("description", required=True)

    # priority 5
    if submitted_by is not None:
        require_ref("employees", submitted_by, "submitted_by_employee_id")

    # priority 6
    if case["status"] not in REVIEWABLE_CASE_STATES:
        raise_error(ERR_INVALID_STATE,
                    f"cannot log evidence under a case in status "
                    f"{case['status']}")
    # priority 7
    check_case_not_held(case)
    # ownership — evidence enters the file through the assigned investigator
    inv = require_investigator(caller)
    if inv["id"] != case["assigned_investigator_id"]:
        raise_error(ERR_UNAUTHORIZED,
                    "only the case's assigned investigator may log evidence")

    # priority 24
    p.raise_if_errors()

    # chain-of-custody ordinal: starts at 1, never reused or compacted
    seq = custody_seq.get(cid, 0) + 1
    custody_seq[cid] = seq

    rec = new_record()
    rec.update({
        "case_id": cid,
        "submitted_by_employee_id": submitted_by,
        "evidence_type": evidence_type,
        "description": description,
        "custody_sequence": seq,
        "status": "LOGGED",
        "weight": None,
        "reviewed_by_investigator_id": None,
    })
    db["evidence_items"][rec["id"]] = rec
    touch_case_manifest(cid)
    return success_object(serialize_evidence(rec), status=201)


@bp.get("/er/cases/<cid>/evidence-items")
def list_case_evidence(cid):
    authorize(READ_ROLES)
    require_path("cases", cid)
    items = [ev for ev in db["evidence_items"].values() if ev["case_id"] == cid]
    for field in ("status", "evidence_type"):
        v = request.args.get(field)
        if v is not None:
            items = [ev for ev in items if ev.get(field) == v]
    return list_response(items, serialize_evidence)


@bp.get("/er/evidence-items/<eid>")
def get_evidence(eid):
    authorize(READ_ROLES)
    rec = require_path("evidence_items", eid)
    return success_object(serialize_evidence(rec))


@bp.get("/er/evidence-items")
def list_evidence():
    authorize(READ_ROLES)
    items = list(db["evidence_items"].values())
    for field in ("submitted_by_employee_id", "reviewed_by_investigator_id",
                  "status", "evidence_type"):
        v = request.args.get(field)
        if v is not None:
            items = [ev for ev in items if ev.get(field) == v]
    return list_response(items, serialize_evidence)


@bp.post("/er/evidence-items/<eid>/begin-review")
def begin_review(eid):
    caller = authorize({"Investigator"})
    ev = require_path("evidence_items", eid)
    case = db["cases"][ev["case_id"]]

    # priority 6 — item LOGGED; parent case INVESTIGATING or FINDINGS_DRAFT
    if ev["status"] != "LOGGED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot begin review on an item in status {ev['status']}")
    if case["status"] not in REVIEWABLE_CASE_STATES:
        raise_error(ERR_INVALID_STATE,
                    f"cannot review evidence while the case is "
                    f"{case['status']}")
    # priority 7
    check_case_not_held(case)
    # ownership — the case's assigned investigator
    inv = require_investigator(caller)
    if inv["id"] != case["assigned_investigator_id"]:
        raise_error(ERR_UNAUTHORIZED,
                    "only the case's assigned investigator may begin review")

    ev["status"] = "UNDER_REVIEW"
    ev["reviewed_by_investigator_id"] = inv["id"]
    touch(ev)
    return success_object(serialize_evidence(ev))


@bp.post("/er/evidence-items/<eid>/admit")
def admit_evidence(eid):
    caller = authorize({"Investigator"})
    ev = require_path("evidence_items", eid)
    p = Payload(request.get_json(silent=True))
    weight = p.get_num("weight", required=True)

    case = db["cases"][ev["case_id"]]
    # priority 6 — item UNDER_REVIEW; parent case INVESTIGATING or FINDINGS_DRAFT
    if ev["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"cannot admit an item in status {ev['status']}")
    if case["status"] not in REVIEWABLE_CASE_STATES:
        raise_error(ERR_INVALID_STATE,
                    f"cannot admit evidence while the case is {case['status']}")
    # priority 7
    check_case_not_held(case)
    # priority 8 — segregation of duties: only the bound reviewer may admit
    require_investigator(caller)
    if caller.user_id != ev["reviewed_by_investigator_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "only the investigator who began the review may admit the "
                    "item")

    # priority 24 — weight present, 0.0 <= w <= 1.0, at most 2 decimal places
    if weight is not None:
        try:
            dec = Decimal(str(weight))
        except InvalidOperation:
            dec = None
        if dec is None or not (Decimal("0") <= dec <= Decimal("1")):
            p.errors.append("weight must be between 0.0 and 1.0")
        elif dec.as_tuple().exponent < -2:
            p.errors.append("weight must have at most 2 decimal places")
    p.raise_if_errors()

    ev["status"] = "ADMITTED"
    ev["weight"] = weight
    touch(ev)
    return success_object(serialize_evidence(ev))


@bp.post("/er/evidence-items/<eid>/exclude")
def exclude_evidence(eid):
    caller = authorize({"Investigator"})
    ev = require_path("evidence_items", eid)
    p = Payload(request.get_json(silent=True))
    exclusion_reason = p.get_str("exclusion_reason", required=True)

    # priority 6 — item UNDER_REVIEW
    if ev["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"cannot exclude an item in status {ev['status']}")
    # priority 7
    case = db["cases"][ev["case_id"]]
    check_case_not_held(case)
    # priority 8 — only the bound reviewer
    require_investigator(caller)
    if caller.user_id != ev["reviewed_by_investigator_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "only the investigator who began the review may exclude "
                    "the item")
    # priority 16 — documentation standard
    if exclusion_reason is not None and len(exclusion_reason) < 20:
        raise_error(ERR_DOCUMENTATION_STANDARD,
                    "exclusion_reason must be at least 20 characters")
    # priority 24
    p.raise_if_errors()

    ev["status"] = "EXCLUDED"
    touch(ev)
    return success_object(serialize_evidence(ev))


@bp.post("/er/evidence-items/<eid>/archive")
def archive_evidence(eid):
    authorize({"ERManager"})
    ev = require_path("evidence_items", eid)
    case = db["cases"][ev["case_id"]]

    # priority 6 — item EXCLUDED; parent case CLOSED
    if ev["status"] != "EXCLUDED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot archive an item in status {ev['status']}")
    if case["status"] != "CLOSED":
        raise_error(ERR_INVALID_STATE,
                    "evidence may be archived only once the case is CLOSED")
    # priority 7
    check_case_not_held(case)

    ev["status"] = "ARCHIVED"
    touch(ev)
    # custody_sequence of remaining items is unchanged — never reused/compacted
    touch_case_manifest(ev["case_id"])
    return success_object(serialize_evidence(ev))
