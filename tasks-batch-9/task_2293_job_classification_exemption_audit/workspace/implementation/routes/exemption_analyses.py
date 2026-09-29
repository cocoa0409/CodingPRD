"""Exemption analysis, independent review, determination and rescission
(PRD 3.4, 3.5)."""
from flask import Blueprint, g

import db
from constants import ALL_ROLES, APPLIED_TESTS
from errors import fail
from middleware import body, endpoint
from response import success
from services import derive, exemption, lookup, serialize
from validation import req_enum, req_int, req_str

bp = Blueprint("exemption_analyses", __name__)

DETERMINED_STATES = ("EXEMPT_CONFIRMED", "NONEXEMPT_DETERMINED")


def _cases_of_position(position_id):
    return [
        c for c in db.reclassification_cases.values() if c["position_id"] == position_id
    ]


@bp.post("/exemption-analyses")
@endpoint(["ComplianceAnalyst"])
def create_analysis():
    payload = body()
    position_id = req_str(payload, "position_id")
    applied_test = req_enum(payload, "applied_test", APPLIED_TESTS)
    expected_version = req_int(payload, "expected_position_version")

    # rank 5: foreign key
    position = lookup.position(position_id)

    # rank 9: stale-read protection (PRD 2.9)
    if expected_version != position["version"]:
        fail("ERR_STALE_POSITION_VERSION")

    row = db.make_row(
        position_id=position["id"],
        applied_test=applied_test,
        analyst_user_id=g.user_id,
        reviewer_user_id=None,
        revision_round=0,
        weekly_salary_cents_snapshot=None,
        primary_duty_pct_snapshot=None,
        applicable_salary_floor_cents=None,
        applicable_duty_floor_pct=None,
        salary_threshold_source=None,
        federal_pass=None,
        state_pass=None,
        hce_shortcut_applied=None,
        outcome=None,
        return_reason=None,
        status="DRAFT",
    )
    db.exemption_analyses[row["id"]] = row

    # opening an analysis advances the position's version (PRD 3.4)
    db.touch(position)
    return success(serialize.exemption_analysis(row), 201)


@bp.get("/exemption-analyses/<analysis_id>")
@endpoint(ALL_ROLES)
def get_analysis(analysis_id):
    analysis = lookup.analysis(analysis_id)
    return success(serialize.exemption_analysis(analysis), 200)


@bp.post("/exemption-analyses/<analysis_id>/submit")
@endpoint(["ComplianceAnalyst"])
def submit_analysis(analysis_id):
    analysis = lookup.analysis(analysis_id)
    position = lookup.position(analysis["position_id"])

    # rank 8: declared transitions DRAFT -> SUBMITTED and RETURNED -> SUBMITTED
    previous = analysis["status"]
    if previous not in ("DRAFT", "RETURNED"):
        fail("ERR_INVALID_STATE_TRANSITION")

    # rank 11: the audit will not stake a determination on an uncorroborated
    # duty picture
    if derive.duty_view(position)["duties_validation_status"] == "PENDING":
        fail("ERR_DUTIES_NOT_CORROBORATED")

    if previous == "RETURNED":
        analysis["revision_round"] = analysis["revision_round"] + 1

    analysis.update(exemption.evaluate(position, analysis["applied_test"]))
    analysis["status"] = "SUBMITTED"
    db.touch(analysis)
    return success(serialize.exemption_analysis(analysis), 200)


@bp.post("/exemption-analyses/<analysis_id>/return")
@endpoint(["ClassificationReviewer"])
def return_analysis(analysis_id):
    analysis = lookup.analysis(analysis_id)
    payload = body()
    return_reason = req_str(payload, "return_reason")
    position = lookup.position(analysis["position_id"])

    # rank 8: declared transitions out of SUBMITTED and the two determined states
    previous = analysis["status"]
    if previous not in ("SUBMITTED",) + DETERMINED_STATES:
        fail("ERR_INVALID_STATE_TRANSITION")
    if previous in DETERMINED_STATES:
        # rescission is blocked once payroll has moved
        for case in _cases_of_position(position["id"]):
            if case["pay_conversion_status"] == "CONVERTED":
                fail("ERR_RECLASS_ALREADY_CONVERTED")

    # rank 10: four eyes
    if g.user_id == analysis["analyst_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    analysis["reviewer_user_id"] = g.user_id
    analysis["return_reason"] = return_reason
    analysis["status"] = "RETURNED"
    db.touch(analysis)

    if previous in DETERMINED_STATES:
        position["classification_status"] = "UNREVIEWED"
        lookup.touch_position_chain(position)
    return success(serialize.exemption_analysis(analysis), 200)


@bp.post("/exemption-analyses/<analysis_id>/determine")
@endpoint(["ClassificationReviewer"])
def determine_analysis(analysis_id):
    analysis = lookup.analysis(analysis_id)
    position = lookup.position(analysis["position_id"])

    # rank 8: only a SUBMITTED analysis with a decisive outcome is determinable
    if analysis["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    outcome = analysis["outcome"]
    if outcome not in ("EXEMPT", "NONEXEMPT"):
        fail("ERR_INVALID_STATE_TRANSITION")

    # rank 10: four eyes
    if g.user_id == analysis["analyst_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    analysis["reviewer_user_id"] = g.user_id
    if outcome == "EXEMPT":
        analysis["status"] = "EXEMPT_CONFIRMED"
        position["classification_status"] = "VALIDATED_EXEMPT"
    else:
        analysis["status"] = "NONEXEMPT_DETERMINED"
        position["classification_status"] = (
            "MISCLASSIFIED"
            if position["current_fls_status"] == "EXEMPT"
            else "CONFIRMED_NONEXEMPT"
        )
    db.touch(analysis)
    lookup.touch_position_chain(position)
    return success(serialize.exemption_analysis(analysis), 200)
