"""QAReport routes: file (drives job IN_QA -> QA_PASSED/REVISION), get. PRD §3.6, §3.10."""
from flask import Blueprint

from db import db, common_fields, touch
from errors import err
from middleware import get_user_context, require_role
from response import success_object
from serializers import qa_report_out
from services import calc
from services.helpers import get_json_body, require_fields
from services.lookups import (get_job, get_qa_report, get_assignment,
                              active_reviewer_assignment, assignments_of_job)

bp = Blueprint("qa_reports", __name__)


@bp.route("/jobs/<jid>/qa-reports", methods=["POST"])
def file_qa_report(jid):
    uid, role = get_user_context()
    require_role(role, {"Reviewer"})
    j = get_job(jid)
    body = get_json_body()
    require_fields(body, ["reviewer_assignment_id", "scored_word_count"])

    # body well-formedness (priority 4)
    crit = _count(body, "critical_count")
    maj = _count(body, "major_count")
    minor = _count(body, "minor_count")
    swc = body["scored_word_count"]
    if not isinstance(swc, int) or isinstance(swc, bool) or swc <= 0:
        raise err("ERR_INVALID_REQUEST", "scored_word_count must be a positive integer")

    # existence: reviewer_assignment_id must resolve
    reviewer_a = get_assignment(body["reviewer_assignment_id"])

    # state (priority 5): job must be IN_QA
    if j["status"] != "IN_QA":
        raise err("ERR_INVALID_STATE", "Job must be IN_QA to file a QA report")

    # priority 8: QA-report reviewer precondition. The named reviewer assignment
    # must be a REVIEWER assignment IN_PROGRESS on this job, owned by the acting
    # reviewer, and the reviewer must not be the translator.
    translator = None
    for a in assignments_of_job(jid):
        if a["role"] == "TRANSLATOR" and a["status"] in ("ACCEPTED", "IN_PROGRESS", "DELIVERED"):
            translator = a
            break
    if (reviewer_a["job_id"] != jid
            or reviewer_a["role"] != "REVIEWER"
            or reviewer_a["status"] != "IN_PROGRESS"
            or reviewer_a["linguist_id"] != uid
            or (translator is not None and translator["linguist_id"] == uid)):
        raise err("ERR_NO_REVIEWER_ASSIGNED",
                  "No valid IN_PROGRESS reviewer assignment for the acting reviewer")

    score, outcome = calc.qa_score(crit, maj, minor, swc)

    q = common_fields()
    q.update({
        "job_id": jid,
        "reviewer_assignment_id": reviewer_a["id"],
        "critical_count": crit,
        "major_count": maj,
        "minor_count": minor,
        "scored_word_count": swc,
        "score": score,
        "outcome": outcome,
    })
    db.qa_reports[q["id"]] = q

    # side effects: set job.latest_qa_score, drive transition, bump version
    j["latest_qa_score"] = score
    if outcome == "PASS":
        j["status"] = "QA_PASSED"
    else:
        j["status"] = "REVISION"
    touch(j)  # increments version

    return success_object(qa_report_out(q), 201)


def _count(body, field):
    if field in body and body[field] is not None:
        v = body[field]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise err("ERR_INVALID_REQUEST", "%s must be a non-negative integer" % field)
        return v
    return 0


@bp.route("/qa-reports/<qid>", methods=["GET"])
def get_qa_report_route(qid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "Reviewer", "Translator"})
    q = get_qa_report(qid)
    if role in ("Translator", "Reviewer"):
        held = any(a["linguist_id"] == uid for a in assignments_of_job(q["job_id"]))
        if not held:
            raise err("ERR_FORBIDDEN_FOR_ROLE", "Linguist may only read its own QA reports")
    return success_object(qa_report_out(q), 200)
