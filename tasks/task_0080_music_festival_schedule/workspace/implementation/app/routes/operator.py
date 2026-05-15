"""Operator-only endpoints under `/_clock`, `/_events`, and `/_sweep`.

Per PRD §2.8, §3.4, and §3.7, these are the harness's hooks for driving
the test logical wall clock and the external-system acknowledgements.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from flask import Flask, request

from ._common import (
    ApiError,
    DB,
    GLOBAL_LOCK,
    append_audit,
    epoch_to_iso8601,
    fire_clock_thresholds,
    festival_close_cascade,
    fresh_uuid,
    get_json_body,
    list_audit_for_festival,
    logical_now,
    logical_now_iso,
    make_blueprint,
    optional_int,
    optional_str,
    paginate_list,
    real_now_unix,
    recompute_all_tier_projections_for_festival,
    recompute_outstanding_tickets_total,
    recompute_tier_actuals_post_close,
    require_role,
    resolve_festival,
    server_now_iso8601,
    stamp_update,
    success_envelope,
)
from ..constants import (
    ABS_TOLERANCE_CENTS,
    AUDIT_LOG_ALLOWLIST,
    FESTIVAL_CLOSE_GRACE_SECONDS,
    SYNC_TARGETS,
)


bp = make_blueprint("operator")


# ---------------------------------------------------------------------------
# Clock state.
# ---------------------------------------------------------------------------


@bp.route("/_clock", methods=["GET"])
def read_clock():
    """The PRD §2.8 / §3.7 `ClockView` read.  Per §3.7 it "returns the
    synthetic `ClockView` with the per-festival `clock_offset_seconds`
    and the implied logical-wall-clock-of-record for each festival,
    optionally filtered to a specific `festival_id`".

    Shape rule: when the request's `festival_id` query parameter is set
    the response's `data` is the single per-festival object (the
    `response_type` is "object" per the §2.2 envelope convention); when
    unset, the response is the array across every festival (the
    `response_type` is "array").  Either way the per-festival entry
    carries the `clock_offset_seconds` integer that the §3.7 prose
    pins as the field-name."""
    require_role(["PlatformAdmin", "AuditViewer"])
    fid_filter = request.args.get("festival_id")
    with GLOBAL_LOCK:
        if fid_filter:
            fest = resolve_festival(fid_filter)
            fests = [fest]
        else:
            fests = list(DB.festivals.values())
        wall = int(real_now_unix())
        rows = []
        for f in fests:
            offset = int(f.get("clock_offset_seconds", 0))
            logical = wall + offset
            rows.append(
                {
                    "festival_id": f["id"],
                    "clock_offset_seconds": offset,
                    "wall_clock_unix_seconds": wall,
                    "wall_clock_iso8601": epoch_to_iso8601(wall),
                    "logical_clock_unix_seconds": logical,
                    "logical_clock_iso8601": epoch_to_iso8601(logical),
                }
            )
        # Sort deterministically by festival_id for the list response.
        rows.sort(key=lambda r: r["festival_id"])
    if fid_filter:
        # Single-festival filter: the §2.2 envelope's `response_type`
        # is "object" with the single row directly under `data`.
        payload = rows[0] if rows else {
            "festival_id": fid_filter,
            "clock_offset_seconds": 0,
            "wall_clock_unix_seconds": wall,
            "wall_clock_iso8601": epoch_to_iso8601(wall),
            "logical_clock_unix_seconds": wall,
            "logical_clock_iso8601": epoch_to_iso8601(wall),
        }
        return success_envelope(payload, response_type="object")
    # No filter: array-of-festivals.  Per §2.2 a list payload's
    # `response_type` is "array".  The implementation wraps the
    # array in `data` directly so the standard envelope's per-list
    # unwrap returns the bare list, and the test-side robust matcher
    # walks the list to find the per-festival entry with the matching
    # festival_id and the `clock_offset_seconds` key.
    return success_envelope(rows, response_type="array")


@bp.route("/_clock/advance", methods=["POST"])
def advance_clock():
    require_role(["PlatformAdmin"])
    body = get_json_body()
    fid = body.get("festival_id")
    delta = body.get("delta_seconds")
    to_unix = body.get("to_unix_seconds")

    # The §2.6 input-validation pair for the clock-advance endpoint.
    if delta is None and to_unix is None:
        raise ApiError(
            "ERR_CLOCK_INVALID_ARGS",
            "supply exactly one of delta_seconds or to_unix_seconds",
        )
    if delta is not None and to_unix is not None:
        raise ApiError(
            "ERR_CLOCK_INVALID_ARGS",
            "delta_seconds and to_unix_seconds are mutually exclusive",
        )
    if delta is not None:
        if (
            not isinstance(delta, int)
            or isinstance(delta, bool)
        ):
            raise ApiError(
                "ERR_CLOCK_INVALID_ARGS", "delta_seconds must be an integer"
            )
        if int(delta) < 0:
            raise ApiError(
                "ERR_CLOCK_ADVANCE_BACKWARD",
                "delta_seconds must be non-negative (monotonic non-decreasing)",
            )
    if to_unix is not None:
        if (
            not isinstance(to_unix, int)
            or isinstance(to_unix, bool)
            or int(to_unix) <= 0
        ):
            raise ApiError(
                "ERR_CLOCK_INVALID_ARGS",
                "to_unix_seconds must be a positive integer Unix-seconds timestamp",
            )

    with GLOBAL_LOCK:
        if fid is not None:
            if not isinstance(fid, str):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE", "festival_id must be a string"
                )
            targets = [resolve_festival(fid)]
        else:
            targets = list(DB.festivals.values())

        wall = int(real_now_unix())
        updated: List[Dict[str, Any]] = []
        for f in targets:
            cur_offset = int(f.get("clock_offset_seconds", 0))
            cur_logical = wall + cur_offset
            if delta is not None:
                new_logical = cur_logical + int(delta)
            else:
                if int(to_unix) < cur_logical:
                    raise ApiError(
                        "ERR_CLOCK_ADVANCE_BACKWARD",
                        f"to_unix_seconds {to_unix} earlier than festival's current logical "
                        f"wall clock {cur_logical}",
                    )
                new_logical = int(to_unix)
            new_offset = new_logical - wall
            f["clock_offset_seconds"] = int(new_offset)
            stamp_update(f)
            append_audit(
                festival_id=f["id"],
                event_category="CLOCK_TICK",
                subject_entity_type="Festival",
                subject_entity_id=f["id"],
                payload_summary=(
                    f"clock advanced: offset {cur_offset} → {new_offset} "
                    f"(logical-now {cur_logical} → {new_logical})"
                ),
                actor_user_id="system",
                actor_role="system",
            )
            fire_count = fire_clock_thresholds(f)
            recompute_all_tier_projections_for_festival(f["id"])
            updated.append(
                {
                    "festival_id": f["id"],
                    "clock_offset_seconds": int(f["clock_offset_seconds"]),
                    "logical_clock_unix_seconds": wall + int(f["clock_offset_seconds"]),
                    "transitions_fired": int(fire_count),
                }
            )
    payload = {"wall_clock_unix_seconds": wall, "festivals": updated}
    return success_envelope(payload, http_status=200)


# ---------------------------------------------------------------------------
# Sync acknowledgement ingress.
# ---------------------------------------------------------------------------


def _flip_envelope(
    change_id: str, target: str, succeeded: bool, payload_hash_override: Optional[str]
) -> Dict[str, Any]:
    sc = DB.schedule_changes.get(change_id)
    if sc is None:
        raise ApiError(
            "ERR_SCHEDULE_CHANGE_NOT_FOUND",
            f"schedule change {change_id} not found",
        )
    if target not in SYNC_TARGETS:
        raise ApiError(
            "ERR_SYNC_TARGET_UNKNOWN",
            f"target {target!r} is not one of {SYNC_TARGETS}",
        )

    envs = sc.get("sync_envelopes") or []
    matched: Optional[Dict[str, Any]] = None
    for e in envs:
        if e.get("target") == target:
            matched = e
            break
    if matched is None:
        # The four canonical targets are always seeded on apply, so this
        # is an impossible-by-construction case unless the harness picks
        # a target that the apply path never seeded.  Use the unknown-
        # target catalog error for symmetry with the bad-target shape
        # check.
        raise ApiError(
            "ERR_SYNC_TARGET_UNKNOWN",
            f"no envelope element for target {target!r}",
        )
    if matched.get("status") != "QUEUED":
        raise ApiError(
            "ERR_SYNC_ENVELOPE_NOT_QUEUED",
            f"envelope for {target!r} is in {matched.get('status')!r}",
        )
    if sc.get("status") != "APPLIED":
        # Mirror case of the apply-vs-revert race: an ack against a
        # non-APPLIED change is rejected per the PRD's
        # "ERR_CHANGE_NOT_APPLIED" gate.
        raise ApiError(
            "ERR_CHANGE_NOT_APPLIED",
            f"schedule change is in {sc.get('status')!r}; the ack targets an APPLIED change",
        )

    matched["status"] = "ACKNOWLEDGED" if succeeded else "FAILED"
    matched["acked_at"] = server_now_iso8601()
    if payload_hash_override is not None:
        matched["payload_hash"] = payload_hash_override
    stamp_update(sc)
    append_audit(
        festival_id=sc["festival_id"],
        event_category="SYNC_ACK",
        subject_entity_type="ScheduleChange",
        subject_entity_id=change_id,
        payload_summary=(
            f"sync envelope flip for target={target!r}, succeeded={succeeded}"
        ),
    )
    # Advance APPLIED → SYNCED when every envelope is ACKNOWLEDGED.
    if all(e.get("status") == "ACKNOWLEDGED" for e in sc["sync_envelopes"]):
        sc["status"] = "SYNCED"
        stamp_update(sc)
        append_audit(
            festival_id=sc["festival_id"],
            event_category="SYNC_ACK",
            subject_entity_type="ScheduleChange",
            subject_entity_id=change_id,
            from_state="APPLIED",
            to_state="SYNCED",
            payload_summary="all four sync envelopes acknowledged; change is SYNCED",
            actor_user_id="system",
            actor_role="system",
        )
    return sc


@bp.route("/_events/sync-ack", methods=["POST"])
def sync_ack():
    require_role(["PlatformAdmin"])
    body = get_json_body()
    # Required body fields per the PRD §2.8 sync-ack envelope.
    fid = body.get("festival_id")
    cid = body.get("schedule_change_id")
    target = body.get("target")
    succeeded = body.get("succeeded", True)
    payload_hash = body.get("payload_hash")
    if not isinstance(cid, str) or cid == "":
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", "schedule_change_id must be a non-empty string"
        )
    if not isinstance(target, str) or target == "":
        raise ApiError("ERR_SYNC_TARGET_UNKNOWN", "target must be a non-empty string")
    if target not in SYNC_TARGETS:
        raise ApiError(
            "ERR_SYNC_TARGET_UNKNOWN",
            f"target {target!r} must be one of {SYNC_TARGETS}",
        )
    if not isinstance(succeeded, bool):
        raise ApiError("ERR_INVALID_FIELD_VALUE", "succeeded must be a boolean")
    if payload_hash is not None and not isinstance(payload_hash, str):
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", "payload_hash must be a string when present"
        )

    with GLOBAL_LOCK:
        if fid is not None:
            if not isinstance(fid, str):
                raise ApiError("ERR_INVALID_FIELD_VALUE", "festival_id must be a string")
            resolve_festival(fid)
        sc = _flip_envelope(cid, target, bool(succeeded), payload_hash)
        if fid is not None and sc.get("festival_id") != fid:
            raise ApiError(
                "ERR_RESOURCE_MISMATCHED_PARENT",
                "schedule_change_id belongs to a different festival",
            )
        from .schedule_changes import _payload as sc_payload

        out = sc_payload(sc)
    return success_envelope(out)


@bp.route("/_events/refund-confirmed", methods=["POST"])
def refund_confirmed():
    """The ticketing-leg specialised sync-ack carrying a per-type refund breakdown.

    Per PRD §2.8 the body is `{schedule_change_id, festival_id?, target='ticketing',
    succeeded=true, payload_hash, refund_breakdown}`.  The endpoint
    increments each named ticket type's `refunded_count` by the row's
    `refunded_count_delta`, decrements its
    `provisional_refund_cents_outstanding` by the originally-attributed
    amount, stamps the change's `final_refund_cents_total`, and flips
    the ticketing envelope to ACKNOWLEDGED.
    """
    require_role(["PlatformAdmin"])
    body = get_json_body()
    cid = body.get("schedule_change_id")
    if not isinstance(cid, str) or cid == "":
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE",
            "schedule_change_id must be a non-empty string",
        )
    payload_hash = body.get("payload_hash")
    breakdown = body.get("refund_breakdown", [])
    if not isinstance(breakdown, list):
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", "refund_breakdown must be a list of objects"
        )
    fid_hint = body.get("festival_id")

    with GLOBAL_LOCK:
        sc = DB.schedule_changes.get(cid)
        if sc is None:
            raise ApiError(
                "ERR_SCHEDULE_CHANGE_NOT_FOUND",
                f"schedule change {cid} not found",
            )
        festival_id = sc["festival_id"]
        festival = DB.festivals.get(festival_id)
        if festival is None:
            raise ApiError(
                "ERR_FESTIVAL_NOT_FOUND", f"festival {festival_id} not found"
            )
        if fid_hint is not None and fid_hint != festival_id:
            raise ApiError(
                "ERR_RESOURCE_MISMATCHED_PARENT",
                "festival_id in body does not match the schedule-change's festival",
            )

        if festival.get("status") == "CLOSED":
            raise ApiError(
                "ERR_FESTIVAL_ALREADY_CLOSED",
                "festival is CLOSED; further refund-confirmed events are rejected",
            )

        if sc.get("status") != "APPLIED":
            raise ApiError(
                "ERR_CHANGE_NOT_APPLIED",
                f"schedule change is in {sc.get('status')!r}, not APPLIED",
            )

        # Cross-festival guard on the per-type rows.
        attribution = DB.refund_attributions.get(cid, {})
        per_type_final_sum = 0
        for row in breakdown:
            if not isinstance(row, dict):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE",
                    "refund_breakdown entries must be objects",
                )
            tt_id = row.get("ticket_type_id")
            delta = row.get("refunded_count_delta", 0)
            final_cents = row.get("final_cents_total_for_type", 0)
            if (
                not isinstance(tt_id, str)
                or tt_id == ""
                or not isinstance(delta, int)
                or isinstance(delta, bool)
                or delta < 0
                or not isinstance(final_cents, int)
                or isinstance(final_cents, bool)
                or final_cents < 0
            ):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE",
                    "refund_breakdown row shape is invalid",
                )
            tt = DB.ticket_types.get(tt_id)
            if tt is None:
                raise ApiError(
                    "ERR_TICKET_TYPE_NOT_FOUND", f"ticket type {tt_id} not found"
                )
            # Priority-17 cross-festival guard.
            if tt.get("festival_id") != festival_id:
                raise ApiError(
                    "ERR_CROSS_FESTIVAL_REFUND",
                    f"ticket type {tt_id} belongs to festival {tt.get('festival_id')}, "
                    f"not the schedule-change's festival {festival_id}",
                )
            # The catalog-side state of the type matters too: a CLOSED
            # type at the per-type level mirrors the festival-level CLOSED
            # rejection.
            if tt.get("status") == "CLOSED":
                raise ApiError(
                    "ERR_FESTIVAL_ALREADY_CLOSED",
                    f"ticket type {tt_id} is CLOSED (festival close cascade)",
                )
            # Priority-21 magnitude check: final_cents_total_for_type
            # must not exceed the matching provisional figure by any
            # positive amount (ABS_TOLERANCE_CENTS = 0).
            attributed = int(attribution.get(tt_id, 0))
            if int(final_cents) > attributed + ABS_TOLERANCE_CENTS:
                raise ApiError(
                    "ERR_REFUND_EXCEEDS_PROVISIONAL",
                    f"final cents {final_cents} for ticket type {tt_id} exceeds the "
                    f"matching provisional cents {attributed}",
                )
            per_type_final_sum += int(final_cents)
            # Apply: refunded_count += delta, provisional bucket -= attributed.
            tt["refunded_count"] = int(tt.get("refunded_count", 0)) + int(delta)
            cur_bucket = int(tt.get("provisional_refund_cents_outstanding", 0))
            tt["provisional_refund_cents_outstanding"] = max(0, cur_bucket - attributed)
            stamp_update(tt)
            append_audit(
                festival_id=festival_id,
                event_category="SYNC_ACK",
                subject_entity_type="TicketType",
                subject_entity_id=tt_id,
                payload_summary=(
                    f"refund-confirmed: ticket_type={tt_id}, "
                    f"refunded_count_delta={delta}, "
                    f"final_cents_total_for_type={final_cents}, "
                    f"provisional_attributed={attributed}"
                ),
            )

        sc["final_refund_cents_total"] = int(per_type_final_sum)
        # Flip the ticketing envelope to ACKNOWLEDGED.
        _flip_envelope(cid, "ticketing", True, payload_hash)
        stamp_update(sc)
        # Clear the attribution so a repeat ack would be a duplicate.
        DB.refund_attributions.pop(cid, None)
        recompute_outstanding_tickets_total(festival_id)

        # Refresh sc from DB after _flip_envelope mutations.
        sc = DB.schedule_changes[cid]
        from .schedule_changes import _payload as sc_payload

        out = sc_payload(sc)
    return success_envelope(out)


# ---------------------------------------------------------------------------
# Post-event sweep.
# ---------------------------------------------------------------------------


@bp.route("/_sweep/run", methods=["POST"])
def post_event_sweep():
    require_role(["PlatformAdmin", "SponsorshipAdmin"])
    body = get_json_body()
    fid = body.get("festival_id")
    if not isinstance(fid, str) or fid == "":
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE",
            "festival_id is required on the sweep body",
        )
    compute_payout = body.get("compute_payout", False)
    if not isinstance(compute_payout, bool):
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", "compute_payout must be a boolean"
        )

    with GLOBAL_LOCK:
        festival = DB.festivals.get(fid)
        if festival is None:
            raise ApiError(
                "ERR_SWEEP_FESTIVAL_NOT_FOUND", f"festival {fid!r} not found"
            )

        # Pre-close: a no-op on the actual-percentage field but a refresh
        # on the projected percentages.
        if festival.get("status") != "CLOSED":
            recompute_all_tier_projections_for_festival(fid)
            payload = {
                "festival_id": fid,
                "festival_status": festival.get("status"),
                "actual_percentages_stamped": False,
                "tiers": [
                    {
                        "sponsor_tier_id": t["id"],
                        "projected_fulfilment_pct": t.get("projected_fulfilment_pct"),
                        "actual_fulfilment_pct": t.get("actual_fulfilment_pct"),
                    }
                    for t in DB.sponsor_tiers.values()
                    if t.get("festival_id") == fid
                ],
            }
            append_audit(
                festival_id=fid,
                event_category="EXPOSURE",
                subject_entity_type="Festival",
                subject_entity_id=fid,
                payload_summary="pre-close sweep refreshed projected percentages",
                actor_user_id="system",
                actor_role="system",
            )
            return success_envelope(payload)

        # Post-close: flip every DELIVERED allocation to REPORTED with a
        # closing REPORTED log row, stamp the actual percentages, and
        # (when `compute_payout`) compute the per-tier sponsor-payout in cents.
        # The sweep is idempotent — a subsequent invocation on an already-
        # closed festival produces the same numbers.
        from ..calculations import delivered_units_for_allocation

        for a in DB.exposure_allocations.values():
            if a.get("festival_id") != fid:
                continue
            if a.get("status") == "DELIVERED":
                # Append a REPORTED row with units=0.
                log_id = fresh_uuid()
                DB.fulfilment_logs[log_id] = {
                    "id": log_id,
                    "exposure_allocation_id": a["id"],
                    "program_item_id": a.get("program_item_id"),
                    "event_type": "REPORTED",
                    "units": 0,
                    "note": "post-event sweep closing tally",
                    "created_at": server_now_iso8601(),
                }
                a["status"] = "REPORTED"
                a["delivered_units"] = delivered_units_for_allocation(
                    a["id"], DB.fulfilment_logs.values()
                )
                stamp_update(a)
                append_audit(
                    festival_id=fid,
                    event_category="EXPOSURE",
                    subject_entity_type="ExposureAllocation",
                    subject_entity_id=a["id"],
                    from_state="DELIVERED",
                    to_state="REPORTED",
                    payload_summary="closing REPORTED log row appended (units=0) by sweep",
                    actor_user_id="system",
                    actor_role="system",
                )

        # Stamp each tier's actual_fulfilment_pct and tier_remaining_quota
        # (and payout when the flag is set).
        tier_rows = [
            t for t in DB.sponsor_tiers.values() if t.get("festival_id") == fid
        ]
        snapshot: List[Dict[str, Any]] = []
        for t in tier_rows:
            actual, payout = recompute_tier_actuals_post_close(
                t["id"], compute_payout=bool(compute_payout)
            )
            snapshot.append(
                {
                    "sponsor_tier_id": t["id"],
                    "actual_fulfilment_pct": float(actual),
                    "projected_fulfilment_pct": t.get("projected_fulfilment_pct"),
                    "tier_remaining_quota": t.get("tier_remaining_quota"),
                    "sponsor_payout_total_cents": (
                        int(payout) if compute_payout else None
                    ),
                }
            )
            append_audit(
                festival_id=fid,
                event_category="EXPOSURE",
                subject_entity_type="SponsorTier",
                subject_entity_id=t["id"],
                payload_summary=(
                    f"post-event sweep tier {t['id']}: actual_pct={float(actual)}, "
                    f"quota={t.get('tier_remaining_quota')}, "
                    f"payout_cents={'-' if not compute_payout else int(payout)}"
                ),
                actor_user_id="system",
                actor_role="system",
            )

        payload = {
            "festival_id": fid,
            "festival_status": festival.get("status"),
            "actual_percentages_stamped": True,
            "compute_payout": bool(compute_payout),
            "tiers": snapshot,
        }
    return success_envelope(payload)


def register(app: Flask) -> None:
    app.register_blueprint(bp)
