"""Festival CRUD and lifecycle endpoints per PRD §3.1 and §4."""
from __future__ import annotations

from typing import Any, Dict

from flask import Flask, request

from ._common import (
    ANY_ROLE,
    ApiError,
    DB,
    GLOBAL_LOCK,
    actor_tuple,
    append_audit,
    check_if_match,
    festival_cancel_fanout,
    find_or_404,
    get_json_body,
    if_match_header,
    list_by_predicate,
    make_blueprint,
    optional_str,
    paginate_list,
    recompute_outstanding_tickets_total,
    require_role,
    require_str,
    require_window,
    resolve_festival,
    server_now_iso8601,
    stamp_create,
    stamp_update,
    success_envelope,
)
from ..calculations import festival_day_count


bp = make_blueprint("festivals")


# Per PRD §2.4, the festival window must satisfy end > start and both
# times must be positive Unix-seconds integers.  A zero festival_day_count
# (a window shorter than a single second-difference would round-up to 1
# day, but a window of zero or a window with end == start) is rejected
# with ERR_INVALID_FESTIVAL_WINDOW.
def _validate_festival_window(start_time: int, end_time: int) -> None:
    if start_time <= 0 or end_time <= 0:
        raise ApiError(
            "ERR_INVALID_FESTIVAL_WINDOW",
            "start_time and end_time must be positive Unix-seconds integers",
        )
    if end_time <= start_time:
        raise ApiError(
            "ERR_INVALID_FESTIVAL_WINDOW",
            f"end_time {end_time} must be strictly greater than start_time {start_time}",
        )
    if festival_day_count(start_time, end_time) <= 0:
        raise ApiError(
            "ERR_INVALID_FESTIVAL_WINDOW",
            "festival window resolves to zero days",
        )


def _festival_payload(fest: Dict[str, Any]) -> Dict[str, Any]:
    # Recompute the live outstanding-tickets aggregate before returning.
    recompute_outstanding_tickets_total(fest["id"])
    return {
        "id": fest["id"],
        "name": fest.get("name"),
        "venue_name": fest.get("venue_name"),
        "start_time": fest.get("start_time"),
        "end_time": fest.get("end_time"),
        "festival_day_count": fest.get("festival_day_count"),
        "status": fest.get("status"),
        "current_program_version_id": fest.get("current_program_version_id"),
        "clock_offset_seconds": fest.get("clock_offset_seconds", 0),
        "outstanding_tickets_total": fest.get("outstanding_tickets_total", 0),
        "created_at": fest.get("created_at"),
        "updated_at": fest.get("updated_at"),
        "version": fest.get("version"),
    }


@bp.route("/festivals", methods=["POST"])
def create_festival():
    require_role(["FestivalProducer", "PlatformAdmin"])
    body = get_json_body()
    # Catch the priority-30 invalid-window check before the catch-all body
    # check by extracting the two times manually so the error id is correct.
    if "start_time" not in body or "end_time" not in body:
        raise ApiError(
            "ERR_INVALID_FESTIVAL_WINDOW",
            "start_time and end_time are required on a festival create",
        )
    s_raw, e_raw = body["start_time"], body["end_time"]
    if (
        not isinstance(s_raw, int)
        or isinstance(s_raw, bool)
        or not isinstance(e_raw, int)
        or isinstance(e_raw, bool)
    ):
        raise ApiError(
            "ERR_INVALID_FESTIVAL_WINDOW",
            "start_time and end_time must be Unix-seconds integers",
        )
    _validate_festival_window(int(s_raw), int(e_raw))

    name = require_str(body, "name")
    venue_name = require_str(body, "venue_name")
    start_time = int(s_raw)
    end_time = int(e_raw)

    fest = {
        "name": name,
        "venue_name": venue_name,
        "start_time": start_time,
        "end_time": end_time,
        "festival_day_count": festival_day_count(start_time, end_time),
        "status": "PLANNED",
        "current_program_version_id": None,
        "clock_offset_seconds": 0,
        "outstanding_tickets_total": 0,
    }
    stamp_create(fest)
    with GLOBAL_LOCK:
        DB.festivals[fest["id"]] = fest
        append_audit(
            festival_id=fest["id"],
            event_category="STATE_TRANSITION",
            subject_entity_type="Festival",
            subject_entity_id=fest["id"],
            from_state=None,
            to_state="PLANNED",
            payload_summary="festival created",
        )
    return success_envelope(_festival_payload(fest), http_status=201)


@bp.route("/festivals", methods=["GET"])
def list_festivals():
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        rows = list_by_predicate(DB.festivals, lambda r: True)
        page, meta = paginate_list(rows, request.args)
        payload = [_festival_payload(r) for r in page]
    return success_envelope(payload, http_status=200, pagination=meta)


@bp.route("/festivals/<festival_id>", methods=["GET"])
def read_festival(festival_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        fest = resolve_festival(festival_id)
        payload = _festival_payload(fest)
    return success_envelope(payload, http_status=200)


@bp.route("/festivals/<festival_id>", methods=["PATCH"])
def patch_festival(festival_id: str):
    require_role(["FestivalProducer", "PlatformAdmin"])
    body = get_json_body()
    with GLOBAL_LOCK:
        fest = resolve_festival(festival_id)
        check_if_match(fest, if_match_header())
        s = body.get("start_time", fest["start_time"])
        e = body.get("end_time", fest["end_time"])
        if "start_time" in body or "end_time" in body:
            if (
                not isinstance(s, int)
                or isinstance(s, bool)
                or not isinstance(e, int)
                or isinstance(e, bool)
            ):
                raise ApiError(
                    "ERR_INVALID_FESTIVAL_WINDOW",
                    "start_time and end_time must be integers",
                )
            _validate_festival_window(int(s), int(e))
            fest["start_time"] = int(s)
            fest["end_time"] = int(e)
            fest["festival_day_count"] = festival_day_count(int(s), int(e))
        if "name" in body:
            fest["name"] = require_str({"name": body["name"]}, "name")
        if "venue_name" in body:
            fest["venue_name"] = require_str(
                {"venue_name": body["venue_name"]}, "venue_name"
            )
        stamp_update(fest)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="Festival",
            subject_entity_id=festival_id,
            payload_summary="festival fields patched",
        )
        payload = _festival_payload(fest)
    return success_envelope(payload, http_status=200)


@bp.route("/festivals/<festival_id>/open-scheduling", methods=["POST"])
def open_scheduling(festival_id: str):
    require_role(["FestivalProducer"])
    with GLOBAL_LOCK:
        fest = resolve_festival(festival_id)
        if fest.get("status") != "PLANNED":
            raise ApiError(
                "ERR_FESTIVAL_NOT_SCHEDULING_OR_PUBLISHED",
                f"festival is in {fest.get('status')!r}, expected PLANNED",
            )
        fest["status"] = "SCHEDULING"
        stamp_update(fest)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="Festival",
            subject_entity_id=festival_id,
            from_state="PLANNED",
            to_state="SCHEDULING",
            payload_summary="festival opened for scheduling",
        )
        payload = _festival_payload(fest)
    return success_envelope(payload, http_status=200)


@bp.route("/festivals/<festival_id>/cancel", methods=["POST"])
def hard_cancel_festival(festival_id: str):
    # Both FestivalProducer and PlatformAdmin per the role matrix.
    require_role(["FestivalProducer", "PlatformAdmin"])
    body = get_json_body()
    reason = optional_str(body, "reason", default="")
    with GLOBAL_LOCK:
        fest = resolve_festival(festival_id)
        prior = fest.get("status")
        if prior in ("CLOSED", "CANCELLED"):
            raise ApiError(
                "ERR_FESTIVAL_ALREADY_CLOSED",
                f"festival is already in terminal state {prior!r}",
            )
        check_if_match(fest, if_match_header())
        fest["status"] = "CANCELLED"
        stamp_update(fest)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="Festival",
            subject_entity_id=festival_id,
            from_state=prior,
            to_state="CANCELLED",
            payload_summary=f"festival hard-cancelled, reason: {reason!r}",
        )
        counts = festival_cancel_fanout(fest, reason or "")
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="Festival",
            subject_entity_id=festival_id,
            payload_summary=(
                f"festival-cancel fan-out counts: "
                f"items_cancelled={counts['items_cancelled']}, "
                f"rehearsals_cancelled={counts['rehearsals_cancelled']}, "
                f"ticket_types_withdrawn={counts['ticket_types_withdrawn']}, "
                f"allocations_voided={counts['allocations_voided']}"
            ),
        )
        recompute_outstanding_tickets_total(festival_id)
        payload = _festival_payload(fest)
    return success_envelope(payload, http_status=200)


def register(app: Flask) -> None:
    app.register_blueprint(bp)
