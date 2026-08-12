"""Decision-domain services: resolutions, vote records, conflict
disclosures, minutes/minute book, audit reconstruction, and the governance
checkpoint."""

import hashlib
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import (
    ERR_CLEARING_RESOLUTION_NOT_ADOPTED,
    ERR_CONFLICT_RECUSAL_REQUIRED,
    ERR_CONSENT_DEADLINE_PASSED,
    ERR_CROSS_CORPORATION_REFERENCE,
    ERR_DISCLOSURE_WINDOW_CONFLICT,
    ERR_DUPLICATE_VOTE,
    ERR_FORBIDDEN_ROLE,
    ERR_INELIGIBLE_VOTER,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MEETING_NOT_IN_SESSION,
    ERR_NO_ADOPTED_BYLAWS,
    ERR_NOT_FOUND,
    ERR_QUORUM_NOT_MET,
    ERR_VALIDATION,
    raise_err,
)
from response import list_response, serialize_row, success_object
from services_core import (
    active_directors_of,
    adopted_bylaws_for,
    director_departure_cascade,
    get_or_404,
    has_open_matching_disclosure,
    recompute_resolution_tallies,
    void_active_votes,
)
from util import add_years, iso_ms, opt_string, req_datetime, req_enum, req_string

PRESENT_MODES = ("IN_PERSON", "REMOTE", "PROXY")


# ---------------------------------------------------------------------------
# Resolutions
# ---------------------------------------------------------------------------


def create_resolution(body):
    corporation_id = req_string(body, "corporation_id")
    origin = req_enum(body, "origin", ("MEETING", "WRITTEN_CONSENT"))
    resolution_type = req_enum(body, "resolution_type", ("ORDINARY", "SPECIAL"))
    title = req_string(body, "title")
    text = req_string(body, "text")
    related_party = opt_string(body, "related_party")
    meeting_id = opt_string(body, "meeting_id")

    if origin == "MEETING" and meeting_id is None:
        raise_err(ERR_VALIDATION, "meeting_id is required when origin is MEETING")
    if origin == "WRITTEN_CONSENT" and meeting_id is not None:
        raise_err(ERR_VALIDATION, "meeting_id must be null when origin is WRITTEN_CONSENT")

    get_or_404(db.corporations, corporation_id, "Corporation")
    meeting = None
    if meeting_id is not None:
        meeting = get_or_404(db.meetings, meeting_id, "Meeting")

    if meeting is not None and meeting["corporation_id"] != corporation_id:
        raise_err(
            ERR_CROSS_CORPORATION_REFERENCE,
            "Meeting belongs to a different corporation",
        )

    row = db.new_row()
    row.update(
        {
            "corporation_id": corporation_id,
            "meeting_id": meeting_id,
            "origin": origin,
            "resolution_type": resolution_type,
            "title": title,
            "text": text,
            "related_party": related_party,
            "status": "DRAFT",
            "consent_deadline_at": None,
            "consent_required_count": None,
            "consent_bylaws_id": None,
            "for_count": 0,
            "against_count": 0,
            "abstain_count": 0,
            "recused_count": 0,
            "closed_at": None,
            "_consent_eligible_ids": None,
            "_eligible_pool_at_close": None,
        }
    )
    db.resolutions[row["id"]] = row
    return success_object(serialize_row(row), status=201)


def list_resolutions(args):
    return list_response(
        db.resolutions.values(),
        [
            ("corporation_id", args.get("corporation_id")),
            ("meeting_id", args.get("meeting_id")),
            ("status", args.get("status")),
            ("consent_bylaws_id", args.get("consent_bylaws_id")),
        ],
        args,
    )


def get_resolution(resolution_id):
    return success_object(
        serialize_row(get_or_404(db.resolutions, resolution_id, "Resolution"))
    )


def table_resolution(resolution_id, caller_role):
    resolution = get_or_404(db.resolutions, resolution_id, "Resolution")
    if resolution["status"] == "DRAFT":
        # DRAFT -> TABLED: secretary or chair; MEETING origin; meeting
        # NOTICED or IN_SESSION.
        if resolution["origin"] != "MEETING":
            raise_err(
                ERR_INVALID_STATE_TRANSITION,
                "Only MEETING-origin resolutions can be tabled",
            )
        meeting = db.meetings.get(resolution["meeting_id"])
        if meeting is None or meeting["status"] not in ("NOTICED", "IN_SESSION"):
            raise_err(
                ERR_INVALID_STATE_TRANSITION,
                "The linked meeting must be NOTICED or IN_SESSION to table",
            )
        resolution["status"] = "TABLED"
        db.touch(resolution)
        return success_object(serialize_row(resolution))
    if resolution["status"] == "VOTE_OPEN":
        # VOTE_OPEN -> TABLED (withdraw from the floor): chair only; voids
        # every ACTIVE ballot already cast.
        if caller_role != "BoardChair":
            raise_err(
                ERR_FORBIDDEN_ROLE,
                "Only the BoardChair may withdraw an open vote",
            )
        void_active_votes(resolution)
        resolution["status"] = "TABLED"
        recompute_resolution_tallies(resolution)
        db.touch(resolution)
        return success_object(serialize_row(resolution))
    raise_err(
        ERR_INVALID_STATE_TRANSITION,
        "Only a DRAFT or VOTE_OPEN resolution can be tabled",
    )


def open_vote(resolution_id):
    resolution = get_or_404(db.resolutions, resolution_id, "Resolution")
    if resolution["status"] != "TABLED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a TABLED resolution can open voting")
    meeting = db.meetings.get(resolution["meeting_id"])
    if meeting is None or meeting["status"] != "IN_SESSION":
        raise_err(ERR_MEETING_NOT_IN_SESSION, "The linked meeting is not IN_SESSION")
    # Rolling quorum: re-evaluated from ALL current attendance records.
    present = sum(
        1
        for record in db.attendance_records.values()
        if record["meeting_id"] == meeting["id"]
        and record["attendance_mode"] in PRESENT_MODES
    )
    required = meeting.get("quorum_required_count")
    if required is None or present < required:
        raise_err(ERR_QUORUM_NOT_MET, "Rolling presence %s is below quorum %s" % (present, required))
    resolution["status"] = "VOTE_OPEN"
    db.touch(resolution)
    return success_object(serialize_row(resolution))


def _eligible_pool(resolution):
    """Directors ACTIVE now, minus those holding an OPEN disclosure whose
    related_party matches the resolution's."""
    actives = active_directors_of(resolution["corporation_id"])
    recused = {
        d["id"]
        for d in actives
        if has_open_matching_disclosure(d["id"], resolution["related_party"])
    }
    return len(actives) - len(recused)


def close_vote(resolution_id):
    resolution = get_or_404(db.resolutions, resolution_id, "Resolution")
    if resolution["status"] != "VOTE_OPEN":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a VOTE_OPEN resolution can be closed")
    recompute_resolution_tallies(resolution)
    eligible = _eligible_pool(resolution)
    resolution["_eligible_pool_at_close"] = eligible
    for_count = resolution["for_count"]
    against_count = resolution["against_count"]
    if resolution["resolution_type"] == "ORDINARY":
        # present-and-voting: strict majority of non-abstain cast ballots
        adopted = for_count * 2 > (for_count + against_count)
    else:
        # full-board majority: floor(eligible / 2) + 1
        adopted = for_count >= (eligible // 2) + 1
    resolution["status"] = "ADOPTED" if adopted else "REJECTED"
    resolution["closed_at"] = db.clock_now()
    db.touch(resolution)
    return success_object(serialize_row(resolution))


def redraft_resolution(resolution_id):
    resolution = get_or_404(db.resolutions, resolution_id, "Resolution")
    if resolution["status"] not in ("REJECTED", "CONSENT_LAPSED"):
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Only a REJECTED or CONSENT_LAPSED resolution can be redrafted",
        )
    void_active_votes(resolution)
    resolution["status"] = "DRAFT"
    resolution["for_count"] = 0
    resolution["against_count"] = 0
    resolution["abstain_count"] = 0
    resolution["recused_count"] = 0
    resolution["consent_deadline_at"] = None
    resolution["consent_required_count"] = None
    resolution["consent_bylaws_id"] = None
    resolution["closed_at"] = None
    resolution["_consent_eligible_ids"] = None
    resolution["_eligible_pool_at_close"] = None
    db.touch(resolution)
    return success_object(serialize_row(resolution))


def circulate_consent(resolution_id):
    resolution = get_or_404(db.resolutions, resolution_id, "Resolution")
    if resolution["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a DRAFT resolution can be circulated")
    if resolution["origin"] != "WRITTEN_CONSENT":
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Only WRITTEN_CONSENT-origin resolutions can circulate for consent",
        )
    bylaws_row = adopted_bylaws_for(resolution["corporation_id"])
    if bylaws_row is None:
        raise_err(ERR_NO_ADOPTED_BYLAWS, "An ADOPTED bylaws is required to circulate a consent")

    # Pinned evaluation order: (1) ACTIVE directors now, (2) remove those
    # recused by an OPEN matching disclosure, (3) unanimity -> all remaining,
    # else floor(half)+1, (4) store and never revisit.
    active_set = active_directors_of(resolution["corporation_id"])
    eligible_ids = [
        d["id"]
        for d in active_set
        if not has_open_matching_disclosure(d["id"], resolution["related_party"])
    ]
    if bylaws_row["consent_unanimity_required"]:
        required = len(eligible_ids)
    else:
        required = (len(eligible_ids) // 2) + 1

    resolution["consent_bylaws_id"] = bylaws_row["id"]
    resolution["consent_deadline_at"] = db.clock_now() + timedelta(
        days=bylaws_row["consent_window_days"]
    )
    resolution["consent_required_count"] = required
    resolution["_consent_eligible_ids"] = set(eligible_ids)
    resolution["status"] = "CIRCULATING"
    db.touch(resolution)
    return success_object(serialize_row(resolution))


def _consent_for_count(resolution):
    return sum(
        1
        for vote in db.vote_records.values()
        if vote["resolution_id"] == resolution["id"]
        and vote["status"] == "ACTIVE"
        and vote["vote"] == "FOR"
    )


def finalize_consent(resolution_id):
    resolution = get_or_404(db.resolutions, resolution_id, "Resolution")
    if resolution["status"] != "CIRCULATING":
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Only a CIRCULATING resolution can be finalized",
        )
    for_count = _consent_for_count(resolution)
    if for_count >= (resolution["consent_required_count"] or 0):
        resolution["status"] = "CONSENT_ADOPTED"
        resolution["closed_at"] = db.clock_now()
        db.touch(resolution)
    elif db.clock_now() > resolution["consent_deadline_at"]:
        resolution["status"] = "CONSENT_LAPSED"
        resolution["closed_at"] = db.clock_now()
        db.touch(resolution)
    # Otherwise the circulation remains open; the evaluation is a no-op.
    return success_object(serialize_row(resolution))


# ---------------------------------------------------------------------------
# Vote records (ballots and consent signatures)
# ---------------------------------------------------------------------------


def cast_vote(body, caller_id):
    resolution_id = req_string(body, "resolution_id")
    channel = req_enum(body, "channel", ("MEETING_BALLOT", "WRITTEN_CONSENT"))
    vote = req_enum(body, "vote", ("FOR", "AGAINST", "ABSTAIN", "RECUSED"))
    if channel == "WRITTEN_CONSENT" and vote in ("ABSTAIN", "RECUSED"):
        raise_err(
            ERR_VALIDATION,
            "The WRITTEN_CONSENT channel admits only FOR or AGAINST",
        )

    resolution = get_or_404(db.resolutions, resolution_id, "Resolution")

    # State tier.
    if channel == "MEETING_BALLOT":
        if resolution["status"] != "VOTE_OPEN":
            raise_err(
                ERR_INVALID_STATE_TRANSITION,
                "Ballots are cast only while the resolution is VOTE_OPEN",
            )
    else:
        if resolution["status"] != "CIRCULATING":
            raise_err(
                ERR_INVALID_STATE_TRANSITION,
                "Consents are signed only while the resolution is CIRCULATING",
            )

    # Clock-relative temporal tier.
    if channel == "WRITTEN_CONSENT" and db.clock_now() > resolution["consent_deadline_at"]:
        raise_err(ERR_CONSENT_DEADLINE_PASSED, "The consent deadline has passed")

    # Compliance tier: a conflicted director may only vote RECUSED on the
    # floor, and may not sign a consent at all.
    conflicted = has_open_matching_disclosure(caller_id, resolution["related_party"])
    if conflicted:
        if channel == "WRITTEN_CONSENT" or vote != "RECUSED":
            raise_err(
                ERR_CONFLICT_RECUSAL_REQUIRED,
                "A director with an OPEN matching disclosure must vote RECUSED "
                "and may not sign a consent",
            )

    # Uniqueness tier: one ACTIVE record per (resolution, director, channel).
    for record in db.vote_records.values():
        if (
            record["resolution_id"] == resolution["id"]
            and record["director_id"] == caller_id
            and record["channel"] == channel
            and record["status"] == "ACTIVE"
        ):
            raise_err(ERR_DUPLICATE_VOTE, "An ACTIVE vote record already exists")

    # Cross-reference / lifecycle tier: caster eligibility.
    director = db.directors.get(caller_id)
    if channel == "MEETING_BALLOT":
        meeting = db.meetings.get(resolution["meeting_id"])
        if meeting is None or meeting["status"] != "IN_SESSION":
            raise_err(ERR_MEETING_NOT_IN_SESSION, "The linked meeting is not IN_SESSION")
        present = any(
            record["meeting_id"] == meeting["id"]
            and record["director_id"] == caller_id
            and record["attendance_mode"] in PRESENT_MODES
            for record in db.attendance_records.values()
        )
        if director is None or director["status"] != "ACTIVE" or not present:
            raise_err(
                ERR_INELIGIBLE_VOTER,
                "The caster must be an ACTIVE director present at the meeting",
            )
    else:
        eligible_ids = resolution.get("_consent_eligible_ids") or set()
        if (
            director is None
            or director["status"] != "ACTIVE"
            or caller_id not in eligible_ids
        ):
            raise_err(
                ERR_INELIGIBLE_VOTER,
                "The signer must belong to the non-recused active set frozen at "
                "circulation and still be ACTIVE",
            )

    row = db.new_row()
    row.update(
        {
            "resolution_id": resolution["id"],
            "director_id": caller_id,
            "channel": channel,
            "vote": vote,
            "status": "ACTIVE",
            "cast_at": db.clock_now(),
            "recast_count": 0,
        }
    )
    db.vote_records[row["id"]] = row
    recompute_resolution_tallies(resolution)
    db.touch(resolution)
    return success_object(serialize_row(row), status=201)


def list_vote_records(args):
    return list_response(
        db.vote_records.values(),
        [
            ("resolution_id", args.get("resolution_id")),
            ("director_id", args.get("director_id")),
            ("channel", args.get("channel")),
            ("status", args.get("status")),
        ],
        args,
    )


def get_vote_record(record_id):
    return success_object(
        serialize_row(get_or_404(db.vote_records, record_id, "VoteRecord"))
    )


def recast_vote(record_id, body, caller_id):
    record = get_or_404(db.vote_records, record_id, "VoteRecord")
    if caller_id != record["director_id"]:
        raise_err(ERR_FORBIDDEN_ROLE, "Only the original caster may recast a ballot")
    vote = req_enum(body, "vote", ("FOR", "AGAINST", "ABSTAIN", "RECUSED"))

    resolution = get_or_404(db.resolutions, record["resolution_id"], "Resolution")
    if record["status"] != "ACTIVE" or resolution["status"] != "VOTE_OPEN":
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Ballots can be recast only while ACTIVE and the resolution is VOTE_OPEN",
        )

    # Compliance: a conflicted caster may only hold a RECUSED ballot.
    if has_open_matching_disclosure(caller_id, resolution["related_party"]) and vote != "RECUSED":
        raise_err(
            ERR_CONFLICT_RECUSAL_REQUIRED,
            "A director with an OPEN matching disclosure must vote RECUSED",
        )

    record["vote"] = vote
    record["recast_count"] = record.get("recast_count", 0) + 1
    db.touch(record)
    recompute_resolution_tallies(resolution)
    db.touch(resolution)
    return success_object(serialize_row(record))


# ---------------------------------------------------------------------------
# Conflict disclosures
# ---------------------------------------------------------------------------


def create_disclosure(body, caller_role, caller_id):
    # Self-scoped ownership: a Director files only their own disclosure.
    if (
        caller_role == "Director"
        and body.get("director_id") is not None
        and body.get("director_id") != caller_id
    ):
        raise_err(ERR_FORBIDDEN_ROLE, "A Director may only file their own disclosure")

    director_id = req_string(body, "director_id")
    corporation_id = req_string(body, "corporation_id")
    related_party = req_string(body, "related_party")
    effective_from = req_datetime(body, "effective_from")
    effective_to = req_datetime(body, "effective_to")
    if effective_to < effective_from:
        raise_err(ERR_VALIDATION, "effective_to must be on or after effective_from")
    description = opt_string(body, "description")
    clearing_resolution_id = opt_string(body, "clearing_resolution_id")

    director = get_or_404(db.directors, director_id, "Director")
    get_or_404(db.corporations, corporation_id, "Corporation")
    if clearing_resolution_id is not None:
        get_or_404(db.resolutions, clearing_resolution_id, "Resolution")

    # Uniqueness/overlap tier: closed-interval overlap on (director,
    # related_party) among OPEN disclosures; touching endpoints conflict.
    for other in db.conflict_disclosures.values():
        if (
            other["director_id"] == director_id
            and other["related_party"] == related_party
            and other["status"] == "OPEN"
            and effective_from <= other["effective_to"]
            and effective_to >= other["effective_from"]
        ):
            raise_err(
                ERR_DISCLOSURE_WINDOW_CONFLICT,
                "Window overlaps an existing OPEN disclosure for this director/party",
            )

    # Cross-reference tier.
    if director["corporation_id"] != corporation_id:
        raise_err(
            ERR_CROSS_CORPORATION_REFERENCE,
            "Director belongs to a different corporation",
        )

    row = db.new_row()
    row.update(
        {
            "director_id": director_id,
            "corporation_id": corporation_id,
            "related_party": related_party,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "description": description,
            "status": "OPEN",
            "cleared_at": None,
            "clearing_resolution_id": clearing_resolution_id,
        }
    )
    db.conflict_disclosures[row["id"]] = row
    return success_object(serialize_row(row), status=201)


def list_disclosures(args):
    return list_response(
        db.conflict_disclosures.values(),
        [
            ("director_id", args.get("director_id")),
            ("corporation_id", args.get("corporation_id")),
            ("status", args.get("status")),
            ("related_party", args.get("related_party")),
            ("clearing_resolution_id", args.get("clearing_resolution_id")),
        ],
        args,
    )


def get_disclosure(disclosure_id):
    return success_object(
        serialize_row(get_or_404(db.conflict_disclosures, disclosure_id, "ConflictDisclosure"))
    )


def clear_disclosure(disclosure_id):
    disclosure = get_or_404(db.conflict_disclosures, disclosure_id, "ConflictDisclosure")
    if disclosure["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an OPEN disclosure can be cleared")
    clearing_id = disclosure.get("clearing_resolution_id")
    if clearing_id:
        resolution = db.resolutions.get(clearing_id)
        if resolution is None or resolution["status"] not in ("ADOPTED", "CONSENT_ADOPTED"):
            raise_err(
                ERR_CLEARING_RESOLUTION_NOT_ADOPTED,
                "The clearing resolution is not ADOPTED or CONSENT_ADOPTED",
            )
    disclosure["status"] = "CLEARED"
    disclosure["cleared_at"] = db.clock_now()
    db.touch(disclosure)
    return success_object(serialize_row(disclosure))


# ---------------------------------------------------------------------------
# Minutes and the minute book
# ---------------------------------------------------------------------------


def list_minutes(args):
    status_filter = args.get("status")
    sort_key = None
    if status_filter == "ENTERED_IN_BOOK":
        # The minute book view is ordered by book_seq_no, not created_at.
        sort_key = lambda r: (r.get("book_seq_no") or 0, r.get("_seq", 0))
    return list_response(
        db.minutes.values(),
        [
            ("meeting_id", args.get("meeting_id")),
            ("corporation_id", args.get("corporation_id")),
            ("status", args.get("status")),
        ],
        args,
        sort_key=sort_key,
    )


def get_minutes(minutes_id):
    return success_object(serialize_row(get_or_404(db.minutes, minutes_id, "Minutes")))


def circulate_minutes(minutes_id, body):
    content = req_string(body, "content")
    minutes_row = get_or_404(db.minutes, minutes_id, "Minutes")
    if minutes_row["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only DRAFT minutes can be circulated")
    minutes_row["content"] = content
    minutes_row["review_round"] = minutes_row.get("review_round", 0) + 1
    minutes_row["status"] = "CIRCULATED_FOR_REVIEW"
    db.touch(minutes_row)
    return success_object(serialize_row(minutes_row))


def _minutes_chair_check(minutes_row, caller_id):
    meeting = db.meetings.get(minutes_row["meeting_id"])
    if meeting is None or caller_id != meeting["chair_director_id"]:
        raise_err(
            ERR_FORBIDDEN_ROLE,
            "Only the chair of the linked meeting may decide its minutes",
        )
    return meeting


def approve_minutes(minutes_id, caller_id):
    minutes_row = get_or_404(db.minutes, minutes_id, "Minutes")
    meeting = _minutes_chair_check(minutes_row, caller_id)
    if minutes_row["status"] != "CIRCULATED_FOR_REVIEW":
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Only CIRCULATED_FOR_REVIEW minutes can be approved",
        )
    if meeting["status"] != "ADJOURNED":
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "The linked meeting must be ADJOURNED",
        )
    approved_at = db.clock_now()
    minutes_row["approved_at"] = approved_at
    bylaws_row = adopted_bylaws_for(minutes_row["corporation_id"])
    minutes_row["retention_until"] = (
        add_years(approved_at, bylaws_row["minute_retention_years"])
        if bylaws_row is not None
        else None
    )
    minutes_row["status"] = "APPROVED"
    db.touch(minutes_row)
    return success_object(serialize_row(minutes_row))


def reject_minutes(minutes_id, body, caller_id):
    reason = req_string(body, "reason")
    minutes_row = get_or_404(db.minutes, minutes_id, "Minutes")
    _minutes_chair_check(minutes_row, caller_id)
    if minutes_row["status"] != "CIRCULATED_FOR_REVIEW":
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Only CIRCULATED_FOR_REVIEW minutes can be rejected",
        )
    minutes_row["status"] = "REJECTED"
    minutes_row["rejection_reason"] = reason
    db.touch(minutes_row)
    return success_object(serialize_row(minutes_row))


def redraft_minutes(minutes_id, body):
    content = req_string(body, "content")
    minutes_row = get_or_404(db.minutes, minutes_id, "Minutes")
    if minutes_row["status"] != "REJECTED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only REJECTED minutes can be redrafted")
    minutes_row["content"] = content
    minutes_row["rejection_reason"] = None
    minutes_row["status"] = "DRAFT"
    db.touch(minutes_row)
    return success_object(serialize_row(minutes_row))


def enter_book(minutes_id):
    minutes_row = get_or_404(db.minutes, minutes_id, "Minutes")
    if minutes_row["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only APPROVED minutes can enter the book")
    existing = [
        m.get("book_seq_no") or 0
        for m in db.minutes.values()
        if m["corporation_id"] == minutes_row["corporation_id"]
        and m["status"] == "ENTERED_IN_BOOK"
    ]
    minutes_row["book_seq_no"] = max(existing, default=0) + 1
    minutes_row["content_hash"] = hashlib.sha256(
        minutes_row["content"].encode("utf-8")
    ).hexdigest()
    minutes_row["status"] = "ENTERED_IN_BOOK"
    db.touch(minutes_row)
    return success_object(serialize_row(minutes_row))


# ---------------------------------------------------------------------------
# Audit requests and reconstruction
# ---------------------------------------------------------------------------


def create_audit_request(body):
    corporation_id = req_string(body, "corporation_id")
    requested_by_label = req_string(body, "requested_by_label")
    scope_start = req_datetime(body, "scope_start")
    scope_end = req_datetime(body, "scope_end")
    if scope_end < scope_start:
        raise_err(ERR_VALIDATION, "scope_end must be on or after scope_start")
    get_or_404(db.corporations, corporation_id, "Corporation")

    row = db.new_row()
    row.update(
        {
            "corporation_id": corporation_id,
            "requested_by_label": requested_by_label,
            "scope_start": scope_start,
            "scope_end": scope_end,
            "status": "OPEN",
            "reconstruction_digest": None,
            "entry_count": None,
            "governance_approval_rate_pct": None,
            "failure_reason": None,
            "reconstruction_log": None,
        }
    )
    db.audit_requests[row["id"]] = row
    return success_object(serialize_row(row), status=201)


def list_audit_requests(args):
    return list_response(
        db.audit_requests.values(),
        [
            ("corporation_id", args.get("corporation_id")),
            ("status", args.get("status")),
        ],
        args,
    )


def get_audit_request(request_id):
    return success_object(
        serialize_row(get_or_404(db.audit_requests, request_id, "AuditRequest"))
    )


def _round_half_up_1(value):
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def run_reconstruction(request_id):
    request_row = get_or_404(db.audit_requests, request_id, "AuditRequest")
    if request_row["status"] not in ("OPEN", "FAILED"):
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Only an OPEN or FAILED audit request can be reconstructed",
        )
    request_row["status"] = "RECONSTRUCTING"

    corporation_id = request_row["corporation_id"]
    scope_start = request_row["scope_start"]
    scope_end = request_row["scope_end"]

    def in_scope(moment):
        return moment is not None and scope_start <= moment <= scope_end

    # Gap check first: any meeting inside scope whose minutes are PURGED
    # collapses the request to FAILED.
    meetings_in_scope = [
        m
        for m in db.meetings.values()
        if m["corporation_id"] == corporation_id and in_scope(m["created_at"])
    ]
    minutes_by_meeting = {m["meeting_id"]: m for m in db.minutes.values()}
    purged_gap = any(
        minutes_by_meeting.get(meeting["id"]) is not None
        and minutes_by_meeting[meeting["id"]]["status"] == "PURGED"
        for meeting in meetings_in_scope
    )
    if purged_gap:
        request_row["status"] = "FAILED"
        request_row["failure_reason"] = "Purged minutes inside the reconstruction scope"
        request_row["reconstruction_log"] = None
        request_row["reconstruction_digest"] = None
        request_row["entry_count"] = None
        request_row["governance_approval_rate_pct"] = None
        db.touch(request_row)
        return success_object(serialize_row(request_row))

    # Projection: meetings by created_at, closed resolutions (ADOPTED or
    # REJECTED) by closed_at, approved minutes by approved_at.
    rank = {"MEETING": 1, "RESOLUTION": 2, "MINUTES": 3}
    sources = []
    for meeting in meetings_in_scope:
        sources.append(
            (meeting["created_at"], rank["MEETING"], meeting["created_at"], meeting["_seq"],
             "MEETING", meeting["id"], meeting["created_at"])
        )
    closed_resolutions = [
        r
        for r in db.resolutions.values()
        if r["corporation_id"] == corporation_id
        and r["status"] in ("ADOPTED", "REJECTED")
        and in_scope(r["closed_at"])
    ]
    for resolution in closed_resolutions:
        sources.append(
            (resolution["closed_at"], rank["RESOLUTION"], resolution["created_at"], resolution["_seq"],
             "RESOLUTION", resolution["id"], resolution["closed_at"])
        )
    for minutes_row in db.minutes.values():
        if (
            minutes_row["corporation_id"] == corporation_id
            and minutes_row["approved_at"] is not None
            and in_scope(minutes_row["approved_at"])
        ):
            sources.append(
                (minutes_row["approved_at"], rank["MINUTES"], minutes_row["created_at"], minutes_row["_seq"],
                 "MINUTES", minutes_row["id"], minutes_row["approved_at"])
            )
    sources.sort(key=lambda s: (s[0], s[1], s[2], s[3]))

    log_entries = []
    digest_lines = []
    for index, source in enumerate(sources, start=1):
        occurred_iso = iso_ms(source[6])
        entry = {
            "seq": index,
            "source_type": source[4],
            "source_id": source[5],
            "occurred_at": occurred_iso,
        }
        log_entries.append(entry)
        digest_lines.append(
            "%d|%s|%s|%s" % (index, source[4], source[5], occurred_iso)
        )
    digest = hashlib.sha256("\n".join(digest_lines).encode("utf-8")).hexdigest()

    # Governance approval rate: per-resolution rounded percentages, averaged,
    # rounded again. Resolutions with a zero eligible pool are skipped.
    percentages = []
    for resolution in closed_resolutions:
        pool = resolution.get("_eligible_pool_at_close")
        if not pool:
            continue
        pct = _round_half_up_1(
            Decimal(100 * resolution["for_count"]) / Decimal(pool)
        )
        percentages.append(pct)
    if percentages:
        mean = sum(percentages) / Decimal(len(percentages))
        approval_rate = float(_round_half_up_1(mean))
    else:
        approval_rate = None

    request_row["status"] = "COMPLETED"
    request_row["reconstruction_log"] = log_entries
    request_row["entry_count"] = len(log_entries)
    request_row["reconstruction_digest"] = digest
    request_row["governance_approval_rate_pct"] = approval_rate
    request_row["failure_reason"] = None
    db.touch(request_row)
    return success_object(serialize_row(request_row))


# ---------------------------------------------------------------------------
# Governance checkpoint
# ---------------------------------------------------------------------------


def run_checkpoint(corporation_id):
    get_or_404(db.corporations, corporation_id, "Corporation")
    now = db.clock_now()

    expired_director_ids = []
    for director in list(db.directors.values()):
        if (
            director["corporation_id"] == corporation_id
            and director["status"] == "ACTIVE"
            and now > director["term_end"]
        ):
            director["status"] = "TERM_EXPIRED"
            db.touch(director)
            director_departure_cascade(director, "DIRECTOR_TERM_EXPIRED")
            expired_director_ids.append(director["id"])

    adopted_resolution_ids = []
    lapsed_resolution_ids = []
    for resolution in list(db.resolutions.values()):
        if (
            resolution["corporation_id"] == corporation_id
            and resolution["status"] == "CIRCULATING"
        ):
            if _consent_for_count(resolution) >= (resolution["consent_required_count"] or 0):
                resolution["status"] = "CONSENT_ADOPTED"
                resolution["closed_at"] = now
                db.touch(resolution)
                adopted_resolution_ids.append(resolution["id"])
            elif now > resolution["consent_deadline_at"]:
                resolution["status"] = "CONSENT_LAPSED"
                resolution["closed_at"] = now
                db.touch(resolution)
                lapsed_resolution_ids.append(resolution["id"])

    purged_minutes_ids = []
    for minutes_row in list(db.minutes.values()):
        if (
            minutes_row["corporation_id"] == corporation_id
            and minutes_row["status"] == "ENTERED_IN_BOOK"
            and minutes_row["retention_until"] is not None
            and now > minutes_row["retention_until"]
        ):
            minutes_row["status"] = "PURGED"
            minutes_row["content"] = ""  # hash retained for tamper evidence
            db.touch(minutes_row)
            purged_minutes_ids.append(minutes_row["id"])

    return success_object(
        {
            "expired_director_ids": expired_director_ids,
            "lapsed_resolution_ids": lapsed_resolution_ids,
            "adopted_resolution_ids": adopted_resolution_ids,
            "purged_minutes_ids": purged_minutes_ids,
        }
    )
