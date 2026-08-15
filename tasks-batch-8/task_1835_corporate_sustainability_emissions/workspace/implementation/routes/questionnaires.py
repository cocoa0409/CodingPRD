"""Framework questionnaire responses under independent review (PRD 3.9)."""
from flask import Blueprint, g, request

import calc
import domain
from envelope import ok, ok_list
from errors import err, invalid_request, invalid_state, not_found, sod
from http_util import (
    DISCLOSURE_LEAD,
    MANAGER,
    READ_ROLES,
    get_body,
    parse_pagination,
    require_roles,
    v_enum,
    v_str,
)
from store import db, new_entity, touch

bp = Blueprint("questionnaires", __name__, url_prefix="/sustainability")

FRAMEWORKS = {"CDP", "GRI", "ECOVADIS"}
QUESTIONNAIRE_STATUSES = {"DRAFT", "IN_REVIEW", "APPROVED", "SUBMITTED"}
DECISIONS = {"APPROVE", "REQUEST_CHANGES"}

# Cycle statuses that block the DRAFT -> IN_REVIEW submit-for-review gate.
REVIEW_BLOCKED_CYCLE = ("LOCKED", "UNDER_ASSURANCE", "ASSURED", "DISCLOSED")


def load_questionnaire(qid):
    q = db.questionnaires.get(qid)
    if q is None:
        raise not_found(f"QuestionnaireResponse {qid} not found")
    return q


@bp.route("/questionnaire-responses", methods=["POST"])
@require_roles(DISCLOSURE_LEAD)
def create_questionnaire():
    body = get_body()
    # Priority 3: body FK.
    cid = body.get("cycle_id")
    if cid is not None and (not isinstance(cid, str) or cid not in db.cycles):
        raise not_found("Field cycle_id does not resolve to an existing resource")
    # Priority 4: request shape.
    cycle = db.cycles[v_str(body, "cycle_id")]
    framework = v_enum(body, "framework", FRAMEWORKS)
    # Priority 13: one response per (cycle_id, framework).
    for other in db.questionnaires.values():
        if other["cycle_id"] == cycle["id"] and other["framework"] == framework:
            raise err(
                "ERR_DUPLICATE_QUESTIONNAIRE",
                409,
                "A QuestionnaireResponse already exists for this cycle and framework",
            )
    q = new_entity(
        {
            "cycle_id": cycle["id"],
            "framework": framework,
            "prepared_by_user_id": g.user_id,
            "sections": {},
            "completeness_pct": 0.0,
            "emissions_section_stale": False,
            "status": "DRAFT",
            "review_decision_by": None,
            "review_notes": None,
        }
    )
    db.questionnaires[q["id"]] = q
    return ok(domain.ser_questionnaire(q), status=201)


@bp.route("/questionnaire-responses/<qid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_questionnaire(qid):
    return ok(domain.ser_questionnaire(load_questionnaire(qid)))


@bp.route("/questionnaire-responses", methods=["GET"])
@require_roles(*READ_ROLES)
def list_questionnaires():
    limit, offset = parse_pagination()
    items = sorted(db.questionnaires.values(), key=lambda x: x["_seq"])
    cycle_id = request.args.get("cycle_id")
    framework = request.args.get("framework")
    status = request.args.get("status")
    if cycle_id is not None:
        items = [q for q in items if q["cycle_id"] == cycle_id]
    if framework is not None:
        items = [q for q in items if q["framework"] == framework]
    if status is not None:
        items = [q for q in items if q["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.ser_questionnaire(q) for q in page], limit, offset, total)


@bp.route("/questionnaire-responses/<qid>/answers", methods=["POST"])
@require_roles(DISCLOSURE_LEAD)
def upsert_answer(qid):
    q = load_questionnaire(qid)
    body = get_body()
    # Priority 4: request shape; section keys are the framework-required set.
    section_key = v_str(body, "section_key")
    answer_text = v_str(body, "answer_text")
    if section_key not in calc.REQUIRED_SECTIONS[q["framework"]]:
        raise invalid_request(
            f"Section {section_key} is not a required section of framework {q['framework']}"
        )
    # Priority 6: answers are upserted in DRAFT only.
    if q["status"] != "DRAFT":
        raise invalid_state(
            f"QuestionnaireResponse in status {q['status']} no longer accepts answers"
        )
    q["sections"][section_key] = {"answer_text": answer_text}
    calc.recompute_completeness(q)
    # Only re-answering EMISSIONS clears the staleness marker.
    if section_key == "EMISSIONS":
        q["emissions_section_stale"] = False
    touch(q)
    return ok(domain.ser_questionnaire(q))


@bp.route("/questionnaire-responses/<qid>/transition", methods=["POST"])
@require_roles(DISCLOSURE_LEAD)
def questionnaire_transition(qid):
    q = load_questionnaire(qid)
    body = get_body()
    to_state = v_enum(body, "to_state", QUESTIONNAIRE_STATUSES)
    cycle = db.cycles[q["cycle_id"]]
    if to_state == "IN_REVIEW":
        # Priority 6: own state, then the cycle gate; the section gate (PRD
        # priority 15) runs after the cycle check (PRD 3.9).
        if q["status"] != "DRAFT":
            raise invalid_state(
                f"QuestionnaireResponse in status {q['status']} cannot move to IN_REVIEW"
            )
        if cycle["status"] in REVIEW_BLOCKED_CYCLE:
            raise err(
                "ERR_CYCLE_NOT_COLLECTING",
                409,
                f"Cycle in status {cycle['status']} does not permit submit-for-review",
            )
        required = calc.REQUIRED_SECTIONS[q["framework"]]
        if any(s not in q["sections"] for s in required) or q["emissions_section_stale"]:
            raise err(
                "ERR_SECTION_INCOMPLETE",
                422,
                "Required sections are unanswered or the EMISSIONS section is stale",
            )
    elif to_state == "SUBMITTED":
        if q["status"] != "APPROVED":
            raise invalid_state(
                f"QuestionnaireResponse in status {q['status']} cannot move to SUBMITTED"
            )
        if cycle["status"] == "DISCLOSED":
            raise err(
                "ERR_CYCLE_NOT_COLLECTING",
                409,
                "The parent cycle is already DISCLOSED",
            )
    else:
        raise invalid_state(
            f"QuestionnaireResponse in status {q['status']} cannot transition to {to_state}"
        )
    q["status"] = to_state
    touch(q)
    return ok(domain.ser_questionnaire(q))


@bp.route("/questionnaire-responses/<qid>/review-decision", methods=["POST"])
@require_roles(MANAGER)
def review_decision(qid):
    q = load_questionnaire(qid)
    body = get_body()
    decision = v_enum(body, "decision", DECISIONS)
    review_notes = body.get("review_notes")
    if review_notes is not None and not isinstance(review_notes, str):
        raise invalid_request("Field review_notes must be a string")
    # Priority 6: own state.
    if q["status"] != "IN_REVIEW":
        raise invalid_state(
            f"QuestionnaireResponse in status {q['status']} is not awaiting review"
        )
    # Priority 7: the independent reviewer must differ from the preparer.
    if g.user_id == q["prepared_by_user_id"]:
        raise sod("The review decision-maker must differ from the preparer")
    q["status"] = "APPROVED" if decision == "APPROVE" else "DRAFT"
    q["review_decision_by"] = g.user_id
    q["review_notes"] = review_notes
    touch(q)
    return ok(domain.ser_questionnaire(q))
