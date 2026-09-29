"""Compliance-case endpoints and the four-hop disqualification cascade (PRD 3.5)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import cascades
import constants
import db
import errors
import listing
import lookup
import response
import serialize
import validation

bp = Blueprint("compliance_cases", __name__)


@bp.post("/compliance-cases")
def create_case():
    user_id, _role = auth.require(constants.ELECTION_COMMISSIONER)
    body = validation.get_body()

    # rule 4 — body foreign keys, in input-list order
    election = lookup.fk_election(body)
    candidacy = lookup.fk_candidacy(body)

    # rule 5 — schema
    validation.req_str(body, "election_id")
    validation.req_str(body, "candidacy_id")
    rule_code = validation.req_str(body, "rule_code")
    severity = validation.req_enum(body, "severity", constants.CASE_SEVERITIES)
    description = validation.req_text(body, "description")

    row = db.new_row(db.store.compliance_cases, {
        "election_id": election["id"],
        "candidacy_id": candidacy["id"],
        "rule_code": rule_code,
        "severity": severity,
        "description": description,
        "status": "FILED",
        "penalty_points": 0,
        "prior_upheld_count": 0,
        "timing_factor_applied": Decimal("1.0"),
        "overspend_points_applied": 0,
        "filed_by_user_id": user_id,
        "adjudicated_by_user_id": None,
        "upheld_at": None,
    })
    return response.object_response(serialize.case(row), 201)


@bp.get("/compliance-cases")
def list_cases():
    auth.require_any()
    rows = listing.filtered(db.store.compliance_cases, {
        "election_id": ("election_id", None),
        "candidacy_id": ("candidacy_id", None),
        "status": ("status", None),
    })
    return listing.list_response(rows, serialize.case)


@bp.get("/compliance-cases/<compliance_case_id>")
def read_case(compliance_case_id):
    auth.require_any()
    row = lookup.case(compliance_case_id)
    return response.object_response(serialize.case(row))


@bp.post("/compliance-cases/<compliance_case_id>/uphold")
def uphold_case(compliance_case_id):
    user_id, _role = auth.require(constants.FACULTY_ADVISOR)
    case = lookup.case(compliance_case_id)
    candidacy = db.store.candidacies.get(case["candidacy_id"])

    if case["status"] != "FILED":
        errors.fail(errors.ERR_INVALID_STATE, "Only a FILED case may be upheld.")
    if candidacy is not None and candidacy["status"] in constants.CANDIDACY_CLOSED_FOR_COMPLIANCE:
        errors.fail(errors.ERR_INVALID_STATE,
                    "The respondent candidacy is no longer subject to enforcement.")

    # hop 1 — score the case at the AT_ADJUDICATION spend basis
    db.set_fields(case, status="UPHELD", adjudicated_by_user_id=user_id,
                  upheld_at=db.now())
    calc.score_case(case, at_certification=False)
    db.touch(case)

    # hops 2, 3 and 4
    cascades.compliance_cascade(case)
    return response.object_response(serialize.case(case))


@bp.post("/compliance-cases/<compliance_case_id>/dismiss")
def dismiss_case(compliance_case_id):
    user_id, _role = auth.require(constants.FACULTY_ADVISOR)
    case = lookup.case(compliance_case_id)

    body = validation.get_body()
    validation.opt_text(body, "reason")

    if case["status"] != "FILED":
        errors.fail(errors.ERR_INVALID_STATE, "Only a FILED case may be dismissed.")

    db.set_fields(case, status="DISMISSED", adjudicated_by_user_id=user_id)
    db.touch(case)
    return response.object_response(serialize.case(case))
