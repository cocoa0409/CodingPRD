"""Artist consultations, moral-rights notices and deaccession cases (PRD 3.6, 3.8)."""

from datetime import timedelta

from flask import Blueprint, g

import calc
import services as svc
from db import (
    create_record,
    db,
    fmt_date,
    fmt_instant,
    now,
    ordered,
    parse_instant,
    touch,
)
from errors import ApiError
from middleware import ANY_ROLE, endpoint, require_owner
from response import created, listing, ok
from validate import (
    BALLOTS,
    CONSULTATION_RESPONSES,
    CONSULTATION_SUBJECTS,
    DEACCESSION_CRITERIA,
    DISPOSITIONS,
    NOTICE_ACTION_TYPES,
    apply_filters,
    field,
    paging,
    parse_input,
)

bp = Blueprint("rights", __name__)


# ---------------------------------------------------------------------------
# ArtistConsultation
# ---------------------------------------------------------------------------

@bp.post("/public-art/artist-consultations")
@endpoint(("ChiefConservator", "PublicArtManager"))
def create_consultation():
    body = parse_input({
        "artwork_id": field("id", required=True),
        "artist_id": field("id", required=True),
        "subject": field("enum", required=True, enum=CONSULTATION_SUBJECTS),
        "proposal_id": field("id"),
    })
    artwork = svc.artwork_or_404(body["artwork_id"])
    artist = svc.artist_or_404(body["artist_id"])
    proposal = svc.proposal_or_404(body["proposal_id"]) if body["proposal_id"] else None
    svc.require_in_collection(artwork)

    clock = now()
    due_at = clock + timedelta(days=int(artist["consultation_response_days"]))
    record = create_record(db.consultations, {
        "artwork_id": artwork["id"],
        "artist_id": artist["id"],
        "proposal_id": proposal["id"] if proposal else None,
        "subject": body["subject"],
        "sent_on": fmt_date(clock),
        "due_at": fmt_instant(due_at),
        "status": "WAIVED" if artwork["moral_rights_status"] == "WAIVED" else "PENDING",
        "response_note": None,
        "responded_at": None,
    })
    return created(record)


@bp.get("/public-art/artist-consultations/<consultation_id>")
@endpoint(ANY_ROLE)
def read_consultation(consultation_id):
    return ok(svc.consultation_or_404(consultation_id))


@bp.get("/public-art/artist-consultations")
@endpoint(ANY_ROLE)
def list_consultations():
    limit, offset = paging()
    rows = apply_filters(db.consultations.values(), (
        ("artwork_id", "artwork_id", "string"),
        ("artist_id", "artist_id", "string"),
        ("proposal_id", "proposal_id", "string"),
        ("subject", "subject", "string"),
        ("status", "status", "string"),
    ))
    return listing(ordered(rows), limit, offset)


@bp.post("/public-art/artist-consultations/<consultation_id>/respond")
@endpoint(("ArtistRepresentative",))
def respond_consultation(consultation_id):
    consultation = svc.consultation_or_404(consultation_id)
    body = parse_input({
        "response": field("enum", required=True, enum=CONSULTATION_RESPONSES),
        "response_note": field("string"),
    })
    require_owner(consultation["artist_id"])
    svc.require_state(consultation["status"], ("PENDING",), "ERR_CONSULTATION_INVALID_STATE")
    if now() >= parse_instant(consultation["due_at"]):
        raise ApiError("ERR_CONSULTATION_WINDOW_CLOSED")

    consultation["status"] = "CONCURRED" if body["response"] == "CONCUR" else "OBJECTED"
    consultation["response_note"] = body["response_note"]
    consultation["responded_at"] = fmt_instant(now())
    touch(consultation)
    return ok(consultation)


# ---------------------------------------------------------------------------
# MoralRightsNotice
# ---------------------------------------------------------------------------

@bp.post("/public-art/moral-rights-notices")
@endpoint(("PublicArtManager", "CollectionsRegistrar"))
def create_notice():
    body = parse_input({
        "artwork_id": field("id", required=True),
        "artist_id": field("id", required=True),
        "action_type": field("enum", required=True, enum=NOTICE_ACTION_TYPES),
    })
    artwork = svc.artwork_or_404(body["artwork_id"])
    artist = svc.artist_or_404(body["artist_id"])
    svc.require_in_collection(artwork)

    clock = now()
    record = create_record(db.notices, {
        "artwork_id": artwork["id"],
        "artist_id": artist["id"],
        "action_type": body["action_type"],
        "sent_at": fmt_instant(clock),
        "earliest_action_at": fmt_instant(
            clock + timedelta(days=int(artist["notice_wait_days"]))
        ),
        "status": "SENT",
        "acknowledged_at": None,
        "consumed_by_ref": None,
    })
    svc.recompute_open_notice_count(artwork)
    return created(record)


@bp.get("/public-art/moral-rights-notices/<notice_id>")
@endpoint(ANY_ROLE)
def read_notice(notice_id):
    return ok(svc.notice_or_404(notice_id))


@bp.get("/public-art/moral-rights-notices")
@endpoint(ANY_ROLE)
def list_notices():
    limit, offset = paging()
    rows = apply_filters(db.notices.values(), (
        ("artwork_id", "artwork_id", "string"),
        ("artist_id", "artist_id", "string"),
        ("action_type", "action_type", "string"),
        ("status", "status", "string"),
    ))
    return listing(ordered(rows), limit, offset)


@bp.post("/public-art/moral-rights-notices/<notice_id>/acknowledge")
@endpoint(("ArtistRepresentative",))
def acknowledge_notice(notice_id):
    notice = svc.notice_or_404(notice_id)
    parse_input({"acknowledgement_note": field("string")})
    require_owner(notice["artist_id"])
    svc.require_state(notice["status"], ("SENT",), "ERR_NOTICE_INVALID_STATE")
    notice["status"] = "ACKNOWLEDGED"
    notice["acknowledged_at"] = fmt_instant(now())
    touch(notice)
    return ok(notice)


# ---------------------------------------------------------------------------
# DeaccessionCase
# ---------------------------------------------------------------------------

@bp.post("/public-art/deaccession-cases")
@endpoint(("PublicArtManager",))
def create_case():
    body = parse_input({
        "artwork_id": field("id", required=True),
        "criteria": field("enum_array", required=True, enum=DEACCESSION_CRITERIA),
        "disposition": field("enum", required=True, enum=DISPOSITIONS),
        "disposition_target_ref": field("string"),
        "comment_days": field("int", default=45, minimum=7, maximum=180),
    })
    artwork = svc.artwork_or_404(body["artwork_id"])
    svc.require_in_collection(artwork)
    record = create_record(db.cases, {
        "artwork_id": artwork["id"],
        "criteria": body["criteria"],
        "disposition": body["disposition"],
        "disposition_target_ref": body["disposition_target_ref"],
        "comment_days": body["comment_days"],
        "initiated_by_user_id": g.user_id,
        "public_comment_opens_on": None,
        "public_comment_closes_at": None,
        "status": "INITIATED",
        "vote_records": [],
        "approve_count": 0,
        "deny_count": 0,
        "abstain_count": 0,
        "recuse_count": 0,
        "decision_ratio": None,
        "executed_at": None,
    })
    return created(record)


@bp.get("/public-art/deaccession-cases/<case_id>")
@endpoint(ANY_ROLE)
def read_case(case_id):
    return ok(svc.case_or_404(case_id))


@bp.get("/public-art/deaccession-cases")
@endpoint(ANY_ROLE)
def list_cases():
    limit, offset = paging()
    rows = apply_filters(db.cases.values(), (
        ("artwork_id", "artwork_id", "string"),
        ("status", "status", "string"),
        ("disposition", "disposition", "string"),
    ))
    return listing(ordered(rows), limit, offset)


@bp.post("/public-art/deaccession-cases/<case_id>/advance")
@endpoint(("PublicArtManager",))
def advance_case(case_id):
    case = svc.case_or_404(case_id)
    parse_input({"advance_note": field("string")})
    svc.require_state(case["status"], ("INITIATED", "PUBLIC_COMMENT"), "ERR_CASE_INVALID_STATE")

    if case["status"] == "INITIATED":
        svc.require_in_collection(svc.artwork_or_404(case["artwork_id"]))
        clock = now()
        case["public_comment_opens_on"] = fmt_date(clock)
        case["public_comment_closes_at"] = fmt_instant(
            clock + timedelta(days=int(case["comment_days"]))
        )
        case["status"] = "PUBLIC_COMMENT"
        touch(case)
        return ok(case)

    if now() < parse_instant(case["public_comment_closes_at"]):
        raise ApiError("ERR_PUBLIC_COMMENT_OPEN")
    case["status"] = "BOARD_REVIEW"
    touch(case)
    return ok(case)


_BALLOT_COUNTERS = {
    "APPROVE": "approve_count",
    "DENY": "deny_count",
    "ABSTAIN": "abstain_count",
    "RECUSE": "recuse_count",
}


@bp.post("/public-art/deaccession-cases/<case_id>/votes")
@endpoint(("ArtCommissionMember", "PublicArtManager"))
def cast_ballot(case_id):
    case = svc.case_or_404(case_id)
    body = parse_input({
        "ballot": field("enum", required=True, enum=BALLOTS),
        "ballot_note": field("string"),
    })
    svc.require_state(case["status"], ("BOARD_REVIEW",), "ERR_CASE_INVALID_STATE")
    if g.user_id == case["initiated_by_user_id"] and body["ballot"] in ("APPROVE", "DENY"):
        raise ApiError("ERR_INITIATOR_CANNOT_VOTE")
    for entry in case["vote_records"]:
        if entry["member_user_id"] == g.user_id:
            raise ApiError("ERR_DUPLICATE_BALLOT")

    case["vote_records"].append({
        "member_user_id": g.user_id,
        "ballot": body["ballot"],
        "created_at": fmt_instant(now()),
    })
    counter = _BALLOT_COUNTERS[body["ballot"]]
    case[counter] = int(case[counter]) + 1

    quorum_votes = (
        int(case["approve_count"]) + int(case["deny_count"]) + int(case["abstain_count"])
    )
    if quorum_votes >= calc.QUORUM_MIN_VOTES:
        ratio = calc.decision_ratio(int(case["approve_count"]), int(case["deny_count"]))
        case["decision_ratio"] = float(ratio)
        case["status"] = "APPROVED" if ratio >= calc.APPROVE_RATIO_MIN else "DENIED"
    touch(case)
    return ok(case)


@bp.post("/public-art/deaccession-cases/<case_id>/execute")
@endpoint(("PublicArtManager",))
def execute_case(case_id):
    case = svc.case_or_404(case_id)
    parse_input({"execution_note": field("string")})
    svc.require_state(case["status"], ("APPROVED",), "ERR_CASE_INVALID_STATE")
    artwork = svc.artwork_or_404(case["artwork_id"])
    svc.require_in_collection(artwork)

    if case["disposition"] == "DESTRUCTION" and artwork.get("recognized_stature"):
        raise ApiError("ERR_RECOGNIZED_STATURE_PROTECTED")

    notice = None
    if artwork["moral_rights_status"] == "ACTIVE":
        notice = svc.authorizing_notice(artwork, ("REMOVAL", "DESTRUCTION"))

    if case["disposition"] in ("SALE", "TRANSFER") and not case.get("disposition_target_ref"):
        raise ApiError("ERR_DISPOSITION_TARGET_REQUIRED")

    case["status"] = "EXECUTED"
    case["executed_at"] = fmt_instant(now())
    touch(case)
    svc.cascade_b(case, artwork, notice)
    return ok(case)
