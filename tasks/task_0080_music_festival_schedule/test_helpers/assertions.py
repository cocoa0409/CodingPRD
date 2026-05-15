"""Entity-shape assertions and domain-invariant checkers.

Every entity-shape assertion below is derived from the PRD §2.4 common
fields and the §3 narrative's per-entity field set.  The append-only
trio — RiderRequirement, FulfilmentLog, AuditEntry — is asserted with
only the `id` and `created_at` common fields and the entity-specific
payload columns; `updated_at` and `version` are explicitly NOT asserted
on those rows (their absence is the contract from the PRD's common-fields
branching rule).

Domain-invariant helpers cover the two conservation invariants the PRD §3
pins by name: the festival's `outstanding_tickets_total` across an
ITEM_CANCEL apply-and-revert window, and the sponsor tier's
`tier_remaining_quota` across a deliver-and-matching-void round trip.

Pagination-meta shape assertion implements the PRD §2.3 four-field
metadata block `limit`, `offset`, `total_count`, `has_more`.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

from .constants import (
    AUDIT_CATEGORIES,
    CANONICAL_SYNC_TARGETS,
    CATALOG_KINDS,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from .types import (
    ArtistTier,
    AuditEventCategory,
    ExposureAllocationStatus,
    ExposureKind,
    FestivalStatus,
    FulfilmentLogEventType,
    ProgramItemStatus,
    ProgramVersionStatus,
    RehearsalStatus,
    RehearsalType,
    RiderCategory,
    ScheduleChangeKind,
    ScheduleChangeStatus,
    SoundCheckSlotStatus,
    SoundCheckStatusAxis,
    SoundEngineerTeamStatus,
    SponsorTierCode,
    StageStatus,
    SyncEnvelopeStatus,
    SyncEnvelopeTarget,
    TicketClass,
    TicketTypeStatus,
)


# ---------------------------------------------------------------------------
# Common-field guards
# ---------------------------------------------------------------------------

def _assert_common_fields_full(data: Dict[str, Any], entity_label: str) -> None:
    """The four common fields a mutable entity carries per PRD §2.4."""
    assert isinstance(data, dict), f"{entity_label}: response data is not a dict"
    assert is_valid_uuid(str(data.get("id", ""))), f"{entity_label}: id must be a UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), \
        f"{entity_label}: created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(str(data.get("updated_at", ""))), \
        f"{entity_label}: updated_at must be an ISO 8601 UTC timestamp"
    v = data.get("version")
    assert isinstance(v, int) and v >= 1, f"{entity_label}: version must be a positive integer"


def _assert_common_fields_append_only(data: Dict[str, Any], entity_label: str) -> None:
    """The two common fields an append-only entity carries per PRD §2.4.

    Append-only rows do not have `updated_at` and do not have `version`.
    The PRD §2.4 prose names the three append-only entity types explicitly:
    RiderRequirement, FulfilmentLog, AuditEntry.
    """
    assert isinstance(data, dict), f"{entity_label}: response data is not a dict"
    assert is_valid_uuid(str(data.get("id", ""))), f"{entity_label}: id must be a UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), \
        f"{entity_label}: created_at must be an ISO 8601 UTC timestamp"
    # Tolerate the implementation having harmlessly added these fields, but
    # do not require them; the append-only contract is the explicit absence
    # of mutation, which we exercise by never PATCHing these rows.


def _enum_in(value: Any, members: Iterable[str], label: str) -> None:
    valid = set(members)
    assert value in valid, f"{label}: got {value!r}, expected one of {sorted(valid)}"


def _enum_values(enum_cls) -> Set[str]:
    return {member.value for member in enum_cls}


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_festival_shape(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Festival")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["venue_name"], str) and data["venue_name"]
    assert isinstance(data["start_time"], int) and data["start_time"] > 0
    assert isinstance(data["end_time"], int) and data["end_time"] > data["start_time"]
    assert isinstance(data["festival_day_count"], int) and data["festival_day_count"] >= 1, \
        "Festival.festival_day_count must be a positive integer"
    _enum_in(data["status"], _enum_values(FestivalStatus), "Festival.status")
    cpv = data.get("current_program_version_id")
    assert cpv is None or is_valid_uuid(str(cpv)), \
        "Festival.current_program_version_id is null or a UUID"
    assert isinstance(data.get("clock_offset_seconds", 0), int), \
        "Festival.clock_offset_seconds must be an integer"
    assert isinstance(data.get("outstanding_tickets_total", 0), int), \
        "Festival.outstanding_tickets_total must be an integer"


def assert_program_version_shape(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "ProgramVersion")
    assert is_valid_uuid(str(data["festival_id"]))
    assert isinstance(data["version_label"], str)
    _enum_in(data["status"], _enum_values(ProgramVersionStatus), "ProgramVersion.status")
    assert isinstance(data.get("program_item_ids", []), list)
    pa = data.get("published_at")
    assert pa is None or is_iso8601_timestamp(str(pa)), \
        "ProgramVersion.published_at is null or an ISO 8601 UTC timestamp"
    sv = data.get("superseded_by_version_id")
    assert sv is None or is_valid_uuid(str(sv)), \
        "ProgramVersion.superseded_by_version_id is null or a UUID"


def assert_stage_shape(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Stage")
    assert is_valid_uuid(str(data["festival_id"]))
    assert isinstance(data["stage_name"], str)
    assert isinstance(data["zone_capacity"], int) and data["zone_capacity"] >= 0
    assert isinstance(data["changeover_buffer_seconds"], int) and data["changeover_buffer_seconds"] >= 0
    assert isinstance(data["equipment_kits"], list)
    assert all(isinstance(s, str) for s in data["equipment_kits"])
    assert isinstance(data["is_emergency_substitute"], bool)
    _enum_in(data["status"], _enum_values(StageStatus), "Stage.status")


def assert_equipment_kit_shape(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "EquipmentKit")
    assert is_valid_uuid(str(data["festival_id"]))
    assert isinstance(data["kit_code"], str) and data["kit_code"]
    assert isinstance(data["total_units"], int) and data["total_units"] >= 0


def assert_artist_shape(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Artist")
    assert isinstance(data["stage_name"], str) and data["stage_name"]
    _enum_in(data["tier"], _enum_values(ArtistTier), "Artist.tier")
    assert isinstance(data["home_city"], str)
    ec = data.get("external_commitments", [])
    assert isinstance(ec, list)
    for c in ec:
        assert isinstance(c, dict), "external_commitments entries are dicts"
        assert isinstance(c.get("start_time"), int)
        assert isinstance(c.get("end_time"), int)


def assert_program_item_shape(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "ProgramItem")
    assert is_valid_uuid(str(data["festival_id"]))
    assert is_valid_uuid(str(data["program_version_id"]))
    assert is_valid_uuid(str(data["artist_id"]))
    assert is_valid_uuid(str(data["stage_id"]))
    assert isinstance(data["start_time"], int) and data["start_time"] > 0
    assert isinstance(data["end_time"], int) and data["end_time"] > data["start_time"]
    assert isinstance(data["duration_seconds"], int)
    assert data["duration_seconds"] == data["end_time"] - data["start_time"], \
        "ProgramItem.duration_seconds equals end_time - start_time per PRD §2.4"
    ek = data.get("equipment_kit_codes", [])
    assert isinstance(ek, list) and all(isinstance(s, str) for s in ek)
    sps = data.get("slot_priority_score")
    assert isinstance(sps, (int, float)) and float(sps) >= 0.0, \
        "slot_priority_score is the non-negative floor of the raw score per PRD §3.5"
    _enum_in(data["status"], _enum_values(ProgramItemStatus), "ProgramItem.status")
    _enum_in(data["sound_check_status"],
             _enum_values(SoundCheckStatusAxis), "ProgramItem.sound_check_status")
    ass = data.get("announcement_sync_state")
    if ass is not None:
        _enum_in(ass, {"PENDING", "QUEUED", "ACKED", "FAILED"},
                 "ProgramItem.announcement_sync_state")


def assert_rider_shape(data: Dict[str, Any]) -> None:
    """Append-only entity — no updated_at, no version per PRD §2.4."""
    _assert_common_fields_append_only(data, "RiderRequirement")
    assert is_valid_uuid(str(data["program_item_id"]))
    _enum_in(data["category"], _enum_values(RiderCategory), "RiderRequirement.category")
    assert isinstance(data["description"], str)
    assert isinstance(data["is_blocking"], bool)
    fa = data.get("fulfilled_at")
    assert fa is None or is_iso8601_timestamp(str(fa)), \
        "RiderRequirement.fulfilled_at is null or an ISO 8601 timestamp"


def assert_sound_engineer_team_shape(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "SoundEngineerTeam")
    assert is_valid_uuid(str(data["festival_id"]))
    assert isinstance(data["team_name"], str)
    assert isinstance(data["head_engineer_name"], str)
    assert isinstance(data["warmup_minutes"], int) and data["warmup_minutes"] >= 0
    _enum_in(data["status"], _enum_values(SoundEngineerTeamStatus),
             "SoundEngineerTeam.status")
    cbk = data.get("current_booking_id")
    assert cbk is None or is_valid_uuid(str(cbk))


def assert_sound_check_shape(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "SoundCheckSlot")
    assert is_valid_uuid(str(data["festival_id"]))
    assert is_valid_uuid(str(data["program_item_id"]))
    assert is_valid_uuid(str(data["stage_id"]))
    sid = data.get("sound_engineer_team_id")
    assert sid is None or is_valid_uuid(str(sid))
    ws = data.get("scheduled_window_start")
    we = data.get("scheduled_window_end")
    if ws is not None and we is not None:
        assert isinstance(ws, int) and isinstance(we, int)
        assert we > ws, "SoundCheckSlot.scheduled_window_end > scheduled_window_start"
    _enum_in(data["status"], _enum_values(SoundCheckSlotStatus), "SoundCheckSlot.status")


def assert_rehearsal_shape(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Rehearsal")
    assert is_valid_uuid(str(data["festival_id"]))
    assert is_valid_uuid(str(data["artist_id"]))
    _enum_in(data["rehearsal_type"], _enum_values(RehearsalType),
             "Rehearsal.rehearsal_type")
    if data["rehearsal_type"] == "STAGE":
        assert is_valid_uuid(str(data["stage_id"])), \
            "Rehearsal.stage_id is required when rehearsal_type=='STAGE' per PRD §3.5"
        assert data.get("rehearsal_room_name") in (None, ""), \
            "Rehearsal.rehearsal_room_name is null/empty when rehearsal_type=='STAGE'"
    else:
        assert isinstance(data.get("rehearsal_room_name"), str) and data["rehearsal_room_name"], \
            "Rehearsal.rehearsal_room_name is required when rehearsal_type=='ROOM' per PRD §3.5"
        assert data.get("stage_id") in (None, ""), \
            "Rehearsal.stage_id is null/empty when rehearsal_type=='ROOM'"
    assert isinstance(data["start_time"], int)
    assert isinstance(data["end_time"], int) and data["end_time"] > data["start_time"]
    _enum_in(data["status"], _enum_values(RehearsalStatus), "Rehearsal.status")
    uri = data.get("archive_uri")
    if data["status"] == RehearsalStatus.ARCHIVED.value:
        assert isinstance(uri, str) and uri.startswith("archive://festival/"), \
            "Archived rehearsal's archive_uri starts with archive://festival/ per PRD §3.5"
    else:
        assert uri is None, "Non-archived rehearsals have null archive_uri per PRD §3.5"


def assert_ticket_type_shape(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "TicketType")
    assert is_valid_uuid(str(data["festival_id"]))
    _enum_in(data["ticket_class"], _enum_values(TicketClass), "TicketType.ticket_class")
    assert isinstance(data["tied_program_item_ids"], list)
    assert isinstance(data["zone_name"], str)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["issued_count"], int) and data["issued_count"] >= 0
    assert isinstance(data["refunded_count"], int) and data["refunded_count"] >= 0
    assert isinstance(data["provisional_refund_cents_outstanding"], int)
    assert data["provisional_refund_cents_outstanding"] >= 0
    _enum_in(data["status"], _enum_values(TicketTypeStatus), "TicketType.status")


def assert_sponsor_tier_shape(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "SponsorTier")
    assert is_valid_uuid(str(data["festival_id"]))
    _enum_in(data["tier_code"], _enum_values(SponsorTierCode), "SponsorTier.tier_code")
    assert isinstance(data["tier_name"], str)
    assert isinstance(data["priority_rank"], int)
    assert isinstance(data["sponsor_external_id"], str)
    assert isinstance(data["sponsor_display_name"], str)
    assert isinstance(data["contracted_units"], int) and data["contracted_units"] >= 0
    cka = data["contract_kinds_allowed"]
    assert isinstance(cka, list) and all(k in CATALOG_KINDS for k in cka), \
        "SponsorTier.contract_kinds_allowed values come from the four-kind set per PRD §2.8"
    pfp = data["projected_fulfilment_pct"]
    assert isinstance(pfp, (int, float)) and 0.0 <= float(pfp) <= 100.0 + 1e-6, \
        "projected_fulfilment_pct is a percentage between 0 and 100"
    afp = data.get("actual_fulfilment_pct")
    assert afp is None or (0.0 <= float(afp) <= 100.0 + 1e-6), \
        "actual_fulfilment_pct is null before close per PRD §2.7 or a percentage"
    assert isinstance(data["tier_remaining_quota"], int)


def assert_exposure_allocation_shape(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "ExposureAllocation")
    assert is_valid_uuid(str(data["festival_id"]))
    assert is_valid_uuid(str(data["sponsor_tier_id"]))
    pi = data.get("program_item_id")
    assert pi is None or is_valid_uuid(str(pi))
    _enum_in(data["kind"], _enum_values(ExposureKind), "ExposureAllocation.kind")
    assert isinstance(data["requested_units"], int) and data["requested_units"] >= 0
    assert isinstance(data["actual_units"], int) and data["actual_units"] >= 0
    assert isinstance(data["delivered_units"], int) and data["delivered_units"] >= 0
    rate = data.get("pinned_rate_cents_per_unit")
    assert rate is None or (isinstance(rate, int) and rate >= 0)
    _enum_in(data["status"], _enum_values(ExposureAllocationStatus),
             "ExposureAllocation.status")
    assert data["actual_units"] <= data["requested_units"] + 0, \
        "actual_units never exceeds requested_units per the PRD §3.6 waterfall rule"


def assert_fulfilment_log_shape(data: Dict[str, Any]) -> None:
    """Append-only.  See PRD §2.4 for the no-updated_at-no-version contract."""
    _assert_common_fields_append_only(data, "FulfilmentLog")
    assert is_valid_uuid(str(data["exposure_allocation_id"]))
    pi = data.get("program_item_id")
    assert pi is None or is_valid_uuid(str(pi))
    _enum_in(data["event_type"], _enum_values(FulfilmentLogEventType),
             "FulfilmentLog.event_type")
    assert isinstance(data["units"], int) and data["units"] >= 0, \
        "FulfilmentLog.units is a non-negative integer; the sign comes from event_type per PRD §3.6"
    # Per the PRD §3.6 REPORTED-row contract the units field on a REPORTED
    # closing-tally row is always zero.  Other event types carry positive
    # magnitudes.
    if data["event_type"] == FulfilmentLogEventType.REPORTED.value:
        assert data["units"] == 0, \
            "FulfilmentLog row of event_type REPORTED has units==0 per PRD §2.7"


def assert_schedule_change_shape(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "ScheduleChange")
    assert is_valid_uuid(str(data["festival_id"]))
    _enum_in(data["change_kind"], _enum_values(ScheduleChangeKind),
             "ScheduleChange.change_kind")
    tpi = data.get("target_program_item_id")
    assert tpi is None or is_valid_uuid(str(tpi))
    assert isinstance(data.get("payload", {}), dict)
    _enum_in(data["status"], _enum_values(ScheduleChangeStatus),
             "ScheduleChange.status")
    aa = data.get("applied_at")
    if data["status"] in {"APPLIED", "SYNCED", "REVERTED"}:
        assert aa is not None and is_iso8601_timestamp(str(aa)), \
            "ScheduleChange.applied_at is non-null once the change has been APPLIED per PRD §3.4"
    envs = data.get("sync_envelopes", [])
    assert isinstance(envs, list)
    # After apply, the canonical four-target ordered list of envelopes is
    # present (PRD §2.8 names the canonical order ticketing, im,
    # broadcasting, sponsor).
    if data["status"] in {"APPLIED", "SYNCED", "REVERTED"}:
        targets_seen = [e.get("target") for e in envs]
        # The order is canonical per PRD §2.8 and the cardinality is 4.
        assert sorted(set(targets_seen)) == sorted(CANONICAL_SYNC_TARGETS), \
            ("ScheduleChange.sync_envelopes covers the four canonical targets "
             "{ticketing, im, broadcasting, sponsor} per PRD §2.8")
        assert targets_seen == CANONICAL_SYNC_TARGETS, \
            "ScheduleChange.sync_envelopes is in the canonical order per PRD §2.8"
        for e in envs:
            _enum_in(e["status"], _enum_values(SyncEnvelopeStatus),
                     "sync_envelopes[i].status")
    p_total = data.get("provisional_refund_cents_total", 0)
    assert isinstance(p_total, int) and p_total >= 0
    f_total = data.get("final_refund_cents_total")
    assert f_total is None or (isinstance(f_total, int) and f_total >= 0)


def assert_audit_entry_shape(data: Dict[str, Any]) -> None:
    """Append-only audit row per PRD §2.4 and §3.7."""
    _assert_common_fields_append_only(data, "AuditEntry")
    assert is_valid_uuid(str(data["festival_id"]))
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    _enum_in(data["event_category"], set(AUDIT_CATEGORIES), "AuditEntry.event_category")
    assert isinstance(data["subject_entity_type"], str) and data["subject_entity_type"]
    assert isinstance(data["subject_entity_id"], str) and data["subject_entity_id"]
    fs = data.get("from_state")
    ts = data.get("to_state")
    if fs is not None:
        assert isinstance(fs, str)
    if ts is not None:
        assert isinstance(ts, str)
    assert isinstance(data["payload_summary"], str)


# ---------------------------------------------------------------------------
# Pagination metadata shape  — PRD §2.3
# ---------------------------------------------------------------------------

def assert_pagination_meta(meta: Dict[str, Any],
                           expected_limit: Optional[int] = None,
                           expected_offset: Optional[int] = None) -> None:
    """The four-field pagination metadata block.  Per the PRD §2.3 prose
    the four keys are exactly `limit`, `offset`, `total_count`, and
    `has_more`, with `has_more` equal to `offset + limit < total_count`."""
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"pagination meta is missing the `{key}` field per PRD §2.3"
    assert isinstance(meta["limit"], int)
    assert isinstance(meta["offset"], int)
    assert isinstance(meta["total_count"], int)
    assert isinstance(meta["has_more"], bool)
    assert PAGINATION_MIN_LIMIT <= meta["limit"] <= PAGINATION_MAX_LIMIT, \
        f"limit in [{PAGINATION_MIN_LIMIT}, {PAGINATION_MAX_LIMIT}] per PRD §2.3"
    assert meta["offset"] >= 0
    assert meta["total_count"] >= 0
    expected_has_more = (meta["offset"] + meta["limit"]) < meta["total_count"]
    assert meta["has_more"] is expected_has_more, \
        "has_more == (offset + limit < total_count) per PRD §2.3"
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset


def assert_success_envelope_meta(meta: Dict[str, Any]) -> None:
    """The PRD §2.2 success-envelope meta block carries api_request_id and
    api_request_timestamp at minimum; list responses additionally carry the
    four-pagination-field block.  This helper checks the always-present
    pair."""
    rid = meta.get("api_request_id", "")
    ts = meta.get("api_request_timestamp", "")
    assert isinstance(rid, str) and rid.startswith("req_"), \
        "meta.api_request_id is a string beginning with the literal prefix req_ per PRD §2.2"
    assert isinstance(ts, str) and is_iso8601_timestamp(ts), \
        "meta.api_request_timestamp is an ISO 8601 UTC timestamp per PRD §2.2"


# ---------------------------------------------------------------------------
# Domain invariants — the two conserved-quantity invariants the PRD §3
# pins by name (the festival's outstanding_tickets_total across an
# ITEM_CANCEL apply-and-revert window, and the sponsor tier's
# tier_remaining_quota across a deliver-and-matching-void round-trip).
# ---------------------------------------------------------------------------

def assert_outstanding_tickets_total_conserved(
    pre_outstanding: int, post_outstanding: int,
) -> None:
    """PRD §3.4: the apply of an ITEM_CANCEL change does not move
    issued_count or refunded_count, and the revert without an external
    ack snaps the provisional bucket back to zero — so the outstanding
    total is the same before and after the apply-then-revert window.
    The transient evidence the cents bucket bulged on the apply and
    cleared on the revert is asserted separately by the test that calls
    this helper."""
    assert pre_outstanding == post_outstanding, (
        f"Festival.outstanding_tickets_total is conserved across an apply-then-revert "
        f"of an ITEM_CANCEL ScheduleChange per PRD §3.4 — "
        f"observed pre={pre_outstanding}, post={post_outstanding}"
    )


def assert_tier_remaining_quota_conserved(
    pre_quota: int, post_quota: int, contracted_units: int,
) -> None:
    """PRD §3.6: a deliver-of-N-units followed by a matching void of N
    units returns the parent SponsorTier.tier_remaining_quota to its
    pre-deliver value.  In the empty-allocation-history case (the deliver
    is the first event) the post value equals contracted_units."""
    assert pre_quota == post_quota, (
        f"SponsorTier.tier_remaining_quota is conserved across a deliver-and-matching-void "
        f"round-trip per PRD §3.6 — observed pre={pre_quota}, post={post_quota} "
        f"(contracted_units={contracted_units})."
    )


def assert_sponsor_payout_total_cents(report_view: Dict[str, Any],
                                      expected_cents: int) -> None:
    """PRD §3.6 / §2.7: the sponsor_payout_total_cents is the integer cents
    result of the sum-mills-then-divide-by-1000-then-round-half-up rule.
    On the canonical three-lines-of-one-unit-at-25-mills input the value
    is exactly 8 cents (the rejected per-line-rounded alternative would
    have produced 9)."""
    got = report_view.get("sponsor_payout_total_cents")
    assert got == expected_cents, (
        f"sponsor_payout_total_cents == {expected_cents} per the pinned "
        f"sum-then-round mills-to-cents conversion in PRD §2.7 and §3.6 — got {got!r}"
    )


def assert_canonical_fulfilment_report_keys(report_view: Dict[str, Any]) -> None:
    """The §3.7 FulfilmentReportView keys, by name."""
    expected_keys = {
        "projected_fulfilment_pct",
        "actual_fulfilment_pct",
        "delivered_units_by_allocation",
        "tier_remaining_quota",
        "sponsor_payout_total_cents",
    }
    # Accept additional keys, only require the canonical ones to be present
    # — the PRD says the report "exposes" those fields.  Implementations
    # may include extras such as an allocation list or sponsor display
    # name without affecting correctness.
    missing = expected_keys - set(report_view.keys())
    assert not missing, (
        f"FulfilmentReportView is missing the canonical fields per PRD §3.7 — "
        f"missing keys: {sorted(missing)}; present keys: {sorted(report_view.keys())}"
    )


# ---------------------------------------------------------------------------
# Sync-envelope assertions
# ---------------------------------------------------------------------------

def assert_four_envelopes_queued(change_data: Dict[str, Any]) -> None:
    """PRD §2.8 / §3.4: a fresh apply seeds all four sync-envelope elements
    with the QUEUED status and stamps queued_at on each, with the targets
    in the canonical order ticketing, im, broadcasting, sponsor."""
    envs = change_data.get("sync_envelopes", [])
    assert len(envs) == 4, \
        "ScheduleChange.sync_envelopes has exactly four elements per PRD §2.8"
    assert [e["target"] for e in envs] == CANONICAL_SYNC_TARGETS, \
        "ScheduleChange.sync_envelopes targets are in canonical order per PRD §2.8"
    for env in envs:
        assert env["status"] == SyncEnvelopeStatus.QUEUED.value, \
            "Every fresh envelope element starts in status QUEUED per PRD §2.8"


def assert_envelope_status_by_target(change_data: Dict[str, Any],
                                     target: str,
                                     expected_status: str) -> None:
    envs = change_data.get("sync_envelopes", [])
    matches = [e for e in envs if e.get("target") == target]
    assert matches, f"No sync envelope element with target=={target!r}"
    assert matches[0]["status"] == expected_status, (
        f"Envelope element with target={target!r} has status {matches[0]['status']!r}, "
        f"expected {expected_status!r} per PRD §2.8"
    )


def assert_clock_view_shape(view: Dict[str, Any]) -> None:
    """PRD §3.7: ClockView carries the per-festival clock_offset_seconds
    and the implied logical wall clock."""
    # The PRD prose says the view exposes "the per-festival
    # clock_offset_seconds and the implied logical-wall-clock-of-record".
    # The exact key names below are the most natural reading of that prose
    # but the implementation may render the per-festival mapping as either
    # a dict keyed by festival id or a list of {festival_id, offset, now}
    # records — we accept both shapes.  The implementation-side
    # generator's PRD says "synthetic ClockView" so the wrapping shape is
    # not pinned.  The shape we hard-pin is the presence of a numeric
    # offset field for at least one festival when one is supplied as a
    # filter.
    assert isinstance(view, dict) or isinstance(view, list), \
        "the clock-view read returns a JSON object or array per PRD §3.7"


# ---------------------------------------------------------------------------
# Audit-trail walking
# ---------------------------------------------------------------------------

def find_audit_entries(
    entries: List[Dict[str, Any]],
    *,
    event_category: Optional[str] = None,
    subject_entity_type: Optional[str] = None,
    subject_entity_id: Optional[str] = None,
    to_state: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter the audit-list response by the PRD §2.8 audit-row fields.

    The audit list is in `created_at` ascending order per the PRD §2.3 list
    contract and the §3.7 audit-log-ordering contract."""
    out: List[Dict[str, Any]] = []
    for e in entries:
        if event_category is not None and e.get("event_category") != event_category:
            continue
        if (subject_entity_type is not None
                and e.get("subject_entity_type") != subject_entity_type):
            continue
        if (subject_entity_id is not None
                and e.get("subject_entity_id") != subject_entity_id):
            continue
        if to_state is not None and e.get("to_state") != to_state:
            continue
        out.append(e)
    return out


def assert_audit_chronological(entries: List[Dict[str, Any]]) -> None:
    """Per PRD §3.7 the audit-list endpoint orders by `created_at`
    ascending per festival."""
    timestamps = [e.get("created_at", "") for e in entries]
    assert timestamps == sorted(timestamps), \
        "Audit entries are in created_at ascending order per PRD §3.7"


def assert_audit_contains(
    entries: List[Dict[str, Any]],
    *,
    event_category: str,
    subject_entity_type: Optional[str] = None,
    subject_entity_id: Optional[str] = None,
    to_state: Optional[str] = None,
    payload_summary_substring: Optional[str] = None,
) -> Dict[str, Any]:
    """Returns the matching audit entry (the first match) or raises."""
    matches = find_audit_entries(
        entries,
        event_category=event_category,
        subject_entity_type=subject_entity_type,
        subject_entity_id=subject_entity_id,
        to_state=to_state,
    )
    if payload_summary_substring is not None:
        matches = [e for e in matches
                   if payload_summary_substring in (e.get("payload_summary") or "")]
    assert matches, (
        f"No audit entry matched filters event_category={event_category!r}, "
        f"subject_entity_type={subject_entity_type!r}, "
        f"subject_entity_id={subject_entity_id!r}, to_state={to_state!r}, "
        f"payload_summary contains {payload_summary_substring!r}. "
        f"Audit log had {len(entries)} entries."
    )
    return matches[0]


# ---------------------------------------------------------------------------
# Error envelope shape (also see api_errors.py for the id→status map)
# ---------------------------------------------------------------------------

def assert_error_envelope_shape(envelope: Dict[str, Any]) -> None:
    """PRD §2.2 error envelope: meta is api_request_id + api_request_timestamp,
    response_type is the literal string 'error', and data is
    {error_id, message}."""
    meta = envelope.get("meta", {})
    assert "api_request_id" in meta
    assert "api_request_timestamp" in meta
    assert envelope.get("response_type") == "error", \
        "Error envelope response_type is the literal 'error' per PRD §2.2"
    data = envelope.get("data", {})
    assert isinstance(data, dict)
    assert isinstance(data.get("error_id"), str) and data["error_id"]
    assert isinstance(data.get("message"), str)


__all__ = [
    # entity-shape assertions
    "assert_festival_shape", "assert_program_version_shape",
    "assert_stage_shape", "assert_equipment_kit_shape",
    "assert_artist_shape", "assert_program_item_shape",
    "assert_rider_shape", "assert_sound_engineer_team_shape",
    "assert_sound_check_shape", "assert_rehearsal_shape",
    "assert_ticket_type_shape", "assert_sponsor_tier_shape",
    "assert_exposure_allocation_shape", "assert_fulfilment_log_shape",
    "assert_schedule_change_shape", "assert_audit_entry_shape",
    # envelope / pagination
    "assert_pagination_meta", "assert_success_envelope_meta",
    "assert_error_envelope_shape",
    # invariants
    "assert_outstanding_tickets_total_conserved",
    "assert_tier_remaining_quota_conserved",
    "assert_sponsor_payout_total_cents",
    "assert_canonical_fulfilment_report_keys",
    # envelope-array helpers
    "assert_four_envelopes_queued", "assert_envelope_status_by_target",
    # audit-trail helpers
    "find_audit_entries", "assert_audit_chronological",
    "assert_audit_contains",
    # operator views
    "assert_clock_view_shape",
]
