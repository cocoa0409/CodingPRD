"""Wine dinner events: plan, price, confirm, settle, void, cancel (PRD 3.9)."""
from datetime import timedelta

from flask import Blueprint

from core import (
    API_PREFIX,
    EVENT_TURNOVER_BUFFER_MINUTES,
    authorize,
    check_venue_scope,
    fail,
    get_event,
    get_list_entry,
    get_list_version,
    get_venue,
    new_record,
    paginate,
    parse_iso,
    q,
    respond_list,
    respond_object,
    serialize,
    sort_by,
    store,
    touch,
    validate_body,
    get_body,
)
from calc import (
    LIVE_VERSION_STATES,
    candidate_lots,
    draw_from_lots,
    event_bottles_needed,
    event_pour_yield,
    event_pricing,
    lot_available,
)
from cascade import (
    apply_ledger_totals,
    recompute_bin_of_lot,
    refresh_availability,
    write_depletion,
)

bp = Blueprint("events", __name__)

EVENT_READ_ROLES = ["BeverageDirector", "VenueSommelier", "Controller", "ComplianceOfficer"]
OCCUPYING_STATES = ("PLANNED", "PRICED", "CONFIRMED", "SETTLED", "SETTLEMENT_VOIDED")
CANCELLABLE_STATES = ("PLANNED", "PRICED", "CONFIRMED", "SETTLEMENT_VOIDED")

EVENT_SPEC = [
    {"name": "venue_id", "type": "string", "required": True},
    {"name": "list_version_id", "type": "string", "required": True},
    {"name": "name", "type": "string", "required": True, "min_len": 1, "max_len": 120},
    {"name": "starts_at", "type": "datetime", "required": True},
    {"name": "ends_at", "type": "datetime", "required": True},
    {"name": "seat_count", "type": "int", "required": True, "min": 1, "max": 400},
    {"name": "pour_plan", "type": "array", "required": True},
]


def _plan_lines(event_or_body, version_id):
    """Resolve every pour-plan line to (line, entry, wine) in array order."""
    lines = []
    for line in event_or_body["pour_plan"]:
        entry = store.list_entries.get(line["list_entry_id"])
        wine = store.wines.get(entry["wine_id"]) if entry else None
        lines.append((line, entry, wine))
    return lines


def _check_plan_membership(pour_plan, version_id):
    for line in pour_plan:
        entry = store.list_entries.get(line["list_entry_id"])
        if entry is None or entry["list_version_id"] != version_id:
            fail("ERR_POUR_PLAN_ENTRY_MISMATCH", "A pour-plan line names a foreign listing.")
        if int(line["pours_per_seat"]) < 1:
            fail("ERR_POUR_PLAN_ENTRY_MISMATCH", "A pour-plan line pours less than one per seat.")


@bp.post(API_PREFIX + "/wine-dinner-events")
def create_event():
    user_id, role = authorize("VenueSommelier")
    body = get_body()
    check_venue_scope(role, user_id, body.get("venue_id"))
    if body.get("venue_id") is not None:
        get_venue(body["venue_id"])
    version = None
    if body.get("list_version_id") is not None:
        version = get_list_version(body["list_version_id"])
    plan = body.get("pour_plan")
    if isinstance(plan, list):
        for line in plan:
            if isinstance(line, dict) and isinstance(line.get("list_entry_id"), str):
                get_list_entry(line["list_entry_id"])
    validate_body(body, EVENT_SPEC)

    plan = body["pour_plan"]
    if len(plan) < 1 or len(plan) > 12:
        fail("ERR_VALUE_OUT_OF_RANGE", "A pour plan carries between 1 and 12 lines.")
    for line in plan:
        if not isinstance(line, dict):
            fail("ERR_INVALID_REQUEST", "Each pour-plan line is an object.")
        if not isinstance(line.get("list_entry_id"), str):
            fail("ERR_INVALID_REQUEST", "Each pour-plan line names a list_entry_id.")
        pps = line.get("pours_per_seat")
        if not isinstance(pps, int) or isinstance(pps, bool):
            fail("ERR_INVALID_REQUEST", "Each pour-plan line carries an integer pours_per_seat.")
        if pps > 6:
            fail("ERR_VALUE_OUT_OF_RANGE", "pours_per_seat may not exceed 6.")

    starts_at = parse_iso(body["starts_at"])
    ends_at = parse_iso(body["ends_at"])
    if not starts_at < ends_at:
        fail("ERR_INVALID_EVENT_WINDOW", "An event window must open strictly before it closes.")

    if version["state"] not in LIVE_VERSION_STATES:
        fail("ERR_LIST_VERSION_NOT_PUBLISHED", "The pour plan must be drawn from a live version.")

    buffer_delta = timedelta(minutes=EVENT_TURNOVER_BUFFER_MINUTES)
    for other in store.wine_dinner_events.values():
        if other["venue_id"] != body["venue_id"] or other["state"] not in OCCUPYING_STATES:
            continue
        if starts_at < other["ends_at"] + buffer_delta and other["starts_at"] < ends_at + buffer_delta:
            fail("ERR_EVENT_WINDOW_CONFLICT", "That window collides with another dinner.")

    _check_plan_membership(plan, body["list_version_id"])

    rec = new_record(
        {
            "venue_id": body["venue_id"],
            "list_version_id": body["list_version_id"],
            "name": body["name"],
            "starts_at": starts_at,
            "ends_at": ends_at,
            "seat_count": body["seat_count"],
            "pour_plan": [
                {"list_entry_id": l["list_entry_id"], "pours_per_seat": l["pours_per_seat"]}
                for l in plan
            ],
            "state": "PLANNED",
            "beverage_cost_per_seat_cents": None,
            "provisional_gross_cents": None,
            "tier_discount_pct": None,
            "final_ticket_price_cents": None,
            "projected_pour_cost_pct": None,
            "pinned_version_no": version["version_no"],
            "pinned_version_stale": False,
            "settled_cogs_cents": None,
            "settled_revenue_cents": None,
        }
    )
    store.wine_dinner_events[rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@bp.get(API_PREFIX + "/wine-dinner-events/<event_id>")
def read_event(event_id):
    authorize(EVENT_READ_ROLES)
    return respond_object(serialize(get_event(event_id)))


@bp.get(API_PREFIX + "/wine-dinner-events")
def list_events():
    authorize(EVENT_READ_ROLES)
    rows = list(store.wine_dinner_events.values())
    for field in ("venue_id", "list_version_id", "state"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, meta = paginate(sort_by(rows, "starts_at"))
    return respond_list([serialize(r) for r in page], meta)


@bp.post(API_PREFIX + "/wine-dinner-events/<event_id>/price")
def price_event(event_id):
    user_id, role = authorize("VenueSommelier")
    event = get_event(event_id)
    check_venue_scope(role, user_id, event["venue_id"])
    if event["state"] not in ("PLANNED", "PRICED"):
        fail("ERR_EVENT_INVALID_STATE", "Only a planned or priced event may be priced.")
    _check_plan_membership(event["pour_plan"], event["list_version_id"])

    venue = store.venues.get(event["venue_id"])
    figures = event_pricing(event, venue, _plan_lines(event, event["list_version_id"]))
    event.update(figures)
    event["state"] = "PRICED"
    touch(event)
    return respond_object(serialize(event))


@bp.post(API_PREFIX + "/wine-dinner-events/<event_id>/confirm")
def confirm_event(event_id):
    authorize("BeverageDirector")
    event = get_event(event_id)
    if event["state"] != "PRICED" or event["final_ticket_price_cents"] is None:
        fail("ERR_EVENT_INVALID_STATE", "Only a priced event carrying a ticket price may be confirmed.")
    version = store.list_versions.get(event["list_version_id"])
    if version is None or version["state"] not in LIVE_VERSION_STATES:
        fail("ERR_LIST_VERSION_NOT_PUBLISHED", "The pinned list version is no longer live.")
    venue = store.venues.get(event["venue_id"])
    if venue["program_posture"] == "FROZEN":
        fail("ERR_VENUE_PROGRAM_FROZEN", "This venue's beverage program is frozen.")
    event["state"] = "CONFIRMED"
    event["pinned_version_no"] = version["version_no"]
    event["pinned_version_stale"] = False
    touch(event)
    return respond_object(serialize(event))


@bp.post(API_PREFIX + "/wine-dinner-events/<event_id>/settle")
def settle_event(event_id):
    authorize("Controller")
    event = get_event(event_id)
    if event["state"] != "CONFIRMED":
        fail("ERR_EVENT_INVALID_STATE", "Only a confirmed event may be settled.")
    version = store.list_versions.get(event["list_version_id"])
    if (
        event["pinned_version_stale"]
        or version is None
        or version["state"] not in LIVE_VERSION_STATES
    ):
        fail("ERR_PINNED_LIST_VERSION_STALE", "The pinned list version is no longer settleable.")

    venue = store.venues.get(event["venue_id"])
    seat_count = int(event["seat_count"])

    # Plan the whole draw against a working availability map first: nothing is
    # mutated until every line is known to be satisfiable.
    availability = {}
    for lot in store.inventory_lots.values():
        if lot["venue_id"] == event["venue_id"] and lot["state"] == "ON_HAND":
            availability[lot["id"]] = lot_available(lot)

    planned = []
    for line, entry, wine in _plan_lines(event, event["list_version_id"]):
        pour_yield = event_pour_yield(wine)
        needed = event_bottles_needed(seat_count, line["pours_per_seat"], pour_yield)
        lots = candidate_lots(event["venue_id"], wine["id"], availability)
        if sum(availability.get(lot["id"], 0) for lot in lots) < needed:
            fail("ERR_INSUFFICIENT_BOTTLES", "The cellar cannot cover this pour plan.")
        _total, draws = draw_from_lots(venue, lots, needed, availability)
        for lot, take, cogs in draws:
            availability[lot["id"]] = availability.get(lot["id"], 0) - take
        planned.append((entry, wine, draws))

    written = []
    settled_cogs = 0
    settled_revenue = int(event["final_ticket_price_cents"]) * seat_count
    for entry, wine, draws in planned:
        for lot, take, cogs in draws:
            revenue = settled_revenue if not written else 0
            written.append(
                write_depletion(
                    event["venue_id"], wine["id"], lot["id"], "EVENT", take, 0, cogs, revenue,
                    list_entry_id=entry["id"], event_id=event["id"],
                )
            )
            settled_cogs += cogs
            lot["bottles_on_hand"] = int(lot["bottles_on_hand"]) - take
            depleted = int(lot["bottles_on_hand"]) <= 0
            if depleted:
                lot["state"] = "DEPLETED"
            touch(lot)
            recompute_bin_of_lot(lot)
            if depleted:
                refresh_availability(
                    lot["venue_id"], lot["wine_id"], live_only=True, direction="deplete"
                )

    event["state"] = "SETTLED"
    event["settled_cogs_cents"] = settled_cogs
    event["settled_revenue_cents"] = settled_revenue
    touch(event)
    apply_ledger_totals(venue, written)
    return respond_object(serialize(event))


NOTE_SPEC = [{"name": "note", "type": "string", "required": True, "min_len": 1, "max_len": 500}]
OPTIONAL_NOTE_SPEC = [{"name": "note", "type": "string", "min_len": 1, "max_len": 500}]


@bp.post(API_PREFIX + "/wine-dinner-events/<event_id>/void-settlement")
def void_settlement(event_id):
    authorize("Controller")
    event = get_event(event_id)
    body = get_body()
    validate_body(body, NOTE_SPEC)
    if event["state"] != "SETTLED":
        fail("ERR_EVENT_INVALID_STATE", "Only a settled event may have its settlement voided.")

    venue = store.venues.get(event["venue_id"])
    originals = sorted(
        [
            e
            for e in store.depletion_entries.values()
            if e["event_id"] == event["id"] and e["reason"] == "EVENT"
        ],
        key=lambda e: (e["created_at"], e["_seq"]),
    )
    written = []
    for original in originals:
        written.append(
            write_depletion(
                original["venue_id"], original["wine_id"], original["lot_id"], "REVERSAL",
                -int(original["bottles"]), -int(original["pours"]),
                -int(original["cogs_cents"]), -int(original["revenue_cents"]),
                list_entry_id=original["list_entry_id"], event_id=event["id"],
            )
        )
        lot = store.inventory_lots.get(original["lot_id"])
        if lot is None:
            continue
        lot["bottles_on_hand"] = int(lot["bottles_on_hand"]) + int(original["bottles"])
        if lot["state"] == "DEPLETED":
            lot["state"] = "ON_HAND"
        touch(lot)
        recompute_bin_of_lot(lot)
        refresh_availability(
            lot["venue_id"], lot["wine_id"], live_only=True, direction="restock"
        )

    event["state"] = "SETTLEMENT_VOIDED"
    event["settled_cogs_cents"] = None
    event["settled_revenue_cents"] = None
    touch(event)
    apply_ledger_totals(venue, written)
    return respond_object(serialize(event))


@bp.post(API_PREFIX + "/wine-dinner-events/<event_id>/cancel")
def cancel_event(event_id):
    user_id, role = authorize("VenueSommelier", "BeverageDirector")
    event = get_event(event_id)
    check_venue_scope(role, user_id, event["venue_id"])
    body = get_body()
    validate_body(body, OPTIONAL_NOTE_SPEC)
    if event["state"] not in CANCELLABLE_STATES:
        fail("ERR_EVENT_INVALID_STATE", "This event can no longer be cancelled.")
    if event["state"] in ("CONFIRMED", "SETTLEMENT_VOIDED"):
        event["pinned_version_no"] = None
    event["state"] = "CANCELLED"
    touch(event)
    return respond_object(serialize(event))
