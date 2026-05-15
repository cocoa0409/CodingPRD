"""ExposureAllocation endpoints and the deliver/void-delivery pair per §3.6."""
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
    check_if_match,
    fresh_uuid,
    get_json_body,
    if_match_header,
    list_by_predicate,
    make_blueprint,
    optional_int,
    optional_str,
    paginate_list,
    recompute_tier_projection,
    require_enum,
    require_int,
    require_role,
    require_str,
    resolve_festival,
    server_now_iso8601,
    stamp_create,
    stamp_update,
    success_envelope,
)
from ..calculations import delivered_units_for_allocation
from ..constants import EXPOSURE_KINDS, SPONSOR_PAYOUT_RATE_MILS_DEFAULT


bp = make_blueprint("exposure_allocations")


def _payload(a: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": a["id"],
        "festival_id": a.get("festival_id"),
        "sponsor_tier_id": a.get("sponsor_tier_id"),
        "program_item_id": a.get("program_item_id"),
        "kind": a.get("kind"),
        "requested_units": a.get("requested_units"),
        "actual_units": a.get("actual_units", 0),
        "delivered_units": a.get("delivered_units", 0),
        "pinned_rate_cents_per_unit": a.get(
            "pinned_rate_cents_per_unit", SPONSOR_PAYOUT_RATE_MILS_DEFAULT
        ),
        "status": a.get("status", "PLANNED"),
        "created_at": a.get("created_at"),
        "updated_at": a.get("updated_at"),
        "version": a.get("version"),
    }


def _resolve_tier(festival_id: str, tier_id: str) -> Dict[str, Any]:
    resolve_festival(festival_id)
    t = DB.sponsor_tiers.get(tier_id)
    if t is None:
        raise ApiError(
            "ERR_SPONSOR_TIER_NOT_FOUND", f"sponsor tier {tier_id} not found"
        )
    if t.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT", "tier belongs to a different festival"
        )
    return t


def _resolve_allocation(festival_id: str, alloc_id: str) -> Dict[str, Any]:
    resolve_festival(festival_id)
    a = DB.exposure_allocations.get(alloc_id)
    if a is None:
        raise ApiError(
            "ERR_EXPOSURE_ALLOCATION_NOT_FOUND",
            f"exposure allocation {alloc_id} not found",
        )
    if a.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT",
            "exposure allocation belongs to a different festival",
        )
    return a


@bp.route(
    "/festivals/<festival_id>/sponsor-tiers/<tier_id>/exposure-allocations",
    methods=["POST"],
)
def create_allocation(festival_id: str, tier_id: str):
    require_role(["SponsorshipAdmin"])
    body = get_json_body()
    with GLOBAL_LOCK:
        # Sweep-in-progress guard (§1.2.1 advisory lock).
        if festival_id in DB.sweep_locked_festivals:
            raise ApiError(
                "ERR_CONCURRENT_SWEEP_IN_PROGRESS",
                "a sponsor-allocation-sweep is currently in progress; retry after",
            )
        tier = _resolve_tier(festival_id, tier_id)
        kind = require_enum(body, "kind", tuple(EXPOSURE_KINDS))
        requested = require_int(body, "requested_units", non_negative=True)
        program_item_id = body.get("program_item_id")
        if program_item_id is not None and not isinstance(program_item_id, str):
            raise ApiError(
                "ERR_INVALID_FIELD_VALUE",
                "program_item_id must be a string or null",
            )
        pinned_rate = optional_int(
            body,
            "pinned_rate_cents_per_unit",
            default=SPONSOR_PAYOUT_RATE_MILS_DEFAULT,
            non_negative=True,
        )

        # Priority-16: referential contract-kinds check, with the
        # artist-mention specialisation.
        kinds_allowed = set(tier.get("contract_kinds_allowed", []) or [])
        if kind not in kinds_allowed:
            if kind == "artist_mention":
                raise ApiError(
                    "ERR_ARTIST_NOT_ELIGIBLE_FOR_TIER",
                    f"sponsor tier does not allow artist_mention exposure",
                )
            raise ApiError(
                "ERR_EXPOSURE_KIND_NOT_CONTRACTED",
                f"sponsor tier does not allow exposure kind {kind!r}",
            )

        # Priority-16 cross-festival-program-item guard.
        if program_item_id is not None:
            pi = DB.program_items.get(program_item_id)
            if pi is None:
                raise ApiError(
                    "ERR_PROGRAM_ITEM_NOT_FOUND",
                    f"program item {program_item_id} not found",
                )
            if pi.get("festival_id") != festival_id:
                raise ApiError(
                    "ERR_EXPOSURE_PROGRAM_ITEM_CROSS_FESTIVAL",
                    "tied program item is in a different festival",
                )

        # Priority-19 contract-units cap: sum of existing tier
        # allocations of the same kind + requested_units ≤ contracted_units.
        existing_sum = sum(
            int(a.get("requested_units", 0))
            for a in DB.exposure_allocations.values()
            if a.get("sponsor_tier_id") == tier_id
            and a.get("kind") == kind
            and a.get("status") != "VOIDED"
        )
        contracted = int(tier.get("contracted_units", 0))
        if existing_sum + int(requested) > contracted:
            raise ApiError(
                "ERR_TIER_CONTRACT_UNITS_EXCEEDED",
                f"requested {requested} + existing {existing_sum} exceeds contract "
                f"cap {contracted} for kind {kind!r}",
            )

        # Empty-pool zero-units case (§2.6 priority 28): if the catalog
        # pool for this kind is currently drained, the row is created
        # with actual_units = 0 rather than rejected.
        cat_row = DB.exposure_catalogs.get(festival_id)
        if cat_row is None:
            pool_remaining = 0
        else:
            cat = cat_row.get("catalog") or {}
            already_disbursed = sum(
                int(a.get("actual_units", 0))
                for a in DB.exposure_allocations.values()
                if a.get("festival_id") == festival_id
                and a.get("kind") == kind
                and a.get("status") in ("PLANNED", "DELIVERED")
            )
            pool_remaining = max(0, int(cat.get(kind, 0)) - already_disbursed)
        initial_actual = min(int(requested), pool_remaining)

        row = {
            "festival_id": festival_id,
            "sponsor_tier_id": tier_id,
            "program_item_id": program_item_id,
            "kind": kind,
            "requested_units": int(requested),
            "actual_units": int(initial_actual),
            "delivered_units": 0,
            "pinned_rate_cents_per_unit": int(pinned_rate),
            "status": "PLANNED",
        }
        stamp_create(row)
        DB.exposure_allocations[row["id"]] = row
        append_audit(
            festival_id=festival_id,
            event_category="EXPOSURE",
            subject_entity_type="ExposureAllocation",
            subject_entity_id=row["id"],
            to_state="PLANNED",
            payload_summary=(
                f"exposure allocation created (kind={kind}, requested={requested}, "
                f"initial actual={initial_actual}, pool_remaining_pre={pool_remaining})"
            ),
        )
        recompute_tier_projection(tier_id)
        out = _payload(row)
    return success_envelope(out, http_status=201)


@bp.route(
    "/festivals/<festival_id>/exposure-allocations", methods=["GET"]
)
def list_allocations(festival_id: str):
    require_role(ANY_ROLE)
    status_f = request.args.get("status")
    kind_f = request.args.get("kind")
    tier_f = request.args.get("sponsor_tier_id")
    with GLOBAL_LOCK:
        resolve_festival(festival_id)

        def _pred(r: dict) -> bool:
            if r.get("festival_id") != festival_id:
                return False
            if status_f is not None and r.get("status") != status_f:
                return False
            if kind_f is not None and r.get("kind") != kind_f:
                return False
            if tier_f is not None and r.get("sponsor_tier_id") != tier_f:
                return False
            return True

        rows = list_by_predicate(DB.exposure_allocations, _pred)
        # Refresh each row's delivered_units from the log.
        for r in rows:
            r["delivered_units"] = delivered_units_for_allocation(
                r["id"], DB.fulfilment_logs.values()
            )
        page, meta = paginate_list(rows, request.args)
        out = [_payload(r) for r in page]
    return success_envelope(out, pagination=meta)


@bp.route(
    "/festivals/<festival_id>/exposure-allocations/<alloc_id>", methods=["GET"]
)
def read_allocation_detail(festival_id: str, alloc_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        a = _resolve_allocation(festival_id, alloc_id)
        a["delivered_units"] = delivered_units_for_allocation(
            a["id"], DB.fulfilment_logs.values()
        )
        logs = [
            {
                "id": f["id"],
                "exposure_allocation_id": f["exposure_allocation_id"],
                "program_item_id": f.get("program_item_id"),
                "event_type": f["event_type"],
                "units": int(f.get("units", 0)),
                "note": f.get("note", ""),
                "created_at": f.get("created_at"),
            }
            for f in DB.fulfilment_logs.values()
            if f.get("exposure_allocation_id") == alloc_id
        ]
        logs.sort(key=lambda r: (r["created_at"], r["id"]))
        payload = _payload(a)
        payload["fulfilment_log"] = logs
    return success_envelope(payload)


@bp.route(
    "/festivals/<festival_id>/exposure-allocations/<alloc_id>/deliver",
    methods=["POST"],
)
def deliver_units(festival_id: str, alloc_id: str):
    require_role(["SponsorshipAdmin"])
    body = get_json_body()
    units = require_int(body, "units", positive=True)
    note = optional_str(body, "note", default="") or ""
    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        a = _resolve_allocation(festival_id, alloc_id)
        check_if_match(a, if_match_header())

        if a.get("status") in ("VOIDED", "REPORTED"):
            raise ApiError(
                "ERR_EXPOSURE_ALLOCATION_TERMINAL",
                f"allocation is in terminal state {a.get('status')!r}",
            )

        # Cross-entity-state gate.
        if a.get("program_item_id") is not None:
            pi = DB.program_items.get(a["program_item_id"])
            if pi is None or pi.get("status") != "PERFORMED":
                raise ApiError(
                    "ERR_EXPOSURE_ALLOCATION_NOT_DELIVERABLE",
                    f"tied program item is not PERFORMED",
                )
        else:
            if festival.get("status") not in ("LIVE", "CLOSED"):
                raise ApiError(
                    "ERR_EXPOSURE_ALLOCATION_NOT_DELIVERABLE",
                    "festival-wide allocation requires the festival to be LIVE or CLOSED",
                )

        # Cap: prior DELIVERED units + new units ≤ allocation.actual_units.
        current_delivered = sum(
            int(f.get("units", 0))
            for f in DB.fulfilment_logs.values()
            if f.get("exposure_allocation_id") == alloc_id
            and f.get("event_type") == "DELIVERED"
        )
        actual_units = int(a.get("actual_units", 0))
        if current_delivered + int(units) > actual_units:
            raise ApiError(
                "ERR_EXPOSURE_ALLOCATION_NOT_DELIVERABLE",
                f"delivery would exceed actual_units cap: "
                f"{current_delivered}+{units} > {actual_units}",
            )

        # Tier-quota gate.
        tier = DB.sponsor_tiers[a["sponsor_tier_id"]]
        # Recompute the tier's quota from the log before the check.
        from ..calculations import tier_remaining_quota_from_logs

        tier_allocs = [
            x
            for x in DB.exposure_allocations.values()
            if x.get("sponsor_tier_id") == tier["id"]
        ]
        cur_quota = tier_remaining_quota_from_logs(
            int(tier.get("contracted_units", 0)),
            tier_allocs,
            DB.fulfilment_logs.values(),
        )
        if int(units) > cur_quota:
            raise ApiError(
                "ERR_TIER_CONTRACT_UNITS_EXCEEDED",
                f"delivery of {units} exceeds tier remaining quota {cur_quota}",
            )

        # Append the log row and flip the status.
        log_id = fresh_uuid()
        DB.fulfilment_logs[log_id] = {
            "id": log_id,
            "exposure_allocation_id": alloc_id,
            "program_item_id": a.get("program_item_id"),
            "event_type": "DELIVERED",
            "units": int(units),
            "note": note,
            "created_at": server_now_iso8601(),
        }
        prior_status = a.get("status")
        a["delivered_units"] = current_delivered + int(units) - 0  # voided=0 freshly tallied below
        # The authoritative delivered_units comes from the log helper, but
        # for the on-row cache we want the post-append value.
        from ..calculations import delivered_units_for_allocation as _du

        a["delivered_units"] = _du(alloc_id, DB.fulfilment_logs.values())
        a["status"] = "DELIVERED"
        stamp_update(a)
        append_audit(
            festival_id=festival_id,
            event_category="EXPOSURE",
            subject_entity_type="ExposureAllocation",
            subject_entity_id=alloc_id,
            from_state=prior_status,
            to_state="DELIVERED",
            payload_summary=(
                f"delivered {units} units (cumulative delivered={a['delivered_units']})"
            ),
        )
        recompute_tier_projection(a["sponsor_tier_id"])
        out = _payload(a)
    return success_envelope(out)


@bp.route(
    "/festivals/<festival_id>/exposure-allocations/<alloc_id>/void-delivery",
    methods=["POST"],
)
def void_delivery(festival_id: str, alloc_id: str):
    require_role(["SponsorshipAdmin"])
    body = get_json_body()
    reason = body.get("reason")
    if not isinstance(reason, str) or reason == "":
        raise ApiError("ERR_MISSING_VOID_REASON", "void-delivery requires a `reason` string")
    units_field = body.get("units")
    with GLOBAL_LOCK:
        a = _resolve_allocation(festival_id, alloc_id)
        check_if_match(a, if_match_header())
        if a.get("status") in ("VOIDED", "REPORTED"):
            raise ApiError(
                "ERR_EXPOSURE_ALLOCATION_TERMINAL",
                f"allocation is in terminal state {a.get('status')!r}",
            )
        from ..calculations import delivered_units_for_allocation as _du

        cur_delivered = _du(alloc_id, DB.fulfilment_logs.values())
        if units_field is None:
            magnitude = max(0, int(cur_delivered))
        else:
            if (
                isinstance(units_field, bool)
                or not isinstance(units_field, int)
                or units_field < 0
            ):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE",
                    "units must be a non-negative integer when supplied",
                )
            if int(units_field) > int(cur_delivered):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE",
                    f"void units {units_field} exceeds currently-delivered {cur_delivered}",
                )
            magnitude = int(units_field)

        log_id = fresh_uuid()
        DB.fulfilment_logs[log_id] = {
            "id": log_id,
            "exposure_allocation_id": alloc_id,
            "program_item_id": a.get("program_item_id"),
            "event_type": "VOIDED",
            "units": magnitude,
            "note": reason,
            "created_at": server_now_iso8601(),
        }
        prior_status = a.get("status")
        a["status"] = "VOIDED"
        a["delivered_units"] = _du(alloc_id, DB.fulfilment_logs.values())
        stamp_update(a)
        append_audit(
            festival_id=festival_id,
            event_category="EXPOSURE",
            subject_entity_type="ExposureAllocation",
            subject_entity_id=alloc_id,
            from_state=prior_status,
            to_state="VOIDED",
            payload_summary=(
                f"void of {magnitude} units, reason: {reason!r}; "
                f"running delivered_units now {a['delivered_units']}"
            ),
        )
        recompute_tier_projection(a["sponsor_tier_id"])
        out = _payload(a)
    return success_envelope(out)


def register(app: Flask) -> None:
    app.register_blueprint(bp)
