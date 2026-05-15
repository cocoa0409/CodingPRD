"""SponsorTier endpoints and the fulfilment-report read per PRD §3.6 / §3.7."""
from __future__ import annotations

from typing import Any, Dict, List

from flask import Flask, request

from ._common import (
    ANY_ROLE,
    ApiError,
    DB,
    GLOBAL_LOCK,
    append_audit,
    check_if_match,
    fulfilment_report_payload,
    get_json_body,
    if_match_header,
    list_by_predicate,
    make_blueprint,
    optional_list,
    optional_str,
    paginate_list,
    recompute_all_tier_projections_for_festival,
    recompute_tier_projection,
    require_enum,
    require_int,
    require_list,
    require_role,
    require_str,
    resolve_festival,
    run_waterfall,
    server_now_iso8601,
    stamp_create,
    stamp_update,
    success_envelope,
)
from ..constants import EXPOSURE_KINDS


bp = make_blueprint("sponsor_tiers")


_TIER_CODES = ("TITLE", "GOLD", "SILVER")


def _payload(t: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": t["id"],
        "festival_id": t.get("festival_id"),
        "tier_code": t.get("tier_code"),
        "tier_name": t.get("tier_name"),
        "priority_rank": t.get("priority_rank"),
        "sponsor_external_id": t.get("sponsor_external_id"),
        "sponsor_display_name": t.get("sponsor_display_name"),
        "contracted_units": t.get("contracted_units"),
        "contract_kinds_allowed": list(t.get("contract_kinds_allowed", []) or []),
        "projected_fulfilment_pct": t.get("projected_fulfilment_pct"),
        "actual_fulfilment_pct": t.get("actual_fulfilment_pct"),
        "tier_remaining_quota": t.get(
            "tier_remaining_quota", t.get("contracted_units")
        ),
        "sponsor_payout_total_cents": t.get("sponsor_payout_total_cents"),
        "created_at": t.get("created_at"),
        "updated_at": t.get("updated_at"),
        "version": t.get("version"),
    }


def _resolve(festival_id: str, tier_id: str) -> Dict[str, Any]:
    resolve_festival(festival_id)
    t = DB.sponsor_tiers.get(tier_id)
    if t is None:
        raise ApiError(
            "ERR_SPONSOR_TIER_NOT_FOUND", f"sponsor tier {tier_id} not found"
        )
    if t.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT",
            "sponsor tier belongs to a different festival",
        )
    return t


@bp.route("/festivals/<festival_id>/sponsor-tiers", methods=["POST"])
def create_tier(festival_id: str):
    require_role(["SponsorshipAdmin", "FestivalProducer"])
    body = get_json_body()
    with GLOBAL_LOCK:
        resolve_festival(festival_id)
        tier_code = require_enum(body, "tier_code", _TIER_CODES)
        tier_name = require_str(body, "tier_name")
        priority_rank = require_int(body, "priority_rank", non_negative=True)
        sponsor_ext = require_str(body, "sponsor_external_id")
        sponsor_disp = optional_str(body, "sponsor_display_name", default="") or ""
        contracted_units = require_int(body, "contracted_units", non_negative=True)
        kinds_allowed_raw = require_list(
            body, "contract_kinds_allowed", element_type=str
        )
        for kind in kinds_allowed_raw:
            if kind not in EXPOSURE_KINDS:
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE",
                    f"contract_kinds_allowed entry {kind!r} is not a known exposure kind",
                )

        row = {
            "festival_id": festival_id,
            "tier_code": tier_code,
            "tier_name": tier_name,
            "priority_rank": priority_rank,
            "sponsor_external_id": sponsor_ext,
            "sponsor_display_name": sponsor_disp,
            "contracted_units": contracted_units,
            "contract_kinds_allowed": list(kinds_allowed_raw),
            "projected_fulfilment_pct": 0.0,
            "actual_fulfilment_pct": None,
            "tier_remaining_quota": contracted_units,
            "sponsor_payout_total_cents": None,
        }
        stamp_create(row)
        DB.sponsor_tiers[row["id"]] = row
        append_audit(
            festival_id=festival_id,
            event_category="EXPOSURE",
            subject_entity_type="SponsorTier",
            subject_entity_id=row["id"],
            payload_summary=(
                f"sponsor tier registered: {tier_code}/{sponsor_ext} with "
                f"contracted_units={contracted_units}"
            ),
        )
        out = _payload(row)
    return success_envelope(out, http_status=201)


@bp.route("/festivals/<festival_id>/sponsor-tiers", methods=["GET"])
def list_tiers(festival_id: str):
    require_role(ANY_ROLE)
    tier_filter = request.args.get("tier_code")
    with GLOBAL_LOCK:
        resolve_festival(festival_id)

        def _pred(r: dict) -> bool:
            if r.get("festival_id") != festival_id:
                return False
            if tier_filter is not None and r.get("tier_code") != tier_filter:
                return False
            return True

        rows = list_by_predicate(DB.sponsor_tiers, _pred)
        # Refresh each row's live projection before serialisation.
        for r in rows:
            recompute_tier_projection(r["id"])
        page, meta = paginate_list(rows, request.args)
        out = [_payload(r) for r in page]
    return success_envelope(out, pagination=meta)


@bp.route("/festivals/<festival_id>/sponsor-tiers/<tier_id>", methods=["GET"])
def read_tier(festival_id: str, tier_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        t = _resolve(festival_id, tier_id)
        recompute_tier_projection(tier_id)
        out = _payload(t)
    return success_envelope(out)


@bp.route(
    "/festivals/<festival_id>/sponsor-tiers/<tier_id>/fulfilment-report",
    methods=["GET"],
)
def read_fulfilment_report(festival_id: str, tier_id: str):
    require_role(["SponsorshipAdmin", "FestivalProducer", "AuditViewer"])
    with GLOBAL_LOCK:
        tier = _resolve(festival_id, tier_id)
        report = fulfilment_report_payload(tier_id)
    return success_envelope(report)


@bp.route(
    "/festivals/<festival_id>/sponsor-allocation-sweep", methods=["POST"]
)
def sponsor_allocation_sweep(festival_id: str):
    require_role(["SponsorshipAdmin", "FestivalProducer"])
    with GLOBAL_LOCK:
        resolve_festival(festival_id)
        if festival_id in DB.sweep_locked_festivals:
            raise ApiError(
                "ERR_CONCURRENT_SWEEP_IN_PROGRESS",
                "another sponsor-allocation-sweep is in progress for this festival",
            )
        DB.sweep_locked_festivals.add(festival_id)
        try:
            summary = run_waterfall(festival_id)
        finally:
            DB.sweep_locked_festivals.discard(festival_id)
    # Serialise the per-kind disbursement vector in a JSON-safe shape.
    out = {
        "festival_id": festival_id,
        "disbursement": {k: [{"exposure_allocation_id": aid, "actual_units": units} for aid, units in v] for k, v in summary.items()},
    }
    return success_envelope(out)


def register(app: Flask) -> None:
    app.register_blueprint(bp)
