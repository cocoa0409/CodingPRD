"""CommitteePanel, PresentationSlot and CommitteeVote endpoints (PRD 3.8)."""

from datetime import timedelta

import calc
import domain
import serializers as S
import validation as V
from db import apply_changes, base_record, db, now, touch
from errors import fail
from middleware import authorize, check_state_scope
from response import respond, respond_list

from flask import Blueprint

bp = Blueprint("panels", __name__)

PANEL_READ_ROLES = (
    "PlatformAdmin",
    "StateAdoptionOfficer",
    "ReviewCommitteeMember",
    "PublisherEditor",
)

VOTE_LIST_ROLES = ("PlatformAdmin", "StateAdoptionOfficer", "ReviewCommitteeMember")


def _whole_minutes(start, end):
    return int((end - start).total_seconds() // 60)


# --- CommitteePanel --------------------------------------------------------
@bp.post("/committee-panels")
def create_panel():
    user_id, role = authorize(("StateAdoptionOfficer",))
    payload = V.body()

    cycle_id = V.get_str(payload, "cycle_id")
    panel_label = V.get_str(payload, "panel_label", min_len=1, max_len=60)
    session_start_at = V.get_datetime(payload, "session_start_at")
    session_end_at = V.get_datetime(payload, "session_end_at")
    if session_end_at <= session_start_at:
        fail(
            "ERR_INVALID_REQUEST",
            "session_end_at must be strictly after session_start_at.",
        )
    buffer_minutes = V.get_int(
        payload, "buffer_minutes", minimum=0, maximum=60, required=False, default=10
    )
    member_count = V.get_int(payload, "member_count", minimum=1, maximum=25)
    quorum_required = V.get_int(payload, "quorum_required", minimum=1)
    if quorum_required > member_count:
        fail("ERR_INVALID_REQUEST", "quorum_required must not exceed member_count.")

    session_minutes = _whole_minutes(session_start_at, session_end_at)
    slot_minutes_capacity = V.get_int(
        payload, "slot_minutes_capacity", minimum=1, required=False, default=None
    )
    if slot_minutes_capacity is None:
        slot_minutes_capacity = session_minutes
    elif slot_minutes_capacity > session_minutes:
        fail(
            "ERR_INVALID_REQUEST",
            "slot_minutes_capacity may not exceed the session length in minutes.",
        )

    cycle = domain.find_cycle(cycle_id, "ERR_REFERENCED_RESOURCE_NOT_FOUND")
    check_state_scope(role, user_id, cycle["state_id"])
    if cycle["status"] in ("DECIDED", "ARCHIVED"):
        fail(
            "ERR_ADOPTION_CYCLE_STATE_INVALID",
            "This cycle no longer admits new panels.",
        )

    record = base_record()
    record.update(
        {
            "cycle_id": cycle_id,
            "panel_label": panel_label,
            "session_start_at": session_start_at,
            "session_end_at": session_end_at,
            "buffer_minutes": buffer_minutes,
            "slot_minutes_capacity": slot_minutes_capacity,
            "reserved_minutes": 0,
            "member_count": member_count,
            "quorum_required": quorum_required,
            "status": "SCHEDULED",
        }
    )
    db.committee_panels[record["id"]] = record
    return respond(S.serialize(record, S.COMMITTEE_PANEL_FIELDS), 201)


@bp.get("/committee-panels/<panel_id>")
def get_panel(panel_id):
    authorize(PANEL_READ_ROLES)
    record = domain.find_panel(panel_id)
    return respond(S.serialize(record, S.COMMITTEE_PANEL_FIELDS))


@bp.post("/committee-panels/<panel_id>/slots")
def reserve_slot(panel_id):
    user_id, role = authorize(("StateAdoptionOfficer",))
    payload = V.body()

    submission_id = V.get_str(payload, "submission_id")
    start_at = V.get_datetime(payload, "start_at")
    end_at = V.get_datetime(payload, "end_at")
    if end_at <= start_at:
        fail("ERR_INVALID_REQUEST", "end_at must be strictly after start_at.")
    expected_panel_version = V.get_int(payload, "expected_panel_version", minimum=0)

    panel = domain.find_panel(panel_id)
    submission = domain.find_submission(
        submission_id, "ERR_REFERENCED_RESOURCE_NOT_FOUND"
    )
    cycle = db.adoption_cycles[panel["cycle_id"]]
    check_state_scope(role, user_id, cycle["state_id"])

    if expected_panel_version != panel["version"]:
        fail(
            "ERR_STALE_PANEL_VERSION",
            "expected_panel_version does not match the panel's current version.",
        )
    if cycle["status"] in ("DECIDED", "ARCHIVED"):
        fail(
            "ERR_ADOPTION_CYCLE_STATE_INVALID",
            "This cycle no longer admits slot reservations.",
        )
    if submission["review_status"] != "FILED":
        fail(
            "ERR_SUBMISSION_STATE_INVALID",
            "Only a FILED submission may be given a hearing.",
        )
    if panel["status"] != "SCHEDULED":
        fail(
            "ERR_COMMITTEE_PANEL_STATE_INVALID",
            "Slots may only be reserved while the panel is SCHEDULED.",
        )
    if submission["content_pin_stale"]:
        fail(
            "ERR_CONTENT_PIN_STALE",
            "The submission's pinned content revision is stale.",
        )
    if start_at < panel["session_start_at"] or end_at > panel["session_end_at"]:
        fail(
            "ERR_SLOT_OUTSIDE_SESSION",
            "The requested window lies outside the panel's session.",
        )

    buffer = timedelta(minutes=panel["buffer_minutes"])
    for existing in domain.slots_of_panel(panel_id):
        if existing["status"] not in domain.OCCUPYING_SLOT_STATUSES:
            continue
        after = start_at >= existing["end_at"] + buffer
        before = end_at + buffer <= existing["start_at"]
        if not (after or before):
            fail(
                "ERR_SLOT_BUFFER_CONFLICT",
                "The requested window violates the panel's turnover buffer.",
            )

    duration_minutes = _whole_minutes(start_at, end_at)
    if panel["reserved_minutes"] + duration_minutes > panel["slot_minutes_capacity"]:
        fail(
            "ERR_PANEL_CAPACITY_EXCEEDED",
            "The panel's presentation-minute budget cannot accommodate this slot.",
        )

    record = base_record()
    record.update(
        {
            "panel_id": panel_id,
            "submission_id": submission_id,
            "start_at": start_at,
            "end_at": end_at,
            "duration_minutes": duration_minutes,
            "status": "RESERVED",
            "tally_outcome": "PENDING",
            "recommend_ratio": None,
            "counted_vote_count": 0,
        }
    )
    db.presentation_slots[record["id"]] = record

    # Every accepted reservation bumps the panel's version exactly once.
    panel["reserved_minutes"] = panel["reserved_minutes"] + duration_minutes
    touch(panel)

    apply_changes(submission, {"review_status": "SCHEDULED"})
    domain.recount_cycle(cycle)

    return respond(S.serialize(record, S.PRESENTATION_SLOT_FIELDS), 201)


@bp.post("/committee-panels/<panel_id>/open-session")
def open_session(panel_id):
    user_id, role = authorize(("StateAdoptionOfficer",))
    V.body()

    panel = domain.find_panel(panel_id)
    cycle = db.adoption_cycles[panel["cycle_id"]]
    check_state_scope(role, user_id, cycle["state_id"])

    if cycle["status"] != "IN_REVIEW":
        fail(
            "ERR_ADOPTION_CYCLE_STATE_INVALID",
            "A panel session may only open while the cycle is IN_REVIEW.",
        )
    if panel["status"] != "SCHEDULED":
        fail(
            "ERR_COMMITTEE_PANEL_STATE_INVALID",
            "Only a SCHEDULED panel may open its session.",
        )
    if now() < panel["session_start_at"]:
        fail(
            "ERR_PANEL_SESSION_NOT_DUE",
            "The logical clock has not reached session_start_at.",
        )

    apply_changes(panel, {"status": "IN_SESSION"})
    return respond(S.serialize(panel, S.COMMITTEE_PANEL_FIELDS))


@bp.post("/committee-panels/<panel_id>/close-session")
def close_session(panel_id):
    user_id, role = authorize(("StateAdoptionOfficer",))
    V.body()

    panel = domain.find_panel(panel_id)
    cycle = db.adoption_cycles[panel["cycle_id"]]
    check_state_scope(role, user_id, cycle["state_id"])

    if panel["status"] != "IN_SESSION":
        fail(
            "ERR_COMMITTEE_PANEL_STATE_INVALID",
            "Only an IN_SESSION panel may be closed.",
        )
    slots = domain.slots_of_panel(panel_id)
    for slot in slots:
        if slot["status"] == "PRESENTED":
            fail(
                "ERR_PRESENTATION_SLOT_STATE_INVALID",
                "A presented slot of this panel has not been tallied.",
            )

    apply_changes(panel, {"status": "CLOSED"})

    affected = []
    for slot in slots:
        if slot["status"] == "RESERVED":
            domain.no_show_slot(slot)
            affected.append(db.submissions[slot["submission_id"]])
    for submission in affected:
        domain.demote_if_unslotted(submission)

    return respond(S.serialize(panel, S.COMMITTEE_PANEL_FIELDS))


# --- PresentationSlot ------------------------------------------------------
@bp.get("/presentation-slots/<slot_id>")
def get_slot(slot_id):
    authorize(PANEL_READ_ROLES)
    record = domain.find_slot(slot_id)
    return respond(S.serialize(record, S.PRESENTATION_SLOT_FIELDS))


@bp.get("/presentation-slots")
def list_slots():
    authorize(PANEL_READ_ROLES)
    limit, offset = V.pagination()
    panel_id = V.query_str("panel_id")
    submission_id = V.query_str("submission_id")
    status = V.query_enum("status", V.SLOT_STATUSES)
    tally_outcome = V.query_enum("tally_outcome", V.TALLY_OUTCOMES)

    items = domain.ordered(list(db.presentation_slots.values()))
    if panel_id is not None:
        items = [i for i in items if i["panel_id"] == panel_id]
    if submission_id is not None:
        items = [i for i in items if i["submission_id"] == submission_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if tally_outcome is not None:
        items = [i for i in items if i["tally_outcome"] == tally_outcome]

    total = len(items)
    page = items[offset:offset + limit]
    return respond_list(
        S.serialize_many(page, S.PRESENTATION_SLOT_FIELDS), total, limit, offset
    )


@bp.post("/presentation-slots/<slot_id>/present")
def present_slot(slot_id):
    user_id, role = authorize(("StateAdoptionOfficer",))
    V.body()

    slot = domain.find_slot(slot_id)
    panel = db.committee_panels[slot["panel_id"]]
    cycle = db.adoption_cycles[panel["cycle_id"]]
    check_state_scope(role, user_id, cycle["state_id"])

    if panel["status"] != "IN_SESSION":
        fail(
            "ERR_COMMITTEE_PANEL_STATE_INVALID",
            "The panel is not IN_SESSION.",
        )
    if slot["status"] != "RESERVED":
        fail(
            "ERR_PRESENTATION_SLOT_STATE_INVALID",
            "Only a RESERVED slot may be presented.",
        )
    submission = db.submissions[slot["submission_id"]]
    if submission["content_pin_stale"]:
        fail(
            "ERR_CONTENT_PIN_STALE",
            "The submission's pinned content revision is stale.",
        )
    if now() < slot["start_at"]:
        fail(
            "ERR_SLOT_NOT_STARTED",
            "The logical clock has not reached the slot's start_at.",
        )

    apply_changes(slot, {"status": "PRESENTED"})
    apply_changes(submission, {"review_status": "PRESENTED"})
    domain.recount_cycle(cycle)
    return respond(S.serialize(slot, S.PRESENTATION_SLOT_FIELDS))


# --- CommitteeVote ---------------------------------------------------------
@bp.post("/presentation-slots/<slot_id>/votes")
def cast_vote(slot_id):
    user_id, _role = authorize(("ReviewCommitteeMember",))
    payload = V.body()

    vote = V.get_enum(payload, "vote", V.VOTES)
    rationale = V.get_str(payload, "rationale", min_len=5, max_len=500)

    slot = domain.find_slot(slot_id)
    if slot["status"] != "PRESENTED":
        fail(
            "ERR_PRESENTATION_SLOT_STATE_INVALID",
            "Ballots may only be cast on a PRESENTED slot.",
        )

    existing = domain.votes_of_slot(slot_id)
    sequence_no = max([v["sequence_no"] for v in existing] or [0]) + 1
    for ballot in existing:
        if ballot["member_user_id"] == user_id:
            ballot["superseded"] = True

    record = base_record(with_version=False)
    record.update(
        {
            "slot_id": slot_id,
            "member_user_id": user_id,
            "vote": vote,
            "rationale": rationale,
            "sequence_no": sequence_no,
            "superseded": False,
        }
    )
    db.committee_votes[record["id"]] = record
    return respond(S.serialize(record, S.COMMITTEE_VOTE_FIELDS), 201)


@bp.get("/presentation-slots/<slot_id>/votes")
def list_votes(slot_id):
    authorize(VOTE_LIST_ROLES)
    limit, offset = V.pagination()
    vote = V.query_enum("vote", V.VOTES)
    superseded = V.query_bool("superseded")

    domain.find_slot(slot_id)

    items = domain.votes_of_slot(slot_id)
    if vote is not None:
        items = [i for i in items if i["vote"] == vote]
    if superseded is not None:
        items = [i for i in items if i["superseded"] == superseded]

    total = len(items)
    page = items[offset:offset + limit]
    return respond_list(
        S.serialize_many(page, S.COMMITTEE_VOTE_FIELDS), total, limit, offset
    )


@bp.post("/presentation-slots/<slot_id>/tally")
def tally_slot(slot_id):
    user_id, role = authorize(("StateAdoptionOfficer",))
    V.body()

    slot = domain.find_slot(slot_id)
    panel = db.committee_panels[slot["panel_id"]]
    cycle = db.adoption_cycles[panel["cycle_id"]]
    state = db.state_profiles[cycle["state_id"]]
    check_state_scope(role, user_id, cycle["state_id"])

    if panel["status"] != "IN_SESSION":
        fail("ERR_COMMITTEE_PANEL_STATE_INVALID", "The panel is not IN_SESSION.")
    if slot["status"] != "PRESENTED":
        fail(
            "ERR_PRESENTATION_SLOT_STATE_INVALID",
            "Only a PRESENTED slot may be tallied.",
        )

    counted = calc.project_ballots(domain.votes_of_slot(slot_id))
    if len(counted) < panel["quorum_required"]:
        fail(
            "ERR_QUORUM_NOT_MET",
            "Counted ballots do not reach the panel's quorum.",
        )
    if not [v for v in counted if v["vote"] != "ABSTAIN"]:
        fail("ERR_NO_COUNTABLE_VOTES", "Every counted ballot is an abstention.")

    ratio, outcome = calc.tally_ratio(counted)
    apply_changes(
        slot,
        {
            "status": "TALLIED",
            "tally_outcome": outcome,
            "recommend_ratio": ratio,
            "counted_vote_count": len(counted),
        },
    )

    submission = db.submissions[slot["submission_id"]]
    title = db.titles[submission["title_id"]]

    gates_met = (
        submission["pricing_status"] == "PRICE_APPROVED"
        and submission["verified_coverage_pct"] >= state["min_verified_coverage_pct"]
        and not submission["adoption_blocked"]
        and submission["unresolved_critical_count"] == 0
    )

    if outcome in ("RECOMMEND", "RECOMMEND_WITH_CONDITIONS") and gates_met:
        review_status = (
            "ADOPTED" if outcome == "RECOMMEND" else "ADOPTED_WITH_CONDITIONS"
        )
        apply_changes(submission, {"review_status": review_status})

        title_changes = {}
        if state["state_code"] not in title["adopted_state_codes"]:
            title_changes["adopted_state_codes"] = (
                list(title["adopted_state_codes"]) + [state["state_code"]]
            )
        if title["status"] == "DRAFT":
            title_changes["status"] = "ACTIVE"
        if title_changes:
            apply_changes(title, title_changes)

        for proposal in domain.proposals_of_submission(submission["id"]):
            if proposal["status"] == "APPROVED":
                apply_changes(proposal, {"contract_locked": True})
    else:
        apply_changes(submission, {"review_status": "NOT_ADOPTED"})

    domain.recount_cycle(cycle)
    return respond(S.serialize(slot, S.PRESENTATION_SLOT_FIELDS))
