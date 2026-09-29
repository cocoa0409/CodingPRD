"""Acceptance tests, pay factors and the remediation cascade (PRD 3.8)."""
from flask import Blueprint, g

import calc
import db
import response
import validators as v
from errors import ApiError
from middleware import endpoint
from services import cascades, derive

bp = Blueprint("acceptance_tests", __name__)

DECISIONS = ("PASS", "FAIL", "RETEST")
READ_ROLES = ("PavementEngineer", "Inspector", "BudgetOfficer", "Contractor")


def _find_test(test_id):
    test = db.acceptance_tests.get(test_id)
    if test is None:
        raise ApiError("ERR_ACCEPTANCE_TEST_NOT_FOUND")
    return test


@bp.post("/acceptance-tests")
@endpoint("Inspector")
def create_test():
    data = v.body()
    line_id = v.field_id(data, "project_segment_id")
    core_density = v.field_number(data, "core_density_pct", minimum=70,
                                 maximum=105)
    iri = v.field_number(data, "iri_in_per_mi", minimum=0, maximum=400)
    thickness = v.field_number(data, "thickness_in", minimum=0,
                              exclusive_minimum=True)
    witness = v.field_id(data, "witness_inspector_user_id")

    line = db.project_segments.get(line_id)
    if line is None:
        raise ApiError("ERR_PROJECT_SEGMENT_NOT_FOUND")

    if line["work_state"] not in ("IN_PROGRESS", "REMEDIATION_REQUIRED"):
        raise ApiError("ERR_LINE_NOT_TESTABLE")
    existing = derive.tests_of_line(line["id"])
    if any(t["test_status"] == "SUBMITTED" for t in existing):
        raise ApiError("ERR_TEST_ALREADY_PENDING")

    project = db.projects.get(line["project_id"])
    test_round = (max(t["test_round"] for t in existing) + 1) if existing else 1

    # A higher round supersedes the prior decided round.
    recovered = False
    for prior in existing:
        if prior["test_status"] in ("FAILED", "RETEST_ORDERED"):
            was_failed = prior["test_status"] == "FAILED"
            derive.apply_updates(prior, {"test_status": "SUPERSEDED"})
            if was_failed and line["work_state"] == "REMEDIATION_REQUIRED":
                derive.apply_updates(line, {"work_state": "IN_PROGRESS"})
                recovered = True

    factor, outcome = calc.acceptance_pay_factor(
        core_density, iri, thickness, line["design_thickness_in"]
    )
    test = {
        "id": db.new_id(),
        "project_segment_id": line["id"],
        "core_density_pct": calc.num(core_density, 1),
        "iri_in_per_mi": iri,
        "thickness_in": calc.num(thickness, 2),
        "witness_inspector_user_id": witness,
        "test_round": test_round,
        "computed_pay_factor": factor,
        "computed_outcome": outcome,
        "test_status": "SUBMITTED",
        "decided_by_user_id": None,
        "decision_note": None,
        "_decision": None,
    }
    test.update(db.audit())
    db.acceptance_tests[test["id"]] = test
    derive.recompute_line_test_count(line)

    if project is not None:
        derive.recompute_project_counters(project)
        if project["quality_status"] == "NOT_STARTED":
            derive.apply_updates(project, {"quality_status": "TESTING"})
        elif project["quality_status"] == "REMEDIATION_REQUIRED" \
                and project["open_remediation_count"] == 0 and recovered:
            derive.apply_updates(project, {"quality_status": "TESTING"})
    return response.object_response(test, 201)


@bp.get("/acceptance-tests/<test_id>")
@endpoint(*READ_ROLES)
def read_test(test_id):
    return response.object_response(_find_test(test_id))


@bp.get("/acceptance-tests")
@endpoint(*READ_ROLES)
def list_tests():
    rows = v.filter_rows(db.ordered(db.acceptance_tests.values()), {
        "project_segment_id": "project_segment_id",
        "test_status": "test_status",
    })
    page, meta = v.paginate(rows)
    return response.array_response(page, pagination=meta)


@bp.post("/acceptance-tests/<test_id>/decide")
@endpoint("Inspector")
def decide_test(test_id):
    # Step 5 — segregation of duties, ahead of request shape (PRD 2.10).
    pending = db.acceptance_tests.get(test_id)
    if pending is not None \
            and pending["witness_inspector_user_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    data = v.body()
    decision = v.field_enum(data, "decision", DECISIONS)
    note = v.field_string(data, "decision_note", 1, 500, required=False)

    test = _find_test(test_id)
    if test["test_status"] != "SUBMITTED":
        raise ApiError("ERR_TEST_ALREADY_DECIDED")
    if decision == "PASS" and test["computed_outcome"] == "FAIL":
        raise ApiError("ERR_TEST_DECISION_CONFLICTS_COMPUTED")

    line = db.project_segments.get(test["project_segment_id"])
    project = db.projects.get(line["project_id"]) if line else None
    contractor = db.contractors.get(project["contractor_id"]) if project else None
    highest_round = line is not None and test["test_round"] == max(
        t["test_round"] for t in derive.tests_of_line(line["id"])
    )

    updates = {
        "test_status": {"PASS": "PASSED", "FAIL": "FAILED",
                        "RETEST": "RETEST_ORDERED"}[decision],
        "decided_by_user_id": g.user_id,
        "_decision": decision,
    }
    if note is not None:
        updates["decision_note"] = note
    derive.apply_updates(test, updates)

    if decision == "PASS":
        if line is not None and highest_round:
            line_updates = {"pay_factor": test["computed_pay_factor"]}
            if line["work_state"] == "IN_PROGRESS":
                line_updates["work_state"] = "WORK_COMPLETE"
            derive.apply_updates(line, line_updates)
        if contractor is not None:
            derive.apply_updates(contractor, {
                "passed_test_count": contractor["passed_test_count"] + 1,
            })
            derive.recompute_contractor_scores(contractor)
        if project is not None:
            derive.recompute_project_counters(project)
            cascades.bubble_quality_status(project)

    elif decision == "FAIL":
        # Level 1 — the line drops into remediation.
        if line is not None and highest_round:
            line_updates = {"pay_factor": test["computed_pay_factor"]}
            if line["work_state"] == "IN_PROGRESS":
                line_updates["work_state"] = "REMEDIATION_REQUIRED"
            derive.apply_updates(line, line_updates)
        # Level 2 — the project's quality dimension follows.
        if project is not None:
            derive.recompute_project_counters(project)
            if project["quality_status"] == "TESTING" \
                    and project["open_remediation_count"] > 0:
                derive.apply_updates(project,
                                     {"quality_status": "REMEDIATION_REQUIRED"})
        # Levels 3 and 4 — contractor counters, score and standing.
        if contractor is not None:
            derive.apply_updates(contractor, {
                "failed_test_count": contractor["failed_test_count"] + 1,
                "remediation_event_count":
                    contractor["remediation_event_count"] + 1,
            })
            derive.recompute_contractor_scores(contractor)

    return response.object_response(test)
