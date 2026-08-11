"""Meeting-lifecycle services: meetings, notices, attendance, agenda items,
board packages, and access-controlled package documents."""

from datetime import timedelta

import db
from errors import (
    ERR_AGENDA_LOCKED,
    ERR_CONFLICT_RECUSAL_REQUIRED,
    ERR_CROSS_CORPORATION_REFERENCE,
    ERR_DIRECTOR_NOT_ACTIVE,
    ERR_DUPLICATE_ATTENDANCE,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MEETING_NOT_YET,
    ERR_MEETING_TIME_CONFLICT,
    ERR_NO_ACTIVE_DIRECTORS,
    ERR_NO_ADOPTED_BYLAWS,
    ERR_NOT_FOUND,
    ERR_PACKAGE_ACCESS_DENIED,
    ERR_PACKAGE_DISTRIBUTION_LATE,
    ERR_PACKAGE_EMPTY,
    ERR_PROXY_HOLDER_INELIGIBLE,
    ERR_SCHEDULED_START_IN_PAST,
    ERR_STALE_MEETING_VERSION,
    ERR_UNRESOLVED_VOTES_EXIST,
    ERR_VALIDATION,
    raise_err,
)
from response import list_response, serialize_row, success_object
from services_core import (
    adopted_bylaws_for,
    active_directors_of,
    get_or_404,
    revert_resolution_to_draft,
)
from util import (
    SECONDS_PER_DAY,
    check_range_int,
    opt_string,
    req_datetime,
    req_enum,
    req_int,
    req_string,
)

PRESENT_MODES = ("IN_PERSON", "REMOTE", "PROXY")


# ---------------------------------------------------------------------------
# Meetings
# ---------------------------------------------------------------------------


def _meeting_end(meeting):
    return meeting["scheduled_start"] + timedelta(minutes=meeting["duration_minutes"])


def _calendar_overlap_check(corporation_id, start, duration_minutes, exclude_meeting_id=None):
    """Half-open window conflict: conflict iff W.start < other.end and
    W.end > other.start; CANCELLED meetings never conflict; back-to-back
    adjacency is allowed."""
    end = start + timedelta(minutes=duration_minutes)
    for other in db.meetings.values():
        if other["corporation_id"] != corporation_id:
            continue
        if other["status"] == "CANCELLED":
            continue
        if exclude_meeting_id is not None and other["id"] == exclude_meeting_id:
            continue
        other_end = _meeting_end(other)
        if start < other_end and end > other["scheduled_start"]:
            raise_err(
                ERR_MEETING_TIME_CONFLICT,
                "Meeting window overlaps meeting %s" % other["id"],
            )


def create_meeting(body):
    corporation_id = req_string(body, "corporation_id")
    meeting_type = req_enum(body, "meeting_type", ("REGULAR", "SPECIAL", "ANNUAL"))
    scheduled_start = req_datetime(body, "scheduled_start")
    duration_minutes = check_range_int(
        req_int(body, "duration_minutes"), "duration_minutes", minimum=1
    )
    location_or_medium = req_string(body, "location_or_medium")
    chair_director_id = req_string(body, "chair_director_id")

    get_or_404(db.corporations, corporation_id, "Corporation")
    chair = get_or_404(db.directors, chair_director_id, "Director")

    # Clock-relative temporal tier.
    if scheduled_start <= db.clock_now():
        raise_err(ERR_SCHEDULED_START_IN_PAST, "scheduled_start must be strictly in the future")

    # Uniqueness / overlap tier.
    _calendar_overlap_check(corporation_id, scheduled_start, duration_minutes)

    # Cross-reference / lifecycle tier.
    if chair["corporation_id"] != corporation_id:
        raise_err(
            ERR_CROSS_CORPORATION_REFERENCE,
            "Chair director belongs to a different corporation",
        )
    if chair["status"] != "ACTIVE":
        raise_err(ERR_DIRECTOR_NOT_ACTIVE, "Chair director is not ACTIVE")

    row = db.new_row()
    row.update(
        {
            "corporation_id": corporation_id,
            "meeting_type": meeting_type,
            "scheduled_start": scheduled_start,
            "duration_minutes": duration_minutes,
            "location_or_medium": location_or_medium,
            "chair_director_id": chair_director_id,
            "status": "SCHEDULED",
            "convened_at": None,
            "bylaws_id_at_notice": None,
            "quorum_required_count": None,
            "quorum_present_snapshot": None,
            "quorum_met": None,
        }
    )
    db.meetings[row["id"]] = row
    return success_object(serialize_row(row), status=201)


def list_meetings(args):
    return list_response(
        db.meetings.values(),
        [
            ("corporation_id", args.get("corporation_id")),
            ("status", args.get("status")),
            ("chair_director_id", args.get("chair_director_id")),
            ("bylaws_id_at_notice", args.get("bylaws_id_at_notice")),
        ],
        args,
    )


def get_meeting(meeting_id):
    return success_object(serialize_row(get_or_404(db.meetings, meeting_id, "Meeting")))


def send_notices(meeting_id):
    meeting = get_or_404(db.meetings, meeting_id, "Meeting")
    if meeting["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Notices can only be sent from SCHEDULED")
    bylaws_row = adopted_bylaws_for(meeting["corporation_id"])
    if bylaws_row is None:
        raise_err(ERR_NO_ADOPTED_BYLAWS, "An ADOPTED bylaws is required to send notices")
    actives = active_directors_of(meeting["corporation_id"])
    if not actives:
        raise_err(ERR_NO_ACTIVE_DIRECTORS, "At least one ACTIVE director is required")

    required_days = (
        bylaws_row["notice_days_special"]
        if meeting["meeting_type"] == "SPECIAL"
        else bylaws_row["notice_days_regular"]
    )
    sent_at = db.clock_now()
    deadline_at = meeting["scheduled_start"] - timedelta(days=required_days)
    for director in actives:
        notice = db.new_row()
        notice.update(
            {
                "meeting_id": meeting["id"],
                "director_id": director["id"],
                "sent_at": sent_at,
                "required_notice_days": required_days,
                "deadline_at": deadline_at,
                "is_timely": sent_at <= deadline_at,
                "status": "SENT",
                "waived_at": None,
            }
        )
        db.meeting_notices[notice["id"]] = notice

    meeting["bylaws_id_at_notice"] = bylaws_row["id"]
    meeting["status"] = "NOTICED"
    db.touch(meeting)
    return success_object(serialize_row(meeting))


def reschedule_meeting(meeting_id, body):
    scheduled_start = req_datetime(body, "scheduled_start")
    duration_minutes = check_range_int(
        req_int(body, "duration_minutes"), "duration_minutes", minimum=1
    )
    expected_meeting_version = req_int(body, "expected_meeting_version")

    meeting = get_or_404(db.meetings, meeting_id, "Meeting")
    if meeting["status"] not in ("SCHEDULED", "NOTICED"):
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Only a SCHEDULED or NOTICED meeting can be rescheduled",
        )
    if expected_meeting_version != meeting["version"]:
        raise_err(
            ERR_STALE_MEETING_VERSION,
            "expected_meeting_version %s does not match meeting version %s"
            % (expected_meeting_version, meeting["version"]),
        )
    if scheduled_start <= db.clock_now():
        raise_err(ERR_SCHEDULED_START_IN_PAST, "scheduled_start must be strictly in the future")
    _calendar_overlap_check(
        meeting["corporation_id"],
        scheduled_start,
        duration_minutes,
        exclude_meeting_id=meeting["id"],
    )

    meeting["scheduled_start"] = scheduled_start
    meeting["duration_minutes"] = duration_minutes
    meeting["status"] = "SCHEDULED"
    # Issued notices are deleted; notice must be re-sent against the new date.
    stale_notice_ids = [
        n["id"] for n in db.meeting_notices.values() if n["meeting_id"] == meeting["id"]
    ]
    for notice_id in stale_notice_ids:
        del db.meeting_notices[notice_id]
    db.touch(meeting)
    return success_object(serialize_row(meeting))


def cancel_meeting(meeting_id):
    meeting = get_or_404(db.meetings, meeting_id, "Meeting")
    if meeting["status"] not in ("SCHEDULED", "NOTICED", "IN_SESSION"):
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Only a SCHEDULED, NOTICED or IN_SESSION meeting can be cancelled",
        )

    # Agenda cascade: every PROPOSED/INCLUDED item drops; a dropped item that
    # links a TABLED or VOTE_OPEN resolution sends it back to DRAFT and voids
    # its ACTIVE ballots.
    for item in db.agenda_items.values():
        if item["meeting_id"] == meeting["id"] and item["status"] in ("PROPOSED", "INCLUDED"):
            item["status"] = "DROPPED"
            db.touch(item)
            resolution_id = item.get("resolution_id")
            if resolution_id:
                resolution = db.resolutions.get(resolution_id)
                if resolution is not None:
                    revert_resolution_to_draft(resolution)

    # Package cascade: ASSEMBLING/SEALED withdraw; DISTRIBUTED remains.
    for package in db.board_packages.values():
        if package["meeting_id"] == meeting["id"] and package["status"] in ("ASSEMBLING", "SEALED"):
            package["status"] = "WITHDRAWN"
            db.touch(package)

    meeting["status"] = "CANCELLED"
    db.touch(meeting)
    return success_object(serialize_row(meeting))


def convene_meeting(meeting_id, caller_id):
    meeting = get_or_404(db.meetings, meeting_id, "Meeting")
    if caller_id != meeting["chair_director_id"]:
        raise_err(ERR_FORBIDDEN_ROLE, "Only the meeting's chair may convene it")
    if meeting["status"] != "NOTICED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a NOTICED meeting can be convened")
    if db.clock_now() < meeting["scheduled_start"]:
        raise_err(ERR_MEETING_NOT_YET, "The meeting cannot be convened before scheduled_start")

    bylaws_row = db.bylaws.get(meeting["bylaws_id_at_notice"])
    active_count = len(active_directors_of(meeting["corporation_id"]))
    percent = bylaws_row["quorum_percent"]
    fixed = bylaws_row["quorum_fixed_count"]
    percent_need = (percent * active_count + 99) // 100  # ceil before max
    required = max(fixed, percent_need)
    present = sum(
        1
        for record in db.attendance_records.values()
        if record["meeting_id"] == meeting["id"]
        and record["attendance_mode"] in PRESENT_MODES
    )

    meeting["convened_at"] = db.clock_now()
    meeting["quorum_required_count"] = required
    meeting["quorum_present_snapshot"] = present
    meeting["quorum_met"] = present >= required
    meeting["status"] = "IN_SESSION"
    db.touch(meeting)
    return success_object(serialize_row(meeting))


def adjourn_meeting(meeting_id, caller_id):
    meeting = get_or_404(db.meetings, meeting_id, "Meeting")
    if caller_id != meeting["chair_director_id"]:
        raise_err(ERR_FORBIDDEN_ROLE, "Only the meeting's chair may adjourn it")
    if meeting["status"] != "IN_SESSION":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an IN_SESSION meeting can be adjourned")
    for resolution in db.resolutions.values():
        if resolution["meeting_id"] == meeting["id"] and resolution["status"] == "VOTE_OPEN":
            raise_err(
                ERR_UNRESOLVED_VOTES_EXIST,
                "Resolution %s is still VOTE_OPEN" % resolution["id"],
            )

    meeting["status"] = "ADJOURNED"
    db.touch(meeting)

    # Exactly one Minutes per meeting, auto-created in DRAFT with empty content.
    minutes_row = db.new_row()
    minutes_row.update(
        {
            "meeting_id": meeting["id"],
            "corporation_id": meeting["corporation_id"],
            "content": "",
            "status": "DRAFT",
            "review_round": 0,
            "rejection_reason": None,
            "approved_at": None,
            "retention_until": None,
            "book_seq_no": None,
            "content_hash": None,
        }
    )
    db.minutes[minutes_row["id"]] = minutes_row
    return success_object(serialize_row(meeting))


# ---------------------------------------------------------------------------
# Meeting notices
# ---------------------------------------------------------------------------


def _refresh_notice(notice):
    """is_timely is re-derived on every read: a waived notice is satisfied
    regardless; otherwise dispatch exactly at the deadline counts as timely."""
    notice["is_timely"] = (notice["status"] == "WAIVED") or (
        notice["sent_at"] <= notice["deadline_at"]
    )
    return notice


def list_notices(args):
    for notice in db.meeting_notices.values():
        _refresh_notice(notice)
    return list_response(
        db.meeting_notices.values(),
        [
            ("meeting_id", args.get("meeting_id")),
            ("director_id", args.get("director_id")),
            ("status", args.get("status")),
        ],
        args,
    )


def get_notice(notice_id):
    notice = get_or_404(db.meeting_notices, notice_id, "MeetingNotice")
    return success_object(serialize_row(_refresh_notice(notice)))


def waive_notice(notice_id, caller_id):
    notice = get_or_404(db.meeting_notices, notice_id, "MeetingNotice")
    if caller_id != notice["director_id"]:
        raise_err(ERR_FORBIDDEN_ROLE, "A Director may only waive their own notice")
    if notice["status"] != "SENT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a SENT notice can be waived")
    notice["status"] = "WAIVED"
    notice["waived_at"] = db.clock_now()
    db.touch(notice)
    return success_object(serialize_row(_refresh_notice(notice)))


# ---------------------------------------------------------------------------
# Attendance records
# ---------------------------------------------------------------------------


def create_attendance(body):
    meeting_id = req_string(body, "meeting_id")
    director_id = req_string(body, "director_id")
    attendance_mode = req_enum(
        body, "attendance_mode", ("IN_PERSON", "REMOTE", "PROXY", "ABSENT")
    )
    proxy_holder_director_id = opt_string(body, "proxy_holder_director_id")

    meeting = get_or_404(db.meetings, meeting_id, "Meeting")
    director = get_or_404(db.directors, director_id, "Director")
    proxy_holder = None
    if proxy_holder_director_id is not None:
        proxy_holder = get_or_404(db.directors, proxy_holder_director_id, "Director")

    if meeting["status"] not in ("NOTICED", "IN_SESSION"):
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Attendance is recorded for a NOTICED or IN_SESSION meeting",
        )

    # Uniqueness tier: one record per (meeting, director).
    for record in db.attendance_records.values():
        if record["meeting_id"] == meeting["id"] and record["director_id"] == director_id:
            raise_err(
                ERR_DUPLICATE_ATTENDANCE,
                "An attendance record already exists for this (meeting, director)",
            )

    # Cross-reference / lifecycle tier.
    if director["corporation_id"] != meeting["corporation_id"]:
        raise_err(
            ERR_CROSS_CORPORATION_REFERENCE,
            "Director belongs to a different corporation than the meeting",
        )
    if attendance_mode == "PROXY":
        if (
            proxy_holder is None
            or proxy_holder_director_id == director_id
            or proxy_holder["status"] != "ACTIVE"
            or proxy_holder["corporation_id"] != meeting["corporation_id"]
        ):
            raise_err(
                ERR_PROXY_HOLDER_INELIGIBLE,
                "PROXY mode requires an ACTIVE proxy holder, other than the attendee, "
                "of the same corporation",
            )

    row = db.new_row()
    row.update(
        {
            "meeting_id": meeting_id,
            "director_id": director_id,
            "attendance_mode": attendance_mode,
            "proxy_holder_director_id": proxy_holder_director_id,
            "recorded_at": db.clock_now(),
        }
    )
    db.attendance_records[row["id"]] = row
    return success_object(serialize_row(row), status=201)


def list_attendance(args):
    return list_response(
        db.attendance_records.values(),
        [
            ("meeting_id", args.get("meeting_id")),
            ("director_id", args.get("director_id")),
            ("proxy_holder_director_id", args.get("proxy_holder_director_id")),
        ],
        args,
    )


def get_attendance(record_id):
    return success_object(
        serialize_row(get_or_404(db.attendance_records, record_id, "AttendanceRecord"))
    )


# ---------------------------------------------------------------------------
# Agenda items
# ---------------------------------------------------------------------------


def create_agenda_item(body):
    meeting_id = req_string(body, "meeting_id")
    title = req_string(body, "title")
    order_index = check_range_int(req_int(body, "order_index"), "order_index", minimum=1)
    proposed_by_director_id = req_string(body, "proposed_by_director_id")
    resolution_id = opt_string(body, "resolution_id")

    meeting = get_or_404(db.meetings, meeting_id, "Meeting")
    proposer = get_or_404(db.directors, proposed_by_director_id, "Director")
    resolution = None
    if resolution_id is not None:
        resolution = get_or_404(db.resolutions, resolution_id, "Resolution")

    if meeting["status"] not in ("SCHEDULED", "NOTICED"):
        raise_err(ERR_AGENDA_LOCKED, "The agenda is locked once the meeting leaves SCHEDULED/NOTICED")

    if proposer["corporation_id"] != meeting["corporation_id"]:
        raise_err(
            ERR_CROSS_CORPORATION_REFERENCE,
            "Proposing director belongs to a different corporation",
        )
    if resolution is not None and resolution["corporation_id"] != meeting["corporation_id"]:
        raise_err(
            ERR_CROSS_CORPORATION_REFERENCE,
            "Linked resolution belongs to a different corporation",
        )

    row = db.new_row()
    row.update(
        {
            "meeting_id": meeting_id,
            "title": title,
            "order_index": order_index,
            "proposed_by_director_id": proposed_by_director_id,
            "resolution_id": resolution_id,
            "status": "PROPOSED",
        }
    )
    db.agenda_items[row["id"]] = row
    return success_object(serialize_row(row), status=201)


def list_agenda_items(args):
    return list_response(
        db.agenda_items.values(),
        [
            ("meeting_id", args.get("meeting_id")),
            ("resolution_id", args.get("resolution_id")),
            ("proposed_by_director_id", args.get("proposed_by_director_id")),
            ("status", args.get("status")),
        ],
        args,
    )


def get_agenda_item(item_id):
    return success_object(serialize_row(get_or_404(db.agenda_items, item_id, "AgendaItem")))


def include_agenda_item(item_id):
    item = get_or_404(db.agenda_items, item_id, "AgendaItem")
    if item["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a PROPOSED item can be included")
    meeting = get_or_404(db.meetings, item["meeting_id"], "Meeting")
    if meeting["status"] not in ("SCHEDULED", "NOTICED"):
        raise_err(ERR_AGENDA_LOCKED, "The agenda is locked once the meeting leaves SCHEDULED/NOTICED")
    item["status"] = "INCLUDED"
    db.touch(item)
    return success_object(serialize_row(item))


def drop_agenda_item(item_id):
    item = get_or_404(db.agenda_items, item_id, "AgendaItem")
    if item["status"] not in ("PROPOSED", "INCLUDED"):
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a PROPOSED or INCLUDED item can be dropped")
    item["status"] = "DROPPED"
    db.touch(item)
    resolution_id = item.get("resolution_id")
    if resolution_id:
        resolution = db.resolutions.get(resolution_id)
        if resolution is not None:
            revert_resolution_to_draft(resolution)
    return success_object(serialize_row(item))


# ---------------------------------------------------------------------------
# Board packages
# ---------------------------------------------------------------------------


def create_board_package(body):
    meeting_id = req_string(body, "meeting_id")
    meeting = get_or_404(db.meetings, meeting_id, "Meeting")
    if meeting["status"] not in ("SCHEDULED", "NOTICED"):
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Packages are created for a SCHEDULED or NOTICED meeting",
        )
    row = db.new_row()
    row.update(
        {
            "meeting_id": meeting_id,
            "seal_count": 0,
            "document_count": 0,
            "status": "ASSEMBLING",
            "sealed_at": None,
            "distributed_at": None,
        }
    )
    db.board_packages[row["id"]] = row
    return success_object(serialize_row(row), status=201)


def list_board_packages(args):
    return list_response(
        db.board_packages.values(),
        [("meeting_id", args.get("meeting_id")), ("status", args.get("status"))],
        args,
    )


def get_board_package(package_id):
    return success_object(
        serialize_row(get_or_404(db.board_packages, package_id, "BoardPackage"))
    )


def seal_package(package_id):
    package = get_or_404(db.board_packages, package_id, "BoardPackage")
    if package["status"] != "ASSEMBLING":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an ASSEMBLING package can be sealed")
    if package["document_count"] < 1:
        raise_err(ERR_PACKAGE_EMPTY, "A package must hold at least one document to seal")
    meeting = get_or_404(db.meetings, package["meeting_id"], "Meeting")
    if meeting["status"] not in ("SCHEDULED", "NOTICED"):
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "The package's meeting must be SCHEDULED or NOTICED to seal",
        )
    package["status"] = "SEALED"
    package["sealed_at"] = db.clock_now()
    package["seal_count"] = package.get("seal_count", 0) + 1
    db.touch(package)
    return success_object(serialize_row(package))


def unseal_package(package_id):
    package = get_or_404(db.board_packages, package_id, "BoardPackage")
    if package["status"] != "SEALED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a SEALED package can be unsealed")
    package["status"] = "ASSEMBLING"
    db.touch(package)
    return success_object(serialize_row(package))


def distribute_package(package_id):
    package = get_or_404(db.board_packages, package_id, "BoardPackage")
    if package["status"] != "SEALED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a SEALED package can be distributed")
    meeting = get_or_404(db.meetings, package["meeting_id"], "Meeting")
    # Bylaws source: the set pinned at notice when present, else the
    # corporation's currently adopted set.
    bylaws_row = None
    if meeting.get("bylaws_id_at_notice"):
        bylaws_row = db.bylaws.get(meeting["bylaws_id_at_notice"])
    if bylaws_row is None:
        bylaws_row = adopted_bylaws_for(meeting["corporation_id"])
    if bylaws_row is None:
        raise_err(ERR_NO_ADOPTED_BYLAWS, "No bylaws available for the lead window check")
    deadline = meeting["scheduled_start"] - timedelta(days=bylaws_row["package_lead_days"])
    if db.clock_now() > deadline:
        raise_err(
            ERR_PACKAGE_DISTRIBUTION_LATE,
            "Distribution is past the package lead window",
        )
    package["status"] = "DISTRIBUTED"
    package["distributed_at"] = db.clock_now()
    db.touch(package)
    return success_object(serialize_row(package))


# ---------------------------------------------------------------------------
# Package documents (tier-gated reads)
# ---------------------------------------------------------------------------


def create_package_document(body):
    package_id = req_string(body, "package_id")
    title = req_string(body, "title")
    content_ref = req_string(body, "content_ref")
    confidentiality_tier = req_enum(
        body, "confidentiality_tier", ("GENERAL", "CONFIDENTIAL", "RESTRICTED")
    )
    package = get_or_404(db.board_packages, package_id, "BoardPackage")
    if package["status"] != "ASSEMBLING":
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Documents can only be added to an ASSEMBLING package",
        )
    row = db.new_row()
    row.update(
        {
            "package_id": package_id,
            "title": title,
            "content_ref": content_ref,
            "confidentiality_tier": confidentiality_tier,
        }
    )
    db.package_documents[row["id"]] = row
    package["document_count"] = package.get("document_count", 0) + 1
    db.touch(package)
    return success_object(serialize_row(row), status=201)


def _doc_visible_to(document, caller_role, caller_id):
    """GENERAL: every director; CONFIDENTIAL: ACTIVE directors only;
    RESTRICTED: ACTIVE directors with independence_status INDEPENDENT.
    CorporateSecretary / ExternalAuditor see everything."""
    if caller_role in ("CorporateSecretary", "ExternalAuditor"):
        return True
    tier = document["confidentiality_tier"]
    if tier == "GENERAL":
        return True
    director = db.directors.get(caller_id)
    if director is None or director["status"] != "ACTIVE":
        return False
    if tier == "CONFIDENTIAL":
        return True
    return director["independence_status"] == "INDEPENDENT"


def list_package_documents(args, caller_role, caller_id):
    rows = list(db.package_documents.values())
    if caller_role in ("Director", "BoardChair"):
        rows = [r for r in rows if _doc_visible_to(r, caller_role, caller_id)]
    return list_response(
        rows,
        [
            ("package_id", args.get("package_id")),
            ("confidentiality_tier", args.get("confidentiality_tier")),
        ],
        args,
    )


def get_package_document(document_id, caller_role, caller_id):
    document = get_or_404(db.package_documents, document_id, "PackageDocument")
    if not _doc_visible_to(document, caller_role, caller_id):
        raise_err(
            ERR_PACKAGE_ACCESS_DENIED,
            "Caller lacks the clearance tier for this document",
        )
    return success_object(serialize_row(document))
