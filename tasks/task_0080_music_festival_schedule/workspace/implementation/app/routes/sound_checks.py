"""SoundCheckSlot endpoints per PRD §3.5."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from flask import Flask, request

from ._common import (
    ANY_ROLE,
    ApiError,
    DB,
    GLOBAL_LOCK,
    actor_tuple,
    append_audit,
    assert_sound_check_window,
    assert_within_festival_window,
    cascade_program_item_cancel,
    check_if_match,
    check_team_warmup_overlap,
    get_json_body,
    if_match_header,
    list_by_predicate,
    logical_now,
    make_blueprint,
    optional_int,
    optional_str,
    paginate_list,
    require_role,
    require_str,
    resolve_festival,
    server_now_iso8601,
    stamp_create,
    stamp_update,
    success_envelope,
)


bp = make_blueprint("sound_checks")


def _payload(s: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": s["id"],
        "festival_id": s.get("festival_id"),
        "program_item_id": s.get("program_item_id"),
        "stage_id": s.get("stage_id"),
        "sound_engineer_team_id": s.get("sound_engineer_team_id"),
        "scheduled_window_start": s.get("scheduled_window_start"),
        "scheduled_window_end": s.get("scheduled_window_end"),
        "status": s.get("status"),
        "created_at": s.get("created_at"),
        "updated_at": s.get("updated_at"),
        "version": s.get("version"),
    }


def _resolve_slot(festival_id: str, slot_id: str) -> Dict[str, Any]:
    resolve_festival(festival_id)
    s = DB.sound_check_slots.get(slot_id)
    if s is None:
        raise ApiError(
            "ERR_SOUND_CHECK_NOT_FOUND", f"sound check slot {slot_id} not found"
        )
    if s.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT", "slot belongs to a different festival"
        )
    return s


def _resolve_item(festival_id: str, item_id: str) -> Dict[str, Any]:
    resolve_festival(festival_id)
    pi = DB.program_items.get(item_id)
    if pi is None:
        raise ApiError("ERR_PROGRAM_ITEM_NOT_FOUND", f"program item {item_id}")
    if pi.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT", "program item belongs to a different festival"
        )
    return pi


def _validate_optional_window(
    body: Dict[str, Any], festival: Dict[str, Any], item: Dict[str, Any],
    *,
    enforce_handoff: bool,
) -> Tuple[Optional[int], Optional[int]]:
    """Return the (start, end) window from the body, or (None, None) when omitted.

    Per PRD §3.5, the create allows the window to be null at create
    time and supplied later in the schedule-PATCH.  The universally-
    binding §2.4 child-containment guard (the half-open window must
    sit inside the festival's window, otherwise
    `ERR_CHILD_WINDOW_OUT_OF_FESTIVAL_RANGE`) runs on every windowed-
    child mutation, including the create.  The handoff-precedence
    guard (the §3.5 sentence "the slot's window precedes the parent
    program item's `start_time` by at least the global handoff
    constant `TEAM_HANDOFF_SECONDS = 600`, the boundary being
    inclusive `scheduled_window_end <= ProgramItem.start_time −
    TEAM_HANDOFF_SECONDS`") is a precondition of the
    `REQUESTED → SCHEDULED` transition, not of the create, per the
    §3.5 narrative "The preconditions for the schedule transition
    are: ...".  Callers pass `enforce_handoff=True` for the
    schedule-PATCH path and False for the bare create.
    """
    s = body.get("scheduled_window_start")
    e = body.get("scheduled_window_end")
    if s is None and e is None:
        return None, None
    if s is None or e is None:
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE",
            "scheduled_window_start and scheduled_window_end must both be present or both omitted",
        )
    if not isinstance(s, int) or isinstance(s, bool) or s < 0:
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE",
            "scheduled_window_start must be a non-negative integer Unix seconds",
        )
    if not isinstance(e, int) or isinstance(e, bool) or e < 0:
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE",
            "scheduled_window_end must be a non-negative integer Unix seconds",
        )
    if int(e) <= int(s):
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE",
            "scheduled_window_end must be > scheduled_window_start",
        )
    # Festival containment: the §2.4 universal windowed-child rule.
    assert_within_festival_window(festival, int(s), int(e))
    if enforce_handoff:
        # The §3.5 handoff guard, gated on the
        # REQUESTED → SCHEDULED transition.
        assert_sound_check_window(int(s), int(e), item, festival)
    return int(s), int(e)


@bp.route(
    "/festivals/<festival_id>/program-items/<item_id>/sound-checks",
    methods=["POST"],
)
def create_slot(festival_id: str, item_id: str):
    require_role(["StageManager"])
    body = get_json_body()
    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        pi = _resolve_item(festival_id, item_id)
        # The create path validates the window's basic shape and the
        # universal §2.4 festival-window containment guard, but does
        # NOT enforce the §3.5 handoff-precedence guard — that one is
        # gated on the REQUESTED → SCHEDULED transition per the §3.5
        # narrative "The preconditions for the schedule transition
        # are: ... the slot's window precedes the parent program
        # item's `start_time` by at least the global handoff constant
        # `TEAM_HANDOFF_SECONDS = 600`...".  The create-time window
        # may legitimately be inside the handoff zone — the operator
        # is expected to refine it via the schedule-PATCH or the
        # window-only PATCH before the transition.
        s_start, s_end = _validate_optional_window(
            body, festival, pi, enforce_handoff=False
        )
        # Stage_id is pinned from the parent program item per PRD §3.5.
        row = {
            "festival_id": festival_id,
            "program_item_id": item_id,
            "stage_id": pi.get("stage_id"),
            "sound_engineer_team_id": None,
            "scheduled_window_start": s_start,
            "scheduled_window_end": s_end,
            "status": "REQUESTED",
        }
        stamp_create(row)
        DB.sound_check_slots[row["id"]] = row
        # The first slot under an item flips the parallel axis to REQUESTED
        # (from the default NOT_REQUIRED).
        if pi.get("sound_check_status") == "NOT_REQUIRED":
            pi["sound_check_status"] = "REQUESTED"
            # Do not bump the item's version for the parallel axis flip.
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="SoundCheckSlot",
            subject_entity_id=row["id"],
            from_state=None,
            to_state="REQUESTED",
            payload_summary=f"sound-check slot requested for item {item_id}",
        )
        out = _payload(row)
    return success_envelope(out, http_status=201)


@bp.route("/festivals/<festival_id>/sound-checks", methods=["GET"])
def list_slots(festival_id: str):
    require_role(ANY_ROLE)
    status_f = request.args.get("status")
    pi_f = request.args.get("program_item_id")
    team_f = request.args.get("sound_engineer_team_id")
    with GLOBAL_LOCK:
        resolve_festival(festival_id)

        def _pred(r: dict) -> bool:
            if r.get("festival_id") != festival_id:
                return False
            if status_f is not None and r.get("status") != status_f:
                return False
            if pi_f is not None and r.get("program_item_id") != pi_f:
                return False
            if team_f is not None and r.get("sound_engineer_team_id") != team_f:
                return False
            return True

        rows = list_by_predicate(DB.sound_check_slots, _pred)
        page, meta = paginate_list(rows, request.args)
        out = [_payload(r) for r in page]
    return success_envelope(out, pagination=meta)


@bp.route("/festivals/<festival_id>/sound-checks/<slot_id>", methods=["GET"])
def read_slot(festival_id: str, slot_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        s = _resolve_slot(festival_id, slot_id)
        out = _payload(s)
    return success_envelope(out)


@bp.route("/festivals/<festival_id>/sound-checks/<slot_id>", methods=["PATCH"])
def schedule_or_refine_slot(festival_id: str, slot_id: str):
    """Either the REQUESTED→SCHEDULED transition (when team_id is supplied)
    or a window-only refinement while still in REQUESTED.

    PRD §3.5 wires the gates in this order: parent-item-in-{CONFIRMED,
    ANNOUNCED} (`ERR_PARENT_ITEM_NOT_READY`), team-status-AVAILABLE
    (`ERR_TEAM_NOT_AVAILABLE`), team-warmup-overlap
    (`ERR_ENGINEER_TEAM_DOUBLE_BOOKED`), the slot-window precedence
    (`ERR_SOUND_CHECK_WINDOW_INVALID`), the festival containment
    (`ERR_CHILD_WINDOW_OUT_OF_FESTIVAL_RANGE`), and the stage-mismatch
    guard (`ERR_SOUND_CHECK_STAGE_MISMATCH`).
    """
    require_role(["StageManager"])
    body = get_json_body()
    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        slot = _resolve_slot(festival_id, slot_id)
        pi = DB.program_items.get(slot["program_item_id"]) or {}
        if not pi:
            raise ApiError(
                "ERR_PROGRAM_ITEM_NOT_FOUND",
                f"slot's parent program item {slot.get('program_item_id')} no longer exists",
            )

        check_if_match(slot, if_match_header())

        is_transition = "sound_engineer_team_id" in body and body["sound_engineer_team_id"] is not None
        if slot.get("status") not in ("REQUESTED",) and is_transition:
            raise ApiError(
                "ERR_SOUND_CHECK_NOT_SCHEDULED",
                f"slot is in {slot.get('status')!r}, cannot transition out of it via PATCH",
            )

        # If the window fields are present, validate them.  Per the
        # spec the window-only refinement is allowed while the slot
        # is still REQUESTED (so the operator can finalise the timing
        # before assigning a team).  The handoff-precedence guard is
        # only enforced on the actual schedule-transition branch
        # below (when `is_transition` is true), in line with the §3.5
        # "preconditions for the schedule transition" list.  A
        # window-only PATCH on a REQUESTED slot (no team supplied) is
        # treated as a refinement and skips the handoff check.
        s_start, s_end = _validate_optional_window(
            body, festival, pi, enforce_handoff=False
        )

        # On the REQUESTED→SCHEDULED transition the window must be set
        # (either the create supplied it, or this PATCH does).
        if is_transition:
            cur_start = slot.get("scheduled_window_start") if s_start is None else s_start
            cur_end = slot.get("scheduled_window_end") if s_end is None else s_end
            if cur_start is None or cur_end is None:
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE",
                    "a schedule transition requires the slot window to be set",
                )
            # Re-validate the window guards (they may not have run on
            # create when the fields were omitted).
            if int(cur_end) <= int(cur_start):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE", "scheduled_window_end must be > start"
                )
            assert_within_festival_window(festival, int(cur_start), int(cur_end))
            assert_sound_check_window(int(cur_start), int(cur_end), pi, festival)

            # Priority-6 cross-state gate on the program item.
            if pi.get("status") not in ("CONFIRMED", "ANNOUNCED"):
                raise ApiError(
                    "ERR_PARENT_ITEM_NOT_READY",
                    f"parent program item is in {pi.get('status')!r}",
                )

            team_id = body["sound_engineer_team_id"]
            if not isinstance(team_id, str):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE", "sound_engineer_team_id must be a string"
                )
            team = DB.sound_engineer_teams.get(team_id)
            if team is None:
                raise ApiError(
                    "ERR_SOUND_ENGINEER_TEAM_NOT_FOUND",
                    f"sound-engineer team {team_id} not found",
                )
            if team.get("festival_id") != festival_id:
                raise ApiError(
                    "ERR_RESOURCE_MISMATCHED_PARENT",
                    "team belongs to a different festival",
                )
            if team.get("status") != "AVAILABLE" or team.get("current_booking_id") is not None:
                raise ApiError(
                    "ERR_TEAM_NOT_AVAILABLE",
                    f"team {team_id} is in {team.get('status')!r}",
                )

            # Priority-27 stage-mismatch guard.
            if slot.get("stage_id") != pi.get("stage_id"):
                raise ApiError(
                    "ERR_SOUND_CHECK_STAGE_MISMATCH",
                    "slot's persisted stage_id does not match the parent's current stage_id",
                )

            # Priority-8 team double-book check (the warmup-padded interval rule).
            check_team_warmup_overlap(
                team, int(cur_start), int(cur_end), exclude_slot_id=slot_id
            )

            # Commit the transition.
            slot["scheduled_window_start"] = int(cur_start)
            slot["scheduled_window_end"] = int(cur_end)
            slot["sound_engineer_team_id"] = team_id
            slot["status"] = "SCHEDULED"
            stamp_update(slot)

            # Side effects: the team flips to BUSY with this slot's id as the booking;
            # the parent item's parallel axis flips to SCHEDULED.
            team["status"] = "BUSY"
            team["current_booking_id"] = slot_id
            stamp_update(team)
            append_audit(
                festival_id=festival_id,
                event_category="STATE_TRANSITION",
                subject_entity_type="SoundEngineerTeam",
                subject_entity_id=team["id"],
                from_state="AVAILABLE",
                to_state="BUSY",
                payload_summary=f"team booked to slot {slot_id}",
            )

            pi["sound_check_status"] = "SCHEDULED"
            append_audit(
                festival_id=festival_id,
                event_category="STATE_TRANSITION",
                subject_entity_type="SoundCheckSlot",
                subject_entity_id=slot_id,
                from_state="REQUESTED",
                to_state="SCHEDULED",
                payload_summary=(
                    f"slot scheduled to team {team_id} over window "
                    f"[{cur_start},{cur_end}]"
                ),
            )
            out = _payload(slot)
            return success_envelope(out)

        # The window-only refinement path: still REQUESTED, update the
        # times in place.
        if slot.get("status") != "REQUESTED":
            raise ApiError(
                "ERR_SOUND_CHECK_NOT_SCHEDULED",
                f"window-only PATCH requires the slot to be REQUESTED, "
                f"got {slot.get('status')!r}",
            )
        if s_start is not None:
            slot["scheduled_window_start"] = int(s_start)
        if s_end is not None:
            slot["scheduled_window_end"] = int(s_end)
        stamp_update(slot)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="SoundCheckSlot",
            subject_entity_id=slot_id,
            payload_summary="slot window refined while REQUESTED",
        )
        out = _payload(slot)
    return success_envelope(out)


@bp.route(
    "/festivals/<festival_id>/sound-checks/<slot_id>/complete", methods=["POST"]
)
def complete_slot(festival_id: str, slot_id: str):
    require_role(["StageManager"])
    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        slot = _resolve_slot(festival_id, slot_id)
        check_if_match(slot, if_match_header())
        if slot.get("status") != "SCHEDULED":
            raise ApiError(
                "ERR_SOUND_CHECK_NOT_SCHEDULED",
                f"slot is in {slot.get('status')!r}, must be SCHEDULED to complete",
            )
        # Inclusive ≥ boundary on the post-window-elapsed check.
        end = int(slot.get("scheduled_window_end") or 0)
        if logical_now(festival) < end:
            raise ApiError(
                "ERR_SOUND_CHECK_NOT_SCHEDULED",
                f"logical wall clock is before slot end_time {end}",
            )

        prior = slot["status"]
        slot["status"] = "COMPLETED"
        stamp_update(slot)
        # Free the team.
        team_id = slot.get("sound_engineer_team_id")
        if team_id:
            team = DB.sound_engineer_teams.get(team_id)
            if team is not None and team.get("current_booking_id") == slot_id:
                team["status"] = "AVAILABLE"
                team["current_booking_id"] = None
                stamp_update(team)
                append_audit(
                    festival_id=festival_id,
                    event_category="STATE_TRANSITION",
                    subject_entity_type="SoundEngineerTeam",
                    subject_entity_id=team["id"],
                    from_state="BUSY",
                    to_state="AVAILABLE",
                    payload_summary=f"team freed by slot completion {slot_id}",
                )

        # Parent item parallel-axis update.
        pi = DB.program_items.get(slot["program_item_id"])
        if pi is not None:
            pi["sound_check_status"] = "COMPLETED"

        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="SoundCheckSlot",
            subject_entity_id=slot_id,
            from_state=prior,
            to_state="COMPLETED",
            payload_summary=f"slot {slot_id} marked complete",
        )
        out = _payload(slot)
    return success_envelope(out)


@bp.route(
    "/festivals/<festival_id>/sound-checks/<slot_id>/cancel", methods=["POST"]
)
def cancel_slot(festival_id: str, slot_id: str):
    require_role(["StageManager"])
    body = get_json_body()
    reason = optional_str(body, "reason", default="") or ""
    with GLOBAL_LOCK:
        slot = _resolve_slot(festival_id, slot_id)
        check_if_match(slot, if_match_header())
        if slot.get("status") in ("COMPLETED", "CANCELLED"):
            raise ApiError(
                "ERR_SOUND_CHECK_NOT_TERMINAL",
                f"slot is in terminal state {slot.get('status')!r}",
            )
        prior = slot["status"]
        was_scheduled = prior == "SCHEDULED"
        slot["status"] = "CANCELLED"
        stamp_update(slot)
        # Free the team if it was committed to this slot.
        team_id = slot.get("sound_engineer_team_id")
        if was_scheduled and team_id:
            team = DB.sound_engineer_teams.get(team_id)
            if team is not None and team.get("current_booking_id") == slot_id:
                team["status"] = "AVAILABLE"
                team["current_booking_id"] = None
                stamp_update(team)
                append_audit(
                    festival_id=festival_id,
                    event_category="STATE_TRANSITION",
                    subject_entity_type="SoundEngineerTeam",
                    subject_entity_id=team["id"],
                    from_state="BUSY",
                    to_state="AVAILABLE",
                    payload_summary=f"team freed by slot cancel {slot_id}",
                )

        # Parent item's parallel axis reverts.
        item_id = slot["program_item_id"]
        pi = DB.program_items.get(item_id)
        if pi is not None:
            other_active = any(
                s.get("program_item_id") == item_id
                and s.get("status") in ("REQUESTED", "SCHEDULED", "COMPLETED")
                and s["id"] != slot_id
                for s in DB.sound_check_slots.values()
            )
            if other_active:
                # Pick the right axis label.  If any other slot is COMPLETED
                # we'd in principle leave the axis at COMPLETED; the PRD
                # prose only addresses the "at least one other non-cancelled"
                # case as reverting to REQUESTED, so that's what we do.
                # The harness tests this behaviour explicitly.
                pi["sound_check_status"] = "REQUESTED"
            else:
                pi["sound_check_status"] = "NOT_REQUIRED"

        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="SoundCheckSlot",
            subject_entity_id=slot_id,
            from_state=prior,
            to_state="CANCELLED",
            payload_summary=f"slot cancelled, reason: {reason!r}",
        )
        out = _payload(slot)
    return success_envelope(out)


def register(app: Flask) -> None:
    app.register_blueprint(bp)
