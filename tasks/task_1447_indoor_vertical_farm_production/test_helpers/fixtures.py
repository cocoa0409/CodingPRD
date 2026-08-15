"""Composite setup helpers (multi-step PRD workflows).

Every fixture builds preconditions from scratch via PRD endpoints only; the
harness restarts the server before every test, so nothing carries over.
Setup calls use get_success_data() so failures surface as clear setup errors.

Standard timeline used by the pack-ready chain (21-day recipe):
  seed 2026-08-03T06:00Z  ->  projected harvest 2026-08-24T06:00Z
  sanitation cycle PASSED 2026-08-22T03:30Z (51h before pack — within 72h)
  mark-harvest-ready 2026-08-22T06:00Z (exactly projected - 48h)
  harvest 2026-08-24T06:30Z; safety release; pack same UTC date.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    SEED_CLOCK, SANITATION_CYCLE_START, SANITATION_CYCLE_END,
    SANITATION_PASS_CLOCK, HARVEST_READY_CLOCK, HARVEST_CLOCK,
    SHIP_DATE, SHIP_WINDOW_START, SHIP_WINDOW_END,
    HARVESTER_USER_ID, QA_USER_ID, SANITATION_USER_1,
)
from .factories import (
    create_crop_payload, create_recipe_payload, create_water_loop_payload,
    create_rack_payload, create_batch_payload, create_sanitation_cycle_payload,
    create_contract_payload, create_shipment_payload, create_worker_payload,
    create_labor_shift_payload, create_assignment_payload,
)
from .test_users import (
    TEST_USERS, make_grower_headers, make_quality_assurance_headers,
    make_sanitation_lead_headers, make_worker_headers,
)

FM = TEST_USERS["farm_manager_headers"]
GR = TEST_USERS["grower_headers"]
SL = TEST_USERS["sanitation_lead_headers"]
QA = TEST_USERS["quality_assurance_headers"]
CM = TEST_USERS["contracts_manager_headers"]
LP = TEST_USERS["labor_planner_headers"]


def _data(resp, step: str):
    body = get_success_data(resp)
    assert isinstance(body, dict), f"Setup failed at {step}: expected object, got {body!r}"
    return body


def _list_data(resp, step: str) -> list:
    body = get_success_data(resp)
    assert isinstance(body, list), f"Setup failed at {step}: expected array, got {body!r}"
    return body


# ── Tier 0: clock ────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, FM)
    _data(resp, f"set_clock({to_iso8601})")


# ── Tier 1: catalog ──────────────────────────────────────────────────────────

def create_crop(**overrides) -> dict:
    return _data(api_client.create_crop(create_crop_payload(**overrides), FM), "create_crop")


def create_crop_with_active_recipe(crop_overrides=None, recipe_overrides=None) -> tuple:
    """Crop + DRAFT recipe + activate (OCC on the crop's version). Returns (crop, recipe)."""
    crop = create_crop(**(crop_overrides or {}))
    recipe = _data(
        api_client.create_recipe(create_recipe_payload(crop["id"], **(recipe_overrides or {})), GR),
        "create_recipe",
    )
    recipe = _data(
        api_client.activate_recipe(recipe["id"], {"expected_crop_version": crop["version"]}, GR),
        "activate_recipe",
    )
    crop = _data(api_client.get_crop(crop["id"], FM), "get_crop after activate")
    return crop, recipe


# ── Tier 2: physical layout ──────────────────────────────────────────────────

def create_loop(**overrides) -> dict:
    return _data(api_client.create_water_loop(create_water_loop_payload(**overrides), FM), "create_water_loop")


def create_rack_with_towers(loop_id: str, tower_count: int = 4, **overrides) -> tuple:
    """Rack creation auto-creates tower_count towers (tower_index 1..N). Returns (rack, towers)."""
    rack = _data(
        api_client.create_rack(create_rack_payload(loop_id, tower_count=tower_count, **overrides), FM),
        "create_rack",
    )
    towers = _list_data(api_client.list_rack_towers(rack["id"], FM), "list_rack_towers")
    return rack, towers


def create_loop_rack(loop_code: str = None, rack_code: str = None, tower_count: int = 4, zone: str = "Z1") -> tuple:
    """Loop + rack + towers. Returns (loop, rack, towers)."""
    loop_kw = {"loop_code": loop_code} if loop_code else {}
    rack_kw = {"rack_code": rack_code} if rack_code else {}
    loop = create_loop(**loop_kw)
    rack, towers = create_rack_with_towers(loop["id"], tower_count=tower_count, zone=zone, **rack_kw)
    return loop, rack, towers


# ── Tier 3: batch lifecycle progression ─────────────────────────────────────

def create_batch(crop_id: str, tower_ids: list, planned_seed_at: str = None) -> dict:
    overrides = {"planned_seed_at": planned_seed_at} if planned_seed_at else {}
    return _data(
        api_client.create_batch(create_batch_payload(crop_id, tower_ids, **overrides), GR),
        "create_batch",
    )


def seed_batch(batch_id: str) -> dict:
    return _data(api_client.seed_batch(batch_id, GR), "seed_batch")


def germination_check(batch_id: str, germination_rate_pct: float = 96.0) -> dict:
    return _data(
        api_client.germination_check_batch(batch_id, {"germination_rate_pct": germination_rate_pct}, GR),
        "germination_check",
    )


def create_growing_batch(crop_id: str, tower_ids: list, germination_rate_pct: float = 96.0,
                         seed_clock: str = SEED_CLOCK, planned_seed_at: str = None) -> dict:
    """PLANNED -> SEEDED -> GROWING at the given seed clock."""
    set_clock(seed_clock)
    batch = create_batch(crop_id, tower_ids, planned_seed_at=planned_seed_at)
    seed_batch(batch["id"])
    return germination_check(batch["id"], germination_rate_pct)


def mark_harvest_ready(batch_id: str, at_clock: str = HARVEST_READY_CLOCK) -> dict:
    set_clock(at_clock)
    return _data(api_client.mark_harvest_ready_batch(batch_id, GR), "mark_harvest_ready")


def harvest_batch(batch_id: str, grade_a_lb: float, grade_b_lb: float = 0.0, cull_lb: float = 0.0,
                  at_clock: str = HARVEST_CLOCK, harvester: str = HARVESTER_USER_ID) -> dict:
    set_clock(at_clock)
    return _data(
        api_client.harvest_batch(
            batch_id,
            {"grade_a_lb": grade_a_lb, "grade_b_lb": grade_b_lb, "cull_lb": cull_lb},
            make_grower_headers(harvester),
        ),
        "harvest_batch",
    )


def safety_release(batch_id: str, decision: str = "RELEASED", lab_ref: str = "LAB-1",
                   qa_user: str = QA_USER_ID) -> dict:
    return _data(
        api_client.safety_release_batch(
            batch_id, {"decision": decision, "lab_ref": lab_ref},
            make_quality_assurance_headers(qa_user),
        ),
        "safety_release",
    )


def pack_batch(batch_id: str, packed_lb: float) -> dict:
    return _data(api_client.pack_batch(batch_id, {"packed_lb": packed_lb}, GR), "pack_batch")


# ── Tier 3b: sanitation cycles ──────────────────────────────────────────────

def schedule_cycle(loop_id: str, start: str, end: str, parent_cycle_id: str = None) -> dict:
    overrides = {"parent_cycle_id": parent_cycle_id} if parent_cycle_id else {}
    return _data(
        api_client.create_sanitation_cycle(
            create_sanitation_cycle_payload(
                loop_id, scheduled_start_at=start, scheduled_end_at=end, **overrides,
            ),
            SL,
        ),
        "schedule_cycle",
    )


def start_cycle(cycle_id: str, at_clock: str) -> dict:
    set_clock(at_clock)
    return _data(api_client.start_sanitation_cycle(cycle_id, SL), "start_cycle")


def record_cycle_result(cycle_id: str, result: str, coliform_cfu: int, at_clock: str,
                        recorded_by: str = SANITATION_USER_1) -> dict:
    set_clock(at_clock)
    return _data(
        api_client.record_sanitation_result(
            cycle_id, {"result": result, "coliform_cfu": coliform_cfu},
            make_sanitation_lead_headers(recorded_by),
        ),
        "record_cycle_result",
    )


def run_passed_cycle(loop_id: str, start: str = SANITATION_CYCLE_START, end: str = SANITATION_CYCLE_END,
                     pass_clock: str = SANITATION_PASS_CLOCK, recorded_by: str = SANITATION_USER_1,
                     parent_cycle_id: str = None) -> dict:
    """Schedule -> start -> record PASSED. Returns the PASSED cycle."""
    cycle = schedule_cycle(loop_id, start, end, parent_cycle_id=parent_cycle_id)
    start_cycle(cycle["id"], start)
    return record_cycle_result(cycle["id"], "PASSED", 0, pass_clock, recorded_by=recorded_by)


# ── Tier 4: full production chain ───────────────────────────────────────────

def setup_packed_batch(packed_lb: float = 100.0, grade_a_lb: float = None, grade_b_lb: float = 0.0,
                       cull_lb: float = 0.0, tower_count: int = 4, germination_rate_pct: float = 96.0,
                       crop_overrides=None, recipe_overrides=None,
                       seed_clock: str = SEED_CLOCK, ready_clock: str = HARVEST_READY_CLOCK,
                       harvest_clock: str = HARVEST_CLOCK, harvester: str = HARVESTER_USER_ID,
                       qa_user: str = QA_USER_ID, loop_code: str = None, rack_code: str = None,
                       pass_clock: str = SANITATION_PASS_CLOCK) -> dict:
    """Full chain: crop+ACTIVE recipe, loop+rack+towers, batch GROWING, a PASSED
    sanitation cycle on the loop, then mark-ready -> harvest -> RELEASED -> PACKED.
    Returns a dict with crop, recipe, loop, rack, towers, cycle, batch (PACKED).
    """
    crop, recipe = create_crop_with_active_recipe(crop_overrides, recipe_overrides)
    loop, rack, towers = create_loop_rack(loop_code=loop_code, rack_code=rack_code, tower_count=tower_count)
    tower_ids = [t["id"] for t in towers]
    # Schedule the pass window first (while the clock is early), then grow the batch.
    cycle = schedule_cycle(loop["id"], SANITATION_CYCLE_START, SANITATION_CYCLE_END)
    batch = create_growing_batch(crop["id"], tower_ids, germination_rate_pct=germination_rate_pct,
                                 seed_clock=seed_clock)
    start_cycle(cycle["id"], SANITATION_CYCLE_START)
    record_cycle_result(cycle["id"], "PASSED", 0, pass_clock, recorded_by=SANITATION_USER_1)
    mark_harvest_ready(batch["id"], at_clock=ready_clock)
    ga = grade_a_lb if grade_a_lb is not None else packed_lb
    batch = harvest_batch(batch["id"], ga, grade_b_lb, cull_lb, at_clock=harvest_clock, harvester=harvester)
    batch = safety_release(batch["id"], qa_user=qa_user)
    batch = pack_batch(batch["id"], packed_lb)
    return {
        "crop": crop, "recipe": recipe, "loop": loop, "rack": rack, "towers": towers,
        "cycle": cycle, "batch": batch,
    }


# ── Tier 4b: contracts and shipments ────────────────────────────────────────

def create_contract(crop_id: str, **overrides) -> dict:
    return _data(api_client.create_contract(create_contract_payload(crop_id, **overrides), CM), "create_contract")


def fresh_contract_version(contract_id: str) -> int:
    return _data(api_client.get_contract(contract_id, CM), "get_contract")["version"]


def create_shipment(contract_id: str, lines: list, ship_date: str = SHIP_DATE,
                    window_start: str = SHIP_WINDOW_START, window_end: str = SHIP_WINDOW_END) -> dict:
    """Create a shipment, threading the contract's CURRENT version (OCC)."""
    version = fresh_contract_version(contract_id)
    return _data(
        api_client.create_shipment(
            create_shipment_payload(
                contract_id, version, lines,
                ship_date=ship_date, window_start_at=window_start, window_end_at=window_end,
            ),
            CM,
        ),
        "create_shipment",
    )


def get_shipment_lines(shipment_id: str) -> list:
    return _list_data(api_client.list_shipment_lines(shipment_id, CM), "list_shipment_lines")


def confirm_pack(shipment_id: str, packed_by_line: dict = None) -> tuple:
    """confirm-pack every line; default packed == reserved. Returns (shipment, lines)."""
    lines = get_shipment_lines(shipment_id)
    packed = packed_by_line or {ln["id"]: ln["reserved_lb"] for ln in lines}
    shipment = _data(
        api_client.confirm_pack_shipment(
            shipment_id,
            {"lines": [{"line_id": ln["id"], "packed_lb": packed[ln["id"]]} for ln in lines]},
            CM,
        ),
        "confirm_pack",
    )
    return shipment, get_shipment_lines(shipment_id)


def setup_reserved_shipment(batch: dict, crop_id: str, reserve_lb: float = 10.0,
                            contract_overrides=None, ship_date: str = SHIP_DATE,
                            window_start: str = SHIP_WINDOW_START,
                            window_end: str = SHIP_WINDOW_END) -> dict:
    """Contract + one RESERVED shipment with a single line on the PACKED batch."""
    contract = create_contract(crop_id, **(contract_overrides or {}))
    shipment = create_shipment(
        contract["id"], [{"batch_id": batch["id"], "reserved_lb": reserve_lb}],
        ship_date=ship_date, window_start=window_start, window_end=window_end,
    )
    return {"contract": contract, "shipment": shipment, "lines": get_shipment_lines(shipment["id"])}


def setup_packed_shipment(batch: dict, crop_id: str, reserve_lb: float = 10.0, **kwargs) -> dict:
    """Reserved shipment, then confirm-pack at exactly the reserved pounds."""
    ctx = setup_reserved_shipment(batch, crop_id, reserve_lb, **kwargs)
    shipment, lines = confirm_pack(ctx["shipment"]["id"])
    ctx["shipment"] = shipment
    ctx["lines"] = lines
    return ctx


# ── Tier 4c: failure / replant chain ────────────────────────────────────────

def setup_failure_report(crop_id: str, tower_ids: list, cause_category: str = "PATHOGEN",
                         lost_lb_estimate: float = 12.5, germination_rate_pct: float = 96.0,
                         seed_clock: str = SEED_CLOCK, fail_clock: str = None,
                         triage: bool = True) -> tuple:
    """GROWING batch -> fail -> FailureReport (optionally TRIAGED). Returns (batch, failure)."""
    batch = create_growing_batch(crop_id, tower_ids, germination_rate_pct=germination_rate_pct,
                                 seed_clock=seed_clock)
    if fail_clock:
        set_clock(fail_clock)
    _data(api_client.fail_batch(batch["id"], {"cause_category": cause_category}, GR), "fail_batch")
    failures = _list_data(api_client.list_batch_failure_reports(batch["id"], GR), "list failure reports")
    failure = failures[0]
    if triage:
        failure = _data(
            api_client.triage_failure_report(
                failure["id"],
                {"cause_category": cause_category, "lost_lb_estimate": lost_lb_estimate},
                GR,
            ),
            "triage_failure",
        )
    return batch, failure


def setup_queued_replant(crop_id: str, tower_ids: list, **kwargs) -> tuple:
    """Failure triaged + replant requested. Returns (batch, failure, replant)."""
    batch, failure = setup_failure_report(crop_id, tower_ids, **kwargs)
    replant = _data(api_client.request_replant(failure["id"], GR), "request_replant")
    return batch, failure, replant


# ── Tier 5: labor chain ─────────────────────────────────────────────────────

def create_worker(certifications=("PACK_CREW",), **overrides) -> dict:
    overrides.setdefault("certifications", list(certifications))
    return _data(api_client.create_worker(create_worker_payload(**overrides), LP), "create_worker")


def create_published_shift(shift_date: str = "2026-08-05", role_type: str = "PACK_CREW",
                           start_at: str = "2026-08-05T07:00:00Z", end_at: str = "2026-08-05T15:00:00Z",
                           headcount_required: int = 1, planned_hourly_rate_cents: int = 2200) -> dict:
    shift = _data(
        api_client.create_labor_shift(
            create_labor_shift_payload(
                shift_date=shift_date, role_type=role_type, start_at=start_at, end_at=end_at,
                headcount_required=headcount_required,
                planned_hourly_rate_cents=planned_hourly_rate_cents,
            ),
            LP,
        ),
        "create_labor_shift",
    )
    return _data(api_client.publish_labor_shift(shift["id"], LP), "publish_labor_shift")


def assign_worker(shift_id: str, worker_id: str):
    """Create an assignment, threading the shift's CURRENT version (OCC).

    Returns (response, shift_version_used) so callers can assert either the
    success payload or the rejection."""
    version = _data(api_client.get_labor_shift(shift_id, LP), "get_labor_shift")["version"]
    resp = api_client.create_shift_assignment(
        shift_id, create_assignment_payload(worker_id, version), LP,
    )
    return resp, version


def assign_worker_ok(shift_id: str, worker_id: str) -> dict:
    resp, _ = assign_worker(shift_id, worker_id)
    return _data(resp, "create_shift_assignment")


def confirm_assignment(shift_id: str, assignment_id: str, worker_id: str) -> dict:
    """Worker confirms their own assignment (entity-backed ownership)."""
    return _data(
        api_client.confirm_shift_assignment(shift_id, assignment_id, make_worker_headers(worker_id)),
        "confirm_shift_assignment",
    )
