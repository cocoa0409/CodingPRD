"""Routes: PreservationNotice, CollectionScope, EvidenceItem, WitnessInterview."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import resp
import services as svc
import validate as v
from transitions import parse_to_status, require_actor

bp = Blueprint("fieldwork", __name__)


# ---------------------------------------------------------------------------
# PreservationNotice
# ---------------------------------------------------------------------------
@bp.post("/api/cases/<rid>/preservation-notices")
def create_notice(rid):
    case = svc.get_or_404(db.cases, rid, "Case")
    p = v.payload()
    custodian_ref = v.need_str(p, "custodian_ref")
    scope = v.need_enum(p, "scope", svc.NOTICE_SCOPES)
    is_regulator_ordered = v.need_bool(p, "is_regulator_ordered")

    if case["status"] not in ("PLANNING", "FIELDWORK", "FINDINGS", "DISPOSITION", "REMEDIATION"):
        errors.invalid_state(
            "Preservation notices require the case in PLANNING or a later non-terminal, non-CLOSED status"
        )

    notice = svc.new_row(
        {
            "case_id": case["id"],
            "custodian_ref": custodian_ref,
            "scope": scope,
            "is_regulator_ordered": is_regulator_ordered,
            "issued_at": db.clock_now(),
            "acknowledged_at": None,
            "status": "ISSUED",
        }
    )
    db.notices[notice["id"]] = notice
    svc.recompute_case_derived(case)
    return resp.ok(svc.dump(notice), status=201)


@bp.get("/api/preservation-notices")
def list_notices():
    q = request.args
    rows = list(db.notices.values())
    for param in ("case_id", "custodian_ref", "status"):
        val = q.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    limit, offset = v.parse_pagination(q)
    rows = svc.sort_rows(rows)
    page, total = svc.paginate(rows, limit, offset)
    return resp.ok_list([svc.dump(r) for r in page], limit, offset, total)


@bp.get("/api/preservation-notices/<rid>")
def get_notice(rid):
    return resp.ok(svc.dump(svc.get_or_404(db.notices, rid, "PreservationNotice")))


@bp.post("/api/preservation-notices/<rid>/transition")
def transition_notice(rid):
    notice = svc.get_or_404(db.notices, rid, "PreservationNotice")
    p = v.payload()
    to = parse_to_status(p, svc.NOTICE_STATUSES)
    src = notice["status"]
    case = svc.get_or_404(db.cases, notice["case_id"], "Case")

    if src == "ISSUED" and to == "ACKNOWLEDGED":
        notice["status"] = "ACKNOWLEDGED"
        notice["acknowledged_at"] = db.clock_now()
    elif src in ("ISSUED", "ACKNOWLEDGED") and to == "RELEASED":
        if notice["is_regulator_ordered"] and case["status"] != "CLOSED":
            errors.business(
                "ERR_ORDERED_NOTICE_RESTRICTION",
                "Regulator-ordered notices may be released only once the case is CLOSED",
            )
        notice["status"] = "RELEASED"
        # cascade hop 1: dependent scopes of the same custodian -> WITHDRAWN
        for s in db.scopes.values():
            if (
                s["case_id"] == case["id"]
                and s["custodian_ref"] == notice["custodian_ref"]
                and s["status"] in svc.OPEN_SCOPE_STATUSES
            ):
                s["status"] = "WITHDRAWN"
                svc.touch(s)
    else:
        errors.invalid_state(f"PreservationNotice cannot transition {src} -> {to}")

    svc.touch(notice)
    # hop 2: ratio recompute (RELEASED excluded from both terms)
    svc.recompute_case_derived(case)
    return resp.ok(svc.dump(notice))


# ---------------------------------------------------------------------------
# CollectionScope
# ---------------------------------------------------------------------------
@bp.post("/api/cases/<rid>/collection-scopes")
def create_scope(rid):
    case = svc.get_or_404(db.cases, rid, "Case")
    p = v.payload()
    custodian_ref = v.need_str(p, "custodian_ref")
    data_source = v.need_enum(p, "data_source", svc.DATA_SOURCES)
    planned_start = v.need_dt(p, "planned_start")
    planned_end = v.need_dt(p, "planned_end")
    notice_id = p.get("preservation_notice_id", None)

    # body-referenced id existence (priority 4)
    if notice_id is not None:
        svc.get_or_404(db.notices, notice_id, "PreservationNotice")

    # state gate (priority 6)
    if case["status"] != "FIELDWORK":
        errors.invalid_state("Collection scopes require the case in FIELDWORK")

    # overlap constraint (priority 8): closed-interval, touching conflicts
    for s in db.scopes.values():
        if (
            s["case_id"] == case["id"]
            and s["custodian_ref"] == custodian_ref
            and s["data_source"] == data_source
            and s["status"] in svc.OPEN_SCOPE_STATUSES
            and planned_start <= s["planned_end"]
            and s["planned_start"] <= planned_end
        ):
            errors.business(
                "ERR_SCOPE_OVERLAP",
                "An open scope for this custodian/data_source overlaps the planned window",
            )

    # referential coverage (priority 9)
    covering = svc.covering_notices(
        case["id"], custodian_ref, data_source, {"ISSUED", "ACKNOWLEDGED"}
    )
    if not covering:
        errors.business(
            "ERR_CUSTODIAN_NOT_PRESERVED",
            "No ISSUED/ACKNOWLEDGED preservation notice covers this custodian and data source",
        )

    # window order (priority 10): closed interval, equal allowed
    if planned_end < planned_start:
        errors.validation("planned_end must be greater than or equal to planned_start")

    scope = svc.new_row(
        {
            "case_id": case["id"],
            "preservation_notice_id": notice_id,
            "custodian_ref": custodian_ref,
            "data_source": data_source,
            "planned_start": planned_start,
            "planned_end": planned_end,
            "collected_item_count": 0,
            "collected_bytes": 0,
            "review_effort_minutes": None,
            "status": "PROPOSED",
        }
    )
    db.scopes[scope["id"]] = scope
    return resp.ok(svc.dump(scope), status=201)


@bp.get("/api/collection-scopes")
def list_scopes():
    q = request.args
    rows = list(db.scopes.values())
    for param in ("case_id", "preservation_notice_id", "custodian_ref", "data_source", "status"):
        val = q.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    limit, offset = v.parse_pagination(q)
    rows = svc.sort_rows(rows)
    page, total = svc.paginate(rows, limit, offset)
    return resp.ok_list([svc.dump(r) for r in page], limit, offset, total)


@bp.get("/api/collection-scopes/<rid>")
def get_scope(rid):
    return resp.ok(svc.dump(svc.get_or_404(db.scopes, rid, "CollectionScope")))


SCOPE_ACTORS = {
    "APPROVED": "InvestigationsManager",
    "IN_PROGRESS": "Investigator",
    "COLLECTED": "Investigator",
    # WITHDRAWN: Investigator or InvestigationsManager
}


@bp.post("/api/collection-scopes/<rid>/transition")
def transition_scope(rid):
    scope = svc.get_or_404(db.scopes, rid, "CollectionScope")
    p = v.payload()
    to = parse_to_status(p, svc.SCOPE_STATUSES)
    require_actor(to, SCOPE_ACTORS)

    src = scope["status"]
    case = svc.get_or_404(db.cases, scope["case_id"], "Case")

    if src == "PROPOSED" and to == "APPROVED":
        if case["status"] != "FIELDWORK":
            errors.invalid_state("Parent case must be in FIELDWORK to approve a scope")
        acked = svc.covering_notices(
            case["id"], scope["custodian_ref"], scope["data_source"], {"ACKNOWLEDGED"}
        )
        if not acked:
            errors.business(
                "ERR_NOTICE_NOT_ACKNOWLEDGED",
                "The covering preservation notice is not ACKNOWLEDGED",
            )
        scope["status"] = "APPROVED"
    elif src == "APPROVED" and to == "IN_PROGRESS":
        covering = svc.covering_notices(
            case["id"], scope["custodian_ref"], scope["data_source"], {"ISSUED", "ACKNOWLEDGED"}
        )
        if not covering:
            errors.business(
                "ERR_CUSTODIAN_NOT_PRESERVED",
                "The covering preservation notice has been released",
            )
        scope["status"] = "IN_PROGRESS"
    elif src == "IN_PROGRESS" and to == "COLLECTED":
        count = sum(
            1
            for e in db.evidence_items.values()
            if e["collection_scope_id"] == scope["id"] and e["status"] in svc.CUSTODY_STATUSES
        )
        if count == 0:
            errors.business(
                "ERR_EMPTY_COLLECTION",
                "Scope has no linked evidence in LOGGED/UNDER_REVIEW/ADMITTED",
            )
        scope["review_effort_minutes"] = svc.review_effort_minutes(scope)
        scope["status"] = "COLLECTED"
    elif src in ("PROPOSED", "APPROVED", "IN_PROGRESS") and to == "WITHDRAWN":
        scope["status"] = "WITHDRAWN"
    else:
        errors.invalid_state(f"CollectionScope cannot transition {src} -> {to}")

    svc.touch(scope)
    svc.recompute_case_derived(case)
    return resp.ok(svc.dump(scope))


# ---------------------------------------------------------------------------
# EvidenceItem
# ---------------------------------------------------------------------------
@bp.post("/api/collection-scopes/<rid>/evidence-items")
def create_evidence(rid):
    scope = svc.get_or_404(db.scopes, rid, "CollectionScope")
    p = v.payload()
    custodian_ref = v.need_str(p, "custodian_ref")
    hash_value = v.need_str(p, "hash_value")
    size_bytes = v.need_int(p, "size_bytes")
    captured_at = v.need_dt(p, "captured_at")
    description = v.opt_str(p, "description")

    if scope["status"] != "IN_PROGRESS":
        errors.invalid_state("Evidence may be logged only into an IN_PROGRESS scope")
    if custodian_ref != scope["custodian_ref"]:
        errors.validation("custodian_ref must equal the scope's custodian_ref")
    if size_bytes <= 0:
        errors.validation("size_bytes must be greater than zero")

    item = svc.new_row(
        {
            "collection_scope_id": scope["id"],
            "case_id": scope["case_id"],
            "custodian_ref": custodian_ref,
            "hash_value": hash_value,
            "size_bytes": size_bytes,
            "captured_at": captured_at,
            "description": description,
            "status": "LOGGED",
        }
    )
    db.evidence_items[item["id"]] = item
    svc.recompute_scope_custody(scope)
    return resp.ok(svc.dump(item), status=201)


@bp.get("/api/evidence-items")
def list_evidence():
    q = request.args
    rows = list(db.evidence_items.values())
    for param in ("collection_scope_id", "case_id", "custodian_ref", "status"):
        val = q.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    limit, offset = v.parse_pagination(q)
    rows = svc.sort_rows(rows)
    page, total = svc.paginate(rows, limit, offset)
    return resp.ok_list([svc.dump(r) for r in page], limit, offset, total)


@bp.get("/api/evidence-items/<rid>")
def get_evidence(rid):
    return resp.ok(svc.dump(svc.get_or_404(db.evidence_items, rid, "EvidenceItem")))


@bp.post("/api/evidence-items/<rid>/transition")
def transition_evidence(rid):
    item = svc.get_or_404(db.evidence_items, rid, "EvidenceItem")
    p = v.payload()
    to = parse_to_status(p, svc.EVIDENCE_STATUSES)
    src = item["status"]

    def privilege_pending():
        for d in db.designations.values():
            if (
                d["target_type"] == "EVIDENCE_ITEM"
                and d["target_id"] == item["id"]
                and d["status"] == "DESIGNATED"
            ):
                return True
        return False

    if src == "LOGGED" and to == "UNDER_REVIEW":
        pass
    elif src == "UNDER_REVIEW" and to == "ADMITTED":
        if privilege_pending():
            errors.business(
                "ERR_PRIVILEGE_PENDING",
                "A DESIGNATED privilege designation pends on this item",
            )
    elif src == "UNDER_REVIEW" and to == "EXCLUDED":
        pass
    elif src == "ADMITTED" and to == "EXCLUDED":
        pass
    elif src == "EXCLUDED" and to == "ADMITTED":
        if privilege_pending():
            errors.business(
                "ERR_PRIVILEGE_PENDING",
                "A DESIGNATED privilege designation pends on this item",
            )
    else:
        errors.invalid_state(f"EvidenceItem cannot transition {src} -> {to}")

    item["status"] = to
    svc.touch(item)
    scope = svc.get_or_404(db.scopes, item["collection_scope_id"], "CollectionScope")
    svc.recompute_scope_custody(scope)
    return resp.ok(svc.dump(item))


# ---------------------------------------------------------------------------
# WitnessInterview
# ---------------------------------------------------------------------------
def _half_open_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def interviewer_conflict(interviewer_id, start, end, exclude_id=None):
    for i in db.interviews.values():
        if i["id"] == exclude_id:
            continue
        if i["interviewer_id"] != interviewer_id:
            continue
        if i["status"] not in ("SCHEDULED", "UPJOHN_DELIVERED"):
            continue
        if _half_open_overlap(start, end, i["scheduled_start"], i["scheduled_end"]):
            return True
    return False


def room_conflict(room_ref, start, end, exclude_id=None):
    buffer = timedelta(minutes=15)
    for i in db.interviews.values():
        if i["id"] == exclude_id:
            continue
        if not i.get("room_ref") or i["room_ref"] != room_ref:
            continue
        if i["status"] not in ("SCHEDULED", "UPJOHN_DELIVERED"):
            continue
        # existing window expanded by +/-15 minutes, half-open
        exp_start = i["scheduled_start"] - buffer
        exp_end = i["scheduled_end"] + buffer
        if start < exp_end and exp_start < end:
            return True
    return False


@bp.post("/api/cases/<rid>/interviews")
def create_interview(rid):
    case = svc.get_or_404(db.cases, rid, "Case")
    p = v.payload()
    witness_ref = v.need_str(p, "witness_ref")
    interviewer_id = v.need_str(p, "interviewer_id")
    scheduled_start = v.need_dt(p, "scheduled_start")
    scheduled_end = v.need_dt(p, "scheduled_end")
    room_ref = v.opt_str(p, "room_ref")
    is_subject_interview = v.opt_bool(p, "is_subject_interview", default=False)

    if case["status"] != "FIELDWORK":
        errors.invalid_state("Interviews may be scheduled only while the case is in FIELDWORK")
    if scheduled_end <= scheduled_start:
        errors.validation("scheduled_end must be strictly after scheduled_start")
    if interviewer_conflict(interviewer_id, scheduled_start, scheduled_end):
        errors.business(
            "ERR_INTERVIEWER_OVERLAP",
            "Interviewer already has a SCHEDULED/UPJOHN_DELIVERED interview overlapping this window",
        )
    if room_ref is not None and room_conflict(room_ref, scheduled_start, scheduled_end):
        errors.business(
            "ERR_ROOM_OVERLAP",
            "Room is booked within the 15-minute buffer of this window",
        )

    interview = svc.new_row(
        {
            "case_id": case["id"],
            "witness_ref": witness_ref,
            "interviewer_id": interviewer_id,
            "is_subject_interview": is_subject_interview,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "room_ref": room_ref,
            "upjohn_delivered_at": None,
            "completed_at": None,
            "completion_note": None,
            "no_show_count": 0,
            "status": "SCHEDULED",
        }
    )
    db.interviews[interview["id"]] = interview
    return resp.ok(svc.dump(interview), status=201)


@bp.get("/api/interviews")
def list_interviews():
    q = request.args
    rows = list(db.interviews.values())
    for param in ("case_id", "witness_ref", "interviewer_id", "status"):
        val = q.get(param)
        if val is not None:
            rows = [r for r in rows if r.get(param) == val]
    limit, offset = v.parse_pagination(q)
    rows = svc.sort_rows(rows)
    page, total = svc.paginate(rows, limit, offset)
    return resp.ok_list([svc.dump(r) for r in page], limit, offset, total)


@bp.get("/api/interviews/<rid>")
def get_interview(rid):
    return resp.ok(svc.dump(svc.get_or_404(db.interviews, rid, "WitnessInterview")))


@bp.post("/api/interviews/<rid>/transition")
def transition_interview(rid):
    interview = svc.get_or_404(db.interviews, rid, "WitnessInterview")
    p = v.payload()
    to = parse_to_status(p, svc.INTERVIEW_STATUSES)
    src = interview["status"]
    now = db.clock_now()

    if src == "SCHEDULED" and to == "UPJOHN_DELIVERED":
        if now > interview["scheduled_end"]:
            errors.business(
                "ERR_INTERVIEW_WINDOW_EXPIRED",
                "The scheduled window has expired",
            )
        interview["upjohn_delivered_at"] = now
        interview["status"] = "UPJOHN_DELIVERED"
    elif src == "UPJOHN_DELIVERED" and to == "COMPLETED":
        if interview["upjohn_delivered_at"] is None:
            errors.business(
                "ERR_UPJOHN_REQUIRED",
                "The Upjohn warning must precede completion",
            )
        note = p.get("completion_note", None)
        if note is None or (isinstance(note, str) and not note.strip()):
            errors.missing_field("completion_note")
        if not isinstance(note, str):
            errors.validation("completion_note must be a string")
        interview["completion_note"] = note
        interview["completed_at"] = now
        interview["status"] = "COMPLETED"
    elif src == "SCHEDULED" and to == "NO_SHOW":
        if now <= interview["scheduled_end"]:
            errors.business(
                "ERR_NO_SHOW_TOO_EARLY",
                "No-show may be recorded only after the scheduled window ends",
            )
        interview["no_show_count"] += 1
        interview["status"] = "NO_SHOW"
    elif src == "NO_SHOW" and to == "SCHEDULED":
        new_start = p.get("new_start", None)
        new_end = p.get("new_end", None)
        if new_start is None:
            errors.missing_field("new_start")
        if new_end is None:
            errors.missing_field("new_end")
        ns = v.parse_dt(new_start)
        ne = v.parse_dt(new_end)
        if ns is None:
            errors.validation("new_start must be an ISO8601 datetime")
        if ne is None:
            errors.validation("new_end must be an ISO8601 datetime")
        if not ns < ne:
            errors.validation("new_start must be strictly before new_end")
        # business constraints (priority 8) precede clock rules (priority 10)
        if interviewer_conflict(interview["interviewer_id"], ns, ne, exclude_id=interview["id"]):
            errors.business(
                "ERR_INTERVIEWER_OVERLAP",
                "Interviewer already has a SCHEDULED/UPJOHN_DELIVERED interview overlapping this window",
            )
        if interview.get("room_ref") is not None and room_conflict(
            interview["room_ref"], ns, ne, exclude_id=interview["id"]
        ):
            errors.business(
                "ERR_ROOM_OVERLAP",
                "Room is booked within the 15-minute buffer of this window",
            )
        if ns < now:
            errors.business(
                "ERR_SCHEDULE_IN_PAST",
                "new_start must not be earlier than the current logical clock",
            )
        interview["scheduled_start"] = ns
        interview["scheduled_end"] = ne
        interview["upjohn_delivered_at"] = None
        interview["status"] = "SCHEDULED"
    elif src in ("SCHEDULED", "UPJOHN_DELIVERED") and to == "CANCELLED":
        interview["status"] = "CANCELLED"
    else:
        errors.invalid_state(f"WitnessInterview cannot transition {src} -> {to}")

    svc.touch(interview)
    return resp.ok(svc.dump(interview))
