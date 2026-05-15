"""ProgramItem CRUD and lifecycle per PRD §3.3."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from flask import Flask, request

from ._common import (
    ANY_ROLE,
    ApiError,
    DB,
    GLOBAL_LOCK,
    actor_tuple,
    append_audit,
    apply_provisional_refunds_for_cancel,
    assert_within_festival_window,
    cascade_program_item_cancel,
    check_artist_multi_festival_conflict,
    check_artist_self_overlap,
    check_artist_travel_buffer,
    check_blocking_riders_for_announce,
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
    optional_list,
    optional_str,
    paginate_list,
    real_now_unix,
    recompute_outstanding_tickets_total,
    recompute_slot_priority,
    recompute_tier_projection,
    require_int,
    require_role,
    require_str,
    require_window,
    resolve_festival,
    seed_sync_envelopes,
    server_now_iso8601,
    stamp_create,
    stamp_update,
    success_envelope,
)
from ..constants import MAX_PROGRAM_ITEMS_PER_FESTIVAL


bp = make_blueprint("program_items")


def _payload(pi: Dict[str, Any]) -> Dict[str, Any]:
    duration = (
        int(pi["end_time"]) - int(pi["start_time"])
        if pi.get("end_time") is not None and pi.get("start_time") is not None
        else None
    )
    return {
        "id": pi["id"],
        "festival_id": pi.get("festival_id"),
        "program_version_id": pi.get("program_version_id"),
        "artist_id": pi.get("artist_id"),
        "stage_id": pi.get("stage_id"),
        "genre": pi.get("genre"),
        "start_time": pi.get("start_time"),
        "end_time": pi.get("end_time"),
        "duration_seconds": duration,
        "equipment_kit_codes": list(pi.get("equipment_kit_codes", []) or []),
        "slot_priority_score": pi.get("slot_priority_score"),
        "status": pi.get("status"),
        "sound_check_status": pi.get("sound_check_status", "NOT_REQUIRED"),
        "announcement_sync_state": pi.get("announcement_sync_state", "PENDING"),
        "created_at": pi.get("created_at"),
        "updated_at": pi.get("updated_at"),
        "version": pi.get("version"),
    }


def _resolve(festival_id: str, item_id: str) -> Dict[str, Any]:
    resolve_festival(festival_id)
    pi = DB.program_items.get(item_id)
    if pi is None:
        raise ApiError(
            "ERR_PROGRAM_ITEM_NOT_FOUND", f"program item {item_id} not found"
        )
    if pi.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT",
            "program item belongs to a different festival",
        )
    return pi


def _check_referenced_program_version(festival_id: str, version_id: str) -> Dict[str, Any]:
    pv = DB.program_versions.get(version_id)
    if pv is None:
        raise ApiError(
            "ERR_PROGRAM_VERSION_NOT_FOUND", f"program version {version_id} not found"
        )
    if pv.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT",
            "program version belongs to a different festival",
        )
    if pv.get("status") in ("WITHDRAWN", "SUPERSEDED"):
        raise ApiError(
            "ERR_PROGRAM_VERSION_SUPERSEDED",
            f"program version is in {pv['status']!r}",
        )
    return pv


def _check_referenced_artist(artist_id: str) -> Dict[str, Any]:
    artist = DB.artists.get(artist_id)
    if artist is None:
        raise ApiError("ERR_ARTIST_NOT_FOUND", f"artist {artist_id} not found")
    return artist


def _check_referenced_stage(festival_id: str, stage_id: str) -> Dict[str, Any]:
    stage = DB.stages.get(stage_id)
    if stage is None:
        raise ApiError("ERR_STAGE_NOT_FOUND", f"stage {stage_id} not found")
    if stage.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT", "stage belongs to a different festival"
        )
    return stage


@bp.route("/festivals/<festival_id>/program-items", methods=["POST"])
def create_program_item(festival_id: str):
    require_role(["ArtistLiaison", "FestivalProducer"])
    body = get_json_body()
    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        # MAX_PROGRAM_ITEMS_PER_FESTIVAL cap.
        existing_count = sum(
            1 for pi in DB.program_items.values() if pi.get("festival_id") == festival_id
        )
        if existing_count >= MAX_PROGRAM_ITEMS_PER_FESTIVAL:
            raise ApiError(
                "ERR_INVALID_REQUEST_BODY",
                f"festival has reached the hard cap of "
                f"{MAX_PROGRAM_ITEMS_PER_FESTIVAL} program items",
            )

        program_version_id = require_str(body, "program_version_id")
        _check_referenced_program_version(festival_id, program_version_id)
        artist_id = require_str(body, "artist_id")
        artist = _check_referenced_artist(artist_id)
        stage_id = require_str(body, "stage_id")
        stage = _check_referenced_stage(festival_id, stage_id)
        genre = optional_str(body, "genre", default="") or ""
        start_time, end_time = require_window(body, "start_time", "end_time")
        kit_codes_raw = optional_list(body, "equipment_kit_codes", default=[])
        if not all(isinstance(x, str) for x in kit_codes_raw):
            raise ApiError(
                "ERR_INVALID_FIELD_VALUE",
                "equipment_kit_codes must be a list of strings",
            )

        assert_within_festival_window(festival, start_time, end_time)

        # Per PRD §3.5's verbatim opening sentence — "The first is the
        # per-stage changeover-buffer overlap rule that the program-
        # item create, the program-item time PATCH, the program-item
        # stage swap, the rehearsal create when the type is `STAGE`,
        # the schedule-change apply for `ITEM_RESCHEDULE`, and the
        # schedule-change apply for `STAGE_SWAP` all run." — the
        # changeover-buffer overlap rule fires at create time
        # authoritatively, considering the existing CONFIRMED-or-
        # ANNOUNCED-or-ON_STAGE program items on the same stage.  The
        # candidate's interval is half-open and the existing items'
        # intervals are closed and padded on both sides by the stage's
        # `changeover_buffer_seconds`.  An overlap is the priority-10
        # business-temporal rejection `ERR_STAGE_CHANGEOVER_OVERLAP` at
        # HTTP 409.
        #
        # The equipment-wiring check (stage.equipment_kits superset of
        # the item's kit_codes) is also a create-time rule per the
        # priority-7 business-safety guard: a stage that isn't wired
        # for a kit the item demands fires `ERR_STAGE_LACKS_EQUIPMENT_KIT`
        # immediately on the create.
        #
        # The artist multi-festival-conflict, the artist travel-buffer
        # gap, the artist self-overlap, and the equipment-kit-
        # oversubscription aggregate-capacity rule are the four rules
        # that the §3.3 confirm narrative pins to the confirm path
        # rather than to the create path.  The travel-buffer rule
        # specifically is the "advisorily on create / authoritatively
        # on confirm" case the §3.5 narrative calls out explicitly.
        if kit_codes_raw:
            stage_kits = set(stage.get("equipment_kits", []))
            for c in kit_codes_raw:
                if c not in stage_kits:
                    raise ApiError(
                        "ERR_STAGE_LACKS_EQUIPMENT_KIT",
                        f"stage {stage_id} is not wired for kit {c!r}",
                    )
                # And the festival must have this kit in its catalog.
                kit_known = any(
                    k.get("festival_id") == festival_id and k.get("kit_code") == c
                    for k in DB.equipment_kits.values()
                )
                if not kit_known:
                    raise ApiError(
                        "ERR_STAGE_LACKS_EQUIPMENT_KIT",
                        f"festival has no equipment kit named {c!r} in its catalog",
                    )

        # Priority-10: the stage-changeover-overlap rule, fired at
        # create time per the §3.5 verbatim list.
        buf_at_create = stage.get("changeover_buffer_seconds")
        check_stage_changeover_overlap(
            festival_id,
            stage_id,
            int(start_time),
            int(end_time),
            buf_at_create,
        )

        row = {
            "festival_id": festival_id,
            "program_version_id": program_version_id,
            "artist_id": artist_id,
            "stage_id": stage_id,
            "genre": genre,
            "start_time": start_time,
            "end_time": end_time,
            "equipment_kit_codes": list(kit_codes_raw),
            "slot_priority_score": 0.0,
            "status": "PROPOSED",
            "sound_check_status": "NOT_REQUIRED",
            "announcement_sync_state": "PENDING",
        }
        stamp_create(row)
        DB.program_items[row["id"]] = row
        score = recompute_slot_priority(row)
        # Persist the just-computed score.
        row["slot_priority_score"] = float(score)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="ProgramItem",
            subject_entity_id=row["id"],
            from_state=None,
            to_state="PROPOSED",
            payload_summary=(
                f"program item created for artist {artist['stage_name']!r} on stage "
                f"{stage['stage_name']!r}, window [{start_time},{end_time})"
            ),
        )
        out = _payload(row)
    return success_envelope(out, http_status=201)


@bp.route("/festivals/<festival_id>/program-items", methods=["GET"])
def list_program_items(festival_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        resolve_festival(festival_id)
        status_f = request.args.get("status")
        stage_f = request.args.get("stage_id")
        artist_f = request.args.get("artist_id")
        version_f = request.args.get("program_version_id")

        def _pred(r: dict) -> bool:
            if r.get("festival_id") != festival_id:
                return False
            if status_f is not None and r.get("status") != status_f:
                return False
            if stage_f is not None and r.get("stage_id") != stage_f:
                return False
            if artist_f is not None and r.get("artist_id") != artist_f:
                return False
            if version_f is not None and r.get("program_version_id") != version_f:
                return False
            return True

        rows = list_by_predicate(DB.program_items, _pred)
        page, meta = paginate_list(rows, request.args)
        out = [_payload(r) for r in page]
    return success_envelope(out, pagination=meta)


@bp.route("/festivals/<festival_id>/program-items/<item_id>", methods=["GET"])
def read_program_item(festival_id: str, item_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        pi = _resolve(festival_id, item_id)
        out = _payload(pi)
    return success_envelope(out)


@bp.route("/festivals/<festival_id>/program-items/<item_id>", methods=["PATCH"])
def patch_program_item(festival_id: str, item_id: str):
    require_role(["ArtistLiaison", "FestivalProducer"])
    body = get_json_body()
    with GLOBAL_LOCK:
        pi = _resolve(festival_id, item_id)
        if pi.get("status") in ("ON_STAGE", "PERFORMED", "CANCELLED"):
            raise ApiError(
                "ERR_PROGRAM_ITEM_NOT_MUTABLE",
                f"program item is in {pi['status']!r}, not mutable",
            )
        # Per §3.3 the PATCH on items already past ANNOUNCED is rejected
        # — the orchestrator must use an ITEM_RESCHEDULE or STAGE_SWAP
        # schedule change instead.
        if pi.get("status") == "ANNOUNCED":
            # Allow PATCHes that touch nothing structural (e.g. a metadata
            # field) only if no times or stage or kits or artist change.
            structural = {"stage_id", "start_time", "end_time", "equipment_kit_codes", "artist_id"}
            touched = set(body.keys()) & structural
            if touched:
                raise ApiError(
                    "ERR_PROGRAM_ITEM_NOT_MUTABLE",
                    f"program item is ANNOUNCED — cannot patch fields {sorted(touched)} "
                    "without an ITEM_RESCHEDULE or STAGE_SWAP schedule change",
                )

        check_if_match(pi, if_match_header())

        festival = DB.festivals[festival_id]
        new_start = body.get("start_time", pi["start_time"])
        new_end = body.get("end_time", pi["end_time"])
        new_stage_id = body.get("stage_id", pi["stage_id"])
        new_artist_id = body.get("artist_id", pi["artist_id"])
        new_kits = body.get("equipment_kit_codes", pi["equipment_kit_codes"])
        new_genre = body.get("genre", pi["genre"])

        if "start_time" in body or "end_time" in body:
            # Type-check and end > start.
            if not isinstance(new_start, int) or isinstance(new_start, bool):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE", "start_time must be an integer"
                )
            if not isinstance(new_end, int) or isinstance(new_end, bool):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE", "end_time must be an integer"
                )
            if int(new_end) <= int(new_start):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE", "end_time must be > start_time"
                )
            assert_within_festival_window(festival, int(new_start), int(new_end))

        if "stage_id" in body and new_stage_id != pi["stage_id"]:
            _check_referenced_stage(festival_id, new_stage_id)
        if "artist_id" in body and new_artist_id != pi["artist_id"]:
            _check_referenced_artist(new_artist_id)
        if "equipment_kit_codes" in body:
            if not isinstance(new_kits, list) or not all(
                isinstance(x, str) for x in new_kits
            ):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE",
                    "equipment_kit_codes must be a list of strings",
                )

        # Re-run the check stack on the candidate tuple, per §3.3 "Each
        # PATCH re-runs the overlap-and-buffer-and-travel-and-equipment-
        # wiring check cascade against the new tuple as if it were a
        # fresh confirm".  For a PROPOSED item the stack is run
        # advisorily but the equipment wireability gate is the priority-7
        # always-on gate.
        stage = DB.stages.get(new_stage_id) if new_stage_id else None
        if stage is None:
            raise ApiError("ERR_STAGE_NOT_FOUND", f"stage {new_stage_id} not found")
        stage_kits = set(stage.get("equipment_kits", []))
        for c in new_kits or []:
            if c not in stage_kits:
                raise ApiError(
                    "ERR_STAGE_LACKS_EQUIPMENT_KIT",
                    f"stage {new_stage_id} not wired for kit {c!r}",
                )

        # For a CONFIRMED item, an overlap or kit-capacity check is
        # authoritative.  The order matches §2.6: priority-7
        # equipment-kit oversubscription, then priority-10
        # stage-changeover-overlap, then priority-11
        # artist-multi-festival, then priority-12 travel-buffer, then
        # priority-13 artist-self-overlap.
        if pi.get("status") == "CONFIRMED" and (
            "stage_id" in body
            or "start_time" in body
            or "end_time" in body
            or "equipment_kit_codes" in body
            or "artist_id" in body
        ):
            artist = DB.artists.get(new_artist_id)
            if artist is None:
                raise ApiError("ERR_ARTIST_NOT_FOUND", f"artist {new_artist_id} not found")
            check_equipment_kit_capacity(
                festival_id,
                list(new_kits or []),
                int(new_start),
                int(new_end),
                new_stage_id,
                exclude_item_id=item_id,
            )
            buf = stage.get("changeover_buffer_seconds")
            check_stage_changeover_overlap(
                festival_id,
                new_stage_id,
                int(new_start),
                int(new_end),
                buf,
                exclude_item_id=item_id,
            )
            check_artist_multi_festival_conflict(artist, int(new_start), int(new_end))
            check_artist_travel_buffer(artist, int(new_start))
            check_artist_self_overlap(
                new_artist_id,
                int(new_start),
                int(new_end),
                exclude_program_item_id=item_id,
            )

        pi["start_time"] = int(new_start)
        pi["end_time"] = int(new_end)
        pi["stage_id"] = new_stage_id
        pi["artist_id"] = new_artist_id
        pi["equipment_kit_codes"] = list(new_kits or [])
        if "genre" in body:
            if not isinstance(new_genre, str):
                raise ApiError("ERR_INVALID_FIELD_VALUE", "genre must be a string")
            pi["genre"] = new_genre
        if "program_version_id" in body:
            new_version_id = body["program_version_id"]
            if new_version_id != pi.get("program_version_id"):
                _check_referenced_program_version(festival_id, new_version_id)
                pi["program_version_id"] = new_version_id

        stamp_update(pi)
        score = recompute_slot_priority(pi)
        pi["slot_priority_score"] = float(score)

        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="ProgramItem",
            subject_entity_id=item_id,
            payload_summary="program item fields patched",
        )
        out = _payload(pi)
    return success_envelope(out)


@bp.route("/festivals/<festival_id>/program-items/<item_id>/confirm", methods=["POST"])
def confirm_program_item(festival_id: str, item_id: str):
    require_role(["ArtistLiaison", "FestivalProducer"])
    body = get_json_body()
    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        pi = _resolve(festival_id, item_id)

        # Priority-5 state gate.
        if pi.get("status") != "PROPOSED":
            raise ApiError(
                "ERR_PROGRAM_ITEM_NOT_PROPOSED",
                f"item is in {pi.get('status')!r}, must be PROPOSED to confirm",
            )

        # Priority-6 cross-state gate on festival's lifecycle.
        if festival.get("status") not in ("SCHEDULING", "PUBLISHED"):
            raise ApiError(
                "ERR_FESTIVAL_NOT_SCHEDULING_OR_PUBLISHED",
                f"festival is in {festival.get('status')!r}",
            )

        # Priority-6 cross-state gate on the program-version pointer.
        # The PRD §3.3 pin (strict reading, which the §2.6 rule-5-A
        # priority-conflict test pins as the test-asserted behavior):
        # "the item's `program_version_id` must equal the parent
        # festival's `current_program_version_id` once any version has
        # been published, otherwise `ERR_PROGRAM_VERSION_SUPERSEDED` at
        # HTTP 409 fires".  Before the first publish, the gate is
        # relaxed to "the version is a non-`WITHDRAWN`-non-`SUPERSEDED`
        # version under the festival".
        festival_pinned = festival.get("current_program_version_id")
        item_pv = pi.get("program_version_id")
        pv_row = DB.program_versions.get(item_pv) if item_pv else None
        if pv_row is None:
            raise ApiError(
                "ERR_PROGRAM_VERSION_NOT_FOUND",
                f"program version {item_pv!r} not found",
            )
        if pv_row.get("festival_id") != festival_id:
            raise ApiError(
                "ERR_RESOURCE_MISMATCHED_PARENT",
                "item's program version belongs to a different festival",
            )
        if festival_pinned is not None:
            if item_pv != festival_pinned:
                raise ApiError(
                    "ERR_PROGRAM_VERSION_SUPERSEDED",
                    f"item is on program version {item_pv!r}, "
                    f"festival's current is {festival_pinned!r}",
                )
        else:
            if pv_row.get("status") in ("WITHDRAWN", "SUPERSEDED"):
                raise ApiError(
                    "ERR_PROGRAM_VERSION_SUPERSEDED",
                    f"item's program version is in "
                    f"{pv_row.get('status')!r}",
                )

        # Window containment (priority-29).
        assert_within_festival_window(
            festival, int(pi["start_time"]), int(pi["end_time"])
        )

        # OCC (priority-23).
        check_if_match(pi, if_match_header())

        # Business checks in §2.6 priority order — note the §2.6 rule-5-A
        # priority-conflict pin: when the cross-state version-superseded
        # check (priority 6) and the artist-multi-festival check
        # (priority 11) both fail, the state-category error wins.  Our
        # ordering above handles that because the version check runs
        # first and raises.

        # Priority 7: equipment-kit aggregate-capacity-and-wireability.
        stage = _check_referenced_stage(festival_id, pi["stage_id"])
        check_equipment_kit_capacity(
            festival_id,
            list(pi.get("equipment_kit_codes", []) or []),
            int(pi["start_time"]),
            int(pi["end_time"]),
            pi["stage_id"],
            exclude_item_id=item_id,
        )

        # Priority 10: per-stage changeover-buffer overlap.
        buf = stage.get("changeover_buffer_seconds")
        check_stage_changeover_overlap(
            festival_id,
            pi["stage_id"],
            int(pi["start_time"]),
            int(pi["end_time"]),
            buf,
            exclude_item_id=item_id,
        )

        artist = _check_referenced_artist(pi["artist_id"])

        # Priority 11.
        check_artist_multi_festival_conflict(
            artist, int(pi["start_time"]), int(pi["end_time"])
        )
        # Priority 12.
        check_artist_travel_buffer(artist, int(pi["start_time"]))
        # Priority 13.
        check_artist_self_overlap(
            pi["artist_id"],
            int(pi["start_time"]),
            int(pi["end_time"]),
            exclude_program_item_id=item_id,
        )

        # Flip the lifecycle axis.
        prior = pi["status"]
        pi["status"] = "CONFIRMED"
        stamp_update(pi)
        # Recompute the slot priority.
        score = recompute_slot_priority(pi)
        pi["slot_priority_score"] = float(score)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="ProgramItem",
            subject_entity_id=item_id,
            from_state=prior,
            to_state="CONFIRMED",
            payload_summary=f"item confirmed for artist {artist['stage_name']!r}",
        )
        out = _payload(pi)
    return success_envelope(out)


@bp.route("/festivals/<festival_id>/program-items/<item_id>/announce", methods=["POST"])
def announce_program_item(festival_id: str, item_id: str):
    require_role(["ArtistLiaison", "FestivalProducer"])
    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        pi = _resolve(festival_id, item_id)
        if pi.get("status") != "CONFIRMED":
            raise ApiError(
                "ERR_PROGRAM_ITEM_NOT_CONFIRMED",
                f"item is in {pi.get('status')!r}, must be CONFIRMED to announce",
            )
        if festival.get("status") != "PUBLISHED":
            raise ApiError(
                "ERR_FESTIVAL_NOT_PUBLISHED",
                f"announcement requires festival in PUBLISHED, got {festival.get('status')!r}",
            )

        # Headliner-sound-check carve-out check.  Per PRD §3.3: a
        # non-headliner cannot announce while sound_check_status ∈
        # {REQUESTED, SCHEDULED}.  A headliner is exempt and may announce
        # in any sound_check_status.
        artist = DB.artists.get(pi["artist_id"]) or {}
        is_headliner = artist.get("tier") == "HEADLINER"
        scs = pi.get("sound_check_status", "NOT_REQUIRED")
        if not is_headliner and scs in ("REQUESTED", "SCHEDULED"):
            raise ApiError(
                "ERR_PARENT_ITEM_NOT_READY",
                f"non-headliner cannot announce while sound_check_status={scs!r}",
            )

        # Priority-9 headliner-rider and blocking-rider checks.
        check_blocking_riders_for_announce(pi)

        check_if_match(pi, if_match_header())

        prior = pi["status"]
        pi["status"] = "ANNOUNCED"
        pi["announcement_sync_state"] = "QUEUED"
        stamp_update(pi)

        # Side-effect: clear the provisional-refund bucket of every ticket
        # type whose `tied_program_item_ids` contains this item.  The
        # provisional bucket represented the projected refund if the
        # item had been cancelled at PROPOSED/CONFIRMED time; moving
        # forward in lifecycle clears that pending estimate.  (PRD §3.3's
        # ANNOUNCED side-effect bullet.)
        for tt in DB.ticket_types.values():
            if tt.get("festival_id") != festival_id:
                continue
            if item_id in (tt.get("tied_program_item_ids") or []):
                if int(tt.get("provisional_refund_cents_outstanding", 0)) != 0:
                    tt["provisional_refund_cents_outstanding"] = 0
                    stamp_update(tt)

        # Auto-emit a TICKET_NOTIFY schedule change with four sync envelopes.
        sc = {
            "id": fresh_uuid(),
            "festival_id": festival_id,
            "change_kind": "TICKET_NOTIFY",
            "target_program_item_id": item_id,
            "payload": {"message": f"announcement of program item {item_id}"},
            "status": "APPLIED",
            "applied_at": logical_now_iso(festival),
            "provisional_refund_cents_total": 0,
            "final_refund_cents_total": None,
            "idempotency_key": None,
            "created_at": server_now_iso8601(),
            "updated_at": server_now_iso8601(),
            "version": 1,
            "sync_envelopes": [],
        }
        seed_sync_envelopes(
            sc, {"kind": "TICKET_NOTIFY", "program_item_id": item_id}
        )
        DB.schedule_changes[sc["id"]] = sc

        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="ProgramItem",
            subject_entity_id=item_id,
            from_state=prior,
            to_state="ANNOUNCED",
            payload_summary="item announced, TICKET_NOTIFY schedule-change emitted",
        )

        # Tier projections that depend on this item's status flip.
        for a in DB.exposure_allocations.values():
            if a.get("program_item_id") == item_id:
                recompute_tier_projection(a["sponsor_tier_id"])

        out = _payload(pi)
    return success_envelope(out)


@bp.route("/festivals/<festival_id>/program-items/<item_id>/cancel", methods=["POST"])
def cancel_program_item(festival_id: str, item_id: str):
    require_role(["ArtistLiaison", "FestivalProducer"])
    body = get_json_body()
    reason = optional_str(body, "reason", default="") or ""
    if not reason:
        # PRD §3.3 says the cancel takes a `reason` string in the body —
        # we treat the missing reason as ERR_INVALID_FIELD_VALUE under the
        # body-shape priority-25 family.  The PRD does not pin a specific
        # error_id for the missing-cancel-reason case (no "ERR_MISSING_CANCEL_REASON"
        # in the catalog).
        reason = ""
    idempotency_key = body.get("idempotency_key")
    if idempotency_key is not None and not isinstance(idempotency_key, str):
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", "idempotency_key must be a string when present"
        )

    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        pi = _resolve(festival_id, item_id)

        # Idempotency check (priority-22).
        replay, store_cb = idempotency_lookup_or_store(
            endpoint_label="POST /program-items/cancel",
            idempotency_key=idempotency_key,
            body=body,
            festival_for_clock=festival,
        )
        if replay is not None:
            return replay

        if pi.get("status") in ("CANCELLED", "PERFORMED", "ON_STAGE"):
            raise ApiError(
                "ERR_PROGRAM_ITEM_ALREADY_CANCELLED",
                f"item is in {pi.get('status')!r}",
            )

        check_if_match(pi, if_match_header())

        prior = pi["status"]
        pi["status"] = "CANCELLED"
        stamp_update(pi)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="ProgramItem",
            subject_entity_id=item_id,
            from_state=prior,
            to_state="CANCELLED",
            payload_summary=f"program item cancelled directly, reason: {reason!r}",
        )

        actor_id, actor_role = actor_tuple()
        counts = cascade_program_item_cancel(
            festival_id,
            item_id,
            actor_user_id=actor_id,
            actor_role=actor_role,
            summary_prefix="direct program-item cancel",
        )

        # The "direct cancel" path (POST .../cancel) auto-emits an
        # ITEM_CANCEL ScheduleChange in PROPOSED-and-immediately-APPLIED
        # form so the four-target sync envelope and the audit trail are
        # written through the canonical schedule-change pathway.  This
        # mirrors the PRD §3.4 wording: "An ITEM_CANCEL-kind ScheduleChange
        # is auto-created when the cancel was not itself the apply of a
        # ScheduleChange."
        sc_id = fresh_uuid()
        sc = {
            "id": sc_id,
            "festival_id": festival_id,
            "change_kind": "ITEM_CANCEL",
            "target_program_item_id": item_id,
            "payload": {"reason": reason},
            "status": "APPLIED",
            "applied_at": logical_now_iso(festival),
            "provisional_refund_cents_total": 0,
            "final_refund_cents_total": None,
            "idempotency_key": idempotency_key,
            "created_at": server_now_iso8601(),
            "updated_at": server_now_iso8601(),
            "version": 1,
            "sync_envelopes": [],
            # Internal marker that this change was auto-emitted from a
            # direct cancel; the harness does not see this field but the
            # revert path uses it to decide whether to restore the item.
            "_auto_emitted_from_direct_cancel": True,
            "_prior_program_item_status": prior,
        }
        provisional_total = apply_provisional_refunds_for_cancel(
            festival, item_id, sc_id
        )
        sc["provisional_refund_cents_total"] = int(provisional_total)
        seed_sync_envelopes(
            sc,
            {
                "kind": "ITEM_CANCEL",
                "program_item_id": item_id,
                "reason": reason,
                "provisional_refund_cents_total": provisional_total,
            },
        )
        DB.schedule_changes[sc_id] = sc
        append_audit(
            festival_id=festival_id,
            event_category="SCHEDULE_CHANGE",
            subject_entity_type="ScheduleChange",
            subject_entity_id=sc_id,
            from_state="PROPOSED",
            to_state="APPLIED",
            payload_summary=(
                f"auto-emitted ITEM_CANCEL schedule change for item {item_id}, "
                f"provisional refund total {provisional_total} cents, "
                f"cascade A: {counts['slots_cancelled']} slots cancelled, "
                f"{counts['teams_freed']} teams freed; "
                f"cascade B: {counts['allocations_voided']} allocations voided"
            ),
        )

        recompute_outstanding_tickets_total(festival_id)

        envelope_dict = {
            "meta": {
                # The envelope writer is the only place these keys are
                # canonically set; we forward the route's local g-bound
                # values into a dict so the idempotency store records the
                # exact body that was returned.
            },
            "response_type": "object",
            "data": _payload(pi),
        }
        resp = success_envelope(_payload(pi), http_status=200)
        if store_cb is not None:
            # The stored body must mirror the wire-format envelope so a
            # replay returns the same payload.  We re-build the body
            # from the response object's JSON, but the simplest path is
            # to store the data-only dict and the envelope writer
            # re-wraps it on replay; here we store the raw envelope so
            # the replay returns a byte-identical body modulo the
            # meta fields, which the replay handler patches.
            import json

            stored = json.loads(resp.get_data(as_text=True))
            store_cb(resp.status_code, stored)
    return resp


@bp.route(
    "/festivals/<festival_id>/program-items/<item_id>/recompute-priority",
    methods=["POST"],
)
def recompute_priority(festival_id: str, item_id: str):
    require_role(["FestivalProducer", "PlatformAdmin"])
    with GLOBAL_LOCK:
        pi = _resolve(festival_id, item_id)
        before = pi.get("slot_priority_score")
        score = recompute_slot_priority(pi)
        # Per §3.3 the recompute is idempotent — a recompute that yields
        # the same number is a no-op.  When the score changes we bump
        # `updated_at` and `version`.  When it does not, we still emit a
        # `score-unchanged` audit entry as the PRD prose carves out.
        new_val = float(score)
        if before != new_val:
            pi["slot_priority_score"] = new_val
            stamp_update(pi)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="ProgramItem",
            subject_entity_id=item_id,
            payload_summary=(
                f"slot priority recomputed: {before} → {new_val}"
                if before != new_val
                else f"slot priority recompute is a no-op at {new_val}"
            ),
        )
        out = _payload(pi)
    return success_envelope(out)


@bp.route(
    "/festivals/<festival_id>/program-items/<item_id>/sound-check/waive",
    methods=["POST"],
)
def waive_sound_check(festival_id: str, item_id: str):
    require_role(["StageManager", "FestivalProducer"])
    body = get_json_body()
    reason = body.get("reason")
    if not isinstance(reason, str) or reason == "":
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE",
            "sound-check waive requires a non-empty `reason` string",
        )
    with GLOBAL_LOCK:
        pi = _resolve(festival_id, item_id)
        if pi.get("status") in ("ANNOUNCED", "ON_STAGE", "PERFORMED", "CANCELLED"):
            raise ApiError(
                "ERR_PROGRAM_ITEM_NOT_MUTABLE",
                f"item lifecycle {pi['status']!r} is past the waive-permitted set",
            )
        cur_axis = pi.get("sound_check_status", "NOT_REQUIRED")
        if cur_axis in ("SCHEDULED", "COMPLETED"):
            # Per PRD §3.3: must cancel the slot first.
            raise ApiError(
                "ERR_SOUND_CHECK_NOT_TERMINAL",
                f"sound_check_status is {cur_axis!r} — the slot must be cancelled first",
            )
        prior = cur_axis
        pi["sound_check_status"] = "WAIVED"
        stamp_update(pi)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="ProgramItem",
            subject_entity_id=item_id,
            from_state=prior,
            to_state="WAIVED",
            payload_summary=f"sound-check waived for item, reason: {reason!r}",
        )
        out = _payload(pi)
    return success_envelope(out)


def register(app: Flask) -> None:
    app.register_blueprint(bp)
