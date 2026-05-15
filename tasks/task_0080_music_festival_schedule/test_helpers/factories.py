"""Payload factories for the Festival Program Schedule API.

One factory per create endpoint, emitting the input-source field set the
PRD §3 narrative names for that endpoint.  Each factory accepts
``**overrides`` so tests can pin the values that matter to the rule
being asserted while still benefitting from sensible defaults.

The factories also include the deterministic-random-seed convention
described in the PRD §3.5: the artist's `home_city` doubles as a fixed
deterministic seed for the priority-score tie-break, so when tests
need two artists to differ in tie-break order they pick distinct
`home_city` strings.

Append-only entities — RiderRequirement, FulfilmentLog, AuditEntry —
have factories that emit no `updated_at` and no `version`, per the
PRD §2.4 append-only contract.
"""
from __future__ import annotations

import random
import time
import uuid
from typing import Any, Dict, List, Optional

from .constants import (
    CATALOG_KINDS, DAY_SECONDS, TEST_DEFAULTS, THRESHOLDS,
)


# The deterministic-random seed for the test process.  The PRD §3.5 prose
# names the artist's `home_city` as the deterministic seed of the priority
# tie-break; this rng is the unrelated test-side seed for generating
# unique entity names so two parallel tests don't collide on a string.
_TEST_RNG_SEED = 20260514
_rng = random.Random(_TEST_RNG_SEED)


def _unique_suffix() -> str:
    """A short, deterministic-but-unique suffix for entity name strings."""
    # Combine the rng with a uuid4 fragment so concurrent test processes
    # do not collide on the same name.
    return f"{_rng.randrange(10**6):06d}-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Time anchors.  The PRD §2.4 declares every time as an integer Unix-seconds
# UTC.  The harness's clock-advance endpoint takes the system from
# real_now to the time tests want; for the time-fields in entity creation
# bodies we use offsets from a deterministic anchor so the windowing
# arithmetic is reproducible.
# ---------------------------------------------------------------------------

# The fixed anchor — a Wednesday in 2026 well before the test clock's
# logical wall clock is normally advanced.  Tests interpret this as the
# start of a festival window unless they pick their own.
TIME_ANCHOR_UNIX_SECONDS: int = 1_780_000_000   # arbitrary but stable for the test run

ONE_HOUR_SECONDS: int = 3600
ONE_DAY_SECONDS: int = DAY_SECONDS               # 86400


# ---------------------------------------------------------------------------
# Per-entity factories
# ---------------------------------------------------------------------------

def festival_payload(*, name: Optional[str] = None,
                     venue_name: Optional[str] = None,
                     start_time: Optional[int] = None,
                     end_time: Optional[int] = None,
                     day_count: Optional[int] = None,
                     **overrides: Any) -> Dict[str, Any]:
    """Create-festival body.

    Per PRD §2.4 the festival's `start_time` and `end_time` are integer
    Unix-seconds UTC, `end_time > start_time`, and the day count is the
    ceiling-divide of the second-delta by 86400.  When `day_count` is
    supplied and the times are not, the window is constructed so that the
    integer ceiling division of (end - start) by 86400 lands exactly at
    `day_count`.
    """
    if name is None:
        name = f"{TEST_DEFAULTS['FESTIVAL_NAME_PREFIX']}-{_unique_suffix()}"
    if venue_name is None:
        venue_name = str(TEST_DEFAULTS["VENUE_NAME"])
    if start_time is None:
        start_time = TIME_ANCHOR_UNIX_SECONDS
    if end_time is None:
        days = day_count or int(TEST_DEFAULTS["FESTIVAL_DAY_COUNT_DEFAULT"])
        # Use exactly `days` whole days so the ceiling-divide yields `days`.
        end_time = start_time + days * ONE_DAY_SECONDS
    body: Dict[str, Any] = {
        "name": name,
        "venue_name": venue_name,
        "start_time": int(start_time),
        "end_time": int(end_time),
    }
    body.update(overrides)
    return body


def stage_payload(*, stage_name: Optional[str] = None,
                  zone_capacity: Optional[int] = None,
                  changeover_buffer_seconds: Optional[int] = None,
                  equipment_kits: Optional[List[str]] = None,
                  is_emergency_substitute: bool = False,
                  **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "stage_name": stage_name or f"{TEST_DEFAULTS['STAGE_NAME_PREFIX']}-{_unique_suffix()}",
        "zone_capacity": int(zone_capacity if zone_capacity is not None
                             else TEST_DEFAULTS["ZONE_CAPACITY"]),
        "equipment_kits": list(equipment_kits) if equipment_kits is not None else [],
        "is_emergency_substitute": bool(is_emergency_substitute),
    }
    if changeover_buffer_seconds is not None:
        body["changeover_buffer_seconds"] = int(changeover_buffer_seconds)
    body.update(overrides)
    return body


def equipment_kit_payload(*, kit_code: Optional[str] = None,
                          total_units: Optional[int] = None,
                          description: str = "",
                          **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "kit_code": kit_code or f"{TEST_DEFAULTS['EQUIPMENT_KIT_CODE_PREFIX']}-{_unique_suffix()}",
        "total_units": int(total_units if total_units is not None
                           else TEST_DEFAULTS["EQUIPMENT_KIT_TOTAL_UNITS"]),
        "description": description,
    }
    body.update(overrides)
    return body


def artist_payload(*, stage_name: Optional[str] = None,
                   tier: str = "OPENER",
                   home_city: Optional[str] = None,
                   external_commitments: Optional[List[Dict[str, Any]]] = None,
                   minimum_travel_buffer_hours: Optional[int] = None,
                   **overrides: Any) -> Dict[str, Any]:
    """Create-artist body.  Artists are global per the PRD §2.1 prose and
    the §4 table — the path is /artists with no festival prefix."""
    body: Dict[str, Any] = {
        "stage_name": stage_name or f"Artist-{_unique_suffix()}",
        "tier": tier,
        "home_city": home_city or str(TEST_DEFAULTS["ARTIST_HOME_CITY"]),
        "external_commitments": list(external_commitments) if external_commitments is not None else [],
    }
    if minimum_travel_buffer_hours is not None:
        body["minimum_travel_buffer_hours"] = int(minimum_travel_buffer_hours)
    body.update(overrides)
    return body


def external_commitment(*, festival_external_id: str = "ExtFestX",
                        start_time: int = 0, end_time: int = 0,
                        city: str = "OtherCity") -> Dict[str, Any]:
    """One element of the artist's `external_commitments` array.  The
    PRD §3.2 names the four required fields."""
    return {
        "festival_external_id": festival_external_id,
        "start_time": int(start_time),
        "end_time": int(end_time),
        "city": city,
    }


def program_version_payload(*, version_label: Optional[str] = None,
                            **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "version_label": version_label
        or f"{TEST_DEFAULTS['VERSION_LABEL_PREFIX']}{_rng.randrange(1, 1000)}-test",
    }
    body.update(overrides)
    return body


def program_item_payload(*, program_version_id: str,
                         artist_id: str,
                         stage_id: str,
                         genre: str = "rock",
                         start_time: int,
                         end_time: int,
                         equipment_kit_codes: Optional[List[str]] = None,
                         **overrides: Any) -> Dict[str, Any]:
    """Create-program-item body.  The four required references are the
    program-version, the artist, the stage, and the [start, end) window.
    The `equipment_kit_codes` array is the per-item list of kit codes
    the act requires from the festival-wide catalogue.
    """
    body: Dict[str, Any] = {
        "program_version_id": program_version_id,
        "artist_id": artist_id,
        "stage_id": stage_id,
        "genre": genre,
        "start_time": int(start_time),
        "end_time": int(end_time),
        "equipment_kit_codes": list(equipment_kit_codes) if equipment_kit_codes is not None else [],
    }
    body.update(overrides)
    return body


def rider_payload(*, category: str = "TECHNICAL",
                  description: str = "test rider line",
                  is_blocking: bool = False,
                  **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "category": category,
        "description": description,
        "is_blocking": bool(is_blocking),
    }
    body.update(overrides)
    return body


def rider_fulfil_payload() -> Dict[str, Any]:
    """The PRD §3.3 rider-fulfilment PATCH body carries the `fulfilled:
    true` discriminator that flips the row's `fulfilled_at` from null to
    the server clock."""
    return {"fulfilled": True}


def sound_engineer_team_payload(*, team_name: Optional[str] = None,
                                head_engineer_name: str = "",
                                warmup_minutes: Optional[int] = None,
                                **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "team_name": team_name or f"{TEST_DEFAULTS['TEAM_NAME_PREFIX']}-{_unique_suffix()}",
        "head_engineer_name": head_engineer_name or str(TEST_DEFAULTS["HEAD_ENGINEER_NAME"]),
    }
    if warmup_minutes is not None:
        body["warmup_minutes"] = int(warmup_minutes)
    body.update(overrides)
    return body


def sound_check_create_payload(*, scheduled_window_start: Optional[int] = None,
                               scheduled_window_end: Optional[int] = None,
                               **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if scheduled_window_start is not None:
        body["scheduled_window_start"] = int(scheduled_window_start)
    if scheduled_window_end is not None:
        body["scheduled_window_end"] = int(scheduled_window_end)
    body.update(overrides)
    return body


def sound_check_schedule_payload(*, sound_engineer_team_id: str,
                                 scheduled_window_start: int,
                                 scheduled_window_end: int,
                                 **overrides: Any) -> Dict[str, Any]:
    """The PATCH body that drives REQUESTED → SCHEDULED.  Per PRD §3.5
    the team_id and the window pair are the three input fields."""
    body: Dict[str, Any] = {
        "sound_engineer_team_id": sound_engineer_team_id,
        "scheduled_window_start": int(scheduled_window_start),
        "scheduled_window_end": int(scheduled_window_end),
    }
    body.update(overrides)
    return body


def rehearsal_payload(*, artist_id: str,
                      rehearsal_type: str,
                      start_time: int,
                      end_time: int,
                      stage_id: Optional[str] = None,
                      rehearsal_room_name: Optional[str] = None,
                      **overrides: Any) -> Dict[str, Any]:
    """Create-rehearsal body.  Per PRD §3.5 a STAGE-type rehearsal carries
    `stage_id` (and the disjoint string namespace's `rehearsal_room_name`
    is null), a ROOM-type rehearsal carries `rehearsal_room_name` (and
    `stage_id` is null), and the two namespaces never conflict with each
    other.  We pass through whichever the caller supplies and the server
    enforces the required-when-type-is rule."""
    body: Dict[str, Any] = {
        "artist_id": artist_id,
        "rehearsal_type": rehearsal_type,
        "start_time": int(start_time),
        "end_time": int(end_time),
    }
    if rehearsal_type == "STAGE":
        assert stage_id is not None, "STAGE-type rehearsal requires stage_id per PRD §3.5"
        body["stage_id"] = stage_id
    elif rehearsal_type == "ROOM":
        if rehearsal_room_name is None:
            rehearsal_room_name = str(TEST_DEFAULTS["REHEARSAL_ROOM_NAME"]) + "-" + _unique_suffix()
        body["rehearsal_room_name"] = rehearsal_room_name
    body.update(overrides)
    return body


def ticket_type_payload(*, ticket_class: str = "SINGLE_DAY",
                        tied_program_item_ids: Optional[List[str]] = None,
                        zone_name: Optional[str] = None,
                        unit_price_cents: Optional[int] = None,
                        **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "ticket_class": ticket_class,
        "tied_program_item_ids": list(tied_program_item_ids or []),
        "zone_name": zone_name or str(TEST_DEFAULTS["ZONE_NAME"]),
        "unit_price_cents": int(unit_price_cents
                                if unit_price_cents is not None
                                else TEST_DEFAULTS["UNIT_PRICE_CENTS"]),
    }
    body.update(overrides)
    return body


def ticket_issue_payload(*, count: int,
                         idempotency_key: Optional[str] = None,
                         **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"count": int(count)}
    if idempotency_key is not None:
        body["idempotency_key"] = str(idempotency_key)
    body.update(overrides)
    return body


def sponsor_tier_payload(*, tier_code: str,
                         tier_name: Optional[str] = None,
                         priority_rank: int = 1,
                         sponsor_external_id: Optional[str] = None,
                         sponsor_display_name: Optional[str] = None,
                         contracted_units: Optional[int] = None,
                         contract_kinds_allowed: Optional[List[str]] = None,
                         **overrides: Any) -> Dict[str, Any]:
    sxid = sponsor_external_id or f"sponsor-ext-{_unique_suffix()}"
    body: Dict[str, Any] = {
        "tier_code": tier_code,
        "tier_name": tier_name or f"{tier_code.title()} Tier {sxid}",
        "priority_rank": int(priority_rank),
        "sponsor_external_id": sxid,
        "sponsor_display_name": sponsor_display_name or f"Sponsor {sxid}",
        "contracted_units": int(contracted_units if contracted_units is not None
                                else TEST_DEFAULTS["SPONSOR_CONTRACTED_UNITS"]),
        "contract_kinds_allowed": list(contract_kinds_allowed) if contract_kinds_allowed is not None
                                  else list(CATALOG_KINDS),
    }
    body.update(overrides)
    return body


def exposure_catalog_payload(*, stage_name: int = 100,
                             screen_time: int = 100,
                             artist_mention: int = 100,
                             branded_zone: int = 10,
                             **overrides: Any) -> Dict[str, Any]:
    """The PRD §2.8 catalog-dictionary payload.  The four allowed keys of
    the inner `catalog` dict are the four kind strings.  Defaults match
    the §3.6 worked-waterfall input: 10 units of branded_zone with the
    other three kinds amply provisioned at 100 each so they don't
    interfere with the branded-zone-pool exhaustion test.
    """
    catalog = {
        "stage_name": int(stage_name),
        "screen_time": int(screen_time),
        "artist_mention": int(artist_mention),
        "branded_zone": int(branded_zone),
    }
    catalog.update({k: v for k, v in overrides.items() if k in CATALOG_KINDS})
    return {"catalog": catalog}


def exposure_allocation_payload(*, kind: str,
                                requested_units: int,
                                program_item_id: Optional[str] = None,
                                pinned_rate_cents_per_unit: Optional[int] = None,
                                **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "kind": kind,
        "requested_units": int(requested_units),
    }
    if program_item_id is not None:
        body["program_item_id"] = program_item_id
    if pinned_rate_cents_per_unit is not None:
        body["pinned_rate_cents_per_unit"] = int(pinned_rate_cents_per_unit)
    body.update(overrides)
    return body


def exposure_deliver_payload(*, units: int,
                             note: str = "",
                             **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"units": int(units), "note": note}
    body.update(overrides)
    return body


def exposure_void_payload(*, reason: str,
                          units: Optional[int] = None,
                          **overrides: Any) -> Dict[str, Any]:
    """Per PRD §3.6 the `reason` string is required (missing returns
    ERR_MISSING_VOID_REASON) and the optional `units` field defaults to
    the allocation's current delivered_units so the inverse cancels the
    running total cleanly per the conservation invariant of §3.6."""
    body: Dict[str, Any] = {"reason": str(reason)}
    if units is not None:
        body["units"] = int(units)
    body.update(overrides)
    return body


def schedule_change_payload(*, change_kind: str,
                            target_program_item_id: Optional[str] = None,
                            payload: Optional[Dict[str, Any]] = None,
                            idempotency_key: Optional[str] = None,
                            **overrides: Any) -> Dict[str, Any]:
    """Create-schedule-change body.  The `change_kind` discriminator is
    the §3.4 enum from {ITEM_CANCEL, ITEM_RESCHEDULE, STAGE_SWAP,
    VERSION_PUBLISH, TICKET_NOTIFY}; the `payload` shape is keyed on the
    discriminator per the PRD §3.4 prose."""
    body: Dict[str, Any] = {
        "change_kind": change_kind,
        "payload": dict(payload) if payload is not None else {},
    }
    if target_program_item_id is not None:
        body["target_program_item_id"] = target_program_item_id
    if idempotency_key is not None:
        body["idempotency_key"] = str(idempotency_key)
    body.update(overrides)
    return body


def schedule_reject_payload(*, reason: str) -> Dict[str, Any]:
    """The PRD §3.4 reject body requires a `reason` string; missing
    surfaces as ERR_MISSING_REJECTION_REASON at HTTP 400."""
    return {"reason": str(reason)}


def revision_return_payload(*, reason: str) -> Dict[str, Any]:
    """The PRD §3.3 return-for-revision body requires a `reason` string;
    missing surfaces as ERR_MISSING_REVISION_REASON at HTTP 400."""
    return {"reason": str(reason)}


def cancel_program_item_payload(*, reason: str,
                                idempotency_key: Optional[str] = None,
                                **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"reason": str(reason)}
    if idempotency_key is not None:
        body["idempotency_key"] = str(idempotency_key)
    body.update(overrides)
    return body


def festival_cancel_payload(*, reason: str = "test-festival-cancel") -> Dict[str, Any]:
    return {"reason": str(reason)}


def waive_sound_check_payload(*, reason: str = "test-waive") -> Dict[str, Any]:
    return {"reason": str(reason)}


def cancel_sound_check_payload(*, reason: str = "test-sc-cancel") -> Dict[str, Any]:
    return {"reason": str(reason)}


def cancel_rehearsal_payload(*, reason: str = "test-r-cancel") -> Dict[str, Any]:
    return {"reason": str(reason)}


def suspend_ticket_type_payload(*, reason: str = "test-suspend") -> Dict[str, Any]:
    return {"reason": str(reason)}


# ---------------------------------------------------------------------------
# Operator-only test-harness payloads under /_clock, /_events, /_sweep
# ---------------------------------------------------------------------------

def clock_advance_payload(*, festival_id: Optional[str] = None,
                          delta_seconds: Optional[int] = None,
                          to_unix_seconds: Optional[int] = None) -> Dict[str, Any]:
    """The PRD §2.8 clock-advance body shape is `{festival_id?,
    delta_seconds?, to_unix_seconds?}` with exactly one of the two time
    arguments supplied.  Supplying neither or both surfaces as
    ERR_CLOCK_INVALID_ARGS, and a negative delta or a backward
    to_unix_seconds surfaces as ERR_CLOCK_ADVANCE_BACKWARD."""
    body: Dict[str, Any] = {}
    if festival_id is not None:
        body["festival_id"] = festival_id
    if delta_seconds is not None:
        body["delta_seconds"] = int(delta_seconds)
    if to_unix_seconds is not None:
        body["to_unix_seconds"] = int(to_unix_seconds)
    return body


def sync_ack_payload(*, festival_id: str,
                    schedule_change_id: str,
                    target: str,
                    succeeded: bool = True,
                    payload_hash: str = "deadbeef") -> Dict[str, Any]:
    """The PRD §2.8 sync-ack body: festival_id, schedule_change_id,
    target ∈ {ticketing, im, broadcasting, sponsor}, succeeded boolean,
    and the SHA-256 payload_hash echo from the external system."""
    return {
        "festival_id": festival_id,
        "schedule_change_id": schedule_change_id,
        "target": target,
        "succeeded": bool(succeeded),
        "payload_hash": payload_hash,
    }


def refund_confirmed_payload(*, festival_id: str,
                             schedule_change_id: str,
                             refund_breakdown: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The PRD §2.8 / §3.4 refund-confirmed body: an array of
    `{ticket_type_id, refunded_count_delta, final_cents_total_for_type}`
    rows.  The cross-festival guard ERR_CROSS_FESTIVAL_REFUND and the
    magnitude guard ERR_REFUND_EXCEEDS_PROVISIONAL fire if either
    invariant is broken by the body."""
    return {
        "festival_id": festival_id,
        "schedule_change_id": schedule_change_id,
        "refund_breakdown": list(refund_breakdown),
    }


def refund_breakdown_entry(*, ticket_type_id: str,
                            refunded_count_delta: int,
                            final_cents_total_for_type: int) -> Dict[str, Any]:
    return {
        "ticket_type_id": ticket_type_id,
        "refunded_count_delta": int(refunded_count_delta),
        "final_cents_total_for_type": int(final_cents_total_for_type),
    }


def sweep_payload(*, festival_id: str,
                  compute_payout: bool = False) -> Dict[str, Any]:
    return {
        "festival_id": festival_id,
        "compute_payout": bool(compute_payout),
    }


# ---------------------------------------------------------------------------
# Schedule-change-discriminated payload bodies for the inner `payload`
# field, keyed on the change_kind discriminator per PRD §3.4.
# ---------------------------------------------------------------------------

def item_cancel_inner_payload(*, reason: str = "weather") -> Dict[str, Any]:
    return {"reason": str(reason)}


def item_reschedule_inner_payload(*, new_start_time: int, new_end_time: int) -> Dict[str, Any]:
    return {"new_start_time": int(new_start_time),
            "new_end_time": int(new_end_time)}


def stage_swap_inner_payload(*, new_stage_id: str) -> Dict[str, Any]:
    return {"new_stage_id": str(new_stage_id)}


def ticket_notify_inner_payload(*, message: str = "test-notify") -> Dict[str, Any]:
    return {"message": str(message)}


def version_publish_inner_payload(*, program_version_id: str) -> Dict[str, Any]:
    return {"program_version_id": str(program_version_id)}


# ---------------------------------------------------------------------------
# Idempotency-key generator — the PRD §2.5 prose names the key as an
# opaque client-supplied string, so the generator just emits unique
# uuid-flavoured tokens.
# ---------------------------------------------------------------------------

def fresh_idempotency_key(prefix: str = "idem") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


__all__ = [
    "festival_payload", "stage_payload", "equipment_kit_payload",
    "artist_payload", "external_commitment", "program_version_payload",
    "program_item_payload", "rider_payload", "rider_fulfil_payload",
    "sound_engineer_team_payload", "sound_check_create_payload",
    "sound_check_schedule_payload",
    "rehearsal_payload", "ticket_type_payload", "ticket_issue_payload",
    "sponsor_tier_payload", "exposure_catalog_payload",
    "exposure_allocation_payload", "exposure_deliver_payload",
    "exposure_void_payload",
    "schedule_change_payload", "schedule_reject_payload",
    "revision_return_payload", "cancel_program_item_payload",
    "festival_cancel_payload", "waive_sound_check_payload",
    "cancel_sound_check_payload", "cancel_rehearsal_payload",
    "suspend_ticket_type_payload",
    "clock_advance_payload", "sync_ack_payload", "refund_confirmed_payload",
    "refund_breakdown_entry", "sweep_payload",
    "item_cancel_inner_payload", "item_reschedule_inner_payload",
    "stage_swap_inner_payload", "ticket_notify_inner_payload",
    "version_publish_inner_payload",
    "fresh_idempotency_key",
    "TIME_ANCHOR_UNIX_SECONDS", "ONE_HOUR_SECONDS", "ONE_DAY_SECONDS",
]
