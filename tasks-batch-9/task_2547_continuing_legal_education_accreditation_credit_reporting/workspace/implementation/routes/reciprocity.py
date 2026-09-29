"""Out-of-state instruction: reciprocity conversion and comity closure (PRD 3.7)."""
from decimal import Decimal, InvalidOperation

from flask import Blueprint

import calc
import constants as C
import db
import middleware
import response
import util
from errors import fail
from routes.attorneys import load_attorney
from services import cascades

bp = Blueprint("reciprocity", __name__)

BASES = ["RECIPROCITY", "COMITY"]
ORIGIN_CATEGORIES = ["GENERAL", "PROFESSIONALISM", "ETHICS", "TECHNOLOGY", "DIVERSITY_INCLUSION"]
DETERMINATION_ACTIONS = ["APPROVE", "DENY"]


def load_claim(claim_id):
    claim = db.get("reciprocity_claims", claim_id)
    if claim is None:
        fail("ERR_RECIPROCITY_CLAIM_NOT_FOUND", "No reciprocity claim matches that identifier.")
    return claim


def _origin_hours(body):
    value = middleware.req_number(body, "origin_credit_hours")
    if value <= 0:
        fail("ERR_INVALID_REQUEST", "origin_credit_hours must be greater than zero.")
    try:
        as_decimal = Decimal(str(value))
    except InvalidOperation:
        fail("ERR_INVALID_REQUEST", "origin_credit_hours must be a number.")
    if as_decimal.as_tuple().exponent < -1:
        fail("ERR_INVALID_REQUEST", "origin_credit_hours carries at most one decimal place.")
    return value


@bp.route("/cle/reciprocity-claims", methods=["POST"])
def file_claim():
    user_id, _role = middleware.require_roles([C.ROLE_ATTORNEY])
    body = middleware.body_json()

    # Step 4: body foreign-key existence.
    attorney = load_attorney(body.get("attorney_id")) if middleware.present(body, "attorney_id") else None

    # Step 5: ownership.
    if attorney is not None and attorney["id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "An attorney may only file its own out-of-state claims.")

    # Step 6: request shape.
    if attorney is None:
        fail("ERR_INVALID_REQUEST", "attorney_id is required.")
    basis = middleware.req_enum(body, "basis", BASES)
    origin_jurisdiction = middleware.req_jurisdiction(body, "origin_jurisdiction")
    origin_course_title = middleware.req_str(body, "origin_course_title", 1, 200)
    origin_credit_hours = _origin_hours(body)
    origin_category = middleware.req_enum(body, "origin_category", ORIGIN_CATEGORIES)
    completion_date = middleware.req_instant(body, "completion_date")
    expected = middleware.req_int(body, "expected_attorney_version")

    # Step 7: optimistic concurrency against the attorney row.
    if expected != attorney.get("version"):
        fail("ERR_STALE_VERSION", "expected_attorney_version does not match the attorney's version.")

    # Step 13: regulatory standing.
    if attorney.get("status") not in ("ACTIVE", "EXEMPT"):
        fail("ERR_ATTORNEY_NOT_IN_GOOD_STANDING", "The attorney is not in good standing.")

    claim = db.insert(
        "reciprocity_claims",
        {
            "attorney_id": attorney["id"],
            "basis": basis,
            "origin_jurisdiction": origin_jurisdiction,
            "origin_course_title": origin_course_title,
            "origin_credit_hours": origin_credit_hours,
            "origin_category": origin_category,
            "completion_date": util.iso(completion_date),
            "converted_minutes": 0,
            "converted_category": "GENERAL",
            "status": "SUBMITTED",
            "determination_reason": None,
        },
    )
    # Filing raises the attorney's own version by one.
    db.touch(attorney)
    return response.success(db.serialize(claim), 201)


@bp.route("/cle/reciprocity-claims/<claim_id>/determination", methods=["POST"])
def determine_claim(claim_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN])
    claim = load_claim(claim_id)
    body = middleware.body_json()
    action = middleware.req_enum(body, "action", DETERMINATION_ACTIONS)
    reason = middleware.opt_str(body, "determination_reason", 1, None, None)
    if action == "DENY" and reason is None:
        fail("ERR_INVALID_REQUEST", "determination_reason is required to deny a claim.")

    # Step 8: state preconditions.
    if claim.get("status") != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a SUBMITTED claim may be determined.")

    if action == "DENY":
        cascades.set_fields(claim, {"status": "DENIED", "determination_reason": reason})
        return response.success(db.serialize(claim), 200)

    attorney = db.get("attorneys", claim.get("attorney_id"))
    if attorney is None or attorney.get("status") not in ("ACTIVE", "EXEMPT"):
        fail("ERR_ATTORNEY_NOT_IN_GOOD_STANDING", "The attorney is not in good standing.")
    completion_date = util.parse_dt(claim.get("completion_date"))
    cycle = cascades.cycle_for_instant(attorney["id"], completion_date)
    if cycle is None or cycle.get("credit_status") != "OPEN":
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Approval requires an OPEN compliance period covering the completion date.",
        )

    # Step 14: referential coherence.
    if cycle.get("attorney_id") != claim.get("attorney_id"):
        fail("ERR_CYCLE_ATTORNEY_MISMATCH", "The resolved cycle belongs to another attorney.")

    if claim.get("basis") == "RECIPROCITY":
        _approve_reciprocity(claim, cycle, reason)
    else:
        _approve_comity(claim, cycle, attorney, reason)
    return response.success(db.serialize(claim), 200)


def _approve_reciprocity(claim, cycle, reason):
    # Step 16: the reciprocal-arrangement gate.
    if claim.get("origin_jurisdiction") not in C.RECIPROCITY_JURISDICTIONS:
        fail("ERR_JURISDICTION_NOT_RECIPROCAL", "The board has no reciprocal arrangement there.")
    converted, category = calc.convert_reciprocity(claim)
    cascades.set_fields(
        claim,
        {
            "status": "APPROVED",
            "converted_minutes": converted,
            "converted_category": category,
            "determination_reason": reason,
        },
    )
    fields = {
        "attorney_id": claim.get("attorney_id"),
        "cycle_id": cycle["id"],
        "course_id": None,
        "attendance_report_id": None,
        "reciprocity_claim_id": claim["id"],
        "affirmation_id": None,
        "source": "RECIPROCITY",
        "verification_method": "CERTIFICATE",
        "certificate_reference": None,
        "attended_minutes": converted,
        "completion_date": claim.get("completion_date"),
        "credited_ethics_minutes": 0,
        "credited_technology_minutes": 0,
        "credited_bias_minutes": 0,
        "credited_general_minutes": 0,
        "credited_minutes": converted,
        "countable_minutes": 0,
        "effective_format": "LIVE",
        "status": "VERIFIED",
        "void_reason": None,
    }
    fields[calc.CATEGORY_FIELD[category]] = converted
    db.insert("credit_records", fields)
    cascades.rerun_cycle(cycle)


def _approve_comity(claim, cycle, attorney, reason):
    # Step 16: the three-part comity gate.
    jurisdiction = claim.get("origin_jurisdiction")
    if jurisdiction not in C.COMITY_JURISDICTIONS:
        fail("ERR_COMITY_NOT_AVAILABLE", "%s is not a recognised comity jurisdiction." % jurisdiction)
    if attorney.get("principal_office_jurisdiction") != jurisdiction:
        fail(
            "ERR_COMITY_NOT_AVAILABLE",
            "The attorney's principal office is not in that jurisdiction.",
        )
    if jurisdiction == C.HOME_JURISDICTION:
        fail("ERR_COMITY_NOT_AVAILABLE", "Comity is never available in the home jurisdiction.")

    cascades.set_fields(claim, {"status": "APPROVED", "determination_reason": reason})

    res = cascades.persist_application(cycle, "FINAL")
    specialties_met = (
        res["earned_ethics_minutes"] >= int(cycle.get("required_ethics_minutes") or 0)
        and res["earned_technology_minutes"] >= int(cycle.get("required_technology_minutes") or 0)
        and res["earned_bias_minutes"] >= int(cycle.get("required_bias_minutes") or 0)
    )
    updates = {
        "comity_claim_id": claim["id"],
        "carryover_out_general_minutes": 0,
        "carryover_out_ethics_minutes": 0,
    }
    if specialties_met:
        updates["credit_status"] = "CLOSED_COMITY"
        updates["certified_at"] = util.now_iso()
        updates["earned_countable_minutes"] = int(cycle.get("required_total_minutes") or 0)
        cascades.set_fields(cycle, updates)
    else:
        updates["credit_status"] = "DEFICIENT"
        cascades.set_fields(cycle, updates)
        cascades.bump_deficiency_count(attorney, 1)
    cascades.write_carryover_out(cycle, 0, 0)
