"""Test plans and the feature-set closure (PRD 3.5)."""

from flask import Blueprint

import calc
import cascade
import common as C
import middleware as M
import queries as Q
import shape as S
from db import new_row, ordered, set_fields, store, touch
from errors import ApiError
from response import list_response, object_response
from serial import public, public_list

bp = Blueprint("test_plans", __name__)

PLAN_READ_ROLES = [M.PROGRAM_ADMIN, M.MEMBER, M.TEST_LABORATORY,
                   M.CONFORMANCE_REVIEWER, M.SECURITY_REVIEWER]


@bp.post("/test-plans")
def create_test_plan():
    M.auth([M.PROGRAM_ADMIN])
    body = S.body_obj()
    # rung 5
    submission = C.body_fk("submission", body, "submission_id")
    # rung 6
    S.req_str(body, "submission_id")
    expected_version = S.req_int(body, "expected_submission_version")
    # rung 11 -- optimistic concurrency on the parent submission
    if expected_version != submission["version"]:
        raise ApiError("ERR_STALE_SUBMISSION_VERSION",
                       "expected_submission_version does not match the stored version")
    # rung 16
    if submission["state"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_SUBMISSION_STATE", "a test plan requires an IN_REVIEW submission")

    prior = Q.live_plan(submission["id"])
    if prior is not None:
        cascade.void_plan(prior, "SUPERSEDED_BY_NEW_PLAN")

    included, required, mandatory, optional = calc.plan_closure(
        submission["specification_id"], submission["device_type"],
        submission["declared_feature_codes"],
    )
    plan = new_row(
        submission_id=submission["id"],
        specification_id=submission["specification_id"],
        device_type=submission["device_type"],
        state="DRAFT",
        included_feature_set_ids=included,
        required_case_count=required,
        mandatory_case_count=mandatory,
        optional_case_count=optional,
        voided_reason=None,
    )
    store.test_plans[plan["id"]] = plan
    # PRD 3.5: the create bumps the parent submission's version.
    touch(submission)
    return object_response(public(plan), 201)


@bp.get("/test-plans/<test_plan_id>")
def get_test_plan(test_plan_id):
    M.auth(PLAN_READ_ROLES)
    return object_response(public(C.must("test_plan", test_plan_id)), 200)


@bp.get("/test-plans")
def list_test_plans():
    M.auth(PLAN_READ_ROLES)
    limit, offset = S.paging()
    submission_id = S.q_str("submission_id")
    specification_id = S.q_str("specification_id")
    state = S.q_str("state")
    rows = ordered(store.test_plans.values())
    if submission_id is not None:
        rows = [r for r in rows if r["submission_id"] == submission_id]
    if specification_id is not None:
        rows = [r for r in rows if r["specification_id"] == specification_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    page, total = C.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.post("/test-plans/<test_plan_id>/issue")
def issue_test_plan(test_plan_id):
    M.auth([M.PROGRAM_ADMIN])
    plan = C.must("test_plan", test_plan_id)
    submission = store.submissions[plan["submission_id"]]
    # rung 16
    if submission["state"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_SUBMISSION_STATE",
                       "issuing a plan requires an IN_REVIEW submission")
    # rung 18
    if plan["state"] != "DRAFT":
        raise ApiError("ERR_INVALID_TEST_PLAN_STATE", "only a DRAFT plan can be issued")
    # rung 43
    if plan["required_case_count"] < 1:
        raise ApiError("ERR_MANDATORY_COVERAGE_INCOMPLETE", "the closure is empty")
    set_fields(plan, state="ISSUED")
    return object_response(public(plan), 200)
