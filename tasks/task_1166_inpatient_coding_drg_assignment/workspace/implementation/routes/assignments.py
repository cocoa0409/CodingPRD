"""CodingAssignment queue endpoints (PRD §3.2, §3.4, §3.5)."""
from flask import Blueprint, request

from db import now, sort_default, stamp_new, store, touch
from errors import (ERR_ASSIGNMENT_EXISTS, ERR_ASSIGNMENT_NOT_FOUND,
                    ERR_CHART_NOT_FOUND, ERR_CHART_NOT_READY,
                    ERR_CODER_CREDENTIAL_INSUFFICIENT, ERR_CODER_INACTIVE,
                    ERR_CODER_NOT_FOUND, ERR_DUPLICATE_SEQUENCE,
                    ERR_FORBIDDEN, ERR_INVALID_PRINCIPAL_CODE,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_MANIFESTATION_ORDER, ERR_NO_ELIGIBLE_CODER,
                    ERR_PRINCIPAL_DX_REQUIRED, ERR_WORKLOAD_OVERLAP, fail)
from middleware import ALL_ROLES, require_roles
from response import ok_obj, paginate
from services.calc import (compute_priority_score, coder_credit_workload,
                           coder_debit_workload, coder_record_accept,
                           regroup_case)
from services.core import (ACUITY_MIN_RANK, NON_TERMINAL_ASSIGNMENT, RANK,
                           active_dx_lines, assignment_for_chart,
                           bill_for_account, case_for_chart, ser_assignment)
from validators import body, has, req_dt

bp = Blueprint("assignments", __name__)


def get_assignment_or_404(asg_id):
    a = store.assignments.get(asg_id)
    if a is None:
        fail(404, ERR_ASSIGNMENT_NOT_FOUND, f"CodingAssignment {asg_id} does not exist")
    return a


def _check_credential(coder, chart):
    need = ACUITY_MIN_RANK[chart["acuity"]]
    if RANK[coder["credential"]] < need:
        fail(422, ERR_CODER_CREDENTIAL_INSUFFICIENT,
             f"Credential {coder['credential']} below requirement for {chart['acuity']}")


@bp.route("/assignments", methods=["POST"])
def create_assignment():
    require_roles("CodingManager")
    b = body()
    if not has(b, "chart_id"):
        fail(400, ERR_INVALID_REQUEST, "chart_id is required")
    chart = store.charts.get(b["chart_id"])
    if chart is None:
        fail(404, ERR_CHART_NOT_FOUND, f"Chart {b['chart_id']} does not exist")
    named = None
    if has(b, "coder_id"):
        named = store.coders.get(b["coder_id"])
        if named is None:
            fail(404, ERR_CODER_NOT_FOUND,
                 f"Coder {b['coder_id']} does not exist")
    # state tier
    if chart["status"] != "READY_FOR_CODING":
        fail(409, ERR_CHART_NOT_READY,
             f"Chart is {chart['status']}; must be READY_FOR_CODING")
    # credential tier (before the tier-7 constraint checks)
    if named is not None:
        _check_credential(named, chart)
    # tier-7 input validation
    due_at = req_dt(b, "due_at")
    if assignment_for_chart(chart["id"], statuses=NON_TERMINAL_ASSIGNMENT) is not None:
        fail(409, ERR_ASSIGNMENT_EXISTS,
             "A non-terminal assignment already exists for this chart")
    if named is None:
        need = ACUITY_MIN_RANK[chart["acuity"]]
        pool = [c for c in store.coders.values()
                if c["status"] == "ACTIVE" and RANK[c["credential"]] >= need]
        if not pool:
            fail(422, ERR_NO_ELIGIBLE_CODER,
                 "No ACTIVE coder meets the credential requirement")
        pool.sort(key=lambda c: (c["workload_units"], c["created_at"], c["_seq"]))
        named = pool[0]
    account = store.accounts[chart["account_id"]]
    assignment = stamp_new({
        "chart_id": chart["id"],
        "coder_id": named["id"],
        "status": "ASSIGNED",
        "priority_score": compute_priority_score(account, chart),
        "due_at": due_at,
        "assigned_at": now(),
        "started_at": None,
        "submitted_at": None,
        "accepted_at": None,
        "returned_count": 0,
        "return_reason": None,
    })
    store.assignments[assignment["id"]] = assignment
    coder_debit_workload(named, chart)
    return ok_obj(ser_assignment(assignment), 201)


@bp.route("/assignments/<id>", methods=["GET"])
def get_assignment(id):
    require_roles(*ALL_ROLES)
    return ok_obj(ser_assignment(get_assignment_or_404(id)), 200)


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    require_roles(*ALL_ROLES)
    items = list(store.assignments.values())
    chart_id = request.args.get("chart_id")
    if chart_id is not None:
        items = [a for a in items if a["chart_id"] == chart_id]
    coder_id = request.args.get("coder_id")
    if coder_id is not None:
        items = [a for a in items if a["coder_id"] == coder_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate([ser_assignment(a) for a in sort_default(items)])


@bp.route("/assignments/<id>/assign", methods=["POST"])
def assign_assignment(id):
    require_roles("CodingManager")
    assignment = get_assignment_or_404(id)
    b = body()
    coder = None
    if has(b, "coder_id"):
        coder = store.coders.get(b["coder_id"])
        if coder is None:
            fail(404, ERR_CODER_NOT_FOUND, f"Coder {b['coder_id']} does not exist")
    if assignment["status"] != "QUEUED":
        fail(409, ERR_INVALID_STATE,
             f"Cannot assign an assignment in state {assignment['status']}")
    if coder is not None:
        chart = store.charts[assignment["chart_id"]]
        _check_credential(coder, chart)
    else:
        fail(400, ERR_INVALID_REQUEST, "coder_id is required")
    chart = store.charts[assignment["chart_id"]]
    assignment["coder_id"] = coder["id"]
    assignment["assigned_at"] = now()
    assignment["status"] = "ASSIGNED"
    touch(assignment)
    coder_debit_workload(coder, chart)
    return ok_obj(ser_assignment(assignment), 200)


@bp.route("/assignments/<id>/start", methods=["POST"])
def start_assignment(id):
    uid, _ = require_roles("Coder")
    assignment = get_assignment_or_404(id)
    if assignment["coder_id"] != uid:
        fail(403, ERR_FORBIDDEN, "Only the assignment's own coder may start it")
    if assignment["status"] not in ("ASSIGNED", "RETURNED"):
        fail(409, ERR_INVALID_STATE,
             f"Cannot start an assignment in state {assignment['status']}")
    coder = store.coders[uid] if uid in store.coders else None
    if coder is None or coder["status"] != "ACTIVE":
        fail(409, ERR_CODER_INACTIVE, "Coder is not ACTIVE")
    chart = store.charts[assignment["chart_id"]]
    _check_credential(coder, chart)  # tier 6, before the workload rule
    if any(a["coder_id"] == uid and a["status"] == "IN_PROGRESS" and a["id"] != id
           for a in store.assignments.values()):
        fail(409, ERR_WORKLOAD_OVERLAP,
             "Coder already holds an IN_PROGRESS assignment")
    assignment["status"] = "IN_PROGRESS"
    assignment["started_at"] = now()
    touch(assignment)
    if chart["status"] == "READY_FOR_CODING":
        chart["status"] = "IN_CODING"
        touch(chart)
    return ok_obj(ser_assignment(assignment), 200)


@bp.route("/assignments/<id>/submit", methods=["POST"])
def submit_assignment(id):
    uid, _ = require_roles("Coder")
    assignment = get_assignment_or_404(id)
    if assignment["coder_id"] != uid:
        fail(403, ERR_FORBIDDEN, "Only the assignment's own coder may submit it")
    if assignment["status"] != "IN_PROGRESS":
        fail(409, ERR_INVALID_STATE,
             f"Cannot submit an assignment in state {assignment['status']}")
    chart = store.charts[assignment["chart_id"]]
    lines = active_dx_lines(chart["id"])
    principals = [l for l in lines if l["is_principal"]]
    if len(principals) != 1:
        fail(422, ERR_PRINCIPAL_DX_REQUIRED,
             "Exactly one ACTIVE principal diagnosis is required at submit")
    principal = principals[0]
    if principal["icd_code"][:1] in ("R", "Z"):
        fail(422, ERR_INVALID_PRINCIPAL_CODE,
             "Codes starting with R or Z may not be principal")
    seqs = [l["sequence"] for l in lines]
    if len(seqs) != len(set(seqs)):
        fail(422, ERR_DUPLICATE_SEQUENCE,
             "Duplicate sequence among ACTIVE lines on the chart")
    for l in lines:
        if l["is_manifestation"] and l["manifestation_of_id"] is not None:
            etio = store.dx_lines.get(l["manifestation_of_id"])
            if etio is not None and not l["sequence"] > etio["sequence"]:
                fail(422, ERR_MANIFESTATION_ORDER,
                     "A manifestation line must sequence strictly after its etiology line")
    assignment["status"] = "SUBMITTED"
    assignment["submitted_at"] = now()
    touch(assignment)
    chart["status"] = "SUBMITTED"
    touch(chart)
    case = case_for_chart(chart["id"])
    if case is None:
        case = stamp_new({
            "chart_id": chart["id"],
            "principal_dx_id": principal["id"],
            "grouper_variant": "MS_DRG",
            "base_partition": None,
            "severity_level": None,
            "relative_weight": None,
            "expected_reimbursement_cents": None,
            "status": "GROUPED",
        })
        store.coded_cases[case["id"]] = case
        # regroup_case touches; the create above already stamped version 1,
        # so neutralize the create-stamp and let the recompute own the version.
        case["version"] = 0
    else:
        case["principal_dx_id"] = principal["id"]
    regroup_case(case)
    return ok_obj(ser_assignment(assignment), 200)


@bp.route("/assignments/<id>/accept", methods=["POST"])
def accept_assignment(id):
    require_roles("CodingManager")
    assignment = get_assignment_or_404(id)
    if assignment["status"] != "SUBMITTED":
        fail(409, ERR_INVALID_STATE,
             f"Cannot accept an assignment in state {assignment['status']}")
    chart = store.charts[assignment["chart_id"]]
    assignment["status"] = "ACCEPTED"
    assignment["accepted_at"] = now()
    touch(assignment)
    chart["status"] = "CODED"  # cascade hop 1
    touch(chart)
    case = case_for_chart(chart["id"])
    account = store.accounts[chart["account_id"]]
    bill = bill_for_account(account["id"])
    if bill is not None and bill["status"] == "DRAFT":  # cascade hop 2
        bill["status"] = "READY"
        if case is not None:
            bill["expected_reimbursement_cents"] = case["expected_reimbursement_cents"]
        touch(bill)
    coder = store.coders.get(assignment["coder_id"])
    if coder is not None:
        coder_record_accept(coder, chart)
    return ok_obj(ser_assignment(assignment), 200)


@bp.route("/assignments/<id>/return", methods=["POST"])
def return_assignment(id):
    require_roles("CodingManager")
    assignment = get_assignment_or_404(id)
    if assignment["status"] != "SUBMITTED":
        fail(409, ERR_INVALID_STATE,
             f"Cannot return an assignment in state {assignment['status']}")
    b = body()
    reason = b.get("return_reason")
    if not isinstance(reason, str) or reason == "":
        fail(400, ERR_INVALID_REQUEST, "return_reason is required and must be non-empty")
    assignment["status"] = "RETURNED"
    assignment["return_reason"] = reason
    assignment["returned_count"] += 1
    touch(assignment)
    chart = store.charts[assignment["chart_id"]]
    chart["status"] = "IN_CODING"
    touch(chart)
    return ok_obj(ser_assignment(assignment), 200)


@bp.route("/assignments/<id>/release", methods=["POST"])
def release_assignment(id):
    require_roles("CodingManager")
    assignment = get_assignment_or_404(id)
    if assignment["status"] != "ASSIGNED":
        fail(409, ERR_INVALID_STATE,
             f"Cannot release an assignment in state {assignment['status']}")
    chart = store.charts[assignment["chart_id"]]
    coder = store.coders.get(assignment["coder_id"])
    if coder is not None:
        coder_credit_workload(coder, chart)
    assignment["coder_id"] = None
    assignment["status"] = "QUEUED"
    touch(assignment)
    return ok_obj(ser_assignment(assignment), 200)
