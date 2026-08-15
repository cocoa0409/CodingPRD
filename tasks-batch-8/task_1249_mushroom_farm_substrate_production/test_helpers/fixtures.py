"""Composite setup helpers.

These fixtures encapsulate the multi-step farm-chain preambles the PRD's
workflows demand (variety -> tunnel -> batch -> pasteurization -> spawn ->
room -> cycle -> place -> advance -> flushes / pieces / packaging /
commitments). Every fixture starts from the empty database the runner
guarantees and builds only from PRD-declared endpoints.

All fixtures use ``get_success_data`` so a failed setup surfaces as a clear
"Setup failed" error rather than a confusing assertion failure.
"""
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, WB1_VARIETY
from .factories import (
    create_buyer_commitment_payload,
    create_buyer_payload,
    create_commitment_line_payload,
    create_packaged_lot_payload,
    create_pasteurization_cycle_payload,
    create_room_cycle_payload,
    create_room_payload,
    create_substrate_batch_payload,
    create_tunnel_payload,
    create_variety_payload,
    create_worker_payload,
    grade_flush_payload,
    log_piece_payload,
    record_flush_payload,
    report_contamination_event_payload,
)
from .test_users import TEST_USERS, make_harvest_crew_lead_headers

FARM = TEST_USERS["farm_manager_headers"]
COMPOST = TEST_USERS["compost_supervisor_headers"]
GRADING = TEST_USERS["grading_inspector_headers"]
PAYROLL = TEST_USERS["payroll_clerk_headers"]
SALES = TEST_USERS["sales_manager_headers"]
QUALITY = TEST_USERS["quality_inspector_headers"]
ANY = TEST_USERS["any_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, FARM)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: simple creators
# ---------------------------------------------------------------------------

def create_variety(**overrides) -> dict:
    """Create a variety (defaults to the canonical WB1 white-button)."""
    resp = api_client.create_variety(create_variety_payload(**overrides), COMPOST)
    return get_success_data(resp)


def create_tunnel(**overrides) -> dict:
    resp = api_client.create_tunnel(create_tunnel_payload(**overrides), COMPOST)
    return get_success_data(resp)


def create_room(**overrides) -> dict:
    resp = api_client.create_room(create_room_payload(**overrides), FARM)
    return get_success_data(resp)


def create_batch(**overrides) -> dict:
    resp = api_client.create_substrate_batch(create_substrate_batch_payload(**overrides), COMPOST)
    return get_success_data(resp)


def create_worker(**overrides) -> dict:
    resp = api_client.create_worker(create_worker_payload(**overrides), FARM)
    return get_success_data(resp)


def create_buyer(**overrides) -> dict:
    resp = api_client.create_buyer(create_buyer_payload(**overrides), SALES)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: substrate chain — batch driven to a target status
# ---------------------------------------------------------------------------

def create_conditioned_batch(tonnage: float = TEST_DEFAULTS["BATCH_TONNAGE"],
                             recipe: str = "PHASE_II_COMPOST",
                             complete_hours: float = 8.0,
                             tunnel: Optional[dict] = None) -> Tuple[dict, dict, dict]:
    """Batch pasteurized to CONDITIONED. Returns (batch, tunnel, pcycle)."""
    tunnel = tunnel or create_tunnel()
    batch = create_batch(recipe=recipe, tonnage=tonnage)
    pcycle = get_success_data(api_client.create_pasteurization_cycle(
        create_pasteurization_cycle_payload(batch_id=batch["id"], tunnel_id=tunnel["id"]),
        COMPOST,
    ))
    get_success_data(api_client.start_pasteurization_cycle(pcycle["id"], COMPOST))
    get_success_data(api_client.complete_pasteurization_cycle(
        pcycle["id"], {"hours_at_target_temp": complete_hours}, COMPOST,
    ))
    batch = get_success_data(api_client.get_substrate_batch(batch["id"], ANY))
    return batch, tunnel, pcycle


def create_spawned_batch(tonnage: float = TEST_DEFAULTS["BATCH_TONNAGE"],
                         variety: Optional[dict] = None,
                         spawn_kg: float = TEST_DEFAULTS["SPAWN_KG"]) -> Tuple[dict, dict]:
    """Batch driven MIXED -> PASTEURIZING -> CONDITIONED -> SPAWNED.

    Returns (batch, variety)."""
    variety = variety or create_variety()
    batch, _tunnel, _pcycle = create_conditioned_batch(
        tonnage=tonnage, recipe=variety["substrate_recipe"],
    )
    get_success_data(api_client.spawn_batch(
        batch["id"], {"variety_id": variety["id"], "spawn_kg": spawn_kg}, COMPOST,
    ))
    batch = get_success_data(api_client.get_substrate_batch(batch["id"], ANY))
    return batch, variety


# ---------------------------------------------------------------------------
# Tier 3: room cycle at a target phase
# ---------------------------------------------------------------------------

def create_scheduled_room_cycle(batch: dict, room: dict,
                                allocated_tonnage: float = TEST_DEFAULTS["ALLOCATED_TONNAGE"],
                                planned_start: str = TEST_DEFAULTS["CYCLE_PLANNED_START"],
                                planned_end: str = TEST_DEFAULTS["CYCLE_PLANNED_END"]) -> dict:
    """Book a room cycle against the room's CURRENT version (re-read)."""
    fresh_room = get_success_data(api_client.get_room(room["id"], ANY))
    payload = create_room_cycle_payload(
        room_id=room["id"], batch_id=batch["id"],
        allocated_tonnage=allocated_tonnage,
        planned_start=planned_start, planned_end=planned_end,
        expected_room_version=fresh_room["version"],
    )
    return get_success_data(api_client.create_room_cycle(payload, FARM))


def place_room_cycle(room_cycle: dict) -> dict:
    """Move the clock to the cycle's planned_start and place it."""
    set_clock(room_cycle["planned_start"])
    get_success_data(api_client.place_room_cycle(room_cycle["id"], FARM))
    return get_success_data(api_client.get_room_cycle(room_cycle["id"], ANY))


def advance_cycle_to_fruiting(room_cycle: dict, variety: dict) -> dict:
    """Advance SPAWN_RUN -> CASING -> FRUITING, walking the clock by the
    variety's minimum day counts (spawn_run_days then casing_days)."""
    from datetime import datetime, timedelta, timezone

    placed_at = datetime.fromisoformat(room_cycle["placed_at"].replace("Z", "+00:00"))
    t1 = placed_at + timedelta(days=variety["spawn_run_days"])
    set_clock(t1.strftime("%Y-%m-%dT%H:%M:%SZ"))
    get_success_data(api_client.advance_room_cycle(room_cycle["id"], FARM))
    mid = get_success_data(api_client.get_room_cycle(room_cycle["id"], ANY))
    phase_entered = datetime.fromisoformat(mid["phase_entered_at"].replace("Z", "+00:00"))
    t2 = phase_entered + timedelta(days=variety["casing_days"])
    set_clock(t2.strftime("%Y-%m-%dT%H:%M:%SZ"))
    get_success_data(api_client.advance_room_cycle(room_cycle["id"], FARM))
    return get_success_data(api_client.get_room_cycle(room_cycle["id"], ANY))


def setup_fruiting_cycle(tonnage: float = TEST_DEFAULTS["BATCH_TONNAGE"],
                         allocated_tonnage: float = TEST_DEFAULTS["ALLOCATED_TONNAGE"],
                         room_capacity: float = TEST_DEFAULTS["ROOM_CAPACITY_TONNES"],
                         **variety_overrides):
    """The canonical farm chain: spawned batch + room cycle in FRUITING.

    The canonical clock trace places the cycle at 2026-05-03 and reaches
    FRUITING at 2026-05-08. Returns
    (variety, batch, room, room_cycle) with room_cycle FRUITING."""
    batch, variety = create_spawned_batch(tonnage=tonnage, **variety_overrides)
    room = create_room(capacity_tonnes=room_capacity)
    rc = create_scheduled_room_cycle(batch, room, allocated_tonnage=allocated_tonnage)
    rc = place_room_cycle(rc)
    rc = advance_cycle_to_fruiting(rc, variety)
    return variety, batch, room, rc


# ---------------------------------------------------------------------------
# Tier 4: flushes / pieces / packaged lots
# ---------------------------------------------------------------------------

def record_flush_on_cycle(room_cycle: dict, total_kg: float = 100.0) -> dict:
    resp = api_client.record_flush(room_cycle["id"], record_flush_payload(total_kg=total_kg), FARM)
    return get_success_data(resp)


def grade_flush(flush: dict, grade_a_kg: float = 60.0, grade_b_kg: float = 30.0,
                cull_kg: float = 10.0) -> dict:
    resp = api_client.grade_flush(
        flush["id"],
        grade_flush_payload(grade_a_kg=grade_a_kg, grade_b_kg=grade_b_kg, cull_kg=cull_kg),
        GRADING,
    )
    return get_success_data(resp)


def setup_fruiting_cycle_with_graded_flush(total_kg: float = 100.0,
                                           grade_a_kg: float = 60.0,
                                           grade_b_kg: float = 30.0,
                                           cull_kg: float = 10.0):
    """Fruiting cycle plus one GRADED flush. Returns
    (variety, batch, room, rc, flush)."""
    variety, batch, room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=total_kg)
    flush = grade_flush(flush, grade_a_kg=grade_a_kg, grade_b_kg=grade_b_kg, cull_kg=cull_kg)
    return variety, batch, room, rc, flush


def create_worker_and_log_piece(flush: dict, kg_picked: float = 40.0,
                                rate: int = TEST_DEFAULTS["WORKER_RATE_CENTS_PER_KG"],
                                worker: Optional[dict] = None):
    """Create a worker (if not given) and log a piece on the flush as that
    worker wearing the HarvestCrewLead hat. Returns (worker, piece)."""
    worker = worker or create_worker(piece_rate_cents_per_kg=rate)
    headers = make_harvest_crew_lead_headers(worker["id"])
    resp = api_client.log_piece(flush["id"], log_piece_payload(worker_id=worker["id"], kg_picked=kg_picked), headers)
    piece = get_success_data(resp)
    return worker, piece


def pack_flush_lot(flush: dict, grade: str = "A", units: int = 20,
                   kg_per_unit: float = 1.0) -> dict:
    resp = api_client.pack_flush(
        flush["id"],
        create_packaged_lot_payload(grade=grade, units=units, kg_per_unit=kg_per_unit),
        FARM,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: commitments / allocation / spent lots
# ---------------------------------------------------------------------------

def create_active_commitment_with_line(variety: dict, committed_kg: float = 500.0,
                                       week_start: str = TEST_DEFAULTS["LINE_WEEK_START"],
                                       week_end: str = TEST_DEFAULTS["LINE_WEEK_END"],
                                       min_grade: str = "B",
                                       buyer: Optional[dict] = None,
                                       reference: str = "PO-100"):
    """Buyer + ACTIVE commitment with one ACTIVE line.

    Returns (buyer, commitment, line)."""
    buyer = buyer or create_buyer()
    commitment = get_success_data(api_client.create_buyer_commitment(
        create_buyer_commitment_payload(buyer_id=buyer["id"], reference=reference), SALES,
    ))
    line = get_success_data(api_client.add_commitment_line(
        commitment["id"],
        create_commitment_line_payload(
            variety_id=variety["id"], committed_kg=committed_kg,
            week_start=week_start, week_end=week_end, min_grade=min_grade,
        ),
        SALES,
    ))
    get_success_data(api_client.activate_commitment(
        commitment["id"], {"expected_commitment_version": commitment["version"]}, SALES,
    ))
    commitment = get_success_data(api_client.get_buyer_commitment(commitment["id"], ANY))
    line = get_success_data(api_client.get_commitment_line(line["id"], ANY))
    return buyer, commitment, line


def get_first_spent_lot_for_cycle(room_cycle_id: str) -> dict:
    resp = api_client.list_spent_lots(ANY, params={"room_cycle_id": room_cycle_id})
    data = get_success_data(resp)
    lots = data if isinstance(data, list) else data.get("items", [])
    assert lots, f"Setup failed: expected at least one spent lot for cycle {room_cycle_id}"
    return lots[0]


def setup_turned_over_cycle_with_spent_lot(**kwargs):
    """Farm chain through end-cropping: cycle TURNAROUND + AVAILABLE spent lot.

    Returns (variety, batch, room, rc, spent_lot)."""
    variety, batch, room, rc = setup_fruiting_cycle(**kwargs)
    get_success_data(api_client.end_cropping_room_cycle(rc["id"], FARM))
    rc = get_success_data(api_client.get_room_cycle(rc["id"], ANY))
    spent_lot = get_first_spent_lot_for_cycle(rc["id"])
    return variety, batch, room, rc, spent_lot


def report_and_confirm_contamination(room: dict, room_cycle: Optional[dict] = None,
                                     severity: int = 4,
                                     pathogen: str = "TRICHODERMA",
                                     affected_zone_pct: float = 35.0) -> dict:
    payload = report_contamination_event_payload(
        room_id=room["id"], severity=severity, pathogen=pathogen,
        affected_zone_pct=affected_zone_pct,
    )
    if room_cycle is not None:
        payload["room_cycle_id"] = room_cycle["id"]
    event = get_success_data(api_client.report_contamination_event(payload, QUALITY))
    get_success_data(api_client.confirm_contamination_event(event["id"], QUALITY))
    return get_success_data(api_client.get_contamination_event(event["id"], ANY))
