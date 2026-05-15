"""Shared imports/utilities the per-resource blueprints reuse."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from flask import Blueprint, Response, request, g

from .. import GLOBAL_LOCK
from ..audit import append_audit, append_occ_conflict, list_audit_for_festival
from ..auth import actor_tuple, require_audit_log_allowlist, require_role
from ..constants import AUDIT_LOG_ALLOWLIST, ROLE_NAMES, SYNC_TARGETS
from ..envelope import (
    epoch_to_iso8601,
    error_envelope_response,
    fresh_uuid,
    paginate_list,
    server_now_iso8601,
    success_envelope,
)
from ..errors import ApiError, ERROR_CATALOG, lookup_status
from ..idempotency import idempotency_lookup_or_store
from ..services import (
    apply_provisional_refunds_for_cancel,
    assert_within_festival_window,
    assert_sound_check_window,
    cascade_program_item_cancel,
    check_artist_multi_festival_conflict,
    check_artist_self_overlap,
    check_artist_travel_buffer,
    check_blocking_riders_for_announce,
    check_equipment_kit_capacity,
    check_rehearsal_room_overlap,
    check_stage_changeover_overlap,
    check_team_warmup_overlap,
    check_unblocking_riders_for_publish,
    equipment_kit_peak_demand_for_kit,
    festival_cancel_fanout,
    festival_close_cascade,
    fire_clock_thresholds,
    fulfilment_report_payload,
    recompute_all_tier_projections_for_festival,
    recompute_outstanding_tickets_total,
    recompute_slot_priority,
    recompute_tier_actuals_post_close,
    recompute_tier_projection,
    resolve_festival,
    revert_provisional_refunds,
    run_waterfall,
    seed_sync_envelopes,
    zone_capacity_check,
)
from ..storage import (
    DB,
    check_if_match,
    child_belongs,
    find_or_404,
    get_json_body,
    logical_now,
    logical_now_iso,
    real_now_unix,
    stamp_create,
    stamp_update,
)
from ..validators import (
    optional_bool,
    optional_int,
    optional_list,
    optional_str,
    require_bool,
    require_dict,
    require_enum,
    require_field,
    require_int,
    require_list,
    require_str,
    require_window,
)

# The string "Any" allows every authenticated role through.
ANY_ROLE = ["Any"]


def list_by_predicate(
    collection: Dict[str, dict],
    predicate: Callable[[dict], bool],
    *,
    extra_filters: Optional[Callable[[dict], bool]] = None,
) -> List[dict]:
    """Return rows passing the predicates sorted by `created_at` ascending."""
    rows = [r for r in collection.values() if predicate(r)]
    if extra_filters is not None:
        rows = [r for r in rows if extra_filters(r)]
    rows.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    return rows


def make_blueprint(name: str, url_prefix: Optional[str] = None) -> Blueprint:
    return Blueprint(name, __name__, url_prefix=url_prefix or "")


def if_match_header() -> Optional[str]:
    """Return the request's `If-Match` header value, or None."""
    v = request.headers.get("If-Match")
    if v is None or v == "":
        return None
    return v
