"""Composite setup helpers for the festival-program-schedule benchmark.

The PRD §3 pipeline is "create festival → open scheduling → register
stages and equipment kits and the global artist row → create a program
version and a few program items → confirm the items → publish the
version, which pins the festival's current_program_version_id and flips
the festival into PUBLISHED → register ticket types and issue tickets
→ register sponsor tiers, seed the exposure catalog, create per-
allocation rows, run the waterfall sweep → advance the clock past the
festival start so it goes LIVE, past each item's start/end so they go
ON_STAGE then PERFORMED, deliver exposures, then advance past the
festival end + grace so it goes CLOSED and rehearsals auto-archive →
run the post-event sweep with compute_payout=true → read the
fulfilment report".

The fixtures below stage the system at every intermediate point on that
pipeline so test functions can leap directly to the precondition they
need.  All fixtures use the lenient `get_success_data` validator
internally so a setup failure surfaces as a clear "Setup failed: ..."
message rather than as a confusing assertion-error elsewhere.
"""
from __future__ import annotations

import time as wall_time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as F
from .api_client import ApiClient
from .constants import (
    CANONICAL_SYNC_TARGETS, CATALOG_KINDS, THRESHOLDS, DAY_SECONDS,
)
from .test_users import (
    ADMIN_HEADERS, AUDIT_HEADERS, LIAISON_HEADERS, PRODUCER_HEADERS,
    SPONSOR_HEADERS, STAGE_HEADERS, TICKETING_HEADERS, TEST_USERS,
)


# ---------------------------------------------------------------------------
# Bag-of-ids container.  Every composite fixture returns a snapshot of the
# resources it built.  The dataclass keeps the field names stable across
# tests so the bag can be flat-passed between helpers.
# ---------------------------------------------------------------------------

@dataclass
class WorldBag:
    """Snapshot of the seeded entities.  Fields are populated as the
    fixture progresses through the pipeline; trailing fields are None
    when the fixture stopped earlier in the pipeline."""
    festival: Dict[str, Any] = field(default_factory=dict)
    festival_id: str = ""
    artist: Dict[str, Any] = field(default_factory=dict)
    artist_id: str = ""
    stage: Dict[str, Any] = field(default_factory=dict)
    stage_id: str = ""
    equipment_kit: Optional[Dict[str, Any]] = None
    version: Optional[Dict[str, Any]] = None
    version_id: Optional[str] = None
    program_item: Optional[Dict[str, Any]] = None
    program_item_id: Optional[str] = None
    program_items: List[Dict[str, Any]] = field(default_factory=list)
    team: Optional[Dict[str, Any]] = None
    sound_check_slot: Optional[Dict[str, Any]] = None
    rehearsal: Optional[Dict[str, Any]] = None
    ticket_type: Optional[Dict[str, Any]] = None
    sponsor_tier: Optional[Dict[str, Any]] = None
    exposure_allocation: Optional[Dict[str, Any]] = None
    schedule_change: Optional[Dict[str, Any]] = None
    # Time anchors that subsequent fixture steps reuse so the windows
    # the steps build don't drift away from the festival window.
    festival_start: int = 0
    festival_end: int = 0


# ---------------------------------------------------------------------------
# Tier 0 — bare festival, optionally moved to SCHEDULING.  The simplest
# entry point; every other fixture builds on top of this one.
# ---------------------------------------------------------------------------

def create_festival(api: ApiClient,
                    *,
                    day_count: int = 3,
                    name_suffix: str = "",
                    headers: Optional[Dict[str, str]] = None,
                    start_offset_seconds: int = 0) -> WorldBag:
    """Create a fresh festival in PLANNED.  The festival's window starts
    at the deterministic TIME_ANCHOR offset by `start_offset_seconds` so
    parallel tests can pick distinct windows by varying the offset.
    `day_count` controls the festival_day_count integer that the
    provisional-refund pro-rata formula uses as its divisor — the
    canonical worked example in PRD §3.4 uses 3 days.
    """
    h = headers or PRODUCER_HEADERS
    start = F.TIME_ANCHOR_UNIX_SECONDS + int(start_offset_seconds)
    end = start + int(day_count) * F.ONE_DAY_SECONDS
    name = f"{F.TEST_DEFAULTS['FESTIVAL_NAME_PREFIX']}-{name_suffix or F._unique_suffix()}"
    body = F.festival_payload(name=name, start_time=start, end_time=end)
    resp = api.create_festival(body, h)
    data = get_success_data(resp)
    bag = WorldBag(
        festival=data, festival_id=str(data["id"]),
        festival_start=int(data["start_time"]),
        festival_end=int(data["end_time"]),
    )
    return bag


def open_scheduling(api: ApiClient, bag: WorldBag,
                    *, headers: Optional[Dict[str, str]] = None) -> WorldBag:
    """PLANNED → SCHEDULING."""
    h = headers or PRODUCER_HEADERS
    resp = api.open_scheduling(bag.festival_id, h)
    data = get_success_data(resp)
    bag.festival = data
    return bag


def festival_in_scheduling(api: ApiClient,
                           *,
                           day_count: int = 3,
                           start_offset_seconds: int = 0,
                           ) -> WorldBag:
    """Combined: create + open-scheduling."""
    bag = create_festival(api,
                          day_count=day_count,
                          start_offset_seconds=start_offset_seconds)
    open_scheduling(api, bag)
    return bag


# ---------------------------------------------------------------------------
# Tier 1 — festival with one global artist, one stage, an optional
# equipment kit, and a single fresh DRAFT program version.
# ---------------------------------------------------------------------------

def register_artist(api: ApiClient,
                    *,
                    tier: str = "OPENER",
                    home_city: Optional[str] = None,
                    external_commitments: Optional[List[Dict[str, Any]]] = None,
                    minimum_travel_buffer_hours: Optional[int] = None,
                    stage_name: Optional[str] = None,
                    ) -> Dict[str, Any]:
    """Global artist registration — the PRD §3.2 prose names the field
    set as stage_name, tier, home_city, external_commitments,
    minimum_travel_buffer_hours."""
    body = F.artist_payload(
        stage_name=stage_name, tier=tier, home_city=home_city,
        external_commitments=external_commitments,
        minimum_travel_buffer_hours=minimum_travel_buffer_hours,
    )
    resp = api.create_artist(body, LIAISON_HEADERS)
    return get_success_data(resp)


def add_stage(api: ApiClient, bag: WorldBag,
              *,
              zone_capacity: int = 100,
              changeover_buffer_seconds: Optional[int] = None,
              equipment_kits_codes: Optional[List[str]] = None,
              is_emergency_substitute: bool = False,
              ) -> Dict[str, Any]:
    body = F.stage_payload(
        zone_capacity=zone_capacity,
        changeover_buffer_seconds=changeover_buffer_seconds,
        equipment_kits=equipment_kits_codes or [],
        is_emergency_substitute=is_emergency_substitute,
    )
    resp = api.create_stage(bag.festival_id, body, STAGE_HEADERS)
    data = get_success_data(resp)
    if not bag.stage:
        bag.stage = data
        bag.stage_id = str(data["id"])
    return data


def add_equipment_kit(api: ApiClient, bag: WorldBag,
                      *, kit_code: str, total_units: int = 1) -> Dict[str, Any]:
    body = F.equipment_kit_payload(kit_code=kit_code, total_units=total_units)
    resp = api.create_equipment_kit(bag.festival_id, body, STAGE_HEADERS)
    data = get_success_data(resp)
    bag.equipment_kit = data
    return data


def add_program_version(api: ApiClient, bag: WorldBag,
                        *, version_label: Optional[str] = None) -> Dict[str, Any]:
    body = F.program_version_payload(version_label=version_label)
    resp = api.create_program_version(bag.festival_id, body, PRODUCER_HEADERS)
    data = get_success_data(resp)
    if bag.version is None:
        bag.version = data
        bag.version_id = str(data["id"])
    return data


def base_world(api: ApiClient,
               *,
               day_count: int = 3,
               artist_tier: str = "OPENER",
               artist_external_commitments: Optional[List[Dict[str, Any]]] = None,
               artist_min_buffer_hours: Optional[int] = None,
               stage_zone_capacity: int = 100,
               equipment_kit_code: Optional[str] = None,
               equipment_kit_total_units: int = 1,
               version_label: str = "v1-initial",
               start_offset_seconds: int = 0,
               ) -> WorldBag:
    """Compose a festival-in-SCHEDULING with one stage, one artist, and
    a DRAFT program version.  This is the workhorse for ~80% of the
    tests."""
    bag = festival_in_scheduling(api, day_count=day_count,
                                 start_offset_seconds=start_offset_seconds)
    artist = register_artist(api,
                             tier=artist_tier,
                             external_commitments=artist_external_commitments,
                             minimum_travel_buffer_hours=artist_min_buffer_hours)
    bag.artist = artist
    bag.artist_id = str(artist["id"])
    # The stage wires the equipment_kit_code into its `equipment_kits`
    # array when one is supplied so the per-item kit-membership guard
    # passes.  When no kit_code is supplied the stage's array is empty
    # and the item's `equipment_kit_codes` must also be empty.
    kit_codes_for_stage: List[str] = []
    if equipment_kit_code is not None:
        kit_codes_for_stage.append(equipment_kit_code)
    add_stage(api, bag, zone_capacity=stage_zone_capacity,
              equipment_kits_codes=kit_codes_for_stage)
    if equipment_kit_code is not None:
        add_equipment_kit(api, bag,
                          kit_code=equipment_kit_code,
                          total_units=equipment_kit_total_units)
    add_program_version(api, bag, version_label=version_label)
    return bag


# ---------------------------------------------------------------------------
# Tier 2 — base_world plus a single PROPOSED program item, then the
# CONFIRMED variant, then the ANNOUNCED variant for the festival-already-
# PUBLISHED case.
# ---------------------------------------------------------------------------

def _item_window(bag: WorldBag,
                 *, day_index: int = 0,
                 hour_offset_in_day: int = 12,
                 duration_seconds: int = F.ONE_HOUR_SECONDS) -> Tuple[int, int]:
    """Compute a [start, end) integer-seconds window that lies inside the
    festival window and on the requested calendar-day-index of the
    festival.  day_index 0 is the first day of the festival, 1 the
    second, and so on.  The hour_offset_in_day picks the wall-clock hour
    inside that day."""
    day_start = bag.festival_start + day_index * DAY_SECONDS
    start = day_start + hour_offset_in_day * 3600
    end = start + int(duration_seconds)
    assert bag.festival_start <= start < end <= bag.festival_end, (
        f"Computed item window [{start}, {end}) is not contained in the "
        f"festival window [{bag.festival_start}, {bag.festival_end}) — "
        f"increase day_count when constructing the bag"
    )
    return start, end


def add_program_item(api: ApiClient, bag: WorldBag,
                     *,
                     day_index: int = 0,
                     hour_offset_in_day: int = 12,
                     duration_seconds: int = F.ONE_HOUR_SECONDS,
                     artist_id: Optional[str] = None,
                     stage_id: Optional[str] = None,
                     program_version_id: Optional[str] = None,
                     equipment_kit_codes: Optional[List[str]] = None,
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    """Create a fresh PROPOSED program item on the bag's stage and
    artist.  Records it on bag.program_items and on the singletons
    bag.program_item / bag.program_item_id when those are still
    unset."""
    h = headers or LIAISON_HEADERS
    start, end = _item_window(bag, day_index=day_index,
                              hour_offset_in_day=hour_offset_in_day,
                              duration_seconds=duration_seconds)
    body = F.program_item_payload(
        program_version_id=program_version_id or (bag.version_id or ""),
        artist_id=artist_id or bag.artist_id,
        stage_id=stage_id or bag.stage_id,
        start_time=start, end_time=end,
        equipment_kit_codes=equipment_kit_codes,
    )
    resp = api.create_program_item(bag.festival_id, body, h)
    data = get_success_data(resp)
    bag.program_items.append(data)
    if bag.program_item is None:
        bag.program_item = data
        bag.program_item_id = str(data["id"])
    return data


def confirm_item(api: ApiClient, bag: WorldBag, item_id: str,
                 *, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PROPOSED → CONFIRMED."""
    h = headers or LIAISON_HEADERS
    resp = api.confirm_program_item(bag.festival_id, item_id, h)
    data = get_success_data(resp)
    # Update the cached version of the item on the bag.
    for i, it in enumerate(bag.program_items):
        if str(it.get("id")) == item_id:
            bag.program_items[i] = data
    if bag.program_item is not None and str(bag.program_item.get("id")) == item_id:
        bag.program_item = data
    return data


def publish_version(api: ApiClient, bag: WorldBag,
                    version_id: Optional[str] = None,
                    *, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Drive the version through submit-for-review then publish, which
    pins the festival's current_program_version_id and flips the
    festival to PUBLISHED per PRD §3.3."""
    h = headers or PRODUCER_HEADERS
    vid = version_id or (bag.version_id or "")
    get_success_data(api.submit_program_version_for_review(bag.festival_id, vid, h))
    pub_resp = api.publish_program_version(bag.festival_id, vid, h)
    data = get_success_data(pub_resp)
    # Refresh the festival snapshot so bag.festival reflects the new
    # current_program_version_id pointer.
    fest = get_success_data(api.get_festival(bag.festival_id, h))
    bag.festival = fest
    if bag.version is not None and str(bag.version.get("id")) == vid:
        bag.version = data
    return data


def announce_item(api: ApiClient, bag: WorldBag, item_id: str,
                  *, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """CONFIRMED → ANNOUNCED."""
    h = headers or LIAISON_HEADERS
    resp = api.announce_program_item(bag.festival_id, item_id, h)
    return get_success_data(resp)


def confirmed_item_world(api: ApiClient,
                         *,
                         artist_tier: str = "OPENER",
                         day_count: int = 3,
                         equipment_kit_code: Optional[str] = None,
                         equipment_kit_total_units: int = 1,
                         publish_the_version: bool = True,
                         ) -> WorldBag:
    """Festival + one stage + one artist + one DRAFT program-version +
    one CONFIRMED program item on day-1.  When publish_the_version is
    true (the default), the program version is also submitted and
    published so the festival's status is PUBLISHED — this is the state
    every announce-and-ticket-issue test needs."""
    bag = base_world(api, day_count=day_count,
                     artist_tier=artist_tier,
                     equipment_kit_code=equipment_kit_code,
                     equipment_kit_total_units=equipment_kit_total_units,
                     stage_zone_capacity=100)
    add_program_item(api, bag, day_index=0, hour_offset_in_day=12,
                     equipment_kit_codes=[equipment_kit_code] if equipment_kit_code else [])
    confirm_item(api, bag, str(bag.program_item["id"]))
    if publish_the_version:
        publish_version(api, bag)
    return bag


# ---------------------------------------------------------------------------
# Tier 3 — ticket types and the refund pathway preconditions.
# ---------------------------------------------------------------------------

def add_ticket_type(api: ApiClient, bag: WorldBag,
                    *,
                    ticket_class: str = "SINGLE_DAY",
                    tied_program_item_ids: Optional[List[str]] = None,
                    zone_name: Optional[str] = None,
                    unit_price_cents: Optional[int] = None,
                    headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    h = headers or TICKETING_HEADERS
    tied = tied_program_item_ids
    if tied is None and bag.program_item_id is not None:
        tied = [bag.program_item_id]
    body = F.ticket_type_payload(
        ticket_class=ticket_class,
        tied_program_item_ids=tied or [],
        zone_name=zone_name,
        unit_price_cents=unit_price_cents,
    )
    resp = api.create_ticket_type(bag.festival_id, body, h)
    data = get_success_data(resp)
    if bag.ticket_type is None:
        bag.ticket_type = data
    return data


def issue_tickets(api: ApiClient, bag: WorldBag, ticket_type_id: str,
                  *, count: int, idempotency_key: Optional[str] = None,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TICKETING_HEADERS
    body = F.ticket_issue_payload(count=count, idempotency_key=idempotency_key)
    resp = api.issue_tickets(bag.festival_id, ticket_type_id, body, h)
    return get_success_data(resp)


def confirmed_published_world_with_ticket(
    api: ApiClient,
    *,
    day_count: int = 3,
    unit_price_cents: int = int(F.TEST_DEFAULTS["UNIT_PRICE_CENTS"]),
    initial_issued: int = int(F.TEST_DEFAULTS["TICKET_COUNT_DEFAULT"]),
    artist_tier: str = "HEADLINER",
    headliner_blocking_rider: bool = True,
) -> WorldBag:
    """The canonical refund-pathway precondition: a festival with a
    published program version, one confirmed-and-announced program item
    on day-1, a SINGLE_DAY ticket type tied to that item, and an
    initial issuance bumping issued_count to `initial_issued`.

    Per PRD §3.3 a HEADLINER announcement requires at least one
    blocking rider on file (HEADLINER_MIN_BLOCKING_RIDERS == 1), so
    when the caller wants the item to also reach ANNOUNCED on a
    HEADLINER artist they should leave headliner_blocking_rider True
    so the fixture pre-fulfils the blocking rider.

    The literal numbers — unit_price_cents=12000, initial_issued=3,
    day_count=3 — match the §3.4 worked-example arithmetic so the
    test asserting provisional_refund_cents_total == 12000 can use
    this fixture verbatim.  Per the §3.4 formula the per-ticket
    provisional figure is round_half_up(12000 * 1 / 3) = 4000 cents
    times the outstanding count of 3 == 12000 cents on the change row
    and the per-type provisional_refund_cents_outstanding bucket.
    """
    bag = base_world(api, day_count=day_count,
                     artist_tier=artist_tier,
                     stage_zone_capacity=max(100, initial_issued + 10))
    add_program_item(api, bag, day_index=1, hour_offset_in_day=12)
    item_id = str(bag.program_item["id"])
    # The blocking-rider preamble is conditional on the caller wanting
    # the announce step to succeed.  Per PRD §3.3's "the universal
    # 'every blocking rider that does exist must be fulfilled'
    # condition", appending an unfulfilled blocking rider would also
    # block the non-HEADLINER announce, and per §3.3's HEADLINER
    # cardinality rule a HEADLINER must have at least one fulfilled
    # blocking rider for the announce to clear.  The two-axes truth
    # table reduces to: "create-and-fulfil one blocking rider when the
    # caller wants the announce to succeed" — exactly the
    # headliner_blocking_rider flag's semantics.
    want_announce = not (artist_tier == "HEADLINER" and not headliner_blocking_rider)
    if want_announce:
        rider_resp = api.create_rider(bag.festival_id, item_id,
                                      F.rider_payload(is_blocking=True,
                                                      category="HOSPITALITY",
                                                      description="green-room blocking rider"),
                                      LIAISON_HEADERS)
        rider_data = get_success_data(rider_resp)
        fulfil_resp = api.fulfil_rider(bag.festival_id, item_id, str(rider_data["id"]),
                                       F.rider_fulfil_payload(), LIAISON_HEADERS)
        get_success_data(fulfil_resp)
    confirm_item(api, bag, item_id)
    publish_version(api, bag)
    # Announce the item — this is the §3.3 announce step that gates on
    # the headliner-blocking-rider minimum and on the festival's status
    # being PUBLISHED.  When the caller has asked for the
    # zero-blocking-rider HEADLINER negative case the announce is
    # deliberately skipped so the test under test can issue it itself
    # and observe the rejection.
    if want_announce:
        get_success_data(api.announce_program_item(bag.festival_id, item_id, LIAISON_HEADERS))
    # Ticket type tied to the item, then the issuance.
    ticket = add_ticket_type(api, bag,
                             tied_program_item_ids=[item_id],
                             unit_price_cents=unit_price_cents)
    if initial_issued > 0:
        issued = issue_tickets(api, bag, str(ticket["id"]), count=initial_issued)
        bag.ticket_type = issued  # the post-issuance ticket-type snapshot
    return bag


# ---------------------------------------------------------------------------
# Tier 4 — schedule-change apply chain (the cascade-A / cascade-B
# originating triggers from PRD §3.5).
# ---------------------------------------------------------------------------

def create_and_apply_item_cancel(
    api: ApiClient,
    bag: WorldBag,
    *,
    target_item_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    reason: str = "weather",
) -> Dict[str, Any]:
    """Create a ScheduleChange of kind ITEM_CANCEL targeting the bag's
    program item, then POST the apply endpoint.  The apply fires the
    cascade A's sound-check leg (when a sound-check exists) and the
    cascade B's exposure-allocation leg (when a tied allocation
    exists), and stamps provisional_refund_cents_total on the change
    row from the formula in PRD §3.4 applied to the bag's tied ticket
    types.

    Returns the post-apply ScheduleChange row.
    """
    tid = target_item_id or (bag.program_item_id or "")
    create_body = F.schedule_change_payload(
        change_kind="ITEM_CANCEL",
        target_program_item_id=tid,
        payload=F.item_cancel_inner_payload(reason=reason),
        idempotency_key=idempotency_key,
    )
    create_resp = api.create_schedule_change(bag.festival_id, create_body,
                                             PRODUCER_HEADERS)
    change = get_success_data(create_resp)
    apply_resp = api.apply_schedule_change(bag.festival_id, str(change["id"]),
                                           PRODUCER_HEADERS)
    applied = get_success_data(apply_resp)
    bag.schedule_change = applied
    return applied


def confirm_refund_via_ack(api: ApiClient,
                           bag: WorldBag,
                           change_id: str,
                           refund_breakdown: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Land the external-ticketing-system refund-confirmed event on a
    given APPLIED ScheduleChange, which stamps the change's
    final_refund_cents_total, flips the ticketing envelope element to
    ACKNOWLEDGED, decrements each tied TicketType's
    provisional_refund_cents_outstanding, and increments each tied
    TicketType's refunded_count — see PRD §3.4."""
    body = F.refund_confirmed_payload(
        festival_id=bag.festival_id,
        schedule_change_id=change_id,
        refund_breakdown=refund_breakdown,
    )
    resp = api.refund_confirmed(body, ADMIN_HEADERS)
    return get_success_data(resp)


def ack_remaining_targets(api: ApiClient, bag: WorldBag, change_id: str,
                          *, targets: Optional[List[str]] = None) -> None:
    """Drive the non-ticketing targets to ACKNOWLEDGED via the generic
    sync-ack ingress.  After the last QUEUED envelope flips, the change
    advances APPLIED → SYNCED per PRD §2.8."""
    for target in (targets if targets is not None else ["im", "broadcasting", "sponsor"]):
        body = F.sync_ack_payload(festival_id=bag.festival_id,
                                  schedule_change_id=change_id,
                                  target=target,
                                  succeeded=True,
                                  payload_hash="deadbeef")
        get_success_data(api.sync_ack(body, ADMIN_HEADERS))


# ---------------------------------------------------------------------------
# Tier 5 — sponsor waterfall, sweep, deliver-and-void, the post-event
# fulfilment report.
# ---------------------------------------------------------------------------

def add_sponsor_tier(api: ApiClient,
                     bag: WorldBag,
                     *,
                     tier_code: str,
                     priority_rank: int = 1,
                     sponsor_external_id: Optional[str] = None,
                     contracted_units: int = 10,
                     contract_kinds_allowed: Optional[List[str]] = None,
                     ) -> Dict[str, Any]:
    body = F.sponsor_tier_payload(
        tier_code=tier_code,
        priority_rank=priority_rank,
        sponsor_external_id=sponsor_external_id,
        contracted_units=contracted_units,
        contract_kinds_allowed=contract_kinds_allowed,
    )
    resp = api.create_sponsor_tier(bag.festival_id, body, SPONSOR_HEADERS)
    data = get_success_data(resp)
    if bag.sponsor_tier is None:
        bag.sponsor_tier = data
    return data


def seed_default_catalog(api: ApiClient, bag: WorldBag,
                         *,
                         stage_name: int = 1000,
                         screen_time: int = 1000,
                         artist_mention: int = 1000,
                         branded_zone: int = 10) -> Dict[str, Any]:
    """Seed the per-kind exposure-catalog dictionary.

    The four optional kwargs map one-to-one to the four catalog kinds the
    PRD §2.8 dictionary uses, and each defaults to a comfortable headroom
    so callers that only care about one specific kind can leave the others
    unspecified.
    """
    body = F.exposure_catalog_payload(stage_name=stage_name,
                                      screen_time=screen_time,
                                      artist_mention=artist_mention,
                                      branded_zone=branded_zone)
    resp = api.seed_exposure_catalog(bag.festival_id, body, PRODUCER_HEADERS)
    return get_success_data(resp)


def add_exposure_allocation(api: ApiClient, bag: WorldBag,
                            tier_id: str,
                            *,
                            kind: str,
                            requested_units: int,
                            program_item_id: Optional[str] = None,
                            pinned_rate_cents_per_unit: Optional[int] = None,
                            ) -> Dict[str, Any]:
    body = F.exposure_allocation_payload(
        kind=kind,
        requested_units=requested_units,
        program_item_id=program_item_id,
        pinned_rate_cents_per_unit=pinned_rate_cents_per_unit,
    )
    resp = api.create_exposure_allocation(bag.festival_id, tier_id, body, SPONSOR_HEADERS)
    data = get_success_data(resp)
    if bag.exposure_allocation is None:
        bag.exposure_allocation = data
    return data


def run_waterfall(api: ApiClient, bag: WorldBag) -> Dict[str, Any]:
    """POST /festivals/{fid}/sponsor-allocation-sweep per PRD §3.6.
    Idempotent: running it again with no input change yields the same
    actual_units vector."""
    resp = api.run_sponsor_allocation_sweep(bag.festival_id, SPONSOR_HEADERS)
    return get_success_data(resp)


def waterfall_six_sponsor_world(api: ApiClient) -> Dict[str, Any]:
    """Build the §3.6 canonical six-sponsor waterfall scenario: one
    TITLE-rank-1 (id 'title-aaa', contracted 5), two GOLD-ranks 1 and 2
    (ids 'gold-aaa' and 'gold-bbb', contracted 2 each), three SILVER
    ranks 1 / 2 / 3 (ids 'silver-aaa' / 'silver-bbb' / 'silver-ccc',
    contracted 1 each).  The branded-zone catalog pool is 10 units.

    Returns a dict mapping sponsor_external_id → the allocation row's
    post-sweep state so the test can assert the canonical (5, 2, 2,
    1, 0, 0) tuple.
    """
    bag = festival_in_scheduling(api, day_count=3)
    # No stage capacity constraint matters here — the test doesn't issue
    # tickets, so the stage's zone_capacity is irrelevant.
    add_stage(api, bag, zone_capacity=10_000)
    # Seed the catalog with branded_zone == 10.
    seed_default_catalog(api, bag, branded_zone=10)
    sponsors_spec: List[Tuple[str, int, str, int, List[str]]] = [
        ("TITLE",  1, "title-aaa", 5, ["branded_zone"]),
        ("GOLD",   1, "gold-aaa",  2, ["branded_zone"]),
        ("GOLD",   2, "gold-bbb",  2, ["branded_zone"]),
        ("SILVER", 1, "silver-aaa", 1, ["branded_zone"]),
        ("SILVER", 2, "silver-bbb", 1, ["branded_zone"]),
        ("SILVER", 3, "silver-ccc", 1, ["branded_zone"]),
    ]
    tiers_and_allocs: Dict[str, Dict[str, Any]] = {}
    for tier_code, rank, ext_id, contracted, kinds in sponsors_spec:
        tier = add_sponsor_tier(api, bag,
                                tier_code=tier_code,
                                priority_rank=rank,
                                sponsor_external_id=ext_id,
                                contracted_units=contracted,
                                contract_kinds_allowed=kinds)
        alloc = add_exposure_allocation(api, bag, str(tier["id"]),
                                        kind="branded_zone",
                                        requested_units=contracted)
        tiers_and_allocs[ext_id] = {"tier": tier, "allocation": alloc}
    sweep_result = run_waterfall(api, bag)
    # Read the per-allocation actual_units back so the bag carries the
    # post-sweep state the assertions consult.
    listing = get_success_data(
        api.list_exposure_allocations(bag.festival_id, SPONSOR_HEADERS,
                                      params={"limit": 100, "offset": 0})
    )
    rows = listing if isinstance(listing, list) else listing.get("items", listing.get("data", []))
    # Build a map by sponsor_external_id, joining the tier id back to
    # the spec.  The list endpoint returns the allocation rows with
    # the sponsor_tier_id field per PRD §1.1; we resolve the external
    # id by looking up each tier in the tiers_and_allocs map.
    tid_to_external_id: Dict[str, str] = {
        str(spec["tier"]["id"]): ext for ext, spec in tiers_and_allocs.items()
    }
    by_external: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        tid = str(r.get("sponsor_tier_id"))
        if tid in tid_to_external_id:
            by_external[tid_to_external_id[tid]] = r
    return {"bag": bag, "by_external_id": by_external, "sweep_result": sweep_result}


# ---------------------------------------------------------------------------
# Tier 6 — clock-advance helpers.  The PRD §2.8 contract is the
# /_clock/advance operator endpoint that takes either an absolute
# `to_unix_seconds` or a relative `delta_seconds`.  These helpers wrap
# the two flavours so test code reads like "advance the festival's clock
# to the moment its window opens" rather than the raw body shape.
# ---------------------------------------------------------------------------

def advance_clock_to(api: ApiClient,
                     *,
                     festival_id: Optional[str] = None,
                     to_unix_seconds: int,
                     ) -> Dict[str, Any]:
    """Drive the test clock so the festival's logical wall clock crosses
    the given Unix-seconds threshold.  Per PRD §2.8 the operator-only
    `/_clock/advance` endpoint takes either `delta_seconds` or
    `to_unix_seconds` (exactly one), and a backward target surfaces as
    `ERR_CLOCK_ADVANCE_BACKWARD`.
    """
    body = F.clock_advance_payload(festival_id=festival_id,
                                   to_unix_seconds=int(to_unix_seconds))
    resp = api.advance_clock(body, ADMIN_HEADERS)
    return get_success_data(resp)


def advance_clock_by(api: ApiClient,
                     *,
                     festival_id: Optional[str] = None,
                     delta_seconds: int) -> Dict[str, Any]:
    body = F.clock_advance_payload(festival_id=festival_id,
                                   delta_seconds=int(delta_seconds))
    resp = api.advance_clock(body, ADMIN_HEADERS)
    return get_success_data(resp)


def advance_festival_through_close(api: ApiClient, bag: WorldBag) -> Dict[str, Any]:
    """Move the festival's logical wall clock past
    `end_time + FESTIVAL_CLOSE_GRACE_SECONDS` (the one-hour grace
    constant) so the festival auto-closes per the PRD §2.8 cascade.
    """
    target = bag.festival_end + int(THRESHOLDS["FESTIVAL_CLOSE_GRACE_SECONDS"]) + 1
    return advance_clock_to(api, festival_id=bag.festival_id,
                            to_unix_seconds=target)


def run_post_event_sweep(api: ApiClient, bag: WorldBag,
                         *, compute_payout: bool = True) -> Dict[str, Any]:
    body = F.sweep_payload(festival_id=bag.festival_id,
                           compute_payout=compute_payout)
    resp = api.run_sweep(body, ADMIN_HEADERS)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 7 — sound-engineer team and sound-check slot composite setup.
# ---------------------------------------------------------------------------

def add_team(api: ApiClient, bag: WorldBag,
             *, team_name: Optional[str] = None,
             warmup_minutes: Optional[int] = None) -> Dict[str, Any]:
    body = F.sound_engineer_team_payload(team_name=team_name,
                                         warmup_minutes=warmup_minutes)
    resp = api.create_sound_engineer_team(bag.festival_id, body, STAGE_HEADERS)
    data = get_success_data(resp)
    if bag.team is None:
        bag.team = data
    return data


def add_sound_check_slot(api: ApiClient, bag: WorldBag,
                         program_item_id: str,
                         *, scheduled_window_start: Optional[int] = None,
                         scheduled_window_end: Optional[int] = None,
                         ) -> Dict[str, Any]:
    body = F.sound_check_create_payload(
        scheduled_window_start=scheduled_window_start,
        scheduled_window_end=scheduled_window_end,
    )
    resp = api.create_sound_check(bag.festival_id, program_item_id, body, STAGE_HEADERS)
    data = get_success_data(resp)
    if bag.sound_check_slot is None:
        bag.sound_check_slot = data
    return data


def schedule_sound_check(api: ApiClient, bag: WorldBag,
                         slot_id: str, team_id: str,
                         scheduled_window_start: int,
                         scheduled_window_end: int) -> Dict[str, Any]:
    body = F.sound_check_schedule_payload(
        sound_engineer_team_id=team_id,
        scheduled_window_start=scheduled_window_start,
        scheduled_window_end=scheduled_window_end,
    )
    resp = api.patch_sound_check(bag.festival_id, slot_id, body, STAGE_HEADERS)
    return get_success_data(resp)


def confirmed_item_with_scheduled_sound_check(
    api: ApiClient,
    *,
    artist_tier: str = "OPENER",
    day_count: int = 3,
) -> Tuple[WorldBag, Dict[str, Any], Dict[str, Any]]:
    """Compose a published-festival world with a confirmed item, a
    sound-engineer team, and a SCHEDULED sound-check slot under the
    item — the precondition for the cascade-A test of §3.5 (apply an
    ITEM_CANCEL change, observe the slot and the team flip in causal
    order).  Returns (bag, team_row, slot_row)."""
    bag = base_world(api, day_count=day_count, artist_tier=artist_tier,
                     stage_zone_capacity=200)
    add_program_item(api, bag, day_index=1, hour_offset_in_day=14,
                     duration_seconds=F.ONE_HOUR_SECONDS)
    item_id = str(bag.program_item["id"])
    # Confirm the item so the sound-check's REQUESTED → SCHEDULED gate
    # of PRD §3.5 (parent in CONFIRMED|ANNOUNCED) is satisfied.
    confirm_item(api, bag, item_id)
    publish_version(api, bag)
    # The sound-check window must end at least TEAM_HANDOFF_SECONDS = 600
    # before the parent item's start_time per PRD §3.5.
    item_start = int(bag.program_item["start_time"])
    handoff = int(THRESHOLDS["TEAM_HANDOFF_SECONDS"])
    sc_end = item_start - handoff
    sc_start = sc_end - 1800  # a 30-minute sound-check window
    assert bag.festival_start <= sc_start < sc_end < item_start
    team = add_team(api, bag)
    slot = add_sound_check_slot(api, bag, item_id,
                                scheduled_window_start=sc_start,
                                scheduled_window_end=sc_end)
    scheduled = schedule_sound_check(api, bag, str(slot["id"]), str(team["id"]),
                                     sc_start, sc_end)
    return bag, team, scheduled


# ---------------------------------------------------------------------------
# Tier 8 — exposure-allocation deliver/void round-trip world for the rule-9
# instance-B compensating-invariant test.
# ---------------------------------------------------------------------------

def delivered_allocation_world(api: ApiClient,
                               *,
                               units: int = 3) -> Dict[str, Any]:
    """Compose a festival in CLOSED state where one festival-wide GOLD
    sponsor tier with contracted_units=10 has a single allocation of
    kind=branded_zone that has been DELIVERED with `units` units.  The
    festival itself is in CLOSED state so the deliver-and-void
    invariant test can land a matching void and then a sweep without
    the festival's window-state interfering.

    Returns the dict { bag, tier_id, allocation_id, post_deliver_tier,
    pre_deliver_quota } so tests can read the canonical
    contracted_units-minus-delivered quota and assert the invariant
    after a matching void."""
    bag = festival_in_scheduling(api, day_count=2)
    # No stage capacity matters — we don't issue tickets.
    add_stage(api, bag, zone_capacity=1)
    artist = register_artist(api, tier="OPENER")
    bag.artist = artist
    bag.artist_id = str(artist["id"])
    add_program_version(api, bag, version_label="v1")
    # The festival-wide branded_zone allocation does not need a tied
    # program item.  But we need at least one ProgramItem under the
    # version for the publish step's empty-program guard
    # (ERR_EMPTY_PROGRAM_VERSION) — see PRD §3.3.  So we create a
    # trivial PROPOSED item on day-0.
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    confirm_item(api, bag, str(bag.program_item["id"]))
    publish_version(api, bag)
    # Seed the catalog with a generous branded_zone pool.
    seed_default_catalog(api, bag, branded_zone=units * 2 + 10)
    # The sponsor tier.
    tier = add_sponsor_tier(api, bag,
                            tier_code="GOLD",
                            priority_rank=1,
                            sponsor_external_id="gold-test-tier",
                            contracted_units=units * 2,
                            contract_kinds_allowed=["branded_zone"])
    # A festival-wide branded_zone allocation, requested_units == units
    # so after the sweep the actual_units lands at `units`.
    alloc = add_exposure_allocation(api, bag, str(tier["id"]),
                                    kind="branded_zone",
                                    requested_units=units)
    run_waterfall(api, bag)
    # The deliver endpoint's cross-entity-state gate for an allocation
    # whose program_item_id is null is "the festival is LIVE or
    # CLOSED".  Advance the clock past the festival's start so it goes
    # LIVE, then deliver, then advance past the close so the closing
    # sweep can flip DELIVERED → REPORTED — but for the conservation-
    # invariant test we deliver and then void without the closing
    # sweep, so we only need LIVE.
    target_live = bag.festival_start + 1
    advance_clock_to(api, festival_id=bag.festival_id,
                     to_unix_seconds=target_live)
    # Refresh the tier so we know its pre-deliver tier_remaining_quota.
    pre_tier = get_success_data(api.get_sponsor_tier(bag.festival_id,
                                                    str(tier["id"]),
                                                    AUDIT_HEADERS))
    pre_quota = int(pre_tier["tier_remaining_quota"])
    # Deliver `units` units.
    deliver_resp = api.deliver_exposure(bag.festival_id, str(alloc["id"]),
                                        F.exposure_deliver_payload(units=units),
                                        SPONSOR_HEADERS)
    delivered = get_success_data(deliver_resp)
    post_deliver_tier = get_success_data(
        api.get_sponsor_tier(bag.festival_id, str(tier["id"]), AUDIT_HEADERS)
    )
    return {
        "bag": bag,
        "tier_id": str(tier["id"]),
        "allocation_id": str(alloc["id"]),
        "delivered_row": delivered,
        "pre_deliver_quota": pre_quota,
        "post_deliver_tier": post_deliver_tier,
    }


# ---------------------------------------------------------------------------
# Convenience: a fully-closed-festival world with no remaining live state,
# the precondition for the sweep-when-CLOSED tests and the
# already-closed-rejected refund-confirmed test.
# ---------------------------------------------------------------------------

def closed_festival_world(api: ApiClient, *, day_count: int = 2) -> WorldBag:
    bag = base_world(api, day_count=day_count)
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    confirm_item(api, bag, str(bag.program_item["id"]))
    publish_version(api, bag)
    # Advance through the festival window and the close-grace boundary.
    target = bag.festival_end + int(THRESHOLDS["FESTIVAL_CLOSE_GRACE_SECONDS"]) + 1
    advance_clock_to(api, festival_id=bag.festival_id, to_unix_seconds=target)
    # Re-fetch the festival so the bag's status snapshot reflects CLOSED.
    bag.festival = get_success_data(api.get_festival(bag.festival_id, PRODUCER_HEADERS))
    return bag


# ---------------------------------------------------------------------------
# Audit-log read helper — used by every cascade and state-transition test
# that needs to walk the per-festival audit stream in chronological order.
# ---------------------------------------------------------------------------

def read_audit_log(api: ApiClient, bag: WorldBag,
                   *,
                   event_category: Optional[str] = None,
                   subject_entity_type: Optional[str] = None,
                   created_at_after: Optional[str] = None,
                   limit: int = 100,
                   ) -> List[Dict[str, Any]]:
    """Pull the festival's audit-log rows ordered by created_at
    ascending per PRD §3.7.  Filters mirror the §3.7 list-endpoint
    filter set: event_category, subject_entity_type, and the
    created_at_after ISO-string boundary.

    The `limit` kwarg is clamped to PRD §2.3's hard ceiling of 100 — a
    caller that asks for "all the audit rows" by passing a number above
    the §2.3 [1, 100] range is reading the PRD-permitted maximum.  The
    test scenarios this helper supports never exceed a couple dozen
    audit rows, so the clamp is a no-op semantically while keeping the
    request itself inside the §2.3 sanity bound.
    """
    from test_helpers.constants import PAGINATION_MAX_LIMIT
    effective_limit = max(1, min(int(limit), PAGINATION_MAX_LIMIT))
    params: Dict[str, Any] = {"limit": effective_limit, "offset": 0}
    if event_category is not None:
        params["event_category"] = event_category
    if subject_entity_type is not None:
        params["subject_entity_type"] = subject_entity_type
    if created_at_after is not None:
        params["created_at_after"] = created_at_after
    resp = api.list_audit_entries(bag.festival_id, AUDIT_HEADERS, params=params)
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    # Tolerate the implementation wrapping the array in a 'items' or
    # 'entries' key — the standard envelope unwrap in
    # GenericApiClient returns the inner `data` array directly, so the
    # primary expected shape is a list.
    for k in ("items", "entries", "data", "audit_entries"):
        if k in data and isinstance(data[k], list):
            return data[k]
    raise AssertionError(
        f"Audit-list response had no recognisable list-of-entries shape: "
        f"keys={sorted(data.keys()) if isinstance(data, dict) else type(data).__name__}"
    )


def get_festival_snapshot(api: ApiClient, festival_id: str,
                          *, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or PRODUCER_HEADERS
    return get_success_data(api.get_festival(festival_id, h))


def get_ticket_type_snapshot(api: ApiClient, festival_id: str, tt_id: str,
                             *, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TICKETING_HEADERS
    return get_success_data(api.get_ticket_type(festival_id, tt_id, h))


def get_schedule_change_snapshot(api: ApiClient, festival_id: str, change_id: str,
                                 *, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or PRODUCER_HEADERS
    return get_success_data(api.get_schedule_change(festival_id, change_id, h))


def get_sponsor_tier_snapshot(api: ApiClient, festival_id: str, tier_id: str,
                              *, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or SPONSOR_HEADERS
    return get_success_data(api.get_sponsor_tier(festival_id, tier_id, h))


def get_fulfilment_report_snapshot(api: ApiClient, festival_id: str, tier_id: str,
                                   *, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or SPONSOR_HEADERS
    return get_success_data(api.get_fulfilment_report(festival_id, tier_id, h))


__all__ = [
    "WorldBag",
    "create_festival", "open_scheduling", "festival_in_scheduling",
    "register_artist", "add_stage", "add_equipment_kit",
    "add_program_version", "base_world",
    "add_program_item", "confirm_item", "publish_version", "announce_item",
    "confirmed_item_world",
    "add_ticket_type", "issue_tickets",
    "confirmed_published_world_with_ticket",
    "create_and_apply_item_cancel", "confirm_refund_via_ack",
    "ack_remaining_targets",
    "add_sponsor_tier", "seed_default_catalog",
    "add_exposure_allocation", "run_waterfall",
    "waterfall_six_sponsor_world",
    "advance_clock_to", "advance_clock_by",
    "advance_festival_through_close", "run_post_event_sweep",
    "add_team", "add_sound_check_slot", "schedule_sound_check",
    "confirmed_item_with_scheduled_sound_check",
    "delivered_allocation_world", "closed_festival_world",
    "read_audit_log",
    "get_festival_snapshot", "get_ticket_type_snapshot",
    "get_schedule_change_snapshot", "get_sponsor_tier_snapshot",
    "get_fulfilment_report_snapshot",
]
