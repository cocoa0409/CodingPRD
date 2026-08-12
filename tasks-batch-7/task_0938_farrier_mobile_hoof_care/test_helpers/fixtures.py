"""Composite setup helpers.

Every helper builds its preconditions from scratch through declared endpoints —
the database is empty at the start of each test. Setup calls use the lenient
`get_success_data` validator so a broken precondition reads as a setup failure
rather than as a confusing assertion failure.

Each composite stops at exactly the state its name promises; tests that need a
later state call the next helper explicitly, so no fixture ever drives an entity
past the source state of the transition under test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BASE_RATE_CARD, TEST_DEFAULTS
from .factories import (
    appointment_payload,
    barn_payload,
    client_payload,
    farrier_payload,
    horse_payload,
    lameness_case_payload,
    prescription_payload,
    rate_card_payload,
    route_payload,
    route_stop_payload,
    service_line,
    service_lines_payload,
    shoe_sku_payload,
    stock_transfer_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_headers,
    make_farrier_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
VET = TEST_USERS["veterinarian_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1 — single-call primitives
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_barn(**overrides) -> dict:
    return get_success_data(api_client.create_barn(barn_payload(**overrides), ADMIN))


def create_client(barn_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_client(client_payload(barn_id, **overrides), ADMIN)
    )


def create_horse(client_id: str, barn_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_horse(horse_payload(client_id, barn_id, **overrides), ADMIN)
    )


def list_limb_states(horse_id: str) -> list:
    return get_success_data(api_client.list_limb_states(horse_id, ADMIN))


def limb_ids(horse_id: str) -> dict:
    """Map limb token to LimbState id for one horse."""
    return {row["limb"]: row["id"] for row in list_limb_states(horse_id)}


def create_farrier(**overrides) -> dict:
    return get_success_data(
        api_client.create_farrier(farrier_payload(**overrides), ADMIN)
    )


def create_sku(**overrides) -> dict:
    return get_success_data(
        api_client.create_shoe_sku(shoe_sku_payload(**overrides), ADMIN)
    )


def van_bucket(farrier_id: str, sku_id: str) -> dict:
    rows = get_success_data(
        api_client.list_inventory_buckets(
            ADMIN,
            params={
                "farrier_id": farrier_id,
                "sku_id": sku_id,
                "location_kind": "VAN",
            },
        )
    )
    assert rows, f"setup failed: no VAN bucket for farrier {farrier_id} / sku {sku_id}"
    return rows[0]


def shop_bucket(sku_id: str) -> dict:
    rows = get_success_data(
        api_client.list_inventory_buckets(
            ADMIN, params={"sku_id": sku_id, "location_kind": "SHOP"}
        )
    )
    assert rows, f"setup failed: no SHOP bucket for sku {sku_id}"
    return rows[0]


def adjust_bucket(bucket_id: str, delta_pairs: int) -> dict:
    return get_success_data(
        api_client.adjust_inventory_bucket(
            bucket_id, {"delta_pairs": delta_pairs}, ADMIN
        )
    )


def create_rate_card(**overrides) -> dict:
    return get_success_data(
        api_client.create_rate_card(rate_card_payload(**overrides), ADMIN)
    )


def activate_rate_card(rate_card_id: str) -> dict:
    return get_success_data(api_client.activate_rate_card(rate_card_id, ADMIN))


def create_active_rate_card(**overrides) -> dict:
    card = create_rate_card(**overrides)
    return activate_rate_card(card["id"])


def create_transfer(sku_id, from_bucket_id, to_bucket_id, quantity_pairs=5) -> dict:
    return get_success_data(
        api_client.create_stock_transfer(
            stock_transfer_payload(
                sku_id, from_bucket_id, to_bucket_id, quantity_pairs
            ),
            ADMIN,
        )
    )


def create_route(farrier_id: str, route_date: str = None) -> dict:
    return get_success_data(
        api_client.create_route(route_payload(farrier_id, route_date), DISPATCHER)
    )


def add_stop(route_id, barn_id, sequence_index=1, planned_start_minute=None) -> dict:
    return get_success_data(
        api_client.create_route_stop(
            route_id,
            route_stop_payload(barn_id, sequence_index, planned_start_minute),
            DISPATCHER,
        )
    )


def create_appointment(horse_id, scheduled_date, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_appointment(
            appointment_payload(horse_id, scheduled_date, **overrides),
            headers or DISPATCHER,
        )
    )


def read_appointment(appointment_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_appointment(appointment_id, headers or ADMIN)
    )


def read_route(route_id, headers=None) -> dict:
    return get_success_data(api_client.get_route(route_id, headers or ADMIN))


def read_stop(stop_id, headers=None) -> dict:
    return get_success_data(api_client.get_route_stop(stop_id, headers or ADMIN))


def read_horse(horse_id, headers=None) -> dict:
    return get_success_data(api_client.get_horse(horse_id, headers or ADMIN))


def read_client(client_id, headers=None) -> dict:
    return get_success_data(api_client.get_client(client_id, headers or ADMIN))


def read_farrier(farrier_id) -> dict:
    return get_success_data(api_client.get_farrier(farrier_id, ADMIN))


def read_bucket(bucket_id) -> dict:
    return get_success_data(api_client.get_inventory_bucket(bucket_id, ADMIN))


def read_transfer(transfer_id) -> dict:
    return get_success_data(api_client.get_stock_transfer(transfer_id, ADMIN))


def read_case(case_id) -> dict:
    return get_success_data(api_client.get_lameness_case(case_id, ADMIN))


def read_prescription(prescription_id) -> dict:
    return get_success_data(api_client.get_prescription(prescription_id, ADMIN))


def read_reminder(reminder_id) -> dict:
    return get_success_data(api_client.get_reminder(reminder_id, ADMIN))


def read_service_line(line_id) -> dict:
    return get_success_data(api_client.get_service_line(line_id, ADMIN))


def read_rate_card(rate_card_id) -> dict:
    return get_success_data(api_client.get_rate_card(rate_card_id, ADMIN))


def route_version(route_id: str) -> int:
    return read_route(route_id)["version"]


def appointment_version(appointment_id: str) -> int:
    return read_appointment(appointment_id)["version"]


def reservations_for(appointment_id: str) -> list:
    return get_success_data(
        api_client.list_shoe_reservations(
            ADMIN, params={"appointment_id": appointment_id}
        )
    )


def service_lines_for(appointment_id: str) -> list:
    return get_success_data(
        api_client.list_service_lines(ADMIN, params={"appointment_id": appointment_id})
    )


def reminders_for(appointment_id: str) -> list:
    return get_success_data(
        api_client.list_reminders(DISPATCHER, params={"appointment_id": appointment_id})
    )


def invoices_for(appointment_id: str) -> list:
    return get_success_data(
        api_client.list_invoices(BILLING, params={"appointment_id": appointment_id})
    )


def sole_invoice(appointment_id: str) -> dict:
    rows = invoices_for(appointment_id)
    assert len(rows) == 1, (
        f"expected exactly 1 invoice for appointment {appointment_id}, got {len(rows)}"
    )
    return rows[0]


def limb_state_rows(horse_id: str) -> dict:
    return {row["limb"]: row for row in list_limb_states(horse_id)}


# ---------------------------------------------------------------------------
# Tier 2 — line construction and multi-call actions
# ---------------------------------------------------------------------------


def lines_for_limbs(limbs, limb_id_map, service_type, sku_id=None, **extra) -> list:
    """Build a `lines` array of one service type across the named limbs."""
    built = []
    for limb in limbs:
        payload = service_line(limb_id_map[limb], service_type, **extra)
        if sku_id is not None:
            payload["sku_id"] = sku_id
        built.append(payload)
    return built


def add_lines(appointment_id, lines, headers=None, expected_version=None) -> list:
    """Add service lines using the appointment's current version."""
    version = (
        appointment_version(appointment_id)
        if expected_version is None
        else expected_version
    )
    return get_success_data(
        api_client.add_service_lines(
            appointment_id,
            service_lines_payload(lines, version),
            headers or DISPATCHER,
        )
    )


def attach(stop_id, appointment_id, route_id, headers=None) -> dict:
    """Attach with a freshly read route version."""
    return get_success_data(
        api_client.attach_appointment(
            stop_id,
            {
                "appointment_id": appointment_id,
                "expected_route_version": route_version(route_id),
            },
            headers or DISPATCHER,
        )
    )


def attach_response(stop_id, appointment_id, route_id, headers=None):
    """The raw response of an attach, for tests asserting the refusal."""
    return api_client.attach_appointment(
        stop_id,
        {
            "appointment_id": appointment_id,
            "expected_route_version": route_version(route_id),
        },
        headers or DISPATCHER,
    )


def detach(stop_id, appointment_id, headers=None) -> dict:
    return get_success_data(
        api_client.detach_appointment(
            stop_id, appointment_id, headers or DISPATCHER
        )
    )


def plan_route(route_id) -> dict:
    return get_success_data(api_client.plan_route(route_id, DISPATCHER))


def dispatch_route(route_id) -> dict:
    return get_success_data(api_client.dispatch_route(route_id, DISPATCHER))


def cancel_route(route_id) -> dict:
    return get_success_data(api_client.cancel_route(route_id, DISPATCHER))


def arrive_stop(stop_id, farrier_id) -> dict:
    return get_success_data(
        api_client.arrive_route_stop(stop_id, make_farrier_headers(farrier_id))
    )


def complete_stop(stop_id, farrier_id) -> dict:
    return get_success_data(
        api_client.complete_route_stop(stop_id, make_farrier_headers(farrier_id))
    )


def start_visit(appointment_id, farrier_id) -> dict:
    return get_success_data(
        api_client.start_appointment(appointment_id, make_farrier_headers(farrier_id))
    )


def complete_visit(appointment_id, performed_line_ids, farrier_id) -> dict:
    return get_success_data(
        api_client.complete_appointment(
            appointment_id,
            {"performed_service_line_ids": list(performed_line_ids)},
            make_farrier_headers(farrier_id),
        )
    )


def record_no_show(appointment_id, farrier_id) -> dict:
    return get_success_data(
        api_client.record_no_show(appointment_id, make_farrier_headers(farrier_id))
    )


def cancel_visit(appointment_id, client_id=None) -> dict:
    headers = make_client_headers(client_id) if client_id else DISPATCHER
    return get_success_data(api_client.cancel_appointment(appointment_id, headers))


def report_lameness(horse_id, reported_on, severity) -> dict:
    return get_success_data(
        api_client.create_lameness_case(
            lameness_case_payload(horse_id, reported_on, severity), VET
        )
    )


def draft_prescription(
    case_id, issued_on, expires_on, limb_scope=None, prescribed_cycle_weeks=3
) -> dict:
    return get_success_data(
        api_client.create_prescription(
            prescription_payload(
                case_id, issued_on, expires_on, limb_scope, prescribed_cycle_weeks
            ),
            VET,
        )
    )


def activate_prescription(prescription_id, case_id) -> dict:
    case = read_case(case_id)
    return get_success_data(
        api_client.activate_prescription(
            prescription_id,
            {"expected_lameness_case_version": case["version"]},
            VET,
        )
    )


def resolve_case(case_id) -> dict:
    return get_success_data(api_client.resolve_lameness_case(case_id, VET))


def post_deposit(client_id, amount_cents) -> dict:
    return get_success_data(
        api_client.post_deposit(client_id, {"amount_cents": amount_cents}, BILLING)
    )


# ---------------------------------------------------------------------------
# Tier 3 — the reference world (no route, no visit)
# ---------------------------------------------------------------------------

ALL_LIMBS = ("LF", "RF", "LH", "RH")


def setup_reference(
    clock=TEST_DEFAULTS["CLOCK"],
    barn=None,
    client=None,
    horse=None,
    farrier=None,
    with_sku=True,
    sku=None,
    van_pairs=10,
    with_rate_card=True,
    rate_card=None,
):
    """Barn + client + horse (+ SKU, farrier, van stock, ACTIVE rate card).

    The SKU is created before the farrier so that the van bucket is the one the
    PRD says farrier creation mints for each existing SKU.
    Leaves every entity in its initial state: no route, no appointment.
    """
    world = {}
    if clock is not None:
        set_clock(clock)
    world["barn"] = create_barn(**(barn or {}))
    world["client"] = create_client(world["barn"]["id"], **(client or {}))
    world["horse"] = create_horse(
        world["client"]["id"], world["barn"]["id"], **(horse or {})
    )
    world["limbs"] = limb_ids(world["horse"]["id"])
    if with_sku:
        world["sku"] = create_sku(**(sku or {}))
    world["farrier"] = create_farrier(**(farrier or {}))
    if with_sku:
        world["shop"] = shop_bucket(world["sku"]["id"])
        world["van"] = van_bucket(world["farrier"]["id"], world["sku"]["id"])
        if van_pairs:
            world["van"] = adjust_bucket(world["van"]["id"], van_pairs)
    if with_rate_card:
        world["rate_card"] = create_active_rate_card(**(rate_card or {}))
    return world


def add_horse(world, name="Dusty", **overrides):
    """A second (or third) horse for the same client at the same barn."""
    extra = dict(overrides)
    extra.setdefault("name", name)
    horse = create_horse(world["client"]["id"], world["barn"]["id"], **extra)
    return horse, limb_ids(horse["id"])


# ---------------------------------------------------------------------------
# Tier 4 — routes and visits
# ---------------------------------------------------------------------------


def setup_route_with_stop(
    world,
    route_date=TEST_DEFAULTS["ROUTE_DATE"],
    planned_start_minute=None,
    barn_id=None,
    farrier_id=None,
):
    """A DRAFT route carrying exactly one PENDING stop. Nothing is planned."""
    world["route"] = create_route(farrier_id or world["farrier"]["id"], route_date)
    world["stop"] = add_stop(
        world["route"]["id"],
        barn_id or world["barn"]["id"],
        1,
        planned_start_minute,
    )
    return world


def setup_unrouted_visit(
    world,
    limbs=ALL_LIMBS,
    service_type="TRIM",
    use_sku=False,
    scheduled_date=TEST_DEFAULTS["ROUTE_DATE"],
    horse=None,
    limb_map=None,
    appointment_overrides=None,
    line_overrides=None,
):
    """An UNROUTED appointment carrying its service lines. It is not attached."""
    the_horse = horse or world["horse"]
    the_limbs = limb_map or world["limbs"]
    appointment = create_appointment(
        the_horse["id"], scheduled_date, **(appointment_overrides or {})
    )
    lines = []
    if limbs:
        lines = add_lines(
            appointment["id"],
            lines_for_limbs(
                limbs,
                the_limbs,
                service_type,
                sku_id=world["sku"]["id"] if use_sku else None,
                **(line_overrides or {}),
            ),
        )
        appointment = read_appointment(appointment["id"])
    world["appointment"] = appointment
    world["lines"] = lines
    return appointment, lines


def setup_scheduled_visit(world, **kwargs):
    """UNROUTED visit attached to the stop, so the appointment is SCHEDULED.

    The route is left DRAFT — callers that need PLANNED or DISPATCHED must say so.
    """
    appointment, lines = setup_unrouted_visit(world, **kwargs)
    attach(world["stop"]["id"], appointment["id"], world["route"]["id"])
    world["appointment"] = read_appointment(appointment["id"])
    return world["appointment"], lines


def dispatch_and_arrive(world):
    """Move the route DRAFT -> PLANNED -> DISPATCHED and the stop to ARRIVED."""
    plan_route(world["route"]["id"])
    dispatch_route(world["route"]["id"])
    arrive_stop(world["stop"]["id"], world["farrier"]["id"])
    world["stop"] = read_stop(world["stop"]["id"])
    return world


def setup_in_progress_visit(world, **kwargs):
    """A SCHEDULED visit taken to IN_PROGRESS at an ARRIVED stop."""
    appointment, lines = setup_scheduled_visit(world, **kwargs)
    dispatch_and_arrive(world)
    start_visit(appointment["id"], world["farrier"]["id"])
    world["appointment"] = read_appointment(appointment["id"])
    return world["appointment"], lines


def setup_completed_visit(world, **kwargs):
    """A visit worked through to COMPLETED, performing every planned line."""
    appointment, lines = setup_in_progress_visit(world, **kwargs)
    completed = complete_visit(
        appointment["id"], [line["id"] for line in lines], world["farrier"]["id"]
    )
    world["appointment"] = completed
    return completed, lines


def successor_of(horse_id, exclude_ids=()):
    """The UNROUTED appointments of one horse, minus the ones already known."""
    rows = get_success_data(
        api_client.list_appointments(
            ADMIN, params={"horse_id": horse_id, "status": "UNROUTED"}
        )
    )
    return [row for row in rows if row["id"] not in set(exclude_ids)]


def reminder_with_offset(appointment_id, offset_days):
    """Pick a reminder by its declared offset rather than by list position."""
    for row in reminders_for(appointment_id):
        if row["offset_days"] == offset_days:
            return row
    raise AssertionError(
        f"no reminder with offset_days {offset_days} on appointment {appointment_id}"
    )

