"""Composite setup helpers.

Every function here performs real API calls through the client and returns the
server's own view of the created rows, so a test never assumes state that the
implementation did not actually produce. Setup calls use the lenient
`get_success_data` so that a setup failure is reported as a setup failure.

The canonical world these helpers build:

    logical clock          2026-08-01T00:00:00Z
    P1  "AUS-101"          ZONE_A, TWO_BR, 2 bath / 3 beds,
                           local_utc_offset_minutes -300,
                           min_clean_minutes 120, min_skill_level 2
    sl1 "LIN-SHEET-Q"      LINEN, 260 cents, par 6, seeded 6
    sl2 "LIN-TOWEL-B"      LINEN, 180 cents, par 8, seeded 8
    Cleaner C              home ZONE_A, skill 4, max_daily 3, quality 92.00
    OUT-1                  [2026-08-05T21:00Z, 2026-08-08T16:00Z)
    IN-1                   [2026-08-08T21:00Z, 2026-08-11T16:00Z)
    T1                     window 16:00Z-20:30Z on 2026-08-08
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .constants import INITIAL_CLOCK
from .factories import (
    assign_turnover_payload,
    create_booking_payload,
    create_cleaner_payload,
    create_property_payload,
    create_quality_audit_payload,
    create_supply_line_payload,
    create_turnover_payload,
    restock_entry,
    review_task_payload,
    submit_task_payload,
)
from .test_users import (
    COORDINATOR_ASSIGN_USER_ID,
    TEST_USERS,
    make_cleaner_headers,
)

# Canonical instants of the shared world.
CHECKOUT_INSTANT = "2026-08-08T16:00:00Z"
WINDOW_START = "2026-08-08T16:00:00Z"
WINDOW_END = "2026-08-08T20:30:00Z"
ON_TIME_FINISH = "2026-08-08T20:00:00Z"

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["coordinator_reviewer_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]


# ─── Primitive seeds ──────────────────────────────────────────────────────

def reset_clock(api, when: str = INITIAL_CLOCK) -> None:
    """Pin the server's logical UTC instant."""
    get_success_data(api.set_clock(when, ADMIN))


def seed_property(api, **overrides) -> Dict[str, Any]:
    """Register the canonical TWO_BR unit P1 (required_minutes 198)."""
    fields: Dict[str, Any] = {
        "bedroom_count": 2,
        "bathroom_count": 2,
        "bed_count": 3,
        "local_utc_offset_minutes": -300,
        "min_clean_minutes": 120,
        "min_skill_level": 2,
    }
    fields.update(overrides)
    return get_success_data(api.create_property(create_property_payload(**fields), ADMIN))


def seed_supply_line(api, property_id: str, **overrides) -> Dict[str, Any]:
    """Add one stock line; `initial_on_hand_qty` appends the SEED movement."""
    payload = create_supply_line_payload(**overrides)
    return get_success_data(api.create_supply_line(property_id, payload, COORDINATOR))


def seed_linen_pair(api, property_id: str) -> List[Dict[str, Any]]:
    """The two ACTIVE LINEN lines whose par_qty sum (14) drives provisional pay."""
    sl1 = seed_supply_line(
        api, property_id, sku="LIN-SHEET-Q", name="Queen Sheet Set",
        category="LINEN", unit_cost_cents=260, par_qty=6, unit="SET",
        initial_on_hand_qty=6)
    sl2 = seed_supply_line(
        api, property_id, sku="LIN-TOWEL-B", name="Bath Towel",
        category="LINEN", unit_cost_cents=180, par_qty=8, unit="EACH",
        initial_on_hand_qty=8)
    return [sl1, sl2]


def seed_four_supply_lines(api, property_id: str) -> List[Dict[str, Any]]:
    """Two LINEN lines plus a CONSUMABLE and a WELCOME line seeded at 1 unit."""
    lines = seed_linen_pair(api, property_id)
    lines.append(seed_supply_line(
        api, property_id, sku="CON-COFFEE", name="Coffee Pods",
        category="CONSUMABLE", unit_cost_cents=340, par_qty=4, unit="BOX",
        initial_on_hand_qty=4))
    lines.append(seed_supply_line(
        api, property_id, sku="WEL-WINE", name="Welcome Wine",
        category="WELCOME", unit_cost_cents=900, par_qty=1, unit="BOTTLE",
        initial_on_hand_qty=1))
    return lines


def seed_cleaner(api, **overrides) -> Dict[str, Any]:
    """Onboard the canonical Cleaner C (ZONE_A, skill 4, quality 92.00)."""
    fields: Dict[str, Any] = {
        "max_daily_turnovers": 3,
        "initial_quality_score": 92.00,
    }
    fields.update(overrides)
    return get_success_data(api.create_cleaner(create_cleaner_payload(**fields), ADMIN))


def seed_booking(api, property_id: str, **overrides) -> Dict[str, Any]:
    """Import one reservation."""
    payload = create_booking_payload(property_id, **overrides)
    return get_success_data(api.create_booking(payload, COORDINATOR))


def seed_stay_pair(api, property_id: str):
    """The departing OUT-1 and the arriving IN-1 that bracket the turn."""
    b_out = seed_booking(
        api, property_id, external_ref="OUT-1", guest_name="Guest Out",
        checkin_at="2026-08-05T21:00:00Z", checkout_at="2026-08-08T16:00:00Z")
    b_in = seed_booking(
        api, property_id, external_ref="IN-1", guest_name="Guest In",
        checkin_at="2026-08-08T21:00:00Z", checkout_at="2026-08-11T16:00:00Z")
    return b_out, b_in


def seed_turnover(api, outgoing_booking_id: str,
                  incoming_booking_id: Optional[str] = None,
                  **overrides) -> Dict[str, Any]:
    """Open a turnover; omit the arriving stay for a vacant gap."""
    payload = create_turnover_payload(
        outgoing_booking_id, incoming_booking_id, **overrides)
    return get_success_data(api.create_turnover(payload, COORDINATOR))


# ─── World builders ───────────────────────────────────────────────────────

def build_world(api, supply: Optional[str] = "pair") -> Dict[str, Any]:
    """Clock, P1, optional stock lines, Cleaner C, OUT-1/IN-1 and T1.

    `supply` selects the stock lines: "pair" for the two LINEN lines,
    "four" to add a CONSUMABLE and a WELCOME line, None for no stock at all.
    The returned turnover sits in PENDING_ASSIGNMENT at version 1.
    """
    reset_clock(api)
    p1 = seed_property(api)
    if supply == "pair":
        lines = seed_linen_pair(api, p1["id"])
    elif supply == "four":
        lines = seed_four_supply_lines(api, p1["id"])
    else:
        lines = []
    cc = seed_cleaner(api)
    b_out, b_in = seed_stay_pair(api, p1["id"])
    t1 = seed_turnover(api, b_out["id"], b_in["id"])
    return {
        "p1": p1,
        "supply_lines": lines,
        "cc": cc,
        "b_out": b_out,
        "b_in": b_in,
        "t1": t1,
        "cleaner_headers": make_cleaner_headers(cc["id"]),
        "a1": None,
        "tasks": [],
    }


def offer_turnover(api, world: Dict[str, Any], cleaner_id: Optional[str] = None,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Create the offer at the turnover's current version. Records a1."""
    turnover = get_success_data(
        api.get_turnover(world["t1"]["id"], COORDINATOR))
    payload = assign_turnover_payload(
        turnover["version"], cleaner_id or world["cc"]["id"])
    a1 = get_success_data(
        api.assign_turnover(turnover["id"], payload, headers or COORDINATOR))
    world["a1"] = a1
    world["assigned_by_user_id"] = COORDINATOR_ASSIGN_USER_ID
    return a1


def accept_offer(api, world: Dict[str, Any]) -> Dict[str, Any]:
    """Accept the outstanding offer, minting the PROVISIONAL pay line."""
    a1 = get_success_data(
        api.accept_assignment(world["a1"]["id"], {}, world["cleaner_headers"]))
    world["a1"] = a1
    return a1


def start_clean(api, world: Dict[str, Any],
                at: str = CHECKOUT_INSTANT) -> List[Dict[str, Any]]:
    """Advance the clock, record the departure and begin the clean.

    Returns the generated checklist tasks in sequence_no order and stores them
    on the world under "tasks".
    """
    reset_clock(api, at)
    get_success_data(api.checkout_booking(world["b_out"]["id"], {}, COORDINATOR))
    get_success_data(
        api.start_turnover(world["t1"]["id"], {}, world["cleaner_headers"]))
    tasks = get_success_data(
        api.list_turnover_checklist_tasks(world["t1"]["id"], COORDINATOR))
    world["tasks"] = tasks
    return tasks


def default_restock_entries(world: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One unit consumed from each LINEN line — 280 + 194 = 474 cents."""
    return [restock_entry(line["id"], 1)
            for line in world["supply_lines"] if line["category"] == "LINEN"]


def submit_all_tasks(api, world: Dict[str, Any],
                     restock_entries: Optional[List[Dict[str, Any]]] = None
                     ) -> List[Dict[str, Any]]:
    """Submit every generated task with photo evidence where required.

    The RESTOCK row carries the consumed quantities; a task whose category is
    not RESTOCK must not carry any.
    """
    entries = (default_restock_entries(world) if restock_entries is None
               else restock_entries)
    submitted = []
    for task in world["tasks"]:
        payload = submit_task_payload(
            photo_uri=(f"https://cdn.example.com/{task['task_code'].lower()}.jpg"
                       if task["requires_photo"] else None),
            note=f"{task['task_code']} done",
            restock_entries=entries if task["category"] == "RESTOCK" else None,
        )
        submitted.append(get_success_data(
            api.submit_checklist_task(task["id"], payload, world["cleaner_headers"])))
    world["tasks"] = submitted
    return submitted


def review_all_tasks(api, world: Dict[str, Any], action: str = "APPROVE",
                     headers: Optional[Dict[str, str]] = None
                     ) -> List[Dict[str, Any]]:
    """Review every submitted task with one action."""
    reviewed = []
    for task in world["tasks"]:
        payload = review_task_payload(
            action, reject_reason="evidence insufficient" if action != "APPROVE" else None)
        reviewed.append(get_success_data(
            api.review_checklist_task(task["id"], payload, headers or REVIEWER)))
    world["tasks"] = reviewed
    return reviewed


def complete_clean(api, world: Dict[str, Any],
                   at: Optional[str] = ON_TIME_FINISH) -> Dict[str, Any]:
    """Close the clean out, switching the pay line PROVISIONAL to FINAL."""
    if at is not None:
        reset_clock(api, at)
    t1 = get_success_data(
        api.complete_turnover(world["t1"]["id"], {}, world["cleaner_headers"]))
    world["t1"] = t1
    return t1


def sample_audit(api, world: Dict[str, Any], score: int,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Sample the completed turnover as an independent auditor."""
    payload = create_quality_audit_payload(world["t1"]["id"], score)
    audit = get_success_data(
        api.create_quality_audit(payload, headers or AUDITOR))
    world["audit"] = audit
    return audit


# ─── One-shot worlds at each stage ────────────────────────────────────────

def world_pending(api, supply: Optional[str] = "pair") -> Dict[str, Any]:
    """T1 in PENDING_ASSIGNMENT, version 1, no offer yet."""
    return build_world(api, supply)


def world_offered(api, supply: Optional[str] = "pair") -> Dict[str, Any]:
    """T1 carries one OFFERED assignment; the turnover is at version 2."""
    world = build_world(api, supply)
    offer_turnover(api, world)
    return world


def world_scheduled(api, supply: Optional[str] = "pair") -> Dict[str, Any]:
    """The offer is ACCEPTED, T1 is SCHEDULED and a PROVISIONAL pay line exists."""
    world = world_offered(api, supply)
    accept_offer(api, world)
    return world


def world_in_progress(api, supply: Optional[str] = "pair") -> Dict[str, Any]:
    """The guest has departed and the clean is running with its checklist."""
    world = world_scheduled(api, supply)
    start_clean(api, world)
    return world


def world_awaiting_verification(api, supply: Optional[str] = "pair") -> Dict[str, Any]:
    """Every checklist row is SUBMITTED and the turn awaits review."""
    world = world_in_progress(api, supply)
    submit_all_tasks(api, world)
    return world


def world_all_verified(api, supply: Optional[str] = "pair") -> Dict[str, Any]:
    """Every checklist row is VERIFIED; the stock ledger has booked the restock."""
    world = world_awaiting_verification(api, supply)
    review_all_tasks(api, world)
    return world


def world_completed(api, supply: Optional[str] = "pair") -> Dict[str, Any]:
    """T1 is COMPLETED on time with a FINAL pay line."""
    world = world_all_verified(api, supply)
    complete_clean(api, world)
    return world


def world_audited(api, score: int, supply: Optional[str] = "pair") -> Dict[str, Any]:
    """A COMPLETED turn carrying one SAMPLED audit at the given score."""
    world = world_completed(api, supply)
    sample_audit(api, world, score)
    return world


# ─── Read-back helpers ────────────────────────────────────────────────────

def read_turnover(api, world: Dict[str, Any],
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_turnover(world["t1"]["id"], headers or COORDINATOR))


def read_cleaner(api, world: Dict[str, Any],
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_cleaner(world["cc"]["id"], headers or ADMIN))


def read_supply_line(api, supply_line_id: str,
                     headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_supply_line(supply_line_id, headers or COORDINATOR))


def read_pay_lines(api, cleaner_id: str,
                   headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    body = get_success_data(
        api.list_pay_lines(headers or COORDINATOR, {"cleaner_id": cleaner_id}))
    return body if isinstance(body, list) else []


def read_movements(api, params: Dict[str, Any],
                   headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    body = get_success_data(api.list_stock_movements(headers or COORDINATOR, params))
    return body if isinstance(body, list) else []


def tasks_by_code(tasks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Index a checklist by task_code for readable test bodies."""
    return {task["task_code"]: task for task in tasks}
