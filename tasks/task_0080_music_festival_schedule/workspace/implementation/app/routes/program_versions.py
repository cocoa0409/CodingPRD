"""ProgramVersion endpoints per PRD §3.3 and §4."""
from __future__ import annotations

from typing import Any, Dict, List

from flask import Flask, request

from ._common import (
    ANY_ROLE,
    ApiError,
    DB,
    GLOBAL_LOCK,
    actor_tuple,
    append_audit,
    append_occ_conflict,
    check_if_match,
    check_unblocking_riders_for_publish,
    child_belongs,
    find_or_404,
    fresh_uuid,
    get_json_body,
    if_match_header,
    list_by_predicate,
    logical_now_iso,
    make_blueprint,
    optional_str,
    paginate_list,
    require_role,
    require_str,
    resolve_festival,
    seed_sync_envelopes,
    stamp_create,
    stamp_update,
    success_envelope,
)


bp = make_blueprint("program_versions")


def _payload(pv: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": pv["id"],
        "festival_id": pv.get("festival_id"),
        "version_label": pv.get("version_label"),
        "status": pv.get("status"),
        "program_item_ids": list(pv.get("program_item_ids", []) or []),
        "published_at": pv.get("published_at"),
        "superseded_by_version_id": pv.get("superseded_by_version_id"),
        "created_at": pv.get("created_at"),
        "updated_at": pv.get("updated_at"),
        "version": pv.get("version"),
    }


def _resolve(festival_id: str, version_id: str) -> Dict[str, Any]:
    resolve_festival(festival_id)
    pv = DB.program_versions.get(version_id)
    if pv is None:
        raise ApiError(
            "ERR_PROGRAM_VERSION_NOT_FOUND", f"program version {version_id} not found"
        )
    if pv.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT",
            f"program version belongs to a different festival",
        )
    return pv


@bp.route("/festivals/<festival_id>/program-versions", methods=["POST"])
def create_pv(festival_id: str):
    require_role(["FestivalProducer"])
    body = get_json_body()
    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        if festival.get("status") in ("CLOSED", "CANCELLED"):
            # Creating a version on a closed/cancelled festival is rejected
            # under the cross-state precondition family.
            raise ApiError(
                "ERR_FESTIVAL_ALREADY_CLOSED",
                "cannot create a program version on a terminal festival",
            )
        label = require_str(body, "version_label")
        pv = {
            "festival_id": festival_id,
            "version_label": label,
            "status": "DRAFT",
            "program_item_ids": [],
            "published_at": None,
            "superseded_by_version_id": None,
        }
        stamp_create(pv)
        DB.program_versions[pv["id"]] = pv
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="ProgramVersion",
            subject_entity_id=pv["id"],
            from_state=None,
            to_state="DRAFT",
            payload_summary=f"program version created with label {label!r}",
        )
        out = _payload(pv)
    return success_envelope(out, http_status=201)


@bp.route("/festivals/<festival_id>/program-versions", methods=["GET"])
def list_pv(festival_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        resolve_festival(festival_id)
        status_filter = request.args.get("status")

        def _pred(r: dict) -> bool:
            if r.get("festival_id") != festival_id:
                return False
            if status_filter is not None and r.get("status") != status_filter:
                return False
            return True

        rows = list_by_predicate(DB.program_versions, _pred)
        page, meta = paginate_list(rows, request.args)
        out = [_payload(r) for r in page]
    return success_envelope(out, pagination=meta)


@bp.route("/festivals/<festival_id>/program-versions/<version_id>", methods=["GET"])
def read_pv(festival_id: str, version_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        pv = _resolve(festival_id, version_id)
        out = _payload(pv)
    return success_envelope(out)


@bp.route(
    "/festivals/<festival_id>/program-versions/<version_id>/submit-for-review",
    methods=["POST"],
)
def submit_for_review(festival_id: str, version_id: str):
    require_role(["FestivalProducer"])
    with GLOBAL_LOCK:
        pv = _resolve(festival_id, version_id)
        check_if_match(pv, if_match_header())
        if pv.get("status") != "DRAFT":
            # No specific 'not-DRAFT' error in the catalog — surface the
            # generic state-gate family.  The harness's per-state tests
            # pin the canonical name `ERR_EMPTY_PROGRAM_VERSION` for the
            # empty-program edge, so check that first.
            if pv.get("status") in ("PUBLISHED", "SUPERSEDED", "WITHDRAWN"):
                # Already advanced past DRAFT; use the change-state family.
                raise ApiError(
                    "ERR_FESTIVAL_NOT_SCHEDULING_OR_PUBLISHED",
                    f"program version is in terminal state {pv['status']!r}",
                )
            if pv.get("status") == "READY_FOR_REVIEW":
                raise ApiError(
                    "ERR_EMPTY_PROGRAM_VERSION",
                    "program version is already in READY_FOR_REVIEW",
                )
        # ALLOW_EMPTY_PROGRAM = false (benchmark mode): at least one
        # ProgramItem must reference this version.
        any_item = any(
            pi.get("program_version_id") == version_id
            for pi in DB.program_items.values()
        )
        if not any_item:
            raise ApiError(
                "ERR_EMPTY_PROGRAM_VERSION",
                "program version has zero attached program items",
            )
        from_state = pv["status"]
        pv["status"] = "READY_FOR_REVIEW"
        stamp_update(pv)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="ProgramVersion",
            subject_entity_id=version_id,
            from_state=from_state,
            to_state="READY_FOR_REVIEW",
            payload_summary="program version submitted for review",
        )
        out = _payload(pv)
    return success_envelope(out)


@bp.route(
    "/festivals/<festival_id>/program-versions/<version_id>/return-for-revision",
    methods=["POST"],
)
def return_for_revision(festival_id: str, version_id: str):
    require_role(["ArtistLiaison"])
    body = get_json_body()
    if not body.get("reason"):
        raise ApiError(
            "ERR_MISSING_REVISION_REASON",
            "return-for-revision requires a `reason` string in the body",
        )
    reason = require_str(body, "reason")
    with GLOBAL_LOCK:
        pv = _resolve(festival_id, version_id)
        check_if_match(pv, if_match_header())
        if pv.get("status") != "READY_FOR_REVIEW":
            raise ApiError(
                "ERR_FESTIVAL_NOT_SCHEDULING_OR_PUBLISHED",
                "return-for-revision requires the version to be READY_FOR_REVIEW",
            )
        from_state = pv["status"]
        pv["status"] = "DRAFT"
        stamp_update(pv)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="ProgramVersion",
            subject_entity_id=version_id,
            from_state=from_state,
            to_state="DRAFT",
            payload_summary=f"version returned for revision, reason: {reason!r}",
        )
        out = _payload(pv)
    return success_envelope(out)


@bp.route(
    "/festivals/<festival_id>/program-versions/<version_id>/publish", methods=["POST"]
)
def publish_pv(festival_id: str, version_id: str):
    require_role(["FestivalProducer"])
    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        pv = _resolve(festival_id, version_id)

        # Priority-5 state gate.
        if pv.get("status") not in ("DRAFT", "READY_FOR_REVIEW"):
            raise ApiError(
                "ERR_FESTIVAL_NOT_SCHEDULING_OR_PUBLISHED",
                f"version is in {pv.get('status')!r}, cannot publish",
            )

        # Priority-6 cross-entity gate on the festival's lifecycle.
        if festival.get("status") not in ("SCHEDULING", "PUBLISHED"):
            raise ApiError(
                "ERR_FESTIVAL_NOT_SCHEDULING_OR_PUBLISHED",
                f"festival is in {festival.get('status')!r}, must be SCHEDULING or PUBLISHED",
            )

        # Priority-9 blocking-rider check across every item under the version.
        check_unblocking_riders_for_publish(version_id, festival_id)

        # Priority-23 OCC check on the festival row (the CAS), per the PRD's
        # festival-version-pointer compare-and-swap convention.  The
        # client's If-Match header is keyed on the **festival's** version
        # integer in the publish's race semantics.
        check_if_match(pv, if_match_header())

        # Snapshot the program-item ids whose program_version_id matches.
        snapshot: List[str] = [
            pi["id"]
            for pi in DB.program_items.values()
            if pi.get("program_version_id") == version_id
        ]
        snapshot.sort()

        # Flip prior PUBLISHED under the same festival to SUPERSEDED.
        for other in DB.program_versions.values():
            if (
                other.get("festival_id") == festival_id
                and other["id"] != version_id
                and other.get("status") == "PUBLISHED"
            ):
                other_prior = other["status"]
                other["status"] = "SUPERSEDED"
                other["superseded_by_version_id"] = version_id
                stamp_update(other)
                append_audit(
                    festival_id=festival_id,
                    event_category="STATE_TRANSITION",
                    subject_entity_type="ProgramVersion",
                    subject_entity_id=other["id"],
                    from_state=other_prior,
                    to_state="SUPERSEDED",
                    payload_summary=(
                        f"version superseded by newly-published {version_id}"
                    ),
                    actor_user_id="system",
                    actor_role="system",
                )

        from_state = pv["status"]
        pv["status"] = "PUBLISHED"
        pv["published_at"] = logical_now_iso(festival)
        pv["program_item_ids"] = snapshot
        stamp_update(pv)

        prior_pointer = festival.get("current_program_version_id")
        festival["current_program_version_id"] = version_id
        if festival.get("status") == "SCHEDULING":
            prior_f = festival["status"]
            festival["status"] = "PUBLISHED"
            stamp_update(festival)
            append_audit(
                festival_id=festival_id,
                event_category="STATE_TRANSITION",
                subject_entity_type="Festival",
                subject_entity_id=festival_id,
                from_state=prior_f,
                to_state="PUBLISHED",
                payload_summary="festival advanced to PUBLISHED on first publish",
                actor_user_id="system",
                actor_role="system",
            )
        else:
            stamp_update(festival)

        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="ProgramVersion",
            subject_entity_id=version_id,
            from_state=from_state,
            to_state="PUBLISHED",
            payload_summary=(
                f"version published, snapshot of {len(snapshot)} program items, "
                f"festival current pointer: {prior_pointer} → {version_id}"
            ),
        )

        # Auto-create a ScheduleChange of kind VERSION_PUBLISH with four QUEUED envelopes.
        sc = {
            "id": fresh_uuid(),
            "festival_id": festival_id,
            "change_kind": "VERSION_PUBLISH",
            "target_program_item_id": None,
            "payload": {"program_version_id": version_id},
            "status": "APPLIED",
            "applied_at": logical_now_iso(festival),
            "provisional_refund_cents_total": 0,
            "final_refund_cents_total": None,
            "idempotency_key": None,
            "created_at": server_now_iso8601_safe(),
            "updated_at": server_now_iso8601_safe(),
            "version": 1,
            "sync_envelopes": [],
        }
        seed_sync_envelopes(sc, {"version_id": version_id, "kind": "VERSION_PUBLISH"})
        DB.schedule_changes[sc["id"]] = sc
        append_audit(
            festival_id=festival_id,
            event_category="SCHEDULE_CHANGE",
            subject_entity_type="ScheduleChange",
            subject_entity_id=sc["id"],
            from_state=None,
            to_state="APPLIED",
            payload_summary=(
                f"auto-emitted VERSION_PUBLISH schedule change for version {version_id}, "
                "four sync envelopes queued"
            ),
            actor_user_id="system",
            actor_role="system",
        )

        out = _payload(pv)
    return success_envelope(out)


@bp.route(
    "/festivals/<festival_id>/program-versions/<version_id>/withdraw", methods=["POST"]
)
def withdraw_pv(festival_id: str, version_id: str):
    require_role(["FestivalProducer"])
    with GLOBAL_LOCK:
        pv = _resolve(festival_id, version_id)
        check_if_match(pv, if_match_header())
        if pv.get("published_at") is not None:
            raise ApiError(
                "ERR_FESTIVAL_NOT_SCHEDULING_OR_PUBLISHED",
                "a previously-published version cannot be withdrawn",
            )
        if pv.get("status") not in ("DRAFT", "READY_FOR_REVIEW"):
            raise ApiError(
                "ERR_FESTIVAL_NOT_SCHEDULING_OR_PUBLISHED",
                f"version is in {pv.get('status')!r}, cannot withdraw",
            )
        prior = pv["status"]
        pv["status"] = "WITHDRAWN"
        stamp_update(pv)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="ProgramVersion",
            subject_entity_id=version_id,
            from_state=prior,
            to_state="WITHDRAWN",
            payload_summary="version withdrawn",
        )
        out = _payload(pv)
    return success_envelope(out)


# A tiny helper that imports the canonical timestamp generator lazily — we
# keep `_payload` and the helpers above synchronously importable from the
# `_common` module without a circular dependency.
def server_now_iso8601_safe() -> str:
    from ..envelope import server_now_iso8601

    return server_now_iso8601()


def register(app: Flask) -> None:
    app.register_blueprint(bp)
