"""ScheduleChange endpoints per PRD §3.4 and §4."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from flask import Flask, request

from ._common import (
    ANY_ROLE,
    ApiError,
    DB,
    GLOBAL_LOCK,
    actor_tuple,
    append_audit,
    append_occ_conflict,
    apply_provisional_refunds_for_cancel,
    assert_within_festival_window,
    cascade_program_item_cancel,
    check_artist_multi_festival_conflict,
    check_artist_self_overlap,
    check_artist_travel_buffer,
    check_equipment_kit_capacity,
    check_if_match,
    check_stage_changeover_overlap,
    fresh_uuid,
    get_json_body,
    idempotency_lookup_or_store,
    if_match_header,
    list_by_predicate,
    logical_now_iso,
    make_blueprint,
    optional_str,
    paginate_list,
    recompute_outstanding_tickets_total,
    recompute_slot_priority,
    recompute_tier_projection,
    require_dict,
    require_enum,
    require_int,
    require_role,
    require_str,
    resolve_festival,
    revert_provisional_refunds,
    seed_sync_envelopes,
    server_now_iso8601,
    stamp_create,
    stamp_update,
    success_envelope,
)


bp = make_blueprint("schedule_changes")


_KINDS = ("ITEM_CANCEL", "ITEM_RESCHEDULE", "STAGE_SWAP", "VERSION_PUBLISH", "TICKET_NOTIFY")


def _payload(sc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": sc["id"],
        "festival_id": sc.get("festival_id"),
        "change_kind": sc.get("change_kind"),
        "target_program_item_id": sc.get("target_program_item_id"),
        "payload": sc.get("payload"),
        "status": sc.get("status"),
        "applied_at": sc.get("applied_at"),
        "sync_envelopes": list(sc.get("sync_envelopes", []) or []),
        "provisional_refund_cents_total": sc.get("provisional_refund_cents_total"),
        "final_refund_cents_total": sc.get("final_refund_cents_total"),
        "idempotency_key": sc.get("idempotency_key"),
        "created_at": sc.get("created_at"),
        "updated_at": sc.get("updated_at"),
        "version": sc.get("version"),
    }


def _resolve(festival_id: str, change_id: str) -> Dict[str, Any]:
    resolve_festival(festival_id)
    sc = DB.schedule_changes.get(change_id)
    if sc is None:
        raise ApiError(
            "ERR_SCHEDULE_CHANGE_NOT_FOUND", f"schedule change {change_id} not found"
        )
    if sc.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT",
            "schedule change belongs to a different festival",
        )
    return sc


def _validate_payload_for_kind(kind: str, payload_obj: Any) -> Dict[str, Any]:
    if payload_obj is None:
        payload_obj = {}
    if not isinstance(payload_obj, dict):
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", "schedule-change payload must be an object or null"
        )
    if kind == "ITEM_CANCEL":
        reason = payload_obj.get("reason", "")
        if reason is not None and not isinstance(reason, str):
            raise ApiError(
                "ERR_INVALID_FIELD_VALUE", "ITEM_CANCEL payload.reason must be a string"
            )
        return {"reason": reason or ""}
    if kind == "ITEM_RESCHEDULE":
        ns = payload_obj.get("new_start_time")
        ne = payload_obj.get("new_end_time")
        if (
            not isinstance(ns, int)
            or isinstance(ns, bool)
            or ns <= 0
            or not isinstance(ne, int)
            or isinstance(ne, bool)
            or ne <= 0
            or ne <= ns
        ):
            raise ApiError(
                "ERR_INVALID_FIELD_VALUE",
                "ITEM_RESCHEDULE payload requires positive new_start_time < new_end_time",
            )
        return {"new_start_time": int(ns), "new_end_time": int(ne)}
    if kind == "STAGE_SWAP":
        nsid = payload_obj.get("new_stage_id")
        if not isinstance(nsid, str) or nsid == "":
            raise ApiError(
                "ERR_INVALID_FIELD_VALUE",
                "STAGE_SWAP payload requires a non-empty new_stage_id string",
            )
        return {"new_stage_id": nsid}
    if kind == "TICKET_NOTIFY":
        msg = payload_obj.get("message", "")
        if msg is not None and not isinstance(msg, str):
            raise ApiError(
                "ERR_INVALID_FIELD_VALUE", "TICKET_NOTIFY payload.message must be a string"
            )
        return {"message": msg or ""}
    if kind == "VERSION_PUBLISH":
        pvid = payload_obj.get("program_version_id", "")
        if pvid is not None and not isinstance(pvid, str):
            raise ApiError(
                "ERR_INVALID_FIELD_VALUE",
                "VERSION_PUBLISH payload.program_version_id must be a string",
            )
        return {"program_version_id": pvid or ""}
    raise ApiError("ERR_INVALID_FIELD_VALUE", f"unknown change_kind {kind!r}")


@bp.route("/festivals/<festival_id>/schedule-changes", methods=["POST"])
def create_change(festival_id: str):
    require_role(["FestivalProducer"])
    body = get_json_body()
    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        idempotency_key = body.get("idempotency_key")
        if idempotency_key is not None and not isinstance(idempotency_key, str):
            raise ApiError(
                "ERR_INVALID_FIELD_VALUE",
                "idempotency_key must be a string when present",
            )
        replay, store_cb = idempotency_lookup_or_store(
            endpoint_label="POST /schedule-changes",
            idempotency_key=idempotency_key,
            body=body,
            festival_for_clock=festival,
        )
        if replay is not None:
            return replay

        kind = require_enum(body, "change_kind", _KINDS)
        target_id = body.get("target_program_item_id")
        if kind in ("ITEM_CANCEL", "ITEM_RESCHEDULE", "STAGE_SWAP"):
            if not isinstance(target_id, str) or target_id == "":
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE",
                    f"{kind} requires target_program_item_id",
                )
            pi = DB.program_items.get(target_id)
            if pi is None:
                raise ApiError(
                    "ERR_PROGRAM_ITEM_NOT_FOUND",
                    f"target program item {target_id} not found",
                )
            if pi.get("festival_id") != festival_id:
                raise ApiError(
                    "ERR_RESOURCE_MISMATCHED_PARENT",
                    "target program item is in a different festival",
                )
        else:
            # VERSION_PUBLISH and TICKET_NOTIFY are festival-level when
            # `target_program_item_id` is null.  When supplied, it must
            # still resolve (the TICKET_NOTIFY-of-a-specific-item case).
            if target_id is not None and not isinstance(target_id, str):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE",
                    "target_program_item_id must be a string or null",
                )
            if isinstance(target_id, str) and target_id != "":
                pi = DB.program_items.get(target_id)
                if pi is None:
                    raise ApiError(
                        "ERR_PROGRAM_ITEM_NOT_FOUND",
                        f"target program item {target_id} not found",
                    )

        payload_obj = _validate_payload_for_kind(kind, body.get("payload"))

        row = {
            "festival_id": festival_id,
            "change_kind": kind,
            "target_program_item_id": target_id if isinstance(target_id, str) else None,
            "payload": payload_obj,
            "status": "PROPOSED",
            "applied_at": None,
            "sync_envelopes": [],
            "provisional_refund_cents_total": 0,
            "final_refund_cents_total": None,
            "idempotency_key": idempotency_key,
        }
        stamp_create(row)
        DB.schedule_changes[row["id"]] = row
        append_audit(
            festival_id=festival_id,
            event_category="SCHEDULE_CHANGE",
            subject_entity_type="ScheduleChange",
            subject_entity_id=row["id"],
            to_state="PROPOSED",
            payload_summary=f"schedule change proposed ({kind})",
        )
        resp = success_envelope(_payload(row), http_status=201)
        if store_cb is not None:
            store_cb(resp.status_code, json.loads(resp.get_data(as_text=True)))
    return resp


@bp.route("/festivals/<festival_id>/schedule-changes", methods=["GET"])
def list_changes(festival_id: str):
    require_role(ANY_ROLE)
    status_f = request.args.get("status")
    kind_f = request.args.get("change_kind")
    target_f = request.args.get("target_program_item_id")
    with GLOBAL_LOCK:
        resolve_festival(festival_id)

        def _pred(r: dict) -> bool:
            if r.get("festival_id") != festival_id:
                return False
            if status_f is not None and r.get("status") != status_f:
                return False
            if kind_f is not None and r.get("change_kind") != kind_f:
                return False
            if target_f is not None and r.get("target_program_item_id") != target_f:
                return False
            return True

        rows = list_by_predicate(DB.schedule_changes, _pred)
        page, meta = paginate_list(rows, request.args)
        out = [_payload(r) for r in page]
    return success_envelope(out, pagination=meta)


@bp.route("/festivals/<festival_id>/schedule-changes/<change_id>", methods=["GET"])
def read_change(festival_id: str, change_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        sc = _resolve(festival_id, change_id)
        out = _payload(sc)
    return success_envelope(out)


def _apply_item_cancel(sc: Dict[str, Any], festival: Dict[str, Any]) -> Dict[str, Any]:
    """ITEM_CANCEL apply side-effects, returning a counts dict for the audit."""
    target_id = sc["target_program_item_id"]
    pi = DB.program_items.get(target_id)
    if pi is None:
        raise ApiError(
            "ERR_PROGRAM_ITEM_NOT_FOUND",
            f"target program item {target_id} not found at apply time",
        )
    if pi.get("status") in ("CANCELLED", "ON_STAGE", "PERFORMED"):
        raise ApiError(
            "ERR_PROGRAM_ITEM_ALREADY_CANCELLED",
            f"target item is in {pi.get('status')!r}",
        )
    prior = pi.get("status")
    sc["_prior_program_item_status"] = prior
    pi["status"] = "CANCELLED"
    stamp_update(pi)
    append_audit(
        festival_id=festival["id"],
        event_category="STATE_TRANSITION",
        subject_entity_type="ProgramItem",
        subject_entity_id=target_id,
        from_state=prior,
        to_state="CANCELLED",
        payload_summary=(
            f"program item cancelled via ITEM_CANCEL schedule-change {sc['id']}"
        ),
        actor_user_id=actor_tuple()[0],
        actor_role=actor_tuple()[1],
    )
    actor_id, actor_role = actor_tuple()
    counts = cascade_program_item_cancel(
        festival["id"],
        target_id,
        actor_user_id=actor_id,
        actor_role=actor_role,
        summary_prefix="ITEM_CANCEL apply",
    )
    provisional_total = apply_provisional_refunds_for_cancel(
        festival, target_id, sc["id"]
    )
    sc["provisional_refund_cents_total"] = int(provisional_total)
    recompute_outstanding_tickets_total(festival["id"])
    return {
        "slots_cancelled": counts["slots_cancelled"],
        "teams_freed": counts["teams_freed"],
        "allocations_voided": counts["allocations_voided"],
        "provisional_refund_cents_total": int(provisional_total),
    }


def _apply_item_reschedule(sc: Dict[str, Any], festival: Dict[str, Any]) -> Dict[str, Any]:
    target_id = sc["target_program_item_id"]
    pi = DB.program_items.get(target_id)
    if pi is None:
        raise ApiError(
            "ERR_PROGRAM_ITEM_NOT_FOUND", f"target {target_id} not found"
        )
    payload = sc["payload"]
    new_start = int(payload["new_start_time"])
    new_end = int(payload["new_end_time"])
    assert_within_festival_window(festival, new_start, new_end)

    stage = DB.stages.get(pi.get("stage_id"))
    if stage is None:
        raise ApiError(
            "ERR_STAGE_NOT_FOUND", f"stage {pi.get('stage_id')} not found"
        )

    artist = DB.artists.get(pi.get("artist_id"))
    if artist is None:
        raise ApiError(
            "ERR_ARTIST_NOT_FOUND", f"artist {pi.get('artist_id')} not found"
        )

    # Run the standard confirm-style check stack against the new window.
    check_equipment_kit_capacity(
        festival["id"],
        list(pi.get("equipment_kit_codes", []) or []),
        new_start,
        new_end,
        pi["stage_id"],
        exclude_item_id=target_id,
    )
    check_stage_changeover_overlap(
        festival["id"],
        pi["stage_id"],
        new_start,
        new_end,
        stage.get("changeover_buffer_seconds"),
        exclude_item_id=target_id,
    )
    check_artist_multi_festival_conflict(artist, new_start, new_end)
    check_artist_travel_buffer(artist, new_start)
    check_artist_self_overlap(
        pi["artist_id"], new_start, new_end, exclude_program_item_id=target_id
    )

    prior_window = (pi["start_time"], pi["end_time"])
    pi["start_time"] = new_start
    pi["end_time"] = new_end
    stamp_update(pi)
    recompute_slot_priority(pi)
    append_audit(
        festival_id=festival["id"],
        event_category="SCHEDULE_CHANGE",
        subject_entity_type="ProgramItem",
        subject_entity_id=target_id,
        payload_summary=(
            f"ITEM_RESCHEDULE applied: window {prior_window} → ({new_start},{new_end})"
        ),
    )
    return {"new_start_time": new_start, "new_end_time": new_end}


def _apply_stage_swap(sc: Dict[str, Any], festival: Dict[str, Any]) -> Dict[str, Any]:
    target_id = sc["target_program_item_id"]
    pi = DB.program_items.get(target_id)
    if pi is None:
        raise ApiError("ERR_PROGRAM_ITEM_NOT_FOUND", f"target {target_id} not found")
    new_stage_id = sc["payload"]["new_stage_id"]
    new_stage = DB.stages.get(new_stage_id)
    if new_stage is None:
        raise ApiError("ERR_STAGE_NOT_FOUND", f"stage {new_stage_id} not found")
    if new_stage.get("festival_id") != festival["id"]:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT",
            "new stage is in a different festival",
        )
    # Wireability against the kit list.
    stage_kits = set(new_stage.get("equipment_kits", []))
    for c in pi.get("equipment_kit_codes", []) or []:
        if c not in stage_kits:
            raise ApiError(
                "ERR_STAGE_LACKS_EQUIPMENT_KIT",
                f"new stage is not wired for kit {c!r}",
            )
    # Changeover-buffer on the new stage.
    check_stage_changeover_overlap(
        festival["id"],
        new_stage_id,
        int(pi["start_time"]),
        int(pi["end_time"]),
        new_stage.get("changeover_buffer_seconds"),
        exclude_item_id=target_id,
    )
    prior_stage = pi["stage_id"]
    pi["stage_id"] = new_stage_id
    stamp_update(pi)
    append_audit(
        festival_id=festival["id"],
        event_category="SCHEDULE_CHANGE",
        subject_entity_type="ProgramItem",
        subject_entity_id=target_id,
        payload_summary=f"STAGE_SWAP applied: stage {prior_stage} → {new_stage_id}",
    )
    return {"prior_stage_id": prior_stage, "new_stage_id": new_stage_id}


@bp.route(
    "/festivals/<festival_id>/schedule-changes/<change_id>/apply", methods=["POST"]
)
def apply_change(festival_id: str, change_id: str):
    require_role(["FestivalProducer"])
    body = get_json_body()
    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        sc = _resolve(festival_id, change_id)

        # Idempotency on the apply body using the change's original key.
        idempotency_key = body.get("idempotency_key") or sc.get("idempotency_key")
        if idempotency_key is not None and not isinstance(idempotency_key, str):
            raise ApiError(
                "ERR_INVALID_FIELD_VALUE",
                "idempotency_key must be a string when present",
            )
        replay, store_cb = idempotency_lookup_or_store(
            endpoint_label="POST /schedule-changes/apply",
            idempotency_key=idempotency_key,
            body={"change_id": change_id, "body": body},
            festival_for_clock=festival,
        )
        if replay is not None:
            return replay

        if sc.get("status") != "PROPOSED":
            append_occ_conflict(
                festival_id=festival_id,
                subject_entity_type="ScheduleChange",
                subject_entity_id=change_id,
                payload_summary=f"apply lost CAS race; observed status {sc.get('status')!r}",
            )
            raise ApiError(
                "ERR_CHANGE_NOT_PROPOSED",
                f"change is in {sc.get('status')!r}, must be PROPOSED to apply",
            )

        check_if_match(sc, if_match_header())

        kind = sc["change_kind"]
        cascade_summary: Dict[str, Any] = {}
        if kind == "ITEM_CANCEL":
            cascade_summary = _apply_item_cancel(sc, festival)
        elif kind == "ITEM_RESCHEDULE":
            cascade_summary = _apply_item_reschedule(sc, festival)
        elif kind == "STAGE_SWAP":
            cascade_summary = _apply_stage_swap(sc, festival)
        elif kind == "TICKET_NOTIFY":
            cascade_summary = {"message": sc["payload"].get("message", "")}
        elif kind == "VERSION_PUBLISH":
            # Conceptually emitted by the publish path itself; an explicit
            # apply here is the no-op-fanout variant the PRD allows for
            # consistency.
            cascade_summary = {
                "program_version_id": sc["payload"].get("program_version_id")
            }

        seed_sync_envelopes(sc, {"id": change_id, "kind": kind, "summary": cascade_summary})
        sc["status"] = "APPLIED"
        sc["applied_at"] = logical_now_iso(festival)
        stamp_update(sc)
        append_audit(
            festival_id=festival_id,
            event_category="SCHEDULE_CHANGE",
            subject_entity_type="ScheduleChange",
            subject_entity_id=change_id,
            from_state="PROPOSED",
            to_state="APPLIED",
            payload_summary=(
                f"schedule change applied ({kind}); cascade summary: {cascade_summary}"
            ),
        )
        resp = success_envelope(_payload(sc), http_status=200)
        if store_cb is not None:
            store_cb(resp.status_code, json.loads(resp.get_data(as_text=True)))
    return resp


@bp.route(
    "/festivals/<festival_id>/schedule-changes/<change_id>/reject", methods=["POST"]
)
def reject_change(festival_id: str, change_id: str):
    require_role(["FestivalProducer"])
    body = get_json_body()
    if not body.get("reason"):
        raise ApiError("ERR_MISSING_REJECTION_REASON", "reject requires a `reason` string")
    reason = require_str(body, "reason")
    with GLOBAL_LOCK:
        sc = _resolve(festival_id, change_id)
        check_if_match(sc, if_match_header())
        if sc.get("status") != "PROPOSED":
            append_occ_conflict(
                festival_id=festival_id,
                subject_entity_type="ScheduleChange",
                subject_entity_id=change_id,
                payload_summary="reject lost CAS race against apply or another reject",
            )
            raise ApiError(
                "ERR_CHANGE_NOT_PROPOSED",
                f"change is in {sc.get('status')!r}, cannot reject",
            )
        sc["status"] = "REJECTED"
        stamp_update(sc)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="ScheduleChange",
            subject_entity_id=change_id,
            from_state="PROPOSED",
            to_state="REJECTED",
            payload_summary=f"change rejected, reason: {reason!r}",
        )
        out = _payload(sc)
    return success_envelope(out)


@bp.route(
    "/festivals/<festival_id>/schedule-changes/<change_id>/revert", methods=["POST"]
)
def revert_change(festival_id: str, change_id: str):
    require_role(["FestivalProducer"])
    with GLOBAL_LOCK:
        sc = _resolve(festival_id, change_id)
        check_if_match(sc, if_match_header())
        if sc.get("status") != "APPLIED":
            raise ApiError(
                "ERR_CHANGE_NOT_APPLIED",
                f"change is in {sc.get('status')!r}, cannot revert",
            )
        envs = sc.get("sync_envelopes") or []
        any_acked = any(e.get("status") == "ACKNOWLEDGED" for e in envs)
        if any_acked:
            raise ApiError(
                "ERR_CHANGE_ALREADY_ACKED",
                "at least one sync envelope is ACKNOWLEDGED; revert is not allowed",
            )
        # Flip all QUEUED envelopes to CANCELLED.
        for e in envs:
            if e.get("status") == "QUEUED":
                e["status"] = "CANCELLED"
                e["acked_at"] = server_now_iso8601()
        # Inverse cascade for ITEM_CANCEL: restore the program item's prior status.
        kind = sc.get("change_kind")
        if kind == "ITEM_CANCEL":
            target_id = sc.get("target_program_item_id")
            prior_status = sc.get("_prior_program_item_status") or "PROPOSED"
            pi = DB.program_items.get(target_id) if target_id else None
            if pi is not None and pi.get("status") == "CANCELLED":
                pi["status"] = prior_status
                stamp_update(pi)
                append_audit(
                    festival_id=festival_id,
                    event_category="STATE_TRANSITION",
                    subject_entity_type="ProgramItem",
                    subject_entity_id=target_id,
                    from_state="CANCELLED",
                    to_state=prior_status,
                    payload_summary=(
                        f"program item restored to {prior_status} on revert of change {change_id}"
                    ),
                )
            # Wipe the provisional refund buckets attributed to this change.
            revert_provisional_refunds(change_id, festival_id)
            # Restore the festival's outstanding-tickets aggregate (already
            # invariant under the apply-revert pair per the §1.8 conservation
            # rule, but the recompute call is the standard refresh hook).
            recompute_outstanding_tickets_total(festival_id)
            # Sponsor tiers whose allocations were voided in cascade B
            # are not auto-reinstated per the PRD §3.4 prose: "Sound-check
            # cancellations are NOT auto-reinstated".  The same applies
            # to the exposure-allocation void cascade B: the operator
            # decides whether to re-create the voided allocations.
        elif kind == "ITEM_RESCHEDULE":
            # The PRD does not pin a specific inverse for ITEM_RESCHEDULE
            # in the revert prose ("the apply's side-effects are undone"
            # is the high-level claim).  Without a stored prior_window,
            # the revert flips the envelope statuses only; the operator
            # is expected to issue a follow-up ITEM_RESCHEDULE pointing
            # at the original window.
            pass
        elif kind == "STAGE_SWAP":
            # Same comment as ITEM_RESCHEDULE: no stored prior_stage_id
            # is restored; the operator issues a follow-up STAGE_SWAP if
            # the reversion of the stage swap is desired.
            pass
        sc["status"] = "REVERTED"
        stamp_update(sc)
        append_audit(
            festival_id=festival_id,
            event_category="SCHEDULE_CHANGE",
            subject_entity_type="ScheduleChange",
            subject_entity_id=change_id,
            from_state="APPLIED",
            to_state="REVERTED",
            payload_summary='"reverted"',
        )
        out = _payload(sc)
    return success_envelope(out)


def register(app: Flask) -> None:
    app.register_blueprint(bp)
