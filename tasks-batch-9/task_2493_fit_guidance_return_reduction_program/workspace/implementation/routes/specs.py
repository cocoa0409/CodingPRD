"""Measurement specifications: the cyclic verification machine (PRD 3.2)."""

from flask import Blueprint

import clock
import constants as C
import validate as V
from db import db, new_row, touch
from errors import ApiError
from lookup import ensure_not_delisted, filtered, get_item, get_spec
from middleware import authenticate, require_owner
from response import array_response, object_response
from services.derive import (debit_vendor_correction_round,
                             readiness_fall_to_unverified, specs_of_item)
from services.spec_verify import run_verification

bp = Blueprint("measurement_specs", __name__)

IN_FLIGHT_STATUSES = ("DRAFT", "SUBMITTED", "CORRECTION_REQUESTED")


def _vendor_of_item(item):
    return db.vendors.get(item["vendor_id"])


def _ensure_vendor_not_suspended(item):
    """Rank 17: a suspended brand cannot author, submit or resubmit."""
    vendor = _vendor_of_item(item)
    if vendor is not None and vendor["status"] == "SUSPENDED":
        raise ApiError("ERR_VENDOR_SUSPENDED",
                       "Vendor '%s' is SUSPENDED." % vendor["id"])
    return vendor


def _require_base_size_label(base_size_label, size_points):
    if not any(point["size_label"] == base_size_label for point in size_points):
        raise V.invalid("'base_size_label' must appear among the size_points.")


@bp.post("/fit-program/measurement-specs")
def create_spec():
    actor = authenticate(C.ROLE_VENDOR_USER)

    # rank 4 precedes rank 5: peek at the body's item_id for the ownership test
    peeked = V.peek_str(V.raw_body(), "item_id")
    if peeked is not None and peeked in db.items:
        require_owner(db.items[peeked]["vendor_id"] == actor.user_id,
                      "A VendorUser may only author specifications for its own items.")

    body = V.get_body()
    item_id = V.req_str(body, "item_id", min_len=1)
    size_system = V.req_enum(body, "size_system", C.SIZE_SYSTEMS)
    base_size_label = V.req_str(body, "base_size_label", min_len=1)
    fabric_stretch_class = V.req_enum(body, "fabric_stretch_class",
                                      C.FABRIC_STRETCH_CLASSES)
    size_points = V.validate_size_points(body)
    grade_rules = V.validate_grade_rules(body)
    _require_base_size_label(base_size_label, size_points)

    item = get_item(item_id)
    require_owner(item["vendor_id"] == actor.user_id,
                  "A VendorUser may only author specifications for its own items.")
    ensure_not_delisted(item)
    _ensure_vendor_not_suspended(item)

    for sibling in specs_of_item(item["id"]):
        if sibling["status"] in IN_FLIGHT_STATUSES:
            raise ApiError("ERR_SPEC_REVISION_IN_FLIGHT",
                           "The item already has a specification in %s."
                           % sibling["status"])

    spec = new_row({
        "item_id": item["id"],
        "revision_round": 0,
        "status": "DRAFT",
        "size_system": size_system,
        "base_size_label": base_size_label,
        "fabric_stretch_class": fabric_stretch_class,
        "size_points": size_points,
        "grade_rules": grade_rules,
        "violation_count": 0,
        "first_violation_point": None,
        "first_violation_from_size_label": None,
        "tolerance_applied_mm": [],
        "correction_reason": None,
        "verified_by_user_id": None,
        "verified_at": None,
    })
    db.specs[spec["id"]] = spec
    return object_response(spec, 201)


@bp.get("/fit-program/measurement-specs/<spec_id>")
def read_spec(spec_id):
    authenticate(C.ROLE_VENDOR_USER, C.ROLE_FIT_ANALYST, C.ROLE_MERCH_OPS_ADMIN)
    return object_response(get_spec(spec_id))


@bp.get("/fit-program/measurement-specs")
def list_specs():
    authenticate(C.ROLE_VENDOR_USER, C.ROLE_FIT_ANALYST, C.ROLE_MERCH_OPS_ADMIN)
    limit, offset = V.pagination_params()
    rows = filtered(db.specs.values(), {"item_id": "item_id", "status": "status"})
    page, meta = V.paginate(rows, limit, offset)
    return array_response(page, meta)


@bp.post("/fit-program/measurement-specs/<spec_id>/submit")
def submit_spec(spec_id):
    actor = authenticate(C.ROLE_VENDOR_USER)
    spec = get_spec(spec_id)
    item = get_item(spec["item_id"])
    require_owner(item["vendor_id"] == actor.user_id,
                  "A VendorUser may only submit specifications for its own items.")

    if len(spec["size_points"]) < 2:
        raise V.invalid("The stored size_points must still contain at least 2 entries.")
    _require_base_size_label(spec["base_size_label"], spec["size_points"])

    ensure_not_delisted(item)
    if spec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SPEC_STATE",
                       "Only a DRAFT specification can be submitted; this one is %s."
                       % spec["status"])
    _ensure_vendor_not_suspended(item)

    spec["status"] = "SUBMITTED"
    touch(spec)
    return object_response(spec)


@bp.post("/fit-program/measurement-specs/<spec_id>/verify")
def verify_spec(spec_id):
    actor = authenticate(C.ROLE_FIT_ANALYST)
    spec = get_spec(spec_id)
    item = get_item(spec["item_id"])
    ensure_not_delisted(item)
    if spec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_SPEC_STATE",
                       "Only a SUBMITTED specification can be verified; this one "
                       "is %s." % spec["status"])

    tolerance_applied, violations = run_verification(spec)

    spec["tolerance_applied_mm"] = tolerance_applied
    spec["violation_count"] = len(violations)

    if not violations:
        spec["first_violation_point"] = None
        spec["first_violation_from_size_label"] = None
        spec["status"] = "VERIFIED"
        spec["correction_reason"] = None
        spec["verified_by_user_id"] = actor.user_id
        spec["verified_at"] = clock.now()
        touch(spec)
        # an item never holds two verified specifications at once
        for sibling in specs_of_item(item["id"]):
            if sibling["id"] != spec["id"] and sibling["status"] == "VERIFIED":
                sibling["status"] = "SUPERSEDED"
                touch(sibling)
        return object_response(spec)

    first = violations[0]
    spec["first_violation_point"] = first["measurement_point"]
    spec["first_violation_from_size_label"] = first["from_size_label"]

    if spec["revision_round"] < C.MAX_CORRECTION_ROUNDS:
        spec["status"] = "CORRECTION_REQUESTED"
        spec["correction_reason"] = "GRADE_TOLERANCE_VIOLATION"
        touch(spec)
        debit_vendor_correction_round(item["vendor_id"])
        return object_response(spec)

    # the allowance for this specification is exhausted, not overdrawn further
    spec["status"] = "REJECTED"
    touch(spec)
    readiness_fall_to_unverified(item)
    return object_response(spec)


@bp.post("/fit-program/measurement-specs/<spec_id>/resubmit")
def resubmit_spec(spec_id):
    actor = authenticate(C.ROLE_VENDOR_USER)
    spec = get_spec(spec_id)
    item = get_item(spec["item_id"])
    require_owner(item["vendor_id"] == actor.user_id,
                  "A VendorUser may only resubmit specifications for its own items.")

    body = V.get_body()
    size_points = V.validate_size_points(body)
    grade_rules = None
    if "grade_rules" in body and body["grade_rules"] is not None:
        grade_rules = V.validate_grade_rules(body)
    _require_base_size_label(spec["base_size_label"], size_points)

    ensure_not_delisted(item)
    if spec["status"] != "CORRECTION_REQUESTED":
        raise ApiError("ERR_INVALID_SPEC_STATE",
                       "Only a CORRECTION_REQUESTED specification can be "
                       "resubmitted; this one is %s." % spec["status"])
    vendor = _ensure_vendor_not_suspended(item)

    if vendor is not None and (vendor["correction_spend_cents"]
                               > vendor["correction_budget_cents"]):
        raise ApiError("ERR_VENDOR_CORRECTION_BUDGET_EXHAUSTED",
                       "The vendor's correction allowance is overdrawn.")

    spec["size_points"] = size_points
    if grade_rules is not None:
        spec["grade_rules"] = grade_rules
    spec["revision_round"] = spec["revision_round"] + 1
    spec["correction_reason"] = None
    spec["status"] = "SUBMITTED"
    touch(spec)
    return object_response(spec)
