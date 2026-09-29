"""Battlecards, claim substantiation, legal review and publication (PRD 3.7-3.8)."""
from flask import Blueprint, g

from db import db, new_row, touch
from errors import fail
from middleware import ANY_ROLE, endpoint
from response import list_response, object_response
from validate import (ASSIGNMENT_STATUS, BATTLECARD_STATUS, CLAIM_TYPE,
                      LEGAL_DECISION, LEGAL_STATUS, RISK_CLASS,
                      SUBSTANTIATION_LEVEL, body, fk_from_body, fk_from_query,
                      opt_str, paginate, pagination, query_enum, req_enum,
                      req_str, req_str_array, resolve)

from services import calc, cascade, serialize
from services.listing import by_created_at

bp = Blueprint("battlecards", __name__)

CLAIM_WRITABLE_STATES = ("DRAFT", "LEGAL_REVIEW")


def get_card(battlecard_id):
    return resolve(db.battlecards, battlecard_id, "ERR_BATTLECARD_NOT_FOUND")


def _claim_of_card(card, claim_id):
    claim = db.battlecard_claims.get(claim_id)
    if claim is None or claim["battlecard_id"] != card["id"]:
        fail("ERR_BATTLECARD_CLAIM_NOT_FOUND")
    return claim


def _program_of_card(card):
    return calc.program_of_battlecard(card)


@bp.post("/battlecards")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def create_battlecard():
    payload = body()
    competitor = fk_from_body(payload, "competitor_id", db.competitors,
                              "ERR_COMPETITOR_NOT_FOUND")
    req_str(payload, "competitor_id")
    title = req_str(payload, "title")
    version_label = req_str(payload, "version_label")

    card = new_row({
        "competitor_id": competitor["id"],
        "title": title,
        "version_label": version_label,
        "status": "DRAFT",
        "published_at": None,
        "reopen_count": 0,
        "_authored_by": g.user_id,
    })
    db.battlecards[card["id"]] = card
    return object_response(serialize.battlecard(card), 201)


@bp.get("/battlecards/<battlecard_id>")
@endpoint(ANY_ROLE)
def read_battlecard(battlecard_id):
    return object_response(serialize.battlecard(get_card(battlecard_id)))


@bp.get("/battlecards")
@endpoint(ANY_ROLE)
def list_battlecards():
    competitor_id = fk_from_query("competitor_id", db.competitors,
                                  "ERR_COMPETITOR_NOT_FOUND")
    status = query_enum("status", BATTLECARD_STATUS)
    limit, offset = pagination()
    rows = list(db.battlecards.values())
    if competitor_id:
        rows = [c for c in rows if c["competitor_id"] == competitor_id]
    if status:
        rows = [c for c in rows if c["status"] == status]
    rows = by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.battlecard(r) for r in page],
                         limit, offset, total)


# ----------------------------------------------------------------------- claims
@bp.post("/battlecards/<battlecard_id>/claims")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def add_claim(battlecard_id):
    card = get_card(battlecard_id)
    payload = body()

    # 6. every element of the evidence set resolves
    raw = payload.get("evidence_response_ids")
    if isinstance(raw, list) and all(isinstance(v, str) for v in raw):
        for response_id in raw:
            resolve(db.interview_responses, response_id,
                    "ERR_INTERVIEW_RESPONSE_NOT_FOUND")

    # 7. structural
    claim_text = req_str(payload, "claim_text")
    claim_type = req_enum(payload, "claim_type", CLAIM_TYPE)
    evidence_ids = req_str_array(payload, "evidence_response_ids", non_empty=True)

    # 13. the card must accept content writes
    if card["status"] not in CLAIM_WRITABLE_STATES:
        fail("ERR_BATTLECARD_STATE_INVALID",
             "Claims cannot be added to the card in its current state.")

    # 38. evidence-set integrity
    program_id = calc.program_id_of_battlecard(card)
    deduped = []
    for response_id in evidence_ids:
        if response_id not in deduped:
            deduped.append(response_id)
    if not deduped:
        fail("ERR_EVIDENCE_SET_INVALID", "The evidence set is empty.")
    for response_id in deduped:
        response = db.interview_responses[response_id]
        interview = db.interviews.get(response["interview_id"])
        if interview is None or interview["status"] != "COMPLETED":
            fail("ERR_EVIDENCE_SET_INVALID",
                 "Every cited response must belong to a completed interview.")
        if calc.program_id_of_response(response) != program_id:
            fail("ERR_EVIDENCE_SET_INVALID",
                 "Every cited response must sit inside the card's program.")

    score, level, risk_class = calc.substantiation(deduped, claim_type, db.clock)
    claim = new_row({
        "battlecard_id": card["id"],
        "claim_text": claim_text,
        "claim_type": claim_type,
        "evidence_response_ids": deduped,
        "substantiation_score": score,
        "substantiation_level": level,
        "risk_class": risk_class,
        "legal_status": "PENDING",
        "conditions_note": None,
        "decided_at": None,
    })
    db.battlecard_claims[claim["id"]] = claim
    touch(card)
    return object_response(serialize.battlecard_claim(claim), 201)


@bp.get("/battlecards/<battlecard_id>/claims")
@endpoint(ANY_ROLE)
def list_card_claims(battlecard_id):
    card = get_card(battlecard_id)
    legal_status = query_enum("legal_status", LEGAL_STATUS)
    risk_class = query_enum("risk_class", RISK_CLASS)
    limit, offset = pagination()
    rows = calc.claims_of_battlecard(card["id"])
    if legal_status:
        rows = [c for c in rows if c["legal_status"] == legal_status]
    if risk_class:
        rows = [c for c in rows if c["risk_class"] == risk_class]
    rows = by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.battlecard_claim(r) for r in page],
                         limit, offset, total)


@bp.get("/battlecard-claims/<claim_id>")
@endpoint(ANY_ROLE)
def read_claim(claim_id):
    claim = resolve(db.battlecard_claims, claim_id, "ERR_BATTLECARD_CLAIM_NOT_FOUND")
    return object_response(serialize.battlecard_claim(claim))


@bp.get("/battlecard-claims")
@endpoint(ANY_ROLE)
def list_claims():
    battlecard_id = fk_from_query("battlecard_id", db.battlecards,
                                  "ERR_BATTLECARD_NOT_FOUND")
    legal_status = query_enum("legal_status", LEGAL_STATUS)
    risk_class = query_enum("risk_class", RISK_CLASS)
    level = query_enum("substantiation_level", SUBSTANTIATION_LEVEL)
    limit, offset = pagination()
    rows = list(db.battlecard_claims.values())
    if battlecard_id:
        rows = [c for c in rows if c["battlecard_id"] == battlecard_id]
    if legal_status:
        rows = [c for c in rows if c["legal_status"] == legal_status]
    if risk_class:
        rows = [c for c in rows if c["risk_class"] == risk_class]
    if level:
        rows = [c for c in rows if c["substantiation_level"] == level]
    rows = by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.battlecard_claim(r) for r in page],
                         limit, offset, total)


# -------------------------------------------------------------- legal decisions
@bp.post("/battlecards/<battlecard_id>/claims/<claim_id>/legal-decision")
@endpoint(("LegalReviewer",))
def legal_decision(battlecard_id, claim_id):
    card = get_card(battlecard_id)
    claim = _claim_of_card(card, claim_id)
    payload = body()
    decision = req_enum(payload, "decision", LEGAL_DECISION)
    conditions_note = opt_str(payload, "conditions_note")
    if decision == "CONDITIONAL" and not conditions_note:
        fail("ERR_INVALID_REQUEST",
             "conditions_note is required for a CONDITIONAL decision.")

    # 13. the decision must be admissible for the claim in the card's state
    if card["status"] not in ("LEGAL_REVIEW", "PUBLISHED"):
        fail("ERR_CLAIM_STATE_INVALID",
             "Legal decisions are only accepted while the card is in review "
             "or published.")
    current = claim["legal_status"]
    if current == "REJECTED":
        fail("ERR_CLAIM_STATE_INVALID", "REJECTED is terminal for a claim.")
    if current == "CONDITIONAL" and decision != "APPROVE":
        fail("ERR_CLAIM_STATE_INVALID",
             "A CONDITIONAL claim only accepts a subsequent APPROVE.")
    if current == "APPROVED" and not (decision == "REJECT"
                                      and card["status"] == "PUBLISHED"):
        fail("ERR_CLAIM_STATE_INVALID",
             "An APPROVED claim only admits rejection on a published card.")
    if decision == "APPROVE" and current == "PENDING" and \
            claim["substantiation_level"] == "UNSUBSTANTIATED":
        fail("ERR_CLAIM_STATE_INVALID",
             "An UNSUBSTANTIATED claim cannot be approved.")

    # 15. segregation of duties
    if g.user_id == card.get("_authored_by"):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The card's author may not review its claims.")

    if decision == "APPROVE":
        claim["legal_status"] = "APPROVED"
    elif decision == "CONDITIONAL":
        claim["legal_status"] = "CONDITIONAL"
        claim["conditions_note"] = conditions_note
    else:
        claim["legal_status"] = "REJECTED"
    claim["decided_at"] = db.clock
    touch(claim)
    touch(card)

    # card-level auto-transitions: the two branches of one fork
    if decision == "REJECT":
        if card["status"] == "LEGAL_REVIEW":
            card["status"] = "DRAFT"
            touch(card)
        elif card["status"] == "PUBLISHED":
            approved, _, _, _ = calc.claim_counts(card)
            if approved == 0:
                card["status"] = "WITHDRAWN"
                touch(card)
                cascade.expire_outstanding_assignments(card)
                competitor = db.competitors.get(card["competitor_id"])
                if competitor is not None:
                    touch(competitor)
    elif card["status"] == "LEGAL_REVIEW":
        claims = calc.claims_of_battlecard(card["id"])
        pending = [c for c in claims if c["legal_status"] == "PENDING"]
        approved, _, rejected, _ = calc.claim_counts(card)
        if not pending and approved >= 1 and rejected == 0:
            card["status"] = "APPROVED"
            touch(card)

    return object_response(serialize.battlecard_claim(claim))


# ---------------------------------------------------------------- card actions
@bp.post("/battlecards/<battlecard_id>/submit-legal")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def submit_legal(battlecard_id):
    card = get_card(battlecard_id)
    body()
    if card["status"] != "DRAFT":
        fail("ERR_BATTLECARD_STATE_INVALID",
             "Only a DRAFT card can be submitted for legal review.")
    claims = calc.claims_of_battlecard(card["id"])
    if not claims:
        fail("ERR_BATTLECARD_STATE_INVALID",
             "The card must carry at least one claim.")
    program = _program_of_card(card)
    if program is None or program["status"] != "ACTIVE":
        fail("ERR_PROGRAM_STATE_INVALID", "The owning program must be ACTIVE.")
    if calc.posture(program) == "FROZEN":
        fail("ERR_PROGRAM_POSTURE_FROZEN", "The program's posture is FROZEN.")
    for claim in claims:
        if claim["substantiation_level"] == "UNSUBSTANTIATED":
            fail("ERR_CLAIM_UNSUBSTANTIATED",
                 "Every claim must be at least ANECDOTAL.")

    card["status"] = "LEGAL_REVIEW"
    for claim in claims:
        if claim["legal_status"] == "REJECTED":
            continue
        if claim["legal_status"] != "PENDING" or claim.get("decided_at") is not None:
            claim["legal_status"] = "PENDING"
            claim["decided_at"] = None
            touch(claim)
    touch(card)
    return object_response(serialize.battlecard(card))


@bp.post("/battlecards/<battlecard_id>/publish")
@endpoint(("EnablementManager",))
def publish_battlecard(battlecard_id):
    card = get_card(battlecard_id)
    body()
    if card["status"] != "APPROVED":
        fail("ERR_BATTLECARD_STATE_INVALID", "Only an APPROVED card can be published.")
    program = _program_of_card(card)
    if program is not None and calc.posture(program) == "FROZEN":
        fail("ERR_PROGRAM_POSTURE_FROZEN", "The program's posture is FROZEN.")
    _, final = calc.risk_indices(card)
    if final > calc.PUBLISH_RISK_MAX:
        fail("ERR_RISK_CEILING_EXCEEDED",
             "risk_index_final exceeds the publication ceiling of 2.20.")

    card["status"] = "PUBLISHED"
    card["published_at"] = db.clock
    touch(card)
    competitor = db.competitors.get(card["competitor_id"])
    if competitor is not None:
        touch(competitor)
    return object_response(serialize.battlecard(card))


@bp.post("/battlecards/<battlecard_id>/reopen")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def reopen_battlecard(battlecard_id):
    card = get_card(battlecard_id)
    payload = body()
    opt_str(payload, "reopen_reason", allow_empty=True)
    if card["status"] != "PUBLISHED":
        fail("ERR_BATTLECARD_STATE_INVALID", "Only a PUBLISHED card can be reopened.")

    card["status"] = "DRAFT"
    card["reopen_count"] = card["reopen_count"] + 1
    touch(card)
    cascade.expire_outstanding_assignments(card)
    competitor = db.competitors.get(card["competitor_id"])
    if competitor is not None:
        touch(competitor)
    return object_response(serialize.battlecard(card))


@bp.get("/battlecards/<battlecard_id>/enablement-assignments")
@endpoint(ANY_ROLE)
def list_card_assignments(battlecard_id):
    card = get_card(battlecard_id)
    status = query_enum("status", ASSIGNMENT_STATUS)
    limit, offset = pagination()
    rows = calc.assignments_of_battlecard(card["id"])
    if status:
        rows = [a for a in rows if a["status"] == status]
    rows = sorted(by_created_at(rows), key=lambda a: a["due_at"].timestamp())
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.enablement_assignment(r) for r in page],
                         limit, offset, total)
