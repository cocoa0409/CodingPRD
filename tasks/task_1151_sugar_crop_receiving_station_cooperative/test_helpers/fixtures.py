"""Composite setup helpers for multi-step test prerequisites.

All helpers build state purely through PRD-declared endpoints and use the
lenient get_success_data() validator so setup failures surface as clear
"Setup failed" errors. Every test runs against a freshly restarted server
with an empty database, so each helper builds its preconditions from scratch.

Identity threading: booking creation and other ownership-gated calls always
use make_member_headers(member["id"]) — never the shared MEMBER constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_BASE_PRICE_CENTS_PER_TON,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
    QT_ALICE,
    QT_BOB,
    SLOT_AM_END,
    SLOT_AM_START,
    SLOT_PM_END,
    SLOT_PM_START,
    WEIGH_CLOCK_AM,
    WEIGH_CLOCK_PM,
)
from .factories import (
    accept_payload,
    complete_reclaim_payload,
    create_booking_payload,
    create_campaign_payload,
    create_installment_payload,
    create_loss_event_payload,
    create_member_payload,
    create_pile_payload,
    create_sample_payload,
    create_station_payload,
    create_ticket_payload,
    generate_settlements_payload,
    open_accrual_payload,
    close_pool_payload,
    record_result_payload,
    set_clock_payload,
    weigh_payload,
)
from .test_users import TEST_USERS, make_member_headers, make_quality_tech_headers

ADMIN = TEST_USERS["admin_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
OPERATOR = TEST_USERS["station_operator_headers"]
ACCOUNTANT = TEST_USERS["pool_accountant_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and simple state progression
# ---------------------------------------------------------------------------

def create_campaign(name="C-1", window_start=DEFAULT_WINDOW_START,
                    window_end=DEFAULT_WINDOW_END,
                    base_price_cents_per_ton=DEFAULT_BASE_PRICE_CENTS_PER_TON) -> dict:
    """Create a campaign (starts OPEN; its payment pool is auto-created)."""
    res = api_client.create_campaign(
        create_campaign_payload(
            name=name, window_start=window_start, window_end=window_end,
            base_price_cents_per_ton=base_price_cents_per_ton),
        ADMIN)
    return get_success_data(res)


def get_campaign_pool(campaign_id: str) -> dict:
    """Return the campaign's single auto-created payment pool."""
    res = api_client.list_campaign_pools(campaign_id, ACCOUNTANT)
    pools = get_success_data(res)
    assert len(pools) == 1, f"Setup failed: expected exactly one pool, got {len(pools)}"
    return pools[0]


def create_member(name="M1", member_code="M-1001", haul_distance_miles=22.5) -> dict:
    res = api_client.create_member(
        create_member_payload(name=name, member_code=member_code,
                              haul_distance_miles=haul_distance_miles),
        ADMIN)
    return get_success_data(res)


def suspend_member(member_id: str) -> dict:
    return get_success_data(api_client.suspend_member(member_id, ADMIN))


def create_station(name="ST", booking_capacity_tons=1000) -> dict:
    res = api_client.create_station(
        create_station_payload(name=name, booking_capacity_tons=booking_capacity_tons),
        ADMIN)
    return get_success_data(res)


def create_pile(station_id: str, capacity_tons=200) -> dict:
    res = api_client.create_pile(create_pile_payload(station_id, capacity_tons=capacity_tons),
                                 OPERATOR)
    return get_success_data(res)


def set_logical_clock(to_iso8601: str):
    get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def create_requested_booking(campaign_id: str, station_id: str, member_id: str,
                             slot_start=SLOT_AM_START, slot_end=SLOT_AM_END,
                             estimated_tons=20) -> dict:
    """Create a booking as its owning member (REQUESTED)."""
    res = api_client.create_booking(
        create_booking_payload(campaign_id, station_id,
                               slot_start=slot_start, slot_end=slot_end,
                               estimated_tons=estimated_tons),
        make_member_headers(member_id))
    return get_success_data(res)


def confirm_booking(booking_id: str) -> dict:
    return get_success_data(api_client.confirm_booking(booking_id, SCHEDULER))


def create_confirmed_booking(campaign_id: str, station_id: str, member_id: str,
                             slot_start=SLOT_AM_START, slot_end=SLOT_AM_END,
                             estimated_tons=20) -> dict:
    booking = create_requested_booking(campaign_id, station_id, member_id,
                                       slot_start=slot_start, slot_end=slot_end,
                                       estimated_tons=estimated_tons)
    return confirm_booking(booking["id"])


# ---------------------------------------------------------------------------
# Tier 2: world builders (campaign + member + station [+ pile])
# ---------------------------------------------------------------------------

def setup_world(base_price_cents_per_ton=DEFAULT_BASE_PRICE_CENTS_PER_TON,
                haul_distance_miles=22.5, member_code="M-1001",
                station_capacity_tons=1000, pile_capacity_tons=200,
                with_pile=True) -> dict:
    """Campaign + one member + one station (+ one pile). Returns a dict world."""
    campaign = create_campaign(base_price_cents_per_ton=base_price_cents_per_ton)
    member = create_member(member_code=member_code, haul_distance_miles=haul_distance_miles)
    station = create_station(booking_capacity_tons=station_capacity_tons)
    world = {"campaign": campaign, "member": member, "station": station}
    if with_pile:
        world["pile"] = create_pile(station["id"], capacity_tons=pile_capacity_tons)
    return world


# ---------------------------------------------------------------------------
# Tier 3: ticket lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_weighed_ticket(booking_id: str, gross_weight_lbs=80000,
                          tare_weight_lbs=32000, clock=WEIGH_CLOCK_AM) -> dict:
    """Set the logical clock inside the booking's weigh window, create a ticket
    against the booking, and weigh it. Returns the WEIGHED ticket."""
    set_logical_clock(clock)
    ticket = get_success_data(
        api_client.create_ticket(create_ticket_payload(booking_id), OPERATOR))
    weighed = api_client.weigh_ticket(
        ticket["id"], weigh_payload(gross_weight_lbs, tare_weight_lbs), OPERATOR)
    return get_success_data(weighed)


def collect_sample(ticket_id: str, sample_type: str) -> dict:
    return get_success_data(
        api_client.create_sample(create_sample_payload(ticket_id, sample_type),
                                 make_quality_tech_headers(QT_ALICE)))


def record_sample(sample_id: str, sugar_pct: float, trash_pct: float,
                  recorder=QT_ALICE) -> dict:
    return get_success_data(api_client.record_sample_result(
        sample_id, record_result_payload(sugar_pct, trash_pct),
        make_quality_tech_headers(recorder)))


def verify_sample(sample_id: str, verifier=QT_BOB) -> dict:
    return get_success_data(
        api_client.verify_sample(sample_id, make_quality_tech_headers(verifier)))


def add_recorded_sample(ticket_id: str, sample_type: str, sugar_pct: float,
                        trash_pct: float, recorder=QT_ALICE) -> dict:
    """Collect + record in one step. Returns the RESULT_RECORDED sample."""
    sample = collect_sample(ticket_id, sample_type)
    return record_sample(sample["id"], sugar_pct, trash_pct, recorder=recorder)


def add_verified_lab_sample(ticket_id: str, sugar_pct: float, trash_pct: float,
                            recorder=QT_ALICE, verifier=QT_BOB) -> dict:
    """Collect + record + verify a LAB_VERIFY sample. Returns the VERIFIED sample."""
    sample = add_recorded_sample(ticket_id, "LAB_VERIFY", sugar_pct, trash_pct,
                                 recorder=recorder)
    return verify_sample(sample["id"], verifier=verifier)


def make_sampled_ticket(booking_id: str, gross_weight_lbs=80000, tare_weight_lbs=32000,
                        clock=WEIGH_CLOCK_AM, sugar_pct=16.50, trash_pct=4.50,
                        sample_type="STATION_QUICK", recorder=QT_ALICE) -> tuple:
    """Ticket driven CREATED -> WEIGHED -> SAMPLED via one recorded sample.
    Returns (ticket_dict_fetched_after_sampling, sample)."""
    ticket = create_weighed_ticket(booking_id, gross_weight_lbs, tare_weight_lbs, clock)
    sample = add_recorded_sample(ticket["id"], sample_type, sugar_pct, trash_pct,
                                 recorder=recorder)
    ticket = get_success_data(api_client.get_ticket(ticket["id"], ACCOUNTANT))
    return ticket, sample


def accept_ticket(ticket_id: str, pile_id: str) -> dict:
    return get_success_data(
        api_client.accept_ticket(ticket_id, accept_payload(pile_id), OPERATOR))


def make_accepted_ticket(booking_id: str, pile_id: str, gross_weight_lbs=80000,
                         tare_weight_lbs=32000, clock=WEIGH_CLOCK_AM,
                         sugar_pct=16.10, trash_pct=4.40,
                         quick_first: tuple = None) -> dict:
    """Drive a ticket to ACCEPTED: weigh, optional STATION_QUICK sample first
    (sets the provisional basis), then a verified LAB_VERIFY sample, then accept
    into the pile. Returns the ACCEPTED ticket."""
    ticket = create_weighed_ticket(booking_id, gross_weight_lbs, tare_weight_lbs, clock)
    if quick_first is not None:
        add_recorded_sample(ticket["id"], "STATION_QUICK", quick_first[0], quick_first[1])
    add_verified_lab_sample(ticket["id"], sugar_pct, trash_pct)
    return accept_ticket(ticket["id"], pile_id)


# ---------------------------------------------------------------------------
# Tier 4: pool / credit / installment helpers
# ---------------------------------------------------------------------------

def open_pool_accrual(campaign_id: str, estimated_pool_value_cents: int) -> dict:
    pool = get_campaign_pool(campaign_id)
    return get_success_data(api_client.open_pool_accrual(
        pool["id"], open_accrual_payload(estimated_pool_value_cents), ACCOUNTANT))


def credit_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.credit_ticket(ticket_id, ACCOUNTANT))


def create_installment(pool: dict, pct_of_estimated) -> dict:
    """Create an installment with the pool's CURRENT version (OCC)."""
    fresh = get_success_data(api_client.get_pool(pool["id"], ACCOUNTANT))
    return get_success_data(api_client.create_pool_installment(
        pool["id"],
        create_installment_payload(pct_of_estimated, fresh["version"]),
        ACCOUNTANT))


def issue_installment(installment_id: str) -> dict:
    return get_success_data(api_client.issue_installment(installment_id, ACCOUNTANT))


def list_ledger_entries(**params) -> list:
    return get_success_data(api_client.list_ledger_entries(ACCOUNTANT, params=params))


# ---------------------------------------------------------------------------
# Tier 4b: pile seal / reclaim / loss helpers
# ---------------------------------------------------------------------------

def seal_pile(pile_id: str, clock=None) -> dict:
    if clock is not None:
        set_logical_clock(clock)
    return get_success_data(api_client.seal_pile(pile_id, OPERATOR))


def reclaim_pile(pile_id: str, shipped_lbs) -> dict:
    """SEALED -> RECLAIMING -> EMPTY (no open blackout windows assumed)."""
    get_success_data(api_client.begin_reclaim_pile(pile_id, OPERATOR))
    return get_success_data(api_client.complete_reclaim_pile(
        pile_id, complete_reclaim_payload(shipped_lbs), OPERATOR))


def create_loss_event(pile_id: str, method: str, survey_at: str,
                      window_start: str, window_end: str,
                      measured_remaining_lbs=None) -> dict:
    overrides = {}
    if measured_remaining_lbs is not None:
        overrides["measured_remaining_lbs"] = measured_remaining_lbs
    return get_success_data(api_client.create_loss_event(
        create_loss_event_payload(pile_id, method, survey_at, window_start, window_end,
                                  **overrides),
        OPERATOR))


# ---------------------------------------------------------------------------
# Tier 5: full-lifecycle composite worlds
# ---------------------------------------------------------------------------

def setup_accepted_world(gross_weight_lbs=80000, tare_weight_lbs=32000,
                         sugar_pct=16.10, trash_pct=4.40, quick_first=None,
                         estimated_tons=30, base_price_cents_per_ton=5500,
                         pile_capacity_tons=200, station_capacity_tons=1000,
                         haul_distance_miles=22.5, member_code="M-1001") -> dict:
    """World with one booking CONFIRMED -> IN_USE -> COMPLETED and one ticket
    ACCEPTED into the pile. Returns world incl. booking/ticket/pool."""
    world = setup_world(base_price_cents_per_ton=base_price_cents_per_ton,
                        haul_distance_miles=haul_distance_miles,
                        member_code=member_code,
                        station_capacity_tons=station_capacity_tons,
                        pile_capacity_tons=pile_capacity_tons)
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        slot_start=SLOT_AM_START, slot_end=SLOT_AM_END, estimated_tons=estimated_tons)
    ticket = make_accepted_ticket(
        booking["id"], world["pile"]["id"],
        gross_weight_lbs=gross_weight_lbs, tare_weight_lbs=tare_weight_lbs,
        clock=WEIGH_CLOCK_AM, sugar_pct=sugar_pct, trash_pct=trash_pct,
        quick_first=quick_first)
    world.update({"booking": booking, "ticket": ticket,
                  "pool": get_campaign_pool(world["campaign"]["id"])})
    return world


def setup_credited_world(estimated_pool_value_cents=700000, **kwargs) -> dict:
    """Accepted world + pool ACCRUING + ticket CREDITED."""
    world = setup_accepted_world(**kwargs)
    world["pool"] = open_pool_accrual(world["campaign"]["id"], estimated_pool_value_cents)
    world["ticket"] = credit_ticket(world["ticket"]["id"])
    return world


def setup_single_member_closed_pool(estimated_pool_value_cents=700000,
                                    gross_pool_value_cents=1000000,
                                    sugar_pct=16.10, trash_pct=4.40,
                                    gross_weight_lbs=80000, tare_weight_lbs=32000,
                                    quick_first=None, haul_distance_miles=22.5,
                                    base_price_cents_per_ton=5500) -> dict:
    """Full single-member lifecycle through pool CLOSED and settlements DRAFT:
    accepted -> credited -> pile sealed/reclaimed -> campaign closed -> pool closed
    -> settlements generated. Returns world incl. settlement (single element)."""
    world = setup_credited_world(
        estimated_pool_value_cents=estimated_pool_value_cents,
        gross_weight_lbs=gross_weight_lbs, tare_weight_lbs=tare_weight_lbs,
        sugar_pct=sugar_pct, trash_pct=trash_pct, quick_first=quick_first,
        haul_distance_miles=haul_distance_miles,
        base_price_cents_per_ton=base_price_cents_per_ton)
    ticket = get_success_data(api_client.get_ticket(world["ticket"]["id"], ACCOUNTANT))
    shipped = ticket["adjusted_net_lbs_final"]
    seal_pile(world["pile"]["id"], clock="2026-10-02T09:00:00Z")
    reclaim_pile(world["pile"]["id"], shipped)
    get_success_data(api_client.close_campaign(world["campaign"]["id"], ADMIN))
    world["pool"] = get_success_data(api_client.close_pool(
        world["pool"]["id"], close_pool_payload(gross_pool_value_cents), ACCOUNTANT))
    settlements = get_success_data(api_client.generate_settlements(
        generate_settlements_payload(world["campaign"]["id"]), ACCOUNTANT))
    assert len(settlements) == 1, "Setup failed: expected exactly one settlement"
    world["settlement"] = settlements[0]
    return world


def setup_disputed_settlement(**kwargs) -> dict:
    """Single-member world through settlement ISSUED then DISPUTED by the owner.
    Returns world; settlement versions for OCC are available on the returned
    world['settlement_issued_version'] and world['settlement_disputed_version']."""
    world = setup_single_member_closed_pool(**kwargs)
    issued = get_success_data(
        api_client.issue_settlement(world["settlement"]["id"], ACCOUNTANT))
    disputed = get_success_data(api_client.dispute_settlement(
        issued["id"], {"reason": "review"}, make_member_headers(world["member"]["id"])))
    world["settlement_issued_version"] = issued["version"]
    world["settlement_disputed_version"] = disputed["version"]
    world["settlement"] = disputed
    return world


def setup_two_member_credited_world() -> dict:
    """Two members, two tickets, both CREDITED; pool ACCRUING at 700000.

    M1 (haul 22.5): booking 08:00-10:00, ticket weighed 80000/32000, STATION_QUICK
    16.50/4.50 recorded first (provisional basis), then LAB_VERIFY 16.10/4.40
    verified; accepted (47328 lbs).
    M2 (haul 12.0): booking 10:00-12:00, ticket weighed 64000/32000, LAB_VERIFY
    17.20/2.00 verified; accepted (32000 lbs).
    """
    campaign = create_campaign(name="C-2M")
    m1 = create_member(name="M1", member_code="M-1001", haul_distance_miles=22.5)
    m2 = create_member(name="M2", member_code="M-1002", haul_distance_miles=12.0)
    station = create_station(booking_capacity_tons=1000)
    pile = create_pile(station["id"], capacity_tons=200)

    b1 = create_confirmed_booking(campaign["id"], station["id"], m1["id"],
                                  slot_start=SLOT_AM_START, slot_end=SLOT_AM_END,
                                  estimated_tons=30)
    b2 = create_confirmed_booking(campaign["id"], station["id"], m2["id"],
                                  slot_start=SLOT_PM_START, slot_end=SLOT_PM_END,
                                  estimated_tons=20)

    t1 = make_accepted_ticket(b1["id"], pile["id"], gross_weight_lbs=80000,
                              tare_weight_lbs=32000, clock=WEIGH_CLOCK_AM,
                              sugar_pct=16.10, trash_pct=4.40,
                              quick_first=(16.50, 4.50))
    t2 = make_accepted_ticket(b2["id"], pile["id"], gross_weight_lbs=64000,
                              tare_weight_lbs=32000, clock=WEIGH_CLOCK_PM,
                              sugar_pct=17.20, trash_pct=2.00)

    pool = open_pool_accrual(campaign["id"], 700000)
    t1 = credit_ticket(t1["id"])
    t2 = credit_ticket(t2["id"])

    return {"campaign": campaign, "m1": m1, "m2": m2, "station": station,
            "pile": pile, "b1": b1, "b2": b2, "t1": t1, "t2": t2, "pool": pool}


def setup_two_ticket_credited_world(gross_weight_lbs=72050, tare_weight_lbs=32000,
                                    sugar_pct=16.00, trash_pct=2.00,
                                    haul_distance_miles=22.5,
                                    estimated_pool_value_cents=700000,
                                    estimated_tons=25) -> dict:
    """One member, two identical bookings/tickets, both ACCEPTED into one pile
    and CREDITED; pool ACCRUING. Used for per-ticket rounding-order checks."""
    world = setup_world(haul_distance_miles=haul_distance_miles,
                        station_capacity_tons=1000, pile_capacity_tons=500)
    b1 = create_confirmed_booking(world["campaign"]["id"], world["station"]["id"],
                                  world["member"]["id"],
                                  slot_start=SLOT_AM_START, slot_end=SLOT_AM_END,
                                  estimated_tons=estimated_tons)
    b2 = create_confirmed_booking(world["campaign"]["id"], world["station"]["id"],
                                  world["member"]["id"],
                                  slot_start=SLOT_PM_START, slot_end=SLOT_PM_END,
                                  estimated_tons=estimated_tons)
    t1 = make_accepted_ticket(b1["id"], world["pile"]["id"],
                              gross_weight_lbs=gross_weight_lbs,
                              tare_weight_lbs=tare_weight_lbs, clock=WEIGH_CLOCK_AM,
                              sugar_pct=sugar_pct, trash_pct=trash_pct)
    t2 = make_accepted_ticket(b2["id"], world["pile"]["id"],
                              gross_weight_lbs=gross_weight_lbs,
                              tare_weight_lbs=tare_weight_lbs, clock=WEIGH_CLOCK_PM,
                              sugar_pct=sugar_pct, trash_pct=trash_pct)
    world["pool"] = open_pool_accrual(world["campaign"]["id"], estimated_pool_value_cents)
    world["b1"], world["b2"] = b1, b2
    world["t1"] = credit_ticket(t1["id"])
    world["t2"] = credit_ticket(t2["id"])
    return world


def close_campaign_and_pool(world: dict, gross_pool_value_cents: int,
                            shipped_lbs=None, seal_clock="2026-10-02T09:00:00Z") -> dict:
    """Seal + reclaim the world's pile, close the campaign, close the pool.
    shipped_lbs defaults to the pile's current stored_lbs."""
    pile = get_success_data(api_client.get_pile(world["pile"]["id"], ACCOUNTANT))
    if shipped_lbs is None:
        shipped_lbs = pile["stored_lbs"]
    seal_pile(world["pile"]["id"], clock=seal_clock)
    reclaim_pile(world["pile"]["id"], shipped_lbs)
    get_success_data(api_client.close_campaign(world["campaign"]["id"], ADMIN))
    world["pool"] = get_success_data(api_client.close_pool(
        world["pool"]["id"], close_pool_payload(gross_pool_value_cents), ACCOUNTANT))
    return world
