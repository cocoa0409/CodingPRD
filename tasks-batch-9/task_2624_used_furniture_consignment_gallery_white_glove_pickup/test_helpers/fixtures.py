"""Composite setup helpers.

The harness restarts the server before every test, so each fixture builds its
whole world from an empty database. Every helper uses the lenient
`get_success_data()` so a broken preamble reports as a setup failure rather than
as a confusing assertion further down.

Ownership-gated calls are threaded with `make_consignor_headers()` /
`make_buyer_headers()` built from the row that was just created, because those
two roles are entity-backed.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    SCORES_GRADE_A,
    SCORES_GRADE_B,
    STD_ELECTION_WINDOW_DAYS,
    STD_SCHEDULE_STEPS,
    STD_UNSOLD_TRIGGER_DAY,
)
from .factories import (
    adjudicate_payload,
    agreement_payload,
    attach_item_payload,
    buyer_payload,
    clock_payload,
    complete_delivery_payload,
    complete_pickup_payload,
    consignor_payload,
    crew_payload,
    damage_claim_payload,
    delivery_order_payload,
    elect_disposition_payload,
    floor_zone_payload,
    inventory_flag_payload,
    item_payload,
    payout_payload,
    pickup_job_payload,
    place_payload,
    price_schedule_payload,
    price_schedule_step_payload,
    receive_payload,
    request_info_payload,
    resubmit_payload,
    sale_payload,
    screen_payload,
    shrinkage_audit_payload,
    truck_payload,
    write_off_payload,
)
from .test_users import (
    FLOOR_OPERATOR,
    GALLERY_MANAGER,
    INTAKE_APPRAISER,
    LOGISTICS_COORDINATOR,
    SYSTEM_OPERATOR,
    make_buyer_headers,
    make_consignor_headers,
)

# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def fetch_consignor(consignor_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_consignor(consignor_id, GALLERY_MANAGER))


def fetch_buyer(buyer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_buyer(buyer_id, GALLERY_MANAGER))


def fetch_agreement(agreement_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_agreement(agreement_id, GALLERY_MANAGER))


def fetch_price_schedule(schedule_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_price_schedule(schedule_id, GALLERY_MANAGER)
    )


def fetch_item(item_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_item(item_id, GALLERY_MANAGER))


def fetch_zone(zone_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_zone(zone_id, GALLERY_MANAGER))


def fetch_truck(truck_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_truck(truck_id, LOGISTICS_COORDINATOR))


def fetch_crew(crew_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_crew(crew_id, LOGISTICS_COORDINATOR))


def fetch_pickup_job(job_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_pickup_job(job_id, LOGISTICS_COORDINATOR)
    )


def fetch_sale(sale_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_sale(sale_id, GALLERY_MANAGER))


def fetch_delivery_order(order_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_delivery_order(order_id, LOGISTICS_COORDINATOR)
    )


def fetch_damage_claim(claim_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_damage_claim(claim_id, GALLERY_MANAGER))


def fetch_consignor_ledger(
    consignor_id: str, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    response = api_client.list_consignor_ledger_entries(
        consignor_id, GALLERY_MANAGER, params=params or {"limit": 100}
    )
    return get_success_data(response)


def fetch_item_ledger(
    item_id: str, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    response = api_client.list_item_ledger_entries(
        item_id, GALLERY_MANAGER, params=params or {"limit": 100}
    )
    return get_success_data(response)


def consignor_version(consignor_id: str) -> int:
    return fetch_consignor(consignor_id)["version"]


def item_version(item_id: str) -> int:
    return fetch_item(item_id)["version"]


def total_count(response: Dict[str, Any]) -> int:
    """Pagination total from an envelope the caller already knows succeeded."""
    return response.json()["meta"]["total_count"]


# ---------------------------------------------------------------------------
# Clock and epochs
# ---------------------------------------------------------------------------


def set_clock(current_utc: str) -> None:
    get_success_data(
        api_client.set_clock(clock_payload(current_utc), SYSTEM_OPERATOR)
    )


def run_markdown_epoch() -> None:
    get_success_data(api_client.run_markdown_epoch(SYSTEM_OPERATOR))


def run_escheatment_epoch() -> None:
    get_success_data(api_client.run_escheatment_epoch(SYSTEM_OPERATOR))


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# ---------------------------------------------------------------------------


def create_price_schedule(
    steps: Sequence[Sequence[Any]] = STD_SCHEDULE_STEPS,
    unsold_trigger_day: int = STD_UNSOLD_TRIGGER_DAY,
    election_window_days: int = STD_ELECTION_WINDOW_DAYS,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a schedule and hang `steps` off it in sequence order.

    `steps` is a sequence of (sequence, start_day_offset, markdown_pct,
    min_price_cents) tuples. Returns the schedule row re-read after the last
    step so `step_count` is current.
    """
    schedule = get_success_data(
        api_client.create_price_schedule(
            price_schedule_payload(
                unsold_trigger_day=unsold_trigger_day,
                election_window_days=election_window_days,
                **overrides,
            ),
            GALLERY_MANAGER,
        )
    )
    for sequence, start_day_offset, markdown_pct, min_price_cents in steps:
        get_success_data(
            api_client.create_price_schedule_step(
                price_schedule_step_payload(
                    schedule["id"],
                    sequence,
                    start_day_offset,
                    markdown_pct,
                    min_price_cents,
                ),
                GALLERY_MANAGER,
            )
        )
    return fetch_price_schedule(schedule["id"]) if steps else schedule


def create_consignor(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_consignor(consignor_payload(**overrides), GALLERY_MANAGER)
    )


def create_buyer(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_buyer(buyer_payload(**overrides), GALLERY_MANAGER)
    )


def create_agreement(
    consignor_id: str, price_schedule_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_agreement(
            agreement_payload(consignor_id, price_schedule_id, **overrides),
            GALLERY_MANAGER,
        )
    )


def create_active_agreement(
    consignor_id: str, price_schedule_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Create the agreement and activate it. Returns the ACTIVE row."""
    agreement = create_agreement(consignor_id, price_schedule_id, **overrides)
    return get_success_data(
        api_client.activate_agreement(agreement["id"], GALLERY_MANAGER)
    )


def create_truck(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_truck(truck_payload(**overrides), LOGISTICS_COORDINATOR)
    )


def create_crew(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_crew(crew_payload(**overrides), LOGISTICS_COORDINATOR)
    )


def create_zone(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_zone(floor_zone_payload(**overrides), FLOOR_OPERATOR)
    )


def create_item(agreement_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_item(
            item_payload(agreement_id, **overrides), INTAKE_APPRAISER
        )
    )


def screen_item(
    item_id: str,
    scores: Optional[Dict[str, float]] = None,
    decision: str = "ACCEPT",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.screen_item(
            item_id, screen_payload(decision=decision, scores=scores), INTAKE_APPRAISER
        )
    )


def receive_item(
    item_id: str, scores: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.receive_item(item_id, receive_payload(scores=scores), FLOOR_OPERATOR)
    )


def place_item(
    item_id: str, zone_id: str, tag_code: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.place_item(
            item_id, place_payload(zone_id, tag_code), FLOOR_OPERATOR
        )
    )


def flag_inventory(item_id: str, flag: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.inventory_flag(item_id, inventory_flag_payload(flag), FLOOR_OPERATOR)
    )


def write_off_item(item_id: str, expected_item_version: Optional[int] = None) -> Dict[str, Any]:
    version = (
        expected_item_version
        if expected_item_version is not None
        else item_version(item_id)
    )
    return get_success_data(
        api_client.write_off_item(item_id, write_off_payload(version), GALLERY_MANAGER)
    )


def release_item(item_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.release_item(item_id, FLOOR_OPERATOR))


def elect_disposition(
    item_id: str, election: str, consignor_id: Optional[str] = None
) -> Dict[str, Any]:
    """Elect as the owning consignor when one is given, else as the manager."""
    headers = (
        make_consignor_headers(consignor_id)
        if consignor_id is not None
        else GALLERY_MANAGER
    )
    return get_success_data(
        api_client.elect_disposition(
            item_id, elect_disposition_payload(election), headers
        )
    )


def request_payout(
    consignor_id: str, expected_consignor_version: Optional[int] = None
) -> Dict[str, Any]:
    """Disburse the balance and return the minted PAYOUT_DISBURSEMENT_DEBIT entry.

    PRD 3.9 places `withholding_cents`, `processing_fee_cents` and
    `net_payout_cents` on the minted ledger entry ("carrying `withholding_cents`,
    `processing_fee_cents` and `net_payout_cents` as reporting fields on that same
    entry"), and PRD 4 makes a consignor's ledger readable through
    `GET /consignors/{id}/ledger-entries`. The PRD nowhere pins which of the two
    rows the disbursement touches (the new entry, or the updated consignor) is
    echoed in `data`, so the entry is read back from the endpoint that PRD does
    declare rather than assumed to be the POST body.
    """
    version = (
        expected_consignor_version
        if expected_consignor_version is not None
        else consignor_version(consignor_id)
    )
    get_success_data(
        api_client.create_payout(consignor_id, payout_payload(version), GALLERY_MANAGER)
    )
    disbursements = [
        entry
        for entry in fetch_consignor_ledger(consignor_id)
        if entry["entry_type"] == "PAYOUT_DISBURSEMENT_DEBIT"
    ]
    assert disbursements, "The disbursement minted no PAYOUT_DISBURSEMENT_DEBIT entry"
    return disbursements[-1]


# ---------------------------------------------------------------------------
# Tier 2: paperwork hierarchy
# ---------------------------------------------------------------------------

DEFAULT_PICKUP_WINDOW_START = "2026-08-01T09:00:00Z"
DEFAULT_PICKUP_WINDOW_END = "2026-08-01T11:00:00Z"
DEFAULT_DELIVERY_WINDOW_START = "2026-08-01T13:00:00Z"
DEFAULT_DELIVERY_WINDOW_END = "2026-08-01T15:00:00Z"


def setup_consignor_with_active_agreement(
    schedule_steps: Sequence[Sequence[Any]] = STD_SCHEDULE_STEPS,
    term_days: int = 365,
    consignor_overrides: Optional[Dict[str, Any]] = None,
    schedule_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Standard schedule + one consignor + one ACTIVE agreement.

    Returns {"schedule", "consignor", "agreement"}.
    """
    schedule = create_price_schedule(steps=schedule_steps, **(schedule_overrides or {}))
    consignor = create_consignor(**(consignor_overrides or {}))
    agreement = create_active_agreement(
        consignor["id"], schedule["id"], term_days=term_days
    )
    return {"schedule": schedule, "consignor": consignor, "agreement": agreement}


# ---------------------------------------------------------------------------
# Tier 3: full merchandising lifecycle shortcuts
# ---------------------------------------------------------------------------


def schedule_pickup(
    consignor_id: str,
    truck_id: str,
    item_ids: Optional[Sequence[str]] = None,
    window_start: str = DEFAULT_PICKUP_WINDOW_START,
    window_end: str = DEFAULT_PICKUP_WINDOW_END,
    crew_size: int = 2,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_pickup_job(
            pickup_job_payload(
                consignor_id,
                truck_id,
                window_start,
                window_end,
                crew_size=crew_size,
                item_ids=list(item_ids) if item_ids is not None else None,
            ),
            LOGISTICS_COORDINATOR,
        )
    )


def attach_item_to_pickup(job_id: str, item_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.attach_pickup_item(
            job_id, attach_item_payload(item_id), LOGISTICS_COORDINATOR
        )
    )


def complete_pickup(
    job_id: str,
    actual_stair_flights: int = 0,
    actual_elevator_used: bool = False,
    actual_crew_size: int = 2,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.complete_pickup_job(
            job_id,
            complete_pickup_payload(
                actual_stair_flights, actual_elevator_used, actual_crew_size
            ),
            LOGISTICS_COORDINATOR,
        )
    )


def take_custody(
    consignor_id: str,
    item_ids: Sequence[str],
    truck: Optional[Dict[str, Any]] = None,
    window_start: str = DEFAULT_PICKUP_WINDOW_START,
    window_end: str = DEFAULT_PICKUP_WINDOW_END,
    crew_size: int = 2,
    actual_stair_flights: int = 0,
    actual_elevator_used: bool = False,
    actual_crew_size: int = 2,
) -> Dict[str, Any]:
    """Truck + pickup job over `item_ids` + completion, so the pieces are RECEIVED.

    Returns {"truck", "pickup_job"} with the job re-read after completion.
    """
    truck_row = truck if truck is not None else create_truck()
    job = schedule_pickup(
        consignor_id,
        truck_row["id"],
        item_ids,
        window_start=window_start,
        window_end=window_end,
        crew_size=crew_size,
    )
    completed = complete_pickup(
        job["id"],
        actual_stair_flights=actual_stair_flights,
        actual_elevator_used=actual_elevator_used,
        actual_crew_size=actual_crew_size,
    )
    return {"truck": truck_row, "pickup_job": completed}


def setup_screened_item(
    scores: Optional[Dict[str, float]] = None,
    decision: str = "ACCEPT",
    item_overrides: Optional[Dict[str, Any]] = None,
    **world_kwargs: Any,
) -> Dict[str, Any]:
    """Paperwork + one intaken, screened piece.

    Returns {"schedule", "consignor", "agreement", "item"}.
    """
    world = setup_consignor_with_active_agreement(**world_kwargs)
    item = create_item(world["agreement"]["id"], **(item_overrides or {}))
    world["item"] = screen_item(
        item["id"], scores=scores or SCORES_GRADE_B, decision=decision
    )
    return world


def setup_item_in_custody(
    screen_scores: Optional[Dict[str, float]] = None,
    item_overrides: Optional[Dict[str, Any]] = None,
    pickup_kwargs: Optional[Dict[str, Any]] = None,
    **world_kwargs: Any,
) -> Dict[str, Any]:
    """Screened piece carried in on a completed pickup job: RECEIVED / IN_CUSTODY."""
    world = setup_screened_item(
        scores=screen_scores, item_overrides=item_overrides, **world_kwargs
    )
    world.update(
        take_custody(
            world["consignor"]["id"],
            [world["item"]["id"]],
            **(pickup_kwargs or {}),
        )
    )
    world["item"] = fetch_item(world["item"]["id"])
    return world


def setup_item_awaiting_placement(
    screen_scores: Optional[Dict[str, float]] = None,
    receive_scores: Optional[Dict[str, float]] = None,
    item_overrides: Optional[Dict[str, Any]] = None,
    pickup_kwargs: Optional[Dict[str, Any]] = None,
    **world_kwargs: Any,
) -> Dict[str, Any]:
    """Received and inspected piece, priced and ready for the floor."""
    world = setup_item_in_custody(
        screen_scores=screen_scores,
        item_overrides=item_overrides,
        pickup_kwargs=pickup_kwargs,
        **world_kwargs,
    )
    world["item"] = receive_item(
        world["item"]["id"],
        scores=receive_scores if receive_scores is not None else screen_scores,
    )
    return world


def setup_item_on_floor(
    screen_scores: Optional[Dict[str, float]] = None,
    receive_scores: Optional[Dict[str, float]] = None,
    item_overrides: Optional[Dict[str, Any]] = None,
    zone_overrides: Optional[Dict[str, Any]] = None,
    tag_code: Optional[str] = None,
    pickup_kwargs: Optional[Dict[str, Any]] = None,
    **world_kwargs: Any,
) -> Dict[str, Any]:
    """A piece all the way onto a sales floor zone: ON_FLOOR / IN_CUSTODY.

    Returns {"schedule", "consignor", "agreement", "truck", "pickup_job",
    "zone", "item"}.
    """
    world = setup_item_awaiting_placement(
        screen_scores=screen_scores,
        receive_scores=receive_scores,
        item_overrides=item_overrides,
        pickup_kwargs=pickup_kwargs,
        **world_kwargs,
    )
    zone_kwargs = {"capacity_sqft": 200}
    zone_kwargs.update(zone_overrides or {})
    world["zone"] = create_zone(**zone_kwargs)
    world["item"] = place_item(
        world["item"]["id"], world["zone"]["id"], tag_code=tag_code
    )
    return world


def setup_zone_with_placed_items(
    item_specs: Sequence[Dict[str, Any]],
    screen_scores: Optional[Dict[str, float]] = None,
    zone_overrides: Optional[Dict[str, Any]] = None,
    pickup_kwargs: Optional[Dict[str, Any]] = None,
    **world_kwargs: Any,
) -> Dict[str, Any]:
    """Several pieces intaken together and all placed in one zone.

    `item_specs` is a sequence of dicts; each may carry item field overrides plus
    an optional "screen_scores" / "receive_scores" entry for that piece.
    Returns {"schedule", "consignor", "agreement", "truck", "pickup_job",
    "zone", "items"}.
    """
    world = setup_consignor_with_active_agreement(**world_kwargs)
    items: List[Dict[str, Any]] = []
    for spec in item_specs:
        overrides = {
            k: v
            for k, v in spec.items()
            if k not in ("screen_scores", "receive_scores")
        }
        item = create_item(world["agreement"]["id"], **overrides)
        screen_item(
            item["id"], scores=spec.get("screen_scores") or screen_scores or SCORES_GRADE_B
        )
        items.append(item)
    world.update(
        take_custody(
            world["consignor"]["id"],
            [item["id"] for item in items],
            **(pickup_kwargs or {}),
        )
    )
    zone_kwargs = {"capacity_sqft": 200}
    zone_kwargs.update(zone_overrides or {})
    world["zone"] = create_zone(**zone_kwargs)
    placed: List[Dict[str, Any]] = []
    for item, spec in zip(items, item_specs):
        receive_item(
            item["id"],
            scores=spec.get("receive_scores")
            or spec.get("screen_scores")
            or screen_scores
            or SCORES_GRADE_B,
        )
        placed.append(place_item(item["id"], world["zone"]["id"]))
    world["items"] = placed
    return world


# ---------------------------------------------------------------------------
# Tier 3 (continued): selling, delivering, claiming
# ---------------------------------------------------------------------------


def sell_item(item_id: str, buyer_id: str, sale_price_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_sale(
            sale_payload(item_id, buyer_id, sale_price_cents), GALLERY_MANAGER
        )
    )


def reverse_sale(sale_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.reverse_sale(sale_id, GALLERY_MANAGER))


def schedule_delivery(
    sale_id: str,
    crew_id: str,
    window_start: str = DEFAULT_DELIVERY_WINDOW_START,
    window_end: str = DEFAULT_DELIVERY_WINDOW_END,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_delivery_order(
            delivery_order_payload(sale_id, crew_id, window_start, window_end),
            LOGISTICS_COORDINATOR,
        )
    )


def complete_delivery(order_id: str, outcome: str = "DELIVERED") -> Dict[str, Any]:
    return get_success_data(
        api_client.complete_delivery_order(
            order_id, complete_delivery_payload(outcome), LOGISTICS_COORDINATOR
        )
    )


def setup_sold_item(
    sale_price_cents: int = 126_317,
    buyer_overrides: Optional[Dict[str, Any]] = None,
    **on_floor_kwargs: Any,
) -> Dict[str, Any]:
    """A placed piece sold to a fresh buyer.

    Returns the on-floor world plus {"buyer", "sale"}.
    """
    world = setup_item_on_floor(**on_floor_kwargs)
    world["buyer"] = create_buyer(**(buyer_overrides or {}))
    world["sale"] = sell_item(
        world["item"]["id"], world["buyer"]["id"], sale_price_cents
    )
    return world


def setup_scheduled_delivery(
    crew_overrides: Optional[Dict[str, Any]] = None,
    window_start: str = DEFAULT_DELIVERY_WINDOW_START,
    window_end: str = DEFAULT_DELIVERY_WINDOW_END,
    **sold_kwargs: Any,
) -> Dict[str, Any]:
    """Sold piece with a SCHEDULED white-glove delivery order.

    Returns the sold world plus {"crew", "delivery_order"}.
    """
    world = setup_sold_item(**sold_kwargs)
    world["crew"] = create_crew(**(crew_overrides or {}))
    world["delivery_order"] = schedule_delivery(
        world["sale"]["id"], world["crew"]["id"], window_start, window_end
    )
    return world


def setup_completed_delivery(
    outcome: str = "DELIVERED", **delivery_kwargs: Any
) -> Dict[str, Any]:
    """Delivery order carried through to DELIVERED or REFUSED."""
    world = setup_scheduled_delivery(**delivery_kwargs)
    world["delivery_order"] = complete_delivery(
        world["delivery_order"]["id"], outcome
    )
    world["sale"] = fetch_sale(world["sale"]["id"])
    world["item"] = fetch_item(world["item"]["id"])
    return world


def file_damage_claim(
    delivery_order_id: str, buyer_id: str, claim_amount_cents: int, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_damage_claim(
            damage_claim_payload(delivery_order_id, claim_amount_cents, **overrides),
            make_buyer_headers(buyer_id),
        )
    )


def request_claim_info(claim_id: str, note: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.request_claim_info(
            claim_id, request_info_payload(note), GALLERY_MANAGER
        )
    )


def resubmit_claim(
    claim_id: str,
    buyer_id: str,
    description: Optional[str] = None,
    withdraw: Optional[bool] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.resubmit_claim(
            claim_id,
            resubmit_payload(description, withdraw),
            make_buyer_headers(buyer_id),
        )
    )


def adjudicate_claim(
    claim_id: str, approve: bool, fault_party: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.adjudicate_claim(
            claim_id,
            adjudicate_payload(approve, fault_party),
            headers if headers is not None else GALLERY_MANAGER,
        )
    )


def setup_damage_claim(
    claim_amount_cents: int = 30_000,
    **delivery_kwargs: Any,
) -> Dict[str, Any]:
    """Delivered piece with one SUBMITTED damage claim against the order.

    Returns the delivered world plus {"claim"}.
    """
    world = setup_completed_delivery(outcome="DELIVERED", **delivery_kwargs)
    world["claim"] = file_damage_claim(
        world["delivery_order"]["id"], world["buyer"]["id"], claim_amount_cents
    )
    return world


# ---------------------------------------------------------------------------
# Tier 3 (continued): shrinkage audits
# ---------------------------------------------------------------------------


def submit_shrinkage_audit(
    zone_id: str, counted_item_ids: Sequence[str], headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_shrinkage_audit(
            shrinkage_audit_payload(zone_id, list(counted_item_ids)),
            headers if headers is not None else FLOOR_OPERATOR,
        )
    )


def approve_audit_write_off(
    audit_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.approve_write_off(
            audit_id, headers if headers is not None else GALLERY_MANAGER
        )
    )


# ---------------------------------------------------------------------------
# Tier 4: lots, markdown targeting, dormancy targeting
# ---------------------------------------------------------------------------


def setup_lot(
    parent_overrides: Optional[Dict[str, Any]] = None,
    component_specs: Sequence[Dict[str, Any]] = (),
    parent_scores: Optional[Dict[str, float]] = None,
    **world_kwargs: Any,
) -> Dict[str, Any]:
    """A lot parent with components, all screened.

    Each entry of `component_specs` carries item field overrides plus an optional
    "screen_scores". Returns {"schedule", "consignor", "agreement", "parent",
    "components"}.
    """
    world = setup_consignor_with_active_agreement(**world_kwargs)
    parent_kwargs = {"category": "DINING", "declared_value_cents": 70_000}
    parent_kwargs.update(parent_overrides or {})
    parent = create_item(world["agreement"]["id"], **parent_kwargs)
    components: List[Dict[str, Any]] = []
    for spec in component_specs:
        overrides = {k: v for k, v in spec.items() if k != "screen_scores"}
        component = create_item(
            world["agreement"]["id"], parent_lot_item_id=parent["id"], **overrides
        )
        components.append(component)
    for component, spec in zip(components, component_specs):
        screen_item(
            component["id"],
            scores=spec.get("screen_scores") or SCORES_GRADE_A,
        )
    world["parent"] = screen_item(
        parent["id"], scores=parent_scores or SCORES_GRADE_A
    )
    world["components"] = [fetch_item(c["id"]) for c in components]
    return world


def advance_to_markdown_step(instant: str) -> None:
    """Park the clock on `instant` and run one markdown epoch."""
    set_clock(instant)
    run_markdown_epoch()


def drive_consignor_dormant(instant: str) -> None:
    """Park the clock on `instant` and run one escheatment epoch."""
    set_clock(instant)
    run_escheatment_epoch()
