"""Cross-cutting helpers shared by the route blueprints.

The blueprints stay short by delegating to focused helpers here.  This
module groups:

  - Festival window containment for a windowed-child entity (§2.4).
  - The zone-capacity walker for the ticket-issue path (§3.4).
  - The equipment-kit aggregate sweep wrapper that pulls the right
    set of existing intervals from `DB.program_items` and feeds the
    flavour-2 `equipment_kit_peak_concurrent` function.
  - The stage-changeover-buffer wrapper that pulls the right set of
    existing CONFIRMED|ANNOUNCED|ON_STAGE program-items and
    BOOKED|IN_PROGRESS stage-rehearsals on the same stage.
  - The artist cross-festival conflict and travel-buffer walker.
  - The sync-envelope seeding helper for the schedule-change apply path.
  - The cascade A, B, C side-effect runners.
  - The clock-advance threshold sweep that fires the time-gated
    transitions in PRD §2.8's deterministic order.
  - The waterfall allocator.
  - The provisional-and-final-refund integration for ITEM_CANCEL.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .audit import append_audit
from .calculations import (
    actual_fulfilment_pct,
    delivered_units_for_allocation,
    festival_day_count as _festival_day_count_calc,
    projected_fulfilment_pct,
    provisional_refund_for_change,
    slot_priority_score as _slot_priority_score_calc,
    sponsor_payout_total_cents,
    tier_remaining_quota_from_logs,
)
from .constants import (
    FESTIVAL_CLOSE_GRACE_SECONDS,
    REHEARSAL_GRACE_SECONDS,
    SPONSOR_PAYOUT_RATE_MILS_DEFAULT,
    SYNC_TARGETS,
    TEAM_HANDOFF_SECONDS,
    TRAVEL_HOURS_MIN,
    WATERFALL_TIER_ORDER,
)
from .envelope import epoch_to_iso8601, fresh_uuid, server_now_iso8601
from .errors import ApiError
from .intervals import (
    equipment_kit_peak_concurrent,
    half_open_overlaps,
    rehearsal_room_conflict,
    stage_changeover_conflict,
    team_warmup_conflict,
    within_window,
)
from .storage import DB, logical_now, real_now_unix, stamp_create, stamp_update


# ---------------------------------------------------------------------------
# Festival lookup helpers.
# ---------------------------------------------------------------------------


def resolve_festival(festival_id: str) -> dict:
    """Look up the festival or raise ERR_FESTIVAL_NOT_FOUND."""
    fest = DB.festivals.get(festival_id)
    if fest is None:
        raise ApiError("ERR_FESTIVAL_NOT_FOUND", f"festival {festival_id!r} not found")
    return fest


def recompute_outstanding_tickets_total(festival_id: str) -> None:
    """Refresh the festival's `outstanding_tickets_total` aggregate.

    Sum across all ticket types of `issued_count - refunded_count`.
    """
    total = 0
    for tt in DB.ticket_types.values():
        if tt.get("festival_id") != festival_id:
            continue
        total += int(tt.get("issued_count", 0)) - int(tt.get("refunded_count", 0))
    fest = DB.festivals.get(festival_id)
    if fest is not None:
        fest["outstanding_tickets_total"] = total


def assert_within_festival_window(
    festival: Dict[str, Any], start: int, end: int
) -> None:
    """The §2.4 child-window containment guard.  Half-open `[start, end)` ⊂ festival's window."""
    f_start = int(festival["start_time"])
    f_end = int(festival["end_time"])
    if not within_window((start, end), (f_start, f_end)):
        raise ApiError(
            "ERR_CHILD_WINDOW_OUT_OF_FESTIVAL_RANGE",
            f"window [{start},{end}) is not within the festival's window "
            f"[{f_start},{f_end})",
        )


# ---------------------------------------------------------------------------
# The four interval-arithmetic wrappers.
# ---------------------------------------------------------------------------


def _active_program_items_on_stage(
    festival_id: str, stage_id: str, exclude_item_id: Optional[str] = None
) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for pi in DB.program_items.values():
        if pi.get("festival_id") != festival_id:
            continue
        if pi.get("stage_id") != stage_id:
            continue
        if exclude_item_id is not None and pi["id"] == exclude_item_id:
            continue
        if pi.get("status") in ("CONFIRMED", "ANNOUNCED", "ON_STAGE"):
            out.append((int(pi["start_time"]), int(pi["end_time"])))
    # Stage rehearsals also count on the same stage's interval graph.
    for r in DB.rehearsals.values():
        if r.get("festival_id") != festival_id:
            continue
        if r.get("rehearsal_type") != "STAGE":
            continue
        if r.get("stage_id") != stage_id:
            continue
        if r.get("status") in ("BOOKED", "IN_PROGRESS"):
            out.append((int(r["start_time"]), int(r["end_time"])))
    return out


def check_stage_changeover_overlap(
    festival_id: str,
    stage_id: str,
    candidate_start: int,
    candidate_end: int,
    buffer_seconds: Optional[int],
    exclude_item_id: Optional[str] = None,
) -> None:
    """Flavour-1 overlap check; raises ERR_STAGE_CHANGEOVER_OVERLAP on conflict."""
    from .constants import STAGE_CHANGEOVER_BUFFER_SECONDS

    buf = buffer_seconds if buffer_seconds is not None else STAGE_CHANGEOVER_BUFFER_SECONDS
    intervals = _active_program_items_on_stage(festival_id, stage_id, exclude_item_id)
    if stage_changeover_conflict((candidate_start, candidate_end), intervals, buf):
        raise ApiError(
            "ERR_STAGE_CHANGEOVER_OVERLAP",
            f"stage {stage_id} has an overlapping booking within the "
            f"{buf}-second changeover buffer",
        )


def check_equipment_kit_capacity(
    festival_id: str,
    kit_codes: Sequence[str],
    candidate_start: int,
    candidate_end: int,
    candidate_stage_id: str,
    exclude_item_id: Optional[str] = None,
) -> None:
    """Flavour-2 aggregate-capacity sweep, plus the wireability guard from §3.3.

    The wireability check is `every kit_code in candidate.equipment_kit_codes
    must appear in the parent Stage.equipment_kits[]`, otherwise
    ERR_STAGE_LACKS_EQUIPMENT_KIT.

    The aggregate-capacity check is the festival-wide `+1 over the candidate's
    window` peak versus the kit's `total_units` ceiling.
    """
    # Wireability.
    stage = DB.stages.get(candidate_stage_id)
    if stage is None:
        raise ApiError("ERR_STAGE_NOT_FOUND", f"stage {candidate_stage_id} not found")
    stage_kits = set(stage.get("equipment_kits", []))
    for code in kit_codes:
        if code not in stage_kits:
            raise ApiError(
                "ERR_STAGE_LACKS_EQUIPMENT_KIT",
                f"stage {candidate_stage_id} is not wired for equipment kit {code!r}",
            )

    # Aggregate-capacity sweep, one kit_code at a time.
    if not kit_codes:
        return
    # Build a kit_code -> total_units map from the festival's equipment kits.
    kit_index: Dict[str, dict] = {}
    for k in DB.equipment_kits.values():
        if k.get("festival_id") != festival_id:
            continue
        kit_index[k["kit_code"]] = k

    for code in kit_codes:
        kit_row = kit_index.get(code)
        if kit_row is None:
            # An undeclared kit_code on the stage's equipment_kits is a
            # configuration error and surfaces under the same wireability
            # error since the stage cannot legitimately claim to wire a
            # kit the festival's catalog doesn't list.
            raise ApiError(
                "ERR_STAGE_LACKS_EQUIPMENT_KIT",
                f"festival has no equipment kit with kit_code {code!r}",
            )
        total_units = int(kit_row.get("total_units", 0))

        # Festival-wide existing intervals of CONFIRMED|ANNOUNCED|ON_STAGE items
        # whose equipment_kit_codes contain `code`.
        existing: List[Tuple[int, int]] = []
        for pi in DB.program_items.values():
            if pi.get("festival_id") != festival_id:
                continue
            if exclude_item_id is not None and pi["id"] == exclude_item_id:
                continue
            if pi.get("status") not in ("CONFIRMED", "ANNOUNCED", "ON_STAGE"):
                continue
            kits_on_item = set(pi.get("equipment_kit_codes", []))
            if code not in kits_on_item:
                continue
            existing.append((int(pi["start_time"]), int(pi["end_time"])))

        # The peak overlap among existings during the candidate's window,
        # PLUS the candidate itself adds 1 over its whole window.  The
        # candidate's +1 is constant across the window, so the peak
        # simultaneous-users count is `max_overlap_existing + 1`.
        peak_existing = equipment_kit_peak_concurrent(
            (candidate_start, candidate_end), existing
        )
        peak_with_candidate = peak_existing + 1
        if peak_with_candidate > total_units:
            raise ApiError(
                "ERR_EQUIPMENT_KIT_OVERSUBSCRIBED",
                f"equipment kit {code!r} oversubscribed: peak demand "
                f"{peak_with_candidate} exceeds total_units {total_units}",
            )


def equipment_kit_peak_demand_for_kit(festival_id: str, kit_code: str) -> int:
    """For the §3.2 PATCH-equipment-kit `ERR_EXPOSURE_CATALOG_BELOW_DISBURSED` reuse.

    Returns the peak concurrent demand for ``kit_code`` across the
    festival's CONFIRMED|ANNOUNCED|ON_STAGE program items.  The endpoint
    rejects a new `total_units` value below this number.
    """
    existing: List[Tuple[int, int]] = []
    for pi in DB.program_items.values():
        if pi.get("festival_id") != festival_id:
            continue
        if pi.get("status") not in ("CONFIRMED", "ANNOUNCED", "ON_STAGE"):
            continue
        if kit_code not in set(pi.get("equipment_kit_codes", [])):
            continue
        existing.append((int(pi["start_time"]), int(pi["end_time"])))
    if not existing:
        return 0
    # Take the festival-wide sweep over the whole festival's window — the
    # peak count of overlapping existing intervals.  An empty `candidate`
    # window does not work, so we sweep over the union of all the existings'
    # spans.
    all_starts = [s for s, _ in existing]
    all_ends = [e for _, e in existing]
    candidate = (min(all_starts), max(all_ends))
    return equipment_kit_peak_concurrent(candidate, existing)


def _team_existing_slots(team_id: str, exclude_slot_id: Optional[str]) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for s in DB.sound_check_slots.values():
        if s.get("sound_engineer_team_id") != team_id:
            continue
        if exclude_slot_id is not None and s["id"] == exclude_slot_id:
            continue
        if s.get("status") not in ("SCHEDULED", "COMPLETED"):
            continue
        if s.get("scheduled_window_start") is None or s.get("scheduled_window_end") is None:
            continue
        out.append((int(s["scheduled_window_start"]), int(s["scheduled_window_end"])))
    return out


def check_team_warmup_overlap(
    team: dict,
    candidate_start: int,
    candidate_end: int,
    exclude_slot_id: Optional[str] = None,
) -> None:
    """Flavour-3 closed-closed warmup-padded team overlap, raises ERR_ENGINEER_TEAM_DOUBLE_BOOKED."""
    warmup = int(team.get("warmup_minutes", 0)) or 0
    if warmup == 0:
        from .constants import TEAM_WARMUP_MINUTES

        warmup = TEAM_WARMUP_MINUTES
    existings = _team_existing_slots(team["id"], exclude_slot_id)
    if team_warmup_conflict(
        (candidate_start, candidate_end), existings, warmup_minutes=warmup
    ):
        raise ApiError(
            "ERR_ENGINEER_TEAM_DOUBLE_BOOKED",
            f"team {team['id']} would double-book within the {warmup}-minute warmup window",
        )


def check_rehearsal_room_overlap(
    festival_id: str,
    room_name: str,
    candidate_start: int,
    candidate_end: int,
    exclude_rehearsal_id: Optional[str] = None,
) -> None:
    """Flavour-4 half-open same-name room overlap.  Raises ERR_REHEARSAL_ROOM_OVERLAP."""
    existings: List[Tuple[int, int]] = []
    for r in DB.rehearsals.values():
        if r.get("festival_id") != festival_id:
            continue
        if r.get("rehearsal_type") != "ROOM":
            continue
        if exclude_rehearsal_id is not None and r["id"] == exclude_rehearsal_id:
            continue
        if r.get("rehearsal_room_name") != room_name:
            continue
        if r.get("status") not in ("BOOKED", "IN_PROGRESS"):
            continue
        existings.append((int(r["start_time"]), int(r["end_time"])))
    if rehearsal_room_conflict((candidate_start, candidate_end), existings):
        raise ApiError(
            "ERR_REHEARSAL_ROOM_OVERLAP",
            f"rehearsal room {room_name!r} has an overlapping booking",
        )


# ---------------------------------------------------------------------------
# Artist temporal checks.
# ---------------------------------------------------------------------------


def check_artist_multi_festival_conflict(
    artist: dict,
    candidate_start: int,
    candidate_end: int,
) -> None:
    """§3.5 priority-11 check.

    The candidate's half-open window must not intersect any of the artist's
    `external_commitments` half-open windows.  Cross-festival visibility
    is via the artist's array (per the PRD prose).
    """
    cand = (candidate_start, candidate_end)
    for c in artist.get("external_commitments", []) or []:
        c_s = int(c.get("start_time", 0))
        c_e = int(c.get("end_time", 0))
        if half_open_overlaps(cand, (c_s, c_e)):
            raise ApiError(
                "ERR_ARTIST_MULTI_FESTIVAL_CONFLICT",
                f"artist {artist['id']} has an external commitment overlapping the slot",
            )


def check_artist_travel_buffer(
    artist: dict,
    candidate_start: int,
) -> None:
    """§3.5 priority-12 travel-buffer gap check.

    Find the latest preceding external commitment (whose end_time ≤
    candidate_start).  When one exists, the gap in seconds from its
    end_time to candidate_start must be ≥ `minimum_travel_buffer_hours
    * 3600`.  The boundary is inclusive (equality is acceptable);
    strict less-than rejects with ERR_ARTIST_TRAVEL_BUFFER_VIOLATION.
    """
    min_hours = artist.get("minimum_travel_buffer_hours")
    if min_hours is None:
        min_hours = TRAVEL_HOURS_MIN
    min_seconds = int(min_hours) * 3600
    latest_end: Optional[int] = None
    for c in artist.get("external_commitments", []) or []:
        c_e = int(c.get("end_time", 0))
        if c_e <= candidate_start:
            if latest_end is None or c_e > latest_end:
                latest_end = c_e
    if latest_end is None:
        return
    gap = candidate_start - latest_end
    if gap < min_seconds:
        raise ApiError(
            "ERR_ARTIST_TRAVEL_BUFFER_VIOLATION",
            f"artist travel buffer is {gap}s, less than the required {min_seconds}s",
        )


def check_artist_self_overlap(
    artist_id: str,
    candidate_start: int,
    candidate_end: int,
    exclude_program_item_id: Optional[str] = None,
) -> None:
    """§3.5 priority-13 self-overlap across **any** festival.

    The same artist cannot have two CONFIRMED|ANNOUNCED|ON_STAGE program
    items with overlapping half-open windows in the system, regardless of
    which festival they belong to.
    """
    cand = (candidate_start, candidate_end)
    for pi in DB.program_items.values():
        if pi.get("artist_id") != artist_id:
            continue
        if exclude_program_item_id is not None and pi["id"] == exclude_program_item_id:
            continue
        if pi.get("status") not in ("CONFIRMED", "ANNOUNCED", "ON_STAGE"):
            continue
        other = (int(pi["start_time"]), int(pi["end_time"]))
        if half_open_overlaps(cand, other):
            raise ApiError(
                "ERR_ARTIST_SELF_OVERLAP",
                f"artist {artist_id} has another active item overlapping this window",
            )


# ---------------------------------------------------------------------------
# Sync envelope helper.
# ---------------------------------------------------------------------------


def _payload_hash(payload: Any) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def seed_sync_envelopes(
    schedule_change: dict, payload_for_hash: Any
) -> None:
    """Initialise the four-element `sync_envelopes` array on a freshly-applied change."""
    now_iso = server_now_iso8601()
    payload_hash = _payload_hash(payload_for_hash)
    schedule_change["sync_envelopes"] = [
        {
            "target": target,
            "status": "QUEUED",
            "queued_at": now_iso,
            "acked_at": None,
            "payload_hash": payload_hash,
        }
        for target in SYNC_TARGETS
    ]


# ---------------------------------------------------------------------------
# Slot priority recomputation.
# ---------------------------------------------------------------------------


def recompute_slot_priority(program_item: dict) -> Decimal:
    """Compute and assign `slot_priority_score`.

    Reads the parent artist's tier and `external_commitments`, and the
    item's rider-count.  Returns the new Decimal value.
    """
    artist = DB.artists.get(program_item.get("artist_id", ""))
    if artist is None:
        # Defensive: a dangling artist_id means the score is zero.
        program_item["slot_priority_score"] = float(Decimal("0.00"))
        return Decimal("0.00")
    rider_count = sum(
        1
        for r in DB.riders.values()
        if r.get("program_item_id") == program_item["id"]
    )
    score = _slot_priority_score_calc(
        artist.get("tier", "SURPRISE"),
        artist.get("external_commitments", []) or [],
        int(program_item["start_time"]),
        int(program_item["end_time"]),
        rider_count,
    )
    # Surface as JSON-friendly float; the Decimal is the authoritative
    # value but the wire format is a number with two decimals.
    program_item["slot_priority_score"] = float(score)
    return score


# ---------------------------------------------------------------------------
# Cascade A: ScheduleChange.apply of kind ITEM_CANCEL or direct cancel.
#
# Link 1: ProgramItem flips to CANCELLED (the caller handles this).
# Link 2: every REQUESTED|SCHEDULED SoundCheckSlot under the item flips to CANCELLED.
# Link 3: each cancelled slot's SoundEngineerTeam, if the team's
# current_booking_id equals the slot's id, flips BUSY → AVAILABLE
# with current_booking_id cleared and a STATE_TRANSITION audit row.
#
# Cascade B (parallel to A): every PLANNED|DELIVERED ExposureAllocation
# tied to the cancelled item flips to VOIDED, appends a FulfilmentLog of
# event_type PROGRAM_VOIDED whose `units` is the current
# `delivered_units` magnitude (so the inverse cleanly cancels), and
# triggers the parent SponsorTier's projected_fulfilment_pct and
# tier_remaining_quota to be recomputed.
# ---------------------------------------------------------------------------


def cascade_program_item_cancel(
    festival_id: str,
    program_item_id: str,
    *,
    actor_user_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    summary_prefix: str = "Item cancelled",
) -> Dict[str, Any]:
    """Run cascades A's sound-check leg and B's exposure-allocation leg.

    The caller is responsible for the link-1 audit entry on the program
    item itself.  This function writes the link-2/3 audit entries for
    the slot cancel, the team release, the exposure void, and the
    sponsor-tier recomputation.

    Returns a summary dict with the counts the audit's `payload_summary`
    can reference: `{slots_cancelled, teams_freed, allocations_voided,
    tickets_refundable_count}`.
    """
    slots_cancelled = 0
    teams_freed = 0
    for slot in list(DB.sound_check_slots.values()):
        if slot.get("program_item_id") != program_item_id:
            continue
        if slot.get("status") not in ("REQUESTED", "SCHEDULED"):
            continue
        from_state = slot["status"]
        was_scheduled = from_state == "SCHEDULED"
        slot["status"] = "CANCELLED"
        stamp_update(slot)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="SoundCheckSlot",
            subject_entity_id=slot["id"],
            from_state=from_state,
            to_state="CANCELLED",
            payload_summary=f"sound-check slot cancelled by cascade A from program item {program_item_id}",
            actor_user_id=actor_user_id or "system",
            actor_role=actor_role or "system",
        )
        slots_cancelled += 1

        # Link 3: free the team if it was committed to this slot.
        team_id = slot.get("sound_engineer_team_id")
        if was_scheduled and team_id:
            team = DB.sound_engineer_teams.get(team_id)
            if (
                team is not None
                and team.get("status") == "BUSY"
                and team.get("current_booking_id") == slot["id"]
            ):
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
                    payload_summary=f"team freed by cascade A from sound-check slot {slot['id']}",
                    actor_user_id="system",
                    actor_role="system",
                )
                teams_freed += 1

        # Update the parent program item's parallel sound_check_status axis.
        item = DB.program_items.get(program_item_id)
        if item is not None:
            # Any other non-cancelled slot for the same item flips axis to REQUESTED, else NOT_REQUIRED.
            other_active = any(
                s.get("program_item_id") == program_item_id
                and s.get("status") not in ("CANCELLED",)
                and s["id"] != slot["id"]
                for s in DB.sound_check_slots.values()
            )
            new_axis = "REQUESTED" if other_active else "NOT_REQUIRED"
            if item.get("sound_check_status") != new_axis:
                item["sound_check_status"] = new_axis
                # Don't bump the item's `version` for the parallel axis flip
                # because the lifecycle axis is the authoritative version
                # driver per §2.4 and the test suite's OCC pins.

    # Cascade B: exposure allocations tied to this program item.
    allocations_voided = 0
    affected_tier_ids: set[str] = set()
    for alloc in list(DB.exposure_allocations.values()):
        if alloc.get("festival_id") != festival_id:
            continue
        if alloc.get("program_item_id") != program_item_id:
            continue
        if alloc.get("status") not in ("PLANNED", "DELIVERED"):
            continue
        prior_status = alloc["status"]
        # Determine the magnitude to write into the PROGRAM_VOIDED row.
        current_delivered = delivered_units_for_allocation(
            alloc["id"], DB.fulfilment_logs.values()
        )
        # The PRD: "the units field equals the allocation's current
        # delivered units" so the running sum returns to zero.  When the
        # allocation has never been delivered (PLANNED state), delivered
        # is zero and we write a zero-units PROGRAM_VOIDED row purely as
        # the audit-stream evidence of the cascade.
        log_id = fresh_uuid()
        log_row = {
            "id": log_id,
            "exposure_allocation_id": alloc["id"],
            "program_item_id": program_item_id,
            "event_type": "PROGRAM_VOIDED",
            "units": max(0, int(current_delivered)),
            "note": f"cascade B from program-item-cancel of {program_item_id}",
            "created_at": server_now_iso8601(),
        }
        DB.fulfilment_logs[log_id] = log_row

        alloc["status"] = "VOIDED"
        alloc["delivered_units"] = 0
        stamp_update(alloc)
        append_audit(
            festival_id=festival_id,
            event_category="EXPOSURE",
            subject_entity_type="ExposureAllocation",
            subject_entity_id=alloc["id"],
            from_state=prior_status,
            to_state="VOIDED",
            payload_summary=(
                f"exposure allocation voided by cascade B from program-item-cancel "
                f"{program_item_id}; magnitude={current_delivered} units"
            ),
            actor_user_id="system",
            actor_role="system",
        )
        affected_tier_ids.add(alloc["sponsor_tier_id"])
        allocations_voided += 1

    # Recompute the parent tiers' projected and quota figures.
    for tier_id in affected_tier_ids:
        recompute_tier_projection(tier_id)

    return {
        "slots_cancelled": slots_cancelled,
        "teams_freed": teams_freed,
        "allocations_voided": allocations_voided,
    }


# ---------------------------------------------------------------------------
# Refund cascade for an ITEM_CANCEL schedule-change apply.
# ---------------------------------------------------------------------------


def apply_provisional_refunds_for_cancel(
    festival: dict,
    program_item_id: str,
    schedule_change_id: str,
) -> int:
    """Run the §3.4 forward-looking refund computation and stamp the per-type buckets.

    Returns the across-types `provisional_refund_cents_total` integer
    the apply path writes to the schedule-change row.
    """
    festival_id = festival["id"]
    fdc = int(festival.get("festival_day_count", 1)) or 1

    # The set S of ticket types whose `tied_program_item_ids` contains the
    # cancelled program item.
    affected: List[dict] = []
    for tt in DB.ticket_types.values():
        if tt.get("festival_id") != festival_id:
            continue
        ties = list(tt.get("tied_program_item_ids", []) or [])
        if program_item_id in ties:
            affected.append(tt)

    total, per_type = provisional_refund_for_change(
        affected,
        cancelled_days=1,
        festival_day_count_value=fdc,
    )

    # Bump each affected type's `provisional_refund_cents_outstanding` bucket
    # by the per-type figure and bump the type's version.
    attribution: Dict[str, int] = {}
    for tt in affected:
        delta = int(per_type.get(tt["id"], 0))
        if delta == 0:
            continue
        tt["provisional_refund_cents_outstanding"] = int(
            tt.get("provisional_refund_cents_outstanding", 0)
        ) + delta
        stamp_update(tt)
        attribution[tt["id"]] = delta
        append_audit(
            festival_id=festival_id,
            event_category="SCHEDULE_CHANGE",
            subject_entity_type="TicketType",
            subject_entity_id=tt["id"],
            payload_summary=(
                f"provisional refund of {delta} cents pencilled for change {schedule_change_id}, "
                f"item {program_item_id}, outstanding tickets "
                f"{int(tt['issued_count']) - int(tt['refunded_count'])}"
            ),
            actor_user_id="system",
            actor_role="system",
        )

    DB.refund_attributions[schedule_change_id] = attribution
    return int(total)


def revert_provisional_refunds(schedule_change_id: str, festival_id: str) -> None:
    """Inverse of `apply_provisional_refunds_for_cancel` for the revert path.

    Decrements each affected ticket type's `provisional_refund_cents_outstanding`
    by the previously-attributed amount and zeroes out the attribution
    record so a later refund-confirmed against the reverted change is
    rejected as a non-applied change (the change's status is REVERTED
    and the apply-status gate handles that path).
    """
    attribution = DB.refund_attributions.pop(schedule_change_id, {})
    for tt_id, delta in attribution.items():
        tt = DB.ticket_types.get(tt_id)
        if tt is None:
            continue
        cur = int(tt.get("provisional_refund_cents_outstanding", 0))
        tt["provisional_refund_cents_outstanding"] = max(0, cur - int(delta))
        stamp_update(tt)
        append_audit(
            festival_id=festival_id,
            event_category="SCHEDULE_CHANGE",
            subject_entity_type="TicketType",
            subject_entity_id=tt["id"],
            payload_summary=(
                f"provisional refund of {delta} cents reverted on change "
                f"{schedule_change_id}, bucket back to zero on this attribution"
            ),
            actor_user_id=getattr(__import__("flask").g, "actor_user_id", "system"),
            actor_role=getattr(__import__("flask").g, "actor_role", "system"),
        )


# ---------------------------------------------------------------------------
# Sponsor projected/actual recomputation.
# ---------------------------------------------------------------------------


def recompute_tier_projection(sponsor_tier_id: str) -> None:
    """Recompute the tier's `projected_fulfilment_pct` and `tier_remaining_quota`.

    Run eagerly on every event that the PRD §3.6 lists: a tied program
    item's state change, an exposure-allocation create or void, the
    explicit sweep, and the cascade-from-cancel.
    """
    tier = DB.sponsor_tiers.get(sponsor_tier_id)
    if tier is None:
        return
    festival = DB.festivals.get(tier["festival_id"])
    if festival is None:
        return
    tier_allocations = [
        a
        for a in DB.exposure_allocations.values()
        if a.get("sponsor_tier_id") == sponsor_tier_id
    ]
    # Refresh delivered_units from the log for each allocation.
    for a in tier_allocations:
        a["delivered_units"] = delivered_units_for_allocation(
            a["id"], DB.fulfilment_logs.values()
        )

    program_item_lookup = {pi["id"]: pi for pi in DB.program_items.values()}
    contracted = int(tier.get("contracted_units", 0))
    projected = projected_fulfilment_pct(
        contracted,
        tier_allocations,
        program_item_lookup,
        festival,
        logical_now(festival),
    )
    tier["projected_fulfilment_pct"] = float(projected)
    quota = tier_remaining_quota_from_logs(
        contracted, tier_allocations, DB.fulfilment_logs.values()
    )
    tier["tier_remaining_quota"] = int(quota)


def recompute_all_tier_projections_for_festival(festival_id: str) -> None:
    for t in DB.sponsor_tiers.values():
        if t.get("festival_id") == festival_id:
            recompute_tier_projection(t["id"])


def recompute_tier_actuals_post_close(
    sponsor_tier_id: str, compute_payout: bool
) -> Tuple[Decimal, int]:
    """Post-close fulfilment computation, returns the (actual_pct, payout_cents) pair.

    Walks the FulfilmentLog stream, sets `actual_fulfilment_pct` and the
    `tier_remaining_quota`, and (when `compute_payout` is true) the
    sponsor-payout cents total.
    """
    tier = DB.sponsor_tiers.get(sponsor_tier_id)
    if tier is None:
        return Decimal("0.00"), 0
    tier_allocations = [
        a
        for a in DB.exposure_allocations.values()
        if a.get("sponsor_tier_id") == sponsor_tier_id
    ]
    contracted = int(tier.get("contracted_units", 0))
    actual = actual_fulfilment_pct(
        contracted, tier_allocations, DB.fulfilment_logs.values()
    )
    tier["actual_fulfilment_pct"] = float(actual)

    quota = tier_remaining_quota_from_logs(
        contracted, tier_allocations, DB.fulfilment_logs.values()
    )
    tier["tier_remaining_quota"] = int(quota)
    stamp_update(tier)

    payout = 0
    if compute_payout:
        payout = sponsor_payout_total_cents(
            tier_allocations, DB.fulfilment_logs.values()
        )
        tier["sponsor_payout_total_cents"] = int(payout)

    # Update delivered_units on each allocation from the log.
    for a in tier_allocations:
        a["delivered_units"] = delivered_units_for_allocation(
            a["id"], DB.fulfilment_logs.values()
        )

    return actual, payout


# ---------------------------------------------------------------------------
# Festival-close cascade (cascade C).
# ---------------------------------------------------------------------------


def festival_close_cascade(festival: dict) -> Dict[str, int]:
    """Cascade C.

    Link-1: festival itself flips LIVE → CLOSED (the caller handles this audit).
    Link-2: every non-terminal rehearsal (BOOKED or IN_PROGRESS) auto-archives.
    Link-3: each archived rehearsal's audit entry of category CLOCK_TICK
            names the originating festival-close event.

    Also flips every TicketType: ACTIVE → CLOSED, SUSPENDED → WITHDRAWN.
    """
    festival_id = festival["id"]
    archived = 0
    for r in list(DB.rehearsals.values()):
        if r.get("festival_id") != festival_id:
            continue
        if r.get("status") not in ("BOOKED", "IN_PROGRESS"):
            continue
        prior = r["status"]
        r["status"] = "ARCHIVED"
        r["archive_uri"] = (
            f"archive://festival/{festival_id}/rehearsal/{r['id']}"
        )
        stamp_update(r)
        append_audit(
            festival_id=festival_id,
            event_category="CLOCK_TICK",
            subject_entity_type="Rehearsal",
            subject_entity_id=r["id"],
            from_state=prior,
            to_state="ARCHIVED",
            payload_summary=(
                f"rehearsal auto-archived on festival-close cascade (festival {festival_id})"
            ),
            actor_user_id="system",
            actor_role="system",
        )
        archived += 1

    ticket_types_closed = 0
    ticket_types_withdrawn = 0
    for tt in list(DB.ticket_types.values()):
        if tt.get("festival_id") != festival_id:
            continue
        prior = tt.get("status")
        if prior == "ACTIVE":
            tt["status"] = "CLOSED"
            stamp_update(tt)
            append_audit(
                festival_id=festival_id,
                event_category="STATE_TRANSITION",
                subject_entity_type="TicketType",
                subject_entity_id=tt["id"],
                from_state="ACTIVE",
                to_state="CLOSED",
                payload_summary="ticket type closed on festival close",
                actor_user_id="system",
                actor_role="system",
            )
            ticket_types_closed += 1
        elif prior == "SUSPENDED":
            tt["status"] = "WITHDRAWN"
            stamp_update(tt)
            append_audit(
                festival_id=festival_id,
                event_category="STATE_TRANSITION",
                subject_entity_type="TicketType",
                subject_entity_id=tt["id"],
                from_state="SUSPENDED",
                to_state="WITHDRAWN",
                payload_summary="suspended ticket type withdrawn on festival close",
                actor_user_id="system",
                actor_role="system",
            )
            ticket_types_withdrawn += 1

    return {
        "rehearsals_archived": archived,
        "ticket_types_closed": ticket_types_closed,
        "ticket_types_withdrawn": ticket_types_withdrawn,
    }


# ---------------------------------------------------------------------------
# Festival hard-cancel fan-out.
# ---------------------------------------------------------------------------


def festival_cancel_fanout(festival: dict, reason: str) -> Dict[str, int]:
    """Fan-out per PRD §3.1.

    Visits every non-terminal child in one transaction.  Per the PRD the
    fan-out is broad rather than deep so does **not** count toward the
    depth-3 cascade quota.  Each per-child status flip writes a
    STATE_TRANSITION audit row.
    """
    festival_id = festival["id"]
    items_cancelled = 0
    for pi in list(DB.program_items.values()):
        if pi.get("festival_id") != festival_id:
            continue
        if pi.get("status") in ("PERFORMED", "CANCELLED"):
            continue
        prior = pi["status"]
        pi["status"] = "CANCELLED"
        stamp_update(pi)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="ProgramItem",
            subject_entity_id=pi["id"],
            from_state=prior,
            to_state="CANCELLED",
            payload_summary=f"program item cancelled on festival-cancel fan-out: {reason!r}",
            actor_user_id="system",
            actor_role="system",
        )
        # Each cancelled item runs cascades A and B's sub-effects.
        cascade_program_item_cancel(
            festival_id,
            pi["id"],
            actor_user_id="system",
            actor_role="system",
            summary_prefix="Festival cancel fan-out",
        )
        items_cancelled += 1

    rehearsals_cancelled = 0
    for r in list(DB.rehearsals.values()):
        if r.get("festival_id") != festival_id:
            continue
        if r.get("status") in ("ARCHIVED", "CANCELLED"):
            continue
        prior = r["status"]
        r["status"] = "CANCELLED"
        stamp_update(r)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="Rehearsal",
            subject_entity_id=r["id"],
            from_state=prior,
            to_state="CANCELLED",
            payload_summary=f"rehearsal cancelled on festival-cancel fan-out: {reason!r}",
            actor_user_id="system",
            actor_role="system",
        )
        rehearsals_cancelled += 1

    types_withdrawn = 0
    for tt in list(DB.ticket_types.values()):
        if tt.get("festival_id") != festival_id:
            continue
        if tt.get("status") in ("CLOSED", "WITHDRAWN"):
            continue
        prior = tt["status"]
        tt["status"] = "WITHDRAWN"
        stamp_update(tt)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="TicketType",
            subject_entity_id=tt["id"],
            from_state=prior,
            to_state="WITHDRAWN",
            payload_summary=f"ticket type withdrawn on festival-cancel fan-out: {reason!r}",
            actor_user_id="system",
            actor_role="system",
        )
        types_withdrawn += 1

    allocations_voided = 0
    for a in list(DB.exposure_allocations.values()):
        if a.get("festival_id") != festival_id:
            continue
        if a.get("status") in ("VOIDED", "REPORTED"):
            continue
        prior = a["status"]
        delivered = delivered_units_for_allocation(a["id"], DB.fulfilment_logs.values())
        log_id = fresh_uuid()
        DB.fulfilment_logs[log_id] = {
            "id": log_id,
            "exposure_allocation_id": a["id"],
            "program_item_id": a.get("program_item_id"),
            "event_type": "PROGRAM_VOIDED",
            "units": max(0, int(delivered)),
            "note": f"festival-cancel fan-out: {reason}",
            "created_at": server_now_iso8601(),
        }
        a["status"] = "VOIDED"
        a["delivered_units"] = 0
        stamp_update(a)
        append_audit(
            festival_id=festival_id,
            event_category="EXPOSURE",
            subject_entity_type="ExposureAllocation",
            subject_entity_id=a["id"],
            from_state=prior,
            to_state="VOIDED",
            payload_summary=f"exposure allocation voided on festival-cancel fan-out: {reason!r}",
            actor_user_id="system",
            actor_role="system",
        )
        allocations_voided += 1

    # Recompute every tier's projection.
    recompute_all_tier_projections_for_festival(festival_id)

    return {
        "items_cancelled": items_cancelled,
        "rehearsals_cancelled": rehearsals_cancelled,
        "ticket_types_withdrawn": types_withdrawn,
        "allocations_voided": allocations_voided,
    }


# ---------------------------------------------------------------------------
# Clock-driven threshold sweep (PRD §2.8).
#
# The harness drives time by POSTing to /_clock/advance with either
# `delta_seconds` or `to_unix_seconds`.  This function inspects every
# festival's threshold crossings against the new logical wall clock and
# fires the deterministic-order transitions: festival start, item start,
# rehearsal start, item end, rehearsal end + grace, festival end + grace.
# Each fired transition appends a CLOCK_TICK audit row.
#
# The implementation is a single pass that uses the post-advance logical
# wall clock; transitions whose threshold is at or below the new wall
# clock and whose source state matches the precondition all fire.  Order
# within a tick: wall-clock ascending of the thresholds, with the
# entity-type ordering (festival.start, item.start, rehearsal.start,
# item.end, rehearsal.end+grace, festival.end+grace) as the tiebreak
# at equal thresholds.
# ---------------------------------------------------------------------------


def _per_entity_threshold_events(festival: dict) -> List[Tuple[int, int, str, str]]:
    """For a given festival, enumerate every pending threshold crossing.

    Each event is a tuple `(threshold_unix_seconds, tiebreak_kind_index, kind, entity_id)`.
    Kind ordering tiebreak indices (PRD §2.8):
      0 = festival.start (PUBLISHED → LIVE)
      1 = program-item.start (ANNOUNCED → ON_STAGE while festival LIVE)
      2 = rehearsal.start (BOOKED → IN_PROGRESS while festival PUBLISHED|LIVE)
      3 = program-item.end (ON_STAGE → PERFORMED)
      4 = rehearsal.end + REHEARSAL_GRACE_SECONDS (IN_PROGRESS → ARCHIVED)
      5 = festival.end + FESTIVAL_CLOSE_GRACE_SECONDS (LIVE → CLOSED)
    """
    fid = festival["id"]
    events: List[Tuple[int, int, str, str]] = []

    if festival.get("status") == "PUBLISHED":
        events.append((int(festival["start_time"]), 0, "festival_start", fid))
    if festival.get("status") in ("PUBLISHED", "LIVE"):
        thresh = int(festival["end_time"]) + FESTIVAL_CLOSE_GRACE_SECONDS
        events.append((thresh, 5, "festival_close", fid))

    for pi in DB.program_items.values():
        if pi.get("festival_id") != fid:
            continue
        if pi.get("status") == "ANNOUNCED":
            events.append((int(pi["start_time"]), 1, "item_start", pi["id"]))
        if pi.get("status") == "ON_STAGE":
            events.append((int(pi["end_time"]), 3, "item_end", pi["id"]))

    for r in DB.rehearsals.values():
        if r.get("festival_id") != fid:
            continue
        if r.get("status") == "BOOKED":
            events.append((int(r["start_time"]), 2, "rehearsal_start", r["id"]))
        if r.get("status") == "IN_PROGRESS":
            events.append(
                (int(r["end_time"]) + REHEARSAL_GRACE_SECONDS, 4, "rehearsal_archive", r["id"])
            )

    return events


def fire_clock_thresholds(festival: dict) -> int:
    """Walk every pending threshold under the festival whose `threshold ≤ logical_now`
    and fire the corresponding transition with a CLOCK_TICK audit entry.

    Repeats the sweep until no new transitions fire (a single tick can
    cascade festival-close which then archives in-progress rehearsals
    via the festival-close cascade).

    Returns the number of transitions fired.
    """
    total_fired = 0
    while True:
        now_logical = logical_now(festival)
        pending = [
            ev
            for ev in _per_entity_threshold_events(festival)
            if ev[0] <= now_logical
        ]
        if not pending:
            break
        # Sort by (threshold_time, tiebreak_kind_index) ascending so the
        # PRD's deterministic order is honoured.
        pending.sort(key=lambda ev: (ev[0], ev[1]))
        fired_this_pass = 0
        for thresh, kind_idx, kind, entity_id in pending:
            ok = _fire_one_threshold(festival, thresh, kind, entity_id)
            if ok:
                fired_this_pass += 1
        total_fired += fired_this_pass
        if fired_this_pass == 0:
            break
    return total_fired


def _fire_one_threshold(
    festival: dict, threshold_time: int, kind: str, entity_id: str
) -> bool:
    fid = festival["id"]

    if kind == "festival_start":
        if festival.get("status") != "PUBLISHED":
            return False
        festival["status"] = "LIVE"
        stamp_update(festival)
        append_audit(
            festival_id=fid,
            event_category="CLOCK_TICK",
            subject_entity_type="Festival",
            subject_entity_id=fid,
            from_state="PUBLISHED",
            to_state="LIVE",
            payload_summary=f"festival went live at logical-time {threshold_time}",
            actor_user_id="system",
            actor_role="system",
        )
        return True

    if kind == "festival_close":
        if festival.get("status") != "LIVE":
            # The PRD pins the precondition: must be LIVE.  When the
            # status is PUBLISHED at the close-threshold (because the
            # festival skipped LIVE — e.g., the harness fast-forwarded
            # past both start and close in one advance) we still close
            # it, advancing through LIVE implicitly.
            if festival.get("status") == "PUBLISHED":
                # Implicit LIVE pass-through.
                festival["status"] = "LIVE"
                stamp_update(festival)
                append_audit(
                    festival_id=fid,
                    event_category="CLOCK_TICK",
                    subject_entity_type="Festival",
                    subject_entity_id=fid,
                    from_state="PUBLISHED",
                    to_state="LIVE",
                    payload_summary="festival auto-advanced through LIVE on close tick",
                    actor_user_id="system",
                    actor_role="system",
                )
            else:
                return False
        # Now flip to CLOSED.
        festival["status"] = "CLOSED"
        stamp_update(festival)
        cascade_counts = festival_close_cascade(festival)
        summary = (
            f"festival closed at logical-time {threshold_time}; "
            f"rehearsals_archived={cascade_counts['rehearsals_archived']}, "
            f"ticket_types_closed={cascade_counts['ticket_types_closed']}, "
            f"ticket_types_withdrawn={cascade_counts['ticket_types_withdrawn']}"
        )
        append_audit(
            festival_id=fid,
            event_category="CLOCK_TICK",
            subject_entity_type="Festival",
            subject_entity_id=fid,
            from_state="LIVE",
            to_state="CLOSED",
            payload_summary=summary,
            actor_user_id="system",
            actor_role="system",
        )
        return True

    if kind == "item_start":
        item = DB.program_items.get(entity_id)
        if item is None:
            return False
        if item.get("status") != "ANNOUNCED":
            return False
        if festival.get("status") != "LIVE":
            return False
        item["status"] = "ON_STAGE"
        stamp_update(item)
        append_audit(
            festival_id=fid,
            event_category="CLOCK_TICK",
            subject_entity_type="ProgramItem",
            subject_entity_id=entity_id,
            from_state="ANNOUNCED",
            to_state="ON_STAGE",
            payload_summary=f"program item went on-stage at logical-time {threshold_time}",
            actor_user_id="system",
            actor_role="system",
        )
        # Sponsor tiers tied to this item see their projection change.
        for a in DB.exposure_allocations.values():
            if a.get("program_item_id") == entity_id:
                recompute_tier_projection(a["sponsor_tier_id"])
        return True

    if kind == "item_end":
        item = DB.program_items.get(entity_id)
        if item is None:
            return False
        if item.get("status") != "ON_STAGE":
            return False
        item["status"] = "PERFORMED"
        stamp_update(item)
        append_audit(
            festival_id=fid,
            event_category="CLOCK_TICK",
            subject_entity_type="ProgramItem",
            subject_entity_id=entity_id,
            from_state="ON_STAGE",
            to_state="PERFORMED",
            payload_summary=f"program item performed at logical-time {threshold_time}",
            actor_user_id="system",
            actor_role="system",
        )
        for a in DB.exposure_allocations.values():
            if a.get("program_item_id") == entity_id:
                recompute_tier_projection(a["sponsor_tier_id"])
        return True

    if kind == "rehearsal_start":
        r = DB.rehearsals.get(entity_id)
        if r is None:
            return False
        if r.get("status") != "BOOKED":
            return False
        if festival.get("status") not in ("PUBLISHED", "LIVE"):
            return False
        r["status"] = "IN_PROGRESS"
        stamp_update(r)
        append_audit(
            festival_id=fid,
            event_category="CLOCK_TICK",
            subject_entity_type="Rehearsal",
            subject_entity_id=entity_id,
            from_state="BOOKED",
            to_state="IN_PROGRESS",
            payload_summary=f"rehearsal in progress at logical-time {threshold_time}",
            actor_user_id="system",
            actor_role="system",
        )
        return True

    if kind == "rehearsal_archive":
        r = DB.rehearsals.get(entity_id)
        if r is None:
            return False
        if r.get("status") != "IN_PROGRESS":
            return False
        r["status"] = "ARCHIVED"
        r["archive_uri"] = f"archive://festival/{fid}/rehearsal/{entity_id}"
        stamp_update(r)
        append_audit(
            festival_id=fid,
            event_category="CLOCK_TICK",
            subject_entity_type="Rehearsal",
            subject_entity_id=entity_id,
            from_state="IN_PROGRESS",
            to_state="ARCHIVED",
            payload_summary=(
                f"rehearsal auto-archived after the {REHEARSAL_GRACE_SECONDS}s grace at "
                f"logical-time {threshold_time}"
            ),
            actor_user_id="system",
            actor_role="system",
        )
        return True

    return False


# ---------------------------------------------------------------------------
# Sponsor waterfall sweep.
# ---------------------------------------------------------------------------


def run_waterfall(festival_id: str) -> Dict[str, List[Tuple[str, int]]]:
    """Run the §3.6 waterfall allocator across every kind.

    Returns a dict keyed by `kind` of the disbursement vector
    ``[(allocation_id, actual_units), ...]`` in tier-then-rank-then-sponsor-id
    order, for the audit summary.

    The catalog is read from the festival-level `exposure_catalogs` dict.
    Pool per `kind`: catalog total minus zero (the running sum is the
    `pool_remaining` we walk down).  Allocations in PLANNED or DELIVERED
    status get their `actual_units` rewritten in place; VOIDED and
    REPORTED allocations are excluded.

    The advisory-lock and the racing-against-an-in-progress-sweep error
    are at the route layer (`POST /festivals/{fid}/sponsor-allocation-sweep`).
    """
    cat_row = DB.exposure_catalogs.get(festival_id)
    catalog: Dict[str, int] = dict(cat_row["catalog"]) if cat_row else {}

    # Index allocations.
    allocs_by_kind: Dict[str, List[dict]] = {}
    for a in DB.exposure_allocations.values():
        if a.get("festival_id") != festival_id:
            continue
        if a.get("status") not in ("PLANNED", "DELIVERED"):
            continue
        allocs_by_kind.setdefault(a["kind"], []).append(a)

    summary: Dict[str, List[Tuple[str, int]]] = {}
    tiers_index = {t["id"]: t for t in DB.sponsor_tiers.values()}

    for kind, allocs in allocs_by_kind.items():
        pool = int(catalog.get(kind, 0))
        # Order: WATERFALL_TIER_ORDER, then priority_rank ascending, then
        # sponsor_external_id lexicographic ascending.

        def _sort_key(alloc: dict) -> Tuple[int, int, str]:
            t = tiers_index.get(alloc["sponsor_tier_id"], {})
            tier_idx = (
                WATERFALL_TIER_ORDER.index(t.get("tier_code"))
                if t.get("tier_code") in WATERFALL_TIER_ORDER
                else len(WATERFALL_TIER_ORDER)
            )
            return (
                tier_idx,
                int(t.get("priority_rank", 0)),
                str(t.get("sponsor_external_id", "")),
            )

        allocs_sorted = sorted(allocs, key=_sort_key)
        disbursement: List[Tuple[str, int]] = []
        for a in allocs_sorted:
            requested = int(a.get("requested_units", 0))
            disbursed = min(requested, max(0, pool))
            a["actual_units"] = disbursed
            stamp_update(a)
            pool -= disbursed
            disbursement.append((a["id"], disbursed))
        summary[kind] = disbursement

    append_audit(
        festival_id=festival_id,
        event_category="EXPOSURE",
        subject_entity_type="Festival",
        subject_entity_id=festival_id,
        payload_summary=f"sponsor-allocation-sweep disbursement vector: {summary}",
    )

    # Recompute every tier under the festival.
    recompute_all_tier_projections_for_festival(festival_id)

    return summary


# ---------------------------------------------------------------------------
# Sound-check window guard (§3.5 priority-14).
# ---------------------------------------------------------------------------


def assert_sound_check_window(
    slot_start: int,
    slot_end: int,
    parent_item: dict,
    festival: dict,
) -> None:
    """Pre-show-window guard: `slot_end ≤ item.start_time - TEAM_HANDOFF_SECONDS`
    and `slot_start ≥ festival.start_time`.

    The inclusive `≤` boundary on the handoff gap and the inclusive `≥`
    boundary on the festival's own start.  PRD §3.5 pins both.
    """
    item_start = int(parent_item["start_time"])
    bound = item_start - TEAM_HANDOFF_SECONDS
    if slot_end > bound:
        raise ApiError(
            "ERR_SOUND_CHECK_WINDOW_INVALID",
            f"sound-check window end {slot_end} must be ≤ "
            f"{bound} (item.start − {TEAM_HANDOFF_SECONDS}s)",
        )
    if slot_start < int(festival["start_time"]):
        raise ApiError(
            "ERR_SOUND_CHECK_WINDOW_INVALID",
            f"sound-check window starts before the festival starts "
            f"({slot_start} < {festival['start_time']})",
        )


# ---------------------------------------------------------------------------
# Zone-capacity walker (§3.4).
# ---------------------------------------------------------------------------


def zone_capacity_check(
    festival_id: str, ticket_type_id: str, additional_count: int
) -> None:
    """Raise ERR_TICKET_ZONE_CAPACITY_EXCEEDED or ERR_TICKET_ZONE_NO_STAGE.

    The zone capacity is the maximum `Stage.zone_capacity` over the
    stages hosting any program item that appears in any
    `tied_program_item_ids` array across the zone group.  The
    cumulative net-issued in the zone group must not exceed that
    capacity after the increment.

    Strict-`>` boundary on the post-increment cumulative count.  The
    empty-zone-stage edge case (no tied stages anywhere in the zone group)
    is the ERR_TICKET_ZONE_NO_STAGE rejection.
    """
    this_type = DB.ticket_types[ticket_type_id]
    zone_name = this_type["zone_name"]
    zone_group = [
        tt
        for tt in DB.ticket_types.values()
        if tt.get("festival_id") == festival_id and tt.get("zone_name") == zone_name
    ]
    # Find every stage that hosts a tied program item across the zone group.
    stage_ids: set[str] = set()
    for tt in zone_group:
        ties = list(tt.get("tied_program_item_ids", []) or [])
        for pi_id in ties:
            pi = DB.program_items.get(pi_id)
            if pi is None:
                continue
            sid = pi.get("stage_id")
            if sid:
                stage_ids.add(sid)

    if not stage_ids:
        raise ApiError(
            "ERR_TICKET_ZONE_NO_STAGE",
            f"zone {zone_name!r} has no tied stage to derive capacity from",
        )

    zone_capacity = 0
    for sid in stage_ids:
        stage = DB.stages.get(sid)
        if stage is None:
            continue
        cap = int(stage.get("zone_capacity", 0))
        if cap > zone_capacity:
            zone_capacity = cap

    cumulative = sum(
        int(tt.get("issued_count", 0)) - int(tt.get("refunded_count", 0))
        for tt in zone_group
    )
    if cumulative + int(additional_count) > zone_capacity:
        raise ApiError(
            "ERR_TICKET_ZONE_CAPACITY_EXCEEDED",
            f"zone {zone_name!r} capacity {zone_capacity} would be exceeded "
            f"by adding {additional_count} to cumulative {cumulative}",
        )


# ---------------------------------------------------------------------------
# The `headliner-blocking-rider` and `blocking-rider-fulfilled` checks
# for the announce path.
# ---------------------------------------------------------------------------


def check_blocking_riders_for_announce(program_item: dict) -> None:
    """§3.3 / §1.3 `blocking_rider_minimum_check`.

    Step A (HEADLINER only): the program item must carry at least one
    blocking rider on file.  ERR_HEADLINER_MISSING_BLOCKING_RIDER on
    failure (boundary at the 0-versus-1 transition).

    Step B (every tier): every blocking rider on file must have its
    `fulfilled_at` non-null.  ERR_BLOCKING_RIDERS_UNFULFILLED otherwise.
    """
    item_id = program_item["id"]
    artist = DB.artists.get(program_item["artist_id"])
    is_headliner = artist is not None and artist.get("tier") == "HEADLINER"

    blocking = [
        r
        for r in DB.riders.values()
        if r.get("program_item_id") == item_id and bool(r.get("is_blocking", False))
    ]
    blocking_count = len(blocking)
    unfulfilled = [r for r in blocking if not r.get("fulfilled_at")]

    # Step A first (priority 9 in §1.4).
    if is_headliner:
        from .constants import HEADLINER_MIN_BLOCKING_RIDERS

        if blocking_count < HEADLINER_MIN_BLOCKING_RIDERS:
            raise ApiError(
                "ERR_HEADLINER_MISSING_BLOCKING_RIDER",
                f"headliner item {item_id} must have at least "
                f"{HEADLINER_MIN_BLOCKING_RIDERS} blocking rider; observed {blocking_count}",
            )
    # Step B: any blocking-but-unfulfilled rider rejects.
    if unfulfilled:
        raise ApiError(
            "ERR_BLOCKING_RIDERS_UNFULFILLED",
            f"item {item_id} has {len(unfulfilled)} unfulfilled blocking rider(s)",
        )


def check_unblocking_riders_for_publish(version_id: str, festival_id: str) -> None:
    """The §3.3 program-version-publish blocking-rider check.

    Every ProgramItem under the version with at least one blocking rider
    must have that rider fulfilled.  Otherwise ERR_BLOCKING_RIDERS_UNFULFILLED.
    """
    items = [
        pi
        for pi in DB.program_items.values()
        if pi.get("festival_id") == festival_id
        and pi.get("program_version_id") == version_id
    ]
    for item in items:
        blocking_unfulfilled = [
            r
            for r in DB.riders.values()
            if r.get("program_item_id") == item["id"]
            and bool(r.get("is_blocking", False))
            and not r.get("fulfilled_at")
        ]
        if blocking_unfulfilled:
            raise ApiError(
                "ERR_BLOCKING_RIDERS_UNFULFILLED",
                f"program item {item['id']} has unfulfilled blocking rider(s)",
            )


# ---------------------------------------------------------------------------
# Helpers for projecting tier-allocation cap and waterfall reads on the read endpoint.
# ---------------------------------------------------------------------------


def fulfilment_report_payload(tier_id: str) -> Dict[str, Any]:
    """Build the synthetic FulfilmentReportView shape for the read endpoint."""
    tier = DB.sponsor_tiers.get(tier_id)
    if tier is None:
        raise ApiError("ERR_SPONSOR_TIER_NOT_FOUND", f"sponsor tier {tier_id} not found")
    # Refresh the live projection.
    recompute_tier_projection(tier_id)
    tier_allocs = [
        a
        for a in DB.exposure_allocations.values()
        if a.get("sponsor_tier_id") == tier_id
    ]
    per_alloc: List[Dict[str, Any]] = []
    for a in tier_allocs:
        d = delivered_units_for_allocation(a["id"], DB.fulfilment_logs.values())
        per_alloc.append({"exposure_allocation_id": a["id"], "delivered_units": int(d)})

    sponsor_payout = tier.get("sponsor_payout_total_cents")
    return {
        "sponsor_tier_id": tier_id,
        "projected_fulfilment_pct": tier.get("projected_fulfilment_pct"),
        "actual_fulfilment_pct": tier.get("actual_fulfilment_pct"),
        "per_allocation_delivered_units": per_alloc,
        "tier_remaining_quota": tier.get("tier_remaining_quota"),
        "sponsor_payout_total_cents": sponsor_payout,
        "contracted_units": tier.get("contracted_units"),
    }
